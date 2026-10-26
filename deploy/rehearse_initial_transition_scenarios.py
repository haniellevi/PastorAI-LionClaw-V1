"""Scenarios of ``rehearse_initial_transition.py`` (one owned stack each; the controller is real).

The rehearsal only observes, holds barriers, makes the explicit "human"
actions a runbook would require (drop an invalid index, remove a planted
layout, give a decision) and SIGKILLs the CONTROLLER at boundaries; it never
kills a worker or a migration job.
"""
from __future__ import annotations

import json
import time

from initial_transition import concurrent_indexes, git_tree, verify_contained_exit
from initial_transition_ops import LIST_DIGEST, OWNER_LABEL, ZSET_DIGEST
from rehearse_initial_transition import (
    CANDIDATE_SHA, DSN, HEARTBEATS, NEGATIVE, PROCESSING, QUEUE, ROLES, TABLE_LOCK, TENANT_A, Refused,
)
from rehearse_legacy_queue import SYNTHETIC_ENV
from rehearse_legacy_queue_active import HOLDER_PROBE, lock_key, lock_parts

PROD_SHAPE = {'ALLOW_REAL_SENDS': 'true', 'BREVO_SEND_MODE': 'live', 'BROADCAST_ASYNC_ENABLED': 'false'}
BROADCAST_ON = {'ALLOW_REAL_SENDS': 'true', 'BREVO_SEND_MODE': 'live', 'BROADCAST_ASYNC_ENABLED': 'true'}
EXTERNAL_LEDGER = '29990101_000000_synthetic_external_ddl.sql'
RECONCILE_ACTION = 'team_pessoa_reconciliar_duplicidade'
OP_AUDIT = ("select count(*) from platform_audit_log where acao = '" + RECONCILE_ACTION
            + "' and detalhe->>'operation_id' = '{op}'")
NULL_OP_AUDIT = "acao = '" + RECONCILE_ACTION + "' and detalhe->>'operation_id' is null"
# Legacy queue keys (07a3f4d and candidate queue_worker.py): DLQ list, scheduled-retry zset.
DEAD_LETTER = 'pastorai:webhooks:dead'
RETRY_SCHEDULED = 'pastorai:webhooks:retry-scheduled'


def seed_dead_and_retry(f):
    """One synthetic DLQ item and one retry due in 24 h (never promoted during the run, no send)."""
    item = json.dumps({'payload': {'event': 'synthetic.rehearsal.dead', 'data': {}}, 'attempts': 3})
    retry = json.dumps({'payload': {'event': 'synthetic.rehearsal.retry', 'data': {}}, 'attempts': 1})
    f.rcli(0, 'RPUSH', DEAD_LETTER, item)
    f.rcli(0, 'ZADD', RETRY_SCHEDULED, str(int(time.time()) + 86400), retry)
    dead = f.rcli(0, 'EVAL', LIST_DIGEST, '1', DEAD_LETTER).split()
    flat = f.rcli(0, 'EVAL', ZSET_DIGEST, '1', RETRY_SCHEDULED).split()
    f.check(len(dead) == 1 and len(flat) == 2, 'seed-dead-retry',
            'fixture-dead-letter-item-and-future-scheduled-retry-persistent')
    return {DEAD_LETTER: dead}, {RETRY_SCHEDULED: [[flat[0], flat[1]]]}


def expect_run(f, label, *args, code=0, refusal=None, background=False):
    exit_code, out = f.controller(*args)
    f.check(exit_code == code and (refusal is None or out.get('code') == refusal),
            f'{label}:exit={exit_code}:code={out.get("code")}', label)
    return out


def ddl_marker(f):
    return any(e['kind'] == 'ddl-marker' for e in f.journal())


def queue_in_flight(f):
    """Holder on the real legacy advisory lock of m1: m1 claimed and waiting; m2 parked in the queue."""
    holder = f.legacy_run('holder', ['-c', HOLDER_PROBE, DSN, TENANT_A, 'm1', 'synthetic:held', 'synthetic:release'],
                          env={**SYNTHETIC_ENV, 'REDIS_URL': 'redis://redis:6379/3'})
    f.probes.append(holder)
    f.until(lambda: f.rcli(3, 'GET', 'synthetic:held') != '', 'holder')
    f.check(f.webhook('m1') == '202' and f.webhook('m2') == '202', 'legacy-webhooks')
    classid, objid = lock_parts(lock_key(TENANT_A, 'm1'))
    waiting = (f"select count(*) from pg_locks where locktype = 'advisory' and not granted and classid = {classid} "
               f"and objid = {objid}")
    f.until(lambda: f.psql(waiting) == '1' and f.rcli(0, 'LLEN', QUEUE) == '1', 'queue-barrier', 60)
    f.check(f.messages('m1')['m1'] == 0, 'ingested-through-barrier',
            'queue-worker-claimed-m1-waiting-on-real-advisory-lock-m2-parked')
    f.m2_digest = f.rcli(0, 'EVAL', LIST_DIGEST, '1', QUEUE).split()
    return holder


