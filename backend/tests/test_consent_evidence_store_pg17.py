"""PostgreSQL 17 proof for the consent evidence-store laboratory migration.

The fixture below creates a child database from the guarded disposable URL and
builds a deliberately small synthetic parent schema.  It is not a substitute
for the canonical replay: it proves the candidate's own table, FK, RLS and ACL
surface without mutating the canonical database.  The sibling canonical PG17
module owns the historical-ledger clone proof and invokes only the existing
RETIRADO service there, with explicit Pessoa parent grants; this synthetic
module never writes the ledger and no test calls a runtime caller, provider,
network or vault.
"""

from __future__ import annotations

import pathlib
import hashlib
import datetime as dt
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event as sa_event
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.domain.consent_evidence_store import (
    ConsentChallenge,
    ConsentEvidenceAction,
    ConsentEvidenceAgeStatus,
    ConsentEvidenceAuthenticationState,
    ConsentEvidenceChannel,
    ConsentEvidenceChoiceMode,
    ConsentEvidenceInteractionIntegrity,
    ConsentEvidenceLanguage,
    ConsentEvidenceLedgerState,
    ConsentEvidenceRequest,
    ConsentEvidenceSessionState,
    ConsentEvidenceSubjectKind,
    OpaqueConsentEvidenceIdempotencyKey,
    TrustedAdultSelfSubject,
    TrustedConsentEvidenceAuthority,
)
from app.domain.purpose_consent import PurposeConsentPurpose
from app.services.consent_evidence_store import (
    ConsentEvidenceUnitOfWork,
    ConsentEvidenceUnitOfWorkError,
    ConsentEvidenceUnitOfWorkErrorCode,
)
from app.services.consent_evidence_store_postgres import (
    PostgresConsentEvidenceStore,
)

from tests.conftest_rls import assert_disposable_database, rls_database_url


pytestmark = pytest.mark.rls_integration


_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260909_004005_consent_evidence_store_lab.sql"
)
_SCHEMA = "public"
_CHALLENGE = "public.consentimento_desafio"
_EVIDENCE = "public.consentimento_evidencia"
_RECEIPT = "public.consentimento_recibo"
_LEDGER = "public.consentimento_finalidade_evento"

IGREJA_A = "a1000000-0000-0000-0000-000000000001"
IGREJA_B = "b1000000-0000-0000-0000-000000000001"
PESSOA_A = "a1000000-0000-0000-0000-000000000002"
PESSOA_B = "b1000000-0000-0000-0000-000000000002"
PESSOA_C = "a1000000-0000-0000-0000-000000000004"


def _migration_sql() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def _key(label: str) -> str:
    """Build the same opaque persisted shape accepted by the E2 domain."""

    return "ce:v1:" + hashlib.sha256(label.encode("ascii")).hexdigest()


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


def _set_authenticated_tenant(connection: Connection, tenant: str) -> None:
    connection.exec_driver_sql("set local role authenticated")
    connection.exec_driver_sql(
        "select set_config('app.tenant_igreja_id', %s, true)",
        (tenant,),
    )


