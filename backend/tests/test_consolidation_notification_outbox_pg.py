"""PostgreSQL proof for the V3 consolidation notification producer and fence.

The fixture applies the literal V3 migration to an isolated schema, then makes
the worker run as the ``authenticated`` NOBYPASSRLS role.  The provider is a
fake; scheduling, claiming, fences and persisted state are production code.
"""

from __future__ import annotations

import datetime as dt
import os
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import (
    AgentConfig,
    AppUser,
    ConsentRecord,
    Consolidacao,
    ConsolidationWhatsappActivation,
    Igreja,
    LlmCredential,
    NotificationOutbox,
    Pessoa,
    UserRole,
    WhatsappConnection,
    WhatsappReminderPreference,
    WorkQueueItem,
)
from app.db.models import Base
from app.db.tenant_session import mark_tenant_scoped
from app.services import consolidation_whatsapp, notification_outbox, whatsapp_privilege
from tests.conftest_rls import assert_disposable_database


pytestmark = pytest.mark.rls_integration

_DATABASE_ENV = "V3_DELIVERY_DATABASE_URL"
_SCHEMA = "v3_delivery"
_MIGRATION = (
    Path(__file__).parents[1]
    / "migrations"
    / "20260928_080000_whatsapp_consolidation_v3.sql"
)
_TERM = "v3-delivery-synthetic"
_TENANT = uuid.UUID("c3c3c3c3-0000-4000-8000-000000000001")
_OTHER_TENANT = uuid.UUID("c3c3c3c3-0000-4000-8000-000000000002")
_NOW = dt.datetime(2031, 1, 15, 12, 0, tzinfo=dt.UTC)


def _delivery_database_url() -> str:
    url = os.environ.get(_DATABASE_ENV, "").strip()
    if not url:
        pytest.skip(f"{_DATABASE_ENV} não definida")
    assert_disposable_database(url)
    parsed = urlsplit(url)
    database_name = parsed.path.rsplit("/", 1)[-1].lower()
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or database_name != "v3_delivery_test"
    ):
        raise RuntimeError("banco V3 de entrega não está explicitamente identificado")
    return url


@pytest.fixture(scope="session")
def rls_database_url() -> str:
    """Use the dedicated delivery database, never the shared RLS setting."""

    return _delivery_database_url()


def _apply_v3_migration(engine: Engine) -> None:
    sql = _MIGRATION.read_text(encoding="utf-8").replace("public.", f"{_SCHEMA}.")
    raw = engine.raw_connection()
    try:
        raw.autocommit = True
        with raw.cursor() as cursor:
            cursor.execute(sql)
    finally:
        raw.close()


def _create_current_tenant_function(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"create or replace function {_SCHEMA}.current_igreja_id() "
            "returns uuid language sql stable as $$ "
            "select nullif(current_setting('app.tenant_igreja_id', true), '')::uuid "
            "$$"
        )


def _tenant_rls(engine: Engine) -> None:
    tables = (
        "pessoas",
        "app_users",
        "user_roles",
        "consent_records",
        "agent_configs",
        "llm_credentials",
        "whatsapp_connections",
        "conversations",
        "consolidacoes",
        "work_queue_items",
        "whatsapp_reminder_preferences",
        "notification_outbox",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f"alter table {_SCHEMA}.igrejas enable row level security")
        connection.exec_driver_sql(f"alter table {_SCHEMA}.igrejas force row level security")
        connection.exec_driver_sql(
            f"create policy delivery_igrejas_scope on {_SCHEMA}.igrejas for all "
            f"using (id = {_SCHEMA}.current_igreja_id()) "
            f"with check (id = {_SCHEMA}.current_igreja_id())"
        )
        for table in tables:
            connection.exec_driver_sql(f"alter table {_SCHEMA}.{table} enable row level security")
            connection.exec_driver_sql(f"alter table {_SCHEMA}.{table} force row level security")
            connection.exec_driver_sql(
                f"create policy delivery_{table}_scope on {_SCHEMA}.{table} for all "
                f"using (igreja_id = {_SCHEMA}.current_igreja_id()) "
                f"with check (igreja_id = {_SCHEMA}.current_igreja_id())"
            )


@pytest.fixture
def delivery_engine(rls_database_url: str) -> Iterator[Engine]:
    engine = create_engine(
        rls_database_url,
        future=True,
        connect_args={"options": f"-c search_path={_SCHEMA},public"},
    )
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"drop schema if exists {_SCHEMA} cascade; create schema {_SCHEMA};"
            )
            connection.exec_driver_sql("create extension if not exists pgcrypto;")
            connection.exec_driver_sql(
                "do $$ begin "
                "if not exists (select 1 from pg_roles where rolname = 'authenticated') then "
                "create role authenticated nologin noinherit nobypassrls; end if; end $$;"
            )
            connection.exec_driver_sql(f"grant usage on schema {_SCHEMA} to authenticated;")
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"grant select, insert, update, delete on all tables in schema {_SCHEMA} "
                "to authenticated;"
            )
        _create_current_tenant_function(engine)
        _apply_v3_migration(engine)
        _tenant_rls(engine)
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade;")
        engine.dispose()


def _factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def _window_now() -> dt.datetime:
    return _NOW


@dataclass(frozen=True, slots=True)
class _DeliveryTurn:
    engine: Engine
    factory: sessionmaker
    now: dt.datetime
    tenant: uuid.UUID
    responsible_pessoa_id: uuid.UUID
    responsible_user_id: uuid.UUID
    visitor_pessoa_id: uuid.UUID
    clock: list[dt.datetime]


def _synthetic_phone(suffix: str) -> str:
    return "".join(("55", "11", "9", "0000", suffix.zfill(4)[-4:]))


