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
if [ "$1" = compose ] && [ "$2" = -f ]; then
  python3 - "$5" <<'OVERRIDE'
import json, os, sys
from pathlib import Path
service = json.loads(Path(sys.argv[1]).read_text())["services"]["backend"]
assert service["entrypoint"] == ["python", "/tmp/backend-rollback-schema.py"]
assert service["command"] == []
assert service["restart"] == "no"
assert service["healthcheck"] == {"disable": True}
with open(os.environ["TRACE"], "a") as out:
    out.write("checker-override|" + sys.argv[1] + "\\n")
    out.write("checker-manifest|" + service["environment"]["EXPECTED_MIGRATIONS"] + "\\n")
OVERRIDE
  [ $? = 0 ] || exit 1
  shift 5
  set -- compose "$@"
fi
case "$*" in
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
  *' sh -c '*)
    printf 'gates|%s|%s\\n' "$PWD" "$4" >> "$TRACE"
    if [ "$PWD" = "$NEW_DEPLOY" ] && [ "${CANDIDATE_GATES_EXIT:-0}" = 1 ]; then exit 1; fi
    sh -lc "$7"; exit $? ;;
esac
printf 'docker|%s|%s\\n' "$PWD" "$*" >> "$TRACE"
case "$*" in
  'compose exec -T -e EXPECTED_MIGRATIONS='*' backend python -') exit "${PREFLIGHT_EXIT:-0}" ;;
  'compose build backend')
    if [ "$PWD" = "$NEW_DEPLOY" ]; then exit "${BUILD_EXIT:-0}"; fi
    exit "${ROLLBACK_BUILD_EXIT:-0}" ;;
  'compose run '*) exit "${ROLLBACK_PREFLIGHT_EXIT:-0}" ;;
  'compose up --no-start '*)
    if [ "$PWD" != "$NEW_DEPLOY" ]; then exit "${ROLLBACK_CREATE_EXIT:-0}"; fi ;;
  'compose stop '*)
    if [ "$PWD" != "$NEW_DEPLOY" ] && [ "${ROLLBACK_STOP_EXIT:-0}" = 1 ]; then exit 1; fi
    exit "${STOP_EXIT:-0}" ;;
  'compose start '*)
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
printf 'curl|%s|%s\\n' "$PWD" "$*" >> "$TRACE"
if [ "$PWD" = "$NEW_DEPLOY" ]; then exit "${HEALTH_EXIT:-0}"; fi
exit "${ROLLBACK_HEALTH_EXIT:-0}"
"""
        )
        (bin_dir / "timeout").write_text(
            """#!/bin/sh
printf 'timeout|%s|%s\\n' "$PWD" "$*" >> "$TRACE"
[ "$1" = --signal=TERM ] && [ "$2" = --kill-after=5s ] && [ "$3" = 180s ] || exit 2
[ "${CHECKER_TIMEOUT_EXIT:-0}" = 0 ] || exit "$CHECKER_TIMEOUT_EXIT"
shift 3
exec "$@"
"""
        )
        for name in ("docker", "curl", "timeout"):
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

    def run_release(self, **changes: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["bash", str(DEPLOY / "backend-release.sh"), SHA_NEW],
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

    def test_missing_previous_manifest_blocks_checker_and_application(self):
        (self.old.parent / "backend/scripts/migrate.py").unlink()
        result = self.run_release(HEALTH_EXIT="17")
        self.assertEqual(result.returncode, 17)
        self.assertFalse(any("checker-start|" in c for c in self.calls()))
        self.assertFalse(any(f"docker|{self.old}|compose start --wait " in c for c in self.calls()))

    def test_failed_candidate_does_not_retain_private_configuration(self):
        result = self.run_release(BUILD_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.new / "configuration.fixture").exists())
        self.assertTrue((self.old / "configuration.fixture").exists())

    def test_rollback_missing_checker_never_starts_previous_code(self):
        (self.old / "check_backend_schema.py").unlink()
        result = self.run_release(HEALTH_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(f"docker|{self.old}|compose start --wait " in c for c in self.calls()))
        self.assertIn("rollback schema compatibility", result.stderr)

    def test_candidate_gates_verified_before_start(self):
        result = self.run_release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any("compose up " in c and "--no-start" not in c for c in self.calls()))
        calls = self.calls()
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
        self.assertTrue(any("compose build backend" in call for call in self.calls()))
        self.assertFalse(any("compose start --wait " in call for call in self.calls()))
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_health_failure_restarts_previous_code(self) -> None:
        result = self.run_release(HEALTH_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        calls = self.calls()
        self.assertTrue(any(f"docker|{self.new}|compose start --wait " in call for call in calls))
        self.assertTrue(any(f"docker|{self.old}|compose build backend" in call for call in calls))
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
