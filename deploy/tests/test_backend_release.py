"""Local command doubles verify deploy stops and code-only rollback order."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


DEPLOY = Path(__file__).resolve().parents[1]
SHA_OLD = "a" * 40
SHA_NEW = "b" * 40
SERVICES = "backend queue-worker cron-worker broadcast-worker"
SCHEMA = runpy.run_path(str(DEPLOY / "check_backend_schema.py"))
TOPOLOGY = runpy.run_path(str(DEPLOY / "release_topology.py"))
PROJECT = "pastorai-permanent"
NETWORK = "pastorai_default"

# Synthetic Docker state behind the adopted topology: four contained legacy
# containers, Redis/Evolution of the legacy project on the shared network and
# the permanent project, whose services follow the fake's create/stop/start.
WORLD = r"""
import json, os, sys
from pathlib import Path

SERVICES = ("backend", "queue-worker", "cron-worker", "broadcast-worker")
contract = json.loads(Path(os.environ["WORLD_CONTRACT"]).read_text())
P, N = contract["project"], contract["network"]["name"]
state_path = Path(os.environ["TRACE"] + ".world.json")
env = lambda key: os.environ.get("WORLD_" + key, "")


def load():
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {s: {"state": "exited" if env("PREDECESSOR_STOPPED") == s else "running", "image": 1,
                "created": False} for s in SERVICES}


def rows(st):
    found = []
    def add(cid, name, running, project, service, networks, policy="always", health=None, image=9):
        found.append([cid, "/" + name, running, policy, project, service, "False" if project else "",
                      health, "sha256:%064d" % image, networks])
    for role, cid in contract["reserved_legacy"].items():
        if env("LEGACY_MISSING") != role:
            project = P if env("LEGACY_IN_PROJECT") == role else ("pastorai" if role != "broadcast-worker" else "")
            add(cid, "legacy-" + role, env("LEGACY_RUNNING") == role, project, role if project else "",
                {N: {"Aliases": ["legacy-" + role, role]}}, policy="always" if env("LEGACY_POLICY") == role else "no")
    for index, alias in enumerate(("redis", "evolution-api")):
        if env("DEP_MISSING") == alias or (env("DEP_DOWN_ON_START") == alias and st.get("_started_new")):
            continue
        for copy in range(2 if env("DEP_DUPLICATE") == alias else 1):
            health = "unhealthy" if env("DEP_UNHEALTHY") == alias else ("healthy" if alias == "redis" else None)
            add("%064x" % (0xd0 + index * 4 + copy), "legacy-%s-%d" % (alias, copy), True, "pastorai", alias,
                {N: {"Aliases": [alias], "DNSNames": [alias, "legacy-" + alias]}}, health=health)
    if env("ALIAS_CONFLICT") and (not env("ALIAS_CONFLICT_ON_CREATE") or st.get("_created_new")) and (
            not env("ALIAS_CONFLICT_ON_BUILD") or st.get("_built_new")):
        add("%064x" % 0xbad, "rogue", True, "rogue", "rogue", {N: {"DNSNames": [env("ALIAS_CONFLICT")]}})
    for index, role in enumerate(SERVICES):
        item = st[role]
        name = "wrong-" + role if env("WRONG_NAME") == role else contract["containers"][role]
        networks = {N: {"Aliases": [name, role], "DNSNames": [name, role]}}
        if item["created"] and env("CREATED_EXTRA_NETWORK"):
            networks["second_network"] = {"Aliases": [role]}
        add("%064x" % (0xa0 + index), name, item["state"] == "running", P, role, networks, image=item["image"])
    if env("STRANGER_ON_START") and st.get("_started_new"):
        add("%064x" % 0xbb, "unexpected-backend-copy", True, P, "backend", {N: {}})
    if env("FOREIGN_SERVICE"):
        add("%064x" % 0xf0, "foreign", False, P, "redis", {N: {}})
    return found


st = load()
command = sys.argv[1]
if command == "event":
    kind, roles = sys.argv[2], sys.argv[3:]
    if kind == "built":
        st["_built_new"] = True
    if kind == "stopped-ids":
        by_id = {"%064x" % (0xa0 + index): role for index, role in enumerate(SERVICES)}
        assert roles[0] == "stop" and all(cid in by_id for cid in roles[1:]), "stop of a non-owned ID"
        kind, roles = "stopped", [by_id[cid] for cid in roles[1:]]
    for role in roles:
        if kind == "created":
            st[role] = {"state": "created", "image": 2 if os.environ["PWD"] == os.environ["NEW_DEPLOY"] else 1,
                        "created": True}
            if os.environ["PWD"] == os.environ["NEW_DEPLOY"]:
                st["_created_new"] = True
        else:
            st[role]["state"] = {"stopped": "exited", "started": "running", "checker-ran": "exited"}[kind]
            if kind == "started" and os.environ["PWD"] == os.environ["NEW_DEPLOY"]:
                st["_started_new"] = True
    state_path.write_text(json.dumps(st))
    sys.exit(0)
args = sys.argv[2:]
if args[:2] == ["network", "inspect"]:
    print(json.dumps([env("NETWORK_ID") or contract["network"]["id"], N]))
elif args[:2] == ["container", "ls"]:
    with open(os.environ["TRACE"] + ".topology", "a") as out:
        out.write("guard|%s|%s\n" % (os.environ["PWD"], ",".join(
            "%s=%s" % (s, st[s]["state"]) for s in SERVICES)))
    for row in rows(st):
        print(row[0])
elif args[:2] == ["container", "inspect"]:
    assert args[2] == "--format" and ".Config.Env" not in args[3], "inspect must not read Config.Env"
    by_id = {row[0]: row for row in rows(st)}
    for cid in args[4:]:
        if cid not in by_id:
            sys.exit(1)
        print(json.dumps(by_id[cid]))
else:
    sys.exit(2)
"""


class BackendReleaseTest(unittest.TestCase):
    stop_marker = "|compose stop "  # trace fragment of a consumer stop
    rollback_ps_failure = ({"ROLLBACK_PS_EXIT": "1"},)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="backend-release-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / "releases" / SHA_OLD / "deploy"
        self.new = self.root / "releases" / SHA_NEW / "deploy"
        self.old.mkdir(parents=True)
        self.new.mkdir(parents=True)
        (self.old / "configuration.fixture").write_text("SYNTHETIC=1\n")
        (self.new / "check_backend_schema.py").write_bytes(
            (DEPLOY / "check_backend_schema.py").read_bytes()
        )
        (self.old / "check_backend_schema.py").write_text("# SYNTHETIC OLD CHECKER\n")
        old_backend = self.old.parent / "backend"
        (old_backend / "scripts").mkdir(parents=True)
        (old_backend / "migrations").mkdir()
        (old_backend / "scripts/migrate.py").write_text("def migration_files(path): return ['0001_synthetic.sql']\n")
        (self.root / "current").symlink_to(self.old.parent)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "docker").write_text(
            """#!/bin/sh
if [ -n "${LOCK_TEST_FILE:-}" ] && flock -n "$LOCK_TEST_FILE" true; then
  echo 'release lock not held during Docker operation' >&2; exit 1
fi
overlay=0
state_file="$TRACE.$(basename "$(dirname "$PWD")").state"
world="$(dirname "$0")/docker-world.py"
topology_call=0
kinds=
if [ "$1" = compose ] && [ "$2" = -p ]; then
  if [ -z "${TOPOLOGY_PROJECT:-}" ] || [ "$3" != "$TOPOLOGY_PROJECT" ]; then
    printf 'bad-compose|%s|unexpected project\\n' "$PWD" >> "$TRACE"; exit 97
  fi
  topology_call=1
  shift 3
  set -- compose "$@"
elif [ "$1" = compose ] && [ -n "${TOPOLOGY_PROJECT:-}" ]; then
  printf 'bad-compose|%s|missing project\\n' "$PWD" >> "$TRACE"; exit 97
fi
while [ "$1" = compose ] && [ "$2" = -f ]; do
  file="$3"
  if [ "$file" = docker-compose.yml ]; then kinds="${kinds}${kinds:+,}base"
  elif [ "$(basename "$file")" = topology.yml ]; then
    grep -q "\\"name\\": \\"$TOPOLOGY_PROJECT\\"" "$file" || exit 96
    kinds="${kinds}${kinds:+,}topology"
  else
  if grep -q entrypoint "$file"; then kinds="${kinds}${kinds:+,}checker"; else kinds="${kinds}${kinds:+,}pin"; fi
  python3 - "$file" <<'OVERRIDE'
