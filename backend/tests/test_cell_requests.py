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
    UserRole,
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
        accesses=None,
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
        self.accesses = list(accesses) if accesses is not None else [
            SimpleNamespace(
                id=uuid.uuid5(uuid.NAMESPACE_URL, f"access:{p.id}"),
                igreja_id=uuid.UUID(_TENANT),
                pessoa_id=p.id,
                clerk_user_id=f"clerk_{p.id}",
                status="ativo",
            )
            for p in self.pessoas
        ]
        self.role_rows: list = []
        self.added: list = []
        self.deleted: list = []
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
            eqs, _ins = self._preds(statement)
            if "clerk_user_id" in eqs:
                return _Res(scalar=self.app_user)
            rows = self._filter(self.accesses, statement)
            if name == "id":
                ids = [row.id for row in rows]
                return _Res(scalar=(ids[0] if ids else None), scalars=ids)
            return _Res(scalar=(rows[0] if rows else None), scalars=rows)
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
        if ent is UserRole and name == "papel":
            return _Res(scalars=self.roles)
        if ent is UserRole:
            rows = self._filter(self.role_rows, statement)
            return _Res(scalar=(rows[0] if rows else None), scalars=rows)
        # set_config text.
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
        elif isinstance(obj, UserRole):
            self.role_rows.append(obj)

    def delete(self, obj) -> None:
        self.deleted.append(obj)
        if obj in self.role_rows:
            self.role_rows.remove(obj)

    def flush(self) -> None:
        pass

    def refresh(self, obj, **_kwargs) -> None:
        # Aceita with_for_update=... (SEC-4B: approve() trava a linha antes de
        # revalidar). Sem Postgres real não há lock — o objeto já está "vivo".
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
    ativo: bool = True,
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
        ativo=ativo,
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


def make_pessoa(
    pessoa_id: str,
    nome: str = "Pessoa",
    celula_id: str | None = _CELL,
    *,
    apto_lider: bool = True,
    sem_interesse: bool = False,
    tipo: str | None = None,
    telefone: str | None = None,
):
    return SimpleNamespace(
        id=pessoa_id,
        nome=nome,
        igreja_id=_TENANT,
        celula_id=celula_id,
        lider_id=None,
        apto_lider=apto_lider,
        sem_interesse=sem_interesse,
        tipo=tipo,
        telefone=telefone,
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


def test_create_transferir_membro_blocked_403(app) -> None:
    # M7B-W1.3: transferência/remoção de membro não parte da tela do líder — a
    # gestão de membros é da Central. Barrado no backend (fecha bypass direto).
    session = _leader_session()
    resp = _wire(app, session=session).post(
        "/cell-requests",
        headers=_AUTH,
        json={"celula_id": _CELL, "tipo": "transferir_membro",
              "payload_proposto": {"pessoa_id": _MEMBER, "celula_destino_id": _DEST_CELL}},
    )
    assert resp.status_code == 403, resp.text
    assert "Central" in resp.json()["detail"]
    assert session.solicitacoes == []  # nada criado


def test_create_remover_membro_blocked_403(app) -> None:
    session = _leader_session()
    resp = _wire(app, session=session).post(
        "/cell-requests",
        headers=_AUTH,
        json={"celula_id": _CELL, "tipo": "remover_membro",
              "payload_proposto": {"pessoa_id": _MEMBER}},
    )
    assert resp.status_code == 403, resp.text
    assert session.solicitacoes == []


def test_resubmit_membro_tipo_blocked_403(app) -> None:
    # Reenvio de solicitação de membro legada (ajuste_solicitado) também é barrado.
    solic = make_solicitacao(
        tipo="remover_membro", status="ajuste_solicitado", pessoa_id=_MEMBER,
        payload_proposto={"pessoa_id": _MEMBER},
    )
    session = _leader_session(solicitacoes=[solic])
    resp = _wire(app, session=session).put(
        f"/cell-requests/{_SOLIC}/resubmit",
        headers=_AUTH,
        json={"payload_proposto": {"pessoa_id": _MEMBER}},
    )
    assert resp.status_code == 403, resp.text


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


def test_approve_rejects_stale_origin_leadership_under_lock(app) -> None:
    solic = make_solicitacao(
        tipo="alterar_dia",
        status="aguardando",
        solicitante_id=_LEADER,
        payload_proposto={"dia_reuniao": "sexta"},
    )
    cell = make_cell(lider_id=_OUTSIDER, dia_reuniao="quinta")
    session = _central_session(cells=[cell], solicitacoes=[solic])

    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve", headers=_AUTH, json={}
    )

    assert resp.status_code == 409
    assert cell.dia_reuniao == "quinta"
    assert solic.status == "aguardando"
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


