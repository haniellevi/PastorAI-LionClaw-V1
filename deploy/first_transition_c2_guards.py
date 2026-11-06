"""Fixture-only C2 guard composition with real filesystem/read-contract checks.

A local lease excludes cooperative callers only. Private, hash-admitted receipts
assert the reviewed recovery and complete declared schedule inventory; they are
not measurements or human authorization. Actual ledger/writer observations and
schedule sources are freshly checked on every call. This is not an operational
recovery/exclusivity attestation provider. GuardProof assertions are fictional
when explicitly synthetic-enabled; default/nonfixture use refuses. No live wiring.
"""

from copy import deepcopy
from dataclasses import dataclass
from functools import wraps
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time

from first_transition_c2_containment import GuardProof
from first_transition_c2_cron import CronPathPolicy
from first_transition_adapter import digest
from first_transition_database import LedgerProof
from first_transition_window_bindings import UnknownWriters
from initial_transition_files import is_protected
from initial_transition_ops import Refused

CODE = "c2-native-guard-refused"
HEX = re.compile("[0-9a-f]{64}")
UNIT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}\.timer")
O_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
PROPERTIES = "Id,LoadState,ActiveState,UnitFileState"


def need(ok):
    if not ok:
        raise Refused(CODE)


def private_errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        failed = False
        try:
            result = function(*args, **kwargs)
        except Exception:
            failed = True
        if failed:
            raise Refused(CODE)
        return result

    return wrapped


def safe_ancestor(part, row, owner_uid, root_uid):
    sticky = (
        part == "tmp" and row.st_uid == root_uid and bool(row.st_mode & stat.S_ISVTX)
    )
    need(row.st_uid in (root_uid, owner_uid) and (not row.st_mode & 0o022 or sticky))


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result)
            result[key] = value
        return result

    return json.loads(
        raw, object_pairs_hook=pairs, parse_constant=lambda _: need(False)
    )


