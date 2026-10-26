"""Dedicated database login for private Storage maintenance.

Only private deletion tasks and audio upload ownership use this boundary. It
never falls back to ``DATABASE_URL`` and never issues ``SET ROLE``: the login
itself is the identity, proven at the start of every transaction together with
a fixed transaction-local ``search_path`` and tenant GUC. The tenant GUC scopes
rows; it is not the identity. The pool checkout only rejects a persisted tenant
GUC; identity is proven at BEGIN. Send ownership release has its own login
(``app.db.private_send_session``); event fences and summary tasks are outside
this boundary.

The URL user may be ``private_storage_runtime`` (direct connection) or the
Supabase shared-pooler form ``private_storage_runtime.<project-ref>``. The URL
is never the proof: every transaction requires ``session_user`` and
``current_user`` to be exactly ``private_storage_runtime``. Which hosted
endpoint/mode is used must still be validated in the release.
The role-independent proof lives in ``app.db.dedicated_login``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from app.config import get_settings
from app.db import dedicated_login

PRIVATE_STORAGE_ROLE = "private_storage_runtime"
PRIVATE_STORAGE_TENANT_KEY = "private_storage_tenant_igreja_id"
# Fixed name resolution for every transaction (pg_temp explicitly last, so a
# TEMP table cannot shadow public relations); never taken from the URL, the
# role defaults or the environment. Isolated-schema test harnesses may adapt it.
PRIVATE_STORAGE_SEARCH_PATH = "pg_catalog, public, pg_temp"
_LABEL = "private storage"

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


class PrivateStorageUnavailable(RuntimeError):
    """The dedicated login is not configured, unsafe or unproven."""


class PrivateStorageScopeError(PrivateStorageUnavailable):
    """A transaction did not prove the dedicated identity and its tenant."""


def _identity_matches(row: Any, tenant_id: str | None) -> bool:
    return dedicated_login.identity_matches(
        row, role=PRIVATE_STORAGE_ROLE, search_path=PRIVATE_STORAGE_SEARCH_PATH, tenant_id=tenant_id)


def _prove_transaction(session: Session, _transaction: SessionTransaction,
                       connection: Any) -> None:
    """Fix search_path and tenant, then prove the login on every BEGIN.

    Runs post-commit too. Fail-closed: any mismatch raises and the transaction
    never runs a service query.
    """
    if not session.info.get("private_storage_session"):
        return
    if not dedicated_login.prove_transaction(
            connection, role=PRIVATE_STORAGE_ROLE, search_path=PRIVATE_STORAGE_SEARCH_PATH,
            tenant_id=session.info.get(PRIVATE_STORAGE_TENANT_KEY)):
        raise PrivateStorageScopeError("private storage identity verification failed")


def is_private_storage_url_user(username: object) -> bool:
    """Direct ``private_storage_runtime`` or pooler ``private_storage_runtime.<ref>``.

    Only a shape check before connecting; the SQL probe is the identity proof.
    """
    return dedicated_login.is_login_user(username, PRIVATE_STORAGE_ROLE)


def _validated_url() -> str:
    settings = get_settings()
    url = settings.private_storage_database_url
    if not url:
        raise PrivateStorageUnavailable("PRIVATE_STORAGE_DATABASE_URL is not configured")
    parsed = dedicated_login.parse_url(url, "PRIVATE_STORAGE_DATABASE_URL", PrivateStorageUnavailable)
    if not is_private_storage_url_user(parsed.username):
        raise PrivateStorageUnavailable(
            "PRIVATE_STORAGE_DATABASE_URL must authenticate as private_storage_runtime")
    for name, other in (("DATABASE_URL", settings.database_url),
                        ("AGENT_RUNTIME_DATABASE_URL", settings.agent_runtime_database_url),
                        ("PRIVATE_SUMMARY_DATABASE_URL", settings.private_summary_database_url)):
        if other and dedicated_login.parse_url(other, name, PrivateStorageUnavailable) == parsed:
            raise PrivateStorageUnavailable(f"PRIVATE_STORAGE_DATABASE_URL must differ from {name}")
    return url


def get_private_storage_session_factory() -> sessionmaker[Session]:
    """Lazy factory bound only to the dedicated login; no privileged fallback."""
    global _engine, _SessionFactory
    if _SessionFactory is None:
        engine = dedicated_login.create_login_engine(_validated_url(), _LABEL)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                               expire_on_commit=False, future=True,
                               info={"private_storage_session": True})
        event.listen(factory, "after_begin", _prove_transaction)
        _engine, _SessionFactory = engine, factory
    return _SessionFactory


def dispose_private_storage_engine() -> None:
    """Drop the cached engine (configuration change or test teardown)."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = _SessionFactory = None


def scope_private_storage(session: Session, igreja_id: Any) -> str:
    """Pin a fresh dedicated session to one tenant; every BEGIN re-proves it."""
    return dedicated_login.pin_tenant(
        session, igreja_id, info_flag="private_storage_session",
        tenant_key=PRIVATE_STORAGE_TENANT_KEY, label=_LABEL, error=PrivateStorageScopeError)


__all__ = [
    "PRIVATE_STORAGE_ROLE",
    "PRIVATE_STORAGE_SEARCH_PATH",
    "PrivateStorageScopeError",
    "PrivateStorageUnavailable",
    "dispose_private_storage_engine",
    "get_private_storage_session_factory",
    "is_private_storage_url_user",
    "scope_private_storage",
]
