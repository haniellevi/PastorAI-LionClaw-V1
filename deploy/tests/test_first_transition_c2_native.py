"""Native read grammar and snapshots from fictional CLI replies; no Docker IO."""

from copy import deepcopy
from dataclasses import replace
import json
import re
from pathlib import Path
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_c2_native as native
from first_transition_adapter import ROLES
from first_transition_host_driver import HostManifest, MANDATORY_GATES, SCHEMA
from first_transition_host_transport import SUPPORT_ROLES
from initial_transition_ops import Refused

PRIVATE = "NATIVE-PRIVATE-SYNTHETIC-SENTINEL"


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def deny(*a, **kw):
        pytest.fail("native process/socket attempted")

    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(socket, "socket", deny)


class World:
    def __init__(self):
        self.now = 100.0
        self.calls = []
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
        self.image = "sha256:" + "f" * 64
        self.intent = {
            "EndpointsConfig": {
                "synthetic-net": {
                    "NetworkID": self.manifest.network_id,
                    "Aliases": ["declared-alias"],
                }
            }
        }
        self.admission = native.NativeAdmission(
            self.manifest.digest,
            self.target,
            self.image,
            "/synthetic-broadcast",
            self.intent,
        )
        self.row = [
            self.target,
            self.admission.name,
            self.image,
            {
                "Image": "synthetic:mutable-tag",
                "Env": ["SECRET=" + PRIVATE],
                "Entrypoint": None,
                "Cmd": ["python", "-m", "app.workers.broadcast_worker"],
                "Labels": {"private": PRIVATE},
                "Other": {"keep": PRIVATE},
            },
            {
                "RestartPolicy": {"Name": "always", "MaximumRetryCount": 0},
                "Init": False,
                "Binds": ["synthetic:" + PRIVATE],
            },
            {
                "Status": "running",
                "Running": True,
                "Paused": False,
                "Restarting": False,
                "Dead": False,
                "OOMKilled": False,
                "ExitCode": 0,
                "StartedAt": "2026-11-06T00:00:00Z",
                "Pid": 123,
            },
            0,
            {
                "synthetic-net": {
                    "NetworkID": self.manifest.network_id,
                    "IPAddress": "192.0.2.25",
                    "Aliases": ["runtime-alias"],
                }
            },
            "python",
            ["-m", "app.workers.broadcast_worker"],
        ]

    def run(self, argv, **kw):
        self.calls.append((argv, kw))
        if self.fault == "timeout":
            raise TimeoutError(PRIVATE)
        if self.fault == "late":
            self.now = 131.0
        if argv == native.INFO_ARGV:
            r = self.manifest.daemon_id
        elif argv[1:3] == ("network", "inspect"):
            r = [self.manifest.network_id, "synthetic-net"]
        else:
            r = deepcopy(self.row)
        return 0, (json.dumps(r) + "\n").encode()

    def producer(self, **kw):
        return native.NativeSnapshotProducer(
            self.manifest,
            self.admission,
            runner=self.run,
            deadline=130,
            enabled=True,
            clock=lambda: self.now,
            **kw,
        )


def test_native_snapshot_preserves_config_and_only_normalizes_image_intent():
    w = World()
    p = w.producer()
    s = p(w.target)
    o = s.observation
    assert len(w.calls) == 7 and all(c[1]["timeout"] <= 10 for c in w.calls)
    expected = deepcopy(w.row[3])
    expected["Image"] = w.image
    assert (
        o.private_config["Config"] == expected
        and o.private_config["HostConfig"] == w.row[4]
    )
    assert o.private_config["NetworkingConfig"] == w.intent
    assert "runtime-alias" not in json.dumps(o.private_config["NetworkingConfig"])
    assert o.effective_network_verified and s.name == w.admission.name
    assert (
        PRIVATE not in repr(s)
        and PRIVATE not in repr(p)
        and PRIVATE not in repr(w.admission)
    )


def test_default_closed_on_producer_and_native_runner_without_io():
    w = World()
    p = native.NativeSnapshotProducer(
        w.manifest, w.admission, runner=w.run, deadline=130
    )
    with pytest.raises(Refused):
        p(w.target)
    assert w.calls == []
    r = native.NativeReadRunner(
        manifest=w.manifest,
        admission=w.admission,
        docker_binary="/synthetic/docker",
        endpoint="unix:///synthetic/docker.sock",
        config_dir="/synthetic/config",
    )
    with pytest.raises(Refused):
        r(native.INFO_ARGV, timeout=1, max_output=256)


