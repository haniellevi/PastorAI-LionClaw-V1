"""PG17 proof of the S2 JSON migration and read-only S2b HTTP projection.

Canonical facts are seeded by the fixture owner. This does not attest the S2b
migration, its write grants, or PUT /igreja/cadastro.
"""

from __future__ import annotations

import json
import pathlib
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import app.db.session as db_session
from app.db.session import get_db
from app.services.clerk import ClerkIdentity, get_clerk_client
from tests.conftest_rls import rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration

_TENANT_A = "3a3a3a3a-0000-0000-0000-00000000000a"
_TENANT_B = "3b3b3b3b-0000-0000-0000-00000000000b"
_USER_A = "3a3a3a3a-0000-0000-0000-0000000000a1"
_USER_B = "3b3b3b3b-0000-0000-0000-0000000000b1"
_CLERK_A = "s2-clerk-a"
_CLERK_B = "s2-clerk-b"
_CELL_A_PUBLIC = "3a3a3a3a-0000-0000-0000-0000000000c1"
_CELL_A_HIDDEN = "3a3a3a3a-0000-0000-0000-0000000000c2"
_CELL_A_INACTIVE = "3a3a3a3a-0000-0000-0000-0000000000c3"
_CELL_B_PUBLIC = "3b3b3b3b-0000-0000-0000-0000000000c1"
_MIGRATION = (
    pathlib.Path(__file__).resolve().parent.parent
    / "migrations"
    / "20260926_191500_agent_public_profile.sql"
)

_CatalogFingerprint = tuple[
    bool,
    bool,
    str,
    tuple[tuple[str, str, str, str], ...],
]


class _Clerk:
    def __init__(self, clerk_user_id: str) -> None:
        self._clerk_user_id = clerk_user_id

    def verify_session_token(self, _token: str) -> ClerkIdentity:
        return ClerkIdentity(
            clerk_user_id=self._clerk_user_id,
            claims={"sub": self._clerk_user_id},
        )


def _catalog_fingerprint(connection) -> _CatalogFingerprint:
    table = connection.execute(
        text(
            "select c.relrowsecurity, c.relforcerowsecurity, "
            "coalesce(c.relacl::text, '') "
            "from pg_class c where c.oid = 'public.agent_configs'::regclass"
        )
    ).one()
    policies = connection.execute(
        text(
            "select p.polname, p.polcmd::text, "
            "coalesce(pg_get_expr(p.polqual, p.polrelid), ''), "
            "coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '') "
            "from pg_policy p "
            "where p.polrelid = 'public.agent_configs'::regclass "
            "order by p.polname, p.polcmd"
        )
    ).all()
    return (
        bool(table[0]),
        bool(table[1]),
        str(table[2]),
        tuple(tuple(str(value) for value in policy) for policy in policies),
    )


