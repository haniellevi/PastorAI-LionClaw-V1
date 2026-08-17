"""Contrato de POST /team/invite: acesso administrativo, sem vínculo de célula."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.models import AppUser, Celula, CelulaMembro, Pessoa
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.services.brevo import get_brevo_client
from app.services.clerk import get_clerk_client
from app.services.invite_identity import (
    assert_invite_email_available,
    get_invite_identity_db,
    invite_email_advisory_key,
)
from tests.conftest import FakeClerk

_IGREJA_ID = "00000000-0000-0000-0000-000000000001"
_ADMIN_APP_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")

_TARGET_CELL = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
_LEADERLESS_CELL = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
_INACTIVE_CELL = uuid.UUID("00000000-0000-0000-0000-0000000000e3")
_LEADER_OF_TARGET = uuid.UUID("00000000-0000-0000-0000-0000000000b0")

_LIDER_PESSOA = uuid.UUID("00000000-0000-0000-0000-0000000000d1")  # lidera outra célula
_LIDER_CELL = uuid.UUID("00000000-0000-0000-0000-0000000000e4")  # célula que _LIDER_PESSOA lidera
_NORMAL_PESSOA = uuid.UUID("00000000-0000-0000-0000-0000000000d2")  # elegível

_AUTH = {"Authorization": "Bearer good"}


# ---------------------------------------------------------------------------
# Fake session — filtro genérico por predicados de igualdade (estilo
# cell_backend_fakes.CellSession), estendido para func.lower(coluna) == valor.
# ---------------------------------------------------------------------------
class _Result:
    def __init__(self, *, scalar=None, scalars_list=None) -> None:
        self._scalar = scalar
        self._scalars_list = list(scalars_list or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        items = self._scalars_list
        return SimpleNamespace(
            all=lambda: list(items),
            first=lambda: (items[0] if items else None),
        )


def _predicates(statement) -> dict[str, object]:
    preds: dict[str, object] = {}
    clause = getattr(statement, "whereclause", None)
    stack = [clause] if clause is not None else []
    while stack:
        node = stack.pop()
        left = getattr(node, "left", None)
        right = getattr(node, "right", None)
        if left is not None and right is not None:
            key = getattr(left, "key", None)
            if key is None:
                # func.lower(Column) == valor: a coluna é o 1º clause interno.
                inner_clauses = getattr(left, "clauses", None)
                if inner_clauses is not None:
                    inner = list(inner_clauses)
                    if inner:
                        key = getattr(inner[0], "key", None)
            value = getattr(right, "value", None)
            if key and value is not None:
                preds[key] = value
            continue
        child_clauses = getattr(node, "clauses", None)
        if child_clauses is not None:
            stack.extend(list(child_clauses))
    return preds


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


class _InviteSession:
    def __init__(
        self,
        *,
        actor_pessoa_id: uuid.UUID | None = None,
        app_users: list = (),
        pessoas: list = (),
        cells: list = (),
    ) -> None:
        self.actor_pessoa_id = actor_pessoa_id
        self.app_users = list(app_users)
        self.pessoas = list(pessoas)
        self.cells = list(cells)
        self.added: list = []
        self.committed = False
        self.statements: list = []

    def execute(self, statement, params=None) -> _Result:
        self.statements.append(statement)
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        name = descs[0].get("name") if descs else None

        if ent is AppUser and name == "pessoa_id":
            return _Result(scalar=self.actor_pessoa_id)
        if ent is AppUser:
            preds = _predicates(statement)
            rows = [
                u
                for u in self.app_users
                if all(str(getattr(u, k, None)) == str(v) for k, v in preds.items())
            ]
            return _Result(scalar=(rows[0] if rows else None), scalars_list=rows)
        if ent is Pessoa:
            preds = _predicates(statement)
            rows = [
                p
                for p in self.pessoas
                if all(str(getattr(p, k, None)) == str(v) for k, v in preds.items())
            ]
            return _Result(scalar=(rows[0] if rows else None), scalars_list=rows)
        if ent is Celula:
            preds = _predicates(statement)
            rows = [
                c
                for c in self.cells
                if all(str(getattr(c, k, None)) == str(v) for k, v in preds.items())
            ]
            if _wants_active(statement):
                rows = [c for c in rows if getattr(c, "ativo", True) is True]
            return _Result(scalar=(rows[0] if rows else None), scalars_list=rows)
        return _Result()  # text() do set_tenant_context (RLS GUC)

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:  # pragma: no cover
        pass

    def close(self) -> None:  # pragma: no cover
        pass


class _FakeBrevo:
    """Evita HTTP/config real do Brevo — só precisa não estourar."""

    def send_invite(self, *, to_email: str, nome: str, activation_link: str) -> str:
        return "fake-msg-id"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def _admin() -> CurrentUser:
    return CurrentUser(
        app_user_id=str(_ADMIN_APP_USER_ID),
        clerk_user_id="clerk_admin",
        igreja_id=_IGREJA_ID,
        email="admin@igrejapiloto.com.br",
        nome="Admin",
        roles=frozenset({"admin"}),
    )


def _cell(cell_id: uuid.UUID, *, lider_id: uuid.UUID | None, ativo: bool) -> SimpleNamespace:
    return SimpleNamespace(id=cell_id, igreja_id=_IGREJA_ID, lider_id=lider_id, ativo=ativo)


def _pessoa(pessoa_id: uuid.UUID, *, celula_id=None, email: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=pessoa_id,
        igreja_id=_IGREJA_ID,
        celula_id=celula_id,
        email=email,
        nome="Fulano",
        arquivada_em=None,
        sem_interesse=False,
    )


def _client(
    app, *, session, current_user, clerk=None, identity_session=None
) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_clerk_client] = lambda: clerk or FakeClerk()
    app.dependency_overrides[get_brevo_client] = lambda: _FakeBrevo()
    app.dependency_overrides[get_invite_identity_db] = (
        lambda: identity_session or session
    )
    return TestClient(app)


def test_invite_rejects_legacy_celula_id_in_new_payload(app) -> None:
    session = _InviteSession()
    client = _client(app, session=session, current_user=_admin())
    resp = client.post(
        "/team/invite",
        json={
            "nome": "Novo Membro",
            "email": "novo@igrejapiloto.com.br",
            "celulaId": str(_TARGET_CELL),
        },
        headers=_AUTH,
    )
    assert resp.status_code == 422
    assert session.added == []


def test_invite_existing_cell_member_grants_access_without_moving(app) -> None:
    original_cell = uuid.UUID("00000000-0000-0000-0000-0000000000c9")
    candidato = _pessoa(_NORMAL_PESSOA, celula_id=original_cell, email=None)
    session = _InviteSession(pessoas=[candidato])
    client = _client(app, session=session, current_user=_admin())

    resp = client.post(
        "/team/invite",
        json={
            "pessoaId": str(_NORMAL_PESSOA),
            "email": "membro@igrejapiloto.com.br",
        },
        headers=_AUTH,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "convidado"
    assert session.committed is True
    assert len(session.added) == 2  # AppUser + UserRole, nenhum CelulaMembro
    assert candidato.celula_id == original_cell
    assert not any(isinstance(o, CelulaMembro) for o in session.added)
    assert any("FOR UPDATE" in str(stmt).upper() for stmt in session.statements)
    assert "PG_ADVISORY_XACT_LOCK" in str(session.statements[0]).upper()


def test_invite_existing_cell_leader_can_receive_access(app) -> None:
    candidato = _pessoa(_LIDER_PESSOA, celula_id=None)
    led_cell = _cell(_LIDER_CELL, lider_id=_LIDER_PESSOA, ativo=True)
    session = _InviteSession(pessoas=[candidato], cells=[led_cell])
    resp = _client(app, session=session, current_user=_admin()).post(
        "/team/invite",
        json={"pessoaId": str(_LIDER_PESSOA), "email": "lider@igreja.org"},
        headers=_AUTH,
    )
    assert resp.status_code == 200, resp.text
    assert len(session.added) == 2


def test_invite_rejects_second_access_for_same_person(app) -> None:
    candidato = _pessoa(_NORMAL_PESSOA)
    linked = SimpleNamespace(
        id=uuid.uuid4(),
        igreja_id=uuid.UUID(_IGREJA_ID),
        pessoa_id=_NORMAL_PESSOA,
        email="outro@igreja.org",
    )
    session = _InviteSession(pessoas=[candidato], app_users=[linked])
    resp = _client(app, session=session, current_user=_admin()).post(
        "/team/invite",
        json={"pessoaId": str(_NORMAL_PESSOA), "email": "novo@igreja.org"},
        headers=_AUTH,
    )
    assert resp.status_code == 409
    assert session.added == []


def test_invite_rejects_archived_person_until_explicit_reactivation(app) -> None:
    candidato = _pessoa(_NORMAL_PESSOA)
    candidato.arquivada_em = object()
    session = _InviteSession(pessoas=[candidato])

    resp = _client(app, session=session, current_user=_admin()).post(
        "/team/invite",
        json={"pessoaId": str(_NORMAL_PESSOA), "email": "novo@igreja.org"},
        headers=_AUTH,
    )

    assert resp.status_code == 409
    assert session.added == []


def test_invite_rejects_person_without_ministerial_interest(app) -> None:
    candidato = _pessoa(_NORMAL_PESSOA)
    candidato.sem_interesse = True
    session = _InviteSession(pessoas=[candidato])

    resp = _client(app, session=session, current_user=_admin()).post(
        "/team/invite",
        json={"pessoaId": str(_NORMAL_PESSOA), "email": "novo@igreja.org"},
        headers=_AUTH,
    )

    assert resp.status_code == 409
    assert session.added == []


def test_invite_rejects_existing_global_clerk_identity_before_write(app) -> None:
    session = _InviteSession()
    clerk = FakeClerk(existing_clerk_id="clerk_from_another_church")

    resp = _client(
        app, session=session, current_user=_admin(), clerk=clerk
    ).post(
        "/team/invite",
        json={"nome": "Novo", "email": "existente@igreja.org"},
        headers=_AUTH,
    )

    assert resp.status_code == 409
    assert session.added == []
    assert clerk.create_calls == 0
    assert "PG_ADVISORY_XACT_LOCK" in str(session.statements[0]).upper()


def test_team_and_platform_invites_share_the_same_normalized_email_lock() -> None:
    from app.routers import platform_admin, team

    assert team.assert_invite_email_available is assert_invite_email_available
    assert platform_admin.assert_invite_email_available is assert_invite_email_available
    assert invite_email_advisory_key(" Pessoa@Igreja.ORG ") == (
        invite_email_advisory_key("pessoa@igreja.org")
    )


def test_invite_rejects_pending_access_from_another_church(app) -> None:
    tenant_session = _InviteSession()
    other_church_pending = SimpleNamespace(
        id=uuid.uuid4(),
        igreja_id=uuid.uuid4(),
        email="pendente@igreja.org",
        status="convidado",
        clerk_user_id=None,
    )
    global_identity_session = _InviteSession(app_users=[other_church_pending])

    resp = _client(
        app,
        session=tenant_session,
        identity_session=global_identity_session,
        current_user=_admin(),
    ).post(
        "/team/invite",
        json={"nome": "Novo", "email": "pendente@igreja.org"},
        headers=_AUTH,
    )

    assert resp.status_code == 409
    assert tenant_session.added == []
    assert "PG_ADVISORY_XACT_LOCK" in str(
        global_identity_session.statements[0]
    ).upper()


def test_invite_fails_closed_when_clerk_lookup_is_unavailable(app) -> None:
    session = _InviteSession()
    clerk = FakeClerk(raise_find=True)

    resp = _client(
        app, session=session, current_user=_admin(), clerk=clerk
    ).post(
        "/team/invite",
        json={"nome": "Novo", "email": "novo@igreja.org"},
        headers=_AUTH,
    )

    assert resp.status_code == 502
    assert session.added == []


@pytest.mark.parametrize(
    ("user_status", "clerk_user_id"),
    [("ativo", "clerk_active"), ("revogado", None), ("convidado", "clerk_done")],
)
def test_resend_accepts_only_pending_invite_without_clerk(
    app, user_status, clerk_user_id
) -> None:
    target = SimpleNamespace(
        id=uuid.uuid4(),
        igreja_id=uuid.UUID(_IGREJA_ID),
        pessoa_id=None,
        nome="Convite",
        email="convite@igreja.org",
        status=user_status,
        clerk_user_id=clerk_user_id,
    )
    session = _InviteSession(app_users=[target])

    resp = _client(app, session=session, current_user=_admin()).post(
        f"/team/{target.id}/resend", headers=_AUTH
    )

    assert resp.status_code == 409


def test_resend_pending_invite_without_clerk_is_allowed(app) -> None:
    target = SimpleNamespace(
        id=uuid.uuid4(),
        igreja_id=uuid.UUID(_IGREJA_ID),
        pessoa_id=None,
        nome="Convite",
        email="convite@igreja.org",
        status="convidado",
        clerk_user_id=None,
    )
    session = _InviteSession(app_users=[target])

    resp = _client(app, session=session, current_user=_admin()).post(
        f"/team/{target.id}/resend", headers=_AUTH
    )

    assert resp.status_code == 200
    assert resp.json()["emailEnviado"] is True


def test_invite_requires_admin_not_pastor_or_cell_leader(app) -> None:
    for role in ("pastor", "lider_celula"):
        session = _InviteSession()
        resp = _client(
            app,
            session=session,
            current_user=CurrentUser(
                app_user_id=str(_ADMIN_APP_USER_ID),
                clerk_user_id="clerk",
                igreja_id=_IGREJA_ID,
                email="x@igreja.org",
                nome="X",
                roles=frozenset({role}),
            ),
        ).post(
            "/team/invite",
            json={"nome": "Novo", "email": "novo@igreja.org"},
            headers=_AUTH,
        )
        assert resp.status_code == 403
        assert session.added == []