SELF_TERM = 'import os, signal; os.kill(1, signal.SIGTERM)'


def negative_control(f):
    """Own container kept ``always``: an exit NOT marked manual is restarted by the daemon and refused.

    ``docker kill`` marks the container manually stopped, so ``always`` does not
    restart it at once; it would on a daemon/host restart (not exercised here).
    The control therefore delivers SIGTERM from inside the container (an exit
    the daemon does not consider manual), the same path a supervisor or the
    daemon at boot would take. The persisted ``no`` policy is what changes it.
    """
    nid = f.legacy_run('negative', ['-I', '-c', NEGATIVE], network='none', restart='always')
    f.inert = [nid]
    ready = lambda: f.docker('logs', nid).count('handler-ready')
    f.until(lambda: ready() == 1, 'negative-ready')
    before = f.inspect(nid)
    observed = dict(restart_count=before['RestartCount'], started=before['State']['StartedAt'])
    f.observed['negative_control_pre'] = dict(restart_count=observed['restart_count'],
                                              handler_ready_lines=ready())
    f.docker('exec', nid, 'python3', '-I', '-c', SELF_TERM)

    def restarted_by_our_signal():
        data = f.inspect(nid)  # one consistent read; relative to what was observed before the signal
        return (data['RestartCount'] > observed['restart_count'] and data['State']['Running']
                and data['State']['StartedAt'] != observed['started'])
    f.until(restarted_by_our_signal, 'negative-restart')
    after = f.inspect(nid)
    code = verify_contained_exit(observed, after)
    f.observed['negative_control_raw'] = dict(code=code, restart_before=observed['restart_count'],
                                              restart_after=after['RestartCount'],
                                              started_changed=after['State']['StartedAt'] != observed['started'])
    f.check(code == 'restarted-after-signal' and after['State']['StartedAt'] != observed['started'],
            'negative-control', 'negative-control-always-restarts-after-non-manual-sigterm-and-is-refused')
    f.until(lambda: ready() == 2, 'negative-ready-again')
    f.docker('update', '--restart', 'no', nid)
    f.check(f.inspect(nid)['HostConfig']['RestartPolicy']['Name'] == 'no', 'positive-policy')
    f.docker('exec', nid, 'python3', '-I', '-c', SELF_TERM)
    f.until(lambda: not f.inspect(nid)['State']['Running'], 'negative-stop')
    f.sleep(3)
    final = f.inspect(nid)
    f.check(final['RestartCount'] == after['RestartCount'] and not final['State']['Running'], 'positive-control',
            'positive-control-restart-no-persisted-before-sigterm-stays-stopped')
    f.observed['negative_control'] = dict(code=code, restart_count=after['RestartCount'])
    status, created = f.runner_status(['docker', 'create', '--name', f.legacy_names['backend'], '--network', 'none',
                                       '--label', f'{OWNER_LABEL}={f.run_id}', f.legacy_tag, 'true'])
    if status == 0:
        f._record('containers', created)  # unexpected: still owned, still cleaned
    f.check(status != 0 and f.docker('ps', '-aq', '--no-trunc', '--filter',
                                     f'name=^/{f.legacy_names["backend"]}$').split() == [f.legacy['backend']],
            'name-conflict', 'legacy-name-conflict-shown-in-own-prefix-candidate-uses-separate-project')


def ingress_refused(f, label):
    """Contained: internal (Evolution -> backend:8000) and external (edge) ingress both refused, nothing written."""
    before = f.pjson("select json_build_object('messages', (select count(*) from messages))")
    internal = f.webhook('m-refused')
    edge = f.edge_get('/health', timeout=5)
    f.observed['ingress_while_contained'] = dict(internal=internal, edge=edge)
    f.check(internal != '202' and edge is None and f.messages('m-refused')['m-refused'] == 0
            and f.pjson("select json_build_object('messages', (select count(*) from messages))") == before,
            'ingress-not-contained', label)


def until_alive(f, process, predicate, code, timeout):
    def check():
        if process.poll() is not None:
            raise Refused(code + '-controller-exited')
        return predicate()
    f.until(check, code, timeout)


