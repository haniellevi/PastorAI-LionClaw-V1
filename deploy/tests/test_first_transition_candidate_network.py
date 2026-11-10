"""A9 network identity with Docker's empty NetworkID for never-started containers."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from first_transition_candidate import CANDIDATE_TEMPLATE, CandidatePort, CandidateRunner, check_identity
import first_transition_candidate as candidate_module
from first_transition_host_driver import NETWORK_TEMPLATE
from initial_transition_ops import Refused
from test_first_transition_orchestrator import (CANDIDATE_IDS, pinned, world,
                                               no_real_processes_or_network)  # noqa: F401


def network_argv(spec):
    return ('docker', 'network', 'inspect', '--format', NETWORK_TEMPLATE, spec.network_id, spec.network_name)


def create(world):
    world.cdocker.created_network_id = ''
    world.cdocker(world.spec.compose_argv(), timeout=5, max_output=65536)
    return CandidatePort(world.spec, runner=world.cdocker)


def test_created_network_intent_survives_a9_replay_and_writer(world):
    world.cdocker.created_network_id = ''
    transition = world.transition()
    result = transition.run()
    assert result['status'] == 'a9-backend-smoked'
    assert transition.candidate_writer(timeout=5) == CANDIDATE_IDS['backend']
    world.journal.close()
    assert world.transition().run() == result
    assert world.cdocker.starts == 1
    world.consumers_held()
    world.assert_legacy_contained()
    assert world.journal.last('transition-a9-complete')


@pytest.mark.parametrize('effective', [False, True])
def test_inspect_preserves_raw_id_with_fresh_name_id_binding(world, effective):
    port = create(world)
    world.cdocker.created_network_id = world.spec.network_id if effective else ''
    state = port.inspect((CANDIDATE_IDS['backend'],))[CANDIDATE_IDS['backend']]
    assert state['networks'] == [world.cdocker.created_network_id]
    assert state['network_names'] == [world.spec.network_name]
    assert state['network_binding'] == [world.spec.network_id, world.spec.network_name]
    check_identity(world.spec, 'backend', state)
    assert world.cdocker.calls.count(network_argv(world.spec)) == 2
    assert world.cdocker.starts == 0


def project(port, change):
    runner = port.runner

    def run(argv, **kwargs):
        rc, out = runner(argv, **kwargs)
        if argv[:6] == ('docker', 'inspect', '--type', 'container', '--format', CANDIDATE_TEMPLATE):
            rows = [json.loads(line) for line in out.splitlines()]
            for row in rows:
                change(row)
            return rc, b''.join(json.dumps(row).encode() + b'\n' for row in rows)
        return rc, out
    port.runner = run


@pytest.mark.parametrize('change', [
    lambda r: r.__setitem__(18, [None]),
    lambda r: r[18].insert(0, ['other', [], 'a' * 64]),
    lambda r: r[18][0].__setitem__(0, 'other'),
    lambda r: r[18][0].__setitem__(2, 'a' * 64),
    lambda r: r.__setitem__(15, 'host'),
    lambda r: r.__setitem__(15, 'container:' + 'b' * 64),
])
def test_wrong_or_extra_network_never_authorizes_start(world, change):
    port = create(world)
    project(port, change)
    with pytest.raises(Refused, match='candidate-network-mismatch'):
        port.start_backend(CANDIDATE_IDS['backend'])
    assert world.cdocker.starts == 0


@pytest.mark.parametrize('index,value', [(6, 'exited'), (11, '2026-11-03T01:00:00Z'), (13, 1), (14, 'always')])
def test_empty_network_id_requires_complete_never_started_state(world, index, value):
    port = create(world)
    project(port, lambda row: row.__setitem__(index, value))
    with pytest.raises(Refused, match='candidate-network-mismatch'):
        state = port.inspect((CANDIDATE_IDS['backend'],))[CANDIDATE_IDS['backend']]
        check_identity(world.spec, 'backend', state)
    assert world.cdocker.starts == 0


def test_running_backend_empty_id_refuses_even_with_verified_name(world):
    port = create(world)
    world.cdocker._run(CANDIDATE_IDS['backend'])
    project(port, lambda row: row[18][0].__setitem__(2, ''))
    with pytest.raises(Refused, match='candidate-network-mismatch'):
        port._backend(CANDIDATE_IDS['backend'])


@pytest.mark.parametrize('change', [
    lambda rows: rows[0].__setitem__(1, 'renamed'),
    lambda rows: rows[1].__setitem__(0, 'f' * 64),
    lambda rows: rows.pop(),
    lambda rows: rows.append(['f' * 64, 'extra']),
])
def test_network_lookup_must_bind_both_full_id_and_name(world, change):
    port = create(world)
    # Independent row objects: mutations model actual divergent Docker responses.
    world.cdocker.network_rows = [[world.spec.network_id, world.spec.network_name] for _ in range(2)]
    change(world.cdocker.network_rows)
    with pytest.raises(Refused, match='candidate-network-binding'):
        port.start_backend(CANDIDATE_IDS['backend'])
    assert world.cdocker.starts == 0


def test_network_rebound_during_inspection_refuses(world):
    port = create(world)
    runner = port.runner

    def mutate(argv, **kwargs):
        answer = runner(argv, **kwargs)
        if argv[:2] == ('docker', 'inspect'):
            world.cdocker.network_rows = [['f' * 64, world.spec.network_name]] * 2
        return answer
    port.runner = mutate
    with pytest.raises(Refused, match='candidate-network-binding'):
        port.start_backend(CANDIDATE_IDS['backend'])
    assert world.cdocker.starts == 0


def test_binding_is_rechecked_on_next_inspection(world):
    port = create(world)
    state = port.inspect((CANDIDATE_IDS['backend'],))[CANDIDATE_IDS['backend']]
    check_identity(world.spec, 'backend', state)
    world.cdocker.network_rows = [['f' * 64, world.spec.network_name]] * 2
    with pytest.raises(Refused, match='candidate-network-binding'):
        port.start_backend(CANDIDATE_IDS['backend'])
    assert world.cdocker.starts == 0


def test_unbound_raw_projection_cannot_authorize_empty_id(world):
    create(world)
    raw = CandidatePort._row(world.cdocker._render(CANDIDATE_IDS['backend']))
    with pytest.raises(Refused, match='candidate-network-mismatch'):
        check_identity(world.spec, 'backend', raw)


def test_candidate_runner_only_allows_exact_network_binding_query(world):
    runner = CandidateRunner(world.spec, docker_binary='/usr/bin/docker', endpoint='unix:///run/x/docker.sock',
                             config_dir='/srv/docker-config')
    argv = network_argv(world.spec)
    assert runner._allowed(argv)
    assert not runner._allowed(argv[:-1])
    assert not runner._allowed((*argv, 'extra'))
    assert not runner._allowed((*argv[:5], 'f' * 64, argv[-1]))


@pytest.mark.parametrize('response,code', [
    ((1, b'SENTINEL-unrelated-output'), 'candidate-network-binding'),
    ((0, b'not-json-SENTINEL'), 'candidate-network-binding'),
    ((0, b'x' * 1025), 'candidate-runner-failed'),
])
def test_network_lookup_failures_are_bounded_and_sanitized(world, response, code):
    port = create(world)
    runner = port.runner
    port.runner = lambda argv, **kwargs: response if argv == network_argv(world.spec) else runner(argv, **kwargs)
    with pytest.raises(Refused, match='^' + code + '$') as raised:
        port.start_backend(CANDIDATE_IDS['backend'])
    assert 'SENTINEL' not in repr(raised.value)
    assert world.cdocker.starts == 0


def test_network_lookup_cannot_exceed_shared_inspection_deadline(world, monkeypatch):
    port = create(world)
    runner, clock = port.runner, [1.0]
    monkeypatch.setattr(candidate_module.time, 'monotonic', lambda: clock[0])

    def slow(argv, **kwargs):
        answer = runner(argv, **kwargs)
        assert kwargs['timeout'] <= 0.25
        if argv == network_argv(world.spec):
            clock[0] += 0.26
        return answer
    port.runner = slow
    with pytest.raises(Refused, match='^candidate-timeout$'):
        port.inspect((CANDIDATE_IDS['backend'],), timeout=0.25)
    assert not any(a[:2] == ('docker', 'inspect') for a in world.cdocker.calls)
    assert world.cdocker.starts == 0
