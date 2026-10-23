"""Session revocation and tenant isolation against the synthetic PostgreSQL chain."""

from __future__ import annotations

import os
import time
import datetime as dt
from types import SimpleNamespace
from uuid import uuid4
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AppUser, AuthSession
from app.db.session import get_db
from app.db.tenant_session import mark_tenant_scoped
from app.deps import CurrentUser, get_current_user
from app.routers import auth, team
from app.services.auth_sessions import register_session_with_backend_role
from app.services.clerk import ClerkClient, get_clerk_client
from app.workers.cron_worker import AUTH_SESSION_PURGE_INTERVAL, CronWorker
from tests.conftest_rls import assert_disposable_database
from tests.test_uv_turmas_pg import database, migrated_database, seeded  # noqa: F401

pytestmark = [
    pytest.mark.rls_integration,
    pytest.mark.usefixtures("rls_database_url"),
]


@pytest.fixture(scope="module")
def rls_database_url():
    # The imported migration fixture belongs to test_uv_turmas_pg and must stay
    # on its dedicated database, away from the shared minimal RLS schema.
    url = os.environ.get("UV_TURMAS_DATABASE_URL", "").strip()
    if not url:
        pytest.fail("Logout exige PostgreSQL local sintético via UV_TURMAS_DATABASE_URL; nenhum skip permitido")
    assert_disposable_database(url)
    parsed = urlsplit(url)
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.path != "/uv_turmas_test"
    ):
        pytest.fail("Use somente o PostgreSQL local descartável uv_turmas_test para logout")
    return url


def _clerk() -> ClerkClient:
    return ClerkClient(
        SimpleSettings(
            effective_session_secret="synthetic-session-revocation-secret-only"
        )
    )


class SimpleSettings:
    effective_session_secret: str
    session_ttl_hours = 8

    def __init__(self, effective_session_secret: str) -> None:
        self.effective_session_secret = effective_session_secret


def _token(clerk: ClerkClient, subject: str) -> tuple[str, str]:
    token = clerk._mint_session_token(subject)  # noqa: SLF001
    identity = clerk.verify_session_token(token)
    return token, identity.claims["jti"]


def _scoped_db(database, tenant, subject):
    session = Session(database)
    mark_tenant_scoped(
        session,
        str(tenant),
        actor_sub=subject,
        source="auth-session-revocation-pg-test",
    )
    return session


def _app(database, tenant, subject, clerk, *, current_user=None):
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(team.router)

    def db_override():
        session = _scoped_db(database, tenant, subject)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    return app


def _insert_session(database, *, jti, tenant, app_user_id, issued_at=None):
    issued_at = issued_at or int(time.time())
    with database.begin() as connection:
        connection.execute(
            text(
                "insert into auth_sessions(jti,igreja_id,app_user_id,issued_at,expires_at) "
                "values(:jti,:tenant,:user,to_timestamp(:iat),to_timestamp(:iat + 3600))"
            ),
            {"jti": jti, "tenant": tenant, "user": app_user_id, "iat": issued_at},
        )


def test_authenticated_cannot_delete_or_reinsert_revoked_session(database, seeded):
    subject, jti = "session-owner-acl", "revoked-session-acl"
    with database.begin() as connection:
        connection.execute(
            text("update app_users set clerk_user_id=:sub where id=:id"),
            {"sub": subject, "id": seeded["uid"]},
        )
    _insert_session(database, jti=jti, tenant=seeded["t"], app_user_id=seeded["uid"])
    with database.begin() as connection:
        connection.execute(
            text("update auth_sessions set revoked_at=now() where jti=:jti"),
            {"jti": jti},
        )

    with database.connect() as connection:
        assert not connection.scalar(
            text("select has_table_privilege('authenticated','auth_sessions','INSERT')")
        )
        assert not connection.scalar(
            text("select has_table_privilege('authenticated','auth_sessions','DELETE')")
        )

    with pytest.raises(DBAPIError):
        with _scoped_db(database, seeded["t"], subject) as session:
            session.execute(text("delete from auth_sessions where jti=:jti"), {"jti": jti})

    with pytest.raises(DBAPIError):
        with _scoped_db(database, seeded["t"], subject) as session:
            session.execute(
                text(
                    "insert into auth_sessions(jti,igreja_id,app_user_id,issued_at,expires_at) "
                    "values(:jti,:tenant,:user,now(),now()+interval '1 hour')"
                ),
                {"jti": jti, "tenant": seeded["t"], "user": seeded["uid"]},
            )

    with database.connect() as connection:
        assert connection.scalar(
            text("select revoked_at is not null from auth_sessions where jti=:jti"),
            {"jti": jti},
        ) is True


