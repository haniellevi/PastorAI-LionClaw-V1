"""PostgreSQL 17 contract for the D2B2b3A governance-draft migration."""

from __future__ import annotations

import json
import pathlib
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from psycopg2 import Error as PsycopgError
from sqlalchemy import create_engine, event as sa_event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.domain.purpose_consent import PurposeConsentPurpose
from app.domain.purpose_consent_governance import (
    empty_purpose_consent_governance_content,
    normalize_purpose_consent_governance_api_payload,
)
from app.services.purpose_consent_governance import (
    PurposeConsentGovernanceRevisionConflictError,
    initialize_purpose_consent_governance,
    load_purpose_consent_governance,
    update_purpose_consent_governance_draft,
)
from tests.conftest_rls import (  # noqa: F401
    assert_disposable_database,
    rls_database_url,
)


_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260828_094914_d2b2b3_purpose_consent_governance_drafts.sql"
)
_SCHEMA = "public"
_TABLE = f"{_SCHEMA}.purpose_consent_governance_envelope"

IGREJA_A = uuid.UUID("a1000000-0000-0000-0000-000000000001")
IGREJA_B = uuid.UUID("b1000000-0000-0000-0000-000000000001")
ACTOR_ID = uuid.UUID("c1000000-0000-0000-0000-000000000001")
PLATFORM_ADMIN_ID = uuid.UUID("d1000000-0000-0000-0000-000000000001")

_FIELDS = (
    "real_processing_agents",
    "operations_and_minimum_data",
    "data_sensitivity_assessment",
    "operational_need",
    "systems_and_recipients",
    "retention_and_disposal_inventory",
    "operator_instructions",
    "open_questions",
)
_PURPOSES = (
    "atendimento_solicitado",
    "cuidado_pastoral",
    "tarefas_operacionais",
    "comunicados",
)


def _migration_sql() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def _execute_script(engine: Engine, sql: str) -> None:
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.execute(sql)
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            cursor.close()
    finally:
        raw.close()


def _execute_script_as_role(engine: Engine, role: str, sql: str) -> None:
    """Execute an imperative migration as one controlled database owner."""

    raw = engine.raw_connection()
    quoted_role = engine.dialect.identifier_preparer.quote(role)
    original_autocommit = raw.autocommit
    try:
        raw.autocommit = True
        cursor = raw.cursor()
        try:
            cursor.execute(f"set role {quoted_role}")
            cursor.execute(sql)
        except BaseException:
            raw.rollback()
            raise
        finally:
            cursor.execute("reset role")
            cursor.close()
    finally:
        raw.autocommit = original_autocommit
        raw.close()


def _setup_base(engine: Engine) -> None:
    ddl = f"""
    do $$ begin
      if to_regrole('anon') is null then
        create role anon nologin noinherit nobypassrls;
      end if;
      if to_regrole('authenticated') is null then
        create role authenticated nologin noinherit nobypassrls;
      end if;
      if to_regrole('service_role') is null then
        create role service_role nologin noinherit bypassrls;
      end if;
      if to_regrole('agent_runtime') is null then
        create role agent_runtime nologin noinherit nobypassrls;
      end if;
    end $$;

    drop schema if exists {_SCHEMA} cascade;
    create schema {_SCHEMA};
    grant usage on schema {_SCHEMA}
      to anon, authenticated, service_role, agent_runtime;

    create table {_SCHEMA}.igrejas (
      id uuid primary key,
      nome text not null
    );
    create table {_SCHEMA}.app_users (
      id uuid primary key,
      igreja_id uuid not null references {_SCHEMA}.igrejas(id) on delete cascade,
      nome text not null,
      email text not null
    );
    create table {_SCHEMA}.platform_admins (
      id uuid primary key,
      app_user_id uuid not null unique
        references {_SCHEMA}.app_users(id) on delete cascade,
      email text not null
    );

    insert into {_SCHEMA}.igrejas (id, nome) values
      ('{IGREJA_A}', 'Igreja A'),
      ('{IGREJA_B}', 'Igreja B');
    insert into {_SCHEMA}.app_users (id, igreja_id, nome, email) values
      ('{ACTOR_ID}', '{IGREJA_A}', 'Operador sintético', 'operator@example.invalid');
    insert into {_SCHEMA}.platform_admins (id, app_user_id, email) values
      ('{PLATFORM_ADMIN_ID}', '{ACTOR_ID}', 'operator@example.invalid');
    """
    _execute_script(engine, ddl)


