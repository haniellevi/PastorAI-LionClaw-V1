"""Shared, transaction-only finalization for a canonical cell report.

Human and WhatsApp writers retain their own input authorization, but both must
use this boundary to make the meeting terminal.  It never commits, transports,
or accepts text from a model.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Celula, CelulaReuniao
from app.db.rls_observability import require_tenant_scope
from app.domain.cell_meetings_schedule import meeting_has_passed
from app.domain.cell_report_snapshot import build_cell_report_snapshot_v2
from app.domain.cell_report_workflow import CellReportCandidate


class CellReportFinalizerError(ValueError):
    """Static failure at the meeting finalization boundary."""


@dataclass(frozen=True, slots=True, repr=False)
class FinalizedCellReport:
    meeting_id: uuid.UUID
    snapshot: dict[str, object] = field(repr=False)

    def __repr__(self) -> str:
        return "FinalizedCellReport(<aggregate-only>)"


def _require_uuid(value: object) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        raise CellReportFinalizerError("relatório inválido")
    return value


def _utc(value: object) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None:
        raise CellReportFinalizerError("relatório inválido")
    try:
        return value.astimezone(dt.timezone.utc)
    except (OverflowError, ValueError):
        raise CellReportFinalizerError("relatório inválido") from None


def _digest(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CellReportFinalizerError("relatório inválido")
    return value


def _lock_owned_meeting(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    reuniao_id: uuid.UUID,
    actor_pessoa_id: uuid.UUID,
) -> CelulaReuniao | None:
    """Lock an existing meeting and its current, active leader cell."""

    meeting = session.execute(
        select(CelulaReuniao)
        .where(
            CelulaReuniao.igreja_id == igreja_id,
            CelulaReuniao.id == reuniao_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if meeting is None:
        return None
    cell = session.execute(
        select(Celula)
        .where(
            Celula.igreja_id == igreja_id,
            Celula.id == getattr(meeting, "celula_id", None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if (
        cell is None
        or getattr(cell, "ativo", None) is not True
        or getattr(cell, "lider_id", None) != actor_pessoa_id
    ):
        return None
    return meeting


def _effect_reference(proposal_id: uuid.UUID) -> str:
    return "agent_effect_v1_" + hashlib.sha256(
        b"pastorai:v1a:cell-report-effect:v1\0" + proposal_id.bytes
    ).hexdigest()


def _payload_reference(proposal_id: uuid.UUID, payload_sha256: str) -> str:
    return "agent_payload_v1_" + hashlib.sha256(
        b"pastorai:v1a:cell-report-payload:v1\0"
        + proposal_id.bytes
        + payload_sha256.encode("ascii")
    ).hexdigest()


def _finalize_locked_cell_report(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    meeting: CelulaReuniao,
    actor_pessoa_id: uuid.UUID,
    snapshot: dict[str, object],
    oferta_valor: Decimal | None,
    observacoes: str | None,
    now: dt.datetime,
) -> FinalizedCellReport:
    """Make one already-authorized, locked meeting terminal.

    Both writers reach this short boundary only after authenticating the
    leader and taking the meeting lock.  It owns the terminal predicate and
    write set, but intentionally neither commits nor transports.
    """

    if (
        getattr(meeting, "igreja_id", None) != igreja_id
        or getattr(meeting, "relatorio_status", None) != "pendente"
        or getattr(meeting, "status", None) == "cancelada"
        or type(getattr(meeting, "data", None)) is not dt.date
        or type(snapshot) is not dict
        or type(oferta_valor) not in {Decimal, type(None)}
        or (
            type(oferta_valor) is Decimal
            and (not oferta_valor.is_finite() or oferta_valor < 0)
        )
        or type(observacoes) not in {str, type(None)}
    ):
        raise CellReportFinalizerError("relatório indisponível")

    meeting.relatorio_status = "enviado"
    meeting.relatorio_enviado_em = now
    meeting.relatorio_enviado_por = actor_pessoa_id
    meeting.updated_at = now
    meeting.relatorio_snapshot = snapshot
    meeting.oferta_valor = oferta_valor
    meeting.observacoes = observacoes
    session.flush()
    return FinalizedCellReport(meeting_id=meeting.id, snapshot=snapshot)


def finalize_human_cell_report(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    meeting: CelulaReuniao,
    actor_pessoa_id: uuid.UUID,
    snapshot: dict[str, object],
    oferta_valor: Decimal | None,
    observacoes: str | None,
    now: dt.datetime,
) -> FinalizedCellReport:
    """Finalize the authenticated panel writer through the shared boundary.

    ``meeting`` must be the same row locked and authorized by the panel route.
    The panel retains its established full snapshot; the WhatsApp path writes
    the aggregate-only snapshot below.
    """

    igreja_id = _require_uuid(igreja_id)
    actor_pessoa_id = _require_uuid(actor_pessoa_id)
    now = _utc(now)
    if type(oferta_valor) not in {Decimal, type(None)}:
        raise CellReportFinalizerError("relatório inválido")
    # The legacy panel snapshot is built before the terminal write. Its schema
    # is intentionally distinct from the closed V2 aggregate snapshot used by
    # WhatsApp, so attach panel-only terminal facts here rather than in the
    # shared finalizer.
    terminal_snapshot = dict(snapshot)
    terminal_snapshot["relatorio_status"] = "enviado"
    return _finalize_locked_cell_report(
        session,
        igreja_id=igreja_id,
        meeting=meeting,
        actor_pessoa_id=actor_pessoa_id,
        snapshot=terminal_snapshot,
        oferta_valor=oferta_valor,
        observacoes=observacoes,
        now=now,
    )


def finalize_v1a_cell_report(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    reuniao_id: uuid.UUID,
    actor_pessoa_id: uuid.UUID,
    candidate: CellReportCandidate,
    proposal_id: uuid.UUID,
    draft_payload_sha256: str,
    now: dt.datetime,
) -> FinalizedCellReport:
    """Persist one aggregate-only official report in the caller transaction.

    The S3 proposal executor supplies the server-owned actor, meeting and
    proposal identifiers.  A second call conflicts after the first finalizer
    changes the meeting status, which keeps human and WhatsApp writers aligned.
    """

    igreja_id = _require_uuid(igreja_id)
    reuniao_id = _require_uuid(reuniao_id)
    actor_pessoa_id = _require_uuid(actor_pessoa_id)
    proposal_id = _require_uuid(proposal_id)
    now = _utc(now)
    payload_sha256 = _digest(draft_payload_sha256)
    if (
        type(candidate) is not CellReportCandidate
        or not candidate.is_complete
        or candidate.observacoes is not None
        or type(candidate.presentes) is not int
        or type(candidate.visitantes) is not int
        or type(candidate.decisoes) is not int
        or type(candidate.oferta) is not str
    ):
        raise CellReportFinalizerError("relatório inválido")
    require_tenant_scope(
        session,
        expected_igreja_id=igreja_id,
        source="cell_report_finalizer",
    )
    meeting = _lock_owned_meeting(
        session,
        igreja_id=igreja_id,
        reuniao_id=reuniao_id,
        actor_pessoa_id=actor_pessoa_id,
    )
    if meeting is None:
        raise CellReportFinalizerError("relatório indisponível")
    if (
        type(getattr(meeting, "data", None)) is not dt.date
        or not meeting_has_passed(
            data=meeting.data,
            hora=getattr(meeting, "hora", None),
            now=now,
        )
    ):
        raise CellReportFinalizerError("relatório indisponível")
    snapshot = build_cell_report_snapshot_v2(
        presentes=candidate.presentes,
        visitantes=candidate.visitantes,
        decisoes=candidate.decisoes,
        oferta_valor=candidate.oferta,
        observacoes=None,
        submission_effect_id=_effect_reference(proposal_id),
        submission_payload_digest=_payload_reference(proposal_id, payload_sha256),
    )
    try:
        offering = Decimal(candidate.oferta)
    except (InvalidOperation, TypeError, ValueError):
        raise CellReportFinalizerError("relatório inválido") from None
    return _finalize_locked_cell_report(
        session,
        igreja_id=igreja_id,
        meeting=meeting,
        actor_pessoa_id=actor_pessoa_id,
        snapshot=snapshot,
        oferta_valor=offering,
        observacoes=None,
        now=now,
    )


__all__ = [
    "CellReportFinalizerError",
    "FinalizedCellReport",
    "finalize_human_cell_report",
    "finalize_v1a_cell_report",
]
