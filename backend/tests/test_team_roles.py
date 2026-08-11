"""Tests for the last-active-admin guard on PUT /team/{usuario_id}/roles.

update_roles blocks demoting/removing the last admin (409) so a tenant never
loses its administrator. Since access revocation (status='revogado') landed, that
count must exclude invited/revoked admins and identities without Clerk. The
guard therefore uses _active_admin_user_ids (JOIN app_users + usable access) —
the same helper the revoke endpoint uses — instead of a raw admin count.

Like the other router tests, this runs offline against a fake session
(conftest.FakeSession style). _RolesSession models the admin roster *with status*
and applies the revoked filter only to the active-admin query (the one that JOINs
app_users), so a regression back to the unfiltered count would surface here as a
missing 409.
"""

from __future__ import annotations

import pathlib
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.models import AppUser, Celula, Igreja, Pessoa
from app.db.session import get_db
from app.deps import REVOKED_USER_STATUS, CurrentUser, get_current_user

_IGREJA_ID = "00000000-0000-0000-0000-000000000001"
_ADMIN_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_ADMIN_B = uuid.UUID("00000000-0000-0000-0000-0000000000a2")
_AUTH = {"Authorization": "Bearer good"}


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _Result:
    def __init__(self, *, scalar=None, scalars_list=None) -> None:
        self._scalar = scalar
        self._scalars_list = scalars_list or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars_list))


class _RolesSession:
    """Routes update_roles' selects: target AppUser, admin ids, current roles.

    `admins` aceita (user_id, status) ou (user_id, status, clerk_user_id). A
    consulta efetiva exclui convidado/revogado e identidade sem Clerk.
    The plain projection — were the guard to regress to it — would count every
    admin and the revoked-peer case would stop raising 409.
    """

    def __init__(
        self,
        *,
        target,
        admins,
        current_roles=(),
        igreja=None,
        active_cell_id=None,
    ) -> None:
        self.target = target
        self.admins = list(admins)
        self.current_roles = list(current_roles)
        self.igreja = igreja  # #4: db.get(Igreja, ...) ao rebaixar o dono
        self.active_cell_id = active_cell_id
        self.committed = False
        self.deleted: list = []
        self.added: list = []
        self.statements: list = []

    def execute(self, statement, params=None) -> _Result:
        self.statements.append(statement)
        descriptions = getattr(statement, "column_descriptions", None)
        if not descriptions:
            # text() clause from set_tenant_context (RLS GUC / SET LOCAL ROLE).
            return _Result()
        first = descriptions[0]
        if first.get("entity") is AppUser:
            return _Result(scalar=self.target, scalars_list=[self.target])
        if first.get("entity") is Pessoa:
            return _Result(scalar=getattr(self.target, "pessoa_id", None))
        if first.get("entity") is Celula:
            return _Result(scalar=self.active_cell_id)
        if first.get("entity") is Igreja:
            return _Result(scalar=uuid.UUID(_IGREJA_ID))
        if first.get("name") == "user_id":
            if "app_users" in str(statement):  # active-admin query: drop revoked
                ids = [
                    item[0]
                    for item in self.admins
                    if item[1] in (None, "ativo")
                    and (len(item) < 3 or item[2] is not None)
                ]
            else:  # unfiltered admin count (pre-fix behaviour)
                ids = [item[0] for item in self.admins]
            return _Result(scalars_list=ids)
        # select(UserRole) -> the target's current roles
        return _Result(scalars_list=self.current_roles)

    def get(self, model, pk):  # #4: db.get(Igreja, igreja_uuid)
        return self.igreja

    def delete(self, obj) -> None:
        self.deleted.append(obj)

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


def _admin(roles=("admin",)) -> CurrentUser:
    return CurrentUser(
        app_user_id=str(_ADMIN_A),
        clerk_user_id="clerk_admin",
        igreja_id=_IGREJA_ID,
        email="admin@igreja.com.br",
        nome="Admin",
        roles=frozenset(roles),
    )


def _target(uid: uuid.UUID, *, status="ativo", pessoa_id=None):
    return SimpleNamespace(
        id=uid,
        igreja_id=uuid.UUID(_IGREJA_ID),
        clerk_user_id="clerk_target",
        status=status,
        pessoa_id=pessoa_id,
    )


def _client(app, *, session, current_user) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


# ---------------------------------------------------------------------------
# Last-active-admin guard (corner case introduced by access revocation)
# ---------------------------------------------------------------------------
def test_demote_last_active_admin_with_revoked_peer_is_blocked(app) -> None:
    # Tenant has two admins but one is revoked; demoting the only active admin
    # would leave zero usable administrators, so it must be blocked (409).
    target = _target(_ADMIN_A, status="ativo")
    session = _RolesSession(
        target=target,
        admins=[(_ADMIN_A, "ativo"), (_ADMIN_B, REVOKED_USER_STATUS)],
    )
    client = _client(app, session=session, current_user=_admin())

    resp = client.put(
        f"/team/{_ADMIN_A}/roles", json={"papeis": ["membro"]}, headers=_AUTH
    )

    assert resp.status_code == 409
    assert "último administrador" in resp.json()["detail"]
    assert session.committed is False
    assert any(
        "FROM IGREJAS" in str(statement).upper()
        and "FOR UPDATE" in str(statement).upper()
        for statement in session.statements
    )


