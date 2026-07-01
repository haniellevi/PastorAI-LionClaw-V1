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
        # allow_real_sends=True: estes testes exercitam o caminho de ENVIO real
        # (httpx mockado). O guard B2 (outbound_guard) bloquearia em não-produção;
        # aqui habilitamos para validar o comportamento de envio em si. O bloqueio
        # do guard é testado em test_outbound_guard.py.
        allow_real_sends=True,
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


# ---- media: receive (getBase64) + send (sendMedia) — Etapa 2 --------------
def test_get_media_base64_returns_data_and_mime(monkeypatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"base64": "Zm9v", "mimetype": "image/png"})

    _use_transport(monkeypatch, handler)
    data, mime = EvolutionClient(_settings()).get_media_base64(
        "igreja-1", {"id": "M1", "remoteJid": "x@s.whatsapp.net", "fromMe": False}
    )
    assert data == "Zm9v"
    assert mime == "image/png"
    assert seen["url"].endswith("/chat/getBase64FromMediaMessage/igreja-1")
    assert seen["body"]["message"]["key"]["id"] == "M1"


def test_get_media_base64_raises_when_empty(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"base64": ""})

    _use_transport(monkeypatch, handler)
    with pytest.raises(EvolutionError):
        EvolutionClient(_settings()).get_media_base64("igreja-1", {"id": "M1"})


def test_send_media_posts_payload(monkeypatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"key": {"id": "X"}})

    _use_transport(monkeypatch, handler)
    ok = EvolutionClient(_settings()).send_media(
        "igreja-1",
        "5511999990000",
        mediatype="image",
        media_base64="Zm9v",
        mime="image/png",
        caption="oi",
    )
    assert ok is True
    assert seen["url"].endswith("/message/sendMedia/igreja-1")
    assert seen["body"]["number"] == "5511999990000"
    assert seen["body"]["mediatype"] == "image"
    assert seen["body"]["media"] == "Zm9v"
    assert seen["body"]["caption"] == "oi"


def test_send_media_raises_on_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    _use_transport(monkeypatch, handler)
    with pytest.raises(EvolutionError):
        EvolutionClient(_settings()).send_media(
            "igreja-1",
            "5511999990000",
            mediatype="document",
            media_base64="Zm9v",
            mime="application/pdf",
            filename="a.pdf",
        )


# ---- foto de perfil (fetchProfilePictureUrl) — Etapa 4 --------------------
def test_fetch_profile_picture_url_returns_url(monkeypatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"profilePictureUrl": "https://cdn/x.jpg"})

    _use_transport(monkeypatch, handler)
    url = EvolutionClient(_settings()).fetch_profile_picture_url("igreja-1", "5599")
    assert url == "https://cdn/x.jpg"
    assert seen["url"].endswith("/chat/fetchProfilePictureUrl/igreja-1")
    assert seen["body"]["number"] == "5599"


