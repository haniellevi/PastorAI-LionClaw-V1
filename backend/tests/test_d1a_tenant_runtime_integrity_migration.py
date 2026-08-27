"""Contrato D1A de integridade multi-tenant e instância Evolution única."""

from __future__ import annotations

import pathlib
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from psycopg2 import Error as PsycopgError
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    AppUser,
    ConsentRecord,
    Conversation,
    Message,
    Pessoa,
    UserRole,
    WhatsappConnection,
)
from tests.conftest_rls import rls_database_url  # noqa: F401


_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260827_175634_d1a_tenant_runtime_integrity.sql"
)
_SCHEMA = "d1a_tenant_runtime_integrity"

_PARENT_UNIQUES = {
    "pessoas_igreja_id_id_key",
    "app_users_igreja_id_id_key",
    "conversations_igreja_id_id_key",
}
_TENANT_FKS = {
    "pessoas_tenant_lider_fkey",
    "pessoas_tenant_arquivada_por_fkey",
    "app_users_tenant_pessoa_fkey",
    "user_roles_tenant_user_fkey",
    "conversations_tenant_pessoa_fkey",
    "conversations_tenant_assumido_por_fkey",
    "messages_tenant_conversation_fkey",
    "messages_tenant_enviado_por_fkey",
    "consent_records_tenant_pessoa_fkey",
    "consent_records_tenant_ator_fkey",
}
_TENANT_INDEXES = {
    "whatsapp_connections_instance_uidx",
    "pessoas_igreja_id_lider_id_idx",
    "pessoas_igreja_id_arquivada_por_idx",
    "app_users_igreja_id_pessoa_id_idx",
    "user_roles_igreja_id_user_id_idx",
    "conversations_igreja_id_pessoa_id_idx",
    "conversations_igreja_id_assumido_por_idx",
    "messages_igreja_id_conversation_id_idx",
    "messages_igreja_id_enviado_por_idx",
    "consent_records_igreja_id_pessoa_id_idx",
    "consent_records_igreja_id_ator_id_idx",
}

_TENANT_REFERENCE_CASES = (
    ("pessoas", "lider_id", "pessoa_a", "pessoa_b", "pessoas.lider_id"),
    (
        "pessoas",
        "arquivada_por",
        "pessoa_a",
        "user_b",
        "pessoas.arquivada_por",
    ),
    ("app_users", "pessoa_id", "user_a", "pessoa_b", "app_users.pessoa_id"),
    ("user_roles", "user_id", "role_a", "user_b", "user_roles.user_id"),
    (
        "conversations",
        "pessoa_id",
        "conversation_a",
        "pessoa_b",
        "conversations.pessoa_id",
    ),
    (
        "conversations",
        "assumido_por",
        "conversation_a",
        "user_b",
        "conversations.assumido_por",
    ),
    (
        "messages",
        "conversation_id",
        "message_a",
        "conversation_b",
        "messages.conversation_id",
    ),
    ("messages", "enviado_por", "message_a", "user_b", "messages.enviado_por"),
    (
        "consent_records",
        "pessoa_id",
        "consent_a",
        "pessoa_b",
        "consent_records.pessoa_id",
    ),
    (
        "consent_records",
        "ator_id",
        "consent_a",
        "user_b",
        "consent_records.ator_id",
    ),
)

_MINIMAL_SCHEMA_SQL = """
create table igrejas (
  id uuid primary key
);

create table pessoas (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id) on delete cascade,
  lider_id uuid references pessoas(id) on delete set null
);

create table app_users (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id) on delete cascade,
  pessoa_id uuid references pessoas(id) on delete set null
);

alter table pessoas
  add column arquivada_por uuid references app_users(id) on delete set null;

create table user_roles (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id) on delete cascade,
  user_id uuid not null references app_users(id) on delete cascade
);

create table conversations (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id) on delete cascade,
  pessoa_id uuid references pessoas(id) on delete set null,
  assumido_por uuid references app_users(id) on delete set null
);

create table messages (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id) on delete cascade,
  conversation_id uuid not null references conversations(id) on delete cascade,
  enviado_por uuid references app_users(id) on delete set null
);

create table consent_records (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id) on delete cascade,
  pessoa_id uuid not null references pessoas(id) on delete cascade,
  ator_id uuid references app_users(id) on delete set null
);

create table whatsapp_connections (
  id uuid primary key,
  igreja_id uuid not null unique references igrejas(id) on delete cascade,
  instance text
);
"""


def _migration_sql() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def _migration_sql_for_disposable_schema() -> str:
    """Redireciona somente os alvos public para o schema sintético do teste."""

    return _migration_sql().replace("public.", f"{_SCHEMA}.")


