"""Containment driver contracts, fictional snapshots and private local files only."""

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_c2_containment as c2
from first_transition_adapter import ROLES, digest
from first_transition_c2_adapter import Observation
from first_transition_host_driver import HostManifest, MANDATORY_GATES, SCHEMA
from first_transition_host_transport import SUPPORT_ROLES
from initial_transition_ops import Refused

PRIVATE = "SYNTHETIC-C2-PRIVATE-SENTINEL"


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("unexpected native process/socket")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)


class World:
    def __init__(self, tmp_path):
        self.now = 100.0
        self.calls = []
        self.effects = []
        self.fault = None
        self.manifest = HostManifest.from_dict(
            dict(
                schema=SCHEMA,
                daemon_id="01234567-89ab-4cde-8fab-0123456789ab",
                legacy_project="synthetic",
                network_id="e" * 64,
                service_ids={r: str(i) * 64 for i, r in enumerate(ROLES, 1)},
                support_ids={r: str(i) * 64 for i, r in zip((5, 6, 7), SUPPORT_ROLES)},
                processing_keys=[],
                gate_names=list(MANDATORY_GATES),
            )
        )
        self.target = dict(self.manifest.service_ids)["broadcast-worker"]
        net = {
            "EndpointsConfig": {"synthetic": {"NetworkID": self.manifest.network_id}}
        }
        config = {
            "Config": {
                "Image": "sha256:" + "f" * 64,
                "Env": [
                    "TOKEN=" + PRIVATE,
                    "ALLOW_REAL_SENDS=true",
                    "ALLOW_REAL_SENDS=true",
                ],
                "Labels": {},
            },
            "HostConfig": {"RestartPolicy": {"Name": "always", "MaximumRetryCount": 0}},
            "NetworkingConfig": net,
        }
        row = Observation(
            self.target,
            self.manifest.daemon_id,
            "sha256:" + "f" * 64,
            "broadcast-worker",
            True,
            "running",
            0,
            "always",
            config,
            digest(net),
            True,
        )
        self.original = c2.Snapshot(
            row, "/synthetic-broadcast", "2026-11-01T00:00:00Z", 0
        )
        self.row = deepcopy(self.original)
        self.tmp = tmp_path

    def guard(self, scope, nonce):
        return c2.GuardProof(
            scope,
            nonce,
            self.now,
            min(101, self.now + 0.9),
            True,
            True,
            True,
            True,
            False,
        )

    def observe(self, target):
        assert target == self.target
        if self.fault == "drift-after-update" and self.effects:
            return replace(self.row, restart_count=1)
        return deepcopy(self.row)

    def runner(self, argv, **kwargs):
        self.calls.append(argv)
        if argv == c2.INFO_ARGV:
            return 0, (json.dumps(self.manifest.daemon_id) + "\n").encode()
        self.effects.append(argv[1])
        row = self.row.observation
        config = deepcopy(row.private_config)
        if argv[1] == "update":
            config["HostConfig"]["RestartPolicy"] = {
                "Name": "no",
                "MaximumRetryCount": 0,
            }
            self.row = replace(
                self.row, observation=replace(row, private_config=config, restart="no")
            )
        elif argv[1] == "kill":
            assert argv == ("docker", "kill", "--signal=TERM", self.target)
            if self.fault != "never-exit":
                self.row = replace(
                    self.row,
                    observation=replace(
                        row,
                        running=False,
                        status="exited",
                        exit_code=7 if self.fault == "bad-exit" else 0,
                    ),
                )
        else:
            raise AssertionError("unexpected command")
        if self.fault == "lost-ack" and argv[1] == "update":
            raise RuntimeError(PRIVATE)
        return 0, (self.target + "\n").encode()

    def driver(self, **kw):
        return c2.BroadcastContainment(
            self.manifest,
            original=self.original,
            observe=self.observe,
            guard=self.guard,
            runner=self.runner,
            state_root=self.tmp,
            nonce="synthetic-attempt",
            deadline=101,
            enabled=True,
            clock=lambda: self.now,
            sleep=lambda n: setattr(self, "now", self.now + n),
            owner_uid=os.geteuid(),
            **kw,
        )


