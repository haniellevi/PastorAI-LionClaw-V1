"""PostgreSQL 17 proof for the additive S2b canonical-public-data migration."""

from __future__ import annotations

import pathlib
import threading
import time
import uuid
from collections.abc import Iterator

import pytest
from psycopg2 import Error as PsycopgError
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Conversation
from app.services.secretaria_offer import resolve_secretaria_offer_inbound
from tests.conftest_rls import rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration

_SCHEMA = "church_cell_public_s2b_pg17"
_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260927_120000_church_cell_public_data.sql"
)
_TENANT_A = uuid.UUID("c2b00000-0000-0000-0000-0000000000a1")
_TENANT_B = uuid.UUID("c2b00000-0000-0000-0000-0000000000b1")
_TENANT_C = uuid.UUID("c2b00000-0000-0000-0000-0000000000c1")
_USER_A = "s2b-pg-auth-a"
_USER_B = "s2b-pg-auth-b"


def _migration_for_schema() -> str:
    sql = _MIGRATION.read_text(encoding="utf-8")
    return sql.replace("public.", f"{_SCHEMA}.").replace(
        "set search_path = public, pg_temp",
        f"set search_path = {_SCHEMA}, pg_temp",
    )


def _apply_migration(engine: Engine) -> None:
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cursor:
            cursor.execute(_migration_for_schema())
        raw.commit()
    except BaseException:
        raw.rollback()
        raise
    finally:
        raw.close()


def _catalog_fingerprint(connection) -> tuple[
    tuple[tuple[str, bool, bool, str], ...],
    tuple[tuple[str, str, str, str, str], ...],
    tuple[tuple[str, str, str], ...],
]:
    tables = connection.execute(
        text(
            "select c.relname, c.relrowsecurity, c.relforcerowsecurity, "
            "coalesce(c.relacl::text, '') "
            "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = :schema and c.relname in "
            "('igrejas', 'celulas', 'conversations', 'messages') order by c.relname"
        ),
        {"schema": _SCHEMA},
    ).all()
    policies = connection.execute(
        text(
            "select c.relname, p.polname, p.polcmd::text, "
            "coalesce(pg_get_expr(p.polqual, p.polrelid), ''), "
            "coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '') "
            "from pg_policy p join pg_class c on c.oid = p.polrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = :schema and c.relname in "
            "('igrejas', 'celulas', 'conversations', 'messages') "
            "order by c.relname, p.polname, p.polcmd"
        ),
        {"schema": _SCHEMA},
    ).all()
    old_column_acls = connection.execute(
        text(
            "select c.relname, a.attname, coalesce(a.attacl::text, '') "
            "from pg_attribute a join pg_class c on c.oid = a.attrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = :schema and c.relname in "
            "('igrejas', 'celulas', 'conversations', 'messages') "
            "and a.attnum > 0 and not a.attisdropped "
            "and a.attname not in ("
            "'endereco_institucional', 'horarios_culto', 'bairro', "
            "'divulgar_whatsapp', 'secretaria_oferta_estado', "
            "'secretaria_oferta_message_id', 'secretaria_oferta_expira_em', "
            "'secretaria_oferta_resposta_message_id', 'public_info_reply') "
            "order by c.relname, a.attname"
        ),
        {"schema": _SCHEMA},
    ).all()
    return (
        tuple((str(name), bool(rls), bool(force), str(acl)) for name, rls, force, acl in tables),
        tuple(tuple(str(value) for value in row) for row in policies),
        tuple(tuple(str(value) for value in row) for row in old_column_acls),
    )