def _apply_real_migration(engine: Engine) -> None:
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.execute(_migration_sql_for_disposable_schema())
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            cursor.close()
    finally:
        raw.close()


@pytest.fixture
def d1a_engine(rls_database_url: str) -> Engine:
    admin = create_engine(rls_database_url, future=True)
    with admin.begin() as connection:
        connection.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade")
        connection.exec_driver_sql(f"create schema {_SCHEMA}")

    engine = create_engine(
        rls_database_url,
        connect_args={"options": f"-csearch_path={_SCHEMA},public"},
        future=True,
    )
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(_MINIMAL_SCHEMA_SQL)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(
                f"drop schema if exists {_SCHEMA} cascade"
            )
        admin.dispose()


def _seed_valid_graph(engine: Engine) -> dict[str, str]:
    values = {
        "igreja_a": str(uuid.uuid4()),
        "igreja_b": str(uuid.uuid4()),
        "pessoa_a": str(uuid.uuid4()),
        "pessoa_b": str(uuid.uuid4()),
        "leader_a": str(uuid.uuid4()),
        "user_a": str(uuid.uuid4()),
        "user_b": str(uuid.uuid4()),
        "role_a": str(uuid.uuid4()),
        "role_b": str(uuid.uuid4()),
        "conversation_a": str(uuid.uuid4()),
        "conversation_b": str(uuid.uuid4()),
        "message_a": str(uuid.uuid4()),
        "message_b": str(uuid.uuid4()),
        "consent_a": str(uuid.uuid4()),
        "consent_b": str(uuid.uuid4()),
        "connection_a": str(uuid.uuid4()),
        "connection_b": str(uuid.uuid4()),
    }
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "insert into igrejas (id) values (%s), (%s)",
            (values["igreja_a"], values["igreja_b"]),
        )
        connection.exec_driver_sql(
            "insert into pessoas (id, igreja_id) "
            "values (%s, %s), (%s, %s), (%s, %s)",
            (
                values["pessoa_a"],
                values["igreja_a"],
                values["pessoa_b"],
                values["igreja_b"],
                values["leader_a"],
                values["igreja_a"],
            ),
        )
        connection.exec_driver_sql(
            "insert into app_users (id, igreja_id, pessoa_id) "
            "values (%s, %s, %s), (%s, %s, %s)",
            (
                values["user_a"],
                values["igreja_a"],
                values["pessoa_a"],
                values["user_b"],
                values["igreja_b"],
                values["pessoa_b"],
            ),
        )
        connection.exec_driver_sql(
            "update pessoas set arquivada_por = case id "
            "when %s then %s::uuid when %s then %s::uuid end",
            (
                values["pessoa_a"],
                values["user_a"],
                values["pessoa_b"],
                values["user_b"],
            ),
        )
        connection.exec_driver_sql(
            "insert into user_roles (id, igreja_id, user_id) "
            "values (%s, %s, %s), (%s, %s, %s)",
            (
                values["role_a"],
                values["igreja_a"],
                values["user_a"],
                values["role_b"],
                values["igreja_b"],
                values["user_b"],
            ),
        )
        connection.exec_driver_sql(
            "insert into conversations (id, igreja_id, pessoa_id, assumido_por) "
            "values (%s, %s, %s, %s), (%s, %s, %s, %s)",
            (
                values["conversation_a"],
                values["igreja_a"],
                values["pessoa_a"],
                values["user_a"],
                values["conversation_b"],
                values["igreja_b"],
                values["pessoa_b"],
                values["user_b"],
            ),
        )
        connection.exec_driver_sql(
            "insert into messages (id, igreja_id, conversation_id, enviado_por) "
            "values (%s, %s, %s, %s), (%s, %s, %s, %s)",
            (
                values["message_a"],
                values["igreja_a"],
                values["conversation_a"],
                values["user_a"],
                values["message_b"],
                values["igreja_b"],
                values["conversation_b"],
                values["user_b"],
            ),
        )
        connection.exec_driver_sql(
            "insert into consent_records (id, igreja_id, pessoa_id, ator_id) "
            "values (%s, %s, %s, %s), (%s, %s, %s, %s)",
            (
                values["consent_a"],
                values["igreja_a"],
                values["pessoa_a"],
                values["user_a"],
                values["consent_b"],
                values["igreja_b"],
                values["pessoa_b"],
                values["user_b"],
            ),
        )
        connection.exec_driver_sql(
            "insert into whatsapp_connections (id, igreja_id, instance) "
            "values (%s, %s, null), (%s, %s, null)",
            (
                values["connection_a"],
                values["igreja_a"],
                values["connection_b"],
                values["igreja_b"],
            ),
        )
    return values


