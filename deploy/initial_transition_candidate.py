"""Candidate side of the initial transition: create, start, readiness, promotion, containment.

The candidate lives in its OWN Compose project (``docker rename`` would keep the
legacy Compose labels, so the legacy project is never reused and never ``up``-ed).
Promotion order: release layout written/verified (no process effect) -> fresh
identity + readiness of this invocation -> restart ``always`` persisted ->
identity re-checked -> ``current`` link. Any refusal after the DDL marker and
before promotion contains the candidate (``contain_candidate``); restarting it
requires the human decision ``retry-candidate`` and starts a new epoch.
"""
from __future__ import annotations

import json

from initial_transition_files import activate, write_layout
from initial_transition_ops import COMPOSE_PROJECT, OWNER_LABEL, READY_PROBE, gates_of, host_exposed

ROLES = ('backend', 'queue-worker', 'cron-worker', 'broadcast-worker')
CONTAIN_ORDER = ('backend', 'cron-worker', 'broadcast-worker', 'queue-worker')
START_ORDER = ('backend', 'queue-worker', 'broadcast-worker', 'cron-worker')


def policy(data):
    return ((data.get('HostConfig') or {}).get('RestartPolicy') or {}).get('Name')


def validate_created(t, ids):
    spec = t.spec['candidate']
    names = {key: t.ops.network_members(t.spec['network'][key])[0]['Name'] for key in ('app', 'edge')}
    for role in ROLES:
        data = t.ops.inspect(ids[role]) or {}
        labels = (data.get('Config') or {}).get('Labels') or {}
        attached = set((data.get('NetworkSettings') or {}).get('Networks') or {})
        expected = {names['app'], *([names['edge']] if role == 'backend' else [])}
        if (data.get('Image') != spec['image'] or labels.get(COMPOSE_PROJECT) != spec['project']
                or labels.get(OWNER_LABEL) != t.spec['run_id'] or data.get('Name', '').lstrip('/') != spec['names'][role]
                or host_exposed(data) or attached != expected):
            t.refuse('candidate-identity', 'candidate:create', role=role)
        if gates_of(data) != t.legacy()[role]['gates']:
            t.refuse('candidate-gates-differ', 'candidate:create', role=role)
        expected_policy = 'always' if t.cdone(f'promote:policy:{role}') else 'no'
        if policy(data) != expected_policy:
            t.refuse('candidate-restart-policy', 'candidate:create', role=role)


def verify_running(t, ids):
    """All four running the execution started in this epoch (no silent restart)."""
    for role in ROLES:
        data = t.ops.inspect(ids[role]) or {}
        started = t.j.last('done', f'candidate:start:{role}', t.epoch())
        if (not (data.get('State') or {}).get('Running') or data.get('RestartCount', 0) != 0
                or not started or (data.get('State') or {}).get('StartedAt') != started.get('started')):
            t.refuse('candidate-not-running', 'candidate', role=role)


def ready_check(t):
    """Fresh probes of THIS invocation: /ready status ready with workers ok, and edge /health."""
    image = t.spec['candidate']['image']
    _, code, out = t.job('ready', t.probe_name('ready'), image=image,
                         args=['-I', '-c', READY_PROBE, 'http://backend:8000/ready', str(t.t['ready_s']), 'ready'])
    ready = json.loads(out.strip().splitlines()[-1]) if code == 0 and out.strip() else {}
    body = ready.get('body') or {}
    if (ready.get('status') != 200 or body.get('status') != 'ready' or set((body.get('required') or {}).values())
            != {'ok'} or set((body.get('workers') or {}).values()) != {'ok'}):
        t.refuse('candidate-not-ready', 'ready', observed=body.get('status'))
    # External ingress: a job on the edge network only (the proxy side), never on app.
    _, code, out = t.job('edge', t.probe_name('edge-health'), image=image, network='edge',
                         args=['-I', '-c', READY_PROBE, 'http://backend:8000/health', '30', 'any'])
    if code != 0 or not out.strip() or json.loads(out.strip().splitlines()[-1]).get('status') != 200:
        t.refuse('candidate-edge-health', 'edge')
    return body.get('status')


