"""Authentication helpers (US-01 / RNF-01).

Two responsibilities:

1. Authenticate an email+password pair against Clerk's Backend API for the
   `POST /auth/login` contract (Clerk verifies the password; no password is
   ever stored — RNF-01).
2. Mint and verify PastorAI's OWN session JWT (HS256). The panel session is
   decoupled from Clerk's short-lived (~1 min) session tokens so users are not
   logged out after a minute; Clerk is only touched at login.

Errors are normalized to a single `ClerkAuthError` so callers can return a
generic message that never reveals whether an email exists (US-01).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt

from app.config import Settings, get_settings

logger = logging.getLogger("pastorai.clerk")

_CLERK_API_BASE = "https://api.clerk.com/v1"

# PastorAI-issued session JWT (HS256) — see module docstring.
_SESSION_ISSUER = "pastorai"
_SESSION_ALG = "HS256"


class ClerkAuthError(Exception):
    """Raised when a Clerk token is invalid or credentials fail.

    Intentionally carries no detail that distinguishes "wrong password" from
    "unknown email" — the caller maps it to a single generic response.
    """


@dataclass(frozen=True)
class ClerkIdentity:
    """Resolved identity from a verified Clerk session token."""

    clerk_user_id: str
    claims: dict[str, Any]


class ClerkClient:
    """Thin client around Clerk JWKS verification and the Backend API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    # ---- Session token: PastorAI-issued JWT (panel session) ----------------
    def _mint_session_token(self, clerk_user_id: str) -> str:
        """Mint a short-lived PastorAI session JWT (HS256) for the panel."""
        secret = self._settings.effective_session_secret
        if not secret:
            raise ClerkAuthError("Session secret is not configured")
        now = datetime.now(timezone.utc)
        payload = {
            "sub": clerk_user_id,
            "iss": _SESSION_ISSUER,
            "iat": now,
            "exp": now + timedelta(hours=self._settings.session_ttl_hours),
        }
        return jwt.encode(payload, secret, algorithm=_SESSION_ALG)

    def verify_session_token(self, token: str) -> ClerkIdentity:
        """Verify a PastorAI-issued session JWT and return the resolved identity.

        Raises ClerkAuthError on any validation failure (expired, bad
        signature, wrong issuer, missing subject).
        """
        if not token:
            raise ClerkAuthError("Empty token")

        secret = self._settings.effective_session_secret
        if not secret:
            raise ClerkAuthError("Session secret is not configured")

        try:
            claims = jwt.decode(
                token,
                secret,
                algorithms=[_SESSION_ALG],
                issuer=_SESSION_ISSUER,
                options={
                    "require": ["exp", "sub", "iss"],
                    "verify_aud": False,
                },
            )
        except ClerkAuthError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize to one error type
            # Log without leaking the token contents.
            logger.warning("Session token verification failed: %s", type(exc).__name__)
            raise ClerkAuthError("Invalid session token") from exc

        subject = claims.get("sub")
        if not subject:
            raise ClerkAuthError("Token missing subject")
        return ClerkIdentity(clerk_user_id=str(subject), claims=claims)

    # ---- Password sign-in (Backend API) -------------------------------------
    def authenticate_password(self, email: str, password: str) -> tuple[str, str]:
        """Authenticate email+password via Clerk and return (token, clerk_user_id).

        Clerk's Backend API verifies the password; PastorAI then mints its own
        session token (see `_mint_session_token`). Any failure raises
        ClerkAuthError with no email-existence signal.
        """
        secret = self._settings.clerk_secret_key
        if not secret:
            raise ClerkAuthError("Clerk secret key is not configured")

        headers = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(base_url=_CLERK_API_BASE, timeout=10.0) as client:
                # 1) Find the user by email.
                user_resp = client.get(
                    "/users",
                    params={"email_address": [email], "limit": 1},
                    headers=headers,
                )
                user_resp.raise_for_status()
                users = user_resp.json()
                if not users:
                    raise ClerkAuthError("Invalid credentials")
                clerk_user_id = str(users[0]["id"])

                # 2) Verify the password for that user.
                verify_resp = client.post(
                    f"/users/{clerk_user_id}/verify_password",
                    json={"password": password},
                    headers=headers,
                )
                if verify_resp.status_code != 200 or not verify_resp.json().get(
                    "verified", False
                ):
                    raise ClerkAuthError("Invalid credentials")

                # 3) Password verified. Mint a PastorAI session token (HS256,
                #    hours-long) instead of Clerk's short-lived session token so
                #    the panel session does not expire after ~1 minute. Still no
                #    password is ever stored (RNF-01).
                token = self._mint_session_token(clerk_user_id)
        except ClerkAuthError:
            raise
        except httpx.HTTPError as exc:
            logger.warning("Clerk Backend API error during login: %s", type(exc).__name__)
            raise ClerkAuthError("Authentication failed") from exc
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Unexpected Clerk response shape during login")
            raise ClerkAuthError("Authentication failed") from exc

        return token, clerk_user_id


def get_clerk_client() -> ClerkClient:
    """FastAPI dependency / factory for the Clerk client."""
    return ClerkClient()
