"""Panel assistant service (api-assistant — O5).

This is the **web panel assistant**, a separate channel from the WhatsApp
Orchestrator (delta-034): different actor, audience and entry point. It answers a
logged-in panel user, is aware of their role/tenant, and suggests only the
screens the role may open (`app.domain.assistant`).

It reuses the igreja's BYO LLM credential (encrypted at rest, US-27/RNF-03) to
phrase the reply. With no validated+active credential it degrades gracefully to a
deterministic answer instead of failing — the screen suggestions, which are the
security-relevant output, are always computed deterministically.

The service performs no WhatsApp I/O and never touches the orchestrator graph.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AgentConfig, LlmCredential, RolePermission
from app.domain.assistant import allowed_screens_for_roles, suggest_screens
from app.services.crypto import SecretDecryptionError, decrypt_secret
from app.services.llm import LLMClient, LLMError

logger = logging.getLogger("pastorai.assistant")


@dataclass
class AssistantResult:
    """Outcome of one panel-assistant turn."""

    resposta: str
    telas_sugeridas: list[str] = field(default_factory=list)
    llm_used: bool = False


def _role_permission_map(session: Session, igreja_id: uuid.UUID) -> dict[str, list[str]]:
    """Project role_permissions into {papel: [tela, ...]} for the igreja."""
    rows = session.execute(
        select(RolePermission.papel, RolePermission.tela).where(
            RolePermission.igreja_id == igreja_id
        )
    ).all()
    mapping: dict[str, list[str]] = {}
    for papel, tela in rows:
        mapping.setdefault(papel, []).append(tela)
    return mapping


def _active_credential(session: Session, igreja_id: uuid.UUID) -> LlmCredential | None:
    cred = session.execute(
        select(LlmCredential).where(LlmCredential.igreja_id == igreja_id)
    ).scalar_one_or_none()
    if cred is None or not cred.validado or not cred.ativo:
        return None
    return cred


def _fallback_reply(telas: list[str]) -> str:
    """Deterministic answer used when the LLM is unavailable."""
    if telas:
        nomes = ", ".join(telas)
        return (
            "Posso te ajudar com isso. Telas sugeridas para o seu acesso: "
            f"{nomes}."
        )
    return (
        "Posso te ajudar a navegar no painel. Me diga o que você precisa fazer "
        "(ex.: ver pendências, consolidação, relatórios)."
    )


def _phrase_with_llm(
    cred: LlmCredential,
    model: str,
    texto: str,
    telas: list[str],
    comportamento: str | None,
) -> str | None:
    """Phrase the reply via the BYO LLM; returns None on any failure."""
    try:
        api_key = decrypt_secret(cred.api_key_encrypted)
    except SecretDecryptionError:
        logger.error("Failed to decrypt LLM credential; using deterministic reply")
        return None
    try:
        client = LLMClient(cred.provedor, api_key, model)
        system = (
            "Você é o assistente do PAINEL WEB de uma igreja (não é o atendimento "
            "do WhatsApp). Responda em português brasileiro, de forma objetiva e "
            "cordial, orientando o usuário a usar o painel. "
            + (comportamento or "")
            + (
                " Quando útil, mencione estas telas permitidas ao usuário: "
                + ", ".join(telas)
                if telas
                else ""
            )
            + " Não invente telas fora desta lista."
        )
        result = client.complete(system, texto)
        return result.texto or None
    except LLMError:
        logger.exception("Panel assistant LLM call failed; using deterministic reply")
        return None


def answer_panel_message(
    session: Session,
    *,
    igreja_id: str | uuid.UUID,
    roles: list[str],
    texto: str,
) -> AssistantResult:
    """Produce the panel assistant reply + role-filtered screen suggestions.

    The screen suggestions are always computed from `role_permissions` filtered
    to the caller's roles (never trusting client-claimed access). The reply text
    is phrased by the BYO LLM when available, else a deterministic fallback.
    """
    settings = get_settings()
    igreja_uuid = igreja_id if isinstance(igreja_id, uuid.UUID) else uuid.UUID(str(igreja_id))

    role_map = _role_permission_map(session, igreja_uuid)
    allowed = allowed_screens_for_roles(role_map, roles)
    telas = suggest_screens(texto, allowed)

    cred = _active_credential(session, igreja_uuid)
    if cred is None:
        return AssistantResult(resposta=_fallback_reply(telas), telas_sugeridas=telas)

    config = session.execute(
        select(AgentConfig).where(AgentConfig.igreja_id == igreja_uuid)
    ).scalar_one_or_none()

    phrased = _phrase_with_llm(
        cred,
        settings.assistant_default_model,
        texto,
        telas,
        config.comportamento if config else None,
    )
    if phrased is None:
        return AssistantResult(resposta=_fallback_reply(telas), telas_sugeridas=telas)

    return AssistantResult(resposta=phrased, telas_sugeridas=telas, llm_used=True)
