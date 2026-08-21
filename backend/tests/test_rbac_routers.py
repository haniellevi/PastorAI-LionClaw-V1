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

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import RolePermission
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


# ---- matriz de permissões da sessão --------------------------------------
def test_get_role_permissions_allowed_for_membro_and_tenant_scoped(app) -> None:
    rows = [
        SimpleNamespace(papel="membro", tela="dashboard"),
        SimpleNamespace(papel="membro", tela="calendario"),
        SimpleNamespace(papel="lider_celula", tela="dashboard"),
        SimpleNamespace(papel="lider_celula", tela="minha-celula"),
        SimpleNamespace(papel="lider_celula", tela="central-celula"),
    ]

    class PermissionsSession(FakeSession):
        def execute(self, statement, params=None):
            descriptions = getattr(statement, "column_descriptions", None)
            if descriptions and descriptions[0].get("entity") is RolePermission:
                return SimpleNamespace(
                    scalars=lambda: SimpleNamespace(all=lambda: list(rows))
                )
            return super().execute(statement, params)

    app_user = make_app_user()
    session = PermissionsSession(
        app_user=app_user,
        roles=["membro"],
    )
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()

    resp = TestClient(app).get(
        "/roles/permissions?igrejaId=00000000-0000-0000-0000-000000000999",
        headers=_AUTH,
    )

    assert resp.status_code == 200
    assert resp.json()["matriz"]["membro"] == ["dashboard", "calendario"]
    assert resp.json()["matriz"]["lider_celula"] == [
        "dashboard",
        "minha-celula",
    ]
    assert "inbox" in resp.json()["matriz"]["operador"]
    # O cliente não escolhe o tenant: o seam fixa a sessão na igreja do token,
    # e a consulta de RolePermission fica sob a RLS dessa sessão.
    assert session.info["tenant_igreja_id"] == str(app_user.igreja_id)


def test_put_role_permissions_remains_forbidden_for_membro(app) -> None:
    resp = _client(app, ["membro"]).put(
        "/roles/permissions",
        json={"matriz": {"membro": ["dashboard"]}},
        headers=_AUTH,
    )
    assert resp.status_code == 403


def test_put_role_permissions_strips_central_grant_from_cell_leader(app) -> None:
    class WritablePermissionsSession(FakeSession):
        def delete(self, obj) -> None:
            raise AssertionError("fixture não deve ter linhas antigas")

    app_user = make_app_user()
    session = WritablePermissionsSession(app_user=app_user, roles=["admin"])
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()

    resp = TestClient(app).put(
        "/roles/permissions",
        json={
            "matriz": {
                "lider_celula": [
                    "dashboard",
                    "minha-celula",
                    "central-celula",
                ]
            }
        },
        headers=_AUTH,
    )

    assert resp.status_code == 200
    assert resp.json()["matriz"]["lider_celula"] == [
        "dashboard",
        "minha-celula",
    ]
    persisted = {
        (row.papel, row.tela)
        for row in session.added
        if isinstance(row, RolePermission)
    }
    assert ("lider_celula", "central-celula") not in persisted
    assert ("lider_celula", "minha-celula") in persisted
    assert session.commits == 1


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


# ---- papel autorizado passa o gate (não é barrado por 403) -----------------
def test_put_pipeline_allowed_role_passes_gate(app) -> None:
    # lider_consol passa o gate de papel; o fluxo segue (404 por pessoa ausente
    # no fake), mas NÃO é barrado por 403.
    resp = _client(app, ["lider_consol"]).put(
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


def test_comunicados_forbidden_for_pastor_by_default(app) -> None:
    # 'comunicados' é ADMIN_ONLY (Missão 7B-2): pastor sem o papel admin não
    # passa o gate, mesmo sendo pastor.
    resp = _client(app, ["pastor"]).get("/broadcasts", headers=_AUTH)
    assert resp.status_code == 403


def test_matrix_restricts_pastor_when_screen_removed(app) -> None:
    matrix = [("pastor", "dashboard")]  # pastor ficou só com dashboard
    resp = _client(app, ["pastor"], role_permissions=matrix).get(
        "/broadcasts", headers=_AUTH
    )
    assert resp.status_code == 403


def test_comunicados_forbidden_for_lider_celula_by_default(app) -> None:
    # lider_celula NÃO tem 'comunicados' no default.
    resp = _client(app, ["lider_celula"]).get("/broadcasts", headers=_AUTH)
    assert resp.status_code == 403


def test_matrix_cannot_grant_comunicados_to_non_admin(app) -> None:
    # Missão 7B-2: 'comunicados' é ADMIN_ONLY — mesmo uma linha explícita na
    # matriz do tenant (customização legada ou deliberada) concedendo a tela a
    # um papel não-admin não abre a rota. Fecha o caso de resquício em
    # role_permissions sobrevivendo à mudança de default.
    matrix = [("lider_celula", "dashboard"), ("lider_celula", "comunicados")]
    resp = _client(app, ["lider_celula"], role_permissions=matrix).get(
        "/broadcasts", headers=_AUTH
    )
    assert resp.status_code == 403


def test_admin_passes_screen_gate(app) -> None:
    # admin tem acesso implícito a qualquer tela.
    resp = _client(app, ["admin"]).get("/broadcasts", headers=_AUTH)
    assert resp.status_code not in (401, 403)
