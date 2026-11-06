"""Admission and lifecycle ownership boundaries; real primitives, fictional IO."""

from dataclasses import replace
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_c2_lifecycle as lifecycle
from c2_lifecycle_fixture import SessionFixture
from initial_transition_ops import Refused
from test_first_transition_c2_native import PRIVATE


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def deny(*_args, **_kwargs):
        pytest.fail("real process/socket attempted")

    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(socket, "socket", deny)


def refused(call):
    with pytest.raises(Refused) as caught:
        call()
    assert str(caught.value) == lifecycle.CODE
    assert caught.value.__context__ is None
    assert PRIVATE not in repr(caught.value)


def test_constructor_is_pure_and_private_even_for_default_closed_session(
    tmp_path, monkeypatch
):
    f = SessionFixture(tmp_path)
    monkeypatch.setattr(os, "open", lambda *_a, **_k: pytest.fail("constructor IO"))
    session = f.session(enabled=False, synthetic_only=False)
    assert PRIVATE not in repr(session)
    assert not f.docker.calls and not f.scheduler.calls
    refused(session.run)
    assert session.used is True and not f.effects


@pytest.mark.parametrize(
    "options",
    [
        {"enabled": False},
        {"enabled": 1},
        {"synthetic_only": False},
        {"synthetic_only": 1},
    ],
)
def test_session_seals_refuse_before_any_file_or_process_and_latch(
    tmp_path, monkeypatch, options
):
    f = SessionFixture(tmp_path)
    session = f.session(**options)
    monkeypatch.setattr(os, "open", lambda *_a, **_k: pytest.fail("unexpected IO"))
    refused(session.run)
    session.enabled = session.synthetic_only = True
    refused(session.run)
    assert not f.docker.calls and not f.scheduler.calls
    assert f.guards.guard.root is None and f.guards.guard.lease is None


@pytest.mark.parametrize(
    "fault", ["scope", "deadline", "clock", "endpoint", "grammar", "popen"]
)
def test_crossed_bindings_refuse_at_pure_construction(tmp_path, monkeypatch, fault):
    f = SessionFixture(tmp_path)
    if fault == "scope":
        f.guards.guard.admission = replace(f.guards.guard.admission, scope="9" * 64)
    elif fault == "deadline":
        f.observer._deadline += 1
    elif fault == "clock":
        f.observer._clock = lambda: f.guards.now
    elif fault == "endpoint":
        f.runner.endpoint = "unix:///fixture/other.sock"
    elif fault == "grammar":
        f.read_runner._commands += (("docker", "logs", f.world.target),)
    else:
        f.runner.popen = lambda *_a, **_k: pytest.fail("alternate backend invoked")
    monkeypatch.setattr(os, "open", lambda *_a, **_k: pytest.fail("unexpected IO"))
    refused(f.session)
    assert not f.docker.calls and not f.scheduler.calls


@pytest.mark.parametrize("used", ["observer", "scheduler", "guard"])
def test_previously_used_sources_are_not_adopted(tmp_path, used):
    f = SessionFixture(tmp_path)
    if used == "observer":
        f.observer(f.world.target)
    elif used == "scheduler":
        f.schedule_runner(
            f.guards.schedule.argv("synthetic.timer"), timeout=1, max_output=4096
        )
    else:
        f.guards.guard.acquire()
        f.guards.prove()
        f.guards.guard.close()
    calls = (len(f.docker.calls), len(f.scheduler.calls))
    refused(f.session().run)
    assert calls == (len(f.docker.calls), len(f.scheduler.calls))
    assert f.guards.guard.root is None and f.guards.guard.lease is None
    assert not f.effects


