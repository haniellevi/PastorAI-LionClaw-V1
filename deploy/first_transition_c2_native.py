"""Opt-in private Docker CLI snapshots for containment, never create provenance.

Config.Image is normalized to the immutable inspect.Image ID. Every other Config
and HostConfig value is preserved in private RAM. NetworkingConfig comes ONLY
from admitted private intent, never reconstructed from runtime endpoint metadata.
The raw Config.Image reference is retained privately in the producer, in memory
only. This normalized view is NOT faithful Docker Create or durable custody.
No IO on import/construction, CLI, host dispatch, config read permission or human
approval is provided here. Operational use requires separately admitted scope.
"""

from copy import deepcopy
from dataclasses import dataclass, field
import json
import math
import re
import time

from first_transition_adapter import digest
from first_transition_c2_adapter import Observation, checked_config, encoded, profile
from first_transition_c2_containment import Snapshot
from first_transition_host_driver import (
    INFO_ARGV,
    NETWORK_TEMPLATE,
    PopenRunner,
    STARTED,
)
from initial_transition_ops import Refused

CODE = "c2-native-read-refused"
CAP = 1024 * 1024
INSPECT_TEMPLATE = (
    "[{{json .Id}},{{json .Name}},{{json .Image}},{{json .Config}},"
    '{{json .HostConfig}},{"Status":{{json .State.Status}},'
    '"Running":{{json .State.Running}},"Paused":{{json .State.Paused}},'
    '"Restarting":{{json .State.Restarting}},"Dead":{{json .State.Dead}},'
    '"OOMKilled":{{json .State.OOMKilled}},"ExitCode":{{json .State.ExitCode}},'
    '"StartedAt":{{json .State.StartedAt}},"Pid":{{json .State.Pid}}},'
    "{{json .RestartCount}},"
    "{{json .NetworkSettings.Networks}},{{json .Path}},{{json .Args}}]"
)


def need(ok):
    if not ok:
        raise Refused(CODE)


def _json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            need(key not in result)
            result[key] = value
        return result

    def constant(_value):
        raise Refused(CODE)

    need(type(raw) is bytes and 0 < len(raw) <= CAP)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


@dataclass(frozen=True, repr=False)
class NativeAdmission:
    scope: str
    target_id: str
    image_id: str
    name: str
    network_intent: dict = field(repr=False)


