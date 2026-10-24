#!/usr/bin/env python3
"""Reconciliação excepcional e nominal de UM vínculo Pessoa duplicado.

Desvincula somente a conta escolhida por humanos (``--corrigir``) e preserva a
outra (``--manter``). Nunca escolhe automaticamente. Sem ``--aplicar`` roda só
a prévia, em transação ``REPEATABLE READ READ ONLY``.

A aplicação exige igreja, pessoa esperada, as duas contas, admin ativo da
igreja, operador platform admin ativo, id de operação UUID e SHA exato, além
da linha exata ``DESVINCULAR:<sha256 do payload>`` emitida pela prévia e lida
da entrada padrão (nunca de argumento). A auditoria vai para
``platform_audit_log`` na mesma transação privilegiada. UUIDs não autenticam
pessoas: quem executa responde pela sessão nominal autorizada fora do script.

A conexão vem só de ``TEAM_PESSOA_RECONCILE_DATABASE_URL``; o script não lê
``.env`` nem a configuração da aplicação. A saída mostra apenas códigos e
contagens, sem UUIDs ou dados pessoais. Ferramenta operacional: não integra o
catálogo do agente. Executar contra PROD exige autorização nominal e o
[runbook do lote](../../docs/ops/RELEASE-LOTE-2026-10.md).
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.exc import DBAPIError, SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.db.tenant_session import mark_cross_tenant  # noqa: E402
from app.services.team_pessoa import (  # noqa: E402
    REFUSALS,
    DuplicateLinkReconciliation,
    ReconciliationRefused,
    reconcile_duplicate_link,
    validate_request,
)

DATABASE_URL_ENV = "TEAM_PESSOA_RECONCILE_DATABASE_URL"
ALLOWED_DRIVERS = frozenset({"postgresql", "postgresql+psycopg2"})
LOCK_NOT_AVAILABLE = "55P03"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--igreja", "--pessoa", "--manter", "--corrigir",
                 "--admin-igreja", "--operador", "--operacao"):
        parser.add_argument(flag, required=True, type=uuid.UUID)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--aplicar", action="store_true",
                        help="aplica após ler da entrada padrão o código CONFIRMACAO da prévia")
    parser.add_argument("--lock-timeout-ms", type=int, default=5000, help="1 a 30000")
    return parser


def _request(args, confirmation: str | None) -> DuplicateLinkReconciliation:
    return DuplicateLinkReconciliation(
        operation_id=args.operacao,
        igreja_id=args.igreja,
        pessoa_id=args.pessoa,
        keep_user_id=args.manter,
        target_user_id=args.corrigir,
        church_admin_id=args.admin_igreja,
        operator_id=args.operador,
        release_sha=args.release_sha,
        confirmation=confirmation,
    )


def _print_result(result) -> None:
    print(
        f"RESULTADO={result.code} grupo_linhas_antes={result.group_rows_before} "
        f"grupo_linhas_depois={result.group_rows_after} "
        f"admins_ativos_antes={result.active_admins_before} "
        f"admins_ativos_depois={result.active_admins_after} "
        f"linhas_alteradas={result.changed_rows}"
    )
    if result.confirmation_token:
        # Hash do payload aprovado: não contém UUIDs nem dados pessoais.
        print(f"CONFIRMACAO={result.confirmation_token}")


def _refuse(code: str, exit_code: int = 1) -> int:
    print(f"RECONCILIACAO_RECUSADA={code}: {REFUSALS[code]}", file=sys.stderr)
    return exit_code


def _engine(raw_url: str):
    """Cria o engine só para URL postgresql; nunca repete a DSN recebida."""

    try:
        url = make_url(raw_url)
        if url.drivername not in ALLOWED_DRIVERS or not url.database:
            return None
        return create_engine(url, poolclass=NullPool)
    except Exception:  # noqa: BLE001 - mensagens do parser/driver podem conter a DSN
        return None


def run(argv: list[str] | None = None, *, stdin=None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    raw_url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not raw_url:
        print(f"RECONCILIACAO_RECUSADA: defina {DATABASE_URL_ENV} no ambiente seguro", file=sys.stderr)
        return 2
    confirmation = None
    if args.aplicar:
        # Comparação exata com o código da prévia; só a quebra de linha sai.
        confirmation = (stdin or sys.stdin).readline().rstrip("\r\n")

    engine = None
    try:
        validate_request(_request(args, confirmation), apply=args.aplicar,
                         lock_timeout_ms=args.lock_timeout_ms)
        engine = _engine(raw_url)
        if engine is None:
            return _refuse("conexao_invalida", 2)
        with engine.connect() as connection:
            if not args.aplicar:
                connection = connection.execution_options(
                    isolation_level="REPEATABLE READ", postgresql_readonly=True,
                )
            with Session(bind=connection) as db:
                # Plano de plataforma explícito: sem escopo de tenant e sob a role
                # privilegiada da conexão, conferida pelo serviço.
                mark_cross_tenant(db, source="reconcile_team_pessoa")
                try:
                    read_only = db.execute(text("select current_setting('transaction_read_only')")).scalar_one()
                    if read_only != ("off" if args.aplicar else "on"):
                        raise ReconciliationRefused("falha_banco")
                    result = reconcile_duplicate_link(
                        db, _request(args, confirmation), apply=args.aplicar,
                        lock_timeout_ms=args.lock_timeout_ms,
                    )
                    if args.aplicar and result.code == "APLICADA":
                        db.commit()
                    else:
                        db.rollback()
                except BaseException:
                    db.rollback()
                    raise
        _print_result(result)
        return 0
    except ReconciliationRefused as exc:
        return _refuse(exc.code)
    except DBAPIError as exc:
        pgcode = getattr(exc.orig, "pgcode", None)
        return _refuse("lock_indisponivel" if pgcode == LOCK_NOT_AVAILABLE else "falha_banco")
    except (SQLAlchemyError, ValueError):
        # Mensagens de driver podem conter DSN, host ou valores: nunca repassar.
        return _refuse("falha_banco")
    except Exception:  # noqa: BLE001 - nenhuma exceção sai com traceback ou valores
        return _refuse("falha_interna")
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(run())