@pytest.fixture
def unmigrated_governance_engine(governance_database_url: str) -> Engine:
    engine = create_engine(governance_database_url, future=True, pool_size=6)

    @sa_event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("set search_path to public")
        finally:
            cursor.close()

    _setup_base(engine)
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade")
        engine.dispose()


@pytest.fixture(scope="module")
def governance_database_url(rls_database_url: str) -> Iterator[str]:
    """Create an isolated child database; never mutate the shared RLS public."""

    assert_disposable_database(rls_database_url)
    root_url = make_url(rls_database_url)
    child_name = f"rls_d2b2b3_{uuid.uuid4().hex[:12]}"
    child_url = root_url.set(database=child_name).render_as_string(
        hide_password=False
    )
    assert_disposable_database(child_url)

    admin_engine = create_engine(
        root_url,
        future=True,
        isolation_level="AUTOCOMMIT",
    )
    quoted_child = admin_engine.dialect.identifier_preparer.quote(child_name)
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(
                f"create database {quoted_child} template template0"
            )
        yield child_url
    finally:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(
                f"drop database if exists {quoted_child} with (force)"
            )
        admin_engine.dispose()


@pytest.fixture
def governance_engine(unmigrated_governance_engine: Engine) -> Engine:
    engine = unmigrated_governance_engine
    _execute_script(engine, _migration_sql())
    yield engine


def _valid_drafts() -> dict[str, dict[str, str | None]]:
    return {
        purpose: {field: None for field in _FIELDS}
        for purpose in _PURPOSES
    }


def _valid_revisions() -> dict[str, int]:
    return {purpose: 1 for purpose in _PURPOSES}


def _insert_envelope(
    connection: object,
    *,
    igreja_id: uuid.UUID,
    drafts: object | None = None,
    revisions: object | None = None,
    status: str = "DRAFT_NOT_APPROVED",
) -> None:
    connection.exec_driver_sql(  # type: ignore[attr-defined]
        f"insert into {_TABLE} ("
        "igreja_id, status, drafts, draft_revisions, "
        "created_by_app_user_id, updated_by_app_user_id"
        ") values (%s, %s, %s::jsonb, %s::jsonb, %s, %s)",
        (
            str(igreja_id),
            status,
            json.dumps(drafts if drafts is not None else _valid_drafts()),
            json.dumps(revisions if revisions is not None else _valid_revisions()),
            str(ACTOR_ID),
            str(ACTOR_ID),
        ),
    )


def test_static_sql_is_draft_only_fail_closed_and_has_no_backfill() -> None:
    sql = _migration_sql().lower()

    assert sql.lstrip().startswith("-- pastorai d2b2b3a")
    assert sql.rstrip().endswith("commit;")
    assert "set transaction isolation level serializable" in sql
    assert "create table public.purpose_consent_governance_envelope" in sql
    assert "force row level security" in sql
    assert "create policy" not in sql
    assert "grant " not in sql
    assert "revoke all privileges" in sql
    for role in ("public", "anon", "authenticated", "service_role", "agent_runtime"):
        assert role in sql
    for forbidden in (
        "controller_approved boolean",
        "human_packet_complete boolean",
        "catalog_ready boolean",
        "writer_eligible boolean",
        "content_digest",
        "approval_record",
        "insert into public.purpose_consent_governance_envelope",
    ):
        assert forbidden not in sql


