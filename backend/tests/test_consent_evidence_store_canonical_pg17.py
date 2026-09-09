"""Real UoW/adapter proof on canonical75 plus an isolated history clone."""

import datetime as dt
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from threading import Barrier, Event
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.domain.consent_evidence_store import (
    ConsentChallenge, ConsentEvidencePurpose, ConsentEvidenceChannel,
    ConsentEvidenceLanguage, OpaqueConsentEvidenceIdempotencyKey,
    ConsentEvidenceRequest, ConsentEvidenceAction, TrustedAdultSelfSubject,
    ConsentEvidenceSubjectKind, ConsentEvidenceAgeStatus,
    ConsentEvidenceAuthenticationState, ConsentEvidenceSessionState,
    ConsentEvidenceInteractionIntegrity, ConsentEvidenceChoiceMode,
    TrustedConsentEvidenceAuthority, ConsentEvidenceLedgerState,
)
from app.services.consent_evidence_store import (
    ConsentEvidenceUnitOfWork,
    ConsentEvidenceUnitOfWorkError,
    ConsentEvidenceUnitOfWorkErrorCode,
)
from app.services.consent_evidence_store_postgres import PostgresConsentEvidenceStore
from tests.conftest_rls import rls_database_url as maintenance_database_url, assert_disposable_database


pytestmark = pytest.mark.rls_integration
NOW = dt.datetime(2026, 9, 9, 12, tzinfo=dt.timezone.utc)
TABLES = ("consentimento_desafio", "consentimento_evidencia", "consentimento_recibo")


@pytest.fixture(scope="module")
def rls_database_url(maintenance_database_url):
    """Prepare canonical state ourselves, never depend on another CI job.

    The launcher still receives the maintenance database named postgres.
    All replay source comes from the exact committed private snapshot, not
    from the mutable checkout. Originals of this fixture remain frozen.
    """
    from scripts import new_migration as authoring

    assert_disposable_database(maintenance_database_url)
    admin_url = make_url(maintenance_database_url)
    assert admin_url.host in {"127.0.0.1", "::1"}
    assert admin_url.database == "postgres"
    assert admin_url.username == "postgres"
    assert admin_url.port is not None and 1024 <= admin_url.port <= 65535
    repository = Path(os.environ.get(
        "CONSENT_TEST_SOURCE_REPOSITORY", str(Path(__file__).resolve().parents[2])
    )).absolute()
    git_env = authoring.trusted_snapshot._minimal_git_environment()
    observed_sha = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        env=git_env, text=True, timeout=30,
    ).strip()
    sha = os.environ.get("GITHUB_SHA", observed_sha)
    assert sha == observed_sha, "source SHA differs from checked-out commit"
    snapshot = authoring._create_repository_snapshot(repository_root=repository, git_sha=sha)
    admin = None
    created = False
    database = "migration_catalog_current_head_disposable"
    try:
        assert snapshot.git_sha == sha
        # A dirty fixture must not claim evidence for an older commit.
        relative = "backend/tests/test_consent_evidence_store_canonical_pg17.py"
        assert Path(__file__).read_bytes() == (snapshot.repository / relative).read_bytes()
        replay = snapshot.repository / "backend/scripts/replay_migration_catalog_current_head_pg17.py"
        assert hashlib.sha256(replay.read_bytes()).hexdigest() == (
            "753abf57747de9a28f6192617dfd7ea348cb7adf302d7acbd57f280de3d8ce3f"
        )
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            assert int(connection.execute(text("show server_version_num")).scalar_one()) // 10000 == 17
            assert not connection.execute(text(
                "select exists(select 1 from pg_database where datname=:name)"
            ), {"name": database}).scalar_one()
            connection.exec_driver_sql("create database migration_catalog_current_head_disposable")
            created = True
        target = admin_url.set(database=database)
        child_env = {
            "PATH": os.defpath,
            "PYTHONDONTWRITEBYTECODE": "1",
            "MIGRATION_CATALOG_REPLAY_DATABASE_URL": target.set(drivername="postgresql").render_as_string(hide_password=False),
        }
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(replay), "--confirmation",
             "REPLAY_MIGRATION_CATALOG_CURRENT_HEAD_PG17_DISPOSABLE"],
            cwd=snapshot.repository / "backend", env=child_env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180,
        )
        assert result.returncode == 0, "canonical disposable replay failed (output withheld)"
        assert b"CATALOG_MIGRATION_COUNT=76\n" in result.stdout
        # Restart probes inherit this variable: bind them to this fixture's
        # disposable database, never the maintenance database used to create it.
        with pytest.MonkeyPatch.context() as environment:
            environment.setenv("RLS_TEST_DATABASE_URL", target.render_as_string(hide_password=False))
            yield target.render_as_string(hide_password=False)
    finally:
        if admin is not None:
            try:
                if created:
                    with admin.connect() as connection:
                        connection.exec_driver_sql("drop database migration_catalog_current_head_disposable with (force)")
            finally:
                admin.dispose()
        snapshot.cleanup()


