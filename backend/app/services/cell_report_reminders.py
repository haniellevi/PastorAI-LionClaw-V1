"""Durable V1a reminder outbox with bounded, fail-closed delivery.

This is deliberately separate from inbound messages. It records a single
reminder intention per meeting and leader, commits every claim before any
provider boundary, and retries only outcomes proven to be before-send.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, null, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    AgentConfig,
    AgentActionProposal,
    Celula,
    CelulaReuniao,
    CellReportDraft,
    CellReportReminder,
    CellReportReminderPreference,
    ConsentRecord,
    Conversation,
    Igreja,
    LlmCredential,
    Message,
    Pessoa,
    WhatsappConnection,
)
from app.domain.agent_reply import (
    AGENT_REPLY_AMBIGUOUS,
    AGENT_REPLY_CONFIRMED,
    AGENT_REPLY_EXECUTION_AMBIGUOUS,
    AGENT_REPLY_IN_FLIGHT,
    AGENT_REPLY_NO_RESPONSE,
    AGENT_REPLY_PENDING,
    AGENT_REPLY_RESERVED,
    AGENT_REPLY_EXECUTING,
    AGENT_REPLY_SUPPRESSED,
)
from app.db.rls_observability import require_tenant_scope
from app.db.tenant_session import mark_cross_tenant, mark_tenant_scoped
from app.deps import BLOCKING_IGREJA_STATUSES
from app.domain.cell_meetings_schedule import SAO_PAULO_TZ, meeting_has_passed
from app.domain.phone import normalize_phone, phone_suffix
from app.services.cell_report_application import (
    CellReportApplicationError,
    revalidate_cell_report_leader,
)
from app.services.cell_report_whatsapp import (
    LgpdConsentRecord,
    cell_report_enabled_from_environment,
    current_v1a_lgpd_acceptance,
)
from app.services.evolution import BroadcastSendResult, EvolutionClient
from app.services.outbound_guard import external_sends_allowed


logger = logging.getLogger("pastorai.cell_report_reminders")

_UTC = dt.timezone.utc
_TIME = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
_OPEN = dt.time(8, 0)
_CLOSE = dt.time(21, 0)
_RETRY_DELAYS = (dt.timedelta(minutes=1), dt.timedelta(minutes=5))
_DRAFT_ACTIVE = frozenset({"coletando", "pronto"})
_V1A_REPORT_ACTION = "enviar_relatorio_celula"
_PROPOSAL_ACTIVE = frozenset({"preparada", "pendente"})
_SUMMARY_SAFE_TO_ERASE = frozenset(
    {
        AGENT_REPLY_RESERVED,
        AGENT_REPLY_EXECUTING,
        AGENT_REPLY_PENDING,
        AGENT_REPLY_NO_RESPONSE,
        AGENT_REPLY_SUPPRESSED,
    }
)
_SUMMARY_RECONCILIATION_REQUIRED = frozenset(
    {
        AGENT_REPLY_IN_FLIGHT,
        AGENT_REPLY_AMBIGUOUS,
        AGENT_REPLY_EXECUTION_AMBIGUOUS,
    }
)

# Generic fixed text only. It contains no name, address, telephone, roster,
# meeting identifier, or report content. The row retains only its digest.
_REMINDER_TEXT = (
    "Lembrete: envie o relatório da reunião da célula com presentes, visitantes, "
    "decisões e oferta total. Para parar estes lembretes, envie PARAR LEMBRETES."
)


class CellReportReminderError(ValueError):
    """A malformed reminder input or durable state was rejected."""


@dataclass(frozen=True, slots=True)
class ReminderClaim:
    igreja_id: uuid.UUID
    reminder_id: uuid.UUID
    reuniao_id: uuid.UUID
    leader_pessoa_id: uuid.UUID
    claim_token: uuid.UUID
    instance: str
    phone: str
    text: str


@dataclass(frozen=True, slots=True)
class ReminderResultTransition:
    state: str
    attempts: int
    due_at: dt.datetime | None
    terminal_reason: str | None


def _as_utc(value: object) -> dt.datetime | None:
    if type(value) is not dt.datetime or value.tzinfo is None:
        return None
    try:
        return value.astimezone(_UTC)
    except (OverflowError, ValueError):
        return None


def _now(value: dt.datetime | None = None) -> dt.datetime:
    normalized = _as_utc(value) if value is not None else dt.datetime.now(_UTC)
    if normalized is None:
        raise CellReportReminderError("horário do lembrete inválido")
    return normalized


def _meeting_start(data: object, hora: object) -> dt.datetime | None:
    if type(data) is not dt.date or type(hora) is not str or not _TIME.fullmatch(hora):
        return None
    hour, minute = (int(piece) for piece in hora.split(":", 1))
    return dt.datetime.combine(data, dt.time(hour, minute), tzinfo=SAO_PAULO_TZ)


def cell_report_reminder_due_at(data: object, hora: object) -> dt.datetime | None:
    """Return the first allowed São Paulo reminder instant, as UTC."""

    start = _meeting_start(data, hora)
    if start is None:
        return None
    local_due = start + dt.timedelta(hours=2)
    if local_due.time() < _OPEN:
        local_due = local_due.replace(hour=8, minute=0, second=0, microsecond=0)
    elif local_due.time() > _CLOSE:
        local_due = (local_due + dt.timedelta(days=1)).replace(
            hour=8,
            minute=0,
            second=0,
            microsecond=0,
        )
    return local_due.astimezone(_UTC)


def cell_report_reminder_is_obsolete(
    data: object,
    hora: object,
    now: object,
) -> bool:
    """Return true only after the reviewed 24-hour recovery window closes."""

    start = _meeting_start(data, hora)
    current = _as_utc(now)
    if start is None or current is None:
        return True
    return current > start.astimezone(_UTC) + dt.timedelta(hours=24)


def cell_report_reminder_transport_window_open(now: object) -> bool:
    """Whether a provider call may start at this São Paulo local time."""

    current = _as_utc(now)
    if current is None:
        return False
    local_time = current.astimezone(SAO_PAULO_TZ).timetz().replace(tzinfo=None)
    return _OPEN <= local_time <= _CLOSE


def _next_transport_window(now: dt.datetime) -> dt.datetime:
    local = now.astimezone(SAO_PAULO_TZ)
    local_time = local.timetz().replace(tzinfo=None)
    if local_time < _OPEN:
        return local.replace(hour=8, minute=0, second=0, microsecond=0).astimezone(_UTC)
    if local_time > _CLOSE:
        return (local + dt.timedelta(days=1)).replace(
            hour=8, minute=0, second=0, microsecond=0
        ).astimezone(_UTC)
    return now


def cell_report_reminder_text() -> str:
    """Return the fixed, PII-free reminder body at the provider boundary."""

    return _REMINDER_TEXT


def cell_report_reminder_text_sha256() -> str:
    return hashlib.sha256(_REMINDER_TEXT.encode("utf-8")).hexdigest()


def reminder_result_transition(
    result: object,
    *,
    attempts: object,
    now: object,
) -> ReminderResultTransition:
    """Map one classified transport result without retrying ambiguity.

    ``attempts`` is a retry index: initial attempt is zero and the two allowed
    pre-send retries are one and two. Unknown or malformed results become a
    terminal ambiguous state.
    """

    current = _as_utc(now)
    if current is None or type(attempts) is not int or attempts < 0 or attempts > 2:
        raise CellReportReminderError("estado de lembrete inválido")
    status = getattr(result, "status", None)
    consume_retry_budget = getattr(result, "consume_retry_budget", True)
    retry_after_seconds = getattr(result, "retry_after_seconds", None)
    if (
        type(status) is not str
        or type(consume_retry_budget) is not bool
        or (
            retry_after_seconds is not None
            and (type(retry_after_seconds) is not int or retry_after_seconds < 0)
        )
    ):
        return ReminderResultTransition("ambiguo", attempts, None, "resultado_invalido")
    if status == "aceito":
        return ReminderResultTransition("enviado", attempts, None, None)
    if status == "suprimido":
        return ReminderResultTransition("cancelado", attempts, None, "envio_suprimido")
    if status == "falhou_permanente":
        return ReminderResultTransition("cancelado", attempts, None, "falha_permanente")
    if status != "falhou_retentavel":
        return ReminderResultTransition("ambiguo", attempts, None, "resultado_ambiguo")
    if attempts >= 2:
        return ReminderResultTransition("cancelado", attempts, None, "retries_esgotados")
    next_attempt = attempts + 1
    delay = (
        dt.timedelta(seconds=max(60, retry_after_seconds or 0))
        if consume_retry_budget is False
        else _RETRY_DELAYS[next_attempt - 1]
    )
    return ReminderResultTransition(
        "retry", next_attempt, current + delay, None
    )


def _schema_present(session: Session) -> bool:
    """Avoid referencing V1a tables before their migration exists."""

    bind = session.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return False
    row = session.execute(
        text(
            "select to_regclass('cell_report_drafts') is not null "
            "and to_regclass('cell_report_reminders') is not null "
            "and to_regclass('cell_report_reminder_preferences') is not null"
        )
    ).scalar_one()
    return row is True


def _scoped(session: Session, igreja_id: uuid.UUID, source: str) -> None:
    mark_tenant_scoped(session, igreja_id, source=source)
    require_tenant_scope(session, expected_igreja_id=igreja_id, source=source)


def _valid_uuid(value: object) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        raise CellReportReminderError("identificador de lembrete inválido")
    return value


def _current_lgpd_acceptance(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    now: dt.datetime,
) -> bool:
    term = getattr(get_settings(), "agent_term_version", None)
    rows = tuple(
        LgpdConsentRecord(row.termo_versao, row.aceite_em, row.id)
        for row in session.execute(
            select(ConsentRecord)
            .where(
                ConsentRecord.igreja_id == igreja_id,
                ConsentRecord.pessoa_id == pessoa_id,
            )
            .order_by(ConsentRecord.aceite_em.asc(), ConsentRecord.id.asc())
        ).scalars()
    )
    return current_v1a_lgpd_acceptance(rows, current_term=term, now=now) is not None


def _cancel_reminder(reminder: CellReportReminder, *, now: dt.datetime, reason: str) -> None:
    reminder.state = "cancelado"
    reminder.claim_token = None
    reminder.claimed_until = None
    reminder.terminal_reason = reason
    reminder.updated_at = now


def _lock_reminder_recipient_prefix(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
) -> tuple[Pessoa | None, tuple[Conversation, ...]]:
    """Take the shared Conversation -> Pessoa prefix before any reminder row.

    The persisted ``PARAR LEMBRETES`` path takes exactly this prefix before it
    fences outbox rows.  Claim, fence and maintenance therefore never create a
    R->C/P cycle with a user refusal.
    """

    conversations = tuple(
        session.execute(
            select(Conversation)
            .where(
                Conversation.igreja_id == igreja_id,
                Conversation.pessoa_id == pessoa_id,
            )
            .order_by(Conversation.id.asc())
            .with_for_update()
        ).scalars()
    )
    pessoa = session.execute(
        select(Pessoa)
        .where(Pessoa.igreja_id == igreja_id, Pessoa.id == pessoa_id)
        .with_for_update()
    ).scalar_one_or_none()
    return pessoa, conversations


def _terminalize_expired_claims(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    now: dt.datetime,
    limit: int,
) -> int:
    """Fence stale claims without taking a Reminder lock before C->P."""

    if limit <= 0:
        return 0
    candidates = tuple(
        session.execute(
            select(CellReportReminder.id, CellReportReminder.leader_pessoa_id)
            .where(
                CellReportReminder.igreja_id == igreja_id,
                CellReportReminder.state == "em_envio",
                CellReportReminder.claimed_until.is_not(None),
                CellReportReminder.claimed_until <= now,
            )
            .order_by(CellReportReminder.claimed_until.asc(), CellReportReminder.id.asc())
            .limit(limit)
        ).all()
    )
    changed = 0
    for reminder_id, pessoa_id in candidates:
        if type(reminder_id) is not uuid.UUID or type(pessoa_id) is not uuid.UUID:
            continue
        _lock_reminder_recipient_prefix(
            session,
            igreja_id=igreja_id,
            pessoa_id=pessoa_id,
        )
        reminder = session.execute(
            select(CellReportReminder)
            .where(
                CellReportReminder.igreja_id == igreja_id,
                CellReportReminder.id == reminder_id,
                CellReportReminder.leader_pessoa_id == pessoa_id,
                CellReportReminder.state == "em_envio",
                CellReportReminder.claimed_until.is_not(None),
                CellReportReminder.claimed_until <= now,
            )
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if reminder is None:
            continue
        reminder.state = "ambiguo"
        reminder.claim_token = None
        reminder.claimed_until = None
        reminder.terminal_reason = "lease_expirada"
        reminder.updated_at = now
        changed += 1
    return changed


def _cancel_pending_after_gate_close(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    now: dt.datetime,
    limit: int,
) -> int:
    """Cancel pending rows with the same C->P->R prefix as user refusal."""

    if limit <= 0:
        return 0
    candidates = tuple(
        session.execute(
            select(CellReportReminder.id, CellReportReminder.leader_pessoa_id)
            .where(
                CellReportReminder.igreja_id == igreja_id,
                CellReportReminder.state.in_(("pendente", "retry")),
            )
            .order_by(CellReportReminder.due_at.asc(), CellReportReminder.id.asc())
            .limit(limit)
        ).all()
    )
    changed = 0
    for reminder_id, pessoa_id in candidates:
        if type(reminder_id) is not uuid.UUID or type(pessoa_id) is not uuid.UUID:
            continue
        _lock_reminder_recipient_prefix(
            session,
            igreja_id=igreja_id,
            pessoa_id=pessoa_id,
        )
        reminder = session.execute(
            select(CellReportReminder)
            .where(
                CellReportReminder.igreja_id == igreja_id,
                CellReportReminder.id == reminder_id,
                CellReportReminder.leader_pessoa_id == pessoa_id,
                CellReportReminder.state.in_(("pendente", "retry")),
            )
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if reminder is None:
            continue
        _cancel_reminder(reminder, now=now, reason="gate_fechado")
        changed += 1
    return changed


def _proposals_for_v1a_draft(
    session: Session,
    *,
    draft: CellReportDraft,
) -> tuple[AgentActionProposal, ...]:
    """Load every proposal durably associated with this draft.

    A correction reuses the same draft UUID with a newer revision. Historical
    summaries are retained only if delivered, so sweep needs every revision,
    while selection of the live proposal happens separately below.
    """

    draft_id = getattr(draft, "id", None)
    if type(draft_id) is not uuid.UUID:
        return ()
    return tuple(
        session.execute(
            select(AgentActionProposal)
            .where(
                AgentActionProposal.igreja_id == draft.igreja_id,
                AgentActionProposal.conversation_id == draft.conversation_id,
                AgentActionProposal.actor_pessoa_id == draft.actor_pessoa_id,
                AgentActionProposal.target_id == draft.reuniao_id,
                AgentActionProposal.action == _V1A_REPORT_ACTION,
                AgentActionProposal.arguments_json["rascunho_id"].as_string()
                == str(draft_id),
            )
            .order_by(AgentActionProposal.created_at.desc(), AgentActionProposal.id.desc())
            # The sweep already owns Conversation then Pessoa.  Waiting for a
            # short proposal lock is safer than terminalizing a draft while an
            # older active proposal was skipped and would no longer be found.
            .with_for_update()
        ).scalars()
    )


def _current_proposal_for_v1a_draft(
    draft: CellReportDraft,
    proposals: tuple[AgentActionProposal, ...],
) -> AgentActionProposal | None:
    """Return the newest validated proposal for the draft's current revision."""

    revision = getattr(draft, "revision", None)
    if type(revision) is not int or revision <= 0:
        return None
    for proposal in proposals:
        arguments = getattr(proposal, "arguments_json", None)
        if type(arguments) is dict and arguments.get("revisao") == revision:
            return proposal
    return None


