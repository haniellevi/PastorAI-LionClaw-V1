"""Single prayer domain service. Callers own commit; no transport or content logs."""

from dataclasses import dataclass
import hashlib
import uuid
from fastapi import HTTPException
from sqlalchemy import and_, exists, false, func, or_, select, text
from sqlalchemy.orm import Session
from app.config import get_settings
from app.db.models import (
    AppUser,
    Celula,
    CelulaMembro,
    ConsentRecord,
    Conversation,
    Message,
    Pessoa,
    UserRole,
)
from app.deps import CurrentUser
from app.domain.agent_reply import AGENT_REPLY_CONFIRMED
from app.domain.phone import normalize_phone
from app.prayer import policy
from app.prayer.catalog import AUTHORIZATION_VERSION
from app.prayer.models import PrayerMessage, PrayerProposal, PrayerRequest


def protected_message(db, *, igreja_id, message_id):
    # V1b can be deployed before prayer privacy; absence must not abort its txn.
    if db.scalar(text("select to_regclass('pedido_oracao_mensagem')")) is None:
        return False
    return db.scalar(select(exists().where(
        PrayerMessage.igreja_id == igreja_id,
        PrayerMessage.message_id == message_id,
    )))


def has_audio(db, proposal):
    return bool(db.scalar(select(exists().where(
        PrayerMessage.igreja_id == proposal.igreja_id,
        PrayerMessage.proposal_id == proposal.id,
        Message.igreja_id == PrayerMessage.igreja_id,
        Message.id == PrayerMessage.message_id,
        Message.tipo == "audio",
    ))))


@dataclass(frozen=True)
class Contact:
    igreja_id: uuid.UUID
    pessoa_id: uuid.UUID
    conversation_id: uuid.UUID
    inbound_message_id: uuid.UUID
    term_version: str


def now(db):
    return db.scalar(select(func.clock_timestamp()))