@pytest.fixture
def canonical_engine(rls_database_url):
    assert_disposable_database(rls_database_url)
    url = make_url(rls_database_url)
    assert url.host in {"127.0.0.1", "::1"}
    assert url.database == "migration_catalog_current_head_disposable"
    assert url.username == "postgres"
    engine = create_engine(url, pool_size=5)
    with engine.connect() as connection:
        assert int(connection.execute(text("show server_version_num")).scalar_one()) // 10000 == 17
        # This test intentionally does not construct a simplified fake schema.
        assert connection.execute(text("select to_regclass('public.celula_reuniao')")).scalar_one()
        assert connection.execute(text("select to_regclass('public.consentimento_recibo')")).scalar_one()
    yield engine
    engine.dispose()


@pytest.fixture
def tenants(canonical_engine):
    pairs = [(uuid.uuid4(), uuid.uuid4()), (uuid.uuid4(), uuid.uuid4())]
    with canonical_engine.begin() as connection:
        for tenant, person in pairs:
            connection.execute(text("insert into public.igrejas(id,nome) values(:id,'Igreja Exemplo')"), {"id": tenant})
            connection.execute(text("insert into public.pessoas(id,igreja_id,nome,telefone) "
                                    "values(:id,:tenant,'Pessoa Sintetica',:placeholder)"),
                               {"id": person, "tenant": tenant, "placeholder": "synthetic-" + person.hex})
    try:
        yield pairs
    finally:
        with canonical_engine.begin() as connection:
            for tenant, _person in pairs:
                connection.execute(text("delete from public.igrejas where id=:id"), {"id": tenant})


@pytest.fixture(scope="module")
def historical_database_url(rls_database_url):
    """Clone canonical75+candidate for the explicit historical-writer lab.

    The canonical source is never granted new Pessoa privileges.  PostgreSQL
    requires the source database to have no active sessions while it is used
    as a template, so the administrative connection targets the maintenance
    database instead of the source itself.
    """

    from tests.conftest_rls import assert_disposable_database

    assert_disposable_database(rls_database_url)
    source_url = make_url(rls_database_url)
    assert source_url.host in {"127.0.0.1", "::1"}
    assert source_url.database == "migration_catalog_current_head_disposable"
    assert source_url.username == "postgres"
    child_name = f"consent_evidence_history_{uuid.uuid4().hex[:12]}"
    child_url = source_url.set(database=child_name).render_as_string(
        hide_password=False
    )
    assert_disposable_database(child_url)
    maintenance_url = source_url.set(database="postgres")
    admin_engine = create_engine(
        maintenance_url, future=True, isolation_level="AUTOCOMMIT"
    )
    source_identifier = admin_engine.dialect.identifier_preparer.quote(
        source_url.database
    )
    child_identifier = admin_engine.dialect.identifier_preparer.quote(child_name)
    try:
        with admin_engine.connect() as connection:
            assert (
                int(connection.execute(text("show server_version_num")).scalar_one())
                // 10000
                == 17
            )
            connection.exec_driver_sql(
                f"create database {child_identifier} template {source_identifier}"
            )
        yield child_url
    finally:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(
                "select pg_terminate_backend(pid) from pg_stat_activity "
                "where datname=%s and pid <> pg_backend_pid()",
                (child_name,),
            )
            connection.exec_driver_sql(f"drop database if exists {child_identifier}")
        admin_engine.dispose()


