"""V4 through real persisted inbounds, worker, catalog, domain and transport.

Only the external Evolution client is fake. Roles, contact identity, grants,
confirmation and the domain writer are real PostgreSQL/production code.
"""

from __future__ import annotations
import datetime as dt
import dataclasses
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func, text, delete
from cryptography.fernet import Fernet
from app.config import get_settings
from app.db.models import (
    AgentConfig,
    AppUser,
    Celula,
    CelulaMembro,
    ConsentRecord,
    Conversation,
    LlmCredential,
    Message,
    Pessoa,
    UserRole,
)
from app.deps import CurrentUser
from app.prayer import policy, service
from app.prayer.models import PrayerProposal, PrayerRequest
from app.visits.models import VisitEvent  # noqa: F401 - offboarding fixture schema
from app.services.crypto import encrypt_secret
from app.workers import queue_worker as worker
from tests.conftest_rls import rls_database_url  # noqa: F401
from tests.test_messages_inbound_idempotency import msg_engine_fx as msg_engine_fx
from tests.test_messages_inbound_idempotency import (
    _factory,
    _seed_igreja_with_connection,
    _seed_tier_a_handoff_anchor,
    _seed_inbound_anchor,
    _agent_outcome,
    _ClassifiedEvolution,
    _SCHEMA,
)

pytestmark = pytest.mark.rls_integration
TENANT = uuid.UUID("4a4a4a4a-0000-4000-8000-000000000001")
FOREIGN = uuid.UUID("4a4a4a4a-0000-4000-8000-000000000002")
MIGRATION = Path(__file__).parents[1] / "migrations/20261016_180000_prayer_requests.sql"


@pytest.fixture
def prayer(msg_engine_fx, monkeypatch):  # noqa: F811 - imported pytest fixture
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AGENT_TERM_VERSION", "prayer-test-v1")
    monkeypatch.setenv("WHATSAPP_PILOTO_IGREJA_IDS", str(TENANT))
    monkeypatch.setenv("PRAYER_REQUEST_ENABLED_IGREJA_IDS", str(TENANT))
    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("SESSION_JWT_SECRET", "prayer-synthetic-session-key-only")
    monkeypatch.setenv("ALLOW_REAL_SENDS", "true")  # synthetic provider only
    monkeypatch.setattr(policy, "PRAYER_REQUEST_APPROVED_RELEASE_ID", "synthetic-only")
    get_settings.cache_clear()
    # Unexpected fallback must never contact a real LLM, including with test keys.
    from app.services.llm import LLMClient

    def forbidden_llm(*args, **kwargs):
        raise AssertionError("prayer turn reached external LLM")

    monkeypatch.setattr(LLMClient, "complete", forbidden_llm)
    factory = _factory(msg_engine_fx)
    _seed_igreja_with_connection(factory, igreja_id=TENANT, instance="prayer-test")
    _seed_igreja_with_connection(factory, igreja_id=FOREIGN, instance="prayer-other")
    conv, person, _ = _seed_tier_a_handoff_anchor(
        factory, igreja_id=TENANT, provider_message_id="PRAYER-SEED"
    )
    actors = {}
    cell = uuid.uuid4()
    with factory.begin() as db:
        for role in ["pastor", "lider_celula", "operador", "admin", "membro"]:
            pid, uid = uuid.uuid4(), uuid.uuid4()
            db.add(
                Pessoa(
                    id=pid,
                    igreja_id=TENANT,
                    nome=role + " sintético",
                    telefone="55" + str(pid.int)[:11],
                )
            )
            db.flush()
            db.add(
                AppUser(
                    id=uid,
                    igreja_id=TENANT,
                    pessoa_id=pid,
                    nome=role,
                    email=role + "@example.test",
                    clerk_user_id="prayer-" + role,
                    status="ativo",
                )
            )
            db.flush()
            db.add(UserRole(igreja_id=TENANT, user_id=uid, papel=role))
            actors[role] = CurrentUser(
                app_user_id=str(uid),
                clerk_user_id="prayer-" + role,
                igreja_id=str(TENANT),
                email="",
                nome=role,
                roles=frozenset({role}),
            )
        db.add(
            Celula(
                id=cell,
                igreja_id=TENANT,
                nome="Célula sintética",
                lider_id=db.get(
                    AppUser, uuid.UUID(actors["lider_celula"].app_user_id)
                ).pessoa_id,
                cobertura_espiritual="Teste",
                ativo=True,
            )
        )
        db.flush()
        db.add(
            CelulaMembro(igreja_id=TENANT, celula_id=cell, pessoa_id=person, ativo=True)
        )
        db.add(
            ConsentRecord(
                igreja_id=TENANT,
                pessoa_id=person,
                termo_versao="prayer-test-v1",
                aceite_em=dt.datetime.now(dt.UTC),
            )
        )
        db.add(
            AgentConfig(
                igreja_id=TENANT, comportamento="Somente teste sintético", ativo=True
            )
        )
        db.add(
            LlmCredential(
                igreja_id=TENANT,
                provedor="openai",
                modelo="gpt-5.6-luna",
                api_key_encrypted=encrypt_secret("synthetic-provider-key"),
                validado=True,
                ativo=True,
            )
        )
    # Apply real migration policies to the isolated fixture schema; never public/shared.
    sql = (
        MIGRATION.read_text()
        .replace("public.", _SCHEMA + ".")
        .replace("pg_catalog, public", "pg_catalog, " + _SCHEMA)
        .replace("pg_catalog,public", "pg_catalog," + _SCHEMA)
    )
    with msg_engine_fx.begin() as conn:
        conn.exec_driver_sql(sql)
    yield SimpleNamespace(
        factory=factory,
        engine=msg_engine_fx,
        conv=conv,
        person=person,
        cell=cell,
        actors=actors,
    )
    get_settings.cache_clear()


