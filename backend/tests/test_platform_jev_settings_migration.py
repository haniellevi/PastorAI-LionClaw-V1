"""Executa a migration da configuração do Jev em PostgreSQL descartável."""

import datetime as dt
from decimal import Decimal
import json
from pathlib import Path
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg2
import pytest
from psycopg2.errors import CheckViolation, InsufficientPrivilege, RaiseException
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Igreja, PlatformAuditLog, PlatformJevSettings
from app.db.session import get_db
from app.deps import PlatformAdminUser, get_platform_admin
from app.routers import platform_jev
from app.services import crypto
from app.services import semantic_triage as jev_triage
from app.services.semantic_triage import TriageSettings
from tests.conftest_rls import rls_database_url  # noqa: F401


MIGRATION = Path(__file__).parents[1] / "migrations" / (
    "20260926_120446_platform_jev_settings.sql"
)

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def scratch_schema(rls_database_url):
    engine = create_engine(rls_database_url)
    schema = "jev_settings_test_" + uuid.uuid4().hex
    connection = engine.raw_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(f"create schema {schema}")
        cursor.execute(f"set local search_path = {schema}, public")
        cursor.execute(f"""
            do $$ begin
              if not exists (select 1 from pg_roles where rolname='authenticated') then
                create role authenticated nologin nobypassrls;
              end if;
              if not exists (select 1 from pg_roles where rolname='anon') then
                create role anon nologin nobypassrls;
              end if;
            end $$;
            grant usage on schema {schema} to authenticated, anon;
            alter default privileges in schema {schema}
              grant select, insert, update, delete on tables to authenticated, anon;
        """)
        yield cursor, schema, MIGRATION.read_text().replace("public.", schema + ".")
    finally:
        connection.rollback()
        cursor.close()
        connection.close()
        engine.dispose()


@pytest.fixture
def migrated_db(scratch_schema):
    cursor, schema, sql = scratch_schema
    cursor.execute(sql)
    cursor.execute(sql)
    return cursor, schema


def _violates(cursor, statement: str, params=()) -> type[Exception] | None:
    cursor.execute("savepoint tentativa")
    try:
        cursor.execute(statement, params)
    except psycopg2.Error as exc:
        cursor.execute("rollback to savepoint tentativa")
        return type(exc)
    cursor.execute("release savepoint tentativa")
    return None