@pytest.fixture(scope="module")
def historical_engine(historical_database_url):
    """Historical lab with Pessoa lock privileges explicit only in the clone."""

    url = make_url(historical_database_url)
    assert url.host in {"127.0.0.1", "::1"}
    assert url.database.startswith("consent_evidence_history_")
    assert url.username == "postgres"
    engine = create_engine(url, future=True, pool_size=5)
    with engine.connect() as connection:
        assert (
            int(connection.execute(text("show server_version_num")).scalar_one())
            // 10000
            == 17
        )
        assert connection.execute(
            text("select to_regclass('public.consentimento_finalidade_evento')")
        ).scalar_one()
        assert connection.execute(
            text("select to_regclass('public.consentimento_recibo')")
        ).scalar_one()
    # This is the only place in the PG proof that adds the legacy writer's
    # required lock privilege.  It is confined to the cloned child database.
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "grant select, update on table public.pessoas to authenticated"
        )
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def historical_tenants(historical_engine):
    pairs = [(uuid.uuid4(), uuid.uuid4()), (uuid.uuid4(), uuid.uuid4())]
    with historical_engine.begin() as connection:
        for tenant, person in pairs:
            connection.execute(
                text("insert into public.igrejas(id,nome) "
                     "values(:id,'Igreja Historica')"),
                {"id": tenant},
            )
            connection.execute(
                text("insert into public.pessoas(id,igreja_id,nome,telefone) "
                     "values(:id,:tenant,'Pessoa Historica',:placeholder)"),
                {
                    "id": person,
                    "tenant": tenant,
                    "placeholder": "historical-" + person.hex,
                },
            )
    try:
        yield pairs
    finally:
        with historical_engine.begin() as connection:
            for tenant, _person in pairs:
                connection.execute(
                    text("delete from public.igrejas where id=:id"),
                    {"id": tenant},
                )


def _request(pair):
    tenant, person = pair
    challenge = ConsentChallenge(
        id=uuid.uuid4(), igreja_id=tenant, pessoa_id=person,
        finalidade=ConsentEvidencePurpose.TAREFAS_OPERACIONAIS,
        package_id=uuid.uuid4(), package_version="synthetic-v1",
        content_digest="1" * 64, catalog_entry_digest="2" * 64,
        notice_text_digest="3" * 64, binding_id=uuid.uuid4(), interaction_id=uuid.uuid4(),
        canal=ConsentEvidenceChannel.PANEL, idioma=ConsentEvidenceLanguage.PT_BR,
        criado_em=NOW, expira_em=NOW + dt.timedelta(minutes=20),
    )
    return ConsentEvidenceRequest(
        desafio=challenge, chave_idempotencia=OpaqueConsentEvidenceIdempotencyKey.generate(),
        apresentada_em=NOW + dt.timedelta(seconds=10),
        manifestada_em=NOW + dt.timedelta(seconds=20), acao=ConsentEvidenceAction.REFUSE_INITIAL,
    )


class SyntheticSource:
    """Independent fixed test observation, not a real provider/authority issuer."""

    def __init__(
        self,
        request,
        *,
        prior_ledger_state=ConsentEvidenceLedgerState.ABSENT,
        prior_event_id=None,
    ):
        names = {item.name for item in fields(TrustedConsentEvidenceAuthority)}
        values = {item.name: getattr(request.desafio, item.name)
                  for item in fields(request.desafio) if item.name in names}
        self.observation = TrustedConsentEvidenceAuthority(
            **values, actor_id=request.desafio.pessoa_id,
            subject=TrustedAdultSelfSubject(
                kind=ConsentEvidenceSubjectKind.ADULT_SELF,
                age_status=ConsentEvidenceAgeStatus.ADULT,
                authentication_state=ConsentEvidenceAuthenticationState.VALID,
                session_state=ConsentEvidenceSessionState.ACTIVE,
                interaction_integrity=ConsentEvidenceInteractionIntegrity.ORIGINAL_DIRECT,
                choice_mode=ConsentEvidenceChoiceMode.EXPLICIT_CONTROL,
            ),
            prior_ledger_state=prior_ledger_state,
            prior_event_id=prior_event_id,
            action=request.acao, presented_at=request.apresentada_em,
            manifested_at=request.manifestada_em,
        )

    def resolve(self, request, *, now):
        return self.observation

    def revalidate(self, request, previous, *, now):
        return self.observation


