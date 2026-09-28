"""PG17 proof for V3 consolidation assignment and canonical fonovisita work."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import threading
from urllib.parse import urlsplit
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app.db.session  # noqa: F401 - registers the tenant-session listener
from app.db.tenant_session import mark_tenant_scoped
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.routers.pipeline import (
    AdvanceStageRequest,
    FonovisitaRequest,
    advance_stage,
    queue_fonovisita,
)
from app.routers.work_queue import ActionRequest, _get_item_in_scope, act_on_item
from app.services.consolidation_workflow import (
    assign_consolidacao,
    complete_fonovisita,
)
from app.services.ministerial_actions import register_decision
from tests.conftest_rls import assert_disposable_database
from tests.test_whatsapp_consolidation_v3_migration_pg import (
    _MIGRATION as _V3_MIGRATION,
    _apply as _apply_v3_migration,
    v3_database as _v3_database,
)


pytestmark = pytest.mark.rls_integration


def _workflow_database_url() -> str:
    url = os.environ.get("V3_WORKFLOW_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("V3_WORKFLOW_DATABASE_URL não definida")
    assert_disposable_database(url)
    parsed = urlsplit(url)
    database_name = parsed.path.rsplit("/", 1)[-1].lower()
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or database_name != "v3_workflow_test"
    ):
        raise RuntimeError("banco de workflow V3 não está explicitamente identificado")
    return url


@pytest.fixture
def rls_database_url() -> str:
    return _workflow_database_url()


@pytest.fixture
def workflow_database(rls_database_url: str):
    """Reuse the exact V3 migration fixture against this test's isolated DB."""

    generator = _v3_database.__wrapped__(rls_database_url)
    engine = next(generator)
    try:
        _apply_v3_migration(engine, _V3_MIGRATION.read_text())
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                alter table decisions
                  alter column id set default gen_random_uuid();
                alter table pessoas
                  add column if not exists nome text not null default 'Pessoa sintética',
                  add column if not exists email text,
                  add column if not exists genero text,
                  add column if not exists faixa_etaria text,
                  add column if not exists endereco text,
                  add column if not exists tipo text,
                  add column if not exists etapa text,
                  add column if not exists subetapa text,
                  add column if not exists presencas_celula integer not null default 0,
                  add column if not exists aceitou_jesus boolean not null default false,
                  add column if not exists acompanhamento text,
                  add column if not exists origem text,
                  add column if not exists primeiro_contato timestamptz,
                  add column if not exists celula_id uuid,
                  add column if not exists lider_id uuid,
                  add column if not exists consentimento boolean not null default false,
                  add column if not exists apto_proxima_cd boolean not null default false,
                  add column if not exists apto_lider boolean not null default false,
                  add column if not exists sem_interesse boolean not null default false,
                  add column if not exists sem_interesse_motivo text,
                  add column if not exists arquivada_por uuid,
                  add column if not exists arquivada_motivo text,
                  add column if not exists created_at timestamptz not null default now();

                -- The real queue scope for a cell leader compiles through
                -- these relations even when explicit assignment grants the
                -- candidate visibility. Keep the disposable V3 fixture
                -- structurally equivalent to that route.
                create table if not exists celulas (
                  id uuid primary key,
                  igreja_id uuid not null,
                  lider_id uuid,
                  ativo boolean not null default true
                );
                create table if not exists celula_membro (
                  id uuid primary key default gen_random_uuid(),
                  igreja_id uuid not null,
                  celula_id uuid not null,
                  pessoa_id uuid not null,
                  ativo boolean not null default true
                );
                alter table celulas enable row level security;
                alter table celula_membro enable row level security;
                drop policy if exists tenant_isolation on celulas;
                create policy tenant_isolation on celulas for all
                  using (igreja_id = current_igreja_id())
                  with check (igreja_id = current_igreja_id());
                drop policy if exists tenant_isolation on celula_membro;
                create policy tenant_isolation on celula_membro for all
                  using (igreja_id = current_igreja_id())
                  with check (igreja_id = current_igreja_id());
                grant select on celulas, celula_membro to authenticated;
                """
            )
        yield engine
    finally:
        try:
            next(generator)
        except StopIteration:
            pass


def _factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def _actor(tenant: uuid.UUID, actor_id: uuid.UUID) -> CurrentUser:
    return CurrentUser(
        app_user_id=str(actor_id),
        clerk_user_id=f"clerk-{actor_id}",
        igreja_id=str(tenant),
        email="synthetic@example.test",
        nome="Pastor sintético",
        roles=frozenset({"pastor"}),
    )


def _scoped(factory: sessionmaker[Session], tenant: uuid.UUID) -> Session:
    session = factory()
    mark_tenant_scoped(session, tenant, source="v3_consolidation_workflow_pg")
    assert session.execute(text("select current_user")).scalar_one() == "authenticated"
    assert session.execute(
        text("select rolbypassrls from pg_roles where rolname = current_user")
    ).scalar_one() is False
    return session


def _seed(
    engine,
    *,
    include_legacy_target: bool = False,
) -> dict[str, uuid.UUID]:
    values = {
        "tenant": uuid.uuid4(),
        "actor_person": uuid.uuid4(),
        "actor": uuid.uuid4(),
        "person": uuid.uuid4(),
        "target_a_person": uuid.uuid4(),
        "target_a": uuid.uuid4(),
        "target_b_person": uuid.uuid4(),
        "target_b": uuid.uuid4(),
        "legacy_target": uuid.uuid4(),
    }
    with engine.begin() as connection:
        connection.execute(
            text("insert into igrejas(id,status) values(:tenant,'ativa')"), values
        )
        for person_key, phone in (
            ("actor_person", "5500000000001"),
            ("person", "5500000000002"),
            ("target_a_person", "5500000000003"),
            ("target_b_person", "5500000000004"),
        ):
            connection.execute(
                text(
                    "insert into pessoas(id,igreja_id,telefone) "
                    "values(:person,:tenant,:phone)"
                ),
                {"person": values[person_key], "tenant": values["tenant"], "phone": phone},
            )
        for user_key, person_key in (
            ("actor", "actor_person"),
            ("target_a", "target_a_person"),
            ("target_b", "target_b_person"),
        ):
            connection.execute(
                text(
                    "insert into app_users(id,igreja_id,pessoa_id,clerk_user_id,status) "
                    "values(:user,:tenant,:person,:clerk,'ativo')"
                ),
                {
                    "user": values[user_key],
                    "tenant": values["tenant"],
                    "person": values[person_key],
                    "clerk": f"clerk-{values[user_key]}",
                },
            )
            connection.execute(
                text(
                    "insert into user_roles(igreja_id,user_id,papel) "
                    "values(:tenant,:user,'lider_consol')"
                ),
                {"tenant": values["tenant"], "user": values[user_key]},
            )
        if include_legacy_target:
            connection.execute(
                text(
                    "insert into app_users(id,igreja_id,clerk_user_id,status) "
                    "values(:user,:tenant,:clerk,'ativo')"
                ),
                {
                    "user": values["legacy_target"],
                    "tenant": values["tenant"],
                    "clerk": f"clerk-{values['legacy_target']}",
                },
            )
    return values


def _insert_track(
    engine,
    values: dict[str, uuid.UUID],
    *,
    concluded: bool = False,
    responsible_key: str = "actor",
) -> tuple[uuid.UUID, uuid.UUID]:
    track_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into consolidacoes("
                "id,igreja_id,pessoa_id,tipo,responsavel_id,progresso,concluida"
                ") values(:track,:tenant,:person,'individual',:responsible,33,:concluded)"
            ),
            {
                "track": track_id,
                "tenant": values["tenant"],
                "person": values["person"],
                "responsible": values[responsible_key],
                "concluded": concluded,
            },
        )
        connection.execute(
            text(
                "insert into consolidacao_etapas("
                "igreja_id,consolidacao_id,etapa,concluida"
                ") values(:tenant,:track,'aceitou_jesus',true)"
            ),
            {"tenant": values["tenant"], "track": track_id},
        )
        queue_id = connection.execute(
            text(
                "select id from work_queue_items where igreja_id=:tenant "
                "and consolidacao_id=:track and tipo='fonovisita'"
            ),
            {"tenant": values["tenant"], "track": track_id},
        ).scalar_one()
    return track_id, queue_id


def _assignment_revision(engine, track_id: uuid.UUID) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("select assignment_revision from consolidacoes where id=:track"),
                {"track": track_id},
            ).scalar_one()
        )


def _track_rows(engine, track_id: uuid.UUID) -> list[tuple[uuid.UUID, uuid.UUID | None, str | None]]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "select id,responsavel_id,status from work_queue_items "
                    "where consolidacao_id=:track order by id"
                ),
                {"track": track_id},
            )
        )


def _queue_actor(
    tenant: uuid.UUID,
    actor_id: uuid.UUID,
    roles: frozenset[str],
) -> CurrentUser:
    return CurrentUser(
        app_user_id=str(actor_id),
        clerk_user_id=f"clerk-{actor_id}",
        igreja_id=str(tenant),
        email="queue-actor@example.test",
        nome="Líder sintético",
        roles=roles,
    )


@pytest.mark.parametrize(
    ("roles", "item_tipo", "action", "expected_status", "target_key"),
    (
        (frozenset({"lider_g12"}), "conectar_celula", "assume", 200, "actor"),
        (frozenset({"lider_g12"}), "fonovisita", "assign", 200, "target_a"),
        (frozenset({"lider_celula"}), "fonovisita", "assume", 200, "actor"),
        (frozenset({"lider_celula"}), "fonovisita", "assign", 403, "actor"),
        (frozenset({"lider_celula"}), "conectar_celula", "assume", 403, "actor"),
    ),
    ids=(
        "lider_g12_assume_conexao",
        "lider_g12_assign_fonovisita",
        "lider_celula_assume_fonovisita",
        "lider_celula_cannot_assign",
        "lider_celula_cannot_assume_conexao",
    ),
)
def test_v3_queue_http_keeps_legacy_role_capability_and_state(
    workflow_database,
    app,
    roles: frozenset[str],
    item_tipo: str,
    action: str,
    expected_status: int,
    target_key: str,
) -> None:
    """The linked V3 path retains the panel's queue-role contract.

    The request crosses the actual FastAPI route and the shared workflow under
    authenticated NOBYPASSRLS.  It proves the specialised S3/pipeline role
    boundary cannot accidentally remove ``can_resolve`` from human queue work.
    """

    values = _seed(workflow_database)
    track_id, fonovisita_id = _insert_track(workflow_database, values)
    candidate_id = fonovisita_id
    if item_tipo == "conectar_celula":
        candidate_id = uuid.uuid4()
        with workflow_database.begin() as connection:
            connection.execute(
                text(
                    "insert into work_queue_items("
                    "id,igreja_id,consolidacao_id,tipo,titulo,pessoa_id,responsavel_id,status,prioridade"
                    ") values(:id,:tenant,:track,'conectar_celula','Conectar',:person,:actor,'aberto',1)"
                ),
                {
                    "id": candidate_id,
                    "tenant": values["tenant"],
                    "track": track_id,
                    "person": values["person"],
                    "actor": values["actor"],
                },
            )
    with workflow_database.begin() as connection:
        connection.execute(
            text("delete from user_roles where igreja_id=:tenant and user_id=:actor"),
            {"tenant": values["tenant"], "actor": values["actor"]},
        )
        for role in roles:
            connection.execute(
                text(
                    "insert into user_roles(igreja_id,user_id,papel) "
                    "values(:tenant,:actor,:role)"
                ),
                {"tenant": values["tenant"], "actor": values["actor"], "role": role},
            )

    session = _scoped(_factory(workflow_database), values["tenant"])
    actor = _queue_actor(values["tenant"], values["actor"], roles)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: actor
    client = TestClient(app)
    try:
        payload: dict[str, str] = {"action": action}
        if action == "assign":
            payload["responsavelId"] = str(values["target_a"])
        response = client.post(f"/work-queue/{candidate_id}/action", json=payload)
    finally:
        client.close()
        session.close()

    assert response.status_code == expected_status, response.text
    expected_responsavel = values[target_key]
    with workflow_database.connect() as connection:
        assert connection.execute(
            text("select responsavel_id from consolidacoes where id=:track"),
            {"track": track_id},
        ).scalar_one() == expected_responsavel
        item_state = connection.execute(
            text(
                "select responsavel_id,status from work_queue_items "
                "where id=:item"
            ),
            {"item": candidate_id},
        ).one()
    if expected_status == 200:
        assert item_state == (expected_responsavel, "assumido")
    else:
        assert item_state == (values["actor"], "aberto")


def test_register_decision_reads_its_exact_v3_origin_and_keeps_conflict_semantics(
    workflow_database,
) -> None:
    values = _seed(workflow_database)
    factory = _factory(workflow_database)
    actor = _actor(values["tenant"], values["actor"])

    session = _scoped(factory, values["tenant"])
    try:
        consolidacao = register_decision(
            session,
            actor,
            pessoa_id=values["person"],
            vinculo="visitante",
        )
        origin_decision_id = consolidacao.origin_decision_id
        assert origin_decision_id is not None
        session.commit()
    finally:
        session.close()

    with workflow_database.connect() as connection:
        assert connection.execute(
            text(
                "select origin_decision_id from consolidacoes where id=:track"
            ),
            {"track": consolidacao.id},
        ).scalar_one() == origin_decision_id
        assert connection.execute(
            text(
                "select count(*) from work_queue_items "
                "where consolidacao_id=:track and tipo='fonovisita'"
            ),
            {"track": consolidacao.id},
        ).scalar_one() == 1
        assert connection.execute(
            text(
                "select count(*) from work_queue_items "
                "where consolidacao_id=:track and tipo='conectar_celula'"
            ),
            {"track": consolidacao.id},
        ).scalar_one() == 1

    collision = _scoped(factory, values["tenant"])
    try:
        with pytest.raises(IntegrityError) as rejected:
            register_decision(
                collision,
                actor,
                pessoa_id=values["person"],
                vinculo="visitante",
            )
        assert rejected.value.orig.pgcode == "23505"
        assert collision.is_active
        collision.rollback()
    finally:
        collision.close()

    with workflow_database.connect() as connection:
        assert connection.execute(
            text("select count(*) from decisions where igreja_id=:tenant"),
            {"tenant": values["tenant"]},
        ).scalar_one() == 1
        assert connection.execute(
            text("select count(*) from consolidacoes where igreja_id=:tenant"),
            {"tenant": values["tenant"]},
        ).scalar_one() == 1


def test_assignment_syncs_linked_tasks_and_fences_aba(workflow_database) -> None:
    values = _seed(workflow_database)
    track_id, _ = _insert_track(workflow_database, values)
    connection_item = uuid.uuid4()
    with workflow_database.begin() as connection:
        connection.execute(
            text(
                "insert into work_queue_items("
                "id,igreja_id,consolidacao_id,tipo,titulo,pessoa_id,responsavel_id,status,prioridade"
                ") values(:id,:tenant,:track,'conectar_celula','Conectar',:person,:responsible,'aberto',1)"
            ),
            {
                "id": connection_item,
                "tenant": values["tenant"],
                "track": track_id,
                "person": values["person"],
                "responsible": values["actor"],
            },
        )

    factory = _factory(workflow_database)
    session = _scoped(factory, values["tenant"])
    try:
        result = assign_consolidacao(
            session,
            _actor(values["tenant"], values["actor"]),
            consolidacao_id=track_id,
            responsavel_id=values["target_a"],
            expected_assignment_revision=0,
            whatsapp=True,
        )
        assert result.consolidacao.id == track_id
        assert result.consolidacao.assignment_revision == 1
        session.commit()
    finally:
        session.close()

    assert _assignment_revision(workflow_database, track_id) == 1
    assert {
        (responsible, item_status)
        for _, responsible, item_status in _track_rows(workflow_database, track_id)
    } == {(values["target_a"], "assumido")}

    for target, revision in (("target_b", 1), ("target_a", 2)):
        session = _scoped(factory, values["tenant"])
        try:
            assign_consolidacao(
                session,
                _actor(values["tenant"], values["actor"]),
                consolidacao_id=track_id,
                responsavel_id=values[target],
                expected_assignment_revision=revision,
                whatsapp=True,
            )
            session.commit()
        finally:
            session.close()

    stale = _scoped(factory, values["tenant"])
    try:
        with pytest.raises(HTTPException) as rejected:
            assign_consolidacao(
                stale,
                _actor(values["tenant"], values["actor"]),
                consolidacao_id=track_id,
                responsavel_id=values["target_b"],
                expected_assignment_revision=1,
                whatsapp=True,
            )
        assert rejected.value.status_code == 409
        stale.rollback()
    finally:
        stale.close()

    assert _assignment_revision(workflow_database, track_id) == 3
    assert {
        (responsible, item_status)
        for _, responsible, item_status in _track_rows(workflow_database, track_id)
    } == {(values["target_a"], "assumido")}


def test_concurrent_assignment_allows_one_current_revision(workflow_database) -> None:
    values = _seed(workflow_database)
    track_id, _ = _insert_track(workflow_database, values)
    factory = _factory(workflow_database)
    barrier = threading.Barrier(2)

    def assign(target: uuid.UUID) -> int:
        session = _scoped(factory, values["tenant"])
        try:
            barrier.wait(timeout=5)
            assign_consolidacao(
                session,
                _actor(values["tenant"], values["actor"]),
                consolidacao_id=track_id,
                responsavel_id=target,
                expected_assignment_revision=0,
                whatsapp=True,
            )
            session.commit()
            return 200
        except HTTPException as exc:
            session.rollback()
            return exc.status_code
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(assign, (values["target_a"], values["target_b"])))

    assert sorted(statuses) == [200, 409]
    assert _assignment_revision(workflow_database, track_id) == 1


def test_complete_fonovisita_is_atomic_and_binds_the_exact_track(workflow_database) -> None:
    values = _seed(workflow_database)
    historical_track, historical_queue = _insert_track(
        workflow_database, values, concluded=True
    )
    current_track, current_queue = _insert_track(workflow_database, values)
    factory = _factory(workflow_database)

    non_responsible = _scoped(factory, values["tenant"])
    try:
        with pytest.raises(HTTPException) as rejected:
            complete_fonovisita(
                non_responsible,
                _actor(values["tenant"], values["target_a"]),
                consolidacao_id=current_track,
                work_queue_item_id=current_queue,
                expected_assignment_revision=0,
                whatsapp=True,
            )
        assert rejected.value.status_code == 403
        non_responsible.rollback()
    finally:
        non_responsible.close()

    wrong = _scoped(factory, values["tenant"])
    try:
        with pytest.raises(HTTPException) as rejected:
            complete_fonovisita(
                wrong,
                _actor(values["tenant"], values["actor"]),
                consolidacao_id=current_track,
                work_queue_item_id=historical_queue,
                expected_assignment_revision=0,
                whatsapp=True,
            )
        assert rejected.value.status_code == 404
        wrong.rollback()
    finally:
        wrong.close()

    rolled_back = _scoped(factory, values["tenant"])
    try:
        result = complete_fonovisita(
            rolled_back,
            _actor(values["tenant"], values["actor"]),
            consolidacao_id=current_track,
            work_queue_item_id=current_queue,
            expected_assignment_revision=0,
            whatsapp=True,
        )
        assert result.consolidacao.id == current_track
        assert result.work_queue_item.id == current_queue
        assert result.consolidacao.concluida is False
        assert result.work_queue_item.status == "resolvido"
        rolled_back.rollback()
    finally:
        rolled_back.close()

    with workflow_database.connect() as connection:
        assert connection.execute(
            text("select status from work_queue_items where id=:item"),
            {"item": current_queue},
        ).scalar_one() == "aberto"
        assert connection.execute(
            text(
                "select count(*) from consolidacao_etapas "
                "where consolidacao_id=:track and etapa='fonovisita'"
            ),
            {"track": current_track},
        ).scalar_one() == 0

    completed = _scoped(factory, values["tenant"])
    try:
        complete_fonovisita(
            completed,
            _actor(values["tenant"], values["actor"]),
            consolidacao_id=current_track,
            work_queue_item_id=current_queue,
            expected_assignment_revision=0,
            whatsapp=True,
        )
        completed.commit()
    finally:
        completed.close()

    with workflow_database.connect() as connection:
        assert connection.execute(
            text("select status from work_queue_items where id=:item"),
            {"item": current_queue},
        ).scalar_one() == "resolvido"
        assert connection.execute(
            text(
                "select concluida from consolidacao_etapas "
                "where consolidacao_id=:track and etapa='fonovisita'"
            ),
            {"track": current_track},
        ).scalar_one() is True
        assert connection.execute(
            text("select progresso,concluida from consolidacoes where id=:track"),
            {"track": current_track},
        ).one() == (67, False)
        assert connection.execute(
            text("select status from work_queue_items where id=:item"),
            {"item": historical_queue},
        ).scalar_one() == "aberto"
        assert historical_track != current_track


def test_whatsapp_target_is_stricter_than_existing_web_assignment(workflow_database) -> None:
    values = _seed(workflow_database, include_legacy_target=True)
    track_id, _ = _insert_track(workflow_database, values)
    factory = _factory(workflow_database)

    strict = _scoped(factory, values["tenant"])
    try:
        with pytest.raises(HTTPException) as missing_revision:
            assign_consolidacao(
                strict,
                _actor(values["tenant"], values["actor"]),
                consolidacao_id=track_id,
                responsavel_id=values["target_a"],
                expected_assignment_revision=None,
                whatsapp=True,
            )
        assert missing_revision.value.status_code == 422
        with pytest.raises(HTTPException) as rejected:
            assign_consolidacao(
                strict,
                _actor(values["tenant"], values["actor"]),
                consolidacao_id=track_id,
                responsavel_id=values["legacy_target"],
                expected_assignment_revision=0,
                whatsapp=True,
            )
        assert rejected.value.status_code == 404
        strict.rollback()
    finally:
        strict.close()

    with workflow_database.begin() as connection:
        connection.execute(
            text(
                "delete from user_roles where igreja_id=:tenant and user_id=:target"
            ),
            {"tenant": values["tenant"], "target": values["target_b"]},
        )

    no_role = _scoped(factory, values["tenant"])
    try:
        with pytest.raises(HTTPException) as rejected:
            assign_consolidacao(
                no_role,
                _actor(values["tenant"], values["actor"]),
                consolidacao_id=track_id,
                responsavel_id=values["target_b"],
                expected_assignment_revision=0,
                whatsapp=True,
            )
        assert rejected.value.status_code == 422
        no_role.rollback()
    finally:
        no_role.close()

    web = _scoped(factory, values["tenant"])
    try:
        result = assign_consolidacao(
            web,
            _actor(values["tenant"], values["actor"]),
            consolidacao_id=track_id,
            responsavel_id=values["legacy_target"],
            expected_assignment_revision=None,
            whatsapp=False,
        )
        assert result.consolidacao.responsavel_id == values["legacy_target"]
        web.commit()
    finally:
        web.close()


def test_cross_tenant_track_is_not_visible_to_tenant_scoped_service(workflow_database) -> None:
    own = _seed(workflow_database)
    foreign = _seed(workflow_database)
    foreign_track, foreign_queue = _insert_track(workflow_database, foreign)
    factory = _factory(workflow_database)

    session = _scoped(factory, own["tenant"])
    try:
        with pytest.raises(HTTPException) as assignment:
            assign_consolidacao(
                session,
                _actor(own["tenant"], own["actor"]),
                consolidacao_id=foreign_track,
                responsavel_id=own["target_a"],
                expected_assignment_revision=0,
                whatsapp=True,
            )
        assert assignment.value.status_code == 404
        session.rollback()
    finally:
        session.close()

    session = _scoped(factory, own["tenant"])
    try:
        with pytest.raises(HTTPException) as completion:
            complete_fonovisita(
                session,
                _actor(own["tenant"], own["actor"]),
                consolidacao_id=foreign_track,
                work_queue_item_id=foreign_queue,
                expected_assignment_revision=0,
                whatsapp=True,
            )
        assert completion.value.status_code == 404
        session.rollback()
    finally:
        session.close()

    with workflow_database.connect() as connection:
        assert connection.execute(
            text(
                "select responsavel_id,status from work_queue_items "
                "where id=:item"
            ),
            {"item": foreign_queue},
        ).one() == (foreign["actor"], "aberto")


def test_pipeline_queue_keeps_canonical_fonovisita_separate_from_manual_legacy(
    workflow_database,
) -> None:
    values = _seed(workflow_database)
    track_id, canonical_id = _insert_track(workflow_database, values)
    factory = _factory(workflow_database)
    actor = _actor(values["tenant"], values["actor"])

    session = _scoped(factory, values["tenant"])
    try:
        created = queue_fonovisita(
            FonovisitaRequest(pessoaId=str(values["person"]), contexto="manual A"),
            session,
            actor,
        )
        manual_id = uuid.UUID(created.itemId)
        assert created.status == "created"
    finally:
        session.close()

    session = _scoped(factory, values["tenant"])
    try:
        reused = queue_fonovisita(
            FonovisitaRequest(pessoaId=str(values["person"]), contexto="manual B"),
            session,
            actor,
        )
        assert reused.status == "updated"
        assert reused.itemId == str(manual_id)
    finally:
        session.close()

    with workflow_database.connect() as connection:
        rows = connection.execute(
            text(
                "select id,consolidacao_id,contexto from work_queue_items "
                "where igreja_id=:tenant and pessoa_id=:person and tipo='fonovisita' "
                "order by id"
            ),
            {"tenant": values["tenant"], "person": values["person"]},
        ).all()
        by_id = {row.id: row for row in rows}
        assert set(by_id) == {canonical_id, manual_id}
        assert by_id[canonical_id].consolidacao_id == track_id
        assert by_id[manual_id].consolidacao_id is None
        assert by_id[manual_id].contexto == "manual B"


def test_pipeline_advance_fonovisita_with_conclude_combination_is_atomic(
    workflow_database,
) -> None:
    values = _seed(workflow_database)
    track_id, queue_id = _insert_track(workflow_database, values)
    with workflow_database.begin() as connection:
        connection.execute(
            text(
                "insert into consolidacao_etapas("
                "igreja_id,consolidacao_id,etapa,concluida"
                ") values(:tenant,:track,'conectou_celula',true)"
            ),
            {"tenant": values["tenant"], "track": track_id},
        )

    session = _scoped(_factory(workflow_database), values["tenant"])
    try:
        response = advance_stage(
            AdvanceStageRequest(
                consolidacaoId=str(track_id), etapa="fonovisita", concluir=True
            ),
            session,
            _actor(values["tenant"], values["actor"]),
        )
        assert response.status == "concluded"
        assert response.progresso == 100
        assert response.concluida is True
        assert response.etapasPendentes == []
    finally:
        session.close()

    with workflow_database.connect() as connection:
        assert connection.execute(
            text("select status from work_queue_items where id=:item"),
            {"item": queue_id},
        ).scalar_one() == "resolvido"
        assert connection.execute(
            text("select concluida from consolidacoes where id=:track"),
            {"track": track_id},
        ).scalar_one() is True


def test_linked_work_queue_assignment_uses_workflow_and_enforces_actor(
    workflow_database,
) -> None:
    values = _seed(workflow_database)
    track_id, queue_id = _insert_track(workflow_database, values)
    other_item = uuid.uuid4()
    with workflow_database.begin() as connection:
        connection.execute(
            text(
                "insert into work_queue_items("
                "id,igreja_id,consolidacao_id,tipo,titulo,pessoa_id,status,prioridade"
                ") values(:id,:tenant,:track,'conectar_celula','Conectar',:person,'aberto',1)"
            ),
            {
                "id": other_item,
                "tenant": values["tenant"],
                "track": track_id,
                "person": values["person"],
            },
        )

    session = _scoped(_factory(workflow_database), values["tenant"])
    try:
        response = act_on_item(
            str(queue_id),
            ActionRequest(action="assign", responsavelId=str(values["target_a"])),
            session,
            _actor(values["tenant"], values["actor"]),
        )
        assert response.status == "assumido"
        assert response.responsavelId == str(values["target_a"])
    finally:
        session.close()

    restricted = _scoped(_factory(workflow_database), values["tenant"])
    try:
        member = CurrentUser(
            app_user_id=str(values["actor"]),
            clerk_user_id=f"clerk-{values['actor']}",
            igreja_id=str(values["tenant"]),
            email="member@example.test",
            nome="Membro sintético",
            roles=frozenset({"membro"}),
        )
        with pytest.raises(HTTPException) as denied:
            act_on_item(
                str(queue_id),
                ActionRequest(action="assign", responsavelId=str(values["target_b"])),
                restricted,
                member,
            )
        assert denied.value.status_code == 403
        restricted.rollback()
    finally:
        restricted.close()

    with workflow_database.connect() as connection:
        assert connection.execute(
            text("select responsavel_id from consolidacoes where id=:track"),
            {"track": track_id},
        ).scalar_one() == values["target_a"]
        assert connection.execute(
            text(
                "select distinct responsavel_id,status from work_queue_items "
                "where consolidacao_id=:track"
            ),
            {"track": track_id},
        ).all() == [(values["target_a"], "assumido")]


@pytest.mark.parametrize(("action", "target_key"), [("assume", "actor"), ("assign", "target_b")])
def test_queue_candidate_completed_after_read_cannot_reassign_linked_work(
    workflow_database,
    action: str,
    target_key: str,
) -> None:
    values = _seed(workflow_database)
    track_id, queue_id = _insert_track(workflow_database, values)
    other_item = uuid.uuid4()
    with workflow_database.begin() as connection:
        connection.execute(
            text(
                "insert into work_queue_items("
                "id,igreja_id,consolidacao_id,tipo,titulo,pessoa_id,status,prioridade"
                ") values(:id,:tenant,:track,'conectar_celula','Conectar',:person,'aberto',1)"
            ),
            {
                "id": other_item,
                "tenant": values["tenant"],
                "track": track_id,
                "person": values["person"],
            },
        )

    factory = _factory(workflow_database)
    actor = _actor(values["tenant"], values["actor"])
    stale = _scoped(factory, values["tenant"])
    try:
        candidate = _get_item_in_scope(stale, str(queue_id), actor)
        assert candidate.status == "aberto"

        completer = _scoped(factory, values["tenant"])
        try:
            complete_fonovisita(
                completer,
                actor,
                consolidacao_id=track_id,
                work_queue_item_id=queue_id,
                expected_assignment_revision=None,
                whatsapp=False,
            )
            completer.commit()
        finally:
            completer.close()

        with pytest.raises(HTTPException) as rejected:
            assign_consolidacao(
                stale,
                actor,
                consolidacao_id=track_id,
                responsavel_id=values[target_key],
                expected_assignment_revision=None,
                whatsapp=False,
                expected_work_queue_item_id=candidate.id,
                work_queue_action=action,  # type: ignore[arg-type]
            )
        assert rejected.value.status_code == 409
        stale.rollback()
    finally:
        stale.close()

    with workflow_database.connect() as connection:
        assert connection.execute(
            text("select responsavel_id,status from work_queue_items where id=:item"),
            {"item": other_item},
        ).one() == (None, "aberto")
        assert connection.execute(
            text("select responsavel_id from consolidacoes where id=:track"),
            {"track": track_id},
        ).scalar_one() == values["actor"]


@pytest.mark.parametrize("action", ["assume", "assign"])
def test_queue_action_does_not_take_a_live_holder_after_candidate_read(
    workflow_database,
    action: str,
) -> None:
    values = _seed(workflow_database)
    track_id, queue_id = _insert_track(workflow_database, values)
    factory = _factory(workflow_database)
    original_actor = _actor(values["tenant"], values["actor"])

    stale = _scoped(factory, values["tenant"])
    try:
        candidate = _get_item_in_scope(stale, str(queue_id), original_actor)
        assert candidate.status == "aberto"

        winner = _scoped(factory, values["tenant"])
        try:
            assign_consolidacao(
                winner,
                _actor(values["tenant"], values["target_a"]),
                consolidacao_id=track_id,
                responsavel_id=values["target_a"],
                expected_assignment_revision=None,
                whatsapp=False,
                expected_work_queue_item_id=queue_id,
                work_queue_action="assume",
            )
            winner.commit()
        finally:
            winner.close()

        with pytest.raises(HTTPException) as rejected:
            assign_consolidacao(
                stale,
                original_actor,
                consolidacao_id=track_id,
                responsavel_id=values["actor"],
                expected_assignment_revision=None,
                whatsapp=False,
                expected_work_queue_item_id=candidate.id,
                work_queue_action=action,  # type: ignore[arg-type]
            )
        assert rejected.value.status_code == 409
        stale.rollback()
    finally:
        stale.close()

    with workflow_database.connect() as connection:
        assert connection.execute(
            text("select responsavel_id,status from work_queue_items where id=:item"),
            {"item": queue_id},
        ).one() == (values["target_a"], "assumido")
        assert connection.execute(
            text("select responsavel_id from consolidacoes where id=:track"),
            {"track": track_id},
        ).scalar_one() == values["target_a"]
