"""test-local.sh: alvo desconhecido falha antes de executar qualquer ferramenta."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "test-local.sh"


def _rodar(tmp_path: Path, *args: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    chamadas = tmp_path / "chamadas"
    fake_python = tmp_path / "python"
    fake_python.write_text(f'#!/usr/bin/env bash\necho "$@" >> "{chamadas}"\n')
    fake_python.chmod(0o755)
    env = {**os.environ, "PASTORAI_PYTHON": str(fake_python), "PASTORAI_NODE_BIN": str(tmp_path)}
    resultado = subprocess.run(
        ["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False
    )
    return resultado, chamadas


def test_alvo_desconhecido_falha_sem_executar_ferramenta(tmp_path: Path) -> None:
    resultado, chamadas = _rodar(tmp_path, "bakend")

    assert resultado.returncode != 0
    assert "bakend" in resultado.stderr
    assert not chamadas.exists()


def test_alvo_backend_continua_aceito(tmp_path: Path) -> None:
    resultado, chamadas = _rodar(tmp_path, "backend")

    assert resultado.returncode == 0
    assert "pytest" in chamadas.read_text()