@pytest.mark.rls_integration
def test_migration_is_idempotent_and_catalog_is_owner_only(
    governance_engine: Engine,
) -> None:
    _execute_script(governance_engine, _migration_sql())

    with governance_engine.begin() as connection:
        relation = connection.exec_driver_sql(
            "select relkind, relrowsecurity, relforcerowsecurity "
            "from pg_class where oid=%s::regclass",
            (_TABLE,),
        ).one()
        columns = connection.exec_driver_sql(
            "select attname, format_type(atttypid, atttypmod), attnotnull "
            "from pg_attribute where attrelid=%s::regclass "
            "and attnum>0 and not attisdropped order by attnum",
            (_TABLE,),
        ).all()
        constraints = connection.exec_driver_sql(
            "select conname, contype, confdeltype, convalidated "
            "from pg_constraint where conrelid=%s::regclass order by conname",
            (_TABLE,),
        ).all()
        policies = connection.exec_driver_sql(
            "select polname from pg_policy where polrelid=%s::regclass",
            (_TABLE,),
        ).all()
        privileges = {
            (role, privilege): connection.exec_driver_sql(
                "select has_table_privilege(%s, %s, %s)",
                (role, _TABLE, privilege),
            ).scalar_one()
            for role in ("anon", "authenticated", "service_role", "agent_runtime")
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
        }
        function_privileges = {
            role: connection.exec_driver_sql(
                "select has_function_privilege(%s, %s, 'EXECUTE')",
                (
                    role,
                    "public.purpose_consent_governance_draft_valid(jsonb)",
                ),
            ).scalar_one()
            for role in (
                "anon",
                "authenticated",
                "service_role",
                "agent_runtime",
            )
        }
        column_privileges = {
            (role, privilege): connection.exec_driver_sql(
                "select has_any_column_privilege(%s, %s, %s)",
                (role, _TABLE, privilege),
            ).scalar_one()
            for role in (
                "anon",
                "authenticated",
                "service_role",
                "agent_runtime",
            )
            for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES")
        }
        owner_contract = connection.exec_driver_sql(
            "select role_row.rolsuper or role_row.rolbypassrls, "
            "(select array_agg(acl.privilege_type order by acl.privilege_type) "
            "from pg_class relation, lateral aclexplode(coalesce("
            "relation.relacl, acldefault('r', relation.relowner))) acl "
            "where relation.oid=%s::regclass and acl.grantee=relation.relowner), "
            "(select array_agg(acl.privilege_type order by acl.privilege_type) "
            "from pg_proc function_row, lateral aclexplode(coalesce("
            "function_row.proacl, acldefault('f', function_row.proowner))) acl "
            "where function_row.oid=%s::regprocedure "
            "and acl.grantee=function_row.proowner) "
            "from pg_class relation join pg_roles role_row "
            "on role_row.rolname=pg_get_userbyid(relation.relowner) "
            "where relation.oid=%s::regclass",
            (
                _TABLE,
                "public.purpose_consent_governance_draft_valid(jsonb)",
                _TABLE,
            ),
        ).one()

    assert tuple(relation) == ("r", True, True)
    assert [tuple(row) for row in columns] == [
        ("id", "uuid", True),
        ("igreja_id", "uuid", True),
        ("schema_version", "text", True),
        ("status", "text", True),
        ("drafts", "jsonb", True),
        ("draft_revisions", "jsonb", True),
        ("revision", "bigint", True),
        ("created_by_app_user_id", "uuid", False),
        ("updated_by_app_user_id", "uuid", False),
        ("created_at", "timestamp with time zone", True),
        ("updated_at", "timestamp with time zone", True),
    ]
    assert {row.conname for row in constraints} == {
        "purpose_consent_governance_envelope_pkey",
        "purpose_consent_governance_envelope_igreja_key",
        "purpose_consent_governance_envelope_igreja_fkey",
        "purpose_consent_governance_envelope_created_by_fkey",
        "purpose_consent_governance_envelope_updated_by_fkey",
        "purpose_consent_governance_envelope_schema_version_check",
        "purpose_consent_governance_envelope_status_check",
        "purpose_consent_governance_envelope_revision_check",
        "purpose_consent_governance_envelope_drafts_check",
        "purpose_consent_governance_envelope_draft_revisions_check",
    }
    assert all(row.convalidated for row in constraints)
    assert policies == []
    assert not any(privileges.values())
    assert not any(function_privileges.values())
    assert not any(column_privileges.values())
    assert tuple(owner_contract) == (
        True,
        [
            "DELETE",
            "INSERT",
            "MAINTAIN",
            "REFERENCES",
            "SELECT",
            "TRIGGER",
            "TRUNCATE",
            "UPDATE",
        ],
        ["EXECUTE"],
    )


@pytest.mark.rls_integration
def test_preexisting_validator_is_never_replaced_or_adopted(
    unmigrated_governance_engine: Engine,
) -> None:
    with unmigrated_governance_engine.begin() as connection:
        connection.exec_driver_sql(
            f"create function {_SCHEMA}.purpose_consent_governance_draft_valid("
            "payload jsonb) returns boolean language sql immutable strict "
            "as 'select false'"
        )

    with pytest.raises(PsycopgError, match="validator definition or ACL drifted"):
        _execute_script(unmigrated_governance_engine, _migration_sql())

    with unmigrated_governance_engine.begin() as connection:
        assert connection.exec_driver_sql(
            f"select {_SCHEMA}.purpose_consent_governance_draft_valid("
            "'{}'::jsonb)"
        ).scalar_one() is False
        assert connection.exec_driver_sql(
            "select to_regclass(%s)", (_TABLE,)
        ).scalar_one() is None


