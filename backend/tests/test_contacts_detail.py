"""Tests for GET /contacts/{id} — rich contact detail for the chat panel (Parte B).

Reads are open to any authenticated tenant user (like GET /contacts); the detail
resolves célula/líder names for display. RLS handles tenant isolation; here we
exercise auth gating, the 404 path and the response shape.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Celula, Pessoa
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_PID = "00000000-0000-0000-0000-0000000000b2"
_AUTH = {"Authorization": "Bearer good"}


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


class DetailSession:
    """Routes auth (AppUser/UserRole) + the Pessoa/Celula lookups."""

    def __init__(
        self, *, app_user, roles, pessoa, celula_nome=None, led_cell_id=None
    ) -> None:
        self.app_user = app_user
        self.roles = roles
        self.pessoa = pessoa
        self.celula_nome = celula_nome
        self.led_cell_id = led_cell_id  # célula ativa liderada (liderDeCelula)

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        d0 = descs[0] if descs else {}
        ent = d0.get("entity")
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is Celula:
            # select(Celula.nome) (rótulo) vs select(Celula.id) (liderDeCelula).
            if d0.get("name") == "id":
                return _R(scalar=self.led_cell_id)
            return _R(scalar=self.celula_nome)
        if ent is Pessoa:
            return _R(scalar=self.pessoa)
        return _R(scalars=self.roles)

    def close(self) -> None:  # pragma: no cover
        pass


def make_pessoa(*, celula_id=None):
    return SimpleNamespace(
        id=_PID,
        nome="Maria Santos",
        telefone="+5589999990000",
        email="maria@x.com",
        genero="f",
        faixa_etaria="adulto",
        endereco="Rua A, 123",
        tipo="visitante",
        etapa="ganhar",
        subetapa="visitante",
        acompanhamento=None,
        sem_interesse=False,
        sem_interesse_motivo=None,
        presencas_celula=2,
        aceitou_jesus=False,
        celula_id=celula_id,
        lider_id=None,
        apto_lider=False,
        arquivada_em=None,
        consentimento=True,
        optout=False,
        origem="whatsapp",
        primeiro_contato=None,
        created_at=None,
    )


def _wire(app, *, session, clerk=None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk or FakeClerk()
    return TestClient(app)


def test_detail_requires_auth(app) -> None:
    session = DetailSession(
        app_user=make_app_user(), roles=["admin"], pessoa=make_pessoa()
    )
    client = _wire(app, session=session)
    assert client.get(f"/contacts/{_PID}").status_code == 401


def test_detail_not_found(app) -> None:
    session = DetailSession(app_user=make_app_user(), roles=["pastor"], pessoa=None)
    client = _wire(app, session=session)
    assert client.get(f"/contacts/{_PID}", headers=_AUTH).status_code == 404


def test_detail_returns_full_shape(app) -> None:
    pessoa = make_pessoa(celula_id="00000000-0000-0000-0000-0000000000c3")
    session = DetailSession(
        app_user=make_app_user(),
        roles=["lider_g12"],
        pessoa=pessoa,
        celula_nome="Célula Alfa",
    )
    client = _wire(app, session=session)
    resp = client.get(f"/contacts/{_PID}", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == _PID
    assert body["nome"] == "Maria Santos"
    assert body["endereco"] == "Rua A, 123"
    assert body["faixaEtaria"] == "adulto"
    assert body["etapa"] == "ganhar"
    assert body["celulaNome"] == "Célula Alfa"
    assert body["consentimento"] is True
    assert body["origem"] == "whatsapp"
    assert body["aptoLider"] is False
    assert body["liderDeCelula"] is False
    assert body["arquivada"] is False


def test_detail_exposes_archived_state(app) -> None:
    pessoa = make_pessoa()
    pessoa.arquivada_em = object()
    session = DetailSession(
        app_user=make_app_user(), roles=["admin"], pessoa=pessoa
    )
    client = _wire(app, session=session)

    resp = client.get(f"/contacts/{_PID}", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["arquivada"] is True


def test_detail_derives_lider_de_celula(app) -> None:
    # liderDeCelula = vínculo real (celulas.lider_id em célula ativa), não tipo.
    pessoa = make_pessoa()
    pessoa.apto_lider = True
    session = DetailSession(
        app_user=make_app_user(),
        roles=["pastor"],
        pessoa=pessoa,
        led_cell_id="00000000-0000-0000-0000-0000000000c9",
    )
    client = _wire(app, session=session)
    resp = client.get(f"/contacts/{_PID}", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["aptoLider"] is True
    assert body["liderDeCelula"] is True


def test_detail_invalid_uuid_is_404(app) -> None:
    session = DetailSession(app_user=make_app_user(), roles=["admin"], pessoa=None)
    client = _wire(app, session=session)
    assert client.get("/contacts/not-a-uuid", headers=_AUTH).status_code == 404
