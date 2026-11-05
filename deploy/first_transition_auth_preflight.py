"""Fixed whitelisted SELECT for admission before any provider login. No IO."""
import hashlib
import math
import json
import re

QUERY = r'''
WITH wanted(name,expected,expected_source) AS (VALUES
 ('log_statement','ddl','configuration file'),('session_preload_libraries','supautils','configuration file'),('local_preload_libraries','','default')
), target AS MATERIALIZED (
 SELECT r.oid AS role_oid,d.oid AS db_oid,s.system_identifier::text AS sysid
 FROM pg_catalog.pg_roles r CROSS JOIN pg_catalog.pg_database d
 CROSS JOIN pg_catalog.pg_control_system() s
 WHERE r.rolname='postgres' AND d.datname='postgres'
), effective AS (
 SELECT w.name,w.expected,w.expected_source,p.name AS observed_name,p.setting,p.reset_val,p.source,p.pending_restart
 FROM wanted w LEFT JOIN pg_catalog.pg_settings p ON p.name=w.name
), persisted AS (
 SELECT s.setdatabase,s.setrole,pg_catalog.split_part(v.entry,'=',1) AS name,
 1 AS present
 FROM pg_catalog.pg_db_role_setting s CROSS JOIN target t
 CROSS JOIN LATERAL pg_catalog.unnest(s.setconfig) v(entry)
 WHERE s.setdatabase IN (0,t.db_oid) AND s.setrole IN (0,t.role_oid)
 AND pg_catalog.split_part(v.entry,'=',1) IN ('log_statement','session_preload_libraries','local_preload_libraries')
), auth AS (
 SELECT a.usesysid,a.datid,a.backend_type FROM pg_catalog.pg_stat_activity a
 WHERE a.pid=pg_catalog.pg_backend_pid()
)
SELECT pg_catalog.current_database()='postgres' AS database_ok,
 current_user='postgres' AS current_role_ok, session_user='postgres' AS session_role_ok,
 (SELECT pg_catalog.count(*) FROM target) AS target_count,
 (SELECT pg_catalog.count(observed_name) FROM effective) AS effective_setting_count,
 (SELECT coalesce(pg_catalog.bool_and(setting=expected AND reset_val=expected AND source=expected_source AND pending_restart IS FALSE),false) FROM effective) AS managed_profile_conformant,
 (SELECT pg_catalog.count(*) FROM effective WHERE source IS DISTINCT FROM expected_source) AS masked_or_unknown_sources,
 (SELECT pg_catalog.count(*) FROM auth) AS authenticated_backend_count,
 ((SELECT coalesce(pg_catalog.bool_and(a.usesysid=t.role_oid AND a.datid=t.db_oid AND a.backend_type='client backend'),false)
 FROM auth a CROSS JOIN target t) AND pg_catalog.current_setting('role')='none' AND
 pg_catalog.current_setting('session_authorization')='postgres') AS authentication_state_unmasked,
 (SELECT pg_catalog.count(*) FROM persisted) AS relevant_persisted_entries,
 (SELECT pg_catalog.count(*) FROM persisted) AS unsafe_persisted_entries,
 (SELECT pg_catalog.count(*) FROM (SELECT 1 FROM persisted GROUP BY setdatabase,setrole,name HAVING pg_catalog.count(*)>1) duplicates) AS duplicate_persisted_groups,
 (SELECT pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to('["'||sysid||'",'||db_oid::text||',"postgres"]','UTF8')),'hex') FROM target) AS source_identity_sha256,
 extract(epoch FROM pg_catalog.clock_timestamp())::double precision AS observed_at,
 pg_catalog.current_setting('server_version_num')::integer AS server_version_num,
 'supabase-17.6.1.127'::text AS startup_profile
'''


def query_sha256():
    return hashlib.sha256(QUERY.encode()).hexdigest()


