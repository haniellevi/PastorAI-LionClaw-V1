"""Observed stages of the synthetic C2/capture dispatch; never an A8 receipt.

The dispatcher calls the real, bound lifecycle and supervisor. These gates only
validate their issued outcomes and observe local stage times. No callback is
invoked for host/source effects, no child event is invented, and no caller JSON
can authorize DDL or replace the missing SQL/API/Storage fence. Python binding
checks detect accidental mutation, not malicious arbitrary code in this process.
"""
from copy import deepcopy
from dataclasses import asdict,dataclass
import hashlib
from pathlib import Path
import re
import time

from first_transition_adapter import Plan,digest
from first_transition_c2_lifecycle import ContainmentSession,RESULT as C2_RESULT
from first_transition_host_driver import HostManifest
from first_transition_native_events import NativeWindowEvents
from first_transition_native_supervision import NativeCleanupObservation,NativeSupervisedWindow
from first_transition_orchestrator import BACKUP_REQUEST_SCHEMA
from first_transition_window_backup import WINDOW_REQUEST_FIELDS
from initial_transition_files import read_regular
from initial_transition_ops import Refused,require

SCHEMA='igreja12.native-dispatch-stages/1'
CODE='native-dispatch-gates-refused'
PHASES=('request-admitted','c2-start','c2-held','capture-start','capture-validated','cleanup-validated','result')
HEX=re.compile(r'[0-9a-f]{64}\Z')


def _hex(value):return type(value) is str and HEX.fullmatch(value) is not None
def _method(value):return getattr(value,'__func__',None)


def _cleanup_type():
    try:
        from first_transition_native_cleanup import NativeDockerCleanup
        return NativeDockerCleanup
    except ModuleNotFoundError:
        return None


@dataclass(frozen=True)
class NativeDispatchPins:
    request_sha256: str
    context_sha256: str
    plan_sha256: str
    runtime_sha256: str
    manifest_sha256: str
    source_identity: str


