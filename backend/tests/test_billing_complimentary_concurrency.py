"""Corridas reais entre billing e cortesia em PostgreSQL descartável."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Base,
    BillingPlanChangeOperation,
    BillingSubscriptionOperation,
    Igreja,
    Plano,
    Subscription,
)
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
