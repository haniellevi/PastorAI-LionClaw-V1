from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from app.db import models
from app.services.evolution import BroadcastSendResult
from app.services import notification_outbox as outbox
from app.services import whatsapp_agenda


def test_common_transport_window_is_sao_paulo_08_inclusive_21_exclusive() -> None:
    assert outbox.transport_window_open(
        dt.datetime(2026, 9, 27, 11, tzinfo=dt.timezone.utc)
    )
    assert not outbox.transport_window_open(
        dt.datetime(2026, 9, 28, 0, tzinfo=dt.timezone.utc)
    )


def test_only_explicitly_pre_send_failure_can_retry() -> None:
    now = dt.datetime(2026, 9, 27, 18, tzinfo=dt.timezone.utc)

    retry = outbox.result_transition(
        BroadcastSendResult(
            status="falhou_retentavel",
            error_class="connect_error",
            consume_retry_budget=False,
        ),
        attempts=0,
        now=now,
    )
    ambiguous = outbox.result_transition(
        BroadcastSendResult(
            status="falhou_retentavel",
            error_class="unknown_retry_class",
        ),
        attempts=0,
        now=now,
    )

    assert (retry.state, retry.attempts, retry.due_at) == (
        "retry",
        1,
        now + dt.timedelta(minutes=1),
    )
    assert (ambiguous.state, ambiguous.terminal_reason) == (
        "ambiguo",
        "resultado_ambiguo",
    )


def test_agenda_delivery_gate_reuses_the_canonical_s3_agenda_gate(monkeypatch) -> None:
    igreja_id = uuid.UUID("00000000-0000-0000-0000-000000000091")
    monkeypatch.setattr(whatsapp_agenda, "AGENDA_WHATSAPP_APPROVED_RELEASE_ID", "v2b-test")
    monkeypatch.setattr(whatsapp_agenda, "privilege_enabled_from_environment", lambda _id: True)
    monkeypatch.setenv("AGENDA_WHATSAPP_ENABLED_IGREJA_IDS", str(igreja_id))
    monkeypatch.setenv("AGENDA_NOTIFY_ENABLED", "true")

    assert outbox.agenda_delivery_enabled(igreja_id)


def test_agenda_templates_always_include_the_global_stop_instruction() -> None:
    event = SimpleNamespace(titulo="Culto", tipo="culto")

    assert "PARAR LEMBRETES" in outbox._agenda_evt7_text(event)
    assert "PARAR LEMBRETES" in outbox._agenda_reminder_text(event)


@pytest.mark.parametrize(
    ("occurrence_at", "expected_due_at"),
    (
        (
            dt.datetime(2026, 9, 28, 22, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 9, 27, 22, tzinfo=dt.timezone.utc),
        ),
        (
            dt.datetime(2026, 10, 5, 22, tzinfo=dt.timezone.utc),
            dt.datetime(2026, 10, 4, 22, tzinfo=dt.timezone.utc),
        ),
    ),
)
def test_agenda_reminder_due_at_derives_each_weekly_occurrence_from_antecedence(
    occurrence_at: dt.datetime,
    expected_due_at: dt.datetime,
) -> None:
    event = SimpleNamespace(
        recorrencia="semanal",
        data=dt.date(2026, 9, 28),
        hora="19:00",
        dia_semana=1,
        # This is the persisted first-occurrence timestamp and must not pin
        # later weekly subscriptions to the old absolute instant.
        notificar_em=dt.datetime(2026, 9, 27, 22, tzinfo=dt.timezone.utc),
        antecedencia_horas=24,
    )

    assert outbox._agenda_reminder_due_at(
        event,
        occurrence_at=occurrence_at,
        now=dt.datetime(2026, 9, 27, 18, tzinfo=dt.timezone.utc),
    ) == expected_due_at


def test_agenda_reminder_due_at_rejects_later_weekly_occurrence_without_antecedence() -> None:
    event = SimpleNamespace(
        recorrencia="semanal",
        data=dt.date(2026, 9, 28),
        hora="19:00",
        dia_semana=1,
        notificar_em=dt.datetime(2026, 9, 27, 22, tzinfo=dt.timezone.utc),
        antecedencia_horas=None,
    )

    assert outbox._agenda_reminder_due_at(
        event,
        occurrence_at=dt.datetime(2026, 9, 28, 22, tzinfo=dt.timezone.utc),
        now=dt.datetime(2026, 9, 27, 18, tzinfo=dt.timezone.utc),
    ) == dt.datetime(2026, 9, 27, 22, tzinfo=dt.timezone.utc)
    assert outbox._agenda_reminder_due_at(
        event,
        occurrence_at=dt.datetime(2026, 10, 5, 22, tzinfo=dt.timezone.utc),
        now=dt.datetime(2026, 9, 27, 18, tzinfo=dt.timezone.utc),
    ) is None


