"""Webhook queue worker for inbound WhatsApp messages (RNF-16 / RNF-17).

Flow:
  Evolution webhook --(enqueue)--> Redis list --(BRPOP)--> worker --> Postgres

Design notes:
- Idempotency (RNF-16): a contact is never duplicated. Persons are deduped by
  (normalized telefone, igreja); the provider message id is recorded in Redis so
  a redelivery after a reconnection is skipped instead of reprocessed.
- Official number only (US-07): a message is only persisted when its instance
  matches a registered `whatsapp_connections.instance`. Personal conversations
  (any other number/instance) are dropped.
- Reprocess (RNF-17): a transient failure re-enqueues the envelope with an
  incremented attempt counter (bounded by MAX_ATTEMPTS); exhausted envelopes go
  to a dead-letter list for inspection instead of being lost.

The worker is a standalone process: `python -m app.workers.queue_worker`.
"""

from __future__ import annotations

import json
import logging
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Conversation, Message, Pessoa, WhatsappConnection
from app.db.session import get_session_factory
from app.domain.conversations import ParsedMessage, parse_message_event
from app.domain.phone import normalize_phone, phone_suffix

logger = logging.getLogger("pastorai.queue_worker")

WEBHOOK_QUEUE = "pastorai:webhooks"
DEAD_LETTER_QUEUE = "pastorai:webhooks:dead"
PROCESSED_PREFIX = "pastorai:processed:"
PROCESSED_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days
MAX_ATTEMPTS = 5
BRPOP_TIMEOUT = 5  # seconds


class IngestionResult(str, Enum):
    """Outcome of persisting a single webhook event."""

    REGISTERED = "registered"
    DUPLICATE = "duplicate"
    SKIPPED_NOT_OFFICIAL = "skipped_not_official"
    IGNORED = "ignored"


# ---------------------------------------------------------------------------
# DB ingestion (idempotent, official-number-only)
# ---------------------------------------------------------------------------
@dataclass
class IngestionOutcome:
    """Result of an ingestion plus the context the orchestrator needs."""

    result: IngestionResult
    conversation_id: Any | None = None
    instance: str | None = None
    telefone: str | None = None
    texto: str | None = None
    inbound: bool = False


def ingest_message_event(db: Session, parsed: ParsedMessage) -> IngestionResult:
    """Persist one parsed inbound message, deduping contacts (RNF-16/US-07).

    Returns an IngestionResult describing what happened. Raises on unexpected
    database errors so the caller (worker) can retry (RNF-17).
    """
    return ingest_message_event_ex(db, parsed).result


def ingest_message_event_ex(db: Session, parsed: ParsedMessage) -> IngestionOutcome:
    """Like `ingest_message_event` but also returns the conversation context.

    Used by the worker to hand the persisted inbound message to the agent
    orchestrator (delta-034), which emits the single official-number reply.
    """
    connection = db.execute(
        select(WhatsappConnection).where(
            WhatsappConnection.instance == parsed.instance
        )
    ).scalar_one_or_none()

    # US-07: only the official number (a registered instance) is captured.
    if connection is None:
        logger.info("Dropping message from non-official instance %s", parsed.instance)
        return IngestionOutcome(result=IngestionResult.SKIPPED_NOT_OFFICIAL)

    igreja_id = connection.igreja_id
    inbound = not parsed.from_me

    # Data integrity (regra do usuário + US-07): só uma mensagem RECEBIDA de um
    # número que NÃO é o próprio número oficial da igreja vira contato. O número
    # da igreja (auto-conversa, ou a sincronização de histórico ao ler o QR) e os
    # ecos de mensagens enviadas NUNCA viram "pessoa".
    official = parsed.owner or (
        normalize_phone(connection.numero) if connection.numero else None
    )
    if official and parsed.telefone == official:
        logger.info(
            "Ignoring the church's own number as a contact (instance %s)",
            parsed.instance,
        )
        return IngestionOutcome(result=IngestionResult.IGNORED)

    # Dedupe person by CANONICAL telefone + igreja (RNF-16). Always look up an
    # existing contact before creating, matching across the +55 / 9th-digit
    # variations (parsed.telefone is already canonical): narrow candidates by the
    # stable 8-digit suffix in SQL, then confirm the full canonical match in
    # Python. This is why a person who messages the church number is recognized
    # instead of being recreated as a new visitor.
    stored_digits = func.regexp_replace(Pessoa.telefone, r"\D", "", "g")
    candidates = db.execute(
        select(Pessoa).where(
            Pessoa.igreja_id == igreja_id,
            func.right(stored_digits, 8) == phone_suffix(parsed.telefone),
        )
    ).scalars().all()
    pessoa = next(
        (p for p in candidates if normalize_phone(p.telefone) == parsed.telefone),
        None,
    )

    if pessoa is None:
        if not inbound:
            # Mensagem ENVIADA para um número ainda desconhecido (ex.: histórico
            # sincronizado ao conectar) não cria contato — só quem fala com a
            # igreja vira contato.
            logger.info("Outbound to unknown number — not creating a contact")
            return IngestionOutcome(result=IngestionResult.IGNORED)
        pessoa = Pessoa(
            igreja_id=igreja_id,
            nome=parsed.push_name or parsed.telefone_raw,
            telefone=parsed.telefone_raw,
            origem="whatsapp",
            tipo="visitante",
        )
        db.add(pessoa)
        db.flush()

    conversation = db.execute(
        select(Conversation).where(
            Conversation.igreja_id == igreja_id,
            Conversation.pessoa_id == pessoa.id,
        )
    ).scalar_one_or_none()

    if conversation is None:
        conversation = Conversation(
            igreja_id=igreja_id,
            pessoa_id=pessoa.id,
            telefone=parsed.telefone_raw,
            estado="ia",
            numero_oficial=True,
            nao_lidas=0,
        )
        db.add(conversation)
        db.flush()

    message = Message(
        igreja_id=igreja_id,
        conversation_id=conversation.id,
        direcao="in" if inbound else "out",
        autor="contato" if inbound else "humano",
        texto=parsed.texto,
    )
    db.add(message)

    conversation.ultima_mensagem = parsed.texto
    if inbound:
        conversation.nao_lidas = (conversation.nao_lidas or 0) + 1

    # trg_consent_on_inbound grants consent automatically on the first inbound.
    db.commit()
    return IngestionOutcome(
        result=IngestionResult.REGISTERED,
        conversation_id=conversation.id,
        instance=parsed.instance,
        telefone=parsed.telefone_raw,
        texto=parsed.texto,
        inbound=inbound,
    )


