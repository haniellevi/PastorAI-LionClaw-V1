"""Shared durable outbox for Agenda, internal EVT-7 and V1a reminders.

Intent creation commits without transport.  The common dispatcher then claims,
revalidates and fences each intent before one classified provider call.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session


_UTC = dt.timezone.utc
SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
_OPEN = dt.time(8, 0)
_CLOSE = dt.time(21, 0)
_STOP_REMINDERS_NOTICE = " Para parar lembretes, envie PARAR LEMBRETES."
_EVT7_PRE_SEND_GRACE = dt.timedelta(minutes=10)
_RETRY_DELAYS = (dt.timedelta(minutes=1), dt.timedelta(minutes=5))
_PROVEN_PRE_SEND_ERRORS = frozenset(
    {
        "configuracao_ausente",
        "connect_error",
        "connect_timeout",
        "pool_timeout",
        "http_429",
    }
)

logger = logging.getLogger("pastorai.notification_outbox")

@dataclass(frozen=True, slots=True)
class NotificationResultTransition:
    state: str
    attempts: int
    due_at: dt.datetime | None
    terminal_reason: str | None


@dataclass(frozen=True, slots=True)
class NotificationClaim:
    igreja_id: uuid.UUID
    outbox_id: uuid.UUID
    pessoa_id: uuid.UUID
    claim_token: uuid.UUID
    destination_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class NotificationTransport:
    """Transient provider input built only after the durable transport fence."""

    claim: NotificationClaim
    instance: str
    phone: str
    text: str


def _utc_datetime(value: object) -> dt.datetime | None:
    if type(value) is not dt.datetime or value.tzinfo is None:
        return None
    try:
        return value.astimezone(_UTC)
    except (OverflowError, ValueError):
        return None


def transport_window_open(now: object) -> bool:
    """Return whether a provider call may begin at ``now``.

    The pilot has one explicit timezone and the upper bound is exclusive.
    """

    current = _utc_datetime(now)
    if current is None:
        return False
    local_time = current.astimezone(SAO_PAULO_TZ).timetz().replace(tzinfo=None)
    return _OPEN <= local_time < _CLOSE


def next_transport_window(now: object) -> dt.datetime | None:
    """Return the first permitted São Paulo instant at or after ``now``."""

    current = _utc_datetime(now)
    if current is None:
        return None
    local = current.astimezone(SAO_PAULO_TZ)
    local_time = local.timetz().replace(tzinfo=None)
    if local_time < _OPEN:
        return local.replace(hour=8, minute=0, second=0, microsecond=0).astimezone(_UTC)
    if local_time >= _CLOSE:
        return (local + dt.timedelta(days=1)).replace(
            hour=8, minute=0, second=0, microsecond=0
        ).astimezone(_UTC)
    return current


def _evt7_pre_send_deadline(created_at: object) -> dt.datetime | None:
    """Bound EVT-7 pre-send deferrals to its first eligible window.

    ``created_at`` never changes across a retry, unlike ``due_at``. An internal
    confirmation made after 21:00 therefore gets the next morning's ten-minute
    grace period, while a repeatedly contended source can never create a daily
    retry loop. Provider attempts remain independent from this deadline.
    """

    opening = next_transport_window(created_at)
    if opening is None:
        return None
    return opening + _EVT7_PRE_SEND_GRACE


def _evt7_pre_send_expired(row: object, *, now: dt.datetime) -> bool:
    if getattr(row, "purpose", None) != "agenda_evt7":
        return False
    deadline = _evt7_pre_send_deadline(getattr(row, "created_at", None))
    return deadline is None or now > deadline


def _pre_send_retry_allowed(row: object, *, due_at: dt.datetime) -> bool:
    """Keep source/context deferrals inside durable purpose-specific bounds."""

    if getattr(row, "purpose", None) != "agenda_evt7":
        return True
    deadline = _evt7_pre_send_deadline(getattr(row, "created_at", None))
    return deadline is not None and due_at <= deadline


def _retry_is_proven_before_send(result: object) -> bool:
    return (
        getattr(result, "status", None) == "falhou_retentavel"
        and type(getattr(result, "error_class", None)) is str
        and getattr(result, "error_class") in _PROVEN_PRE_SEND_ERRORS
    )


def result_transition(
    result: object,
    *,
    attempts: object,
    now: object,
) -> NotificationResultTransition:
    """Classify one provider result without retrying an uncertain send."""

    current = _utc_datetime(now)
    if current is None or type(attempts) is not int or not 0 <= attempts <= 2:
        raise ValueError("estado de notificação inválido")
    status = getattr(result, "status", None)
    if status == "aceito":
        return NotificationResultTransition("enviado", attempts, None, None)
    if status == "suprimido":
        return NotificationResultTransition("cancelado", attempts, None, "envio_suprimido")
    if status == "falhou_permanente":
        return NotificationResultTransition("cancelado", attempts, None, "falha_permanente")
    if not _retry_is_proven_before_send(result):
        return NotificationResultTransition("ambiguo", attempts, None, "resultado_ambiguo")
    if attempts >= len(_RETRY_DELAYS):
        return NotificationResultTransition("cancelado", attempts, None, "retries_esgotados")
    next_attempt = attempts + 1
    delay = _RETRY_DELAYS[next_attempt - 1]
    return NotificationResultTransition("retry", next_attempt, current + delay, None)


def _enabled_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def agenda_delivery_enabled(igreja_id: object) -> bool:
    """Check only Agenda's release and autonomous-notification gates.

    Tenant state, S3, consent, AgentConfig and provider readiness are rechecked
    by the dispatcher while it owns a durable lease.
    """

    if not _enabled_bool("AGENDA_NOTIFY_ENABLED"):
        return False
    from app.services.whatsapp_agenda import agenda_enabled_from_environment

    return agenda_enabled_from_environment(igreja_id)


def _valid_uuid(value: object) -> uuid.UUID | None:
    return value if type(value) is uuid.UUID and value.int else None


def _destination_fingerprint(context: tuple[str, str] | None) -> str | None:
    """Keep only a transient digest across the claim and its final fence."""

    if context is None:
        return None
    instance, phone = context
    if type(instance) is not str or type(phone) is not str:
        return None
    return hashlib.sha256(f"{instance}\x00{phone}".encode("utf-8")).hexdigest()


def _event_fingerprint(event: object) -> str | None:
    """Hash the mutable event projection without retaining its content."""

    event_id = _valid_uuid(getattr(event, "id", None))
    if event_id is None:
        return None
    confirmed_at = _utc_datetime(getattr(event, "confirmado_em", None))
    notification_at = _utc_datetime(getattr(event, "notificar_em", None))
    event_date = getattr(event, "data", None)
    payload = {
        "id": str(event_id),
        "status": getattr(event, "status", None),
        "confirmed_at": confirmed_at.isoformat() if confirmed_at is not None else None,
        "confirmed_by": str(getattr(event, "confirmado_por", None)),
        "data": event_date.isoformat() if type(event_date) is dt.date else None,
        "hora": getattr(event, "hora", None),
        "titulo": getattr(event, "titulo", None),
        "tipo": getattr(event, "tipo", None),
        "origem": getattr(event, "origem", None),
        "recorrencia": getattr(event, "recorrencia", None),
        "dia_semana": getattr(event, "dia_semana", None),
        "publico": getattr(event, "publico_alvo", None),
        "antecedencia": getattr(event, "antecedencia_horas", None),
        "notificar_em": notification_at.isoformat() if notification_at is not None else None,
    }
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _current_consent_allows(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    now: dt.datetime,
) -> bool:
    """Reuse V1a's terminal consent interpretation for every outbox purpose."""

    from app.config import get_settings
    from app.db.models import ConsentRecord
    from app.services.cell_report_whatsapp import LgpdConsentRecord, current_v1a_lgpd_acceptance

    current_term = getattr(get_settings(), "agent_term_version", None)
    records = tuple(
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
    return current_v1a_lgpd_acceptance(
        records, current_term=current_term, now=now
    ) is not None


def _agenda_preference_allows(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    now: dt.datetime,
) -> bool:
    """Require the confirmed versioned Agenda preference, never a phone."""

    from app.config import get_settings
    from app.db.models import WhatsappReminderPreference

    preference = session.execute(
        select(WhatsappReminderPreference).where(
            WhatsappReminderPreference.igreja_id == igreja_id,
            WhatsappReminderPreference.pessoa_id == pessoa_id,
            WhatsappReminderPreference.reminder_kind == "agenda",
        )
    ).scalar_one_or_none()
    term = getattr(get_settings(), "agent_term_version", None)
    accepted_at = _utc_datetime(getattr(preference, "accepted_at", None))
    return bool(
        preference is not None
        and preference.state == "active"
        and type(term) is str
        and bool(term)
        and preference.term_version == term
        and accepted_at is not None
        and accepted_at <= now
    )


def _agenda_audience_allows(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    event_id: uuid.UUID,
    pessoa_id: uuid.UUID,
) -> bool:
    """Recompute the current EVT-8 audience for a reminder recipient.

    A confirmed S3 subscription is not a permanent audience grant.  The event
    resolver remains the source of truth for individual targets, collective
    roles and active cell leadership, so a later role or audience change is
    observed at both subscription time and the transport fence.
    """

    from app.services.event_recipients import resolve_event_notification_recipients

    audience = resolve_event_notification_recipients(session, event_id, igreja_id)
    return any(
        getattr(recipient, "pessoa_id", None) == str(pessoa_id)
        for recipient in audience.recipients
    )


def _agenda_reminder_due_at(
    event: object,
    *,
    occurrence_at: dt.datetime,
    now: dt.datetime,
) -> dt.datetime | None:
    """Use the approved Event schedule and never invent a catch-up deadline."""

    antecedence = getattr(event, "antecedencia_horas", None)
    valid_antecedence = (
        type(antecedence) is int
        and not isinstance(antecedence, bool)
        and antecedence >= 0
    )
    if getattr(event, "recorrencia", None) == "semanal":
        if valid_antecedence:
            # ``notificar_em`` records the first materialized occurrence. A
            # weekly subscription must instead retain its own relative slot.
            due_at = occurrence_at - dt.timedelta(hours=antecedence)
        else:
            # With no reviewed relative interval, an absolute timestamp cannot
            # establish a later weekly occurrence safely. It remains usable
            # only for the source's dated first occurrence.
            local_occurrence = occurrence_at.astimezone(SAO_PAULO_TZ).date()
            if getattr(event, "data", None) != local_occurrence:
                return None
            due_at = _utc_datetime(getattr(event, "notificar_em", None))
    else:
        due_at = _utc_datetime(getattr(event, "notificar_em", None))
        if due_at is None and valid_antecedence:
            due_at = occurrence_at - dt.timedelta(hours=antecedence)
    if due_at is None:
        return None
    if due_at < now or due_at >= occurrence_at:
        return None
    return due_at


def execute_agenda_reminder_subscription(session: Session, execution: object):
    """Turn one confirmed S3 Agenda offer into a durable, future-only intent.

    This is an in-transaction domain effect.  It neither commits nor reaches a
    provider; the generic S3 resolver persists its receipt in the same caller
    transaction and the shared dispatcher later owns transport.
    """

    from app.config import get_settings
    from app.db.models import (
        AgendaReminderSubscription,
        Event,
        NotificationOutbox,
        WhatsappReminderPreference,
    )
    from app.services.agent_action_proposals import (
        ActionEffect,
        AgentAction,
        ProposalContractError,
        ProposalExecutionDenied,
        ProposalTarget,
        canonical_action_arguments,
    )
    from app.services.whatsapp_agenda import agenda_read_allowed

    def deny() -> None:
        raise ProposalExecutionDenied("domain_denied")

    tenant = _valid_uuid(getattr(execution, "igreja_id", None))
    proposal_id = _valid_uuid(getattr(execution, "proposal_id", None))
    context = getattr(execution, "privilege_context", None)
    target = getattr(execution, "target", None)
    action = getattr(execution, "action", None)
    if (
        tenant is None
        or proposal_id is None
        or type(target) is not ProposalTarget
        or action is not AgentAction.CONFIGURAR_LEMBRETE_AGENDA
        or getattr(context, "igreja_id", None) != tenant
        or not agenda_read_allowed(context)
        or not agenda_delivery_enabled(tenant)
    ):
        deny()
    try:
        arguments = canonical_action_arguments(
            AgentAction.CONFIGURAR_LEMBRETE_AGENDA,
            target,
            getattr(execution, "arguments", None),
        )
        event_id = uuid.UUID(arguments["event_id"])
        occurrence_at = _utc_datetime(dt.datetime.fromisoformat(arguments["occurrence_at"]))
    except (ProposalContractError, TypeError, ValueError):
        deny()
    if occurrence_at is None or target.id != event_id:
        deny()
    term_version = arguments["term_version"]
    if term_version != getattr(get_settings(), "agent_term_version", None):
        deny()
    pessoa_id = _valid_uuid(getattr(context, "pessoa_id", None))
    if pessoa_id is None:
        deny()
    current = _worker_now(None)
    if occurrence_at <= current:
        deny()

    _scoped(session, tenant, "agenda_reminder_subscription")
    pessoa, conversations = _lock_notification_recipient_prefix(
        session, igreja_id=tenant, pessoa_id=pessoa_id
    )
    if (
        pessoa is None
        or getattr(pessoa, "arquivada_em", None) is not None
        or getattr(pessoa, "optout", None) is True
        or getattr(pessoa, "sem_interesse", None) is True
        or any(
            getattr(conversation, "estado", None) == "humano"
            or getattr(conversation, "assumido_por", None) is not None
            for conversation in conversations
        )
    ):
        deny()

    # Confirmation transitions lock Event before they resolve recipients.  This
    # S3 path already owns Conversation -> Pessoa, so it must defer instead of
    # waiting and creating an Event <-> Pessoa deadlock.
    event = session.execute(
        select(Event)
        .where(Event.igreja_id == tenant, Event.id == event_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if (
        event is None
        or getattr(event, "status", None) != "confirmado"
        or _valid_uuid(getattr(event, "igreja_id", None)) != tenant
        or not _event_occurrence_matches(
            type("AgendaOccurrenceIntent", (), {
                "purpose": "agenda_reminder", "occurrence_at": occurrence_at
            })(),
            event,
        )
        or not _current_consent_allows(
            session, igreja_id=tenant, pessoa_id=pessoa_id, now=current
        )
        or not _agenda_audience_allows(
            session, igreja_id=tenant, event_id=event_id, pessoa_id=pessoa_id
        )
    ):
        deny()
    due_at = _agenda_reminder_due_at(event, occurrence_at=occurrence_at, now=current)
    fingerprint = _event_fingerprint(event)
    if due_at is None or fingerprint is None:
        deny()

    existing_subscription = session.execute(
        select(AgendaReminderSubscription)
        .where(
            AgendaReminderSubscription.igreja_id == tenant,
            AgendaReminderSubscription.pessoa_id == pessoa_id,
            AgendaReminderSubscription.event_id == event_id,
            AgendaReminderSubscription.occurrence_at == occurrence_at,
        )
        .with_for_update()
    ).scalar_one_or_none()
    existing_notification = session.execute(
        select(NotificationOutbox)
        .where(
            NotificationOutbox.igreja_id == tenant,
            NotificationOutbox.pessoa_id == pessoa_id,
            NotificationOutbox.origin_kind == "event",
            NotificationOutbox.origin_id == event_id,
            NotificationOutbox.occurrence_at == occurrence_at,
            NotificationOutbox.purpose == "agenda_reminder",
        )
        .with_for_update()
    ).scalar_one_or_none()
    # A new S3 confirmation must select a later occurrence after a refusal or
    # ambiguity.  Terminal work is never reopened under the unique outbox key.
    if existing_subscription is not None or existing_notification is not None:
        deny()

    preference = session.execute(
        select(WhatsappReminderPreference)
        .where(
            WhatsappReminderPreference.igreja_id == tenant,
            WhatsappReminderPreference.pessoa_id == pessoa_id,
            WhatsappReminderPreference.reminder_kind == "agenda",
        )
        .with_for_update()
    ).scalar_one_or_none()
    if preference is None:
        preference = WhatsappReminderPreference(
            igreja_id=tenant,
            pessoa_id=pessoa_id,
            reminder_kind="agenda",
            state="active",
            term_version=term_version,
            accepted_at=current,
            changed_at=current,
        )
        session.add(preference)
    else:
        preference.state = "active"
        preference.term_version = term_version
        preference.accepted_at = current
        preference.changed_at = current

    subscription = AgendaReminderSubscription(
        igreja_id=tenant,
        pessoa_id=pessoa_id,
        event_id=event_id,
        occurrence_at=occurrence_at,
        proposal_id=proposal_id,
        state="active",
        term_version=term_version,
        confirmed_at=current,
        updated_at=current,
    )
    session.add(subscription)
    session.flush()
    subscription_id = _valid_uuid(getattr(subscription, "id", None))
    if subscription_id is None:
        raise ProposalContractError("inscrição persistida inválida")
    session.add(
        NotificationOutbox(
            igreja_id=tenant,
            pessoa_id=pessoa_id,
            agenda_alert_recipient_id=None,
            event_id=event_id,
            reuniao_id=None,
            agenda_subscription_id=subscription_id,
            origin_kind="event",
            origin_id=event_id,
            occurrence_at=occurrence_at,
            origin_fingerprint=fingerprint,
            purpose="agenda_reminder",
            state="pendente",
            due_at=due_at,
            delivery_reservation_day=None,
            claim_token=None,
            claimed_until=None,
            claimed_by=None,
            attempts=0,
            transport_started_at=None,
            sent_at=None,
            terminal_reason=None,
            created_at=current,
            updated_at=current,
        )
    )
    return ActionEffect(
        receipt_text="Lembrete confirmado.", opaque_effect_id=subscription_id
    )


@dataclass(frozen=True, slots=True)
class _Evt7Recipient:
    id: uuid.UUID | None
    pessoa_id: uuid.UUID


def _eligible_evt7_recipients(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    now: dt.datetime,
) -> tuple[_Evt7Recipient, ...]:
    """Resolve only linked, current, consented EVT-7 targets.

    A legacy phone-only configuration is deliberately ineligible.  The admin
    API writes the server-managed Pessoa link after resolving phone aliases;
    this transaction takes the same Conversation -> Pessoa prefix as PARAR and
    SAIR before it reads consent and preference or appends an outbox row.
    """

    from app.db.models import AgendaAlertRecipient, Pessoa
    from app.domain.phone import normalize_phone

    recipients = tuple(
        session.execute(
            select(AgendaAlertRecipient)
            .where(
                AgendaAlertRecipient.igreja_id == igreja_id,
                AgendaAlertRecipient.ativo.is_(True),
            )
            .order_by(AgendaAlertRecipient.id.asc())
        ).scalars().all()
    )
    people = tuple(
        session.execute(
            select(Pessoa)
            .where(
                Pessoa.igreja_id == igreja_id,
                Pessoa.arquivada_em.is_(None),
            )
            .order_by(Pessoa.id.asc())
        ).scalars().all()
    )
    eligible: list[_Evt7Recipient] = []
    seen_people: set[uuid.UUID] = set()
    for recipient in recipients:
        recipient_id = _valid_uuid(getattr(recipient, "id", None))
        linked_pessoa_id = _valid_uuid(getattr(recipient, "pessoa_id", None))
        phone = normalize_phone(getattr(recipient, "telefone", "") or "")
        if recipient_id is None or linked_pessoa_id is None or not phone:
            continue
        matches = tuple(
            person
            for person in people
            if getattr(person, "igreja_id", None) == igreja_id
            and getattr(person, "arquivada_em", None) is None
            and normalize_phone(getattr(person, "telefone", "") or "") == phone
        )
        if len(matches) != 1 or _valid_uuid(getattr(matches[0], "id", None)) != linked_pessoa_id:
            continue
        person, _conversations = _lock_notification_recipient_prefix(
            session, igreja_id=igreja_id, pessoa_id=linked_pessoa_id
        )
        pessoa_id = _valid_uuid(getattr(person, "id", None))
        if (
            pessoa_id is None
            or pessoa_id != linked_pessoa_id
            or getattr(person, "igreja_id", None) != igreja_id
            or getattr(person, "arquivada_em", None) is not None
            or normalize_phone(getattr(person, "telefone", "") or "") != phone
            or recipient_id is None
            or pessoa_id in seen_people
            or getattr(person, "optout", None) is True
            or getattr(person, "sem_interesse", None) is True
            or not _current_consent_allows(
                session, igreja_id=igreja_id, pessoa_id=pessoa_id, now=now
            )
            or not _agenda_preference_allows(
                session, igreja_id=igreja_id, pessoa_id=pessoa_id, now=now
            )
        ):
            continue
        seen_people.add(pessoa_id)
        eligible.append(_Evt7Recipient(id=recipient_id, pessoa_id=pessoa_id))
    return tuple(eligible)


def enqueue_evt7_for_confirmed_event(
    session: Session,
    event: object,
    *,
    now: dt.datetime | None = None,
) -> int:
    """Append EVT-7 intentions in the event-confirmation transaction.

    It does not flush, commit, construct a recipient phone or invoke a provider.
    A caller rollback therefore removes the confirmation and all intentions.
    """

    from app.db.models import NotificationOutbox

    current = _utc_datetime(now or dt.datetime.now(_UTC))
    event_id = _valid_uuid(getattr(event, "id", None))
    igreja_id = _valid_uuid(getattr(event, "igreja_id", None))
    confirmed_at = _utc_datetime(getattr(event, "confirmado_em", None))
    if (
        current is None
        or event_id is None
        or igreja_id is None
        or getattr(event, "status", None) != "confirmado"
        or confirmed_at is None
        or getattr(event, "notification_outbox_fenced_at", None) is not None
        or not agenda_delivery_enabled(igreja_id)
    ):
        return 0
    fingerprint = _event_fingerprint(event)
    due_at = next_transport_window(current)
    if fingerprint is None or due_at is None:
        return 0
    created = 0
    seen_people: set[uuid.UUID] = set()
    for recipient in _eligible_evt7_recipients(session, igreja_id=igreja_id, now=current):
        pessoa_id = _valid_uuid(getattr(recipient, "pessoa_id", None))
        recipient_id = _valid_uuid(getattr(recipient, "id", None))
        if pessoa_id is None or recipient_id is None or pessoa_id in seen_people:
            continue
        seen_people.add(pessoa_id)
        session.add(
            NotificationOutbox(
                igreja_id=igreja_id,
                pessoa_id=pessoa_id,
                agenda_alert_recipient_id=recipient_id,
                event_id=event_id,
                reuniao_id=None,
                agenda_subscription_id=None,
                origin_kind="event",
                origin_id=event_id,
                occurrence_at=confirmed_at,
                origin_fingerprint=fingerprint,
                purpose="agenda_evt7",
                state="pendente",
                due_at=due_at,
                claim_token=None,
                claimed_until=None,
                claimed_by=None,
                attempts=0,
                transport_started_at=None,
                sent_at=None,
                terminal_reason=None,
                delivery_reservation_day=None,
                created_at=current,
                updated_at=current,
            )
        )
        created += 1
    return created


def _worker_now(value: dt.datetime | None) -> dt.datetime:
    current = _utc_datetime(value or dt.datetime.now(_UTC))
    if current is None:
        raise ValueError("horário de dispatcher inválido")
    return current


def _discover_notification_tenants(
    session_factory: Callable[[], Session],
) -> tuple[uuid.UUID, ...]:
    """Return only tenant IDs that already own a durable V2b row."""

    from app.db.models import NotificationOutbox
    from app.db.tenant_session import mark_cross_tenant

    session = session_factory()
    try:
        mark_cross_tenant(session, source="notification_outbox_discovery")
        rows = session.execute(
            select(NotificationOutbox.igreja_id).distinct().order_by(NotificationOutbox.igreja_id)
        ).scalars()
        return tuple(value for value in rows if _valid_uuid(value) is not None)
    finally:
        session.close()


def maintain_notification_outbox(
    session_factory: Callable[[], Session],
    *,
    igreja_id: uuid.UUID,
    now: dt.datetime,
    limit: int = 100,
) -> int:
    """Run non-transport maintenance before a tenant dispatch scan.

    The concrete sweeps live below the claim seam so every mutation follows the
    same Conversation, Pessoa, source, outbox lock order. Keeping this callable
    separate lets cron run maintenance while every release gate is closed.
    """

    return _maintain_notification_tenant(
        session_factory, igreja_id=igreja_id, now=now, limit=limit
    )


def dispatch_notification_outbox(
    session_factory: Callable[[], Session],
    evolution_client: object,
    *,
    worker_id: str,
    now: dt.datetime | None = None,
    limit: int = 20,
    lease_seconds: int = 30,
) -> int:
    """Dispatch all V2b purposes through one claim/fence/result lifecycle.

    A provider is reached only after the claim transaction and the fresh
    revalidation fence transaction have both committed. Any raised provider
    exception is recorded as ambiguous by the same durable row.
    """

    if type(worker_id) is not str or not worker_id.strip():
        raise ValueError("worker de notificação inválido")
    if type(limit) is not int or limit <= 0 or type(lease_seconds) is not int or lease_seconds <= 0:
        raise ValueError("limite de notificação inválido")
    fixed_now = _worker_now(now) if now is not None else None

    def current_time() -> dt.datetime:
        return fixed_now if fixed_now is not None else _worker_now(None)

    sent = 0
    scanned = 0
    for igreja_id in _discover_notification_tenants(session_factory):
        if scanned >= limit:
            break
        current = current_time()
        maintain_notification_outbox(
            session_factory, igreja_id=igreja_id, now=current, limit=max(1, limit)
        )
        excluded: set[uuid.UUID] = set()
        while scanned < limit:
            claim = _claim_next_notification(
                session_factory,
                igreja_id=igreja_id,
                now=current_time(),
                lease_seconds=lease_seconds,
                worker_id=worker_id,
                excluded_ids=tuple(sorted(excluded, key=str)),
            )
            if claim is None:
                break
            scanned += 1
            excluded.add(claim.outbox_id)
            try:
                transport = _renew_notification_transport_fence(
                    session_factory,
                    claim,
                    now=current_time(),
                    lease_seconds=lease_seconds,
                )
            except Exception:  # noqa: BLE001 - never call provider without a fence
                logger.exception("Notification transport fence failed")
                continue
            if transport is None:
                continue
            try:
                result = evolution_client.send_text_classificado(
                    transport.instance,
                    transport.phone,
                    transport.text,
                )
            except Exception:  # noqa: BLE001 - a provider boundary may be crossed
                from app.services.evolution import BroadcastSendResult

                result = BroadcastSendResult(
                    status="desconhecido", error_class="erro_nao_classificado"
                )
            try:
                _record_notification_result(
                    session_factory,
                    transport.claim,
                    result=result,
                    now=current_time(),
                )
            except Exception:  # noqa: BLE001 - leave the committed lease ambiguous
                logger.exception("Notification result recording failed")
                continue
            sent += 1
    return sent


_PENDING_STATES = ("pendente", "retry")
_QUOTA_RESERVING_STATES = frozenset(
    {"pendente", "retry", "em_envio", "enviado", "ambiguo", "obsoleto"}
)
_AGENDA_PURPOSES = frozenset({"agenda_reminder", "agenda_evt7"})


def _scoped(session: Session, igreja_id: uuid.UUID, source: str) -> None:
    from app.db.rls_observability import require_tenant_scope
    from app.db.tenant_session import mark_tenant_scoped

    mark_tenant_scoped(session, igreja_id, source=source)
    require_tenant_scope(session, expected_igreja_id=igreja_id, source=source)


def disable_whatsapp_reminders(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    conversation_id: uuid.UUID | None = None,
    now: dt.datetime | None = None,
) -> bool:
    """Persist one global reminder refusal and fence all common work.

    The caller keeps ownership of the enclosing transaction.  This takes the
    shared sorted Conversation -> Pessoa lock prefix before it reads or mutates
    a preference, subscription, or outbox row, so PARAR and SAIR serialize with
    enqueue, claim and the final provider fence.  A lease that may already have
    reached transport becomes ambiguous instead of becoming eligible again.
    """

    from app.db.models import (
        AgendaReminderSubscription,
        AgentActionProposal,
        NotificationOutbox,
        WhatsappReminderPreference,
    )
    from app.services.cell_report_reminders import disable_cell_report_reminders

    tenant = _valid_uuid(igreja_id)
    person_id = _valid_uuid(pessoa_id)
    conversation = _valid_uuid(conversation_id) if conversation_id is not None else None
    if tenant is None or person_id is None or (
        conversation_id is not None and conversation is None
    ):
        raise ValueError("identificador de lembrete inválido")
    current = _worker_now(now)
    _scoped(session, tenant, "notification_outbox_reminder_stop")
    pessoa, conversations = _lock_notification_recipient_prefix(
        session, igreja_id=tenant, pessoa_id=person_id
    )
    if pessoa is None:
        return False
    if conversation is not None and not any(
        getattr(item, "id", None) == conversation for item in conversations
    ):
        return False

    existing = {
        getattr(row, "reminder_kind", None): row
        for row in session.execute(
            select(WhatsappReminderPreference)
            .where(
                WhatsappReminderPreference.igreja_id == tenant,
                WhatsappReminderPreference.pessoa_id == person_id,
                WhatsappReminderPreference.reminder_kind.in_(("agenda", "cell_report")),
            )
            .order_by(WhatsappReminderPreference.reminder_kind.asc())
            .with_for_update()
        ).scalars()
    }
    changed = False
    for reminder_kind in ("agenda", "cell_report"):
        preference = existing.get(reminder_kind)
        if preference is None:
            session.add(
                WhatsappReminderPreference(
                    igreja_id=tenant,
                    pessoa_id=person_id,
                    reminder_kind=reminder_kind,
                    state="disabled",
                    term_version=None,
                    accepted_at=None,
                    changed_at=current,
                )
            )
            changed = True
        elif getattr(preference, "state", None) != "disabled":
            preference.state = "disabled"
            preference.changed_at = current
            changed = True

    for subscription in session.execute(
        select(AgendaReminderSubscription)
        .where(
            AgendaReminderSubscription.igreja_id == tenant,
            AgendaReminderSubscription.pessoa_id == person_id,
            AgendaReminderSubscription.state == "active",
        )
        .with_for_update()
    ).scalars():
        subscription.state = "cancelled"
        subscription.updated_at = current
        changed = True

    # A delivered S3 reminder offer is still an unexecuted capability. Fence
    # only this Agenda action for the same person, while the shared recipient
    # lock is held, so a later SIM cannot recreate a preference, subscription
    # or outbox row after PARAR LEMBRETES. Other sensitive S3 actions remain
    # untouched because their user control has a different contract.
    cancelled_proposals = session.execute(
        update(AgentActionProposal)
        .where(
            AgentActionProposal.igreja_id == tenant,
            AgentActionProposal.actor_pessoa_id == person_id,
            AgentActionProposal.action == "configurar_lembrete_agenda",
            AgentActionProposal.state.in_(("preparada", "pendente")),
        )
        .values(
            state="cancelada",
            terminal_reason="lembretes_recusados",
            expires_at=None,
        )
    )
    changed = bool(getattr(cancelled_proposals, "rowcount", 0)) or changed

    cancelled = session.execute(
        update(NotificationOutbox)
        .where(
            NotificationOutbox.igreja_id == tenant,
            NotificationOutbox.pessoa_id == person_id,
            NotificationOutbox.state.in_(_PENDING_STATES),
        )
        .values(
            state="cancelado",
            claim_token=None,
            claimed_until=None,
            claimed_by=None,
            terminal_reason="lembretes_recusados",
            updated_at=current,
        )
    )
    ambiguous = session.execute(
        update(NotificationOutbox)
        .where(
            NotificationOutbox.igreja_id == tenant,
            NotificationOutbox.pessoa_id == person_id,
            NotificationOutbox.state == "em_envio",
        )
        .values(
            state="ambiguo",
            claim_token=None,
            claimed_until=None,
            claimed_by=None,
            terminal_reason="lembretes_recusados_em_envio",
            updated_at=current,
        )
    )
    changed = bool(getattr(cancelled, "rowcount", 0) or getattr(ambiguous, "rowcount", 0)) or changed

    # V1a historical rows remain durable through cutover.  Its legacy marker
    # is deliberately preserved, while `_cell_report_preference_allows` treats
    # the versioned common preference as canonical after a future S3 acceptance.
    disable_cell_report_reminders(
        session,
        igreja_id=tenant,
        conversation_id=conversation,
        pessoa_id=person_id,
        now=current,
    )
    # A valid repeated refusal is still a handled inbound command.  Returning
    # `changed` here would make the second PARAR LEMBRETES look like a missing
    # conversation, even though all durable state is correctly fenced.
    return True


def _lock_notification_recipient_prefix(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
) -> tuple[object | None, tuple[object, ...]]:
    """Reuse V1a's Conversation -> Pessoa lock prefix for every purpose."""

    from app.services.cell_report_reminders import _lock_reminder_recipient_prefix

    return _lock_reminder_recipient_prefix(
        session, igreja_id=igreja_id, pessoa_id=pessoa_id
    )


def _clear_claim(row: object) -> None:
    row.claim_token = None
    row.claimed_until = None
    row.claimed_by = None


def _terminalize(
    row: object,
    *,
    state: str,
    reason: str,
    now: dt.datetime,
) -> None:
    """Only turn non-terminal work into a terminal, non-reopenable state."""

    if getattr(row, "state", None) in {"enviado", "ambiguo", "cancelado", "obsoleto", "fenced"}:
        return
    row.state = state
    row.terminal_reason = reason
    _clear_claim(row)
    row.updated_at = now


def _purpose_gate_allows(purpose: object, igreja_id: uuid.UUID) -> bool:
    from app.config import get_settings
    from app.services.cell_report_whatsapp import cell_report_enabled_from_environment
    from app.services.outbound_guard import external_sends_allowed

    settings = get_settings()
    if not external_sends_allowed(settings) or not settings.whatsapp_piloto(igreja_id):
        return False
    if purpose in _AGENDA_PURPOSES:
        return agenda_delivery_enabled(igreja_id)
    if purpose == "cell_report_reminder":
        return cell_report_enabled_from_environment(igreja_id)
    return False


def _agenda_quota_rank(
    session: Session,
    *,
    row: object,
    now: dt.datetime,
) -> tuple[int, dt.date] | None:
    """Count one Agenda transport slot while Pessoa is locked.

    The cap is about the São Paulo day on which transport starts, never an
    event's occurrence date or insertion order.  Every established reservation
    on that day counts before a candidate, including a source that was later
    removed and an ambiguous result.  Only a row already classified as a
    proven pre-send retry may move to a later day.  The caller persists the
    returned day with its final transition, after all source reads, so this
    calculation never causes an intermediate autoflush.
    """

    from app.db.models import NotificationOutbox

    target_day = now.astimezone(SAO_PAULO_TZ).date()
    prior_day = getattr(row, "delivery_reservation_day", None)
    if prior_day is None:
        candidate_already_counted = False
    elif prior_day != target_day:
        # `retry` is only emitted by `result_transition` for an explicitly
        # classified pre-send failure.  A live lease, sent receipt or ambiguity
        # never crosses a day and therefore never opens a new slot.
        if getattr(row, "state", None) != "retry":
            return None
        candidate_already_counted = False
    else:
        candidate_already_counted = True

    rows = tuple(
        session.execute(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.igreja_id == row.igreja_id,
                NotificationOutbox.pessoa_id == row.pessoa_id,
                NotificationOutbox.purpose.in_(tuple(sorted(_AGENDA_PURPOSES))),
                NotificationOutbox.delivery_reservation_day == target_day,
                NotificationOutbox.state.in_(tuple(sorted(_QUOTA_RESERVING_STATES))),
            )
        ).scalars()
    )
    rank = sum(1 for item in rows if getattr(item, "id", None) is not None)
    if not candidate_already_counted:
        rank += 1
    return rank, target_day


def _reschedule_outside_window(row: object, *, now: dt.datetime) -> bool:
    """Move a claim to the next opening, never past an Agenda occurrence."""

    due_at = next_transport_window(now)
    if due_at is None or not _pre_send_retry_allowed(row, due_at=due_at):
        _terminalize(row, state="cancelado", reason="pre_envio_expirado", now=now)
        return False
    occurrence = _utc_datetime(getattr(row, "occurrence_at", None))
    if getattr(row, "purpose", None) == "agenda_reminder" and (
        occurrence is None or due_at >= occurrence
    ):
        _terminalize(row, state="obsoleto", reason="janela_expirada", now=now)
        return False
    row.state = "pendente"
    row.due_at = due_at
    row.terminal_reason = None
    _clear_claim(row)
    row.updated_at = now
    return False


def _maintain_notification_tenant(
    session_factory: Callable[[], Session],
    *,
    igreja_id: uuid.UUID,
    now: dt.datetime,
    limit: int,
) -> int:
    """Fence expired leases and gate-closed pending work without transport."""

    from app.db.models import NotificationOutbox

    if limit <= 0:
        return 0
    session = session_factory()
    changed = 0
    try:
        _scoped(session, igreja_id, "notification_outbox_maintenance")
        candidates = tuple(
            session.execute(
                select(NotificationOutbox.id, NotificationOutbox.pessoa_id)
                .where(
                    NotificationOutbox.igreja_id == igreja_id,
                    (
                        (
                            NotificationOutbox.state == "em_envio"
                        )
                        & (NotificationOutbox.claimed_until.is_not(None))
                        & (NotificationOutbox.claimed_until <= now)
                    )
                    | NotificationOutbox.state.in_(_PENDING_STATES),
                )
                .order_by(NotificationOutbox.due_at.asc(), NotificationOutbox.id.asc())
                .limit(limit)
            ).all()
        )
        for row_id, pessoa_id in candidates:
            if _valid_uuid(row_id) is None or _valid_uuid(pessoa_id) is None:
                continue
            _lock_notification_recipient_prefix(
                session, igreja_id=igreja_id, pessoa_id=pessoa_id
            )
            row = session.execute(
                select(NotificationOutbox)
                .where(
                    NotificationOutbox.igreja_id == igreja_id,
                    NotificationOutbox.id == row_id,
                    NotificationOutbox.pessoa_id == pessoa_id,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if row is None:
                continue
            if (
                row.state == "em_envio"
                and row.claimed_until is not None
                and row.claimed_until <= now
            ):
                row.state = "ambiguo"
                row.terminal_reason = "lease_expirada"
                _clear_claim(row)
                row.updated_at = now
                changed += 1
                continue
            if row.state in _PENDING_STATES and not _purpose_gate_allows(
                row.purpose, igreja_id
            ):
                _terminalize(row, state="cancelado", reason="gate_fechado", now=now)
                changed += 1
        session.commit()
        return changed
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _claim_next_notification(
    session_factory: Callable[[], Session],
    *,
    igreja_id: uuid.UUID,
    now: dt.datetime,
    lease_seconds: int,
    worker_id: str,
    excluded_ids: tuple[uuid.UUID, ...] = (),
) -> NotificationClaim | None:
    """Commit one lease after the shared recipient lock prefix.

    The initial scan intentionally holds no outbox lock. Once a candidate is
    chosen, every path locks Conversations then Pessoa before it locks the row,
    matching inbound PARAR/SAIR and V1a maintenance.
    """

    from app.db.models import NotificationOutbox

    session = session_factory()
    try:
        _scoped(session, igreja_id, "notification_outbox_claim")
        statement = (
            select(NotificationOutbox.id, NotificationOutbox.pessoa_id)
            .where(
                NotificationOutbox.igreja_id == igreja_id,
                NotificationOutbox.state.in_(_PENDING_STATES),
                NotificationOutbox.due_at <= now,
            )
            .order_by(NotificationOutbox.due_at.asc(), NotificationOutbox.id.asc())
            .limit(100)
        )
        if excluded_ids:
            statement = statement.where(NotificationOutbox.id.not_in(excluded_ids))
        candidates = tuple(session.execute(statement).all())
        for row_id, pessoa_id in candidates:
            if _valid_uuid(row_id) is None or _valid_uuid(pessoa_id) is None:
                continue
            pessoa, _conversations = _lock_notification_recipient_prefix(
                session, igreja_id=igreja_id, pessoa_id=pessoa_id
            )
            row = session.execute(
                select(NotificationOutbox)
                .where(
                    NotificationOutbox.igreja_id == igreja_id,
                    NotificationOutbox.id == row_id,
                    NotificationOutbox.pessoa_id == pessoa_id,
                    NotificationOutbox.state.in_(_PENDING_STATES),
                    NotificationOutbox.due_at <= now,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if row is None:
                continue
            if pessoa is None:
                _terminalize(row, state="obsoleto", reason="pessoa_ausente", now=now)
                session.commit()
                continue
            if _evt7_pre_send_expired(row, now=now):
                _terminalize(row, state="cancelado", reason="pre_envio_expirado", now=now)
                session.commit()
                continue
            if not transport_window_open(now):
                _reschedule_outside_window(row, now=now)
                session.commit()
                continue
            reservation_day: dt.date | None = None
            if row.purpose in _AGENDA_PURPOSES:
                quota = _agenda_quota_rank(session, row=row, now=now)
                if quota is None:
                    _terminalize(row, state="obsoleto", reason="quota_invalida", now=now)
                    session.commit()
                    continue
                rank, reservation_day = quota
                if rank > 2:
                    row.delivery_reservation_day = reservation_day
                    _terminalize(row, state="cancelado", reason="limite_diario", now=now)
                    session.commit()
                    continue
            destination, _destination_reason = _recipient_transport_context(
                session,
                igreja_id=igreja_id,
                pessoa=pessoa,
                conversations=_conversations,
                purpose=row.purpose,
                now=now,
            )
            if reservation_day is not None:
                row.delivery_reservation_day = reservation_day
            token = uuid.uuid4()
            row.state = "em_envio"
            row.claim_token = token
            row.claimed_until = now + dt.timedelta(seconds=lease_seconds)
            row.claimed_by = worker_id
            row.terminal_reason = None
            row.updated_at = now
            session.commit()
            return NotificationClaim(
                igreja_id=igreja_id,
                outbox_id=row_id,
                pessoa_id=pessoa_id,
                claim_token=token,
                destination_fingerprint=_destination_fingerprint(destination),
            )
        session.rollback()
        return None
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _cell_report_preference_allows(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
) -> bool:
    """Keep V1a's legacy default while honoring the canonical stop record."""

    from app.db.models import CellReportReminderPreference, WhatsappReminderPreference

    preference = session.execute(
        select(WhatsappReminderPreference).where(
            WhatsappReminderPreference.igreja_id == igreja_id,
            WhatsappReminderPreference.pessoa_id == pessoa_id,
            WhatsappReminderPreference.reminder_kind == "cell_report",
        )
    ).scalar_one_or_none()
    # A versioned common preference becomes canonical when it exists.  Until
    # then, V1a's durable refusal remains effective through cutover.  This
    # preserves old PARAR records without preventing a separately confirmed,
    # explicit future activation from becoming authoritative.
    if preference is not None:
        return preference.state == "active"
    legacy_refusal = session.execute(
        select(CellReportReminderPreference.id).where(
            CellReportReminderPreference.igreja_id == igreja_id,
            CellReportReminderPreference.pessoa_id == pessoa_id,
        )
    ).scalar_one_or_none()
    return legacy_refusal is None


def _recipient_transport_context(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa: object | None,
    conversations: tuple[object, ...],
    purpose: object,
    now: dt.datetime,
) -> tuple[tuple[str, str] | None, str | None]:
    """Revalidate tenant, person, consent, preference and sender connection."""

    from app.db.models import AgentConfig, Igreja, LlmCredential, Pessoa, WhatsappConnection
    from app.deps import BLOCKING_IGREJA_STATUSES
    from app.domain.phone import normalize_phone

    pessoa_id = _valid_uuid(getattr(pessoa, "id", None))
    if (
        pessoa is None
        or pessoa_id is None
        or getattr(pessoa, "arquivada_em", None) is not None
        or getattr(pessoa, "optout", None) is True
        or getattr(pessoa, "sem_interesse", None) is True
    ):
        return None, "pessoa_revogada"
    if any(
        getattr(item, "estado", None) == "humano"
        or getattr(item, "assumido_por", None) is not None
        for item in conversations
    ):
        return None, "atendimento_humano"
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
    if (
        igreja is None
        or getattr(igreja, "status", None) in BLOCKING_IGREJA_STATUSES
        or config is None
        or getattr(config, "ativo", None) is not True
        or credential is None
        or getattr(credential, "ativo", None) is not True
        or getattr(credential, "validado", None) is not True
        or not _current_consent_allows(
            session, igreja_id=igreja_id, pessoa_id=pessoa_id, now=now
        )
    ):
        return None, "contexto_revogado"
    if purpose in _AGENDA_PURPOSES:
        preference_ok = _agenda_preference_allows(
            session, igreja_id=igreja_id, pessoa_id=pessoa_id, now=now
        )
    elif purpose == "cell_report_reminder":
        preference_ok = _cell_report_preference_allows(
            session, igreja_id=igreja_id, pessoa_id=pessoa_id
        )
    else:
        preference_ok = False
    if not preference_ok:
        return None, "lembretes_recusados"
    phone = normalize_phone(getattr(pessoa, "telefone", "") or "")
    if not phone:
        return None, "telefone_invalido"
    people = tuple(
        session.execute(
            select(Pessoa)
            .where(
                Pessoa.igreja_id == igreja_id,
                Pessoa.arquivada_em.is_(None),
            )
            .order_by(Pessoa.id.asc())
        ).scalars()
    )
    matches = tuple(
        item
        for item in people
        if normalize_phone(getattr(item, "telefone", "") or "") == phone
    )
    if len(matches) != 1 or getattr(matches[0], "id", None) != pessoa_id:
        return None, "telefone_ambiguo"
    connection = session.execute(
        select(WhatsappConnection)
        .where(WhatsappConnection.igreja_id == igreja_id)
        .with_for_update()
    ).scalar_one_or_none()
    instance = getattr(connection, "instance", None)
    if (
        connection is None
        or getattr(connection, "status", None) != "online"
        or type(instance) is not str
        or not instance.strip()
    ):
        return None, "instancia_indisponivel"
    return (instance, phone), None


def _meeting_fingerprint(meeting: object) -> str | None:
    meeting_id = _valid_uuid(getattr(meeting, "id", None))
    meeting_date = getattr(meeting, "data", None)
    if meeting_id is None or type(meeting_date) is not dt.date:
        return None
    payload = {
        "id": str(meeting_id),
        "data": meeting_date.isoformat(),
        "hora": getattr(meeting, "hora", None),
        "status": getattr(meeting, "status", None),
        "relatorio_status": getattr(meeting, "relatorio_status", None),
        "updated_at": (
            _utc_datetime(getattr(meeting, "updated_at", None)).isoformat()
            if _utc_datetime(getattr(meeting, "updated_at", None)) is not None
            else None
        ),
    }
    try:
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
    except (TypeError, ValueError):
        return None


def _safe_event_label(event: object) -> str:
    from app.services.whatsapp_agenda import project_institutional_title

    projected = project_institutional_title(getattr(event, "titulo", None))
    if projected is not None:
        return projected
    labels = {
        "culto": "Culto",
        "reuniao": "Reunião da igreja",
        "celula": "Encontro de célula",
        "especial": "Evento especial da igreja",
        "conferencia": "Conferência da igreja",
    }
    return labels.get(getattr(event, "tipo", None), "Evento da igreja")


def _agenda_evt7_text(event: object) -> str:
    return f"Agenda: {_safe_event_label(event)} foi confirmado.{_STOP_REMINDERS_NOTICE}"


def _agenda_reminder_text(event: object) -> str:
    return f"Lembrete da Agenda: {_safe_event_label(event)}.{_STOP_REMINDERS_NOTICE}"


def _event_occurrence_matches(row: object, event: object) -> bool:
    """Require the persisted Agenda occurrence to still be a real event slot."""

    if getattr(row, "purpose", None) != "agenda_reminder":
        return True
    occurrence = _utc_datetime(getattr(row, "occurrence_at", None))
    hour = getattr(event, "hora", None)
    if occurrence is None or type(hour) is not str:
        return False
    try:
        hour_value = dt.time.fromisoformat(hour)
    except ValueError:
        return False
    local = occurrence.astimezone(SAO_PAULO_TZ)
    if local.time().replace(tzinfo=None) != hour_value:
        return False
    if getattr(event, "recorrencia", None) == "pontual":
        return getattr(event, "data", None) == local.date()
    if getattr(event, "recorrencia", None) != "semanal":
        return False
    weekday = getattr(event, "dia_semana", None)
    return (
        type(weekday) is int
        and 0 <= weekday <= 6
        and (local.date().weekday() + 1) % 7 == weekday
    )


def _discover_cell_report_schedule_tenants(
    session_factory: Callable[[], Session],
) -> tuple[uuid.UUID, ...]:
    """Reuse V1a's bounded tenant discovery without its transport path."""

    from app.services.cell_report_reminders import _discover_tenants

    return _discover_tenants(
        session_factory, source="notification_outbox_cell_report_schedule_discovery"
    )


def _schedule_cell_report_tenant(
    session_factory: Callable[[], Session],
    *,
    igreja_id: uuid.UUID,
    now: dt.datetime,
    limit: int,
) -> int:
    """Append V1a intentions to the common outbox, never a legacy queue."""

    from sqlalchemy.exc import IntegrityError

    from app.db.models import CellReportReminder, Celula, CelulaReuniao, NotificationOutbox
    from app.services.cell_report_application import (
        CellReportApplicationError,
        revalidate_cell_report_leader,
    )
    from app.services.cell_report_reminders import (
        cell_report_reminder_due_at,
        cell_report_reminder_is_obsolete,
    )

    if limit <= 0 or not _purpose_gate_allows("cell_report_reminder", igreja_id):
        return 0
    session = session_factory()
    try:
        _scoped(session, igreja_id, "notification_outbox_cell_report_schedule")
        candidates = tuple(
            session.execute(
                select(CelulaReuniao.id, Celula.lider_id)
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
                .limit(limit * 4)
            ).all()
        )
        created = 0
        for meeting_id, pessoa_id in candidates:
            if created >= limit:
                break
            if _valid_uuid(meeting_id) is None or _valid_uuid(pessoa_id) is None:
                continue
            pessoa, conversations = _lock_notification_recipient_prefix(
                session, igreja_id=igreja_id, pessoa_id=pessoa_id
            )
            meeting = session.execute(
                select(CelulaReuniao)
                .where(
                    CelulaReuniao.igreja_id == igreja_id,
                    CelulaReuniao.id == meeting_id,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if meeting is None:
                continue
            cell = session.execute(
                select(Celula)
                .where(
                    Celula.igreja_id == igreja_id,
                    Celula.id == meeting.celula_id,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if (
                cell is None
                or getattr(cell, "ativo", None) is not True
                or getattr(cell, "lider_id", None) != pessoa_id
                or getattr(meeting, "relatorio_status", None) != "pendente"
                or getattr(meeting, "status", None) == "cancelada"
                or cell_report_reminder_is_obsolete(
                    getattr(meeting, "data", None), getattr(meeting, "hora", None), now
                )
            ):
                continue
            due_at = cell_report_reminder_due_at(
                getattr(meeting, "data", None), getattr(meeting, "hora", None)
            )
            if due_at is None or due_at > now:
                continue
            context, _reason = _recipient_transport_context(
                session,
                igreja_id=igreja_id,
                pessoa=pessoa,
                conversations=conversations,
                purpose="cell_report_reminder",
                now=now,
            )
            if context is None:
                continue
            try:
                revalidate_cell_report_leader(
                    session,
                    igreja_id=igreja_id,
                    meeting=meeting,
                    ator_pessoa_id=pessoa_id,
                )
            except CellReportApplicationError:
                continue
            fingerprint = _meeting_fingerprint(meeting)
            if fingerprint is None:
                continue
            # A cell meeting is a one-time source.  Any terminal/ambiguous
            # historical row blocks an edited source from being rescheduled as
            # a supposedly new occurrence.
            existing = session.execute(
                select(NotificationOutbox.id)
                .where(
                    NotificationOutbox.igreja_id == igreja_id,
                    NotificationOutbox.pessoa_id == pessoa_id,
                    NotificationOutbox.origin_kind == "meeting",
                    NotificationOutbox.origin_id == meeting_id,
                    NotificationOutbox.purpose == "cell_report_reminder",
                )
                .limit(1)
            ).scalar_one_or_none()
            if existing is not None:
                continue
            # Cutover deliberately leaves the legacy V1a rows in place. Any
            # row for this exact meeting/leader is terminal for scheduling,
            # regardless of its state, so an old ambiguous or cancelled row
            # can never turn an edited meeting into a new send intent.
            legacy_existing = session.execute(
                select(CellReportReminder.id)
                .where(
                    CellReportReminder.igreja_id == igreja_id,
                    CellReportReminder.reuniao_id == meeting_id,
                    CellReportReminder.leader_pessoa_id == pessoa_id,
                )
                .limit(1)
            ).scalar_one_or_none()
            if legacy_existing is not None:
                continue
            # Preserve V1a's one-reminder-per-leader rolling day.  The
            # recipient prefix above serializes concurrent schedulers before
            # this query, so a second meeting cannot race into another row.
            recent = session.execute(
                select(NotificationOutbox.id)
                .where(
                    NotificationOutbox.igreja_id == igreja_id,
                    NotificationOutbox.pessoa_id == pessoa_id,
                    NotificationOutbox.purpose == "cell_report_reminder",
                    NotificationOutbox.created_at >= now - dt.timedelta(hours=24),
                )
                .limit(1)
            ).scalar_one_or_none()
            legacy_recent = session.execute(
                select(CellReportReminder.id)
                .where(
                    CellReportReminder.igreja_id == igreja_id,
                    CellReportReminder.leader_pessoa_id == pessoa_id,
                    CellReportReminder.created_at >= now - dt.timedelta(hours=24),
                )
                .limit(1)
            ).scalar_one_or_none()
            if recent is not None or legacy_recent is not None:
                continue
            notification = NotificationOutbox(
                igreja_id=igreja_id,
                pessoa_id=pessoa_id,
                agenda_alert_recipient_id=None,
                event_id=None,
                reuniao_id=meeting_id,
                agenda_subscription_id=None,
                origin_kind="meeting",
                origin_id=meeting_id,
                occurrence_at=due_at,
                origin_fingerprint=fingerprint,
                purpose="cell_report_reminder",
                state="pendente",
                due_at=due_at,
                delivery_reservation_day=None,
                claim_token=None,
                claimed_until=None,
                claimed_by=None,
                attempts=0,
                transport_started_at=None,
                sent_at=None,
                terminal_reason=None,
                created_at=now,
                updated_at=now,
            )
            try:
                with session.begin_nested():
                    session.add(notification)
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


def schedule_due_cell_report_notification_outbox(
    session_factory: Callable[[], Session],
    *,
    now: dt.datetime | None = None,
    limit: int = 100,
) -> int:
    """Materialize V1a reminders in the sole shared outbox."""

    current = _worker_now(now)
    if type(limit) is not int or limit <= 0:
        raise ValueError("limite de lembretes inválido")
    created = 0
    for igreja_id in _discover_cell_report_schedule_tenants(session_factory):
        if created >= limit:
            break
        created += _schedule_cell_report_tenant(
            session_factory,
            igreja_id=igreja_id,
            now=current,
            limit=limit - created,
        )
    return created


def _same_notification_intent(current: object, snapshot: object) -> bool:
    """Reject a row changed between its lock-free scan and final outbox lock."""

    fields = (
        "igreja_id",
        "pessoa_id",
        "agenda_alert_recipient_id",
        "event_id",
        "reuniao_id",
        "agenda_subscription_id",
        "origin_kind",
        "origin_id",
        "occurrence_at",
        "origin_fingerprint",
        "purpose",
    )
    return all(getattr(current, field, None) == getattr(snapshot, field, None) for field in fields)


def _source_transport_text(
    session: Session,
    *,
    row: object,
    pessoa: object,
    now: dt.datetime,
) -> tuple[str | None, str | None]:
    """Lock and revalidate the live source, returning transient safe text only."""

    from app.db.models import (
        AgendaAlertRecipient,
        AgendaReminderSubscription,
        CelulaReuniao,
        Event,
    )

    igreja_id = _valid_uuid(getattr(row, "igreja_id", None))
    pessoa_id = _valid_uuid(getattr(row, "pessoa_id", None))
    origin_id = _valid_uuid(getattr(row, "origin_id", None))
    purpose = getattr(row, "purpose", None)
    if igreja_id is None or pessoa_id is None or origin_id is None:
        return None, "origem_invalida"

    if purpose in _AGENDA_PURPOSES:
        event_id = _valid_uuid(getattr(row, "event_id", None))
        if event_id is None or event_id != origin_id:
            return None, "evento_indisponivel"
        event = session.execute(
            select(Event)
            .where(Event.igreja_id == igreja_id, Event.id == event_id)
            # Confirmation owns Event before it resolves recipients.  The
            # dispatcher already owns Conversation -> Pessoa, so waiting here
            # would invert those locks.  A contended source is a proven
            # pre-send deferral, never a fabricated terminal receipt.
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if event is None:
            source_exists = session.execute(
                select(Event.id).where(Event.igreja_id == igreja_id, Event.id == event_id)
            ).scalar_one_or_none()
            return None, "evento_ocupado" if source_exists is not None else "evento_alterado"
        if (
            getattr(event, "status", None) != "confirmado"
            or _event_fingerprint(event) != getattr(row, "origin_fingerprint", None)
        ):
            return None, "evento_alterado"
        if purpose == "agenda_evt7":
            confirmed_at = _utc_datetime(getattr(event, "confirmado_em", None))
            recipient_id = _valid_uuid(getattr(row, "agenda_alert_recipient_id", None))
            if (
                confirmed_at is None
                or _utc_datetime(getattr(row, "occurrence_at", None)) != confirmed_at
                or getattr(event, "notification_outbox_fenced_at", None) is not None
                or getattr(event, "notificado_em", None) is not None
                or recipient_id is None
            ):
                return None, "evento_fenced"
            recipient = session.execute(
                select(AgendaAlertRecipient)
                .where(
                    AgendaAlertRecipient.igreja_id == igreja_id,
                    AgendaAlertRecipient.id == recipient_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            from app.domain.phone import normalize_phone

            if (
                recipient is None
                or getattr(recipient, "ativo", None) is not True
                or _valid_uuid(getattr(recipient, "pessoa_id", None)) != pessoa_id
                or normalize_phone(getattr(recipient, "telefone", "") or "")
                != normalize_phone(getattr(pessoa, "telefone", "") or "")
            ):
                return None, "destinatario_revogado"
            return _agenda_evt7_text(event), None

        subscription_id = _valid_uuid(getattr(row, "agenda_subscription_id", None))
        if subscription_id is None:
            return None, "inscricao_indisponivel"
        subscription = session.execute(
            select(AgendaReminderSubscription)
            .where(
                AgendaReminderSubscription.igreja_id == igreja_id,
                AgendaReminderSubscription.id == subscription_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if (
            subscription is None
            or getattr(subscription, "state", None) != "active"
            or _valid_uuid(getattr(subscription, "pessoa_id", None)) != pessoa_id
            or _valid_uuid(getattr(subscription, "event_id", None)) != event_id
            or _utc_datetime(getattr(subscription, "occurrence_at", None))
            != _utc_datetime(getattr(row, "occurrence_at", None))
            or not _event_occurrence_matches(row, event)
            or not _agenda_audience_allows(
                session,
                igreja_id=igreja_id,
                event_id=event_id,
                pessoa_id=pessoa_id,
            )
            or _utc_datetime(getattr(row, "occurrence_at", None)) is None
            or _utc_datetime(getattr(row, "occurrence_at", None)) <= now
        ):
            return None, "inscricao_alterada"
        return _agenda_reminder_text(event), None

    if purpose != "cell_report_reminder":
        return None, "finalidade_invalida"
    reuniao_id = _valid_uuid(getattr(row, "reuniao_id", None))
    if reuniao_id is None or reuniao_id != origin_id:
        return None, "reuniao_indisponivel"
    meeting = session.execute(
        select(CelulaReuniao)
        .where(CelulaReuniao.igreja_id == igreja_id, CelulaReuniao.id == reuniao_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if (
        meeting is None
        or getattr(meeting, "relatorio_status", None) != "pendente"
        or getattr(meeting, "status", None) == "cancelada"
        or _meeting_fingerprint(meeting) != getattr(row, "origin_fingerprint", None)
    ):
        return None, "reuniao_alterada"
    from app.services.cell_report_application import (
        CellReportApplicationError,
        revalidate_cell_report_leader,
    )
    from app.services.cell_report_reminders import (
        cell_report_reminder_is_obsolete,
        cell_report_reminder_text,
    )

    if cell_report_reminder_is_obsolete(
        getattr(meeting, "data", None), getattr(meeting, "hora", None), now
    ):
        return None, "janela_expirada"
    try:
        revalidate_cell_report_leader(
            session,
            igreja_id=igreja_id,
            meeting=meeting,
            ator_pessoa_id=pessoa_id,
        )
    except CellReportApplicationError:
        return None, "lideranca_revogada"
    return cell_report_reminder_text(), None


def _release_claim_before_transport(
    row: object,
    *,
    now: dt.datetime,
    reason: str,
) -> None:
    """Release a lease only when no provider call has started."""

    due_at = next_transport_window(now + dt.timedelta(minutes=1))
    occurrence = _utc_datetime(getattr(row, "occurrence_at", None))
    if due_at is None or not _pre_send_retry_allowed(row, due_at=due_at):
        _terminalize(row, state="cancelado", reason="pre_envio_expirado", now=now)
        return
    if (
        (
            getattr(row, "purpose", None) == "agenda_reminder"
            and (occurrence is None or due_at >= occurrence)
        )
    ):
        _terminalize(row, state="obsoleto", reason="janela_expirada", now=now)
        return
    row.state = "retry"
    row.due_at = due_at
    row.terminal_reason = None
    _clear_claim(row)
    row.updated_at = now


def _renew_notification_transport_fence(
    session_factory: Callable[[], Session],
    claim: NotificationClaim,
    *,
    now: dt.datetime,
    lease_seconds: int,
) -> NotificationTransport | None:
    """Commit current gates, source and lease immediately before provider I/O."""

    from app.db.models import NotificationOutbox

    session = session_factory()
    try:
        _scoped(session, claim.igreja_id, "notification_outbox_transport_fence")
        snapshot = session.execute(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.igreja_id == claim.igreja_id,
                NotificationOutbox.id == claim.outbox_id,
                NotificationOutbox.pessoa_id == claim.pessoa_id,
            )
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if snapshot is None:
            session.rollback()
            return None
        pessoa, conversations = _lock_notification_recipient_prefix(
            session, igreja_id=claim.igreja_id, pessoa_id=claim.pessoa_id
        )
        source_text, source_reason = _source_transport_text(
            session, row=snapshot, pessoa=pessoa, now=now
        )
        context, context_reason = _recipient_transport_context(
            session,
            igreja_id=claim.igreja_id,
            pessoa=pessoa,
            conversations=conversations,
            purpose=getattr(snapshot, "purpose", None),
            now=now,
        )
        row = session.execute(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.igreja_id == claim.igreja_id,
                NotificationOutbox.id == claim.outbox_id,
                NotificationOutbox.pessoa_id == claim.pessoa_id,
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if (
            row is None
            or row.state != "em_envio"
            or row.claim_token != claim.claim_token
            or row.claimed_until is None
            or row.claimed_until <= now
            or not _same_notification_intent(row, snapshot)
        ):
            session.rollback()
            return None
        if not _purpose_gate_allows(row.purpose, claim.igreja_id):
            _terminalize(row, state="cancelado", reason="gate_fechado", now=now)
            session.commit()
            return None
        if source_text is None:
            if source_reason == "evento_ocupado":
                _release_claim_before_transport(row, now=now, reason=source_reason)
                session.commit()
                return None
            _terminalize(
                row, state="obsoleto", reason=source_reason or "origem_indisponivel", now=now
            )
            session.commit()
            return None
        if context is None:
            if context_reason == "instancia_indisponivel":
                _release_claim_before_transport(
                    row, now=now, reason=context_reason
                )
            else:
                _terminalize(
                    row,
                    state="cancelado",
                    reason=context_reason or "contexto_revogado",
                    now=now,
                )
            session.commit()
            return None
        if (
            claim.destination_fingerprint is not None
            and _destination_fingerprint(context) != claim.destination_fingerprint
        ):
            _terminalize(row, state="cancelado", reason="destino_alterado", now=now)
            session.commit()
            return None
        if not transport_window_open(now):
            _release_claim_before_transport(row, now=now, reason="fora_da_janela")
            session.commit()
            return None
        if _evt7_pre_send_expired(row, now=now):
            _terminalize(row, state="cancelado", reason="pre_envio_expirado", now=now)
            session.commit()
            return None
        instance, phone = context
        row.claimed_until = now + dt.timedelta(seconds=lease_seconds)
        row.transport_started_at = now
        row.updated_at = now
        session.commit()
        return NotificationTransport(
            claim=claim,
            instance=instance,
            phone=phone,
            text=source_text,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _record_notification_result(
    session_factory: Callable[[], Session],
    claim: NotificationClaim,
    *,
    result: object,
    now: dt.datetime,
) -> bool:
    """Persist a classified provider result without reopening uncertainty."""

    from app.db.models import NotificationOutbox

    session = session_factory()
    try:
        _scoped(session, claim.igreja_id, "notification_outbox_result")
        _pessoa, _conversations = _lock_notification_recipient_prefix(
            session, igreja_id=claim.igreja_id, pessoa_id=claim.pessoa_id
        )
        row = session.execute(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.igreja_id == claim.igreja_id,
                NotificationOutbox.id == claim.outbox_id,
                NotificationOutbox.pessoa_id == claim.pessoa_id,
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if (
            row is None
            or row.state != "em_envio"
            or row.claim_token != claim.claim_token
            or row.claimed_until is None
            or row.claimed_until <= now
        ):
            session.rollback()
            return False
        transition = result_transition(result, attempts=row.attempts, now=now)
        row.state = transition.state
        row.attempts = transition.attempts
        if transition.due_at is not None:
            row.due_at = transition.due_at
        row.terminal_reason = transition.terminal_reason
        _clear_claim(row)
        row.updated_at = now
        if transition.state == "enviado":
            row.sent_at = now
            # Every shared template carries the fixed stop instruction. Keep
            # that durable receipt code alongside `sent_at` without retaining
            # message text, a phone, or another delivery table.
            row.terminal_reason = "aviso_parada_incluido"
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = [
    "NotificationResultTransition",
    "SAO_PAULO_TZ",
    "agenda_delivery_enabled",
    "disable_whatsapp_reminders",
    "dispatch_notification_outbox",
    "enqueue_evt7_for_confirmed_event",
    "next_transport_window",
    "result_transition",
    "schedule_due_cell_report_notification_outbox",
    "transport_window_open",
]