def inbound(p, body, key=None):
    key = key or "prayer-" + uuid.uuid4().hex
    mid = _seed_inbound_anchor(
        p.factory,
        igreja_id=TENANT,
        conversation_id=p.conv,
        provider_message_id=key,
        texto=body,
    )
    outcome = _agent_outcome(
        p.conv,
        igreja_id=TENANT,
        provider_message_id=key,
        inbound_message_id=mid,
        instance="prayer-test",
        telefone="5500000000000",
    )
    return dataclasses.replace(outcome, texto=body)


def send(p, body):
    class CommittedTransport(_ClassifiedEvolution):
        def send_text_classificado(self, instance, phone, body):
            with p.factory() as db:
                outgoing = (
                    db.execute(
                        select(Message)
                        .where(
                            Message.conversation_id == p.conv,
                            Message.direcao == "out",
                            Message.texto == body,
                        )
                        .order_by(Message.criado_em.desc())
                    )
                    .scalars()
                    .first()
                )
                assert (
                    outgoing is not None
                )  # A different connection sees the committed reply.
                if body.startswith("Pedido de oração registrado"):
                    assert (
                        db.scalar(select(func.count()).select_from(PrayerRequest)) == 1
                    )
            return super().send_text_classificado(instance, phone, body)

    client = CommittedTransport()
    outcome = inbound(p, body)
    worker.run_agent_for_message(p.factory, outcome, evolution_client=client)
    with p.factory() as db:
        reply = (
            db.execute(
                select(Message)
                .where(Message.conversation_id == p.conv, Message.direcao == "out")
                .order_by(Message.criado_em.desc())
            )
            .scalars()
            .first()
        )
        return outcome, reply, client


def create_request(p, audience="Só pastores"):
    send(p, "Peço oração por mim: preciso de força nesta semana.")
    _, proposal, _ = send(p, audience)
    assert "Admin e atendimento não têm acesso por cargo" in proposal.texto
    confirmation, reply, client = send(p, "SIM")
    assert client.calls
    assert reply.agent_reply_state == "ia"
    assert "registrado" in reply.texto
    with p.factory() as db:
        row = db.execute(select(PrayerRequest)).scalar_one()
        assert row.confirmation_message_id == confirmation.inbound_message_id
        assert row.authorization_text == proposal.texto
        return row


def test_complete_turn_without_panel_account(prayer):
    row = create_request(prayer)
    with prayer.factory() as db:
        assert (
            db.execute(
                select(func.count())
                .select_from(AppUser)
                .where(AppUser.pessoa_id == prayer.person)
            ).scalar_one()
            == 0
        )
        assert len(service.list_requests(db, prayer.actors["pastor"])) == 1
        assert row.audience == "pastoral"


