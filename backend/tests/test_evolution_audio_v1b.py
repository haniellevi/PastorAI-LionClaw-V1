"""Bounded V1b media retrieval without changing legacy media resolution."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.config import Settings
from app.services.evolution import EvolutionClient, EvolutionError


def _settings() -> Settings:
    return Settings(
        allow_real_sends=True,
        evolution_api_url="http://evolution.invalid",
        evolution_api_key="synthetic-key",
    )


def _use_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    real = httpx.Client

    def fake(*args, **kwargs):
        kwargs.pop("transport", None)
        return real(*args, transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "Client", fake)


def _stream_json(body: dict[str, str], *, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        headers=headers,
        stream=httpx.ByteStream(json.dumps(body).encode("utf-8")),
    )


def test_limited_audio_fetch_streams_and_decodes_only_bounded_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = base64.b64encode(b"audio").decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/getBase64FromMediaMessage/instance")
        assert json.loads(request.content)["message"]["key"]["id"] == "message"
        assert request.headers["accept-encoding"] == "identity"
        return _stream_json({"base64": payload, "mimetype": "audio/ogg"})

    _use_transport(monkeypatch, handler)

    media, mime = EvolutionClient(_settings()).get_audio_media_bytes_limited(
        "instance",
        {"id": "message", "remoteJid": "5511000000000@s.whatsapp.net", "fromMe": False},
        max_bytes=5,
        timeout_seconds=2.0,
    )

    assert media == b"audio"
    assert mime == "audio/ogg"


def test_limited_audio_fetch_rejects_content_length_before_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": "9999999"},
            content=b'{"base64":"Zm9v"}',
        )

    _use_transport(monkeypatch, handler)

    with pytest.raises(EvolutionError):
        EvolutionClient(_settings()).get_audio_media_bytes_limited(
            "instance", {"id": "message"}, max_bytes=5, timeout_seconds=2.0
        )


def test_limited_audio_fetch_rejects_compressed_response_before_raw_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            content=b"not-read",
        )

    _use_transport(monkeypatch, handler)

    with pytest.raises(EvolutionError):
        EvolutionClient(_settings()).get_audio_media_bytes_limited(
            "instance", {"id": "message"}, max_bytes=5, timeout_seconds=2.0
        )


@pytest.mark.parametrize(
    "body",
    [
        {"base64": base64.b64encode(b"six!!!").decode("ascii")},
        {"base64": "not valid base64***"},
    ],
)
def test_limited_audio_fetch_rejects_oversize_or_invalid_base64(
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, str],
) -> None:
    _use_transport(monkeypatch, lambda _request: _stream_json(body))

    with pytest.raises(EvolutionError):
        EvolutionClient(_settings()).get_audio_media_bytes_limited(
            "instance", {"id": "message"}, max_bytes=5, timeout_seconds=2.0
        )