def test_orm_e_migration_declaram_o_mesmo_contrato_aditivo() -> None:
    sql = _migration_sql().lower()
    constraint_names = {
        constraint.name
        for table in (Pessoa, AppUser, UserRole, Conversation, Message, ConsentRecord)
        for constraint in table.__table__.constraints
        if constraint.name is not None
    }
    index_names = {
        index.name
        for table in (
            Pessoa,
            AppUser,
            UserRole,
            Conversation,
            Message,
            ConsentRecord,
            WhatsappConnection,
        )
        for index in table.__table__.indexes
    }

    assert _PARENT_UNIQUES <= constraint_names
    assert _TENANT_FKS <= constraint_names
    assert _TENANT_INDEXES <= index_names
    assert "set transaction isolation level serializable" in sql
    assert "set local search_path = pg_catalog, public" in sql
    assert "set local lock_timeout = '5s'" in sql
    assert "set local statement_timeout = '120s'" in sql
    assert "in share row exclusive mode" in sql
    assert "not valid" in sql
    assert "validate constraint" in sql
    assert "create index concurrently" not in sql
    assert not re.search(r"(?m)^\s*(update|delete|insert)\s", sql)
    assert not re.search(r"(?m)^\s*(grant|revoke)\s", sql)
    for table in (
        "pessoas",
        "app_users",
        "user_roles",
        "conversations",
        "messages",
        "consent_records",
        "whatsapp_connections",
    ):
        assert f"public.{table}" in sql


@pytest.mark.rls_integration
def test_real_migration_duas_vezes_fecha_instancia_e_todas_as_relacoes(
    d1a_engine: Engine,
) -> None:
    values = _seed_valid_graph(d1a_engine)
    _apply_real_migration(d1a_engine)
    _apply_real_migration(d1a_engine)

    with d1a_engine.begin() as connection:
        constraints = connection.exec_driver_sql(
            "select conname, convalidated from pg_constraint "
            "where conrelid in ("
            "'pessoas'::regclass, 'app_users'::regclass, "
            "'user_roles'::regclass, 'conversations'::regclass, "
            "'messages'::regclass, 'consent_records'::regclass) "
            "and conname = any(%s)",
            (list(_TENANT_FKS),),
        ).all()
        assert {row[0] for row in constraints} == _TENANT_FKS
        assert all(row[1] is True for row in constraints)

    for table, column, child_key, parent_key, _error_fragment in (
        _TENANT_REFERENCE_CASES
    ):
        with pytest.raises(IntegrityError):
            with d1a_engine.begin() as connection:
                connection.exec_driver_sql(
                    f"update {table} set {column} = %s where id = %s",
                    (values[parent_key], values[child_key]),
                )

    with d1a_engine.begin() as connection:
        connection.exec_driver_sql(
            "update whatsapp_connections set instance = 'instancia-unica' "
            "where id = %s",
            (values["connection_a"],),
        )
    with pytest.raises(IntegrityError):
        with d1a_engine.begin() as connection:
            connection.exec_driver_sql(
                "update whatsapp_connections set instance = 'instancia-unica' "
                "where id = %s",
                (values["connection_b"],),
            )


@pytest.mark.rls_integration
@pytest.mark.parametrize(
    "table,column,child_key,parent_key,error_fragment",
    _TENANT_REFERENCE_CASES,
)
def test_preflight_cross_tenant_aborta_atomicamente_sem_expor_ids(
    d1a_engine: Engine,
    table: str,
    column: str,
    child_key: str,
    parent_key: str,
    error_fragment: str,
) -> None:
    values = _seed_valid_graph(d1a_engine)
    with d1a_engine.begin() as connection:
        connection.exec_driver_sql(
            f"update {table} set {column} = %s where id = %s",
            (values[parent_key], values[child_key]),
        )

    with pytest.raises(PsycopgError) as raised:
        _apply_real_migration(d1a_engine)

    error = str(raised.value)
    assert f"{error_fragment} tenant mismatch" in error
    assert "rows=1" in error
    assert all(identifier not in error for identifier in values.values())

    with d1a_engine.begin() as connection:
        added_constraints = connection.exec_driver_sql(
            "select count(*) from pg_constraint where conname = any(%s)",
            (list(_PARENT_UNIQUES | _TENANT_FKS),),
        ).scalar_one()
        added_indexes = connection.exec_driver_sql(
            "select count(*) from pg_class where relname = any(%s)",
            (list(_TENANT_INDEXES),),
        ).scalar_one()
        persisted_reference = connection.exec_driver_sql(
            f"select {column}::text from {table} where id = %s",
            (values[child_key],),
        ).scalar_one()

    assert added_constraints == 0
    assert added_indexes == 0
    assert persisted_reference == values[parent_key]


