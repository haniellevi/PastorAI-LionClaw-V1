"""Storage info witness of one audio attempt, through the product client and fake HTTP.

Only the exact, live, unversioned row of this attempt proves a commit; every
other answer, shape or failure is "not proven" (never "absent").
"""
import json
import logging
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.services import storage

TENANT = uuid.UUID("6b6b6b6b-0000-4000-8000-000000000001")
OTHER = uuid.UUID("6b6b6b6b-0000-4000-8000-000000000002")
ATTEMPT = uuid.UUID("6b6b6b6b-0000-4000-8000-0000000000a1")
OWNED = f"{TENANT}/cell-report-audio/{'a' * 64}.ogg"
DROP = object()


def _client(monkeypatch, handler):
    """The info GET runs on ``httpx.AsyncClient``; nothing may use the sync client."""
    real_client = httpx.AsyncClient
    clients, requests = [], []
    async def recorded(request):
        requests.append(request)
        response = handler(request)
        if not isinstance(response, httpx.Response):
            response = await response
        if hasattr(response, "_content"):  # Like a real transport: an unread stream.
            response = httpx.Response(response.status_code, headers=response.headers,
                                      stream=httpx.ByteStream(response.content))
        return response
    def factory(**kwargs):
        clients.append(kwargs)
        return real_client(transport=httpx.MockTransport(recorded), **kwargs)
    monkeypatch.setattr(storage.httpx, "AsyncClient", factory)
    monkeypatch.setattr(storage.httpx, "Client", lambda **_: pytest.fail("info GET must be async"))
    service = storage.SupabaseStorage(SimpleNamespace(
        supabase_url="https://storage.example.test", supabase_service_role_key="synthetic-key"))
    return service, clients, requests


def _info(**override):
    """Shape returned by the pinned storage-api 6dd28b4 info renderer (A-r2)."""
    body = dict(id=str(uuid.uuid4()), name=OWNED, version=str(uuid.uuid4()), bucket_id="whatsapp-media",
                size=15, content_type="audio/ogg", cache_control="no-cache", content_encoding=None,
                etag='"synthetic"', metadata={"igreja12_attempt": str(ATTEMPT)},
                last_modified="2026-10-26T00:00:00.000Z", created_at="2026-10-26T00:00:00.000Z",
                archived_at=None, is_delete_marker=False, is_versioned=False)
    body.update(override)
    return {k: v for k, v in body.items() if v is not DROP}


def _json(status, body, **kwargs):
    return httpx.Response(status, content=json.dumps(body).encode(),
                          headers={"content-type": "application/json; charset=utf-8"}, **kwargs)


def test_exact_live_attempt_is_proven_with_one_bounded_get(monkeypatch):
    service, clients, requests = _client(monkeypatch, lambda _: _json(200, _info()))
    assert service.cell_report_audio_attempt_committed(TENANT, OWNED, ATTEMPT) is True
    [request] = requests
    assert request.method == "GET"
    assert request.url.path == f"/storage/v1/object/info/authenticated/whatsapp-media/{OWNED}"
    assert request.headers["Authorization"] == "Bearer synthetic-key"
    assert request.headers["Accept-Encoding"] == "identity"  # Cap applies to raw bytes.
    assert clients == [dict(timeout=5.0, follow_redirects=False, trust_env=False)]