@pytest.mark.rls_integration
def test_homonymous_actor_index_aborts_without_partial_contract(
    unmigrated_governance_engine: Engine,
) -> None:
    index_name = "purpose_consent_governance_envelope_created_by_idx"
    with unmigrated_governance_engine.begin() as connection:
        connection.exec_driver_sql(
            f"create table {_SCHEMA}.unrelated_index_owner (id uuid not null)"
        )
        connection.exec_driver_sql(
            f"create index {index_name} "
            f"on {_SCHEMA}.unrelated_index_owner (id)"
        )

    with pytest.raises(PsycopgError, match="homonymous actor index already exists"):
        _execute_script(unmigrated_governance_engine, _migration_sql())

    with unmigrated_governance_engine.begin() as connection:
        assert connection.exec_driver_sql(
            "select to_regclass(%s)", (_TABLE,)
        ).scalar_one() is None
        assert connection.exec_driver_sql(
            "select to_regprocedure(%s)",
            (f"{_SCHEMA}.purpose_consent_governance_draft_valid(jsonb)",),
        ).scalar_one() is None
        assert connection.exec_driver_sql(
            "select indexdef from pg_indexes "
            "where schemaname=%s and indexname=%s",
            (_SCHEMA, index_name),
        ).scalar_one().endswith("unrelated_index_owner USING btree (id)")


@pytest.mark.rls_integration
def test_reapply_rejects_index_drift_without_repair(
    governance_engine: Engine,
) -> None:
    index_name = "purpose_consent_governance_envelope_created_by_idx"
    with governance_engine.begin() as connection:
        connection.exec_driver_sql(f"drop index {_SCHEMA}.{index_name}")
        connection.exec_driver_sql(
            f"create index {index_name} on {_TABLE} (revision)"
        )

    with pytest.raises(PsycopgError, match=f"index {index_name} drifted"):
        _execute_script(governance_engine, _migration_sql())

    with governance_engine.begin() as connection:
        assert connection.exec_driver_sql(
            "select pg_get_indexdef(%s::regclass)",
            (f"{_SCHEMA}.{index_name}",),
        ).scalar_one().endswith(
            "purpose_consent_governance_envelope USING btree (revision)"
        )


@pytest.mark.rls_integration
def test_reapply_rejects_constraint_drift_without_repair(
    governance_engine: Engine,
) -> None:
    constraint_name = "purpose_consent_governance_envelope_status_check"
    with governance_engine.begin() as connection:
        connection.exec_driver_sql(
            f"alter table {_TABLE} drop constraint {constraint_name}"
        )
        connection.exec_driver_sql(
            f"alter table {_TABLE} add constraint {constraint_name} "
            "check (status in ('DRAFT_NOT_APPROVED', 'CONTROLLER_APPROVED'))"
        )

    with pytest.raises(PsycopgError, match=f"constraint {constraint_name} drifted"):
        _execute_script(governance_engine, _migration_sql())

    with governance_engine.begin() as connection:
        definition = connection.exec_driver_sql(
            "select pg_get_constraintdef(oid) from pg_constraint "
            "where conrelid=%s::regclass and conname=%s",
            (_TABLE, constraint_name),
        ).scalar_one()
    assert "CONTROLLER_APPROVED" in definition


@pytest.mark.rls_integration
def test_reapply_rejects_case_only_status_constraint_drift(
    governance_engine: Engine,
) -> None:
    constraint_name = "purpose_consent_governance_envelope_status_check"
    with governance_engine.begin() as connection:
        connection.exec_driver_sql(
            f"alter table {_TABLE} drop constraint {constraint_name}"
        )
        connection.exec_driver_sql(
            f"alter table {_TABLE} add constraint {constraint_name} "
            "check (status = 'draft_not_approved')"
        )

    with pytest.raises(DBAPIError):
        with governance_engine.begin() as connection:
            _insert_envelope(connection, igreja_id=IGREJA_A)

    with pytest.raises(
        PsycopgError,
        match=f"constraint {constraint_name} drifted",
    ):
        _execute_script(governance_engine, _migration_sql())

    with governance_engine.begin() as connection:
        definition = connection.exec_driver_sql(
            "select pg_get_constraintdef(oid) from pg_constraint "
            "where conrelid=%s::regclass and conname=%s",
            (_TABLE, constraint_name),
        ).scalar_one()
    assert "draft_not_approved" in definition


