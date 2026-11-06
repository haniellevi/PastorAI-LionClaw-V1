"""Canonical R4 readers and strict recovery comparison, no connection or writes.

Four sibling reader modules are unchanged copies of CAPTURA-DIRETA-R4-20261104
verified against its RUNTIME-MANIFEST. Collector/projections below retain the
function bodies from capture_core.py f47ee8f7...b70d46; only import aliases and
managed_profile.PROFILE binding differ. ACL comparison bodies come from
PACOTE-LOGICO-20261105/acl_compare.py de4f486a...bbc3 (no repair helper copied).
Controller Plan pins all runtime sources. No historical request, artefact or
retention identifiers are accepted as a new window's authority.

Private payload stays in memory/companion; only aggregate summaries leave
comparison. This module does not emit an A8 receipt or prove physical recovery.
"""
from copy import deepcopy
import hashlib
import json
import time
from types import SimpleNamespace

import first_transition_native_v2 as sql
import first_transition_native_v3 as coverage_sql
import first_transition_native_v3_compare as coverage_compare
import first_transition_native_settings as settings
from initial_transition_ops import Refused, require

managed_profile = SimpleNamespace(PROFILE='supabase-17.6.1.127')

class CaptureError(ValueError):pass

def need(ok,code):
    if not ok:raise CaptureError(code)

