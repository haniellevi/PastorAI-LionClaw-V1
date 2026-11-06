"""Dedicated Linux outer deadline for the entire staged C2/capture wrapper.

Forked callbacks inherit bound ports, never receive authority from caller JSON.
The exclusive single-thread reaper temporarily becomes a child subreaper: even
trusted descendants using setsid are adopted, signalled through pidfds and
reaped before parent-owned Docker cleanup. This is not a sandbox against hostile
code, escaped remote work, kernel stalls or an uninspectable process tree.
Provisioning precedes this boundary. Source fence/DDL/Origin admission stay shut.
"""
from copy import deepcopy
import ctypes
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import select
import signal
import time

from first_transition_adapter import digest
from first_transition_native_cleanup import NativeDockerCleanup
from first_transition_native_dispatch import NativeC2Dispatcher
from initial_transition_ops import Refused,require

CODE='native-outer-dispatch-failed'
SCHEMA='igreja12.native-outer-dispatch/1'
LIMIT=131072


def _number(value):return type(value) in (int,float) and math.isfinite(value)


def _subreaper(value=None):
    libc=ctypes.CDLL(None,use_errno=True)
    if value is not None:require(libc.prctl(36,int(value),0,0,0)==0,CODE)
    current=ctypes.c_int()
    require(libc.prctl(37,ctypes.byref(current),0,0,0)==0 and current.value in (0,1),CODE)
    return current.value


def _children():
    values=(Path('/proc/self/task')/str(os.getpid())/'children').read_text().split()
    require(len(values)<=64 and all(v.isdecimal() for v in values),CODE)
    return tuple(int(v) for v in values)


def _pairs(values):
    result={}
    for k,v in values:
        require(k not in result,CODE);result[k]=v
    return result


