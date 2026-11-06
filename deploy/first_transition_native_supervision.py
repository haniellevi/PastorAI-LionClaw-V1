"""Staged parent supervision; no operational factory or OriginReceipt producer.

The native worker is externally bounded and reaped by NativeWorkerSupervisor.
Daemon cleanup is a REQUIRED trusted callback boundary, called even when the
worker fails or returns invalid output. Its typed observation is checked for
association/absence only; it never proves daemon authority by declaration.
Cleanup callbacks MUST enforce their deadline on each real daemon operation.
Before/after checks cannot preempt a blocked callback/native kernel operation:
the complete wrapper requires a dedicated outer process for a hard deadline.
No signals, retries, metadata-adopted resources, or source fence are installed.
"""
from copy import deepcopy
from dataclasses import asdict,dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time

from first_transition_adapter import Plan,digest
from first_transition_capture_contract import V3_CATEGORIES
from first_transition_native_events import PHASES as JOB_PHASES,SCHEMA as EVENTS_SCHEMA
from first_transition_native_job import JOB_SCHEMA
from first_transition_orchestrator import BACKUP_REQUEST_SCHEMA,CLONE_FIELDS
from first_transition_window_backup import NativeWorkerSupervisor,WINDOW_REQUEST_FIELDS
from initial_transition_files import read_regular
from initial_transition_ops import Refused,require

SCHEMA='igreja12.native-supervised-window/1'
CODE='native-supervised-window-failed'
HEX=re.compile(r'[0-9a-f]{64}\Z')
JOB_FIELDS=frozenset(('schema','binding','binding_digest','clone_rehearsal','comparison','cleanup_verified',
    'events','source_unchanged_proven','a8_window_proven','operational_ready'))
BINDING_FIELDS=frozenset(('request_digest','context_digest','dump_sha256','companion_sha256','snapshot_sha256',
    'sample_summary','container_id','network_id','clone_identity','daemon_id','image_id','clone_system_sha256',
    'code_pins_sha256','effective_source_policy_sha256','dump_spec_sha256','events_sha256',
    'source_unchanged_proven','clone_rehearsal_digest'))
SUMMARY_FIELDS=frozenset(('v2_observed_sha256','v2_clone_expected_sha256','v3_sha256','row_counts_sha256',
    'settings_inventory_sha256','v3_counts'))
EVENT_FIELDS=frozenset(('schema','request_digest','context_digest','events','source_unchanged_proven',
    'writer_absence_proven','source_state_equality_proven','a8_window_proven'))
JOINT_FIELDS=frozenset(('schema','artifacts','aggregates','policy_sha256','runtime_sha256','maximum_pulse_gap_s',
    'pulse_calls','fixture_scope_only','source_unchanged_proven','authoritative_fence_verified',
    'storage_body_retention_verified','storage_recovery_verified','a8_window_proven','operational_ready'))
JOINT_FALSE=frozenset(('source_unchanged_proven','authoritative_fence_verified','storage_body_retention_verified',
    'storage_recovery_verified','a8_window_proven','operational_ready'))
AGGREGATE_FIELDS=frozenset(('schema','selected_objects','hashed_objects','hashed_bytes','references',
    'same_holder_snapshot_observed','source_body_hashes_verified','authority_verified',
    'native_transport_keepalive_proven','all_application_references_covered','a8_window_proven',
    'operational_receipt','production_go'))
REFERENCE_TABLES=frozenset(('public.messages','public.igrejas','public.cell_report_audio_inputs',
    'public.private_deletion_tasks'))


def _hex(value):return type(value) is str and HEX.fullmatch(value) is not None
def _number(value):return type(value) in (int,float) and math.isfinite(value)
def _count(value):return type(value) is int and 0<=value<=2**63-1


@dataclass(frozen=True)
class NativeSupervisionPins:
    request_sha256: str
    context_sha256: str
    runtime_sha256: str
    worker_argv_sha256: str
    source_policy_sha256: str
    dump_spec_sha256: str
    # Independent expectations, not enable flags. A pin requires the paired
    # extension; None forbids it, including downgrade/upgrade ambiguity.
    joint_policy_sha256: str | None = None
    parent_registry_sha256: str | None = None


