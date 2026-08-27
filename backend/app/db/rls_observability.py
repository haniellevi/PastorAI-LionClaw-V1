"""Sinal read-only e barreira fail-closed de escopo de tenant.

Objetivo: dado uma sessao, dizer se ela esta rodando *tenant-scoped* — isto e,
sob o papel `authenticated` (NOBYPASSRLS) e com `current_igreja_id()` resolvido
(nao-nulo). Serve de sinal de observabilidade: uma sessao que DEVERIA ser
tenant-scoped mas roda no papel de conexao (`postgres`, BYPASSRLS) e um risco de
vazamento entre tenants — e este helper permite detecta-lo num caminho de
amostra.

Contrato:
  * O helper e PURAMENTE read-only: emite UM unico SELECT e NAO altera o papel,
    o GUC nem qualquer estado da sessao (nenhum SET / set_config de escrita).
  * `log_if_not_scoped` permanece um sinal de observabilidade.
  * `require_tenant_scope` e uma barreira usada pelo worker e runtime do agente:
    exige papel, tenant derivado e GUC transacional iguais ao tenant esperado.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.tenant_session import TenantScopeError

logger = logging.getLogger(__name__)

# Papel de tenant esperado (NOBYPASSRLS). O papel de conexao (postgres) tem
# BYPASSRLS e, sem `SET LOCAL ROLE authenticated`, `current_setting('role')`
# devolve 'none'.
TENANT_ROLE = "authenticated"


@dataclass(frozen=True)
class TenantScopeSignal:
    """Fotografia read-only do escopo de tenant de uma sessao.

    Attributes:
        role: valor de `current_setting('role')` (ex.: 'authenticated' ou 'none').
        igreja_id: `current_igreja_id()` resolvido (str) ou None.
        tenant_guc: valor transacional de `app.tenant_igreja_id` ou None.
        is_scoped: sinal base, True quando role == TENANT_ROLE e igreja_id
            nao-nulo. A barreira estrita também compara tenant_guc.
    """

    role: str | None
    igreja_id: str | None
    tenant_guc: str | None
    is_scoped: bool


class TenantScopeVerificationError(TenantScopeError):
    """A sessão não possui exatamente o escopo de tenant exigido."""


def probe_tenant_scope(session: Session) -> TenantScopeSignal:
    """Le o escopo de tenant da sessao SEM alterar nada.

    Emite um unico SELECT read-only de `current_setting('role')` e
    `current_igreja_id()`. Nao executa SET/set_config e nao muta a sessao.

    Args:
        session: sessao SQLAlchemy a inspecionar.

    Returns:
        TenantScopeSignal com role, igreja_id, tenant_guc e is_scoped.
    """
    row = session.execute(
        text(
            "select current_setting('role', true) as role, "
            "current_igreja_id() as igreja_id, "
            "nullif(current_setting('app.tenant_igreja_id', true), '') "
            "as tenant_guc"
        )
    ).one()
    role = row.role
    igreja_id = None if row.igreja_id is None else str(row.igreja_id)
    tenant_guc = None if row.tenant_guc is None else str(row.tenant_guc)
    is_scoped = role == TENANT_ROLE and igreja_id is not None
    return TenantScopeSignal(
        role=role,
        igreja_id=igreja_id,
        tenant_guc=tenant_guc,
        is_scoped=is_scoped,
    )


def log_if_not_scoped(
    session: Session, *, source: str | None = None
) -> TenantScopeSignal:
    """Emite um warning se a sessao NAO estiver tenant-scoped; retorna o sinal.

    Conveniencia read-only: nao muta a sessao, so observa e loga. A partir do
    PR3-A e ligada num caminho HTTP de amostra do seam (subscription.get) como
    fonte do gatilho de rollback da SPEC secao 9/10 — evidencia de leitura
    cross-tenant / perda de contexto nos logs.

    O log e ESTRUTURADO e livre de PII/segredos: no maximo `source`, `role` e
    `igreja_id` (o proprio tenant, nunca dado pessoal).

    Args:
        session: sessao SQLAlchemy a inspecionar.
        source: rotulo opcional da origem da observacao (ex.: "http").
    """
    signal = probe_tenant_scope(session)
    if not signal.is_scoped:
        logger.warning(
            "Sessao NAO tenant-scoped (possivel BYPASSRLS): "
            "source=%s role=%s igreja_id=%s",
            source,
            signal.role,
            signal.igreja_id,
        )
    return signal


def require_tenant_scope(
    session: Session,
    *,
    expected_igreja_id: object,
    source: str | None = None,
) -> TenantScopeSignal:
    """Exige papel tenant e o ``igreja_id`` esperado, sem corrigir o contexto.

    Diferente de :func:`log_if_not_scoped`, este helper é uma barreira de
    execução. Ele observa o papel e o GUC já aplicados pelo chamador e levanta
    uma exceção quando o contexto está ausente, está em BYPASSRLS ou aponta
    para outra igreja. A exceção acontece antes de qualquer leitura de domínio.
    """

    expected = str(expected_igreja_id).strip()
    if not expected:
        raise ValueError("expected_igreja_id é obrigatório")

    signal = probe_tenant_scope(session)
    matches_expected = signal.igreja_id == expected
    guc_matches_expected = signal.tenant_guc == expected
    if not signal.is_scoped or not matches_expected or not guc_matches_expected:
        logger.error(
            "Escopo de tenant obrigatório ausente ou inconsistente: "
            "source=%s role=%s scoped=%s tenant_matches=%s guc_matches=%s",
            source,
            signal.role,
            signal.is_scoped,
            matches_expected,
            guc_matches_expected,
        )
        raise TenantScopeVerificationError(
            "sessão sem o escopo de tenant obrigatório"
        )
    return signal