@pytest.mark.rls_integration
def test_reapply_rejects_default_and_rls_drift_without_repair(
    governance_engine: Engine,
) -> None:
    with governance_engine.begin() as connection:
        connection.exec_driver_sql(
            f"alter table {_TABLE} alter column revision set default 2"
        )
        connection.exec_driver_sql(f"alter table {_TABLE} no force row level security")

    with pytest.raises(PsycopgError, match="column/default contract drifted"):
        _execute_script(governance_engine, _migration_sql())

    with governance_engine.begin() as connection:
        default_and_security = connection.exec_driver_sql(
            "select pg_get_expr(default_row.adbin, default_row.adrelid), "
            "relation.relforcerowsecurity "
            "from pg_class relation "
            "join pg_attribute attribute on attribute.attrelid=relation.oid "
            "join pg_attrdef default_row on default_row.adrelid=relation.oid "
            "and default_row.adnum=attribute.attnum "
            "where relation.oid=%s::regclass and attribute.attname='revision'",
            (_TABLE,),
        ).one()
    assert tuple(default_and_security) == ("2", False)


@pytest.mark.rls_integration
def test_reapply_rejects_owner_table_acl_drift_without_repair(
    governance_engine: Engine,
) -> None:
    with governance_engine.begin() as connection:
        connection.exec_driver_sql(
            f"revoke select on table {_TABLE} from current_user"
        )

    with pytest.raises(
        PsycopgError,
        match="RLS, policy, ACL, trigger or rule drifted",
    ):
        _execute_script(governance_engine, _migration_sql())

    with governance_engine.begin() as connection:
        owner_privileges = connection.exec_driver_sql(
            "select array_agg(acl.privilege_type order by acl.privilege_type) "
            "from pg_class relation, lateral aclexplode(coalesce("
            "relation.relacl, acldefault('r', relation.relowner))) acl "
            "where relation.oid=%s::regclass and acl.grantee=relation.relowner",
            (_TABLE,),
        ).scalar_one()
    assert "SELECT" not in owner_privileges


@pytest.mark.rls_integration
def test_reapply_rejects_owner_function_acl_drift_without_repair(
    governance_engine: Engine,
) -> None:
    function_signature = (
        "public.purpose_consent_governance_draft_valid(jsonb)"
    )
    with governance_engine.begin() as connection:
        connection.exec_driver_sql(
            "revoke execute on function "
            f"{function_signature} from current_user"
        )

    with pytest.raises(PsycopgError, match="validator definition or ACL drifted"):
        _execute_script(governance_engine, _migration_sql())

    with governance_engine.begin() as connection:
        owner_privileges = connection.exec_driver_sql(
            "select array_agg(acl.privilege_type order by acl.privilege_type) "
            "from pg_proc function_row, lateral aclexplode(coalesce("
            "function_row.proacl, acldefault('f', function_row.proowner))) acl "
            "where function_row.oid=%s::regprocedure "
            "and acl.grantee=function_row.proowner",
            (function_signature,),
        ).scalar_one_or_none()
    assert owner_privileges is None or "EXECUTE" not in owner_privileges


@pytest.mark.rls_integration
def test_reapply_blocks_column_acl_replay_exploit(
    governance_engine: Engine,
) -> None:
    with governance_engine.begin() as connection:
        _insert_envelope(connection, igreja_id=IGREJA_A)
        connection.exec_driver_sql(
            f"grant select (drafts) on table {_TABLE} to service_role"
        )
        assert connection.exec_driver_sql(
            "select has_table_privilege('service_role', %s, 'SELECT')",
            (_TABLE,),
        ).scalar_one() is False
        assert connection.exec_driver_sql(
            "select has_column_privilege('service_role', %s, 'drafts', 'SELECT')",
            (_TABLE,),
        ).scalar_one() is True

    with governance_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("set local role service_role")
            exposed = connection.exec_driver_sql(
                f"select drafts from {_TABLE}",
            ).scalar_one()
        finally:
            transaction.rollback()
    assert exposed == _valid_drafts()

    with pytest.raises(
        PsycopgError,
        match="RLS, policy, ACL, trigger or rule drifted",
    ):
        _execute_script(governance_engine, _migration_sql())

    with governance_engine.begin() as connection:
        assert connection.exec_driver_sql(
            "select has_column_privilege('service_role', %s, 'drafts', 'SELECT')",
            (_TABLE,),
        ).scalar_one() is True


