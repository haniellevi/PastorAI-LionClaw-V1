"""Database engine and session management (Supabase/Postgres).

Provides a SQLAlchemy engine built from DATABASE_URL and a request-scoped
session dependency. The session is used both for ORM access and for injecting
the tenant context that drives Postgres RLS (see rls.py).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


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
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            pool_recycle=1800,
            future=True,
        )
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
