"""Phone normalization for tenant-scoped contact dedupe.

A contact is unique per (telefone, igreja). To make the dedupe reliable
regardless of how the number was typed (spaces, dashes, parentheses, leading
"+"), we reduce every number to a canonical digits-only key used for the
existence check. The original, human-friendly value is preserved as typed.

The normalization mirrors the SQL `regexp_replace(telefone, '\\D', '', 'g')`
used in the dedupe query, so the Python and database views of a number agree.
"""

from __future__ import annotations

import re

_NON_DIGITS = re.compile(r"\D+")


def normalize_phone(raw: str) -> str:
    """Return a digits-only canonical key for `raw`.

    Drops every non-digit character (spaces, dashes, parentheses, leading "+").
    Returns an empty string when no digit is present.
    """
    if not raw:
        return ""
    return _NON_DIGITS.sub("", raw)
