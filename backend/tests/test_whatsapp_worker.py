"""Tests for the webhook queue worker: idempotency, reprocess and ingestion."""

from __future__ import annotations

import json
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Conversation, Message, Pessoa, WhatsappConnection
from app.domain.conversations import parse_message_event
from app.domain.phone import normalize_phone
from app.workers.queue_worker import (
    DEAD_LETTER_QUEUE,
    MAX_ATTEMPTS,
    REDIS_CONNECT_TIMEOUT_SECONDS,
    REDIS_MAX_CONNECTIONS,
    REDIS_SOCKET_TIMEOUT_SECONDS,
    WEBHOOK_QUEUE,
    WORKER_LEASE_SECONDS,
    WORKER_REGISTRY,
    ClaimOwnershipLost,
    IngestionOutcome,
    IngestionResult,
    QueueWorker,
    WebhookQueue,
    _Envelope,
    _build_redis,
    ingest_message_event,
    ingest_message_event_ex,
    process_webhook_payload,
    run_agent_for_message,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeRedis:
    """Minimal in-memory Redis stand-in for queue + idempotency keys."""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.kv: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.direct_lrem_calls = 0
        self.failed_transition_calls = 0
        self.fence_calls: list[tuple[str, str]] = []

    def lpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).insert(0, value)

    def brpop(self, key: str, timeout: int = 0):
        items = self.lists.get(key)
        if not items:
            return None
        return key, items.pop()

    def brpoplpush(self, source: str, destination: str, timeout: int = 0):
        return self.rpoplpush(source, destination)

    def rpoplpush(self, source: str, destination: str):
        items = self.lists.get(source)
        if not items:
            return None
        value = items.pop()
        self.lpush(destination, value)
        return value

    def lrem(self, key: str, count: int, value: str) -> int:
        self.direct_lrem_calls += 1
        items = self.lists.get(key, [])
        removed = 0
        for index, item in list(enumerate(items)):
            if item == value and (count == 0 or removed < count):
                items.pop(index - removed)
                removed += 1
        return removed

    def set(
        self,
        key: str,
        value: str,
        nx: bool = False,
        xx: bool = False,
        ex: int | None = None,
    ) -> bool:
        if nx and key in self.kv:
            return False
        if xx and key not in self.kv:
            return False
        self.kv[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.kv.get(key)

    def delete(self, key: str) -> None:
        self.kv.pop(key, None)

    def exists(self, key: str) -> int:
        return int(key in self.kv)

    def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    def sadd(self, key: str, value: str) -> int:
        values = self.sets.setdefault(key, set())
        before = len(values)
        values.add(value)
        return int(len(values) != before)

    def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    def srem(self, key: str, value: str) -> int:
        values = self.sets.get(key, set())
        if value not in values:
            return 0
        values.remove(value)
        return 1

    def eval(self, script: str, numkeys: int, *values: str) -> int:
        if numkeys == 3 and "LREM" in script:
            # Failed claims move only when the same worker still owns both the
            # live lease and the raw item in its private processing list.  The
            # destination is persisted before removing the source claim so a
            # failed source removal stays recoverable rather than losing work.
            lease_key, processing, target, worker_id, raw, replacement = values
            self.failed_transition_calls += 1
            if self.kv.get(lease_key) != worker_id:
                return 0
            items = self.lists.get(processing, [])
            try:
                index = items.index(raw)
            except ValueError:
                return 0
            destination = self.lists.setdefault(target, [])
            if replacement not in destination:
                self.lpush(target, replacement)
            items.pop(index)
            return 1

        if numkeys == 3:  # marker mutation only for the live raw-item owner
            lease_key, processing, marker_key, worker_id, raw, expected, *rest = values
            if self.kv.get(lease_key) != worker_id:
                return 0
            if raw not in self.lists.get(processing, []):
                return 0
            if self.kv.get(marker_key) != expected:
                return 0
            if rest:
                done, _ttl = rest
                self.kv[marker_key] = done
            else:
                self.kv.pop(marker_key, None)
            return 1

        if "LRANGE" in script:  # atomic worker lease + private-list ownership
            lease_key, processing, worker_id, raw, *_ttl = values
            if self.kv.get(lease_key) != worker_id:
                return 0
            owned = raw in self.lists.get(processing, [])
            if owned and _ttl:
                self.fence_calls.append((worker_id, _ttl[0]))
            return int(owned)

        assert numkeys == 1
        key, *args = values
        if len(args) == 1:  # compare-and-delete
            expected = args[0]
            if self.kv.get(key) != expected:
                return 0
            self.kv.pop(key, None)
            return 1
        if len(args) == 3:  # compare-and-set marker -> done
            expected, done, _ttl = args
            current = self.kv.get(key)
            if current == expected:
                self.kv[key] = done
                return 1
            return int(current == done)
        raise AssertionError(f"Unsupported fake Lua call: {script!r}")


class _Scalar:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    # Candidate-narrowing dedupe uses .scalars().all(); the fake ignores the
    # WHERE clause and returns the routed row (or none) as the candidate list.
    def scalars(self):
        return self

    def all(self):
        return [] if self._value is None else [self._value]


class FakeIngestSession:
    """Routes selects by entity, records added rows; no real persistence."""

    def __init__(self, *, connection=None, pessoa=None, conversation=None) -> None:
        self._by_entity = {
            WhatsappConnection: connection,
            Pessoa: pessoa,
            Conversation: conversation,
        }
        self.added: list = []
        self.committed = False
        self.rolled_back = False
        # Records text() clauses (RLS set_config / set role) for assertions.
        self.tenant_calls: list[tuple[str, dict | None]] = []
        # O seam de tenant grava sua marca em session.info (mark_cross_tenant /
        # promote_to_tenant). Uma Session real sempre expõe .info; a fake precisa
        # provê-lo para atravessar o seam do worker (PR3-B).
        self.info: dict = {}

    def execute(self, statement, params=None) -> _Scalar:
        descriptions = getattr(statement, "column_descriptions", None)
        if not descriptions:
            # text() clause (e.g. set_tenant_context_for_igreja) — no routing.
            self.tenant_calls.append((str(statement), params))
            return _Scalar(None)
        entity = descriptions[0]["entity"]
        return _Scalar(self._by_entity.get(entity))

    def add(self, obj) -> None:
        self.added.append(obj)

    def begin_nested(self):
        # UNIQ-PESSOA-1: insert_pessoa_or_get_winner roda o INSERT num SAVEPOINT.
        # Sem corrida na fake (flush não levanta), o SAVEPOINT é um no-op.
        from contextlib import nullcontext

        return nullcontext()

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        pass


def _parsed_payload(message_id: str = "MSG1") -> dict:
    return {
        "event": "messages.upsert",
        "instance": "igreja-1",
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


# ---------------------------------------------------------------------------
# Ingestion (RNF-16 / US-07)
# ---------------------------------------------------------------------------
def test_ingest_skips_non_official_instance() -> None:
    # No connection matches the instance -> personal/non-official, dropped.
    session = FakeIngestSession(connection=None)
    from app.domain.conversations import parse_message_event

    parsed = parse_message_event(_parsed_payload())
    result = ingest_message_event(session, parsed)
    assert result is IngestionResult.SKIPPED_NOT_OFFICIAL
    assert session.added == []


def test_ingest_registers_and_creates_contact_and_conversation() -> None:
    connection = WhatsappConnection(
        igreja_id="00000000-0000-0000-0000-000000000001", instance="igreja-1"
    )
    session = FakeIngestSession(connection=connection, pessoa=None, conversation=None)
    from app.domain.conversations import parse_message_event

    parsed = parse_message_event(_parsed_payload())
    result = ingest_message_event(session, parsed)

    assert result is IngestionResult.REGISTERED
    assert session.committed is True
    # A new person, a new conversation and the message were added.
    assert any(isinstance(o, Pessoa) for o in session.added)
    assert any(isinstance(o, Conversation) for o in session.added)
    # Nasce como "contato" (US-10/#1): novo_contato na etapa ganhar.
    pessoa = next(o for o in session.added if isinstance(o, Pessoa))
    assert pessoa.etapa == "ganhar"
    assert pessoa.subetapa == "novo_contato"


def test_ingest_reuses_existing_contact() -> None:
    """RNF-16: an existing person (same phone) is reused, never duplicated."""
    connection = WhatsappConnection(
        igreja_id="00000000-0000-0000-0000-000000000001", instance="igreja-1"
    )
    existing = Pessoa(
        igreja_id="00000000-0000-0000-0000-000000000001",
        nome="João",
        telefone="5511988887777",
    )
    existing_conv = Conversation(
        igreja_id="00000000-0000-0000-0000-000000000001",
        telefone="5511988887777",
        estado="ia",
        nao_lidas=0,
    )
    session = FakeIngestSession(
        connection=connection, pessoa=existing, conversation=existing_conv
    )
    from app.domain.conversations import parse_message_event

    parsed = parse_message_event(_parsed_payload())
    result = ingest_message_event(session, parsed)

    assert result is IngestionResult.REGISTERED
    # No new Pessoa nor Conversation created.
    assert not any(isinstance(o, Pessoa) for o in session.added)
    assert not any(isinstance(o, Conversation) for o in session.added)
    assert existing_conv.nao_lidas == 1


def test_ingest_reuses_person_after_conversation_deleted() -> None:
    """M7B-W1 (regressão do incidente real): apagar a conversa remove só
    Conversation/Messages, não a Pessoa. Ao chegar nova mensagem pelo MESMO
    telefone+igreja, o worker reusa a Pessoa (nome/tipo preservados) e cria uma
    NOVA Conversation — nunca duplica a Pessoa nem rebaixa o tipo."""
    connection = WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1")
    existing = Pessoa(
        igreja_id=_IGREJA,
        nome="Raniel Levi",  # nome confiável, cadastrado
        telefone="5511988887777",
        tipo="membro",  # já é membro (vínculo ativo de célula)
    )
    # conversation=None simula a conversa apagada — não existe mais no banco.
    session = FakeIngestSession(
        connection=connection, pessoa=existing, conversation=None
    )
    parsed = parse_message_event(_parsed_payload("AFTER_DELETE"))
    result = ingest_message_event(session, parsed)

    assert result is IngestionResult.REGISTERED
    # Mesma Pessoa reutilizada — nenhuma nova criada.
    assert not any(isinstance(o, Pessoa) for o in session.added)
    # Tipo preservado: o worker nunca rebaixa (nada de voltar a "contato").
    assert existing.tipo == "membro"
    assert existing.nome == "Raniel Levi"
    # Uma nova Conversation é criada no lugar da apagada.
    assert any(isinstance(o, Conversation) for o in session.added)


def test_ingest_persists_provider_message_id() -> None:
    """MSG-IDEMP-1: a linha grava o id estável da Evolution — é a chave que o
    índice único parcial `messages_inbound_provider_id_uidx` (Postgres real,
    ver test_messages_inbound_idempotency.py) usa como 2ª barreira de dedupe."""
    connection = WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1")
    session = FakeIngestSession(connection=connection, pessoa=None, conversation=None)
    parsed = parse_message_event(_parsed_payload("PID1"))
    ingest_message_event_ex(session, parsed)
    msg = next(o for o in session.added if isinstance(o, Message))
    assert msg.provider_message_id == "PID1"


class _CommitIntegrityErrorSession(FakeIngestSession):
    def __init__(self, *, constraint_name: str) -> None:
        connection = WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1")
        pessoa = Pessoa(igreja_id=_IGREJA, nome="João", telefone="5511988887777")
        conversation = Conversation(
            igreja_id=_IGREJA,
            telefone="5511988887777",
            estado="ia",
            nao_lidas=0,
        )
        super().__init__(
            connection=connection,
            pessoa=pessoa,
            conversation=conversation,
        )
        self._constraint_name = constraint_name

    def commit(self) -> None:
        orig = SimpleNamespace(
            pgcode="23505",
            diag=SimpleNamespace(constraint_name=self._constraint_name),
        )
        raise IntegrityError("insert messages", {}, orig)


def test_ingest_treats_provider_id_index_violation_as_duplicate() -> None:
    session = _CommitIntegrityErrorSession(
        constraint_name="messages_inbound_provider_id_uidx"
    )

    outcome = ingest_message_event_ex(session, parse_message_event(_parsed_payload()))

    assert outcome.result is IngestionResult.DUPLICATE
    assert session.rolled_back is True


def test_ingest_treats_outbound_provider_index_violation_as_duplicate() -> None:
    session = _CommitIntegrityErrorSession(
        constraint_name="messages_outbound_provider_id_uidx"
    )
    payload = _parsed_payload("OUT-DUP")
    payload["data"]["key"]["fromMe"] = True

    outcome = ingest_message_event_ex(session, parse_message_event(payload))

    assert outcome.result is IngestionResult.DUPLICATE
    assert session.rolled_back is True


def test_ingest_does_not_mask_other_unique_violation_as_duplicate() -> None:
    session = _CommitIntegrityErrorSession(constraint_name="some_other_unique_idx")

    with pytest.raises(IntegrityError):
        ingest_message_event_ex(session, parse_message_event(_parsed_payload()))

    assert session.rolled_back is True


def test_ingest_sets_tenant_context_for_igreja() -> None:
    """Fase 0 (#10b): após resolver a igreja pelo instance, o worker ativa o
    tenant-context (GUC app.tenant_igreja_id + role authenticated) antes de
    qualquer escrita, e expõe igreja_id no outcome para o path do agente."""
    connection = WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1")
    session = FakeIngestSession(connection=connection, pessoa=None, conversation=None)
    parsed = parse_message_event(_parsed_payload())
    outcome = ingest_message_event_ex(session, parsed)

    assert outcome.result is IngestionResult.REGISTERED
    assert outcome.igreja_id == _IGREJA
    joined = " ".join(sql for sql, _ in session.tenant_calls)
    assert "app.tenant_igreja_id" in joined
    assert "set local role authenticated" in joined
    bound = [p for _, p in session.tenant_calls if p and "igreja_id" in p]
    assert bound and bound[0]["igreja_id"] == _IGREJA


def test_process_webhook_payload_ignores_non_message() -> None:
    session = FakeIngestSession()
    assert (
        process_webhook_payload(session, {"event": "connection.update"})
        is IngestionResult.IGNORED
    )


# ---------------------------------------------------------------------------
# Contact integrity: never ingest the church's own number; only inbound creates
# ---------------------------------------------------------------------------
_IGREJA = "00000000-0000-0000-0000-000000000001"


def test_parser_captures_owner_from_sender() -> None:
    payload = _parsed_payload()
    payload["sender"] = "558994711318@s.whatsapp.net"
    parsed = parse_message_event(payload)
    assert parsed is not None
    assert parsed.owner == normalize_phone("558994711318")


def test_ingest_ignores_church_own_number_via_sender() -> None:
    # A message whose contact == the instance owner (self-chat / connect sync)
    # must never become a contact.
    connection = WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1")
    session = FakeIngestSession(connection=connection)
    payload = {
        "event": "messages.upsert",
        "instance": "igreja-1",
        "sender": "558994711318@s.whatsapp.net",
        "data": {
            "key": {
                "remoteJid": "558994711318@s.whatsapp.net",
                "fromMe": True,
                "id": "SELF1",
            },
            "message": {"conversation": "x"},
        },
    }
    parsed = parse_message_event(payload)
    result = ingest_message_event(session, parsed)
    assert result is IngestionResult.IGNORED
    assert not any(isinstance(o, Pessoa) for o in session.added)


def test_ingest_ignores_official_number_via_connection_numero() -> None:
    # Fallback when the payload has no `sender`: the registered official number.
    connection = WhatsappConnection(
        igreja_id=_IGREJA, instance="igreja-1", numero="5511988887777"
    )
    session = FakeIngestSession(connection=connection)
    parsed = parse_message_event(_parsed_payload())  # remoteJid 5511988887777
    result = ingest_message_event(session, parsed)
    assert result is IngestionResult.IGNORED
    assert not any(isinstance(o, Pessoa) for o in session.added)


def test_ingest_outbound_to_unknown_does_not_create_contact() -> None:
    connection = WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1")
    session = FakeIngestSession(connection=connection, pessoa=None)
    payload = _parsed_payload()
    payload["data"]["key"]["fromMe"] = True  # outbound to a not-yet-known number
    parsed = parse_message_event(payload)
    result = ingest_message_event(session, parsed)
    assert result is IngestionResult.IGNORED
    assert not any(isinstance(o, Pessoa) for o in session.added)


def test_ingest_outbound_to_known_contact_still_records() -> None:
    # Outbound to an EXISTING contact is still recorded (no new contact created).
    connection = WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1")
    existing = Pessoa(igreja_id=_IGREJA, nome="João", telefone="5511988887777")
    existing_conv = Conversation(
        igreja_id=_IGREJA, telefone="5511988887777", estado="ia", nao_lidas=0
    )
    session = FakeIngestSession(
        connection=connection, pessoa=existing, conversation=existing_conv
    )
    payload = _parsed_payload()
    payload["data"]["key"]["fromMe"] = True
    parsed = parse_message_event(payload)
    result = ingest_message_event(session, parsed)
    assert result is IngestionResult.REGISTERED
    assert not any(isinstance(o, Pessoa) for o in session.added)


# ---------------------------------------------------------------------------
# Media ingestion (Etapa 2): download via resolver -> Storage pointer on the row
# ---------------------------------------------------------------------------
def _media_payload(message_id: str = "IMG1") -> dict:
    return {
        "event": "messages.upsert",
        "instance": "igreja-1",
        "data": {
            "key": {
                "remoteJid": "5511988887777@s.whatsapp.net",
                "fromMe": False,
                "id": message_id,
            },
            "pushName": "João",
            "message": {"imageMessage": {"mimetype": "image/jpeg"}},
        },
    }


def test_ingest_media_uploads_and_sets_fields() -> None:
    connection = WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1")
    session = FakeIngestSession(connection=connection, pessoa=None, conversation=None)

    stored = SimpleNamespace(
        path="igreja/conv/abc.jpg", mime="image/jpeg", nome=None, tamanho=42
    )
    calls: list = []

    def resolver(parsed, igreja_id, conversation_id):
        calls.append(parsed.media_kind)
        return stored

    parsed = parse_message_event(_media_payload())
    outcome = ingest_message_event_ex(session, parsed, media_resolver=resolver)

    assert outcome.result is IngestionResult.REGISTERED
    msg = next(o for o in session.added if isinstance(o, Message))
    assert msg.tipo == "imagem"
    assert msg.media_path == "igreja/conv/abc.jpg"
    assert msg.media_mime == "image/jpeg"
    assert msg.media_tamanho == 42
    assert calls == ["imagem"]


def test_media_resolver_reuses_injected_evolution_and_stable_object_id(
    monkeypatch,
) -> None:
    from app.services import evolution as evolution_module
    from app.services import storage as storage_module
    from app.workers import queue_worker as worker_module

    parsed = parse_message_event(_media_payload("IMG-STABLE"))
    evolution_calls: list[tuple[str, dict]] = []
    upload_calls: list[dict] = []

    class SharedEvolution:
        def get_media_base64(self, instance, key):
            evolution_calls.append((instance, key))
            return "aGVsbG8=", "image/jpeg"

    class FakeStorage:
        def upload(self, *args, **kwargs):
            upload_calls.append(kwargs)
            return SimpleNamespace(path="i/c/stable.jpg")

    def must_not_construct():  # pragma: no cover - failure path only
        raise AssertionError("resolver must reuse the worker-owned client")

    monkeypatch.setattr(evolution_module, "EvolutionClient", must_not_construct)
    monkeypatch.setattr(storage_module, "SupabaseStorage", FakeStorage)

    result = worker_module.resolve_media_via_evolution(
        parsed,
        "igreja-1",
        "conv-1",
        evolution_client=SharedEvolution(),
    )

    assert result.path == "i/c/stable.jpg"
    assert evolution_calls[0][0] == "igreja-1"
    assert upload_calls == [{"object_id": "IMG-STABLE"}]


def test_main_injects_one_evolution_client_into_both_hot_paths(monkeypatch) -> None:
    from app.services import evolution as evolution_module
    from app.workers import queue_worker as worker_module

    captured: dict = {}

    class SharedEvolution:
        def __enter__(self):
            captured["entered"] = captured.get("entered", 0) + 1
            return self

        def __exit__(self, *_args):
            captured["exited"] = captured.get("exited", 0) + 1

    shared = SharedEvolution()

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def stop(self, *_args):
            return None

        def run(self):
            captured["ran"] = True

    monkeypatch.setattr(evolution_module, "EvolutionClient", lambda: shared)
    monkeypatch.setattr(worker_module, "QueueWorker", FakeWorker)
    monkeypatch.setattr(worker_module.signal, "signal", lambda *_args: None)

    worker_module.main()

    assert captured["agent_runner"].keywords["evolution_client"] is shared
    assert captured["media_resolver"].keywords["evolution_client"] is shared
    assert captured["entered"] == 1
    assert captured["exited"] == 1
    assert captured["ran"] is True


def test_postgres_provider_fence_serializes_before_duplicate_lookup() -> None:
    from app.workers import queue_worker as worker_module

    statements: list[str] = []
    results = iter([None, SimpleNamespace(id="existing")])

    class FenceSession:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement):
            statements.append(str(statement))
            value = next(results)
            return SimpleNamespace(scalar_one_or_none=lambda: value)

    exists = worker_module._provider_message_exists_after_fence(
        FenceSession(),
        "igreja-1",
        "provider-1",
        inbound=True,
    )

    assert exists is True
    assert "pg_advisory_xact_lock" in statements[0]
    assert "provider_message_id" in statements[1]
    assert "direcao" in statements[1]
    assert worker_module._provider_message_lock_key("igreja-1", "provider-1") == (
        worker_module._provider_message_lock_key("igreja-1", "provider-1")
    )
    assert worker_module._provider_message_lock_key("igreja-1", "provider-1") != (
        worker_module._provider_message_lock_key("igreja-2", "provider-1")
    )


def test_ingest_media_degrades_when_resolver_fails() -> None:
    connection = WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1")
    session = FakeIngestSession(connection=connection, pessoa=None, conversation=None)

    def boom(parsed, igreja_id, conversation_id):
        raise RuntimeError("evolution down")

    parsed = parse_message_event(_media_payload())
    outcome = ingest_message_event_ex(session, parsed, media_resolver=boom)

    # A mensagem NÃO se perde: fica marcada como imagem, sem ponteiro de mídia.
    assert outcome.result is IngestionResult.REGISTERED
    msg = next(o for o in session.added if isinstance(o, Message))
    assert msg.tipo == "imagem"
    assert msg.media_path is None


def test_ingest_media_snippet_without_caption() -> None:
    connection = WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1")
    existing = Pessoa(igreja_id=_IGREJA, nome="João", telefone="5511988887777")
    conv = Conversation(
        igreja_id=_IGREJA, telefone="5511988887777", estado="ia", nao_lidas=0
    )
    session = FakeIngestSession(
        connection=connection, pessoa=existing, conversation=conv
    )

    stored = SimpleNamespace(path="p.jpg", mime="image/jpeg", nome=None, tamanho=10)
    parsed = parse_message_event(_media_payload())
    ingest_message_event_ex(session, parsed, media_resolver=lambda *a: stored)

    assert conv.ultima_mensagem == "📷 Imagem"


def test_ingest_text_message_has_no_media_resolver_call() -> None:
    # Mensagem de texto não dispara o resolver de mídia.
    connection = WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1")
    session = FakeIngestSession(connection=connection, pessoa=None, conversation=None)

    def resolver(*_a):  # pragma: no cover - não deve ser chamado
        raise AssertionError("resolver não deveria rodar para texto")

    parsed = parse_message_event(_parsed_payload())
    outcome = ingest_message_event_ex(session, parsed, media_resolver=resolver)
    assert outcome.result is IngestionResult.REGISTERED
    msg = next(o for o in session.added if isinstance(o, Message))
    assert msg.tipo == "texto"
    assert msg.media_path is None


# ---------------------------------------------------------------------------
# Queue idempotency + reprocess (RNF-16 / RNF-17)
# ---------------------------------------------------------------------------
def test_queue_enqueue_wraps_envelope() -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    queue.enqueue({"event": "messages.upsert"})
    raw = redis.lists[WEBHOOK_QUEUE][0]
    env = _Envelope.from_json(raw)
    assert env.attempts == 0
    assert env.payload == {"event": "messages.upsert"}
    assert env.claim_id


def test_envelope_serialization_preserves_claim_id() -> None:
    envelope = _Envelope(payload=_parsed_payload("SERIAL"))

    restored = _Envelope.from_json(envelope.to_json())

    assert restored.claim_id == envelope.claim_id
    assert _Envelope(payload=envelope.payload).claim_id != envelope.claim_id


def test_legacy_envelope_derives_stable_claim_id_from_raw() -> None:
    raw = json.dumps({"payload": _parsed_payload("LEGACY"), "attempts": 0})

    first = _Envelope.from_json(raw)
    recovered = _Envelope.from_json(raw)

    assert first.claim_id.startswith("legacy-")
    assert recovered.claim_id == first.claim_id


def test_mark_processed_accepts_only_the_same_claim_owner() -> None:
    queue = WebhookQueue(redis_client=FakeRedis())
    assert queue.mark_processed_if_new("MSG1", "claim-a") is True
    # The same recovered envelope may resume its in-flight claim.
    assert queue.mark_processed_if_new("MSG1", "claim-a") is True
    # A distinct delivery of the same provider id is blocked pre-ingestion.
    assert queue.mark_processed_if_new("MSG1", "claim-b") is False
    queue.mark_processed("MSG1", "claim-a")
    assert queue.mark_processed_if_new("MSG1", "claim-a") is False


def test_marker_cas_cannot_delete_or_finalize_a_new_owner() -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    assert queue.mark_processed_if_new("CAS", "old-owner") is True
    # Simulate expiry followed by a new claim before the old worker unwinds.
    redis.delete("pastorai:processed:CAS")
    assert queue.mark_processed_if_new("CAS", "new-owner") is True

    queue.release_processed("CAS", "old-owner")
    assert queue.mark_processed_if_new("CAS", "new-owner") is True
    with pytest.raises(RuntimeError, match="ownership was lost"):
        queue.mark_processed("CAS", "old-owner")
    queue.mark_processed("CAS", "new-owner")


def test_recovered_claim_marker_cannot_be_released_by_stale_worker() -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    queue.register_worker("marker-old")
    queue.register_worker("marker-new")
    queue.enqueue(_parsed_payload("MARKER-RECOVERY"))
    raw = queue.claim("marker-old", timeout=0)
    envelope = _Envelope.from_json(raw)
    assert queue.mark_processed_if_new(
        "MARKER-RECOVERY", envelope.claim_id
    ) is True

    redis.delete(queue._lease_key("marker-old"))  # noqa: SLF001
    assert queue.recover_pending("marker-new") == 1
    assert queue.claim("marker-new", timeout=0) == raw

    assert queue.release_processed_if_owned(
        "MARKER-RECOVERY", envelope.claim_id, "marker-old", raw
    ) is False
    assert queue.mark_processed_if_new(
        "MARKER-RECOVERY", envelope.claim_id
    ) is True
    assert queue.release_processed_if_owned(
        "MARKER-RECOVERY", envelope.claim_id, "marker-new", raw
    ) is True


def test_queue_claim_and_ack_use_processing_list() -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    worker_id = "worker-claim"
    queue.register_worker(worker_id)
    queue.enqueue(_parsed_payload("CLAIM"))

    raw = queue.claim(worker_id, timeout=0)

    assert raw is not None
    assert redis.lists[WEBHOOK_QUEUE] == []
    processing = queue.processing_queue(worker_id)
    assert redis.lists[processing] == [raw]
    queue.ack(worker_id, raw)
    assert redis.lists[processing] == []
    assert redis.direct_lrem_calls == 1


def test_effect_fence_atomically_renews_a_live_claim() -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    worker_id = "worker-fence"
    queue.register_worker(worker_id)
    queue.enqueue(_parsed_payload("FENCE"))
    raw = queue.claim(worker_id, timeout=0)

    queue.assert_claim_owned(worker_id, raw)

    assert redis.fence_calls == [(worker_id, str(WORKER_LEASE_SECONDS))]
    redis.delete(queue._lease_key(worker_id))  # noqa: SLF001
    with pytest.raises(ClaimOwnershipLost):
        queue.assert_claim_owned(worker_id, raw)


def test_recovery_does_not_steal_active_worker_claim() -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    queue.register_worker("worker-a")
    queue.register_worker("worker-b")
    queue.enqueue(_parsed_payload("ACTIVE"))
    raw = queue.claim("worker-a", timeout=0)

    assert queue.recover_pending("worker-b") == 0
    assert redis.lists[queue.processing_queue("worker-a")] == [raw]
    assert redis.lists[WEBHOOK_QUEUE] == []


def test_old_worker_stops_before_commit_after_live_claim_recovery() -> None:
    """A lease loser still alive cannot commit or run the external agent."""
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    old_worker_id = "worker-old-alive"
    new_worker_id = "worker-recovered"
    queue.register_worker(old_worker_id)
    queue.register_worker(new_worker_id)
    queue.enqueue(_media_payload("LEASE-RACE"))
    raw = queue.claim(old_worker_id, timeout=0)
    assert raw is not None

    media_started = Event()
    release_old_media = Event()
    media_calls: list[str] = []
    sessions: list[FakeIngestSession] = []
    agent_calls: list[IngestionOutcome] = []
    connection = WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1")

    def session_factory() -> FakeIngestSession:
        session = FakeIngestSession(connection=connection)
        sessions.append(session)
        return session

    def media_resolver(parsed, _igreja_id, _conversation_id):
        media_calls.append(parsed.provider_message_id)
        if len(media_calls) == 1:
            media_started.set()
            assert release_old_media.wait(timeout=2)
        return SimpleNamespace(
            path="stable/provider-object.jpg",
            mime="image/jpeg",
            nome=None,
            tamanho=4,
        )

    old_worker = QueueWorker(
        queue=queue,
        session_factory=session_factory,
        agent_runner=lambda _factory, outcome, _guard: agent_calls.append(outcome),
        media_resolver=media_resolver,
        worker_id=old_worker_id,
    )
    old_thread = Thread(target=old_worker._handle_raw, args=(raw,))  # noqa: SLF001
    old_thread.start()
    assert media_started.wait(timeout=2)

    # The old handler is still inside its upload when its lease expires. A live
    # worker recovers and claims the exact same raw envelope.
    redis.delete(queue._lease_key(old_worker_id))  # noqa: SLF001
    assert queue.recover_pending(new_worker_id) == 1
    recovered_raw = queue.claim(new_worker_id, timeout=0)
    assert recovered_raw == raw

    release_old_media.set()
    old_thread.join(timeout=2)
    assert not old_thread.is_alive()
    assert len(sessions) == 1
    assert sessions[0].committed is False
    assert agent_calls == []

    recovered_worker = QueueWorker(
        queue=queue,
        session_factory=session_factory,
        agent_runner=lambda _factory, outcome, _guard: agent_calls.append(outcome),
        media_resolver=media_resolver,
        worker_id=new_worker_id,
    )
    recovered_worker._handle_raw(recovered_raw)  # noqa: SLF001

    assert [session.committed for session in sessions] == [False, True]
    assert len(agent_calls) == 1
    # The in-flight upload may finish, but both attempts carry the same provider
    # id; SupabaseStorage maps it to one deterministic upsert object path.
    assert media_calls == ["LEASE-RACE", "LEASE-RACE"]
    assert redis.lists[queue.processing_queue(new_worker_id)] == []


def test_lease_recovery_between_ingest_and_agent_has_one_external_effect(
    monkeypatch,
) -> None:
    """A stale owner aborts; the recovered owner resumes the same claim once."""
    from app.workers import queue_worker as worker_module

    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    old_worker_id = "worker-agent-old"
    new_worker_id = "worker-agent-new"
    queue.register_worker(old_worker_id)
    queue.register_worker(new_worker_id)
    queue.enqueue(_parsed_payload("AGENT-LEASE-RACE"))
    raw = queue.claim(old_worker_id, timeout=0)
    assert raw is not None

    outcomes = iter(
        [
            IngestionOutcome(
                result=IngestionResult.REGISTERED,
                conversation_id="conversation-1",
                instance="igreja-1",
                telefone="5511988887777",
                texto="ola",
                inbound=True,
                igreja_id=_IGREJA,
            ),
            IngestionOutcome(
                result=IngestionResult.DUPLICATE,
                conversation_id="conversation-1",
                instance="igreja-1",
                telefone="5511988887777",
                texto="ola",
                inbound=True,
                igreja_id=_IGREJA,
            ),
        ]
    )
    monkeypatch.setattr(
        worker_module,
        "ingest_message_event_ex",
        lambda *_args, **_kwargs: next(outcomes),
    )
    session_factory = lambda: SimpleNamespace(close=lambda: None)  # noqa: E731
    recovered_raw: list[str] = []
    effects: list[str] = []

    def stale_agent(_factory, _outcome, ownership_guard) -> None:
        # Recovery wins after the worker's pre-runner fence but before the
        # runner's first effect fence.
        redis.delete(queue._lease_key(old_worker_id))  # noqa: SLF001
        assert queue.recover_pending(new_worker_id) == 1
        claimed = queue.claim(new_worker_id, timeout=0)
        assert claimed == raw
        recovered_raw.append(claimed)
        ownership_guard()
        effects.append("stale")  # pragma: no cover - ownership must abort first

    old_worker = QueueWorker(
        queue=queue,
        session_factory=session_factory,
        agent_runner=stale_agent,
        worker_id=old_worker_id,
    )
    old_worker._handle_raw(raw)  # noqa: SLF001

    assert effects == []
    assert recovered_raw == [raw]
    assert redis.get("pastorai:processed:AGENT-LEASE-RACE").startswith(
        "processing:"
    )

    def recovered_agent(_factory, _outcome, ownership_guard) -> None:
        ownership_guard()
        effects.append("recovered")

    new_worker = QueueWorker(
        queue=queue,
        session_factory=session_factory,
        agent_runner=recovered_agent,
        worker_id=new_worker_id,
    )
    new_worker._handle_raw(recovered_raw[0])  # noqa: SLF001

    assert effects == ["recovered"]
    assert redis.get("pastorai:processed:AGENT-LEASE-RACE") == "done"
    assert redis.lists[queue.processing_queue(new_worker_id)] == []


def test_agent_checks_ownership_immediately_before_whatsapp(monkeypatch) -> None:
    from app.agent import runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "process_inbound_message",
        lambda *_args, **_kwargs: SimpleNamespace(
            handled=True,
            suppressed=False,
            response="resposta",
        ),
    )

    class FakeEvolution:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        def send_text(self, instance, telefone, texto):
            self.calls.append((instance, telefone, texto))
            return True

    evolution = FakeEvolution()
    guard_calls = 0

    def ownership_guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 2:
            raise ClaimOwnershipLost("recovered before WhatsApp")

    session_factory = lambda: SimpleNamespace(close=lambda: None)  # noqa: E731
    outcome = IngestionOutcome(
        result=IngestionResult.REGISTERED,
        conversation_id="conversation-1",
        instance="igreja-1",
        telefone="5511988887777",
        texto="ola",
        inbound=True,
    )

    with pytest.raises(ClaimOwnershipLost, match="before WhatsApp"):
        run_agent_for_message(
            session_factory,
            outcome,
            ownership_guard,
            evolution_client=evolution,
        )

    assert guard_calls == 2
    assert evolution.calls == []