def _setup_synthetic_base(engine: Engine) -> None:
    """Create synthetic parents and an isolated historical-ledger witness.

    This child deliberately grants the pre-existing Pessoa SELECT/UPDATE
    privileges required by the old RETIRADO writer.  Those grants are test
    infrastructure only; the canonical75 replay remains unmodified and is
    tested separately for the expected 42501 denial.
    """

    ddl = f"""
    create extension if not exists pgcrypto;

    do $$ begin
      if to_regrole('anon') is null then
        create role anon nologin noinherit nobypassrls;
      end if;
      if to_regrole('authenticated') is null then
        create role authenticated nologin noinherit nobypassrls;
      end if;
      if to_regrole('service_role') is null then
        create role service_role nologin noinherit nobypassrls;
      end if;
      if to_regrole('agent_runtime') is null then
        create role agent_runtime nologin noinherit nobypassrls;
      end if;
    end $$;

    create table public.igrejas (
      id uuid primary key,
      nome text not null
    );
    create table public.pessoas (
      id uuid primary key,
      igreja_id uuid not null references public.igrejas(id) on delete cascade,
      nome text not null,
      constraint pessoas_igreja_id_id_key unique (igreja_id, id)
    );
    create table public.app_users (
      id uuid primary key,
      igreja_id uuid not null references public.igrejas(id) on delete cascade,
      clerk_user_id text unique,
      constraint app_users_igreja_id_id_key unique (igreja_id, id)
    );

    create function public.current_igreja_id()
    returns uuid
    language sql
    stable
    security definer
    set search_path = public, pg_temp
    as $function$
      select nullif(current_setting('app.tenant_igreja_id', true), '')::uuid
    $function$;
    grant execute on function public.current_igreja_id() to authenticated;

    -- Synthetic shape of the already-existing ledger.  The candidate must not
    -- create or alter this relation.  Its writer is invoked only through the
    -- existing RETIRADO service in tests below; direct ledger DML is avoided.
    create table public.consentimento_finalidade_evento (
      id uuid primary key default gen_random_uuid(),
      igreja_id uuid not null references public.igrejas(id) on delete cascade,
      pessoa_id uuid not null,
      finalidade text not null,
      estado text not null,
      versao_termo text not null,
      fonte text not null,
      registrado_por_app_user_id uuid,
      chave_idempotencia text not null,
      sequencia bigint not null default 1,
      registrado_em timestamptz not null default clock_timestamp(),
      constraint synthetic_ledger_tenant_id_key unique (igreja_id, id),
      constraint synthetic_ledger_tenant_pessoa_fkey
        foreign key (igreja_id, pessoa_id)
        references public.pessoas (igreja_id, id)
        on delete cascade,
      constraint synthetic_ledger_registered_by_fkey
        foreign key (registrado_por_app_user_id)
        references public.app_users (id)
        on delete set null,
      constraint synthetic_ledger_tenant_registered_by_fkey
        foreign key (igreja_id, registrado_por_app_user_id)
        references public.app_users (igreja_id, id),
      constraint synthetic_ledger_idempotency_key unique
        (igreja_id, chave_idempotencia),
      constraint synthetic_ledger_stream_sequence_key unique
        (igreja_id, pessoa_id, finalidade, sequencia),
      constraint synthetic_ledger_finalidade_check check (
        finalidade in ('atendimento_solicitado', 'cuidado_pastoral',
                       'tarefas_operacionais', 'comunicados')
      ),
      constraint synthetic_ledger_estado_check check (
        estado in ('concedido', 'retirado')
      ),
      constraint synthetic_ledger_fonte_check check (
        fonte in ('whatsapp_inbound', 'painel_autenticado')
      )
    );

    grant usage on schema public
      to anon, authenticated, service_role, agent_runtime;
    grant select, insert, update on table public.pessoas to authenticated;
    grant select on table public.igrejas to authenticated;
    grant select on table public.app_users to authenticated;
    -- Historical lab grants are intentionally broader than canonical75 only
    -- for this child proof of the already-reviewed RETIRADO service path.
    grant select, insert on table public.consentimento_finalidade_evento
      to authenticated;

    insert into public.igrejas (id, nome) values
      ('{IGREJA_A}', 'synthetic A'), ('{IGREJA_B}', 'synthetic B');
    insert into public.pessoas (id, igreja_id, nome) values
      ('{PESSOA_A}', '{IGREJA_A}', 'synthetic person A'),
      ('{PESSOA_B}', '{IGREJA_B}', 'synthetic person B'),
      ('{PESSOA_C}', '{IGREJA_A}', 'synthetic person C');
    insert into public.app_users (id, igreja_id, clerk_user_id) values
      ('a1000000-0000-0000-0000-000000000010', '{IGREJA_A}', 'synthetic-a'),
      ('b1000000-0000-0000-0000-000000000010', '{IGREJA_B}', 'synthetic-b');
    """
    _execute_script(engine, ddl)


@pytest.fixture
def evidence_database_url(rls_database_url: str) -> Iterator[str]:
    """Use one disposable child database per test, independent of test order.

    Keep the D5.1 guard and teardown: each test owns its synthetic parents,
    ledger witness and evidence tables, without weakening any assertion.
    """

    assert_disposable_database(rls_database_url)
    root_url = make_url(rls_database_url)
    assert root_url.host in {"127.0.0.1", "::1"}
    child_name = f"rls_consent_evidence_{uuid.uuid4().hex[:12]}"
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
            assert (
                int(connection.exec_driver_sql("show server_version_num").scalar_one())
                // 10000
                == 17
            )
            connection.exec_driver_sql(
                f"create database {quoted_child} template template0"
            )
        yield child_url
    finally:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(
                "select pg_terminate_backend(pid) from pg_stat_activity "
                "where datname=%s and pid <> pg_backend_pid()",
                (child_name,),
            )
            connection.exec_driver_sql(
                f"drop database if exists {quoted_child}"
            )
        admin_engine.dispose()


@pytest.fixture
def evidence_engine(evidence_database_url: str) -> Iterator[Engine]:
    engine = create_engine(evidence_database_url, future=True, pool_size=8)

    @sa_event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("set search_path to public")
        finally:
            cursor.close()

    _setup_synthetic_base(engine)
    _execute_script(engine, _migration_sql())
    try:
        yield engine
    finally:
        engine.dispose()


def _insert_challenge(
    connection: Connection,
    *,
    tenant: str,
    person: str,
    challenge_id: str | None = None,
    binding_id: str | None = None,
    interaction_id: str | None = None,
) -> str:
    challenge_id = challenge_id or str(uuid.uuid4())
    binding_id = binding_id or str(uuid.uuid4())
    interaction_id = interaction_id or str(uuid.uuid4())
    row = connection.exec_driver_sql(
        f"""
        insert into {_CHALLENGE} (
          id, igreja_id, pessoa_id, finalidade, package_id, package_version,
          content_digest, catalog_entry_digest, notice_text_digest, binding_id,
          interaction_id, canal, idioma, expira_em
        ) values (
          %s, %s, %s, 'atendimento_solicitado', %s, 'lab-v1',
          %s, %s, %s, %s, %s, 'WHATSAPP', 'pt-BR',
          pg_catalog.clock_timestamp() + interval '10 minutes'
        )
        returning id::text
        """,
        (
            challenge_id,
            tenant,
            person,
            str(uuid.uuid4()),
            "a" * 64,
            "b" * 64,
            "c" * 64,
            binding_id,
            interaction_id,
        ),
    ).scalar_one()
    return str(row)