import json, os, sys
from pathlib import Path
services = json.loads(Path(sys.argv[1]).read_text())["services"]
service = services["backend"]
if "entrypoint" in service:
    assert service["entrypoint"] == ["python", "/tmp/backend-rollback-schema.py"]
    assert service["command"] == []
    assert service["restart"] == "no"
    assert service["healthcheck"] == {"disable": True}
    with open(os.environ["TRACE"], "a") as out:
        out.write("checker-override|" + sys.argv[1] + "\\n")
        out.write("checker-manifest|" + service["environment"]["EXPECTED_MIGRATIONS"] + "\\n")
else:
    assert set(services) == {"backend", "queue-worker", "cron-worker", "broadcast-worker"}
    assert len({v["image"] for v in services.values()}) == 1
    with open(os.environ["TRACE"], "a") as out:
        out.write("image-overlay|" + sys.argv[1] + "|" + service["image"] + "\\n")
OVERRIDE
  [ $? = 0 ] || exit 1
  if grep -q entrypoint "$file"; then overlay=1; fi
  fi
  shift 3
  set -- compose "$@"
done
if [ "$topology_call" = 1 ]; then
  case "$kinds" in
    base,topology|base,topology,checker|base,topology,pin|base,topology,checker,pin) ;;
    *) printf 'bad-compose|%s|file order %s\\n' "$PWD" "$kinds" >> "$TRACE"; exit 98 ;;
  esac
  printf 'compose|%s|%s|%s\\n' "$PWD" "$kinds" "$(printf '%s' "$*" | tr '\\n' ' ')" >> "$TRACE.topology"
fi
case "$*" in
  'compose config --format json --no-env-resolution')
    printf '%s\\n' "$TOPOLOGY_CONFIG_JSON"; exit 0 ;;
  'container '*|'network inspect '*) exec python3 "$world" read "$@" ;;
  'context inspect --format '*) printf '%s\\n' 'unix:///var/run/docker.sock'; exit 0 ;;
  'image inspect --format '* )
    case "$4" in
      '{{.Id}}')
        case "$5" in
          *-release:"${PREVIOUS_IMAGE_SHA:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}") printf 'sha256:%064d\\n' 1 ;;
          *) printf 'sha256:%064d\\n' 2 ;;
        esac ;;
      *) if [ "$5" = 'sha256:'"$(printf '%064d' 1)" ]; then
           printf '%s\\n' "${PREVIOUS_IMAGE_SHA:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}";
         else printf '%s\\n' "${CANDIDATE_IMAGE_SHA:-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}"; fi ;;
    esac
    exit 0 ;;
  'inspect --format {{.State.Running}} '* )
    [ "${CONSUMER_STILL_RUNNING:-0}" = 0 ] && printf 'false\\n' || printf 'true\\n'
    exit 0 ;;
  'inspect --format {{.Image}} '* )
    if [ "$PWD" = "$NEW_DEPLOY" ]; then
      printf 'sha256:%064d\\n' "${CREATED_IMAGE_ID:-2}";
    elif [ "$4" = queue-worker ] && [ "${INCONSISTENT_PREVIOUS_IMAGES:-0}" = 1 ]; then
      printf 'sha256:%064d\\n' 3;
    else printf 'sha256:%064d\\n' 1; fi
    exit 0 ;;
  'pull '*) printf 'pull|%s\\n' "$2" >> "$TRACE"; exit "${PULL_EXIT:-0}" ;;
  'compose version --short') printf '%s\\n' "${COMPOSE_VERSION:-5.0.0}"; exit "${VERSION_EXIT:-0}" ;;
  'compose start --help')
    printf 'capabilities|%s\\n' "$PWD" >> "$TRACE"
    [ "${HELP_EXIT:-0}" = 0 ] || exit 1
    [ "${NO_WAIT:-0}" = 1 ] || printf '%s\\n' '  --wait Wait for healthy'
    [ "${NO_TIMEOUT:-0}" = 1 ] || printf '%s\\n' '  --wait-timeout seconds'
    exit 0 ;;
  'cp '*)
    printf 'checker-copy|%s|' "$PWD" >> "$TRACE"
    sha256sum "$2" | cut -d' ' -f1 >> "$TRACE"
    exit "${COPY_EXIT:-0}" ;;
  'compose start backend')
    [ "$overlay" = 1 ] && [ "$(cat "$state_file")" = checker ] || exit 1
    printf 'checker-start|%s\\n' "$PWD" >> "$TRACE"
    [ -z "${TOPOLOGY_PROJECT:-}" ] || python3 "$world" event checker-ran backend
    exit "${CHECKER_START_EXIT:-0}" ;;
  'wait '*)
    printf 'checker-wait|%s\\n' "$PWD" >> "$TRACE"
    printf '%s\\n' "${ROLLBACK_PREFLIGHT_EXIT-0}"
    exit "${CHECKER_WAIT_EXIT:-0}" ;;
  'compose ps -aq '*)
    if [ "$PWD" != "$NEW_DEPLOY" ] && [ "${ROLLBACK_PS_EXIT:-0}" = 1 ]; then
      printf '%s\\n' "$4"; exit 1
    fi
    printf '%s\\n' "$4"; exit 0 ;;
  'inspect '*)
    printf 'inspect|%s|%s\\n' "$PWD" "$4" >> "$TRACE"
    if [ "${STOPPED_GATES_EXIT:-0}" = 1 ] ||
       { [ "$PWD" != "$NEW_DEPLOY" ] && [ "${ROLLBACK_STOPPED_GATES_EXIT:-0}" = 1 ]; }; then printf '[]';
    else printf '["ALLOW_REAL_SENDS=false","ASAAS_BILLING_ENABLED=false","BREVO_SEND_MODE=off","BROADCAST_ASYNC_ENABLED=false"]'; fi
    exit 0 ;;
  'compose config --format json')
    printf 'config-json|%s\\n' "$PWD" >> "$TRACE"
    if [ "$PWD" = "$NEW_DEPLOY" ]; then printf '%s\\n' "$CANDIDATE_CONFIG_JSON";
    elif [ -f "$TRACE.candidate_up" ]; then printf '%s\\n' "$ROLLBACK_CONFIG_JSON";
    else printf '%s\\n' "$ACTIVE_CONFIG_JSON"; fi
    exit 0 ;;
  'compose exec -T -e EXPECTED_MIGRATIONS='*' backend python -')
    checker_hash=$(sha256sum | cut -d' ' -f1)
    printf 'preflight-checker|%s|%s\\n' "$PWD" "$checker_hash" >> "$TRACE"
    printf 'docker|%s|%s\\n' "$PWD" "$*" >> "$TRACE"
    if [ "$5" = 'EXPECTED_MIGRATIONS=["0001_synthetic.sql"]' ]; then
      exit "${PREVIOUS_PREFLIGHT_EXIT:-0}"
    fi
    exit "${PREFLIGHT_EXIT:-0}" ;;
  *' sh -c '*)
    printf 'gates|%s|%s\\n' "$PWD" "$4" >> "$TRACE"
    if [ "$PWD" = "$NEW_DEPLOY" ] && [ "${CANDIDATE_GATES_EXIT:-0}" = 1 ]; then exit 1; fi
    sh -lc "$7"; exit $? ;;