def test_backend_session_registrar_writes_without_authenticated_insert(database, seeded):
    subject = "session-backend-registrar"
    with database.begin() as connection:
        connection.execute(
            text("update app_users set clerk_user_id=:sub where id=:id"),
            {"sub": subject, "id": seeded["uid"]},
        )
    with Session(database) as session:
        app_user = session.get(AppUser, seeded["uid"])
    clerk = _clerk()
    token, jti = _token(clerk, subject)

    register_session_with_backend_role(
        clerk,
        token,
        app_user,
        session_factory=lambda: Session(database),
    )

    with database.connect() as connection:
        assert connection.scalar(
            text("select count(*) from auth_sessions where jti=:jti"), {"jti": jti}
        ) == 1


def test_composite_session_fk_allows_detached_platform_admin_null_tenant(
    database, seeded
):
    user_id = uuid4()
    jti = str(uuid4())
    with database.begin() as connection:
        connection.execute(
            text(
                "insert into app_users(id,igreja_id,nome,email,status,clerk_user_id) "
                "values(:id,:tenant,'Admin de plataforma sintético',:email,'ativo',:subject)"
            ),
            {
                "id": user_id,
                "tenant": seeded["t"],
                "email": f"platform-{user_id}@example.test",
                "subject": f"platform-admin-{user_id}",
            },
        )
        connection.execute(
            text("insert into platform_admins(app_user_id,email) values(:id,:email)"),
            {"id": user_id, "email": f"platform-{user_id}@example.test"},
        )
        connection.execute(
            text("update app_users set igreja_id=null where id=:id"), {"id": user_id}
        )
        connection.execute(
            text(
                "insert into auth_sessions(jti,igreja_id,app_user_id,issued_at,expires_at) "
                "values(:jti,null,:user,now(),now()+interval '1 hour')"
            ),
            {"jti": jti, "user": user_id},
        )
    with database.connect() as connection:
        assert connection.scalar(
            text("select igreja_id is null from auth_sessions where jti=:jti"),
            {"jti": jti},
        ) is True
    with pytest.raises(IntegrityError):
        with database.begin() as connection:
            connection.execute(
                text(
                    "insert into auth_sessions(jti,igreja_id,app_user_id,issued_at,expires_at) "
                    "values(:jti,null,:user,now(),now()+interval '1 hour')"
                ),
                {"jti": str(uuid4()), "user": uuid4()},
            )


def test_cron_purges_expired_sessions_across_tenants(database, seeded):
    now = dt.datetime.now(dt.timezone.utc)
    old_issued_at = int((now - dt.timedelta(hours=2)).timestamp())
    with database.begin() as connection:
        connection.execute(
            text("update app_users set clerk_user_id='session-expiry-a' where id=:id"),
            {"id": seeded["uid"]},
        )
        connection.execute(
            text(
                "insert into app_users(id,igreja_id,nome,email,status,clerk_user_id) "
                "values(:id,:tenant,'Equipe expirada sintética','expiry@example.test','ativo','session-expiry-b')"
            ),
            {"id": uuid4(), "tenant": seeded["other"]},
        )
        other_user = connection.scalar(
            text("select id from app_users where clerk_user_id='session-expiry-b'")
        )
    expired_a, expired_b, active = "expired-session-a", "expired-session-b", "active-session"
    _insert_session(
        database,
        jti=expired_a,
        tenant=seeded["t"],
        app_user_id=seeded["uid"],
        issued_at=old_issued_at,
    )
    _insert_session(
        database,
        jti=expired_b,
        tenant=seeded["other"],
        app_user_id=other_user,
        issued_at=old_issued_at,
    )
    _insert_session(database, jti=active, tenant=seeded["t"], app_user_id=seeded["uid"])

    worker = CronWorker(
        session_factory=lambda: Session(database),
        engine=object(),
        settings=SimpleNamespace(cron_tick_seconds=30, redis_url=""),
    )
    assert worker._purge_auth_sessions(now) == 2
    assert worker._purge_auth_sessions(now + AUTH_SESSION_PURGE_INTERVAL / 2) == 0
    with database.connect() as connection:
        assert connection.scalar(
            text("select count(*) from auth_sessions where jti in (:a,:b)"),
            {"a": expired_a, "b": expired_b},
        ) == 0
        assert connection.scalar(
            text("select count(*) from auth_sessions where jti=:jti"), {"jti": active}
        ) == 1


