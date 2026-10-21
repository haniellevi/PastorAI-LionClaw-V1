"""Independent, inert release fence for the agenda write specialist."""
import os
import uuid
from app.services.whatsapp_privilege import privilege_enabled_from_environment

AGENDA_WRITE_WHATSAPP_APPROVED_RELEASE_ID: str | None = None


def enabled(igreja_id: uuid.UUID) -> bool:
    release = AGENDA_WRITE_WHATSAPP_APPROVED_RELEASE_ID
    if (type(igreja_id) is not uuid.UUID or igreja_id.int == 0
        or type(release) is not str or not release.strip()
        or not privilege_enabled_from_environment(igreja_id)):
        return False
    raw = os.environ.get('AGENDA_WRITE_WHATSAPP_ENABLED_IGREJA_IDS', '')
    try:
        values = [uuid.UUID(part.strip()) for part in raw.split(',')]
    except (ValueError, AttributeError):
        return False
    return len(set(values)) == len(values) and igreja_id in values