def _prepare_pre_s2b_baseline(engine: Engine) -> tuple[
    tuple[tuple[str, bool, bool, str], ...],
    tuple[tuple[str, str, str, str, str], ...],
    tuple[tuple[str, str, str], ...],
]:
    """Create a pre-S2b tenant schema; migration owns every new field."""

    with engine.begin() as connection:
        connection.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade")
        connection.exec_driver_sql(f"create schema {_SCHEMA}")
        connection.exec_driver_sql(
            "do $$ begin "
            "if not exists (select 1 from pg_roles where rolname = 'authenticated') then "
            "create role authenticated nologin noinherit nobypassrls; "
            "end if; end $$"
        )
        connection.exec_driver_sql("alter role authenticated nologin noinherit nobypassrls")
        connection.exec_driver_sql(
            f"create table {_SCHEMA}.igrejas ("
            "id uuid primary key, nome text not null, status text not null default 'ativa', "
            "plano text, setup_fee_override numeric, dono_id uuid, logo_path text, "
            "created_at timestamptz not null default now())"
        )
        connection.exec_driver_sql(
            f"create table {_SCHEMA}.app_users ("
            "id uuid primary key, igreja_id uuid not null, clerk_user_id text unique not null)"
        )
        connection.exec_driver_sql(
            f"create function {_SCHEMA}.current_igreja_id() returns uuid "
            f"language sql stable security definer set search_path = {_SCHEMA}, pg_temp as $$ "
            f"select igreja_id from {_SCHEMA}.app_users "
            "where clerk_user_id = nullif(current_setting('app.clerk_user_id', true), '') "
            "limit 1 $$"
        )
        connection.exec_driver_sql(
            f"create table {_SCHEMA}.celulas ("
            f"id uuid primary key, igreja_id uuid not null references {_SCHEMA}.igrejas(id) on delete cascade, "
            "nome text not null, dia_reuniao text, horario text, "
            "cobertura_espiritual text not null default 'Pastor', endereco text, "
            "ativo boolean not null default true)"
        )
        connection.exec_driver_sql(
            f"create table {_SCHEMA}.conversations ("
            f"id uuid primary key, igreja_id uuid not null references {_SCHEMA}.igrejas(id) on delete cascade, "
            "pessoa_id uuid, telefone text not null default '5500000000000', estado text, "
            "assumido_por uuid, assumido_em timestamptz, ultima_mensagem text, "
            "nao_lidas integer not null default 0, espera_desde timestamptz, "
            "numero_oficial boolean not null default true, updated_at timestamptz not null default now(), "
            "unique (igreja_id, id))"
        )
        connection.exec_driver_sql(
            f"create table {_SCHEMA}.messages ("
            f"id uuid primary key, igreja_id uuid not null references {_SCHEMA}.igrejas(id) on delete cascade, "
            f"conversation_id uuid not null, direcao text not null, autor text not null, "
            "agent_reply_state text, texto text, provider_message_id text, tipo text not null default 'texto', "
            "media_path text, enviado_por uuid, created_at timestamptz not null default now(), "
            f"foreign key (igreja_id, conversation_id) references {_SCHEMA}.conversations(igreja_id, id) on delete cascade)"
        )
        connection.exec_driver_sql(
            f"create table {_SCHEMA}.agent_configs ("
            f"id uuid primary key, igreja_id uuid not null unique references {_SCHEMA}.igrejas(id) on delete cascade, "
            "informacoes_publicas jsonb not null default '{}'::jsonb, "
            "constraint agent_configs_informacoes_publicas_objeto "
            "check (jsonb_typeof(informacoes_publicas) = 'object'))"
        )

        connection.exec_driver_sql(f"alter table {_SCHEMA}.igrejas enable row level security")
        connection.exec_driver_sql(f"alter table {_SCHEMA}.celulas enable row level security")
        connection.exec_driver_sql(f"alter table {_SCHEMA}.conversations enable row level security")
        connection.exec_driver_sql(f"alter table {_SCHEMA}.messages enable row level security")
        connection.exec_driver_sql(
            f"create policy igrejas_self_select on {_SCHEMA}.igrejas for select "
            f"using (id = {_SCHEMA}.current_igreja_id())"
        )
        connection.exec_driver_sql(
            f"create policy igrejas_self_update on {_SCHEMA}.igrejas for update "
            f"using (id = {_SCHEMA}.current_igreja_id()) "
            f"with check (id = {_SCHEMA}.current_igreja_id())"
        )
        for table in ("celulas", "conversations", "messages"):
            connection.exec_driver_sql(
                f"create policy tenant_isolation on {_SCHEMA}.{table} for all "
                f"using (igreja_id = {_SCHEMA}.current_igreja_id()) "
                f"with check (igreja_id = {_SCHEMA}.current_igreja_id())"
            )
        connection.exec_driver_sql(f"grant usage on schema {_SCHEMA} to authenticated")
        connection.exec_driver_sql(
            f"grant execute on function {_SCHEMA}.current_igreja_id() to authenticated"
        )
        connection.exec_driver_sql(f"grant select on {_SCHEMA}.igrejas to authenticated")
        connection.exec_driver_sql(
            f"grant select, update, delete on {_SCHEMA}.conversations to authenticated"
        )
        connection.exec_driver_sql(
            f"grant select, update, delete on {_SCHEMA}.messages to authenticated"
        )
        connection.exec_driver_sql(f"grant select on {_SCHEMA}.celulas to authenticated")

        connection.execute(
            text(
                f"insert into {_SCHEMA}.igrejas (id, nome, logo_path) values "
                "(:a, 'Igreja sintética A', 'logo-a'), "
                "(:b, 'Igreja sintética B', 'logo-b'), "
                "(:c, 'Igreja sintética C', 'logo-c')"
            ),
            {"a": _TENANT_A, "b": _TENANT_B, "c": _TENANT_C},
        )
        connection.execute(
            text(
                f"insert into {_SCHEMA}.app_users (id, igreja_id, clerk_user_id) values "
                "(:a, :tenant_a, :clerk_a), (:b, :tenant_b, :clerk_b)"
            ),
            {
                "a": uuid.uuid4(),
                "b": uuid.uuid4(),
                "tenant_a": _TENANT_A,
                "tenant_b": _TENANT_B,
                "clerk_a": _USER_A,
                "clerk_b": _USER_B,
            },
        )
        connection.execute(
            text(
                f"insert into {_SCHEMA}.agent_configs "
                "(id, igreja_id, informacoes_publicas) values "
                "(:a, :tenant_a, cast(:info_a as jsonb)), "
                "(:b, :tenant_b, cast(:info_b as jsonb)), "
                "(:c, :tenant_c, cast(:info_c as jsonb))"
            ),
            {
                "a": uuid.uuid4(),
                "b": uuid.uuid4(),
                "c": uuid.uuid4(),
                "tenant_a": _TENANT_A,
                "tenant_b": _TENANT_B,
                "tenant_c": _TENANT_C,
                "info_a": '{"endereco_igreja":" Avenida A, 10 ","horarios_culto":" Domingo, 19h "}',
                "info_b": '{"endereco_igreja":"Não substituir B","horarios_culto":"Terça, 20h"}',
                "info_c": '{"endereco_igreja":[],"horarios_culto":""}',
            },
        )
        connection.execute(
            text(
                f"insert into {_SCHEMA}.celulas (id, igreja_id, nome, endereco) values "
                "(:a, :tenant_a, 'Célula A', 'Residência privada A'), "
                "(:b, :tenant_b, 'Célula B', 'Residência privada B')"
            ),
            {"a": uuid.uuid4(), "b": uuid.uuid4(), "tenant_a": _TENANT_A, "tenant_b": _TENANT_B},
        )
        return _catalog_fingerprint(connection)


