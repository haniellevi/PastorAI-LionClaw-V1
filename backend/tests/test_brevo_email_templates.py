"""Contrato visual e de acessibilidade dos e-mails transacionais da Igreja 12."""

from __future__ import annotations

import json

import httpx

from app.config import Settings
from app.services.brevo import BrevoClient


def _settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "frontend_url": "https://app.igreja12.com.br",
        "brevo_api_url": "https://api.brevo.com/v3",
        "brevo_api_key": "test-brevo-key",
        "brevo_from_email": "no-reply@igreja12.com.br",
        "brevo_from_name": "Igreja 12",
        "allow_real_sends": True,
    }
    values.update(overrides)
    return Settings(**values)


def _capture_payload(monkeypatch) -> dict:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(201, json={"messageId": "message-123"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    return captured


def test_invite_uses_shared_brand_layout_and_plain_text(monkeypatch) -> None:
    payload = _capture_payload(monkeypatch)
    link = "https://app.igreja12.com.br/#ativar/token?source=email&next=painel"

    message_id = BrevoClient(_settings()).send_invite(
        to_email="raniel@example.com",
        nome="Raniel <Admin>",
        activation_link=link,
    )

    assert message_id == "message-123"
    assert payload["subject"] == "Você foi convidado para a Igreja 12"
    assert payload["to"] == [{"email": "raniel@example.com", "name": "Raniel <Admin>"}]
    assert "<!doctype html>" in payload["htmlContent"]
    assert "Gestão pastoral inteligente" in payload["htmlContent"]
    assert "/brand/diamante-simbolo-128.png" in payload["htmlContent"]
    assert "#092038" in payload["htmlContent"]
    assert "#2b5cb4" in payload["htmlContent"]
    assert "Ativar meu acesso" in payload["htmlContent"]
    assert "Raniel &lt;Admin&gt;" in payload["htmlContent"]
    assert "Raniel <Admin>" not in payload["htmlContent"]
    assert link in payload["textContent"]
    assert 'href="https://app.igreja12.com.br/privacidade"' in payload["htmlContent"]
    assert 'href="https://app.igreja12.com.br/termos"' in payload["htmlContent"]
    for legacy_green in ("#0d9488", "#0f766e", "#0b3a35", "#5eead4", "#082220"):
        assert legacy_green not in payload["htmlContent"].lower()


def test_password_reset_explains_expiry_and_single_use(monkeypatch) -> None:
    payload = _capture_payload(monkeypatch)
    link = "https://app.igreja12.com.br/#redefinir-senha/safe-token"

    message_id = BrevoClient(_settings(password_reset_ttl_minutes=45)).send_password_reset(
        to_email="raniel@example.com",
        reset_link=link,
    )

    assert message_id == "message-123"
    assert payload["subject"] == "Redefina sua senha com segurança — Igreja 12"
    assert "Redefinir minha senha" in payload["htmlContent"]
    assert "45 minutos" in payload["htmlContent"]
    assert "só pode ser usado uma vez" in payload["htmlContent"]
    assert "45 minutos" in payload["textContent"]
    assert link in payload["textContent"]
