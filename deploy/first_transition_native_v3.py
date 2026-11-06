"""Private catalog capture protocol v3. No row/secret/Storage bytes selected."""
import json
from pathlib import Path

def acl(column):
    # Column expressions below are static source constants, never user input.
    return "CASE WHEN "+column+" IS NULL THEN NULL ELSE (SELECT coalesce(jsonb_agg(jsonb_build_object('grantor',pg_get_userbyid(g.grantor),'grantee',CASE WHEN g.grantee=0 THEN NULL ELSE pg_get_userbyid(g.grantee) END,'privilege',g.privilege_type,'grant_option',g.is_grantable) ORDER BY g.grantor,g.grantee,g.privilege_type,g.is_grantable),'[]'::jsonb) FROM aclexplode("+column+") g) END"

NON_SYSTEM="n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'"
CATEGORIES={
 'schemas':"SELECT n.nspname AS schema,pg_get_userbyid(n.nspowner) AS owner,"+acl('n.nspacl')+" AS acl FROM pg_namespace n WHERE "+NON_SYSTEM,
 'relations':"SELECT n.nspname AS schema,c.relname AS name,c.relkind AS kind,pg_get_userbyid(c.relowner) AS owner,c.relrowsecurity AS rls,c.relforcerowsecurity AS force_rls,"+acl('c.relacl')+" AS acl FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE "+NON_SYSTEM+" AND c.relkind IN('r','p','m','v','f','S')",
 'columns':"SELECT n.nspname AS schema,c.relname AS relation,a.attname AS name,"+acl('a.attacl')+" AS acl FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE "+NON_SYSTEM+" AND c.relkind IN('r','p','m','v','f','S') AND a.attnum>0 AND NOT a.attisdropped",
 'types':"SELECT n.nspname AS schema,t.typname AS name,t.typtype AS kind,pg_get_userbyid(t.typowner) AS owner,"+acl('t.typacl')+" AS acl FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE "+NON_SYSTEM,
 'routines':"SELECT n.nspname AS schema,p.proname AS name,pg_get_function_identity_arguments(p.oid) AS args,p.prokind AS kind,pg_get_userbyid(p.proowner) AS owner,p.prosecdef AS security_definer,"+acl('p.proacl')+" AS acl,CASE WHEN p.prokind IN('f','p','w') THEN encode(sha256(convert_to(pg_get_functiondef(p.oid),'UTF8')),'hex') ELSE NULL END AS definition_sha256 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE "+NON_SYSTEM,
 'default_acl':"SELECT pg_get_userbyid(d.defaclrole) AS owner,n.nspname AS schema,d.defaclobjtype AS kind,"+acl('d.defaclacl')+" AS acl FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace WHERE n.oid IS NULL OR ("+NON_SYSTEM+")",
 'policies':"SELECT n.nspname AS schema,c.relname AS relation,p.polname AS name,p.polcmd AS command,p.polpermissive AS permissive,(SELECT jsonb_agg(CASE WHEN x=0 THEN NULL ELSE pg_get_userbyid(x) END ORDER BY x) FROM unnest(p.polroles) x) AS roles,encode(sha256(convert_to(pg_get_expr(p.polqual,p.polrelid),'UTF8')),'hex') AS using_sha256,encode(sha256(convert_to(pg_get_expr(p.polwithcheck,p.polrelid),'UTF8')),'hex') AS check_sha256 FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE "+NON_SYSTEM,
 'indexes':"SELECT n.nspname AS schema,c.relname AS relation,ic.relname AS name,i.indisvalid AS valid,i.indisready AS ready,i.indislive AS live,encode(sha256(convert_to(pg_get_indexdef(i.indexrelid),'UTF8')),'hex') AS definition_sha256 FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid JOIN pg_class ic ON ic.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE "+NON_SYSTEM,
}
OBJECTS="""
SELECT 'pg_namespace'::regclass::oid AS classoid,n.oid AS objoid,0 AS subid,'schemas' AS category,jsonb_build_array(n.nspname) AS identity FROM pg_namespace n WHERE {ns}
UNION ALL SELECT 'pg_class'::regclass::oid,c.oid,0,'relations',jsonb_build_array(n.nspname,c.relname,c.relkind) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {ns} AND c.relkind IN('r','p','m','v','f','S')
UNION ALL SELECT 'pg_class'::regclass::oid,c.oid,a.attnum,'columns',jsonb_build_array(n.nspname,c.relname,a.attname) FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {ns} AND c.relkind IN('r','p','m','v','f','S') AND a.attnum>0 AND NOT a.attisdropped
UNION ALL SELECT 'pg_type'::regclass::oid,t.oid,0,'types',jsonb_build_array(n.nspname,t.typname) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE {ns}
UNION ALL SELECT 'pg_proc'::regclass::oid,p.oid,0,'routines',jsonb_build_array(n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),p.prokind) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE {ns}
""".format(ns=NON_SYSTEM)
CATEGORIES['initial_privileges']="SELECT o.category,o.identity,i.privtype AS privilege_origin,"+acl('i.initprivs')+" AS acl FROM pg_init_privs i JOIN objects o ON o.classoid=i.classoid AND o.objoid=i.objoid AND o.subid=i.objsubid"


def query():
    fields=[]
    for name,sql in CATEGORIES.items():
        fields.extend(["'"+name+"'","(SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]'::jsonb) FROM ("+sql+") x)"])
    return "WITH objects AS ("+OBJECTS+") SELECT jsonb_build_object("+','.join(fields)+")"


def capture_local(docker,container,database):
    # Same observer settings in source and clone. Function signatures/definition
    # rendering must not depend on each role's search_path.
    import platform
    if platform.node()!='raniel-Legion-5-Pro':raise ValueError('local-fixture-only')
    q="BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY; SET LOCAL statement_timeout='8s'; SET LOCAL lock_timeout='1s'; SET LOCAL search_path=pg_catalog; "+query()+"; ROLLBACK;"
    raw=docker.sql(container,q.encode(),database=database)
    if len(raw)>2097152:raise ValueError('coverage-output-bound')
    return json.loads(raw)


def public_shape_query():
    return "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY; SET LOCAL statement_timeout='8s'; SET LOCAL lock_timeout='1s'; SET LOCAL search_path=pg_catalog; SELECT jsonb_object_agg(key,jsonb_array_length(value)) AS category_counts FROM ("+query()+") q(metadata) CROSS JOIN LATERAL jsonb_each(metadata); ROLLBACK;"

if __name__=='__main__':
    Path('catalog-v3.sql').write_text(query()+';\n')
    Path('catalog-v3-shape.sql').write_text(public_shape_query()+'\n')