class NativeOuterDispatch:
    """One attempt, real monotonic deadline and reserved parent finalization.

    Caller must own this dedicated process, its sole waitpid/reaper role and all
    forks throughout run(). Existing children, threads, custom SIGCHLD or an
    existing subreaper are refused. Every callback/port runs in a child; only
    fixed process-state/FD monitoring occurs in this parent. No automatic retry,
    host resume, metadata adoption or operational factory entry is introduced.
    """
    def __init__(self,dispatcher,*,timeout_s=30,cleanup_budget_s=5,stop_budget_s=.3):
        require(type(dispatcher) is NativeC2Dispatcher and not dispatcher.used
            and _number(timeout_s) and 0<timeout_s<=1200
            and _number(cleanup_budget_s) and 0<cleanup_budget_s<timeout_s
            and _number(stop_budget_s) and 0<stop_budget_s<=2
            and cleanup_budget_s>stop_budget_s+.1
            and timeout_s-cleanup_budget_s>stop_budget_s+.2,CODE)
        cleanup=dispatcher.gates.supervisor.cleanup
        require(type(cleanup) is NativeDockerCleanup and cleanup.observation is None,CODE)
        self.dispatcher,self.cleanup=dispatcher,cleanup
        self.timeout,self.cleanup_budget,self.stop_budget=timeout_s,cleanup_budget_s,stop_budget_s
        self._config=(timeout_s,cleanup_budget_s,stop_budget_s)
        self._refs=(dispatcher,dispatcher.gates,dispatcher.gates.supervisor,cleanup,cleanup.registry)
        g=dispatcher.gates
        self._session=g.c2_session;self._consumed=False
        self._pins=deepcopy(asdict(g.pins));self._registry_digest=cleanup.registry.digest
        self.used=False;self._result_sha256=None;self._started=self._finished=None
        self._diag=dict(main_reaped=False,main_process_created=False,cleanup_reaped=False,process_cleanup_verified=False,
            parent_cleanup_completed=False,staged_complete=False,authoritative_fence_proven=False,
            source_unchanged_proven=False,a8_window_proven=False,operational_ready=False)
        self._last_reaped=self._last_started=False

    def __repr__(self):return '<NativeOuterDispatch staged, dedicated reaper required>'

    def _bound(self):
        d,g,s,c,r=self._refs
        require(self.dispatcher is d and d.gates is g and g.supervisor is s and s.cleanup is c
            and self.cleanup is c and c.registry is r and r.digest==self._registry_digest
            and g.c2_session is self._session and asdict(g.pins)==self._pins
            and d.used is self._consumed and s.used is self._consumed and self._session.used is self._consumed
            and c._used is self._consumed and g._failed is self._consumed
            and c.observation is None and (self.timeout,self.cleanup_budget,self.stop_budget)==self._config,CODE)
        protected={g.manifest.network_id,*dict(g.manifest.service_ids).values(),*dict(g.manifest.support_ids).values()}
        owned={v.container_id for v in r.containers}
        if r.network_id is not None:owned.add(r.network_id)
        require(not owned&protected and r.request_digest==self._pins['request_sha256']
            and r.context_digest==self._pins['context_sha256'],CODE)

    def _drain(self,deadline):
        codes={}
        while True:
            children=_children()
            if not children:return codes
            require(time.monotonic()<deadline,CODE)
            for pid in children:
                # With no other reaper, this direct child cannot be recycled.
                os.waitid(os.P_PID,pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
                fd=os.pidfd_open(pid)
                try:signal.pidfd_send_signal(fd,signal.SIGKILL)
                finally:os.close(fd)
            for pid in children:
                found,status=os.waitpid(pid,os.WNOHANG)
                if found:codes[pid]=os.waitstatus_to_exitcode(status)
            if _children():time.sleep(min(.005,max(0,deadline-time.monotonic())))

    @staticmethod
    def _invoke(callback,outfd,input_fd,deadline):
        try:
            os.setsid();os.chdir('/');os.umask(0o077)
            for name in os.listdir('/proc/self/fd'):
                if name.isdecimal() and int(name)>2 and int(name) not in (outfd,input_fd):
                    try:os.close(int(name))
                    except OSError:pass
            null=os.open('/dev/null',os.O_RDWR)
            try:
                for fd in (0,1,2):os.dup2(null,fd)
            finally:
                if null>2:os.close(null)
            for sig in (signal.SIGCHLD,signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_DFL)
            os.environ.clear();os.environ.update(PATH='/usr/bin:/bin',LC_ALL='C',PYTHON_DOTENV_DISABLED='1')
            value=callback()
            raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
            require(0<len(raw)<=LIMIT,CODE)
            while raw:
                remaining=deadline-time.monotonic();require(remaining>0,CODE)
                _,ready,_=select.select((),(outfd,),(),remaining);require(ready,CODE)
                try:n=os.write(outfd,raw)
                except BlockingIOError:continue
                require(n>0,CODE);raw=raw[n:]
            os.close(outfd);os._exit(0)
        except BaseException:os._exit(97)

    def _attempt(self,callback,*,deadline,input_fd):
        require(deadline-time.monotonic()>self.stop_budget,CODE)
        readfd=writefd=None
        pid=pidfd=None;raw=bytearray();failure=False;interrupted=False;self._last_reaped=self._last_started=False
        try:
            readfd,writefd=os.pipe2(os.O_CLOEXEC|os.O_NONBLOCK)
            pid=os.fork()
            if pid==0:self._invoke(callback,writefd,input_fd,deadline-self.stop_budget)
            self._last_started=True
            os.close(writefd);writefd=None
            pidfd=os.pidfd_open(pid)
            eof=False
            while True:
                remaining=deadline-self.stop_budget-time.monotonic();require(remaining>0,CODE)
                ready,_,_=select.select((pidfd,) if eof else (readfd,pidfd),(),(),remaining)
                require(ready,CODE)
                if readfd in ready:
                    chunk=os.read(readfd,min(65536,LIMIT+1-len(raw)))
                    raw.extend(chunk);require(len(raw)<=LIMIT,CODE)
                    if not chunk:eof=True
                if eof and pidfd in ready:break
        except Exception:failure=True
        except BaseException:failure=interrupted=True
        finally:
            codes={}
            try:
                if pid is not None:
                    codes=self._drain(deadline)
                    self._last_reaped=not _children()
                else:self._last_reaped=not _children()
            except Exception:failure=True
            except BaseException:failure=interrupted=True
            for fd in (readfd,writefd,pidfd):
                if fd is not None:
                    try:os.close(fd)
                    except OSError:failure=True
        if interrupted:raise KeyboardInterrupt from None
        require(not failure and self._last_reaped and codes=={pid:0} and raw,CODE)
        def invalid(_value):raise Refused(CODE)
        return json.loads(raw,object_pairs_hook=_pairs,parse_constant=invalid)

    def _dispatch_child(self,input_fd):
        result=self.dispatcher.run(input_fd=input_fd)
        self.dispatcher.validate_result(result)
        return dict(dispatch=result,supervised=deepcopy(self.dispatcher._supervised))

    def _cleanup_child(self,deadline):
        remaining=deadline-self.stop_budget-time.monotonic();require(remaining>0,CODE)
        # Independent finalization of the frozen parent registry, in success
        # and failure alike. Child output never selects or authorizes its IDs.
        value=self.cleanup(request_digest=self._pins['request_sha256'],context_digest=self._pins['context_sha256'],
            result=None,status='worker-failed',
            deadline=self.cleanup.clock()+remaining,worker_cleanup_uncertain=False)
        evidence=self.cleanup.validate_observation(value)
        # Runtime drift can refuse the result, never suppress owned cleanup.
        runtime_revalidated=False
        try:
            self.dispatcher.gates._check()
            runtime_revalidated=True
        except Exception:pass
        return dict(observation=asdict(value),evidence=asdict(evidence),evidence_digest=evidence.digest,
            runtime_revalidated=runtime_revalidated)

    def diagnostics(self):return deepcopy(self._diag)

    def run(self,*,input_fd):
        require(not self.used,'native-outer-dispatch-used');self.used=True
        main=cleanup=None;armed=False;failure=False;interrupted=False
        self._started=time.monotonic();deadline=self._started+self.timeout
        try:
            self._bound();input_pin=NativeC2Dispatcher._input(input_fd)
            require(hasattr(os,'fork') and hasattr(signal,'pidfd_send_signal')
                and signal.getsignal(signal.SIGCHLD)==signal.SIG_DFL
                and len(os.listdir('/proc/self/task'))==1 and not _children() and _subreaper()==0,CODE)
            _subreaper(True);armed=True;require(_subreaper()==1,CODE)
            try:main=self._attempt(lambda:self._dispatch_child(input_fd),deadline=deadline-self.cleanup_budget,input_fd=input_fd)
            except Exception:failure=True
            except BaseException:failure=interrupted=True
            self._diag['main_reaped']=self._last_reaped
            self._diag['main_process_created']=self._last_started
            if self._last_reaped:
                try:
                    if main is not None:
                        require(type(main) is dict and set(main)=={'dispatch','supervised'}
                            and type(main['dispatch']) is dict and type(main['supervised']) is dict
                            and digest(main['supervised'])==main['dispatch']['supervised_digest']
                            and main['supervised']['runtime_sha256']==self._pins['runtime_sha256'],CODE)
                except Exception:main=None;failure=True
                except BaseException:main=None;failure=interrupted=True
                try:
                    cleanup=self._attempt(lambda:self._cleanup_child(deadline),deadline=deadline,input_fd=input_fd)
                    self._diag['parent_cleanup_completed']=True
                except Exception:failure=True
                except BaseException:failure=interrupted=True
                self._diag['cleanup_reaped']=self._last_reaped
            require(NativeC2Dispatcher._input(input_fd)==input_pin,CODE)
            self._bound()
        except Exception:failure=True
        except BaseException:failure=interrupted=True
        finally:
            try:
                if armed:
                    self._diag['process_cleanup_verified']=not _children()
                    require(self._diag['process_cleanup_verified'],CODE)
                    _subreaper(False);require(_subreaper()==0,CODE)
            except Exception:failure=True
            except BaseException:failure=interrupted=True
            self._finished=time.monotonic()
            if armed:
                # Forks consume copies. Spend the original parent ports too,
                # only after both child attempts; never fabricate their proof.
                d,g,s,c,_=self._refs
                d.used=s.used=self._session.used=c._used=True
                d.stage=self._session.stage=s._status='outer-consumed'
                d.uncertain=self._session.uncertain=True
                g._failed=self._consumed=True
        if interrupted:raise KeyboardInterrupt from None
        require(not failure and main is not None and cleanup is not None
            and cleanup['runtime_revalidated'] is True
            and self._diag['process_cleanup_verified'] and self._finished<deadline,CODE)
        self._diag['staged_complete']=True
        report=dict(schema=SCHEMA,pins=deepcopy(self._pins),registry_digest=self._registry_digest,
            dispatch=main['dispatch'],dispatch_digest=digest(main['dispatch']),
            parent_cleanup=cleanup,elapsed_s=self._finished-self._started,
            main_reaped=True,cleanup_reaped=True,wrapper_deadline_enforced=True,process_cleanup_verified=True,
            daemon_cleanup_verified=cleanup['evidence']['transport']=='bounded-docker-cli',
            daemon_cleanup_authoritative=False,authoritative_fence_proven=False,source_unchanged_proven=False,
            a8_window_proven=False,ddl_authorized=False,operational_ready=False,provisioning_included=False)
        self._result_sha256=digest(report)
        return report

    def validate_result(self,result):
        try:
            self._bound()
            require(self._diag['staged_complete'] and self._result_sha256 is not None
                and type(result) is dict and digest(result)==self._result_sha256,CODE)
            return deepcopy(result)
        except Exception:raise Refused(CODE) from None

    def admit_operational(self):raise Refused('native-outer-authoritative-fence-missing')


class NativeProcessBoundary:
    """Two concrete consumers share the existing sole-reaper fork primitive.

    This context owns no Docker/C2 ports. The caller supplies absolute real
    monotonic deadlines and retains all command/registry decisions in the
    parent. A failed step may be followed by reserved cleanup only after its
    complete process tree is reaped. No child output grants resource authority.
    """
    _invoke=staticmethod(NativeOuterDispatch._invoke)
    _drain=NativeOuterDispatch._drain

    def __init__(self,*,stop_budget_s=.3):
        require(_number(stop_budget_s) and 0<stop_budget_s<=2,CODE)
        self.stop_budget=stop_budget_s;self._config=stop_budget_s
        self._used=self._active=False
        self._last_reaped=self._last_started=False
        self._uncertain=False
        self._owner_pid=os.getpid();self._role_owned=False

    @property
    def last_reaped(self):return self._last_reaped
    @property
    def last_started(self):return self._last_started

    def __enter__(self):
        require(not self._used and self._owner_pid==os.getpid(),CODE);self._used=True
        require(hasattr(os,'fork') and hasattr(signal,'pidfd_send_signal')
            and signal.getsignal(signal.SIGCHLD)==signal.SIG_DFL
            and len(os.listdir('/proc/self/task'))==1 and not _children() and _subreaper()==0,CODE)
        try:
            self._role_owned=True
            _subreaper(True)
            require(_subreaper()==1,CODE)
            self._active=True
            return self
        except BaseException as error:
            # __exit__ is never called when acquisition fails. The preflight
            # established zero; restore it even if SET succeeded then raised.
            self._active=False
            interrupted=not isinstance(error,Exception)
            try:self.recover()
            except Exception:pass
            except BaseException:interrupted=True
            if interrupted:raise KeyboardInterrupt from None
            raise Refused(CODE) from None

    def recover(self):
        """Restore only this PID's acquired role after a proven reaped tree."""
        require(self._used and self._owner_pid==os.getpid()
            and (not self._last_started or self._last_reaped) and not _children(),CODE)
        if self._role_owned:
            _subreaper(False);require(_subreaper()==0,CODE)
            self._role_owned=False
        else:require(_subreaper()==0,CODE)
        self._active=False

    def attempt(self,callback,*,deadline,input_fd=-1):
        require(self._active and not self._uncertain and self.stop_budget==self._config and callable(callback)
            and _number(deadline) and deadline-time.monotonic()>self.stop_budget
            and type(input_fd) is int and (input_fd==-1 or input_fd>2) and not _children(),CODE)
        try:
            return NativeOuterDispatch._attempt(self,callback,deadline=deadline,input_fd=input_fd)
        finally:
            if not self._last_reaped:self._uncertain=True

    def __exit__(self,*_error):
        require(self._active,CODE)
        self._active=False
        # attempt() already spent its stop budget. Do not silently extend the
        # caller's total deadline or detach an uninspectable surviving child.
        self.recover()
        return False
