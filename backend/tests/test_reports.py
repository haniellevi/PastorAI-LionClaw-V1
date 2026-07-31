"""Testes de ``GET /reports`` — fonte de verdade = ``celula_reuniao`` (REPORT-SOT-1).

O painel legado #relatorios deixou de ler a tabela ``reports`` (que nunca teve
writer na aplicação e devolvia 100% pendente para sempre). Aqui provamos as três
decisões do dono:

  1. relatório só existe por OCORRÊNCIA materializada — célula sem reunião no
     período NÃO vira pendência sintética;
  2. SLA: ``pendente`` vira ``atrasado`` em ``data + hora + 2h`` (São Paulo);
  3. privacidade: a listagem tenant-wide é só de ``pastor``/``admin``.

Sessão fake em memória que INTERPRETA o WHERE de verdade (eq/ne/ge/le/in) — se o
router perder o filtro de tenant, de semana ou de cancelada, o teste quebra.
A fake NÃO tem store de ``Report``: qualquer leitura da tabela legada falharia.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.sql import operators

from app.db.models import AppUser, Celula, CelulaReuniao
from app.db.session import get_db
from app.domain.cell_meetings_schedule import now_in_sao_paulo, report_is_overdue
from app.routers import reports as reports_router
from app.routers.reports import current_iso_week
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}

TENANT = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT = "00000000-0000-0000-0000-000000000002"
CELL = "00000000-0000-0000-0000-0000000000e1"
CELL2 = "00000000-0000-0000-0000-0000000000e2"

PAST = dt.date(2000, 1, 1)  # sempre no passado (logo, sempre além do SLA de 2h)
FUTURE = dt.date(2999, 12, 31)  # sempre no futuro (logo, sempre dentro do SLA)


def week_of(data: dt.date) -> str:
    year, week, _ = data.isocalendar()
    return f"{year}-W{week:02d}"


# ===========================================================================
# Fake session que lê o WHERE real
# ===========================================================================
def _norm(value):
    if isinstance(value, (dt.date, dt.datetime, int, float, bool)):
        return value
    return str(value)


_OPS = {
    operators.eq: lambda a, b: a == b,
    operators.ne: lambda a, b: a != b,
    operators.ge: lambda a, b: a >= b,
    operators.le: lambda a, b: a <= b,
    operators.gt: lambda a, b: a > b,
    operators.lt: lambda a, b: a < b,
}


def _matches(obj, node) -> bool:
    if node is None:
        return True
    left = getattr(node, "left", None)
    right = getattr(node, "right", None)
    if left is not None and right is not None:
        key = getattr(left, "key", None)
        if key is None:
            return True
        actual = _norm(getattr(obj, key, None))
        expected = getattr(right, "value", None)
        op = getattr(node, "operator", None)
        if op is operators.in_op:
            return actual in {_norm(v) for v in (expected or [])}
        fn = _OPS.get(op)
        if fn is None:
            return True
        return fn(actual, _norm(expected))
    return all(_matches(obj, c) for c in (getattr(node, "clauses", None) or []))


class _Scalars:
    def __init__(self, items) -> None:
        self._items = list(items)

    def all(self) -> list:
        return list(self._items)

    def first(self):
        return self._items[0] if self._items else None


class _R:
    def __init__(self, *, scalar=None, scalars=None, rows=None) -> None:
        self._scalar = scalar
        self._scalars = list(scalars or [])
        self._rows = list(rows or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self) -> _Scalars:
        return _Scalars(self._scalars)

    def all(self) -> list:
        return list(self._rows)


class ReportsSession:
    """Só conhece Celula e CelulaReuniao — não existe store de ``Report``."""

    def __init__(self, *, roles, cells=None, reunioes=None, app_user=None) -> None:
        self.app_user = app_user or make_app_user()
        self.roles = roles
        self.cells = cells or []
        self.reunioes = reunioes or []

    def _match(self, store, statement):
        where = getattr(statement, "whereclause", None)
        return [o for o in store if _matches(o, where)]

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        if not descs:
            return _R(scalars=self.roles)
        ent = descs[0].get("entity")
        name = descs[0].get("name")
        if ent is AppUser and name == "pessoa_id":
            return _R(scalar=None)
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is CelulaReuniao:
            return _R(scalars=self._match(self.reunioes, statement))
        if ent is Celula and name == "id":
            return _R(rows=[(c.id, c.nome) for c in self._match(self.cells, statement)])
        if ent is Celula:
            return _R(scalars=self._match(self.cells, statement))
        return _R(scalars=self.roles)

    def add(self, obj) -> None:  # pragma: no cover - endpoint é read-only
        raise AssertionError("GET /reports não deve escrever nada")

    def flush(self) -> None:  # pragma: no cover
        pass

    def refresh(self, obj, **_kwargs) -> None:  # pragma: no cover
        pass

    def commit(self) -> None:  # pragma: no cover
        pass

    def rollback(self) -> None:  # pragma: no cover
        pass

    def close(self) -> None:  # pragma: no cover
        pass


# ===========================================================================
# Builders
# ===========================================================================
def make_cell(*, cell_id=CELL, igreja_id=TENANT, nome="Célula A", ativo=True,
              lider_id="00000000-0000-0000-0000-0000000000b1"):
    from types import SimpleNamespace

    return SimpleNamespace(
        id=cell_id, igreja_id=igreja_id, nome=nome, ativo=ativo, lider_id=lider_id
    )


def make_reuniao(
    *,
    reuniao_id,
    igreja_id=TENANT,
    celula_id=CELL,
    data,
    hora="19:30",
    status="planejada",
    relatorio_status="pendente",
    oferta_valor=None,
    observacoes=None,
    relatorio_snapshot=None,
):
    from types import SimpleNamespace

    return SimpleNamespace(
        id=reuniao_id,
        igreja_id=igreja_id,
        celula_id=celula_id,
        data=data,
        hora=hora,
        status=status,
        relatorio_status=relatorio_status,
        oferta_valor=oferta_valor,
        observacoes=observacoes,
        relatorio_snapshot=relatorio_snapshot,
    )


def snapshot(*, presencas=(), visitantes=(), records=(), oferta=None, observacoes=None):
    return {
        "presencas": [{"pessoa_id": f"p{i}", "estado": e} for i, e in enumerate(presencas)],
        "visitantes": [{"id": f"v{i}", "nome_visitante": n} for i, n in enumerate(visitantes)],
        "records": [{"id": f"r{i}", "tipo": t, "conteudo": "x"} for i, t in enumerate(records)],
        "oferta_valor": oferta,
        "observacoes": observacoes,
    }


def _wire(app, *, session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def _central(**kwargs) -> ReportsSession:
    kwargs.setdefault("roles", ["pastor"])
    return ReportsSession(**kwargs)


def _get(app, session, semana: str | None = None):
    url = "/reports" if semana is None else f"/reports?semana={semana}"
    return _wire(app, session=session).get(url, headers=_AUTH)


# ===========================================================================
# 1. Tabela `reports` vazia não impede listar o relatório real
# ===========================================================================
def test_lists_real_report_from_celula_reuniao_without_reports_table(app) -> None:
    """A fake não tem store de `Report`; o dado vem todo de `celula_reuniao`."""
    reu = make_reuniao(
        reuniao_id="r1",
        data=PAST,
        relatorio_status="enviado",
        relatorio_snapshot=snapshot(
            presencas=["compareceu", "compareceu", "ausente"],
            visitantes=["Ana"],
            records=["decisao"],
            oferta=120.5,
            observacoes="Noite boa.",
        ),
    )
    session = _central(cells=[make_cell()], reunioes=[reu])
    resp = _get(app, session, week_of(PAST))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == "r1"
    assert item["status"] == "recebido"
    assert item["celulaNome"] == "Célula A"
    assert item["dataReuniao"] == PAST.isoformat()


# ===========================================================================
# 2. Célula sem reunião materializada NÃO vira pendência virtual
# ===========================================================================
def test_cell_without_meeting_produces_no_synthetic_pending(app) -> None:
    session = _central(
        cells=[make_cell(cell_id=CELL, nome="Sem reunião")], reunioes=[]
    )
    resp = _get(app, session, week_of(PAST))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_active_led_cell_with_meeting_in_another_week_does_not_leak(app) -> None:
    reu = make_reuniao(reuniao_id="r-outra", data=PAST)
    session = _central(cells=[make_cell()], reunioes=[reu])
    resp = _get(app, session, week_of(FUTURE))
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []


# ===========================================================================
# 3. SLA de 2h — pendente antes, atrasado depois
# ===========================================================================
def test_future_meeting_is_pendente(app) -> None:
    reu = make_reuniao(reuniao_id="r-fut", data=FUTURE)
    session = _central(cells=[make_cell()], reunioes=[reu])
    resp = _get(app, session, week_of(FUTURE))
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"][0]["status"] == "pendente"


def test_long_past_meeting_is_atrasado(app) -> None:
    reu = make_reuniao(reuniao_id="r-past", data=PAST)
    session = _central(cells=[make_cell()], reunioes=[reu])
    resp = _get(app, session, week_of(PAST))
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"][0]["status"] == "atrasado"


@pytest.mark.parametrize(
    ("agora", "esperado"),
    [
        ("2026-07-15 19:29", False),  # antes da reunião
        ("2026-07-15 20:30", False),  # reunião ocorreu, dentro da carência
        ("2026-07-15 21:29", False),  # 1h59 depois — ainda pendente
        ("2026-07-15 21:30", False),  # exatamente +2h — ainda NÃO atrasado
        ("2026-07-15 21:31", True),  # passou de +2h — atrasado
        ("2026-07-16 08:00", True),
    ],
)
def test_report_is_overdue_boundary_two_hours(agora: str, esperado: bool) -> None:
    """Fronteira exata do SLA: reunião 19:30 fica atrasada só depois das 21:30."""
    now = dt.datetime.strptime(agora, "%Y-%m-%d %H:%M")
    assert (
        report_is_overdue(data=dt.date(2026, 7, 15), hora="19:30", now=now) is esperado
    )


@pytest.mark.parametrize(
    ("agora", "esperado"),
    [
        ("2026-07-15 23:59", False),
        ("2026-07-16 01:59", False),
        ("2026-07-16 02:01", True),
    ],
)
def test_report_is_overdue_without_hora_uses_day_rollover(agora, esperado) -> None:
    """Sem `hora`, a reunião só conta como ocorrida na virada do dia (+2h = 02:00)."""
    now = dt.datetime.strptime(agora, "%Y-%m-%d %H:%M")
    assert report_is_overdue(data=dt.date(2026, 7, 15), hora=None, now=now) is esperado


# ===========================================================================
# 4. Reunião cancelada não aparece
# ===========================================================================
def test_cancelled_meeting_is_excluded(app) -> None:
    cancelada = make_reuniao(reuniao_id="r-cancel", data=PAST, status="cancelada")
    viva = make_reuniao(reuniao_id="r-viva", data=PAST)
    session = _central(cells=[make_cell()], reunioes=[cancelada, viva])
    resp = _get(app, session, week_of(PAST))
    assert resp.status_code == 200, resp.text
    ids = [i["id"] for i in resp.json()["items"]]
    assert ids == ["r-viva"]


# ===========================================================================
# 5. Snapshot enviado mapeia os números reais
# ===========================================================================
def test_sent_report_maps_snapshot_numbers(app) -> None:
    reu = make_reuniao(
        reuniao_id="r-snap",
        data=PAST,
        relatorio_status="enviado",
        # Colunas divergentes de propósito: o snapshot congelado é que vale.
        oferta_valor=999.0,
        observacoes="rascunho antigo",
        relatorio_snapshot=snapshot(
            presencas=["compareceu", "compareceu", "confirmada", "ausente"],
            visitantes=["Ana", "Bia"],
            records=["decisao", "oracao", "decisao"],
            oferta=75.25,
            observacoes="Consolidado.",
        ),
    )
    session = _central(cells=[make_cell()], reunioes=[reu])
    resp = _get(app, session, week_of(PAST))
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert item["presentes"] == 2  # só 'compareceu'
    assert item["visitantes"] == 2
    assert item["decisoes"] == 2  # só tipo 'decisao'
    assert item["oferta"] == 75.25
    assert item["observacoes"] == "Consolidado."


def test_pending_report_exposes_no_numbers_or_draft_values(app) -> None:
    """Rascunho de oferta/observações não vaza antes do envio."""
    reu = make_reuniao(
        reuniao_id="r-draft",
        data=PAST,
        relatorio_status="pendente",
        oferta_valor=42.0,
        observacoes="rascunho",
    )
    session = _central(cells=[make_cell()], reunioes=[reu])
    resp = _get(app, session, week_of(PAST))
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert item["status"] == "atrasado"
    assert item["presentes"] is None
    assert item["visitantes"] is None
    assert item["decisoes"] is None
    assert item["oferta"] is None
    assert item["observacoes"] is None


def test_sent_report_without_snapshot_has_no_invented_numbers(app) -> None:
    reu = make_reuniao(
        reuniao_id="r-nosnap",
        data=PAST,
        relatorio_status="enviado",
        oferta_valor=10.0,
        observacoes="Sem snapshot",
        relatorio_snapshot=None,
    )
    session = _central(cells=[make_cell()], reunioes=[reu])
    resp = _get(app, session, week_of(PAST))
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert item["status"] == "recebido"
    assert item["presentes"] is None
    assert item["oferta"] == 10.0


# ===========================================================================
# 6. Validação de ?semana=
# ===========================================================================
@pytest.mark.parametrize(
    "semana",
    ["banana", "2026-13", "26-W13", "2026W13", "2026-W1", "2026-W1x", "2026-W00", "2026-W54"],
)
def test_invalid_week_returns_422(app, semana: str) -> None:
    session = _central(cells=[make_cell()], reunioes=[])
    resp = _get(app, session, semana)
    assert resp.status_code == 422, resp.text


def test_week_53_of_a_52_week_year_returns_422(app) -> None:
    """Validação vai além do formato: 2026 tem 53 semanas ISO? 2025 não tem."""
    session = _central(cells=[make_cell()], reunioes=[])
    assert _get(app, session, "2025-W53").status_code == 422


def test_missing_week_defaults_to_current_iso_week(app) -> None:
    hoje = now_in_sao_paulo().date()
    reu = make_reuniao(reuniao_id="r-hoje", data=hoje, relatorio_status="enviado")
    session = _central(cells=[make_cell()], reunioes=[reu])
    resp = _get(app, session)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"][0]["semana"] == week_of(hoje)


# ---------------------------------------------------------------------------
# Semana padrão no fuso do PRODUTO (America/Sao_Paulo), não no fuso do host
# ---------------------------------------------------------------------------
# 2026-08-03T00:30Z = domingo 02/08 21:30 em São Paulo. Em UTC a data já virou
# segunda (semana 32); em São Paulo ainda é domingo (semana 31).
_MEIA_NOITE_UTC = dt.datetime(2026, 8, 3, 0, 30, tzinfo=dt.timezone.utc)


def test_current_iso_week_uses_sao_paulo_not_host_timezone() -> None:
    assert current_iso_week(_MEIA_NOITE_UTC) == "2026-W31"
    # Prova de que o caso é discriminante: no fuso do host (UTC) daria W32.
    assert f"{_MEIA_NOITE_UTC.date().isocalendar()[0]}-W{_MEIA_NOITE_UTC.date().isocalendar()[1]:02d}" == "2026-W32"


def test_default_week_endpoint_uses_sao_paulo(app, monkeypatch) -> None:
    """Sem ``?semana=``, o endpoint resolve a semana em São Paulo.

    Congela o relógio no instante exigido chamando a função REAL com `now`
    injetado — nada aqui depende da data nem do fuso da máquina.
    """
    monkeypatch.setattr(
        reports_router, "current_iso_week", lambda: current_iso_week(_MEIA_NOITE_UTC)
    )
    # Domingo 02/08 (semana 31) entra; segunda 03/08 (semana 32) fica de fora.
    domingo = make_reuniao(
        reuniao_id="r-domingo", data=dt.date(2026, 8, 2), relatorio_status="enviado"
    )
    segunda = make_reuniao(
        reuniao_id="r-segunda", data=dt.date(2026, 8, 3), relatorio_status="enviado"
    )
    session = _central(cells=[make_cell()], reunioes=[domingo, segunda])
    resp = _get(app, session)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [i["id"] for i in body["items"]] == ["r-domingo"]
    assert body["items"][0]["semana"] == "2026-W31"


# ===========================================================================
# 7. Autorização — só pastor/admin
# ===========================================================================
@pytest.mark.parametrize("papel", ["pastor", "admin"])
def test_central_roles_can_list(app, papel: str) -> None:
    session = ReportsSession(roles=[papel], cells=[make_cell()], reunioes=[])
    resp = _get(app, session, week_of(PAST))
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize(
    "papel", ["lider", "lider_celula", "lider_g12", "lider_mult", "operador", "membro"]
)
def test_non_central_roles_are_forbidden(app, papel: str) -> None:
    reu = make_reuniao(
        reuniao_id="r1",
        data=PAST,
        relatorio_status="enviado",
        relatorio_snapshot=snapshot(oferta=500.0, observacoes="sigiloso"),
    )
    session = ReportsSession(roles=[papel], cells=[make_cell()], reunioes=[reu])
    resp = _get(app, session, week_of(PAST))
    assert resp.status_code == 403, resp.text
    assert "sigiloso" not in resp.text


def test_requires_authentication(app) -> None:
    session = _central()
    resp = _wire(app, session=session).get("/reports")
    assert resp.status_code == 401


# ===========================================================================
# 8. Isolamento por tenant
# ===========================================================================
def test_other_tenant_meetings_never_appear(app) -> None:
    minha = make_reuniao(reuniao_id="r-minha", data=PAST)
    alheia = make_reuniao(
        reuniao_id="r-alheia", igreja_id=OTHER_TENANT, celula_id=CELL2, data=PAST
    )
    session = _central(
        cells=[make_cell(), make_cell(cell_id=CELL2, igreja_id=OTHER_TENANT, nome="De outra igreja")],
        reunioes=[minha, alheia],
    )
    resp = _get(app, session, week_of(PAST))
    assert resp.status_code == 200, resp.text
    ids = [i["id"] for i in resp.json()["items"]]
    assert ids == ["r-minha"]
    assert "De outra igreja" not in resp.text


# ===========================================================================
# Grão: duas reuniões da mesma célula na mesma semana = duas linhas distintas
# ===========================================================================
def test_two_meetings_same_cell_same_week_are_two_rows(app) -> None:
    a = make_reuniao(reuniao_id="r-a", data=PAST, hora="19:30", relatorio_status="enviado",
                     relatorio_snapshot=snapshot(presencas=["compareceu"]))
    b = make_reuniao(reuniao_id="r-b", data=PAST, hora="21:00")
    session = _central(cells=[make_cell()], reunioes=[a, b])
    resp = _get(app, session, week_of(PAST))
    assert resp.status_code == 200, resp.text
    items = {i["id"]: i for i in resp.json()["items"]}
    assert set(items) == {"r-a", "r-b"}
    assert items["r-a"]["status"] == "recebido"
    assert items["r-b"]["status"] == "atrasado"
