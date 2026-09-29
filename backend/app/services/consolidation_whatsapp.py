"""Closed V3 WhatsApp gates and privacy-safe consolidation projections."""
from __future__ import annotations

import os
import unicodedata
import uuid
from urllib.parse import urlsplit

from app.config import get_settings
from app.domain.work_queue import ADMIN_ROLE, TIPO_RESOLVER_ROLES, can_resolve
from app.services.whatsapp_privilege import privilege_enabled_from_environment


CONSOLIDATION_WHATSAPP_APPROVED_RELEASE_ID: str | None = None
CONSOLIDATION_PANEL_FRAGMENT = "consolidar"
# Coordination remains intentionally narrower than human responsibility. It
# is used for tenant-wide opaque queue access and assignment only.
CONSOLIDATION_WHATSAPP_ROLES = frozenset({"admin", "pastor", "lider_consol"})
_CONSOLIDATION_PENDING_TASK_TYPES = frozenset({"conectar_celula", "fonovisita"})


def _role_set(roles: object) -> frozenset[str]:
    if not isinstance(roles, (frozenset, set, tuple)) or not all(
        type(role) is str for role in roles
    ):
        return frozenset()
    return frozenset(roles)


def consolidation_coordination_allowed(roles: object) -> bool:
    """Whether roles can manage the tenant-wide opaque V3 queue."""

    return bool(_role_set(roles) & CONSOLIDATION_WHATSAPP_ROLES)


def consolidation_responsible_task_types(roles: object) -> frozenset[str]:
    """Return V3 task types that the current human role may resolve."""

    role_set = _role_set(roles)
    return frozenset(
        task_type
        for task_type in _CONSOLIDATION_PENDING_TASK_TYPES
        if can_resolve(role_set, task_type)
    )


def consolidation_responsible_allowed(roles: object) -> bool:
    """Whether roles can access their own V3 work of at least one type."""

    return bool(consolidation_responsible_task_types(roles))


def consolidation_task_resolver_roles(task_type: object) -> frozenset[str]:
    """Server-side SQL role predicate for one assigned V3 notification."""

    if type(task_type) is not str or task_type not in _CONSOLIDATION_PENDING_TASK_TYPES:
        return frozenset()
    return frozenset({ADMIN_ROLE}) | TIPO_RESOLVER_ROLES.get(task_type, frozenset())


def consolidation_enabled_from_environment(igreja_id: object) -> bool:
    """Require V3's reviewed release, exact tenant allowlist and S3 gate."""

    if type(igreja_id) is not uuid.UUID or igreja_id.int == 0:
        return False
    if (
        type(CONSOLIDATION_WHATSAPP_APPROVED_RELEASE_ID) is not str
        or not CONSOLIDATION_WHATSAPP_APPROVED_RELEASE_ID.strip()
        or not privilege_enabled_from_environment(igreja_id)
    ):
        return False
    raw = os.environ.get("CONSOLIDATION_WHATSAPP_ENABLED_IGREJA_IDS", "")
    if type(raw) is not str or not raw.strip():
        return False
    pieces = raw.split(",")
    if any(not piece.strip() for piece in pieces):
        return False
    try:
        allowed = tuple(uuid.UUID(piece.strip()) for piece in pieces)
    except ValueError:
        return False
    return len(allowed) == len(set(allowed)) and igreja_id in allowed


def consolidation_delivery_enabled(igreja_id: object) -> bool:
    """Require every autonomous V3 transport gate before scheduling or sending."""

    if type(igreja_id) is not uuid.UUID or igreja_id.int == 0:
        return False
    settings = get_settings()
    return bool(
        getattr(settings, "consolidation_notify_enabled", False) is True
        and getattr(settings, "allow_real_sends", False) is True
        and settings.whatsapp_piloto(igreja_id)
        and consolidation_enabled_from_environment(igreja_id)
    )


def consolidation_panel_link(frontend_url: object) -> str | None:
    """Return the fixed authenticated panel fragment without a target or token."""

    if type(frontend_url) is not str or not frontend_url:
        return None
    try:
        parsed = urlsplit(frontend_url)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.hostname is None
        or (port is not None and not 1 <= port <= 65535)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    return f"{parsed.scheme}://{parsed.netloc}/#{CONSOLIDATION_PANEL_FRAGMENT}"


def template_first_name(value: object) -> str | None:
    """Project one safe first name only for a transient 1:1 template."""

    if type(value) is not str or not 1 <= len(value) <= 160:
        return None
    value = unicodedata.normalize("NFC", value)
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in value):
        return None
    first = " ".join(value.split()).split(" ")[0]
    if not 1 <= len(first) <= 60:
        return None
    if not all(character.isalpha() or character in {"-", "'"} for character in first):
        return None
    if first[0] in {"-", "'"} or first[-1] in {"-", "'"}:
        return None
    return first


__all__ = [
    "CONSOLIDATION_PANEL_FRAGMENT",
    "CONSOLIDATION_WHATSAPP_APPROVED_RELEASE_ID",
    "CONSOLIDATION_WHATSAPP_ROLES",
    "consolidation_coordination_allowed",
    "consolidation_delivery_enabled",
    "consolidation_enabled_from_environment",
    "consolidation_panel_link",
    "consolidation_responsible_allowed",
    "consolidation_responsible_task_types",
    "consolidation_task_resolver_roles",
    "template_first_name",
]
