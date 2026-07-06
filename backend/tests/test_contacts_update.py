"""Tests for PATCH /contacts/{id} — admin-only contact edit (RF-05)."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Celula, Pessoa
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
    """Routes auth (AppUser/UserRole) + Pessoa lookup + Celula (liderDeCelula)."""

    def __init__(
        self, *, app_user, roles, pessoa, candidates=None, led_cell_id=None
    ) -> None:
        self.app_user = app_user
        self.roles = roles
        self.pessoa = pessoa
        self.candidates = candidates or []
        self.led_cell_id = led_cell_id  # célula ativa liderada (derivação)
        self.committed = False

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is Celula:
            return _R(scalar=self.led_cell_id)
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
        sem_interesse=False,
        sem_interesse_motivo=None,
        faixa_etaria=None,
        endereco=None,
        presencas_celula=0,
        aceitou_jesus=False,
        celula_id=None,
        lider_id=None,
        apto_lider=False,
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


def test_update_marks_csim_with_motivo(app) -> None:
    pessoa = make_pessoa()
    session = ContactSession(app_user=make_app_user(), roles=["admin"], pessoa=pessoa)
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.patch(
        f"/contacts/{_PID}",
        headers=_AUTH,
        json={"semInteresse": True, "semInteresseMotivo": "empresa"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["semInteresse"] is True
    assert body["semInteresseMotivo"] == "empresa"
    assert pessoa.sem_interesse is True
    assert pessoa.sem_interesse_motivo == "empresa"


def test_update_unmarks_csim_clears_motivo(app) -> None:
    pessoa = make_pessoa()
    pessoa.sem_interesse = True
    pessoa.sem_interesse_motivo = "empresa"
    session = ContactSession(app_user=make_app_user(), roles=["admin"], pessoa=pessoa)
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.patch(f"/contacts/{_PID}", headers=_AUTH, json={"semInteresse": False})
    assert resp.status_code == 200
    assert pessoa.sem_interesse is False
    assert pessoa.sem_interesse_motivo is None


def test_update_accepts_contato(app) -> None:
    pessoa = make_pessoa()
    session = ContactSession(app_user=make_app_user(), roles=["admin"], pessoa=pessoa)
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.patch(f"/contacts/{_PID}", headers=_AUTH, json={"tipo": "contato"})
    assert resp.status_code == 200
    assert resp.json()["tipo"] == "contato"
    assert pessoa.tipo == "contato"


def test_update_rejects_invalid_tipo(app) -> None:
    session = ContactSession(
        app_user=make_app_user(), roles=["admin"], pessoa=make_pessoa()
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.patch(f"/contacts/{_PID}", headers=_AUTH, json={"tipo": "rei"})
    assert resp.status_code == 422


def test_update_rejects_tipo_lider(app) -> None:
    # "lider" saiu dos tipos manuais: liderança deriva da célula ativa.
    session = ContactSession(
        app_user=make_app_user(), roles=["admin"], pessoa=make_pessoa()
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.patch(f"/contacts/{_PID}", headers=_AUTH, json={"tipo": "lider"})
    assert resp.status_code == 422


def test_update_sets_apto_lider(app) -> None:
    pessoa = make_pessoa()
    session = ContactSession(app_user=make_app_user(), roles=["admin"], pessoa=pessoa)
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.patch(f"/contacts/{_PID}", headers=_AUTH, json={"aptoLider": True})
    assert resp.status_code == 200
    assert resp.json()["aptoLider"] is True
    assert pessoa.apto_lider is True

    resp = client.patch(f"/contacts/{_PID}", headers=_AUTH, json={"aptoLider": False})
    assert resp.status_code == 200
    assert pessoa.apto_lider is False


def test_update_rejects_apto_lider_on_csim(app) -> None:
    # CSIM está fora da visão: nunca apto a liderar.
    pessoa = make_pessoa()
    pessoa.sem_interesse = True
    session = ContactSession(app_user=make_app_user(), roles=["admin"], pessoa=pessoa)
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.patch(f"/contacts/{_PID}", headers=_AUTH, json={"aptoLider": True})
    assert resp.status_code == 422
    assert pessoa.apto_lider is False


def test_update_blocks_csim_on_active_cell_leader(app) -> None:
    # Quem lidera célula ativa não pode virar CSIM sem antes trocar o líder.
    pessoa = make_pessoa()
    session = ContactSession(
        app_user=make_app_user(),
        roles=["admin"],
        pessoa=pessoa,
        led_cell_id="00000000-0000-0000-0000-0000000000c9",
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.patch(
        f"/contacts/{_PID}", headers=_AUTH, json={"semInteresse": True}
    )
    assert resp.status_code == 409
    assert pessoa.sem_interesse is False


def test_update_marking_csim_clears_apto_lider(app) -> None:
    pessoa = make_pessoa()
    pessoa.apto_lider = True
    session = ContactSession(app_user=make_app_user(), roles=["admin"], pessoa=pessoa)
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.patch(
        f"/contacts/{_PID}", headers=_AUTH, json={"semInteresse": True}
    )
    assert resp.status_code == 200
    assert pessoa.sem_interesse is True
    assert pessoa.apto_lider is False


def test_update_response_derives_lider_de_celula(app) -> None:
    # liderDeCelula vem do vínculo real (celulas.lider_id em célula ativa).
    pessoa = make_pessoa()
    session = ContactSession(
        app_user=make_app_user(),
        roles=["admin"],
        pessoa=pessoa,
        led_cell_id="00000000-0000-0000-0000-0000000000c9",
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.patch(f"/contacts/{_PID}", headers=_AUTH, json={"nome": "Novo"})
    assert resp.status_code == 200
    assert resp.json()["liderDeCelula"] is True
