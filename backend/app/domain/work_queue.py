"""Work-queue role gating and internal-message formatting (F5 / delta-006).

Two pure concerns:

1. Role gating: each work_queue item type can only be listed/actioned by the
   roles able to resolve it (delta-006). `admin` always passes (implicit
   access, consistent with require_role).
2. Internal message: an internal note posted to the conversation is prefixed
   with the author's identity as "Nome [papel]: mensagem", where `papel` is the
   author's most senior accumulated role.
"""

from __future__ import annotations

from collections.abc import Iterable

ADMIN_ROLE = "admin"

# Roles allowed to resolve each work_queue_items.tipo (besides admin).
TIPO_RESOLVER_ROLES: dict[str, frozenset[str]] = {
    "visitante": frozenset({"lider_celula", "lider_consol", "lider_g12", "pastor"}),
    "atendimento": frozenset({"lider_g12", "pastor"}),
    "relatorio": frozenset({"lider_celula", "lider_g12", "pastor"}),
    "conectar_celula": frozenset({"lider_consol", "lider_g12", "pastor"}),
    "fonovisita": frozenset({"lider_consol", "lider_celula", "lider_g12", "pastor"}),
}

# Seniority order (most senior first) used to pick the display role for a note.
ROLE_SENIORITY: tuple[str, ...] = (
    "admin",
    "pastor",
    "lider_g12",
    "lider_consol",
    "lider_celula",
    "lider_mult",
    "membro",
)

# Human-readable label per role for the message prefix.
ROLE_LABELS: dict[str, str] = {
    "admin": "Admin",
    "pastor": "Pastor",
    "lider_g12": "Líder G12",
    "lider_consol": "Líder de Consolidação",
    "lider_celula": "Líder de Célula",
    "lider_mult": "Líder de Multiplicação",
    "membro": "Membro",
}


def can_resolve(roles: Iterable[str], tipo: str) -> bool:
    """True if any of `roles` can resolve a work item of `tipo`.

    `admin` passes for every type; unknown types are admin-only.
    """
    role_set = set(roles)
    if ADMIN_ROLE in role_set:
        return True
    allowed = TIPO_RESOLVER_ROLES.get(tipo, frozenset())
    return bool(role_set & allowed)


def resolvable_tipos(roles: Iterable[str]) -> set[str]:
    """The set of work item types these roles may list/action.

    `admin` gets every known type.
    """
    role_set = set(roles)
    if ADMIN_ROLE in role_set:
        return set(TIPO_RESOLVER_ROLES)
    return {
        tipo for tipo, allowed in TIPO_RESOLVER_ROLES.items() if role_set & allowed
    }


def primary_role(roles: Iterable[str]) -> str:
    """Most senior role among `roles` (for display); "membro" as fallback."""
    role_set = set(roles)
    for role in ROLE_SENIORITY:
        if role in role_set:
            return role
    return "membro"


def format_internal_message(nome: str, roles: Iterable[str], mensagem: str) -> str:
    """Build the "Nome [papel]: mensagem" internal-note body."""
    role = primary_role(roles)
    label = ROLE_LABELS.get(role, role)
    return f"{nome} [{label}]: {mensagem}"
