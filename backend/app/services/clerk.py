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
import uuid
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
# Distinct issuer for password-reset links so a reset token can never be used
# as a session token (and vice-versa).
_RESET_ISSUER = "pastorai-reset"
# Distinct issuer for invite/activation links (7-day expiry). A separate issuer
# means an invite token can never double as a session or reset token.
_INVITE_ISSUER = "pastorai-invite"
# Invite link validity (delta-042: "link que expira em 7 dias").
_INVITE_TTL_DAYS = 7


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

    # ---- Shared purpose-token emission (MEDIO-005) --------------------------
    def _mint_purpose_token(
        self,
        subject: str,
        *,
        issuer: str,
        ttl: timedelta,
        extra_claims: dict[str, Any] | None = None,
    ) -> tuple[str, datetime]:
        """Mint an HS256 purpose-scoped JWT under one shared policy (MEDIO-005).

        Emission counterpart of ``verify_purpose_token``: every short-lived,
        purpose-scoped JWT PastorAI issues (session, reset, invite) is built
        here with the same secret, algorithm and base claims (``sub``/``iss``/
        ``iat``/``exp``); only the issuer, the TTL and purpose-specific extra
        claims (e.g. the reset ``jti``) vary per caller. Returns ``(token,
        expires_at)``.
        """
        secret = self._settings.effective_session_secret
        if not secret:
            raise ClerkAuthError("Session secret is not configured")
        now = datetime.now(timezone.utc)
        expires_at = now + ttl
        payload: dict[str, Any] = {
            "sub": subject,
            "iss": issuer,
            "iat": now,
            "exp": expires_at,
        }
        if extra_claims:
            payload.update(extra_claims)
        return jwt.encode(payload, secret, algorithm=_SESSION_ALG), expires_at

    # ---- Session token: PastorAI-issued JWT (panel session) ----------------
    def _mint_session_token(self, clerk_user_id: str) -> str:
        """Mint a short-lived PastorAI session JWT (HS256) for the panel."""
        token, _expires_at = self._mint_purpose_token(
            clerk_user_id,
            issuer=_SESSION_ISSUER,
            ttl=timedelta(hours=self._settings.session_ttl_hours),
        )
        return token

    def verify_session_token(self, token: str) -> ClerkIdentity:
        """Verify a PastorAI-issued session JWT and return the resolved identity.

        Decode+verify is delegated to ``verify_purpose_token`` (SEC-ALTO-004B)
        — the same hardened policy shared with reset/invite/OAuth-state; only
        the ``sub`` VALUE check stays local. Raises ClerkAuthError on any
        validation failure (expired, bad signature, wrong issuer, missing
        subject).
        """
        claims = self.verify_purpose_token(
            token,
            issuer=_SESSION_ISSUER,
            required_claims=("exp", "sub", "iss"),
            invalid_token_message="Invalid session token",
        )
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

    # ---- Password reset (forgot-password flow) ------------------------------
    def mint_reset_token(self, clerk_user_id: str) -> tuple[str, str, datetime]:
        """Mint a short-lived password-reset JWT (HS256, distinct issuer).

        Returns ``(token, jti, expires_at)``. The caller persists ``(jti,
        expires_at)`` in ``password_reset_tokens`` so the link can be redeemed
        exactly once (SEC-3B / MEDIO-003) — the signature alone only proves the
        token was minted by us and hasn't expired, not that it wasn't already
        used.
        """
        jti = str(uuid.uuid4())
        token, expires_at = self._mint_purpose_token(
            clerk_user_id,
            issuer=_RESET_ISSUER,
            ttl=timedelta(minutes=self._settings.password_reset_ttl_minutes),
            extra_claims={"jti": jti},
        )
        return token, jti, expires_at

    def verify_reset_token(self, token: str) -> tuple[str, str]:
        """Verify a password-reset JWT and return ``(clerk_user_id, jti)``.

        Decode+verify delegated to ``verify_purpose_token`` (SEC-ALTO-004B);
        only the ``sub``/``jti`` VALUE checks stay local.
        """
        claims = self.verify_purpose_token(
            token,
            issuer=_RESET_ISSUER,
            required_claims=("exp", "sub", "iss", "jti"),
            invalid_token_message="Invalid or expired reset token",
        )
        subject = claims.get("sub")
        jti = claims.get("jti")
        if not subject or not jti:
            raise ClerkAuthError("Token missing subject or jti")
        return str(subject), str(jti)

    # ---- Invite / activation token (convite ponta a ponta) ------------------
    def mint_invite_token(self, app_user_id: str) -> str:
        """Mint an invite/activation JWT (HS256, 7-day expiry, distinct issuer).

        The subject is the app_user id (the invited account has no Clerk user
        yet). Signed so the link cannot be forged from a raw id.
        """
        token, _expires_at = self._mint_purpose_token(
            app_user_id,
            issuer=_INVITE_ISSUER,
            ttl=timedelta(days=_INVITE_TTL_DAYS),
        )
        return token

    def verify_invite_token(self, token: str) -> str:
        """Verify an invite token and return the app_user_id (sub).

        Decode+verify delegated to ``verify_purpose_token`` (SEC-ALTO-004B);
        only the ``sub`` VALUE check stays local.
        """
        claims = self.verify_purpose_token(
            token,
            issuer=_INVITE_ISSUER,
            required_claims=("exp", "sub", "iss"),
            invalid_token_message="Invalid or expired invite token",
        )
        subject = claims.get("sub")
        if not subject:
            raise ClerkAuthError("Token missing subject")
        return str(subject)

    # ---- Shared purpose-token policy (reused by other short-lived JWTs) -----
    def verify_purpose_token(
        self,
        token: str,
        *,
        issuer: str,
        required_claims: tuple[str, ...],
        invalid_token_message: str = "Invalid or expired token",
    ) -> dict[str, Any]:
        """Decode+verify an HS256 JWT under one hardened policy (SEC-ALTO-004B).

        Centralizes the rules shared by every short-lived, purpose-scoped JWT
        PastorAI issues — session, reset, invite (all three above) and the
        Google Calendar OAuth ``state`` (SEC-ALTO-004): fixed algorithm
        allowlist, panel session secret, pinned issuer, required claims,
        normalized error with no leaked detail. Callers still validate their
        own claim VALUES (e.g. a ``purpose``/tenant field) after this returns.
        """
        if not token:
            raise ClerkAuthError("Empty token")
        secret = self._settings.effective_session_secret
        if not secret:
            raise ClerkAuthError("Session secret is not configured")
        try:
            return jwt.decode(
                token,
                secret,
                algorithms=[_SESSION_ALG],
                issuer=issuer,
                options={"require": list(required_claims), "verify_aud": False},
            )
        except Exception as exc:  # noqa: BLE001 - normalize to one error type
            logger.warning(
                "Purpose token verification failed (issuer=%s): %s",
                issuer,
                type(exc).__name__,
            )
            raise ClerkAuthError(invalid_token_message) from exc

    def find_user_id_by_email(self, email: str) -> str | None:
        """Return the Clerk user id for an e-mail, or None when not found."""
        secret = self._settings.clerk_secret_key
        if not secret:
            raise ClerkAuthError("Clerk secret key is not configured")
        headers = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(base_url=_CLERK_API_BASE, timeout=10.0) as client:
                resp = client.get(
                    "/users",
                    params={"email_address": [email], "limit": 1},
                    headers=headers,
                )
                resp.raise_for_status()
                users = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Clerk user lookup failed: %s", type(exc).__name__)
            raise ClerkAuthError("Lookup failed") from exc
        if not users:
            return None
        return str(users[0]["id"])

    def set_user_password(self, clerk_user_id: str, password: str) -> None:
        """Set a user's password via the Clerk Backend API."""
        secret = self._settings.clerk_secret_key
        if not secret:
            raise ClerkAuthError("Clerk secret key is not configured")
        headers = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(base_url=_CLERK_API_BASE, timeout=10.0) as client:
                resp = client.patch(
                    f"/users/{clerk_user_id}",
                    json={"password": password, "skip_password_checks": True},
                    headers=headers,
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Clerk set-password failed: %s", type(exc).__name__)
            raise ClerkAuthError("Could not set password") from exc

    def create_user(self, email: str, password: str) -> str:
        """Create a Clerk user (email+password) and return its id.

        If the e-mail already has a Clerk account (taken), reuse it and set the
        password — the invitee controls the mailbox. Returns the clerk_user_id
        either way. Raises ClerkAuthError on any failure.
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
                resp = client.post(
                    "/users",
                    json={
                        "email_address": [email],
                        "password": password,
                        "skip_password_checks": True,
                    },
                    headers=headers,
                )
            if resp.status_code in (200, 201):
                return str(resp.json()["id"])
        except httpx.HTTPError as exc:
            logger.warning("Clerk create_user error: %s", type(exc).__name__)
            raise ClerkAuthError("Could not create user") from exc
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Unexpected Clerk response shape in create_user")
            raise ClerkAuthError("Could not create user") from exc

        # Não criou (e-mail provavelmente já cadastrado): reaproveita a conta
        # existente e define a senha informada na ativação.
        existing = self.find_user_id_by_email(email)
        if existing:
            self.set_user_password(existing, password)
            return existing
        logger.warning("Clerk create_user failed (status masked) and no existing user")
        raise ClerkAuthError("Could not create user")


def get_clerk_client() -> ClerkClient:
    """FastAPI dependency / factory for the Clerk client."""
    return ClerkClient()