def run_candidate(t):
    if t.reached('candidate-ready'):
        verify_running(t, t.candidate_ids())
        return
    if t.epoch():
        consumed = t.j.last('decision', 'candidate', t.epoch())
        if not consumed:
            if t.decision != 'retry-candidate':
                t.refuse('candidate-contained-decision-required', 'candidate')
            t.j.append('decision', value=t.decision, step='candidate')
    spec = t.spec['candidate']
    if not t.done('candidate:create'):
        t.j.append('intent', step='candidate:create', project=spec['project'], compose_sha256=spec['compose_sha256'])
        t.ops.compose_create(spec['project'], spec['compose_file'])
        ids = t.ops.compose_ids(spec['project'])
        if set(ids) != set(ROLES):
            t.refuse('candidate-services', 'candidate:create')
        t.j.append('done', step='candidate:create', ids=ids, project=spec['project'])
    ids = t.candidate_ids()
    validate_created(t, ids)
    for role in START_ORDER:
        step = f'candidate:start:{role}'
        if t.cdone(step):
            continue
        data = t.ops.inspect(ids[role]) or {}
        if not (data.get('State') or {}).get('Running'):
            t.j.append('intent', step=step)
            t.ops.start(ids[role])
            t.checkpoint(f'candidate:{role}:after-start')
        data = t.ops.inspect(ids[role]) or {}
        t.j.append('done', step=step, started=(data.get('State') or {}).get('StartedAt'))
    verify_running(t, ids)
    status = ready_check(t)
    limit = t.clock() + t.t['ready_s']
    while problems := t.check_expectations('expect_candidate'):
        if t.clock() >= limit:
            t.refuse('candidate-expectation-mismatch', 'candidate:expect', problems=problems)
        t.sleep(1)
    t.check_scope(legacy_running=(), candidate_running=ROLES)
    t.j.append('done', step='candidate:ready', readiness=status)
    t.phase('candidate-ready')


def release_contract(t):
    """Public topology the next ``backend-release.sh`` adopts: permanent project, the existing
    app network (name + ID), candidate container names and the contained legacy IDs."""
    spec = t.spec
    network = t.ops.network_members(spec['network']['app'])[0]
    return dict(schema='pastorai.release-topology', version=1, project=spec['candidate']['project'],
                legacy_project=spec['legacy']['project'],
                network=dict(name=network['Name'], id=spec['network']['app']),
                containers={role: spec['candidate']['names'][role] for role in ROLES},
                reserved_legacy={role: t.legacy()[role]['id'] for role in ROLES})


def run_promote(t):
    ids = t.candidate_ids()
    if t.reached('promoted'):
        verify_running(t, ids)
        if any(policy(t.ops.inspect(ids[r]) or {}) != 'always' for r in ROLES):
            t.refuse('candidate-restart-policy', 'promote')
        activate(t.spec['release_root'], t.spec['candidate']['sha'])  # verifies the existing link only
        return
    # 1. Layout first: no process effect, idempotent, verified on every invocation.
    if not t.done('promote:layout'):
        t.j.append('intent', step='promote:layout')
    files = write_layout(t.spec['release_root'], t.spec['candidate']['sha'], t.files(), release_contract(t),
                         t.manifest(), t.spec['candidate']['image'])
    if not t.done('promote:layout'):
        t.j.append('done', step='promote:layout', files=files)
    # 2. Fresh identity + readiness of this invocation, before any persistent policy.
    verify_running(t, ids)
    ready_check(t)
    # 3. Persist restart ``always`` (inspect-proven); a crash here replays 1-2 first.
    for role in ROLES:
        step = f'promote:policy:{role}'
        if not t.cdone(step):
            t.j.append('intent', step=step)
            t.ops.update_restart(ids[role], 'always')
            if policy(t.ops.inspect(ids[role]) or {}) != 'always':
                t.refuse('restart-policy-not-persisted', step)
            t.j.append('done', step=step, persisted='always')
    t.checkpoint('promote:after-policy')
    verify_running(t, ids)
    if not t.done('promote:current'):
        t.j.append('intent', step='promote:current')
        activate(t.spec['release_root'], t.spec['candidate']['sha'])
        t.j.append('done', step='promote:current', project=t.spec['candidate']['project'])
    t.phase('promoted')


def contain_candidate(t, reason):
    """Post-DDL failure: persist restart ``no``, SIGTERM, observe exit. Never SIGKILL, never the legacy."""
    ids = t.candidate_ids()
    t.j.append('intent', step='candidate-contain', reason=reason)
    for role in CONTAIN_ORDER:
        t.ops.update_restart(ids[role], 'no')
        data = t.ops.inspect(ids[role]) or {}
        if policy(data) != 'no':
            t.refuse('candidate-containment-failed', 'candidate-contain', role=role)
        if (data.get('State') or {}).get('Running'):
            t.ops.signal(ids[role])
    for role in CONTAIN_ORDER:
        limit = t.clock() + t.t['grace_s']
        while ((t.ops.inspect(ids[role]) or {}).get('State') or {}).get('Running'):
            if t.clock() >= limit:
                t.refuse('candidate-containment-timeout', 'candidate-contain', role=role)
            t.sleep(0.2)
    t.j.append('candidate-contained', reason=reason, ids=ids)
