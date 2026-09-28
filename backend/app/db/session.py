"""Database engine and session management (Supabase/Postgres).

Provides a SQLAlchemy engine built from DATABASE_URL and a request-scoped
session dependency. The session is used both for ORM access and for injecting
the tenant context that drives Postgres RLS (see rls.py).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import InvalidatePoolError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None

_POOL_CHECKOUT_TIMEOUT_SECONDS = 5
_POSTGRES_CONNECT_TIMEOUT_SECONDS = 5
# libpq TCP keepalives: an idle pooled connection sends a probe every 30 s, which
# keeps NAT/load-balancer state alive and lets the kernel notice a dead peer
# (30 s + 3 x 10 s) instead of a request hanging on it.
_POSTGRES_KEEPALIVE_ARGS = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
}
_LAST_CHECKIN_KEY = "pastorai_last_checkin"


def _install_idle_pre_ping(engine: Engine, idle_seconds: float) -> None:
    """Ping a pooled connection only when it sat idle for ``idle_seconds``.

    ``pool_pre_ping=True`` pays one database round trip (~185 ms to Supabase
    us-west-2) on every checkout, even for a connection returned a moment ago.
    Here a connection reused within ``idle_seconds`` skips the ping; an older one
    is pinged exactly like pre-ping does, and a disconnect invalidates the pool
    so the checkout retries on a fresh connection. A freshly opened connection
    has no check-in stamp (the stamp is cleared on reconnect) and is not pinged.
    """
    dialect = engine.dialect

    def _stamp_checkin(_dbapi_connection: Any, connection_record: Any) -> None:
        connection_record.info[_LAST_CHECKIN_KEY] = time.monotonic()

    def _ping_if_idle(
        dbapi_connection: Any, connection_record: Any, _connection_proxy: Any
    ) -> None:
        last_checkin = connection_record.info.get(_LAST_CHECKIN_KEY)
        if last_checkin is None or time.monotonic() - last_checkin < idle_seconds:
            return
        # Public do_ping, not SQLAlchemy's internal _do_ping_w_event: a failed
        # ping here does not dispatch `handle_error` events. The app registers
        # no such listener today; add one here if that ever changes.
        try:
            dialect.do_ping(dbapi_connection)
        except dialect.loaded_dbapi.Error as exc:
            if dialect.is_disconnect(exc, dbapi_connection, None):
                raise InvalidatePoolError(
                    "idle pooled connection failed its ping"
                ) from exc
            raise

    event.listen(engine, "checkin", _stamp_checkin)
    event.listen(engine, "checkout", _ping_if_idle)


def get_engine() -> Engine:
    """Lazily build the SQLAlchemy engine with a sane connection pool.

    Built lazily so the app (and tests) can import modules without requiring a
    live database connection until a request actually needs one.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not configured")
        idle_seconds = settings.db_pool_ping_idle_seconds
        engine = create_engine(
            settings.database_url,
            # 0 keeps SQLAlchemy's ping on every checkout (rollback lever).
            pool_pre_ping=idle_seconds == 0,
            pool_size=5,
            max_overflow=10,
            pool_timeout=_POOL_CHECKOUT_TIMEOUT_SECONDS,
            pool_recycle=1800,
            connect_args={
                "connect_timeout": _POSTGRES_CONNECT_TIMEOUT_SECONDS,
                **_POSTGRES_KEEPALIVE_ARGS,
            },
            future=True,
        )
        if idle_seconds > 0:
            _install_idle_pre_ping(engine, idle_seconds)
        _engine = engine
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
    return _SessionFactory


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a transactional session with cleanup.

    The session is closed on completion (graceful resource release). Callers
    that mutate data must commit explicitly.
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


# Registra (uma única vez) o listener after_begin do seam profundo de tenant
# (PR2 / D2). É um efeito do import de session.py de propósito: assim que o
# módulo do pool de sessões existe, o seam já reaplica o escopo em toda sessão
# MARCADA (session.info). Para sessões não-marcadas o listener é no-op, então
# este registro NÃO altera o comportamento dos caminhos legados.
from app.db.tenant_session import register_after_begin_listener  # noqa: E402

register_after_begin_listener()
