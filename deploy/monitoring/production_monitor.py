#!/usr/bin/env python3
"""Small, credential-safe monitor for the PastorAI VPS.

It checks local liveness/readiness and backup freshness.  Failures are logged as
bounded key/value records and sent through the Brevo account already configured
for the application.  Notifications are deduplicated by persisted state.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

UTC = dt.timezone.utc
DEFAULT_ENV_FILE = Path("/opt/pastorai-current/deploy/.env")
DEFAULT_STATE_FILE = Path("/var/lib/pastorai-monitor/state.json")
DEFAULT_BACKUP_ROOT = Path("/root/pastorai-backups")


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


class AlertDelivery(str, Enum):
    SENT = "sent"
    DEFINITE_FAILURE = "failed"
    AMBIGUOUS = "ambiguous"


def utcnow() -> dt.datetime:
    return dt.datetime.now(UTC)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_config() -> dict[str, str]:
    env_file = Path(os.environ.get("PASTORAI_ENV_FILE", DEFAULT_ENV_FILE))
    config = parse_env_file(env_file)
    config.update(os.environ)
    return config


def request_json(url: str, *, timeout: float = 8.0) -> Any:
    request = urllib.request.Request(
        url,
        headers={"accept": "application/json", "user-agent": "PastorAI-Monitor/1"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError("unexpected HTTP status")
        return json.loads(response.read(131072).decode("utf-8"))


def check_liveness(config: dict[str, str]) -> CheckResult:
    base = config.get("MONITOR_LOCAL_API_BASE", "http://127.0.0.1:8000").rstrip("/")
    try:
        body = request_json(base + "/health")
    except Exception as exc:  # noqa: BLE001 - dependency failure is a result
        return CheckResult("liveness", False, f"indisponivel ({type(exc).__name__})")
    ok = isinstance(body, dict) and body.get("status") == "ok"
    return CheckResult("liveness", ok, "status=ok" if ok else "resposta inesperada")


def check_readiness(config: dict[str, str]) -> CheckResult:
    base = config.get("MONITOR_LOCAL_API_BASE", "http://127.0.0.1:8000").rstrip("/")
    try:
        body = request_json(base + "/ready")
    except Exception as exc:  # noqa: BLE001
        return CheckResult("readiness", False, f"indisponivel ({type(exc).__name__})")
    if not isinstance(body, dict):
        return CheckResult("readiness", False, "resposta inesperada")
    status = str(body.get("status", "unknown"))
    required = body.get("required") if isinstance(body.get("required"), dict) else {}
    failed_required = sorted(key for key, value in required.items() if value != "ok")
    if status == "ready" and not failed_required:
        return CheckResult("readiness", True, "status=ready")
    detail = f"status={status}"
    if failed_required:
        detail += " required=" + ",".join(failed_required)
    return CheckResult("readiness", False, detail)


def check_backup(
    config: dict[str, str], *, now: dt.datetime | None = None
) -> CheckResult:
    root = Path(config.get("MONITOR_BACKUP_ROOT", DEFAULT_BACKUP_ROOT))
    try:
        max_age = max(1, int(config.get("MONITOR_BACKUP_MAX_AGE_HOURS", "30")))
    except ValueError:
        max_age = 30
    try:
        archives = sorted(
            root.glob("pastorai-backup-*.tar.gz"),
            key=lambda item: item.stat().st_mtime,
        )
    except OSError as exc:
        return CheckResult("backup", False, f"indisponivel ({type(exc).__name__})")
    if not archives:
        return CheckResult("backup", False, "nenhum arquivo encontrado")
    latest = archives[-1]
    checksum = Path(str(latest) + ".sha256")
    try:
        if not checksum.is_file() or checksum.stat().st_size < 64:
            return CheckResult("backup", False, "checksum lateral ausente")
        modified = dt.datetime.fromtimestamp(latest.stat().st_mtime, tz=UTC)
    except OSError as exc:
        return CheckResult("backup", False, f"indisponivel ({type(exc).__name__})")
    checked_at = now or utcnow()
    age_hours = max(0.0, (checked_at - modified).total_seconds() / 3600)
    if age_hours > max_age:
        return CheckResult("backup", False, f"atrasado age_hours={age_hours:.1f}")
    return CheckResult("backup", True, f"recente age_hours={age_hours:.1f}")


def load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def failure_signature(checks: list[CheckResult]) -> str:
    # Details can contain a moving age counter. The failed check set is stable
    # enough to deduplicate alerts without hiding the current detail in e-mail.
    return "|".join(sorted(item.name for item in checks if not item.ok))


def should_notify(
    previous: dict[str, Any],
    signature: str,
    *,
    now: dt.datetime,
    reminder_hours: int,
    retry_hours: int = 1,
    ambiguous_retry_hours: int = 6,
) -> bool:
    old_signature = str(previous.get("signature", ""))
    if signature != old_signature:
        return True

    delivery_status = str(previous.get("delivery_status", ""))
    if not delivery_status and previous.get("notified_at"):
        delivery_status = AlertDelivery.SENT.value
    if not signature and delivery_status in {"", AlertDelivery.SENT.value}:
        return False
    if delivery_status == AlertDelivery.SENT.value:
        timestamp_key = (
            "delivered_at" if previous.get("delivered_at") else "notified_at"
        )
        wait_hours = reminder_hours
    elif delivery_status in {AlertDelivery.AMBIGUOUS.value, "attempting"}:
        timestamp_key = "attempted_at"
        wait_hours = ambiguous_retry_hours
    else:
        timestamp_key = "attempted_at"
        wait_hours = retry_hours
    try:
        last_attempt = dt.datetime.fromisoformat(str(previous[timestamp_key]))
    except (KeyError, TypeError, ValueError):
        return True
    return now - last_attempt >= dt.timedelta(hours=max(1, wait_hours))


def send_brevo_alert(
    config: dict[str, str], *, subject: str, checks: list[CheckResult]
) -> AlertDelivery:
    api_key = config.get("BREVO_API_KEY", "")
    recipient = config.get("MONITOR_ALERT_EMAIL", "")
    sender = config.get("BREVO_FROM_EMAIL", "")
    if not api_key or not recipient or not sender:
        print("monitor_alert delivery=skipped reason=configuration_missing")
        return AlertDelivery.DEFINITE_FAILURE
    rows = "".join(
        "<li><strong>"
        f"{html.escape(item.name)}</strong>: {html.escape(item.detail)}</li>"
        for item in checks
    )
    payload = json.dumps(
        {
            "sender": {
                "email": sender,
                "name": config.get("BREVO_FROM_NAME", "Igreja 12"),
            },
            "to": [{"email": recipient}],
            "subject": subject,
            "htmlContent": f"<h2>{html.escape(subject)}</h2><ul>{rows}</ul>",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        config.get("BREVO_API_URL", "https://api.brevo.com/v3").rstrip("/")
        + "/smtp/email",
        data=payload,
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            ok = 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        print(f"monitor_alert delivery=failed error_type={type(exc).__name__}")
        return AlertDelivery.DEFINITE_FAILURE
    except Exception as exc:  # noqa: BLE001 - never print provider response/key
        print(f"monitor_alert delivery=ambiguous error_type={type(exc).__name__}")
        return AlertDelivery.AMBIGUOUS
    delivery = AlertDelivery.SENT if ok else AlertDelivery.DEFINITE_FAILURE
    print(f"monitor_alert delivery={delivery.value}")
    return delivery


def run(config: dict[str, str], *, now: dt.datetime | None = None) -> int:
    checked_at = now or utcnow()
    checks = [
        check_liveness(config),
        check_readiness(config),
        check_backup(config, now=checked_at),
    ]
    for item in checks:
        print(
            f"monitor_check name={item.name} ok={str(item.ok).lower()} "
            f"detail={json.dumps(item.detail, ensure_ascii=True)}"
        )

    state_path = Path(config.get("MONITOR_STATE_FILE", DEFAULT_STATE_FILE))
    previous = load_state(state_path)
    signature = failure_signature(checks)
    try:
        reminder = int(config.get("MONITOR_REMINDER_HOURS", "6"))
    except ValueError:
        reminder = 6
    try:
        retry_hours = int(config.get("MONITOR_RETRY_HOURS", "1"))
    except ValueError:
        retry_hours = 1
    try:
        ambiguous_retry_hours = int(
            config.get("MONITOR_AMBIGUOUS_RETRY_HOURS", "6")
        )
    except ValueError:
        ambiguous_retry_hours = 6
    notify = should_notify(
        previous,
        signature,
        now=checked_at,
        reminder_hours=reminder,
        retry_hours=retry_hours,
        ambiguous_retry_hours=ambiguous_retry_hours,
    )
    state = {
        "checked_at": checked_at.isoformat(),
        "attempted_at": previous.get("attempted_at"),
        "delivered_at": previous.get("delivered_at"),
        "notified_at": previous.get("notified_at"),
        "delivery_status": previous.get("delivery_status"),
        "signature": signature,
        "checks": [asdict(item) for item in checks],
    }
    if notify:
        subject = (
            "[PastorAI] Falha na producao"
            if signature
            else "[PastorAI] Producao recuperada"
        )
        state["attempted_at"] = checked_at.isoformat()
        state["delivery_status"] = "attempting"
        # Persist the transition before network I/O. A crash or ambiguous
        # response is therefore cooled down instead of retried every five minutes.
        save_state(state_path, state)
        try:
            delivery = send_brevo_alert(config, subject=subject, checks=checks)
        except Exception as exc:  # noqa: BLE001 - custom sender must remain safe
            print(
                "monitor_alert delivery=ambiguous "
                f"error_type={type(exc).__name__}"
            )
            delivery = AlertDelivery.AMBIGUOUS
        state["delivery_status"] = delivery.value
        if delivery is AlertDelivery.SENT:
            state["delivered_at"] = checked_at.isoformat()
            state["notified_at"] = checked_at.isoformat()
    save_state(state_path, state)
    return 1 if signature else 0


def main() -> int:
    return run(load_config())


if __name__ == "__main__":
    raise SystemExit(main())
