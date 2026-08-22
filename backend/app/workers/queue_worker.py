"""Webhook queue worker for inbound WhatsApp messages (RNF-16 / RNF-17).

Flow:
  Evolution webhook --(enqueue)--> Redis list --(BRPOPLPUSH)--> processing
  list --> worker --> Postgres --(ack processing item)

Design notes:
- Idempotency (RNF-16): a contact is never duplicated. Persons are deduped by
  (normalized telefone, igreja); the provider message id is recorded in Redis so
  a redelivery after a reconnection is skipped instead of reprocessed.
- Idempotency in depth (MSG-IDEMP-1): Redis is the fast first barrier, but its
  claim expires (PROCESSED_TTL_SECONDS) and does not survive a Redis outage/
  flush. `messages_inbound_provider_id_uidx` (partial unique index on
  `messages(igreja_id, provider_message_id)` where inbound) is the durable
  second barrier — `ingest_message_event_ex` catches the resulting
  IntegrityError and returns DUPLICATE instead of persisting twice or
  treating a fresh provider redelivery as new work. A recovered copy of the
  exact same queue claim may resume effects that were not finalized yet.
- Official number only (US-07): a message is only persisted when its instance
  matches a registered `whatsapp_connections.instance`. Personal conversations
  (any other number/instance) are dropped.
- Reprocess (RNF-17): a transient failure re-enqueues the envelope with an
  incremented attempt counter (bounded by MAX_ATTEMPTS); exhausted envelopes go
  to a dead-letter list for inspection instead of being lost.
- Crash recovery: claims live in a Redis processing list until acknowledged.
  On startup the worker moves unfinished claims back to the ready queue. The
  Redis idempotency marker binds in-flight work to the envelope claim id and
  distinguishes it from completed work. A crash before/after the database
  commit is safe to retry; the database unique index remains the durable final
  barrier.

The worker is a standalone process: `python -m app.workers.queue_worker`.
"""

from __future__ import annotations

import json
import logging
import signal
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from functools import partial
from hashlib import sha256
from threading import Event, Lock, Thread
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Conversation, Message, Pessoa, WhatsappConnection
from app.db.rls_observability import log_if_not_scoped
from app.db.session import get_session_factory
from app.db.tenant_session import (
    mark_cross_tenant,
    mark_tenant_scoped,
    promote_to_tenant,
)
from app.domain.conversations import (
    ParsedMessage,
    media_snippet,
    parse_message_event,
)
from app.domain.phone import normalize_phone, phone_suffix
from app.services.pessoa_dedup import insert_pessoa_or_get_winner, lock_canonical_phone
from app.services.worker_health import publish_worker_heartbeat

logger = logging.getLogger("pastorai.queue_worker")

WEBHOOK_QUEUE = "pastorai:webhooks"
PROCESSING_QUEUE = "pastorai:webhooks:processing"
DEAD_LETTER_QUEUE = "pastorai:webhooks:dead"
PROCESSED_PREFIX = "pastorai:processed:"
WORKER_REGISTRY = "pastorai:webhooks:workers"
WORKER_LEASE_PREFIX = "pastorai:webhooks:worker-lease:"
WORKER_RECOVERY_LOCK_PREFIX = "pastorai:webhooks:recovery-lock:"
PROCESSED_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days
MAX_ATTEMPTS = 5
BRPOP_TIMEOUT = 5  # seconds
WORKER_LEASE_SECONDS = 30
WORKER_HEARTBEAT_SECONDS = 10
WORKER_PROGRESS_TIMEOUT_SECONDS = WORKER_LEASE_SECONDS * 2
REDIS_CONNECT_TIMEOUT_SECONDS = 3
# Must exceed BRPOP_TIMEOUT so the client socket does not time out before the
# blocking Redis command returns normally.
REDIS_SOCKET_TIMEOUT_SECONDS = BRPOP_TIMEOUT + 2
REDIS_MAX_CONNECTIONS = 20

_PROCESSING_MARKER = "processing"
_PROCESSED_MARKER = "done"

_COMPARE_AND_DELETE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

_MARK_DONE_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current == ARGV[1] then
    redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
    return 1
end
if current == ARGV[2] then
    return 1
end
return 0
"""

_MOVE_FAILED_CLAIM_SCRIPT = """
-- A failed claim must never disappear if Redis rejects a later write.  Redis
-- does not roll back earlier Lua mutations after a command error, so validate
-- every key first, persist the replacement first, and only then remove the
-- original claim.  A rare failure after LPUSH leaves a recoverable duplicate;
-- the next owner sees the replacement and removes the original without
-- enqueueing a second copy.
local lease_type = redis.call('TYPE', KEYS[1]).ok
local processing_type = redis.call('TYPE', KEYS[2]).ok
local target_type = redis.call('TYPE', KEYS[3]).ok
if lease_type ~= 'string' or processing_type ~= 'list' then
    return 0
end
if target_type ~= 'none' and target_type ~= 'list' then
    return -1
end
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end

local processing_items = redis.call('LRANGE', KEYS[2], 0, -1)
local owned = false
for _, item in ipairs(processing_items) do
    if item == ARGV[2] then
        owned = true
        break
    end
end
if not owned then
    return 0
end

-- Test-only failure points exercise Redis's non-transactional error model in
-- a real Redis 7 server.  Runtime callers never pass ARGV[4].
local failure = ARGV[4] or ''
if failure == 'before_destination' or failure == 'target_write_error' then
    return -10
end

local destination_has_replacement = false
if target_type == 'list' then
    local target_items = redis.call('LRANGE', KEYS[3], 0, -1)
    for _, item in ipairs(target_items) do
        if item == ARGV[3] then
            destination_has_replacement = true
            break
        end
    end
end
if not destination_has_replacement then
    local pushed = redis.pcall('LPUSH', KEYS[3], ARGV[3])
    if type(pushed) == 'table' and pushed.err then
        return -11
    end
end

if failure == 'after_destination' or failure == 'before_source' then
    return -12
end

local removed = redis.pcall('LREM', KEYS[2], 1, ARGV[2])
if type(removed) == 'table' and removed.err then
    return -13
end
if removed ~= 1 then
    -- The destination is deliberately retained.  Returning a non-success
    -- fences this worker; a later owner can reconcile the original claim.
    return -14
end
if failure == 'after_source' then
    return -15
end
return 1
"""

_OWNS_CLAIM_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
local items = redis.call('LRANGE', KEYS[2], 0, -1)
for _, item in ipairs(items) do
    if item == ARGV[2] then
        return 1
    end
end
return 0
"""

_RELEASE_MARKER_IF_OWNED_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
local items = redis.call('LRANGE', KEYS[2], 0, -1)
for _, item in ipairs(items) do
    if item == ARGV[2] then
        if redis.call('GET', KEYS[3]) == ARGV[3] then
            return redis.call('DEL', KEYS[3])
        end
        return 0
    end
end
return 0
"""

_FENCE_CLAIM_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
local items = redis.call('LRANGE', KEYS[2], 0, -1)
for _, item in ipairs(items) do
    if item == ARGV[2] then
        redis.call('EXPIRE', KEYS[1], ARGV[3])
        return 1
    end
end
return 0
"""

_MARK_DONE_IF_OWNED_SCRIPT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
local items = redis.call('LRANGE', KEYS[2], 0, -1)
for _, item in ipairs(items) do
    if item == ARGV[2] then
        if redis.call('GET', KEYS[3]) == ARGV[3] then
            redis.call('SET', KEYS[3], ARGV[4], 'EX', ARGV[5])
            return 1
        end
        return 0
    end
