"""Fail-closed D3 contract for future private LangGraph checkpoints.

This module deliberately does not install or build a saver.  The current
``AgentState`` is still turn-local and replay-unsafe.  Effect intents now live
in one complete, resettable, untracked ``turn_effects`` envelope, but they do
not yet have durable command identity or idempotent replay semantics.  The
direct fallback also cannot resume a persisted workflow.  The PostgreSQL
adapter still needs a private, tenant-bearing schema with forced RLS and strict
serialization.

The opaque LangGraph ``thread_id`` derived here is only defense in depth.  Its
unkeyed SHA-256 is a stable pseudonym/namespace, not a secret, authenticator, or
tenant authority.  It cannot replace ``igreja_id`` columns, forced RLS, or the
transaction-local tenant context required by the database contract.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, NoReturn, Protocol

from app.agent.context import TrustedAgentContext, require_trusted_context

CHECKPOINT_NAMESPACE = "pastorai.agent.private.v1"
CHECKPOINT_SCOPE_VERSION = "v1"
_CHECKPOINT_SCOPE_DOMAIN = "pastorai:d3:checkpoint-scope:v1"


class PrivateCheckpointActivationBlocker(str, Enum):
    """Static blockers that keep the current graph deliberately stateless."""

    POSTGRES_SAVER_NOT_INSTALLED = "POSTGRES_SAVER_NOT_INSTALLED"
    PRIVATE_SCHEMA_NOT_SUPPORTED = "PRIVATE_SCHEMA_NOT_SUPPORTED"
    TENANT_SCHEMA_NOT_MIGRATED = "TENANT_SCHEMA_NOT_MIGRATED"
    CURRENT_AGENT_STATE_REPLAY_UNSAFE = "CURRENT_AGENT_STATE_REPLAY_UNSAFE"
    STATELESS_FALLBACK_REPLAY_UNSAFE = "STATELESS_FALLBACK_REPLAY_UNSAFE"
    STRICT_SERIALIZATION_NOT_CONFIGURED = "STRICT_SERIALIZATION_NOT_CONFIGURED"
    RETENTION_AND_DELETION_NOT_APPROVED = "RETENTION_AND_DELETION_NOT_APPROVED"


CURRENT_PRIVATE_CHECKPOINT_BLOCKERS: tuple[
    PrivateCheckpointActivationBlocker, ...
] = tuple(PrivateCheckpointActivationBlocker)

# Every field in today's AgentState belongs to one turn.  The effect envelope
# is an untracked LangGraph channel and is therefore not durable workflow
# state; its contents are unexecuted intents consumed by the runtime.
CURRENT_EPHEMERAL_AGENT_STATE_KEYS = frozenset(
    {
        "texto",
        "pessoa",
        "route",
        "response",
        "turn_effects",
    }
)
CURRENT_REPLAY_SENSITIVE_AGENT_STATE_KEYS = frozenset({"turn_effects"})
CURRENT_TURN_EFFECT_KEYS = frozenset(
    {
        "events",
        "tool_calls",
        "apply_optout",
        "apply_consent_version",
        "intake_update",
    }
)


class PrivateCheckpointActivationError(RuntimeError):
    """Durable checkpoint activation is unavailable or replay-unsafe."""

    def __init__(
        self,
        blockers: tuple[PrivateCheckpointActivationBlocker, ...],
    ) -> None:
        self.blockers = blockers
        labels = ",".join(blocker.value for blocker in blockers)
        super().__init__(f"private checkpoint activation blocked: {labels}")


@dataclass(frozen=True, slots=True, repr=False)
class PrivateCheckpointBinding:
    """Server-only binding between trusted authority and an opaque LG scope.

    Raw identifiers stay on this server-side object for the future database
    adapter.  Only ``as_langgraph_config`` crosses into LangGraph, and that
    config contains no authority.  A future saver must still bind these raw
    identifiers to tenant-bearing rows inside a scoped database transaction.
    Person reassociation never changes the conversation thread identifier; the
    future adapter must validate the person binding relationally on every use.
    """

    igreja_id: uuid.UUID
    conversation_id: uuid.UUID
    pessoa_id: uuid.UUID
    thread_id: str
    checkpoint_ns: str = CHECKPOINT_NAMESPACE

    def __repr__(self) -> str:
        return (
            "PrivateCheckpointBinding("
            f"scope_version={CHECKPOINT_SCOPE_VERSION!r})"
        )

    def as_langgraph_config(self) -> dict[str, dict[str, str]]:
        """Return a fresh, non-authoritative config for a future saver."""
        return {
            "configurable": {
                "thread_id": self.thread_id,
                "checkpoint_ns": self.checkpoint_ns,
            }
        }


def _opaque_thread_id(igreja_id: uuid.UUID, conversation_id: uuid.UUID) -> str:
    material = "\n".join(
        (_CHECKPOINT_SCOPE_DOMAIN, str(igreja_id), str(conversation_id))
    ).encode("ascii")
    return f"d3v1_{hashlib.sha256(material).hexdigest()}"


def build_private_checkpoint_binding(
    context: TrustedAgentContext | object,
) -> PrivateCheckpointBinding:
    """Derive the future checkpoint binding only from trusted server context."""
    trusted = require_trusted_context(context)
    return PrivateCheckpointBinding(
        igreja_id=trusted.igreja_id,
        conversation_id=trusted.conversation_id,
        pessoa_id=trusted.pessoa_id,
        thread_id=_opaque_thread_id(
            trusted.igreja_id,
            trusted.conversation_id,
        ),
    )


def reject_current_agent_state_rehydration(_state: object) -> NoReturn:
    """Refuse checkpointing or rehydration of the current ephemeral state."""
    raise PrivateCheckpointActivationError(
        (
            PrivateCheckpointActivationBlocker.CURRENT_AGENT_STATE_REPLAY_UNSAFE,
            PrivateCheckpointActivationBlocker.STATELESS_FALLBACK_REPLAY_UNSAFE,
        )
    )


class PrivateCheckpointBackendFactory(Protocol):
    """Future adapter seam; no implementation is accepted in this D3 slice."""

    def create(self, *, binding: PrivateCheckpointBinding) -> Any:
        """Build a reviewed saver bound to trusted tenant/conversation scope."""
        ...


def build_private_checkpointer(
    _factory: PrivateCheckpointBackendFactory,
    *,
    context: TrustedAgentContext | object,
) -> NoReturn:
    """Validate trusted scope, then fail closed without calling the factory."""
    _binding = build_private_checkpoint_binding(context)
    raise PrivateCheckpointActivationError(CURRENT_PRIVATE_CHECKPOINT_BLOCKERS)


__all__ = [
    "CHECKPOINT_NAMESPACE",
    "CHECKPOINT_SCOPE_VERSION",
    "CURRENT_EPHEMERAL_AGENT_STATE_KEYS",
    "CURRENT_PRIVATE_CHECKPOINT_BLOCKERS",
    "CURRENT_REPLAY_SENSITIVE_AGENT_STATE_KEYS",
    "CURRENT_TURN_EFFECT_KEYS",
    "PrivateCheckpointActivationBlocker",
    "PrivateCheckpointActivationError",
    "PrivateCheckpointBackendFactory",
    "PrivateCheckpointBinding",
    "build_private_checkpoint_binding",
    "build_private_checkpointer",
    "reject_current_agent_state_rehydration",
]
