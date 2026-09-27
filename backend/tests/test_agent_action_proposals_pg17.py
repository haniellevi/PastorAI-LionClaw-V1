"""PostgreSQL 17 proof for S3 identity and durable action-proposal boundaries."""

from __future__ import annotations

import json
from pathlib import Path
import threading
import uuid

import psycopg2
import pytest
from psycopg2.errors import CheckViolation, InsufficientPrivilege, UniqueViolation
from sqlalchemy import create_engine

from tests.conftest_rls import rls_database_url  # noqa: F401


pytestmark = pytest.mark.rls_integration

_MIGRATION = Path(__file__).parents[1] / "migrations" / (
    "20260927_170000_whatsapp_privilege_actions.sql"
)
_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_B = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
_PESSOA_A = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
_PESSOA_A2 = uuid.UUID("00000000-0000-0000-0000-0000000000f2")
_PESSOA_B = uuid.UUID("00000000-0000-0000-0000-0000000000f3")
_USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
_USER_A2 = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
_USER_B = uuid.UUID("00000000-0000-0000-0000-0000000000e3")
_CONV_A = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
_CONV_A2 = uuid.UUID("00000000-0000-0000-0000-0000000000c2")
_CONV_B = uuid.UUID("00000000-0000-0000-0000-0000000000c3")
_SOURCE_A = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
_SOURCE_A2 = uuid.UUID("00000000-0000-0000-0000-0000000000d2")
_SOURCE_B = uuid.UUID("00000000-0000-0000-0000-0000000000d3")


@pytest.fixture
def s3_actions_pg(rls_database_url):
    """Fresh baseline deliberately predating the S3 migration."""

    engine = create_engine(rls_database_url)
    schema = "s3_actions_" + uuid.uuid4().hex
    connection = engine.raw_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(f"create schema {schema}")
        cursor.execute(f"set search_path = {schema}, public")
        cursor.execute(
            "do $$ begin "
            "if not exists (select 1 from pg_roles where rolname = 'authenticated') then "
            "create role authenticated nologin noinherit nobypassrls; end if; "
            "if not exists (select 1 from pg_roles where rolname = 'anon') then "
            "create role anon nologin noinherit nobypassrls; end if; "
            "if not exists (select 1 from pg_roles where rolname = 'agent_runtime') then "
            "create role agent_runtime nologin noinherit nobypassrls; end if; "
            "end $$;"
        )
        cursor.execute(
            f"""
            create table {schema}.igrejas (
              id uuid primary key, status text not null
            );
            create table {schema}.pessoas (
              id uuid primary key,
              igreja_id uuid not null references {schema}.igrejas(id) on delete cascade,
              telefone text not null,
              arquivada_em timestamptz,
              optout boolean not null default false,
              sem_interesse boolean not null default false,
              unique (igreja_id, id)
            );
            create table {schema}.app_users (
              id uuid primary key,
              igreja_id uuid not null references {schema}.igrejas(id) on delete cascade,
              pessoa_id uuid references {schema}.pessoas(id) on delete set null,
              clerk_user_id text unique,
              status text,
              password_changed_at timestamptz,
              unique (igreja_id, id)
            );
            create table {schema}.user_roles (
              id uuid primary key,
              igreja_id uuid not null references {schema}.igrejas(id) on delete cascade,
              user_id uuid not null references {schema}.app_users(id) on delete cascade,
              papel text not null,
              unique (user_id, papel)
            );
            create table {schema}.celulas (
              id uuid primary key,
              igreja_id uuid not null references {schema}.igrejas(id) on delete cascade,
              lider_id uuid references {schema}.pessoas(id) on delete set null,
              ativo boolean not null default true
            );
            create table {schema}.conversations (
              id uuid primary key,
              igreja_id uuid not null references {schema}.igrejas(id) on delete cascade,
              pessoa_id uuid references {schema}.pessoas(id) on delete set null,
              telefone text not null,
              estado text,
              assumido_por uuid,
              unique (igreja_id, id)
            );
            create table {schema}.messages (
              id uuid primary key,
              igreja_id uuid not null references {schema}.igrejas(id) on delete cascade,
              conversation_id uuid not null references {schema}.conversations(id) on delete cascade,
              direcao text not null,
              autor text not null,
              agent_reply_state text,
              texto text,
              criado_em timestamptz not null default now(),
              unique (igreja_id, conversation_id, id)
            );
            create table {schema}.agent_configs (
              id uuid primary key,
              igreja_id uuid not null unique references {schema}.igrejas(id) on delete cascade,
              comportamento text not null,
              ativo boolean not null
            );
            create table {schema}.consent_records (
              id uuid primary key,
              igreja_id uuid not null references {schema}.igrejas(id) on delete cascade,
              pessoa_id uuid not null references {schema}.pessoas(id) on delete cascade,
              termo_versao text,
              aceite_em timestamptz
            );
            create function {schema}.current_igreja_id() returns uuid
              language sql stable as $$
                select nullif(current_setting('app.tenant_igreja_id', true), '')::uuid
              $$;
            """
        )
        for table in (
            "pessoas",
            "app_users",
            "user_roles",
            "celulas",
            "conversations",
            "messages",
            "agent_configs",
            "consent_records",
        ):
            cursor.execute(f"alter table {schema}.{table} enable row level security")
            cursor.execute(
                f"create policy tenant_isolation on {schema}.{table} for all "
                f"using (igreja_id = {schema}.current_igreja_id()) "
                f"with check (igreja_id = {schema}.current_igreja_id())"
            )
        cursor.execute(f"alter table {schema}.igrejas enable row level security")
        cursor.execute(
            f"create policy igrejas_self_select on {schema}.igrejas for select "
            f"using (id = {schema}.current_igreja_id())"
        )
        cursor.execute(
            f"grant usage on schema {schema} to authenticated, anon, agent_runtime; "
            f"grant select, insert, update, delete on all tables in schema {schema} to authenticated;"
        )
        _seed(cursor, schema)
        connection.commit()
        migration = _MIGRATION.read_text(encoding="utf-8").replace("public.", f"{schema}.")
        cursor.execute(migration)
        connection.commit()
        cursor.execute(migration)
        connection.commit()
        yield connection, cursor, schema, engine
    finally:
        connection.rollback()
        cursor.close()
        connection.close()
        with engine.begin() as cleanup:
            cleanup.exec_driver_sql(f"drop schema if exists {schema} cascade")
        engine.dispose()