@pytest.mark.rls_integration
def test_reapply_rejects_user_trigger_without_removing_it(
    governance_engine: Engine,
) -> None:
    with governance_engine.begin() as connection:
        connection.exec_driver_sql(
            "create function public.d2b2b3_unexpected_trigger() "
            "returns trigger language plpgsql as "
            "'begin return new; end'"
        )
        connection.exec_driver_sql(
            f"create trigger d2b2b3_unexpected_trigger before insert on {_TABLE} "
            "for each row execute function public.d2b2b3_unexpected_trigger()"
        )

    with pytest.raises(
        PsycopgError,
        match="RLS, policy, ACL, trigger or rule drifted",
    ):
        _execute_script(governance_engine, _migration_sql())

    with governance_engine.begin() as connection:
        assert connection.exec_driver_sql(
            "select count(*) from pg_trigger "
            "where tgrelid=%s::regclass and not tgisinternal",
            (_TABLE,),
        ).scalar_one() == 1


@pytest.mark.rls_integration
def test_reapply_rejects_rewrite_rule_without_removing_it(
    governance_engine: Engine,
) -> None:
    with governance_engine.begin() as connection:
        connection.exec_driver_sql(
            f"create rule d2b2b3_unexpected_rule as on update to {_TABLE} "
            "do also nothing"
        )

    with pytest.raises(
        PsycopgError,
        match="RLS, policy, ACL, trigger or rule drifted",
    ):
        _execute_script(governance_engine, _migration_sql())

    with governance_engine.begin() as connection:
        assert connection.exec_driver_sql(
            "select count(*) from pg_rewrite where ev_class=%s::regclass",
            (_TABLE,),
        ).scalar_one() == 1


@pytest.mark.rls_integration
def test_reapply_rejects_application_membership_in_owner(
    unmigrated_governance_engine: Engine,
) -> None:
    engine = unmigrated_governance_engine
    owner = f"d2b2b3_owner_{uuid.uuid4().hex[:12]}"
    quoted_owner = engine.dialect.identifier_preparer.quote(owner)
    with engine.begin() as connection:
        executor = connection.exec_driver_sql("select current_user").scalar_one()
    quoted_executor = engine.dialect.identifier_preparer.quote(executor)

    role_created = False
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"create role {quoted_owner} nologin bypassrls"
            )
            connection.exec_driver_sql(
                f"grant {quoted_owner} to {quoted_executor}"
            )
            connection.exec_driver_sql(
                f"alter schema public owner to {quoted_owner}"
            )
            connection.exec_driver_sql(
                f"alter table public.igrejas owner to {quoted_owner}"
            )
            connection.exec_driver_sql(
                f"alter table public.app_users owner to {quoted_owner}"
            )
        role_created = True

        _execute_script_as_role(engine, owner, _migration_sql())

        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"grant {quoted_owner} to authenticated"
            )
            assert connection.exec_driver_sql(
                "select pg_has_role('authenticated', %s, 'MEMBER')",
                (owner,),
            ).scalar_one() is True

        with pytest.raises(
            PsycopgError,
            match="application role reaches executor",
        ):
            _execute_script_as_role(engine, owner, _migration_sql())
    finally:
        if role_created:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    f"revoke {quoted_owner} from authenticated"
                )
                connection.exec_driver_sql(
                    f"reassign owned by {quoted_owner} to {quoted_executor}"
                )
                connection.exec_driver_sql(
                    f"drop owned by {quoted_owner}"
                )
                connection.exec_driver_sql(
                    f"revoke {quoted_owner} from {quoted_executor}"
                )
                connection.exec_driver_sql(f"drop role {quoted_owner}")


