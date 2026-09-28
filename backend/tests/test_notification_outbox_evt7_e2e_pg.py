"""EVT-7 through the authenticated confirmation route and common dispatcher."""
from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import get_settings
from app.db.models import (
    AgendaAlertRecipient,
    Conversation,
    Event,
    NotificationOutbox,
    WhatsappConnection,
    WhatsappReminderPreference,
)
from app.db.session import get_db
from app.db.tenant_session import mark_tenant_scoped
from app.services import notification_outbox, whatsapp_agenda, whatsapp_privilege
from app.services.clerk import get_clerk_client
from app.services.notification_outbox import dispatch_notification_outbox
from tests.conftest import FakeClerk
from tests.test_agent_privileged_turn_pg import (  # noqa: F401 - fixture dependencies
    _ClassifiedEvolution,
    _IGREJA,
    _TERM,
    _rows,
    msg_engine_fx,
    rls_database_url,
    s3_turn,
)
from tests.test_messages_inbound_idempotency import _SCHEMA as _MSG_SCHEMA


pytestmark = pytest.mark.rls_integration
_AUTH = {"Authorization": "Bearer evt7-synthetic"}
_MIGRATION = Path(__file__).parents[1] / "migrations" / "20260927_220000_notification_outbox_v2b.sql"


def _install_v2b_runtime(engine) -> None:
    """Apply the frozen SQL with only the disposable schema name adapted."""

    migration = _MIGRATION.read_text(encoding="utf-8").replace(
        "public.", f"{_MSG_SCHEMA}."
    )
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.execute(migration)
            raw.commit()
        finally:
            cursor.close()
    finally:
        raw.close()


@pytest.fixture
def evt7_turn(s3_turn, monkeypatch):
    """Seed a pastor, linked internal recipient, consent and current preference."""

    _install_v2b_runtime(s3_turn.engine)
    monkeypatch.setenv("AGENT_TERM_VERSION", _TERM)
    monkeypatch.setenv("ALLOW_REAL_SENDS", "true")
    monkeypatch.setenv("WHATSAPP_PILOTO_IGREJA_IDS", str(_IGREJA))
    monkeypatch.setenv("AGENDA_NOTIFY_ENABLED", "true")
    monkeypatch.setenv("AGENDA_WHATSAPP_ENABLED_IGREJA_IDS", str(_IGREJA))
    monkeypatch.setenv("AGENT_PRIVILEGE_ENABLED_IGREJA_IDS", str(_IGREJA))
    monkeypatch.setattr(
        whatsapp_agenda, "AGENDA_WHATSAPP_APPROVED_RELEASE_ID", "evt7-e2e"
    )
    monkeypatch.setattr(
        whatsapp_privilege, "PRIVILEGE_APPROVED_RELEASE_ID", "evt7-e2e"
    )
    get_settings.cache_clear()
    with s3_turn.factory.begin() as session:
        conversation = session.get(Conversation, s3_turn.conversation_id)
        assert conversation is not None and conversation.pessoa_id is not None
        connection = session.execute(
            select(WhatsappConnection).where(WhatsappConnection.igreja_id == _IGREJA)
        ).scalar_one()
        connection.status = "online"
        pessoa_id = conversation.pessoa_id
        event = Event(
            id=uuid.uuid4(),
            igreja_id=_IGREJA,
            titulo="Culto sintético",
            tipo="culto",
            status="a_confirmar",
            data=dt.date.today() + dt.timedelta(days=2),
            hora="19:00",
            recorrencia="pontual",
            confirmado_em=None,
            confirmado_por=None,
        )
        session.add(event)
        session.flush()
        session.add(
            AgendaAlertRecipient(
                igreja_id=_IGREJA,
                pessoa_id=pessoa_id,
                nome="Secretaria sintética",
                telefone=conversation.telefone,
                ativo=True,
            )
        )
        session.add(
            WhatsappReminderPreference(
                igreja_id=_IGREJA,
                pessoa_id=pessoa_id,
                reminder_kind="agenda",
                state="active",
                term_version=_TERM,
                accepted_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1),
                changed_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1),
            )
        )
    try:
        yield s3_turn, event.id
    finally:
        get_settings.cache_clear()


def _client(app, turn):
    session = turn.factory()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk(
        clerk_user_id="clerk-s3-synthetic"
    )
    return TestClient(app), session


def _factory_with_statement_timeout(factory):
    """Make an unexpected PG wait fail the lock test deterministically."""

    def timed_factory():
        session = factory()
        session.execute(text("set local statement_timeout = '1500ms'"))
        return session

    return timed_factory


