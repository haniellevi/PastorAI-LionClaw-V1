#!/usr/bin/env python3
"""Dry-run por padrão para excluir todos os tenants de um banco PostgreSQL."""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import stat
import sys
from collections.abc import Callable, Container
from pathlib import Path

# Direct ``python backend/scripts/reset_tudo.py`` starts with scripts/ as the
# import root. Add only this repository's backend root, never a global path.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.services.tenant_deletion import (
    E4bPopulatedError,
    TenantDeletionActor,
    TenantDeletionBlocked,
    collect_reset_counts,
    reset_all_tenants,
)

_SAFE_QUERY_OPTIONS = {"sslmode", "connect_timeout", "application_name"}
_BLOCKED_QUERY_OPTIONS = {
    "host",
    "hostaddr",
    "port",
    "dbname",
    "service",
    "user",
    "password",
    "passfile",
    "options",
}
_REDIRECT_ENVIRONMENT = (
    "PGHOSTADDR",
    "PGOPTIONS",
    "PGPORT",
    "PGSERVICE",
    "PGSERVICEFILE",
)
_SUPPORTED_DRIVERS = {"postgresql", "postgresql+psycopg2"}
_HOSTNAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")


class ResetTargetError(ValueError):
    """The supplied URL could resolve to an unconfirmed database target."""


def _is_displayable_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return bool(_HOSTNAME_RE.fullmatch(host))
    return True


def parse_target_database_url(
    raw_url: str, *, environment: Container[str] | None = None
) -> tuple[URL, str]:
    """Accept only a PostgreSQL URL with one explicit, displayable host."""
    try:
        url = make_url(raw_url)
    except Exception as exc:
        raise ResetTargetError("URL de banco inválida") from exc
    if url.drivername not in _SUPPORTED_DRIVERS:
        raise ResetTargetError("O destino deve usar PostgreSQL")
    env = os.environ if environment is None else environment
    if any(name in env for name in _REDIRECT_ENVIRONMENT):
        raise ResetTargetError("O ambiente contém redirecionamento de destino não permitido")
    host = url.host
    if (
        not isinstance(host, str)
        or not host
        or host != host.strip()
        or any(char in host for char in (",", "/", "?", "#"))
        or not _is_displayable_host(host)
    ):
        raise ResetTargetError("A URL precisa declarar um único host explícito")
    if not url.database:
        raise ResetTargetError("A URL precisa declarar o banco de destino")
    try:
        _ = url.port
    except ValueError as exc:
        raise ResetTargetError("Porta do banco inválida") from exc
    for key in url.query:
        normalized = str(key).lower()
        if normalized in _BLOCKED_QUERY_OPTIONS or normalized not in _SAFE_QUERY_OPTIONS:
            raise ResetTargetError("A URL contém opção de redirecionamento não permitida")
    return url, host


def validate_backup_path(raw_path: str | None) -> bool:
    """Check only metadata. Backup contents are never opened by this command."""
    if not raw_path:
        return False
    try:
        path = Path(raw_path)
        metadata = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(metadata.st_mode) and metadata.st_size > 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", required=True, help="URL PostgreSQL explícita")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="executa a exclusão após as confirmações obrigatórias",
    )
    parser.add_argument("--backup-path", help="arquivo pg_dump prévio, sem leitura")
    parser.add_argument(
        "--backup-confirmed",
        action="store_true",
        help="atesta que --backup-path é um pg_dump prévio do destino",
    )
    return parser


def _print_counts(host: str, counts, output: Callable[[str], None]) -> None:
    output(f"Destino confirmado para revisão: host={host}")
    output(
        "Contagens: "
        f"igrejas={counts.igrejas} app_users={counts.app_users} "
        f"pessoas={counts.pessoas} subscriptions={counts.subscriptions} "
        f"platform_admins={counts.platform_admins} "
        f"platform_audit_events={counts.platform_audit_events}"
    )


def _print_e4b_block(
    host: str, error: E4bPopulatedError, output: Callable[[str], None]
) -> None:
    output(f"Destino confirmado para revisão: host={host}")
    counts = " ".join(
        f"{table}={count}" for table, count in error.table_counts.items()
    )
    output(f"{error.code}: {counts}")


def _set_public_search_path(session: Session) -> None:
    session.execute(text("SET LOCAL search_path TO public"))


def main(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
    engine_factory: Callable[..., object] = create_engine,
    session_factory_factory: Callable[..., Callable[[], Session]] = sessionmaker,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        url, host = parse_target_database_url(args.database_url)
    except ResetTargetError as exc:
        output(f"Abortado: {exc}")
        return 2

    engine = None
    session = None
    try:
        engine = engine_factory(url, future=True, pool_pre_ping=True)
        factory = session_factory_factory(
            bind=engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
        session = factory()
    except Exception:
        dispose = getattr(engine, "dispose", None)
        if callable(dispose):
            dispose()
        output("Abortado: não foi possível preparar a conexão ao destino")
        return 2

    try:
        try:
            _set_public_search_path(session)
            counts = collect_reset_counts(session)
            session.rollback()
        except E4bPopulatedError as exc:
            session.rollback()
            _print_e4b_block(host, exc, output)
            return 3
        except Exception:
            session.rollback()
            output("Abortado: não foi possível consultar as contagens do destino")
            return 2
        _print_counts(host, counts, output)

        if not args.execute:
            output("Dry-run concluído: nenhuma alteração foi realizada.")
            return 0
        if not args.backup_confirmed or not validate_backup_path(args.backup_path):
            output("Abortado: --execute exige pg_dump prévio válido e --backup-confirmed.")
            return 2
        try:
            typed_host = input_fn(f"Digite exatamente o host {host} para executar: ")
        except EOFError:
            output("Abortado: confirmação do host não recebida.")
            return 2
        if typed_host != host:
            output("Abortado: confirmação do host não confere.")
            return 2

        try:
            _set_public_search_path(session)
            result = reset_all_tenants(
                session, TenantDeletionActor(app_user_id=None, email="reset_tudo")
            )
            session.commit()
        except E4bPopulatedError as exc:
            session.rollback()
            _print_e4b_block(host, exc, output)
            return 3
        except TenantDeletionBlocked as exc:
            session.rollback()
            output(f"Abortado: {exc}")
            return 2
        except Exception:
            session.rollback()
            output("Falha na transação; confirme o resultado pelo audit antes de repetir.")
            return 2
        output(
            "Reset concluído: "
            f"igrejas_excluidas={result.igrejas_deleted} "
            f"limpezas_externas_pendentes={result.pending_tasks}"
        )
        return 0
    finally:
        if session is not None:
            session.close()
        dispose = getattr(engine, "dispose", None)
        if callable(dispose):
            dispose()


if __name__ == "__main__":
    raise SystemExit(main())
