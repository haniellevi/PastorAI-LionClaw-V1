"""Read-only catalogue proof for additive promotion and supported code recovery.

Expected catalogues must be rebuilt from nominal baseline/candidate migrations,
never captured from an unverified live database and relabelled as expected.
This module does not apply SQL, restart consumers or authorize a release.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

_QUERIES = {
    'relations': """SELECT c.relname, jsonb_build_array(c.relkind, c.relrowsecurity, c.relforcerowsecurity, pg_get_userbyid(c.relowner), c.reloptions)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S')""",
    'columns': """SELECT c.relname||'.'||a.attname,
        jsonb_build_array(format_type(a.atttypid,a.atttypmod), a.attnotnull,
            pg_get_expr(d.adbin,d.adrelid),a.attidentity,a.attgenerated,a.attacl)
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m') AND a.attnum>0 AND NOT a.attisdropped""",
    'constraints': """SELECT c.relname||'.'||k.conname, to_jsonb(pg_get_constraintdef(k.oid,true))
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'""",
    'policies': """SELECT c.relname||'.'||p.polname,
        jsonb_build_array(p.polcmd,p.polpermissive,
            (SELECT array_agg(CASE WHEN role_id=0 THEN 'public' ELSE pg_get_userbyid(role_id) END ORDER BY CASE WHEN role_id=0 THEN 'public' ELSE pg_get_userbyid(role_id) END)
             FROM unnest(p.polroles) role_id),pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid))
        FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'""",
    'table_acl': """SELECT c.relname||'.'||CASE WHEN a.grantee=0 THEN 'public' ELSE pg_get_userbyid(a.grantee) END||'.'||pg_get_userbyid(a.grantor)||'.'||a.privilege_type,
        jsonb_build_array(pg_get_userbyid(a.grantor),a.is_grantable)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault(CASE WHEN c.relkind='S' THEN 's'::"char" ELSE 'r'::"char" END,c.relowner))) a
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S')""",
    'functions': """SELECT p.proname||'('||pg_get_function_identity_arguments(p.oid)||')',
        jsonb_build_array(pg_get_functiondef(p.oid),p.prosecdef,p.proconfig,pg_get_userbyid(p.proowner),
          (SELECT jsonb_agg(jsonb_build_array(CASE WHEN a.grantee=0 THEN 'public' ELSE pg_get_userbyid(a.grantee) END,
             pg_get_userbyid(a.grantor),a.privilege_type,a.is_grantable) ORDER BY CASE WHEN a.grantee=0 THEN 'public' ELSE pg_get_userbyid(a.grantee) END,a.privilege_type)
           FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a))
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND p.prokind IN ('f','p')""",
    'triggers': """SELECT c.relname||'.'||t.tgname,jsonb_build_array(pg_get_triggerdef(t.oid,true),t.tgenabled)
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal""",
    'indices': """SELECT c.relname,jsonb_build_array(pg_get_indexdef(c.oid),table_class.relname,i.indisunique,i.indisvalid,i.indisready)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_index i ON i.indexrelid=c.oid JOIN pg_class table_class ON table_class.oid=i.indrelid
        WHERE n.nspname='public' AND c.relkind='i'""",
    'views': """SELECT c.relname,to_jsonb(pg_get_viewdef(c.oid,true))
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('v','m')""",
    'roles': """SELECT rolname,jsonb_build_array(rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,rolbypassrls)
        FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role','agent_runtime')""",
    'role_memberships': """SELECT parent.rolname||'.'||member.rolname,
        jsonb_build_array(m.admin_option,m.inherit_option,m.set_option)
        FROM pg_auth_members m JOIN pg_roles parent ON parent.oid=m.roleid JOIN pg_roles member ON member.oid=m.member
        WHERE parent.rolname IN ('anon','authenticated','service_role','agent_runtime')
           OR member.rolname IN ('anon','authenticated','service_role','agent_runtime')""",
    'default_acl': """SELECT pg_get_userbyid(d.defaclrole)||'.'||d.defaclobjtype::text||'.'||
           CASE WHEN a.grantee=0 THEN 'public' ELSE pg_get_userbyid(a.grantee) END||'.'||a.privilege_type,
           jsonb_build_array(pg_get_userbyid(a.grantor),a.is_grantable)
        FROM pg_default_acl d JOIN pg_namespace n ON n.oid=d.defaclnamespace
        CROSS JOIN LATERAL aclexplode(d.defaclacl) a WHERE n.nspname='public'""",
    'sequences': """SELECT c.relname,jsonb_build_array(format_type(s.seqtypid,NULL),s.seqstart,s.seqincrement,s.seqmax,s.seqmin,s.seqcache,s.seqcycle)
        FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public'""",
    'enums': """SELECT t.typname,to_jsonb(array_agg(e.enumlabel ORDER BY e.enumsortorder))
        FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace JOIN pg_enum e ON e.enumtypid=t.oid
        WHERE n.nspname='public' GROUP BY t.typname""",
}


