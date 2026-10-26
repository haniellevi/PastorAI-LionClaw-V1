"""Pre-DDL duplicate-link reconciliation of the initial transition (real script, exact delta).

A scoped baseline is journaled before the apply job; the result is accepted
only as the exact authorized delta, also when a replay adopts an apply job that
committed before the controller died. ``resume-legacy`` adopts an existing,
already started apply job but never creates or starts one.
"""
from __future__ import annotations

import json
import re

from initial_transition_files import sha256


def canonical(value):
    from initial_transition import canonical as digest
    return digest(value)


def reconcile_payload_sha(spec):
    """Same canonical payload as ``DuplicateLinkReconciliation.payload_sha256`` (audited per operation)."""
    r = spec['reconcile']
    payload = {'operation_id': r['operacao'], 'igreja_id': r['igreja'], 'pessoa_id': r['pessoa'],
               'keep_user_id': r['manter'], 'target_user_id': r['corrigir'], 'church_admin_id': r['admin_igreja'],
               'operator_id': r['operador'], 'release_sha': spec['candidate']['sha']}
    return sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode())


def expected_audit_detail(spec):
    """``detalhe`` exactly as ``team_pessoa.reconcile_duplicate_link`` writes it for this operation."""
    r = spec['reconcile']
    return {'operation_id': r['operacao'], 'payload_sha256': reconcile_payload_sha(spec), 'operacao': 'desvincular',
            'igreja_id': r['igreja'], 'pessoa_id': r['pessoa'], 'conta_mantida': r['manter'],
            'conta_corrigida': r['corrigir'], 'admin_igreja': r['admin_igreja'],
            'release_sha': spec['candidate']['sha']}


def scope(t):
    r = t.spec['reconcile']
    return t.ops.reconcile_scope(target=r['corrigir'], operation=r['operacao'], operator=r['operador'],
                                 detail=expected_audit_detail(t.spec))


def reconcile(t):
    """Pre-DDL data change by the real script; a later legacy resume does NOT undo it.

    The scoped baseline is journaled before the apply job, in the same
    invocation that re-proves the settled snapshot (DB and Redis). The outcome
    is accepted only as the exact authorized delta; the journaled
    ``reconciled`` snapshot is the one that was verified (never a re-read).
    """
    if t.reached('reconciled'):
        return
    t.critical_state('reconcile')
    spec = t.spec.get('reconcile')
    if not spec:
        if t.ops.duplicate_groups():
            t.refuse('duplicate-without-reconciliation', 'reconcile')
        t.j.append('done', step='reconcile', skipped=True)
        t.phase('reconciled')
        return
    argv, env, target, path = reconcile_command(t, spec)
    base = t.j.last('reconcile-baseline')
    if base is None:
        settled = t.baseline_snapshot()
        if settled != t.snapshot():
            t.refuse('writer-after-settle', 'reconcile')
        if t.j.last('done', 'reconcile:preview') is None:
            _, code, out = t.script('reconcile:preview', t.probe_name('reconcile-preview'), target, path, argv, env)
            lines = out.strip().splitlines()
            token = lines[-1].removeprefix('CONFIRMACAO=') if lines else ''
            if code != 0 or not lines[0].startswith('RESULTADO=PREVIA_OK') or not token.startswith('DESVINCULAR:'):
                t.refuse('reconcile-preview', 'reconcile:preview')
            t.j.append('done', step='reconcile:preview', token=token)
        current = scope(t)
        if canonical(current['tables']) != settled['db'] or canonical(t.ops.redis_snapshot()) != settled['redis']:
            t.refuse('writer-after-settle', 'reconcile')
        if current['target_pessoa'] != spec['pessoa'] or current['audit_op_total']:
            t.refuse('reconcile-precondition', 'reconcile')
        base = t.j.append('reconcile-baseline', redis=settled['redis'], **current)  # Redis of the SETTLED state
    if not t.done('reconcile:preview'):
        t.refuse('reconcile-preview-missing', 'reconcile')
    finish(t, base, create=True)
    t.phase('reconciled')


