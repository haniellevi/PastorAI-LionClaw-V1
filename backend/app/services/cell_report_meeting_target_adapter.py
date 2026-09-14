"""Offline fail-closed bridge from a trusted resolver to an opaque target.

The adapter accepts only server-owned identity objects and a caller-owned
transaction.  It does not create a transaction, choose a meeting, grant
consent, stage a report, or write domain state.  Its sole successful result is
the existing process-local ``CellReportMeetingTarget`` after the inbound,
tenant, actor, transaction, and resolver bindings have all been revalidated.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import Enum
from typing import Callable

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.turn_identity import AgentTurnIdentity
from app.db.rls_observability import require_tenant_scope
from app.db.tenant_session import TenantScopeError
from app.deps import CurrentUser
from app.services import cell_report_meeting_resolver as meeting_resolver
from app.services import cell_report_whatsapp_coordinator as coordinator


class CellReportMeetingTargetAdapterErrorCode(str, Enum):
    """Static rejection categories that contain no tenant or inbound detail."""

    INVALID_IDENTITY = "INVALID_IDENTITY"
    TENANT_SCOPE_REQUIRED = "TENANT_SCOPE_REQUIRED"
    INBOUND_REJECTED = "INBOUND_REJECTED"
    ACTOR_BINDING_INVALID = "ACTOR_BINDING_INVALID"
    CLOCK_INVALID = "CLOCK_INVALID"
    RESOLUTION_REJECTED = "RESOLUTION_REJECTED"
    RESOLUTION_NOT_CANDIDATE = "RESOLUTION_NOT_CANDIDATE"
    TRANSACTION_BINDING_INVALID = "TRANSACTION_BINDING_INVALID"
    MEETING_TARGET_INVALID = "MEETING_TARGET_INVALID"


class CellReportMeetingTargetAdapterError(RuntimeError):
    """Sanitized fail-closed error emitted by this offline adapter."""

    def __init__(self, code: CellReportMeetingTargetAdapterErrorCode) -> None:
        self.code = code
        super().__init__(f"cell report meeting target rejected: {code.value}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code.value!r})"


def _reject(code: CellReportMeetingTargetAdapterErrorCode) -> None:
    raise CellReportMeetingTargetAdapterError(code)


def _reject_without_context(code: CellReportMeetingTargetAdapterErrorCode) -> None:
    raise CellReportMeetingTargetAdapterError(code) from None


def _canonical_uuid(value: object) -> uuid.UUID:
    """Accept exactly one non-nil canonical UUID string from CurrentUser."""

    if type(value) is not str:
        _reject(CellReportMeetingTargetAdapterErrorCode.INVALID_IDENTITY)
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        _reject_without_context(CellReportMeetingTargetAdapterErrorCode.INVALID_IDENTITY)
    if parsed.int == 0 or str(parsed) != value:
        _reject(CellReportMeetingTargetAdapterErrorCode.INVALID_IDENTITY)
    return parsed


def _require_current_user(value: object) -> tuple[CurrentUser, uuid.UUID, uuid.UUID]:
    if type(value) is not CurrentUser:
        _reject(CellReportMeetingTargetAdapterErrorCode.INVALID_IDENTITY)
    tenant_id = _canonical_uuid(value.igreja_id)
    app_user_id = _canonical_uuid(value.app_user_id)
    if (
        type(value.clerk_user_id) is not str
        or not value.clerk_user_id
        or value.clerk_user_id != value.clerk_user_id.strip()
    ):
        _reject(CellReportMeetingTargetAdapterErrorCode.INVALID_IDENTITY)
    return value, tenant_id, app_user_id


def _require_turn_identity(value: object) -> AgentTurnIdentity:
    try:
        return coordinator._require_identity(value)
    except coordinator.CellReportCoordinatorError:
        _reject_without_context(CellReportMeetingTargetAdapterErrorCode.INVALID_IDENTITY)


def _require_tenant(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    source: str,
) -> None:
    try:
        require_tenant_scope(
            db,
            expected_igreja_id=tenant_id,
            source=source,
        )
    except (SQLAlchemyError, TenantScopeError, AttributeError, TypeError, ValueError):
        _reject_without_context(
            CellReportMeetingTargetAdapterErrorCode.TENANT_SCOPE_REQUIRED
        )


def _require_external_transaction_before_scope(db: Session) -> None:
    """Prevent a tenant-scope probe from autobeginning a caller-less session."""

    try:
        coordinator._require_external_transaction(db)
    except coordinator.CellReportCoordinatorError:
        _reject_without_context(CellReportMeetingTargetAdapterErrorCode.INBOUND_REJECTED)


def _require_bound_context(
    value: object,
    *,
    identity: AgentTurnIdentity,
    tenant_id: uuid.UUID,
) -> coordinator._InboundContext:
    if type(value) is not coordinator._InboundContext:
        _reject(CellReportMeetingTargetAdapterErrorCode.INBOUND_REJECTED)
    try:
        context_tenant_id = value.igreja_id
        conversation_id = value.conversation_id
        inbound_message_id = value.inbound_message_id
        actor_pessoa_id = value.actor_pessoa_id
    except AttributeError:
        _reject_without_context(CellReportMeetingTargetAdapterErrorCode.INBOUND_REJECTED)
    if (
        context_tenant_id != tenant_id
        or context_tenant_id != identity.igreja_id
        or conversation_id != identity.conversation_id
        or inbound_message_id != identity.inbound_message_id
        or type(actor_pessoa_id) is not uuid.UUID
        or actor_pessoa_id.int == 0
    ):
        _reject(CellReportMeetingTargetAdapterErrorCode.INBOUND_REJECTED)
    return value


def _require_transaction_handles(value: object) -> tuple[object, object | None]:
    if type(value) is not tuple or len(value) != 2 or value[0] is None:
        _reject(CellReportMeetingTargetAdapterErrorCode.INBOUND_REJECTED)
    return value[0], value[1]


def _load_bound_actor(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    app_user_id: uuid.UUID,
    current_user: CurrentUser,
) -> uuid.UUID:
    try:
        actor_pessoa_id = meeting_resolver._load_actor_pessoa_id(
            db,
            igreja_id=tenant_id,
            app_user_id=app_user_id,
            clerk_user_id=current_user.clerk_user_id,
        )
    except (
        meeting_resolver.CellReportMeetingResolverError,
        SQLAlchemyError,
        AttributeError,
        TypeError,
        ValueError,
    ):
        _reject_without_context(
            CellReportMeetingTargetAdapterErrorCode.ACTOR_BINDING_INVALID
        )
    if type(actor_pessoa_id) is not uuid.UUID or actor_pessoa_id.int == 0:
        _reject(CellReportMeetingTargetAdapterErrorCode.ACTOR_BINDING_INVALID)
    return actor_pessoa_id


def _read_clock(clock: Callable[[], dt.datetime] | object) -> dt.datetime:
    if not callable(clock):
        _reject(CellReportMeetingTargetAdapterErrorCode.CLOCK_INVALID)
    try:
        now = clock()
    except Exception:
        _reject_without_context(CellReportMeetingTargetAdapterErrorCode.CLOCK_INVALID)
    if type(now) is not dt.datetime:
        _reject(CellReportMeetingTargetAdapterErrorCode.CLOCK_INVALID)
    return now


def _candidate_meeting_id(value: object) -> uuid.UUID:
    if type(value) is not meeting_resolver.CellReportMeetingResolution:
        _reject(CellReportMeetingTargetAdapterErrorCode.RESOLUTION_REJECTED)
    if value.status is not meeting_resolver.CellReportMeetingResolutionStatus.CANDIDATE:
        _reject(CellReportMeetingTargetAdapterErrorCode.RESOLUTION_NOT_CANDIDATE)
    candidate = value.candidate
    if (
        type(candidate) is not meeting_resolver.CellReportMeetingCandidate
        or value.candidates != (candidate,)
        or type(candidate.reuniao_id) is not uuid.UUID
        or candidate.reuniao_id.int == 0
    ):
        _reject(CellReportMeetingTargetAdapterErrorCode.RESOLUTION_REJECTED)
    return candidate.reuniao_id


def _require_same_transaction(
    db: Session,
    *,
    expected_handles: tuple[object, object | None],
) -> None:
    try:
        current_handles = coordinator._require_external_transaction(db)
    except coordinator.CellReportCoordinatorError:
        _reject_without_context(
            CellReportMeetingTargetAdapterErrorCode.TRANSACTION_BINDING_INVALID
        )
    if (
        current_handles[0] is not expected_handles[0]
        or current_handles[1] is not expected_handles[1]
    ):
        _reject(CellReportMeetingTargetAdapterErrorCode.TRANSACTION_BINDING_INVALID)


def resolve_cell_report_meeting_target(
    db: Session,
    *,
    current_user: CurrentUser,
    turn_identity: AgentTurnIdentity,
    clock: Callable[[], dt.datetime],
) -> coordinator.CellReportMeetingTarget:
    """Resolve exactly one eligible meeting into the existing opaque target.

    The caller supplies no actor, tenant, inbound, meeting or purpose.  The
    transaction remains entirely caller-owned; a successful target is still
    not consent, a proposal, a confirmation, or a domain write.
    """

    trusted_user, tenant_id, app_user_id = _require_current_user(current_user)
    identity = _require_turn_identity(turn_identity)
    if identity.igreja_id != tenant_id:
        _reject(CellReportMeetingTargetAdapterErrorCode.INVALID_IDENTITY)

    with db.no_autoflush:
        _require_external_transaction_before_scope(db)
        _require_tenant(
            db,
            tenant_id=tenant_id,
            source="cell_report_meeting_target_adapter",
        )
        try:
            raw_context, raw_handles = coordinator._load_bound_inbound(
                db,
                identity=identity,
            )
        except coordinator.CellReportCoordinatorError:
            _reject_without_context(
                CellReportMeetingTargetAdapterErrorCode.INBOUND_REJECTED
            )
        context = _require_bound_context(
            raw_context,
            identity=identity,
            tenant_id=tenant_id,
        )
        transaction_handles = _require_transaction_handles(raw_handles)

        actor_before = _load_bound_actor(
            db,
            tenant_id=tenant_id,
            app_user_id=app_user_id,
            current_user=trusted_user,
        )
        if actor_before != context.actor_pessoa_id:
            _reject(CellReportMeetingTargetAdapterErrorCode.ACTOR_BINDING_INVALID)

        now = _read_clock(clock)
        try:
            resolution = meeting_resolver.resolve_pending_cell_report_meeting(
                db,
                current_user=trusted_user,
                now=now,
            )
        except meeting_resolver.CellReportMeetingResolverError:
            _reject_without_context(
                CellReportMeetingTargetAdapterErrorCode.RESOLUTION_REJECTED
            )
        meeting_id = _candidate_meeting_id(resolution)

        _require_tenant(
            db,
            tenant_id=tenant_id,
            source="cell_report_meeting_target_adapter_before_mint",
        )
        _require_same_transaction(db, expected_handles=transaction_handles)
        actor_after = _load_bound_actor(
            db,
            tenant_id=tenant_id,
            app_user_id=app_user_id,
            current_user=trusted_user,
        )
        if actor_after != context.actor_pessoa_id:
            _reject(CellReportMeetingTargetAdapterErrorCode.ACTOR_BINDING_INVALID)

        try:
            return coordinator._mint_cell_report_meeting_target(
                identity,
                actor_pessoa_id=actor_after,
                meeting_id=meeting_id,
            )
        except coordinator.CellReportCoordinatorError:
            _reject_without_context(
                CellReportMeetingTargetAdapterErrorCode.MEETING_TARGET_INVALID
            )


__all__ = ["resolve_cell_report_meeting_target"]
