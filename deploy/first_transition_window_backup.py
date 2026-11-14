"""Window backup provider of the first transition (A8): fresh dump, restore and clone replay.

``WindowBackup`` is the ``backup_proof`` injected into
first_transition_orchestrator.assemble. Called once per window, after quiescence:

1. dumps the SOURCE with a digest-pinned ``pg_dump`` image in a throwaway container
   (custom format, ``--lock-wait-timeout``), streamed into a NEW 0600 file of an exclusive
   0700 run directory; the source URL travels only in the child environment (``-e NAME``),
   never in argv, output, exceptions or the receipt;
2. starts a disposable clone cluster from a digest-pinned image in a NEW ``--internal``
   Docker network (no egress), mirrors the source role NAMES only (NOLOGIN NOINHERIT, no password),
   restores with ``pg_restore --exit-on-error --single-transaction`` and requires the
   restored ledger and catalog fingerprint (first_transition_database.Q_CATALOG) to equal
   the expected baseline before any replay (``restore_verified``);
3. replays the pending migrations on the clone through the orchestrator's
   MigrationExecutor (exact pinned migrate.py bytes, one per invocation), then records the
   final ledger, invalid indexes and catalog fingerprint;
4. removes ONLY its own clone container and network (named and labelled by the run id),
   also on failure; the dump stays as the window backup and ``backup_id`` is its SHA-256.

The receipt satisfies first_transition_adapter.validate_clone_receipt and binds the
``request_digest`` of the journaled request. The clone holds real data only while it runs
inside the protected host; nothing is copied elsewhere. Errors are fixed codes; command
output is discarded or bounded and never enters exceptions or receipts. Nothing runs at
import or construction.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import tempfile
import time

import first_transition_database as fdb
from first_transition_adapter import Plan, digest
from first_transition_host_driver import _absolute
from first_transition_orchestrator import BACKUP_REQUEST_SCHEMA, MigrationExecutor, ProcessRunner
from initial_transition_ops import Refused, require

RECEIPT_SCHEMA = 'igreja12.first-transition-window-backup/1'
# A rehearsal request is never journaled, so its receipt can never attest a window request.
REHEARSAL_SCHEMA = 'igreja12.first-transition-window-backup-rehearsal/1'
REQUEST_SCHEMAS = (BACKUP_REQUEST_SCHEMA, REHEARSAL_SCHEMA)
PINNED_IMAGE = re.compile(r'[a-z0-9][a-z0-9./_-]{0,200}@sha256:[0-9a-f]{64}')
ROLE = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,62}')
ARG = re.compile(r'[A-Za-z0-9_./=:,+-]{1,256}')
SOURCE_ENV = 'PGDUMP_URL'
CLONE_ENV = 'POSTGRES_PASSWORD'
CLONE_USER_ENV = 'POSTGRES_USER'
RESTORE_ENV = 'PGPASSWORD'
CLONE_DB = 'window_clone'
APPLICATOR_STATEMENT_TIMEOUT = '2min'
RUNTIME_ROLE_NAMES = (
    'anon',
    'authenticated',
    'private_send_runtime',
    'private_storage_runtime',
    'private_summary_runtime',
    'queue_worker_runtime',
    'service_role',
)
Q_SOURCE_ROLES = "SELECT rolname FROM pg_roles WHERE rolname !~ '^pg_' ORDER BY oid, rolname COLLATE \"C\""
Q_SOURCE_EXTENSIONS = (
    "SELECT e.extname::text, r.rolname::text FROM pg_extension e "
    "JOIN pg_roles r ON r.oid = e.extowner "
    "JOIN pg_namespace n ON n.oid = e.extnamespace "
    "WHERE n.nspname = 'public' ORDER BY e.extname COLLATE \"C\""
)
Q_SOURCE_TRUSTED_EXTENSION_OWNER = (
    "SELECT CASE WHEN r.rolsuper THEN r.rolname::text "
    "ELSE (SELECT b.rolname::text FROM pg_roles b WHERE b.oid = 10) END "
    "FROM pg_roles r WHERE r.rolname = current_user"
)
Q_ALIGN_EXTENSION_OWNERS = """
DO $$
DECLARE
    v_ext text := nullif(current_setting('igreja12.ext_name', true), '');
    v_from_owner text := nullif(current_setting('igreja12.ext_from_owner', true), '');
    v_owner text := current_setting('igreja12.ext_owner');
    rec record;
    acl record;
BEGIN
    FOR rec IN
        SELECT p.oid::regprocedure AS sig, p.proacl IS NULL AS acl_null
        FROM pg_depend d
        JOIN pg_extension e ON e.oid = d.refobjid
        JOIN pg_proc p ON p.oid = d.objid
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE d.deptype = 'e' AND n.nspname = 'public'
          AND (v_ext IS NULL OR e.extname = v_ext)
          AND (v_from_owner IS NULL OR p.proowner = v_from_owner::regrole)
          AND p.proowner <> v_owner::regrole
        ORDER BY 1
    LOOP
        EXECUTE format('ALTER FUNCTION %s OWNER TO %I', rec.sig, v_owner);
        IF v_from_owner IS NOT NULL AND rec.acl_null THEN
            EXECUTE format('SET LOCAL ROLE %I', v_owner);
            FOR acl IN
                SELECT r.rolname AS grantee, a.privilege_type, a.is_grantable
                FROM pg_default_acl d
                CROSS JOIN LATERAL aclexplode(d.defaclacl) a
                JOIN pg_roles r ON r.oid = a.grantee
                WHERE d.defaclrole = v_owner::regrole
                  AND d.defaclnamespace IN (0, 'public'::regnamespace)
                  AND d.defaclobjtype = 'f'
            LOOP
                EXECUTE format(
                    'GRANT %s ON FUNCTION %s TO %I%s',
                    acl.privilege_type, rec.sig, acl.grantee,
                    CASE WHEN acl.is_grantable THEN ' WITH GRANT OPTION' ELSE '' END
                );
            END LOOP;
            RESET ROLE;
        END IF;
    END LOOP;
    FOR rec IN
        SELECT t.oid::regtype AS typ, t.typacl IS NULL AS acl_null
        FROM pg_depend d
        JOIN pg_extension e ON e.oid = d.refobjid
        JOIN pg_type t ON t.oid = d.objid
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE d.deptype = 'e' AND n.nspname = 'public'
          AND (v_ext IS NULL OR e.extname = v_ext)
          AND (v_from_owner IS NULL OR t.typowner = v_from_owner::regrole)
          AND t.typowner <> v_owner::regrole
          AND (t.typelem = 0 OR NOT EXISTS (
              SELECT 1 FROM pg_type e2 WHERE e2.oid = t.typelem AND e2.typarray = t.oid
          ))
        ORDER BY 1
    LOOP
        EXECUTE format('ALTER TYPE %s OWNER TO %I', rec.typ, v_owner);
        IF v_from_owner IS NOT NULL AND rec.acl_null THEN
            EXECUTE format('SET LOCAL ROLE %I', v_owner);
            FOR acl IN
                SELECT r.rolname AS grantee, a.privilege_type, a.is_grantable
                FROM pg_default_acl d
                CROSS JOIN LATERAL aclexplode(d.defaclacl) a
                JOIN pg_roles r ON r.oid = a.grantee
                WHERE d.defaclrole = v_owner::regrole
                  AND d.defaclnamespace IN (0, 'public'::regnamespace)
                  AND d.defaclobjtype = 'T'
            LOOP
                EXECUTE format(
                    'GRANT %s ON TYPE %s TO %I%s',
                    acl.privilege_type, rec.typ, acl.grantee,
                    CASE WHEN acl.is_grantable THEN ' WITH GRANT OPTION' ELSE '' END
                );
            END LOOP;
            RESET ROLE;
        END IF;
    END LOOP;
