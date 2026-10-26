"""Dedicated database login that only releases agent send ownership.

The queue worker inserts, renews and checks ``private_deletion_sends`` inside
its domain transactions on the main login; only the release after the provider
boundary returns runs here, through ``private_send_release``. The role has no
table grant and no access to messages, conversations, paths or audio. It never
falls back to ``DATABASE_URL`` and never issues ``SET ROLE``: every transaction
proves ``session_user``/``current_user``, the role attributes, a fixed
``search_path`` (``pg_temp`` last) and the tenant GUC, as in
``app.db.privacy_storage_session`` (shared mechanics in ``dedicated_login``).

URL user: ``private_send_runtime`` (direct) or the Supabase shared-pooler form
``private_send_runtime.<project-ref>``; the SQL probe, not the URL, is the proof.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from app.config import get_settings
from app.db import dedicated_login

PRIVATE_SEND_ROLE = "private_send_runtime"
PRIVATE_SEND_TENANT_KEY = "private_send_tenant_igreja_id"
# Read at call time; isolated-schema test harnesses may adapt it.
PRIVATE_SEND_SEARCH_PATH = "pg_catalog, public, pg_temp"
_LABEL = "private send"

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


class PrivateSendUnavailable(RuntimeError):
    """The dedicated send login is not configured, unsafe or unproven."""


class PrivateSendScopeError(PrivateSendUnavailable):
    """A transaction did not prove the dedicated identity and its tenant."""


def _identity_matches(row: Any, tenant_id: str | None) -> bool:
    return dedicated_login.identity_matches(
        row, role=PRIVATE_SEND_ROLE, search_path=PRIVATE_SEND_SEARCH_PATH, tenant_id=tenant_id)


def _prove_transaction(session: Session, _transaction: SessionTransaction,
                       connection: Any) -> None:
    if not session.info.get("private_send_session"):
        return
    if not dedicated_login.prove_transaction(
            connection, role=PRIVATE_SEND_ROLE, search_path=PRIVATE_SEND_SEARCH_PATH,
            tenant_id=session.info.get(PRIVATE_SEND_TENANT_KEY)):
        raise PrivateSendScopeError("private send identity verification failed")


def is_private_send_url_user(username: object) -> bool:
    return dedicated_login.is_login_user(username, PRIVATE_SEND_ROLE)


def _validated_url() -> str:
    settings = get_settings()
    url = settings.private_send_database_url
    if not url:
        raise PrivateSendUnavailable("PRIVATE_SEND_DATABASE_URL is not configured")
    parsed = dedicated_login.parse_url(url, "PRIVATE_SEND_DATABASE_URL", PrivateSendUnavailable)
    if not is_private_send_url_user(parsed.username):
        raise PrivateSendUnavailable("PRIVATE_SEND_DATABASE_URL must authenticate as private_send_runtime")
    for name, other in (("DATABASE_URL", settings.database_url),
                        ("AGENT_RUNTIME_DATABASE_URL", settings.agent_runtime_database_url),
                        ("PRIVATE_STORAGE_DATABASE_URL", settings.private_storage_database_url)):
        if other and dedicated_login.parse_url(other, name, PrivateSendUnavailable) == parsed:
            raise PrivateSendUnavailable(f"PRIVATE_SEND_DATABASE_URL must differ from {name}")
    return url


def get_private_send_session_factory() -> sessionmaker[Session]:
    """Lazy factory bound only to the dedicated login; no privileged fallback."""
    global _engine, _SessionFactory
    if _SessionFactory is None:
        engine = dedicated_login.create_login_engine(_validated_url(), _LABEL)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                               expire_on_commit=False, future=True,
                               info={"private_send_session": True})
        event.listen(factory, "after_begin", _prove_transaction)
        _engine, _SessionFactory = engine, factory
    return _SessionFactory


def dispose_private_send_engine() -> None:
    """Drop the cached engine (configuration change or test teardown)."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = _SessionFactory = None


def scope_private_send(session: Session, igreja_id: Any) -> str:
    """Pin a fresh dedicated session to one tenant; every BEGIN re-proves it."""
    return dedicated_login.pin_tenant(
        session, igreja_id, info_flag="private_send_session",
        tenant_key=PRIVATE_SEND_TENANT_KEY, label=_LABEL, error=PrivateSendScopeError)


__all__ = [
    "PRIVATE_SEND_ROLE",
    "PRIVATE_SEND_SEARCH_PATH",
    "PrivateSendScopeError",
    "PrivateSendUnavailable",
    "dispose_private_send_engine",
    "get_private_send_session_factory",
    "is_private_send_url_user",
    "scope_private_send",
]
