"""V2b Agenda reminder through the real S3 worker and disposable PostgreSQL.

Only LLM choices and provider transport are faked. The inbound anchor, S3
router, server catalogue, confirmation, durable effect, receipt and outbox
dispatcher all use the application code and a NOBYPASSRLS database role.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import uuid

import pytest
from sqlalchemy import select, text

from app.config import Settings, get_settings
from app.db.models import (
    AgendaReminderSubscription,
    AgentActionProposal,
    AgentActionReceipt,
    ConsentRecord,
    Conversation,
    Event,
    NotificationOutbox,
    Pessoa,
    WhatsappConnection,
    WhatsappReminderPreference,
)
from app.db.rls_observability import probe_tenant_scope
from app.db.tenant_session import mark_tenant_scoped
from app.services import notification_outbox
from app.services.llm import LLMClient, LLMUsage, TypedChoiceResult
from app.workers import queue_worker as worker_module
from tests.test_agent_privileged_turn_pg import (  # noqa: F401 - fixtures
    _ClassifiedEvolution,
    _IGREJA,
    _TERM,
    _inbound,
    msg_engine_fx,
    rls_database_url,
    s3_turn,
)
from tests.test_messages_inbound_idempotency import _SCHEMA as _MSG_SCHEMA
from tests.test_whatsapp_agenda_pg import agenda_turn  # noqa: F401 - fixture


pytestmark = pytest.mark.rls_integration
_MIGRATION = Path(__file__).parents[1] / "migrations" / "20260927_220000_notification_outbox_v2b.sql"
_REAL_PILOT_GATE = Settings.whatsapp_piloto


def _install_v2b_runtime(engine) -> None:
    """Apply the immutable V2b migration to MSG-IDEMP's isolated schema."""

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
def agenda_reminder_turn(agenda_turn, monkeypatch: pytest.MonkeyPatch):
    """Activate only the synthetic gates and prepare one future occurrence."""

    turn = agenda_turn
    _install_v2b_runtime(turn.engine)
    monkeypatch.setattr(Settings, "whatsapp_piloto", _REAL_PILOT_GATE)
    monkeypatch.setenv("AGENT_TERM_VERSION", _TERM)
    monkeypatch.setenv("ALLOW_REAL_SENDS", "true")
    monkeypatch.setenv("WHATSAPP_PILOTO_IGREJA_IDS", str(_IGREJA))
    monkeypatch.setenv("AGENDA_NOTIFY_ENABLED", "true")
    get_settings.cache_clear()

    current = dt.datetime.now(dt.UTC)
    dispatch_at = notification_outbox.next_transport_window(
        current + dt.timedelta(days=1)
    )
    assert dispatch_at is not None
    event_date = dispatch_at.astimezone(notification_outbox.SAO_PAULO_TZ).date()
    with turn.factory.begin() as session:
        event = session.execute(
            select(Event).where(Event.igreja_id == _IGREJA)
        ).scalar_one()
        event.data = event_date + dt.timedelta(days=1)
        event.hora = "19:30"
        event.publico_alvo = ["toda_igreja"]
        event.notificar_em = dispatch_at
        event.notificado_em = None
        event.notification_outbox_fenced_at = None
        event.notification_outbox_fence_reason = None
        conversation = session.get(Conversation, turn.conversation_id)
        assert conversation is not None
        for consent in session.execute(
            select(ConsentRecord).where(
                ConsentRecord.igreja_id == _IGREJA,
                ConsentRecord.pessoa_id == conversation.pessoa_id,
            )
        ).scalars():
            consent.aceite_em = current - dt.timedelta(minutes=1)
        connection = session.execute(
            select(WhatsappConnection).where(
                WhatsappConnection.igreja_id == _IGREJA
            )
        ).scalar_one()
        connection.status = "online"
    turn.dispatch_at = dispatch_at
    yield turn
    get_settings.cache_clear()


def _scoped_rows(turn, model):
    session = turn.factory()
    try:
        mark_tenant_scoped(
            session, _IGREJA, source="agenda_reminder_subscription_e2e_assert"
        )
        scope = probe_tenant_scope(session)
        assert scope.is_scoped and scope.igreja_id == str(_IGREJA)
        assert session.execute(
            text("select rolbypassrls from pg_roles where rolname = current_user")
        ).scalar_one() is False
        rows = session.execute(
            select(model).where(model.igreja_id == _IGREJA)
        ).scalars().all()
        session.expunge_all()
        return rows
    finally:
        session.rollback()
        session.close()


