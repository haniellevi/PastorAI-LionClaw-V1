"""Clerk authentication helpers (US-01 / RNF-01).

Two responsibilities:

1. Verify a Clerk-issued session JWT on every request (JWKS / RS256).
2. Authenticate an email+password pair against Clerk's Backend API for the
   `POST /auth/login` contract, returning a session token + clerk_user_id.

No passwords are ever stored by PastorAI (RNF-01). Errors are normalized to a
single `ClerkAuthError` so callers can return a generic message that never
reveals whether an email exists (US-01).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

from app.config import Settings, get_settings

logger = logging.getLogger("pastorai.clerk")

_CLERK_API_BASE = "https://api.clerk.com/v1"


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
        self._jwk_client: PyJWKClient | None = None

    # ---- Session token verification -----------------------------------------
    def _get_jwk_client(self) -> PyJWKClient:
        if self._jwk_client is None:
            jwks_url = self._settings.effective_jwks_url
            if not jwks_url:
                raise ClerkAuthError("Clerk JWKS URL is not configured")
            # PyJWKClient caches keys internally between calls.
            self._jwk_client = PyJWKClient(jwks_url)
        return self._jwk_client

    def verify_session_token(self, token: str) -> ClerkIdentity:
        """Verify a Clerk session JWT and return the resolved identity.

        Raises ClerkAuthError on any validation failure (expired, bad
        signature, wrong issuer, missing subject).
        """
        if not token:
            raise ClerkAuthError("Empty token")

        try:
            signing_key = self._get_jwk_client().get_signing_key_from_jwt(token)
            issuer = self._settings.clerk_jwt_issuer or None
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=issuer,
                options={
                    "require": ["exp", "sub"],
                    "verify_iss": bool(issuer),
                    "verify_aud": False,
                },
            )
        except ClerkAuthError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize to one error type
            # Log without leaking the token contents.
            logger.warning("Clerk token verification failed: %s", type(exc).__name__)
            raise ClerkAuthError("Invalid session token") from exc

        subject = claims.get("sub")
        if not subject:
            raise ClerkAuthError("Token missing subject")
        return ClerkIdentity(clerk_user_id=str(subject), claims=claims)

    # ---- Password sign-in (Backend API) -------------------------------------
    def authenticate_password(self, email: str, password: str) -> tuple[str, str]:
        """Authenticate email+password via Clerk and return (token, clerk_user_id).

        Uses Clerk's Backend API to verify the password and mint a session
        token. Any failure raises ClerkAuthError with no email-existence signal.
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

                # 3) Mint a session and its token.
                session_resp = client.post(
                    "/sessions",
                    json={"user_id": clerk_user_id},
                    headers=headers,
                )
                session_resp.raise_for_status()
                session_id = str(session_resp.json()["id"])

                token_resp = client.post(
                    f"/sessions/{session_id}/tokens",
                    headers=headers,
                )
                token_resp.raise_for_status()
                token = str(token_resp.json()["jwt"])
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
