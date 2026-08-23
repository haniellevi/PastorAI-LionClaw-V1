"""Contrato visual e de acessibilidade dos e-mails transacionais da Igreja 12."""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.services.brevo import BrevoClient, BrevoError


def _settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "frontend_url": "https://app.igreja12.com.br",
        "brevo_api_url": "https://api.brevo.com/v3",
        "brevo_api_key": "test-brevo-key",
        "brevo_from_email": "no-reply@igreja12.com.br",
        "brevo_from_name": "Igreja 12",
        "brevo_send_mode": "live",
        "allow_real_sends": True,
    }
    values.update(overrides)
    return Settings(**values)


def _capture_payload(monkeypatch, *, response: httpx.Response | None = None) -> dict:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return response or httpx.Response(201, json={"messageId": "message-123"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    return captured


@pytest.mark.parametrize("mode", ["", "preview", "canary-only"])
def test_invalid_brevo_send_mode_is_rejected(mode: str) -> None:
    with pytest.raises(ValueError, match="BREVO_SEND_MODE"):
        _settings(brevo_send_mode=mode)


def test_invite_uses_shared_brand_layout_and_plain_text(monkeypatch) -> None:
    payload = _capture_payload(monkeypatch)
    link = "https://app.igreja12.com.br/ativar/token"

    message_id = BrevoClient(_settings()).send_invite(
        to_email="raniel@example.com",
        nome="Raniel <Admin>",
        activation_link=link,
    )

    assert message_id == "message-123"
    assert payload["subject"] == "Você foi convidado para a Igreja 12"
    assert payload["to"] == [
        {
            "email": "raniel@example.com",
            "name": "Raniel <Admin>",
            "contactPixelTrackingConsent": False,
        }
    ]
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
    link = "https://app.igreja12.com.br/redefinir-senha/safe-token"

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
    assert payload["to"] == [
        {
            "email": "raniel@example.com",
            "contactPixelTrackingConsent": False,
        }
    ]


@pytest.mark.parametrize(
    "operation",
    [
        lambda client: client.send_invite(
            to_email="canary@example.com", nome="Canário", activation_link="https://x/a"
        ),
        lambda client: client.send_password_reset(
            to_email="canary@example.com", reset_link="https://x/r"
        ),
    ],
    ids=["invite", "password-reset"],
)
def test_off_mode_blocks_before_http_without_false_success(monkeypatch, operation) -> None:
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Brevo não deveria tocar a rede")
        ),
    )

    with pytest.raises(BrevoError, match="desabilitado"):
        operation(BrevoClient(_settings(brevo_send_mode="off", allow_real_sends=True)))


def test_canary_only_allows_explicit_recipient_without_global_send_gate(monkeypatch) -> None:
    payload = _capture_payload(monkeypatch)
    client = BrevoClient(
        _settings(
            brevo_send_mode="canary",
            brevo_canary_recipients="CANARY@example.com",
            allow_real_sends=False,
        )
    )

    assert (
        client.send_invite(
            to_email="canary@example.com", nome="Canário", activation_link="https://x/a"
        )
        == "message-123"
    )
    assert payload["to"] == [
        {
            "email": "canary@example.com",
            "name": "Canário",
            "contactPixelTrackingConsent": False,
        }
    ]


@pytest.mark.parametrize(
    "recipients,to_email,fragment",
    [
        ("", "canary@example.com", "sem destinatário autorizado"),
        ("canary@example.com", "outside@example.com", "não autorizado"),
        ("not-an-email", "canary@example.com", "Configuração"),
    ],
)
def test_canary_misconfiguration_or_outside_recipient_blocks_before_http(
    monkeypatch, recipients, to_email, fragment
) -> None:
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Brevo não deveria tocar a rede")
        ),
    )
    client = BrevoClient(
        _settings(
            brevo_send_mode="canary",
            brevo_canary_recipients=recipients,
            allow_real_sends=True,
        )
    )

    with pytest.raises(BrevoError, match=fragment):
        client.send_password_reset(to_email=to_email, reset_link="https://x/r")


def test_live_mode_fails_closed_for_missing_config_without_http(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Brevo não deveria tocar a rede")
        ),
    )
    with pytest.raises(BrevoError, match="not configured"):
        BrevoClient(_settings(brevo_api_key="", allow_real_sends=False)).send_invite(
            to_email="canary@example.com", nome="Canário", activation_link="https://x/a"
        )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(201, json={}),
        httpx.Response(201, json={"messageId": ""}),
        httpx.Response(503, json={"code": "temporary"}),
    ],
    ids=["missing-message-id", "blank-message-id", "http-failure"],
)
def test_live_mode_never_treats_invalid_or_failed_provider_response_as_sent(
    monkeypatch, response
) -> None:
    _capture_payload(monkeypatch, response=response)
    with pytest.raises(BrevoError):
        BrevoClient(_settings(allow_real_sends=False)).send_password_reset(
            to_email="canary@example.com", reset_link="https://x/r"
        )
