"""Tests for the panel assistant routing rules (api-assistant — O5).

Pure tests: role-filtered screen resolution and intent→screen suggestion. No DB
or LLM involved. They guarantee the assistant only ever points to screens the
caller's role may open.
"""

from __future__ import annotations

from app.domain.assistant import (
    LOCKED_SCREENS,
    allowed_screens_for_roles,
    suggest_screens,
)

# A representative role_permissions projection (papel -> telas).
_ROLE_MAP = {
    "lider_celula": ["dashboard", "ganhar", "central-celula", "g12"],
    "lider_consol": ["dashboard", "consolidar", "consol-individual"],
    "pastor": [
        "dashboard",
        "ganhar",
        "consolidar",
        "consol-individual",
        "g12",
        "central-celula",
        "enviar",
        "comunicados",
        "calendario",
        "relatorios",
    ],
}


# ---- allowed_screens_for_roles -------------------------------------------
def test_admin_gets_all_known_screens_except_locked() -> None:
    allowed = allowed_screens_for_roles(_ROLE_MAP, ["admin"])
    assert "agente" in allowed and "permissoes" in allowed
    assert not (allowed & LOCKED_SCREENS)


def test_role_only_sees_its_permitted_screens_plus_dashboard() -> None:
    allowed = allowed_screens_for_roles(_ROLE_MAP, ["lider_celula"])
    assert allowed == {"dashboard", "ganhar", "central-celula", "g12"}
    # A config screen the role lacks must not appear.
    assert "permissoes" not in allowed
    assert "enviar" not in allowed


def test_accumulated_roles_union_their_screens() -> None:
    allowed = allowed_screens_for_roles(_ROLE_MAP, ["lider_celula", "lider_consol"])
    assert {"ganhar", "consolidar", "consol-individual", "g12"} <= allowed


# ---- suggest_screens ------------------------------------------------------
def test_suggests_only_allowed_screen_for_intent() -> None:
    allowed = allowed_screens_for_roles(_ROLE_MAP, ["lider_celula"])
    telas = suggest_screens("preciso ver a central de célula", allowed)
    assert "central-celula" in telas
    assert all(t in allowed for t in telas)


def test_does_not_suggest_screen_outside_role() -> None:
    # lider_celula cannot access 'enviar' (multiplicação) — never suggested.
    allowed = allowed_screens_for_roles(_ROLE_MAP, ["lider_celula"])
    telas = suggest_screens("quero registrar uma multiplicação", allowed)
    assert "enviar" not in telas


def test_pastor_gets_enviar_for_multiplication_intent() -> None:
    allowed = allowed_screens_for_roles(_ROLE_MAP, ["pastor"])
    telas = suggest_screens("quero agendar uma multiplicação de célula", allowed)
    assert "enviar" in telas


def test_falls_back_to_dashboard_when_no_intent_match() -> None:
    allowed = allowed_screens_for_roles(_ROLE_MAP, ["lider_celula"])
    telas = suggest_screens("bom dia, tudo bem?", allowed)
    assert telas == ["dashboard"]


def test_never_suggests_locked_screens() -> None:
    allowed = set(LOCKED_SCREENS) | {"dashboard", "consolidar"}
    telas = suggest_screens("universidade da vida e capacitação", allowed)
    assert not (set(telas) & LOCKED_SCREENS)
