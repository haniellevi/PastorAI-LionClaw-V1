"""Tests for the webhook queue worker: idempotency, reprocess and ingestion."""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.db.models import Conversation, Message, Pessoa, WhatsappConnection
from app.domain.conversations import parse_message_event
from app.domain.phone import normalize_phone
from app.workers.queue_worker import (
    DEAD_LETTER_QUEUE,
    MAX_ATTEMPTS,
    WEBHOOK_QUEUE,
    IngestionResult,
    QueueWorker,
    WebhookQueue,
    _Envelope,
    ingest_message_event,
    ingest_message_event_ex,
    process_webhook_payload,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeRedis:
    """Minimal in-memory Redis stand-in for queue + idempotency keys."""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.kv: dict[str, str] = {}

    def lpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).insert(0, value)

    def brpop(self, key: str, timeout: int = 0):
        items = self.lists.get(key)
        if not items:
            return None
        return key, items.pop()

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.kv:
            return False
        self.kv[key] = value
        return True

    def delete(self, key: str) -> None:
        self.kv.pop(key, None)


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

    def execute(self, statement, params=None) -> _Scalar:
        entity = statement.column_descriptions[0]["entity"]
        return _Scalar(self._by_entity.get(entity))

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

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


def test_mark_processed_if_new_is_idempotent() -> None:
    queue = WebhookQueue(redis_client=FakeRedis())
    assert queue.mark_processed_if_new("MSG1") is True
    assert queue.mark_processed_if_new("MSG1") is False


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

    worker = QueueWorker(queue=queue, session_factory=boom)
    raw = _Envelope(payload=_parsed_payload("RETRY")).to_json()
    worker._handle_raw(raw)  # noqa: SLF001

    requeued = redis.lists[WEBHOOK_QUEUE]
    assert len(requeued) == 1
    assert _Envelope.from_json(requeued[0]).attempts == 1


def test_worker_dead_letters_after_max_attempts() -> None:
    redis = FakeRedis()
    queue = WebhookQueue(redis_client=redis)
    env = _Envelope(payload={"event": "messages.upsert"}, attempts=MAX_ATTEMPTS - 1)
    queue._requeue(env)  # noqa: SLF001
    assert redis.lists.get(WEBHOOK_QUEUE) in (None, [])
    assert len(redis.lists[DEAD_LETTER_QUEUE]) == 1
