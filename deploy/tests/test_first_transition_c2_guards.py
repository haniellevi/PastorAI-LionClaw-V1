"""Native guard contracts over private synthetic files; no live integrations."""

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_c2_guards as guards
from first_transition_adapter import digest
from first_transition_c2_cron import CronPathPolicy
from first_transition_database import DatabaseExpectation, LedgerProof, ReadOnlyDatabase
from first_transition_window_bindings import UnknownWriters
from initial_transition_ops import Refused

PRIVATE = "SYNTHETIC-PRIVATE-GUARD-SENTINEL"


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("unexpected native process or socket")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)


class FixtureDatabase(ReadOnlyDatabase):
    def __init__(self, world):
        self.world = world
        super().__init__(lambda **kwargs: pytest.fail("unexpected database connection"))
        self.change = {}
        self.hook = None
        self.calls = []

    def observe(self, *, timeout):
        self.calls.append(timeout)
        if self.hook:
            self.hook()
        e = self.world.expected
        return {
            **dict(
                identity=e.identity,
                ledger=e.ledger,
                catalog=e.catalog,
                ledger_digest=digest(list(e.ledger)),
                read_only=True,
                activity_visible=True,
                invalid=(),
                index_builds=0,
            ),
            **self.change,
        }


class FixtureWriters(UnknownWriters):
    def __init__(self, world):
        self.world = world
        # Nominal configuration only; no native constructor or observation IO.
        self.scope = world.scope
        self.declared = frozenset((world.target,))
        self.addresses, self.port = frozenset(("192.0.2.8",)), 5432
        self.docker = ("/synthetic/docker", "--host", "unix:///synthetic/docker.sock")
        self.readonly_roles, self.internal_roles = (), ("synthetic_internal",)
        self.proc, self.own_pid = Path("/synthetic/proc"), 1234
        self.connect = lambda **kwargs: pytest.fail(
            "unexpected writer database connection"
        )
        self._candidate_provider = None
        self.value, self.hook, self.calls = 0, None, []

    def observe(self, scope, *, timeout):
        assert scope == self.scope
        self.calls.append(timeout)
        if self.hook:
            self.hook()
        return self.value


class GuardWorld:
    """Reusable fixture assembly; all effects stay inside tmp_path or memory."""

    def __init__(
        self, tmp_path, *, scope="c" * 64, target="d" * 64, nonce="fixture_nonce"
    ):
        self.scope, self.target, self.nonce = scope, target, nonce
        self.now, self.wall = 100.0, 1000.0
        self.clock = lambda: self.now
        self.wall_clock = lambda: self.wall
        self.root = tmp_path / "guard-state"
        self.root.mkdir(mode=0o700)
        self.cron_policy = CronPathPolicy(
            ("/etc/cron.d/synthetic-disabled",),
            fixture_root=str(tmp_path),
            synthetic_only=True,
        )
        self.cron = Path(self.cron_policy.paths[0])
        self.cron.parent.mkdir(parents=True, mode=0o700)
        self.cron.parent.parent.chmod(0o700)
        self.cron.write_bytes(b"# synthetic disabled scheduler\nSHELL=/bin/false\n")
        self.cron.chmod(0o600)
        self.expected = DatabaseExpectation("a" * 64, ("0001_fixture.sql",), "b" * 64)
        self.db = FixtureDatabase(self)
        self.ledger = LedgerProof(self.db, self.expected, scope=scope)
        self.writers = FixtureWriters(self)
        self.calls, self.run_hook = [], None
        self.run_result = (
            0,
            b"Id=synthetic.timer\nLoadState=loaded\nActiveState=inactive\nUnitFileState=masked\n",
        )
        self.run = self._run
        self.schedule = guards.NativeScheduleProbe(
            units=("synthetic.timer",),
            cron_files=(str(self.cron),),
            cron_policy=self.cron_policy,
            run=self.run,
            enabled=True,
            synthetic_only=True,
            owner_uid=os.geteuid(),
            clock=self.clock,
        )
        self.admission = guards.GuardAdmission(
            scope, nonce, target, "e" * 64, "0" * 64, "0" * 64, "0" * 64, 110.0
        )
        initial = self.make_guard()
        sources = initial.source_pins()
        common = dict(
            scope=scope,
            nonce=nonce,
            target_id=target,
            request_digest=self.admission.request_digest,
            issued_at=999.0,
            expires_at=1010.0,
        )
        self.docs = {
            "scope": dict(
                common,
                kind="admitted-c2-scope",
                database_identity=self.expected.identity,
                baseline_digest=self.expected.baseline_digest,
                writer_sources=sources[0],
                scheduler_sources=sources[1],
                database_sources=sources[2],
            ),
            "recovery": dict(
                common,
                kind="verified-recovery",
                status="PASS",
                baseline_digest=self.expected.baseline_digest,
                restored_artifact_sha256="f" * 64,
            ),
            "schedule": dict(
                common,
                kind="reviewed-schedule-fence",
                complete_declared_inventory=True,
                units=list(self.schedule.units),
                cron_files={str(self.cron): guards.sha(self.cron.read_bytes())},
            ),
        }
        self.write_receipts()
        self.guard = self.make_guard()

    def _run(self, argv, *, timeout, max_output):
        self.calls.append((argv, timeout, max_output))
        if self.run_hook:
            self.run_hook()
        return self.run_result

    def write_receipts(self):
        hashes = {}
        for name, doc in self.docs.items():
            raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
            path = self.root / (name + ".json")
            path.write_bytes(raw)
            path.chmod(0o600)
            hashes[name + "_sha256"] = guards.sha(raw)
        self.admission = replace(self.admission, **hashes)

    def make_guard(self, **kwargs):
        return guards.NativeC2Guard(
            self.admission,
            state_root=self.root,
            ledger=self.ledger,
            writers=self.writers,
            schedule=self.schedule,
            owner_uid=os.geteuid(),
            clock=self.clock,
            wall_clock=self.wall_clock,
            **{"enabled": True, "synthetic_only": True, **kwargs},
        )

    def prove(self):
        return self.guard(self.scope, self.nonce)