def _seed_tenant(
    session: Session,
    *,
    tenant: uuid.UUID,
    label: str,
    responsible_pessoa_id: uuid.UUID,
    responsible_user_id: uuid.UUID,
) -> None:
    session.add(Igreja(id=tenant, nome=f"Igreja {label}", status="ativa"))
    session.flush()
    session.add(
        Pessoa(
            id=responsible_pessoa_id,
            igreja_id=tenant,
            nome=f"Responsável {label}",
            telefone=_synthetic_phone(label),
        )
    )
    session.flush()
    session.add(
        AppUser(
            id=responsible_user_id,
            igreja_id=tenant,
            pessoa_id=responsible_pessoa_id,
            nome=f"Operador {label}",
            email=f"{label}@example.test",
            clerk_user_id=f"clerk-delivery-{label}",
            status="ativo",
        )
    )
    session.flush()
    session.add(UserRole(igreja_id=tenant, user_id=responsible_user_id, papel="lider_consol"))
    session.add(
        ConsentRecord(
            igreja_id=tenant,
            pessoa_id=responsible_pessoa_id,
            termo_versao=_TERM,
            aceite_em=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1),
        )
    )
    session.add(
        WhatsappReminderPreference(
            igreja_id=tenant,
            pessoa_id=responsible_pessoa_id,
            reminder_kind="consolidation",
            state="active",
            term_version=_TERM,
            accepted_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1),
            changed_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1),
        )
    )
    session.add(AgentConfig(igreja_id=tenant, comportamento="sintético", ativo=True))
    session.add(
        LlmCredential(
            igreja_id=tenant,
            provedor="openai",
            modelo="synthetic",
            api_key_encrypted="synthetic",
            validado=True,
            ativo=True,
        )
    )
    session.add(
        WhatsappConnection(
            igreja_id=tenant,
            instance=f"delivery-{label}",
            status="online",
        )
    )