@pytest.mark.parametrize("cancel", [False, True])
def test_partial_acquire_failure_always_releases_owned_lease(
    tmp_path, monkeypatch, cancel
):
    f = SessionFixture(tmp_path)
    acquire = f.guards.guard.acquire
    error = KeyboardInterrupt("fixture-cancel") if cancel else RuntimeError(PRIVATE)

    def partial():
        acquire()
        raise error

    monkeypatch.setattr(f.guards.guard, "acquire", partial)
    session = f.session()
    if cancel:
        with pytest.raises(KeyboardInterrupt) as caught:
            session.run()
        assert caught.value is error
    else:
        refused(session.run)
    assert f.guards.guard.root is None and f.guards.guard.lease is None
    assert not f.docker.calls and not f.scheduler.calls and not f.effects
    refused(session.run)


@pytest.mark.parametrize("cancel", [False, True])
def test_driver_constructor_failure_releases_after_guarded_snapshot(
    tmp_path, monkeypatch, cancel
):
    f = SessionFixture(tmp_path)
    error = KeyboardInterrupt("fixture-cancel") if cancel else RuntimeError(PRIVATE)

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(lifecycle, "BroadcastContainment", fail)
    session = f.session()
    if cancel:
        with pytest.raises(KeyboardInterrupt) as caught:
            session.run()
        assert caught.value is error
    else:
        refused(session.run)
    assert f.docker.calls and f.scheduler.calls
    assert f.guards.guard.root is None and f.guards.guard.lease is None
    assert not f.effects and not f.journal.exists()
    assert all(child.stdout.closed for child in f.docker.children)


def test_primary_cancellation_survives_cleanup_cancellation(tmp_path, monkeypatch):
    f = SessionFixture(tmp_path)
    acquire, close = f.guards.guard.acquire, f.guards.guard.close
    first, second = KeyboardInterrupt("first"), KeyboardInterrupt("second")

    def partial():
        acquire()
        raise first

    def release():
        close()
        raise second

    monkeypatch.setattr(f.guards.guard, "acquire", partial)
    monkeypatch.setattr(f.guards.guard, "close", release)
    session = f.session()
    with pytest.raises(KeyboardInterrupt) as caught:
        session.run()
    assert caught.value is first and session.uncertain is True
    assert f.guards.guard.root is None and f.guards.guard.lease is None
    refused(session.run)
    assert session.uncertain is True and not f.effects


def test_failure_after_driver_success_discards_success_and_latches_uncertainty(
    tmp_path, monkeypatch
):
    f = SessionFixture(tmp_path)
    run = lifecycle.BroadcastContainment.run

    def late_loss(driver):
        result = run(driver)
        f.guards.writers.value = 1
        return result

    monkeypatch.setattr(lifecycle.BroadcastContainment, "run", late_loss)
    session = f.session()
    refused(session.run)
    assert f.effects == ["restart-no", "TERM"] and session.uncertain is True
    assert f.guards.guard.root is None and f.guards.guard.lease is None
    calls = (len(f.docker.calls), len(f.scheduler.calls))
    refused(session.run)
    assert session.uncertain is True
    assert calls == (len(f.docker.calls), len(f.scheduler.calls))


@pytest.mark.parametrize("fault", ["seal", "guard"])
def test_release_hook_cannot_change_scope_or_seal_and_return_success(
    tmp_path, monkeypatch, fault
):
    f = SessionFixture(tmp_path)
    close = f.guards.guard.close
    holder = {}

    def release():
        close()
        if fault == "seal":
            holder["session"].enabled = False
        else:
            holder["session"].guard = f.guards.make_guard()

    monkeypatch.setattr(f.guards.guard, "close", release)
    session = f.session()
    holder["session"] = session
    refused(session.run)
    assert f.effects == ["restart-no", "TERM"] and session.uncertain is True
    assert f.guards.guard.root is None and f.guards.guard.lease is None
    if fault == "guard":
        assert session.guard.root is None and session.guard.lease is None
    calls = (len(f.docker.calls), len(f.scheduler.calls))
    refused(session.run)
    assert session.uncertain is True
    assert calls == (len(f.docker.calls), len(f.scheduler.calls))
