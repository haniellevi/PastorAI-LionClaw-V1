from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HELPER_PATH = ROOT / "deploy/monitoring/prepare_monitor_config.py"
SPEC = importlib.util.spec_from_file_location("prepare_monitor_config", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


def test_monitor_config_is_an_explicit_allowlist(tmp_path: Path) -> None:
    env_file = tmp_path / "deploy.env"
    output = tmp_path / "pastorai-monitor.env"
    secret = "postgresql://user:secret@example.invalid/app"
    env_file.write_text(
        "\n".join(
            (
                f"DATABASE_URL={secret}",
                "SESSION_JWT_SECRET=not-for-monitor",
                "BREVO_API_KEY=brevo-test-key",
                "BREVO_FROM_EMAIL=no-reply@example.invalid",
                "BREVO_FROM_NAME=Igreja \"12\"",
                "MONITOR_STUCK_FLOW_ENABLED=true",
                "MONITOR_STUCK_FLOW_URL=http://127.0.0.1:8000/operations/pending",
                "MONITOR_STUCK_FLOW_TOKEN=synthetic-admin-token",
                "MONITOR_STUCK_FLOW_MAX_AGE_SECONDS=1800",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    assert prepare.main(
        [
            str(env_file),
            "ops@example.invalid",
            "/var/lib/pastorai-backup/backup-status.json",
            str(output),
        ]
    ) == 0

    contents = output.read_text(encoding="utf-8")
    assert "DATABASE_URL" not in contents
    assert secret not in contents
    assert "SESSION_JWT_SECRET" not in contents
    assert 'BREVO_API_KEY="brevo-test-key"' in contents
    assert 'BREVO_FROM_NAME="Igreja \\"12\\""' in contents
    assert "MONITOR_BACKUP_MANIFEST=\"/var/lib/pastorai-backup/backup-status.json\"" in contents
    assert 'MONITOR_STUCK_FLOW_ENABLED="true"' in contents
    assert 'MONITOR_STUCK_FLOW_URL="http://127.0.0.1:8000/operations/pending"' in contents
    assert 'MONITOR_STUCK_FLOW_TOKEN="synthetic-admin-token"' in contents
    assert 'MONITOR_STUCK_FLOW_MAX_AGE_SECONDS="1800"' in contents
    if os.name != "nt":
        assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_stuck_flow_monitor_defaults_to_disabled() -> None:
    config = prepare.build_config(
        {},
        alert_email="ops@example.invalid",
        manifest_path="/var/lib/pastorai-backup/backup-status.json",
    )

    assert config["MONITOR_STUCK_FLOW_ENABLED"] == "false"
    assert config["MONITOR_STUCK_FLOW_MAX_AGE_SECONDS"] == "3600"
    assert config["MONITOR_STUCK_FLOW_URL"] == ""
    assert config["MONITOR_STUCK_FLOW_TOKEN"] == ""


def test_monitor_config_rejects_line_breaks_without_echoing_value(tmp_path: Path, capsys) -> None:
    env_file = tmp_path / "deploy.env"
    output = tmp_path / "pastorai-monitor.env"
    env_file.write_text("BREVO_API_KEY=key\n", encoding="utf-8")

    assert prepare.main(
        [str(env_file), "ops\n@example.invalid", "/safe/manifest.json", str(output)]
    ) == 1

    captured = capsys.readouterr()
    assert "ops" not in captured.err
    assert not output.exists()
