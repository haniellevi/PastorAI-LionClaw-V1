"""Google OAuth 2.0 — connect a church's existing Google Calendar (events F1).

Implements the web-server OAuth flow (offline access → refresh_token) with
**PKCE S256**, token refresh and the calendar-list call.

OAUTH-CALENDAR-V1: o ``state`` deixou de ser um JWT auto-contido. Agora é um
segredo opaco cuja única função é indexar uma linha de ``calendar_oauth_flows``
(ver ``app.services.calendar_oauth_flows``), que guarda tenant, iniciador e o
``code_verifier`` cifrado. Esta classe não sabe mais o que é ``state``: quem o
gera e valida é o router, contra o banco.

Failures are normalized to ``GoogleOAuthError`` and never leak the secret.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from urllib.parse import quote, urlencode

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger("pastorai.gcal_oauth")

# Read/write events + read the calendar list (to let the admin pick one).
_SCOPES = (
    "https://www.googleapis.com/auth/calendar.events "
    "https://www.googleapis.com/auth/calendar.readonly"
)
# Capacidade mínima que a conexão precisa ter para ser utilizável. Validada por
# PROBE (uma chamada real a calendarList), não pelo campo `scope` da resposta do
# token — a semântica desse campo não é garantida e um `scope` ausente jamais
# pode, sozinho, reprovar uma conexão.
REQUIRED_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


class GoogleOAuthError(Exception):
    """Raised when the OAuth flow fails or is misconfigured."""


@dataclass(frozen=True)
class OAuthTokens:
    """Tokens returned by the authorization-code / refresh exchanges."""

    access_token: str
    refresh_token: str | None
    expires_in: int
    # Escopos que o Google diz ter concedido. Observabilidade apenas — pode vir
    # ausente e nunca é usado como condição de aceite (ver REQUIRED_SCOPE).
    scope: str | None = None


class GoogleOAuthClient:
    """Thin client around Google's OAuth + calendarList endpoints."""

    def __init__(
        self,
        settings: Settings | None = None,
    ) -> None:
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

    # ---- flow --------------------------------------------------------------
    def build_consent_url(self, *, state: str, code_challenge: str) -> str:
        """URL de consentimento com PKCE S256.

        ``state`` é opaco para esta classe (e para o Google): é a chave da linha
        de ``calendar_oauth_flows``. Só o ``code_challenge`` viaja — o verifier
        correspondente fica cifrado no servidor.
        """
        client_id, _, redirect_uri = self._require_config()
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self._settings.google_oauth_auth_url}?{urlencode(params)}"

    def exchange_code(self, code: str, code_verifier: str) -> OAuthTokens:
        """Troca o ``code`` apresentando o ``code_verifier`` do MESMO fluxo.

        O que o PKCE cobre: um code obtido em OUTRA requisição de autorização
        não casa com este verifier — o Google o amarrou ao ``code_challenge``
        daquela requisição — e volta ``invalid_grant`` (400), que
        ``_token_request`` normaliza em ``GoogleOAuthError``.

        O que o PKCE **NÃO** cobre: alguém abrir a URL de autorização ORIGINAL
        deste fluxo noutro navegador e consentir com outra conta Google. O code
        sai amarrado a ESTE mesmo ``code_challenge``, então a troca sucede e os
        tokens são os da conta do terceiro. PKCE prova que o code pertence a
        ESTA requisição — nunca prova QUAL conta consentiu. Quem barra esse
        caminho é a posse obrigatória do ``flowSecret`` no ``finish``; a
        identidade da conta Google segue não verificada
        (ACCOUNT_IDENTITY_RISK_PENDING — ver
        ``docs/security/2026-07-31-oauth-calendar-v1-risk-acceptance.md``).
        """
        client_id, client_secret, redirect_uri = self._require_config()
        return self._token_request(
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
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
        scope = body.get("scope")
        return OAuthTokens(
            access_token=str(access),
            refresh_token=body.get("refresh_token"),
            expires_in=int(body.get("expires_in") or 3600),
            scope=str(scope) if scope else None,
        )

    def list_events(
        self,
        access_token: str,
        calendar_id: str,
        time_min: str,
        time_max: str,
        *,
        max_results: int = 250,
    ) -> list[dict]:
        """Read-only: list a calendar's events in ``[time_min, time_max)``.

        Uses Google Calendar ``events.list`` with ``singleEvents=true`` so
        recurring series are expanded into individual occurrences. This is a GET
        only — it never writes. Tokens are per-igreja (passed in by the caller);
        the global legacy token/calendar are never read here. Returns normalized
        dicts ready for the import-preview response (no ``events`` row written).
        """
        base = self._settings.google_calendar_api_url.rstrip("/")
        params = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": str(max_results),
        }
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    # `calendar_id` vem do que o admin escolheu; escapado para
                    # não escorregar do segmento de path.
                    f"{base}/calendars/{quote(calendar_id, safe='')}/events",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Google events.list failed: %s", type(exc).__name__)
            raise GoogleOAuthError("Falha ao listar eventos do Google") from exc
        except ValueError as exc:
            raise GoogleOAuthError("Resposta inesperada do Google (events)") from exc
        items = body.get("items") or []
        return [
            _normalize_event(it)
            for it in items
            if isinstance(it, dict) and it.get("id") and it.get("status") != "cancelled"
        ]

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


def _split_dt(block: dict) -> tuple[str | None, str | None]:
    """``(date 'YYYY-MM-DD', time 'HH:MM' or None)`` from a start/end block.

    All-day events carry ``date``; timed events carry ``dateTime`` (RFC3339).
    """
    if block.get("date"):  # all-day event
        return str(block["date"]), None
    raw = block.get("dateTime")
    if not raw:
        return None, None
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None, None
    return parsed.date().isoformat(), parsed.strftime("%H:%M")


def _normalize_event(it: dict) -> dict:
    """Map a Google event to the import-preview shape (read-only projection)."""
    data, hora = _split_dt(it.get("start") or {})
    _, fim = _split_dt(it.get("end") or {})
    return {
        "googleEventId": str(it.get("id")),
        "titulo": it.get("summary"),
        "descricao": it.get("description"),
        "data": data,
        "hora": hora,
        "fim": fim,
        # singleEvents=true expands a series, so each occurrence carries
        # recurringEventId; `recurrence` covers the unexpanded master case.
        "recorrente": bool(it.get("recurringEventId") or it.get("recurrence")),
    }


def get_google_oauth_client() -> GoogleOAuthClient:
    """FastAPI dependency / factory for the Google OAuth client."""
    return GoogleOAuthClient()
