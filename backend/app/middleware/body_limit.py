"""Bound the inbox media request before FastAPI parses its JSON body.

The binary payload is transported as base64, so the HTTP body is larger than
the 16 MiB file limit enforced by the router and Storage.  This ASGI middleware
counts raw request chunks before Starlette joins them into one bytes object.
Only the media-send endpoint is affected; all other request bodies pass through
unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services.storage import MAX_MEDIA_BYTES

# Base64 grows the binary payload to 4 * ceil(n / 3).  The JSON envelope can
# additionally contain MIME/name/caption fields. Pydantic caps those at 255,
# 255 and 4,096 characters; 64 KiB also accommodates worst-case JSON escaping
# plus field names and separators without allowing arbitrary ignored fields.
MAX_MEDIA_BASE64_CHARS = 4 * ((MAX_MEDIA_BYTES + 2) // 3)
MAX_MEDIA_JSON_OVERHEAD_BYTES = 64 * 1024
MAX_MEDIA_REQUEST_BODY_BYTES = (
    MAX_MEDIA_BASE64_CHARS + MAX_MEDIA_JSON_OVERHEAD_BYTES
)

_MEDIA_UPLOAD_PATH = re.compile(r"^/conversations/[^/]+/messages/media/?$")
_TOO_LARGE_DETAIL = "Arquivo excede o limite de 16 MB."


class _RequestBodyTooLarge(HTTPException):
    """Internal signal raised by the guarded ASGI receive callable."""

    def __init__(self) -> None:
        # FastAPI deliberately preserves HTTPException while translating an
        # arbitrary body-read exception to a generic 400. This keeps chunked
        # overflows observable as the same 413 used for Content-Length.
        super().__init__(status_code=413, detail=_TOO_LARGE_DETAIL)


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


class MediaUploadBodyLimitMiddleware:
    """Reject oversized inbox media JSON without buffering it in the app."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int = MAX_MEDIA_REQUEST_BODY_BYTES,
    ) -> None:
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be positive")
        self.app = app
        self.max_body_bytes = max_body_bytes

    @staticmethod
    def _targets_media_upload(scope: Mapping[str, Any]) -> bool:
        return (
            scope.get("type") == "http"
            and scope.get("method") == "POST"
            and bool(_MEDIA_UPLOAD_PATH.fullmatch(str(scope.get("path", ""))))
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._targets_media_upload(scope):
            await self.app(scope, receive, send)
            return

        declared_length = _content_length(scope.get("headers", []))
        if declared_length is not None and declared_length > self.max_body_bytes:
            await self._reject(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": _TOO_LARGE_DETAIL},
        )
        await response(scope, receive, send)
