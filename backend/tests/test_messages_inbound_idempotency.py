"""MSG-IDEMP-1 — prova, contra Postgres real, que o índice único parcial
`messages_inbound_provider_id_uidx` (migration
`20260715_204540_msg_idemp1_messages_inbound_provider_id_uidx.sql`, refletido
em `Message.__table_args__`) fecha a duplicação de mensagem INBOUND quando a
marca do Redis (`WebhookQueue.mark_processed_if_new`) expira, falta ou perde
uma corrida — e que o CÓDIGO de produção (`ingest_message_event_ex` /
`QueueWorker.handle_envelope`) devolve `IngestionResult.DUPLICATE` em vez de
duplicar a linha ou rodar o agente de novo.

Não dá pra provar constraint/corrida de banco com FakeSession (SQL nunca roda
de verdade) — por isso esta suíte é `rls_integration`, opt-in via
`RLS_TEST_DATABASE_URL` (mesmo guard de produção de `tests/conftest_rls.py`):
sem a env var, skip limpo; com ela, roda de verdade contra um Postgres
descartável, schema próprio (`Base.metadata.create_all` — o MESMO índice do
model real, não uma cópia manual do SQL).

Mapa:
  * test_same_message_after_redis_mark_lost_is_deduped_by_db — sequencial:
    2ª ingestão do MESMO provider_message_id (Redis já teria dito "novo" de
    novo, TTL expirado/flush) é rejeitada pelo índice, vira DUPLICATE, nenhuma
    Pessoa/Conversation/Message extra.
  * test_concurrent_sessions_same_message_only_one_registers — corrida real:
    duas sessões independentes ingerem a MESMA mensagem em paralelo; uma
    REGISTERED, a outra DUPLICATE (nunca as duas), efeito único.
  * test_different_provider_ids_both_persist — mensagens diferentes continuam
    livres.
  * test_same_provider_id_different_igreja_does_not_conflict — multi-tenant:
    o mesmo id de provider em igrejas diferentes não colide.
  * test_without_index_duplicate_reproduces — regressão: índice dropado ->
    volta a duplicar. Prova que o índice é o fix, não um acidente de outro
    caminho do código.
  * test_agent_does_not_rerun_when_redis_mark_is_lost — ponta-a-ponta via
    `QueueWorker.handle_envelope`: Redis "esquece" (stub que sempre diz
    "novo"); só o índice do banco impede a reingestão, e por isso o agente
    (run_agent_for_message) nunca dispara uma 2ª vez para a mesma mensagem.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

import app.db.session  # noqa: F401 - registra o listener after_begin (paridade prod)
from app.db.models import Base, Conversation, Igreja, Message, WhatsappConnection
from app.domain.conversations import ParsedMessage
from app.domain.phone import normalize_phone
from app.workers.queue_worker import (
    IngestionResult,
    QueueWorker,
    WebhookQueue,
    _Envelope,
    ClaimOwnershipLost,
    ingest_message_event_ex,
    run_agent_for_message,
)
from app.workers import queue_worker as worker_module

# Fixture opt-in (guard de produção + skip sem a env var). noqa: F401 — fixture
# do pytest usada por injeção, não importação "morta".
from tests.conftest_rls import rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration

# Schema dedicado (via search_path) para NÃO colidir com o `public` da suíte RLS
# nem com o `sec4b_create` de outra suíte, no MESMO banco descartável.
_SCHEMA = "msg_idemp1"

_IGREJA_A = uuid.UUID("2a2a2a2a-0000-0000-0000-00000000aa01")
_IGREJA_B = uuid.UUID("2b2b2b2b-0000-0000-0000-00000000bb01")


# ---------------------------------------------------------------------------
# Schema + seed no banco descartável
# ---------------------------------------------------------------------------
@pytest.fixture
def msg_engine_fx(rls_database_url: str) -> Iterator[Engine]:
    """Engine contra o Postgres descartável, schema próprio recriado do zero.

    `ingest_message_event_ex` chama `promote_to_tenant` -> `SET LOCAL ROLE
    authenticated` de verdade (fail-closed, ver app/db/tenant_session.py); por
    isso o papel é criado aqui (idempotente) e recebe GRANT amplo no schema —
    nenhuma RLS é habilitada nestas tabelas (create_all não expressa policy),
    então o grant é só para o INSERT/SELECT não esbarrar em falta de
    permissão após o SET ROLE.
    """
    engine = create_engine(
        rls_database_url,
        future=True,
        connect_args={"options": f"-c search_path={_SCHEMA}"},
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"drop schema if exists {_SCHEMA} cascade; create schema {_SCHEMA};"
        )
        conn.exec_driver_sql(
            "do $$ begin "
            "if not exists (select 1 from pg_roles where rolname = 'authenticated') then "
            "create role authenticated nologin noinherit nobypassrls; "
            "end if; end $$;"
        )
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(f"grant usage on schema {_SCHEMA} to authenticated;")
        conn.exec_driver_sql(
            f"grant select, insert, update, delete on all tables in schema "
            f"{_SCHEMA} to authenticated;"
        )
        # ``run_agent_for_message`` also exercises the production scope probe.
        # Keep the disposable schema self-contained rather than depending on
        # the public RLS fixture used by a different integration suite.
        conn.exec_driver_sql(
            f"create or replace function {_SCHEMA}.current_igreja_id() "
            "returns uuid language sql stable as $$ "
            "select nullif(current_setting('app.tenant_igreja_id', true), '')::uuid "
            "$$;"
        )
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade;")
        engine.dispose()


def _factory(engine: Engine) -> sessionmaker:
    # expire_on_commit=False espelha o get_session_factory() de produção.
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def _seed_igreja_with_connection(
    factory: sessionmaker, *, igreja_id: uuid.UUID, instance: str
) -> None:
    session = factory()
    try:
        session.add(Igreja(id=igreja_id, nome="Igreja"))
        session.flush()
        session.add(WhatsappConnection(igreja_id=igreja_id, instance=instance))
        session.commit()
    finally:
        session.close()


def _seed_agent_conversation(factory: sessionmaker, *, igreja_id: uuid.UUID) -> uuid.UUID:
    session = factory()
    try:
        conversation = Conversation(
            igreja_id=igreja_id,
            telefone="5511988887777",
            estado="ia",
            numero_oficial=True,
            nao_lidas=0,
        )
        session.add(conversation)
        session.commit()
        return conversation.id
    finally:
        session.close()


def _agent_outcome(
    conversation_id: uuid.UUID,
    *,
    provider_message_id: str = "AGENT-DELIVERY-ONCE",
    claim_id: str = "stable-claim-1",
) -> worker_module.IngestionOutcome:
    return worker_module.IngestionOutcome(
        result=IngestionResult.REGISTERED,
        conversation_id=conversation_id,
        instance="igreja-1",
        telefone="5511988887777",
        texto="Oi",
        inbound=True,
        igreja_id=_IGREJA_A,
        provider_message_id=provider_message_id,
        claim_id=claim_id,
    )


class _ClassifiedEvolution:
    def __init__(self, *statuses: str) -> None:
        self.statuses = list(statuses or ("aceito",))
        self.calls: list[tuple[str | None, str | None, str]] = []
        self.lock = threading.Lock()

    def send_text_classificado(self, instance, telefone, texto):
        with self.lock:
            self.calls.append((instance, telefone, texto))
            status = self.statuses.pop(0) if self.statuses else "aceito"
        return SimpleNamespace(status=status)


def _agent_reply_states(factory: sessionmaker, igreja_id: uuid.UUID) -> list[str]:
    session = factory()
    try:
        return list(
            session.execute(
                text(
                    "select autor from messages where igreja_id = :i "
                    "and provider_message_id like 'agent-reply:%' order by criado_em"
                ),
                {"i": str(igreja_id)},
            ).scalars()
        )
    finally:
        session.close()


def _parsed(
    *,
    provider_message_id: str,
    instance: str = "igreja-1",
    telefone: str = "5511988887777",
    from_me: bool = False,
) -> ParsedMessage:
    """Espelha o contrato do parse_message_event de produção: `telefone` é o
    parâmetro BRUTO (como vem do JID); `ParsedMessage.telefone` recebe a chave
    canônica via normalize_phone e `telefone_raw` preserva o bruto. Com o valor
    bruto nos dois campos, a confirmação canônica do dedupe de Pessoa nunca
    bate e a 2ª ingestão do MESMO número tentava recriar a Pessoa — colidindo
    com `uq_pessoas_telefone_ativa` (UNIQ-PESSOA-1) em vez de reconhecê-la.
    """
    return ParsedMessage(
        instance=instance,
        provider_message_id=provider_message_id,
        telefone=normalize_phone(telefone),
        telefone_raw=telefone,
        texto="Oi",
        push_name="João",
        from_me=from_me,
    )


def _count_messages(factory: sessionmaker, igreja_id: uuid.UUID) -> int:
    session = factory()
    try:
        return int(
            session.execute(
                text("select count(*) from messages where igreja_id = :i"),
                {"i": str(igreja_id)},
            ).scalar_one()
        )
    finally:
        session.close()


def _count_messages_by_direction(
    factory: sessionmaker, igreja_id: uuid.UUID, direction: str
) -> int:
    session = factory()
    try:
        return int(
            session.execute(
                text(
                    "select count(*) from messages "
                    "where igreja_id = :i and direcao = :d"
                ),
                {"i": str(igreja_id), "d": direction},
            ).scalar_one()
        )
    finally:
        session.close()


def _count_pessoas(factory: sessionmaker, igreja_id: uuid.UUID) -> int:
    session = factory()
    try:
        return int(
            session.execute(
                text("select count(*) from pessoas where igreja_id = :i"),
                {"i": str(igreja_id)},
            ).scalar_one()
        )
    finally:
        session.close()


def _count_conversations(factory: sessionmaker, igreja_id: uuid.UUID) -> int:
    session = factory()
    try:
        return int(
            session.execute(
                text("select count(*) from conversations where igreja_id = :i"),
                {"i": str(igreja_id)},
            ).scalar_one()
        )
    finally:
        session.close()


def _run_two_ingests(
    factory: sessionmaker, *, parsed: ParsedMessage
) -> dict[int, IngestionResult]:
    """Duas sessões independentes ingerem a MESMA mensagem em paralelo.

    Cada thread abre a própria sessão e só dispara após a barreira — maximiza
    a sobreposição real da corrida.
    """
    barrier = threading.Barrier(2)
    out: dict[int, IngestionResult] = {}

    def worker(idx: int) -> None:
        session = factory()
        try:
            barrier.wait(timeout=15)
            outcome = ingest_message_event_ex(session, parsed)
            out[idx] = outcome.result
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    return out


# ---------------------------------------------------------------------------
# Sequencial: marca do Redis "perdida" (TTL expirado / flush / indisponível)
# ---------------------------------------------------------------------------
def test_same_message_after_redis_mark_lost_is_deduped_by_db(
    msg_engine_fx: Engine,
) -> None:
    factory = _factory(msg_engine_fx)
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA_A, instance="igreja-1")
    parsed = _parsed(provider_message_id="DUP-SEQ")

    session1 = factory()
    try:
        first = ingest_message_event_ex(session1, parsed)
    finally:
        session1.close()

    # 2ª "entrega": Redis já disse "novo" de novo (TTL/flush) — só o banco
    # ainda sabe que essa mensagem já foi persistida.
    session2 = factory()
    try:
        second = ingest_message_event_ex(session2, parsed)
    finally:
        session2.close()

    assert first.result is IngestionResult.REGISTERED
    assert second.result is IngestionResult.DUPLICATE
    assert _count_messages(factory, _IGREJA_A) == 1
    assert _count_pessoas(factory, _IGREJA_A) == 1
    assert _count_conversations(factory, _IGREJA_A) == 1


# ---------------------------------------------------------------------------
# Corrida real: duas sessões concorrentes, mesma mensagem
# ---------------------------------------------------------------------------
def test_concurrent_sessions_same_message_only_one_registers(
    msg_engine_fx: Engine,
) -> None:
    factory = _factory(msg_engine_fx)
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA_A, instance="igreja-1")
    parsed = _parsed(provider_message_id="DUP-RACE")

    out = _run_two_ingests(factory, parsed=parsed)

    assert sorted(out.values(), key=str) == sorted(
        [IngestionResult.REGISTERED, IngestionResult.DUPLICATE], key=str
    ), out
    # Mesmo com as DUAS sessões tendo passado pelo lookup de Pessoa/Conversation
    # antes de qualquer commit, o rollback da transação perdedora desfaz TUDO
    # que ela tinha preparado — nunca sobra Pessoa/Conversation órfã.
    assert _count_messages(factory, _IGREJA_A) == 1
    assert _count_pessoas(factory, _IGREJA_A) == 1
    assert _count_conversations(factory, _IGREJA_A) == 1


# ---------------------------------------------------------------------------
# Mensagens diferentes / tenants diferentes continuam livres
# ---------------------------------------------------------------------------
def test_different_provider_ids_both_persist(msg_engine_fx: Engine) -> None:
    factory = _factory(msg_engine_fx)
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA_A, instance="igreja-1")

    session1 = factory()
    try:
        r1 = ingest_message_event_ex(session1, _parsed(provider_message_id="ID-1"))
    finally:
        session1.close()
    session2 = factory()
    try:
        r2 = ingest_message_event_ex(session2, _parsed(provider_message_id="ID-2"))
    finally:
        session2.close()

    assert r1.result is IngestionResult.REGISTERED
    assert r2.result is IngestionResult.REGISTERED
    assert _count_messages(factory, _IGREJA_A) == 2


def test_same_provider_id_different_igreja_does_not_conflict(
    msg_engine_fx: Engine,
) -> None:
    factory = _factory(msg_engine_fx)
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA_A, instance="igreja-a")
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA_B, instance="igreja-b")

    session1 = factory()
    try:
        r1 = ingest_message_event_ex(
            session1, _parsed(provider_message_id="SHARED-ID", instance="igreja-a")
        )
    finally:
        session1.close()
    session2 = factory()
    try:
        r2 = ingest_message_event_ex(
            session2, _parsed(provider_message_id="SHARED-ID", instance="igreja-b")
        )
    finally:
        session2.close()

    assert r1.result is IngestionResult.REGISTERED
    assert r2.result is IngestionResult.REGISTERED
    assert _count_messages(factory, _IGREJA_A) == 1
    assert _count_messages(factory, _IGREJA_B) == 1


def test_same_outbound_provider_id_is_deduped_by_db(msg_engine_fx: Engine) -> None:
    """A barreira outbound real aceita uma entrega e rejeita a repetição."""
    factory = _factory(msg_engine_fx)
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA_A, instance="igreja-1")

    # O fluxo outbound só persiste para um contato conhecido. Uma inbound única
    # cria Pessoa/Conversation usando exatamente o caminho de produção.
    seed_session = factory()
    try:
        seed = ingest_message_event_ex(
            seed_session,
            _parsed(provider_message_id="OUTBOUND-CONTACT-SEED"),
        )
    finally:
        seed_session.close()
    assert seed.result is IngestionResult.REGISTERED

    outbound = _parsed(provider_message_id="OUTBOUND-DUP", from_me=True)
    first_session = factory()
    try:
        first = ingest_message_event_ex(first_session, outbound)
    finally:
        first_session.close()
    second_session = factory()
    try:
        second = ingest_message_event_ex(second_session, outbound)
    finally:
        second_session.close()

    assert first.result is IngestionResult.REGISTERED
    assert second.result is IngestionResult.DUPLICATE
    assert _count_messages_by_direction(factory, _IGREJA_A, "out") == 1


# ---------------------------------------------------------------------------
# Regressão: sem o índice, a duplicação volta
# ---------------------------------------------------------------------------
def test_without_index_duplicate_reproduces(msg_engine_fx: Engine) -> None:
    with msg_engine_fx.begin() as conn:
        conn.exec_driver_sql(
            f"drop index {_SCHEMA}.messages_inbound_provider_id_uidx"
        )

    factory = _factory(msg_engine_fx)
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA_A, instance="igreja-1")
    parsed = _parsed(provider_message_id="NO-INDEX-DUP")

    session1 = factory()
    try:
        first = ingest_message_event_ex(session1, parsed)
    finally:
        session1.close()
    assert first.result is IngestionResult.REGISTERED

    # O advisory fence da aplicação ainda rejeitaria uma segunda chamada pelo
    # caminho normal. A inserção direta isola a última barreira do banco: sem o
    # índice, outra sessão/integração consegue persistir a mesma chave.
    with msg_engine_fx.begin() as conn:
        conn.execute(
            text(
                "insert into messages "
                "(id, igreja_id, conversation_id, direcao, autor, texto, "
                "provider_message_id) "
                "select :new_id, igreja_id, conversation_id, direcao, autor, "
                "texto, provider_message_id from messages "
                "where igreja_id = :igreja_id and provider_message_id = :pid "
                "limit 1"
            ),
            {
                "new_id": str(uuid.uuid4()),
                "igreja_id": str(_IGREJA_A),
                "pid": parsed.provider_message_id,
            },
        )

    assert _count_messages(factory, _IGREJA_A) == 2


# ---------------------------------------------------------------------------
# Ponta-a-ponta: agente nunca roda 2x quando o Redis "esquece"
# ---------------------------------------------------------------------------
class _AlwaysNewRedis:
    """Simula Redis com a marca de idempotência perdida (TTL expirado, flush ou
    indisponibilidade recuperada): `set(nx=True)` sempre devolve sucesso, como
    se a chave nunca tivesse existido — a mesma condição que uma redelivery da
    Evolution depois de PROCESSED_TTL_SECONDS (ou de um Redis reiniciado) causa
    em produção.
    """

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        return True

    def delete(self, key: str) -> None:
        pass

    def eval(self, script: str, numkeys: int, *args: object) -> int:
        # CAS de `mark_processed`/`release_processed`: este stub modela a perda
        # posterior da marca, não uma disputa de ownership durante a chamada.
        return 1


def _payload(message_id: str, *, instance: str = "igreja-1") -> dict:
    return {
        "event": "messages.upsert",
        "instance": instance,
        "data": {
            "key": {
                "remoteJid": "5511988887777@s.whatsapp.net",
                "fromMe": False,
                "id": message_id,
            },
            "pushName": "João",
            "message": {"conversation": "Oi"},
        },
    }


def test_agent_does_not_rerun_when_redis_mark_is_lost(msg_engine_fx: Engine) -> None:
    factory = _factory(msg_engine_fx)
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA_A, instance="igreja-1")

    queue = WebhookQueue(redis_client=_AlwaysNewRedis())
    agent_calls: list = []
    worker = QueueWorker(
        queue=queue,
        session_factory=factory,
        agent_runner=lambda *args: agent_calls.append(args),
    )

    payload = _payload("AGENT-ONCE")
    first = worker.handle_envelope(_Envelope(payload=payload))
    second = worker.handle_envelope(_Envelope(payload=payload))

    assert first is IngestionResult.REGISTERED
    assert second is IngestionResult.DUPLICATE
    assert len(agent_calls) == 1
    assert _count_messages(factory, _IGREJA_A) == 1


# ---------------------------------------------------------------------------
# AGENT-DELIVERY-ONCE — outbound intent before Evolution (Postgres real)
# ---------------------------------------------------------------------------
def _stub_agent(monkeypatch, response: str = "Resposta da IA") -> list[str]:
    from app.agent import runtime as runtime_module

    calls: list[str] = []

    def process(_session, **_kwargs):
        calls.append("agent")
        return SimpleNamespace(handled=True, suppressed=False, response=response)

    monkeypatch.setattr(runtime_module, "process_inbound_message", process)
    return calls


def _seed_agent_delivery(factory: sessionmaker) -> uuid.UUID:
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA_A, instance="igreja-1")
    return _seed_agent_conversation(factory, igreja_id=_IGREJA_A)


def test_agent_reply_timeout_is_quarantined_and_never_auto_resent(
    msg_engine_fx: Engine, monkeypatch
) -> None:
    factory = _factory(msg_engine_fx)
    conversation_id = _seed_agent_delivery(factory)
    agent_calls = _stub_agent(monkeypatch)
    evolution = _ClassifiedEvolution("desconhecido")
    outcome = _agent_outcome(conversation_id)

    run_agent_for_message(factory, outcome, evolution_client=evolution)
    run_agent_for_message(factory, outcome, evolution_client=evolution)

    assert agent_calls == ["agent"]
    assert evolution.calls == [("igreja-1", "5511988887777", "Resposta da IA")]
    assert _agent_reply_states(factory, _IGREJA_A) == ["ia_ambigua"]


def test_agent_reply_retryable_failure_releases_intent_without_rerunning_agent(
    msg_engine_fx: Engine, monkeypatch
) -> None:
    factory = _factory(msg_engine_fx)
    conversation_id = _seed_agent_delivery(factory)
    agent_calls = _stub_agent(monkeypatch)
    evolution = _ClassifiedEvolution("falhou_retentavel", "aceito")
    outcome = _agent_outcome(conversation_id)

    with pytest.raises(worker_module.AgentReplyRetryable):
        run_agent_for_message(factory, outcome, evolution_client=evolution)
    run_agent_for_message(factory, outcome, evolution_client=evolution)

    assert agent_calls == ["agent"]
    assert len(evolution.calls) == 2
    assert _agent_reply_states(factory, _IGREJA_A) == ["ia"]


def test_agent_reply_suppressed_is_recorded_and_never_auto_resent(
    msg_engine_fx: Engine, monkeypatch
) -> None:
    factory = _factory(msg_engine_fx)
    conversation_id = _seed_agent_delivery(factory)
    agent_calls = _stub_agent(monkeypatch)
    evolution = _ClassifiedEvolution("suprimido")
    outcome = _agent_outcome(conversation_id)

    run_agent_for_message(factory, outcome, evolution_client=evolution)
    run_agent_for_message(factory, outcome, evolution_client=evolution)

    assert agent_calls == ["agent"]
    assert len(evolution.calls) == 1
    assert _agent_reply_states(factory, _IGREJA_A) == ["ia_suprimida"]


def test_agent_reply_recovery_after_intent_before_transport_reuses_text_once(
    msg_engine_fx: Engine, monkeypatch
) -> None:
    factory = _factory(msg_engine_fx)
    conversation_id = _seed_agent_delivery(factory)
    outcome = _agent_outcome(conversation_id)
    prepared = worker_module._prepare_agent_reply_intent(
        factory, outcome, "Resposta persistida"
    )
    assert prepared is not None
    agent_calls = _stub_agent(monkeypatch)
    evolution = _ClassifiedEvolution("aceito")

    # Simulates a worker crash after its durable intent commit and before the
    # provider call; the recovered claim must not invoke the LLM again.
    run_agent_for_message(factory, outcome, evolution_client=evolution)
    run_agent_for_message(factory, outcome, evolution_client=evolution)

    assert agent_calls == []
    assert evolution.calls == [("igreja-1", "5511988887777", "Resposta persistida")]
    assert _agent_reply_states(factory, _IGREJA_A) == ["ia"]


def test_agent_reply_confirmation_persist_failure_is_quarantined_without_second_send(
    msg_engine_fx: Engine, monkeypatch
) -> None:
    factory = _factory(msg_engine_fx)
    conversation_id = _seed_agent_delivery(factory)
    agent_calls = _stub_agent(monkeypatch)
    evolution = _ClassifiedEvolution("aceito")
    original_transition = worker_module._transition_agent_reply_intent
    failed_once = False

    def fail_confirmation(*args, **kwargs):
        nonlocal failed_once
        if kwargs.get("target") == worker_module._AGENT_REPLY_CONFIRMED and not failed_once:
            failed_once = True
            raise RuntimeError("simulated final persistence loss")
        return original_transition(*args, **kwargs)

    monkeypatch.setattr(worker_module, "_transition_agent_reply_intent", fail_confirmation)
    outcome = _agent_outcome(conversation_id)

    run_agent_for_message(factory, outcome, evolution_client=evolution)
    run_agent_for_message(factory, outcome, evolution_client=evolution)

    assert agent_calls == ["agent"]
    assert len(evolution.calls) == 1
    assert _agent_reply_states(factory, _IGREJA_A) == ["ia_ambigua"]


def test_agent_reply_loss_before_transport_releases_pending_without_provider_call(
    msg_engine_fx: Engine, monkeypatch
) -> None:
    factory = _factory(msg_engine_fx)
    conversation_id = _seed_agent_delivery(factory)
    _stub_agent(monkeypatch)
    evolution = _ClassifiedEvolution("aceito")
    guard_calls = 0

    def guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 6:
            raise ClaimOwnershipLost("lease lost immediately before transport")

    with pytest.raises(ClaimOwnershipLost):
        run_agent_for_message(
            factory,
            _agent_outcome(conversation_id),
            guard,
            evolution_client=evolution,
        )

    assert evolution.calls == []
    assert _agent_reply_states(factory, _IGREJA_A) == ["ia_pendente"]


def test_agent_reply_loss_during_transport_never_retries_an_inflight_call(
    msg_engine_fx: Engine, monkeypatch
) -> None:
    factory = _factory(msg_engine_fx)
    conversation_id = _seed_agent_delivery(factory)
    agent_calls = _stub_agent(monkeypatch)
    evolution = _ClassifiedEvolution("aceito")
    guard_calls = 0

    def guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 7:
            raise ClaimOwnershipLost("lease lost after provider transport")

    outcome = _agent_outcome(conversation_id)
    with pytest.raises(ClaimOwnershipLost):
        run_agent_for_message(factory, outcome, guard, evolution_client=evolution)
    run_agent_for_message(factory, outcome, evolution_client=evolution)

    assert agent_calls == ["agent"]
    assert len(evolution.calls) == 1
    assert _agent_reply_states(factory, _IGREJA_A) == ["ia_em_transporte"]


@pytest.mark.parametrize("workers", [2, 5, 10])
def test_agent_reply_concurrent_recovered_claims_execute_once_before_transport(
    msg_engine_fx: Engine, monkeypatch, workers: int
) -> None:
    """PostgreSQL single-flight holds under 2/5/10 concurrent claim recoveries."""

    factory = _factory(msg_engine_fx)
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA_A, instance="igreja-1")

    from app.agent import runtime as runtime_module

    for repetition in range(3):
        conversation_id = _seed_agent_conversation(factory, igreja_id=_IGREJA_A)
        start = threading.Barrier(workers)
        agent_started = threading.Event()
        release_agent = threading.Event()
        agent_calls: list[str] = []
        agent_lock = threading.Lock()
        outcomes: list[BaseException] = []
        dispositions: list[worker_module.AgentRunDisposition] = []

        def process(_session, **_kwargs):
            with agent_lock:
                agent_calls.append("agent")
            agent_started.set()
            assert release_agent.wait(timeout=10)
            return SimpleNamespace(
                handled=True,
                suppressed=False,
                response="Resposta concorrente",
            )

        monkeypatch.setattr(runtime_module, "process_inbound_message", process)
        evolution = _ClassifiedEvolution("aceito")
        outcome = _agent_outcome(
            conversation_id,
            provider_message_id=f"AGENT-CONCURRENT-{workers}-{repetition}",
            claim_id=f"stable-concurrent-claim-{workers}-{repetition}",
        )

        def worker() -> None:
            try:
                start.wait(timeout=10)
                disposition = run_agent_for_message(
                    factory,
                    outcome,
                    evolution_client=evolution,
                )
                dispositions.append(disposition)
            except BaseException as exc:  # noqa: BLE001 - surface worker failure to test
                outcomes.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(workers)]
        for thread in threads:
            thread.start()
        assert agent_started.wait(timeout=10)
        release_agent.set()
        for thread in threads:
            thread.join(timeout=20)

        assert not outcomes
        assert all(not thread.is_alive() for thread in threads)
        assert agent_calls == ["agent"]
        assert len(evolution.calls) <= 1
        assert _agent_reply_states(factory, _IGREJA_A)[-1:] == ["ia"]
        assert worker_module.AgentRunDisposition.COMPLETED in dispositions


def test_agent_execution_lease_keeps_postgres_connection_checked_out(
    msg_engine_fx: Engine,
) -> None:
    """A competing PostgreSQL session cannot reenter the live agent lease."""

    engine = create_engine(
        msg_engine_fx.url,
        future=True,
        pool_size=1,
        max_overflow=1,
        pool_timeout=2,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    outcome = _agent_outcome(
        uuid.uuid4(),
        provider_message_id="AGENT-LEASE-CONNECTION",
        claim_id="stable-lease-connection",
    )
    provider_message_id = worker_module._agent_reply_idempotency_key(outcome)
    assert provider_message_id is not None
    lock_key = worker_module._agent_execution_lock_key(outcome, provider_message_id)
    lease = worker_module._AgentExecutionLease(
        factory,
        outcome,
        provider_message_id,
    )
    lease_closed = False
    try:
        assert lease.acquire()
        competing = factory()
        competing_acquired = False
        try:
            competing_acquired = bool(
                competing.execute(
                    select(func.pg_try_advisory_lock(lock_key))
                ).scalar_one()
            )
            assert not competing_acquired
        finally:
            if competing_acquired:
                competing.execute(select(func.pg_advisory_unlock(lock_key))).scalar_one()
            competing.commit()
            competing.close()

        lease.close()
        lease_closed = True
        verifier = factory()
        try:
            assert bool(
                verifier.execute(
                    select(func.pg_try_advisory_lock(lock_key))
                ).scalar_one()
            )
            verifier.execute(select(func.pg_advisory_unlock(lock_key))).scalar_one()
            verifier.commit()
        finally:
            verifier.close()
    finally:
        if not lease_closed:
            lease.close()
        engine.dispose()


def test_agent_execution_lease_invalidates_after_acquire_commit_failure(
    msg_engine_fx: Engine, monkeypatch
) -> None:
    """A failed acquire commit cannot leave the advisory lock in the pool."""

    engine = create_engine(
        msg_engine_fx.url,
        future=True,
        pool_size=1,
        max_overflow=1,
        pool_timeout=2,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    outcome = _agent_outcome(
        uuid.uuid4(),
        provider_message_id="AGENT-LEASE-COMMIT-FAILURE",
        claim_id="stable-lease-commit-failure",
    )
    provider_message_id = worker_module._agent_reply_idempotency_key(outcome)
    assert provider_message_id is not None
    lock_key = worker_module._agent_execution_lock_key(outcome, provider_message_id)
    lease = worker_module._AgentExecutionLease(
        factory,
        outcome,
        provider_message_id,
    )

    def fail_commit(_connection) -> None:
        raise RuntimeError("forced commit failure after advisory lock")

    try:
        with monkeypatch.context() as context:
            context.setattr(worker_module.Connection, "commit", fail_commit)
            with pytest.raises(RuntimeError, match="forced commit failure"):
                lease.acquire()

        # Hold the pooled connection that would retain the lock in the old
        # implementation, then use an overflow connection as a true competitor.
        pooled_connection = engine.connect()
        competing_connection = engine.connect()
        try:
            assert bool(
                competing_connection.execute(
                    select(func.pg_try_advisory_lock(lock_key))
                ).scalar_one()
            )
            competing_connection.execute(
                select(func.pg_advisory_unlock(lock_key))
            ).scalar_one()
            competing_connection.commit()
        finally:
            competing_connection.close()
            pooled_connection.close()
    finally:
        lease.close()
        engine.dispose()


def test_agent_reply_reservation_survives_crash_before_agent_and_uses_stable_key(
    msg_engine_fx: Engine, monkeypatch
) -> None:
    """A committed reservation can be retried without deriving identity from text."""

    factory = _factory(msg_engine_fx)
    conversation_id = _seed_agent_delivery(factory)
    outcome = _agent_outcome(
        conversation_id,
        provider_message_id="AGENT-RESERVATION-CRASH",
        claim_id="stable-reservation-crash",
    )
    key = worker_module._agent_reply_idempotency_key(outcome)
    assert key is not None

    # Simulate a process crash after its durable reservation commit but before
    # it acquired the execution lease or invoked the agent.
    reserved = worker_module._reserve_agent_reply_intent(factory, outcome)
    assert reserved is not None
    assert reserved.provider_message_id == key
    assert reserved.state == worker_module._AGENT_REPLY_RESERVED
    assert reserved.response == ""

    agent_calls = _stub_agent(monkeypatch, response="Resposta não participa da chave")
    evolution = _ClassifiedEvolution("aceito")
    run_agent_for_message(factory, outcome, evolution_client=evolution)

    assert agent_calls == ["agent"]
    assert len(evolution.calls) == 1
    session = factory()
    try:
        message = session.execute(
            text(
                "select provider_message_id, autor from messages "
                "where igreja_id = :i and provider_message_id = :key"
            ),
            {"i": str(_IGREJA_A), "key": key},
        ).one()
    finally:
        session.close()
    assert message.provider_message_id == key
    assert message.autor == "ia"


def test_agent_reply_owner_loss_after_reservation_runs_no_agent_or_tool(
    msg_engine_fx: Engine, monkeypatch
) -> None:
    """A lease loss immediately before the turn leaves a recoverable reservation."""

    factory = _factory(msg_engine_fx)
    conversation_id = _seed_agent_delivery(factory)
    agent_calls = _stub_agent(monkeypatch)
    evolution = _ClassifiedEvolution("aceito")
    guard_calls = 0

    def guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 3:
            raise ClaimOwnershipLost("lease lost before agent execution")

    outcome = _agent_outcome(
        conversation_id,
        provider_message_id="AGENT-OWNER-LOSS",
        claim_id="stable-owner-loss",
    )
    with pytest.raises(ClaimOwnershipLost):
        run_agent_for_message(factory, outcome, guard, evolution_client=evolution)

    assert agent_calls == []
    assert evolution.calls == []
    assert _agent_reply_states(factory, _IGREJA_A) == ["ia_reservada"]

    # The retry owns the same persisted claim and performs the one permitted
    # agent turn; no stale owner can have produced an earlier side effect.
    run_agent_for_message(factory, outcome, evolution_client=evolution)
    assert agent_calls == ["agent"]
    assert len(evolution.calls) == 1
    assert _agent_reply_states(factory, _IGREJA_A) == ["ia"]


def test_agent_reply_recovers_legacy_response_hash_intent_without_rerunning_agent(
    msg_engine_fx: Engine, monkeypatch
) -> None:
    """A pre-single-flight intent remains the only durable plan after upgrade."""

    factory = _factory(msg_engine_fx)
    conversation_id = _seed_agent_delivery(factory)
    outcome = _agent_outcome(
        conversation_id,
        provider_message_id="AGENT-LEGACY-INTENT",
        claim_id="stable-legacy-intent",
    )
    stable_key = worker_module._agent_reply_idempotency_key(outcome)
    assert stable_key is not None

    session = factory()
    try:
        session.add(
            Message(
                igreja_id=_IGREJA_A,
                conversation_id=conversation_id,
                direcao="out",
                autor="ia_pendente",
                texto="Resposta já persistida antes da atualização",
                provider_message_id=f"{stable_key}:legacy-response-hash",
            )
        )
        session.commit()
    finally:
        session.close()

    agent_calls = _stub_agent(monkeypatch)
    evolution = _ClassifiedEvolution("aceito")
    run_agent_for_message(factory, outcome, evolution_client=evolution)

    assert agent_calls == []
    assert evolution.calls == [
        ("igreja-1", "5511988887777", "Resposta já persistida antes da atualização")
    ]
    session = factory()
    try:
        count = session.execute(
            text(
                "select count(*) from messages where igreja_id = :i "
                "and direcao = 'out' and provider_message_id like :key"
            ),
            {"i": str(_IGREJA_A), "key": f"{stable_key}%"},
        ).scalar_one()
    finally:
        session.close()
    assert count == 1
