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
    """Return a canonical Brazilian digits-only key for `raw`.

    Beyond dropping non-digits, this canonicalizes the two ways the *same*
    Brazilian mobile shows up, so dedupe is reliable regardless of source:
      - drops the `55` country code (present on WhatsApp JIDs / E.164 input);
      - re-inserts the 9th digit that WhatsApp frequently omits on mobiles.

    So `89 99431-5927`, `+55 89 99431-5927` and the WhatsApp JID `558994315927`
    all reduce to the same key `89994315927`. Returns "" when no digit present.

    Note: a 10-digit local number is treated as a mobile missing the 9th digit
    (the dominant case for this WhatsApp-first product); 8-digit landlines are
    rare here and would gain a spurious 9 — acceptable for contact dedupe.
    """
    digits = _NON_DIGITS.sub("", raw or "")
    if not digits:
        return ""
    # Drop the +55 country code (E.164 / WhatsApp JID) when present.
    if len(digits) > 11 and digits.startswith("55"):
        digits = digits[2:]
    # DDD + 8 digits -> mobile missing the leading 9; re-insert it.
    if len(digits) == 10:
        digits = digits[:2] + "9" + digits[2:]
    return digits


def phone_suffix(canonical: str) -> str:
    """Last 8 digits of a canonical phone — a cheap SQL pre-filter for dedupe.

    The subscriber's last 8 digits are stable across the +55 and 9th-digit
    variations, so a query can narrow candidates by this suffix and then confirm
    a full canonical match in Python.
    """
    return canonical[-8:] if canonical else ""