def test_unregister_keeps_orphan_with_pending_item_discoverable() -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    worker_id = "worker-pending"
    queue.register_worker(worker_id)
    redis.lpush(queue.processing_queue(worker_id), "raw")

    queue.unregister_worker(worker_id)

    assert not redis.exists(queue._lease_key(worker_id))  # noqa: SLF001
    assert worker_id in redis.smembers(WORKER_REGISTRY)


def test_worker_recovers_crashed_claim_without_losing_idempotency() -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    crashed_worker = "worker-crashed"
    recovery_worker = "worker-recovery"
    queue.register_worker(crashed_worker)
    queue.enqueue(_parsed_payload("CRASH"))
    raw = queue.claim(crashed_worker, timeout=0)
    assert raw is not None
    claimed_envelope = _Envelope.from_json(raw)
    # Simulate the crash window after the Redis id was claimed but before the
    # database transaction/ack completed.
    assert queue.mark_processed_if_new("CRASH", claimed_envelope.claim_id) is True

    # Hard crash: heartbeat disappears but registry/list survive until another
    # live worker observes the expired lease.
    redis.delete(queue._lease_key(crashed_worker))  # noqa: SLF001
    queue.register_worker(recovery_worker)
    assert queue.recover_pending(recovery_worker) == 1
    assert redis.lists[queue.processing_queue(crashed_worker)] == []
    assert crashed_worker not in redis.smembers(WORKER_REGISTRY)
    recovered = queue.claim(recovery_worker, timeout=0)
    assert recovered == raw
    recovered_envelope = _Envelope.from_json(recovered)
    assert recovered_envelope.claim_id == claimed_envelope.claim_id

    connection = WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1")
    factory = lambda: FakeIngestSession(connection=connection)  # noqa: E731
    worker = QueueWorker(
        queue=queue,
        session_factory=factory,
        worker_id=recovery_worker,
    )
    result = worker.handle_envelope(recovered_envelope)
    queue.ack(recovery_worker, recovered)

    assert result is IngestionResult.REGISTERED
    assert queue.mark_processed_if_new("CRASH", "different-delivery") is False
    assert redis.lists[queue.processing_queue(recovery_worker)] == []