def _assert_v2b_rls_is_forced(turn) -> None:
    session = turn.factory()
    try:
        mark_tenant_scoped(
            session, _IGREJA, source="agenda_reminder_subscription_e2e_rls"
        )
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
    finally:
        session.rollback()
        session.close()


def _reminder_choices(monkeypatch: pytest.MonkeyPatch, turn) -> list[str]:
    stages: list[str] = []

    def choose(_self, _system, prompt, *, schema_name, choices, timeout_seconds):
        assert turn.engine.pool.checkedout() == 0
        assert timeout_seconds > 0
        stages.append(schema_name)
        payload = json.loads(prompt)
        if schema_name == "s3_route":
            selected = "restrita"
        elif schema_name == "s3_tool":
            assert "configurar_lembrete_agenda" in payload["ferramentas"]
            selected = "configurar_lembrete_agenda"
        elif schema_name == "s3_handle":
            selected = next(
                handle
                for handle, summary in payload["candidatos"].items()
                if summary.startswith("Ativar lembretes da Agenda")
            )
        else:
            pytest.fail(f"etapa LLM inesperada: {schema_name}")
        assert selected in choices
        return TypedChoiceResult(
            selected,
            LLMUsage(modelo="agenda-reminder-synthetic", tokens_in=3, tokens_out=1, custo=0.0),
        )

    monkeypatch.setattr(LLMClient, "generate_typed", choose)
    return stages


class _ReceiptEvolution(_ClassifiedEvolution):
    def __init__(self, turn):
        super().__init__()
        self.turn = turn

    def send_text_classificado(self, instance, telefone, texto):
        assert self.turn.engine.pool.checkedout() == 0
        if "Comprovante:" in texto:
            receipts = _scoped_rows(self.turn, AgentActionReceipt)
            outbox_rows = _scoped_rows(self.turn, NotificationOutbox)
            assert len(receipts) == 1
            assert len(outbox_rows) == 1 and outbox_rows[0].state == "pendente"
        return super().send_text_classificado(instance, telefone, texto)


class _OutboxEvolution(_ClassifiedEvolution):
    def __init__(self, turn):
        super().__init__()
        self.turn = turn

    def send_text_classificado(self, instance, telefone, texto):
        assert self.turn.engine.pool.checkedout() == 0
        rows = _scoped_rows(self.turn, NotificationOutbox)
        assert len(rows) == 1
        assert rows[0].state == "em_envio"
        assert rows[0].claim_token is not None and rows[0].claimed_until is not None
        assert "PARAR LEMBRETES" in texto
        return super().send_text_classificado(instance, telefone, texto)


