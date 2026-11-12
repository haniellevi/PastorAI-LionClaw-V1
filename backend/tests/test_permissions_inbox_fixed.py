"""B3 (decisão de 12/11/2026): Conversas só para os papéis fixos da inbox."""

from __future__ import annotations

import pytest

from app.domain.conversations import INBOX_ROLES
from app.domain.permissions import can_access_screen, screens_for_role


@pytest.mark.parametrize("role", ["membro", "lider_mult"])
def test_saved_matrix_cannot_grant_inbox_outside_fixed_roles(role):
    matrix = {role: {"inbox", "calendario"}}
    assert "inbox" not in screens_for_role(role, matrix)
    assert can_access_screen(frozenset({role}), "inbox", matrix) is False
    assert "calendario" in screens_for_role(role, matrix)


@pytest.mark.parametrize("role", sorted(INBOX_ROLES))
def test_fixed_roles_keep_inbox_by_default_and_matrix_can_remove(role):
    assert can_access_screen(frozenset({role}), "inbox", {}) is True
    assert can_access_screen(frozenset({role}), "inbox", {role: {"inbox"}}) is True
    # A remoção feita pelo admin continua valendo: nada é ampliado.
    assert can_access_screen(frozenset({role}), "inbox", {role: {"dashboard"}}) is False


def test_no_new_role_gains_inbox_against_defaults():
    from app.domain.permissions import DEFAULT_PERMISSIONS

    for role, screens in DEFAULT_PERMISSIONS.items():
        assert ("inbox" in screens_for_role(role, {})) is ("inbox" in screens)