def test_worker_heartbeat_renews_lease_while_main_loop_progress_is_fresh(
    monkeypatch,
) -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    queue.register_worker("worker-heartbeat")
    now = [0.0]
    heartbeats: list[tuple[str, int]] = []
    worker = QueueWorker(
        queue=queue,
        session_factory=FakeIngestSession,
        worker_id="worker-heartbeat",
        heartbeat_publisher=lambda state, ttl: heartbeats.append((state, ttl)),
        progress_clock=lambda: now[0],
        progress_timeout_seconds=WORKER_LEASE_SECONDS,
    )
    refreshes: list[str] = []
    monkeypatch.setattr(
        queue,
        "refresh_worker_lease",
        lambda worker_id: refreshes.append(worker_id) or True,
    )

    worker._record_progress()  # noqa: SLF001
    now[0] = WORKER_LEASE_SECONDS - 1

    assert worker._heartbeat_once() is True  # noqa: SLF001
    assert refreshes == ["worker-heartbeat"]
    assert heartbeats == [("ready", WORKER_LEASE_SECONDS)]


def test_stalled_worker_stops_renewing_and_claim_becomes_recoverable(
    monkeypatch,
) -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    queue.register_worker("worker-stalled")
    queue.register_worker("worker-recovery")
    queue.enqueue(_parsed_payload("STALL-RECOVERY"))
    raw = queue.claim("worker-stalled", timeout=0)
    now = [0.0]
    heartbeats: list[tuple[str, int]] = []
    refreshes: list[str] = []
    worker = QueueWorker(
        queue=queue,
        session_factory=FakeIngestSession,
        worker_id="worker-stalled",
        heartbeat_publisher=lambda state, ttl: heartbeats.append((state, ttl)),
        progress_clock=lambda: now[0],
        progress_timeout_seconds=WORKER_LEASE_SECONDS,
    )
    worker._running = True  # noqa: SLF001
    worker._record_progress()  # noqa: SLF001
    monkeypatch.setattr(
        queue,
        "refresh_worker_lease",
        lambda worker_id: refreshes.append(worker_id) or True,
    )

    now[0] = WORKER_LEASE_SECONDS + 1

    assert worker._heartbeat_once() is False  # noqa: SLF001
    assert worker._running is False  # noqa: SLF001
    assert refreshes == []
    assert heartbeats == [("error", WORKER_LEASE_SECONDS)]

    # FakeRedis does not advance TTL; deleting the unrenewed lease models its
    # natural expiry and proves that a live worker can recover the exact claim.
    redis.delete(queue._lease_key("worker-stalled"))  # noqa: SLF001
    assert queue.recover_pending("worker-recovery") == 1
    assert queue.claim("worker-recovery", timeout=0) == raw


