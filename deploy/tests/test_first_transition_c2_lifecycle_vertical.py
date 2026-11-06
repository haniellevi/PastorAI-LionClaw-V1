"""Lease-owned C2 lifecycle with real component classes and fictional IO edges."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from c2_lifecycle_fixture import SessionFixture
from first_transition_c2_containment import BroadcastRunner
from first_transition_c2_native import NativeSnapshotProducer
from initial_transition_ops import Refused
from test_first_transition_c2_native import PRIVATE


@pytest.fixture(autouse=True)
def no_real_services(monkeypatch):
    def deny(*_args, **_kwargs):
        pytest.fail("real process or socket attempted")

    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(socket, "socket", deny)


def assert_released(f):
    assert f.guards.guard.root is None and f.guards.guard.lease is None
    assert all(c.stdout.closed for c in f.docker.children)
    assert all(
        c.stdout.file.closed and c.stderr.file.closed for c in f.scheduler.children
    )


def test_lease_precedes_first_snapshot_and_covers_entire_vertical_flow(tmp_path):
    f = SessionFixture(tmp_path)
    seen = []

    def held(stage):
        lease = f.guards.guard.lease
        assert lease is not None and os.fstat(lease.fd).st_nlink == 1
        seen.append(stage)

    f.docker.before = lambda argv: held(argv[1])
    f.scheduler.hook = lambda _child: held("scheduler")
    f.guards.db.hook = lambda: held("database")
    f.guards.writers.hook = lambda: held("writers")
    session = f.session()
    assert not seen and not f.docker.calls and not f.scheduler.calls
    result = session.run()
    assert result["status"] == "broadcast-held"
    assert result["lease_released"] is True
    assert result["production_ready"] is result["operational_dispatch_enabled"] is False
    assert result["original_removed"] is result["replacement_started"] is False
    assert f.effects == ["restart-no", "TERM"]
    assert seen[0] == "scheduler" and seen.index("writers") < seen.index("info")
    assert f.world.row[5]["Running"] is False
    assert PRIVATE not in repr(session) and PRIVATE not in json.dumps(result)
    assert_released(f)
    before = json.loads((f.journal / "before.json").read_bytes())
    assert before["private_config"]["Config"]["Image"] == f.world.image
    assert (f.journal / "before.json").stat().st_mode & 0o777 == 0o600
    events = [
        json.loads(line)
        for line in (f.journal / "events.jsonl").read_text().splitlines()
    ]
    assert events[-1] == {"kind": "complete", "step": "held"}
    calls = (len(f.docker.calls), len(f.scheduler.calls))
    with pytest.raises(Refused):
        session.run()
    assert calls == (len(f.docker.calls), len(f.scheduler.calls))


@pytest.mark.parametrize(
    "fault", ["scheduler", "baseline", "writers", "identity", "command"]
)
def test_vertical_refusal_releases_lease_without_custody_or_broadcast_effects(
    tmp_path, fault
):
    f = SessionFixture(tmp_path)
    if fault == "scheduler":
        f.scheduler.stderr = PRIVATE.encode()
    elif fault == "baseline":
        f.guards.db.change = {"catalog": "9" * 64}
    elif fault == "writers":
        f.guards.writers.value = 1
    elif fault == "identity":
        f.world.row[2] = "sha256:" + "9" * 64
    else:
        f.world.row[8] = "sh"
    session = f.session()
    with pytest.raises(Refused) as error:
        session.run()
    assert error.value.__context__ is None and PRIVATE not in str(error.value)
    assert not f.effects and not f.journal.exists()
    if fault in ("scheduler", "baseline", "writers"):
        assert not f.docker.calls  # No protected snapshot before valid proof.
    assert_released(f)
    calls = (len(f.docker.calls), len(f.scheduler.calls))
    with pytest.raises(Refused):
        session.run()
    assert calls == (len(f.docker.calls), len(f.scheduler.calls))


def test_lost_guard_after_policy_change_preserves_custody_and_uncertainty(tmp_path):
    f = SessionFixture(tmp_path)

    def lose_guard(argv, _child):
        if argv[1] == "update":
            (f.guards.root / "ddl-marker").write_text("fixture-only")

    f.docker.after = lose_guard
    session = f.session()
    with pytest.raises(Refused):
        session.run()
    assert f.effects == ["restart-no"] and f.world.row[5]["Running"] is True
    assert session.uncertain is True
    assert_released(f)
    events = [
        json.loads(line)
        for line in (f.journal / "events.jsonl").read_text().splitlines()
    ]
    assert events == [{"kind": "intent", "step": "restart-no"}]
    with pytest.raises(Refused):
        session.run()
    assert session.uncertain is True


@pytest.mark.parametrize("stage", ["snapshot", "effect-ack"])
def test_vertical_cancellation_preserves_signal_and_releases_owned_resources(
    tmp_path, stage
):
    f = SessionFixture(tmp_path)
    cancelled = KeyboardInterrupt("fixture cancellation")
    if stage == "snapshot":

        def before(argv):
            if argv[1] == "inspect":
                raise cancelled

        f.docker.before = before
    else:

        def after(argv, child):
            if argv[1] == "update":
                child.wait_error = cancelled

        f.docker.after = after
    session = f.session()
    with pytest.raises(KeyboardInterrupt) as error:
        session.run()
    assert error.value is cancelled
    assert f.effects == ([] if stage == "snapshot" else ["restart-no"])
    assert_released(f)
    with pytest.raises(Refused):
        session.run()


@pytest.mark.parametrize("failure", ["error", "late"])
def test_release_failure_cannot_return_held_success_or_retry(
    tmp_path, monkeypatch, failure
):
    f = SessionFixture(tmp_path)
    original_close = f.guards.guard.close

    def release():
        original_close()
        if failure == "error":
            raise RuntimeError(PRIVATE)
        f.guards.now = f.guards.guard.admission.deadline

    monkeypatch.setattr(f.guards.guard, "close", release)
    session = f.session()
    with pytest.raises(Refused) as error:
        session.run()
    assert error.value.__context__ is None and PRIVATE not in str(error.value)
    assert f.effects == ["restart-no", "TERM"] and session.uncertain is True
    assert_released(f)
    calls = len(f.docker.calls)
    with pytest.raises(Refused):
        session.run()
    assert len(f.docker.calls) == calls
    assert session.uncertain is True


def test_does_not_steal_or_release_a_callers_existing_lease(tmp_path):
    f = SessionFixture(tmp_path)
    f.guards.guard.acquire()
    fd = f.guards.guard.lease.fd
    try:
        with pytest.raises(Refused):
            f.session().run()
        assert f.guards.guard.lease.fd == fd and os.fstat(fd).st_nlink == 1
        assert not f.docker.calls and not f.scheduler.calls
    finally:
        f.guards.guard.close()


@pytest.mark.parametrize("component", ["guard", "observer", "runner"])
def test_component_swap_during_snapshot_releases_original_owner_and_refuses_effects(
    tmp_path, component
):
    f = SessionFixture(tmp_path)
    original_guard = f.guards.guard
    if component == "guard":
        replacement = f.guards.make_guard()
    elif component == "observer":
        replacement = NativeSnapshotProducer(
            f.world.manifest,
            f.world.admission,
            runner=f.read_runner,
            deadline=f.guards.admission.deadline,
            enabled=True,
            clock=f.clock,
        )
    else:
        replacement = BroadcastRunner(
            manifest=f.world.manifest,
            docker_binary="/fixture/docker",
            endpoint="unix:///fixture/docker.sock",
            config_dir="/fixture/docker-config",
            popen=f.spawn,
        )
    session = f.session()

    def swap(argv):
        if argv[1] == "inspect":
            setattr(session, component, replacement)

    f.docker.before = swap
    try:
        with pytest.raises(Refused):
            session.run()
        assert not f.effects and not f.journal.exists()
        assert_released(f)
        if component == "guard":
            assert replacement.root is replacement.lease is None
    finally:
        original_guard.close()  # Test cleanup even if release assertions fail.
        if component == "guard":
            replacement.close()


@pytest.mark.parametrize("seal", ["enabled", "synthetic_only"])
def test_runtime_seal_drop_stops_before_custody_or_first_effect(tmp_path, seal):
    f = SessionFixture(tmp_path)
    session = f.session()

    def drop(argv):
        if argv[1] == "inspect":
            setattr(session, seal, False)

    f.docker.before = drop
    with pytest.raises(Refused):
        session.run()
    assert not f.effects and not f.journal.exists()
    assert_released(f)
