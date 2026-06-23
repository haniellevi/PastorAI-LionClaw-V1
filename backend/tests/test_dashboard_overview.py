"""Visão geral do dashboard (#2): escopo por papel + normalização das contagens.

Cobre o domínio puro (has_full_overview, normalize_counts) e a GARANTIA de
escopo no endpoint: quem não tem visão completa e não lidera células recebe
zeros (não vaza os totais da igreja).
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Celula, RolePermission, UserRole
from app.db.session import get_db
from app.domain.dashboard_overview import (
    ETAPA_BUCKETS,
    TIPO_BUCKETS,
    has_full_overview,
    normalize_counts,
)
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_OVERVIEW = "/dashboard/overview"


# ---- domínio puro ---------------------------------------------------------
def test_has_full_overview_admin_pastor_and_senior() -> None:
    assert has_full_overview(["admin"]) is True
    assert has_full_overview(["pastor"]) is True
    assert has_full_overview(["lider_g12"]) is True
    assert has_full_overview(["lider_consol"]) is True


def test_has_full_overview_scoped_roles() -> None:
    # Só admin/pastor/G12/consolidação veem tudo; os demais caem no escopo célula.
    assert has_full_overview(["lider_celula"]) is False
    assert has_full_overview(["lider_mult"]) is False
    assert has_full_overview(["operador"]) is False
    assert has_full_overview(["membro"]) is False
    assert has_full_overview([]) is False
    # Papel acumulado sênior amplia: célula + g12 => visão completa.
    assert has_full_overview(["lider_celula", "lider_g12"]) is True


def test_normalize_counts_fills_buckets_and_ignores_unknown() -> None:
    out = normalize_counts({"visitante": 3, "sem_interesse": 1, "xpto": 9}, TIPO_BUCKETS)
    assert out["visitante"] == 3
    assert out["sem_interesse"] == 1
    assert out["contato"] == 0  # bucket ausente vira 0
    assert "xpto" not in out  # chave estranha é ignorada
    etapa = normalize_counts({"ganhar": 5}, ETAPA_BUCKETS)
    assert etapa == {"ganhar": 5, "consolidar": 0, "discipular": 0, "enviar": 0}


# ---- endpoint: garantia de escopo (zeros para quem não deve ver) ----------
class _Res:
    def __init__(self, *, scalar=None, scalars=None, rows=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def all(self):
        return list(self._rows)


class DashboardSession:
    """Roteia auth + lookups do overview. Foca nos caminhos de escopo vazio."""

    def __init__(self, *, app_user, roles, pessoa_id=None, cell_ids=None) -> None:
        self.app_user = app_user
        self.roles = roles
        self.pessoa_id = pessoa_id
        self.cell_ids = cell_ids or []

    def execute(self, statement, params=None) -> _Res:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        if not descs:
            return _Res()
        d0 = descs[0]
        ent = d0.get("entity")
        name = d0.get("name")
        if ent is AppUser:
            # select(AppUser) (auth) vs select(AppUser.pessoa_id) (escopo).
            if name == "pessoa_id":
                return _Res(scalar=self.pessoa_id)
            return _Res(scalar=self.app_user)
        if ent is RolePermission:
            return _Res(rows=[])  # matriz vazia => defaults (dashboard sempre ok)
        if ent is UserRole:
            return _Res(scalars=self.roles)
        if ent is Celula and name == "id":
            return _Res(scalars=self.cell_ids)
        return _Res()

    def commit(self) -> None:  # pragma: no cover
        pass

    def close(self) -> None:  # pragma: no cover
        pass


def _wire(app, session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def _assert_empty(body: dict) -> None:
    assert body["scope"] == "celula"
    assert body["total"] == 0
    assert body["decisoesJesus"] == 0
    assert body["celulasAtivas"] == 0
    assert body["semInteresse"] == 0
    assert set(body["porTipo"]) == set(TIPO_BUCKETS)
    assert all(v == 0 for v in body["porTipo"].values())
    assert all(v == 0 for v in body["porEtapa"].values())


def test_overview_cell_leader_without_linked_pessoa_is_empty(app) -> None:
    session = DashboardSession(
        app_user=make_app_user(), roles=["lider_celula"], pessoa_id=None
    )
    resp = _wire(app, session).get(_OVERVIEW, headers=_AUTH)
    assert resp.status_code == 200
    _assert_empty(resp.json())


def test_overview_cell_leader_without_cells_is_empty(app) -> None:
    session = DashboardSession(
        app_user=make_app_user(),
        roles=["lider_celula"],
        pessoa_id="00000000-0000-0000-0000-0000000000f1",
        cell_ids=[],
    )
    resp = _wire(app, session).get(_OVERVIEW, headers=_AUTH)
    assert resp.status_code == 200
    _assert_empty(resp.json())


def test_overview_member_is_empty(app) -> None:
    # membro não tem visão completa nem lidera células => zeros (sem vazamento).
    session = DashboardSession(
        app_user=make_app_user(), roles=["membro"], pessoa_id=None
    )
    resp = _wire(app, session).get(_OVERVIEW, headers=_AUTH)
    assert resp.status_code == 200
    _assert_empty(resp.json())