@pytest.mark.rls_integration
def test_database_accepts_only_exact_four_bounded_drafts(
    governance_engine: Engine,
) -> None:
    with governance_engine.begin() as connection:
        _insert_envelope(connection, igreja_id=IGREJA_A)

        canonical_multiline = _valid_drafts()
        canonical_multiline["comunicados"]["operational_need"] = (
            "linha 1\n\tdetalhe"
        )
        _insert_envelope(
            connection,
            igreja_id=IGREJA_B,
            drafts=canonical_multiline,
        )
        connection.exec_driver_sql(
            f"delete from {_TABLE} where igreja_id=%s",
            (str(IGREJA_B),),
        )

    invalid_payloads: list[tuple[object, object, str]] = []
    missing_purpose = _valid_drafts()
    missing_purpose.pop("comunicados")
    invalid_payloads.append((missing_purpose, _valid_revisions(), "missing purpose"))

    extra_field = _valid_drafts()
    extra_field["comunicados"]["content_digest"] = "forbidden"
    invalid_payloads.append((extra_field, _valid_revisions(), "extra field"))

    wrong_type = _valid_drafts()
    wrong_type["comunicados"]["operational_need"] = 42  # type: ignore[assignment]
    invalid_payloads.append((wrong_type, _valid_revisions(), "wrong type"))

    empty_string = _valid_drafts()
    empty_string["comunicados"]["operational_need"] = ""
    invalid_payloads.append((empty_string, _valid_revisions(), "empty string"))

    leading_line_feed = _valid_drafts()
    leading_line_feed["comunicados"]["operational_need"] = "\nconteúdo"
    invalid_payloads.append(
        (leading_line_feed, _valid_revisions(), "non-canonical trim")
    )

    carriage_return = _valid_drafts()
    carriage_return["comunicados"]["operational_need"] = "linha 1\rlinha 2"
    invalid_payloads.append(
        (carriage_return, _valid_revisions(), "carriage return")
    )

    control_character = _valid_drafts()
    control_character["comunicados"]["operational_need"] = "antes\u0001depois"
    invalid_payloads.append(
        (control_character, _valid_revisions(), "control character")
    )

    too_long = _valid_drafts()
    too_long["comunicados"]["operational_need"] = "x" * 4001
    invalid_payloads.append((too_long, _valid_revisions(), "field too long"))

    over_total = _valid_drafts()
    for field in _FIELDS[:5]:
        over_total["comunicados"][field] = "x" * 4000
    invalid_payloads.append((over_total, _valid_revisions(), "total too long"))

    bad_revisions = _valid_revisions()
    bad_revisions["comunicados"] = 0
    invalid_payloads.append((_valid_drafts(), bad_revisions, "bad revision"))

    for drafts, revisions, _label in invalid_payloads:
        with pytest.raises(DBAPIError):
            with governance_engine.begin() as connection:
                connection.exec_driver_sql(
                    f"delete from {_TABLE} where igreja_id=%s",
                    (str(IGREJA_B),),
                )
                _insert_envelope(
                    connection,
                    igreja_id=IGREJA_B,
                    drafts=drafts,
                    revisions=revisions,
                )

    with pytest.raises(DBAPIError):
        with governance_engine.begin() as connection:
            _insert_envelope(
                connection,
                igreja_id=IGREJA_B,
                status="CONTROLLER_APPROVED",
            )


@pytest.mark.rls_integration
def test_initialize_is_atomic_under_real_concurrency(governance_engine: Engine) -> None:
    barrier = Barrier(2)

    def initialize() -> tuple[int, tuple[int, ...]]:
        with Session(governance_engine) as session:
            with session.begin():
                barrier.wait(timeout=5)
                snapshot = initialize_purpose_consent_governance(
                    session,
                    igreja_id=IGREJA_A,
                    actor_app_user_id=ACTOR_ID,
                )
                return snapshot.revision, tuple(
                    purpose.revision for purpose in snapshot.purposes
                )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: initialize(), range(2)))

    assert results == [(1, (1, 1, 1, 1)), (1, (1, 1, 1, 1))]
    with governance_engine.begin() as connection:
        assert connection.exec_driver_sql(
            f"select count(*) from {_TABLE} where igreja_id=%s",
            (str(IGREJA_A),),
        ).scalar_one() == 1


