"""Pure metadata contract for a separately reviewed future origin capture.

No connector, credential lookup, clock read, filesystem, process or IO exists.
Caller-supplied metadata can be structurally bound; it cannot authenticate its
own provenance. This module never authorizes execution or issues A8 receipts.
"""
import hashlib
import json
import math
import re

PROJECT = 'pffafnchtxbimpwyaczq'
HOST = 'srv2031318'
DAEMON = 'cca7e973-6a19-4f7f-9b51-f14f45414d2e'
RUN = 'igreja12-origin-v2-v3-capture-20261104-r11'
ROOT = '/root/igreja12-recovery/20261104-r11'
RETENTION_DEADLINE = 1794351429.2238355
R2_DUMP_SHA256 = '579856ddf0a5ae41108177d0f500d193b34b315a709d12dda69068b7f70652b7'
V3_CATEGORIES = ('schemas','relations','columns','types','routines','default_acl',
                 'policies','indexes','initial_privileges')
HEX = re.compile('[0-9a-f]{64}')
SNAPSHOT = re.compile('[0-9A-F]{8}-[0-9A-F]{8}-[1-9][0-9]*')
FORBIDDEN_KEYS = frozenset({'password','passwords','secret','secrets','token','tokens',
    'access_token','refresh_token','api_key','key','credentials','credential','dsn','url',
    'connection_string','environment','env','full_env','sql','query','rows','values',
    'code','function_body','provider_file','provider_key','settings_values','raw_output',
    'receipt','controller_receipt','a8_receipt','containment_writes'})


class Refused(Exception):
    """Fixed codes only; never include rejected caller data in the message."""


def need(condition,code):
    if not condition:
        raise Refused(code)


def digest(value):
    _public(value)
    try:
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    except (TypeError,ValueError,OverflowError,RecursionError):
        raise Refused('capture-json-shape') from None
    need(len(raw)<=131072,'capture-metadata-bound')
    return hashlib.sha256(raw).hexdigest()


def _public(value,depth=0):
    need(depth<=12,'capture-metadata-depth')
    if type(value) is dict:
        need(len(value)<=64 and all(type(k) is str for k in value),'capture-metadata-shape')
        need(not any(k.lower() in FORBIDDEN_KEYS for k in value),'capture-secret-or-payload-field')
        for item in value.values():_public(item,depth+1)
    elif type(value) is list:
        need(len(value)<=64,'capture-metadata-bound')
        for item in value:_public(item,depth+1)
    else:
        need(value is None or type(value) in (str,int,float,bool),'capture-metadata-shape')
        if type(value) is str:need(len(value)<=256,'capture-metadata-bound')
        if type(value) is float:need(math.isfinite(value),'capture-time-shape')
        if type(value) is int:need(-(1<<64)<=value<(1<<64),'capture-metadata-number')


def _shape(value,keys):
    need(type(value) is dict and set(value)==set(keys),'capture-metadata-fields')



def _fixed(value,expected):
    if type(value) is not type(expected):return False
    if type(expected) is dict:
        return set(value)==set(expected) and all(_fixed(value[k],expected[k]) for k in expected)
    return value==expected


