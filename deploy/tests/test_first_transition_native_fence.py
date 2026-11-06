"""Fence inventory/requirements are diagnostics, never write authority."""
from dataclasses import asdict
import hashlib
import importlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from initial_transition_ops import Refused

ROUTES=('api-compose','queue-worker-compose','cron-worker-compose','broadcast-worker-compose',
    'sqlalchemy-direct','ingress-nginx-public','ingress-evolution-bridge','sql-external-clients',
    'sql-open-transactions','data-api','storage-https-service-role','storage-s3','storage-signed-uploads',
    'storage-resumable-uploads','storage-inflight-uploads')
BUCKETS=('whatsapp-media','church-logos')


def feature():
    try:return importlib.import_module('first_transition_native_fence')
    except ModuleNotFoundError:pytest.fail('native fence contract is not implemented')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def inventory(*,routes=ROUTES,buckets=BUCKETS):
    return feature().NativeFenceInventory('a'*64,'b'*64,routes,buckets)


def contract(value=None):
    value=inventory() if value is None else value
    return feature().NativeFenceContract('c'*64,'d'*64,value,digest(asdict(value)))


def test_known_inventory_remains_non_exhaustive_and_cannot_admit_any_writer():
    # Break caught: a complete-looking inventory is promoted to an authority.
    gate=contract();view=gate.requirements()
    assert view['schema']=='igreja12.native-fence-requirements/1'
    assert view['bindings']['request_digest']=='c'*64 and view['bindings']['context_digest']=='d'*64
    assert view['bindings']['source_identity']=='a'*64 and view['bindings']['host_scope_digest']=='b'*64
    assert {d['domain'] for d in view['domains']}=={'application','sql','storage','handoff'}
    covered=[route for domain in view['domains'] for route in domain['routes']]
    assert set(covered)==set(ROUTES) and len(covered)==len(ROUTES)
    assert all(domain['coverage_proven'] is False for domain in view['domains'])
    assert all(view[k] is False for k in ('mechanism_available','inventory_exhaustive_proven','authority_verified',
        'source_unchanged_proven','storage_immutability_proven','a8_window_proven','ddl_authorized','operational_ready'))
    assert view['interval']['continuous_required'] is True
    assert view['interval']['starts_before']=='fresh-capture'
    assert view['interval']['ends_after']=='verified-handoff-to-authorized-ddl-writer'
    with pytest.raises(Refused,match='^native-fence-authoritative-mechanism-unavailable$'):gate.admit()


@pytest.mark.parametrize('route',ROUTES)
def test_each_known_writer_path_is_required_even_if_other_domains_are_present(route):
    with pytest.raises(Refused,match='^native-fence-contract-refused$'):
        inventory(routes=tuple(r for r in ROUTES if r!=route))


@pytest.mark.parametrize('bucket',BUCKETS)
def test_both_known_buckets_are_required(bucket):
    with pytest.raises(Refused,match='^native-fence-contract-refused$'):
        inventory(buckets=tuple(b for b in BUCKETS if b!=bucket))


def test_additional_routes_and_buckets_remain_explicitly_unresolved():
    value=inventory(routes=ROUTES+('another-writer',),buckets=BUCKETS+('another-bucket',))
    view=contract(value).requirements()
    assert value.routes[-1]=='another-writer' and value.storage_buckets[-1]=='another-bucket'
    assert view['unresolved']=={'route_sha256':[digest('another-writer')],
        'bucket_sha256':[digest('another-bucket')],'route_count':1,'bucket_count':1}
    assert view['bindings']['inventory_digest']==digest(asdict(value))
    assert view['inventory_exhaustive_proven'] is False
    assert 'another-writer' not in json.dumps(view) and 'another-bucket' not in json.dumps(view)
    with pytest.raises(Refused):contract(value).admit()


