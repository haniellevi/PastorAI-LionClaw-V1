"""Tests for GET /agent/crons and PUT /agent/crons/{id} (RF-33).

Covers the read/edit/soft-disable half of the cron CRUD that backs the
Agendamentos tab: auth + admin-only gating, tenant isolation on the list,
gatilho re-validation on edit, the soft-disable toggle (`ativo`), and the
cross-tenant 404 (the lookup is scoped to igreja_id, so a cron from another
igreja is never found). Mirrors the fake-session style of test_contacts_update.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Cron
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}

# Tenant of make_app_user() vs. another igreja used for cross-tenant checks.
_TENANT = "00000000-0000-0000-0000-000000000001"
_OTHER = "00000000-0000-0000-0000-000000000002"
_CID = "00000000-0000-0000-0000-0000000000c1"


class _R:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class CronSession:
    """Routes auth (AppUser/UserRole) + Cron lookups, scoped by igreja_id.

    Only crons whose igreja_id matches the current tenant are visible — the same
    scoping the router's WHERE clause and Postgres RLS enforce. A by-id lookup
    (PUT) returns the first visible cron or None; a list (GET) returns all of
    them. Crons from another igreja are therefore invisible (cross-tenant 404).
    """

    def __init__(self, *, app_user, roles, store=None) -> None:
        self.app_user = app_user
        self.roles = roles
        self.tenant = str(app_user.igreja_id)
        self.store = store or []
        self.committed = False

    def _visible(self) -> list:
        return [c for c in self.store if str(c.igreja_id) == self.tenant]

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is Cron:
            visible = self._visible()
            return _R(scalar=(visible[0] if visible else None), scalars=visible)
        return _R(scalars=self.roles)

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


def make_cron(
    *,
    cron_id: str = _CID,
    igreja_id: str = _TENANT,
    nome: str = "Cobrar relatórios",
    frequencia: str = "diaria",
    gatilho_estado: str | None = "relatorio_pendente",
    acao: str | None = None,
    ativo: bool = True,
):
    return SimpleNamespace(
        id=cron_id,
        igreja_id=igreja_id,
        nome=nome,
        frequencia=frequencia,
        gatilho_estado=gatilho_estado,
        acao=acao,
        ativo=ativo,
    )


def _wire(app, *, session, clerk=None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk or FakeClerk()
    return TestClient(app)


# ---- auth gating ----------------------------------------------------------
def test_list_crons_requires_auth(app) -> None:
    session = CronSession(app_user=make_app_user(), roles=["admin"])
    assert _wire(app, session=session).get("/agent/crons").status_code == 401


def test_update_cron_requires_auth(app) -> None:
    session = CronSession(app_user=make_app_user(), roles=["admin"])
    resp = _wire(app, session=session).put(
        f"/agent/crons/{_CID}",
        json={"nome": "X", "frequencia": "diaria", "ativo": True},
    )
    assert resp.status_code == 401


# ---- admin-only (config screens are admin-only — delta-005) ---------------
def test_list_crons_forbidden_for_non_admin(app) -> None:
    session = CronSession(app_user=make_app_user(), roles=["lider_celula"])
    resp = _wire(app, session=session).get("/agent/crons", headers=_AUTH)
    assert resp.status_code == 403


def test_update_cron_forbidden_for_non_admin(app) -> None:
    session = CronSession(
        app_user=make_app_user(), roles=["lider_celula"], store=[make_cron()]
    )
    resp = _wire(app, session=session).put(
        f"/agent/crons/{_CID}",
        headers=_AUTH,
        json={"nome": "X", "frequencia": "diaria", "ativo": True},
    )
    assert resp.status_code == 403


# ---- list + tenant isolation ----------------------------------------------
def test_list_crons_returns_only_tenant_rows(app) -> None:
    store = [
        make_cron(cron_id=_CID, nome="Meu agendamento", igreja_id=_TENANT),
        make_cron(
            cron_id="00000000-0000-0000-0000-0000000000c2",
            nome="De outra igreja",
            igreja_id=_OTHER,
        ),
    ]
    session = CronSession(app_user=make_app_user(), roles=["admin"], store=store)
    resp = _wire(app, session=session).get("/agent/crons", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert [c["nome"] for c in body] == ["Meu agendamento"]


# ---- edit ------------------------------------------------------------------
def test_update_cron_changes_fields_and_commits(app) -> None:
    cron = make_cron(
        nome="Antigo", frequencia="diaria", gatilho_estado="visitante_novo", ativo=True
    )
    session = CronSession(app_user=make_app_user(), roles=["admin"], store=[cron])
    resp = _wire(app, session=session).put(
        f"/agent/crons/{_CID}",
        headers=_AUTH,
        json={
            "nome": "Novo nome",
            "frequencia": "semanal",
            "gatilhoEstado": "relatorio_pendente",
            "acao": "Cobrar líderes",
            "ativo": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["nome"] == "Novo nome"
    assert body["frequencia"] == "semanal"
    assert body["gatilhoEstado"] == "relatorio_pendente"
    assert body["acao"] == "Cobrar líderes"
    assert cron.nome == "Novo nome"
    assert session.committed is True


def test_update_cron_soft_disables_via_ativo_toggle(app) -> None:
    cron = make_cron(nome="Ativo agora", ativo=True)
    session = CronSession(app_user=make_app_user(), roles=["admin"], store=[cron])
    resp = _wire(app, session=session).put(
        f"/agent/crons/{_CID}",
        headers=_AUTH,
        json={
            "nome": cron.nome,
            "frequencia": cron.frequencia,
            "gatilhoEstado": cron.gatilho_estado,
            "ativo": False,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ativo"] is False
    assert cron.ativo is False


# ---- validation ------------------------------------------------------------
def test_update_cron_rejects_invalid_gatilho(app) -> None:
    session = CronSession(
        app_user=make_app_user(), roles=["admin"], store=[make_cron()]
    )
    resp = _wire(app, session=session).put(
        f"/agent/crons/{_CID}",
        headers=_AUTH,
        json={"nome": "X", "frequencia": "diaria", "gatilhoEstado": "voar", "ativo": True},
    )
    assert resp.status_code == 422


# ---- not found / cross-tenant ---------------------------------------------
def test_update_cron_not_found(app) -> None:
    session = CronSession(app_user=make_app_user(), roles=["admin"], store=[])
    resp = _wire(app, session=session).put(
        f"/agent/crons/{_CID}",
        headers=_AUTH,
        json={"nome": "X", "frequencia": "diaria", "ativo": True},
    )
    assert resp.status_code == 404


def test_update_cron_cross_tenant_returns_404(app) -> None:
    # Cron exists, but belongs to another igreja → invisible under tenant scope.
    other = make_cron(cron_id=_CID, igreja_id=_OTHER)
    session = CronSession(app_user=make_app_user(), roles=["admin"], store=[other])
    resp = _wire(app, session=session).put(
        f"/agent/crons/{_CID}",
        headers=_AUTH,
        json={"nome": "X", "frequencia": "diaria", "ativo": True},
    )
    assert resp.status_code == 404
    assert session.committed is False
