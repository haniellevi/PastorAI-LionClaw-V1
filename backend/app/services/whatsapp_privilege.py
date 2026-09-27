"""Server-resolved WhatsApp identity and privilege facts for S3."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    AgentConfig,
    AppUser,
    Celula,
    ConsentRecord,
    Conversation,
    Igreja,
    Message,
    Pessoa,
    UserRole,
)
from app.db.rls_observability import TenantScopeError, require_tenant_scope
from app.deps import BLOCKING_IGREJA_STATUSES
from app.domain import consent as consent_rules
from app.domain.phone import normalize_phone, phone_suffix
from app.domain.purpose_consent_security import KNOWN_PANEL_ROLES


class PrivilegeResolutionKind(StrEnum):
    PUBLIC = "public"
    HUMAN_REQUIRED = "human_required"
    PRIVILEGED = "privileged"


_ALLOWED_ROLES = KNOWN_PANEL_ROLES
_CONTEXT_DOMAIN = "pastorai:s3:whatsapp-privilege-context:v1"
_CREDENTIAL_DOMAIN = "pastorai:s3:whatsapp-privilege-credential:v1"
_PHONE_DOMAIN = "pastorai:s3:whatsapp-privilege-phone:v1"
_AUTHORIZATION_DOMAIN = "pastorai:s3:whatsapp-privilege-authorization:v1"
# A listed tenant remains inert until a reviewed release is identified here.
PRIVILEGE_APPROVED_RELEASE_ID: str | None = None


def parse_privilege_role(value: object) -> str:
    if type(value) is not str or value not in _ALLOWED_ROLES:
        raise ValueError("papel inválido")
    return value


def privilege_enabled_from_environment(igreja_id: uuid.UUID) -> bool:
    """Read the empty-by-default S3 activation allowlist without DB access."""

    if type(igreja_id) is not uuid.UUID or igreja_id.int == 0:
        return False
    if (
        type(PRIVILEGE_APPROVED_RELEASE_ID) is not str
        or not PRIVILEGE_APPROVED_RELEASE_ID.strip()
    ):
        return False
    raw = os.environ.get("AGENT_PRIVILEGE_ENABLED_IGREJA_IDS", "")
    if not isinstance(raw, str) or not raw.strip():
        return False
    pieces = raw.split(",")
    if any(not piece.strip() for piece in pieces):
        return False
    try:
        allowed = tuple(uuid.UUID(piece.strip()) for piece in pieces)
    except ValueError:
        return False
    return len(allowed) == len(set(allowed)) and igreja_id in allowed


@dataclass(frozen=True, slots=True)
class PublicWhatsappContext:
    igreja_id: uuid.UUID
    conversation_id: uuid.UUID
    inbound_message_id: uuid.UUID
    kind: PrivilegeResolutionKind = PrivilegeResolutionKind.PUBLIC


@dataclass(frozen=True, slots=True)
class HumanRequiredContext:
    igreja_id: uuid.UUID
    conversation_id: uuid.UUID
    inbound_message_id: uuid.UUID
    kind: PrivilegeResolutionKind = PrivilegeResolutionKind.HUMAN_REQUIRED


@dataclass(frozen=True, slots=True)
class PrivilegeContext:
    """Immutable, server-resolved facts available to later S3 seams."""

    igreja_id: uuid.UUID
    conversation_id: uuid.UUID
    inbound_message_id: uuid.UUID
    pessoa_id: uuid.UUID
    app_user_id: uuid.UUID
    roles: frozenset[str]
    role_snapshot: tuple[tuple[uuid.UUID, str], ...]
    owned_cell_ids: tuple[uuid.UUID, ...]
    credential_fingerprint: str
    phone_fingerprint: str
    authorization_fingerprint: str
    proof_id: uuid.UUID | None
    proof_until: dt.datetime | None
    sensitive: bool
    scope_fingerprint: str
    context_fingerprint: str
    kind: PrivilegeResolutionKind = PrivilegeResolutionKind.PRIVILEGED


def _frame(parts: tuple[str, ...]) -> bytes:
    result = bytearray()
    for part in parts:
        encoded = part.encode("utf-8")
        result.extend(len(encoded).to_bytes(4, "big"))
        result.extend(encoded)
    return bytes(result)


def _canonical_datetime(value: dt.datetime | None) -> str:
    if value is None:
        return "none"
    if type(value) is not dt.datetime or value.tzinfo is None:
        raise ValueError("timestamp inválido")
    return value.astimezone(dt.timezone.utc).isoformat(timespec="microseconds")


def _scope_parts(context: PrivilegeContext) -> tuple[str, ...]:
    roles = tuple(sorted((str(role_id), role) for role_id, role in context.role_snapshot))
    cells = tuple(sorted(str(cell_id) for cell_id in context.owned_cell_ids))
    return (
        str(context.igreja_id),
        str(context.conversation_id),
        str(context.pessoa_id),
        str(context.app_user_id),
        context.credential_fingerprint,
        context.phone_fingerprint,
        context.authorization_fingerprint,
        "1" if context.sensitive else "0",
        str(context.proof_id) if context.proof_id is not None else "none",
        _canonical_datetime(context.proof_until),
        *tuple(f"role:{role_id}:{role}" for role_id, role in roles),
        *tuple(f"cell:{cell_id}" for cell_id in cells),
    )


def build_privilege_scope_fingerprint(secret: str, context: PrivilegeContext) -> str:
    """Bind mutable authority without binding the one inbound that invoked it."""

    if not isinstance(secret, str) or not secret:
        raise ValueError("segredo efetivo obrigatório")
    return hmac.new(
        secret.encode("utf-8"),
        _frame(("pastorai:s3:whatsapp-privilege-scope:v1", *_scope_parts(context))),
        hashlib.sha256,
    ).hexdigest()


def build_privilege_context_fingerprint(secret: str, context: PrivilegeContext) -> str:
    """Bind transport metadata without persisting phone, roles or proof material."""

    if not isinstance(secret, str) or not secret:
        raise ValueError("segredo efetivo obrigatório")
    scope = context.scope_fingerprint or build_privilege_scope_fingerprint(secret, context)
    parts = (
        _CONTEXT_DOMAIN,
        str(context.inbound_message_id),
        scope,
    )
    return hmac.new(secret.encode("utf-8"), _frame(parts), hashlib.sha256).hexdigest()


def _fingerprint(secret: str, domain: str, parts: Iterable[str]) -> str:
    if not isinstance(secret, str) or not secret:
        raise ValueError("segredo efetivo obrigatório")
    return hmac.new(
        secret.encode("utf-8"), _frame((domain, *tuple(parts))), hashlib.sha256
    ).hexdigest()


def _app_user_fingerprint(secret: str, app_user: AppUser) -> str:
    clerk_user_id = getattr(app_user, "clerk_user_id", None)
    pessoa_id = getattr(app_user, "pessoa_id", None)
    status = getattr(app_user, "status", None)
    if (
        type(clerk_user_id) is not str
        or not clerk_user_id
        or type(pessoa_id) is not uuid.UUID
        or type(status) is not str
    ):
        raise ValueError("vínculo de usuário inválido")
    return _fingerprint(
        secret,
        _CREDENTIAL_DOMAIN,
        (
            clerk_user_id,
            status,
            str(pessoa_id),
            _canonical_datetime(getattr(app_user, "password_changed_at", None)),
        ),
    )


def _phone_fingerprint(secret: str, phone: str) -> str:
    canonical = normalize_phone(phone)
    if not canonical:
        raise ValueError("telefone canônico ausente")
    return _fingerprint(secret, _PHONE_DOMAIN, (canonical,))


def _authorization_fingerprint(
    secret: str,
    *,
    config: AgentConfig,
    accepted_term_version: str,
    current_term_version: str,
) -> str:
    config_id = getattr(config, "id", None)
    if type(config_id) is not uuid.UUID or getattr(config, "ativo", None) is not True:
        raise ValueError("configuração inativa")
    return _fingerprint(
        secret,
        _AUTHORIZATION_DOMAIN,
        (str(config_id), accepted_term_version, current_term_version),
    )


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
    version = getattr(record, "termo_versao", None)
    return version if type(version) is str and version else None


def _uuid(value: object) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        raise ValueError("identificador server-side inválido")
    return value


def _public(
    igreja_id: uuid.UUID, conversation_id: uuid.UUID, inbound_message_id: uuid.UUID
) -> PublicWhatsappContext:
    return PublicWhatsappContext(igreja_id, conversation_id, inbound_message_id)


def _human(
    igreja_id: uuid.UUID, conversation_id: uuid.UUID, inbound_message_id: uuid.UUID
) -> HumanRequiredContext:
    return HumanRequiredContext(igreja_id, conversation_id, inbound_message_id)


def resolve_whatsapp_privilege_context(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    inbound_message_id: uuid.UUID,
    sensitive: bool = False,
    session_secret: str | None = None,
    now: dt.datetime | None = None,
) -> PublicWhatsappContext | HumanRequiredContext | PrivilegeContext:
    """Resolve operational identity from persisted inbound facts, or fail closed.

    It does not infer privilege from text, ``Pessoa.tipo`` or cell leadership.
    A missing operational link remains public; a duplicate or broken link asks
    for human handling instead of selecting one candidate.
    """

    igreja_id = _uuid(igreja_id)
    conversation_id = _uuid(conversation_id)
    inbound_message_id = _uuid(inbound_message_id)
    if type(sensitive) is not bool:
        return _human(igreja_id, conversation_id, inbound_message_id)
    try:
        require_tenant_scope(
            session, expected_igreja_id=igreja_id, source="whatsapp_privilege"
        )
    except (TenantScopeError, TypeError, ValueError):
        return _human(igreja_id, conversation_id, inbound_message_id)

    inbound = session.execute(
        select(Message).where(
            Message.igreja_id == igreja_id,
            Message.id == inbound_message_id,
            Message.conversation_id == conversation_id,
            Message.direcao == "in",
        )
    ).scalar_one_or_none()
    if (
        inbound is None
        or getattr(inbound, "igreja_id", None) != igreja_id
        or getattr(inbound, "conversation_id", None) != conversation_id
        or getattr(inbound, "direcao", None) != "in"
    ):
        return _human(igreja_id, conversation_id, inbound_message_id)

    conversation = session.execute(
        select(Conversation).where(
            Conversation.igreja_id == igreja_id,
            Conversation.id == conversation_id,
        )
    ).scalar_one_or_none()
    if (
        conversation is None
        or getattr(conversation, "igreja_id", None) != igreja_id
        or getattr(conversation, "id", None) != conversation_id
        or getattr(conversation, "estado", None) == "humano"
        or getattr(conversation, "assumido_por", None) is not None
    ):
        return _human(igreja_id, conversation_id, inbound_message_id)
    igreja = session.execute(
        select(Igreja).where(Igreja.id == igreja_id)
    ).scalar_one_or_none()
    config = session.execute(
        select(AgentConfig).where(AgentConfig.igreja_id == igreja_id)
    ).scalar_one_or_none()
    if (
        igreja is None
        or getattr(igreja, "id", None) != igreja_id
        or getattr(igreja, "status", None) in BLOCKING_IGREJA_STATUSES
        or config is None
        or getattr(config, "igreja_id", None) != igreja_id
        or getattr(config, "ativo", None) is not True
    ):
        return _human(igreja_id, conversation_id, inbound_message_id)
    canonical_phone = normalize_phone(getattr(conversation, "telefone", "") or "")
    if not canonical_phone:
        return _human(igreja_id, conversation_id, inbound_message_id)

    digits = func.regexp_replace(Pessoa.telefone, r"\D", "", "g")
    people = list(
        session.execute(
            select(Pessoa)
            .where(
                Pessoa.igreja_id == igreja_id,
                Pessoa.arquivada_em.is_(None),
                func.right(digits, 8) == phone_suffix(canonical_phone),
            )
            .limit(3)
        ).scalars().all()
    )
    # The suffix is only a bounded candidate prefilter.  Reaching its limit
    # cannot establish uniqueness because another canonical match may be
    # outside this page, so route the conversation to a human instead.
    if len(people) == 3:
        return _human(igreja_id, conversation_id, inbound_message_id)
    matches = [
        pessoa
        for pessoa in people
        if getattr(pessoa, "igreja_id", None) == igreja_id
        and normalize_phone(getattr(pessoa, "telefone", "") or "") == canonical_phone
    ]
    if not matches:
        return _public(igreja_id, conversation_id, inbound_message_id)
    if len(matches) != 1:
        return _human(igreja_id, conversation_id, inbound_message_id)
    pessoa = matches[0]
    pessoa_id = getattr(pessoa, "id", None)
    if (
        type(pessoa_id) is not uuid.UUID
        or getattr(pessoa, "arquivada_em", None) is not None
        or bool(getattr(pessoa, "optout", False))
        or bool(getattr(pessoa, "sem_interesse", False))
        or (
            getattr(conversation, "pessoa_id", None) is not None
            and getattr(conversation, "pessoa_id", None) != pessoa_id
        )
    ):
        return _human(igreja_id, conversation_id, inbound_message_id)

    current_term = get_settings().agent_term_version
    accepted_term = _latest_consent_version(
        session,
        igreja_id=igreja_id,
        pessoa_id=pessoa_id,
    )
    if (
        type(current_term) is not str
        or not current_term
        or consent_rules.needs_reaccept(accepted_term, current_term)
    ):
        return _human(igreja_id, conversation_id, inbound_message_id)

    users = list(
        session.execute(
            select(AppUser)
            .where(
                AppUser.igreja_id == igreja_id,
                AppUser.pessoa_id == pessoa_id,
                AppUser.status == "ativo",
                AppUser.clerk_user_id.is_not(None),
            )
            .order_by(AppUser.id.asc())
            .limit(2)
        ).scalars().all()
    )
    if not users:
        return _public(igreja_id, conversation_id, inbound_message_id)
    if len(users) != 1:
        return _human(igreja_id, conversation_id, inbound_message_id)
    app_user = users[0]
    app_user_id = getattr(app_user, "id", None)
    if (
        type(app_user_id) is not uuid.UUID
        or getattr(app_user, "igreja_id", None) != igreja_id
        or getattr(app_user, "pessoa_id", None) != pessoa_id
        or getattr(app_user, "status", None) != "ativo"
        or not isinstance(getattr(app_user, "clerk_user_id", None), str)
    ):
        return _human(igreja_id, conversation_id, inbound_message_id)

    role_rows = list(
        session.execute(
            select(UserRole)
            .where(UserRole.igreja_id == igreja_id, UserRole.user_id == app_user_id)
            .order_by(UserRole.id.asc())
        ).scalars().all()
    )
    role_snapshot: list[tuple[uuid.UUID, str]] = []
    for row in role_rows:
        role_id = getattr(row, "id", None)
        papel = getattr(row, "papel", None)
        if (
            type(role_id) is not uuid.UUID
            or type(papel) is not str
            or not papel
            or getattr(row, "igreja_id", None) != igreja_id
            or getattr(row, "user_id", None) != app_user_id
            or papel not in _ALLOWED_ROLES
        ):
            return _human(igreja_id, conversation_id, inbound_message_id)
        role_snapshot.append((role_id, papel))
    if len(role_snapshot) != len(set(role_snapshot)):
        return _human(igreja_id, conversation_id, inbound_message_id)

    cell_ids = tuple(
        session.execute(
            select(Celula.id)
            .where(
                Celula.igreja_id == igreja_id,
                Celula.lider_id == pessoa_id,
                Celula.ativo.is_(True),
            )
            .order_by(Celula.id.asc())
        ).scalars().all()
    )
    if any(type(cell_id) is not uuid.UUID for cell_id in cell_ids):
        return _human(igreja_id, conversation_id, inbound_message_id)

    effective_secret = (
        session_secret if session_secret is not None else get_settings().effective_session_secret
    )
    try:
        credential = _app_user_fingerprint(effective_secret, app_user)
        phone = _phone_fingerprint(effective_secret, canonical_phone)
        authorization = _authorization_fingerprint(
            effective_secret,
            config=config,
            accepted_term_version=accepted_term,
            current_term_version=current_term,
        )
    except (TypeError, ValueError):
        return _human(igreja_id, conversation_id, inbound_message_id)

    proof_id: uuid.UUID | None = None
    proof_until: dt.datetime | None = None
    if sensitive:
        # Imported locally to keep the operational resolver independent of the
        # panel-only proof module until the sensitive seam is requested.
        from app.services.agent_identity import resolve_confirmed_identity

        confirmed = resolve_confirmed_identity(
            session,
            igreja_id=igreja_id,
            conversation_id=conversation_id,
            session_secret=effective_secret,
            now=now,
        )
        if (
            confirmed is None
            or confirmed.pessoa_id != pessoa_id
            or confirmed.app_user_id != app_user_id
            or confirmed.roles != frozenset(role for _, role in role_snapshot)
            or not isinstance(getattr(confirmed, "proof_id", None), uuid.UUID)
            or not isinstance(getattr(confirmed, "confirmed_until", None), dt.datetime)
        ):
            return _human(igreja_id, conversation_id, inbound_message_id)
        proof_id = confirmed.proof_id
        proof_until = confirmed.confirmed_until

    context = PrivilegeContext(
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        inbound_message_id=inbound_message_id,
        pessoa_id=pessoa_id,
        app_user_id=app_user_id,
        roles=frozenset(role for _, role in role_snapshot),
        role_snapshot=tuple(sorted(role_snapshot, key=lambda value: (str(value[0]), value[1]))),
        owned_cell_ids=tuple(sorted(cell_ids, key=str)),
        credential_fingerprint=credential,
        phone_fingerprint=phone,
        authorization_fingerprint=authorization,
        proof_id=proof_id,
        proof_until=proof_until,
        sensitive=sensitive,
        scope_fingerprint="",
        context_fingerprint="",
    )
    scope = build_privilege_scope_fingerprint(effective_secret, context)
    scoped_context = PrivilegeContext(
        **{
            field: getattr(context, field)
            for field in context.__dataclass_fields__
            if field not in {"context_fingerprint", "scope_fingerprint"}
        },
        scope_fingerprint=scope,
        context_fingerprint="",
    )
    return PrivilegeContext(
        **{
            field: getattr(scoped_context, field)
            for field in scoped_context.__dataclass_fields__
            if field != "context_fingerprint"
        },
        context_fingerprint=build_privilege_context_fingerprint(effective_secret, scoped_context),
    )