@pytest.mark.parametrize("response", (
    _json(400, {"statusCode": "404", "code": "NoSuchKey", "error": "not_found"}),
    _json(404, {"code": "NoSuchKey"}),
    _json(200, _info(metadata={"igreja12_attempt": str(uuid.uuid4())})),
    _json(200, _info(metadata={})),
    _json(200, _info(metadata=None)),
    _json(200, _info(metadata=DROP)),
    _json(200, _info(metadata={"igreja12_attempt": str(ATTEMPT), "other": "x"})),
    _json(200, _info(metadata={"igreja12_attempt": str(ATTEMPT).upper()})),
    _json(200, _info(metadata=[str(ATTEMPT)])),
    _json(200, _info(name=OWNED.replace("a" * 64, "b" * 64))),
    _json(200, _info(name=f"{OTHER}/cell-report-audio/{'a' * 64}.ogg")),
    _json(200, _info(bucket_id="other-bucket")),
    _json(200, _info(version=DROP)), _json(200, _info(version="")),
    _json(200, _info(version="not-a-uuid")), _json(200, _info(version=None)),
    _json(200, _info(is_versioned=True)), _json(200, _info(is_versioned=None)),
    _json(200, _info(is_versioned=DROP)), _json(200, _info(is_versioned=0)),
    _json(200, _info(is_delete_marker=True)), _json(200, _info(is_delete_marker=None)),
    _json(200, _info(is_delete_marker=DROP)),
    _json(200, _info(archived_at="2026-10-26T00:00:00.000Z")), _json(200, _info(archived_at=DROP)),
    _json(200, [_info()]), _json(200, {}), _json(201, _info()), _json(204, _info()),
    httpx.Response(302, headers={"Location": "https://other.example.test"}),
    _json(500, _info()), _json(503, {"error": "unavailable"}),
    httpx.Response(200, content=json.dumps(_info()).encode(), headers={"content-type": "text/plain"}),
    httpx.Response(200, content=b"{not json", headers={"content-type": "application/json"}),
    httpx.Response(200, content=json.dumps(_info()).encode()[:-1] + b',"name":"x"}',
                   headers={"content-type": "application/json"}),  # duplicate key
    httpx.Response(200, content=json.dumps(_info()).encode()[:-1] + b',"size2":NaN}',
                   headers={"content-type": "application/json"}),
    httpx.Response(200, content=json.dumps(_info(padding="x" * 20000)).encode(),
                   headers={"content-type": "application/json"}),
    httpx.Response(200, content=b"\xff\xfe", headers={"content-type": "application/json"}),
))
def test_any_other_answer_is_not_proven(monkeypatch, response):
    service, _, requests = _client(monkeypatch, lambda _: response)
    assert service.cell_report_audio_attempt_committed(TENANT, OWNED, ATTEMPT) is False
    assert len(requests) == 1  # Never retried, never followed.


@pytest.mark.parametrize("error", (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError))
def test_transport_failure_and_timeout_are_not_proven(monkeypatch, error, caplog):
    def handler(request):
        raise error("synthetic failure", request=request)
    service, _, requests = _client(monkeypatch, handler)
    with caplog.at_level(logging.WARNING, logger="pastorai.storage"):
        assert service.cell_report_audio_attempt_committed(TENANT, OWNED, ATTEMPT) is False
    assert len(requests) == 1
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert OWNED not in logged and str(ATTEMPT) not in logged and "synthetic-key" not in logged


def test_slow_body_past_deadline_is_cancelled(monkeypatch):
    import asyncio
    import time as real_time
    monkeypatch.setattr(storage, "_ATTEMPT_INFO_TIMEOUT_SECONDS", 0.3)
    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            body = json.dumps(_info()).encode()
            yield body[:10]
            await asyncio.sleep(5)  # Exact positive, but far past the deadline.
            yield body[10:]
    service, _, _ = _client(monkeypatch, lambda _: httpx.Response(
        200, stream=Slow(), headers={"content-type": "application/json"}))
    started = real_time.monotonic()
    assert service.cell_report_audio_attempt_committed(TENANT, OWNED, ATTEMPT) is False
    assert real_time.monotonic() - started < 0.3 + 0.3


class _Unread(httpx.SyncByteStream, httpx.AsyncByteStream):
    def __iter__(self):
        pytest.fail("An oversized declared body must not be read")

    async def __aiter__(self):
        pytest.fail("An oversized declared body must not be read")
        yield b""


