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
    section = text.split("## 5. Deploy reproduzível do backend", 1)[1].split("## 6.", 1)[0]
    assert "BACKEND-RELEASE-MANUAL.md" in section
    assert "```bash" not in section.split("Antes de ativar um release", 1)[1]
    return (_RUNBOOK.parents[2] / "deploy" / "backend-release.sh").read_text(encoding="utf-8")


def _external_send_gate_script() -> str:
    block = _release_activation_block()
    gate = block.index("check_external_gates()")
    start = block.index("sh -c '", gate) + len("sh -c '")
    end = block.index("' >/dev/null; then", start)
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


@pytest.mark.parametrize("artifact_mode", [False, True])
def test_external_send_gate_exits_before_health_and_symlink(artifact_mode, monkeypatch) -> None:
    import importlib.util

    path = pathlib.Path(__file__).resolve().parents[2] / "deploy/tests/test_backend_release.py"
    spec = importlib.util.spec_from_file_location("synthetic_release_doubles", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.syspath_prepend(str(path.parent))
    spec.loader.exec_module(module)
    fixture = module.BackendReleaseTest()
    fixture.setUp()
    sentinel = "synthetic-private-release-config-sentinel"
    (fixture.old / "configuration.fixture").write_text("PRIVATE_FIXTURE=" + sentinel + "\n")
    fixture.environment["PRIVATE_FIXTURE"] = sentinel
    try:
        changes = {"ALLOW_REAL_SENDS": "true"}
        if artifact_mode:
            changes["RELEASE_IMAGE_REF"] = (
                "ghcr.io/haniellevi/pastorai-lionclaw-v1-backend@sha256:" + "1" * 64
            )
        result = fixture.run_release(**changes)
        assert result.returncode != 0
        assert sentinel not in result.stdout + result.stderr
        assert "external-effect gates open or unverifiable" in result.stderr
        assert not any("compose build" in call or call.startswith("curl|")
                       for call in fixture.calls())
        assert (fixture.root / "current").resolve() == fixture.old.parent
    finally:
        fixture.doCleanups()


@pytest.mark.parametrize(
    (
        "allow_real_sends",
        "asaas_billing_enabled",
        "brevo_send_mode",
        "broadcast_async_enabled",
        "expected_closed",
    ),
    (
        ("false", "false", "off", "false", True),
        (None, "false", "off", "false", False),
        ("", "false", "off", "false", False),
        ("true", "false", "off", "false", False),
        ("FALSE", "false", "off", "false", False),
        ("false", None, "off", "false", False),
        ("false", "", "off", "false", False),
        ("false", "true", "off", "false", False),
        ("false", "disabled", "off", "false", False),
        ("false", "false", None, "false", False),
        ("false", "false", "", "false", False),
        ("false", "false", "canary", "false", False),
        ("false", "false", "live", "false", False),
        ("false", "false", "OFF", "false", False),
        ("false", "false", "off", None, False),
        ("false", "false", "off", "", False),
        ("false", "false", "off", "true", False),
    ),
)
def test_external_send_gate_shell_accepts_only_explicit_closed_values(
    allow_real_sends: str | None,
    asaas_billing_enabled: str | None,
    brevo_send_mode: str | None,
    broadcast_async_enabled: str | None,
    expected_closed: bool,
) -> None:
    env = os.environ.copy()
    env.pop("ALLOW_REAL_SENDS", None)
    env.pop("ASAAS_BILLING_ENABLED", None)
    env.pop("BREVO_SEND_MODE", None)
    env.pop("BROADCAST_ASYNC_ENABLED", None)
    if allow_real_sends is not None:
        env["ALLOW_REAL_SENDS"] = allow_real_sends
    if asaas_billing_enabled is not None:
        env["ASAAS_BILLING_ENABLED"] = asaas_billing_enabled
    if brevo_send_mode is not None:
        env["BREVO_SEND_MODE"] = brevo_send_mode
    if broadcast_async_enabled is not None:
        env["BROADCAST_ASYNC_ENABLED"] = broadcast_async_enabled

    result = subprocess.run(
        [_posix_shell(), "-c", _external_send_gate_script()],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert (result.returncode == 0) is expected_closed
    assert result.stdout == ""