def _insert_presentation(
    connection: Connection,
    *,
    tenant: str,
    challenge_id: str,
    key: str | None = None,
) -> tuple[str, object]:
    key = key or _key(f"presentation:{uuid.uuid4().hex}")
    row = connection.exec_driver_sql(
        f"""
        insert into {_EVIDENCE} (
          igreja_id, desafio_id, tipo, chave_idempotencia, evidence_digest
        ) values (%s, %s, 'PRESENTATION', %s, %s)
        returning id::text, registrado_em
        """,
        (tenant, challenge_id, key, "d" * 64),
    ).one()
    return str(row[0]), row[1]


def _insert_manifestation(
    connection: Connection,
    *,
    tenant: str,
    challenge_id: str,
    presentation_id: str,
    key: str | None = None,
) -> tuple[str, object, str]:
    key = key or _key(f"manifestation:{uuid.uuid4().hex}")
    row = connection.exec_driver_sql(
        f"""
        insert into {_EVIDENCE} (
          igreja_id, desafio_id, tipo, apresentacao_id, acao,
          chave_idempotencia, evidence_digest
        ) values (%s, %s, 'MANIFESTATION', %s, 'REFUSE_INITIAL', %s, %s)
        returning id::text, registrado_em, chave_idempotencia
        """,
        (tenant, challenge_id, presentation_id, key, "e" * 64),
    ).one()
    return str(row[0]), row[1], str(row[2])


def _insert_receipt(
    connection: Connection,
    *,
    tenant: str,
    evidence_id: str,
    key: str,
    registered_at: object,
) -> str:
    row = connection.exec_driver_sql(
        f"""
        insert into {_RECEIPT} (
          igreja_id, evidencia_id, chave_idempotencia, registrado_em,
          acao, schema_version
        ) values (%s, %s, %s, %s, 'REFUSE_INITIAL', 'consent-receipt/lab-v1')
        returning id::text
        """,
        (tenant, evidence_id, key, registered_at),
    ).scalar_one()
    return str(row)


class _SyntheticAuthoritySource:
    """Complete typed source used only to exercise the internal UoW seam."""

    def resolve(
        self, request: ConsentEvidenceRequest, *, now: dt.datetime
    ) -> TrustedConsentEvidenceAuthority:
        return self._authority(request)

    def revalidate(
        self,
        request: ConsentEvidenceRequest,
        previous: TrustedConsentEvidenceAuthority,
        *,
        now: dt.datetime,
    ) -> TrustedConsentEvidenceAuthority:
        return self._authority(request)

    @staticmethod
    def _authority(
        request: ConsentEvidenceRequest,
    ) -> TrustedConsentEvidenceAuthority:
        challenge = request.desafio
        action = request.acao
        return TrustedConsentEvidenceAuthority(
            igreja_id=challenge.igreja_id,
            pessoa_id=challenge.pessoa_id,
            actor_id=challenge.pessoa_id,
            finalidade=challenge.finalidade,
            package_id=challenge.package_id,
            package_version=challenge.package_version,
            content_digest=challenge.content_digest,
            catalog_entry_digest=challenge.catalog_entry_digest,
            notice_text_digest=challenge.notice_text_digest,
            binding_id=challenge.binding_id,
            interaction_id=challenge.interaction_id,
            canal=challenge.canal,
            idioma=challenge.idioma,
            subject=TrustedAdultSelfSubject(
                kind=ConsentEvidenceSubjectKind.ADULT_SELF,
                age_status=ConsentEvidenceAgeStatus.ADULT,
                authentication_state=ConsentEvidenceAuthenticationState.VALID,
                session_state=ConsentEvidenceSessionState.ACTIVE,
                interaction_integrity=ConsentEvidenceInteractionIntegrity.ORIGINAL_DIRECT,
                choice_mode=(
                    ConsentEvidenceChoiceMode.EXPLICIT_CONTROL
                    if action is not None
                    else ConsentEvidenceChoiceMode.PRESENTATION_ONLY
                ),
            ),
            prior_ledger_state=ConsentEvidenceLedgerState.ABSENT,
            action=action,
            presented_at=request.apresentada_em,
            manifested_at=request.manifestada_em,
        )