def test_resubmit_rejects_when_author_is_no_longer_active_cell_leader(app) -> None:
    solic = make_solicitacao(
        status="ajuste_solicitado", solicitante_id=_LEADER
    )
    session = _leader_session(
        cells=[make_cell(lider_id=_OUTSIDER)], solicitacoes=[solic]
    )

    resp = _wire(app, session=session).put(
        f"/cell-requests/{_SOLIC}/resubmit",
        headers=_AUTH,
        json={"payload_proposto": {"dia_reuniao": "sabado"}},
    )

    assert resp.status_code == 409
    assert solic.status == "ajuste_solicitado"
    assert session.committed is False


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


def test_approve_multiplication_leader_is_not_a_member(app) -> None:
    # M7B-W1.2: novo_lider_id está na lista de transferidos (interno à origem).
    # Ele deve virar LÍDER da nova (celulas.lider_id), NUNCA membro dela — sem
    # CelulaMembro ativo na nova; espelho de membresia limpo. Os demais viram
    # membros ativos. A multiplicação conclui normalmente.
    session = _multiplication_session()  # novo_lider=_MEMBER ∈ [_MEMBER, _MEMBER2]
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

    nova = next(c for c in session.cells if str(c.id) != _CELL)
    assert str(nova.lider_id) == _MEMBER  # é o LÍDER da nova
    membros_novos = [
        o for o in session.added
        if isinstance(o, CelulaMembro) and str(o.celula_id) == str(nova.id)
    ]
    pessoas_com_vinculo = {str(m.pessoa_id) for m in membros_novos}
    assert _MEMBER not in pessoas_com_vinculo   # líder NÃO é membro da nova
    assert _MEMBER2 in pessoas_com_vinculo      # discípulo transferido é membro
    # Espelho: líder sem célula (lidera, não é membro); discípulo aponta pra nova.
    lider = next(p for p in session.pessoas if str(p.id) == _MEMBER)
    membro2 = next(p for p in session.pessoas if str(p.id) == _MEMBER2)
    assert lider.celula_id is None
    assert str(membro2.celula_id) == str(nova.id)
    # Ambos os vínculos de ORIGEM foram desativados.
    assert all(
        m.ativo is False for m in session.membros if str(m.celula_id) == _CELL
    )


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


# ---- elegibilidade do novo líder (regra 2026-07-06) ------------------------
def _approve(app, session):
    session.solicitacoes = [
        make_solicitacao(
            tipo="multiplicacao", status="aguardando",
            payload_proposto=_multiplication_payload(with_key=True),
        )
    ]
    return _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve",
        headers=_AUTH,
        json={"idempotency_key": "mult-key-1"},
    )


def test_approve_multiplication_rejects_nao_apto_422(app) -> None:
    session = _multiplication_session()
    for p in session.pessoas:
        if str(p.id) == _MEMBER:
            p.apto_lider = False
    resp = _approve(app, session)
    assert resp.status_code == 422
    assert "Reencontro" in resp.json()["detail"]
    assert len(session.cells) == 1  # nada criado


def test_approve_multiplication_rejects_csim_422(app) -> None:
    session = _multiplication_session()
    for p in session.pessoas:
        if str(p.id) == _MEMBER:
            p.sem_interesse = True
    resp = _approve(app, session)
    assert resp.status_code == 422
    # FECH-07/ROTULO-1: rótulo visível é "fora da igreja" (valor técnico
    # sem_interesse/CSIM inalterado no modelo).
    assert "fora da igreja" in resp.json()["detail"]