@pytest.fixture
def s2b_engine(rls_database_url: str) -> Iterator[tuple[Engine, tuple[object, ...]]]:
    admin = create_engine(rls_database_url, future=True)
    engine = create_engine(
        rls_database_url,
        future=True,
        connect_args={"options": f"-csearch_path={_SCHEMA},public"},
    )
    baseline = _prepare_pre_s2b_baseline(engine)
    try:
        yield engine, baseline
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade")
        admin.dispose()


def _as_authenticated(connection, clerk_user_id: str) -> None:
    connection.execute(
        text("select set_config('app.clerk_user_id', :clerk_user_id, true)"),
        {"clerk_user_id": clerk_user_id},
    )
    connection.execute(text("set local role authenticated"))


def test_s2b_migration_is_idempotent_backfills_and_preserves_rls_acl(
    s2b_engine: tuple[Engine, tuple[object, ...]],
) -> None:
    engine, baseline = s2b_engine
    _apply_migration(engine)
    # The first pass proves a field absent from the baseline was created and
    # backfilled. A later operator edit must survive the idempotent replay.
    with engine.begin() as connection:
        connection.execute(
            text(
                f"update {_SCHEMA}.igrejas set endereco_institucional = :address "
                "where id = :tenant_b"
            ),
            {"address": "Destino B preservado", "tenant_b": _TENANT_B},
        )
        connection.execute(
            text(
                f"update {_SCHEMA}.agent_configs set informacoes_publicas = "
                "cast(:info as jsonb) where igreja_id = :tenant_b"
            ),
            {
                "info": '{"endereco_igreja":"Não substituir destino B","horarios_culto":"Terça, 20h"}',
                "tenant_b": _TENANT_B,
            },
        )
    _apply_migration(engine)

    with engine.connect() as connection:
        post = _catalog_fingerprint(connection)
        public_reply_column = connection.execute(
            text(
                "select is_nullable, column_default from information_schema.columns "
                "where table_schema = :schema and table_name = 'messages' "
                "and column_name = 'public_info_reply'"
            ),
            {"schema": _SCHEMA},
        ).one()
        rows = connection.execute(
            text(
                f"select id, endereco_institucional, horarios_culto, logo_path "
                f"from {_SCHEMA}.igrejas order by id"
            )
        ).all()
        bypass = connection.execute(
            text("select rolbypassrls, rolsuper from pg_roles where rolname = 'authenticated'")
        ).one()
        privileges = connection.execute(
            text(
                "select has_column_privilege('authenticated', :table_name, "
                "'endereco_institucional', 'UPDATE'), "
                "has_column_privilege('authenticated', :table_name, "
                "'horarios_culto', 'UPDATE'), "
                "has_column_privilege('authenticated', :table_name, 'status', 'UPDATE')"
            ),
            {"table_name": f"{_SCHEMA}.igrejas"},
        ).one()

    assert post == baseline
    assert public_reply_column == ("YES", None)
    assert bypass == (False, False)
    assert privileges == (True, True, False)
    assert rows == [
        (_TENANT_A, "Avenida A, 10", "Domingo, 19h", "logo-a"),
        (_TENANT_B, "Destino B preservado", "Terça, 20h", "logo-b"),
        (_TENANT_C, None, None, "logo-c"),
    ]

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"update {_SCHEMA}.igrejas set endereco_institucional = repeat('x', 401) "
                    "where id = :tenant_a"
                ),
                {"tenant_a": _TENANT_A},
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"update {_SCHEMA}.agent_configs set informacoes_publicas = '[]'::jsonb "
                    "where igreja_id = :tenant_a"
                ),
                {"tenant_a": _TENANT_A},
            )

    with engine.begin() as connection:
        _as_authenticated(connection, _USER_A)
        churches_a = connection.execute(
            text(f"select id from {_SCHEMA}.igrejas order by id")
        ).scalars().all()
        cells_a = connection.execute(
            text(f"select igreja_id from {_SCHEMA}.celulas order by igreja_id")
        ).scalars().all()
        own_update = connection.execute(
            text(
                f"update {_SCHEMA}.igrejas set horarios_culto = 'Quarta, 19h' "
                "where id = :tenant_a"
            ),
            {"tenant_a": _TENANT_A},
        ).rowcount
        foreign_update = connection.execute(
            text(
                f"update {_SCHEMA}.igrejas set horarios_culto = 'Não publicar' "
                "where id = :tenant_b"
            ),
            {"tenant_b": _TENANT_B},
        ).rowcount
    assert churches_a == [_TENANT_A]
    assert cells_a == [_TENANT_A]
    assert own_update == 1
    assert foreign_update == 0

    with engine.begin() as connection:
        _as_authenticated(connection, _USER_B)
        assert connection.execute(
            text(f"select id from {_SCHEMA}.igrejas order by id")
        ).scalars().all() == [_TENANT_B]
        assert connection.execute(
            text(f"select igreja_id from {_SCHEMA}.celulas order by igreja_id")
        ).scalars().all() == [_TENANT_B]