def test_happy_path_durable_private_custody_and_no_gate_change(tmp_path):
    w = World(tmp_path)
    d = w.driver()
    r = d.run()
    assert (
        r["status"] == "broadcast-held"
        and not r["replacement_started"]
        and not r["operational_dispatch_enabled"]
    )
    assert w.effects == ["update", "kill"] and d.stage == "held" and not d.uncertain
    folder = tmp_path / ("broadcast-" + w.target)
    assert folder.stat().st_mode & 0o777 == 0o700
    before = folder / "before.json"
    events = folder / "events.jsonl"
    assert before.stat().st_mode & 0o777 == events.stat().st_mode & 0o777 == 0o600
    assert (
        json.loads(before.read_text())["private_config"]
        == w.original.observation.private_config
    )
    lines = [json.loads(v) for v in events.read_text().splitlines()]
    assert lines == [
        {"kind": "intent", "step": "restart-no"},
        {"kind": "confirmed", "step": "restart-no"},
        {"kind": "intent", "step": "term"},
        {"kind": "confirmed", "step": "term"},
        {"kind": "complete", "step": "held"},
    ]
    assert (
        PRIVATE not in repr(r)
        and PRIVATE not in events.read_text()
        and PRIVATE not in repr(w.original)
    )


def test_default_closed_before_any_callback_or_journal(tmp_path):
    w = World(tmp_path)
    d = w.driver()
    d.enabled = False
    with pytest.raises(Refused):
        d.run()
    assert w.calls == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("exclusive", False),
        ("baseline_current", False),
        ("cron_window_clear", False),
        ("backup_recovery_ready", False),
        ("ddl_started", True),
        ("exclusive", 1),
        ("scope", "foreign"),
        ("nonce", "foreign"),
        ("checked_at", 98),
        ("checked_at", 101),
        ("expires_at", 100),
        ("expires_at", 200),
    ],
)
def test_guard_refuses_before_any_effect_or_journal(tmp_path, field, value):
    w = World(tmp_path)
    g = w.guard
    w.guard = lambda s, n: replace(g(s, n), **{field: value})
    with pytest.raises(Refused):
        w.driver().run()
    assert w.calls == [] and list(tmp_path.iterdir()) == []


def test_identity_drift_after_policy_never_signals(tmp_path):
    w = World(tmp_path)
    w.fault = "drift-after-update"
    d = w.driver()
    with pytest.raises(Refused):
        d.run()
    assert w.effects == ["update"] and d.uncertain


def test_lost_ack_is_private_uncertain_and_cannot_retry(tmp_path):
    w = World(tmp_path)
    w.fault = "lost-ack"
    d = w.driver()
    with pytest.raises(Refused) as caught:
        d.run()
    assert (
        str(caught.value) == c2.CODE
        and PRIVATE not in str(caught.value)
        and caught.value.__cause__ is None
    )
    assert w.effects == ["update"] and d.uncertain
    with pytest.raises(Refused):
        d.run()
    assert w.effects == ["update"]


def test_durable_target_claim_blocks_new_driver_attempt(tmp_path):
    w = World(tmp_path)
    w.driver().run()
    after = deepcopy(w.effects)
    w.row = deepcopy(w.original)
    with pytest.raises(Refused):
        w.driver().run()
    assert w.effects == after


def test_fsync_failure_before_effect_stops(tmp_path):
    w = World(tmp_path)
    with patch.object(c2.os, "fsync", side_effect=OSError(PRIVATE)):
        with pytest.raises(Refused):
            w.driver().run()
    assert w.effects == []


def test_journal_intent_failure_prevents_first_effect(tmp_path):
    w = World(tmp_path)
    with patch.object(c2.PrivateJournal, "append", side_effect=OSError(PRIVATE)):
        with pytest.raises(Refused):
            w.driver().run()
    assert w.effects == []


@pytest.mark.parametrize("fault", ["never-exit", "bad-exit"])
def test_timeout_or_abnormal_exit_never_forces_or_resumes(tmp_path, fault):
    w = World(tmp_path)
    w.fault = fault
    d = w.driver()
    with pytest.raises(Refused):
        d.run()
    assert w.effects == ["update", "kill"] and d.uncertain
    assert all(
        a[1] not in ("start", "stop", "restart", "rm", "create")
        and "--signal=KILL" not in a
        for a in w.calls
    )


def test_cancel_preserves_pending_intent(tmp_path):
    w = World(tmp_path)
    real = w.runner

    def runner(argv, **kw):
        if argv[1] == "kill":
            raise KeyboardInterrupt()
        return real(argv, **kw)

    w.runner = runner
    d = w.driver()
    with pytest.raises(KeyboardInterrupt):
        d.run()
    assert d.uncertain and w.effects == ["update"]


