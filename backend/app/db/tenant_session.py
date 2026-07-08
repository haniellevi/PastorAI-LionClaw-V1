"""Seam profundo de escopo por tenant (PR2 — D1/D2/D3/D4).

Este módulo é o ÚNICO lugar que conhece a combinação
`GUC + SET LOCAL ROLE + re-asserção pós-commit + pinning + saída cross-tenant`.
`app/db/rls.py` continua como primitivo low-level (SQL cru); aqui construímos a
disciplina de sessão em cima dele.

Estratégia (fixa pelo SPEC):
  * **D3 — igreja em `session.info`**: a marcação de tenant é gravada em
    `session.info[TENANT_IGREJA_KEY]`. É a fonte de verdade que o listener lê.
  * **D2 — listener `after_begin`**: registrado UMA vez (no import de
    `session.py`), reaplica o escopo em TODA nova transação da sessão marcada —
    inclusive depois de um `commit()` (o `SET LOCAL` reverte por transação, então
    sem o listener uma leitura pós-commit perderia o escopo).
  * **D1 — pinning**: uma sessão marcada num tenant NUNCA é re-fixada em outro
    silenciosamente; conflito levanta `TenantPinConflictError`.
  * **D4 — saída cross-tenant nomeada**: uma sessão só roda no papel de conexão
    (BYPASSRLS) quando marcada EXPLICITAMENTE via `mark_cross_tenant`; a volta ao
    escopo se dá por `promote_to_tenant` (nome explícito, auditável).

PRINCÍPIO TRANSVERSAL — **fail-closed**: NENHUM `try/except` que continue sem
escopo. Se reaplicar o escopo falhar (ex.: papel `authenticated` inexistente), a
exceção PROPAGA e derruba a transação. Correr em BYPASSRLS por engano é pior do
que falhar barulhento.

Coexistência (PR2): este seam NÃO remove os `ensure_tenant_context` /
`set_tenant_context_for_igreja` legados. Ele é criado e PROVADO aqui; a migração
dos caminhos de produção vem nos PRs seguintes. A marcação é idempotente e
byte-compatível com o SQL legado, então os dois mecanismos coexistem produzindo
o mesmo tenant.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, SessionTransaction

from app.db.rls import set_tenant_context_for_igreja

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chaves de session.info (D3). Estáveis: consumidas pelo listener e pelos testes.
# ---------------------------------------------------------------------------
TENANT_IGREJA_KEY = "tenant_igreja_id"
TENANT_META_KEY = "tenant_meta"
CROSS_TENANT_KEY = "cross_tenant"

# Papel de tenant (NOBYPASSRLS). Idêntico ao usado por rls.py.
TENANT_ROLE = "authenticated"
# GUC honrado por current_igreja_id() (migration 20260624_*). Idêntico a rls.py.
_TENANT_GUC = "app.tenant_igreja_id"


# ---------------------------------------------------------------------------
# Hierarquia de exceções nomeadas
# ---------------------------------------------------------------------------
class TenantScopeError(RuntimeError):
    """Base de todos os erros de disciplina de escopo por tenant do seam."""


class TenantPinConflictError(TenantScopeError):
    """Tentativa de re-fixar uma sessão já pinada em OUTRO tenant (ou de misturar
    os modos mutuamente exclusivos scoped × cross-tenant). Nunca sobrescreve o
    pin silenciosamente (D1)."""


class TenantPromotionError(TenantScopeError):
    """`promote_to_tenant` inválido: a sessão não estava em modo cross-tenant, ou
    a promoção mira um tenant diferente de um já pinado (D4)."""


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------
def _normalize_igreja_id(igreja_id: Any) -> str:
    """Coage para str não-vazia; recusa None/vazio na ENTRADA (fail-closed).

    A recusa é um ValueError (erro de programação do chamador), distinto dos
    erros de disciplina (TenantScopeError): marcar sem tenant é um bug, não um
    conflito de estado.
    """
    if igreja_id is None:
        raise ValueError("igreja_id é obrigatório para escopar a sessão por tenant")
    value = str(igreja_id).strip()
    if not value:
        raise ValueError("igreja_id vazio não pode escopar a sessão por tenant")
    return value


def _apply_scope_now(session: Session, igreja_id: str) -> None:
    """Aplica o escopo na transação ATUAL, imediatamente.

    Reusa o primitivo low-level `set_tenant_context_for_igreja` (mesmo GUC +
    `SET LOCAL ROLE authenticated`, com bind param). Isto cobre a transação em
    andamento — cujo `after_begin` já pode ter disparado ANTES da marcação (logo
    o listener não a reaplicaria). O listener cobre as transações FUTURAS
    (leituras pós-commit).
    """
    set_tenant_context_for_igreja(session, igreja_id)


# ---------------------------------------------------------------------------
# API pública de marcação
# ---------------------------------------------------------------------------
def mark_tenant_scoped(
    session: Session,
    igreja_id: Any,
    *,
    actor_sub: str | None = None,
    actor_role: str | None = None,
    source: str,
) -> None:
    """Marca a sessão como tenant-scoped no `igreja_id` e aplica o escopo agora.

    Idempotente para o MESMO `igreja_id` (reaplica o escopo, sem erro). Re-fixar
    em outro tenant levanta `TenantPinConflictError` (D1). Marcar uma sessão já
    `mark_cross_tenant` é mutuamente exclusivo → erro. `igreja_id` None/vazio →
    `ValueError` (recusa na entrada, não marca).

    Args:
        session: sessão SQLAlchemy a escopar.
        igreja_id: tenant alvo (uuid; coagido a str).
        actor_sub: (opcional) subject Clerk que originou a marcação (auditoria).
        actor_role: (opcional) papel do ator (auditoria).
        source: rótulo obrigatório da origem da marcação (ex.: "http", "worker").
    """
    igreja_id = _normalize_igreja_id(igreja_id)
    info = session.info

    if info.get(CROSS_TENANT_KEY):
        raise TenantPinConflictError(
            "sessão marcada como cross-tenant não pode virar tenant-scoped "
            "(modos mutuamente exclusivos); use promote_to_tenant"
        )

    existing = info.get(TENANT_IGREJA_KEY)
    if existing is not None and existing != igreja_id:
        raise TenantPinConflictError(
            f"sessão já fixada no tenant {existing!r}; recusa re-fixar em "
            f"{igreja_id!r} (pinning, D1)"
        )

    if existing is None:
        info[TENANT_IGREJA_KEY] = igreja_id
        info[TENANT_META_KEY] = {
            "source": source,
            "actor_sub": actor_sub,
            "actor_role": actor_role,
            "cross_tenant": False,
        }
    # Idempotente para o mesmo tenant: reaplica o escopo (garante a transação
    # atual escopada) sem tocar a meta original.
    _apply_scope_now(session, igreja_id)


def mark_cross_tenant(
    session: Session,
    *,
    actor_sub: str | None = None,
    source: str,
) -> None:
    """Marca a sessão como cross-tenant (unscoped) — saída explícita nomeada (D4).

    Garante que NENHUM `igreja_id` fica em `session.info`, de modo que o listener
    `after_begin` seja um no-op e a sessão siga no papel de conexão (BYPASSRLS).
    Só deve ser usada em caminhos deliberadamente cross-tenant (ex.: console de
    plataforma, resolução de igreja por instância no worker antes de escopar).

    Marcar cross-tenant uma sessão JÁ pinada num tenant é mutuamente exclusivo →
    `TenantPinConflictError`.
    """
    info = session.info

    if info.get(TENANT_IGREJA_KEY) is not None:
        raise TenantPinConflictError(
            "sessão já fixada num tenant não pode virar cross-tenant "
            "(modos mutuamente exclusivos)"
        )

    # Idempotente: remarca cross-tenant sem erro. Garante ausência do igreja key
    # (defensivo — o pin acima já garante que não estava presente).
    info.pop(TENANT_IGREJA_KEY, None)
    info[CROSS_TENANT_KEY] = True
    info[TENANT_META_KEY] = {
        "source": source,
        "actor_sub": actor_sub,
        "cross_tenant": True,
    }


def promote_to_tenant(
    session: Session,
    igreja_id: Any,
    *,
    source: str,
) -> None:
    """Promove uma sessão cross-tenant para tenant-scoped (D4).

    Só é válido se a sessão estava EXPLICITAMENTE `mark_cross_tenant`; caso
    contrário levanta `TenantPromotionError` (não se promove uma sessão não
    marcada nem uma já pinada). Após promover, o listener passa a reaplicar o
    escopo do `igreja_id` em toda transação futura.
    """
    igreja_id = _normalize_igreja_id(igreja_id)
    info = session.info

    if info.get(TENANT_IGREJA_KEY) is not None:
        raise TenantPromotionError(
            "sessão já está pinada num tenant; promote_to_tenant exige uma "
            "sessão previamente marcada como cross-tenant"
        )
    if not info.get(CROSS_TENANT_KEY):
        raise TenantPromotionError(
            "promote_to_tenant só é válido após mark_cross_tenant"
        )

    info.pop(CROSS_TENANT_KEY, None)
    info[TENANT_IGREJA_KEY] = igreja_id
    info[TENANT_META_KEY] = {
        "source": source,
        "cross_tenant": False,
        "promoted_from_cross_tenant": True,
    }
    _apply_scope_now(session, igreja_id)


# ---------------------------------------------------------------------------
# Listener after_begin (D2) — fail-closed, registrado uma única vez
# ---------------------------------------------------------------------------
def _reapply_tenant_scope(
    session: Session,
    transaction: SessionTransaction,
    connection: Connection,
) -> None:
    """Reaplica o escopo do tenant em cada `BEGIN` de uma sessão marcada.

    No-op quando `session.info` não tem `TENANT_IGREJA_KEY` (sessão não-marcada
    ou cross-tenant explícito). Quando marcado, reafirma o GUC
    `app.tenant_igreja_id` + `set local role authenticated`, ambos
    transaction-local (`set_config is_local=true` / `SET LOCAL`).

    Usa `connection.exec_driver_sql` (NÃO `session.execute`) de propósito: emitir
    via ORM aqui reentraria no ciclo de transação (o próprio `after_begin`). O
    `igreja_id` vai como PARÂMETRO de bind (anti-injeção); a semântica do SQL é a
    mesma de `set_tenant_context_for_igreja` (rls.py) — a única diferença é o
    placeholder de bind (%s do driver × :nome do SQLAlchemy).

    Fail-closed: qualquer falha (ex.: papel `authenticated` inexistente) PROPAGA
    e derruba a transação. Proibido capturar-e-continuar.
    """
    igreja_id = session.info.get(TENANT_IGREJA_KEY)
    if not igreja_id:
        return  # no-op: sessão não-marcada ou cross-tenant explícito

    connection.exec_driver_sql(
        "select set_config('app.tenant_igreja_id', %s, true)",
        (str(igreja_id),),
    )
    connection.exec_driver_sql("set local role authenticated")


def register_after_begin_listener(target: Any = Session) -> None:
    """Registra o listener `after_begin` do seam UMA única vez.

    Idempotente: chamadas repetidas (ou re-import do módulo) não empilham cópias
    do handler — `event.contains` evita duplicação. Chamado no import de
    `session.py` para que o seam esteja ativo assim que o pool de sessões existe.
    """
    if not event.contains(target, "after_begin", _reapply_tenant_scope):
        event.listen(target, "after_begin", _reapply_tenant_scope)