@pytest.mark.rls_integration
def test_platform_owner_reads_and_updates_only_the_explicit_church(
    governance_engine: Engine,
) -> None:
    with Session(governance_engine) as session:
        with session.begin():
            initialized_a = initialize_purpose_consent_governance(
                session,
                igreja_id=IGREJA_A,
                actor_app_user_id=ACTOR_ID,
            )
            initialized_b = initialize_purpose_consent_governance(
                session,
                igreja_id=IGREJA_B,
                actor_app_user_id=ACTOR_ID,
            )
            updated_a = update_purpose_consent_governance_draft(
                session,
                igreja_id=IGREJA_A,
                actor_app_user_id=ACTOR_ID,
                purpose=PurposeConsentPurpose.COMUNICADOS,
                expected_revision=1,
                decision_payload=(
                    normalize_purpose_consent_governance_api_payload(
                        {"operationalNeed": "Somente igreja A"}
                    )
                ),
            )

    with Session(governance_engine) as session:
        loaded_a = load_purpose_consent_governance(
            session,
            igreja_id=IGREJA_A,
            actor_app_user_id=ACTOR_ID,
        )
        loaded_b = load_purpose_consent_governance(
            session,
            igreja_id=IGREJA_B,
            actor_app_user_id=ACTOR_ID,
        )

    assert initialized_a.igreja_id == IGREJA_A
    assert initialized_b.igreja_id == IGREJA_B
    assert updated_a.igreja_id == IGREJA_A
    assert loaded_a is not None and loaded_a.igreja_id == IGREJA_A
    assert loaded_b is not None and loaded_b.igreja_id == IGREJA_B
    assert loaded_a.revision == 2
    assert loaded_b.revision == 1
    purpose_a = next(
        item
        for item in loaded_a.purposes
        if item.purpose is PurposeConsentPurpose.COMUNICADOS
    )
    purpose_b = next(
        item
        for item in loaded_b.purposes
        if item.purpose is PurposeConsentPurpose.COMUNICADOS
    )
    assert purpose_a.decision_payload.operational_need == "Somente igreja A"
    assert purpose_b.decision_payload.operational_need is None

    with governance_engine.begin() as connection:
        tenant_counts = connection.exec_driver_sql(
            f"select igreja_id, count(*) from {_TABLE} "
            "group by igreja_id order by igreja_id"
        ).all()
        assert tenant_counts == [(IGREJA_A, 1), (IGREJA_B, 1)]
        for role in (
            "anon",
            "authenticated",
            "service_role",
            "agent_runtime",
        ):
            assert connection.exec_driver_sql(
                "select has_table_privilege(%s, %s, 'SELECT')",
                (role, _TABLE),
            ).scalar_one() is False


@pytest.mark.rls_integration
def test_concurrent_same_purpose_update_has_one_winner(
    governance_engine: Engine,
) -> None:
    with Session(governance_engine) as session:
        with session.begin():
            initialize_purpose_consent_governance(
                session,
                igreja_id=IGREJA_A,
                actor_app_user_id=ACTOR_ID,
            )

    barrier = Barrier(2)

    def update(value: str) -> str:
        try:
            with Session(governance_engine) as session:
                with session.begin():
                    barrier.wait(timeout=5)
                    update_purpose_consent_governance_draft(
                        session,
                        igreja_id=IGREJA_A,
                        actor_app_user_id=ACTOR_ID,
                        purpose=PurposeConsentPurpose.COMUNICADOS,
                        expected_revision=1,
                        decision_payload=(
                            normalize_purpose_consent_governance_api_payload(
                                {"operationalNeed": value}
                            )
                        ),
                    )
            return "updated"
        except PurposeConsentGovernanceRevisionConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(update, ("versão A", "versão B")))
    assert outcomes == ["conflict", "updated"]

    with Session(governance_engine) as session:
        snapshot = load_purpose_consent_governance(
            session,
            igreja_id=IGREJA_A,
            actor_app_user_id=ACTOR_ID,
        )
    assert snapshot is not None
    assert snapshot.revision == 2
    communicated = next(
        item
        for item in snapshot.purposes
        if item.purpose is PurposeConsentPurpose.COMUNICADOS
    )
    assert communicated.revision == 2
    assert communicated.decision_payload.operational_need in {
        "versão A",
        "versão B",
    }


@pytest.mark.rls_integration
def test_actor_fk_set_null_and_church_fk_cascades(governance_engine: Engine) -> None:
    with Session(governance_engine) as session:
        with session.begin():
            initialize_purpose_consent_governance(
                session,
                igreja_id=IGREJA_A,
                actor_app_user_id=ACTOR_ID,
            )

    with governance_engine.begin() as connection:
        connection.exec_driver_sql(
            f"delete from {_SCHEMA}.platform_admins where app_user_id=%s",
            (str(ACTOR_ID),),
        )
        connection.exec_driver_sql(
            f"delete from {_SCHEMA}.app_users where id=%s",
            (str(ACTOR_ID),),
        )
        actors = connection.exec_driver_sql(
            f"select created_by_app_user_id, updated_by_app_user_id from {_TABLE} "
            "where igreja_id=%s",
            (str(IGREJA_A),),
        ).one()
        assert tuple(actors) == (None, None)
        connection.exec_driver_sql(
            f"delete from {_SCHEMA}.igrejas where id=%s",
            (str(IGREJA_A),),
        )
        assert connection.exec_driver_sql(
            f"select count(*) from {_TABLE} where igreja_id=%s",
            (str(IGREJA_A),),
        ).scalar_one() == 0
