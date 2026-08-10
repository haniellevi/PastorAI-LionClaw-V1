from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import production_monitor as monitor  # noqa: E402

UTC = dt.timezone.utc


def _archive(
    root: Path,
    now: dt.datetime,
    *,
    stamp: str = "20260809T120000Z",
) -> Path:
    archive = root / f"pastorai-backup-{stamp}.tar.gz"
    archive.write_bytes(b"backup")
    Path(str(archive) + ".sha256").write_text("a" * 64 + "  archive\n")
    stamp = now.timestamp()
    os.utime(archive, (stamp, stamp))
    return archive


def _install_checks(monkeypatch, *, failed: set[str] | None = None) -> None:
    failed = failed or set()
    monkeypatch.setattr(
        monitor,
        "check_liveness",
        lambda _config: monitor.CheckResult(
            "liveness", "liveness" not in failed, "status"
        ),
    )
    monkeypatch.setattr(
        monitor,
        "check_readiness",
        lambda _config: monitor.CheckResult(
            "readiness", "readiness" not in failed, "status"
        ),
    )
    monkeypatch.setattr(
        monitor,
        "check_backup",
        lambda _config, now=None: monitor.CheckResult(
            "backup", "backup" not in failed, "status"
        ),
    )


def test_recent_backup_with_checksum_is_healthy(tmp_path) -> None:
    now = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)
    _archive(tmp_path, now - dt.timedelta(hours=2))

    result = monitor.check_backup(
        {"MONITOR_BACKUP_ROOT": str(tmp_path)},
        now=now,
    )

    assert result.ok is True
    assert result.name == "backup"


def test_backup_check_selects_the_most_recent_package(tmp_path) -> None:
    now = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)
    _archive(
        tmp_path,
        now - dt.timedelta(hours=40),
        stamp="20260807T200000Z",
    )
    _archive(
        tmp_path,
        now - dt.timedelta(hours=1),
        stamp="20260809T110000Z",
    )

    result = monitor.check_backup(
        {"MONITOR_BACKUP_ROOT": str(tmp_path)},
        now=now,
    )

    assert result.ok is True
    assert result.detail == "recente age_hours=1.0"


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
    previous = {
        "signature": failing,
        "notified_at": now.isoformat(),
        "delivered_at": now.isoformat(),
        "delivery_status": monitor.AlertDelivery.SENT.value,
    }

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


def test_attempt_is_persisted_before_send_and_success_is_recorded(
    monkeypatch, tmp_path
) -> None:
    state = tmp_path / "state.json"
    _install_checks(monkeypatch, failed={"backup"})

    def send(*_args, **_kwargs):
        during_send = monitor.load_state(state)
        assert during_send["signature"] == "backup"
        assert during_send["delivery_status"] == "attempting"
        assert during_send["attempted_at"] is not None
        return monitor.AlertDelivery.SENT

    monkeypatch.setattr(monitor, "send_brevo_alert", send)
    now = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)

    result = monitor.run(
        {"MONITOR_STATE_FILE": str(state)},
        now=now,
    )

    persisted = monitor.load_state(state)
    assert result == 1
    assert persisted["delivery_status"] == monitor.AlertDelivery.SENT.value
    assert persisted["delivered_at"] == now.isoformat()


def test_definite_failure_uses_retry_cooldown(monkeypatch, tmp_path) -> None:
    state = tmp_path / "state.json"
    _install_checks(monkeypatch, failed={"backup"})
    calls: list[str] = []
    monkeypatch.setattr(
        monitor,
        "send_brevo_alert",
        lambda *_args, **_kwargs: calls.append("send")
        or monitor.AlertDelivery.DEFINITE_FAILURE,
    )
    start = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)
    config = {"MONITOR_STATE_FILE": str(state), "MONITOR_RETRY_HOURS": "1"}

    monitor.run(config, now=start)
    monitor.run(config, now=start + dt.timedelta(minutes=5))
    assert calls == ["send"]
    assert monitor.load_state(state)["delivery_status"] == "failed"

    monitor.run(config, now=start + dt.timedelta(hours=1, minutes=1))
    assert calls == ["send", "send"]


