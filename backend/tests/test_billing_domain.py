"""Unit tests for billing plan ladder helpers (US-36 / RF-42)."""

from __future__ import annotations

from app.domain.billing import PLAN_ORDER, is_upgrade, plan_rank


def test_plan_rank_orders_tiers() -> None:
    assert plan_rank("ate_100") < plan_rank("101_200") < plan_rank("acima_201")
    assert plan_rank("desconhecido") == -1
    assert plan_rank(None) == -1


def test_is_upgrade_detects_promotion() -> None:
    assert is_upgrade("ate_100", "101_200") is True
    assert is_upgrade("101_200", "acima_201") is True


def test_is_upgrade_false_for_same_or_downgrade() -> None:
    assert is_upgrade("101_200", "101_200") is False
    assert is_upgrade("acima_201", "ate_100") is False


def test_plan_order_is_ascending() -> None:
    assert PLAN_ORDER == ("ate_100", "101_200", "acima_201")
