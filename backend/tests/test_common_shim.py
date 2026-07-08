"""Testes unitários do shim fail-closed ``ensure_tenant_context`` (PR4+ / OQ#3).

Após a migração dos 26 routers, ``ensure_tenant_context`` deixou de RE-SETAR o
escopo de RLS e virou um SHIM DE ASSERT: ele apenas verifica que a sessão já foi
marcada como tenant-scoped (pelo ``get_current_user``/seam) no MESMO igreja do
usuário autenticado, e FALHA (``TenantScopeError``) caso contrário — nunca
degrada para "seguir sem escopo". Estes testes provam esse contrato fail-closed,
SEM Postgres real (rodam sempre, offline).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db.tenant_session import TENANT_IGREJA_KEY, TenantScopeError
from app.routers._common import ensure_tenant_context

IGREJA_A = "0a0a0a0a-0000-0000-0000-00000000000a"
IGREJA_B = "0b0b0b0b-0000-0000-0000-00000000000b"


class _FakeSession:
    """Sessão fake: só o dict ``.info`` importa para o shim (duck typing)."""

    def __init__(self) -> None:
        self.info: dict = {}


def _user(igreja_id: str) -> SimpleNamespace:
    """CurrentUser mínimo — o shim só lê ``.igreja_id``."""
    return SimpleNamespace(igreja_id=igreja_id)


def test_shim_passes_when_session_marked_matches_user() -> None:
    """Sessão marcada no igreja do usuário → shim é um no-op silencioso."""
    session = _FakeSession()
    session.info[TENANT_IGREJA_KEY] = IGREJA_A

    # Não deve levantar.
    ensure_tenant_context(session, _user(IGREJA_A))


def test_shim_raises_when_session_not_marked() -> None:
    """Sessão sem marca (seam não ativado) → fail-closed."""
    session = _FakeSession()

    with pytest.raises(TenantScopeError):
        ensure_tenant_context(session, _user(IGREJA_A))


def test_shim_raises_when_marked_other_tenant() -> None:
    """Sessão pinada em OUTRO igreja → fail-closed (não deixa passar)."""
    session = _FakeSession()
    session.info[TENANT_IGREJA_KEY] = IGREJA_B

    with pytest.raises(TenantScopeError):
        ensure_tenant_context(session, _user(IGREJA_A))