def test_approve_multiplication_rejects_ja_lidera_409(app) -> None:
    # Novo líder já lidera OUTRA célula ativa → conflito.
    session = _multiplication_session()
    session.cells.append(make_cell(cell_id=_DEST_CELL, lider_id=_MEMBER))
    resp = _approve(app, session)
    assert resp.status_code == 409
    assert "já lidera" in resp.json()["detail"]


def test_approve_transfer_promotes_contato_and_creates_binding(app) -> None:
    # M7B-W1.2: transferir_membro aprovado cria vínculo ativo na destino, sincroniza
    # o espelho e PROMOVE tipo (contato → membro) — invariante vínculo ativo ⇒ membro.
    dest = make_cell(cell_id=_DEST_CELL, lider_id=_LEADER)
    pessoa = make_pessoa(_MEMBER, "Discípulo", celula_id=_CELL, tipo="contato")
    session = _central_session(
        cells=[make_cell(lider_id=_LEADER), dest],
        membros=[make_membro(pessoa_id=_MEMBER, celula_id=_CELL)],
        pessoas=[
            make_pessoa(_LEADER, "Líder"),
            make_pessoa(_PASTOR, "Pastor Central"),
            pessoa,
        ],
        solicitacoes=[
            make_solicitacao(
                tipo="transferir_membro",
                status="aguardando",
                payload_proposto={
                    "pessoa_id": _MEMBER,
                    "celula_destino_id": _DEST_CELL,
                },
            )
        ],
    )
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve", headers=_AUTH, json={}
    )
    assert resp.status_code == 200, resp.text
    assert pessoa.tipo == "membro"  # promovido
    assert str(pessoa.celula_id) == _DEST_CELL
    novos = [
        o for o in session.added
        if isinstance(o, CelulaMembro) and str(o.celula_id) == _DEST_CELL
    ]
    assert any(str(m.pessoa_id) == _MEMBER for m in novos)


def test_approve_transfer_rejects_pastor_409(app) -> None:
    # M7B-W1.2: aprovar transferência de um PASTOR cria vínculo ativo de membro
    # (6º ponto de escrita de celula_membro, fora do seam) — agora guardado.
    dest = make_cell(cell_id=_DEST_CELL, lider_id=_LEADER)
    pastor = make_pessoa(_MEMBER, "Pastor", celula_id=None, tipo="pastor")
    session = _central_session(
        cells=[make_cell(lider_id=_LEADER), dest],
        pessoas=[
            make_pessoa(_LEADER, "Líder"),
            make_pessoa(_PASTOR, "Pastor Central"),
            pastor,
        ],
        solicitacoes=[
            make_solicitacao(
                tipo="transferir_membro",
                status="aguardando",
                payload_proposto={
                    "pessoa_id": _MEMBER,
                    "celula_destino_id": _DEST_CELL,
                },
            )
        ],
    )
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve", headers=_AUTH, json={}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "pastor_nao_pode_ser_membro"
    assert not any(isinstance(o, CelulaMembro) for o in session.added)


def test_approve_transfer_rejects_inactive_destination(app) -> None:
    pessoa = make_pessoa(_MEMBER, "Discípulo", celula_id=_CELL, tipo="membro")
    session = _central_session(
        cells=[
            make_cell(lider_id=_LEADER),
            make_cell(cell_id=_DEST_CELL, lider_id=None, ativo=False),
        ],
        membros=[make_membro(pessoa_id=_MEMBER, celula_id=_CELL)],
        pessoas=[
            make_pessoa(_LEADER, "Líder"),
            make_pessoa(_PASTOR, "Pastor Central"),
            pessoa,
        ],
        solicitacoes=[
            make_solicitacao(
                tipo="transferir_membro",
                payload_proposto={
                    "pessoa_id": _MEMBER,
                    "celula_destino_id": _DEST_CELL,
                },
            )
        ],
    )

    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve", headers=_AUTH, json={}
    )

    assert resp.status_code == 409
    assert pessoa.celula_id == _CELL


