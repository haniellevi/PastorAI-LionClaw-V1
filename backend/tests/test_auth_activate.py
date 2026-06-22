"""Tests for the invite activation flow (POST /auth/activate + GET /auth/invite).

The invited app_user starts without a Clerk account (clerk_user_id NULL).
Activation verifies the signed invite token, creates the Clerk user with the
chosen password and links it, flipping the account to 'ativo'. Validated offline.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Pessoa
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk

_AID = "00000000-0000-0000-0000-0000000000a1"
_PESSOA_ID = "00000000-0000-0000-0000-0000000000b1"
_PID = "00000000-0000-0000-0000-0000000000b9"
_CELULA_ID = "00000000-0000-0000-0000-0000000000c1"


class _Scalars:
    def __init__(self, items) -> None:
        self._items = items

    def all(self) -> list:
        return list(self._items)


class _Result:
    def __init__(self, scalar=None, items=None) -> None:
        self._scalar = scalar
        self._items = items or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self) -> _Scalars:
        return _Scalars(self._items)


class InviteSession:
    """Minimal session: returns the invited app_user, records commit, and
    supports the Parte B path (Pessoa dedup lookup + insert)."""

    def __init__(self, app_user=None, pessoas=None) -> None:
        self.app_user = app_user
        self.pessoas = pessoas or []  # dedup candidates for Parte B
        self.added: list = []
        self.committed = False

    def execute(self, statement, params=None) -> _Result:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _Result(scalar=self.app_user)
        if ent is Pessoa:
            return _Result(items=self.pessoas)
        return _Result()

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = _PID

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


def make_invited(
    *,
    clerk_user_id=None,
    email: str = "novo@igreja.org",
    nome: str = "Pastor Novo",
    igreja: str = "Igreja Nova",
    pessoa_id=_PESSOA_ID,
    celula_pendente_id=None,
):
    return SimpleNamespace(
        id=_AID,
        clerk_user_id=clerk_user_id,
        email=email,
        nome=nome,
        status="convidado",
        pessoa_id=pessoa_id,
        celula_pendente_id=celula_pendente_id,
        igreja_id="00000000-0000-0000-0000-000000000001",
        igreja=SimpleNamespace(nome=igreja),
    )


def _wire(app, *, session, clerk) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    return TestClient(app)


# ---- GET /auth/invite/{token} ---------------------------------------------
def test_invite_info_returns_data(app) -> None:
    client = _wire(app, session=InviteSession(make_invited()), clerk=FakeClerk(invite_app_user_id=_AID))
    resp = client.get("/auth/invite/sometoken")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "novo@igreja.org"
    assert body["nome"] == "Pastor Novo"
    assert body["igreja"] == "Igreja Nova"


def test_invite_info_invalid_token(app) -> None:
    client = _wire(app, session=InviteSession(make_invited()), clerk=FakeClerk(raise_invite=True))
    assert client.get("/auth/invite/bad").status_code == 400


def test_invite_info_already_activated(app) -> None:
    client = _wire(
        app,
        session=InviteSession(make_invited(clerk_user_id="clerk_existing")),
        clerk=FakeClerk(invite_app_user_id=_AID),
    )
    assert client.get("/auth/invite/tok").status_code == 409


# ---- POST /auth/activate ---------------------------------------------------
def test_activate_creates_access(app) -> None:
    invited = make_invited()
    session = InviteSession(invited)
    client = _wire(
        app,
        session=session,
        clerk=FakeClerk(invite_app_user_id=_AID, created_clerk_id="clerk_brand_new"),
    )
    resp = client.post("/auth/activate", json={"token": "tok", "password": "umaSenha123"})
    assert resp.status_code == 200
    assert invited.clerk_user_id == "clerk_brand_new"
    assert invited.status == "ativo"
    assert session.committed is True


def test_activate_invalid_token(app) -> None:
    client = _wire(app, session=InviteSession(make_invited()), clerk=FakeClerk(raise_invite=True))
    resp = client.post("/auth/activate", json={"token": "bad", "password": "umaSenha123"})
    assert resp.status_code == 400


def test_activate_already_activated(app) -> None:
    client = _wire(
        app,
        session=InviteSession(make_invited(clerk_user_id="clerk_x")),
        clerk=FakeClerk(invite_app_user_id=_AID),
    )
    resp = client.post("/auth/activate", json={"token": "tok", "password": "umaSenha123"})
    assert resp.status_code == 409


def test_activate_rejects_short_password(app) -> None:
    client = _wire(app, session=InviteSession(make_invited()), clerk=FakeClerk(invite_app_user_id=_AID))
    resp = client.post("/auth/activate", json={"token": "tok", "password": "curta"})
    assert resp.status_code == 422


def test_activate_clerk_failure_is_502(app) -> None:
    client = _wire(
        app,
        session=InviteSession(make_invited()),
        clerk=FakeClerk(invite_app_user_id=_AID, raise_create=True),
    )
    resp = client.post("/auth/activate", json={"token": "tok", "password": "umaSenha123"})
    assert resp.status_code == 502


# ---- Parte B (pessoa nova completa o cadastro na ativação) ----------------
def test_invite_info_flags_parte_b(app) -> None:
    # Sem pessoa vinculada => o convite pede o cadastro (telefone) na ativação.
    parte_b = InviteSession(make_invited(pessoa_id=None, celula_pendente_id=_CELULA_ID))
    parte_a = InviteSession(make_invited())
    assert (
        _wire(app, session=parte_b, clerk=FakeClerk(invite_app_user_id=_AID))
        .get("/auth/invite/tok")
        .json()["precisaCadastro"]
        is True
    )
    assert (
        _wire(app, session=parte_a, clerk=FakeClerk(invite_app_user_id=_AID))
        .get("/auth/invite/tok")
        .json()["precisaCadastro"]
        is False
    )


def test_activate_parte_b_requires_phone(app) -> None:
    invited = make_invited(pessoa_id=None, celula_pendente_id=_CELULA_ID)
    client = _wire(app, session=InviteSession(invited), clerk=FakeClerk(invite_app_user_id=_AID))
    resp = client.post("/auth/activate", json={"token": "tok", "password": "umaSenha123"})
    assert resp.status_code == 400
    assert invited.clerk_user_id is None  # não cria conta órfã


def test_activate_parte_b_creates_member(app) -> None:
    invited = make_invited(pessoa_id=None, celula_pendente_id=_CELULA_ID)
    session = InviteSession(invited)  # sem candidatos de dedup -> cria nova
    client = _wire(
        app,
        session=session,
        clerk=FakeClerk(invite_app_user_id=_AID, created_clerk_id="clerk_b"),
    )
    resp = client.post(
        "/auth/activate",
        json={"token": "tok", "password": "umaSenha123", "telefone": "(11) 98888-7777"},
    )
    assert resp.status_code == 200
    assert invited.clerk_user_id == "clerk_b"
    assert invited.status == "ativo"
    # Uma Pessoa-membro foi criada e vinculada na célula pendente.
    assert len(session.added) == 1
    nova = session.added[0]
    assert nova.tipo == "membro"
    assert str(nova.celula_id) == _CELULA_ID
    assert invited.pessoa_id == nova.id
    assert invited.celula_pendente_id is None