def _admitted_private(manifest, admission):
    manifest = manifest.validated()
    need(
        type(admission) is NativeAdmission
        and admission.scope == manifest.digest
        and admission.target_id == dict(manifest.service_ids)["broadcast-worker"]
        and type(admission.image_id) is str
        and re.fullmatch("sha256:[0-9a-f]{64}", admission.image_id)
        and type(admission.name) is str
        and re.fullmatch("/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", admission.name)
    )
    intent = deepcopy(admission.network_intent)
    need(type(intent) is dict and set(intent) == {"EndpointsConfig"})
    endpoints = intent["EndpointsConfig"]
    need(type(endpoints) is dict and len(endpoints) == 1)
    name, endpoint = next(iter(endpoints.items()))
    need(
        type(name) is str
        and re.fullmatch("[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name)
        and type(endpoint) is dict
        and endpoint.get("NetworkID") == manifest.network_id
    )
    raw = encoded(intent)
    need(len(raw) <= CAP)
    return (
        manifest,
        NativeAdmission(
            admission.scope,
            admission.target_id,
            admission.image_id,
            admission.name,
            intent,
        ),
        raw,
        name,
    )


def _admitted(manifest, admission):
    good, result = False, None
    try:
        result = _admitted_private(manifest, admission)
        good = True
    except Exception:
        pass
    if not good:
        raise Refused(CODE)
    return result


class NativeReadRunner(PopenRunner):
    """Existing bounded runner with an exact, read-only target/network whitelist.

    Full config is private stdout, never a public error/receipt. Native access is
    closed by default, including info. Explicit enablement is an accident guard,
    not permission to read protected production configuration.
    """

    def __init__(self, *, manifest, admission, enabled=False, **kwargs):
        manifest, fixed, _raw, network_name = _admitted(manifest, admission)
        need("resume" not in kwargs)
        self.enabled = enabled
        self._commands = (
            INFO_ARGV,
            (
                "docker",
                "inspect",
                "--type",
                "container",
                "--format",
                INSPECT_TEMPLATE,
                fixed.target_id,
            ),
            (
                "docker",
                "network",
                "inspect",
                "--format",
                NETWORK_TEMPLATE,
                manifest.network_id,
            ),
            (
                "docker",
                "network",
                "inspect",
                "--format",
                NETWORK_TEMPLATE,
                network_name,
            ),
        )
        super().__init__(resume=False, **kwargs)

    def _allowed(self, argv):
        return tuple(argv) in self._commands

    def __call__(self, argv, *, timeout, max_output):
        good, result = False, None
        try:
            need(self.enabled is True)
            result = super().__call__(argv, timeout=timeout, max_output=max_output)
            good = True
        except Exception:
            pass
        if not good:
            raise Refused(CODE)
        return result


class NativeSnapshotProducer:
    """Bounded native read orchestration, with injectable runner for synthetic tests.

    Frozen private intent is admitted independently; endpoint IP/MAC/aliases from
    inspect are never turned into creation intent. Returned config is a private
    normalized containment view. No faithful-create, custody, recovery, quiescence
    or fresh approval is inferred from this snapshot. Production dispatch remains
    closed elsewhere. The producer is single-deadline, not a retry mechanism.
    """

    def __init__(
        self,
        manifest,
        admission,
        *,
        runner,
        deadline,
        enabled=False,
        clock=time.monotonic,
        max_calls=512,
    ):
        fixed_manifest, fixed, raw, name = _admitted(manifest, admission)
        self._manifest = fixed_manifest
        self._manifest_digest = fixed_manifest.digest
        self._scope = fixed.scope
        self._target = fixed.target_id
        self._image = fixed.image_id
        self._name = fixed.name
        self._intent = raw
        self._network_name = name
        self._network_id = fixed_manifest.network_id
        self._daemon_id = fixed_manifest.daemon_id
        self._runner, self._clock = runner, clock
        self._deadline, self._enabled = deadline, enabled
        self._max_calls = max_calls
        self._calls = 0
        self._last = None
        self._began = None
        self._failed = False
        self._original_image_reference = (
            None  # Private RAM only; no durable create/custody claim.
        )

    def __repr__(self):
        return "<NativeSnapshotProducer private, no production admission>"

    def _check(self):
        need(
            self._failed is False
            and self._enabled is True
            and callable(self._runner)
            and callable(self._clock)
            and type(self._max_calls) is int
            and 1 <= self._max_calls <= 1024
            and self._manifest.validated().digest
            == self._manifest_digest
            == self._scope
        )
        now = self._clock()
        need(
            type(now) in (int, float)
            and math.isfinite(now)
            and type(self._deadline) in (int, float)
            and math.isfinite(self._deadline)
            and (self._last is None or now >= self._last)
            and now < self._deadline
        )
        if self._began is None:
            self._began = now
        need(self._deadline <= self._began + 60)
        self._last = now
        intent = _json(self._intent)
        need(
            set(intent) == {"EndpointsConfig"}
            and len(intent["EndpointsConfig"]) == 1
            and intent["EndpointsConfig"][self._network_name]["NetworkID"]
            == self._network_id
        )
        return now

    def _read(self, argv, cap):
        now = self._check()
        need(self._calls < self._max_calls)
        self._calls += 1
        rc, raw = self._runner(
            argv, timeout=min(10, self._deadline - now), max_output=cap
        )
        self._check()
        need(type(rc) is int and rc == 0 and type(raw) is bytes and 0 < len(raw) <= cap)
        return _json(raw)

    def _daemon(self):
        need(self._read(INFO_ARGV, 256) == self._daemon_id)

    def _network(self, selector):
        row = self._read(
            ("docker", "network", "inspect", "--format", NETWORK_TEMPLATE, selector),
            1024,
        )
        need(type(row) is list and row == [self._network_id, self._network_name])

    def _snapshot(self, value):
        need(type(value) is list and len(value) == 10)
        identity, name, image, config, host, state, restarts, networks, path, args = (
            value
        )
        need(
            identity == self._target
            and name == self._name
            and image == self._image
            and type(config) is dict
            and type(host) is dict
            and type(state) is dict
            and type(restarts) is int
            and restarts >= 0
            and type(networks) is dict
        )
        need(type(config.get("Image")) is str and bool(config["Image"]))
        labels = config.get("Labels")
        need(labels is None or type(labels) is dict)
        labels = labels or {}
        need(
            type(labels) is dict
            and not labels.get("com.docker.compose.project")
            and not labels.get("com.docker.compose.service")
        )
        command = []
        for field in ("Entrypoint", "Cmd"):
            parts = config.get(field)
            need(
                parts is None
                or type(parts) is list
                and all(type(v) is str for v in parts)
            )
            command.extend(parts or [])
        need(
            path
            in (
                "python",
                "python3",
                "python3.13",
                "/usr/local/bin/python",
                "/usr/local/bin/python3",
                "/usr/local/bin/python3.13",
                "/usr/bin/python3",
                "/usr/bin/python3.13",
            )
            and args == ["-m", "app.workers.broadcast_worker"]
            and command == [path, *args]
            and host.get("Init") is False
        )
        required = {
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
        need(
            required <= set(state)
            and type(state["Running"]) is bool
            and all(
                state[k] is False for k in ("Paused", "Restarting", "Dead", "OOMKilled")
            )
            and type(state["ExitCode"]) is int
            and 0 <= state["ExitCode"] <= 255
            and type(state["StartedAt"]) is str
            and STARTED.fullmatch(state["StartedAt"])
            and state["Status"] == ("running" if state["Running"] else "exited")
            and type(state["Pid"]) is int
            and (state["Pid"] > 0 if state["Running"] else state["Pid"] == 0)
        )
        policy = host.get("RestartPolicy")
        need(
            type(policy) is dict
            and set(policy) == {"Name", "MaximumRetryCount"}
            and policy["Name"] in ("always", "unless-stopped", "on-failure", "no")
            and type(policy["MaximumRetryCount"]) is int
            and policy["MaximumRetryCount"] >= 0
        )
        need(not networks or set(networks) == {self._network_name})
        if networks:
            endpoint = networks[self._network_name]
            need(
                type(endpoint) is dict and endpoint.get("NetworkID") == self._network_id
            )
        if state["Running"]:
            need(set(networks) == {self._network_name})
        if self._original_image_reference is None:
            self._original_image_reference = config["Image"]
        need(config["Image"] == self._original_image_reference)
        normalized = deepcopy(config)
        normalized["Image"] = (
            image  # Explicit containment normalization, not raw create provenance.
        )
        private = checked_config(
            {
                "Config": normalized,
                "HostConfig": deepcopy(host),
                "NetworkingConfig": _json(self._intent),
            }
        )
        row = Observation(
            identity,
            self._daemon_id,
            image,
            "broadcast-worker",
            state["Running"],
            state["Status"],
            state["ExitCode"],
            policy["Name"],
            private,
            digest(_json(self._intent)),
            bool(state["Running"]),
        )
        profile(row)
        return Snapshot(row, name, state["StartedAt"], restarts)

    def __call__(self, target_id):
        good, result = False, None
        try:
            self._check()
            need(target_id == self._target)
            self._daemon()
            self._network(self._network_id)
            self._network(self._network_name)
            raw = self._read(
                (
                    "docker",
                    "inspect",
                    "--type",
                    "container",
                    "--format",
                    INSPECT_TEMPLATE,
                    self._target,
                ),
                CAP,
            )
            result = self._snapshot(raw)
            self._network(self._network_name)
            self._network(self._network_id)
            self._daemon()
            self._check()
            good = True
        except Exception:
            self._failed = True
        except BaseException:
            self._failed = True
            raise
        if not good:
            raise Refused(CODE)
        return result