@pytest.mark.parametrize(('field','bad'),[
    ('source_identity',True),('source_identity','A'*64),('source_identity','a'*63),
    ('host_scope_digest',1),('schema',True),('schema','igreja12.native-fence-inventory/2'),
    ('routes',list(ROUTES)),('routes',ROUTES+(ROUTES[0],)),('routes',ROUTES+(True,)),
    ('routes',ROUTES+('../private',)),('routes',ROUTES+('url://host',)),
    ('routes',ROUTES+('a'*129,)),('storage_buckets',list(BUCKETS)),
    ('storage_buckets',BUCKETS+(BUCKETS[0],)),('storage_buckets',BUCKETS+(1,)),
])
def test_inventory_rejects_type_confusion_duplicates_and_private_paths(field,bad):
    values={'source_identity':'a'*64,'host_scope_digest':'b'*64,
        'routes':ROUTES,'storage_buckets':BUCKETS}
    values[field]=bad
    with pytest.raises(Refused,match='^native-fence-contract-refused$'):
        feature().NativeFenceInventory(**values)


@pytest.mark.parametrize('bad',[None,True,1,'x','A'*64,'a'*63])
def test_independent_digest_pins_are_strict(bad):
    value=inventory()
    with pytest.raises(Refused,match='^native-fence-contract-refused$'):
        feature().NativeFenceContract('c'*64,'d'*64,value,bad)


def test_digest_of_different_inventory_cannot_pin_this_source():
    value=inventory()
    other=feature().NativeFenceInventory('e'*64,'b'*64,ROUTES,BUCKETS)
    with pytest.raises(Refused,match='^native-fence-contract-refused$'):
        feature().NativeFenceContract('c'*64,'d'*64,value,other.digest)


def test_frozen_input_drift_is_detected_and_public_view_cannot_mutate_contract():
    value=inventory();gate=contract(value);first=gate.requirements()
    first['authority_verified']=True;first['domains'][0]['coverage_proven']=True
    assert gate.requirements()['authority_verified'] is False
    assert gate.requirements()['domains'][0]['coverage_proven'] is False
    object.__setattr__(value,'source_identity','e'*64)
    with pytest.raises(Refused,match='^native-fence-contract-refused$'):gate.requirements()
    with pytest.raises(Refused,match='^native-fence-authoritative-mechanism-unavailable$'):gate.admit()


@pytest.mark.parametrize('evidence',[
    None,True,1,{},
    {'lease':'valid','hashes_equal':True,'zero_observation':True},
    {'repeatable_read':True,'rls':True,'nginx_blocked':True,'pg_network_restricted':True},
    {'schema':'igreja12.fence-authority/1','source_unchanged_proven':True,
     'storage_immutability_proven':True,'a8_window_proven':True,'ddl_authorized':True},
])
def test_json_observations_and_claims_never_grant_authority(evidence):
    with pytest.raises(Refused,match='^native-fence-authoritative-mechanism-unavailable$'):
        contract().validate_authority(evidence)


def test_authority_validation_does_not_invoke_or_inspect_the_supplied_object():
    class Hostile:
        def __bool__(self):raise AssertionError('truthiness evaluated')
        def __iter__(self):raise AssertionError('iteration attempted')
        def __repr__(self):raise AssertionError('private details rendered')
        def __call__(self):raise AssertionError('effect invoked')
    with pytest.raises(Refused,match='^native-fence-authoritative-mechanism-unavailable$'):
        contract().validate_authority(Hostile())


def test_requirements_distinguish_controls_and_require_continuous_owned_handoff():
    view=contract().requirements();domains={item['domain']:item for item in view['domains']}
    assert {'ingress-nginx-public','ingress-evolution-bridge'}<=set(domains['application']['routes'])
    assert 'resolve-existing-transactions-and-inflight-statements-before-capture' in domains['sql']['obligations']
    assert 'independently-bind-storage-project-account-and-source-database' in domains['storage']['obligations']
    assert 'resolve-signed-resumable-and-inflight-uploads-before-capture' in domains['storage']['obligations']
    assert 'sql-rls-nginx-or-postgres-network-restrictions-do-not-fence-storage' in domains['storage']['obligations']
    assert 'verify-no-gap-handoff-to-exact-authorized-ddl-writer' in domains['handoff']['obligations']
    assert 'expiry-owner-loss-cancellation-or-uncertainty-must-fail-closed' in domains['handoff']['obligations']
