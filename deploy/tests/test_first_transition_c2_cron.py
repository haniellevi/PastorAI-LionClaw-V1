"""Nominal paths, refusal before IO and fixture-only schedule composition."""

from dataclasses import FrozenInstanceError
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from first_transition_c2_cron import CronPathPolicy, CODE
from first_transition_c2_guards import NativeScheduleProbe
from initial_transition_ops import Refused
from test_first_transition_c2_guards import GuardWorld


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def deny(*_args, **_kwargs):
        pytest.fail("native process or socket attempted")

    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(socket, "socket", deny)


def test_exact_nominal_names_and_fixture_mapping_without_io(tmp_path, monkeypatch):
    def deny(*_args, **_kwargs):
        pytest.fail("filesystem access during pure admission")

    monkeypatch.setattr(os, "open", deny)
    names = (
        "/etc/crontab",
        "/etc/cron.d/broadcast-disabled",
        "/var/spool/cron/crontabs/root",
    )
    real = CronPathPolicy(names)
    assert real.paths == names and real.admit(names) is True
    mapped = CronPathPolicy(names, fixture_root=str(tmp_path), synthetic_only=True)
    assert mapped.paths == tuple(str(tmp_path) + n for n in names)
    assert mapped.digest != real.digest and mapped.admit(mapped.paths) is True
    assert "crontab" not in repr(mapped)
    with pytest.raises(FrozenInstanceError):
        mapped.files = ()


@pytest.mark.parametrize(
    "path",
    [
        "/etc/shadow",
        "/etc/passwd",
        "/etc/cron.d",
        "/etc/cron.d/",
        "/etc/cron.d/*",
        "/etc/cron.d/../shadow",
        "/etc/cron.d/job/child",
        "/etc/cron.d/.hidden",
        "/etc/cron.d/job.disabled",
        "/etc/cron.d/job~",
        "/etc/cron.d/-option",
        "/etc//cron.d/job",
        "//etc/cron.d/job",
        "/etc/./cron.d/job",
        "etc/cron.d/job",
        "/etc/cron.d/job\n",
        "/etc/cron.d/job\x00",
        "/var/spool/cron/root",
        "/var/spool/cron/crontabs",
        "/var/spool/cron/crontabs/root/other",
        "/var/spool/cron/crontabs/Root",
        "/var/spool/cron/crontabs/*",
        "/etc/cron.hourly/private-script",
        "/tmp/job",
        "/etc/cron.d/.env",
    ],
)
def test_non_nominal_paths_refuse_before_any_io(path, monkeypatch):
    monkeypatch.setattr(os, "open", lambda *_a, **_k: pytest.fail("unexpected IO"))
    with pytest.raises(Refused) as exc:
        CronPathPolicy((path,))
    assert str(exc.value) == CODE and exc.value.__context__ is None


@pytest.mark.parametrize(
    "files", [(), ["/etc/crontab"], ("/etc/crontab",) * 2, (None,), ([],)]
)
def test_invalid_inventory_refuses(files):
    with pytest.raises(Refused):
        CronPathPolicy(files)


@pytest.mark.parametrize(
    "root,seal",
    [
        ("/tmp/fixture", False),
        ("/tmp", True),
        ("/home/fixture", True),
        ("/tmp/x/../y", True),
        ("//tmp/x", True),
        ("/tmp/x/", True),
        ("/tmp/x", 1),
    ],
)
def test_fixture_prefix_requires_explicit_literal_seal_and_normalized_private_namespace(
    root, seal
):
    with pytest.raises(Refused):
        CronPathPolicy(("/etc/crontab",), fixture_root=root, synthetic_only=seal)


def test_inventory_is_exact_and_ordered():
    policy = CronPathPolicy(("/etc/crontab", "/etc/cron.d/declared"))
    for paths in (
        ("/etc/crontab",),
        tuple(reversed(policy.paths)),
        policy.paths + ("/etc/cron.d/extra",),
        list(policy.paths),
    ):
        with pytest.raises(Refused):
            policy.admit(paths)


def test_probe_requires_nominal_policy_before_reads_or_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "open", lambda *_a, **_k: pytest.fail("unexpected IO"))
    for policy, paths in (
        (None, ("/etc/shadow",)),
        (CronPathPolicy(("/etc/crontab",)), ("/etc/shadow",)),
    ):
        with pytest.raises(Refused):
            NativeScheduleProbe(
                units=("synthetic.timer",),
                cron_files=paths,
                cron_policy=policy,
                run=lambda *_a, **_k: pytest.fail("unexpected runner"),
                enabled=True,
                synthetic_only=True,
            )


def test_real_root_is_never_read_by_fixture_probe(monkeypatch):
    policy = CronPathPolicy(("/etc/crontab",), synthetic_only=True)
    probe = NativeScheduleProbe(
        units=("synthetic.timer",),
        cron_files=policy.paths,
        cron_policy=policy,
        run=lambda *_a, **_k: pytest.fail("unexpected runner"),
        enabled=True,
        synthetic_only=True,
    )
    monkeypatch.setattr(
        os, "open", lambda *_a, **_k: pytest.fail("host-file read attempted")
    )
    with pytest.raises(Refused):
        probe.verify({"/etc/crontab": "a" * 64}, timeout=1)


def test_path_mutation_and_policy_drift_refuse_before_open(tmp_path, monkeypatch):
    w = GuardWorld(tmp_path)
    w.schedule.cron_files = ("/etc/shadow",)
    monkeypatch.setattr(os, "open", lambda *_a, **_k: pytest.fail("unexpected IO"))
    with pytest.raises(Refused):
        w.schedule.verify({"/etc/shadow": "a" * 64}, timeout=1)
    w.schedule.cron_files = w.cron_policy.paths
    w.schedule.cron_policy = CronPathPolicy(
        ("/etc/cron.d/different",), fixture_root=str(tmp_path), synthetic_only=True
    )
    with pytest.raises(Refused):
        w.schedule.verify({w.schedule.cron_files[0]: "a" * 64}, timeout=1)
    assert not w.calls


def test_guard_receipt_binds_policy_identity_even_for_equal_policy(tmp_path):
    w = GuardWorld(tmp_path)
    w.schedule.cron_policy = CronPathPolicy(
        w.cron_policy.files,
        fixture_root=w.cron_policy.fixture_root,
        synthetic_only=True,
    )
    with pytest.raises(Refused):
        w.guard.acquire()
    assert not w.calls and not w.db.calls


def test_fixture_symlink_cannot_escape_nominal_path_policy(tmp_path):
    w = GuardWorld(tmp_path)
    outside = tmp_path / "outside-private-fixture"
    outside.write_bytes(b"PRIVATE-FIXTURE-CONTENT")
    w.cron.unlink()
    w.cron.symlink_to(outside)
    w.guard.acquire()
    try:
        with pytest.raises(Refused):
            w.prove()
        assert not w.calls and not w.db.calls
        assert outside.read_bytes() == b"PRIVATE-FIXTURE-CONTENT"
    finally:
        w.guard.close()