def finish(t, base, *, create):
    """Apply (or adopt) once, verify the exact delta, journal ``done`` once and the VERIFIED snapshot."""
    if journaled_snapshot(t, base):
        return True
    ids = t.ops.job_find(reconcile_job(t))
    if not create and (not ids or ((t.ops.inspect(ids[0]) or {}).get('State') or {}).get('Status') == 'created'):
        return False  # resume: never create nor start the apply; no effect happened
    adopted = bool(ids)
    result = apply_reconciliation(t, *reconcile_command(t, t.spec['reconcile']))
    t.checkpoint('reconcile:after-apply')  # committed by the job; not yet verified nor journaled
    verified = verify_reconciliation(t, base)
    if t.j.last('done', 'reconcile', base['seq']) is None:
        t.j.append('done', step='reconcile', result=result, recovered=adopted or not create)
    t.checkpoint('reconcile:after-done')
    t.j.append('snapshot', reason='reconciled', **verified)
    t.checkpoint('reconcile:after-snapshot')
    return True


def journaled_snapshot(t, base):
    return [e for e in t.j.find('snapshot', since=base['seq']) if e.get('reason') == 'reconciled']


def reconcile_command(t, spec):
    argv = []
    for flag in ('igreja', 'pessoa', 'manter', 'corrigir', 'admin_igreja', 'operador', 'operacao'):
        argv += ['--' + flag.replace('_', '-'), spec[flag]]
    argv += ['--release-sha', t.spec['candidate']['sha']]
    env = {'TEAM_PESSOA_RECONCILE_DATABASE_URL': t.dsn()}
    return argv, env, '/app/scripts/reconcile_team_pessoa.py', 'backend/scripts/reconcile_team_pessoa.py'


def reconcile_job(t):
    return f'{t.prefix}-job-reconcile-apply'


def apply_reconciliation(t, argv, env, target, path):
    """Fixed name: a replay adopts the same apply job (never a second application)."""
    token = t.j.last('done', 'reconcile:preview')['token']
    _, code, out = t.script('reconcile:apply', reconcile_job(t), target, path, [*argv, '--aplicar'], env,
                            stdin=token + '\n')
    result = (out.strip().splitlines() or [''])[0]
    if code != 0 or not re.match(r'RESULTADO=(APLICADA|JA_APLICADA) ', result):
        t.refuse('reconcile-apply', 'reconcile:apply')
    return result.split()[0].removeprefix('RESULTADO=')


def verify_reconciliation(t, base):
    """Exactly the authorized effect since the baseline; returns the snapshot of THAT verified read.

    One unlink (only ``pessoa_id`` of the corrected account) and exactly one
    audit row of this operation as the service writes it; nothing else in any
    table, persistent Redis unchanged from the settled state, no duplicate.
    """
    now = scope(t)
    touched = {'app_users', 'platform_audit_log'}
    if ({k: v for k, v in now['tables'].items() if k not in touched}
            != {k: v for k, v in base['tables'].items() if k not in touched}
            or now['app_users_others'] != base['app_users_others'] or now['target_row'] != base['target_row']
            or now['target_pessoa'] is not None or now['audit_others'] != base['audit_others']
            or now['audit_op_total'] != 1 or now['audit_op_exact'] != 1
            or canonical(t.ops.redis_snapshot()) != base['redis'] or t.ops.duplicate_groups()):
        t.refuse('reconcile-delta-mismatch', 'reconcile')
    return {'db': canonical(now['tables']), 'redis': base['redis']}


def recover_reconciliation(t):
    """For ``resume-legacy``: complete a committed apply (adopt, verify, verified snapshot); never create one."""
    base = t.j.last('reconcile-baseline')
    if t.spec.get('reconcile') and base is not None:
        finish(t, base, create=False)
