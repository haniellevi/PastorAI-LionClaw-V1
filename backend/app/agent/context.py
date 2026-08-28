"""Trusted, server-resolved context for one agent turn.

The context is deliberately separate from ``AgentState``.  It contains the
tenant and authority facts that must never be supplied by an LLM, copied into
a checkpoint, or accepted from a caller-controlled state dictionary.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from langgraph.runtime import Runtime

from app.domain.agent_authz import PrivilegeContext
from app.domain.conversations import VALID_ESTADOS


class TrustedContextError(RuntimeError):
    """The trusted runtime context or mutable graph state is invalid."""


@dataclass(frozen=True, slots=True)
class LegacyTermContext:
    """Server-resolved legacy consent versions used by the current graph."""

    accepted_version: str | None
    current_version: str

    def __post_init__(self) -> None:
        _validate_legacy_term(self)


@dataclass(frozen=True, slots=True)
class TrustedAgentContext:
    """Immutable authority boundary for a single WhatsApp agent turn."""

    igreja_id: uuid.UUID
    conversation_id: uuid.UUID
    pessoa_id: uuid.UUID
    conversation_state: str
    igreja_nome: str | None
    privilege: PrivilegeContext
    legacy_term: LegacyTermContext
    channel: Literal["whatsapp"] = "whatsapp"

    def __post_init__(self) -> None:
        _validate_trusted_context(self)


_ALLOWED_STATE_KEYS = frozenset(
    {
        "texto",
        "pessoa",
        "route",
        "response",
        "events",
        "tool_calls",
        "apply_optout",
        "apply_consent_version",
        "intake_update",
    }
)

_RESERVED_STATE_KEYS = frozenset(
    {
        "tenant_id",
        "igreja_id",
        "igreja_nome",
        "church_id",
        "church_name",
        "conversation_id",
        "pessoa_id",
        "person_id",
        "actor_id",
        "actor_roles",
        "estado",
        "conversation_state",
        "is_ministerial",
        "is_admin",
        "is_pastor",
        "privilege",
        "roles",
        "papeis",
        "capabilities",
        "permissions",
        "allowed_tools",
        "term_accepted_version",
        "term_current_version",
        "legacy_term",
        "channel",
        "context",
        "runtime",
    }
)

_OUTPUT_STATE_KEYS = frozenset(
    {
        "route",
        "response",
        "events",
        "tool_calls",
        "apply_optout",
        "apply_consent_version",
        "intake_update",
    }
)

_ALLOWED_PESSOA_KEYS = frozenset(
    {
        "nome",
        "subetapa",
        "origem",
        "has_endereco",
        "primeiro_contato_set",
    }
)


def _nonempty_exact_string(value: object, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise TrustedContextError(f"{field} must be a non-empty normalized string")
    return value


def _validate_uuid(value: object, field: str) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        raise TrustedContextError(f"{field} must be a non-nil UUID")
    return value


def _validate_legacy_term(term: LegacyTermContext) -> None:
    _nonempty_exact_string(term.current_version, "legacy_term.current_version")
    if term.accepted_version is not None:
        _nonempty_exact_string(
            term.accepted_version, "legacy_term.accepted_version"
        )


def _validate_privilege(privilege: object, pessoa_id: uuid.UUID) -> None:
    if type(privilege) is not PrivilegeContext:
        raise TrustedContextError("privilege must be a PrivilegeContext")
    if type(privilege.pessoa_id) is not str:
        raise TrustedContextError("privilege.pessoa_id must be a UUID")
    try:
        privilege_pessoa_id = uuid.UUID(privilege.pessoa_id)
    except (AttributeError, TypeError, ValueError):
        raise TrustedContextError("privilege.pessoa_id must be a UUID") from None
    if privilege_pessoa_id != pessoa_id:
        raise TrustedContextError("privilege belongs to a different person")
    if privilege.pessoa_id != str(privilege_pessoa_id):
        raise TrustedContextError("privilege.pessoa_id must be normalized")
    _nonempty_exact_string(privilege.tipo, "privilege.tipo")
    if type(privilege.sem_interesse) is not bool:  # noqa: E721
        raise TrustedContextError("privilege.sem_interesse must be a bool")
    if type(privilege.leads_cells) is not bool:  # noqa: E721
        raise TrustedContextError("privilege.leads_cells must be a bool")
    if type(privilege.roles) is not frozenset or any(
        type(role) is not str or not role or role != role.strip()
        for role in privilege.roles
    ):
        raise TrustedContextError("privilege.roles must be normalized strings")


def _validate_trusted_context(context: TrustedAgentContext) -> None:
    _validate_uuid(context.igreja_id, "igreja_id")
    _validate_uuid(context.conversation_id, "conversation_id")
    pessoa_id = _validate_uuid(context.pessoa_id, "pessoa_id")
    if (
        type(context.conversation_state) is not str
        or context.conversation_state not in VALID_ESTADOS
    ):
        raise TrustedContextError("conversation_state is invalid")
    if context.igreja_nome is not None:
        _nonempty_exact_string(context.igreja_nome, "igreja_nome")
    if type(context.channel) is not str or context.channel != "whatsapp":
        raise TrustedContextError("channel must be whatsapp")
    if type(context.legacy_term) is not LegacyTermContext:
        raise TrustedContextError("legacy_term must be a LegacyTermContext")
    _validate_legacy_term(context.legacy_term)
    _validate_privilege(context.privilege, pessoa_id)


def require_trusted_context(value: object) -> TrustedAgentContext:
    """Return a repeatedly validated context or fail closed."""
    if type(value) is not TrustedAgentContext:
        raise TrustedContextError("trusted agent context is required")
    _validate_trusted_context(value)
    return value


def context_from_runtime(
    runtime: Runtime[TrustedAgentContext] | object,
) -> TrustedAgentContext:
    """Extract and validate context from LangGraph's runtime injection."""
    if not isinstance(runtime, Runtime):
        raise TrustedContextError("LangGraph Runtime is required")
    return require_trusted_context(runtime.context)


