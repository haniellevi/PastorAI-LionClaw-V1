"""PostgreSQL 17 checks for tenant deletion's FK, trigger and grant seams."""

from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.services import tenant_deletion as tenant_deletion_service
from app.services.tenant_deletion import (
    E4bPopulatedError,
    TenantDeletionActor,
    TenantDeletionBlocked,
    TenantResetPermissionError,
    collect_reset_counts,
    delete_tenant_locally,
    load_cleanup_drain_state,
    reset_all_tenants,
    run_pending_cleanup,
)
from scripts import reset_tudo
from tests.conftest_rls import rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration


_SCHEMA = "tenant_deletion_pg17"
_SERVICE_ROLE = "tenant_reset_service_test"
_TENANT_ROLE = "tenant_reset_tenant_test"

_SCHEMA_SQL = f"""
create table igrejas (
  id uuid primary key,
  nome text not null,
  status varchar not null default 'ativa',
  plano text,
  setup_fee_override numeric(10,2),
  dono_id uuid,
  logo_path text,
  created_at timestamptz not null default now()
);

create table pessoas (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id) on delete cascade,
  arquivada_por uuid,
  unique (igreja_id, id)
);

create table app_users (
  id uuid primary key,
  igreja_id uuid references igrejas(id) on delete cascade,
  clerk_user_id text unique,
  pessoa_id uuid,
  celula_pendente_id uuid,
  unique (igreja_id, id),
  constraint app_users_tenant_pessoa_fkey foreign key (igreja_id, pessoa_id)
    references pessoas(igreja_id, id)
);
alter table pessoas add constraint pessoas_tenant_arquivada_por_fkey
  foreign key (igreja_id, arquivada_por)
  references app_users(igreja_id, id);

create table platform_admins (
  id uuid primary key,
  app_user_id uuid not null unique references app_users(id) on delete cascade,
  email text not null,
  created_at timestamptz not null default now()
);

create table planos (
  codigo text primary key,
  preco_mensal numeric(10,2) not null
);

create table schema_migrations (
  versao text primary key
);

create table platform_audit_log (
  id uuid primary key default gen_random_uuid(),
  actor_id uuid,
  actor_email text,
  acao text not null,
  alvo_tipo text not null,
  alvo_id uuid,
  alvo_nome text,
  detalhe jsonb,
  created_at timestamptz not null default now()
);

create table conversations (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id) on delete cascade,
  assumido_por uuid,
  constraint conversations_tenant_assumido_por_fkey foreign key (igreja_id, assumido_por)
    references app_users(igreja_id, id)
);

create table messages (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id) on delete cascade,
  media_path text,
  enviado_por uuid,
  constraint messages_tenant_enviado_por_fkey foreign key (igreja_id, enviado_por)
    references app_users(igreja_id, id)
);

create table consent_records (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id) on delete cascade,
  pessoa_id uuid not null,
  ator_id uuid,
  foreign key (igreja_id, pessoa_id)
    references pessoas(igreja_id, id),
  constraint consent_records_tenant_ator_fkey foreign key (igreja_id, ator_id)
    references app_users(igreja_id, id)
);

create table consentimento_finalidade_evento (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id) on delete cascade,
  pessoa_id uuid not null,
  registrado_por_app_user_id uuid,
  foreign key (igreja_id, pessoa_id)
    references pessoas(igreja_id, id) on delete cascade,
  foreign key (igreja_id, registrado_por_app_user_id)
    references app_users(igreja_id, id)
);
create function consent_event_append_only()
returns trigger language plpgsql as $$
begin
  if pg_trigger_depth() > 1 then
    return old;
  end if;
  raise exception 'consent event is append-only';
end;
$$;
create trigger consent_event_append_only_trigger
before delete on consentimento_finalidade_evento
for each row execute function consent_event_append_only();

create table pessoa_arquivamento_evento (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id) on delete cascade,
  pessoa_id uuid not null references pessoas(id) on delete cascade,
  ator_id uuid references app_users(id) on delete set null
);
create function pessoa_event_append_only()
returns trigger language plpgsql as $$
begin
  if pg_trigger_depth() > 1 then
    return old;
  end if;
  raise exception 'person archive event is append-only';
end;
$$;
create trigger pessoa_event_append_only_trigger
before delete on pessoa_arquivamento_evento
for each row execute function pessoa_event_append_only();

create table user_roles (
  id uuid primary key,
  igreja_id uuid not null references igrejas(id) on delete cascade,
  user_id uuid not null,
  foreign key (igreja_id, user_id) references app_users(igreja_id, id)
);

create table password_reset_tokens (
  id uuid primary key,
  jti uuid not null,
  clerk_user_id text not null,
  expires_at timestamptz not null,
  used_at timestamptz,
  created_at timestamptz not null default now()
);

create table subscriptions (
  id uuid primary key,
  igreja_id uuid not null unique references igrejas(id) on delete cascade,
  plano text not null,
  status varchar,
  pessoas integer,
  limite integer,
  proxima_cobranca date,
  asaas_customer_id text,
  asaas_subscription_id text,
  asaas_customer_external_reference text,
  asaas_subscription_external_reference text,
  asaas_setup_charge_id text,
  asaas_setup_reversed_payment_id text,
  asaas_invoice_url text,
  asaas_setup_invoice_url text,
  asaas_invoice_payment_id text,
  asaas_invoice_reversal text,
  setup_pago boolean not null default false,
  setup_fee_contracted numeric(10,2)
);

create table whatsapp_connections (
  id uuid primary key,
  igreja_id uuid not null unique references igrejas(id) on delete cascade,
  instance text,
  numero text,
  status varchar,
  ultima_sync timestamptz
);
"""


