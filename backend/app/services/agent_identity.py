"""Tenant-bound, locally confirmed identity proofs for the S3 readonly seam.

The challenge is only a correlator for an inbound message.  It becomes useful
only after a current panel session consumes it into an HMAC-protected proof.
This module deliberately has no provider, runtime, catalog or writer logic.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import math
import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.agent.masking import log_agent_event
from app.config import get_settings
from app.db.models import (
    AgentConfig,
    AgentIdentityChallenge,
    AgentIdentityProof,
    AppUser,
    Celula,
    ConsentRecord,
    Conversation,
    Igreja,
    Message,
    Pessoa,
    UserRole,
)
from app.db.rls import set_tenant_context
from app.db.rls_observability import require_tenant_scope
from app.deps import BLOCKING_IGREJA_STATUSES
from app.domain import consent as consent_rules


_HMAC_DOMAIN = "pastorai:s3:identity-proof:v1"
_CREDENTIAL_FINGERPRINT_DOMAIN = "pastorai:s3:identity-credential:v1"
_ROLES_FINGERPRINT_DOMAIN = "pastorai:s3:identity-roles:v1"
_CHALLENGE_TTL = dt.timedelta(minutes=5)
_PROOF_TTL = dt.timedelta(minutes=15)
_PASSWORD_CHANGE_CLOCK_SKEW = dt.timedelta(seconds=5)
_AUDIT_FLOW_VERSION = "s3_identity_v1"
_AUDIT_EVENT_CHALLENGE = "agent_identity_challenge"
_AUDIT_EVENT_CONFIRMATION = "agent_identity_confirmation"


class AgentIdentityError(RuntimeError):
    """Base for failures that must not disclose challenge existence."""


class AgentIdentityIssueDenied(AgentIdentityError):
    """The inbound anchor cannot receive a challenge."""


class AgentIdentityConfirmationDenied(AgentIdentityError):
    """The panel request cannot consume a challenge."""

    def __init__(self, message: str = "confirmação indisponível", *, audit_logged: bool = False):
        super().__init__(message)
        self.audit_logged = audit_logged


@dataclass(frozen=True)
class ProofIntegrityInput:
    """All persisted values whose relationship is integrity protected."""

    challenge_id: uuid.UUID
    igreja_id: uuid.UUID
    app_user_id: uuid.UUID
    pessoa_id: uuid.UUID
    conversation_id: uuid.UUID
    confirmed_at: dt.datetime
    confirmed_until: dt.datetime
    credential_fingerprint: str
    roles_fingerprint: str


@dataclass(frozen=True)
class IssuedIdentityChallenge:
    """Opaque correlator returned only to the future trusted inbound path."""

    challenge: str
    expires_at: dt.datetime
    sequence: int


@dataclass(frozen=True)
class IdentityConfirmation:
    """Non-sensitive result of consuming one identity challenge."""

    confirmed_until: dt.datetime


@dataclass(frozen=True)
class ConfirmedIdentityContext:
    """Server-owned facts usable by a future S3 readonly catalog only."""

    igreja_id: uuid.UUID
    conversation_id: uuid.UUID
    pessoa_id: uuid.UUID
    app_user_id: uuid.UUID
    proof_id: uuid.UUID
    roles: frozenset[str]
    confirmed_until: dt.datetime
    owned_cell_ids: tuple[uuid.UUID, ...]


def _require_uuid(value: object) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        raise ValueError("uuid server-side válido é obrigatório")
    return value


def _utc_datetime(value: object) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None:
        raise ValueError("timestamp timezone-aware é obrigatório")
    return value.astimezone(dt.timezone.utc)


def _now(value: dt.datetime | None) -> dt.datetime:
    return _utc_datetime(value or dt.datetime.now(dt.timezone.utc))


def _audit_identity_event(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    evento: str,
    result: str,
    started_at: float,
) -> None:
    """Persist only fixed audit metadata, never a correlator or identity snapshot."""

    elapsed_ms = max(0, int((time.monotonic() - started_at) * 1000))
    log_agent_event(
        session,
        igreja_id=igreja_id,
        evento=evento,
        payload={
            "flow_version": _AUDIT_FLOW_VERSION,
            "result": result,
            "latency_ms": elapsed_ms,
        },
        conversation_id=conversation_id,
    )


def _deny_confirmation(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    started_at: float,
    result: str = "rejected",
) -> None:
    _audit_identity_event(
        session,
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        evento=_AUDIT_EVENT_CONFIRMATION,
        result=result,
        started_at=started_at,
    )
    raise AgentIdentityConfirmationDenied(audit_logged=True)


def _require_secret(secret: object) -> bytes:
    if not isinstance(secret, str) or not secret:
        raise ValueError("session secret efetivo é obrigatório")
    return secret.encode("utf-8")


def _encode_typed_fields(fields: Iterable[tuple[str, str, str]]) -> bytes:
    """Length-prefix typed UTF-8 fields so HMAC inputs cannot concatenate ambiguously."""

    material = bytearray()
    for name, kind, value in fields:
        for part in (name, kind, value):
            encoded = part.encode("utf-8")
            material.extend(len(encoded).to_bytes(4, byteorder="big"))
            material.extend(encoded)
    return bytes(material)


def _hmac_hex(secret: str, domain: str, fields: Iterable[tuple[str, str, str]]) -> str:
    material = _encode_typed_fields(
        (("domain", "text", domain), *tuple(fields))
    )
    return hmac.new(_require_secret(secret), material, hashlib.sha256).hexdigest()


def _canonical_datetime(value: object) -> str:
    return _utc_datetime(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hmac_text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} válido é obrigatório")
    return value


def parse_challenge_code(value: object) -> uuid.UUID | None:
    """Accept only the lowercase RFC 4122 UUID spelling emitted by this service."""

    if not isinstance(value, str):
        return None
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        return None
    if parsed.int == 0 or str(parsed) != value:
        return None
    return parsed


def build_credential_fingerprint(
    secret: str,
    *,
    clerk_user_id: str,
    password_changed_at: dt.datetime | None,
) -> str:
    """Fingerprint the current locally verified panel credential snapshot."""

    changed = "none" if password_changed_at is None else _canonical_datetime(password_changed_at)
    return _hmac_hex(
        secret,
        _CREDENTIAL_FINGERPRINT_DOMAIN,
        (
            ("clerk_user_id", "text", _hmac_text(clerk_user_id, name="clerk_user_id")),
            ("password_changed_at", "datetime-or-none", changed),
        ),
    )


def build_roles_fingerprint(
    secret: str,
    *,
    roles: Iterable[tuple[uuid.UUID, str]],
) -> str:
    """Fingerprint exact UserRole rows, including IDs to detect reinsertion."""

    normalized: list[tuple[str, str]] = []
    for role_id, papel in roles:
        normalized.append((str(_require_uuid(role_id)), _hmac_text(papel, name="papel")))
    normalized.sort()
    if len(normalized) != len(set(normalized)):
        raise ValueError("papéis duplicados não compõem um snapshot válido")
    fields: list[tuple[str, str, str]] = [("role_count", "integer", str(len(normalized)))]
    for index, (role_id, papel) in enumerate(normalized):
        fields.extend(
            (
                (f"role_{index}_id", "uuid", role_id),
                (f"role_{index}_papel", "text", papel),
            )
        )
    return _hmac_hex(secret, _ROLES_FINGERPRINT_DOMAIN, fields)


def build_proof_integrity_hmac(secret: str, value: ProofIntegrityInput) -> str:
    """Bind every persisted proof relation and current authorization snapshot."""

    if type(value) is not ProofIntegrityInput:
        raise ValueError("proof input tipado é obrigatório")
    return _hmac_hex(
        secret,
        _HMAC_DOMAIN,
        (
            ("challenge_id", "uuid", str(_require_uuid(value.challenge_id))),
            ("igreja_id", "uuid", str(_require_uuid(value.igreja_id))),
            ("app_user_id", "uuid", str(_require_uuid(value.app_user_id))),
            ("pessoa_id", "uuid", str(_require_uuid(value.pessoa_id))),
            ("conversation_id", "uuid", str(_require_uuid(value.conversation_id))),
            ("confirmed_at", "datetime", _canonical_datetime(value.confirmed_at)),
            ("confirmed_until", "datetime", _canonical_datetime(value.confirmed_until)),
            (
                "credential_fingerprint",
                "sha256-hex",
                _hmac_text(value.credential_fingerprint, name="credential_fingerprint"),
            ),
            (
                "roles_fingerprint",
                "sha256-hex",
                _hmac_text(value.roles_fingerprint, name="roles_fingerprint"),
            ),
        ),
    )


def verify_proof_integrity_hmac(
    secret: str,
    value: ProofIntegrityInput,
    integrity_hmac: object,
) -> bool:
    if not isinstance(integrity_hmac, str) or len(integrity_hmac) != 64:
        return False
    try:
        expected = build_proof_integrity_hmac(secret, value)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(expected, integrity_hmac)


def _locked_one_or_none(session: Session, statement):
    return session.execute(
        statement.with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _role_snapshot(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    app_user_id: uuid.UUID,
    lock: bool,
) -> tuple[tuple[uuid.UUID, str], ...] | None:
    statement = (
        select(UserRole)
        .where(
            UserRole.igreja_id == igreja_id,
            UserRole.user_id == app_user_id,
        )
        .order_by(UserRole.id.asc())
    )
    if lock:
        statement = statement.with_for_update(of=UserRole).execution_options(
            populate_existing=True
        )
    roles = list(session.execute(statement).scalars().all())
    snapshot: list[tuple[uuid.UUID, str]] = []
    for role in roles:
        if (
            type(role.id) is not uuid.UUID
            or role.igreja_id != igreja_id
            or role.user_id != app_user_id
            or not isinstance(role.papel, str)
            or not role.papel
        ):
            return None
        snapshot.append((role.id, role.papel))
    return tuple(snapshot)


def _panel_session_issued_at(claims: Mapping[str, Any]) -> dt.datetime:
    value = claims.get("iat")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AgentIdentityConfirmationDenied("sessão sem iat válido")
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise AgentIdentityConfirmationDenied("sessão sem iat válido") from exc
    if not math.isfinite(numeric):
        raise AgentIdentityConfirmationDenied("sessão sem iat válido")
    try:
        return dt.datetime.fromtimestamp(numeric, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise AgentIdentityConfirmationDenied("sessão sem iat válido") from exc


def _panel_session_expires_at(claims: Mapping[str, Any]) -> dt.datetime:
    value = claims.get("exp")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AgentIdentityConfirmationDenied("sessão sem exp válido")
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise AgentIdentityConfirmationDenied("sessão sem exp válido") from exc
    if not math.isfinite(numeric):
        raise AgentIdentityConfirmationDenied("sessão sem exp válido")
    try:
        return dt.datetime.fromtimestamp(numeric, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise AgentIdentityConfirmationDenied("sessão sem exp válido") from exc


def _session_matches_password_snapshot(
    app_user: AppUser,
    claims: Mapping[str, Any],
) -> bool:
    try:
        issued_at = _panel_session_issued_at(claims)
    except AgentIdentityConfirmationDenied:
        return False
    changed_at = app_user.password_changed_at
    if changed_at is None:
        return True
    try:
        return issued_at >= _utc_datetime(changed_at) - _PASSWORD_CHANGE_CLOCK_SKEW
    except ValueError:
        return False


def _session_is_current(claims: Mapping[str, Any], *, at: dt.datetime) -> bool:
    try:
        return _panel_session_expires_at(claims) > _utc_datetime(at)
    except (AgentIdentityConfirmationDenied, ValueError):
        return False


def _require_scope(session: Session, igreja_id: uuid.UUID, *, clerk_user_id: str | None) -> None:
    if clerk_user_id is not None:
        # ``request.jwt.claims`` is transaction-local.  The seam restores only
        # tenant + role after a fresh BEGIN, so the server-verified sub is
        # deliberately reapplied before policies that distinguish panel users.
        set_tenant_context(session, clerk_user_id)
    require_tenant_scope(
        session,
        expected_igreja_id=igreja_id,
        source="agent_identity",
    )


def issue_identity_challenge(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    inbound_message_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> IssuedIdentityChallenge:
    """Issue or replay one inbound-bound challenge under the Conversation lock.

    Runtime integration will call this only after its deterministic consent and
    configuration gates.  This service independently binds the persisted
    inbound anchor and rejects an archived, opted-out, human-owned or malformed
    conversation so a direct caller cannot mint a useful correlation elsewhere.
    """

    igreja_id = _require_uuid(igreja_id)
    conversation_id = _require_uuid(conversation_id)
    inbound_message_id = _require_uuid(inbound_message_id)
    started_at = time.monotonic()
    _require_scope(session, igreja_id, clerk_user_id=None)

    conversation = _locked_one_or_none(
        session,
        select(Conversation).where(
            Conversation.igreja_id == igreja_id,
            Conversation.id == conversation_id,
        ),
    )
    if (
        conversation is None
        or conversation.igreja_id != igreja_id
        or conversation.id != conversation_id
        or type(conversation.pessoa_id) is not uuid.UUID
        or conversation.estado == "humano"
        or conversation.assumido_por is not None
    ):
        raise AgentIdentityIssueDenied("conversa inelegível")

    pessoa = _locked_one_or_none(
        session,
        select(Pessoa).where(
            Pessoa.igreja_id == igreja_id,
            Pessoa.id == conversation.pessoa_id,
        ),
    )
    if (
        pessoa is None
        or pessoa.id != conversation.pessoa_id
        or pessoa.arquivada_em is not None
        or pessoa.optout
        or pessoa.sem_interesse
    ):
        raise AgentIdentityIssueDenied("pessoa inelegível")

    inbound = session.execute(
        select(Message).where(
            Message.igreja_id == igreja_id,
            Message.id == inbound_message_id,
            Message.conversation_id == conversation_id,
            Message.direcao == "in",
        )
    ).scalar_one_or_none()
    if inbound is None:
        raise AgentIdentityIssueDenied("âncora inbound ausente")

    existing = _locked_one_or_none(
        session,
        select(AgentIdentityChallenge).where(
            AgentIdentityChallenge.igreja_id == igreja_id,
            AgentIdentityChallenge.issued_from_message_id == inbound_message_id,
        ),
    )
    if existing is not None:
        if (
            existing.conversation_id != conversation_id
            or existing.pessoa_id != pessoa.id
            or existing.issued_from_message_id != inbound_message_id
        ):
            raise AgentIdentityIssueDenied("correlacionador inconsistente")
        return IssuedIdentityChallenge(
            challenge=str(existing.id),
            expires_at=_utc_datetime(existing.challenge_expires_at),
            sequence=int(existing.sequence),
        )

    prior = session.execute(
        select(AgentIdentityChallenge.sequence)
        .where(
            AgentIdentityChallenge.igreja_id == igreja_id,
            AgentIdentityChallenge.conversation_id == conversation_id,
        )
        .order_by(desc(AgentIdentityChallenge.sequence))
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()
    sequence = int(prior or 0) + 1
    issued_at = _now(now)
    challenge = AgentIdentityChallenge(
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        pessoa_id=pessoa.id,
        issued_from_message_id=inbound_message_id,
        issued_at=issued_at,
        challenge_expires_at=issued_at + _CHALLENGE_TTL,
        sequence=sequence,
    )
    session.add(challenge)
    session.flush()
    _audit_identity_event(
        session,
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        evento=_AUDIT_EVENT_CHALLENGE,
        result="issued",
        started_at=started_at,
    )
    return IssuedIdentityChallenge(
        challenge=str(challenge.id),
        expires_at=challenge.challenge_expires_at,
        sequence=sequence,
    )


def confirm_identity_challenge(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    app_user_id: uuid.UUID,
    clerk_user_id: str,
    session_claims: Mapping[str, Any],
    challenge: object,
    session_secret: str,
    now: dt.datetime | None = None,
) -> IdentityConfirmation:
    """Atomically consume the latest challenge after a local panel JWT check."""

    igreja_id = _require_uuid(igreja_id)
    app_user_id = _require_uuid(app_user_id)
    challenge_id = parse_challenge_code(challenge)
    if challenge_id is None or not isinstance(session_claims, Mapping):
        raise AgentIdentityConfirmationDenied("confirmação inválida")
    _hmac_text(clerk_user_id, name="clerk_user_id")
    started_at = time.monotonic()
    _require_scope(session, igreja_id, clerk_user_id=clerk_user_id)

    # Read once only to identify the Conversation lock.  It is reloaded under
    # that lock before any decision, preserving Conversation -> downstream order.
    candidate = session.execute(
        select(AgentIdentityChallenge).where(
            AgentIdentityChallenge.igreja_id == igreja_id,
            AgentIdentityChallenge.id == challenge_id,
        )
    ).scalar_one_or_none()
    if candidate is None or candidate.igreja_id != igreja_id:
        _deny_confirmation(
            session,
            igreja_id=igreja_id,
            conversation_id=None,
            started_at=started_at,
        )

    conversation = _locked_one_or_none(
        session,
        select(Conversation).where(
            Conversation.igreja_id == igreja_id,
            Conversation.id == candidate.conversation_id,
        ),
    )
    if (
        conversation is None
        or conversation.pessoa_id != candidate.pessoa_id
        or conversation.estado == "humano"
        or conversation.assumido_por is not None
    ):
        _deny_confirmation(
            session,
            igreja_id=igreja_id,
            conversation_id=candidate.conversation_id,
            started_at=started_at,
        )

    current = _locked_one_or_none(
        session,
        select(AgentIdentityChallenge).where(
            AgentIdentityChallenge.igreja_id == igreja_id,
            AgentIdentityChallenge.id == challenge_id,
        ),
    )
    newest = session.execute(
        select(AgentIdentityChallenge)
        .where(
            AgentIdentityChallenge.igreja_id == igreja_id,
            AgentIdentityChallenge.conversation_id == conversation.id,
        )
        .order_by(desc(AgentIdentityChallenge.sequence))
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()
    if current is None or current.pessoa_id != conversation.pessoa_id:
        _deny_confirmation(
            session,
            igreja_id=igreja_id,
            conversation_id=conversation.id,
            started_at=started_at,
        )
    if newest is None or newest.id != current.id:
        _deny_confirmation(
            session,
            igreja_id=igreja_id,
            conversation_id=conversation.id,
            started_at=started_at,
            result="substituted",
        )

    existing_proof = _locked_one_or_none(
        session,
        select(AgentIdentityProof).where(AgentIdentityProof.challenge_id == current.id),
    )
    if existing_proof is not None:
        _deny_confirmation(
            session,
            igreja_id=igreja_id,
            conversation_id=conversation.id,
            started_at=started_at,
        )

    pessoa = _locked_one_or_none(
        session,
        select(Pessoa).where(
            Pessoa.igreja_id == igreja_id,
            Pessoa.id == current.pessoa_id,
        ),
    )
    if (
        pessoa is None
        or pessoa.arquivada_em is not None
        or pessoa.optout
        or pessoa.sem_interesse
    ):
        _deny_confirmation(
            session,
            igreja_id=igreja_id,
            conversation_id=conversation.id,
            started_at=started_at,
        )

    usable_users = list(
        session.execute(
            select(AppUser)
            .where(
                AppUser.igreja_id == igreja_id,
                AppUser.pessoa_id == pessoa.id,
                AppUser.status == "ativo",
                AppUser.clerk_user_id.is_not(None),
            )
            .order_by(AppUser.id.asc())
            .limit(2)
            .with_for_update(of=AppUser)
            .execution_options(populate_existing=True)
        ).scalars().all()
    )
    if len(usable_users) != 1:
        _deny_confirmation(
            session,
            igreja_id=igreja_id,
            conversation_id=conversation.id,
            started_at=started_at,
        )
    app_user = usable_users[0]
    if (
        app_user.id != app_user_id
        or app_user.clerk_user_id != clerk_user_id
    ):
        _deny_confirmation(
            session,
            igreja_id=igreja_id,
            conversation_id=conversation.id,
            started_at=started_at,
        )

    roles = _role_snapshot(
        session,
        igreja_id=igreja_id,
        app_user_id=app_user.id,
        lock=True,
    )
    if roles is None:
        _deny_confirmation(
            session,
            igreja_id=igreja_id,
            conversation_id=conversation.id,
            started_at=started_at,
        )
    confirmed_at = _now(now)
    try:
        challenge_expires_at = _utc_datetime(current.challenge_expires_at)
    except ValueError:
        _deny_confirmation(
            session,
            igreja_id=igreja_id,
            conversation_id=conversation.id,
            started_at=started_at,
        )
    if challenge_expires_at <= confirmed_at or not _session_is_current(
        session_claims,
        at=confirmed_at,
    ):
        _deny_confirmation(
            session,
            igreja_id=igreja_id,
            conversation_id=conversation.id,
            started_at=started_at,
            result="expired",
        )
    if not _session_matches_password_snapshot(app_user, session_claims):
        _deny_confirmation(
            session,
            igreja_id=igreja_id,
            conversation_id=conversation.id,
            started_at=started_at,
        )
    credential_fingerprint = build_credential_fingerprint(
        session_secret,
        clerk_user_id=clerk_user_id,
        password_changed_at=app_user.password_changed_at,
    )
    roles_fingerprint = build_roles_fingerprint(session_secret, roles=roles)
    confirmed_until = confirmed_at + _PROOF_TTL
    integrity_input = ProofIntegrityInput(
        challenge_id=current.id,
        igreja_id=igreja_id,
        app_user_id=app_user.id,
        pessoa_id=pessoa.id,
        conversation_id=conversation.id,
        confirmed_at=confirmed_at,
        confirmed_until=confirmed_until,
        credential_fingerprint=credential_fingerprint,
        roles_fingerprint=roles_fingerprint,
    )
    proof = AgentIdentityProof(
        igreja_id=igreja_id,
        challenge_id=current.id,
        conversation_id=conversation.id,
        pessoa_id=pessoa.id,
        confirmed_by_app_user_id=app_user.id,
        confirmed_at=confirmed_at,
        confirmed_until=confirmed_until,
        credential_fingerprint=credential_fingerprint,
        roles_fingerprint=roles_fingerprint,
        integrity_hmac=build_proof_integrity_hmac(session_secret, integrity_input),
    )
    session.add(proof)
    session.flush()
    _audit_identity_event(
        session,
        igreja_id=igreja_id,
        conversation_id=conversation.id,
        evento=_AUDIT_EVENT_CONFIRMATION,
        result="confirmed",
        started_at=started_at,
    )
    return IdentityConfirmation(confirmed_until=confirmed_until)


def _latest_consent_version(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
) -> str | None:
    record = session.execute(
        select(ConsentRecord)
        .where(
            ConsentRecord.igreja_id == igreja_id,
            ConsentRecord.pessoa_id == pessoa_id,
        )
        .order_by(ConsentRecord.aceite_em.desc().nullslast(), ConsentRecord.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return record.termo_versao if record is not None else None


def resolve_confirmed_identity(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    session_secret: str | None = None,
    now: dt.datetime | None = None,
    term_version: str | None = None,
) -> ConfirmedIdentityContext | None:
    """Return one current readonly identity context or fail closed with ``None``.

    This revalidates mutable access, tenant, conversation and consent gates on
    every caller invocation.  It has no panel JWT and never inserts a proof.
    """

    effective_secret = (
        session_secret
        if session_secret is not None
        else get_settings().effective_session_secret
    )
    try:
        igreja_id = _require_uuid(igreja_id)
        conversation_id = _require_uuid(conversation_id)
        resolved_at = _now(now)
        _require_scope(session, igreja_id, clerk_user_id=None)
    except (TypeError, ValueError):
        return None

    conversation = session.execute(
        select(Conversation).where(
            Conversation.igreja_id == igreja_id,
            Conversation.id == conversation_id,
        )
    ).scalar_one_or_none()
    if (
        conversation is None
        or conversation.igreja_id != igreja_id
        or conversation.id != conversation_id
        or type(conversation.pessoa_id) is not uuid.UUID
        or conversation.estado == "humano"
        or conversation.assumido_por is not None
    ):
        return None

    igreja = session.execute(select(Igreja).where(Igreja.id == igreja_id)).scalar_one_or_none()
    if igreja is None or igreja.id != igreja_id or igreja.status in BLOCKING_IGREJA_STATUSES:
        return None
    pessoa = session.execute(
        select(Pessoa).where(
            Pessoa.igreja_id == igreja_id,
            Pessoa.id == conversation.pessoa_id,
        )
    ).scalar_one_or_none()
    if (
        pessoa is None
        or pessoa.id != conversation.pessoa_id
        or pessoa.arquivada_em is not None
        or pessoa.optout
        or pessoa.sem_interesse
    ):
        return None
    config = session.execute(
        select(AgentConfig).where(AgentConfig.igreja_id == igreja_id)
    ).scalar_one_or_none()
    if config is None or config.igreja_id != igreja_id or config.ativo is not True:
        return None
    current_term = term_version if term_version is not None else get_settings().agent_term_version
    if not isinstance(current_term, str) or not current_term:
        return None
    if consent_rules.needs_reaccept(
        _latest_consent_version(session, igreja_id=igreja_id, pessoa_id=pessoa.id),
        current_term,
    ):
        return None

    challenge = session.execute(
        select(AgentIdentityChallenge)
        .where(
            AgentIdentityChallenge.igreja_id == igreja_id,
            AgentIdentityChallenge.conversation_id == conversation_id,
        )
        .order_by(desc(AgentIdentityChallenge.sequence))
        .limit(1)
    ).scalar_one_or_none()
    if challenge is None:
        return None
    proof = session.execute(
        select(AgentIdentityProof).where(
            AgentIdentityProof.igreja_id == igreja_id,
            AgentIdentityProof.challenge_id == challenge.id,
        )
    ).scalar_one_or_none()
    try:
        proof_until = _utc_datetime(proof.confirmed_until) if proof is not None else None
    except ValueError:
        return None
    if (
        proof is None
        or proof_until is None
        or proof_until <= resolved_at
        or proof.conversation_id != conversation_id
        or proof.pessoa_id != pessoa.id
        or proof.challenge_id != challenge.id
    ):
        return None

    usable_users = list(
        session.execute(
            select(AppUser)
            .where(
                AppUser.igreja_id == igreja_id,
                AppUser.pessoa_id == pessoa.id,
                AppUser.status == "ativo",
                AppUser.clerk_user_id.is_not(None),
            )
            .order_by(AppUser.id.asc())
            .limit(2)
        ).scalars().all()
    )
    if len(usable_users) != 1:
        return None
    app_user = usable_users[0]
    if app_user.id != proof.confirmed_by_app_user_id:
        return None
    roles = _role_snapshot(
        session,
        igreja_id=igreja_id,
        app_user_id=app_user.id,
        lock=False,
    )
    if roles is None:
        return None
    try:
        credential_fingerprint = build_credential_fingerprint(
            effective_secret,
            clerk_user_id=app_user.clerk_user_id,
            password_changed_at=app_user.password_changed_at,
        )
        roles_fingerprint = build_roles_fingerprint(effective_secret, roles=roles)
        integrity_input = ProofIntegrityInput(
            challenge_id=proof.challenge_id,
            igreja_id=proof.igreja_id,
            app_user_id=proof.confirmed_by_app_user_id,
            pessoa_id=proof.pessoa_id,
            conversation_id=proof.conversation_id,
            confirmed_at=proof.confirmed_at,
            confirmed_until=proof.confirmed_until,
            credential_fingerprint=proof.credential_fingerprint,
            roles_fingerprint=proof.roles_fingerprint,
        )
    except (TypeError, ValueError):
        return None
    if (
        credential_fingerprint != proof.credential_fingerprint
        or roles_fingerprint != proof.roles_fingerprint
        or not verify_proof_integrity_hmac(
            effective_secret,
            integrity_input,
            proof.integrity_hmac,
        )
    ):
        return None

    owned_cell_ids = tuple(
        session.execute(
            select(Celula.id)
            .where(
                Celula.igreja_id == igreja_id,
                Celula.lider_id == pessoa.id,
                Celula.ativo.is_(True),
            )
            .order_by(Celula.id.asc())
        ).scalars().all()
    )
    if any(type(cell_id) is not uuid.UUID for cell_id in owned_cell_ids):
        return None
    return ConfirmedIdentityContext(
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        pessoa_id=pessoa.id,
        app_user_id=app_user.id,
        proof_id=proof.id,
        roles=frozenset(role for _, role in roles),
        confirmed_until=proof_until,
        owned_cell_ids=owned_cell_ids,
    )
