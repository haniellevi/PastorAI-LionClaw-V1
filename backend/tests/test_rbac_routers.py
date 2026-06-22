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


def _client(app, roles: list[str], role_permissions=None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: FakeSession(
        app_user=make_app_user(), roles=roles, role_permissions=role_permissions or []
    )
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    # raise_server_exceptions=False: nos casos "passa o gate", o handler real roda
    # contra o fake e estoura (sem dados) -> vira 500. O que provamos é só que NÃO
    # foi barrado por 401/403 (passou auth + autorização).
    return TestClient(app, raise_server_exceptions=False)


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


# ---- M0c: a matriz role_permissions vira o gate real (require_screen) ------
def test_inbox_forbidden_for_membro(app) -> None:
    # 'membro' não tem 'inbox' no default; matriz vazia => usa o default.
    resp = _client(app, ["membro"]).get("/conversations", headers=_AUTH)
    assert resp.status_code == 403


def test_comunicados_forbidden_for_membro(app) -> None:
    resp = _client(app, ["membro"]).get("/broadcasts", headers=_AUTH)
    assert resp.status_code == 403


def test_comunicados_allowed_for_pastor_by_default(app) -> None:
    # pastor tem 'comunicados' no default => passa o gate (o handler erra no
    # fake, mas o ponto é que NÃO é 403).
    resp = _client(app, ["pastor"]).get("/broadcasts", headers=_AUTH)
    assert resp.status_code not in (401, 403)


def test_matrix_restricts_pastor_when_screen_removed(app) -> None:
    # O PONTO do M0c (restringir): o admin remove 'comunicados' do pastor na
    # matriz do tenant => pastor recebe 403 NA ROTA, não só some o menu.
    matrix = [("pastor", "dashboard")]  # pastor ficou só com dashboard
    resp = _client(app, ["pastor"], role_permissions=matrix).get(
        "/broadcasts", headers=_AUTH
    )
    assert resp.status_code == 403


def test_comunicados_forbidden_for_lider_celula_by_default(app) -> None:
    # lider_celula NÃO tem 'comunicados' no default.
    resp = _client(app, ["lider_celula"]).get("/broadcasts", headers=_AUTH)
    assert resp.status_code == 403


def test_matrix_grants_lider_celula_when_screen_added(app) -> None:
    # O PONTO do M0c (conceder): dar 'comunicados' ao lider_celula na matriz
    # abre a rota que o default negava.
    matrix = [("lider_celula", "dashboard"), ("lider_celula", "comunicados")]
    resp = _client(app, ["lider_celula"], role_permissions=matrix).get(
        "/broadcasts", headers=_AUTH
    )
    assert resp.status_code not in (401, 403)


def test_admin_passes_screen_gate(app) -> None:
    # admin tem acesso implícito a qualquer tela.
    resp = _client(app, ["admin"]).get("/broadcasts", headers=_AUTH)
    assert resp.status_code not in (401, 403)
