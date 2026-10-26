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


def test_v1b_upload_late_2xx_is_confirmed_failure(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(storage.time, "monotonic", lambda: clock[0])
    def handler(_request):
        clock[0] = 111.0
        return httpx.Response(200)
    service, _ = _client(monkeypatch, handler)
    with pytest.raises(storage.StorageLateSuccess) as late:
        service.upload_cell_report_audio(igreja_id=TENANT, provider_message_sha256=DIGEST,
            mime_type="audio/wav", raw=b"synthetic audio", deadline_seconds=10)
    # Still a failure for every StorageError caller; only the object is known.
    assert isinstance(late.value, storage.StorageError)
    assert late.value.stored.path == f"{TENANT}/cell-report-audio/{DIGEST}.wav"
    assert late.value.stored.mime == "audio/wav" and late.value.stored.tamanho == 15


class _FailingClose(httpx.SyncByteStream):
    def __init__(self, error):
        self.error = error
    def __iter__(self):
        pytest.fail("The upload must not load the response body")
    def close(self):
        raise self.error


@pytest.mark.parametrize("late", (False, True))
@pytest.mark.parametrize("outcome", ("302", "403", "500", "timeout", "close", "foreign_close"))
def test_v1b_upload_unknown_outcome_is_never_confirmed(monkeypatch, outcome, late):
    clock = [100.0]
    monkeypatch.setattr(storage.time, "monotonic", lambda: clock[0])
    def handler(request):
        if late:
            clock[0] = 111.0
        if outcome == "timeout":
            raise httpx.ReadTimeout("synthetic timeout after the write", request=request)
        if outcome == "close":
            return httpx.Response(200, stream=_FailingClose(httpx.ReadError("synthetic close")))
        if outcome == "foreign_close":
            return httpx.Response(200, stream=_FailingClose(RuntimeError("synthetic close")))
        return httpx.Response(int(outcome), headers={"Location": "https://other.example.test"})
    service, _ = _client(monkeypatch, handler)
    with pytest.raises(Exception) as error:
        service.upload_cell_report_audio(igreja_id=TENANT, provider_message_sha256=DIGEST,
            mime_type="audio/wav", raw=b"synthetic audio", deadline_seconds=10)
    assert not isinstance(error.value, storage.StorageLateSuccess)
    if outcome != "foreign_close":
        assert type(error.value) is storage.StorageError


OWNED = f"{TENANT}/cell-report-audio/{DIGEST}.wav"


def _claim(storage_path=OWNED):
    return SimpleNamespace(igreja_id=TENANT, input_id=uuid.uuid4(), storage_path=storage_path,
                           provider_message_sha256=DIGEST, declared_mime="audio/wav")


def _stored(path=OWNED):
    return storage.StoredMedia(path=path, mime="audio/wav", nome=None, tamanho=15)


def _late(path=OWNED):
    return storage.StorageLateSuccess(_stored(path))


class _Ownership(list):
    """Records resolutions; the real login is proven by the PG suites."""
    def __init__(self, fail):
        super().__init__()
        self.fail = fail
    def finish_upload(self, claim):
        self.append(claim)
        if self.fail:
            raise RuntimeError("synthetic database unavailable")


def _finish_calls(monkeypatch, *, fail=False):
    return _Ownership(fail)


def test_v1b_confirmed_late_upload_resolves_ownership_and_keeps_error(monkeypatch):
    from app.services.cell_report_audio_service import _upload_owned_audio
    calls, claim, late = _finish_calls(monkeypatch), _claim(), _late()
    def upload():
        raise late
    with pytest.raises(storage.StorageLateSuccess) as error:
        _upload_owned_audio(calls, claim, upload)
    assert error.value is late and calls == [claim]


def test_v1b_confirmed_late_upload_keeps_error_when_resolution_fails(monkeypatch):
    from app.services.cell_report_audio_service import _upload_owned_audio
    calls, claim, late = _finish_calls(monkeypatch, fail=True), _claim(), _late()
    def upload():
        raise late
    with pytest.raises(storage.StorageLateSuccess) as error:
        _upload_owned_audio(calls, claim, upload)
    assert error.value is late and calls == [claim]


@pytest.mark.parametrize("storage_path", (OWNED, ""))
def test_v1b_owned_upload_resolves_only_its_exact_path(monkeypatch, storage_path):
    # Empty storage_path uses finish's same deterministic canonical fallback.
    from app.services.cell_report_audio_service import _upload_owned_audio
    calls, claim, stored = _finish_calls(monkeypatch), _claim(storage_path), _stored()
    assert _upload_owned_audio(calls, claim, lambda: stored) is stored
    assert calls == [claim]


OTHER = uuid.UUID("6b6b6b6b-0000-4000-8000-000000000002")


@pytest.mark.parametrize("late", (False, True))
@pytest.mark.parametrize("path", (
    OWNED.replace(DIGEST, "b"*64), OWNED.replace(str(TENANT), str(OTHER)),
    OWNED.replace(".wav", ".ogg"), None,
), ids=("same-church", "other-church", "other-extension", "missing"))
def test_v1b_divergent_upload_path_keeps_ownership_and_stops(monkeypatch, late, path):
    from app.services.cell_report_audio_service import _upload_owned_audio
    calls = _finish_calls(monkeypatch)
    returned = SimpleNamespace(path=None) if path is None else _stored(path)
    def upload():
        if late:
            raise storage.StorageLateSuccess(returned)
        return returned
    with pytest.raises(storage.StorageError) as error:
        _upload_owned_audio(calls, _claim(), upload)
    # Never a confirmed result for another object; the late error stays chained.
    assert not isinstance(error.value, storage.StorageLateSuccess)
    assert isinstance(error.value.__context__, storage.StorageLateSuccess) is late
    assert calls == []


def test_v1b_claim_path_outside_its_church_never_resolves(monkeypatch):
    from app.services.cell_report_audio_service import _upload_owned_audio
    calls, foreign = _finish_calls(monkeypatch), OWNED.replace(str(TENANT), str(OTHER))
    with pytest.raises(storage.StoragePathError):
        _upload_owned_audio(calls, _claim(foreign), lambda: _stored(foreign))
    assert calls == []


@pytest.mark.parametrize("error", (storage.StorageError("unknown"), TimeoutError("unknown"),
                                   RuntimeError("process boundary")))
def test_v1b_unknown_upload_outcome_keeps_ownership(monkeypatch, error):
    from app.services.cell_report_audio_service import _upload_owned_audio
    calls = _finish_calls(monkeypatch)
    def upload():
        raise error
    with pytest.raises(type(error)):
        _upload_owned_audio(calls, _claim(), upload)
    assert calls == []
