"""Regras puras da visão geral do dashboard (#2) — escopo por papel e
normalização das contagens. Sem I/O, testável.

Escopo (decisão do usuário 2026-06-23):
- admin/pastor e os líderes sênior (G12, consolidação) veem os totais da
  IGREJA INTEIRA.
- líder de célula vê só as pessoas das células que ELE lidera (filtro por
  celula_id no router, via AppUser.pessoa_id → celulas.lider_id).
- demais papéis (ex.: multiplicação, operador, membro) caem no escopo de
  célula, que sem células lideradas resulta em zeros.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

ADMIN_ROLE = "admin"

# Papéis com visão da igreja inteira no overview (admin é implícito).
FULL_OVERVIEW_ROLES: frozenset[str] = frozenset(
    {"pastor", "lider_g12", "lider_consol"}
)

# Buckets fixos das contagens (chaves sempre presentes, default 0).
# "sem_interesse" (CSIM) é um bucket próprio em porTipo: a pessoa CSIM entra aqui
# em vez do seu tipo, espelhando a exibição da UI (CSIM tem prioridade).
TIPO_BUCKETS: tuple[str, ...] = (
    "contato",
    "visitante",
    "discipulo",
    "membro",
    "lider",
    "pastor",
    "sem_interesse",
)
ETAPA_BUCKETS: tuple[str, ...] = ("ganhar", "consolidar", "discipular", "enviar")


def has_full_overview(roles: Iterable[str]) -> bool:
    """True se o usuário vê os totais da igreja inteira (admin implícito)."""
    role_set = set(roles)
    if ADMIN_ROLE in role_set:
        return True
    return bool(role_set & FULL_OVERVIEW_ROLES)


def normalize_counts(
    raw: Mapping[str | None, int], buckets: Iterable[str]
) -> dict[str, int]:
    """Garante todos os buckets presentes (default 0) e ignora chaves estranhas."""
    out = {b: 0 for b in buckets}
    for key, value in raw.items():
        if key in out:
            out[key] = int(value)
    return out