def _validate_safety_row(row, *, expected_identity, now):
    flags=('database_ok','current_role_ok','session_role_ok','managed_profile_conformant','authentication_state_unmasked')
    counts={'target_count':1,'effective_setting_count':3,'masked_or_unknown_sources':0,
            'authenticated_backend_count':1,'unsafe_persisted_entries':0,'duplicate_persisted_groups':0,'relevant_persisted_entries':0}
    expected=set(flags)|set(counts)|{'source_identity_sha256','observed_at','server_version_num','startup_profile'}
    if type(row)is not dict or set(row)!=expected:
        raise ValueError('source-safety-shape')
    if not all(row[k]is True for k in flags) or not all(type(row[k])is int and row[k]==v for k,v in counts.items()):
        raise ValueError('source-safety-refused')
    if not(row['startup_profile']=='supabase-17.6.1.127' and type(row['server_version_num'])is int and 170000<=row['server_version_num']<180000 and
           row['source_identity_sha256']==expected_identity and type(row['observed_at'])in(int,float) and
           math.isfinite(row['observed_at']) and type(now)in(int,float) and math.isfinite(now) and
           now-60<=row['observed_at']<=now):
        raise ValueError('source-safety-binding-freshness')
    return dict(safe=True,source_identity_sha256=expected_identity,observed_at=row['observed_at'],
                query_sha256=query_sha256(),scope='managed-startup-profile-for-read-only-metadata-only',
                credentials_read=False,provider_login_performed=False,production_go=False)

REQUEST_SCHEMA='igreja12.auth-source-request/2'
REQUEST_FIELDS=frozenset(('schema','nonce','controller_plan_digest','source_identity_sha256','baseline_v1_digest',
    'catalog_sha256','ledger_names_sha256','endpoint_identity_sha256','source_descriptor_sha256','ca_sha256',
    'code_bundle_sha256','expected_ledger_names','project','database','role','limits','startup_profile','expected_server_version_num'))
HEX_FIELDS=REQUEST_FIELDS-{'schema','expected_ledger_names','project','database','role','limits','startup_profile','expected_server_version_num'}
LIMITS=dict(maximum_seconds=35,connect_seconds=8,query_timeout_ms=8000,safety_max_age_seconds=60)
PROJECT='pffafnchtxbimpwyaczq'
LEDGER_SHA='d66425d621c06f04adcad3f6155878012ba1c585080c0801319a5684fc87e695'


def need(ok,code):
    if not ok:raise ValueError(code)


def hex64(value):
    return type(value)is str and re.fullmatch('[0-9a-f]{64}',value)is not None


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()


def validate_request(request):
    need(type(request)is dict and set(request)==REQUEST_FIELDS and request['schema']==REQUEST_SCHEMA,'auth-request-shape')
    need(all(hex64(request[k]) for k in HEX_FIELDS),'auth-request-digest')
    need(request['project']==PROJECT and request['database']==request['role']=='postgres' and request['startup_profile']=='supabase-17.6.1.127' and
         type(request['expected_server_version_num'])is int and request['expected_server_version_num']==170006,'auth-request-scope')
    need(type(request['limits'])is dict and request['limits']==LIMITS and
         all(type(v)is int for v in request['limits'].values()),'auth-request-limits')
    names=request['expected_ledger_names']
    need(type(names)is list and len(names)==78 and all(type(n)is str and re.fullmatch('[A-Za-z0-9_.-]+[.]sql',n) for n in names) and
         names==sorted(set(names)) and digest(names)==LEDGER_SHA and request['ledger_names_sha256']==LEDGER_SHA,
         'auth-request-ledger')
    need(digest([names,request['catalog_sha256']])==request['baseline_v1_digest'],'auth-request-baseline')
    need(digest(dict(protocol='minimal-provider-fd-json/1',endpoint=request['endpoint_identity_sha256']))==request['source_descriptor_sha256'],
         'auth-request-descriptor')
    return digest(request)


