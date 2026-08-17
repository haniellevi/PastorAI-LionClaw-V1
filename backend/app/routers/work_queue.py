"""Work-queue router — shared queue actions and internal messages (F5).

Endpoints:
  - GET  /work-queue                     list items the caller can resolve
  - POST /work-queue/{itemId}/action     assume/assign an item (concurrency-safe)
  - POST /work-queue/{itemId}/message    post an internal note to the contact

Role gating (delta-006): an item is only listed/actionable by roles able to
resolve its type. Concurrent changes remain conflict-safe. A broad role may
recover an assumed item only when its current holder is absent, revoked or no
longer capable of resolving that item type.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    Celula,
    CelulaMembro,
    Conversation,
    Message,
    Pessoa,
    UserRole,
    WorkQueueItem,
)
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.domain.conversations import has_full_inbox
from app.domain.work_queue import (
    can_resolve,
    format_internal_message,
    has_tenant_queue_scope,
    resolvable_tipos,
)
from app.routers._common import Page, PaginationParams

logger = logging.getLogger("pastorai.work_queue")

router = APIRouter(prefix="/work-queue", tags=["work-queue"])

ACTIVE_QUEUE_STATUSES = ("aberto", "assumido")


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
    canMessage: bool = False  # noqa: N815 - capacidade resolvida no servidor
    # ISO-8601 deadline (when present) so the panel can render the deadline-badge
    # and re-order items by urgency without an extra round-trip.
    prazo: str | None = None

    @classmethod
    def from_model(
        cls, i: WorkQueueItem, *, can_message: bool = False
    ) -> "WorkItemOut":
        return cls(
            id=str(i.id),
            tipo=i.tipo,
            titulo=i.titulo,
            contexto=i.contexto,
            status=i.status,
            pessoaId=str(i.pessoa_id) if i.pessoa_id else None,
            responsavelId=str(i.responsavel_id) if i.responsavel_id else None,
            prioridade=i.prioridade,
            canMessage=can_message,
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

    tipos = list(resolvable_tipos(current_user.roles))
    if not tipos:
        return Page[WorkItemOut](
            items=[], page=pagination.page, pageSize=pagination.page_size, total=0
        )

    cond = and_(
        WorkQueueItem.tipo.in_(tipos),
        _operational_status_condition(),
        _work_item_scope_condition(db, current_user),
    )
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
    messageable_person_ids = _messageable_person_ids(db, current_user, rows)

    return Page[WorkItemOut](
        items=[
            WorkItemOut.from_model(
                i,
                can_message=(
                    i.pessoa_id is not None
                    and i.pessoa_id in messageable_person_ids
                ),
            )
            for i in rows
        ],
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
    """Assume or assign a queue item, guarding concurrent state changes.

    The row is locked FOR UPDATE. A competing change remains a 409 while the
    current holder is active and capable. A broad role using ``assign`` may
    recover orphaned work after the new destination passes tenant, revocation
    and capability validation.
    """

    if payload.action == "assign":
        if not has_tenant_queue_scope(current_user.roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para atribuir itens da fila",
            )
        if not payload.responsavelId:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="responsavelId é obrigatório para assign",
            )

    item = _get_item_for_update(db, item_id, current_user)

    if not can_resolve(current_user.roles, item.tipo):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não pode resolver itens deste tipo",
        )

    if item.status is not None and item.status not in ACTIVE_QUEUE_STATUSES:
        raise _conflict(item)

    if payload.action == "assign":
        new_responsible = _resolve_assign_target(
            db,
            current_user,
            payload.responsavelId,
            item.tipo,
        )
    else:  # assume
        new_responsible = current_user.app_user_id

    current_responsible = (
        str(item.responsavel_id) if item.responsavel_id else None
    )

    # Concurrency / stale detection.
    if item.status == "assumido":
        if current_responsible == new_responsible:
            # Idempotent: already assigned to the intended responsible.
            return ActionResponse(
                status=item.status,
                itemId=str(item.id),
                responsavelId=current_responsible,
            )
        if payload.action == "assume":
            raise _conflict(item)
        if _assignment_holder_is_active_and_capable(
            db,
            current_user,
            current_responsible,
            item.tipo,
        ):
            raise _conflict(item)
        # The target was fully validated above. Reassignment is limited to an
        # orphaned item, avoiding silent last-write-wins between live holders.

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

    item = db.execute(
        select(WorkQueueItem).where(
            WorkQueueItem.id == _parse_uuid(item_id),
            _operational_status_condition(),
            _work_item_scope_condition(db, current_user),
        )
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

    igreja_uuid = uuid.UUID(current_user.igreja_id)
    pessoa = db.execute(
        select(Pessoa).where(
            Pessoa.id == item.pessoa_id,
            Pessoa.igreja_id == igreja_uuid,
        )
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pessoa associada ao item não encontrada",
        )

    conversation = _select_message_conversation(
        db, current_user, pessoa.id
    )

    # Visão restrita (#5): o "responsável" (sem visão completa) só anota em uma
    # conversa JÁ atribuída a ele — e não cria conversa nova. admin/pastor (visão
    # completa) seguem livres (a fila é o mecanismo de atribuição de trabalho).
    if conversation is None and not has_full_inbox(current_user.roles):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversa não encontrada"
        )

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
def _operational_status_condition():
    """Legacy NULL queue status is operational and normalizes on action."""

    return or_(
        WorkQueueItem.status.is_(None),
        WorkQueueItem.status.in_(ACTIVE_QUEUE_STATUSES),
    )


def _messageable_person_ids(
    db: Session,
    current_user: CurrentUser,
    rows: list[WorkQueueItem],
) -> set[uuid.UUID]:
    """Return people for which the caller can use the queue message action.

    Admin/pastor may start a conversation for any in-scope item with a person.
    Restricted inbox roles only receive the CTA when that person's conversation
    is already assigned to their AppUser. This mirrors ``send_internal_message``
    and prevents the interface from promising an action that will return 404.
    """

    pessoa_ids = {i.pessoa_id for i in rows if i.pessoa_id is not None}
    if not pessoa_ids:
        return set()

    igreja_id = uuid.UUID(current_user.igreja_id)
    valid_pessoa_ids = set(
        db.execute(
            select(Pessoa.id).where(
                Pessoa.igreja_id == igreja_id,
                Pessoa.id.in_(pessoa_ids),
            )
        ).scalars().all()
    )
    if not valid_pessoa_ids:
        return set()
    if has_full_inbox(current_user.roles):
        return valid_pessoa_ids

    conversations = db.execute(
        select(Conversation)
        .where(*_message_conversation_filters(current_user, valid_pessoa_ids))
        .order_by(
            Conversation.pessoa_id.asc(),
            *_message_conversation_order(),
        )
    ).scalars().all()

    # The rows are ordered by the same rule used by POST /message. Keeping the
    # first row per person makes the capability projection and the write target
    # select the exact same assigned thread, even with duplicate legacy rows.
    selected: dict[uuid.UUID, uuid.UUID] = {}
    for conversation in conversations:
        if conversation.pessoa_id is not None:
            selected.setdefault(conversation.pessoa_id, conversation.id)
    return set(selected)


def _select_message_conversation(
    db: Session,
    current_user: CurrentUser,
    pessoa_id: uuid.UUID,
) -> Conversation | None:
    """Pick the single queue-message thread using a stable tenant-safe rule.

    Restricted roles only consider conversations assigned to their AppUser.
    Broad inbox roles prefer the official, most recently updated thread. UUID
    is the final tie-breaker, so a retry cannot drift to another conversation.
    """

    return db.execute(
        select(Conversation)
        .where(*_message_conversation_filters(current_user, {pessoa_id}))
        .order_by(*_message_conversation_order())
        .limit(1)
    ).scalar_one_or_none()


def _message_conversation_filters(
    current_user: CurrentUser,
    pessoa_ids: set[uuid.UUID],
) -> tuple:
    filters = [
        Conversation.igreja_id == uuid.UUID(current_user.igreja_id),
        Conversation.pessoa_id.in_(pessoa_ids),
    ]
    if not has_full_inbox(current_user.roles):
        filters.append(
            Conversation.assumido_por == uuid.UUID(current_user.app_user_id)
        )
    return tuple(filters)


def _message_conversation_order() -> tuple:
    """Canonical priority for duplicate conversation rows of one person."""

    return (
        Conversation.numero_oficial.desc(),
        Conversation.updated_at.desc(),
        Conversation.id.asc(),
    )


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item não encontrado"
        ) from exc


def _resolve_assign_target(
    db: Session,
    current_user: CurrentUser,
    responsavel_id: str,
    item_tipo: str,
) -> str:
    """Resolve an eligible assignment target inside the authenticated tenant."""

    igreja_id = uuid.UUID(current_user.igreja_id)
    target_id = db.execute(
        select(AppUser.id).where(
            AppUser.id == uuid.UUID(responsavel_id),
            AppUser.igreja_id == igreja_id,
            or_(AppUser.status.is_(None), AppUser.status == "ativo"),
        )
    ).scalar_one_or_none()
    if target_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Responsável não encontrado",
        )

    target_roles = db.execute(
        select(UserRole.papel).where(
            UserRole.user_id == target_id,
            UserRole.igreja_id == igreja_id,
        )
    ).scalars().all()
    if not can_resolve(target_roles, item_tipo):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Responsável não pode resolver itens deste tipo",
        )

    return str(target_id)


def _assignment_holder_is_active_and_capable(
    db: Session,
    current_user: CurrentUser,
    responsavel_id: str | None,
    item_tipo: str,
) -> bool:
    """Whether an existing holder still owns a conflict-safe assignment."""

    if responsavel_id is None:
        return False

    igreja_id = uuid.UUID(current_user.igreja_id)
    holder_id = uuid.UUID(responsavel_id)
    holder = db.execute(
        select(AppUser).where(
            AppUser.id == holder_id,
            AppUser.igreja_id == igreja_id,
        )
    ).scalar_one_or_none()
    if holder is None or holder.status not in {None, "ativo"}:
        return False

    holder_roles = db.execute(
        select(UserRole.papel).where(
            UserRole.user_id == holder_id,
            UserRole.igreja_id == igreja_id,
        )
    ).scalars().all()
    return can_resolve(holder_roles, item_tipo)


def _work_item_scope_condition(db: Session, current_user: CurrentUser):
    """Predicado canônico de escopo para lista e acesso direto à fila.

    Papéis pastorais amplos veem a fila do tenant. Os demais veem somente itens
    atribuídos a si, ligados à própria Pessoa ou a um membro ativo de célula
    ativa que lideram. Sem Pessoa vinculada, a atribuição explícita continua
    funcionando e todo o restante falha fechado.
    """

    igreja_id = uuid.UUID(current_user.igreja_id)
    tenant_condition = WorkQueueItem.igreja_id == igreja_id
    if has_tenant_queue_scope(current_user.roles):
        return tenant_condition

    visible = [
        WorkQueueItem.responsavel_id == uuid.UUID(current_user.app_user_id),
    ]
    actor_pessoa_id = db.execute(
        select(AppUser.pessoa_id).where(
            AppUser.id == uuid.UUID(current_user.app_user_id),
            AppUser.igreja_id == igreja_id,
        )
    ).scalar_one_or_none()

    if actor_pessoa_id is not None:
        led_cell_members = (
            select(CelulaMembro.pessoa_id)
            .join(Celula, Celula.id == CelulaMembro.celula_id)
            .where(
                CelulaMembro.igreja_id == igreja_id,
                CelulaMembro.ativo.is_(True),
                Celula.igreja_id == igreja_id,
                Celula.ativo.is_(True),
                Celula.lider_id == actor_pessoa_id,
            )
        )
        visible.extend(
            [
                WorkQueueItem.pessoa_id == actor_pessoa_id,
                WorkQueueItem.pessoa_id.in_(led_cell_members),
            ]
        )

    return and_(tenant_condition, or_(*visible))


def _get_item_for_update(
    db: Session, item_id: str, current_user: CurrentUser
) -> WorkQueueItem:
    item = db.execute(
        select(WorkQueueItem)
        .where(
            WorkQueueItem.id == _parse_uuid(item_id),
            _work_item_scope_condition(db, current_user),
        )
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
