"""Testes de ``cell_materials`` — publicação Central-only, leitura E14, inativação.

Fake-session em memória (``CellSession``). Só a Central (pastor/admin) publica e
inativa (E1/E2); qualquer papel autenticado lê os materiais ATIVOS da própria
igreja (E14). Sem upload real — guarda-se apenas link + metadados.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.cell_backend_fakes import (
    MEMBER_PESSOA,
    CellSession,
    make_app_user,
    make_material,
)
from tests.conftest import FakeClerk

_AUTH = {"Authorization": "Bearer good"}


def _wire(app, *, session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def _central_session(**kwargs) -> CellSession:
    kwargs.setdefault("app_user", make_app_user())
    kwargs.setdefault("roles", ["pastor"])
    kwargs.setdefault("actor_pessoa_id", "00000000-0000-0000-0000-0000000000b0")
    return CellSession(**kwargs)


def _member_session(**kwargs) -> CellSession:
    kwargs.setdefault("app_user", make_app_user())
    kwargs.setdefault("roles", ["membro"])
    kwargs.setdefault("actor_pessoa_id", MEMBER_PESSOA)
    return CellSession(**kwargs)


# ===========================================================================
# POST /cell-materials
# ===========================================================================
def test_central_publishes_material(app) -> None:
    session = _central_session()
    resp = _wire(app, session=session).post(
        "/cell-materials",
        headers=_AUTH,
        json={
            "titulo": "Estudo 1",
            "url": "https://example.com/estudo.pdf",
            "descricao": "Material da semana",
            "tipo": "pdf",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["titulo"] == "Estudo 1"
    assert body["url"] == "https://example.com/estudo.pdf"
    assert body["ativo"] is True
    assert body["publicado_em"] is not None
    assert session.committed is True


@pytest.mark.parametrize(
    "url",
    [
        "",  # vazia
        "ftp://example.com/a.pdf",  # esquema não permitido
        "example.com/a.pdf",  # sem esquema
        "http://" + "x" * 2048,  # > 2048
    ],
)
def test_invalid_url_is_422(app, url) -> None:
    session = _central_session()
    resp = _wire(app, session=session).post(
        "/cell-materials", headers=_AUTH, json={"titulo": "T", "url": url}
    )
    assert resp.status_code == 422


def test_non_central_cannot_publish(app) -> None:
    session = _member_session()
    resp = _wire(app, session=session).post(
        "/cell-materials",
        headers=_AUTH,
        json={"titulo": "T", "url": "https://example.com/a.pdf"},
    )
    assert resp.status_code == 403


def test_publish_requires_auth(app) -> None:
    session = _central_session()
    resp = _wire(app, session=session).post(
        "/cell-materials", json={"titulo": "T", "url": "https://example.com/a.pdf"}
    )
    assert resp.status_code == 401


# ===========================================================================
# GET /cell-materials (E14 — qualquer papel lê)
# ===========================================================================
def test_member_lists_active_materials(app) -> None:
    ativo = make_material(material_id="m-on", titulo="On", ativo=True)
    inativo = make_material(material_id="m-off", titulo="Off", ativo=False)
    session = _member_session(materiais=[ativo, inativo])
    resp = _wire(app, session=session).get("/cell-materials", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [m["id"] for m in body["items"]] == ["m-on"]
    assert body["total"] == 1


def test_list_paginates(app) -> None:
    materiais = [make_material(material_id=f"m{i}") for i in range(3)]
    session = _member_session(materiais=materiais)
    resp = _wire(app, session=session).get(
        "/cell-materials", params={"page": 1, "page_size": 2}, headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["page_size"] == 2


def test_list_requires_auth(app) -> None:
    session = _member_session()
    resp = _wire(app, session=session).get("/cell-materials")
    assert resp.status_code == 401


# ===========================================================================
# DELETE /cell-materials/{id}
# ===========================================================================
def test_central_inactivates_material(app) -> None:
    material = make_material(
        material_id="00000000-0000-0000-0000-0000000000a1", ativo=True
    )
    session = _central_session(materiais=[material])
    resp = _wire(app, session=session).delete(
        f"/cell-materials/{material.id}", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ativo"] is False
    assert material.ativo is False


def test_non_central_cannot_inactivate(app) -> None:
    material = make_material(
        material_id="00000000-0000-0000-0000-0000000000a2", ativo=True
    )
    session = _member_session(materiais=[material])
    resp = _wire(app, session=session).delete(
        f"/cell-materials/{material.id}", headers=_AUTH
    )
    assert resp.status_code == 403
    assert material.ativo is True


def test_delete_unknown_is_404(app) -> None:
    session = _central_session(materiais=[])
    resp = _wire(app, session=session).delete(
        "/cell-materials/00000000-0000-0000-0000-0000000000af", headers=_AUTH
    )
    assert resp.status_code == 404


def test_delete_malformed_id_is_404(app) -> None:
    session = _central_session(materiais=[])
    resp = _wire(app, session=session).delete("/cell-materials/nope", headers=_AUTH)
    assert resp.status_code == 404