def refused(call):
    with pytest.raises(Refused) as caught:
        call()
    assert str(caught.value) == guards.CODE
    assert caught.value.__context__ is None
    assert PRIVATE not in repr(caught.value)


def test_real_guard_composes_native_contracts(tmp_path):
    w = GuardWorld(tmp_path)
    assert not w.calls and not w.db.calls and not w.writers.calls
    w.guard.acquire()
    try:
        proof = w.prove()
        assert type(proof) is guards.GuardProof
        assert proof.scope == w.scope and proof.nonce == w.nonce
        assert proof.checked_at == 100.0 and 100 < proof.expires_at <= 100.9
        assert (
            proof.exclusive is proof.baseline_current is proof.cron_window_clear is True
        )
        assert proof.backup_recovery_ready is True and proof.ddl_started is False
        assert len(w.calls) == len(w.db.calls) == len(w.writers.calls) == 1
        assert w.calls[0][0] == w.schedule.argv("synthetic.timer")
        assert w.calls[0][2] == 4096
    finally:
        w.guard.close()


def test_default_closed_without_io(tmp_path, monkeypatch):
    w = GuardWorld(tmp_path)
    guard = w.make_guard(enabled=False)
    monkeypatch.setattr(os, "open", lambda *a, **k: pytest.fail("unexpected IO"))
    refused(guard.acquire)
    refused(lambda: guard(w.scope, w.nonce))
    assert not w.calls and not w.db.calls


@pytest.mark.parametrize(
    "name,field,value",
    [
        ("scope", "writer_sources", "9" * 64),
        ("scope", "baseline_digest", "9" * 64),
        ("scope", "database_identity", "9" * 64),
        ("scope", "kind", "unreviewed"),
        ("recovery", "kind", "captured-dump"),
        ("recovery", "status", "FAIL"),
        ("recovery", "baseline_digest", "9" * 64),
        ("recovery", "restored_artifact_sha256", PRIVATE),
        ("schedule", "complete_declared_inventory", False),
        ("schedule", "units", ["different.timer"]),
        ("schedule", "cron_files", {}),
        ("recovery", "scope", "9" * 64),
        ("recovery", "request_digest", "9" * 64),
        ("recovery", "nonce", "other"),
        ("recovery", "target_id", "9" * 64),
        ("recovery", "expires_at", 1000),
        ("recovery", "issued_at", 1001),
        ("recovery", "expires_at", 1061),
        ("recovery", "issued_at", False),
    ],
)
def test_invalid_admitted_receipt_semantics_refuse(tmp_path, name, field, value):
    w = GuardWorld(tmp_path)
    w.docs[name][field] = value
    w.write_receipts()
    w.guard = w.make_guard().acquire()
    try:
        refused(w.prove)
    finally:
        w.guard.close()


@pytest.mark.parametrize(
    "change",
    [
        {"read_only": False},
        {"activity_visible": False},
        {"catalog": "9" * 64},
        {"identity": "9" * 64},
        {"ledger": ("other.sql",)},
        {"ledger_digest": "9" * 64},
        {"invalid": ("bad_index",)},
        {"index_builds": 1},
    ],
)
def test_database_drift_or_visibility_refuses(tmp_path, change):
    w = GuardWorld(tmp_path)
    w.db.change = change
    w.guard.acquire()
    try:
        refused(w.prove)
        assert not w.writers.calls
    finally:
        w.guard.close()


