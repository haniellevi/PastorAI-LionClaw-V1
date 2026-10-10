"""Local command doubles verify deploy stops and code-only rollback order."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch


DEPLOY = Path(__file__).resolve().parents[1]
SHA_OLD = "a" * 40
SHA_NEW = "b" * 40
SERVICES = "backend queue-worker cron-worker broadcast-worker"
SCHEMA = runpy.run_path(str(DEPLOY / "check_backend_schema.py"))


class BackendReleaseTest(unittest.TestCase):
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
while [ "$1" = compose ] && [ "$2" = -f ]; do
  file="$3"
  if [ "$file" != docker-compose.yml ]; then
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
case "$*" in
  'context inspect --format '*) printf '%s\\n' 'unix:///var/run/docker.sock'; exit 0 ;;
  'image inspect --format '* )
    case "$4" in
      '{{.Id}}') printf 'sha256:%064d\\n' 2 ;;
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
    if [ "$PWD" = "$NEW_DEPLOY" ]; then exit "${BUILD_EXIT:-0}"; fi
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
    else
      [ "$*" = 'compose up --no-start --no-build --no-deps --pull never --force-recreate backend queue-worker cron-worker broadcast-worker' ] || exit 1
      printf 'normal' > "$state_file"
      printf 'created|%s|normal|backend queue-worker cron-worker broadcast-worker\\n' "$PWD" >> "$TRACE"
    fi ;;

  'compose stop '*)
    if [ "$PWD" != "$NEW_DEPLOY" ] && [ "${ROLLBACK_STOP_EXIT:-0}" = 1 ]; then exit 1; fi
    exit "${STOP_EXIT:-0}" ;;
  'compose start '*)
    if [ "$overlay" != 0 ] || [ "$(cat "$state_file")" != normal ]; then
      printf 'rejected-app-start|%s\\n' "$PWD" >> "$TRACE"
      exit 1
    fi
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
                             or "compose stop " in c or "compose start --wait " in c
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
                self.assertFalse(any("compose up " in c or "compose stop " in c
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
            {"ROLLBACK_PS_EXIT": "1"}, {"ROLLBACK_STOPPED_GATES_EXIT": "1"},
        ):
            with self.subTest(changes=changes):
                self.trace.write_text("")
                result = self.run_release(HEALTH_EXIT="1", **changes)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(any(f"docker|{self.old}|compose start --wait " in c for c in self.calls()))
                self.assertTrue(any(f"docker|{self.old}|compose stop " in c for c in self.calls()))
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
                             or "compose stop " in c or "compose start --wait " in c
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
                self.assertTrue(any(f"docker|{self.new}|compose stop " in c for c in self.calls()))
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
        self.assertTrue(any("compose stop " in c for c in self.calls()))

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