def _uow_refusal_request() -> ConsentEvidenceRequest:
    created = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)
    challenge = ConsentChallenge(
        id=uuid.uuid4(),
        igreja_id=uuid.UUID(IGREJA_A),
        pessoa_id=uuid.UUID(PESSOA_C),
        finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
        package_id=uuid.uuid4(),
        package_version="lab-v1",
        content_digest="a" * 64,
        catalog_entry_digest="b" * 64,
        notice_text_digest="c" * 64,
        binding_id=uuid.uuid4(),
        interaction_id=uuid.uuid4(),
        canal=ConsentEvidenceChannel.WHATSAPP,
        idioma=ConsentEvidenceLanguage.PT_BR,
        criado_em=created,
        expira_em=created + dt.timedelta(minutes=10),
    )
    return ConsentEvidenceRequest(
        desafio=challenge,
        chave_idempotencia=OpaqueConsentEvidenceIdempotencyKey.generate(),
        apresentada_em=created + dt.timedelta(minutes=1),
        manifestada_em=created + dt.timedelta(minutes=2),
        acao=ConsentEvidenceAction.REFUSE_INITIAL,
    )


def _seed_presentation(
    engine: Engine,
    *,
    suffix: str = "",
    person: str = PESSOA_A,
) -> tuple[str, str]:
    challenge_id = str(uuid.uuid4())
    with engine.begin() as connection:
        challenge_id = _insert_challenge(
            connection,
            tenant=IGREJA_A,
            person=person,
            challenge_id=challenge_id,
            binding_id=str(uuid.uuid4()),
            interaction_id=str(uuid.uuid4()),
        )
        presentation_id, _ = _insert_presentation(
            connection,
            tenant=IGREJA_A,
            challenge_id=challenge_id,
            key=_key(f"presentation:{uuid.uuid4().hex}{suffix}"),
        )
    return challenge_id, presentation_id


def test_evidence_store_pg17_migration_and_acl_contract(
    evidence_engine: Engine,
) -> None:
    sql = _migration_sql().lower()
    assert sql.rstrip().endswith("commit;")
    assert "create table public.consentimento_desafio" in sql
    assert "create table public.consentimento_evidencia" in sql
    assert "create table public.consentimento_recibo" in sql
    assert "insert into public.consentimento_finalidade_evento" not in sql
    assert "alter table public.consentimento_finalidade_evento" not in sql
    assert sql.count("alter table public.consentimento_desafio enable row level security") == 1
    assert sql.count("alter table public.consentimento_evidencia enable row level security") == 1
    assert sql.count("alter table public.consentimento_recibo enable row level security") == 1

    with evidence_engine.begin() as connection:
        relations = connection.exec_driver_sql(
            """
            select relname, relrowsecurity, relforcerowsecurity
              from pg_catalog.pg_class
             where oid in (
               'public.consentimento_desafio'::regclass,
               'public.consentimento_evidencia'::regclass,
               'public.consentimento_recibo'::regclass
             )
             order by relname
            """
        ).all()
        assert relations == [
            ("consentimento_desafio", True, True),
            ("consentimento_evidencia", True, True),
            ("consentimento_recibo", True, True),
        ]

        policy_rows = connection.exec_driver_sql(
            """
            select c.relname, count(*)
              from pg_catalog.pg_class c
              join pg_catalog.pg_policy p on p.polrelid = c.oid
             where c.oid in (
               'public.consentimento_desafio'::regclass,
               'public.consentimento_evidencia'::regclass,
               'public.consentimento_recibo'::regclass
             )
             group by c.relname
             order by c.relname
            """
        ).all()
        assert policy_rows == [
            ("consentimento_desafio", 4),
            ("consentimento_evidencia", 3),
            ("consentimento_recibo", 3),
        ]

        tenant_barriers = connection.exec_driver_sql(
            """
            select c.relname, p.polpermissive, p.polcmd,
                   p.polroles::text,
                   pg_catalog.pg_get_expr(p.polqual, p.polrelid),
                   pg_catalog.pg_get_expr(p.polwithcheck, p.polrelid)
              from pg_catalog.pg_class c
              join pg_catalog.pg_policy p on p.polrelid = c.oid
             where p.polname like '%%_tenant_context_barrier'
             order by c.relname
            """
        ).all()
        assert len(tenant_barriers) == 3
        for relation, permissive, command, roles, using, check in tenant_barriers:
            assert relation in {
                "consentimento_desafio",
                "consentimento_evidencia",
                "consentimento_recibo",
            }
            assert permissive is False
            assert command == "*"
            assert roles == "{0}"
            assert "current_setting('app.tenant_igreja_id'" in using
            assert "current_setting('app.tenant_igreja_id'" in check

        fk_rows = connection.exec_driver_sql(
            """
            select c.conname, c.confdeltype
              from pg_catalog.pg_constraint c
             where c.conrelid in (
               'public.consentimento_desafio'::pg_catalog.regclass,
               'public.consentimento_evidencia'::pg_catalog.regclass,
               'public.consentimento_recibo'::pg_catalog.regclass
             )
               and c.contype = 'f'
             order by c.conname
            """
        ).all()
        assert fk_rows == [
            ("consentimento_desafio_igreja_fkey", "c"),
            ("consentimento_desafio_tenant_pessoa_fkey", "c"),
            ("consentimento_evidencia_apresentacao_fkey", "c"),
            ("consentimento_evidencia_desafio_fkey", "c"),
            ("consentimento_recibo_evidencia_fkey", "c"),
        ]

        for table in (_CHALLENGE, _EVIDENCE, _RECEIPT):
            assert connection.exec_driver_sql(
                "select has_any_column_privilege(%s, %s, 'SELECT') "
                "and has_any_column_privilege(%s, %s, 'INSERT')",
                ("authenticated", table, "authenticated", table),
            ).scalar_one()
            for privilege in ("DELETE", "TRUNCATE"):
                assert not connection.exec_driver_sql(
                    "select has_table_privilege(%s, %s, %s)",
                    ("authenticated", table, privilege),
                ).scalar_one()
            for role in ("anon", "service_role", "agent_runtime"):
                for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
                    assert not connection.exec_driver_sql(
                        "select has_any_column_privilege(%s, %s, %s)",
                        (role, table, privilege),
                    ).scalar_one()

        assert connection.exec_driver_sql(
            "select has_column_privilege(%s, %s, 'estado', 'UPDATE')",
            ("authenticated", _CHALLENGE),
        ).scalar_one()
        assert connection.exec_driver_sql(
            "select has_column_privilege(%s, %s, 'encerrado_em', 'UPDATE')",
            ("authenticated", _CHALLENGE),
        ).scalar_one()
        assert not connection.exec_driver_sql(
            "select has_column_privilege(%s, %s, 'pessoa_id', 'UPDATE')",
            ("authenticated", _CHALLENGE),
        ).scalar_one()
        assert not connection.exec_driver_sql(
            "select has_any_column_privilege(%s, %s, 'UPDATE')",
            ("authenticated", _EVIDENCE),
        ).scalar_one()
        assert not connection.exec_driver_sql(
            "select has_any_column_privilege(%s, %s, 'UPDATE')",
            ("authenticated", _RECEIPT),
        ).scalar_one()
        assert not connection.exec_driver_sql(
            "select has_function_privilege(%s, %s, 'EXECUTE')",
            ("authenticated", "public.consentimento_desafio_validate_write()"),
        ).scalar_one()