@pytest.mark.parametrize("wrong_command", (False, True), ids=("missing", "insert"))
def test_s2b_migration_requires_existing_igrejas_self_update_policy(
    s2b_engine: tuple[Engine, tuple[object, ...]],
    wrong_command: bool,
) -> None:
    """The final policy guard aborts all additive DDL if UPDATE policy is absent."""

    engine, _baseline = s2b_engine
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"drop policy igrejas_self_update on {_SCHEMA}.igrejas"
        )
        if wrong_command:
            connection.exec_driver_sql(
                f"create policy igrejas_self_update on {_SCHEMA}.igrejas for insert "
                f"with check (id = {_SCHEMA}.current_igreja_id())"
            )
        before = _catalog_fingerprint(connection)

    with pytest.raises(PsycopgError) as migration_error:
        _apply_migration(engine)
    assert migration_error.value.pgcode == "P0001"
    assert "policy igrejas_self_update ausente ou inválida" in str(
        migration_error.value
    )

    with engine.connect() as connection:
        after = _catalog_fingerprint(connection)
        columns = connection.execute(
            text(
                "select table_name, column_name from information_schema.columns "
                "where table_schema = :schema and ("
                "(table_name = 'igrejas' and column_name in "
                "('endereco_institucional', 'horarios_culto')) or "
                "(table_name = 'celulas' and column_name in "
                "('bairro', 'divulgar_whatsapp')) or "
                "(table_name = 'conversations' and column_name like 'secretaria_oferta%') or "
                "(table_name = 'messages' and column_name = 'public_info_reply')) "
                "order by table_name, column_name"
            ),
            {"schema": _SCHEMA},
        ).all()
    assert after == before
    assert columns == []


