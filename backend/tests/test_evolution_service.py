"""Unit tests for EvolutionClient.set_webhook (US-08).

The webhook registration is what makes a freshly-connected instance forward
messages to the backend. These tests pin: the token is appended to the callback
URL as a query param, the request hits /webhook/set/{instance}, the nested v2.1+
body is tried first with a flat fallback, and a missing callback URL is a no-op.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.services.evolution import EvolutionClient, EvolutionError


def _use_transport(monkeypatch, handler) -> None:
    """Route every httpx.Client through a MockTransport with `handler`."""
    transport = httpx.MockTransport(handler)
    real = httpx.Client

    def fake(*args, **kwargs):
        kwargs.pop("transport", None)
        return real(*args, transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "Client", fake)


def _settings(**over) -> Settings:
    base = dict(
        evolution_api_url="http://evo:8080",
        evolution_api_key="key",
        evolution_webhook_secret="s3cr3t",
        evolution_webhook_callback_url="http://backend:8000/whatsapp/webhook",
    )
    base.update(over)
    return Settings(**base)


def test_set_webhook_posts_token_url(monkeypatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"webhook": {"enabled": True}})

    _use_transport(monkeypatch, handler)

    assert EvolutionClient(_settings()).set_webhook("igreja-1") is True
    assert seen["url"].endswith("/webhook/set/igreja-1")
    assert (
        seen["body"]["webhook"]["url"]
        == "http://backend:8000/whatsapp/webhook?token=s3cr3t"
    )
    assert seen["body"]["webhook"]["events"] == ["MESSAGES_UPSERT"]
    assert seen["body"]["webhook"]["webhookByEvents"] is False


def test_set_webhook_falls_back_to_flat(monkeypatch) -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if "webhook" in body:  # nested shape rejected by older servers
            return httpx.Response(400, json={"error": "bad request"})
        return httpx.Response(200, json={"enabled": True})

    _use_transport(monkeypatch, handler)

    assert EvolutionClient(_settings()).set_webhook("igreja-1") is True
    assert len(calls) == 2
    assert "webhook" in calls[0]  # nested tried first
    assert "webhook" not in calls[1]  # flat fallback
    assert calls[1]["url"].endswith("?token=s3cr3t")


def test_set_webhook_appends_token_when_url_has_query(monkeypatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    _use_transport(monkeypatch, handler)

    settings = _settings(
        evolution_webhook_callback_url="http://backend:8000/whatsapp/webhook?x=1"
    )
    assert EvolutionClient(settings).set_webhook("igreja-1") is True
    assert seen["body"]["webhook"]["url"].endswith("?x=1&token=s3cr3t")


def test_set_webhook_noop_without_callback_url(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not POST without a callback url")

    _use_transport(monkeypatch, handler)
    assert (
        EvolutionClient(_settings(evolution_webhook_callback_url="")).set_webhook(
            "igreja-1"
        )
        is False
    )


def test_set_webhook_raises_on_http_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    _use_transport(monkeypatch, handler)
    with pytest.raises(EvolutionError):
        EvolutionClient(_settings()).set_webhook("igreja-1")


def test_disconnect_logs_out_instance(monkeypatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"status": "SUCCESS"})

    _use_transport(monkeypatch, handler)

    result = EvolutionClient(_settings()).disconnect("igreja-1")
    assert result.status == "offline"
    assert seen["method"] == "DELETE"
    assert seen["url"].endswith("/instance/logout/igreja-1")


def test_disconnect_idempotent_when_already_logged_out(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "instance not found"})

    _use_transport(monkeypatch, handler)
    assert EvolutionClient(_settings()).disconnect("igreja-1").status == "offline"


def test_disconnect_raises_on_server_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    _use_transport(monkeypatch, handler)
    with pytest.raises(EvolutionError):
        EvolutionClient(_settings()).disconnect("igreja-1")