def test_evidence_store_pg17_role_and_guc_fail_closed(
    evidence_engine: Engine,
) -> None:
    challenge_id = str(uuid.uuid4())
    with evidence_engine.begin() as connection:
        _insert_challenge(
            connection,
            tenant=IGREJA_A,
            person=PESSOA_A,
            challenge_id=challenge_id,
        )

    with evidence_engine.begin() as connection:
        _set_authenticated_tenant(connection, IGREJA_A)
        assert connection.exec_driver_sql(
            f"select count(*) from {_CHALLENGE}"
        ).scalar_one() == 1

    with evidence_engine.begin() as connection:
        connection.exec_driver_sql("set local role authenticated")
        connection.exec_driver_sql("reset app.tenant_igreja_id")
        assert connection.exec_driver_sql(
            f"select count(*) from {_CHALLENGE}"
        ).scalar_one() == 0
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.exec_driver_sql(
                    f"insert into {_EVIDENCE} "
                    "(igreja_id, desafio_id, tipo, chave_idempotencia, evidence_digest) "
                    "values (%s, %s, 'PRESENTATION', %s, %s)",
                    (IGREJA_A, challenge_id, _key("missing-guc"), "f" * 64),
                )

    with evidence_engine.begin() as connection:
        connection.exec_driver_sql("set local role authenticated")
        connection.exec_driver_sql(
            "select set_config('app.tenant_igreja_id', %s, true)",
            ("not-a-uuid",),
        )
        with pytest.raises(DBAPIError):
            connection.exec_driver_sql(
                f"select count(*) from {_CHALLENGE}"
            )

    with evidence_engine.begin() as connection:
        connection.exec_driver_sql("set local role anon")
        with pytest.raises(DBAPIError):
            connection.exec_driver_sql(f"select count(*) from {_CHALLENGE}")


def test_evidence_store_pg17_cross_tenant_fk_and_dml_isolation(
    evidence_engine: Engine,
) -> None:
    challenge_a = str(uuid.uuid4())
    challenge_b = str(uuid.uuid4())
    with evidence_engine.begin() as connection:
        _insert_challenge(
            connection,
            tenant=IGREJA_A,
            person=PESSOA_A,
            challenge_id=challenge_a,
        )
        _insert_challenge(
            connection,
            tenant=IGREJA_B,
            person=PESSOA_B,
            challenge_id=challenge_b,
        )

    with evidence_engine.begin() as connection:
        _set_authenticated_tenant(connection, IGREJA_A)
        assert connection.exec_driver_sql(
            f"select distinct igreja_id::text from {_CHALLENGE} order by igreja_id"
        ).all() == [(IGREJA_A,)]
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.exec_driver_sql(
                    f"insert into {_EVIDENCE} "
                    "(igreja_id, desafio_id, tipo, chave_idempotencia, evidence_digest) "
                    "values (%s, %s, 'PRESENTATION', %s, %s)",
                    (IGREJA_B, challenge_b, _key("wrong-tenant"), "f" * 64),
                )

    with evidence_engine.begin() as connection:
        _set_authenticated_tenant(connection, IGREJA_B)
        assert connection.exec_driver_sql(
            f"select distinct igreja_id::text from {_CHALLENGE} order by igreja_id"
        ).all() == [(IGREJA_B,)]
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.exec_driver_sql(
                    f"insert into {_EVIDENCE} "
                    "(igreja_id, desafio_id, tipo, chave_idempotencia, evidence_digest) "
                    "values (%s, %s, 'PRESENTATION', %s, %s)",
                    (IGREJA_B, challenge_a, _key("cross-fk"), "f" * 64),
                )


