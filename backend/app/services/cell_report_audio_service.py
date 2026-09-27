"""Durable V1b audio anchors, bounded I/O, and retention maintenance.

The inbound anchor is recorded with its real ``Message``. Every media,
storage, and model boundary runs only after that transaction closes; later
local transitions retain the anchor for idempotent cleanup and replay fences.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from threading import Event, Thread
from typing import Any

from sqlalchemy import String, and_, cast, func, inspect, literal, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    AgentActionProposal,
    CellReportAiDailyBudget,
    CellReportAiReservation,
    CellReportAudioConsentEvent,
    CellReportAudioInput,
    CellReportAudioNotice,
    CellReportAudioReservation,
    CellReportDraft,
    Celula,
    CelulaReuniao,
    ConsentRecord,
    Conversation,
    LlmCredential,
    Message,
    Pessoa,
    WhatsappConnection,
)
from app.db.rls_observability import require_tenant_scope
from app.db.tenant_session import mark_cross_tenant, mark_tenant_scoped
from app.config import get_settings
from app.services.cell_report_audio import (
    AudioConsentCommand,
    CELL_REPORT_AUDIO_CONSENT_VERSION,
    canonical_audio_mime,
    cell_report_audio_enabled_from_environment,
    parse_audio_consent_command,
)


_UTC = dt.timezone.utc
_AUDIO_EXTENSION_BY_MIME: dict[str, str] = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "mp4",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
}
_AUDIO_INPUT_TTL = dt.timedelta(hours=24)
_MAX_PROVIDER_MESSAGE_ID_BYTES = 512
_AUDIO_LEASE_SECONDS = 180
_AUDIO_TRANSCRIPTION_MICROUSD_PER_MINUTE = 6_000
_AUDIO_REPORT_LIMIT_MICROUSD = 100_000
_AUDIO_DAILY_LIMIT_MICROUSD = 2_000_000
_AUDIO_COST_VERSION = "v1"
_AUDIO_OUTPUT_PREFIX = "agent-reply:v1b-audio:"
logger = logging.getLogger("pastorai.cell_report_audio")
AUDIO_CONSENT_NOTICE_TEXT = (
    "A OpenAI da igreja transcreve o áudio para preparar o relatório. "
    "No nosso sistema, áudio e transcrição ficam por até 24 horas; "
    "o relatório confirmado permanece. "
    "Responda ACEITO AUDIO para permitir ou PARAR AUDIO para revogar."
)


class CellReportAudioServiceError(ValueError):
    """Fail-closed local input rejection without fetching media."""


class _AudioClaimBusy(RuntimeError):
    """A short durable lock is held by another valid V1b transition."""


class _AudioClaimDeadlineExceeded(CellReportAudioServiceError):
    """The durable audio lease ended while only a local lock was contested."""


class _AudioStageDeferred:
    """Private sentinel: retry only the local stage after a short lock wait."""


_AUDIO_STAGE_DEFERRED = _AudioStageDeferred()


@dataclass(frozen=True, slots=True)
class AudioInputEnqueueResult:
    input_id: uuid.UUID
    state: str
    created: bool


@dataclass(frozen=True, slots=True)
class AudioConsentResult:
    """A durable command result without an automatic confirmation reply."""

    handled: bool
    command: AudioConsentCommand | None
    event_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class AudioInputClaim:
    """Committed ownership of one audio job, without any live ORM row."""

    igreja_id: uuid.UUID
    input_id: uuid.UUID
    conversation_id: uuid.UUID
    pessoa_id: uuid.UUID
    inbound_message_id: uuid.UUID
    provider_message_id: str
    instance: str
    phone: str
    declared_mime: str
    provider_message_sha256: str
    lease_token: uuid.UUID
    lease_until: dt.datetime
    credential_provider: str = field(repr=False)
    credential_key_encrypted: str = field(repr=False)
    credential_model: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AudioDispatchResult:
    claimed: int
    completed: int


@dataclass(frozen=True, slots=True)
class AudioBudgetReservation:
    reservation_id: uuid.UUID
    estimated_microusd: int


@dataclass(frozen=True, slots=True)
class _AudioExtractionPlan:
    """A committed V1a extraction reservation awaiting one bounded LLM call."""

    claim: AudioInputClaim
    draft_id: uuid.UUID
    draft_revision: int
    projection: dict[str, str]
    reservation_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class _AudioClaimAttempt:
    claim: AudioInputClaim | None
    exhausted: bool
    candidate_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class _AudioHandoffRecoveryAttempt:
    """One expired, post-I/O claim that needs only a durable human fence."""

    handled: bool
    exhausted: bool
    candidate_id: uuid.UUID | None = None


def _all_scalars(result: object) -> list[object]:
    """Keep unit fakes narrow without weakening the production query shape."""

    scalars = getattr(result, "scalars", None)
    if callable(scalars):
        return list(scalars().all())
    scalar_one_or_none = getattr(result, "scalar_one_or_none", None)
    if callable(scalar_one_or_none):
        one = scalar_one_or_none()
        return [] if one is None else [one]
    return []


def _required_uuid(value: object, *, field: str) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        raise CellReportAudioServiceError(f"{field} inválido")
    return value


def _utc_now(value: object | None) -> dt.datetime:
    current = dt.datetime.now(_UTC) if value is None else value
    if type(current) is not dt.datetime or current.tzinfo is None:
        raise CellReportAudioServiceError("horário inválido")
    try:
        return current.astimezone(_UTC)
    except (OverflowError, ValueError):
        raise CellReportAudioServiceError("horário inválido") from None


def _provider_digest(value: object) -> str:
    if type(value) is not str:
        raise CellReportAudioServiceError("mensagem de áudio inválida")
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > _MAX_PROVIDER_MESSAGE_ID_BYTES:
        raise CellReportAudioServiceError("mensagem de áudio inválida")
    return hashlib.sha256(encoded).hexdigest()


def _current_lgpd_acceptance(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    now: dt.datetime,
) -> ConsentRecord | None:
    """Return one current, unambiguous LGPD acceptance for audio authorization.

    Audio is an additional, revocable consent.  It never revives after a later
    global withdrawal or re-acceptance because its explicit event must follow
    this exact latest LGPD record.
    """

    current_term = getattr(get_settings(), "agent_term_version", None)
    if type(current_term) is not str or not current_term:
        return None
    pessoa = session.execute(
        select(Pessoa).where(
            Pessoa.igreja_id == igreja_id,
            Pessoa.id == pessoa_id,
        )
    ).scalar_one_or_none()
    if (
        not isinstance(pessoa, Pessoa)
        or bool(getattr(pessoa, "optout", False))
        or getattr(pessoa, "arquivada_em", None) is not None
        or bool(getattr(pessoa, "sem_interesse", False))
    ):
        return None
    rows = _all_scalars(
        session.execute(
            select(ConsentRecord)
            .where(
                ConsentRecord.igreja_id == igreja_id,
                ConsentRecord.pessoa_id == pessoa_id,
            )
            .order_by(ConsentRecord.aceite_em.desc().nullslast(), ConsentRecord.id.desc())
            .limit(2)
        )
    )
    if not rows or not isinstance(rows[0], ConsentRecord):
        return None
    latest = rows[0]
    accepted_at = getattr(latest, "aceite_em", None)
    if type(accepted_at) is not dt.datetime or accepted_at.tzinfo is None:
        return None
    try:
        accepted_at = accepted_at.astimezone(_UTC)
    except (OverflowError, ValueError):
        return None
    if accepted_at > now or getattr(latest, "termo_versao", None) != current_term:
        return None
    if (
        len(rows) > 1
        and isinstance(rows[1], ConsentRecord)
        and getattr(rows[1], "aceite_em", None) == latest.aceite_em
    ):
        return None
    return latest


def _active_audio_consent(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> CellReportAudioConsentEvent | None:
    """Return one explicit acceptance bound to the latest LGPD consent."""

    current_time = _utc_now(now)
    rows = _all_scalars(
        session.execute(
            select(CellReportAudioConsentEvent)
            .where(
                CellReportAudioConsentEvent.igreja_id == igreja_id,
                CellReportAudioConsentEvent.pessoa_id == pessoa_id,
            )
            .order_by(
                CellReportAudioConsentEvent.occurred_at.desc(),
                CellReportAudioConsentEvent.id.desc(),
            )
            .limit(2)
        )
    )
    if not rows:
        return None
    current = rows[0]
    if not isinstance(current, CellReportAudioConsentEvent):
        return None
    if (
        len(rows) > 1
        and isinstance(rows[1], CellReportAudioConsentEvent)
        and rows[1].occurred_at == current.occurred_at
    ):
        return None
    if (
        current.command != AudioConsentCommand.ACCEPT.value
        or current.version != CELL_REPORT_AUDIO_CONSENT_VERSION
    ):
        return None
    accepted_at = getattr(current, "occurred_at", None)
    if type(accepted_at) is not dt.datetime or accepted_at.tzinfo is None:
        return None
    try:
        accepted_at = accepted_at.astimezone(_UTC)
    except (OverflowError, ValueError):
        return None
    lgpd = _current_lgpd_acceptance(
        session,
        igreja_id=igreja_id,
        pessoa_id=pessoa_id,
        now=current_time,
    )
    lgpd_at = getattr(lgpd, "aceite_em", None)
    if (
        lgpd is None
        or type(lgpd_at) is not dt.datetime
        or lgpd_at.tzinfo is None
        or accepted_at <= lgpd_at.astimezone(_UTC)
    ):
        return None
    return current


def audio_capture_scope_allows(
    session: Session,
    *,
    igreja_id: object,
    conversation_id: object,
    inbound_message_id: object,
    now: object | None = None,
) -> bool:
    """Allow V1b capture only for one server-resolved eligible report scope.

    This preflight is read-only: it does not reserve a meeting, start an LLM
    turn, or infer authority from the audio job itself.  Any ambiguity preserves
    the legacy media path.
    """

    tenant = _required_uuid(igreja_id, field="igreja")
    conversation = _required_uuid(conversation_id, field="conversa")
    inbound = _required_uuid(inbound_message_id, field="mensagem")
    current_time = _utc_now(now)
    try:
        from app.services.cell_report_v1a_service import _eligible_meeting
        from app.services.whatsapp_privilege import (
            PrivilegeContext,
            resolve_whatsapp_privilege_context,
        )

        context = resolve_whatsapp_privilege_context(
            session,
            igreja_id=tenant,
            conversation_id=conversation,
            inbound_message_id=inbound,
        )
        if type(context) is not PrivilegeContext:
            return False
        return _eligible_meeting(
            session,
            context=context,
            now=current_time,
            lock=False,
        ) is not None
    except Exception:  # fail closed: inbox audio remains on the legacy path.
        return False


def audio_schema_available(session: Session) -> bool:
    """Return whether the additive V1b table exists without raising a gate.

    This is intentionally called only after the V1b environment gate.  A
    listed deployment that has not applied the additive migration keeps the
    established generic media path instead of touching a missing relation.
    """

    get_bind = getattr(session, "get_bind", None)
    if get_bind is None:
        return False
    try:
        bind = get_bind()
        if bind.dialect.name == "postgresql":
            return bool(
                session.execute(
                    text(
                        "select pg_catalog.to_regclass("
                        "'public.cell_report_audio_inputs') is not null"
                    )
                ).scalar_one()
            )
        return bool(inspect(bind).has_table("cell_report_audio_inputs"))
    except Exception:  # schema discovery is a fail-closed compatibility gate.
        return False


def find_audio_input_by_provider(
    session: Session,
    *,
    igreja_id: object,
    provider_message_id: object,
) -> CellReportAudioInput | None:
    """Return the durable V1b tombstone for one trusted provider event.

    The digest, rather than the mutable ``Message`` row, survives normal
    deletion long enough to prevent the same provider audio from creating a
    new inbound, storage path, or paid job on replay.
    """

    tenant = _required_uuid(igreja_id, field="igreja")
    digest = _provider_digest(provider_message_id)
    row = session.execute(
        select(CellReportAudioInput).where(
            CellReportAudioInput.igreja_id == tenant,
            CellReportAudioInput.provider_message_sha256 == digest,
        )
    ).scalar_one_or_none()
    return row if isinstance(row, CellReportAudioInput) else None


def audio_notice_required_for_inbound(
    session: Session,
    *,
    igreja_id: object,
    pessoa_id: object,
    conversation_id: object,
    inbound_message_id: object,
) -> bool:
    """Recognize only a live, awaiting V1b audio anchor for notice staging."""

    tenant = _required_uuid(igreja_id, field="igreja")
    pessoa = _required_uuid(pessoa_id, field="pessoa")
    conversation = _required_uuid(conversation_id, field="conversa")
    inbound = _required_uuid(inbound_message_id, field="mensagem")
    return (
        session.execute(
            select(CellReportAudioInput.id).where(
                CellReportAudioInput.igreja_id == tenant,
                CellReportAudioInput.pessoa_id == pessoa,
                CellReportAudioInput.conversation_id == conversation,
                CellReportAudioInput.inbound_message_id == inbound,
                CellReportAudioInput.live_message_id == inbound,
                CellReportAudioInput.state == "aguardando_aceite",
            )
        ).scalar_one_or_none()
        is not None
    )


def enqueue_audio_input_after_inbound(
    session: Session,
    *,
    igreja_id: object,
    conversation_id: object,
    pessoa_id: object,
    inbound_message_id: object,
    provider_message_id: object,
    declared_mime: object,
    now: object | None = None,
) -> AudioInputEnqueueResult:
    """Record one immutable cleanup anchor for a trusted, persisted inbound.

    The caller has already validated the official instance and persisted the
    inbound ``Message`` in this same transaction.  This function neither
    commits nor performs I/O, preserving atomic message/input idempotency.
    """

    tenant = _required_uuid(igreja_id, field="igreja")
    conversation = _required_uuid(conversation_id, field="conversa")
    pessoa = _required_uuid(pessoa_id, field="pessoa")
    inbound = _required_uuid(inbound_message_id, field="mensagem")
    received_at = _utc_now(now)
    digest = _provider_digest(provider_message_id)
    canonical_mime = canonical_audio_mime(declared_mime)

    existing = session.execute(
        select(CellReportAudioInput).where(
            CellReportAudioInput.igreja_id == tenant,
            or_(
                CellReportAudioInput.inbound_message_id == inbound,
                CellReportAudioInput.provider_message_sha256 == digest,
            ),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return AudioInputEnqueueResult(
            input_id=existing.id,
            state=existing.state,
            created=False,
        )

    accepted = _active_audio_consent(
        session,
        igreja_id=tenant,
        pessoa_id=pessoa,
    )
    input_id = uuid.uuid4()
    accepted_input = canonical_mime is not None
    if canonical_mime is not None:
        # Storage owns the one public implementation of this private key.  The
        # durable row records the exact same path before any upload starts.
        from app.services.storage import cell_report_audio_storage_path

        storage_path = cell_report_audio_storage_path(
            tenant,
            digest,
            canonical_mime,
        )
    else:
        # Invalid media is terminal and never reaches Storage.  Retain only a
        # deterministic private cleanup anchor; no MIME extension is inferred.
        storage_path = f"{tenant}/cell-report-audio/{digest}.invalid"
    row = CellReportAudioInput(
        id=input_id,
        igreja_id=tenant,
        conversation_id=conversation,
        pessoa_id=pessoa,
        inbound_message_id=inbound,
        live_conversation_id=conversation,
        live_pessoa_id=pessoa,
        live_message_id=inbound,
        provider_message_sha256=digest,
        storage_path=storage_path,
        declared_mime=canonical_mime,
        consent_version=accepted.version if accepted is not None else None,
        consent_event_id=accepted.id if accepted is not None else None,
        state=(
            "pendente"
            if accepted_input and accepted is not None
            else ("aguardando_aceite" if accepted_input else "cancelada")
        ),
        transcription_attempts=0,
        purge_state="ativa",
        purge_attempts=0,
        received_at=received_at,
        expires_at=received_at + _AUDIO_INPUT_TTL,
        updated_at=received_at,
        terminal_reason=None if accepted_input else "mime_invalido",
        terminal_at=None if accepted_input else received_at,
    )
    session.add(row)
    return AudioInputEnqueueResult(
        input_id=input_id,
        state=row.state,
        created=True,
    )


def prepare_audio_consent_notice(
    session: Session,
    *,
    igreja_id: object,
    pessoa_id: object,
    conversation_id: object,
    inbound_message_id: object,
    notice_message_id: object,
    now: object | None = None,
) -> CellReportAudioNotice | None:
    """Bind a one-time notice to an outbound ledger row before transport."""

    tenant = _required_uuid(igreja_id, field="igreja")
    pessoa = _required_uuid(pessoa_id, field="pessoa")
    conversation = _required_uuid(conversation_id, field="conversa")
    inbound = _required_uuid(inbound_message_id, field="mensagem")
    notice_message = _required_uuid(notice_message_id, field="aviso")
    occurred_at = _utc_now(now)

    existing = session.execute(
        select(CellReportAudioNotice)
        .where(
            CellReportAudioNotice.igreja_id == tenant,
            CellReportAudioNotice.notice_message_id == notice_message,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    audio_input = session.execute(
        select(CellReportAudioInput)
        .where(
            CellReportAudioInput.igreja_id == tenant,
            CellReportAudioInput.pessoa_id == pessoa,
            CellReportAudioInput.conversation_id == conversation,
            CellReportAudioInput.inbound_message_id == inbound,
            CellReportAudioInput.live_message_id == inbound,
            CellReportAudioInput.state == "aguardando_aceite",
        )
        .with_for_update()
    ).scalar_one_or_none()
    if audio_input is None or _active_audio_consent(
        session,
        igreja_id=tenant,
        pessoa_id=pessoa,
    ) is not None:
        return None

    notice = CellReportAudioNotice(
        id=uuid.uuid4(),
        igreja_id=tenant,
        pessoa_id=pessoa,
        conversation_id=conversation,
        notice_message_id=notice_message,
        version=CELL_REPORT_AUDIO_CONSENT_VERSION,
        state="preparado",
        created_at=occurred_at,
    )
    session.add(notice)
    return notice


def audio_notice_still_pending(
    session: Session,
    *,
    igreja_id: object,
    pessoa_id: object,
    conversation_id: object,
    notice_message_id: object,
) -> bool:
    """Revalidate the exact pending notice immediately before transport."""

    tenant = _required_uuid(igreja_id, field="igreja")
    pessoa = _required_uuid(pessoa_id, field="pessoa")
    conversation = _required_uuid(conversation_id, field="conversa")
    notice_message = _required_uuid(notice_message_id, field="aviso")
    if not cell_report_audio_enabled_from_environment(tenant):
        return False
    return (
        session.execute(
            select(CellReportAudioNotice.id).where(
                CellReportAudioNotice.igreja_id == tenant,
                CellReportAudioNotice.pessoa_id == pessoa,
                CellReportAudioNotice.conversation_id == conversation,
                CellReportAudioNotice.notice_message_id == notice_message,
                CellReportAudioNotice.version == CELL_REPORT_AUDIO_CONSENT_VERSION,
                CellReportAudioNotice.state == "preparado",
            )
        ).scalar_one_or_none()
        is not None
    )


def audio_summary_still_authorized(
    session: Session,
    *,
    igreja_id: object,
    conversation_id: object,
    pessoa_id: object,
    audio_input_id: object,
    now: object | None = None,
) -> bool:
    """Recheck the V1b-specific source before a transcript-derived reply.

    S3 already rechecks the privilege context and the V1a proposal.  This
    narrow additional fence keeps an audio-derived summary from crossing the
    outbound boundary after audio consent or the cumulative V1b release gate
    was withdrawn.
    """

    tenant = _required_uuid(igreja_id, field="igreja")
    conversation = _required_uuid(conversation_id, field="conversa")
    pessoa = _required_uuid(pessoa_id, field="pessoa")
    input_id = _required_uuid(audio_input_id, field="áudio")
    if not cell_report_audio_enabled_from_environment(tenant):
        return False
    current = _utc_now(now)
    row = session.execute(
        select(CellReportAudioInput).where(
            CellReportAudioInput.igreja_id == tenant,
            CellReportAudioInput.id == input_id,
            CellReportAudioInput.conversation_id == conversation,
            CellReportAudioInput.pessoa_id == pessoa,
            CellReportAudioInput.state == "transcrita",
            CellReportAudioInput.purge_state == "ativa",
            CellReportAudioInput.expires_at > current,
        )
    ).scalar_one_or_none()
    if not isinstance(row, CellReportAudioInput):
        return False
    consent = _active_audio_consent(
        session,
        igreja_id=tenant,
        pessoa_id=pessoa,
        now=current,
    )
    return (
        consent is not None
        and consent.id == row.consent_event_id
        and consent.version == row.consent_version
    )


def mark_audio_consent_notice_delivered(
    session: Session,
    *,
    igreja_id: object,
    conversation_id: object,
    notice_message_id: object,
    now: object | None = None,
) -> bool:
    """Promote a notice only after the canonical outbound ledger confirms it."""

    tenant = _required_uuid(igreja_id, field="igreja")
    conversation = _required_uuid(conversation_id, field="conversa")
    notice_message = _required_uuid(notice_message_id, field="aviso")
    occurred_at = _utc_now(now)
    notice = session.execute(
        select(CellReportAudioNotice)
        .where(
            CellReportAudioNotice.igreja_id == tenant,
            CellReportAudioNotice.conversation_id == conversation,
            CellReportAudioNotice.notice_message_id == notice_message,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if notice is None:
        return False
    if notice.state == "entregue":
        return True
    if notice.state != "preparado":
        return False
    notice.state = "entregue"
    notice.delivered_at = occurred_at
    return True


def invalidate_audio_consent_notice(
    session: Session,
    *,
    igreja_id: object,
    conversation_id: object,
    notice_message_id: object,
    now: object | None = None,
) -> bool:
    """Cancel an unsent notice, keeping a failed delivery from enabling consent."""

    tenant = _required_uuid(igreja_id, field="igreja")
    conversation = _required_uuid(conversation_id, field="conversa")
    notice_message = _required_uuid(notice_message_id, field="aviso")
    occurred_at = _utc_now(now)
    notice = session.execute(
        select(CellReportAudioNotice)
        .where(
            CellReportAudioNotice.igreja_id == tenant,
            CellReportAudioNotice.conversation_id == conversation,
            CellReportAudioNotice.notice_message_id == notice_message,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if notice is None or notice.state != "preparado":
        return False
    notice.state = "cancelado"
    notice.terminal_at = occurred_at
    return True


def record_audio_consent_command(
    session: Session,
    *,
    igreja_id: object,
    pessoa_id: object,
    conversation_id: object,
    source_message_id: object,
    command: object,
    now: object | None = None,
) -> AudioConsentResult:
    """Append one explicit V1b choice from its persisted inbound anchor.

    Acceptance is valid only when its own inbound text says ``ACEITO AUDIO``
    and was stored strictly after a delivered V1b notice in the same
    conversation.  A queued old message therefore cannot become consent only
    because it was processed late.
    """

    tenant = _required_uuid(igreja_id, field="igreja")
    pessoa = _required_uuid(pessoa_id, field="pessoa")
    conversation = _required_uuid(conversation_id, field="conversa")
    source = _required_uuid(source_message_id, field="mensagem")
    if type(command) is not AudioConsentCommand:
        return AudioConsentResult(False, None, None)
    current_time = _utc_now(now)

    # Keep the durable mutation order consistent with handoff and report work:
    # conversation, person, then the inbound anchor.
    live_conversation = session.execute(
        select(Conversation)
        .where(
            Conversation.igreja_id == tenant,
            Conversation.id == conversation,
            Conversation.pessoa_id == pessoa,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if not isinstance(live_conversation, Conversation):
        return AudioConsentResult(False, command, None)
    live_pessoa = session.execute(
        select(Pessoa)
        .where(Pessoa.igreja_id == tenant, Pessoa.id == pessoa)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if not isinstance(live_pessoa, Pessoa):
        return AudioConsentResult(False, command, None)
    source_message = session.execute(
        select(Message)
        .where(
            Message.id == source,
            Message.igreja_id == tenant,
            Message.conversation_id == conversation,
            Message.direcao == "in",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if not isinstance(source_message, Message):
        return AudioConsentResult(False, command, None)
    if source_message.tipo != "texto":
        return AudioConsentResult(False, command, None)
    if parse_audio_consent_command(source_message.texto) is not command:
        return AudioConsentResult(False, command, None)
    source_created_at = getattr(source_message, "criado_em", None)
    if type(source_created_at) is not dt.datetime or source_created_at.tzinfo is None:
        return AudioConsentResult(False, command, None)
    try:
        occurred_at = source_created_at.astimezone(_UTC)
    except (OverflowError, ValueError):
        return AudioConsentResult(False, command, None)
    if occurred_at > current_time:
        return AudioConsentResult(False, command, None)

    existing = session.execute(
        select(CellReportAudioConsentEvent).where(
            CellReportAudioConsentEvent.igreja_id == tenant,
            CellReportAudioConsentEvent.source_message_id == source,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing_command = (
            AudioConsentCommand(existing.command)
            if existing.command in {item.value for item in AudioConsentCommand}
            else None
        )
        if existing_command is AudioConsentCommand.REVOKE:
            cancel_audio_inputs_for_conversation(
                session,
                igreja_id=tenant,
                conversation_id=conversation,
                reason="consentimento_audio_revogado",
                now=occurred_at,
            )
        return AudioConsentResult(True, existing_command, existing.id)

    notice_id: uuid.UUID | None = None
    if command is AudioConsentCommand.ACCEPT:
        lgpd = _current_lgpd_acceptance(
            session,
            igreja_id=tenant,
            pessoa_id=pessoa,
            now=occurred_at,
        )
        lgpd_at = getattr(lgpd, "aceite_em", None)
        if (
            lgpd is None
            or type(lgpd_at) is not dt.datetime
            or lgpd_at.tzinfo is None
            or lgpd_at.astimezone(_UTC) >= occurred_at
        ):
            return AudioConsentResult(False, command, None)
        notices = _all_scalars(
            session.execute(
                select(CellReportAudioNotice)
                .where(
                    CellReportAudioNotice.igreja_id == tenant,
                    CellReportAudioNotice.pessoa_id == pessoa,
                    CellReportAudioNotice.conversation_id == conversation,
                    CellReportAudioNotice.version == CELL_REPORT_AUDIO_CONSENT_VERSION,
                    CellReportAudioNotice.state == "entregue",
                    CellReportAudioNotice.delivered_at < occurred_at,
                )
                .order_by(
                    CellReportAudioNotice.delivered_at.desc(),
                    CellReportAudioNotice.id.desc(),
                )
                .limit(2)
            )
        )
        if not notices or not isinstance(notices[0], CellReportAudioNotice):
            return AudioConsentResult(False, command, None)
        notice = notices[0]
        if (
            len(notices) > 1
            and isinstance(notices[1], CellReportAudioNotice)
            and notices[1].delivered_at == notice.delivered_at
        ):
            return AudioConsentResult(False, command, None)
        notice_id = notice.id

    event = CellReportAudioConsentEvent(
        id=uuid.uuid4(),
        igreja_id=tenant,
        pessoa_id=pessoa,
        conversation_id=conversation,
        source_message_id=source,
        notice_id=notice_id,
        command=command.value,
        version=CELL_REPORT_AUDIO_CONSENT_VERSION,
        occurred_at=occurred_at,
    )
    session.add(event)
    if command is AudioConsentCommand.REVOKE:
        cancel_audio_inputs_for_conversation(
            session,
            igreja_id=tenant,
            conversation_id=conversation,
            reason="consentimento_audio_revogado",
            now=occurred_at,
        )
        session.execute(
            update(CellReportAudioNotice)
            .where(
                CellReportAudioNotice.igreja_id == tenant,
                CellReportAudioNotice.pessoa_id == pessoa,
                CellReportAudioNotice.state == "preparado",
            )
            .values(state="cancelado", terminal_at=occurred_at)
        )
    return AudioConsentResult(True, command, event.id)


def _scoped(session: Session, igreja_id: uuid.UUID, source: str) -> None:
    mark_tenant_scoped(session, igreja_id, source=source)
    require_tenant_scope(session, expected_igreja_id=igreja_id, source=source)


def _discover_audio_tenants(
    session_factory: Callable[[], Session],
) -> tuple[uuid.UUID, ...]:
    """Discover durable work only from the explicit worker maintenance edge."""

    session = session_factory()
    try:
        mark_cross_tenant(session, source="cell_report_audio_dispatch_discovery")
        if not audio_schema_available(session):
            return ()
        values = session.execute(
            select(CellReportAudioInput.igreja_id).distinct()
        ).scalars()
        return tuple(sorted((row for row in values if type(row) is uuid.UUID), key=str))
    except Exception:
        session.rollback()
        return ()
    finally:
        session.close()


def _terminalize_audio_input(
    row: CellReportAudioInput,
    *,
    now: dt.datetime,
    reason: str,
    ambiguous: bool = False,
    scrub_private: bool = False,
    expire_for_purge: bool = False,
) -> None:
    row.state = "ambigua" if ambiguous else "cancelada"
    row.lease_token = None
    row.lease_until = None
    row.terminal_reason = reason
    row.terminal_at = now
    row.updated_at = now
    if scrub_private:
        # Keep the immutable provider digest and canonical storage path for
        # idempotency and physical cleanup.  Transcript content has no reason
        # to outlive a revocation, handoff, or terminal report decision.
        row.transcript_text = None
        row.transcript_sha256 = None
    if expire_for_purge:
        row.expires_at = _immediate_audio_expiry(row, now)
        row.purge_state = "ativa"


def _immediate_audio_expiry(
    row: CellReportAudioInput,
    now: dt.datetime,
) -> dt.datetime:
    """Make cleanup due without extending the immutable 24-hour window."""

    received_at = _utc_now(row.received_at)
    existing_expiry = _utc_now(row.expires_at)
    # The SQL check requires a strict interval. A same-timestamp terminal
    # transition remains eligible practically immediately without producing an
    # invalid ``expires_at == received_at`` row.
    earliest_valid = received_at + dt.timedelta(microseconds=1)
    return min(existing_expiry, max(earliest_valid, now))


def _cancel_audio_output_for_input(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    input_id: uuid.UUID,
    reason: str,
) -> None:
    """Cancel only an undelivered audio-derived reply and its S3 proposal.

    The caller already holds the conversation lock.  A confirmed receipt or
    official report is deliberately outside this fence.
    """

    from app.domain.agent_reply import (
        AGENT_REPLY_EXECUTING,
        AGENT_REPLY_IN_FLIGHT,
        AGENT_REPLY_PENDING,
        AGENT_REPLY_RESERVED,
        AGENT_REPLY_NO_RESPONSE,
    )

    output = session.execute(
        select(Message)
        .where(
            Message.igreja_id == igreja_id,
            Message.conversation_id == conversation_id,
            Message.provider_message_id == _audio_output_provider_id(input_id),
            Message.direcao == "out",
            Message.autor == "ia",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if output is None:
        return
    session.execute(
        update(AgentActionProposal)
        .where(
            AgentActionProposal.igreja_id == igreja_id,
            AgentActionProposal.conversation_id == conversation_id,
            AgentActionProposal.summary_message_id == output.id,
            AgentActionProposal.state.in_(("preparada", "pendente")),
        )
        .values(state="cancelada", terminal_reason=reason)
    )
    if output.agent_reply_state in {
        AGENT_REPLY_RESERVED,
        AGENT_REPLY_EXECUTING,
        AGENT_REPLY_PENDING,
        AGENT_REPLY_IN_FLIGHT,
    }:
        output.agent_reply_state = AGENT_REPLY_NO_RESPONSE
        output.texto = ""


def cancel_audio_inputs_for_conversation(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    reason: str,
    now: dt.datetime | None = None,
) -> int:
    """Purge private V1b content when a conversation becomes terminal.

    ``Conversation`` is locked by the handoff/opt-out caller.  This helper
    takes Pessoa before audio rows and leaves technical tombstones intact for
    replay suppression and physical-storage cleanup.
    """

    current = _utc_now(now)
    if not audio_schema_available(session):
        return 0
    pessoa_ids = tuple(
        sorted(
            {
                row
                for row in session.execute(
                    select(CellReportAudioInput.live_pessoa_id).where(
                        CellReportAudioInput.igreja_id == igreja_id,
                        CellReportAudioInput.conversation_id == conversation_id,
                        CellReportAudioInput.state.in_(
                            ("aguardando_aceite", "pendente", "processando", "transcrita")
                        ),
                    )
                ).scalars()
                if isinstance(row, uuid.UUID)
            },
            key=str,
        )
    )
    if pessoa_ids:
        tuple(
            session.execute(
                select(Pessoa)
                .where(Pessoa.igreja_id == igreja_id, Pessoa.id.in_(pessoa_ids))
                .order_by(Pessoa.id.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
            ).scalars()
        )
    rows = tuple(
        session.execute(
            select(CellReportAudioInput)
            .where(
                CellReportAudioInput.igreja_id == igreja_id,
                CellReportAudioInput.conversation_id == conversation_id,
                CellReportAudioInput.state.in_(
                    ("aguardando_aceite", "pendente", "processando", "transcrita")
                ),
            )
            .order_by(CellReportAudioInput.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalars()
    )
    if not rows:
        return 0
    for row in rows:
        _cancel_audio_output_for_input(
            session,
            igreja_id=igreja_id,
            conversation_id=conversation_id,
            input_id=row.id,
            reason=reason,
        )
        _terminalize_audio_input(
            row,
            now=current,
            reason=reason,
            ambiguous=row.state == "processando",
            scrub_private=True,
            expire_for_purge=True,
        )
    return len(rows)


def clear_audio_transcript_after_official_report(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    proposal_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> bool:
    """Drop every V1b transcript that contributed to one official report.

    A correction may be a later text inbound, so the executed proposal's source
    message is not necessarily the original audio anchor.  The committed audio
    reservation links each input to the meeting before transcription, which is
    the durable provenance even when the draft was created after reception.
    """

    if not audio_schema_available(session):
        return False
    proposal = session.execute(
        select(AgentActionProposal)
        .where(
            AgentActionProposal.igreja_id == igreja_id,
            AgentActionProposal.conversation_id == conversation_id,
            AgentActionProposal.id == proposal_id,
            AgentActionProposal.state == "executada",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if proposal is None:
        return False
    rows = tuple(
        session.execute(
            select(CellReportAudioInput)
            .join(
                CellReportAudioReservation,
                (CellReportAudioReservation.igreja_id == CellReportAudioInput.igreja_id)
                & (CellReportAudioReservation.audio_input_id == CellReportAudioInput.id),
            )
            .where(
                CellReportAudioInput.igreja_id == igreja_id,
                CellReportAudioInput.conversation_id == conversation_id,
                CellReportAudioInput.pessoa_id == proposal.actor_pessoa_id,
                CellReportAudioReservation.reuniao_id == proposal.target_id,
                CellReportAudioInput.state != "purgada",
            )
            .order_by(CellReportAudioInput.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalars()
    )
    if not rows:
        return False
    current = _utc_now(now)
    for row in rows:
        _cancel_audio_output_for_input(
            session,
            igreja_id=igreja_id,
            conversation_id=conversation_id,
            input_id=row.id,
            reason="relatorio_confirmado",
        )
        _terminalize_audio_input(
            row,
            now=current,
            reason="relatorio_confirmado",
            ambiguous=row.state == "processando",
            scrub_private=True,
            expire_for_purge=True,
        )
    return True


def _audio_claim_candidates(
    session_factory: Callable[[], Session],
    igreja_id: uuid.UUID,
    *,
    excluded_input_ids: tuple[uuid.UUID, ...],
) -> tuple[uuid.UUID, ...]:
    """Read candidate ids without an input lock, then revalidate under order."""

    session = session_factory()
    try:
        _scoped(session, igreja_id, "cell_report_audio_claim_candidates")
        statement = select(CellReportAudioInput.id).where(
            CellReportAudioInput.igreja_id == igreja_id,
            CellReportAudioInput.state == "pendente",
            CellReportAudioInput.purge_state == "ativa",
        )
        if excluded_input_ids:
            statement = statement.where(~CellReportAudioInput.id.in_(excluded_input_ids))
        return tuple(
            row
            for row in session.execute(
                statement.order_by(
                    CellReportAudioInput.received_at.asc(),
                    CellReportAudioInput.id.asc(),
                ).limit(1)
            ).scalars()
            if type(row) is uuid.UUID
        )
    finally:
        session.close()


def _recover_expired_audio_handoff(
    session_factory: Callable[[], Session],
    igreja_id: uuid.UUID,
    *,
    now: dt.datetime,
    excluded_input_ids: tuple[uuid.UUID, ...] = (),
) -> _AudioHandoffRecoveryAttempt:
    """Retry only the human fence of an expired post-I/O audio claim.

    A claim has already marked ``external_started_at`` before media or model
    I/O.  Once that boundary was crossed, recovery must never reset it to
    pending or invoke a provider again.  The surviving input row is enough to
    retry the local handoff after a short competing Conversation/Pessoa lock
    releases, even when deployment gates have since closed.
    """

    session = session_factory()
    try:
        _scoped(session, igreja_id, "cell_report_audio_handoff_candidates")
        statement = select(CellReportAudioInput.id).where(
            CellReportAudioInput.igreja_id == igreja_id,
            CellReportAudioInput.state == "processando",
            CellReportAudioInput.purge_state == "ativa",
            CellReportAudioInput.external_started_at.is_not(None),
            CellReportAudioInput.lease_until.is_not(None),
            CellReportAudioInput.lease_until <= now,
        )
        if excluded_input_ids:
            statement = statement.where(~CellReportAudioInput.id.in_(excluded_input_ids))
        input_id = session.execute(
            statement.order_by(
                CellReportAudioInput.lease_until.asc(),
                CellReportAudioInput.id.asc(),
            ).limit(1)
        ).scalar_one_or_none()
        session.commit()
    except Exception:
        session.rollback()
        return _AudioHandoffRecoveryAttempt(False, True)
    finally:
        session.close()
    if type(input_id) is not uuid.UUID:
        return _AudioHandoffRecoveryAttempt(False, True)

    session = session_factory()
    try:
        _scoped(session, igreja_id, "cell_report_audio_handoff_recovery")
        row = session.execute(
            select(CellReportAudioInput).where(
                CellReportAudioInput.igreja_id == igreja_id,
                CellReportAudioInput.id == input_id,
            )
        ).scalar_one_or_none()
        if (
            row is None
            or row.state != "processando"
            or row.purge_state != "ativa"
            or row.external_started_at is None
            or row.lease_until is None
            or row.lease_until > now
        ):
            session.commit()
            return _AudioHandoffRecoveryAttempt(False, False, input_id)

        conversation = None
        if row.live_conversation_id is not None:
            conversation = session.execute(
                select(Conversation)
                .where(
                    Conversation.igreja_id == igreja_id,
                    Conversation.id == row.live_conversation_id,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if conversation is None:
                exists = session.execute(
                    select(Conversation.id).where(
                        Conversation.igreja_id == igreja_id,
                        Conversation.id == row.live_conversation_id,
                    )
                ).scalar_one_or_none()
                if exists is not None:
                    session.commit()
                    return _AudioHandoffRecoveryAttempt(False, False, input_id)
        if row.live_pessoa_id is not None:
            pessoa = session.execute(
                select(Pessoa)
                .where(
                    Pessoa.igreja_id == igreja_id,
                    Pessoa.id == row.live_pessoa_id,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if pessoa is None:
                exists = session.execute(
                    select(Pessoa.id).where(
                        Pessoa.igreja_id == igreja_id,
                        Pessoa.id == row.live_pessoa_id,
                    )
                ).scalar_one_or_none()
                if exists is not None:
                    session.commit()
                    return _AudioHandoffRecoveryAttempt(False, False, input_id)
        locked = session.execute(
            select(CellReportAudioInput)
            .where(
                CellReportAudioInput.igreja_id == igreja_id,
                CellReportAudioInput.id == input_id,
                CellReportAudioInput.state == "processando",
                CellReportAudioInput.purge_state == "ativa",
                CellReportAudioInput.external_started_at.is_not(None),
                CellReportAudioInput.lease_until.is_not(None),
                CellReportAudioInput.lease_until <= now,
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if locked is None:
            session.commit()
            return _AudioHandoffRecoveryAttempt(False, False, input_id)
        if conversation is not None:
            from app.services.conversation_handoff import mark_conversation_for_handoff_locked

            mark_conversation_for_handoff_locked(session, conversation=conversation)
        _terminalize_audio_input(
            locked,
            now=now,
            reason="audio_handoff_pendente",
            scrub_private=True,
            expire_for_purge=True,
        )
        session.commit()
        return _AudioHandoffRecoveryAttempt(True, False, input_id)
    except Exception:
        session.rollback()
        return _AudioHandoffRecoveryAttempt(False, False, input_id)
    finally:
        session.close()


def recover_expired_audio_handoffs(
    session_factory: Callable[[], Session],
    *,
    now: dt.datetime | None = None,
    limit: int = 100,
) -> int:
    """Apply only delayed human fences before retention or feature gates.

    These rows already crossed a provider boundary.  This maintenance pass
    never starts media, storage, or model work, so deployment withdrawal cannot
    strand an expired claim after a competing Conversation or Pessoa lock.
    """

    if type(limit) is not int or isinstance(limit, bool) or limit <= 0:
        return 0
    current = _utc_now(now)
    recovered = 0
    remaining = limit
    for tenant in _discover_audio_tenants(session_factory):
        if remaining <= 0:
            break
        visited: list[uuid.UUID] = []
        while remaining > 0:
            attempt = _recover_expired_audio_handoff(
                session_factory,
                tenant,
                now=current,
                excluded_input_ids=tuple(visited),
            )
            if attempt.exhausted:
                break
            if attempt.candidate_id is not None:
                visited.append(attempt.candidate_id)
            if attempt.handled:
                recovered += 1
                remaining -= 1
    return recovered


def _claim_next_audio_input(
    session_factory: Callable[[], Session],
    igreja_id: uuid.UUID,
    *,
    now: dt.datetime,
    excluded_input_ids: tuple[uuid.UUID, ...] = (),
) -> _AudioClaimAttempt:
    """Commit one V1b job claim before any media, storage or LLM boundary.

    The initial id read intentionally has no row lock.  The mutation path takes
    Conversation, Pessoa, Meeting, Cell and finally the audio input, matching
    the existing report-maintenance order without holding any lock through I/O.
    """

    candidates = _audio_claim_candidates(
        session_factory,
        igreja_id,
        excluded_input_ids=excluded_input_ids,
    )
    if not candidates:
        return _AudioClaimAttempt(None, True)
    input_id = candidates[0]
    session = session_factory()
    try:
        _scoped(session, igreja_id, "cell_report_audio_claim")

        def defer() -> _AudioClaimAttempt:
            session.commit()
            return _AudioClaimAttempt(None, False, input_id)

        def terminalize(reason: str) -> _AudioClaimAttempt:
            locked_input = session.execute(
                select(CellReportAudioInput)
                .where(
                    CellReportAudioInput.igreja_id == igreja_id,
                    CellReportAudioInput.id == input_id,
                    CellReportAudioInput.state == "pendente",
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if locked_input is None:
                return defer()
            _terminalize_audio_input(locked_input, now=now, reason=reason)
            session.commit()
            return _AudioClaimAttempt(None, False, input_id)

        row = session.execute(
            select(CellReportAudioInput).where(
                CellReportAudioInput.igreja_id == igreja_id,
                CellReportAudioInput.id == input_id,
            )
        ).scalar_one_or_none()
        if row is None:
            session.commit()
            return _AudioClaimAttempt(None, False, input_id)
        if not cell_report_audio_enabled_from_environment(igreja_id):
            locked = session.execute(
                select(CellReportAudioInput)
                .where(
                    CellReportAudioInput.igreja_id == igreja_id,
                    CellReportAudioInput.id == input_id,
                    CellReportAudioInput.state == "pendente",
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if locked is not None:
                _terminalize_audio_input(locked, now=now, reason="gate_fechado")
            session.commit()
            return _AudioClaimAttempt(None, False, input_id)
        if (
            row.live_conversation_id is None
            or row.live_pessoa_id is None
            or row.live_message_id is None
            or row.expires_at <= now
        ):
            locked = session.execute(
                select(CellReportAudioInput)
                .where(
                    CellReportAudioInput.igreja_id == igreja_id,
                    CellReportAudioInput.id == input_id,
                    CellReportAudioInput.state == "pendente",
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if locked is not None:
                _terminalize_audio_input(
                    locked,
                    now=now,
                    reason="ancora_ausente" if row.expires_at > now else "expirado",
                )
            session.commit()
            return _AudioClaimAttempt(None, False, input_id)
        conversation = session.execute(
            select(Conversation)
            .where(
                Conversation.igreja_id == igreja_id,
                Conversation.id == row.live_conversation_id,
                Conversation.pessoa_id == row.live_pessoa_id,
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if conversation is None:
            exists = session.execute(
                select(Conversation.id).where(
                    Conversation.igreja_id == igreja_id,
                    Conversation.id == row.live_conversation_id,
                    Conversation.pessoa_id == row.live_pessoa_id,
                )
            ).scalar_one_or_none()
            return defer() if exists is not None else terminalize("ancora_ausente")
        pessoa = session.execute(
            select(Pessoa)
            .where(Pessoa.igreja_id == igreja_id, Pessoa.id == row.live_pessoa_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if pessoa is None:
            exists = session.execute(
                select(Pessoa.id).where(
                    Pessoa.igreja_id == igreja_id,
                    Pessoa.id == row.live_pessoa_id,
                )
            ).scalar_one_or_none()
            return defer() if exists is not None else terminalize("ancora_ausente")
        from app.services.cell_report_v1a_service import _eligible_meeting
        from app.services.whatsapp_privilege import (
            PrivilegeContext,
            resolve_whatsapp_privilege_context,
        )

        context = resolve_whatsapp_privilege_context(
            session,
            igreja_id=igreja_id,
            conversation_id=conversation.id,
            inbound_message_id=row.live_message_id,
        )
        consent = _active_audio_consent(
            session,
            igreja_id=igreja_id,
            pessoa_id=pessoa.id,
            now=now,
        )
        if (
            type(context) is not PrivilegeContext
            or consent is None
            or consent.id != row.consent_event_id
            or consent.version != row.consent_version
        ):
            return terminalize("contexto_revogado")
        meeting_hint = _eligible_meeting(
            session,
            context=context,
            now=now,
            lock=False,
        )
        if meeting_hint is None:
            return terminalize("reuniao_indisponivel")
        meeting = _eligible_meeting(
            session,
            context=context,
            now=now,
            meeting_id=meeting_hint.id,
            skip_locked=True,
        )
        if meeting is None:
            rechecked = _eligible_meeting(
                session,
                context=context,
                now=now,
                meeting_id=meeting_hint.id,
                lock=False,
            )
            return defer() if rechecked is not None else terminalize("reuniao_indisponivel")
        credential = session.execute(
            select(LlmCredential)
            .where(LlmCredential.igreja_id == igreja_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        credential_locked = credential is not None
        connection = session.execute(
            select(WhatsappConnection)
            .where(WhatsappConnection.igreja_id == igreja_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        connection_locked = connection is not None
        if not credential_locked:
            credential_present = session.execute(
                select(LlmCredential.id).where(
                    LlmCredential.igreja_id == igreja_id,
                )
            ).scalar_one_or_none()
            if credential_present is not None:
                return defer()
        if not connection_locked:
            connection_present = session.execute(
                select(WhatsappConnection.id).where(
                    WhatsappConnection.igreja_id == igreja_id,
                )
            ).scalar_one_or_none()
            if connection_present is not None:
                return defer()
        locked = session.execute(
            select(CellReportAudioInput)
            .where(
                CellReportAudioInput.igreja_id == igreja_id,
                CellReportAudioInput.id == input_id,
                CellReportAudioInput.state == "pendente",
                CellReportAudioInput.purge_state == "ativa",
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if locked is None:
            session.commit()
            return _AudioClaimAttempt(None, False, input_id)
        declared_mime = canonical_audio_mime(locked.declared_mime)
        provider_message_id = session.execute(
            select(Message.provider_message_id).where(
                Message.igreja_id == igreja_id,
                Message.conversation_id == conversation.id,
                Message.id == locked.live_message_id,
                Message.direcao == "in",
                Message.tipo == "audio",
            )
        ).scalar_one_or_none()
        if (
            declared_mime is None
            or type(provider_message_id) is not str
            or not provider_message_id
            or credential is None
            or credential.ativo is not True
            or credential.validado is not True
            or not isinstance(credential.provedor, str)
            or not isinstance(credential.api_key_encrypted, str)
            or not isinstance(credential.modelo, str)
            or not credential.modelo
            or connection is None
            or connection.status != "online"
            or not isinstance(connection.instance, str)
            or not connection.instance
            or not isinstance(conversation.telefone, str)
            or not conversation.telefone
            or locked.transcription_attempts != 0
        ):
            _terminalize_audio_input(locked, now=now, reason="contexto_revogado")
            session.commit()
            return _AudioClaimAttempt(None, False, input_id)
        token = uuid.uuid4()
        locked.state = "processando"
        locked.lease_token = token
        locked.lease_until = now + dt.timedelta(seconds=_AUDIO_LEASE_SECONDS)
        locked.transcription_attempts = 1
        # Record the non-repeatable boundary before download/transcription.  A
        # process loss after this commit becomes reconciliation, never a second
        # paid provider call.
        locked.external_started_at = now
        locked.updated_at = now
        session.commit()
        return _AudioClaimAttempt(
        AudioInputClaim(
                igreja_id=igreja_id,
                input_id=locked.id,
                conversation_id=conversation.id,
                pessoa_id=pessoa.id,
                inbound_message_id=locked.live_message_id,
                provider_message_id=provider_message_id,
                instance=connection.instance,
                phone=conversation.telefone,
                declared_mime=declared_mime,
            provider_message_sha256=locked.provider_message_sha256,
            lease_token=token,
            lease_until=locked.lease_until,
                credential_provider=credential.provedor,
                credential_key_encrypted=credential.api_key_encrypted,
                credential_model=credential.modelo,
            ),
            False,
            input_id,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _cost_microusd(value: object) -> int | None:
    """Convert a finite USD amount without ever rounding a reservation down."""

    if type(value) not in (int, float, Decimal) or type(value) is bool:
        return None
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            return None
        return int((amount * Decimal(1_000_000)).to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _audio_estimated_microusd(duration_seconds: object) -> int | None:
    if type(duration_seconds) not in (int, float) or type(duration_seconds) is bool:
        return None
    try:
        duration = Decimal(str(duration_seconds))
        if not duration.is_finite() or duration <= 0 or duration > Decimal("120"):
            return None
        amount = duration * Decimal(_AUDIO_TRANSCRIPTION_MICROUSD_PER_MINUTE) / Decimal(60)
        return max(1, int(amount.to_integral_value(rounding=ROUND_CEILING)))
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _lock_audio_claim_context(
    session: Session,
    claim: AudioInputClaim,
    *,
    now: dt.datetime,
) -> tuple[CellReportAudioInput, object, object] | None:
    """Revalidate a live V1b source under the common report lock order."""

    row = session.execute(
        select(CellReportAudioInput).where(
            CellReportAudioInput.igreja_id == claim.igreja_id,
            CellReportAudioInput.id == claim.input_id,
        )
    ).scalar_one_or_none()
    if (
        row is None
        or row.live_conversation_id is None
        or row.live_pessoa_id is None
        or row.live_message_id is None
        or row.state != "processando"
        or row.purge_state != "ativa"
        or row.expires_at <= now
    ):
        return None
    if not cell_report_audio_enabled_from_environment(claim.igreja_id):
        return None
    conversation = session.execute(
        select(Conversation)
        .where(
            Conversation.igreja_id == claim.igreja_id,
            Conversation.id == row.live_conversation_id,
            Conversation.pessoa_id == row.live_pessoa_id,
        )
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if conversation is None:
        exists = session.execute(
            select(Conversation.id).where(
                Conversation.igreja_id == claim.igreja_id,
                Conversation.id == row.live_conversation_id,
                Conversation.pessoa_id == row.live_pessoa_id,
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise _AudioClaimBusy
        return None
    pessoa = session.execute(
        select(Pessoa)
        .where(Pessoa.igreja_id == claim.igreja_id, Pessoa.id == row.live_pessoa_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if pessoa is None:
        exists = session.execute(
            select(Pessoa.id).where(
                Pessoa.igreja_id == claim.igreja_id,
                Pessoa.id == row.live_pessoa_id,
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise _AudioClaimBusy
        return None
    from app.services.cell_report_v1a_service import _eligible_meeting
    from app.services.whatsapp_privilege import (
        PrivilegeContext,
        resolve_whatsapp_privilege_context,
    )

    context = resolve_whatsapp_privilege_context(
        session,
        igreja_id=claim.igreja_id,
        conversation_id=conversation.id,
        inbound_message_id=claim.inbound_message_id,
    )
    if type(context) is not PrivilegeContext:
        return None
    consent = _active_audio_consent(
        session,
        igreja_id=claim.igreja_id,
        pessoa_id=pessoa.id,
        now=now,
    )
    if (
        consent is None
        or consent.id != row.consent_event_id
        or consent.version != row.consent_version
    ):
        return None
    meeting = _eligible_meeting(
        session,
        context=context,
        now=now,
        skip_locked=True,
    )
    if meeting is None:
        if _eligible_meeting(session, context=context, now=now, lock=False) is not None:
            raise _AudioClaimBusy
        return None
    locked = session.execute(
        select(CellReportAudioInput)
        .where(
            CellReportAudioInput.igreja_id == claim.igreja_id,
            CellReportAudioInput.id == claim.input_id,
            CellReportAudioInput.state == "processando",
            CellReportAudioInput.lease_token == claim.lease_token,
            CellReportAudioInput.lease_until.is_not(None),
            CellReportAudioInput.lease_until > now,
        )
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if locked is None:
        exists = session.execute(
            select(CellReportAudioInput.id).where(
                CellReportAudioInput.igreja_id == claim.igreja_id,
                CellReportAudioInput.id == claim.input_id,
                CellReportAudioInput.state == "processando",
                CellReportAudioInput.lease_token == claim.lease_token,
                CellReportAudioInput.lease_until.is_not(None),
                CellReportAudioInput.lease_until > now,
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise _AudioClaimBusy
        return None
    return locked, context, meeting


def _audio_claim_still_authorized(
    session_factory: Callable[[], Session],
    claim: AudioInputClaim,
) -> bool | None:
    """Revalidate the durable V1b claim immediately before external I/O.

    A committed claim records ownership only.  It cannot carry authorization
    across a later expiry, feature withdrawal, consent revocation, credential
    change, or disconnected WhatsApp connection.
    """

    from app.services.outbound_guard import external_sends_allowed

    if not external_sends_allowed() or not cell_report_audio_enabled_from_environment(
        claim.igreja_id
    ):
        return False
    current = _utc_now(None)
    lease_until = getattr(claim, "lease_until", None)
    if type(lease_until) is not dt.datetime or lease_until.tzinfo is None:
        return False
    try:
        if lease_until.astimezone(_UTC) <= current:
            return False
    except (OverflowError, ValueError):
        return False
    session = session_factory()
    try:
        _scoped(session, claim.igreja_id, "cell_report_audio_preflight")
        locked_context = _lock_audio_claim_context(session, claim, now=current)
        if locked_context is None:
            session.commit()
            return False
        credential = session.execute(
            select(LlmCredential).where(LlmCredential.igreja_id == claim.igreja_id)
        ).scalar_one_or_none()
        connection = session.execute(
            select(WhatsappConnection).where(WhatsappConnection.igreja_id == claim.igreja_id)
        ).scalar_one_or_none()
        valid = (
            credential is not None
            and credential.ativo is True
            and credential.validado is True
            and isinstance(credential.provedor, str)
            and credential.provedor == claim.credential_provider
            and isinstance(credential.api_key_encrypted, str)
            and credential.api_key_encrypted == claim.credential_key_encrypted
            and isinstance(credential.modelo, str)
            and credential.modelo == claim.credential_model
            and connection is not None
            and connection.status == "online"
            and isinstance(connection.instance, str)
            and connection.instance == claim.instance
        )
        session.commit()
        return valid
    except _AudioClaimBusy:
        session.rollback()
        return None
    except Exception:
        session.rollback()
        # Treat an unavailable local transaction like lock contention.  The
        # durable ``processando`` row remains the recovery record; returning
        # False here would incorrectly tell the caller that handoff completed.
        logger.warning("Handoff de áudio V1b adiado por falha local")
        return None
    finally:
        session.close()


def reserve_audio_transcription_budget(
    session_factory: Callable[[], Session],
    claim: AudioInputClaim,
    *,
    duration_seconds: object,
    now: dt.datetime | None = None,
) -> AudioBudgetReservation | None:
    """Commit the conservative V1b share of the existing report/day ceiling."""

    current = _utc_now(now)
    estimate = _audio_estimated_microusd(duration_seconds)
    if estimate is None:
        return None
    session = session_factory()
    try:
        _scoped(session, claim.igreja_id, "cell_report_audio_budget_reserve")
        if not cell_report_audio_enabled_from_environment(claim.igreja_id):
            session.commit()
            return None
        locked_context = _lock_audio_claim_context(session, claim, now=current)
        if locked_context is None:
            session.commit()
            return None
        row, _context, meeting = locked_context
        existing = session.execute(
            select(CellReportAudioReservation)
            .where(
                CellReportAudioReservation.igreja_id == claim.igreja_id,
                CellReportAudioReservation.audio_input_id == claim.input_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if existing is not None:
            if (
                existing.state != "reservada"
                or existing.estimated_microusd != estimate
                or existing.reuniao_id != meeting.id
            ):
                session.commit()
                return None
            session.commit()
            return AudioBudgetReservation(existing.id, existing.estimated_microusd)
        audio_rows = tuple(
            session.execute(
                select(CellReportAudioReservation)
                .where(
                    CellReportAudioReservation.igreja_id == claim.igreja_id,
                    CellReportAudioReservation.reuniao_id == meeting.id,
                )
                .order_by(CellReportAudioReservation.audio_number.asc())
                .with_for_update(of=CellReportAudioReservation)
                .execution_options(populate_existing=True)
            ).scalars()
        )
        extraction_rows = tuple(
            session.execute(
                select(CellReportAiReservation)
                .join(
                    CellReportDraft,
                    (CellReportDraft.igreja_id == CellReportAiReservation.igreja_id)
                    & (CellReportDraft.id == CellReportAiReservation.draft_id),
                )
                .where(
                    CellReportAiReservation.igreja_id == claim.igreja_id,
                    CellReportDraft.reuniao_id == meeting.id,
                    CellReportAiReservation.state != "cancelada",
                )
                .with_for_update(of=CellReportAiReservation)
                .execution_options(populate_existing=True)
            ).scalars()
        )
        active_audio = tuple(item for item in audio_rows if item.state != "cancelada")
        number = max((item.audio_number for item in audio_rows), default=0) + 1
        report_reserved = sum(item.estimated_microusd for item in active_audio) + sum(
            item.estimated_microusd for item in extraction_rows
        )
        if number > 3 or report_reserved + estimate > _AUDIO_REPORT_LIMIT_MICROUSD:
            _terminalize_audio_input(row, now=current, reason="orcamento_indisponivel")
            session.commit()
            return None
        from app.services.cell_report_whatsapp import (
            CELL_REPORT_COST_VERSION,
            _locked_daily_budget,
        )

        budget = _locked_daily_budget(
            session,
            igreja_id=claim.igreja_id,
            budget_day=current.date(),
            now=current,
        )
        if (
            budget.cost_version != CELL_REPORT_COST_VERSION
            or type(budget.reserved_microusd) is not int
            or type(budget.settled_microusd) is not int
            or budget.reserved_microusd < 0
            or budget.settled_microusd < 0
            or budget.reserved_microusd + budget.settled_microusd + estimate
            > _AUDIO_DAILY_LIMIT_MICROUSD
        ):
            _terminalize_audio_input(row, now=current, reason="orcamento_indisponivel")
            session.commit()
            return None
        reservation = CellReportAudioReservation(
            id=uuid.uuid4(),
            igreja_id=claim.igreja_id,
            audio_input_id=claim.input_id,
            reuniao_id=meeting.id,
            budget_id=budget.id,
            audio_number=number,
            budget_day=current.date(),
            cost_version=_AUDIO_COST_VERSION,
            state="reservada",
            estimated_microusd=estimate,
            actual_microusd=None,
            created_at=current,
            settled_at=None,
        )
        session.add(reservation)
        budget.reserved_microusd += estimate
        budget.updated_at = current
        session.commit()
        return AudioBudgetReservation(reservation.id, estimate)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _settle_audio_transcription_budget(
    session_factory: Callable[[], Session],
    claim: AudioInputClaim,
    reservation: AudioBudgetReservation,
    *,
    actual_cost: object,
    now: dt.datetime,
) -> bool:
    actual = _cost_microusd(actual_cost)
    if actual is None or actual > reservation.estimated_microusd:
        return False
    session = session_factory()
    try:
        _scoped(session, claim.igreja_id, "cell_report_audio_budget_settle")
        row = session.execute(
            select(CellReportAudioReservation)
            .where(
                CellReportAudioReservation.igreja_id == claim.igreja_id,
                CellReportAudioReservation.id == reservation.reservation_id,
                CellReportAudioReservation.audio_input_id == claim.input_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if row is None or row.state not in {"reservada", "liquidada"}:
            session.commit()
            return False
        budget = session.execute(
            select(CellReportAiDailyBudget)
            .where(
                CellReportAiDailyBudget.igreja_id == claim.igreja_id,
                CellReportAiDailyBudget.id == row.budget_id,
                CellReportAiDailyBudget.budget_day == row.budget_day,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if budget is None or row.estimated_microusd != reservation.estimated_microusd:
            session.commit()
            return False
        if row.state == "liquidada":
            session.commit()
            return row.actual_microusd == actual
        if budget.reserved_microusd < row.estimated_microusd:
            session.commit()
            return False
        row.state = "liquidada"
        row.actual_microusd = actual
        row.settled_at = now
        budget.reserved_microusd -= row.estimated_microusd
        budget.settled_microusd += actual
        budget.updated_at = now
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _audio_output_provider_id(input_id: uuid.UUID) -> str:
    return f"{_AUDIO_OUTPUT_PREFIX}{input_id.hex}"


def _audio_dispatch_outcome(claim: AudioInputClaim):
    """Build only the durable-ledger context required for one outbound reply."""

    from app.workers.queue_worker import IngestionOutcome, IngestionResult

    return IngestionOutcome(
        result=IngestionResult.REGISTERED,
        conversation_id=claim.conversation_id,
        instance=claim.instance,
        telefone=claim.phone,
        texto=None,
        inbound=True,
        igreja_id=claim.igreja_id,
        provider_message_id=claim.provider_message_id,
        claim_id=f"v1b-audio:{claim.input_id.hex}",
        inbound_message_id=claim.inbound_message_id,
    )


def _audio_media_key(claim: AudioInputClaim) -> dict[str, object]:
    """Reconstruct the trusted Evolution key from the live inbound anchor.

    V1b captures only inbound direct-chat audio, so ``fromMe`` is fixed rather
    than taken from caller input.  The provider id and phone were reloaded from
    the persisted Message/Conversation under the claim locks.
    """

    if (
        type(claim.provider_message_id) is not str
        or not claim.provider_message_id
        or type(claim.phone) is not str
        or not claim.phone
    ):
        raise CellReportAudioServiceError("mídia de áudio indisponível")
    return {
        "id": claim.provider_message_id,
        "remoteJid": f"{claim.phone}@s.whatsapp.net",
        "fromMe": False,
    }


def _remaining_audio_seconds(deadline_at: float, *, cap: float) -> float:
    remaining = deadline_at - time.monotonic()
    if not math.isfinite(remaining) or remaining <= 0:
        raise CellReportAudioServiceError("prazo de áudio indisponível")
    return min(cap, remaining)


def _run_audio_boundary(
    operation: Callable[[], object],
    *,
    deadline_at: float,
    progress_callback: Callable[[], None] | None,
) -> object:
    """Run one blocking boundary while keeping cron health bounded to its lease.

    The callback never touches the database and stops by the durable monotonic
    deadline.  It therefore cannot keep a stuck provider call healthy beyond
    the claim's own fence, and its thread is joined before this function
    returns.
    """

    if progress_callback is None:
        result = operation()
        if time.monotonic() >= deadline_at:
            raise CellReportAudioServiceError("prazo de áudio indisponível")
        return result
    stop = Event()

    def heartbeat() -> None:
        while True:
            remaining = deadline_at - time.monotonic()
            if not math.isfinite(remaining) or remaining <= 0:
                return
            if stop.wait(min(5.0, remaining)):
                return
            progress_callback()

    progress_callback()
    thread = Thread(target=heartbeat, name="cell-report-audio-boundary", daemon=True)
    thread.start()
    try:
        result = operation()
    finally:
        stop.set()
        thread.join(timeout=1.0)
        if time.monotonic() < deadline_at:
            progress_callback()
    if time.monotonic() >= deadline_at:
        raise CellReportAudioServiceError("prazo de áudio indisponível")
    return result


def _wait_for_audio_authorization(
    session_factory: Callable[[], Session],
    claim: AudioInputClaim,
    *,
    deadline_at: float,
    progress_callback: Callable[[], None] | None = None,
) -> bool:
    """Reprobe short row-lock contention without retaining a session or lock.

    A claim that already crossed an external boundary must not be reset or
    re-run.  The bounded wait is therefore local only and ends at the durable
    lease deadline, where the caller routes to the existing human fallback.
    """

    while True:
        if progress_callback is not None:
            progress_callback()
        authorized = _audio_claim_still_authorized(session_factory, claim)
        if authorized is not None:
            if progress_callback is not None:
                progress_callback()
            return authorized
        try:
            remaining = _remaining_audio_seconds(deadline_at, cap=0.05)
        except CellReportAudioServiceError:
            raise _AudioClaimDeadlineExceeded("prazo de áudio indisponível") from None
        time.sleep(remaining)


def _defer_audio_claim_before_external(
    session_factory: Callable[[], Session],
    claim: AudioInputClaim,
    *,
    now: dt.datetime | None = None,
) -> bool:
    """Return one pre-I/O claim to pending through its lease-token CAS.

    ``external_started_at`` is recorded at claim time to survive a crash.  It
    is cleared only here, before *any* media, storage or transcription call;
    later contention instead uses ``_wait_for_audio_authorization``.
    """

    current = _utc_now(now)
    session = session_factory()
    try:
        _scoped(session, claim.igreja_id, "cell_report_audio_defer")
        row = session.execute(
            select(CellReportAudioInput).where(
                CellReportAudioInput.igreja_id == claim.igreja_id,
                CellReportAudioInput.id == claim.input_id,
            )
        ).scalar_one_or_none()
        if row is None:
            session.commit()
            return False
        if row.live_conversation_id is not None:
            conversation = session.execute(
                select(Conversation)
                .where(
                    Conversation.igreja_id == claim.igreja_id,
                    Conversation.id == row.live_conversation_id,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if conversation is None:
                exists = session.execute(
                    select(Conversation.id).where(
                        Conversation.igreja_id == claim.igreja_id,
                        Conversation.id == row.live_conversation_id,
                    )
                ).scalar_one_or_none()
                session.commit()
                return exists is None
        if row.live_pessoa_id is not None:
            pessoa = session.execute(
                select(Pessoa)
                .where(
                    Pessoa.igreja_id == claim.igreja_id,
                    Pessoa.id == row.live_pessoa_id,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if pessoa is None:
                exists = session.execute(
                    select(Pessoa.id).where(
                        Pessoa.igreja_id == claim.igreja_id,
                        Pessoa.id == row.live_pessoa_id,
                    )
                ).scalar_one_or_none()
                session.commit()
                return exists is None
        locked = session.execute(
            select(CellReportAudioInput)
            .where(
                CellReportAudioInput.igreja_id == claim.igreja_id,
                CellReportAudioInput.id == claim.input_id,
                CellReportAudioInput.state == "processando",
                CellReportAudioInput.lease_token == claim.lease_token,
                CellReportAudioInput.transcription_attempts == 1,
                CellReportAudioInput.external_started_at.is_not(None),
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if locked is None:
            session.commit()
            return False
        locked.state = "pendente"
        locked.lease_token = None
        locked.lease_until = None
        locked.external_started_at = None
        locked.transcription_attempts = 0
        locked.updated_at = current
        session.commit()
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


def _audio_transcript(value: object) -> str:
    if type(value) is not str:
        raise CellReportAudioServiceError("transcrição indisponível")
    transcript = value.strip()
    if not transcript or len(transcript) > 4_000:
        raise CellReportAudioServiceError("transcrição indisponível")
    return transcript


def _terminalize_audio_claim(
    session_factory: Callable[[], Session],
    claim: AudioInputClaim,
    *,
    reason: str,
    ambiguous: bool,
    expire_for_purge: bool = False,
    now: dt.datetime | None = None,
) -> bool:
    """Fence one claimed job after a local or external failure.

    The token comparison prevents a stale provider return from overwriting a
    later terminal decision.  Locks follow the report order whenever the live
    anchors still exist; an already deleted anchor falls back to the durable
    job row solely to retain the purge path.
    """

    current = _utc_now(now)
    session = session_factory()
    try:
        _scoped(session, claim.igreja_id, "cell_report_audio_terminalize")
        row = session.execute(
            select(CellReportAudioInput).where(
                CellReportAudioInput.igreja_id == claim.igreja_id,
                CellReportAudioInput.id == claim.input_id,
            )
        ).scalar_one_or_none()
        if row is None:
            session.commit()
            return True
        if row.live_conversation_id is not None:
            conversation = session.execute(
                select(Conversation)
                .where(
                    Conversation.igreja_id == claim.igreja_id,
                    Conversation.id == row.live_conversation_id,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if conversation is None:
                exists = session.execute(
                    select(Conversation.id).where(
                        Conversation.igreja_id == claim.igreja_id,
                        Conversation.id == row.live_conversation_id,
                    )
                ).scalar_one_or_none()
                if exists is not None:
                    session.commit()
                    logger.warning("Terminalização de áudio V1b adiada por contenção")
                    return False
        if row.live_pessoa_id is not None:
            pessoa = session.execute(
                select(Pessoa)
                .where(
                    Pessoa.igreja_id == claim.igreja_id,
                    Pessoa.id == row.live_pessoa_id,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if pessoa is None:
                exists = session.execute(
                    select(Pessoa.id).where(
                        Pessoa.igreja_id == claim.igreja_id,
                        Pessoa.id == row.live_pessoa_id,
                    )
                ).scalar_one_or_none()
                if exists is not None:
                    session.commit()
                    logger.warning("Terminalização de áudio V1b adiada por contenção")
                    return False
        locked = session.execute(
            select(CellReportAudioInput)
            .where(
                CellReportAudioInput.igreja_id == claim.igreja_id,
                CellReportAudioInput.id == claim.input_id,
                CellReportAudioInput.state == "processando",
                CellReportAudioInput.lease_token == claim.lease_token,
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if locked is None:
            exists = session.execute(
                select(CellReportAudioInput.id).where(
                    CellReportAudioInput.igreja_id == claim.igreja_id,
                    CellReportAudioInput.id == claim.input_id,
                    CellReportAudioInput.state == "processando",
                    CellReportAudioInput.lease_token == claim.lease_token,
                )
            ).scalar_one_or_none()
            session.commit()
            if exists is not None:
                logger.warning("Terminalização de áudio V1b adiada por contenção")
            return exists is None
        _terminalize_audio_input(
            locked,
            now=current,
            reason=reason,
            ambiguous=ambiguous,
        )
        if expire_for_purge:
            # Upload already crossed the private-storage boundary.  Make
            # its cleanup eligible on the next maintenance pass rather
            # than retaining bytes until the ordinary 24-hour deadline.
            locked.expires_at = _immediate_audio_expiry(locked, current)
            locked.purge_state = "ativa"
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _reopen_audio_purge_after_late_upload(
    session_factory: Callable[[], Session],
    claim: AudioInputClaim,
    *,
    now: dt.datetime | None = None,
) -> None:
    """Reopen physical cleanup if storage returned after an expired purge lease.

    The old purge may have observed no object yet and marked the durable row as
    purged.  A late successful upload must make the same canonical path
    selectable again, never leave a private blob stranded.
    """

    current = _utc_now(now)
    session = session_factory()
    try:
        _scoped(session, claim.igreja_id, "cell_report_audio_late_upload")
        row = session.execute(
            select(CellReportAudioInput)
            .where(
                CellReportAudioInput.igreja_id == claim.igreja_id,
                CellReportAudioInput.id == claim.input_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if row is not None and row.purge_state in {"pendente", "purgada"}:
            row.purge_state = "ativa"
            row.content_purged_at = None
            row.purge_error_code = None
            # Invalidate a storage-delete completion that was already in
            # flight when the delayed upload returned.
            row.purge_attempts += 1
            row.expires_at = _immediate_audio_expiry(row, current)
            row.updated_at = current
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def _stage_audio_transcript(
    session_factory: Callable[[], Session],
    claim: AudioInputClaim,
    *,
    transcript: str,
    measured_mime: str,
    byte_size: int,
    duration_seconds: float,
    content_sha256: str,
    now: dt.datetime | None = None,
):
    """Persist private transcript facts and one V1a reply intent atomically.

    This is deliberately after all media and transcription I/O.  A failure to
    revalidate any current authorization leaves no new summary eligible for
    transport.  The transcript is never copied to ``Message.texto``.
    """

    current = _utc_now(now)
    session = session_factory()
    try:
        _scoped(session, claim.igreja_id, "cell_report_audio_stage")
        if not cell_report_audio_enabled_from_environment(claim.igreja_id):
            session.commit()
            _terminalize_audio_claim(
                session_factory,
                claim,
                reason="gate_fechado",
                ambiguous=False,
                expire_for_purge=True,
                now=current,
            )
            return None
        locked_context = _lock_audio_claim_context(session, claim, now=current)
        if locked_context is None:
            session.commit()
            _terminalize_audio_claim(
                session_factory,
                claim,
                reason="contexto_revogado",
                ambiguous=False,
                expire_for_purge=True,
                now=current,
            )
            return None
        row, context, _meeting = locked_context
        conversation = session.execute(
            select(Conversation)
            .where(
                Conversation.igreja_id == claim.igreja_id,
                Conversation.id == claim.conversation_id,
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if conversation is None:
            session.commit()
            _terminalize_audio_claim(
                session_factory,
                claim,
                reason="ancora_ausente",
                ambiguous=False,
                expire_for_purge=True,
                now=current,
            )
            return None
        from app.agent.nodes import is_handoff_request
        from app.domain.consent import is_optout_request
        from app.services.conversation_handoff import mark_conversation_for_handoff_locked

        if is_optout_request(transcript):
            from app.agent.runtime import _apply_optout

            pessoa = session.execute(
                select(Pessoa)
                .where(
                    Pessoa.igreja_id == claim.igreja_id,
                    Pessoa.id == context.pessoa_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if pessoa is None:
                session.commit()
                _terminalize_audio_claim(
                    session_factory,
                    claim,
                    reason="contexto_revogado",
                    ambiguous=False,
                    expire_for_purge=True,
                    now=current,
                )
                return None
            _apply_optout(
                pessoa,
                claim.igreja_id,
                session,
                getattr(get_settings(), "agent_term_version", None),
            )
            mark_conversation_for_handoff_locked(session, conversation=conversation)
            _terminalize_audio_input(
                row,
                now=current,
                reason="transcricao_optout",
                scrub_private=True,
                expire_for_purge=True,
            )
            session.commit()
            return None

        row.measured_mime = measured_mime
        row.byte_size = byte_size
        row.duration_seconds = duration_seconds
        row.content_sha256 = content_sha256
        row.transcript_text = transcript
        row.transcript_sha256 = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
        row.transcribed_at = current
        row.updated_at = current
        if is_handoff_request(transcript):
            mark_conversation_for_handoff_locked(session, conversation=conversation)
            _terminalize_audio_input(
                row,
                now=current,
                reason="transcricao_humano",
                scrub_private=True,
                expire_for_purge=True,
            )
            session.commit()
            return None

        from app.domain.agent_reply import (
            AGENT_REPLY_NO_RESPONSE,
            AGENT_REPLY_PENDING,
            AGENT_REPLY_RESERVED,
        )
        from app.services.cell_report_v1a_service import (
            CellReportStageKind,
            stage_v1a_cell_report_turn,
        )
        from app.agent.privileged_turn import reply_metadata
        from app.workers import queue_worker as qw

        output_key = _audio_output_provider_id(claim.input_id)
        output = session.execute(
            select(Message)
            .where(
                Message.igreja_id == claim.igreja_id,
                Message.conversation_id == claim.conversation_id,
                Message.provider_message_id == output_key,
                Message.direcao == "out",
                Message.autor == "ia",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if output is not None:
            if output.agent_reply_state == AGENT_REPLY_PENDING:
                row.state = "transcrita"
                row.lease_token = None
                row.lease_until = None
                session.commit()
                return qw._intent_from_message(output)
            session.commit()
            return None
        output = Message(
            id=uuid.uuid4(),
            igreja_id=claim.igreja_id,
            conversation_id=claim.conversation_id,
            direcao="out",
            autor="ia",
            tipo="texto",
            texto=None,
            provider_message_id=output_key,
            agent_reply_state=AGENT_REPLY_RESERVED,
            public_info_reply=False,
        )
        session.add(output)
        session.flush()
        stage = stage_v1a_cell_report_turn(
            session,
            context=context,
            inbound_message_id=claim.inbound_message_id,
            text=transcript,
            summary_message=output,
            now=current,
        )
        if stage.kind is CellReportStageKind.HUMAN_REQUIRED:
            mark_conversation_for_handoff_locked(session, conversation=conversation)
            _terminalize_audio_input(
                row,
                now=current,
                reason="relatorio_indisponivel",
                scrub_private=True,
                expire_for_purge=True,
            )
            output.agent_reply_state = AGENT_REPLY_NO_RESPONSE
            output.texto = ""
            session.commit()
            return None
        if stage.kind is CellReportStageKind.NOT_APPLICABLE:
            row.state = "transcrita"
            row.lease_token = None
            row.lease_until = None
            output.agent_reply_state = AGENT_REPLY_NO_RESPONSE
            output.texto = ""
            session.commit()
            return None
        if stage.kind is CellReportStageKind.EXTRACTION:
            from app.services.cell_report_whatsapp import (
                CellReportWhatsappError,
                reserve_v1a_extraction_budget,
            )
            from app.services.llm import estimate_cost

            if (
                stage.draft_id is None
                or stage.draft_revision is None
                or stage.extraction_projection is None
            ):
                raise CellReportAudioServiceError("resumo de áudio indisponível")
            try:
                reservation = reserve_v1a_extraction_budget(
                    session,
                    igreja_id=claim.igreja_id,
                    draft_id=stage.draft_id,
                    model=claim.credential_model,
                    estimate_cost=estimate_cost,
                )
            except (CellReportWhatsappError, ValueError) as exc:
                raise CellReportAudioServiceError("custo de extração indisponível") from exc
            if reservation is None:
                raise CellReportAudioServiceError("custo de extração indisponível")
            session.commit()
            return _AudioExtractionPlan(
                claim=claim,
                draft_id=stage.draft_id,
                draft_revision=stage.draft_revision,
                projection=dict(stage.extraction_projection),
                reservation_id=reservation.reservation_id,
            )
        if stage.kind is CellReportStageKind.SUMMARY:
            if stage.proposal is None or not isinstance(stage.response, str):
                raise CellReportAudioServiceError("resumo de áudio indisponível")
            output.texto = stage.response
            output.agent_reply_state = AGENT_REPLY_PENDING
            output.agent_privilege_context = reply_metadata(
                context,
                kind="summary",
                proposal_id=stage.proposal.proposal_id,
                audio_input_id=row.id,
            )
        elif stage.kind is CellReportStageKind.CLARIFY:
            if not isinstance(stage.response, str):
                raise CellReportAudioServiceError("resumo de áudio indisponível")
            output.texto = stage.response
            output.agent_reply_state = AGENT_REPLY_PENDING
            output.agent_privilege_context = reply_metadata(
                context,
                kind="clarify",
                audio_input_id=row.id,
            )
        else:
            raise CellReportAudioServiceError("resumo de áudio indisponível")
        row.state = "transcrita"
        row.lease_token = None
        row.lease_until = None
        session.commit()
        return qw._intent_from_message(output)
    except _AudioClaimBusy:
        session.rollback()
        logger.info("Estágio de áudio V1b adiado por contenção")
        return _AUDIO_STAGE_DEFERRED
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _handoff_audio_claim_failure(
    session_factory: Callable[[], Session],
    claim: AudioInputClaim,
    *,
    reason: str,
    ambiguous: bool,
    now: dt.datetime | None = None,
) -> bool | None:
    """Fail closed to the existing human path after an audio boundary fails.

    ``None`` means a short durable lock is still held.  The caller retries the
    local fence before the claim deadline, never repeats media or provider I/O.
    """

    current = _utc_now(now)
    session = session_factory()
    try:
        _scoped(session, claim.igreja_id, "cell_report_audio_failure_handoff")
        locked_context = _lock_audio_claim_context(session, claim, now=current)
        if locked_context is None:
            # A provider boundary can reach its hard deadline precisely when
            # the normal gate rejects the expired lease.  That must still
            # leave an explicit human fence, provided this worker still owns
            # the input.  This fallback deliberately validates only durable
            # anchors and the lease token: it grants nothing and cannot revive
            # a newer claim.
            row = session.execute(
                select(CellReportAudioInput).where(
                    CellReportAudioInput.igreja_id == claim.igreja_id,
                    CellReportAudioInput.id == claim.input_id,
                    CellReportAudioInput.state == "processando",
                    CellReportAudioInput.lease_token == claim.lease_token,
                )
            ).scalar_one_or_none()
            if row is None:
                session.commit()
                return False
            conversation = None
            if row.live_conversation_id is not None:
                conversation = session.execute(
                    select(Conversation)
                    .where(
                        Conversation.igreja_id == claim.igreja_id,
                        Conversation.id == row.live_conversation_id,
                    )
                    .with_for_update(skip_locked=True)
                    .execution_options(populate_existing=True)
                ).scalar_one_or_none()
                if conversation is None:
                    exists = session.execute(
                        select(Conversation.id).where(
                            Conversation.igreja_id == claim.igreja_id,
                            Conversation.id == row.live_conversation_id,
                        )
                    ).scalar_one_or_none()
                    if exists is not None:
                        raise _AudioClaimBusy
            if row.live_pessoa_id is not None:
                pessoa = session.execute(
                    select(Pessoa)
                    .where(
                        Pessoa.igreja_id == claim.igreja_id,
                        Pessoa.id == row.live_pessoa_id,
                    )
                    .with_for_update(skip_locked=True)
                    .execution_options(populate_existing=True)
                ).scalar_one_or_none()
                if pessoa is None:
                    exists = session.execute(
                        select(Pessoa.id).where(
                            Pessoa.igreja_id == claim.igreja_id,
                            Pessoa.id == row.live_pessoa_id,
                        )
                    ).scalar_one_or_none()
                    if exists is not None:
                        raise _AudioClaimBusy
            row = session.execute(
                select(CellReportAudioInput)
                .where(
                    CellReportAudioInput.igreja_id == claim.igreja_id,
                    CellReportAudioInput.id == claim.input_id,
                    CellReportAudioInput.state == "processando",
                    CellReportAudioInput.lease_token == claim.lease_token,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if row is None:
                raise _AudioClaimBusy
        else:
            row, _context, _meeting = locked_context
            conversation = session.execute(
                select(Conversation)
                .where(
                    Conversation.igreja_id == claim.igreja_id,
                    Conversation.id == claim.conversation_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
        from app.services.conversation_handoff import mark_conversation_for_handoff_locked

        if conversation is not None:
            mark_conversation_for_handoff_locked(session, conversation=conversation)
        _terminalize_audio_input(
            row,
            now=current,
            reason=reason,
            ambiguous=ambiguous,
            scrub_private=True,
            expire_for_purge=True,
        )
        session.commit()
        return True
    except _AudioClaimBusy:
        session.rollback()
        return None
    except Exception:
        session.rollback()
        # A database failure cannot establish that the prior durable handoff
        # won. Treat it like contention so the caller reaches the bounded
        # terminal path, then the gate-independent recovery pass retries only
        # the local fence after the lease expires.
        logger.warning("Encaminhamento de áudio V1b adiado por falha local")
        return None
    finally:
        session.close()


def _handoff_audio_claim_after_boundary(
    session_factory: Callable[[], Session],
    claim: AudioInputClaim,
    *,
    deadline_at: float,
    reason: str,
    ambiguous: bool,
    storage_attempted: bool,
    progress_callback: Callable[[], None] | None = None,
) -> None:
    """Fence a failed audio chain without repeating any external boundary."""

    # Storage can have accepted the object even when it reports a timeout.
    # Reopen retention before the handoff, whose terminalization otherwise
    # overwrites the generation that an older delete completion must not close.
    if storage_attempted:
        _reopen_audio_purge_after_late_upload(session_factory, claim)
    while True:
        result = _handoff_audio_claim_failure(
            session_factory,
            claim,
            reason=reason,
            ambiguous=ambiguous,
        )
        if result is not None:
            return
        try:
            authorized = _wait_for_audio_authorization(
                session_factory,
                claim,
                deadline_at=deadline_at,
                progress_callback=progress_callback,
            )
        except _AudioClaimDeadlineExceeded:
            break
        if not authorized:
            break
    # A terminal write without the Conversation/Pessoa fence would suppress the
    # only durable route to human attention.  Leave the claimed row intact for
    # ``recover_expired_audio_handoffs``; it retries no provider boundary and
    # runs before purge, even when rollout and send gates have closed.
    logger.warning("Encaminhamento de áudio V1b aguardando recuperação local")


def _complete_audio_extraction_after_provider(
    session_factory: Callable[[], Session],
    plan: _AudioExtractionPlan,
    *,
    extracted_payload: object,
    usage: object,
    actual_microusd: int,
    now: dt.datetime | None = None,
) -> object:
    """Apply one paid V1a completion after closed-session LLM I/O."""

    from app.agent.masking import log_ai_usage
    from app.agent.privileged_turn import reply_metadata
    from app.domain.agent_reply import AGENT_REPLY_NO_RESPONSE, AGENT_REPLY_PENDING, AGENT_REPLY_RESERVED
    from app.services.cell_report_v1a_service import (
        CellReportStageKind,
        complete_v1a_extraction_after_provider,
    )
    from app.workers import queue_worker as qw

    claim = plan.claim
    current = _utc_now(now)
    session = session_factory()
    try:
        _scoped(session, claim.igreja_id, "cell_report_audio_extract_complete")
        locked_context = _lock_audio_claim_context(session, claim, now=current)
        if locked_context is None:
            session.commit()
            return None
        row, context, _meeting = locked_context
        conversation = session.execute(
            select(Conversation)
            .where(
                Conversation.igreja_id == claim.igreja_id,
                Conversation.id == claim.conversation_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        output = session.execute(
            select(Message)
            .where(
                Message.igreja_id == claim.igreja_id,
                Message.conversation_id == claim.conversation_id,
                Message.provider_message_id == _audio_output_provider_id(claim.input_id),
                Message.direcao == "out",
                Message.autor == "ia",
                Message.agent_reply_state == AGENT_REPLY_RESERVED,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if conversation is None or output is None:
            session.commit()
            return None
        stage = complete_v1a_extraction_after_provider(
            session,
            context=context,
            inbound_message_id=claim.inbound_message_id,
            summary_message=output,
            draft_id=plan.draft_id,
            expected_revision=plan.draft_revision,
            projection=plan.projection,
            extracted_payload=extracted_payload,
            reservation_id=plan.reservation_id,
            actual_microusd=actual_microusd,
            now=current,
        )
        if stage.kind is CellReportStageKind.SUMMARY:
            if stage.proposal is None or not isinstance(stage.response, str):
                raise CellReportAudioServiceError("resumo de áudio indisponível")
            output.texto = stage.response
            output.agent_reply_state = AGENT_REPLY_PENDING
            output.agent_privilege_context = reply_metadata(
                context,
                kind="summary",
                proposal_id=stage.proposal.proposal_id,
                audio_input_id=row.id,
            )
            row.state = "transcrita"
            row.lease_token = None
            row.lease_until = None
            result = qw._intent_from_message(output)
        elif stage.kind is CellReportStageKind.CLARIFY:
            if not isinstance(stage.response, str):
                raise CellReportAudioServiceError("resumo de áudio indisponível")
            output.texto = stage.response
            output.agent_reply_state = AGENT_REPLY_PENDING
            output.agent_privilege_context = reply_metadata(
                context,
                kind="clarify",
                audio_input_id=row.id,
            )
            row.state = "transcrita"
            row.lease_token = None
            row.lease_until = None
            result = qw._intent_from_message(output)
        else:
            from app.services.conversation_handoff import mark_conversation_for_handoff_locked

            mark_conversation_for_handoff_locked(session, conversation=conversation)
            _terminalize_audio_input(
                row,
                now=current,
                reason="extracao_contexto_revogado",
                scrub_private=True,
                expire_for_purge=True,
            )
            output.agent_reply_state = AGENT_REPLY_NO_RESPONSE
            output.texto = ""
            result = None
        log_ai_usage(
            session,
            igreja_id=claim.igreja_id,
            usage=usage,
            ferramenta="cell_report_extraction",
        )
        session.commit()
        return result
    except _AudioClaimBusy:
        session.rollback()
        return _AUDIO_STAGE_DEFERRED
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _run_audio_extraction_provider_chain(
    session_factory: Callable[[], Session],
    plan: _AudioExtractionPlan,
    *,
    deadline_at: float,
    progress_callback: Callable[[], None] | None = None,
) -> object | None:
    """Run the V1a aggregate extractor after the audio transcript is durable."""

    from app.services.cell_report_whatsapp import actual_v1a_extraction_microusd
    from app.services.crypto import decrypt_secret
    from app.services.llm import LLMClient, LLMError, estimate_cost

    claim = plan.claim
    if not _wait_for_audio_authorization(
        session_factory,
        claim,
        deadline_at=deadline_at,
        progress_callback=progress_callback,
    ):
        _handoff_audio_claim_after_boundary(
            session_factory,
            claim,
            deadline_at=deadline_at,
            reason="extracao_contexto_revogado",
            ambiguous=False,
            storage_attempted=True,
            progress_callback=progress_callback,
        )
        return None
    try:
        extraction = _run_audio_boundary(
            lambda: LLMClient(
                claim.credential_provider,
                decrypt_secret(claim.credential_key_encrypted),
                claim.credential_model,
            ).extract_v1a_cell_report(
                plan.projection,
                timeout_seconds=_remaining_audio_seconds(deadline_at, cap=4.0),
            ),
            deadline_at=deadline_at,
            progress_callback=progress_callback,
        )
        actual_microusd = actual_v1a_extraction_microusd(
            extraction.usage,
            estimate_cost,
        )
    except (LLMError, ValueError, TypeError, CellReportAudioServiceError):
        _handoff_audio_claim_after_boundary(
            session_factory,
            claim,
            deadline_at=deadline_at,
            reason="extracao_indisponivel",
            ambiguous=False,
            storage_attempted=True,
            progress_callback=progress_callback,
        )
        return None
    while True:
        result = _complete_audio_extraction_after_provider(
            session_factory,
            plan,
            extracted_payload=extraction.payload,
            usage=extraction.usage,
            actual_microusd=actual_microusd,
        )
        if result is not _AUDIO_STAGE_DEFERRED:
            return result
        if not _wait_for_audio_authorization(
            session_factory,
            claim,
            deadline_at=deadline_at,
            progress_callback=progress_callback,
        ):
            _handoff_audio_claim_after_boundary(
                session_factory,
                claim,
                deadline_at=deadline_at,
                reason="extracao_contexto_revogado",
                ambiguous=False,
                storage_attempted=True,
                progress_callback=progress_callback,
            )
            return None


def _run_audio_provider_chain(
    session_factory: Callable[[], Session],
    claim: AudioInputClaim,
    *,
    evolution_client: object,
    storage: object,
    decoder: Callable[..., object],
    transcriber: Callable[..., object],
    progress_callback: Callable[[], None] | None = None,
) -> object | None:
    """Run bounded V1b I/O outside every database session and stage its reply."""

    from app.services.crypto import decrypt_secret
    from app.services.cell_report_audio import (
        CELL_REPORT_AUDIO_DECODER_DEADLINE_SECONDS,
        CELL_REPORT_AUDIO_MAX_BYTES,
        CELL_REPORT_AUDIO_TRANSCRIPTION_DEADLINE_SECONDS,
        DecodedAudio,
        canonical_audio_mime,
    )

    current = _utc_now(None)
    lease_until = claim.lease_until
    if type(lease_until) is not dt.datetime or lease_until.tzinfo is None:
        _terminalize_audio_claim(
            session_factory,
            claim,
            reason="prazo_processamento_expirado",
            ambiguous=False,
            expire_for_purge=True,
            now=current,
        )
        return None
    try:
        remaining_lease = (lease_until.astimezone(_UTC) - current).total_seconds()
    except (OverflowError, ValueError):
        remaining_lease = 0.0
    if not math.isfinite(remaining_lease) or remaining_lease <= 0:
        _terminalize_audio_claim(
            session_factory,
            claim,
            reason="prazo_processamento_expirado",
            ambiguous=False,
            expire_for_purge=True,
            now=current,
        )
        return None
    deadline_at = time.monotonic() + min(float(_AUDIO_LEASE_SECONDS), remaining_lease)
    storage_attempted = False

    def denied_before_external() -> None:
        if storage_attempted:
            _reopen_audio_purge_after_late_upload(session_factory, claim)
        _terminalize_audio_claim(
            session_factory,
            claim,
            reason="contexto_revogado",
            ambiguous=False,
            expire_for_purge=storage_attempted,
        )

    def report_progress() -> None:
        if progress_callback is not None:
            progress_callback()

    try:
        report_progress()
        authorized = _audio_claim_still_authorized(session_factory, claim)
        if authorized is None:
            authorized = _wait_for_audio_authorization(
                session_factory,
                claim,
                deadline_at=deadline_at,
                progress_callback=progress_callback,
            )
        if not authorized:
            denied_before_external()
            return None
        raw, remote_mime = _run_audio_boundary(
            lambda: evolution_client.get_audio_media_bytes_limited(
                claim.instance,
                _audio_media_key(claim),
                max_bytes=CELL_REPORT_AUDIO_MAX_BYTES,
                timeout_seconds=_remaining_audio_seconds(deadline_at, cap=30.0),
            ),
            deadline_at=deadline_at,
            progress_callback=progress_callback,
        )
        report_progress()
        measured_mime = canonical_audio_mime(remote_mime)
        if measured_mime is None or measured_mime != claim.declared_mime:
            raise CellReportAudioServiceError("mídia de áudio indisponível")
        decoded = _run_audio_boundary(
            lambda: decoder(
                raw,
                declared_mime=measured_mime,
                timeout_seconds=_remaining_audio_seconds(
                    deadline_at,
                    cap=CELL_REPORT_AUDIO_DECODER_DEADLINE_SECONDS,
                ),
            ),
            deadline_at=deadline_at,
            progress_callback=progress_callback,
        )
        if not isinstance(decoded, DecodedAudio):
            raise CellReportAudioServiceError("mídia de áudio indisponível")
        authorized = _audio_claim_still_authorized(session_factory, claim)
        if authorized is None:
            authorized = _wait_for_audio_authorization(
                session_factory,
                claim,
                deadline_at=deadline_at,
                progress_callback=progress_callback,
            )
        if not authorized:
            denied_before_external()
            return None
        storage_attempted = True
        stored = _run_audio_boundary(
            lambda: storage.upload_cell_report_audio(
                igreja_id=claim.igreja_id,
                provider_message_sha256=claim.provider_message_sha256,
                mime_type=decoded.mime_type,
                raw=raw,
                deadline_seconds=_remaining_audio_seconds(deadline_at, cap=30.0),
            ),
            deadline_at=deadline_at,
            progress_callback=progress_callback,
        )
        report_progress()
        from app.services.storage import cell_report_audio_storage_path

        expected_path = cell_report_audio_storage_path(
            claim.igreja_id,
            claim.provider_message_sha256,
            decoded.mime_type,
        )
        if getattr(stored, "path", None) != expected_path:
            raise CellReportAudioServiceError("armazenamento de áudio indisponível")
        authorized = _audio_claim_still_authorized(session_factory, claim)
        if authorized is None:
            authorized = _wait_for_audio_authorization(
                session_factory,
                claim,
                deadline_at=deadline_at,
                progress_callback=progress_callback,
            )
        if not authorized:
            denied_before_external()
            return None
        while True:
            try:
                reservation = reserve_audio_transcription_budget(
                    session_factory,
                    claim,
                    duration_seconds=decoded.duration_seconds,
                )
                break
            except _AudioClaimBusy:
                if not _wait_for_audio_authorization(
                    session_factory,
                    claim,
                    deadline_at=deadline_at,
                    progress_callback=progress_callback,
                ):
                    reservation = None
                    break
        if reservation is None:
            _handoff_audio_claim_after_boundary(
                session_factory,
                claim,
                deadline_at=deadline_at,
                reason="orcamento_indisponivel",
                ambiguous=False,
                storage_attempted=True,
                progress_callback=progress_callback,
            )
            return None
        authorized = _audio_claim_still_authorized(session_factory, claim)
        if authorized is None:
            authorized = _wait_for_audio_authorization(
                session_factory,
                claim,
                deadline_at=deadline_at,
                progress_callback=progress_callback,
            )
        if not authorized:
            denied_before_external()
            return None
        transcription = _run_audio_boundary(
            lambda: transcriber(
                claim.credential_provider,
                decrypt_secret(claim.credential_key_encrypted),
                audio_bytes=raw,
                mime_type=decoded.mime_type,
                filename="cell-report-audio",
                timeout_seconds=_remaining_audio_seconds(
                    deadline_at,
                    cap=CELL_REPORT_AUDIO_TRANSCRIPTION_DEADLINE_SECONDS,
                ),
                max_retries=0,
                require_real_result=True,
            ),
            deadline_at=deadline_at,
            progress_callback=progress_callback,
        )
        report_progress()
        transcript = _audio_transcript(getattr(transcription, "texto", None))
        actual_duration = getattr(transcription, "duracao_segundos", None)
        actual_cost = getattr(transcription, "custo", None)
        if _audio_estimated_microusd(actual_duration) is None:
            raise CellReportAudioServiceError("transcrição indisponível")
        if not _settle_audio_transcription_budget(
            session_factory,
            claim,
            reservation,
            actual_cost=actual_cost,
            now=_utc_now(None),
        ):
            raise CellReportAudioServiceError("custo de transcrição indisponível")
        while True:
            staged = _stage_audio_transcript(
                session_factory,
                claim,
                transcript=transcript,
                measured_mime=decoded.mime_type,
                byte_size=decoded.byte_size,
                duration_seconds=decoded.duration_seconds,
                content_sha256=decoded.content_sha256,
            )
            if staged is not _AUDIO_STAGE_DEFERRED:
                if isinstance(staged, _AudioExtractionPlan):
                    return _run_audio_extraction_provider_chain(
                        session_factory,
                        staged,
                        deadline_at=deadline_at,
                        progress_callback=progress_callback,
                    )
                return staged
            if not _wait_for_audio_authorization(
                session_factory,
                claim,
                deadline_at=deadline_at,
                progress_callback=progress_callback,
            ):
                denied_before_external()
                return None
    except CellReportAudioServiceError:
        _handoff_audio_claim_after_boundary(
            session_factory,
            claim,
            deadline_at=deadline_at,
            reason="audio_indisponivel",
            ambiguous=False,
            storage_attempted=storage_attempted,
            progress_callback=progress_callback,
        )
        return None
    except Exception:  # Provider and storage outcomes are non-repeatable.
        logger.warning("Falha externa de áudio V1b; encaminhando atendimento humano")
        _handoff_audio_claim_after_boundary(
            session_factory,
            claim,
            deadline_at=deadline_at,
            reason="externo_ambiguo",
            ambiguous=True,
            storage_attempted=storage_attempted,
            progress_callback=progress_callback,
        )
        return None


@dataclass(frozen=True, slots=True)
class _AudioReplyRetry:
    outcome: object | None
    intent: object | None
    exhausted: bool
    candidate_id: uuid.UUID | None = None


def _load_audio_pending_reply(
    session_factory: Callable[[], Session],
    igreja_id: uuid.UUID,
    *,
    now: dt.datetime,
    excluded_input_ids: tuple[uuid.UUID, ...] = (),
) -> _AudioReplyRetry:
    """Recover one durable summary transport without re-downloading audio."""

    from app.domain.agent_reply import AGENT_REPLY_PENDING
    from app.services.whatsapp_privilege import (
        PrivilegeContext,
        resolve_whatsapp_privilege_context,
    )
    from app.workers import queue_worker as qw

    session = session_factory()
    try:
        _scoped(session, igreja_id, "cell_report_audio_reply_recovery")
        output_key = literal(_AUDIO_OUTPUT_PREFIX) + func.replace(
            cast(CellReportAudioInput.id, String), "-", ""
        )
        statement = select(CellReportAudioInput.id).join(
            Message,
            and_(
                Message.igreja_id == CellReportAudioInput.igreja_id,
                Message.conversation_id == CellReportAudioInput.conversation_id,
                Message.provider_message_id == output_key,
                Message.direcao == "out",
                Message.autor == "ia",
                Message.agent_reply_state == AGENT_REPLY_PENDING,
            ),
        ).where(
            CellReportAudioInput.igreja_id == igreja_id,
            CellReportAudioInput.state == "transcrita",
            CellReportAudioInput.purge_state == "ativa",
            CellReportAudioInput.expires_at > now,
        )
        if excluded_input_ids:
            statement = statement.where(~CellReportAudioInput.id.in_(excluded_input_ids))
        input_id = session.execute(
            statement.order_by(
                CellReportAudioInput.transcribed_at.asc().nullslast(),
                CellReportAudioInput.id.asc(),
            ).limit(1)
        ).scalar_one_or_none()
        if not isinstance(input_id, uuid.UUID):
            session.commit()
            return _AudioReplyRetry(None, None, True)
        row = session.execute(
            select(CellReportAudioInput).where(
                CellReportAudioInput.igreja_id == igreja_id,
                CellReportAudioInput.id == input_id,
            )
        ).scalar_one_or_none()
        if (
            row is None
            or row.live_conversation_id is None
            or row.live_pessoa_id is None
            or row.live_message_id is None
        ):
            session.commit()
            return _AudioReplyRetry(None, None, False, input_id)
        conversation = session.execute(
            select(Conversation)
            .where(
                Conversation.igreja_id == igreja_id,
                Conversation.id == row.live_conversation_id,
                Conversation.pessoa_id == row.live_pessoa_id,
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if conversation is None:
            session.commit()
            return _AudioReplyRetry(None, None, False, input_id)
        pessoa = session.execute(
            select(Pessoa)
            .where(Pessoa.igreja_id == igreja_id, Pessoa.id == row.live_pessoa_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if pessoa is None:
            session.commit()
            return _AudioReplyRetry(None, None, False, input_id)
        locked = session.execute(
            select(CellReportAudioInput)
            .where(
                CellReportAudioInput.igreja_id == igreja_id,
                CellReportAudioInput.id == input_id,
                CellReportAudioInput.state == "transcrita",
                CellReportAudioInput.purge_state == "ativa",
                CellReportAudioInput.expires_at > now,
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if locked is None:
            session.commit()
            return _AudioReplyRetry(None, None, False, input_id)
        context = resolve_whatsapp_privilege_context(
            session,
            igreja_id=igreja_id,
            conversation_id=conversation.id,
            inbound_message_id=locked.live_message_id,
        )
        output = session.execute(
            select(Message)
            .where(
                Message.igreja_id == igreja_id,
                Message.conversation_id == conversation.id,
                Message.provider_message_id == _audio_output_provider_id(locked.id),
                Message.direcao == "out",
                Message.autor == "ia",
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if output is None:
            # ``SKIP LOCKED`` can observe an outbound reply being delivered
            # by a sibling worker.  That is not a revocation of every audio
            # item in the conversation.  Only a genuinely missing durable
            # reply invalidates this particular input.
            existing_output = session.execute(
                select(Message.id).where(
                    Message.igreja_id == igreja_id,
                    Message.conversation_id == conversation.id,
                    Message.provider_message_id == _audio_output_provider_id(locked.id),
                    Message.direcao == "out",
                    Message.autor == "ia",
                )
            ).scalar_one_or_none()
            if existing_output is not None:
                session.commit()
                return _AudioReplyRetry(None, None, False, input_id)
            _terminalize_audio_input(
                locked,
                now=now,
                reason="resumo_ausente",
                scrub_private=True,
                expire_for_purge=True,
            )
            session.commit()
            return _AudioReplyRetry(None, None, False, input_id)
        if output.agent_reply_state != AGENT_REPLY_PENDING:
            # The sent/terminal reply remains historical evidence until the
            # normal retention path removes it.  It must never cancel newer
            # audio captured for this same report.
            session.commit()
            return _AudioReplyRetry(None, None, False, input_id)
        if (
            type(context) is not PrivilegeContext
            or not audio_summary_still_authorized(
                session,
                igreja_id=igreja_id,
                conversation_id=conversation.id,
                pessoa_id=pessoa.id,
                audio_input_id=locked.id,
                now=now,
            )
        ):
            cancel_audio_inputs_for_conversation(
                session,
                igreja_id=igreja_id,
                conversation_id=conversation.id,
                reason="audio_reply_revogado",
                now=now,
            )
            session.commit()
            return _AudioReplyRetry(None, None, False, input_id)
        source_provider_id = session.execute(
            select(Message.provider_message_id).where(
                Message.igreja_id == igreja_id,
                Message.conversation_id == conversation.id,
                Message.id == locked.live_message_id,
                Message.direcao == "in",
                Message.tipo == "audio",
            )
        ).scalar_one_or_none()
        connection = session.execute(
            select(WhatsappConnection).where(
                WhatsappConnection.igreja_id == igreja_id,
                WhatsappConnection.status == "online",
            )
        ).scalar_one_or_none()
        if (
            not isinstance(source_provider_id, str)
            or not source_provider_id
            or connection is None
            or not isinstance(connection.instance, str)
            or not connection.instance
            or not isinstance(conversation.telefone, str)
            or not conversation.telefone
        ):
            cancel_audio_inputs_for_conversation(
                session,
                igreja_id=igreja_id,
                conversation_id=conversation.id,
                reason="ancora_ausente",
                now=now,
            )
            session.commit()
            return _AudioReplyRetry(None, None, False, input_id)
        outcome = qw.IngestionOutcome(
            result=qw.IngestionResult.REGISTERED,
            conversation_id=conversation.id,
            instance=connection.instance,
            telefone=conversation.telefone,
            texto=None,
            inbound=True,
            igreja_id=igreja_id,
            provider_message_id=source_provider_id,
            claim_id=f"v1b-audio:{locked.id.hex}",
            inbound_message_id=locked.live_message_id,
        )
        intent = qw._intent_from_message(output)
        session.commit()
        return _AudioReplyRetry(outcome, intent, False, input_id)
    except Exception:
        session.rollback()
        return _AudioReplyRetry(None, None, True)
    finally:
        session.close()


def dispatch_cell_report_audio_inputs(
    session_factory: Callable[[], Session],
    *,
    evolution_client: object,
    storage: object,
    decoder: Callable[..., object],
    transcriber: Callable[..., object],
    limit: int = 10,
    progress_callback: Callable[[], None] | None = None,
) -> AudioDispatchResult:
    """Claim and process a finite batch of already committed V1b inputs.

    Every provider boundary starts only after the claim and budget reservation
    commit.  The result re-enters the existing outbound agent ledger rather
    than fabricating a WhatsApp inbound or directly sending a response.
    """

    if type(limit) is not int or isinstance(limit, bool) or limit <= 0:
        return AudioDispatchResult(0, 0)
    from app.services.outbound_guard import external_sends_allowed
    from app.workers import queue_worker as qw

    claimed = 0
    completed = 0
    recovered = recover_expired_audio_handoffs(session_factory, limit=limit)
    completed += recovered
    remaining = limit - recovered
    tenants = _discover_audio_tenants(session_factory)
    if not external_sends_allowed() or remaining <= 0:
        return AudioDispatchResult(claimed, completed)

    for tenant in tenants:
        if progress_callback is not None:
            progress_callback()
        if remaining <= 0:
            break
        if not cell_report_audio_enabled_from_environment(tenant):
            continue
        visited: list[uuid.UUID] = []
        while remaining > 0:
            if progress_callback is not None:
                progress_callback()
            retry = _load_audio_pending_reply(
                session_factory,
                tenant,
                now=_utc_now(None),
                excluded_input_ids=tuple(visited),
            )
            if retry.candidate_id is not None:
                visited.append(retry.candidate_id)
            if retry.outcome is not None and retry.intent is not None:
                remaining -= 1
                try:
                    qw._deliver_agent_reply_intent(
                        session_factory,
                        retry.outcome,
                        retry.intent,
                        None,
                        evolution_client=evolution_client,
                    )
                except qw.AgentReplyRetryable:
                    pass
                completed += 1
                continue
            if retry.exhausted:
                # No already-transcribed reply needs a transport retry.  New
                # inputs below still get their own finite claim attempt.
                pass
            attempt = _claim_next_audio_input(
                session_factory,
                tenant,
                now=_utc_now(None),
                excluded_input_ids=tuple(visited),
            )
            if attempt.exhausted:
                break
            if attempt.candidate_id is not None:
                visited.append(attempt.candidate_id)
            if attempt.claim is None:
                continue
            claimed += 1
            remaining -= 1
            intent = _run_audio_provider_chain(
                session_factory,
                attempt.claim,
                evolution_client=evolution_client,
                storage=storage,
                decoder=decoder,
                transcriber=transcriber,
                progress_callback=progress_callback,
            )
            if intent is None:
                completed += 1
                continue
            outcome = _audio_dispatch_outcome(attempt.claim)
            try:
                qw._deliver_agent_reply_intent(
                    session_factory,
                    outcome,
                    intent,
                    None,
                    evolution_client=evolution_client,
                )
            except qw.AgentReplyRetryable:
                # The durable outbound intent is pending; a later worker tick
                # can retry transport without downloading or transcribing again.
                pass
            completed += 1
    return AudioDispatchResult(claimed, completed)


@dataclass(frozen=True, slots=True)
class _AudioPurgeClaim:
    igreja_id: uuid.UUID
    input_id: uuid.UUID
    storage_path: str
    purge_attempt: int


def _claim_audio_purge(
    session_factory: Callable[[], Session],
    igreja_id: uuid.UUID,
    *,
    now: dt.datetime,
    excluded_input_ids: tuple[uuid.UUID, ...],
) -> tuple[_AudioPurgeClaim | None, bool, uuid.UUID | None]:
    """Commit a purge lease without holding database locks across storage I/O."""

    session = session_factory()
    try:
        _scoped(session, igreja_id, "cell_report_audio_purge_claim")
        statement = select(CellReportAudioInput.id).where(
            CellReportAudioInput.igreja_id == igreja_id,
            CellReportAudioInput.purge_state.in_(("ativa", "pendente")),
            CellReportAudioInput.expires_at <= now,
            CellReportAudioInput.state != "processando",
        )
        if excluded_input_ids:
            statement = statement.where(~CellReportAudioInput.id.in_(excluded_input_ids))
        input_id = session.execute(
            statement.order_by(
                CellReportAudioInput.expires_at.asc(),
                CellReportAudioInput.id.asc(),
            ).limit(1)
        ).scalar_one_or_none()
        if type(input_id) is not uuid.UUID:
            session.commit()
            return None, True, None
        row = session.execute(
            select(CellReportAudioInput).where(
                CellReportAudioInput.igreja_id == igreja_id,
                CellReportAudioInput.id == input_id,
            )
        ).scalar_one_or_none()
        if row is None:
            session.commit()
            return None, False, input_id
        # Match the durable report prefix before mutating the input.  A live
        # in-flight provider operation keeps its lease and is revisited later.
        if row.live_conversation_id is not None:
            session.execute(
                select(Conversation)
                .where(
                    Conversation.igreja_id == igreja_id,
                    Conversation.id == row.live_conversation_id,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
        if row.live_pessoa_id is not None:
            session.execute(
                select(Pessoa)
                .where(
                    Pessoa.igreja_id == igreja_id,
                    Pessoa.id == row.live_pessoa_id,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
        locked = session.execute(
            select(CellReportAudioInput)
            .where(
                CellReportAudioInput.igreja_id == igreja_id,
                CellReportAudioInput.id == input_id,
                CellReportAudioInput.purge_state.in_(("ativa", "pendente")),
                CellReportAudioInput.expires_at <= now,
                CellReportAudioInput.state != "processando",
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if locked is None:
            session.commit()
            return None, False, input_id
        if locked.state not in {"ambigua", "cancelada", "purgada"}:
            _terminalize_audio_input(locked, now=now, reason="retencao_expirada")
        locked.purge_state = "pendente"
        locked.purge_attempts += 1
        locked.purge_error_code = None
        locked.transcript_text = None
        locked.transcript_sha256 = None
        locked.updated_at = now
        session.commit()
        return _AudioPurgeClaim(
            igreja_id,
            locked.id,
            locked.storage_path,
            locked.purge_attempts,
        ), False, input_id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _finish_audio_purge(
    session_factory: Callable[[], Session],
    claim: _AudioPurgeClaim,
    *,
    now: dt.datetime,
    removed: bool,
) -> None:
    session = session_factory()
    try:
        _scoped(session, claim.igreja_id, "cell_report_audio_purge_finish")
        row = session.execute(
            select(CellReportAudioInput)
            .where(
                CellReportAudioInput.igreja_id == claim.igreja_id,
                CellReportAudioInput.id == claim.input_id,
                CellReportAudioInput.purge_state == "pendente",
                CellReportAudioInput.purge_attempts == claim.purge_attempt,
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if row is None:
            session.commit()
            return
        if not removed:
            row.purge_error_code = "storage_unavailable"
            row.updated_at = now
            session.commit()
            return
        if row.live_conversation_id is not None and row.live_message_id is not None:
            message = session.execute(
                select(Message)
                .where(
                    Message.igreja_id == claim.igreja_id,
                    Message.conversation_id == row.live_conversation_id,
                    Message.id == row.live_message_id,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if message is not None and message.media_path == claim.storage_path:
                message.media_path = None
        row.state = "purgada"
        row.purge_state = "purgada"
        row.content_purged_at = now
        row.transcript_text = None
        row.transcript_sha256 = None
        row.purge_error_code = None
        row.updated_at = now
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def purge_cell_report_audio_inputs(
    session_factory: Callable[[], Session],
    *,
    storage: object,
    now: dt.datetime | None = None,
    limit: int = 100,
) -> int:
    """Purge expired V1b private content even after feature gates close.

    The durable input tombstone is retained for replay suppression.  Storage
    removal is idempotent and happens strictly between two closed sessions, so
    a failed provider call leaves a recoverable ``pendente`` purge marker.
    """

    if type(limit) is not int or isinstance(limit, bool) or limit <= 0:
        return 0
    # Direct callers of maintenance get the same durable human fence as the
    # cron path. Without this ordering an expired processando row could be
    # scrubbed before its failed provider boundary reaches human attention.
    recover_expired_audio_handoffs(session_factory, now=now, limit=limit)
    current = _utc_now(now)
    purged = 0
    delayed = 0
    remaining = limit
    for tenant in _discover_audio_tenants(session_factory):
        if remaining <= 0:
            break
        visited: list[uuid.UUID] = []
        while remaining > 0:
            claim, exhausted, candidate_id = _claim_audio_purge(
                session_factory,
                tenant,
                now=current,
                excluded_input_ids=tuple(visited),
            )
            if exhausted:
                break
            if candidate_id is not None:
                visited.append(candidate_id)
            if claim is None:
                continue
            removed = False
            try:
                storage.remove_tenant_media(claim.igreja_id, [claim.storage_path])
                removed = True
            except Exception:  # Physical cleanup remains pending for retry.
                delayed += 1
            _finish_audio_purge(
                session_factory,
                claim,
                now=_utc_now(now),
                removed=removed,
            )
            if removed:
                purged += 1
            remaining -= 1
    if delayed:
        logger.warning(
            "Limpeza de áudio V1b atrasada",
            extra={"event": "cell_report_audio_purge_delayed", "count": delayed},
        )
    return purged


__all__ = (
    "AUDIO_CONSENT_NOTICE_TEXT",
    "AudioConsentResult",
    "AudioDispatchResult",
    "AudioInputClaim",
    "AudioInputEnqueueResult",
    "AudioBudgetReservation",
    "CellReportAudioServiceError",
    "audio_capture_scope_allows",
    "audio_notice_required_for_inbound",
    "audio_schema_available",
    "audio_notice_still_pending",
    "audio_summary_still_authorized",
    "dispatch_cell_report_audio_inputs",
    "enqueue_audio_input_after_inbound",
    "find_audio_input_by_provider",
    "invalidate_audio_consent_notice",
    "mark_audio_consent_notice_delivered",
    "prepare_audio_consent_notice",
    "record_audio_consent_command",
    "recover_expired_audio_handoffs",
    "reserve_audio_transcription_budget",
    "purge_cell_report_audio_inputs",
)
