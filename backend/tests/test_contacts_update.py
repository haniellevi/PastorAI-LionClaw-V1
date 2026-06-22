"""Tests for PATCH /contacts/{id} — admin-only contact edit (RF-05)."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Pessoa
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_PID = "00000000-0000-0000-0000-0000000000b2"


class _R:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class ContactSession:
    """Routes auth (AppUser/UserRole) + the contact lookup (Pessoa)."""

    def __init__(self, *, app_user, roles, pessoa, candidates=None) -> None:
        self.app_user = app_user
        self.roles = roles
        self.pessoa = pessoa
        self.candidates = candidates or []
        self.committed = False

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is Pessoa:
            return _R(scalar=self.pessoa, scalars=self.candidates)
        return _R(scalars=self.roles)

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


def make_pessoa(*, nome="Antigo", telefone="+5589999990000", email="a@x.com"):
    return SimpleNamespace(
        id=_PID,
        nome=nome,
        telefone=telefone,
        email=email,
        genero=None,
        tipo="membro",
        etapa=None,
        subetapa=None,
        acompanhamento=None,
        faixa_etaria=None,
        endereco=None,
        presencas_celula=0,
        aceitou_jesus=False,
        celula_id=None,
        lider_id=None,
    )


def _wire(app, *, session, clerk) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    return TestClient(app)


_AUTH = {"Authorization": "Bearer good"}


def test_update_requires_admin(app) -> None:
    session = ContactSession(
        app_user=make_app_user(), roles=["lider_celula"], pessoa=make_pessoa()
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.patch(f"/contacts/{_PID}", headers=_AUTH, json={"nome": "Novo"})
    assert resp.status_code == 403


def test_update_not_found(app) -> None:
    session = ContactSession(app_user=make_app_user(), roles=["admin"], pessoa=None)
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.patch(f"/contacts/{_PID}", headers=_AUTH, json={"nome": "Novo"})
    assert resp.status_code == 404


def test_update_changes_name_and_email(app) -> None:
    pessoa = make_pessoa(nome="Antigo", email="a@x.com")
    session = ContactSession(app_user=make_app_user(), roles=["admin"], pessoa=pessoa)
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.patch(
        f"/contacts/{_PID}",
        headers=_AUTH,
        json={"nome": "Novo Nome", "email": "novo@x.com"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["nome"] == "Novo Nome"
    assert body["email"] == "novo@x.com"
    assert pessoa.nome == "Novo Nome"
    assert session.committed is True


def test_update_rejects_invalid_tipo(app) -> None:
    session = ContactSession(
        app_user=make_app_user(), roles=["admin"], pessoa=make_pessoa()
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.patch(f"/contacts/{_PID}", headers=_AUTH, json={"tipo": "rei"})
    assert resp.status_code == 422
