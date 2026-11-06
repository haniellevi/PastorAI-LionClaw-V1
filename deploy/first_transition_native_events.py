"""Locally observed native-job events, never proof of absent source writers.

Only trusted execution calls advance phases. There is no event deserializer or
caller-supplied timestamp API. Client closure means local frontend handles and
the dump process finished; it does not attest server backend disappearance.
``request`` observes local job acceptance, not the controller's receipt time.
"""
from copy import deepcopy
import hashlib
import json
import math
import re
import time

from initial_transition_ops import Refused, require

SCHEMA = 'igreja12.native-window-events/1'
CODE = 'native-job-events-invalid'
PHASES = ('request', 'capture-start', 'source-frontends-closed', 'capture-finish',
          'recovery-start', 'recovery-finish', 'cleanup-finish', 'result')
DRIFT_S = 2.0


class NativeWindowEvents:
    """Single execution, bound to a request/context; clocks are trusted IO seams.

Monotonic elapsed time enforces budgets. Wall time must progress consistently
within two seconds, including accumulated drift from the first observation.
Equal timestamps are allowed for coarse clocks; no artificial time is added.
"""
    def __init__(self, request_digest, context_digest, *, clock=None, wall_clock=None):
        require(all(type(value) is str and re.fullmatch('[0-9a-f]{64}', value)
                    for value in (request_digest, context_digest))
                and (clock is None or callable(clock)) and (wall_clock is None or callable(wall_clock)), CODE)
        self._request, self._context = request_digest, context_digest
        self._clock = time.monotonic if clock is None else clock
        self._wall = time.time if wall_clock is None else wall_clock
        self._events, self._failed = [], False
        self._first = self._last = None
        self._record('request')

    def _observe(self):
        wall, mono = self._wall(), self._clock()
        require(type(wall) in (int, float) and math.isfinite(wall) and wall > 0
                and type(mono) in (int, float) and math.isfinite(mono) and mono >= 0, CODE)
        if self._first is None:
            self._first = (wall, mono)
        if self._last is not None:
            require(wall >= self._last[0] and mono >= self._last[1]
                    and abs((wall-self._last[0])-(mono-self._last[1])) <= DRIFT_S, CODE)
        elapsed = mono-self._first[1]
        require(abs((wall-self._first[0])-elapsed) <= DRIFT_S and elapsed <= 1200, CODE)
        self._last = (wall, mono)
        return wall, elapsed

    def _record(self, phase):
        require(not self._failed, CODE)
        try:
            require(len(self._events) < len(PHASES) and PHASES[len(self._events)] == phase, CODE)
            wall, elapsed = self._observe()
            observed = {event['phase']: event['elapsed_s'] for event in self._events}
            if phase == 'capture-start':
                require(elapsed <= 60, CODE)
            if 'capture-start' in observed and 'capture-finish' not in observed:
                require(elapsed <= 240 and elapsed-observed['capture-start'] <= 240, CODE)
            if phase == 'recovery-start':
                require(elapsed-observed['capture-finish'] <= 60, CODE)
            if phase == 'cleanup-finish':
                require(elapsed-observed['recovery-finish'] <= 60, CODE)
            if phase == 'result':
                require(elapsed-observed['cleanup-finish'] <= 60, CODE)
            self._events.append(dict(sequence=len(self._events), phase=phase,
                                     wall_at=wall, elapsed_s=elapsed))
        except Exception:
            self._failed = True
            raise Refused(CODE) from None
        except BaseException:
            self._failed = True
            raise KeyboardInterrupt from None

    def capture_start(self):self._record('capture-start')
    def source_frontends_closed(self):self._record('source-frontends-closed')
    def capture_finish(self):self._record('capture-finish')
    def recovery_start(self):self._record('recovery-start')
    def recovery_finish(self):self._record('recovery-finish')
    def cleanup_finish(self):self._record('cleanup-finish')
    def result(self):self._record('result')

    def public(self):
        """Complete immutable-by-copy observations, without payloads or endpoints."""
        require(not self._failed and len(self._events) == len(PHASES), CODE)
        try:
            _, elapsed = self._observe()
            require(elapsed-self._events[-2]['elapsed_s'] <= 60, CODE)
        except Exception:
            self._failed = True
            raise Refused(CODE) from None
        except BaseException:
            self._failed = True
            raise KeyboardInterrupt from None
        return dict(schema=SCHEMA, request_digest=self._request, context_digest=self._context,
                    events=deepcopy(self._events), source_unchanged_proven=False,
                    writer_absence_proven=False, source_state_equality_proven=False,
                    a8_window_proven=False)

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(self.public(), sort_keys=True, separators=(',', ':'),
                                         allow_nan=False).encode()).hexdigest()