@pytest.mark.parametrize("kind", ("gzip", "declared_oversized"))
def test_compressed_or_declared_oversized_body_is_not_proven(monkeypatch, kind):
    import gzip
    if kind == "gzip":  # A valid positive, but compressed: never decompressed here.
        packed = gzip.compress(json.dumps(_info()).encode())
        response = httpx.Response(200, stream=httpx.ByteStream(packed), headers={
            "content-type": "application/json", "content-encoding": "gzip", "content-length": str(len(packed))})
    else:
        response = httpx.Response(200, stream=_Unread(), headers={"content-type": "application/json",
                                                                  "content-length": str(16 * 1024 + 1)})
    service, _, _ = _client(monkeypatch, lambda _: response)
    assert service.cell_report_audio_attempt_committed(TENANT, OWNED, ATTEMPT) is False


def test_headers_after_deadline_are_cancelled(monkeypatch):
    import asyncio
    import time as real_time
    monkeypatch.setattr(storage, "_ATTEMPT_INFO_TIMEOUT_SECONDS", 0.3)
    async def late(_request):
        await asyncio.sleep(5)  # Exact positive answer, but only after 5 s.
        return _json(200, _info())
    service, _, _ = _client(monkeypatch, late)
    started = real_time.monotonic()
    assert service.cell_report_audio_attempt_committed(TENANT, OWNED, ATTEMPT) is False
    assert real_time.monotonic() - started < 0.3 + 0.3


def test_call_inside_a_running_loop_is_not_proven_and_does_no_request(monkeypatch):
    import asyncio
    service, clients, _ = _client(monkeypatch, lambda _: _json(200, _info()))
    async def nested():
        return service.cell_report_audio_attempt_committed(TENANT, OWNED, ATTEMPT)
    assert asyncio.run(nested()) is False and clients == []


class _LoopbackServer:
    """Real loopback HTTP/1.1 server; records when it sees the client close."""

    def __init__(self, head: bytes, body: bytes, *, trickle_head=False, trickle_body=False,
                 silent=False, gap=0.05):
        import socket
        import threading
        self.head, self.body, self.gap = head, body, gap
        self.trickle_head, self.trickle_body, self.silent = trickle_head, trickle_body, silent
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.closed_by_client_at = None
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        import time as real_time
        conn, _ = self.listener.accept()
        with conn:
            conn.recv(65536)
            try:
                if self.silent:  # Accepts and never answers: wait for the client to leave.
                    conn.settimeout(10)
                    conn.recv(1)
                else:
                    for part in ([bytes([b]) for b in self.head] if self.trickle_head else [self.head]):
                        conn.sendall(part)
                        if self.trickle_head:
                            real_time.sleep(self.gap)
                    for part in ([bytes([b]) for b in self.body] if self.trickle_body else [self.body]):
                        conn.sendall(part)
                        if self.trickle_body:
                            real_time.sleep(self.gap)
                    conn.settimeout(10)
                    conn.recv(1)  # EOF once the client closes.
            except OSError:
                pass  # Reset/broken pipe: the client closed the connection.
            self.closed_by_client_at = real_time.monotonic()
        self.listener.close()


def _response_head(payload: bytes) -> bytes:
    return (b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n"
            + f"content-length: {len(payload)}\r\n\r\n".encode())


@pytest.mark.parametrize("mode", ("headers", "body", "silent"))
def test_real_socket_slow_server_is_cut_at_the_deadline_and_closed(monkeypatch, mode):
    import threading
    import time as real_time
    deadline = 0.6
    monkeypatch.setattr(storage, "_ATTEMPT_INFO_TIMEOUT_SECONDS", deadline)
    payload = json.dumps(_info()).encode()  # An exact positive, if it ever arrived in time.
    # 1 byte per 0.05 s: each read stays far below the per-operation timeout.
    server = _LoopbackServer(_response_head(payload), payload, trickle_head=mode == "headers",
                             trickle_body=mode == "body", silent=mode == "silent")
    service = storage.SupabaseStorage(SimpleNamespace(
        supabase_url=f"http://127.0.0.1:{server.port}", supabase_service_role_key="synthetic-key"))
    threads_before = threading.active_count()  # The server thread is already running.
    started = real_time.monotonic()
    assert service.cell_report_audio_attempt_committed(TENANT, OWNED, ATTEMPT) is False
    returned = real_time.monotonic()
    assert returned - started < deadline + 0.3  # Total duration bounded, headers included.
    server.thread.join(5)
    assert not server.thread.is_alive() and server.closed_by_client_at is not None
    assert server.closed_by_client_at - started < deadline + 0.5  # Connection closed by the client.
    assert threading.active_count() == threads_before - 1  # Only the server thread ended.


