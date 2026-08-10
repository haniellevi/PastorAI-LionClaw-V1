"""Corridas reais entre billing e cortesia em PostgreSQL descartável."""

from __future__ import annotations

import pathlib
import threading
import time
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import (
    Base,
    BillingPlanChangeOperation,
    BillingSubscriptionOperation,
    Igreja,
    Pessoa,
    Plano,
    Subscription,
)
from app.routers.subscription import AsaasWebhookEvent, asaas_webhook
from app.services.billing import (
    PlanChangeConflict,
    assigned_complimentary_plan,
    ensure_plan_change_operation,
    find_blocking_plan_change_for_plan,
    find_blocking_subscription_creation,
    lock_igreja_for_billing,
    lock_plan_rows_for_billing,
)
from tests.conftest_rls import rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration

_SCHEMA = "billing_complimentary_race"
_IGREJA = uuid.UUID("31000000-0000-0000-0000-000000000001")
_SUB = uuid.UUID("32000000-0000-0000-0000-000000000001")
_FORWARD_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade.sql"
)
_WEBHOOK_TOKEN = "whsec-local-pg17"


@pytest.fixture
def engine_fx(rls_database_url: str) -> Iterator[Engine]:
    engine = create_engine(
        rls_database_url,
        future=True,
        connect_args={"options": f"-c search_path={_SCHEMA}"},
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"drop schema if exists {_SCHEMA} cascade; create schema {_SCHEMA};"
        )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade;")
        engine.dispose()


def _factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


def _apply_forward_migration(engine: Engine) -> None:
    sql = _FORWARD_MIGRATION.read_text(encoding="utf-8")
    sql = sql.replace("public.", f"{_SCHEMA}.").replace(
        "set search_path = public, pg_temp",
        f"set search_path = {_SCHEMA}, pg_temp",
    )
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.execute(
                """
                do $$
                begin
                  if not exists (select 1 from pg_roles where rolname = 'anon') then
                    create role anon nologin;
                  end if;
                  if not exists (
                    select 1 from pg_roles where rolname = 'authenticated'
                  ) then
                    create role authenticated nologin;
                  end if;
                  if not exists (
                    select 1 from pg_roles where rolname = 'service_role'
                  ) then
                    create role service_role nologin;
                  end if;
                end $$;
                """
            )
            cursor.execute(sql)
            raw.commit()
        finally:
            cursor.close()
    finally:
        raw.close()


def _install_existing_autoupgrade_trigger(engine: Engine) -> None:
    """Reproduz no schema descartável os objetos históricos do auto-upgrade."""
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"""
            create unique index billing_plan_change_operations_open_uidx
              on {_SCHEMA}.billing_plan_change_operations (subscription_id)
              where status in ('prepared','processing','reconciling');
            create trigger trg_subscription_autoupgrade
              after insert or update or delete on {_SCHEMA}.pessoas
              for each row
              execute function {_SCHEMA}.fn_subscription_autoupgrade()
            """
        )


def _wait_for_application_lock(engine: Engine, application_name: str) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as observer:
            wait_type = observer.exec_driver_sql(
                "select wait_event_type from pg_stat_activity "
                "where application_name = %s and pid <> pg_backend_pid()",
                (application_name,),
            ).scalar_one_or_none()
        if wait_type == "Lock":
            return True
        time.sleep(0.05)
    return False


def _seed(factory: sessionmaker[Session]) -> None:
    with factory.begin() as db:
        db.add_all(
            [
                Plano(
                    codigo="ate_100",
                    nome="Até 100 membros",
                    limite_pessoas=100,
                    preco_mensal=199,
                    ativo=True,
                    ordem=1,
                ),
                Plano(
                    codigo="101_200",
                    nome="101–200 membros",
                    limite_pessoas=200,
                    preco_mensal=299,
                    ativo=True,
                    ordem=2,
                ),
                Plano(
                    codigo="piloto",
                    nome="Piloto",
                    limite_pessoas=50,
                    preco_mensal=0,
                    ativo=True,
                    ordem=99,
                ),
                Igreja(id=_IGREJA, nome="Igreja corrida", plano="ate_100"),
            ]
        )
        db.flush()
        db.add(
            Subscription(
                id=_SUB,
                igreja_id=_IGREJA,
                plano="ate_100",
                pessoas=20,
                limite=100,
                asaas_subscription_id=None,
            )
        )


