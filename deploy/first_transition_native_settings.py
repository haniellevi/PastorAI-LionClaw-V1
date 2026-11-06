"""Pure strict V2 settings profile; no IO, SQL, credentials or runtime effects.

Eight admitted keys, four persisted scope combinations. Unknown values/keys,
missing safety values and duplicate records are refused, never inferred safe.
This covers this V2 profile, not every PostgreSQL GUC or cluster config file.
"""
import csv
import re

KEYS=frozenset(('search_path','statement_timeout','lock_timeout',
    'idle_in_transaction_session_timeout','default_transaction_read_only',
    'app.settings.jwt_exp','log_statement','session_preload_libraries'))
TIME_KEYS=frozenset(('statement_timeout','lock_timeout','idle_in_transaction_session_timeout'))
SCOPES=('all','database','role','role-database')
NAME=re.compile('[a-z_][a-z0-9_]{0,62}')

class Refused(ValueError):pass

def need(ok,code):
    if not ok:raise Refused(code)


def search_path(value):
    need(type(value)is str and 0<len(value)<=1024 and '\n' not in value and '\r' not in value,
         'v2-search-path')
    try:atoms=next(csv.reader([value],skipinitialspace=True,strict=True))
    except (csv.Error,StopIteration):raise Refused('v2-search-path') from None
    raw=value.split(',')
    need(0<len(atoms)<=32 and len(raw)==len(atoms),'v2-search-path')
    for index,atom in enumerate(atoms):
        need(atom in ('$user',r'\$user') or re.fullmatch('[a-zA-Z_][a-zA-Z0-9_]*',atom),
             'v2-search-path')
        if atom==r'\$user' or re.search('[A-Z]',atom):
            need(raw[index].strip()=='"'+atom+'"','v2-search-path')
    return ', '.join('"'+x+'"' for x in atoms)


def normalize_value(key,value):
    need(type(key)is str and key in KEYS,'v2-unknown-setting')
    need(type(value)is str and len(value)<=1024,'v2-setting-value')
    if key=='search_path':return search_path(value)
    if key in TIME_KEYS:
        found=re.fullmatch('([0-9]{1,12})(ms|s|min|h|d)?',value)
        need(found is not None,'v2-setting-time')
        number=int(found[1])*{None:1,'ms':1,'s':1000,'min':60000,'h':3600000,'d':86400000}[found[2]]
        need(number<=2147483647,'v2-setting-time')
        return str(number)
    if key=='app.settings.jwt_exp':
        need(re.fullmatch('[0-9]{1,12}',value) is not None,'v2-jwt-exp')
        need(int(value)<=2147483647,'v2-jwt-exp')
        return str(int(value))
    if key=='default_transaction_read_only':
        need(value in ('on','off','true','false','yes','no','1','0'),'v2-readonly-value')
        return 'on' if value in ('on','true','yes','1') else 'off'
    if key=='log_statement':
        need(value=='none','v2-logging-unsafe');return value
    need(value=='','v2-preload-unsafe');return value


def _normalize(rows,*,managed_inventory=False):
    need(type(rows)is list and len(rows)<=1000,'v2-settings-shape')
    result=[];seen=set()
    for row in rows:
        need(type(row)is dict and set(row)=={'scope','role','key','value'},'v2-setting-shape')
        scope,role=row['scope'],row['role']
        need(type(scope)is str and scope in SCOPES,'v2-setting-scope')
        if scope in ('all','database'):need(role is None,'v2-setting-role')
        else:need(type(role)is str and NAME.fullmatch(role),'v2-setting-role')
        key=row['key'];need(type(key)is str and key in KEYS,'v2-unknown-setting')
        identity=(scope,role,key);need(identity not in seen,'v2-setting-duplicate');seen.add(identity)
        # Preserve one observed managed-role inventory entry verbatim. This is
        # data capture only: effective-session and replay validation stay strict.
        if (managed_inventory and scope=='role' and role=='authenticator' and
            key=='session_preload_libraries' and type(row['value'])is str and
            row['value']=='supautils, safeupdate'):
            value=row['value']
        else:value=normalize_value(key,row['value'])
        result.append(dict(scope=scope,role=role,key=key,value=value))
    return sorted(result,key=lambda r:(SCOPES.index(r['scope']),r['role'] or '',r['key']))


def normalize(rows):
    return _normalize(rows)


def normalize_inventory(rows,*,profile):
    """Managed catalog data, never permission to load libraries or replay it."""
    need(type(profile)is str and profile=='supabase-17.6.1.127','v2-inventory-profile')
    return _normalize(rows,managed_inventory=True)


def expected_effective(rows,role='postgres'):
    need(type(role)is str and NAME.fullmatch(role),'v2-setting-role')
    result={}
    for row in normalize(rows):
        if row['role'] in (None,role):result[row['key']]=row['value']
    need(set(result)==KEYS,'v2-effective-profile-incomplete')
    return result


def normalize_effective(value):
    need(type(value)is dict and set(value)==KEYS,'v2-effective-shape')
    return {key:normalize_value(key,value[key]) for key in sorted(KEYS)}


def compare(expected,actual):
    left=normalize(expected);right=normalize(actual)
    return dict(equal=left==right,expected_rows=len(left),actual_rows=len(right),
        missing=len({(x['scope'],x['role'],x['key']) for x in left}-
                    {(x['scope'],x['role'],x['key']) for x in right}),
        automatic_repair=False)