def _scope(session, tenant, *, readonly=False):
    if readonly:
        session.execute(text("set transaction read only"))
    session.execute(text("set local role authenticated"))
    session.execute(text("select set_config('app.tenant_igreja_id',:tenant,true)"), {"tenant": str(tenant)})


def _uow(session, request, *, source=None):
    return ConsentEvidenceUnitOfWork(
        PostgresConsentEvidenceStore(session),
        source=source or SyntheticSource(request),
        clock=lambda: NOW + dt.timedelta(minutes=1),
    )


def _write(engine, request, *, source=None):
    with Session(engine) as session, session.begin():
        _scope(session, request.desafio.igreja_id)
        return _uow(session, request, source=source).record_initial_refusal(request)


def _withdrawal(engine, request, *, finalidade=None):
    """Call only the existing RETIRADO writer in the isolated history lab."""

    from app.domain.purpose_consent import (
        OpaquePurposeConsentIdempotencyKey,
        PurposeConsentEventState,
        PurposeConsentSource,
        TrustedTermVersion,
    )
    from app.services.purpose_consent import append_purpose_consent_event

    with Session(engine) as session, session.begin():
        _scope(session, request.desafio.igreja_id)
        return _withdrawal_in_session(
            session,
            request,
            finalidade=finalidade,
            append_purpose_consent_event=append_purpose_consent_event,
            event_state=PurposeConsentEventState.RETIRADO,
            term_version=TrustedTermVersion(request.desafio.package_version),
            source=PurposeConsentSource.WHATSAPP_INBOUND,
            key_type=OpaquePurposeConsentIdempotencyKey,
        )


def _withdrawal_in_session(
    session,
    request,
    *,
    finalidade=None,
    append_purpose_consent_event=None,
    event_state=None,
    term_version=None,
    source=None,
    key_type=None,
):
    """Stage a real RETIRADO event while borrowing the caller transaction."""

    if append_purpose_consent_event is None:
        from app.services.purpose_consent import append_purpose_consent_event
    if event_state is None:
        from app.domain.purpose_consent import PurposeConsentEventState
        event_state = PurposeConsentEventState.RETIRADO
    if term_version is None:
        from app.domain.purpose_consent import TrustedTermVersion
        term_version = TrustedTermVersion(request.desafio.package_version)
    if source is None:
        from app.domain.purpose_consent import PurposeConsentSource
        source = PurposeConsentSource.WHATSAPP_INBOUND
    if key_type is None:
        from app.domain.purpose_consent import OpaquePurposeConsentIdempotencyKey
        key_type = OpaquePurposeConsentIdempotencyKey

    event = append_purpose_consent_event(
        session,
        igreja_id=request.desafio.igreja_id,
        pessoa_id=request.desafio.pessoa_id,
        finalidade=finalidade or request.desafio.finalidade,
        estado=event_state,
        versao_termo=term_version,
        fonte=source,
        chave_idempotencia=key_type.generate(),
    )
    return event.id


def _insert_challenge_for_request(connection, request):
    """Seed an OPEN challenge in a test child, never in canonical75 itself."""

    challenge = request.desafio
    connection.execute(
        text(
            "insert into public.consentimento_desafio ("
            "id, igreja_id, pessoa_id, finalidade, package_id, package_version, "
            "content_digest, catalog_entry_digest, notice_text_digest, binding_id, "
            "interaction_id, canal, idioma, criado_em, expira_em, estado, encerrado_em"
            ") values ("
            ":id, :igreja_id, :pessoa_id, :finalidade, :package_id, :package_version, "
            ":content_digest, :catalog_entry_digest, :notice_text_digest, :binding_id, "
            ":interaction_id, :canal, :idioma, :criado_em, :expira_em, 'OPEN', null"
            ")"
        ),
        {
            "id": challenge.id,
            "igreja_id": challenge.igreja_id,
            "pessoa_id": challenge.pessoa_id,
            "finalidade": challenge.finalidade.value,
            "package_id": challenge.package_id,
            "package_version": challenge.package_version,
            "content_digest": challenge.content_digest,
            "catalog_entry_digest": challenge.catalog_entry_digest,
            "notice_text_digest": challenge.notice_text_digest,
            "binding_id": challenge.binding_id,
            "interaction_id": challenge.interaction_id,
            "canal": challenge.canal.value,
            "idioma": challenge.idioma.value,
            "criado_em": challenge.criado_em,
            "expira_em": challenge.expira_em,
        },
    )


