"""Read-only PostgreSQL observations of the first transition over an injected connection.

``ReadOnlyDatabase.observe`` opens a fresh connection from the injected factory,
runs one ``REPEATABLE READ READ ONLY`` transaction and returns aggregates only:
database identity, role visibility over pg_stat_activity, the ordered ledger,
the public catalog fingerprint (``Q_CATALOG``; not the local adapter's
relation/attribute digest), invalid indexes, index builds, writing sessions and
active leases. No row payload, query text, PII or session detail is read; the
catalog's definitions are hashed server-side. ``LedgerProof`` binds that
observation to an expected identity/baseline ledger/catalog: any drift of the
ledger or of the CATALOG-COVERED state (public relations/RLS/owner/ACL/view
definitions, attributes/defaults/generated/identity, constraints, index
definitions/validity, triggers, rules, policies, functions, types/enums,
sequences, extensions, schema/default privileges) refuses. It proves equality
of that covered state now, not that no DDL ever ran: objects outside the public
schema, cluster-global objects (roles, databases) and a change reverted before
the observation are not covered. It is the fresh database proof the observed
driver requires before every resume effect; a journal without a DDL marker
alone is never accepted as that proof.

Nothing connects at import or construction. The real connection factory and
expected values are Phase 3 inputs (A5 preflight); errors are fixed codes.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re

from first_transition_adapter import digest
from initial_transition_ops import Refused, require

HEX64 = re.compile('[0-9a-f]{64}')
IDENT = re.compile('[a-z_][a-z0-9_]{0,62}')
APPLICATION = re.compile(r'[A-Za-z0-9_.:-]{1,63}')
LEDGER_NAME = re.compile(r'[A-Za-z0-9_.-]{1,200}\.sql')
# Mandatory lease columns of the consumers (active lease = column > now()). Counted, never read.
# Configuration may add explicit extra columns but can never drop one of these.
LEASES = (('broadcast_execucoes', 'lease_ate'), ('broadcast_entregas', 'lease_ate'),
          ('notification_outbox', 'claimed_until'), ('cell_report_audio_inputs', 'lease_until'))
OBSERVER_APPLICATION = 'igreja12-first-transition-observer'

CURRENT_DB = '(SELECT oid FROM pg_database WHERE datname=current_database())'
Q_BEGIN = 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY'
Q_TIMEOUT = "SELECT set_config('statement_timeout', %s, true)"
Q_PATH = "SELECT set_config('search_path', 'pg_catalog,public', true)"
Q_RLS_OFF = "SELECT set_config('row_security', 'off', true)"
Q_READ_ONLY = "SELECT current_setting('transaction_read_only')"
Q_IDENTITY = ('SELECT s.system_identifier::text, d.oid::bigint, d.datname FROM pg_control_system() s, '
              'pg_database d WHERE d.datname=current_database()')
# USAGE, not MEMBER: a non-inherited membership does not make other sessions' activity visible.
Q_VISIBILITY = ("SELECT r.rolsuper OR pg_has_role(current_user, 'pg_read_all_stats', 'USAGE') "
                'FROM pg_roles r WHERE r.rolname=current_user')
Q_LEDGER = 'SELECT name FROM public.schema_migrations ORDER BY name COLLATE "C"'
Q_INVALID = ('SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n '
             "ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT (i.indisvalid AND i.indisready) "
             'ORDER BY c.relname')
Q_INDEXES = ("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
             "WHERE n.nspname='public' AND c.relkind='i' ORDER BY c.relname")
Q_BUILDS = 'SELECT count(*) FROM pg_stat_progress_create_index WHERE datid=' + CURRENT_DB
PUBLIC = "(SELECT oid FROM pg_namespace WHERE nspname='public')"
# Catalog fingerprint of the public application schema: one (kind, object, md5) row per object.
# Every definition (defaults, view/function/policy/trigger/constraint/index bodies, ACLs) is hashed
# SERVER-SIDE by md5(row(...)::text); no body, literal or expression ever reaches Python or a journal.
# pg_get_functiondef is not defined for aggregates (prokind 'a'): their pg_aggregate row is hashed instead.
CATALOG_KINDS = ('attribute', 'constraint', 'default-acl', 'extension', 'function', 'index', 'namespace',
                 'policy', 'relation', 'rule', 'sequence', 'trigger', 'type')
Q_CATALOG = (
    'SELECT kind, name, md5(definition) AS hash FROM ('
    "SELECT 'namespace'::text AS kind, n.nspname::text AS name, row(n.nspowner::regrole, n.nspacl)::text "
    "AS definition FROM pg_namespace n WHERE n.nspname='public' "
    "UNION ALL SELECT 'default-acl', d.defaclrole::regrole::text || ':' || d.defaclobjtype::text || ':' "
    "|| CASE WHEN d.defaclnamespace=0 THEN '*' ELSE 'public' END, row(d.defaclacl)::text "
    'FROM pg_default_acl d WHERE d.defaclnamespace IN (0, ' + PUBLIC + ') '
    "UNION ALL SELECT 'extension', e.extname::text, row(e.extversion, e.extowner::regrole, e.extrelocatable)::text "
    'FROM pg_extension e WHERE e.extnamespace=' + PUBLIC + ' '
    "UNION ALL SELECT 'relation', c.relname::text, row(c.relkind, c.relowner::regrole, c.relacl, c.relrowsecurity, "
    'c.relforcerowsecurity, c.relpersistence, c.relreplident, c.reloptions, c.relispartition, c.reloftype::regtype, '
    "CASE WHEN c.relkind IN ('v', 'm') THEN pg_get_viewdef(c.oid) END, pg_get_partkeydef(c.oid), "
    'pg_get_expr(c.relpartbound, c.oid), ARRAY(SELECT h.inhparent::regclass::text FROM pg_inherits h '
    'WHERE h.inhrelid=c.oid ORDER BY h.inhseqno))::text FROM pg_class c WHERE c.relnamespace=' + PUBLIC + ' '
    "UNION ALL SELECT 'attribute', c.relname || '.' || a.attname, row(a.attnum, format_type(a.atttypid, a.atttypmod), "
    'a.attnotnull, a.atthasdef, pg_get_expr(d.adbin, d.adrelid), a.attidentity, a.attgenerated, '
    'a.attcollation::regcollation, a.attacl, a.attoptions, a.attstorage)::text FROM pg_attribute a '
    'JOIN pg_class c ON c.oid=a.attrelid LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum '
    'WHERE c.relnamespace=' + PUBLIC + ' AND a.attnum>0 AND NOT a.attisdropped '
    "UNION ALL SELECT 'constraint', coalesce(c.relname::text, k.contypid::regtype::text) || '.' || k.conname, "
    'row(k.contype, k.condeferrable, k.condeferred, k.convalidated, k.connoinherit, pg_get_constraintdef(k.oid))::text '
    'FROM pg_constraint k LEFT JOIN pg_class c ON c.oid=k.conrelid WHERE k.connamespace=' + PUBLIC + ' '
    "UNION ALL SELECT 'index', c.relname::text, row(pg_get_indexdef(i.indexrelid), i.indisunique, i.indisprimary, "
    'i.indisexclusion, i.indimmediate, i.indisvalid, i.indisready, i.indislive, i.indisreplident, '
    'i.indnullsnotdistinct)::text FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid '
    'WHERE c.relnamespace=' + PUBLIC + ' '
    "UNION ALL SELECT 'trigger', c.relname || '.' || t.tgname, row(t.tgenabled, pg_get_triggerdef(t.oid))::text "
    'FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid WHERE c.relnamespace=' + PUBLIC + ' '
    "UNION ALL SELECT 'rule', c.relname || '.' || r.rulename, row(r.ev_enabled, pg_get_ruledef(r.oid))::text "
    'FROM pg_rewrite r JOIN pg_class c ON c.oid=r.ev_class WHERE c.relnamespace=' + PUBLIC + ' '
    "UNION ALL SELECT 'policy', c.relname || '.' || p.polname, row(p.polcmd, p.polpermissive, "
    'ARRAY(SELECT r::regrole::text FROM unnest(p.polroles) r ORDER BY 1), pg_get_expr(p.polqual, p.polrelid), '
    'pg_get_expr(p.polwithcheck, p.polrelid))::text FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid '
    'WHERE c.relnamespace=' + PUBLIC + ' '
    "UNION ALL SELECT 'function', p.oid::regprocedure::text, row(p.prokind, p.proowner::regrole, p.proacl, "
    'p.proconfig, p.prosecdef, p.proleakproof, p.proisstrict, p.provolatile, p.proparallel, '
    "pg_get_function_result(p.oid), CASE WHEN p.prokind <> 'a' THEN pg_get_functiondef(p.oid) END, "
    '(SELECT row(g.aggkind, g.aggtransfn::regproc, g.aggfinalfn::regproc, g.aggcombinefn::regproc, '
    'g.aggtranstype::regtype, g.agginitval)::text FROM pg_aggregate g WHERE g.aggfnoid=p.oid))::text '
    'FROM pg_proc p WHERE p.pronamespace=' + PUBLIC + ' '
    "UNION ALL SELECT 'type', t.oid::regtype::text, row(t.typtype, t.typowner::regrole, t.typacl, t.typnotnull, "
    't.typdefault, format_type(t.typbasetype, t.typtypmod), t.typcollation::regcollation, '
    'ARRAY(SELECT e.enumlabel::text FROM pg_enum e WHERE e.enumtypid=t.oid ORDER BY e.enumsortorder))::text '
    'FROM pg_type t WHERE t.typnamespace=' + PUBLIC + ' '
    "UNION ALL SELECT 'sequence', c.relname::text, row(s.seqtypid::regtype, s.seqstart, s.seqincrement, s.seqmax, "
    's.seqmin, s.seqcache, s.seqcycle)::text FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid '
    'WHERE c.relnamespace=' + PUBLIC +
    ') catalog ORDER BY kind COLLATE "C", name COLLATE "C", 3')
MD5 = re.compile('[0-9a-f]{32}')
# Potential writer = any other client session of this database holding an xid or not idle (active,
# idle in transaction, unknown state). Only this observer's own PID is excluded; no application_name
# exempts a session (a writer may not hold an xid yet). Only counted; never query/user/address.
Q_WRITERS = ('SELECT count(*) FROM pg_stat_activity WHERE datid=' + CURRENT_DB + ' AND pid<>pg_backend_pid() '
             "AND backend_type='client backend' AND (backend_xid IS NOT NULL OR state IS DISTINCT FROM 'idle')")
Q_RELATION = "SELECT to_regclass(%s) IS NOT NULL"


def lease_query(table, column):
    require(IDENT.fullmatch(table) and IDENT.fullmatch(column), 'database-lease-scope')
    return f'SELECT count(*) FROM public."{table}" WHERE "{column}" > now()'


def _single(cur, query, params=None):
    cur.execute(query, params) if params is not None else cur.execute(query)
    rows = cur.fetchall()
    require(isinstance(rows, (list, tuple)) and len(rows) == 1 and len(rows[0]) >= 1, 'database-observation-shape')
    return rows[0]


def _count(cur, query, params=None):
    value = _single(cur, query, params)[0]
    require(type(value) is int and 0 <= value <= 2**62, 'database-observation-shape')
    return value


def _catalog(cur):
    cur.execute(Q_CATALOG)
    rows = cur.fetchall()
    require(isinstance(rows, (list, tuple)) and rows and all(
        isinstance(r, (list, tuple)) and len(r) == 3 and r[0] in CATALOG_KINDS
        and isinstance(r[1], str) and 0 < len(r[1]) <= 1024 and isinstance(r[2], str) and MD5.fullmatch(r[2])
        for r in rows), 'database-catalog-shape')
    return digest([list(r) for r in rows])


def lease_scope(lease_columns):
    """Validated lease scope: identifiers only, no duplicate, every mandatory LEASES pair present."""
    require(isinstance(lease_columns, tuple) and lease_columns and all(
        isinstance(p, tuple) and len(p) == 2 and all(isinstance(v, str) and IDENT.fullmatch(v) for v in p)
        for p in lease_columns) and len(set(lease_columns)) == len(lease_columns), 'database-lease-scope')
    require(set(LEASES) <= set(lease_columns), 'database-lease-mandatory')
    return lease_columns


@dataclass(frozen=True)
class DatabaseExpectation:
    """Identity + exact baseline ledger + catalog digest, from configuration (A5)."""
    identity: str
    ledger: tuple
    catalog: str

    def validated(self):
        require(isinstance(self.identity, str) and HEX64.fullmatch(self.identity)
                and isinstance(self.catalog, str) and HEX64.fullmatch(self.catalog)
                and type(self.ledger) is tuple and self.ledger
                and all(isinstance(n, str) and LEDGER_NAME.fullmatch(n) for n in self.ledger)
                and list(self.ledger) == sorted(set(self.ledger)), 'database-expectation')
        return self

    @property
    def baseline_digest(self):
        # Same value as first_transition_adapter.baseline_digest over an observation.
        return digest([list(self.ledger), self.catalog])


class ReadOnlyDatabase:
    """``observer_applications`` stays accepted (validated) for configuration compatibility only:
    application names are labels, never a bypass of the activity predicate of ``Q_WRITERS``.
    ``lease_columns`` must contain every mandatory ``LEASES`` pair (extras allowed), checked before any IO."""

    def __init__(self, connect: Callable, *, lease_columns=LEASES, observer_applications=()):
        require(callable(connect), 'database-connect-missing')
        lease_scope(lease_columns)
        require(isinstance(observer_applications, tuple) and len(observer_applications) <= 8
                and all(isinstance(a, str) and APPLICATION.fullmatch(a) for a in observer_applications),
                'database-observer-scope')
        self.connect, self.lease_columns = connect, lease_columns
        self.observer_applications = (OBSERVER_APPLICATION, *observer_applications)

    def observe(self, *, timeout=10):
        require(type(timeout) in (int, float) and 0 < timeout <= 30, 'database-timeout-bound')
        conn, outcome = None, None
        try:
            conn = self.connect(timeout=timeout)
            result = self._observe(conn, timeout)
        except Refused as exc:
            outcome = str(exc) if str(exc).startswith('database-') else 'database-observation-failed'
        except Exception:
            outcome = 'database-observation-failed'
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    outcome = outcome or 'database-observation-failed'
        require(outcome is None, outcome)
        return result

    def _observe(self, conn, timeout):
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(Q_BEGIN)
        try:
            _single(cur, Q_TIMEOUT, (f'{int(timeout * 1000)}ms',))
            _single(cur, Q_PATH)
            # With row_security=off a restricted role errors instead of hiding leased rows.
            require(_single(cur, Q_RLS_OFF)[0] == 'off', 'database-row-security')
            read_only = _single(cur, Q_READ_ONLY)[0] == 'on'
            require(read_only, 'database-not-read-only')
            system, oid, name = _single(cur, Q_IDENTITY)[:3]
            require(isinstance(system, str) and system.isdigit() and type(oid) is int and isinstance(name, str),
                    'database-observation-shape')
            visible = _single(cur, Q_VISIBILITY)[0]
            require(visible is True, 'database-activity-not-visible')
            cur.execute(Q_LEDGER)
            ledger = tuple(row[0] for row in cur.fetchall())
            require(all(isinstance(n, str) and LEDGER_NAME.fullmatch(n) for n in ledger), 'database-ledger-shape')
            cur.execute(Q_INVALID)
            invalid = tuple(row[0] for row in cur.fetchall())
            cur.execute(Q_INDEXES)
            indexes = tuple(row[0] for row in cur.fetchall())
            builds = _count(cur, Q_BUILDS)
            catalog = _catalog(cur)
            writers = _count(cur, Q_WRITERS)
            leases = 0
            for table, column in self.lease_columns:
                require(_single(cur, Q_RELATION, ('public.' + table,))[0] is True, 'database-lease-relation')
                leases += _count(cur, lease_query(table, column))
            return dict(identity=digest([system, oid, name]), read_only=True, activity_visible=True,
                        ledger=ledger, ledger_digest=digest(list(ledger)), catalog=catalog, invalid=invalid,
                        indexes=indexes, index_builds=builds, writing_sessions=writers, active_leases=leases)
        finally:
            cur.execute('ROLLBACK')


def require_same_database(observation, expected):
    """Read-only observation with visible activity, of the expected database identity."""
    require(observation['read_only'] is True and observation['activity_visible'] is True, 'database-not-read-only')
    require(observation['identity'] == expected.identity, 'database-identity-mismatch')


def require_ddl_free(observation, expected):
    """The observed ledger and catalog fingerprint equal the baseline; no index build in progress."""
    require_same_database(observation, expected)
    require(observation['ledger'] == expected.ledger, 'database-ledger-drift')
    require(observation['catalog'] == expected.catalog, 'database-ddl-drift')
    require(not observation['invalid'] and observation['index_builds'] == 0, 'database-ddl-in-progress')


def require_quiet(observation):
    require(observation['writing_sessions'] == 0, 'database-writing-session')
    require(observation['active_leases'] == 0, 'database-active-lease')


def summary(observation):
    """Journal-safe aggregates (no names beyond the ledger digest)."""
    return {key: observation[key] for key in ('identity', 'ledger_digest', 'catalog', 'index_builds',
                                             'writing_sessions', 'active_leases')} | dict(
        ledger_count=len(observation['ledger']), invalid_count=len(observation['invalid']))


class LedgerProof:
    """Fresh read-only proof, bound to a host scope, that the ledger and the catalog-covered state
    still equal the baseline (see the module docstring for what the fingerprint covers)."""

    def __init__(self, database, expected, *, scope):
        require(isinstance(database, ReadOnlyDatabase), 'database-proof-source')
        require(isinstance(expected, DatabaseExpectation), 'database-expectation')
        require(isinstance(scope, str) and HEX64.fullmatch(scope), 'database-proof-scope')
        self.database, self.expected, self.scope = database, expected.validated(), scope

    def prove(self, scope, *, timeout):
        require(scope == self.scope, 'database-proof-scope')
        observation = self.database.observe(timeout=min(timeout, 30))
        require_ddl_free(observation, self.expected)
        return dict(scope=scope, read_only=True, ddl_free=True, identity=observation['identity'],
                    ledger_digest=observation['ledger_digest'], catalog=observation['catalog'])


def psycopg2_connector(secret, *, application_name=OBSERVER_APPLICATION):
    """Connection factory for a future authorized run; the URL comes only from ``secret()``.

    The session is forced read-only by default; the URL is never stored,
    logged or put in argv. Unused by tests.
    """
    require(callable(secret) and APPLICATION.fullmatch(application_name), 'database-connect-missing')

    def connect(*, timeout):
        import psycopg2
        url = secret()
        require(isinstance(url, str) and url.startswith('postgresql://') and '\n' not in url, 'database-secret')
        return psycopg2.connect(url, connect_timeout=max(1, int(timeout)), application_name=application_name,
                                options='-c default_transaction_read_only=on')
    return connect
