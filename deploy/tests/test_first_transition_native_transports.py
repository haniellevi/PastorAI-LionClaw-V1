"""Native consumers on pinned fake handles; no real process or network."""
from copy import deepcopy
from dataclasses import asdict,replace
import ipaddress
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import quote,urlencode,urlsplit,urlunsplit

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import first_transition_native_transports as transports
from first_transition_adapter import digest
from initial_transition_ops import Refused
from test_first_transition_native_job import CloneConnection,CloneCursor,SECRET,plan,rig  # noqa: F401
from test_first_transition_orchestrator import no_real_processes_or_network  # noqa: F401


@pytest.fixture
def bundle(rig):
    pins = transports.NativeTransportPins(digest(rig.worker.context),digest(asdict(rig.worker.connector.policy)),
        rig.worker.plan.digest,rig.source.expected.identity)
    return transports.NativeSourceTransports(plan=rig.worker.plan,expected=rig.source.expected,context=rig.worker.context,
        policy=rig.worker.connector.policy,pins=pins,secret=rig.worker.connector.secret,driver=rig.source,owner=os.geteuid())


def test_writer_endpoint_is_same_actual_route_without_dns(bundle,monkeypatch):
    import socket
    monkeypatch.setattr(socket,'getaddrinfo',lambda *_a,**_k:pytest.fail('DNS must not select writer endpoints'))
    assert bundle.endpoint(SECRET) == (frozenset({ipaddress.ip_address('192.0.2.10')}),5432)
    assert bundle.connector.driver.connections == []


def test_single_provider_is_frozen_for_endpoint_reader_and_candidate(bundle):
    calls = []
    def provider():
        calls.append(True)
        return SECRET if len(calls)==1 else SECRET.replace('SYNTHETIC-PRIVATE','ROTATED')
    bundle._provider = provider
    bundle.endpoint(SECRET)
    conn = bundle.read_connect(timeout=10)
    conn.close()
    candidate = bundle.candidate_uri()
    assert bundle.candidate_environment([('DATABASE_URL',candidate)],SECRET) == 5
    assert len(calls) == 1 and 'ROTATED' not in candidate


def test_reader_clamps_ten_second_budget_to_native_eight(bundle):
    conn = bundle.read_connect(timeout=10)
    assert bundle.connector.driver.kwargs[-1]['connect_timeout'] == 8
    conn.close()


def test_late_native_connect_is_closed_instead_of_returning_success(bundle):
    values = iter((0,11))
    bundle.clock = lambda:next(values)
    with pytest.raises(Refused,match='^native-transports-budget$'):
        bundle.read_connect(timeout=10)
    assert bundle.connector.driver.connections[-1].closed


@pytest.mark.parametrize('budget',[True,0,-1,float('nan'),float('inf'),1201])
def test_invalid_reader_budget_refuses_before_login(bundle,budget):
    with pytest.raises(Refused,match='^native-transports-budget$'):
        bundle.read_connect(timeout=budget)
    assert bundle.connector.driver.connections == []


def test_pin_mutation_refuses_before_provider(bundle):
    bundle.pins = replace(bundle.pins,source_policy_sha256='f'*64)
    bundle._provider = lambda:pytest.fail('provider opened after mismatched pins')
    for call in (lambda:bundle.endpoint(SECRET),bundle.candidate_uri,lambda:bundle.read_connect(timeout=8)):
        with pytest.raises(Refused,match='^native-transports-binding$'):call()


@pytest.mark.parametrize('change',[dict(hostaddr='192.0.2.11'),dict(port=6543),dict(ca_file='/other/ca.crt')])
def test_independent_policy_alias_cannot_retarget_writers_or_candidate(bundle,change):
    bundle.policy = replace(bundle.policy,**change)
    bundle._provider = lambda:pytest.fail('provider opened after policy alias changed')
    for call in (lambda:bundle.endpoint(SECRET),bundle.candidate_uri,lambda:bundle.read_connect(timeout=8)):
        with pytest.raises(Refused,match='^native-transports-binding$'):call()


def test_candidate_mount_intent_never_claims_effective_ca_after_host_replace(bundle,tmp_path):
    ca=Path(bundle.policy.ca_file)
    old=tmp_path/'old-mounted-ca.crt';ca.rename(old)
    ca.write_bytes(old.read_bytes());ca.chmod(0o600)
    proof=bundle.candidate_mounts([['bind',str(ca),transports.CANDIDATE_CA,False],None])
    assert proof['mount_intent_verified'] is True and proof['effective_ca_verified'] is False
    old.write_bytes(b'SYNTHETIC-STILL-MOUNTED-BUT-WRONG-CA')
    assert bundle.candidate_mounts([['bind',str(ca),transports.CANDIDATE_CA,False],None])['effective_ca_verified'] is False


