"""Inactive, pure authorization contract for purpose-specific consent.

This module performs no I/O and is not a channel integration.  Future callers
must resolve every field from server-side state immediately before evaluating
the action.  Unknown values, inconsistent identity bindings and unsupported
actions are denied instead of being coerced.

The first security slice deliberately permits no grant.  A later, separately
approved slice must prove the exact purpose, approved term and presentation
evidence before a self-grant can become reachable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.domain.purpose_consent import PurposeConsentPurpose


class PurposeConsentAction(str, Enum):
    """Closed set of operations understood by the policy evaluator."""

    READ_EFFECTIVE = "read_effective"
    READ_AUDIT = "read_audit"
    GRANT = "grant"
    WITHDRAW = "withdraw"


class PurposeConsentScope(str, Enum):
    """Closed target scopes, resolved by trusted server-side queries."""

    SELF = "self"
    ASSIGNED_CONVERSATION = "assigned_conversation"
    ACTIVE_CELL = "active_cell"
    RESPONSIBILITY = "responsibility"
    TENANT = "tenant"
    PLATFORM = "platform"


class PurposeConsentCapability(str, Enum):
    """Capabilities emitted by the deny-first RBAC policy."""

    READ_SELF_EFFECTIVE = "read_self_effective"
    READ_ASSIGNED_EFFECTIVE = "read_assigned_effective"
    READ_ACTIVE_CELL_EFFECTIVE = "read_active_cell_effective"
    READ_RESPONSIBILITY_EFFECTIVE = "read_responsibility_effective"
    READ_TENANT_EFFECTIVE = "read_tenant_effective"
    READ_TENANT_AUDIT = "read_tenant_audit"
    RECORD_SELF_WITHDRAWAL = "record_self_withdrawal"
    RECORD_PANEL_WITHDRAWAL_DISABLED = "record_panel_withdrawal_disabled"
    RECORD_SELF_GRANT_DISABLED = "record_self_grant_disabled"
    RECORD_PANEL_GRANT_DISABLED = "record_panel_grant_disabled"


class PanelAccessStatus(str, Enum):
    """Normalized status of the single server-resolved panel access."""

    ACTIVE = "ativo"
    INVITED = "convidado"
    REVOKED = "revogado"


KNOWN_PANEL_ROLES: Final[frozenset[str]] = frozenset(
    {
        "admin",
        "pastor",
        "lider_g12",
        "lider_consol",
        "lider_celula",
        "lider_mult",
        "operador",
        "membro",
    }
)

_TENANT_EFFECTIVE_ROLES: Final[frozenset[str]] = frozenset({"admin", "pastor"})
_RESPONSIBILITY_ROLES: Final[frozenset[str]] = frozenset(
    {"lider_g12", "lider_consol"}
)
_SCOPED_MINISTERIAL_PURPOSES: Final[frozenset[PurposeConsentPurpose]] = frozenset(
    {
        PurposeConsentPurpose.CUIDADO_PASTORAL,
        PurposeConsentPurpose.TAREFAS_OPERACIONAIS,
    }
)


@dataclass(frozen=True, slots=True)
class WhatsAppSelfConsentContext:
    """Server-resolved binding for one inbound WhatsApp self-service action."""

    igreja_id: uuid.UUID
    conversation_id: uuid.UUID
    conversation_igreja_id: uuid.UUID
    pessoa_id: uuid.UUID
    conversation_pessoa_id: uuid.UUID
    message_id: uuid.UUID
    message_igreja_id: uuid.UUID
    message_conversation_id: uuid.UUID
    target_igreja_id: uuid.UUID
    target_pessoa_id: uuid.UUID
    message_is_inbound: bool
    active_pessoa_match_count: int
    sem_interesse: bool = False


@dataclass(frozen=True, slots=True)
class PanelConsentContext:
    """Server-resolved panel identity and target-scope evidence."""

    igreja_id: uuid.UUID
    actor_app_user_id: uuid.UUID
    actor_igreja_id: uuid.UUID
    actor_pessoa_id: uuid.UUID | None
    target_igreja_id: uuid.UUID
    target_pessoa_id: uuid.UUID
    roles: frozenset[str]
    access_status: PanelAccessStatus
    authenticated_clerk_subject: str | None
    persisted_clerk_user_id: str | None
    usable_access_count: int
    has_assigned_conversation_scope: bool = False
    has_active_cell_scope: bool = False
    has_responsibility_scope: bool = False
    sem_interesse: bool = False
    is_platform_admin: bool = False


ConsentSecurityContext = WhatsAppSelfConsentContext | PanelConsentContext


def _is_non_nil_uuid(value: object) -> bool:
    return type(value) is uuid.UUID and value.int != 0


def _is_normalized_identity(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and value.isprintable()
    )


def _whatsapp_context_is_consistent(context: WhatsAppSelfConsentContext) -> bool:
    uuid_values = (
        context.igreja_id,
        context.conversation_id,
        context.conversation_igreja_id,
        context.pessoa_id,
        context.conversation_pessoa_id,
        context.message_id,
        context.message_igreja_id,
        context.message_conversation_id,
        context.target_igreja_id,
        context.target_pessoa_id,
    )
    if not all(_is_non_nil_uuid(value) for value in uuid_values):
        return False
    if type(context.message_is_inbound) is not bool or not context.message_is_inbound:
        return False
    if type(context.active_pessoa_match_count) is not int:
        return False
    if context.active_pessoa_match_count != 1:
        return False
    if type(context.sem_interesse) is not bool:
        return False
    return (
        context.conversation_igreja_id == context.igreja_id
        and context.message_igreja_id == context.igreja_id
        and context.target_igreja_id == context.igreja_id
        and context.conversation_pessoa_id == context.pessoa_id
        and context.target_pessoa_id == context.pessoa_id
        and context.message_conversation_id == context.conversation_id
    )


def _panel_context_is_consistent(context: PanelConsentContext) -> bool:
    uuid_values = (
        context.igreja_id,
        context.actor_app_user_id,
        context.actor_igreja_id,
        context.target_igreja_id,
        context.target_pessoa_id,
    )
    if not all(_is_non_nil_uuid(value) for value in uuid_values):
        return False
    if context.actor_pessoa_id is not None and not _is_non_nil_uuid(
        context.actor_pessoa_id
    ):
        return False
    if (
        context.actor_igreja_id != context.igreja_id
        or context.target_igreja_id != context.igreja_id
    ):
        return False
    if type(context.roles) is not frozenset or not context.roles:
        return False
    if any(type(role) is not str for role in context.roles):
        return False
    if not context.roles <= KNOWN_PANEL_ROLES:
        return False
    if type(context.access_status) is not PanelAccessStatus:
        return False
    if context.access_status is not PanelAccessStatus.ACTIVE:
        return False
    if not _is_normalized_identity(context.authenticated_clerk_subject):
        return False
    if not _is_normalized_identity(context.persisted_clerk_user_id):
        return False
    if context.authenticated_clerk_subject != context.persisted_clerk_user_id:
        return False
    if type(context.usable_access_count) is not int:
        return False
    if context.usable_access_count != 1:
        return False
    boolean_evidence = (
        context.has_assigned_conversation_scope,
        context.has_active_cell_scope,
        context.has_responsibility_scope,
        context.sem_interesse,
        context.is_platform_admin,
    )
    if any(type(value) is not bool for value in boolean_evidence):
        return False
    if context.is_platform_admin:
        return False
    return True


def consent_capabilities(context: object) -> frozenset[PurposeConsentCapability]:
    """Return capabilities for an exact trusted context, or none on inconsistency."""

    if type(context) is WhatsAppSelfConsentContext:
        if not _whatsapp_context_is_consistent(context):
            return frozenset()
        return frozenset(
            {
                PurposeConsentCapability.READ_SELF_EFFECTIVE,
                PurposeConsentCapability.RECORD_SELF_WITHDRAWAL,
            }
        )

    if type(context) is not PanelConsentContext:
        return frozenset()
    if not _panel_context_is_consistent(context):
        return frozenset()

    capabilities: set[PurposeConsentCapability] = set()
    if (
        context.actor_pessoa_id is not None
        and context.actor_pessoa_id == context.target_pessoa_id
    ):
        capabilities.update(
            {
                PurposeConsentCapability.READ_SELF_EFFECTIVE,
                PurposeConsentCapability.RECORD_SELF_WITHDRAWAL,
            }
        )
    if "admin" in context.roles:
        capabilities.add(PurposeConsentCapability.READ_TENANT_AUDIT)
    # ``sem_interesse`` removes ministerial/operational visibility, but never
    # the person's own read/withdrawal rights or admin compliance audit.
    if context.sem_interesse:
        return frozenset(capabilities)
    if context.roles & _TENANT_EFFECTIVE_ROLES:
        capabilities.add(PurposeConsentCapability.READ_TENANT_EFFECTIVE)
    if context.roles & _RESPONSIBILITY_ROLES and context.has_responsibility_scope:
        capabilities.add(PurposeConsentCapability.READ_RESPONSIBILITY_EFFECTIVE)
    if "lider_celula" in context.roles and context.has_active_cell_scope:
        capabilities.add(PurposeConsentCapability.READ_ACTIVE_CELL_EFFECTIVE)
    if "operador" in context.roles and context.has_assigned_conversation_scope:
        capabilities.add(PurposeConsentCapability.READ_ASSIGNED_EFFECTIVE)
    return frozenset(capabilities)


def consent_action_allowed(
    context: object,
    purpose: PurposeConsentPurpose,
    action: PurposeConsentAction,
    scope: PurposeConsentScope,
) -> bool:
    """Evaluate one closed action/scope pair without I/O or implicit widening."""

    if type(purpose) is not PurposeConsentPurpose:
        return False
    if type(action) is not PurposeConsentAction:
        return False
    if type(scope) is not PurposeConsentScope:
        return False
    if action is PurposeConsentAction.GRANT:
        return False
    if scope is PurposeConsentScope.PLATFORM:
        return False
    if (
        scope is PurposeConsentScope.ASSIGNED_CONVERSATION
        and purpose is not PurposeConsentPurpose.ATENDIMENTO_SOLICITADO
    ):
        return False
    if (
        scope
        in {PurposeConsentScope.ACTIVE_CELL, PurposeConsentScope.RESPONSIBILITY}
        and purpose not in _SCOPED_MINISTERIAL_PURPOSES
    ):
        return False

    required: PurposeConsentCapability | None = None
    if action is PurposeConsentAction.READ_EFFECTIVE:
        required = {
            PurposeConsentScope.SELF: PurposeConsentCapability.READ_SELF_EFFECTIVE,
            PurposeConsentScope.ASSIGNED_CONVERSATION: (
                PurposeConsentCapability.READ_ASSIGNED_EFFECTIVE
            ),
            PurposeConsentScope.ACTIVE_CELL: (
                PurposeConsentCapability.READ_ACTIVE_CELL_EFFECTIVE
            ),
            PurposeConsentScope.RESPONSIBILITY: (
                PurposeConsentCapability.READ_RESPONSIBILITY_EFFECTIVE
            ),
            PurposeConsentScope.TENANT: (
                PurposeConsentCapability.READ_TENANT_EFFECTIVE
            ),
        }.get(scope)
    elif (
        action is PurposeConsentAction.READ_AUDIT
        and scope is PurposeConsentScope.TENANT
    ):
        required = PurposeConsentCapability.READ_TENANT_AUDIT
    elif (
        action is PurposeConsentAction.WITHDRAW
        and scope is PurposeConsentScope.SELF
    ):
        required = PurposeConsentCapability.RECORD_SELF_WITHDRAWAL

    if required is None:
        return False
    return required in consent_capabilities(context)
