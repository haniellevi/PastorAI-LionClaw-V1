"""Transactional application boundary for WhatsApp cell reports.

The caller must already own an active tenant-scoped transaction. This module
locks the conversation and target meeting, revalidates the active cell leader
and ministerial access, persists a closed pending proposal, and materializes a
``cell-report/v2`` snapshot only after literal confirmation.

The service flushes, but never commits, rolls back, starts a transaction,
invokes runtime code, emits a message or performs network I/O. Effect intents
are structurally revalidated and bound to their exact payload. Their hashes
are not authenticators and do not provide global first-execution uniqueness;
the future trusted adapter and durable receipt store must prove provenance and
uniqueness across rows. AgentConfig, inbound provenance and the still-unapproved
``tarefas_operacionais`` legal/controller source remain wiring gates outside
this offline slice; conversation handoff is revalidated locally under lock.
Every human report writer must adopt the same meeting lock before activation,
otherwise a legacy writer could still race this isolated transaction.
After a sanitized database failure, the caller remains responsible for
rolling back its failed transaction.
"""

from __future__ import annotations

import datetime as dt
import hmac
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Final

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.turn_identity import (
    AgentEffectIntent,
    AgentEffectKind,
    AgentTurnContractError,
    AgentTurnIdentity,
    digest_effect_payload,
    validate_agent_effect_intents,
)
from app.db.models import (
    AppUser,
    Celula,
    CelulaReuniao,
    Conversation,
    Pessoa,
    UserRole,
)
from app.db.rls_observability import require_tenant_scope
from app.domain.agent_authz import MINISTERIAL_ROLES
from app.domain.cell_meetings_schedule import meeting_has_passed
from app.domain.cell_report_legacy_snapshot import (
    is_canonical_legacy_human_report_snapshot,
)
from app.domain.cell_report_pending_proposal import (
    CELL_REPORT_PENDING_PROPOSAL_SCHEMA_V1,
    MAX_CELL_REPORT_PROPOSAL_OPERATION_RECEIPTS,
    CellReportPendingProposal,
    CellReportPendingProposalError,
    CellReportProposalBindings,
    CellReportProposalOperationReceipt,
    build_cell_report_pending_proposal,
    cell_report_proposal_bindings_match,
    derive_cell_report_proposal_base_state_digest,
    derive_cell_report_proposal_bindings,
    rehydrate_cell_report_pending_proposal,
)
from app.domain.cell_report_snapshot import (
    CellReportSnapshotValidationError,
    build_cell_report_snapshot_v2,
    validate_cell_report_snapshot_v2,
)
from app.domain.cell_report_workflow import (
    CellReportCandidate,
    CellReportWorkflow,
    CellReportWorkflowError,
    CellReportWorkflowState,
    cell_report_candidate_payload,
    cell_report_confirmation_command,
    correlate_cell_report_confirmation,
    merge_cell_report_candidates,
    parse_cell_report_candidate,
    parse_cell_report_confirmation_command,
    revise_cell_report_workflow,
    start_cell_report_workflow,
)
from app.domain.conversations import VALID_ESTADOS


RELATORIO_PENDENTE: Final = "pendente"
RELATORIO_ENVIADO: Final = "enviado"
VALID_REPORT_STATUSES: Final = frozenset(
    {RELATORIO_PENDENTE, RELATORIO_ENVIADO}
)
STATUS_CANCELADA: Final = "cancelada"
VALID_MEETING_STATUSES: Final = frozenset(
    {"planejada", "confirmada", "realizada", STATUS_CANCELADA}
)
MAX_CELL_REPORT_PROPOSAL_TTL: Final = dt.timedelta(hours=24)
CELL_REPORT_PROPOSAL_EFFECT_SCHEMA_V1: Final = (
    "cell-report-proposal-effect/v1"
)
CELL_REPORT_CONFIRMATION_EFFECT_SCHEMA_V1: Final = (
    "cell-report-confirmation-effect/v1"
)


class CellReportApplicationErrorCode(str, Enum):
    """Sanitized service failure categories."""

    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    TRANSACTION_REQUIRED = "TRANSACTION_REQUIRED"
    MEETING_NOT_FOUND = "MEETING_NOT_FOUND"
    DATA_INTEGRITY = "DATA_INTEGRITY"
    ACTOR_NOT_AUTHORIZED = "ACTOR_NOT_AUTHORIZED"
    REPORT_CONFLICT = "REPORT_CONFLICT"
    PROPOSAL_CORRUPT = "PROPOSAL_CORRUPT"
    PROPOSAL_BINDING_MISMATCH = "PROPOSAL_BINDING_MISMATCH"
    PROPOSAL_EXPIRED = "PROPOSAL_EXPIRED"
    EXPIRY_MISMATCH = "EXPIRY_MISMATCH"
    EXPIRY_LIMIT_EXCEEDED = "EXPIRY_LIMIT_EXCEEDED"
    OPERATION_LIMIT_EXCEEDED = "OPERATION_LIMIT_EXCEEDED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    REPLAY_EXPECTATION_MISMATCH = "REPLAY_EXPECTATION_MISMATCH"
    CONFIRMATION_REJECTED = "CONFIRMATION_REJECTED"


