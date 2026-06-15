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

from app.db.models import AppUser, Igreja, Pessoa, PlatformAdmin
from app.db.session import get_db
from app.services.brevo import BrevoError, get_brevo_client
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user


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
    ) -> None:
        self.gate_app_user = gate_app_user
        self.admin_marker = admin_marker
        self.igrejas = igrejas or []
        self.igreja_scalar = igreja_scalar
        self.membros_rows = membros_rows or []
        self.pessoas_rows = pessoas_rows or []
        self.count_value = count_value
        self.added: list = []
        self.committed = False

    def execute(self, statement, params=None) -> _Result:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        entities = [d.get("entity") for d in descs]
        # Grouped aggregation: (igreja_id, count) — two output columns.
        if len(descs) >= 2:
            if entities[0] is AppUser:
                return _Result(rows=self.membros_rows)
            if entities[0] is Pessoa:
                return _Result(rows=self.pessoas_rows)
            return _Result(rows=[])
        ent = entities[0] if entities else None
        if ent is AppUser:
            return _Result(scalar=self.gate_app_user)
        if ent is PlatformAdmin:
            return _Result(scalar=self.admin_marker)
        if ent is Igreja:
            return _Result(scalar=self.igreja_scalar, scalars=self.igrejas)
        # select(func.count()) — scalar count with no mapped entity.
        return _Result(scalar_one=self.count_value)

    def add(self, obj) -> None:
        self.added.append(obj)

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
