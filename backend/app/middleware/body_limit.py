"""Bound request bodies before FastAPI parses and buffers their JSON."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services.storage import MAX_MEDIA_BYTES

# Ordinary API payloads are small JSON documents.  Two MiB also preserves the
# existing 1.5-million-character church-logo contract and bounded bulk lists,
# without letting one request make Starlette/Pydantic buffer an arbitrary body.
MAX_JSON_REQUEST_BODY_BYTES = 2 * 1024 * 1024

# Base64 grows the binary payload to 4 * ceil(n / 3).  The JSON envelope can
# additionally contain MIME/name/caption fields. Pydantic caps those at 255,
# 255 and 4,096 characters; 64 KiB also accommodates worst-case JSON escaping
# plus field names and separators without allowing arbitrary ignored fields.
MAX_MEDIA_BASE64_CHARS = 4 * ((MAX_MEDIA_BYTES + 2) // 3)
MAX_MEDIA_JSON_OVERHEAD_BYTES = 64 * 1024
MAX_MEDIA_REQUEST_BODY_BYTES = (
    MAX_MEDIA_BASE64_CHARS + MAX_MEDIA_JSON_OVERHEAD_BYTES
)

# Keep the Evolution endpoint's existing router-level contract.  The outer
# guard prevents buffering first; the router still authenticates and validates
# the same one-megabyte maximum itself.
MAX_WEBHOOK_REQUEST_BODY_BYTES = 1024 * 1024

_MEDIA_UPLOAD_PATH = re.compile(r"^/conversations/[^/]+/messages/media/?$")
_WEBHOOK_PATH = re.compile(r"^/whatsapp/webhook/?$")
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_MEDIA_TOO_LARGE_DETAIL = "Arquivo excede o limite de 16 MB."
_WEBHOOK_TOO_LARGE_DETAIL = "Payload do webhook excede o limite permitido"
_JSON_TOO_LARGE_DETAIL = "Corpo da requisição excede o limite permitido."


class _RequestBodyTooLarge(HTTPException):
    """Internal signal raised by the guarded ASGI receive callable."""

    def __init__(self, detail: str) -> None:
        # FastAPI deliberately preserves HTTPException while translating an
        # arbitrary body-read exception to a generic 400. This keeps chunked
        # overflows observable as the same 413 used for Content-Length.
        super().__init__(status_code=413, detail=detail)


def _content_length(headers: list[tuple[bytes, bytes]]) -> int | None:
    """Return a valid non-negative Content-Length, otherwise stream-count."""
    for name, value in headers:
        if name.lower() != b"content-length":
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None
    return None


class RequestBodyLimitMiddleware:
    """Reject oversized API bodies without buffering them in the app."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int = MAX_JSON_REQUEST_BODY_BYTES,
        max_media_body_bytes: int = MAX_MEDIA_REQUEST_BODY_BYTES,
        max_webhook_body_bytes: int = MAX_WEBHOOK_REQUEST_BODY_BYTES,
    ) -> None:
        if min(max_body_bytes, max_media_body_bytes, max_webhook_body_bytes) < 1:
            raise ValueError("body limits must be positive")
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.max_media_body_bytes = max_media_body_bytes
        self.max_webhook_body_bytes = max_webhook_body_bytes

    @staticmethod
    def _body_policy(scope: Mapping[str, Any]) -> str | None:
        if scope.get("type") != "http" or scope.get("method") not in _BODY_METHODS:
            return None

        path = str(scope.get("path", ""))
        if scope.get("method") == "POST" and _MEDIA_UPLOAD_PATH.fullmatch(path):
            return "media"
        if scope.get("method") == "POST" and _WEBHOOK_PATH.fullmatch(path):
            return "webhook"
        return "json"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        policy = self._body_policy(scope)
        if policy is None:
            await self.app(scope, receive, send)
            return

        if policy == "media":
            body_limit = self.max_media_body_bytes
            detail = _MEDIA_TOO_LARGE_DETAIL
        elif policy == "webhook":
            body_limit = self.max_webhook_body_bytes
            detail = _WEBHOOK_TOO_LARGE_DETAIL
        else:
            body_limit = self.max_body_bytes
            detail = _JSON_TOO_LARGE_DETAIL

        declared_length = _content_length(scope.get("headers", []))
        if declared_length is not None and declared_length > body_limit:
            await self._reject(scope, receive, send, detail)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > body_limit:
                    raise _RequestBodyTooLarge(detail)
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            await self._reject(scope, receive, send, detail)

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        detail: str,
    ) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": detail},
        )
        await response(scope, receive, send)


# Keep the public name used by the app wiring while broadening its protection.
MediaUploadBodyLimitMiddleware = RequestBodyLimitMiddleware
