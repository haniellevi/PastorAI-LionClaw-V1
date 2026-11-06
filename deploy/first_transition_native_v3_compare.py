"""Strict v3 comparison. Public output only aggregates, never object identities."""
import json
KEYS={'schemas':('schema',),'relations':('schema','name','kind'),'columns':('schema','relation','name'),
      'types':('schema','name'),'routines':('schema','name','args','kind'),
      'default_acl':('owner','schema','kind'),'policies':('schema','relation','name'),
      'indexes':('schema','relation','name'),'initial_privileges':('category','identity','privilege_origin')}

FIELDS={
 'schemas':{'schema','owner','acl'},
 'relations':{'schema','name','kind','owner','rls','force_rls','acl'},
 'columns':{'schema','relation','name','acl'},
 'types':{'schema','name','kind','owner','acl'},
 'routines':{'schema','name','args','kind','owner','security_definer','acl','definition_sha256'},
 'default_acl':{'owner','schema','kind','acl'},
 'policies':{'schema','relation','name','command','permissive','roles','using_sha256','check_sha256'},
 'indexes':{'schema','relation','name','valid','ready','live','definition_sha256'},
 'initial_privileges':{'category','identity','privilege_origin','acl'},
}


def canonical(value):
    if isinstance(value,dict):return {k:canonical(v) for k,v in sorted(value.items())}
    if isinstance(value,list):return sorted((canonical(v) for v in value),key=lambda v:json.dumps(v,sort_keys=True))
    return value


def validate(value):
    if not isinstance(value,dict) or set(value)!=set(KEYS):raise ValueError('coverage-categories')
    for name,rows in value.items():
        if not isinstance(rows,list) or len(rows)>10000:raise ValueError('coverage-row-bound')
        seen=set()
        for row in rows:
            if not isinstance(row,dict) or set(row)!=FIELDS[name]:raise ValueError('coverage-required-fields')
            key=json.dumps([row[k] for k in KEYS[name]],sort_keys=True)
            if key in seen:raise ValueError('coverage-duplicate')
            seen.add(key)
            if 'acl' in row and row['acl'] is not None:
                if not isinstance(row['acl'],list):raise ValueError('coverage-acl-type')
                for grant in row['acl']:
                    if not isinstance(grant,dict) or set(grant)!={'grantor','grantee','privilege','grant_option'}:raise ValueError('coverage-acl-fields')
                    if not isinstance(grant['grantor'],str) or not(grant['grantee'] is None or isinstance(grant['grantee'],str)) or not isinstance(grant['privilege'],str) or type(grant['grant_option']) is not bool:raise ValueError('coverage-acl-values')
    return value


def compare(expected,actual):
    validate(expected);validate(actual);out={}
    for name,keys in KEYS.items():
        def index(rows):return {json.dumps([r[k] for k in keys],sort_keys=True):r for r in rows}
        left=index(expected[name]);right=index(actual[name]);shared=set(left)&set(right)
        missing=len(set(left)-set(right));extra=len(set(right)-set(left))
        changed=sum(canonical(left[k])!=canonical(right[k]) for k in shared)
        # Composite identities are positional. Match keys before comparing rows;
        # never sort identities together as if their elements were a set.
        out[name]={'expected':len(left),'actual':len(right),'missing':missing,
                   'extra':extra,'changed':changed,'equal':missing==0 and extra==0 and changed==0}
    return {'protocol':'catalog-v3-all-schema-object-acls','equal':all(x['equal'] for x in out.values()),'categories':out,'automatic_repair':False}
