"""E4a durable operation identity, deliberately without authority or storage.

This module defines an untrusted, tenant-scoped idempotency identity that a
future reviewed persistence adapter may compare.  It does not mint authority,
open a transaction, declare locks, or claim that an operation is authorized.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from enum import Enum


class ConsentLedgerReceiptValidationError(ValueError):
    """A value does not meet the intentionally small E4a identity contract."""


class ConsentLedgerReceiptAction(str, Enum):
    """Known manifestations that remain blocked in E4a."""

    ACCEPT = "ACCEPT"
    WITHDRAW = "WITHDRAW"
    REFUSE_INITIAL = "REFUSE_INITIAL"


class ConsentLedgerReceiptIdempotencyDisposition(str, Enum):
    """Comparison result for two rehydrated records in the same tenant scope."""

    EXACT_RETRY = "EXACT_RETRY"
    CONFLICT = "CONFLICT"


_PERSISTED_KEY_RE = re.compile(r"[a-z0-9][a-z0-9:._-]{0,127}")


def _reject(field: str, message: str) -> None:
    raise ConsentLedgerReceiptValidationError(f"{field}: {message}")


def _require_uuid(value: object, *, field: str) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        _reject(field, "UUID não nulo obrigatório")
    return value


@dataclass(frozen=True, slots=True)
class TenantScopedConsentLedgerReceiptIdempotencyKey:
    """Durable identity, not a credential or a server-owned capability.

    ``value`` is deliberately rehydratable after a process restart.  Its scope
    is the tuple ``(igreja_id, value)`` and a future database adapter must make
    that tuple durable and unique before it can call any writer.
    """

    igreja_id: uuid.UUID
    value: str

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, field="igreja_id")
        if type(self.value) is not str or _PERSISTED_KEY_RE.fullmatch(self.value) is None:
            _reject("value", "chave idempotente persistida inválida")

    @classmethod
    def from_persisted(
        cls,
        *,
        igreja_id: uuid.UUID,
        value: str,
    ) -> TenantScopedConsentLedgerReceiptIdempotencyKey:
        """Rehydrate a persisted identity without adding process-local proof."""

        return cls(igreja_id=igreja_id, value=value)


def canonical_tenant_scoped_idempotency_identity(
    key: TenantScopedConsentLedgerReceiptIdempotencyKey,
) -> str:
    """Return the stable serialized identity used by a future durable adapter."""

    if type(key) is not TenantScopedConsentLedgerReceiptIdempotencyKey:
        _reject("key", "identidade idempotente tenant-scoped obrigatória")
    return json.dumps(
        {"igreja_id": str(key.igreja_id), "value": key.value},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


@dataclass(frozen=True, slots=True)
class ConsentLedgerReceiptOperation:
    """Untrusted operation identity retained only for future idempotency checks."""

    operation_id: uuid.UUID
    idempotency_key: TenantScopedConsentLedgerReceiptIdempotencyKey
    action: ConsentLedgerReceiptAction

    def __post_init__(self) -> None:
        _require_uuid(self.operation_id, field="operation_id")
        if type(self.idempotency_key) is not TenantScopedConsentLedgerReceiptIdempotencyKey:
            _reject("idempotency_key", "chave tenant-scoped obrigatória")
        if type(self.action) is not ConsentLedgerReceiptAction:
            _reject("action", "ação fechada obrigatória")


def compare_rehydrated_operations(
    existing: ConsentLedgerReceiptOperation,
    candidate: ConsentLedgerReceiptOperation,
) -> ConsentLedgerReceiptIdempotencyDisposition:
    """Classify retry versus conflict without inferring persistence or ownership.

    Both records must already have been read by a future tenant-scoped adapter.
    This pure comparison neither queries storage nor proves that either record
    belongs to a caller.
    """

    if type(existing) is not ConsentLedgerReceiptOperation:
        _reject("existing", "operação persistida fechada obrigatória")
    if type(candidate) is not ConsentLedgerReceiptOperation:
        _reject("candidate", "operação candidata fechada obrigatória")
    if existing.idempotency_key != candidate.idempotency_key:
        _reject("idempotency_key", "comparação exige a mesma chave tenant-scoped")
    if (
        existing.operation_id == candidate.operation_id
        and existing.action is candidate.action
    ):
        return ConsentLedgerReceiptIdempotencyDisposition.EXACT_RETRY
    return ConsentLedgerReceiptIdempotencyDisposition.CONFLICT


__all__ = (
    "ConsentLedgerReceiptAction",
    "ConsentLedgerReceiptIdempotencyDisposition",
    "ConsentLedgerReceiptOperation",
    "ConsentLedgerReceiptValidationError",
    "TenantScopedConsentLedgerReceiptIdempotencyKey",
    "canonical_tenant_scoped_idempotency_identity",
    "compare_rehydrated_operations",
)
