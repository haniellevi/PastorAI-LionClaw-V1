"""Typed receipt boundary with no execution capability."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .e4b_authenticated_operational_projection import FinalProjectionReceipt


class ProjectionConsumerDisabled(RuntimeError):
    """Raised when a receipt is not the exact finalized source type."""


def reject_projection_receipt(receipt: object) -> None:
    """Preserve the legacy always-disabled rejection entrypoint."""

    raise ProjectionConsumerDisabled("source-only projection consumer is disabled")


def accept_final_projection_receipt(receipt: object) -> "FinalProjectionReceipt":
    """Accept a typed final source receipt without invoking any consumer action."""

    receipt_type = _final_receipt_type()
    if receipt_type is None or type(receipt) is not receipt_type:
        raise ProjectionConsumerDisabled("final typed projection receipt required")
    return receipt


def _final_receipt_type() -> type[object] | None:
    try:
        from .e4b_authenticated_operational_projection import FinalProjectionReceipt
    except ImportError:
        try:
            from e4b_authenticated_operational_projection import FinalProjectionReceipt
        except ImportError:
            return None
    return FinalProjectionReceipt
