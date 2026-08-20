"""Contratos estáticos dos gates destrutivos do runbook de produção."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

import pytest


_RUNBOOK = (
    pathlib.Path(__file__).resolve().parents[2]
    / "docs"
    / "ops"
    / "PRODUCTION-RUNBOOK.md"
)


def _release_activation_block() -> str:
    text = _RUNBOOK.read_text(encoding="utf-8")
    section = text.index("Antes de ativar um release")
    start = text.index("```bash", section) + len("```bash")
    end = text.index("```", start)
    return text[start:end]


def _external_send_gate_script() -> str:
    block = _release_activation_block()
    gate = block.index("for service in backend queue-worker cron-worker")
    start = block.index("sh -lc '", gate) + len("sh -lc '")
    end = block.index("'; then", start)
    return block[start:end]


def _posix_shell() -> str:
    candidates: list[str | None] = []
    if os.name == "nt":
        candidates.extend(
            (
                r"C:\Program Files\Git\bin\sh.exe",
                r"C:\Program Files\Git\usr\bin\sh.exe",
            )
        )
    candidates.extend((shutil.which("sh"), shutil.which("bash")))
    for candidate in candidates:
        if candidate and pathlib.Path(candidate).is_file():
            return candidate
    pytest.skip("shell POSIX indisponível para validar o gate operacional")


def test_external_send_gate_exits_before_health_and_symlink() -> None:
    block = _release_activation_block()

    gate = block.index("for service in backend queue-worker cron-worker")
    guarded_exec = block.index("if ! docker compose exec", gate)
    allow_present = block.index(
        '[ "${ALLOW_REAL_SENDS+x}" = "x" ]', guarded_exec
    )
    allow_closed = block.index('[ "$ALLOW_REAL_SENDS" = "false" ]', allow_present)
    billing_present = block.index(
        '[ "${ASAAS_BILLING_ENABLED+x}" = "x" ]', allow_closed
    )
    billing_closed = block.index(
        '[ "$ASAAS_BILLING_ENABLED" = "false" ]', billing_present
    )
    brevo_present = block.index(
        '[ "${BREVO_SEND_MODE+x}" = "x" ]', billing_closed
    )
    brevo_closed = block.index('[ "$BREVO_SEND_MODE" = "off" ]', brevo_present)
    hard_stop = block.index("exit 1", brevo_closed)
    guard_end = block.index("fi", hard_stop)
    loop_end = block.index("done", guard_end)
    health = block.index("curl -fsS", loop_end)
    symlink = block.index("ln -sfn", health)

    assert (
        guarded_exec
        < allow_present
        < allow_closed
        < billing_present
        < billing_closed
        < brevo_present
        < brevo_closed
        < hard_stop
    )
    assert hard_stop < guard_end < loop_end < health < symlink
    assert ":-false" not in block
    assert "cat .env" not in block
    assert "printenv" not in block


@pytest.mark.parametrize(
    (
        "allow_real_sends",
        "asaas_billing_enabled",
        "brevo_send_mode",
        "expected_closed",
    ),
    (
        ("false", "false", "off", True),
        (None, "false", "off", False),
        ("", "false", "off", False),
        ("true", "false", "off", False),
        ("FALSE", "false", "off", False),
        ("false", None, "off", False),
        ("false", "", "off", False),
        ("false", "true", "off", False),
        ("false", "disabled", "off", False),
        ("false", "false", None, False),
        ("false", "false", "", False),
        ("false", "false", "canary", False),
        ("false", "false", "live", False),
        ("false", "false", "OFF", False),
    ),
)
def test_external_send_gate_shell_accepts_only_explicit_closed_values(
    allow_real_sends: str | None,
    asaas_billing_enabled: str | None,
    brevo_send_mode: str | None,
    expected_closed: bool,
) -> None:
    env = os.environ.copy()
    env.pop("ALLOW_REAL_SENDS", None)
    env.pop("ASAAS_BILLING_ENABLED", None)
    env.pop("BREVO_SEND_MODE", None)
    if allow_real_sends is not None:
        env["ALLOW_REAL_SENDS"] = allow_real_sends
    if asaas_billing_enabled is not None:
        env["ASAAS_BILLING_ENABLED"] = asaas_billing_enabled
    if brevo_send_mode is not None:
        env["BREVO_SEND_MODE"] = brevo_send_mode

    result = subprocess.run(
        [_posix_shell(), "-c", _external_send_gate_script()],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert (result.returncode == 0) is expected_closed
    assert ("external-send gates: CLOSED" in result.stdout) is expected_closed