@pytest.mark.parametrize("role", ["operador", "admin", "membro", "lider_celula"])
def test_only_pastors_denies_other_roles(prayer, role):
    row = create_request(prayer)
    with prayer.factory() as db:
        assert service.list_requests(db, prayer.actors[role]) == []
        with pytest.raises(HTTPException):
            service.get_request(db, prayer.actors[role], row.id)


def test_authorized_leader_loses_access_after_membership_change(prayer):
    row = create_request(prayer, "Pastores e meu líder")
    with prayer.factory.begin() as db:
        assert (
            service.get_request(db, prayer.actors["lider_celula"], row.id).id == row.id
        )
        member = db.execute(
            select(CelulaMembro).where(CelulaMembro.pessoa_id == prayer.person)
        ).scalar_one()
        member.ativo = False
    with prayer.factory() as db:
        assert service.list_requests(db, prayer.actors["lider_celula"]) == []


def test_ambiguous_choice_and_confirmation_never_record_request(prayer):
    send(prayer, "Peço oração por mim: estou preocupado.")
    _, reply, _ = send(prayer, "talvez com todos")
    assert "Com quem autoriza" in reply.texto
    send(prayer, "SIM")
    with prayer.factory() as db:
        assert db.scalar(select(func.count()).select_from(PrayerRequest)) == 0


def test_confirmation_duplicate_and_expired_do_not_duplicate(prayer):
    create_request(prayer)
    _assert_prayer_yields_sim(prayer)
    send(prayer, "Peço oração por mim: preciso de paz.")
    send(prayer, "Só pastores")
    with prayer.factory.begin() as db:
        draft = db.execute(
            select(PrayerProposal).where(PrayerProposal.state == "pending")
        ).scalar_one()
        draft.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    _, reply, _ = send(prayer, "SIM")
    assert "expir" in reply.texto
    with prayer.factory() as db:
        assert db.scalar(select(func.count()).select_from(PrayerRequest)) == 1


def test_optout_and_crisis_precede_prayer(prayer):
    send(prayer, "Peço oração por mim: preciso de ajuda.")
    send(prayer, "Quero me matar, peço oração")
    with prayer.factory.begin() as db:
        assert db.get(Conversation, prayer.conv).estado == "humano"
        assert db.scalar(select(func.count()).select_from(PrayerRequest)) == 0
        db.get(Conversation, prayer.conv).estado = "ia"
    send(prayer, "SAIR")
    with prayer.factory() as db:
        assert db.get(Pessoa, prayer.person).optout


def test_flag_closed_does_not_touch_prayer_tables(prayer, monkeypatch):
    from app.prayer.turn import run_prayer_turn

    monkeypatch.delenv("PRAYER_REQUEST_ENABLED_IGREJA_IDS")

    def forbidden():
        raise AssertionError("disabled prayer opened a session")

    assert (
        run_prayer_turn(
            forbidden,
            forbidden,
            inbound(prayer, "Peço oração por mim: paz."),
            igreja_id=TENANT,
            uses_dedicated_agent_session=False,
            ownership_guard=None,
            evolution_client=None,
        )
        is None
    )


def test_assume_close_and_delete_for_approved_offboarding(prayer):
    row = create_request(prayer)
    with prayer.factory.begin() as db:
        service.assume(db, prayer.actors["pastor"], row.id)
        assert service.close(db, prayer.actors["pastor"], row.id).state == "closed"
        db.execute(
            text(
                "select set_config('app.tenant_igreja_id',:tenant,true), set_config('request.jwt.claims','{\"sub\":\"prayer-admin\"}',true), set_config('role','authenticated',true)"
            ),
            {"tenant": str(TENANT)},
        )
        service.delete_for_person(db, igreja_id=TENANT, pessoa_id=prayer.person)
    with prayer.factory() as db:
        assert db.scalar(select(func.count()).select_from(PrayerRequest)) == 0
        assert db.scalar(select(func.count()).select_from(PrayerProposal)) == 0