class NativeDispatchGates:
    """Single sequence; bindings, phase order and clock failure latch closed.

    The NativeWindowEvents observation component supplies the existing monotonic
    1200s/clock rollback/drift2s checks. Its internal request observation starts
    this budget; the seven events here are observations of THIS dispatcher.
    Generic cleanup remains association-only. A concrete cleanup's own issued
    evidence can attest its narrow Docker absence check, never fence authority.
    """
    def __init__(self,request,context,plan,manifest,pins,*,c2_session,supervisor,runtime_sources,
                 clock=None,wall_clock=None):
        try:
            require(type(pins) is NativeDispatchPins and all(_hex(v) for v in asdict(pins).values())
                    and type(plan) is Plan and type(manifest) is HostManifest
                    and type(c2_session) is ContainmentSession and type(supervisor) is NativeSupervisedWindow
                    and type(request) is dict and set(request)==WINDOW_REQUEST_FIELDS
                    and request['schema']==BACKUP_REQUEST_SCHEMA
                    and all(_hex(v) for k,v in request.items() if k!='schema')
                    and type(context) is dict and callable(runtime_sources),CODE)
            self.request,self.context,self.plan,self.manifest,self.pins=request,context,plan,manifest,pins
            self.c2_session,self.supervisor,self.runtime_sources=c2_session,supervisor,runtime_sources
            self.clock,self.wall_clock=clock or time.monotonic,wall_clock or time.time
            self._timing=NativeWindowEvents(pins.request_sha256,pins.context_sha256,
                clock=self.clock,wall_clock=self.wall_clock)
            self._timing_binding,self._received=self._timing,self._timing._first
            self._refs=(request,context,plan,manifest,pins,c2_session,supervisor,runtime_sources,self.clock,self.wall_clock)
            self._pins=asdict(pins)
            self._methods=(_method(c2_session.run),_method(supervisor.run),_method(supervisor.validate_report))
            self._cleanup=supervisor.cleanup
            concrete=type(self._cleanup) is _cleanup_type()
            self._cleanup_registry=self._cleanup.registry if concrete else None
            self._registry_digest=self._cleanup_registry.digest if concrete else None
            self._cleanup_validator=_method(self._cleanup.validate_observation) if concrete else None
            self._supervisor_config=digest([asdict(supervisor.pins),supervisor.argv,supervisor.timeout,supervisor.cleanup_budget])
            self._admission=deepcopy(c2_session.guard.admission)
            self._target=dict(manifest.service_ids)['broadcast-worker']
            self._events=[];self._failed=False
            self._c2_result=self._capture_result=None
            self._c2_digest=self._capture_digest=self._cleanup_digest=self._daemon_evidence_digest=None
            self._daemon_cleanup_verified=False
            require(c2_session.used is False and c2_session.stage=='not-started' and c2_session.uncertain is False
                    and supervisor.used is False and supervisor.diagnostics()['status']=='not-started',CODE)
            self._advance('request-admitted')
        except Exception:
            self._failed=True
            raise Refused(CODE) from None
        except BaseException:
            self._failed=True
            raise KeyboardInterrupt from None

    def _check(self):
        values=(self.request,self.context,self.plan,self.manifest,self.pins,self.c2_session,self.supervisor,
                self.runtime_sources,self.clock,self.wall_clock)
        require(not self._failed and all(a is b for a,b in zip(values,self._refs))
                and self._timing is self._timing_binding and self._timing._first==self._received
                and self._timing._clock is self.clock and self._timing._wall is self.wall_clock
                and self._timing._request==self.pins.request_sha256 and self._timing._context==self.pins.context_sha256
                and asdict(self.pins)==self._pins and digest(self.request)==self.pins.request_sha256
                and digest(self.context)==self.pins.context_sha256 and self.plan.digest==self.pins.plan_sha256
                and self.request['plan_digest']==self.context['plan_digest']==self.plan.digest
                and self.request['source_identity']==self.context['source_identity']==self.pins.source_identity
                and self.request['baseline_digest']==self.context['baseline_digest']
                and self.request['config_digest']==self.context['config_digest']
                and self.manifest.validated().digest==self.pins.manifest_sha256,CODE)
        c,s=self.c2_session,self.supervisor
        c._bound()  # Pure primitive binding checks; never acquire/observe/effect.
        require(type(c) is ContainmentSession and type(s) is NativeSupervisedWindow
                and c.manifest.validated()==self.manifest and c.clock is self.clock
                and c.guard.admission==self._admission
                and self._admission.scope==self.manifest.digest and self._admission.target_id==self._target
                and self._admission.request_digest==self.pins.request_sha256
                and self._admission.nonce==self.request['nonce']
                and c.guard.expected.identity==self.pins.source_identity
                and c.guard.expected.ledger==self.plan.baseline
                and c.guard.expected.baseline_digest==self.request['baseline_digest']
                and s.plan is self.plan and s.clock is self.clock and s.wall_clock is self.wall_clock
                and s.runtime_sources is self.runtime_sources and s.cleanup is self._cleanup
                and s.pins.request_sha256==self.pins.request_sha256
                and s.pins.context_sha256==self.pins.context_sha256 and s.pins.runtime_sha256==self.pins.runtime_sha256
                and digest([asdict(s.pins),s.argv,s.timeout,s.cleanup_budget])==self._supervisor_config
                and (_method(c.run),_method(s.run),_method(s.validate_report))==self._methods,CODE)
        if type(self._cleanup) is _cleanup_type():
            registry=self._cleanup.registry
            protected={self.manifest.network_id,*dict(self.manifest.service_ids).values(),
                       *dict(self.manifest.support_ids).values()}
            owned={v.container_id for v in registry.containers}
            if registry.network_id is not None:owned.add(registry.network_id)
            require(registry is self._cleanup_registry and registry.digest==self._registry_digest
                    and registry.request_digest==self.pins.request_sha256
                    and registry.context_digest==self.pins.context_sha256 and not owned&protected
                    and self._cleanup.clock is self.clock and self._cleanup.wall_clock is self.wall_clock
                    and _method(self._cleanup.validate_observation)==self._cleanup_validator,CODE)
        sources=self.runtime_sources()
        require(type(sources) is tuple and sources==self.plan.adapter_sources
                and len(dict(sources))==len(sources) and digest(dict(sources))==self.pins.runtime_sha256,CODE)
        directory=Path(__file__).resolve().parent
        require(all(type(name) is str and re.fullmatch('[A-Za-z0-9_]+\\.py',name) and _hex(pin)
                    and hashlib.sha256(read_regular(directory/name,2097152)).hexdigest()==pin for name,pin in sources),CODE)
        if self._c2_result is not None:require(digest(self._c2_result)==self._c2_digest,CODE)
        if self._capture_result is not None:
            require(digest(self._capture_result)==self._capture_digest,CODE)
            s.validate_report(self._capture_result)

    def _advance(self,phase,validate=None):
        try:
            require(not self._failed and len(self._events)<len(PHASES) and PHASES[len(self._events)]==phase,CODE)
            self._check()
            if validate is not None:validate()
            self._check()
            wall,elapsed=self._timing._observe()
            stages={v['phase']:v['elapsed_s'] for v in self._events}
            if phase=='c2-start':require(elapsed-stages['request-admitted']<=60,CODE)
            if phase=='c2-held':require(elapsed-stages['c2-start']<=60,CODE)
            if phase=='capture-start':require(elapsed-stages['c2-held']<=60,CODE)
            if phase=='cleanup-validated':require(elapsed-stages['capture-validated']<=60,CODE)
            if phase=='result':require(elapsed-stages['cleanup-validated']<=60,CODE)
            self._events.append(dict(sequence=len(self._events),phase=phase,wall_at=wall,elapsed_s=elapsed))
        except Exception:
            self._failed=True
            raise Refused(CODE) from None
        except BaseException:
            self._failed=True
            raise KeyboardInterrupt from None

    def remaining_s(self):
        try:
            self._check()
            _,elapsed=self._timing._observe()
            require(1200-elapsed>0,CODE)
            return 1200-elapsed
        except Exception:
            self._failed=True
            raise Refused(CODE) from None
        except BaseException:
            self._failed=True
            raise KeyboardInterrupt from None

    def c2_start(self):
        def validate():
            require(self.c2_session.used is False and self.c2_session.stage=='not-started'
                    and self.c2_session.uncertain is False,CODE)
        self._advance('c2-start',validate)

    def c2_held(self,result,scope,target,nonce):
        def validate():
            require(type(result) is dict and set(result)==set(C2_RESULT)|{'lease_released'}
                    and result['status']=='broadcast-held' and result['lease_released'] is True
                    and all(result[k] is False for k in C2_RESULT if k!='status')
                    and self.c2_session.used is True and self.c2_session.stage=='held'
                    and self.c2_session.uncertain is False
                    and scope==self.manifest.digest and target==self._target and nonce==self.request['nonce']
                    and self.c2_session.guard.root is None and self.c2_session.guard.lease is None,CODE)
            self._c2_result,self._c2_digest=result,digest(result)
        self._advance('c2-held',validate)

    def capture_start(self):
        def validate():
            require(self.supervisor.used is False and self.supervisor.diagnostics()['status']=='not-started'
                    and self.supervisor.timeout<=self.remaining_s(),CODE)
        self._advance('capture-start',validate)

    def capture_validated(self,supervised_result):
        def validate():
            validated=self.supervisor.validate_report(supervised_result)
            require(type(validated) is dict and validated==supervised_result
                    and validated['runtime_sha256']==self.pins.runtime_sha256
                    and validated['worker_reaped'] is True and validated['daemon_cleanup_authoritative'] is False
                    and validated['source_unchanged_proven'] is validated['a8_window_proven']
                    is validated['operational_ready'] is False,CODE)
            self._capture_result,self._capture_digest=supervised_result,digest(supervised_result)
        self._advance('capture-validated',validate)

    def cleanup_validated(self,observation):
        def validate():
            require(type(observation) is NativeCleanupObservation
                    and asdict(observation)==self._capture_result['cleanup_observation'],CODE)
            self._cleanup_digest=digest(asdict(observation))
            # Lazy dependency avoids a cycle with the supervisor/dispatcher.
            # Validate the ORIGINAL issued observation, never a reconstructed copy.
            if type(self._cleanup) is _cleanup_type():
                from first_transition_native_cleanup import NativeCleanupDaemonEvidence
                original=self._cleanup.observation
                require(asdict(original)==asdict(observation),CODE)
                evidence=self._cleanup.validate_observation(original)
                require(type(evidence) is NativeCleanupDaemonEvidence,CODE)
                self._daemon_evidence_digest=evidence.digest
                self._daemon_cleanup_verified=(evidence.transport=='bounded-docker-cli'
                    and self._capture_result.get('daemon_cleanup_verified') is True)
        self._advance('cleanup-validated',validate)

    def finish(self):
        self._advance('result')
        return dict(schema=SCHEMA,request_digest=self.pins.request_sha256,context_digest=self.pins.context_sha256,
            plan_digest=self.pins.plan_sha256,runtime_sha256=self.pins.runtime_sha256,
            manifest_digest=self.pins.manifest_sha256,source_identity=self.pins.source_identity,
            c2_result_digest=self._c2_digest,supervised_result_digest=self._capture_digest,
            cleanup_observation_digest=self._cleanup_digest,daemon_evidence_digest=self._daemon_evidence_digest,
            daemon_cleanup_verified=self._daemon_cleanup_verified,events=deepcopy(self._events),
            source_unchanged_proven=False,authoritative_fence_verified=False,ddl_authorized=False,
            a8_window_proven=False,operational_dispatch_enabled=False,operational_ready=False)

    def admit_operational(self):
        raise Refused('native-dispatch-authoritative-fence-missing')

    def origin_receipt(self):
        raise Refused('native-dispatch-authoritative-fence-missing')
