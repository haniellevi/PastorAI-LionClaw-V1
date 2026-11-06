"""C2-to-capture dispatcher over explicit, fixture-admitted bound ports.

No CLI, nominal admission, source mutation or implicit rollback is provided.
C2 owns lease release; the capture supervisor owns worker/cleanup attempts.
The result is a staged receipt, never a source fence or OriginReceipt.
"""
from copy import deepcopy
from dataclasses import asdict
import fcntl
import os
import stat

from first_transition_adapter import digest
from first_transition_native_gates import NativeDispatchGates
from first_transition_native_supervision import NativeCleanupObservation
from initial_transition_ops import Refused,require

CODE='native-c2-dispatch-failed'


class NativeC2Dispatcher:
    def __init__(self,gates):
        require(type(gates) is NativeDispatchGates,CODE)
        self.gates=gates
        self._gates=gates;self._session=gates.c2_session;self._supervisor=gates.supervisor
        self._pins=digest(asdict(gates.pins));self._clock=gates.clock;self._wall=gates.wall_clock
        self.used=self.uncertain=False
        self.stage='not-started';self._result_sha256=None;self._supervised=None

    def __repr__(self):return '<NativeC2Dispatcher private, no operational admission>'

    def _bound(self):
        require(self.gates is self._gates and self.gates.c2_session is self._session
            and self.gates.supervisor is self._supervisor and self.gates.clock is self._clock
            and self.gates.wall_clock is self._wall and digest(asdict(self.gates.pins))==self._pins,CODE)
        self.gates.remaining_s()

    @staticmethod
    def _input(fd):
        require(type(fd) is int and fd>2,CODE)
        row=os.fstat(fd)
        require(stat.S_ISREG(row.st_mode) and 0<row.st_size<=2097152 and fcntl.fcntl(fd,1034)&15==15,CODE)
        require(fcntl.fcntl(fd,fcntl.F_GETFL)&os.O_ACCMODE in (os.O_RDONLY,os.O_RDWR),CODE)
        return tuple(getattr(row,k) for k in ('st_dev','st_ino','st_uid','st_mode','st_size','st_mtime_ns','st_ctime_ns'))

    def run(self,*,input_fd):
        require(not self.used,'native-c2-dispatch-used');self.used=True
        interrupted=False;capture_started=False
        try:
            self._bound();input_pin=self._input(input_fd)
            self.gates.c2_start();self.stage='c2-dispatching'
            c2=self._session.run()
            self._bound()
            self.gates.c2_held(c2,scope=self._session.manifest.digest,
                target=dict(self._session.manifest.service_ids)['broadcast-worker'],nonce=self._session.guard.admission.nonce)
            self.stage='c2-held'
            require(self._input(input_fd)==input_pin,CODE)
            self.gates.capture_start();capture_started=True;self.stage='capture-dispatching'
            result=self._supervisor.run(deepcopy(self.gates.request),deepcopy(self.gates.context),input_fd=input_fd)
            self._bound();require(self._input(input_fd)==input_pin,CODE)
            self.gates.capture_validated(result)
            observation=NativeCleanupObservation(**result['cleanup_observation'])
            self.gates.cleanup_validated(observation)
            receipt=self.gates.finish()
            report=dict(schema='igreja12.native-c2-dispatch-result/1',receipt=receipt,receipt_digest=digest(receipt),
                c2_digest=digest(c2),supervised_digest=digest(result),
                source_unchanged_proven=False,fence_verified=False,ddl_authorized=False,
                operational_dispatch_enabled=False,a8_window_proven=False,operational_ready=False,
                cleanup_hard_deadline_verified=False,requires_dedicated_outer_process=True)
            self._supervised=deepcopy(result);self._result_sha256=digest(report)
            self.stage='staged-complete';self.uncertain=False
            return report
        except Exception:
            pass
        except BaseException:
            interrupted=True
        self.stage='refused'
        self.uncertain=bool(capture_started or getattr(self._session,'uncertain',True)
            or self._session.used and self._session.stage not in ('not-started','held'))
        if interrupted:raise KeyboardInterrupt from None
        raise Refused(CODE)

    def validate_result(self,result):
        try:
            self._bound()
            require(self.stage=='staged-complete' and self._result_sha256 is not None
                and type(result) is dict and digest(result)==self._result_sha256,CODE)
            self._supervisor.validate_report(self._supervised)
            return deepcopy(result)
        except Exception:
            raise Refused('native-c2-dispatch-result-binding') from None

    def admit_operational(self):
        """Must fail before dispatching any host, source or cleanup port."""
        raise Refused('native-c2-dispatch-authoritative-fence-missing')

    def origin_receipt(self):
        raise Refused('native-c2-dispatch-authoritative-fence-missing')