@pytest.fixture
def tenant_deletion_engine(rls_database_url: str) -> Engine:
    admin = create_engine(rls_database_url, future=True)
    with admin.begin() as connection:
        connection.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade")
        connection.exec_driver_sql(f"create schema {_SCHEMA}")
        connection.exec_driver_sql(f"set local search_path to {_SCHEMA}, public")
        connection.exec_driver_sql(_SCHEMA_SQL)
        connection.exec_driver_sql(f"revoke all on all tables in schema {_SCHEMA} from public")
        connection.exec_driver_sql(f"drop role if exists {_SERVICE_ROLE}")
        connection.exec_driver_sql(f"drop role if exists {_TENANT_ROLE}")
        connection.exec_driver_sql(f"create role {_SERVICE_ROLE} nologin bypassrls")
        connection.exec_driver_sql(f"create role {_TENANT_ROLE} nologin nobypassrls")
        connection.exec_driver_sql(f"grant usage on schema {_SCHEMA} to {_SERVICE_ROLE}")
        connection.exec_driver_sql(f"grant usage on schema {_SCHEMA} to {_TENANT_ROLE}")
        connection.exec_driver_sql(
            f"grant select, insert, update, delete on all tables in schema {_SCHEMA} "
            f"to {_SERVICE_ROLE}"
        )
        connection.exec_driver_sql(f"grant select on igrejas to {_TENANT_ROLE}")
    engine = create_engine(
        rls_database_url,
        future=True,
        connect_args={"options": f"-csearch_path={_SCHEMA},public"},
    )
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade")
            connection.exec_driver_sql(f"drop role if exists {_SERVICE_ROLE}")
            connection.exec_driver_sql(f"drop role if exists {_TENANT_ROLE}")
        admin.dispose()


def _seed_graph(
    engine: Engine,
    *,
    suffix: str = "",
    igreja_id: uuid.UUID | None = None,
    include_consent_event: bool = True,
) -> dict[str, uuid.UUID]:
    ids = {
        name: uuid.uuid4()
        for name in ("igreja", "master", "member", "pessoa", "event", "archive_event")
    }
    if igreja_id is not None:
        ids["igreja"] = igreja_id
    label = suffix or str(ids["igreja"])
    with engine.begin() as connection:
        connection.execute(
            text("insert into igrejas (id, nome) values (:id, 'Igreja sintética')"),
            {"id": ids["igreja"]},
        )
        connection.execute(
            text("insert into pessoas (id, igreja_id) values (:id, :igreja_id)"),
            {"id": ids["pessoa"], "igreja_id": ids["igreja"]},
        )
        connection.execute(
            text(
                "insert into app_users (id, igreja_id, clerk_user_id, pessoa_id) "
                "values (:id, :igreja_id, :master_clerk, :pessoa_id), "
                "(:member_id, :igreja_id, :member_clerk, null)"
            ),
            {
                "id": ids["master"],
                "member_id": ids["member"],
                "igreja_id": ids["igreja"],
                "pessoa_id": ids["pessoa"],
                "master_clerk": f"clerk-master-{label}",
                "member_clerk": f"clerk-member-{label}",
            },
        )
        connection.execute(
            text("update pessoas set arquivada_por = :master where id = :pessoa"),
            {"master": ids["master"], "pessoa": ids["pessoa"]},
        )
        connection.execute(
            text("insert into platform_admins (id, app_user_id, email) values (:id, :master, 'master@test')"),
            {"id": uuid.uuid4(), "master": ids["master"]},
        )
        connection.execute(
            text(
                "insert into user_roles (id, igreja_id, user_id) values (:id, :igreja, :master)"
            ),
            {"id": uuid.uuid4(), "igreja": ids["igreja"], "master": ids["master"]},
        )
        connection.execute(
            text(
                "insert into conversations (id, igreja_id, assumido_por) "
                "values (:id, :igreja, :master)"
            ),
            {"id": uuid.uuid4(), "igreja": ids["igreja"], "master": ids["master"]},
        )
        connection.execute(
            text(
                "insert into messages (id, igreja_id, media_path, enviado_por) "
                "values (:id, :igreja, :path, :master)"
            ),
            {
                "id": uuid.uuid4(),
                "igreja": ids["igreja"],
                "path": f"{ids['igreja']}/provider/deadbeef.jpg",
                "master": ids["master"],
            },
        )
        connection.execute(
            text(
                "insert into consent_records (id, igreja_id, pessoa_id, ator_id) "
                "values (:id, :igreja, :pessoa, :master)"
            ),
            {
                "id": uuid.uuid4(),
                "igreja": ids["igreja"],
                "pessoa": ids["pessoa"],
                "master": ids["master"],
            },
        )
        if include_consent_event:
            connection.execute(
                text(
                    "insert into consentimento_finalidade_evento "
                    "(id, igreja_id, pessoa_id, registrado_por_app_user_id) "
                    "values (:id, :igreja, :pessoa, :master)"
                ),
                {
                    "id": ids["event"],
                    "igreja": ids["igreja"],
                    "pessoa": ids["pessoa"],
                    "master": ids["master"],
                },
            )
        connection.execute(
            text(
                "insert into pessoa_arquivamento_evento "
                "(id, igreja_id, pessoa_id, ator_id) "
                "values (:id, :igreja, :pessoa, :master)"
            ),
            {
                "id": ids["archive_event"],
                "igreja": ids["igreja"],
                "pessoa": ids["pessoa"],
                "master": ids["master"],
            },
        )
        connection.execute(
            text(
                "insert into password_reset_tokens (id, jti, clerk_user_id, expires_at) "
                "values (:id, :jti, :clerk_user_id, now())"
            ),
            {
                "id": uuid.uuid4(),
                "jti": uuid.uuid4(),
                "clerk_user_id": f"clerk-member-{label}",
            },
        )
    return ids


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return int(connection.exec_driver_sql(f"select count(*) from {table}").scalar_one())


def test_reset_rejects_tenant_role_before_counts_or_delete(
    tenant_deletion_engine: Engine,
) -> None:
    ids = _seed_graph(tenant_deletion_engine)
    session = Session(tenant_deletion_engine, future=True)
    try:
        session.execute(text(f"set local role {_TENANT_ROLE}"))
        with pytest.raises(TenantResetPermissionError):
            collect_reset_counts(session)
        with pytest.raises(TenantResetPermissionError):
            reset_all_tenants(session, TenantDeletionActor(None, "reset_tudo"))
        session.rollback()
    finally:
        session.close()

    assert _count(tenant_deletion_engine, "igrejas") == 1
    with tenant_deletion_engine.connect() as connection:
        assert connection.execute(
            text("select igreja_id from app_users where id = :id"),
            {"id": ids["master"]},
        ).scalar_one() == ids["igreja"]