def process_webhook_payload(db: Session, payload: dict[str, Any]) -> IngestionResult:
    """Parse and persist a raw webhook payload (no Redis dependency)."""
    parsed = parse_message_event(payload)
    if parsed is None:
        return IngestionResult.IGNORED
    return ingest_message_event(db, parsed)


# ---------------------------------------------------------------------------
# Redis-backed queue
# ---------------------------------------------------------------------------
@dataclass
class _Envelope:
    payload: dict[str, Any]
    attempts: int = 0

    def to_json(self) -> str:
        return json.dumps({"payload": self.payload, "attempts": self.attempts})

    @classmethod
    def from_json(cls, raw: str) -> "_Envelope":
        data = json.loads(raw)
        return cls(payload=data.get("payload", {}), attempts=int(data.get("attempts", 0)))


class WebhookQueue:
    """Redis list used to hand webhook payloads to the worker."""

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client or _build_redis()

    def enqueue(self, payload: dict[str, Any]) -> None:
        """Push a new webhook payload onto the queue (attempts=0)."""
        self._redis.lpush(WEBHOOK_QUEUE, _Envelope(payload=payload).to_json())

    def mark_processed_if_new(self, message_id: str) -> bool:
        """Atomically claim a provider message id; False if already seen.

        Backs message-level idempotency: a redelivered event is skipped.
        """
        key = f"{PROCESSED_PREFIX}{message_id}"
        # SET key 1 NX EX ttl -> truthy only the first time.
        return bool(self._redis.set(key, "1", nx=True, ex=PROCESSED_TTL_SECONDS))

    def release_processed(self, message_id: str) -> None:
        """Release a previously-claimed message id so a retry can reprocess it.

        Called when ingestion fails after the id was claimed, so the bounded
        reprocess (RNF-17) is not silently dropped as a duplicate.
        """
        self._redis.delete(f"{PROCESSED_PREFIX}{message_id}")

    def _requeue(self, envelope: _Envelope) -> None:
        envelope.attempts += 1
        if envelope.attempts >= MAX_ATTEMPTS:
            logger.error(
                "Webhook exhausted retries (%d), moving to dead-letter",
                envelope.attempts,
            )
            self._redis.lpush(DEAD_LETTER_QUEUE, envelope.to_json())
        else:
            self._redis.lpush(WEBHOOK_QUEUE, envelope.to_json())