def _seed_offer_rows(engine: Engine) -> dict[str, uuid.UUID]:
    ids = {name: uuid.uuid4() for name in (
        "conversation_a",
        "conversation_a_other",
        "conversation_b",
        "outbound_a",
        "outbound_a_other",
        "outbound_b",
        "inbound_yes",
    )}
    with engine.begin() as connection:
        connection.execute(
            text(
                f"insert into {_SCHEMA}.conversations "
                "(id, igreja_id, telefone, estado) values "
                "(:conversation_a, :tenant_a, '550000000001', 'ia'), "
                "(:conversation_a_other, :tenant_a, '550000000002', 'ia'), "
                "(:conversation_b, :tenant_b, '550000000003', 'ia')"
            ),
            {**ids, "tenant_a": _TENANT_A, "tenant_b": _TENANT_B},
        )
        connection.execute(
            text(
                f"insert into {_SCHEMA}.messages "
                "(id, igreja_id, conversation_id, direcao, autor, agent_reply_state, texto) values "
                "(:outbound_a, :tenant_a, :conversation_a, 'out', 'ia', 'ia', 'oferta A'), "
                "(:outbound_a_other, :tenant_a, :conversation_a_other, 'out', 'ia', 'ia', 'oferta A2'), "
                "(:outbound_b, :tenant_b, :conversation_b, 'out', 'ia', 'ia', 'oferta B'), "
                "(:inbound_yes, :tenant_a, :conversation_a, 'in', 'contato', null, 'sim')"
            ),
            {**ids, "tenant_a": _TENANT_A, "tenant_b": _TENANT_B},
        )
        connection.execute(
            text(
                f"update {_SCHEMA}.conversations set "
                "secretaria_oferta_estado = 'pendente', "
                "secretaria_oferta_message_id = :outbound_a, "
                "secretaria_oferta_expira_em = clock_timestamp() + interval '10 minutes' "
                "where id = :conversation_a"
            ),
            ids,
        )
    return ids


