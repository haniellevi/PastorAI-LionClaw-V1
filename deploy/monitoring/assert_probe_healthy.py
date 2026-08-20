#!/usr/bin/env python3
"""Fail the Actions job after incident maintenance when the probe is unhealthy."""

from __future__ import annotations

import json
import os
from pathlib import Path

REPORT_PATH = Path("production-monitor-report.json")


def is_healthy(*, probe_outcome: str | None, report_path: Path = REPORT_PATH) -> bool:
    """Require both a successful probe step and an explicitly healthy report."""
    if probe_outcome != "success":
        return False
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(report, dict) or report.get("ok") is not True:
        return False
    checks = report.get("checks")
    return isinstance(checks, list) and bool(checks) and all(
        isinstance(check, dict) and check.get("ok") is True for check in checks
    )


def main() -> int:
    if is_healthy(probe_outcome=os.environ.get("PROBE_OUTCOME")):
        return 0
    print("Produção não está saudável; issue atualizada e workflow marcado como falho.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
