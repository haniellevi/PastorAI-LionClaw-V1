"""Single-use glue for the isolated joint core; no production entry point.

TLS context and numeric endpoint addresses must be prepared before the holder
opens. HTTP waits invoke the caller's Pulse and the same bound window guard on
the calling thread. Guards remain trusted external dependencies, not authority
created by this adapter. No connection/config/token discovery or file output.
"""
import time

from first_transition_native_joint_capture import Collector, WindowEvidence, finite
from first_transition_native_http_reader import HTTPReader


class Refused(ValueError):
    pass


class A8HTTPHook:
    def __init__(self, *, request_sha256, source_sha256, window_sha256,
                 preserved_objects, token, endpoint, context, guard, state_reader):
        self._request=request_sha256
        self._source=source_sha256
        self._window=window_sha256
        self._guard=guard
        self._active=None
        self._used=False
        # Constructor validates TLS/endpoint policy outside the transaction.
        # It must not connect or invoke the not-yet-bound checkpoint.
        self._reader=HTTPReader(token=token,endpoint=endpoint,context=context,
                                checkpoint=self._checkpoint)
        self._collector=Collector(request_sha256,source_sha256,window_sha256,
                                  preserved_objects,self._reader,guard,state_reader)

    def __repr__(self):
        return 'A8HTTPHook(private configuration)'

    def _checkpoint(self):
        if self._active is None:
            raise Refused('a8-http-unbound')
        pulse,deadline,started=self._active
        if time.monotonic()>=deadline:
            raise Refused('a8-http-deadline')
        try:
            pulse()
        except Exception:
            raise Refused('a8-http-pulse') from None
        try:
            value=self._guard(self._request,self._source,self._window,started,deadline)
        except Exception:
            raise Refused('a8-http-window') from None
        now=time.time()
        if not (type(value) is WindowEvidence and value.allowed is True
                and (value.request_sha256,value.source_sha256,value.window_sha256)
                ==(self._request,self._source,self._window)
                and finite(value.interval_started_at) and finite(value.valid_until)
                and value.interval_started_at<=started<=now<value.valid_until):
            raise Refused('a8-http-window')
        if time.monotonic()>=deadline:
            raise Refused('a8-http-deadline')
        try:
            pulse()
        except Exception:
            raise Refused('a8-http-pulse') from None

    def __call__(self, *, holder, source_identity_sha256, snapshot, dump,
                 pulse, deadline, capture_started_at):
        if self._used:
            raise Refused('a8-http-attempt-used')
        self._used=True
        if (source_identity_sha256!=self._source or not callable(pulse)
                or not finite(deadline) or not finite(capture_started_at)):
            raise Refused('a8-http-source-or-budget')
        self._active=(pulse,deadline,capture_started_at)
        try:
            self._checkpoint()
            return self._collector(holder=holder,source_identity_sha256=source_identity_sha256,
                snapshot=snapshot,dump=dump,pulse=pulse,deadline=deadline,
                capture_started_at=capture_started_at)
        finally:
            self._active=None
