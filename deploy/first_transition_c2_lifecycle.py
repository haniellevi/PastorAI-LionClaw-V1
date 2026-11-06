"""Fixture-only C2 lifecycle ownership, from admitted binding through release.

No import/constructor IO, CLI, host dispatch or operational authority is added.
The session owns only a fresh lease acquired by this run; a caller-owned lease
is never closed. Private initial observations stay inside the containment driver.
Injected fixture processes are mandatory; the marker is not a security boundary
against a dishonest caller. Recovery/exclusivity remain synthetic assertions.
"""

from copy import deepcopy
import math
import os
from pathlib import Path
import time

from first_transition_c2_containment import (
    BroadcastContainment,
    BroadcastRunner,
    GuardProof,
)
from first_transition_c2_guards import GuardAdmission, NativeC2Guard
from first_transition_c2_native import (
    INSPECT_TEMPLATE,
    NativeReadRunner,
    NativeSnapshotProducer,
)
from first_transition_c2_systemctl import SystemctlReadRunner
from first_transition_host_driver import INFO_ARGV, NETWORK_TEMPLATE, HostManifest
from initial_transition_files import is_protected
from initial_transition_ops import Refused

CODE = "c2-lifecycle-refused"
RESULT = {
    "status": "broadcast-held",
    "production_ready": False,
    "original_removed": False,
    "replacement_started": False,
    "operational_dispatch_enabled": False,
}
OBSERVER_FIELDS = (
    "_scope",
    "_target",
    "_image",
    "_name",
    "_intent",
    "_network_name",
    "_network_id",
    "_daemon_id",
    "_max_calls",
)
DOCKER_FIELDS = (
    "docker_binary",
    "endpoint",
    "config_dir",
    "cleanup_wait",
    "chunk",
    "resume",
)


