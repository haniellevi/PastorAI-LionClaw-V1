"""Testes da visão Líder (Minha Célula) + ciclo do relatório (Células PR3-PR9).

Cobre os endpoints do domínio Líder de ``app/routers/cell_meetings.py`` (contrato
snake_case), agrupados em:

  Grupo 1 — reunião/presença/visitantes/registros/membros:
    * POST   /cell-meetings                          (planejar reunião pontual)
    * PUT    /cell-meetings/{id}                      (editar data/hora/tema; RF-14)
    * PUT    /cell-meetings/{id}/attendance          (presença real por pessoa)
    * POST   /cell-meetings/{id}/visitors            (visitante presente)
    * GET    /cell-meetings/{id}/visitor-expectations
    * POST   /cell-meetings/{id}/records             (registro pastoral)
    * GET    /cell-meetings/{id}/records             (líder/Central; oculto do discípulo)
    * GET    /cells/{cell_id}/members                (discípulos da própria célula)

  Grupo 2 — ciclo do relatório (E10/E11):
    * PUT    /cell-meetings/{id}/report              (rascunho de oferta/observações)
    * POST   /cell-meetings/{id}/report/submit       (enviar → 'enviado')
    * GET    /cell-meetings/{id}/report              (consolidado)

Segue o estilo fake-session de ``test_cell_discipulo.py`` (sem Postgres real): o
fake espelha os predicados WHERE, o filtro ``ativo`` e o ORDER BY do router, e é
estendido para as entidades ``CelulaVisitante``, ``CelulaReuniaoRegistro`` e
``Pessoa`` (usadas pelas escritas/consolidação do Líder). Ownership de célula
deriva de ``celulas.lider_id`` ligado à Pessoa do app_user (E9/6.6), nunca do
payload.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.sql import operators

from app.db.models import (
    AppUser,
    Celula,
    CelulaExpectativaVisitante,
    CelulaMembro,
    CelulaPresenca,
    CelulaReuniao,
    CelulaReuniaoRegistro,
    CelulaVisitante,
    Pessoa,
)
from app.db.session import get_db
from app.deps import CurrentUser
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}

_APPUSER = "00000000-0000-0000-0000-0000000000a1"  # id de make_app_user()
_TENANT = "00000000-0000-0000-0000-000000000001"
_OTHER = "00000000-0000-0000-0000-000000000002"
_CELL = "00000000-0000-0000-0000-0000000000e1"
_OTHER_CELL = "00000000-0000-0000-0000-0000000000e2"
_LEADER = "00000000-0000-0000-0000-0000000000b1"  # pessoa do líder (app_user atual)
_MEMBER = "00000000-0000-0000-0000-0000000000d1"  # pessoa do discípulo/membro
_OUTSIDER = "00000000-0000-0000-0000-0000000000c9"  # pessoa fora da célula
_REU = "00000000-0000-0000-0000-0000000000f1"  # reunião
_EXP = "00000000-0000-0000-0000-0000000000f7"  # expectativa de visitante


# ===========================================================================
# Fake session (espelha WHERE + filtro ativo + ORDER BY do router Líder)
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


class LiderSession:
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
        visitantes=None,
        registros=None,
        pessoas=None,
    ) -> None:
        self.app_user = app_user
        self.roles = roles
        self.actor_pessoa_id = actor_pessoa_id
        self.cells = cells or []
        self.reunioes = reunioes or []
        self.membros = membros or []
        self.presencas = presencas or []
        self.expectativas = expectativas or []
        self.visitantes = visitantes or []
        self.registros = registros or []
        self.pessoas = pessoas or []
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
        if ent is Pessoa:
            # select(Pessoa.id, Pessoa.nome) -> linhas (id, nome); senão scalar id.
            if len(descs) >= 2:
                return _R(rows=[(p.id, p.nome) for p in self.pessoas])
            rows = self._filter(self.pessoas, statement)
            return _R(scalar=(rows[0].id if rows else None))
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
            rows = self._apply_order(rows, self._order_specs(statement))
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is CelulaPresenca:
            rows = self._filter(self.presencas, statement)
            rows = self._apply_order(rows, self._order_specs(statement))
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is CelulaExpectativaVisitante:
            rows = self._filter(self.expectativas, statement)
            rows = self._apply_order(rows, self._order_specs(statement))
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is CelulaVisitante:
            rows = self._filter(self.visitantes, statement)
            rows = self._apply_order(rows, self._order_specs(statement))
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is CelulaReuniaoRegistro:
            rows = self._filter(self.registros, statement)
            rows = self._apply_order(rows, self._order_specs(statement))
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        # set_config text / UserRole.papel projection.
        return _R(scalars=self.roles)

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        if isinstance(obj, CelulaReuniao):
            self.reunioes.append(obj)
        elif isinstance(obj, CelulaPresenca):
            self.presencas.append(obj)
        elif isinstance(obj, CelulaExpectativaVisitante):
            self.expectativas.append(obj)
        elif isinstance(obj, CelulaVisitante):
            self.visitantes.append(obj)
        elif isinstance(obj, CelulaReuniaoRegistro):
            self.registros.append(obj)

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
    lider_id: str | None = _LEADER,
):
    return SimpleNamespace(
        id=cell_id,
        igreja_id=igreja_id,
        nome="Célula Central",
        lider_id=lider_id,
        anfitriao_id=None,
        auxiliar_id=None,
        endereco="Rua das Flores, 100",
        dia_reuniao="quinta",
        horario="20:00",
    )


def make_member(
    *,
    member_id: str | None = None,
    igreja_id: str = _TENANT,
    celula_id: str = _CELL,
    pessoa_id: str = _MEMBER,
    ativo: bool = True,
    created_at: dt.datetime | None = None,
):
    return SimpleNamespace(
        id=member_id or str(uuid.uuid4()),
        igreja_id=igreja_id,
        celula_id=celula_id,
        pessoa_id=pessoa_id,
        ativo=ativo,
        created_at=created_at or dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc),
    )


def make_pessoa(pessoa_id: str, nome: str):
    return SimpleNamespace(id=pessoa_id, nome=nome, lider_id=None)


def make_reuniao(
    *,
    reuniao_id: str = _REU,
    igreja_id: str = _TENANT,
    celula_id: str = _CELL,
    data: dt.date | None = None,
    hora: str | None = "20:00",
    tema: str | None = None,
    status: str = "planejada",
    relatorio_status: str = "pendente",
    relatorio_enviado_em: dt.datetime | None = None,
    relatorio_enviado_por: str | None = None,
    oferta_valor: float | None = None,
    observacoes: str | None = None,
    relatorio_snapshot: dict | None = None,
):
    return SimpleNamespace(
        id=reuniao_id,
        igreja_id=igreja_id,
        celula_id=celula_id,
        data=data or dt.date(2026, 3, 5),
        hora=hora,
        tema=tema,
        status=status,
        relatorio_status=relatorio_status,
        relatorio_enviado_em=relatorio_enviado_em,
        relatorio_enviado_por=relatorio_enviado_por,
        oferta_valor=oferta_valor,
        observacoes=observacoes,
        relatorio_snapshot=relatorio_snapshot,
        updated_at=None,
    )


def make_presenca(
    *,
    presenca_id: str | None = None,
    igreja_id: str = _TENANT,
    reuniao_id: str = _REU,
    pessoa_id: str = _MEMBER,
    estado: str = "compareceu",
    origem: str | None = "lider",
    created_at: dt.datetime | None = None,
):
    return SimpleNamespace(
        id=presenca_id or str(uuid.uuid4()),
        igreja_id=igreja_id,
        reuniao_id=reuniao_id,
        pessoa_id=pessoa_id,
        estado=estado,
        origem=origem,
        created_at=created_at or dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc),
        updated_at=None,
    )


def make_expectativa(
    *,
    expectativa_id: str = _EXP,
    igreja_id: str = _TENANT,
    reuniao_id: str = _REU,
    pessoa_id: str = _MEMBER,
    nome_visitante: str = "Visitante Esperado",
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


def make_visitante(
    *,
    visitante_id: str | None = None,
    igreja_id: str = _TENANT,
    reuniao_id: str = _REU,
    expectativa_id: str | None = None,
    nome_visitante: str = "Visitante Presente",
    observacao: str | None = None,
    created_at: dt.datetime | None = None,
):
    return SimpleNamespace(
        id=visitante_id or str(uuid.uuid4()),
        igreja_id=igreja_id,
        reuniao_id=reuniao_id,
        expectativa_id=expectativa_id,
        nome_visitante=nome_visitante,
        observacao=observacao,
        created_at=created_at or dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc),
    )


def make_registro(
    *,
    registro_id: str | None = None,
    igreja_id: str = _TENANT,
    reuniao_id: str = _REU,
    tipo: str = "observacao",
    conteudo: str = "Conteúdo do registro",
    pessoa_id: str | None = None,
    autor_id: str | None = _LEADER,
    created_at: dt.datetime | None = None,
):
    return SimpleNamespace(
        id=registro_id or str(uuid.uuid4()),
        igreja_id=igreja_id,
        reuniao_id=reuniao_id,
        tipo=tipo,
        conteudo=conteudo,
        pessoa_id=pessoa_id,
        autor_id=autor_id,
        created_at=created_at or dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc),
    )


def make_current_user(roles: list[str]) -> CurrentUser:
    return CurrentUser(
        app_user_id=_APPUSER,
        clerk_user_id="clerk_user_1",
        igreja_id=_TENANT,
        email="lider@igrejapiloto.com",
        nome="Líder",
        roles=frozenset(roles),
    )


def _wire(app, *, session, clerk=None):
    from fastapi.testclient import TestClient

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk or FakeClerk()
    return TestClient(app)


def _leader_session(**kwargs) -> LiderSession:
    """Sessão do líder _LEADER sobre a célula _CELL, com _MEMBER ativo."""
    kwargs.setdefault("app_user", make_app_user())
    kwargs.setdefault("roles", ["lider"])
    kwargs.setdefault("actor_pessoa_id", _LEADER)
    kwargs.setdefault("cells", [make_cell(lider_id=_LEADER)])
    kwargs.setdefault(
        "membros", [make_member(pessoa_id=_MEMBER, celula_id=_CELL, ativo=True)]
    )
    kwargs.setdefault(
        "pessoas",
        [
            make_pessoa(_LEADER, "Líder"),
            make_pessoa(_MEMBER, "Membro Fiel"),
            make_pessoa(_OUTSIDER, "De Fora"),
        ],
    )
    return LiderSession(**kwargs)


# ===========================================================================
# POST /cell-meetings — planejar reunião pontual
# ===========================================================================
def test_plan_meeting_creates_pending_201(app) -> None:
    session = _leader_session(reunioes=[])
    resp = _wire(app, session=session).post(
        "/cell-meetings",
        headers=_AUTH,
        json={
            "celula_id": _CELL,
            "data": "2026-03-12",
            "hora": "20:00",
            "tema": "Comunhão",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["celula_id"] == _CELL
    assert body["data"] == "2026-03-12"
    assert body["hora"] == "20:00"
    assert body["tema"] == "Comunhão"
    assert body["status"] == "planejada"
    assert body["relatorio_status"] == "pendente"  # nasce pendente
    assert session.committed is True
    assert len(session.reunioes) == 1


def test_plan_meeting_403_when_not_leader(app) -> None:
    # Célula existe no tenant mas é liderada por outra pessoa → 403.
    session = _leader_session(cells=[make_cell(lider_id=_OUTSIDER)], reunioes=[])
    resp = _wire(app, session=session).post(
        "/cell-meetings",
        headers=_AUTH,
        json={"celula_id": _CELL, "data": "2026-03-12", "hora": "20:00"},
    )
    assert resp.status_code == 403
    assert session.reunioes == []


def test_plan_meeting_404_other_tenant(app) -> None:
    session = _leader_session(
        cells=[make_cell(lider_id=_LEADER, igreja_id=_OTHER)], reunioes=[]
    )
    resp = _wire(app, session=session).post(
        "/cell-meetings",
        headers=_AUTH,
        json={"celula_id": _CELL, "data": "2026-03-12", "hora": "20:00"},
    )
    assert resp.status_code == 404
    assert session.reunioes == []


def test_plan_meeting_409_slot_conflict(app) -> None:
    existing = make_reuniao(
        reuniao_id="r-existing", data=dt.date(2026, 3, 12), hora="20:00"
    )
    session = _leader_session(reunioes=[existing])
    resp = _wire(app, session=session).post(
        "/cell-meetings",
        headers=_AUTH,
        json={"celula_id": _CELL, "data": "2026-03-12", "hora": "20:00"},
    )
    assert resp.status_code == 409
    assert len(session.reunioes) == 1  # não cria duplicata


@pytest.mark.parametrize(
    "payload",
    [
        {"celula_id": "not-a-uuid", "data": "2026-03-12"},
        {"celula_id": _CELL, "data": "2026-03-12", "hora": "25:00"},
        {"celula_id": _CELL, "data": "2026-03-12", "tema": "x" * 121},
        {"celula_id": _CELL, "data": "nope"},
    ],
)
def test_plan_meeting_422_invalid_payload(app, payload) -> None:
    session = _leader_session(reunioes=[])
    resp = _wire(app, session=session).post(
        "/cell-meetings", headers=_AUTH, json=payload
    )
    assert resp.status_code == 422
    assert session.reunioes == []


def test_plan_meeting_requires_auth(app) -> None:
    session = _leader_session(reunioes=[])
    resp = _wire(app, session=session).post(
        "/cell-meetings", json={"celula_id": _CELL, "data": "2026-03-12"}
    )
    assert resp.status_code == 401


# ===========================================================================
# PUT /cell-meetings/{id} — editar data/hora/tema (RF-14)
# ===========================================================================
def test_edit_meeting_updates_fields(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=dt.date(2026, 3, 5), hora="20:00")
    session = _leader_session(reunioes=[reu])
    resp = _wire(app, session=session).put(
        f"/cell-meetings/{_REU}",
        headers=_AUTH,
        json={"data": "2026-03-19", "hora": "19:30", "tema": "Novo Tema"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"] == "2026-03-19"
    assert body["hora"] == "19:30"
    assert body["tema"] == "Novo Tema"
    assert reu.data == dt.date(2026, 3, 19)


def test_edit_meeting_ignores_sensitive_fields_RF14(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, data=dt.date(2026, 3, 5), hora="20:00")
    cell = make_cell(lider_id=_LEADER)
    session = _leader_session(cells=[cell], reunioes=[reu])
    resp = _wire(app, session=session).put(
        f"/cell-meetings/{_REU}",
        headers=_AUTH,
        json={
            "data": "2026-03-19",
            "hora": "19:30",
            "tema": "Tema",
            # Campos sensíveis: devem ser ignorados (não aplicados).
            "anfitriao_id": _OUTSIDER,
            "auxiliar_id": _OUTSIDER,
            "endereco": "Endereço Hackeado, 999",
            "dia_reuniao": "domingo",
            "horario": "06:00",
        },
    )
    assert resp.status_code == 200, resp.text
    # Padrão da célula intacto (RF-14).
    assert cell.anfitriao_id is None
    assert cell.auxiliar_id is None
    assert cell.endereco == "Rua das Flores, 100"
    assert cell.dia_reuniao == "quinta"
    assert cell.horario == "20:00"
    # Resposta não expõe campos sensíveis.
    assert "endereco" not in resp.json()


def test_edit_meeting_404_other_leader(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, celula_id=_OTHER_CELL)
    session = _leader_session(
        cells=[make_cell(cell_id=_OTHER_CELL, lider_id=_OUTSIDER)], reunioes=[reu]
    )
    resp = _wire(app, session=session).put(
        f"/cell-meetings/{_REU}", headers=_AUTH, json={"data": "2026-03-19"}
    )
    assert resp.status_code == 404


def test_edit_meeting_requires_auth(app) -> None:
    session = _leader_session(reunioes=[make_reuniao()])
    resp = _wire(app, session=session).put(
        f"/cell-meetings/{_REU}", json={"data": "2026-03-19"}
    )
    assert resp.status_code == 401


# ===========================================================================
# PUT /cell-meetings/{id}/attendance — presença real
# ===========================================================================
_ATT_PATH = f"/cell-meetings/{_REU}/attendance"


def test_attendance_upserts_states(app) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    session = _leader_session(reunioes=[reu], presencas=[])
    resp = _wire(app, session=session).put(
        _ATT_PATH,
        headers=_AUTH,
        json={"presencas": [{"pessoa_id": _MEMBER, "compareceu": True}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meeting_id"] == _REU
    assert body["presencas"] == [{"pessoa_id": _MEMBER, "compareceu": True}]
    assert len(session.presencas) == 1
    assert session.presencas[0].estado == "compareceu"
    assert session.presencas[0].origem == "lider"


def test_attendance_marks_absent(app) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    existing = make_presenca(pessoa_id=_MEMBER, estado="compareceu")
    session = _leader_session(reunioes=[reu], presencas=[existing])
    resp = _wire(app, session=session).put(
        _ATT_PATH,
        headers=_AUTH,
        json={"presencas": [{"pessoa_id": _MEMBER, "compareceu": False}]},
    )
    assert resp.status_code == 200, resp.text
    assert existing.estado == "ausente"  # upsert last-write-wins
    assert len(session.presencas) == 1


def test_attendance_422_pessoa_other_tenant(app) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    # _OUTSIDER não está em `pessoas` do tenant -> _assert_pessoa_tenant 422.
    session = _leader_session(
        reunioes=[reu], pessoas=[make_pessoa(_LEADER, "Líder")]
    )
    resp = _wire(app, session=session).put(
        _ATT_PATH,
        headers=_AUTH,
        json={"presencas": [{"pessoa_id": _OUTSIDER, "compareceu": True}]},
    )
    assert resp.status_code == 422
    assert session.presencas == []


def test_attendance_422_without_active_membership(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, celula_id=_CELL)
    # _MEMBER ativo em OUTRA célula não vale para a reunião (E11).
    session = _leader_session(
        reunioes=[reu],
        membros=[make_member(pessoa_id=_MEMBER, celula_id=_OTHER_CELL, ativo=True)],
    )
    resp = _wire(app, session=session).put(
        _ATT_PATH,
        headers=_AUTH,
        json={"presencas": [{"pessoa_id": _MEMBER, "compareceu": True}]},
    )
    assert resp.status_code == 422
    assert session.presencas == []


def test_attendance_404_other_leader(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, celula_id=_OTHER_CELL)
    session = _leader_session(
        cells=[make_cell(cell_id=_OTHER_CELL, lider_id=_OUTSIDER)], reunioes=[reu]
    )
    resp = _wire(app, session=session).put(
        _ATT_PATH,
        headers=_AUTH,
        json={"presencas": [{"pessoa_id": _MEMBER, "compareceu": True}]},
    )
    assert resp.status_code == 404


def test_attendance_requires_auth(app) -> None:
    session = _leader_session(reunioes=[make_reuniao()])
    resp = _wire(app, session=session).put(
        _ATT_PATH, json={"presencas": []}
    )
    assert resp.status_code == 401


# ===========================================================================
# POST /cell-meetings/{id}/visitors — visitante presente
# ===========================================================================
_VIS_PATH = f"/cell-meetings/{_REU}/visitors"


def test_register_visitor_201(app) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    session = _leader_session(reunioes=[reu], visitantes=[])
    resp = _wire(app, session=session).post(
        _VIS_PATH,
        headers=_AUTH,
        json={"nome_visitante": "  João Novo  ", "observacao": "Convidado do culto"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["nome_visitante"] == "João Novo"  # trim
    assert body["reuniao_id"] == _REU
    assert body["expectativa_id"] is None
    assert body["id"]
    assert len(session.visitantes) == 1


def test_register_visitor_links_expectativa(app) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    exp = make_expectativa(expectativa_id=_EXP, reuniao_id=_REU)
    session = _leader_session(reunioes=[reu], expectativas=[exp], visitantes=[])
    resp = _wire(app, session=session).post(
        _VIS_PATH,
        headers=_AUTH,
        json={"nome_visitante": "Ana Esperada", "expectativa_id": _EXP},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["expectativa_id"] == _EXP


def test_register_visitor_422_expectativa_mismatch(app) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    # Expectativa de OUTRA reunião → não pertence a esta → 422.
    exp = make_expectativa(expectativa_id=_EXP, reuniao_id="other-reu")
    session = _leader_session(reunioes=[reu], expectativas=[exp], visitantes=[])
    resp = _wire(app, session=session).post(
        _VIS_PATH,
        headers=_AUTH,
        json={"nome_visitante": "Ana", "expectativa_id": _EXP},
    )
    assert resp.status_code == 422
    assert session.visitantes == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"nome_visitante": ""},
        {"nome_visitante": "   "},
        {"nome_visitante": "x" * 121},
        {"nome_visitante": "Ok", "expectativa_id": "not-a-uuid"},
    ],
)
def test_register_visitor_422_invalid(app, payload) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    session = _leader_session(reunioes=[reu], visitantes=[])
    resp = _wire(app, session=session).post(_VIS_PATH, headers=_AUTH, json=payload)
    assert resp.status_code == 422
    assert session.visitantes == []


def test_register_visitor_404_other_leader(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, celula_id=_OTHER_CELL)
    session = _leader_session(
        cells=[make_cell(cell_id=_OTHER_CELL, lider_id=_OUTSIDER)],
        reunioes=[reu],
        visitantes=[],
    )
    resp = _wire(app, session=session).post(
        _VIS_PATH, headers=_AUTH, json={"nome_visitante": "João"}
    )
    assert resp.status_code == 404


# ===========================================================================
# GET /cell-meetings/{id}/visitor-expectations
# ===========================================================================
def test_list_visitor_expectations_derives_compareceu(app) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    exp_present = make_expectativa(
        expectativa_id=_EXP,
        reuniao_id=_REU,
        pessoa_id=_MEMBER,
        nome_visitante="Presente",
        created_at=dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc),
    )
    exp_absent = make_expectativa(
        expectativa_id="00000000-0000-0000-0000-0000000000f8",
        reuniao_id=_REU,
        pessoa_id=_MEMBER,
        nome_visitante="Ausente",
        created_at=dt.datetime(2020, 1, 2, tzinfo=dt.timezone.utc),
    )
    vis = make_visitante(reuniao_id=_REU, expectativa_id=_EXP)
    session = _leader_session(
        reunioes=[reu], expectativas=[exp_present, exp_absent], visitantes=[vis]
    )
    resp = _wire(app, session=session).get(
        f"/cell-meetings/{_REU}/visitor-expectations", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["expectations"]
    by_name = {i["nome_visitante"]: i for i in items}
    assert by_name["Presente"]["compareceu"] is True
    assert by_name["Ausente"]["compareceu"] is False
    assert by_name["Presente"]["indicado_por"] == _MEMBER


def test_list_visitor_expectations_404_other_leader(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, celula_id=_OTHER_CELL)
    session = _leader_session(
        cells=[make_cell(cell_id=_OTHER_CELL, lider_id=_OUTSIDER)], reunioes=[reu]
    )
    resp = _wire(app, session=session).get(
        f"/cell-meetings/{_REU}/visitor-expectations", headers=_AUTH
    )
    assert resp.status_code == 404


# ===========================================================================
# POST /cell-meetings/{id}/records — registro pastoral
# ===========================================================================
_REC_PATH = f"/cell-meetings/{_REU}/records"


def test_add_record_sets_autor_from_context_201(app) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    session = _leader_session(reunioes=[reu], registros=[])
    resp = _wire(app, session=session).post(
        _REC_PATH,
        headers=_AUTH,
        json={"tipo": "decisao", "conteudo": "Aceitou a Cristo", "pessoa_id": _MEMBER},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["tipo"] == "decisao"
    assert body["conteudo"] == "Aceitou a Cristo"
    assert body["pessoa_id"] == _MEMBER
    assert body["autor_id"] == _LEADER  # do contexto, nunca do payload
    assert len(session.registros) == 1


def test_add_record_422_invalid_tipo(app) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    session = _leader_session(reunioes=[reu], registros=[])
    resp = _wire(app, session=session).post(
        _REC_PATH, headers=_AUTH, json={"tipo": "fofoca", "conteudo": "algo"}
    )
    assert resp.status_code == 422
    assert session.registros == []


def test_add_record_422_pessoa_other_tenant(app) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    session = _leader_session(
        reunioes=[reu], registros=[], pessoas=[make_pessoa(_LEADER, "Líder")]
    )
    resp = _wire(app, session=session).post(
        _REC_PATH,
        headers=_AUTH,
        json={"tipo": "oracao", "conteudo": "orar", "pessoa_id": _OUTSIDER},
    )
    assert resp.status_code == 422
    assert session.registros == []


def test_add_record_404_other_leader(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, celula_id=_OTHER_CELL)
    session = _leader_session(
        cells=[make_cell(cell_id=_OTHER_CELL, lider_id=_OUTSIDER)],
        reunioes=[reu],
        registros=[],
    )
    resp = _wire(app, session=session).post(
        _REC_PATH, headers=_AUTH, json={"tipo": "observacao", "conteudo": "x"}
    )
    assert resp.status_code == 404


# ===========================================================================
# GET /cell-meetings/{id}/records — líder/Central; oculto do discípulo
# ===========================================================================
def test_list_records_leader_sees(app) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    rec = make_registro(reuniao_id=_REU, tipo="decisao", conteudo="Decisão")
    session = _leader_session(reunioes=[reu], registros=[rec])
    resp = _wire(app, session=session).get(_REC_PATH, headers=_AUTH)
    assert resp.status_code == 200, resp.text
    records = resp.json()["records"]
    assert len(records) == 1
    assert records[0]["tipo"] == "decisao"


def test_list_records_central_sees_any_cell(app) -> None:
    # Central (pastor) lê registros de célula que NÃO lidera.
    reu = make_reuniao(reuniao_id=_REU, celula_id=_OTHER_CELL)
    rec = make_registro(reuniao_id=_REU)
    session = _leader_session(
        roles=["pastor"],
        actor_pessoa_id=_OUTSIDER,
        cells=[make_cell(cell_id=_OTHER_CELL, lider_id="00000000-0000-0000-0000-0000000000bb")],
        reunioes=[reu],
        registros=[rec],
    )
    resp = _wire(app, session=session).get(_REC_PATH, headers=_AUTH)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["records"]) == 1


def test_list_records_404_for_disciple(app) -> None:
    # Membro comum que não lidera a célula → 404 (projeção pastoral oculta).
    reu = make_reuniao(reuniao_id=_REU)
    session = _leader_session(
        roles=["membro"],
        actor_pessoa_id=_MEMBER,
        cells=[make_cell(lider_id=_LEADER)],
        reunioes=[reu],
        registros=[make_registro(reuniao_id=_REU)],
    )
    resp = _wire(app, session=session).get(_REC_PATH, headers=_AUTH)
    assert resp.status_code == 404


# ===========================================================================
# PUT /cell-meetings/{id}/report — rascunho de oferta/observações
# ===========================================================================
_REP_PATH = f"/cell-meetings/{_REU}/report"


def test_save_report_keeps_pending(app) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    session = _leader_session(reunioes=[reu])
    resp = _wire(app, session=session).put(
        _REP_PATH,
        headers=_AUTH,
        json={"oferta_valor": 150.50, "observacoes": "Boa reunião"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["oferta_valor"] == 150.50
    assert body["observacoes"] == "Boa reunião"
    assert body["relatorio_status"] == "pendente"  # não envia
    assert reu.oferta_valor == 150.50


@pytest.mark.parametrize(
    "payload",
    [
        {"oferta_valor": -1},
        {"oferta_valor": 1000000},
        {"observacoes": "x" * 2001},
    ],
)
def test_save_report_422_invalid(app, payload) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    session = _leader_session(reunioes=[reu])
    resp = _wire(app, session=session).put(_REP_PATH, headers=_AUTH, json=payload)
    assert resp.status_code == 422


def test_save_report_accepts_boundaries(app) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    session = _leader_session(reunioes=[reu])
    resp = _wire(app, session=session).put(
        _REP_PATH, headers=_AUTH, json={"oferta_valor": 999999.99}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["oferta_valor"] == 999999.99


def test_save_report_404_other_leader(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, celula_id=_OTHER_CELL)
    session = _leader_session(
        cells=[make_cell(cell_id=_OTHER_CELL, lider_id=_OUTSIDER)], reunioes=[reu]
    )
    resp = _wire(app, session=session).put(
        _REP_PATH, headers=_AUTH, json={"oferta_valor": 10}
    )
    assert resp.status_code == 404


# ===========================================================================
# POST /cell-meetings/{id}/report/submit — enviar relatório
# ===========================================================================
_SUBMIT_PATH = f"/cell-meetings/{_REU}/report/submit"


def test_submit_report_marks_sent(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, relatorio_status="pendente")
    session = _leader_session(reunioes=[reu])
    resp = _wire(app, session=session).post(_SUBMIT_PATH, headers=_AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["relatorio_status"] == "enviado"
    assert body["relatorio_enviado_em"] is not None
    assert body["relatorio_enviado_por"] == _LEADER
    assert reu.relatorio_status == "enviado"


def test_submit_report_409_already_sent(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, relatorio_status="enviado")
    session = _leader_session(reunioes=[reu])
    resp = _wire(app, session=session).post(_SUBMIT_PATH, headers=_AUTH)
    assert resp.status_code == 409


def test_submit_report_404_other_leader(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, celula_id=_OTHER_CELL)
    session = _leader_session(
        cells=[make_cell(cell_id=_OTHER_CELL, lider_id=_OUTSIDER)], reunioes=[reu]
    )
    resp = _wire(app, session=session).post(_SUBMIT_PATH, headers=_AUTH)
    assert resp.status_code == 404


# ===========================================================================
# GET /cell-meetings/{id}/report — consolidado
# ===========================================================================
def test_get_report_consolidates(app) -> None:
    reu = make_reuniao(
        reuniao_id=_REU,
        tema="Consolidado",
        oferta_valor=200.0,
        observacoes="Notas",
        relatorio_status="pendente",
    )
    pres = make_presenca(pessoa_id=_MEMBER, estado="compareceu", origem="lider")
    vis = make_visitante(reuniao_id=_REU, nome_visitante="Visita")
    rec = make_registro(reuniao_id=_REU, tipo="decisao", conteudo="Decisão")
    session = _leader_session(
        reunioes=[reu], presencas=[pres], visitantes=[vis], registros=[rec]
    )
    resp = _wire(app, session=session).get(_REP_PATH, headers=_AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meeting_id"] == _REU
    assert body["tema"] == "Consolidado"
    assert body["oferta_valor"] == 200.0
    assert body["observacoes"] == "Notas"
    assert body["relatorio_status"] == "pendente"
    assert len(body["presencas"]) == 1
    assert body["presencas"][0]["estado"] == "compareceu"
    assert len(body["visitantes"]) == 1
    assert body["visitantes"][0]["nome_visitante"] == "Visita"
    assert len(body["records"]) == 1
    assert body["records"][0]["tipo"] == "decisao"


def test_report_frozen_after_submit_via_snapshot(app) -> None:
    # E10/E11: submit congela o snapshot; mudar celula_presenca depois (upsert
    # PR2, sempre-200) NÃO altera o relatório enviado — get lê o snapshot.
    reu = make_reuniao(reuniao_id=_REU, relatorio_status="pendente")
    pres = make_presenca(pessoa_id=_MEMBER, estado="compareceu", origem="lider")
    session = _leader_session(reunioes=[reu], presencas=[pres])
    client = _wire(app, session=session)

    sub = client.post(_SUBMIT_PATH, headers=_AUTH)
    assert sub.status_code == 200, sub.text
    assert reu.relatorio_status == "enviado"
    assert reu.relatorio_snapshot is not None  # snapshot materializado

    # Alteração AO VIVO após o envio (simula o endpoint PR2 de presença).
    pres.estado = "ausente"

    rep = client.get(_REP_PATH, headers=_AUTH)
    assert rep.status_code == 200, rep.text
    body = rep.json()
    assert body["relatorio_status"] == "enviado"
    assert len(body["presencas"]) == 1
    assert body["presencas"][0]["estado"] == "compareceu"  # congelado, não 'ausente'


def test_edit_meeting_409_after_report_sent(app) -> None:
    # #3: editar a reunião após o relatório enviado é bloqueado (E10/E11).
    reu = make_reuniao(reuniao_id=_REU, relatorio_status="enviado")
    session = _leader_session(reunioes=[reu])
    resp = _wire(app, session=session).put(
        f"/cell-meetings/{_REU}",
        headers=_AUTH,
        json={"data": "2026-04-01", "hora": "20:00", "tema": "Novo"},
    )
    assert resp.status_code == 409


def test_get_report_central_reads_any_cell(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, celula_id=_OTHER_CELL)
    session = _leader_session(
        roles=["pastor"],
        actor_pessoa_id=_OUTSIDER,
        cells=[make_cell(cell_id=_OTHER_CELL, lider_id="00000000-0000-0000-0000-0000000000bb")],
        reunioes=[reu],
    )
    resp = _wire(app, session=session).get(_REP_PATH, headers=_AUTH)
    assert resp.status_code == 200, resp.text


def test_get_report_404_for_disciple(app) -> None:
    reu = make_reuniao(reuniao_id=_REU)
    session = _leader_session(
        roles=["membro"], actor_pessoa_id=_MEMBER, reunioes=[reu]
    )
    resp = _wire(app, session=session).get(_REP_PATH, headers=_AUTH)
    assert resp.status_code == 404


# ===========================================================================
# E10/E11 — após enviado, escritas bloqueadas (409); sem reabertura
# ===========================================================================
def test_locked_report_blocks_writes(app) -> None:
    reu = make_reuniao(reuniao_id=_REU, relatorio_status="enviado")
    session = _leader_session(reunioes=[reu])
    client = _wire(app, session=session)

    # PUT report → 409
    r1 = client.put(_REP_PATH, headers=_AUTH, json={"oferta_valor": 10})
    assert r1.status_code == 409
    # submit de novo → 409
    r2 = client.post(_SUBMIT_PATH, headers=_AUTH)
    assert r2.status_code == 409
    # presença → 409
    r3 = client.put(
        _ATT_PATH,
        headers=_AUTH,
        json={"presencas": [{"pessoa_id": _MEMBER, "compareceu": True}]},
    )
    assert r3.status_code == 409
    # visitante → 409
    r4 = client.post(_VIS_PATH, headers=_AUTH, json={"nome_visitante": "João"})
    assert r4.status_code == 409
    # registro → 409
    r5 = client.post(
        _REC_PATH, headers=_AUTH, json={"tipo": "observacao", "conteudo": "x"}
    )
    assert r5.status_code == 409


def test_locked_report_still_readable(app) -> None:
    # GET do relatório continua disponível após envio (só escrita bloqueia).
    reu = make_reuniao(reuniao_id=_REU, relatorio_status="enviado")
    session = _leader_session(reunioes=[reu])
    resp = _wire(app, session=session).get(_REP_PATH, headers=_AUTH)
    assert resp.status_code == 200, resp.text
    assert resp.json()["relatorio_status"] == "enviado"


# ===========================================================================
# GET /cells/{cell_id}/members — discípulos da própria célula
# ===========================================================================
def test_list_members_returns_active(app) -> None:
    session = _leader_session(
        membros=[
            make_member(pessoa_id=_MEMBER, celula_id=_CELL, ativo=True),
            make_member(pessoa_id=_OUTSIDER, celula_id=_CELL, ativo=False),
        ]
    )
    resp = _wire(app, session=session).get(f"/cells/{_CELL}/members", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    members = resp.json()["members"]
    assert len(members) == 1  # só ativos
    assert members[0]["pessoa_id"] == _MEMBER
    assert members[0]["nome"] == "Membro Fiel"
    assert members[0]["ativo"] is True


def test_list_members_404_other_leader(app) -> None:
    session = _leader_session(cells=[make_cell(cell_id=_CELL, lider_id=_OUTSIDER)])
    resp = _wire(app, session=session).get(f"/cells/{_CELL}/members", headers=_AUTH)
    assert resp.status_code == 404


def test_list_members_404_other_tenant(app) -> None:
    session = _leader_session(
        cells=[make_cell(cell_id=_CELL, lider_id=_LEADER, igreja_id=_OTHER)]
    )
    resp = _wire(app, session=session).get(f"/cells/{_CELL}/members", headers=_AUTH)
    assert resp.status_code == 404


def test_list_members_requires_auth(app) -> None:
    session = _leader_session()
    resp = _wire(app, session=session).get(f"/cells/{_CELL}/members")
    assert resp.status_code == 401


# ===========================================================================
# GET /cells/me/leading — célula(s) que o ator LIDERA (#16)
# ===========================================================================
def test_list_my_led_cells_returns_led_cell(app) -> None:
    session = _leader_session(cells=[make_cell(cell_id=_CELL, lider_id=_LEADER)])
    resp = _wire(app, session=session).get("/cells/me/leading", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == _CELL


def test_list_my_led_cells_empty_when_not_leader(app) -> None:
    # Ator é MEMBRO mas não LIDERA esta célula (lider_id de outro) → lista vazia.
    session = _leader_session(cells=[make_cell(cell_id=_CELL, lider_id=_OUTSIDER)])
    resp = _wire(app, session=session).get("/cells/me/leading", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_list_my_led_cells_requires_auth(app) -> None:
    session = _leader_session()
    resp = _wire(app, session=session).get("/cells/me/leading")
    assert resp.status_code == 401
