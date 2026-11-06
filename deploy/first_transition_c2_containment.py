"""Opt-in containment of one pinned legacy broadcast; no recreation or restart.

Nothing executes on import/construction. The native runner can only query daemon
identity, disable restart and send TERM to the manifest's broadcast ID. Complete
private observations and fresh exclusion/baseline/cron/recovery evidence remain
explicit trusted producer obligations. Their assertions are NOT human approval.
No CLI or operational host/controller dispatch is added here.
"""

from copy import deepcopy
from dataclasses import dataclass, field
import json
import math
import os
import re
from pathlib import Path
import stat
import time

from first_transition_adapter import digest
from first_transition_c2_adapter import Observation, checked_config, encoded, profile
from first_transition_host_driver import INFO_ARGV, STARTED, PopenRunner
from initial_transition_files import is_protected
from initial_transition_ops import Refused

CODE = "c2-containment-refused"


def need(ok):
    if not ok:
        raise Refused(CODE)


@dataclass(frozen=True, repr=False)
class Snapshot:
    observation: Observation = field(repr=False)
    name: str
    started_at: str
    restart_count: int


@dataclass(frozen=True)
class GuardProof:
    scope: str
    nonce: str
    checked_at: float
    expires_at: float
    exclusive: bool = False
    baseline_current: bool = False
    cron_window_clear: bool = False
    backup_recovery_ready: bool = False
    ddl_started: bool = True


class BroadcastRunner(PopenRunner):
    """Future authorized CLI transport, restricted to this one original ID.

    Uses the existing bounded runner/minimal environment. Its timeout cleanup
    concerns only its own CLI process, not the worker. No stop/start/create/rm.
    """

    def __init__(self, *, manifest, **kwargs):
        self.original_id = dict(manifest.validated().service_ids)["broadcast-worker"]
        need("resume" not in kwargs)
        super().__init__(resume=False, **kwargs)

    def _allowed(self, argv):
        return tuple(argv) in (
            INFO_ARGV,
            ("docker", "update", "--restart=no", self.original_id),
            ("docker", "kill", "--signal=TERM", self.original_id),
        )


class PrivateJournal:
    """Exclusive per-target directory. A failed/complete attempt is never replayed.

    state_root must already exist. The lock is the exclusive directory creation;
    no journal repair, removal, automatic rollback or alternate attempt path.
    Root-path binding is an admitted operator input, not a global host lock.
    """

    def __init__(self, state_root, target_id, owner_uid):
        self.fd = self.events = None
        need(type(target_id) is str and re.fullmatch("[0-9a-f]{64}", target_id))
        root = Path(state_root)
        need(
            root.is_absolute()
            and str(root) == os.path.normpath(root)
            and not is_protected(root.parts)
        )
        parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        root_uid = os.fstat(parent).st_uid
        try:
            for part in root.parts[1:]:
                fd = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
                )
                s = os.fstat(fd)
                need(
                    not {"system.posix_acl_access", "system.posix_acl_default"}
                    & set(os.listxattr(fd))
                )
                sticky = (
                    s.st_uid == root_uid
                    and bool(s.st_mode & stat.S_ISVTX)
                    and part in ("tmp", "var/tmp")
                )
                need(
                    s.st_uid in (root_uid, owner_uid)
                    and (not s.st_mode & 0o022 or sticky)
                )
                os.close(parent)
                parent = fd
            name = "broadcast-" + target_id
            os.mkdir(name, 0o700, dir_fd=parent)
            self.fd = os.open(
                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
            )
            need(
                not {"system.posix_acl_access", "system.posix_acl_default"}
                & set(os.listxattr(self.fd))
            )
            os.fchmod(self.fd, 0o700)
            need(os.fstat(self.fd).st_uid == owner_uid)
            os.fsync(parent)
            self.events = os.open(
                "events.jsonl",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=self.fd,
            )
            os.fchmod(self.events, 0o600)
            os.fsync(self.events)
            os.fsync(self.fd)
        except BaseException:
            self.close()
            raise
        finally:
            os.close(parent)

    @staticmethod
    def _write(fd, data):
        rest = memoryview(data)
        while rest:
            n = os.write(fd, rest)
            need(n > 0)
            rest = rest[n:]
        os.fsync(fd)

    def save(self, snapshot):
        row = snapshot.observation
        body = encoded(
            dict(
                container_id=row.container_id,
                daemon_id=row.daemon_id,
                image_id=row.image_id,
                name=snapshot.name,
                started_at=snapshot.started_at,
                restart_count=snapshot.restart_count,
                network_intent_sha256=row.network_intent_sha256,
                private_config=row.private_config,
            )
        )
        fd = os.open(
            "before.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self.fd,
        )
        try:
            os.fchmod(fd, 0o600)
            self._write(fd, body)
        finally:
            os.close(fd)
        os.fsync(self.fd)

    def append(self, kind, step):
        need(
            kind in ("intent", "confirmed", "complete")
            and step in ("restart-no", "term", "held")
        )
        self._write(self.events, encoded({"kind": kind, "step": step}) + b"\n")
        os.fsync(self.fd)

    def close(self):
        for name in ("events", "fd"):
            value = getattr(self, name, None)
            if value is not None:
                os.close(value)
                setattr(self, name, None)


