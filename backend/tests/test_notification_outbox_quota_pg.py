"""PG17 coverage for the Agenda transport quota shared by S3 and EVT-7.

The rows are prepared from the real S3 Agenda confirmation and EVT-7 enqueue
service.  Only Evolution is synthetic.  Each dispatcher transaction enters the
tenant through ``authenticated`` (NOBYPASSRLS), so the quota tests also exercise
the committed RLS path rather than an owner shortcut.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import threading
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db.models import (
    AgendaAlertRecipient,
    ConsentRecord,
    Conversation,
    Event,
    Igreja,
    NotificationOutbox,
    Pessoa,
    WhatsappReminderPreference,
)
from app.db.tenant_session import mark_tenant_scoped
from app.services import notification_outbox
from app.services.evolution import BroadcastSendResult
from tests.conftest_rls import rls_database_url  # noqa: F401 - disposable PG guard
from tests.test_agent_privileged_turn_pg import msg_engine_fx, s3_turn  # noqa: F401
from tests.test_agenda_reminder_subscription_e2e_pg import (
    _IGREJA,
    _TERM,
    _assert_v2b_rls_is_forced,
    _request_and_confirm,
    _scoped_rows,
    agenda_reminder_turn,
)
from tests.test_whatsapp_agenda_pg import agenda_turn  # noqa: F401


pytestmark = pytest.mark.rls_integration


@pytest.fixture(autouse=True)
def _require_disposable_pg(rls_database_url: str) -> None:
    """Keep every marked test tied to the suite's disposable-database guard."""


class _QuotaProvider:
    """Thread-safe classified provider fake for committed dispatcher calls."""

    def __init__(self, *results: BroadcastSendResult) -> None:
        self._results = list(results)
        self.calls: list[tuple[str | None, str | None, str]] = []
        self._lock = threading.Lock()

    def send_text_classificado(self, instance, telefone, texto):
        assert "PARAR LEMBRETES" in texto
        with self._lock:
            self.calls.append((instance, telefone, texto))
            if self._results:
                return self._results.pop(0)
        return BroadcastSendResult(status="aceito")


def _actor_pessoa_id(turn) -> uuid.UUID:
    session = turn.factory()
    try:
        mark_tenant_scoped(session, _IGREJA, source="notification_outbox_quota_actor")
        assert session.execute(
            text("select rolbypassrls from pg_roles where rolname = current_user")
        ).scalar_one() is False
        conversation = session.get(Conversation, turn.conversation_id)
        assert conversation is not None and type(conversation.pessoa_id) is uuid.UUID
        return conversation.pessoa_id
    finally:
        session.rollback()
        session.close()


def _agenda_row(turn, monkeypatch: pytest.MonkeyPatch, *, suffix: str):
    _request_and_confirm(turn, monkeypatch, suffix=suffix)
    rows = _scoped_rows(turn, NotificationOutbox)
    return next(row for row in rows if row.purpose == "agenda_reminder")


def _ensure_evt7_recipient(turn) -> uuid.UUID:
    pessoa_id = _actor_pessoa_id(turn)
    with turn.factory.begin() as session:
        mark_tenant_scoped(session, _IGREJA, source="notification_outbox_quota_recipient")
        pessoa = session.execute(
            select(Pessoa).where(Pessoa.igreja_id == _IGREJA, Pessoa.id == pessoa_id)
        ).scalar_one()
        recipient = session.execute(
            select(AgendaAlertRecipient).where(
                AgendaAlertRecipient.igreja_id == _IGREJA,
                AgendaAlertRecipient.pessoa_id == pessoa_id,
                AgendaAlertRecipient.ativo.is_(True),
            )
        ).scalar_one_or_none()
        if recipient is None:
            recipient = AgendaAlertRecipient(
                igreja_id=_IGREJA,
                nome="Destinatário sintético",
                telefone=pessoa.telefone,
                pessoa_id=pessoa_id,
                ativo=True,
            )
            session.add(recipient)
            session.flush()
        assert type(recipient.id) is uuid.UUID
        return recipient.id


