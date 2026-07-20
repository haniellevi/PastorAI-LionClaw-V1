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

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

import app.db.session  # noqa: F401 - registra o listener after_begin (paridade prod)
from app.db.models import Base, Igreja, WhatsappConnection
from app.domain.conversations import ParsedMessage
from app.domain.phone import normalize_phone
from app.workers.queue_worker import (
    IngestionResult,
    QueueWorker,
    WebhookQueue,
    _Envelope,
    ingest_message_event_ex,
)

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


def _parsed(
    *,
    provider_message_id: str,
    instance: str = "igreja-1",
    telefone: str = "5511988887777",
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
        from_me=False,
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
    session2 = factory()
    try:
        second = ingest_message_event_ex(session2, parsed)
    finally:
        session2.close()

    # Sem o índice, nada impede a 2ª ingestão — prova que o índice é o fix.
    assert first.result is IngestionResult.REGISTERED
    assert second.result is IngestionResult.REGISTERED
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
