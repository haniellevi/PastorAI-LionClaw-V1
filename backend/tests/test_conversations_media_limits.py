"""Boundary checks that keep inbox media payloads from amplifying memory."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.types import Message

from app.middleware.body_limit import (
    MAX_MEDIA_JSON_OVERHEAD_BYTES,
    MAX_MEDIA_REQUEST_BODY_BYTES,
    MediaUploadBodyLimitMiddleware,
)
from app.routers import conversations
from app.services.storage import MAX_MEDIA_BYTES


def _asgi_request(
    *,
    path: str,
    chunks: list[bytes],
    max_body_bytes: int,
    content_length: int | None = None,
) -> tuple[list[Message], dict[str, object]]:
    """Exercise the pure ASGI guard, including requests without a length."""
    request_events = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    ]
    if not request_events:
        request_events.append(
            {"type": "http.request", "body": b"", "more_body": False}
        )

    state: dict[str, object] = {"handler_ran": False, "body": None}
    sent: list[Message] = []

    async def downstream(scope, receive, send) -> None:
        body = bytearray()
        while True:
            event = await receive()
            body.extend(event.get("body", b""))
            if not event.get("more_body", False):
                break
        # This represents the point after request-body parsing where a route
        # handler could execute. Oversized chunked input must never reach it.
        state["handler_ran"] = True
        state["body"] = bytes(body)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> Message:
        if request_events:
            return request_events.pop(0)  # type: ignore[return-value]
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    headers = []
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode("ascii")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("test", 123),
        "server": ("test", 80),
    }
    middleware = MediaUploadBodyLimitMiddleware(
        downstream, max_body_bytes=max_body_bytes
    )
    asyncio.run(middleware(scope, receive, send))  # type: ignore[arg-type]
    return sent, state


def test_send_media_schema_caps_encoded_payload_before_decode() -> None:
    metadata = conversations.SendMediaRequest.model_fields["base64"].metadata
    limits = [getattr(item, "max_length", None) for item in metadata]
    assert conversations.MAX_MEDIA_BASE64_CHARS in limits


def test_media_request_limit_reuses_file_limit_with_safe_json_overhead() -> None:
    assert MAX_MEDIA_REQUEST_BODY_BYTES == (
        conversations.MAX_MEDIA_BASE64_CHARS + MAX_MEDIA_JSON_OVERHEAD_BYTES
    )
    # JSON may encode each Unicode code point as a surrogate pair (12 bytes).
    max_metadata_chars = 255 + 255 + 4096
    assert MAX_MEDIA_JSON_OVERHEAD_BYTES > max_metadata_chars * 12


def test_media_body_limit_rejects_large_content_length_without_parsing() -> None:
    sent, state = _asgi_request(
        path="/conversations/id/messages/media",
        chunks=[b"ignored"],
        max_body_bytes=8,
        content_length=9,
    )

    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"])["detail"].endswith("16 MB.")
    assert state["handler_ran"] is False


def test_media_body_limit_counts_chunked_body_without_content_length() -> None:
    sent, state = _asgi_request(
        path="/conversations/id/messages/media",
        chunks=[b"1234", b"56789"],
        max_body_bytes=8,
    )

    assert sent[0]["status"] == 413
    assert state["handler_ran"] is False


def test_media_body_limit_keeps_413_through_fastapi_chunked_parsing() -> None:
    state = {"handler_ran": False}
    app = FastAPI()
    app.add_middleware(MediaUploadBodyLimitMiddleware, max_body_bytes=8)

    # Mirror the production outer observability middleware. FastAPI's request
    # parser must preserve our HTTPException instead of translating it to 400.
    @app.middleware("http")
    async def passthrough(request, call_next):
        return await call_next(request)

    @app.post("/conversations/{conversation_id}/messages/media")
    async def media_route(conversation_id: str, payload: dict) -> dict:
        state["handler_ran"] = True
        return payload

    def chunks():
        yield b"1234"
        yield b"56789"

    response = TestClient(app).post(
        "/conversations/id/messages/media",
        content=chunks(),
        headers={"content-type": "application/json"},
    )

    assert "content-length" not in response.request.headers
    assert response.request.headers["transfer-encoding"] == "chunked"
    assert response.status_code == 413
    assert response.json()["detail"].endswith("16 MB.")
    assert state["handler_ran"] is False


def test_media_body_limit_does_not_affect_other_routes() -> None:
    sent, state = _asgi_request(
        path="/conversations/id/messages",
        chunks=[b"1234", b"56789"],
        max_body_bytes=8,
    )

    assert sent[0]["status"] == 204
    assert state == {"handler_ran": True, "body": b"123456789"}


def test_send_media_rejects_decoded_payload_over_limit(monkeypatch) -> None:
    app_user_id = "00000000-0000-0000-0000-0000000000a1"

    class _OversizedDecodedPayload:
        def __len__(self) -> int:
            return MAX_MEDIA_BYTES + 1

    class _DB:
        def execute(self, _query):
            return type(
                "Result",
                (),
                {
                    "scalar_one_or_none": lambda self: type(
                        "Connection",
                        (),
                        {"status": "online", "instance": "igreja-1"},
                    )()
                },
            )()

    conv = type(
        "Conversation",
        (),
        {
            "id": "00000000-0000-0000-0000-0000000000aa",
            "estado": "humano",
            "assumido_por": app_user_id,
            "telefone": "5511999990000",
        },
    )()
    monkeypatch.setattr(conversations, "_get_conversation_for_update", lambda *_: conv)
    monkeypatch.setattr(conversations, "_authorize_conversation_view", lambda *_: None)
    monkeypatch.setattr(
        conversations.base64,
        "b64decode",
        lambda *_args, **_kwargs: _OversizedDecodedPayload(),
    )

    with pytest.raises(HTTPException) as exc_info:
        conversations.send_media_message(
            str(conv.id),
            conversations.SendMediaRequest(
                mime="application/octet-stream", base64="Zm9v"
            ),
            db=_DB(),
            current_user=type(
                "User",
                (),
                {
                    "igreja_id": "00000000-0000-0000-0000-000000000001",
                    "app_user_id": app_user_id,
                    "chat_nome": None,
                    "nome": "Teste",
                },
            )(),
            evolution=object(),
            storage=object(),
        )

    assert exc_info.value.status_code == 413