class CellReportApplicationError(RuntimeError):
    """Fail-closed application error that never echoes identifiers or text."""

    def __init__(self, code: CellReportApplicationErrorCode) -> None:
        self.code = code
        super().__init__(f"cell report application rejected: {code.value}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code.value!r})"


def _reject(code: CellReportApplicationErrorCode) -> None:
    raise CellReportApplicationError(code)


def _reject_without_context(code: CellReportApplicationErrorCode) -> None:
    raise CellReportApplicationError(code) from None


@dataclass(frozen=True, slots=True, repr=False)
class CellReportProposalResult:
    """One persisted-in-transaction pending proposal or exact replay."""

    proposal: CellReportPendingProposal = field(repr=False)
    confirmation_command: str | None = field(repr=False)
    replayed: bool

    def __repr__(self) -> str:
        return f"CellReportProposalResult(replayed={self.replayed!r})"


@dataclass(frozen=True, slots=True, repr=False)
class CellReportConfirmationResult:
    """Final snapshot plus whether a caller commit is still required."""

    snapshot: dict[str, object] = field(repr=False)
    accepted_workflow: CellReportWorkflow | None = field(repr=False)
    replayed: bool
    requires_caller_commit: bool

    def __repr__(self) -> str:
        return (
            "CellReportConfirmationResult("
            f"replayed={self.replayed!r}, "
            f"requires_caller_commit={self.requires_caller_commit!r})"
        )


def _require_uuid(value: object) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        _reject(CellReportApplicationErrorCode.INVALID_ARGUMENT)
    return value


def _canonical_utc(value: object) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None:
        _reject(CellReportApplicationErrorCode.INVALID_ARGUMENT)
    try:
        offset = value.utcoffset()
        if offset is None:
            _reject(CellReportApplicationErrorCode.INVALID_ARGUMENT)
        return value.astimezone(dt.timezone.utc)
    except (OverflowError, TypeError, ValueError):
        _reject(CellReportApplicationErrorCode.INVALID_ARGUMENT)


def _render_utc(value: dt.datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _require_external_transaction(db: Session) -> None:
    try:
        active = db.in_transaction()
    except SQLAlchemyError:
        _reject_without_context(
            CellReportApplicationErrorCode.TRANSACTION_REQUIRED
        )
    except (AttributeError, TypeError):
        _reject(CellReportApplicationErrorCode.TRANSACTION_REQUIRED)
    if not active:
        _reject(CellReportApplicationErrorCode.TRANSACTION_REQUIRED)


def _rows_sanitized(db: Session, statement: object) -> list[object]:
    try:
        return list(db.execute(statement).all())
    except SQLAlchemyError:
        _reject_without_context(CellReportApplicationErrorCode.DATA_INTEGRITY)


def _scalars_sanitized(db: Session, statement: object) -> list[object]:
    try:
        return list(db.execute(statement).scalars().all())
    except SQLAlchemyError:
        _reject_without_context(CellReportApplicationErrorCode.DATA_INTEGRITY)


def _flush_sanitized(db: Session) -> None:
    try:
        db.flush()
    except SQLAlchemyError:
        _reject_without_context(CellReportApplicationErrorCode.DATA_INTEGRITY)


def _proposal_material(
    *,
    igreja_id: uuid.UUID,
    reuniao_id: uuid.UUID,
    conversa_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
    correlation_key: str,
    text: str | None,
    expires_at: dt.datetime,
) -> tuple[
    CellReportProposalBindings,
    CellReportCandidate,
    CellReportWorkflow,
    dict[str, object],
]:
    try:
        patch = parse_cell_report_candidate(text)
        if patch.is_empty:
            _reject(CellReportApplicationErrorCode.INVALID_ARGUMENT)
        workflow = start_cell_report_workflow(
            correlation_key=correlation_key,
            candidate=patch,
        )
        bindings = derive_cell_report_proposal_bindings(
            igreja_id=igreja_id,
            reuniao_id=reuniao_id,
            conversa_id=conversa_id,
            ator_pessoa_id=ator_pessoa_id,
        )
    except (CellReportPendingProposalError, CellReportWorkflowError):
        _reject(CellReportApplicationErrorCode.INVALID_ARGUMENT)
    payload: dict[str, object] = {
        "schema": CELL_REPORT_PROPOSAL_EFFECT_SCHEMA_V1,
        "bindings": bindings.to_jsonb(),
        "scope_digest": workflow.scope_digest,
        "candidate_patch": cell_report_candidate_payload(patch),
        "expires_at": _render_utc(expires_at),
    }
    return bindings, patch, workflow, payload


def build_cell_report_proposal_effect_payload(
    *,
    igreja_id: uuid.UUID,
    reuniao_id: uuid.UUID,
    conversa_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
    correlation_key: str,
    text: str | None,
    expires_at: dt.datetime,
) -> dict[str, object]:
    """Build the exact private payload a trusted adapter must plan."""

    tenant_id = _require_uuid(igreja_id)
    meeting_id = _require_uuid(reuniao_id)
    conversation_id = _require_uuid(conversa_id)
    actor_id = _require_uuid(ator_pessoa_id)
    expiry = _canonical_utc(expires_at)
    _bindings, _patch, _workflow, payload = _proposal_material(
        igreja_id=tenant_id,
        reuniao_id=meeting_id,
        conversa_id=conversation_id,
        ator_pessoa_id=actor_id,
        correlation_key=correlation_key,
        text=text,
        expires_at=expiry,
    )
    return payload


def _confirmation_material(
    *,
    igreja_id: uuid.UUID,
    reuniao_id: uuid.UUID,
    conversa_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
    command: str,
) -> tuple[CellReportProposalBindings, dict[str, object]]:
    try:
        parse_cell_report_confirmation_command(command)
        bindings = derive_cell_report_proposal_bindings(
            igreja_id=igreja_id,
            reuniao_id=reuniao_id,
            conversa_id=conversa_id,
            ator_pessoa_id=ator_pessoa_id,
        )
    except (CellReportPendingProposalError, CellReportWorkflowError):
        _reject(CellReportApplicationErrorCode.INVALID_ARGUMENT)
    return bindings, {
        "schema": CELL_REPORT_CONFIRMATION_EFFECT_SCHEMA_V1,
        "bindings": bindings.to_jsonb(),
        "command": command,
    }


def build_cell_report_confirmation_effect_payload(
    *,
    igreja_id: uuid.UUID,
    reuniao_id: uuid.UUID,
    conversa_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
    command: str,
) -> dict[str, object]:
    """Build the exact confirmation payload a trusted adapter must plan."""

    tenant_id = _require_uuid(igreja_id)
    meeting_id = _require_uuid(reuniao_id)
    conversation_id = _require_uuid(conversa_id)
    actor_id = _require_uuid(ator_pessoa_id)
    _bindings, payload = _confirmation_material(
        igreja_id=tenant_id,
        reuniao_id=meeting_id,
        conversa_id=conversation_id,
        ator_pessoa_id=actor_id,
        command=command,
    )
    return payload


def _validate_trusted_effect(
    *,
    turn_identity: AgentTurnIdentity,
    intent: AgentEffectIntent,
    igreja_id: uuid.UUID,
    conversa_id: uuid.UUID,
    expected_payload: dict[str, object],
) -> AgentEffectIntent:
    try:
        validated = validate_agent_effect_intents(turn_identity, (intent,))
    except AgentTurnContractError:
        _reject(CellReportApplicationErrorCode.INVALID_ARGUMENT)
    current = validated[0]
    if (
        turn_identity.igreja_id != igreja_id
        or turn_identity.conversation_id != conversa_id
    ):
        _reject(CellReportApplicationErrorCode.PROPOSAL_BINDING_MISMATCH)
    if current.kind is not AgentEffectKind.TOOL_CALL:
        _reject(CellReportApplicationErrorCode.INVALID_ARGUMENT)
    try:
        expected_digest = digest_effect_payload(
            current.effect_id,
            AgentEffectKind.TOOL_CALL,
            expected_payload,
        )
    except AgentTurnContractError:
        _reject(CellReportApplicationErrorCode.INVALID_ARGUMENT)
    if not hmac.compare_digest(expected_digest, current.payload_digest):
        _reject(CellReportApplicationErrorCode.IDEMPOTENCY_CONFLICT)
    return current


def _locked_meeting_statement(
    *,
    igreja_id: uuid.UUID,
    reuniao_id: uuid.UUID,
):
    return (
        select(CelulaReuniao)
        .where(
            CelulaReuniao.igreja_id == igreja_id,
            CelulaReuniao.id == reuniao_id,
        )
        .limit(2)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _load_locked_meeting(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    reuniao_id: uuid.UUID,
) -> CelulaReuniao:
    rows = _scalars_sanitized(
        db,
        _locked_meeting_statement(
            igreja_id=igreja_id,
            reuniao_id=reuniao_id,
        )
    )
    if not rows:
        _reject(CellReportApplicationErrorCode.MEETING_NOT_FOUND)
    if len(rows) != 1:
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    meeting = rows[0]
    if (
        type(meeting) is not CelulaReuniao
        or meeting.id != reuniao_id
        or meeting.igreja_id != igreja_id
        or type(meeting.celula_id) is not uuid.UUID
        or meeting.celula_id.int == 0
    ):
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    return meeting


def _conversation_actor_statement(
    *,
    igreja_id: uuid.UUID,
    conversa_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
):
    return (
        select(
            Conversation.id,
            Conversation.igreja_id,
            Conversation.pessoa_id,
            Conversation.estado,
            Conversation.assumido_por,
            Conversation.numero_oficial,
        )
        .where(
            Conversation.id == conversa_id,
            Conversation.igreja_id == igreja_id,
            Conversation.pessoa_id == ator_pessoa_id,
        )
        .limit(2)
        .with_for_update(of=Conversation)
        .execution_options(populate_existing=True)
    )


def _revalidate_locked_conversation_actor(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    conversa_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
) -> None:
    rows = _rows_sanitized(
        db,
        _conversation_actor_statement(
            igreja_id=igreja_id,
            conversa_id=conversa_id,
            ator_pessoa_id=ator_pessoa_id,
        ),
    )
    if not rows:
        _reject(CellReportApplicationErrorCode.ACTOR_NOT_AUTHORIZED)
    if len(rows) != 1:
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    try:
        (
            conversation_id,
            tenant_id,
            person_id,
            state,
            assumed_by,
            official_number,
        ) = rows[0]
    except (TypeError, ValueError):
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    if (
        conversation_id != conversa_id
        or tenant_id != igreja_id
        or person_id != ator_pessoa_id
        or type(state) is not str
        or state not in VALID_ESTADOS
        or official_number is not True
    ):
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    if state == "humano" or assumed_by is not None:
        _reject(CellReportApplicationErrorCode.ACTOR_NOT_AUTHORIZED)


def _active_leader_statement(
    *,
    igreja_id: uuid.UUID,
    celula_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
):
    return (
        select(
            Celula.id,
            Celula.igreja_id,
            Celula.lider_id,
            Celula.ativo,
            Pessoa.id,
            Pessoa.igreja_id,
            Pessoa.arquivada_em,
            Pessoa.sem_interesse,
            Pessoa.optout,
        )
        .join(
            Pessoa,
            and_(
                Pessoa.id == ator_pessoa_id,
                Pessoa.igreja_id == igreja_id,
            ),
        )
        .where(
            Celula.id == celula_id,
            Celula.igreja_id == igreja_id,
            Celula.ativo.is_(True),
            Celula.lider_id == ator_pessoa_id,
            Pessoa.arquivada_em.is_(None),
            Pessoa.sem_interesse.is_(False),
            Pessoa.optout.is_(False),
        )
        .limit(2)
        .with_for_update(of=(Celula, Pessoa))
        .execution_options(populate_existing=True)
    )


def _usable_access_statement(
    *,
    igreja_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
):
    return (
        select(AppUser.id, AppUser.igreja_id, AppUser.pessoa_id)
        .where(
            AppUser.igreja_id == igreja_id,
            AppUser.pessoa_id == ator_pessoa_id,
            AppUser.clerk_user_id.is_not(None),
            or_(AppUser.status.is_(None), AppUser.status == "ativo"),
        )
        .order_by(AppUser.id.asc())
        .limit(2)
        .with_for_update(of=AppUser)
        .execution_options(populate_existing=True)
    )


def _ministerial_role_statement(
    *,
    igreja_id: uuid.UUID,
    app_user_id: uuid.UUID,
):
    return (
        select(
            UserRole.id,
            UserRole.igreja_id,
            UserRole.user_id,
            UserRole.papel,
        )
        .where(
            UserRole.igreja_id == igreja_id,
            UserRole.user_id == app_user_id,
            UserRole.papel.in_(tuple(sorted(MINISTERIAL_ROLES))),
        )
        .order_by(UserRole.id.asc())
        .limit(1)
        .with_for_update(of=UserRole)
        .execution_options(populate_existing=True)
    )


def _revalidate_ministerial_access(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
) -> None:
    accesses = _rows_sanitized(
        db,
        _usable_access_statement(
            igreja_id=igreja_id,
            ator_pessoa_id=ator_pessoa_id,
        ),
    )
    if len(accesses) != 1:
        _reject(CellReportApplicationErrorCode.ACTOR_NOT_AUTHORIZED)
    try:
        access_id, access_tenant_id, access_person_id = accesses[0]
    except (TypeError, ValueError):
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    if (
        type(access_id) is not uuid.UUID
        or access_id.int == 0
        or access_tenant_id != igreja_id
        or access_person_id != ator_pessoa_id
    ):
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)

    roles = _rows_sanitized(
        db,
        _ministerial_role_statement(
            igreja_id=igreja_id,
            app_user_id=access_id,
        ),
    )
    if len(roles) != 1:
        _reject(CellReportApplicationErrorCode.ACTOR_NOT_AUTHORIZED)
    try:
        role_id, role_tenant_id, role_user_id, role_name = roles[0]
    except (TypeError, ValueError):
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    if (
        type(role_id) is not uuid.UUID
        or role_id.int == 0
        or role_tenant_id != igreja_id
        or role_user_id != access_id
        or role_name not in MINISTERIAL_ROLES
    ):
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)


def _revalidate_locked_leader(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    meeting: CelulaReuniao,
    ator_pessoa_id: uuid.UUID,
) -> None:
    rows = _rows_sanitized(
        db,
        _active_leader_statement(
            igreja_id=igreja_id,
            celula_id=meeting.celula_id,
            ator_pessoa_id=ator_pessoa_id,
        ),
    )
    if not rows:
        _reject(CellReportApplicationErrorCode.ACTOR_NOT_AUTHORIZED)
    if len(rows) != 1:
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    try:
        (
            cell_id,
            cell_tenant_id,
            leader_id,
            cell_active,
            actor_id,
            actor_tenant_id,
            actor_archived_at,
            actor_without_interest,
            actor_optout,
        ) = rows[0]
    except (TypeError, ValueError):
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    if (
        cell_id != meeting.celula_id
        or cell_tenant_id != igreja_id
        or leader_id != ator_pessoa_id
        or cell_active is not True
        or actor_id != ator_pessoa_id
        or actor_tenant_id != igreja_id
        or actor_archived_at is not None
        or actor_without_interest is not False
        or actor_optout is not False
    ):
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    _revalidate_ministerial_access(
        db,
        igreja_id=igreja_id,
        ator_pessoa_id=ator_pessoa_id,
    )


def _validate_meeting_eligibility(
    meeting: CelulaReuniao,
    *,
    now: dt.datetime,
) -> None:
    if (
        type(meeting.data) is not dt.date
        or (meeting.hora is not None and type(meeting.hora) is not str)
        or type(meeting.status) is not str
        or meeting.status not in VALID_MEETING_STATUSES
        or type(meeting.relatorio_status) is not str
        or meeting.relatorio_status not in VALID_REPORT_STATUSES
    ):
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    if meeting.status == STATUS_CANCELADA:
        _reject(CellReportApplicationErrorCode.REPORT_CONFLICT)
    try:
        passed = meeting_has_passed(
            data=meeting.data,
            hora=meeting.hora,
            now=now,
        )
    except (AttributeError, OverflowError, TypeError, ValueError):
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    if not passed:
        _reject(CellReportApplicationErrorCode.REPORT_CONFLICT)
    if meeting.relatorio_status == RELATORIO_PENDENTE and (
        meeting.relatorio_enviado_em is not None
        or meeting.relatorio_enviado_por is not None
    ):
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)


