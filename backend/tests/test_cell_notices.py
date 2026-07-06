"""Testes de ``cell_notices`` — publicação, alcance E15 e inativação (PR3-PR9).

Fake-session em memória (``CellSession``); autoria (origem/escopo/célula) é
sempre decidida server-side pelo papel autenticado. O papel do usuário deriva de
``session.roles`` (pastor = Central; caso contrário líder/membro). ``notificado_em``
é carimbado pelo ponto de extensão NO-OP (``cell_notify``), sem envio real.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.cell_backend_fakes import (
    CELL,
    LP,
    LP2,
    MEMBER_PESSOA,
    OTHER_CELL,
    CellSession,
    make_app_user,
    make_aviso,
    make_cell,
    make_member,
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


def _leader_session(**kwargs) -> CellSession:
    kwargs.setdefault("app_user", make_app_user())
    kwargs.setdefault("roles", ["lider"])
    kwargs.setdefault("actor_pessoa_id", LP)
    kwargs.setdefault("cells", [make_cell(lider_id=LP)])
    return CellSession(**kwargs)


def _member_session(**kwargs) -> CellSession:
    kwargs.setdefault("app_user", make_app_user())
    kwargs.setdefault("roles", ["membro"])
    kwargs.setdefault("actor_pessoa_id", MEMBER_PESSOA)
    kwargs.setdefault(
        "membros",
        [make_member(pessoa_id=MEMBER_PESSOA, celula_id=CELL, ativo=True)],
    )
    return CellSession(**kwargs)


# ===========================================================================
# POST /cell-notices — líder
# ===========================================================================
def test_leader_publishes_own_cell_notice(app) -> None:
    session = _leader_session()
    resp = _wire(app, session=session).post(
        "/cell-notices",
        headers=_AUTH,
        json={"titulo": "Reunião", "conteudo": "Hoje às 20h", "celula_id": CELL},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["origem"] == "celula"
    assert body["escopo"] == "celula"
    assert body["celula_id"] == CELL
    assert body["ativo"] is True
    assert body["notificado_em"] is not None  # cell_notify carimbou (no-op)
    assert session.committed is True


def test_leader_cannot_broadcast_igreja(app) -> None:
    session = _leader_session()
    resp = _wire(app, session=session).post(
        "/cell-notices",
        headers=_AUTH,
        json={
            "titulo": "T",
            "conteudo": "C",
            "escopo": "igreja",
            "celula_id": CELL,
        },
    )
    assert resp.status_code == 403


def test_leader_other_cell_is_404(app) -> None:
    # Célula existe, mas é liderada por outra pessoa (LP2) → 404 (não vaza).
    session = _leader_session(cells=[make_cell(lider_id=LP2)])
    resp = _wire(app, session=session).post(
        "/cell-notices",
        headers=_AUTH,
        json={"titulo": "T", "conteudo": "C", "celula_id": CELL},
    )
    assert resp.status_code == 404


def test_leader_without_celula_id_is_422(app) -> None:
    session = _leader_session()
    resp = _wire(app, session=session).post(
        "/cell-notices", headers=_AUTH, json={"titulo": "T", "conteudo": "C"}
    )
    assert resp.status_code == 422


# ===========================================================================
# POST /cell-notices — Central
# ===========================================================================
def test_central_publishes_igreja_broadcast(app) -> None:
    session = _central_session()
    resp = _wire(app, session=session).post(
        "/cell-notices",
        headers=_AUTH,
        json={"titulo": "Aviso geral", "conteudo": "Culto especial", "escopo": "igreja"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["origem"] == "central"
    assert body["escopo"] == "igreja"
    assert body["celula_id"] is None


def test_central_cell_scope_requires_celula_id(app) -> None:
    session = _central_session()
    resp = _wire(app, session=session).post(
        "/cell-notices",
        headers=_AUTH,
        json={"titulo": "T", "conteudo": "C", "escopo": "celula"},
    )
    assert resp.status_code == 422


def test_central_invalid_scope_is_422(app) -> None:
    session = _central_session()
    resp = _wire(app, session=session).post(
        "/cell-notices",
        headers=_AUTH,
        json={"titulo": "T", "conteudo": "C", "escopo": "regional"},
    )
    assert resp.status_code == 422


def test_central_cell_scope_with_valid_cell(app) -> None:
    session = _central_session(cells=[make_cell(cell_id=CELL)])
    resp = _wire(app, session=session).post(
        "/cell-notices",
        headers=_AUTH,
        json={"titulo": "T", "conteudo": "C", "escopo": "celula", "celula_id": CELL},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["origem"] == "central"
    assert body["escopo"] == "celula"
    assert body["celula_id"] == CELL


def test_blank_title_is_422(app) -> None:
    session = _central_session()
    resp = _wire(app, session=session).post(
        "/cell-notices",
        headers=_AUTH,
        json={"titulo": "   ", "conteudo": "C", "escopo": "igreja"},
    )
    assert resp.status_code == 422


def test_publish_requires_auth(app) -> None:
    session = _central_session()
    resp = _wire(app, session=session).post(
        "/cell-notices", json={"titulo": "T", "conteudo": "C", "escopo": "igreja"}
    )
    assert resp.status_code == 401


# ===========================================================================
# GET /cell-notices — alcance E15
# ===========================================================================
def test_member_sees_igreja_and_own_cell_only(app) -> None:
    igreja = make_aviso(aviso_id="n-igreja", escopo="igreja", celula_id=None)
    minha = make_aviso(aviso_id="n-minha", escopo="celula", celula_id=CELL)
    outra = make_aviso(aviso_id="n-outra", escopo="celula", celula_id=OTHER_CELL)
    session = _member_session(avisos=[igreja, minha, outra])
    resp = _wire(app, session=session).get("/cell-notices", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    ids = {n["id"] for n in resp.json()["items"]}
    assert ids == {"n-igreja", "n-minha"}


def test_member_excludes_inactive(app) -> None:
    ativo = make_aviso(aviso_id="n-on", escopo="igreja", ativo=True)
    inativo = make_aviso(aviso_id="n-off", escopo="igreja", ativo=False)
    session = _member_session(avisos=[ativo, inativo])
    resp = _wire(app, session=session).get("/cell-notices", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    assert [n["id"] for n in resp.json()["items"]] == ["n-on"]


def test_central_sees_every_cell_notice(app) -> None:
    igreja = make_aviso(aviso_id="n-igreja", escopo="igreja")
    c1 = make_aviso(aviso_id="n-c1", escopo="celula", celula_id=CELL)
    c2 = make_aviso(aviso_id="n-c2", escopo="celula", celula_id=OTHER_CELL)
    session = _central_session(avisos=[igreja, c1, c2])
    resp = _wire(app, session=session).get("/cell-notices", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    ids = {n["id"] for n in resp.json()["items"]}
    assert ids == {"n-igreja", "n-c1", "n-c2"}


def test_list_paginates(app) -> None:
    avisos = [
        make_aviso(aviso_id=f"n{i}", escopo="igreja") for i in range(3)
    ]
    session = _member_session(avisos=avisos)
    resp = _wire(app, session=session).get(
        "/cell-notices", params={"page": 1, "page_size": 2}, headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["page"] == 1
    assert body["page_size"] == 2


def test_list_requires_auth(app) -> None:
    session = _member_session()
    resp = _wire(app, session=session).get("/cell-notices")
    assert resp.status_code == 401


# ===========================================================================
# DELETE /cell-notices/{id}
# ===========================================================================
def test_central_inactivates_any_notice(app) -> None:
    aviso = make_aviso(
        aviso_id="00000000-0000-0000-0000-0000000000c1",
        escopo="igreja",
        origem="central",
    )
    session = _central_session(avisos=[aviso])
    resp = _wire(app, session=session).delete(
        f"/cell-notices/{aviso.id}", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ativo"] is False
    assert aviso.ativo is False


def test_leader_inactivates_own_cell_notice(app) -> None:
    aviso = make_aviso(
        aviso_id="00000000-0000-0000-0000-0000000000c2",
        escopo="celula",
        origem="celula",
        celula_id=CELL,
    )
    session = _leader_session(avisos=[aviso])
    resp = _wire(app, session=session).delete(
        f"/cell-notices/{aviso.id}", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    assert aviso.ativo is False


def test_leader_cannot_inactivate_other_cell_notice(app) -> None:
    aviso = make_aviso(
        aviso_id="00000000-0000-0000-0000-0000000000c3",
        escopo="celula",
        origem="celula",
        celula_id=CELL,
    )
    # Célula pertence a outro líder (LP2) → 404.
    session = _leader_session(cells=[make_cell(lider_id=LP2)], avisos=[aviso])
    resp = _wire(app, session=session).delete(
        f"/cell-notices/{aviso.id}", headers=_AUTH
    )
    assert resp.status_code == 404
    assert aviso.ativo is True


def test_member_cannot_inactivate_central_notice(app) -> None:
    aviso = make_aviso(
        aviso_id="00000000-0000-0000-0000-0000000000c4",
        escopo="igreja",
        origem="central",
    )
    session = _member_session(avisos=[aviso])
    resp = _wire(app, session=session).delete(
        f"/cell-notices/{aviso.id}", headers=_AUTH
    )
    assert resp.status_code == 403
    assert aviso.ativo is True


def test_delete_unknown_is_404(app) -> None:
    session = _central_session(avisos=[])
    resp = _wire(app, session=session).delete(
        "/cell-notices/00000000-0000-0000-0000-0000000000cf", headers=_AUTH
    )
    assert resp.status_code == 404


def test_delete_malformed_id_is_404(app) -> None:
    session = _central_session(avisos=[])
    resp = _wire(app, session=session).delete("/cell-notices/nope", headers=_AUTH)
    assert resp.status_code == 404