def test_evt7_pre_send_deadline_starts_at_the_next_open_window() -> None:
    """A post-window confirmation gets one bounded next-window grace period."""

    created_at = dt.datetime(2026, 9, 28, 1, tzinfo=dt.timezone.utc)

    assert outbox._evt7_pre_send_deadline(created_at) == dt.datetime(
        2026, 9, 28, 11, 10, tzinfo=dt.timezone.utc
    )


def test_durable_rows_keep_only_opaque_references_and_transport_state() -> None:
    notification = getattr(models, "NotificationOutbox", None)
    preference = getattr(models, "WhatsappReminderPreference", None)
    subscription = getattr(models, "AgendaReminderSubscription", None)

    assert notification is not None
    assert preference is not None
    assert subscription is not None
    assert {
        "igreja_id",
        "pessoa_id",
        "origin_kind",
        "origin_id",
        "occurrence_at",
        "origin_fingerprint",
        "purpose",
        "state",
        "claim_token",
        "claimed_until",
        "transport_started_at",
        "delivery_reservation_day",
    } <= set(notification.__table__.columns.keys())
    assert {
        "telefone",
        "texto",
        "titulo",
        "descricao",
        "payload",
        "recipient_key",
    }.isdisjoint(
        notification.__table__.columns.keys()
    )
    assert {"igreja_id", "pessoa_id", "reminder_kind", "state", "term_version"} <= set(
        preference.__table__.columns.keys()
    )
    assert {"igreja_id", "pessoa_id", "event_id", "occurrence_at", "state"} <= set(
        subscription.__table__.columns.keys()
    )
    recipient = getattr(models, "AgendaAlertRecipient", None)
    assert recipient is not None
    assert recipient.__table__.columns["pessoa_id"].nullable is True

    subscription_fk = next(
        fk
        for fk in subscription.__table__.foreign_key_constraints
        if fk.name == "agenda_reminder_subscriptions_tenant_event_fkey"
    )
    assert subscription_fk.ondelete == "CASCADE"

    proposal_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in models.AgentActionProposal.__table__.constraints
        if getattr(constraint, "sqltext", None) is not None
    }
    receipt_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in models.AgentActionReceipt.__table__.constraints
        if getattr(constraint, "sqltext", None) is not None
    }
    assert "configurar_lembrete_agenda" in proposal_checks[
        "agent_action_proposals_action_closed"
    ]
    assert "target_kind = 'evento'" in proposal_checks[
        "agent_action_proposals_target_kind_closed"
    ]
    assert "Lembrete confirmado." in receipt_checks[
        "agent_action_receipts_receipt_text_closed"
    ]


class _EnqueueSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)


class _Scalars:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def __iter__(self):
        return iter(self._values)

    def all(self) -> list[object]:
        return list(self._values)


class _EligibleRecipientsSession:
    def __init__(self, *, recipients: list[object], people: list[object]) -> None:
        self.recipients = recipients
        self.people = people

    def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is models.AgendaAlertRecipient:
            return SimpleNamespace(scalars=lambda: _Scalars(self.recipients))
        if entity is models.Pessoa:
            return SimpleNamespace(scalars=lambda: _Scalars(self.people))
        raise AssertionError(f"consulta inesperada: {entity!r}")


