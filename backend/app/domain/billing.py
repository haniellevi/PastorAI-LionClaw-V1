"""Billing plan ladder logic (US-36 / RF-42) — pure, side-effect-free helpers.

The plan ladder mirrors `fn_subscription_autoupgrade` in the DB triggers:
`ate_100` (<=100) -> `101_200` (<=200) -> `acima_201` (unlimited). The trigger
promotes the plan when the people count crosses the limit; these helpers let the
router reason about ordering (e.g. to notify the admin of an automatic upgrade).

Price and people-limit per plan are NOT hardcoded here — they live in the
`planos` table (migration 0012), edited by the master console (/admin/planos)
and read directly by the routers (subscription.py checkout + catalog,
platform_admin.py MRR/validation) so an edited price/limit takes effect
immediately without a code change.
"""

from __future__ import annotations

# Ordered ladder of plan tiers (lowest to highest porte).
PLAN_ORDER: tuple[str, ...] = ("ate_100", "101_200", "acima_201")


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
