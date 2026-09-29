"""Local command doubles verify deploy stops and code-only rollback order."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


DEPLOY = Path(__file__).resolve().parents[1]
SHA_OLD = "a" * 40
SHA_NEW = "b" * 40
SERVICES = "backend queue-worker cron-worker broadcast-worker"


class BackendReleaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="backend-release-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / "releases" / SHA_OLD / "deploy"
        self.new = self.root / "releases" / SHA_NEW / "deploy"
        self.old.mkdir(parents=True)
        self.new.mkdir(parents=True)
        (self.old / ".env").write_text("SYNTHETIC=1\n")
        (self.new / "check_backend_schema.py").write_bytes(
            (DEPLOY / "check_backend_schema.py").read_bytes()
        )
        (self.root / "current").symlink_to(self.old.parent)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "docker").write_text(
            """#!/bin/sh
printf 'docker|%s|%s\\n' "$PWD" "$*" >> "$TRACE"
case "$*" in
  'compose exec -T backend python -') exit "${PREFLIGHT_EXIT:-0}" ;;
  'compose build backend')
    if [ "$PWD" = "$NEW_DEPLOY" ]; then exit "${BUILD_EXIT:-0}"; fi
    exit "${ROLLBACK_BUILD_EXIT:-0}" ;;
  'compose up '*)
    if [ "$PWD" = "$NEW_DEPLOY" ]; then exit "${RESTART_EXIT:-0}"; fi
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
        for name in ("docker", "curl"):
            (bin_dir / name).chmod(0o755)
        self.trace = self.root / "trace"
        self.environment = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "TRACE": str(self.trace),
            "NEW_DEPLOY": str(self.new),
            "BACKEND_RELEASE_TEST_MODE": "1",
            "BACKEND_RELEASE_TEST_ROOT": str(self.root),
        }

    def run_release(self, **changes: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(DEPLOY / "backend-release.sh"), SHA_NEW],
            env={**self.environment, **changes},
            capture_output=True,
            text=True,
            check=False,
        )

    def calls(self) -> list[str]:
        return self.trace.read_text().splitlines() if self.trace.exists() else []

    def test_schema_failure_stops_before_build_or_restart(self) -> None:
        result = self.run_release(PREFLIGHT_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("before restart", result.stderr)
        self.assertEqual(len(self.calls()), 2)  # config, then schema preflight
        self.assertIn("compose exec -T backend python -", self.calls()[-1])
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_build_failure_keeps_previous_containers(self) -> None:
        result = self.run_release(BUILD_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any("compose build backend" in call for call in self.calls()))
        self.assertFalse(any("compose up " in call for call in self.calls()))
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_health_failure_restarts_previous_code(self) -> None:
        result = self.run_release(HEALTH_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        calls = self.calls()
        self.assertTrue(any(f"docker|{self.new}|compose up " in call for call in calls))
        self.assertTrue(any(f"docker|{self.old}|compose build backend" in call for call in calls))
        self.assertTrue(
            any(f"docker|{self.old}|compose up " in call and SERVICES in call for call in calls)
        )
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_failed_candidate_restart_rolls_back(self) -> None:
        result = self.run_release(RESTART_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(
            any(
                f"docker|{self.old}|compose up " in call and SERVICES in call
                for call in self.calls()
            )
        )
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_rollback_failure_reports_incomplete_recovery(self) -> None:
        result = self.run_release(HEALTH_EXIT="1", ROLLBACK_BUILD_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rollback of code is unhealthy", result.stderr)
        self.assertEqual((self.root / "current").resolve(), self.old.parent)

    def test_healthy_candidate_becomes_current(self) -> None:
        result = self.run_release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "current").resolve(), self.new.parent)
        up_calls = [call for call in self.calls() if "compose up " in call]
        self.assertEqual(len(up_calls), 1)
        self.assertIn(SERVICES, up_calls[0])


if __name__ == "__main__":
    unittest.main()
