"""No provider, host or Redis is contacted by these contract tests."""
import dataclasses
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from first_transition_adapter import LocalEvidence, Refused, local_endpoint, prepare

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = 'afdfb78d71a53f2861632806e13cdda4662d7d63'
EXECUTOR = '37c7d68d60b6f86cfb1fe75d4c720530537845d6'


def test_exact_plan_selects_the_reviewed_78_plus_51():
    plan = prepare(ROOT, APP, EXECUTOR)
    assert (len(plan.baseline), len(plan.pending), len(plan.migrations)) == (78, 51, 129)
    assert sum(m.concurrent for m in plan.pending) == 8
    assert plan.application_sha == APP and plan.executor_sha == EXECUTOR
    assert plan.report()['production_ready'] is False
    assert len(plan.digest) == 64
    assert all(m.sha256 for m in plan.migrations)
    assert 'postgresql' not in str(plan.report())


@pytest.mark.parametrize('url', [
    'postgresql://postgres@remote/first_transition_test',
    'postgresql://postgres@localhost/first_transition_test',
    'postgresql://postgres@127.0.0.1/prod',
    'postgresql://postgres@127.0.0.1/first_transition_test?host=remote',
    'postgresql://postgres@127.0.0.1/first_transition_test#fragment',
    'service=production',
    'postgresql://postgres:fixture-other@127.0.0.1:5432/first_transition_test',
    'postgresql://fixture-other:synthetic-only@127.0.0.1:5432/first_transition_test',
])
def test_remote_or_ambiguous_endpoint_refused(url):
    with pytest.raises(Refused):
        local_endpoint(url)


def test_local_endpoint_accepts_only_literal_loopback_and_named_database():
    local_endpoint('postgresql://postgres:synthetic-only@127.0.0.1:5432/first_transition_test')


def test_evidence_requires_four_contained_roles_and_no_gate_delta():
    evidence = LocalEvidence.synthetic('a' * 64, 'b' * 64)
    evidence.validate('a' * 64, 'b' * 64)
    for change in [dict(ingress_blocked=False), dict(backup_rehearsal_requested=False),
                   dict(queue_preservation_assumed=False), dict(support_preserved=False),
                   dict(gates_preserved=False), dict(stopped_roles=('backend',)),
                   dict(baseline_digest='c' * 64), dict(plan_digest='c' * 64),
                   dict(kind='production')]:
        with pytest.raises(Refused):
            dataclasses.replace(evidence, **change).validate('a' * 64, 'b' * 64)


class MetadataRedis:
    def __init__(self, *, ttl=-1):
        self.calls, self.ttl = [], ttl

    def __call__(self, command, key):
        self.calls.append((command, key))
        if command == 'TYPE':
            return 'zset' if key.endswith('retry-scheduled') else 'list'
        if command == 'PTTL':
            return self.ttl
        if command in ('LLEN', 'ZCARD'):
            return 2 if key.endswith(':dead') else 0
        raise AssertionError('content reads and key enumeration are prohibited')


def test_queue_observer_reads_only_explicit_metadata_and_never_dead_contents():
    import first_transition_adapter as adapter
    redis = MetadataRedis()
    result = adapter.queue_metadata(redis)
    assert result['counts']['pastorai:webhooks:dead'] == 2
    assert result['content_verified'] is False
    assert len(redis.calls) == 12
    assert {command for command, _ in redis.calls} == {'TYPE', 'PTTL', 'LLEN', 'ZCARD'}
    assert all(key.startswith('pastorai:webhooks') for _, key in redis.calls)


@pytest.mark.parametrize('keys', [('unrelated:site',), ('pastorai:webhooks:processing:*',),
                                 ('pastorai:webhooks:processing:person@example.test',)])
def test_unknown_queue_scope_refused_before_redis_calls(keys):
    import first_transition_adapter as adapter
    redis = MetadataRedis()
    with pytest.raises(Refused, match='queue-scope'):
        adapter.queue_metadata(redis, processing_keys=keys)
    assert redis.calls == []


def test_volatile_critical_queue_is_refused():
    import first_transition_adapter as adapter
    with pytest.raises(Refused, match='queue-not-persistent'):
        adapter.queue_metadata(MetadataRedis(ttl=100))


def test_importing_rehearsal_has_no_effects(monkeypatch):
    import runpy
    import subprocess
    monkeypatch.setattr(subprocess, 'run', lambda *_args, **_kwargs: pytest.fail('import must not launch a process'))
    namespace = runpy.run_path(str(ROOT / 'deploy/rehearse_first_transition_database.py'))
    assert callable(namespace['main'])


def test_full_preflight_summary_is_counts_only():
    import json
    import first_transition_adapter as adapter
    counts = dict(status='ok', read_only=True, files=129, applied=78, pending=51,
                  unknown=0, fk_findings=0, duplicates=0, missing_tables=0,
                  definer_examined=0, definer_unverified=10, definer_findings=0)
    assert adapter.preflight_summary(json.dumps(counts).encode(), 129, 78) == counts


@pytest.mark.parametrize('output', [b'not-json', b'{"raw_person_id":"synthetic-private-id"}',
                                    b'{"status":"refused","code":"internal"}'])
def test_unexpected_preflight_output_is_not_exposed(output):
    import first_transition_adapter as adapter
    with pytest.raises(Refused, match='full-preflight-output') as failure:
        adapter.preflight_summary(output, 129, 78)
    assert 'synthetic-private-id' not in str(failure.value)


def test_reviewed_concurrent_index_names_are_exact():
    plan = prepare(ROOT)
    assert {index for migration in plan.pending for index in migration.indexes} == {
        'ai_usage_logs_igreja_created_at_idx', 'notification_outbox_pending_igreja_created_idx',
        'notification_outbox_retry_igreja_created_idx', 'notification_outbox_lease_igreja_claimed_idx',
        'messages_pending_agent_igreja_created_idx', 'work_queue_pending_igreja_created_idx',
        'private_erasure_requests_overview_idx', 'private_resume_delivered_overview_idx'}