def validate_safety(evidence,request,now):
    validate_request(request)
    need(type(evidence)is dict and set(evidence)=={'schema','project','query_sha256','row','startup_profile','project_release','project_release_observed_at'} and
         evidence['schema']=='igreja12.source-safety-evidence/2' and evidence['project']==PROJECT and
         evidence['query_sha256']==query_sha256() and evidence['startup_profile']==request['startup_profile'] and
         evidence['project_release']=='17.6.1.127' and type(evidence['project_release_observed_at'])in(int,float) and
         math.isfinite(evidence['project_release_observed_at']) and now-60<=evidence['project_release_observed_at']<=now,
         'auth-safety-evidence')
    _validate_safety_row(evidence['row'],expected_identity=request['source_identity_sha256'],now=now)
    need(evidence['row']['server_version_num']==request['expected_server_version_num'],'auth-safety-server-version')
    return digest(evidence)


def assess(request,report,*,now):
    """Bindings only, never authority for capture/A8/production. No I/O."""
    request_sha=validate_request(request)
    fields={'schema','outcome','request_digest','controller_plan_digest','source_identity_sha256','baseline_v1_digest',
        'catalog_sha256','ledger_names_sha256','endpoint_identity_sha256','source_descriptor_sha256','ca_sha256',
        'safety_evidence_sha256','safety_observed_at','started_at','finished_at','server_version_num','role_matches',
        'session_role_matches','read_only','repeatable_read','tls_verify_full','ssl_protocol','login_calls',
        'rollback_observed','transaction_idle_before_close','frontend_closed','server_backend_absence_proven',
        'capture_snapshot_exported','backup_created','credential_returned','credential_hashed','a8_receipt_issued',
        'production_go','operational_ready','reason','phase','database_authenticated',
        'credential_supplied_to_native_driver','source_authenticated_via_provider','password_authentication_observed',
        'startup_profile','managed_profile_conformant','managed_server_binary_attested'}
    need(type(report)is dict and set(report)==fields and report['schema']=='igreja12.auth-source-report/2' and
         report['outcome']=='passed' and report['reason'] is None and report['phase']=='completed','auth-report-shape')
    need(report['request_digest']==request_sha and all(report[k]==request[k] for k in
         ('controller_plan_digest','source_identity_sha256','baseline_v1_digest','catalog_sha256','ledger_names_sha256',
          'endpoint_identity_sha256','source_descriptor_sha256','ca_sha256','startup_profile')),'auth-report-binding')
    need(hex64(report['safety_evidence_sha256']) and type(report['login_calls'])is int and report['login_calls']==1 and
         type(report['server_version_num'])is int and report['server_version_num']==request['expected_server_version_num'] and
         report['ssl_protocol'] in ('TLSv1.2','TLSv1.3'),'auth-report-protocol')
    for key in ('role_matches','session_role_matches','read_only','repeatable_read','tls_verify_full',
                'rollback_observed','transaction_idle_before_close','frontend_closed','database_authenticated',
                'credential_supplied_to_native_driver','source_authenticated_via_provider','password_authentication_observed','managed_profile_conformant'):
        need(report[key]is True,'auth-report-context-closure')
    for key in ('server_backend_absence_proven','capture_snapshot_exported','backup_created','credential_returned',
                'credential_hashed','a8_receipt_issued','production_go','operational_ready','managed_server_binary_attested'):
        need(report[key]is False,'auth-report-authority')
    start,end,observed=report['started_at'],report['finished_at'],report['safety_observed_at']
    need(all(type(v)in(int,float) and math.isfinite(v) and v>0 for v in (now,start,end,observed)) and
         start<end<=now and end-start<=LIMITS['maximum_seconds'] and now-end<=60 and
         start-60<=observed<=start,'auth-report-freshness')
    return dict(schema='igreja12.controller-auth-source-assessment/1',request_digest=request_sha,
        report_digest=digest(report),controller_plan_digest=request['controller_plan_digest'],
        source_identity_sha256=request['source_identity_sha256'],baseline_v1_digest=request['baseline_v1_digest'],
        metadata_consistent=True,provider_opened_by_contract=False,execution_authorized=False,
        capture_proven=False,a8_window_proven=False,receipt_emitted=False,production_go=False)