def release(f, key):
    f.rcli(3, 'SET', key, '1')


def fixture_main(f):
    dead, retry = seed_dead_and_retry(f)
    holder = queue_in_flight(f)
    negative_control(f)
    f.write_spec(dict(messages={'m0': 1, 'm1': 1}, redis_lists={QUEUE: f.m2_digest, **dead}, redis_zsets=retry,
                      redis_absent_prefixes=[PROCESSING]),
                 dict(messages={'m0': 1, 'm1': 1, 'm2': 1}, redis_lists={QUEUE: [], **dead}, redis_zsets=retry,
                      redis_absent_prefixes=[PROCESSING]), f.pending())
    expect_run(f, 'controller-observed-identities-sources-scope', 'run', '--until', 'observed')
    process = f.controller('run', '--until', 'contained', '--pause-at', 'contain:queue-worker:after-signal',
                           background=True)
    until_alive(f, process, lambda: (f.state / 'paused').exists(), 'pause-contain', 240)
    f.check(f.inspect(f.legacy['queue-worker'])['State']['Running'] and f.messages('m1')['m1'] == 0,
            'drain-before-release', 'sigterm-delivered-queue-worker-still-draining-m1-not-committed')
    f.kill_controller(process)
    (f.state / 'paused').unlink()
    f.sleep(2)
    f.check(f.inspect(f.legacy['queue-worker'])['State']['Running'], 'worker-died-with-controller',
            'controller-sigkilled-mid-containment-worker-unaffected')
    release(f, 'synthetic:release')
    f.finish(holder, 60, 'holder')
    expect_run(f, 'replay-after-crash-exit0-m1-once-m2-preserved-then-stable-db-redis-snapshot',
               'run', '--until', 'settled')
    ingress_refused(f, 'contained-internal-webhook-and-edge-health-refused-no-write')
    expect_run(f, 'reconciliation-real-script-preview-apply-audit-backfills-zero-release-preflight',
               'run', '--until', 'preflighted')
    f.check(f.duplicates() == 0, 'duplicates')
    # Crash while the first migration job is ACTIVE (blocked on a table lock held by a probe).
    locker = f.legacy_run('locker', ['-c', TABLE_LOCK, DSN, 'LOCK TABLE public.pessoas IN EXCLUSIVE MODE',
                                     'redis://redis:6379/3', 'synthetic:locked', 'synthetic:unlock'])
    f.probes.append(locker)
    f.until(lambda: f.rcli(3, 'GET', 'synthetic:locked') == '1', 'locker')
    process = f.controller('run', '--until', 'migrated', background=True)
    app = f'pastorai-mig-{f.run_id[:12]}-01-a1'
    blocked = f"select count(*) from pg_stat_activity where application_name = '{app}' and wait_event_type = 'Lock'"
    until_alive(f, process, lambda: f.psql(blocked) == '1', 'migration-blocked', 180)
    f.kill_controller(process)
    jobs = [e for e in f.journal() if e['kind'] == 'job']
    exit_code, out = f.controller('run', '--until', 'migrated')
    f.check(exit_code == 4 and out.get('code') == 'job-active' and f.psql(blocked) == '1'
            and [e for e in f.journal() if e['kind'] == 'job' and 'mig-' in e['name']]
            == [e for e in jobs if 'mig-' in e['name']], 'active-job-replay',
            'controller-sigkilled-during-active-migration-replay-waits-no-new-application')
    release(f, 'synthetic:unlock')
    f.finish(locker, 60, 'locker')
    expect_run(f, 'adopted-job-completed-46-pending-by-migrate.py-one-job-each-ledger-124',
               'run', '--until', 'migrated')
    # Candidate start + crash, then a real readiness failure (provider 503) after start.
    f.rcli(2, 'SET', 'synthetic:evo:fail-root', '1')
    process = f.controller('run', '--pause-at', 'candidate:backend:after-start', background=True)
    until_alive(f, process, lambda: (f.state / 'paused').exists(), 'pause-candidate', 600)
    f.kill_controller(process)
    (f.state / 'paused').unlink()
    expect_run(f, 'replay-after-start-crash-readiness-degraded-refused', 'run', code=3,
               refusal='candidate-not-ready')
    contained_candidate(f, 'post-ddl-candidate-failure-contained-restart-no-exit-observed-legacy-stays-stopped')
    expect_run(f, 'contained-candidate-requires-human-decision', 'run', code=3,
               refusal='candidate-contained-decision-required')
    f.rcli(2, 'DEL', 'synthetic:evo:fail-root')
    process = f.controller('run', '--decision', 'retry-candidate', '--pause-at', 'promote:after-policy',
                           background=True)
    until_alive(f, process, lambda: (f.state / 'paused').exists(), 'pause-promote', 600)
    f.kill_controller(process)
    f.check(all(f.inspect(i)['HostConfig']['RestartPolicy']['Name'] == 'always' for i in f.candidate().values())
            and not (f.dir / 'release-root' / 'current').exists(), 'partial-promotion',
            'crash-between-policy-always-and-current-link-no-false-success')
    expect_run(f, 'replay-partial-promotion-fresh-readiness-then-link', 'run')
    f.assert_promoted()
    f.check(f.webhook('m3') == '202', 'candidate-webhook')
    f.until(lambda: f.messages('m3')['m3'] == 1, 'candidate-ingest', 60)
    f.check(f.messages('m0', 'm1', 'm2', 'm3') == {'m0': 1, 'm1': 1, 'm2': 1, 'm3': 1}
            and f.effects().get('POST sendText', 0) == 0, 'final-messages',
            'backlog-m2-consumed-once-by-candidate-new-webhook-once-no-send-with-empty-pilot')
    f.check(f.rcli(0, 'EVAL', LIST_DIGEST, '1', DEAD_LETTER).split() == dead[DEAD_LETTER]
            and f.rcli(0, 'EVAL', ZSET_DIGEST, '1', RETRY_SCHEDULED).split() == retry[RETRY_SCHEDULED][0]
            and f.rcli(0, 'PTTL', DEAD_LETTER) == '-1' and f.rcli(0, 'PTTL', RETRY_SCHEDULED) == '-1',
            'dead-retry-preserved', 'dead-letter-and-future-retry-preserved-persistent-after-promotion')


