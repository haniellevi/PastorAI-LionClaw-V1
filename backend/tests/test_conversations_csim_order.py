"""GET /conversations empurra CSIM/Fora da igreja pro final da lista (Missão 7B-3).

A suíte de routers roda offline com uma sessão FAKE (ver conftest): o mock NÃO
executa o SQL, então não dá para provar a ordenação "rodando" a query. O que
guardamos aqui é o mesmo nível de garantia que o projeto já aceita para regras
equivalentes (ver test_pipeline_csim.py): a chave de ordenação por
``pessoas.sem_interesse`` está compilada no ORDER BY, ANTES das demais chaves
(fila humana / última atualização) — então CSIM nunca fura a fila por estar
"aguardando" ou "recém atualizada".
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Conversation, RolePermission
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}


class _R:
    def __init__(self, *, scalar=None, scalars_list=None, rows=None) -> None:
        self._scalar = scalar
        self._scalars_list = scalars_list or []
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars_list))

    def all(self):
        return list(self._rows)


class InboxOrderSession:
    """Roteia auth (AppUser/RolePermission/UserRole) e captura o SQL da query
    de linhas de /conversations, pro assert de posição no ORDER BY."""

    def __init__(self, *, app_user, roles) -> None:
        self.app_user = app_user
        self.roles = roles
        self.rows_sql: list[str] = []

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        sql = str(statement)
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is RolePermission:
            return _R(rows=[])
        if "count(" in sql.lower() and "conversations" in sql.lower():
            return _R(scalar=0)
        if ent is Conversation:
            self.rows_sql.append(sql)
            return _R(rows=[])
        return _R(scalars_list=self.roles)  # projeção UserRole.papel

    def commit(self) -> None:  # pragma: no cover
        pass

    def close(self) -> None:  # pragma: no cover
        pass


def _wire(app, *, session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def test_list_conversations_orders_csim_last(app) -> None:
    session = InboxOrderSession(app_user=make_app_user(), roles=["admin"])
    client = _wire(app, session=session)

    resp = client.get("/conversations", headers=_AUTH)
    assert resp.status_code == 200

    # Exatamente uma query de linhas (a de contagem cai no branch de count acima).
    assert len(session.rows_sql) == 1
    sql = session.rows_sql[0]

    order_clause = sql.split("ORDER BY", 1)[1]
    assert "sem_interesse" in order_clause, order_clause

    # CSIM ordena ANTES de espera_desde/updated_at — sempre por último na lista,
    # independente de estar na fila humana ou ter mensagem recente.
    csim_pos = order_clause.lower().index("sem_interesse")
    espera_pos = order_clause.lower().index("espera_desde")
    updated_pos = order_clause.lower().index("updated_at")
    assert csim_pos < espera_pos < updated_pos, order_clause