def _seed(cursor, schema: str) -> None:
    cursor.execute(
        f"insert into {schema}.igrejas (id, status) values (%s, 'ativa'), (%s, 'ativa')",
        (str(_A), str(_B)),
    )
    cursor.execute(
        f"""
        insert into {schema}.pessoas (id, igreja_id, telefone) values
          (%s, %s, '5500000000000'), (%s, %s, '5500000000001'),
          (%s, %s, '5500000000002');
        insert into {schema}.app_users (id, igreja_id, pessoa_id, clerk_user_id, status) values
          (%s, %s, %s, 'clerk_s3_a', 'ativo'),
          (%s, %s, %s, 'clerk_s3_a2', 'ativo'),
          (%s, %s, %s, 'clerk_s3_b', 'ativo');
        insert into {schema}.user_roles (id, igreja_id, user_id, papel) values
          (%s, %s, %s, 'membro'), (%s, %s, %s, 'pastor'), (%s, %s, %s, 'membro');
        insert into {schema}.conversations (id, igreja_id, pessoa_id, telefone, estado) values
          (%s, %s, %s, '5500000000000', 'ia'),
          (%s, %s, %s, '5500000000001', 'ia'),
          (%s, %s, %s, '5500000000002', 'ia');
        insert into {schema}.messages (id, igreja_id, conversation_id, direcao, autor, texto) values
          (%s, %s, %s, 'in', 'contato', 'inbound A'),
          (%s, %s, %s, 'in', 'contato', 'inbound A2'),
          (%s, %s, %s, 'in', 'contato', 'inbound B');
        insert into {schema}.agent_configs (id, igreja_id, comportamento, ativo) values
          (%s, %s, 'perfil sintético', true), (%s, %s, 'perfil sintético', true);
        insert into {schema}.consent_records (id, igreja_id, pessoa_id, termo_versao, aceite_em) values
          (%s, %s, %s, 's3-synthetic', now()),
          (%s, %s, %s, 's3-synthetic', now()),
          (%s, %s, %s, 's3-synthetic', now());
        """,
        (
            str(_PESSOA_A), str(_A), str(_PESSOA_A2), str(_A), str(_PESSOA_B), str(_B),
            str(_USER_A), str(_A), str(_PESSOA_A),
            str(_USER_A2), str(_A), str(_PESSOA_A2),
            str(_USER_B), str(_B), str(_PESSOA_B),
            str(uuid.UUID("00000000-0000-0000-0000-0000000000e4")), str(_A), str(_USER_A),
            str(uuid.UUID("00000000-0000-0000-0000-0000000000e5")), str(_A), str(_USER_A2),
            str(uuid.UUID("00000000-0000-0000-0000-0000000000e6")), str(_B), str(_USER_B),
            str(_CONV_A), str(_A), str(_PESSOA_A),
            str(_CONV_A2), str(_A), str(_PESSOA_A2),
            str(_CONV_B), str(_B), str(_PESSOA_B),
            str(_SOURCE_A), str(_A), str(_CONV_A),
            str(_SOURCE_A2), str(_A), str(_CONV_A2),
            str(_SOURCE_B), str(_B), str(_CONV_B),
            str(uuid.UUID("00000000-0000-0000-0000-0000000000a4")), str(_A),
            str(uuid.UUID("00000000-0000-0000-0000-0000000000b4")), str(_B),
            str(uuid.UUID("00000000-0000-0000-0000-0000000000a5")), str(_A), str(_PESSOA_A),
            str(uuid.UUID("00000000-0000-0000-0000-0000000000a6")), str(_A), str(_PESSOA_A2),
            str(uuid.UUID("00000000-0000-0000-0000-0000000000b5")), str(_B), str(_PESSOA_B),
        ),
    )


