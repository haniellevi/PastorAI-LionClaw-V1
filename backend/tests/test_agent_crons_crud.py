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
_CID2 = "00000000-0000-0000-0000-0000000000c2"


class _R:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class CronSession:
    """Routes auth (AppUser/UserRole) + Cron lookups by APPLYING the statement's
    own predicates, so the router's WHERE/ORDER BY are what is under test.

    For a Cron select, every `Column == value` in the WHERE is extracted and the
    store is filtered by ALL of them (id and/or igreja_id), then ordered by any
    ORDER BY columns. A by-id lookup (PUT) thus 404s on a wrong id OR a foreign
    tenant; the list (GET) returns the tenant's rows in nome order. Because the
    fake mirrors the SQL instead of re-implementing the filter in Python,
    dropping a predicate (igreja_id or id) or the ordering from the router makes
    the corresponding test fail — the protection is actually exercised.
    """

    def __init__(self, *, app_user, roles, store=None) -> None:
        self.app_user = app_user
        self.roles = roles
        self.store = store or []
        self.committed = False

    @staticmethod
    def _eq_predicates(statement) -> dict[str, str]:
        """{column_key: str(value)} for each `Col == bind` in the WHERE clause."""
        preds: dict[str, str] = {}
        clause = getattr(statement, "whereclause", None)
        stack = [clause] if clause is not None else []
        while stack:
            node = stack.pop()
            left = getattr(node, "left", None)
            right = getattr(node, "right", None)
            if left is not None and right is not None:
                key = getattr(left, "key", None)
                value = getattr(right, "value", None)
                if key is not None and value is not None:
                    preds[key] = str(value)
                continue
            stack.extend(getattr(node, "clauses", []) or [])
        return preds

    @staticmethod
    def _order_keys(statement) -> list[str]:
        return [
            key
            for clause in getattr(statement, "_order_by_clauses", ()) or ()
            if (key := getattr(clause, "key", None))
        ]

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is Cron:
            preds = self._eq_predicates(statement)
            rows = [
                c
                for c in self.store
                if all(str(getattr(c, k, None)) == v for k, v in preds.items())
            ]
            for key in reversed(self._order_keys(statement)):
                rows = sorted(rows, key=lambda c, k=key: getattr(c, k))
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
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
        make_cron(cron_id=_CID2, nome="De outra igreja", igreja_id=_OTHER),
    ]
    session = CronSession(app_user=make_app_user(), roles=["admin"], store=store)
    resp = _wire(app, session=session).get("/agent/crons", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert [c["nome"] for c in body] == ["Meu agendamento"]


def test_list_crons_sorted_by_nome(app) -> None:
    # Exercita o order_by(Cron.nome): inserido fora de ordem, sai ordenado.
    store = [
        make_cron(cron_id=_CID, nome="Zebra"),
        make_cron(cron_id=_CID2, nome="Alpha"),
    ]
    session = CronSession(app_user=make_app_user(), roles=["admin"], store=store)
    resp = _wire(app, session=session).get("/agent/crons", headers=_AUTH)
    assert resp.status_code == 200
    assert [c["nome"] for c in resp.json()] == ["Alpha", "Zebra"]


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
    assert session.committed is True


def test_update_cron_clears_gatilho(app) -> None:
    # Editar pode limpar o gatilho (cron vira só-frequência): PUT é substituição
    # total e gatilhoEstado=None é válido e persiste.
    cron = make_cron(gatilho_estado="relatorio_pendente")
    session = CronSession(app_user=make_app_user(), roles=["admin"], store=[cron])
    resp = _wire(app, session=session).put(
        f"/agent/crons/{_CID}",
        headers=_AUTH,
        json={"nome": cron.nome, "frequencia": cron.frequencia, "ativo": True},
    )
    assert resp.status_code == 200
    assert resp.json()["gatilhoEstado"] is None
    assert cron.gatilho_estado is None


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
    # Cron exists, but belongs to another igreja → filtered out by the igreja_id
    # predicate (dropping it from the router would make this test fail).
    other = make_cron(cron_id=_CID, igreja_id=_OTHER)
    session = CronSession(app_user=make_app_user(), roles=["admin"], store=[other])
    resp = _wire(app, session=session).put(
        f"/agent/crons/{_CID}",
        headers=_AUTH,
        json={"nome": "X", "frequencia": "diaria", "ativo": True},
    )
    assert resp.status_code == 404
    assert session.committed is False


def test_update_cron_wrong_id_same_tenant_returns_404(app) -> None:
    # Same tenant, but the path id addresses a cron that doesn't exist → the
    # Cron.id predicate must 404 (dropping it from the router would fail here).
    session = CronSession(
        app_user=make_app_user(), roles=["admin"], store=[make_cron(cron_id=_CID)]
    )
    resp = _wire(app, session=session).put(
        f"/agent/crons/{_CID2}",
        headers=_AUTH,
        json={"nome": "X", "frequencia": "diaria", "ativo": True},
    )
    assert resp.status_code == 404
    assert session.committed is False


def test_update_cron_edits_only_addressed_row(app) -> None:
    # Two same-tenant crons: the PUT must edit ONLY the one named in the path.
    c1 = make_cron(cron_id=_CID, nome="Primeiro")
    c2 = make_cron(cron_id=_CID2, nome="Segundo")
    session = CronSession(app_user=make_app_user(), roles=["admin"], store=[c1, c2])
    resp = _wire(app, session=session).put(
        f"/agent/crons/{_CID2}",
        headers=_AUTH,
        json={"nome": "Só o segundo", "frequencia": "semanal", "ativo": True},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == _CID2
    assert c2.nome == "Só o segundo"
    assert c1.nome == "Primeiro"  # a outra linha não é tocada


def test_update_cron_rejects_invalid_uuid(app) -> None:
    # Path id is typed as uuid.UUID → malformed id 422s before any DB work.
    session = CronSession(
        app_user=make_app_user(), roles=["admin"], store=[make_cron()]
    )
    resp = _wire(app, session=session).put(
        "/agent/crons/not-a-uuid",
        headers=_AUTH,
        json={"nome": "X", "frequencia": "diaria", "ativo": True},
    )
    assert resp.status_code == 422
