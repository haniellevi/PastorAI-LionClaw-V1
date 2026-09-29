"""PG17 proof that a reused session refreshes the V3 reply fence."""

from __future__ import annotations

import datetime as dt
import os
from urllib.parse import urlsplit
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

import app.db.session  # noqa: F401 - registers the tenant-session listener
from app.db.models import Consolidacao, WorkQueueItem
from app.db.tenant_session import mark_tenant_scoped
from app.services.consolidation_privileged import consolidation_pending_reply
from app.services.whatsapp_privilege import PrivilegeContext
from tests.conftest_rls import assert_disposable_database
from tests.test_whatsapp_consolidation_v3_migration_pg import (
    _MIGRATION as _V3_MIGRATION,
    _apply as _apply_v3_migration,
    v3_database as _v3_database,
)


pytestmark = pytest.mark.rls_integration


def _turn_database_url() -> str:
    url = os.environ.get("V3_TURN_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("V3_TURN_DATABASE_URL não definida")
    assert_disposable_database(url)
    parsed = urlsplit(url)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("banco de turno V3 deve ser loopback descartável")
    if parsed.path.rstrip("/") != "/v3_consolidation_test":
        raise RuntimeError("banco de turno V3 deve ser exclusivo")
    return url


@pytest.fixture
def rls_database_url() -> str:
    return _turn_database_url()


@pytest.fixture
def privileged_database(rls_database_url: str):
    generator = _v3_database.__wrapped__(rls_database_url)
    engine = next(generator)
    try:
        _apply_v3_migration(engine, _V3_MIGRATION.read_text())
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "alter table pessoas add column if not exists nome text "
                "not null default 'Pessoa sintética'"
            )
        yield engine
    finally:
        try:
            next(generator)
        except StopIteration:
            pass


def _factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def _scoped(factory: sessionmaker[Session], tenant: uuid.UUID) -> Session:
    session = factory()
    mark_tenant_scoped(session, tenant, source="v3_consolidation_privileged_pg")
    assert session.execute(text("select current_user")).scalar_one() == "authenticated"
    assert session.execute(
        text("select rolbypassrls from pg_roles where rolname = current_user")
    ).scalar_one() is False
    return session


def _seed(engine) -> dict[str, uuid.UUID]:
    values = {
        "tenant": uuid.uuid4(),
        "subject": uuid.uuid4(),
        "actor_person": uuid.uuid4(),
        "actor": uuid.uuid4(),
        "other_person": uuid.uuid4(),
        "other": uuid.uuid4(),
        "track": uuid.uuid4(),
        "item": uuid.uuid4(),
    }
    with engine.begin() as connection:
        connection.execute(
            text("insert into igrejas(id,status) values(:tenant,'ativa')"), values
        )
        for key, name, phone in (
            ("subject", "Maria Silva", "5500000000101"),
            ("actor_person", "Ana Líder", "5500000000102"),
            ("other_person", "Bia Líder", "5500000000103"),
        ):
            connection.execute(
                text(
                    "insert into pessoas(id,igreja_id,nome,telefone) "
                    "values(:id,:tenant,:name,:phone)"
                ),
                {"id": values[key], "tenant": values["tenant"], "name": name, "phone": phone},
            )
        for user_key, person_key in (("actor", "actor_person"), ("other", "other_person")):
            connection.execute(
                text(
                    "insert into app_users(id,igreja_id,pessoa_id,clerk_user_id,status) "
                    "values(:id,:tenant,:person,:clerk,'ativo')"
                ),
                {
                    "id": values[user_key],
                    "tenant": values["tenant"],
                    "person": values[person_key],
                    "clerk": f"clerk-{values[user_key]}",
                },
            )
        connection.execute(
            text(
                "insert into consolidacoes("
                "id,igreja_id,pessoa_id,tipo,responsavel_id,progresso,concluida"
                ") values(:track,:tenant,:subject,'individual',:actor,20,false)"
            ),
            values,
        )
        connection.execute(
            text(
                "insert into work_queue_items("
                "id,igreja_id,consolidacao_id,tipo,titulo,pessoa_id,responsavel_id,"
                "status,prazo,prioridade"
                ") values(:item,:tenant,:track,'conectar_celula','Conectar',:subject,"
                ":actor,'aberto',:due,1)"
            ),
            {
                **values,
                "due": dt.datetime(2026, 10, 1, 12, tzinfo=dt.timezone.utc),
            },
        )
    return values


def _context(values: dict[str, uuid.UUID]) -> PrivilegeContext:
    return PrivilegeContext(
        igreja_id=values["tenant"],
        conversation_id=uuid.uuid4(),
        inbound_message_id=uuid.uuid4(),
        pessoa_id=values["actor_person"],
        app_user_id=values["actor"],
        roles=frozenset({"lider_consol"}),
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


def test_delivery_fence_refreshes_reused_session_after_assignment_changes(
    privileged_database,
    monkeypatch,
) -> None:
    """A reused session must render the post-assignment opaque projection."""

    import app.services.consolidation_privileged as privileged

    values = _seed(privileged_database)
    factory = _factory(privileged_database)
    monkeypatch.setattr(privileged, "consolidation_enabled_from_environment", lambda _tenant: True)
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: type("Settings", (), {"frontend_url": "https://app.igreja12.example"})(),
    )
    context = _context(values)

    reused = _scoped(factory, values["tenant"])
    try:
        assert reused.execute(
            select(Consolidacao).where(Consolidacao.id == values["track"])
        ).scalar_one().responsavel_id == values["actor"]
        assert reused.execute(
            select(WorkQueueItem).where(WorkQueueItem.id == values["item"])
        ).scalar_one().responsavel_id == values["actor"]

        changed = _scoped(factory, values["tenant"])
        try:
            changed.execute(
                text(
                    "update consolidacoes set responsavel_id=:other "
                    "where igreja_id=:tenant and id=:track"
                ),
                values,
            )
            changed.execute(
                text(
                    "update work_queue_items set responsavel_id=:other "
                    "where igreja_id=:tenant and consolidacao_id=:track"
                ),
                values,
            )
            changed.commit()
        finally:
            changed.close()

        assert reused.execute(
            text("select responsavel_id from consolidacoes where id=:track"),
            values,
        ).scalar_one() == values["other"]
        assert reused.execute(
            text(
                "select count(*) from work_queue_items "
                "where igreja_id=:tenant and consolidacao_id=:track and responsavel_id=:other"
            ),
            values,
        ).scalar_one() == 2
        refreshed = consolidation_pending_reply(reused, context=context, for_transport=True)
        assert refreshed is not None
        assert "Maria" not in refreshed.response
        assert "P-" in refreshed.response
    finally:
        reused.rollback()
        reused.close()
