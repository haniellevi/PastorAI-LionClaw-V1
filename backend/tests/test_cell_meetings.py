"""Testes das reuniões de célula (Células PR2 / Domínio A) — US-01..US-04.

Cobre o serviço determinista de cálculo (parser PT-BR + próxima data com relógio
injetável) e os dois endpoints do router próprio ``cell_meetings``:

  - GET  /cells/{id}/reunioes        listagem ordenada + isolamento por tenant;
  - POST /cells/{id}/reunioes/next   materialização idempotente, 422 sem
                                     dia/horário, 403 para membro comum.

Segue o estilo fake-session de ``test_cells_crud.py`` (sem Postgres real): o fake
espelha os predicados WHERE e a ordenação do router, então largar um filtro/ORDER
BY quebra os testes. UNIQUE/RLS reais são validados manualmente no DEV.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.models import (
    AppUser,
    Celula,
    CelulaExpectativaVisitante,
    CelulaMembro,
    CelulaPresenca,
    CelulaReuniao,
    Pessoa,
)
from app.db.session import get_db
from app.domain.cell_meetings_schedule import (
    InvalidDiaReuniao,
    next_meeting_date,
    parse_weekday,
)
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}

_TENANT = "00000000-0000-0000-0000-000000000001"
_OTHER = "00000000-0000-0000-0000-000000000002"
_CELL = "00000000-0000-0000-0000-0000000000e1"
_OTHER_CELL = "00000000-0000-0000-0000-0000000000e2"  # outra célula do tenant
_LP = "00000000-0000-0000-0000-0000000000b1"  # pessoa do líder-ator
_OUTSIDER = "00000000-0000-0000-0000-0000000000c9"  # pessoa que não lidera
_TARGET = "00000000-0000-0000-0000-0000000000d1"  # pessoa alvo (terceiro)
_REU = "00000000-0000-0000-0000-0000000000f1"  # reunião


# ===========================================================================
# US-01 — serviço de cálculo (parser + próxima data determinista)
# ===========================================================================
def test_parse_accepts_full_names_and_abbreviations() -> None:
    assert parse_weekday("segunda") == 0
    assert parse_weekday("Terça") == 1  # acento normalizado
    assert parse_weekday("QUARTA-FEIRA") == 2  # sufixo -feira removido
    assert parse_weekday("quinta-feira") == 3
    assert parse_weekday("sexta") == 4
    assert parse_weekday("sábado") == 5
    assert parse_weekday("domingo") == 6
    # abreviações de 3 letras
    assert parse_weekday("seg") == 0
    assert parse_weekday("ter") == 1
    assert parse_weekday("qua") == 2
    assert parse_weekday("qui") == 3
    assert parse_weekday("sex") == 4
    assert parse_weekday("sab") == 5
    assert parse_weekday("dom") == 6


@pytest.mark.parametrize(
    "value",
    [None, "", "   ", "2", "toda quinta", "quinta a noite", "seg.", "segundas"],
)
def test_parse_rejects_out_of_allowlist(value) -> None:
    with pytest.raises(InvalidDiaReuniao):
        parse_weekday(value)


def test_next_meeting_future_weekday_is_soonest_occurrence() -> None:
    now = dt.datetime(2026, 7, 6, 10, 0)  # segunda-feira
    result = next_meeting_date(dia_reuniao="sexta", hora="20:00", now=now)
    assert result.weekday() == 4  # sexta
    assert result >= now.date()
    assert (result - now.date()).days < 7


def test_next_meeting_today_before_time_stays_today() -> None:
    now = dt.datetime(2026, 7, 6, 10, 0)  # segunda 10:00
    result = next_meeting_date(dia_reuniao="segunda", hora="20:00", now=now)
    assert result == dt.date(2026, 7, 6)


def test_next_meeting_today_after_time_advances_a_week() -> None:
    now = dt.datetime(2026, 7, 6, 21, 0)  # segunda 21:00, já passou das 20:00
    result = next_meeting_date(dia_reuniao="segunda", hora="20:00", now=now)
    assert result == dt.date(2026, 7, 13)


def test_next_meeting_aware_now_is_converted_to_sao_paulo() -> None:
    # 2026-07-07 00:30 UTC == 2026-07-06 21:30 em São Paulo (segunda, -03:00).
    now = dt.datetime(2026, 7, 7, 0, 30, tzinfo=dt.timezone.utc)
    result = next_meeting_date(dia_reuniao="segunda", hora="20:00", now=now)
    assert result == dt.date(2026, 7, 13)


def test_next_meeting_rejects_invalid_dia() -> None:
    with pytest.raises(InvalidDiaReuniao):
        next_meeting_date(dia_reuniao="banana", hora="20:00")


# ===========================================================================
# Fake session (espelha predicados WHERE + ORDER BY do router)
# ===========================================================================
class _R:
    def __init__(self, *, scalar=None, scalars=None, rows=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def all(self):
        return list(self._rows)


class MeetingSession:
    def __init__(
        self,
        *,
        app_user,
        roles,
        cells=None,
        reunioes=None,
        pessoas=None,
        membros=None,
        presencas=None,
        expectativas=None,
        actor_pessoa_id=None,
    ) -> None:
        self.app_user = app_user
        self.roles = roles
        self.cells = cells or []
        self.reunioes = reunioes or []
        self.pessoas = pessoas or []
        self.membros = membros or []
        self.presencas = presencas or []
        self.expectativas = expectativas or []
        self.actor_pessoa_id = actor_pessoa_id
        self.added: list = []
        self.committed = False

    @staticmethod
    def _eq_predicates(statement) -> dict[str, str]:
        preds: dict[str, str] = {}
        clause = getattr(statement, "whereclause", None)
        stack = [clause] if clause is not None else []
        while stack:
            node = stack.pop()
            left = getattr(node, "left", None)
            right = getattr(node, "right", None)
            if left is not None and right is not None:
                key = getattr(left, "key", None)
                value = getattr(right, "value", None)
                if key is not None and value is not None:
                    preds[key] = str(value)
                continue
            stack.extend(getattr(node, "clauses", []) or [])
        return preds

    def _filter(self, store, statement):
        preds = self._eq_predicates(statement)
        return [
            o
            for o in store
            if all(str(getattr(o, k, None)) == v for k, v in preds.items())
        ]

    @staticmethod
    def _wants_active(statement) -> bool:
        """True se o WHERE filtra por `ativo` (predicado `ativo.is_(True)`).

        `_eq_predicates` descarta o IS-clause (value=None); detectamos a coluna
        `ativo` no WHERE para aplicar o filtro — se o router LARGAR esse filtro,
        o fake para de aplicá-lo e os testes de vínculo inativo quebram.
        """
        clause = getattr(statement, "whereclause", None)
        stack = [clause] if clause is not None else []
        while stack:
            node = stack.pop()
            left = getattr(node, "left", None)
            if left is not None and getattr(left, "key", None) == "ativo":
                return True
            stack.extend(getattr(node, "clauses", []) or [])
        return False

    @staticmethod
    def _order_reunioes(rows):
        """Espelha ORDER BY data DESC, hora DESC NULLS LAST, id DESC (passes estáveis)."""
        rows = list(rows)
        rows.sort(key=lambda r: str(r.id), reverse=True)
        rows.sort(key=lambda r: (r.hora or ""), reverse=True)
        rows.sort(key=lambda r: r.hora is None)  # nulls last (estável)
        rows.sort(key=lambda r: r.data, reverse=True)
        return rows

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        name = descs[0].get("name") if descs else None

        if ent is AppUser and name == "pessoa_id":
            return _R(scalar=self.actor_pessoa_id)
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is Celula:
            rows = self._filter(self.cells, statement)
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is CelulaReuniao:
            rows = self._filter(self.reunioes, statement)
            if getattr(statement, "_order_by_clauses", ()):
                rows = self._order_reunioes(rows)
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is CelulaMembro:
            rows = self._filter(self.membros, statement)
            if self._wants_active(statement):
                rows = [r for r in rows if getattr(r, "ativo", True) is True]
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is CelulaPresenca:
            rows = self._filter(self.presencas, statement)
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is Pessoa and len(descs) > 1:
            return _R(rows=[(p.id, p.lider_id) for p in self.pessoas])
        if ent is Pessoa:
            rows = self._filter(self.pessoas, statement)
            return _R(scalar=(rows[0] if rows else None))
        # set_config text / UserRole.papel projection.
        return _R(scalars=self.roles)

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        if isinstance(obj, CelulaReuniao):
            self.reunioes.append(obj)
        if isinstance(obj, CelulaPresenca):
            self.presencas.append(obj)
        if isinstance(obj, CelulaExpectativaVisitante):
            self.expectativas.append(obj)

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:  # pragma: no cover - sem corrida real nos testes
        pass

    def close(self) -> None:  # pragma: no cover
        pass


def make_cell(
    *,
    cell_id: str = _CELL,
    igreja_id: str = _TENANT,
    lider_id: str | None = None,
    dia_reuniao: str | None = "quarta",
    horario: str | None = "20:00",
):
    return SimpleNamespace(
        id=cell_id,
        igreja_id=igreja_id,
        nome="Célula Central",
        lider_id=lider_id,
        dia_reuniao=dia_reuniao,
        horario=horario,
    )


def make_pessoa(*, pessoa_id: str = _LP, lider_id: str | None = None):
    return SimpleNamespace(id=pessoa_id, lider_id=lider_id)


def make_reuniao(
    *,
    reuniao_id: str,
    igreja_id: str = _TENANT,
    celula_id: str = _CELL,
    data: dt.date,
    hora: str | None = "20:00",
    tema: str | None = None,
    status: str = "planejada",
):
    return SimpleNamespace(
        id=reuniao_id,
        igreja_id=igreja_id,
        celula_id=celula_id,
        data=data,
        hora=hora,
        tema=tema,
        status=status,
    )


def make_member(
    *,
    member_id: str = "00000000-0000-0000-0000-0000000000a1",
    igreja_id: str = _TENANT,
    celula_id: str = _CELL,
    pessoa_id: str = _TARGET,
    papel: str = "membro",
    ativo: bool = True,
):
    return SimpleNamespace(
        id=member_id,
        igreja_id=igreja_id,
        celula_id=celula_id,
        pessoa_id=pessoa_id,
        papel=papel,
        ativo=ativo,
    )


def make_presenca(
    *,
    presenca_id: str = "00000000-0000-0000-0000-0000000000a2",
    igreja_id: str = _TENANT,
    reuniao_id: str = _REU,
    pessoa_id: str = _TARGET,
    estado: str = "confirmada",
    origem: str | None = "lider",
):
    return SimpleNamespace(
        id=presenca_id,
        igreja_id=igreja_id,
        reuniao_id=reuniao_id,
        pessoa_id=pessoa_id,
        estado=estado,
        origem=origem,
        updated_at=None,
    )


def _wire(app, *, session, clerk=None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk or FakeClerk()
    return TestClient(app)


# ===========================================================================
# US-04 — POST /cells/{id}/reunioes/next (materializar, idempotente)
# ===========================================================================
def test_materialize_creates_planejada(app) -> None:
    cell = make_cell(dia_reuniao="quarta", horario="20:00")
    session = MeetingSession(
        app_user=make_app_user(), roles=["pastor"], cells=[cell]
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/reunioes/next", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "planejada"
    assert body["hora"] == "20:00"
    assert body["celulaId"] == _CELL
    assert body["tema"] is None
    # data no formato YYYY-MM-DD.
    dt.date.fromisoformat(body["data"])
    assert session.committed is True


def test_materialize_is_idempotent(app) -> None:
    cell = make_cell(dia_reuniao="quarta", horario="20:00")
    session = MeetingSession(
        app_user=make_app_user(), roles=["pastor"], cells=[cell]
    )
    client = _wire(app, session=session)
    first = client.post(f"/cells/{_CELL}/reunioes/next", headers=_AUTH)
    second = client.post(f"/cells/{_CELL}/reunioes/next", headers=_AUTH)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    # segunda chamada devolve a MESMA reunião (sem duplicar).
    assert first.json()["id"] == second.json()["id"]
    assert len(session.reunioes) == 1


def test_materialize_422_without_dia(app) -> None:
    cell = make_cell(dia_reuniao=None, horario="20:00")
    session = MeetingSession(
        app_user=make_app_user(), roles=["pastor"], cells=[cell]
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/reunioes/next", headers=_AUTH
    )
    assert resp.status_code == 422
    assert session.reunioes == []  # nenhuma linha criada
    assert session.committed is False


def test_materialize_422_with_unrecognized_dia(app) -> None:
    cell = make_cell(dia_reuniao="toda quarta", horario="20:00")
    session = MeetingSession(
        app_user=make_app_user(), roles=["pastor"], cells=[cell]
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/reunioes/next", headers=_AUTH
    )
    assert resp.status_code == 422
    assert session.reunioes == []


def test_materialize_422_without_horario(app) -> None:
    cell = make_cell(dia_reuniao="quarta", horario=None)
    session = MeetingSession(
        app_user=make_app_user(), roles=["pastor"], cells=[cell]
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/reunioes/next", headers=_AUTH
    )
    assert resp.status_code == 422
    assert session.reunioes == []


def test_materialize_forbidden_for_member(app) -> None:
    # Membro comum (não pastor/Central, não líder da célula) → 403.
    cell = make_cell(lider_id=_LP, dia_reuniao="quarta", horario="20:00")
    session = MeetingSession(
        app_user=make_app_user(),
        roles=["membro"],
        cells=[cell],
        pessoas=[make_pessoa(pessoa_id=_LP)],
        actor_pessoa_id=_OUTSIDER,
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/reunioes/next", headers=_AUTH
    )
    assert resp.status_code == 403
    assert session.reunioes == []


def test_materialize_allowed_for_cell_leader(app) -> None:
    # Líder da célula (via hierarquia), papel não-Central → pode materializar.
    cell = make_cell(lider_id=_LP, dia_reuniao="quarta", horario="20:00")
    session = MeetingSession(
        app_user=make_app_user(),
        roles=["lider_celula"],
        cells=[cell],
        pessoas=[make_pessoa(pessoa_id=_LP)],
        actor_pessoa_id=_LP,
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/reunioes/next", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "planejada"


def test_materialize_requires_auth(app) -> None:
    session = MeetingSession(
        app_user=make_app_user(), roles=["pastor"], cells=[make_cell()]
    )
    resp = _wire(app, session=session).post(f"/cells/{_CELL}/reunioes/next")
    assert resp.status_code == 401


def test_materialize_404_for_unknown_cell(app) -> None:
    session = MeetingSession(app_user=make_app_user(), roles=["pastor"], cells=[])
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/reunioes/next", headers=_AUTH
    )
    assert resp.status_code == 404


# ===========================================================================
# US-03 — GET /cells/{id}/reunioes (listar, ordenado, isolado por tenant)
# ===========================================================================
def test_list_reunioes_ordered_desc(app) -> None:
    r1 = make_reuniao(reuniao_id="r1", data=dt.date(2026, 7, 1), hora="20:00")
    r2 = make_reuniao(reuniao_id="r2", data=dt.date(2026, 7, 8), hora="19:00")
    r3 = make_reuniao(reuniao_id="r3", data=dt.date(2026, 7, 8), hora=None)
    r4 = make_reuniao(reuniao_id="r4", data=dt.date(2026, 7, 1), hora="19:00")
    session = MeetingSession(
        app_user=make_app_user(),
        roles=["membro"],  # qualquer autenticado do tenant lê
        cells=[make_cell()],
        reunioes=[r1, r2, r3, r4],
    )
    resp = _wire(app, session=session).get(
        f"/cells/{_CELL}/reunioes", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    ids = [r["id"] for r in resp.json()]
    # data DESC, depois hora DESC com NULLS LAST.
    assert ids == ["r2", "r3", "r1", "r4"]


def test_list_reunioes_tenant_isolation(app) -> None:
    mine = make_reuniao(reuniao_id="mine", igreja_id=_TENANT, data=dt.date(2026, 7, 1))
    foreign = make_reuniao(
        reuniao_id="foreign", igreja_id=_OTHER, data=dt.date(2026, 7, 2)
    )
    session = MeetingSession(
        app_user=make_app_user(),
        roles=["pastor"],
        cells=[make_cell()],
        reunioes=[mine, foreign],
    )
    resp = _wire(app, session=session).get(
        f"/cells/{_CELL}/reunioes", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    assert [r["id"] for r in resp.json()] == ["mine"]


def test_list_reunioes_empty(app) -> None:
    session = MeetingSession(
        app_user=make_app_user(), roles=["pastor"], cells=[make_cell()], reunioes=[]
    )
    resp = _wire(app, session=session).get(
        f"/cells/{_CELL}/reunioes", headers=_AUTH
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_reunioes_requires_auth(app) -> None:
    session = MeetingSession(
        app_user=make_app_user(), roles=["pastor"], cells=[make_cell()]
    )
    resp = _wire(app, session=session).get(f"/cells/{_CELL}/reunioes")
    assert resp.status_code == 401


def test_list_reunioes_404_for_unknown_cell(app) -> None:
    session = MeetingSession(app_user=make_app_user(), roles=["pastor"], cells=[])
    resp = _wire(app, session=session).get(
        f"/cells/{_CELL}/reunioes", headers=_AUTH
    )
    assert resp.status_code == 404


# ===========================================================================
# US-05..US-08 — POST /cell-reunioes/{id}/presenca (auto + terceiro, upsert)
# ===========================================================================
def test_presenca_auto_confirmacao(app) -> None:
    # Sem pessoaId → auto-confirmação da própria pessoa do app_user.
    reu = make_reuniao(reuniao_id=_REU, data=dt.date(2026, 7, 8))
    session = MeetingSession(
        app_user=make_app_user(),
        roles=["membro"],
        reunioes=[reu],
        membros=[make_member(pessoa_id=_TARGET, celula_id=_CELL, ativo=True)],
        actor_pessoa_id=_TARGET,
    )
    resp = _wire(app, session=session).post(
        f"/cell-reunioes/{_REU}/presenca", headers=_AUTH, json={}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["estado"] == "confirmada"
    assert body["origem"] == "auto"
    assert body["pessoaId"] == _TARGET
    assert body["reuniaoId"] == _REU
    assert session.committed is True
    assert len(session.presencas) == 1


def test_presenca_por_lider(app) -> None:
    # Com pessoaId de terceiro + papel pastor → origem=lider.
    reu = make_reuniao(reuniao_id=_REU, data=dt.date(2026, 7, 8))
    session = MeetingSession(
        app_user=make_app_user(),
        roles=["pastor"],
        cells=[make_cell()],
        reunioes=[reu],
        pessoas=[make_pessoa(pessoa_id=_TARGET)],
        membros=[make_member(pessoa_id=_TARGET, celula_id=_CELL, ativo=True)],
        actor_pessoa_id=_LP,
    )
    resp = _wire(app, session=session).post(
        f"/cell-reunioes/{_REU}/presenca", headers=_AUTH, json={"pessoaId": _TARGET}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["estado"] == "confirmada"
    assert body["origem"] == "lider"
    assert body["pessoaId"] == _TARGET


def test_presenca_idempotente_sem_duplicar(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=dt.date(2026, 7, 8))
    session = MeetingSession(
        app_user=make_app_user(),
        roles=["membro"],
        reunioes=[reu],
        membros=[make_member(pessoa_id=_TARGET, celula_id=_CELL, ativo=True)],
        actor_pessoa_id=_TARGET,
    )
    client = _wire(app, session=session)
    first = client.post(f"/cell-reunioes/{_REU}/presenca", headers=_AUTH, json={})
    second = client.post(f"/cell-reunioes/{_REU}/presenca", headers=_AUTH, json={})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    # Presença é SEMPRE 200 — nunca 409 (409 é exclusivo de add_cell_member).
    assert second.status_code != 409
    assert first.json()["id"] == second.json()["id"]
    assert len(session.presencas) == 1


def test_presenca_remarcacao_last_write_wins(app) -> None:
    # Linha pré-existente (origem=lider); auto pela própria pessoa sobrescreve.
    reu = make_reuniao(reuniao_id=_REU, data=dt.date(2026, 7, 8))
    pre = make_presenca(pessoa_id=_TARGET, reuniao_id=_REU, origem="lider")
    session = MeetingSession(
        app_user=make_app_user(),
        roles=["membro"],
        reunioes=[reu],
        membros=[make_member(pessoa_id=_TARGET, celula_id=_CELL, ativo=True)],
        presencas=[pre],
        actor_pessoa_id=_TARGET,
    )
    resp = _wire(app, session=session).post(
        f"/cell-reunioes/{_REU}/presenca", headers=_AUTH, json={}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["origem"] == "auto"  # last-write-wins: lider -> auto
    assert body["id"] == str(pre.id)  # mesma linha, sem duplicar
    assert len(session.presencas) == 1


def test_presenca_403_membro_comum_marca_outro(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=dt.date(2026, 7, 8))
    session = MeetingSession(
        app_user=make_app_user(),
        roles=["membro"],
        cells=[make_cell(lider_id=_LP)],
        reunioes=[reu],
        pessoas=[make_pessoa(pessoa_id=_LP), make_pessoa(pessoa_id=_TARGET)],
        membros=[make_member(pessoa_id=_TARGET, celula_id=_CELL, ativo=True)],
        actor_pessoa_id=_OUTSIDER,
    )
    resp = _wire(app, session=session).post(
        f"/cell-reunioes/{_REU}/presenca", headers=_AUTH, json={"pessoaId": _TARGET}
    )
    assert resp.status_code == 403
    assert session.presencas == []


def test_presenca_403_app_user_sem_pessoa(app) -> None:
    # Auto-confirmação com app_user sem pessoa vinculada → 403 (SEC-DEC-04).
    reu = make_reuniao(reuniao_id=_REU, data=dt.date(2026, 7, 8))
    session = MeetingSession(
        app_user=make_app_user(),
        roles=["membro"],
        reunioes=[reu],
        actor_pessoa_id=None,
    )
    resp = _wire(app, session=session).post(
        f"/cell-reunioes/{_REU}/presenca", headers=_AUTH, json={}
    )
    assert resp.status_code == 403
    assert session.presencas == []


def test_presenca_403_sem_vinculo_ativo_na_celula_da_reuniao(app) -> None:
    # Pessoa ativa em OUTRA célula não vale para a célula da reunião (E11).
    reu = make_reuniao(reuniao_id=_REU, celula_id=_CELL, data=dt.date(2026, 7, 8))
    session = MeetingSession(
        app_user=make_app_user(),
        roles=["pastor"],
        cells=[make_cell()],
        reunioes=[reu],
        pessoas=[make_pessoa(pessoa_id=_TARGET)],
        membros=[make_member(pessoa_id=_TARGET, celula_id=_OTHER_CELL, ativo=True)],
        actor_pessoa_id=_LP,
    )
    resp = _wire(app, session=session).post(
        f"/cell-reunioes/{_REU}/presenca", headers=_AUTH, json={"pessoaId": _TARGET}
    )
    assert resp.status_code == 403
    assert session.presencas == []


def test_presenca_404_reuniao_outro_tenant(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, igreja_id=_OTHER, data=dt.date(2026, 7, 8))
    session = MeetingSession(
        app_user=make_app_user(),
        roles=["pastor"],
        reunioes=[reu],
        actor_pessoa_id=_LP,
    )
    resp = _wire(app, session=session).post(
        f"/cell-reunioes/{_REU}/presenca", headers=_AUTH, json={}
    )
    assert resp.status_code == 404
    assert session.presencas == []


def test_presenca_422_pessoa_outra_igreja(app) -> None:
    # pessoaId de outra igreja (ausente do tenant via RLS) → 422.
    reu = make_reuniao(reuniao_id=_REU, data=dt.date(2026, 7, 8))
    session = MeetingSession(
        app_user=make_app_user(),
        roles=["pastor"],
        cells=[make_cell()],
        reunioes=[reu],
        pessoas=[],  # _TARGET não existe neste tenant
        actor_pessoa_id=_LP,
    )
    resp = _wire(app, session=session).post(
        f"/cell-reunioes/{_REU}/presenca", headers=_AUTH, json={"pessoaId": _TARGET}
    )
    assert resp.status_code == 422
    assert session.presencas == []


def test_presenca_status_reuniao_nao_e_validado(app) -> None:
    # E12: presença permitida em qualquer status (inclusive cancelada).
    reu = make_reuniao(
        reuniao_id=_REU, data=dt.date(2026, 7, 8), status="cancelada"
    )
    session = MeetingSession(
        app_user=make_app_user(),
        roles=["membro"],
        reunioes=[reu],
        membros=[make_member(pessoa_id=_TARGET, celula_id=_CELL, ativo=True)],
        actor_pessoa_id=_TARGET,
    )
    resp = _wire(app, session=session).post(
        f"/cell-reunioes/{_REU}/presenca", headers=_AUTH, json={}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["origem"] == "auto"


def test_presenca_requires_auth(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=dt.date(2026, 7, 8))
    session = MeetingSession(
        app_user=make_app_user(), roles=["pastor"], reunioes=[reu]
    )
    resp = _wire(app, session=session).post(
        f"/cell-reunioes/{_REU}/presenca", json={}
    )
    assert resp.status_code == 401


# ===========================================================================
# US-09..US-10 — POST /cell-reunioes/{id}/expectativas-visitantes (nominal, 201)
# ===========================================================================
_EXPECT_PATH = f"/cell-reunioes/{_REU}/expectativas-visitantes"


def _expectativa_session(*, actor_pessoa_id=_TARGET, membros=None, reunioes=None):
    reu = make_reuniao(reuniao_id=_REU, celula_id=_CELL, data=dt.date(2026, 7, 8))
    return MeetingSession(
        app_user=make_app_user(),
        roles=["membro"],
        reunioes=reunioes if reunioes is not None else [reu],
        membros=membros
        if membros is not None
        else [make_member(pessoa_id=_TARGET, celula_id=_CELL, ativo=True)],
        actor_pessoa_id=actor_pessoa_id,
    )


def test_expectativa_created_201(app) -> None:
    # Criação válida da própria pessoa → 201 CREATED (nunca 200).
    session = _expectativa_session()
    resp = _wire(app, session=session).post(
        _EXPECT_PATH,
        headers=_AUTH,
        json={"nomeVisitante": "  Maria da Silva  ", "observacaoOracao": "Cura"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["nomeVisitante"] == "Maria da Silva"  # trim aplicado
    assert body["observacaoOracao"] == "Cura"
    assert body["pessoaId"] == _TARGET
    assert body["reuniaoId"] == _REU
    assert body["id"]
    assert session.committed is True
    assert len(session.expectativas) == 1


def test_expectativa_sem_observacao_retorna_null(app) -> None:
    session = _expectativa_session()
    resp = _wire(app, session=session).post(
        _EXPECT_PATH, headers=_AUTH, json={"nomeVisitante": "João"}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["observacaoOracao"] is None


def test_expectativa_multiplas_do_mesmo_membro_todas_201(app) -> None:
    # SEM UNIQUE: N registros do mesmo membro/reunião, todos 201.
    session = _expectativa_session()
    client = _wire(app, session=session)
    first = client.post(
        _EXPECT_PATH, headers=_AUTH, json={"nomeVisitante": "Visitante A"}
    )
    second = client.post(
        _EXPECT_PATH, headers=_AUTH, json={"nomeVisitante": "Visitante B"}
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] != second.json()["id"]
    assert len(session.expectativas) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {},  # nomeVisitante ausente
        {"nomeVisitante": ""},  # vazio
        {"nomeVisitante": "   "},  # só espaços após trim
        {"nomeVisitante": "x" * 201},  # > 200 chars
        {"nomeVisitante": "Ana", "observacaoOracao": "y" * 501},  # obs > 500
    ],
)
def test_expectativa_422_borda_e_nada_persistido(app, payload) -> None:
    session = _expectativa_session()
    resp = _wire(app, session=session).post(
        _EXPECT_PATH, headers=_AUTH, json=payload
    )
    assert resp.status_code == 422, resp.text
    assert session.expectativas == []  # nada persistido
    assert session.committed is False


def test_expectativa_403_app_user_sem_pessoa(app) -> None:
    session = _expectativa_session(actor_pessoa_id=None)
    resp = _wire(app, session=session).post(
        _EXPECT_PATH, headers=_AUTH, json={"nomeVisitante": "Maria"}
    )
    assert resp.status_code == 403
    assert session.expectativas == []


def test_expectativa_403_sem_vinculo_ativo_na_celula_da_reuniao(app) -> None:
    # Pessoa ativa em OUTRA célula não vale para a célula da reunião (E11).
    session = _expectativa_session(
        membros=[make_member(pessoa_id=_TARGET, celula_id=_OTHER_CELL, ativo=True)]
    )
    resp = _wire(app, session=session).post(
        _EXPECT_PATH, headers=_AUTH, json={"nomeVisitante": "Maria"}
    )
    assert resp.status_code == 403
    assert session.expectativas == []


def test_expectativa_403_vinculo_inativo(app) -> None:
    session = _expectativa_session(
        membros=[make_member(pessoa_id=_TARGET, celula_id=_CELL, ativo=False)]
    )
    resp = _wire(app, session=session).post(
        _EXPECT_PATH, headers=_AUTH, json={"nomeVisitante": "Maria"}
    )
    assert resp.status_code == 403
    assert session.expectativas == []


def test_expectativa_404_reuniao_outro_tenant(app) -> None:
    foreign = make_reuniao(
        reuniao_id=_REU, igreja_id=_OTHER, celula_id=_CELL, data=dt.date(2026, 7, 8)
    )
    session = _expectativa_session(reunioes=[foreign])
    resp = _wire(app, session=session).post(
        _EXPECT_PATH, headers=_AUTH, json={"nomeVisitante": "Maria"}
    )
    assert resp.status_code == 404
    assert session.expectativas == []


def test_expectativa_nao_e_por_terceiro_ignora_pessoaid(app) -> None:
    # No PR2 é SEMPRE da própria pessoa; um pessoaId extra no corpo é ignorado.
    session = _expectativa_session(actor_pessoa_id=_TARGET)
    resp = _wire(app, session=session).post(
        _EXPECT_PATH,
        headers=_AUTH,
        json={"nomeVisitante": "Maria", "pessoaId": _OUTSIDER},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["pessoaId"] == _TARGET  # a própria, não _OUTSIDER


def test_expectativa_requires_auth(app) -> None:
    session = _expectativa_session()
    resp = _wire(app, session=session).post(
        _EXPECT_PATH, json={"nomeVisitante": "Maria"}
    )
    assert resp.status_code == 401