class SchemaCompatibilityError(ValueError):
    pass


def capture_catalog(connection) -> dict:
    """Capture schema only, using the caller's existing read-only transaction."""
    return {kind: dict(connection.exec_driver_sql(query).all()) for kind, query in _QUERIES.items()}


def _manifest(names: Sequence[str]) -> set[str]:
    if not names or len(names) != len(set(names)) or any(
        not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_]+\.sql', name) for name in names
    ):
        raise SchemaCompatibilityError('invalid migration manifest')
    return set(names)


def verify_additive_compatibility(*, previous: Mapping, candidate: Mapping, live: Mapping,
                                  previous_migrations: Sequence[str], candidate_migrations: Sequence[str],
                                  applied_migrations: Sequence[str]) -> None:
    """Fail closed on drift and on changes to any previous catalogue contract.

    Additional ledger entries are accepted only when they are exactly the
    candidate manifest, and the complete live catalogue matches its independent
    reconstructed expectation. No blanket allowance for ledger extras exists.
    """
    old, new, applied = map(_manifest, (previous_migrations, candidate_migrations, applied_migrations))
    if not old <= new or applied != new:
        raise SchemaCompatibilityError('migration manifest mismatch')
    if set(previous) != set(_QUERIES) or set(candidate) != set(_QUERIES) or set(live) != set(_QUERIES):
        raise SchemaCompatibilityError('incomplete catalogue contract')
    if candidate != live:
        raise SchemaCompatibilityError('live catalogue drift')
    if any(not isinstance(catalogue[kind], Mapping) for catalogue in (previous, candidate, live) for kind in _QUERIES):
        raise SchemaCompatibilityError('invalid catalogue contract')
    for catalogue in (previous, candidate):
        tenant_role = catalogue['roles'].get('authenticated')
        if not isinstance(tenant_role, list) or len(tenant_role) != 7 or tenant_role[0] or tenant_role[6]:
            raise SchemaCompatibilityError('tenant role is privileged or unverifiable')
        if any(key.endswith('.authenticated') for key in catalogue['role_memberships']):
            raise SchemaCompatibilityError('tenant role membership requires separate review')
    for kind in ('roles', 'role_memberships', 'default_acl'):
        if previous[kind] != candidate[kind]:
            raise SchemaCompatibilityError('previous schema contract changed')
    # An extra permissive policy or grant on an existing table can weaken the
    # previous contract even when every old definition still exists.
    for kind in ('policies', 'table_acl', 'triggers', 'constraints'):
        for name in candidate[kind]:
            table = name.split('.', 1)[0]
            if table in previous['relations'] and name not in previous[kind]:
                raise SchemaCompatibilityError('previous schema contract changed')
    # Old code omits new columns on INSERT. A required value with no default
    # breaks it, even after a successful backfill of the existing rows.
    for name, column in candidate['columns'].items():
        if name not in previous['columns'] and name.split('.', 1)[0] in previous['relations']:
            if column[1] and column[2] is None and not column[3] and not column[4]:
                raise SchemaCompatibilityError('previous schema contract changed')
    for name, index in candidate['indices'].items():
        if name not in previous['indices'] and index[1] in previous['relations'] and index[2]:
            raise SchemaCompatibilityError('previous schema contract changed')
    for kind in _QUERIES:
        for name, definition in previous[kind].items():
            if name not in candidate[kind] or candidate[kind][name] != definition:
                # Definitions can contain expressions; expose a static code only.
                raise SchemaCompatibilityError('previous schema contract changed')
