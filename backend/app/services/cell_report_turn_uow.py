"""Atomic offline boundary for a confirmed WhatsApp cell-report turn.

The caller owns one active tenant-scoped transaction.  This service binds the
confirmation, sanitized audit and outbound reply to one canonical three-effect
plan, locks the pre-reserved ``Message`` reply row, materializes the report via
``confirm_cell_report``, records one content-free audit row and stages the reply
as ``ia_pendente``.  It flushes only.  It never starts or completes a
transaction, invokes the agent runtime, worker or provider, or performs network
I/O.

The locked reply row is the correlation source for a legacy v1/v0 key.  That
binding is not global authentication or a durable generic receipt.  A v2 key is
derived from the exact planned reply effect and must match both the caller's
expected key and the locked row.  An exact replay observation is accepted only
when the final report, pending reply and sanitized audit all agree.  That
observation does not prove an earlier commit because it can see writes from the
caller's current transaction.

After a sanitized database failure, the caller remains responsible for
discarding its failed transaction.
"""

from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.turn_execution import (
    AgentCompatibilityKeyVersion,
    AgentTurnExecutionError,
    AgentTurnExecutionPlan,
    bind_agent_legacy_reply_key_evidence,
    build_agent_effect_compatibility_key,
    build_agent_turn_execution_plan,
)
from app.agent.turn_identity import (
    MAX_PROVIDER_MESSAGE_ID_BYTES,
    AgentEffectIntent,
    AgentEffectKind,
    AgentTurnContractError,
    AgentTurnIdentity,
    digest_effect_payload,
    validate_agent_effect_intents,
)
from app.agent.turn_plan_adapter import MAX_AGENT_TURN_RESPONSE_BYTES
from app.db.models import AgentConversationLog, Message
from app.db.rls_observability import require_tenant_scope
from app.db.tenant_session import TenantScopeError
from app.domain.agent_reply import AGENT_REPLY_EXECUTING, AGENT_REPLY_PENDING
from app.services.cell_report_application import (
    CellReportApplicationError,
    CellReportApplicationErrorCode,
    CellReportConfirmationResult,
    confirm_cell_report,
)


CELL_REPORT_TURN_REPLY_EFFECT_SCHEMA_V1: Final = (
    "cell-report-turn-reply-effect/v1"
)
CELL_REPORT_TURN_AUDIT_EFFECT_SCHEMA_V1: Final = (
    "cell-report-turn-audit-effect/v1"
)
CELL_REPORT_TURN_AUDIT_EVENT: Final = "cell_report_turn_staged"


class CellReportTurnUnitOfWorkErrorCode(str, Enum):
    """Static fail-closed categories that never contain caller material."""

    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    TRANSACTION_REQUIRED = "TRANSACTION_REQUIRED"
    EFFECT_PLAN_INVALID = "EFFECT_PLAN_INVALID"
    REPLY_KEY_INVALID = "REPLY_KEY_INVALID"
    REPLY_MESSAGE_NOT_FOUND = "REPLY_MESSAGE_NOT_FOUND"
    REPLY_MESSAGE_CONFLICT = "REPLY_MESSAGE_CONFLICT"
    AUDIT_CONFLICT = "AUDIT_CONFLICT"
    REPLAY_CONFLICT = "REPLAY_CONFLICT"
    DATA_INTEGRITY = "DATA_INTEGRITY"


