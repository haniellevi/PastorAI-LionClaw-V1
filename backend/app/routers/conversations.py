"""Conversations router — inbox listing and IA/human handoff (US-11..US-13).

Endpoints:
  - GET  /conversations                list the tenant's conversations
  - POST /conversations/{id}/handoff   switch control between IA and human
  - GET  /conversations/{id}/messages  conversation history (oldest first)
  - POST /conversations/{id}/messages  send a human reply to the contact (WhatsApp)

Access (US-11): the inbox screen is gated by the tenant's role_permissions
matrix via require_screen("inbox") — the same matrix the admin edits in
#permissoes (admin implicit). Roles without the inbox screen receive 403.

Handoff concurrency (US-12): the conversation row is locked FOR UPDATE; if a
human already assumed it, a second "assume" returns 409 carrying the real
`assumido_por` so the UI reflects who actually holds it.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, aliased

from app.db.models import (
    AppUser,
    Conversation,
    Message,
    Pessoa,
    UserRole,
    WhatsappConnection,
)
from app.db.session import get_db
from app.deps import CurrentUser, require_role, require_screen
from app.domain.conversations import (
    can_access_inbox,
    media_snippet,
    resolve_handoff,
)
from app.routers._common import Page, PaginationParams, ensure_tenant_context
from app.services.evolution import (
    EvolutionClient,
    EvolutionError,
    get_evolution_client,
)
from app.services.storage import (
    StorageError,
    SupabaseStorage,
    get_storage,
    kind_for_mime,
    mediatype_for_tipo,
)

logger = logging.getLogger("pastorai.conversations")

router = APIRouter(prefix="/conversations", tags=["conversations"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ConversationOut(BaseModel):
    id: str
    telefone: str
    pessoaId: str | None = None  # noqa: N815
    nome: str | None = None  # nome do contato (humaniza a lista/thread)
    estado: str | None = None
    ultimaMensagem: str | None = None  # noqa: N815
    naoLidas: int  # noqa: N815
    assumidoPor: str | None = None  # noqa: N815
    assumidoPorNome: str | None = None  # noqa: N815 - nome de quem assumiu (humano)
    assumidoEm: str | None = None  # noqa: N815
    esperaDesde: str | None = None  # noqa: N815
    atualizadoEm: str | None = None  # noqa: N815 - hora da última atividade (lista)
    tipo: str | None = None  # tipo da pessoa vinculada (marca discreta no chat)
    semInteresse: bool = False  # noqa: N815 - CSIM da pessoa vinculada

    @classmethod
    def from_model(
        cls,
        c: Conversation,
        nome: str | None = None,
        assumido_por_nome: str | None = None,
        tipo: str | None = None,
        sem_interesse: bool = False,
    ) -> "ConversationOut":
        return cls(
            id=str(c.id),
            telefone=c.telefone,
            pessoaId=str(c.pessoa_id) if c.pessoa_id else None,
            nome=nome,
            estado=c.estado,
            ultimaMensagem=c.ultima_mensagem,
            naoLidas=c.nao_lidas or 0,
            assumidoPor=str(c.assumido_por) if c.assumido_por else None,
            assumidoPorNome=assumido_por_nome,
            assumidoEm=c.assumido_em.isoformat() if c.assumido_em else None,
            esperaDesde=c.espera_desde.isoformat() if c.espera_desde else None,
            atualizadoEm=c.updated_at.isoformat() if c.updated_at else None,
            tipo=tipo,
            semInteresse=bool(sem_interesse),
        )


class HandoffRequest(BaseModel):
    to: Literal["human", "ia"]


class HandoffResponse(BaseModel):
    estado: str
    assumidoPor: str | None = None  # noqa: N815


class MessageOut(BaseModel):
    """A single message in a conversation thread."""

    id: str
    direcao: str  # in | out
    autor: str  # contato | ia | humano
    autorNome: str | None = None  # noqa: N815 - quem respondeu (humano)
    tipo: str = "texto"  # texto | imagem | arquivo | audio
    texto: str | None = None
    mediaUrl: str | None = None  # noqa: N815 - URL assinada de curta duração
    mediaMime: str | None = None  # noqa: N815
    mediaNome: str | None = None  # noqa: N815
    criadoEm: str  # noqa: N815 - external contract camelCase

    @classmethod
    def from_model(cls, m: Message, media_url: str | None = None) -> "MessageOut":
        return cls(
            id=str(m.id),
            direcao=m.direcao,
            autor=m.autor,
            autorNome=m.autor_nome,
            tipo=m.tipo or "texto",
            texto=m.texto,
            mediaUrl=media_url,
            mediaMime=m.media_mime,
            mediaNome=m.media_nome,
            criadoEm=m.criado_em.isoformat() if m.criado_em else "",
        )


class SendMessageRequest(BaseModel):
    texto: str = Field(min_length=1, max_length=4096)

    @field_validator("texto")
    @classmethod
    def _texto(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Mensagem vazia")
        return value


class SendMediaRequest(BaseModel):
    """Upload de mídia (imagem/arquivo) como base64 — Etapa 2 do chat.

    O painel lê o arquivo (FileReader) e envia o base64 puro (sem o prefixo
    `data:`). Evita a dependência `python-multipart` e reaproveita o base64 como
    transporte direto para a Evolution.
    """

    mime: str = Field(min_length=1, max_length=255)
    base64: str = Field(min_length=1)
    nome: str | None = Field(default=None, max_length=255)
    caption: str | None = Field(default=None, max_length=4096)

    @field_validator("caption")
    @classmethod
    def _caption(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class TransferRequest(BaseModel):
    """Transferir a conversa para outro membro com acesso ao inbox."""

    toUserId: str = Field(min_length=1)  # noqa: N815

    @field_validator("toUserId")
    @classmethod
    def _to_user(cls, value: str) -> str:
        try:
            uuid.UUID(value)
        except ValueError as exc:
            raise ValueError("toUserId inválido") from exc
        return value


class TransferResponse(BaseModel):
    estado: str
    assumidoPor: str | None = None  # noqa: N815
    assumidoPorNome: str | None = None  # noqa: N815


class PhotoResponse(BaseModel):
    """Foto de perfil do contato (URL do CDN do WhatsApp) — pode ser None."""

    url: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("", response_model=Page[ConversationOut])
def list_conversations(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_screen("inbox")),
) -> Page[ConversationOut]:
    """List tenant conversations (estado, última mensagem, não lidas, fila)."""
    ensure_tenant_context(db, current_user)

    holder = aliased(AppUser)
    total = db.execute(
        select(func.count()).select_from(Conversation)
    ).scalar_one()
    rows = db.execute(
        select(
            Conversation,
            Pessoa.nome,
            holder.nome,
            holder.chat_nome,
            Pessoa.tipo,
            Pessoa.sem_interesse,
        )
        # Nome do contato vinculado (humaniza a UI); LEFT JOIN preserva
        # conversas sem pessoa vinculada (nome fica None -> front usa telefone).
        .outerjoin(Pessoa, Pessoa.id == Conversation.pessoa_id)
        # Nome de quem assumiu (humano), p/ exibir "em atendimento por X".
        .outerjoin(holder, holder.id == Conversation.assumido_por)
        # Human-queue first (espera_desde set), then most recently updated.
        .order_by(
            Conversation.espera_desde.asc().nulls_last(),
            desc(Conversation.updated_at),
        )
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()

    return Page[ConversationOut](
        items=[
            ConversationOut.from_model(
                c,
                nome=nome,
                assumido_por_nome=(holder_chat or holder_nome),
                tipo=tipo,
                sem_interesse=sem_interesse,
            )
            for c, nome, holder_nome, holder_chat, tipo, sem_interesse in rows
        ],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


@router.post("/{conversation_id}/handoff", response_model=HandoffResponse)
def handoff(
    conversation_id: str,
    payload: HandoffRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_screen("inbox")),
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


@router.post("/{conversation_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_screen("inbox")),
) -> Response:
    """Zera o contador de não lidas quando o atendente abre a conversa (US-13)."""
    ensure_tenant_context(db, current_user)
    conv = _get_conversation(db, conversation_id)
    if conv.nao_lidas:
        conv.nao_lidas = 0
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{conversation_id}/transfer", response_model=TransferResponse)
def transfer_conversation(
    conversation_id: str,
    payload: TransferRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_screen("inbox")),
) -> TransferResponse:
    """Transferir o atendimento humano para outro membro com acesso ao inbox.

    Quem pode transferir: o **admin** (qualquer conversa) ou o **detentor atual**
    de uma conversa já sob controle humano. O destino precisa ser um usuário do
    tenant com acesso ao inbox (admin/pastor/lider_g12/operador) — caso contrário
    422. A conversa passa ao controle humano do destino (sai da fila de espera).
    """
    ensure_tenant_context(db, current_user)
    conv = _get_conversation_for_update(db, conversation_id)

    holder = str(conv.assumido_por) if conv.assumido_por else None
    if not current_user.has_role("admin"):
        # Não-admin só transfere o que ele mesmo está atendendo.
        if conv.estado != "humano" or holder != current_user.app_user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Assuma o atendimento antes de transferir.",
            )

    target_id = uuid.UUID(payload.toUserId)
    target = db.execute(
        select(AppUser).where(AppUser.id == target_id)
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário de destino não encontrado",
        )
    target_roles = db.execute(
        select(UserRole.papel).where(UserRole.user_id == target_id)
    ).scalars().all()
    if not can_access_inbox(target_roles):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O usuário escolhido não tem acesso ao inbox",
        )

    conv.estado = "humano"
    conv.assumido_por = target_id
    conv.assumido_em = dt.datetime.now(dt.timezone.utc)
    conv.espera_desde = None
    db.flush()
    db.commit()

    nome = target.chat_nome or target.nome
    return TransferResponse(
        estado="humano", assumidoPor=str(target_id), assumidoPorNome=nome
    )


@router.get("/{conversation_id}/photo", response_model=PhotoResponse)
def conversation_photo(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_screen("inbox")),
    evolution: EvolutionClient = Depends(get_evolution_client),
) -> PhotoResponse:
    """Foto de perfil do contato no WhatsApp (Etapa 4) — best-effort.

    Consulta a Evolution pelo número oficial da igreja. Sem conexão/instância, ou
    quando o contato não tem foto / a oculta por privacidade, retorna ``url=None``
    e a UI cai nas iniciais. O avatar nunca quebra o inbox.
    """
    ensure_tenant_context(db, current_user)
    conv = _get_conversation(db, conversation_id)

    conn = db.execute(
        select(WhatsappConnection).where(
            WhatsappConnection.igreja_id == uuid.UUID(current_user.igreja_id)
        )
    ).scalar_one_or_none()
    if conn is None or not conn.instance:
        return PhotoResponse(url=None)

    try:
        url = evolution.fetch_profile_picture_url(conn.instance, conv.telefone)
    except EvolutionError:
        url = None
    return PhotoResponse(url=url)


@router.get("/{conversation_id}/messages", response_model=Page[MessageOut])
def list_messages(
    conversation_id: str,
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_screen("inbox")),
    storage: SupabaseStorage = Depends(get_storage),
) -> Page[MessageOut]:
    """Return a conversation's message history, oldest first (US-13).

    Media messages carry a short-lived **signed URL** (`mediaUrl`) so the panel
    can render images/download files without the bucket ever being public. URLs
    are batch-signed in one call; a signing failure degrades to a placeholder.
    """
    ensure_tenant_context(db, current_user)
    conv = _get_conversation(db, conversation_id)

    total = db.execute(
        select(func.count())
        .select_from(Message)
        .where(Message.conversation_id == conv.id)
    ).scalar_one()
    rows = db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.criado_em.asc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).scalars().all()

    paths = [m.media_path for m in rows if m.media_path]
    signed = storage.sign(paths) if paths else {}

    return Page[MessageOut](
        items=[
            MessageOut.from_model(
                m, media_url=signed.get(m.media_path) if m.media_path else None
            )
            for m in rows
        ],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=int(total),
    )


@router.post("/{conversation_id}/messages", response_model=MessageOut)
def send_message(
    conversation_id: str,
    payload: SendMessageRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_screen("inbox")),
    evolution: EvolutionClient = Depends(get_evolution_client),
) -> MessageOut:
    """Send a human reply to the contact's WhatsApp (US-13).

    Requires the conversation to be under human control held by the caller
    (assume first) and the official number to be online. The message is
    dispatched via Evolution *before* being persisted, so a failed send (502)
    never leaves a phantom "sent" row in the thread.
    """
    ensure_tenant_context(db, current_user)
    conv = _get_conversation_for_update(db, conversation_id)

    # Composer gate: must hold the conversation under human control (mirrors the
    # inbox UI, which only enables the composer for the holder).
    holder = str(conv.assumido_por) if conv.assumido_por else None
    if conv.estado != "humano" or holder != current_user.app_user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Assuma o atendimento antes de responder.",
        )

    conn = db.execute(
        select(WhatsappConnection).where(
            WhatsappConnection.igreja_id == uuid.UUID(current_user.igreja_id)
        )
    ).scalar_one_or_none()
    if conn is None or conn.status != "online" or not conn.instance:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WhatsApp não está conectado. Conecte o número antes de responder.",
        )

    # Dispatch first; persist only on success (no phantom rows on failure). O
    # nome de quem responde vai PREFIXADO no texto do WhatsApp (o contato precisa
    # saber quem é); no banco guardamos o texto limpo + autor_nome.
    author = current_user.chat_nome or current_user.nome
    try:
        evolution.send_text(
            conn.instance, conv.telefone, _author_caption(author, payload.texto)
        )
    except EvolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    msg = Message(
        igreja_id=uuid.UUID(current_user.igreja_id),
        conversation_id=conv.id,
        direcao="out",
        autor="humano",
        autor_nome=author,
        enviado_por=uuid.UUID(current_user.app_user_id),
        texto=payload.texto,
    )
    db.add(msg)
    conv.ultima_mensagem = payload.texto
    conv.updated_at = dt.datetime.now(dt.timezone.utc)
    db.flush()
    db.refresh(msg)
    db.commit()

    return MessageOut.from_model(msg)


@router.post("/{conversation_id}/messages/media", response_model=MessageOut)
def send_media_message(
    conversation_id: str,
    payload: SendMediaRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_screen("inbox")),
    evolution: EvolutionClient = Depends(get_evolution_client),
    storage: SupabaseStorage = Depends(get_storage),
) -> MessageOut:
    """Send an image/file to the contact's WhatsApp (Etapa 2 do chat).

    Same gate as the text reply (US-13): the caller must hold the conversation
    under human control and the official number must be online. The bytes go to
    Storage and are dispatched via Evolution as base64; the row is persisted
    only after a successful send (no phantom "sent" media in the thread).
    """
    ensure_tenant_context(db, current_user)
    conv = _get_conversation_for_update(db, conversation_id)

    # Composer gate: mirror send_message (must hold the conversation).
    holder = str(conv.assumido_por) if conv.assumido_por else None
    if conv.estado != "humano" or holder != current_user.app_user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Assuma o atendimento antes de responder.",
        )

    conn = db.execute(
        select(WhatsappConnection).where(
            WhatsappConnection.igreja_id == uuid.UUID(current_user.igreja_id)
        )
    ).scalar_one_or_none()
    if conn is None or conn.status != "online" or not conn.instance:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WhatsApp não está conectado. Conecte o número antes de responder.",
        )

    try:
        raw = base64.b64decode(payload.base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mídia inválida (base64).",
        ) from exc

    tipo = kind_for_mime(payload.mime)

    # Storage primeiro (ponteiro), depois despacho. Se o upload falhar, nada é
    # enviado; se o envio falhar, não persistimos linha "enviada" fantasma.
    try:
        stored = storage.upload(
            current_user.igreja_id, conv.id, raw, payload.mime, payload.nome
        )
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    # O nome de quem responde vai PREFIXADO na legenda do WhatsApp (mesmo sem
    # legenda, envia o nome); no banco guardamos a legenda limpa + autor_nome.
    author = current_user.chat_nome or current_user.nome
    try:
        evolution.send_media(
            conn.instance,
            conv.telefone,
            mediatype=mediatype_for_tipo(tipo),
            media_base64=payload.base64,
            mime=payload.mime,
            filename=payload.nome,
            caption=_author_caption(author, payload.caption),
        )
    except EvolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    msg = Message(
        igreja_id=uuid.UUID(current_user.igreja_id),
        conversation_id=conv.id,
        direcao="out",
        autor="humano",
        autor_nome=author,
        enviado_por=uuid.UUID(current_user.app_user_id),
        texto=payload.caption,
        tipo=tipo,
        media_path=stored.path,
        media_mime=stored.mime,
        media_nome=stored.nome,
        media_tamanho=stored.tamanho,
    )
    db.add(msg)
    conv.ultima_mensagem = payload.caption or media_snippet(tipo)
    conv.updated_at = dt.datetime.now(dt.timezone.utc)
    db.flush()
    db.refresh(msg)
    db.commit()

    signed = storage.sign([stored.path])
    return MessageOut.from_model(msg, media_url=signed.get(stored.path))


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
    storage: SupabaseStorage = Depends(get_storage),
) -> Response:
    """Excluir permanentemente uma conversa e tudo que ela contém (admin-only).

    Ação destrutiva e irreversível: remove a conversa, suas mensagens (cascata
    via FK ``messages.conversation_id``) e limpa a mídia no Storage (best-effort).
    Restrita ao admin — o inbox é acessível a outros papéis, mas a exclusão não.
    Tenant-scoped (RLS): só apaga conversas da própria igreja.
    """
    ensure_tenant_context(db, current_user)
    conv = _get_conversation(db, conversation_id)

    # Coleta os ponteiros de mídia ANTES de apagar (a cascata leva as mensagens
    # junto). A limpeza no Storage é best-effort e roda após o commit, então
    # nunca bloqueia a exclusão da conversa em si.
    media_paths = list(
        db.execute(
            select(Message.media_path).where(
                Message.conversation_id == conv.id,
                Message.media_path.is_not(None),
            )
        ).scalars().all()
    )

    db.delete(conv)  # ON DELETE CASCADE remove as mensagens da conversa
    db.commit()

    if media_paths:
        storage.remove(media_paths)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _author_caption(author: str, text: str | None) -> str:
    """Prefixa o nome de quem respondeu no texto que vai pro WhatsApp.

    O contato precisa saber QUEM respondeu (a igreja usa um único número). O nome
    vai em negrito + quebra de linha antes da mensagem; sem texto (mídia sem
    legenda), envia só o nome. No banco guardamos o texto limpo — o painel já
    exibe o nome como rótulo, então não há duplicação.
    """
    base = f"*{author}:*"
    return f"{base}\n{text}" if text else base


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversa não encontrada"
        ) from exc


def _get_conversation(db: Session, conversation_id: str) -> Conversation:
    conv = db.execute(
        select(Conversation).where(Conversation.id == _parse_uuid(conversation_id))
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversa não encontrada"
        )
    return conv


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