def _as_authenticated(cursor, *, igreja_id: uuid.UUID, clerk_sub: str | None) -> None:
    cursor.execute("reset role")
    cursor.execute("set local role authenticated")
    cursor.execute("select set_config('app.tenant_igreja_id', %s, true)", (str(igreja_id),))
    claims = "" if clerk_sub is None else json.dumps({"sub": clerk_sub})
    cursor.execute("select set_config('request.jwt.claims', %s, true)", (claims,))


def _raises(cursor, statement: str, params=()):
    cursor.execute("savepoint s3_attempt")
    try:
        cursor.execute(statement, params)
    except psycopg2.Error as exc:
        cursor.execute("rollback to savepoint s3_attempt")
        return type(exc)
    cursor.execute("release savepoint s3_attempt")
    return None


def _proposal_insert(cursor, schema: str, *, proposal_id: uuid.UUID, igreja_id: uuid.UUID = _A, conversation_id: uuid.UUID = _CONV_A, pessoa_id: uuid.UUID = _PESSOA_A, user_id: uuid.UUID = _USER_A, source_id: uuid.UUID = _SOURCE_A) -> None:
    cursor.execute(
        f"""
        insert into {schema}.agent_action_proposals (
          id, igreja_id, conversation_id, actor_pessoa_id, actor_app_user_id,
          source_message_id, action, target_kind, target_id, arguments_json,
          arguments_sha256, scope_fingerprint, summary_sha256, state
        ) values (
          %s, %s, %s, %s, %s, %s, 'registrar_decisao', 'pessoa', %s,
          '{{"celula_id":null,"pessoa_id":"00000000-0000-0000-0000-0000000000f1","vinculo":"celula"}}'::jsonb,
          repeat('a', 64), repeat('b', 64), repeat('c', 64), 'preparada'
        )
        """,
        (
            str(proposal_id), str(igreja_id), str(conversation_id), str(pessoa_id),
            str(user_id), str(source_id), str(pessoa_id),
        ),
    )