def test_real_rls_web_recipients_and_two_tenants(prayer):
    create_request(prayer)
    for role, wanted in [
        ("pastor", 1),
        ("admin", 0),
        ("operador", 0),
        ("lider_celula", 0),
    ]:
        with prayer.engine.begin() as conn:
            conn.execute(
                text(
                    "select set_config('app.tenant_igreja_id',:t,true),set_config('request.jwt.claims',:claims,true),set_config('role','authenticated',true)"
                ),
                {"t": str(TENANT), "claims": '{"sub":"prayer-' + role + '"}'},
            )
            assert conn.scalar(text("select count(*) from pedido_oracao")) == wanted
    with prayer.engine.begin() as conn:
        conn.execute(
            text(
                "select set_config('app.tenant_igreja_id',:t,true),set_config('role','authenticated',true)"
            ),
            {"t": str(FOREIGN)},
        )
        assert conn.scalar(text("select count(*) from pedido_oracao")) == 0


def test_handoff_cancels_old_confirmation_even_after_human_returns(prayer):
    send(prayer, "Peço oração por mim: preciso de ajuda.")
    send(prayer, "Só pastores")
    send(prayer, "Quero falar com uma pessoa")
    with prayer.factory.begin() as db:
        assert not db.scalars(
            select(PrayerProposal).where(
                PrayerProposal.state.in_(("collecting", "pending"))
            )
        ).all()
        db.get(Conversation, prayer.conv).estado = "ia"
    _assert_prayer_yields_sim(prayer)
    with prayer.factory() as db:
        assert db.scalar(select(func.count()).select_from(PrayerRequest)) == 0


def test_new_leader_does_not_inherit_authorization(prayer):
    row = create_request(prayer, "Pastores e meu líder")
    with prayer.factory.begin() as db:
        db.get(Celula, prayer.cell).lider_id = db.get(
            AppUser, uuid.UUID(prayer.actors["membro"].app_user_id)
        ).pessoa_id
    with prayer.factory() as db:
        assert service.list_requests(db, prayer.actors["lider_celula"]) == []
        assert service.list_requests(db, prayer.actors["membro"]) == []
        assert service.get_request(db, prayer.actors["pastor"], row.id)


def test_existing_archive_removes_prayer_content(prayer):
    from app.services.pessoa_offboarding_service import archive_pessoa

    create_request(prayer)
    with prayer.factory.begin() as db:
        db.execute(delete(CelulaMembro).where(CelulaMembro.pessoa_id == prayer.person))
    with prayer.factory() as db:
        db.execute(
            text(
                "select set_config('app.tenant_igreja_id',:t,true),set_config('request.jwt.claims','{\"sub\":\"prayer-admin\"}',true),set_config('role','authenticated',true)"
            ),
            {"t": str(TENANT)},
        )
        person = db.get(Pessoa, prayer.person)
        archive_pessoa(
            db,
            pessoa=person,
            actor_app_user_id=uuid.UUID(prayer.actors["admin"].app_user_id),
            motivo="Exclusão sintética aprovada",
        )
    with prayer.factory() as db:
        assert db.scalar(select(func.count()).select_from(PrayerRequest)) == 0
        assert db.scalar(select(func.count()).select_from(PrayerProposal)) == 0


def test_role_revoked_and_foreign_pastor_cannot_read(prayer):
    row = create_request(prayer)
    foreign_user = uuid.uuid4()
    with prayer.factory.begin() as db:
        db.add(
            AppUser(
                id=foreign_user,
                igreja_id=FOREIGN,
                nome="Pastor sintético B",
                email="pastor-b@example.test",
                clerk_user_id="prayer-pastor-b",
                status="ativo",
            )
        )
        db.flush()
        db.add(UserRole(igreja_id=FOREIGN, user_id=foreign_user, papel="pastor"))
        db.execute(
            delete(UserRole).where(
                UserRole.user_id == uuid.UUID(prayer.actors["pastor"].app_user_id)
            )
        )
    other = CurrentUser(
        app_user_id=str(foreign_user),
        clerk_user_id="prayer-pastor-b",
        igreja_id=str(FOREIGN),
        email="",
        nome="Pastor B",
        roles=frozenset({"pastor"}),
    )
    with prayer.factory() as db:
        assert service.list_requests(db, prayer.actors["pastor"]) == []
        with pytest.raises(HTTPException) as error:
            service.get_request(db, other, row.id)
        assert error.value.status_code == 404


