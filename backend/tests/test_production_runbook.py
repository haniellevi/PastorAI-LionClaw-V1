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


def _billing_gate_script() -> str:
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


def test_billing_gate_exits_before_health_and_symlink() -> None:
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
    hard_stop = block.index("exit 1", billing_closed)
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
        < hard_stop
    )
    assert hard_stop < guard_end < loop_end < health < symlink
    assert ":-false" not in block
    assert "cat .env" not in block
    assert "printenv" not in block


@pytest.mark.parametrize(
    ("allow_real_sends", "asaas_billing_enabled", "expected_closed"),
    (
        ("false", "false", True),
        (None, "false", False),
        ("", "false", False),
        ("true", "false", False),
        ("FALSE", "false", False),
        ("false", None, False),
        ("false", "", False),
        ("false", "true", False),
        ("false", "disabled", False),
    ),
)
def test_billing_gate_shell_accepts_only_two_explicit_false_values(
    allow_real_sends: str | None,
    asaas_billing_enabled: str | None,
    expected_closed: bool,
) -> None:
    env = os.environ.copy()
    env.pop("ALLOW_REAL_SENDS", None)
    env.pop("ASAAS_BILLING_ENABLED", None)
    if allow_real_sends is not None:
        env["ALLOW_REAL_SENDS"] = allow_real_sends
    if asaas_billing_enabled is not None:
        env["ASAAS_BILLING_ENABLED"] = asaas_billing_enabled

    result = subprocess.run(
        [_posix_shell(), "-c", _billing_gate_script()],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert (result.returncode == 0) is expected_closed
    assert ("billing gates: CLOSED" in result.stdout) is expected_closed
