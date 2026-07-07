"""Sinal read-only de escopo de tenant (PR1 — estritamente aditivo).

Objetivo: dado uma sessao, dizer se ela esta rodando *tenant-scoped* — isto e,
sob o papel `authenticated` (NOBYPASSRLS) e com `current_igreja_id()` resolvido
(nao-nulo). Serve de sinal de observabilidade: uma sessao que DEVERIA ser
tenant-scoped mas roda no papel de conexao (`postgres`, BYPASSRLS) e um risco de
vazamento entre tenants — e este helper permite detecta-lo num caminho de
amostra.

IMPORTANTE — contrato deste PR:
  * O helper e PURAMENTE read-only: emite UM unico SELECT e NAO altera o papel,
    o GUC nem qualquer estado da sessao (nenhum SET / set_config de escrita).
  * Ele NAO e plugado em nenhum caminho de producao aqui (deps.py/routers/
    workers seguem intactos). E apenas disponibilizado e coberto por teste; a
    fiacao real em um caminho de amostra fica para um PR futuro.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

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
        is_scoped: True somente se role == TENANT_ROLE e igreja_id nao-nulo.
    """

    role: str | None
    igreja_id: str | None
    is_scoped: bool


def probe_tenant_scope(session: Session) -> TenantScopeSignal:
    """Le o escopo de tenant da sessao SEM alterar nada.

    Emite um unico SELECT read-only de `current_setting('role')` e
    `current_igreja_id()`. Nao executa SET/set_config e nao muta a sessao.

    Args:
        session: sessao SQLAlchemy a inspecionar.

    Returns:
        TenantScopeSignal com role, igreja_id e o booleano is_scoped.
    """
    row = session.execute(
        text(
            "select current_setting('role', true) as role, "
            "current_igreja_id() as igreja_id"
        )
    ).one()
    role = row.role
    igreja_id = None if row.igreja_id is None else str(row.igreja_id)
    is_scoped = role == TENANT_ROLE and igreja_id is not None
    return TenantScopeSignal(role=role, igreja_id=igreja_id, is_scoped=is_scoped)


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
