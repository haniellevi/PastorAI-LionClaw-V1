"""GET /pipeline exclui CSIM da Visão/Jornada G12 (fecha dívida do PR #103).

A suíte de routers roda offline com uma sessão FAKE (ver conftest): o mock NÃO
executa o SQL, então não dá para provar a exclusão "rodando" a query. O que
guardamos aqui é o que de fato importa e regride se alguém remover o filtro: que
a condição ``pessoas.sem_interesse IS false`` está compilada no WHERE das DUAS
queries do endpoint (contagem + linhas), com e sem o parâmetro ``etapa``. É o
mesmo nível de garantia que o projeto já aceita para o filtro equivalente em
``dashboard.overview`` (cujo SQL também não é exercido por teste). Além disso
exercemos o caminho feliz: uma pessoa normal em "ganhar" segue retornando.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Celula, Pessoa
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_PID = "00000000-0000-0000-0000-0000000000d1"


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


class PipelineSession:
    """Roteia auth (AppUser/UserRole) + as queries de Pessoa/Celula do endpoint.

    Registra em ``pessoa_sql`` o SQL compilado de toda query que toca ``pessoas``
    (contagem e linhas) para as asserções do filtro CSIM.
    """

    def __init__(self, *, app_user, roles, pessoas) -> None:
        self.app_user = app_user
        self.roles = roles
        self.pessoas = pessoas
        self.pessoa_sql: list[str] = []

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        sql = str(statement)
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is Celula:  # _active_leader_ids: nenhum líder ativo no tenant
            return _R(scalars=[])
        if ent is Pessoa:  # query de linhas: select(Pessoa)
            self.pessoa_sql.append(sql)
            return _R(scalars=self.pessoas)
        if "count(" in sql.lower() and "pessoas" in sql.lower():  # contagem
            self.pessoa_sql.append(sql)
            return _R(scalar=len(self.pessoas))
        # set_config (RLS) e projeção UserRole.papel caem aqui.
        return _R(scalars=self.roles)

    def commit(self) -> None:  # pragma: no cover
        pass

    def close(self) -> None:  # pragma: no cover
        pass


def _pessoa_ganhar():
    return SimpleNamespace(
        id=_PID,
        nome="João Normal",
        telefone="+5589999991111",
        email=None,
        genero=None,
        tipo="contato",
        etapa="ganhar",
        subetapa="novo_contato",
        acompanhamento=None,
        sem_interesse=False,
        sem_interesse_motivo=None,
        presencas_celula=0,
        aceitou_jesus=False,
        celula_id=None,
        lider_id=None,
        apto_lider=False,
        created_at=None,
    )


def _wire(app, *, session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def test_pipeline_ganhar_exclui_csim_no_where(app) -> None:
    """?etapa=ganhar: WHERE de contagem E linhas exclui sem_interesse + filtra etapa."""
    session = PipelineSession(
        app_user=make_app_user(), roles=["pastor"], pessoas=[_pessoa_ganhar()]
    )
    client = _wire(app, session=session)

    resp = client.get("/pipeline?etapa=ganhar", headers=_AUTH)
    assert resp.status_code == 200

    # Caminho feliz: a pessoa normal em "ganhar" continua retornando.
    body = resp.json()
    assert [item["id"] for item in body["items"]] == [_PID]
    assert body["items"][0]["etapa"] == "ganhar"

    # Regressão: as DUAS queries de pessoas carregam a exclusão de CSIM + etapa.
    assert len(session.pessoa_sql) == 2  # contagem + linhas
    for sql in session.pessoa_sql:
        assert "sem_interesse" in sql, sql
        assert "etapa" in sql, sql


def test_pipeline_sem_etapa_ainda_exclui_csim(app) -> None:
    """Sem ?etapa a exclusão de CSIM continua (regra vale para todo o pipeline)."""
    session = PipelineSession(
        app_user=make_app_user(), roles=["pastor"], pessoas=[_pessoa_ganhar()]
    )
    client = _wire(app, session=session)

    resp = client.get("/pipeline", headers=_AUTH)
    assert resp.status_code == 200

    assert len(session.pessoa_sql) == 2
    for sql in session.pessoa_sql:
        assert "sem_interesse" in sql, sql