def _request_and_confirm(turn, monkeypatch: pytest.MonkeyPatch, *, suffix: str):
    stages = _reminder_choices(monkeypatch, turn)
    evolution = _ReceiptEvolution(turn)
    request = _inbound(
        turn,
        f"AGENDA-REMINDER-REQUEST-{suffix}",
        "Me avise do próximo evento da agenda.",
    )
    assert worker_module.run_agent_for_message(
        turn.factory, request, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    proposals = _scoped_rows(turn, AgentActionProposal)
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.action == "configurar_lembrete_agenda"
    assert proposal.state == "pendente" and proposal.delivered_at is not None
    assert proposal.summary_message_id is not None
    assert "Ativar lembretes da Agenda" in evolution.calls[0][2]

    confirmation = _inbound(turn, f"AGENDA-REMINDER-SIM-{suffix}", "SIM")
    assert worker_module.run_agent_for_message(
        turn.factory, confirmation, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    assert stages == ["s3_route", "s3_tool", "s3_handle"]
    assert len(evolution.calls) == 2
    assert "Lembrete confirmado. Comprovante:" in evolution.calls[1][2]
    return proposal


def test_agenda_reminder_s3_confirmation_creates_and_dispatches_outbox(
    agenda_reminder_turn, monkeypatch: pytest.MonkeyPatch
):
    turn = agenda_reminder_turn
    _assert_v2b_rls_is_forced(turn)
    proposal = _request_and_confirm(turn, monkeypatch, suffix="HAPPY")

    preferences = _scoped_rows(turn, WhatsappReminderPreference)
    subscriptions = _scoped_rows(turn, AgendaReminderSubscription)
    outbox_rows = _scoped_rows(turn, NotificationOutbox)
    receipts = _scoped_rows(turn, AgentActionReceipt)
    assert len(preferences) == 1
    assert preferences[0].reminder_kind == "agenda"
    assert preferences[0].state == "active" and preferences[0].term_version == _TERM
    assert len(subscriptions) == 1
    assert subscriptions[0].proposal_id == proposal.id and subscriptions[0].state == "active"
    assert len(outbox_rows) == 1
    assert outbox_rows[0].purpose == "agenda_reminder"
    assert outbox_rows[0].agenda_subscription_id == subscriptions[0].id
    assert outbox_rows[0].state == "pendente" and outbox_rows[0].attempts == 0
    assert len(receipts) == 1 and receipts[0].receipt_text == "Lembrete confirmado."

    provider = _OutboxEvolution(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory,
        provider,
        worker_id="agenda-reminder-e2e",
        now=turn.dispatch_at + dt.timedelta(seconds=1),
    ) == 1
    outbox_rows = _scoped_rows(turn, NotificationOutbox)
    assert len(provider.calls) == 1
    assert outbox_rows[0].state == "enviado" and outbox_rows[0].sent_at is not None
    assert outbox_rows[0].terminal_reason == "aviso_parada_incluido"


def test_agenda_reminder_dispatch_fence_blocks_audience_revoked_after_sim(
    agenda_reminder_turn, monkeypatch: pytest.MonkeyPatch
):
    turn = agenda_reminder_turn
    _request_and_confirm(turn, monkeypatch, suffix="FENCE")
    with turn.factory.begin() as session:
        event = session.execute(
            select(Event).where(Event.igreja_id == _IGREJA)
        ).scalar_one()
        event.publico_alvo = []

    provider = _OutboxEvolution(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory,
        provider,
        worker_id="agenda-reminder-fence-e2e",
        now=turn.dispatch_at + dt.timedelta(seconds=1),
    ) == 0
    assert provider.calls == []
    rows = _scoped_rows(turn, NotificationOutbox)
    assert len(rows) == 1 and rows[0].state == "obsoleto"


@pytest.mark.parametrize("stop_command", ("PARAR LEMBRETES", "SAIR"))
def test_old_agenda_reminder_sim_cannot_reactivate_after_real_stop_command(
    agenda_reminder_turn, monkeypatch: pytest.MonkeyPatch, stop_command: str
):
    turn = agenda_reminder_turn
    stages = _reminder_choices(monkeypatch, turn)
    evolution = _ReceiptEvolution(turn)
    request = _inbound(
        turn,
        f"AGENDA-REMINDER-STOP-REQUEST-{stop_command}",
        "Me avise do próximo evento da agenda.",
    )
    assert worker_module.run_agent_for_message(
        turn.factory, request, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    proposal = _scoped_rows(turn, AgentActionProposal)[0]
    assert proposal.state == "pendente"

    stop = _inbound(
        turn, f"AGENDA-REMINDER-STOP-{stop_command}", stop_command
    )
    assert worker_module.run_agent_for_message(
        turn.factory, stop, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    agenda_preferences = [
        row
        for row in _scoped_rows(turn, WhatsappReminderPreference)
        if row.reminder_kind == "agenda"
    ]
    assert len(agenda_preferences) == 1 and agenda_preferences[0].state == "disabled"
    if stop_command == "SAIR":
        people = _scoped_rows(turn, Pessoa)
        assert len(people) >= 1
        assert next(
            row for row in people if row.id == proposal.actor_pessoa_id
        ).optout is True

    old_confirmation = _inbound(
        turn, f"AGENDA-REMINDER-OLD-SIM-{stop_command}", "SIM"
    )
    assert worker_module.run_agent_for_message(
        turn.factory, old_confirmation, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    assert stages == ["s3_route", "s3_tool", "s3_handle"]
    assert _scoped_rows(turn, AgendaReminderSubscription) == []
    assert _scoped_rows(turn, NotificationOutbox) == []
    assert all(
        row.receipt_text != "Lembrete confirmado."
        for row in _scoped_rows(turn, AgentActionReceipt)
    )
    proposal = _scoped_rows(turn, AgentActionProposal)[0]
    assert proposal.state == "cancelada"

    provider = _OutboxEvolution(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory,
        provider,
        worker_id="agenda-reminder-stop-e2e",
        now=turn.dispatch_at + dt.timedelta(seconds=1),
    ) == 0
    assert provider.calls == []


def test_parar_then_new_future_occurrence_can_reactivate_only_the_new_intent(
    agenda_reminder_turn, monkeypatch: pytest.MonkeyPatch
):
    """A new resolved occurrence may opt in again; a stale SIM never may."""

    turn = agenda_reminder_turn
    _assert_v2b_rls_is_forced(turn)
    stages = _reminder_choices(monkeypatch, turn)
    evolution = _ReceiptEvolution(turn)
    initial_request = _inbound(
        turn,
        "AGENDA-REMINDER-REACTIVATE-INITIAL",
        "Me avise do próximo evento da agenda.",
    )
    assert worker_module.run_agent_for_message(
        turn.factory, initial_request, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    old_proposal = _scoped_rows(turn, AgentActionProposal)[0]
    assert old_proposal.state == "pendente"

    stop = _inbound(
        turn, "AGENDA-REMINDER-REACTIVATE-STOP", "PARAR LEMBRETES"
    )
    assert worker_module.run_agent_for_message(
        turn.factory, stop, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    proposals = {row.id: row for row in _scoped_rows(turn, AgentActionProposal)}
    assert proposals[old_proposal.id].state == "cancelada"
    assert _scoped_rows(turn, AgendaReminderSubscription) == []
    assert _scoped_rows(turn, NotificationOutbox) == []

    with turn.factory.begin() as session:
        mark_tenant_scoped(
            session, _IGREJA, source="agenda_reminder_reactivation_new_occurrence"
        )
        existing_event = session.execute(
            select(Event).where(Event.igreja_id == _IGREJA)
        ).scalar_one()
        assert existing_event.data is not None
        new_date = existing_event.data + dt.timedelta(days=7)
        new_event = Event(
            id=uuid.uuid4(),
            igreja_id=_IGREJA,
            titulo="Culto da Nova Ocorrência",
            tipo="culto",
            status="confirmado",
            data=new_date,
            hora="19:30",
            recorrencia="pontual",
            publico_alvo=["toda_igreja"],
            notificar_em=turn.dispatch_at,
            confirmado_em=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1),
            confirmado_por=existing_event.confirmado_por,
            notification_outbox_fenced_at=None,
            notification_outbox_fence_reason=None,
            notificado_em=None,
        )
        session.add(new_event)
        session.flush()
        new_event_id = new_event.id

    new_request = _inbound(
        turn,
        "AGENDA-REMINDER-REACTIVATE-NEW",
        f"Me avise do Culto da Nova Ocorrência em {new_date:%d/%m/%Y}.",
    )
    assert worker_module.run_agent_for_message(
        turn.factory, new_request, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    proposals = _scoped_rows(turn, AgentActionProposal)
    assert len(proposals) == 2
    new_proposal = next(row for row in proposals if row.id != old_proposal.id)
    assert new_proposal.state == "pendente"
    assert new_proposal.target_id == new_event_id
    assert new_proposal.arguments_json["event_id"] == str(new_event_id)

    new_confirmation = _inbound(
        turn, "AGENDA-REMINDER-REACTIVATE-SIM", "SIM"
    )
    assert worker_module.run_agent_for_message(
        turn.factory, new_confirmation, evolution_client=evolution
    ) is worker_module.AgentRunDisposition.COMPLETED
    assert stages == [
        "s3_route", "s3_tool", "s3_handle",
        "s3_route", "s3_tool", "s3_handle",
    ]
    preferences = _scoped_rows(turn, WhatsappReminderPreference)
    subscriptions = _scoped_rows(turn, AgendaReminderSubscription)
    outbox_rows = _scoped_rows(turn, NotificationOutbox)
    receipts = _scoped_rows(turn, AgentActionReceipt)
    proposals = {row.id: row for row in _scoped_rows(turn, AgentActionProposal)}
    agenda_preferences = [
        row for row in preferences if row.reminder_kind == "agenda"
    ]
    cell_report_preferences = [
        row for row in preferences if row.reminder_kind == "cell_report"
    ]
    assert len(agenda_preferences) == 1 and agenda_preferences[0].state == "active"
    assert (
        len(cell_report_preferences) == 1
        and cell_report_preferences[0].state == "disabled"
    )
    assert len(subscriptions) == 1
    assert subscriptions[0].proposal_id == new_proposal.id
    assert subscriptions[0].event_id == new_event_id
    assert len(outbox_rows) == 1
    assert outbox_rows[0].agenda_subscription_id == subscriptions[0].id
    assert outbox_rows[0].event_id == new_event_id
    assert len(receipts) == 1 and receipts[0].receipt_text == "Lembrete confirmado."
    assert proposals[old_proposal.id].state == "cancelada"

    provider = _OutboxEvolution(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory,
        provider,
        worker_id="agenda-reminder-reactivate-new-occurrence",
        now=turn.dispatch_at + dt.timedelta(seconds=1),
    ) == 1
    assert len(provider.calls) == 1
    assert _scoped_rows(turn, NotificationOutbox)[0].state == "enviado"
