"""Offline, fail-closed coordinator for one WhatsApp cell-report turn.

This module is deliberately *not* a runtime, webhook, worker, transport or
consent writer.  It prepares the already-reviewed cell-report application
boundary inside a caller-owned, tenant-scoped transaction.  It never creates a
transaction, commits, rolls back, sends a reply, calls an LLM, reads storage or
performs network I/O.

The current product has no approved, durable source for the
``tarefas_operacionais`` purpose.  Consequently the public default is a
deny-all consent gate and this coordinator is not imported by the live agent
path.  A future, separately approved adapter must prove a purpose-specific
consent permit in the same transaction before it may use the staging path.
Legacy ``Pessoa.consentimento`` and ``ConsentRecord`` are intentionally never
read here and cannot authorize this purpose.

The coordinator derives tenant, conversation, inbound message and actor from
the persisted inbound row bound to ``AgentTurnIdentity``.  It accepts only a
server-resolved meeting target; it never derives a meeting, actor, effect,
correlation key or reply from text, graph output or model output.  Ambiguous
meeting selection remains a future trusted resolver responsibility.
"""

from __future__ import annotations

import datetime as dt
import hmac
import secrets
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Final, Protocol

from sqlalchemy import and_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.turn_execution import (
    AgentCompatibilityKeyVersion,
    AgentTurnExecutionError,
    build_agent_effect_compatibility_key,
    build_agent_outbound_reply_reservation_v2,
    build_agent_turn_execution_plan,
)
from app.agent.turn_identity import (
    AgentEffectIntent,
    AgentEffectKind,
    AgentTurnContractError,
    AgentTurnIdentity,
    build_agent_effect_intent,
    validate_agent_effect_intents,
)
from app.db.models import Conversation, Message
from app.db.rls_observability import require_tenant_scope
from app.db.tenant_session import TenantScopeError
from app.domain.conversations import VALID_ESTADOS
from app.domain.purpose_consent import PurposeConsentPurpose
from app.services.cell_report_application import (
    CellReportApplicationError,
    CellReportProposalResult,
    build_cell_report_confirmation_effect_payload,
    build_cell_report_proposal_effect_payload_for_cycle,
    prepare_cell_report_proposal_cycle,
    propose_cell_report_from_cycle,
)
from app.services.cell_report_turn_uow import (
    CellReportTurnStageResult,
    CellReportTurnUnitOfWorkError,
    build_cell_report_turn_audit_effect_payload,
    build_cell_report_turn_reply_effect_payload,
    stage_confirmed_cell_report_turn,
)


CELL_REPORT_OPERATIONAL_PURPOSE: Final = (
    PurposeConsentPurpose.TAREFAS_OPERACIONAIS
)
CELL_REPORT_CONFIRMATION_REPLY: Final = (
    "Relatório de célula confirmado. Obrigado por enviar."
)
_PERMIT_DOMAIN: Final = b"pastorai.cell-report.operational-consent-permit/v1"
_MEETING_TARGET_DOMAIN: Final = b"pastorai.cell-report.meeting-target/v1"
_PERMIT_SECRET: Final = secrets.token_bytes(32)
_MEETING_TARGET_SECRET: Final = secrets.token_bytes(32)
_MAX_PROVIDER_KEY_BYTES: Final = 512


class CellReportOperation(str, Enum):
    """The two closed operations guarded by purpose-specific consent."""

    PROPOSAL = "proposal"
    CONFIRMATION = "confirmation"


class CellReportCoordinatorErrorCode(str, Enum):
    """Static failures that intentionally contain no pastoral or SQL detail."""

    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    TRANSACTION_REQUIRED = "TRANSACTION_REQUIRED"
    TENANT_SCOPE_INVALID = "TENANT_SCOPE_INVALID"
    INBOUND_BINDING_INVALID = "INBOUND_BINDING_INVALID"
    INBOUND_NOT_FOUND = "INBOUND_NOT_FOUND"
    INBOUND_TEXT_REQUIRED = "INBOUND_TEXT_REQUIRED"
    MEETING_TARGET_INVALID = "MEETING_TARGET_INVALID"
    OPERATIONAL_CONSENT_DENIED = "OPERATIONAL_CONSENT_DENIED"
    REPLY_RESERVATION_INVALID = "REPLY_RESERVATION_INVALID"
    EFFECT_PLAN_INVALID = "EFFECT_PLAN_INVALID"
    APPLICATION_REJECTED = "APPLICATION_REJECTED"
    STAGING_REJECTED = "STAGING_REJECTED"
    DATA_INTEGRITY = "DATA_INTEGRITY"