def test_checkout_intent_and_complimentary_grant_are_serialized(
    engine_fx: Engine,
) -> None:
    factory = _factory(engine_fx)
    _seed(factory)
    creator_locked = threading.Event()
    grant_started = threading.Event()
    release_creator = threading.Event()
    outcome: dict[str, object] = {}

    def checkout() -> None:
        with factory() as db:
            assert lock_igreja_for_billing(db, _IGREJA) is not None
            db.add(
                BillingSubscriptionOperation(
                    subscription_id=_SUB,
                    operation_key="subscription:race",
                    plano="ate_100",
                    valor=199,
                    limite=100,
                    descricao="PastorAI — plano ate_100",
                    status="creating",
                )
            )
            db.flush()
            creator_locked.set()
            assert release_creator.wait(timeout=10)
            db.commit()

    def grant() -> None:
        assert creator_locked.wait(timeout=10)
        with factory() as db:
            grant_started.set()
            igreja = lock_igreja_for_billing(db, _IGREJA)
            sub = db.execute(
                select(Subscription).where(Subscription.igreja_id == _IGREJA)
            ).scalar_one()
            blocking = find_blocking_subscription_creation(db, sub.id)
            outcome["blocking_type"] = type(blocking)
            outcome["blocking_status"] = blocking.status if blocking else None
            outcome["plan"] = igreja.plano if igreja else None
            db.rollback()

    checkout_thread = threading.Thread(target=checkout)
    grant_thread = threading.Thread(target=grant)
    checkout_thread.start()
    assert creator_locked.wait(timeout=10)
    grant_thread.start()
    assert grant_started.wait(timeout=10)
    release_creator.set()
    for thread in (checkout_thread, grant_thread):
        thread.join(timeout=10)
        assert not thread.is_alive(), "corrida checkout/cortesia não terminou"

    assert outcome["blocking_type"] is BillingSubscriptionOperation
    assert outcome["blocking_status"] == "creating"
    assert outcome["plan"] == "ate_100"

    # Ordem inversa: cortesia comita primeiro; o checkout que acorda enxerga a
    # concessão e não tem autorização para criar intenção financeira.
    with factory.begin() as db:
        op = db.execute(select(BillingSubscriptionOperation)).scalar_one()
        op.status = "failed"
    master_locked = threading.Event()
    checkout_started = threading.Event()
    release_master = threading.Event()
    reverse: dict[str, object] = {}

    def grant_first() -> None:
        with factory() as db:
            igreja = lock_igreja_for_billing(db, _IGREJA)
            assert igreja is not None
            igreja.plano = "piloto"
            master_locked.set()
            assert release_master.wait(timeout=10)
            db.commit()

    def checkout_second() -> None:
        assert master_locked.wait(timeout=10)
        with factory() as db:
            stale = db.get(Igreja, _IGREJA)
            assert stale is not None and stale.plano == "ate_100"
            checkout_started.set()
            igreja = lock_igreja_for_billing(db, _IGREJA)
            reverse["complimentary"] = assigned_complimentary_plan(db, igreja)
            reverse["operations"] = db.execute(
                select(BillingSubscriptionOperation).where(
                    BillingSubscriptionOperation.status.not_in(
                        ("failed", "superseded")
                    )
                )
            ).scalars().all()
            db.rollback()

    master_thread = threading.Thread(target=grant_first)
    checkout_thread = threading.Thread(target=checkout_second)
    master_thread.start()
    assert master_locked.wait(timeout=10)
    checkout_thread.start()
    assert checkout_started.wait(timeout=10)
    release_master.set()
    for thread in (master_thread, checkout_thread):
        thread.join(timeout=10)
        assert not thread.is_alive(), "corrida cortesia/checkout não terminou"

    assert isinstance(reverse["complimentary"], Plano)
    assert reverse["operations"] == []


