"""Unit tests for the Supabase Storage media client (Etapa 2 do chat).

These pin the upload contract (path is tenant-scoped, bytes go raw with the
service-role key), the batch signing (relative signedURL -> absolute URL), and
the graceful degradation (signing failure yields an empty map, not an error).
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from app.services import storage as storage_service
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


def test_upload_object_id_is_deterministic_for_queue_recovery(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    _use_transport(monkeypatch, handler)
    storage = SupabaseStorage(_settings())

    first = storage.upload(
        "i", "c", b"same", "image/jpeg", object_id="provider-message-1"
    )
    recovered = storage.upload(
        "i", "c", b"same", "image/jpeg", object_id="provider-message-1"
    )
    other = storage.upload(
        "i", "c", b"other", "image/jpeg", object_id="provider-message-2"
    )

    assert first.path == recovered.path
    assert first.path != other.path
    assert first.path.startswith("i/provider/")
    assert "/c/" not in first.path
    assert "provider-message-1" not in first.path


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


def test_tenant_media_namespace_cleanup_lists_all_pages_and_subdirectories(
    monkeypatch,
) -> None:
    igreja_id = uuid.uuid4()
    prefix = f"{igreja_id}/"
    list_calls: list[tuple[str, int]] = []
    deleted: list[str] = []

    monkeypatch.setattr(storage_service, "_TENANT_LIST_PAGE_SIZE", 2, raising=False)

    pages = {
        (prefix, 0): [
            {"name": "conversation", "id": None},
            {"name": "orphan.bin", "id": "orphan"},
        ],
        (prefix, 2): [{"name": "later.bin", "id": "later"}],
        (f"{prefix}conversation/", 0): [
            {"name": "deep", "id": None},
            {"name": "message.jpg", "id": "message"},
        ],
        (f"{prefix}conversation/", 2): [],
        (f"{prefix}conversation/deep/", 0): [
            {"name": "archive.pdf", "id": "archive"},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/storage/v1/object/list/whatsapp-media"):
            body = json.loads(request.content)
            key = (body["prefix"], body["offset"])
            list_calls.append(key)
            assert body["limit"] == 2
            return httpx.Response(200, json=pages[key])
        assert request.method == "DELETE"
        assert request.url.path.endswith("/storage/v1/object/whatsapp-media")
        deleted.extend(json.loads(request.content)["prefixes"])
        return httpx.Response(200, json=[])

    _use_transport(monkeypatch, handler)

    SupabaseStorage(_settings()).remove_tenant_media_namespace(igreja_id)

    assert set(deleted) == {
        f"{prefix}orphan.bin",
        f"{prefix}later.bin",
        f"{prefix}conversation/message.jpg",
        f"{prefix}conversation/deep/archive.pdf",
    }
    assert set(list_calls) == set(pages)


def test_tenant_logo_namespace_cleanup_removes_orphan_under_exact_uuid_prefix(
    monkeypatch,
) -> None:
    igreja_id = uuid.uuid4()
    prefix = f"{igreja_id}/"
    deleted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/storage/v1/object/list/church-logos"):
            body = json.loads(request.content)
            assert body["prefix"] == prefix
            return httpx.Response(200, json=[{"name": "orphan-logo.png", "id": "logo"}])
        assert request.method == "DELETE"
        assert request.url.path.endswith("/storage/v1/object/church-logos")
        deleted.extend(json.loads(request.content)["prefixes"])
        return httpx.Response(200, json=[])

    _use_transport(monkeypatch, handler)

    SupabaseStorage(_settings()).remove_tenant_logos_namespace(igreja_id)

    assert deleted == [f"{prefix}orphan-logo.png"]


@pytest.mark.parametrize(
    "entry",
    (
        {"name": "ambiguous"},
        {"name": "file.bin", "id": None, "metadata": {"size": 1}},
    ),
)
def test_tenant_namespace_cleanup_rejects_ambiguous_list_entries(
    monkeypatch, entry: dict[str, object]
) -> None:
    igreja_id = uuid.uuid4()
    returned_entry = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal returned_entry
        if request.url.path.endswith("/storage/v1/object/list/whatsapp-media"):
            if returned_entry:
                return httpx.Response(200, json=[])
            returned_entry = True
            return httpx.Response(200, json=[entry])
        pytest.fail("an ambiguous list entry cannot be deleted")

    _use_transport(monkeypatch, handler)

    with pytest.raises(StorageError):
        SupabaseStorage(_settings()).remove_tenant_media_namespace(igreja_id)


def test_tenant_namespace_cleanup_rejects_another_tenants_full_key(monkeypatch) -> None:
    igreja_id = uuid.uuid4()
    other_igreja_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/storage/v1/object/list/whatsapp-media"):
            return httpx.Response(
                200,
                json=[{"name": f"{other_igreja_id}/foreign.bin", "id": "foreign"}],
            )
        pytest.fail("a foreign full key cannot be deleted")

    _use_transport(monkeypatch, handler)

    with pytest.raises(StorageError):
        SupabaseStorage(_settings()).remove_tenant_media_namespace(igreja_id)


def test_tenant_namespace_cleanup_renews_before_each_page_and_remove_batch(
    monkeypatch,
) -> None:
    igreja_id = uuid.uuid4()
    prefix = f"{igreja_id}/"
    renewals = 0

    monkeypatch.setattr(storage_service, "_TENANT_LIST_PAGE_SIZE", 1)
    monkeypatch.setattr(storage_service, "_TENANT_REMOVE_BATCH_SIZE", 1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/storage/v1/object/list/whatsapp-media"):
            body = json.loads(request.content)
            if body["offset"] == 0:
                return httpx.Response(200, json=[{"name": "one.bin", "id": "one"}])
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[])

    def renew() -> None:
        nonlocal renewals
        renewals += 1

    _use_transport(monkeypatch, handler)

    SupabaseStorage(_settings()).remove_tenant_media_namespace(
        igreja_id,
        before_request=renew,
    )

    assert renewals == 3