def test_evidence_store_pg17_event_constraints_and_receipt_binding(
    evidence_engine: Engine,
) -> None:
    challenge_id, presentation_id = _seed_presentation(evidence_engine)
    with evidence_engine.begin() as connection:
        _set_authenticated_tenant(connection, IGREJA_A)
        ledger_before = connection.exec_driver_sql(
            f"select count(*) from {_LEDGER} "
            "where igreja_id=%s and pessoa_id=%s",
            (IGREJA_A, PESSOA_A),
        ).scalar_one()
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.exec_driver_sql(
                    f"insert into {_EVIDENCE} "
                    "(igreja_id, desafio_id, tipo, acao, chave_idempotencia, evidence_digest) "
                    "values (%s, %s, 'PRESENTATION', 'REFUSE_INITIAL', %s, %s)",
                    (IGREJA_A, challenge_id, _key("presentation-action"), "f" * 64),
                )

        manifestation_id, registered_at, key = _insert_manifestation(
            connection,
            tenant=IGREJA_A,
            challenge_id=challenge_id,
            presentation_id=presentation_id,
        )
        receipt_id = _insert_receipt(
            connection,
            tenant=IGREJA_A,
            evidence_id=manifestation_id,
            key=key,
            registered_at=registered_at,
        )
        assert receipt_id
        assert connection.exec_driver_sql(
            f"select count(*) from {_LEDGER} "
            "where igreja_id=%s and pessoa_id=%s",
            (IGREJA_A, PESSOA_A),
        ).scalar_one() == ledger_before

    with evidence_engine.begin() as connection:
        _set_authenticated_tenant(connection, IGREJA_A)
        with pytest.raises(DBAPIError):
            connection.exec_driver_sql(
                f"insert into {_RECEIPT} "
                "(igreja_id, evidencia_id, chave_idempotencia, registrado_em, acao, schema_version) "
                "select igreja_id, evidencia_id, chave_idempotencia, registrado_em, "
                "'REFUSE_INITIAL', schema_version from "
                f"{_RECEIPT} where id=%s::uuid",
                (receipt_id,),
            )

    with evidence_engine.begin() as connection:
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.exec_driver_sql(
                    f"update {_CHALLENGE} set estado='OPEN' "
                    "where id=%s::uuid",
                    (challenge_id,),
                )

        connection.exec_driver_sql(
            f"update {_CHALLENGE} set estado='CONSUMED', "
            "encerrado_em=criado_em + interval '1 second' "
            "where id=%s::uuid",
            (challenge_id,),
        )

    # Even the owner cannot rewrite challenge content, while the authorized
    # transition remains conditional on OPEN -> terminal.
    with evidence_engine.begin() as connection:
        with pytest.raises(DBAPIError):
            connection.exec_driver_sql(
                f"update {_CHALLENGE} set finalidade='comunicados' "
                "where id=%s::uuid",
                (challenge_id,),
            )

    # Exercise the actual E2 UoW against the PostgreSQL adapter.  The caller
    # owns the transaction and commits only after the UoW has flushed; the UoW
    # itself has no commit/rollback or ledger writer.
    request = _uow_refusal_request()
    with Session(bind=evidence_engine, future=True) as session:
        session.begin()
        _set_authenticated_tenant(session.connection(), IGREJA_A)
        result = ConsentEvidenceUnitOfWork(
            PostgresConsentEvidenceStore(session),
            source=_SyntheticAuthoritySource(),
            clock=lambda: request.manifestada_em,
        ).record_initial_refusal(request)
        assert result.replayed is False
        assert result.receipt is not None
        session.commit()

    with evidence_engine.begin() as connection:
        assert connection.exec_driver_sql(
            f"select count(*) from {_RECEIPT} where evidencia_id=%s::uuid",
            (str(result.receipt.evidencia_id),),
        ).scalar_one() == 1
        assert connection.exec_driver_sql(
            f"select count(*) from {_LEDGER} where igreja_id=%s and pessoa_id=%s",
            (IGREJA_A, PESSOA_C),
        ).scalar_one() == 0