def test_worker_run_cleans_up_lease_and_registry(monkeypatch) -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    queue.enqueue({"event": "connection.update"})
    heartbeats: list[tuple[str, int]] = []
    worker = QueueWorker(
        queue=queue,
        session_factory=FakeIngestSession,
        worker_id="worker-clean",
        heartbeat_publisher=lambda state, ttl: heartbeats.append((state, ttl)),
    )
    original_handle = worker._handle_raw  # noqa: SLF001

    def handle_once(raw: str) -> None:
        original_handle(raw)
        worker.stop()

    monkeypatch.setattr(worker, "_handle_raw", handle_once)

    worker.run()

    assert not redis.exists(queue._lease_key("worker-clean"))  # noqa: SLF001
    assert "worker-clean" not in redis.smembers(WORKER_REGISTRY)
    assert redis.lists[queue.processing_queue("worker-clean")] == []
    assert heartbeats == [
        ("ready", WORKER_LEASE_SECONDS),
        ("running", WORKER_LEASE_SECONDS),
        ("stopped", WORKER_LEASE_SECONDS),
    ]


def test_worker_acks_non_object_json_poison_pill() -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    worker_id = "worker-poison"
    redis.lpush(WEBHOOK_QUEUE, "[]")
    claimed = queue.claim(worker_id, timeout=0)
    worker = QueueWorker(
        queue=queue,
        session_factory=FakeIngestSession,
        worker_id=worker_id,
    )

    worker._handle_raw(claimed)  # noqa: SLF001

    assert redis.lists[queue.processing_queue(worker_id)] == []
    assert redis.lists[WEBHOOK_QUEUE] == []
    assert redis.direct_lrem_calls == 1
    assert redis.failed_transition_calls == 0


