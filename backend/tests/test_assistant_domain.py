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
from app.domain.permissions import ADMIN_ONLY

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


def test_admin_only_screens_stripped_even_with_legacy_role_permissions_grant() -> None:
    """M7B-FIX-ASSISTANT-PERMISSIONS: `pastor` em _ROLE_MAP ainda concede
    "comunicados" (customização de tenant salva antes da regra ADMIN_ONLY) —
    tem que sumir do resultado, fail-closed, igual `can_access_screen`."""
    allowed = allowed_screens_for_roles(_ROLE_MAP, ["pastor"])
    assert not (allowed & ADMIN_ONLY)


def test_admin_still_sees_admin_only_screens() -> None:
    allowed = allowed_screens_for_roles(_ROLE_MAP, ["admin"])
    assert ADMIN_ONLY <= allowed


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


def test_never_suggests_admin_only_screen_for_non_admin_even_on_keyword_match() -> None:
    """M7B-FIX-ASSISTANT-PERMISSIONS: mesmo com o marcador legado concedendo
    "comunicados" a pastor E o texto batendo a keyword de intenção, o
    assistente não pode sugerir a tela admin-only."""
    allowed = allowed_screens_for_roles(_ROLE_MAP, ["pastor"])
    telas = suggest_screens("preciso enviar um comunicado agora", allowed)
    assert "comunicados" not in telas


def test_never_suggests_contatos_for_non_admin_even_with_legacy_grant() -> None:
    role_map = {"pastor": ["dashboard", "contatos"]}
    allowed = allowed_screens_for_roles(role_map, ["pastor"])
    assert "contatos" not in allowed
    telas = suggest_screens("preciso do cadastro de pessoa", allowed)
    assert "contatos" not in telas