def test_evidence_store_pg17_person_cascade_preserves_tenant_boundaries(
    evidence_engine: Engine,
) -> None:
    person_a = str(uuid.uuid4())
    person_b = str(uuid.uuid4())
    with evidence_engine.begin() as connection:
        connection.exec_driver_sql(
            "insert into public.pessoas (id, igreja_id, nome) values "
            "(%s::uuid, %s::uuid, 'cascade A'), (%s::uuid, %s::uuid, 'cascade B')",
            (person_a, IGREJA_A, person_b, IGREJA_B),
        )

    challenge_a, presentation_a = _seed_presentation(
        evidence_engine, suffix="a", person=person_a
    )
    challenge_b = str(uuid.uuid4())
    with evidence_engine.begin() as connection:
        _insert_challenge(
            connection,
            tenant=IGREJA_B,
            person=person_b,
            challenge_id=challenge_b,
        )
        presentation_b, _ = _insert_presentation(
            connection,
            tenant=IGREJA_B,
            challenge_id=challenge_b,
            key=_key(f"presentation:{uuid.uuid4().hex}b"),
        )
        manifestation_a, atime, akey = _insert_manifestation(
            connection,
            tenant=IGREJA_A,
            challenge_id=challenge_a,
            presentation_id=presentation_a,
        )
        manifestation_b, btime, bkey = _insert_manifestation(
            connection,
            tenant=IGREJA_B,
            challenge_id=challenge_b,
            presentation_id=presentation_b,
        )
        receipt_a = _insert_receipt(
            connection,
            tenant=IGREJA_A,
            evidence_id=manifestation_a,
            key=akey,
            registered_at=atime,
        )
        receipt_b = _insert_receipt(
            connection,
            tenant=IGREJA_B,
            evidence_id=manifestation_b,
            key=bkey,
            registered_at=btime,
        )

    with evidence_engine.begin() as connection:
        connection.exec_driver_sql(
            "delete from public.pessoas where id=%s::uuid", (person_a,)
        )
        for table, identifier in (
            (_CHALLENGE, challenge_a),
            (_EVIDENCE, presentation_a),
            (_EVIDENCE, manifestation_a),
            (_RECEIPT, receipt_a),
        ):
            assert connection.exec_driver_sql(
                f"select count(*) from {table} where id=%s::uuid",
                (identifier,),
            ).scalar_one() == 0
        assert connection.exec_driver_sql(
            f"select count(*) from {_CHALLENGE} where id=%s::uuid",
            (challenge_b,),
        ).scalar_one() == 1
        assert connection.exec_driver_sql(
            f"select count(*) from {_EVIDENCE} where id in (%s::uuid, %s::uuid)",
            (presentation_b, manifestation_b),
        ).scalar_one() == 2
        assert connection.exec_driver_sql(
            f"select count(*) from {_RECEIPT} where evidencia_id=%s::uuid",
            (manifestation_b,),
        ).scalar_one() == 1
        assert connection.exec_driver_sql(
            f"select count(*) from {_RECEIPT} where id=%s::uuid",
            (receipt_b,),
        ).scalar_one() == 1


class _BothInitialChallengeReadsEmpty(PostgresConsentEvidenceStore):
    """Test seam forcing both UoWs past the same initial empty read."""

    def __init__(self, session: Session, barrier: Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier
        self._waited = False

    def get_challenge(self, igreja_id, desafio_id):
        row = super().get_challenge(igreja_id, desafio_id)
        if row is None and not self._waited:
            self._waited = True
            self._barrier.wait(timeout=20)
        return row


def test_evidence_store_pg17_same_challenge_different_keys_one_fresh_one_conflict(
    evidence_engine: Engine,
) -> None:
    """Two empty reads for one challenge never consume both idempotency keys."""

    request_a = _uow_refusal_request()
    request_b = ConsentEvidenceRequest(
        desafio=request_a.desafio,
        chave_idempotencia=OpaqueConsentEvidenceIdempotencyKey.generate(),
        apresentada_em=request_a.apresentada_em,
        manifestada_em=request_a.manifestada_em,
        acao=request_a.acao,
    )
    barrier = Barrier(2)

    def attempt(request: ConsentEvidenceRequest):
        with Session(bind=evidence_engine, future=True) as session:
            session.begin()
            _set_authenticated_tenant(session.connection(), IGREJA_A)
            store = _BothInitialChallengeReadsEmpty(session, barrier)
            try:
                result = ConsentEvidenceUnitOfWork(
                    store,
                    source=_SyntheticAuthoritySource(),
                    clock=lambda: request.manifestada_em,
                ).record_initial_refusal(request)
                session.commit()
                return "fresh", result
            except ConsentEvidenceUnitOfWorkError as error:
                session.rollback()
                return "conflict", error.code
            except BaseException:
                session.rollback()
                raise

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, (request_a, request_b)))

    assert [item[0] for item in results].count("fresh") == 1
    assert [item[0] for item in results].count("conflict") == 1
    conflict = next(item for item in results if item[0] == "conflict")
    assert conflict[1] in {
        ConsentEvidenceUnitOfWorkErrorCode.IDEMPOTENCY_CONFLICT,
        ConsentEvidenceUnitOfWorkErrorCode.CHALLENGE_CONFLICT,
    }
    winner = next(item for item in results if item[0] == "fresh")[1]
    assert winner.replayed is False
    with evidence_engine.begin() as connection:
        assert connection.exec_driver_sql(
            f"select count(*) from {_CHALLENGE} where id=%s::uuid",
            (str(request_a.desafio.id),),
        ).scalar_one() == 1
        assert connection.exec_driver_sql(
            f"select count(*) from {_RECEIPT} where igreja_id=%s and evidencia_id=%s::uuid",
            (IGREJA_A, str(winner.receipt.evidencia_id)),
        ).scalar_one() == 1
        assert connection.exec_driver_sql(
            f"select count(*) from {_EVIDENCE} "
            "where igreja_id=%s and desafio_id=%s::uuid and tipo='MANIFESTATION'",
            (IGREJA_A, str(request_a.desafio.id)),
        ).scalar_one() == 1
        request_key_rows = connection.exec_driver_sql(
            f"select count(*) from {_EVIDENCE} "
            "where igreja_id=%s and chave_idempotencia=%s",
            (IGREJA_A, request_a.chave_idempotencia.value),
        ).scalar_one() + connection.exec_driver_sql(
            f"select count(*) from {_EVIDENCE} "
            "where igreja_id=%s and chave_idempotencia=%s",
            (IGREJA_A, request_b.chave_idempotencia.value),
        ).scalar_one()
        assert request_key_rows == 1