def test_real_socket_positive_is_proven_and_closed(monkeypatch):
    import threading
    payload = json.dumps(_info()).encode()
    server = _LoopbackServer(_response_head(payload), payload)
    service = storage.SupabaseStorage(SimpleNamespace(
        supabase_url=f"http://127.0.0.1:{server.port}", supabase_service_role_key="synthetic-key"))
    threads_before = threading.active_count()
    assert service.cell_report_audio_attempt_committed(TENANT, OWNED, ATTEMPT) is True
    server.thread.join(5)
    assert server.closed_by_client_at is not None and threading.active_count() == threads_before - 1


@pytest.mark.parametrize("igreja_id,path,token", (
    (OTHER, OWNED, ATTEMPT),
    (TENANT, f"{OTHER}/cell-report-audio/{'a' * 64}.ogg", ATTEMPT),
    (TENANT, f"{TENANT}/../{OTHER}/cell-report-audio/{'a' * 64}.ogg", ATTEMPT),
    (TENANT, f"{TENANT}/provider/{'a' * 64}.png", ATTEMPT),
    (TENANT, f"{TENANT}/cell-report-audio/{'a' * 64}.ogg/extra", ATTEMPT),
    (TENANT, f"{TENANT}/cell-report-audio/{'A' * 64}.ogg", ATTEMPT),
    (TENANT, None, ATTEMPT),
    (TENANT, OWNED, str(ATTEMPT)), (TENANT, OWNED, None),
    ("../tenant", OWNED, ATTEMPT),
))
def test_invalid_scope_is_refused_before_any_request(monkeypatch, igreja_id, path, token):
    service, clients, _ = _client(monkeypatch, lambda _: pytest.fail("No HTTP for invalid input"))
    with pytest.raises(storage.StorageError):
        service.cell_report_audio_attempt_committed(igreja_id, path, token)
    assert clients == []


@pytest.mark.parametrize("failure", (None, RuntimeError("synthetic witness failure")))
def test_cron_runs_witness_before_cleanup_and_never_blocks_it(monkeypatch, failure):
    from app.db import privacy_storage_session
    from app.services import cell_report_audio_service, outbound_guard, private_deletion, private_upload_witness
    from app.workers.cron_worker import CronWorker
    calls = []
    def reconcile(factory, *, storage, now, progress):
        calls.append(("witness", progress))
        progress()
        if failure:
            raise failure
    monkeypatch.setattr(private_upload_witness, "reconcile_upload_attempts", reconcile)
    monkeypatch.setattr(private_deletion, "process_storage_tasks",
                        lambda factory, *, storage, now: calls.append(("cleanup", None)))
    monkeypatch.setattr(privacy_storage_session, "get_private_storage_session_factory", lambda: object())
    monkeypatch.setattr("app.services.private_summaries.process_tasks", lambda factory: None)
    monkeypatch.setattr(cell_report_audio_service, "purge_cell_report_audio_inputs", lambda *a, **k: 0)
    monkeypatch.setattr(outbound_guard, "external_sends_allowed", lambda: False)
    worker = CronWorker(session_factory=lambda: None, engine=None)
    assert worker._run_cell_report_audio_cycle(now=None) == (0, 0)
    assert [name for name, _ in calls] == ["witness", "cleanup"]
    assert calls[0][1] == worker._record_progress  # Per-item heartbeat progress.
