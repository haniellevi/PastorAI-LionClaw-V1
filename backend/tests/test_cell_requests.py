"""Testes das Solicitações de célula e Multiplicação transacional (Células PR3-PR9).

Cobre os endpoints de ``app/routers/cell_requests.py`` (contrato snake_case) e a
visão consolidada de ``app/routers/multiplicacoes.py``:

  Criação/leitura (líder):
    * POST /cell-requests                 (nasce 'aguardando' + evento 'criada')
    * GET  /cell-requests                 (Central vê a igreja; líder vê as suas)
    * GET  /cell-requests/{id}            (detalhe + trilha de eventos)

  Decisão (Central) e ciclo do autor:
    * POST /cell-requests/{id}/approve            (aplica payload + auditoria)
    * POST /cell-requests/{id}/reject             (observacao obrigatória)
    * POST /cell-requests/{id}/request-adjustment (observacao obrigatória)
    * PUT  /cell-requests/{id}/resubmit           (autor, só em ajuste_solicitado)
    * POST /cell-requests/{id}/cancel             (autor, enquanto aberta)

  Multiplicação transacional/idempotente + GET /multiplicacoes.

Estilo fake-session (sem Postgres/Clerk reais): o fake espelha os predicados
WHERE (==, IN, ativo) e o ORDER BY do router/serviço. Ownership de célula deriva
de ``celulas.lider_id`` ligado à Pessoa do app_user (E9/6.6), nunca do payload.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from app.db.models import (
    AppUser,
    Celula,
    CelulaMembro,
    CelulaSolicitacao,
    CelulaSolicitacaoEvento,
    Multiplicacao,
    Pessoa,
)
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}

_APPUSER = "00000000-0000-0000-0000-0000000000a1"  # id de make_app_user()
_TENANT = "00000000-0000-0000-0000-000000000001"
_OTHER = "00000000-0000-0000-0000-000000000002"
_CELL = "00000000-0000-0000-0000-0000000000e1"
_DEST_CELL = "00000000-0000-0000-0000-0000000000e2"
_LEADER = "00000000-0000-0000-0000-0000000000b1"  # pessoa do líder (app_user atual)
_PASTOR = "00000000-0000-0000-0000-0000000000b9"  # pessoa da Central (≠ autor, 3.1)
_MEMBER = "00000000-0000-0000-0000-0000000000d1"  # pessoa membro / novo líder
_MEMBER2 = "00000000-0000-0000-0000-0000000000d2"
_OUTSIDER = "00000000-0000-0000-0000-0000000000c9"
_SOLIC = "00000000-0000-0000-0000-0000000000f1"


# ===========================================================================
# Fake session (espelha WHERE ==/IN/ativo + ORDER BY)
# ===========================================================================
class _Res:
    def __init__(self, *, scalar=None, scalars=None, first=None, rows=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []
        self._first = first
        self._rows = rows or []

    def scalar_one(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def first(self):
        return self._first

    def all(self):
        return list(self._rows)


def _collect(node, eqs, ins) -> None:
    clauses = getattr(node, "clauses", None)
    if clauses:
        for child in clauses:
            _collect(child, eqs, ins)
        return
    left = getattr(node, "left", None)
    right = getattr(node, "right", None)
    if left is None or right is None:
        return
    key = getattr(left, "key", None)
    value = getattr(right, "value", None)
    if key is None or value is None:
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        ins[key] = {str(v) for v in value}
    else:
        eqs[key] = str(value)


class ReqSession:
    def __init__(
        self,
        *,
        app_user,
        roles,
        actor_pessoa_id=None,
        cells=None,
        membros=None,
        pessoas=None,
        solicitacoes=None,
        eventos=None,
        multiplicacoes=None,
    ) -> None:
        self.app_user = app_user
        self.roles = roles
        self.actor_pessoa_id = actor_pessoa_id
        self.cells = cells or []
        self.membros = membros or []
        self.pessoas = pessoas or []
        self.solicitacoes = solicitacoes or []
        self.eventos = eventos or []
        self.multiplicacoes = multiplicacoes or []
        self.added: list = []
        self.committed = False
        self.rolled_back = False

    # -- predicate helpers --------------------------------------------------
    @staticmethod
    def _preds(statement) -> tuple[dict, dict]:
        eqs: dict[str, str] = {}
        ins: dict[str, set[str]] = {}
        clause = getattr(statement, "whereclause", None)
        if clause is not None:
            _collect(clause, eqs, ins)
        return eqs, ins

    def _filter(self, store, statement):
        eqs, ins = self._preds(statement)
        out = []
        for o in store:
            if not all(str(getattr(o, k, None)) == v for k, v in eqs.items()):
                continue
            if not all(str(getattr(o, k, None)) in vs for k, vs in ins.items()):
                continue
            out.append(o)
        return out

    @staticmethod
    def _order(rows, statement):
        specs = []
        from sqlalchemy.sql import operators

        for clause in getattr(statement, "_order_by_clauses", ()) or ():
            descending = getattr(clause, "modifier", None) is operators.desc_op
            element = getattr(clause, "element", clause)
            key = getattr(element, "key", None)
            if key is None:
                inner = getattr(element, "element", None)
                key = getattr(inner, "key", None)
            if key:
                specs.append((key, descending))
        rows = list(rows)
        for key, descending in reversed(specs):
            rows.sort(
                key=lambda r, k=key: (getattr(r, k, None) is not None, getattr(r, k, None)),
                reverse=descending,
            )
        return rows

    # -- execute ------------------------------------------------------------
    def execute(self, statement, params=None) -> _Res:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        name = descs[0].get("name") if descs else None

        # func.count() projection (list endpoint).
        if descs and ent is None and name and "count" in str(name).lower():
            return _Res(scalar=len(self._filter(self.solicitacoes, statement)))

        if ent is AppUser and name == "pessoa_id":
            return _Res(scalar=self.actor_pessoa_id)
        if ent is AppUser:
            return _Res(scalar=self.app_user)
        if ent is Pessoa:
            rows = self._filter(self.pessoas, statement)
            if name == "id":
                return _Res(scalar=(rows[0].id if rows else None))
            return _Res(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is Celula:
            rows = self._filter(self.cells, statement)
            return _Res(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is CelulaMembro:
            rows = self._filter(self.membros, statement)
            return _Res(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is CelulaSolicitacao:
            rows = self._filter(self.solicitacoes, statement)
            rows = self._order(rows, statement)
            first = rows[0] if rows else None
            return _Res(scalar=first, scalars=rows, first=first)
        if ent is CelulaSolicitacaoEvento:
            rows = self._filter(self.eventos, statement)
            rows = self._order(rows, statement)
            return _Res(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is Multiplicacao:
            rows = self._filter(self.multiplicacoes, statement)
            rows = self._order(rows, statement)
            return _Res(scalar=(rows[0] if rows else None), scalars=rows)
        # set_config text / UserRole.papel projection.
        return _Res(scalars=self.roles)

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        if isinstance(obj, CelulaSolicitacao):
            self.solicitacoes.append(obj)
        elif isinstance(obj, CelulaSolicitacaoEvento):
            self.eventos.append(obj)
        elif isinstance(obj, Celula):
            self.cells.append(obj)
        elif isinstance(obj, CelulaMembro):
            self.membros.append(obj)
        elif isinstance(obj, Multiplicacao):
            self.multiplicacoes.append(obj)

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

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
    dia_reuniao: str = "quinta",
):
    return SimpleNamespace(
        id=cell_id,
        igreja_id=igreja_id,
        nome="Célula Central",
        lider_id=lider_id,
        cobertura_espiritual="Rede Norte",
        anfitriao_id=None,
        auxiliar_id=None,
        endereco="Rua das Flores, 100",
        dia_reuniao=dia_reuniao,
        horario="20:00",
        ativo=True,
    )


def make_membro(
    *, igreja_id: str = _TENANT, celula_id: str = _CELL, pessoa_id: str, ativo: bool = True
):
    return SimpleNamespace(
        id=str(uuid.uuid4()),
        igreja_id=igreja_id,
        celula_id=celula_id,
        pessoa_id=pessoa_id,
        papel="membro",
        ativo=ativo,
        created_at=dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc),
        updated_at=None,
    )


def make_pessoa(pessoa_id: str, nome: str = "Pessoa", celula_id: str | None = _CELL):
    return SimpleNamespace(
        id=pessoa_id, nome=nome, igreja_id=_TENANT, celula_id=celula_id, lider_id=None
    )


def make_solicitacao(
    *,
    solic_id: str = _SOLIC,
    igreja_id: str = _TENANT,
    celula_id: str = _CELL,
    solicitante_id: str | None = _LEADER,
    pessoa_id: str | None = None,
    tipo: str = "alterar_dia",
    status: str = "aguardando",
    payload_proposto: dict | None = None,
    observacao_central: str | None = None,
):
    return SimpleNamespace(
        id=solic_id,
        igreja_id=igreja_id,
        celula_id=celula_id,
        solicitante_id=solicitante_id,
        pessoa_id=pessoa_id,
        tipo=tipo,
        status=status,
        payload_proposto=payload_proposto or {"dia_reuniao": "sexta"},
        payload_atual=None,
        motivo=None,
        observacao_central=observacao_central,
        decidido_por=None,
        decidido_em=None,
        created_at=dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc),
        updated_at=None,
    )


def _wire(app, *, session, clerk=None):
    from fastapi.testclient import TestClient

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk or FakeClerk()
    return TestClient(app)


def _leader_session(**kwargs) -> ReqSession:
    kwargs.setdefault("app_user", make_app_user())
    kwargs.setdefault("roles", ["lider"])
    kwargs.setdefault("actor_pessoa_id", _LEADER)
    kwargs.setdefault("cells", [make_cell(lider_id=_LEADER)])
    kwargs.setdefault("pessoas", [make_pessoa(_LEADER, "Líder")])
    return ReqSession(**kwargs)


def _central_session(**kwargs) -> ReqSession:
    # A Central que DECIDE é uma pessoa distinta do líder AUTOR (segregação 3.1):
    # actor_pessoa_id=_PASTOR ≠ solicitante_id=_LEADER (default de make_solicitacao).
    kwargs.setdefault("app_user", make_app_user())
    kwargs.setdefault("roles", ["pastor"])
    kwargs.setdefault("actor_pessoa_id", _PASTOR)
    kwargs.setdefault("cells", [make_cell(lider_id=_LEADER)])
    kwargs.setdefault(
        "pessoas", [make_pessoa(_LEADER, "Líder"), make_pessoa(_PASTOR, "Pastor")]
    )
    return ReqSession(**kwargs)


# ===========================================================================
# POST /cell-requests — criação
# ===========================================================================
def test_create_request_born_aguardando_with_event(app) -> None:
    session = _leader_session()
    resp = _wire(app, session=session).post(
        "/cell-requests",
        headers=_AUTH,
        json={"celula_id": _CELL, "tipo": "alterar_dia",
              "payload_proposto": {"dia_reuniao": "sexta"}},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["celula_id"] == _CELL
    assert body["tipo"] == "alterar_dia"
    assert body["status"] == "aguardando"
    assert body["payload_proposto"] == {"dia_reuniao": "sexta"}
    assert session.committed is True
    # Não altera o dado real (a célula permanece com o dia original).
    assert session.cells[0].dia_reuniao == "quinta"
    # Gera exatamente 1 evento 'criada'.
    assert len(session.eventos) == 1
    assert session.eventos[0].acao == "criada"
    assert session.eventos[0].para_status == "aguardando"


def test_create_request_invalid_payload_422(app) -> None:
    session = _leader_session()
    resp = _wire(app, session=session).post(
        "/cell-requests",
        headers=_AUTH,
        json={"celula_id": _CELL, "tipo": "alterar_horario",
              "payload_proposto": {"horario": "25:99"}},
    )
    assert resp.status_code == 422
    assert session.solicitacoes == []


def test_create_request_unknown_tipo_422(app) -> None:
    session = _leader_session()
    resp = _wire(app, session=session).post(
        "/cell-requests",
        headers=_AUTH,
        json={"celula_id": _CELL, "tipo": "explodir", "payload_proposto": {}},
    )
    assert resp.status_code == 422


def test_create_request_endereco_too_long_422(app) -> None:
    session = _leader_session()
    resp = _wire(app, session=session).post(
        "/cell-requests",
        headers=_AUTH,
        json={"celula_id": _CELL, "tipo": "alterar_endereco",
              "payload_proposto": {"endereco": "x" * 256}},
    )
    assert resp.status_code == 422


def test_create_request_conflict_open_same_tipo_409(app) -> None:
    existing = make_solicitacao(tipo="alterar_dia", status="aguardando")
    session = _leader_session(solicitacoes=[existing])
    resp = _wire(app, session=session).post(
        "/cell-requests",
        headers=_AUTH,
        json={"celula_id": _CELL, "tipo": "alterar_dia",
              "payload_proposto": {"dia_reuniao": "sexta"}},
    )
    assert resp.status_code == 409


def test_create_request_no_conflict_when_existing_closed(app) -> None:
    existing = make_solicitacao(tipo="alterar_dia", status="rejeitada")
    session = _leader_session(solicitacoes=[existing])
    resp = _wire(app, session=session).post(
        "/cell-requests",
        headers=_AUTH,
        json={"celula_id": _CELL, "tipo": "alterar_dia",
              "payload_proposto": {"dia_reuniao": "sexta"}},
    )
    assert resp.status_code == 201, resp.text


def test_create_request_member_conflict_same_pessoa_409(app) -> None:
    existing = make_solicitacao(
        tipo="remover_membro", status="aguardando", pessoa_id=_MEMBER,
        payload_proposto={"pessoa_id": _MEMBER},
    )
    session = _leader_session(solicitacoes=[existing])
    resp = _wire(app, session=session).post(
        "/cell-requests",
        headers=_AUTH,
        json={"celula_id": _CELL, "tipo": "transferir_membro",
              "payload_proposto": {"pessoa_id": _MEMBER, "celula_destino_id": _DEST_CELL}},
    )
    assert resp.status_code == 409


def test_create_request_404_when_not_leader(app) -> None:
    session = _leader_session(cells=[make_cell(lider_id=_OUTSIDER)])
    resp = _wire(app, session=session).post(
        "/cell-requests",
        headers=_AUTH,
        json={"celula_id": _CELL, "tipo": "alterar_dia",
              "payload_proposto": {"dia_reuniao": "sexta"}},
    )
    assert resp.status_code == 404
    assert session.solicitacoes == []


def test_create_request_requires_auth(app) -> None:
    session = _leader_session()
    resp = _wire(app, session=session).post(
        "/cell-requests",
        json={"celula_id": _CELL, "tipo": "alterar_dia",
              "payload_proposto": {"dia_reuniao": "sexta"}},
    )
    assert resp.status_code == 401


# ===========================================================================
# GET /cell-requests — listagem
# ===========================================================================
def test_list_central_sees_all_igreja(app) -> None:
    minhas = make_solicitacao(solic_id=_SOLIC, solicitante_id=_LEADER)
    outra = make_solicitacao(
        solic_id="00000000-0000-0000-0000-0000000000f2", solicitante_id=_OUTSIDER
    )
    session = _central_session(solicitacoes=[minhas, outra])
    resp = _wire(app, session=session).get("/cell-requests", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_list_leader_sees_only_own(app) -> None:
    minhas = make_solicitacao(solic_id=_SOLIC, solicitante_id=_LEADER)
    outra = make_solicitacao(
        solic_id="00000000-0000-0000-0000-0000000000f2", solicitante_id=_OUTSIDER
    )
    session = _leader_session(solicitacoes=[minhas, outra])
    resp = _wire(app, session=session).get("/cell-requests", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["solicitante_id"] == _LEADER


def test_list_status_filter(app) -> None:
    aguardando = make_solicitacao(solic_id=_SOLIC, status="aguardando")
    aprovada = make_solicitacao(
        solic_id="00000000-0000-0000-0000-0000000000f2", status="aprovada"
    )
    session = _central_session(solicitacoes=[aguardando, aprovada])
    resp = _wire(app, session=session).get(
        "/cell-requests?status=aprovada", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "aprovada"


# ===========================================================================
# GET /cell-requests/{id} — detalhe + trilha
# ===========================================================================
def test_get_detail_with_events_trail(app) -> None:
    solic = make_solicitacao()
    ev1 = SimpleNamespace(
        id="ev1", acao="criada", autor_id=_LEADER, de_status=None,
        para_status="aguardando", observacao=None, payload_snapshot={"dia_reuniao": "sexta"},
        solicitacao_id=_SOLIC, created_at=dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc),
    )
    ev2 = SimpleNamespace(
        id="ev2", acao="aprovada", autor_id=_LEADER, de_status="aguardando",
        para_status="aprovada", observacao=None, payload_snapshot={"dia_reuniao": "sexta"},
        solicitacao_id=_SOLIC, created_at=dt.datetime(2026, 3, 2, tzinfo=dt.timezone.utc),
    )
    session = _central_session(solicitacoes=[solic], eventos=[ev2, ev1])
    resp = _wire(app, session=session).get(f"/cell-requests/{_SOLIC}", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == _SOLIC
    assert [e["acao"] for e in body["eventos"]] == ["criada", "aprovada"]


def test_get_detail_404_other_tenant(app) -> None:
    solic = make_solicitacao(igreja_id=_OTHER)
    session = _central_session(solicitacoes=[solic])
    resp = _wire(app, session=session).get(f"/cell-requests/{_SOLIC}", headers=_AUTH)
    assert resp.status_code == 404


# ===========================================================================
# POST /cell-requests/{id}/approve
# ===========================================================================
def test_approve_applies_payload_and_audits(app) -> None:
    solic = make_solicitacao(
        tipo="alterar_dia", status="aguardando",
        payload_proposto={"dia_reuniao": "sexta"},
    )
    cell = make_cell(dia_reuniao="quinta")
    session = _central_session(cells=[cell], solicitacoes=[solic])
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve", headers=_AUTH, json={}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "aprovada"
    assert cell.dia_reuniao == "sexta"  # dado real aplicado
    assert session.committed is True
    assert any(e.acao == "aprovada" for e in session.eventos)


def test_approve_requires_central(app) -> None:
    solic = make_solicitacao()
    session = _leader_session(solicitacoes=[solic])
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve", headers=_AUTH, json={}
    )
    assert resp.status_code == 403


def test_approve_idempotent_on_already_approved(app) -> None:
    solic = make_solicitacao(status="aprovada")
    cell = make_cell()
    session = _central_session(cells=[cell], solicitacoes=[solic])
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve", headers=_AUTH, json={}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "aprovada"
    # Reprocesso não gera novo evento.
    assert session.eventos == []


def test_approve_conflict_when_already_rejected(app) -> None:
    solic = make_solicitacao(status="rejeitada")
    cell = make_cell()
    session = _central_session(cells=[cell], solicitacoes=[solic])
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve", headers=_AUTH, json={}
    )
    assert resp.status_code == 409


def test_approve_blocked_when_actor_is_author_403(app) -> None:
    # Segregação 3.1: pastor que também é o líder AUTOR não aprova a própria.
    solic = make_solicitacao(status="aguardando", solicitante_id=_LEADER)
    cell = make_cell(dia_reuniao="quinta")
    session = _central_session(
        cells=[cell], solicitacoes=[solic], actor_pessoa_id=_LEADER
    )
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve", headers=_AUTH, json={}
    )
    assert resp.status_code == 403
    assert cell.dia_reuniao == "quinta"  # dado real intacto
    assert session.committed is False


def test_write_endpoints_503_when_flag_off(app, monkeypatch) -> None:
    # Gate de rollout (CELULAS_REQUESTS_ENABLED off) barra a escrita sensível.
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "celulas_requests_enabled", False)
    session = _leader_session()
    resp = _wire(app, session=session).post(
        "/cell-requests",
        headers=_AUTH,
        json={"celula_id": _CELL, "tipo": "alterar_dia",
              "payload_proposto": {"dia_reuniao": "sexta"}},
    )
    assert resp.status_code == 503
    assert session.solicitacoes == []


# ===========================================================================
# POST reject / request-adjustment
# ===========================================================================
def test_reject_requires_observacao_422(app) -> None:
    solic = make_solicitacao(status="aguardando")
    session = _central_session(solicitacoes=[solic])
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/reject", headers=_AUTH, json={}
    )
    assert resp.status_code == 422


def test_reject_sets_rejeitada(app) -> None:
    solic = make_solicitacao(status="aguardando")
    session = _central_session(solicitacoes=[solic])
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/reject",
        headers=_AUTH,
        json={"observacao_central": "Fora do padrão"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejeitada"
    assert resp.json()["observacao_central"] == "Fora do padrão"
    assert any(e.acao == "rejeitada" for e in session.eventos)


def test_request_adjustment_sets_ajuste(app) -> None:
    solic = make_solicitacao(status="aguardando")
    session = _central_session(solicitacoes=[solic])
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/request-adjustment",
        headers=_AUTH,
        json={"observacao_central": "Ajuste o endereço"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ajuste_solicitado"


# ===========================================================================
# PUT resubmit / POST cancel (autor)
# ===========================================================================
def test_resubmit_only_in_ajuste_409(app) -> None:
    solic = make_solicitacao(status="aguardando")
    session = _leader_session(solicitacoes=[solic])
    resp = _wire(app, session=session).put(
        f"/cell-requests/{_SOLIC}/resubmit",
        headers=_AUTH,
        json={"payload_proposto": {"dia_reuniao": "sabado"}},
    )
    assert resp.status_code == 409


def test_resubmit_from_ajuste_back_to_aguardando(app) -> None:
    solic = make_solicitacao(status="ajuste_solicitado")
    session = _leader_session(solicitacoes=[solic])
    resp = _wire(app, session=session).put(
        f"/cell-requests/{_SOLIC}/resubmit",
        headers=_AUTH,
        json={"payload_proposto": {"dia_reuniao": "sabado"}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "aguardando"
    assert body["payload_proposto"] == {"dia_reuniao": "sabado"}
    assert any(e.acao == "reenviada" for e in session.eventos)


def test_resubmit_404_when_not_author(app) -> None:
    solic = make_solicitacao(status="ajuste_solicitado", solicitante_id=_OUTSIDER)
    session = _leader_session(solicitacoes=[solic])
    resp = _wire(app, session=session).put(
        f"/cell-requests/{_SOLIC}/resubmit",
        headers=_AUTH,
        json={"payload_proposto": {"dia_reuniao": "sabado"}},
    )
    assert resp.status_code == 404


def test_cancel_open_request(app) -> None:
    solic = make_solicitacao(status="aguardando")
    session = _leader_session(solicitacoes=[solic])
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/cancel", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelada"
    assert any(e.acao == "cancelada" for e in session.eventos)


def test_cancel_decided_request_409(app) -> None:
    solic = make_solicitacao(status="aprovada")
    session = _leader_session(solicitacoes=[solic])
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/cancel", headers=_AUTH
    )
    assert resp.status_code == 409


# ===========================================================================
# Multiplicação transacional/idempotente
# ===========================================================================
def _multiplication_payload(*, with_key: bool = True) -> dict:
    payload = {
        "nome_nova_celula": "Célula Filha",
        "novo_lider_id": _MEMBER,
        "membros_transferidos_ids": [_MEMBER, _MEMBER2],
    }
    if with_key:
        payload["idempotency_key"] = "mult-key-1"
    return payload


def _multiplication_session() -> ReqSession:
    cell = make_cell()
    membros = [
        make_membro(pessoa_id=_MEMBER, celula_id=_CELL, ativo=True),
        make_membro(pessoa_id=_MEMBER2, celula_id=_CELL, ativo=True),
    ]
    pessoas = [
        make_pessoa(_LEADER, "Líder"),
        make_pessoa(_MEMBER, "Novo Líder"),
        make_pessoa(_MEMBER2, "Membro 2"),
    ]
    return _central_session(cells=[cell], membros=membros, pessoas=pessoas)


def test_approve_multiplication_requires_idempotency_key_422(app) -> None:
    session = _multiplication_session()
    session.solicitacoes = [
        make_solicitacao(
            tipo="multiplicacao", status="aguardando",
            payload_proposto=_multiplication_payload(with_key=False),
        )
    ]
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve", headers=_AUTH, json={}
    )
    assert resp.status_code == 422


def test_approve_multiplication_creates_cell_and_record(app) -> None:
    session = _multiplication_session()
    session.solicitacoes = [
        make_solicitacao(
            tipo="multiplicacao", status="aguardando",
            payload_proposto=_multiplication_payload(with_key=True),
        )
    ]
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve",
        headers=_AUTH,
        json={"idempotency_key": "mult-key-1"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "aprovada"
    # Nova célula criada (origem + filha).
    assert len(session.cells) == 2
    assert len(session.multiplicacoes) == 1
    mult = session.multiplicacoes[0]
    assert str(mult.celula_id) == _CELL  # origem permanece
    assert mult.celula_nova_id is not None
    assert mult.solicitacao_id == _SOLIC
    assert session.committed is True


def test_approve_multiplication_state_idempotent(app) -> None:
    session = _multiplication_session()
    solic = make_solicitacao(
        tipo="multiplicacao", status="aprovada",
        payload_proposto=_multiplication_payload(with_key=True),
    )
    session.solicitacoes = [solic]
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve",
        headers=_AUTH,
        json={"idempotency_key": "mult-key-1"},
    )
    assert resp.status_code == 200, resp.text
    # Reprocesso: nenhuma nova célula/registro/evento.
    assert len(session.cells) == 1
    assert session.multiplicacoes == []
    assert session.eventos == []


# ===========================================================================
# GET /multiplicacoes — pendentes + registradas
# ===========================================================================
def test_list_multiplicacoes_pendentes_e_registradas(app) -> None:
    pendente = make_solicitacao(
        solic_id=_SOLIC, tipo="multiplicacao", status="aguardando",
        payload_proposto=_multiplication_payload(),
    )
    # Uma solicitação de outro tipo NÃO deve aparecer em pendentes.
    outra = make_solicitacao(
        solic_id="00000000-0000-0000-0000-0000000000f3", tipo="alterar_dia",
        status="aguardando",
    )
    registrada = SimpleNamespace(
        id="m1", igreja_id=_TENANT, celula_id=_CELL,
        celula_nova_id=_DEST_CELL, solicitacao_id=_SOLIC, novo_lider_id=_MEMBER,
        status="concluida", data_prevista=None, descendencia=None,
        idempotency_key="mult-key-1",
        created_at=dt.datetime(2026, 3, 3, tzinfo=dt.timezone.utc),
    )
    session = _central_session(
        solicitacoes=[pendente, outra], multiplicacoes=[registrada]
    )
    resp = _wire(app, session=session).get("/multiplicacoes", headers=_AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["pendentes"]) == 1
    assert body["pendentes"][0]["id"] == _SOLIC
    assert len(body["registradas"]) == 1
    assert body["registradas"][0]["celula_id"] == _CELL
    assert body["registradas"][0]["celula_nova_id"] == _DEST_CELL
