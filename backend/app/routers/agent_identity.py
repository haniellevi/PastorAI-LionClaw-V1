"""Panel endpoint that consumes an S3 identity challenge without exposing it."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.services.agent_identity import (
    AgentIdentityConfirmationDenied,
    AgentIdentityError,
    confirm_identity_challenge,
    parse_challenge_code,
)
from app.services.clerk import ClerkAuthError, ClerkIdentity, ClerkClient, get_clerk_client


router = APIRouter(prefix="/agent/identity-confirmations", tags=["agent-identity"])

_GENERIC_CONFIRMATION_DETAIL = {"error": "identity_confirmation_unavailable"}
_MAX_CHALLENGE_CHARS = 36
_MAX_CONFIRMATION_BODY_BYTES = 256


@dataclass(frozen=True)
class ConfirmingPanelPrincipal:
    """A request-local JWT recheck paired with the already scoped CurrentUser."""

    current_user: CurrentUser
    identity: ClerkIdentity


def _generic_confirmation_error(status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail=_GENERIC_CONFIRMATION_DETAIL)


def _bearer_token(authorization: str | None) -> str | None:
    if not isinstance(authorization, str):
        return None
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token or token.strip() != token:
        return None
    return token


def get_confirming_panel_principal(
    authorization: Annotated[str | None, Header()] = None,
    current_user: CurrentUser = Depends(get_current_user),
    clerk: ClerkClient = Depends(get_clerk_client),
) -> ConfirmingPanelPrincipal:
    """Reverify the local PastorAI JWT without contacting Clerk.

    ``get_current_user`` authenticated and tenant-scoped the request first.  A
    second local verification gives confirmation its own server-derived claims
    snapshot for the post-lock password-change check in the service.
    """

    token = _bearer_token(authorization)
    if token is None:
        raise _generic_confirmation_error(status.HTTP_401_UNAUTHORIZED)
    try:
        identity = clerk.verify_session_token(token)
    except ClerkAuthError as exc:
        raise _generic_confirmation_error(status.HTTP_401_UNAUTHORIZED) from exc
    if identity.clerk_user_id != current_user.clerk_user_id:
        raise _generic_confirmation_error(status.HTTP_401_UNAUTHORIZED)
    return ConfirmingPanelPrincipal(current_user=current_user, identity=identity)


async def _challenge_from_body(request: Request) -> str:
    """Read a tiny bounded JSON body without FastAPI's echoing 422 payload."""

    declared_length = request.headers.get("content-length")
    try:
        if declared_length is not None and int(declared_length) > _MAX_CONFIRMATION_BODY_BYTES:
            raise ValueError("corpo excede o teto")
        if declared_length is not None and int(declared_length) < 0:
            raise ValueError("content-length inválido")
        raw_body = bytearray()
        async for chunk in request.stream():
            raw_body.extend(chunk)
            if len(raw_body) > _MAX_CONFIRMATION_BODY_BYTES:
                raise ValueError("corpo excede o teto")
        payload = json.loads(bytes(raw_body))
    except Exception as exc:  # noqa: BLE001 - one generic client outcome
        raise _generic_confirmation_error(status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    if (
        type(payload) is not dict
        or set(payload) != {"challenge"}
        or not isinstance(payload.get("challenge"), str)
        or len(payload["challenge"]) != _MAX_CHALLENGE_CHARS
        or parse_challenge_code(payload["challenge"]) is None
    ):
        raise _generic_confirmation_error(status.HTTP_422_UNPROCESSABLE_CONTENT)
    return payload["challenge"]


@router.post("")
def confirm_identity(
    challenge: str = Depends(_challenge_from_body),
    db: Session = Depends(get_db),
    principal: ConfirmingPanelPrincipal = Depends(get_confirming_panel_principal),
) -> dict[str, str]:
    """Consume exactly one current challenge and return no correlator or PII."""

    try:
        confirm_identity_challenge(
            db,
            igreja_id=uuid.UUID(principal.current_user.igreja_id),
            app_user_id=uuid.UUID(principal.current_user.app_user_id),
            clerk_user_id=principal.identity.clerk_user_id,
            session_claims=principal.identity.claims,
            challenge=challenge,
            session_secret=get_settings().effective_session_secret,
        )
        db.commit()
    except AgentIdentityConfirmationDenied as exc:
        if exc.audit_logged:
            try:
                db.commit()
            except (IntegrityError, TypeError, ValueError):
                db.rollback()
        else:
            db.rollback()
        raise _generic_confirmation_error(status.HTTP_409_CONFLICT) from None
    except (AgentIdentityError, IntegrityError, TypeError, ValueError):
        db.rollback()
        raise _generic_confirmation_error(status.HTTP_409_CONFLICT) from None
    return {"status": "confirmed"}
