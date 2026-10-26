"""Pre-DDL legacy resume of the initial transition (confirmed, re-proven on every invocation)."""
from __future__ import annotations

START_ORDER = ('backend', 'queue-worker', 'broadcast-worker', 'cron-worker')
TERMINAL = 'legacy-resumed'


def canonical(value):
    from initial_transition import canonical as digest
    return digest(value)


def resume_legacy(t, confirmation, expected_token):
    """Pre-DDL only, confirmed; every invocation (also a replay after a crash) re-proves the target.

    Endpoint, owned topology, legacy identity/gates, baseline ledger and the
    absence of any DDL trace are checked before EACH start. Roles already
    resumed must be running with their original policy; the domain
    snapshot is only required before the first legacy consumer is back.
    """
    if t.j.find('ddl-marker'):
        t.refuse('post-ddl', 'legacy-resume')
    if t.reached(TERMINAL):
        return
    started = t.j.find('intent', 'legacy-resume')
    if not started and confirmation != expected_token:
        t.refuse('confirmation', 'legacy-resume')
    t.base_checks()
    t.revalidate()
    if not t.reached('contained'):
        t.refuse('resume-not-contained', 'legacy-resume')
    t.resume_preconditions()
    t.recover_reconciliation()  # a committed apply is proven exactly, then becomes the baseline
    evidence = {r: execution_evidence(t, r) for r in START_ORDER}
    if 'exited-after-start' in evidence.values() or 'inconsistent' in evidence.values():
        t.refuse('legacy-resume-ambiguous', 'legacy-resume')  # ran and stopped, or unexplained: human
    resumed = [r for r in START_ORDER if evidence[r] == 'running']
    # Only an OBSERVED new execution relaxes the data/queue gates; an intent alone never does.
    if not resumed:  # before the first legacy consumer is back: data and critical queues unchanged
        if t.baseline_snapshot() is not None and t.baseline_snapshot() != t.snapshot():
            t.refuse('writer-after-settle', 'legacy-resume')
        t.critical_state('legacy-resume')
    t.check_scope(legacy_running=resumed)
    if not started:
        t.j.append('intent', step='legacy-resume', reconciliation_kept=t.done('reconcile'))
    for role in START_ORDER:
        step = f'legacy-resume:{role}'
        if t.done(step):
            continue
        t.resume_preconditions()  # again right before each start
        item = t.legacy()[role]
        t.j.append('intent', step=step)
        t.checkpoint(f'legacy-resume:{role}:before-update')
        t.ops.update_restart(item['id'], item['policy'])
        data = t.ops.inspect(item['id']) or {}
        if ((data.get('HostConfig') or {}).get('RestartPolicy') or {}).get('Name') != item['policy']:
            t.refuse('restart-policy-not-persisted', step)
        if not (data.get('State') or {}).get('Running'):
            t.ops.start(item['id'])
        limit = t.clock() + t.t['ready_s']
        while not ((data := t.ops.inspect(item['id']) or {}).get('State') or {}).get('Running'):
            if t.clock() >= limit:
                t.refuse('legacy-start-failed', step)
            t.sleep(0.2)
        t.checkpoint(f'legacy-resume:{role}:after-start')  # real start observed, ``done`` not yet written
        t.j.append('done', step=step, started=data['State']['StartedAt'],
                   restart_count=data.get('RestartCount', 0), policy=item['policy'])
    t.phase(TERMINAL)

def resume_preconditions(t):
    ledger = t.ops.ledger()
    if len(ledger) != t.observed()['ledger_count'] or canonical(ledger) != t.observed()['ledger_digest']:
        t.refuse('ledger-not-baseline', 'legacy-resume')
    if (t.ops.invalid_indexes() or t.ops.index_builds() or t.migration_sessions()
            or [e for e in t.j.find('job') if e.get('step', '').startswith('migration:')]
            or t.candidate_ids()):
        t.refuse('ddl-trace-before-marker', 'legacy-resume')


def execution_evidence(t, role):
    """``none`` | ``running`` | ``exited-after-start`` | ``inconsistent`` for one legacy role.

    A new execution is a ``StartedAt`` different from the one observed before
    containment (the contained process kept it). ``done`` roles were already
    re-checked by ``revalidate`` (same execution, original policy, running).
    """
    item = t.legacy()[role]
    data = t.ops.inspect(item['id']) or {}
    state = data.get('State') or {}
    new_execution = state.get('StartedAt') != item['started']
    if t.done(f'legacy-resume:{role}'):
        return 'running'
    if state.get('Running'):
        # Exactly the one start we issued: a daemon restart since then is unexplained.
        restarted = data.get('RestartCount', 0) != item['restart_count']
        return 'running' if new_execution and not restarted else 'inconsistent'
    if new_execution:
        return 'exited-after-start'
    return 'none'
