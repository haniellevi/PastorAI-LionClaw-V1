"""Resolve a pending cell-report meeting from a server-authenticated leader.

This is a read-only bridge for callers that already possess an authenticated
``CurrentUser``.  It deliberately does not accept a tenant or actor supplied by
the model, does not choose between multiple meetings, and does not create a
report proposal or effect.  A future WhatsApp caller must pass through this
same resolver before handing an explicitly selected meeting to the existing
application/UoW transaction boundary.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Final

from sqlalchemy import and_, nulls_last, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import AppUser, Celula, CelulaReuniao, Pessoa, UserRole
from app.db.rls_observability import require_tenant_scope
from app.db.tenant_session import TenantScopeError
from app.deps import CurrentUser
from app.domain.agent_authz import MINISTERIAL_ROLES
from app.domain.cell_meetings_schedule import meeting_has_passed
from app.services.cell_report_application import (
    RELATORIO_PENDENTE,
    STATUS_CANCELADA,
    VALID_MEETING_STATUSES,
    VALID_REPORT_STATUSES,
)


class CellReportMeetingResolutionStatus(str, Enum):
    """Closed cardinality result; no implicit choice is made."""

    NONE = "none"
    CANDIDATE = "candidate"
    AMBIGUOUS = "ambiguous"


class CellReportMeetingResolverErrorCode(str, Enum):
    """Static failure categories that never contain caller material."""

    INVALID_IDENTITY = "INVALID_IDENTITY"
    INVALID_MEETING_ID = "INVALID_MEETING_ID"
    TENANT_SCOPE_REQUIRED = "TENANT_SCOPE_REQUIRED"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    TOO_MANY_CANDIDATES = "TOO_MANY_CANDIDATES"


class CellReportMeetingResolverError(RuntimeError):
    """Sanitized rejection from the server-bound resolver."""

    def __init__(self, code: CellReportMeetingResolverErrorCode) -> None:
        self.code = code
        super().__init__(f"cell report meeting resolution rejected: {code.value}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code.value!r})"


@dataclass(frozen=True, slots=True, repr=False)
class CellReportMeetingCandidate:
    """Minimal tenant-private meeting binding returned to a trusted caller."""

    reuniao_id: uuid.UUID
    celula_id: uuid.UUID
    data: dt.date
    hora: str | None
    status: str
    relatorio_status: str


@dataclass(frozen=True, slots=True, repr=False)
class CellReportMeetingResolution:
    """The only allowed resolution outcomes for a pending report lookup."""

    status: CellReportMeetingResolutionStatus
    candidate: CellReportMeetingCandidate | None
    candidates: tuple[CellReportMeetingCandidate, ...]

    def __post_init__(self) -> None:
        if type(self.status) is not CellReportMeetingResolutionStatus:
            raise ValueError("resolution status is not recognized")
        if self.status is CellReportMeetingResolutionStatus.NONE:
            if self.candidate is not None or self.candidates:
                raise ValueError("none resolution must not contain candidates")
        elif self.status is CellReportMeetingResolutionStatus.CANDIDATE:
            if self.candidate is None or self.candidates != (self.candidate,):
                raise ValueError("candidate resolution must contain one candidate")
        elif self.status is CellReportMeetingResolutionStatus.AMBIGUOUS:
            if self.candidate is not None or len(self.candidates) < 2:
                raise ValueError(
                    "ambiguous resolution must contain multiple candidates"
                )
        else:
            raise ValueError("resolution status is not recognized")

    def __repr__(self) -> str:
        return (
            "CellReportMeetingResolution("
            f"status={self.status.value!r}, "
            f"candidate_count={len(self.candidates)})"
        )


_ACTIVE_ACCESS_STATUSES: Final = (None, "ativo")
_MEETING_ROW_WIDTH: Final = 16
_MAX_RESOLUTION_CANDIDATES: Final = 100


def _reject(code: CellReportMeetingResolverErrorCode) -> None:
    raise CellReportMeetingResolverError(code)


def _reject_without_context(code: CellReportMeetingResolverErrorCode) -> None:
    raise CellReportMeetingResolverError(code) from None


def _parse_uuid(value: object, code: CellReportMeetingResolverErrorCode) -> uuid.UUID:
    if type(value) is uuid.UUID and value.int != 0:
        return value
    if type(value) is not str or not value:
        _reject_without_context(code)
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        _reject_without_context(code)
    if parsed.int == 0:
        _reject_without_context(code)
    return parsed


def _read_rows(db: Session, statement: object) -> list[object]:
    try:
        return list(db.execute(statement).all())
    except (AttributeError, SQLAlchemyError, TypeError, ValueError):
        _reject_without_context(CellReportMeetingResolverErrorCode.DATA_UNAVAILABLE)


def _none() -> CellReportMeetingResolution:
    return CellReportMeetingResolution(
        status=CellReportMeetingResolutionStatus.NONE,
        candidate=None,
        candidates=(),
    )


def _load_actor_pessoa_id(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    app_user_id: uuid.UUID,
    clerk_user_id: str,
) -> uuid.UUID | None:
    """Revalidate the authenticated access and ministerial role in the tenant."""

    principal_rows = _read_rows(
        db,
        select(
            AppUser.id,
            AppUser.igreja_id,
            AppUser.pessoa_id,
            AppUser.status,
        )
        .where(
            AppUser.id == app_user_id,
            AppUser.igreja_id == igreja_id,
            AppUser.clerk_user_id == clerk_user_id,
            or_(AppUser.status.is_(None), AppUser.status == "ativo"),
        )
        .limit(2),
    )
    if len(principal_rows) != 1:
        return None
    try:
        access_id, access_tenant_id, pessoa_id, access_status = principal_rows[0]
    except (TypeError, ValueError):
        _reject_without_context(CellReportMeetingResolverErrorCode.DATA_UNAVAILABLE)
    if (
        type(access_id) is not uuid.UUID
        or access_id.int == 0
        or access_id != app_user_id
        or access_tenant_id != igreja_id
        or type(pessoa_id) is not uuid.UUID
        or pessoa_id.int == 0
        or access_status not in _ACTIVE_ACCESS_STATUSES
    ):
        return None

    # Match the human writer's exactly-one-usable-access rule.  A stale or
    # duplicated panel access must not silently select one identity.
    usable_accesses = _read_rows(
        db,
        select(AppUser.id, AppUser.igreja_id, AppUser.pessoa_id)
        .where(
            AppUser.igreja_id == igreja_id,
            AppUser.pessoa_id == pessoa_id,
            or_(AppUser.status.is_(None), AppUser.status == "ativo"),
        )
        .order_by(AppUser.id.asc())
        .limit(2),
    )
    if len(usable_accesses) != 1:
        return None
    try:
        usable_id, usable_tenant_id, usable_person_id = usable_accesses[0]
    except (TypeError, ValueError):
        _reject_without_context(CellReportMeetingResolverErrorCode.DATA_UNAVAILABLE)
    if (
        usable_id != app_user_id
        or usable_tenant_id != igreja_id
        or usable_person_id != pessoa_id
    ):
        return None

    role_rows = _read_rows(
        db,
        select(UserRole.id, UserRole.igreja_id, UserRole.user_id, UserRole.papel)
        .where(
            UserRole.igreja_id == igreja_id,
            UserRole.user_id == app_user_id,
            UserRole.papel.in_(tuple(sorted(MINISTERIAL_ROLES))),
        )
        .order_by(UserRole.id.asc())
        .limit(1),
    )
    if len(role_rows) != 1:
        return None
    try:
        role_id, role_tenant_id, role_user_id, role_name = role_rows[0]
    except (TypeError, ValueError):
        _reject_without_context(CellReportMeetingResolverErrorCode.DATA_UNAVAILABLE)
    if (
        type(role_id) is not uuid.UUID
        or role_id.int == 0
        or role_tenant_id != igreja_id
        or role_user_id != app_user_id
        or role_name not in MINISTERIAL_ROLES
    ):
        return None
    return pessoa_id


def _meeting_statement(
    *,
    igreja_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
    suggested_reuniao_id: uuid.UUID | None,
):
    statement = (
        select(
            CelulaReuniao.id,
            CelulaReuniao.igreja_id,
            CelulaReuniao.celula_id,
            CelulaReuniao.data,
            CelulaReuniao.hora,
            CelulaReuniao.status,
            CelulaReuniao.relatorio_status,
            Celula.id,
            Celula.igreja_id,
            Celula.ativo,
            Celula.lider_id,
            Pessoa.id,
            Pessoa.igreja_id,
            Pessoa.arquivada_em,
            Pessoa.optout,
            Pessoa.sem_interesse,
        )
        .join(
            Celula,
            and_(
                Celula.id == CelulaReuniao.celula_id,
                Celula.igreja_id == igreja_id,
            ),
        )
        .join(
            Pessoa,
            and_(Pessoa.id == ator_pessoa_id, Pessoa.igreja_id == igreja_id),
        )
        .where(
            CelulaReuniao.igreja_id == igreja_id,
            Celula.ativo.is_(True),
            Celula.lider_id == ator_pessoa_id,
            Pessoa.arquivada_em.is_(None),
            Pessoa.optout.is_(False),
            Pessoa.sem_interesse.is_(False),
            CelulaReuniao.status.in_(tuple(sorted(VALID_MEETING_STATUSES))),
            CelulaReuniao.status != STATUS_CANCELADA,
            CelulaReuniao.relatorio_status == RELATORIO_PENDENTE,
        )
        .order_by(
            CelulaReuniao.data.asc(),
            nulls_last(CelulaReuniao.hora.asc()),
            CelulaReuniao.id.asc(),
        )
        .limit(_MAX_RESOLUTION_CANDIDATES + 1)
    )
    if suggested_reuniao_id is not None:
        statement = statement.where(CelulaReuniao.id == suggested_reuniao_id)
    return statement


def _candidate_from_row(
    row: object,
    *,
    igreja_id: uuid.UUID,
    ator_pessoa_id: uuid.UUID,
    now: dt.datetime | None,
) -> CellReportMeetingCandidate | None:
    try:
        values = tuple(row)  # SQLAlchemy Row and synthetic test rows alike.
    except TypeError:
        _reject_without_context(CellReportMeetingResolverErrorCode.DATA_UNAVAILABLE)
    if len(values) != _MEETING_ROW_WIDTH:
        _reject_without_context(CellReportMeetingResolverErrorCode.DATA_UNAVAILABLE)
    (
        meeting_id,
        meeting_tenant_id,
        meeting_cell_id,
        meeting_date,
        meeting_time,
        meeting_status,
        report_status,
        cell_id,
        cell_tenant_id,
        cell_active,
        cell_leader_id,
        person_id,
        person_tenant_id,
        person_archived_at,
        person_optout,
        person_without_interest,
    ) = values

    if any(
        type(value) is not uuid.UUID or value.int == 0
        for value in (
            meeting_id,
            meeting_tenant_id,
            meeting_cell_id,
            cell_id,
            cell_tenant_id,
            cell_leader_id,
            person_id,
            person_tenant_id,
        )
    ):
        _reject_without_context(CellReportMeetingResolverErrorCode.DATA_UNAVAILABLE)
    if (
        meeting_tenant_id != igreja_id
        or cell_tenant_id != igreja_id
        or person_tenant_id != igreja_id
        or meeting_cell_id != cell_id
        or cell_leader_id != ator_pessoa_id
        or person_id != ator_pessoa_id
    ):
        return None
    if (
        type(meeting_date) is not dt.date
        or (meeting_time is not None and type(meeting_time) is not str)
        or type(meeting_status) is not str
        or meeting_status not in VALID_MEETING_STATUSES
        or type(report_status) is not str
        or report_status not in VALID_REPORT_STATUSES
    ):
        _reject(CellReportMeetingResolverErrorCode.DATA_UNAVAILABLE)
    if (
        cell_active is not True
        or person_archived_at is not None
        or person_optout is not False
        or person_without_interest is not False
        or meeting_status == STATUS_CANCELADA
        or report_status != RELATORIO_PENDENTE
    ):
        return None
    try:
        passed = meeting_has_passed(
            data=meeting_date,
            hora=meeting_time,
            now=now,
        )
    except (AttributeError, OverflowError, TypeError, ValueError):
        _reject_without_context(CellReportMeetingResolverErrorCode.DATA_UNAVAILABLE)
    if not passed:
        return None
    return CellReportMeetingCandidate(
        reuniao_id=meeting_id,
        celula_id=meeting_cell_id,
        data=meeting_date,
        hora=meeting_time,
        status=meeting_status,
        relatorio_status=report_status,
    )


def _resolution(
    candidates: list[CellReportMeetingCandidate],
) -> CellReportMeetingResolution:
    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.data,
                item.hora is None,
                item.hora or "",
                item.reuniao_id.hex,
            ),
        )
    )
    if not ordered:
        return _none()
    if len(ordered) == 1:
        return CellReportMeetingResolution(
            status=CellReportMeetingResolutionStatus.CANDIDATE,
            candidate=ordered[0],
            candidates=ordered,
        )
    return CellReportMeetingResolution(
        status=CellReportMeetingResolutionStatus.AMBIGUOUS,
        candidate=None,
        candidates=ordered,
    )


def resolve_pending_cell_report_meeting(
    db: Session,
    *,
    current_user: CurrentUser,
    now: dt.datetime | None = None,
    suggested_reuniao_id: object | None = None,
) -> CellReportMeetingResolution:
    """Resolve eligible past meetings for the authenticated cell leader.

    ``suggested_reuniao_id`` is merely an untrusted selector.  It is accepted
    only if the same tenant, active leadership, person state, report state and
    past-meeting checks all succeed.  Invalid or ineligible suggestions return
    the same empty result as no eligible meeting, avoiding an existence oracle.
    """

    if type(current_user) is not CurrentUser:
        _reject(CellReportMeetingResolverErrorCode.INVALID_IDENTITY)
    tenant_id = _parse_uuid(
        current_user.igreja_id,
        CellReportMeetingResolverErrorCode.INVALID_IDENTITY,
    )
    app_user_id = _parse_uuid(
        current_user.app_user_id,
        CellReportMeetingResolverErrorCode.INVALID_IDENTITY,
    )
    if type(current_user.clerk_user_id) is not str or not current_user.clerk_user_id:
        _reject(CellReportMeetingResolverErrorCode.INVALID_IDENTITY)
    suggested_id = None
    if suggested_reuniao_id is not None:
        suggested_id = _parse_uuid(
            suggested_reuniao_id,
            CellReportMeetingResolverErrorCode.INVALID_MEETING_ID,
        )

    try:
        require_tenant_scope(
            db,
            expected_igreja_id=tenant_id,
            source="cell_report_meeting_resolver",
        )
    except TenantScopeError:
        _reject_without_context(
            CellReportMeetingResolverErrorCode.TENANT_SCOPE_REQUIRED
        )
    except (SQLAlchemyError, AttributeError, TypeError, ValueError):
        _reject_without_context(CellReportMeetingResolverErrorCode.DATA_UNAVAILABLE)

    actor_id = _load_actor_pessoa_id(
        db,
        igreja_id=tenant_id,
        app_user_id=app_user_id,
        clerk_user_id=current_user.clerk_user_id,
    )
    if actor_id is None:
        return _none()

    rows = _read_rows(
        db,
        _meeting_statement(
            igreja_id=tenant_id,
            ator_pessoa_id=actor_id,
            suggested_reuniao_id=suggested_id,
        ),
    )
    if len(rows) > _MAX_RESOLUTION_CANDIDATES:
        _reject_without_context(
            CellReportMeetingResolverErrorCode.TOO_MANY_CANDIDATES
        )
    candidates = [
        candidate
        for row in rows
        if (
            candidate := _candidate_from_row(
                row,
                igreja_id=tenant_id,
                ator_pessoa_id=actor_id,
                now=now,
            )
        )
        is not None
        and (suggested_id is None or candidate.reuniao_id == suggested_id)
    ]
    return _resolution(candidates)


__all__ = [
    "CellReportMeetingCandidate",
    "CellReportMeetingResolution",
    "CellReportMeetingResolutionStatus",
    "CellReportMeetingResolverError",
    "CellReportMeetingResolverErrorCode",
    "resolve_pending_cell_report_meeting",
]