def test_candidate_port_refuses_unproven_effective_ca_before_backend_start(bundle):
    from first_transition_adapter import ROLES
    from first_transition_candidate import CandidatePort,CandidateSpec,NATIVE_DATABASE_TEMPLATE
    from first_transition_host_driver import INFO_ARGV
    spec=CandidateSpec(bundle.plan.application_sha,'sha256:'+'a'*64,'native-test',
        tuple((r,'native-'+r) for r in ROLES),'1'*64,'native-net','/synthetic/releases','/synthetic/hold',
        '/synthetic/env','aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',smoke_seconds=30,native_ca_override='/synthetic/native-ca.json')
    calls=[];cid='2'*64
    def runner(argv,**_kwargs):
        calls.append(argv)
        if argv==INFO_ARGV:return 0,(json.dumps(spec.daemon_id)+'\n').encode()
        assert argv==('docker','inspect','--type','container','--format',NATIVE_DATABASE_TEMPLATE,cid)
        row=[cid,['DATABASE_URL='+bundle.candidate_uri(),None],
            [['bind',bundle.policy.ca_file,transports.CANDIDATE_CA,False],None]]
        return 0,json.dumps(row).encode()
    candidate=CandidatePort(spec,runner=runner,database_secret=lambda:SECRET,source_transports=bundle)
    with pytest.raises(Refused,match='^native-candidate-effective-ca-unproven$'):
        candidate.check_database(cid)
    assert len(calls)==2 and 'start' not in str(calls)
    assert ('--file',spec.native_ca_override) == spec.compose_argv()[spec.compose_argv().index('up')-2:spec.compose_argv().index('up')]


def test_ca_override_contains_only_public_mount_data_and_no_secret(bundle):
    content=bundle.candidate_override()
    assert b'SYNTHETIC-PRIVATE' not in content
    model=json.loads(content)
    for service in model['services'].values():
        proof=bundle.candidate_compose(service)
        assert proof['mount_intent_verified'] is True and proof['effective_ca_verified'] is False


@pytest.mark.parametrize('destination',['/run','/run/igreja12','/'])
def test_parent_mount_cannot_shadow_candidate_ca(bundle,destination):
    with pytest.raises(Refused,match='^native-candidate-mounts$'):
        bundle.candidate_mounts([['bind',bundle.policy.ca_file,transports.CANDIDATE_CA,False],
            ['bind','/synthetic/shadow',destination,False],None])


def test_provider_failure_is_consumed_and_never_leaks_private_text(bundle):
    calls = []
    def provider():
        calls.append(True)
        raise RuntimeError('SYNTHETIC-PRIVATE-PASSWORD')
    bundle._provider = provider
    for _ in range(2):
        with pytest.raises(Refused) as error:bundle.candidate_uri()
        assert 'PRIVATE' not in str(error.value)
    assert len(calls)==1


def test_candidate_uri_native_parser_sees_exact_required_security_parameters(bundle):
    from psycopg2.extensions import parse_dsn
    uri = bundle.candidate_uri()
    parsed = parse_dsn(uri)
    assert parsed['password'] == 'SYNTHETIC-PRIVATE'
    assert all(parsed[k] == v for k,v in bundle.candidate_parameters().items())
    assert bundle.candidate_environment([('DATABASE_URL',uri),('PRIVATE_SEND_DATABASE_URL','')],SECRET) == 5


@pytest.mark.parametrize('fault',['sslmode','hostaddr','ca','options','cert','password','duplicate','ambient',
    'dedicated','case','alternate-source','plus-options'])
def test_candidate_configuration_refuses_any_unbound_route_or_consumer(bundle,fault):
    from urllib.parse import parse_qsl
    uri = urlsplit(bundle.candidate_uri());query = dict(parse_qsl(uri.query));source=SECRET;extra=[]
    if fault == 'sslmode':query['sslmode']='require'
    elif fault == 'hostaddr':query['hostaddr']='192.0.2.11'
    elif fault == 'ca':query['sslrootcert']='/other/ca.crt'
    elif fault == 'options':query['options']='-c session_preload_libraries=evil'
    elif fault == 'cert':query['sslcertmode']='allow'
    elif fault == 'password':uri=uri._replace(netloc=uri.netloc.replace('SYNTHETIC-PRIVATE','OTHER'))
    elif fault == 'ambient':extra=[('PGSSLMODE','require')]
    elif fault == 'dedicated':extra=[('PRIVATE_SEND_DATABASE_URL',bundle.candidate_uri())]
    elif fault == 'case':extra=[('database_url',bundle.candidate_uri())]
    elif fault == 'alternate-source':source=SECRET.replace('SYNTHETIC-PRIVATE','OTHER')
    encoded = urlencode(query,quote_via=quote)
    if fault == 'duplicate':encoded += '&sslmode=verify-full'
    if fault == 'plus-options':encoded = urlencode(query)  # libpq treats '+' literally
    candidate = urlunsplit((uri.scheme,uri.netloc,uri.path,encoded,''))
    with pytest.raises(Refused):bundle.candidate_environment([('DATABASE_URL',candidate),*extra],source)