def _load_and_authorize(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    reuniao_id: uuid.UUID,
    conversa_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
    now: dt.datetime,
) -> CelulaReuniao:
    try:
        require_tenant_scope(
            db,
            expected_igreja_id=igreja_id,
            source="cell_report_application",
        )
    except SQLAlchemyError:
        _reject_without_context(CellReportApplicationErrorCode.DATA_INTEGRITY)
    _revalidate_locked_conversation_actor(
        db,
        igreja_id=igreja_id,
        conversa_id=conversa_id,
        ator_pessoa_id=ator_pessoa_id,
    )
    meeting = _load_locked_meeting(
        db,
        igreja_id=igreja_id,
        reuniao_id=reuniao_id,
    )
    _validate_meeting_eligibility(meeting, now=now)
    _revalidate_locked_leader(
        db,
        igreja_id=igreja_id,
        meeting=meeting,
        ator_pessoa_id=ator_pessoa_id,
    )
    return meeting


def _hydrate_pending(value: object) -> CellReportPendingProposal:
    if (
        type(value) is not dict
        or value.get("schema") != CELL_REPORT_PENDING_PROPOSAL_SCHEMA_V1
    ):
        _reject(CellReportApplicationErrorCode.REPORT_CONFLICT)
    try:
        return rehydrate_cell_report_pending_proposal(value)
    except CellReportPendingProposalError:
        _reject(CellReportApplicationErrorCode.PROPOSAL_CORRUPT)