end
return 0
"""

# Postgres error code for unique_violation (23505) — the only IntegrityError
# `ingest_message_event_ex` treats as a duplicate; anything else re-raises.
_PG_UNIQUE_VIOLATION = "23505"
_PROVIDER_MESSAGE_UNIQUE_CONSTRAINTS = frozenset(
    {
        "messages_inbound_provider_id_uidx",
        "messages_outbound_provider_id_uidx",
    }
)


def _is_provider_message_duplicate(exc: IntegrityError) -> bool:
    """Return True only for a durable provider-message idempotency index."""
    orig = exc.orig
    sqlstate = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    return (
        sqlstate == _PG_UNIQUE_VIOLATION
        and constraint_name in _PROVIDER_MESSAGE_UNIQUE_CONSTRAINTS
    )


def _provider_message_lock_key(igreja_id: Any, provider_message_id: str) -> int:
    """Stable signed bigint used by Postgres transaction advisory locks."""
    material = f"{igreja_id}:{provider_message_id}".encode("utf-8")
    return int.from_bytes(sha256(material).digest()[:8], "big", signed=True)


def _provider_message_exists_after_fence(
    db: Session,
    igreja_id: Any,
    provider_message_id: str,
    *,
    inbound: bool,
) -> bool:
    """Serialize one provider event in Postgres and detect prior persistence.

    A Redis worker can lose its lease while its handler is still unwinding. A
    replacement worker may then recover the same claim. The transaction-scoped
    advisory lock fences those two database transactions independently of the
    Redis connection: the loser waits, observes the committed provider id, and
    returns before contact, media, or message side effects.

    Unit-test SQLite and lightweight fake sessions do not support Postgres
    advisory locks; the durable unique index remains their idempotency seam.
    Production is Postgres and always takes this path.
    """
    return (
        _provider_message_after_fence(
            db,
            igreja_id,
            provider_message_id,
            inbound=inbound,
        )
        is not None
    )


def _provider_message_after_fence(
    db: Session,
    igreja_id: Any,
    provider_message_id: str,
    *,
    inbound: bool,
) -> Message | None:
    """Fence one provider event and return the already persisted row, if any."""
    get_bind = getattr(db, "get_bind", None)
    if get_bind is None or get_bind().dialect.name != "postgresql":
        return None

    lock_key = _provider_message_lock_key(igreja_id, provider_message_id)
    db.execute(select(func.pg_advisory_xact_lock(lock_key))).scalar_one_or_none()
    return db.execute(
        select(Message).where(
            Message.igreja_id == igreja_id,
            Message.provider_message_id == provider_message_id,
            Message.direcao == ("in" if inbound else "out"),
        )
    ).scalar_one_or_none()


class IngestionResult(str, Enum):
    """Outcome of persisting a single webhook event."""

    REGISTERED = "registered"
    DUPLICATE = "duplicate"
    SKIPPED_NOT_OFFICIAL = "skipped_not_official"
    IGNORED = "ignored"


class ProcessingClaim(str, Enum):
    """How this envelope relates to the Redis idempotency marker."""

    NEW = "new"
    RESUMED = "resumed"
    REJECTED = "rejected"


class ClaimOwnershipLost(RuntimeError):
    """Raised when a recovered queue item no longer belongs to this worker."""


class AgentReplyRetryable(RuntimeError):
    """A reply failed before Evolution could accept it and can be retried safely."""


class AgentRunDisposition(str, Enum):
    """Whether this worker completed a safe agent turn for the queue claim."""

    COMPLETED = "completed"
    IN_FLIGHT = "in_flight"


# A resposta do agente usa a própria tabela ``messages`` como ledger durável.
# A migration MSG-IDEMP-1 já criou o índice parcial único outbound sobre
# ``(igreja_id, provider_message_id)``.  The opaque provider id below is
# derived only from the inbound event + queue claim, never from the response.
# ``ia_reservada`` is committed *before* the agent executes mutable tools;
# ``ia_executando`` is deliberately quarantined after a crash because the
# process may have crossed a non-transactional tool boundary already.
_AGENT_REPLY_PROVIDER_PREFIX = "agent-reply:"
_AGENT_REPLY_RESERVED = "ia_reservada"
_AGENT_REPLY_EXECUTING = "ia_executando"
_AGENT_REPLY_PENDING = "ia_pendente"
_AGENT_REPLY_IN_FLIGHT = "ia_em_transporte"
_AGENT_REPLY_CONFIRMED = "ia"
_AGENT_REPLY_AMBIGUOUS = "ia_ambigua"
_AGENT_REPLY_EXECUTION_AMBIGUOUS = "ia_execucao_ambigua"
_AGENT_REPLY_FAILED = "ia_falhou"
_AGENT_REPLY_SUPPRESSED = "ia_suprimida"
_AGENT_REPLY_NO_RESPONSE = "ia_sem_resposta"


@dataclass(frozen=True)
class _AgentReplyIntent:
    """Sanitized snapshot of one durable outbound agent intent.

    ``ia_em_transporte`` is deliberately treated as unresolved by a later
    recovery: the first process may have crossed the provider boundary before
    crashing.  Only ``ia_pendente`` can start a new call automatically.
    """

    id: Any
    state: str
    response: str
    provider_message_id: str


@dataclass
class _LocalAgentExecutionLock:
    """Small fallback for non-PostgreSQL test adapters in one process only."""

    lock: Lock
    users: int = 0


_LOCAL_AGENT_EXECUTION_LOCKS: dict[str, _LocalAgentExecutionLock] = {}
_LOCAL_AGENT_EXECUTION_LOCKS_GUARD = Lock()


class _AgentExecutionLease:
    """Hold a session advisory lock while one agent turn is executing.

    PostgreSQL is the production contract.  The local lock only keeps focused
    SQLite/fake-session tests deterministic; it is never used for production
    cross-process fencing.
    """

    def __init__(self, session_factory: Any, outcome: "IngestionOutcome", key: str) -> None:
        self._session_factory = session_factory
        self._outcome = outcome
        self._key = key
        self._connection: Connection | None = None
        self._local: _LocalAgentExecutionLock | None = None

    def acquire(self) -> bool:
        session: Session = self._session_factory()
        try:
            _scope_agent_session(session, self._outcome)
            get_bind = getattr(session, "get_bind", None)
            bind = get_bind() if callable(get_bind) else None
            dialect = getattr(getattr(bind, "dialect", None), "name", None)
        finally:
            session.close()

        if dialect == "postgresql":
            connect = getattr(bind, "connect", None)
            if not callable(connect):
                connect = getattr(getattr(bind, "engine", None), "connect", None)
            if not callable(connect):
                raise RuntimeError(
                    "PostgreSQL agent execution lease requires a connectable bind"
                )

            connection: Connection = connect()
            try:
                lock_key = _agent_execution_lock_key(self._outcome, self._key)
                acquired = bool(
                    connection.execute(
                        select(func.pg_try_advisory_lock(lock_key))
                    ).scalar_one()
                )
                # The lock is session-scoped, so finish the transaction while
                # keeping its physical connection checked out until close().
                connection.commit()
            except Exception:
                try:
                    # A failed commit may leave a session advisory lock alive.
                    # Do not return that physical connection to the pool.
                    connection.invalidate()
                finally:
                    connection.close()
                raise
            if acquired:
                self._connection = connection
                return True
            connection.close()
            return False

        with _LOCAL_AGENT_EXECUTION_LOCKS_GUARD:
            local = _LOCAL_AGENT_EXECUTION_LOCKS.get(self._key)
            if local is None:
                local = _LocalAgentExecutionLock(lock=Lock())
                _LOCAL_AGENT_EXECUTION_LOCKS[self._key] = local
            local.users += 1
        if not local.lock.acquire(blocking=False):
            with _LOCAL_AGENT_EXECUTION_LOCKS_GUARD:
                local.users -= 1
                if local.users == 0 and _LOCAL_AGENT_EXECUTION_LOCKS.get(self._key) is local:
                    del _LOCAL_AGENT_EXECUTION_LOCKS[self._key]
            return False
        self._local = local
        return True

    def close(self) -> None:
        if self._connection is not None:
            connection = self._connection
            self._connection = None
            try:
                lock_key = _agent_execution_lock_key(self._outcome, self._key)
                released = bool(
                    connection.execute(
                        select(func.pg_advisory_unlock(lock_key))
                    ).scalar_one()
                )
                connection.commit()
                if not released:
                    connection.invalidate()
            except Exception:
                connection.invalidate()
                raise
            finally:
                connection.close()
        if self._local is not None:
            local = self._local
            self._local = None
            local.lock.release()
            with _LOCAL_AGENT_EXECUTION_LOCKS_GUARD:
                local.users -= 1
                if local.users == 0 and _LOCAL_AGENT_EXECUTION_LOCKS.get(self._key) is local:
                    del _LOCAL_AGENT_EXECUTION_LOCKS[self._key]


# Resolver que baixa a mídia da Evolution e a sobe no Storage, devolvendo o
# ponteiro (StoredMedia: .path/.mime/.nome/.tamanho). Injetado no worker para
# manter a ingestão testável (sem rede) — tipado como Any para evitar acoplar a
# ingestão ao módulo de storage.
MediaResolver = Callable[[ParsedMessage, Any, Any], Any]
ClaimGuard = Callable[[], None]


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
    igreja_id: Any | None = None
    provider_message_id: str | None = None
    claim_id: str | None = None


def ingest_message_event(db: Session, parsed: ParsedMessage) -> IngestionResult:
    """Persist one parsed inbound message, deduping contacts (RNF-16/US-07).

    Returns an IngestionResult describing what happened. Raises on unexpected
    database errors so the caller (worker) can retry (RNF-17).
    """
    return ingest_message_event_ex(db, parsed).result


def ingest_message_event_ex(
    db: Session,
    parsed: ParsedMessage,
    media_resolver: MediaResolver | None = None,
    ownership_guard: ClaimGuard | None = None,
) -> IngestionOutcome:
    """Like `ingest_message_event` but also returns the conversation context.

    Used by the worker to hand the persisted inbound message to the agent
    orchestrator (delta-034), which emits the single official-number reply.

    When the message carries media (`parsed.media_kind`) and a `media_resolver`
    is supplied, the bytes are fetched from Evolution and uploaded to Storage;
    a resolver failure degrades gracefully (the row keeps its media `tipo` so
    the panel shows a placeholder, instead of losing the message).

    MSG-IDEMP-1: if `messages_inbound_provider_id_uidx` rejects the insert
    (the same inbound provider_message_id was already persisted for this
    igreja — Redis dedupe expired/missed/lost the race), the whole
    transaction rolls back and this returns IngestionResult.DUPLICATE instead
    of raising, so the caller never double-runs the agent for it.
    """
    # Fase 1 (D4) — saída cross-tenant NOMEADA: o lookup por `instance` descobre
    # a igreja e por isso PRECISA rodar sem escopo (no papel de conexão). Marcar
    # explicitamente torna a ordem "lookup-antes-de-promoção" uma invariante
    # executável: promote_to_tenant abaixo FALHA (TenantPromotionError) se esta
    # fase não a preceder — a ordem virou estrutura, não comentário.
    mark_cross_tenant(db, source="worker_ingest")
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
    # Fase 2 (D4/#10b): promoção explícita para tenant-scoped. A partir daqui o
    # processamento é escopado à igreja (GUC app.tenant_igreja_id + papel
    # `authenticated`, pois o contato do WhatsApp não tem JWT do Clerk). O
    # listener after_begin (D2) reaplica o escopo em toda transação futura desta
    # sessão marcada — inclusive após o commit da ingestão.
    promote_to_tenant(db, igreja_id, source="worker_ingest")
    inbound = not parsed.from_me

    # The Redis processing list is the live ownership record. A handler whose
    # lease expired may still be running while another worker recovers the same
    # envelope, so fence the stale owner before it reaches any side effect.
    if ownership_guard is not None:
        ownership_guard()

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

    existing_message = _provider_message_after_fence(
        db,
        igreja_id,
        parsed.provider_message_id,
        inbound=inbound,
    )
    if existing_message is not None:
        logger.info(
            "Duplicate provider message %s for igreja %s (DB fence)",
            parsed.provider_message_id,
            igreja_id,
        )
        return IngestionOutcome(
            result=IngestionResult.DUPLICATE,
            conversation_id=existing_message.conversation_id,
            instance=parsed.instance,
            telefone=parsed.telefone_raw,
            texto=parsed.texto,
            inbound=inbound,
            igreja_id=igreja_id,
            provider_message_id=parsed.provider_message_id,
        )

    # The advisory lock above may have waited behind the current winner. Check
    # the Redis owner again before continuing with contact/media work.
    if ownership_guard is not None:
        ownership_guard()

    lock_canonical_phone(
        db, igreja_id=igreja_id, canonical=parsed.telefone
    )

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
        # Nasce como "contato" (US-10): quem fala pela 1ª vez e ainda não foi à
        # igreja/célula. Vira "visitante" só por evento real (líder cadastra,
        # consolidação ou check-in) — nunca por autodeclaração no chat.
        # UNIQ-PESSOA-1: SAVEPOINT + re-fetch da vencedora. Duas mensagens
        # inbound concorrentes do MESMO número (mesmo parsed.telefone_raw) não se
        # veem na dedupe acima e ambas tentariam inserir; uq_pessoas_telefone_ativa
        # serializa — a perdedora recebe unique_violation e reaproveita a Pessoa
        # vencedora. Caminho feliz idêntico. A Session aqui é a do turno; o
        # SAVEPOINT preserva o já pendente na transação externa.
        pessoa = insert_pessoa_or_get_winner(
            db,
            Pessoa(
                igreja_id=igreja_id,
                nome=parsed.push_name or parsed.telefone_raw,
                telefone=parsed.telefone_raw,
                origem="whatsapp",
                tipo="contato",
                etapa="ganhar",
                subetapa="novo_contato",
            ),
            igreja_id=igreja_id,
            canonical=parsed.telefone,
        )

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

    # Mídia (Etapa 2): baixa da Evolution + sobe no Storage. Se falhar, o `tipo`
    # ainda reflete que era mídia (painel mostra "indisponível"), sem quebrar a
    # ingestão nem perder a mensagem.
    stored = None
    if parsed.media_kind and media_resolver is not None:
        if ownership_guard is not None:
            ownership_guard()
        try:
            stored = media_resolver(parsed, igreja_id, conversation.id)
        except Exception:  # noqa: BLE001 - falha de mídia não derruba a ingestão
            logger.warning(
                "Falha ao baixar/guardar mídia da mensagem %s",
                parsed.provider_message_id,
            )

    message = Message(
        igreja_id=igreja_id,
        conversation_id=conversation.id,
        direcao="in" if inbound else "out",
        autor="contato" if inbound else "humano",
        texto=parsed.texto,
        tipo=parsed.media_kind or "texto",
        media_path=stored.path if stored else None,
        media_mime=(stored.mime if stored else parsed.media_mime)
        if parsed.media_kind
        else None,
        media_nome=(stored.nome if stored else parsed.media_nome)
        if parsed.media_kind
        else None,
        media_tamanho=stored.tamanho if stored else None,
        provider_message_id=parsed.provider_message_id,
    )
    db.add(message)

    conversation.ultima_mensagem = parsed.texto or media_snippet(parsed.media_kind)
    if inbound:
        conversation.nao_lidas = (conversation.nao_lidas or 0) + 1

    # trg_consent_on_inbound grants consent automatically on the first inbound.
    # An upload already in flight cannot be revoked if the lease expires. The
    # post-effect check prevents the stale owner from committing; Storage uses
    # a provider-id-derived upsert path, so the recovered owner overwrites the
    # same object instead of creating a duplicate/orphan.
    if ownership_guard is not None:
        ownership_guard()
    try:
        db.commit()
    except IntegrityError as exc:
        # MSG-IDEMP-1: segunda barreira (DB) contra a mesma barreira do Redis
        # (mark_processed_if_new) ter expirado/faltado/perdido a corrida.
        # Apenas a violação do índice de idempotência da mensagem é duplicata.
        # Outras constraints também podem falhar nesta transação e precisam
        # subir para o retry/diagnóstico, nunca ser mascaradas como redelivery.
        # O rollback desfaz Pessoa/Conversation/Message inteiros desta chamada,
        # então o lado perdedor de uma corrida na primeira mensagem de um
        # contato novo nunca deixa registro órfão.
        db.rollback()
        if not _is_provider_message_duplicate(exc):
            raise
        logger.info(
            "Duplicate inbound message %s for igreja %s (DB-level dedupe)",
            parsed.provider_message_id,
            igreja_id,
        )
        existing_message = _provider_message_after_fence(
            db,
            igreja_id,
            parsed.provider_message_id,
            inbound=inbound,
        )
        return IngestionOutcome(
            result=IngestionResult.DUPLICATE,
            conversation_id=(
                existing_message.conversation_id if existing_message is not None else None
            ),
            instance=parsed.instance,
            telefone=parsed.telefone_raw,
            texto=parsed.texto,
            inbound=inbound,
            igreja_id=igreja_id,
            provider_message_id=parsed.provider_message_id,
        )
    return IngestionOutcome(
        result=IngestionResult.REGISTERED,
        conversation_id=conversation.id,
        instance=parsed.instance,
        telefone=parsed.telefone_raw,
        texto=parsed.texto,
        inbound=inbound,
        igreja_id=igreja_id,
        provider_message_id=parsed.provider_message_id,
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
    claim_id: str = ""

    def __post_init__(self) -> None:
        if not self.claim_id:
            self.claim_id = uuid.uuid4().hex

    def to_json(self) -> str:
        return json.dumps(
            {
                "payload": self.payload,
                "attempts": self.attempts,
                "claim_id": self.claim_id,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "_Envelope":
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Webhook envelope must be a JSON object")
        claim_id = data.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id:
            # Backward compatibility for envelopes already in Redis during the
            # rollout. Hashing the exact raw value gives the crashed/recovered
            # item a stable owner without making a fresh duplicate delivery of
            # the same provider id share that owner going forward.
            claim_id = f"legacy-{sha256(raw.encode('utf-8')).hexdigest()}"
        return cls(
            payload=data.get("payload", {}),
            attempts=int(data.get("attempts", 0)),
            claim_id=claim_id,
        )


class WebhookQueue:
    """Reliable Redis-list handoff for webhook payloads."""

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client or _build_redis()

    def enqueue(self, payload: dict[str, Any]) -> None:
        """Push a new webhook payload onto the queue (attempts=0)."""
        self._redis.lpush(WEBHOOK_QUEUE, _Envelope(payload=payload).to_json())

    @staticmethod
    def processing_queue(worker_id: str) -> str:
        """Return the private processing-list key owned by one worker."""
        return f"{PROCESSING_QUEUE}:{worker_id}"

    @staticmethod
    def _lease_key(worker_id: str) -> str:
        return f"{WORKER_LEASE_PREFIX}{worker_id}"

    @staticmethod
    def _recovery_lock_key(worker_id: str) -> str:
        return f"{WORKER_RECOVERY_LOCK_PREFIX}{worker_id}"

    def _compare_and_delete(self, key: str, expected: str) -> bool:
        return bool(
            self._redis.eval(
                _COMPARE_AND_DELETE_SCRIPT,
                1,
                key,
                expected,
            )
        )

    def register_worker(self, worker_id: str) -> None:
        """Register a worker and create its renewable ownership lease."""
        self._redis.set(
            self._lease_key(worker_id),
            worker_id,
            ex=WORKER_LEASE_SECONDS,
        )
        self._redis.sadd(WORKER_REGISTRY, worker_id)

    def refresh_worker_lease(self, worker_id: str) -> bool:
        """Renew an existing lease without resurrecting an expired owner."""
        return bool(
            self._redis.set(
                self._lease_key(worker_id),
                worker_id,
                xx=True,
                ex=WORKER_LEASE_SECONDS,
            )
        )

    def unregister_worker(self, worker_id: str) -> None:
        """Release a clean worker lease, preserving orphan discovery if needed."""
        self._compare_and_delete(self._lease_key(worker_id), worker_id)
        if self._redis.llen(self.processing_queue(worker_id)) == 0:
            self._redis.srem(WORKER_REGISTRY, worker_id)

    def claim(self, worker_id: str, timeout: int = BRPOP_TIMEOUT) -> str | None:
        """Move the oldest ready item to this worker's private processing list."""
        return self._redis.brpoplpush(
            WEBHOOK_QUEUE,
            self.processing_queue(worker_id),
            timeout=timeout,
        )

    def ack(self, worker_id: str, raw: str) -> None:
        """Acknowledge one claimed item after success, ignore, or requeue."""
        self._redis.lrem(self.processing_queue(worker_id), 1, raw)

    def owns_claim(self, worker_id: str, raw: str) -> bool:
        """Return whether this live worker still owns this exact queue item.

        Lease and private-list membership are checked in one Redis script so a
        recovered item cannot be processed concurrently by its expired owner.
        """
        return bool(
            self._redis.eval(
                _OWNS_CLAIM_SCRIPT,
                2,
                self._lease_key(worker_id),
                self.processing_queue(worker_id),
                worker_id,
                raw,
            )
        )

    def assert_claim_owned(self, worker_id: str, raw: str) -> None:
        """Fence the next effect with a live lease and private-list ownership.

        The check and lease renewal are one Redis operation.  A worker whose
        lease expired cannot revive it after a recovery worker registered the
        new owner, while a legitimate bounded effect gets a full lease window
        immediately before it starts.
        """
        try:
            owned = bool(
                self._redis.eval(
                    _FENCE_CLAIM_SCRIPT,
                    2,
                    self._lease_key(worker_id),
                    self.processing_queue(worker_id),
                    worker_id,
                    raw,
                    str(WORKER_LEASE_SECONDS),
                )
            )
        except Exception as exc:  # noqa: BLE001 - unverifiable means unsafe
            raise ClaimOwnershipLost(
                "Webhook queue claim ownership could not be verified"
            ) from exc
        if not owned:
            raise ClaimOwnershipLost(
                "Webhook queue claim was recovered by another worker"
            )

    def recover_pending(self, current_worker_id: str) -> int:
        """Recover only processing lists whose worker lease has expired.

        RPOPLPUSH preserves at-least-once delivery: the item is never between
        lists. A per-owner recovery lock prevents two live workers from draining
        the same abandoned list. Active workers retain their private list.
        """
        recovered = 0
        for raw_owner in self._redis.smembers(WORKER_REGISTRY):
            owner = (
                raw_owner.decode("utf-8")
                if isinstance(raw_owner, bytes)
                else str(raw_owner)
            )
            if owner == current_worker_id:
                continue
            lease_key = self._lease_key(owner)
            if self._redis.exists(lease_key):
                continue
            lock_key = self._recovery_lock_key(owner)
            locked = self._redis.set(
                lock_key,
                current_worker_id,
                nx=True,
                ex=WORKER_LEASE_SECONDS,
            )
            if not locked:
                continue
            try:
                # Close the check/lock race: a worker that still owned its lease
                # when we took the lock must never have its active item stolen.
                if self._redis.exists(lease_key):
                    continue
                processing = self.processing_queue(owner)
                while self._redis.rpoplpush(processing, WEBHOOK_QUEUE) is not None:
                    recovered += 1
                self._redis.srem(WORKER_REGISTRY, owner)
            finally:
                self._compare_and_delete(lock_key, current_worker_id)
        return recovered

    @staticmethod
    def _claim_marker(claim_id: str) -> str:
        return f"{_PROCESSING_MARKER}:{claim_id}"

    def mark_processed_if_new(self, message_id: str, claim_id: str) -> bool:
        """Claim a provider id for this envelope; reject every other owner.

        The exact same envelope keeps ``claim_id`` across crash recovery and
        retry, so it may resume an in-flight claim. A separate delivery gets a
        different token and is rejected before DB/media work. ``done`` is final.
        """
        return self.claim_processing(message_id, claim_id) is not ProcessingClaim.REJECTED

    def claim_processing(self, message_id: str, claim_id: str) -> ProcessingClaim:
        """Create, resume or reject the envelope's idempotency claim."""
        key = f"{PROCESSED_PREFIX}{message_id}"
        marker = self._claim_marker(claim_id)
        claimed = self._redis.set(
            key,
            marker,
            nx=True,
            ex=PROCESSED_TTL_SECONDS,
        )
        if claimed:
            return ProcessingClaim.NEW
        if self._redis.get(key) == marker:
            return ProcessingClaim.RESUMED
        return ProcessingClaim.REJECTED

    def mark_processed(self, message_id: str, claim_id: str) -> None:
        """Finalize an idempotency marker owned by this envelope."""
        key = f"{PROCESSED_PREFIX}{message_id}"
        marker = self._claim_marker(claim_id)
        finalized = self._redis.eval(
            _MARK_DONE_SCRIPT,
            1,
            key,
            marker,
            _PROCESSED_MARKER,
            str(PROCESSED_TTL_SECONDS),
        )
        if not finalized:
            raise RuntimeError("Webhook idempotency claim ownership was lost")

    def mark_processed_if_owned(
        self,
        message_id: str,
        claim_id: str,
        worker_id: str,
        raw: str,
    ) -> bool:
        """Finalize only while this live worker owns the exact raw claim."""
        key = f"{PROCESSED_PREFIX}{message_id}"
        return bool(
            self._redis.eval(
                _MARK_DONE_IF_OWNED_SCRIPT,
                3,
                self._lease_key(worker_id),
                self.processing_queue(worker_id),
                key,
                worker_id,
                raw,
                self._claim_marker(claim_id),
                _PROCESSED_MARKER,
                str(PROCESSED_TTL_SECONDS),
            )
        )

    def release_processed(self, message_id: str, claim_id: str) -> None:
        """Release a previously-claimed message id so a retry can reprocess it.

        Called when ingestion fails after the id was claimed, so the bounded
        reprocess (RNF-17) is not silently dropped as a duplicate. It never
        deletes a marker owned by a different delivery or a completed marker.
        """
        key = f"{PROCESSED_PREFIX}{message_id}"
        self._compare_and_delete(key, self._claim_marker(claim_id))

    def release_processed_if_owned(
        self,
        message_id: str,
        claim_id: str,
        worker_id: str,
        raw: str,
    ) -> bool:
        """Release a retry marker only while this worker owns the raw item."""
        key = f"{PROCESSED_PREFIX}{message_id}"
        return bool(
            self._redis.eval(
                _RELEASE_MARKER_IF_OWNED_SCRIPT,
                3,
                self._lease_key(worker_id),
                self.processing_queue(worker_id),
                key,
                worker_id,
                raw,
                self._claim_marker(claim_id),
            )
        )

    def transition_failed_claim(
        self,
        worker_id: str,
        raw: str,
        envelope: _Envelope,
    ) -> None:
        """Move a failed claim only while its worker still owns a live lease."""
        next_attempts = envelope.attempts + 1
        replacement = _Envelope(
            payload=envelope.payload,
            attempts=next_attempts,
            claim_id=envelope.claim_id,
        )
        if next_attempts >= MAX_ATTEMPTS:
            target = DEAD_LETTER_QUEUE
        else:
            target = WEBHOOK_QUEUE
        try:
            moved = self._redis.eval(
                _MOVE_FAILED_CLAIM_SCRIPT,
                3,
                self._lease_key(worker_id),
                self.processing_queue(worker_id),
                target,
                worker_id,
                raw,
                replacement.to_json(),
            )
        except Exception as exc:  # noqa: BLE001 - unverifiable means unsafe
            raise ClaimOwnershipLost(
                "Webhook failed claim ownership could not be verified"
            ) from exc
        if moved != 1:
            # A Lua error, wrong destination type, timeout, or deliberately
            # recoverable partial transition is never success.  The original
            # claim remains recoverable or the replacement is already durable;
            # stopping this worker avoids a stale retry/dead-letter mutation.
            raise ClaimOwnershipLost("Webhook failed claim was no longer owned")
        if target == DEAD_LETTER_QUEUE:
            logger.error(
                "Webhook exhausted retries (%d), moving to dead-letter",
                next_attempts,
            )


