"""Compose C2 native producers and containment using fictional endpoints only."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from first_transition_c2_containment import BroadcastContainment
from first_transition_c2_native import NativeSnapshotProducer
from initial_transition_ops import Refused
from test_first_transition_c2_guards import GuardWorld
from test_first_transition_c2_native import World


@pytest.fixture(autouse=True)
def no_native_io(monkeypatch):
    def deny(*_args, **_kwargs):
        pytest.fail("native process or socket attempted")

    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(socket, "socket", deny)


class ContainmentFixture:
    def __init__(self, tmp_path):
        self.world = World()
        w = self.world
        self.guards = GuardWorld(
            tmp_path, scope=w.manifest.digest, target=w.target, nonce="fixture_nonce"
        )
        g = self.guards
        self.guard = g.guard
        self.effects = []
        self.after_policy = None
        self.producer = NativeSnapshotProducer(
            w.manifest,
            w.admission,
            runner=w.run,
            deadline=self.guard.admission.deadline,
            enabled=True,
            clock=lambda: g.now,
        )
        self.original = self.producer(w.target)
        self.journal_root = tmp_path / "containment-journal"
        self.journal_root.mkdir(mode=0o700)
        self.driver = BroadcastContainment(
            w.manifest,
            original=self.original,
            observe=self.producer,
            guard=self.guard,
            runner=self.run,
            state_root=self.journal_root,
            nonce="fixture_nonce",
            deadline=self.guard.admission.deadline,
            enabled=True,
            clock=lambda: g.now,
            sleep=lambda _delay: pytest.fail("fixture should exit immediately"),
            owner_uid=os.geteuid(),
        )

    def run(self, argv, **bounds):
        w = self.world
        if argv == ("docker", "info", "--format", "{{json .ID}}"):
            return w.run(argv, **bounds)
        assert bounds["timeout"] > 0 and bounds["max_output"] == 256
        assert argv[-1] == w.target
        if argv == ("docker", "update", "--restart=no", w.target):
            self.effects.append("restart-no")
            w.row[4]["RestartPolicy"] = {"Name": "no", "MaximumRetryCount": 0}
            if self.after_policy is not None:
                self.after_policy()
        elif argv == ("docker", "kill", "--signal=TERM", w.target):
            self.effects.append("TERM")
            w.row[5].update(Status="exited", Running=False, ExitCode=0, Pid=0)
            w.row[7] = {}
        else:
            pytest.fail("unadmitted fixture effect")
        return 0, (w.target + "\n").encode()

    def marker(self):
        (Path(self.guard.state_root) / "ddl-marker").write_text("fixture-only")


def test_native_producers_compose_into_held_broadcast_with_private_journal(tmp_path):
    f = ContainmentFixture(tmp_path)
    f.guard.acquire()
    try:
        result = f.driver.run()
        assert result == {
            "status": "broadcast-held",
            "production_ready": False,
            "original_removed": False,
            "replacement_started": False,
            "operational_dispatch_enabled": False,
        }
        assert f.effects == ["restart-no", "TERM"]
        assert f.world.row[5]["Running"] is False
        assert f.driver.stage == "held" and f.driver.uncertain is False
        journal = f.journal_root / ("broadcast-" + f.world.target)
        before = json.loads((journal / "before.json").read_bytes())
        assert before["private_config"]["Config"]["Image"] == f.world.image
        assert len((journal / "events.jsonl").read_text().splitlines()) == 5
        assert (journal / "before.json").stat().st_mode & 0o777 == 0o600
        assert all(call[0][0] == "docker" for call in f.world.calls)
    finally:
        f.guard.close()


@pytest.mark.parametrize("failure", ["ddl", "missing-recovery", "expired"])
def test_invalid_native_guards_refuse_before_any_containment_effect(tmp_path, failure):
    f = ContainmentFixture(tmp_path)
    f.guard.acquire()
    try:
        if failure == "ddl":
            f.marker()
        elif failure == "missing-recovery":
            (Path(f.guard.state_root) / "recovery.json").unlink()
        else:
            f.guards.now = f.guard.admission.deadline
        with pytest.raises(Refused) as exc:
            f.driver.run()
        assert str(exc.value) == "c2-containment-refused"
        assert exc.value.__context__ is None
        assert f.effects == []
        assert list(f.journal_root.iterdir()) == []
        assert f.world.row[4]["RestartPolicy"]["Name"] == "always"
        assert f.world.row[5]["Running"] is True
    finally:
        f.guard.close()


def test_guard_loss_after_policy_change_keeps_uncertainty_and_never_terms(tmp_path):
    f = ContainmentFixture(tmp_path)
    f.after_policy = f.marker
    f.guard.acquire()
    try:
        with pytest.raises(Refused):
            f.driver.run()
        assert f.effects == ["restart-no"]
        assert f.driver.uncertain is True
        assert f.world.row[5]["Running"] is True
        assert f.world.row[4]["RestartPolicy"]["Name"] == "no"
        journal = f.journal_root / ("broadcast-" + f.world.target)
        events = [
            json.loads(line)
            for line in (journal / "events.jsonl").read_text().splitlines()
        ]
        assert events == [{"kind": "intent", "step": "restart-no"}]
        with pytest.raises(Refused):
            f.driver.run()
        assert f.effects == ["restart-no"]
    finally:
        f.guard.close()


def test_native_snapshot_drift_refuses_before_journal_or_effects(tmp_path):
    f = ContainmentFixture(tmp_path)
    f.world.row[3]["Image"] = "synthetic:different-reference"
    f.guard.acquire()
    try:
        with pytest.raises(Refused):
            f.driver.run()
        assert f.effects == [] and list(f.journal_root.iterdir()) == []
        assert f.world.row[5]["Running"] is True
    finally:
        f.guard.close()