def test_delete_cascades_append_only_ledger_and_preserves_explicit_service_grant(
    tenant_deletion_engine: Engine,
) -> None:
    ids = _seed_graph(tenant_deletion_engine)
    with tenant_deletion_engine.connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(
                text("delete from consentimento_finalidade_evento where id = :id"),
                {"id": ids["event"]},
            )
        connection.rollback()
        with pytest.raises(DBAPIError):
            connection.execute(
                text("delete from pessoa_arquivamento_evento where id = :id"),
                {"id": ids["archive_event"]},
            )
        connection.rollback()
        assert connection.execute(
            text("select has_table_privilege(:role, 'app_users', 'SELECT')"),
            {"role": _SERVICE_ROLE},
        ).scalar_one()
        assert connection.execute(
            text("select has_table_privilege(:role, 'app_users', 'UPDATE')"),
            {"role": _SERVICE_ROLE},
        ).scalar_one()

    # The service principal keeps its explicit table grant when app_users is
    # forced through RLS.  The production principal is not asserted here: this
    # is a disposable, synthetic BYPASSRLS role only.
    with tenant_deletion_engine.begin() as connection:
        connection.exec_driver_sql("alter table app_users enable row level security")
        connection.exec_driver_sql("alter table app_users force row level security")
        connection.exec_driver_sql(
            "create policy tenant_deletion_deny_all on app_users "
            "as restrictive for all to public using (false) with check (false)"
        )

    session = Session(tenant_deletion_engine, future=True)
    try:
        session.execute(text(f"set local role {_SERVICE_ROLE}"))
        result = delete_tenant_locally(
            session,
            ids["igreja"],
            TenantDeletionActor(ids["master"], "master@test"),
        )
        session.commit()
    finally:
        session.close()

    assert result.deleted_now is True
    assert _count(tenant_deletion_engine, "igrejas") == 0
    assert _count(tenant_deletion_engine, "consentimento_finalidade_evento") == 0
    assert _count(tenant_deletion_engine, "pessoa_arquivamento_evento") == 0
    assert _count(tenant_deletion_engine, "user_roles") == 0
    assert _count(tenant_deletion_engine, "password_reset_tokens") == 0
    with tenant_deletion_engine.connect() as connection:
        connection.execute(text(f"set local role {_SERVICE_ROLE}"))
        igreja_id = connection.execute(
            text("select igreja_id from app_users where id = :id"),
            {"id": ids["master"]},
        ).scalar_one()
        assert igreja_id is None
        assert connection.execute(text("select count(*) from platform_admins")).scalar_one() == 1
        assert connection.execute(text("select count(*) from platform_audit_log")).scalar_one() >= 2


def test_delete_one_tenant_preserves_other_tenant_and_detached_admin_token(
    tenant_deletion_engine: Engine,
) -> None:
    first = _seed_graph(tenant_deletion_engine, suffix="single-a")
    second = _seed_graph(tenant_deletion_engine, suffix="single-b")
    with tenant_deletion_engine.begin() as connection:
        connection.execute(
            text(
                "insert into password_reset_tokens "
                "(id, jti, clerk_user_id, expires_at) "
                "values (:id, :jti, :clerk_user_id, now())"
            ),
            {
                "id": uuid.uuid4(),
                "jti": uuid.uuid4(),
                "clerk_user_id": "clerk-master-single-a",
            },
        )

    session = Session(tenant_deletion_engine, future=True)
    try:
        result = delete_tenant_locally(
            session,
            first["igreja"],
            TenantDeletionActor(first["master"], "master@test"),
        )
        session.commit()
    finally:
        session.close()

    assert result.deleted_now is True
    assert _count(tenant_deletion_engine, "igrejas") == 1
    assert _count(tenant_deletion_engine, "pessoas") == 1
    with tenant_deletion_engine.connect() as connection:
        assert connection.execute(
            text("select igreja_id from app_users where id = :id"),
            {"id": first["master"]},
        ).scalar_one() is None
        assert connection.execute(
            text("select igreja_id from app_users where id = :id"),
            {"id": second["master"]},
        ).scalar_one() == second["igreja"]
        assert connection.execute(
            text(
                "select count(*) from password_reset_tokens "
                "where clerk_user_id = 'clerk-master-single-a'"
            )
        ).scalar_one() == 1
        assert connection.execute(
            text(
                "select count(*) from password_reset_tokens "
                "where clerk_user_id = 'clerk-member-single-b'"
            )
        ).scalar_one() == 1