def _prepare_pre_s2_baseline(engine: Engine) -> _CatalogFingerprint:
    """Create only the pre-S2 tenant baseline before applying the SQL artifact.

    Grants are a synthetic precondition of this disposable test. The migration
    itself is not allowed to create or widen them; the returned fingerprint is
    compared after the SQL is applied.
    """

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "do $$ begin "
            "if not exists (select 1 from pg_roles where rolname = 'authenticated') then "
            "create role authenticated nologin noinherit nobypassrls; "
            "end if; end $$;"
        )
        conn.exec_driver_sql("alter role authenticated nobypassrls noinherit nologin")
        conn.exec_driver_sql(
            "create table if not exists public.igrejas ("
            "id uuid primary key, nome text not null, status varchar not null default 'ativa', "
            "plano text, setup_fee_override numeric, dono_id uuid, logo_path text, "
            "endereco_institucional text, horarios_culto text, "
            "notification_outbox_cutover_at timestamptz not null default transaction_timestamp(), "
            "created_at timestamptz not null default now())"
        )
        conn.exec_driver_sql(
            "create table if not exists public.app_users ("
            "id uuid primary key default gen_random_uuid(), igreja_id uuid, clerk_user_id text unique, pessoa_id uuid, "
            "celula_pendente_id uuid, nome text, email text, status varchar, chat_nome text, "
            "created_at timestamptz default now(), password_changed_at timestamptz)"
        )
        for column_sql in (
            "add column if not exists status varchar default 'ativa'",
            "add column if not exists plano text",
            "add column if not exists setup_fee_override numeric",
            "add column if not exists dono_id uuid",
            "add column if not exists logo_path text",
            "add column if not exists endereco_institucional text",
            "add column if not exists horarios_culto text",
            "add column if not exists notification_outbox_cutover_at timestamptz not null default transaction_timestamp()",
            "add column if not exists created_at timestamptz default now()",
        ):
            conn.exec_driver_sql(f"alter table public.igrejas {column_sql}")
        conn.exec_driver_sql(
            "create table if not exists public.celulas ("
            "id uuid primary key, igreja_id uuid not null, nome text, "
            "dia_reuniao text, horario text, cobertura_espiritual text not null default 'Pastor', "
            "endereco text, ativo boolean not null default true, "
            "bairro text, divulgar_whatsapp boolean not null default false)"
        )
        # This projection fixture does not attest cell schema constraints.
        # Keep the shared disposable baseline compatible with the earlier
        # migration tests that seed only cell id/tenant.
        for column_sql in (
            "add column if not exists dia_reuniao text",
            "add column if not exists horario text",
            "add column if not exists cobertura_espiritual text default 'Pastor'",
            "add column if not exists endereco text",
            "add column if not exists ativo boolean default true",
            "add column if not exists bairro text",
            "add column if not exists divulgar_whatsapp boolean default false",
        ):
            conn.exec_driver_sql(f"alter table public.celulas {column_sql}")
        for column_sql in (
            "add column if not exists pessoa_id uuid",
            "add column if not exists celula_pendente_id uuid",
            "add column if not exists nome text",
            "add column if not exists email text",
            "add column if not exists status varchar",
            "add column if not exists chat_nome text",
            "add column if not exists created_at timestamptz default now()",
            "add column if not exists password_changed_at timestamptz",
        ):
            conn.exec_driver_sql(f"alter table public.app_users {column_sql}")
        conn.exec_driver_sql(
            "create table if not exists public.user_roles ("
            "id uuid primary key, igreja_id uuid not null, user_id uuid not null, papel varchar not null)"
        )
        conn.exec_driver_sql(
            "create table if not exists public.agent_configs ("
            "id uuid primary key, igreja_id uuid not null unique, nome text, tom text, "
            "comportamento text not null, publico_alvo text[], acessos text[], "
            "ativo boolean not null default true)"
        )
        conn.exec_driver_sql(
            "alter table public.agent_configs "
            "drop constraint if exists agent_configs_informacoes_publicas_objeto"
        )
        conn.exec_driver_sql(
            "alter table public.agent_configs drop column if exists informacoes_publicas"
        )
        conn.exec_driver_sql(
            "create or replace function public.current_igreja_id() "
            "returns uuid language sql stable security definer set search_path = public, pg_temp as $$ "
            "select au.igreja_id from public.app_users au "
            "where au.clerk_user_id = nullif(" 
            "coalesce(current_setting('request.jwt.claims', true)::jsonb ->> 'sub', "
            "current_setting('request.jwt.claim.sub', true)), '') limit 1 $$"
        )
        for table in ("app_users", "user_roles", "agent_configs", "celulas"):
            conn.exec_driver_sql(f"alter table public.{table} enable row level security")
            conn.exec_driver_sql(f"drop policy if exists tenant_isolation on public.{table}")
            conn.exec_driver_sql(
                f"create policy tenant_isolation on public.{table} for all "
                "using (igreja_id = current_igreja_id()) "
                "with check (igreja_id = current_igreja_id())"
            )
        conn.exec_driver_sql("alter table public.igrejas enable row level security")
        conn.exec_driver_sql("drop policy if exists igrejas_self_select on public.igrejas")
        conn.exec_driver_sql(
            "create policy igrejas_self_select on public.igrejas for select "
            "using (id = current_igreja_id())"
        )
        conn.exec_driver_sql("grant usage on schema public to authenticated")
        conn.exec_driver_sql("grant execute on function public.current_igreja_id() to authenticated")
        conn.exec_driver_sql("grant select on public.igrejas to authenticated")
        conn.exec_driver_sql("grant select on public.app_users to authenticated")
        conn.exec_driver_sql("grant select on public.user_roles to authenticated")
        conn.exec_driver_sql("grant select, update on public.agent_configs to authenticated")
        conn.exec_driver_sql("grant select on public.celulas to authenticated")

        conn.execute(
            text("delete from public.celulas where id in (:a, :h, :i, :b)"),
            {"a": _CELL_A_PUBLIC, "h": _CELL_A_HIDDEN,
             "i": _CELL_A_INACTIVE, "b": _CELL_B_PUBLIC},
        )
        conn.execute(
            text(
                "insert into public.igrejas (id, nome, status) values "
                "(:tenant_a, 'Igreja S2 A', 'ativa'), (:tenant_b, 'Igreja S2 B', 'ativa') "
                "on conflict (id) do update set nome = excluded.nome, status = excluded.status, "
                "endereco_institucional = null, horarios_culto = null"
            ),
            {"tenant_a": _TENANT_A, "tenant_b": _TENANT_B},
        )
        conn.execute(
            text(
                "insert into public.app_users (id, igreja_id, clerk_user_id, nome, email, status) values "
                "(:user_a, :tenant_a, :clerk_a, 'Admin S2 A', 'admin-a@example.test', 'ativo'), "
                "(:user_b, :tenant_b, :clerk_b, 'Admin S2 B', 'admin-b@example.test', 'ativo') "
                "on conflict (id) do update set igreja_id = excluded.igreja_id, "
                "clerk_user_id = excluded.clerk_user_id, nome = excluded.nome, "
                "email = excluded.email, status = excluded.status"
            ),
            {
                "user_a": _USER_A,
                "user_b": _USER_B,
                "tenant_a": _TENANT_A,
                "tenant_b": _TENANT_B,
                "clerk_a": _CLERK_A,
                "clerk_b": _CLERK_B,
            },
        )
        conn.execute(
            text(
                "insert into public.user_roles (id, igreja_id, user_id, papel) values "
                "(:role_a, :tenant_a, :user_a, 'admin'), "
                "(:role_b, :tenant_b, :user_b, 'admin') "
                "on conflict (id) do update set igreja_id = excluded.igreja_id, "
                "user_id = excluded.user_id, papel = excluded.papel"
            ),
            {
                "role_a": "3a3a3a3a-0000-0000-0000-0000000000a2",
                "role_b": "3b3b3b3b-0000-0000-0000-0000000000b2",
                "tenant_a": _TENANT_A,
                "tenant_b": _TENANT_B,
                "user_a": _USER_A,
                "user_b": _USER_B,
            },
        )
        conn.execute(
            text(
                "insert into public.agent_configs "
                "(id, igreja_id, comportamento, ativo) values "
                "(:config_a, :tenant_a, 'Tom A', true), "
                "(:config_b, :tenant_b, 'Tom B', false) "
                "on conflict (igreja_id) do update set comportamento = excluded.comportamento, "
                "ativo = excluded.ativo"
            ),
            {
                "config_a": "3a3a3a3a-0000-0000-0000-0000000000a3",
                "config_b": "3b3b3b3b-0000-0000-0000-0000000000b3",
                "tenant_a": _TENANT_A,
                "tenant_b": _TENANT_B,
            },
        )
        baseline = _catalog_fingerprint(conn)
        conn.execute(text(_MIGRATION.read_text(encoding="utf-8")))
        return baseline