def test_ambiguous_timeout_does_not_repeat_each_timer(monkeypatch, tmp_path) -> None:
    state = tmp_path / "state.json"
    _install_checks(monkeypatch, failed={"readiness"})
    calls: list[str] = []
    monkeypatch.setattr(
        monitor,
        "send_brevo_alert",
        lambda *_args, **_kwargs: calls.append("send")
        or monitor.AlertDelivery.AMBIGUOUS,
    )
    start = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)
    config = {
        "MONITOR_STATE_FILE": str(state),
        "MONITOR_AMBIGUOUS_RETRY_HOURS": "6",
    }

    monitor.run(config, now=start)
    monitor.run(config, now=start + dt.timedelta(minutes=5))
    assert calls == ["send"]
    assert monitor.load_state(state)["delivery_status"] == "ambiguous"

    monitor.run(config, now=start + dt.timedelta(hours=6, minutes=1))
    assert calls == ["send", "send"]


def test_recovery_and_new_failure_are_immediate_transitions(
    monkeypatch, tmp_path
) -> None:
    state = tmp_path / "state.json"
    calls: list[str] = []
    monkeypatch.setattr(
        monitor,
        "send_brevo_alert",
        lambda _config, *, subject, checks: calls.append(subject)
        or monitor.AlertDelivery.SENT,
    )
    start = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)
    config = {"MONITOR_STATE_FILE": str(state)}

    _install_checks(monkeypatch, failed={"backup"})
    monitor.run(config, now=start)
    _install_checks(monkeypatch)
    monitor.run(config, now=start + dt.timedelta(minutes=5))
    _install_checks(monkeypatch, failed={"backup"})
    monitor.run(config, now=start + dt.timedelta(minutes=10))

    assert calls == [
        "[PastorAI] Falha na producao",
        "[PastorAI] Producao recuperada",
        "[PastorAI] Falha na producao",
    ]


def test_failed_recovery_uses_cooldown_then_retries(monkeypatch, tmp_path) -> None:
    state = tmp_path / "state.json"
    start = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)
    state.write_text(
        '{"signature":"backup","delivery_status":"sent",'
        f'"delivered_at":"{start.isoformat()}"}}',
        encoding="utf-8",
    )
    _install_checks(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        monitor,
        "send_brevo_alert",
        lambda *_args, **_kwargs: calls.append("recovery")
        or monitor.AlertDelivery.DEFINITE_FAILURE,
    )
    config = {"MONITOR_STATE_FILE": str(state), "MONITOR_RETRY_HOURS": "1"}

    monitor.run(config, now=start + dt.timedelta(minutes=1))
    monitor.run(config, now=start + dt.timedelta(minutes=6))
    assert calls == ["recovery"]

    monitor.run(config, now=start + dt.timedelta(hours=1, minutes=2))
    assert calls == ["recovery", "recovery"]


def test_brevo_http_rejection_is_definite_and_timeout_is_ambiguous(
    monkeypatch,
) -> None:
    config = {
        "BREVO_API_KEY": "synthetic-key",
        "MONITOR_ALERT_EMAIL": "alerts@example.invalid",
        "BREVO_FROM_EMAIL": "sender@example.invalid",
    }
    checks = [monitor.CheckResult("backup", False, "atrasado")]

    def reject(*_args, **_kwargs):
        raise monitor.urllib.error.HTTPError(
            "https://example.invalid", 400, "rejected", {}, None
        )

    monkeypatch.setattr(monitor.urllib.request, "urlopen", reject)
    assert (
        monitor.send_brevo_alert(config, subject="failure", checks=checks)
        is monitor.AlertDelivery.DEFINITE_FAILURE
    )

    def timeout(*_args, **_kwargs):
        raise TimeoutError("ambiguous")

    monkeypatch.setattr(monitor.urllib.request, "urlopen", timeout)
    assert (
        monitor.send_brevo_alert(config, subject="failure", checks=checks)
        is monitor.AlertDelivery.AMBIGUOUS
    )


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