def fingerprint(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def no_acl(fd):
    need(
        not {"system.posix_acl_access", "system.posix_acl_default"}
        & set(os.listxattr(fd))
    )


class PrivateRoot:
    """No-follow retained ancestor FDs; only named, private regular receipts read."""

    def __init__(self, path, owner_uid):
        self.fds = []
        self.links = []
        self.owner_uid = owner_uid
        root = Path(path)
        need(
            root.is_absolute()
            and str(root) == os.path.normpath(root)
            and not is_protected(root.parts)
            and type(owner_uid) is int
        )
        try:
            fd = os.open("/", O_DIR)
            self.fds.append(fd)
            root_uid = os.fstat(fd).st_uid
            need(owner_uid != 0 or root_uid == 0)
            self.root_uid = root_uid
            for part in root.parts[1:]:
                child = os.open(part, O_DIR, dir_fd=fd)
                self.fds.append(child)
                row = os.fstat(child)
                sticky = (
                    part == "tmp"
                    and row.st_uid == root_uid
                    and bool(row.st_mode & stat.S_ISVTX)
                )
                need(
                    row.st_uid in (root_uid, owner_uid)
                    and (not row.st_mode & 0o022 or sticky)
                )
                no_acl(child)
                self.links.append((fd, part, child))
                fd = child
            s = os.fstat(fd)
            need(s.st_uid == owner_uid and stat.S_IMODE(s.st_mode) == 0o700)
            self.fd = fd
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self):
        for parent, name, child in self.links:
            a = os.stat(name, dir_fd=parent, follow_symlinks=False)
            b = os.fstat(child)
            need(
                (a.st_dev, a.st_ino, a.st_mode, a.st_uid, a.st_gid)
                == (b.st_dev, b.st_ino, b.st_mode, b.st_uid, b.st_gid)
            )
            safe_ancestor(name, b, self.owner_uid, self.root_uid)
            no_acl(child)
        s = os.fstat(self.fd)
        need(s.st_uid == self.owner_uid and stat.S_IMODE(s.st_mode) == 0o700)

    def read(self, name):
        need(name in ("scope.json", "recovery.json", "schedule.json"))
        self.check()
        before = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        need(
            stat.S_ISREG(before.st_mode)
            and before.st_uid == self.owner_uid
            and stat.S_IMODE(before.st_mode) == 0o600
            and before.st_nlink == 1
            and 0 < before.st_size <= 65536
        )
        fd = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOATIME,
            dir_fd=self.fd,
        )
        try:
            no_acl(fd)
            need(fingerprint(before) == fingerprint(os.fstat(fd)))
            data = bytearray()
            while len(data) < before.st_size:
                chunk = os.read(fd, min(65536, before.st_size - len(data)))
                need(bool(chunk))
                data.extend(chunk)
            need(not os.read(fd, 1))
            need(
                fingerprint(before)
                == fingerprint(os.fstat(fd))
                == fingerprint(os.stat(name, dir_fd=self.fd, follow_symlinks=False))
            )
        finally:
            os.close(fd)
        self.check()
        return bytes(data)

    def absent_ddl(self):
        self.check()
        try:
            os.stat("ddl-marker", dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise Refused(CODE)

    def close(self):
        failure = False
        while self.fds:
            try:
                os.close(self.fds.pop())
            except OSError:
                failure = True
        if failure:
            raise Refused(CODE)


class PrivateLease:
    """FD flock plus unchanged pathname binding, not global host exclusivity."""

    def __init__(self, root, target):
        need(
            type(root) is PrivateRoot and type(target) is str and HEX.fullmatch(target)
        )
        self.root, self.fd, self.identity = root, None, None
        self.name = "c2-lease-" + target

    def acquire(self):
        need(self.fd is None)
        self.root.check()
        fd = os.open(
            self.name,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=self.root.fd,
        )
        self.fd = fd
        try:
            s = os.fstat(fd)
            need(
                stat.S_ISREG(s.st_mode)
                and s.st_uid == self.root.owner_uid
                and s.st_nlink == 1
                and s.st_size == 0
                and stat.S_IMODE(s.st_mode) == 0o600
            )
            no_acl(fd)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.identity = (s.st_dev, s.st_ino)
            os.fsync(fd)
            os.fsync(self.root.fd)
            self.check()
        except BaseException:
            os.close(fd)
            self.fd = None
            raise

    def check(self):
        need(self.fd is not None and self.identity is not None)
        self.root.check()
        a = os.stat(self.name, dir_fd=self.root.fd, follow_symlinks=False)
        b = os.fstat(self.fd)
        need(
            (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino) == self.identity
            and stat.S_ISREG(a.st_mode)
            and a.st_uid == self.root.owner_uid
            and a.st_nlink == 1
            and a.st_size == 0
            and stat.S_IMODE(a.st_mode) == 0o600
        )
        no_acl(self.fd)
        # Refreshing this open file description's lock never acquires a replaced inode.
        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def close(self):
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.close(
                fd
            )  # releases only this caller's lock, never unlinks another lease


class NativeScheduleProbe:
    """Declared timer status + cron files only; no all-host completeness claim.

    Receipts list the reviewed *complete relevant inventory*. Every listed timer
    must be loaded/inactive/masked, and listed cron files contain no jobs. An
    unknown/active source refuses. The runner must impose its own process cap;
    only these fixed systemctl read argv are supplied. No subprocess is started
    by this class itself or by its constructor. This verifier is synthetic-only:
    exact nominal cron policy is mandatory before any filesystem operation.
    Fixture paths grant no host-file authority; operational admission stays closed.
    """

    @private_errors
    def __init__(
        self,
        *,
        units,
        cron_files,
        run,
        cron_policy=None,
        owner_uid=0,
        enabled=False,
        synthetic_only=False,
        clock=time.monotonic,
    ):
        self.units = tuple(deepcopy(units))
        self.cron_files = tuple(deepcopy(cron_files))
        self.run, self.owner_uid, self.enabled, self.clock = (
            run,
            owner_uid,
            enabled,
            clock,
        )
        self.synthetic_only = synthetic_only
        need(type(cron_policy) is CronPathPolicy)
        self.cron_policy = cron_policy
        self._policy_digest = cron_policy.digest
        need(
            self.units
            and len(set(self.units)) == len(self.units)
            and all(type(u) is str and UNIT.fullmatch(u) for u in self.units)
        )
        need(
            self.cron_files
            and len(set(self.cron_files)) == len(self.cron_files)
            and all(
                type(p) is str
                and Path(p).is_absolute()
                and str(Path(p)) == os.path.normpath(p)
                and not is_protected(Path(p).parts)
                for p in self.cron_files
            )
        )
        self._paths()

    def _paths(self):
        need(type(self.cron_policy) is CronPathPolicy)
        need(self.cron_policy.digest == self._policy_digest)
        need(self.cron_policy.admit(self.cron_files) is True)

    def argv(self, unit):
        need(unit in self.units)
        return (
            "/usr/bin/systemctl",
            "show",
            "--no-pager",
            "--property=" + PROPERTIES,
            unit,
        )

    @private_errors
    def verify(self, hashes, *, timeout):
        need(
            self.enabled is True
            and self.synthetic_only is True
            and self.cron_policy.synthetic_only is True
            and self.cron_policy.fixture_root != "/"
            and callable(self.run)
            and finite(timeout)
            and 0 < timeout <= 60
        )
        self._paths()
        need(
            type(hashes) is dict
            and set(hashes) == set(self.cron_files)
            and all(type(h) is str and HEX.fullmatch(h) for h in hashes.values())
        )
        start = self.clock()
        need(finite(start))
        end = start + timeout
        last = start

        def remaining():
            nonlocal last
            now = self.clock()
            need(finite(now) and now >= last and now < end)
            last = now
            return end - now

        for path in self.cron_files:
            remaining()
            self._paths()
            fd = os.open("/", O_DIR)
            descriptors = [fd]
            links = []
            try:
                parts = Path(path).parts[1:]
                for part in parts[:-1]:
                    parent_fd = fd
                    fd = os.open(part, O_DIR, dir_fd=fd)
                    links.append((parent_fd, part, fd))
                    descriptors.append(fd)
                    s = os.fstat(fd)
                    sticky = (
                        part == "tmp"
                        and s.st_uid == os.fstat(descriptors[0]).st_uid
                        and bool(s.st_mode & stat.S_ISVTX)
                    )
                    need(
                        s.st_uid in (os.fstat(descriptors[0]).st_uid, self.owner_uid)
                        and (not s.st_mode & 0o022 or sticky)
                    )
                    no_acl(fd)
                parent = fd
                fd = os.open(
                    parts[-1],
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOATIME,
                    dir_fd=parent,
                )
                descriptors.append(fd)
                s = os.fstat(fd)
                need(
                    stat.S_ISREG(s.st_mode)
                    and s.st_uid == self.owner_uid
                    and s.st_nlink == 1
                    and not s.st_mode & 0o022
                    and s.st_size <= 65536
                )
                no_acl(fd)
                raw = bytearray()
                while len(raw) < s.st_size:
                    chunk = os.read(fd, min(65536, s.st_size - len(raw)))
                    need(bool(chunk))
                    raw.extend(chunk)
                need(not os.read(fd, 1) and sha(raw) == hashes[path])
                need(
                    fingerprint(s)
                    == fingerprint(os.fstat(fd))
                    == fingerprint(
                        os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                    )
                )
                for parent_fd, part, child_fd in links:
                    a = os.stat(part, dir_fd=parent_fd, follow_symlinks=False)
                    b = os.fstat(child_fd)
                    need(
                        (a.st_dev, a.st_ino, a.st_mode, a.st_uid, a.st_gid)
                        == (b.st_dev, b.st_ino, b.st_mode, b.st_uid, b.st_gid)
                    )
                    safe_ancestor(
                        part, b, self.owner_uid, os.fstat(descriptors[0]).st_uid
                    )
                    no_acl(child_fd)
                for line in raw.decode("utf-8").splitlines():
                    clean = line.strip()
                    need(
                        not clean
                        or clean.startswith("#")
                        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\s*=.*", clean)
                        is not None
                    )
            finally:
                for fd in reversed(descriptors):
                    os.close(fd)
            remaining()
        self._paths()
        for unit in self.units:
            rc, raw = self.run(self.argv(unit), timeout=remaining(), max_output=4096)
            remaining()
            self._paths()
            need(
                type(rc) is int and rc == 0 and type(raw) is bytes and len(raw) <= 4096
            )
            rows = {}
            for line in raw.decode("utf-8").splitlines():
                key, sep, value = line.partition("=")
                need(sep and key not in rows)
                rows[key] = value
            need(
                rows
                == dict(
                    Id=unit,
                    LoadState="loaded",
                    ActiveState="inactive",
                    UnitFileState="masked",
                )
            )
        return True


@dataclass(frozen=True, repr=False)
class GuardAdmission:
    scope: str
    nonce: str
    target_id: str
    request_digest: str
    scope_sha256: str
    recovery_sha256: str
    schedule_sha256: str
    deadline: float


class NativeC2Guard:
    """Compose native read contracts and private admitted evidence, never boolean ports.

    The private recovery receipt is a trusted artifact supplied by its owner; its
    hash/root custody/request/baseline binding do not recreate recovery evidence.
    Missing/expired/capture-only evidence refuses. The private scope receipt binds declared sources only. The lease and writer
    census never prove global zero writers, drained ingress, or host-wide quiet.
    An authoritative receipt issuer and broader operational attestation remain
    required before any production wiring; this module supplies neither. No enabled
    operation is implied by constructing this object.
    """

    @private_errors
    def __init__(
        self,
        admission,
        *,
        state_root,
        ledger,
        writers,
        schedule,
        enabled=False,
        synthetic_only=False,
        owner_uid=0,
        clock=time.monotonic,
        wall_clock=time.time,
    ):
        need(type(admission) is GuardAdmission)
        self.admission = deepcopy(admission)
        self.state_root, self.ledger, self.writers, self.schedule = (
            state_root,
            ledger,
            writers,
            schedule,
        )
        self.enabled, self.synthetic_only = enabled, synthetic_only
        self.owner_uid, self.clock, self.wall_clock = owner_uid, clock, wall_clock
        self.root = self.lease = None
        self._failed = False
        self._last = self._last_wall = None
        a = self.admission
        need(
            all(
                type(s) is str and HEX.fullmatch(s)
                for s in (
                    a.scope,
                    a.target_id,
                    a.request_digest,
                    a.scope_sha256,
                    a.recovery_sha256,
                    a.schedule_sha256,
                )
            )
        )
        need(type(a.nonce) is str and re.fullmatch("[A-Za-z0-9_-]{1,128}", a.nonce))
        need(
            isinstance(ledger, LedgerProof)
            and ledger.scope == a.scope
            and isinstance(writers, UnknownWriters)
            and writers.scope == a.scope
            and type(schedule) is NativeScheduleProbe
            and schedule.clock is clock
        )
        self.expected = deepcopy(ledger.expected.validated())
        self._sources = self.source_pins()
        # Identities and nominal configuration retain the admitted custody binding.
        self._bindings = (
            ledger.database,
            ledger.database.connect,
            writers.connect,
            writers._candidate_provider,
            schedule.run,
            schedule.clock,
            schedule.cron_policy,
        )

    def source_pins(self):
        w, s, db = self.writers, self.schedule, self.ledger.database
        need(
            type(w.declared) is frozenset
            and self.admission.target_id in w.declared
            and all(type(v) is str and HEX.fullmatch(v) for v in w.declared)
            and type(w.addresses) is frozenset
            and w.addresses
            and all(type(v) is str for v in w.addresses)
            and type(w.port) is int
            and 0 < w.port <= 65535
            and type(w.own_pid) is int
            and w.own_pid > 0
        )
        writer = [
            sorted(w.declared),
            sorted(w.addresses),
            w.port,
            list(w.docker),
            list(w.readonly_roles),
            list(w.internal_roles),
            str(w.proc),
            w.own_pid,
        ]
        s._paths()
        scheduler = [
            list(s.units),
            list(s.cron_files),
            s.owner_uid,
            s.cron_policy.digest,
        ]
        database = [list(map(list, db.lease_columns)), list(db.observer_applications)]
        return (digest(writer), digest(scheduler), digest(database))

    def _remaining(self):
        now = self.clock()
        need(
            finite(now)
            and (self._last is None or now >= self._last)
            and finite(self.admission.deadline)
            and now < self.admission.deadline
        )
        if self._last is None:
            need(self.admission.deadline <= now + 60)
        self._last = now
        return self.admission.deadline - now

    def _check(self):
        need(
            not self._failed
            and self.enabled is True
            and self.synthetic_only is True
            and self.lease is not None
        )
        self._remaining()
        self.lease.check()
        self.root.absent_ddl()
        need(
            self.ledger.scope == self.admission.scope
            and self.writers.scope == self.admission.scope
            and self.ledger.expected == self.expected
            and self.source_pins() == self._sources
            and all(
                a is b
                for a, b in zip(
                    self._bindings,
                    (
                        self.ledger.database,
                        self.ledger.database.connect,
                        self.writers.connect,
                        self.writers._candidate_provider,
                        self.schedule.run,
                        self.schedule.clock,
                        self.schedule.cron_policy,
                    ),
                )
            )
        )
        self._remaining()

    def acquire(self):
        failed, interrupted = False, None
        try:
            need(
                not self._failed
                and self.enabled is True
                and self.synthetic_only is True
                and self.root is None
                and self.lease is None
            )
            self._remaining()
            self.root = PrivateRoot(self.state_root, self.owner_uid)
            self.lease = PrivateLease(self.root, self.admission.target_id)
            self.lease.acquire()
            self._check()
        except Exception:
            failed = True
        except BaseException as exc:
            interrupted = exc
        if failed or interrupted is not None:
            self._failed = True
            try:
                self.close()
            except Exception:
                failed = True
            if interrupted is not None:
                raise interrupted
            raise Refused(CODE)
        return self

    def _receipt(self, name, expected_sha, wall):
        raw = self.root.read(name)
        need(sha(raw) == expected_sha)
        doc = strict_json(raw)
        a = self.admission
        need(
            type(doc) is dict
            and doc.get("scope") == a.scope
            and doc.get("nonce") == a.nonce
            and doc.get("target_id") == a.target_id
            and doc.get("request_digest") == a.request_digest
            and finite(doc.get("issued_at"))
            and finite(doc.get("expires_at"))
            and doc["issued_at"] <= wall < doc["expires_at"] <= doc["issued_at"] + 60
        )
        return doc

    def __call__(self, scope, nonce):
        failed, interrupted, result = False, None, None
        try:
            need(scope == self.admission.scope and nonce == self.admission.nonce)
            self._remaining()
            checked_at = self._last
            self._check()
            wall = self.wall_clock()
            need(finite(wall) and (self._last_wall is None or wall >= self._last_wall))
            self._last_wall = wall
            scope_receipt = self._receipt(
                "scope.json", self.admission.scope_sha256, wall
            )
            need(
                set(scope_receipt)
                == {
                    "scope",
                    "nonce",
                    "target_id",
                    "request_digest",
                    "issued_at",
                    "expires_at",
                    "kind",
                    "database_identity",
                    "baseline_digest",
                    "writer_sources",
                    "scheduler_sources",
                    "database_sources",
                }
                and scope_receipt["kind"] == "admitted-c2-scope"
                and scope_receipt["database_identity"] == self.expected.identity
                and scope_receipt["baseline_digest"] == self.expected.baseline_digest
                and (
                    scope_receipt["writer_sources"],
                    scope_receipt["scheduler_sources"],
                    scope_receipt["database_sources"],
                )
                == self._sources
            )
            recovery = self._receipt(
                "recovery.json", self.admission.recovery_sha256, wall
            )
            need(
                set(recovery)
                == {
                    "scope",
                    "nonce",
                    "target_id",
                    "request_digest",
                    "issued_at",
                    "expires_at",
                    "kind",
                    "status",
                    "baseline_digest",
                    "restored_artifact_sha256",
                }
                and recovery["kind"] == "verified-recovery"
                and recovery["status"] == "PASS"
                and recovery["baseline_digest"] == self.expected.baseline_digest
                and type(recovery["restored_artifact_sha256"]) is str
                and HEX.fullmatch(recovery["restored_artifact_sha256"])
            )
            receipt = self._receipt(
                "schedule.json", self.admission.schedule_sha256, wall
            )
            need(
                set(receipt)
                == {
                    "scope",
                    "nonce",
                    "target_id",
                    "request_digest",
                    "issued_at",
                    "expires_at",
                    "kind",
                    "complete_declared_inventory",
                    "units",
                    "cron_files",
                }
                and receipt["kind"] == "reviewed-schedule-fence"
                and receipt["complete_declared_inventory"] is True
                and receipt["units"] == list(self.schedule.units)
            )
            self._check()
            need(
                self.schedule.verify(receipt["cron_files"], timeout=self._remaining())
                is True
            )
            self._check()
            proof = self.ledger.prove(scope, timeout=min(30, self._remaining()))
            self._check()
            need(
                type(proof) is dict
                and proof.get("scope") == scope
                and proof.get("read_only") is True
                and proof.get("ddl_free") is True
                and proof.get("identity") == self.expected.identity
                and proof.get("catalog") == self.expected.catalog
                and proof.get("ledger_digest") == digest(list(self.expected.ledger))
            )
            writers = self.writers.observe(scope, timeout=self._remaining())
            self._check()
            need(type(writers) is int and writers == 0)
            end_wall = self.wall_clock()
            need(
                finite(end_wall)
                and end_wall >= wall
                and end_wall
                < min(
                    scope_receipt["expires_at"],
                    recovery["expires_at"],
                    receipt["expires_at"],
                )
            )
            self._last_wall = end_wall
            remaining = self._remaining()
            now = self._last
            need(now - checked_at < 0.9)
            result = GuardProof(
                scope,
                nonce,
                checked_at,
                now
                + min(
                    0.9 - (now - checked_at),
                    remaining,
                    scope_receipt["expires_at"] - end_wall,
                    recovery["expires_at"] - end_wall,
                    receipt["expires_at"] - end_wall,
                ),
                True,
                True,
                True,
                True,
                False,
            )
        except Exception:
            failed = True
        except BaseException as exc:
            interrupted = exc
        if interrupted is not None or failed:
            self._failed = True
        if interrupted is not None:
            raise interrupted
        if failed:
            raise Refused(CODE)
        return result

    def close(self):
        failed, interrupted = False, None
        for obj in (self.lease, self.root):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    failed = True
                except BaseException as exc:
                    interrupted = interrupted or exc
        self.lease = self.root = None
        if failed or interrupted is not None:
            self._failed = True
        if interrupted is not None:
            raise interrupted
        if failed:
            raise Refused(CODE)