def test_worker_blocks_concurrent_delivery_with_same_provider_id() -> None:
    queue = WebhookQueue(redis_client=FakeRedis())
    first = _Envelope(payload=_parsed_payload("RACE"))
    concurrent = _Envelope(payload=_parsed_payload("RACE"))
    assert first.claim_id != concurrent.claim_id
    assert queue.mark_processed_if_new("RACE", first.claim_id) is True

    def forbidden_factory():  # pragma: no cover - must be blocked before DB
        raise AssertionError("concurrent envelope reached database work")

    worker = QueueWorker(queue=queue, session_factory=forbidden_factory)

    assert worker.handle_envelope(concurrent) is IngestionResult.DUPLICATE


def test_worker_skips_duplicate_message() -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    connection = WhatsappConnection(
        igreja_id="00000000-0000-0000-0000-000000000001", instance="igreja-1"
    )
    factory = lambda: FakeIngestSession(connection=connection)  # noqa: E731
    worker = QueueWorker(queue=queue, session_factory=factory)

    first = worker.handle_envelope(_Envelope(payload=_parsed_payload("DUP")))
    second = worker.handle_envelope(_Envelope(payload=_parsed_payload("DUP")))

    assert first is IngestionResult.REGISTERED
    assert second is IngestionResult.DUPLICATE


