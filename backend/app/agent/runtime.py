"""Agent runtime: bind the orchestrator graph to the database and BYO LLM.

This is the single place that turns an inbound WhatsApp message into the
orchestrator's one reply (delta-034). It:

  1. Loads the conversation, person, igreja config and the BYO LLM credential.
  2. Refuses to operate without a validated+active credential (US-27): the
     agent never runs on an unconfigured/invalid key.
  3. Runs one orchestrator turn (LangGraph) to pick a sub-agent and draft a
     reply, then applies the side effects with the *same* validations a human
     uses (tools), persisting consent/opt-out and writing the AI audit logs.
  4. Optionally refines the reply via the igreja's LLM, recording token/cost
     usage; on any LLM error it falls back to the deterministic draft.

It does NOT send the message itself; it returns the single reply so the caller
(worker) emits it through the official number — preserving the one-exit rule.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.graph import run_turn
from app.agent.masking import log_agent_event, log_ai_usage
from app.agent.nodes import ROUTE_HANDOFF, AgentState
from app.agent.tools import TOOLS, ToolError
from app.config import get_settings
from app.db.models import (
    AgentConfig,
    Conversation,
    ConsentRecord,
    Igreja,
    LlmCredential,
    Pessoa,
)
from app.services.crypto import SecretDecryptionError, decrypt_secret
from app.services.llm import LLMClient, LLMError

logger = logging.getLogger("pastorai.agent.runtime")


@dataclass
class AgentTurnResult:
    """Outcome of one orchestrator turn."""

    handled: bool
    route: str | None = None
    response: str | None = None
    suppressed: bool = False  # True when a human owns the chat (handoff)
    tools_executed: list[str] = field(default_factory=list)
    reason: str | None = None


def _active_credential(session: Session, igreja_id: uuid.UUID) -> LlmCredential | None:
    cred = session.execute(
        select(LlmCredential).where(LlmCredential.igreja_id == igreja_id)
    ).scalar_one_or_none()
    if cred is None or not cred.validado or not cred.ativo:
        return None
    return cred


def _latest_consent_version(
    session: Session, igreja_id: uuid.UUID, pessoa_id: uuid.UUID
) -> str | None:
    row = session.execute(
        select(ConsentRecord)
        .where(
            ConsentRecord.igreja_id == igreja_id,
            ConsentRecord.pessoa_id == pessoa_id,
        )
        .order_by(ConsentRecord.aceite_em.desc().nullslast())
        .limit(1)
    ).scalar_one_or_none()
    return row.termo_versao if row else None


def _build_state(
    *,
    igreja_id: uuid.UUID,
    igreja_nome: str | None,
    conversation: Conversation,
    pessoa: Pessoa,
    texto: str | None,
    accepted_version: str | None,
    current_version: str,
) -> AgentState:
    return {
        "igreja_id": str(igreja_id),
        "igreja_nome": igreja_nome,
        "conversation_id": str(conversation.id),
        "pessoa_id": str(pessoa.id),
        "texto": texto or "",
        "estado": conversation.estado or "ia",
        "pessoa": {
            "id": str(pessoa.id),
            "nome": pessoa.nome,
            "telefone": pessoa.telefone,
            "tipo": pessoa.tipo or "visitante",
            "etapa": pessoa.etapa or "ganhar",
            "origem": pessoa.origem or "",
            "has_endereco": bool(pessoa.endereco),
            "primeiro_contato_set": pessoa.primeiro_contato is not None,
        },
        "term_accepted_version": accepted_version,
        "term_current_version": current_version,
        "events": [],
        "tool_calls": [],
    }


def _apply_intake(pessoa: Pessoa, update: dict) -> None:
    """Backfill person basics produced by the intake sub-agent (US-09)."""
    if update.get("origem") and not pessoa.origem:
        pessoa.origem = update["origem"]
    if update.get("set_primeiro_contato") and pessoa.primeiro_contato is None:
        pessoa.primeiro_contato = dt.datetime.now(dt.timezone.utc)


def _apply_optout(pessoa: Pessoa, igreja_id: uuid.UUID, session: Session, current_version: str) -> None:
    """Set opt-out and record the withdrawal (US-32/RNF-06)."""
    pessoa.optout = True
    session.add(
        ConsentRecord(
            igreja_id=igreja_id,
            pessoa_id=pessoa.id,
            termo_versao=f"optout:{current_version}",
            aceite_em=dt.datetime.now(dt.timezone.utc),
        )
    )


def _apply_consent(
    pessoa: Pessoa, igreja_id: uuid.UUID, session: Session, version: str
) -> None:
    """Persist a consent acceptance at `version` (delta-040)."""
    pessoa.consentimento = True
    session.add(
        ConsentRecord(
            igreja_id=igreja_id,
            pessoa_id=pessoa.id,
            termo_versao=version,
            aceite_em=dt.datetime.now(dt.timezone.utc),
        )
    )


def _execute_tools(
    session: Session, igreja_id: uuid.UUID, tool_calls: list[dict]
) -> tuple[list[str], list[dict]]:
    """Run the tool calls emitted by a sub-agent with human-equivalent rules."""
    executed: list[str] = []
    audit: list[dict] = []
    for call in tool_calls:
        name = call.get("ferramenta")
        fn = TOOLS.get(name)
        if fn is None:
            logger.warning("Unknown tool requested by agent: %s", name)
            continue
        args = dict(call.get("args") or {})
        try:
            result = fn(session, igreja_id=igreja_id, **args)
            executed.append(name)
            audit.append(
                {"evento": "tool_call", "payload": {"ferramenta": name, "detalhe": result.detalhe}}
            )
        except ToolError as exc:
            audit.append(
                {"evento": "tool_error", "payload": {"ferramenta": name, "erro": str(exc)}}
            )
            logger.info("Tool %s refused: %s", name, exc)
    return executed, audit


def _refine_with_llm(
    cred: LlmCredential, model: str, draft: str, user_text: str, comportamento: str | None
) -> tuple[str, object] | None:
    """Phrase the final reply via the BYO LLM; None on any failure."""
    try:
        api_key = decrypt_secret(cred.api_key_encrypted)
    except SecretDecryptionError:
        logger.error("Failed to decrypt LLM credential; using deterministic reply")
        return None
    try:
        client = LLMClient(cred.provedor, api_key, model)
        system = (
            "Você é o assistente pastoral de uma igreja no WhatsApp. "
            "Responda em português brasileiro, de forma acolhedora e breve. "
            + (comportamento or "")
            + " Use a intenção desta resposta-base sem inventar fatos: "
            + draft
        )
        result = client.complete(system, user_text or draft)
        texto = result.texto or draft
        return texto, result.usage
    except LLMError:
        logger.exception("BYO LLM call failed; using deterministic reply")
        return None


def process_inbound_message(
    session: Session, *, conversation_id: str | uuid.UUID, texto: str | None
) -> AgentTurnResult:
    """Run one orchestrator turn for an inbound message and apply side effects.

    The caller commits the session and sends `response` via the official number.
    """
    settings = get_settings()
    conv_uuid = conversation_id if isinstance(conversation_id, uuid.UUID) else uuid.UUID(str(conversation_id))

    conversation = session.execute(
        select(Conversation).where(Conversation.id == conv_uuid)
    ).scalar_one_or_none()
    if conversation is None or conversation.pessoa_id is None:
        return AgentTurnResult(handled=False, reason="conversation_not_found")

    igreja_id = conversation.igreja_id
    pessoa = session.execute(
        select(Pessoa).where(Pessoa.id == conversation.pessoa_id)
    ).scalar_one_or_none()
    if pessoa is None:
        return AgentTurnResult(handled=False, reason="pessoa_not_found")

    # US-27: the agent does not operate without a validated, active credential.
    cred = _active_credential(session, igreja_id)
    if cred is None:
        log_agent_event(
            session,
            igreja_id=igreja_id,
            evento="agent_skipped_no_credential",
            payload={"conversationId": str(conv_uuid)},
            conversation_id=conv_uuid,
        )
        session.commit()
        return AgentTurnResult(handled=False, reason="no_credential")

    igreja = session.execute(
        select(Igreja).where(Igreja.id == igreja_id)
    ).scalar_one_or_none()
    config = session.execute(
        select(AgentConfig).where(AgentConfig.igreja_id == igreja_id)
    ).scalar_one_or_none()

    accepted_version = _latest_consent_version(session, igreja_id, pessoa.id)
    state = _build_state(
        igreja_id=igreja_id,
        igreja_nome=igreja.nome if igreja else None,
        conversation=conversation,
        pessoa=pessoa,
        texto=texto,
        accepted_version=accepted_version,
        current_version=settings.agent_term_version,
    )

    final = run_turn(state)
    route = final.get("route")

    # Apply person backfill from intake (origem / primeiro_contato).
    _apply_intake(pessoa, final.get("intake_update") or {})

    # Consent / opt-out persistence.
    if final.get("apply_optout"):
        _apply_optout(pessoa, igreja_id, session, settings.agent_term_version)
    if final.get("apply_consent_version"):
        _apply_consent(pessoa, igreja_id, session, final["apply_consent_version"])

    # Execute tool calls (human-equivalent validations, tenant-scoped).
    executed, tool_audit = _execute_tools(
        session, igreja_id, final.get("tool_calls") or []
    )

    # Audit every routing/sub-agent event + tool calls (masked payloads).
    for ev in (final.get("events") or []) + tool_audit:
        log_agent_event(
            session,
            igreja_id=igreja_id,
            evento=ev.get("evento", "agent_event"),
            payload=ev.get("payload"),
            conversation_id=conv_uuid,
        )

    # Handoff: suppress the automatic reply (human owns the chat).
    if route == ROUTE_HANDOFF:
        session.commit()
        return AgentTurnResult(
            handled=True, route=route, response=None, suppressed=True,
            tools_executed=executed,
        )

    response = final.get("response")
    model = settings.agent_default_model

    # Refine the deterministic draft via the BYO LLM and log usage (RNF-24).
    if response:
        refined = _refine_with_llm(
            cred, model, response, texto or "", config.comportamento if config else None
        )
        if refined is not None:
            response, usage = refined
            log_ai_usage(session, igreja_id=igreja_id, usage=usage, ferramenta=route)

    session.commit()
    return AgentTurnResult(
        handled=True,
        route=route,
        response=response,
        suppressed=False,
        tools_executed=executed,
    )
