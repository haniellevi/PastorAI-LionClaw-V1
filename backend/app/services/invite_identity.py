"""Global identity guard shared by every AppUser invitation surface.

``app_users.email`` is not yet protected by a database UNIQUE constraint and a
tenant-scoped session cannot see pending invitations from another church due
to RLS.  Invitation routes therefore use a small, dedicated cross-tenant
session for exactly two operations: acquire the canonical e-mail advisory lock
and check whether any AppUser already owns the normalized address.  FastAPI
keeps this dependency alive until the route finishes, so the lock spans the
caller transaction's commit without weakening the caller's tenant scope.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import AppUser
from app.db.session import get_session_factory
from app.db.tenant_session import mark_cross_tenant
from app.services.clerk import ClerkAuthError, ClerkClient

_INVITE_EMAIL_LOCK_NAMESPACE = "app-user-invite-email:v1"


def invite_email_advisory_key(email: str) -> int:
    """Return the stable signed bigint used by all invitation routes."""

    normalized = email.strip().lower()
    material = f"{_INVITE_EMAIL_LOCK_NAMESPACE}:{normalized}".encode("utf-8")
    return int.from_bytes(
        hashlib.blake2b(material, digest_size=8).digest(),
        byteorder="big",
        signed=True,
    )


def get_invite_identity_db() -> Iterator[Session]:
    """Yield a fresh, narrowly-scoped BYPASSRLS session for invite identity.

    This must remain a distinct dependency from ``get_db``.  Reusing the
    request's tenant-pinned session would make another church's pending invite
    invisible, while attempting to unpin it would violate the tenant-session
    seam.  Closing rolls back this read-only guard transaction and releases its
    transaction-level advisory lock.
    """

    session = get_session_factory()()
    mark_cross_tenant(session, source="invite_identity_guard")
    try:
        yield session
    finally:
        session.close()


def assert_invite_email_available(
    db: Session, clerk: ClerkClient, email: str
) -> None:
    """Serialize and validate the global e-mail identity before an invite."""

    normalized = email.strip().lower()
    db.execute(
        text("SELECT pg_advisory_xact_lock(:invite_email_key)"),
        {"invite_email_key": invite_email_advisory_key(normalized)},
    )
    existing = db.execute(
        select(AppUser.id)
        .where(func.lower(AppUser.email) == normalized)
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um acesso com este e-mail.",
        )
    try:
        clerk_existing = clerk.find_user_id_by_email(normalized)
    except ClerkAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível validar o e-mail para convite.",
        ) from exc
    if clerk_existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este e-mail não está disponível para um novo acesso.",
        )
