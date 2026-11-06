"""Local synthetic C2 port composition. No Docker/SSH/CLI or production driver.

Port observations/guards are trusted test inputs, never native attestations.
Private configuration and custody handles must never enter public receipts.
"""
from dataclasses import dataclass, field
import copy
import json
import re


class Refused(ValueError):
    pass


def need(ok):
    if not ok:
        raise Refused('c2-profile-refused')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode()


def checked_config(value):
    need(type(value) is dict and set(value) == {'Config', 'HostConfig', 'NetworkingConfig'})
    need(all(type(value[k]) is dict for k in value))
    need(len(encoded(value)) <= 1048576)
    return copy.deepcopy(value)


def replacement_config(value):
    """Only one identical canonical gate duplicate and the restart policy change."""
    result = checked_config(value)
    env = result['Config'].get('Env')
    need(type(env) is list and 1 <= len(env) <= 512)
    seen = {}
    for i, item in enumerate(env):
        need(type(item) is str and '=' in item and len(item.encode()) <= 65536
             and not any(c in item for c in '\x00\r\n'))
        name, val = item.split('=', 1)
        need(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', name))
        if name.upper() in {'ALLOW_REAL_SENDS', 'BREVO_SEND_MODE',
                            'BROADCAST_ASYNC_ENABLED', 'ASAAS_BILLING_ENABLED'}:
            need(name == name.upper())
            seen.setdefault(name, []).append((i, val))
    targets = seen.get('ALLOW_REAL_SENDS', [])
    need(len(targets) == 2 and targets[0][1] == targets[1][1]
         and targets[0][1].lower() in ('true', 'false'))
    need(all(len(v) == 1 for k, v in seen.items() if k != 'ALLOW_REAL_SENDS'))
    result['Config']['Env'] = [v for i, v in enumerate(env) if i != targets[1][0]]
    policy = result['HostConfig'].get('RestartPolicy')
    need(type(policy) is dict and set(policy) == {'Name', 'MaximumRetryCount'})
    need(policy['Name'] in ('always', 'unless-stopped', 'on-failure', 'no')
         and type(policy['MaximumRetryCount']) is int and policy['MaximumRetryCount'] >= 0)
    result['HostConfig']['RestartPolicy'] = {'Name': 'no', 'MaximumRetryCount': 0}
    return result


@dataclass(frozen=True, repr=False)
class Observation:
    container_id: str
    daemon_id: str
    image_id: str
    role: str
    running: bool
    status: str
    exit_code: int | None
    restart: str
    private_config: dict = field(repr=False)
    network_intent_sha256: str = field(repr=False)
    effective_network_verified: bool = False


@dataclass(repr=False)
class Attempt:
    """Caller-owned journal survives failures; never serialize opaque handles."""
    used: bool = False
    stage: str = 'not-started'
    intents: list = field(default_factory=list)
    confirmed: list = field(default_factory=list)
    private_original_handle: object = field(default=None, repr=False)
    private_replacement_handle: object = field(default=None, repr=False)
    replacement_id: str | None = field(default=None, repr=False)
    uncertain: bool = False


def profile(row):
    need(type(row) is Observation and re.fullmatch('[0-9a-f]{64}', row.container_id)
         and type(row.daemon_id) is str and bool(row.daemon_id)
         and re.fullmatch('sha256:[0-9a-f]{64}', row.image_id)
         and row.role == 'broadcast-worker' and type(row.running) is bool
         and type(row.effective_network_verified) is bool
         and re.fullmatch('[0-9a-f]{64}', row.network_intent_sha256))
    checked_config(row.private_config)
    need(row.private_config['HostConfig'].get('RestartPolicy', {}).get('Name') == row.restart)


def stopped(row):
    profile(row)
    need(row.running is False and row.status == 'exited'
         and type(row.exit_code) is int and row.exit_code == 0 and row.restart == 'no')


def run_synthetic(port, original, attempt):
    """No native driver is supplied. Failure stops; no rollback or automatic retry.

    The caller must retain Attempt after any exception, including BaseException.
    External durable journaling, deadline, exclusive ownership, approved scope,
    writable-layer recovery and native evidence remain future driver obligations.
    """
    claimed_this_call = False

    def step(stage, action):
        attempt.stage = stage
        port.guard()  # Must check baseline, ownership, schedule and freshness.
        attempt.intents.append(stage)
        attempt.uncertain = True
        value = action()
        attempt.confirmed.append(stage)
        attempt.uncertain = False
        return value

    try:
        need(type(attempt) is Attempt and attempt.used is False)
        attempt.used = True
        claimed_this_call = True
        need(port.synthetic_only is True)  # A test marker, not a security boundary.
        profile(original)
        need(original.running is True and original.status == 'running'
             and original.effective_network_verified is True)
        initial = checked_config(original.private_config)
        expected = replacement_config(initial)
        held_original = copy.deepcopy(initial)
        held_original['HostConfig']['RestartPolicy'] = {'Name': 'no', 'MaximumRetryCount': 0}
        policy = copy.deepcopy(initial['HostConfig']['RestartPolicy'])

        def observe_original(*, held, disabled=False):
            row = port.inspect(original.container_id)
            profile(row)
            need((row.container_id, row.daemon_id, row.image_id, row.role,
                  row.network_intent_sha256) ==
                 (original.container_id, original.daemon_id, original.image_id,
                  original.role, original.network_intent_sha256))
            need(encoded(row.private_config) == encoded(held_original if held or disabled else initial))
            if held:
                stopped(row)
            elif disabled:
                need(row.running is True and row.status == 'running' and row.restart == 'no')
            else:
                need(row == original)
            return row

        step('verify-original', lambda: observe_original(held=False))
        attempt.private_original_handle = step('save-private-original',
                                               lambda: port.save_private(original))
        need(attempt.private_original_handle is not None)
        step('disable-original-restart', lambda: port.set_restart_no(original.container_id))
        step('verify-original-restart-disabled', lambda: observe_original(held=False, disabled=True))
        step('signal-original-SIGTERM', lambda: port.signal_term(original.container_id))
        step('await-original-exit', lambda: port.await_exit(original.container_id))
        step('verify-original-held', lambda: observe_original(held=True))
        attempt.private_replacement_handle = step('reserve-replacement-identity', port.reserve_replacement)
        need(attempt.private_replacement_handle is not None)
        attempt.replacement_id = step('create-stopped', lambda: port.create_stopped(
            copy.deepcopy(expected), attempt.private_replacement_handle))
        need(type(attempt.replacement_id) is str
             and re.fullmatch('[0-9a-f]{64}', attempt.replacement_id)
             and attempt.replacement_id != original.container_id)

        def observe_replacement(*, running, restored_policy=False):
            row = port.inspect(attempt.replacement_id)
            profile(row)
            need(row.container_id == attempt.replacement_id
                 and row.daemon_id == original.daemon_id and row.image_id == original.image_id
                 and row.network_intent_sha256 == original.network_intent_sha256)
            config = copy.deepcopy(expected)
            if restored_policy:
                config['HostConfig']['RestartPolicy'] = policy
            need(encoded(row.private_config) == encoded(config))
            need(row.running is running and row.status == ('running' if running else 'created')
                 and row.restart == (policy['Name'] if restored_policy else 'no'))
            if running:
                need(row.effective_network_verified is True)
            return row

        step('verify-replacement-created', lambda: observe_replacement(running=False))
        step('verify-original-before-start', lambda: observe_original(held=True))
        step('start-only-replacement', lambda: port.start(attempt.replacement_id))
        step('verify-replacement-running', lambda: observe_replacement(running=True))
        step('check-health', lambda: need(port.check_health(attempt.replacement_id) is True))
        step('verify-original-before-policy', lambda: observe_original(held=True))
        step('verify-replacement-before-policy', lambda: observe_replacement(running=True))
        step('restore-replacement-policy', lambda: port.set_policy(attempt.replacement_id, copy.deepcopy(policy)))
        step('verify-replacement-policy', lambda: observe_replacement(running=True, restored_policy=True))
        step('publish-inventory', lambda: port.publish_inventory(original.container_id, attempt.replacement_id))
        return {'outcome': 'synthetic-composition-passed', 'production_ready': False,
                'native_evidence_verified': False, 'original_removed': False}
    except BaseException as exc:
        if claimed_this_call and attempt.intents:
            attempt.uncertain = True
        if isinstance(exc, Exception):
            raise Refused('c2-composition-refused') from None
        raise