@pytest.mark.rls_integration
def test_indice_homonimo_incorreto_falha_fechado_e_reverte_catalogo(
    d1a_engine: Engine,
) -> None:
    _seed_valid_graph(d1a_engine)
    with d1a_engine.begin() as connection:
        connection.exec_driver_sql(
            "create index whatsapp_connections_instance_uidx "
            "on whatsapp_connections (igreja_id)"
        )

    with pytest.raises(PsycopgError, match="catalog conflict"):
        _apply_real_migration(d1a_engine)

    with d1a_engine.begin() as connection:
        added_constraints = connection.exec_driver_sql(
            "select count(*) from pg_constraint where conname = any(%s)",
            (list(_PARENT_UNIQUES | _TENANT_FKS),),
        ).scalar_one()
    assert added_constraints == 0


@pytest.mark.rls_integration
def test_constraint_homonima_incorreta_falha_fechado(
    d1a_engine: Engine,
) -> None:
    _seed_valid_graph(d1a_engine)
    with d1a_engine.begin() as connection:
        connection.exec_driver_sql(
            "alter table pessoas add constraint pessoas_igreja_id_id_key "
            "unique (id, igreja_id)"
        )

    with pytest.raises(PsycopgError, match="catalog conflict"):
        _apply_real_migration(d1a_engine)

    with d1a_engine.begin() as connection:
        tenant_constraints = connection.exec_driver_sql(
            "select count(*) from pg_constraint where conname = any(%s)",
            (list(_TENANT_FKS),),
        ).scalar_one()
        extra_parent_uniques = connection.exec_driver_sql(
            "select count(*) from pg_constraint "
            "where conname = any(%s) and conname <> 'pessoas_igreja_id_id_key'",
            (list(_PARENT_UNIQUES),),
        ).scalar_one()

    assert tenant_constraints == 0
    assert extra_parent_uniques == 0


@pytest.mark.rls_integration
def test_constraint_homonima_deferrable_falha_fechado(
    d1a_engine: Engine,
) -> None:
    _seed_valid_graph(d1a_engine)
    with d1a_engine.begin() as connection:
        connection.exec_driver_sql(
            "alter table pessoas add constraint pessoas_igreja_id_id_key "
            "unique (igreja_id, id) deferrable initially deferred"
        )

    with pytest.raises(PsycopgError, match="catalog conflict"):
        _apply_real_migration(d1a_engine)


@pytest.mark.rls_integration
def test_indice_homonimo_com_ordem_nao_padrao_falha_fechado(
    d1a_engine: Engine,
) -> None:
    _seed_valid_graph(d1a_engine)
    with d1a_engine.begin() as connection:
        connection.exec_driver_sql(
            "create unique index whatsapp_connections_instance_uidx "
            "on whatsapp_connections (instance desc) where instance is not null"
        )

    with pytest.raises(PsycopgError, match="catalog conflict"):
        _apply_real_migration(d1a_engine)


@pytest.mark.rls_integration
def test_preflight_instancia_duplicada_aborta_sem_expor_valor(
    d1a_engine: Engine,
) -> None:
    values = _seed_valid_graph(d1a_engine)
    raw_instance = "instancia-que-nao-pode-aparecer-no-erro"
    with d1a_engine.begin() as connection:
        connection.exec_driver_sql(
            "update whatsapp_connections set instance = %s",
            (raw_instance,),
        )

    with pytest.raises(PsycopgError) as raised:
        _apply_real_migration(d1a_engine)

    error = str(raised.value)
    assert "duplicate Evolution instances" in error
    assert "duplicate_groups=1" in error
    assert raw_instance not in error
    assert all(identifier not in error for identifier in values.values())

    with d1a_engine.begin() as connection:
        assert connection.exec_driver_sql(
            "select count(*) from pg_constraint where conname = any(%s)",
            (list(_PARENT_UNIQUES | _TENANT_FKS),),
        ).scalar_one() == 0


