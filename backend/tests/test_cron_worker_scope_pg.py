"""PostgreSQL proof that scheduled SLA actions stay inside one church scope."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import event, select, text

from app.db.models import Cron, Igreja
from app.db.tenant_session import CROSS_TENANT_KEY, TENANT_META_KEY
from app.workers.cron_worker import run_due_crons
from tests.conftest_rls import assert_disposable_database
from tests.test_whatsapp_integrated_pg import migrated_factory as _migrated_factory

pytestmark = pytest.mark.rls_integration


@pytest.fixture(scope="module")
def rls_database_url() -> str:
    url = os.environ.get("RLS_TEST_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("RLS_TEST_DATABASE_URL is required for the cron PostgreSQL proof")
    assert_disposable_database(url)
    return url


@pytest.fixture
def migrated_factory_pg(rls_database_url):
    generator = _migrated_factory.__wrapped__(rls_database_url)
    factory = next(generator)
    try:
        yield factory
    finally:
        generator.close()


def test_due_crons_discover_ids_then_run_sla_in_tenant_sessions(migrated_factory_pg):
    factory = migrated_factory_pg
    bind = factory.kw["bind"]
    igreja_a, igreja_b = uuid.uuid4(), uuid.uuid4()
    with factory.begin() as session:
        session.add_all(
            [
                Igreja(id=igreja_a, nome="Igreja sintética A"),
                Igreja(id=igreja_b, nome="Igreja sintética B"),
            ]
        )
        session.flush()
        session.add_all(
            [
                Cron(
                    igreja_id=igreja_a,
                    nome="SLA sintético A",
                    frequencia="continuo",
                    acao="rodar_sla",
                    ativo=True,
                ),
                Cron(
                    igreja_id=igreja_b,
                    nome="SLA sintético B",
                    frequencia="continuo",
                    acao="rodar_sla",
                    ativo=True,
                ),
            ]
        )

    cron_queries: list[str] = []

    def record_query(_conn, _cursor, statement, _params, _context, _executemany):
        normalized = statement.lower()
        if "select crons.id" in normalized and "from crons" in normalized:
            cron_queries.append(normalized)

    class ScopeProbe:
        def __init__(self) -> None:
            self.calls: list[uuid.UUID] = []

        def run_for_igreja(self, session, igreja_id, now=None, *, progress_callback=None):
            role, scope = session.execute(
                text("select current_user, current_setting('app.tenant_igreja_id', true)")
            ).one()
            assert role == "authenticated"
            assert scope == str(igreja_id)
            assert set(session.execute(select(Cron.igreja_id)).scalars()) == {igreja_id}

            session.commit()

            role_after, scope_after = session.execute(
                text("select current_user, current_setting('app.tenant_igreja_id', true)")
            ).one()
            assert role_after == "authenticated"
            assert scope_after == str(igreja_id)
            assert set(session.execute(select(Cron.igreja_id)).scalars()) == {igreja_id}
            self.calls.append(igreja_id)
            return []

    probe = ScopeProbe()
    tenant_sessions = []

    def tenant_factory():
        session = factory()
        tenant_sessions.append(session)
        return session

    discovery = factory()
    event.listen(bind, "before_cursor_execute", record_query)
    try:
        dispatched = run_due_crons(
            discovery,
            engine=probe,
            session_factory=tenant_factory,
            last_run={},
        )
    finally:
        event.remove(bind, "before_cursor_execute", record_query)
        discovery.close()

    assert dispatched == 2
    assert set(probe.calls) == {igreja_a, igreja_b}
    assert discovery.info[CROSS_TENANT_KEY] is True
    assert discovery.info[TENANT_META_KEY]["source"] == "cron_due_discovery"
    assert len(tenant_sessions) == 2
    assert len(cron_queries) == 2
    assert all("crons.igreja_id =" in statement for statement in cron_queries)
    assert all("crons.ativo is true" in statement for statement in cron_queries)

    with bind.connect() as connection:
        role, scope = connection.execute(
            text("select current_user, current_setting('app.tenant_igreja_id', true)")
        ).one()
    assert role != "authenticated"
    assert scope in (None, "")
    assert bind.pool.checkedout() == 0