def validate_agent_node_state(value: object) -> dict[str, Any]:
    """Validate an internal node state and reject authority injection."""
    if not isinstance(value, Mapping):
        raise TrustedContextError("agent state must be a mapping")

    keys = set(value)
    if any(type(key) is not str for key in keys):
        raise TrustedContextError("agent state keys must be strings")
    reserved = sorted(keys & _RESERVED_STATE_KEYS)
    if reserved:
        raise TrustedContextError("reserved agent state key is not allowed")
    unknown = sorted(keys - _ALLOWED_STATE_KEYS)
    if unknown:
        raise TrustedContextError("unknown agent state key is not allowed")

    texto = value.get("texto")
    if texto is not None and not isinstance(texto, str):
        raise TrustedContextError("texto must be a string")

    pessoa = value.get("pessoa")
    if pessoa is not None:
        if not isinstance(pessoa, Mapping):
            raise TrustedContextError("pessoa must be a mapping")
        if any(type(key) is not str for key in pessoa):
            raise TrustedContextError("pessoa snapshot keys must be strings")
        pessoa_unknown = sorted(set(pessoa) - _ALLOWED_PESSOA_KEYS)
        if pessoa_unknown:
            raise TrustedContextError("unknown pessoa snapshot key is not allowed")
        for key in ("nome", "subetapa", "origem"):
            field = pessoa.get(key)
            if field is not None and not isinstance(field, str):
                raise TrustedContextError(f"pessoa.{key} must be a string")
        for key in ("has_endereco", "primeiro_contato_set"):
            field = pessoa.get(key)
            if field is not None and type(field) is not bool:  # noqa: E721
                raise TrustedContextError(f"pessoa.{key} must be a bool")

    for key in ("events", "tool_calls"):
        field = value.get(key)
        if field is not None and not isinstance(field, list):
            raise TrustedContextError(f"{key} must be a list")
    intake_update = value.get("intake_update")
    if intake_update is not None and not isinstance(intake_update, Mapping):
        raise TrustedContextError("intake_update must be a mapping")
    for key in ("route", "response", "apply_consent_version"):
        field = value.get(key)
        if field is not None and not isinstance(field, str):
            raise TrustedContextError(f"{key} must be a string or null")
    apply_optout = value.get("apply_optout")
    if apply_optout is not None and type(apply_optout) is not bool:  # noqa: E721
        raise TrustedContextError("apply_optout must be a bool")

    return cast(dict[str, Any], value)


def validate_agent_input_state(value: object) -> dict[str, Any]:
    """Validate an untrusted turn input before any graph or fallback runs.

    Outputs and control fields are forbidden even when their supplied values
    are empty.  Only graph nodes may introduce them after the input boundary.
    """
    if type(value) is not dict:
        raise TrustedContextError("agent input state must be a plain dict")
    pessoa = value.get("pessoa")
    if pessoa is not None and type(pessoa) is not dict:
        raise TrustedContextError("pessoa input snapshot must be a plain dict")
    state = validate_agent_node_state(value)
    preseeded = sorted(set(state) & _OUTPUT_STATE_KEYS)
    if preseeded:
        raise TrustedContextError("preseeded agent output key is not allowed")
    if "texto" not in state or "pessoa" not in state:
        raise TrustedContextError("texto and pessoa are required agent inputs")
    if type(state["texto"]) is not str:
        raise TrustedContextError("texto input must be a string")
    return state


__all__ = [
    "LegacyTermContext",
    "TrustedAgentContext",
    "TrustedContextError",
    "context_from_runtime",
    "require_trusted_context",
    "validate_agent_input_state",
    "validate_agent_node_state",
]