@pytest.mark.parametrize(
    "inactive_peer",
    [
        (_ADMIN_B, "convidado", "clerk_invited"),
        (_ADMIN_B, "ativo", None),
    ],
)
def test_invited_or_clerkless_admin_does_not_sustain_floor(
    app, inactive_peer
) -> None:
    target = _target(_ADMIN_A, status="ativo")
    session = _RolesSession(
        target=target,
        admins=[(_ADMIN_A, "ativo", "clerk_a"), inactive_peer],
    )

    resp = _client(app, session=session, current_user=_admin()).put(
        f"/team/{_ADMIN_A}/roles",
        json={"papeis": ["membro"]},
        headers=_AUTH,
    )

    assert resp.status_code == 409
    assert session.committed is False


def test_demote_admin_with_another_active_admin_is_allowed(app) -> None:
    # Two active admins: demoting one keeps the tenant covered, so it succeeds.
    # Guards against a false 409 (proves the guard discriminates on the count).
    target = _target(_ADMIN_A, status="ativo")
    session = _RolesSession(
        target=target,
        admins=[(_ADMIN_A, "ativo"), (_ADMIN_B, "ativo")],
        current_roles=[SimpleNamespace(papel="admin")],
    )
    client = _client(app, session=session, current_user=_admin())

    resp = client.put(
        f"/team/{_ADMIN_A}/roles", json={"papeis": ["membro"]}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert resp.json() == {"usuarioId": str(_ADMIN_A), "papeis": ["membro"]}
    assert session.committed is True
    locked = [
        str(statement).upper()
        for statement in session.statements
        if "FOR UPDATE" in str(statement).upper()
    ]
    igreja_lock = next(i for i, sql in enumerate(locked) if "FROM IGREJAS" in sql)
    user_lock = next(i for i, sql in enumerate(locked) if "FROM APP_USERS" in sql)
    role_lock = next(i for i, sql in enumerate(locked) if "FROM USER_ROLES" in sql)
    assert igreja_lock < user_lock < role_lock


def test_demote_dono_clears_church_dono_id(app) -> None:
    # #4: rebaixar o DONO (perde 'admin') limpa igreja.dono_id — senão o ex-admin
    # continuaria com is_owner=True e manteria acesso à Assinatura.
    target = _target(_ADMIN_A, status="ativo")
    igreja = SimpleNamespace(id=uuid.UUID(_IGREJA_ID), dono_id=_ADMIN_A)
    session = _RolesSession(
        target=target,
        admins=[(_ADMIN_A, "ativo"), (_ADMIN_B, "ativo")],  # 2 admins: passa a trava
        current_roles=[SimpleNamespace(papel="admin")],
        igreja=igreja,
    )
    client = _client(app, session=session, current_user=_admin())

    resp = client.put(
        f"/team/{_ADMIN_A}/roles", json={"papeis": ["membro"]}, headers=_AUTH
    )

    assert resp.status_code == 200
    assert igreja.dono_id is None  # cobre a limpeza do dono ao rebaixar
    assert session.committed is True


def test_roles_empty_is_valid_when_leader_role_is_derived(app) -> None:
    pessoa_id = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
    target = _target(_ADMIN_B, pessoa_id=pessoa_id)
    session = _RolesSession(
        target=target,
        admins=[(_ADMIN_A, "ativo")],
        active_cell_id=uuid.UUID("00000000-0000-0000-0000-0000000000e1"),
    )
    resp = _client(app, session=session, current_user=_admin()).put(
        f"/team/{_ADMIN_B}/roles", json={"papeis": []}, headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["papeis"] == ["lider_celula"]
    assert any(getattr(obj, "papel", None) == "lider_celula" for obj in session.added)


def test_roles_empty_is_rejected_without_effective_leadership(app) -> None:
    target = _target(_ADMIN_B)
    session = _RolesSession(target=target, admins=[(_ADMIN_A, "ativo")])
    resp = _client(app, session=session, current_user=_admin()).put(
        f"/team/{_ADMIN_B}/roles", json={"papeis": []}, headers=_AUTH
    )
    assert resp.status_code == 422
    assert session.committed is False


def test_lider_celula_cannot_be_added_manually(app) -> None:
    target = _target(_ADMIN_B)
    session = _RolesSession(target=target, admins=[(_ADMIN_A, "ativo")])
    resp = _client(app, session=session, current_user=_admin()).put(
        f"/team/{_ADMIN_B}/roles",
        json={"papeis": ["membro", "lider_celula"]},
        headers=_AUTH,
    )
    assert resp.status_code == 409
    assert session.committed is False


def test_migration_grants_update_on_dono_id() -> None:
    """A migration 20260707_011455 (Branding) revogou o UPDATE table-wide de
    `igrejas` e só devolveu grant para `logo_path` — `dono_id` ficou de fora, e
    `igreja.dono_id = None` (linha 593, acima) roda sob `SET LOCAL ROLE
    authenticated` igual ao UPDATE de logo. Confirmado contra o DEV real
    (has_column_privilege('authenticated','public.igrejas','dono_id','UPDATE')
    = false antes desta migration). Sem grant por coluna, o UPDATE falha com
    42501 e aborta a transação inteira do PUT /team/{id}/roles (não só a
    limpeza de dono_id — as trocas de papel também não commitam)."""
    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "migrations"
        / "20260708_221808_igreja_dono_id_grant_update.sql"
    )
    sql = path.read_text(encoding="utf-8").lower()
    assert "grant update (dono_id) on igrejas to authenticated" in sql