def _assert_evt7_rls_is_forced(turn) -> None:
    """Migration policies must exist before the route is exercised as a human."""

    session = turn.factory()
    try:
        mark_tenant_scoped(session, _IGREJA, source="evt7_e2e_rls_structure")
        assert session.execute(
            text("select rolbypassrls from pg_roles where rolname = current_user")
        ).scalar_one() is False
        assert session.execute(
            text(
                "select count(*) = 3 and bool_and(relrowsecurity and relforcerowsecurity) "
                "from pg_class where relnamespace = current_schema()::regnamespace "
                "and relname in ('whatsapp_reminder_preferences', "
                "'agenda_reminder_subscriptions', 'notification_outbox')"
            )
        ).scalar_one() is True
        policies = set(
            session.execute(
                text(
                    "select policyname from pg_policies "
                    "where schemaname = current_schema() "
                    "and policyname in ('whatsapp_reminder_preferences_human_agenda_select', "
                    "'notification_outbox_human_evt7_select', "
                    "'notification_outbox_human_evt7_insert', "
                    "'notification_outbox_worker_only')"
                )
            ).scalars()
        )
        assert policies == {
            "whatsapp_reminder_preferences_human_agenda_select",
            "notification_outbox_human_evt7_select",
            "notification_outbox_human_evt7_insert",
            "notification_outbox_worker_only",
        }
    finally:
        session.rollback()
        session.close()


def _evt7_rows(turn):
    return [
        row
        for row in _rows(turn, NotificationOutbox)
        if row.purpose == "agenda_evt7"
    ]


def _confirm_evt7(app, turn, event_id: uuid.UUID) -> NotificationOutbox:
    client, session = _client(app, turn)
    try:
        response = client.post(f"/events/{event_id}/confirm", headers=_AUTH, json={})
    finally:
        client.close()
        session.close()
    assert response.status_code == 200, response.text
    rows = _evt7_rows(turn)
    assert len(rows) == 1
    return rows[0]


def _after_hours_created_at() -> dt.datetime:
    local = dt.datetime.now(dt.UTC).astimezone(notification_outbox.SAO_PAULO_TZ)
    created = local.replace(hour=22, minute=0, second=0, microsecond=0)
    if created <= local:
        created += dt.timedelta(days=1)
    return created.astimezone(dt.UTC)


def _align_evt7_pre_send_window(turn) -> tuple[dt.datetime, dt.datetime]:
    created_at = _after_hours_created_at()
    first_due = notification_outbox.next_transport_window(created_at)
    deadline = notification_outbox._evt7_pre_send_deadline(created_at)
    assert first_due is not None and deadline is not None
    with turn.factory.begin() as session:
        row = session.execute(
            select(NotificationOutbox).where(
                NotificationOutbox.igreja_id == _IGREJA,
                NotificationOutbox.purpose == "agenda_evt7",
            )
        ).scalar_one()
        row.created_at = created_at
        row.updated_at = created_at
        row.due_at = first_due
    return first_due, deadline


class _Evt7Evolution(_ClassifiedEvolution):
    def __init__(self, turn) -> None:
        super().__init__()
        self.turn = turn

    def send_text_classificado(self, instance, telefone, texto):
        assert self.turn.engine.pool.checkedout() == 0
        rows = _evt7_rows(self.turn)
        assert len(rows) == 1
        row = rows[0]
        assert row.state == "em_envio"
        assert row.claim_token is not None and row.claimed_until is not None
        assert row.transport_started_at is not None
        return super().send_text_classificado(instance, telefone, texto)


def test_confirm_route_atomically_enqueues_evt7_then_common_dispatcher_delivers(
    evt7_turn, app, monkeypatch
):
    turn, event_id = evt7_turn
    _assert_evt7_rls_is_forced(turn)
    from app.routers import events as events_router

    original_enqueue = events_router.enqueue_evt7_for_confirmed_event

    def assert_human_rls_then_enqueue(session, event):
        assert session.execute(text("select current_user")).scalar_one() == "authenticated"
        assert session.execute(
            text("select rolbypassrls from pg_roles where rolname = current_user")
        ).scalar_one() is False
        assert session.execute(
            text("select current_setting('request.jwt.claims', true)::jsonb ->> 'sub'")
        ).scalar_one() == "clerk-s3-synthetic"
        return original_enqueue(session, event)

    monkeypatch.setattr(events_router, "enqueue_evt7_for_confirmed_event", assert_human_rls_then_enqueue)
    client, session = _client(app, turn)
    try:
        response = client.post(f"/events/{event_id}/confirm", headers=_AUTH, json={})
    finally:
        client.close()
        session.close()

    assert response.status_code == 200, response.text
    rows = _evt7_rows(turn)
    assert len(rows) == 1
    row = rows[0]
    assert row.state == "pendente"
    assert row.attempts == 0
    assert row.claim_token is None and row.transport_started_at is None
    assert row.sent_at is None and row.delivery_reservation_day is None
    with turn.factory() as verify:
        event = verify.get(Event, event_id)
        assert event is not None and event.status == "confirmado"
        assert event.notificado_em is None

    provider = _Evt7Evolution(turn)
    dispatched = dispatch_notification_outbox(
        turn.factory,
        provider,
        worker_id="evt7-e2e-worker",
        now=row.due_at,
    )
    assert dispatched == 1
    assert len(provider.calls) == 1
    assert "PARAR LEMBRETES" in provider.calls[0][2]
    delivered = _evt7_rows(turn)[0]
    assert delivered.state == "enviado"
    assert delivered.sent_at is not None
    assert delivered.terminal_reason == "aviso_parada_incluido"

    retry = _client(app, turn)
    retry_client, retry_session = retry
    try:
        repeated = retry_client.post(f"/events/{event_id}/confirm", headers=_AUTH, json={})
    finally:
        retry_client.close()
        retry_session.close()
    assert repeated.status_code == 409
    assert len(_evt7_rows(turn)) == 1