class QueueWorker:
    """Long-running consumer that drains WEBHOOK_QUEUE into Postgres."""

    def __init__(
        self,
        queue: WebhookQueue | None = None,
        session_factory: Any | None = None,
        agent_runner: (
            "Callable[[Any, IngestionOutcome, ClaimGuard | None], None] | None"
        ) = None,
        media_resolver: MediaResolver | None = None,
        worker_id: str | None = None,
        heartbeat_publisher: Callable[[str, int], None] | None = None,
        progress_clock: Callable[[], float] = time.monotonic,
        progress_timeout_seconds: float = WORKER_PROGRESS_TIMEOUT_SECONDS,
    ) -> None:
        self._queue = queue or WebhookQueue()
        self._session_factory = session_factory or get_session_factory()
        # Optional orchestrator hook (delta-034). When set, a freshly persisted
        # inbound message is handed to the agent, which emits the single reply.
        # Defaulting to None keeps ingestion-only tests free of agent/DB needs.
        self._agent_runner = agent_runner
        # Optional media hook (Etapa 2). When set, inbound media is fetched from
        # Evolution and uploaded to Storage. None keeps ingestion tests offline.
        self._media_resolver = media_resolver
        self._worker_id = worker_id or uuid.uuid4().hex
        self._running = False
        self._heartbeat_stop = Event()
        self._heartbeat_thread: Thread | None = None
        self._health_state = "ready"
        self._progress_clock = progress_clock
        self._progress_timeout_seconds = max(
            float(WORKER_LEASE_SECONDS),
            float(progress_timeout_seconds),
        )
        self._progress_lock = Lock()
        self._last_progress_at = self._progress_clock()
        self._heartbeat_publisher = heartbeat_publisher or (
            lambda state, ttl: publish_worker_heartbeat(
                None,
                worker_name="queue-worker",
                state=state,
                ttl_seconds=ttl,
                client=self._queue._redis,  # noqa: SLF001 - same module owner
            )
        )

    def _record_progress(self) -> None:
        with self._progress_lock:
            self._last_progress_at = self._progress_clock()

    def _progress_stale(self) -> bool:
        with self._progress_lock:
            last_progress_at = self._last_progress_at
        return (
            self._progress_clock() - last_progress_at
            > self._progress_timeout_seconds
        )

    def _heartbeat_once(self) -> bool:
        """Renew lease/health only while the main consumer made recent progress."""
        if self._progress_stale():
            logger.error("Webhook worker stalled; lease renewal stopped")
            self._publish_health("error")
            self._running = False
            return False
        try:
            renewed = self._queue.refresh_worker_lease(self._worker_id)
        except Exception as exc:  # noqa: BLE001 - lease loss stops consumption
            logger.error(
                "Webhook worker lease renewal failed error_type=%s",
                type(exc).__name__,
            )
            self._publish_health("error")
            self._running = False
            return False
        if not renewed:
            logger.error("Webhook worker lease expired; stopping consumer")
            self._publish_health("error")
            self._running = False
            return False
        self._publish_health()
        return True

    def _publish_health(self, state: str | None = None) -> None:
        if state is not None:
            self._health_state = state
        try:
            self._heartbeat_publisher(self._health_state, WORKER_LEASE_SECONDS)
        except Exception as exc:  # noqa: BLE001 - telemetry cannot stop ingestion
            logger.warning(
                "Queue worker heartbeat failed error_type=%s",
                type(exc).__name__,
            )

    def stop(self, *_: Any) -> None:
        """Request a graceful shutdown (used as a SIGTERM/SIGINT handler)."""
        logger.info("Queue worker shutdown requested")
        self._running = False

    def _heartbeat_loop(self) -> None:
        """Renew a claim lease only inside the bounded progress window."""
        while not self._heartbeat_stop.wait(WORKER_HEARTBEAT_SECONDS):
            if not self._heartbeat_once():
                return

    def _assert_effect_ownership(self, raw: str) -> None:
        """Fence an effect and count that successful fence as main-loop progress."""
        self._queue.assert_claim_owned(self._worker_id, raw)
        self._record_progress()

    def run(self) -> None:
        """Block draining the queue until stopped (graceful shutdown)."""
        self._running = True
        self._heartbeat_stop.clear()
        self._queue.register_worker(self._worker_id)
        self._record_progress()
        self._publish_health("ready")
        heartbeat = Thread(
            target=self._heartbeat_loop,
            name=f"webhook-lease-{self._worker_id[:8]}",
            daemon=True,
        )
        self._heartbeat_thread = heartbeat
        heartbeat.start()
        next_recovery_at = 0.0
        try:
            logger.info(
                "Queue worker %s started, consuming %s",
                self._worker_id,
                WEBHOOK_QUEUE,
            )
            while self._running:
                if not self._queue.refresh_worker_lease(self._worker_id):
                    logger.error("Webhook worker lease expired; stopping consumer")
                    self._publish_health("error")
                    break
                self._record_progress()
                if not self._running:
                    break
                now = time.monotonic()
                if now >= next_recovery_at:
                    recovered = self._queue.recover_pending(self._worker_id)
                    if recovered:
                        logger.warning(
                            "Recovered %d abandoned webhook claim(s)", recovered
                        )
                    next_recovery_at = now + WORKER_HEARTBEAT_SECONDS
                raw = self._queue.claim(self._worker_id, timeout=BRPOP_TIMEOUT)
                self._record_progress()
                if raw is None:
                    continue
                self._publish_health("running")
                self._handle_raw(raw)
                self._record_progress()
                if self._running:
                    self._publish_health("ready")
        finally:
            self._running = False
            self._heartbeat_stop.set()
            heartbeat.join(timeout=REDIS_SOCKET_TIMEOUT_SECONDS + 1)
            self._publish_health("stopped")
            self._queue.unregister_worker(self._worker_id)
            logger.info("Queue worker %s stopped", self._worker_id)

    def _handle_raw(self, raw: str) -> None:
        try:
            envelope = _Envelope.from_json(raw)
        except (ValueError, TypeError):
            logger.error("Discarding malformed envelope from queue")
            self._queue.ack(self._worker_id, raw)
            return
        ownership_guard = partial(self._assert_effect_ownership, raw)
        try:
            ownership_guard()
            self.handle_envelope(envelope, claimed_raw=raw)
        except ClaimOwnershipLost:
            # Recovery already moved the raw item out of this worker's private
            # list, or Redis could not safely prove ownership. Stop consuming so
            # this raw claim remains discoverable; do not ack or requeue here.
            logger.warning("Webhook claim ownership lost during processing")
            self._running = False
            return
        except Exception:  # noqa: BLE001 - any error triggers a bounded retry
            logger.exception("Webhook processing failed; scheduling reprocess")
            try:
                self._queue.transition_failed_claim(self._worker_id, raw, envelope)
            except ClaimOwnershipLost:
                # The raw item remains in (or was recovered from) the private
                # list. A stale worker must not retry/dead-letter it after its
                # lease expires; stop and let the current owner recover it.
                logger.warning("Webhook claim ownership lost during failure handling")
                self._running = False
            return
        self._queue.ack(self._worker_id, raw)

    def handle_envelope(
        self,
        envelope: _Envelope,
        *,
        claimed_raw: str | None = None,
    ) -> IngestionResult:
        """Process one envelope: idempotency guard + DB ingestion.

        The message id is claimed before processing (dedupe) and released if
        ingestion fails, so the bounded reprocess (RNF-17) is not dropped as a
        duplicate.
        """
        parsed = parse_message_event(envelope.payload)
        if parsed is None:
            return IngestionResult.IGNORED

        ownership_guard = (
            partial(self._assert_effect_ownership, claimed_raw)
            if claimed_raw is not None
            else None
        )

        processing_claim = self._queue.claim_processing(
            parsed.provider_message_id,
            envelope.claim_id,
        )
        if processing_claim is ProcessingClaim.REJECTED:
            logger.info("Skipping duplicate message %s", parsed.provider_message_id)
            return IngestionResult.DUPLICATE

        try:
            session: Session = self._session_factory()
            try:
                outcome = ingest_message_event_ex(
                    session,
                    parsed,
                    media_resolver=self._media_resolver,
                    ownership_guard=ownership_guard,
                )
            finally:
                session.close()
        except ClaimOwnershipLost:
            # The recovered envelope intentionally keeps the same claim id.
            # Do not delete its shared processing marker from the stale owner.
            raise
        except Exception as exc:
            # Release the claim so the requeued envelope can be reprocessed.
            if claimed_raw is None:
                self._queue.release_processed(
                    parsed.provider_message_id,
                    envelope.claim_id,
                )
            else:
                try:
                    released = self._queue.release_processed_if_owned(
                        parsed.provider_message_id,
                        envelope.claim_id,
                        self._worker_id,
                        claimed_raw,
                    )
                except Exception as ownership_exc:  # noqa: BLE001
                    raise ClaimOwnershipLost(
                        "Webhook queue claim ownership could not be verified"
                    ) from ownership_exc
                if not released:
                    raise ClaimOwnershipLost(
                        "Webhook queue claim was recovered during failure handling"
                    ) from exc
            raise

        # Hand the persisted inbound message to the orchestrator (delta-034).
        # A recovered envelope may observe the already committed inbound row.
        # It resumes the agent only when it owns the same in-flight claim; a new
        # delivery rejected by Redis never re-runs the agent.
        should_run_agent = outcome.result is IngestionResult.REGISTERED or (
            processing_claim is ProcessingClaim.RESUMED
            and outcome.result is IngestionResult.DUPLICATE
        )
        if (
            self._agent_runner is not None
            and should_run_agent
            and outcome.inbound
        ):
            # The claim survives Redis recovery in the serialized envelope and
            # becomes part of the durable outbound reply idempotency key.
            outcome.claim_id = envelope.claim_id
            if ownership_guard is not None:
                ownership_guard()
            agent_disposition = self._agent_runner(
                self._session_factory,
                outcome,
                ownership_guard,
            )
            if agent_disposition is AgentRunDisposition.IN_FLIGHT:
                # A previous process still holds the durable execution lease.
                # Do not ACK this recovered raw claim: its current owner stops
                # and leaves it discoverable once the active lease finishes or
                # expires.  Treating it as success would lose recovery after a
                # crash before the agent persisted its terminal state.
                raise ClaimOwnershipLost("Agent execution is already in flight")

        # Finalization is the last effect. Until it succeeds the same claim stays
        # recoverable. A stale owner cannot finalize after another worker moved
        # the raw item out of its private processing list.
        if claimed_raw is None:
            self._queue.mark_processed(parsed.provider_message_id, envelope.claim_id)
        elif not self._queue.mark_processed_if_owned(
            parsed.provider_message_id,
            envelope.claim_id,
            self._worker_id,
            claimed_raw,
        ):
            raise ClaimOwnershipLost("Webhook claim was recovered before finalization")

        return outcome.result