@pytest.mark.parametrize("count", [1, -1, True, False, None, 0.0, "0"])
def test_only_strict_zero_undeclared_sources_pass(tmp_path, count):
    w = GuardWorld(tmp_path)
    w.writers.value = count
    w.guard.acquire()
    try:
        refused(w.prove)
    finally:
        w.guard.close()


def test_fixture_seals_required_before_any_io(tmp_path, monkeypatch):
    w = GuardWorld(tmp_path)
    guard = w.make_guard(synthetic_only=False)
    w.schedule.synthetic_only = False
    monkeypatch.setattr(os, "open", lambda *a, **k: pytest.fail("unexpected IO"))
    refused(guard.acquire)
    refused(lambda: w.schedule.verify({}, timeout=1))


@pytest.mark.parametrize("deadline", [None, True, float("nan"), float("inf"), 100, 161])
def test_invalid_deadline_refuses_before_acquire_io(tmp_path, monkeypatch, deadline):
    w = GuardWorld(tmp_path)
    w.admission = replace(w.admission, deadline=deadline)
    guard = w.make_guard()
    monkeypatch.setattr(os, "open", lambda *a, **k: pytest.fail("unexpected IO"))
    refused(guard.acquire)


def test_clock_must_be_bound_to_schedule_probe(tmp_path):
    w = GuardWorld(tmp_path)
    w.schedule.clock = lambda: w.now
    refused(w.make_guard)


@pytest.mark.parametrize("marker", ["regular", "symlink", "directory"])
def test_existing_or_unknown_ddl_marker_refuses(tmp_path, marker):
    w = GuardWorld(tmp_path)
    path = w.root / "ddl-marker"
    if marker == "regular":
        path.touch()
    elif marker == "directory":
        path.mkdir()
    else:
        path.symlink_to("missing")
    refused(w.guard.acquire)
    assert not w.calls and not w.db.calls


@pytest.mark.parametrize(
    "fault",
    ["missing", "hash", "symlink", "hardlink", "mode", "duplicate", "nonfinite"],
)
def test_private_receipt_integrity(tmp_path, fault):
    w = GuardWorld(tmp_path)
    path = w.root / "recovery.json"
    if fault == "missing":
        path.unlink()
    elif fault == "hash":
        path.write_text(PRIVATE)
    elif fault == "symlink":
        path.unlink()
        path.symlink_to(w.root / "scope.json")
    elif fault == "hardlink":
        os.link(path, w.root / "recovery-alias")
    elif fault == "mode":
        path.chmod(0o640)
    else:
        raw = (
            b'{"scope":"first","scope":"second"}'
            if fault == "duplicate"
            else b'{"scope":NaN}'
        )
        path.write_bytes(raw)
        w.admission = replace(w.admission, recovery_sha256=guards.sha(raw))
        w.guard = w.make_guard()
    w.guard.acquire()
    try:
        refused(w.prove)
    finally:
        w.guard.close()


def test_private_lease_contends_and_never_unlinks(tmp_path):
    w = GuardWorld(tmp_path)
    first = w.guard.acquire()
    second = w.make_guard()
    refused(second.acquire)
    first.close()
    assert (w.root / ("c2-lease-" + w.target)).exists()
    fresh = w.make_guard().acquire()
    try:
        assert fresh(w.scope, w.nonce).exclusive is True
    finally:
        fresh.close()


@pytest.mark.parametrize(
    "fault",
    ["root-replaced", "lease-replaced", "root-permissions", "parent-permissions"],
)
def test_custody_loss_refuses(tmp_path, fault):
    w = GuardWorld(tmp_path)
    w.guard.acquire()
    try:
        if fault == "root-replaced":
            w.root.rename(tmp_path / "old-root")
            w.root.mkdir(mode=0o700)
        elif fault == "lease-replaced":
            lease = w.root / ("c2-lease-" + w.target)
            lease.rename(w.root / "old-lease")
            lease.touch(mode=0o600)
        elif fault == "root-permissions":
            w.root.chmod(0o770)
        else:
            tmp_path.chmod(0o777)
        refused(w.prove)
        assert not w.calls and not w.db.calls
    finally:
        tmp_path.chmod(0o700)
        w.guard.close()