class Cursor(CloneCursor):
    description = None
    def execute(self,query,params=None):
        conn = self.c
        if query == transports.authenticated.QUERY:
            assert conn.info.transaction_status==2 and conn.search_path=='pg_catalog,public'
            row = dict(database_ok=True,current_role_ok=True,session_role_ok=True,managed_profile_conformant=True,
                authentication_state_unmasked=True,target_count=1,effective_setting_count=3,masked_or_unknown_sources=0,
                authenticated_backend_count=1,unsafe_persisted_entries=0,duplicate_persisted_groups=0,
                relevant_persisted_entries=0,source_identity_sha256=conn.docker.source.expected.identity,
                observed_at=time.time(),server_version_num=170006,startup_profile='supabase-17.6.1.127')
            if conn.docker.fault == 'unsafe-role':row['current_role_ok']=False
            self.description=[(key,) for key in row];self.rows=[tuple(row.values())];return
        if query in (transports.db.Q_WRITERS,transports.db.Q_BUILDS):
            self.rows=[(1 if conn.docker.fault=='writer' else 0,)];return
        if query in (transports.SOURCE_WRITE_OPTIONS,transports.SOURCE_READ_OPTIONS):
            assert conn.info.transaction_status==0 and conn.autocommit is True and conn.probed
            conn.readonly = query == transports.SOURCE_READ_OPTIONS
            return
        if query in conn.docker.allowed_sql:
            assert conn.readonly is False and conn.probed
        return super().execute(query,params)


@pytest.fixture
def migrating(bundle,rig,monkeypatch,tmp_path):
    docker = rig.docker
    docker.system = '7300000000000000001'
    docker.inventory = deepcopy(rig.source.inventory)
    docker.catalog_rows = deepcopy(rig.source.catalog)
    docker.ledger = list(rig.worker.plan.baseline)
    connections=[]
    def driver(value,**kwargs):
        assert value == SECRET
        c = CloneConnection(docker,'postgres')
        c.info.ssl_in_use=True;c.info.ssl_attribute=lambda _:'TLSv1.3';c.info.dsn_parameters=dict(kwargs)
        c.readonly=True
        c.cursor=lambda:Cursor(c)
        connections.append(c)
        return c
    bundle.connector.driver=driver
    work=tmp_path/'source-executor';work.mkdir(mode=0o700)
    executor=bundle.migration_executor(python=sys.executable,workdir=str(work))
    return executor,docker,connections


def test_all_51_source_migrations_use_fresh_same_probed_handles_and_restore_ro(migrating):
    executor,docker,connections=migrating
    for index,migration in enumerate(executor.plan.pending,1):assert executor.apply(index,migration)==0
    assert len(connections)==51 and len({id(c) for c in connections})==51
    assert all(c.closed and c.readonly and c.search_path=='pg_catalog,public' for c in connections)
    assert docker.applied==[m.name for m in executor.plan.pending]
    assert len(executor.receipts)==51 and executor.next_index==52
    assert 'SYNTHETIC-PRIVATE' not in json.dumps(executor.receipts)


def test_equal_observations_after_live_change_and_reversal_do_not_prove_source_unchanged(rig):
    inventory=deepcopy(rig.source.inventory)
    original=rig.worker.dump_popen;mutations=[]
    def producer(*args,**kwargs):
        rig.source.inventory['v2']['row_counts']['public.synthetic_table']=1000;mutations.append('write')
        rig.source.inventory=deepcopy(inventory);mutations.append('revert')
        return original(*args,**kwargs)
    rig.worker.dump_popen=producer
    result=rig.worker.execute(rig.request)
    assert rig.source.inventory==inventory and mutations==['write','revert']
    assert result['comparison']['equal'] is True
    assert result['source_unchanged_proven'] is False and result['a8_window_proven'] is False


@pytest.mark.parametrize('index',[0,2,True])
def test_first_bad_order_consumes_executor_before_any_login(migrating,index):
    executor,docker,connections=migrating
    with pytest.raises(Refused,match='^native-migration-order$'):
        executor.apply(index,executor.plan.pending[0])
    with pytest.raises(Refused,match='^native-migration-order$'):
        executor.apply(1,executor.plan.pending[0])
    assert executor.stopped and connections==[] and docker.applied==[]


@pytest.mark.parametrize('fault',['unsafe-role','writer','identity','ledger','catalog','migration'])
def test_first_source_failure_stops_executor_without_retry(migrating,fault):
    executor,docker,connections=migrating
    docker.fault=fault
    if fault=='identity':docker.system='7400000000000000001'
    if fault=='ledger':docker.ledger.append('unexpected.sql')
    if fault=='catalog':docker.catalog_rows=[('namespace','public','f'*32)]
    for index,migration in enumerate(executor.plan.pending,1):
        try:executor.apply(index,migration)
        except Refused:break
    else:pytest.fail('fault did not stop source executor')
    assert executor.stopped and all(c.closed for c in connections)
    if fault!='migration':assert docker.applied==[]
    with pytest.raises(Refused,match='^native-migration-order$'):
        executor.apply(index,migration)
