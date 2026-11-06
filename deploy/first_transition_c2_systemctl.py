"""Fixture-gated, bounded transport for nominal systemd timer observations.

Only the declared ``systemctl show`` grammar is accepted. This module does not
admit a host, create an ACP/model session, prove schedule completeness or change
systemd state. The synthetic marker is a test contract, not a security boundary
against a dishonest caller. Production wiring and authorization remain absent.
"""

import math
import os
import re
import select
import subprocess
import time

from initial_transition_ops import Refused

CODE = "c2-systemctl-read-refused"
UNIT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}\.timer")
PROPERTIES = "Id,LoadState,ActiveState,UnitFileState"
PREFIX = ("/usr/bin/systemctl", "show", "--no-pager", "--property=" + PROPERTIES)
CAP = 4096
ENV = {
    "PATH": "/usr/bin:/bin",
    "LC_ALL": "C",
    "SYSTEMD_PAGER": "cat",
    "SYSTEMD_PAGERSECURE": "1",
    "SYSTEMD_COLORS": "0",
    "SYSTEMD_URLIFY": "0",
}


def need(ok):
    if not ok:
        raise Refused(CODE)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class SystemctlReadRunner:
    """Single-budget, no-retry reader; never kill a systemd service or peer.

    The child receives no inherited HOME, bus address, credentials or pager
    settings. Output is private: stderr is bounded/discarded and any nonempty
    stderr, nonzero exit or uncertain cleanup refuses. Cleanup ends only this
    invocation's CLI child and waits at most one second. Any ordinary failure or
    cancellation seals the object against further observations.
    """

    def __init__(
        self,
        units,
        *,
        deadline,
        enabled=False,
        synthetic_only=False,
        clock=time.monotonic,
        popen=None,
        max_calls=128,
    ):
        need(
            type(units) in (tuple, list)
            and 1 <= len(units) <= 128
            and all(type(u) is str and UNIT.fullmatch(u) for u in units)
            and len(set(units)) == len(units)
            and finite(deadline)
            and callable(clock)
            and (popen is None or callable(popen))
            and type(max_calls) is int
            and 1 <= max_calls <= 1024
        )
        self._units = tuple(units)
        self._deadline = deadline
        self._enabled, self._synthetic_only = enabled, synthetic_only
        self._clock, self._popen = clock, popen
        self._max_calls, self._calls = max_calls, 0
        self._began = self._last = None
        self._failed = False
        self.unreaped = 0

    @property
    def units(self):
        return self._units

    def __repr__(self):
        return "<SystemctlReadRunner fixture-gated, no production admission>"

    def _now(self):
        now = self._clock()
        need(
            finite(now)
            and (self._last is None or now >= self._last)
            and now < self._deadline
        )
        if self._began is None:
            self._began = now
        need(self._deadline <= self._began + 60)
        self._last = now
        return now

    def _remaining(self, end):
        remaining = end - self._now()
        need(remaining > 0)
        return remaining

    def _read(self, proc, end, limit):
        stdout, stderr = proc.stdout.fileno(), proc.stderr.fileno()
        need(
            type(stdout) is int
            and type(stderr) is int
            and stdout >= 0
            and stderr >= 0
            and stdout != stderr
        )
        active = {stdout, stderr}
        sizes = {stdout: 0, stderr: 0}
        limits = {stdout: limit, stderr: CAP}
        chunks = []
        while active:
            ready = select.select(sorted(active), [], [], self._remaining(end))[0]
            need(ready and all(fd in active for fd in ready))
            for fd in ready:
                self._remaining(end)
                chunk = os.read(fd, min(1024, limits[fd] + 1 - sizes[fd]))
                if not chunk:
                    active.remove(fd)
                    continue
                sizes[fd] += len(chunk)
                need(sizes[fd] <= limits[fd])
                if fd == stdout:
                    chunks.append(chunk)
        return b"".join(chunks), sizes[stderr]

    def _cleanup(self, proc):
        """Always attempt wait, even if inspecting/killing our child failed."""
        failed, interrupted = False, None
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            failed = True
        except BaseException as exc:
            interrupted = exc
        try:
            proc.wait(timeout=1.0)
        except Exception:
            failed = True
        except BaseException as exc:
            interrupted = interrupted or exc
        if failed or interrupted is not None:
            self.unreaped += 1
        return interrupted

    def __call__(self, argv, *, timeout, max_output):
        proc = None
        failed, interrupted, result = False, None, None
        try:
            need(
                self._failed is False
                and self.unreaped == 0
                and self._enabled is True
                and self._synthetic_only is True
                and type(argv) in (tuple, list)
                and len(argv) == 5
                and all(type(part) is str for part in argv)
                and tuple(argv[:4]) == PREFIX
                and argv[4] in self._units
                and finite(timeout)
                and 0 < timeout <= 60
                and type(max_output) is int
                and 0 < max_output <= CAP
                and self._calls < self._max_calls
            )
            now = self._now()
            end = min(now + timeout, self._deadline)
            self._calls += 1
            factory = self._popen or subprocess.Popen
            proc = factory(
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=dict(ENV),
                cwd="/",
                close_fds=True,
                shell=False,
                start_new_session=True,
                bufsize=0,
            )
            need(proc is not None)
            out, errors = self._read(proc, end, max_output)
            rc = proc.wait(timeout=self._remaining(end))
            self._remaining(end)
            need(type(rc) is int and rc == 0 and errors == 0)
            result = rc, out
        except Exception:
            failed = True
        except BaseException as exc:
            interrupted = exc
        finally:
            if proc is not None:
                for name in ("stdout", "stderr"):
                    try:
                        getattr(proc, name).close()
                    except Exception:
                        failed = True
                    except BaseException as exc:
                        interrupted = interrupted or exc
                if not failed and interrupted is None:
                    # Stream closure is part of the same observation budget.
                    # A late close must never turn a stale read into success.
                    try:
                        self._remaining(end)
                    except Exception:
                        failed = True
                    except BaseException as exc:
                        interrupted = exc
                if failed or interrupted is not None:
                    cleanup_interrupt = self._cleanup(proc)
                    interrupted = interrupted or cleanup_interrupt
        if failed or interrupted is not None:
            self._failed = True
        if interrupted is not None:
            raise interrupted
        if failed:
            # Raise outside all except blocks: private child errors have no context.
            raise Refused(CODE)
        return result
