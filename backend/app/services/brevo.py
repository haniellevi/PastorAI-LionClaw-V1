"""Brevo (ex-Sendinblue) email client — team activation invites (RF-40).

Sends the activation link to a newly invited team member via Brevo's
transactional email API (`POST /v3/smtp/email`, `api-key` header). Failures are
normalized to `BrevoError` and logged without leaking the API key.
"""

from __future__ import annotations

import logging

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger("pastorai.brevo")


class BrevoError(Exception):
    """Raised when the Brevo API call fails or is misconfigured."""


def _activation_html(nome: str, link: str) -> str:
    return (
        f"<p>Olá, {nome}!</p>"
        "<p>Você foi convidado(a) para a equipe da Igreja 12. "
        "Clique no botão abaixo para ativar seu acesso:</p>"
        f'<p><a href="{link}">Ativar acesso</a></p>'
        f"<p>Ou copie e cole este link no navegador:<br>{link}</p>"
    )


class BrevoClient:
    """Thin HTTP client around the Brevo transactional-email endpoint."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _require_config(self) -> tuple[str, str, str, str]:
        base_url = self._settings.brevo_api_url
        api_key = self._settings.brevo_api_key
        from_email = self._settings.brevo_from_email
        from_name = self._settings.brevo_from_name
        if not base_url or not api_key or not from_email:
            raise BrevoError("Brevo API is not configured")
        return base_url.rstrip("/"), api_key, from_email, from_name

    def send_invite(self, *, to_email: str, nome: str, activation_link: str) -> str:
        """Send the activation email; returns the Brevo message id."""
        base_url, api_key, from_email, from_name = self._require_config()
        headers = {
            "api-key": api_key,
            "accept": "application/json",
            "content-type": "application/json",
        }
        payload = {
            "sender": {"name": from_name, "email": from_email},
            "to": [{"email": to_email, "name": nome}],
            "subject": "Seu convite para a equipe da Igreja 12",
            "htmlContent": f"<html><body>{_activation_html(nome, activation_link)}</body></html>",
        }
        try:
            with httpx.Client(base_url=base_url, timeout=15.0) as client:
                resp = client.post("/smtp/email", headers=headers, json=payload)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Brevo send failed: %s", type(exc).__name__)
            raise BrevoError("Falha ao enviar e-mail de convite") from exc
        except (ValueError, KeyError) as exc:
            logger.warning("Unexpected Brevo response shape")
            raise BrevoError("Resposta inesperada do Brevo") from exc
        return str(body.get("messageId", ""))


def get_brevo_client() -> BrevoClient:
    """FastAPI dependency / factory for the Brevo client."""
    return BrevoClient()
