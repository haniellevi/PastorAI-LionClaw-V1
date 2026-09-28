"""Private audio upload contract through a fake HTTP transport, no provider."""
import uuid
from types import SimpleNamespace
import httpx
import pytest
from app.services import storage

TENANT = uuid.UUID("6b6b6b6b-0000-4000-8000-000000000001")
DIGEST = "a" * 64


def _client(monkeypatch, handler):
    real_client = httpx.Client
    calls = []
    def factory(**kwargs):
        calls.append(kwargs)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(storage.httpx, "Client", factory)
    service = storage.SupabaseStorage(SimpleNamespace(
        supabase_url="https://storage.example.test", supabase_service_role_key="synthetic-key"))
    return service, calls


class _UnreadBody(httpx.SyncByteStream):
    def __iter__(self):
        pytest.fail("The upload must not load the response body")


def test_v1b_upload_is_private_deterministic_and_does_not_read_response(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.content == b"synthetic audio"
        return httpx.Response(200, stream=_UnreadBody())
    service, clients = _client(monkeypatch, handler)
    first = service.upload_cell_report_audio(igreja_id=TENANT, provider_message_sha256=DIGEST,
        mime_type="audio/ogg; codecs=opus", raw=b"synthetic audio", deadline_seconds=10)
    second = service.upload_cell_report_audio(igreja_id=TENANT, provider_message_sha256=DIGEST,
        mime_type="audio/ogg; codecs=opus", raw=b"synthetic audio", deadline_seconds=10)
    assert first.path == second.path == f"{TENANT}/cell-report-audio/{DIGEST}.ogg"
    assert all(r.url.path == "/storage/v1/object/whatsapp-media/" + first.path for r in requests)
    assert all(r.headers["x-upsert"] == "true" for r in requests)
    assert all(r.headers["Content-Type"] == "audio/ogg" for r in requests)
    assert all(c.get("follow_redirects") is False and c.get("trust_env") is False for c in clients)
    assert first.tamanho == 15 and first.nome is None


@pytest.mark.parametrize("override", (
    {"igreja_id": "../tenant"}, {"igreja_id": uuid.UUID(int=0)},
    {"provider_message_sha256": "../" + DIGEST}, {"provider_message_sha256": "A"*64},
    {"mime_type": "text/html"}, {"raw": b""}, {"raw": b"x"*(5*1024*1024+1)},
    {"deadline_seconds": 0}, {"deadline_seconds": True},
    {"deadline_seconds": float("nan")}, {"deadline_seconds": float("inf")},
))
def test_v1b_upload_rejects_invalid_input_before_transport(monkeypatch, override):
    service, clients = _client(monkeypatch, lambda _: pytest.fail("No HTTP for invalid input"))
    args = dict(igreja_id=TENANT, provider_message_sha256=DIGEST,
        mime_type="audio/wav", raw=b"synthetic audio", deadline_seconds=10)
    args.update(override)
    with pytest.raises(storage.StorageError):
        service.upload_cell_report_audio(**args)
    assert clients == []


@pytest.mark.parametrize("status", (302, 403, 500))
def test_v1b_upload_failure_is_not_reported_as_success(monkeypatch, status):
    service, _ = _client(monkeypatch, lambda _: httpx.Response(status,
        headers={"Location": "https://other.example.test"}))
    with pytest.raises(storage.StorageError):
        service.upload_cell_report_audio(igreja_id=TENANT, provider_message_sha256=DIGEST,
            mime_type="audio/wav", raw=b"synthetic audio", deadline_seconds=10)


def test_v1b_upload_late_response_is_ambiguous_failure(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(storage.time, "monotonic", lambda: clock[0])
    def handler(_request):
        clock[0] = 111.0
        return httpx.Response(200)
    service, _ = _client(monkeypatch, handler)
    with pytest.raises(storage.StorageError):
        service.upload_cell_report_audio(igreja_id=TENANT, provider_message_sha256=DIGEST,
            mime_type="audio/wav", raw=b"synthetic audio", deadline_seconds=10)
