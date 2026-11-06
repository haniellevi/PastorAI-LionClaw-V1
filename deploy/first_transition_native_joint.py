"""Synthetic-only native holder/dump/HTTPS/custody integration.

Nominal endpoints are refused BEFORE the SQL provider opens. There is no real
window authority implementation: fixture WindowEvidence is deliberately NOT
writer containment. The operational factory remains closed. This composition
preserves the reviewed collector/HTTP contracts without promoting their flags.
Bodies are hashed and discarded; the SQL projection is retained, never replayed.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import ipaddress
from pathlib import Path
import re
import ssl
import time

from first_transition_adapter import adapter_sources, digest
from first_transition_native_http_hook import A8HTTPHook
from first_transition_native_http_reader import Endpoint, endpoint_profile, environment, tls_profile
from first_transition_native_joint_capture import WindowEvidence, finite
from first_transition_window_backup import NativeSourceSnapshot
from initial_transition_ops import Refused, require

CODE = 'native-joint-synthetic-binding'
VENDORED = {
    'first_transition_native_joint_capture.py': 'ef30cf37351a0fcb0ef70b91640a163dd7cbb74344d63e44bbff665269c9abaf',
    'first_transition_native_http_reader.py': '7ed54a1c5b0d3d2106292397512de099d33b697e20abf8590e2ad140657bc569',
    # Only the two import module names differ from the reviewed hook.
    'first_transition_native_http_hook.py': '91744da84db896268a2374fa70cf00f008a84b3c9b7364e59c1e15f20803d796',
}


@dataclass(frozen=True)
class NativeJointPins:
    request_sha256: str
    context_sha256: str
    source_policy_sha256: str
    http_policy_sha256: str
    runtime_sha256: str


def http_policy(endpoint, ca_der, preserved_objects):
    """Public descriptor for independent fixture pins; no token or object names."""
    require(type(endpoint) is Endpoint and type(ca_der) is tuple and 0 < len(ca_der) <= 16
            and all(type(value) is bytes and 0 < len(value) <= 65536 for value in ca_der), CODE)
    return dict(endpoint=asdict(endpoint), ca_sha256=sorted(hashlib.sha256(c).hexdigest() for c in ca_der),
                preserved_sha256=digest(preserved_objects), tls_minimum='TLSv1.2',
                check_hostname=True, verify_mode='CERT_REQUIRED', profile='synthetic-only')


class NativeSyntheticJointCapture:
    """An explicit fixture seam, unavailable to CLI and OriginWindowPorts.

    Numeric loopback HTTPS and source fixture aliases are mandatory. The guard
    is a fixture dependency, never authoritative evidence accepted for A8.
    TLS trust is copied before the holder into a newly owned context; no caller
    context can be weakened afterward. Every checkpoint rechecks its policy.
    """
    def __init__(self, *, root, endpoint, ca_der, preserved_objects, token, guard, pins, owner=0):
        require(type(pins) is NativeJointPins and all(type(v) is str and re.fullmatch('[0-9a-f]{64}', v)
                for v in asdict(pins).values()) and callable(guard)
                and type(owner) is int and owner >= 0, CODE)
        endpoint_profile(endpoint)
        require(endpoint.profile == 'synthetic', 'native-joint-authoritative-fence-missing')
        environment()
        self._policy = http_policy(endpoint, ca_der, preserved_objects)
        require(digest(self._policy) == pins.http_policy_sha256, CODE)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_verify_locations(cadata=''.join(ssl.DER_cert_to_PEM_cert(c) for c in ca_der))
        tls_profile(context)
        self._context, self._tls = context, self._tls_pin(context)
        self._root, self._owner, self._pins = root, owner, pins
        self._endpoint, self._guard = endpoint, guard
        self._preserved, self._token = deepcopy(preserved_objects), token
        self._ready = self._captured = False
        self._hook = None

    def __repr__(self):
        return 'NativeSyntheticJointCapture(private fixture configuration)'

    @staticmethod
    def _tls_pin(context):
        tls_profile(context)
        return digest(dict(ca=sorted(hashlib.sha256(c).hexdigest() for c in context.get_ca_certs(binary_form=True)),
            minimum=int(context.minimum_version),maximum=int(context.maximum_version),options=int(context.options),
            flags=int(context.verify_flags),ciphers=context.get_ciphers()))

    def _check(self):
        environment()
        require(self._tls_pin(self._context) == self._tls, CODE)
        directory = Path(__file__).resolve().parent
        require(all(hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected
                    for name,expected in VENDORED.items()), CODE)

    def preflight(self, *, request, context, policy, plan):
        require(not self._ready and not self._captured, CODE)
        self._check()
        require(digest(request) == self._pins.request_sha256 and digest(context) == self._pins.context_sha256
                and digest(asdict(policy)) == self._pins.source_policy_sha256
                and digest(dict(plan.adapter_sources)) == self._pins.runtime_sha256
                and adapter_sources() == plan.adapter_sources
                and policy.host.endswith(('.synthetic.invalid','.example.test'))
                and (ipaddress.ip_address(policy.hostaddr).is_loopback
                     or any(ipaddress.ip_address(policy.hostaddr) in ipaddress.ip_network(network)
                            for network in ('192.0.2.0/24','198.51.100.0/24','203.0.113.0/24')))
                and context['source_identity'] == request['source_identity'], CODE)
        self._request, self._source = digest(request), request['source_identity']
        self._window = request['quiescence_digest']
        self._hook = A8HTTPHook(request_sha256=self._request,source_sha256=self._source,
            window_sha256=self._window,preserved_objects=self._preserved,token=self._token,
            endpoint=self._endpoint,context=self._context,guard=self._checkpoint_guard,
            state_reader=lambda holder:holder.state())
        self._token = None
        self._ready = True

    def _checkpoint_guard(self, request, source, window, started, deadline):
        self._check()
        value = self._guard(request,source,window,started,deadline)
        require(type(value) is WindowEvidence and value.allowed is True
                and (value.request_sha256,value.source_sha256,value.window_sha256)
                == (self._request,self._source,self._window), CODE)
        return value

    def custody(self):
        from first_transition_native_joint_artifacts import NativeJointArtifacts
        require(self._ready and not self._captured, CODE)
        return NativeJointArtifacts(self._root,self._request,owner=self._owner)

    def capture(self, *, snapshot, dumper, dump, artifacts, deadline, capture_started_at):
        from first_transition_native_job import NativeDump
        from first_transition_native_joint_artifacts import NativeJointArtifacts
        require(self._ready and not self._captured and type(snapshot) is NativeSourceSnapshot
                and type(dumper) is NativeDump and type(artifacts) is NativeJointArtifacts
                and artifacts.request_digest == self._request and artifacts.root == self._root
                and artifacts.owner == self._owner, CODE)
        self._captured = True
        try:
            self._check()
            pulse = dumper.keepalive(snapshot)  # same object/last observation; no reset
            token = snapshot.snapshot_id()
            require(token == dump['snapshot_id'] and time.monotonic() < deadline, CODE)
            def checkpoint():
                require(time.monotonic() < deadline, CODE)
                pulse()
                value = self._checkpoint_guard(self._request,self._source,self._window,capture_started_at,deadline)
                require(finite(value.interval_started_at) and finite(value.valid_until)
                        and value.interval_started_at <= capture_started_at <= time.time() < value.valid_until
                        and time.monotonic() < deadline, CODE)
                pulse()
            with snapshot.holder_cursor() as holder:
                private,aggregate = self._hook(holder=holder,source_identity_sha256=self._source,
                    snapshot=dict(exported_id=token,holder=holder.state()),
                    dump=dict(exit_code=0,imported_snapshot=token,sha256=dump['sha256'],bytes=dump['size']),
                    pulse=pulse,deadline=deadline,capture_started_at=capture_started_at)
                metadata = artifacts.capture_material(projection=private.sql_projection,manifest=private.manifest,
                    manifest_sha256=private.manifest_sha256,
                    expected_binding=dict(request_sha256=self._request,source_sha256=self._source,
                        window_sha256=self._window,snapshot_token=token,dump_sha256=dump['sha256']),
                    timeout=min(10,snapshot._remaining(),deadline-time.monotonic()),pulse=checkpoint)
                checkpoint()
                require(snapshot.snapshot_id() == token and self._tls_pin(self._context) == self._tls, CODE)
            return dict(schema='igreja12.native-synthetic-joint/1',artifacts=metadata,aggregates=aggregate,
                policy_sha256=self._pins.http_policy_sha256,runtime_sha256=self._pins.runtime_sha256,
                maximum_pulse_gap_s=pulse.maximum,pulse_calls=pulse.calls,fixture_scope_only=True,
                source_unchanged_proven=False,authoritative_fence_verified=False,
                storage_body_retention_verified=False,storage_recovery_verified=False,
                a8_window_proven=False,operational_ready=False)
        except Exception:
            raise Refused('native-joint-capture-failed') from None