def test_evidence_store_pg17_concurrent_same_intent_has_one_winner(
    evidence_engine: Engine,
) -> None:
    challenge_id, presentation_id = _seed_presentation(evidence_engine, suffix="race")
    barrier = Barrier(2)
    key = _key("manifestation:concurrent-same-intent")

    def attempt() -> str:
        connection = evidence_engine.connect()
        transaction = connection.begin()
        try:
            _set_authenticated_tenant(connection, IGREJA_A)
            barrier.wait(timeout=20)
            _insert_manifestation(
                connection,
                tenant=IGREJA_A,
                challenge_id=challenge_id,
                presentation_id=presentation_id,
                key=key,
            )
            transaction.commit()
            return "committed"
        except Exception:
            if transaction.is_active:
                transaction.rollback()
            return "conflict"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: attempt(), (1, 2)))

    assert sorted(results) == ["committed", "conflict"]
    with evidence_engine.begin() as connection:
        assert connection.exec_driver_sql(
            f"select count(*) from {_EVIDENCE} "
            "where igreja_id=%s and desafio_id=%s and tipo='MANIFESTATION'",
            (IGREJA_A, challenge_id),
        ).scalar_one() == 1


def test_evidence_store_pg17_rollback_and_reconnect_replay_are_not_success(
    evidence_engine: Engine,
) -> None:
    challenge_id, presentation_id = _seed_presentation(evidence_engine, suffix="rollback")
    connection = evidence_engine.connect()
    transaction = connection.begin()
    try:
        _set_authenticated_tenant(connection, IGREJA_A)
        manifestation_id, registered_at, key = _insert_manifestation(
            connection,
            tenant=IGREJA_A,
            challenge_id=challenge_id,
            presentation_id=presentation_id,
        )
        _insert_receipt(
            connection,
            tenant=IGREJA_A,
            evidence_id=manifestation_id,
            key=key,
            registered_at=registered_at,
        )
        transaction.rollback()
    finally:
        connection.close()

    with evidence_engine.begin() as connection:
        assert connection.exec_driver_sql(
            f"select count(*) from {_EVIDENCE} where desafio_id=%s",
            (challenge_id,),
        ).scalar_one() == 1  # presentation survives; no manifestation exists
        assert connection.exec_driver_sql(
            f"select count(*) from {_RECEIPT} where evidencia_id=%s::uuid",
            (manifestation_id,),
        ).scalar_one() == 0


def test_evidence_store_pg17_restart_reconnect_keeps_committed_receipt(
    evidence_engine: Engine,
) -> None:
    challenge_id, presentation_id = _seed_presentation(evidence_engine, suffix="restart")
    with evidence_engine.begin() as connection:
        _set_authenticated_tenant(connection, IGREJA_A)
        manifestation_id, registered_at, key = _insert_manifestation(
            connection,
            tenant=IGREJA_A,
            challenge_id=challenge_id,
            presentation_id=presentation_id,
        )
        receipt_id = _insert_receipt(
            connection,
            tenant=IGREJA_A,
            evidence_id=manifestation_id,
            key=key,
            registered_at=registered_at,
        )

    # A fresh connection is the laboratory restart/reconciliation seam.  A
    # retry with the same server-owned key conflicts; it is never a second
    # success or an implicit ledger write.
    evidence_engine.dispose()
    restarted_engine = create_engine(evidence_engine.url, future=True)
    try:
        with restarted_engine.begin() as connection:
            _set_authenticated_tenant(connection, IGREJA_A)
            assert connection.exec_driver_sql(
                f"select id::text from {_RECEIPT} where id=%s::uuid",
                (receipt_id,),
            ).scalar_one() == receipt_id
            with pytest.raises(DBAPIError):
                _insert_manifestation(
                    connection,
                    tenant=IGREJA_A,
                    challenge_id=challenge_id,
                    presentation_id=presentation_id,
                    key=key,
                )
    finally:
        restarted_engine.dispose()
