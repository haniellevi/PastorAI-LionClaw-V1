"""Billing plan logic (US-36 / RF-42) — pure, side-effect-free helpers.

The plan ladder mirrors `fn_subscription_autoupgrade` in the DB triggers:
`ate_100` (<=100) -> `101_200` (<=200) -> `acima_201` (unlimited). The trigger
promotes the plan when the people count crosses the limit; these helpers let the
router reason about ordering (e.g. to notify the admin of an automatic upgrade)
and price the checkout deterministically.
"""

from __future__ import annotations

# Ordered ladder of plan tiers (lowest to highest porte).
PLAN_ORDER: tuple[str, ...] = ("ate_100", "101_200", "acima_201")

# People limit per plan (acima_201 is effectively unlimited).
PLAN_LIMIT: dict[str, int] = {
    "ate_100": 100,
    "101_200": 200,
    "acima_201": 999999,
}

# Monthly price per plan (BRL). Espelha o catálogo `planos` (PRD: 199/299/399),
# que o console master edita. Valor usado no checkout do Asaas.
# TODO: ler da tabela `planos` para a edição de preço do master valer no checkout.
PLAN_PRICE: dict[str, float] = {
    "ate_100": 199.0,
    "101_200": 299.0,
    "acima_201": 399.0,
}


def plan_rank(plano: str | None) -> int:
    """Return the ladder index of a plan, or -1 when unknown."""
    if plano is None:
        return -1
    try:
        return PLAN_ORDER.index(plano)
    except ValueError:
        return -1


def is_upgrade(previous: str | None, current: str | None) -> bool:
    """True when `current` is a strictly higher tier than `previous`."""
    return plan_rank(current) > plan_rank(previous)


def plan_price(plano: str) -> float:
    """Monthly price for a plan; 0.0 when the plan is unknown."""
    return PLAN_PRICE.get(plano, 0.0)


def plan_limit(plano: str) -> int | None:
    """People limit for a plan; None when the plan is unknown."""
    return PLAN_LIMIT.get(plano)
