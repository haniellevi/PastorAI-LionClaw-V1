"""Tenant and account-state gates for POST /pipeline/assign-consolidador."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.models import AppUser, Consolidacao
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user


_AUTH = {"Authorization": "Bearer good"}
_IGREJA_ID = "00000000-0000-0000-0000-000000000001"
_OTHER_IGREJA_ID = "00000000-0000-0000-0000-000000000002"
_ACTOR_ID = "00000000-0000-0000-0000-0000000000a1"
_RESPONSAVEL_ID = "00000000-0000-0000-0000-0000000000b1"
_CONSOLIDACAO_ID = "00000000-0000-0000-0000-0000000000c1"


class _Result:
    def __init__(self, scalar=None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


def _compiled(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True})).lower()


class AssignSession:
    def __init__(self, *, consolidacao, responsavel) -> None:
        self.consolidacao = consolidacao
        self.responsavel = responsavel
        self.consolidacao_statements: list = []
        self.responsavel_statements: list = []
        self.flushes = 0
        self.refreshes = 0
        self.commits = 0

    def execute(self, statement, params=None) -> _Result:
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entity = descriptions[0].get("entity") if descriptions else None
        sql = _compiled(statement)

        if entity is Consolidacao:
            self.consolidacao_statements.append(statement)
            row = self.consolidacao
            if (
                row is not None
                and "consolidacoes.igreja_id" in sql
                and str(row.igreja_id) != _IGREJA_ID
            ):
                row = None
            return _Result(row)

        if entity is AppUser:
            self.responsavel_statements.append(statement)
            row = self.responsavel
            if (
                row is not None
                and "app_users.igreja_id" in sql
                and str(row.igreja_id) != _IGREJA_ID
            ):
                row = None
            if (
                row is not None
                and "app_users.status is null" in sql
                and "app_users.status = 'ativo'" in sql
                and row.status not in (None, "ativo")
            ):
                row = None
            return _Result(row)

        raise AssertionError(f"consulta inesperada: {sql}")

    def flush(self) -> None:
        self.flushes += 1

    def refresh(self, obj) -> None:
        self.refreshes += 1

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:  # pragma: no cover
        pass


def _consolidacao(*, igreja_id=_IGREJA_ID):
    return SimpleNamespace(
        id=uuid.UUID(_CONSOLIDACAO_ID),
        igreja_id=uuid.UUID(igreja_id),
        responsavel_id=None,
    )


def _responsavel(
    *,
    igreja_id=_IGREJA_ID,
    user_status: str | None = "ativo",
    roles=(),
):
    return SimpleNamespace(
        id=uuid.UUID(_RESPONSAVEL_ID),
        igreja_id=uuid.UUID(igreja_id),
        status=user_status,
        roles=[SimpleNamespace(papel=role) for role in roles],
    )


def _current_user() -> CurrentUser:
    return CurrentUser(
        app_user_id=_ACTOR_ID,
        clerk_user_id="clerk_assign",
        igreja_id=_IGREJA_ID,
        email="pastor@igrejapiloto.com.br",
        nome="Pastor",
        roles=frozenset({"pastor"}),
    )


def _client(app, *, session: AssignSession) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


def _post(client: TestClient):
    return client.post(
        "/pipeline/assign-consolidador",
        headers=_AUTH,
        json={
            "consolidacaoId": _CONSOLIDACAO_ID,
            "responsavelId": _RESPONSAVEL_ID,
        },
    )


def _assert_consolidacao_tenant_filter(statement) -> None:
    sql = _compiled(statement)
    assert "consolidacoes.id" in sql, sql
    assert "consolidacoes.igreja_id" in sql, sql
    assert uuid.UUID(_IGREJA_ID).hex in sql, sql


def _assert_responsavel_filters(statement) -> None:
    sql = _compiled(statement)
    assert "app_users.id" in sql, sql
    assert "app_users.igreja_id" in sql, sql
    assert "app_users.status is null" in sql, sql
    assert "app_users.status = 'ativo'" in sql, sql
    assert " or " in sql, sql
    assert uuid.UUID(_IGREJA_ID).hex in sql, sql


@pytest.mark.parametrize(
    ("user_status", "roles"),
    [
        (None, ("membro",)),
        ("ativo", ("membro", "lider_celula")),
        ("ativo", ()),
    ],
)
def test_active_or_legacy_tenant_user_can_be_assigned_regardless_of_roles(
    app, user_status, roles
) -> None:
    consolidacao = _consolidacao()
    responsavel = _responsavel(user_status=user_status, roles=roles)
    session = AssignSession(consolidacao=consolidacao, responsavel=responsavel)
    client = _client(app, session=session)

    response = _post(client)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "assigned",
        "consolidacaoId": _CONSOLIDACAO_ID,
        "responsavelId": _RESPONSAVEL_ID,
    }
    assert consolidacao.responsavel_id == uuid.UUID(_RESPONSAVEL_ID)
    assert len(session.consolidacao_statements) == 1
    assert len(session.responsavel_statements) == 1
    _assert_consolidacao_tenant_filter(session.consolidacao_statements[0])
    _assert_responsavel_filters(session.responsavel_statements[0])
    assert session.flushes == 1
    assert session.refreshes == 1
    assert session.commits == 1


@pytest.mark.parametrize("user_status", ["revogado", "convidado"])
def test_non_active_responsavel_is_404_before_mutation(app, user_status) -> None:
    consolidacao = _consolidacao()
    session = AssignSession(
        consolidacao=consolidacao,
        responsavel=_responsavel(user_status=user_status),
    )
    client = _client(app, session=session)

    response = _post(client)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Responsável não encontrado"
    assert len(session.consolidacao_statements) == 1
    assert len(session.responsavel_statements) == 1
    _assert_responsavel_filters(session.responsavel_statements[0])
    assert consolidacao.responsavel_id is None
    assert session.flushes == 0
    assert session.refreshes == 0
    assert session.commits == 0


def test_cross_tenant_responsavel_uuid_is_404_before_mutation(app) -> None:
    consolidacao = _consolidacao()
    session = AssignSession(
        consolidacao=consolidacao,
        responsavel=_responsavel(igreja_id=_OTHER_IGREJA_ID),
    )
    client = _client(app, session=session)

    response = _post(client)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Responsável não encontrado"
    _assert_responsavel_filters(session.responsavel_statements[0])
    assert consolidacao.responsavel_id is None
    assert session.flushes == 0
    assert session.commits == 0


def test_cross_tenant_consolidacao_uuid_is_404_before_target_lookup(app) -> None:
    consolidacao = _consolidacao(igreja_id=_OTHER_IGREJA_ID)
    session = AssignSession(
        consolidacao=consolidacao,
        responsavel=_responsavel(),
    )
    client = _client(app, session=session)

    response = _post(client)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Consolidação não encontrada"
    assert len(session.consolidacao_statements) == 1
    _assert_consolidacao_tenant_filter(session.consolidacao_statements[0])
    assert session.responsavel_statements == []
    assert consolidacao.responsavel_id is None
    assert session.flushes == 0
    assert session.commits == 0