@pytest.mark.parametrize(
    "value",
    [
        "active",
        "unmasked",
        "extra",
        "duplicate",
        "oversize",
        "bad-return",
        "bool-return",
    ],
)
def test_native_schedule_metadata_must_match_exactly(tmp_path, value):
    w = GuardWorld(tmp_path)
    rc, raw = w.run_result
    if value == "active":
        raw = raw.replace(b"inactive", b"active")
    elif value == "unmasked":
        raw = raw.replace(b"masked", b"enabled")
    elif value == "extra":
        raw += b"Unknown=" + PRIVATE.encode() + b"\n"
    elif value == "duplicate":
        raw += b"ActiveState=inactive\n"
    elif value == "oversize":
        raw = b"x" * 4097
    elif value == "bad-return":
        rc = 1
    else:
        rc = False
    w.run_result = rc, raw
    w.guard.acquire()
    try:
        refused(w.prove)
        assert not w.db.calls
    finally:
        w.guard.close()


def test_actual_cron_job_refuses_even_when_hash_admitted(tmp_path):
    w = GuardWorld(tmp_path)
    w.cron.write_bytes(b"* * * * * synthetic-no-execution\n")
    w.docs["schedule"]["cron_files"][str(w.cron)] = guards.sha(w.cron.read_bytes())
    w.write_receipts()
    w.guard = w.make_guard().acquire()
    try:
        refused(w.prove)
        assert not w.calls
    finally:
        w.guard.close()


@pytest.mark.parametrize("which", ["recovery", "cron"])
def test_read_identity_bracket_detects_toctou(tmp_path, monkeypatch, which):
    w = GuardWorld(tmp_path)
    path = w.root / "recovery.json" if which == "recovery" else w.cron
    info = path.stat()
    original = os.read
    changed = False

    def racing_read(fd, size):
        nonlocal changed
        data = original(fd, size)
        if not changed and os.fstat(fd).st_ino == info.st_ino:
            changed = True
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
        return data

    w.guard.acquire()
    monkeypatch.setattr(os, "read", racing_read)
    try:
        refused(w.prove)
        assert changed
    finally:
        w.guard.close()


@pytest.mark.parametrize(
    "fault",
    ["slow", "deadline", "reverse", "nan", "bool", "wall-reverse", "wall-expired"],
)
def test_clock_and_observation_freshness(tmp_path, fault):
    w = GuardWorld(tmp_path)

    def advance():
        if fault == "slow":
            w.now += 0.9
        elif fault == "deadline":
            w.now = 110
        elif fault == "reverse":
            w.now -= 1
        elif fault == "nan":
            w.now = float("nan")
        elif fault == "bool":
            w.now = True
        elif fault == "wall-reverse":
            w.wall -= 1
        else:
            w.wall = 1010

    w.db.hook = advance
    w.guard.acquire()
    try:
        refused(w.prove)
    finally:
        w.guard.close()


@pytest.mark.parametrize("source", ["database", "schedule", "writers", "ddl"])
def test_secret_failures_are_sanitized_and_latched(tmp_path, monkeypatch, source):
    w = GuardWorld(tmp_path)

    def fail():
        raise OSError(PRIVATE)

    w.guard.acquire()
    if source == "database":
        w.db.hook = fail
    elif source == "schedule":
        w.run_hook = fail
    elif source == "writers":
        w.writers.hook = fail
    else:
        monkeypatch.setattr(w.guard.root, "absent_ddl", fail)
    try:
        refused(w.prove)
        counts = len(w.calls), len(w.db.calls), len(w.writers.calls)
        monkeypatch.setattr(
            w.guard.root, "check", lambda: pytest.fail("retry observation")
        )
        refused(w.prove)
        refused(w.guard.acquire)
        assert counts == (len(w.calls), len(w.db.calls), len(w.writers.calls))
    finally:
        w.guard.close()


def test_cancellation_is_preserved_and_latched(tmp_path, monkeypatch):
    w = GuardWorld(tmp_path)
    interrupt = KeyboardInterrupt()

    def cancel():
        raise interrupt

    w.db.hook = cancel
    w.guard.acquire()
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            w.prove()
        assert caught.value is interrupt
        monkeypatch.setattr(
            w.guard.root, "check", lambda: pytest.fail("retry observation")
        )
        refused(w.prove)
        refused(w.guard.acquire)
    finally:
        w.guard.close()


def test_mutable_dependency_inventory_cannot_change_after_admission(tmp_path):
    w = GuardWorld(tmp_path)
    w.guard.acquire()
    try:
        w.writers.declared = frozenset((w.target, "9" * 64))
        refused(w.prove)
        assert not w.calls
    finally:
        w.guard.close()


def test_admission_is_copied_and_private(tmp_path):
    w = GuardWorld(tmp_path)
    assert w.guard.admission is not w.admission
    assert w.scope not in repr(w.guard.admission)
    original = deepcopy(w.guard.admission)
    object.__setattr__(w.admission, "nonce", "changed_original")
    assert w.guard.admission == original
