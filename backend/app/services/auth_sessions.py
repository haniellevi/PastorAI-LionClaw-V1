"""Persistence and revocation for PastorAI-issued panel session JWTs."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.db.models import AppUser, AuthSession
from app.services.clerk import ClerkClient, ClerkIdentity

_INVALID_SESSION = "Sessão inválida ou expirada"


def _claim_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if type(value) not in (int, float):
        raise ValueError("invalid session timestamp")
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def session_jti(identity: ClerkIdentity) -> str:
    value = identity.claims.get("jti")
    if not isinstance(value, str) or not value or len(value) > 128:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_SESSION,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return value


def register_session(db: Session, clerk: ClerkClient, token: str, app_user: AppUser) -> None:
    """Persist the signed session before returning it to a browser."""
    identity = clerk.verify_session_token(token)
    jti = session_jti(identity)
    if identity.clerk_user_id != app_user.clerk_user_id:
        raise ValueError("session subject does not match app_user")
    issued_at = _claim_datetime(identity.claims.get("iat"))
    expires_at = _claim_datetime(identity.claims.get("exp"))
    if expires_at <= issued_at:
        raise ValueError("invalid session lifetime")

    # Bound registry growth for users who return to the application.
    db.execute(
        delete(AuthSession).where(
            AuthSession.app_user_id == app_user.id,
            AuthSession.igreja_id.is_not_distinct_from(app_user.igreja_id),
            AuthSession.expires_at <= datetime.now(timezone.utc),
        )
    )
    db.add(
        AuthSession(
            jti=jti,
            igreja_id=app_user.igreja_id,
            app_user_id=app_user.id,
            issued_at=issued_at,
            expires_at=expires_at,
        )
    )


def require_active_session(
    db: Session, app_user: AppUser, identity: ClerkIdentity
) -> AuthSession:
    """Reject missing, unknown, or already-revoked session records with 401."""
    session = db.execute(
        select(AuthSession).where(
            AuthSession.jti == session_jti(identity),
            AuthSession.app_user_id == app_user.id,
            AuthSession.igreja_id.is_not_distinct_from(app_user.igreja_id),
        )
    ).scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_SESSION,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return session


def revoke_session(
    db: Session,
    *,
    app_user_id: str,
    jti: str,
    igreja_id: str | None = None,
) -> None:
    query = select(AuthSession).where(
        AuthSession.jti == jti,
        AuthSession.app_user_id == app_user_id,
    )
    if igreja_id is not None:
        query = query.where(AuthSession.igreja_id == igreja_id)
    session = db.execute(query).scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_SESSION,
            headers={"WWW-Authenticate": "Bearer"},
        )
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()


def revoke_user_sessions(db: Session, *, app_user_id: str, igreja_id: str) -> int:
    result = db.execute(
        update(AuthSession)
        .where(
            AuthSession.app_user_id == app_user_id,
            AuthSession.igreja_id == igreja_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=func.now())
    )
    return int(getattr(result, "rowcount", 0) or 0)
