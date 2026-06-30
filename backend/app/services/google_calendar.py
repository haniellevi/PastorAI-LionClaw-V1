"""Google Calendar client — mirror church events (RF-39).

Creates/updates/deletes events on a Google Calendar via the REST API using an
OAuth access token. Failures are normalized to `GoogleCalendarError` so callers
can mark the event as not synchronized instead of failing the whole request.

EVT-6 PR6.0: este cliente NÃO está mais ligado ao `POST /events`. Ele usa o
token/calendar GLOBAIS de `settings` ("Legacy"), nunca os tokens OAuth por igreja
em `calendar_sync` — em produção isso escreveria todos os tenants numa única conta
Google (risco multi-tenant). A classe é mantida (e seguro pelo guard B2),
reservada para um push POR IGREJA de fase futura que leia o token correto.
Nenhum caminho ativo o invoca hoje; o uso atual é só nos testes do guard B2.
"""

from __future__ import annotations

import datetime as dt
import logging

import httpx

from app.config import Settings, get_settings
from app.services.outbound_guard import external_sends_allowed, log_suppressed

logger = logging.getLogger("pastorai.gcal")


class GoogleCalendarError(Exception):
    """Raised when a Google Calendar call fails or is misconfigured."""


def _to_rfc3339(data: dt.date, hora: str | None) -> tuple[dict, dict]:
    """Build start/end blocks. With a time -> timed event; otherwise all-day."""
    if hora:
        try:
            parsed = dt.datetime.strptime(hora.strip(), "%H:%M").time()
        except ValueError as exc:
            raise GoogleCalendarError("Hora inválida (use HH:MM)") from exc
        start_dt = dt.datetime.combine(data, parsed)
        end_dt = start_dt + dt.timedelta(hours=1)
        return (
            {"dateTime": start_dt.isoformat(), "timeZone": "America/Sao_Paulo"},
            {"dateTime": end_dt.isoformat(), "timeZone": "America/Sao_Paulo"},
        )
    next_day = data + dt.timedelta(days=1)
    return ({"date": data.isoformat()}, {"date": next_day.isoformat()})


class GoogleCalendarClient:
    """Thin HTTP client around the Google Calendar events endpoints."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _require_config(self) -> tuple[str, str, str]:
        base_url = self._settings.google_calendar_api_url
        token = self._settings.google_calendar_access_token
        calendar_id = self._settings.google_calendar_id or "primary"
        if not base_url or not token:
            raise GoogleCalendarError("Google Calendar is not configured")
        return base_url.rstrip("/"), token, calendar_id

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def create_event(
        self,
        *,
        titulo: str,
        data: dt.date,
        hora: str | None,
        descricao: str | None,
    ) -> str:
        """Create an event and return its Google event id."""
        if not external_sends_allowed(self._settings):
            log_suppressed("Google Calendar", "create_event")
            raise GoogleCalendarError(
                "Google Calendar desativado fora de producao (guard B2)"
            )
        base_url, token, calendar_id = self._require_config()
        start, end = _to_rfc3339(data, hora)
        payload: dict[str, object] = {"summary": titulo, "start": start, "end": end}
        if descricao:
            payload["description"] = descricao
        try:
            with httpx.Client(base_url=base_url, timeout=15.0) as client:
                resp = client.post(
                    f"/calendars/{calendar_id}/events",
                    headers=self._headers(token),
                    json=payload,
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Google Calendar create failed: %s", type(exc).__name__)
            raise GoogleCalendarError("Falha ao sincronizar com Google Calendar") from exc
        except (ValueError, KeyError) as exc:
            logger.warning("Unexpected Google Calendar response shape")
            raise GoogleCalendarError("Resposta inesperada do Google Calendar") from exc
        return str(body["id"])

    def delete_event(self, google_event_id: str) -> None:
        """Best-effort delete of a previously synced event."""
        if not external_sends_allowed(self._settings):
            log_suppressed("Google Calendar", "delete_event")
            return
        base_url, token, calendar_id = self._require_config()
        try:
            with httpx.Client(base_url=base_url, timeout=15.0) as client:
                resp = client.delete(
                    f"/calendars/{calendar_id}/events/{google_event_id}",
                    headers=self._headers(token),
                )
                if resp.status_code not in (200, 204, 404, 410):
                    resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Google Calendar delete failed: %s", type(exc).__name__)
            raise GoogleCalendarError("Falha ao remover evento no Google Calendar") from exc


def get_google_calendar_client() -> GoogleCalendarClient:
    """FastAPI dependency / factory for the Google Calendar client."""
    return GoogleCalendarClient()
