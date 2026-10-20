"""Inert release fence. Deployment and migrations never activate this feature."""

import os
import uuid

# Only a later, explicitly approved release may replace this value.
CONHECIMENTO_WHATSAPP_APPROVED_RELEASE_ID: str | None = None


def enabled(igreja_id: uuid.UUID) -> bool:
    if type(igreja_id) is not uuid.UUID or not CONHECIMENTO_WHATSAPP_APPROVED_RELEASE_ID:
        return False
    raw = os.environ.get("CONHECIMENTO_WHATSAPP_ENABLED_IGREJA_IDS", "")
    try:
        parts = raw.split(",")
        values = [uuid.UUID(part.strip()) for part in parts]
    except (ValueError, AttributeError):
        return False
    return bool(raw) and len(set(values)) == len(values) and igreja_id in values