def _wait_for_blocked(
    engine,
    *,
    first_pid_box,
    second_pid_box,
    second_started,
    second_done,
    expected_wait_events=None,
):
    """Require PostgreSQL to report the second session blocked by the first.

    A refusal-first operation already owns the stream advisory lock when the
    old writer reaches its trigger.  In the inverse order, the new challenge's
    composite Pessoa FK can be the first wait because the old writer holds its
    Pessoa row lock.  The caller may therefore constrain the observed wait
    event without incorrectly requiring every protocol edge to be advisory.
    """

    assert second_started.wait(timeout=20)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        second_pid = second_pid_box.get("pid")
        first_pid = first_pid_box.get("pid")
        if second_pid is not None and first_pid is not None:
            with engine.connect() as connection:
                wait_type, wait_event, blockers = connection.exec_driver_sql(
                    "select wait_event_type, wait_event, "
                    "pg_catalog.pg_blocking_pids(pid) "
                    "from pg_catalog.pg_stat_activity where pid=%s",
                    (second_pid,),
                ).one()
            if first_pid in (blockers or []):
                if expected_wait_events is None or wait_event in expected_wait_events:
                    assert wait_type == "Lock"
                    return wait_type, wait_event
        if second_done.is_set():
            raise AssertionError(
                "second historical operation completed without waiting for the first lock"
            )
        time.sleep(0.02)
    raise AssertionError("second historical operation never became blocked")


def _run_historical_blocked_pair(
    engine,
    request,
    *,
    first_operation,
    second_operation,
    expected_wait_events=None,
    deletion_as_lab_owner=False,
):
    """Hold the first stream lock until PostgreSQL observes the second waiter."""

    first_staged = Event()
    second_started = Event()
    second_done = Event()
    release_first = Event()
    first_pid_box = {}
    second_pid_box = {}

    def first_worker():
        session = Session(engine)
        transaction = session.begin()
        try:
            _scope(session, request.desafio.igreja_id)
            first_pid_box["pid"] = int(
                session.connection().exec_driver_sql("select pg_backend_pid()").scalar_one()
            )
            value = first_operation(session)
            first_staged.set()
            if not release_first.wait(timeout=20):
                raise AssertionError("first historical transaction was not released")
            transaction.commit()
            return value
        except BaseException as error:
            if transaction.is_active:
                transaction.rollback()
            first_staged.set()
            return error
        finally:
            session.close()

    def second_worker():
        session = Session(engine)
        transaction = session.begin()
        try:
            if not deletion_as_lab_owner:
                _scope(session, request.desafio.igreja_id)
            second_pid_box["pid"] = int(
                session.connection().exec_driver_sql("select pg_backend_pid()").scalar_one()
            )
            second_started.set()
            value = second_operation(session)
            transaction.commit()
            return value
        except BaseException as error:
            if transaction.is_active:
                transaction.rollback()
            return error
        finally:
            second_done.set()
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first_worker)
        assert first_staged.wait(timeout=20)
        second_future = executor.submit(second_worker)
        try:
            _wait_for_blocked(
                engine,
                first_pid_box=first_pid_box,
                second_pid_box=second_pid_box,
                second_started=second_started,
                second_done=second_done,
                expected_wait_events=expected_wait_events,
            )
        finally:
            release_first.set()
        return first_future.result(timeout=30), second_future.result(timeout=30)


def _observe(engine, request):
    with Session(engine) as session, session.begin():
        _scope(session, request.desafio.igreja_id, readonly=True)
        return _uow(session, request).reconcile_initial_refusal(request)


