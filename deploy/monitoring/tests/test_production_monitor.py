from __future__ import annotations

import datetime as dt
import json
import os
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import production_monitor as monitor  # noqa: E402

UTC = dt.timezone.utc


def _manifest(
    directory: Path,
    now: dt.datetime,
    *,
    stamp: str = "20260809T120000Z",
    **overrides,
) -> Path:
    payload = {
        "version": 1,
        "status": "verified",
        "archive": f"pastorai-backup-{stamp}.tar.gz",
        "sha256": "a" * 64,
        "bytes": 123,
        "completed_at": now.isoformat().replace("+00:00", "Z"),
    }
    payload.update(overrides)
    path = directory / "backup-status.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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


def test_recent_verified_backup_manifest_is_healthy(tmp_path) -> None:
    now = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)
    manifest = _manifest(tmp_path, now - dt.timedelta(hours=2))

    result = monitor.check_backup(
        {"MONITOR_BACKUP_MANIFEST": str(manifest)},
        now=now,
    )

    assert result.ok is True
    assert result.name == "backup"


def test_backup_manifest_uses_verified_completion_time_not_file_mtime(tmp_path) -> None:
    now = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)
    manifest = _manifest(tmp_path, now - dt.timedelta(hours=1))
    os.utime(manifest, (now.timestamp() - 40 * 3600, now.timestamp() - 40 * 3600))

    result = monitor.check_backup(
        {"MONITOR_BACKUP_MANIFEST": str(manifest)},
        now=now,
    )

    assert result.ok is True
    assert result.detail == "recente age_hours=1.0"


def test_stale_backup_fails_without_exposing_paths(tmp_path) -> None:
    now = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)
    manifest = _manifest(tmp_path, now - dt.timedelta(hours=31))

    result = monitor.check_backup(
        {"MONITOR_BACKUP_MANIFEST": str(manifest)},
        now=now,
    )

    assert result.ok is False
    assert result.detail.startswith("atrasado age_hours=")
    assert str(tmp_path) not in result.detail


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "created"},
        {"archive": "other.tar.gz"},
        {"sha256": "not-a-sha256"},
        {"bytes": 0},
        {"completed_at": "not-a-timestamp"},
    ],
)
def test_backup_manifest_fails_closed(tmp_path, overrides: dict[str, object]) -> None:
    now = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)
    manifest = _manifest(tmp_path, now - dt.timedelta(hours=1), **overrides)

    result = monitor.check_backup({"MONITOR_BACKUP_MANIFEST": str(manifest)}, now=now)

    assert result.ok is False
    assert result.detail in {"manifesto invalido", "manifesto nao verificado"}


def test_backup_missing_or_unreadable_manifest_is_unhealthy(tmp_path, monkeypatch) -> None:
    now = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)
    manifest = tmp_path / "backup-status.json"
    assert monitor.check_backup(
        {"MONITOR_BACKUP_MANIFEST": str(manifest)}, now=now
    ).detail == "indisponivel (FileNotFoundError)"

    _manifest(tmp_path, now - dt.timedelta(hours=1))
    original_read_text = Path.read_text

    def fail_manifest_read(path: Path, *args, **kwargs):
        if path == manifest:
            raise PermissionError("sensitive manifest path")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_manifest_read)
    result = monitor.check_backup({"MONITOR_BACKUP_MANIFEST": str(manifest)}, now=now)

    assert result.ok is False
    assert result.detail == "indisponivel (PermissionError)"
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
    assert result == 0
    assert persisted["delivery_status"] == monitor.AlertDelivery.SENT.value
    assert persisted["delivered_at"] == now.isoformat()


@pytest.mark.parametrize("failed", [{"backup"}, {"readiness"}])
def test_operational_degradation_returns_zero_and_keeps_alert_state(
    monkeypatch, tmp_path, failed: set[str]
) -> None:
    """Missing backup/readiness failure is an alert, not a failed unit install."""

    _install_checks(monkeypatch, failed=failed)
    monkeypatch.setattr(
        monitor,
        "send_brevo_alert",
        lambda *_args, **_kwargs: monitor.AlertDelivery.SENT,
    )

    result = monitor.run(
        {"MONITOR_STATE_FILE": str(tmp_path / "state.json")},
        now=dt.datetime(2026, 8, 9, 12, tzinfo=UTC),
    )

    assert result == 0


def test_missing_backup_manifest_is_operational_not_installer_failure(
    monkeypatch, tmp_path
) -> None:
    """The first monitor tick must stay alive to report a missing M02 artifact."""

    state = tmp_path / "state.json"
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
    calls: list[str] = []
    monkeypatch.setattr(
        monitor,
        "send_brevo_alert",
        lambda *_args, **_kwargs: calls.append("alert") or monitor.AlertDelivery.SENT,
    )

    result = monitor.run(
        {
            "MONITOR_STATE_FILE": str(state),
            "MONITOR_BACKUP_MANIFEST": str(tmp_path / "missing.json"),
        },
        now=dt.datetime(2026, 8, 9, 12, tzinfo=UTC),
    )

    assert result == 0
    assert calls == ["alert"]
    assert monitor.load_state(state)["signature"] == "backup"


def test_brevo_failure_is_operational_degradation_not_process_failure(
    monkeypatch, tmp_path
) -> None:
    _install_checks(monkeypatch, failed={"backup"})
    monkeypatch.setattr(
        monitor,
        "send_brevo_alert",
        lambda *_args, **_kwargs: monitor.AlertDelivery.DEFINITE_FAILURE,
    )

    state = tmp_path / "state.json"
    result = monitor.run(
        {"MONITOR_STATE_FILE": str(state)},
        now=dt.datetime(2026, 8, 9, 12, tzinfo=UTC),
    )

    assert result == 0
    assert monitor.load_state(state)["delivery_status"] == "failed"


def test_concurrent_monitor_runs_send_one_alert(monkeypatch, tmp_path) -> None:
    state = tmp_path / "state.json"
    start = dt.datetime(2026, 8, 9, 12, tzinfo=UTC)
    checks_ready = threading.Barrier(2)
    send_entered = threading.Event()
    release_send = threading.Event()
    calls: list[str] = []
    calls_lock = threading.Lock()

    monkeypatch.setattr(
        monitor,
        "check_liveness",
        lambda _config: monitor.CheckResult("liveness", True, "status"),
    )
    monkeypatch.setattr(
        monitor,
        "check_readiness",
        lambda _config: monitor.CheckResult("readiness", False, "status"),
    )

    def synchronized_backup(_config, now=None):
        checks_ready.wait(timeout=2)
        return monitor.CheckResult("backup", True, "status")

    def send(*_args, **_kwargs):
        with calls_lock:
            calls.append("send")
        send_entered.set()
        assert release_send.wait(timeout=2)
        return monitor.AlertDelivery.SENT

    monkeypatch.setattr(monitor, "check_backup", synchronized_backup)
    monkeypatch.setattr(monitor, "send_brevo_alert", send)
    results: list[int] = []

    def execute() -> None:
        results.append(
            monitor.run({"MONITOR_STATE_FILE": str(state)}, now=start)
        )

    first = threading.Thread(target=execute)
    second = threading.Thread(target=execute)
    first.start()
    second.start()
    assert send_entered.wait(timeout=2)
    release_send.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert sorted(results) == [0, 0]
    assert calls == ["send"]
    assert monitor.load_state(state)["delivery_status"] == "sent"
    if os.name != "nt":
        assert (
            state.parent / (state.name + ".lock")
        ).stat().st_mode & 0o777 == 0o600


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