def test_s3_migration_preserves_message_rls_and_denies_panel_action_rows(s3_actions_pg) -> None:
    _, cursor, schema, _ = s3_actions_pg
    for table in (
        "agent_identity_challenges",
        "agent_identity_proofs",
        "agent_action_proposals",
        "agent_action_receipts",
    ):
        cursor.execute(
            "select relrowsecurity, relforcerowsecurity from pg_class where oid = %s::regclass",
            (f"{schema}.{table}",),
        )
        assert cursor.fetchone() == (True, True)
    cursor.execute(
        "select relrowsecurity from pg_class where oid = %s::regclass",
        (f"{schema}.messages",),
    )
    assert cursor.fetchone() == (True,)

    _as_authenticated(cursor, igreja_id=_A, clerk_sub=None)
    proposal_id = uuid.UUID("00000000-0000-0000-0000-0000000000a7")
    _proposal_insert(cursor, schema, proposal_id=proposal_id)
    cursor.execute(f"select id::text from {schema}.agent_action_proposals")
    assert cursor.fetchall() == [(str(proposal_id),)]
    assert _raises(
        cursor,
        f"update {schema}.messages set agent_privilege_context = '[]'::jsonb where id = %s",
        (str(_SOURCE_A),),
    ) is CheckViolation

    _as_authenticated(cursor, igreja_id=_A, clerk_sub="clerk_s3_a")
    cursor.execute(f"select id from {schema}.agent_action_proposals")
    assert cursor.fetchall() == []
    assert _raises(
        cursor,
        f"select * from {schema}.agent_action_proposals",
    ) is None
    assert _raises(
        cursor,
        f"""insert into {schema}.agent_action_proposals (
          id, igreja_id, conversation_id, actor_pessoa_id, actor_app_user_id,
          source_message_id, action, target_kind, target_id, arguments_json,
          arguments_sha256, scope_fingerprint, summary_sha256, state
        ) values (%s, %s, %s, %s, %s, %s, 'registrar_decisao', 'pessoa', %s,
          '{{}}'::jsonb, repeat('a',64), repeat('b',64), repeat('c',64), 'preparada')""",
        (
            str(uuid.uuid4()), str(_A), str(_CONV_A), str(_PESSOA_A), str(_USER_A),
            str(_SOURCE_A), str(_PESSOA_A),
        ),
    ) is InsufficientPrivilege

    _as_authenticated(cursor, igreja_id=_B, clerk_sub=None)
    cursor.execute(f"select id from {schema}.agent_action_proposals")
    assert cursor.fetchall() == []
    assert _raises(
        cursor,
        f"select * from {schema}.agent_action_proposals where id = %s",
        (str(proposal_id),),
    ) is None
    assert _raises(
        cursor,
        f"""insert into {schema}.agent_action_proposals (
          id, igreja_id, conversation_id, actor_pessoa_id, actor_app_user_id,
          source_message_id, action, target_kind, target_id, arguments_json,
          arguments_sha256, scope_fingerprint, summary_sha256, state
        ) values (%s, %s, %s, %s, %s, %s, 'registrar_decisao', 'pessoa', %s,
          '{{}}'::jsonb, repeat('a',64), repeat('b',64), repeat('c',64), 'preparada')""",
        (
            str(uuid.uuid4()), str(_A), str(_CONV_A), str(_PESSOA_A), str(_USER_A),
            str(_SOURCE_A), str(_PESSOA_A),
        ),
    ) is InsufficientPrivilege


