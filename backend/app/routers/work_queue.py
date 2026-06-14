"""Work-queue router — shared queue actions and internal messages (F5).

Endpoints:
  - GET  /work-queue                     list items the caller can resolve
  - POST /work-queue/{itemId}/action     assume/assign an item (concurrency-safe)
  - POST /work-queue/{itemId}/message    post an internal note to the contact

Role gating (delta-006): an item is only listed/actionable by roles able to
resolve its type. Concurrency: an item already assumed/resolved by another user
returns 409 with the real current state (stale), guarded by a row lock.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message, Pessoa, WorkQueueItem
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.domain.work_queue import (
    can_resolve,
    format_internal_message,
    resolvable_tipos,
)
from app.routers._common import Page, PaginationParams, ensure_tenant_context

logger = logging.getLogger("pastorai.work_queue")

router = APIRouter(prefix="/work-queue", tags=["work-queue"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class WorkItemOut(BaseModel):
    id: str
    tipo: str
    titulo: str
    contexto: str | None = None
    status: str | None = None
    pessoaId: str | None = None  # noqa: N815
    responsavelId: str | None = None  # noqa: N815
    prioridade: int | None = None
    # ISO-8601 deadline (when present) so the panel can render the deadline-badge
    # and re-order items by urgency without an extra round-trip.
    prazo: str | None = None

    @classmethod
    def from_model(cls, i: WorkQueueItem) -> "WorkItemOut":
        return cls(
            id=str(i.id),
            tipo=i.tipo,
            titulo=i.titulo,
            contexto=i.contexto,
            status=i.status,
            pessoaId=str(i.pessoa_id) if i.pessoa_id else None,
            responsavelId=str(i.responsavel_id) if i.responsavel_id else None,
            prioridade=i.prioridade,
            prazo=i.prazo.isoformat() if i.prazo else None,
        )


class ActionRequest(BaseModel):
    action: Literal["assume", "assign"]
    responsavelId: str | None = None  # noqa: N815

    @field_validator("responsavelId")
    @classmethod
    def _uuid_opt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("responsavelId inválido") from exc
        return value


class ActionResponse(BaseModel):
    status: str
    itemId: str  # noqa: N815
    responsavelId: str | None = None  # noqa: N815


class MessageRequest(BaseModel):
    mensagem: str = Field(min_length=1, max_length=2000)

    @field_validator("mensagem")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("mensagem obrigatória")
        return value


class MessageResponse(BaseModel):
    status: str
    messageId: str  # noqa: N815


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("", response_model=Page[WorkItemOut])
def list_items(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Page[WorkItemOut]:
    """List queue items the caller is allowed to resolve (delta-006)."""
    ensure_tenant_context(db, current_user)

    tipos = list(resolvable_tipos(current_user.roles))
    if not tipos:
        return Page[WorkItemOut](
            items=[], page=pagination.page, pageSize=pagination.page_size, total=0
        )

    cond = WorkQueueItem.tipo.in_(tipos)
    total = db.execute(
        select(func.count()).select_from(WorkQueueItem).where(cond)
    ).scalar_one()
    rows = db.execute(
        select(WorkQueueItem)
        .where(cond)
        .order_by(WorkQueueItem.prioridade.asc().nulls_last(),
                  WorkQueueItem.created_at.asc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).scalars().all()

    return Page[WorkItemOut](
        items=[WorkItemOut.from_model(i) for i in rows],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


@router.post("/{item_id}/action", response_model=ActionResponse)
def act_on_item(
    item_id: str,
    payload: ActionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> ActionResponse:
    """Assume or assign a queue item, guarding against stale concurrent state.

    The row is locked FOR UPDATE; if it is already taken (assumido/resolvido)
    by someone else, a 409 is returned with the real current state.
    """
    ensure_tenant_context(db, current_user)

    item = _get_item_for_update(db, item_id)

    if not can_resolve(current_user.roles, item.tipo):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não pode resolver itens deste tipo",
        )

    if payload.action == "assign":
        if not payload.responsavelId:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="responsavelId é obrigatório para assign",
            )
        new_responsible = payload.responsavelId
    else:  # assume
        new_responsible = current_user.app_user_id

    current_responsible = (
        str(item.responsavel_id) if item.responsavel_id else None
    )

    # Concurrency / stale detection.
    if item.status == "resolvido":
        raise _conflict(item)
    if item.status == "assumido":
        if current_responsible == new_responsible:
            # Idempotent: already assigned to the intended responsible.
            return ActionResponse(
                status=item.status,
                itemId=str(item.id),
                responsavelId=current_responsible,
            )
        raise _conflict(item)

    item.status = "assumido"
    item.responsavel_id = uuid.UUID(new_responsible)
    db.flush()
    db.refresh(item)
    db.commit()

    return ActionResponse(
        status="assumido",
        itemId=str(item.id),
        responsavelId=new_responsible,
    )


@router.post("/{item_id}/message", response_model=MessageResponse)
def send_internal_message(
    item_id: str,
    payload: MessageRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> MessageResponse:
    """Post an internal note ('Nome [papel]: mensagem') to the item's contact."""
    ensure_tenant_context(db, current_user)

    item = db.execute(
        select(WorkQueueItem).where(WorkQueueItem.id == _parse_uuid(item_id))
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item não encontrado"
        )

    if not can_resolve(current_user.roles, item.tipo):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não pode atuar em itens deste tipo",
        )

    if item.pessoa_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Item sem pessoa associada para enviar mensagem",
        )

    pessoa = db.execute(
        select(Pessoa).where(Pessoa.id == item.pessoa_id)
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pessoa associada ao item não encontrada",
        )

    conversation = db.execute(
        select(Conversation).where(Conversation.pessoa_id == pessoa.id).limit(1)
    ).scalar_one_or_none()

    igreja_uuid = uuid.UUID(current_user.igreja_id)
    if conversation is None:
        conversation = Conversation(
            igreja_id=igreja_uuid,
            pessoa_id=pessoa.id,
            telefone=pessoa.telefone,
            estado="humano",
        )
        db.add(conversation)
        db.flush()  # assign conversation.id

    texto = format_internal_message(
        current_user.nome, current_user.roles, payload.mensagem
    )
    message = Message(
        igreja_id=igreja_uuid,
        conversation_id=conversation.id,
        direcao="out",
        autor="humano",
        texto=texto,
    )
    db.add(message)
    conversation.ultima_mensagem = texto
    db.flush()
    db.refresh(message)
    db.commit()

    return MessageResponse(status="sent", messageId=str(message.id))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item não encontrado"
        ) from exc


def _get_item_for_update(db: Session, item_id: str) -> WorkQueueItem:
    item = db.execute(
        select(WorkQueueItem)
        .where(WorkQueueItem.id == _parse_uuid(item_id))
        .with_for_update()
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item não encontrado"
        )
    return item


def _conflict(item: WorkQueueItem) -> HTTPException:
    """Build a 409 carrying the item's real current state (stale)."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error": "stale_item",
            "message": "Item já foi assumido ou resolvido por outro usuário",
            "status": item.status,
            "responsavelId": str(item.responsavel_id)
            if item.responsavel_id
            else None,
        },
    )