@pytest.fixture
def public_profile_engine(
    rls_database_url: str,
) -> Iterator[tuple[Engine, _CatalogFingerprint]]:
    engine = create_engine(rls_database_url, future=True)
    baseline = _prepare_pre_s2_baseline(engine)
    try:
        yield engine, baseline
    finally:
        engine.dispose()


def _client(app, monkeypatch, engine: Engine, clerk_user_id: str) -> TestClient:
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionFactory", factory)
    app.dependency_overrides[get_clerk_client] = lambda: _Clerk(clerk_user_id)
    assert get_db not in app.dependency_overrides
    return TestClient(app)


def _direct_rls_result(
    engine: Engine,
    *,
    clerk_user_id: str,
    foreign_tenant_id: str,
) -> tuple[str, list[uuid.UUID], int]:
    """Exercise the real policy as a non-owner authenticated role."""

    with engine.begin() as connection:
        connection.execute(
            text("select set_config('request.jwt.claims', :claims, true)"),
            {"claims": json.dumps({"sub": clerk_user_id})},
        )
        connection.execute(text("set local role authenticated"))
        role = connection.execute(text("select current_user")).scalar_one()
        visible = connection.execute(
            text("select igreja_id from public.agent_configs order by igreja_id")
        ).scalars().all()
        foreign_update_count = connection.execute(
            text(
                "update public.agent_configs "
                "set informacoes_publicas = informacoes_publicas "
                "where igreja_id = :foreign_tenant_id"
            ),
            {"foreign_tenant_id": foreign_tenant_id},
        ).rowcount
    return str(role), visible, foreign_update_count