def contained_candidate(f, label):
    for identifier in f.candidate().values():
        data = f.inspect(identifier)
        f.check(not data['State']['Running'] and data['HostConfig']['RestartPolicy']['Name'] == 'no'
                and data['State']['ExitCode'] == 0, 'candidate-not-contained')
    f.assert_legacy_contained(label)
    exit_code, out = f.controller('resume-legacy', '--confirm', 'any')
    f.check(exit_code == 3 and out.get('code') == 'post-ddl', 'resume-post-ddl')


def daemon_restart(f, role):
    """Real automatic restart: SIGTERM from inside (not ``docker kill``), the daemon restarts ``always``."""
    before = f.inspect(f.legacy[role])
    f.docker('exec', f.legacy[role], 'python3', '-I', '-c', SELF_TERM)

    def back():
        data = f.inspect(f.legacy[role])
        return (data['RestartCount'] == before['RestartCount'] + 1 and data['State']['Running']
                and data['State']['StartedAt'] != before['State']['StartedAt'])
    f.until(back, 'daemon-restart', 90)
    f.until(lambda: f.rcli(0, 'GET', HEARTBEATS[role]) in ('ready', 'running', 'idle'), 'restart-heartbeat', 90)
    return f.inspect(f.legacy[role])


def fixture_pre_ddl(f):
    # Legacy that already carries a restart history (k > 0) before the transition starts.
    f.observed['docker_server_version'] = f.docker('version', '--format', '{{.Server.Version}}').strip()
    queue_id = f.legacy['queue-worker']
    k = daemon_restart(f, 'queue-worker')['RestartCount']
    f.check(k == 1, 'k-not-raised', 'legacy-queue-worker-auto-restarted-before-observe-k-1')
    dead, retry = seed_dead_and_retry(f)
    holder = queue_in_flight(f)
    f.write_spec(dict(messages={'m0': 1, 'm1': 1}, redis_lists={QUEUE: f.m2_digest, **dead}, redis_zsets=retry,
                      redis_absent_prefixes=[PROCESSING]), {}, f.pending())
    process = f.controller('run', '--pause-at', 'reconcile:after-apply', background=True)
    f.wait_journal(lambda e: e['kind'] == 'done' and e.get('step') == 'signal:queue-worker', 'signal', process)
    release(f, 'synthetic:release')
    # Controller dies right after the reconciliation job COMMITTED, before verification/done/snapshot.
    until_alive(f, process, lambda: (f.state / 'paused').exists(), 'pause-reconcile', 600)
    f.check(f.psql(OP_AUDIT.format(op=f.reconcile['operacao'])) == '1' and f.duplicates() == 0
            and not any(e['kind'] == 'done' and e.get('step') == 'reconcile' for e in f.journal()),
            'reconcile-not-committed', 'reconciliation-committed-by-real-job-before-controller-crash')
    f.kill_controller(process)
    (f.state / 'paused').unlink()
    # Real PostgreSQL, while recovery is pending: (B4) a same-action audit row WITHOUT operation_id and
    # (B5) a field of the operation's own audit row are each changed; recovery must refuse, never absorb.
    op = f.reconcile['operacao']
    for label, change, revert in (
            ('null-operation-audit-row', f"update platform_audit_log set alvo_nome = 'synthetic-changed' where {NULL_OP_AUDIT}",
             f"update platform_audit_log set alvo_nome = null where {NULL_OP_AUDIT}"),
            ('operation-audit-field', "update platform_audit_log set actor_email = 'synthetic-changed' where acao = '"
             + RECONCILE_ACTION + f"' and detalhe->>'operation_id' = '{op}'",
             "update platform_audit_log set actor_email = null where acao = '" + RECONCILE_ACTION
             + f"' and detalhe->>'operation_id' = '{op}'")):
        f.psql(change)
        exit_code, out = f.controller('run')
        f.check(exit_code == 3 and out.get('code') == 'reconcile-delta-mismatch'
                and not any(e['kind'] == 'done' and e.get('step') == 'reconcile' for e in f.journal()),
                'absorbed:' + label, f'pg-recovery-refuses-changed-{label}')
        f.psql(revert)  # reviewed human reversal (synthetic)
    exit_code, _ = f.controller('run')
    _, status = f.controller('status')
    recovered = [e for e in f.journal() if e['kind'] == 'done' and e.get('step') == 'reconcile']
    apply_jobs = [e for e in f.journal() if e['kind'] == 'job' and e.get('step') == 'reconcile:apply']
    f.check(recovered and recovered[-1].get('recovered') is True and len(apply_jobs) == 1
            and f.psql(OP_AUDIT.format(op=f.reconcile['operacao'])) == '1', 'reconcile-recovery',
            'replay-adopted-committed-apply-job-exact-delta-verified-no-reapplication')
    f.check(exit_code == 3 and status.get('last_refusal') == 'backfill-candidates' and not ddl_marker(f)
            and status.get('resume_token'), 'pre-ddl-refusal',
            'pre-ddl-refusal-backfill-candidate-after-reconciliation-no-ddl-marker')
    f.assert_legacy_contained('pre-ddl-legacy-contained-restart-no', restart_counts={'queue-worker': k})
    observe = [e for e in f.journal() if e['kind'] == 'done' and e.get('step') == 'observe'][-1]
    contained = f.inspect(queue_id)
    f.check(observe['legacy']['queue-worker']['restart_count'] == k and contained['RestartCount'] == k
            and contained['HostConfig']['RestartPolicy']['Name'] == 'no', 'k-not-kept',
            'k-observed-and-kept-by-update-and-stop')
    k_started = contained['State']['StartedAt']
    # External DDL trace without marker: the legacy is not restarted.
    f.psql(f"insert into schema_migrations (name) values ('{EXTERNAL_LEDGER}')")
    _, status = f.controller('status')
    expect_run(f, 'external-ledger-change-blocks-legacy-resume', 'resume-legacy', '--confirm',
               status['resume_token'], code=3, refusal='ledger-not-baseline')
    f.assert_legacy_contained('legacy-still-contained-after-refused-resume')
    f.psql(f"delete from schema_migrations where name = '{EXTERNAL_LEDGER}'")  # reviewed human reversal
    expect_run(f, 'resume-refuses-wrong-token', 'resume-legacy', '--confirm', 'RETOMAR-LEGADO-PRE-DDL:wrong',
               code=3, refusal='confirmation')
    _, status = f.controller('status')
    # Crash after the role intent, BEFORE any update/start; then a critical queue changes.
    process = f.controller('resume-legacy', '--confirm', status['resume_token'], '--pause-at',
                           'legacy-resume:backend:before-update', background=True)
    until_alive(f, process, lambda: (f.state / 'paused').exists(), 'pause-resume', 120)
    f.kill_controller(process)
    (f.state / 'paused').unlink()
    f.rcli(0, 'RPUSH', DEAD_LETTER, '{"synthetic": "late-dead-letter"}')
    exit_code, out = f.controller('resume-legacy', '--confirm', 'replay')
    f.check(exit_code == 3 and out.get('code') in ('writer-after-settle', 'expectation-mismatch')
            and not any(f.inspect(f.legacy[r])['State']['Running'] for r in ROLES), 'resume-intent-relaxed',
            'resume-crash-before-update-intent-only-never-relaxes-queue-gate-zero-legacy-started')
    f.rcli(0, 'RPOP', DEAD_LETTER)  # reviewed human reversal of the late item
    # Crash after the REAL start of backend (before ``done``): the replay sees a new execution.
    process = f.controller('resume-legacy', '--confirm', 'replay', '--pause-at',
                           'legacy-resume:backend:after-start', background=True)
    until_alive(f, process, lambda: (f.state / 'paused').exists(), 'pause-resume-start', 180)
    f.kill_controller(process)
    (f.state / 'paused').unlink()
    f.check(f.inspect(f.legacy['backend'])['State']['Running'], 'backend-not-started',
            'resume-crash-after-real-start-backend-running-new-execution')
    # Second crash, on the k > 0 role: after the REAL start of queue-worker, before its ``done``.
    process = f.controller('resume-legacy', '--confirm', 'replay', '--pause-at',
                           'legacy-resume:queue-worker:after-start', background=True)
    until_alive(f, process, lambda: (f.state / 'paused').exists(), 'pause-resume-queue-start', 180)
    f.kill_controller(process)
    (f.state / 'paused').unlink()
    started = f.inspect(queue_id)
    queue_done = lambda: [e for e in f.journal() if e['kind'] == 'done' and e.get('step') == 'legacy-resume:queue-worker']
    f.observed['queue_after_start_crash'] = dict(observed_k=k, restart_count=started['RestartCount'],
                                                 running=started['State']['Running'], done_entries=len(queue_done()))
    f.check(started['Id'] == queue_id and started['State']['Running'] and started['RestartCount'] == 0
            and started['State']['StartedAt'] != k_started and not queue_done(), 'queue-start-crash',
            'resume-crash-after-real-start-queue-worker-k1-runtime-0-no-done')
    expect_run(f, 'confirmed-resume-pre-ddl-replayed-after-start-crash', 'resume-legacy', '--confirm', 'replay')
    adopted = f.inspect(queue_id)
    f.observed['queue_after_replay'] = dict(same_id=adopted['Id'] == queue_id,
                                            same_started=adopted['State']['StartedAt'] == started['State']['StartedAt'],
                                            restart_count=adopted['RestartCount'], done_entries=len(queue_done()))
    f.check(adopted['Id'] == queue_id and adopted['State']['StartedAt'] == started['State']['StartedAt']
            and adopted['RestartCount'] == 0 and len(queue_done()) == 1, 'queue-not-adopted',
            'replay-adopted-same-queue-execution-id-and-startedat-intact-one-done')
    for role in ROLES:
        data = f.inspect(f.legacy[role])
        f.check(data['State']['Running'] and data['HostConfig']['RestartPolicy']['Name'] == 'always'
                and data['Id'] == f.legacy[role], 'legacy-resumed')
    resumed = f.inspect(queue_id)
    queue_done = [e for e in f.journal() if e['kind'] == 'done' and e.get('step') == 'legacy-resume:queue-worker'][-1]
    f.observed['restart_count_k'] = dict(observed=k, contained=contained['RestartCount'],
                                         resumed=resumed['RestartCount'], journal_done=queue_done['restart_count'])
    f.check(resumed['Id'] == queue_id and resumed['RestartCount'] == 0 and queue_done['restart_count'] == 0
            and resumed['State']['StartedAt'] != k_started and resumed['HostConfig']['RestartPolicy']['Name'] == 'always',
            'k-resume', 'same-id-resumed-counter-reset-to-0-new-startedat-policy-always-done-0')
    f.until(lambda: f.messages('m2')['m2'] == 1, 'legacy-backlog', 90)
    f.check(f.edge_get('/health') == 200 and f.duplicates() == 0
            and f.psql(OP_AUDIT.format(op=f.reconcile['operacao'])) == '1', 'resume-state',
            'legacy-resumed-same-ids-policy-always-backlog-m2-once-reconciliation-kept-not-undone')
    expect_run(f, 'terminal-replay-after-backlog-consumed-revalidated-ok', 'resume-legacy', '--confirm', 'replay')
    daemon_restart(f, 'queue-worker')  # real automatic restart of an already resumed role
    expect_run(f, 'terminal-replay-after-real-restart-refused', 'resume-legacy', '--confirm', 'replay', code=3,
               refusal='legacy-resumed-state-changed')
    expect_run(f, 'run-after-legacy-resume-refused', 'run', code=3, refusal='legacy-resumed-terminal')