def _enqueue_evt7(
    turn,
    *,
    label: str,
    now: dt.datetime,
    due_at: dt.datetime | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create one live EVT-7 intent through its event-confirmation service."""

    _ensure_evt7_recipient(turn)
    with turn.factory.begin() as session:
        mark_tenant_scoped(session, _IGREJA, source="notification_outbox_quota_evt7")
        event = Event(
            id=uuid.uuid4(),
            igreja_id=_IGREJA,
            titulo=f"Evento sintético {label}",
            tipo="culto",
            status="confirmado",
            data=now.astimezone(notification_outbox.SAO_PAULO_TZ).date() + dt.timedelta(days=3),
            hora="19:30",
            recorrencia="pontual",
            confirmado_em=now - dt.timedelta(minutes=1),
            confirmado_por=None,
            notification_outbox_fenced_at=None,
            notificado_em=None,
        )
        session.add(event)
        session.flush()
        assert notification_outbox.enqueue_evt7_for_confirmed_event(session, event, now=now) == 1
        session.flush()
        row = session.execute(
            select(NotificationOutbox).where(
                NotificationOutbox.igreja_id == _IGREJA,
                NotificationOutbox.event_id == event.id,
                NotificationOutbox.purpose == "agenda_evt7",
            )
        ).scalar_one()
        if due_at is not None:
            row.due_at = due_at
        assert type(row.id) is uuid.UUID
        return row.id, event.id


def _set_outbox(turn, outbox_id: uuid.UUID, **values: object) -> None:
    with turn.factory.begin() as session:
        mark_tenant_scoped(session, _IGREJA, source="notification_outbox_quota_prepare")
        row = session.execute(
            select(NotificationOutbox).where(
                NotificationOutbox.igreja_id == _IGREJA,
                NotificationOutbox.id == outbox_id,
            )
        ).scalar_one()
        for field, value in values.items():
            setattr(row, field, value)


def _delete_event(turn, event_id: uuid.UUID) -> None:
    with turn.factory.begin() as session:
        mark_tenant_scoped(session, _IGREJA, source="notification_outbox_quota_remove_source")
        event = session.execute(
            select(Event).where(Event.igreja_id == _IGREJA, Event.id == event_id)
        ).scalar_one()
        session.delete(event)


def _rows_by_id(turn) -> dict[uuid.UUID, object]:
    return {row.id: row for row in _scoped_rows(turn, NotificationOutbox)}


def _transport_time(turn, *, day_offset: int, hour: int, minute: int) -> dt.datetime:
    day = turn.dispatch_at.astimezone(notification_outbox.SAO_PAULO_TZ).date()
    local = dt.datetime.combine(
        day + dt.timedelta(days=day_offset),
        dt.time(hour=hour, minute=minute),
        tzinfo=notification_outbox.SAO_PAULO_TZ,
    )
    return local.astimezone(dt.UTC)


def test_agenda_reminder_and_evt7_share_two_slots_under_concurrent_dispatch(
    agenda_reminder_turn, monkeypatch: pytest.MonkeyPatch
):
    turn = agenda_reminder_turn
    _assert_v2b_rls_is_forced(turn)
    agenda = _agenda_row(turn, monkeypatch, suffix="QUOTA-CONCURRENT")
    now = turn.dispatch_at + dt.timedelta(minutes=2)
    evt7_a, _ = _enqueue_evt7(turn, label="concurrent-a", now=now, due_at=now)
    evt7_b, _ = _enqueue_evt7(turn, label="concurrent-b", now=now, due_at=now)
    provider = _QuotaProvider()
    barrier = threading.Barrier(3)

    def run(worker_number: int) -> int:
        barrier.wait(timeout=10)
        return notification_outbox.dispatch_notification_outbox(
            turn.factory,
            provider,
            worker_id=f"quota-concurrent-{worker_number}",
            now=now,
            limit=1,
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = tuple(pool.submit(run, number) for number in range(3))
        results = tuple(future.result(timeout=30) for future in futures)

    rows = _rows_by_id(turn)
    relevant = (agenda.id, evt7_a, evt7_b)
    target_day = now.astimezone(notification_outbox.SAO_PAULO_TZ).date()
    assert sum(results) == 2
    assert len(provider.calls) == 2
    assert sum(rows[row_id].state == "enviado" for row_id in relevant) == 2
    assert sum(
        rows[row_id].state == "cancelado"
        and rows[row_id].terminal_reason == "limite_diario"
        for row_id in relevant
    ) == 1
    assert {rows[row_id].delivery_reservation_day for row_id in relevant} == {target_day}


def test_old_delayed_intent_cannot_displace_two_current_day_sends(
    agenda_reminder_turn, monkeypatch: pytest.MonkeyPatch
):
    turn = agenda_reminder_turn
    _assert_v2b_rls_is_forced(turn)
    agenda = _agenda_row(turn, monkeypatch, suffix="QUOTA-LATE")
    start = turn.dispatch_at + dt.timedelta(minutes=2)
    _set_outbox(
        turn,
        agenda.id,
        created_at=start - dt.timedelta(days=30),
        due_at=start + dt.timedelta(minutes=3),
    )
    evt7_current, _ = _enqueue_evt7(
        turn, label="current-a", now=start, due_at=start
    )
    evt7_second, _ = _enqueue_evt7(
        turn, label="current-b", now=start, due_at=start + dt.timedelta(seconds=1)
    )

    first_provider = _QuotaProvider()
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory,
        first_provider,
        worker_id="quota-current-two",
        now=start + dt.timedelta(minutes=2),
        limit=2,
    ) == 2
    assert len(first_provider.calls) == 2

    late_provider = _QuotaProvider()
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory,
        late_provider,
        worker_id="quota-old-delayed",
        now=start + dt.timedelta(minutes=4),
        limit=1,
    ) == 0
    rows = _rows_by_id(turn)
    target_day = start.astimezone(notification_outbox.SAO_PAULO_TZ).date()
    assert rows[evt7_current].state == rows[evt7_second].state == "enviado"
    assert rows[agenda.id].state == "cancelado"
    assert rows[agenda.id].terminal_reason == "limite_diario"
    assert rows[agenda.id].delivery_reservation_day == target_day
    assert late_provider.calls == []


def test_proven_pre_send_retry_crossing_midnight_competes_for_new_day_quota(
    agenda_reminder_turn, monkeypatch: pytest.MonkeyPatch
):
    turn = agenda_reminder_turn
    _assert_v2b_rls_is_forced(turn)
    agenda = _agenda_row(turn, monkeypatch, suffix="QUOTA-RETRY")
    first_attempt_at = _transport_time(turn, day_offset=0, hour=20, minute=59)
    retry_provider = _QuotaProvider(
        BroadcastSendResult(status="falhou_retentavel", error_class="connect_timeout")
    )
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory,
        retry_provider,
        worker_id="quota-retry-day-one",
        now=first_attempt_at,
        limit=1,
    ) == 1
    rows = _rows_by_id(turn)
    first_day = first_attempt_at.astimezone(notification_outbox.SAO_PAULO_TZ).date()
    assert rows[agenda.id].state == "retry"
    assert rows[agenda.id].attempts == 1
    assert rows[agenda.id].delivery_reservation_day == first_day

    next_day = _transport_time(turn, day_offset=1, hour=8, minute=1)
    evt7_a, _ = _enqueue_evt7(turn, label="retry-next-day-a", now=next_day, due_at=next_day)
    evt7_b, _ = _enqueue_evt7(turn, label="retry-next-day-b", now=next_day, due_at=next_day)
    second_provider = _QuotaProvider()
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory,
        second_provider,
        worker_id="quota-retry-day-two",
        now=next_day,
        limit=3,
    ) == 2
    rows = _rows_by_id(turn)
    second_day = next_day.astimezone(notification_outbox.SAO_PAULO_TZ).date()
    assert rows[agenda.id].state == "enviado"
    assert rows[agenda.id].attempts == 1
    assert rows[agenda.id].delivery_reservation_day == second_day
    assert sum(rows[row_id].state == "enviado" for row_id in (agenda.id, evt7_a, evt7_b)) == 2
    assert sum(
        rows[row_id].state == "cancelado"
        and rows[row_id].terminal_reason == "limite_diario"
        for row_id in (agenda.id, evt7_a, evt7_b)
    ) == 1
    assert len(second_provider.calls) == 2


def test_ambiguous_and_removed_origin_keep_their_daily_reservations(
    agenda_reminder_turn, monkeypatch: pytest.MonkeyPatch
):
    turn = agenda_reminder_turn
    _assert_v2b_rls_is_forced(turn)
    agenda = _agenda_row(turn, monkeypatch, suffix="QUOTA-AMBIGUOUS")
    now = turn.dispatch_at + dt.timedelta(minutes=5)
    removed, removed_event = _enqueue_evt7(
        turn, label="removed-origin", now=now, due_at=now + dt.timedelta(seconds=1)
    )
    candidate, _ = _enqueue_evt7(
        turn, label="third-candidate", now=now, due_at=now + dt.timedelta(seconds=2)
    )
    _delete_event(turn, removed_event)

    ambiguous_provider = _QuotaProvider(
        BroadcastSendResult(status="desconhecido", error_class="provider_timeout")
    )
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory,
        ambiguous_provider,
        worker_id="quota-ambiguous",
        now=now + dt.timedelta(minutes=1),
        limit=1,
    ) == 1
    assert len(ambiguous_provider.calls) == 1

    removed_provider = _QuotaProvider()
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory,
        removed_provider,
        worker_id="quota-removed-origin",
        now=now + dt.timedelta(minutes=1),
        limit=1,
    ) == 0
    candidate_provider = _QuotaProvider()
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory,
        candidate_provider,
        worker_id="quota-third-candidate",
        now=now + dt.timedelta(minutes=1),
        limit=1,
    ) == 0

    rows = _rows_by_id(turn)
    target_day = now.astimezone(notification_outbox.SAO_PAULO_TZ).date()
    assert rows[agenda.id].state == "ambiguo"
    assert rows[removed].state == "obsoleto"
    assert rows[candidate].state == "cancelado"
    assert rows[candidate].terminal_reason == "limite_diario"
    assert {rows[row_id].delivery_reservation_day for row_id in (agenda.id, removed, candidate)} == {
        target_day
    }
    assert removed_provider.calls == []
    assert candidate_provider.calls == []


def test_intent_identity_keeps_distinct_occurrence_recipient_purpose_and_tenant(
    agenda_reminder_turn, monkeypatch: pytest.MonkeyPatch
):
    """The exact intent is closed, while the four identity dimensions stay live."""

    turn = agenda_reminder_turn
    _assert_v2b_rls_is_forced(turn)
    agenda = _agenda_row(turn, monkeypatch, suffix="QUOTA-IDENTITY")
    actor_pessoa_id = _actor_pessoa_id(turn)
    now = turn.dispatch_at + dt.timedelta(minutes=9)
    _ensure_evt7_recipient(turn)

    with turn.factory.begin() as session:
        mark_tenant_scoped(session, _IGREJA, source="notification_outbox_quota_identity_a")
        target = session.execute(
            select(Pessoa).where(Pessoa.igreja_id == _IGREJA, Pessoa.id == turn.target_id)
        ).scalar_one()
        if session.execute(
            select(ConsentRecord).where(
                ConsentRecord.igreja_id == _IGREJA,
                ConsentRecord.pessoa_id == target.id,
                ConsentRecord.termo_versao == _TERM,
            )
        ).scalar_one_or_none() is None:
            session.add(
                ConsentRecord(
                    igreja_id=_IGREJA,
                    pessoa_id=target.id,
                    termo_versao=_TERM,
                    aceite_em=now - dt.timedelta(minutes=1),
                )
            )
        session.add(
            WhatsappReminderPreference(
                igreja_id=_IGREJA,
                pessoa_id=target.id,
                reminder_kind="agenda",
                state="active",
                term_version=_TERM,
                accepted_at=now - dt.timedelta(minutes=1),
                changed_at=now,
            )
        )
        session.add(
            AgendaAlertRecipient(
                igreja_id=_IGREJA,
                nome="Segundo destinatário sintético",
                telefone=target.telefone,
                pessoa_id=target.id,
                ativo=True,
            )
        )
        event = Event(
            id=uuid.uuid4(),
            igreja_id=_IGREJA,
            titulo="Evento de identidade sintético",
            tipo="culto",
            status="confirmado",
            data=now.astimezone(notification_outbox.SAO_PAULO_TZ).date() + dt.timedelta(days=3),
            hora="19:30",
            recorrencia="pontual",
            confirmado_em=now - dt.timedelta(minutes=1),
            confirmado_por=None,
            notification_outbox_fenced_at=None,
            notificado_em=None,
        )
        session.add(event)
        session.flush()
        assert notification_outbox.enqueue_evt7_for_confirmed_event(session, event, now=now) == 2
        session.flush()
        evt7_rows = tuple(
            session.execute(
                select(NotificationOutbox).where(
                    NotificationOutbox.igreja_id == _IGREJA,
                    NotificationOutbox.event_id == event.id,
                    NotificationOutbox.purpose == "agenda_evt7",
                )
            ).scalars()
        )
        assert {row.pessoa_id for row in evt7_rows} == {actor_pessoa_id, target.id}
        assert {row.occurrence_at for row in evt7_rows} == {event.confirmado_em}
        assert agenda.occurrence_at != event.confirmado_em

        exact_duplicate = NotificationOutbox(
            igreja_id=agenda.igreja_id,
            pessoa_id=agenda.pessoa_id,
            agenda_alert_recipient_id=agenda.agenda_alert_recipient_id,
            event_id=agenda.event_id,
            reuniao_id=agenda.reuniao_id,
            agenda_subscription_id=agenda.agenda_subscription_id,
            origin_kind=agenda.origin_kind,
            origin_id=agenda.origin_id,
            occurrence_at=agenda.occurrence_at,
            origin_fingerprint=agenda.origin_fingerprint,
            purpose=agenda.purpose,
            state="pendente",
            due_at=agenda.due_at,
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
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(exact_duplicate)
                session.flush()

    tenant_b = uuid.uuid4()
    pessoa_b = uuid.uuid4()
    event_b = uuid.uuid4()
    monkeypatch.setenv("WHATSAPP_PILOTO_IGREJA_IDS", f"{_IGREJA},{tenant_b}")
    monkeypatch.setenv("AGENDA_WHATSAPP_ENABLED_IGREJA_IDS", f"{_IGREJA},{tenant_b}")
    monkeypatch.setenv("AGENT_PRIVILEGE_ENABLED_IGREJA_IDS", f"{_IGREJA},{tenant_b}")
    get_settings.cache_clear()
    with turn.factory.begin() as session:
        session.add(Igreja(id=tenant_b, nome="Igreja B sintética"))
    with turn.factory.begin() as session:
        mark_tenant_scoped(session, tenant_b, source="notification_outbox_quota_identity_b")
        session.add(Pessoa(
            id=pessoa_b,
            igreja_id=tenant_b,
            nome="Pessoa B sintética",
            telefone="5500000000099",
        ))
        session.flush()
        session.add_all((
            ConsentRecord(
                igreja_id=tenant_b,
                pessoa_id=pessoa_b,
                termo_versao=_TERM,
                aceite_em=now - dt.timedelta(minutes=1),
            ),
            WhatsappReminderPreference(
                igreja_id=tenant_b,
                pessoa_id=pessoa_b,
                reminder_kind="agenda",
                state="active",
                term_version=_TERM,
                accepted_at=now - dt.timedelta(minutes=1),
                changed_at=now,
            ),
            AgendaAlertRecipient(
                igreja_id=tenant_b,
                nome="Destinatário B sintético",
                telefone="5500000000099",
                pessoa_id=pessoa_b,
                ativo=True,
            ),
            Event(
                id=event_b,
                igreja_id=tenant_b,
                titulo="Evento B sintético",
                tipo="culto",
                status="confirmado",
                data=now.astimezone(notification_outbox.SAO_PAULO_TZ).date() + dt.timedelta(days=3),
                hora="19:30",
                recorrencia="pontual",
                confirmado_em=now - dt.timedelta(minutes=1),
                confirmado_por=None,
                notification_outbox_fenced_at=None,
                notificado_em=None,
            ),
        ))
        session.flush()
        source_b = session.execute(
            select(Event).where(Event.igreja_id == tenant_b, Event.id == event_b)
        ).scalar_one()
        assert notification_outbox.enqueue_evt7_for_confirmed_event(session, source_b, now=now) == 1

    session = turn.factory()
    try:
        mark_tenant_scoped(session, tenant_b, source="notification_outbox_quota_identity_b_assert")
        assert session.execute(
            text("select rolbypassrls from pg_roles where rolname = current_user")
        ).scalar_one() is False
        rows_b = tuple(session.execute(select(NotificationOutbox)).scalars())
        assert len(rows_b) == 1
        assert rows_b[0].igreja_id == tenant_b and rows_b[0].event_id == event_b
    finally:
        session.rollback()
        session.close()

    session = turn.factory()
    try:
        mark_tenant_scoped(session, _IGREJA, source="notification_outbox_quota_identity_a_assert")
        assert all(
            row.igreja_id == _IGREJA
            for row in session.execute(select(NotificationOutbox)).scalars()
        )
    finally:
        session.rollback()
        session.close()
