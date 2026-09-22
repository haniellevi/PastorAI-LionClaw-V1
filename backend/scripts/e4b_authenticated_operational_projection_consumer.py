"""Deliberate rejection boundary for the source-only E4b projection slice."""

from __future__ import annotations


class ProjectionConsumerDisabled(RuntimeError):
    """Raised because this slice never invokes an operational consumer."""


def reject_projection_receipt(receipt: object) -> None:
    """Reject every receipt without opening an operational execution path."""

    raise ProjectionConsumerDisabled("source-only projection consumer is disabled")