def _v1a_draft_context_is_current(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa: Pessoa | None,
    conversations: tuple[Conversation, ...],
    meeting_is_current: bool,
    now: dt.datetime,
) -> bool:
    """Check only the durable context needed to retain an active draft."""

    if (
        pessoa is None
        or pessoa.arquivada_em is not None
        or pessoa.optout
        or pessoa.sem_interesse
        or any(
            row.estado == "humano" or row.assumido_por is not None
            for row in conversations
        )
        or not meeting_is_current
        or not cell_report_enabled_from_environment(igreja_id)
    ):
        return False
    config = session.execute(
        select(AgentConfig)
        .where(AgentConfig.igreja_id == igreja_id)
        .with_for_update()
    ).scalar_one_or_none()
    credential = session.execute(
        select(LlmCredential)
        .where(LlmCredential.igreja_id == igreja_id)
        .with_for_update()
    ).scalar_one_or_none()
    return (
        config is not None
        and config.ativo is True
        and credential is not None
        and credential.ativo is True
        and credential.validado is True
        and (
            _current_lgpd_acceptance(
                session,
                igreja_id=igreja_id,
                pessoa_id=pessoa.id,
                now=now,
            )
            is True
        )
    )


def _locked_v1a_draft_meeting_is_current(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    reuniao_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    now: dt.datetime,
) -> bool:
    """Revalidate the report target in the shared lock order.

    The caller has already locked Conversation then Pessoa.  This acquires the
    meeting and delegates the Cell, leader and ministerial-access checks to the
    same human-equivalent service used by report finalization.  It deliberately
    has no delivery side effect.
    """

    meeting = session.execute(
        select(CelulaReuniao)
        .where(
            CelulaReuniao.igreja_id == igreja_id,
            CelulaReuniao.id == reuniao_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if (
        meeting is None
        or meeting.relatorio_status != "pendente"
        or meeting.status == "cancelada"
        or type(meeting.data) is not dt.date
        or not meeting_has_passed(data=meeting.data, hora=meeting.hora, now=now)
    ):
        return False
    try:
        revalidate_cell_report_leader(
            session,
            igreja_id=igreja_id,
            meeting=meeting,
            ator_pessoa_id=pessoa_id,
        )
    except CellReportApplicationError:
        return False
    return True


def _purge_unconfirmed_v1a_summary(
    session: Session,
    *,
    proposal: AgentActionProposal,
) -> bool:
    """Erase a summary only when transport was provably never started.

    ``False`` deliberately keeps the parent draft selectable.  A late
    reconciliation may still establish delivery for an in-flight or ambiguous
    ledger row; private content must not be marked purged before that result.
    """

    if proposal.delivered_at is not None or type(proposal.summary_message_id) is not uuid.UUID:
        return True
    summary = session.execute(
        select(Message)
        .where(
            Message.igreja_id == proposal.igreja_id,
            Message.conversation_id == proposal.conversation_id,
            Message.id == proposal.summary_message_id,
            Message.direcao == "out",
            Message.autor == "ia",
        )
        .with_for_update()
    ).scalar_one_or_none()
    # A confirmed ledger row is durable evidence of delivery even if a crash
    # happened before proposal promotion. Preserve that history.
    if summary is None or summary.agent_reply_state == AGENT_REPLY_CONFIRMED:
        return True
    if summary.agent_reply_state in _SUMMARY_RECONCILIATION_REQUIRED:
        return False
    if summary.agent_reply_state not in _SUMMARY_SAFE_TO_ERASE:
        return False
    summary.texto = None
    summary.agent_reply_state = AGENT_REPLY_SUPPRESSED
    # JSONB maps Python None to JSON ``null`` unless the column opts into
    # ``none_as_null``. The ledger constraint accepts only an object or SQL
    # NULL, so use an explicit SQL null for this legacy mapping.
    summary.agent_privilege_context = null()
    return True


def _terminalize_v1a_draft(
    draft: CellReportDraft,
    *,
    now: dt.datetime,
    expired: bool,
    content_purged: bool,
) -> bool:
    """Terminalize aggregate collection, retaining a reconciliation marker.

    When an outbound summary is ambiguous, ``content_purged_at`` stays NULL so
    the next sweep can revisit the draft after ledger reconciliation.  The
    private aggregate itself is still cleared immediately.
    """

    changed = False
    state = "expirado" if expired else "cancelado"
    if draft.state != state:
        draft.state = state
        changed = True
    if draft.candidate_json is not None:
        draft.candidate_json = None
        changed = True
    if draft.candidate_sha256 is not None:
        draft.candidate_sha256 = None
        changed = True
    if draft.terminal_at is None:
        draft.terminal_at = now
        changed = True
    if content_purged:
        if draft.content_purged_at is None:
            draft.content_purged_at = now
            changed = True
    elif draft.content_purged_at is not None:
        draft.content_purged_at = None
        changed = True
    if changed:
        draft.updated_at = now
    return changed


def _purge_v1a_draft_content(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    now: dt.datetime,
    limit: int,
) -> int:
    """Prioritize V1a aggregate erasure over outbox maintenance work.

    Claims can be numerous after a provider outage.  They never consume this
    content-retention quota, otherwise expired drafts in this or later tenants
    could retain private aggregates indefinitely.
    """

    if limit <= 0:
        return 0
    # Scan lightweight identities rather than applying ``limit`` before the
    # eligibility checks.  Otherwise a stable prefix of valid old drafts can
    # starve a later expired, revoked or human-owned draft forever.  ``limit``
    # still bounds mutations, and terminalized rows leave this candidate set.
    candidates = tuple(
        session.execute(
            select(
                CellReportDraft.id,
                CellReportDraft.actor_pessoa_id,
                CellReportDraft.reuniao_id,
            )
            .where(
                CellReportDraft.igreja_id == igreja_id,
                or_(
                    CellReportDraft.state.in_(tuple(_DRAFT_ACTIVE)),
                    CellReportDraft.candidate_json.is_not(None),
                    CellReportDraft.content_purged_at.is_(None),
                ),
            )
            .order_by(
                CellReportDraft.expires_at.asc(),
                CellReportDraft.updated_at.asc(),
                CellReportDraft.id.asc(),
            )
        ).all()
    )
    changed = 0
    for draft_id, pessoa_id, reuniao_id in candidates:
        if changed >= limit:
            break
        if (
            type(draft_id) is not uuid.UUID
            or type(pessoa_id) is not uuid.UUID
            or type(reuniao_id) is not uuid.UUID
        ):
            continue
        pessoa, conversations = _lock_reminder_recipient_prefix(
            session,
            igreja_id=igreja_id,
            pessoa_id=pessoa_id,
        )
        # Every target check follows Conversation -> Pessoa -> Meeting -> Cell
        # before this sweep takes the Draft/Proposal rows.  This matches the
        # human finalizer and avoids a stale role or reassigned cell retaining
        # a private aggregate through the 24-hour TTL.
        meeting_is_current = _locked_v1a_draft_meeting_is_current(
            session,
            igreja_id=igreja_id,
            reuniao_id=reuniao_id,
            pessoa_id=pessoa_id,
            now=now,
        )
        draft = session.execute(
            select(CellReportDraft)
            .where(
                CellReportDraft.igreja_id == igreja_id,
                CellReportDraft.id == draft_id,
                CellReportDraft.actor_pessoa_id == pessoa_id,
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if draft is None:
            continue
        proposals = _proposals_for_v1a_draft(session, draft=draft)
        proposal = _current_proposal_for_v1a_draft(draft, proposals)
        expired = draft.expires_at <= now
        must_terminalize = expired or draft.state not in _DRAFT_ACTIVE
        context_current = (
            _v1a_draft_context_is_current(
                session,
                igreja_id=igreja_id,
                pessoa=pessoa,
                conversations=conversations,
                meeting_is_current=meeting_is_current,
                now=now,
            )
            if not must_terminalize and draft.state in _DRAFT_ACTIVE
            else False
        )
        if proposal is None:
            # Partial reports do not have an S3 proposal yet, but their four
            # aggregates are still private draft content. A later SAIR,
            # human takeover, release revocation or term change erases them.
            must_terminalize = must_terminalize or not context_current
        else:
            if proposal.state == "pendente" and (
                proposal.expires_at is None or proposal.expires_at <= now
            ):
                proposal.state = "expirada"
                proposal.terminal_reason = "expired"
                proposal.expires_at = None
                must_terminalize = True
                expired = True
            elif proposal.state not in _PROPOSAL_ACTIVE:
                must_terminalize = True
                expired = proposal.state == "expirada" or expired
            elif not context_current:
                proposal.state = "cancelada"
                proposal.terminal_reason = "contexto_revogado"
                proposal.expires_at = None
                must_terminalize = True
        if not must_terminalize:
            # A correction can leave an older summary terminal but never
            # delivered. It no longer represents a live offer, so erase it
            # even while the newer draft remains active. A stale active
            # historical proposal has the same treatment, otherwise it blocks
            # the current revision through the S3 one-active constraint.
            for historical in proposals:
                if historical is proposal:
                    continue
                if historical.state in _PROPOSAL_ACTIVE:
                    historical.state = "cancelada"
                    historical.terminal_reason = "revisao_substituida"
                    historical.expires_at = None
                _purge_unconfirmed_v1a_summary(session, proposal=historical)
            continue
        summaries_purged = True
        for historical in proposals:
            if historical.state in _PROPOSAL_ACTIVE:
                historical.state = (
                    "expirada" if expired and historical is proposal else "cancelada"
                )
                historical.terminal_reason = (
                    "expired" if expired and historical is proposal else "draft_terminal"
                )
                historical.expires_at = None
            summaries_purged = (
                _purge_unconfirmed_v1a_summary(session, proposal=historical)
                and summaries_purged
            )
        if _terminalize_v1a_draft(
            draft,
            now=now,
            expired=expired,
            content_purged=summaries_purged,
        ):
            changed += 1
    return changed


def disable_cell_report_reminders(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID | None = None,
    pessoa_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> bool:
    """Persist a scoped reminder refusal and fence pending provider work.

    The caller owns the enclosing transaction. An in-flight row is marked
    ambiguous rather than cancelled because the provider boundary may already
    have started; its late result cannot revive it.
    """

    tenant = _valid_uuid(igreja_id)
    person = _valid_uuid(pessoa_id)
    current = _now(now)
    require_tenant_scope(session, expected_igreja_id=tenant, source="cell_report_reminder_stop")
    if not _schema_present(session):
        return False
    if conversation_id is not None:
        conversation = _valid_uuid(conversation_id)
        locked_conversation = session.execute(
            select(Conversation)
            .where(
                Conversation.igreja_id == tenant,
                Conversation.id == conversation,
                Conversation.pessoa_id == person,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if locked_conversation is None:
            return False
        locked_person = session.execute(
            select(Pessoa)
            .where(Pessoa.igreja_id == tenant, Pessoa.id == person)
            .with_for_update()
        ).scalar_one_or_none()
    else:
        # Direct maintenance callers have no anchored conversation.  They take
        # the complete sorted Conversation prefix before Pessoa.
        locked_person, _ = _lock_reminder_recipient_prefix(
            session,
            igreja_id=tenant,
            pessoa_id=person,
        )
    if locked_person is None:
        return False
    preference = session.execute(
        select(CellReportReminderPreference)
        .where(
            CellReportReminderPreference.igreja_id == tenant,
            CellReportReminderPreference.pessoa_id == person,
        )
        .with_for_update()
    ).scalar_one_or_none()
    changed = preference is None
    if preference is None:
        try:
            with session.begin_nested():
                preference = CellReportReminderPreference(
                    igreja_id=tenant,
                    pessoa_id=person,
                    disabled_at=current,
                    updated_at=current,
                )
                session.add(preference)
                session.flush()
        except IntegrityError:
            preference = session.execute(
                select(CellReportReminderPreference)
                .where(
                    CellReportReminderPreference.igreja_id == tenant,
                    CellReportReminderPreference.pessoa_id == person,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if preference is None:
                raise
            changed = False
    else:
        preference.updated_at = current
    session.execute(
        update(CellReportReminder)
        .where(
            CellReportReminder.igreja_id == tenant,
            CellReportReminder.leader_pessoa_id == person,
            CellReportReminder.state.in_(("pendente", "retry")),
        )
        .values(
            state="cancelado",
            claim_token=None,
            claimed_until=None,
            terminal_reason="lembretes_recusados",
            updated_at=current,
        )
    )
    # A delivery already in flight is uncertain, never automatically retried.
    session.execute(
        update(CellReportReminder)
        .where(
            CellReportReminder.igreja_id == tenant,
            CellReportReminder.leader_pessoa_id == person,
            CellReportReminder.state == "em_envio",
        )
        .values(
            state="ambiguo",
            claim_token=None,
            claimed_until=None,
            terminal_reason="lembretes_recusados_em_envio",
            updated_at=current,
        )
    )
    return changed


def _reminder_gates_allow(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    reuniao_id: uuid.UUID,
    now: dt.datetime,
) -> tuple[bool, str | None]:
    """Revalidate all autonomous-message gates while holding short row locks."""

    settings = get_settings()
    if (
        not cell_report_enabled_from_environment(igreja_id)
        or not external_sends_allowed(settings)
        or not settings.whatsapp_piloto(igreja_id)
    ):
        return False, "gate_fechado"
    pessoa, conversations = _lock_reminder_recipient_prefix(
        session,
        igreja_id=igreja_id,
        pessoa_id=pessoa_id,
    )
    if any(row.estado == "humano" or row.assumido_por is not None for row in conversations):
        return False, "atendimento_humano"
    igreja = session.execute(
        select(Igreja).where(Igreja.id == igreja_id).with_for_update()
    ).scalar_one_or_none()
    config = session.execute(
        select(AgentConfig)
        .where(AgentConfig.igreja_id == igreja_id)
        .with_for_update()
    ).scalar_one_or_none()
    credential = session.execute(
        select(LlmCredential)
        .where(LlmCredential.igreja_id == igreja_id)
        .with_for_update()
    ).scalar_one_or_none()
    preference = session.execute(
        select(CellReportReminderPreference)
        .where(
            CellReportReminderPreference.igreja_id == igreja_id,
            CellReportReminderPreference.pessoa_id == pessoa_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if (
        pessoa is None
        or pessoa.arquivada_em is not None
        or pessoa.optout
        or pessoa.sem_interesse
        or igreja is None
        or igreja.status in BLOCKING_IGREJA_STATUSES
        or config is None
        or config.ativo is not True
        or credential is None
        or credential.ativo is not True
        or credential.validado is not True
        or preference is not None
        or not _current_lgpd_acceptance(
            session, igreja_id=igreja_id, pessoa_id=pessoa_id, now=now
        )
    ):
        return False, "contexto_revogado"
    phone = normalize_phone(pessoa.telefone)
    if not phone:
        return False, "telefone_invalido"
    digits = func.regexp_replace(Pessoa.telefone, r"\D", "", "g")
    same_suffix = tuple(
        session.execute(
            select(Pessoa)
            .where(
                Pessoa.igreja_id == igreja_id,
                Pessoa.arquivada_em.is_(None),
                func.right(digits, 8) == phone_suffix(phone),
            )
            .order_by(Pessoa.id.asc())
            .limit(3)
        ).scalars()
    )
    matching_people = tuple(
        row
        for row in same_suffix
        if normalize_phone(getattr(row, "telefone", "") or "") == phone
    )
    if len(same_suffix) == 3 or len(matching_people) != 1 or matching_people[0].id != pessoa_id:
        return False, "telefone_ambiguo"
    meeting = session.execute(
        select(CelulaReuniao)
        .where(
            CelulaReuniao.igreja_id == igreja_id,
            CelulaReuniao.id == reuniao_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if (
        meeting is None
        or meeting.relatorio_status != "pendente"
        or meeting.status == "cancelada"
        or cell_report_reminder_is_obsolete(meeting.data, meeting.hora, now)
    ):
        return False, "reuniao_indisponivel"
    try:
        revalidate_cell_report_leader(
            session,
            igreja_id=igreja_id,
            meeting=meeting,
            ator_pessoa_id=pessoa_id,
        )
    except CellReportApplicationError:
        return False, "lideranca_revogada"
    return True, phone


def _discover_tenants(session_factory: Callable[[], Session], *, source: str) -> tuple[uuid.UUID, ...]:
    session = session_factory()
    try:
        mark_cross_tenant(session, source=source)
        if not _schema_present(session):
            return ()
        ids = set(session.execute(select(CellReportDraft.igreja_id).distinct()).scalars())
        ids.update(session.execute(select(CellReportReminder.igreja_id).distinct()).scalars())
        ids.update(
            session.execute(
                select(CelulaReuniao.igreja_id)
                .join(Celula, Celula.id == CelulaReuniao.celula_id)
                .where(
                    Celula.ativo.is_(True),
                    Celula.lider_id.is_not(None),
                    CelulaReuniao.relatorio_status == "pendente",
                )
                .distinct()
            ).scalars()
        )
        return tuple(sorted((row for row in ids if type(row) is uuid.UUID), key=str))
    finally:
        session.close()


def _create_due_reminders_for_tenant(
    session_factory: Callable[[], Session],
    igreja_id: uuid.UUID,
    *,
    now: dt.datetime,
    limit: int,
) -> int:
    if not cell_report_enabled_from_environment(igreja_id):
        return 0
    session = session_factory()
    try:
        _scoped(session, igreja_id, "cell_report_reminder_schedule")
        meetings = tuple(
            session.execute(
                select(
                    CelulaReuniao.id,
                    CelulaReuniao.celula_id,
                    Celula.lider_id,
                )
                .join(
                    Celula,
                    (Celula.igreja_id == CelulaReuniao.igreja_id)
                    & (Celula.id == CelulaReuniao.celula_id),
                )
                .where(
                    CelulaReuniao.igreja_id == igreja_id,
                    CelulaReuniao.relatorio_status == "pendente",
                    CelulaReuniao.status != "cancelada",
                    Celula.ativo.is_(True),
                    Celula.lider_id.is_not(None),
                )
                .order_by(CelulaReuniao.data.asc(), CelulaReuniao.id.asc())
            ).all()
        )
        created = 0
        for meeting_id, _cell_id, leader_id in meetings:
            if created >= limit:
                break
            if type(meeting_id) is not uuid.UUID or type(leader_id) is not uuid.UUID:
                continue
            allowed, _ = _reminder_gates_allow(
                session,
                igreja_id=igreja_id,
                pessoa_id=leader_id,
                reuniao_id=meeting_id,
                now=now,
            )
            if not allowed:
                continue
            # `_reminder_gates_allow` has already locked this meeting after the
            # Conversation and Pessoa prefix.  Reading from the identity map
            # avoids taking Meeting/Cell locks in the inverse order here.
            meeting = session.get(CelulaReuniao, meeting_id)
            if meeting is None:
                continue
            due_at = cell_report_reminder_due_at(meeting.data, meeting.hora)
            if due_at is None or due_at > now:
                continue
            if cell_report_reminder_is_obsolete(meeting.data, meeting.hora, now):
                continue
            recent = session.execute(
                select(CellReportReminder.id)
                .where(
                    CellReportReminder.igreja_id == igreja_id,
                    CellReportReminder.leader_pessoa_id == leader_id,
                    CellReportReminder.created_at >= now - dt.timedelta(hours=24),
                )
                .limit(1)
            ).scalar_one_or_none()
            if recent is not None:
                continue
            reminder = CellReportReminder(
                igreja_id=igreja_id,
                reuniao_id=meeting.id,
                leader_pessoa_id=leader_id,
                state="pendente",
                due_at=due_at,
                claim_token=None,
                claimed_until=None,
                attempts=0,
                notice_recorded_at=None,
                sent_at=None,
                text_sha256=cell_report_reminder_text_sha256(),
                terminal_reason=None,
                created_at=now,
                updated_at=now,
            )
            try:
                with session.begin_nested():
                    session.add(reminder)
                    session.flush()
            except IntegrityError:
                continue
            created += 1
        session.commit()
        return created
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def schedule_due_cell_report_reminders(
    session_factory: Callable[[], Session],
    *,
    now: dt.datetime | None = None,
    limit: int = 100,
) -> int:
    """Materialize bounded V1a reminder intentions; never call a provider."""

    current = _now(now)
    if type(limit) is not int or limit <= 0:
        raise CellReportReminderError("limite de lembretes inválido")
    created = 0
    for igreja_id in _discover_tenants(session_factory, source="cell_report_reminder_discovery"):
        if created >= limit:
            break
        created += _create_due_reminders_for_tenant(
            session_factory, igreja_id, now=current, limit=limit - created
        )
    return created


def _claim_next_reminder(
    session_factory: Callable[[], Session],
    igreja_id: uuid.UUID,
    *,
    now: dt.datetime,
    lease_seconds: int,
) -> ReminderClaim | None:
    session = session_factory()
    try:
        _scoped(session, igreja_id, "cell_report_reminder_claim")
        candidate = session.execute(
            select(
                CellReportReminder.id,
                CellReportReminder.reuniao_id,
                CellReportReminder.leader_pessoa_id,
            )
            .where(
                CellReportReminder.igreja_id == igreja_id,
                CellReportReminder.state.in_(("pendente", "retry")),
                CellReportReminder.due_at <= now,
            )
            .order_by(CellReportReminder.due_at.asc(), CellReportReminder.id.asc())
            .limit(1)
        ).one_or_none()
        if candidate is None:
            session.commit()
            return None
        reminder_id, reuniao_id, leader_pessoa_id = candidate
        allowed, phone_or_reason = _reminder_gates_allow(
            session,
            igreja_id=igreja_id,
            pessoa_id=leader_pessoa_id,
            reuniao_id=reuniao_id,
            now=now,
        )
        reminder = session.execute(
            select(CellReportReminder)
            .where(
                CellReportReminder.igreja_id == igreja_id,
                CellReportReminder.id == reminder_id,
                CellReportReminder.state.in_(("pendente", "retry")),
                CellReportReminder.due_at <= now,
                CellReportReminder.reuniao_id == reuniao_id,
                CellReportReminder.leader_pessoa_id == leader_pessoa_id,
            )
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if reminder is None:
            session.commit()
            return None
        if not allowed:
            _cancel_reminder(reminder, now=now, reason=phone_or_reason or "contexto_revogado")
            session.commit()
            return None
        if not cell_report_reminder_transport_window_open(now):
            reminder.state = "retry"
            reminder.claim_token = None
            reminder.claimed_until = None
            reminder.due_at = _next_transport_window(now)
            reminder.terminal_reason = None
            reminder.updated_at = now
            session.commit()
            return None
        connection = session.execute(
            select(WhatsappConnection)
            .where(
                WhatsappConnection.igreja_id == igreja_id,
                WhatsappConnection.status == "online",
                WhatsappConnection.instance.is_not(None),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if connection is None or not connection.instance:
            reminder.due_at = now + dt.timedelta(minutes=1)
            reminder.updated_at = now
            session.commit()
            return None
        if reminder.text_sha256 != cell_report_reminder_text_sha256():
            _cancel_reminder(reminder, now=now, reason="texto_inconsistente")
            session.commit()
            return None
        token = uuid.uuid4()
        reminder.state = "em_envio"
        reminder.claim_token = token
        reminder.claimed_until = now + dt.timedelta(seconds=max(1, lease_seconds))
        reminder.updated_at = now
        session.commit()
        return ReminderClaim(
            igreja_id=igreja_id,
            reminder_id=reminder.id,
            reuniao_id=reminder.reuniao_id,
            leader_pessoa_id=reminder.leader_pessoa_id,
            claim_token=token,
            instance=connection.instance,
            phone=phone_or_reason or "",
            text=cell_report_reminder_text(),
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _renew_reminder_transport_fence(
    session_factory: Callable[[], Session],
    claim: ReminderClaim,
    *,
    now: dt.datetime,
    lease_seconds: int,
) -> bool:
    """Commit a fresh ownership and gate proof immediately before HTTP."""

    session = session_factory()
    try:
        _scoped(session, claim.igreja_id, "cell_report_reminder_transport_fence")
        allowed, phone_or_reason = _reminder_gates_allow(
            session,
            igreja_id=claim.igreja_id,
            pessoa_id=claim.leader_pessoa_id,
            reuniao_id=claim.reuniao_id,
            now=now,
        )
        reminder = session.execute(
            select(CellReportReminder)
            .where(
                CellReportReminder.igreja_id == claim.igreja_id,
                CellReportReminder.id == claim.reminder_id,
            )
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if (
            reminder is None
            or reminder.state != "em_envio"
            or reminder.claim_token != claim.claim_token
            or reminder.claimed_until is None
            or reminder.claimed_until <= now
            or reminder.text_sha256 != cell_report_reminder_text_sha256()
            or reminder.reuniao_id != claim.reuniao_id
            or reminder.leader_pessoa_id != claim.leader_pessoa_id
        ):
            session.rollback()
            return False
        if not allowed:
            _cancel_reminder(reminder, now=now, reason=phone_or_reason or "contexto_revogado")
            session.commit()
            return False
        if phone_or_reason != claim.phone:
            _cancel_reminder(reminder, now=now, reason="destino_alterado")
            session.commit()
            return False
        if not cell_report_reminder_transport_window_open(now):
            reminder.state = "retry"
            reminder.claim_token = None
            reminder.claimed_until = None
            reminder.due_at = _next_transport_window(now)
            reminder.terminal_reason = None
            reminder.updated_at = now
            session.commit()
            return False
        connection = session.execute(
            select(WhatsappConnection)
            .where(WhatsappConnection.igreja_id == claim.igreja_id)
            .with_for_update()
        ).scalar_one_or_none()
        if (
            connection is None
            or connection.status != "online"
            or not isinstance(connection.instance, str)
            or not connection.instance
            or connection.instance != claim.instance
        ):
            _cancel_reminder(reminder, now=now, reason="destino_alterado")
            session.commit()
            return False
        reminder.claimed_until = now + dt.timedelta(seconds=max(1, lease_seconds))
        reminder.updated_at = now
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _record_reminder_result(
    session_factory: Callable[[], Session],
    claim: ReminderClaim,
    result: object,
    *,
    now: dt.datetime,
) -> bool:
    session = session_factory()
    try:
        _scoped(session, claim.igreja_id, "cell_report_reminder_result")
        reminder = session.execute(
            select(CellReportReminder)
            .where(
                CellReportReminder.igreja_id == claim.igreja_id,
                CellReportReminder.id == claim.reminder_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if (
            reminder is None
            or reminder.state != "em_envio"
            or reminder.claim_token != claim.claim_token
            or reminder.claimed_until is None
            or reminder.claimed_until <= now
        ):
            session.rollback()
            return False
        transition = reminder_result_transition(result, attempts=reminder.attempts, now=now)
        reminder.state = transition.state
        reminder.attempts = transition.attempts
        reminder.due_at = transition.due_at or reminder.due_at
        reminder.claim_token = None
        reminder.claimed_until = None
        reminder.terminal_reason = transition.terminal_reason
        reminder.updated_at = now
        if transition.state == "enviado":
            reminder.sent_at = now
            reminder.notice_recorded_at = reminder.notice_recorded_at or now
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispatch_cell_report_reminders(
    session_factory: Callable[[], Session],
    evolution_client: EvolutionClient,
    *,
    worker_id: str,
    now: dt.datetime | None = None,
    limit: int = 20,
    lease_seconds: int = 30,
) -> int:
    """Claim, revalidate, transport and record a bounded reminder batch.

    Every provider call happens after the claim and fresh transport-fence
    transactions have committed and closed. A raised transport error is
    ambiguous and therefore never retried automatically.
    """

    if type(worker_id) is not str or not worker_id.strip():
        raise CellReportReminderError("worker de lembrete inválido")
    if type(limit) is not int or limit <= 0 or type(lease_seconds) is not int or lease_seconds <= 0:
        raise CellReportReminderError("limite de lembretes inválido")
    fixed_now = _now(now) if now is not None else None

    def current_time() -> dt.datetime:
        return fixed_now if fixed_now is not None else _now(None)

    dispatched = 0
    for igreja_id in _discover_tenants(session_factory, source="cell_report_reminder_dispatch_discovery"):
        if dispatched >= limit:
            break
        while dispatched < limit:
            claim = _claim_next_reminder(
                session_factory,
                igreja_id,
                now=current_time(),
                lease_seconds=lease_seconds,
            )
            if claim is None:
                break
            dispatched += 1
            try:
                can_send = _renew_reminder_transport_fence(
                    session_factory,
                    claim,
                    now=current_time(),
                    lease_seconds=lease_seconds,
                )
            except Exception:  # noqa: BLE001 - never send without a new fence
                logger.exception("Cell-report reminder transport fence failed")
                continue
            if not can_send:
                continue
            try:
                result = evolution_client.send_text_classificado(
                    claim.instance,
                    claim.phone,
                    claim.text,
                )
            except Exception:  # noqa: BLE001 - uncertain provider boundary
                result = BroadcastSendResult(
                    status="desconhecido", error_class="erro_nao_classificado"
                )
            _record_reminder_result(session_factory, claim, result, now=current_time())
    return dispatched


def _purge_tenant_state(
    session_factory: Callable[[], Session],
    igreja_id: uuid.UUID,
    *,
    now: dt.datetime,
    limit: int,
) -> int:
    session = session_factory()
    try:
        _scoped(session, igreja_id, "cell_report_state_purge")
        # Content retention has its own quota.  A provider outage can create
        # many expired claims, but it must not postpone removal of private
        # report aggregates in this or later tenants.
        content_changed = _purge_v1a_draft_content(
            session,
            igreja_id=igreja_id,
            now=now,
            limit=limit,
        )
        maintenance_limit = max(1, limit)
        _terminalize_expired_claims(
            session,
            igreja_id=igreja_id,
            now=now,
            limit=maintenance_limit,
        )
        # Turning off V1a never lets an old pending row wait for a later
        # re-enable. This is maintenance, not a new-effect gate.
        if not cell_report_enabled_from_environment(igreja_id):
            _cancel_pending_after_gate_close(
                session,
                igreja_id=igreja_id,
                now=now,
                limit=maintenance_limit,
            )
            session.commit()
            return content_changed
        candidates = tuple(
            session.execute(
                select(
                    CellReportReminder.id,
                    CellReportReminder.leader_pessoa_id,
                    CellReportReminder.reuniao_id,
                )
                .where(
                    CellReportReminder.igreja_id == igreja_id,
                    CellReportReminder.state.in_(("pendente", "retry")),
                )
                .order_by(CellReportReminder.due_at.asc(), CellReportReminder.id.asc())
                .limit(maintenance_limit)
            ).all()
        )
        for reminder_id, pessoa_id, reuniao_id in candidates:
            if (
                type(reminder_id) is not uuid.UUID
                or type(pessoa_id) is not uuid.UUID
                or type(reuniao_id) is not uuid.UUID
            ):
                continue
            # All worker paths which touch these rows use this prefix.  The
            # initial candidate scan intentionally holds no row lock.
            _lock_reminder_recipient_prefix(
                session,
                igreja_id=igreja_id,
                pessoa_id=pessoa_id,
            )
            meeting = session.execute(
                select(CelulaReuniao)
                .where(
                    CelulaReuniao.igreja_id == igreja_id,
                    CelulaReuniao.id == reuniao_id,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if meeting is None:
                continue
            # Lock the cell after its meeting even though only its existence is
            # needed here.  Scheduler, finalizer and this maintenance path then
            # share C -> P -> Meeting -> Cell -> Reminder ordering.
            cell = session.execute(
                select(Celula)
                .where(
                    Celula.igreja_id == igreja_id,
                    Celula.id == meeting.celula_id,
                )
                .with_for_update(skip_locked=True)
            ).scalar_one_or_none()
            reminder = session.execute(
                select(CellReportReminder)
                .where(
                    CellReportReminder.igreja_id == igreja_id,
                    CellReportReminder.id == reminder_id,
                    CellReportReminder.leader_pessoa_id == pessoa_id,
                    CellReportReminder.reuniao_id == reuniao_id,
                    CellReportReminder.state.in_(("pendente", "retry")),
                )
                .with_for_update(skip_locked=True)
            ).scalar_one_or_none()
            if reminder is None:
                continue
            if cell is None:
                _cancel_reminder(reminder, now=now, reason="reuniao_indisponivel")
                continue
            if cell_report_reminder_is_obsolete(meeting.data, meeting.hora, now):
                reminder.state = "obsoleto"
                reminder.claim_token = None
                reminder.claimed_until = None
                reminder.terminal_reason = "janela_expirada"
                reminder.updated_at = now
        session.commit()
        return content_changed
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def purge_expired_cell_report_state(
    session_factory: Callable[[], Session],
    *,
    now: dt.datetime | None = None,
    limit: int = 100,
) -> int:
    """Purge V1a drafts and fence stale outbox rows even after flag disable."""

    current = _now(now)
    if type(limit) is not int or limit <= 0:
        raise CellReportReminderError("limite de manutenção inválido")
    changed = 0
    for igreja_id in _discover_tenants(session_factory, source="cell_report_state_purge_discovery"):
        # ``limit`` is a per-tenant private-content quota. A busy first tenant
        # must not prevent a later tenant's expired or revoked report data from
        # being considered at all. The lower-level sweep scans identities until
        # it has mutated this tenant's quota, so valid prefixes do not starve
        # eligible rows either.
        changed += _purge_tenant_state(
            session_factory, igreja_id, now=current, limit=limit
        )
    return changed


__all__ = [
    "CellReportReminderError",
    "ReminderClaim",
    "ReminderResultTransition",
    "cell_report_reminder_due_at",
    "cell_report_reminder_is_obsolete",
    "cell_report_reminder_text",
    "cell_report_reminder_text_sha256",
    "disable_cell_report_reminders",
    "dispatch_cell_report_reminders",
    "purge_expired_cell_report_state",
    "reminder_result_transition",
    "schedule_due_cell_report_reminders",
]