def test_canonical_pg17_uow_commit_and_readonly_observation(canonical_engine, tenants):
    request = _request(tenants[0])
    with Session(canonical_engine) as session, session.begin():
        _scope(session, request.desafio.igreja_id)
        _uow(session, request).record_initial_refusal(request)
        with pytest.raises(RuntimeError, match="readonly observation"):
            PostgresConsentEvidenceStore(session).require_readonly_observation()
        # PostgreSQL itself also forbids changing transaction mode after DML.
        # Do not pretend a SET READ ONLY here can create a fresh observation.
    staged = _write(canonical_engine, request)
    observed = _observe(canonical_engine, request)
    assert observed.status.value == "CONFIRMED"
    assert observed.operation.receipt.id == staged.receipt.id
    replayed = _write(canonical_engine, request)
    assert replayed.replayed is True
    assert replayed.receipt.id == staged.receipt.id
    # A new Python process rehydrates STORAGE rows, not a server-issued key
    # or operational authority. This proves durability across process restart.
    program = '''
import os, uuid
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.services.consent_evidence_store_postgres import PostgresConsentEvidenceStore
engine = create_engine(os.environ['RLS_TEST_DATABASE_URL'])
with Session(engine) as session, session.begin():
    session.execute(text('set transaction read only'))
    session.execute(text('set local role authenticated'))
    session.execute(text("select set_config('app.tenant_igreja_id',:id,true)"), {'id': os.environ['LAB_TENANT']})
    store = PostgresConsentEvidenceStore(session)
    store.require_readonly_observation()
    tenant = uuid.UUID(os.environ['LAB_TENANT'])
    evidence = store.get_evidence_by_idempotency(tenant, os.environ['LAB_KEY'])
    assert evidence is not None
    receipt = store.get_receipt_by_evidence(tenant, evidence.id)
    assert str(receipt.id) == os.environ['LAB_RECEIPT']
    assert receipt.igreja_id == tenant
engine.dispose()
print('STORAGE_REHYDRATED_NO_AUTHORIZATION')
'''
    environment = dict(os.environ, LAB_TENANT=str(request.desafio.igreja_id),
                       LAB_KEY=request.chave_idempotencia.value,
                       LAB_RECEIPT=str(staged.receipt.id))
    restarted = subprocess.run([sys.executable, "-c", program], env=environment,
                               capture_output=True, text=True, timeout=20)
    assert restarted.returncode == 0, restarted.stderr
    assert restarted.stdout.strip() == "STORAGE_REHYDRATED_NO_AUTHORIZATION"


def test_canonical_pg17_uow_rollback_and_ambiguous_commit(canonical_engine, tenants):
    request = _request(tenants[0])
    with Session(canonical_engine) as session:
        with pytest.raises(RuntimeError, match="synthetic rollback"):
            with session.begin():
                _scope(session, request.desafio.igreja_id)
                _uow(session, request).record_initial_refusal(request)
                raise RuntimeError("synthetic rollback")
    assert _observe(canonical_engine, request).status.value == "NOT_FOUND"
    # Simulates loss of the caller's acknowledgement AFTER a real PG commit.
    # The ambiguity is injected, not claimed to be a physical network outage.
    with pytest.raises(ConnectionError, match="synthetic lost acknowledgement"):
        _write(canonical_engine, request)
        raise ConnectionError("synthetic lost acknowledgement")
    canonical_engine.dispose()  # Fresh database connection; no write retry.
    assert _observe(canonical_engine, request).status.value == "CONFIRMED"


