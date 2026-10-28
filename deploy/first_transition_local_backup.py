"""Real dump/restore rehearsal of an already guarded, synthetic local database.

This is not the production backup script or a backup of Redis/media/storage.
The archive exists only inside the rehearsal temp directory; only metadata
leaves it. The restored database is UUID-named, ownership-marked and removed.
No services, gates or remote endpoints are changed. Replaying the clone can
create cluster-global roles in this owned disposable cluster; it is not
cluster isolation or an operational backup.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from first_transition_adapter import (
    LocalDatabase, Refused, _full_preflight_at, baseline_digest, digest, local_endpoint, require,
    pre_ddl_findings, remaining_pre_ddl_gates, step_invariants,
    require_clean_preflight,
)

TOOLS = Path('/usr/lib/postgresql/17/bin')
# Normalize identities across databases: no OIDs or relfilenodes in this proof.
CATALOG = (
    "SELECT c.relkind,c.relname,pg_get_userbyid(c.relowner),c.relrowsecurity,c.relforcerowsecurity "
    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relname",
    "SELECT c.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity,a.attgenerated,"
    "pg_get_expr(d.adbin,d.adrelid) FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
    "JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum "
    "WHERE n.nspname='public' AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum",
    "SELECT c.relname,x.conname,pg_get_constraintdef(x.oid,true),x.convalidated FROM pg_constraint x "
    "JOIN pg_class c ON c.oid=x.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
    "WHERE n.nspname='public' ORDER BY c.relname,x.conname",
    "SELECT c.relname,pg_get_indexdef(i.indexrelid),i.indisvalid,i.indisready FROM pg_index i "
    "JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
    "WHERE n.nspname='public' ORDER BY c.relname",
    "SELECT p.proname,pg_get_function_identity_arguments(p.oid),md5(pg_get_functiondef(p.oid)),"
    "pg_get_userbyid(p.proowner),p.prosecdef,p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
    "WHERE n.nspname='public' AND p.prokind IN ('f','p') ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)",
    "SELECT c.relname,p.polname,p.polcmd,p.polpermissive,p.polroles::text,pg_get_expr(p.polqual,p.polrelid),"
    "pg_get_expr(p.polwithcheck,p.polrelid) FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid "
    "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relname,p.polname",
)


def snapshot(connection):
    """Owned synthetic DB only: schema metadata + table cardinalities, never row contents."""
    from psycopg2 import sql
    with connection.cursor() as cursor:
        cursor.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        try:
            cursor.execute("SET LOCAL search_path=pg_catalog,public")
            cursor.execute("SET LOCAL statement_timeout='5s'")
            cursor.execute('SET LOCAL row_security=off')
            catalog = []
            for query in CATALOG:
                cursor.execute(query)
                catalog.append(cursor.fetchall())
            cursor.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                           "WHERE n.nspname='public' AND c.relkind='r' ORDER BY c.relname")
            counts = {}
            for (table,) in cursor.fetchall():
                cursor.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(table)))
                counts[table] = cursor.fetchone()[0]
            return dict(catalog=digest(catalog), counts=digest(counts), tables=len(counts))
        finally:
            cursor.execute('ROLLBACK')


def rehearse_restored_migrations(plan, url, nonce):
    """Apply exact pending SQL only to the owned UUID clone, never the source.

    This is a destructive disposable rehearsal, not a production retry path.
    Failure discards this clone; no invalid-index repair or ledger adoption.
    """
    with LocalDatabase(url, nonce, restore=True) as clone:
        before = clone.observe()
        require(before['ledger'] == plan.baseline, 'clone-baseline-ledger')
        pre_ddl_findings(before)
        ledger = set(plan.baseline)
        for migration in plan.pending:
            current = clone.observe()
            step_invariants(current)
            remaining_pre_ddl_gates(current)
            require(set(current['ledger']) == ledger, 'clone-ledger-drift')
            require(not set(migration.indexes).intersection(current['relations']),
                    'clone-index-collision')
            clone.apply(plan, migration)
            ledger.add(migration.name)
            after = clone.observe()
            step_invariants(after)
            require(set(after['ledger']) == ledger, 'clone-migration-ledger')
        require(ledger == {m.name for m in plan.migrations}, 'clone-final-ledger')
        require_clean_preflight(clone.full_preflight(plan, len(ledger)), complete=True)
        return dict(migrations_verified=True, applied=len(plan.pending),
                    final_schema_digest=snapshot(clone.conn)['catalog'],
                    clone_identity=clone.identity, cluster_global_ddl_possible=True,
                    final_ledger=len(ledger), concurrent=sum(m.concurrent for m in plan.pending),
                    sql_digest=digest([(m.name, m.sha256) for m in plan.pending]))


def rehearse_backup(database, plan):
    import psycopg2
    from psycopg2 import sql
    local_endpoint(database._url)
    before = database.observe()
    require(before['ledger'] == plan.baseline, 'backup-requires-baseline')
    expected = snapshot(database.conn)
    parts = urlsplit(database._url)
    target = 'first_transition_restore_' + uuid4().hex
    nonce = str(uuid4())
    target_url = urlunsplit(parts._replace(path='/' + target))
    local_endpoint(target_url, restore=True)
    env = dict(PATH='/usr/bin:/bin', PGHOST='127.0.0.1', PGPORT=str(parts.port), PGUSER='postgres',
               PGPASSWORD='synthetic-only', PGSSLMODE='disable', PGAPPNAME='igreja12-local-backup',
               PGOPTIONS='-c search_path=pg_catalog,public -c statement_timeout=30000 -c row_security=off')
    versions = {}
    for name in ('pg_dump', 'pg_restore'):
        try:
            version = subprocess.run([str(TOOLS / name), '--version'], env=env,
                                     capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            raise Refused('local-pg17-tools-unavailable') from None
        match = re.fullmatch(r'pg_(?:dump|restore) \(PostgreSQL\) (17\.[0-9]+)(?: .*|)\n?', version.stdout)
        require(version.returncode == 0 and match is not None, 'local-pg17-tools-unavailable')
        versions[name] = match.group(1)
    created = False
    try:
        with tempfile.TemporaryDirectory(prefix='igreja12-synthetic-restore-') as directory:
            archive = Path(directory) / 'synthetic.archive'
            try:
                dumped = subprocess.run([str(TOOLS / 'pg_dump'), '--format=custom',
                                         '--file', str(archive), '--dbname', 'first_transition_test'],
                                        env=env, capture_output=True, timeout=60)
                require(dumped.returncode == 0, 'local-dump-failed')
                archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
                with database.conn.cursor() as cursor:
                    cursor.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(target)))
                    created = True
                    cursor.execute(sql.SQL('COMMENT ON DATABASE {} IS %s').format(sql.Identifier(target)),
                                   ('igreja12-local-disposable:' + nonce,))
                # Full pg_dump expects the template's public schema to exist.
                result = subprocess.run([str(TOOLS / 'pg_restore'), '--exit-on-error', '--single-transaction',
                                         '--dbname', target, str(archive)], env=env,
                                        capture_output=True, timeout=60)
                require(result.returncode == 0, 'local-restore-failed')
                with closing(psycopg2.connect(target_url, connect_timeout=3, hostaddr='127.0.0.1', options='')) as restored:
                    restored.autocommit = True
                    actual = snapshot(restored)
                require(actual == expected, 'local-restore-mismatch')
                summary = _full_preflight_at(plan, target_url, len(before['ledger']), nonce)
                require_clean_preflight(summary, complete=False)
                migrated = rehearse_restored_migrations(plan, target_url, nonce)
                after = database.observe()
                require(baseline_digest(before) == baseline_digest(after)
                        and snapshot(database.conn) == expected, 'source-changed-during-local-backup')
                return dict(scope='synthetic-database-only', restore_verified=True, archive_persisted=False,
                            content_verified=False, clone_rehearsal=migrated,
                            plan_digest=plan.digest, source_identity=database.identity,
                            baseline_digest=baseline_digest(before), archive_sha256=archive_sha,
                            schema_digest=expected['catalog'], counts_digest=expected['counts'],
                            tables=expected['tables'], tools=versions)
            except (OSError, subprocess.TimeoutExpired):
                raise Refused('local-backup-tool-failed') from None
    except psycopg2.Error:
        raise Refused('local-backup-database-failed') from None
    finally:
        if created:
            try:
                with database.conn.cursor() as cursor:
                    cursor.execute("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=%s", (target,))
                    ownership = cursor.fetchone()
                    require(ownership is not None and ownership[0] == 'igreja12-local-disposable:' + nonce,
                            'local-restore-ownership-changed')
                    cursor.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(target)))
            except psycopg2.Error:
                raise Refused('local-restore-cleanup-failed') from None