def need(ok):
    if not ok:
        raise Refused(CODE)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class ContainmentSession:
    """One run, one lease owner, no retry or private snapshot export.

    Exact primitive types and their admitted identities are pinned before IO.
    Every callback revalidates those bindings. This is fixture composition only;
    no complete inventory, real recovery, global quiet or stop authorization is
    inferred. Cleanup always attempts release, even after cancellation/expiry.
    A failed/late release discards success and leaves uncertainty explicit.
    """

    def __init__(
        self,
        manifest,
        *,
        observer,
        guard,
        runner,
        enabled=False,
        synthetic_only=False,
        clock=time.monotonic,
        sleep=time.sleep,
        owner_uid=0,
    ):
        good = False
        try:
            need(
                type(manifest) is HostManifest
                and type(observer) is NativeSnapshotProducer
                and type(guard) is NativeC2Guard
                and type(runner) is BroadcastRunner
                and type(guard.admission) is GuardAdmission
                and type(observer._runner) is NativeReadRunner
                and type(guard.schedule.run) is SystemctlReadRunner
                and callable(clock)
                and callable(sleep)
                and type(owner_uid) is int
            )
            self.manifest = deepcopy(manifest.validated())
            self.observer, self.guard, self.runner = observer, guard, runner
            self._components = (observer, guard, runner)
            self._active = False
            self.enabled, self.synthetic_only = enabled, synthetic_only
            self.clock, self.sleep, self.owner_uid = clock, sleep, owner_uid
            self._clock, self._sleep_binding = clock, sleep
            self._scope = self.manifest.digest
            self._target = dict(self.manifest.service_ids)["broadcast-worker"]
            self._admission = deepcopy(guard.admission)
            self._deadline, self._nonce = (
                self._admission.deadline,
                self._admission.nonce,
            )
            self._state_root = Path(guard.state_root)
            need(
                self._state_root.is_absolute()
                and str(self._state_root) == os.path.normpath(self._state_root)
                and not str(self._state_root).startswith("//")
                and not is_protected(self._state_root.parts)
            )
            self._reader, self._scheduler = observer._runner, guard.schedule.run
            self._observer_values = tuple(
                deepcopy(getattr(observer, k)) for k in OBSERVER_FIELDS
            )
            self._reader_values = tuple(getattr(self._reader, k) for k in DOCKER_FIELDS)
            self._runner_values = tuple(getattr(runner, k) for k in DOCKER_FIELDS)
            self._popen = (self._reader.popen, runner.popen, self._scheduler._popen)
            self._sources = guard._sources
            self._guard_bindings = guard._bindings
            self._expected_database = deepcopy(guard.expected)
            self._policy = guard.schedule.cron_policy
            self._scheduler_values = (
                self._scheduler.units,
                self._scheduler._deadline,
                self._scheduler._max_calls,
            )
            self.used = self.uncertain = False
            self.stage = "not-started"
            self._last = None
            self._bound()
            good = True
        except Exception:
            pass
        if not good:
            raise Refused(CODE)

    def __repr__(self):
        return "<ContainmentSession private, fixture-only, no production admission>"

    def _bound(self):
        o, g, r, s = self.observer, self.guard, self.runner, self._scheduler
        need(
            o is self._components[0]
            and g is self._components[1]
            and r is self._components[2]
            and type(o) is NativeSnapshotProducer
            and type(g) is NativeC2Guard
            and type(r) is BroadcastRunner
            and type(o._runner) is NativeReadRunner
            and type(g.schedule.run) is SystemctlReadRunner
            and self.manifest.validated().digest == self._scope
            and o._manifest.validated().digest == self._scope
            and o._manifest_digest == self._scope == o._scope == g.admission.scope
            and o._target == self._target == g.admission.target_id == r.original_id
            and g.admission == self._admission
            and Path(g.state_root) == self._state_root
            and g.owner_uid == self.owner_uid
            and o._deadline == self._deadline == s._deadline
            and self.clock
            is self._clock
            is o._clock
            is g.clock
            is g.schedule.clock
            is s._clock
            and self.sleep is self._sleep_binding
            and o._runner is self._reader
            and g.schedule.run is s
            and g.schedule.cron_policy is self._policy
            and g.expected == self._expected_database
            and g._sources == self._sources
            and len(g._bindings) == len(self._guard_bindings)
            and all(a is b for a, b in zip(g._bindings, self._guard_bindings))
            and tuple(getattr(o, k) for k in OBSERVER_FIELDS) == self._observer_values
            and tuple(getattr(self._reader, k) for k in DOCKER_FIELDS)
            == self._reader_values
            and tuple(getattr(r, k) for k in DOCKER_FIELDS) == self._runner_values
            and self._reader_values[:3] == self._runner_values[:3]
            and self._reader.resume is False
            and r.resume is False
            and self._reader.popen is self._popen[0] is r.popen
            and r.popen is self._popen[1]
            and s._popen is self._popen[2]
            and all(callable(p) for p in self._popen)
            and (s.units, s._deadline, s._max_calls) == self._scheduler_values
            and s.units == g.schedule.units
        )
        expected = (
            INFO_ARGV,
            (
                "docker",
                "inspect",
                "--type",
                "container",
                "--format",
                INSPECT_TEMPLATE,
                self._target,
            ),
            (
                "docker",
                "network",
                "inspect",
                "--format",
                NETWORK_TEMPLATE,
                self.manifest.network_id,
            ),
            (
                "docker",
                "network",
                "inspect",
                "--format",
                NETWORK_TEMPLATE,
                o._network_name,
            ),
        )
        need(self._reader._commands == expected)
        if self._active:
            self._sealed()

    def _sealed(self):
        need(
            self.enabled is True
            and self.synthetic_only is True
            and self.observer._enabled is True
            and self._reader.enabled is True
            and self.guard.enabled is True
            and self.guard.synthetic_only is True
            and self.guard.schedule.enabled is True
            and self.guard.schedule.synthetic_only is True
            and self._scheduler._enabled is True
            and self._scheduler._synthetic_only is True
        )

    def _now(self):
        now = self._clock()
        need(
            finite(now)
            and finite(self._deadline)
            and (self._last is None or now >= self._last)
            and now < self._deadline
        )
        if self._last is None:
            need(self._deadline <= now + 60)
        self._last = now
        return now

    def _fresh(self):
        self._bound()
        o, g, s = self.observer, self.guard, self._scheduler
        need(
            self.enabled is True
            and self.synthetic_only is True
            and self.owner_uid == os.geteuid()
            and o._enabled is True
            and self._reader.enabled is True
            and g.enabled is True
            and g.synthetic_only is True
            and g.schedule.enabled is True
            and g.schedule.synthetic_only is True
            and s._enabled is True
            and s._synthetic_only is True
            and o._failed is False
            and g._failed is False
            and s._failed is False
            and o._calls == 0
            and o._began is None
            and o._last is None
            and o._original_image_reference is None
            and s._calls == 0
            and s._began is None
            and s._last is None
            and g.root is None
            and g.lease is None
            and g._last is None
            and g._last_wall is None
            and self._reader.unreaped == 0
            and self.runner.unreaped == 0
            and s.unreaped == 0
        )
        self._now()

    def _proof(self, scope, nonce):
        self._bound()
        self._now()
        need(scope == self._scope and nonce == self._nonce)
        proof = self._components[1](scope, nonce)
        now = self._now()
        self._bound()
        need(
            type(proof) is GuardProof
            and proof.scope == scope
            and proof.nonce == nonce
            and finite(proof.checked_at)
            and finite(proof.expires_at)
            and 0 <= now - proof.checked_at <= 1
            and now < proof.expires_at <= self._deadline
            and proof.exclusive
            is proof.baseline_current
            is proof.cron_window_clear
            is proof.backup_recovery_ready
            is True
            and proof.ddl_started is False
        )
        return proof

    def _observe(self, target):
        self._bound()
        self._now()
        need(target == self._target)
        snapshot = self._components[0](target)
        self._now()
        self._bound()
        return snapshot

    def _run_cli(self, argv, **bounds):
        self._bound()
        self._now()
        value = self._components[2](argv, **bounds)
        self._now()
        self._bound()
        return value

    def _sleep_port(self, delay):
        self._bound()
        self._now()
        self._sleep_binding(delay)
        self._now()
        self._bound()

    def run(self):
        owned, driver, result = False, None, None
        owned_lease = owned_root = owned_guard = owned_close = None
        failed, interrupted, cleanup_failed = False, None, False
        try:
            need(self.used is False)
            self.used = True
            self._fresh()
            self._active = True
            self._bound()
            self.stage = "acquire"
            owned_guard = self._components[1]
            owned_close = owned_guard.close
            owned = True
            need(owned_guard.acquire() is owned_guard)
            owned_lease, owned_root = owned_guard.lease, owned_guard.root
            self._proof(self._scope, self._nonce)
            self.stage = "snapshot"
            original = self._observe(self._target)
            self._proof(self._scope, self._nonce)
            self.stage = "containment"
            driver = BroadcastContainment(
                self.manifest,
                original=original,
                observe=self._observe,
                guard=self._proof,
                runner=self._run_cli,
                state_root=self._state_root,
                nonce=self._nonce,
                deadline=self._deadline,
                enabled=True,
                clock=self.clock,
                sleep=self._sleep_port,
                owner_uid=self.owner_uid,
            )
            result = driver.run()
            need(type(result) is dict and result == RESULT)
            self._proof(self._scope, self._nonce)
        except Exception:
            failed = True
        except BaseException as exc:
            interrupted = exc
        finally:
            if owned:
                self.stage = "release"

                def released():
                    need(owned_guard.root is None and owned_guard.lease is None)
                    need(owned_lease is None or owned_lease.fd is None)
                    need(owned_root is None or not owned_root.fds)

                for action in (
                    self._now,
                    owned_close,
                    released,
                    self._bound,
                    self._now,
                ):
                    try:
                        action()
                    except Exception:
                        failed = cleanup_failed = True
                    except BaseException as exc:
                        interrupted = interrupted or exc
                        cleanup_failed = True
        if failed or interrupted is not None:
            self.uncertain = (
                self.uncertain
                or cleanup_failed
                or bool(
                    driver
                    and (
                        driver.uncertain
                        or driver.stage not in ("not-started", "custody")
                    )
                )
            )
            self.stage = "refused"
        if interrupted is not None:
            raise interrupted
        if failed:
            raise Refused(CODE)
        self.stage = "held"
        self.uncertain = False
        return {**result, "lease_released": True}
