"""Decisão 21 (12/11/2026): dúvida sem resposta no conhecimento oficial.

A dúvida vai ao responsável configurado do setor ``conhecimento_oficial``
(``responsabilidades_setor``, gerido por pastor/admin no painel). Sem
responsável vigente, ou quando ele não pode receber conversas, a conversa entra
na fila humana comum, atendida pelo admin (e pelo pastor, de visão completa).
Escalar é a transferência humana já existente, do responsável para o admin.

A responsabilidade não concede acesso: o destino só recebe a conversa se for
usuário ativo da igreja com papel de inbox (mesmo serviço da transferência).
O caller trava a conversa e faz o commit.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.datas import hoje_da_igreja
from app.db.models import AppUser, Conversation
from app.services.conversation_assignment import (
    AssignmentTargetNotFound,
    AssignmentTargetWithoutInbox,
    assign_conversation_locked,
)
from app.services.conversation_handoff import mark_conversation_for_handoff_locked
from app.services.responsabilidades import vigentes_em

logger = logging.getLogger(__name__)

SETOR_CONHECIMENTO = "conhecimento_oficial"
ROTA_RESPONSAVEL = "responsavel_setor"
ROTA_FILA_ADMIN = "fila_admin"
ROTA_JA_ASSUMIDA = "ja_assumida"


def _responsible_user_id(session: Session, igreja_id: uuid.UUID) -> uuid.UUID | None:
    rows = vigentes_em(
        session, igreja_id=igreja_id, em=hoje_da_igreja(), setor=SETOR_CONHECIMENTO
    )
    if len(rows) != 1:
        return None
    users = session.execute(
        select(AppUser.id).where(
            AppUser.igreja_id == igreja_id,
            AppUser.pessoa_id == rows[0]["pessoa_id"],
            or_(AppUser.status.is_(None), AppUser.status == "ativo"),
        ).limit(2)
    ).scalars().all()
    return users[0] if len(users) == 1 else None


def route_unanswered_question_locked(
    session: Session, *, conversation: Conversation
) -> str:
    """Encaminha a conversa travada e devolve a rota escolhida (sem PII)."""
    if conversation.estado == "humano" and conversation.assumido_por is not None:
        # Alguém já atende: não troca o dono da conversa.
        return ROTA_JA_ASSUMIDA
    target = _responsible_user_id(session, conversation.igreja_id)
    if target is not None:
        # O serviço valida o destino antes de alterar a conversa.
        try:
            assign_conversation_locked(
                session, conversation=conversation, target_user_id=target
            )
        except (AssignmentTargetNotFound, AssignmentTargetWithoutInbox):
            logger.info("conhecimento: responsável do setor sem inbox; fila comum")
        else:
            return ROTA_RESPONSAVEL
    mark_conversation_for_handoff_locked(session, conversation=conversation)
    return ROTA_FILA_ADMIN