def resolve_contact(
    db, *, igreja_id, conversation_id, inbound_message_id, provider_id, phone
):
    """Resolve only the real persisted contact/official conversation/inbound."""
    conv = db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.igreja_id == igreja_id)
        .with_for_update()
    ).scalar_one_or_none()
    if (
        conv is None
        or not conv.numero_oficial
        or conv.estado != "ia"
        or normalize_phone(conv.telefone) != normalize_phone(phone)
    ):
        return None
    inbound = db.execute(
        select(Message).where(
            Message.id == inbound_message_id,
            Message.igreja_id == igreja_id,
            Message.conversation_id == conv.id,
            Message.direcao == "in",
            Message.autor == "contato",
            Message.provider_message_id == provider_id,
        )
    ).scalar_one_or_none()
    audio = inbound is not None and inbound.tipo == "audio" and protected_message(
        db, igreja_id=igreja_id, message_id=inbound.id,
    )
    if inbound is None or (not audio and (
        inbound.tipo != "texto" or any(
            getattr(inbound, k) is not None
            for k in ("media_path", "media_mime", "media_nome", "media_tamanho")
        )
    )):
        return None
    from app.workers.queue_worker import _resolve_unique_active_pessoa_by_phone

    person = _resolve_unique_active_pessoa_by_phone(
        db, igreja_id=igreja_id, canonical=normalize_phone(conv.telefone)
    )
    if person is None:
        return None
    person = db.execute(
        select(Pessoa)
        .where(Pessoa.igreja_id == igreja_id, Pessoa.id == person.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if normalize_phone(person.telefone) != normalize_phone(conv.telefone):
        return None
    if conv.pessoa_id != person.id or person.optout or person.sem_interesse:
        return None
    version = get_settings().agent_term_version
    accepted = db.execute(
        select(ConsentRecord.termo_versao)
        .where(
            ConsentRecord.igreja_id == igreja_id, ConsentRecord.pessoa_id == person.id
        )
        .order_by(ConsentRecord.aceite_em.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not version or accepted != version:
        return None
    return Contact(igreja_id, person.id, conv.id, inbound.id, version)


def current_leader(db, contact):
    rows = db.execute(
        select(Celula, Pessoa)
        .join(
            CelulaMembro,
            and_(
                CelulaMembro.igreja_id == Celula.igreja_id,
                CelulaMembro.celula_id == Celula.id,
            ),
        )
        .join(
            Pessoa,
            and_(Pessoa.igreja_id == Celula.igreja_id, Pessoa.id == Celula.lider_id),
        )
        .where(
            Celula.igreja_id == contact.igreja_id,
            Celula.ativo.is_(True),
            CelulaMembro.pessoa_id == contact.pessoa_id,
            CelulaMembro.ativo.is_(True),
            Pessoa.arquivada_em.is_(None),
        )
        .with_for_update(of=(Celula, CelulaMembro, Pessoa))
    ).all()
    if len(rows) != 1:
        return None
    cell, leader = rows[0]
    person = db.get(Pessoa, contact.pessoa_id)
    if not leader.nome or (
        person.celula_id is not None and person.celula_id != cell.id
    ):
        return None
    return cell.id, leader.id, leader.nome


def has_pastoral_team(db, tenant):
    return bool(
        db.scalar(
            select(
                exists().where(
                    AppUser.igreja_id == tenant,
                    AppUser.status == "ativo",
                    UserRole.igreja_id == tenant,
                    UserRole.user_id == AppUser.id,
                    UserRole.papel.in_(policy.PASTORAL_ROLES),
                )
            )
        )
    )


def register(
    db: Session, *, contact: Contact, proposal: PrayerProposal, confirmation: Message
):
    """Write once after a delivered, unexpired exact summary and strict SIM."""
    if not policy.enabled(contact.igreja_id) or proposal.state != "pending":
        raise HTTPException(403, "Pedido não autorizado")
    if has_audio(db, proposal) and proposal.audience != "pastoral":
        raise HTTPException(403, "Áudio de oração é restrito aos pastores")
    fresh = resolve_contact(
        db,
        igreja_id=contact.igreja_id,
        conversation_id=contact.conversation_id,
        inbound_message_id=confirmation.id,
        provider_id=confirmation.provider_message_id,
        phone=db.get(Conversation, contact.conversation_id).telefone,
    )
    if (
        fresh != contact
        or proposal.igreja_id != contact.igreja_id
        or proposal.pessoa_id != contact.pessoa_id
        or proposal.conversation_id != contact.conversation_id
        or proposal.term_version != contact.term_version
    ):
        raise HTTPException(403, "Pedido não autorizado")
    if confirmation.texto.strip().casefold() != "sim":
        raise HTTPException(403, "Confirmação explícita obrigatória")
    delivered = db.execute(
        select(Message).where(
            Message.id == proposal.summary_message_id,
            Message.igreja_id == contact.igreja_id,
            Message.conversation_id == contact.conversation_id,
            Message.direcao == "out",
            Message.autor == "ia",
            Message.agent_reply_state == AGENT_REPLY_CONFIRMED,
        )
    ).scalar_one_or_none()
    if (
        delivered is None
        or delivered.texto != proposal.authorization_text
        or proposal.delivered_at is None
        or confirmation.criado_em <= proposal.delivered_at
        or proposal.expires_at <= now(db)
    ):
        raise HTTPException(409, "Confirmação expirada ou não entregue")
    if not has_pastoral_team(db, contact.igreja_id):
        raise HTTPException(409, "Equipe pastoral indisponível")
    if proposal.audience == "pastoral_lider":
        leader = current_leader(db, contact)
        if leader is None or leader[:2] != (proposal.cell_id, proposal.leader_id):
            raise HTTPException(409, "Vínculo de célula mudou; escolha novamente")
    elif proposal.audience != "pastoral":
        raise HTTPException(403, "Escolha de destinatários obrigatória")
    row = PrayerRequest(
        igreja_id=contact.igreja_id,
        pessoa_id=contact.pessoa_id,
        conversation_id=contact.conversation_id,
        proposal_id=proposal.id,
        confirmation_message_id=confirmation.id,
        summary=proposal.summary,
        audience=proposal.audience,
        cell_id=proposal.cell_id,
        leader_id=proposal.leader_id,
        authorization_text=proposal.authorization_text,
        authorization_hash=hashlib.sha256(
            proposal.authorization_text.encode()
        ).hexdigest(),
        authorization_version=AUTHORIZATION_VERSION,
        authorized_at=now(db),
        state="open",
    )
    db.add(row)
    proposal.state = "executed"
    db.flush()
    return row


def _actor(db, user: CurrentUser):
    tenant = uuid.UUID(user.igreja_id)
    if not policy.enabled(tenant):
        raise HTTPException(404, "Recurso indisponível")
    actor = db.execute(
        select(AppUser).where(
            AppUser.id == uuid.UUID(user.app_user_id),
            AppUser.igreja_id == tenant,
            AppUser.clerk_user_id == user.clerk_user_id,
            AppUser.status == "ativo",
        )
    ).scalar_one_or_none()
    if actor is None:
        raise HTTPException(403, "Acesso não autorizado")
    if actor.pessoa_id is not None:
        person = db.execute(
            select(Pessoa).where(
                Pessoa.id == actor.pessoa_id,
                Pessoa.igreja_id == tenant,
                Pessoa.arquivada_em.is_(None),
            )
        ).scalar_one_or_none()
        if person is None:
            raise HTTPException(403, "Acesso não autorizado")
    roles = set(
        db.scalars(
            select(UserRole.papel).where(
                UserRole.igreja_id == tenant, UserRole.user_id == actor.id
            )
        )
    )
    return actor, roles


def _visible(db, user):
    actor, roles = _actor(db, user)
    tenant = uuid.UUID(user.igreja_id)
    if roles & policy.PASTORAL_ROLES:
        return PrayerRequest.igreja_id == tenant
    if actor.pessoa_id is None:
        return false()
    return and_(
        PrayerRequest.igreja_id == tenant,
        PrayerRequest.audience == "pastoral_lider",
        PrayerRequest.leader_id == actor.pessoa_id,
        exists(
            select(Celula.id)
            .join(
                CelulaMembro,
                and_(
                    CelulaMembro.igreja_id == Celula.igreja_id,
                    CelulaMembro.celula_id == Celula.id,
                ),
            )
            .join(
                Pessoa,
                and_(
                    Pessoa.igreja_id == Celula.igreja_id,
                    Pessoa.id == CelulaMembro.pessoa_id,
                ),
            )
            .where(
                Celula.igreja_id == tenant,
                Celula.id == PrayerRequest.cell_id,
                Celula.ativo.is_(True),
                Celula.lider_id == actor.pessoa_id,
                CelulaMembro.ativo.is_(True),
                CelulaMembro.pessoa_id == PrayerRequest.pessoa_id,
                Pessoa.arquivada_em.is_(None),
                or_(Pessoa.celula_id.is_(None), Pessoa.celula_id == Celula.id),
            )
        ),
    )


def list_requests(db, user):
    return list(
        db.scalars(
            select(PrayerRequest)
            .where(_visible(db, user))
            .order_by(PrayerRequest.created_at.desc())
            .limit(100)
        )
    )


def get_request(db, user, request_id, *, lock=False):
    stmt = (
        select(PrayerRequest)
        .where(PrayerRequest.id == request_id, _visible(db, user))
        .execution_options(populate_existing=True)
    )
    row = db.execute(stmt.with_for_update() if lock else stmt).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Pedido não encontrado")
    return row


def assume(db, user, request_id):
    row = get_request(db, user, request_id, lock=True)
    actor, roles = _actor(db, user)
    if row.state == "closed":
        raise HTTPException(409, "Pedido encerrado")
    if row.responsavel_id not in (None, actor.id):
        previous = db.get(AppUser, row.responsavel_id)
        still_authorized = False
        if previous is not None:
            principal = CurrentUser(
                app_user_id=str(previous.id),
                igreja_id=str(previous.igreja_id),
                clerk_user_id=previous.clerk_user_id,
                email="",
                nome="",
            )
            try:
                get_request(db, principal, row.id)
                still_authorized = True
            except HTTPException:
                pass
        if not roles & policy.PASTORAL_ROLES or still_authorized:
            raise HTTPException(409, "Pedido já assumido")
    row.responsavel_id = actor.id
    row.state = "assigned"
    db.flush()
    return row


def close(db, user, request_id):
    row = get_request(db, user, request_id, lock=True)
    actor, _ = _actor(db, user)
    if row.responsavel_id != actor.id:
        raise HTTPException(403, "Assuma o pedido antes de encerrar")
    if row.state != "closed":
        row.state = "closed"
        row.closed_at = now(db)
    db.flush()
    return row


def delete_for_person(db, *, igreja_id, pessoa_id):
    """Approved offboarding only; DB rechecks admin/worker, returns no content.

    A pre-migration deployment must not break the existing offboarding path.
    """
    installed = db.execute(
        text("select to_regprocedure('delete_prayer_requests_for_person(uuid,uuid)')")
    ).scalar_one_or_none()
    if installed is None:
        table = db.execute(
            text("select to_regclass('pedido_oracao')")
        ).scalar_one_or_none()
        if table is not None:
            raise RuntimeError("Prayer deletion migration is incomplete")
    if installed is not None:
        db.execute(
            text("select delete_prayer_requests_for_person(:tenant,:person)"),
            {"tenant": str(igreja_id), "person": str(pessoa_id)},
        )
