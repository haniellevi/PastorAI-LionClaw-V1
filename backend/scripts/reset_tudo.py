#!/usr/bin/env python3
"""Dry-run por padrão para excluir todos os tenants de um banco PostgreSQL."""

from __future__ import annotations

import argparse
import getpass
import ipaddress
import os
import re
import stat
import sys
from collections.abc import Callable, Container, Mapping
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
    load_cleanup_drain_state,
    reset_all_tenants,
    run_pending_cleanup,
)
from app.services.asaas import AsaasClient
from app.services.clerk import ClerkClient
from app.services.evolution import EvolutionClient
from app.services.storage import SupabaseStorage

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


class _ResetArgumentError(ValueError):
    """A command-line error safe to report without echoing its values."""


class _ResetArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise _ResetArgumentError("Argumentos inválidos")


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
    """Accept only a regular, non-symlink pg_dump file by its initial bytes."""
    if not raw_path:
        return False
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        return False
    try:
        descriptor = os.open(
            raw_path,
            os.O_RDONLY
            | nofollow
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
    except OSError:
        return False
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0:
            return False
        prefix = os.read(descriptor, 512)
    except OSError:
        return False
    finally:
        os.close(descriptor)
    return prefix.startswith(b"PGDMP") or b"-- PostgreSQL database dump" in prefix


def build_parser(operation: str = "reset") -> argparse.ArgumentParser:
    description = __doc__.splitlines()[0]
    if operation == "drain-external":
        description = "Dry-run por padrão para executar limpezas externas já auditadas."
    parser = _ResetArgumentParser(description=description)
    parser.epilog = "A URL vem de RESET_DATABASE_URL ou do prompt protegido."
    parser.add_argument(
        "--execute",
        action="store_true",
        help="executa efeitos após a confirmação obrigatória do host",
    )
    if operation == "reset":
        parser.add_argument(
            "--backup-path", help="arquivo pg_dump prévio, cabeçalho verificado"
        )
        parser.add_argument(
            "--backup-confirmed",
            action="store_true",
            help="atesta que --backup-path é um pg_dump prévio do destino",
        )
    return parser


def _argv_contains_database_url(argv: list[str]) -> bool:
    return any(
        argument == "--database-url" or argument.startswith("--database-url=")
        for argument in argv
    )


def _split_operation(argv: list[str]) -> tuple[str, list[str]]:
    if argv and argv[0] in {"reset", "drain-external"}:
        return argv[0], argv[1:]
    return "reset", argv


def _read_database_url(
    environment: Mapping[str, str], secret_input: Callable[[str], str]
) -> str:
    database_url = environment.get("RESET_DATABASE_URL")
    if database_url is None:
        try:
            database_url = secret_input("Cole a URL PostgreSQL do reset: ")
        except (EOFError, KeyboardInterrupt) as exc:
            raise ResetTargetError("URL do banco não recebida") from exc
    if not isinstance(database_url, str) or not database_url.strip():
        raise ResetTargetError("URL do banco não recebida")
    return database_url


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


def _new_cleanup_clients() -> tuple[
    ClerkClient, EvolutionClient, AsaasClient, SupabaseStorage
]:
    return ClerkClient(), EvolutionClient(), AsaasClient(), SupabaseStorage()


def _close_cleanup_clients(clients: tuple[object, ...]) -> None:
    for client in clients:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _read_drain_state(session: Session):
    _set_public_search_path(session)
    state = load_cleanup_drain_state(session)
    session.rollback()
    return state


def _print_drain_state(host: str, state, output: Callable[[str], None]) -> None:
    output(f"Destino confirmado para revisão: host={host}")
    output(
        "Limpezas externas: "
        f"pendentes={len(state.pending_tasks)} "
        f"rejeitadas={len(state.rejected_tasks)}"
    )


def _drain_exit_code(state) -> int:
    return 4 if state.pending_tasks or state.rejected_tasks else 0


def _confirm_host(
    host: str,
    input_fn: Callable[[str], str],
    output: Callable[[str], None],
) -> bool:
    try:
        typed_host = input_fn(f"Digite exatamente o host {host} para executar: ")
    except (EOFError, KeyboardInterrupt):
        output("Abortado: confirmação do host não recebida.")
        return False
    if typed_host != host:
        output("Abortado: confirmação do host não confere.")
        return False
    return True


def _drain_external(
    session: Session,
    *,
    args: argparse.Namespace,
    host: str,
    input_fn: Callable[[str], str],
    output: Callable[[str], None],
    cleanup_clients_factory: Callable[[], tuple[object, ...]],
) -> int:
    try:
        initial = _read_drain_state(session)
    except Exception:
        session.rollback()
        output("Abortado: não foi possível carregar o audit de limpezas externas.")
        return 2
    _print_drain_state(host, initial, output)
    if not initial.pending_tasks:
        return _drain_exit_code(initial)
    if not args.execute:
        output("Dry-run concluído: nenhuma limpeza externa foi executada.")
        return 4
    if not _confirm_host(host, input_fn, output):
        return 2

    try:
        current = _read_drain_state(session)
    except Exception:
        session.rollback()
        output("Abortado: não foi possível recarregar o audit de limpezas externas.")
        return 2
    if not current.pending_tasks:
        _print_drain_state(host, current, output)
        return _drain_exit_code(current)

    clients: tuple[object, ...] = ()
    try:
        clients = cleanup_clients_factory()
        clerk, evolution, asaas, storage = clients
        outcomes = run_pending_cleanup(
            session,
            TenantDeletionActor(
                app_user_id=None,
                email="reset_tudo",
                execution_host=host,
            ),
            current.pending_tasks,
            clerk=clerk,
            evolution=evolution,
            asaas=asaas,
            storage=storage,
            before_task=_set_public_search_path,
        )
    except Exception:
        session.rollback()
        output("Falha no drain; confirme o resultado pelo audit antes de repetir.")
        return 2
    finally:
        _close_cleanup_clients(clients)

    try:
        final = _read_drain_state(session)
    except Exception:
        session.rollback()
        output("Falha no drain; confirme o resultado pelo audit antes de repetir.")
        return 2
    completed = sum(outcome.status == "done" for outcome in outcomes)
    output(
        "Drain concluído: "
        f"concluídas={completed} pendentes={len(final.pending_tasks)} "
        f"rejeitadas={len(final.rejected_tasks)}"
    )
    return _drain_exit_code(final)


def main(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    secret_input: Callable[[str], str] = getpass.getpass,
    output: Callable[[str], None] = print,
    engine_factory: Callable[..., object] = create_engine,
    session_factory_factory: Callable[..., Callable[[], Session]] = sessionmaker,
    environment: Mapping[str, str] | None = None,
    cleanup_clients_factory: Callable[[], tuple[object, ...]] = _new_cleanup_clients,
) -> int:
    parsed_argv = list(sys.argv[1:] if argv is None else argv)
    if _argv_contains_database_url(parsed_argv):
        output("Abortado: URL de banco no argv não é aceita.")
        return 2
    operation, operation_argv = _split_operation(parsed_argv)
    try:
        args = build_parser(operation).parse_args(operation_argv)
    except _ResetArgumentError as exc:
        output(f"Abortado: {exc}")
        return 2
    database_environment = os.environ if environment is None else environment
    try:
        url, host = parse_target_database_url(
            _read_database_url(database_environment, secret_input),
            environment=database_environment,
        )
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
        if operation == "drain-external":
            return _drain_external(
                session,
                args=args,
                host=host,
                input_fn=input_fn,
                output=output,
                cleanup_clients_factory=cleanup_clients_factory,
            )
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
        if not _confirm_host(host, input_fn, output):
            return 2

        try:
            _set_public_search_path(session)
            result = reset_all_tenants(
                session,
                TenantDeletionActor(
                    app_user_id=None,
                    email="reset_tudo",
                    execution_host=host,
                ),
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