def test_worker_reprocesses_on_transient_failure() -> None:
    """RNF-17: a failure re-enqueues the envelope with attempts incremented."""
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)

    def boom():
        raise RuntimeError("db down")

    worker = QueueWorker(
        queue=queue,
        session_factory=boom,
        worker_id="worker-retry",
    )
    queue.register_worker("worker-retry")
    original = _Envelope(payload=_parsed_payload("RETRY"))
    raw = original.to_json()
    redis.lpush(WEBHOOK_QUEUE, raw)
    claimed = queue.claim("worker-retry", timeout=0)
    worker._handle_raw(claimed)  # noqa: SLF001

    requeued = redis.lists[WEBHOOK_QUEUE]
    assert len(requeued) == 1
    retried = _Envelope.from_json(requeued[0])
    assert retried.attempts == 1
    assert retried.claim_id == original.claim_id
    assert redis.lists[queue.processing_queue("worker-retry")] == []
    assert redis.failed_transition_calls == 1
    assert redis.direct_lrem_calls == 0


def test_failed_transition_does_not_enqueue_when_claim_is_missing() -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    envelope = _Envelope(payload=_parsed_payload("MISSING"))

    with pytest.raises(ClaimOwnershipLost, match="no longer owned"):
        queue.transition_failed_claim(
            "worker-missing",
            envelope.to_json(),
            envelope,
        )

    assert redis.lists.get(WEBHOOK_QUEUE) in (None, [])
    assert redis.lists.get(DEAD_LETTER_QUEUE) in (None, [])
    assert redis.failed_transition_calls == 1
    assert redis.direct_lrem_calls == 0


