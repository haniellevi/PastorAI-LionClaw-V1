"""Observed phase timing, with fake clocks and the existing isolated job rig."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import first_transition_native_job as job
from first_transition_adapter import digest
from first_transition_native_events import CODE, PHASES, NativeWindowEvents
from initial_transition_ops import Refused
from test_first_transition_native_job import plan, rig  # noqa: F401
from test_first_transition_orchestrator import no_real_processes_or_network  # noqa: F401


class Clock:
    def __init__(self):self.wall,self.mono=10000.0,100.0
    def advance(self,seconds):self.wall+=seconds;self.mono+=seconds
    def events(self):
        return NativeWindowEvents('a'*64,'b'*64,clock=lambda:self.mono,wall_clock=lambda:self.wall)


METHODS = ('capture_start','source_frontends_closed','capture_finish','recovery_start',
           'recovery_finish','cleanup_finish','result')


def finish(events,clock):
    for name in METHODS:
        clock.advance(1)
        getattr(events,name)()


def test_complete_events_are_bound_observations_with_no_writer_claim():
    clock=Clock();events=clock.events();finish(events,clock)
    value=events.public()
    assert value['request_digest']=='a'*64 and value['context_digest']=='b'*64
    assert [row['phase'] for row in value['events']]==list(PHASES)
    assert [row['sequence'] for row in value['events']]==list(range(8))
    assert [row['elapsed_s'] for row in value['events']]==list(range(8))
    assert events.digest==digest(value)
    assert all(value[key] is False for key in ('source_unchanged_proven','writer_absence_proven',
                                               'source_state_equality_proven','a8_window_proven'))
    value['events'][0]['wall_at']=1;value['events'].clear();value['source_unchanged_proven']=True
    assert events.digest==digest(events.public()) and len(events.public()['events'])==8
    assert events.public()['source_unchanged_proven'] is False


@pytest.mark.parametrize('field',['request_digest','context_digest'])
def test_different_binding_changes_digest(field):
    clock=Clock();first=clock.events();finish(first,clock)
    clock=Clock();args=dict(request_digest='a'*64,context_digest='b'*64);args[field]='c'*64
    second=NativeWindowEvents(**args,clock=lambda:clock.mono,wall_clock=lambda:clock.wall)
    finish(second,clock)
    assert first.digest!=second.digest


@pytest.mark.parametrize('method',METHODS[1:])
def test_skipped_phase_consumes_log(method):
    events=Clock().events()
    with pytest.raises(Refused,match=CODE):getattr(events,method)()
    with pytest.raises(Refused,match=CODE):events.capture_start()


def test_duplicate_phase_and_result_cannot_be_replayed():
    clock=Clock();events=clock.events();events.capture_start()
    with pytest.raises(Refused,match=CODE):events.capture_start()
    clock=Clock();events=clock.events();finish(events,clock)
    with pytest.raises(Refused,match=CODE):events.result()
    with pytest.raises(Refused,match=CODE):events.public()


def test_incomplete_observations_cannot_be_exported():
    events=Clock().events()
    with pytest.raises(Refused,match=CODE):events.public()
    with pytest.raises(Refused,match=CODE):_ = events.digest


def test_export_checks_age_again_without_manufacturing_new_events():
    clock=Clock();events=clock.events();finish(events,clock)
    before=events.public();clock.advance(59)
    assert events.public()==before
    clock.advance(.001)
    with pytest.raises(Refused,match=CODE):events.public()
    with pytest.raises(Refused,match=CODE):_ = events.digest


@pytest.mark.parametrize('field,value',[('wall',True),('wall',0),('wall',float('nan')),
    ('wall',float('inf')),('mono',False),('mono',-1),('mono',float('nan')),('mono',float('inf'))])
@pytest.mark.parametrize('at_start',[True,False])
def test_invalid_clock_values_refuse(field,value,at_start):
    clock=Clock();events=None if at_start else clock.events();setattr(clock,field,value)
    with pytest.raises(Refused,match=CODE):
        if at_start:clock.events()
        else:events.capture_start()


@pytest.mark.parametrize('wall,mono',[(9999,100),(10000,99),(10003,100),(10000,103)])
def test_backward_or_divergent_clocks_refuse(wall,mono):
    clock=Clock();events=clock.events();clock.wall,clock.mono=wall,mono
    with pytest.raises(Refused,match=CODE):events.capture_start()


def test_accumulated_drift_is_not_hidden_by_small_per_phase_changes():
    clock=Clock();events=clock.events()
    clock.wall+=1;events.capture_start()
    clock.wall+=1;events.source_frontends_closed()
    clock.wall+=1
    with pytest.raises(Refused,match=CODE):events.capture_finish()


@pytest.mark.parametrize('phase,delay',[(0,61),(1,241),(2,241),(3,61),(4,1201),(5,61),(6,61)])
def test_budgets_and_phase_gaps_refuse(phase,delay):
    clock=Clock();events=clock.events()
    for index,method in enumerate(METHODS):
        if index==phase:
            clock.advance(delay)
            with pytest.raises(Refused,match=CODE):getattr(events,method)()
            break
        getattr(events,method)()


def test_capture_budget_includes_delay_before_capture_start():
    clock=Clock();events=clock.events();clock.advance(50);events.capture_start()
    clock.advance(190);events.source_frontends_closed();clock.advance(1)
    with pytest.raises(Refused,match=CODE):events.capture_finish()


def test_exact_budget_boundaries_and_equal_clock_ticks_are_allowed():
    clock=Clock();events=clock.events();clock.advance(60);events.capture_start()
    clock.advance(180);events.source_frontends_closed();events.capture_finish()
    clock.advance(60);events.recovery_start();clock.advance(780);events.recovery_finish()
    clock.advance(60);events.cleanup_finish();clock.advance(60);events.result()
    assert events.public()['events'][-1]['elapsed_s']==1200


@pytest.mark.parametrize('failure',[RuntimeError('SYNTHETIC-PRIVATE'),KeyboardInterrupt('SYNTHETIC-PRIVATE')])
def test_clock_failure_is_sanitized_and_consumes_log(failure):
    clock=Clock();events=clock.events()
    def broken():raise failure
    events._wall=broken
    with pytest.raises(type(failure) if isinstance(failure,KeyboardInterrupt) else Refused) as found:
        events.capture_start()
    assert 'SYNTHETIC-PRIVATE' not in str(found.value)
    with pytest.raises(Refused,match=CODE):events.capture_start()


@pytest.mark.parametrize('value',[{},True,1,'z'*64,'a'*63])
def test_caller_payloads_cannot_be_imported_as_events(value):
    with pytest.raises(Refused,match=CODE):NativeWindowEvents(value,'b'*64)


def test_job_publishes_actual_order_and_binds_complete_events(rig):
    result=rig.worker.execute(rig.request)
    value=result['events']
    assert [row['phase'] for row in value['events']]==list(PHASES)
    assert value['request_digest']==digest(rig.request)
    assert value['context_digest']==digest(rig.worker.context)
    assert result['binding']['events_sha256']==digest(value)
    assert result['binding_digest']==digest(result['binding'])
    assert result['source_unchanged_proven'] is False and result['binding']['source_unchanged_proven'] is False
    assert 'SYNTHETIC-PRIVATE' not in json.dumps(value)
    assert all(connection.closed for connection in rig.source.connections)
    assert rig.source.producer.wait(timeout=1)==0
    assert not rig.docker.have_container and not rig.docker.have_network


def test_job_snapshot_success_with_live_mutation_does_not_claim_unchanged(rig):
    original=rig.worker.dump_popen
    def mutate(argv,**kwargs):
        rig.source.inventory['v2']['row_counts']['public.synthetic_table']=1000
        return original(argv,**kwargs)
    rig.worker.dump_popen=mutate
    result=rig.worker.execute(rig.request)
    assert result['source_unchanged_proven'] is False
    assert result['events']['writer_absence_proven'] is False
    assert result['a8_window_proven'] is False


def test_job_records_closure_replay_and_cleanup_after_the_actual_effects(rig,monkeypatch):
    checked=[]
    class Observed(NativeWindowEvents):
        def source_frontends_closed(self):
            assert all(connection.closed for connection in rig.source.connections)
            assert rig.source.producer.wait(timeout=1)==0
            assert not rig.docker.have_container
            checked.append('closed');super().source_frontends_closed()
        def recovery_finish(self):
            assert len(rig.docker.applied)==51 and rig.docker.have_container
            checked.append('replayed');super().recovery_finish()
        def cleanup_finish(self):
            assert not rig.docker.have_container and not rig.docker.have_network
            checked.append('cleaned');super().cleanup_finish()
    monkeypatch.setattr(job,'NativeWindowEvents',Observed)
    rig.worker.execute(rig.request)
    assert checked==['closed','replayed','cleaned']


@pytest.mark.parametrize('phase',METHODS)
def test_event_failure_never_skips_owned_resource_cleanup(rig,monkeypatch,phase):
    class Failed(NativeWindowEvents):pass
    def refuse(_self):raise Refused(CODE)
    monkeypatch.setattr(Failed,phase,refuse)
    monkeypatch.setattr(job,'NativeWindowEvents',Failed)
    with pytest.raises(Refused,match='native-job-failed'):rig.worker.execute(rig.request)
    assert not rig.docker.have_container and not rig.docker.have_network
    assert all(connection.closed for connection in rig.source.connections)
    if phase=='capture_start':assert rig.requests==[] and rig.docker.calls==[]


def test_event_clock_failure_after_replay_still_cleans_owned_resources(rig):
    wall=[rig.worker.wall_clock()];rig.worker.wall_clock=lambda:wall[0]
    original=rig.docker.run
    def changed_clock(argv,**kwargs):
        result=original(argv,**kwargs)
        if len(rig.docker.applied)==51:wall[0]-=1000
        return result
    rig.worker.run=changed_clock
    with pytest.raises(Refused,match='native-job-failed'):rig.worker.execute(rig.request)
    assert len(rig.docker.applied)==51
    assert not rig.docker.have_container and not rig.docker.have_network