esac
printf 'docker|%s|%s\\n' "$PWD" "$*" >> "$TRACE"
case "$*" in
  'compose build --build-arg PASTORAI_RELEASE_SHA='*' backend')
    if [ "$PWD" = "$NEW_DEPLOY" ]; then expected_revision="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    else expected_revision="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"; fi
    [ "$*" = "compose build --build-arg PASTORAI_RELEASE_SHA=$expected_revision backend" ] || exit 1
    if [ "$PWD" = "$NEW_DEPLOY" ]; then
      [ "${BUILD_EXIT:-0}" = 0 ] || exit "$BUILD_EXIT"
      [ -z "${TOPOLOGY_PROJECT:-}" ] || python3 "$world" event built
      exit 0
    fi
    exit "${ROLLBACK_BUILD_EXIT:-0}" ;;
  'compose run '*) exit "${ROLLBACK_PREFLIGHT_EXIT:-0}" ;;
  'compose up --no-start '*)
    if [ "$PWD" != "$NEW_DEPLOY" ] && [ "${ROLLBACK_CREATE_EXIT:-0}" != 0 ]; then
      exit "$ROLLBACK_CREATE_EXIT"
    fi
    if [ "$overlay" = 1 ]; then
      [ "$*" = 'compose up --no-start --no-build --no-deps --pull never --force-recreate backend' ] || exit 1
      printf 'checker' > "$state_file"
      printf 'created|%s|checker|backend\\n' "$PWD" >> "$TRACE"
      [ -z "${TOPOLOGY_PROJECT:-}" ] || python3 "$world" event created backend
    else
      [ "$*" = 'compose up --no-start --no-build --no-deps --pull never --force-recreate backend queue-worker cron-worker broadcast-worker' ] || exit 1
      printf 'normal' > "$state_file"
      printf 'created|%s|normal|backend queue-worker cron-worker broadcast-worker\\n' "$PWD" >> "$TRACE"
      [ -z "${TOPOLOGY_PROJECT:-}" ] || python3 "$world" event created backend queue-worker cron-worker broadcast-worker
    fi ;;

  'stop '*)
    if [ "$PWD" != "$NEW_DEPLOY" ] && [ "${ROLLBACK_STOP_EXIT:-0}" = 1 ]; then exit 1; fi
    [ "${STOP_EXIT:-0}" = 0 ] || exit "$STOP_EXIT"
    printf 'stop|%s|%s\\n' "$PWD" "$*" >> "$TRACE.topology"
    python3 "$world" event stopped-ids "$@"
    exit 0 ;;
  'compose stop '*)
    if [ "$PWD" != "$NEW_DEPLOY" ] && [ "${ROLLBACK_STOP_EXIT:-0}" = 1 ]; then exit 1; fi
    [ "${STOP_EXIT:-0}" = 0 ] || exit "$STOP_EXIT"
    [ -z "${TOPOLOGY_PROJECT:-}" ] || python3 "$world" event stopped backend queue-worker cron-worker broadcast-worker
    exit 0 ;;
  'compose start '*)
    if [ "$overlay" != 0 ] || [ "$(cat "$state_file")" != normal ]; then
      printf 'rejected-app-start|%s\\n' "$PWD" >> "$TRACE"
      exit 1
    fi
    [ -z "${TOPOLOGY_PROJECT:-}" ] || python3 "$world" event started backend queue-worker cron-worker broadcast-worker
    if [ "$PWD" = "$NEW_DEPLOY" ]; then
      touch "$TRACE.candidate_up"
      if [ -n "${SIGNAL_ON_START:-}" ]; then kill -"$SIGNAL_ON_START" "$PPID"; fi
      exit "${RESTART_EXIT:-0}"
    fi
    exit "${ROLLBACK_RESTART_EXIT:-0}" ;;
esac
exit 0
"""
        )
        (bin_dir / "docker-world.py").write_text(WORLD)
        (bin_dir / "curl").write_text(
            """#!/bin/sh
if [ -n "${LOCK_TEST_FILE:-}" ] && flock -n "$LOCK_TEST_FILE" true; then
  echo 'release lock not held during health check' >&2; exit 1
fi
printf 'curl|%s|%s\\n' "$PWD" "$*" >> "$TRACE"
if [ "$PWD" = "$NEW_DEPLOY" ]; then exit "${HEALTH_EXIT:-0}"; fi
exit "${ROLLBACK_HEALTH_EXIT:-0}"
"""
        )
        (bin_dir / "cp").write_text(
            """#!/bin/sh
printf 'copy-configuration|%s\\n' "$PWD" >> "$TRACE"
exec /bin/cp "$@"
"""
        )
        (bin_dir / "timeout").write_text(
            """#!/bin/sh
printf 'timeout|%s|%s\\n' "$PWD" "$*" >> "$TRACE"
[ "${TIMEOUT_OPTIONS_EXIT:-0}" = 0 ] || exit "$TIMEOUT_OPTIONS_EXIT"
[ "$1" = --signal=TERM ] && [ "$2" = --kill-after=5s ] || exit 2
case "$3 $4" in
  '1s true')
    [ ! -f "$NEW_DEPLOY/configuration.fixture" ] || exit 1
    printf 'timeout-probe|configuration-absent\\n' >> "$TRACE" ;;
  '180s docker') [ "${CHECKER_TIMEOUT_EXIT:-0}" = 0 ] || exit "$CHECKER_TIMEOUT_EXIT" ;;
  *) exit 2 ;;