# ---------------------------------------------------------------------------
# Agent orchestration runner (delta-034)
# ---------------------------------------------------------------------------
def _agent_reply_idempotency_key(outcome: IngestionOutcome) -> str | None:
    """Return one stable durable key for an inbound event and its queue claim."""

    if (
        outcome.igreja_id is None
        or not outcome.provider_message_id
        or not outcome.claim_id
    ):
        return None
    material = (
        f"{outcome.igreja_id}:{outcome.provider_message_id}:{outcome.claim_id}"
    ).encode("utf-8")
    return f"{_AGENT_REPLY_PROVIDER_PREFIX}{sha256(material).hexdigest()}"


def _agent_execution_lock_key(outcome: IngestionOutcome, provider_message_id: str) -> int:
    """Use a distinct PostgreSQL advisory-lock namespace for agent execution."""

    return _provider_message_lock_key(
        outcome.igreja_id,
        f"agent-execution:{provider_message_id}",
    )


def _agent_reply_after_fence(
    db: Session, igreja_id: Any, provider_message_id: str
) -> Message | None:
    """Fence one reply plan and return its existing durable row, if any.

    The ``:<response-hash>`` suffix was part of the pre-single-flight key.
    Read it only for recovery compatibility: all new plans use the exact,
    stable claim-derived key above.
    """

    get_bind = getattr(db, "get_bind", None)
    if get_bind is not None and get_bind().dialect.name == "postgresql":
        db.execute(
            select(
                func.pg_advisory_xact_lock(
                    _provider_message_lock_key(igreja_id, provider_message_id)
                )
            )
        ).scalar_one_or_none()
    return db.execute(
        select(Message)
        .where(
            Message.igreja_id == igreja_id,
            Message.direcao == "out",
            or_(
                Message.provider_message_id == provider_message_id,
                Message.provider_message_id.like(f"{provider_message_id}:%"),
            ),
        )
        .order_by(Message.criado_em.asc(), Message.id.asc())
        .limit(1)
    ).scalar_one_or_none()