def test_stale_worker_cannot_dead_letter_and_claim_remains_recoverable(
    monkeypatch,
) -> None:
    """A lease loser cannot move a failed claim after a new owner can recover it."""
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    old_worker_id = "worker-failure-old"
    new_worker_id = "worker-failure-new"
    queue.register_worker(old_worker_id)
    queue.register_worker(new_worker_id)
    original = _Envelope(
        payload=_parsed_payload("STALE-FAILURE"),
        attempts=MAX_ATTEMPTS - 1,
    )
    redis.lpush(WEBHOOK_QUEUE, original.to_json())
    raw = queue.claim(old_worker_id, timeout=0)
    assert raw is not None

    worker = QueueWorker(
        queue=queue,
        session_factory=FakeIngestSession,
        worker_id=old_worker_id,
    )

    def fail_after_lease_loss(*_args, **_kwargs):
        redis.delete(queue._lease_key(old_worker_id))  # noqa: SLF001
        raise RuntimeError("processing failed after lease expiry")

    monkeypatch.setattr(worker, "handle_envelope", fail_after_lease_loss)
    worker._handle_raw(raw)  # noqa: SLF001

    assert redis.lists[queue.processing_queue(old_worker_id)] == [raw]
    assert redis.lists.get(DEAD_LETTER_QUEUE) in (None, [])
    assert redis.lists.get(WEBHOOK_QUEUE) in (None, [])
    assert redis.failed_transition_calls == 1
    assert worker._running is False  # noqa: SLF001

    assert queue.recover_pending(new_worker_id) == 1
    recovered = queue.claim(new_worker_id, timeout=0)
    assert recovered == raw
    assert _Envelope.from_json(recovered).attempts == MAX_ATTEMPTS - 1


