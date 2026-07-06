"""Testes da visão Discípulo (Células PR3) — deps de autorização + endpoints.

Cobre:
  - Dependências de autorização em ``app/deps.py``:
      * ``require_central`` — 403 para papel não-Central; passa pastor/admin;
      * ``get_current_cell_for_leader`` — ownership derivado de ``celulas.lider_id``
        ligado à Pessoa do app_user (E9/6.6); 404 (sem vazar existência) para outra
        célula/tenant, id malformado, célula sem líder ou liderada por outro.
  - Endpoints do Discípulo (projeção MINIMIZADA server-side, RF-05/RF-30):
      * GET    /cells/me/next-meeting
      * GET    /cells/me/notices
      * GET    /cells/me/history
      * POST   /cell-meetings/{id}/attendance/confirm
      * DELETE /cell-meetings/{id}/attendance/confirm
      * POST   /cell-meetings/{id}/visitor-expectations

Segue o estilo fake-session de ``test_cell_meetings.py`` (sem Postgres real): o
fake espelha os predicados WHERE, o filtro ``ativo`` e o ORDER BY do router. As
datas usam extremos (ano 2000 = sempre passada; 2999 = sempre futura) para que
``meeting_has_passed`` (relógio real, fuso America/Sao_Paulo) seja determinista
independentemente de quando os testes rodam.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.sql import operators

from app.db.models import (
    AppUser,
    Celula,
    CelulaAviso,
    CelulaExpectativaVisitante,
    CelulaMembro,
    CelulaPresenca,
    CelulaReuniao,
)
from app.db.session import get_db
from app.deps import (
    CurrentUser,
    get_current_cell_for_leader,
    require_central,
)
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}

_APPUSER = "00000000-0000-0000-0000-0000000000a1"  # id de make_app_user()
_TENANT = "00000000-0000-0000-0000-000000000001"
_OTHER = "00000000-0000-0000-0000-000000000002"
_CELL = "00000000-0000-0000-0000-0000000000e1"
_OTHER_CELL = "00000000-0000-0000-0000-0000000000e2"
_LP = "00000000-0000-0000-0000-0000000000b1"  # pessoa do líder
_OUTSIDER = "00000000-0000-0000-0000-0000000000c9"  # pessoa que não lidera
_TARGET = "00000000-0000-0000-0000-0000000000d1"  # pessoa do discípulo
_REU = "00000000-0000-0000-0000-0000000000f1"  # reunião

_PAST = dt.date(2000, 1, 1)  # sempre no passado
_FUTURE = dt.date(2999, 12, 31)  # sempre no futuro


# ===========================================================================
# Fake session (espelha WHERE + filtro ativo + ORDER BY do router Discípulo)
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


class DiscipuloSession:
    def __init__(
        self,
        *,
        app_user,
        roles,
        actor_pessoa_id=None,
        cells=None,
        reunioes=None,
        membros=None,
        presencas=None,
        expectativas=None,
        avisos=None,
    ) -> None:
        self.app_user = app_user
        self.roles = roles
        self.actor_pessoa_id = actor_pessoa_id
        self.cells = cells or []
        self.reunioes = reunioes or []
        self.membros = membros or []
        self.presencas = presencas or []
        self.expectativas = expectativas or []
        self.avisos = avisos or []
        self.added: list = []
        self.deleted: list = []
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
    def _order_specs(statement) -> list[tuple[str, bool]]:
        specs: list[tuple[str, bool]] = []
        for clause in getattr(statement, "_order_by_clauses", ()) or ():
            descending = getattr(clause, "modifier", None) is operators.desc_op
            element = getattr(clause, "element", clause)
            key = getattr(element, "key", None)
            if key is None:
                inner = getattr(element, "element", None)
                key = getattr(inner, "key", None)
            if key:
                specs.append((key, descending))
        return specs

    @staticmethod
    def _apply_order(rows, specs):
        rows = list(rows)
        for key, descending in reversed(specs):
            rows.sort(key=lambda r, k=key: getattr(r, k), reverse=descending)
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
            rows = self._apply_order(rows, self._order_specs(statement))
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is CelulaMembro:
            rows = self._filter(self.membros, statement)
            if self._wants_active(statement):
                rows = [r for r in rows if getattr(r, "ativo", True) is True]
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is CelulaPresenca:
            rows = self._filter(self.presencas, statement)
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is CelulaExpectativaVisitante:
            rows = self._filter(self.expectativas, statement)
            rows = self._apply_order(rows, self._order_specs(statement))
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is CelulaAviso:
            rows = self._filter(self.avisos, statement)
            if self._wants_active(statement):
                rows = [r for r in rows if getattr(r, "ativo", True) is True]
            rows = self._apply_order(rows, self._order_specs(statement))
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        # set_config text / UserRole.papel projection.
        return _R(scalars=self.roles)

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        if isinstance(obj, CelulaPresenca):
            self.presencas.append(obj)
        if isinstance(obj, CelulaExpectativaVisitante):
            self.expectativas.append(obj)

    def delete(self, obj) -> None:
        self.deleted.append(obj)
        if obj in self.presencas:
            self.presencas.remove(obj)

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


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def make_cell(
    *,
    cell_id: str = _CELL,
    igreja_id: str = _TENANT,
    lider_id: str | None = None,
    endereco: str | None = "Rua das Flores, 100",
):
    return SimpleNamespace(
        id=cell_id,
        igreja_id=igreja_id,
        nome="Célula Central",
        lider_id=lider_id,
        endereco=endereco,
    )


def make_member(
    *,
    member_id: str = "00000000-0000-0000-0000-0000000000a5",
    igreja_id: str = _TENANT,
    celula_id: str = _CELL,
    pessoa_id: str = _TARGET,
    ativo: bool = True,
):
    return SimpleNamespace(
        id=member_id,
        igreja_id=igreja_id,
        celula_id=celula_id,
        pessoa_id=pessoa_id,
        ativo=ativo,
    )


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


def make_presenca(
    *,
    presenca_id: str = "00000000-0000-0000-0000-0000000000a6",
    igreja_id: str = _TENANT,
    reuniao_id: str = _REU,
    pessoa_id: str = _TARGET,
    estado: str = "confirmada",
    origem: str | None = "auto",
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


def make_expectativa(
    *,
    expectativa_id: str,
    igreja_id: str = _TENANT,
    reuniao_id: str = _REU,
    pessoa_id: str = _TARGET,
    nome_visitante: str = "Visitante",
    observacao_oracao: str | None = None,
    created_at: dt.datetime | None = None,
):
    return SimpleNamespace(
        id=expectativa_id,
        igreja_id=igreja_id,
        reuniao_id=reuniao_id,
        pessoa_id=pessoa_id,
        nome_visitante=nome_visitante,
        observacao_oracao=observacao_oracao,
        created_at=created_at or dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc),
    )


def make_aviso(
    *,
    aviso_id: str,
    igreja_id: str = _TENANT,
    celula_id: str | None = None,
    origem: str = "central",
    escopo: str = "igreja",
    titulo: str = "Aviso",
    conteudo: str = "Conteúdo",
    ativo: bool = True,
    publicado_em: dt.datetime | None = None,
):
    return SimpleNamespace(
        id=aviso_id,
        igreja_id=igreja_id,
        celula_id=celula_id,
        origem=origem,
        escopo=escopo,
        titulo=titulo,
        conteudo=conteudo,
        ativo=ativo,
        publicado_em=publicado_em
        or dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    )


def make_current_user(roles: list[str]) -> CurrentUser:
    return CurrentUser(
        app_user_id=_APPUSER,
        clerk_user_id="clerk_user_1",
        igreja_id=_TENANT,
        email="disc@igrejapiloto.com",
        nome="Discípulo",
        roles=frozenset(roles),
    )


def _wire(app, *, session, clerk=None):
    from fastapi.testclient import TestClient

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk or FakeClerk()
    return TestClient(app)


def _discipulo_session(**kwargs) -> DiscipuloSession:
    """Sessão com o discípulo _TARGET ativo na célula _CELL por padrão."""
    kwargs.setdefault("app_user", make_app_user())
    kwargs.setdefault("roles", ["membro"])
    kwargs.setdefault("actor_pessoa_id", _TARGET)
    kwargs.setdefault(
        "membros",
        [make_member(pessoa_id=_TARGET, celula_id=_CELL, ativo=True)],
    )
    kwargs.setdefault("cells", [make_cell()])
    return DiscipuloSession(**kwargs)


# ===========================================================================
# deps — require_central
# ===========================================================================
def test_require_central_allows_pastor() -> None:
    cu = make_current_user(["pastor"])
    assert require_central(current_user=cu) is cu


def test_require_central_allows_admin_implicit() -> None:
    cu = make_current_user(["admin"])
    assert require_central(current_user=cu) is cu


def test_require_central_forbids_membro() -> None:
    cu = make_current_user(["membro"])
    with pytest.raises(HTTPException) as exc:
        require_central(current_user=cu)
    assert exc.value.status_code == 403


# ===========================================================================
# deps — get_current_cell_for_leader (ownership por celulas.lider_id)
# ===========================================================================
def test_leader_ownership_returns_cell() -> None:
    session = DiscipuloSession(
        app_user=make_app_user(),
        roles=["membro"],
        actor_pessoa_id=_LP,
        cells=[make_cell(lider_id=_LP)],
    )
    cell = get_current_cell_for_leader(session, make_current_user(["membro"]), _CELL)
    assert str(cell.id) == _CELL


def test_leader_ownership_404_for_other_leader() -> None:
    # Célula liderada por _LP, mas o ator é _OUTSIDER → 404 (não vaza existência).
    session = DiscipuloSession(
        app_user=make_app_user(),
        roles=["membro"],
        actor_pessoa_id=_OUTSIDER,
        cells=[make_cell(lider_id=_LP)],
    )
    with pytest.raises(HTTPException) as exc:
        get_current_cell_for_leader(session, make_current_user(["membro"]), _CELL)
    assert exc.value.status_code == 404


def test_leader_ownership_404_for_other_tenant() -> None:
    session = DiscipuloSession(
        app_user=make_app_user(),
        roles=["membro"],
        actor_pessoa_id=_LP,
        cells=[make_cell(lider_id=_LP, igreja_id=_OTHER)],
    )
    with pytest.raises(HTTPException) as exc:
        get_current_cell_for_leader(session, make_current_user(["membro"]), _CELL)
    assert exc.value.status_code == 404


def test_leader_ownership_404_for_malformed_id() -> None:
    session = DiscipuloSession(
        app_user=make_app_user(), roles=["membro"], actor_pessoa_id=_LP
    )
    with pytest.raises(HTTPException) as exc:
        get_current_cell_for_leader(session, make_current_user(["membro"]), "nope")
    assert exc.value.status_code == 404


def test_leader_ownership_404_when_cell_has_no_leader() -> None:
    session = DiscipuloSession(
        app_user=make_app_user(),
        roles=["membro"],
        actor_pessoa_id=_LP,
        cells=[make_cell(lider_id=None)],
    )
    with pytest.raises(HTTPException) as exc:
        get_current_cell_for_leader(session, make_current_user(["membro"]), _CELL)
    assert exc.value.status_code == 404


def test_leader_ownership_404_when_actor_has_no_pessoa() -> None:
    session = DiscipuloSession(
        app_user=make_app_user(),
        roles=["membro"],
        actor_pessoa_id=None,
        cells=[make_cell(lider_id=_LP)],
    )
    with pytest.raises(HTTPException) as exc:
        get_current_cell_for_leader(session, make_current_user(["membro"]), _CELL)
    assert exc.value.status_code == 404


# ===========================================================================
# GET /cells/me/next-meeting
# ===========================================================================
def test_next_meeting_returns_soonest_future(app) -> None:
    past = make_reuniao(reuniao_id="r-past", data=_PAST, hora="20:00")
    soon = make_reuniao(
        reuniao_id="r-soon", data=dt.date(2998, 1, 1), hora="20:00", tema="Fé"
    )
    late = make_reuniao(reuniao_id="r-late", data=_FUTURE, hora="20:00")
    session = _discipulo_session(reunioes=[past, soon, late])
    resp = _wire(app, session=session).get("/cells/me/next-meeting", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    meeting = resp.json()["meeting"]
    assert meeting is not None
    assert meeting["id"] == "r-soon"
    assert meeting["celula_id"] == _CELL
    assert meeting["tema"] == "Fé"
    assert meeting["local"] == "Rua das Flores, 100"  # deriva do endereço da célula
    dt.date.fromisoformat(meeting["data"])


def test_next_meeting_null_when_only_past(app) -> None:
    session = _discipulo_session(
        reunioes=[make_reuniao(reuniao_id="r-past", data=_PAST, hora="20:00")]
    )
    resp = _wire(app, session=session).get("/cells/me/next-meeting", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    assert resp.json()["meeting"] is None


def test_next_meeting_null_without_cell(app) -> None:
    session = _discipulo_session(membros=[])  # discípulo sem célula ativa
    resp = _wire(app, session=session).get("/cells/me/next-meeting", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    assert resp.json()["meeting"] is None


def test_next_meeting_null_without_pessoa(app) -> None:
    session = _discipulo_session(actor_pessoa_id=None)
    resp = _wire(app, session=session).get("/cells/me/next-meeting", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    assert resp.json()["meeting"] is None


def test_next_meeting_requires_auth(app) -> None:
    session = _discipulo_session()
    resp = _wire(app, session=session).get("/cells/me/next-meeting")
    assert resp.status_code == 401


# ===========================================================================
# GET /cells/me/notices
# ===========================================================================
def test_notices_returns_igreja_and_own_cell_only(app) -> None:
    igreja = make_aviso(aviso_id="n-igreja", escopo="igreja", celula_id=None)
    minha = make_aviso(aviso_id="n-minha", escopo="celula", celula_id=_CELL)
    outra = make_aviso(aviso_id="n-outra", escopo="celula", celula_id=_OTHER_CELL)
    session = _discipulo_session(avisos=[igreja, minha, outra])
    resp = _wire(app, session=session).get("/cells/me/notices", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    ids = {n["id"] for n in resp.json()}
    assert ids == {"n-igreja", "n-minha"}  # nunca aviso de outra célula


def test_notices_excludes_inactive(app) -> None:
    ativo = make_aviso(aviso_id="n-ativo", escopo="igreja", ativo=True)
    inativo = make_aviso(aviso_id="n-inativo", escopo="igreja", ativo=False)
    session = _discipulo_session(avisos=[ativo, inativo])
    resp = _wire(app, session=session).get("/cells/me/notices", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    assert [n["id"] for n in resp.json()] == ["n-ativo"]


def test_notices_without_cell_sees_only_igreja(app) -> None:
    igreja = make_aviso(aviso_id="n-igreja", escopo="igreja")
    celula = make_aviso(aviso_id="n-celula", escopo="celula", celula_id=_CELL)
    session = _discipulo_session(membros=[], avisos=[igreja, celula])
    resp = _wire(app, session=session).get("/cells/me/notices", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    assert [n["id"] for n in resp.json()] == ["n-igreja"]


def test_notices_requires_auth(app) -> None:
    session = _discipulo_session()
    resp = _wire(app, session=session).get("/cells/me/notices")
    assert resp.status_code == 401


# ===========================================================================
# GET /cells/me/history
# ===========================================================================
def test_history_paginates_and_projects_minimally(app) -> None:
    r0 = make_reuniao(reuniao_id="h0", data=dt.date(2000, 1, 1), tema="A")
    r1 = make_reuniao(reuniao_id="h1", data=dt.date(2001, 1, 1), tema="B")
    r2 = make_reuniao(reuniao_id="h2", data=dt.date(2002, 1, 1), tema="C")
    # presença do próprio membro só em h2 (compareceu → participou).
    pres = make_presenca(reuniao_id="h2", estado="compareceu")
    session = _discipulo_session(reunioes=[r0, r1, r2], presencas=[pres])
    client = _wire(app, session=session)

    page1 = client.get(
        "/cells/me/history", params={"page": 1, "page_size": 2}, headers=_AUTH
    )
    assert page1.status_code == 200, page1.text
    body = page1.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 2
    # mais recentes primeiro (data DESC): h2, h1.
    assert [i["data"] for i in body["items"]] == ["2002-01-01", "2001-01-01"]
    # projeção mínima: só estes 4 campos, nunca decisões/oração/relatório/terceiros.
    assert set(body["items"][0]) == {
        "data",
        "tema",
        "minha_presenca",
        "meus_visitantes_indicados",
    }
    assert body["items"][0]["minha_presenca"] == "participou"  # E5 compareceu

    page2 = client.get(
        "/cells/me/history", params={"page": 2, "page_size": 2}, headers=_AUTH
    )
    assert page2.status_code == 200, page2.text
    body2 = page2.json()
    assert [i["data"] for i in body2["items"]] == ["2000-01-01"]
    assert body2["items"][0]["minha_presenca"] == "nao_confirmou"  # sem linha


def test_history_maps_presence_states_E5(app) -> None:
    reu = make_reuniao(reuniao_id="hx", data=_PAST)
    pres = make_presenca(reuniao_id="hx", estado="ausente")
    session = _discipulo_session(reunioes=[reu], presencas=[pres])
    resp = _wire(app, session=session).get("/cells/me/history", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"][0]["minha_presenca"] == "faltou"  # E5 ausente


def test_history_lists_only_own_visitors(app) -> None:
    reu = make_reuniao(reuniao_id="hv", data=_PAST)
    mine = make_expectativa(
        expectativa_id="ev-1", reuniao_id="hv", pessoa_id=_TARGET, nome_visitante="Ana"
    )
    others = make_expectativa(
        expectativa_id="ev-2",
        reuniao_id="hv",
        pessoa_id=_OUTSIDER,
        nome_visitante="Bruno",
    )
    session = _discipulo_session(reunioes=[reu], expectativas=[mine, others])
    resp = _wire(app, session=session).get("/cells/me/history", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    assert item["meus_visitantes_indicados"] == ["Ana"]  # nunca do terceiro


def test_history_excludes_future(app) -> None:
    session = _discipulo_session(
        reunioes=[make_reuniao(reuniao_id="hf", data=_FUTURE)]
    )
    resp = _wire(app, session=session).get("/cells/me/history", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 0
    assert resp.json()["items"] == []


def test_history_empty_without_cell(app) -> None:
    session = _discipulo_session(membros=[])
    resp = _wire(app, session=session).get("/cells/me/history", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 0


def test_history_page_size_out_of_range_422(app) -> None:
    session = _discipulo_session()
    resp = _wire(app, session=session).get(
        "/cells/me/history", params={"page_size": 101}, headers=_AUTH
    )
    assert resp.status_code == 422


def test_history_requires_auth(app) -> None:
    session = _discipulo_session()
    resp = _wire(app, session=session).get("/cells/me/history")
    assert resp.status_code == 401


# ===========================================================================
# POST /cell-meetings/{id}/attendance/confirm
# ===========================================================================
_CONFIRM_PATH = f"/cell-meetings/{_REU}/attendance/confirm"


def test_confirm_attendance_persists(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=_FUTURE)
    session = _discipulo_session(reunioes=[reu])
    resp = _wire(app, session=session).post(_CONFIRM_PATH, headers=_AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reuniao_id"] == _REU
    assert body["minha_presenca"] == "confirmou"
    assert session.committed is True
    assert len(session.presencas) == 1


def test_confirm_attendance_idempotent(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=_FUTURE)
    session = _discipulo_session(reunioes=[reu])
    client = _wire(app, session=session)
    first = client.post(_CONFIRM_PATH, headers=_AUTH)
    second = client.post(_CONFIRM_PATH, headers=_AUTH)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert len(session.presencas) == 1  # não duplica


def test_confirm_attendance_404_unknown_meeting(app) -> None:
    session = _discipulo_session(reunioes=[])
    resp = _wire(app, session=session).post(_CONFIRM_PATH, headers=_AUTH)
    assert resp.status_code == 404
    assert session.presencas == []


def test_confirm_attendance_409_past_meeting(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=_PAST)
    session = _discipulo_session(reunioes=[reu])
    resp = _wire(app, session=session).post(_CONFIRM_PATH, headers=_AUTH)
    assert resp.status_code == 409
    assert session.presencas == []


def test_confirm_attendance_403_without_pessoa(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=_FUTURE)
    session = _discipulo_session(reunioes=[reu], actor_pessoa_id=None)
    resp = _wire(app, session=session).post(_CONFIRM_PATH, headers=_AUTH)
    assert resp.status_code == 403
    assert session.presencas == []


def test_confirm_attendance_403_without_active_membership(app) -> None:
    # Pessoa ativa em OUTRA célula não vale para a célula da reunião (E11).
    reu = make_reuniao(reuniao_id=_REU, celula_id=_CELL, data=_FUTURE)
    session = _discipulo_session(
        reunioes=[reu],
        membros=[make_member(pessoa_id=_TARGET, celula_id=_OTHER_CELL, ativo=True)],
    )
    resp = _wire(app, session=session).post(_CONFIRM_PATH, headers=_AUTH)
    assert resp.status_code == 403
    assert session.presencas == []


def test_confirm_attendance_404_other_tenant(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, igreja_id=_OTHER, data=_FUTURE)
    session = _discipulo_session(reunioes=[reu])
    resp = _wire(app, session=session).post(_CONFIRM_PATH, headers=_AUTH)
    assert resp.status_code == 404


def test_confirm_attendance_requires_auth(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=_FUTURE)
    session = _discipulo_session(reunioes=[reu])
    resp = _wire(app, session=session).post(_CONFIRM_PATH)
    assert resp.status_code == 401


# ===========================================================================
# DELETE /cell-meetings/{id}/attendance/confirm
# ===========================================================================
def test_revert_attendance_removes_row(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=_FUTURE)
    pres = make_presenca(reuniao_id=_REU, estado="confirmada")
    session = _discipulo_session(reunioes=[reu], presencas=[pres])
    resp = _wire(app, session=session).delete(_CONFIRM_PATH, headers=_AUTH)
    assert resp.status_code == 200, resp.text
    assert resp.json()["minha_presenca"] == "nao_confirmou"
    assert session.presencas == []


def test_revert_attendance_idempotent_without_row(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=_FUTURE)
    session = _discipulo_session(reunioes=[reu], presencas=[])
    resp = _wire(app, session=session).delete(_CONFIRM_PATH, headers=_AUTH)
    assert resp.status_code == 200, resp.text
    assert resp.json()["minha_presenca"] == "nao_confirmou"


def test_revert_attendance_409_past_meeting(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=_PAST)
    pres = make_presenca(reuniao_id=_REU, estado="confirmada")
    session = _discipulo_session(reunioes=[reu], presencas=[pres])
    resp = _wire(app, session=session).delete(_CONFIRM_PATH, headers=_AUTH)
    assert resp.status_code == 409
    assert len(session.presencas) == 1  # não removeu


def test_revert_attendance_404_unknown_meeting(app) -> None:
    session = _discipulo_session(reunioes=[])
    resp = _wire(app, session=session).delete(_CONFIRM_PATH, headers=_AUTH)
    assert resp.status_code == 404


def test_revert_attendance_requires_auth(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=_FUTURE)
    session = _discipulo_session(reunioes=[reu])
    resp = _wire(app, session=session).delete(_CONFIRM_PATH)
    assert resp.status_code == 401


# ===========================================================================
# POST /cell-meetings/{id}/visitor-expectations
# ===========================================================================
_VISITOR_PATH = f"/cell-meetings/{_REU}/visitor-expectations"


def test_visitor_expectation_created_201(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=_FUTURE)
    session = _discipulo_session(reunioes=[reu])
    resp = _wire(app, session=session).post(
        _VISITOR_PATH,
        headers=_AUTH,
        json={"nomeVisitante": "  Maria da Silva  ", "observacaoOracao": "Cura"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["nome_visitante"] == "Maria da Silva"  # trim
    assert body["observacao_oracao"] == "Cura"
    assert body["reuniao_id"] == _REU
    assert body["id"]
    assert session.committed is True
    assert len(session.expectativas) == 1


def test_visitor_expectation_404_unknown_meeting(app) -> None:
    session = _discipulo_session(reunioes=[])
    resp = _wire(app, session=session).post(
        _VISITOR_PATH, headers=_AUTH, json={"nomeVisitante": "Maria"}
    )
    assert resp.status_code == 404
    assert session.expectativas == []


@pytest.mark.parametrize(
    "payload",
    [
        {},  # nome ausente
        {"nomeVisitante": ""},  # vazio
        {"nomeVisitante": "   "},  # só espaços
        {"nomeVisitante": "x" * 201},  # > 200 chars
    ],
)
def test_visitor_expectation_422_invalid_name(app, payload) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=_FUTURE)
    session = _discipulo_session(reunioes=[reu])
    resp = _wire(app, session=session).post(
        _VISITOR_PATH, headers=_AUTH, json=payload
    )
    assert resp.status_code == 422
    assert session.expectativas == []


def test_visitor_expectation_403_without_active_membership(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, celula_id=_CELL, data=_FUTURE)
    session = _discipulo_session(
        reunioes=[reu],
        membros=[make_member(pessoa_id=_TARGET, celula_id=_OTHER_CELL, ativo=True)],
    )
    resp = _wire(app, session=session).post(
        _VISITOR_PATH, headers=_AUTH, json={"nomeVisitante": "Maria"}
    )
    assert resp.status_code == 403
    assert session.expectativas == []


def test_visitor_expectation_403_without_pessoa(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=_FUTURE)
    session = _discipulo_session(reunioes=[reu], actor_pessoa_id=None)
    resp = _wire(app, session=session).post(
        _VISITOR_PATH, headers=_AUTH, json={"nomeVisitante": "Maria"}
    )
    assert resp.status_code == 403
    assert session.expectativas == []


def test_visitor_expectation_requires_auth(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=_FUTURE)
    session = _discipulo_session(reunioes=[reu])
    resp = _wire(app, session=session).post(
        _VISITOR_PATH, json={"nomeVisitante": "Maria"}
    )
    assert resp.status_code == 401
