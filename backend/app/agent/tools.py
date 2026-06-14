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
from sqlalchemy.orm import Session

from app.db.models import Celula, Decision, Pessoa
from app.domain.consolidation import (
    CONNECTION_DEADLINE_HOURS,
    VALID_VINCULOS,
    VINCULO_VISITANTE,
)
from app.domain.pipeline import validate_transition


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
    session.add(decision)
    pessoa.aceitou_jesus = True
    session.flush()  # fires trg_decision_opens_consolidation

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