def test_identity_proof_is_own_subject_only_and_worker_cannot_insert(s3_actions_pg) -> None:
    _, cursor, schema, _ = s3_actions_pg
    challenge = uuid.UUID("00000000-0000-0000-0000-0000000000a8")
    _as_authenticated(cursor, igreja_id=_A, clerk_sub=None)
    cursor.execute(
        f"""insert into {schema}.agent_identity_challenges (
          id, igreja_id, conversation_id, pessoa_id, issued_from_message_id,
          issued_at, challenge_expires_at, sequence
        ) values (%s, %s, %s, %s, %s, now(), now() + interval '5 minutes', 1)""",
        (str(challenge), str(_A), str(_CONV_A), str(_PESSOA_A), str(_SOURCE_A)),
    )
    proof_values = (
        str(uuid.UUID("00000000-0000-0000-0000-0000000000a9")), str(_A), str(challenge),
        str(_CONV_A), str(_PESSOA_A), str(_USER_A),
    )
    proof_sql = f"""insert into {schema}.agent_identity_proofs (
      id, igreja_id, challenge_id, conversation_id, pessoa_id,
      confirmed_by_app_user_id, confirmed_at, confirmed_until,
      credential_fingerprint, roles_fingerprint, integrity_hmac
    ) values (%s, %s, %s, %s, %s, %s, now(), now() + interval '15 minutes',
      repeat('a',64), repeat('b',64), repeat('c',64))"""
    _as_authenticated(cursor, igreja_id=_A, clerk_sub="clerk_s3_a")
    cursor.execute(proof_sql, proof_values)

    _as_authenticated(cursor, igreja_id=_A, clerk_sub=None)
    assert _raises(cursor, proof_sql, proof_values) is InsufficientPrivilege

    _as_authenticated(cursor, igreja_id=_A, clerk_sub="clerk_s3_a2")
    cursor.execute(f"select id from {schema}.agent_identity_proofs")
    assert cursor.fetchall() == []
    assert _raises(cursor, proof_sql, proof_values) is InsufficientPrivilege

    _as_authenticated(cursor, igreja_id=_B, clerk_sub="clerk_s3_b")
    cursor.execute(f"select id from {schema}.agent_identity_proofs")
    assert cursor.fetchall() == []
    assert _raises(cursor, proof_sql, proof_values) is InsufficientPrivilege


def test_one_active_proposal_wins_under_two_worker_transactions(s3_actions_pg) -> None:
    _, cursor, schema, engine = s3_actions_pg
    cursor.execute("reset role")
    cursor.connection.commit()
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    errors: list[str] = []
    guard = threading.Lock()

    def _attempt() -> None:
        local = engine.raw_connection()
        local_cursor = None
        try:
            local_cursor = local.cursor()
            _as_authenticated(local_cursor, igreja_id=_A, clerk_sub=None)
            barrier.wait(timeout=5)
            try:
                _proposal_insert(local_cursor, schema, proposal_id=uuid.uuid4())
                local.commit()
                outcome = "winner"
            except psycopg2.Error:
                local.rollback()
                outcome = "lost"
            with guard:
                outcomes.append(outcome)
        except BaseException as exc:  # noqa: BLE001 - report setup failure deterministically
            with guard:
                errors.append(type(exc).__name__)
        finally:
            if local_cursor is not None:
                local_cursor.close()
            local.close()

    first = threading.Thread(target=_attempt)
    second = threading.Thread(target=_attempt)
    first.start()
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)
    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert sorted(outcomes) == ["lost", "winner"]

    _as_authenticated(cursor, igreja_id=_A, clerk_sub=None)
    cursor.execute(f"select count(*) from {schema}.agent_action_proposals")
    assert cursor.fetchone() == (1,)


@pytest.mark.parametrize('conversation_id,source_id', [(_CONV_A, _SOURCE_A), (_CONV_A2, _SOURCE_A2)])
def test_panel_cannot_issue_challenge_for_own_or_other_person(s3_actions_pg, conversation_id, source_id):
    _, cursor, schema, _ = s3_actions_pg
    _as_authenticated(cursor, igreja_id=_A, clerk_sub='clerk_s3_a')
    sql = f'''insert into {schema}.agent_identity_challenges (
        id, igreja_id, conversation_id, pessoa_id, issued_from_message_id,
        issued_at, challenge_expires_at, sequence
    ) values (%s,%s,%s,%s,%s,now(),now()+interval '5 minutes',9223372036854775807)'''
    params = tuple(str(v) for v in (uuid.uuid4(),_A,conversation_id,_PESSOA_A,source_id))
    assert _raises(cursor, sql, params) is InsufficientPrivilege