def _intent_from_message(message: Message) -> _AgentReplyIntent:
    return _AgentReplyIntent(
        id=message.id,
        state=message.autor,
        response=message.texto or "",
        provider_message_id=message.provider_message_id or "",
    )


def _scope_agent_session(session: Session, outcome: IngestionOutcome) -> None:
    if outcome.igreja_id is not None:
        mark_tenant_scoped(session, outcome.igreja_id, source="worker_agent")


def _load_agent_reply_intent(
    session_factory: Any, outcome: IngestionOutcome
) -> _AgentReplyIntent | None:
    provider_message_id = _agent_reply_idempotency_key(outcome)
    if provider_message_id is None:
        return None
    session: Session = session_factory()
    try:
        _scope_agent_session(session, outcome)
        existing = _agent_reply_after_fence(
            session,
            outcome.igreja_id,
            provider_message_id,
        )
        return _intent_from_message(existing) if existing is not None else None
    finally:
        session.close()


def _reserve_agent_reply_intent(
    session_factory: Any, outcome: IngestionOutcome
) -> _AgentReplyIntent | None:
    """Persist a single-flight reservation before mutable agent work starts."""

    provider_message_id = _agent_reply_idempotency_key(outcome)
    if provider_message_id is None:
        return None
    session: Session = session_factory()
    try:
        _scope_agent_session(session, outcome)
        existing = _agent_reply_after_fence(
            session,
            outcome.igreja_id,
            provider_message_id,
        )
        if existing is not None:
            return _intent_from_message(existing)

        conversation = session.get(Conversation, outcome.conversation_id)
        if conversation is None:
            return None
        message = Message(
            igreja_id=conversation.igreja_id,
            conversation_id=conversation.id,
            direcao="out",
            autor=_AGENT_REPLY_RESERVED,
            texto=None,
            tipo="texto",
            provider_message_id=provider_message_id,
        )
        session.add(message)
        try:
            session.commit()
        except IntegrityError:
            # The unique outbound index remains the durable final barrier if a
            # compatible backend cannot supply the PostgreSQL advisory lock.
            session.rollback()
            existing = _agent_reply_after_fence(
                session,
                outcome.igreja_id,
                provider_message_id,
            )
            if existing is None:
                raise
            return _intent_from_message(existing)
        return _intent_from_message(message)
    finally:
        session.close()


