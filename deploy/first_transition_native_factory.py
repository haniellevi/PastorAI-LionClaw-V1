"""Explicit, currently blocked native-port admission. No CLI or native IO.

NativeWindowJob proves only its own capture/recovery scope. It does not admit
the controller's other URI consumers or produce OriginWindowBackup evidence.
This factory binds reviewed inputs and exposes those gaps; none of its ports
can log in, execute a job, or emit a receipt while the gaps remain.
"""
from copy import deepcopy
from dataclasses import asdict
import re

from first_transition_adapter import APPLICATION_SHA, EXECUTOR_SHA, Plan, digest
from first_transition_database import DatabaseExpectation
from first_transition_host_driver import _absolute
from first_transition_native_job import NativeDumpSpec, NativeJobPins
from first_transition_window_backup import NativeSourcePolicy, OriginWindowPorts, WindowBackupConfig
from initial_transition_ops import Refused, require

CONFIG_CODE = 'window-origin-native-factory-binding'
BLOCKED_CODE = 'window-origin-native-admission-incomplete'
HEX = re.compile('[0-9a-f]{64}')
CONTEXT_FIELDS = frozenset((
    'schema', 'profile', 'profile_digest', 'window_digest', 'plan_digest', 'config_digest',
    'backup_config_digest', 'source_identity', 'baseline_digest', 'provider_descriptor_sha256',
    'endpoint_identity_sha256', 'ca_sha256', 'protocol_pins', 'startup_profile',
))
CAPTURE_PINS = frozenset((
    'v1_reader_sha256', 'v2_reader_sha256', 'v3_reader_sha256', 'dump_runner_sha256',
    'provider_adapter_sha256', 'runtime_bundle_sha256',
))
BLOCKERS = (
    ('source_migrations', 'source-migration-transport-unbound'),
    ('candidate', 'candidate-transports-unbound'),
    ('writers', 'writer-endpoint-unbound'),
    ('observer', 'observer-timeout-adapter-unbound'),
    ('receipt', 'source-unchanged-unproven'),
    ('receipt', 'phase-timing-unbound'),
    ('receipt', 'job-result-not-origin-receipt'),
    ('recovery', 'managed-global-recovery-incomplete'),
    ('supervisor', 'parent-daemon-cleanup-unbound'),
)


def _hex(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def _context(value):
    require(type(value) is dict and set(value) == CONTEXT_FIELDS
            and value['schema'] == 'igreja12.window-origin-context/1'
            and value['profile'] in ('origin_preflight', 'source_auth_preflight'), CONFIG_CODE)
    source = value['profile'] == 'source_auth_preflight'
    require(value['startup_profile'] == ('supabase-17.6.1.127' if source else 'origin-schema-2')
            and all(_hex(value[key]) for key in CONTEXT_FIELDS - {
                'schema', 'profile', 'startup_profile', 'protocol_pins'})
            and type(value['protocol_pins']) is dict
            and set(value['protocol_pins']) == ({'code_bundle_sha256'} if source else CAPTURE_PINS)
            and all(_hex(pin) for pin in value['protocol_pins'].values()), CONFIG_CODE)


class NativeWindowFactory:
    """Bind inputs without opening providers; admission remains unconditional NO-GO.

    ``config`` is the backup configuration. ``pins`` come from independent
    review, not from caller declarations of capabilities or successful tests.
    There is deliberately no runner, job-result input, bypass or enable flag.
    The diagnostic's hashes are typo/provenance bindings, never authorization.
    """
    def __init__(self, *, config, plan, expected, context, policy, dump_spec, pins, transports=None):
        try:
            require(type(config) is WindowBackupConfig and isinstance(plan, Plan)
                    and isinstance(expected, DatabaseExpectation) and type(policy) is NativeSourcePolicy
                    and type(dump_spec) is NativeDumpSpec and type(pins) is NativeJobPins, CONFIG_CODE)
            _context(context)
            config.validated()
            policy.validated()
            expected.validated()
            require(plan.application_sha == APPLICATION_SHA and plan.executor_sha == EXECUTOR_SHA
                    and expected.ledger == plan.baseline
                    and _absolute(dump_spec.binary) and _hex(dump_spec.sha256)
                    and type(dump_spec.owner) is int and dump_spec.owner >= 0
                    and all(_hex(value) for value in asdict(pins).values())
                    and pins.context_sha256 == digest(context)
                    and pins.source_policy_sha256 == digest(asdict(policy))
                    and pins.dump_spec_sha256 == digest(asdict(dump_spec))
                    and context['plan_digest'] == plan.digest
                    and context['source_identity'] == expected.identity
                    and context['baseline_digest'] == expected.baseline_digest
                    and context['backup_config_digest'] == digest(asdict(config))
                    and context['ca_sha256'] == policy.ca_sha256, CONFIG_CODE)
            self._context = deepcopy(context)
            self._pins = pins
            self._plan_digest = plan.digest
            self._backup_digest = digest(asdict(config))
            self._baseline_digest = expected.baseline_digest
            if transports is not None:
                from first_transition_native_transports import NativeSourceTransports
                require(type(transports) is NativeSourceTransports and transports.plan == plan
                    and transports.expected == expected and transports.policy == policy, CONFIG_CODE)
                transports.validate(context)
            self._ports = OriginWindowPorts(pins.context_sha256, self.admit, self.connect, self.backup,transports)
        except Exception:
            raise Refused(CONFIG_CODE) from None

    @property
    def ports(self):
        """A bound port set, whose admission and execution callbacks all refuse."""
        return self._ports

    def diagnostics(self):
        """Public immutable-by-copy status; no URI, hostname, path or payload."""
        return dict(
            schema='igreja12.native-window-admission/1', status='blocked',
            context_digest=self._pins.context_sha256, plan_digest=self._plan_digest,
            backup_config_digest=self._backup_digest,
            source_policy_sha256=self._pins.source_policy_sha256,
            dump_spec_sha256=self._pins.dump_spec_sha256,
            implementations=dict(observer='native-reader-only', dump='native-job-only',
                source_consumers='native-transports-unadmitted' if self._ports.consumers is not None else 'unbound'),
            blockers=[dict(component=component, code=code) for component, code in BLOCKERS],
            admission_granted=False, provider_opened=False, job_executed=False,
            receipt_emitted=False, execution_authorized=False, operational_ready=False,
            a8_window_proven=False,
        )

    def _bound(self, context):
        try:
            _context(context)
            require(digest(context) == self._pins.context_sha256, CONFIG_CODE)
        except Exception:
            raise Refused(CONFIG_CODE) from None

    def admit(self, *, secret, context):
        """Refuse before invoking secret or doing any login/host/journal IO."""
        self._bound(context)
        raise Refused(BLOCKED_CODE)

    def connect(self, *, secret, context, timeout):
        """A direct call cannot bypass the rejected full-controller admission."""
        self._bound(context)
        raise Refused(BLOCKED_CODE)

    def backup(self, request, *, context, secret, connect, config, plan, expected):
        """Never execute NativeWindowJob or reinterpret its result as a receipt."""
        self._bound(context)
        try:
            require(type(config) is WindowBackupConfig and isinstance(plan, Plan)
                    and isinstance(expected, DatabaseExpectation)
                    and digest(asdict(config)) == self._backup_digest
                    and plan.digest == self._plan_digest
                    and expected.baseline_digest == self._baseline_digest
                    and expected.identity == self._context['source_identity'], CONFIG_CODE)
        except Exception:
            raise Refused(CONFIG_CODE) from None
        raise Refused(BLOCKED_CODE)