def test_current_owner_atomically_dead_letters_failed_claim() -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    worker_id = "worker-failure-current"
    queue.register_worker(worker_id)
    original = _Envelope(
        payload=_parsed_payload("OWNED-FAILURE"),
        attempts=MAX_ATTEMPTS - 1,
    )
    redis.lpush(WEBHOOK_QUEUE, original.to_json())
    raw = queue.claim(worker_id, timeout=0)
    assert raw is not None

    queue.transition_failed_claim(worker_id, raw, _Envelope.from_json(raw))

    assert redis.lists[queue.processing_queue(worker_id)] == []
    assert len(redis.lists[DEAD_LETTER_QUEUE]) == 1
    dead = _Envelope.from_json(redis.lists[DEAD_LETTER_QUEUE][0])
    assert dead.attempts == MAX_ATTEMPTS
    assert dead.claim_id == original.claim_id
    assert redis.failed_transition_calls == 1


def test_failed_transition_does_not_treat_a_partial_lua_result_as_success(
    monkeypatch,
) -> None:
    """An ambiguous Redis result leaves the claim recoverable and fences us."""
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    worker_id = "worker-failure-partial"
    queue.register_worker(worker_id)
    envelope = _Envelope(payload=_parsed_payload("PARTIAL"))
    raw = envelope.to_json()
    redis.lpush(WEBHOOK_QUEUE, raw)
    assert queue.claim(worker_id, timeout=0) == raw

    original_eval = redis.eval

    def partial(*args, **kwargs):
        # Simulate a response received after Redis has durably copied the
        # replacement but before the caller can know whether source removal
        # completed.  The queue must not claim success in either case.
        original_eval(*args, **kwargs)
        return -14

    monkeypatch.setattr(redis, "eval", partial)

    with pytest.raises(ClaimOwnershipLost, match="no longer owned"):
        queue.transition_failed_claim(worker_id, raw, envelope)

    assert redis.lists[queue.processing_queue(worker_id)] == []
    assert len(redis.lists[WEBHOOK_QUEUE]) == 1


def test_worker_dead_letters_after_max_attempts() -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    env = _Envelope(payload=_parsed_payload("DEAD"), attempts=MAX_ATTEMPTS - 1)
    raw = env.to_json()
    redis.lpush(WEBHOOK_QUEUE, raw)

    def boom():
        raise RuntimeError("db down")

    worker = QueueWorker(
        queue=queue,
        session_factory=boom,
        worker_id="worker-dead",
    )
    queue.register_worker("worker-dead")
    claimed = queue.claim("worker-dead", timeout=0)
    worker._handle_raw(claimed)  # noqa: SLF001

    assert redis.lists.get(WEBHOOK_QUEUE) in (None, [])
    assert len(redis.lists[DEAD_LETTER_QUEUE]) == 1
    assert redis.lists[queue.processing_queue("worker-dead")] == []
    dead = _Envelope.from_json(redis.lists[DEAD_LETTER_QUEUE][0])
    assert dead.attempts == MAX_ATTEMPTS
    assert dead.claim_id == env.claim_id
    assert redis.failed_transition_calls == 1
    assert redis.direct_lrem_calls == 0


def test_build_redis_has_bounded_pool_and_timeouts(monkeypatch) -> None:
    import redis

    captured: dict = {}
    sentinel = object()

    def fake_from_url(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(redis.Redis, "from_url", fake_from_url)

    assert _build_redis() is sentinel
    assert captured["socket_connect_timeout"] == REDIS_CONNECT_TIMEOUT_SECONDS
    assert captured["socket_timeout"] == REDIS_SOCKET_TIMEOUT_SECONDS
    assert captured["max_connections"] == REDIS_MAX_CONNECTIONS