@pytest.fixture
def delivery_turn(delivery_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[_DeliveryTurn]:
    monkeypatch.setenv("AGENT_TERM_VERSION", _TERM)
    monkeypatch.setenv("ALLOW_REAL_SENDS", "true")
    monkeypatch.setenv("WHATSAPP_PILOTO_IGREJA_IDS", str(_TENANT))
    monkeypatch.setenv("CONSOLIDATION_NOTIFY_ENABLED", "true")
    monkeypatch.setenv("CONSOLIDATION_WHATSAPP_ENABLED_IGREJA_IDS", str(_TENANT))
    monkeypatch.setenv("AGENT_PRIVILEGE_ENABLED_IGREJA_IDS", str(_TENANT))
    monkeypatch.setattr(
        consolidation_whatsapp,
        "CONSOLIDATION_WHATSAPP_APPROVED_RELEASE_ID",
        "delivery-synthetic",
    )
    monkeypatch.setattr(
        whatsapp_privilege,
        "PRIVILEGE_APPROVED_RELEASE_ID",
        "delivery-synthetic",
    )
    get_settings.cache_clear()
    factory = _factory(delivery_engine)
    clock = [_window_now()]
    monkeypatch.setattr(
        notification_outbox,
        "_worker_now",
        lambda value: value if value is not None else clock[0],
    )
    responsible_pessoa_id = uuid.uuid4()
    responsible_user_id = uuid.uuid4()
    visitor_pessoa_id = uuid.uuid4()
    with factory.begin() as session:
        _seed_tenant(
            session,
            tenant=_TENANT,
            label="1",
            responsible_pessoa_id=responsible_pessoa_id,
            responsible_user_id=responsible_user_id,
        )
        _seed_tenant(
            session,
            tenant=_OTHER_TENANT,
            label="2",
            responsible_pessoa_id=uuid.uuid4(),
            responsible_user_id=uuid.uuid4(),
        )
        session.add(
            Pessoa(
                id=visitor_pessoa_id,
                igreja_id=_TENANT,
                nome="Visitante Sintético",
                telefone=_synthetic_phone("99"),
            )
        )
    try:
        yield _DeliveryTurn(
            engine=delivery_engine,
            factory=factory,
            now=clock[0],
            tenant=_TENANT,
            responsible_pessoa_id=responsible_pessoa_id,
            responsible_user_id=responsible_user_id,
            visitor_pessoa_id=visitor_pessoa_id,
            clock=clock,
        )
    finally:
        get_settings.cache_clear()


def _open_fonovisita(
    turn: _DeliveryTurn,
    *,
    created_at: dt.datetime,
    visitor_pessoa_id: uuid.UUID | None = None,
) -> WorkQueueItem:
    visitor = visitor_pessoa_id or turn.visitor_pessoa_id
    with turn.factory.begin() as session:
        track = Consolidacao(
            igreja_id=turn.tenant,
            pessoa_id=visitor,
            tipo="individual",
            responsavel_id=turn.responsible_user_id,
            progresso=0,
            concluida=False,
            prazo_conexao=None,
            created_at=created_at,
        )
        session.add(track)
        session.flush()
        task = session.execute(
            select(WorkQueueItem).where(
                WorkQueueItem.igreja_id == turn.tenant,
                WorkQueueItem.consolidacao_id == track.id,
                WorkQueueItem.tipo == "fonovisita",
            )
        ).scalar_one()
        task.created_at = created_at
        task.status = "aberto"
        task.pessoa_id = visitor
        task.responsavel_id = turn.responsible_user_id
        return task


def _new_visitor(turn: _DeliveryTurn, *, suffix: str) -> uuid.UUID:
    pessoa_id = uuid.uuid4()
    with turn.factory.begin() as session:
        session.add(
            Pessoa(
                id=pessoa_id,
                igreja_id=turn.tenant,
                nome=f"Visitante {suffix}",
                telefone=_synthetic_phone(suffix),
            )
        )
    return pessoa_id


def _alternate_responsible(turn: _DeliveryTurn) -> uuid.UUID:
    pessoa_id = uuid.uuid4()
    user_id = uuid.uuid4()
    accepted_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    with turn.factory.begin() as session:
        session.add(
            Pessoa(
                id=pessoa_id,
                igreja_id=turn.tenant,
                nome="Alterna Sintética",
                telefone=_synthetic_phone("777"),
            )
        )
        session.flush()
        session.add(
            AppUser(
                id=user_id,
                igreja_id=turn.tenant,
                pessoa_id=pessoa_id,
                nome="Alterna Sintética",
                email="alterna@example.test",
                clerk_user_id="clerk-delivery-alt",
                status="ativo",
            )
        )
        session.flush()
        session.add(UserRole(igreja_id=turn.tenant, user_id=user_id, papel="lider_consol"))
        session.add(
            ConsentRecord(
                igreja_id=turn.tenant,
                pessoa_id=pessoa_id,
                termo_versao=_TERM,
                aceite_em=accepted_at,
            )
        )
        session.add(
            WhatsappReminderPreference(
                igreja_id=turn.tenant,
                pessoa_id=pessoa_id,
                reminder_kind="consolidation",
                state="active",
                term_version=_TERM,
                accepted_at=accepted_at,
                changed_at=accepted_at,
            )
        )
    return user_id


def _open_connection_track(
    turn: _DeliveryTurn,
    *,
    created_at: dt.datetime,
    deadline: dt.datetime,
) -> WorkQueueItem:
    with turn.factory.begin() as session:
        track = Consolidacao(
            igreja_id=turn.tenant,
            pessoa_id=turn.visitor_pessoa_id,
            tipo="individual",
            responsavel_id=turn.responsible_user_id,
            progresso=0,
            concluida=False,
            prazo_conexao=deadline,
            created_at=created_at,
        )
        session.add(track)
        session.flush()
        fono = session.execute(
            select(WorkQueueItem).where(
                WorkQueueItem.igreja_id == turn.tenant,
                WorkQueueItem.consolidacao_id == track.id,
                WorkQueueItem.tipo == "fonovisita",
            )
        ).scalar_one()
        fono.status = "resolvido"
        task = WorkQueueItem(
            igreja_id=turn.tenant,
            consolidacao_id=track.id,
            tipo="conectar_celula",
            titulo="Conectar",
            pessoa_id=turn.visitor_pessoa_id,
            responsavel_id=turn.responsible_user_id,
            status="aberto",
            prazo=created_at + dt.timedelta(hours=24),
            prioridade=1,
            created_at=created_at,
        )
        session.add(task)
        session.flush()
        return task


class _Provider:
    def __init__(self, turn: _DeliveryTurn, *, results: tuple[object, ...] = ()) -> None:
        self.turn = turn
        self.calls: list[tuple[str, str, str]] = []
        self._results = list(results)

    def send_text_classificado(self, instance: str, phone: str, message: str):
        assert self.turn.engine.pool.checkedout() == 0
        with self.turn.factory() as session:
            row = session.execute(
                select(NotificationOutbox).where(
                    NotificationOutbox.igreja_id == self.turn.tenant,
                    NotificationOutbox.state == "em_envio",
                )
            ).scalar_one()
            assert row.state == "em_envio" and row.transport_started_at is not None
        self.calls.append((instance, phone, message))
        return self._results.pop(0) if self._results else SimpleNamespace(status="aceito")


class _ConcurrentProvider:
    """Thread-safe provider fake used only to exercise the shared claim path."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def send_text_classificado(self, instance: str, phone: str, message: str):
        self.calls.append((instance, phone, message))
        return SimpleNamespace(status="aceito")


def test_fonovisita_created_after_activation_reaches_common_dispatcher(delivery_turn):
    turn = delivery_turn
    # First open observation establishes the durable prospective epoch before
    # this track exists, so the test cannot accidentally schedule old work.
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    with turn.factory() as session:
        marker = session.get(ConsolidationWhatsappActivation, turn.tenant)
        assert marker is not None and marker.gate_open and marker.activated_at == turn.now

    task = _open_fonovisita(turn, created_at=turn.now + dt.timedelta(seconds=1))
    scheduled_at = turn.now + dt.timedelta(seconds=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=scheduled_at
    ) == 1

    with turn.factory() as session:
        scoped = turn.factory()
        try:
            mark_tenant_scoped(scoped, turn.tenant, source="v3_delivery_test_rls")
            assert scoped.execute(text("select current_user")).scalar_one() == "authenticated"
            rows = scoped.execute(select(NotificationOutbox)).scalars().all()
            assert len(rows) == 1 and rows[0].igreja_id == turn.tenant
        finally:
            scoped.rollback()
            scoped.close()
        row = session.execute(select(NotificationOutbox)).scalar_one()
        assert row.purpose == "consolidation_fonovisita"
        assert row.origin_kind == "work_queue" and row.origin_id == task.id
        assert row.work_queue_item_id == task.id and row.consolidacao_id is None
        assert row.pessoa_id == turn.responsible_pessoa_id
        assert row.state == "pendente"

    provider = _Provider(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory, provider, worker_id="v3-delivery-fono", now=scheduled_at
    ) == 1
    assert len(provider.calls) == 1
    message = provider.calls[0][2]
    assert "Prazo não definido." in message
    assert f"P-{task.id.hex[:10].upper()}" in message
    assert "Visitante Sintético" not in message
    with turn.factory() as session:
        row = session.execute(select(NotificationOutbox)).scalar_one()
        assert row.state == "enviado" and row.sent_at == scheduled_at


@pytest.mark.parametrize("responsible_role", ("lider_consol", "lider_g12"))
def test_connection_open_and_deadline_use_consolidacao_anchor_and_canonical_task(
    delivery_turn, responsible_role: str
):
    turn = delivery_turn
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    with turn.factory.begin() as session:
        role = session.execute(
            select(UserRole).where(
                UserRole.igreja_id == turn.tenant,
                UserRole.user_id == turn.responsible_user_id,
            )
        ).scalar_one()
        role.papel = responsible_role
    created_at = turn.now + dt.timedelta(seconds=1)
    deadline = turn.now + dt.timedelta(seconds=5)
    task = _open_connection_track(turn, created_at=created_at, deadline=deadline)
    scheduled_at = turn.now + dt.timedelta(seconds=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=scheduled_at
    ) == 2

    with turn.factory() as session:
        rows = session.execute(
            select(NotificationOutbox).order_by(NotificationOutbox.purpose.asc())
        ).scalars().all()
        assert [row.purpose for row in rows] == [
            "consolidation_connection_deadline",
            "consolidation_connection_open",
        ]
        assert all(row.consolidacao_id is not None for row in rows)
        assert all(row.work_queue_item_id is None for row in rows)
        assert all(row.origin_kind == "consolidacao" for row in rows)
        assert {row.occurrence_at for row in rows} == {created_at, deadline}

    provider = _Provider(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory, provider, worker_id="v3-delivery-connection", now=scheduled_at
    ) == 1
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory, provider, worker_id="v3-delivery-deadline", now=deadline
    ) == 1
    assert len(provider.calls) == 2
    for _instance, _phone, message in provider.calls:
        assert f"P-{task.id.hex[:10].upper()}" in message
        assert "Prazo:" in message
        assert "Visitante Sintético" not in message
    with turn.factory() as session:
        rows = session.execute(select(NotificationOutbox)).scalars().all()
        assert all(row.state == "enviado" for row in rows)


def test_v3_lider_celula_receives_own_fonovisita_but_not_connection(delivery_turn):
    turn = delivery_turn
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    with turn.factory.begin() as session:
        role = session.execute(
            select(UserRole).where(
                UserRole.igreja_id == turn.tenant,
                UserRole.user_id == turn.responsible_user_id,
            )
        ).scalar_one()
        role.papel = "lider_celula"
    fono = _open_fonovisita(turn, created_at=turn.now + dt.timedelta(seconds=1))
    scheduled_at = turn.now + dt.timedelta(seconds=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=scheduled_at
    ) == 1
    provider = _Provider(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory, provider, worker_id="v3-delivery-lider-celula-fono", now=scheduled_at
    ) == 1
    assert len(provider.calls) == 1
    assert f"P-{fono.id.hex[:10].upper()}" in provider.calls[0][2]

    with turn.factory.begin() as session:
        prior = session.get(Consolidacao, fono.consolidacao_id)
        assert prior is not None
        prior.concluida = True

    _open_connection_track(
        turn,
        created_at=scheduled_at + dt.timedelta(seconds=1),
        deadline=scheduled_at + dt.timedelta(hours=1),
    )
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=scheduled_at + dt.timedelta(seconds=2)
    ) == 0
    with turn.factory() as session:
        rows = session.execute(select(NotificationOutbox)).scalars().all()
        assert len(rows) == 1 and rows[0].purpose == "consolidation_fonovisita"


@pytest.mark.parametrize("closed_by", ("allowlist", "agent_config"))
def test_gate_close_cancels_pending_and_reopen_never_replays_pre_epoch_source(
    delivery_turn, monkeypatch: pytest.MonkeyPatch, closed_by: str
):
    turn = delivery_turn
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    old_task = _open_fonovisita(turn, created_at=turn.now + dt.timedelta(seconds=1))
    pending_at = turn.now + dt.timedelta(seconds=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=pending_at
    ) == 1

    if closed_by == "allowlist":
        monkeypatch.setenv("CONSOLIDATION_WHATSAPP_ENABLED_IGREJA_IDS", str(_OTHER_TENANT))
    else:
        with turn.factory.begin() as session:
            config = session.execute(
                select(AgentConfig).where(AgentConfig.igreja_id == turn.tenant)
            ).scalar_one()
            config.ativo = False
    get_settings.cache_clear()
    closed_at = turn.now + dt.timedelta(seconds=3)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=closed_at
    ) == 0
    with turn.factory() as session:
        marker = session.get(ConsolidationWhatsappActivation, turn.tenant)
        row = session.execute(select(NotificationOutbox)).scalar_one()
        assert marker is not None and marker.gate_open is False
        assert row.state == "cancelado" and row.terminal_reason == "gate_fechado"

    if closed_by == "allowlist":
        monkeypatch.setenv("CONSOLIDATION_WHATSAPP_ENABLED_IGREJA_IDS", str(_TENANT))
    else:
        with turn.factory.begin() as session:
            config = session.execute(
                select(AgentConfig).where(AgentConfig.igreja_id == turn.tenant)
            ).scalar_one()
            config.ativo = True
    get_settings.cache_clear()
    reopened_at = turn.now + dt.timedelta(seconds=4)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=reopened_at
    ) == 0
    with turn.factory() as session:
        marker = session.get(ConsolidationWhatsappActivation, turn.tenant)
        rows = session.execute(select(NotificationOutbox)).scalars().all()
        assert marker is not None and marker.gate_open and marker.activated_at == reopened_at
        assert len(rows) == 1 and rows[0].work_queue_item_id == old_task.id

    new_visitor = _new_visitor(turn, suffix="501")
    new_task = _open_fonovisita(
        turn,
        created_at=reopened_at + dt.timedelta(seconds=1),
        visitor_pessoa_id=new_visitor,
    )
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=reopened_at + dt.timedelta(seconds=2)
    ) == 1
    with turn.factory() as session:
        rows = session.execute(
            select(NotificationOutbox).order_by(NotificationOutbox.created_at.asc())
        ).scalars().all()
        assert len(rows) == 2
        assert rows[0].state == "cancelado" and rows[0].work_queue_item_id == old_task.id
        assert rows[1].state == "pendente" and rows[1].work_queue_item_id == new_task.id


def test_stop_command_service_cancels_pending_consolidation_before_provider(delivery_turn):
    turn = delivery_turn
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    _open_fonovisita(turn, created_at=turn.now + dt.timedelta(seconds=1))
    scheduled_at = turn.now + dt.timedelta(seconds=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=scheduled_at
    ) == 1
    with turn.factory.begin() as session:
        assert notification_outbox.disable_whatsapp_reminders(
            session,
            igreja_id=turn.tenant,
            pessoa_id=turn.responsible_pessoa_id,
            now=scheduled_at,
        )
    provider = _Provider(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory, provider, worker_id="v3-delivery-stop", now=scheduled_at
    ) == 0
    assert provider.calls == []
    with turn.factory() as session:
        preference = session.execute(
            select(WhatsappReminderPreference).where(
                WhatsappReminderPreference.igreja_id == turn.tenant,
                WhatsappReminderPreference.pessoa_id == turn.responsible_pessoa_id,
                WhatsappReminderPreference.reminder_kind == "consolidation",
            )
        ).scalar_one()
        row = session.execute(select(NotificationOutbox)).scalar_one()
        assert preference.state == "disabled"
        assert row.state == "cancelado" and row.terminal_reason == "lembretes_recusados"


def test_expired_post_activation_source_never_materializes_a_historical_burst(delivery_turn):
    turn = delivery_turn
    activated_at = turn.now - dt.timedelta(hours=26)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=activated_at
    ) == 0
    _open_fonovisita(turn, created_at=activated_at + dt.timedelta(seconds=1))
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    with turn.factory() as session:
        marker = session.get(ConsolidationWhatsappActivation, turn.tenant)
        assert marker is not None and marker.activated_at == activated_at and marker.gate_open
        assert session.execute(select(NotificationOutbox)).scalars().all() == []


def test_assignment_aba_before_fence_suppresses_old_intent_without_reroute(delivery_turn):
    turn = delivery_turn
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    task = _open_fonovisita(turn, created_at=turn.now + dt.timedelta(seconds=1))
    scheduled_at = turn.now + dt.timedelta(seconds=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=scheduled_at
    ) == 1
    alternate_user_id = _alternate_responsible(turn)
    with turn.factory.begin() as session:
        track = session.execute(
            select(Consolidacao).where(
                Consolidacao.igreja_id == turn.tenant,
                Consolidacao.pessoa_id == turn.visitor_pessoa_id,
            )
        ).scalar_one()
        task_row = session.get(WorkQueueItem, task.id)
        assert task_row is not None
        track.responsavel_id = alternate_user_id
        task_row.responsavel_id = alternate_user_id
    with turn.factory.begin() as session:
        track = session.execute(
            select(Consolidacao).where(
                Consolidacao.igreja_id == turn.tenant,
                Consolidacao.pessoa_id == turn.visitor_pessoa_id,
            )
        ).scalar_one()
        task_row = session.get(WorkQueueItem, task.id)
        assert task_row is not None
        track.responsavel_id = turn.responsible_user_id
        task_row.responsavel_id = turn.responsible_user_id
    provider = _Provider(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory, provider, worker_id="v3-delivery-aba", now=scheduled_at
    ) == 0
    assert provider.calls == []
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=scheduled_at + dt.timedelta(seconds=1)
    ) == 0
    with turn.factory() as session:
        track = session.execute(select(Consolidacao)).scalar_one()
        row = session.execute(select(NotificationOutbox)).scalar_one()
        assert track.assignment_revision == 2
        assert row.state == "obsoleto" and row.terminal_reason == "origem_alterada"


def test_v3_quota_defers_third_pending_to_next_window_without_using_agenda_slots(delivery_turn):
    turn = delivery_turn
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    source_at = turn.now + dt.timedelta(seconds=1)
    for suffix in ("601", "602", "603"):
        _open_fonovisita(
            turn,
            created_at=source_at,
            visitor_pessoa_id=_new_visitor(turn, suffix=suffix),
        )
    scheduled_at = turn.now + dt.timedelta(seconds=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=scheduled_at
    ) == 3
    provider = _Provider(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory, provider, worker_id="v3-delivery-quota", now=scheduled_at, limit=10
    ) == 2
    next_window = notification_outbox._next_consolidation_quota_window(scheduled_at)
    assert next_window is not None
    with turn.factory() as session:
        rows = session.execute(
            select(NotificationOutbox).order_by(NotificationOutbox.id.asc())
        ).scalars().all()
        assert len(rows) == 3
        assert sum(row.state == "enviado" for row in rows) == 2
        pending = [row for row in rows if row.state == "pendente"]
        assert len(pending) == 1 and pending[0].due_at == next_window
        assert pending[0].delivery_reservation_day is None
        sent = [row for row in rows if row.state == "enviado"]
        assert all(
            row.delivery_reservation_day == scheduled_at.astimezone(notification_outbox.SAO_PAULO_TZ).date()
            for row in sent
        )
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory, provider, worker_id="v3-delivery-quota-next", now=next_window, limit=10
    ) == 1
    assert len(provider.calls) == 3


def test_v3_pre_send_retry_cannot_extend_the_fixed_24_hour_expiry(delivery_turn):
    turn = delivery_turn
    activation_at = turn.now - dt.timedelta(hours=23, minutes=59, seconds=30)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=activation_at
    ) == 0
    _open_fonovisita(turn, created_at=activation_at + dt.timedelta(seconds=1))
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 1

    provider = _Provider(
        turn,
        results=(
            SimpleNamespace(
                status="falhou_retentavel",
                error_class="connect_error",
                consume_retry_budget=False,
            ),
        ),
    )
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory, provider, worker_id="v3-delivery-expiry", now=turn.now
    ) == 1
    assert len(provider.calls) == 1
    with turn.factory() as session:
        row = session.execute(select(NotificationOutbox)).scalar_one()
        assert row.state == "cancelado" and row.terminal_reason == "expirado"
        assert row.attempts == 1
        assert row.due_at == turn.now


def test_v3_outside_transport_window_releases_without_provider_and_keeps_expiry(delivery_turn):
    turn = delivery_turn
    closed_at = turn.now.astimezone(notification_outbox.SAO_PAULO_TZ).replace(
        hour=21, minute=0, second=0, microsecond=0
    ).astimezone(dt.UTC)
    activation_at = closed_at - dt.timedelta(hours=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=activation_at
    ) == 0
    _open_fonovisita(turn, created_at=activation_at + dt.timedelta(seconds=1))
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=closed_at
    ) == 1

    provider = _Provider(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory, provider, worker_id="v3-delivery-window", now=closed_at
    ) == 0
    assert provider.calls == []
    with turn.factory() as session:
        row = session.execute(select(NotificationOutbox)).scalar_one()
        assert row.state == "pendente"
        assert row.due_at == notification_outbox.next_transport_window(closed_at)
        assert row.delivery_reservation_day is None


@pytest.mark.parametrize("initial_role", ("lider_consol", "lider_celula", "lider_g12"))
def test_v3_role_revocation_between_schedule_and_fence_suppresses_transport(
    delivery_turn, initial_role: str
):
    turn = delivery_turn
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    with turn.factory.begin() as session:
        role = session.execute(
            select(UserRole).where(
                UserRole.igreja_id == turn.tenant,
                UserRole.user_id == turn.responsible_user_id,
            )
        ).scalar_one()
        role.papel = initial_role
    _open_fonovisita(turn, created_at=turn.now + dt.timedelta(seconds=1))
    scheduled_at = turn.now + dt.timedelta(seconds=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=scheduled_at
    ) == 1
    with turn.factory.begin() as session:
        role = session.execute(
            select(UserRole).where(
                UserRole.igreja_id == turn.tenant,
                UserRole.user_id == turn.responsible_user_id,
            )
        ).scalar_one()
        role.papel = "membro"

    provider = _Provider(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory, provider, worker_id="v3-delivery-revoked", now=scheduled_at
    ) == 0
    assert provider.calls == []
    with turn.factory() as session:
        row = session.execute(select(NotificationOutbox)).scalar_one()
        assert row.state == "obsoleto" and row.terminal_reason == "destinatario_revogado"


def test_v3_scheduler_materializes_cross_tenant_but_authenticated_rls_hides_it(
    delivery_turn, monkeypatch: pytest.MonkeyPatch
):
    turn = delivery_turn
    tenant_list = f"{_TENANT},{_OTHER_TENANT}"
    monkeypatch.setenv("WHATSAPP_PILOTO_IGREJA_IDS", tenant_list)
    monkeypatch.setenv("CONSOLIDATION_WHATSAPP_ENABLED_IGREJA_IDS", tenant_list)
    monkeypatch.setenv("AGENT_PRIVILEGE_ENABLED_IGREJA_IDS", tenant_list)
    get_settings.cache_clear()
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    other_visitor_id = uuid.uuid4()
    created_at = turn.now + dt.timedelta(seconds=1)
    with turn.factory.begin() as session:
        other_user = session.execute(
            select(AppUser).where(AppUser.igreja_id == _OTHER_TENANT)
        ).scalar_one()
        session.add(
            Pessoa(
                id=other_visitor_id,
                igreja_id=_OTHER_TENANT,
                nome="Visitante Outro",
                telefone=_synthetic_phone("888"),
            )
        )
        session.flush()
        track = Consolidacao(
            igreja_id=_OTHER_TENANT,
            pessoa_id=other_visitor_id,
            tipo="individual",
            responsavel_id=other_user.id,
            progresso=0,
            concluida=False,
            prazo_conexao=None,
            created_at=created_at,
        )
        session.add(track)
        session.flush()
        fono = session.execute(
            select(WorkQueueItem).where(
                WorkQueueItem.igreja_id == _OTHER_TENANT,
                WorkQueueItem.consolidacao_id == track.id,
                WorkQueueItem.tipo == "fonovisita",
            )
        ).scalar_one()
        fono.created_at = created_at
        fono.status = "aberto"
        fono.pessoa_id = other_visitor_id
        fono.responsavel_id = other_user.id

    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now + dt.timedelta(seconds=2)
    ) == 1
    with turn.factory() as session:
        assert session.execute(
            select(NotificationOutbox.id).where(
                NotificationOutbox.igreja_id == _OTHER_TENANT,
                NotificationOutbox.purpose == "consolidation_fonovisita",
            )
        ).scalar_one_or_none() is not None
    scoped = turn.factory()
    try:
        mark_tenant_scoped(scoped, turn.tenant, source="v3_delivery_cross_tenant")
        assert scoped.execute(text("select current_user")).scalar_one() == "authenticated"
        assert scoped.execute(
            select(NotificationOutbox.id).where(
                NotificationOutbox.igreja_id == _OTHER_TENANT
            )
        ).scalar_one_or_none() is None
    finally:
        scoped.rollback()
        scoped.close()


def test_v3_ambiguous_removed_source_keeps_daily_quota_reservation(delivery_turn):
    turn = delivery_turn
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    source_at = turn.now + dt.timedelta(seconds=1)
    for suffix in ("701", "702", "703"):
        _open_fonovisita(
            turn,
            created_at=source_at,
            visitor_pessoa_id=_new_visitor(turn, suffix=suffix),
        )
    scheduled_at = turn.now + dt.timedelta(seconds=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=scheduled_at
    ) == 3

    unknown = _Provider(
        turn,
        results=(
            SimpleNamespace(
                status="falhou_retentavel",
                error_class="unknown_retry_class",
            ),
        ),
    )
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory, unknown, worker_id="v3-delivery-ambiguous", now=scheduled_at, limit=1
    ) == 1
    with turn.factory.begin() as session:
        ambiguous = session.execute(
            select(NotificationOutbox).where(NotificationOutbox.state == "ambiguo")
        ).scalar_one()
        removed_task_id = ambiguous.work_queue_item_id
        assert removed_task_id is not None
        task = session.get(WorkQueueItem, removed_task_id)
        assert task is not None
        session.delete(task)

    accepted = _Provider(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory,
        accepted,
        worker_id="v3-delivery-remaining-quota",
        now=scheduled_at + dt.timedelta(seconds=1),
        limit=10,
    ) == 1
    assert len(accepted.calls) == 1
    with turn.factory() as session:
        rows = session.execute(select(NotificationOutbox)).scalars().all()
        ambiguous = next(row for row in rows if row.state == "ambiguo")
        pending = next(row for row in rows if row.state == "pendente")
        reservation_day = scheduled_at.astimezone(notification_outbox.SAO_PAULO_TZ).date()
        assert ambiguous.work_queue_item_id is None
        assert ambiguous.origin_id == removed_task_id
        assert ambiguous.delivery_reservation_day == reservation_day
        assert pending.due_at == notification_outbox._next_consolidation_quota_window(
            scheduled_at + dt.timedelta(seconds=1)
        )


def test_v3_pre_send_retry_from_yesterday_competes_for_today_quota(
    delivery_turn, monkeypatch: pytest.MonkeyPatch
):
    turn = delivery_turn
    previous_evening = (
        turn.now.astimezone(notification_outbox.SAO_PAULO_TZ)
        - dt.timedelta(days=1)
    ).replace(hour=20, minute=0, second=0, microsecond=0).astimezone(dt.UTC)
    with turn.factory.begin() as session:
        accepted_at = previous_evening - dt.timedelta(seconds=1)
        consent = session.execute(
            select(ConsentRecord).where(
                ConsentRecord.igreja_id == turn.tenant,
                ConsentRecord.pessoa_id == turn.responsible_pessoa_id,
            )
        ).scalar_one()
        preference = session.execute(
            select(WhatsappReminderPreference).where(
                WhatsappReminderPreference.igreja_id == turn.tenant,
                WhatsappReminderPreference.pessoa_id == turn.responsible_pessoa_id,
                WhatsappReminderPreference.reminder_kind == "consolidation",
            )
        ).scalar_one()
        consent.aceite_em = accepted_at
        preference.accepted_at = accepted_at
        preference.changed_at = accepted_at
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=previous_evening
    ) == 0
    old_task = _open_fonovisita(
        turn, created_at=previous_evening + dt.timedelta(seconds=1)
    )
    failure_at = previous_evening + dt.timedelta(seconds=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=failure_at
    ) == 1
    retry_provider = _Provider(
        turn,
        results=(
            SimpleNamespace(
                status="falhou_retentavel",
                error_class="connect_error",
                consume_retry_budget=False,
            ),
        ),
    )
    original_worker_now = notification_outbox._worker_now
    monkeypatch.setattr(
        notification_outbox,
        "_worker_now",
        lambda value: value if value is not None else failure_at,
    )
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory,
        retry_provider,
        worker_id="v3-delivery-yesterday-retry",
        now=failure_at,
        limit=1,
    ) == 1
    monkeypatch.setattr(notification_outbox, "_worker_now", original_worker_now)
    with turn.factory.begin() as session:
        retry_row = session.execute(
            select(NotificationOutbox).where(NotificationOutbox.work_queue_item_id == old_task.id)
        ).scalar_one()
        yesterday = failure_at.astimezone(notification_outbox.SAO_PAULO_TZ).date()
        assert retry_row.state == "retry"
        assert retry_row.delivery_reservation_day == yesterday
        # A later retry due-time models the normal pre-send deferral that
        # crosses midnight. Its immutable occurrence and prior reservation
        # remain intact.
        retry_row.due_at = turn.now + dt.timedelta(minutes=1)

    for suffix in ("711", "712"):
        _open_fonovisita(
            turn,
            created_at=turn.now,
            visitor_pessoa_id=_new_visitor(turn, suffix=suffix),
        )
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 2
    accepted = _Provider(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory,
        accepted,
        worker_id="v3-delivery-today-first-two",
        now=turn.now,
        limit=10,
    ) == 2
    retry_due = turn.now + dt.timedelta(minutes=1)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory,
        accepted,
        worker_id="v3-delivery-today-retry",
        now=retry_due,
        limit=10,
    ) == 0
    with turn.factory() as session:
        retry_row = session.execute(
            select(NotificationOutbox).where(NotificationOutbox.origin_id == old_task.id)
        ).scalar_one()
        assert retry_row.state == "cancelado"
        assert retry_row.terminal_reason == "expirado"
        assert retry_row.delivery_reservation_day == yesterday
    assert len(accepted.calls) == 2


def test_v3_concurrent_dispatchers_never_make_more_than_two_provider_calls(delivery_turn):
    turn = delivery_turn
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    source_at = turn.now + dt.timedelta(seconds=1)
    for suffix in ("721", "722", "723", "724"):
        _open_fonovisita(
            turn,
            created_at=source_at,
            visitor_pessoa_id=_new_visitor(turn, suffix=suffix),
        )
    scheduled_at = turn.now + dt.timedelta(seconds=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=scheduled_at
    ) == 4
    provider = _ConcurrentProvider()

    def dispatch(worker_number: int) -> int:
        return notification_outbox.dispatch_notification_outbox(
            turn.factory,
            provider,
            worker_id=f"v3-delivery-concurrent-{worker_number}",
            now=scheduled_at,
            limit=10,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = tuple(executor.map(dispatch, range(4)))
    assert sum(results) == 2
    assert len(provider.calls) == 2
    with turn.factory() as session:
        rows = session.execute(select(NotificationOutbox)).scalars().all()
        assert sum(row.state == "enviado" for row in rows) == 2
        assert sum(row.state == "pendente" for row in rows) == 2


def test_v3_expired_lease_becomes_ambiguous_without_a_second_transport(delivery_turn):
    turn = delivery_turn
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    _open_fonovisita(turn, created_at=turn.now + dt.timedelta(seconds=1))
    scheduled_at = turn.now + dt.timedelta(seconds=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=scheduled_at
    ) == 1
    with turn.factory.begin() as session:
        row = session.execute(select(NotificationOutbox)).scalar_one()
        row.state = "em_envio"
        row.claim_token = uuid.uuid4()
        row.claimed_until = scheduled_at - dt.timedelta(seconds=1)
        row.claimed_by = "interrompido"
        row.transport_started_at = scheduled_at - dt.timedelta(seconds=31)
        row.delivery_reservation_day = scheduled_at.astimezone(
            notification_outbox.SAO_PAULO_TZ
        ).date()
    provider = _Provider(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory, provider, worker_id="v3-delivery-lease", now=scheduled_at
    ) == 0
    assert provider.calls == []
    with turn.factory() as session:
        row = session.execute(select(NotificationOutbox)).scalar_one()
        assert row.state == "ambiguo" and row.terminal_reason == "lease_expirada"
        assert row.delivery_reservation_day == scheduled_at.astimezone(
            notification_outbox.SAO_PAULO_TZ
        ).date()


def test_v3_config_before_activation_race_finishes_without_deadlock_or_ambiguity(
    delivery_turn, monkeypatch: pytest.MonkeyPatch
):
    """Fence waits on Config before it can lock the activation marker.

    This uses two real PostgreSQL sessions. The old Activation -> Config fence
    order would make the first session time out while holding Config and
    waiting for Activation. The corrected fence reaches context first, so it
    waits for Config without taking Activation; the first session can commit
    both locks and the fence finishes without a provider call or ambiguity.
    """

    turn = delivery_turn
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    _open_fonovisita(turn, created_at=turn.now + dt.timedelta(seconds=1))
    scheduled_at = turn.now + dt.timedelta(seconds=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=scheduled_at
    ) == 1
    claim = notification_outbox._claim_next_notification(
        turn.factory,
        igreja_id=turn.tenant,
        now=scheduled_at,
        lease_seconds=30,
        worker_id="v3-delivery-lock-race",
    )
    assert claim is not None

    context_entered = threading.Event()
    outcome: dict[str, object] = {}
    original_context = notification_outbox._recipient_transport_context

    def observed_context(*args, **kwargs):
        context_entered.set()
        return original_context(*args, **kwargs)

    monkeypatch.setattr(notification_outbox, "_recipient_transport_context", observed_context)

    def renew() -> None:
        try:
            outcome["transport"] = notification_outbox._renew_notification_transport_fence(
                turn.factory,
                claim,
                now=scheduled_at,
                lease_seconds=30,
            )
        except BaseException as error:  # captured for the assertion below
            outcome["error"] = error

    config_session = turn.factory()
    notification_outbox._scoped(
        config_session, turn.tenant, "v3_delivery_lock_order_config"
    )
    config_session.execute(text("set local lock_timeout = '250ms'"))
    config_session.execute(
        select(AgentConfig)
        .where(AgentConfig.igreja_id == turn.tenant)
        .with_for_update()
    ).scalar_one()
    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    assert context_entered.wait(timeout=5)
    try:
        activation = config_session.execute(
            select(ConsolidationWhatsappActivation)
            .where(ConsolidationWhatsappActivation.igreja_id == turn.tenant)
            .with_for_update()
        ).scalar_one()
        assert activation.gate_open is True
        config_session.commit()
    finally:
        config_session.close()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert "error" not in outcome
    assert outcome.get("transport") is not None
    assert notification_outbox._record_notification_result(
        turn.factory,
        claim,
        result=SimpleNamespace(status="aceito"),
        now=scheduled_at,
    )
    with turn.factory() as session:
        row = session.execute(select(NotificationOutbox)).scalar_one()
        assert row.state == "enviado"


@pytest.mark.parametrize(
    ("boundary", "expected_state", "expected_reason"),
    (
        ("window", "retry", None),
        ("expiry", "cancelado", "expirado"),
    ),
)
def test_v3_fence_rechecks_fresh_time_after_a_real_config_lock(
    delivery_turn,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    expected_state: str,
    expected_reason: str | None,
):
    """A blocked final fence cannot transport after its original clock expires."""

    turn = delivery_turn
    if boundary == "window":
        stale_now = turn.now.astimezone(notification_outbox.SAO_PAULO_TZ).replace(
            hour=20, minute=59, second=59, microsecond=0
        ).astimezone(dt.UTC)
        source_at = stale_now - dt.timedelta(seconds=1)
        activated_at = source_at - dt.timedelta(seconds=1)
        fresh_now = stale_now + dt.timedelta(seconds=1)
    else:
        activated_at = turn.now
        source_at = activated_at + dt.timedelta(seconds=1)
        stale_now = source_at + dt.timedelta(hours=24) - dt.timedelta(seconds=1)
        fresh_now = source_at + dt.timedelta(hours=24)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=activated_at
    ) == 0
    _open_fonovisita(turn, created_at=source_at)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=stale_now
    ) == 1
    claim = notification_outbox._claim_next_notification(
        turn.factory,
        igreja_id=turn.tenant,
        now=stale_now,
        lease_seconds=30,
        worker_id=f"v3-delivery-fresh-{boundary}",
    )
    assert claim is not None

    context_entered = threading.Event()
    outcome: dict[str, object] = {}
    original_context = notification_outbox._recipient_transport_context
    original_worker_now = notification_outbox._worker_now
    clock = [stale_now]

    def controlled_worker_now(value: dt.datetime | None) -> dt.datetime:
        return value if value is not None else clock[0]

    def observed_context(*args, **kwargs):
        context_entered.set()
        return original_context(*args, **kwargs)

    monkeypatch.setattr(notification_outbox, "_worker_now", controlled_worker_now)
    monkeypatch.setattr(notification_outbox, "_recipient_transport_context", observed_context)

    def renew() -> None:
        try:
            outcome["transport"] = notification_outbox._renew_notification_transport_fence(
                turn.factory,
                claim,
                now=stale_now,
                lease_seconds=30,
            )
        except BaseException as error:  # captured for the assertion below
            outcome["error"] = error

    config_session = turn.factory()
    notification_outbox._scoped(
        config_session, turn.tenant, f"v3_delivery_fresh_{boundary}"
    )
    config_session.execute(
        select(AgentConfig)
        .where(AgentConfig.igreja_id == turn.tenant)
        .with_for_update()
    ).scalar_one()
    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    assert context_entered.wait(timeout=5)
    clock[0] = fresh_now
    config_session.commit()
    config_session.close()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert "error" not in outcome
    assert outcome.get("transport") is None
    with turn.factory() as session:
        row = session.execute(select(NotificationOutbox)).scalar_one()
        assert row.state == expected_state and row.terminal_reason == expected_reason
        assert row.transport_started_at is None
        if boundary == "window":
            assert row.due_at == notification_outbox.next_transport_window(fresh_now)
    monkeypatch.setattr(notification_outbox, "_worker_now", original_worker_now)


def test_v3_unassigned_consolidation_alerts_current_coordinator_with_code_only(delivery_turn):
    turn = delivery_turn
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    created_at = turn.now + dt.timedelta(seconds=1)
    with turn.factory.begin() as session:
        track = Consolidacao(
            igreja_id=turn.tenant,
            pessoa_id=turn.visitor_pessoa_id,
            tipo="individual",
            responsavel_id=None,
            progresso=0,
            concluida=False,
            prazo_conexao=None,
            created_at=created_at,
        )
        session.add(track)
        session.flush()
        fono = session.execute(
            select(WorkQueueItem).where(
                WorkQueueItem.igreja_id == turn.tenant,
                WorkQueueItem.consolidacao_id == track.id,
                WorkQueueItem.tipo == "fonovisita",
            )
        ).scalar_one()
        fono.created_at = created_at
        fono.status = "aberto"
        fono.pessoa_id = turn.visitor_pessoa_id
        fono.responsavel_id = None
        task_id = fono.id
    scheduled_at = turn.now + dt.timedelta(seconds=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=scheduled_at
    ) == 1
    provider = _Provider(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory, provider, worker_id="v3-delivery-coordinator", now=scheduled_at
    ) == 1
    assert len(provider.calls) == 1
    message = provider.calls[0][2]
    assert f"P-{task_id.hex[:10].upper()}" in message
    assert "Responsável" not in message
    assert "Visitante" not in message
    assert "Prazo:" not in message
    assert "Há 1 pendência de consolidação" in message


def test_v3_pending_source_without_an_eligible_destination_stays_unqueued(delivery_turn):
    turn = delivery_turn
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=turn.now
    ) == 0
    with turn.factory.begin() as session:
        operator = session.get(AppUser, turn.responsible_user_id)
        assert operator is not None
        operator.status = "inativo"
    task = _open_fonovisita(turn, created_at=turn.now + dt.timedelta(seconds=1))
    scheduled_at = turn.now + dt.timedelta(seconds=2)
    assert notification_outbox.schedule_due_consolidation_notification_outbox(
        turn.factory, now=scheduled_at
    ) == 0
    provider = _Provider(turn)
    assert notification_outbox.dispatch_notification_outbox(
        turn.factory, provider, worker_id="v3-delivery-no-target", now=scheduled_at
    ) == 0
    assert provider.calls == []
    with turn.factory() as session:
        assert session.execute(select(NotificationOutbox)).scalars().all() == []
        source = session.get(WorkQueueItem, task.id)
        assert source is not None and source.status == "aberto"