class BroadcastContainment:
    """Containment-only operational orchestration with injected native producers.

    Native use is closed by default. enabled=True is an accident guard, never
    authorization; the future operator must separately admit the exact scope,
    protected config access and stop. GuardProof values are trusted assertions,
    not measurements made by this class. Private observation callbacks must not
    mutate the host. Snapshot/running facts are revalidated around every effect.
    """

    def __init__(
        self,
        manifest,
        *,
        original,
        observe,
        guard,
        runner,
        state_root,
        nonce,
        deadline,
        enabled=False,
        clock=time.monotonic,
        sleep=time.sleep,
        owner_uid=0,
        journal_factory=PrivateJournal,
    ):
        self.manifest = manifest.validated()
        self.original = deepcopy(original)
        self.observe, self.guard, self.runner = observe, guard, runner
        self.state_root, self.nonce, self.deadline = state_root, nonce, deadline
        self.enabled, self.clock, self.sleep = enabled, clock, sleep
        self.owner_uid, self.journal_factory = owner_uid, journal_factory
        self.used = False
        self.uncertain = False
        self.stage = "not-started"
        self._last_time = None

    def _now(self):
        now = self.clock()
        need(
            type(now) in (int, float)
            and math.isfinite(now)
            and (self._last_time is None or now >= self._last_time)
            and type(self.deadline) in (int, float)
            and math.isfinite(self.deadline)
            and now < self.deadline
        )
        self._last_time = now
        return now

    def _guard(self):
        self._now()
        proof = self.guard(self.manifest.digest, self.nonce)
        now = self._now()
        need(
            type(proof) is GuardProof
            and proof.scope == self.manifest.digest
            and proof.nonce == self.nonce
            and type(proof.checked_at) in (int, float)
            and math.isfinite(proof.checked_at)
            and type(proof.expires_at) in (int, float)
            and math.isfinite(proof.expires_at)
            and 0 <= now - proof.checked_at <= 1
            and now < proof.expires_at <= self.deadline
            and all(
                v is True
                for v in (
                    proof.exclusive,
                    proof.baseline_current,
                    proof.cron_window_clear,
                    proof.backup_recovery_ready,
                )
            )
            and proof.ddl_started is False
        )

    def _call(self, action):
        self._guard()
        value = action()
        self._guard()
        return value

    def _daemon(self):
        rc, out = self._call(
            lambda: self.runner(
                INFO_ARGV, timeout=min(10, self.deadline - self._now()), max_output=256
            )
        )
        need(rc == 0 and len(out) <= 256 and json.loads(out) == self.manifest.daemon_id)

    def _validate(self, value, *, held_policy=False, exited=False):
        need(type(value) is Snapshot and type(self.original) is Snapshot)
        row, initial = value.observation, self.original.observation
        profile(row)
        profile(initial)
        need(
            initial.container_id == dict(self.manifest.service_ids)["broadcast-worker"]
            and initial.daemon_id == self.manifest.daemon_id
            and value.name == self.original.name
            and type(value.name) is str
            and re.fullmatch(r"/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value.name)
            and isinstance(value.started_at, str)
            and STARTED.fullmatch(value.started_at)
            and value.started_at == self.original.started_at
            and type(value.restart_count) is int
            and value.restart_count >= 0
            and value.restart_count == self.original.restart_count
            and (
                row.container_id,
                row.daemon_id,
                row.image_id,
                row.role,
                row.network_intent_sha256,
            )
            == (
                initial.container_id,
                initial.daemon_id,
                initial.image_id,
                initial.role,
                initial.network_intent_sha256,
            )
        )
        wanted = checked_config(initial.private_config)
        endpoints = wanted["NetworkingConfig"].get("EndpointsConfig")
        need(
            type(endpoints) is dict
            and len(endpoints) == 1
            and all(
                type(e) is dict and e.get("NetworkID") == self.manifest.network_id
                for e in endpoints.values()
            )
            and initial.network_intent_sha256 == digest(wanted["NetworkingConfig"])
            and wanted["Config"].get("Image") == initial.image_id
        )
        if held_policy:
            wanted["HostConfig"]["RestartPolicy"] = {
                "Name": "no",
                "MaximumRetryCount": 0,
            }
        need(encoded(row.private_config) == encoded(wanted))
        labels = row.private_config["Config"].get("Labels") or {}
        need(
            type(labels) is dict
            and not labels.get("com.docker.compose.project")
            and not labels.get("com.docker.compose.service")
        )
        if exited:
            need(
                row.running is False
                and row.status == "exited"
                and type(row.exit_code) is int
                and row.exit_code == 0
            )
        else:
            need(
                row.running is True
                and row.status == "running"
                and row.effective_network_verified is True
            )
        return value

    def _observe(self, *, held_policy=False, exited=False):
        value = self._call(
            lambda: self.observe(dict(self.manifest.service_ids)["broadcast-worker"])
        )
        return self._validate(value, held_policy=held_policy, exited=exited)

    def _effect(self, journal, step, argv):
        self.stage = step
        self.uncertain = True
        self._call(lambda: journal.append("intent", step))
        self._guard()
        self._daemon()
        rc, out = self._call(
            lambda: self.runner(
                argv, timeout=min(10, self.deadline - self._now()), max_output=256
            )
        )
        need(rc == 0 and out.decode().strip() == self.original.observation.container_id)
        # ACK alone is not a postcondition; caller confirms after observation.

    def run(self):
        journal = None
        failed, interrupted, result = False, None, None
        try:
            need(self.used is False)
            self.used = True
            need(
                self.enabled is True
                and type(self.nonce) is str
                and 0 < len(self.nonce) <= 128
                and type(self.owner_uid) is int
                and self.owner_uid == os.geteuid()
                and callable(self.observe)
                and callable(self.guard)
                and callable(self.runner)
            )
            now = self._now()
            need(self.deadline <= now + 60)
            self._guard()
            self._validate(self.original)
            self._daemon()
            self._observe()
            self.stage = "custody"
            self._guard()
            journal = self.journal_factory(
                self.state_root, self.original.observation.container_id, self.owner_uid
            )
            self._guard()
            self._call(lambda: journal.save(self.original))
            self._observe()
            target = self.original.observation.container_id
            self._effect(
                journal, "restart-no", ("docker", "update", "--restart=no", target)
            )
            self._observe(held_policy=True)
            self._call(lambda: journal.append("confirmed", "restart-no"))
            self.uncertain = False
            self._observe(held_policy=True)
            self._effect(journal, "term", ("docker", "kill", "--signal=TERM", target))
            self.stage = "await-exit"
            while True:
                row = self._call(lambda: self.observe(target))
                if row.observation.running is False:
                    self._validate(row, held_policy=True, exited=True)
                    break
                self._validate(row, held_policy=True)
                self._call(lambda: self.sleep(min(0.1, self.deadline - self._now())))
            self._call(lambda: journal.append("confirmed", "term"))
            self._daemon()
            self._observe(held_policy=True, exited=True)
            self._call(lambda: journal.append("complete", "held"))
            self.uncertain = False
            self.stage = "held"
            result = {
                "status": "broadcast-held",
                "production_ready": False,
                "original_removed": False,
                "replacement_started": False,
                "operational_dispatch_enabled": False,
            }
        except Exception:
            failed = True
        except BaseException as exc:
            interrupted = exc
        finally:
            if journal is not None:
                # Closing must still happen after expiry. A slow/failing close
                # never changes a previous cancellation into an ordinary error.
                for action in (self._now, journal.close, self._now):
                    try:
                        action()
                    except Exception:
                        failed = True
                    except BaseException as exc:
                        if interrupted is None:
                            interrupted = exc
        if failed or interrupted is not None:
            self.uncertain = self.uncertain or journal is not None
        if interrupted is not None:
            raise interrupted
        if failed:
            # Outside all except blocks: no private exception context survives.
            raise Refused(CODE)
        return result