def test_person_delete_cascades_requests_and_proposals(prayer):
    create_request(prayer)
    with prayer.factory.begin() as db:
        # Existing legacy relationships have their own lifecycle; isolate V4's FK.
        db.execute(
            delete(ConsentRecord).where(ConsentRecord.pessoa_id == prayer.person)
        )
        db.execute(delete(CelulaMembro).where(CelulaMembro.pessoa_id == prayer.person))
        db.get(Conversation, prayer.conv).pessoa_id = None
        db.flush()
        db.execute(delete(Pessoa).where(Pessoa.id == prayer.person))
    with prayer.factory() as db:
        assert db.scalar(select(func.count()).select_from(PrayerRequest)) == 0
        assert db.scalar(select(func.count()).select_from(PrayerProposal)) == 0


def test_current_term_is_required_before_collecting(prayer):
    with prayer.factory.begin() as db:
        db.execute(
            delete(ConsentRecord).where(ConsentRecord.pessoa_id == prayer.person)
        )
    send(prayer, "Peço oração por mim: preciso de paz.")
    with prayer.factory() as db:
        assert db.scalar(select(func.count()).select_from(PrayerRequest)) == 0
        assert db.scalar(select(func.count()).select_from(PrayerProposal)) == 0


def test_database_failure_never_exposes_pastoral_text(prayer):
    import traceback

    send(prayer, "Peço oração por mim: conteúdo pastoral sintético privado.")
    send(prayer, "Só pastores")
    with prayer.engine.begin() as conn:
        conn.exec_driver_sql(
            "alter table pedido_oracao add constraint synthetic_failure check (false)"
        )
    with pytest.raises(RuntimeError) as error:
        send(prayer, "SIM")
    assert "conteúdo pastoral sintético privado" not in "".join(
        traceback.format_exception(error.value)
    )
    with prayer.factory() as db:
        assert db.scalar(select(func.count()).select_from(PrayerRequest)) == 0


def test_rls_rejects_privacy_field_mutation_and_unauthorized_delete(prayer):
    from sqlalchemy.exc import DBAPIError

    create_request(prayer)
    for query in [
        "update pedido_oracao set audience='pastoral_lider'",
        "delete from pedido_oracao",
    ]:
        with pytest.raises(DBAPIError):
            with prayer.engine.begin() as conn:
                conn.execute(
                    text(
                        "select set_config('app.tenant_igreja_id',:t,true),set_config('request.jwt.claims','{\"sub\":\"prayer-pastor\"}',true),set_config('role','authenticated',true)"
                    ),
                    {"t": str(TENANT)},
                )
                conn.exec_driver_sql(query)


def test_panel_routes_enforce_recipients_and_domain_lifecycle(prayer):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.prayer.router import router
    from app.db.session import get_db
    from app.deps import get_current_user

    row = create_request(prayer)

    def client_for(role):
        user = prayer.actors[role]

        def db_dependency():
            with prayer.factory() as db:
                db.execute(
                    text(
                        "select set_config('app.tenant_igreja_id',:t,true),set_config('request.jwt.claims',:claims,true),set_config('role','authenticated',true)"
                    ),
                    {
                        "t": str(TENANT),
                        "claims": '{"sub":"' + user.clerk_user_id + '"}',
                    },
                )
                yield db

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = db_dependency
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    for role in ["admin", "operador", "lider_celula"]:
        with client_for(role) as client:
            assert client.get("/prayer-requests/access").json() == {"allowed": False}
            assert client.get(f"/prayer-requests/{row.id}").status_code == 404
            assert client.post(f"/prayer-requests/{row.id}/assume").status_code == 404
    with client_for("pastor") as client:
        result = client.get("/prayer-requests")
        assert result.status_code == 200
        assert result.headers["cache-control"] == "private, no-store"
        assert result.json()[0]["pessoa_nome"] == "Contato sintético"
        assert (
            client.post(f"/prayer-requests/{row.id}/assume").json()["state"]
            == "assigned"
        )
        assert (
            client.post(f"/prayer-requests/{row.id}/close").json()["state"] == "closed"
        )