class CellReportCoordinatorError(RuntimeError):
    """Fail-closed coordinator error with one non-sensitive reason code."""

    def __init__(self, code: CellReportCoordinatorErrorCode) -> None:
        self.code = code
        super().__init__(f"cell report coordinator rejected: {code.value}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code.value!r})"


def _reject(code: CellReportCoordinatorErrorCode) -> None:
    raise CellReportCoordinatorError(code)


def _reject_without_context(code: CellReportCoordinatorErrorCode) -> None:
    raise CellReportCoordinatorError(code) from None


def _require_uuid(value: object, code: CellReportCoordinatorErrorCode) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        _reject(code)
    return value


def _canonical_utc(value: object, code: CellReportCoordinatorErrorCode) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None:
        _reject(code)
    try:
        offset = value.utcoffset()
        if offset is None:
            _reject(code)
        return value.astimezone(dt.timezone.utc)
    except (OverflowError, TypeError, ValueError):
        _reject(code)


def _utc_now() -> dt.datetime:
    """Coordinator-owned clock; callers cannot backdate a consent permit."""

    return dt.datetime.now(dt.timezone.utc)


def _safe_equal(value: object, expected: str) -> bool:
    return (
        type(value) is str
        and len(value) == len(expected)
        and value.isascii()
        and expected.isascii()
        and hmac.compare_digest(value, expected)
    )


def _bounded_provider_key(value: object) -> str:
    if type(value) is not str or not value:
        _reject(CellReportCoordinatorErrorCode.REPLY_RESERVATION_INVALID)
    if len(value) > _MAX_PROVIDER_KEY_BYTES:
        _reject(CellReportCoordinatorErrorCode.REPLY_RESERVATION_INVALID)
    if value[0].isspace() or value[-1].isspace() or not value.isprintable():
        _reject(CellReportCoordinatorErrorCode.REPLY_RESERVATION_INVALID)
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeEncodeError:
        _reject_without_context(
            CellReportCoordinatorErrorCode.REPLY_RESERVATION_INVALID
        )
    if len(encoded) > _MAX_PROVIDER_KEY_BYTES:
        _reject(CellReportCoordinatorErrorCode.REPLY_RESERVATION_INVALID)
    return value


@dataclass(frozen=True, slots=True, repr=False, init=False)
class CellReportMeetingTarget:
    """One request-bound target issued by a trusted server-side resolver.

    This opaque, process-local capability cannot be constructed from a raw
    UUID through the public API. It is bound to the persisted inbound turn and
    locked conversation actor, then revalidated before every proposal or
    confirmation. It is neither a durable selection record nor a substitute
    for the future trusted meeting resolver.
    """

    _meeting_id: uuid.UUID
    _material: bytes = field(repr=False)

    @property
    def meeting_id(self) -> uuid.UUID:
        return self._meeting_id

    def __repr__(self) -> str:
        return "CellReportMeetingTarget(<redacted>)"

    def __reduce__(self):
        raise TypeError("CellReportMeetingTarget cannot be serialized")

    def __reduce_ex__(self, _protocol: int):
        raise TypeError("CellReportMeetingTarget cannot be serialized")


@dataclass(frozen=True, slots=True)
class CellReportReplyReservation:
    """One trusted, already-created V2 reply-row reservation.

    The coordinator does not create this row.  The UoW locks and validates the
    row in the same caller-owned transaction before it stages any result.
    """

    message_id: uuid.UUID
    provider_key: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_uuid(
            self.message_id,
            CellReportCoordinatorErrorCode.REPLY_RESERVATION_INVALID,
        )
        _bounded_provider_key(self.provider_key)


@dataclass(frozen=True, slots=True, repr=False)
class OperationalConsentRequest:
    """Exact binding a future approved purpose-consent gate must attest."""

    igreja_id: uuid.UUID
    actor_pessoa_id: uuid.UUID
    conversation_id: uuid.UUID
    inbound_message_id: uuid.UUID
    meeting_id: uuid.UUID
    turn_id: str
    operation: CellReportOperation
    purpose: PurposeConsentPurpose = CELL_REPORT_OPERATIONAL_PURPOSE

    def __repr__(self) -> str:
        return "OperationalConsentRequest(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False, init=False)
class OperationalConsentPermit:
    """Opaque, process-local evidence returned only by a trusted gate.

    This is deliberately not durable evidence and is not serializable.  A
    future production gate needs an independently reviewed catalog, ledger and
    receipt design.  The local proof prevents accidental use of booleans,
    dictionaries or detached request bindings in this inactive slice.
    """

    _material: bytes = field(repr=False)
    expires_at: dt.datetime = field(repr=False)

    def __repr__(self) -> str:
        return "OperationalConsentPermit(<redacted>)"

    def __reduce__(self):
        raise TypeError("OperationalConsentPermit cannot be serialized")

    def __reduce_ex__(self, _protocol: int):
        raise TypeError("OperationalConsentPermit cannot be serialized")


class OperationalConsentGate(Protocol):
    """Server-side consent boundary; inputs from a webhook or model are invalid."""

    def authorize_in_transaction(
        self,
        db: Session,
        request: OperationalConsentRequest,
    ) -> OperationalConsentPermit | None:
        """Return one request-bound permit or ``None`` to deny."""


class DenyAllOperationalConsentGate:
    """Current product default while purpose consent has no approved writer."""

    def authorize_in_transaction(
        self,
        _db: Session,
        _request: OperationalConsentRequest,
    ) -> OperationalConsentPermit | None:
        return None


DENY_ALL_OPERATIONAL_CONSENT_GATE: Final[OperationalConsentGate] = (
    DenyAllOperationalConsentGate()
)


@dataclass(frozen=True, slots=True, repr=False)
class CellReportProposalStageResult:
    """One flush-only pending proposal and its deterministic next reply draft."""

    proposal: CellReportProposalResult = field(repr=False)
    operation_intent: AgentEffectIntent = field(repr=False)
    reply_text: str = field(repr=False)
    requires_caller_commit: bool = field(default=True, init=False)

    def __repr__(self) -> str:
        return "CellReportProposalStageResult(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class CellReportConfirmationStageResult:
    """One flush-only final stage and its canonical three effect intents."""

    stage: CellReportTurnStageResult = field(repr=False)
    submission_intent: AgentEffectIntent = field(repr=False)
    audit_intent: AgentEffectIntent = field(repr=False)
    reply_intent: AgentEffectIntent = field(repr=False)
    reply_provider_key: str = field(repr=False)

    def __repr__(self) -> str:
        return "CellReportConfirmationStageResult(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class _InboundContext:
    igreja_id: uuid.UUID
    conversation_id: uuid.UUID
    actor_pessoa_id: uuid.UUID
    inbound_message_id: uuid.UUID
    text: str = field(repr=False)


def _permit_material(
    request: OperationalConsentRequest,
    expires_at: dt.datetime,
) -> bytes:
    parts = (
        _PERMIT_DOMAIN,
        request.igreja_id.bytes,
        request.actor_pessoa_id.bytes,
        request.conversation_id.bytes,
        request.inbound_message_id.bytes,
        request.meeting_id.bytes,
        request.turn_id.encode("ascii"),
        request.operation.value.encode("ascii"),
        request.purpose.value.encode("ascii"),
        expires_at.isoformat(timespec="microseconds").encode("ascii"),
    )
    return b"".join(len(part).to_bytes(4, "big") + part for part in parts)


def _meeting_target_material(
    identity: AgentTurnIdentity,
    *,
    actor_pessoa_id: uuid.UUID,
    meeting_id: uuid.UUID,
) -> bytes:
    parts = (
        _MEETING_TARGET_DOMAIN,
        identity.igreja_id.bytes,
        identity.conversation_id.bytes,
        identity.inbound_message_id.bytes,
        identity.turn_id.encode("ascii"),
        actor_pessoa_id.bytes,
        meeting_id.bytes,
    )
    return b"".join(len(part).to_bytes(4, "big") + part for part in parts)


def _mint_cell_report_meeting_target(
    identity: AgentTurnIdentity,
    *,
    actor_pessoa_id: uuid.UUID,
    meeting_id: uuid.UUID,
) -> CellReportMeetingTarget:
    """Internal mint for a future reviewed resolver and focused tests only."""

    expected_identity = _require_identity(identity)
    actor_id = _require_uuid(
        actor_pessoa_id,
        CellReportCoordinatorErrorCode.MEETING_TARGET_INVALID,
    )
    target_id = _require_uuid(
        meeting_id,
        CellReportCoordinatorErrorCode.MEETING_TARGET_INVALID,
    )
    material = _meeting_target_material(
        expected_identity,
        actor_pessoa_id=actor_id,
        meeting_id=target_id,
    )
    target = object.__new__(CellReportMeetingTarget)
    object.__setattr__(target, "_meeting_id", target_id)
    object.__setattr__(
        target,
        "_material",
        hmac.digest(_MEETING_TARGET_SECRET, material, "sha256"),
    )
    return target


def _require_meeting_target(
    value: object,
    *,
    identity: AgentTurnIdentity,
    context: _InboundContext,
) -> CellReportMeetingTarget:
    if type(value) is not CellReportMeetingTarget:
        _reject(CellReportCoordinatorErrorCode.MEETING_TARGET_INVALID)
    try:
        meeting_id = _require_uuid(
            value._meeting_id,
            CellReportCoordinatorErrorCode.MEETING_TARGET_INVALID,
        )
        material = value._material
    except AttributeError:
        _reject(CellReportCoordinatorErrorCode.MEETING_TARGET_INVALID)
    if type(material) is not bytes:
        _reject(CellReportCoordinatorErrorCode.MEETING_TARGET_INVALID)
    expected = hmac.digest(
        _MEETING_TARGET_SECRET,
        _meeting_target_material(
            identity,
            actor_pessoa_id=context.actor_pessoa_id,
            meeting_id=meeting_id,
        ),
        "sha256",
    )
    if len(material) != len(expected) or not hmac.compare_digest(material, expected):
        _reject(CellReportCoordinatorErrorCode.MEETING_TARGET_INVALID)
    return value


def _mint_operational_consent_permit(
    request: OperationalConsentRequest,
    *,
    expires_at: dt.datetime,
) -> OperationalConsentPermit:
    """Internal mint used only by a future reviewed gate and focused tests."""

    expiry = _canonical_utc(
        expires_at,
        CellReportCoordinatorErrorCode.OPERATIONAL_CONSENT_DENIED,
    )
    material = _permit_material(request, expiry)
    permit = object.__new__(OperationalConsentPermit)
    object.__setattr__(
        permit,
        "_material",
        hmac.digest(_PERMIT_SECRET, material, "sha256"),
    )
    object.__setattr__(permit, "expires_at", expiry)
    return permit


def _permit_matches(
    permit: object,
    request: OperationalConsentRequest,
    *,
    now: dt.datetime,
) -> bool:
    if type(permit) is not OperationalConsentPermit:
        return False
    try:
        expiry = permit.expires_at
        material = permit._material
    except AttributeError:
        return False
    if type(material) is not bytes:
        return False
    try:
        canonical_expiry = _canonical_utc(
            expiry,
            CellReportCoordinatorErrorCode.OPERATIONAL_CONSENT_DENIED,
        )
    except CellReportCoordinatorError:
        return False
    if canonical_expiry <= now:
        return False
    expected = hmac.digest(
        _PERMIT_SECRET,
        _permit_material(request, canonical_expiry),
        "sha256",
    )
    return len(material) == len(expected) and hmac.compare_digest(material, expected)


def _require_identity(value: object) -> AgentTurnIdentity:
    if type(value) is not AgentTurnIdentity:
        _reject(CellReportCoordinatorErrorCode.INBOUND_BINDING_INVALID)
    try:
        validate_agent_effect_intents(value, ())
    except AgentTurnContractError:
        _reject_without_context(CellReportCoordinatorErrorCode.INBOUND_BINDING_INVALID)
    return value


def _require_external_transaction(db: Session) -> tuple[object, object | None]:
    try:
        active = db.in_transaction()
    except SQLAlchemyError:
        _reject_without_context(CellReportCoordinatorErrorCode.TRANSACTION_REQUIRED)
    except (AttributeError, TypeError):
        _reject(CellReportCoordinatorErrorCode.TRANSACTION_REQUIRED)
    if not active:
        _reject(CellReportCoordinatorErrorCode.TRANSACTION_REQUIRED)
    try:
        transaction = db.get_transaction()
        nested_transaction = db.get_nested_transaction()
    except SQLAlchemyError:
        _reject_without_context(CellReportCoordinatorErrorCode.TRANSACTION_REQUIRED)
    except (AttributeError, TypeError):
        _reject(CellReportCoordinatorErrorCode.TRANSACTION_REQUIRED)
    if transaction is None:
        _reject(CellReportCoordinatorErrorCode.TRANSACTION_REQUIRED)
    return transaction, nested_transaction


def _rows_sanitized(db: Session, statement: object) -> list[object]:
    try:
        return list(db.execute(statement).all())
    except SQLAlchemyError:
        _reject_without_context(CellReportCoordinatorErrorCode.DATA_INTEGRITY)


def _inbound_statement(identity: AgentTurnIdentity):
    return (
        select(
            Message.id,
            Message.igreja_id,
            Message.conversation_id,
            Message.direcao,
            Message.autor,
            Message.agent_reply_state,
            Message.provider_message_id,
            Message.texto,
            Message.tipo,
            Message.media_path,
            Message.media_mime,
            Message.media_nome,
            Message.media_tamanho,
            Conversation.id,
            Conversation.igreja_id,
            Conversation.pessoa_id,
            Conversation.estado,
            Conversation.assumido_por,
            Conversation.numero_oficial,
        )
        .join(
            Conversation,
            and_(
                Conversation.id == Message.conversation_id,
                Conversation.igreja_id == Message.igreja_id,
            ),
        )
        .where(
            Message.id == identity.inbound_message_id,
            Message.igreja_id == identity.igreja_id,
            Message.conversation_id == identity.conversation_id,
        )
        .limit(2)
        .with_for_update(of=(Message, Conversation))
        .execution_options(populate_existing=True)
    )


def _load_bound_inbound(
    db: Session,
    *,
    identity: AgentTurnIdentity,
) -> tuple[_InboundContext, tuple[object, object | None]]:
    transaction_handles = _require_external_transaction(db)
    try:
        require_tenant_scope(
            db,
            expected_igreja_id=identity.igreja_id,
            source="cell_report_whatsapp_coordinator",
        )
    except (SQLAlchemyError, TenantScopeError, ValueError):
        _reject_without_context(CellReportCoordinatorErrorCode.TENANT_SCOPE_INVALID)

    rows = _rows_sanitized(db, _inbound_statement(identity))
    if not rows:
        _reject(CellReportCoordinatorErrorCode.INBOUND_NOT_FOUND)
    if len(rows) != 1:
        _reject(CellReportCoordinatorErrorCode.DATA_INTEGRITY)
    try:
        (
            inbound_id,
            message_tenant_id,
            message_conversation_id,
            direction,
            author,
            reply_state,
            provider_message_id,
            text,
            message_type,
            media_path,
            media_mime,
            media_name,
            media_size,
            conversation_id,
            conversation_tenant_id,
            actor_pessoa_id,
            conversation_state,
            assumed_by,
            official_number,
        ) = rows[0]
    except (TypeError, ValueError):
        _reject(CellReportCoordinatorErrorCode.DATA_INTEGRITY)

    if (
        inbound_id != identity.inbound_message_id
        or message_tenant_id != identity.igreja_id
        or message_conversation_id != identity.conversation_id
        or conversation_id != identity.conversation_id
        or conversation_tenant_id != identity.igreja_id
        or direction != "in"
        or author != "contato"
        or reply_state is not None
        or provider_message_id != identity.provider_message_id
        or message_type != "texto"
        or media_path is not None
        or media_mime is not None
        or media_name is not None
        or media_size is not None
        or type(actor_pessoa_id) is not uuid.UUID
        or actor_pessoa_id.int == 0
        or type(conversation_state) is not str
        or conversation_state not in VALID_ESTADOS
        or conversation_state == "humano"
        or assumed_by is not None
        or official_number is not True
    ):
        _reject(CellReportCoordinatorErrorCode.INBOUND_BINDING_INVALID)
    if type(text) is not str or not text.strip():
        _reject(CellReportCoordinatorErrorCode.INBOUND_TEXT_REQUIRED)
    return (
        _InboundContext(
            igreja_id=identity.igreja_id,
            conversation_id=identity.conversation_id,
            actor_pessoa_id=actor_pessoa_id,
            inbound_message_id=identity.inbound_message_id,
            text=text,
        ),
        transaction_handles,
    )


def _consent_request(
    *,
    context: _InboundContext,
    identity: AgentTurnIdentity,
    target: CellReportMeetingTarget,
    operation: CellReportOperation,
) -> OperationalConsentRequest:
    return OperationalConsentRequest(
        igreja_id=context.igreja_id,
        actor_pessoa_id=context.actor_pessoa_id,
        conversation_id=context.conversation_id,
        inbound_message_id=context.inbound_message_id,
        meeting_id=target.meeting_id,
        turn_id=identity.turn_id,
        operation=operation,
    )


def _require_operational_consent(
    db: Session,
    *,
    gate: OperationalConsentGate,
    request: OperationalConsentRequest,
    transaction_handles: tuple[object, object | None],
) -> OperationalConsentPermit:
    if not hasattr(gate, "authorize_in_transaction"):
        _reject(CellReportCoordinatorErrorCode.OPERATIONAL_CONSENT_DENIED)
    try:
        permit = gate.authorize_in_transaction(db, request)
    except Exception:  # noqa: BLE001 - a consent error must remain fail-closed
        _reject_without_context(
            CellReportCoordinatorErrorCode.OPERATIONAL_CONSENT_DENIED
        )
    if type(permit) is not OperationalConsentPermit:
        _reject(CellReportCoordinatorErrorCode.OPERATIONAL_CONSENT_DENIED)
    _revalidate_operational_consent(
        db,
        permit=permit,
        request=request,
        transaction_handles=transaction_handles,
    )
    return permit


def _revalidate_operational_consent(
    db: Session,
    *,
    permit: OperationalConsentPermit,
    request: OperationalConsentRequest,
    transaction_handles: tuple[object, object | None],
) -> dt.datetime:
    """Recheck permit, transaction and RLS immediately before a write boundary."""

    authorized_at = _canonical_utc(
        _utc_now(),
        CellReportCoordinatorErrorCode.OPERATIONAL_CONSENT_DENIED,
    )
    if not _permit_matches(permit, request, now=authorized_at):
        _reject(CellReportCoordinatorErrorCode.OPERATIONAL_CONSENT_DENIED)
    (
        current_transaction,
        current_nested_transaction,
    ) = _require_external_transaction(db)
    if (
        current_transaction is not transaction_handles[0]
        or current_nested_transaction is not transaction_handles[1]
    ):
        _reject(CellReportCoordinatorErrorCode.TRANSACTION_REQUIRED)
    try:
        require_tenant_scope(
            db,
            expected_igreja_id=request.igreja_id,
            source="cell_report_whatsapp_coordinator_after_consent",
        )
    except (SQLAlchemyError, TenantScopeError, ValueError):
        _reject_without_context(CellReportCoordinatorErrorCode.TENANT_SCOPE_INVALID)
    return authorized_at


def _proposal_reply(result: CellReportProposalResult) -> str:
    command = result.confirmation_command
    if command is None:
        return (
            "Relatório recebido. Envie presentes, visitantes, decisões e oferta "
            "para concluir."
        )
    return f"Relatório recebido. Para confirmar, responda: {command}"


def stage_whatsapp_cell_report_proposal(
    db: Session,
    *,
    turn_identity: AgentTurnIdentity,
    target: CellReportMeetingTarget,
    consent_gate: OperationalConsentGate = DENY_ALL_OPERATIONAL_CONSENT_GATE,
) -> CellReportProposalStageResult:
    """Flush one pending report proposal under a caller-owned transaction.

    With the default gate this rejects before calling the application service.
    No caller may supply the actor, conversation, text, expiry, correlation
    key, effect ID or purpose decision.
    """

    identity = _require_identity(turn_identity)
    context, transaction_handles = _load_bound_inbound(db, identity=identity)
    resolved_target = _require_meeting_target(
        target,
        identity=identity,
        context=context,
    )
    request = _consent_request(
        context=context,
        identity=identity,
        target=resolved_target,
        operation=CellReportOperation.PROPOSAL,
    )
    permit = _require_operational_consent(
        db,
        gate=consent_gate,
        request=request,
        transaction_handles=transaction_handles,
    )
    try:
        cycle = prepare_cell_report_proposal_cycle(
            db,
            igreja_id=context.igreja_id,
            reuniao_id=resolved_target.meeting_id,
            conversa_id=context.conversation_id,
            ator_pessoa_id=context.actor_pessoa_id,
            turn_identity=identity,
        )
    except CellReportApplicationError:
        _reject_without_context(CellReportCoordinatorErrorCode.APPLICATION_REJECTED)
    try:
        payload = build_cell_report_proposal_effect_payload_for_cycle(
            cycle,
            text=context.text,
        )
        operation_intent = build_agent_effect_intent(
            identity,
            kind=AgentEffectKind.TOOL_CALL,
            ordinal=0,
            payload=payload,
        )
    except (AgentTurnContractError, CellReportApplicationError):
        _reject_without_context(CellReportCoordinatorErrorCode.EFFECT_PLAN_INVALID)
    _revalidate_operational_consent(
        db,
        permit=permit,
        request=request,
        transaction_handles=transaction_handles,
    )
    try:
        proposal = propose_cell_report_from_cycle(
            db,
            cycle=cycle,
            turn_identity=identity,
            operation_intent=operation_intent,
            text=context.text,
        )
    except CellReportApplicationError:
        _reject_without_context(CellReportCoordinatorErrorCode.APPLICATION_REJECTED)
    return CellReportProposalStageResult(
        proposal=proposal,
        operation_intent=operation_intent,
        reply_text=_proposal_reply(proposal),
    )


def stage_confirmed_whatsapp_cell_report(
    db: Session,
    *,
    turn_identity: AgentTurnIdentity,
    target: CellReportMeetingTarget,
    reply_reservation: CellReportReplyReservation,
    consent_gate: OperationalConsentGate = DENY_ALL_OPERATIONAL_CONSENT_GATE,
) -> CellReportConfirmationStageResult:
    """Flush a confirmed report, audit and V2 pending reply as one stage.

    A future adapter must derive the pre-payload V2 reply reservation with
    ``build_agent_outbound_reply_reservation_v2(turn_identity)`` and reserve
    the row with that exact key in the same transaction before invoking this
    function.  This coordinator independently proves that the later canonical
    plan produces the same V2 key.  It never creates that row or dispatches
    its reply.
    """

    identity = _require_identity(turn_identity)
    if type(reply_reservation) is not CellReportReplyReservation:
        _reject(CellReportCoordinatorErrorCode.REPLY_RESERVATION_INVALID)
    context, transaction_handles = _load_bound_inbound(db, identity=identity)
    resolved_target = _require_meeting_target(
        target,
        identity=identity,
        context=context,
    )
    request = _consent_request(
        context=context,
        identity=identity,
        target=resolved_target,
        operation=CellReportOperation.CONFIRMATION,
    )
    permit = _require_operational_consent(
        db,
        gate=consent_gate,
        request=request,
        transaction_handles=transaction_handles,
    )
    try:
        pre_payload_reservation = build_agent_outbound_reply_reservation_v2(
            identity
        )
    except AgentTurnExecutionError:
        _reject_without_context(CellReportCoordinatorErrorCode.EFFECT_PLAN_INVALID)
    if not _safe_equal(
        reply_reservation.provider_key,
        pre_payload_reservation.key,
    ):
        _reject(CellReportCoordinatorErrorCode.REPLY_RESERVATION_INVALID)
    try:
        submission_payload = build_cell_report_confirmation_effect_payload(
            igreja_id=context.igreja_id,
            reuniao_id=resolved_target.meeting_id,
            conversa_id=context.conversation_id,
            ator_pessoa_id=context.actor_pessoa_id,
            command=context.text,
        )
        submission_intent = build_agent_effect_intent(
            identity,
            kind=AgentEffectKind.TOOL_CALL,
            ordinal=0,
            payload=submission_payload,
        )
        reply_payload = build_cell_report_turn_reply_effect_payload(
            turn_identity=identity,
            submission_intent=submission_intent,
            reply_text=CELL_REPORT_CONFIRMATION_REPLY,
        )
        reply_intent = build_agent_effect_intent(
            identity,
            kind=AgentEffectKind.OUTBOUND_REPLY,
            ordinal=0,
            payload=reply_payload,
        )
        audit_payload = build_cell_report_turn_audit_effect_payload(
            turn_identity=identity,
            submission_intent=submission_intent,
            reply_intent=reply_intent,
        )
        audit_intent = build_agent_effect_intent(
            identity,
            kind=AgentEffectKind.AUDIT_EVENT,
            ordinal=0,
            payload=audit_payload,
        )
        plan = build_agent_turn_execution_plan(
            identity,
            (submission_intent, audit_intent, reply_intent),
        )
        planned_reply_key = build_agent_effect_compatibility_key(
            identity,
            plan,
            reply_intent,
            version=AgentCompatibilityKeyVersion.V2,
        ).key
    except (AgentTurnContractError, AgentTurnExecutionError, CellReportApplicationError):
        _reject_without_context(CellReportCoordinatorErrorCode.EFFECT_PLAN_INVALID)
    if not _safe_equal(planned_reply_key, pre_payload_reservation.key):
        _reject(CellReportCoordinatorErrorCode.EFFECT_PLAN_INVALID)
    authorized_at = _revalidate_operational_consent(
        db,
        permit=permit,
        request=request,
        transaction_handles=transaction_handles,
    )
    try:
        stage = stage_confirmed_cell_report_turn(
            db,
            igreja_id=context.igreja_id,
            reuniao_id=resolved_target.meeting_id,
            conversa_id=context.conversation_id,
            ator_pessoa_id=context.actor_pessoa_id,
            command=context.text,
            turn_identity=identity,
            submission_intent=submission_intent,
            audit_intent=audit_intent,
            reply_intent=reply_intent,
            reply_message_id=reply_reservation.message_id,
            expected_reply_provider_key=pre_payload_reservation.key,
            reply_key_version=AgentCompatibilityKeyVersion.V2,
            reply_text=CELL_REPORT_CONFIRMATION_REPLY,
            now=authorized_at,
        )
    except (CellReportTurnUnitOfWorkError, CellReportApplicationError):
        _reject_without_context(CellReportCoordinatorErrorCode.STAGING_REJECTED)
    return CellReportConfirmationStageResult(
        stage=stage,
        submission_intent=submission_intent,
        audit_intent=audit_intent,
        reply_intent=reply_intent,
        reply_provider_key=pre_payload_reservation.key,
    )


__all__ = [
    "CELL_REPORT_CONFIRMATION_REPLY",
    "CELL_REPORT_OPERATIONAL_PURPOSE",
    "DENY_ALL_OPERATIONAL_CONSENT_GATE",
    "CellReportConfirmationStageResult",
    "CellReportCoordinatorError",
    "CellReportCoordinatorErrorCode",
    "CellReportMeetingTarget",
    "CellReportOperation",
    "CellReportProposalStageResult",
    "CellReportReplyReservation",
    "DenyAllOperationalConsentGate",
    "OperationalConsentGate",
    "OperationalConsentPermit",
    "OperationalConsentRequest",
    "stage_confirmed_whatsapp_cell_report",
    "stage_whatsapp_cell_report_proposal",
]
