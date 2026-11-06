"""Explicit schema-2 origin preflight; metadata consistency, never A8 authority.

No provider discovery, credential read, source connection or capture is exposed.
The full R16 plan is required to bind the controller's identity and V1 baseline.
The capture scope excludes A8. The CLI refuses this profile without a separately
reviewed fresh-window recovery implementation; trusted Python composition can
bind its independent native ports through window_context. No legacy fallback.
"""
import json
import math
import os
from pathlib import Path
import stat

import first_transition_capture_contract as capture
import first_transition_auth_preflight as authenticated
from first_transition_adapter import digest
from initial_transition_files import no_symlink
from initial_transition_ops import Refused, require

PLAN_SCHEMA = 'igreja12.r16.real-origin-capture-plan/1'
PLAN_FIELDS = frozenset(('schema', 'capture', 'baseline_v1_digest',
                         'baseline_ledger_names', 'safety_preflight', 'execution_request_digest'))
SAFETY_FIELDS = frozenset(('evidence_sha256', 'source_identity_sha256', 'observed_at',
                           'logging_none', 'preload_empty'))
BASELINE_NAMES_SHA = 'd66425d621c06f04adcad3f6155878012ba1c585080c0801319a5684fc87e695'


def bind_authenticated_preflight(request, report, *, expected, controller_plan_digest, now):
    """Independent authenticated-preflight metadata, never a capture/window receipt."""
    try:
        require(type(request) is dict and request.get('controller_plan_digest') == controller_plan_digest and
                request.get('source_identity_sha256') == expected.identity and
                request.get('baseline_v1_digest') == expected.baseline_digest and
                request.get('expected_ledger_names') == list(expected.ledger), 'window-source-auth-binding')
        result = authenticated.assess(request, report, now=now)
        return {**result, **{key: request[key] for key in (
            'source_descriptor_sha256', 'endpoint_identity_sha256', 'ca_sha256',
            'code_bundle_sha256', 'startup_profile', 'expected_server_version_num')}}
    except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
        raise Refused('window-source-auth-binding') from None


def selection(args):
    values = tuple(getattr(args, k, None) for k in
                   ('origin_contract', 'origin_plan', 'origin_observation'))
    if all(v is None for v in values):
        require(args.mode != 'check-origin', 'window-origin-arguments')
        return False
    require(all(type(v) is str and v for v in values), 'window-origin-arguments')
    require(values[0] == '2', 'window-origin-version')
    require(args.mode in ('prepare', 'check-origin', 'run'), 'window-origin-mode')
    return True


def read_metadata(path):
    """Bounded explicit JSON only, including nonblocking refusal of FIFOs/devices."""
    try:
        require(type(path) is str and os.path.isabs(path) and '\x00' not in path,
                'window-origin-metadata')
        resolved = no_symlink(Path(path))
        fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_size <= 131072, 'window-origin-metadata')
            raw = handle.read(131073)
        require(len(raw) <= 131072, 'window-origin-metadata')

        def pairs(items):
            result = {}
            for key, value in items:
                require(key not in result, 'window-origin-metadata')
                result[key] = value
            return result

        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (OSError, ValueError, TypeError, UnicodeError, Refused):
        raise Refused('window-origin-metadata') from None


def assess(plan, observation, *, expected, daemon_id, now):
    """Only a consistency gate. Caller declarations do not authenticate the source."""
    try:
        require(type(plan) is dict and set(plan) == PLAN_FIELDS and
                plan['schema'] == PLAN_SCHEMA, 'window-origin-binding')
        cap = plan['capture']
        result = capture.assess_capture(cap, observation, now=now)
        safety = plan['safety_preflight']
        # R16's complete ledger list is outside the bounded capture contract.
        require(type(plan['baseline_ledger_names']) is list and
                plan['baseline_ledger_names'] == list(expected.ledger) and
                len(plan['baseline_ledger_names']) == 78 and
                digest(plan['baseline_ledger_names']) == BASELINE_NAMES_SHA and
                plan['baseline_v1_digest'] == expected.baseline_digest,
                'window-origin-binding')
        require(cap['expected_source']['identity_sha256'] == expected.identity and
                cap['daemon'] == daemon_id and
                type(plan['execution_request_digest']) is str and
                plan['execution_request_digest'] == digest({k: v for k, v in plan.items()
                                                           if k != 'execution_request_digest'}) and
                observation['capture_id'] == plan['execution_request_digest'], 'window-origin-binding')
        require(type(safety) is dict and set(safety) == SAFETY_FIELDS and
                capture._hex(safety['evidence_sha256']) and
                safety['source_identity_sha256'] == expected.identity and
                safety['logging_none'] is True and safety['preload_empty'] is True and
                type(safety['observed_at']) in (int, float) and math.isfinite(safety['observed_at']) and
                safety['observed_at'] == observation['source_observation']['observed_at'],
                'window-origin-binding')
    except (capture.Refused, KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise Refused('window-origin-binding') from None
    return dict(schema='igreja12.controller-origin-preflight/2', contract_version=2,
                origin_plan_digest=digest(plan), capture_plan_digest=result['plan_digest'],
                capture_observation_digest=result['observation_digest'],
                source_identity_sha256=expected.identity, baseline_digest=expected.baseline_digest,
                provider_descriptor_sha256=cap['expected_source']['descriptor_sha256'],
                endpoint_identity_sha256=cap['tls_policy']['endpoint_identity_sha256'],
                ca_sha256=cap['tls_policy']['ca_sha256'],
                protocol_pins=dict(cap['protocol_pins']),
                metadata_consistent=True, origin_authenticated=False, artifact_bytes_verified=False,
                provider_opened=False, execution_authorized=False, a8_window_proven=False,
                receipt_emitted=False, production_ready=False)


def window_context(record):
    """Public binding for a trusted window provider; never evidence of capture.

    The provider must independently pin this context. Neither these hashes nor
    the preflight JSON establish provenance or authorize an operation.
    """
    selected = [key for key in ('origin_preflight', 'source_auth_preflight') if key in record]
    require(len(selected) == 1, 'window-origin-capability-binding')
    key = selected[0]
    profile = record[key]
    source = key == 'source_auth_preflight'
    try:
        context = dict(
            schema='igreja12.window-origin-context/1', profile=key,
            profile_digest=digest(profile), window_digest=digest(record),
            plan_digest=record['plan_digest'], config_digest=record['transition_digest'],
            backup_config_digest=record['backup_digest'],
            source_identity=profile['source_identity_sha256'],
            baseline_digest=profile['baseline_v1_digest' if source else 'baseline_digest'],
            provider_descriptor_sha256=profile['source_descriptor_sha256' if source
                                               else 'provider_descriptor_sha256'],
            endpoint_identity_sha256=profile['endpoint_identity_sha256'], ca_sha256=profile['ca_sha256'],
            protocol_pins=({'code_bundle_sha256': profile['code_bundle_sha256']} if source
                           else dict(profile['protocol_pins'])),
            startup_profile=profile['startup_profile'] if source else 'origin-schema-2',
        )
        require(all(type(value) is str and capture._hex(value) for name, value in context.items()
                    if name not in ('schema', 'profile', 'protocol_pins', 'startup_profile'))
                and context['protocol_pins'] and all(capture._hex(value)
                    for value in context['protocol_pins'].values()), 'window-origin-capability-binding')
        return context
    except (KeyError, TypeError, ValueError):
        raise Refused('window-origin-capability-binding') from None
