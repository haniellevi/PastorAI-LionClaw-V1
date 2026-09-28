"""Regressões isoladas para o comando ``./dev.sh reset``."""

from __future__ import annotations

import shlex
import subprocess
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEV_SH = ROOT / "dev.sh"


def _run_reset_with_restart(
    restart_status: int, ps_status: int = 0
) -> subprocess.CompletedProcess[str]:
    script = f"""
source {shlex.quote(str(DEV_SH))}
state_dir=$(mktemp -d)
preparar() {{ mkdir -p "$state_dir/logs"; }}
info() {{ printf 'INFO:%s\\n' "$*"; }}
erro() {{ printf 'ERRO:%s\\n' "$*" >&2; exit 1; }}
compose() {{
  case "$1" in
    stop) return 0 ;;
    ps) printf 'backend\\n'; return {ps_status} ;;
    up) printf 'synthetic restart failure\\n'; return {restart_status} ;;
  esac
  return 0
}}
supabase_cli() {{ return 0; }}
emitir_recibo_banco_local() {{ return 0; }}
carregar_chaves_supabase() {{ return 0; }}
no_backend() {{ return 0; }}
criar_buckets() {{ return 0; }}
cmd_reset
"""
    return subprocess.run(
        ["bash", "-c", script, str(DEV_SH)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_reset_falha_se_o_restart_dos_servicos_falhar() -> None:
    result = _run_reset_with_restart(42)

    assert result.returncode != 0
    assert "synthetic restart failure" in result.stderr
    assert "banco local recriado" not in result.stdout


def test_reset_mantem_sucesso_quando_o_restart_funciona() -> None:
    result = _run_reset_with_restart(0)

    assert result.returncode == 0
    assert "banco local recriado" in result.stdout


def test_reset_falha_se_descoberta_dos_servicos_falhar() -> None:
    result = _run_reset_with_restart(0, ps_status=42)

    assert result.returncode != 0
    assert "descobrir" in result.stderr
    assert "banco local recriado" not in result.stdout


def test_recibo_da_instancia_local_e_legivel_no_bind_do_backend() -> None:
    script = f"""
source {shlex.quote(str(DEV_SH))}
state_dir=$(mktemp -d)
erro() {{ printf 'ERRO:%s\\n' "$*" >&2; exit 1; }}
docker_local_exec() {{ printf '123456789\\n'; }}
emitir_recibo_banco_local
stat -c '%a' "$state_dir/local-db-identity.json"
"""
    result = subprocess.run(
        ["bash", "-c", script, str(DEV_SH)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.rstrip().endswith("644")


def test_preparar_recusa_docker_host_remoto_antes_da_stack() -> None:
    script = f"""
source {shlex.quote(str(DEV_SH))}
garantir_env() {{ printf 'ENV_TOUCHED\\n'; }}
subir_supabase() {{ printf 'STACK_TOUCHED\\n'; }}
carregar_chaves_supabase() {{ return 0; }}
construir_imagem() {{ return 0; }}
docker() {{ printf '111\\n'; }}
preparar
"""
    result = subprocess.run(
        ["bash", "-c", script, str(DEV_SH)],
        env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "DOCKER_HOST": "tcp://synthetic-remote.invalid:2375"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Docker local" in result.stderr
    assert "ENV_TOUCHED" not in result.stdout
    assert "STACK_TOUCHED" not in result.stdout


def test_emissor_recusa_contexto_remoto_sem_emitir_recibo(tmp_path: Path) -> None:
    script = f"""
source {shlex.quote(str(DEV_SH))}
state_dir={shlex.quote(str(tmp_path))}
docker_context_host() {{ printf 'ssh://synthetic-remote.invalid\\n'; }}
docker() {{ printf '111\\n'; }}
emitir_recibo_banco_local
"""
    result = subprocess.run(
        ["bash", "-c", script, str(DEV_SH)],
        env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "DOCKER_CONTEXT": "synthetic-remote"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Docker local" in result.stderr
    assert not (tmp_path / "local-db-identity.json").exists()


def test_emissor_usa_endpoint_unix_fixo_com_duble(tmp_path: Path) -> None:
    socket_path = tmp_path / "docker.sock"
    docker_log = tmp_path / "docker-call.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        '#!/usr/bin/env bash\n'
        'printf "%s\\n" "$DOCKER_HOST|${DOCKER_CONTEXT-unset}|$*" > "$DOCKER_TEST_LOG"\n'
        'printf "111\\n"\n',
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    script = f"""
source {shlex.quote(str(DEV_SH))}
state_dir={shlex.quote(str(tmp_path))}
docker_socket_permitido() {{ return 0; }}
docker_socket_valido() {{ return 0; }}
emitir_recibo_banco_local
"""
    result = subprocess.run(
        ["bash", "-c", script, str(DEV_SH)],
        env={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HOME": os.environ["HOME"],
            "DOCKER_HOST": f"unix://{socket_path}",
            "DOCKER_TEST_LOG": str(docker_log),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert (tmp_path / "local-db-identity.json").exists()
    invocation = docker_log.read_text(encoding="utf-8")
    assert invocation.startswith(f"unix://{socket_path}|unset|")
    assert "exec " in invocation
