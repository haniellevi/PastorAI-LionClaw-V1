"""Isolamento de tenant na deduplicação de contatos por telefone (MEDIO-004).

As buscas por sufixo de telefone em POST /contacts (dedupe) e PATCH
/contacts/{id} (colisão) devem filtrar `Pessoa.igreja_id` explicitamente —
regra de ouro do projeto: nunca depender só da RLS.

Como toda a suíte roda sem Postgres, o fake de sessão daqui NÃO adivinha o que
a query filtra: ele compila o `Select` real e aplica o filtro de `igreja_id`
que estiver de fato no WHERE (mesmo idioma de `_plano_query_filters` no
conftest). Se uma regressão remover `Pessoa.igreja_id == ...` do router, o
fake devolve pessoas de OUTRA igreja e os asserts abaixo quebram.
"""

from __future__ import annotations

import re
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Celula, Pessoa
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

# Tenant do usuário autenticado (igreja de make_app_user) e um tenant vizinho.
_IGREJA_A = "00000000-0000-0000-0000-000000000001"
_IGREJA_B = "00000000-0000-0000-0000-000000000002"

_PID_A = "00000000-0000-0000-0000-0000000000b1"
_PID_A2 = "00000000-0000-0000-0000-0000000000b2"
_PID_B = "00000000-0000-0000-0000-0000000000b9"

_AUTH = {"Authorization": "Bearer good"}

_IGREJA_EQ = re.compile(r"pessoas\.igreja_id = :(\w+)")
_ID_EQ = re.compile(r"pessoas\.id = :(\w+)")
_ID_NE = re.compile(r"pessoas\.id != :(\w+)")


class _R:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class DedupSession:
    """Fake de sessão que aplica os filtros REAIS do WHERE nas selects de Pessoa."""

    def __init__(self, *, app_user, roles, pessoas) -> None:
        self.app_user = app_user
        self.roles = roles
        self.pessoas = list(pessoas)
        self.added: list = []
        self.committed = False

    def _pessoa_result(self, statement) -> _R:
        compiled = statement.compile()
        sql = str(compiled)
        params = compiled.params
        rows = list(self.pessoas)
        m = _IGREJA_EQ.search(sql)
        if m:
            wanted = str(params[m.group(1)])
            rows = [p for p in rows if str(p.igreja_id) == wanted]
        m = _ID_EQ.search(sql)
        if m:
            wanted = str(params[m.group(1)])
            rows = [p for p in rows if str(p.id) == wanted]
        m = _ID_NE.search(sql)
        if m:
            excluded = str(params[m.group(1)])
            rows = [p for p in rows if str(p.id) != excluded]
        return _R(scalar=rows[0] if rows else None, scalars=rows)

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is Celula:
            return _R(scalar=None)
        if ent is Pessoa:
            return self._pessoa_result(statement)
        return _R(scalars=self.roles)

    def add(self, obj) -> None:
        self.added.append(obj)

    def begin_nested(self):
        # UNIQ-PESSOA-1: INSERT roda num SAVEPOINT; sem corrida na fake é no-op.
        from contextlib import nullcontext

        return nullcontext()

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        # Simula os server defaults que um flush real aplicaria.
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "presencas_celula", None) is None:
            obj.presencas_celula = 0
        if getattr(obj, "aceitou_jesus", None) is None:
            obj.aceitou_jesus = False

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


def make_pessoa(*, pessoa_id, igreja_id, telefone, nome="Pessoa"):
    return SimpleNamespace(
        id=pessoa_id,
        igreja_id=igreja_id,
        nome=nome,
        telefone=telefone,
        email=None,
        genero=None,
        tipo="membro",
        etapa=None,
        subetapa=None,
        acompanhamento=None,
        sem_interesse=False,
        sem_interesse_motivo=None,
        faixa_etaria=None,
        endereco=None,
        presencas_celula=0,
        aceitou_jesus=False,
        celula_id=None,
        lider_id=None,
        apto_lider=False,
    )