END
$$;
"""
Q_APPLICATOR_ROLE = (
    "SELECT current_user, current_setting('statement_timeout'), r.rolsuper, r.rolbypassrls, "
    "r.rolcreaterole, r.rolcreatedb, r.rolinherit, r.rolcanlogin, r.rolreplication "
    "FROM pg_roles r WHERE r.rolname = current_user"
)
Q_RUNTIME_ROLES = (
    "SELECT rolname, rolsuper, rolbypassrls, rolcanlogin, rolinherit, rolcreaterole, rolcreatedb "
    "FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'private_send_runtime', "
    "'private_storage_runtime', 'private_summary_runtime', 'queue_worker_runtime', 'service_role') "
    'ORDER BY rolname COLLATE "C"'
)
Q_RUNTIME_TABLE_PRIVS = (
    "SELECT c.relname::text, c.relrowsecurity, c.relforcerowsecurity, "
    "coalesce(ARRAY(SELECT DISTINCT r::regrole::text FROM pg_policy p, LATERAL unnest(p.polroles) r "
    "WHERE p.polrelid = c.oid ORDER BY 1), ARRAY[]::text[]), "
    "(has_any_column_privilege('anon', c.oid, 'SELECT,INSERT,UPDATE') OR has_table_privilege('anon', c.oid, 'DELETE')), "
    "(has_any_column_privilege('service_role', c.oid, 'SELECT,INSERT,UPDATE') "
    "OR has_table_privilege('service_role', c.oid, 'DELETE')), "
    "has_table_privilege('authenticated', c.oid, 'SELECT'), "
    "has_any_column_privilege('authenticated', c.oid, 'INSERT'), "
    "has_any_column_privilege('authenticated', c.oid, 'UPDATE'), "
    "has_table_privilege('authenticated', c.oid, 'DELETE'), "
    "(has_any_column_privilege('private_storage_runtime', c.oid, 'SELECT,INSERT,UPDATE') "
    "OR has_table_privilege('private_storage_runtime', c.oid, 'DELETE')), "
    "(has_any_column_privilege('private_send_runtime', c.oid, 'SELECT,INSERT,UPDATE') "
    "OR has_table_privilege('private_send_runtime', c.oid, 'DELETE')), "
    "(has_any_column_privilege('private_summary_runtime', c.oid, 'SELECT,INSERT,UPDATE') "
    "OR has_table_privilege('private_summary_runtime', c.oid, 'DELETE')), "
    "(has_any_column_privilege('queue_worker_runtime', c.oid, 'SELECT,INSERT,UPDATE') "
    "OR has_table_privilege('queue_worker_runtime', c.oid, 'DELETE')), "
    "CASE WHEN c.relname = 'cell_alerts' "
    "THEN has_column_privilege('authenticated', c.oid, 'tratado', 'UPDATE') ELSE true END, "
    "CASE WHEN c.relname = 'cell_alerts' "
    "THEN has_column_privilege('authenticated', c.oid, 'igreja_id', 'UPDATE') ELSE false END, "
    "CASE WHEN c.relname = 'private_deletion_uploads' "
    "THEN has_table_privilege('private_storage_runtime', c.oid, 'SELECT') "
    "AND has_table_privilege('private_storage_runtime', c.oid, 'DELETE') "
    "AND has_any_column_privilege('private_storage_runtime', c.oid, 'UPDATE') "
    "AND NOT has_any_column_privilege('private_storage_runtime', c.oid, 'INSERT') ELSE false END, "
    "CASE WHEN c.relname = 'private_summary_tasks' "
    "THEN has_table_privilege('private_summary_runtime', c.oid, 'SELECT') "
    "AND has_any_column_privilege('private_summary_runtime', c.oid, 'UPDATE') "
    "AND NOT has_any_column_privilege('private_summary_runtime', c.oid, 'INSERT') "
    "AND NOT has_table_privilege('private_summary_runtime', c.oid, 'DELETE') ELSE false END "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relname IN ("
    "'cell_alerts', 'celula_alerta_regras', 'private_deletion_uploads', 'private_summary_tasks') "
    'ORDER BY c.relname COLLATE "C"'
)
CLONE_DUMP = '/tmp/igreja12-window.dump'
CLONE_LIST = '/tmp/igreja12-window.list'
MAX_LIST = 8 << 20
STDERR_BOUND = 65536
# pg_restore -l entry: "<dump id>; <catalog oid> <oid> <DESC> <namespace|-> <tag...> <owner|->"
# The owner can be EMPTY (EXTENSION and its COMMENT on Supabase): the line then ends in a bare space,
# e.g. "5; 3079 16608 EXTENSION - supabase_vault ". Hence the optional owner is ``(?: \S*)?``, not ``(?: \S+)?``.
TOC_ENTRY = re.compile(r'(\d+); \d+ \d+ (.+)')
TOC_VAULT_EXTENSION = re.compile(r'(?:EXTENSION - supabase_vault|COMMENT - EXTENSION supabase_vault)(?: \S*)?')
# Any entry whose namespace is the vault schema (TABLE DATA, SEQUENCE SET, ACL, COMMENT, ...). The namespace is the
# token right after a DESC from a fixed vocabulary, so ``TABLE public vault_notes`` and ``TABLE DATA SALES vault x``
# are NOT matched.
NAMESPACED_KINDS = ('TABLE DATA', 'SEQUENCE SET', 'SEQUENCE OWNED BY', 'SEQUENCE', 'TABLE', 'MATERIALIZED VIEW DATA',
                    'MATERIALIZED VIEW', 'VIEW', 'FOREIGN TABLE', 'FUNCTION', 'PROCEDURE', 'AGGREGATE', 'TYPE', 'DOMAIN',
                    'ACL', 'DEFAULT ACL', 'COMMENT', 'SECURITY LABEL', 'FK CONSTRAINT', 'CHECK CONSTRAINT',
                    'CONSTRAINT', 'INDEX', 'TRIGGER', 'POLICY', 'ROW SECURITY', 'DEFAULT', 'RULE', 'OPERATOR',
                    'STATISTICS', 'COLLATION', 'CAST')
TOC_VAULT_SCHEMA = re.compile('(?:' + '|'.join(re.escape(k) for k in sorted(NAMESPACED_KINDS, key=len, reverse=True))
                              + r') (?:vault .*|- SCHEMA vault(?: \S*)?)')
EXCLUDED_KEYS = ('event_trigger_names', 'event_triggers', 'vault_extension', 'vault_schema')
TOC_EVENT_TRIGGER = re.compile(r'EVENT TRIGGER - (\S+) (\S+)')
TOC_EVENT_COMMENT = re.compile(r'COMMENT - EVENT TRIGGER (\S+)(?: \S*)?')
# Fixed vocabulary of the object kind that stopped pg_restore (never a name, value or message text).
RESTORE_KINDS = ('EXTENSION', 'EVENT TRIGGER', 'PUBLICATION TABLE', 'PUBLICATION', 'SCHEMA', 'TABLE DATA', 'TABLE',
                 'FUNCTION', 'PROCEDURE', 'TRIGGER', 'VIEW', 'MATERIALIZED VIEW', 'POLICY', 'INDEX', 'FK CONSTRAINT',
                 'CONSTRAINT', 'SEQUENCE', 'TYPE', 'DOMAIN', 'ACL', 'DEFAULT ACL', 'COMMENT', 'OWNER', 'RULE',
                 'AGGREGATE', 'COLLATION', 'CAST', 'FOREIGN TABLE', 'SERVER', 'FOREIGN DATA WRAPPER', 'ROW SECURITY',
                 'SEQUENCE OWNED BY', 'SEQUENCE SET', 'DEFAULT', 'STATISTICS', 'OPERATOR', 'SECURITY LABEL')
TOC_ERROR = re.compile(rb'from TOC entry \d+; \d+ \d+ (' + b'|'.join(
    re.escape(k.encode()) for k in sorted(RESTORE_KINDS, key=len, reverse=True)) + rb') ')
TIMEOUTS = {'dump_s': 1800, 'ready_s': 180, 'restore_s': 1800, 'migration_s': 300, 'max_migration_s': 60,
            'docker_s': 120}


@dataclass(frozen=True)
class WindowBackupConfig:
    """Public values only (no URL or password): where and with which pinned images to work."""
    docker_binary: str
    docker_endpoint: str
    docker_config_dir: str
    backup_root: str
    clone_workdir: str
    python: str
    dump_image: str
    clone_image: str
    clone_command: tuple = ()
    dump_network: str = 'bridge'
    admin_user: str = 'clone_admin'
    restore_user: str = 'clone_admin'
    migration_user: str = 'postgres'
    clone_superusers: tuple = ()
    # Optional pin of what filter_restore_list must remove (copied from the V9 receipt's ``restore_excluded``).
    # Optional for rehearse-backup; REQUIRED for the window request. Stored as sorted (key, value) pairs.
    restore_excluded_expected: tuple = ()
    timeouts: tuple = tuple(sorted(TIMEOUTS.items()))

    def validated(self):
        require(all(_absolute(p) for p in (self.docker_binary, self.docker_config_dir, self.backup_root,
                                           self.clone_workdir, self.python))
                and isinstance(self.docker_endpoint, str) and self.docker_endpoint.startswith('unix:///')
                and _absolute(self.docker_endpoint.removeprefix('unix://')), 'window-backup-paths')
        require(all(isinstance(i, str) and PINNED_IMAGE.fullmatch(i) for i in (self.dump_image, self.clone_image)),
                'window-backup-image-unpinned')
        require(type(self.clone_command) is tuple and len(self.clone_command) <= 16
                and all(isinstance(a, str) and ARG.fullmatch(a) for a in self.clone_command), 'window-backup-command')
        require(self.dump_network in ('bridge', 'host'), 'window-backup-network')
        require(all(isinstance(r, str) and ROLE.fullmatch(r) for r in (self.admin_user, self.restore_user,
                                                                         self.migration_user, *self.clone_superusers))
                and type(self.clone_superusers) is tuple
                and self.migration_user not in (self.admin_user, self.restore_user, *self.clone_superusers),
                'window-backup-roles')
        pairs = self.restore_excluded_expected
        require(type(pairs) is tuple and all(type(p) is tuple and len(p) == 2 and isinstance(p[0], str) for p in pairs),
                'window-backup-restore-excluded')
        pinned = dict(pairs)
        require(type(self.restore_excluded_expected) is tuple
                and (not pinned or (set(pinned) == set(EXCLUDED_KEYS)
                                    and all(type(pinned[k]) is int and 0 <= pinned[k] <= 64
                                            for k in ('event_triggers', 'vault_extension', 'vault_schema'))
                                    and type(pinned['event_trigger_names']) is tuple
                                    and pinned['event_trigger_names'] == tuple(sorted(set(pinned['event_trigger_names'])))
                                    and all(isinstance(n, str) and ROLE.fullmatch(n)
                                            for n in pinned['event_trigger_names']))),
                'window-backup-restore-excluded')
        values = dict(self.timeouts)
        require(type(self.timeouts) is tuple and set(values) == set(TIMEOUTS)
                and all(type(v) is int and 0 < v <= 3600 for v in values.values()), 'window-backup-timeouts')
        return self

    def timeout(self, key):
        return dict(self.timeouts)[key]

    @classmethod
    def from_dict(cls, data):
        """Unknown keys (a password, a URL) refuse."""
        fields = set(cls.__dataclass_fields__)
        require(isinstance(data, dict) and set(data) <= fields and {
            'docker_binary', 'docker_endpoint', 'docker_config_dir', 'backup_root', 'clone_workdir', 'python',
            'dump_image',
            'clone_image'} <= set(data), 'window-backup-config-keys')
        values = dict(data)
        for key in ('clone_command', 'clone_superusers'):
            if key in values:
                require(isinstance(values[key], list), 'window-backup-config-keys')
                values[key] = tuple(values[key])
        if 'restore_excluded_expected' in values:
            pinned = values['restore_excluded_expected']
            require(isinstance(pinned, dict) and set(pinned) == set(EXCLUDED_KEYS)
                    and isinstance(pinned['event_trigger_names'], list), 'window-backup-restore-excluded')
            values['restore_excluded_expected'] = tuple(sorted(
                (k, tuple(v) if isinstance(v, list) else v) for k, v in pinned.items()))
        if 'timeouts' in values:
            require(isinstance(values['timeouts'], dict) and set(values['timeouts']) <= set(TIMEOUTS),
                    'window-backup-timeouts')
            values['timeouts'] = tuple(sorted({**TIMEOUTS, **values['timeouts']}.items()))
        return cls(**values).validated()


def source_role_names(connect, *, timeout=10):
    """Role NAMES of the source (no attributes, memberships or passwords), via a read-only connection."""
    conn = connect(timeout=timeout)
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(fdb.Q_BEGIN)
        try:
            cur.execute(fdb.Q_TIMEOUT, (f'{int(timeout * 1000)}ms',))
            cur.fetchall()
            cur.execute(Q_SOURCE_ROLES)
            names = tuple(row[0] for row in cur.fetchall())
        finally:
            cur.execute('ROLLBACK')
    finally:
        conn.close()
    require(names and all(isinstance(n, str) and ROLE.fullmatch(n) for n in names), 'window-backup-source-roles')
    return names


def source_public_extensions(connect, *, timeout=10):
    """Extension (name, owner) pairs in schema ``public`` so clone restore preserves non-restore extension owners."""
    conn = connect(timeout=timeout)
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(fdb.Q_BEGIN)
        try:
            cur.execute(fdb.Q_TIMEOUT, (f'{int(timeout * 1000)}ms',))
            cur.fetchall()
            cur.execute(Q_SOURCE_EXTENSIONS)
            items = tuple((str(row[0]), str(row[1])) for row in cur.fetchall())
        finally:
            cur.execute('ROLLBACK')
    finally:
        conn.close()
    require(all(ROLE.fullmatch(ext) and ROLE.fullmatch(owner) for ext, owner in items), 'window-backup-source-roles')
    return items


def source_trusted_extension_owner(connect, default='postgres', *, timeout=10):
    """Owner that PostgreSQL assigns to trusted-extension members executed on source."""
    require(isinstance(default, str) and ROLE.fullmatch(default), 'window-backup-source-roles')
    conn = connect(timeout=timeout)
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(fdb.Q_BEGIN)
        try:
            cur.execute(fdb.Q_TIMEOUT, (f'{int(timeout * 1000)}ms',))
            cur.fetchall()
            cur.execute(Q_SOURCE_TRUSTED_EXTENSION_OWNER)
            rows = cur.fetchall()
        finally:
            cur.execute('ROLLBACK')
    finally:
        conn.close()
    if rows and rows[0] and rows[0][0] is not None:
        owner = str(rows[0][0])
        require(ROLE.fullmatch(owner), 'window-backup-source-roles')
        return owner
    return default


def clone_state(conn):
    """Clone identity, ledger, invalid indexes and catalog fingerprint in one read-only snapshot."""
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(fdb.Q_BEGIN)
    try:
        cur.execute(fdb.Q_PATH)
        cur.fetchall()
        cur.execute(fdb.Q_IDENTITY)
        rows = cur.fetchall()
        require(len(rows) == 1 and len(rows[0]) >= 3, 'window-backup-clone-shape')
        system, oid, name = rows[0][:3]
        cur.execute(fdb.Q_LEDGER)
        ledger = tuple(row[0] for row in cur.fetchall())
        cur.execute(fdb.Q_INVALID)
        invalid = len(cur.fetchall())
        catalog = fdb._catalog(cur)
    finally:
        cur.execute('ROLLBACK')
    require(all(isinstance(n, str) and fdb.LEDGER_NAME.fullmatch(n) for n in ledger), 'window-backup-clone-shape')
    return dict(identity=(str(system), int(oid), str(name)), ledger=ledger, invalid=invalid, catalog=catalog)


def _psycopg2_clone(*, host, dbname, user, password, timeout):
    import psycopg2
    return psycopg2.connect(host=host, port=5432, dbname=dbname, user=user, password=password,
                            connect_timeout=max(1, int(timeout)), sslmode='disable', options='',
                            application_name='igreja12-window-clone')


def filter_restore_list(listing, superusers):
    """Drop from a ``pg_restore -l`` listing ONLY what a plain PostgreSQL clone cannot restore.

    1. ``supabase_vault`` (EXTENSION and its COMMENT) and the ACL/COMMENT entries inside schema ``vault``:
       the official image has no such extension, whose objects are not in the dump either.
    2. EVENT TRIGGERs (and their COMMENT) owned by a role that is not a clone superuser: PostgreSQL
       refuses ``ALTER EVENT TRIGGER ... OWNER TO`` a non-superuser, and clone roles are mirrored
       as NOLOGIN non-superusers. Event triggers owned by a superuser stay and fire during the replay.
    Everything else (tables, data, policies, functions, publications, the ``public`` objects the catalog
    fingerprint covers) is kept. Returns ``(lines, removed)``; ``removed`` holds counts, plus the sorted NAMES of
    the dropped event triggers (object names, no data) so the rehearsal receipt shows what it did not exercise.
    """
    require(isinstance(listing, str) and isinstance(superusers, (tuple, frozenset)), 'window-backup-restore-list')
    lines = listing.splitlines()
    unsafe = {m.group(1) for line in lines if (e := TOC_ENTRY.fullmatch(line))
              and (m := TOC_EVENT_TRIGGER.fullmatch(e.group(2))) and m.group(2) not in superusers}
    kept, removed = [], dict(vault_extension=0, vault_schema=0, event_triggers=0)
    for line in lines:
        entry = TOC_ENTRY.fullmatch(line)
        # Anything that is neither a comment nor a well-formed entry (e.g. a name with a newline) is not understood.
        require(entry or line.startswith(';') or not line.strip(), 'window-backup-restore-list')
        what = entry.group(2) if entry else ''
        if TOC_VAULT_EXTENSION.fullmatch(what):
            removed['vault_extension'] += 1
        elif TOC_VAULT_SCHEMA.fullmatch(what):
            removed['vault_schema'] += 1
        elif (m := TOC_EVENT_TRIGGER.fullmatch(what)) and m.group(1) in unsafe \
                or (m := TOC_EVENT_COMMENT.fullmatch(what)) and m.group(1) in unsafe:
            removed['event_triggers'] += 1
        else:
            kept.append(line)
    require(any(TOC_ENTRY.fullmatch(line) for line in kept), 'window-backup-restore-list')
    removed['event_trigger_names'] = sorted(unsafe)
    return kept, removed


def restore_error_code(stderr):
    """Reduce pg_restore stderr to ``window-backup-restore-failed[-<kind>]``: only the object kind from the
    first ``from TOC entry`` line, matched against a fixed vocabulary. No message, name or value leaves."""
    match = TOC_ERROR.search(stderr or b'')
    if match:
        return 'window-backup-restore-failed-' + match.group(1).decode('ascii').lower().replace(' ', '-')
    return 'window-backup-restore-failed'


# Every code this module can raise, for first_transition_window.CODES (the entry point hides all others).
BACKUP_CODES = frozenset({
    'window-backup-already-used', 'window-backup-argv', 'window-backup-cleanup-failed', 'window-backup-clone-failed',
    'window-backup-clone-inspect', 'window-backup-clone-is-source', 'window-backup-clone-migration-failed',
    'window-backup-clone-not-ready', 'window-backup-clone-role', 'window-backup-clone-shape', 'window-backup-command',
    'window-backup-config', 'window-backup-config-keys', 'window-backup-dump-failed', 'window-backup-dump-format',
    'window-backup-final-invalid-index', 'window-backup-final-ledger', 'window-backup-image-unpinned',
    'window-backup-migration-slow', 'window-backup-network', 'window-backup-network-failed', 'window-backup-output',
    'window-backup-paths', 'window-backup-plan', 'window-backup-request', 'window-backup-restore-catalog',
    'window-backup-restore-excluded', 'window-backup-restore-failed', 'window-backup-restore-invalid-index',
    'window-backup-restore-ledger', 'window-backup-restore-list', 'window-backup-restore-list-failed',
    'window-backup-roles', 'window-backup-root-missing', 'window-backup-run-exists', 'window-backup-runtime-rls',
    'window-backup-secret', 'window-backup-source-roles', 'window-backup-spawn-failed', 'window-backup-timeout',
    'window-backup-timeouts', 'window-backup-workdir-missing',
    *('window-backup-restore-failed-' + k.lower().replace(' ', '-') for k in RESTORE_KINDS),
})


class WindowBackup:
    """``backup_proof(request) -> receipt`` for exactly one window; see the module docstring.

    ``secret()`` returns the SOURCE URL; ``connect`` is the read-only source connection factory
    (first_transition_database.psycopg2_connector). ``run``/``clone_connect``/``migrate_run``/
    ``sleep``/``clock`` are injection seams for synthetic tests.
    """

    def __init__(self, config, plan, expected, *, secret, connect, run=None, clone_connect=None,
                 migrate_run=None, sleep=None, clock=None):
        require(isinstance(config, WindowBackupConfig), 'window-backup-config')
        require(isinstance(plan, Plan) and isinstance(expected, fdb.DatabaseExpectation), 'window-backup-plan')
        require(callable(secret) and callable(connect), 'window-backup-secret')
        self.config, self.plan, self.expected = config.validated(), plan, expected.validated()
        require(self.expected.ledger == plan.baseline, 'window-backup-plan')
        self.secret, self.connect = secret, connect
        self.run, self.clone_connect, self.migrate_run = run, clone_connect or _psycopg2_clone, migrate_run
        self.sleep, self.clock = sleep or time.sleep, clock or time.monotonic
        self.used = False

    # -- process plumbing -----------------------------------------------------------------------
    def _docker(self, args, *, timeout, env=None, stdin=None, stdout=None, capture=False, stderr_out=False):
        """Docker CLI with explicit config/endpoint, constructed env, no shell; output discarded or bounded."""
        require(type(args) is tuple and args and all(type(a) is str and 0 < len(a) <= 4096 and '\x00' not in a
                                                     for a in args), 'window-backup-argv')
        child_env = dict(PATH='/usr/bin:/bin', LC_ALL='C', **(env or {}))
        argv = [self.config.docker_binary, '--config', self.config.docker_config_dir,
                '--host', self.config.docker_endpoint, *args]
        run = self.run or subprocess.run
        outcome = None
        err_file = tempfile.TemporaryFile() if stderr_out else None  # unnamed, private; read back bounded
        try:
            done = run(argv, stdin=stdin if stdin is not None else subprocess.DEVNULL,
                       stdout=stdout if stdout is not None else (subprocess.PIPE if capture else subprocess.DEVNULL),
                       stderr=err_file if stderr_out else subprocess.DEVNULL, env=child_env, timeout=timeout, close_fds=True, shell=False,
                       check=False)
        except subprocess.TimeoutExpired:
            outcome = 'window-backup-timeout'
        except Exception:
            outcome = 'window-backup-spawn-failed'
        err = b''
        if err_file is not None:
            try:
                err_file.seek(0)
                err = err_file.read(STDERR_BOUND)
            finally:
                err_file.close()
        require(outcome is None, outcome)
        if capture:
            out = getattr(done, 'stdout', b'') or b''
            require(isinstance(out, bytes) and len(out) <= 4096, 'window-backup-output')
            return done.returncode, out.decode('utf-8', 'replace').strip()
        if stderr_out:  # bounded and only ever reduced by restore_error_code; never stored or printed
            return done.returncode, err
        return done.returncode, None

    def _ok(self, args, code, **kwargs):
        rc, out = self._docker(args, timeout=kwargs.pop('timeout', self.config.timeout('docker_s')), **kwargs)
        require(rc == 0, code)
        return out

    # -- steps ----------------------------------------------------------------------------------
    def _run_dir(self, request_digest):
        root = Path(self.config.backup_root)
        require(os.path.lexists(root) and stat.S_ISDIR(os.lstat(root).st_mode) and not root.is_symlink(),
                'window-backup-root-missing')
        run_dir = root / request_digest
        try:
            run_dir.mkdir(mode=0o700)  # exclusive: a window is never re-run into the same directory
        except FileExistsError:
            raise Refused('window-backup-run-exists') from None
        return run_dir

    def _dump(self, run_dir):
        url = self.secret()
        require(isinstance(url, str) and url.startswith('postgresql://') and '\n' not in url, 'window-backup-secret')
        path = run_dir / 'window.dump'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            rc, _ = self._docker(('run', '--rm', '--pull=never', '--network', self.config.dump_network, '-e', SOURCE_ENV,
                                  '-e', 'PGAPPNAME=igreja12-window-backup', self.config.dump_image,
                                  'sh', '-c', 'exec pg_dump "$' + SOURCE_ENV + '" --format=custom '
                                  '--lock-wait-timeout=10s --no-password'),
                                 timeout=self.config.timeout('dump_s'), env={SOURCE_ENV: url}, stdout=handle)
            handle.flush()
            os.fsync(handle.fileno())
        require(rc == 0, 'window-backup-dump-failed')
        data_hash, size = hashlib.sha256(), 0
        with open(path, 'rb') as handle:
            head = handle.read(5)
            require(head == b'PGDMP', 'window-backup-dump-format')
            data_hash.update(head)
            size += len(head)
            for chunk in iter(lambda: handle.read(1 << 20), b''):
                data_hash.update(chunk)
                size += len(chunk)
        return path, data_hash.hexdigest(), size

    def _start_clone(self, name, password):
        self._ok(('network', 'create', '--internal', '--label', 'igreja12.window-backup=' + name, name),
                 'window-backup-network-failed')
        self._ok(('run', '-d', '--pull=never', '--name', name, '--network', name, '--label', 'igreja12.window-backup=' + name,
                  '-e', CLONE_ENV, '-e', CLONE_USER_ENV, self.config.clone_image, *self.config.clone_command),
                 'window-backup-clone-failed', env={CLONE_ENV: password, CLONE_USER_ENV: self.config.admin_user})
        address = self._ok(('inspect', '--format', '{{(index .NetworkSettings.Networks "' + name + '").IPAddress}}',
                            name), 'window-backup-clone-inspect', capture=True)
        require(re.fullmatch(r'(?:\d{1,3}\.){3}\d{1,3}', address or ''), 'window-backup-clone-inspect')
        deadline = self.clock() + self.config.timeout('ready_s')
        while True:
            try:
                conn = self.clone_connect(host=address, dbname='postgres', user=self.config.admin_user,
                                          password=password, timeout=5)
                return address, conn
            except Exception:
                require(self.clock() < deadline, 'window-backup-clone-not-ready')
                self.sleep(2)

    def _prepare_clone(self, admin, roles, password):
        from psycopg2 import sql
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute('SELECT rolname FROM pg_roles')
            existing = {row[0] for row in cur.fetchall()}
            created = 0
            for role in roles:
                if role not in existing:
                    cur.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOINHERIT').format(sql.Identifier(role)))
                    created += 1
            if self.config.migration_user not in existing and self.config.migration_user not in roles:
                cur.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOINHERIT').format(
                    sql.Identifier(self.config.migration_user)))
                created += 1
            for role in self.config.clone_superusers:
                cur.execute(sql.SQL('ALTER ROLE {} SUPERUSER').format(sql.Identifier(role)))
            cur.execute(
                sql.SQL('ALTER ROLE {} WITH NOSUPERUSER INHERIT CREATEROLE CREATEDB NOREPLICATION BYPASSRLS LOGIN '
                        'PASSWORD %s').format(sql.Identifier(self.config.migration_user)),
                (password,),
            )
            cur.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '2min'").format(
                sql.Identifier(self.config.migration_user)))
            # Supabase's postgres role is NOSUPERUSER with ADMIN OPTION on the core client roles
            # (verified against supabase/postgres:17.11.0.018), required on PG16+ for migration 20261030_160000.
            all_roles = existing | set(roles)
            if 'service_role' in all_roles:
                cur.execute('ALTER ROLE service_role BYPASSRLS')
            for client_role in ('anon', 'authenticated', 'service_role'):
                if client_role in all_roles and client_role != self.config.migration_user:
                    cur.execute(sql.SQL('GRANT {} TO {} WITH ADMIN OPTION').format(
                        sql.Identifier(client_role), sql.Identifier(self.config.migration_user)))
            cur.execute(sql.SQL('CREATE DATABASE {} OWNER {} TEMPLATE template0').format(
                sql.Identifier(CLONE_DB), sql.Identifier(self.config.migration_user)))
        return created

    def _prepare_clone_extensions(self, address, password, extensions):
        """Create source ``public`` extensions under their source owner before ``pg_restore``."""
        targets = [(ext, owner) for ext, owner in extensions if owner != self.config.restore_user]
        if not targets:
            return
        from psycopg2 import sql
        conn = self.clone_connect(host=address, dbname=CLONE_DB, user=self.config.admin_user,
                                  password=password, timeout=10)
        try:
            conn.autocommit = False
            with conn.cursor() as cur:
                for ext, owner in targets:
                    cur.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(owner)))
                    cur.execute(sql.SQL('CREATE EXTENSION IF NOT EXISTS {} WITH SCHEMA public').format(
                        sql.Identifier(ext)))
                    cur.execute('RESET ROLE')
                    # Trusted extensions install member functions/types under the bootstrap superuser;
                    # align their owners in public with the source extension owner so pg_restore ACLs match.
                    cur.execute(
                        "SELECT set_config('igreja12.ext_name', %s, true), "
                        "set_config('igreja12.ext_from_owner', '', true), "
                        "set_config('igreja12.ext_owner', %s, true)",
                        (ext, owner),
                    )
                    cur.execute(Q_ALIGN_EXTENSION_OWNERS)
            conn.commit()
        finally:
            conn.close()

    def _align_replay_extensions(self, address, password, trusted_owner):
        """Reassign bootstrap-owned extension members created during replay to match source bootstrap ownership."""
        if trusted_owner == self.config.admin_user:
            return
        conn = self.clone_connect(host=address, dbname=CLONE_DB, user=self.config.admin_user,
                                  password=password, timeout=10)
        try:
            conn.autocommit = False
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT set_config('igreja12.ext_name', '', true), "
                    "set_config('igreja12.ext_from_owner', %s, true), "
                    "set_config('igreja12.ext_owner', %s, true)",
                    (self.config.admin_user, trusted_owner),
                )
                cur.execute(Q_ALIGN_EXTENSION_OWNERS)
            conn.commit()
        finally:
            conn.close()

    def _restore(self, name, path, password, run_dir):
        """Restore with the content list filtered by ``filter_restore_list`` (see there for what and why)."""
        full = run_dir / 'restore-full.list'
        fd = os.open(full, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as out, open(path, 'rb') as dump:
            rc, _ = self._docker(('exec', '-i', name, 'pg_restore', '-l'), timeout=self.config.timeout('restore_s'),
                                 stdin=dump, stdout=out)
        require(rc == 0, 'window-backup-restore-list-failed')
        size = os.lstat(full).st_size
        require(0 < size <= MAX_LIST, 'window-backup-restore-list')
        try:
            listing = full.read_bytes().decode('utf-8')
        except UnicodeError:
            raise Refused('window-backup-restore-list') from None
        superusers = frozenset((self.config.restore_user, *self.config.clone_superusers))
        lines, removed = filter_restore_list(listing, superusers)
        pinned = dict(self.config.restore_excluded_expected)
        # Before anything is copied or restored: a pinned value that differs means the dump changed shape.
        require(not pinned or {**removed, 'event_trigger_names': tuple(removed['event_trigger_names'])} == pinned,
                'window-backup-restore-excluded')
        kept = run_dir / 'restore.list'
        fd = os.open(kept, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write('\n'.join(lines) + '\n')
        # A seekable copy inside the clone: -L restores in list order, which a pipe cannot always serve.
        for source, target, code in ((path, CLONE_DUMP, 'window-backup-restore-failed'),
                                     (kept, CLONE_LIST, 'window-backup-restore-list-failed')):
            with open(source, 'rb') as handle:
                self._ok(('exec', '-i', name, 'sh', '-c', 'umask 077; cat > "$0"', target), code,
                         timeout=self.config.timeout('restore_s'), stdin=handle)
        rc, err = self._docker(('exec', '-e', RESTORE_ENV, name, 'pg_restore', '-h', '127.0.0.1',
                                '-U', self.config.restore_user, '-d', CLONE_DB, '--exit-on-error', '--single-transaction',
                                '--no-password', '-L', CLONE_LIST, CLONE_DUMP),
                               timeout=self.config.timeout('restore_s'), env={RESTORE_ENV: password}, stderr_out=True)
        require(rc == 0, restore_error_code(err))
        return removed

    def _state(self, address, password):
        conn = self.clone_connect(host=address, dbname=CLONE_DB, user=self.config.admin_user,
                                  password=password, timeout=10)
        try:
            return clone_state(conn)
        finally:
            conn.close()

    def _verify_applicator_session(self, address, password):
        """Read actual applicator flags and role-level statement_timeout on a fresh applicator connection."""
        conn = self.clone_connect(host=address, dbname=CLONE_DB, user=self.config.migration_user,
                                  password=password, timeout=10)
        try:
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(fdb.Q_BEGIN)
            try:
                cur.execute(fdb.Q_PATH)
                cur.fetchall()
                cur.execute(Q_APPLICATOR_ROLE)
                rows = cur.fetchall()
            finally:
                cur.execute('ROLLBACK')
        finally:
            conn.close()
        require(len(rows) == 1 and len(rows[0]) == 9, 'window-backup-clone-role')
        role, timeout_val, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolinherit, rolcanlogin, rolrepl = rows[0]
        require(role == self.config.migration_user
                and role != self.config.restore_user
                and role != self.config.admin_user
                and timeout_val == APPLICATOR_STATEMENT_TIMEOUT
                and rolsuper is False
                and rolbypassrls is True
                and rolcreaterole is True
                and rolcreatedb is True
                and rolinherit is True
                and rolcanlogin is True
                and rolrepl is False,
                'window-backup-clone-role')
        return dict(
            role=str(role),
            restore_role=self.config.restore_user,
            rolsuper=False,
            rolbypassrls=True,
            rolcreaterole=True,
            rolcreatedb=True,
            rolinherit=True,
            rolcanlogin=True,
            rolreplication=False,
            statement_timeout=str(timeout_val),
        )

    def _verify_runtime_rls_and_grants(self, address, password):
        """Inspect runtime role flags, RLS/FORCE RLS, policies and column/table grants without reading domain data."""
        conn = self.clone_connect(host=address, dbname=CLONE_DB, user=self.config.admin_user,
                                  password=password, timeout=10)
        try:
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(fdb.Q_BEGIN)
            try:
                cur.execute(fdb.Q_PATH)
                cur.fetchall()
                cur.execute(Q_RUNTIME_ROLES)
                role_rows = cur.fetchall()
                cur.execute(Q_RUNTIME_TABLE_PRIVS)
                table_rows = cur.fetchall()
            finally:
                cur.execute('ROLLBACK')
        finally:
            conn.close()
        require(tuple(row[0] for row in role_rows) == RUNTIME_ROLE_NAMES, 'window-backup-runtime-rls')
        for name, rolsuper, rolbypassrls, rolcanlogin, rolinherit, rolcreaterole, rolcreatedb in role_rows:
            require(rolsuper is False and rolcanlogin is False and rolcreaterole is False
                    and rolcreatedb is False and rolbypassrls is (name == 'service_role'),
                    'window-backup-runtime-rls')
        expected_tables = ('cell_alerts', 'celula_alerta_regras', 'private_deletion_uploads', 'private_summary_tasks')
        require(tuple(row[0] for row in table_rows) == expected_tables, 'window-backup-runtime-rls')
        verified_tables = {}
        for row in table_rows:
            require(len(row) == 18, 'window-backup-runtime-rls')
            (name, rls, force_rls, polroles, anon_any, service_any, auth_sel, auth_ins, auth_upd, auth_del,
             storage_any, send_any, summary_any, queue_any, alerts_tratado, alerts_igreja,
             upload_ok, summary_ok) = row
            require(rls is True and force_rls is True and not anon_any and not service_any,
                    'window-backup-runtime-rls')
            roles_tuple = tuple(polroles)
            if name in ('cell_alerts', 'celula_alerta_regras'):
                require(roles_tuple == ('authenticated',)
                        and auth_sel is True and auth_ins is True and auth_upd is True and auth_del is False
                        and not storage_any and not send_any and not summary_any and not queue_any
                        and alerts_tratado is True and alerts_igreja is False,
                        'window-backup-runtime-rls')
            elif name == 'private_deletion_uploads':
                require(roles_tuple == ('private_storage_runtime',)
                        and not auth_sel and not auth_ins and not auth_upd and not auth_del
                        and upload_ok is True and not send_any and not summary_any and not queue_any,
                        'window-backup-runtime-rls')
            else:
                require(roles_tuple == ('authenticated', 'private_summary_runtime')
                        and summary_ok is True and not storage_any and not send_any and not queue_any,
                        'window-backup-runtime-rls')
            verified_tables[name] = dict(rls=True, force_rls=True, policy_roles=list(roles_tuple))
        return dict(
            runtime_roles=list(RUNTIME_ROLE_NAMES),
            service_role_bypassrls=True,
            non_service_roles_bypassrls=False,
            tables=verified_tables,
        )

    def _replay(self, request_digest, address, password):
        # Outside the backup root: protected path names (backups, *.dump) are refused by the executor.
        applicator_role = self._verify_applicator_session(address, password)
        root = Path(self.config.clone_workdir)
        require(os.path.lexists(root) and stat.S_ISDIR(os.lstat(root).st_mode) and not root.is_symlink(),
                'window-backup-workdir-missing')
        workdir = root / request_digest
        try:
            workdir.mkdir(mode=0o700)
        except FileExistsError:
            raise Refused('window-backup-run-exists') from None
        url = (f'postgresql://{self.config.migration_user}:{password}@{address}:5432/{CLONE_DB}'
               '?sslmode=disable')
        executor = MigrationExecutor(self.plan, python=self.config.python, workdir=str(workdir),
                                     secret=lambda: url, timeout=self.config.timeout('migration_s'),
                                     runner=ProcessRunner(binaries=(self.config.python,), run=self.migrate_run))
        max_s = min(60, self.config.timeout('max_migration_s'))
        timings = []
        for index, migration in enumerate(self.plan.pending, 1):
            migration_started = self.clock()
            rc = executor.apply(index, migration)
            elapsed = float(round(self.clock() - migration_started, 3))
            require(rc == 0, 'window-backup-clone-migration-failed')
            require(elapsed <= max_s, 'window-backup-migration-slow')
            timings.append(dict(name=migration.name, seconds=elapsed, concurrent=bool(migration.concurrent)))
        migrations_seconds = float(round(sum(t['seconds'] for t in timings), 3))
        max_migration_seconds = float(max((t['seconds'] for t in timings), default=0.0))
        return applicator_role, timings, migrations_seconds, max_migration_seconds

    def _cleanup(self, name):
        # Own resources only, by exact name; a missing container/network is not an error.
        failed = False
        for args in (('rm', '-f', '-v', name), ('network', 'rm', name)):
            try:
                self._docker(args, timeout=self.config.timeout('docker_s'))
            except Refused:
                failed = True
        rc, out = self._docker(('ps', '-a', '--filter', 'label=igreja12.window-backup=' + name, '--format', '{{.ID}}'),
                               timeout=self.config.timeout('docker_s'), capture=True)
        require(not failed and rc == 0 and out == '', 'window-backup-cleanup-failed')

    def __call__(self, request):
        require(not self.used, 'window-backup-already-used')
        self.used = True
        require(isinstance(request, dict) and request.get('schema') in REQUEST_SCHEMAS
                and request.get('plan_digest') == self.plan.digest
                and request.get('source_identity') == self.expected.identity
                and request.get('baseline_digest') == self.expected.baseline_digest
                and isinstance(request.get('nonce'), str) and re.fullmatch('[0-9a-f]{64}', request['nonce']),
                'window-backup-request')
        require(request['schema'] != BACKUP_REQUEST_SCHEMA or self.config.restore_excluded_expected,
                'window-backup-restore-excluded')
        request_digest = digest(request)
        started = self.clock()
        run_dir = self._run_dir(request_digest)
        roles = source_role_names(self.connect)
        extensions = source_public_extensions(self.connect)
        trusted_owner = source_trusted_extension_owner(self.connect, default=self.config.migration_user)
        dump_started = self.clock()
        path, backup_id, size = self._dump(run_dir)
        dump_seconds = float(round(self.clock() - dump_started, 3))
        name = 'igreja12-window-clone-' + request_digest[:16]
        password = secrets.token_hex(24)
        admin = None
        try:
            address, admin = self._start_clone(name, password)
            created = self._prepare_clone(admin, roles, password)
            admin.close()
            admin = None
            self._prepare_clone_extensions(address, password, extensions)
            restore_started = self.clock()
            removed = self._restore(name, path, password, run_dir)
            restore_seconds = float(round(self.clock() - restore_started, 3))
            restored = self._state(address, password)
            require(restored['ledger'] == self.plan.baseline, 'window-backup-restore-ledger')
            require(restored['invalid'] == 0, 'window-backup-restore-invalid-index')
            require(restored['catalog'] == self.expected.catalog, 'window-backup-restore-catalog')
            applicator_role, migration_timings, migrations_seconds, max_migration_seconds = self._replay(
                request_digest, address, password)
            self._align_replay_extensions(address, password, trusted_owner)
            final = self._state(address, password)
            rls_grants_verified = self._verify_runtime_rls_and_grants(address, password)
        finally:
            if admin is not None:
                admin.close()
            self._cleanup(name)
        require(final['ledger'] == tuple(sorted(m.name for m in self.plan.migrations)), 'window-backup-final-ledger')
        require(final['invalid'] == 0, 'window-backup-final-invalid-index')
        clone_identity = digest(['window-clone', *final['identity'], request_digest])
        require(clone_identity != self.expected.identity, 'window-backup-clone-is-source')
        return dict(schema=RECEIPT_SCHEMA, plan_digest=self.plan.digest, source_identity=self.expected.identity,
                    baseline_digest=self.expected.baseline_digest, restore_verified=True,
                    request_digest=request_digest, backup_id=backup_id, backup_bytes=size, backup_path=str(path),
                    clone_rehearsal=dict(
                        migrations_verified=True, clone_identity=clone_identity, cluster_global_ddl_possible=True,
                        applied=len(migration_timings), final_ledger=len(final['ledger']),
                        concurrent=sum(m.concurrent for m in self.plan.pending),
                        sql_digest=digest([(m.name, m.sha256) for m in self.plan.pending]),
                        final_schema_digest=final['catalog'], restored_catalog=restored['catalog'],
                        roles_created=created, restore_excluded=removed, clone_image=self.config.clone_image,
                        dump_image=self.config.dump_image,
                        dump_seconds=dump_seconds, restore_seconds=restore_seconds,
                        migrations_seconds=migrations_seconds, max_migration_seconds=max_migration_seconds,
                        migration_timings=migration_timings, applicator_role=applicator_role,
                        rls_grants_verified=rls_grants_verified),
                    dump_seconds=dump_seconds, restore_seconds=restore_seconds,
                    migrations_seconds=migrations_seconds, max_migration_seconds=max_migration_seconds,
                    seconds=float(round(self.clock() - started, 3)))