def fixture_post_ddl(f):
    pending = f.pending()
    target, second = '20261023_100001_ai_usage_tenant_created_idx.sql', '20261023_110001_notification_outbox_pending_created_idx.sql'
    blobs = git_tree(f.repo, CANDIDATE_SHA, ('backend/migrations',),
                     __import__('re').compile(r'backend/migrations/20261023_1[01]000[1]_.*\.sql'))
    first_index = concurrent_indexes(blobs['backend/migrations/' + target])
    second_index = concurrent_indexes(blobs['backend/migrations/' + second])
    f.check(len(first_index) == 1 and len(second_index) == 1, 'index-names')
    f.write_spec(dict(messages={'m0': 1}, redis_lists={QUEUE: []}, redis_absent_prefixes=[PROCESSING]),
                 dict(messages={'m0': 1}, redis_lists={QUEUE: []}, redis_absent_prefixes=[PROCESSING]), pending)
    expect_run(f, 'no-duplicate-reconciliation-skipped-explicitly', 'run', '--until', 'preflighted')
    ingress_refused(f, 'contained-internal-webhook-and-edge-health-refused-no-write')
    # External ledger change between preflighted and the DDL: refused with NO marker.
    f.psql(f"insert into schema_migrations (name) values ('{EXTERNAL_LEDGER}')")
    expect_run(f, 'external-ledger-change-after-preflight-refused', 'run', '--until', 'migrated', code=3,
               refusal='ledger-not-baseline')
    f.check(not ddl_marker(f), 'marker-written', 'no-ddl-marker-after-fresh-pre-ddl-refusal')
    f.psql(f"delete from schema_migrations where name = '{EXTERNAL_LEDGER}'")
    # CONCURRENTLY under an old snapshot: its own lock_timeout leaves an INVALID index.
    snap = f.legacy_run('snapshot', ['-c', TABLE_LOCK, DSN, 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ; '
                                     'SELECT txid_current()', 'redis://redis:6379/3', 'synthetic:snap',
                                     'synthetic:unsnap'])
    f.probes.append(snap)
    f.until(lambda: f.rcli(3, 'GET', 'synthetic:snap') == '1', 'snapshot-holder')
    expect_run(f, 'concurrent-index-lock-timeout-invalid-index-refused-ledger-absent', 'run', '--until', 'migrated',
               code=3, refusal='concurrent-index-invalid')
    invalid = f.pjson("select coalesce(json_agg(c.relname), '[]') from pg_index i join pg_class c on "
                      "c.oid = i.indexrelid where not i.indisvalid")
    f.check(invalid == first_index and target not in f.ledger(), 'invalid-index')
    f.assert_legacy_contained('post-ddl-failure-legacy-stays-contained')
    expect_run(f, 'post-ddl-legacy-resume-refused', 'resume-legacy', '--confirm', 'any', code=3, refusal='post-ddl')
    expect_run(f, 'refusal-sticky-without-decision', 'run', code=3, refusal='concurrent-index-invalid')
    expect_run(f, 'decision-refused-while-invalid-index-exists', 'run', '--decision', f'retry-migration:{target}',
               code=3, refusal='retry-precondition')
    release(f, 'synthetic:unsnap')
    f.finish(snap, 60, 'snapshot')
    f.psql(f'DROP INDEX CONCURRENTLY public.{first_index[0]}')  # reviewed human action
    # Next CONCURRENTLY: index built VALID but the ledger INSERT fails (synthetic trigger).
    f.psql("create function public.synthetic_ledger_block() returns trigger language plpgsql as $$ begin "
           f"if new.name = '{second}' then raise exception 'synthetic ledger failure'; end if; return new; end $$; "
           "create trigger synthetic_ledger_block before insert on public.schema_migrations for each row "
           "execute function public.synthetic_ledger_block()")
    expect_run(f, 'retry-attempt-2-then-valid-index-without-ledger-refused', 'run', '--decision',
               f'retry-migration:{target}', code=3, refusal='concurrent-index-present-ledger-absent')
    f.check(target in f.ledger() and second not in f.ledger() and f.pjson(
        "select coalesce(json_agg(c.relname), '[]') from pg_index i join pg_class c on c.oid = i.indexrelid "
        f"where i.indisvalid and c.relname = '{second_index[0]}'") == second_index, 'valid-index-no-ledger')
    jobs = [e for e in f.journal() if e['kind'] == 'job']
    expect_run(f, 'valid-index-present-blocks-retry-no-if-not-exists-replay', 'run', '--decision',
               f'retry-migration:{second}', code=3, refusal='retry-precondition')
    f.check([e for e in f.journal() if e['kind'] == 'job'] == jobs, 'retry-created-job',
            'no-new-job-while-valid-index-of-failed-attempt-exists')
    f.psql('drop trigger synthetic_ledger_block on public.schema_migrations; '
           'drop function public.synthetic_ledger_block()')
    f.psql(f'DROP INDEX CONCURRENTLY public.{second_index[0]}')  # reviewed human action
    # Planted conflicting release tree: promotion refuses before any restart policy and contains.
    planted = f.dir / 'release-root' / 'releases' / CANDIDATE_SHA / 'deploy'
    planted.mkdir(parents=True)
    (planted / 'unexpected.txt').write_text('synthetic conflicting layout\n')
    expect_run(f, 'retry-forward-then-conflicting-layout-refused', 'run', '--decision', f'retry-migration:{second}',
               code=3, refusal='layout-mismatch')
    contained_candidate(f, 'layout-failure-candidate-contained-before-any-always-policy')
    f.check(not any(e.get('step', '').startswith('promote:policy') for e in f.journal()), 'policy-before-layout')
    import shutil
    shutil.rmtree(f.dir / 'release-root' / 'releases' / CANDIDATE_SHA)  # reviewed human cleanup of the conflict
    expect_run(f, 'decision-retry-candidate-new-epoch-promoted', 'run', '--decision', 'retry-candidate')
    f.assert_promoted()