def _confirmation_for(workflow: CellReportWorkflow) -> str | None:
    if workflow.state is not CellReportWorkflowState.AWAITING_CONFIRMATION:
        return None
    try:
        return cell_report_confirmation_command(workflow)
    except CellReportWorkflowError:
        _reject(CellReportApplicationErrorCode.PROPOSAL_CORRUPT)


def _find_receipt(
    receipts: tuple[CellReportProposalOperationReceipt, ...],
    intent: AgentEffectIntent,
) -> tuple[int, CellReportProposalOperationReceipt] | None:
    for index, receipt in enumerate(receipts):
        if hmac.compare_digest(receipt.effect_id, intent.effect_id):
            if not hmac.compare_digest(
                receipt.payload_digest,
                intent.payload_digest,
            ):
                _reject(CellReportApplicationErrorCode.IDEMPOTENCY_CONFLICT)
            return index, receipt
    return None


def _proposal_expired(
    proposal: CellReportPendingProposal,
    *,
    now: dt.datetime,
) -> bool:
    try:
        remaining = proposal.expires_at - now
    except (OverflowError, TypeError, ValueError):
        _reject(CellReportApplicationErrorCode.PROPOSAL_CORRUPT)
    if remaining > MAX_CELL_REPORT_PROPOSAL_TTL:
        _reject(CellReportApplicationErrorCode.PROPOSAL_CORRUPT)
    return remaining <= dt.timedelta(0)


