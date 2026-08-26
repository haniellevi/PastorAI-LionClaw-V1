from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assert_probe_healthy as gate


WORKFLOW = (
    Path(__file__).resolve().parents[3] / ".github" / "workflows" / "production-monitor.yml"
)


def test_monitor_keeps_incident_maintenance_before_failing_health_job() -> None:
    content = WORKFLOW.read_text(encoding="utf-8")

    assert "runs-on: ubuntu-24.04" in content
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in content
    assert "actions/github-script@3a2844b7e9c422d3c10d287c895573f7108da1b3" in content
    assert "- name: Maintain one deduplicated incident issue" in content
    assert "- name: Fail workflow when production is unhealthy" in content
    assert "python3 deploy/monitoring/external_probe.py" in content
    assert "python3 deploy/monitoring/assert_probe_healthy.py" in content
    assert content.index("- name: Maintain one deduplicated incident issue") < content.index(
        "- name: Fail workflow when production is unhealthy"
    )
    assert content.count("if: always()") >= 2
    assert content.count('PROBE_OUTCOME: ${{ steps.probe.outcome }}') == 2


def test_gate_requires_successful_probe_and_healthy_report(tmp_path: Path) -> None:
    report = tmp_path / "production-monitor-report.json"
    report.write_text(
        '{"ok": true, "checks": [{"name": "api-readiness", "ok": true}]}\n',
        encoding="utf-8",
    )

    assert gate.is_healthy(probe_outcome="success", report_path=report) is True
    assert gate.is_healthy(probe_outcome="failure", report_path=report) is False


def test_gate_fails_closed_for_missing_invalid_or_unhealthy_reports(tmp_path: Path) -> None:
    report = tmp_path / "production-monitor-report.json"

    assert gate.is_healthy(probe_outcome="success", report_path=report) is False

    report.write_text("not-json", encoding="utf-8")
    assert gate.is_healthy(probe_outcome="success", report_path=report) is False

    report.write_text('{"ok": false}\n', encoding="utf-8")
    assert gate.is_healthy(probe_outcome="success", report_path=report) is False

    report.write_text('{"ok": true, "checks": []}\n', encoding="utf-8")
    assert gate.is_healthy(probe_outcome="success", report_path=report) is False

    report.write_text('{"ok": true, "checks": [null]}\n', encoding="utf-8")
    assert gate.is_healthy(probe_outcome="success", report_path=report) is False