def fixture_broadcast(f):
    first, second = f.deliveries
    states = lambda: f.pjson("select coalesce(json_object_agg(id, status), '{}') from broadcast_entregas")
    f.write_spec(dict(messages={'m0': 1}, deliveries={first: 'aceito', second: 'pendente'}),
                 dict(messages={'m0': 1}, deliveries={first: 'aceito', second: 'aceito'}), f.pending())
    # Pause right after broadcast-worker's restart policy is persisted, BEFORE its SIGTERM.
    process = f.controller('run', '--until', 'contained', '--pause-at', 'contain:broadcast-worker:after-policy',
                           background=True)
    until_alive(f, process, lambda: (f.state / 'paused').exists(), 'pause-broadcast', 300)
    f.seed_deliveries()
    f.until(lambda: f.rcli(2, 'GET', 'synthetic:evo:held') == '1' and states().get(first) == 'em_envio', 'broadcast-held', 30)
    held_at = time.monotonic()
    f.check(states() == {first: 'em_envio', second: 'pendente'}, 'broadcast-claim',
            'legacy-broadcast-real-claim-em-envio-transport-held-at-fake-provider')
    f.kill_controller(process)
    (f.state / 'paused').unlink()
    process = f.controller('run', '--until', 'settled', background=True)
    f.wait_journal(lambda e: e['kind'] == 'done' and e.get('step') == 'signal:broadcast-worker', 'signal', process, 60)
    f.sleep(1)
    f.timings['held_to_checked_s'] = round(time.monotonic() - held_at, 3)
    f.check(f.inspect(f.legacy['broadcast-worker'])['State']['Running'] and states()[first] == 'em_envio'
            and f.effects().get('POST sendText', 0) == 0, 'in-flight',
            'controller-replayed-after-pause-sigterm-during-real-send-worker-alive-delivery-em-envio')
    f.rcli(2, 'SET', 'synthetic:evo:release', '1')
    process.wait(timeout=600)
    f.check(process.returncode == 0 and f.effects().get('POST sendText') == 1 and states() ==
            {first: 'aceito', second: 'pendente'}, 'drain',
            'in-flight-send-completed-once-aceito-second-delivery-preserved-pendente')
    expect_run(f, 'promoted-with-broadcast-enabled-candidate', 'run')
    f.assert_promoted()
    sends = f.rcli(2, 'LRANGE', 'synthetic:evo:sends', '0', '-1').split()
    f.check(f.effects().get('POST sendText') == 2 and len(set(sends)) == 2 and states() ==
            {first: 'aceito', second: 'aceito'}, 'candidate-send',
            'candidate-sent-preserved-delivery-exactly-once-no-resend-of-first')


FIXTURES = {'main': (fixture_main, PROD_SHAPE, True), 'pre-ddl': (fixture_pre_ddl, PROD_SHAPE, True),
            'post-ddl': (fixture_post_ddl, PROD_SHAPE, True), 'broadcast': (fixture_broadcast, BROADCAST_ON, False)}
_ = (time, Refused)
