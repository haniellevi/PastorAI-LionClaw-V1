from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import production_monitor as monitor  # noqa: E402

UTC = dt.timezone.utc


def _archive(root: Path, now: dt.datetime) -> Path:
    archive = root / "pastorai-backup-20260809T120000Z.tar.gz"
    archive.write_bytes(b"backup")
    Path(str(archive) + ".sha256").write_text("a" * 64 + "  archive\n")
    stamp = now.timestamp()
    os.utime(archive, (stamp, stamp))
    return archive


def test_recent_backup_with_checksum_is_healthy(tmp_path) -> None:
    now = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)
    _archive(tmp_path, now - dt.timedelta(hours=2))

    result = monitor.check_backup(
        {"MONITOR_BACKUP_ROOT": str(tmp_path)},
        now=now,
    )

    assert result.ok is True
    assert result.name == "backup"


def test_stale_backup_fails_without_exposing_paths(tmp_path) -> None:
    now = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)
    _archive(tmp_path, now - dt.timedelta(hours=31))

    result = monitor.check_backup(
        {"MONITOR_BACKUP_ROOT": str(tmp_path)},
        now=now,
    )

    assert result.ok is False
    assert result.detail.startswith("atrasado age_hours=")
    assert str(tmp_path) not in result.detail


def test_notification_deduplicates_and_sends_recovery() -> None:
    now = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)
    failing = "backup"
    previous = {"signature": failing, "notified_at": now.isoformat()}

    assert monitor.should_notify(previous, failing, now=now, reminder_hours=6) is False
    assert monitor.should_notify(previous, "", now=now, reminder_hours=6) is True
    assert (
        monitor.should_notify(
            previous,
            failing,
            now=now + dt.timedelta(hours=7),
            reminder_hours=6,
        )
        is True
    )


def test_failure_signature_ignores_moving_backup_age() -> None:
    first = [monitor.CheckResult("backup", False, "atrasado age_hours=31.0")]
    later = [monitor.CheckResult("backup", False, "atrasado age_hours=31.1")]

    assert monitor.failure_signature(first) == monitor.failure_signature(later)


def test_failed_recovery_notification_is_retried(monkeypatch, tmp_path) -> None:
    state = tmp_path / "state.json"
    state.write_text(
        '{"signature":"backup","notified_at":"2026-08-09T10:00:00+00:00"}'
    )
    monkeypatch.setattr(
        monitor,
        "check_liveness",
        lambda _config: monitor.CheckResult("liveness", True, "status=ok"),
    )
    monkeypatch.setattr(
        monitor,
        "check_readiness",
        lambda _config: monitor.CheckResult("readiness", True, "status=ready"),
    )
    monkeypatch.setattr(
        monitor,
        "check_backup",
        lambda _config, now=None: monitor.CheckResult("backup", True, "recente"),
    )
    monkeypatch.setattr(monitor, "send_brevo_alert", lambda *_args, **_kwargs: False)

    result = monitor.run(
        {"MONITOR_STATE_FILE": str(state)},
        now=dt.datetime(2026, 8, 9, 12, tzinfo=UTC),
    )

    assert result == 0
    assert monitor.load_state(state)["signature"] == "backup"


def test_readiness_degraded_is_an_alert_not_a_restart_signal(monkeypatch) -> None:
    monkeypatch.setattr(
        monitor,
        "request_json",
        lambda *_args, **_kwargs: {
            "status": "degraded",
            "required": {"database": "ok", "redis": "ok"},
        },
    )

    result = monitor.check_readiness({})

    assert result.ok is False
    assert result.detail == "status=degraded"
