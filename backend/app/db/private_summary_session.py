"""Dedicated database login for the cron's private summary generation cycle.

Discovery, claim, reservation, projections and publication of
``app.services.private_summaries.process_tasks`` run here, never on the main
login. The role reads/writes only the four private summary tables it is
granted (budget excluded) and reaches central tables solely through typed
``private_summary_runtime_*`` functions. It never falls back to
``DATABASE_URL`` and never issues ``SET ROLE``: every transaction proves
``session_user``/``current_user``, the role attributes, a fixed
``search_path`` (``pg_temp`` last) and the tenant GUC, as in
``app.db.private_send_session`` (shared mechanics in ``dedicated_login``).
Discovery uses an unpinned session (no tenant GUC); each task pins one church.

URL user: ``private_summary_runtime`` (direct) or the Supabase shared-pooler
form ``private_summary_runtime.<project-ref>``; the SQL probe is the proof.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from app.config import get_settings
from app.db import dedicated_login

PRIVATE_SUMMARY_ROLE = "private_summary_runtime"
PRIVATE_SUMMARY_TENANT_KEY = "private_summary_tenant_igreja_id"
PRIVATE_SUMMARY_SEARCH_PATH = "pg_catalog, public, pg_temp"
_LABEL = "private summary"

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


class PrivateSummaryUnavailable(RuntimeError):
    """The dedicated summary login is not configured, unsafe or unproven."""


class PrivateSummaryScopeError(PrivateSummaryUnavailable):
    """A session or transaction did not prove the dedicated identity and its tenant."""


def _identity_matches(row: Any, tenant_id: str | None) -> bool:
    return dedicated_login.identity_matches(
        row, role=PRIVATE_SUMMARY_ROLE, search_path=PRIVATE_SUMMARY_SEARCH_PATH, tenant_id=tenant_id)


def _prove_transaction(session: Session, _transaction: SessionTransaction,
                       connection: Any) -> None:
    if not session.info.get("private_summary_session"):
        return
    if not dedicated_login.prove_transaction(
            connection, role=PRIVATE_SUMMARY_ROLE, search_path=PRIVATE_SUMMARY_SEARCH_PATH,
            tenant_id=session.info.get(PRIVATE_SUMMARY_TENANT_KEY)):
        raise PrivateSummaryScopeError("private summary identity verification failed")


def is_private_summary_url_user(username: object) -> bool:
    return dedicated_login.is_login_user(username, PRIVATE_SUMMARY_ROLE)


def _validated_url() -> str:
    settings = get_settings()
    url = settings.private_summary_database_url
    if not url:
        raise PrivateSummaryUnavailable("PRIVATE_SUMMARY_DATABASE_URL is not configured")
    parsed = dedicated_login.parse_url(url, "PRIVATE_SUMMARY_DATABASE_URL", PrivateSummaryUnavailable)
    if not is_private_summary_url_user(parsed.username):
        raise PrivateSummaryUnavailable("PRIVATE_SUMMARY_DATABASE_URL must authenticate as private_summary_runtime")
    for name, other in (("DATABASE_URL", settings.database_url),
                        ("AGENT_RUNTIME_DATABASE_URL", settings.agent_runtime_database_url),
                        ("PRIVATE_STORAGE_DATABASE_URL", settings.private_storage_database_url),
                        ("PRIVATE_SEND_DATABASE_URL", settings.private_send_database_url)):
        if other and dedicated_login.parse_url(other, name, PrivateSummaryUnavailable) == parsed:
            raise PrivateSummaryUnavailable(f"PRIVATE_SUMMARY_DATABASE_URL must differ from {name}")
    return url


def get_private_summary_session_factory() -> sessionmaker[Session]:
    """Lazy factory bound only to the dedicated login; no privileged fallback."""
    global _engine, _SessionFactory
    if _SessionFactory is None:
        engine = dedicated_login.create_login_engine(_validated_url(), _LABEL)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                               expire_on_commit=False, future=True,
                               info={"private_summary_session": True})
        event.listen(factory, "after_begin", _prove_transaction)
        _engine, _SessionFactory = engine, factory
    return _SessionFactory


def dispose_private_summary_engine() -> None:
    """Drop the cached engine (configuration change or test teardown)."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = _SessionFactory = None


def require_private_summary_session(session: Session) -> None:
    """Refuse, before any query, a session not bound to the dedicated login."""
    if not session.info.get("private_summary_session"):
        raise PrivateSummaryScopeError("session is not bound to the private summary login")


def scope_private_summary(session: Session, igreja_id: Any) -> str:
    """Pin a fresh dedicated session to one tenant; every BEGIN re-proves it."""
    return dedicated_login.pin_tenant(
        session, igreja_id, info_flag="private_summary_session",
        tenant_key=PRIVATE_SUMMARY_TENANT_KEY, label=_LABEL, error=PrivateSummaryScopeError)


__all__ = [
    "PRIVATE_SUMMARY_ROLE",
    "PRIVATE_SUMMARY_SEARCH_PATH",
    "PrivateSummaryScopeError",
    "PrivateSummaryUnavailable",
    "dispose_private_summary_engine",
    "get_private_summary_session_factory",
    "is_private_summary_url_user",
    "require_private_summary_session",
    "scope_private_summary",
]
