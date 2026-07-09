"""Testes diretos do domínio de permissões (Missão 7B-2 — Pessoas/Comunicação
viram ADMIN_ONLY). Cobre `can_access_screen` sem passar pelo HTTP: garante que
nenhum papel não-admin acessa uma tela ADMIN_ONLY, mesmo com uma linha
explícita na matriz do tenant concedendo-a.
"""

from __future__ import annotations

from app.domain.permissions import ADMIN_ONLY, can_access_screen


def test_admin_only_screens_are_comunicados_and_contatos() -> None:
    assert ADMIN_ONLY == frozenset({"comunicados", "contatos"})


def test_non_admin_role_blocked_from_admin_only_screen_by_default() -> None:
    for screen in ADMIN_ONLY:
        assert can_access_screen(frozenset({"pastor"}), screen, {}) is False


def test_tenant_matrix_cannot_grant_admin_only_screen() -> None:
    # Resquício legado: uma linha de role_permissions do tenant concedendo a
    # tela a um papel não-admin. Antes desta regra, a matriz vencia; agora
    # ADMIN_ONLY é checado primeiro e nunca é delegável.
    for screen in ADMIN_ONLY:
        tenant_matrix = {"lider_celula": {screen}}
        assert (
            can_access_screen(frozenset({"lider_celula"}), screen, tenant_matrix)
            is False
        )


def test_dashboard_still_open_to_everyone() -> None:
    assert can_access_screen(frozenset({"membro"}), "dashboard", {}) is True
