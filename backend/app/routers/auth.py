"""Auth router — api-login (SPEC 3.2: POST /auth/login -> {token, churchId}).

Login authenticates email+password via Clerk (RNF-01: no passwords stored),
resolves the linked igreja and returns a session token plus the churchId.

Security:
  - Invalid credentials return a single generic error that never reveals
    whether the email exists (US-01).
  - A suspended/delinquent igreja blocks login with a billing notice (US-35).
  - A valid Clerk account with no linked app_user is rejected clearly (US-02).
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppUser
from app.db.session import get_db
from app.deps import BLOCKING_IGREJA_STATUSES, CurrentUser, get_current_user
from app.services.clerk import ClerkAuthError, ClerkClient, get_clerk_client

logger = logging.getLogger("pastorai.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

# Pragmatic email shape check (avoids an extra email-validator dependency).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Single generic message — must not distinguish unknown email vs wrong password.
_GENERIC_LOGIN_ERROR = "E-mail ou senha inválidos"


class LoginRequest(BaseModel):
    """Login payload validated at the edge."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL_RE.match(value):
            raise ValueError("E-mail inválido")
        return value


class LoginResponse(BaseModel):
    """Login success contract."""

    token: str
    churchId: str  # noqa: N815 - external contract uses camelCase


class MeResponse(BaseModel):
    """Authenticated principal snapshot (handy for the frontend bootstrap)."""

    appUserId: str  # noqa: N815
    churchId: str  # noqa: N815
    email: str
    nome: str
    roles: list[str]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_GENERIC_LOGIN_ERROR,
    )


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
    clerk: ClerkClient = Depends(get_clerk_client),
) -> LoginResponse:
    """Authenticate and return {token, churchId}.

    Failure modes return the same generic 401 to avoid leaking which emails
    exist; billing blocks return a distinct 403 with billing context.
    """
    try:
        token, clerk_user_id = clerk.authenticate_password(
            payload.email, payload.password
        )
    except ClerkAuthError:
        # Generic — never reveals whether the email is registered.
        raise _unauthorized() from None

    app_user = db.execute(
        select(AppUser).where(AppUser.clerk_user_id == clerk_user_id)
    ).scalar_one_or_none()

    if app_user is None:
        # Authenticated at Clerk but not linked to an igreja: keep it generic
        # at login to avoid disclosing account state to anonymous callers.
        logger.info("Login with no linked app_user for clerk_user_id (masked)")
        raise _unauthorized() from None

    igreja_status = app_user.igreja.status if app_user.igreja else None
    if igreja_status in BLOCKING_IGREJA_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "billing_blocked",
                "message": "Acesso bloqueado por pendência de assinatura. "
                "Contate o administrador da igreja.",
                "igrejaStatus": igreja_status,
            },
        )

    return LoginResponse(token=token, churchId=str(app_user.igreja_id))


@router.get("/me", response_model=MeResponse)
def me(current_user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    """Return the resolved identity for the current session token."""
    return MeResponse(
        appUserId=current_user.app_user_id,
        churchId=current_user.igreja_id,
        email=current_user.email,
        nome=current_user.nome,
        roles=sorted(current_user.roles),
    )