class _NoNetworkAsaas:
    calls = 0

    def get_subscription(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("catálogo cortesia deve bloquear antes da rede")

    def update_subscription(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("catálogo cortesia deve bloquear antes da rede")


def test_plan_conversion_and_open_change_are_serialized(engine_fx: Engine) -> None:
    factory = _factory(engine_fx)
    _seed(factory)
    operation_locked = threading.Event()
    conversion_started = threading.Event()
    release_operation = threading.Event()
    outcome: dict[str, object] = {}

    def open_change() -> None:
        with factory() as db:
            lock_plan_rows_for_billing(db, "ate_100", "101_200")
            db.add(
                BillingPlanChangeOperation(
                    subscription_id=_SUB,
                    asaas_subscription_id="asaas-race",
                    from_plano="ate_100",
                    to_plano="101_200",
                    to_preco=299,
                    to_limite=200,
                    to_descricao="PastorAI — plano 101_200",
                    origin="manual",
                    status="prepared",
                    notify_status="skipped",
                )
            )
            db.flush()
            operation_locked.set()
            assert release_operation.wait(timeout=10)
            db.commit()

    def convert() -> None:
        assert operation_locked.wait(timeout=10)
        with factory() as db:
            conversion_started.set()
            lock_plan_rows_for_billing(db, "101_200")
            blocking = find_blocking_plan_change_for_plan(db, "101_200")
            outcome["blocking_type"] = type(blocking)
            outcome["blocking_status"] = blocking.status if blocking else None
            db.rollback()

    operation_thread = threading.Thread(target=open_change)
    conversion_thread = threading.Thread(target=convert)
    operation_thread.start()
    assert operation_locked.wait(timeout=10)
    conversion_thread.start()
    assert conversion_started.wait(timeout=10)
    release_operation.set()
    for thread in (operation_thread, conversion_thread):
        thread.join(timeout=10)
        assert not thread.is_alive(), "corrida operação/conversão não terminou"

    assert outcome["blocking_type"] is BillingPlanChangeOperation
    assert outcome["blocking_status"] == "prepared"

    # Ordem inversa: a conversão vence; a operação que acorda falha antes de
    # persistir/retomar PUT e sem tocar na rede.
    with factory.begin() as db:
        op = db.execute(select(BillingPlanChangeOperation)).scalar_one()
        op.status = "failed"
    converted = threading.Event()
    worker_started = threading.Event()
    release_conversion = threading.Event()
    network = _NoNetworkAsaas()
    reverse: dict[str, object] = {}

    def convert_first() -> None:
        with factory() as db:
            target = lock_plan_rows_for_billing(db, "101_200")["101_200"]
            target.preco_mensal = 0
            converted.set()
            assert release_conversion.wait(timeout=10)
            db.commit()

    def worker_second() -> None:
        assert converted.wait(timeout=10)
        with factory() as db:
            stale = db.execute(
                select(Plano).where(Plano.codigo == "101_200")
            ).scalar_one()
            assert float(stale.preco_mensal) == 299
            worker_started.set()
            sub = db.get(Subscription, _SUB)
            try:
                ensure_plan_change_operation(
                    db,
                    network,
                    sub=sub,
                    to_plano="101_200",
                    to_preco=299,
                    to_limite=200,
                )
            except PlanChangeConflict as exc:
                reverse["error"] = str(exc)
            reverse["open"] = db.execute(
                select(BillingPlanChangeOperation).where(
                    BillingPlanChangeOperation.status.in_(
                        ("prepared", "processing", "reconciling")
                    )
                )
            ).scalars().all()
            db.rollback()

    conversion_thread = threading.Thread(target=convert_first)
    worker_thread = threading.Thread(target=worker_second)
    conversion_thread.start()
    assert converted.wait(timeout=10)
    worker_thread.start()
    assert worker_started.wait(timeout=10)
    release_conversion.set()
    for thread in (conversion_thread, worker_thread):
        thread.join(timeout=10)
        assert not thread.is_alive(), "corrida conversão/operação não terminou"

    assert "virou cortesia" in str(reverse["error"])
    assert reverse["open"] == []
    assert network.calls == 0


def test_webhook_and_autoupgrade_trigger_share_canonical_locks(
    engine_fx: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Webhook e trigger reais serializam sem 40P01 nem estado parcial."""
    factory = _factory(engine_fx)
    settings = get_settings()
    monkeypatch.setattr(
        settings, "asaas_webhook_token", _WEBHOOK_TOKEN, raising=False
    )

    def church_id(index: int) -> uuid.UUID:
        return uuid.UUID(f"41000000-0000-0000-0000-{index:012d}")

    def subscription_id(index: int) -> uuid.UUID:
        return uuid.UUID(f"42000000-0000-0000-0000-{index:012d}")

    race_indexes = range(1, 9)
    rollback_index = 99
    with factory.begin() as db:
        db.add_all(
            [
                Plano(
                    codigo="ate_100",
                    nome="Até 100 membros",
                    limite_pessoas=100,
                    preco_mensal=199,
                    ativo=True,
                    ordem=1,
                ),
                Plano(
                    codigo="101_200",
                    nome="101–200 membros",
                    limite_pessoas=200,
                    preco_mensal=299,
                    ativo=True,
                    ordem=2,
                ),
                Plano(
                    codigo="acima_201",
                    nome="Acima de 201 membros",
                    limite_pessoas=None,
                    preco_mensal=399,
                    ativo=True,
                    ordem=3,
                ),
            ]
        )
        for index in [*race_indexes, rollback_index]:
            igreja_id = church_id(index)
            db.add(
                Igreja(
                    id=igreja_id,
                    nome=f"Igreja webhook {index}",
                    plano="ate_100",
                    status="ativa",
                )
            )
            db.add(
                Subscription(
                    id=subscription_id(index),
                    igreja_id=igreja_id,
                    plano="ate_100",
                    status="pendente",
                    pessoas=100,
                    limite=100,
                    asaas_customer_id=f"cus_pg17_{index}",
                    asaas_subscription_id=f"sub_pg17_{index}",
                    setup_pago=True,
                    setup_fee_contracted=0,
                )
            )
            db.add_all(
                [
                    Pessoa(
                        igreja_id=igreja_id,
                        nome=f"Membro {index}-{member}",
                        telefone=f"55{index:03d}{member:08d}",
                        tipo="membro",
                    )
                    for member in range(1, 101)
                ]
            )

    # A migration real permanece intocada; apply/reapply ocorre só no schema
    # descartável desta fixture PostgreSQL.
    _apply_forward_migration(engine_fx)
    _install_existing_autoupgrade_trigger(engine_fx)
    _apply_forward_migration(engine_fx)

    errors: list[BaseException] = []
    webhook_statuses: list[str | None] = []

    def sqlstate(exc: BaseException) -> str | None:
        original = getattr(exc, "orig", None)
        return getattr(original, "sqlstate", None) or getattr(
            original, "pgcode", None
        )

    for index in race_indexes:
        barrier = threading.Barrier(2)
        igreja_id = church_id(index)
        remote_id = f"sub_pg17_{index}"
        payment_id = f"pay_pg17_{index}"

        def trigger_member(
            *, current_index: int = index, current_church: uuid.UUID = igreja_id
        ) -> None:
            try:
                with factory() as db:
                    db.execute(text("set local lock_timeout = '8s'"))
                    barrier.wait(timeout=5)
                    db.add(
                        Pessoa(
                            igreja_id=current_church,
                            nome=f"Membro {current_index}-101",
                            telefone=f"55{current_index:03d}00000101",
                            tipo="membro",
                        )
                    )
                    db.commit()
            except BaseException as exc:  # noqa: BLE001 - transporta da thread
                errors.append(exc)

        def deliver_webhook(
            *,
            current_index: int = index,
            current_remote: str = remote_id,
            current_payment: str = payment_id,
        ) -> None:
            try:
                with factory() as db:
                    db.execute(text("set local lock_timeout = '8s'"))
                    barrier.wait(timeout=5)
                    result = asaas_webhook(
                        AsaasWebhookEvent(
                            event="PAYMENT_OVERDUE",
                            payment={
                                "id": current_payment,
                                "status": "OVERDUE",
                                "subscription": current_remote,
                                "externalReference": str(church_id(current_index)),
                                "dueDate": "2026-08-10",
                                "invoiceUrl": (
                                    f"https://example.invalid/{current_payment}"
                                ),
                                "value": 199.0,
                            },
                        ),
                        db=db,
                        asaas_access_token=_WEBHOOK_TOKEN,
                    )
                    webhook_statuses.append(result.status)
            except BaseException as exc:  # noqa: BLE001 - transporta da thread
                errors.append(exc)

        trigger_thread = threading.Thread(target=trigger_member)
        webhook_thread = threading.Thread(target=deliver_webhook)
        trigger_thread.start()
        webhook_thread.start()
        for thread in (trigger_thread, webhook_thread):
            thread.join(timeout=12)
            assert not thread.is_alive(), "webhook/trigger não concluiu"

    assert [sqlstate(exc) for exc in errors if sqlstate(exc)] == []
    assert errors == []
    assert webhook_statuses == ["inadimplente"] * len(race_indexes)

    with factory.begin() as db:
        for index in race_indexes:
            igreja = db.get(Igreja, church_id(index))
            sub = db.get(Subscription, subscription_id(index))
            people = db.execute(
                select(Pessoa).where(Pessoa.igreja_id == church_id(index))
            ).scalars().all()
            operations = db.execute(
                select(BillingPlanChangeOperation).where(
                    BillingPlanChangeOperation.subscription_id
                    == subscription_id(index)
                )
            ).scalars().all()
            assert igreja is not None and sub is not None
            assert (
                igreja.status,
                sub.status,
                sub.asaas_invoice_payment_id,
                sub.pessoas,
                len(people),
                len(operations),
            ) == (
                "inadimplente",
                "inadimplente",
                f"pay_pg17_{index}",
                101,
                101,
                1,
            )

    # Rollback adversarial: o trigger chega a criar sua operação dentro da
    # transação, o webhook espera a Igreja e só prossegue depois do rollback.
    # Nenhum membro/operação parcial pode sobreviver.
    inserted = threading.Event()
    release_trigger = threading.Event()
    webhook_started = threading.Event()
    rollback_errors: list[BaseException] = []
    rollback_status: list[str | None] = []
    rollback_app = "billing-webhook-after-trigger-rollback"

    def trigger_then_rollback() -> None:
        try:
            with factory() as db:
                db.execute(text("set local lock_timeout = '8s'"))
                db.add(
                    Pessoa(
                        igreja_id=church_id(rollback_index),
                        nome="Membro rollback 101",
                        telefone="5599900000101",
                        tipo="membro",
                    )
                )
                db.flush()
                inserted.set()
                assert release_trigger.wait(timeout=8)
                db.rollback()
        except BaseException as exc:  # noqa: BLE001 - transporta da thread
            rollback_errors.append(exc)

    def webhook_after_rollback() -> None:
        try:
            assert inserted.wait(timeout=8)
            with factory() as db:
                db.execute(text(f"set local application_name = '{rollback_app}'"))
                db.execute(text("set local lock_timeout = '8s'"))
                webhook_started.set()
                result = asaas_webhook(
                    AsaasWebhookEvent(
                        event="PAYMENT_CONFIRMED",
                        payment={
                            "id": "pay_pg17_rollback",
                            "status": "CONFIRMED",
                            "subscription": f"sub_pg17_{rollback_index}",
                            "externalReference": str(church_id(rollback_index)),
                            "dueDate": "2026-08-10",
                            "value": 199.0,
                        },
                    ),
                    db=db,
                    asaas_access_token=_WEBHOOK_TOKEN,
                )
                rollback_status.append(result.status)
        except BaseException as exc:  # noqa: BLE001 - transporta da thread
            rollback_errors.append(exc)

    trigger_thread = threading.Thread(target=trigger_then_rollback)
    webhook_thread = threading.Thread(target=webhook_after_rollback)
    trigger_thread.start()
    assert inserted.wait(timeout=8)
    webhook_thread.start()
    assert webhook_started.wait(timeout=8)
    assert _wait_for_application_lock(engine_fx, rollback_app)
    release_trigger.set()
    for thread in (trigger_thread, webhook_thread):
        thread.join(timeout=12)
        assert not thread.is_alive(), "rollback/webhook não concluiu"

    assert [sqlstate(exc) for exc in rollback_errors if sqlstate(exc)] == []
    assert rollback_errors == []
    assert rollback_status == ["ativa"]
    with factory.begin() as db:
        sub = db.get(Subscription, subscription_id(rollback_index))
        people = db.execute(
            select(Pessoa).where(Pessoa.igreja_id == church_id(rollback_index))
        ).scalars().all()
        operations = db.execute(
            select(BillingPlanChangeOperation).where(
                BillingPlanChangeOperation.subscription_id
                == subscription_id(rollback_index)
            )
        ).scalars().all()
        assert sub is not None
        assert sub.status == "ativa"
        assert sub.pessoas == 100
        assert sub.asaas_invoice_payment_id == "pay_pg17_rollback"
        assert len(people) == 100
        assert operations == []