@pytest.mark.rls_integration
def test_lock_timeout_aborta_e_reverte_sem_catalogo_parcial(
    d1a_engine: Engine,
) -> None:
    _seed_valid_graph(d1a_engine)
    blocker = d1a_engine.raw_connection()
    try:
        cursor = blocker.cursor()
        try:
            cursor.execute(
                f"lock table {_SCHEMA}.whatsapp_connections "
                "in access exclusive mode"
            )
            started = time.monotonic()
            with pytest.raises(PsycopgError, match="lock timeout"):
                _apply_real_migration(d1a_engine)
            elapsed = time.monotonic() - started
            assert elapsed < 10
        finally:
            blocker.rollback()
            cursor.close()
    finally:
        blocker.close()

    with d1a_engine.begin() as connection:
        assert connection.exec_driver_sql(
            "select count(*) from pg_constraint where conname = any(%s)",
            (list(_PARENT_UNIQUES | _TENANT_FKS),),
        ).scalar_one() == 0
        assert connection.exec_driver_sql(
            "select count(*) from pg_class where relname = any(%s)",
            (list(_TENANT_INDEXES),),
        ).scalar_one() == 0


@pytest.mark.rls_integration
def test_deletes_historicos_preservam_cascade_e_set_null(
    d1a_engine: Engine,
) -> None:
    values = _seed_valid_graph(d1a_engine)
    _apply_real_migration(d1a_engine)
    shadow_user = str(uuid.uuid4())

    with d1a_engine.begin() as connection:
        connection.exec_driver_sql(
            "insert into app_users (id, igreja_id, pessoa_id) values (%s, %s, %s)",
            (shadow_user, values["igreja_a"], values["pessoa_a"]),
        )
        connection.exec_driver_sql(
            "update pessoas set lider_id = %s where id = %s",
            (values["leader_a"], values["pessoa_a"]),
        )
        connection.exec_driver_sql(
            "delete from app_users where id = %s",
            (values["user_a"],),
        )
        assert connection.exec_driver_sql(
            "select count(*) from user_roles where id = %s",
            (values["role_a"],),
        ).scalar_one() == 0
        person = connection.exec_driver_sql(
            "select igreja_id::text, arquivada_por from pessoas where id = %s",
            (values["pessoa_a"],),
        ).one()
        conversation = connection.exec_driver_sql(
            "select igreja_id::text, assumido_por from conversations where id = %s",
            (values["conversation_a"],),
        ).one()
        message_sender = connection.exec_driver_sql(
            "select enviado_por from messages where id = %s",
            (values["message_a"],),
        ).scalar_one()
        consent_actor = connection.exec_driver_sql(
            "select ator_id from consent_records where id = %s",
            (values["consent_a"],),
        ).scalar_one()

        assert person == (values["igreja_a"], None)
        assert conversation == (values["igreja_a"], None)
        assert message_sender is None
        assert consent_actor is None

        connection.exec_driver_sql(
            "delete from pessoas where id = %s",
            (values["leader_a"],),
        )
        led_person = connection.exec_driver_sql(
            "select igreja_id::text, lider_id from pessoas where id = %s",
            (values["pessoa_a"],),
        ).one()
        assert led_person == (values["igreja_a"], None)

        connection.exec_driver_sql(
            "delete from pessoas where id = %s",
            (values["pessoa_a"],),
        )
        app_user_person = connection.exec_driver_sql(
            "select igreja_id::text, pessoa_id from app_users where id = %s",
            (shadow_user,),
        ).one()
        conversation_person = connection.exec_driver_sql(
            "select igreja_id::text, pessoa_id from conversations where id = %s",
            (values["conversation_a"],),
        ).one()
        consent_count = connection.exec_driver_sql(
            "select count(*) from consent_records where id = %s",
            (values["consent_a"],),
        ).scalar_one()

        assert app_user_person == (values["igreja_a"], None)
        assert conversation_person == (values["igreja_a"], None)
        assert consent_count == 0

        connection.exec_driver_sql(
            "delete from conversations where id = %s",
            (values["conversation_a"],),
        )
        assert connection.exec_driver_sql(
            "select count(*) from messages where id = %s",
            (values["message_a"],),
        ).scalar_one() == 0


@pytest.mark.rls_integration
def test_corrida_de_instancia_evolution_tem_um_unico_vencedor(
    d1a_engine: Engine,
) -> None:
    values = _seed_valid_graph(d1a_engine)
    _apply_real_migration(d1a_engine)
    barrier = Barrier(2)

    def compete(connection_id: str) -> str:
        raw = d1a_engine.raw_connection()
        try:
            cursor = raw.cursor()
            try:
                barrier.wait(timeout=5)
                cursor.execute(
                    "update whatsapp_connections set instance = %s where id = %s",
                    ("instancia-concorrente", connection_id),
                )
                raw.commit()
                return "committed"
            except BaseException:
                raw.rollback()
                return "rejected"
            finally:
                cursor.close()
        finally:
            raw.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                compete,
                (values["connection_a"], values["connection_b"]),
            )
        )

    assert sorted(results) == ["committed", "rejected"]