def test_native_runner_whitelist_never_accepts_other_target_or_start(tmp_path):
    w = World(tmp_path)
    r = c2.BroadcastRunner(
        manifest=w.manifest,
        docker_binary="/synthetic/docker",
        endpoint="unix:///synthetic/docker.sock",
        config_dir="/synthetic/config",
    )
    assert r._allowed(c2.INFO_ARGV)
    assert r._allowed(("docker", "update", "--restart=no", w.target))
    assert r._allowed(("docker", "kill", "--signal=TERM", w.target))
    for a in [
        ("docker", "stop", w.target),
        ("docker", "kill", "--signal=KILL", w.target),
        ("docker", "start", w.target),
        ("docker", "update", "--restart=always", w.target),
        ("docker", "update", "--restart=no", "a" * 64),
        ("docker", "inspect", w.target),
    ]:
        assert not r._allowed(a)
        with pytest.raises(Refused):
            r(a, timeout=1, max_output=16)


def test_close_error_cannot_leak_private_exception_or_report_success(tmp_path):
    w = World(tmp_path)
    real = c2.PrivateJournal.close

    def close(journal):
        real(journal)
        raise OSError(PRIVATE)

    with patch.object(c2.PrivateJournal, "close", close):
        with pytest.raises(Refused) as e:
            w.driver().run()
    assert str(e.value) == c2.CODE and e.value.__context__ is None


@pytest.mark.parametrize("seam", ["factory", "save", "intent", "confirmed", "close"])
def test_slow_custody_or_journal_never_allows_next_effect(tmp_path, seam):
    w = World(tmp_path)
    d = w.driver()
    if seam == "factory":

        def factory(*a):
            j = c2.PrivateJournal(*a)
            w.now = 102
            return j

        d.journal_factory = factory
        context = patch.object(c2, "CODE", c2.CODE)
    elif seam == "save":
        real = c2.PrivateJournal.save

        def slow(j, *a):
            real(j, *a)
            w.now = 102

        context = patch.object(c2.PrivateJournal, "save", slow)
    elif seam == "close":
        real = c2.PrivateJournal.close

        def slow(j):
            real(j)
            w.now = 102

        context = patch.object(c2.PrivateJournal, "close", slow)
    else:
        real = c2.PrivateJournal.append

        def slow(j, kind, step):
            real(j, kind, step)
            if kind == seam:
                w.now = 102

        context = patch.object(c2.PrivateJournal, "append", slow)
    with context:
        with pytest.raises(Refused):
            d.run()
    assert w.effects == (
        {"confirmed": ["update"], "close": ["update", "kill"]}.get(seam, [])
    )


def test_cancellation_survives_ordinary_close_error(tmp_path):
    w = World(tmp_path)
    real_runner = w.runner
    real_close = c2.PrivateJournal.close

    def runner(argv, **kw):
        if argv[1] == "kill":
            raise KeyboardInterrupt()
        return real_runner(argv, **kw)

    def close(j):
        real_close(j)
        raise OSError(PRIVATE)

    w.runner = runner
    d = w.driver()
    with patch.object(c2.PrivateJournal, "close", close):
        with pytest.raises(KeyboardInterrupt):
            d.run()
    assert d.uncertain and w.effects == ["update"]


def test_external_mutation_cannot_redefine_captured_private_baseline(tmp_path):
    w = World(tmp_path)
    d = w.driver()
    w.row.observation.private_config["Config"]["Env"].append("FOREIGN=changed")
    w.original.observation.private_config["Config"]["Env"].append("FOREIGN=changed")
    with pytest.raises(Refused):
        d.run()
    assert w.effects == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "/foreign"),
        ("started_at", "2026-11-02T00:00:00Z"),
        ("restart_count", 1),
    ],
)
def test_observation_identity_field_drift_before_custody(tmp_path, field, value):
    w = World(tmp_path)
    w.row = replace(w.row, **{field: value})
    with pytest.raises(Refused):
        w.driver().run()
    assert w.effects == [] and list(tmp_path.iterdir()) == []


def test_wrong_network_intent_cannot_be_admitted(tmp_path):
    w = World(tmp_path)
    config = deepcopy(w.original.observation.private_config)
    config["NetworkingConfig"]["EndpointsConfig"]["synthetic"]["NetworkID"] = "b" * 64
    w.original = replace(
        w.original,
        observation=replace(
            w.original.observation,
            private_config=config,
            network_intent_sha256=digest(config["NetworkingConfig"]),
        ),
    )
    with pytest.raises(Refused):
        w.driver().run()
    assert w.calls == []


def test_private_journal_refuses_unsafe_target_before_any_filesystem(tmp_path):
    with patch.object(c2.os, "open", side_effect=AssertionError("filesystem reached")):
        with pytest.raises(Refused):
            c2.PrivateJournal(tmp_path, "../foreign", os.geteuid())
