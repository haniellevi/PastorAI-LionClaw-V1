"""Durable, deterministic secretary-offer state for one conversation.

The offer is local workflow state only. It never creates a contact, a cell
membership, an expectation, or an outbound request to a leader.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message
from app.domain import consent as consent_rules
from app.domain.agent_reply import AGENT_REPLY_CONFIRMED

OFFER_PREPARED = "preparada"
OFFER_ACCEPT_WAITING = "aceite_aguardando_ancora"
OFFER_PENDING = "pendente"
OFFER_CONSUMED = "consumida"
OFFER_CANCELLED = "cancelada"
OFFER_EXPIRED = "expirada"

_ACTIVE_STATES = frozenset({OFFER_PREPARED, OFFER_ACCEPT_WAITING, OFFER_PENDING})
_TERMINAL_STATES = frozenset({OFFER_CONSUMED, OFFER_CANCELLED, OFFER_EXPIRED})
_YES = re.compile(r"\s*sim[\s.!?]*\Z")
_NO = re.compile(r"\s*nao[\s.!?]*\Z")


@dataclass(frozen=True)
class OfferInboundResolution:
    """Outcome of a locked inbound offer check.

    ``continue_turn`` preserves normal routing after an unrelated message
    cancels a prior offer. ``terminal`` binds a retry of the same inbound and
    prevents it from being reclassified.
    """

    handoff: bool = False
    terminal: bool = False
    continue_turn: bool = False


def _normalized_answer(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
        and unicodedata.category(character) != "Cf"
    )


def _answer_kind(value: object) -> str:
    text = _normalized_answer(value)
    if _YES.fullmatch(text):
        return "yes"
    if _NO.fullmatch(text):
        return "no"
    return "other"


def prepare_secretaria_offer(
    conversation: Conversation,
    *,
    outbound_message_id: uuid.UUID,
    replace_terminal: bool = False,
) -> None:
    """Stage an offer beside the still-unsent durable IA reply intent."""

    if getattr(conversation, "secretaria_oferta_message_id", None) == outbound_message_id:
        return
    if getattr(conversation, "secretaria_oferta_estado", None) in _ACTIVE_STATES:
        # The Conversation lock means another active offer belongs to an older
        # response.  Do not renew or overwrite it from a retry.
        return
    if getattr(conversation, "secretaria_oferta_estado", None) is not None and not replace_terminal:
        # A retry of an older durable response must never revive a consumed,
        # cancelled or expired newer offer.
        return
    conversation.secretaria_oferta_estado = OFFER_PREPARED
    conversation.secretaria_oferta_message_id = outbound_message_id
    conversation.secretaria_oferta_expira_em = None
    conversation.secretaria_oferta_resposta_message_id = None


def cancel_secretaria_offer_for_delivery(
    conversation: Conversation,
    *,
    outbound_message_id: uuid.UUID,
) -> bool:
    """Cancel only a preparation tied to an unsuccessful delivery boundary."""

    if (
        getattr(conversation, "secretaria_oferta_message_id", None) != outbound_message_id
        or getattr(conversation, "secretaria_oferta_estado", None) not in _ACTIVE_STATES
    ):
        return False
    conversation.secretaria_oferta_estado = OFFER_CANCELLED
    conversation.secretaria_oferta_expira_em = None
    return True


def _anchor_exists(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    confirmed: bool,
) -> bool:
    statement = select(Message.id).where(
        Message.id == message_id,
        Message.igreja_id == igreja_id,
        Message.conversation_id == conversation_id,
        Message.direcao == "out",
        Message.autor == "ia",
    )
    if confirmed:
        statement = statement.where(Message.agent_reply_state == AGENT_REPLY_CONFIRMED)
    return session.execute(statement).scalar_one_or_none() is not None


def _cancel_for_inbound(
    conversation: Conversation,
    *,
    inbound_message_id: uuid.UUID | None = None,
    state: str = OFFER_CANCELLED,
) -> None:
    conversation.secretaria_oferta_estado = state
    conversation.secretaria_oferta_expira_em = None
    conversation.secretaria_oferta_resposta_message_id = inbound_message_id


def _is_stale_term_acceptance(
    current_text: object,
    *,
    consent_needs_reaccept: bool,
) -> bool:
    """Only bind an obsolete offer when the inbound could otherwise accept a term."""

    return (
        consent_needs_reaccept
        and isinstance(current_text, str)
        and consent_rules.is_acceptance(current_text)
    )


def resolve_secretaria_offer_inbound(
    session: Session,
    conversation: Conversation,
    *,
    igreja_id: uuid.UUID,
    inbound_message_id: uuid.UUID,
    current_text: object,
    consent_needs_reaccept: bool = False,
    now: dt.datetime | None = None,
) -> OfferInboundResolution:
    """Resolve one anchored inbound while its Conversation row is locked."""

    state = getattr(conversation, "secretaria_oferta_estado", None)
    anchor_id = getattr(conversation, "secretaria_oferta_message_id", None)
    response_id = getattr(conversation, "secretaria_oferta_resposta_message_id", None)
    if state is None or anchor_id is None:
        return OfferInboundResolution(continue_turn=True)
    if state in _TERMINAL_STATES:
        if (
            state in {OFFER_CONSUMED, OFFER_CANCELLED, OFFER_EXPIRED}
            and response_id == inbound_message_id
        ):
            return OfferInboundResolution(terminal=True)
        return OfferInboundResolution(continue_turn=True)
    if state not in _ACTIVE_STATES:
        _cancel_for_inbound(conversation, inbound_message_id=inbound_message_id)
        return OfferInboundResolution(terminal=True)
    if not _anchor_exists(
        session,
        igreja_id=igreja_id,
        conversation_id=conversation.id,
        message_id=anchor_id,
        confirmed=state == OFFER_PENDING,
    ):
        bind_stale_acceptance = _is_stale_term_acceptance(
            current_text,
            consent_needs_reaccept=consent_needs_reaccept,
        )
        _cancel_for_inbound(
            conversation,
            inbound_message_id=(inbound_message_id if bind_stale_acceptance else None),
        )
        return OfferInboundResolution(
            terminal=bind_stale_acceptance,
            continue_turn=not bind_stale_acceptance,
        )

    if state == OFFER_ACCEPT_WAITING:
        if response_id == inbound_message_id:
            return OfferInboundResolution(terminal=True)
        answer = _answer_kind(current_text)
        if answer == "yes":
            return OfferInboundResolution(terminal=True)
        if answer == "no":
            _cancel_for_inbound(conversation, inbound_message_id=inbound_message_id)
            return OfferInboundResolution(terminal=True)
        if _is_stale_term_acceptance(
            current_text,
            consent_needs_reaccept=consent_needs_reaccept,
        ):
            _cancel_for_inbound(conversation, inbound_message_id=inbound_message_id)
            return OfferInboundResolution(terminal=True)
        _cancel_for_inbound(conversation)
        return OfferInboundResolution(continue_turn=True)

    answer = _answer_kind(current_text)
    if state == OFFER_PREPARED:
        if answer == "yes":
            conversation.secretaria_oferta_estado = OFFER_ACCEPT_WAITING
            conversation.secretaria_oferta_resposta_message_id = inbound_message_id
            return OfferInboundResolution(terminal=True)
        if answer == "other" and _is_stale_term_acceptance(
            current_text,
            consent_needs_reaccept=consent_needs_reaccept,
        ):
            _cancel_for_inbound(conversation, inbound_message_id=inbound_message_id)
            return OfferInboundResolution(terminal=True)
        _cancel_for_inbound(
            conversation,
            inbound_message_id=(inbound_message_id if answer == "no" else None),
        )
        return OfferInboundResolution(
            terminal=answer == "no",
            continue_turn=answer == "other",
        )

    expires_at = getattr(conversation, "secretaria_oferta_expira_em", None)
    observed_now = now or session.execute(select(func.clock_timestamp())).scalar_one()
    if expires_at is None or expires_at <= observed_now:
        bind_stale_acceptance = _is_stale_term_acceptance(
            current_text,
            consent_needs_reaccept=consent_needs_reaccept,
        )
        _cancel_for_inbound(
            conversation,
            inbound_message_id=(inbound_message_id if bind_stale_acceptance else None),
            state=OFFER_EXPIRED,
        )
        return OfferInboundResolution(
            terminal=bind_stale_acceptance,
            continue_turn=not bind_stale_acceptance,
        )
    if answer == "other" and _is_stale_term_acceptance(
        current_text,
        consent_needs_reaccept=consent_needs_reaccept,
    ):
        _cancel_for_inbound(conversation, inbound_message_id=inbound_message_id)
        return OfferInboundResolution(terminal=True)
    if answer == "yes":
        _cancel_for_inbound(
            conversation,
            inbound_message_id=inbound_message_id,
            state=OFFER_CONSUMED,
        )
        return OfferInboundResolution(handoff=True, terminal=True)
    _cancel_for_inbound(
        conversation,
        inbound_message_id=(inbound_message_id if answer == "no" else None),
    )
    return OfferInboundResolution(
        terminal=answer == "no",
        continue_turn=answer == "other",
    )


def promote_secretaria_offer_after_delivery(
    session: Session,
    conversation: Conversation,
    *,
    outbound_message_id: uuid.UUID,
) -> bool:
    """Promote a confirmed offer or report a recorded early acceptance.

    The SQL assignment uses the database clock, so the ten-minute window begins
    only after the durable `ia_em_transporte -> ia` confirmation transaction.
    """

    if getattr(conversation, "secretaria_oferta_message_id", None) != outbound_message_id:
        return False
    if getattr(conversation, "secretaria_oferta_estado", None) == OFFER_PREPARED:
        transitioned = session.execute(
            update(Conversation)
            .where(
                Conversation.id == conversation.id,
                Conversation.igreja_id == conversation.igreja_id,
                Conversation.secretaria_oferta_estado == OFFER_PREPARED,
                Conversation.secretaria_oferta_message_id == outbound_message_id,
            )
            .values(
                secretaria_oferta_estado=OFFER_PENDING,
                secretaria_oferta_expira_em=(
                    func.clock_timestamp() + text("interval '10 minutes'")
                ),
            )
            .returning(Conversation.id)
        ).scalar_one_or_none()
        if transitioned is not None:
            session.refresh(conversation)
        return False
    if getattr(conversation, "secretaria_oferta_estado", None) == OFFER_ACCEPT_WAITING:
        conversation.secretaria_oferta_estado = OFFER_CONSUMED
        conversation.secretaria_oferta_expira_em = None
        return True
    return False