def test_real_rls_leader_access_is_revoked_by_cell_change(prayer):
    create_request(prayer, "Pastores e meu líder")
    for expected in [1, 0]:
        with prayer.engine.begin() as conn:
            conn.execute(
                text(
                    "select set_config('app.tenant_igreja_id',:t,true),set_config('request.jwt.claims','{\"sub\":\"prayer-lider_celula\"}',true),set_config('role','authenticated',true)"
                ),
                {"t": str(TENANT)},
            )
            assert conn.scalar(text("select count(*) from pedido_oracao")) == expected
            assert conn.scalar(text("select count(*) from pedido_oracao_proposta")) == 0
        if expected:
            with prayer.factory.begin() as db:
                db.get(Celula, prayer.cell).lider_id = db.get(
                    AppUser, uuid.UUID(prayer.actors["membro"].app_user_id)
                ).pessoa_id


def test_cross_tenant_foreign_key_rejects_a_forged_contact(prayer):
    from sqlalchemy.exc import DBAPIError

    foreign_person = uuid.uuid4()
    with prayer.factory.begin() as db:
        db.add(
            Pessoa(
                id=foreign_person,
                igreja_id=FOREIGN,
                nome="Contato B sintético",
                telefone="5500000000002",
            )
        )
    source = inbound(prayer, "Peço oração por mim: texto sintético.")
    with pytest.raises(DBAPIError):
        with prayer.engine.begin() as conn:
            conn.execute(
                text(
                    "select set_config('app.tenant_igreja_id',:t,true),set_config('request.jwt.claims','{}',true),set_config('role','authenticated',true)"
                ),
                {"t": str(TENANT)},
            )
            conn.execute(
                text(
                    "insert into pedido_oracao_proposta(id,igreja_id,pessoa_id,conversation_id,source_message_id,summary,term_version,expires_at) values(:id,:t,:p,:c,:m,'sintético','v1',now()+interval '10 minutes')"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "t": str(TENANT),
                    "p": str(foreign_person),
                    "c": str(prayer.conv),
                    "m": str(source.inbound_message_id),
                },
            )


def test_queue_text_is_not_used_as_confirmation_authority(prayer):
    send(prayer, "Peço oração por mim: preciso de paz.")
    send(prayer, "Só pastores")
    source = inbound(prayer, "talvez")
    forged = dataclasses.replace(source, texto="SIM")
    worker.run_agent_for_message(
        prayer.factory, forged, evolution_client=_ClassifiedEvolution()
    )
    with prayer.factory() as db:
        assert db.scalar(select(func.count()).select_from(PrayerRequest)) == 0


def test_pastor_recovers_assignment_when_leader_loses_access(prayer):
    row = create_request(prayer, "Pastores e meu líder")
    with prayer.factory.begin() as db:
        service.assume(db, prayer.actors["lider_celula"], row.id)
        db.execute(delete(CelulaMembro).where(CelulaMembro.pessoa_id == prayer.person))
    with prayer.factory.begin() as db:
        service.assume(db, prayer.actors["pastor"], row.id)
        assert service.close(db, prayer.actors["pastor"], row.id).state == "closed"


def test_sim_received_before_summary_delivery_cannot_authorize(prayer):
    send(prayer, "Peço oração por mim: preciso de força.")
    early = inbound(prayer, "SIM")
    send(prayer, "Só pastores")
    worker.run_agent_for_message(
        prayer.factory, early, evolution_client=_ClassifiedEvolution()
    )
    with prayer.factory() as db:
        assert db.scalar(select(func.count()).select_from(PrayerRequest)) == 0


def test_new_prayer_and_s3_summaries_supersede_other_protocol(prayer):
    from app.db.models import AgentActionProposal

    source = inbound(prayer, "ação sintética")

    def s3(db, mid):
        actor = db.get(AppUser, uuid.UUID(prayer.actors["pastor"].app_user_id))
        row = AgentActionProposal(
            igreja_id=TENANT,
            conversation_id=prayer.conv,
            actor_pessoa_id=actor.pessoa_id,
            actor_app_user_id=actor.id,
            source_message_id=mid,
            action="registrar_decisao",
            target_kind="pessoa",
            target_id=prayer.person,
            arguments_json={},
            arguments_sha256="a" * 64,
            scope_fingerprint="b" * 64,
            summary_sha256="c" * 64,
            state="preparada",
        )
        db.add(row)
        db.flush()
        return row.id

    with prayer.factory.begin() as db:
        first = s3(db, source.inbound_message_id)
    send(prayer, "Peço oração por mim: preciso de força.")
    with prayer.factory() as db:
        assert db.get(AgentActionProposal, first).state == "cancelada"
    another = inbound(prayer, "outra ação sintética")
    with prayer.factory.begin() as db:
        s3(db, another.inbound_message_id)
        assert db.execute(select(PrayerProposal)).scalar_one().state == "cancelled"