def propose_cell_report(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    reuniao_id: uuid.UUID,
    conversa_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
    correlation_key: str,
    turn_identity: AgentTurnIdentity,
    operation_intent: AgentEffectIntent,
    text: str | None,
    now: dt.datetime,
    expires_at: dt.datetime,
) -> CellReportProposalResult:
    """Create or revise one pending proposal in the caller transaction."""

    tenant_id = _require_uuid(igreja_id)
    meeting_id = _require_uuid(reuniao_id)
    conversation_id = _require_uuid(conversa_id)
    actor_id = _require_uuid(ator_pessoa_id)
    current_time = _canonical_utc(now)
    expiry = _canonical_utc(expires_at)
    if expiry <= current_time:
        _reject(CellReportApplicationErrorCode.PROPOSAL_EXPIRED)
    try:
        ttl = expiry - current_time
    except (OverflowError, TypeError, ValueError):
        _reject(CellReportApplicationErrorCode.INVALID_ARGUMENT)
    if ttl > MAX_CELL_REPORT_PROPOSAL_TTL:
        _reject(CellReportApplicationErrorCode.EXPIRY_LIMIT_EXCEEDED)

    bindings, patch, initial_workflow, effect_payload = _proposal_material(
        igreja_id=tenant_id,
        reuniao_id=meeting_id,
        conversa_id=conversation_id,
        ator_pessoa_id=actor_id,
        correlation_key=correlation_key,
        text=text,
        expires_at=expiry,
    )
    intent = _validate_trusted_effect(
        turn_identity=turn_identity,
        intent=operation_intent,
        igreja_id=tenant_id,
        conversa_id=conversation_id,
        expected_payload=effect_payload,
    )
    _require_external_transaction(db)
    meeting = _load_and_authorize(
        db,
        igreja_id=tenant_id,
        reuniao_id=meeting_id,
        conversa_id=conversation_id,
        ator_pessoa_id=actor_id,
        now=current_time,
    )
    if meeting.relatorio_status != RELATORIO_PENDENTE:
        _reject(CellReportApplicationErrorCode.REPORT_CONFLICT)

    try:
        base_state_digest = derive_cell_report_proposal_base_state_digest(
            relatorio_status=meeting.relatorio_status,
            oferta_valor=meeting.oferta_valor,
            observacoes=meeting.observacoes,
        )
    except CellReportPendingProposalError:
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)

    replayed = False
    prior_receipts: tuple[CellReportProposalOperationReceipt, ...] = ()
    if meeting.relatorio_snapshot is None:
        next_workflow = initial_workflow
    else:
        current = _hydrate_pending(meeting.relatorio_snapshot)
        matched = _find_receipt(current.operation_receipts, intent)
        if _proposal_expired(current, now=current_time):
            if matched is not None:
                _reject(CellReportApplicationErrorCode.PROPOSAL_EXPIRED)
            if hmac.compare_digest(
                current.workflow.scope_digest,
                initial_workflow.scope_digest,
            ):
                _reject(CellReportApplicationErrorCode.PROPOSAL_EXPIRED)
            next_workflow = initial_workflow
        else:
            if not hmac.compare_digest(
                current.base_state_digest,
                base_state_digest,
            ):
                _reject(CellReportApplicationErrorCode.REPORT_CONFLICT)
            if not cell_report_proposal_bindings_match(
                current.bindings,
                bindings,
            ):
                _reject(CellReportApplicationErrorCode.PROPOSAL_BINDING_MISMATCH)
            if not hmac.compare_digest(
                current.workflow.scope_digest,
                initial_workflow.scope_digest,
            ):
                _reject(CellReportApplicationErrorCode.PROPOSAL_BINDING_MISMATCH)
            if current.expires_at != expiry:
                _reject(CellReportApplicationErrorCode.EXPIRY_MISMATCH)
            if matched is not None:
                receipt_index, _receipt = matched
                if receipt_index != len(current.operation_receipts) - 1:
                    _reject(CellReportApplicationErrorCode.REPORT_CONFLICT)
                next_proposal = current
                replayed = True
            else:
                if (
                    len(current.operation_receipts)
                    >= MAX_CELL_REPORT_PROPOSAL_OPERATION_RECEIPTS
                ):
                    _reject(
                        CellReportApplicationErrorCode.OPERATION_LIMIT_EXCEEDED
                    )
                try:
                    merged = merge_cell_report_candidates(
                        current.workflow.candidate,
                        patch,
                    )
                    next_workflow = revise_cell_report_workflow(
                        current.workflow,
                        merged,
                    )
                except CellReportWorkflowError:
                    _reject(CellReportApplicationErrorCode.REPORT_CONFLICT)
                prior_receipts = current.operation_receipts

    if not replayed:
        try:
            next_proposal = build_cell_report_pending_proposal(
                workflow=next_workflow,
                bindings=bindings,
                expires_at=expiry,
                operation_effect_id=intent.effect_id,
                operation_payload_digest=intent.payload_digest,
                base_state_digest=base_state_digest,
                prior_operation_receipts=prior_receipts,
            )
            meeting.relatorio_snapshot = next_proposal.to_jsonb()
        except CellReportPendingProposalError:
            _reject(CellReportApplicationErrorCode.PROPOSAL_CORRUPT)
        meeting.updated_at = current_time
        _flush_sanitized(db)

    return CellReportProposalResult(
        proposal=next_proposal,
        confirmation_command=_confirmation_for(next_proposal.workflow),
        replayed=replayed,
    )


