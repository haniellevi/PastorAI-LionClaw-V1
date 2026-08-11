"""Row-level scope for GET/PUT/POST /pipeline.

The offline session records the real SQLAlchemy statements. Read tests prove
that the same predicate reaches count and rows; write tests make an otherwise
existing target disappear only when the cell-membership predicate is present,
so an out-of-scope request must return 404 before any mutation.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.models import AppUser, Celula, Pessoa, WorkQueueItem
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user

_AUTH = {"Authorization": "Bearer good"}
_IGREJA_ID = "00000000-0000-0000-0000-000000000001"
_APP_USER_ID = "00000000-0000-0000-0000-0000000000a1"
_ACTOR_PESSOA_ID = "00000000-0000-0000-0000-0000000000b1"
_TARGET_PESSOA_ID = "00000000-0000-0000-0000-0000000000d1"
_OTHER_TENANT_ID = "00000000-0000-0000-0000-000000000002"


class _Result:
    def __init__(self, *, scalar=None, scalars=()) -> None:
        self._scalar = scalar
        self._scalars = list(scalars)

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


def _compiled(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


class PipelineScopeSession:
    def __init__(
        self,
        *,
        actor_pessoa_id: str | None,
        target_pessoa=None,
        scope_denies_target: bool = False,
        deny_archived_target: bool = False,
        people=(),
        total: int = 0,
    ) -> None:
        self.actor_pessoa_id = actor_pessoa_id
        self.target_pessoa = target_pessoa
        self.scope_denies_target = scope_denies_target
        self.deny_archived_target = deny_archived_target
        self.people = list(people)
        self.total = total
        self.actor_lookups = 0
        self.pessoa_statements: list = []
        self.added: list = []
        self.flushes = 0
        self.commits = 0

    def execute(self, statement, params=None) -> _Result:
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entity = descriptions[0].get("entity") if descriptions else None
        sql = _compiled(statement)
        lowered = sql.lower()

        if entity is AppUser:
            self.actor_lookups += 1
            return _Result(scalar=self.actor_pessoa_id)

        if "count(" in lowered and "pessoas" in lowered:
            self.pessoa_statements.append(statement)
            return _Result(scalar=self.total)

        if entity is Pessoa:
            self.pessoa_statements.append(statement)
            if "order by" in lowered:
                return _Result(scalars=self.people)
            target = self.target_pessoa
            if self.scope_denies_target and (
                "celula_membro" in lowered or "conversations" in lowered
            ):
                target = None
            if (
                self.deny_archived_target
                and "pessoas.arquivada_em is not distinct from null" in lowered
            ):
                target = None
            if (
                target is not None
                and target.sem_interesse
                and "pessoas.sem_interesse is false" in lowered
            ):
                target = None
            return _Result(
                scalar=target,
                scalars=([target] if target is not None else []),
            )

        if entity is WorkQueueItem:
            return _Result()

        if entity is Celula:
            return _Result(scalars=[])

        return _Result()

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    def flush(self) -> None:
        self.flushes += 1

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:  # pragma: no cover
        pass

    def close(self) -> None:  # pragma: no cover
        pass


def _current_user(*roles: str) -> CurrentUser:
    return CurrentUser(
        app_user_id=_APP_USER_ID,
        clerk_user_id="clerk_scope",
        igreja_id=_IGREJA_ID,
        email="scope@igrejapiloto.com.br",
        nome="Scope",
        roles=frozenset(roles),
    )


def _target_pessoa():
    return SimpleNamespace(
        id=uuid.UUID(_TARGET_PESSOA_ID),
        igreja_id=uuid.UUID(_IGREJA_ID),
        nome="Pessoa fora da célula",
        telefone="11999990000",
        email=None,
        genero=None,
        tipo="membro",
        etapa="ganhar",
        subetapa=None,
        acompanhamento=None,
        sem_interesse=False,
        sem_interesse_motivo=None,
        presencas_celula=0,
        aceitou_jesus=False,
        celula_id=None,
        lider_id=None,
        apto_lider=False,
        arquivada_em=None,
        created_at=None,
    )


def _client(app, *, session: PipelineScopeSession, current_user: CurrentUser):
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


def _assert_cell_scope(statement) -> None:
    sql = _compiled(statement).lower()
    assert "pessoas.igreja_id" in sql, sql
    assert "pessoas.arquivada_em is not distinct from null" in sql, sql
    assert "pessoas.sem_interesse is false" in sql, sql
    assert "celula_membro" in sql, sql
    assert "celula_membro.igreja_id" in sql, sql
    assert "celula_membro.ativo is true" in sql, sql
    assert "celulas.igreja_id" in sql, sql
    assert "celulas.ativo is true" in sql, sql
    assert "celulas.lider_id" in sql, sql


def _assert_assignment_scope(statement) -> None:
    sql = _compiled(statement).lower()
    assert "pessoas.igreja_id" in sql, sql
    assert "pessoas.arquivada_em is not distinct from null" in sql, sql
    assert "pessoas.sem_interesse is false" in sql, sql
    assert "exists (select conversations.id" in sql, sql
    assert "conversations.igreja_id" in sql, sql
    assert "conversations.pessoa_id = pessoas.id" in sql, sql
    assert "conversations.assumido_por" in sql, sql
    assert uuid.UUID(_IGREJA_ID).hex in sql, sql
    assert uuid.UUID(_APP_USER_ID).hex in sql, sql


def test_cell_leader_scope_is_applied_to_count_and_rows(app) -> None:
    session = PipelineScopeSession(actor_pessoa_id=_ACTOR_PESSOA_ID)
    client = _client(
        app,
        session=session,
        current_user=_current_user("membro", "lider_celula"),
    )

    response = client.get("/pipeline?etapa=ganhar", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "page": 1, "pageSize": 20, "total": 0}
    assert session.actor_lookups == 1
    assert len(session.pessoa_statements) == 2
    for statement in session.pessoa_statements:
        _assert_cell_scope(statement)
        sql = _compiled(statement).lower()
        assert uuid.UUID(_ACTOR_PESSOA_ID).hex in sql, sql
        assert "conversations" not in sql, sql


@pytest.mark.parametrize(
    "wide_role", ["admin", "pastor", "lider_g12", "lider_consol"]
)
def test_accumulated_wide_role_wins_over_cell_leader_scope(app, wide_role) -> None:
    session = PipelineScopeSession(actor_pessoa_id=None)
    client = _client(
        app,
        session=session,
        current_user=_current_user("lider_celula", wide_role),
    )

    response = client.get("/pipeline", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert session.actor_lookups == 0
    assert len(session.pessoa_statements) == 2
    for statement in session.pessoa_statements:
        sql = _compiled(statement).lower()
        assert "pessoas.igreja_id" in sql
        assert "pessoas.arquivada_em is not distinct from null" in sql
        assert uuid.UUID(_IGREJA_ID).hex in sql
        assert "celula_membro" not in sql
        assert "conversations" not in sql


@pytest.mark.parametrize("role", ["membro", "lider_mult"])
def test_other_roles_see_only_their_own_pessoa(app, role) -> None:
    session = PipelineScopeSession(actor_pessoa_id=_ACTOR_PESSOA_ID)
    client = _client(app, session=session, current_user=_current_user(role))

    response = client.get("/pipeline", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert session.actor_lookups == 1
    assert len(session.pessoa_statements) == 2
    for statement in session.pessoa_statements:
        sql = _compiled(statement).lower()
        assert "pessoas.igreja_id" in sql, sql
        assert "pessoas.arquivada_em is not distinct from null" in sql, sql
        assert "pessoas.id" in sql, sql
        assert uuid.UUID(_ACTOR_PESSOA_ID).hex in sql, sql
        assert "celula_membro" not in sql, sql
        assert "conversations" not in sql, sql


def test_operator_assigned_conversation_is_applied_to_count_and_rows(app) -> None:
    target = _target_pessoa()
    session = PipelineScopeSession(
        actor_pessoa_id=None,
        people=[target],
        total=1,
    )
    client = _client(app, session=session, current_user=_current_user("operador"))

    response = client.get("/pipeline", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert [item["id"] for item in response.json()["items"]] == [
        _TARGET_PESSOA_ID
    ]
    assert session.actor_lookups == 1
    assert len(session.pessoa_statements) == 2
    for statement in session.pessoa_statements:
        _assert_assignment_scope(statement)
        assert "celula_membro" not in _compiled(statement).lower()


def test_operator_after_assignment_revoked_or_transferred_gets_empty_200(app) -> None:
    session = PipelineScopeSession(actor_pessoa_id=None)
    client = _client(app, session=session, current_user=_current_user("operador"))

    response = client.get("/pipeline", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "page": 1, "pageSize": 20, "total": 0}
    assert len(session.pessoa_statements) == 2
    for statement in session.pessoa_statements:
        _assert_assignment_scope(statement)


def test_operator_cell_leader_read_is_union_of_own_cell_and_assignment(app) -> None:
    session = PipelineScopeSession(actor_pessoa_id=_ACTOR_PESSOA_ID)
    client = _client(
        app,
        session=session,
        current_user=_current_user("operador", "lider_celula"),
    )

    response = client.get("/pipeline", headers=_AUTH)

    assert response.status_code == 200, response.text
    for statement in session.pessoa_statements:
        _assert_cell_scope(statement)
        _assert_assignment_scope(statement)
        sql = _compiled(statement).lower()
        assert uuid.UUID(_ACTOR_PESSOA_ID).hex in sql, sql
        assert " or " in sql, sql


@pytest.mark.parametrize("role", ["membro", "lider_celula"])
def test_restricted_role_without_linked_pessoa_gets_empty_200(app, role) -> None:
    session = PipelineScopeSession(actor_pessoa_id=None)
    client = _client(app, session=session, current_user=_current_user(role))

    response = client.get("/pipeline", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "page": 1, "pageSize": 20, "total": 0}
    assert session.actor_lookups == 1
    assert len(session.pessoa_statements) == 2
    for statement in session.pessoa_statements:
        assert "false" in _compiled(statement).lower()


@pytest.mark.parametrize("role", ["lider_celula", "operador"])
def test_restricted_roles_cannot_promote_and_do_not_query_target(app, role) -> None:
    target = _target_pessoa()
    session = PipelineScopeSession(
        actor_pessoa_id=_ACTOR_PESSOA_ID,
        target_pessoa=target,
    )
    client = _client(app, session=session, current_user=_current_user(role))

    response = client.put(
        "/pipeline",
        headers=_AUTH,
        json={"pessoaId": _TARGET_PESSOA_ID, "etapa": "ganhar"},
    )

    assert response.status_code == 403, response.text
    assert session.actor_lookups == 0
    assert session.pessoa_statements == []
    assert target.etapa == "ganhar"
    assert session.added == []
    assert session.flushes == 0
    assert session.commits == 0


def test_cell_leader_fonovisita_outside_scope_returns_404_without_mutation(
    app,
) -> None:
    target = _target_pessoa()
    session = PipelineScopeSession(
        actor_pessoa_id=_ACTOR_PESSOA_ID,
        target_pessoa=target,
        scope_denies_target=True,
    )
    client = _client(
        app,
        session=session,
        current_user=_current_user("lider_celula"),
    )

    response = client.post(
        "/pipeline/fonovisita",
        headers=_AUTH,
        json={"pessoaId": _TARGET_PESSOA_ID},
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Pessoa não encontrada"
    assert len(session.pessoa_statements) == 1
    _assert_cell_scope(session.pessoa_statements[0])
    assert target.etapa == "ganhar"
    assert session.added == []
    assert session.flushes == 0
    assert session.commits == 0


def test_operator_fonovisita_assigned_person_uses_assignment_scope(app) -> None:
    target = _target_pessoa()
    session = PipelineScopeSession(
        actor_pessoa_id=None,
        target_pessoa=target,
    )
    client = _client(app, session=session, current_user=_current_user("operador"))

    response = client.post(
        "/pipeline/fonovisita",
        headers=_AUTH,
        json={"pessoaId": _TARGET_PESSOA_ID},
    )

    assert response.status_code == 200, response.text
    assert len(session.pessoa_statements) == 1
    _assert_assignment_scope(session.pessoa_statements[0])
    assert "celula_membro" not in _compiled(session.pessoa_statements[0]).lower()
    assert session.flushes == 1
    assert session.commits == 1


def test_operator_fonovisita_unassigned_person_is_404_without_mutation(app) -> None:
    target = _target_pessoa()
    session = PipelineScopeSession(
        actor_pessoa_id=None,
        target_pessoa=target,
        scope_denies_target=True,
    )
    client = _client(app, session=session, current_user=_current_user("operador"))

    response = client.post(
        "/pipeline/fonovisita",
        headers=_AUTH,
        json={"pessoaId": _TARGET_PESSOA_ID},
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Pessoa não encontrada"
    assert len(session.pessoa_statements) == 1
    _assert_assignment_scope(session.pessoa_statements[0])
    assert target.etapa == "ganhar"
    assert session.added == []
    assert session.flushes == 0
    assert session.commits == 0


def test_operator_fonovisita_cross_tenant_or_id_bypass_is_404(app) -> None:
    target = _target_pessoa()
    target.igreja_id = uuid.UUID(_OTHER_TENANT_ID)
    session = PipelineScopeSession(
        actor_pessoa_id=None,
        target_pessoa=target,
        scope_denies_target=True,
    )
    client = _client(app, session=session, current_user=_current_user("operador"))

    response = client.post(
        "/pipeline/fonovisita",
        headers=_AUTH,
        json={"pessoaId": _TARGET_PESSOA_ID},
    )

    assert response.status_code == 404, response.text
    sql = _compiled(session.pessoa_statements[0]).lower()
    _assert_assignment_scope(session.pessoa_statements[0])
    assert uuid.UUID(_OTHER_TENANT_ID).hex not in sql
    assert session.flushes == 0
    assert session.commits == 0


def test_member_with_artificial_conversation_assignment_still_cannot_write(app) -> None:
    target = _target_pessoa()
    session = PipelineScopeSession(
        actor_pessoa_id=_ACTOR_PESSOA_ID,
        target_pessoa=target,
    )
    client = _client(app, session=session, current_user=_current_user("membro"))

    response = client.put(
        "/pipeline",
        headers=_AUTH,
        json={"pessoaId": _TARGET_PESSOA_ID, "etapa": "ganhar"},
    )

    assert response.status_code == 403, response.text
    assert session.actor_lookups == 0
    assert session.pessoa_statements == []
    assert session.flushes == 0
    assert session.commits == 0


@pytest.mark.parametrize(
    ("role", "method", "path", "payload", "assert_scope"),
    [
        (
            "admin",
            "PUT",
            "/pipeline",
            {"pessoaId": _TARGET_PESSOA_ID, "etapa": "ganhar"},
            None,
        ),
        (
            "admin",
            "POST",
            "/pipeline/fonovisita",
            {"pessoaId": _TARGET_PESSOA_ID},
            None,
        ),
        (
            "lider_celula",
            "POST",
            "/pipeline/fonovisita",
            {"pessoaId": _TARGET_PESSOA_ID},
            _assert_cell_scope,
        ),
        (
            "operador",
            "POST",
            "/pipeline/fonovisita",
            {"pessoaId": _TARGET_PESSOA_ID},
            _assert_assignment_scope,
        ),
    ],
)
def test_csim_uuid_bypass_is_404_without_mutation(
    app, role, method, path, payload, assert_scope
) -> None:
    target = _target_pessoa()
    target.sem_interesse = True
    session = PipelineScopeSession(
        actor_pessoa_id=(
            _ACTOR_PESSOA_ID if role == "lider_celula" else None
        ),
        target_pessoa=target,
    )
    client = _client(app, session=session, current_user=_current_user(role))

    response = client.request(method, path, headers=_AUTH, json=payload)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Pessoa não encontrada"
    assert len(session.pessoa_statements) == 1
    sql = _compiled(session.pessoa_statements[0]).lower()
    assert "pessoas.sem_interesse is false" in sql, sql
    if assert_scope is not None:
        assert_scope(session.pessoa_statements[0])
    assert target.etapa == "ganhar"
    assert session.added == []
    assert session.flushes == 0
    assert session.commits == 0


@pytest.mark.parametrize("role", ["admin", "operador"])
def test_archived_person_is_excluded_from_pipeline_count_and_rows(app, role) -> None:
    session = PipelineScopeSession(
        actor_pessoa_id=None,
        people=[],
        total=0,
    )
    client = _client(app, session=session, current_user=_current_user(role))

    response = client.get("/pipeline", headers=_AUTH)

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "page": 1, "pageSize": 20, "total": 0}
    assert len(session.pessoa_statements) == 2
    for statement in session.pessoa_statements:
        sql = _compiled(statement).lower()
        assert "pessoas.igreja_id" in sql
        assert "pessoas.arquivada_em is not distinct from null" in sql
        if role == "operador":
            _assert_assignment_scope(statement)


@pytest.mark.parametrize(
    ("role", "method", "path", "payload"),
    [
        (
            "admin",
            "PUT",
            "/pipeline",
            {"pessoaId": _TARGET_PESSOA_ID, "etapa": "ganhar"},
        ),
        (
            "admin",
            "POST",
            "/pipeline/fonovisita",
            {"pessoaId": _TARGET_PESSOA_ID},
        ),
        (
            "operador",
            "POST",
            "/pipeline/fonovisita",
            {"pessoaId": _TARGET_PESSOA_ID},
        ),
        (
            "lider_celula",
            "POST",
            "/pipeline/fonovisita",
            {"pessoaId": _TARGET_PESSOA_ID},
        ),
    ],
)
def test_archived_person_write_is_404_for_wide_and_restricted_roles(
    app, role, method, path, payload
) -> None:
    target = _target_pessoa()
    target.arquivada_em = object()
    session = PipelineScopeSession(
        actor_pessoa_id=(
            _ACTOR_PESSOA_ID if role == "lider_celula" else None
        ),
        target_pessoa=target,
        deny_archived_target=True,
    )
    client = _client(app, session=session, current_user=_current_user(role))

    response = client.request(method, path, headers=_AUTH, json=payload)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Pessoa não encontrada"
    assert len(session.pessoa_statements) == 1
    sql = _compiled(session.pessoa_statements[0]).lower()
    assert "pessoas.igreja_id" in sql
    assert "pessoas.arquivada_em is not distinct from null" in sql
    assert "pessoas.sem_interesse is false" in sql
    if role == "operador":
        _assert_assignment_scope(session.pessoa_statements[0])
    if role == "lider_celula":
        _assert_cell_scope(session.pessoa_statements[0])
    assert session.added == []
    assert session.flushes == 0
    assert session.commits == 0


@pytest.mark.parametrize(
    "wide_role", ["admin", "pastor", "lider_g12", "lider_consol"]
)
def test_accumulated_wide_role_can_write_without_cell_scope(app, wide_role) -> None:
    target = _target_pessoa()
    session = PipelineScopeSession(
        actor_pessoa_id=None,
        target_pessoa=target,
        scope_denies_target=True,
    )
    client = _client(
        app,
        session=session,
        current_user=_current_user("lider_celula", wide_role),
    )

    response = client.put(
        "/pipeline",
        headers=_AUTH,
        json={"pessoaId": _TARGET_PESSOA_ID, "etapa": "ganhar"},
    )

    assert response.status_code == 200, response.text
    assert session.actor_lookups == 0
    assert len(session.pessoa_statements) == 1
    sql = _compiled(session.pessoa_statements[0]).lower()
    assert "pessoas.igreja_id" in sql
    assert "pessoas.arquivada_em is not distinct from null" in sql
    assert "pessoas.sem_interesse is false" in sql
    assert uuid.UUID(_IGREJA_ID).hex in sql
    assert "celula_membro" not in sql
    assert "conversations" not in sql
    assert session.flushes == 1
    assert session.commits == 1