def test_tenant_a_cannot_revoke_tenant_b_session(database, seeded):
    v = seeded
    subject_a, subject_b = "session-owner-a", "session-owner-b"
    user_b, jti_a, jti_b = uuid4(), "session-a-jti", "session-b-jti"
    with database.begin() as connection:
        connection.execute(
            text("update app_users set clerk_user_id=:sub where id=:id"),
            {"sub": subject_a, "id": v["outsider"]},
        )
        connection.execute(
            text(
                "insert into app_users(id,igreja_id,nome,email,status,clerk_user_id) "
                "values(:id,:tenant,'Equipe B sintética','b@example.test','ativo',:sub)"
            ),
            {"id": user_b, "tenant": v["other"], "sub": subject_b},
        )
    _insert_session(database, jti=jti_a, tenant=v["t"], app_user_id=v["outsider"])
    _insert_session(database, jti=jti_b, tenant=v["other"], app_user_id=user_b)

    with _scoped_db(database, v["t"], subject_a) as session:
        result = session.execute(
            update(AuthSession)
            .where(AuthSession.jti == jti_b)
            .values(revoked_at=text("now()"))
        )
        assert result.rowcount == 0

    with database.connect() as connection:
        assert connection.scalar(
            text("select revoked_at from auth_sessions where jti=:jti"),
            {"jti": jti_b},
        ) is None


def test_logout_revokes_token_and_followup_request_returns_401(database, seeded):
    v = seeded
    subject = "logout-subject"
    with database.begin() as connection:
        connection.execute(
            text("update app_users set clerk_user_id=:sub where id=:id"),
            {"sub": subject, "id": v["uid"]},
        )
    clerk = _clerk()
    token, jti = _token(clerk, subject)
    _insert_session(database, jti=jti, tenant=v["t"], app_user_id=v["uid"])
    app = _app(database, v["t"], subject, clerk)

    with TestClient(app) as client:
        assert client.post("/auth/logout").status_code == 401
        response = client.post(
            "/auth/logout", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 204, response.text
        rejected = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert rejected.status_code == 401, rejected.text

    with database.connect() as connection:
        assert connection.scalar(
            text("select revoked_at from auth_sessions where jti=:jti"),
            {"jti": jti},
        ) is not None


def test_removing_member_revokes_sessions_and_returns_401(database, seeded):
    v = seeded
    admin_subject, target_subject = "team-admin-session", "removed-member-session"
    with database.begin() as connection:
        connection.execute(
            text("update app_users set clerk_user_id=:sub where id=:id"),
            {"sub": admin_subject, "id": v["uid"]},
        )
        connection.execute(
            text("update app_users set clerk_user_id=:sub where id=:id"),
            {"sub": target_subject, "id": v["leader"]},
        )
    clerk = _clerk()
    token, jti = _token(clerk, target_subject)
    _insert_session(database, jti=jti, tenant=v["t"], app_user_id=v["leader"])
    admin = CurrentUser(
        app_user_id=str(v["uid"]),
        clerk_user_id=admin_subject,
        igreja_id=str(v["t"]),
        email="admin@example.test",
        nome="Admin sintético",
        roles=frozenset({"admin"}),
    )
    app = _app(database, v["t"], admin_subject, clerk, current_user=admin)

    with TestClient(app) as client:
        removed = client.delete(f"/team/{v['leader']}")
        assert removed.status_code == 200, removed.text

        def target_db_override():
            session = _scoped_db(database, v["t"], target_subject)
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = target_db_override
        app.dependency_overrides.pop(get_current_user)
        rejected = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert rejected.status_code == 401, rejected.text

    with database.connect() as connection:
        assert connection.scalar(
            text("select revoked_at from auth_sessions where jti=:jti"),
            {"jti": jti},
        ) is not None
        assert connection.scalar(
            text("select status from app_users where id=:id"),
            {"id": v["leader"]},
        ) == "revogado"
