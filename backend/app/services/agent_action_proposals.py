"""Durable, closed action proposals for the S3 WhatsApp seam.

This module never interprets a user message or grants authority.  Runtime will
pass a server-resolved privilege context and a deterministic confirmation
disposition in a later integration step.
"""

from __future__ import annotations

import hashlib
import json
import uuid
import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AgentActionProposal, AgentActionReceipt, Conversation, Message
from app.db.rls_observability import require_tenant_scope
from app.domain.agent_reply import AGENT_REPLY_CONFIRMED
from app.domain.consolidation import VALID_VINCULOS
from app.services.whatsapp_privilege import PrivilegeContext, resolve_whatsapp_privilege_context


class ProposalContractError(ValueError):
    """A caller crossed the closed S3 proposal contract."""


class ProposalExecutionDenied(ProposalContractError):
    """A human-equivalent adapter refused an otherwise valid proposal."""


class AgentAction(StrEnum):
    REGISTRAR_DECISAO = "registrar_decisao"
    MARCAR_PRESENCA = "marcar_presenca"


class ProposalDisposition(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"
    OTHER = "other"


class ProposalResolutionStatus(StrEnum):
    NO_PENDING = "no_pending"
    DELIVERY_UNCERTAIN = "delivery_uncertain"
    CONTINUE = "continue"
    EXECUTED = "executed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    RECEIPT = "receipt"


def parse_agent_action(value: object) -> AgentAction:
    if type(value) is AgentAction:
        return value
    if type(value) is not str:
        raise ProposalContractError("ação inválida")
    try:
        return AgentAction(value)
    except ValueError as exc:
        raise ProposalContractError("ação inválida") from exc


def parse_proposal_disposition(value: object) -> ProposalDisposition:
    if type(value) is ProposalDisposition:
        return value
    if type(value) is not str:
        raise ProposalContractError("confirmação inválida")
    try:
        return ProposalDisposition(value)
    except ValueError as exc:
        raise ProposalContractError("confirmação inválida") from exc


@dataclass(frozen=True, slots=True)
class ProposalTarget:
    """An opaque server-resolved target, never a handle supplied by a model."""

    kind: str
    id: uuid.UUID

    def __post_init__(self) -> None:
        if self.kind != "pessoa" or type(self.id) is not uuid.UUID or self.id.int == 0:
            raise ProposalContractError("alvo inválido")


@dataclass(frozen=True, slots=True)
class PreparedActionProposal:
    proposal_id: uuid.UUID
    action: AgentAction
    summary_sha256: str


@dataclass(frozen=True, slots=True)
class PendingActionProposal:
    proposal_id: uuid.UUID
    action: AgentAction
    summary_message_id: uuid.UUID
    expires_at: dt.datetime


@dataclass(frozen=True, slots=True)
class ActionEffect:
    """Server adapter result with a generic receipt and opaque domain reference."""

    receipt_text: str
    opaque_effect_id: uuid.UUID

    def __post_init__(self) -> None:
        if type(self.opaque_effect_id) is not uuid.UUID or self.opaque_effect_id.int == 0:
            raise ProposalContractError("resultado de ação inválido")
        if self.receipt_text != "Registro confirmado.":
            raise ProposalContractError("recibo inválido")


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    proposal_id: uuid.UUID
    igreja_id: uuid.UUID
    conversation_id: uuid.UUID
    confirmation_message_id: uuid.UUID
    privilege_context: PrivilegeContext
    action: AgentAction
    target: ProposalTarget
    arguments: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    receipt_id: uuid.UUID
    proposal_id: uuid.UUID
    confirmation_message_id: uuid.UUID
    receipt_text: str
    opaque_effect_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ProposalResolution:
    status: ProposalResolutionStatus
    proposal_id: uuid.UUID | None = None
    receipt_id: uuid.UUID | None = None
    confirmation_message_id: uuid.UUID | None = None
    receipt: ActionReceipt | None = None


def _canonical_uuid(value: object, *, field: str) -> str:
    if type(value) is not str:
        raise ProposalContractError(f"{field} inválido")
    try:
        parsed = uuid.UUID(value)
    except (TypeError, ValueError) as exc:
        raise ProposalContractError(f"{field} inválido") from exc
    if parsed.int == 0 or str(parsed) != value:
        raise ProposalContractError(f"{field} inválido")
    return value


def canonical_action_arguments(
    action: AgentAction,
    target: ProposalTarget,
    arguments: Mapping[str, object],
) -> dict[str, object]:
    """Accept only the two human-adapter payloads approved for S3."""

    if type(action) is not AgentAction or type(arguments) is not dict:
        raise ProposalContractError("argumentos inválidos")
    pessoa_id = _canonical_uuid(arguments.get("pessoa_id"), field="pessoa_id")
    if pessoa_id != str(target.id):
        raise ProposalContractError("alvo divergente")
    if action is AgentAction.REGISTRAR_DECISAO:
        if set(arguments) != {"pessoa_id", "vinculo", "celula_id"}:
            raise ProposalContractError("argumentos inválidos")
        vinculo = arguments["vinculo"]
        celula_id = arguments["celula_id"]
        if type(vinculo) is not str or vinculo not in VALID_VINCULOS:
            raise ProposalContractError("vínculo inválido")
        if celula_id is not None:
            celula_id = _canonical_uuid(celula_id, field="celula_id")
        return {"celula_id": celula_id, "pessoa_id": pessoa_id, "vinculo": vinculo}
    if action is AgentAction.MARCAR_PRESENCA:
        if set(arguments) != {"pessoa_id", "reuniao_id"}:
            raise ProposalContractError("argumentos inválidos")
        return {
            "pessoa_id": pessoa_id,
            "reuniao_id": _canonical_uuid(arguments["reuniao_id"], field="reuniao_id"),
        }
    raise ProposalContractError("ação inválida")


def canonical_arguments_sha256(arguments: Mapping[str, object]) -> str:
    """Return the stable digest retained with a proposal, never raw text."""

    try:
        encoded = json.dumps(
            arguments,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProposalContractError("argumentos inválidos") from exc
    return hashlib.sha256(encoded).hexdigest()


_PROPOSAL_PREPARED = "preparada"
_PROPOSAL_PENDING = "pendente"
_PROPOSAL_EXECUTED = "executada"
_PROPOSAL_REJECTED = "rejeitada"
_PROPOSAL_CANCELLED = "cancelada"
_PROPOSAL_EXPIRED = "expirada"
_PROPOSAL_ACTIVE = frozenset({_PROPOSAL_PREPARED, _PROPOSAL_PENDING})
_PROPOSAL_TTL = dt.timedelta(minutes=10)
_MAX_SUMMARY_BYTES = 600


def _require_uuid(value: object, *, name: str) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        raise ProposalContractError(f"{name} inválido")
    return value


def _utc(value: object) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None:
        raise ProposalContractError("relógio inválido")
    return value.astimezone(dt.timezone.utc)


def _database_now(session: Session, now: dt.datetime | None) -> dt.datetime:
    if now is not None:
        return _utc(now)
    return _utc(session.execute(select(func.clock_timestamp())).scalar_one())


def _summary_sha256(summary: object) -> str:
    if type(summary) is not str or not summary.strip():
        raise ProposalContractError("resumo inválido")
    encoded = summary.encode("utf-8")
    if len(encoded) > _MAX_SUMMARY_BYTES:
        raise ProposalContractError("resumo inválido")
    return hashlib.sha256(encoded).hexdigest()


def _valid_digest(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _require_context(
    context: object,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    inbound_message_id: uuid.UUID,
) -> PrivilegeContext:
    if type(context) is not PrivilegeContext:
        raise ProposalContractError("contexto de privilégio inválido")
    if (
        context.igreja_id != igreja_id
        or context.conversation_id != conversation_id
        or context.inbound_message_id != inbound_message_id
        or not _valid_digest(context.scope_fingerprint)
        or not _valid_digest(context.authorization_fingerprint)
    ):
        raise ProposalContractError("contexto de privilégio divergente")
    return context


def _lock_conversation(
    session: Session, *, igreja_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation | None:
    return session.execute(
        select(Conversation)
        .where(Conversation.igreja_id == igreja_id, Conversation.id == conversation_id)
        .with_for_update()
    ).scalar_one_or_none()


def _inbound_exists(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
) -> Message | None:
    return session.execute(
        select(Message).where(
            Message.igreja_id == igreja_id,
            Message.conversation_id == conversation_id,
            Message.id == message_id,
            Message.direcao == "in",
        )
    ).scalar_one_or_none()


def _load_active_proposal(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    lock: bool,
) -> AgentActionProposal | None:
    statement = (
        select(AgentActionProposal)
        .where(
            AgentActionProposal.igreja_id == igreja_id,
            AgentActionProposal.conversation_id == conversation_id,
            AgentActionProposal.state.in_(_PROPOSAL_ACTIVE),
        )
        .order_by(AgentActionProposal.created_at.desc(), AgentActionProposal.id.desc())
        .limit(1)
    )
    if lock:
        statement = statement.with_for_update()
    return session.execute(statement).scalar_one_or_none()


def _pending_from_row(value: AgentActionProposal) -> PendingActionProposal | None:
    try:
        action = parse_agent_action(value.action)
        summary_id = _require_uuid(value.summary_message_id, name="âncora do resumo")
        expires_at = _utc(value.expires_at)
    except ProposalContractError:
        return None
    return PendingActionProposal(
        proposal_id=_require_uuid(value.id, name="proposta"),
        action=action,
        summary_message_id=summary_id,
        expires_at=expires_at,
    )


def _set_terminal(
    proposal: AgentActionProposal,
    *,
    state: str,
    reason: str,
    confirmation_message_id: uuid.UUID | None,
) -> None:
    proposal.state = state
    proposal.terminal_reason = reason
    proposal.confirmation_message_id = confirmation_message_id
    proposal.expires_at = None


def prepare_action_proposal(
    session: Session,
    *,
    context: PrivilegeContext,
    inbound_message_id: uuid.UUID,
    action: AgentAction,
    target: ProposalTarget,
    arguments: Mapping[str, object],
    summary: str,
    summary_message_id: uuid.UUID | None = None,
    now: dt.datetime | None = None,
) -> PreparedActionProposal:
    """Stage one proposal beside a reserved outbound reply, without a commit."""

    igreja_id = _require_uuid(context.igreja_id, name="igreja")
    conversation_id = _require_uuid(context.conversation_id, name="conversa")
    inbound_message_id = _require_uuid(inbound_message_id, name="âncora inbound")
    context = _require_context(
        context,
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        inbound_message_id=inbound_message_id,
    )
    action = parse_agent_action(action)
    if summary_message_id is not None:
        summary_message_id = _require_uuid(summary_message_id, name="resumo")
    canonical_arguments = canonical_action_arguments(action, target, arguments)
    arguments_sha256 = canonical_arguments_sha256(canonical_arguments)
    summary_sha256 = _summary_sha256(summary)
    require_tenant_scope(
        session, expected_igreja_id=igreja_id, source="agent_action_proposals"
    )
    conversation = _lock_conversation(
        session, igreja_id=igreja_id, conversation_id=conversation_id
    )
    if (
        conversation is None
        or getattr(conversation, "estado", None) == "humano"
        or getattr(conversation, "assumido_por", None) is not None
        or getattr(conversation, "secretaria_oferta_estado", None)
        in {"preparada", "aceite_aguardando_ancora", "pendente"}
    ):
        raise ProposalContractError("conversa inelegível")
    if _inbound_exists(
        session,
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        message_id=inbound_message_id,
    ) is None:
        raise ProposalContractError("âncora inbound ausente")
    if summary_message_id is not None:
        staged_summary = session.execute(
            select(Message)
            .where(
                Message.igreja_id == igreja_id,
                Message.conversation_id == conversation_id,
                Message.id == summary_message_id,
                Message.direcao == "out",
                Message.autor == "ia",
            )
            .with_for_update()
        ).scalar_one_or_none()
        if (
            staged_summary is None
            or _summary_sha256(getattr(staged_summary, "texto", None)) != summary_sha256
        ):
            raise ProposalContractError("resumo reservado ausente")
    source_existing = session.execute(
        select(AgentActionProposal)
        .where(
            AgentActionProposal.igreja_id == igreja_id,
            AgentActionProposal.source_message_id == inbound_message_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if source_existing is not None:
        if (
            source_existing.conversation_id == conversation_id
            and source_existing.action == action.value
            and source_existing.target_kind == target.kind
            and source_existing.target_id == target.id
            and source_existing.arguments_sha256 == arguments_sha256
            and source_existing.summary_sha256 == summary_sha256
            and source_existing.summary_message_id == summary_message_id
            and source_existing.state in _PROPOSAL_ACTIVE
        ):
            return PreparedActionProposal(source_existing.id, action, summary_sha256)
        raise ProposalContractError("proposta da âncora já resolvida")
    if _load_active_proposal(
        session, igreja_id=igreja_id, conversation_id=conversation_id, lock=True
    ) is not None:
        raise ProposalContractError("conversa já possui proposta ativa")
    proposal = AgentActionProposal(
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        actor_pessoa_id=context.pessoa_id,
        actor_app_user_id=context.app_user_id,
        source_message_id=inbound_message_id,
        action=action.value,
        target_kind=target.kind,
        target_id=target.id,
        arguments_json=canonical_arguments,
        arguments_sha256=arguments_sha256,
        scope_fingerprint=context.scope_fingerprint,
        summary_sha256=summary_sha256,
        state=_PROPOSAL_PREPARED,
        summary_message_id=summary_message_id,
        confirmation_message_id=None,
        delivered_at=None,
        expires_at=None,
        executed_at=None,
        terminal_reason=None,
    )
    session.add(proposal)
    session.flush()
    return PreparedActionProposal(
        proposal_id=_require_uuid(proposal.id, name="proposta"),
        action=action,
        summary_sha256=summary_sha256,
    )


def promote_action_proposal_after_delivery(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    proposal_id: uuid.UUID,
    summary_message_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> PendingActionProposal:
    """Start the ten-minute confirmation TTL only after the summary was sent.

    The caller supplies an already-confirmed outbound ledger row.  This helper
    never transports, commits, or turns a prepared proposal into pending from
    an unconfirmed reply.
    """

    igreja_id = _require_uuid(igreja_id, name="igreja")
    conversation_id = _require_uuid(conversation_id, name="conversa")
    proposal_id = _require_uuid(proposal_id, name="proposta")
    summary_message_id = _require_uuid(summary_message_id, name="resumo")
    require_tenant_scope(
        session, expected_igreja_id=igreja_id, source="agent_action_proposals"
    )
    if _lock_conversation(
        session, igreja_id=igreja_id, conversation_id=conversation_id
    ) is None:
        raise ProposalContractError("conversa ausente")
    proposal = session.execute(
        select(AgentActionProposal)
        .where(
            AgentActionProposal.igreja_id == igreja_id,
            AgentActionProposal.id == proposal_id,
            AgentActionProposal.conversation_id == conversation_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if proposal is None:
        raise ProposalContractError("proposta ausente")
    if proposal.state == _PROPOSAL_PENDING:
        if proposal.summary_message_id != summary_message_id:
            raise ProposalContractError("resumo divergente")
        pending = _pending_from_row(proposal)
        if pending is None:
            raise ProposalContractError("proposta pendente inválida")
        return pending
    if proposal.state != _PROPOSAL_PREPARED:
        raise ProposalContractError("proposta terminal")
    if (
        proposal.summary_message_id is not None
        and proposal.summary_message_id != summary_message_id
    ):
        raise ProposalContractError("resumo divergente")
    summary = session.execute(
        select(Message)
        .where(
            Message.igreja_id == igreja_id,
            Message.conversation_id == conversation_id,
            Message.id == summary_message_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if (
        summary is None
        or getattr(summary, "direcao", None) != "out"
        or getattr(summary, "autor", None) != "ia"
        or getattr(summary, "agent_reply_state", None) != AGENT_REPLY_CONFIRMED
        or _summary_sha256(getattr(summary, "texto", None)) != proposal.summary_sha256
    ):
        raise ProposalContractError("resumo não confirmado")
    delivered_at = _database_now(session, now)
    proposal.summary_message_id = summary_message_id
    proposal.state = _PROPOSAL_PENDING
    proposal.delivered_at = delivered_at
    proposal.expires_at = delivered_at + _PROPOSAL_TTL
    proposal.terminal_reason = None
    session.flush()
    pending = _pending_from_row(proposal)
    if pending is None:
        raise ProposalContractError("proposta pendente inválida")
    return pending


def _proposal_by_confirmation(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    confirmation_message_id: uuid.UUID,
) -> AgentActionProposal | None:
    return session.execute(
        select(AgentActionProposal)
        .where(
            AgentActionProposal.igreja_id == igreja_id,
            AgentActionProposal.conversation_id == conversation_id,
            AgentActionProposal.confirmation_message_id == confirmation_message_id,
        )
        .with_for_update()
    ).scalar_one_or_none()


def _receipt_from_row(value: AgentActionReceipt) -> ActionReceipt | None:
    try:
        return ActionReceipt(
            receipt_id=_require_uuid(value.id, name="recibo"),
            proposal_id=_require_uuid(value.proposal_id, name="proposta"),
            confirmation_message_id=_require_uuid(
                value.confirmation_message_id, name="confirmação"
            ),
            receipt_text=_require_receipt_text(value.receipt_text),
            opaque_effect_id=uuid.UUID(_require_effect_reference(value.effect_reference)),
        )
    except (ProposalContractError, TypeError, ValueError):
        return None


def _require_receipt_text(value: object) -> str:
    if value != "Registro confirmado.":
        raise ProposalContractError("recibo inválido")
    return value


def _require_effect_reference(value: object) -> str:
    if type(value) is not str:
        raise ProposalContractError("resultado de ação inválido")
    try:
        parsed = uuid.UUID(value)
    except (TypeError, ValueError) as exc:
        raise ProposalContractError("resultado de ação inválido") from exc
    if parsed.int == 0 or str(parsed) != value:
        raise ProposalContractError("resultado de ação inválido")
    return value


def _terminal_status(state: object) -> ProposalResolutionStatus:
    if state == _PROPOSAL_EXECUTED:
        return ProposalResolutionStatus.RECEIPT
    if state == _PROPOSAL_REJECTED:
        return ProposalResolutionStatus.REJECTED
    if state == _PROPOSAL_EXPIRED:
        return ProposalResolutionStatus.EXPIRED
    return ProposalResolutionStatus.CANCELLED


def _terminal_replay(
    session: Session,
    *,
    proposal: AgentActionProposal,
    confirmation_message_id: uuid.UUID,
) -> ProposalResolution:
    status = _terminal_status(proposal.state)
    if status is not ProposalResolutionStatus.RECEIPT:
        return ProposalResolution(
            status=status,
            proposal_id=_require_uuid(proposal.id, name="proposta"),
            confirmation_message_id=confirmation_message_id,
        )
    receipt_row = session.execute(
        select(AgentActionReceipt)
        .where(
            AgentActionReceipt.igreja_id == proposal.igreja_id,
            AgentActionReceipt.proposal_id == proposal.id,
            AgentActionReceipt.conversation_id == proposal.conversation_id,
            AgentActionReceipt.confirmation_message_id == confirmation_message_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    receipt = _receipt_from_row(receipt_row) if receipt_row is not None else None
    if receipt is None:
        raise ProposalContractError("recibo ausente")
    return ProposalResolution(
        status=ProposalResolutionStatus.RECEIPT,
        proposal_id=_require_uuid(proposal.id, name="proposta"),
        receipt_id=receipt.receipt_id,
        confirmation_message_id=confirmation_message_id,
        receipt=receipt,
    )


def lookup_action_proposal(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> ProposalResolution:
    """Inspect the single active proposal before the normal router runs."""

    igreja_id = _require_uuid(igreja_id, name="igreja")
    conversation_id = _require_uuid(conversation_id, name="conversa")
    require_tenant_scope(
        session, expected_igreja_id=igreja_id, source="agent_action_proposals"
    )
    if _lock_conversation(
        session, igreja_id=igreja_id, conversation_id=conversation_id
    ) is None:
        return ProposalResolution(ProposalResolutionStatus.NO_PENDING)
    proposal = _load_active_proposal(
        session, igreja_id=igreja_id, conversation_id=conversation_id, lock=True
    )
    if proposal is None:
        return ProposalResolution(ProposalResolutionStatus.NO_PENDING)
    proposal_id = _require_uuid(proposal.id, name="proposta")
    if proposal.state == _PROPOSAL_PREPARED:
        return ProposalResolution(
            ProposalResolutionStatus.DELIVERY_UNCERTAIN, proposal_id=proposal_id
        )
    pending = _pending_from_row(proposal)
    if pending is None:
        _set_terminal(
            proposal,
            state=_PROPOSAL_CANCELLED,
            reason="invalid_pending",
            confirmation_message_id=None,
        )
        return ProposalResolution(ProposalResolutionStatus.CANCELLED, proposal_id=proposal_id)
    if pending.expires_at <= _database_now(session, now):
        _set_terminal(
            proposal,
            state=_PROPOSAL_EXPIRED,
            reason="expired",
            confirmation_message_id=None,
        )
        return ProposalResolution(ProposalResolutionStatus.EXPIRED, proposal_id=proposal_id)
    return ProposalResolution(ProposalResolutionStatus.CONTINUE, proposal_id=proposal_id)


def invalidate_action_proposal_for_delivery(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    proposal_id: uuid.UUID,
) -> ProposalResolution:
    """Cancel a proposal whose outbound summary will never become confirmed.

    A failed, ambiguous, or suppressed summary is not an offer.  The terminal
    transition frees the conversation while preserving source idempotency and
    never alters an already executed proposal.
    """

    igreja_id = _require_uuid(igreja_id, name="igreja")
    conversation_id = _require_uuid(conversation_id, name="conversa")
    proposal_id = _require_uuid(proposal_id, name="proposta")
    require_tenant_scope(
        session, expected_igreja_id=igreja_id, source="agent_action_proposals"
    )
    if _lock_conversation(
        session, igreja_id=igreja_id, conversation_id=conversation_id
    ) is None:
        return ProposalResolution(ProposalResolutionStatus.NO_PENDING)
    proposal = session.execute(
        select(AgentActionProposal)
        .where(
            AgentActionProposal.igreja_id == igreja_id,
            AgentActionProposal.conversation_id == conversation_id,
            AgentActionProposal.id == proposal_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if proposal is None:
        return ProposalResolution(ProposalResolutionStatus.NO_PENDING)
    if proposal.state in _PROPOSAL_ACTIVE:
        _set_terminal(
            proposal,
            state=_PROPOSAL_CANCELLED,
            reason="delivery_unavailable",
            confirmation_message_id=None,
        )
        return ProposalResolution(ProposalResolutionStatus.CANCELLED, proposal_id=proposal_id)
    return ProposalResolution(
        _terminal_status(proposal.state), proposal_id=proposal_id
    )


def _confirmed_summary_is_current(
    session: Session,
    *,
    proposal: AgentActionProposal,
) -> bool:
    summary_id = proposal.summary_message_id
    if type(summary_id) is not uuid.UUID:
        return False
    summary = session.execute(
        select(Message)
        .where(
            Message.igreja_id == proposal.igreja_id,
            Message.conversation_id == proposal.conversation_id,
            Message.id == summary_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if (
        summary is None
        or getattr(summary, "direcao", None) != "out"
        or getattr(summary, "autor", None) != "ia"
        or getattr(summary, "agent_reply_state", None) != AGENT_REPLY_CONFIRMED
    ):
        return False
    try:
        return _summary_sha256(getattr(summary, "texto", None)) == proposal.summary_sha256
    except ProposalContractError:
        return False


def _confirmation_is_after_delivery(
    session: Session,
    *,
    proposal: AgentActionProposal,
    confirmation_message_id: uuid.UUID,
) -> bool:
    inbound = _inbound_exists(
        session,
        igreja_id=proposal.igreja_id,
        conversation_id=proposal.conversation_id,
        message_id=confirmation_message_id,
    )
    try:
        return (
            inbound is not None
            and _utc(getattr(inbound, "criado_em", None))
            > _utc(proposal.delivered_at)
        )
    except ProposalContractError:
        return False


def _proposal_context_is_current(
    session: Session,
    *,
    proposal: AgentActionProposal,
    confirmation_message_id: uuid.UUID,
    session_secret: str | None,
    now: dt.datetime | None,
) -> PrivilegeContext | None:
    context = resolve_whatsapp_privilege_context(
        session,
        igreja_id=proposal.igreja_id,
        conversation_id=proposal.conversation_id,
        inbound_message_id=confirmation_message_id,
        sensitive=False,
        session_secret=session_secret,
        now=now,
    )
    if type(context) is not PrivilegeContext:
        return None
    if (
        context.pessoa_id != proposal.actor_pessoa_id
        or context.app_user_id != proposal.actor_app_user_id
        or context.scope_fingerprint != proposal.scope_fingerprint
    ):
        return None
    return context


def _active_proposal_for_resolution(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    confirmation_message_id: uuid.UUID,
) -> tuple[Conversation | None, AgentActionProposal | None, AgentActionProposal | None]:
    """Lock Conversation before proposal/message rows and find a replay first."""

    conversation = _lock_conversation(
        session, igreja_id=igreja_id, conversation_id=conversation_id
    )
    if conversation is None:
        return None, None, None
    replay = _proposal_by_confirmation(
        session,
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        confirmation_message_id=confirmation_message_id,
    )
    if replay is not None:
        return conversation, None, replay
    active = _load_active_proposal(
        session, igreja_id=igreja_id, conversation_id=conversation_id, lock=True
    )
    return conversation, active, None


def _cancel_active_for_context(
    proposal: AgentActionProposal,
    *,
    confirmation_message_id: uuid.UUID,
    reason: str,
) -> ProposalResolution:
    proposal_id = _require_uuid(proposal.id, name="proposta")
    _set_terminal(
        proposal,
        state=_PROPOSAL_CANCELLED,
        reason=reason,
        confirmation_message_id=confirmation_message_id,
    )
    return ProposalResolution(
        ProposalResolutionStatus.CANCELLED,
        proposal_id=proposal_id,
        confirmation_message_id=confirmation_message_id,
    )


def _execution_context(
    proposal: AgentActionProposal,
    *,
    confirmation_message_id: uuid.UUID,
    privilege_context: PrivilegeContext,
) -> ExecutionContext:
    try:
        action = parse_agent_action(proposal.action)
        target = ProposalTarget(
            kind=proposal.target_kind,
            id=_require_uuid(proposal.target_id, name="alvo"),
        )
        arguments = canonical_action_arguments(action, target, proposal.arguments_json)
    except (ProposalContractError, TypeError, ValueError) as exc:
        raise ProposalContractError("proposta persistida inválida") from exc
    if canonical_arguments_sha256(arguments) != proposal.arguments_sha256:
        raise ProposalContractError("proposta persistida divergente")
    return ExecutionContext(
        proposal_id=_require_uuid(proposal.id, name="proposta"),
        igreja_id=_require_uuid(proposal.igreja_id, name="igreja"),
        conversation_id=_require_uuid(proposal.conversation_id, name="conversa"),
        confirmation_message_id=confirmation_message_id,
        privilege_context=privilege_context,
        action=action,
        target=target,
        arguments=arguments,
    )


def _new_receipt(
    proposal: AgentActionProposal,
    *,
    confirmation_message_id: uuid.UUID,
    effect: ActionEffect,
) -> AgentActionReceipt:
    if type(effect) is not ActionEffect:
        raise ProposalContractError("resultado de ação inválido")
    receipt_text = _require_receipt_text(effect.receipt_text)
    return AgentActionReceipt(
        igreja_id=proposal.igreja_id,
        proposal_id=proposal.id,
        conversation_id=proposal.conversation_id,
        confirmation_message_id=confirmation_message_id,
        outcome=_PROPOSAL_EXECUTED,
        effect_reference=str(effect.opaque_effect_id),
        receipt_text=receipt_text,
    )


def resolve_and_execute_action_proposal(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    confirmation_message_id: uuid.UUID,
    disposition: ProposalDisposition,
    execute: Callable[[ExecutionContext], ActionEffect],
    session_secret: str | None = None,
    now: dt.datetime | None = None,
) -> ProposalResolution:
    """Resolve one inbound against the active proposal in one transaction.

    Confirmation, revalidation, the domain callback, proposal execution and a
    receipt intent share the caller's transaction.  The function intentionally
    has no ``commit`` and performs no transport.
    """

    igreja_id = _require_uuid(igreja_id, name="igreja")
    conversation_id = _require_uuid(conversation_id, name="conversa")
    confirmation_message_id = _require_uuid(
        confirmation_message_id, name="confirmação"
    )
    disposition = parse_proposal_disposition(disposition)
    if not callable(execute):
        raise ProposalContractError("executor inválido")
    require_tenant_scope(
        session, expected_igreja_id=igreja_id, source="agent_action_proposals"
    )
    _, proposal, replay = _active_proposal_for_resolution(
        session,
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        confirmation_message_id=confirmation_message_id,
    )
    if replay is not None:
        return _terminal_replay(
            session,
            proposal=replay,
            confirmation_message_id=confirmation_message_id,
        )
    if proposal is None:
        return ProposalResolution(ProposalResolutionStatus.NO_PENDING)
    proposal_id = _require_uuid(proposal.id, name="proposta")
    if proposal.state == _PROPOSAL_PREPARED:
        return ProposalResolution(
            ProposalResolutionStatus.DELIVERY_UNCERTAIN, proposal_id=proposal_id
        )
    pending = _pending_from_row(proposal)
    if pending is None:
        return _cancel_active_for_context(
            proposal,
            confirmation_message_id=confirmation_message_id,
            reason="invalid_pending",
        )
    checked_at = _database_now(session, now)
    if pending.expires_at <= checked_at:
        _set_terminal(
            proposal,
            state=_PROPOSAL_EXPIRED,
            reason="expired",
            confirmation_message_id=confirmation_message_id,
        )
        return ProposalResolution(
            ProposalResolutionStatus.EXPIRED,
            proposal_id=proposal_id,
            confirmation_message_id=confirmation_message_id,
        )
    if not _confirmation_is_after_delivery(
        session, proposal=proposal, confirmation_message_id=confirmation_message_id
    ):
        return ProposalResolution(ProposalResolutionStatus.CONTINUE, proposal_id=proposal_id)
    if disposition is ProposalDisposition.OTHER:
        _set_terminal(
            proposal,
            state=_PROPOSAL_CANCELLED,
            reason="other_inbound",
            confirmation_message_id=None,
        )
        return ProposalResolution(ProposalResolutionStatus.CONTINUE, proposal_id=proposal_id)
    if disposition is ProposalDisposition.REJECT:
        _set_terminal(
            proposal,
            state=_PROPOSAL_REJECTED,
            reason="rejected",
            confirmation_message_id=confirmation_message_id,
        )
        return ProposalResolution(
            ProposalResolutionStatus.REJECTED,
            proposal_id=proposal_id,
            confirmation_message_id=confirmation_message_id,
        )
    if not _confirmed_summary_is_current(session, proposal=proposal):
        return _cancel_active_for_context(
            proposal,
            confirmation_message_id=confirmation_message_id,
            reason="summary_unavailable",
        )
    context = _proposal_context_is_current(
        session,
        proposal=proposal,
        confirmation_message_id=confirmation_message_id,
        session_secret=session_secret,
        now=checked_at,
    )
    if context is None:
        return _cancel_active_for_context(
            proposal,
            confirmation_message_id=confirmation_message_id,
            reason="context_changed",
        )
    execution = _execution_context(
        proposal,
        confirmation_message_id=confirmation_message_id,
        privilege_context=context,
    )
    try:
        effect = execute(execution)
    except ProposalExecutionDenied:
        _set_terminal(
            proposal,
            state=_PROPOSAL_REJECTED,
            reason="domain_denied",
            confirmation_message_id=confirmation_message_id,
        )
        return ProposalResolution(
            ProposalResolutionStatus.REJECTED,
            proposal_id=proposal_id,
            confirmation_message_id=confirmation_message_id,
        )
    receipt_row = _new_receipt(
        proposal,
        confirmation_message_id=confirmation_message_id,
        effect=effect,
    )
    proposal.state = _PROPOSAL_EXECUTED
    proposal.terminal_reason = "confirmed"
    proposal.confirmation_message_id = confirmation_message_id
    proposal.executed_at = checked_at
    proposal.expires_at = None
    session.add(receipt_row)
    session.flush()
    receipt = _receipt_from_row(receipt_row)
    if receipt is None:
        raise ProposalContractError("recibo persistido inválido")
    return ProposalResolution(
        ProposalResolutionStatus.EXECUTED,
        proposal_id=proposal_id,
        receipt_id=receipt.receipt_id,
        confirmation_message_id=confirmation_message_id,
        receipt=receipt,
    )


def cancel_action_proposal_for_term_change(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    inbound_message_id: uuid.UUID,
) -> ProposalResolution:
    """Durably suppress an affirmative inbound when its consent term is stale."""

    igreja_id = _require_uuid(igreja_id, name="igreja")
    conversation_id = _require_uuid(conversation_id, name="conversa")
    inbound_message_id = _require_uuid(inbound_message_id, name="âncora inbound")
    require_tenant_scope(
        session, expected_igreja_id=igreja_id, source="agent_action_proposals"
    )
    conversation, proposal, replay = _active_proposal_for_resolution(
        session,
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        confirmation_message_id=inbound_message_id,
    )
    if conversation is None:
        return ProposalResolution(ProposalResolutionStatus.NO_PENDING)
    if replay is not None:
        return _terminal_replay(
            session,
            proposal=replay,
            confirmation_message_id=inbound_message_id,
        )
    if proposal is None:
        return ProposalResolution(ProposalResolutionStatus.NO_PENDING)
    if _inbound_exists(
        session,
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        message_id=inbound_message_id,
    ) is None:
        raise ProposalContractError("âncora inbound ausente")
    return _cancel_active_for_context(
        proposal,
        confirmation_message_id=inbound_message_id,
        reason="term_changed",
    )


def status_receipt(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    confirmation_message_id: uuid.UUID,
) -> ProposalResolution:
    """Return one committed receipt by its original inbound confirmation."""

    igreja_id = _require_uuid(igreja_id, name="igreja")
    conversation_id = _require_uuid(conversation_id, name="conversa")
    confirmation_message_id = _require_uuid(
        confirmation_message_id, name="confirmação"
    )
    require_tenant_scope(
        session, expected_igreja_id=igreja_id, source="agent_action_proposals"
    )
    receipt_row = session.execute(
        select(AgentActionReceipt)
        .where(
            AgentActionReceipt.igreja_id == igreja_id,
            AgentActionReceipt.conversation_id == conversation_id,
            AgentActionReceipt.confirmation_message_id == confirmation_message_id,
        )
    ).scalar_one_or_none()
    receipt = _receipt_from_row(receipt_row) if receipt_row is not None else None
    if receipt is None:
        return ProposalResolution(ProposalResolutionStatus.NO_PENDING)
    return ProposalResolution(
        ProposalResolutionStatus.RECEIPT,
        proposal_id=receipt.proposal_id,
        receipt_id=receipt.receipt_id,
        confirmation_message_id=confirmation_message_id,
        receipt=receipt,
    )