def _wire(app, *, session, clerk) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /contacts — dedupe
# ---------------------------------------------------------------------------
def test_create_dedupes_only_within_current_tenant(app) -> None:
    """Mesmo telefone em duas igrejas → dedupe encontra só a Pessoa do tenant A.

    A pessoa da igreja B vem PRIMEIRO na lista: sem o filtro de igreja_id no
    WHERE, o dedupe casaria com ela e o id retornado seria o da igreja B.
    """
    telefone = "+5511988887777"
    pessoa_b = make_pessoa(pessoa_id=_PID_B, igreja_id=_IGREJA_B, telefone=telefone)
    pessoa_a = make_pessoa(pessoa_id=_PID_A, igreja_id=_IGREJA_A, telefone=telefone)
    session = DedupSession(
        app_user=make_app_user(), roles=["admin"], pessoas=[pessoa_b, pessoa_a]
    )
    client = _wire(app, session=session, clerk=FakeClerk())

    resp = client.post(
        "/contacts", headers=_AUTH, json={"nome": "Novo", "telefone": telefone}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["deduped"] is True
    assert body["contact"]["id"] == _PID_A
    assert session.added == []  # nada criado no dedupe


def test_create_does_not_dedupe_against_other_tenant(app) -> None:
    """Telefone existe SÓ na igreja B → não deduplica; cria normalmente na A."""
    telefone = "+5511988887777"
    pessoa_b = make_pessoa(pessoa_id=_PID_B, igreja_id=_IGREJA_B, telefone=telefone)
    session = DedupSession(
        app_user=make_app_user(), roles=["admin"], pessoas=[pessoa_b]
    )
    client = _wire(app, session=session, clerk=FakeClerk())

    resp = client.post(
        "/contacts", headers=_AUTH, json={"nome": "Novo", "telefone": telefone}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["deduped"] is False
    assert body["contact"]["id"] != _PID_B
    assert len(session.added) == 1
    assert str(session.added[0].igreja_id) == _IGREJA_A
    assert session.committed is True


# ---------------------------------------------------------------------------
# PATCH /contacts/{id} — colisão de telefone
# ---------------------------------------------------------------------------
def test_update_phone_ignores_collision_in_other_tenant(app) -> None:
    """Telefone novo colide só com pessoa da igreja B → atualiza normalmente."""
    novo_telefone = "+5511977776666"
    pessoa_a = make_pessoa(
        pessoa_id=_PID_A, igreja_id=_IGREJA_A, telefone="+5511988887777"
    )
    pessoa_b = make_pessoa(
        pessoa_id=_PID_B, igreja_id=_IGREJA_B, telefone=novo_telefone
    )
    session = DedupSession(
        app_user=make_app_user(), roles=["admin"], pessoas=[pessoa_a, pessoa_b]
    )
    client = _wire(app, session=session, clerk=FakeClerk())

    resp = client.patch(
        f"/contacts/{_PID_A}", headers=_AUTH, json={"telefone": novo_telefone}
    )
    assert resp.status_code == 200
    assert pessoa_a.telefone == novo_telefone
    assert session.committed is True


def test_update_phone_still_conflicts_within_tenant(app) -> None:
    """Guarda de não-regressão: colisão com OUTRA pessoa da MESMA igreja → 409."""
    novo_telefone = "+5511977776666"
    pessoa_a = make_pessoa(
        pessoa_id=_PID_A, igreja_id=_IGREJA_A, telefone="+5511988887777"
    )
    pessoa_a2 = make_pessoa(
        pessoa_id=_PID_A2, igreja_id=_IGREJA_A, telefone=novo_telefone
    )
    session = DedupSession(
        app_user=make_app_user(), roles=["admin"], pessoas=[pessoa_a, pessoa_a2]
    )
    client = _wire(app, session=session, clerk=FakeClerk())

    resp = client.patch(
        f"/contacts/{_PID_A}", headers=_AUTH, json={"telefone": novo_telefone}
    )
    assert resp.status_code == 409
    assert pessoa_a.telefone == "+5511988887777"


# ---------------------------------------------------------------------------
# Prova estrutural: o WHERE das duas queries carrega o filtro de igreja_id
# ---------------------------------------------------------------------------
def test_dedupe_queries_filter_igreja_id_in_where(app) -> None:
    """As selects de Pessoa por sufixo de telefone incluem pessoas.igreja_id."""
    captured: list[str] = []

    class SpySession(DedupSession):
        def _pessoa_result(self, statement) -> _R:
            captured.append(str(statement.compile()))
            return super()._pessoa_result(statement)

    telefone = "+5511988887777"
    pessoa_a = make_pessoa(pessoa_id=_PID_A, igreja_id=_IGREJA_A, telefone=telefone)
    session = SpySession(
        app_user=make_app_user(), roles=["admin"], pessoas=[pessoa_a]
    )
    client = _wire(app, session=session, clerk=FakeClerk())

    resp = client.post(
        "/contacts", headers=_AUTH, json={"nome": "Novo", "telefone": telefone}
    )
    assert resp.status_code == 200

    resp = client.patch(
        f"/contacts/{_PID_A}", headers=_AUTH, json={"telefone": "+5511977776666"}
    )
    assert resp.status_code == 200

    suffix_queries = [sql for sql in captured if "regexp_replace" in sql]
    assert len(suffix_queries) == 2  # dedupe do create + colisão do update
    for sql in suffix_queries:
        assert _IGREJA_EQ.search(sql), sql