def _prepare_agent_reply_intent(
    session_factory: Any, outcome: IngestionOutcome, response: str
) -> _AgentReplyIntent | None:
    """Persist a reply intent before the provider call.

    Production Postgres serializes the prefix with an advisory transaction lock.
    The existing outbound unique index remains the durable final barrier.  A
    race always returns the first intent and never grants two transports.
    """

    provider_message_id = _agent_reply_idempotency_key(outcome)
    if provider_message_id is None:
        return None
    session: Session = session_factory()
    try:
        _scope_agent_session(session, outcome)
        existing = _agent_reply_after_fence(
            session,
            outcome.igreja_id,
            provider_message_id,
        )
        if existing is not None:
            if existing.autor in {_AGENT_REPLY_RESERVED, _AGENT_REPLY_EXECUTING}:
                transitioned = session.execute(
                    update(Message)
                    .where(
                        Message.id == existing.id,
                        Message.autor.in_(
                            {_AGENT_REPLY_RESERVED, _AGENT_REPLY_EXECUTING}
                        ),
                    )
                    .values(autor=_AGENT_REPLY_PENDING, texto=response)
                    .returning(Message.id)
                ).scalar_one_or_none()
                if transitioned is not None:
                    session.commit()
                    session.refresh(existing)
                else:
                    session.rollback()
                    existing = _agent_reply_after_fence(
                        session,
                        outcome.igreja_id,
                        provider_message_id,
                    )
                    if existing is None:
                        raise RuntimeError("Agent reply reservation disappeared")
            return _intent_from_message(existing)

        conversation = session.get(Conversation, outcome.conversation_id)
        if conversation is None:
            return None
        message = Message(
            igreja_id=conversation.igreja_id,
            conversation_id=conversation.id,
            direcao="out",
            autor=_AGENT_REPLY_PENDING,
            texto=response,
            tipo="texto",
            provider_message_id=provider_message_id,
        )
        session.add(message)
        try:
            session.commit()
        except IntegrityError:
            # The database fence already serializes Postgres.  This catch is a
            # second durable barrier for a collision or a compatible future
            # backend that enforces the unique outbound index without advisory
            # locks.
            session.rollback()
            existing = _agent_reply_after_fence(
                session,
                outcome.igreja_id,
                provider_message_id,
            )
            if existing is None:
                raise
            return _intent_from_message(existing)
        return _intent_from_message(message)
    finally:
        session.close()