def _valid_pins(value):
    optional={'joint_policy_sha256','parent_registry_sha256'}
    return (type(value) is NativeSupervisionPins
            and all(_hex(v) for k,v in asdict(value).items() if k not in optional)
            and all(getattr(value,k) is None or _hex(getattr(value,k)) for k in optional))


@dataclass(frozen=True)
class NativeCleanupObservation:
    """Callback observation, explicitly NOT a real daemon authority receipt."""
    request_digest: str
    context_digest: str
    job_binding_digest: str | None
    status: str
    daemon_id: str
    inspected_resource_ids: tuple[str,...]
    absent_resource_ids: tuple[str,...]


def _pairs(values):
    result={}
    for key,value in values:
        require(key not in result,CODE)
        result[key]=value
    return result


class NativeSupervisedWindow:
    """One pinned worker attempt plus mandatory parent cleanup/revalidation.

    runtime_sources is a trusted reader, additionally checked against the
    actual sibling source files before launch and after cleanup. The input FD
    remains opaque/private and must already have all four Linux memfd seals.
    Parent observations describe supervision only; child capture events stay
    distinct and are never synthesized from parent timestamps.
    """
    def __init__(self,argv,pins,*,plan,runtime_sources,cleanup,timeout_s=1200,cleanup_budget_s=30,
                 clock=None,wall_clock=None):
        require(_valid_pins(pins)
                and type(argv) is tuple and argv and all(type(v) is str for v in argv)
                and digest(argv)==pins.worker_argv_sha256 and type(plan) is Plan
                and callable(runtime_sources) and callable(cleanup)
                and _number(timeout_s) and 0<timeout_s<=1200
                and _number(cleanup_budget_s) and 0<cleanup_budget_s<timeout_s
                and timeout_s-cleanup_budget_s>.2
                and (clock is None or callable(clock)) and (wall_clock is None or callable(wall_clock)),CODE)
        self.argv,self.pins,self.plan=argv,pins,plan
        self.runtime_sources,self.cleanup=runtime_sources,cleanup
        self.timeout,self.cleanup_budget=timeout_s,cleanup_budget_s
        self.clock,self.wall_clock=clock or time.monotonic,wall_clock or time.time
        self.used=False
        self._events=[];self._first=self._last=None
        self._status='not-started'
        self._worker_reaped=self._worker_cleanup_uncertain=False
        self._report_sha256=None
        self._daemon_evidence=None
        self._daemon_cleanup_verified=False
        self._report_refs=self._report_config=self._report_first=self._validation_last=None
        self._parent_registry(fresh=True)

    def _parent_registry(self,*,fresh=False):
        """Typed registry from the parent creator; never adopt worker IDs."""
        if self.pins.parent_registry_sha256 is None:return None
        from first_transition_native_cleanup import NativeDockerCleanup
        require(type(self.cleanup) is NativeDockerCleanup,CODE)
        self.cleanup._binding()
        registry=self.cleanup.registry
        require(registry.digest==self.pins.parent_registry_sha256
                and registry.request_digest==self.pins.request_sha256
                and registry.context_digest==self.pins.context_sha256
                and registry.network_id is not None and len(registry.containers)>0
                and self.cleanup.clock is self.clock and self.cleanup.wall_clock is self.wall_clock,CODE)
        if fresh:
            require(self.cleanup._used is False and self.cleanup.observation is None
                    and self.cleanup.daemon_evidence is None,CODE)
        return registry

    def _report_binding(self):
        return digest([asdict(self.pins),self.argv,self.timeout,self.cleanup_budget,self.plan.digest])

    def _report_binding_check(self):
        require(self._report_refs is not None and all(a is b for a,b in zip(
            (self.clock,self.wall_clock,self.cleanup,self.runtime_sources,self.plan),self._report_refs))
            and self._report_binding()==self._report_config,CODE)

    def _observe(self,phase):
        wall,mono=self.wall_clock(),self.clock()
        require(_number(wall) and wall>0 and _number(mono) and mono>=0,CODE)
        if self._first is None:self._first=(wall,mono)
        if self._last is not None:
            require(wall>=self._last[0] and mono>=self._last[1]
                    and abs((wall-self._last[0])-(mono-self._last[1]))<=2,CODE)
        elapsed=mono-self._first[1]
        require(abs((wall-self._first[0])-elapsed)<=2 and elapsed<=self.timeout,CODE)
        self._last=(wall,mono)
        self._events.append(dict(sequence=len(self._events),phase=phase,wall_at=wall,elapsed_s=elapsed))

    def _runtime(self):
        values=self.runtime_sources()
        require(type(values) is tuple and 0<len(values)<=128 and all(type(v) is tuple and len(v)==2
                and type(v[0]) is str and re.fullmatch('[A-Za-z0-9_]+\\.py',v[0]) and _hex(v[1]) for v in values),CODE)
        require(len(dict(values))==len(values) and values==self.plan.adapter_sources
                and digest(dict(values))==self.pins.runtime_sha256,CODE)
        directory=Path(__file__).resolve().parent
        require(all(hashlib.sha256(read_regular(directory/name,2097152)).hexdigest()==pin for name,pin in values),CODE)

    def _events_validate(self,value,now):
        require(type(value) is dict and set(value)==EVENT_FIELDS and value['schema']==EVENTS_SCHEMA
                and value['request_digest']==self.pins.request_sha256
                and value['context_digest']==self.pins.context_sha256
                and all(value[k] is False for k in EVENT_FIELDS-{'schema','request_digest','context_digest','events'})
                and type(value['events']) is list and len(value['events'])==len(JOB_PHASES),CODE)
        first=last=None;observed={}
        for sequence,event in enumerate(value['events']):
            require(type(event) is dict and set(event)=={'sequence','phase','wall_at','elapsed_s'}
                    and type(event['sequence']) is int and event['sequence']==sequence
                    and event['phase']==JOB_PHASES[sequence] and _number(event['wall_at']) and event['wall_at']>0
                    and _number(event['elapsed_s']) and 0<=event['elapsed_s']<=1200,CODE)
            wall,elapsed=event['wall_at'],event['elapsed_s']
            if first is None:
                require(elapsed==0 and wall>=self._first[0]-2,CODE)
                first=(wall,elapsed)
            if last is not None:
                require(wall>=last[0] and elapsed>=last[1]
                        and abs((wall-last[0])-(elapsed-last[1]))<=2,CODE)
            require(abs((wall-first[0])-elapsed)<=2 and wall<=now+2,CODE)
            phase=event['phase']
            if phase=='capture-start':require(elapsed<=60,CODE)
            if 'capture-start' in observed and 'capture-finish' not in observed:
                require(elapsed<=240 and elapsed-observed['capture-start']<=240,CODE)
            if phase=='recovery-start':require(elapsed-observed['capture-finish']<=60,CODE)
            if phase=='cleanup-finish':require(elapsed-observed['recovery-finish']<=60,CODE)
            if phase=='result':require(elapsed-observed['cleanup-finish']<=60,CODE)
            last=(wall,elapsed);observed[phase]=elapsed
        require(now-last[0]<=60,CODE)

    def _validate(self,raw):
        require(type(raw) is bytes and 0<len(raw)<=131072,CODE)
        def bad_constant(_value):raise Refused(CODE)
        value=json.loads(raw,object_pairs_hook=_pairs,parse_constant=bad_constant)
        joint=self.pins.joint_policy_sha256 is not None
        parent=self.pins.parent_registry_sha256 is not None
        extra=({'joint'} if joint else set())|({'parent_cleanup_required'} if parent else set())
        binding_extra=({'joint_capture_digest'} if joint else set())|({'parent_registry_digest'} if parent else set())
        require(type(value) is dict and set(value)==JOB_FIELDS|extra and value['schema']==JOB_SCHEMA
                and value['cleanup_verified'] is (not parent)
                and (not parent or value['parent_cleanup_required'] is True)
                and all(value[k] is False for k in ('source_unchanged_proven','a8_window_proven','operational_ready')),CODE)
        binding=value['binding']
        require(type(binding) is dict and set(binding)==BINDING_FIELDS|binding_extra and _hex(value['binding_digest'])
                and digest(binding)==value['binding_digest'] and binding['source_unchanged_proven'] is False
                and binding['request_digest']==self.pins.request_sha256
                and binding['context_digest']==self.pins.context_sha256
                and binding['code_pins_sha256']==self.pins.runtime_sha256
                and binding['effective_source_policy_sha256']==self.pins.source_policy_sha256
                and binding['dump_spec_sha256']==self.pins.dump_spec_sha256,CODE)
        require(all(_hex(binding[k]) for k in (BINDING_FIELDS|binding_extra)-
                    {'sample_summary','daemon_id','image_id','source_unchanged_proven'})
                and type(binding['daemon_id']) is str and re.fullmatch('[A-Za-z0-9_.:-]{1,128}',binding['daemon_id'])
                and type(binding['image_id']) is str and re.fullmatch('sha256:[0-9a-f]{64}',binding['image_id'])
                and binding['container_id']!=binding['network_id'],CODE)
        if parent:
            registry=self._parent_registry()
            known={c.container_id:c for c in registry.containers}
            require(binding['parent_registry_digest']==self.pins.parent_registry_sha256
                    and binding['daemon_id']==registry.daemon_id and binding['network_id']==registry.network_id
                    and binding['container_id'] in known
                    and binding['image_id']==known[binding['container_id']].image_id,CODE)
        if joint:
            self._joint_validate(value['joint'])
            require(digest(value['joint'])==binding['joint_capture_digest'],CODE)
        summary=binding['sample_summary']
        require(type(summary) is dict and set(summary)==SUMMARY_FIELDS
                and all(_hex(summary[k]) for k in SUMMARY_FIELDS-{'v3_counts'})
                and type(summary['v3_counts']) is dict and set(summary['v3_counts'])==set(V3_CATEGORIES)
                and all(_count(v) for v in summary['v3_counts'].values()),CODE)
        clone=value['clone_rehearsal']
        require(type(clone) is dict and set(clone)==set(CLONE_FIELDS)
                and clone['migrations_verified'] is clone['cluster_global_ddl_possible'] is True
                and all(type(clone[k]) is int for k in ('applied','final_ledger','concurrent'))
                and clone['applied']==len(self.plan.pending) and clone['final_ledger']==len(self.plan.migrations)
                and clone['concurrent']==sum(m.concurrent for m in self.plan.pending)
                and clone['sql_digest']==digest([(m.name,m.sha256) for m in self.plan.pending])
                and _hex(clone['final_schema_digest']) and _hex(clone['clone_identity'])
                and clone['clone_identity']==binding['clone_identity']
                and clone['clone_identity']!=self._request['source_identity']
                and digest(clone)==binding['clone_rehearsal_digest'],CODE)
        comparison=value['comparison']
        require(type(comparison) is dict and set(comparison)=={'equal','v2','v3_categories','automatic_repair',
                    'v2_login_projection','raw_source_settings_equal_claimed'}
                and comparison['equal'] is True and comparison['automatic_repair'] is False
                and comparison['raw_source_settings_equal_claimed'] is False
                and comparison['v2_login_projection']=='canonical-isolated-clone'
                and type(comparison['v2']) is dict and set(comparison['v2'])=={'catalog','row_counts','settings'}
                and all(v is True for v in comparison['v2'].values())
                and type(comparison['v3_categories']) is dict and set(comparison['v3_categories'])==set(V3_CATEGORIES),CODE)
        for name,category in comparison['v3_categories'].items():
            require(type(category) is dict and set(category)=={'expected','actual','missing','extra','changed','equal'}
                    and category['equal'] is True and all(_count(category[k]) for k in category if k!='equal')
                    and category['missing']==category['extra']==category['changed']==0
                    and category['actual']==category['expected']==summary['v3_counts'][name],CODE)
        self._events_validate(value['events'],self.wall_clock())
        require(digest(value['events'])==binding['events_sha256'],CODE)
        return value

    def _joint_validate(self,value):
        """Public association/bounds only; private manifest/bodies stay private.

        The trusted job/custody bind source/window/dump in its private manifest.
        This parser sees only artifact digests and aggregates, so it does not
        attest private contents, a writer fence or Storage retention/recovery.
        """
        require(type(value) is dict and set(value)==JOINT_FIELDS
                and value['schema']=='igreja12.native-synthetic-joint/1'
                and value['fixture_scope_only'] is True and all(value[k] is False for k in JOINT_FALSE)
                and value['policy_sha256']==self.pins.joint_policy_sha256
                and value['runtime_sha256']==self.pins.runtime_sha256
                and _number(value['maximum_pulse_gap_s']) and 0<=value['maximum_pulse_gap_s']<=2
                and type(value['pulse_calls']) is int and 0<=value['pulse_calls']<=240
                and (value['pulse_calls']>0 or value['maximum_pulse_gap_s']<1),CODE)
        artifacts=value['artifacts']
        require(type(artifacts) is dict and set(artifacts)=={'request_digest','artifacts'}
                and artifacts['request_digest']==self.pins.request_sha256
                and type(artifacts['artifacts']) is dict and set(artifacts['artifacts'])=={'projection','manifest'},CODE)
        for name,limit in (('projection',16777216),('manifest',2097152)):
            item=artifacts['artifacts'][name]
            require(type(item) is dict and set(item)=={'sha256','size'} and _hex(item['sha256'])
                    and type(item['size']) is int and 0<item['size']<=limit,CODE)
        aggregate=value['aggregates']
        require(type(aggregate) is dict and set(aggregate)==AGGREGATE_FIELDS
                and aggregate['schema']=='igreja12.joint-collector-aggregates/1'
                and type(aggregate['selected_objects']) is int and 0<=aggregate['selected_objects']<=1000
                and type(aggregate['hashed_objects']) is int
                and aggregate['hashed_objects']==aggregate['selected_objects']
                and type(aggregate['hashed_bytes']) is int and 0<=aggregate['hashed_bytes']<=1000000000
                and (aggregate['selected_objects']>0 or aggregate['hashed_bytes']==0)
                and aggregate['same_holder_snapshot_observed'] is aggregate['source_body_hashes_verified'] is True
                and all(aggregate[k] is False for k in ('authority_verified','native_transport_keepalive_proven',
                    'all_application_references_covered','a8_window_proven','operational_receipt','production_go'))
                and type(aggregate['references']) is dict and set(aggregate['references'])==REFERENCE_TABLES,CODE)
        rows=0
        for reference in aggregate['references'].values():
            require(type(reference) is dict and set(reference)=={'state','rows','nonempty_references',
                    'missing_in_catalog','missing_in_preserved'},CODE)
            counts=('rows','nonempty_references','missing_in_catalog','missing_in_preserved')
            if reference['state']=='not_projected':
                require(all(reference[k] is None for k in counts),CODE)
            else:
                require(reference['state']=='projected' and all(type(reference[k]) is int
                        and 0<=reference[k]<=10000 for k in counts)
                        and reference['nonempty_references']<=reference['rows']
                        and reference['missing_in_catalog']==reference['missing_in_preserved']
                        <=reference['nonempty_references'],CODE)
                if aggregate['selected_objects']==0:
                    require(reference['missing_in_catalog']==reference['nonempty_references'],CODE)
                rows+=reference['rows']
                require(rows<=10000,CODE)

    def _cleanup_validate(self,value,result,status):
        require(type(value) is NativeCleanupObservation and value.request_digest==self.pins.request_sha256
                and value.context_digest==self.pins.context_sha256 and value.status==status
                and value.job_binding_digest==(None if result is None else result['binding_digest'])
                and type(value.daemon_id) is str and re.fullmatch('[A-Za-z0-9_.:-]{1,128}',value.daemon_id)
                and type(value.inspected_resource_ids) is tuple and type(value.absent_resource_ids) is tuple
                and len(value.inspected_resource_ids)<=64
                and all(_hex(v) for v in value.inspected_resource_ids)
                and len(set(value.inspected_resource_ids))==len(value.inspected_resource_ids)
                and value.inspected_resource_ids==value.absent_resource_ids,CODE)
        if result is not None:
            require(value.daemon_id==result['binding']['daemon_id']
                    and {result['binding']['container_id'],result['binding']['network_id']}<=set(value.inspected_resource_ids),CODE)
        return asdict(value)

    def diagnostics(self):
        return dict(status=self._status,request_digest=self.pins.request_sha256,context_digest=self.pins.context_sha256,
            parent_events=deepcopy(self._events),daemon_cleanup_authoritative=False,
            worker_reaped=self._worker_reaped,worker_cleanup_uncertain=self._worker_cleanup_uncertain,
            daemon_cleanup_verified=self._daemon_cleanup_verified,daemon_evidence=deepcopy(self._daemon_evidence),
            cleanup_hard_deadline_verified=False,requires_dedicated_outer_process=True,
            source_unchanged_proven=False,a8_window_proven=False,operational_ready=False)

    def run(self,request,context,*,input_fd):
        require(not self.used,'native-supervised-window-used');self.used=True
        result=cleanup_result=None;status='worker-failed';failure=False;interrupted=False
        try:
            require(_valid_pins(self.pins),CODE)
            self._parent_registry(fresh=True)
            self._report_refs=(self.clock,self.wall_clock,self.cleanup,self.runtime_sources,self.plan)
            self._report_config=self._report_binding()
            self._observe('request-received')
            require(type(request) is dict and set(request)==WINDOW_REQUEST_FIELDS
                    and request['schema']==BACKUP_REQUEST_SCHEMA
                    and all(_hex(v) for k,v in request.items() if k!='schema')
                    and request['plan_digest']==self.plan.digest and type(context) is dict
                    and digest(request)==self.pins.request_sha256 and digest(context)==self.pins.context_sha256
                    and context.get('source_identity')==request['source_identity']
                    and digest(self.argv)==self.pins.worker_argv_sha256,CODE)
            self._request=deepcopy(request)
            self._runtime()
            require(type(input_fd) is int and input_fd>2 and stat.S_ISREG(os.fstat(input_fd).st_mode)
                    and 0<os.fstat(input_fd).st_size<=2097152 and fcntl.fcntl(input_fd,1034)&15==15,CODE)
            deadline=self._first[1]+self.timeout
            self._observe('supervisor-start')
            supervisor=NativeWorkerSupervisor(cleanup_wait=.1)
            try:
                raw=supervisor.run(self.argv,timeout=deadline-self.clock()-self.cleanup_budget-.1,input_fd=input_fd)
                self._worker_reaped=True
                self._observe('worker-reaped')
                status='invalid-result'
                result=self._validate(raw)
                status='validated'
            except Exception:failure=True
            except BaseException:failure=interrupted=True
            finally:
                self._worker_cleanup_uncertain=supervisor.unreaped
                # The cleanup adapter must have independent owned-resource
                # handles/registry when child output is missing or malformed.
                try:self._observe('cleanup-start')
                except Exception:failure=True
                except BaseException:failure=interrupted=True
                try:
                    observation=self.cleanup(request_digest=self.pins.request_sha256,context_digest=self.pins.context_sha256,
                        result=deepcopy(result),status=status,deadline=deadline,
                        worker_cleanup_uncertain=self._worker_cleanup_uncertain)
                    cleanup_result=self._cleanup_validate(observation,result,status)
                    from first_transition_native_cleanup import NativeDockerCleanup,NativeCleanupDaemonEvidence
                    if type(self.cleanup) is NativeDockerCleanup:
                        evidence=self.cleanup.validate_observation(observation)
                        require(type(evidence) is NativeCleanupDaemonEvidence
                            and evidence.observation_sha256==digest(cleanup_result)
                            and self.cleanup.clock is self.clock and self.cleanup.wall_clock is self.wall_clock,CODE)
                        self._daemon_evidence=asdict(evidence)
                        self._daemon_cleanup_verified=(evidence.transport=='bounded-docker-cli'
                            and self._worker_reaped and not self._worker_cleanup_uncertain)
                    require(self.clock()<deadline,CODE)
                except Exception:failure=True
                except BaseException:failure=interrupted=True
                try:self._observe('cleanup-finish')
                except Exception:failure=True
                except BaseException:failure=interrupted=True
            if interrupted:raise KeyboardInterrupt from None
            self._runtime()
            self._report_binding_check()
            self._observe('revalidated')
            require(not failure and status=='validated' and result is not None and cleanup_result is not None,CODE)
            self._status='staged-complete'
            report=dict(schema=SCHEMA,job=deepcopy(result),job_digest=digest(result),cleanup_observation=cleanup_result,
                parent_events=dict(request_digest=self.pins.request_sha256,context_digest=self.pins.context_sha256,
                    events=deepcopy(self._events)),runtime_sha256=self.pins.runtime_sha256,
                worker_reaped=True,daemon_cleanup_authoritative=False,cleanup_hard_deadline_verified=False,
                daemon_cleanup_verified=self._daemon_cleanup_verified,daemon_evidence=deepcopy(self._daemon_evidence),
                requires_dedicated_outer_process=True,source_unchanged_proven=False,a8_window_proven=False,operational_ready=False)
            self._report_sha256=digest(report)
            self._report_first=self._first;self._validation_last=self._last
            return report
        except Exception:
            self._status='failed'
            raise Refused(CODE) from None
        except BaseException:
            self._status='failed'
            raise KeyboardInterrupt from None
        finally:
            if interrupted:self._status='failed'

    def origin_receipt(self):
        """No observed/staged result can replace a missing authoritative fence."""
        raise Refused('native-supervised-authoritative-fence-missing')

    def validate_report(self,report):
        """Revalidate only this instance's actual successful return, never JSON authority."""
        try:
            require(self.used is True and self._status=='staged-complete' and self._report_sha256 is not None
                and self._worker_reaped is True and self._worker_cleanup_uncertain is False
                and type(report) is dict and digest(report)==self._report_sha256,CODE)
            self._report_binding_check()
            wall,mono=self.wall_clock(),self.clock()
            first,last=self._report_first,self._validation_last
            require(_number(wall) and wall>0 and _number(mono) and mono>=0
                and wall>=last[0] and mono>=last[1] and mono-first[1]<=self.timeout
                and abs((wall-last[0])-(mono-last[1]))<=2
                and abs((wall-first[0])-(mono-first[1]))<=2,CODE)
            self._runtime()
            raw=json.dumps(report['job'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()
            value=self._validate(raw)
            require(digest(value)==report['job_digest'],CODE)
            from first_transition_native_cleanup import NativeDockerCleanup
            if type(self.cleanup) is NativeDockerCleanup:
                observation=self.cleanup.observation
                evidence=self.cleanup.validate_observation(observation)
                require(asdict(observation)==report['cleanup_observation']
                    and asdict(evidence)==report['daemon_evidence']
                    and evidence.observation_sha256==digest(report['cleanup_observation'])
                    and report['daemon_cleanup_verified'] is (evidence.transport=='bounded-docker-cli'),CODE)
            self._report_binding_check();self._validation_last=(wall,mono)
            return deepcopy(report)
        except Exception:
            self._status='report-invalid'
            raise Refused('native-supervised-report-binding') from None
        except BaseException:
            self._status='report-invalid'
            raise KeyboardInterrupt from None
