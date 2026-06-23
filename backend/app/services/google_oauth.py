"""Google OAuth 2.0 — connect a church's existing Google Calendar (events F1).

Implements the web-server OAuth flow (offline access → refresh_token), token
refresh and the calendar-list call. The OAuth ``state`` is a short-lived JWT
signed with the panel session secret, carrying the igreja_id so the (public)
callback can attribute the consent to the right tenant without a session.

Failures are normalized to ``GoogleOAuthError`` and never leak the secret.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from app.config import Settings, get_settings

logger = logging.getLogger("pastorai.gcal_oauth")

_STATE_ALG = "HS256"
_STATE_PURPOSE = "gcal_oauth"
_STATE_TTL_MIN = 10
# Read/write events + read the calendar list (to let the admin pick one).
_SCOPES = (
    "https://www.googleapis.com/auth/calendar.events "
    "https://www.googleapis.com/auth/calendar.readonly"
)


class GoogleOAuthError(Exception):
    """Raised when the OAuth flow fails or is misconfigured."""


@dataclass(frozen=True)
class OAuthTokens:
    """Tokens returned by the authorization-code / refresh exchanges."""

    access_token: str
    refresh_token: str | None
    expires_in: int


class GoogleOAuthClient:
    """Thin client around Google's OAuth + calendarList endpoints."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _require_config(self) -> tuple[str, str, str]:
        s = self._settings
        if not (
            s.google_oauth_client_id
            and s.google_oauth_client_secret
            and s.google_oauth_redirect_uri
        ):
            raise GoogleOAuthError("Google OAuth não está configurado")
        return (
            s.google_oauth_client_id,
            s.google_oauth_client_secret,
            s.google_oauth_redirect_uri,
        )

    # ---- state (CSRF + tenant attribution) ---------------------------------
    def sign_state(self, igreja_id: str) -> str:
        now = dt.datetime.now(dt.timezone.utc)
        payload = {
            "purpose": _STATE_PURPOSE,
            "igreja_id": str(igreja_id),
            "iat": now,
            "exp": now + dt.timedelta(minutes=_STATE_TTL_MIN),
        }
        return jwt.encode(
            payload, self._settings.effective_session_secret, algorithm=_STATE_ALG
        )

    def verify_state(self, state: str) -> str:
        """Return the igreja_id from a valid state, else raise."""
        try:
            claims = jwt.decode(
                state,
                self._settings.effective_session_secret,
                algorithms=[_STATE_ALG],
            )
        except jwt.PyJWTError as exc:
            raise GoogleOAuthError("state inválido ou expirado") from exc
        if claims.get("purpose") != _STATE_PURPOSE or not claims.get("igreja_id"):
            raise GoogleOAuthError("state inválido")
        return str(claims["igreja_id"])

    # ---- flow --------------------------------------------------------------
    def build_consent_url(self, igreja_id: str) -> str:
        client_id, _, redirect_uri = self._require_config()
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": self.sign_state(igreja_id),
        }
        return f"{self._settings.google_oauth_auth_url}?{urlencode(params)}"

    def exchange_code(self, code: str) -> OAuthTokens:
        client_id, client_secret, redirect_uri = self._require_config()
        return self._token_request(
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }
        )

    def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        client_id, client_secret, _ = self._require_config()
        return self._token_request(
            {
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            }
        )

    def _token_request(self, data: dict) -> OAuthTokens:
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(self._settings.google_oauth_token_url, data=data)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Google token request failed: %s", type(exc).__name__)
            raise GoogleOAuthError("Falha na troca de tokens com o Google") from exc
        except ValueError as exc:
            raise GoogleOAuthError("Resposta inesperada do Google (token)") from exc
        access = body.get("access_token")
        if not access:
            raise GoogleOAuthError("Google não retornou access_token")
        return OAuthTokens(
            access_token=str(access),
            refresh_token=body.get("refresh_token"),
            expires_in=int(body.get("expires_in") or 3600),
        )

    def list_calendars(self, access_token: str) -> list[dict]:
        """Return the user's calendars as ``[{id, summary, primary}]``."""
        base = self._settings.google_calendar_api_url.rstrip("/")
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    f"{base}/users/me/calendarList",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Google calendarList failed: %s", type(exc).__name__)
            raise GoogleOAuthError("Falha ao listar as agendas do Google") from exc
        except ValueError as exc:
            raise GoogleOAuthError("Resposta inesperada do Google (calendarList)") from exc
        items = body.get("items") or []
        return [
            {
                "id": it.get("id"),
                "summary": it.get("summary"),
                "primary": bool(it.get("primary")),
            }
            for it in items
            if isinstance(it, dict) and it.get("id")
        ]


def get_google_oauth_client() -> GoogleOAuthClient:
    """FastAPI dependency / factory for the Google OAuth client."""
    return GoogleOAuthClient()