esac
shift 3
exec "$@"
"""
        )
        for name in ("docker", "curl", "cp", "timeout"):
            (bin_dir / name).chmod(0o755)
        self.trace = self.root / "trace"
        closed = {
            "ALLOW_REAL_SENDS": "false",
            "ASAAS_BILLING_ENABLED": "false",
            "BREVO_SEND_MODE": "off",
            "BROADCAST_ASYNC_ENABLED": "false",
        }
        self.closed_config = {
            "services": {service: {"environment": closed} for service in SERVICES.split()}
        }
        closed_json = json.dumps(self.closed_config)
        self.environment = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "TRACE": str(self.trace),
            "NEW_DEPLOY": str(self.new),
            "BACKEND_RELEASE_TEST_MODE": "1",
            "BACKEND_RELEASE_TEST_ROOT": str(self.root),
            "BACKEND_RELEASE_TEST_CONFIG": "configuration.fixture",
            "ACTIVE_CONFIG_JSON": closed_json,
            "CANDIDATE_CONFIG_JSON": closed_json,
            "ROLLBACK_CONFIG_JSON": closed_json,
            "ALLOW_REAL_SENDS": "false",
            "ASAAS_BILLING_ENABLED": "false",
            "BREVO_SEND_MODE": "off",
            "BROADCAST_ASYNC_ENABLED": "false",
        }

        # Host release/Docker inputs are never implicit fixture authority.
        for key in ("RELEASE_IMAGE_REF", "RELEASE_SCHEMA_BUNDLE", "RELEASE_SCHEMA_BUNDLE_SHA256",
                    "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "LOCK_TEST_FILE"):
            self.environment.pop(key, None)

    def run_release(self, *, revision: str = SHA_NEW, **changes: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["bash", str(DEPLOY / "backend-release.sh"), revision],
            env={**self.environment, **changes},
            capture_output=True,
            text=True,
            check=False,
        )

        for call in self.calls():
            if call.startswith("checker-override|"):
                self.assertFalse(Path(call.split("|", 1)[1]).exists())
        return result

    def calls(self) -> list[str]:
        return self.trace.read_text().splitlines() if self.trace.exists() else []

    def config_with_open_gate(self) -> str:
        config = json.loads(json.dumps(self.closed_config))
        config["services"]["queue-worker"]["environment"]["ALLOW_REAL_SENDS"] = "true"
        return json.dumps(config)

    def test_digest_promotion_never_builds_and_persists_public_pin(self):
        image = "ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:" + "1" * 64
        result = self.run_release(RELEASE_IMAGE_REF=image)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any("compose build" in call for call in self.calls()))
        pin = json.loads((self.new / "docker-compose.override.yml").read_text())
        self.assertEqual({v["image"] for v in pin["services"].values()}, {image})
        self.assertEqual({v["environment"]["PASTORAI_RELEASE_SHA"] for v in pin["services"].values()}, {SHA_NEW})

    def test_digest_recovery_reuses_previous_image_without_build(self):
        image = "ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:" + "1" * 64
        result = self.run_release(RELEASE_IMAGE_REF=image, HEALTH_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("compose build" in call for call in self.calls()))
        self.assertTrue(any("checker-start|" in call for call in self.calls()))
        self.assertTrue(any("image-overlay|" in call and "sha256:" + "0" * 63 + "1" in call for call in self.calls()))
        self.assertEqual((self.root / "current").resolve(), self.old.parent)
        self.assertFalse((self.new / "docker-compose.override.yml").exists())

    def test_mutable_wrong_repository_or_wrong_revision_digest_is_refused(self):
        base = "ghcr.io/haniellevi/pastorai-lionclaw-v1-backend"
        for changes in (
            {"RELEASE_IMAGE_REF": base + ":latest"},
            {"RELEASE_IMAGE_REF": "ghcr.io/other/backend@sha256:" + "1" * 64},
            {"RELEASE_IMAGE_REF": base + "@sha256:" + "1" * 64, "CANDIDATE_IMAGE_SHA": SHA_OLD},
            {"RELEASE_IMAGE_REF": base + "@sha256:" + "1" * 64, "PREVIOUS_IMAGE_SHA": "unknown"},
            {"RELEASE_IMAGE_REF": base + "@sha256:" + "1" * 64, "INCONSISTENT_PREVIOUS_IMAGES": "1"},
            {"RELEASE_IMAGE_REF": base + "@sha256:" + "1" * 64, "DOCKER_HOST": "tcp://remote.invalid:2375"},
        ):
            with self.subTest(changes=changes):
                result = self.run_release(**changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.new / "configuration.fixture").exists())

    def test_concurrent_release_refuses_both_modes_before_any_docker_or_configuration(self):
        import fcntl
        image = "ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:" + "1" * 64
        with (self.root / "releases/.backend-release.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for mode in ("", image):
                with self.subTest(mode=mode):
                    result = self.run_release(RELEASE_IMAGE_REF=mode)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("another backend release is in progress", result.stderr)
                    self.assertFalse(self.calls())
                    self.assertFalse((self.new / "configuration.fixture").exists())
                    self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def _assert_lock_lifetime(self, image, fail=False):
        import fcntl
        path = self.root / "releases/.backend-release.lock"
        result = self.run_release(RELEASE_IMAGE_REF=image, LOCK_TEST_FILE=str(path), HEALTH_EXIT="1" if fail else "0")
        self.assertEqual(result.returncode, 1 if fail else 0, result.stderr)
        self.assertNotIn("release lock not held", result.stderr)
        self.assertEqual((self.root / "current").resolve(), self.old.parent if fail else self.new.parent)
        if fail:
            self.assertTrue(any(call.startswith(f"docker|{self.old}|compose start --wait") for call in self.calls()))
        # The command double probes the real lock during every Docker call.
        # It must be released after activation and cleanup finish.
        with path.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_legacy_release_holds_common_lock_until_exit(self):
        self._assert_lock_lifetime("")

    def test_digest_release_holds_common_lock_until_exit(self):
        self._assert_lock_lifetime("ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:" + "1" * 64)

    def test_legacy_recovery_holds_common_lock_until_exit(self):
        self._assert_lock_lifetime("", fail=True)

    def test_digest_recovery_holds_common_lock_until_exit(self):
        self._assert_lock_lifetime("ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:" + "1" * 64, fail=True)

    def test_digest_containment_failure_never_starts_application_or_checker(self):
        image = "ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:" + "1" * 64
        result = self.run_release(RELEASE_IMAGE_REF=image, CONSUMER_STILL_RUNNING="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("consumer containment unverifiable", result.stderr)
        self.assertFalse(any("compose start --wait" in call or "checker-start|" in call for call in self.calls()))

    def test_stopped_digest_mismatch_never_starts_candidate(self):
        image = "ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:" + "1" * 64
        result = self.run_release(RELEASE_IMAGE_REF=image, CREATED_IMAGE_ID="4")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stopped container image mismatch", result.stderr)
        self.assertFalse(any("docker|" + str(self.new) + "|compose start --wait" in call for call in self.calls()))

    def test_unreviewed_compatibility_bundle_blocks_before_configuration_or_services(self):
        bundle=self.root/'schema.json'
        bundle.write_text('{}')
        result=self.run_release(RELEASE_SCHEMA_BUNDLE=str(bundle))
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(self.calls())
        self.assertFalse((self.new/'configuration.fixture').exists())

    def test_reviewed_but_invalid_bundle_never_relaxes_ledger_or_starts_candidate(self):
        for filename in ('emit_schema_check.py','schema_compatibility.py'):
            (self.new/filename).write_bytes((DEPLOY/filename).read_bytes())
        bundle=self.root/'schema.json'
        bundle.write_text('{}')
        result=self.run_release(RELEASE_SCHEMA_BUNDLE=str(bundle),
            RELEASE_SCHEMA_BUNDLE_SHA256=hashlib.sha256(bundle.read_bytes()).hexdigest())
        self.assertNotEqual(result.returncode,0)
        self.assertIn('reviewed schema verifier refused',result.stderr)
        self.assertFalse(any('build' in call or 'restart' in call for call in self.calls()))
        self.assertEqual((self.root/'current').resolve(),self.old.parent)

    def test_incompatible_timeout_blocks_before_configuration_or_services(self):
        result = self.run_release(TIMEOUT_OPTIONS_EXIT="125")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("timeout options unavailable", result.stderr)
        self.assertTrue(any("--signal=TERM --kill-after=5s 1s true" in c for c in self.calls()))
        self.assertFalse(any("compose build " in c or "compose up " in c
                             or self.stop_marker in c or "compose start --wait " in c
                             for c in self.calls()))
        self.assertFalse((self.new / "configuration.fixture").exists())
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_rollback_recreates_all_normal_services_after_checker_zero(self):
        result = self.run_release(HEALTH_EXIT="17")
        self.assertEqual(result.returncode, 17, result.stderr)
        calls = self.calls()
        wait = calls.index(f"checker-wait|{self.old}")
        self.assertIn(f"created|{self.old}|normal|{SERVICES}", calls)
        normal = calls.index(f"created|{self.old}|normal|{SERVICES}")
        start = next(i for i, c in enumerate(calls)
                     if c.startswith(f"docker|{self.old}|compose start --wait "))
        self.assertLess(wait, normal)
        self.assertLess(normal, start)
        self.assertEqual(
            calls[normal + 1:start],
            [f"inspect|{self.old}|{service}" for service in SERVICES.split()],
        )
        self.assertFalse(any("rejected-app-start|" in c for c in calls))

    def test_compose_capabilities_block_before_any_effect(self):
        for changes in (
            {"COMPOSE_VERSION": "2.40.0"}, {"COMPOSE_VERSION": "invalid"},
            {"VERSION_EXIT": "1"}, {"NO_WAIT": "1"}, {"NO_TIMEOUT": "1"},
            {"HELP_EXIT": "1"},
        ):
            with self.subTest(changes=changes):
                self.trace.write_text("")
                result = self.run_release(**changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any("compose up " in c or self.stop_marker in c
                                     or "compose build " in c for c in self.calls()))
                self.assertFalse((self.new / "configuration.fixture").exists())

    def test_rollback_checker_transport_and_order(self):
        result = self.run_release(HEALTH_EXIT="1")
        self.assertEqual(result.returncode, 1, result.stderr)
        calls = self.calls()
        self.assertFalse(any("compose run " in c or "start --attach" in c for c in calls))
        self.assertTrue(any("timeout|" in c and "180s docker wait backend" in c for c in calls))
        expected = hashlib.sha256((self.old / "check_backend_schema.py").read_bytes()).hexdigest()
        copy = calls.index(f"checker-copy|{self.old}|{expected}")
        check = calls.index(f"checker-start|{self.old}")
        wait = calls.index(f"checker-wait|{self.old}")
        start = next(i for i, c in enumerate(calls) if f"docker|{self.old}|compose start --wait " in c)
        self.assertLess(copy, check)
        self.assertLess(check, wait)
        self.assertLess(wait, start)
        self.assertIn('checker-manifest|["0001_synthetic.sql"]', calls)
        self.assertIn(f"inspect|{self.old}|backend", calls[:copy])

    def test_rollback_checker_failures_keep_application_stopped(self):
        for changes in (
            {"COPY_EXIT": "1"}, {"CHECKER_START_EXIT": "1"},
            {"CHECKER_WAIT_EXIT": "1"}, {"CHECKER_TIMEOUT_EXIT": "124"},
            {"ROLLBACK_PREFLIGHT_EXIT": "7"},
            {"ROLLBACK_PREFLIGHT_EXIT": ""}, {"ROLLBACK_CREATE_EXIT": "1"},
            *self.rollback_ps_failure, {"ROLLBACK_STOPPED_GATES_EXIT": "1"},
        ):
            with self.subTest(changes=changes):
                self.trace.write_text("")
                result = self.run_release(HEALTH_EXIT="1", **changes)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(any(f"docker|{self.old}|compose start --wait " in c for c in self.calls()))
                self.assertTrue(any(f"docker|{self.old}{self.stop_marker}" in c for c in self.calls()))
                self.assertFalse((self.new / "configuration.fixture").exists())
                if changes.get("ROLLBACK_STOPPED_GATES_EXIT"):
                    self.assertFalse(any("checker-start|" in c for c in self.calls()))

    def test_checker_timeout_with_failed_containment_reports_human_recovery(self):
        result = self.run_release(
            HEALTH_EXIT="17", CHECKER_TIMEOUT_EXIT="124", ROLLBACK_STOP_EXIT="1"
        )
        self.assertEqual(result.returncode, 17)
        self.assertIn("rollback containment failed", result.stderr)
        self.assertFalse(any(f"docker|{self.old}|compose start --wait " in c for c in self.calls()))
        self.assertTrue((self.old / "configuration.fixture").exists())

    def assert_rollback_prerequisites_refused_before_effects(self):
        active_configuration = (self.old / "configuration.fixture").read_bytes()
        result = self.run_release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rollback schema compatibility", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.new / "configuration.fixture").exists())
        self.assertEqual((self.root / "current").resolve(), self.old.parent)
        self.assertEqual((self.old / "configuration.fixture").read_bytes(), active_configuration)

    def test_missing_previous_manifest_blocks_before_configuration_or_services(self):
        (self.old.parent / "backend/scripts/migrate.py").unlink()
        self.assert_rollback_prerequisites_refused_before_effects()

    def test_invalid_previous_manifest_blocks_before_configuration_or_services(self):
        for selection in ("[]", "None", "'0001_synthetic.sql'", "[None]",
                          "['../0001_synthetic.sql']", "['0001_synthetic.sql'] * 2"):
            with self.subTest(selection=selection):
                self.setUp()
                (self.old.parent / "backend/scripts/migrate.py").write_text(
                    f"def migration_files(path): return {selection}\n"
                )
                self.assert_rollback_prerequisites_refused_before_effects()

    def test_previous_manifest_loader_without_selection_blocks_before_effects(self):
        (self.old.parent / "backend/scripts/migrate.py").write_text("# SYNTHETIC NO LOADER\n")
        self.assert_rollback_prerequisites_refused_before_effects()

    def test_previous_schema_failure_blocks_before_build_or_services(self):
        result = self.run_release(PREVIOUS_PREFLIGHT_EXIT="19")
        self.assertEqual(result.returncode, 19, result.stderr)
        calls = self.calls()
        expected = hashlib.sha256((self.old / "check_backend_schema.py").read_bytes()).hexdigest()
        self.assertIn(f"preflight-checker|{self.old}|{expected}", calls)
        self.assertIn(
            f'docker|{self.old}|compose exec -T -e EXPECTED_MIGRATIONS=["0001_synthetic.sql"] backend python -',
            calls,
        )
        self.assertFalse(any("compose build " in c or "compose up " in c
                             or self.stop_marker in c or "compose start --wait " in c
                             for c in calls))
        self.assertFalse((self.new / "configuration.fixture").exists())
        self.assertEqual((self.root / "current").resolve(), self.old.parent)
        self.assertEqual((self.old / "configuration.fixture").read_text(), "SYNTHETIC=1\n")

    def test_both_release_checkers_run_before_build_with_own_sources_and_manifests(self):
        result = self.run_release()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        checks = [c for c in calls if "|compose exec -T -e EXPECTED_MIGRATIONS=" in c]
        self.assertEqual(len(checks), 2)
        self.assertIn('EXPECTED_MIGRATIONS=["0001_synthetic.sql"] backend python -', checks[0])
        manifest = json.loads(checks[1].split("EXPECTED_MIGRATIONS=", 1)[1].rsplit(" backend python -", 1)[0])
        self.assertEqual(
            manifest,
            sorted(p.name for p in (DEPLOY.parent / "backend/migrations").glob("*.sql")
                   if p.is_file() and "OPERATIONAL_AUTHORIZATION=BLOCKED" not in p.read_text()),
        )
        for directory, check in zip((self.old, self.new), checks, strict=True):
            expected = hashlib.sha256((directory / "check_backend_schema.py").read_bytes()).hexdigest()
            self.assertEqual(calls[calls.index(check) - 1], f"preflight-checker|{self.old}|{expected}")
        build = next(i for i, c in enumerate(calls) if f"docker|{self.new}|compose build " in c)
        self.assertLess(calls.index(checks[0]), calls.index(checks[1]))
        self.assertLess(calls.index(checks[1]), build)

    def test_failed_candidate_does_not_retain_private_configuration(self):
        result = self.run_release(BUILD_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.new / "configuration.fixture").exists())
        self.assertTrue((self.old / "configuration.fixture").exists())

    def test_missing_previous_checker_blocks_before_configuration_or_services(self):
        (self.old / "check_backend_schema.py").unlink()
        self.assert_rollback_prerequisites_refused_before_effects()

    def test_candidate_gates_verified_before_start(self):
        result = self.run_release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any("compose up " in c and "--no-start" not in c for c in self.calls()))
        calls = self.calls()
        self.assertIn("timeout-probe|configuration-absent", calls)
        self.assertTrue(any("compose up --no-start " in c for c in calls))
        self.assertTrue(any("compose start --wait " in c for c in calls))
        self.assert_inspected_before_start(self.new)

    def test_interrupt_and_termination_contain_candidate_and_rollback(self):
        for signal_name, status in (("INT", 130), ("TERM", 143)):
            with self.subTest(signal=signal_name):
                self.trace.write_text("")
                result = self.run_release(SIGNAL_ON_START=signal_name)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertTrue(any(f"docker|{self.new}{self.stop_marker}" in c for c in self.calls()))
                self.assert_inspected_before_start(self.old)
                self.assertEqual((self.root / "current").resolve(), self.old.parent)
                self.assertFalse((self.new / "configuration.fixture").exists())
                self.assertTrue((self.old / "configuration.fixture").exists())

    def test_failed_containment_preserves_configuration_for_recovery(self):
        result = self.run_release(HEALTH_EXIT="1", STOP_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("containment failed", result.stderr)
        self.assertTrue((self.new / "configuration.fixture").exists())
        self.assertTrue((self.old / "configuration.fixture").exists())
        self.assertFalse(any(f"docker|{self.old}|compose start --wait " in c for c in self.calls()))

    def assert_inspected_before_start(self, directory):
        calls = self.calls()
        start = next(i for i, call in enumerate(calls)
                     if call.startswith(f"docker|{directory}|compose start --wait "))
        self.assertEqual(
            [call for call in calls[:start] if call.startswith(f"inspect|{directory}|")],
            [f"inspect|{directory}|{service}" for service in
             (["backend"] + SERVICES.split() if directory == self.old else SERVICES.split())],
        )

    def test_rollback_incompatible_schema_never_starts_previous_code(self):
        result = self.run_release(HEALTH_EXIT="1", ROLLBACK_PREFLIGHT_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(f"docker|{self.old}|compose start --wait " in c for c in self.calls()))
        self.assertTrue(any(self.stop_marker in c for c in self.calls()))

    def test_stopped_container_open_gates_never_start(self):
        result = self.run_release(STOPPED_GATES_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("compose start --wait " in c for c in self.calls()))

    def test_candidate_symlink_cannot_overwrite_active_configuration(self):
        import shutil
        shutil.rmtree(self.new.parent)
        self.new.parent.symlink_to(self.old.parent)
        result = self.run_release()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.old / "configuration.fixture").exists())
        self.assertFalse(self.calls())

    def test_existing_candidate_configuration_is_not_overwritten(self):
        (self.new / "configuration.fixture").write_text("KEEP_SYNTHETIC\n")
        result = self.run_release()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.new / "configuration.fixture").read_text(), "KEEP_SYNTHETIC\n")

    def test_all_services_refuse_each_missing_or_open_compose_gate(self):
        for service in SERVICES.split():
            for gate in ("ALLOW_REAL_SENDS", "ASAAS_BILLING_ENABLED", "BREVO_SEND_MODE", "BROADCAST_ASYNC_ENABLED"):
                for value in (None, "true"):
                    with self.subTest(service=service, gate=gate, value=value):
                        config = json.loads(json.dumps(self.closed_config))
                        environment = config["services"][service]["environment"]
                        if value is None:
                            environment.pop(gate)
                        else:
                            environment[gate] = value
                        if self.trace.exists():
                            self.trace.unlink()
                        result = self.run_release(CANDIDATE_CONFIG_JSON=json.dumps(config))
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse(any("compose start --wait " in c for c in self.calls()))
                        self.assertFalse((self.new / "configuration.fixture").exists())

    def test_schema_failure_stops_before_build_or_restart(self) -> None:
        result = self.run_release(PREFLIGHT_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("before restart", result.stderr)
        self.assertEqual(
            [call.rsplit("|", 1)[-1] for call in self.calls() if call.startswith("gates|")],
            ["backend", "queue-worker", "cron-worker", "broadcast-worker"],
        )
        self.assertIn("compose exec -T -e EXPECTED_MIGRATIONS=", self.calls()[-1])
        self.assertIn(" backend python -", self.calls()[-1])
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_open_external_gate_stops_before_schema_or_build(self) -> None:
        result = self.run_release(ALLOW_REAL_SENDS="true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("external-effect gates open or unverifiable", result.stderr)
        self.assertFalse(any("python -" in call or "compose build" in call for call in self.calls()))
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_candidate_effective_gate_stops_before_build_or_restart(self) -> None:
        result = self.run_release(CANDIDATE_CONFIG_JSON=self.config_with_open_gate())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("effective Compose gates open or unverifiable", result.stderr)
        self.assertFalse(any("compose build" in call or "compose start --wait " in call for call in self.calls()))
        self.assertFalse(any("python -" in call for call in self.calls()))
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_build_failure_keeps_previous_containers(self) -> None:
        result = self.run_release(BUILD_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any(f"compose build --build-arg PASTORAI_RELEASE_SHA={SHA_NEW} backend" in call for call in self.calls()))
        self.assertFalse(any("compose start --wait " in call for call in self.calls()))
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_candidate_build_receives_exact_release_revision(self) -> None:
        result = self.run_release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"docker|{self.new}|compose build --build-arg PASTORAI_RELEASE_SHA={SHA_NEW} backend",
            self.calls(),
        )

    def test_unverifiable_candidate_revision_stops_before_build(self) -> None:
        for revision in ("", "legacy", "b" * 39, "B" * 40):
            with self.subTest(revision=revision):
                result = self.run_release(revision=revision)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exact 40-character release SHA", result.stderr)
                self.assertEqual(self.calls(), [])

    def test_unverifiable_rollback_revision_stops_before_effects(self) -> None:
        legacy = self.old.parent.with_name("legacy")
        self.old.parent.rename(legacy)
        (self.root / "current").unlink()
        (self.root / "current").symlink_to(legacy)

        result = self.run_release()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact SHA required for rollback", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.new / "configuration.fixture").exists())

    def test_rollback_recreates_all_normal_services_after_checker_zero(self):
        result = self.run_release(HEALTH_EXIT="17")
        self.assertEqual(result.returncode, 17, result.stderr)
        calls = [c for c in self.calls() if not c.startswith("image-overlay|")]  # previous pin parsed per call
        wait = calls.index(f"checker-wait|{self.old}")
        normal = calls.index(f"created|{self.old}|normal|{SERVICES}")
        start = next(i for i, c in enumerate(calls) if c.startswith(f"docker|{self.old}|compose start --wait "))
        self.assertLess(wait, normal)
        self.assertEqual(calls[normal + 1:start], [f"inspect|{self.old}|{service}" for service in SERVICES.split()])
        self.assertFalse(any("rejected-app-start|" in c for c in calls))

    def test_health_failure_restarts_previous_code(self) -> None:
        result = self.run_release(HEALTH_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        calls = self.calls()
        self.assertTrue(any(f"docker|{self.new}|compose start --wait " in call for call in calls))
        self.assertIn(f"docker|{self.old}|compose build --build-arg PASTORAI_RELEASE_SHA={SHA_OLD} backend", calls)
        self.assertTrue(
            any(f"docker|{self.old}|compose start --wait " in call and SERVICES in call for call in calls)
        )
        self.assertEqual((self.root / "current").resolve(), self.old.parent)
        self.assert_inspected_before_start(self.new)
        self.assert_inspected_before_start(self.old)

    def test_failed_candidate_restart_rolls_back(self) -> None:
        result = self.run_release(RESTART_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(
            any(
                f"docker|{self.old}|compose start --wait " in call and SERVICES in call
                for call in self.calls()
            )
        )
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_candidate_gate_change_rolls_back_code(self) -> None:
        result = self.run_release(CANDIDATE_GATES_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any(f"docker|{self.old}|compose start --wait " in call for call in self.calls()))
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_rollback_refuses_open_effective_config_before_old_restart(self) -> None:
        result = self.run_release(
            HEALTH_EXIT="1", ROLLBACK_CONFIG_JSON=self.config_with_open_gate()
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rollback of code is unhealthy", result.stderr)
        self.assertFalse(any(f"docker|{self.old}|compose start --wait " in call for call in self.calls()))

    def test_rollback_failure_reports_incomplete_recovery(self) -> None:
        result = self.run_release(HEALTH_EXIT="1", ROLLBACK_BUILD_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rollback of code is unhealthy", result.stderr)
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_healthy_candidate_becomes_current(self) -> None:
        result = self.run_release(COMPOSE_VERSION="v5.5.1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "current").resolve(), self.new.parent)
        up_calls = [call for call in self.calls() if "compose start --wait " in call]
        self.assertEqual(len(up_calls), 1)
        self.assertIn(SERVICES, up_calls[0])


def topology_contract(**changes):
    contract = {
        "schema": "pastorai.release-topology", "version": 1, "project": PROJECT, "legacy_project": "pastorai",
        "network": {"name": NETWORK, "id": "e" * 64},
        "containers": {service: f"{PROJECT}-{service}" for service in SERVICES.split()},
        "reserved_legacy": {service: str(index) * 64 for index, service in enumerate(SERVICES.split(), 1)},
    }
    contract.update(changes)
    return contract


class TopologyReleaseTest(BackendReleaseTest):
    """The whole suite again with an adopted topology, plus its own guards."""

    stop_marker = "|stop "  # containment stops proven-owned IDs, never by service name
    # The predecessor's identity is read before any effect here (see the dedicated test).
    rollback_ps_failure = ()

    def test_unreadable_predecessor_identity_refuses_before_restart(self):
        result = self.run_release(ROLLBACK_PS_EXIT="1")
        self.assertIn("deploy stopped before restart", result.stderr)
        self.assert_no_effects(result)

    def setUp(self) -> None:
        BackendReleaseTest.setUp(self)  # explicit: reused by the layout contract test
        self.contract = topology_contract()
        self.contract_path = self.old / "release-topology.json"
        self.contract_path.write_text(json.dumps(self.contract))
        services = {name: {"container_name": self.contract["containers"][name], "networks": {"default": None},
                           "image": "pastorai-backend:latest"} for name in SERVICES.split()}
        self.topology_model = {"name": PROJECT, "networks": {"default": {"name": NETWORK, "external": True}},
                               "services": services}
        self.environment.update(TOPOLOGY_PROJECT=PROJECT, WORLD_CONTRACT=str(self.contract_path),
                                TOPOLOGY_CONFIG_JSON=json.dumps(self.topology_model))

    def run_release(self, *, revision: str = SHA_NEW, **changes: str) -> subprocess.CompletedProcess[str]:
        # Each invocation starts from a running predecessor; the world never carries over.
        for suffix in (".world.json", ".topology"):
            Path(str(self.trace) + suffix).unlink(missing_ok=True)
        result = BackendReleaseTest.run_release(self, revision=revision, **changes)
        self.assertFalse([c for c in self.calls() if c.startswith("bad-compose|")], result.stderr)
        return result

    def topology_calls(self) -> list[str]:
        path = Path(str(self.trace) + ".topology")
        return path.read_text().splitlines() if path.exists() else []

    def assert_no_effects(self, result) -> None:
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(" up " in c or "|stop " in c or "compose stop" in c or "compose build" in c
                             or "compose start" in c
                             for c in self.calls()), self.calls())
        self.assertFalse((self.new / "configuration.fixture").exists())
        self.assertEqual((self.root / "current").resolve(), self.old.parent)
        self.assertFalse((self.new / "release-topology.json").exists())
        self.assertFalse((self.new / "docker-compose.override.yml").exists())

    def test_digest_promotion_never_builds_and_persists_public_pin(self):
        image = "ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:" + "1" * 64
        result = self.run_release(RELEASE_IMAGE_REF=image)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any("compose build" in call for call in self.calls()))
        override = (self.new / "docker-compose.override.yml").read_text()
        self.assertIn(f'"image": "{image}"', override)
        self.assertIn(f'"PASTORAI_RELEASE_SHA": "{SHA_NEW}"', override)
        self.assertIn(f'"name": "{PROJECT}"', override)

    def test_rollback_recreates_all_normal_services_after_checker_zero(self):
        result = self.run_release(HEALTH_EXIT="17")
        self.assertEqual(result.returncode, 17, result.stderr)
        calls = [c for c in self.calls() if not c.startswith("image-overlay|")]  # previous pin parsed per call
        wait = calls.index(f"checker-wait|{self.old}")
        normal = calls.index(f"created|{self.old}|normal|{SERVICES}")
        start = next(i for i, c in enumerate(calls) if c.startswith(f"docker|{self.old}|compose start --wait "))
        self.assertLess(wait, normal)
        self.assertEqual(calls[normal + 1:start], [f"inspect|{self.old}|{service}" for service in SERVICES.split()])
        self.assertFalse(any("rejected-app-start|" in c for c in calls))

    def test_health_failure_restarts_previous_code(self) -> None:
        result = self.run_release(HEALTH_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        calls = self.calls()
        self.assertTrue(any(f"docker|{self.new}|compose start --wait " in call for call in calls))
        # Never rebuilt: the predecessor returns on its verified immutable image ID.
        self.assertFalse(any(f"docker|{self.old}|compose build" in call for call in calls))
        self.assertTrue(any(f"docker|{self.old}|compose start --wait " in call and SERVICES in call for call in calls))
        self.assertTrue(any(c.startswith("image-overlay|") and c.endswith("sha256:" + "0" * 63 + "1") for c in calls))
        self.assertEqual((self.root / "current").resolve(), self.old.parent)
        self.assert_inspected_before_start(self.new)
        self.assert_inspected_before_start(self.old)

    def test_rollback_failure_reports_incomplete_recovery(self) -> None:
        result = self.run_release(HEALTH_EXIT="1", ROLLBACK_HEALTH_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rollback of code is unhealthy", result.stderr)
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_built_candidate_with_wrong_revision_label_never_starts(self) -> None:
        result = self.run_release(CANDIDATE_IMAGE_SHA="c" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("built candidate image revision unverifiable", result.stderr)
        self.assertFalse(any("compose start --wait" in c or " up " in c for c in self.calls()))
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_stranger_member_appearing_during_rollback_is_never_touched(self) -> None:
        result = self.run_release(HEALTH_EXIT="1", WORLD_STRANGER_ON_START="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stranger project member left untouched", result.stderr)
        stops = [c for c in self.topology_calls() if c.startswith("stop|")]
        self.assertTrue(stops and all("%064x" % 0xbb not in c for c in stops))
        self.assertFalse(any(f"docker|{self.old}|compose start --wait" in c for c in self.calls()))
        # Human recovery: candidate configuration kept WITH its usable topology and immutable pin.
        self.assertTrue((self.new / "configuration.fixture").exists())
        self.assertTrue(self.contract_path.exists())
        self.assertEqual((self.root / "current").resolve(), self.old.parent)
        self.assert_candidate_recovery_files("sha256:" + "0" * 63 + "2")

    def test_digest_stranger_during_rollback_keeps_digest_pin_for_recovery(self) -> None:
        image = "ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:" + "1" * 64
        result = self.run_release(RELEASE_IMAGE_REF=image, HEALTH_EXIT="1", WORLD_STRANGER_ON_START="1")
        self.assertIn("stranger project member left untouched", result.stderr)
        self.assertTrue((self.new / "configuration.fixture").exists())
        self.assert_candidate_recovery_files(image)

    def test_refusal_after_image_validation_removes_candidate_topology_files(self) -> None:
        result = self.run_release(WORLD_ALIAS_CONFLICT="backend", WORLD_ALIAS_CONFLICT_ON_BUILD="1")
        self.assertIn("alias-conflict", result.stderr)
        self.assertIn("deploy stopped before restart", result.stderr)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any("compose build" in c for c in self.calls()))  # image validated, then refused
        self.assertFalse(any(" up " in c or "|stop " in c or "compose start" in c for c in self.calls()))
        for name in ("configuration.fixture", "release-topology.json", "docker-compose.override.yml"):
            self.assertFalse((self.new / name).exists(), name)
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def assert_candidate_recovery_files(self, image: str) -> None:
        self.assertEqual(json.loads((self.new / "release-topology.json").read_text()), self.contract)
        override = self.new / "docker-compose.override.yml"
        for path in (override, self.new / "release-topology.json"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        docker = shutil.which("docker", path=os.environ["PATH"])
        if docker is None:
            self.skipTest("Docker Compose parser unavailable for the manual-maintenance proof")
        # Manual maintenance exactly as an operator would run it in the candidate tree:
        # no -p/-f, so Compose auto-loads the persisted override over the real base file.
        with tempfile.TemporaryDirectory(prefix="topology-recovery-") as directory:
            work = Path(directory)
            (work / "docker-compose.yml").write_bytes((DEPLOY / "docker-compose.yml").read_bytes())
            (work / "docker-compose.override.yml").write_bytes(override.read_bytes())
            done = subprocess.run([docker, "compose", "config", "--format", "json", "--no-env-resolution"],
                                  cwd=work, capture_output=True, text=True,
                                  env={"PATH": os.environ["PATH"], "DOCKER_CONFIG": str(work / "docker-config"),
                                       "PASTORAI_ENV_FILE": "configuration.fixture"})
        self.assertEqual(done.returncode, 0, done.stderr)
        model = json.loads(done.stdout)
        TOPOLOGY["check_config"](self.contract, model)
        self.assertEqual(model["name"], PROJECT)
        for service in SERVICES.split():
            self.assertEqual(model["services"][service]["image"], image)
            self.assertEqual(model["services"][service]["environment"]["PASTORAI_RELEASE_SHA"], SHA_NEW)

    def test_degraded_dependency_never_blocks_containment(self) -> None:
        result = self.run_release(HEALTH_EXIT="1", WORLD_DEP_DOWN_ON_START="redis")
        self.assertNotEqual(result.returncode, 0)
        stops = [c for c in self.topology_calls() if c.startswith("stop|")]
        self.assertTrue(stops)  # candidate stopped although Redis is down
        self.assertIn("dependency-not-running", result.stderr)  # previous code is not started without it
        self.assertFalse(any(f"docker|{self.old}|compose start --wait" in c for c in self.calls()))
        self.assertFalse((self.new / "configuration.fixture").exists())

    def test_every_compose_call_has_project_and_ordered_files(self):
        image = "ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:" + "1" * 64
        for mode, failure in (("", ""), (image, ""), ("", "1"), (image, "1")):
            with self.subTest(image=bool(mode), rollback=bool(failure)):
                for path in (self.trace, Path(str(self.trace) + ".topology"), Path(str(self.trace) + ".world.json")):
                    path.unlink(missing_ok=True)
                for leftover in ("release-topology.json", "docker-compose.override.yml", "configuration.fixture"):
                    (self.new / leftover).unlink(missing_ok=True)
                (self.root / "current").unlink()
                (self.root / "current").symlink_to(self.old.parent)
                result = self.run_release(RELEASE_IMAGE_REF=mode, HEALTH_EXIT=failure or "0")
                self.assertEqual(result.returncode, 1 if failure else 0, result.stderr)
                kinds = {line.split("|")[2] for line in self.topology_calls() if line.startswith("compose|")}
                # The predecessor is always pinned to its verified ID; a built candidate only after build.
                expected = {"base,topology", "base,topology,pin"}
                if failure:
                    expected |= {"base,topology,checker,pin"}
                self.assertEqual(kinds, expected)
                previous = [c for c in self.topology_calls() if c.startswith(f"compose|{self.old}|")
                            and (" up " in c or " start " in c)]
                self.assertEqual(bool(previous), bool(failure))
                self.assertTrue(all(c.split("|")[2].endswith("pin") for c in previous))

    def test_success_persists_contract_and_maintenance_override(self):
        result = self.run_release()
        self.assertEqual(result.returncode, 0, result.stderr)
        persisted = self.new / "release-topology.json"
        self.assertEqual(json.loads(persisted.read_text()), self.contract)
        override = (self.new / "docker-compose.override.yml").read_text()
        self.assertIn(f'"name": "{PROJECT}"', override)
        self.assertIn(f'"default": {{"name": "{NETWORK}", "external": true}}', override)
        self.assertIn('"image": "sha256:' + "0" * 63 + '2"', override)  # built ID, not the mutable tag
        self.assertIn(f'"PASTORAI_RELEASE_SHA": "{SHA_NEW}"', override)
        for path in (persisted, self.new / "docker-compose.override.yml"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        calls = self.calls()
        retain_previous = next(i for i, c in enumerate(calls) if c.endswith(
            "image tag sha256:" + "0" * 63 + f"1 pastorai-backend-release:{SHA_OLD}"))
        build = next(i for i, c in enumerate(calls) if "compose build" in c)
        self.assertLess(retain_previous, build)  # kept before any build can move the mutable tag
        self.assertTrue(any(c.endswith("image tag sha256:" + "0" * 63 + f"2 pastorai-backend-release:{SHA_NEW}")
                            for c in calls[build:]))
        self.assertFalse(list(Path("/tmp").glob("backend-topology.*")))

    def test_guards_precede_stop_and_are_repeated_before_start(self):
        image = "ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:" + "1" * 64
        result = self.run_release(RELEASE_IMAGE_REF=image)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.topology_calls()
        first_effect = next(i for i, c in enumerate(lines) if c.startswith("stop|") or " up " in c)
        running = "backend=running,queue-worker=running,cron-worker=running,broadcast-worker=running"
        self.assertTrue(any(c.endswith(running) for c in lines[:first_effect] if c.startswith("guard|")))
        create = next(i for i, c in enumerate(lines) if c.startswith(f"compose|{self.new}|") and " up " in c)
        start = next(i for i, c in enumerate(lines) if c.startswith(f"compose|{self.new}|") and "start --wait " in c)
        self.assertTrue(any(c.startswith("guard|") and c.endswith("broadcast-worker=exited")
                            for c in lines[first_effect:create]))
        self.assertTrue(any(c.startswith("guard|") and "backend=created" in c for c in lines[create:start]))

    def test_rollback_guards_checker_and_previous_start(self):
        result = self.run_release(HEALTH_EXIT="1")
        self.assertEqual(result.returncode, 1, result.stderr)
        lines = self.topology_calls()
        checker_up = next(i for i, c in enumerate(lines) if "checker" in c.split("|")[2] and " up " in c)
        checker_start = next(i for i, c in enumerate(lines) if "checker" in c.split("|")[2]
                             and c.endswith("compose start backend"))
        self.assertTrue(any(c.startswith("guard|") and "backend=created" in c and "queue-worker=exited" in c
                            for c in lines[checker_up:checker_start]))
        old_start = max(i for i, c in enumerate(lines) if c.startswith(f"compose|{self.old}|") and "start --wait" in c)
        self.assertTrue(lines[old_start - 1].startswith(f"guard|{self.old}|backend=created"))
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_unsafe_docker_state_refuses_before_effects(self):
        for changes in (
            {"WORLD_LEGACY_RUNNING": "queue-worker"}, {"WORLD_LEGACY_POLICY": "cron-worker"},
            {"WORLD_LEGACY_MISSING": "broadcast-worker"}, {"WORLD_LEGACY_IN_PROJECT": "backend"},
            {"WORLD_ALIAS_CONFLICT": "backend"}, {"WORLD_ALIAS_CONFLICT": "broadcast-worker"},
            {"WORLD_DEP_MISSING": "redis"}, {"WORLD_DEP_MISSING": "evolution-api"},
            {"WORLD_DEP_UNHEALTHY": "redis"}, {"WORLD_DEP_DUPLICATE": "evolution-api"},
            {"WORLD_NETWORK_ID": "f" * 64}, {"WORLD_WRONG_NAME": "cron-worker"},
            {"WORLD_PREDECESSOR_STOPPED": "queue-worker"}, {"WORLD_FOREIGN_SERVICE": "1"},
            {"PREVIOUS_IMAGE_SHA": "c" * 40},
            {"DOCKER_HOST": "unix:///synthetic/other.sock"},
        ):
            for image in ("", "ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:" + "1" * 64):
                with self.subTest(changes=changes, image=bool(image)):
                    for path in (self.trace, Path(str(self.trace) + ".world.json")):
                        path.unlink(missing_ok=True)
                    self.assert_no_effects(self.run_release(RELEASE_IMAGE_REF=image, **changes))

    def test_conflict_after_creation_never_starts_candidate_or_previous(self):
        result = self.run_release(WORLD_ALIAS_CONFLICT="queue-worker", WORLD_ALIAS_CONFLICT_ON_CREATE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("alias-conflict", result.stderr)
        self.assertFalse(any("compose start --wait" in c for c in self.calls()))
        self.assertTrue(any(f"docker|{self.new}{self.stop_marker}" in c for c in self.calls()))
        self.assertEqual((self.root / "current").resolve(), self.old.parent)
        self.assertFalse((self.new / "configuration.fixture").exists())

    def test_union_of_networks_on_created_candidate_never_starts(self):
        result = self.run_release(WORLD_CREATED_EXTRA_NETWORK="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("created-network-union", result.stderr)
        self.assertFalse(any("compose start --wait" in c for c in self.calls()))

    def test_effective_model_outside_topology_refuses_before_effects(self):
        for mutate in (
            lambda m: m["services"]["backend"]["networks"].update(second=None),
            lambda m: m["services"]["queue-worker"].update(container_name="pastorai_queue_worker"),
            lambda m: m["services"].update(redis={"container_name": "pastorai_redis", "networks": {"default": None}}),
            lambda m: m.update(name="pastorai"),
            lambda m: m["networks"]["default"].update(external=False),
            lambda m: m["services"]["cron-worker"].update(depends_on={"redis": {"condition": "service_healthy"}}),
        ):
            with self.subTest(mutate=mutate):
                self.trace.unlink(missing_ok=True)
                model = json.loads(json.dumps(self.topology_model))
                mutate(model)
                self.assert_no_effects(self.run_release(TOPOLOGY_CONFIG_JSON=json.dumps(model)))

    def test_invalid_or_untrusted_contract_refuses_before_any_docker_call(self):
        cases = (
            lambda: self.contract_path.write_text("{"),
            lambda: self.contract_path.write_text(json.dumps({**self.contract, "env": {"X": "1"}})),
            lambda: self.contract_path.write_text(json.dumps(topology_contract(project="pastorai"))),
            lambda: self.contract_path.write_text(json.dumps(topology_contract(version=2))),
            lambda: self.contract_path.write_text(json.dumps(self.contract)[:-1] + ', "project": "x"}'),
            lambda: (self.contract_path.unlink(), self.contract_path.symlink_to(self.root / "elsewhere.json"),
                     (self.root / "elsewhere.json").write_text(json.dumps(self.contract))),
            lambda: (self.contract_path.unlink(), (self.old / "compose-project.name").write_text(PROJECT + "\n")),
            lambda: (self.old / "compose-project.name").write_text("pastorai-other\n"),
        )
        for index, damage in enumerate(cases):
            with self.subTest(case=index):
                self.setUp()
                damage()
                result = self.run_release()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("active release topology missing or invalid", result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertFalse((self.new / "configuration.fixture").exists())

    def test_marker_matching_contract_is_accepted(self):
        (self.old / "compose-project.name").write_text(PROJECT + "\n")
        result = self.run_release()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_candidate_with_topology_or_override_from_tarball_refuses(self):
        for name in ("release-topology.json", "compose-project.name", "docker-compose.override.yml"):
            with self.subTest(name=name):
                self.setUp()
                (self.new / name).write_text("{}")
                result = self.run_release()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls(), [])
                self.assertEqual((self.new / name).read_text(), "{}")


class CompatibleReleaseTest(unittest.TestCase):
    def test_marker_without_contract_refuses_and_neither_keeps_single_project_path(self):
        harness = BackendReleaseTest("test_healthy_candidate_becomes_current")
        harness.setUp()
        try:
            (harness.old / "compose-project.name").write_text(PROJECT + "\n")
            result = harness.run_release()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("active release topology missing or invalid", result.stderr)
            self.assertEqual(harness.calls(), [])
            (harness.old / "compose-project.name").unlink()
            result = harness.run_release()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((harness.new / "release-topology.json").exists())
        finally:
            harness.doCleanups()

    def test_candidate_override_from_tarball_refuses_without_digest(self):
        harness = BackendReleaseTest("test_healthy_candidate_becomes_current")
        harness.setUp()
        try:
            (harness.new / "docker-compose.override.yml").write_text("services: {}\n")
            result = harness.run_release()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("existing Compose override", result.stderr)
            self.assertEqual(harness.calls(), [])
        finally:
            harness.doCleanups()


class MigrationLedgerContractTest(unittest.TestCase):
    """Drive the real checker with a literal manifest and synthetic DB results."""

    def check_ledger(self, applied: list[str]) -> tuple[int, str]:
        expected = [
            "20260927_120000_church_cell_public_data.sql",
            "20260927_170000_whatsapp_privilege_actions.sql",
        ]
        policy_rows = [
            (name, command, True, True, using, with_check)
            for name, (command, using, with_check) in SCHEMA["ACTIVATION_POLICIES"].items()
        ]

        class Result:
            def __init__(self, rows=None, scalar=None):
                self.rows = rows
                self.scalar = scalar

            def all(self):
                return self.rows

            def scalar_one_or_none(self):
                return self.scalar

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def exec_driver_sql(self, sql, *_):
                if "SELECT current_database()" in sql:
                    return Result(rows=[("synthetic", "reader", "127.0.0.1", 5432)])
                if "SELECT name FROM public.schema_migrations" in sql:
                    return Result(rows=[(name,) for name in applied])
                if "WITH required(table_name, column_name)" in sql:
                    return Result(rows=[])
                if "SELECT relrowsecurity" in sql:
                    return Result(scalar=True)
                if "SELECT polname" in sql:
                    return Result(rows=policy_rows)
                return Result()

            def rollback(self):
                pass

        class Engine:
            def connect(self):
                return Connection()

            def dispose(self):
                pass

        stderr = io.StringIO()
        with (
            patch.dict(
                os.environ,
                {
                    "DATABASE_URL": "postgresql://synthetic.invalid/local",
                    "EXPECTED_MIGRATIONS": json.dumps(expected),
                },
            ),
            patch.dict(SCHEMA["main"].__globals__, {"create_engine": lambda *_a, **_k: Engine()}),
            contextlib.redirect_stderr(stderr),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = SCHEMA["main"]()
        return status, stderr.getvalue()

    def test_missing_migration_fails_closed(self) -> None:
        status, error = self.check_ledger(
            ["20260927_120000_church_cell_public_data.sql"]
        )
        self.assertEqual(status, 1)
        self.assertIn("migration not applied: 20260927_170000", error)

    def test_empty_ledger_fails_closed(self) -> None:
        status, error = self.check_ledger([])
        self.assertEqual(status, 1)
        self.assertIn("migration not applied: 20260927_120000", error)

    def test_future_migration_fails_closed(self) -> None:
        status, error = self.check_ledger(
            [
                "20260927_120000_church_cell_public_data.sql",
                "20260927_170000_whatsapp_privilege_actions.sql",
                "20990101_000000_future_schema.sql",
            ]
        )
        self.assertEqual(status, 1)
        self.assertIn("database migration absent from candidate: 20990101", error)

    def test_exact_ledger_passes(self) -> None:
        status, error = self.check_ledger(
            [
                "20260927_120000_church_cell_public_data.sql",
                "20260927_170000_whatsapp_privilege_actions.sql",
            ]
        )
        self.assertEqual(status, 0, error)


# The existing CI entrypoint also executes packaging and transport policy tests.
from test_backend_workflow import WorkflowTest


if __name__ == "__main__":
    unittest.main()