@pytest.mark.parametrize(
    "index,value",
    [
        (0, "a" * 64),
        (1, "/foreign"),
        (2, "sha256:" + "a" * 64),
        (3, None),
        (4, None),
        (5, None),
        (6, True),
        (7, None),
        (8, "sh"),
        (9, ["-c", "PRIVATE"]),
    ],
)
def test_wrong_ids_missing_sections_or_ambiguous_entry_are_refused(index, value):
    w = World()
    w.row[index] = value
    with pytest.raises(Refused) as e:
        w.producer()(w.target)
    assert str(e.value) == native.CODE and e.value.__context__ is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("Status", "paused"),
        ("Running", 1),
        ("ExitCode", False),
        ("StartedAt", "unknown"),
        ("Pid", 0),
        ("Paused", True),
        ("Restarting", True),
        ("Dead", True),
        ("OOMKilled", True),
    ],
)
def test_state_must_be_typed_consistent_and_complete(field, value):
    w = World()
    w.row[5][field] = value
    with pytest.raises(Refused):
        w.producer()(w.target)


def test_missing_state_field_is_not_defaulted():
    w = World()
    del w.row[5]["StartedAt"]
    with pytest.raises(Refused):
        w.producer()(w.target)


@pytest.mark.parametrize(
    "networks",
    [
        {},
        {"foreign": {"NetworkID": "e" * 64}},
        {"synthetic-net": {"NetworkID": "a" * 64}},
        {"synthetic-net": {"NetworkID": "e" * 64}, "extra": {"NetworkID": "a" * 64}},
    ],
)
def test_running_requires_exact_single_effective_declared_network(networks):
    w = World()
    w.row[7] = networks
    with pytest.raises(Refused):
        w.producer()(w.target)


def test_exited_snapshot_does_not_invent_effective_network():
    w = World()
    w.row[5].update(Status="exited", Running=False, ExitCode=0, Pid=0)
    w.row[7] = {}
    s = w.producer()(w.target)
    assert (
        not s.observation.effective_network_verified
        and s.observation.private_config["NetworkingConfig"] == w.intent
    )


@pytest.mark.parametrize("init", [None, True, "false"])
def test_unknown_or_injected_init_refused(init):
    w = World()
    w.row[4]["Init"] = init
    with pytest.raises(Refused):
        w.producer()(w.target)


def test_command_token_hidden_in_shell_is_not_worker_identity():
    w = World()
    w.row[3].update(
        Entrypoint=["sh", "-c"], Cmd=["python", "-m", "app.workers.broadcast_worker"]
    )
    with pytest.raises(Refused):
        w.producer()(w.target)


def test_private_admission_aliases_cannot_mutate_frozen_intent():
    w = World()
    p = w.producer()
    w.intent["EndpointsConfig"]["synthetic-net"]["Aliases"].append("foreign")
    assert p(w.target).observation.private_config["NetworkingConfig"][
        "EndpointsConfig"
    ]["synthetic-net"]["Aliases"] == ["declared-alias"]
    s = p(w.target)
    s.observation.private_config["NetworkingConfig"]["EndpointsConfig"][
        "synthetic-net"
    ]["Aliases"].append("returned-mutation")
    assert p(w.target).observation.private_config["NetworkingConfig"][
        "EndpointsConfig"
    ]["synthetic-net"]["Aliases"] == ["declared-alias"]


@pytest.mark.parametrize("fault", ["timeout", "late"])
def test_private_transport_errors_and_late_returns_latch_failure(fault):
    w = World()
    w.fault = fault
    p = w.producer()
    with pytest.raises(Refused) as e:
        p(w.target)
    assert (
        str(e.value) == native.CODE
        and e.value.__context__ is None
        and PRIVATE not in str(e.value)
    )
    count = len(w.calls)
    w.fault = None
    w.now = 100
    with pytest.raises(Refused):
        p(w.target)
    assert len(w.calls) == count


def test_count_budget_is_global_not_reset_between_snapshots():
    w = World()
    p = w.producer(max_calls=7)
    p(w.target)
    with pytest.raises(Refused):
        p(w.target)
    assert len(w.calls) == 7


def test_global_deadline_cannot_exceed_sixty_seconds():
    w = World()
    p = native.NativeSnapshotProducer(
        w.manifest,
        w.admission,
        runner=w.run,
        deadline=161,
        enabled=True,
        clock=lambda: 100.0,
    )
    with pytest.raises(Refused):
        p(w.target)
    assert w.calls == []


def test_oversized_inspect_cannot_escape_to_error():
    w = World()
    real = w.run

    def run(argv, **kw):
        if argv[1] == "inspect":
            return 0, b"x" * (native.CAP + 1)
        return real(argv, **kw)

    p = native.NativeSnapshotProducer(
        w.manifest,
        w.admission,
        runner=run,
        deadline=130,
        enabled=True,
        clock=lambda: 100.0,
    )
    with pytest.raises(Refused) as e:
        p(w.target)
    assert e.value.__context__ is None


def test_duplicate_json_keys_and_nonfinite_payload_are_refused():
    for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
        with pytest.raises(Refused):
            native._json(raw)