def test_evt7_eligibility_requires_the_server_managed_person_link(monkeypatch) -> None:
    igreja_id = uuid.UUID("00000000-0000-0000-0000-000000000097")
    pessoa_id = uuid.UUID("00000000-0000-0000-0000-000000000098")
    canonical_phone = "11" + "99999" + "0000"
    person = SimpleNamespace(
        id=pessoa_id,
        igreja_id=igreja_id,
        telefone="+55 (11) " + "99999-0000",
        arquivada_em=None,
        optout=False,
        sem_interesse=False,
    )
    legacy_phone_only = SimpleNamespace(
        id=uuid.uuid4(), pessoa_id=None, telefone=canonical_phone, ativo=True
    )
    linked = SimpleNamespace(
        id=uuid.uuid4(), pessoa_id=pessoa_id, telefone=canonical_phone, ativo=True
    )
    session = _EligibleRecipientsSession(
        recipients=[legacy_phone_only, linked], people=[person]
    )
    monkeypatch.setattr(
        outbox,
        "_lock_notification_recipient_prefix",
        lambda *_args, **_kwargs: (person, ()),
    )
    monkeypatch.setattr(outbox, "_current_consent_allows", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(outbox, "_agenda_preference_allows", lambda *_args, **_kwargs: True)

    eligible = outbox._eligible_evt7_recipients(
        session,
        igreja_id=igreja_id,
        now=dt.datetime(2026, 9, 27, 15, tzinfo=dt.timezone.utc),
    )

    assert eligible == (outbox._Evt7Recipient(id=linked.id, pessoa_id=pessoa_id),)


def test_evt7_enqueue_is_durable_and_deduplicates_the_canonical_person(monkeypatch) -> None:
    """Confirmation records an intention only; it never reaches transport."""

    igreja_id = uuid.UUID("00000000-0000-0000-0000-000000000091")
    event_id = uuid.UUID("00000000-0000-0000-0000-000000000092")
    pessoa_id = uuid.UUID("00000000-0000-0000-0000-000000000093")
    event = SimpleNamespace(
        id=event_id,
        igreja_id=igreja_id,
        status="confirmado",
        confirmado_em=dt.datetime(2026, 9, 27, 15, tzinfo=dt.timezone.utc),
        notification_outbox_fenced_at=None,
        titulo="texto que só pode virar hash técnico",
        tipo="culto",
        data=dt.date(2026, 9, 28),
        hora="19:00",
    )
    recipient = SimpleNamespace(id=uuid.uuid4(), pessoa_id=pessoa_id)
    session = _EnqueueSession()
    monkeypatch.setattr(outbox, "agenda_delivery_enabled", lambda _tenant: True)
    monkeypatch.setattr(
        outbox,
        "_eligible_evt7_recipients",
        lambda _session, **_kwargs: (recipient, recipient),
    )

    assert outbox.enqueue_evt7_for_confirmed_event(session, event) == 1
    assert len(session.added) == 1
    row = session.added[0]
    assert row.purpose == "agenda_evt7"
    assert row.pessoa_id == pessoa_id
    assert row.event_id == event_id
    assert row.origin_id == event_id
    assert row.state == "pendente"
    assert row.origin_fingerprint != event.titulo


def test_evt7_enqueue_respects_the_legacy_cutover_fence(monkeypatch) -> None:
    igreja_id = uuid.UUID("00000000-0000-0000-0000-000000000094")
    event = SimpleNamespace(
        id=uuid.uuid4(),
        igreja_id=igreja_id,
        status="confirmado",
        confirmado_em=dt.datetime(2026, 9, 27, 15, tzinfo=dt.timezone.utc),
        notification_outbox_fenced_at=dt.datetime(2026, 9, 27, 15, tzinfo=dt.timezone.utc),
    )
    session = _EnqueueSession()
    monkeypatch.setattr(outbox, "agenda_delivery_enabled", lambda _tenant: True)

    assert outbox.enqueue_evt7_for_confirmed_event(session, event) == 0
    assert session.added == []


class _StopResult:
    def __init__(self, values: list[object] | None = None, *, rowcount: int = 0) -> None:
        self._values = values or []
        self.rowcount = rowcount

    def scalars(self):
        return _Scalars(self._values)

    def scalar_one_or_none(self):
        return self._values[0] if self._values else None


class _StopSession:
    def __init__(self, *, preferences: list[object], subscriptions: list[object]) -> None:
        self.preferences = preferences
        self.subscriptions = subscriptions
        self.added: list[object] = []
        self.updates: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    def execute(self, statement):
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is models.WhatsappReminderPreference:
            return _StopResult(self.preferences)
        if entity is models.AgendaReminderSubscription:
            return _StopResult(self.subscriptions)
        self.updates.append(statement)
        return _StopResult(rowcount=1)


def test_global_stop_disables_both_kinds_and_fences_common_outbox(monkeypatch) -> None:
    from app.services import cell_report_reminders

    igreja_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
    pessoa_id = uuid.UUID("00000000-0000-0000-0000-000000000100")
    conversation_id = uuid.UUID("00000000-0000-0000-0000-000000000101")
    current = dt.datetime(2026, 9, 27, 15, tzinfo=dt.timezone.utc)
    agenda_preference = SimpleNamespace(reminder_kind="agenda", state="active")
    subscription = SimpleNamespace(state="active", updated_at=None)
    session = _StopSession(
        preferences=[agenda_preference], subscriptions=[subscription]
    )
    legacy_calls: list[dict[str, object]] = []
    pessoa = SimpleNamespace(id=pessoa_id)
    conversation = SimpleNamespace(id=conversation_id)
    monkeypatch.setattr(outbox, "_scoped", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        outbox,
        "_lock_notification_recipient_prefix",
        lambda *_args, **_kwargs: (pessoa, (conversation,)),
    )
    monkeypatch.setattr(
        cell_report_reminders,
        "disable_cell_report_reminders",
        lambda _session, **kwargs: legacy_calls.append(kwargs) or False,
    )

    assert outbox.disable_whatsapp_reminders(
        session,
        igreja_id=igreja_id,
        pessoa_id=pessoa_id,
        conversation_id=conversation_id,
        now=current,
    )

    assert agenda_preference.state == "disabled"
    assert agenda_preference.changed_at == current
    created_kinds = {
        row.reminder_kind
        for row in session.added
        if isinstance(row, models.WhatsappReminderPreference)
    }
    assert created_kinds == {"cell_report"}
    assert subscription.state == "cancelled"
    assert subscription.updated_at == current
    assert len(session.updates) == 3
    proposal_update = next(
        statement
        for statement in session.updates
        if "agent_action_proposals" in str(statement)
    )
    compiled = str(proposal_update.compile(compile_kwargs={"literal_binds": True}))
    assert "configurar_lembrete_agenda" in compiled
    assert "actor_pessoa_id" in compiled
    assert "preparada" in compiled and "pendente" in compiled
    assert "lembretes_recusados" in compiled
    assert legacy_calls == [
        {
            "igreja_id": igreja_id,
            "conversation_id": conversation_id,
            "pessoa_id": pessoa_id,
            "now": current,
        }
    ]


def test_global_stop_is_idempotently_handled_after_every_row_is_already_fenced(
    monkeypatch,
) -> None:
    """A repeated user refusal is handled, never mistaken for a missing chat."""

    from app.services import cell_report_reminders

    igreja_id = uuid.UUID("00000000-0000-0000-0000-000000000111")
    pessoa_id = uuid.UUID("00000000-0000-0000-0000-000000000112")
    conversation_id = uuid.UUID("00000000-0000-0000-0000-000000000113")
    session = _StopSession(
        preferences=[
            SimpleNamespace(reminder_kind="agenda", state="disabled"),
            SimpleNamespace(reminder_kind="cell_report", state="disabled"),
        ],
        subscriptions=[],
    )
    pessoa = SimpleNamespace(id=pessoa_id)
    conversation = SimpleNamespace(id=conversation_id)
    monkeypatch.setattr(outbox, "_scoped", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        outbox,
        "_lock_notification_recipient_prefix",
        lambda *_args, **_kwargs: (pessoa, (conversation,)),
    )
    monkeypatch.setattr(
        cell_report_reminders,
        "disable_cell_report_reminders",
        lambda *_args, **_kwargs: False,
    )
    original_execute = session.execute

    def execute_without_mutations(statement):
        result = original_execute(statement)
        if getattr(statement, "is_update", False):
            return _StopResult(rowcount=0)
        return result

    session.execute = execute_without_mutations  # type: ignore[method-assign]

    assert outbox.disable_whatsapp_reminders(
        session,
        igreja_id=igreja_id,
        pessoa_id=pessoa_id,
        conversation_id=conversation_id,
    )


class _SubscriptionExecutionResult:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _SubscriptionExecutionSession:
    def __init__(self, *, event: object) -> None:
        self.event = event
        self.added: list[object] = []
        self.flushes = 0

    def execute(self, statement):
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is models.Event:
            return _SubscriptionExecutionResult(self.event)
        if entity in {
            models.WhatsappReminderPreference,
            models.AgendaReminderSubscription,
            models.NotificationOutbox,
        }:
            return _SubscriptionExecutionResult(None)
        raise AssertionError(f"consulta inesperada: {entity!r}")

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        self.flushes += 1
        for value in self.added:
            if isinstance(value, models.AgendaReminderSubscription) and value.id is None:
                value.id = uuid.UUID("00000000-0000-0000-0000-000000000125")

    def commit(self) -> None:
        raise AssertionError("o efeito S3 não pode fazer commit")


def test_s3_agenda_confirmation_creates_one_subscription_and_outbox_without_commit(
    monkeypatch,
) -> None:
    from app.services.agent_action_proposals import AgentAction, ProposalTarget
    from app.services.whatsapp_privilege import PrivilegeContext

    igreja_id = uuid.UUID("00000000-0000-0000-0000-000000000121")
    pessoa_id = uuid.UUID("00000000-0000-0000-0000-000000000122")
    event_id = uuid.UUID("00000000-0000-0000-0000-000000000123")
    proposal_id = uuid.UUID("00000000-0000-0000-0000-000000000124")
    occurrence = dt.datetime(2026, 10, 2, 22, tzinfo=dt.timezone.utc)
    due_at = occurrence - dt.timedelta(days=1)
    current = dt.datetime(2026, 9, 27, 15, tzinfo=dt.timezone.utc)
    event = SimpleNamespace(
        id=event_id,
        igreja_id=igreja_id,
        status="confirmado",
        data=dt.date(2026, 10, 2),
        hora="19:00",
        recorrencia="pontual",
        dia_semana=None,
        notificar_em=due_at,
        antecedencia_horas=None,
        confirmado_em=current,
        confirmado_por=uuid.uuid4(),
        titulo="Culto",
        tipo="culto",
        origem="manual",
        publico_alvo=["toda_igreja"],
    )
    pessoa = SimpleNamespace(
        id=pessoa_id,
        igreja_id=igreja_id,
        arquivada_em=None,
        optout=False,
        sem_interesse=False,
    )
    context = PrivilegeContext(
        igreja_id=igreja_id,
        conversation_id=uuid.uuid4(),
        inbound_message_id=uuid.uuid4(),
        pessoa_id=pessoa_id,
        app_user_id=uuid.uuid4(),
        roles=frozenset({"membro"}),
        role_snapshot=(),
        owned_cell_ids=(),
        credential_fingerprint="1" * 64,
        phone_fingerprint="2" * 64,
        authorization_fingerprint="3" * 64,
        proof_id=None,
        proof_until=None,
        sensitive=False,
        scope_fingerprint="4" * 64,
        context_fingerprint="5" * 64,
    )
    execution = SimpleNamespace(
        proposal_id=proposal_id,
        igreja_id=igreja_id,
        action=AgentAction.CONFIGURAR_LEMBRETE_AGENDA,
        target=ProposalTarget("evento", event_id),
        arguments={
            "event_id": str(event_id),
            "occurrence_at": occurrence.isoformat(timespec="microseconds"),
            "term_version": "lgpd-v2",
        },
        privilege_context=context,
    )
    session = _SubscriptionExecutionSession(event=event)
    monkeypatch.setattr(outbox, "_scoped", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(outbox, "_worker_now", lambda _now: current)
    monkeypatch.setattr(outbox, "agenda_delivery_enabled", lambda _tenant: True)
    monkeypatch.setattr(
        outbox,
        "_lock_notification_recipient_prefix",
        lambda *_args, **_kwargs: (pessoa, ()),
    )
    monkeypatch.setattr(outbox, "_current_consent_allows", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(outbox, "_agenda_audience_allows", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        "app.config.get_settings", lambda: SimpleNamespace(agent_term_version="lgpd-v2")
    )

    effect = outbox.execute_agenda_reminder_subscription(session, execution)

    preference, subscription, notification = session.added
    assert effect.receipt_text == "Lembrete confirmado."
    assert effect.opaque_effect_id == subscription.id
    assert subscription.event_id == event_id
    assert subscription.occurrence_at == occurrence
    assert subscription.proposal_id == proposal_id
    assert subscription.state == "active"
    assert preference.reminder_kind == "agenda"
    assert preference.state == "active"
    assert preference.term_version == "lgpd-v2"
    assert notification.purpose == "agenda_reminder"
    assert notification.event_id == event_id
    assert notification.agenda_subscription_id == subscription.id
    assert notification.due_at == due_at
    assert notification.delivery_reservation_day is None
    assert session.flushes == 1


class _AgendaSourceSession:
    def __init__(self, *, event: object, subscription: object) -> None:
        self.event = event
        self.subscription = subscription

    def execute(self, statement):
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is models.Event:
            return _SubscriptionExecutionResult(self.event)
        if entity is models.AgendaReminderSubscription:
            return _SubscriptionExecutionResult(self.subscription)
        raise AssertionError(f"consulta inesperada: {entity!r}")


def test_agenda_fence_rechecks_current_event_audience_after_s3_confirmation(
    monkeypatch,
) -> None:
    igreja_id = uuid.UUID("00000000-0000-0000-0000-000000000131")
    pessoa_id = uuid.UUID("00000000-0000-0000-0000-000000000132")
    event_id = uuid.UUID("00000000-0000-0000-0000-000000000133")
    current = dt.datetime(2026, 9, 27, 15, tzinfo=dt.timezone.utc)
    occurrence = dt.datetime(2026, 10, 2, 22, tzinfo=dt.timezone.utc)
    event = SimpleNamespace(
        id=event_id,
        igreja_id=igreja_id,
        status="confirmado",
        data=dt.date(2026, 10, 2),
        hora="19:00",
        recorrencia="pontual",
        dia_semana=None,
        confirmado_em=current,
        confirmado_por=uuid.uuid4(),
        notificar_em=occurrence - dt.timedelta(days=1),
        antecedencia_horas=None,
        titulo="Culto",
        tipo="culto",
        origem="manual",
        publico_alvo=["pastores"],
    )
    row = SimpleNamespace(
        igreja_id=igreja_id,
        pessoa_id=pessoa_id,
        origin_id=event_id,
        event_id=event_id,
        purpose="agenda_reminder",
        agenda_subscription_id=uuid.uuid4(),
        occurrence_at=occurrence,
        origin_fingerprint=outbox._event_fingerprint(event),
    )
    subscription = SimpleNamespace(
        state="active",
        pessoa_id=pessoa_id,
        event_id=event_id,
        occurrence_at=occurrence,
    )
    monkeypatch.setattr(outbox, "_agenda_audience_allows", lambda *_args, **_kwargs: False)

    text, reason = outbox._source_transport_text(
        _AgendaSourceSession(event=event, subscription=subscription),
        row=row,
        pessoa=SimpleNamespace(id=pessoa_id),
        now=current,
    )

    assert text is None
    assert reason == "inscricao_alterada"


class _FenceSession:
    def __init__(self, row: object) -> None:
        self.row = row
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, _statement):
        return _StopResult([self.row])

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_evt7_source_lock_contention_releases_pre_send_lease_without_terminalizing(monkeypatch) -> None:
    igreja_id = uuid.UUID("00000000-0000-0000-0000-000000000102")
    pessoa_id = uuid.UUID("00000000-0000-0000-0000-000000000103")
    outbox_id = uuid.UUID("00000000-0000-0000-0000-000000000104")
    claim_token = uuid.UUID("00000000-0000-0000-0000-000000000105")
    current = dt.datetime(2026, 9, 27, 15, tzinfo=dt.timezone.utc)
    synthetic_phone = "55" + "11" + "99999" + "0000"
    row = SimpleNamespace(
        id=outbox_id,
        igreja_id=igreja_id,
        pessoa_id=pessoa_id,
        agenda_alert_recipient_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        reuniao_id=None,
        agenda_subscription_id=None,
        origin_kind="event",
        origin_id=uuid.uuid4(),
        occurrence_at=current,
        origin_fingerprint="0" * 64,
        purpose="agenda_evt7",
        state="em_envio",
        claim_token=claim_token,
        claimed_until=current + dt.timedelta(seconds=30),
    )
    session = _FenceSession(row)
    releases: list[str] = []
    terminals: list[str] = []
    monkeypatch.setattr(outbox, "_scoped", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        outbox,
        "_lock_notification_recipient_prefix",
        lambda *_args, **_kwargs: (SimpleNamespace(id=pessoa_id), ()),
    )
    monkeypatch.setattr(
        outbox,
        "_source_transport_text",
        lambda *_args, **_kwargs: (None, "evento_ocupado"),
    )
    monkeypatch.setattr(
        outbox,
        "_recipient_transport_context",
        lambda *_args, **_kwargs: (("instance", synthetic_phone), None),
    )
    monkeypatch.setattr(outbox, "_purpose_gate_allows", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        outbox,
        "_release_claim_before_transport",
        lambda _row, *, reason, **_kwargs: releases.append(reason),
    )
    monkeypatch.setattr(
        outbox,
        "_terminalize",
        lambda _row, *, reason, **_kwargs: terminals.append(reason),
    )

    result = outbox._renew_notification_transport_fence(
        lambda: session,
        outbox.NotificationClaim(
            igreja_id=igreja_id,
            outbox_id=outbox_id,
            pessoa_id=pessoa_id,
            claim_token=claim_token,
        ),
        now=current,
        lease_seconds=30,
    )

    assert result is None
    assert releases == ["evento_ocupado"]
    assert terminals == []
    assert session.committed is True
    assert session.closed is True


def test_evt7_pre_send_deferral_expires_without_using_provider_attempt_budget() -> None:
    created_at = dt.datetime(2026, 9, 28, 1, tzinfo=dt.timezone.utc)
    deadline = outbox._evt7_pre_send_deadline(created_at)
    assert deadline is not None
    row = SimpleNamespace(
        purpose="agenda_evt7",
        state="em_envio",
        created_at=created_at,
        occurrence_at=created_at,
        attempts=0,
        claim_token=uuid.uuid4(),
        claimed_until=deadline + dt.timedelta(seconds=30),
        claimed_by="synthetic-worker",
        terminal_reason=None,
        updated_at=created_at,
    )

    outbox._release_claim_before_transport(row, now=deadline, reason="evento_ocupado")

    assert row.state == "cancelado"
    assert row.terminal_reason == "pre_envio_expirado"
    assert row.attempts == 0
    assert row.claim_token is None and row.claimed_until is None


def test_agenda_reminder_pre_send_deferral_never_crosses_its_occurrence() -> None:
    current = dt.datetime(2026, 9, 28, 11, tzinfo=dt.timezone.utc)
    row = SimpleNamespace(
        purpose="agenda_reminder",
        state="em_envio",
        created_at=current - dt.timedelta(days=1),
        occurrence_at=current + dt.timedelta(minutes=1),
        attempts=0,
        claim_token=uuid.uuid4(),
        claimed_until=current + dt.timedelta(seconds=30),
        claimed_by="synthetic-worker",
        terminal_reason=None,
        updated_at=current,
    )

    outbox._release_claim_before_transport(row, now=current, reason="instancia_indisponivel")

    assert row.state == "obsoleto"
    assert row.terminal_reason == "janela_expirada"
    assert row.attempts == 0


def test_dispatcher_commits_claim_and_transport_fence_before_provider(monkeypatch) -> None:
    """No provider call is possible while the durable fence is uncommitted."""

    igreja_id = uuid.UUID("00000000-0000-0000-0000-000000000095")
    claim = outbox.NotificationClaim(
        igreja_id=igreja_id,
        outbox_id=uuid.uuid4(),
        pessoa_id=uuid.uuid4(),
        claim_token=uuid.uuid4(),
    )
    transport = outbox.NotificationTransport(
        claim=claim,
        instance="synthetic-instance",
        phone="00000000000",
        text="Mensagem fixa de teste.",
    )
    order: list[str] = []
    results: list[object] = []

    monkeypatch.setattr(outbox, "_discover_notification_tenants", lambda _factory: (igreja_id,))
    monkeypatch.setattr(outbox, "maintain_notification_outbox", lambda *_args, **_kwargs: 0)

    def claim_next(*_args, **_kwargs):
        if "claim" not in order:
            order.append("claim")
            return claim
        return None

    def fence(*_args, **_kwargs):
        assert order == ["claim"]
        order.append("fence")
        return transport

    def record(*_args, **kwargs):
        assert order == ["claim", "fence", "provider"]
        results.append(kwargs["result"])
        order.append("result")
        return True

    class Provider:
        def send_text_classificado(self, instance, phone, text):
            assert (instance, phone, text) == (
                transport.instance,
                transport.phone,
                transport.text,
            )
            assert order == ["claim", "fence"]
            order.append("provider")
            return BroadcastSendResult(status="aceito")

    monkeypatch.setattr(outbox, "_claim_next_notification", claim_next)
    monkeypatch.setattr(outbox, "_renew_notification_transport_fence", fence)
    monkeypatch.setattr(outbox, "_record_notification_result", record)

    assert outbox.dispatch_notification_outbox(
        lambda: object(), Provider(), worker_id="synthetic-worker", limit=2
    ) == 1
    assert order == ["claim", "fence", "provider", "result"]
    assert len(results) == 1