def test_tabela_fica_fechada_para_anon_e_authenticated(migrated_db):
    cursor, schema = migrated_db
    tabela = f"{schema}.platform_jev_settings"
    cursor.execute(
        "select relrowsecurity from pg_class where oid = %s::regclass", (tabela,)
    )
    assert cursor.fetchone() == (True,)
    cursor.execute(
        "select polname, polpermissive, polcmd from pg_policy where polrelid = %s::regclass",
        (tabela,),
    )
    assert cursor.fetchall() == [("service_role_bypass_only", False, "*")]
    cursor.execute("select has_table_privilege(current_user, %s, 'SELECT')", (tabela,))
    assert cursor.fetchone() == (True,)
    for role in ("anon", "authenticated"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            cursor.execute(
                "select has_table_privilege(%s, %s, %s)", (role, tabela, privilege)
            )
            assert cursor.fetchone() == (False,), (role, privilege)


def test_authenticated_nao_le_a_chave_cifrada(migrated_db):
    cursor, _ = migrated_db
    cursor.execute(
        "insert into platform_jev_settings(id, api_key_encrypted) values (1, 'cifrada')"
    )
    cursor.execute("set local role authenticated")
    with pytest.raises(InsufficientPrivilege):
        cursor.execute("select api_key_encrypted from platform_jev_settings")


def test_linha_unica_e_travas_de_valor(migrated_db):
    cursor, _ = migrated_db
    igreja = str(uuid.uuid4())

    assert _violates(cursor, "insert into platform_jev_settings(id) values (2)") is CheckViolation
    assert (
        _violates(
            cursor,
            "insert into platform_jev_settings(igreja_ids) values (array[%s]::uuid[])",
            (igreja,),
        )
        is CheckViolation
    )
    assert (
        _violates(cursor, "insert into platform_jev_settings(modelo) values ('gpt-5.6-luna')")
        is CheckViolation
    )
    assert (
        _violates(cursor, "insert into platform_jev_settings(timeout_seconds) values (11)")
        is CheckViolation
    )
    assert (
        _violates(
            cursor,
            "insert into platform_jev_settings(modelo, timeout_seconds, igreja_ids,"
            " dpa_assinado_em) values ('jev-1.13', 1.5, array[%s]::uuid[], date '2026-09-20')",
            (igreja,),
        )
        is None
    )
    cursor.execute("select id, modelo, cardinality(igreja_ids) from platform_jev_settings")
    assert cursor.fetchall() == [(1, "jev-1.13", 1)]


def test_tabela_preexistente_com_outro_formato_aborta(scratch_schema):
    # `create table if not exists` pularia a tabela; a pós-condição não deixa.
    cursor, schema, sql = scratch_schema
    cursor.execute(f"create table {schema}.platform_jev_settings (id smallint primary key)")
    with pytest.raises(RaiseException, match="CHECK ausente"):
        cursor.execute(sql)


def test_defaults_da_migration(migrated_db):
    cursor, _ = migrated_db
    cursor.execute("insert into platform_jev_settings default values")
    cursor.execute(
        "select id, api_key_encrypted, api_key_updated_at, modelo, timeout_seconds,"
        " igreja_ids, dpa_assinado_em, updated_at, updated_by"
        " from platform_jev_settings"
    )
    row = cursor.fetchone()
    assert row is not None
    (
        row_id,
        api_key_encrypted,
        api_key_updated_at,
        modelo,
        timeout_seconds,
        igreja_ids,
        dpa_assinado_em,
        updated_at,
        updated_by,
    ) = row
    assert row_id == 1
    assert api_key_encrypted is None
    assert api_key_updated_at is None
    assert modelo is None
    assert timeout_seconds is None
    assert igreja_ids == []
    assert dpa_assinado_em is None
    assert updated_at is not None
    assert updated_by is None


def test_limites_timeout_modelo_e_update_dpa(migrated_db):
    cursor, _ = migrated_db
    igreja = str(uuid.uuid4())

    for timeout_invalido in (0, -0.1, 10.1):
        assert (
            _violates(
                cursor,
                "insert into platform_jev_settings(timeout_seconds) values (%s)",
                (timeout_invalido,),
            )
            is CheckViolation
        )

    for modelo_invalido in ("jev-", "jev-" + "a" * 41):
        assert (
            _violates(
                cursor,
                "insert into platform_jev_settings(modelo) values (%s)",
                (modelo_invalido,),
            )
            is CheckViolation
        )

    assert (
        _violates(
            cursor,
            "insert into platform_jev_settings(modelo, timeout_seconds, igreja_ids,"
            " dpa_assinado_em) values (%s, %s, array[%s]::uuid[], date '2026-09-20')",
            ("jev-" + "a" * 40, 0.1, igreja),
        )
        is None
    )
    assert (
        _violates(
            cursor,
            "update platform_jev_settings set timeout_seconds = %s, modelo = null where id = 1",
            (10.0,),
        )
        is None
    )
    assert (
        _violates(
            cursor,
            "update platform_jev_settings set timeout_seconds = null where id = 1",
        )
        is None
    )
    assert (
        _violates(
            cursor,
            "update platform_jev_settings set dpa_assinado_em = null where id = 1",
        )
        is CheckViolation
    )
    assert (
        _violates(
            cursor,
            "update platform_jev_settings set igreja_ids = '{}', dpa_assinado_em = null where id = 1",
        )
        is None
    )
    assert (
        _violates(
            cursor,
            "update platform_jev_settings set dpa_assinado_em = null where id = 1",
        )
        is None
    )


@pytest.fixture
def migrated_public_session_factory(rls_database_url, monkeypatch):
    """Cria banco descartável com schema `public` limpo e migration intacta."""
    db_name = f"jev_func_{uuid.uuid4().hex}"
    admin_engine = create_engine(rls_database_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.exec_driver_sql(f'create database "{db_name}"')

    db_url = make_url(rls_database_url).set(database=db_name)
    engine = create_engine(db_url)
    session_local = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    monkeypatch.setattr(crypto.get_settings(), "secrets_encryption_key", "k" * 32)
    crypto._get_fernet.cache_clear()  # noqa: SLF001
    for var in ("TYPESAFE_API_KEY", "JEV_SHADOW_TRIAGE_IGREJA_IDS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(platform_jev, "external_sends_allowed", lambda: False)

    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("create table if not exists public.app_users (id uuid primary key)")
            Igreja.__table__.create(bind=conn)
            PlatformAuditLog.__table__.create(bind=conn)
        raw_conn = engine.raw_connection()
        try:
            with raw_conn.cursor() as cur:
                cur.execute(MIGRATION.read_text(encoding="utf-8"))
            raw_conn.commit()
        finally:
            raw_conn.close()
        yield session_local
    finally:
        crypto._get_fernet.cache_clear()  # noqa: SLF001
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.exec_driver_sql(f'drop database if exists "{db_name}" with (force)')
        admin_engine.dispose()


def _make_jev_client(session_factory: sessionmaker[Session], admin_uuid: uuid.UUID) -> TestClient:
    app = FastAPI()
    app.include_router(platform_jev.router)

    def _override_get_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_platform_admin] = lambda: PlatformAdminUser(
        app_user_id=str(admin_uuid),
        clerk_user_id="clerk-master-ficticio",
        email="master@example.test",
        nome="Master Fictício",
    )
    return TestClient(app)


def test_ciclo_funcional_servico_e_router_pg17(migrated_public_session_factory, monkeypatch):
    session_factory = migrated_public_session_factory
    admin_uuid = uuid.uuid4()
    igreja_a = uuid.uuid4()
    igreja_b = uuid.uuid4()
    chave_ficticia = "tsk-ficticia-validacao-m4"

    base_settings = TriageSettings(
        _env_file=None,  # type: ignore[call-arg]
        typesafe_api_key="tsk-env-ficticia",
        typesafe_model="jev-latest",
        typesafe_timeout_seconds=2.0,
        jev_shadow_triage_igreja_ids=str(igreja_a),
    )
    monkeypatch.setattr(jev_triage, "get_triage_settings", lambda: base_settings)

    with session_factory() as db:
        assert jev_triage.console_table_exists(db) is True
        assert jev_triage.load_console_settings(db) is None
        antes = jev_triage.effective_settings(db)
        assert antes.chave_origem == "ambiente"
        assert antes.settings.typesafe_timeout_seconds == 2.0

        db.add_all(
            [
                Igreja(id=igreja_a, nome="Igreja Fictícia Alpha"),
                Igreja(id=igreja_b, nome="Igreja Fictícia Beta"),
            ]
        )
        db.commit()

    client = _make_jev_client(session_factory, admin_uuid)
    resp = client.put(
        "/admin/jev/config",
        json={
            "apiKey": chave_ficticia,
            "modelo": "JEV-1.13",
            "timeoutSegundos": 2.5,
            "dpaAssinadoEm": "2026-09-20",
            "igrejaIds": [str(igreja_a), str(igreja_b)],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert chave_ficticia not in json.dumps(body)
    assert body["configurado"] is True
    assert body["chaveOrigem"] == "console"
    assert body["modelo"] == "jev-1.13"
    assert body["timeoutSegundos"] == 2.5
    assert body["dpaAssinadoEm"] == "2026-09-20"
    assert sorted(body["igrejas"], key=lambda i: i["id"]) == sorted(
        [
            {"id": str(igreja_a), "nome": "Igreja Fictícia Alpha"},
            {"id": str(igreja_b), "nome": "Igreja Fictícia Beta"},
        ],
        key=lambda i: i["id"],
    )

    with session_factory() as db:
        row = db.execute(select(PlatformJevSettings).where(PlatformJevSettings.id == 1)).scalar_one()
        assert row.timeout_seconds == Decimal("2.5")
        assert set(row.igreja_ids) == {igreja_a, igreja_b}
        assert row.updated_by == admin_uuid
        assert row.api_key_encrypted is not None
        assert crypto.decrypt_secret(row.api_key_encrypted) == chave_ficticia

        efetiva = jev_triage.effective_settings(db)
        assert efetiva.chave_origem == "console"
        assert efetiva.settings.typesafe_api_key == chave_ficticia
        assert isinstance(efetiva.settings.typesafe_timeout_seconds, float)
        assert efetiva.settings.typesafe_timeout_seconds == 2.5
        assert efetiva.dpa_assinado_em == dt.date(2026, 9, 20)
        assert set(efetiva.settings.jev_shadow_triage_igreja_ids.split(",")) == {
            str(igreja_a),
            str(igreja_b),
        }

    for limite in (0.1, 10.0):
        borda = client.put(
            "/admin/jev/config",
            json={
                "timeoutSegundos": limite,
                "dpaAssinadoEm": "2026-09-20",
                "igrejaIds": [str(igreja_a), str(igreja_b)],
            },
        )
        assert borda.status_code == 200
        assert borda.json()["timeoutSegundos"] == limite
        assert len(borda.json()["igrejas"]) == 2

    limpo = client.put("/admin/jev/config", json={"igrejaIds": [], "dpaAssinadoEm": None})
    assert limpo.status_code == 200
    assert limpo.json()["igrejas"] == []
    with session_factory() as db:
        assert jev_triage.effective_settings(db).settings.jev_shadow_triage_igreja_ids == ""


def test_igreja_excluida_em_igreja_ids_nao_quebra_leitura_nem_atualizacao_pg17(
    migrated_public_session_factory, monkeypatch
):
    session_factory = migrated_public_session_factory
    admin_uuid = uuid.uuid4()
    igreja_a = uuid.uuid4()
    igreja_b = uuid.uuid4()

    monkeypatch.setattr(
        jev_triage,
        "get_triage_settings",
        lambda: TriageSettings(_env_file=None),  # type: ignore[call-arg]
    )

    with session_factory() as db:
        db.add_all(
            [
                Igreja(id=igreja_a, nome="Igreja Mantida"),
                Igreja(id=igreja_b, nome="Igreja Removida"),
            ]
        )
        db.commit()

    client = _make_jev_client(session_factory, admin_uuid)
    put_ok = client.put(
        "/admin/jev/config",
        json={
            "dpaAssinadoEm": "2026-09-20",
            "igrejaIds": [str(igreja_a), str(igreja_b)],
        },
    )
    assert put_ok.status_code == 200

    with session_factory() as db:
        igreja_removida = db.execute(select(Igreja).where(Igreja.id == igreja_b)).scalar_one()
        db.delete(igreja_removida)
        db.commit()

    get_resp = client.get("/admin/jev")
    assert get_resp.status_code == 200
    por_id = {item["id"]: item["nome"] for item in get_resp.json()["igrejas"]}
    assert por_id == {str(igreja_a): "Igreja Mantida", str(igreja_b): None}

    with session_factory() as db:
        efetiva = jev_triage.effective_settings(db)
        assert set(efetiva.settings.jev_shadow_triage_igreja_ids.split(",")) == {
            str(igreja_a),
            str(igreja_b),
        }

    atualizado = client.put(
        "/admin/jev/config",
        json={
            "dpaAssinadoEm": "2026-09-20",
            "igrejaIds": [str(igreja_a)],
        },
    )
    assert atualizado.status_code == 200
    assert atualizado.json()["igrejas"] == [{"id": str(igreja_a), "nome": "Igreja Mantida"}]