def test_canonical_pg17_uow_concurrent_replay(canonical_engine, tenants):
    request = _request(tenants[0])
    barrier = Barrier(2)

    def attempt():
        barrier.wait(timeout=10)
        return _write(canonical_engine, request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(attempt) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert {result.replayed for result in results} == {False, True}
    assert len({result.receipt.id for result in results}) == 1


def test_canonical_pg17_person_cascade_two_tenants(canonical_engine, tenants):
    # This is intentionally a pure canonical replay.  The historical ledger
    # writer still needs Pessoa SELECT/UPDATE privileges that canonical75 does
    # not grant to authenticated; its separate denial proof is below.  The
    # evidence UoW itself follows the E3 protocol without locking Pessoa.
    requests = [_request(pair) for pair in tenants]
    for request in requests:
        _write(canonical_engine, request)
    with canonical_engine.begin() as connection:
        connection.execute(text("delete from public.pessoas where igreja_id=:tenant and id=:person"),
                           {"tenant": tenants[0][0], "person": tenants[0][1]})
        for table in TABLES:
            for index, (tenant, _person) in enumerate(tenants):
                count = connection.execute(text(f"select count(*) from public.{table} where igreja_id=:tenant"),
                                           {"tenant": tenant}).scalar_one()
                assert count == (0 if index == 0 else (2 if table == "consentimento_evidencia" else 1))

        # No E1/E3 path writes the historical ledger.  The B tenant remains
        # untouched by A's Pessoa cascade and has no synthetic ledger seed.
        for tenant in (tenants[0][0], tenants[1][0]):
            assert connection.execute(
                text("select count(*) from public.consentimento_finalidade_evento "
                     "where igreja_id=:tenant"),
                {"tenant": tenant},
            ).scalar_one() == 0


def test_canonical_pg17_historical_ledger_writer_remains_permission_denied(
    canonical_engine, tenants
):
    """Canonical75 keeps the old writer blocked by its existing ACL surface."""

    from app.domain.purpose_consent import (
        OpaquePurposeConsentIdempotencyKey,
        PurposeConsentEventState,
        PurposeConsentSource,
        TrustedTermVersion,
    )
    from app.services.purpose_consent import append_purpose_consent_event

    request = _request(tenants[0])
    with Session(canonical_engine) as session, session.begin():
        _scope(session, request.desafio.igreja_id)
        with pytest.raises(DBAPIError) as raised:
            append_purpose_consent_event(
                session,
                igreja_id=request.desafio.igreja_id,
                pessoa_id=request.desafio.pessoa_id,
                finalidade=ConsentEvidencePurpose.ATENDIMENTO_SOLICITADO,
                estado=PurposeConsentEventState.RETIRADO,
                versao_termo=TrustedTermVersion("synthetic-v1"),
                fonte=PurposeConsentSource.WHATSAPP_INBOUND,
                chave_idempotencia=OpaquePurposeConsentIdempotencyKey.generate(),
            )
        # Document the baseline ACL fact rather than treating a blocked
        # historical writer as an E1/E3 migration failure.
        assert getattr(raised.value.orig, "pgcode", None) == "42501"


def _assert_historical_counts(engine, request, *, challenges, evidence, receipts, ledger):
    with engine.begin() as connection:
        params = {"tenant": request.desafio.igreja_id, "person": request.desafio.pessoa_id}
        assert connection.execute(
            text("select count(*) from public.consentimento_desafio "
                 "where igreja_id=:tenant and pessoa_id=:person"),
            params,
        ).scalar_one() == challenges
        assert connection.execute(
            text("select count(*) from public.consentimento_evidencia "
                 "where igreja_id=:tenant and desafio_id in ("
                 "select id from public.consentimento_desafio "
                 "where igreja_id=:tenant and pessoa_id=:person)"),
            params,
        ).scalar_one() == evidence
        assert connection.execute(
            text("select count(*) from public.consentimento_recibo "
                 "where igreja_id=:tenant and evidencia_id in ("
                 "select evidencia.id from public.consentimento_evidencia evidencia "
                 "join public.consentimento_desafio desafio "
                 "on desafio.igreja_id=evidencia.igreja_id "
                 "and desafio.id=evidencia.desafio_id "
                 "where desafio.igreja_id=:tenant and desafio.pessoa_id=:person)"),
            params,
        ).scalar_one() == receipts
        assert connection.execute(
            text("select count(*) from public.consentimento_finalidade_evento "
                 "where igreja_id=:tenant and pessoa_id=:person"),
            params,
        ).scalar_one() == ledger


def test_historical_pg17_refusal_before_withdrawal_barrier(
    historical_engine, historical_tenants
):
    """A refusal's stream lock blocks a later RETIRADO until commit."""

    request = _request(historical_tenants[0])
    # Use an existing OPEN challenge so the refusal transaction does not hold
    # a Pessoa FK key-share lock before the historical writer reaches its
    # stream trigger.  The observed wait is therefore specifically advisory.
    with historical_engine.begin() as connection:
        _insert_challenge_for_request(connection, request)

    staged, event_id = _run_historical_blocked_pair(
        historical_engine,
        request,
        first_operation=lambda session: _uow(
            session, request
        ).record_initial_refusal(request),
        second_operation=lambda session: _withdrawal_in_session(
            session, request
        ),
        expected_wait_events={"advisory"},
    )
    assert not isinstance(staged, BaseException)
    assert not isinstance(event_id, BaseException)
    assert isinstance(staged.replayed, bool)
    assert staged.replayed is False
    assert isinstance(event_id, uuid.UUID)
    _assert_historical_counts(
        historical_engine, request, challenges=1, evidence=2, receipts=1, ledger=1
    )
    # Reconciliation detects the later stream change; it never claims the
    # original absent-ledger observation is still current.
    assert _observe(historical_engine, request).status.value == "CONFLICT"


def test_historical_pg17_withdrawal_before_refusal_barrier(
    historical_engine, historical_tenants
):
    """A staged withdrawal blocks refusal until the ledger commit is visible."""

    request = _request(historical_tenants[1])

    event_id, rejection = _run_historical_blocked_pair(
        historical_engine,
        request,
        first_operation=lambda session: _withdrawal_in_session(
            session, request
        ),
        # The trusted source was observed before the first transaction
        # committed.  Revalidation after the stream lock must detect the
        # newly committed withdrawal and reject the refusal.
        second_operation=lambda session: _uow(
            session, request
        ).record_initial_refusal(request),
        expected_wait_events={"transactionid", "tuple"},
    )
    assert not isinstance(event_id, BaseException)
    assert isinstance(rejection, ConsentEvidenceUnitOfWorkError)
    assert rejection.code is ConsentEvidenceUnitOfWorkErrorCode.LEDGER_CONFLICT
    _assert_historical_counts(
        historical_engine, request, challenges=0, evidence=0, receipts=0, ledger=1
    )


def test_historical_pg17_person_cascade_preserves_two_tenants_and_ledger(
    historical_engine, historical_tenants
):
    """The real existing ledger and all E3 children cascade only for A."""

    requests = [_request(pair) for pair in historical_tenants]
    for request in requests:
        _write(historical_engine, request)
        # Different purpose keeps the historical withdrawal independent from
        # E1/E3's absent-ledger refusal precondition.
        _withdrawal(
            historical_engine,
            request,
            finalidade=ConsentEvidencePurpose.ATENDIMENTO_SOLICITADO,
        )

    with historical_engine.begin() as connection:
        connection.execute(
            text("delete from public.pessoas where igreja_id=:tenant and id=:person"),
            {"tenant": historical_tenants[0][0], "person": historical_tenants[0][1]},
        )

    _assert_historical_counts(
        historical_engine, requests[0], challenges=0, evidence=0, receipts=0, ledger=0
    )
    _assert_historical_counts(
        historical_engine, requests[1], challenges=1, evidence=2, receipts=1, ledger=1
    )


def _run_concurrent_delete(engine, request, *, existing_challenge):
    if existing_challenge:
        with engine.begin() as connection:
            _insert_challenge_for_request(connection, request)

    def delete_person(session):
        # Existing deletion lifecycle is exercised by the disposable lab owner;
        # no DELETE grant is added to authenticated or to the SQL candidate.
        session.execute(
            text("delete from public.pessoas where igreja_id=:tenant and id=:person"),
            {"tenant": request.desafio.igreja_id, "person": request.desafio.pessoa_id},
        )
        return "deleted"

    return _run_historical_blocked_pair(
        engine, request,
        first_operation=lambda session: _uow(session, request).record_initial_refusal(request),
        second_operation=delete_person,
        expected_wait_events={"transactionid", "tuple"},
        deletion_as_lab_owner=True,
    )


def test_historical_pg17_concurrent_delete_new_challenge_cascades_chain(
    historical_engine, historical_tenants
):
    request = _request(historical_tenants[0])
    staged, deleted = _run_concurrent_delete(
        historical_engine, request, existing_challenge=False
    )
    assert not isinstance(staged, BaseException)
    assert staged.replayed is False
    assert deleted == "deleted"
    _assert_historical_counts(
        historical_engine, request, challenges=0, evidence=0, receipts=0, ledger=0
    )


def test_historical_pg17_concurrent_delete_existing_challenge_cascades_chain(
    historical_engine, historical_tenants
):
    request = _request(historical_tenants[1])
    staged, deleted = _run_concurrent_delete(
        historical_engine, request, existing_challenge=True
    )
    assert not isinstance(staged, BaseException)
    assert staged.replayed is False
    assert deleted == "deleted"
    _assert_historical_counts(
        historical_engine, request, challenges=0, evidence=0, receipts=0, ledger=0
    )
