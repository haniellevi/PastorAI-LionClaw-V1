"""Telas CENTRAL_ONLY vencem a matriz PERSISTIDA (REPORT-SOT-REMEDIATION-1).

Remover `relatorios` só de ``DEFAULT_PERMISSIONS`` não protegia tenants que já
tinham salvo ``role_permissions``: com ``operador -> relatorios`` gravado,
``can_access_screen`` devolvia True, o AppShell renderizava #relatorios e o
``GET /reports`` (``require_central``) respondia 403.

A regra agora é aplicada ANTES da matriz — igual ao tratamento de ADMIN_ONLY —
sem apagar nem alterar as linhas já salvas: a concessão incompatível é apenas
ignorada para estas telas.
"""

from __future__ import annotations

import pytest

from app.domain.assistant import allowed_screens_for_roles
from app.domain.permissions import (
    CENTRAL_ONLY,
    CENTRAL_ROLE,
    can_access_screen,
    screens_for_role,
)

RELATORIOS = "relatorios"

NAO_CENTRAL = ["operador", "lider_celula", "lider_g12", "lider_mult", "lider_consol", "membro"]


def test_relatorios_is_declared_central_only() -> None:
    assert RELATORIOS in CENTRAL_ONLY
    assert CENTRAL_ROLE == "pastor"


# ---------------------------------------------------------------------------
# Matriz customizada persistida NÃO reabre a tela
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("papel", NAO_CENTRAL)
def test_persisted_matrix_granting_relatorios_is_ignored(papel: str) -> None:
    """O caso do finding: linha salva `papel -> relatorios` não vale."""
    matrix = {papel: {RELATORIOS}}
    assert can_access_screen(frozenset({papel}), RELATORIOS, matrix) is False
    assert RELATORIOS not in screens_for_role(papel, matrix)


@pytest.mark.parametrize("papel", NAO_CENTRAL)
def test_default_matrix_also_denies_relatorios(papel: str) -> None:
    assert can_access_screen(frozenset({papel}), RELATORIOS, {}) is False


def test_accumulated_roles_do_not_unlock_relatorios() -> None:
    """Somar papéis não-Central continua sem abrir a tela."""
    matrix = {"operador": {RELATORIOS}, "lider_celula": {RELATORIOS}}
    roles = frozenset({"operador", "lider_celula"})
    assert can_access_screen(roles, RELATORIOS, matrix) is False


# ---------------------------------------------------------------------------
# pastor continua permitido (default e customizado)
# ---------------------------------------------------------------------------
def test_pastor_keeps_relatorios_by_default() -> None:
    assert can_access_screen(frozenset({"pastor"}), RELATORIOS, {}) is True
    assert RELATORIOS in screens_for_role("pastor", {})


def test_pastor_keeps_relatorios_with_custom_matrix() -> None:
    matrix = {"pastor": {RELATORIOS, "inbox"}}
    assert can_access_screen(frozenset({"pastor"}), RELATORIOS, matrix) is True


def test_pastor_accumulated_with_non_central_role_still_sees_relatorios() -> None:
    matrix = {"pastor": {RELATORIOS}, "operador": {"inbox"}}
    roles = frozenset({"pastor", "operador"})
    assert can_access_screen(roles, RELATORIOS, matrix) is True


def test_custom_matrix_that_omits_relatorios_denies_pastor() -> None:
    """A regra não CONCEDE nada: só remove. Pastor sem a tela na matriz não entra."""
    assert can_access_screen(frozenset({"pastor"}), RELATORIOS, {"pastor": {"inbox"}}) is False


# ---------------------------------------------------------------------------
# Nenhuma regressão nas demais telas
# ---------------------------------------------------------------------------
def test_custom_matrix_keeps_other_screens_for_non_central_roles() -> None:
    matrix = {"operador": {"inbox", "ganhar", "celulas", RELATORIOS}}
    roles = frozenset({"operador"})
    for tela in ("inbox", "ganhar", "celulas", "dashboard"):
        assert can_access_screen(roles, tela, matrix) is True, tela
    assert can_access_screen(roles, RELATORIOS, matrix) is False


def test_screens_for_role_only_removes_central_only() -> None:
    matrix = {"lider_celula": {"inbox", "minha-celula", RELATORIOS}}
    screens = screens_for_role("lider_celula", matrix)
    assert screens == frozenset({"inbox", "minha-celula", "dashboard"})


def test_dashboard_still_granted_to_everyone() -> None:
    assert can_access_screen(frozenset({"membro"}), "dashboard", {}) is True


# ---------------------------------------------------------------------------
# Assistente não pode SUGERIR uma tela que responderia 403
# ---------------------------------------------------------------------------
def test_assistant_does_not_suggest_relatorios_to_non_central() -> None:
    allowed = allowed_screens_for_roles(
        {"operador": ["inbox", "ganhar", RELATORIOS]}, ["operador"]
    )
    assert RELATORIOS not in allowed
    assert "inbox" in allowed


def test_assistant_still_suggests_relatorios_to_pastor() -> None:
    allowed = allowed_screens_for_roles({"pastor": ["inbox", RELATORIOS]}, ["pastor"])
    assert RELATORIOS in allowed


def test_assistant_admin_keeps_implicit_access() -> None:
    allowed = allowed_screens_for_roles({}, ["admin"])
    assert RELATORIOS in allowed