def _validate_final_replay(
    meeting: CelulaReuniao,
    *,
    ator_pessoa_id: uuid.UUID,
    submission_effect_id: str,
    submission_payload_digest: str,
) -> dict[str, object]:
    legacy = meeting.relatorio_snapshot
    # Only the complete closed panel projection is a competing human writer.
    # Malformed schema-less content remains a corruption signal.
    if is_canonical_legacy_human_report_snapshot(
        legacy,
        meeting_id=meeting.id,
        meeting_date=meeting.data,
        meeting_tema=meeting.tema,
        meeting_status=meeting.relatorio_status,
        meeting_oferta_valor=meeting.oferta_valor,
        meeting_observacoes=meeting.observacoes,
        meeting_sent_at=meeting.relatorio_enviado_em,
        meeting_sent_by=meeting.relatorio_enviado_por,
        expected_actor_id=ator_pessoa_id,
    ):
        _reject(CellReportApplicationErrorCode.REPORT_CONFLICT)
    try:
        snapshot = validate_cell_report_snapshot_v2(meeting.relatorio_snapshot)
    except CellReportSnapshotValidationError:
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    if not hmac.compare_digest(
        snapshot.submission_effect_id,
        submission_effect_id,
    ) or not hmac.compare_digest(
        snapshot.submission_payload_digest,
        submission_payload_digest,
    ):
        _reject(CellReportApplicationErrorCode.REPORT_CONFLICT)
    if (
        meeting.relatorio_enviado_por != ator_pessoa_id
        or type(meeting.relatorio_enviado_em) is not dt.datetime
        or meeting.relatorio_enviado_em.tzinfo is None
        or meeting.observacoes != snapshot.observacoes
    ):
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    if snapshot.oferta_valor is None:
        if meeting.oferta_valor is not None:
            _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    elif (
        type(meeting.oferta_valor) is not Decimal
        or meeting.oferta_valor != snapshot.oferta_valor
    ):
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    return snapshot.to_jsonb()


