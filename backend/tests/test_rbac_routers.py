"""Testes de 403 por papel nos routers reais (M0 — endurecer o RBAC).

Fecham a lacuna apontada na auditoria: a suíte testava o MECANISMO require_role
(em app sintético) mas não os endpoints reais — o que deixou passar leituras/
mutações sem gate de papel. Aqui confirmamos que um papel sem privilégio
('membro', o papel padrão de quem é convidado) recebe 403 em:
  - GET  /team               (expõe e-mail + papéis; só admin/pastor/lider_g12)
  - PUT  /pipeline           (mover pessoa na jornada)
  - POST /pipeline/fonovisita (registrar fonovisita)
e que um papel operacional passa o gate de papel (não 403). Offline com fakes.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_PID = "00000000-0000-0000-0000-0000000000b1"


def _client(app, roles: list[str]) -> TestClient:
    app.dependency_overrides[get_db] = lambda: FakeSession(
        app_user=make_app_user(), roles=roles
    )
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


# ---- leitura de equipe (PII) ----------------------------------------------
def test_get_team_forbidden_for_membro(app) -> None:
    resp = _client(app, ["membro"]).get("/team", headers=_AUTH)
    assert resp.status_code == 403


# ---- mutação da jornada ---------------------------------------------------
def test_put_pipeline_forbidden_for_membro(app) -> None:
    resp = _client(app, ["membro"]).put(
        "/pipeline", json={"pessoaId": _PID, "etapa": "consolidar"}, headers=_AUTH
    )
    assert resp.status_code == 403


def test_post_fonovisita_forbidden_for_membro(app) -> None:
    resp = _client(app, ["membro"]).post(
        "/pipeline/fonovisita", json={"pessoaId": _PID}, headers=_AUTH
    )
    assert resp.status_code == 403


# ---- papel operacional passa o gate (não é barrado por 403) ---------------
def test_put_pipeline_allowed_role_passes_gate(app) -> None:
    # lider_celula passa o gate de papel; o fluxo segue (404 por pessoa ausente
    # no fake), mas NÃO é barrado por 403.
    resp = _client(app, ["lider_celula"]).put(
        "/pipeline", json={"pessoaId": _PID, "etapa": "consolidar"}, headers=_AUTH
    )
    assert resp.status_code != 403


def test_post_fonovisita_allowed_role_passes_gate(app) -> None:
    resp = _client(app, ["lider_celula"]).post(
        "/pipeline/fonovisita", json={"pessoaId": _PID}, headers=_AUTH
    )
    assert resp.status_code != 403
