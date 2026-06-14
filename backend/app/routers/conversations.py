"""Conversations router — inbox listing and IA/human handoff (US-11..US-13).

Endpoints:
  - GET  /conversations                list the tenant's conversations
  - POST /conversations/{id}/handoff   switch control between IA and human

Access (US-11): the inbox is restricted to privileged roles (admin implicitly,
plus pastor / lider_g12). Cell leaders receive 403 — enforced by require_role,
which already grants admin implicit access and unions accumulated roles.

Handoff concurrency (US-12): the conversation row is locked FOR UPDATE; if a
human already assumed it, a second "assume" returns 409 carrying the real
`assumido_por` so the UI reflects who actually holds it.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.models import Conversation
from app.db.session import get_db
from app.deps import CurrentUser, require_role
from app.domain.conversations import resolve_handoff
from app.routers._common import Page, PaginationParams, ensure_tenant_context

logger = logging.getLogger("pastorai.conversations")

router = APIRouter(prefix="/conversations", tags=["conversations"])

# Privileged inbox roles (admin passes implicitly via require_role).
_INBOX_ROLES = ["pastor", "lider_g12"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ConversationOut(BaseModel):
    id: str
    telefone: str
    pessoaId: str | None = None  # noqa: N815
    estado: str | None = None
    ultimaMensagem: str | None = None  # noqa: N815
    naoLidas: int  # noqa: N815
    assumidoPor: str | None = None  # noqa: N815
    assumidoEm: str | None = None  # noqa: N815
    esperaDesde: str | None = None  # noqa: N815

    @classmethod
    def from_model(cls, c: Conversation) -> "ConversationOut":
        return cls(
            id=str(c.id),
            telefone=c.telefone,
            pessoaId=str(c.pessoa_id) if c.pessoa_id else None,
            estado=c.estado,
            ultimaMensagem=c.ultima_mensagem,
            naoLidas=c.nao_lidas or 0,
            assumidoPor=str(c.assumido_por) if c.assumido_por else None,
            assumidoEm=c.assumido_em.isoformat() if c.assumido_em else None,
            esperaDesde=c.espera_desde.isoformat() if c.espera_desde else None,
        )


class HandoffRequest(BaseModel):
    to: Literal["human", "ia"]


class HandoffResponse(BaseModel):
    estado: str
    assumidoPor: str | None = None  # noqa: N815


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("", response_model=Page[ConversationOut])
def list_conversations(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(_INBOX_ROLES)),
) -> Page[ConversationOut]:
    """List tenant conversations (estado, última mensagem, não lidas, fila)."""
    ensure_tenant_context(db, current_user)

    total = db.execute(
        select(func.count()).select_from(Conversation)
    ).scalar_one()
    rows = db.execute(
        select(Conversation)
        # Human-queue first (espera_desde set), then most recently updated.
        .order_by(
            Conversation.espera_desde.asc().nulls_last(),
            desc(Conversation.updated_at),
        )
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).scalars().all()

    return Page[ConversationOut](
        items=[ConversationOut.from_model(c) for c in rows],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


@router.post("/{conversation_id}/handoff", response_model=HandoffResponse)
def handoff(
    conversation_id: str,
    payload: HandoffRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(_INBOX_ROLES)),
) -> HandoffResponse:
    """Switch a conversation between IA and human control (US-12/US-13)."""
    ensure_tenant_context(db, current_user)

    target = resolve_handoff(payload.to)
    conv = _get_conversation_for_update(db, conversation_id)

    current_holder = str(conv.assumido_por) if conv.assumido_por else None

    if target.assumes:
        # Concurrency guard: someone else already holds this conversation.
        if conv.estado == "humano" and current_holder not in (
            None,
            current_user.app_user_id,
        ):
            raise _conflict(conv)

        conv.estado = target.estado
        conv.assumido_por = uuid.UUID(current_user.app_user_id)
        conv.assumido_em = dt.datetime.now(dt.timezone.utc)
        # Leaving the waiting queue once a human takes over.
        conv.espera_desde = None
    else:  # release back to IA
        conv.estado = target.estado
        conv.assumido_por = None
        conv.assumido_em = None

    db.flush()
    db.refresh(conv)
    db.commit()

    return HandoffResponse(
        estado=conv.estado or target.estado,
        assumidoPor=str(conv.assumido_por) if conv.assumido_por else None,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversa não encontrada"
        ) from exc


def _get_conversation_for_update(db: Session, conversation_id: str) -> Conversation:
    conv = db.execute(
        select(Conversation)
        .where(Conversation.id == _parse_uuid(conversation_id))
        .with_for_update()
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversa não encontrada"
        )
    return conv


def _conflict(conv: Conversation) -> HTTPException:
    """Build a 409 carrying the conversation's real holder (stale)."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error": "already_assumed",
            "message": "Conversa já foi assumida por outro usuário",
            "estado": conv.estado,
            "assumidoPor": str(conv.assumido_por) if conv.assumido_por else None,
        },
    )