@pytest.mark.parametrize("task_kind", ("clerk_user", "storage_media"))
def test_cleanup_claim_commits_before_http_without_blocking_another_tenant(
    tenant_deletion_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    task_kind: str,
) -> None:
    first = _seed_graph(tenant_deletion_engine, suffix="claim-first")
    second = _seed_graph(tenant_deletion_engine, suffix="claim-second")
    actor = TenantDeletionActor(first["master"], "master@test")
    session = Session(tenant_deletion_engine, future=True)
    try:
        local = delete_tenant_locally(session, first["igreja"], actor)
        session.commit()
    finally:
        session.close()
    task = next(task for task in local.pending_tasks if task.kind == task_kind)

    entered_http = threading.Event()
    release_http = threading.Event()
    worker_errors: list[BaseException] = []
    outcomes: list[object] = []
    worker_sessions: list[Session] = []

    class BlockingClerk:
        def __init__(self) -> None:
            self.calls = 0

        def delete_user(self, _clerk_user_id: str) -> None:
            self.calls += 1
            assert not worker_sessions[0].in_transaction()
            entered_http.set()
            assert release_http.wait(timeout=5)

    class BlockingStorage:
        def __init__(self) -> None:
            self.calls = 0

        def remove_tenant_media_namespace(self, _igreja_id, *, before_request) -> None:
            before_request()
            self.calls += 1
            assert not worker_sessions[0].in_transaction()
            entered_http.set()
            assert release_http.wait(timeout=5)

    clerk = BlockingClerk()
    storage = BlockingStorage()
    monkeypatch.setattr(
        tenant_deletion_service,
        "_lock_cleanup_table",
        lambda *_args: pytest.fail("cleanup cannot hold a table lock during HTTP"),
        raising=False,
    )

    def run_first_worker() -> None:
        worker_session = Session(tenant_deletion_engine, future=True)
        worker_sessions.append(worker_session)
        try:
            outcomes.extend(
                run_pending_cleanup(
                    worker_session,
                    actor,
                    (task,),
                    clerk=clerk,
                    evolution=object(),
                    asaas=object(),
                    storage=storage,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            worker_errors.append(exc)
        finally:
            worker_session.close()

    worker = threading.Thread(target=run_first_worker)
    worker.start()
    try:
        assert entered_http.wait(timeout=5)
        with tenant_deletion_engine.begin() as connection:
            connection.execute(text("set local lock_timeout = '250ms'"))
            if task_kind == "clerk_user":
                connection.execute(
                    text(
                        "insert into app_users (id, igreja_id, clerk_user_id) "
                        "values (:id, :igreja_id, :clerk_user_id)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "igreja_id": second["igreja"],
                        "clerk_user_id": "clerk-second-while-http",
                    },
                )
            else:
                connection.execute(
                    text(
                        "insert into messages (id, igreja_id, media_path, enviado_por) "
                        "values (:id, :igreja_id, :media_path, :enviado_por)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "igreja_id": second["igreja"],
                        "media_path": f"{second['igreja']}/provider/while-http.jpg",
                        "enviado_por": second["master"],
                    },
                )

        class DuplicateWorkerClerk:
            def __init__(self) -> None:
                self.calls = 0

            def delete_user(self, _clerk_user_id: str) -> None:
                self.calls += 1

        class DuplicateWorkerStorage:
            def __init__(self) -> None:
                self.calls = 0

            def remove_tenant_media_namespace(
                self, _igreja_id, *, before_request
            ) -> None:
                self.calls += 1

        duplicate = DuplicateWorkerClerk()
        duplicate_storage = DuplicateWorkerStorage()
        second_session = Session(tenant_deletion_engine, future=True)
        try:
            second_outcomes = run_pending_cleanup(
                second_session,
                actor,
                (task,),
                clerk=duplicate,
                evolution=object(),
                asaas=object(),
                storage=duplicate_storage,
            )
        finally:
            second_session.close()
        assert second_outcomes == ()
        assert duplicate.calls == 0
        assert duplicate_storage.calls == 0
    finally:
        release_http.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert worker_errors == []
    assert clerk.calls == (1 if task_kind == "clerk_user" else 0)
    assert storage.calls == (1 if task_kind == "storage_media" else 0)
    assert [outcome.status for outcome in outcomes] == ["done"]
    with tenant_deletion_engine.connect() as connection:
        actions = connection.execute(
            text(
                "select acao from platform_audit_log "
                "where alvo_id = :igreja_id order by created_at, id"
            ),
            {"igreja_id": first["igreja"]},
        ).scalars().all()
    assert "tenant_deletion.cleanup_claimed" in actions
    assert "tenant_deletion.cleanup_done" in actions


def test_cleanup_reclaims_an_expired_lease_and_fences_the_late_owner(
    tenant_deletion_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _seed_graph(tenant_deletion_engine, suffix="expired-lease")
    actor = TenantDeletionActor(ids["master"], "master@test")
    session = Session(tenant_deletion_engine, future=True)
    try:
        local = delete_tenant_locally(session, ids["igreja"], actor)
        session.commit()
    finally:
        session.close()
    task = next(task for task in local.pending_tasks if task.kind == "clerk_user")

    entered_http = threading.Event()
    release_http = threading.Event()
    first_outcomes: list[object] = []

    class BlockingClerk:
        calls = 0

        def delete_user(self, _clerk_user_id: str) -> None:
            self.calls += 1
            entered_http.set()
            assert release_http.wait(timeout=5)

    class WorkingClerk:
        calls = 0

        def delete_user(self, _clerk_user_id: str) -> None:
            self.calls += 1

    monkeypatch.setattr(
        tenant_deletion_service,
        "_lock_cleanup_table",
        lambda *_args: pytest.fail("cleanup cannot hold a table lock during HTTP"),
        raising=False,
    )
    first_clerk = BlockingClerk()

    def run_first_worker() -> None:
        worker_session = Session(tenant_deletion_engine, future=True)
        try:
            first_outcomes.extend(
                run_pending_cleanup(
                    worker_session,
                    actor,
                    (task,),
                    clerk=first_clerk,
                    evolution=object(),
                    asaas=object(),
                    storage=object(),
                )
            )
        finally:
            worker_session.close()

    first_worker = threading.Thread(target=run_first_worker)
    first_worker.start()
    try:
        assert entered_http.wait(timeout=5)
        with tenant_deletion_engine.begin() as connection:
            connection.execute(
                text(
                    "update platform_audit_log "
                    "set detalhe = jsonb_set("
                    "detalhe, '{lease_expires_at}', "
                    "'\"2000-01-01T00:00:00+00:00\"'::jsonb) "
                    "where acao in ("
                    "'tenant_deletion.cleanup_claimed', "
                    "'tenant_deletion.cleanup_lease_renewed') "
                    "and detalhe ->> 'task_id' = :task_id"
                ),
                {"task_id": str(task.task_id)},
            )

        second_clerk = WorkingClerk()
        second_session = Session(tenant_deletion_engine, future=True)
        try:
            second_outcomes = run_pending_cleanup(
                second_session,
                actor,
                (task,),
                clerk=second_clerk,
                evolution=object(),
                asaas=object(),
                storage=object(),
            )
        finally:
            second_session.close()
        assert [outcome.status for outcome in second_outcomes] == ["done"]
        assert second_clerk.calls == 1
    finally:
        release_http.set()
        first_worker.join(timeout=5)

    assert not first_worker.is_alive()
    assert first_clerk.calls == 1
    assert [outcome.status for outcome in first_outcomes] == ["fenced"]
    with tenant_deletion_engine.connect() as connection:
        actions = connection.execute(
            text(
                "select acao from platform_audit_log "
                "where alvo_id = :igreja_id order by created_at, id"
            ),
            {"igreja_id": ids["igreja"]},
        ).scalars().all()
    assert actions.count("tenant_deletion.cleanup_claimed") == 2
    assert actions.count("tenant_deletion.cleanup_done") == 1
    assert "tenant_deletion.cleanup_fenced" in actions


def test_delete_manifest_covers_storage_namespaces_without_database_pointers(
    tenant_deletion_engine: Engine,
) -> None:
    ids = _seed_graph(tenant_deletion_engine, suffix="orphan-namespaces")
    with tenant_deletion_engine.begin() as connection:
        connection.execute(
            text("delete from messages where igreja_id = :igreja_id"),
            {"igreja_id": ids["igreja"]},
        )

    session = Session(tenant_deletion_engine, future=True)
    try:
        result = delete_tenant_locally(
            session,
            ids["igreja"],
            TenantDeletionActor(ids["master"], "master@test"),
        )
        session.rollback()
    finally:
        session.close()

    assert {task.kind for task in result.pending_tasks} >= {
        "storage_media",
        "storage_logo",
    }


def test_absent_tenant_reconstructs_durable_cleanup_until_terminal(
    tenant_deletion_engine: Engine,
) -> None:
    ids = _seed_graph(tenant_deletion_engine, suffix="cleanup")

    class FailingThenWorkingClerk:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.fails = True

        def delete_user(self, clerk_user_id: str) -> None:
            self.calls.append(clerk_user_id)
            if self.fails:
                raise RuntimeError("synthetic clerk outage")

    class RecordingStorage:
        def __init__(self) -> None:
            self.media_calls: list[list[object]] = []
            self.logo_calls: list[list[object]] = []

        def remove_tenant_media_namespace(self, _igreja_id, *, before_request) -> None:
            before_request()
            self.media_calls.append([])

        def remove_tenant_logos_namespace(self, _igreja_id, *, before_request) -> None:
            before_request()
            self.logo_calls.append([])

    actor = TenantDeletionActor(ids["master"], "master@test")
    clerk = FailingThenWorkingClerk()
    storage = RecordingStorage()
    session = Session(tenant_deletion_engine, future=True)
    try:
        initial = delete_tenant_locally(session, ids["igreja"], actor)
        clerk_task = next(task for task in initial.pending_tasks if task.kind == "clerk_user")
        session.commit()
    finally:
        session.close()

    session = Session(tenant_deletion_engine, future=True)
    try:
        drained = load_cleanup_drain_state(session)
        session.rollback()
    finally:
        session.close()
    assert {task.task_id: task for task in drained.pending_tasks} == {
        task.task_id: task for task in initial.pending_tasks
    }
    assert drained.rejected_tasks == ()

    session = Session(tenant_deletion_engine, future=True)
    try:
        first_outcomes = run_pending_cleanup(
            session,
            actor,
            initial.pending_tasks,
            clerk=clerk,
            evolution=object(),
            asaas=object(),
            storage=storage,
        )
    finally:
        session.close()

    assert [outcome.status for outcome in first_outcomes] == ["pending", "done", "done"]
    assert clerk.calls == ["clerk-member-cleanup"]
    assert len(storage.media_calls) == 1
    assert len(storage.logo_calls) == 1
    with tenant_deletion_engine.connect() as connection:
        assert connection.execute(
            text(
                "select count(*) from platform_audit_log "
                "where acao = 'tenant_deletion.cleanup_retry'"
            )
        ).scalar_one() == 1

    session = Session(tenant_deletion_engine, future=True)
    try:
        after_failure = load_cleanup_drain_state(session)
        session.rollback()
    finally:
        session.close()
    assert after_failure.pending_tasks == (clerk_task,)
    assert after_failure.rejected_tasks == ()

    session = Session(tenant_deletion_engine, future=True)
    try:
        recovered = delete_tenant_locally(session, ids["igreja"], actor)
        assert recovered.deleted_now is False
        assert recovered.pending_tasks == (clerk_task,)
        clerk.fails = False
        second_outcomes = run_pending_cleanup(
            session,
            actor,
            recovered.pending_tasks,
            clerk=clerk,
            evolution=object(),
            asaas=object(),
            storage=storage,
        )
    finally:
        session.close()

    assert [outcome.status for outcome in second_outcomes] == ["done"]
    session = Session(tenant_deletion_engine, future=True)
    try:
        after_success = load_cleanup_drain_state(session)
        session.rollback()
    finally:
        session.close()
    assert after_success.pending_tasks == ()
    assert after_success.rejected_tasks == ()
    session = Session(tenant_deletion_engine, future=True)
    try:
        third = delete_tenant_locally(session, ids["igreja"], actor)
        third_outcomes = run_pending_cleanup(
            session,
            actor,
            third.pending_tasks,
            clerk=clerk,
            evolution=object(),
            asaas=object(),
            storage=storage,
        )
    finally:
        session.close()

    assert third.deleted_now is False
    assert third.pending_tasks == ()
    assert third_outcomes == ()
    assert clerk.calls == ["clerk-member-cleanup", "clerk-member-cleanup"]


def test_cli_reapplies_public_search_path_after_each_cleanup_commit(
    tenant_deletion_engine: Engine,
) -> None:
    session = Session(tenant_deletion_engine, future=True)
    try:
        for _ in range(2):
            reset_tudo._set_public_search_path(session)
            assert session.execute(
                text("select current_schemas(false)")
            ).scalar_one() == ["public"]
            session.commit()
            assert session.execute(
                text("select current_schemas(false)")
            ).scalar_one() == [_SCHEMA, "public"]
            session.rollback()
    finally:
        session.close()


def test_local_failure_rolls_back_manifest_and_all_tenant_mutations(
    tenant_deletion_engine: Engine,
) -> None:
    ids = _seed_graph(tenant_deletion_engine)
    with tenant_deletion_engine.begin() as connection:
        connection.exec_driver_sql(
            """
            create function reject_tenant_delete()
            returns trigger language plpgsql as $$
            begin
              raise exception 'synthetic local delete failure';
            end;
            $$;
            create trigger reject_tenant_delete_trigger
            before delete on igrejas
            for each row execute function reject_tenant_delete();
            """
        )

    session = Session(tenant_deletion_engine, future=True)
    try:
        with pytest.raises(DBAPIError):
            delete_tenant_locally(
                session,
                ids["igreja"],
                TenantDeletionActor(ids["master"], "master@test"),
            )
        session.rollback()
    finally:
        session.close()

    assert _count(tenant_deletion_engine, "igrejas") == 1
    assert _count(tenant_deletion_engine, "pessoas") == 1
    assert _count(tenant_deletion_engine, "messages") == 1
    assert _count(tenant_deletion_engine, "platform_audit_log") == 0
    with tenant_deletion_engine.connect() as connection:
        assert connection.execute(
            text("select igreja_id from app_users where id = :id"),
            {"id": ids["master"]},
        ).scalar_one() == ids["igreja"]


def test_reset_all_tenants_preserves_platform_and_schema_relations(
    tenant_deletion_engine: Engine,
) -> None:
    first = _seed_graph(
        tenant_deletion_engine,
        suffix="reset-a",
        igreja_id=uuid.UUID("00000000-0000-0000-0000-000000000101"),
        include_consent_event=False,
    )
    second = _seed_graph(
        tenant_deletion_engine,
        suffix="reset-b",
        igreja_id=uuid.UUID("00000000-0000-0000-0000-000000000102"),
        include_consent_event=False,
    )
    with tenant_deletion_engine.begin() as connection:
        connection.execute(
            text("insert into planos (codigo, preco_mensal) values ('plataforma', 1)"),
        )
        connection.execute(
            text("insert into schema_migrations (versao) values ('synthetic-1')"),
        )
        connection.execute(
            text(
                "insert into platform_audit_log "
                "(acao, alvo_tipo, alvo_nome) values "
                "('platform_prior', 'plataforma', 'before-reset')"
            )
        )

    session = Session(tenant_deletion_engine, future=True)
    try:
        result = reset_all_tenants(
            session, TenantDeletionActor(None, "reset_tudo")
        )
        session.commit()
    finally:
        session.close()

    assert result.igrejas_deleted == 2
    assert _count(tenant_deletion_engine, "igrejas") == 0
    assert _count(tenant_deletion_engine, "pessoas") == 0
    assert _count(tenant_deletion_engine, "user_roles") == 0
    assert _count(tenant_deletion_engine, "platform_admins") == 2
    assert _count(tenant_deletion_engine, "planos") == 1
    assert _count(tenant_deletion_engine, "schema_migrations") == 1
    with tenant_deletion_engine.connect() as connection:
        assert connection.execute(
            text("select count(*) from app_users where igreja_id is null")
        ).scalar_one() == 2
        assert connection.execute(
            text("select count(*) from platform_audit_log where acao = 'platform_prior'")
        ).scalar_one() == 1
        assert connection.execute(
            text("select to_regnamespace(:schema)"), {"schema": _SCHEMA}
        ).scalar_one() is not None
        for ids in (first, second):
            assert connection.execute(
                text("select pessoa_id from app_users where id = :id"),
                {"id": ids["master"]},
            ).scalar_one() is None


def test_reset_all_tenants_counts_existing_pending_cleanup_on_second_run(
    tenant_deletion_engine: Engine,
) -> None:
    _seed_graph(
        tenant_deletion_engine,
        suffix="reset-pending-replay",
        include_consent_event=False,
    )

    session = Session(tenant_deletion_engine, future=True)
    try:
        first = reset_all_tenants(session, TenantDeletionActor(None, "reset_tudo"))
        session.commit()
    finally:
        session.close()

    assert first.igrejas_deleted == 1
    assert first.pending_tasks > 0
    audit_events_after_first = _count(tenant_deletion_engine, "platform_audit_log")

    session = Session(tenant_deletion_engine, future=True)
    try:
        second = reset_all_tenants(session, TenantDeletionActor(None, "reset_tudo"))
        state = load_cleanup_drain_state(session)
        session.commit()
    finally:
        session.close()

    assert second.igrejas_deleted == 0
    assert second.pending_tasks == first.pending_tasks
    assert len(state.pending_tasks) == first.pending_tasks
    assert _count(tenant_deletion_engine, "platform_audit_log") == audit_events_after_first


@pytest.mark.parametrize("create_empty_table", (False, True))
def test_reset_allows_absent_or_empty_e4b_tables(
    tenant_deletion_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    create_empty_table: bool,
) -> None:
    _seed_graph(
        tenant_deletion_engine,
        suffix="e4b-empty",
        include_consent_event=False,
    )
    # Runtime enumerates public. The fixture uses one disposable schema, so
    # replace only this namespace seam; all SQL persistence stays real.
    monkeypatch.setattr(tenant_deletion_service, "_E4B_SCHEMA", _SCHEMA)
    if create_empty_table:
        with tenant_deletion_engine.begin() as connection:
            connection.exec_driver_sql(
                "create table e4b_empty_reset ("
                "id uuid primary key, igreja_id uuid not null references igrejas(id)"
                ")"
            )

    session = Session(tenant_deletion_engine, future=True)
    try:
        assert collect_reset_counts(session).igrejas == 1
        session.rollback()
        result = reset_all_tenants(session, TenantDeletionActor(None, "reset_tudo"))
        session.commit()
    finally:
        session.close()

    assert result.igrejas_deleted == 1
    assert _count(tenant_deletion_engine, "igrejas") == 0
    assert _count(tenant_deletion_engine, "platform_audit_log") >= 2


def test_reset_blocks_all_populated_e4b_tables_before_dml(
    tenant_deletion_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _seed_graph(
        tenant_deletion_engine,
        suffix="e4b-first",
        include_consent_event=False,
    )
    second = _seed_graph(
        tenant_deletion_engine,
        suffix="e4b-second",
        include_consent_event=False,
    )
    # Runtime enumerates public. The fixture uses one disposable schema, so
    # replace only this namespace seam; all SQL persistence stays real.
    monkeypatch.setattr(tenant_deletion_service, "_E4B_SCHEMA", _SCHEMA)
    with tenant_deletion_engine.begin() as connection:
        connection.exec_driver_sql(
            "create table e4b_holds ("
            "id uuid primary key, igreja_id uuid not null references igrejas(id)"
            ")"
        )
        connection.exec_driver_sql(
            "create table e4b_second_tenant ("
            "id uuid primary key, igreja_id uuid not null references igrejas(id)"
            ")"
        )
        connection.execute(
            text("insert into e4b_holds (id, igreja_id) values (:id, :igreja)"),
            {"id": uuid.uuid4(), "igreja": first["igreja"]},
        )
        connection.execute(
            text(
                "insert into e4b_second_tenant (id, igreja_id) "
                "values (:id, :igreja)"
            ),
            {"id": uuid.uuid4(), "igreja": second["igreja"]},
        )

    session = Session(tenant_deletion_engine, future=True)
    try:
        with pytest.raises(E4bPopulatedError) as preflight:
            collect_reset_counts(session)
        assert preflight.value.table_counts == {
            "e4b_holds": 1,
            "e4b_second_tenant": 1,
        }
        session.rollback()
        with pytest.raises(E4bPopulatedError) as execution:
            reset_all_tenants(session, TenantDeletionActor(None, "reset_tudo"))
        assert execution.value.table_counts == preflight.value.table_counts
        session.rollback()
    finally:
        session.close()

    assert _count(tenant_deletion_engine, "igrejas") == 2
    assert _count(tenant_deletion_engine, "pessoas") == 2
    assert _count(tenant_deletion_engine, "platform_audit_log") == 0
    assert _count(tenant_deletion_engine, "e4b_holds") == 1
    assert _count(tenant_deletion_engine, "e4b_second_tenant") == 1
    with tenant_deletion_engine.connect() as connection:
        for ids in (first, second):
            assert connection.execute(
                text("select igreja_id from app_users where id = :id"),
                {"id": ids["master"]},
            ).scalar_one() == ids["igreja"]


def test_reset_rechecks_e4b_after_dry_run_before_any_delete(
    tenant_deletion_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _seed_graph(
        tenant_deletion_engine,
        suffix="e4b-recheck-first",
        include_consent_event=False,
    )
    second = _seed_graph(
        tenant_deletion_engine,
        suffix="e4b-recheck-second",
        include_consent_event=False,
    )
    # Runtime enumerates public. The fixture uses one disposable schema, so
    # replace only this namespace seam; all SQL persistence stays real.
    monkeypatch.setattr(tenant_deletion_service, "_E4B_SCHEMA", _SCHEMA)
    with tenant_deletion_engine.begin() as connection:
        connection.exec_driver_sql(
            "create table e4b_after_dry_run ("
            "id uuid primary key, igreja_id uuid not null references igrejas(id)"
            ")"
        )

    session = Session(tenant_deletion_engine, future=True)
    try:
        assert collect_reset_counts(session).igrejas == 2
        session.rollback()
        with tenant_deletion_engine.begin() as connection:
            connection.execute(
                text(
                    "insert into e4b_after_dry_run (id, igreja_id) "
                    "values (:id, :igreja)"
                ),
                {"id": uuid.uuid4(), "igreja": second["igreja"]},
            )
        with pytest.raises(E4bPopulatedError) as blocked:
            reset_all_tenants(session, TenantDeletionActor(None, "reset_tudo"))
        assert blocked.value.table_counts == {"e4b_after_dry_run": 1}
        session.rollback()
    finally:
        session.close()

    assert _count(tenant_deletion_engine, "igrejas") == 2
    assert _count(tenant_deletion_engine, "platform_audit_log") == 0
    assert _count(tenant_deletion_engine, "e4b_after_dry_run") == 1
    assert first["igreja"] != second["igreja"]


def test_reset_blocks_populated_consent_ledger_before_any_dml(
    tenant_deletion_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _seed_graph(tenant_deletion_engine, suffix="ledger-reset-first")
    second = _seed_graph(tenant_deletion_engine, suffix="ledger-reset-second")
    # The CLI fixes public; this PG fixture keeps its disposable schema by
    # replacing only the catalog namespace used by the reset guard.
    monkeypatch.setattr(tenant_deletion_service, "_E4B_SCHEMA", _SCHEMA)

    session = Session(tenant_deletion_engine, future=True)
    try:
        with pytest.raises(E4bPopulatedError) as preflight:
            collect_reset_counts(session)
        assert preflight.value.table_counts == {"consentimento_finalidade_evento": 2}
        session.rollback()
        with pytest.raises(E4bPopulatedError) as execution:
            reset_all_tenants(session, TenantDeletionActor(None, "reset_tudo"))
        assert execution.value.table_counts == preflight.value.table_counts
        session.rollback()
    finally:
        session.close()

    assert _count(tenant_deletion_engine, "igrejas") == 2
    assert _count(tenant_deletion_engine, "consentimento_finalidade_evento") == 2
    assert _count(tenant_deletion_engine, "platform_audit_log") == 0
    with tenant_deletion_engine.connect() as connection:
        for ids in (first, second):
            assert connection.execute(
                text("select igreja_id from app_users where id = :id"),
                {"id": ids["master"]},
            ).scalar_one() == ids["igreja"]


def test_reset_rolls_back_the_first_tenant_when_the_second_delete_fails(
    tenant_deletion_engine: Engine,
) -> None:
    first = _seed_graph(
        tenant_deletion_engine,
        suffix="rollback-a",
        igreja_id=uuid.UUID("00000000-0000-0000-0000-000000000201"),
        include_consent_event=False,
    )
    second = _seed_graph(
        tenant_deletion_engine,
        suffix="rollback-b",
        igreja_id=uuid.UUID("00000000-0000-0000-0000-000000000202"),
        include_consent_event=False,
    )
    with tenant_deletion_engine.begin() as connection:
        connection.exec_driver_sql(
            f"""
            create function reject_second_reset_delete()
            returns trigger language plpgsql as $$
            begin
              if old.id = '{second["igreja"]}'::uuid then
                raise exception 'synthetic second delete failure';
              end if;
              return old;
            end;
            $$;
            create trigger reject_second_reset_delete_trigger
            before delete on igrejas
            for each row execute function reject_second_reset_delete();
            """
        )

    session = Session(tenant_deletion_engine, future=True)
    try:
        with pytest.raises(DBAPIError):
            reset_all_tenants(session, TenantDeletionActor(None, "reset_tudo"))
        session.rollback()
    finally:
        session.close()

    assert _count(tenant_deletion_engine, "igrejas") == 2
    assert _count(tenant_deletion_engine, "pessoas") == 2
    assert _count(tenant_deletion_engine, "platform_audit_log") == 0
    with tenant_deletion_engine.connect() as connection:
        for ids in (first, second):
            assert connection.execute(
                text("select igreja_id from app_users where id = :id"),
                {"id": ids["master"]},
            ).scalar_one() == ids["igreja"]


def test_delete_skips_generic_e4b_rows_owned_by_another_tenant(
    tenant_deletion_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _seed_graph(tenant_deletion_engine, suffix="e4b-delete-first")
    second = _seed_graph(tenant_deletion_engine, suffix="e4b-delete-second")
    monkeypatch.setattr(tenant_deletion_service, "_E4B_SCHEMA", _SCHEMA)
    with tenant_deletion_engine.begin() as connection:
        connection.exec_driver_sql(
            "create table e4b_tenant_guard ("
            "id uuid primary key, igreja_id uuid not null"
            ")"
        )
        connection.execute(
            text("insert into e4b_tenant_guard (id, igreja_id) values (:id, :igreja)"),
            {"id": uuid.uuid4(), "igreja": second["igreja"]},
        )

    session = Session(tenant_deletion_engine, future=True)
    try:
        result = delete_tenant_locally(
            session,
            first["igreja"],
            TenantDeletionActor(first["master"], "master@test"),
        )
        session.commit()
    finally:
        session.close()

    assert result.deleted_now is True
    session = Session(tenant_deletion_engine, future=True)
    try:
        with pytest.raises(E4bPopulatedError) as blocked:
            delete_tenant_locally(
                session,
                second["igreja"],
                TenantDeletionActor(second["master"], "master@test"),
            )
        assert blocked.value.table_counts == {"e4b_tenant_guard": 1}
        session.rollback()
    finally:
        session.close()

    assert _count(tenant_deletion_engine, "igrejas") == 1
    with tenant_deletion_engine.connect() as connection:
        assert connection.execute(
            text("select igreja_id from app_users where id = :id"),
            {"id": second["master"]},
        ).scalar_one() == second["igreja"]
        assert connection.execute(
            text(
                "select count(*) from platform_audit_log "
                "where alvo_id = :igreja"
            ),
            {"igreja": second["igreja"]},
        ).scalar_one() == 0


def test_delete_blocks_populated_generic_e4b_table_without_tenant_column(
    tenant_deletion_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _seed_graph(tenant_deletion_engine, suffix="e4b-unknown")
    monkeypatch.setattr(tenant_deletion_service, "_E4B_SCHEMA", _SCHEMA)
    with tenant_deletion_engine.begin() as connection:
        connection.exec_driver_sql("create table e4b_unknown_guard (id uuid primary key)")
        connection.execute(
            text("insert into e4b_unknown_guard (id) values (:id)"),
            {"id": uuid.uuid4()},
        )

    session = Session(tenant_deletion_engine, future=True)
    try:
        with pytest.raises(E4bPopulatedError) as blocked:
            delete_tenant_locally(
                session,
                ids["igreja"],
                TenantDeletionActor(ids["master"], "master@test"),
            )
        assert blocked.value.table_counts == {"e4b_unknown_guard": 1}
        session.rollback()
    finally:
        session.close()

    assert _count(tenant_deletion_engine, "igrejas") == 1
    assert _count(tenant_deletion_engine, "platform_audit_log") == 0


def test_e4b_rows_block_before_manifest_or_local_delete(
    tenant_deletion_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _seed_graph(tenant_deletion_engine)
    monkeypatch.setattr(tenant_deletion_service, "_E4B_SCHEMA", _SCHEMA)
    with tenant_deletion_engine.begin() as connection:
        connection.exec_driver_sql(
            """
            create table e4b_consent_operations (
              igreja_id uuid primary key references igrejas(id) on delete restrict
            );
            create function immutable_e4b_operation()
            returns trigger language plpgsql as $$
            begin
              raise exception 'immutable E4B operation' using errcode = 'P0001';
            end;
            $$;
            create trigger immutable_e4b_operation_trigger
            before update or delete on e4b_consent_operations
            for each row execute function immutable_e4b_operation();
            """
        )
        connection.execute(
            text("insert into e4b_consent_operations (igreja_id) values (:igreja)"),
            {"igreja": ids["igreja"]},
        )
    with tenant_deletion_engine.connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(
                text("delete from e4b_consent_operations where igreja_id = :igreja"),
                {"igreja": ids["igreja"]},
            )
        connection.rollback()

    session = Session(tenant_deletion_engine, future=True)
    try:
        with pytest.raises(TenantDeletionBlocked):
            delete_tenant_locally(
                session,
                ids["igreja"],
                TenantDeletionActor(ids["master"], "master@test"),
            )
        session.rollback()
    finally:
        session.close()

    assert _count(tenant_deletion_engine, "igrejas") == 1
    assert _count(tenant_deletion_engine, "platform_audit_log") == 0
