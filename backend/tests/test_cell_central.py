"""Testes de ``cell_central`` — dashboard, fila de pendências e saúde (E16/E6).

Fake-session em memória (``CellSession``). Toda a superfície é restrita à Central
(``require_central`` → 403 para os demais). ``igreja_id`` vem do contexto
autenticado. Datas em extremos (2000 = passada; 2999 = futura) tornam
``meeting_has_passed`` determinista.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.cell_backend_fakes import (
    CELL,
    LP,
    PAST,
    REU,
    CellSession,
    make_app_user,
    make_aviso,
    make_cell,
    make_material,
    make_pessoa,
    make_reuniao,
    make_solicitacao,
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
    return CellSession(**kwargs)


# ===========================================================================
# GET /cell-central/dashboard
# ===========================================================================
def test_dashboard_counts_operational_metrics(app) -> None:
    cell = make_cell(cell_id=CELL, nome="A", lider_id=LP)
    # Reunião passada, não cancelada, relatório pendente → pendente + vermelho.
    reu = make_reuniao(
        reuniao_id=REU, celula_id=CELL, data=PAST, relatorio_status="pendente"
    )
    solicitacoes = [
        make_solicitacao(tipo="alterar_dia", status="aguardando"),
        make_solicitacao(tipo="multiplicacao", status="aguardando"),
    ]
    avisos = [make_aviso(aviso_id="a1", escopo="igreja", ativo=True)]
    materiais = [make_material(material_id="m1", ativo=True)]
    session = _central_session(
        cells=[cell],
        reunioes=[reu],
        solicitacoes=solicitacoes,
        avisos=avisos,
        materiais=materiais,
    )
    resp = _wire(app, session=session).get(
        "/cell-central/dashboard", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["relatorios_pendentes"] == 1
    assert body["solicitacoes_aguardando"] == 2
    assert body["multiplicacoes_pendentes"] == 1
    assert body["celulas_com_alerta"] == 1
    assert body["avisos_recentes"] == 1
    assert body["materiais_recentes"] == 1


def test_dashboard_zeroed_when_empty(app) -> None:
    session = _central_session()
    resp = _wire(app, session=session).get(
        "/cell-central/dashboard", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "relatorios_pendentes": 0,
        "solicitacoes_aguardando": 0,
        "celulas_com_alerta": 0,
        "multiplicacoes_pendentes": 0,
        "avisos_recentes": 0,
        "materiais_recentes": 0,
    }


def test_dashboard_forbidden_for_non_central(app) -> None:
    session = _member_session()
    resp = _wire(app, session=session).get(
        "/cell-central/dashboard", headers=_AUTH
    )
    assert resp.status_code == 403


def test_dashboard_requires_auth(app) -> None:
    session = _central_session()
    resp = _wire(app, session=session).get("/cell-central/dashboard")
    assert resp.status_code == 401


# ===========================================================================
# GET /cell-central/pending-reports
# ===========================================================================
def test_pending_reports_resolves_cell_and_leader(app) -> None:
    cell = make_cell(cell_id=CELL, nome="Célula A", lider_id=LP)
    reu = make_reuniao(
        reuniao_id=REU, celula_id=CELL, data=PAST, relatorio_status="pendente"
    )
    pessoa = make_pessoa(pessoa_id=LP, nome="Líder Ana")
    session = _central_session(
        cells=[cell], reunioes=[reu], pessoas=[pessoa]
    )
    resp = _wire(app, session=session).get(
        "/cell-central/pending-reports", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["reuniao_id"] == REU
    assert item["celula_id"] == CELL
    assert item["celula_nome"] == "Célula A"
    assert item["lider_nome"] == "Líder Ana"
    assert item["data"] == PAST.isoformat()


def test_pending_reports_excludes_sent_and_future(app) -> None:
    cell = make_cell(cell_id=CELL, nome="A", lider_id=LP)
    enviado = make_reuniao(
        reuniao_id="r-sent", celula_id=CELL, data=PAST, relatorio_status="enviado"
    )
    session = _central_session(cells=[cell], reunioes=[enviado])
    resp = _wire(app, session=session).get(
        "/cell-central/pending-reports", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []


def test_pending_reports_forbidden_for_non_central(app) -> None:
    session = _member_session()
    resp = _wire(app, session=session).get(
        "/cell-central/pending-reports", headers=_AUTH
    )
    assert resp.status_code == 403


# ===========================================================================
# GET /cell-central/health
# ===========================================================================
def test_health_serializes_cells(app) -> None:
    cell = make_cell(cell_id=CELL, nome="A", lider_id=LP)
    reu = make_reuniao(
        reuniao_id=REU, celula_id=CELL, data=PAST, relatorio_status="pendente"
    )
    session = _central_session(cells=[cell], reunioes=[reu])
    resp = _wire(app, session=session).get(
        "/cell-central/health", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    cells = resp.json()["cells"]
    assert len(cells) == 1
    entry = cells[0]
    assert entry["celula_id"] == CELL
    assert entry["celula_nome"] == "A"
    assert entry["status"] == "ok"
    assert entry["vermelhos"] == 1
    assert entry["sinais"][0]["cor"] == "vermelho"


def test_health_forbidden_for_non_central(app) -> None:
    session = _member_session()
    resp = _wire(app, session=session).get(
        "/cell-central/health", headers=_AUTH
    )
    assert resp.status_code == 403


def test_health_requires_auth(app) -> None:
    session = _central_session()
    resp = _wire(app, session=session).get("/cell-central/health")
    assert resp.status_code == 401
