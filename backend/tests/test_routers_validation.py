"""Edge-validation and auth-wiring tests for the pastoral routers.

These exercise the HTTP contracts that run *before* any database access:
input validation (422) and authentication gating (401). Business rules that
touch persistence are covered by the pure unit tests in test_domain_logic.py.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user

_AUTH = {"Authorization": "Bearer good"}


def _client(app) -> TestClient:
    app.dependency_overrides[get_db] = lambda: FakeSession(
        app_user=make_app_user(), roles=["admin"]
    )
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


# ---- auth gating ----------------------------------------------------------
def test_contacts_requires_auth(app) -> None:
    client = _client(app)
    assert client.get("/contacts").status_code == 401


def test_cells_requires_auth(app) -> None:
    client = _client(app)
    assert client.get("/cells").status_code == 401


def test_work_queue_requires_auth(app) -> None:
    client = _client(app)
    assert client.get("/work-queue").status_code == 401


# ---- create contact validation -------------------------------------------
def test_create_contact_rejects_invalid_genero(app) -> None:
    client = _client(app)
    resp = client.post(
        "/contacts",
        json={"nome": "Maria", "telefone": "11999990000", "genero": "x"},
        headers=_AUTH,
    )
    assert resp.status_code == 422


def test_create_contact_requires_nome_and_telefone(app) -> None:
    client = _client(app)
    resp = client.post("/contacts", json={"nome": "Maria"}, headers=_AUTH)
    assert resp.status_code == 422


def test_create_contact_rejects_invalid_tipo(app) -> None:
    client = _client(app)
    resp = client.post(
        "/contacts",
        json={"nome": "Maria", "telefone": "11999990000", "tipo": "anjo"},
        headers=_AUTH,
    )
    assert resp.status_code == 422


# ---- cell upsert validation -----------------------------------------------
def test_upsert_cell_requires_cobertura(app) -> None:
    client = _client(app)
    resp = client.post("/cells", json={"nome": "Célula Norte"}, headers=_AUTH)
    assert resp.status_code == 422


def test_upsert_cell_rejects_blank_cobertura(app) -> None:
    client = _client(app)
    resp = client.post(
        "/cells",
        json={"nome": "Célula Norte", "coberturaEspiritual": "   "},
        headers=_AUTH,
    )
    assert resp.status_code == 422


# ---- pipeline validation --------------------------------------------------
def test_pipeline_rejects_invalid_etapa(app) -> None:
    client = _client(app)
    resp = client.put(
        "/pipeline",
        json={
            "pessoaId": "00000000-0000-0000-0000-0000000000aa",
            "etapa": "invalida",
        },
        headers=_AUTH,
    )
    assert resp.status_code == 422


def test_pipeline_rejects_invalid_pessoa_uuid(app) -> None:
    client = _client(app)
    resp = client.put(
        "/pipeline",
        json={"pessoaId": "not-a-uuid", "etapa": "consolidar"},
        headers=_AUTH,
    )
    assert resp.status_code == 422


# ---- work-queue action validation -----------------------------------------
def test_work_queue_action_rejects_unknown_action(app) -> None:
    client = _client(app)
    resp = client.post(
        "/work-queue/00000000-0000-0000-0000-0000000000bb/action",
        json={"action": "delete"},
        headers=_AUTH,
    )
    assert resp.status_code == 422


def test_work_queue_message_requires_text(app) -> None:
    client = _client(app)
    resp = client.post(
        "/work-queue/00000000-0000-0000-0000-0000000000bb/message",
        json={"mensagem": "   "},
        headers=_AUTH,
    )
    assert resp.status_code == 422


# ---- launch decision validation -------------------------------------------
def test_launch_decision_requires_auth(app) -> None:
    client = _client(app)
    resp = client.post(
        "/consolidacao/decisao",
        json={"pessoa": "00000000-0000-0000-0000-0000000000aa", "vinculo": "celula"},
    )
    assert resp.status_code == 401


def test_launch_decision_rejects_invalid_vinculo(app) -> None:
    client = _client(app)
    resp = client.post(
        "/consolidacao/decisao",
        json={"pessoa": "00000000-0000-0000-0000-0000000000aa", "vinculo": "x"},
        headers=_AUTH,
    )
    assert resp.status_code == 422


def test_launch_decision_rejects_invalid_pessoa_uuid(app) -> None:
    client = _client(app)
    resp = client.post(
        "/consolidacao/decisao",
        json={"pessoa": "not-a-uuid", "vinculo": "visitante"},
        headers=_AUTH,
    )
    assert resp.status_code == 422


# ---- advance-stage / assign-consolidador validation -----------------------
def test_advance_stage_rejects_invalid_etapa(app) -> None:
    client = _client(app)
    resp = client.post(
        "/pipeline/advance-stage",
        json={
            "consolidacaoId": "00000000-0000-0000-0000-0000000000cc",
            "etapa": "invalida",
        },
        headers=_AUTH,
    )
    assert resp.status_code == 422


def test_advance_stage_requires_etapa_or_conclude(app) -> None:
    client = _client(app)
    resp = client.post(
        "/pipeline/advance-stage",
        json={"consolidacaoId": "00000000-0000-0000-0000-0000000000cc"},
        headers=_AUTH,
    )
    assert resp.status_code == 422


def test_assign_consolidador_rejects_invalid_uuid(app) -> None:
    client = _client(app)
    resp = client.post(
        "/pipeline/assign-consolidador",
        json={"consolidacaoId": "not-a-uuid", "responsavelId": "also-bad"},
        headers=_AUTH,
    )
    assert resp.status_code == 422


# ---- multiplications validation -------------------------------------------
def test_multiplicacoes_requires_auth(app) -> None:
    client = _client(app)
    assert client.get("/multiplicacoes").status_code == 401


def test_list_multiplicacoes_rejects_invalid_status(app) -> None:
    client = _client(app)
    resp = client.get("/multiplicacoes?status=invalido", headers=_AUTH)
    assert resp.status_code == 422


def test_create_multiplicacao_rejects_invalid_celula_uuid(app) -> None:
    client = _client(app)
    resp = client.post(
        "/multiplicacoes",
        json={"celulaId": "not-a-uuid"},
        headers=_AUTH,
    )
    assert resp.status_code == 422
