"""E4a write boundary with no authority adapter and no persistence capability.

This service intentionally has no constructor injection, authority source,
delegate, transaction, reconciliation method or lock declaration.  Until a
separately reviewed server-owned adapter exists, every valid operation stops at
the same fail-closed boundary before any effect can be attempted.
"""

from __future__ import annotations

from enum import Enum
from typing import NoReturn

from app.domain.consent_ledger_receipt import ConsentLedgerReceiptOperation


class ConsentLedgerReceiptCoordinatorErrorCode(str, Enum):
    INVALID_OPERATION = "INVALID_OPERATION"
    AUTHORITY_ADAPTER_UNAVAILABLE = "AUTHORITY_ADAPTER_UNAVAILABLE"


class ConsentLedgerReceiptCoordinatorError(RuntimeError):
    """Sanitized failure emitted before an E4a operation can have an effect."""

    def __init__(self, code: ConsentLedgerReceiptCoordinatorErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


def _fail(code: ConsentLedgerReceiptCoordinatorErrorCode) -> NoReturn:
    raise ConsentLedgerReceiptCoordinatorError(code)


class ConsentLedgerReceiptCoordinator:
    """Internal fail-closed boundary; a reviewed authority adapter is absent."""

    __slots__ = ()

    def stage_write(self, operation: object) -> NoReturn:
        """Deny every action before any authority, storage or runtime handoff."""

        if type(operation) is not ConsentLedgerReceiptOperation:
            _fail(ConsentLedgerReceiptCoordinatorErrorCode.INVALID_OPERATION)
        _fail(
            ConsentLedgerReceiptCoordinatorErrorCode.AUTHORITY_ADAPTER_UNAVAILABLE
        )


__all__ = (
    "ConsentLedgerReceiptCoordinator",
    "ConsentLedgerReceiptCoordinatorError",
    "ConsentLedgerReceiptCoordinatorErrorCode",
)