def test_approve_transfer_rejects_stale_source_membership(app) -> None:
    stale_cell = "00000000-0000-0000-0000-0000000000e9"
    pessoa = make_pessoa(_MEMBER, "Discípulo", celula_id=stale_cell, tipo="membro")
    session = _central_session(
        cells=[make_cell(), make_cell(cell_id=_DEST_CELL)],
        membros=[make_membro(pessoa_id=_MEMBER, celula_id=stale_cell)],
        pessoas=[
            make_pessoa(_LEADER, "Líder"),
            make_pessoa(_PASTOR, "Pastor Central"),
            pessoa,
        ],
        solicitacoes=[
            make_solicitacao(
                tipo="transferir_membro",
                payload_proposto={
                    "pessoa_id": _MEMBER,
                    "celula_destino_id": _DEST_CELL,
                },
            )
        ],
    )

    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve", headers=_AUTH, json={}
    )

    assert resp.status_code == 409
    assert not any(
        isinstance(obj, CelulaMembro) and str(obj.celula_id) == _DEST_CELL
        for obj in session.added
    )


def test_approve_remove_rejects_stale_source_membership(app) -> None:
    stale_cell = "00000000-0000-0000-0000-0000000000e9"
    pessoa = make_pessoa(_MEMBER, "Discípulo", celula_id=stale_cell, tipo="membro")
    membership = make_membro(pessoa_id=_MEMBER, celula_id=stale_cell)
    session = _central_session(
        cells=[make_cell()],
        membros=[membership],
        pessoas=[
            make_pessoa(_LEADER, "Líder"),
            make_pessoa(_PASTOR, "Pastor Central"),
            pessoa,
        ],
        solicitacoes=[
            make_solicitacao(
                tipo="remover_membro",
                payload_proposto={"pessoa_id": _MEMBER},
            )
        ],
    )

    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve", headers=_AUTH, json={}
    )

    assert resp.status_code == 409
    assert membership.ativo is True
    assert pessoa.celula_id == stale_cell


def test_approve_multiplication_accepts_external_leader(app) -> None:
    # Apto sem célula, EXTERNO à origem: vira lider_id da nova célula SEM ganhar
    # vínculo em celula_membro (liderança é celulas.lider_id; enum não tem 'lider').
    session = _multiplication_session()
    externo = make_pessoa(_OUTSIDER, "Apto Sem Célula", celula_id=None)
    session.pessoas.append(externo)
    session.accesses.append(
        SimpleNamespace(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"access:{_OUTSIDER}"),
            igreja_id=uuid.UUID(_TENANT),
            pessoa_id=_OUTSIDER,
            clerk_user_id="clerk_outsider",
            status="ativo",
        )
    )
    payload = _multiplication_payload(with_key=True)
    payload["novo_lider_id"] = _OUTSIDER
    payload["membros_transferidos_ids"] = [_MEMBER, _MEMBER2]
    session.solicitacoes = [
        make_solicitacao(
            tipo="multiplicacao", status="aguardando", payload_proposto=payload
        )
    ]
    resp = _wire(app, session=session).post(
        f"/cell-requests/{_SOLIC}/approve",
        headers=_AUTH,
        json={"idempotency_key": "mult-key-1"},
    )
    assert resp.status_code == 200, resp.text
    nova = [c for c in session.cells if str(c.id) != _CELL]
    assert len(nova) == 1
    assert str(nova[0].lider_id) == _OUTSIDER
    vinculos = [o for o in session.added if isinstance(o, CelulaMembro)]
    assert {str(v.pessoa_id) for v in vinculos} == {_MEMBER, _MEMBER2}
    assert all(v.papel == "membro" for v in vinculos)  # nunca 'lider' (bug fix)
    assert externo.celula_id is None  # espelho do externo não muda


def test_multiplicacao_payload_allows_external_leader() -> None:
    # Validador estrutural não exige mais novo_lider_id ∈ membros_transferidos.
    from app.domain.cell_requests import MultiplicacaoPayload

    p = MultiplicacaoPayload(
        nome_nova_celula="Célula Filha",
        novo_lider_id=uuid.UUID(_OUTSIDER),
        membros_transferidos_ids=[uuid.UUID(_MEMBER)],
    )
    assert p.novo_lider_id not in p.membros_transferidos_ids


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