def raw(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def digest(value):return hashlib.sha256(raw(value)).hexdigest()

def v3_projection(value):
    coverage_compare.validate(value);result={}
    for category,rows in value.items():
        out=deepcopy(rows)
        for row in out:
            if row.get('acl') is not None:row['acl']=sorted(row['acl'],key=lambda g:raw(g))
            if type(row.get('roles'))is list:row['roles']=sorted(row['roles'],key=lambda r:raw(r))
        # Preserve positional object identities, function signatures, NULL/empty.
        result[category]=sorted(out,key=lambda r:raw([r[k] for k in coverage_compare.KEYS[category]]))
    return result

def v2_projection(value):
    need(type(value)is dict and set(value)=={'manifest','row_counts','settings'},'origin-v2-shape')
    result=deepcopy(value)
    for key,rows in result['manifest'].items():
        need(type(rows)is list,'origin-manifest-list')
        result['manifest'][key]=sorted(rows,key=raw)
    for role in result['manifest'].get('roles',[]):
        need(type(role)is dict and type(role.get('name'))is str and type(role.get('can_login'))is bool,
             'origin-projection-role')
        role['can_login']=role['name'] in ('postgres','supabase_admin')
    # LOGIN normalization can change the JSON sort key; re-sort that set.
    if 'roles' in result['manifest']:result['manifest']['roles']=sorted(result['manifest']['roles'],key=raw)
    result['settings']=settings.normalize_inventory(result['settings'],profile=managed_profile.PROFILE)
    return result

def one(cur,query):cur.execute(query);return cur.fetchone()[0]

def collect_v2(cur):
    manifest=one(cur,sql.MANIFEST)
    need(type(manifest)is dict and set(manifest)=={'roles','memberships','extensions','events',
         'schemas','default_acl','functions','catalog'},'origin-manifest-shape')
    need(all(type(rows)is list and len(rows)<=10000 for rows in manifest.values()),'origin-manifest-bound')
    tables=one(cur,sql.TABLES)
    need(type(tables)is list and len(tables)<=10000,'origin-table-bound')
    counts={}
    for row in tables:
        if getattr(cur,'trace',None)is not None:cur.trace.stage='v2-counts'
        need(type(row)is list and len(row)==2 and all(type(v)is str for v in row),'origin-table-shape')
        key='.'.join(row);need(key not in counts,'origin-count-key-collision')
        count=one(cur,sql.count_table(*row));need(type(count)is int and count>=0,'origin-row-count')
        counts[key]=count
    configured_raw=one(cur,sql.SETTINGS)
    if getattr(cur,'trace',None)is not None:cur.trace.stage='v2-settings-normalize'
    configured=settings.normalize_inventory(configured_raw,profile=managed_profile.PROFILE)
    cur.events['v2_at']=time.time()
    return dict(manifest=manifest,row_counts=counts,settings=configured)

def acl_items(value):
    if value is None:return None
    require(isinstance(value,str) and 2<=len(value)<=32768 and value[0]=='{' and value[-1]=='}','acl-array-format')
    if value=='{}':return ()
    items=[];i=1;end=len(value)-1
    while i<end:
        token=''
        if value[i]=='"':
            i+=1;closed=False
            while i<end:
                ch=value[i];i+=1
                if ch=='\\':
                    require(i<end,'acl-array-format');token+=value[i];i+=1
                elif ch=='"':closed=True;break
                else:token+=ch
            require(closed,'acl-array-format')
        else:
            start=i
            while i<end and value[i]!=',':
                require(value[i] not in '{}"\\' and not value[i].isspace(),'acl-array-format');i+=1
            token=value[start:i]
        require(token and len(token)<=2048 and '=' in token and '/' in token and '\x00' not in token,'acl-array-format')
        items.append(token);require(len(items)<=512,'acl-array-bound')
        if i==end:break
        require(value[i]==',' and i+1<end,'acl-array-format');i+=1
    return tuple(sorted(items))

def canonical(value):
    if isinstance(value,dict):return {k:canonical(v) for k,v in sorted(value.items())}
    if isinstance(value,list):return sorted((canonical(v) for v in value),key=lambda v:json.dumps(v,sort_keys=True))
    return value

def catalog(value):
    result=deepcopy(value)
    for category in ('schemas','default_acl','functions','catalog'):
        require(category in result and isinstance(result[category],list),'acl-catalog-shape')
        for row in result[category]:
            require(isinstance(row,dict) and 'acl' in row,'acl-catalog-shape')
            # NULL stays distinct from {} and from explicit default grants.
            row['acl']=acl_items(row['acl'])
    return canonical(result)

def _typed_metadata(v2, v3):
    """Guard JSON scalar types; Python equality otherwise equates bool and int."""
    v2_bools = dict(roles=('superuser','inherit','create_role','create_db','replication','bypass_rls','can_login'),
                    memberships=('admin','inherit','set_role'), functions=('security_definer',),
                    catalog=('rls','force'))
    v3_bools = dict(relations=('rls','force_rls'), routines=('security_definer',),
                    policies=('permissive',), indexes=('valid','ready','live'))
    for categories, required in ((v2['manifest'], v2_bools), (v3, v3_bools)):
        for name, rows in categories.items():
            for row in rows:
                require(type(row) is dict and all(type(row.get(key)) is bool for key in required.get(name, ())),
                        'window-origin-reader-shape')
    for category, rows in v3.items():
        for row in rows:
            for key, value in row.items():
                if key in v3_bools.get(category, ()) or key in ('acl','roles','identity'):
                    continue
                nullable = key in ('using_sha256','check_sha256') or (category == 'default_acl' and key == 'schema')
                nullable = nullable or (category == 'routines' and row['kind'] == 'a' and key == 'definition_sha256')
                if nullable and value is None:
                    continue
                require(type(value) is str and len(value) <= 65536 and (value or key == 'args'),
                        'window-origin-reader-shape')
                if key.endswith('_sha256'):
                    require(len(value) == 64 and all(c in '0123456789abcdef' for c in value),
                            'window-origin-reader-shape')
            if category == 'policies':
                require(type(row['roles']) is list and len(row['roles']) <= 10000
                        and all(v is None or type(v) is str and 0 < len(v) <= 1024 for v in row['roles']),
                        'window-origin-reader-shape')
            if category == 'initial_privileges':
                lengths = dict(schemas=1, relations=3, columns=3, types=2, routines=4)
                require(row['category'] in lengths and row['privilege_origin'] in ('e','i')
                        and type(row['identity']) is list and len(row['identity']) == lengths[row['category']]
                        and all(type(v) is str and len(v) <= 65536 for v in row['identity']),
                        'window-origin-reader-shape')


class NativeCatalogSample:
    """Immutable private serialization, NOT authentication/provenance evidence."""
    def __init__(self, v2, v3):
        # Canonical validation and projections refuse malformed inventory before
        # retaining private bytes. No scope/projected setting is silently fixed.
        require(type(v2) is dict and set(v2) == {'manifest', 'row_counts', 'settings'}
                and type(v2['manifest']) is dict and set(v2['manifest']) == {
                    'roles', 'memberships', 'extensions', 'events', 'schemas', 'default_acl', 'functions', 'catalog'}
                and all(type(rows) is list and len(rows) <= 10000 for rows in v2['manifest'].values())
                and type(v2['row_counts']) is dict and len(v2['row_counts']) <= 10000
                and all(type(key) is str and 0 < len(key) <= 2049 and type(value) is int
                        and 0 <= value <= 2**63 - 1 for key, value in v2['row_counts'].items()),
                'window-origin-reader-shape')
        v2_projection(v2)
        coverage_compare.validate(v3)
        _typed_metadata(v2, v3)
        encoded = raw(dict(v2=v2, v3=v3))
        require(len(encoded) <= 2080768, 'window-origin-reader-bound')
        self._encoded = encoded

    def summary(self):
        value = json.loads(self._encoded)
        return dict(v2_observed_sha256=digest(v2_inventory_view(value['v2'])),
                    v2_clone_expected_sha256=digest(v2_inventory_view(v2_projection(value['v2']))),
                    v3_sha256=digest(v3_projection(value['v3'])),
                    row_counts_sha256=digest(value['v2']['row_counts']),
                    settings_inventory_sha256=digest(value['v2']['settings']),
                    v3_counts={key: len(rows) for key, rows in value['v3'].items()})


def v2_inventory_view(value):
    """Canonical inventory view preserving OBSERVED LOGIN; never project a clone."""
    result = deepcopy(value)
    result['manifest'] = catalog(result['manifest'])
    result['settings'] = settings.normalize_inventory(result['settings'], profile=managed_profile.PROFILE)
    return result


class _TrackedReader:
    def __init__(self, cursor):
        self.inner, self.events = cursor, {}

    def execute(self, query):
        self.inner.execute(query)

    def fetchone(self):
        rows = self.inner.fetchall()
        require(type(rows) in (tuple, list) and len(rows) == 1 and len(rows[0]) == 1,
                'window-origin-reader-shape')
        return rows[0]


def collect_on_cursor(cursor):
    """Already owned RR/RO cursor only. Never BEGIN, import, connect or mutate."""
    try:
        cursor.execute("SELECT current_setting('transaction_read_only'), current_setting('transaction_isolation')")
        rows = cursor.fetchall()
        require(len(rows) == 1 and rows[0] == ('on', 'repeatable read'), 'window-origin-reader-context')
        cur = _TrackedReader(cursor)
        cur.execute(sql.V3_PATH)
        v2 = collect_v2(cur)
        cur.execute(coverage_sql.query().encode())
        v3 = coverage_compare.validate(cur.fetchone()[0])
        return NativeCatalogSample(v2, v3)
    except Exception:
        raise Refused('window-origin-reader-failed') from None
    except BaseException:
        raise KeyboardInterrupt from None


def collect_source(snapshot):
    """Use the authenticated holder's imported snapshot; no standalone login."""
    from first_transition_window_backup import NativeSourceSnapshot
    require(type(snapshot) is NativeSourceSnapshot, 'window-origin-reader-context')
    with snapshot.reader() as cursor:
        return collect_on_cursor(cursor)


def compare_recovery(expected, actual):
    """No repair: strict V2 catalog/count/settings and all nine V3 categories.

    LOGIN normalization follows the canonical clone projection; persisted
    settings remain inventory-exact. In particular this does NOT strip managed
    preload or turn source settings into a clone replay authorization.
    """
    try:
        require(type(expected) is NativeCatalogSample and type(actual) is NativeCatalogSample,
                'window-origin-reader-shape')
        left, right = (json.loads(value._encoded) for value in (expected, actual))
        # Only the expected clone policy projects source LOGIN. Applying that
        # projection to the observed clone would hide excess login privileges.
        v2_left = v2_inventory_view(v2_projection(left['v2']))
        v2_right = v2_inventory_view(right['v2'])
        v3 = coverage_compare.compare(left['v3'], right['v3'])
        checks = dict(catalog=v2_left['manifest'] == v2_right['manifest'],
                      row_counts=v2_left['row_counts'] == v2_right['row_counts'],
                      settings=v2_left['settings'] == v2_right['settings'])
        return dict(equal=all(checks.values()) and v3['equal'], v2=checks,
                    v3_categories=v3['categories'], automatic_repair=False,
                    v2_login_projection='canonical-isolated-clone', raw_source_settings_equal_claimed=False)
    except Exception:
        raise Refused('window-origin-recovery-compare-failed') from None


def require_recovery_match(expected, actual):
    result = compare_recovery(expected, actual)
    require(result['equal'], 'window-origin-recovery-mismatch')
    return result


class NativeRecoveryGate:
    """Strict metadata admission before exactly one replay in an owned clone.

    Caller still owes physical restore/artifact custody, cluster isolation,
    after-state collection and resource cleanup. This result is NOT an A8
    receipt. Sample, state and replay MUST be collected from the same pinned
    clone and bound to request/dump/companion by the future native runner; this
    standalone gate cannot prove those cross-port bindings. Never infer
    isolation from a different database identity.
    """
    def __init__(self, plan, expected, captured, request_digest):
        from first_transition_adapter import Plan
        from first_transition_database import DatabaseExpectation
        require(isinstance(plan, Plan) and isinstance(expected, DatabaseExpectation)
                and expected.validated().ledger == plan.baseline and type(captured) is NativeCatalogSample
                and type(request_digest) is str and len(request_digest) == 64
                and all(c in '0123456789abcdef' for c in request_digest), 'window-origin-recovery-config')
        self.plan, self.expected, self.captured, self.request_digest = plan, expected, captured, request_digest
        self.used = False

    def _state(self, value, baseline):
        require(type(value) is dict and set(value) == {'identity', 'ledger', 'invalid', 'catalog'},
                'window-origin-recovery-state')
        identity = value['identity']
        require(type(identity) is tuple and len(identity) == 3 and type(identity[0]) is str
                and identity[0].isdigit() and type(identity[1]) is int and identity[1] > 0
                and type(identity[2]) is str and 0 < len(identity[2]) <= 63
                and digest(list(identity)) != self.expected.identity
                and type(value['ledger']) is tuple and value['ledger'] == baseline
                and type(value['invalid']) is int and value['invalid'] == 0
                and type(value['catalog']) is str and len(value['catalog']) == 64
                and all(c in '0123456789abcdef' for c in value['catalog']), 'window-origin-recovery-state')
        return identity

    def run(self, restored, *, observe, replay):
        require(not self.used, 'window-origin-recovery-used')
        self.used = True
        try:
            require(callable(observe) and callable(replay), 'window-origin-recovery-config')
            comparison = require_recovery_match(self.captured, restored)
            require(all(row['valid'] is True and row['ready'] is True and row['live'] is True
                        for row in json.loads(restored._encoded)['v3']['indexes']),
                    'window-origin-recovery-state')
            before = observe()
            identity = self._state(before, self.plan.baseline)
            require(before['catalog'] == self.expected.catalog, 'window-origin-recovery-state')
            applied = replay()
            require(type(applied) is int and applied == len(self.plan.pending), 'window-origin-replay-result')
            after = observe()
            require(self._state(after, tuple(sorted(m.name for m in self.plan.migrations))) == identity,
                    'window-origin-recovery-state')
            return dict(schema='igreja12.native-catalog-replay/1', comparison=comparison,
                        request_digest=self.request_digest, a8_window_proven=False,
                        clone_rehearsal=dict(migrations_verified=True,
                            clone_identity=digest(['window-clone', *identity, self.request_digest]),
                            cluster_global_ddl_possible=True, applied=applied,
                            final_ledger=len(after['ledger']), concurrent=sum(m.concurrent for m in self.plan.pending),
                            sql_digest=digest([(m.name, m.sha256) for m in self.plan.pending]),
                            final_schema_digest=after['catalog']))
        except Exception:
            raise Refused('window-origin-recovery-failed') from None
        except BaseException:
            raise KeyboardInterrupt from None
