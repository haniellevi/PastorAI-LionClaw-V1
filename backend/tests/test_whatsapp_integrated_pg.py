"""F2b: actual migrations/RLS, Redis claim/ack, worker and authenticated inbox.

Only provider HTTP is ASGI-local. Auth uses real signed session tokens; tenant,
catalog, confirmation and domain services are unchanged. Disposable resources
are guarded before access. Redis keys and databases have per-test identities.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import threading
import time
import uuid
from functools import partial
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import psycopg2
import pytest
import redis
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

import app.db.session  # noqa: F401 - real after_begin tenant listener
from app.config import Settings, get_settings
from app.db.models import (
    AgentActionProposal, AgentActionReceipt, AgentConfig, AgentConversationLog, AppUser, Celula,
    CelulaExpectativaVisitante, CelulaMembro, CelulaReuniao, ConsentRecord,
    Conversation, Igreja, LlmCredential, Message, Pessoa, UserRole,
    WhatsappConnection,
)
from app.db.session import get_db
from app.db.tenant_session import mark_tenant_scoped
from app.routers import conversations, whatsapp
from app.services import crypto, whatsapp_privilege
from app.services.clerk import ClerkClient, get_clerk_client
from app.services.evolution import EvolutionClient
from app.workers import queue_worker as qw
from devtools.simulador_whatsapp import create_app, _payload_entrada
from scripts import migrate
from tests.conftest_rls import rls_database_url  # noqa: F401 - disposable guard

pytestmark = pytest.mark.rls_integration
_REAL_PILOT = Settings.whatsapp_piloto
_REAL_REPLY_ENABLED = qw._whatsapp_reply_enabled
_PRIVATE_NAME = "Visitante Sintético"
_COMMAND = f"indicar {_PRIVATE_NAME} como visitante na próxima reunião da minha célula"


@pytest.fixture
def migrated_factory(rls_database_url):
    """Bootstrap the Supabase roles/default ACLs, then run active SQL unchanged."""
    admin_url = make_url(rls_database_url).set(drivername="postgresql")
    if admin_url.host not in {"127.0.0.1", "::1"} or admin_url.database != "rls_disposable":
        raise ValueError("F2b requires a disposable loopback Postgres database")
    name = "f2b_" + uuid.uuid4().hex + "_test"
    admin = psycopg2.connect(admin_url.render_as_string(hide_password=False))
    admin.autocommit = True
    with admin.cursor() as cursor:
        for role, bypass in (("anon", False), ("authenticated", False), ("service_role", True)):
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
            if cursor.fetchone() is None:
                cursor.execute(f"CREATE ROLE {role} NOLOGIN {'BYPASSRLS' if bypass else 'NOBYPASSRLS'}")
            # Roles are cluster-wide: earlier isolated tests may have created
            # service_role without BYPASSRLS. Re-establish this fixture's
            # canonical Supabase roles only in the guarded disposable cluster.
            cursor.execute(f"ALTER ROLE {role} NOLOGIN {'BYPASSRLS' if bypass else 'NOBYPASSRLS'}")
        cursor.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname='authenticated'")
        assert cursor.fetchone() == (False,)
        cursor.execute(f"CREATE DATABASE {name}")
    url = admin_url.set(database=name).render_as_string(hide_password=False)
    engine = None
    try:
        with psycopg2.connect(url) as connection:
            with connection.cursor() as cursor:
                for obj in ("TABLES", "SEQUENCES", "FUNCTIONS"):
                    cursor.execute("ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
                                   f"GRANT ALL ON {obj} TO anon, authenticated, service_role")
                cursor.execute("CREATE TABLE public.schema_migrations "
                               "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        for filename in migrate.migration_files():
            body = (migrate.MIGRATIONS_DIR / filename).read_text()
            concurrent = any("index concurrently" in line.lower() for line in body.splitlines()
                             if not line.lstrip().startswith("--"))
            connection = psycopg2.connect(url)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    migrate.cmd_apply(connection, filename, transactional=not concurrent)
            finally:
                connection.close()
        engine = create_engine(url)
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        if engine is not None:
            engine.dispose()
        with admin.cursor() as cursor:
            cursor.execute(f"DROP DATABASE {name} WITH (FORCE)")
        admin.close()


@pytest.fixture
def integrated_turn(migrated_factory, monkeypatch):
    raw = os.environ.get("F2B_TEST_REDIS_URL")
    if not raw:
        pytest.skip("F2B_TEST_REDIS_URL must identify disposable loopback Redis")
    parsed = urlsplit(raw)
    if parsed.scheme != "redis" or parsed.hostname not in {"127.0.0.1", "::1"}:
        raise ValueError("F2b Redis must be a literal loopback address")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Unexpected F2b Redis routing")
    cache = redis.Redis.from_url(raw, decode_responses=True, socket_timeout=7)
    assert cache.ping()
    prefix = "f2b:" + uuid.uuid4().hex + ":"
    for symbol in ("WEBHOOK_QUEUE", "PROCESSING_QUEUE", "DEAD_LETTER_QUEUE",
                   "SCHEDULED_RETRY_QUEUE", "RETRY_STATE_PREFIX", "PROCESSED_PREFIX",
                   "WORKER_REGISTRY", "WORKER_LEASE_PREFIX", "WORKER_RECOVERY_LOCK_PREFIX"):
        monkeypatch.setattr(qw, symbol, prefix + getattr(qw, symbol))
    monkeypatch.setattr(Settings, "whatsapp_piloto", _REAL_PILOT)
    monkeypatch.setattr(qw, "_whatsapp_reply_enabled", _REAL_REPLY_ENABLED)
    a, b = uuid.uuid4(), uuid.uuid4()
    for key, value in {
        "APP_ENV": "development", "ALLOW_REAL_SENDS": "false",
        "WHATSAPP_TRANSPORTE": "simulado", "EVOLUTION_SIMULADOR_URL": "http://simulador-whatsapp:8090",
        "EVOLUTION_WEBHOOK_SECRET": "synthetic-f2b-webhook", "BREVO_SEND_MODE": "off",
        "ASAAS_BILLING_ENABLED": "false", "WHATSAPP_PILOTO_IGREJA_IDS": f"{a},{b}",
        "AGENT_PRIVILEGE_ENABLED_IGREJA_IDS": f"{a},{b}",
        "SESSION_JWT_SECRET": "synthetic-f2b-session-secret-with-sufficient-length",
        "SECRETS_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(whatsapp_privilege, "PRIVILEGE_APPROVED_RELEASE_ID", "synthetic-f2b")
    get_settings.cache_clear()
    crypto._get_fernet.cache_clear()
    settings = get_settings()
    factory = migrated_factory
    users = []
    tomorrow = dt.date.today() + dt.timedelta(days=7)
    with factory.begin() as session:
        for index, tenant in enumerate((a, b)):
            person, user, cell, meeting = (uuid.uuid4() for _ in range(4))
            phone = f"55000000000{index:02d}"
            subject = f"synthetic-f2b-{index}"
            session.add(Igreja(id=tenant, nome=f"Igreja Sintética {index}"))
            session.flush()
            session.add(Pessoa(id=person, igreja_id=tenant, nome="Membro Sintético", telefone=phone))
            session.flush()
            session.add(AppUser(id=user, igreja_id=tenant, pessoa_id=person, nome="Usuário Sintético",
                                email=f"f2b-{index}@example.test", clerk_user_id=subject, status="ativo"))
            session.flush()
            session.add(UserRole(igreja_id=tenant, user_id=user, papel="pastor"))
            session.add(Celula(id=cell, igreja_id=tenant, nome="Célula Sintética", lider_id=person,
                              cobertura_espiritual="Cobertura sintética", ativo=True))
            session.flush()
            session.add(CelulaMembro(igreja_id=tenant, celula_id=cell, pessoa_id=person, ativo=True))
            session.add(CelulaReuniao(id=meeting, igreja_id=tenant, celula_id=cell,
                                    data=tomorrow, hora="20:00", status="planejada"))
            session.add(ConsentRecord(igreja_id=tenant, pessoa_id=person,
                                      termo_versao=settings.agent_term_version,
                                      aceite_em=dt.datetime.now(dt.timezone.utc)))
            session.add(WhatsappConnection(igreja_id=tenant, instance=f"f2b-{index}"))
            session.add(AgentConfig(igreja_id=tenant, comportamento="Sintético", ativo=True))
            session.add(LlmCredential(igreja_id=tenant, provedor="openai", modelo="gpt-5.6-luna",
                                      api_key_encrypted=crypto.encrypt_secret("synthetic-no-provider"),
                                      validado=True, ativo=True))
            users.append(SimpleNamespace(tenant=tenant, person=person, user=user, cell=cell,
                                         meeting=meeting, phone=phone, subject=subject, instance=f"f2b-{index}"))
    queue = qw.WebhookQueue(redis_client=cache)
    backend = FastAPI()
    backend.include_router(whatsapp.router)
    backend.include_router(conversations.router)
    backend.dependency_overrides[whatsapp.get_webhook_queue] = lambda: queue
    def db():
        with factory() as session:
            yield session
    backend.dependency_overrides[get_db] = db
    clerk = ClerkClient(settings)
    backend.dependency_overrides[get_clerk_client] = lambda: clerk
    api = TestClient(backend, base_url="http://backend:8000")
    simulator = create_app(webhook_url="http://backend:8000/whatsapp/webhook",
                           webhook_secret=settings.evolution_webhook_secret, webhook_client=api)
    ui = TestClient(simulator, base_url="http://simulador-whatsapp:8090")
    evolution = EvolutionClient(settings)
    evolution._client = ui
    # No provider traffic may escape these ASGI clients. Redis/Postgres use their
    # own guarded transports and are intentionally real.
    http_send = httpx.Client.send
    def local_http(client, *args, **kwargs):
        if not isinstance(client, TestClient):
            raise AssertionError("Unexpected external HTTP in F2b")
        return http_send(client, *args, **kwargs)
    monkeypatch.setattr(httpx.Client, "send", local_http)
    errors = []
    worker = qw.QueueWorker(queue=queue, session_factory=factory,
                            agent_runner=partial(qw.run_agent_for_message, evolution_client=evolution),
                            heartbeat_publisher=lambda *_args: None)
    def run():
        try:
            worker.run()
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    def wait(predicate):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            assert not errors, [type(e).__name__ for e in errors]
            if predicate():
                return
            time.sleep(0.02)
        pytest.fail("F2b worker did not reach the expected committed state")
    def rows(model, tenant=a):
        with factory() as session:
            mark_tenant_scoped(session, tenant, source="f2b-assertion")
            assert session.execute(text("SELECT current_user")).scalar_one() == "authenticated"
            return session.scalars(select(model)).all()
    def send(message, *, actor=users[0]):
        before = sum(row.direcao == "in" for row in rows(Message, actor.tenant))
        response = ui.post("/simulador/mensagens", json={"instance": actor.instance,
                           "telefone": actor.phone, "texto": message})
        assert response.status_code == 200 and response.json()["webhook_status"] == 202
        wait(lambda: sum(row.direcao == "in" for row in rows(Message, actor.tenant)) == before + 1
             and cache.llen(qw.WEBHOOK_QUEUE) == 0
             and cache.llen(queue.processing_queue(worker._worker_id)) == 0)
        assert cache.llen(qw.DEAD_LETTER_QUEUE) == 0
        return response.json()
    try:
        wait(lambda: bool(cache.get(queue._lease_key(worker._worker_id))))
        yield SimpleNamespace(factory=factory, users=users, cache=cache, queue=queue, worker=worker,
                              send=send, rows=rows, wait=wait, api=api, ui=ui, clerk=clerk)
    finally:
        worker.stop()
        thread.join(timeout=8)
        assert not thread.is_alive(), "F2b worker leaked"
        api.close()
        ui.close()
        clerk.close()
        keys = list(cache.scan_iter(match=prefix + "*"))
        if keys:
            cache.delete(*keys)
        cache.close()
        get_settings.cache_clear()
        crypto._get_fernet.cache_clear()


def test_visitor_queue_confirmation_rls_and_authenticated_inbox(integrated_turn):
    t = integrated_turn
    t.send(_COMMAND)
    proposals = t.rows(AgentActionProposal)
    assert len(proposals) == 1 and proposals[0].state == "pendente", {
        "messages": [(m.direcao, m.agent_reply_state) for m in t.rows(Message)],
        "people": len(t.rows(Pessoa)),
        "conversations": [(c.estado, str(c.pessoa_id)) for c in t.rows(Conversation)],
        "events": [(e.evento, e.payload) for e in t.rows(AgentConversationLog)],
    }
    assert not t.rows(CelulaExpectativaVisitante)
    t.send("SIM")
    assert len(t.rows(CelulaExpectativaVisitante)) == len(t.rows(AgentActionReceipt)) == 1
    delivered = t.ui.get("/simulador/mensagens").json()
    assert any(m["direcao"] == "saida" and "Comprovante:" in m["texto"] for m in delivered)
    assert t.rows(AgentActionProposal)[0].state == "executada"
    t.send("SIM")
    assert len(t.rows(CelulaExpectativaVisitante)) == len(t.rows(AgentActionReceipt)) == 1
    conversation = t.rows(Conversation)[0]
    url = f"/conversations/{conversation.id}/messages"
    assert t.api.get(url).status_code == 401
    token = t.clerk._mint_session_token(t.users[0].subject)
    response = t.api.get(url, headers={"Authorization": "Bearer " + token})
    assert response.status_code == 200
    assert any(message["direcao"] == "out" for message in response.json()["items"])
    token_b = t.clerk._mint_session_token(t.users[1].subject)
    assert t.api.get(url, headers={"Authorization": "Bearer " + token_b}).status_code == 404
    assert not t.rows(CelulaExpectativaVisitante, t.users[1].tenant)
    # The foreign church must work positively, rather than merely see no rows.
    t.send(_COMMAND, actor=t.users[1])
    assert len(t.rows(AgentActionProposal, t.users[1].tenant)) == 1
    t.send("SIM", actor=t.users[1])
    foreign = t.rows(CelulaExpectativaVisitante, t.users[1].tenant)
    assert len(foreign) == 1 and foreign[0].pessoa_id == t.users[1].person
    assert t.rows(CelulaExpectativaVisitante)[0].pessoa_id == t.users[0].person
    # No explicit tenant filter here: PostgreSQL must reject the foreign write.
    with t.factory() as session:
        mark_tenant_scoped(session, t.users[0].tenant, source="f2b-foreign-write")
        session.add(Pessoa(igreja_id=t.users[1].tenant, nome="Sintético recusado"))
        with pytest.raises(DBAPIError) as error:
            session.flush()
        assert error.value.orig.pgcode == "42501"
        session.rollback()


def test_same_inbound_replay_has_one_effect(integrated_turn):
    t = integrated_turn
    t.send(_COMMAND)
    confirmed = t.send("SIM")
    before = len(t.rows(Message))
    actor = t.users[0]
    payload = _payload_entrada(instance=actor.instance, telefone=actor.phone, texto="SIM",
                             nome="Sintético", numero_oficial="5500000000000", message_id=confirmed["id"])
    response = t.api.post("/whatsapp/webhook", json=payload,
                          headers={"x-webhook-token": "synthetic-f2b-webhook"})
    assert response.status_code == 202
    t.wait(lambda: t.cache.llen(qw.WEBHOOK_QUEUE) == 0
           and t.cache.llen(t.queue.processing_queue(t.worker._worker_id)) == 0)
    assert len(t.rows(Message)) == before
    assert len(t.rows(CelulaExpectativaVisitante)) == len(t.rows(AgentActionReceipt)) == 1


def test_failure_before_commit_rolls_back_effect_and_receipt_then_retries(integrated_turn):
    t = integrated_turn
    t.send(_COMMAND)
    assert len(t.rows(AgentActionProposal)) == 1
    entered, release = threading.Event(), threading.Event()
    def fail_once(session):
        if entered.is_set() or session.get_bind() is not t.factory.kw["bind"]:
            return
        with session.no_autoflush:
            effects = session.scalar(select(func.count()).select_from(CelulaExpectativaVisitante))
            receipts = session.scalar(select(func.count()).select_from(AgentActionReceipt))
        if effects == receipts == 1:
            entered.set()
            assert release.wait(timeout=8), "F2b fault injection timed out"
            raise RuntimeError("SYNTHETIC_F2B_BEFORE_COMMIT")
    event.listen(t.factory.class_, "before_commit", fail_once)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(t.send, "SIM")
            try:
                assert entered.wait(timeout=8)
                assert not t.rows(CelulaExpectativaVisitante)
                assert not t.rows(AgentActionReceipt)
            finally:
                release.set()
            pending.result(timeout=12)
    finally:
        release.set()
        event.remove(t.factory.class_, "before_commit", fail_once)
    assert len(t.rows(CelulaExpectativaVisitante)) == len(t.rows(AgentActionReceipt)) == 1
    assert t.rows(AgentActionProposal)[0].state == "executada"


def test_authenticated_inbox_denied_after_role_revocation(integrated_turn):
    t = integrated_turn
    t.send(_COMMAND)
    url = f"/conversations/{t.rows(Conversation)[0].id}/messages"
    headers = {"Authorization": "Bearer " + t.clerk._mint_session_token(t.users[0].subject)}
    assert t.api.get(url, headers=headers).status_code == 200
    with t.factory.begin() as session:
        for role in session.scalars(select(UserRole).where(UserRole.user_id == t.users[0].user)):
            session.delete(role)
    assert t.api.get(url, headers=headers).status_code == 403


def test_unaccepted_term_does_not_prepare_action(integrated_turn):
    t = integrated_turn
    with t.factory.begin() as session:
        for record in session.scalars(select(ConsentRecord).where(ConsentRecord.pessoa_id == t.users[0].person)):
            session.delete(record)
    t.send(_COMMAND)
    assert not t.rows(AgentActionProposal)
    assert not t.rows(CelulaExpectativaVisitante)


def test_membership_revoked_between_proposal_and_confirmation_has_no_effect(integrated_turn):
    t = integrated_turn
    t.send(_COMMAND)
    assert len(t.rows(AgentActionProposal)) == 1
    with t.factory.begin() as session:
        member = session.scalar(select(CelulaMembro).where(CelulaMembro.pessoa_id == t.users[0].person))
        member.ativo = False
    t.send("SIM")
    assert not t.rows(CelulaExpectativaVisitante)
    assert not t.rows(AgentActionReceipt)


def test_optout_prevents_action_and_transport(integrated_turn):
    t = integrated_turn
    t.send("SAIR")
    t.send(_COMMAND)
    assert t.rows(Pessoa)[0].optout is True
    assert not t.rows(AgentActionProposal)
    assert not t.rows(CelulaExpectativaVisitante)
    assert not [m for m in t.rows(Message) if m.direcao == "out" and m.texto]


def test_reply_reader_legacy_tenant_and_transaction_fence(integrated_turn):
    from app.db.rls_observability import TenantScopeVerificationError
    from app.domain.provider_identity import provider_message_lock_key
    from app.services.agent_reply_reader import ReplyReadContext, load_agent_reply_intent

    t = integrated_turn
    t.send(_COMMAND)
    key = "agent-reply:synthetic-legacy-reader"
    with t.factory.begin() as session:
        for actor in t.users:
            conversation = session.scalar(select(Conversation).where(Conversation.igreja_id == actor.tenant))
            if conversation is None:
                conversation = Conversation(igreja_id=actor.tenant, telefone=actor.phone, pessoa_id=actor.person)
                session.add(conversation)
                session.flush()
            session.add(Message(igreja_id=actor.tenant, conversation_id=conversation.id,
                                direcao="out", autor="ia", texto="Resposta sintética",
                                provider_message_id=key + ":old-response-hash", agent_reply_state=None))
    a, b = (u.tenant for u in t.users)
    with t.factory() as session, t.factory() as contender:
        mark_tenant_scoped(session, a, source="f2b-reader")
        intent = load_agent_reply_intent(session, ReplyReadContext(a, key))
        assert intent.state == "ia" and intent.response == "Resposta sintética"
        assert intent.provider_message_id == key + ":old-response-hash"
        assert load_agent_reply_intent(session, ReplyReadContext(a, key + "-absent")) is None
        assert contender.scalar(select(func.pg_try_advisory_xact_lock(provider_message_lock_key(a, key)))) is False
        session.rollback()
        assert contender.scalar(select(func.pg_try_advisory_xact_lock(provider_message_lock_key(a, key)))) is True
    with t.factory() as session:
        mark_tenant_scoped(session, b, source="f2b-reader")
        other = load_agent_reply_intent(session, ReplyReadContext(b, key))
        assert other.id != intent.id
        with pytest.raises(TenantScopeVerificationError):
            load_agent_reply_intent(session, ReplyReadContext(a, key))
