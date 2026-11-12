"""Atribuição de uma conversa a um usuário com acesso ao inbox.

Serviço único do caminho humano (``POST /conversations/{id}/transfer``) e do
encaminhamento automático de dúvida sem resposta oficial (decisão 21). O caller
já trava a conversa (FOR UPDATE), autoriza quem pede e faz o commit.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import AppUser, Conversation, UserRole
from app.domain.conversations import can_access_inbox
from app.services.conversation_handoff import fence_agent_replies_for_handoff


class AssignmentTargetNotFound(LookupError):
    """Destino inexistente, inativo ou de outra igreja."""


class AssignmentTargetWithoutInbox(PermissionError):
    """Destino ativo, mas sem papel com acesso ao inbox."""


def assign_conversation_locked(
    session: Session,
    *,
    conversation: Conversation,
    target_user_id: uuid.UUID,
    igreja_id: uuid.UUID,
) -> AppUser:
    """Coloca a conversa sob controle humano do destino, revalidando-o agora.

    ``igreja_id`` é a igreja de quem pede (servidor) e precisa ser a da conversa.
    O destino precisa ser usuário ativo da MESMA igreja da conversa e ter papel
    com acesso ao inbox. Respostas do agente ainda não enviadas são cercadas.
    """
    igreja_id = uuid.UUID(str(igreja_id))
    if uuid.UUID(str(conversation.igreja_id)) != igreja_id:
        # Defesa além da RLS: conversa de outra igreja nunca é atribuída.
        raise AssignmentTargetNotFound("conversa de outra igreja")
    target = session.execute(
        select(AppUser).where(
            AppUser.id == target_user_id,
            AppUser.igreja_id == igreja_id,
            or_(AppUser.status.is_(None), AppUser.status == "ativo"),
        )
    ).scalar_one_or_none()
    if target is None:
        raise AssignmentTargetNotFound("destino não encontrado")
    roles = session.execute(
        select(UserRole.papel).where(
            UserRole.user_id == target_user_id,
            UserRole.igreja_id == igreja_id,
        )
    ).scalars().all()
    if not can_access_inbox(roles):
        raise AssignmentTargetWithoutInbox("destino sem acesso ao inbox")

    conversation.estado = "humano"
    conversation.assumido_por = target_user_id
    conversation.assumido_em = dt.datetime.now(dt.timezone.utc)
    conversation.espera_desde = None
    fence_agent_replies_for_handoff(
        session,
        igreja_id=igreja_id,
        conversation_id=conversation.id,
    )
    return target