def test_network_name_rebinding_is_checked_after_inspect():
    w = World()
    real = w.run

    def run(argv, **kw):
        if len(w.calls) >= 4 and argv[1] == "network":
            return 0, json.dumps(["a" * 64, "synthetic-net"]).encode()
        return real(argv, **kw)

    p = native.NativeSnapshotProducer(
        w.manifest,
        w.admission,
        runner=run,
        deadline=130,
        enabled=True,
        clock=lambda: 100.0,
    )
    with pytest.raises(Refused):
        p(w.target)


def test_native_runner_exact_read_whitelist_never_mutates_or_reads_foreign_target():
    w = World()
    r = native.NativeReadRunner(
        manifest=w.manifest,
        admission=w.admission,
        enabled=True,
        docker_binary="/synthetic/docker",
        endpoint="unix:///synthetic/docker.sock",
        config_dir="/synthetic/config",
    )
    assert r._allowed(native.INFO_ARGV)
    assert r._allowed(
        (
            "docker",
            "inspect",
            "--type",
            "container",
            "--format",
            native.INSPECT_TEMPLATE,
            w.target,
        )
    )
    for argv in [
        ("docker", "update", "--restart=no", w.target),
        ("docker", "kill", "--signal=TERM", w.target),
        ("docker", "start", w.target),
        (
            "docker",
            "inspect",
            "--type",
            "container",
            "--format",
            native.INSPECT_TEMPLATE,
            "a" * 64,
        ),
        ("docker", "network", "inspect", "foreign"),
    ]:
        assert not r._allowed(argv)
        with pytest.raises(Refused) as e:
            r(argv, timeout=1, max_output=256)
        assert str(e.value) == native.CODE and e.value.__context__ is None


def test_wrong_requested_target_refuses_before_native_read():
    w = World()
    with pytest.raises(Refused):
        w.producer()("a" * 64)
    assert w.calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", "foreign"),
        ("target_id", "a" * 64),
        ("image_id", "mutable:tag"),
        ("name", "../foreign"),
        ("network_intent", {"EndpointsConfig": {}}),
    ],
)
def test_bad_admission_is_refused_before_construction_io(field, value):
    w = World()
    w.admission = replace(w.admission, **{field: value})
    with pytest.raises(Refused) as e:
        w.producer()
    assert str(e.value) == native.CODE and e.value.__context__ is None and w.calls == []


def test_cancellation_seals_producer_without_sanitizing_interrupt():
    w = World()

    def cancel(*a, **kw):
        raise KeyboardInterrupt()

    p = native.NativeSnapshotProducer(
        w.manifest,
        w.admission,
        runner=cancel,
        deadline=130,
        enabled=True,
        clock=lambda: 100.0,
    )
    with pytest.raises(KeyboardInterrupt):
        p(w.target)
    with pytest.raises(Refused):
        p(w.target)


@pytest.mark.parametrize("clock", [float("nan"), float("inf"), True, 99.0])
def test_clock_invalidity_or_regression_is_not_ignored(clock):
    w = World()
    p = w.producer()
    p(w.target)
    w.now = clock
    with pytest.raises(Refused):
        p(w.target)
    assert len(w.calls) == 7


def test_raw_image_reference_is_retained_privately_and_drift_refuses():
    w = World()
    p = w.producer()
    p(w.target)
    assert p._original_image_reference == "synthetic:mutable-tag"
    assert "synthetic:mutable-tag" not in repr(p)
    w.row[3]["Image"] = "synthetic:foreign-reference"
    with pytest.raises(Refused):
        p(w.target)


def test_cli_projection_excludes_health_log_output_from_private_metadata():
    w = World()
    state = deepcopy(w.row[5])
    health_secret = "HEALTH-OUTPUT-MUST-NOT-BE-READ"
    state["Health"] = {"Status": "unhealthy", "Log": [{"Output": health_secret}]}
    source = dict(
        zip(
            ("Id", "Name", "Image", "Config", "HostConfig", "State", "RestartCount"),
            w.row[:7],
        )
    )
    source["State"] = state
    source.update(NetworkSettings={"Networks": w.row[7]}, Path=w.row[8], Args=w.row[9])

    def json_field(match):
        value = source
        for component in match.group(1).split("."):
            value = value[component]
        return json.dumps(value)

    # Emulate only JSON field substitutions on a fictional Docker struct. This
    # checks the exposure contract without invoking Docker or a real template API.
    rendered = re.sub(
        r"\{\{json \.([A-Za-z.]+)\}\}", json_field, native.INSPECT_TEMPLATE
    )
    result = json.loads(rendered)
    assert len(result) == 10
    assert set(result[5]) == {
        "Status",
        "Running",
        "Paused",
        "Restarting",
        "Dead",
        "OOMKilled",
        "ExitCode",
        "StartedAt",
        "Pid",
    }
    assert health_secret not in rendered
    assert "Health" not in result[5] and "Log" not in result[5]
    assert result[3] == w.row[3] and result[4] == w.row[4]
    assert "{{json .State}}" not in native.INSPECT_TEMPLATE
