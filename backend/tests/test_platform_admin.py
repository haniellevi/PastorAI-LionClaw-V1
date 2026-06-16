"""Tests for the platform admin console (Super-Admin / US-42/43, RF-48/49).

The security-critical property under test: only an identity in the
``platform_admins`` allowlist reaches ``/admin/*``. A normal authenticated
tenant user — even a valid one — must be rejected with 403. Validated offline
with in-memory fakes, like the rest of the backend suite (no live DB/Clerk).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import (
    AgentConfig,
    AppUser,
    Igreja,
    LlmCredential,
    Pessoa,
    Plano,
    PlatformAdmin,
    PlatformAuditLog,
    RolePermission,
    UserRole,
)
from app.db.session import get_db
from app.services.brevo import BrevoError, get_brevo_client
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

# Catálogo padrão usado pelo fake quando o teste não fornece planos: os 3
# planos seedados na migration 0012 (espelha PRD: 199/299/399). Faz MRR e
# mensalidade continuarem batendo sem cada teste precisar montar o catálogo.
_DEFAULT_PLANO_PRECOS = [("ate_100", 199), ("101_200", 299), ("acima_201", 399)]


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _Scalars:
    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return list(self._items)


class _Result:
    def __init__(self, *, scalar=None, scalars=None, rows=None, scalar_one=None):
        self._scalar = scalar
        self._scalars = scalars or []
        self._rows = rows or []
        self._scalar_one = scalar_one

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar_one if self._scalar_one is not None else 0

    def scalars(self) -> _Scalars:
        return _Scalars(self._scalars)

    def all(self) -> list:
        return list(self._rows)


class PlatformDB:
    """Fake session routing the gate + router queries by mapped entity.

    The platform-admin gate runs two single-entity lookups (AppUser, then
    PlatformAdmin); the list/patch routers query Igreja and grouped counts.
    Routing mirrors the conftest FakeSession but covers the extra shapes.
    """

    def __init__(
        self,
        *,
        gate_app_user=None,
        admin_marker=None,
        igrejas=None,
        igreja_scalar=None,
        membros_rows=None,
        pessoas_rows=None,
        count_value: int = 0,
        planos=None,
        plano_scalar=None,
        plano_precos_rows=None,
        em_uso_rows=None,
        audit_rows=None,
        agent_config=None,
        llm_credential=None,
        igreja_admins=None,
        user_role=None,
    ) -> None:
        self.gate_app_user = gate_app_user
        self.admin_marker = admin_marker
        self.igrejas = igrejas or []
        self.igreja_scalar = igreja_scalar
        self.membros_rows = membros_rows or []
        self.pessoas_rows = pessoas_rows or []
        self.count_value = count_value
        # Catálogo de planos (migration 0012). plano_precos_rows alimenta MRR /
        # mensalidade / validação de plano; default = os 3 planos seedados.
        self.planos = planos or []
        self.plano_scalar = plano_scalar
        self.plano_precos_rows = (
            plano_precos_rows
            if plano_precos_rows is not None
            else list(_DEFAULT_PLANO_PRECOS)
        )
        self.em_uso_rows = em_uso_rows or []
        self.audit_rows = audit_rows or []
        self.agent_config = agent_config
        self.llm_credential = llm_credential
        self.igreja_admins = igreja_admins or []
        self.user_role = user_role
        self.added: list = []
        self.deleted: list = []
        self.committed = False

    def execute(self, statement, params=None) -> _Result:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        entities = [d.get("entity") for d in descs]
        # Grouped aggregation: (chave, count) — duas colunas de saída.
        if len(descs) >= 2:
            if entities[0] is AppUser:
                return _Result(rows=self.membros_rows)
            if entities[0] is Pessoa:
                return _Result(rows=self.pessoas_rows)
            if entities[0] is Plano:  # select(Plano.codigo, Plano.preco_mensal)
                return _Result(rows=self.plano_precos_rows)
            if entities[0] is Igreja:  # select(Igreja.plano, count()) — em uso
                return _Result(rows=self.em_uso_rows)
            return _Result(rows=[])
        ent = entities[0] if entities else None
        if ent is AppUser:
            # scalar -> gate (clerk_user_id lookup); scalars -> admins da igreja.
            return _Result(scalar=self.gate_app_user, scalars=self.igreja_admins)
        if ent is PlatformAdmin:
            return _Result(scalar=self.admin_marker)
        if ent is Igreja:
            return _Result(scalar=self.igreja_scalar, scalars=self.igrejas)
        if ent is Plano:
            return _Result(scalar=self.plano_scalar, scalars=self.planos)
        if ent is PlatformAuditLog:
            return _Result(scalars=self.audit_rows)
        if ent is AgentConfig:
            return _Result(scalar=self.agent_config)
        if ent is LlmCredential:
            return _Result(scalar=self.llm_credential)
        if ent is UserRole:
            return _Result(scalar=self.user_role)
        # select(func.count()) — scalar count with no mapped entity.
        return _Result(scalar_one=self.count_value)

    def add(self, obj) -> None:
        self.added.append(obj)

    def delete(self, obj) -> None:
        self.deleted.append(obj)

    def flush(self) -> None:
        # Assign a primary key the way a real flush would, so the router can
        # read igreja.id / app_user.id between inserts.
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def commit(self) -> None:
        self.committed = True

    def refresh(self, obj) -> None:  # pragma: no cover - not exercised
        pass

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


class FakeMailer:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[str] = []

    def send_invite(self, to_email: str, nome: str, activation_link: str) -> None:
        if self.fail:
            raise BrevoError("falha simulada")
        self.sent.append(to_email)


def _wire(app, *, db, clerk, mailer=None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    if mailer is not None:
        app.dependency_overrides[get_brevo_client] = lambda: mailer
    return TestClient(app)


_AUTH = {"Authorization": "Bearer good"}


# ---------------------------------------------------------------------------
# Gate (the security boundary)
# ---------------------------------------------------------------------------
def test_admin_requires_token(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker="pa1")
    client = _wire(app, db=db, clerk=FakeClerk())
    assert client.get("/admin/igrejas").status_code == 401


def test_admin_blocks_unknown_identity(app) -> None:
    # Token verifies, but the identity maps to no app_user at all.
    db = PlatformDB(gate_app_user=None)
    client = _wire(app, db=db, clerk=FakeClerk(clerk_user_id="clerk_ghost"))
    assert client.get("/admin/igrejas", headers=_AUTH).status_code == 403


def test_admin_blocks_non_platform_admin(app) -> None:
    # A perfectly valid tenant user that is NOT on the platform allowlist.
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker=None)
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.get("/admin/igrejas", headers=_AUTH)
    assert resp.status_code == 403
    assert "plataforma" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /admin/me (console gate)
# ---------------------------------------------------------------------------
def test_admin_me_returns_identity(app) -> None:
    db = PlatformDB(
        gate_app_user=make_app_user(email="pr@x.com", nome="Raniel"),
        admin_marker="pa1",
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.get("/admin/me", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "pr@x.com"
    assert body["nome"] == "Raniel"


def test_admin_me_blocks_non_admin(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker=None)
    client = _wire(app, db=db, clerk=FakeClerk())
    assert client.get("/admin/me", headers=_AUTH).status_code == 403


# ---------------------------------------------------------------------------
# GET /admin/igrejas (cross-tenant listing)
# ---------------------------------------------------------------------------
def test_admin_lists_all_churches_with_counters(app) -> None:
    ig1 = SimpleNamespace(
        id="ig-1", nome="Igreja A", status="ativa", plano="ate_100", created_at=None
    )
    ig2 = SimpleNamespace(
        id="ig-2", nome="Igreja B", status="suspensa", plano=None, created_at=None
    )
    db = PlatformDB(
        gate_app_user=make_app_user(),
        admin_marker="pa1",
        igrejas=[ig1, ig2],
        membros_rows=[("ig-1", 3), ("ig-2", 1)],
        pessoas_rows=[("ig-1", 50)],
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.get("/admin/igrejas", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert [i["nome"] for i in body] == ["Igreja A", "Igreja B"]
    a = next(i for i in body if i["id"] == "ig-1")
    assert a["membros"] == 3 and a["pessoas"] == 50
    b = next(i for i in body if i["id"] == "ig-2")
    assert b["membros"] == 1 and b["pessoas"] == 0


# ---------------------------------------------------------------------------
# POST /admin/igrejas (provision)
# ---------------------------------------------------------------------------
def test_admin_create_rejects_bad_email(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker="pa1")
    client = _wire(app, db=db, clerk=FakeClerk(), mailer=FakeMailer())
    resp = client.post(
        "/admin/igrejas",
        headers=_AUTH,
        json={"nome": "Nova", "admin": {"nome": "Pastor", "email": "not-an-email"}},
    )
    assert resp.status_code == 422


def test_admin_create_rejects_unknown_plano(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker="pa1")
    client = _wire(app, db=db, clerk=FakeClerk(), mailer=FakeMailer())
    resp = client.post(
        "/admin/igrejas",
        headers=_AUTH,
        json={
            "nome": "Nova",
            "plano": "ilimitado",
            "admin": {"nome": "Pastor", "email": "p@nova.org"},
        },
    )
    assert resp.status_code == 422


def test_admin_creates_church_and_invites(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker="pa1")
    mailer = FakeMailer()
    client = _wire(app, db=db, clerk=FakeClerk(), mailer=mailer)
    resp = client.post(
        "/admin/igrejas",
        headers=_AUTH,
        json={
            "nome": "Nova Igreja",
            "plano": "ate_100",
            "admin": {"nome": "Pastor Novo", "email": "Pastor@Nova.org"},
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["igrejaId"] and body["adminUsuarioId"]
    assert body["emailEnviado"] is True
    # Email is normalized to lowercase by the validator before the invite.
    assert mailer.sent == ["pastor@nova.org"]
    assert db.committed is True


def test_admin_create_succeeds_even_if_email_fails(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker="pa1")
    mailer = FakeMailer(fail=True)
    client = _wire(app, db=db, clerk=FakeClerk(), mailer=mailer)
    resp = client.post(
        "/admin/igrejas",
        headers=_AUTH,
        json={"nome": "Nova", "admin": {"nome": "P", "email": "p@nova.org"}},
    )
    assert resp.status_code == 201
    assert resp.json()["emailEnviado"] is False
    assert db.committed is True


# ---------------------------------------------------------------------------
# PATCH /admin/igrejas/{id} (status/plano)
# ---------------------------------------------------------------------------
def test_admin_patch_requires_a_field(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker="pa1")
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.patch(
        "/admin/igrejas/00000000-0000-0000-0000-000000000009",
        headers=_AUTH,
        json={},
    )
    assert resp.status_code == 422


def test_admin_patch_rejects_bad_status(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker="pa1")
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.patch(
        "/admin/igrejas/00000000-0000-0000-0000-000000000009",
        headers=_AUTH,
        json={"status": "explodida"},
    )
    assert resp.status_code == 422


def test_admin_patch_updates_status(app) -> None:
    igreja = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000009",
        nome="Igreja X",
        status="ativa",
        plano=None,
        created_at=None,
    )
    db = PlatformDB(
        gate_app_user=make_app_user(),
        admin_marker="pa1",
        igreja_scalar=igreja,
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.patch(
        "/admin/igrejas/00000000-0000-0000-0000-000000000009",
        headers=_AUTH,
        json={"status": "suspensa"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "suspensa"
    assert igreja.status == "suspensa"
    assert db.committed is True


# ---------------------------------------------------------------------------
# POST /admin/login (login dedicado do console, isento do billing gate)
# ---------------------------------------------------------------------------
def test_admin_login_returns_token_for_master(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker="pa1")
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.post("/admin/login", json={"email": "pr@x.com", "password": "x"})
    assert resp.status_code == 200
    assert resp.json()["token"]


def test_admin_login_ignores_billing_block(app) -> None:
    # O ponto do M0b: master cuja igreja-casa está SUSPENSA ainda entra no
    # console (o login do tenant bloquearia; o do console não).
    db = PlatformDB(
        gate_app_user=make_app_user(igreja_status="suspensa"), admin_marker="pa1"
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.post("/admin/login", json={"email": "pr@x.com", "password": "x"})
    assert resp.status_code == 200
    assert resp.json()["token"]


def test_admin_login_blocks_non_master(app) -> None:
    # Credencial válida, mas a conta não está na allowlist de plataforma.
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker=None)
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.post("/admin/login", json={"email": "p@x.com", "password": "x"})
    assert resp.status_code == 401


def test_admin_login_rejects_bad_credentials(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker="pa1")
    client = _wire(app, db=db, clerk=FakeClerk(raise_login=True))
    resp = client.post("/admin/login", json={"email": "p@x.com", "password": "no"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# M1 — métricas globais e drill-down por igreja
# ---------------------------------------------------------------------------
def test_admin_metrics_global_view(app) -> None:
    ig_a = SimpleNamespace(status="ativa", plano="ate_100")
    ig_b = SimpleNamespace(status="suspensa", plano="101_200")
    ig_c = SimpleNamespace(status="ativa", plano="acima_201")
    db = PlatformDB(
        gate_app_user=make_app_user(),
        admin_marker="pa1",
        igrejas=[ig_a, ig_b, ig_c],
        count_value=0,
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.get("/admin/metrics", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["totalIgrejas"] == 3
    assert body["porStatus"] == {"ativa": 2, "suspensa": 1}
    assert body["porPlano"] == {"ate_100": 1, "101_200": 1, "acima_201": 1}
    # MRR conta só as ATIVAS com plano: 199 (ate_100) + 399 (acima_201) = 598.
    assert body["mrr"] == 598


def test_admin_metrics_blocks_non_master(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker=None)
    client = _wire(app, db=db, clerk=FakeClerk())
    assert client.get("/admin/metrics", headers=_AUTH).status_code == 403


def test_admin_igreja_detail_drilldown(app) -> None:
    igreja = SimpleNamespace(
        id="ig-1", nome="Igreja X", status="ativa", plano="ate_100", created_at=None
    )
    db = PlatformDB(
        gate_app_user=make_app_user(),
        admin_marker="pa1",
        igreja_scalar=igreja,
        count_value=7,
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.get(
        "/admin/igrejas/00000000-0000-0000-0000-000000000009", headers=_AUTH
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["nome"] == "Igreja X"
    assert body["membros"] == 7 and body["pessoas"] == 7 and body["celulas"] == 7
    assert body["mensalidade"] == 199  # plano ate_100
    assert body["assinatura"] is None  # sem linha em subscriptions no fake


def test_admin_igreja_detail_404(app) -> None:
    db = PlatformDB(
        gate_app_user=make_app_user(), admin_marker="pa1", igreja_scalar=None
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.get(
        "/admin/igrejas/00000000-0000-0000-0000-000000000009", headers=_AUTH
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /admin/igrejas/{id} (CRUD completo)
# ---------------------------------------------------------------------------
def test_admin_delete_igreja(app) -> None:
    igreja = SimpleNamespace(
        id="ig-1", nome="Igreja X", status="ativa", plano=None, created_at=None
    )
    db = PlatformDB(
        gate_app_user=make_app_user(), admin_marker="pa1", igreja_scalar=igreja
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.delete(
        "/admin/igrejas/00000000-0000-0000-0000-000000000009", headers=_AUTH
    )
    assert resp.status_code == 204
    assert db.deleted == [igreja]
    assert db.committed is True


def test_admin_delete_igreja_404(app) -> None:
    db = PlatformDB(
        gate_app_user=make_app_user(), admin_marker="pa1", igreja_scalar=None
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.delete(
        "/admin/igrejas/00000000-0000-0000-0000-000000000009", headers=_AUTH
    )
    assert resp.status_code == 404


def test_admin_delete_blocks_non_master(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker=None)
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.delete(
        "/admin/igrejas/00000000-0000-0000-0000-000000000009", headers=_AUTH
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# M2 — provisionar como pendente + aprovar (cascata)
# ---------------------------------------------------------------------------
def test_admin_provisions_church_as_pending(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker="pa1")
    client = _wire(app, db=db, clerk=FakeClerk(), mailer=FakeMailer())
    resp = client.post(
        "/admin/igrejas",
        headers=_AUTH,
        json={"nome": "Nova", "admin": {"nome": "P", "email": "p@nova.org"}},
    )
    assert resp.status_code == 201
    # A igreja nasce 'aguardando_aprovacao' (acesso bloqueado até aprovar).
    igreja = next(o for o in db.added if isinstance(o, Igreja))
    assert igreja.status == "aguardando_aprovacao"


_IG_ID = "00000000-0000-0000-0000-000000000009"


def test_admin_aprova_igreja_pendente(app) -> None:
    igreja = SimpleNamespace(
        id=_IG_ID, nome="Igreja Y", status="aguardando_aprovacao", plano=None, created_at=None
    )
    db = PlatformDB(
        gate_app_user=make_app_user(), admin_marker="pa1", igreja_scalar=igreja
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.post(f"/admin/igrejas/{_IG_ID}/aprovar", headers=_AUTH)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ativa"
    assert igreja.status == "ativa"
    assert db.committed is True
    # Cascata: semeou a matriz role_permissions (defaults).
    assert any(isinstance(o, RolePermission) for o in db.added)
    # M3: a aprovação foi registrada na auditoria.
    assert any(
        isinstance(o, PlatformAuditLog) and o.acao == "aprovar" for o in db.added
    )


def test_admin_aprovar_idempotente_quando_ja_ativa(app) -> None:
    igreja = SimpleNamespace(
        id=_IG_ID, nome="Igreja Z", status="ativa", plano=None, created_at=None
    )
    db = PlatformDB(
        gate_app_user=make_app_user(), admin_marker="pa1", igreja_scalar=igreja
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.post(f"/admin/igrejas/{_IG_ID}/aprovar", headers=_AUTH)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ativa"
    # No-op: não semeia de novo nem altera.
    assert all(not isinstance(o, RolePermission) for o in db.added)


def test_admin_aprovar_rejeita_suspensa(app) -> None:
    igreja = SimpleNamespace(
        id=_IG_ID, nome="Igreja W", status="suspensa", plano=None, created_at=None
    )
    db = PlatformDB(
        gate_app_user=make_app_user(), admin_marker="pa1", igreja_scalar=igreja
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.post(f"/admin/igrejas/{_IG_ID}/aprovar", headers=_AUTH)
    assert resp.status_code == 409


def test_admin_aprovar_404(app) -> None:
    db = PlatformDB(
        gate_app_user=make_app_user(), admin_marker="pa1", igreja_scalar=None
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.post(f"/admin/igrejas/{_IG_ID}/aprovar", headers=_AUTH)
    assert resp.status_code == 404


def test_admin_aprovar_blocks_non_master(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker=None)
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.post(f"/admin/igrejas/{_IG_ID}/aprovar", headers=_AUTH)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Gestão de planos — "o master pode definir os planos" (migration 0012)
# ---------------------------------------------------------------------------
def _plano_ns(**over):
    base = dict(
        id="p1",
        codigo="ate_100",
        nome="Até 100 pessoas",
        limite_pessoas=100,
        preco_mensal=199,
        ativo=True,
        ordem=1,
    )
    base.update(over)
    return SimpleNamespace(**base)


_PLANO_ID = "00000000-0000-0000-0000-000000000005"


def test_admin_lists_planos(app) -> None:
    db = PlatformDB(
        gate_app_user=make_app_user(),
        admin_marker="pa1",
        planos=[_plano_ns(), _plano_ns(id="p3", codigo="acima_201", preco_mensal=399)],
        em_uso_rows=[("ate_100", 2)],
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.get("/admin/planos", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert [p["codigo"] for p in body] == ["ate_100", "acima_201"]
    ate = next(p for p in body if p["codigo"] == "ate_100")
    assert ate["precoMensal"] == 199 and ate["emUso"] == 2
    assert next(p for p in body if p["codigo"] == "acima_201")["emUso"] == 0


def test_admin_planos_block_non_master(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker=None)
    client = _wire(app, db=db, clerk=FakeClerk())
    assert client.get("/admin/planos", headers=_AUTH).status_code == 403


def test_admin_creates_plano(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker="pa1")
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.post(
        "/admin/planos",
        headers=_AUTH,
        json={"codigo": "premium", "nome": "Premium", "precoMensal": 499},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["codigo"] == "premium" and body["precoMensal"] == 499
    assert body["ativo"] is True
    assert db.committed is True


def test_admin_create_plano_rejects_bad_codigo(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker="pa1")
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.post(
        "/admin/planos",
        headers=_AUTH,
        json={"codigo": "Plano Premium", "nome": "X", "precoMensal": 10},
    )
    assert resp.status_code == 422


def test_admin_create_plano_conflict(app) -> None:
    # codigo já existe (dup-check encontra uma linha) -> 409.
    db = PlatformDB(
        gate_app_user=make_app_user(), admin_marker="pa1", plano_scalar="existing"
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.post(
        "/admin/planos",
        headers=_AUTH,
        json={"codigo": "ate_100", "nome": "Dup", "precoMensal": 199},
    )
    assert resp.status_code == 409


def test_admin_updates_plano_price(app) -> None:
    plano = _plano_ns()
    db = PlatformDB(
        gate_app_user=make_app_user(), admin_marker="pa1", plano_scalar=plano
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.patch(
        f"/admin/planos/{_PLANO_ID}", headers=_AUTH, json={"precoMensal": 249}
    )
    assert resp.status_code == 200
    assert resp.json()["precoMensal"] == 249
    assert plano.preco_mensal == 249
    assert db.committed is True


def test_admin_update_plano_404(app) -> None:
    db = PlatformDB(
        gate_app_user=make_app_user(), admin_marker="pa1", plano_scalar=None
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.patch(
        f"/admin/planos/{_PLANO_ID}", headers=_AUTH, json={"precoMensal": 1}
    )
    assert resp.status_code == 404


def test_admin_deletes_plano_when_free(app) -> None:
    plano = _plano_ns(codigo="premium")
    db = PlatformDB(
        gate_app_user=make_app_user(),
        admin_marker="pa1",
        plano_scalar=plano,
        count_value=0,  # nenhuma igreja no plano
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.delete(f"/admin/planos/{_PLANO_ID}", headers=_AUTH)
    assert resp.status_code == 204
    assert db.deleted == [plano]
    assert db.committed is True


def test_admin_delete_plano_blocked_when_in_use(app) -> None:
    plano = _plano_ns()
    db = PlatformDB(
        gate_app_user=make_app_user(),
        admin_marker="pa1",
        plano_scalar=plano,
        count_value=3,  # 3 igrejas usam o plano
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.delete(f"/admin/planos/{_PLANO_ID}", headers=_AUTH)
    assert resp.status_code == 409
    assert db.deleted == []


# ---------------------------------------------------------------------------
# M3 — auditoria das ações do console (migration 0013)
# ---------------------------------------------------------------------------
def test_admin_lists_audit(app) -> None:
    entry = SimpleNamespace(
        id="aud-1",
        actor_email="master@x.com",
        acao="aprovar",
        alvo_tipo="igreja",
        alvo_id=None,
        alvo_nome="Igreja X",
        detalhe={"plano": "ate_100"},
        created_at=None,
    )
    db = PlatformDB(
        gate_app_user=make_app_user(), admin_marker="pa1", audit_rows=[entry]
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.get("/admin/audit", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["acao"] == "aprovar"
    assert body[0]["alvoNome"] == "Igreja X"
    assert body[0]["actorEmail"] == "master@x.com"


def test_admin_audit_blocks_non_master(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker=None)
    client = _wire(app, db=db, clerk=FakeClerk())
    assert client.get("/admin/audit", headers=_AUTH).status_code == 403


def test_admin_delete_igreja_writes_audit(app) -> None:
    igreja = SimpleNamespace(
        id="ig-1", nome="Igreja X", status="ativa", plano=None, created_at=None
    )
    db = PlatformDB(
        gate_app_user=make_app_user(), admin_marker="pa1", igreja_scalar=igreja
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.delete(f"/admin/igrejas/{_IG_ID}", headers=_AUTH)
    assert resp.status_code == 204
    assert any(
        isinstance(o, PlatformAuditLog) and o.acao == "excluir" for o in db.added
    )


# ---------------------------------------------------------------------------
# Agente de IA da igreja — configurado pelo master (cross-tenant)
# ---------------------------------------------------------------------------
def _igreja_ns(**over):
    base = dict(id="ig-1", nome="Igreja X", status="ativa", plano=None, created_at=None)
    base.update(over)
    return SimpleNamespace(**base)


def test_admin_get_igreja_agente(app) -> None:
    cfg = SimpleNamespace(
        nome="Pastora Ana", tom="acolhedor", comportamento="Seja gentil.", ativo=True
    )
    cred = SimpleNamespace(validado=True, ativo=True)
    db = PlatformDB(
        gate_app_user=make_app_user(),
        admin_marker="pa1",
        igreja_scalar=_igreja_ns(),
        agent_config=cfg,
        llm_credential=cred,
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.get(f"/admin/igrejas/{_IG_ID}/agente", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["comportamento"] == "Seja gentil."
    assert body["credencialStatus"] == "active"


def test_admin_put_igreja_agente(app) -> None:
    cred = SimpleNamespace(validado=True, ativo=True)
    db = PlatformDB(
        gate_app_user=make_app_user(),
        admin_marker="pa1",
        igreja_scalar=_igreja_ns(),
        agent_config=None,  # ainda não configurado → cria
        llm_credential=cred,
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.put(
        f"/admin/igrejas/{_IG_ID}/agente",
        headers=_AUTH,
        json={"comportamento": "Seja pastoral.", "nome": "Ana", "ativo": True},
    )
    assert resp.status_code == 200
    assert resp.json()["ativo"] is True
    assert db.committed is True
    assert any(isinstance(o, AgentConfig) for o in db.added)
    assert any(
        isinstance(o, PlatformAuditLog) and o.acao == "agente_editar"
        for o in db.added
    )


def test_admin_put_agente_blocks_activation_without_credential(app) -> None:
    db = PlatformDB(
        gate_app_user=make_app_user(),
        admin_marker="pa1",
        igreja_scalar=_igreja_ns(),
        llm_credential=None,  # sem credencial ativa → não pode ligar
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.put(
        f"/admin/igrejas/{_IG_ID}/agente",
        headers=_AUTH,
        json={"comportamento": "X", "ativo": True},
    )
    assert resp.status_code == 409


def test_admin_agente_404(app) -> None:
    db = PlatformDB(
        gate_app_user=make_app_user(), admin_marker="pa1", igreja_scalar=None
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    assert (
        client.get(f"/admin/igrejas/{_IG_ID}/agente", headers=_AUTH).status_code == 404
    )


def test_admin_agente_blocks_non_master(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker=None)
    client = _wire(app, db=db, clerk=FakeClerk())
    assert (
        client.get(f"/admin/igrejas/{_IG_ID}/agente", headers=_AUTH).status_code == 403
    )


# ---------------------------------------------------------------------------
# Fatia 2 — editar dados da igreja (nome) + ver o admin owner
# ---------------------------------------------------------------------------
def test_admin_patch_updates_nome(app) -> None:
    igreja = _igreja_ns(nome="Nome Velho")
    db = PlatformDB(
        gate_app_user=make_app_user(), admin_marker="pa1", igreja_scalar=igreja
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.patch(
        f"/admin/igrejas/{_IG_ID}", headers=_AUTH, json={"nome": "Igreja Nova"}
    )
    assert resp.status_code == 200
    assert resp.json()["nome"] == "Igreja Nova"
    assert igreja.nome == "Igreja Nova"
    assert db.committed is True


def test_admin_lists_igreja_admins(app) -> None:
    owner = SimpleNamespace(id="u1", nome="Pastor", email="p@x.com", status="ativo")
    db = PlatformDB(
        gate_app_user=make_app_user(),
        admin_marker="pa1",
        igreja_scalar=_igreja_ns(),
        igreja_admins=[owner],
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.get(f"/admin/igrejas/{_IG_ID}/admins", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["email"] == "p@x.com"
    assert body[0]["nome"] == "Pastor"
    assert body[0]["status"] == "ativo"


def test_admin_lists_igreja_admins_blocks_non_master(app) -> None:
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker=None)
    client = _wire(app, db=db, clerk=FakeClerk())
    assert (
        client.get(f"/admin/igrejas/{_IG_ID}/admins", headers=_AUTH).status_code == 403
    )


# ---------------------------------------------------------------------------
# CRUD de admins (owner) — convidar / reenviar / remover
# ---------------------------------------------------------------------------
def test_admin_adds_igreja_admin(app) -> None:
    db = PlatformDB(
        gate_app_user=make_app_user(),
        admin_marker="pa1",
        igreja_scalar=_igreja_ns(),
        igreja_admins=[],  # ninguém com esse e-mail ainda
    )
    mailer = FakeMailer()
    client = _wire(app, db=db, clerk=FakeClerk(), mailer=mailer)
    resp = client.post(
        f"/admin/igrejas/{_IG_ID}/admins",
        headers=_AUTH,
        json={"nome": "Novo Admin", "email": "Novo@Igreja.org"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "novo@igreja.org"  # normalizado
    assert body["emailEnviado"] is True
    assert mailer.sent == ["novo@igreja.org"]
    assert any(isinstance(o, AppUser) for o in db.added)
    assert any(isinstance(o, UserRole) and o.papel == "admin" for o in db.added)
    assert any(
        isinstance(o, PlatformAuditLog) and o.acao == "admin_add" for o in db.added
    )


def test_admin_add_admin_conflict(app) -> None:
    existing = SimpleNamespace(id="u1", nome="P", email="dup@x.com", status="ativo")
    db = PlatformDB(
        gate_app_user=make_app_user(),
        admin_marker="pa1",
        igreja_scalar=_igreja_ns(),
        igreja_admins=[existing],
    )
    client = _wire(app, db=db, clerk=FakeClerk(), mailer=FakeMailer())
    resp = client.post(
        f"/admin/igrejas/{_IG_ID}/admins",
        headers=_AUTH,
        json={"nome": "X", "email": "dup@x.com"},
    )
    assert resp.status_code == 409


def test_admin_resends_admin_invite(app) -> None:
    u = make_app_user()
    u.status = "convidado"
    db = PlatformDB(gate_app_user=u, admin_marker="pa1", igreja_scalar=_igreja_ns())
    mailer = FakeMailer()
    client = _wire(app, db=db, clerk=FakeClerk(), mailer=mailer)
    resp = client.post(f"/admin/igrejas/{_IG_ID}/admins/{u.id}/reenviar", headers=_AUTH)
    assert resp.status_code == 200
    assert resp.json()["emailEnviado"] is True
    assert mailer.sent == [u.email]
    assert any(
        isinstance(o, PlatformAuditLog) and o.acao == "admin_reenviar" for o in db.added
    )


def test_admin_resend_blocks_active(app) -> None:
    u = make_app_user()
    u.status = "ativo"
    db = PlatformDB(gate_app_user=u, admin_marker="pa1", igreja_scalar=_igreja_ns())
    client = _wire(app, db=db, clerk=FakeClerk(), mailer=FakeMailer())
    resp = client.post(f"/admin/igrejas/{_IG_ID}/admins/{u.id}/reenviar", headers=_AUTH)
    assert resp.status_code == 409


def test_admin_removes_igreja_admin(app) -> None:
    u = make_app_user()
    role = SimpleNamespace(id="r1", papel="admin")
    db = PlatformDB(
        gate_app_user=u,
        admin_marker="pa1",
        igreja_scalar=_igreja_ns(),
        count_value=2,  # não é o último admin
        user_role=role,
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.delete(f"/admin/igrejas/{_IG_ID}/admins/{u.id}", headers=_AUTH)
    assert resp.status_code == 204
    assert role in db.deleted
    assert any(
        isinstance(o, PlatformAuditLog) and o.acao == "admin_remover" for o in db.added
    )


def test_admin_remove_blocks_last_admin(app) -> None:
    u = make_app_user()
    db = PlatformDB(
        gate_app_user=u, admin_marker="pa1", igreja_scalar=_igreja_ns(), count_value=1
    )
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.delete(f"/admin/igrejas/{_IG_ID}/admins/{u.id}", headers=_AUTH)
    assert resp.status_code == 409
