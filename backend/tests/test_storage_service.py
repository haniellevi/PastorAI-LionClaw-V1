"""Unit tests for the Supabase Storage media client (Etapa 2 do chat).

These pin the upload contract (path is tenant-scoped, bytes go raw with the
service-role key), the batch signing (relative signedURL -> absolute URL), and
the graceful degradation (signing failure yields an empty map, not an error).
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.services.storage import (
    MAX_MEDIA_BYTES,
    StorageError,
    SupabaseStorage,
    kind_for_mime,
    mediatype_for_tipo,
)


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
        supabase_url="https://proj.supabase.co",
        supabase_service_role_key="svc-key",
    )
    base.update(over)
    return Settings(**base)


# ---- MIME helpers ---------------------------------------------------------
def test_kind_for_mime() -> None:
    assert kind_for_mime("image/png") == "imagem"
    assert kind_for_mime("IMAGE/JPEG") == "imagem"
    assert kind_for_mime("audio/ogg") == "audio"
    assert kind_for_mime("application/pdf") == "arquivo"
    assert kind_for_mime(None) == "arquivo"


def test_mediatype_for_tipo() -> None:
    assert mediatype_for_tipo("imagem") == "image"
    assert mediatype_for_tipo("audio") == "audio"
    assert mediatype_for_tipo("arquivo") == "document"


# ---- upload ---------------------------------------------------------------
def test_upload_posts_bytes_and_returns_pointer(monkeypatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["ct"] = request.headers.get("content-type")
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.content
        return httpx.Response(200, json={"Key": "ok"})

    _use_transport(monkeypatch, handler)
    stored = SupabaseStorage(_settings()).upload(
        "igreja-1", "conv-1", b"hello", "image/png", None
    )

    assert stored.mime == "image/png"
    assert stored.tamanho == 5
    assert stored.path.startswith("igreja-1/conv-1/")
    assert stored.path.endswith(".png")
    assert "/storage/v1/object/whatsapp-media/igreja-1/conv-1/" in seen["url"]
    assert seen["ct"] == "image/png"
    assert seen["auth"] == "Bearer svc-key"
    assert seen["body"] == b"hello"


def test_upload_uses_filename_extension_for_unknown_mime(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    _use_transport(monkeypatch, handler)
    stored = SupabaseStorage(_settings()).upload(
        "i", "c", b"x", "application/x-weird", "planilha.csv"
    )
    assert stored.path.endswith(".csv")
    assert stored.nome == "planilha.csv"


def test_upload_rejects_oversize() -> None:
    big = b"x" * (MAX_MEDIA_BYTES + 1)
    with pytest.raises(StorageError):
        SupabaseStorage(_settings()).upload("i", "c", big, "image/png", None)


def test_upload_rejects_empty() -> None:
    with pytest.raises(StorageError):
        SupabaseStorage(_settings()).upload("i", "c", b"", "image/png", None)


def test_upload_requires_config() -> None:
    with pytest.raises(StorageError):
        SupabaseStorage(_settings(supabase_url="")).upload(
            "i", "c", b"x", "image/png", None
        )


def test_upload_raises_on_http_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    _use_transport(monkeypatch, handler)
    with pytest.raises(StorageError):
        SupabaseStorage(_settings()).upload("i", "c", b"x", "image/png", None)


# ---- signing --------------------------------------------------------------
def test_sign_returns_absolute_urls(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "path": "i/c/a.jpg",
                    "signedURL": "/object/sign/whatsapp-media/i/c/a.jpg?token=t",
                }
            ],
        )

    _use_transport(monkeypatch, handler)
    out = SupabaseStorage(_settings()).sign(["i/c/a.jpg"])
    assert out == {
        "i/c/a.jpg": (
            "https://proj.supabase.co/storage/v1"
            "/object/sign/whatsapp-media/i/c/a.jpg?token=t"
        )
    }


def test_sign_empty_paths_returns_empty() -> None:
    assert SupabaseStorage(_settings()).sign([]) == {}


def test_sign_degrades_on_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    _use_transport(monkeypatch, handler)
    assert SupabaseStorage(_settings()).sign(["i/c/a.jpg"]) == {}


def test_sign_degrades_without_config() -> None:
    assert SupabaseStorage(_settings(supabase_url="")).sign(["i/c/a.jpg"]) == {}


# ---- remove (limpeza ao excluir a conversa) -------------------------------
def test_remove_deletes_prefixes(monkeypatch) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = request.content
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=[{"name": "a.jpg"}])

    _use_transport(monkeypatch, handler)
    SupabaseStorage(_settings()).remove(["i/c/a.jpg", "i/c/b.png", "i/c/a.jpg"])

    assert seen["method"] == "DELETE"
    assert seen["url"].endswith("/storage/v1/object/whatsapp-media")
    assert seen["auth"] == "Bearer svc-key"
    # Corpo carrega os prefixos deduplicados.
    assert b"i/c/a.jpg" in seen["body"]
    assert b"i/c/b.png" in seen["body"]


def test_remove_empty_is_noop(monkeypatch) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=[])

    _use_transport(monkeypatch, handler)
    SupabaseStorage(_settings()).remove([])
    SupabaseStorage(_settings()).remove(["", None])  # type: ignore[list-item]
    assert calls["n"] == 0


def test_remove_degrades_on_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    _use_transport(monkeypatch, handler)
    # Best-effort: não levanta mesmo quando o Storage falha.
    SupabaseStorage(_settings()).remove(["i/c/a.jpg"])


def test_remove_degrades_without_config() -> None:
    # Sem config, é no-op silencioso (não levanta).
    SupabaseStorage(_settings(supabase_url="")).remove(["i/c/a.jpg"])
