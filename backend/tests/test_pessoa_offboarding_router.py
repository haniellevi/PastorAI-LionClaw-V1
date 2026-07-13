"""M7B-W3.2A — router-level authz/validation (offline, FakeSession).

Sempre-on (sem Postgres): papel não-admin -> 403 (a checagem de role acontece
ANTES de qualquer query), Pessoa ausente/id inválido -> 404 (mesmo formato
usado para cross-tenant sob RLS — S4: nunca revela existência), motivo vazio
-> 422 (validação Pydantic). A matriz de bloqueadores e a transação de archive
em si precisam de Postgres real (JSONB/lock) — ver
``test_pessoa_offboarding_service.py``.

Mesma técnica de ``test_team_revoke.py``: sobrescreve ``get_current_user``
direto (sem tocar Clerk) + uma sessão fake mínima para a única query do
router (``select(Pessoa)``) — a lógica de preflight/archive em si nunca é
exercitada aqui (382/404/403 curto-circuitam antes do service).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.main import app
from app.routers.contacts import ArchiveContactRequest

_PESSOA_ID = "00000000-0000-0000-0000-0000000000b1"
_AUTH = {"Authorization": "Bearer good"}


class _Result:
    def __init__(self, scalar=None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _PessoaSession:
    """Roteia a única query do router (``select(Pessoa)``); ignora o resto."""

    def __init__(self, *, pessoa=None) -> None:
        self.pessoa = pessoa

    def execute(self, statement, params=None) -> _Result:
        return _Result(scalar=self.pessoa)

    def close(self) -> None:  # pragma: no cover - nada a liberar
        pass


def _user(roles: tuple[str, ...] = ("admin",)) -> CurrentUser:
    return CurrentUser(
        app_user_id="00000000-0000-0000-0000-0000000000a1",
        clerk_user_id="clerk_1",
        igreja_id="00000000-0000-0000-0000-000000000001",
        email="admin@igreja.com.br",
        nome="Admin",
        roles=frozenset(roles),
    )


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client(*, current_user: CurrentUser, pessoa=None) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_db] = lambda: _PessoaSession(pessoa=pessoa)
    return TestClient(app)


# ---------------------------------------------------------------------------
# 403 — papel não-admin (checagem de role, curto-circuita antes de tocar o DB)
# ---------------------------------------------------------------------------
def test_preflight_non_admin_is_forbidden() -> None:
    client = _client(current_user=_user(roles=("membro",)))
    resp = client.get(f"/contacts/{_PESSOA_ID}/offboarding-preflight", headers=_AUTH)
    assert resp.status_code == 403


def test_archive_non_admin_is_forbidden() -> None:
    client = _client(current_user=_user(roles=("lider_celula",)))
    resp = client.post(
        f"/contacts/{_PESSOA_ID}/archive", json={"motivo": "teste"}, headers=_AUTH
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 404 — Pessoa ausente / id inválido / cross-tenant (mesmo formato: nunca
# revela existência — S4). RLS já garante que um id de OUTRA igreja resolve
# para None; o fake modela exatamente esse caso.
# ---------------------------------------------------------------------------
def test_preflight_pessoa_not_found_is_404() -> None:
    client = _client(current_user=_user(), pessoa=None)
    resp = client.get(f"/contacts/{_PESSOA_ID}/offboarding-preflight", headers=_AUTH)
    assert resp.status_code == 404


def test_archive_pessoa_not_found_or_cross_tenant_is_404() -> None:
    client = _client(current_user=_user(), pessoa=None)
    resp = client.post(
        f"/contacts/{_PESSOA_ID}/archive", json={"motivo": "teste"}, headers=_AUTH
    )
    assert resp.status_code == 404


def test_preflight_invalid_uuid_is_404_not_500() -> None:
    client = _client(current_user=_user(), pessoa=None)
    resp = client.get("/contacts/not-a-uuid/offboarding-preflight", headers=_AUTH)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 422 — motivo obrigatório (validação Pydantic, não chega a rodar o endpoint)
# ---------------------------------------------------------------------------
def test_motivo_vazio_e_invalido() -> None:
    with pytest.raises(ValidationError):
        ArchiveContactRequest(motivo="")


def test_motivo_somente_espacos_e_invalido() -> None:
    with pytest.raises(ValidationError):
        ArchiveContactRequest(motivo="   ")


def test_archive_motivo_vazio_via_http_e_422() -> None:
    client = _client(current_user=_user())
    resp = client.post(
        f"/contacts/{_PESSOA_ID}/archive", json={"motivo": ""}, headers=_AUTH
    )
    assert resp.status_code == 422


def test_archive_sem_motivo_e_422() -> None:
    client = _client(current_user=_user())
    resp = client.post(f"/contacts/{_PESSOA_ID}/archive", json={}, headers=_AUTH)
    assert resp.status_code == 422
