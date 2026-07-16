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
from sqlalchemy.sql import operators

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

    Registra em ``pessoa_sql`` o SQL compilado (texto) de toda query que toca
    ``pessoas`` (contagem e linhas), e em ``pessoa_statements`` o objeto
    ``Select`` REAL construído pelo endpoint — a mesma instância que o código
    de produção monta, ANTES de qualquer execução. Como o mock não roda o SQL
    contra um banco, ``pessoa_statements`` é o que permite inspecionar a
    árvore de cláusulas do WHERE (AND/OR reais) sem depender da lista fake de
    ``pessoas`` devolvida abaixo — essa lista fake NÃO prova filtragem, só
    exercita serialização (ver testes de ContactOut mais abaixo).
    """

    def __init__(self, *, app_user, roles, pessoas) -> None:
        self.app_user = app_user
        self.roles = roles
        self.pessoas = pessoas
        self.pessoa_sql: list[str] = []
        self.pessoa_statements: list = []

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
            self.pessoa_statements.append(statement)
            return _R(scalars=self.pessoas)
        if "count(" in sql.lower() and "pessoas" in sql.lower():  # contagem
            self.pessoa_sql.append(sql)
            self.pessoa_statements.append(statement)
            return _R(scalar=len(self.pessoas))
        # set_config (RLS) e projeção UserRole.papel caem aqui.
        return _R(scalars=self.roles)

    def commit(self) -> None:  # pragma: no cover
        pass

    def close(self) -> None:  # pragma: no cover
        pass


def _pessoa_ganhar(*, etapa="ganhar", tipo="contato", sem_interesse=False):
    return SimpleNamespace(
        id=_PID,
        nome="João Normal",
        telefone="+5589999991111",
        email=None,
        genero=None,
        tipo=tipo,
        etapa=etapa,
        subetapa="novo_contato",
        acompanhamento=None,
        sem_interesse=sem_interesse,
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


# ---------------------------------------------------------------------------
# PIPE-1: etapa NULL conta como "ganhar" (contato manual e convite nunca
# gravam etapa na criação — dashboard.overview já tratava NULL como "ganhar";
# GET /pipeline não tratava, e por isso essas pessoas somem da tela Ganhar).
# ---------------------------------------------------------------------------
def test_pipeline_ganhar_where_inclui_etapa_null(app) -> None:
    """Regressão: o WHERE de ?etapa=ganhar cobre etapa IS NULL, não só '='."""
    session = PipelineSession(
        app_user=make_app_user(), roles=["pastor"], pessoas=[_pessoa_ganhar()]
    )
    client = _wire(app, session=session)

    resp = client.get("/pipeline?etapa=ganhar", headers=_AUTH)
    assert resp.status_code == 200

    assert len(session.pessoa_sql) == 2  # contagem + linhas
    for sql in session.pessoa_sql:
        assert "IS NULL" in sql, sql
        assert "etapa" in sql, sql


def test_pipeline_outras_etapas_nao_incluem_null(app) -> None:
    """Regressão inversa: consolidar/discipular/enviar seguem com '=' estrito."""
    session = PipelineSession(
        app_user=make_app_user(),
        roles=["pastor"],
        pessoas=[_pessoa_ganhar(etapa="consolidar")],
    )
    client = _wire(app, session=session)

    resp = client.get("/pipeline?etapa=consolidar", headers=_AUTH)
    assert resp.status_code == 200

    assert len(session.pessoa_sql) == 2
    for sql in session.pessoa_sql:
        assert "IS NULL" not in sql, sql


def test_pipeline_contact_out_serializa_etapa_null_de_contato_manual(app) -> None:
    """ContactOut tolera etapa=None (contato manual — POST /contacts nunca grava etapa).

    NÃO prova o filtro WHERE: a FakeSession devolve ``pessoas`` sem avaliar o
    ``WHERE`` de fato (ver docstring de ``PipelineSession``). Isto exercita só a
    serialização de resposta — que ``ContactOut.etapa`` aceita/repassa ``None``
    sem quebrar. A prova de que o WHERE de fato inclui ``etapa IS NULL`` está em
    ``test_pipeline_ganhar_where_inclui_etapa_null`` e, estruturalmente, em
    ``test_pipeline_ganhar_where_sem_interesse_em_and_com_etapa_null_ou_ganhar``.
    """
    pessoa = _pessoa_ganhar(etapa=None, tipo="contato")
    session = PipelineSession(
        app_user=make_app_user(), roles=["pastor"], pessoas=[pessoa]
    )
    client = _wire(app, session=session)

    resp = client.get("/pipeline?etapa=ganhar", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body["items"]] == [_PID]
    assert body["items"][0]["etapa"] is None


def test_pipeline_contact_out_serializa_etapa_null_de_convite(app) -> None:
    """ContactOut tolera etapa=None (convite — auth.py cria Pessoa tipo=membro, sem etapa).

    Mesma ressalva de ``test_pipeline_contact_out_serializa_etapa_null_de_contato_manual``:
    isto NÃO prova o filtro WHERE, só que a serialização não quebra para uma
    Pessoa com ``tipo=membro`` e ``etapa=None`` (o shape do fluxo de convite).
    """
    pessoa = _pessoa_ganhar(etapa=None, tipo="membro")
    session = PipelineSession(
        app_user=make_app_user(), roles=["pastor"], pessoas=[pessoa]
    )
    client = _wire(app, session=session)

    resp = client.get("/pipeline?etapa=ganhar", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body["items"]] == [_PID]
    assert body["items"][0]["etapa"] is None
    assert body["items"][0]["tipo"] == "membro"


def test_pipeline_ganhar_where_sem_interesse_em_and_com_etapa_null_ou_ganhar(app) -> None:
    """Regressão estrutural: compila a Select REAL do endpoint (não a lista fake de
    ``pessoas``) e inspeciona a árvore de cláusulas do SQLAlchemy para provar que
    ``sem_interesse IS false`` fica em AND com o grupo ``(etapa IS NULL OR etapa =
    'ganhar')`` — nunca dentro do OR. Isso garante que uma Pessoa CSIM
    (``sem_interesse=True``) com ``etapa=None`` NÃO conta como Ganhar mesmo com o
    OR de etapa adicionado pelo fix de PIPE-1; sem essa garantia estrutural, um
    operator-precedence bug poderia deixar o OR "engolir" a exclusão de CSIM.

    A pessoa usada aqui tem ``sem_interesse=True`` propositalmente (cenário do
    achado da revisão externa da PR#178) — mas o que prova a regra é a estrutura
    do WHERE compilado, não o que a FakeSession devolve como linha.
    """
    pessoa = _pessoa_ganhar(etapa=None, sem_interesse=True)
    session = PipelineSession(
        app_user=make_app_user(), roles=["pastor"], pessoas=[pessoa]
    )
    client = _wire(app, session=session)

    resp = client.get("/pipeline?etapa=ganhar", headers=_AUTH)
    assert resp.status_code == 200

    assert len(session.pessoa_statements) == 2  # contagem + linhas
    for stmt in session.pessoa_statements:
        where = stmt.whereclause
        assert where is not None, stmt
        assert where.operator is operators.and_, (
            "topo do WHERE deixou de ser AND",
            str(stmt),
        )
        top_clauses = list(where.clauses)
        assert len(top_clauses) == 2, top_clauses

        def _sql(clause):
            return str(clause.compile(compile_kwargs={"literal_binds": True}))

        sem_interesse_clauses = [c for c in top_clauses if "sem_interesse" in _sql(c)]
        etapa_clauses = [c for c in top_clauses if "etapa" in _sql(c)]
        assert len(sem_interesse_clauses) == 1, top_clauses
        assert len(etapa_clauses) == 1, top_clauses

        # sem_interesse segue exigindo false e NÃO está dentro do grupo OR de etapa.
        sem_interesse_sql = _sql(sem_interesse_clauses[0])
        assert "sem_interesse IS false" in sem_interesse_sql, sem_interesse_sql
        assert "OR" not in sem_interesse_sql, sem_interesse_sql

        # etapa: um único grupo OR(etapa IS NULL, etapa = 'ganhar'), em AND
        # (não OR) com sem_interesse.
        etapa_sql = _sql(etapa_clauses[0])
        assert etapa_sql.startswith("("), etapa_sql
        assert "etapa IS NULL" in etapa_sql, etapa_sql
        assert "etapa = 'ganhar'" in etapa_sql, etapa_sql
        assert " OR " in etapa_sql, etapa_sql