def _direct_public_visibility(
    engine: Engine, *, clerk_user_id: str
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Canonical church and cell reads remain scoped under authenticated RLS."""

    with engine.begin() as connection:
        connection.execute(
            text("select set_config('request.jwt.claims', :claims, true)"),
            {"claims": json.dumps({"sub": clerk_user_id})},
        )
        connection.execute(text("set local role authenticated"))
        churches = connection.execute(
            text("select id from public.igrejas order by id")
        ).scalars().all()
        cells = connection.execute(
            text("select id from public.celulas order by id")
        ).scalars().all()
    return churches, cells


def test_public_profile_migration_preserves_rls_and_real_routes_isolate_tenants(
    app,
    monkeypatch,
    public_profile_engine: tuple[Engine, _CatalogFingerprint],
) -> None:
    engine, baseline = public_profile_engine
    with engine.connect() as owner:
        post_migration = _catalog_fingerprint(owner)
        authenticated_role = owner.execute(
            text(
                "select rolbypassrls, rolsuper from pg_roles "
                "where rolname = 'authenticated'"
            )
        ).one()
        defaults = owner.execute(
            text(
                "select informacoes_publicas from public.agent_configs "
                "where igreja_id = :tenant_a"
            ),
            {"tenant_a": _TENANT_A},
        ).scalar_one()
    assert post_migration == baseline
    assert baseline[:2] == (True, False)
    assert "authenticated=" in baseline[2]
    tenant_policy = next(
        policy
        for policy in baseline[3]
        if policy[0] == "tenant_isolation" and policy[1] == "*"
    )
    assert all("igreja_id = current_igreja_id()" in expression for expression in tenant_policy[2:])
    assert authenticated_role == (False, False)
    assert defaults == {}

    role_a, visible_a, update_b_from_a = _direct_rls_result(
        engine,
        clerk_user_id=_CLERK_A,
        foreign_tenant_id=_TENANT_B,
    )
    role_b, visible_b, update_a_from_b = _direct_rls_result(
        engine,
        clerk_user_id=_CLERK_B,
        foreign_tenant_id=_TENANT_A,
    )
    assert (role_a, visible_a, update_b_from_a) == (
        "authenticated",
        [uuid.UUID(_TENANT_A)],
        0,
    )
    assert (role_b, visible_b, update_a_from_b) == (
        "authenticated",
        [uuid.UUID(_TENANT_B)],
        0,
    )

    with engine.connect() as owner:
        transaction = owner.begin()
        try:
            with pytest.raises(IntegrityError):
                owner.execute(
                    text(
                        "update public.agent_configs "
                        "set informacoes_publicas = '[]'::jsonb "
                        "where igreja_id = :tenant_a"
                    ),
                    {"tenant_a": _TENANT_A},
                )
        finally:
            transaction.rollback()

    legacy_fact = {"endereco_igreja": "LEGADO-NAO-PUBLICAR"}
    with engine.begin() as owner:
        owner.execute(
            text(
                "update public.agent_configs set informacoes_publicas = cast(:info as jsonb) "
                "where igreja_id = :tenant_a"
            ),
            {"info": json.dumps(legacy_fact), "tenant_a": _TENANT_A},
        )

    headers = {"Authorization": "Bearer synthetic"}
    client_a = _client(app, monkeypatch, engine, _CLERK_A)
    initial_a = client_a.get("/agent/public-profile", headers=headers)
    assert initial_a.status_code == 200
    assert initial_a.json() == {
        "configured": True,
        "informacoesPublicas": {
            "enderecoIgreja": None,
            "horariosCulto": None,
            "celulas": [],
        },
    }
    assert "LEGADO-NAO-PUBLICAR" not in initial_a.text
    legacy_put = client_a.put(
        "/agent/public-profile",
        headers=headers,
        json={"igrejaId": _TENANT_B, "segredo": "NOME-SINTETICO-90000-0000"},
    )
    assert legacy_put.status_code == 409
    assert legacy_put.json()["detail"]["code"] == "public_profile_read_only"
    assert "NOME-SINTETICO-90000-0000" not in legacy_put.text

    with engine.begin() as owner:
        owner.execute(
            text(
                "update public.igrejas set endereco_institucional = :address, "
                "horarios_culto = :hours where id = :tenant_a"
            ),
            {
                "address": "Rua Institucional A, 100",
                "hours": "Domingo, 19:00",
                "tenant_a": _TENANT_A,
            },
        )
        owner.execute(
            text(
                "insert into public.celulas "
                "(id, igreja_id, nome, dia_reuniao, horario, cobertura_espiritual, "
                "endereco, ativo, bairro, divulgar_whatsapp) values "
                "(:a_public, :tenant_a, 'Esperança A', 'Terça-feira', '19:00', 'Pastor', "
                "'RUA-RESIDENCIAL-PRIVADA', true, 'Centro', true), "
                "(:a_hidden, :tenant_a, 'Oculta A', 'Quarta-feira', '20:00', 'Pastor', "
                "'RUA-OCULTA', true, 'Sul', false), "
                "(:a_inactive, :tenant_a, 'Inativa A', 'Quinta-feira', '20:00', 'Pastor', "
                "'RUA-INATIVA', false, 'Norte', true), "
                "(:b_public, :tenant_b, 'Esperança B', 'Sábado', '18:00', 'Pastor', "
                "'RUA-B-PRIVADA', true, 'Centro', true) "
                "on conflict (id) do update set igreja_id = excluded.igreja_id, "
                "nome = excluded.nome, dia_reuniao = excluded.dia_reuniao, "
                "horario = excluded.horario, cobertura_espiritual = excluded.cobertura_espiritual, "
                "endereco = excluded.endereco, ativo = excluded.ativo, "
                "bairro = excluded.bairro, divulgar_whatsapp = excluded.divulgar_whatsapp"
            ),
            {
                "a_public": _CELL_A_PUBLIC,
                "a_hidden": _CELL_A_HIDDEN,
                "a_inactive": _CELL_A_INACTIVE,
                "b_public": _CELL_B_PUBLIC,
                "tenant_a": _TENANT_A,
                "tenant_b": _TENANT_B,
            },
        )

    get_a = client_a.get("/agent/public-profile", headers=headers)
    assert get_a.status_code == 200
    assert get_a.json()["informacoesPublicas"] == {
        "enderecoIgreja": "Rua Institucional A, 100",
        "horariosCulto": "Domingo, 19:00",
        "celulas": [
            {"bairro": "Centro", "nome": "Esperança A", "encontro": "Terça-feira, 19:00"}
        ],
    }
    assert "RUA-RESIDENCIAL-PRIVADA" not in get_a.text
    assert "Oculta A" not in get_a.text
    assert "Inativa A" not in get_a.text
    assert "Esperança B" not in get_a.text
    assert "LEGADO-NAO-PUBLICAR" not in get_a.text

    app.dependency_overrides.clear()
    client_b = _client(app, monkeypatch, engine, _CLERK_B)
    get_b = client_b.get("/agent/public-profile", headers=headers)
    assert get_b.status_code == 200
    assert get_b.json()["informacoesPublicas"] == {
        "enderecoIgreja": None,
        "horariosCulto": None,
        "celulas": [
            {"bairro": "Centro", "nome": "Esperança B", "encontro": "Sábado, 18:00"}
        ],
    }
    assert "Rua Institucional A" not in get_b.text
    with engine.begin() as owner:
        owner.execute(
            text(
                "update public.igrejas set endereco_institucional = :address, "
                "horarios_culto = :hours where id = :tenant_b"
            ),
            {
                "address": "Rua Institucional B, 200",
                "hours": "Sábado, 18:00",
                "tenant_b": _TENANT_B,
            },
        )
    get_b_after = client_b.get("/agent/public-profile", headers=headers)
    assert get_b_after.status_code == 200
    assert get_b_after.json()["informacoesPublicas"] == {
        "enderecoIgreja": "Rua Institucional B, 200",
        "horariosCulto": "Sábado, 18:00",
        "celulas": [
            {"bairro": "Centro", "nome": "Esperança B", "encontro": "Sábado, 18:00"}
        ],
    }
    assert "Rua Institucional A" not in get_b_after.text

    with engine.connect() as owner:
        saved = owner.execute(
            text(
                "select igreja_id, informacoes_publicas, ativo from public.agent_configs "
                "where igreja_id in (:tenant_a, :tenant_b) order by igreja_id"
            ),
            {"tenant_a": _TENANT_A, "tenant_b": _TENANT_B},
        ).all()
        canonical = owner.execute(
            text(
                "select id, endereco_institucional, horarios_culto from public.igrejas "
                "where id in (:tenant_a, :tenant_b) order by id"
            ),
            {"tenant_a": _TENANT_A, "tenant_b": _TENANT_B},
        ).all()
    assert saved == [
        (uuid.UUID(_TENANT_A), legacy_fact, True),
        (uuid.UUID(_TENANT_B), {}, False),
    ]
    assert canonical == [
        (uuid.UUID(_TENANT_A), "Rua Institucional A, 100", "Domingo, 19:00"),
        (uuid.UUID(_TENANT_B), "Rua Institucional B, 200", "Sábado, 18:00"),
    ]
    assert _direct_public_visibility(engine, clerk_user_id=_CLERK_A) == (
        [uuid.UUID(_TENANT_A)],
        [uuid.UUID(_CELL_A_PUBLIC), uuid.UUID(_CELL_A_HIDDEN), uuid.UUID(_CELL_A_INACTIVE)],
    )
    assert _direct_public_visibility(engine, clerk_user_id=_CLERK_B) == (
        [uuid.UUID(_TENANT_B)],
        [uuid.UUID(_CELL_B_PUBLIC)],
    )
