"""Resend email client — team activation invites (RF-40).

Sends the activation link to a newly invited team member. Failures are
normalized to `ResendError` and logged without leaking the API key.
"""

from __future__ import annotations

import logging

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger("pastorai.resend")


class ResendError(Exception):
    """Raised when the Resend API call fails or is misconfigured."""


def _activation_html(nome: str, link: str) -> str:
    return (
        f"<p>Olá, {nome}!</p>"
        "<p>Você foi convidado(a) para a equipe no PastorAI. "
        "Clique no botão abaixo para ativar seu acesso:</p>"
        f'<p><a href="{link}">Ativar acesso</a></p>'
        f"<p>Ou copie e cole este link no navegador:<br>{link}</p>"
    )


class ResendClient:
    """Thin HTTP client around the Resend send-email endpoint."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _require_config(self) -> tuple[str, str, str]:
        base_url = self._settings.resend_api_url
        api_key = self._settings.resend_api_key
        from_email = self._settings.resend_from_email
        if not base_url or not api_key or not from_email:
            raise ResendError("Resend API is not configured")
        return base_url.rstrip("/"), api_key, from_email

    def send_invite(self, *, to_email: str, nome: str, activation_link: str) -> str:
        """Send the activation email; returns the Resend message id."""
        base_url, api_key, from_email = self._require_config()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "from": from_email,
            "to": [to_email],
            "subject": "Seu convite para a equipe no PastorAI",
            "html": _activation_html(nome, activation_link),
        }
        try:
            with httpx.Client(base_url=base_url, timeout=15.0) as client:
                resp = client.post("/emails", headers=headers, json=payload)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Resend send failed: %s", type(exc).__name__)
            raise ResendError("Falha ao enviar e-mail de convite") from exc
        except (ValueError, KeyError) as exc:
            logger.warning("Unexpected Resend response shape")
            raise ResendError("Resposta inesperada do Resend") from exc
        return str(body.get("id", ""))


def get_resend_client() -> ResendClient:
    """FastAPI dependency / factory for the Resend client."""
    return ResendClient()
