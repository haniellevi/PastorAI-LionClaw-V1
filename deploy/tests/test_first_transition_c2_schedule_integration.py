"""Nominal cron -> bounded systemctl -> C2 guard, using fictional children only."""

from pathlib import Path
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from first_transition_c2_systemctl import SystemctlReadRunner
from initial_transition_ops import Refused
from test_first_transition_c2_guards import GuardWorld
from test_first_transition_c2_native_integration import ContainmentFixture
from test_first_transition_c2_systemctl import PRIVATE, World


@pytest.fixture(autouse=True)
def no_native_process_or_socket(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("unexpected native process or socket")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)


def wire(g, tmp_path, *, units=None, deadline=None):
    cli = World(tmp_path)
    cli.stdout = g.run_result[1]
    runner = SystemctlReadRunner(
        g.schedule.units if units is None else units,
        deadline=g.admission.deadline if deadline is None else deadline,
        enabled=True,
        synthetic_only=True,
        clock=g.clock,
        popen=cli.spawn,
    )
    g.schedule.run = runner
    # Admit the new callable identity before acquiring any lease. The nominal
    # unit/path metadata pins and fictional receipts are unchanged.
    g.guard = g.make_guard()
    return cli, runner


def test_real_transport_probe_and_guard_compose_without_native_io(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DBUS_SYSTEM_BUS_ADDRESS", "fixture-private-remote")
    g = GuardWorld(tmp_path)
    cli, _runner = wire(g, tmp_path)
    g.guard.acquire()
    try:
        proof = g.prove()
        assert proof.baseline_current is proof.cron_window_clear is True
        assert proof.checked_at == 100.0 and proof.expires_at <= 100.9
        assert len(cli.calls) == len(g.db.calls) == len(g.writers.calls) == 1
        assert g.calls == []  # The former unbounded fake callback was not used.
        argv, options = cli.calls[0]
        assert tuple(argv) == g.schedule.argv("synthetic.timer")
        assert "DBUS_SYSTEM_BUS_ADDRESS" not in options["env"]
        assert options["cwd"] == "/" and options["shell"] is False
        assert cli.children[0].stdout.file.closed
        assert cli.children[0].stderr.file.closed
    finally:
        g.guard.close()


@pytest.mark.parametrize(
    "fault", ["stderr", "overflow", "wrong-unit", "expired", "wrong-status"]
)
def test_bad_scheduler_observation_stops_before_sql_and_never_retries(tmp_path, fault):
    g = GuardWorld(tmp_path)
    cli, _runner = wire(
        g,
        tmp_path,
        units=("unadmitted.timer",) if fault == "wrong-unit" else None,
        deadline=100.5 if fault == "expired" else None,
    )
    if fault == "stderr":
        cli.stderr = PRIVATE.encode()
    elif fault == "overflow":
        cli.stdout = b"x" * 4097
    elif fault == "wrong-status":
        cli.stdout = g.run_result[1].replace(b"inactive", b"active")
    g.guard.acquire()
    if fault == "expired":
        g.now = 101.0
    try:
        with pytest.raises(Refused) as caught:
            g.prove()
        assert str(caught.value) == "c2-native-guard-refused"
        assert caught.value.__context__ is None
        assert PRIVATE not in repr(caught.value)
        count = len(cli.calls)
        assert count == (0 if fault in ("wrong-unit", "expired") else 1)
        assert not g.db.calls and not g.writers.calls and not g.calls
        with pytest.raises(Refused):
            g.prove()
        assert len(cli.calls) == count
        assert not g.db.calls and not g.writers.calls
        assert all(c.stdout.file.closed and c.stderr.file.closed for c in cli.children)
    finally:
        g.guard.close()


@pytest.mark.parametrize("stage", ["spawn", "wait"])
def test_cli_cancellation_seals_guard_without_sql_or_next_child(tmp_path, stage):
    g = GuardWorld(tmp_path)
    cli, _runner = wire(g, tmp_path)
    cancelled = KeyboardInterrupt("fixture-cancel")
    if stage == "spawn":
        cli.spawn_error = cancelled
    else:
        cli.hook = lambda child: setattr(child, "wait_error", cancelled)
    g.guard.acquire()
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            g.prove()
        assert caught.value is cancelled
        assert not g.db.calls and not g.writers.calls
        with pytest.raises(Refused):
            g.prove()
        assert len(cli.calls) == 1
        assert all(c.stdout.file.closed and c.stderr.file.closed for c in cli.children)
    finally:
        g.guard.close()


def test_policy_path_drift_refuses_before_any_open_or_cli(tmp_path, monkeypatch):
    g = GuardWorld(tmp_path)
    cli, _runner = wire(g, tmp_path)
    g.guard.acquire()
    try:
        g.schedule.cron_files = ("/etc/shadow",)

        def forbidden_open(*_args, **_kwargs):
            pytest.fail("unadmitted path opened")

        monkeypatch.setattr("os.open", forbidden_open)
        with pytest.raises(Refused):
            g.prove()
        assert not cli.calls and not g.db.calls and not g.writers.calls
    finally:
        g.guard.close()


def test_guard_with_transport_keeps_explicit_nonfixture_use_closed(tmp_path):
    g = GuardWorld(tmp_path)
    cli, _runner = wire(g, tmp_path)
    g.guard = g.make_guard(synthetic_only=False)
    with pytest.raises(Refused):
        g.guard.acquire()
    assert not cli.calls and not g.db.calls and not g.writers.calls


def test_full_fictional_containment_uses_bounded_scheduler_at_every_guard(tmp_path):
    f = ContainmentFixture(tmp_path)
    cli, _runner = wire(f.guards, tmp_path)
    f.guard = f.guards.guard
    f.driver.guard = f.guard
    f.guard.acquire()
    try:
        result = f.driver.run()
        assert result["status"] == "broadcast-held"
        assert result["production_ready"] is False
        assert result["operational_dispatch_enabled"] is False
        assert f.effects == ["restart-no", "TERM"]  # Fictitious Docker state only.
        assert len(cli.calls) > 1 and f.guards.calls == []
        assert len(f.guards.db.calls) == len(cli.calls)
        assert all(c.stdout.file.closed and c.stderr.file.closed for c in cli.children)
    finally:
        f.guard.close()


def test_scheduler_transport_failure_prevents_first_broadcast_effect(tmp_path):
    f = ContainmentFixture(tmp_path)
    cli, _runner = wire(f.guards, tmp_path)
    cli.stderr = PRIVATE.encode()
    f.guard = f.guards.guard
    f.driver.guard = f.guard
    f.guard.acquire()
    try:
        with pytest.raises(Refused):
            f.driver.run()
        assert f.effects == []
        assert list(f.journal_root.iterdir()) == []
        assert not f.guards.db.calls and not f.guards.writers.calls
        assert len(cli.calls) == 1
    finally:
        f.guard.close()
