"""Transactional V1a report collection and S3 proposal adapter.

This module owns only the short database phases of the text report flow.  A
caller supplies a server-resolved ``PrivilegeContext`` and an already-reserved
outbound message.  It never commits, sends a message, calls an LLM, or accepts
an actor, meeting, tenant, target, or raw summary from a model.

The durable S3 proposal remains the sole delivery and confirmation authority.
``CellReportDraft`` stores a 24-hour aggregate-only revision; it is neither an
offer nor a second confirmation protocol.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import unicodedata
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AgentActionProposal,
    Celula,
    CelulaReuniao,
    CellReportDraft,
    ConsentRecord,
    Conversation,
    Message,
)
from app.db.rls_observability import require_tenant_scope
from app.domain.cell_meetings_schedule import meeting_has_passed
from app.domain.cell_report_v1a import (
    CellReportV1aError,
    merge_v1a_cell_report_text,
    parse_v1a_cell_report_text,
    render_v1a_cell_report_summary,
)
from app.domain.cell_report_workflow import CellReportCandidate
from app.domain.cell_report_workflow import build_cell_report_candidate
from app.services.agent_action_proposals import (
    ActionEffect,
    AgentAction,
    ExecutionContext,
    PreparedActionProposal,
    ProposalContractError,
    ProposalExecutionDenied,
    ProposalTarget,
    canonical_arguments_sha256,
    prepare_action_proposal,
)
from app.services.cell_report_finalizer import (
    CellReportFinalizerError,
    finalize_v1a_cell_report,
)
from app.services.cell_report_whatsapp import (
    CellReportWhatsappError,
    LgpdConsentRecord,
    cell_report_enabled_from_environment,
    canonical_v1a_draft_payload,
    complete_v1a_candidate_from_projection,
    current_v1a_lgpd_acceptance,
    rehydrate_v1a_draft_candidate,
    settle_v1a_extraction_budget,
    v1a_whitelisted_extraction_projection,
)
from app.services import whatsapp_privilege
from app.services.whatsapp_privilege import PrivilegeContext


_DRAFT_COLLECTING = "coletando"
_DRAFT_READY = "pronto"
_DRAFT_COMPLETED = "concluido"
_DRAFT_CANCELLED = "cancelado"
_DRAFT_EXPIRED = "expirado"
_DRAFT_ACTIVE = frozenset({_DRAFT_COLLECTING, _DRAFT_READY})
_DRAFT_TTL = dt.timedelta(hours=24)
_REPORT_ACTION = AgentAction.ENVIAR_RELATORIO_CELULA
_V1A_CLARIFY_FORMAT = (
    " Exemplo válido: presentes: 8, visitantes: 2, decisões: 1, "
    "oferta: R$ 42,50. Separe os campos por vírgula ou quebra de linha."
)


class CellReportV1aServiceError(ValueError):
    """Static rejection from the aggregate-only V1a adapter."""


class CellReportStageKind(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    CLARIFY = "clarify"
    EXTRACTION = "extraction"
    SUMMARY = "summary"
    HUMAN_REQUIRED = "human_required"


@dataclass(frozen=True, slots=True, repr=False)
class CellReportTurnStage:
    """One no-transport response for the current V1a inbound.

    ``SUMMARY`` always contains one prepared S3 proposal bound to the reserved
    outbound summary row.  ``CLARIFY`` does not create a proposal.
    """

    kind: CellReportStageKind
    response: str | None = field(repr=False)
    proposal: PreparedActionProposal | None = field(default=None, repr=False)
    draft_id: uuid.UUID | None = field(default=None, repr=False)
    draft_revision: int | None = field(default=None, repr=False)
    extraction_projection: dict[str, str] | None = field(default=None, repr=False)
    persist_before_handoff: bool = field(default=False, repr=False)

    def __repr__(self) -> str:
        return f"CellReportTurnStage(kind={self.kind.value!r})"


@dataclass(frozen=True, slots=True, repr=False)
class _Meeting:
    id: uuid.UUID
    cell_name: str = field(repr=False)
    date: dt.date


@dataclass(frozen=True, slots=True, repr=False)
class _DraftReference:
    id: uuid.UUID
    meeting_id: uuid.UUID
    revision: int | None = None


def _reject() -> None:
    raise CellReportV1aServiceError("relatório de célula indisponível")


def _utc(value: object) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None:
        _reject()
    try:
        return value.astimezone(dt.timezone.utc)
    except (OverflowError, ValueError):
        _reject()


def _now(session: Session, value: dt.datetime | None) -> dt.datetime:
    if value is not None:
        return _utc(value)
    from sqlalchemy import func

    return _utc(session.execute(select(func.clock_timestamp())).scalar_one())


def _require_context(context: object) -> PrivilegeContext:
    if type(context) is not PrivilegeContext:
        _reject()
    if (
        type(context.igreja_id) is not uuid.UUID
        or context.igreja_id.int == 0
        or type(context.conversation_id) is not uuid.UUID
        or context.conversation_id.int == 0
        or type(context.inbound_message_id) is not uuid.UUID
        or context.inbound_message_id.int == 0
        or type(context.pessoa_id) is not uuid.UUID
        or context.pessoa_id.int == 0
        or type(context.app_user_id) is not uuid.UUID
        or context.app_user_id.int == 0
    ):
        _reject()
    return context


def _canonical_payload_sha256(payload: object) -> str:
    if type(payload) is not dict:
        _reject()
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        _reject()
    return hashlib.sha256(encoded).hexdigest()


def _is_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _rehydrate_verified_draft_candidate(draft: object) -> CellReportCandidate:
    """Fail closed if persisted aggregate JSON no longer matches its digest."""

    try:
        candidate = rehydrate_v1a_draft_candidate(getattr(draft, "candidate_json", None))
        payload = canonical_v1a_draft_payload(candidate)
    except (CellReportWhatsappError, TypeError, ValueError):
        raise CellReportWhatsappError("rascunho de relatório inválido") from None
    if _canonical_payload_sha256(payload) != getattr(draft, "candidate_sha256", None):
        raise CellReportWhatsappError("rascunho de relatório inválido")
    return candidate


def _expected_summary_sha256(candidate: CellReportCandidate, meeting: _Meeting) -> str:
    summary = render_v1a_cell_report_summary(
        candidate,
        cell_name=meeting.cell_name,
        meeting_date=meeting.date,
    )
    return hashlib.sha256(summary.encode("utf-8")).hexdigest()


def _proposal_summary_matches_candidate(
    proposal: AgentActionProposal,
    candidate: CellReportCandidate,
    meeting: _Meeting,
) -> bool:
    return _is_digest(getattr(proposal, "summary_sha256", None)) and (
        _expected_summary_sha256(candidate, meeting) == proposal.summary_sha256
    )


def _render_v1a_cell_report_receipt(meeting: _Meeting) -> str:
    """Render the bounded, server-owned V1a receipt detail."""

    if (
        type(meeting) is not _Meeting
        or type(meeting.cell_name) is not str
        or not meeting.cell_name.strip()
        or meeting.cell_name != meeting.cell_name.strip()
        or "\n" in meeting.cell_name
        or "\r" in meeting.cell_name
        or len(meeting.cell_name.encode("utf-8", "strict")) > 120
        or type(meeting.date) is not dt.date
        or type(meeting.date) is dt.datetime
    ):
        _reject()
    return (
        f"Relatório confirmado. Célula {meeting.cell_name}, reunião de "
        f"{meeting.date:%d/%m/%Y}."
    )


def v1a_receipt_text_after_execution(
    session: Session,
    *,
    context: PrivilegeContext,
    proposal_id: uuid.UUID,
) -> str | None:
    """Load one detailed V1a receipt from the already-finalized server state.

    ``AgentActionReceipt`` remains the closed generic S3 ledger.  The detailed
    text is only for the outbound Message created in the same transaction, so
    the message itself becomes the immutable post-commit receipt.
    """

    context = _require_context(context)
    if type(proposal_id) is not uuid.UUID or proposal_id.int == 0:
        _reject()
    require_tenant_scope(
        session,
        expected_igreja_id=context.igreja_id,
        source="cell_report_v1a_receipt",
    )
    proposal = session.execute(
        select(AgentActionProposal).where(
            AgentActionProposal.igreja_id == context.igreja_id,
            AgentActionProposal.id == proposal_id,
            AgentActionProposal.conversation_id == context.conversation_id,
            AgentActionProposal.action == _REPORT_ACTION.value,
            AgentActionProposal.state == "executada",
            AgentActionProposal.confirmation_message_id == context.inbound_message_id,
        )
    ).scalar_one_or_none()
    if proposal is None:
        return None
    try:
        reference = _draft_reference_from_arguments(
            proposal.arguments_json,
            target_id=proposal.target_id,
        )
    except ProposalExecutionDenied:
        return None
    row = session.execute(
        select(CelulaReuniao.data, Celula.nome)
        .join(
            Celula,
            (Celula.igreja_id == CelulaReuniao.igreja_id)
            & (Celula.id == CelulaReuniao.celula_id),
        )
        .where(
            CelulaReuniao.igreja_id == context.igreja_id,
            CelulaReuniao.id == reference.meeting_id,
            CelulaReuniao.relatorio_status == "enviado",
            Celula.igreja_id == context.igreja_id,
        )
    ).one_or_none()
    if row is None:
        return None
    meeting_date, cell_name = row
    try:
        return _render_v1a_cell_report_receipt(
            _Meeting(reference.meeting_id, cell_name, meeting_date)
        )
    except CellReportV1aServiceError:
        return None


def _looks_like_report(text: object) -> bool:
    if type(text) is not str:
        return False
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", text).casefold()
        if not unicodedata.combining(character)
    )
    return any(
        token in normalized
        for token in ("presente", "visitante", "decisao", "oferta", "relatorio")
    )


def _lock_conversation_and_inbound(
    session: Session,
    *,
    context: PrivilegeContext,
    inbound_message_id: uuid.UUID,
) -> bool:
    conversation = session.execute(
        select(Conversation)
        .where(
            Conversation.igreja_id == context.igreja_id,
            Conversation.id == context.conversation_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if (
        conversation is None
        or getattr(conversation, "estado", None) == "humano"
        or getattr(conversation, "assumido_por", None) is not None
    ):
        return False
    inbound = session.execute(
        select(Message)
        .where(
            Message.igreja_id == context.igreja_id,
            Message.conversation_id == context.conversation_id,
            Message.id == inbound_message_id,
            Message.direcao == "in",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    return inbound is not None


def _current_lgpd_acceptance(
    session: Session,
    *,
    context: PrivilegeContext,
    now: dt.datetime,
) -> str | None:
    settings = whatsapp_privilege.get_settings()
    current_term = getattr(settings, "agent_term_version", None)
    rows = session.execute(
        select(ConsentRecord)
        .where(
            ConsentRecord.igreja_id == context.igreja_id,
            ConsentRecord.pessoa_id == context.pessoa_id,
        )
        .with_for_update()
    ).scalars().all()
    records = tuple(
        LgpdConsentRecord(
            getattr(row, "termo_versao", None),
            getattr(row, "aceite_em", None),
            getattr(row, "id", None),
        )
        for row in rows
    )
    return current_v1a_lgpd_acceptance(
        records,
        current_term=current_term,
        now=now,
    )


def _active_draft_hint(
    session: Session,
    *,
    context: PrivilegeContext,
) -> _DraftReference | None:
    """Read only the active draft identity before taking the meeting lock.

    A turn already owns its conversation.  The identity is deliberately read
    without a row lock so all V1a paths can take Meeting/Cell before Draft.
    The locked load below revalidates every value before it is used.
    """

    rows = session.execute(
        select(CellReportDraft.id, CellReportDraft.reuniao_id)
        .where(
            CellReportDraft.igreja_id == context.igreja_id,
            CellReportDraft.conversation_id == context.conversation_id,
            CellReportDraft.state.in_(tuple(_DRAFT_ACTIVE)),
        )
    ).all()
    if len(rows) > 1:
        _reject()
    if not rows:
        return None
    draft_id, meeting_id = rows[0]
    if (
        type(draft_id) is not uuid.UUID
        or draft_id.int == 0
        or type(meeting_id) is not uuid.UUID
        or meeting_id.int == 0
    ):
        _reject()
    return _DraftReference(id=draft_id, meeting_id=meeting_id)


def _lock_active_draft_after_meeting(
    session: Session,
    *,
    context: PrivilegeContext,
    reference: _DraftReference | None,
    meeting_id: uuid.UUID,
) -> CellReportDraft | None:
    """Lock and revalidate the active draft after Meeting/Cell.

    The conversation lock serializes normal turns.  This second check still
    fails closed if an external writer changed the active draft between the
    read-only identity lookup and the Meeting/Cell lock.
    """

    rows = session.execute(
        select(CellReportDraft)
        .where(
            CellReportDraft.igreja_id == context.igreja_id,
            CellReportDraft.conversation_id == context.conversation_id,
            CellReportDraft.state.in_(tuple(_DRAFT_ACTIVE)),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalars().all()
    if len(rows) > 1:
        _reject()
    draft = rows[0] if rows else None
    if reference is None:
        if draft is not None:
            _reject()
        return None
    if (
        draft is None
        or draft.id != reference.id
        or draft.reuniao_id != reference.meeting_id
        or draft.reuniao_id != meeting_id
    ):
        _reject()
    return draft


def _eligible_meeting(
    session: Session,
    *,
    context: PrivilegeContext,
    now: dt.datetime,
    meeting_id: uuid.UUID | None = None,
    lock: bool = True,
    skip_locked: bool = False,
) -> _Meeting | None:
    if meeting_id is not None:
        requested_ids = (meeting_id,)
    else:
        requested_ids = tuple(context.owned_cell_ids)
    if not requested_ids or any(type(value) is not uuid.UUID for value in requested_ids):
        return None
    statement = (
        select(CelulaReuniao, Celula)
        .join(
            Celula,
            (Celula.igreja_id == CelulaReuniao.igreja_id)
            & (Celula.id == CelulaReuniao.celula_id),
        )
        .where(
            CelulaReuniao.igreja_id == context.igreja_id,
            Celula.igreja_id == context.igreja_id,
            Celula.ativo.is_(True),
            Celula.lider_id == context.pessoa_id,
            CelulaReuniao.relatorio_status == "pendente",
            CelulaReuniao.status != "cancelada",
        )
    )
    if lock:
        statement = statement.with_for_update(
            skip_locked=skip_locked,
        ).execution_options(populate_existing=True)
    if meeting_id is not None:
        statement = statement.where(CelulaReuniao.id == requested_ids[0])
    else:
        statement = statement.where(Celula.id.in_(requested_ids))
    candidates: list[_Meeting] = []
    for meeting, cell in session.execute(statement).all():
        data = getattr(meeting, "data", None)
        if type(data) is not dt.date or not meeting_has_passed(
            data=data,
            hora=getattr(meeting, "hora", None),
            now=now,
        ):
            continue
        cell_name = getattr(cell, "nome", None)
        if (
            type(getattr(meeting, "id", None)) is not uuid.UUID
            or type(cell_name) is not str
            or not cell_name.strip()
            or len(cell_name.encode("utf-8", "strict")) > 120
        ):
            return None
        candidates.append(_Meeting(meeting.id, cell_name, data))
        if len(candidates) > 1:
            return None
    return candidates[0] if len(candidates) == 1 else None


def _expire_draft(draft: CellReportDraft, *, now: dt.datetime) -> None:
    draft.state = _DRAFT_EXPIRED
    draft.candidate_json = None
    draft.candidate_sha256 = None
    draft.updated_at = now
    draft.terminal_at = now
    draft.content_purged_at = now


def _clarify_v1a_response(instruction: str) -> str:
    return instruction + _V1A_CLARIFY_FORMAT


def _missing_response(candidate: CellReportCandidate) -> str:
    labels = {
        "presentes": "presentes",
        "visitantes": "visitantes",
        "decisoes": "decisões",
        "oferta": "oferta total",
    }
    missing = [labels[field] for field in candidate.missing_required_fields]
    if not missing:
        _reject()
    return _clarify_v1a_response(
        "Para preparar o relatório, informe também: " + ", ".join(missing) + "."
    )


def _stage_from_draft_candidate(
    session: Session,
    *,
    context: PrivilegeContext,
    inbound_message_id: uuid.UUID,
    summary_message: Message,
    active: CellReportDraft,
    candidate: CellReportCandidate,
    meeting: _Meeting,
    now: dt.datetime,
) -> CellReportTurnStage:
    """Persist the deterministic part after a locked draft becomes usable."""

    session.flush()
    draft_id = getattr(active, "id", None)
    if type(draft_id) is not uuid.UUID or draft_id.int == 0:
        _reject()
    if not candidate.is_complete:
        return CellReportTurnStage(
            CellReportStageKind.CLARIFY,
            _missing_response(candidate),
            draft_id=draft_id,
            draft_revision=active.revision,
        )
    summary = render_v1a_cell_report_summary(
        candidate,
        cell_name=meeting.cell_name,
        meeting_date=meeting.date,
    )
    summary_message.texto = summary
    try:
        proposal = prepare_action_proposal(
            session,
            context=context,
            inbound_message_id=inbound_message_id,
            action=_REPORT_ACTION,
            target=ProposalTarget(kind="reuniao", id=meeting.id),
            arguments={
                "reuniao_id": str(meeting.id),
                "rascunho_id": str(draft_id),
                "revisao": active.revision,
            },
            summary=summary,
            summary_message_id=summary_message.id,
            now=now,
        )
    except ProposalContractError:
        return CellReportTurnStage(CellReportStageKind.HUMAN_REQUIRED, None)
    return CellReportTurnStage(
        CellReportStageKind.SUMMARY,
        summary,
        proposal=proposal,
        draft_id=draft_id,
        draft_revision=active.revision,
    )


def stage_v1a_cell_report_turn(
    session: Session,
    *,
    context: PrivilegeContext,
    inbound_message_id: uuid.UUID,
    text: object,
    summary_message: Message,
    now: dt.datetime | None = None,
) -> CellReportTurnStage:
    """Collect one aggregate revision and, when complete, prepare S3 summary.

    The caller must have reserved and locked ``summary_message``.  This helper
    returns ``NOT_APPLICABLE`` for ordinary messages, so the existing S3 router
    can retain its behavior.  It never starts a transaction or sends a reply.
    """

    context = _require_context(context)
    if type(inbound_message_id) is not uuid.UUID or inbound_message_id.int == 0:
        _reject()
    current_now = _now(session, now)
    require_tenant_scope(
        session, expected_igreja_id=context.igreja_id, source="cell_report_v1a"
    )
    if not _lock_conversation_and_inbound(
        session, context=context, inbound_message_id=inbound_message_id
    ):
        return CellReportTurnStage(CellReportStageKind.HUMAN_REQUIRED, None)
    if _current_lgpd_acceptance(session, context=context, now=current_now) is None:
        return CellReportTurnStage(CellReportStageKind.NOT_APPLICABLE, None)
    active_hint = _active_draft_hint(session, context=context)
    try:
        patch = parse_v1a_cell_report_text(text)
    except CellReportV1aError:
        # A parser error can carry an observation or another non-V1a field.
        # Do not reconstruct a report from a partial projection in that case.
        if _looks_like_report(text):
            return CellReportTurnStage(
                CellReportStageKind.CLARIFY,
                _clarify_v1a_response(
                    "Envie apenas presentes, visitantes, decisões e oferta total."
                ),
            )
        return CellReportTurnStage(CellReportStageKind.NOT_APPLICABLE, None)
    try:
        projected = v1a_whitelisted_extraction_projection(text)
    except CellReportWhatsappError:
        projected = {}
    # The deterministic parser owns ordinary numeric values.  The paid path is
    # only for a retained label whose value still has words, never merely for a
    # partial report.  That keeps conventional collection at zero LLM calls.
    # Numeric labels are already deterministic draft data.  Only labels still
    # written in words reach the paid extractor, so provider output can never
    # rewrite an adjacent parsed value from the same inbound.
    word_projection = {
        field: value
        for field, value in projected.items()
        if not value.isdigit() and getattr(patch, field) is None
    }
    extraction_projection = (
        word_projection if word_projection and not patch.is_complete else None
    )
    if (
        patch is not None
        and patch.is_empty
        and extraction_projection is None
    ):
        # An unfinished draft never turns an unrelated inbound into a report
        # revision.  In particular, public church questions must continue to
        # the normal router without locking, extending or replacing the draft.
        return CellReportTurnStage(CellReportStageKind.NOT_APPLICABLE, None)
    meeting = _eligible_meeting(
        session,
        context=context,
        now=current_now,
        meeting_id=(active_hint.meeting_id if active_hint is not None else None),
    )
    if meeting is None:
        return CellReportTurnStage(CellReportStageKind.HUMAN_REQUIRED, None)
    active = _lock_active_draft_after_meeting(
        session,
        context=context,
        reference=active_hint,
        meeting_id=meeting.id,
    )
    if active is not None and getattr(active, "expires_at", current_now) <= current_now:
        _expire_draft(active, now=current_now)
        session.flush()
        active = None
    if extraction_projection is not None:
        try:
            if active is None:
                candidate = patch if patch is not None else build_cell_report_candidate()
                payload = canonical_v1a_draft_payload(candidate)
                active = CellReportDraft(
                    igreja_id=context.igreja_id,
                    conversation_id=context.conversation_id,
                    reuniao_id=meeting.id,
                    actor_pessoa_id=context.pessoa_id,
                    source_message_id=inbound_message_id,
                    state=_DRAFT_COLLECTING,
                    revision=1,
                    candidate_json=payload,
                    candidate_sha256=_canonical_payload_sha256(payload),
                    started_at=current_now,
                    expires_at=current_now + _DRAFT_TTL,
                    updated_at=current_now,
                    terminal_at=None,
                    content_purged_at=None,
                )
                session.add(active)
            else:
                current = _rehydrate_verified_draft_candidate(active)
                candidate = (
                    merge_v1a_cell_report_text(current, text)
                    if patch is not None and not patch.is_empty
                    else current
                )
                payload = canonical_v1a_draft_payload(candidate)
                digest = _canonical_payload_sha256(payload)
                if digest != active.candidate_sha256:
                    active.revision += 1
                    active.candidate_json = payload
                    active.candidate_sha256 = digest
                active.state = _DRAFT_COLLECTING
                active.updated_at = current_now
        except CellReportWhatsappError:
            if active is not None:
                active.state = _DRAFT_CANCELLED
                active.updated_at = current_now
                active.terminal_at = current_now
                active.candidate_json = None
                active.candidate_sha256 = None
                active.content_purged_at = current_now
                return CellReportTurnStage(
                    CellReportStageKind.HUMAN_REQUIRED,
                    None,
                    persist_before_handoff=True,
                )
            return CellReportTurnStage(CellReportStageKind.HUMAN_REQUIRED, None)
        except (CellReportV1aError, ValueError):
            return CellReportTurnStage(
                CellReportStageKind.CLARIFY,
                _clarify_v1a_response(
                    "Envie apenas a correção de presentes, visitantes, decisões ou oferta total."
                ),
            )
        session.flush()
        draft_id = getattr(active, "id", None)
        if type(draft_id) is not uuid.UUID or draft_id.int == 0:
            _reject()
        return CellReportTurnStage(
            CellReportStageKind.EXTRACTION,
            None,
            draft_id=draft_id,
            draft_revision=active.revision,
            extraction_projection=extraction_projection,
        )
    assert patch is not None
    if active is None:
        candidate = patch
        payload = canonical_v1a_draft_payload(candidate)
        active = CellReportDraft(
            igreja_id=context.igreja_id,
            conversation_id=context.conversation_id,
            reuniao_id=meeting.id,
            actor_pessoa_id=context.pessoa_id,
            source_message_id=inbound_message_id,
            state=_DRAFT_READY if candidate.is_complete else _DRAFT_COLLECTING,
            revision=1,
            candidate_json=payload,
            candidate_sha256=_canonical_payload_sha256(payload),
            started_at=current_now,
            expires_at=current_now + _DRAFT_TTL,
            updated_at=current_now,
            terminal_at=None,
            content_purged_at=None,
        )
        session.add(active)
    else:
        try:
            current = _rehydrate_verified_draft_candidate(active)
            candidate = merge_v1a_cell_report_text(current, text)
        except CellReportWhatsappError:
            active.state = _DRAFT_CANCELLED
            active.updated_at = current_now
            active.terminal_at = current_now
            active.candidate_json = None
            active.candidate_sha256 = None
            active.content_purged_at = current_now
            return CellReportTurnStage(
                CellReportStageKind.HUMAN_REQUIRED,
                None,
                persist_before_handoff=True,
            )
        except (CellReportV1aError, ValueError):
            return CellReportTurnStage(
                CellReportStageKind.CLARIFY,
                _clarify_v1a_response(
                    "Envie apenas a correção de presentes, visitantes, decisões ou oferta total."
                ),
            )
        payload = canonical_v1a_draft_payload(candidate)
        digest = _canonical_payload_sha256(payload)
        if digest != active.candidate_sha256:
            active.revision += 1
            active.candidate_json = payload
            active.candidate_sha256 = digest
            active.updated_at = current_now
        active.state = _DRAFT_READY if candidate.is_complete else _DRAFT_COLLECTING
    return _stage_from_draft_candidate(
        session,
        context=context,
        inbound_message_id=inbound_message_id,
        summary_message=summary_message,
        active=active,
        candidate=candidate,
        meeting=meeting,
        now=current_now,
    )


def complete_v1a_extraction_after_provider(
    session: Session,
    *,
    context: PrivilegeContext,
    inbound_message_id: uuid.UUID,
    summary_message: Message,
    draft_id: uuid.UUID,
    expected_revision: int,
    projection: object,
    extracted_payload: object,
    reservation_id: uuid.UUID,
    actual_microusd: int,
    now: dt.datetime | None = None,
) -> CellReportTurnStage:
    """Apply one billed, closed extraction after the provider session ended.

    The caller must have committed the reservation before HTTP.  This second
    short transaction rechecks the anchored inbound, consent, Meeting/Cell,
    draft identity and revision before it persists any response.  A mismatch
    deliberately leaves the reservation conservative and produces no summary.
    """

    context = _require_context(context)
    if (
        type(inbound_message_id) is not uuid.UUID
        or inbound_message_id.int == 0
        or type(draft_id) is not uuid.UUID
        or draft_id.int == 0
        or type(expected_revision) is not int
        or expected_revision < 1
        or type(reservation_id) is not uuid.UUID
        or reservation_id.int == 0
        or type(actual_microusd) is not int
        or actual_microusd < 0
        or getattr(summary_message, "id", None) is None
    ):
        _reject()
    current_now = _now(session, now)
    require_tenant_scope(
        session, expected_igreja_id=context.igreja_id, source="cell_report_v1a_extract"
    )
    if not _lock_conversation_and_inbound(
        session, context=context, inbound_message_id=inbound_message_id
    ):
        return CellReportTurnStage(CellReportStageKind.HUMAN_REQUIRED, None)
    if _current_lgpd_acceptance(session, context=context, now=current_now) is None:
        return CellReportTurnStage(CellReportStageKind.HUMAN_REQUIRED, None)
    reference = _active_draft_hint(session, context=context)
    if reference is None or reference.id != draft_id:
        return CellReportTurnStage(CellReportStageKind.HUMAN_REQUIRED, None)
    meeting = _eligible_meeting(
        session,
        context=context,
        now=current_now,
        meeting_id=reference.meeting_id,
    )
    if meeting is None:
        return CellReportTurnStage(CellReportStageKind.HUMAN_REQUIRED, None)
    active = _lock_active_draft_after_meeting(
        session,
        context=context,
        reference=reference,
        meeting_id=meeting.id,
    )
    if (
        active is None
        or active.revision != expected_revision
        or active.expires_at <= current_now
    ):
        if active is not None and active.state in _DRAFT_ACTIVE:
            _expire_draft(active, now=current_now)
            return CellReportTurnStage(
                CellReportStageKind.HUMAN_REQUIRED,
                None,
                persist_before_handoff=True,
            )
        return CellReportTurnStage(CellReportStageKind.HUMAN_REQUIRED, None)
    try:
        current = _rehydrate_verified_draft_candidate(active)
        candidate = complete_v1a_candidate_from_projection(
            current,
            projection=projection,
            extracted=extracted_payload,
            allow_explicit_corrections=True,
        )
        settle_v1a_extraction_budget(
            session,
            igreja_id=context.igreja_id,
            reservation_id=reservation_id,
            actual_microusd=actual_microusd,
            now=current_now,
        )
    except CellReportWhatsappError:
        return CellReportTurnStage(CellReportStageKind.HUMAN_REQUIRED, None)
    payload = canonical_v1a_draft_payload(candidate)
    digest = _canonical_payload_sha256(payload)
    if digest != active.candidate_sha256:
        active.revision += 1
        active.candidate_json = payload
        active.candidate_sha256 = digest
        active.updated_at = current_now
    active.state = _DRAFT_READY if candidate.is_complete else _DRAFT_COLLECTING
    return _stage_from_draft_candidate(
        session,
        context=context,
        inbound_message_id=inbound_message_id,
        summary_message=summary_message,
        active=active,
        candidate=candidate,
        meeting=meeting,
        now=current_now,
    )


def _draft_reference_from_arguments(
    arguments: object,
    *,
    target_id: object,
) -> _DraftReference:
    if type(arguments) is not dict or type(target_id) is not uuid.UUID:
        raise ProposalExecutionDenied("domain_denied")
    try:
        draft_id = uuid.UUID(arguments["rascunho_id"])
        meeting_id = uuid.UUID(arguments["reuniao_id"])
        revision = arguments["revisao"]
    except (KeyError, TypeError, ValueError):
        raise ProposalExecutionDenied("domain_denied") from None
    if (
        draft_id.int == 0
        or meeting_id.int == 0
        or meeting_id != target_id
        or type(revision) is not int
        or revision < 1
    ):
        raise ProposalExecutionDenied("domain_denied")
    return _DraftReference(id=draft_id, meeting_id=meeting_id, revision=revision)


def _load_v1a_draft_for_execution(
    session: Session,
    *,
    execution: ExecutionContext,
    reference: _DraftReference,
    now: dt.datetime,
) -> tuple[CellReportDraft, CellReportCandidate]:
    if execution.action is not _REPORT_ACTION or execution.target.kind != "reuniao":
        raise ProposalExecutionDenied("domain_denied")
    if reference.revision is None:
        raise ProposalExecutionDenied("domain_denied")
    draft = session.execute(
        select(CellReportDraft)
        .where(
            CellReportDraft.igreja_id == execution.igreja_id,
            CellReportDraft.id == reference.id,
            CellReportDraft.conversation_id == execution.conversation_id,
            CellReportDraft.reuniao_id == reference.meeting_id,
            CellReportDraft.actor_pessoa_id == execution.privilege_context.pessoa_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if (
        draft is None
        or draft.state != _DRAFT_READY
        or draft.revision != reference.revision
        or draft.expires_at <= now
        or not _is_digest(draft.candidate_sha256)
    ):
        if draft is not None and draft.state in _DRAFT_ACTIVE:
            _expire_draft(draft, now=now)
        raise ProposalExecutionDenied("domain_denied")
    try:
        candidate = _rehydrate_verified_draft_candidate(draft)
    except CellReportWhatsappError:
        draft.state = _DRAFT_CANCELLED
        draft.updated_at = now
        draft.terminal_at = now
        draft.candidate_json = None
        draft.candidate_sha256 = None
        draft.content_purged_at = now
        raise ProposalExecutionDenied("domain_denied") from None
    if not candidate.is_complete:
        raise ProposalExecutionDenied("domain_denied")
    return draft, candidate


def _execution_proposal_matches_candidate(
    session: Session,
    *,
    execution: ExecutionContext,
    candidate: CellReportCandidate,
    meeting: _Meeting,
) -> bool:
    proposal = session.execute(
        select(AgentActionProposal)
        .where(
            AgentActionProposal.igreja_id == execution.igreja_id,
            AgentActionProposal.id == execution.proposal_id,
            AgentActionProposal.conversation_id == execution.conversation_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    return proposal is not None and _proposal_summary_matches_candidate(
        proposal, candidate, meeting
    )


def execute_v1a_cell_report_proposal(
    session: Session,
    execution: ExecutionContext,
    *,
    now: dt.datetime | None = None,
) -> ActionEffect:
    """Execute the V1a S3 proposal beside its receipt transaction.

    The generic S3 resolver has already locked the conversation and checked
    the confirmation delivery/order.  We recheck exact LGPD state, draft,
    meeting and leader before the shared finalizer changes the official report.
    """

    if type(execution) is not ExecutionContext:
        raise ProposalExecutionDenied("domain_denied")
    current_now = _now(session, now)
    context = _require_context(execution.privilege_context)
    if (
        not cell_report_enabled_from_environment(execution.igreja_id)
        or
        context.igreja_id != execution.igreja_id
        or context.conversation_id != execution.conversation_id
        or _current_lgpd_acceptance(session, context=context, now=current_now) is None
    ):
        raise ProposalExecutionDenied("domain_denied")
    reference = _draft_reference_from_arguments(
        execution.arguments,
        target_id=execution.target.id,
    )
    meeting = _eligible_meeting(
        session,
        context=context,
        now=current_now,
        meeting_id=reference.meeting_id,
    )
    if meeting is None:
        raise ProposalExecutionDenied("domain_denied")
    draft, candidate = _load_v1a_draft_for_execution(
        session,
        execution=execution,
        reference=reference,
        now=current_now,
    )
    if not _execution_proposal_matches_candidate(
        session,
        execution=execution,
        candidate=candidate,
        meeting=meeting,
    ):
        raise ProposalExecutionDenied("domain_denied")
    try:
        finalize_v1a_cell_report(
            session,
            igreja_id=execution.igreja_id,
            reuniao_id=execution.target.id,
            actor_pessoa_id=context.pessoa_id,
            candidate=candidate,
            proposal_id=execution.proposal_id,
            draft_payload_sha256=draft.candidate_sha256,
            now=current_now,
        )
    except CellReportFinalizerError:
        raise ProposalExecutionDenied("domain_denied") from None
    draft.state = _DRAFT_COMPLETED
    draft.updated_at = current_now
    draft.terminal_at = current_now
    draft.content_purged_at = current_now
    draft.candidate_json = None
    draft.candidate_sha256 = None
    return ActionEffect(
        receipt_text="Relatório confirmado.",
        opaque_effect_id=execution.proposal_id,
    )


def v1a_summary_still_authorized(
    session: Session,
    *,
    proposal: AgentActionProposal,
    context: PrivilegeContext,
    summary_message: Message,
    now: dt.datetime | None = None,
) -> bool:
    """Recheck a V1a summary before every transport attempt.

    A retry cannot send a stale summary after term, leader, cell, meeting or
    draft revision changed.  It performs no terminal transition itself; the
    standard undelivered-proposal callback owns that state change.
    """

    try:
        current_now = _now(session, now)
        context = _require_context(context)
        if (
            not cell_report_enabled_from_environment(context.igreja_id)
            or
            proposal.action != _REPORT_ACTION.value
            or proposal.igreja_id != context.igreja_id
            or proposal.conversation_id != context.conversation_id
            or proposal.actor_pessoa_id != context.pessoa_id
            or proposal.scope_fingerprint != context.scope_fingerprint
            or proposal.summary_message_id != summary_message.id
            or proposal.source_message_id != context.inbound_message_id
            or proposal.state not in {"preparada", "pendente"}
            or not _is_digest(proposal.arguments_sha256)
            or canonical_arguments_sha256(proposal.arguments_json)
            != proposal.arguments_sha256
            or hashlib.sha256((summary_message.texto or "").encode("utf-8")).hexdigest()
            != proposal.summary_sha256
            or _current_lgpd_acceptance(session, context=context, now=current_now)
            is None
        ):
            return False
        reference = _draft_reference_from_arguments(
            proposal.arguments_json,
            target_id=proposal.target_id,
        )
        meeting = _eligible_meeting(
            session,
            context=context,
            now=current_now,
            meeting_id=reference.meeting_id,
        )
        if meeting is None or reference.revision is None:
            return False
        draft = session.execute(
            select(CellReportDraft)
            .where(
                CellReportDraft.igreja_id == context.igreja_id,
                CellReportDraft.id == reference.id,
                CellReportDraft.conversation_id == context.conversation_id,
                CellReportDraft.reuniao_id == reference.meeting_id,
                CellReportDraft.actor_pessoa_id == context.pessoa_id,
                CellReportDraft.state == _DRAFT_READY,
                CellReportDraft.revision == reference.revision,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if (
            draft is None
            or draft.expires_at <= current_now
            or not _is_digest(draft.candidate_sha256)
            or _rehydrate_verified_draft_candidate(draft).is_complete is not True
        ):
            return False
        return _proposal_summary_matches_candidate(
            proposal, _rehydrate_verified_draft_candidate(draft), meeting
        )
    except (CellReportV1aServiceError, KeyError, TypeError, ValueError):
        return False


__all__ = [
    "CellReportStageKind",
    "CellReportTurnStage",
    "CellReportV1aServiceError",
    "complete_v1a_extraction_after_provider",
    "execute_v1a_cell_report_proposal",
    "stage_v1a_cell_report_turn",
    "v1a_receipt_text_after_execution",
    "v1a_summary_still_authorized",
]