def test_s2b_anchor_fks_trigger_and_two_sim_are_tenant_scoped(
    s2b_engine: tuple[Engine, tuple[object, ...]],
) -> None:
    engine, _baseline = s2b_engine
    _apply_migration(engine)
    ids = _seed_offer_rows(engine)

    with pytest.raises(IntegrityError) as cross_tenant_anchor:
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"update {_SCHEMA}.conversations set secretaria_oferta_message_id = :outbound_b "
                    "where id = :conversation_a"
                ),
                ids,
            )
    assert cross_tenant_anchor.value.orig.pgcode == "23503"
    assert (
        cross_tenant_anchor.value.orig.diag.constraint_name
        == "conversations_secretaria_oferta_anchor_tenant_fkey"
    )

    with pytest.raises(IntegrityError) as cross_conversation_anchor:
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"update {_SCHEMA}.conversations set "
                    "secretaria_oferta_estado = 'preparada', "
                    "secretaria_oferta_expira_em = null, "
                    "secretaria_oferta_message_id = :outbound_a "
                    "where id = :conversation_a_other"
                ),
                ids,
            )
    assert cross_conversation_anchor.value.orig.pgcode == "23503"
    assert (
        cross_conversation_anchor.value.orig.diag.constraint_name
        == "conversations_secretaria_oferta_anchor_tenant_fkey"
    )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"update {_SCHEMA}.messages set public_info_reply = true "
                    "where id = :inbound_yes"
                ),
                ids,
            )
    with engine.begin() as connection:
        assert connection.execute(
            text(
                f"update {_SCHEMA}.messages set public_info_reply = true "
                "where id = :outbound_a"
            ),
            ids,
        ).rowcount == 1

    # The response anchor has the same composite tenant/conversation fence as
    # the outbound offer.  Use the waiting state so its shape CHECK is valid
    # and the foreign key itself is what rejects each mismatch.
    for mismatched_response in ("outbound_b", "outbound_a_other"):
        with pytest.raises(IntegrityError) as mismatched_response_error:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        f"update {_SCHEMA}.conversations set "
                        "secretaria_oferta_estado = 'aceite_aguardando_ancora', "
                        "secretaria_oferta_expira_em = null, "
                        f"secretaria_oferta_resposta_message_id = :{mismatched_response} "
                        "where id = :conversation_a"
                    ),
                    ids,
                )
        assert mismatched_response_error.value.orig.pgcode == "23503"
        assert (
            mismatched_response_error.value.orig.diag.constraint_name
            == "conversations_secretaria_oferta_response_tenant_fkey"
        )

    with engine.begin() as connection:
        _as_authenticated(connection, _USER_A)
        assert connection.execute(
            text(f"delete from {_SCHEMA}.messages where id = :outbound_b"),
            ids,
        ).rowcount == 0
        assert connection.execute(
            text(
                f"select secretaria_oferta_message_id from {_SCHEMA}.conversations "
                "where id = :conversation_a"
            ),
            ids,
        ).scalar_one() == ids["outbound_a"]
        assert connection.execute(
            text(f"delete from {_SCHEMA}.messages where id = :outbound_a"),
            ids,
        ).rowcount == 1
        assert connection.execute(
            text(
                f"select secretaria_oferta_estado, secretaria_oferta_message_id, "
                "secretaria_oferta_expira_em, secretaria_oferta_resposta_message_id "
                f"from {_SCHEMA}.conversations where id = :conversation_a"
            ),
            ids,
        ).one() == (None, None, None, None)

    # Re-arm the same tenant-conversation pair with a new real outbound anchor.
    with engine.begin() as connection:
        replacement = uuid.uuid4()
        connection.execute(
            text(
                f"insert into {_SCHEMA}.messages "
                "(id, igreja_id, conversation_id, direcao, autor, agent_reply_state, texto) "
                "values (:id, :tenant_a, :conversation_a, 'out', 'ia', 'ia', 'oferta nova')"
            ),
            {"id": replacement, "tenant_a": _TENANT_A, **ids},
        )
        connection.execute(
            text(
                f"update {_SCHEMA}.conversations set secretaria_oferta_estado = 'pendente', "
                "secretaria_oferta_message_id = :id, "
                "secretaria_oferta_expira_em = clock_timestamp() + interval '10 minutes', "
                "secretaria_oferta_resposta_message_id = null where id = :conversation_a"
            ),
            {"id": replacement, **ids},
        )
        ids["outbound_a"] = replacement

    first_locked = threading.Event()
    allow_first = threading.Event()
    outcomes: list[object] = []
    errors: list[BaseException] = []

    def accept_offer(*, wait_before_commit: bool) -> None:
        session = Session(engine, future=True)
        try:
            conversation = session.execute(
                select(Conversation)
                .where(
                    Conversation.id == ids["conversation_a"],
                    Conversation.igreja_id == _TENANT_A,
                )
                .with_for_update()
            ).scalar_one()
            outcome = resolve_secretaria_offer_inbound(
                session,
                conversation,
                igreja_id=_TENANT_A,
                inbound_message_id=ids["inbound_yes"],
                current_text="SIM!",
            )
            outcomes.append(outcome)
            if wait_before_commit:
                first_locked.set()
                assert allow_first.wait(timeout=5)
            session.commit()
        except BaseException as exc:  # pragma: no cover - asserted below
            session.rollback()
            errors.append(exc)
        finally:
            session.close()

    first = threading.Thread(target=accept_offer, kwargs={"wait_before_commit": True})
    second = threading.Thread(target=accept_offer, kwargs={"wait_before_commit": False})
    first.start()
    assert first_locked.wait(timeout=5)
    second.start()
    time.sleep(0.05)
    allow_first.set()
    first.join(timeout=5)
    second.join(timeout=5)
    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert sum(bool(outcome.handoff) for outcome in outcomes) == 1

    with engine.begin() as connection:
        assert connection.execute(
            text(
                f"select secretaria_oferta_estado, secretaria_oferta_resposta_message_id "
                f"from {_SCHEMA}.conversations where id = :conversation_a"
            ),
            ids,
        ).one() == ("consumida", ids["inbound_yes"])

        # Conversation cascade and tenant bulk delete both leave tenant B intact.
        connection.execute(
            text(f"delete from {_SCHEMA}.conversations where id = :conversation_a_other"),
            ids,
        )
        assert connection.execute(
            text(f"select count(*) from {_SCHEMA}.messages where conversation_id = :conversation_a_other"),
            ids,
        ).scalar_one() == 0
        connection.execute(
            text(f"delete from {_SCHEMA}.igrejas where id = :tenant_a"),
            {"tenant_a": _TENANT_A},
        )
        assert connection.execute(
            text(f"select count(*) from {_SCHEMA}.igrejas where id = :tenant_b"),
            {"tenant_b": _TENANT_B},
        ).scalar_one() == 1
