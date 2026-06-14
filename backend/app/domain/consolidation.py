"""Consolidation track rules (US-37/38/39/40 — delta-018/021/041).

Pure, I/O-free helpers for the advanced G12 cycle:

- Launching a decision opens a consolidation. The visitante flow has a 24h
  connection deadline; the celula flow (fluxo A) links a cell with no deadline.
- The individual track advances stage by stage. Stage confirmation is gated by
  identity: only the consolidation's responsavel_id (consolidador) may confirm.
- Concluding the consolidation is blocked while any mandatory stage is pending;
  progress reflects the confirmed mandatory stages.
"""

from __future__ import annotations

from collections.abc import Iterable

# Roles allowed to launch decisions / manage consolidations (US-37/38).
# admin always passes via CurrentUser.has_any_role (implicit access).
CONSOLIDATION_ROLES: list[str] = ["lider_consol", "pastor"]

# decision_vinculo enum (SPEC 2.1).
VINCULO_CELULA = "celula"
VINCULO_VISITANTE = "visitante"
VALID_VINCULOS: frozenset[str] = frozenset({VINCULO_CELULA, VINCULO_VISITANTE})

# Connection deadline for the visitante flow (fluxo B).
CONNECTION_DEADLINE_HOURS = 24

# Canonical individual-track stages (consolidacao_etapas.etapa — SPEC 2.1).
# `visita_n` (repeated follow-up visits) are optional and not part of the gate.
ETAPA_INICIAL = "aceitou_jesus"
MANDATORY_ETAPAS: tuple[str, ...] = (
    "aceitou_jesus",
    "conectou_celula",
    "fonovisita",
)
# Known confirmable stages (mandatory plus the open-ended visita_n family).
VALID_ETAPAS: frozenset[str] = frozenset(MANDATORY_ETAPAS)


def is_valid_etapa(etapa: str) -> bool:
    """True for a known mandatory stage or any `visita_<n>` follow-up visit."""
    if etapa in VALID_ETAPAS:
        return True
    return etapa.startswith("visita_") and etapa[len("visita_"):].isdigit()


def compute_progresso(confirmed: Iterable[str]) -> int:
    """Progress percent (0-100) from the confirmed mandatory stages."""
    confirmed_set = set(confirmed)
    done = sum(1 for etapa in MANDATORY_ETAPAS if etapa in confirmed_set)
    return round(done * 100 / len(MANDATORY_ETAPAS))


def pending_mandatory(confirmed: Iterable[str]) -> set[str]:
    """Mandatory stages still missing from the confirmed set."""
    confirmed_set = set(confirmed)
    return {etapa for etapa in MANDATORY_ETAPAS if etapa not in confirmed_set}


def can_conclude(confirmed: Iterable[str]) -> bool:
    """A consolidation may only be concluded with no mandatory stage pending."""
    return not pending_mandatory(confirmed)