def test_complete_turn_refuses_request_on_behalf_of_someone_else(prayer):
    _, reply, transport = send(
        prayer, "Peço oração pela Maria: estou preocupado com ela."
    )
    assert transport.calls
    assert reply.agent_reply_state == "ia"
    assert "pedido próprio" in reply.texto
    with prayer.factory() as db:
        assert db.scalar(select(func.count()).select_from(PrayerRequest)) == 0
        assert db.scalar(select(func.count()).select_from(PrayerProposal)) == 0


def test_incomplete_prayer_schema_blocks_approved_offboarding(prayer):
    row = create_request(prayer)
    with prayer.factory.begin() as db:
        db.execute(
            text(
                f"drop function {_SCHEMA}.delete_prayer_requests_for_person(uuid,uuid)"
            )
        )
        db.execute(delete(CelulaMembro).where(CelulaMembro.pessoa_id == prayer.person))
    from app.services.pessoa_offboarding_service import archive_pessoa

    with prayer.factory() as db:
        person = db.get(Pessoa, prayer.person)
        with pytest.raises(RuntimeError, match="migration is incomplete"):
            archive_pessoa(
                db,
                pessoa=person,
                actor_app_user_id=uuid.UUID(prayer.actors["admin"].app_user_id),
                motivo="Exclusão sintética autorizada",
            )
        db.rollback()
        assert db.get(Pessoa, prayer.person).arquivada_em is None
        assert db.get(PrayerRequest, row.id) is not None


def _enable_s3_for_prayer_contact(prayer, monkeypatch):
    """Give only the synthetic sender an existing pastoral account for S3."""
    from app.db.models import AgentActionProposal
    from app.services import whatsapp_privilege
    from tests.test_agent_privileged_turn_pg import _fake_choices
    from tests.test_consolidacao_open_unique_concurrency import _TRIGGER_SQL

    monkeypatch.setattr(
        whatsapp_privilege, "PRIVILEGE_APPROVED_RELEASE_ID", "synthetic-only"
    )
    monkeypatch.setenv("AGENT_PRIVILEGE_ENABLED_IGREJA_IDS", str(TENANT))
    uid, target = uuid.uuid4(), uuid.uuid4()
    with prayer.engine.begin() as conn:
        conn.exec_driver_sql(_TRIGGER_SQL)
    with prayer.factory.begin() as db:
        db.add(
            AppUser(
                id=uid,
                igreja_id=TENANT,
                pessoa_id=prayer.person,
                nome="Ator S3 sintético",
                email="s3-prayer@example.test",
                clerk_user_id="s3-prayer-synthetic",
                status="ativo",
            )
        )
        db.flush()
        db.add(UserRole(igreja_id=TENANT, user_id=uid, papel="pastor"))
        db.add(
            Pessoa(
                id=target,
                igreja_id=TENANT,
                nome="Alvo Sintético",
                telefone="5500000000099",
            )
        )
        db.flush()
        db.add(
            CelulaMembro(
                igreja_id=TENANT, celula_id=prayer.cell, pessoa_id=target, ativo=True
            )
        )

    choices_seen = _fake_choices(monkeypatch, prayer, "registrar_decisao")
    request = inbound(prayer, "Registre decisão de Alvo Sintético")
    transport = _ClassifiedEvolution()
    worker.run_agent_for_message(prayer.factory, request, evolution_client=transport)
    with prayer.factory() as db:
        proposal = db.execute(select(AgentActionProposal)).scalar_one()
        assert proposal.state == "pendente"
        assert proposal.delivered_at is not None
        assert db.get(Message, proposal.summary_message_id).agent_reply_state == "ia"
        proposal_id = proposal.id
    assert choices_seen == ["s3_route", "s3_tool", "s3_handle"]
    return target, proposal_id, choices_seen