def test_pending_pastor_is_rejected_before_event_or_outbox_write(evt7_turn, app):
    from app.db.models import AppUser

    turn, event_id = evt7_turn
    _assert_evt7_rls_is_forced(turn)
    with turn.factory.begin() as session:
        actor = session.get(AppUser, turn.app_user_id)
        assert actor is not None
        actor.status = "convidado"

    client, session = _client(app, turn)
    try:
        response = client.post(f"/events/{event_id}/confirm", headers=_AUTH, json={})
    finally:
        client.close()
        session.close()

    assert response.status_code == 403
    assert _evt7_rows(turn) == []
    with turn.factory() as verify:
        event = verify.execute(
            select(Event).where(Event.igreja_id == _IGREJA, Event.id == event_id)
        ).scalar_one()
        assert event.status == "a_confirmar"


@pytest.mark.parametrize("failure", ("source_locked", "connection_unavailable"))
def test_evt7_pre_send_deferrals_expire_without_provider_attempts(
    evt7_turn, app, failure: str
):
    turn, event_id = evt7_turn
    _assert_evt7_rls_is_forced(turn)
    _confirm_evt7(app, turn, event_id)
    first_due, deadline = _align_evt7_pre_send_window(turn)
    lock_connection = None
    lock_transaction = None
    if failure == "source_locked":
        # Keep a physical connection separate from the worker factory.  The
        # lock is real, while finite timeouts make an accidental blocking query
        # fail the test instead of leaving an orphaned PG process.
        lock_connection = turn.engine.connect()
        lock_transaction = lock_connection.begin()
        lock_connection.execute(text("set local lock_timeout = '250ms'"))
        lock_connection.execute(text("set local statement_timeout = '5s'"))
        lock_connection.execute(
            select(Event)
            .where(Event.igreja_id == _IGREJA, Event.id == event_id)
            .with_for_update()
        ).scalar_one()
    else:
        with turn.factory.begin() as session:
            connection = session.execute(
                select(WhatsappConnection).where(WhatsappConnection.igreja_id == _IGREJA)
            ).scalar_one()
            connection.status = "offline"

    provider = _ClassifiedEvolution()
    worker_factory = (
        _factory_with_statement_timeout(turn.factory)
        if failure == "source_locked"
        else turn.factory
    )
    try:
        for current in (first_due, first_due + dt.timedelta(minutes=1), deadline):
            assert dispatch_notification_outbox(
                worker_factory,
                provider,
                worker_id=f"evt7-{failure}",
                now=current,
            ) == 0
    finally:
        if lock_transaction is not None:
            lock_transaction.rollback()
        if lock_connection is not None:
            lock_connection.close()

    row = _evt7_rows(turn)[0]
    assert provider.calls == []
    assert row.state == "cancelado"
    assert row.terminal_reason == "pre_envio_expirado"
    assert row.attempts == 0
    assert row.transport_started_at is None


def test_evt7_late_dispatch_expires_before_any_provider_call(evt7_turn, app):
    turn, event_id = evt7_turn
    _assert_evt7_rls_is_forced(turn)
    _confirm_evt7(app, turn, event_id)
    _first_due, deadline = _align_evt7_pre_send_window(turn)
    provider = _ClassifiedEvolution()

    assert dispatch_notification_outbox(
        turn.factory,
        provider,
        worker_id="evt7-late-dispatch",
        now=deadline + dt.timedelta(seconds=1),
    ) == 0

    row = _evt7_rows(turn)[0]
    assert provider.calls == []
    assert row.state == "cancelado"
    assert row.terminal_reason == "pre_envio_expirado"
    assert row.attempts == 0
