"""Contratos estáticos dos gates destrutivos do runbook de produção."""

from __future__ import annotations

import pathlib


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


def test_billing_gate_exits_before_health_and_symlink() -> None:
    block = _release_activation_block()

    gate = block.index("for service in backend queue-worker cron-worker")
    guarded_exec = block.index("if ! docker compose exec", gate)
    allow_closed = block.index(
        '[ "${ALLOW_REAL_SENDS:-false}" = "false" ]', guarded_exec
    )
    billing_closed = block.index(
        '[ "${ASAAS_BILLING_ENABLED:-false}" = "false" ]', allow_closed
    )
    hard_stop = block.index("exit 1", billing_closed)
    guard_end = block.index("fi", hard_stop)
    loop_end = block.index("done", guard_end)
    health = block.index("curl -fsS", loop_end)
    symlink = block.index("ln -sfn", health)

    assert guarded_exec < allow_closed < billing_closed < hard_stop
    assert hard_stop < guard_end < loop_end < health < symlink
    assert "cat .env" not in block
    assert "printenv" not in block