class QueueWorker:
    """Long-running consumer that drains WEBHOOK_QUEUE into Postgres."""

    def __init__(
        self,
        queue: WebhookQueue | None = None,
        session_factory: Any | None = None,
        agent_runner: "Callable[[Any, IngestionOutcome], None] | None" = None,
    ) -> None:
        self._queue = queue or WebhookQueue()
        self._session_factory = session_factory or get_session_factory()
        # Optional orchestrator hook (delta-034). When set, a freshly persisted
        # inbound message is handed to the agent, which emits the single reply.
        # Defaulting to None keeps ingestion-only tests free of agent/DB needs.
        self._agent_runner = agent_runner
        self._running = False

    def stop(self, *_: Any) -> None:
        """Request a graceful shutdown (used as a SIGTERM/SIGINT handler)."""
        logger.info("Queue worker shutdown requested")
        self._running = False

    def run(self) -> None:
        """Block draining the queue until stopped (graceful shutdown)."""
        self._running = True
        redis = self._queue._redis  # noqa: SLF001 - intentional internal access
        logger.info("Queue worker started, consuming %s", WEBHOOK_QUEUE)
        while self._running:
            item = redis.brpop(WEBHOOK_QUEUE, timeout=BRPOP_TIMEOUT)
            if item is None:
                continue  # timeout: loop to re-check the running flag
            _, raw = item
            self._handle_raw(raw)
        logger.info("Queue worker stopped")

    def _handle_raw(self, raw: str) -> None:
        try:
            envelope = _Envelope.from_json(raw)
        except (ValueError, TypeError):
            logger.error("Discarding malformed envelope from queue")
            return
        try:
            self.handle_envelope(envelope)
        except Exception:  # noqa: BLE001 - any error triggers a bounded retry
            logger.exception("Webhook processing failed; scheduling reprocess")
            self._queue._requeue(envelope)  # noqa: SLF001

    def handle_envelope(self, envelope: _Envelope) -> IngestionResult:
        """Process one envelope: idempotency guard + DB ingestion.

        The message id is claimed before processing (dedupe) and released if
        ingestion fails, so the bounded reprocess (RNF-17) is not dropped as a
        duplicate.
        """
        parsed = parse_message_event(envelope.payload)
        if parsed is None:
            return IngestionResult.IGNORED

        if not self._queue.mark_processed_if_new(parsed.provider_message_id):
            logger.info("Skipping duplicate message %s", parsed.provider_message_id)
            return IngestionResult.DUPLICATE

        try:
            session: Session = self._session_factory()
            try:
                outcome = ingest_message_event_ex(session, parsed)
            finally:
                session.close()
        except Exception:
            # Release the claim so the requeued envelope can be reprocessed.
            self._queue.release_processed(parsed.provider_message_id)
            raise

        # Hand the persisted inbound message to the orchestrator (delta-034).
        # Agent failures must NOT requeue the (already committed) ingestion, so
        # they are caught and logged rather than propagated.
        if (
            self._agent_runner is not None
            and outcome.result is IngestionResult.REGISTERED
            and outcome.inbound
        ):
            try:
                self._agent_runner(self._session_factory, outcome)
            except Exception:  # noqa: BLE001 - agent errors never lose the message
                logger.exception("Agent orchestration failed for %s", parsed.provider_message_id)

        return outcome.result


# ---------------------------------------------------------------------------
# Agent orchestration runner (delta-034)
# ---------------------------------------------------------------------------
def run_agent_for_message(session_factory: Any, outcome: IngestionOutcome) -> None:
    """Drive the orchestrator for one persisted inbound message and reply.

    The orchestrator produces a single reply; we send it through the official
    number and persist the outbound message. Handoff suppresses the auto reply.
    Imports are deferred so the agent stack stays optional for ingestion tests.
    """
    from app.agent.runtime import process_inbound_message  # noqa: PLC0415
    from app.db.models import Conversation, Message  # noqa: PLC0415
    from app.services.evolution import EvolutionClient, EvolutionError  # noqa: PLC0415

    if outcome.conversation_id is None:
        return

    session: Session = session_factory()
    try:
        result = process_inbound_message(
            session, conversation_id=outcome.conversation_id, texto=outcome.texto
        )
    finally:
        session.close()

    if not result.handled or result.suppressed or not result.response:
        return

    # Single exit: send the orchestrator reply through the official number.
    try:
        EvolutionClient().send_text(
            outcome.instance, outcome.telefone, result.response
        )
    except EvolutionError:
        logger.warning("Failed to send agent reply via Evolution")
        return

    # Persist the outbound message and refresh the conversation snapshot.
    session = session_factory()
    try:
        conv = session.get(Conversation, outcome.conversation_id)
        if conv is not None:
            session.add(
                Message(
                    igreja_id=conv.igreja_id,
                    conversation_id=conv.id,
                    direcao="out",
                    autor="ia",
                    texto=result.response,
                )
            )
            conv.ultima_mensagem = result.response
            session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Redis client + entrypoint
# ---------------------------------------------------------------------------
def _build_redis() -> Any:
    """Build a Redis client from REDIS_URL (imported lazily)."""
    import redis  # lazy import so the package is optional for unit tests

    settings = get_settings()
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def main() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker = QueueWorker(agent_runner=run_agent_for_message)
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run()


if __name__ == "__main__":  # pragma: no cover
    main()
