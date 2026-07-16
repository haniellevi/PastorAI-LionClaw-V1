"""Agent tools — the same business functions/validations a human uses (F5).

The orchestrator and its sub-agents never bypass the rules enforced for panel
users: each tool re-applies the exact validations of its HTTP counterpart and
operates strictly within the caller's tenant (`igreja_id`). State-machine side
effects are delegated to the database triggers (decision -> consolidation,
presence/cell-link -> promotion), mirroring the routers.

Tools are tenant-scoped pure functions over a Session: they flush so triggers
fire and return a small result dict, but they do NOT commit — the caller owns
the transaction (so tool calls + audit logs land together).
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Celula, Decision, Pessoa
from app.domain.consolidation import (
    CONNECTION_DEADLINE_HOURS,
    VALID_VINCULOS,
    VINCULO_VISITANTE,
)
from app.domain.pipeline import validate_transition
from app.services.celula_membro import (
    MembroInelegivelError,
    TransferenciaNaoAutorizadaError,
    assert_membro_elegivel,
    ensure_active_membro,
)

# Postgres SQLSTATE de unique_violation. Só ele é traduzido para ToolError em
# registrar_decisao; outras violações de integridade sobem (não são um refusal
# de validação, e sim um erro inesperado).
_PG_UNIQUE_VIOLATION = "23505"


class ToolError(Exception):
    """A tool refused to act because a human-equivalent validation failed."""


@dataclass(frozen=True)
class ToolResult:
    """Outcome of a tool invocation (also fed to the AI audit log)."""

    ferramenta: str
    ok: bool
    detalhe: dict[str, Any]


def _as_uuid(value: str | uuid.UUID) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _load_pessoa(session: Session, igreja_id: uuid.UUID, pessoa_id: uuid.UUID) -> Pessoa:
    """Load a person within the tenant or raise ToolError (tenant isolation)."""
    pessoa = session.execute(
        select(Pessoa).where(
            Pessoa.id == pessoa_id, Pessoa.igreja_id == igreja_id
        )
    ).scalar_one_or_none()
    if pessoa is None:
        raise ToolError("Pessoa não encontrada no escopo da igreja")
    return pessoa


def registrar_decisao(
    session: Session,
    *,
    igreja_id: str | uuid.UUID,
    pessoa_id: str | uuid.UUID,
    vinculo: str,
    origem: str | None = None,
    celula_id: str | uuid.UUID | None = None,
) -> ToolResult:
    """Register a decision for Jesus (mirrors POST /consolidacao/decisao).

    Inserting the decision fires trg_decision_opens_consolidation, which opens
    the consolidation (and a 24h connect item for the visitante flow).
    """
    igreja_uuid = _as_uuid(igreja_id)
    pessoa = _load_pessoa(session, igreja_uuid, _as_uuid(pessoa_id))

    vinculo_norm = (vinculo or "").strip().lower()
    if vinculo_norm not in VALID_VINCULOS:
        raise ToolError(f"vinculo inválido: {vinculo}")

    celula_uuid: uuid.UUID | None = None
    if celula_id is not None:
        celula_uuid = _as_uuid(celula_id)
        celula = session.execute(
            select(Celula).where(
                Celula.id == celula_uuid, Celula.igreja_id == igreja_uuid
            )
        ).scalar_one_or_none()
        if celula is None:
            raise ToolError("Célula não encontrada no escopo da igreja")

    prazo_conexao: dt.datetime | None = None
    if vinculo_norm == VINCULO_VISITANTE:
        prazo_conexao = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
            hours=CONNECTION_DEADLINE_HOURS
        )

    decision = Decision(
        igreja_id=igreja_uuid,
        pessoa_id=pessoa.id,
        origem=origem,
        vinculo=vinculo_norm,
        celula_id=celula_uuid,
        prazo_conexao=prazo_conexao,
    )
    # PR#179 review: `session` here is the SHARED, per-turn session owned by
    # app/agent/runtime.py::process_inbound_message — by the time this tool
    # runs, _apply_intake/_apply_consent/_apply_optout (and any earlier tool
    # call in the same turn) may already have pending, unflushed mutations on
    # THIS session. Flush them into the OUTER transaction now, BEFORE opening
    # the SAVEPOINT below: session.flush() flushes the whole unit of work, not
    # just this function's objects, so anything still pending would otherwise
    # be swept into the SAME flush as the Decision insert and be undone by a
    # ROLLBACK TO SAVEPOINT if that insert hits unique_violation.
    session.flush()
    try:
        # CONSOL-1 + savepoint fix: only the Decision insert (and the
        # trigger's consolidacoes/consolidacao_etapas/work_queue_items side
        # effects) run inside this SAVEPOINT. On unique_violation, ROLLBACK TO
        # SAVEPOINT undoes only THIS block — the outer transaction (and
        # anything flushed above) stays open and intact for the runtime's own
        # later commit.
        with session.begin_nested():
            session.add(decision)
            pessoa.aceitou_jesus = True
            session.flush()  # fires trg_decision_opens_consolidation
    except IntegrityError as exc:
        # TOCTOU — two concurrent decisions for the SAME pessoa both fire
        # trg_decision_opens_consolidation; uq_consolidacoes_pessoa_aberta
        # (partial unique on pessoa_id where concluida=false AND
        # abandonada_em IS NULL) serializes them. The 2nd to commit gets
        # unique_violation, translated DETERMINISTICALLY to ToolError (mirrors
        # the HTTP 409 in app/routers/consolidacao.py). NO session.rollback()
        # here — that would abort the whole shared per-turn transaction (the
        # bug this fix closes). Any other integrity error (not unique) bubbles
        # up unchanged — not a validation refusal.
        if getattr(exc.orig, "pgcode", None) == _PG_UNIQUE_VIOLATION:
            raise ToolError("Pessoa já possui uma consolidação em aberto") from exc
        raise

    return ToolResult(
        ferramenta="registrar_decisao",
        ok=True,
        detalhe={
            "pessoaId": str(pessoa.id),
            "vinculo": vinculo_norm,
            "decisionId": str(decision.id),
        },
    )


def marcar_presenca(
    session: Session,
    *,
    igreja_id: str | uuid.UUID,
    pessoa_id: str | uuid.UUID,
    quantidade: int = 1,
) -> ToolResult:
    """Record cell attendance (feeds F2: trg_promote_pipeline auto-promotes)."""
    if quantidade < 1:
        raise ToolError("quantidade de presença deve ser >= 1")
    igreja_uuid = _as_uuid(igreja_id)
    pessoa = _load_pessoa(session, igreja_uuid, _as_uuid(pessoa_id))

    pessoa.presencas_celula = (pessoa.presencas_celula or 0) + quantidade
    session.flush()  # fires trg_promote_pipeline when criteria are met

    return ToolResult(
        ferramenta="marcar_presenca",
        ok=True,
        detalhe={
            "pessoaId": str(pessoa.id),
            "presencasCelula": pessoa.presencas_celula,
        },
    )


def vincular_celula(
    session: Session,
    *,
    igreja_id: str | uuid.UUID,
    pessoa_id: str | uuid.UUID,
    celula_id: str | uuid.UUID,
) -> ToolResult:
    """Link a person to an active, led cell (mirrors POST /contacts/{id}/cell)."""
    igreja_uuid = _as_uuid(igreja_id)
    pessoa = _load_pessoa(session, igreja_uuid, _as_uuid(pessoa_id))

    celula = session.execute(
        select(Celula).where(
            Celula.id == _as_uuid(celula_id), Celula.igreja_id == igreja_uuid
        )
    ).scalar_one_or_none()
    if celula is None:
        raise ToolError("Célula não encontrada no escopo da igreja")
    if not celula.ativo:
        raise ToolError("Célula inativa não pode receber contatos")
    if celula.lider_id is None:
        raise ToolError("Célula sem líder não pode receber contatos")

    # M7B-W1.2: guarda ANTES de qualquer mutação. Diferente dos caminhos HTTP (o
    # get_db faz rollback ao fechar a sessão numa exceção não tratada), o runtime
    # do agente ENGOLE o ToolError e mesmo assim comita a sessão no fim do turno —
    # então se mutássemos pessoa.celula_id / desativássemos o vínculo antigo ANTES
    # da recusa, a mutação parcial persistiria (divergência espelho↔celula_membro).
    # Recusa traduzida para ToolError (refusal limpo, não "erro inesperado").
    try:
        assert_membro_elegivel(
            session, igreja_id=igreja_uuid, celula=celula, pessoa=pessoa
        )
    except MembroInelegivelError as exc:
        raise ToolError(exc.message) from exc

    # D2: o agente NUNCA tem a capacidade de transferir — pode_transferir=False.
    # O primeiro vínculo (pessoa sem célula) segue liberado; reatribuir quem já
    # pertence a outra célula é recusado PELO DOMÍNIO antes de qualquer escrita
    # (por isso o espelho pessoa.celula_id só é tocado depois do ensure).
    try:
        ensure_active_membro(
            session,
            igreja_id=igreja_uuid,
            celula_id=celula.id,
            pessoa_id=pessoa.id,
            pode_transferir=False,
        )
    except (MembroInelegivelError, TransferenciaNaoAutorizadaError) as exc:
        raise ToolError(exc.message) from exc
    pessoa.celula_id = celula.id
    session.flush()  # fires trg_link_cell_promote

    return ToolResult(
        ferramenta="vincular_celula",
        ok=True,
        detalhe={"pessoaId": str(pessoa.id), "celulaId": str(celula.id)},
    )


def avancar_trilha(
    session: Session,
    *,
    igreja_id: str | uuid.UUID,
    pessoa_id: str | uuid.UUID,
    etapa: str,
    subetapa: str | None = None,
) -> ToolResult:
    """Advance a person's pipeline stage (mirrors PUT /pipeline validations)."""
    igreja_uuid = _as_uuid(igreja_id)
    pessoa = _load_pessoa(session, igreja_uuid, _as_uuid(pessoa_id))

    result = validate_transition(
        current_tipo=pessoa.tipo,
        current_etapa=pessoa.etapa,
        target_etapa=etapa,
        target_subetapa=subetapa,
        presencas_celula=pessoa.presencas_celula or 0,
        aceitou_jesus=pessoa.aceitou_jesus,
    )
    if not result.allowed:
        raise ToolError(result.reason or "Transição de trilha não permitida")

    pessoa.etapa = etapa
    if subetapa is not None:
        pessoa.subetapa = subetapa
    session.flush()

    return ToolResult(
        ferramenta="avancar_trilha",
        ok=True,
        detalhe={
            "pessoaId": str(pessoa.id),
            "etapa": pessoa.etapa,
            "subetapa": pessoa.subetapa,
        },
    )


# Registry exposed to the orchestrator / LangGraph tool binding.
TOOLS = {
    "registrar_decisao": registrar_decisao,
    "marcar_presenca": marcar_presenca,
    "vincular_celula": vincular_celula,
    "avancar_trilha": avancar_trilha,
}


# Whitelist de argumentos aceitos por cada tool (#10b higiene): o executor
# rejeita qualquer chave de arg fora deste conjunto ANTES do splat **args,
# evitando que um tool_call malformado/futuro injete kwargs inesperados numa
# tool mutante. igreja_id é injetado pelo runtime (não vem do tool_call).
TOOL_ARG_SCHEMA: dict[str, frozenset[str]] = {
    "registrar_decisao": frozenset({"pessoa_id", "vinculo", "origem", "celula_id"}),
    "marcar_presenca": frozenset({"pessoa_id", "quantidade"}),
    "vincular_celula": frozenset({"pessoa_id", "celula_id"}),
    "avancar_trilha": frozenset({"pessoa_id", "etapa", "subetapa"}),
}