def confirm_cell_report(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    reuniao_id: uuid.UUID,
    conversa_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
    command: str,
    turn_identity: AgentTurnIdentity,
    submission_intent: AgentEffectIntent,
    now: dt.datetime,
    expected_replayed: bool,
) -> CellReportConfirmationResult:
    """Confirm a report bound to the caller's locked replay classification."""

    tenant_id = _require_uuid(igreja_id)
    meeting_id = _require_uuid(reuniao_id)
    conversation_id = _require_uuid(conversa_id)
    actor_id = _require_uuid(ator_pessoa_id)
    current_time = _canonical_utc(now)
    if type(expected_replayed) is not bool:
        _reject(CellReportApplicationErrorCode.INVALID_ARGUMENT)
    bindings, effect_payload = _confirmation_material(
        igreja_id=tenant_id,
        reuniao_id=meeting_id,
        conversa_id=conversation_id,
        ator_pessoa_id=actor_id,
        command=command,
    )
    intent = _validate_trusted_effect(
        turn_identity=turn_identity,
        intent=submission_intent,
        igreja_id=tenant_id,
        conversa_id=conversation_id,
        expected_payload=effect_payload,
    )
    _require_external_transaction(db)
    meeting = _load_and_authorize(
        db,
        igreja_id=tenant_id,
        reuniao_id=meeting_id,
        conversa_id=conversation_id,
        ator_pessoa_id=actor_id,
        now=current_time,
    )
    replayed = meeting.relatorio_status == RELATORIO_ENVIADO
    if expected_replayed is not replayed:
        _reject(
            CellReportApplicationErrorCode.REPLAY_EXPECTATION_MISMATCH
        )
    if replayed:
        snapshot = _validate_final_replay(
            meeting,
            ator_pessoa_id=actor_id,
            submission_effect_id=intent.effect_id,
            submission_payload_digest=intent.payload_digest,
        )
        return CellReportConfirmationResult(
            snapshot=snapshot,
            accepted_workflow=None,
            replayed=True,
            requires_caller_commit=False,
        )
    if meeting.relatorio_status != RELATORIO_PENDENTE:
        _reject(CellReportApplicationErrorCode.REPORT_CONFLICT)

    proposal = _hydrate_pending(meeting.relatorio_snapshot)
    if not cell_report_proposal_bindings_match(
        proposal.bindings,
        bindings,
    ):
        _reject(CellReportApplicationErrorCode.PROPOSAL_BINDING_MISMATCH)
    if _proposal_expired(proposal, now=current_time):
        _reject(CellReportApplicationErrorCode.PROPOSAL_EXPIRED)
    if any(
        hmac.compare_digest(receipt.effect_id, intent.effect_id)
        for receipt in proposal.operation_receipts
    ):
        _reject(CellReportApplicationErrorCode.IDEMPOTENCY_CONFLICT)
    try:
        base_state_digest = derive_cell_report_proposal_base_state_digest(
            relatorio_status=meeting.relatorio_status,
            oferta_valor=meeting.oferta_valor,
            observacoes=meeting.observacoes,
        )
    except CellReportPendingProposalError:
        _reject(CellReportApplicationErrorCode.DATA_INTEGRITY)
    if not hmac.compare_digest(
        proposal.base_state_digest,
        base_state_digest,
    ):
        _reject(CellReportApplicationErrorCode.REPORT_CONFLICT)

    try:
        accepted = correlate_cell_report_confirmation(
            proposal.workflow,
            command,
        )
    except CellReportWorkflowError:
        _reject(CellReportApplicationErrorCode.CONFIRMATION_REJECTED)
    candidate = accepted.candidate
    if (
        candidate.presentes is None
        or candidate.visitantes is None
        or candidate.decisoes is None
        or candidate.oferta is None
    ):
        _reject(CellReportApplicationErrorCode.PROPOSAL_CORRUPT)
    try:
        snapshot = build_cell_report_snapshot_v2(
            presentes=candidate.presentes,
            visitantes=candidate.visitantes,
            decisoes=candidate.decisoes,
            oferta_valor=candidate.oferta,
            observacoes=candidate.observacoes,
            submission_effect_id=intent.effect_id,
            submission_payload_digest=intent.payload_digest,
        )
    except CellReportSnapshotValidationError:
        _reject(CellReportApplicationErrorCode.PROPOSAL_CORRUPT)

    meeting.relatorio_status = RELATORIO_ENVIADO
    meeting.oferta_valor = Decimal(candidate.oferta)
    meeting.observacoes = candidate.observacoes
    meeting.relatorio_enviado_por = actor_id
    meeting.relatorio_enviado_em = current_time
    meeting.updated_at = current_time
    meeting.relatorio_snapshot = snapshot
    _flush_sanitized(db)

    return CellReportConfirmationResult(
        snapshot=validate_cell_report_snapshot_v2(snapshot).to_jsonb(),
        accepted_workflow=accepted,
        replayed=False,
        requires_caller_commit=True,
    )


__all__ = [
    "CELL_REPORT_CONFIRMATION_EFFECT_SCHEMA_V1",
    "CELL_REPORT_PROPOSAL_EFFECT_SCHEMA_V1",
    "MAX_CELL_REPORT_PROPOSAL_TTL",
    "CellReportApplicationError",
    "CellReportApplicationErrorCode",
    "CellReportConfirmationResult",
    "CellReportProposalResult",
    "build_cell_report_confirmation_effect_payload",
    "build_cell_report_proposal_effect_payload",
    "confirm_cell_report",
    "propose_cell_report",
]