def _transition_agent_reply_intent(
    session_factory: Any,
    outcome: IngestionOutcome,
    intent: _AgentReplyIntent,
    *,
    expected: str,
    target: str,
    refresh_snapshot: bool = False,
    ownership_guard: ClaimGuard | None = None,
) -> bool:
    """Move an intent exactly once, optionally fenced by the live Redis claim.

    The compare-and-set lives in PostgreSQL, rather than in an ORM object read
    before the write.  Two recovered workers can otherwise both observe
    ``ia_pendente`` and each commit an ``ia_em_transporte`` transition, opening
    a second provider call.  ``UPDATE ... WHERE autor = expected RETURNING``
    is the cross-process transport fence.
    """

    session: Session = session_factory()
    try:
        _scope_agent_session(session, outcome)
        if ownership_guard is not None:
            ownership_guard()
        transitioned = session.execute(
            update(Message)
            .where(Message.id == intent.id, Message.autor == expected)
            .values(autor=target)
            .returning(Message.conversation_id, Message.texto)
        ).one_or_none()
        if transitioned is None:
            return False
        if refresh_snapshot:
            session.execute(
                update(Conversation)
                .where(Conversation.id == transitioned.conversation_id)
                .values(ultima_mensagem=transitioned.texto)
            )
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _quarantine_agent_reply(
    session_factory: Any, outcome: IngestionOutcome, intent: _AgentReplyIntent
) -> None:
    """Best-effort durable quarantine after an ambiguous provider boundary."""

    try:
        _transition_agent_reply_intent(
            session_factory,
            outcome,
            intent,
            expected=_AGENT_REPLY_IN_FLIGHT,
            target=_AGENT_REPLY_AMBIGUOUS,
        )
    except Exception:  # noqa: BLE001 - preserve the no-resend fence on DB trouble
        logger.warning("Agent reply left unresolved after provider boundary")


def _quarantine_agent_execution(
    session_factory: Any,
    outcome: IngestionOutcome,
    intent: _AgentReplyIntent,
) -> None:
    """Fence an agent turn whose side effects can no longer be proven absent."""

    try:
        _transition_agent_reply_intent(
            session_factory,
            outcome,
            intent,
            expected=_AGENT_REPLY_EXECUTING,
            target=_AGENT_REPLY_EXECUTION_AMBIGUOUS,
        )
    except Exception:  # noqa: BLE001 - retain the execution fence on DB trouble
        logger.warning("Agent execution left unresolved; automatic rerun skipped")


def _release_agent_execution_reservation(
    session_factory: Any,
    outcome: IngestionOutcome,
    intent: _AgentReplyIntent,
) -> None:
    """Return a pre-agent reservation only when no mutable turn started."""

    try:
        _transition_agent_reply_intent(
            session_factory,
            outcome,
            intent,
            expected=_AGENT_REPLY_EXECUTING,
            target=_AGENT_REPLY_RESERVED,
        )
    except Exception:  # noqa: BLE001 - a failed release remains safely fenced
        logger.warning("Agent reservation ownership was lost before execution")


def _send_agent_reply(
    client: Any, instance: str | None, telefone: str | None, response: str
) -> str:
    """Classify one provider call conservatively without exposing its response."""

    classified = getattr(client, "send_text_classificado", None)
    if classified is None:
        classified = getattr(client, "send_text_classified", None)
    try:
        if callable(classified):
            status = getattr(classified(instance, telefone, response), "status", None)
            return status if isinstance(status, str) else "desconhecido"
        sent = client.send_text(instance, telefone, response)
    except Exception:  # noqa: BLE001 - an unclassified call may have reached Evolution
        return "desconhecido"
    return "aceito" if sent is True else "suprimido"


def _deliver_agent_reply_intent(
    session_factory: Any,
    outcome: IngestionOutcome,
    intent: _AgentReplyIntent,
    ownership_guard: ClaimGuard | None,
    *,
    evolution_client: Any | None,
) -> None:
    """Run at most one Evolution transport for a durable reply intent.

    Evolution does not provide an idempotency key contract.  Therefore an
    in-flight, ambiguous, failed, or suppressed intent is never auto-sent
    again; only a persisted ``ia_pendente`` intent can cross the provider
    boundary.  Operators can reconcile quarantined rows safely before any
    manual recovery.
    """

    if intent.state == _AGENT_REPLY_CONFIRMED:
        return
    if intent.state in {
        _AGENT_REPLY_RESERVED,
        _AGENT_REPLY_EXECUTING,
        _AGENT_REPLY_IN_FLIGHT,
        _AGENT_REPLY_AMBIGUOUS,
        _AGENT_REPLY_EXECUTION_AMBIGUOUS,
        _AGENT_REPLY_FAILED,
        _AGENT_REPLY_SUPPRESSED,
        _AGENT_REPLY_NO_RESPONSE,
    }:
        logger.warning("Agent reply requires reconciliation; automatic resend skipped")
        return
    if intent.state != _AGENT_REPLY_PENDING or not intent.response:
        logger.warning("Agent reply intent is not eligible for automatic transport")
        return

    # Claim the durable intent before the call.  The conditional state move is
    # the cross-process transport fence; a competing worker can only observe
    # ``ia_em_transporte`` and therefore cannot start a second Evolution call.
    if not _transition_agent_reply_intent(
        session_factory,
        outcome,
        intent,
        expected=_AGENT_REPLY_PENDING,
        target=_AGENT_REPLY_IN_FLIGHT,
        ownership_guard=ownership_guard,
    ):
        return

    try:
        # Immediate pre-effect guard.  If it fails, no provider call happened,
        # so returning the intent to pending is safe for the recovered owner.
        if ownership_guard is not None:
            ownership_guard()
    except ClaimOwnershipLost:
        try:
            _transition_agent_reply_intent(
                session_factory,
                outcome,
                intent,
                expected=_AGENT_REPLY_IN_FLIGHT,
                target=_AGENT_REPLY_PENDING,
            )
        except Exception:  # noqa: BLE001 - leave unresolved rather than resend blindly
            logger.warning("Agent reply ownership was lost before transport")
        raise

    def send_with(client: Any) -> str:
        return _send_agent_reply(client, outcome.instance, outcome.telefone, intent.response)

    if evolution_client is None:
        from app.services.evolution import EvolutionClient  # noqa: PLC0415

        with EvolutionClient() as client:
            status = send_with(client)
    else:
        status = send_with(evolution_client)

    if status == "aceito":
        try:
            # A stale owner must not write the post-send confirmation.  The
            # durable in-flight row remains a no-resend fence for its successor.
            if ownership_guard is not None:
                ownership_guard()
            if not _transition_agent_reply_intent(
                session_factory,
                outcome,
                intent,
                expected=_AGENT_REPLY_IN_FLIGHT,
                target=_AGENT_REPLY_CONFIRMED,
                refresh_snapshot=True,
            ):
                _quarantine_agent_reply(session_factory, outcome, intent)
        except ClaimOwnershipLost:
            raise
        except Exception:  # noqa: BLE001 - accepted but durable outcome is uncertain
            _quarantine_agent_reply(session_factory, outcome, intent)
            logger.warning("Agent reply confirmation is unresolved; automatic resend skipped")
        return

    if status == "falhou_retentavel":
        try:
            released = _transition_agent_reply_intent(
                session_factory,
                outcome,
                intent,
                expected=_AGENT_REPLY_IN_FLIGHT,
                target=_AGENT_REPLY_PENDING,
            )
        except Exception:  # noqa: BLE001 - do not retry if the durable state is unknown
            _quarantine_agent_reply(session_factory, outcome, intent)
            return
        if released:
            raise AgentReplyRetryable("Evolution rejected agent reply before send")
        return

    if status == "desconhecido":
        _quarantine_agent_reply(session_factory, outcome, intent)
        logger.warning("Agent reply transport is ambiguous; automatic resend skipped")
        return

    target = _AGENT_REPLY_SUPPRESSED if status == "suprimido" else _AGENT_REPLY_FAILED
    try:
        _transition_agent_reply_intent(
            session_factory,
            outcome,
            intent,
            expected=_AGENT_REPLY_IN_FLIGHT,
            target=target,
        )
    except Exception:  # noqa: BLE001 - no further send after an unknown final write
        _quarantine_agent_reply(session_factory, outcome, intent)