def _hex(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def _time(value):
    if type(value) not in (int,float):return False
    try:return math.isfinite(value) and value>0
    except OverflowError:return False


def _counts(value,keys):
    _shape(value,keys)
    need(all(type(n) is int and 0<=n<=10000000 for n in value.values()),'capture-count-shape')


def pending_plan():
    """Unresolved identity/CA pins stay None; no fabricated observation exists."""
    return dict(schema='igreja12.origin-capture-plan/2',state='pending-observations',
        run_id=RUN,run_root=ROOT,project=PROJECT,host=HOST,daemon=DAEMON,
        database='postgres',role='postgres',scope='fresh-origin-read-only-v2-v3',
        provider_access='existing-protected-provider-opaque',credential_access='protected-provider-only',
        production_mutation='forbidden',synthetic_source='forbidden',derived_source='forbidden',
        operational_ready=False,a8_window_scope='excluded',retention_deadline=RETENTION_DEADLINE,
        expected_source=dict(state='pending',identity_sha256=None,descriptor_sha256=None),
        tls_policy=dict(sslmode='verify-full',ca_sha256=None,endpoint_identity_sha256=None),
        protocol_pins=dict(v1_reader_sha256=None,v2_reader_sha256=None,v3_reader_sha256=None,dump_runner_sha256=None,
                           provider_adapter_sha256=None,runtime_bundle_sha256=None),
        limits=dict(maximum_seconds=1200,work_seconds=1100,cleanup_reserve=90,
            source_phase_seconds=240,dump_seconds=90,keepalive_seconds=1,
            maximum_keepalive_gap_seconds=2,maximum_dump_bytes=104857600,
            maximum_companion_bytes=2097152,observation_max_age_seconds=60))


def validate_plan(plan,*,require_pinned=False):
    _public(plan);digest(plan)
    template=pending_plan();_shape(plan,template)
    for name,value in template.items():
        if name not in ('state','expected_source','tls_policy','protocol_pins'):
            need(_fixed(plan[name],value),'capture-plan-scope')
    _shape(plan['expected_source'],template['expected_source'])
    _shape(plan['tls_policy'],template['tls_policy'])
    _shape(plan['protocol_pins'],template['protocol_pins'])
    need(plan['tls_policy']['sslmode']=='verify-full','capture-tls-policy')
    pinned=plan['state']=='pinned-contract-only' and plan['expected_source']['state']=='pinned-for-review'
    if pinned:
        need(all(_hex(plan['expected_source'][k]) for k in ('identity_sha256','descriptor_sha256')) and
             all(_hex(plan['tls_policy'][k]) for k in ('ca_sha256','endpoint_identity_sha256')) and
             all(_hex(v) for v in plan['protocol_pins'].values()),'capture-source-pins')
    else:
        need(plan['state']=='pending-observations' and plan['expected_source']==template['expected_source']
             and plan['tls_policy']==template['tls_policy'] and
             plan['protocol_pins']==template['protocol_pins'],'capture-pending-pins')
    need(not require_pinned or pinned,'capture-observations-pending')
    return dict(state='pinned-contract-only' if pinned else 'pending-observations',
                plan_digest=digest(plan),operational_ready=False,capture_executed=False,
                receipt_emitted=False,a8_window_proven=False)


def _tls(record,plan,source_start,source_end):
    _shape(record,('sslmode','full_verification','ca_sha256','endpoint_identity_sha256',
                  'evidence_sha256','observed_at'))
    need(record['sslmode']=='verify-full' and record['full_verification'] is True and
         record['ca_sha256']==plan['tls_policy']['ca_sha256'] and
         record['endpoint_identity_sha256']==plan['tls_policy']['endpoint_identity_sha256'] and
         _hex(record['evidence_sha256']),'capture-tls-binding')
    need(_time(record['observed_at']) and source_start<=record['observed_at']<=source_end,
         'capture-tls-time')


def _pin(pin,path,limit,start,end):
    _shape(pin,('path','sha256','size','dev','ino','mtime_ns','ctime_ns','owner','mode','nlink',
                'retention_deadline'))
    need(pin['path']==path and _hex(pin['sha256']) and type(pin['size']) is int and
         5<pin['size']<=limit,'capture-artifact-shape')
    need(all(type(pin[k]) is int and pin[k]>=0 for k in
             ('dev','ino','mtime_ns','ctime_ns','owner','mode','nlink')) and
         pin['ino']>0 and pin['owner']==0 and pin['mode']==0o600 and pin['nlink']==1,
         'capture-artifact-private-pin')
    need(pin['retention_deadline']==RETENTION_DEADLINE and
         start<=pin['mtime_ns']/1e9<=end and start<=pin['ctime_ns']/1e9<=end,
         'capture-artifact-time-retention')


def assess_capture(plan,metadata,*,now):
    """Validate bindings only; a trusted future adapter must observe reality.

    Even a structurally complete caller object never becomes authorization,
    physical source proof, operational readiness or a controller/window receipt.
    """
    validate_plan(plan,require_pinned=True)
    _public(metadata);digest(metadata)
    _shape(metadata,('schema','capture_id','plan_digest','scope','origin_kind','project','host',
        'daemon','database','role','source_identity_sha256','source_descriptor_sha256',
        'provider_adapter_sha256','source_observation','started_at','finished_at','tls','holder','v2','v3','dump',
        'dump_pin','companion','companion_pin','closure'))
    need(metadata['schema']=='igreja12.origin-capture-observation/2' and
         metadata['plan_digest']==digest(plan) and _hex(metadata['capture_id']),
         'capture-plan-binding')
    need(all(metadata[k]==plan[k] for k in ('scope','project','host','daemon','database','role')) and
         metadata['origin_kind']=='nominal-origin-fresh','capture-origin-scope')
    source=plan['expected_source'];limits=plan['limits']
    need(metadata['source_identity_sha256']==source['identity_sha256'] and
         metadata['source_descriptor_sha256']==source['descriptor_sha256'] and
         metadata['provider_adapter_sha256']==plan['protocol_pins']['provider_adapter_sha256'],
         'capture-source-binding')
    start,end=metadata['started_at'],metadata['finished_at']
    need(all(_time(t) for t in (now,start,end)) and start<end<=now<RETENTION_DEADLINE and
         now-end<=limits['observation_max_age_seconds'] and
         end-start<=limits['source_phase_seconds'],'capture-freshness-time')
    observed=metadata['source_observation']
    _shape(observed,('identity_sha256','descriptor_sha256','observed_at'))
    need(observed['identity_sha256']==source['identity_sha256'] and
         observed['descriptor_sha256']==source['descriptor_sha256'],'capture-source-observation-binding')
    need(_time(observed['observed_at']) and
         start-limits['observation_max_age_seconds']<=observed['observed_at']<=start,
         'capture-source-observation-time')
    _shape(metadata['tls'],('holder','dump'))
    for tls in metadata['tls'].values():_tls(tls,plan,start,end)
    h=metadata['holder']
    _shape(h,('backend_pid','read_only','isolation','exported_snapshot_id','rr_snapshot_sha256',
              'opened_at','exported_at','alive_after_dump_at','before_state_sha256',
              'before_dump_state_sha256','after_dump_state_sha256'))
    need(type(h['backend_pid']) is int and h['backend_pid']>0 and h['read_only'] is True and
         h['isolation']=='repeatable-read' and type(h['exported_snapshot_id']) is str and
         SNAPSHOT.fullmatch(h['exported_snapshot_id']) and _hex(h['rr_snapshot_sha256']) and
         _hex(h['before_state_sha256']) and h['before_state_sha256']==h['before_dump_state_sha256']==
         h['after_dump_state_sha256'],'capture-holder-context')
    need(all(_time(h[k]) for k in ('opened_at','exported_at','alive_after_dump_at')) and
         start<=h['opened_at']<=h['exported_at']<=h['alive_after_dump_at']<=end,
         'capture-holder-time')
    need(metadata['tls']['holder']['observed_at']<=h['opened_at'],'capture-tls-time')
    for category,counts in [('v2',('roles','memberships','extensions','events','tables')),
                            ('v3',V3_CATEGORIES)]:
        record=metadata[category]
        _shape(record,('source_identity_sha256','snapshot_id','holder_state_sha256','reader_sha256',
                       'payload_sha256','captured_at','counts'))
        need(record['source_identity_sha256']==source['identity_sha256'] and
             record['snapshot_id']==h['exported_snapshot_id'] and
             record['holder_state_sha256']==h['before_state_sha256'] and
             record['reader_sha256']==plan['protocol_pins'][category+'_reader_sha256'] and
             _hex(record['payload_sha256']),'capture-collector-binding')
        need(_time(record['captured_at']) and h['exported_at']<=record['captured_at']<=end,
             'capture-collector-time')
        _counts(record['counts'],counts)
    dump=metadata['dump']
    _shape(dump,('source_identity_sha256','imported_snapshot_id','runner_sha256','tls_evidence_sha256',
                'started_at','finished_at','exit_code','sha256','bytes'))
    need(dump['source_identity_sha256']==source['identity_sha256'] and
         dump['imported_snapshot_id']==h['exported_snapshot_id'] and
         dump['runner_sha256']==plan['protocol_pins']['dump_runner_sha256'] and
         dump['tls_evidence_sha256']==metadata['tls']['dump']['evidence_sha256'] and
         type(dump['exit_code']) is int and dump['exit_code']==0 and
         _hex(dump['sha256']) and dump['sha256']!=R2_DUMP_SHA256 and
         type(dump['bytes']) is int and 5<dump['bytes']<=limits['maximum_dump_bytes'],
         'capture-dump-binding')
    need(all(_time(dump[k]) for k in ('started_at','finished_at')) and
         metadata['v2']['captured_at']<=metadata['v3']['captured_at']<=dump['started_at']<
         dump['finished_at']<=h['alive_after_dump_at'] and
         dump['finished_at']-dump['started_at']<=limits['dump_seconds'],'capture-dump-time')
    # v2: a real pg_dump TLS handshake is confirmed by its strict verify-full
    # invocation returning successfully; that observation cannot predate start.
    need(dump['finished_at']<=metadata['tls']['dump']['observed_at']<=h['alive_after_dump_at'],
         'capture-tls-time')
    _pin(metadata['dump_pin'],ROOT+'/full.dump',limits['maximum_dump_bytes'],start,end)
    need(metadata['dump_pin']['sha256']==dump['sha256'] and
         metadata['dump_pin']['size']==dump['bytes'],'capture-dump-pin-binding')
    companion=metadata['companion']
    _shape(companion,('protocol','capture_id','snapshot_id','dump_sha256','dump_bytes',
                      'v2_payload_sha256','v3_payload_sha256','sha256'))
    need(companion['protocol']=='v2-plus-v3-shared-exported-snapshot' and
         companion['capture_id']==metadata['capture_id'] and
         companion['snapshot_id']==h['exported_snapshot_id'] and
         companion['dump_sha256']==dump['sha256'] and type(companion['dump_bytes']) is int and
         companion['dump_bytes']==dump['bytes'] and
         all(companion[v+'_payload_sha256']==metadata[v]['payload_sha256'] for v in ('v2','v3')) and
         _hex(companion['sha256']),'capture-companion-binding')
    _pin(metadata['companion_pin'],ROOT+'/private-manifest.json',
         limits['maximum_companion_bytes'],start,end)
    need(metadata['companion_pin']['sha256']==companion['sha256'] and
         (metadata['dump_pin']['dev'],metadata['dump_pin']['ino'])!=
         (metadata['companion_pin']['dev'],metadata['companion_pin']['ino']),
         'capture-companion-pin-binding')
    closure=metadata['closure']
    _shape(closure,('holder_backend_pid','rollback_observed','connection_closed_observed','closed_at',
                   'evidence_sha256','keepalive_calls','maximum_keepalive_gap_seconds','last_keepalive_at'))
    need(type(closure['holder_backend_pid']) is int and closure['holder_backend_pid']==h['backend_pid'] and
         closure['rollback_observed'] is True and
         closure['connection_closed_observed'] is True and _hex(closure['evidence_sha256']),
         'capture-holder-close')
    need(type(closure['keepalive_calls']) is int and closure['keepalive_calls']>=
         int((dump['finished_at']-dump['started_at'])//limits['keepalive_seconds']) and
         type(closure['maximum_keepalive_gap_seconds']) in (int,float) and
         0<=closure['maximum_keepalive_gap_seconds']<=limits['maximum_keepalive_gap_seconds'] and
         _time(closure['last_keepalive_at']) and dump['started_at']<=closure['last_keepalive_at']<=
         h['alive_after_dump_at'] and _time(closure['closed_at']) and
         h['alive_after_dump_at']<=closure['closed_at']<=end,'capture-holder-keepalive')
    return dict(schema='igreja12.origin-capture-binding-assessment/2',
        status='metadata-structurally-bound-only',plan_digest=digest(plan),
        observation_digest=digest(metadata),dump_sha256=dump['sha256'],dump_bytes=dump['bytes'],
        capture_started_at=start,capture_finished_at=end,holder_closed_at=closure['closed_at'],
        v2_counts=dict(metadata['v2']['counts']),v3_counts=dict(metadata['v3']['counts']),
        retention_deadline=RETENTION_DEADLINE,operational_ready=False,
        actual_origin_authenticated_by_contract=False,capture_executed_by_contract=False,
        a8_window_proven=False,receipt_emitted=False,production_mutation_authorized=False)