@pytest.mark.parametrize(
    "history,prayer_enabled",
    [
        ("executed", True),
        ("cancelled", True),
        ("expired", True),
        ("pending_expired", True),
        ("recent_expired", True),
        ("executed", False),
    ],
)
def test_historical_prayer_does_not_capture_real_s3_confirmation(
    prayer, monkeypatch, history, prayer_enabled
):
    from app.db.models import AgentActionProposal, AgentActionReceipt, Decision

    if history == "executed":
        create_request(prayer)
    else:
        send(prayer, "Peço oração por mim: força nesta semana.")
        send(prayer, "Só pastores")
        if history == "cancelled":
            send(prayer, "NÃO")
        else:
            with prayer.factory.begin() as db:
                row = db.execute(select(PrayerProposal)).scalar_one()
                row.expires_at = dt.datetime.now(dt.UTC) - (
                    dt.timedelta(seconds=1)
                    if history == "recent_expired"
                    else dt.timedelta(days=2)
                )
                row.state = (
                    "pending"
                    if history in {"pending_expired", "recent_expired"}
                    else "expired"
                )
    if not prayer_enabled:
        monkeypatch.delenv("PRAYER_REQUEST_ENABLED_IGREJA_IDS")
    target, proposal_id, choices_seen = _enable_s3_for_prayer_contact(
        prayer, monkeypatch
    )
    confirmation = inbound(prayer, "SIM")
    transport = _ClassifiedEvolution()
    worker.run_agent_for_message(
        prayer.factory, confirmation, evolution_client=transport
    )
    assert len(transport.calls) == 1
    assert "Comprovante:" in transport.calls[0][2]
    assert "oração" not in transport.calls[0][2].casefold()
    with prayer.factory() as db:
        assert db.get(AgentActionProposal, proposal_id).state == "executada"
        assert (
            db.scalar(
                select(func.count())
                .select_from(Decision)
                .where(Decision.pessoa_id == target)
            )
            == 1
        )
        receipt = db.execute(select(AgentActionReceipt)).scalar_one()
        assert receipt.confirmation_message_id == confirmation.inbound_message_id
        reply = (
            db.execute(
                select(Message)
                .where(
                    Message.conversation_id == prayer.conv,
                    Message.direcao == "out",
                )
                .order_by(Message.criado_em.desc())
            )
            .scalars()
            .first()
        )
        assert reply.agent_reply_state == "ia"
        assert reply.agent_privilege_context["kind"] == "receipt"
        assert db.scalar(select(func.count()).select_from(PrayerRequest)) == (
            1 if history == "executed" else 0
        )
    assert choices_seen == ["s3_route", "s3_tool", "s3_handle"]


def test_live_prayer_sim_remains_on_its_own_protocol(prayer):
    from app.db.models import AgentActionProposal

    row = create_request(prayer)
    with prayer.factory() as db:
        assert db.get(PrayerProposal, row.proposal_id).state == "executed"
        assert db.scalar(select(func.count()).select_from(AgentActionProposal)) == 0


def _assert_prayer_yields_sim(prayer):
    from app.prayer.turn import run_prayer_turn

    transport = _ClassifiedEvolution()
    assert (
        run_prayer_turn(
            prayer.factory,
            prayer.factory,
            inbound(prayer, "SIM"),
            igreja_id=TENANT,
            uses_dedicated_agent_session=False,
            ownership_guard=None,
            evolution_client=transport,
        )
        is None
    )
    assert transport.calls == []


@pytest.mark.parametrize("elapsed", [1, 61])
def test_prayer_expiry_notice_is_bounded_to_one_minute(prayer, elapsed):
    send(prayer, "Peço oração por mim: força.")
    send(prayer, "Só pastores")
    with prayer.factory.begin() as db:
        proposal = db.execute(select(PrayerProposal)).scalar_one()
        proposal.expires_at = service.now(db) - dt.timedelta(seconds=elapsed)
    if elapsed == 1:
        _, reply, transport = send(prayer, "SIM")
        assert transport.calls
        assert "expirou" in reply.texto
        assert reply.agent_reply_state == "ia"
    else:
        _assert_prayer_yields_sim(prayer)
    with prayer.factory() as db:
        assert db.scalar(select(func.count()).select_from(PrayerRequest)) == 0