def _run_agent_legacy(
    session_factory: Any,
    outcome: IngestionOutcome,
    response: str,
    ownership_guard: ClaimGuard | None,
    *,
    evolution_client: Any | None,
) -> None:
    """Compatibility path for old callers that lack a provider event/claim.

    QueueWorker always supplies both fields.  This branch keeps focused legacy
    unit tests and out-of-tree integrations working, but must not be used for
    webhook-derived production replies because it has no durable intent key.
    """

    if ownership_guard is not None:
        ownership_guard()
    if evolution_client is None:
        from app.services.evolution import EvolutionClient  # noqa: PLC0415

        with EvolutionClient() as client:
            sent = _send_agent_reply(client, outcome.instance, outcome.telefone, response)
    else:
        sent = _send_agent_reply(evolution_client, outcome.instance, outcome.telefone, response)
    if sent != "aceito":
        return
    if ownership_guard is not None:
        ownership_guard()
    session: Session = session_factory()
    try:
        _scope_agent_session(session, outcome)
        conv = session.get(Conversation, outcome.conversation_id)
        if conv is not None:
            session.add(
                Message(
                    igreja_id=conv.igreja_id,
                    conversation_id=conv.id,
                    direcao="out",
                    autor="ia",
                    texto=response,
                )
            )
            conv.ultima_mensagem = response
            session.commit()
    finally:
        session.close()


def run_agent_for_message(
    session_factory: Any,
    outcome: IngestionOutcome,
    ownership_guard: ClaimGuard | None = None,
    *,
    evolution_client: Any | None = None,
) -> AgentRunDisposition:
    """Drive the orchestrator for one persisted inbound message and reply.

    The orchestrator produces a single reply; we send it through the official
    number and persist the outbound message. Handoff suppresses the auto reply.
    A durable reservation and session advisory lock are acquired before calling
    the orchestrator because its tools may mutate tenant state.  An unresolved
    execution is quarantined rather than run a second time.
    """
    from app.agent.runtime import process_inbound_message  # noqa: PLC0415

    if outcome.conversation_id is None:
        return AgentRunDisposition.COMPLETED

    provider_message_id = _agent_reply_idempotency_key(outcome)
    if provider_message_id is None:
        # Compatibility path for out-of-tree callers that predate durable queue
        # claims.  QueueWorker always reaches the durable path below.
        if ownership_guard is not None:
            ownership_guard()
        session: Session = session_factory()
        try:
            if outcome.igreja_id is not None:
                _scope_agent_session(session, outcome)
                log_if_not_scoped(session, source="worker_agent")
            result = process_inbound_message(
                session,
                conversation_id=outcome.conversation_id,
                texto=outcome.texto,
            )
        finally:
            session.close()
        if result.handled and not result.suppressed and result.response:
            _run_agent_legacy(
                session_factory,
                outcome,
                result.response,
                ownership_guard,
                evolution_client=evolution_client,
            )
        return AgentRunDisposition.COMPLETED

    if ownership_guard is not None:
        ownership_guard()

    # Commit the durable row before acquiring the execution lease.  A crash in
    # this gap leaves ``ia_reservada`` and a recovered owner may safely start
    # the agent.  The unique outbound provider id is the stable claim key.
    intent = _reserve_agent_reply_intent(session_factory, outcome)
    if intent is None:
        return AgentRunDisposition.COMPLETED

    execution_lease = _AgentExecutionLease(
        session_factory,
        outcome,
        provider_message_id,
    )
    if not execution_lease.acquire():
        return AgentRunDisposition.IN_FLIGHT

    try:
        # Reload after acquiring the cross-process lease.  A worker that sees
        # ``ia_executando`` only after the prior process died cannot prove
        # whether mutable tools ran, so it quarantines instead of rerunning.
        intent = _load_agent_reply_intent(session_factory, outcome)
        if intent is None:
            return AgentRunDisposition.COMPLETED
        if intent.state == _AGENT_REPLY_EXECUTING:
            _quarantine_agent_execution(session_factory, outcome, intent)
            return AgentRunDisposition.COMPLETED

        if intent.state == _AGENT_REPLY_RESERVED:
            if not _transition_agent_reply_intent(
                session_factory,
                outcome,
                intent,
                expected=_AGENT_REPLY_RESERVED,
                target=_AGENT_REPLY_EXECUTING,
                ownership_guard=ownership_guard,
            ):
                intent = _load_agent_reply_intent(session_factory, outcome)
            else:
                try:
                    # Immediate pre-effect check.  If it fails, no agent/tool
                    # call happened and a recovered owner may resume the same
                    # persisted reservation.
                    if ownership_guard is not None:
                        ownership_guard()
                except ClaimOwnershipLost:
                    _release_agent_execution_reservation(
                        session_factory,
                        outcome,
                        intent,
                    )
                    raise

                session: Session = session_factory()
                try:
                    # Fase 0 (#10b): RLS por igreja também no caminho do agente
                    # — é aqui que tools, retrieval da KB e memória leem/escrevem
                    # dados do tenant.
                    _scope_agent_session(session, outcome)
                    log_if_not_scoped(session, source="worker_agent")
                    result = process_inbound_message(
                        session,
                        conversation_id=outcome.conversation_id,
                        texto=outcome.texto,
                    )
                except BaseException:
                    # A process failure after ``ia_executando`` may have crossed
                    # a non-transactional tool boundary.  Do not re-run it.
                    _quarantine_agent_execution(session_factory, outcome, intent)
                    raise
                finally:
                    session.close()

                try:
                    if ownership_guard is not None:
                        ownership_guard()
                except ClaimOwnershipLost:
                    _quarantine_agent_execution(session_factory, outcome, intent)
                    raise

                if not result.handled or result.suppressed or not result.response:
                    _transition_agent_reply_intent(
                        session_factory,
                        outcome,
                        intent,
                        expected=_AGENT_REPLY_EXECUTING,
                        target=_AGENT_REPLY_NO_RESPONSE,
                    )
                    return AgentRunDisposition.COMPLETED

                try:
                    intent = _prepare_agent_reply_intent(
                        session_factory,
                        outcome,
                        result.response,
                    )
                except Exception:
                    _quarantine_agent_execution(session_factory, outcome, intent)
                    raise
    finally:
        execution_lease.close()

    if intent is not None:
        _deliver_agent_reply_intent(
            session_factory,
            outcome,
            intent,
            ownership_guard,
            evolution_client=evolution_client,
        )
    return AgentRunDisposition.COMPLETED


# ---------------------------------------------------------------------------
# Media resolver (Etapa 2): Evolution download -> Supabase Storage upload
# ---------------------------------------------------------------------------
def _key_from(parsed: ParsedMessage) -> dict[str, Any]:
    """Reconstruct the Evolution message key used to fetch the media bytes.

    Only 1:1 chats are captured (groups are skipped at parse time), so the
    remoteJid is always the contact's `@s.whatsapp.net` JID.
    """
    return {
        "id": parsed.provider_message_id,
        "remoteJid": f"{parsed.telefone_raw}@s.whatsapp.net",
        "fromMe": parsed.from_me,
    }


def resolve_media_via_evolution(
    parsed: ParsedMessage,
    igreja_id: Any,
    conversation_id: Any,
    *,
    evolution_client: Any | None = None,
) -> Any:
    """Real media resolver: pull bytes from Evolution, upload to Storage.

    Imports are deferred so ingestion-only tests don't need the storage/HTTP
    stack. Returns a StoredMedia (pointer) or raises (the worker degrades).
    """
    import base64  # noqa: PLC0415

    from app.services.evolution import EvolutionClient  # noqa: PLC0415
    from app.services.storage import SupabaseStorage  # noqa: PLC0415

    if evolution_client is None:
        with EvolutionClient() as client:
            base64_data, mimetype = client.get_media_base64(
                parsed.instance,
                _key_from(parsed),
            )
    else:
        # Reuse the worker-owned HTTP pool instead of reconnecting for every
        # media event.
        base64_data, mimetype = evolution_client.get_media_base64(
            parsed.instance,
            _key_from(parsed),
        )
    raw = base64.b64decode(base64_data)
    return SupabaseStorage().upload(
        igreja_id,
        conversation_id,
        raw,
        mimetype or parsed.media_mime,
        parsed.media_nome,
        object_id=parsed.provider_message_id,
    )


# ---------------------------------------------------------------------------
# Redis client + entrypoint
# ---------------------------------------------------------------------------
def _build_redis() -> Any:
    """Build a Redis client from REDIS_URL (imported lazily)."""
    import redis  # lazy import so the package is optional for unit tests

    settings = get_settings()
    return redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
        max_connections=REDIS_MAX_CONNECTIONS,
    )


def main() -> None:  # pragma: no cover - process entrypoint
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    from app.services.evolution import EvolutionClient  # noqa: PLC0415

    # One client per worker process keeps TCP/TLS connections warm across
    # messages and is closed deterministically on graceful shutdown or error.
    with EvolutionClient() as evolution_client:
        worker = QueueWorker(
            agent_runner=partial(
                run_agent_for_message,
                evolution_client=evolution_client,
            ),
            media_resolver=partial(
                resolve_media_via_evolution,
                evolution_client=evolution_client,
            ),
        )
        signal.signal(signal.SIGTERM, worker.stop)
        signal.signal(signal.SIGINT, worker.stop)
        worker.run()


if __name__ == "__main__":  # pragma: no cover
    main()
