"""Read-only systemctl grammar and bounded transport with fictional children."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_c2_systemctl as transport
from initial_transition_ops import Refused

PRIVATE = "SYSTEMCTL-PRIVATE-FIXTURE-SENTINEL"
UNIT = "synthetic-disabled.timer"
ARGV = (*transport.PREFIX, UNIT)
OUTPUT = (
    b"Id=synthetic-disabled.timer\nLoadState=loaded\n"
    b"ActiveState=inactive\nUnitFileState=masked\n"
)


@pytest.fixture(autouse=True)
def no_native_process_or_socket(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("unexpected real process or socket")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)


class FixtureStream:
    def __init__(self, root, raw):
        self.file = tempfile.TemporaryFile(dir=root)
        self.file.write(raw)
        self.file.seek(0)
        self.close_error = None
        self.close_hook = None

    def fileno(self):
        return self.file.fileno()

    def close(self):
        self.file.close()
        if self.close_hook:
            self.close_hook()
        if self.close_error:
            raise self.close_error


class FixtureProcess:
    def __init__(self, root, stdout, stderr, *, rc=0):
        self.stdout = FixtureStream(root, stdout)
        self.stderr = FixtureStream(root, stderr)
        self.rc = rc
        self.alive, self.kills = True, 0
        self.waits = []
        self.wait_error = self.poll_error = self.kill_error = None

    def poll(self):
        if self.poll_error:
            raise self.poll_error
        return None if self.alive else self.rc

    def kill(self):
        self.kills += 1
        if self.kill_error:
            raise self.kill_error
        self.alive = False

    def wait(self, *, timeout):
        self.waits.append(timeout)
        if self.wait_error:
            error, self.wait_error = self.wait_error, None
            raise error
        self.alive = False
        return self.rc


class World:
    def __init__(self, root):
        self.root, self.now = root, 100.0
        self.stdout, self.stderr, self.rc = OUTPUT, b"", 0
        self.calls, self.children = [], []
        self.spawn_error = self.hook = None

    def spawn(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.spawn_error:
            raise self.spawn_error
        child = FixtureProcess(self.root, self.stdout, self.stderr, rc=self.rc)
        self.children.append(child)
        if self.hook:
            self.hook(child)
        return child

    def runner(self, **kwargs):
        options = dict(
            deadline=110,
            enabled=True,
            synthetic_only=True,
            clock=lambda: self.now,
            popen=self.spawn,
        )
        options.update(kwargs)
        return transport.SystemctlReadRunner((UNIT,), **options)


def refused(call):
    with pytest.raises(Refused) as caught:
        call()
    assert str(caught.value) == transport.CODE
    assert caught.value.__context__ is None
    assert PRIVATE not in repr(caught.value)


def test_nominal_show_uses_exact_command_env_and_only_fixture_children(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DBUS_SYSTEM_BUS_ADDRESS", "unix:path=" + PRIVATE)
    monkeypatch.setenv("SYSTEMD_PAGER", PRIVATE)
    monkeypatch.setenv("HOME", str(tmp_path))
    w = World(tmp_path)
    runner = w.runner()
    assert not w.calls
    assert runner(ARGV, timeout=2, max_output=4096) == (0, OUTPUT)
    args, opts = w.calls[0]
    assert args == list(ARGV)
    assert opts == dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=transport.ENV,
        cwd="/",
        close_fds=True,
        shell=False,
        start_new_session=True,
        bufsize=0,
    )
    assert "DBUS_SYSTEM_BUS_ADDRESS" not in opts["env"]
    assert "HOME" not in opts["env"] and opts["env"]["SYSTEMD_PAGER"] == "cat"
    assert w.children[0].kills == 0 and w.children[0].waits == [2.0]
    assert w.children[0].stdout.file.closed and w.children[0].stderr.file.closed


@pytest.mark.parametrize(
    "options",
    [
        {"enabled": False},
        {"enabled": 1},
        {"synthetic_only": False},
        {"synthetic_only": 1},
    ],
)
def test_seals_require_literal_true_before_io(tmp_path, options):
    w = World(tmp_path)
    refused(lambda: w.runner(**options)(ARGV, timeout=1, max_output=4096))
    assert not w.calls


def test_default_is_closed_without_construction_io(tmp_path):
    w = World(tmp_path)
    runner = transport.SystemctlReadRunner((UNIT,), deadline=110, popen=w.spawn)
    assert not w.calls
    refused(lambda: runner(ARGV, timeout=1, max_output=4096))
    assert not w.calls


@pytest.mark.parametrize(
    "argv",
    [
        ("systemctl", *ARGV[1:]),
        ("/usr/bin/systemctl", "start", UNIT),
        (*ARGV, "--user"),
        (*ARGV, "--host=remote"),
        (*transport.PREFIX, "unadmitted.timer"),
        (*transport.PREFIX, "--remote.timer"),
        (*transport.PREFIX, "synthetic.service"),
        (*transport.PREFIX[:-1], "--property=Environment", UNIT),
        " ".join(ARGV),
    ],
)
def test_mutation_remote_unknown_or_private_projection_refuses_before_io(
    tmp_path, argv
):
    w = World(tmp_path)
    refused(lambda: w.runner()(argv, timeout=1, max_output=4096))
    assert not w.calls


@pytest.mark.parametrize(
    "units", [(), (UNIT, UNIT), ("--bad.timer",), ("x.service",), "x.timer", (None,)]
)
def test_invalid_nominal_unit_inventory_is_rejected_without_io(tmp_path, units):
    w = World(tmp_path)
    refused(lambda: transport.SystemctlReadRunner(units, deadline=110, popen=w.spawn))
    assert not w.calls


@pytest.mark.parametrize(
    "key,value",
    [
        ("timeout", 0),
        ("timeout", True),
        ("timeout", 61),
        ("timeout", float("nan")),
        ("max_output", 0),
        ("max_output", True),
        ("max_output", 4097),
    ],
)
def test_bad_call_bounds_refuse_before_spawn(tmp_path, key, value):
    w = World(tmp_path)
    bounds = dict(timeout=1, max_output=4096)
    bounds[key] = value
    refused(lambda: w.runner()(ARGV, **bounds))
    assert not w.calls


@pytest.mark.parametrize(
    "options",
    [
        {"deadline": 161},
        {"deadline": 100},
        {"max_calls": True},
        {"max_calls": 0},
        {"max_calls": 1025},
    ],
)
def test_invalid_global_budget_or_call_quota_refuses_without_io(tmp_path, options):
    w = World(tmp_path)
    refused(lambda: w.runner(**options)(ARGV, timeout=1, max_output=4096))
    assert not w.calls


def test_global_deadline_caps_process_wait_and_max_calls_seals_no_retry(tmp_path):
    w = World(tmp_path)
    runner = w.runner(deadline=100.5, max_calls=1)
    assert runner(ARGV, timeout=60, max_output=4096) == (0, OUTPUT)
    assert w.children[0].waits == [0.5]
    refused(lambda: runner(ARGV, timeout=1, max_output=4096))
    refused(lambda: runner(ARGV, timeout=1, max_output=4096))
    assert len(w.calls) == 1


@pytest.mark.parametrize("what", ["stdout", "stderr", "exit", "stderr-small"])
def test_output_limits_nonzero_exit_and_private_stderr_refuse_and_close(tmp_path, what):
    w = World(tmp_path)
    cap = 4096
    if what == "stdout":
        w.stdout, cap = b"x" * 9, 8
    elif what == "stderr":
        w.stderr = b"x" * 4097
    elif what == "stderr-small":
        w.stderr = PRIVATE.encode()
    else:
        w.rc = 1
    runner = w.runner()
    refused(lambda: runner(ARGV, timeout=1, max_output=cap))
    refused(lambda: runner(ARGV, timeout=1, max_output=cap))
    assert len(w.calls) == 1
    assert all(c.stdout.file.closed and c.stderr.file.closed for c in w.children)
    assert w.children[0].waits[-1] == 1.0


def test_both_streams_are_bounded_without_waiting_for_one_to_finish(tmp_path):
    w = World(tmp_path)
    w.stdout, w.stderr = b"o" * 4096, b"e" * 4096
    refused(lambda: w.runner()(ARGV, timeout=1, max_output=4096))
    assert w.children[0].stdout.file.closed and w.children[0].stderr.file.closed


def test_spawn_private_failure_is_sanitized_and_permanently_latched(tmp_path):
    w = World(tmp_path)
    w.spawn_error = RuntimeError(PRIVATE)
    runner = w.runner()
    refused(lambda: runner(ARGV, timeout=1, max_output=4096))
    w.spawn_error = None
    refused(lambda: runner(ARGV, timeout=1, max_output=4096))
    assert len(w.calls) == 1


def test_read_timeout_ends_only_own_cli_and_never_retries(tmp_path, monkeypatch):
    w = World(tmp_path)
    monkeypatch.setattr(transport.select, "select", lambda *_a: ([], [], []))
    runner = w.runner()
    refused(lambda: runner(ARGV, timeout=1, max_output=4096))
    refused(lambda: runner(ARGV, timeout=1, max_output=4096))
    child = w.children[0]
    assert child.kills == 1 and child.waits == [1.0]
    assert len(w.calls) == 1


@pytest.mark.parametrize("clock_fault", [99.0, 110.0, float("nan")])
def test_clock_fault_after_spawn_refuses_and_cleans_own_child(tmp_path, clock_fault):
    w = World(tmp_path)
    w.hook = lambda _child: setattr(w, "now", clock_fault)
    refused(lambda: w.runner()(ARGV, timeout=1, max_output=4096))
    assert w.children[0].kills == 1 and w.children[0].waits == [1.0]


def test_private_wait_error_closes_streams_and_cleans_up(tmp_path):
    w = World(tmp_path)
    w.hook = lambda child: setattr(child, "wait_error", TimeoutError(PRIVATE))
    refused(lambda: w.runner()(ARGV, timeout=1, max_output=4096))
    child = w.children[0]
    assert child.kills == 1 and child.waits == [1.0, 1.0]
    assert child.stdout.file.closed and child.stderr.file.closed


@pytest.mark.parametrize(
    "stage", ["spawn", "read", "wait", "stdout-close", "stderr-close", "cleanup"]
)
def test_cancellation_is_preserved_cleanup_is_attempted_and_runner_latched(
    tmp_path, monkeypatch, stage
):
    w = World(tmp_path)
    cancellation = KeyboardInterrupt("fixture-cancel")
    if stage == "spawn":
        w.spawn_error = cancellation
    elif stage == "read":

        def interrupt(*_args):
            raise cancellation

        monkeypatch.setattr(transport.select, "select", interrupt)
    elif stage == "wait":
        w.hook = lambda child: setattr(child, "wait_error", cancellation)
    elif stage.endswith("close"):
        name = stage.split("-")[0]
        w.hook = lambda child: setattr(
            getattr(child, name), "close_error", cancellation
        )
    else:

        def setup(child):
            child.poll_error = cancellation
            w.now = 110.0

        w.hook = setup
    runner = w.runner()
    with pytest.raises(KeyboardInterrupt) as caught:
        runner(ARGV, timeout=1, max_output=4096)
    assert caught.value is cancellation
    refused(lambda: runner(ARGV, timeout=1, max_output=4096))
    assert len(w.calls) == 1
    for child in w.children:
        assert child.stdout.file.closed and child.stderr.file.closed
        assert child.waits


def test_close_failure_does_not_skip_other_stream_and_latches(tmp_path):
    w = World(tmp_path)
    w.hook = lambda child: setattr(child.stdout, "close_error", RuntimeError(PRIVATE))
    runner = w.runner()
    refused(lambda: runner(ARGV, timeout=1, max_output=4096))
    child = w.children[0]
    assert child.stdout.file.closed and child.stderr.file.closed
    refused(lambda: runner(ARGV, timeout=1, max_output=4096))
    assert len(w.calls) == 1


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("late", [101.1, 110.0])
def test_late_stream_close_refuses_stale_success_and_seals_runner(
    tmp_path, stream, late
):
    w = World(tmp_path)

    def setup(child):
        getattr(child, stream).close_hook = lambda: setattr(w, "now", late)

    w.hook = setup
    runner = w.runner()
    refused(lambda: runner(ARGV, timeout=1, max_output=4096))
    assert w.children[0].stdout.file.closed and w.children[0].stderr.file.closed
    assert w.children[0].kills == 0  # The CLI was already waited, never a worker.
    refused(lambda: runner(ARGV, timeout=1, max_output=4096))
    assert len(w.calls) == 1


def test_cleanup_error_marks_pending_cli_and_never_spawns_again(tmp_path, monkeypatch):
    w = World(tmp_path)
    w.hook = lambda child: setattr(child, "kill_error", RuntimeError(PRIVATE))
    monkeypatch.setattr(transport.select, "select", lambda *_a: ([], [], []))
    runner = w.runner()
    refused(lambda: runner(ARGV, timeout=1, max_output=4096))
    assert runner.unreaped == 1 and w.children[0].waits == [1.0]
    refused(lambda: runner(ARGV, timeout=1, max_output=4096))
    assert len(w.calls) == 1


def test_source_argv_is_copied_before_child_receives_it(tmp_path):
    w = World(tmp_path)
    units = [UNIT]
    runner = transport.SystemctlReadRunner(
        units,
        deadline=110,
        enabled=True,
        synthetic_only=True,
        popen=w.spawn,
        clock=lambda: w.now,
    )
    units[0] = "other.timer"
    assert runner(ARGV, timeout=1, max_output=4096) == (0, OUTPUT)
    assert runner.units == (UNIT,)


def test_constructor_uses_no_clock_or_process_io(tmp_path):
    w = World(tmp_path)

    def denied_clock():
        pytest.fail("clock called at construction")

    runner = transport.SystemctlReadRunner(
        (UNIT,), deadline=110, clock=denied_clock, popen=w.spawn
    )
    assert not w.calls and runner.units == (UNIT,)


def test_grammar_matches_existing_probe(tmp_path):
    # Importing the existing verifier makes no observations or native calls.
    from first_transition_c2_cron import CronPathPolicy
    from first_transition_c2_guards import NativeScheduleProbe

    w = World(tmp_path)
    policy = CronPathPolicy(("/etc/cron.d/synthetic_disabled",), str(tmp_path), True)
    probe = NativeScheduleProbe(
        units=(UNIT,), cron_files=policy.paths, run=w.spawn, cron_policy=policy
    )
    assert probe.argv(UNIT) == ARGV


def test_unknown_select_fd_refuses_and_does_not_read_it(tmp_path, monkeypatch):
    w = World(tmp_path)
    monkeypatch.setattr(transport.select, "select", lambda *_a: ([999999], [], []))
    refused(lambda: w.runner()(ARGV, timeout=1, max_output=4096))
    assert w.children[0].kills == 1


def test_private_read_error_is_sanitized(tmp_path, monkeypatch):
    w = World(tmp_path)

    def failed_read(*_args):
        raise OSError(PRIVATE)

    monkeypatch.setattr(os, "read", failed_read)
    refused(lambda: w.runner()(ARGV, timeout=1, max_output=4096))
    assert w.children[0].kills == 1