def test_fetch_profile_picture_url_none_when_no_photo(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    _use_transport(monkeypatch, handler)
    assert EvolutionClient(_settings()).fetch_profile_picture_url("i", "5599") is None


def test_fetch_profile_picture_url_none_on_404(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    _use_transport(monkeypatch, handler)
    assert EvolutionClient(_settings()).fetch_profile_picture_url("i", "5599") is None


def test_fetch_profile_picture_url_none_on_transport_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    _use_transport(monkeypatch, handler)
    assert EvolutionClient(_settings()).fetch_profile_picture_url("i", "5599") is None


# ---- connect / reconnect: QR, nested QR, pairing code, restart 404 --------
def test_connect_returns_qr_base64(monkeypatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/instance/create"):
            return httpx.Response(201, json={})
        if "/instance/connect/" in path:
            seen["connect_url"] = str(request.url)
            return httpx.Response(
                200, json={"base64": "data:image/png;base64,AAA", "code": "2@abc"}
            )
        if "/webhook/set/" in path:
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected path {path}")  # pragma: no cover

    _use_transport(monkeypatch, handler)
    res = EvolutionClient(_settings()).connect("igreja-1")
    assert res.qr == "data:image/png;base64,AAA"
    assert res.pairing_code is None
    assert res.status == "reconectando"
    # Sem número informado -> modo QR (não anexa ?number=).
    assert "number=" not in seen["connect_url"]


def test_connect_reads_nested_qrcode(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/instance/create"):
            return httpx.Response(409, json={})  # já existe
        if "/instance/connect/" in path:
            return httpx.Response(
                200,
                json={"qrcode": {"base64": "data:image/png;base64,NEST", "pairingCode": None}},
            )
        if "/webhook/set/" in path:
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected path {path}")  # pragma: no cover

    _use_transport(monkeypatch, handler)
    res = EvolutionClient(_settings()).connect("igreja-1")
    assert res.qr == "data:image/png;base64,NEST"
    assert res.pairing_code is None


def test_connect_with_number_returns_pairing_code(monkeypatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/instance/create"):
            return httpx.Response(201, json={})
        if "/instance/connect/" in path:
            seen["connect_url"] = str(request.url)
            # Evolution devolve o code (texto do QR) + o pairingCode numérico.
            return httpx.Response(200, json={"pairingCode": "ABCD-1234", "code": "2@abc"})
        if "/webhook/set/" in path:
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected path {path}")  # pragma: no cover

    _use_transport(monkeypatch, handler)
    res = EvolutionClient(_settings()).connect("igreja-1", numero="5511999998888")
    assert res.pairing_code == "ABCD-1234"
    # O `code` é texto do QR, não imagem: nunca vira QR.
    assert res.qr is None
    assert res.status == "reconectando"
    assert "number=5511999998888" in seen["connect_url"]


def test_reconnect_survives_restart_404_and_ensures_instance(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append((request.method, path))
        if path.endswith("/instance/create"):
            return httpx.Response(409, json={})  # já existe
        if "/instance/restart/" in path:
            return httpx.Response(404, json={"error": "not found"})
        if "/instance/connect/" in path:
            return httpx.Response(200, json={"base64": "QR"})
        if "/webhook/set/" in path:
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected path {path}")  # pragma: no cover

    _use_transport(monkeypatch, handler)
    res = EvolutionClient(_settings()).reconnect("igreja-1")
    assert res.qr == "QR"
    assert res.status == "reconectando"
    # O restart 404 não abortou; ensure_instance + connect rodaram mesmo assim.
    assert any(m == "POST" and p.endswith("/instance/create") for m, p in calls)
    assert any("/instance/restart/" in p for _, p in calls)
    assert any("/instance/connect/" in p for _, p in calls)


def test_reconnect_survives_restart_transport_error_with_number(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/instance/create"):
            return httpx.Response(201, json={})
        if "/instance/restart/" in path:
            raise httpx.ConnectError("boom")  # restart indisponível
        if "/instance/connect/" in path:
            return httpx.Response(200, json={"pairingCode": "WXYZ-9876"})
        if "/webhook/set/" in path:
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected path {path}")  # pragma: no cover

    _use_transport(monkeypatch, handler)
    res = EvolutionClient(_settings()).reconnect("igreja-1", numero="5511999998888")
    assert res.pairing_code == "WXYZ-9876"
    assert res.status == "reconectando"


def test_reconnect_with_number_resets_session_before_pairing(monkeypatch) -> None:
    # Evolution v2.3.7 só emite pairingCode se a sessão foi RESETADA antes do
    # connect com número; numa instância já em "connecting" ele ignora o número e
    # devolve só o QR. reconnect faz o restart primeiro — este teste falha se o
    # caminho voltar a usar connect direto (sem reset), pegando o QR silenciosamente.
    state = {"restarted": False}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/instance/create"):
            return httpx.Response(409, json={})  # já existe / conectando
        if "/instance/restart/" in path:
            state["restarted"] = True
            return httpx.Response(200, json={})
        if "/instance/connect/" in path:
            has_number = "number=" in str(request.url)
            if has_number and state["restarted"]:
                return httpx.Response(200, json={"pairingCode": "PAIR-0001", "code": "2@x"})
            # sessão em "connecting" sem reset -> Evolution ignora o número, só QR
            return httpx.Response(200, json={"base64": "QRONLY"})
        if "/webhook/set/" in path:
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected path {path}")  # pragma: no cover

    _use_transport(monkeypatch, handler)
    res = EvolutionClient(_settings()).reconnect("igreja-1", numero="5511999998888")
    assert res.pairing_code == "PAIR-0001"
    assert res.qr is None
