"""Person pipeline state machine rules (F2 / delta-013 / delta-031).

The database trigger `trg_promote_pipeline` auto-advances a person when the
promotion criteria are met (presencas_celula >= 3 OR aceitou_jesus). For an
explicit, operator-driven move (PUT /pipeline) we must validate the requested
transition *before* writing, so a visitante is never promoted past "ganhar"
without meeting those same criteria.

These helpers are pure: they take the current person state plus the requested
target and answer whether the transition is allowed.
"""

from __future__ import annotations

from dataclasses import dataclass

# Canonical G12 stage order (pessoa_etapa enum).
ETAPA_ORDER: tuple[str, ...] = ("ganhar", "consolidar", "discipular", "enviar")
VALID_ETAPAS: frozenset[str] = frozenset(ETAPA_ORDER)

# Sub-stages (pessoa_subetapa enum).
VALID_SUBETAPAS: frozenset[str] = frozenset(
    {"novo_contato", "visitante", "em_consolidacao", "consolidado"}
)

VISITANTE_TIPO = "visitante"
CONTATO_TIPO = "contato"
# Estados de entrada (etapa "ganhar"): só saem de "ganhar" com os critérios F2.
ENTRY_TIPOS: frozenset[str] = frozenset({CONTATO_TIPO, VISITANTE_TIPO})


@dataclass(frozen=True)
class TransitionResult:
    """Outcome of validating a pipeline transition request."""

    allowed: bool
    reason: str | None = None


def etapa_rank(etapa: str | None) -> int:
    """Numeric rank of a stage; unknown/None sorts before "ganhar"."""
    if etapa in ETAPA_ORDER:
        return ETAPA_ORDER.index(etapa)
    return -1


def meets_promotion_criteria(presencas_celula: int, aceitou_jesus: bool) -> bool:
    """F2 promotion gate: 3+ cell attendances OR a recorded decision."""
    return (presencas_celula or 0) >= 3 or bool(aceitou_jesus)


def validate_transition(
    *,
    current_tipo: str | None,
    current_etapa: str | None,
    target_etapa: str,
    target_subetapa: str | None,
    presencas_celula: int,
    aceitou_jesus: bool,
) -> TransitionResult:
    """Validate an explicit etapa/subetapa change for a person.

    Rules:
      - target_etapa must be a known stage; target_subetapa (when given) too.
      - A contato/visitante may only be promoted beyond "ganhar" once the F2
        criteria are satisfied (presencas_celula >= 3 OR aceitou_jesus). Moving
        within or back to "ganhar" is always allowed.
    """
    if target_etapa not in VALID_ETAPAS:
        return TransitionResult(False, f"Etapa inválida: {target_etapa}")
    if target_subetapa is not None and target_subetapa not in VALID_SUBETAPAS:
        return TransitionResult(False, f"Subetapa inválida: {target_subetapa}")

    is_promotion = etapa_rank(target_etapa) > etapa_rank(current_etapa)
    if (
        current_tipo in ENTRY_TIPOS
        and is_promotion
        and etapa_rank(target_etapa) > etapa_rank("ganhar")
    ):
        if not meets_promotion_criteria(presencas_celula, aceitou_jesus):
            return TransitionResult(
                False,
                "Contato ou visitante só pode ser promovido com 3+ presenças "
                "em célula ou decisão registrada",
            )
    return TransitionResult(True)