class CellReportTurnUnitOfWorkError(RuntimeError):
    """Sanitized unit-of-work rejection."""

    def __init__(self, code: CellReportTurnUnitOfWorkErrorCode) -> None:
        self.code = code
        super().__init__(f"cell report turn rejected: {code.value}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code.value!r})"


def _reject(code: CellReportTurnUnitOfWorkErrorCode) -> None:
    raise CellReportTurnUnitOfWorkError(code)


def _reject_without_context(code: CellReportTurnUnitOfWorkErrorCode) -> None:
    raise CellReportTurnUnitOfWorkError(code) from None


@dataclass(frozen=True, slots=True, repr=False)
class CellReportTurnStageResult:
    """One staged result that always requires caller transaction completion.

    ``requires_caller_commit`` is deliberately invariant ``True``.  Even an
    exact replay may only be observing writes from the current transaction, so
    the caller must make the locked state durable before any outbound send.
    """

    snapshot: dict[str, object] = field(repr=False)
    plan: AgentTurnExecutionPlan = field(repr=False)
    replayed: bool
    requires_caller_commit: bool = field(default=True, init=False)

    def __repr__(self) -> str:
        return (
            "CellReportTurnStageResult("
            f"replayed={self.replayed!r}, "
            f"requires_caller_commit={self.requires_caller_commit!r})"
        )


def _require_uuid(value: object) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        _reject(CellReportTurnUnitOfWorkErrorCode.INVALID_ARGUMENT)
    return value


def _require_bounded_string(
    value: object,
    *,
    max_bytes: int,
    code: CellReportTurnUnitOfWorkErrorCode,
) -> str:
    if type(value) is not str or not value:
        _reject(code)
    if len(value) > max_bytes:
        _reject(code)
    if value[0].isspace() or value[-1].isspace() or not value.isprintable():
        _reject(code)
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeEncodeError:
        _reject_without_context(code)
    if len(encoded) > max_bytes:
        _reject(code)
    return value


def _safe_equal(value: object, expected: str) -> bool:
    if type(value) is not str or len(value) != len(expected):
        return False
    if value.isascii() and expected.isascii():
        return hmac.compare_digest(value, expected)
    return value == expected


def _require_external_transaction(db: Session) -> None:
    try:
        active = db.in_transaction()
    except SQLAlchemyError:
        _reject_without_context(
            CellReportTurnUnitOfWorkErrorCode.TRANSACTION_REQUIRED
        )
    except (AttributeError, TypeError):
        _reject_without_context(
            CellReportTurnUnitOfWorkErrorCode.TRANSACTION_REQUIRED
        )
    if not active:
        _reject(CellReportTurnUnitOfWorkErrorCode.TRANSACTION_REQUIRED)


def _scalars_sanitized(db: Session, statement: object) -> list[object]:
    try:
        return list(db.execute(statement).scalars().all())
    except SQLAlchemyError:
        _reject_without_context(CellReportTurnUnitOfWorkErrorCode.DATA_INTEGRITY)


def _flush_sanitized(db: Session) -> None:
    try:
        db.flush()
    except SQLAlchemyError:
        _reject_without_context(CellReportTurnUnitOfWorkErrorCode.DATA_INTEGRITY)


def _require_effects(
    *,
    turn_identity: AgentTurnIdentity,
    submission_intent: AgentEffectIntent,
    audit_intent: AgentEffectIntent | None = None,
    reply_intent: AgentEffectIntent | None = None,
) -> tuple[AgentEffectIntent, ...]:
    values = tuple(
        value
        for value in (submission_intent, audit_intent, reply_intent)
        if value is not None
    )
    try:
        validated = validate_agent_effect_intents(turn_identity, values)
    except AgentTurnContractError:
        _reject_without_context(
            CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID
        )
    expected_kinds = (AgentEffectKind.TOOL_CALL,)
    if reply_intent is not None and audit_intent is None:
        expected_kinds = (
            AgentEffectKind.TOOL_CALL,
            AgentEffectKind.OUTBOUND_REPLY,
        )
    elif audit_intent is not None and reply_intent is not None:
        expected_kinds = (
            AgentEffectKind.TOOL_CALL,
            AgentEffectKind.AUDIT_EVENT,
            AgentEffectKind.OUTBOUND_REPLY,
        )
    if (
        len(validated) != len(expected_kinds)
        or tuple(intent.kind for intent in validated) != expected_kinds
        or any(intent.ordinal != 0 for intent in validated)
    ):
        _reject(CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID)
    return validated


def build_cell_report_turn_reply_effect_payload(
    *,
    turn_identity: AgentTurnIdentity,
    submission_intent: AgentEffectIntent,
    reply_text: str,
) -> dict[str, object]:
    """Derive the closed reply payload; arbitrary caller payload is forbidden."""

    submission = _require_effects(
        turn_identity=turn_identity,
        submission_intent=submission_intent,
    )[0]
    response = _require_bounded_string(
        reply_text,
        max_bytes=MAX_AGENT_TURN_RESPONSE_BYTES,
        code=CellReportTurnUnitOfWorkErrorCode.INVALID_ARGUMENT,
    )
    return {
        "schema": CELL_REPORT_TURN_REPLY_EFFECT_SCHEMA_V1,
        "submission_effect_id": submission.effect_id,
        "submission_payload_digest": submission.payload_digest,
        "reply_text": response,
    }


def build_cell_report_turn_audit_effect_payload(
    *,
    turn_identity: AgentTurnIdentity,
    submission_intent: AgentEffectIntent,
    reply_intent: AgentEffectIntent,
) -> dict[str, object]:
    """Derive a content-free audit payload without a circular plan digest."""

    effects = _require_effects(
        turn_identity=turn_identity,
        submission_intent=submission_intent,
        reply_intent=reply_intent,
    )
    if len(effects) != 2:
        _reject(CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID)
    submission, reply = effects
    return {
        "schema": CELL_REPORT_TURN_AUDIT_EFFECT_SCHEMA_V1,
        "evento": CELL_REPORT_TURN_AUDIT_EVENT,
        "submission_effect_id": submission.effect_id,
        "submission_payload_digest": submission.payload_digest,
        "reply_effect_id": reply.effect_id,
        "reply_payload_digest": reply.payload_digest,
    }


def _validate_effect_payload(
    intent: AgentEffectIntent,
    *,
    expected_kind: AgentEffectKind,
    payload: dict[str, object],
) -> None:
    if intent.kind is not expected_kind:
        _reject(CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID)
    try:
        expected = digest_effect_payload(intent.effect_id, expected_kind, payload)
    except AgentTurnContractError:
        _reject_without_context(
            CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID
        )
    if not _safe_equal(intent.payload_digest, expected):
        _reject(CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID)


def _locked_reply_message_statement(
    *,
    igreja_id: uuid.UUID,
    conversa_id: uuid.UUID,
    reply_message_id: uuid.UUID,
):
    return (
        select(Message)
        .where(
            Message.id == reply_message_id,
            Message.igreja_id == igreja_id,
            Message.conversation_id == conversa_id,
        )
        .limit(2)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _load_locked_reply_message(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    conversa_id: uuid.UUID,
    reply_message_id: uuid.UUID,
    expected_reply_provider_key: str,
    reply_text: str,
) -> tuple[Message, bool]:
    rows = _scalars_sanitized(
        db,
        _locked_reply_message_statement(
            igreja_id=igreja_id,
            conversa_id=conversa_id,
            reply_message_id=reply_message_id,
        ),
    )
    if not rows:
        _reject(CellReportTurnUnitOfWorkErrorCode.REPLY_MESSAGE_NOT_FOUND)
    if len(rows) != 1:
        _reject(CellReportTurnUnitOfWorkErrorCode.DATA_INTEGRITY)
    message = rows[0]
    if (
        type(message) is not Message
        or message.id != reply_message_id
        or message.igreja_id != igreja_id
        or message.conversation_id != conversa_id
        or message.direcao != "out"
        or message.autor != "ia"
        or message.tipo != "texto"
        or message.media_path is not None
        or message.media_mime is not None
        or message.media_nome is not None
        or message.media_tamanho is not None
        or message.autor_nome is not None
        or message.enviado_por is not None
        or not _safe_equal(
            message.provider_message_id,
            expected_reply_provider_key,
        )
    ):
        _reject(CellReportTurnUnitOfWorkErrorCode.REPLY_MESSAGE_CONFLICT)
    if message.agent_reply_state == AGENT_REPLY_EXECUTING:
        if message.texto is not None:
            _reject(CellReportTurnUnitOfWorkErrorCode.REPLY_MESSAGE_CONFLICT)
        return message, False
    if message.agent_reply_state == AGENT_REPLY_PENDING:
        if not _safe_equal(message.texto, reply_text):
            _reject(CellReportTurnUnitOfWorkErrorCode.REPLY_MESSAGE_CONFLICT)
        return message, True
    _reject(CellReportTurnUnitOfWorkErrorCode.REPLY_MESSAGE_CONFLICT)


def _matching_audit_statement(
    *,
    igreja_id: uuid.UUID,
    conversa_id: uuid.UUID,
    submission_effect_id: str,
):
    return (
        select(AgentConversationLog)
        .where(
            AgentConversationLog.igreja_id == igreja_id,
            AgentConversationLog.conversation_id == conversa_id,
            AgentConversationLog.evento == CELL_REPORT_TURN_AUDIT_EVENT,
            AgentConversationLog.payload.op("->>")(
                "submission_effect_id"
            )
            == submission_effect_id,
        )
        .limit(2)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _load_matching_audit(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    conversa_id: uuid.UUID,
    submission_effect_id: str,
    expected_payload: dict[str, object],
) -> AgentConversationLog | None:
    rows = _scalars_sanitized(
        db,
        _matching_audit_statement(
            igreja_id=igreja_id,
            conversa_id=conversa_id,
            submission_effect_id=submission_effect_id,
        ),
    )
    if not rows:
        return None
    if len(rows) != 1:
        _reject(CellReportTurnUnitOfWorkErrorCode.AUDIT_CONFLICT)
    audit = rows[0]
    if (
        type(audit) is not AgentConversationLog
        or audit.igreja_id != igreja_id
        or audit.conversation_id != conversa_id
        or audit.evento != CELL_REPORT_TURN_AUDIT_EVENT
        or type(audit.payload) is not dict
        or audit.payload != expected_payload
    ):
        _reject(CellReportTurnUnitOfWorkErrorCode.AUDIT_CONFLICT)
    return audit


def _bind_reply_key(
    *,
    turn_identity: AgentTurnIdentity,
    plan: AgentTurnExecutionPlan,
    reply_intent: AgentEffectIntent,
    reply_key_version: AgentCompatibilityKeyVersion,
    exact_locked_key: str,
) -> None:
    try:
        if reply_key_version is AgentCompatibilityKeyVersion.V2:
            compatibility = build_agent_effect_compatibility_key(
                turn_identity,
                plan,
                reply_intent,
                version=reply_key_version,
            )
        elif reply_key_version in {
            AgentCompatibilityKeyVersion.V1,
            AgentCompatibilityKeyVersion.V0,
        }:
            compatibility = bind_agent_legacy_reply_key_evidence(
                turn_identity,
                plan,
                reply_intent,
                version=reply_key_version,
                exact_observed_key=exact_locked_key,
            )
        else:
            _reject(CellReportTurnUnitOfWorkErrorCode.REPLY_KEY_INVALID)
    except AgentTurnExecutionError:
        _reject_without_context(CellReportTurnUnitOfWorkErrorCode.REPLY_KEY_INVALID)
    if not _safe_equal(compatibility.key, exact_locked_key):
        _reject(CellReportTurnUnitOfWorkErrorCode.REPLY_KEY_INVALID)


def stage_confirmed_cell_report_turn(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    reuniao_id: uuid.UUID,
    conversa_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
    command: str,
    turn_identity: AgentTurnIdentity,
    submission_intent: AgentEffectIntent,
    audit_intent: AgentEffectIntent,
    reply_intent: AgentEffectIntent,
    reply_message_id: uuid.UUID,
    expected_reply_provider_key: str,
    reply_key_version: AgentCompatibilityKeyVersion,
    reply_text: str,
    now: object,
) -> CellReportTurnStageResult:
    """Stage report, audit and reply atomically in the caller transaction."""

    tenant_id = _require_uuid(igreja_id)
    meeting_id = _require_uuid(reuniao_id)
    conversation_id = _require_uuid(conversa_id)
    actor_id = _require_uuid(ator_pessoa_id)
    message_id = _require_uuid(reply_message_id)
    provider_key = _require_bounded_string(
        expected_reply_provider_key,
        max_bytes=MAX_PROVIDER_MESSAGE_ID_BYTES,
        code=CellReportTurnUnitOfWorkErrorCode.REPLY_KEY_INVALID,
    )
    response = _require_bounded_string(
        reply_text,
        max_bytes=MAX_AGENT_TURN_RESPONSE_BYTES,
        code=CellReportTurnUnitOfWorkErrorCode.INVALID_ARGUMENT,
    )
    effects = _require_effects(
        turn_identity=turn_identity,
        submission_intent=submission_intent,
        audit_intent=audit_intent,
        reply_intent=reply_intent,
    )
    if len(effects) != 3:
        _reject(CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID)
    submission, audit, reply = effects
    if (
        turn_identity.igreja_id != tenant_id
        or turn_identity.conversation_id != conversation_id
    ):
        _reject(CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID)

    reply_payload = build_cell_report_turn_reply_effect_payload(
        turn_identity=turn_identity,
        submission_intent=submission,
        reply_text=response,
    )
    _validate_effect_payload(
        reply,
        expected_kind=AgentEffectKind.OUTBOUND_REPLY,
        payload=reply_payload,
    )
    audit_payload = build_cell_report_turn_audit_effect_payload(
        turn_identity=turn_identity,
        submission_intent=submission,
        reply_intent=reply,
    )
    _validate_effect_payload(
        audit,
        expected_kind=AgentEffectKind.AUDIT_EVENT,
        payload=audit_payload,
    )
    try:
        plan = build_agent_turn_execution_plan(
            turn_identity,
            (submission, audit, reply),
        )
    except AgentTurnExecutionError:
        _reject_without_context(
            CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID
        )

    if type(reply_key_version) is not AgentCompatibilityKeyVersion:
        _reject(CellReportTurnUnitOfWorkErrorCode.REPLY_KEY_INVALID)
    if reply_key_version is AgentCompatibilityKeyVersion.V2:
        _bind_reply_key(
            turn_identity=turn_identity,
            plan=plan,
            reply_intent=reply,
            reply_key_version=reply_key_version,
            exact_locked_key=provider_key,
        )

    _require_external_transaction(db)
    try:
        require_tenant_scope(
            db,
            expected_igreja_id=tenant_id,
            source="cell_report_turn_uow",
        )
    except (SQLAlchemyError, TenantScopeError, ValueError):
        _reject_without_context(CellReportTurnUnitOfWorkErrorCode.DATA_INTEGRITY)

    message, replay_candidate = _load_locked_reply_message(
        db,
        igreja_id=tenant_id,
        conversa_id=conversation_id,
        reply_message_id=message_id,
        expected_reply_provider_key=provider_key,
        reply_text=response,
    )
    if reply_key_version is not AgentCompatibilityKeyVersion.V2:
        _bind_reply_key(
            turn_identity=turn_identity,
            plan=plan,
            reply_intent=reply,
            reply_key_version=reply_key_version,
            exact_locked_key=message.provider_message_id,
        )

    persisted_audit_payload = dict(audit_payload)
    persisted_audit_payload["plan_digest"] = plan.plan_digest
    existing_audit = _load_matching_audit(
        db,
        igreja_id=tenant_id,
        conversa_id=conversation_id,
        submission_effect_id=submission.effect_id,
        expected_payload=persisted_audit_payload,
    )
    if replay_candidate != (existing_audit is not None):
        _reject(CellReportTurnUnitOfWorkErrorCode.REPLAY_CONFLICT)

    try:
        confirmation: CellReportConfirmationResult = confirm_cell_report(
            db,
            igreja_id=tenant_id,
            reuniao_id=meeting_id,
            conversa_id=conversation_id,
            ator_pessoa_id=actor_id,
            command=command,
            turn_identity=turn_identity,
            submission_intent=submission,
            now=now,
            expected_replayed=replay_candidate,
        )
    except CellReportApplicationError as exc:
        if exc.code is (
            CellReportApplicationErrorCode.REPLAY_EXPECTATION_MISMATCH
        ):
            _reject_without_context(
                CellReportTurnUnitOfWorkErrorCode.REPLAY_CONFLICT
            )
        raise
    if replay_candidate:
        if confirmation.replayed is not True or (
            confirmation.requires_caller_commit is not False
        ):
            _reject(CellReportTurnUnitOfWorkErrorCode.REPLAY_CONFLICT)
        return CellReportTurnStageResult(
            snapshot=confirmation.snapshot,
            plan=plan,
            replayed=True,
        )
    if confirmation.replayed is not False or (
        confirmation.requires_caller_commit is not True
    ):
        _reject(CellReportTurnUnitOfWorkErrorCode.REPLAY_CONFLICT)

    audit_row = AgentConversationLog(
        igreja_id=tenant_id,
        conversation_id=conversation_id,
        evento=CELL_REPORT_TURN_AUDIT_EVENT,
        payload=persisted_audit_payload,
    )
    message.texto = response
    message.agent_reply_state = AGENT_REPLY_PENDING
    try:
        db.add(audit_row)
    except SQLAlchemyError:
        _reject_without_context(CellReportTurnUnitOfWorkErrorCode.DATA_INTEGRITY)
    _flush_sanitized(db)
    return CellReportTurnStageResult(
        snapshot=confirmation.snapshot,
        plan=plan,
        replayed=False,
    )


__all__ = [
    "CELL_REPORT_TURN_AUDIT_EFFECT_SCHEMA_V1",
    "CELL_REPORT_TURN_AUDIT_EVENT",
    "CELL_REPORT_TURN_REPLY_EFFECT_SCHEMA_V1",
    "CellReportTurnStageResult",
    "CellReportTurnUnitOfWorkError",
    "CellReportTurnUnitOfWorkErrorCode",
    "build_cell_report_turn_audit_effect_payload",
    "build_cell_report_turn_reply_effect_payload",
    "stage_confirmed_cell_report_turn",
]
