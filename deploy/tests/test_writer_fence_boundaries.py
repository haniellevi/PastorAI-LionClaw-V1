"""Executable counterexamples, not a native or authoritative writer fence.

Run the repository Storage transport and actual controller predicates; replace
only configuration, metrics/canonical-audio helpers and HTTP/PG/host IO edges.
"""

from contextlib import contextmanager
import importlib.util
from pathlib import Path
import socket
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import uuid

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from first_transition_database import require_quiet
from first_transition_window_bindings import (
    Q_ACTIVE,
    Q_READONLY,
    Q_STATS,
    UnknownWriters,
)
from initial_transition_ops import Refused


@pytest.fixture(autouse=True)
def no_real_process_or_socket(monkeypatch):
    def deny(*_args, **_kwargs):
        pytest.fail("real process or socket attempted")

    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(socket, "socket", deny)


@pytest.fixture
def storage_module(monkeypatch):
    """Load the reviewed repository client; never import real app settings."""
    app = ModuleType("app")
    app.__path__ = []
    services = ModuleType("app.services")
    services.__path__ = []
    config = ModuleType("app.config")
    config.Settings = SimpleNamespace
    config.get_settings = lambda: pytest.fail("real/default settings requested")
    performance = ModuleType("app.performance")

    @contextmanager
    def timed_span(*_args, **_kwargs):
        yield

    performance.timed_span = timed_span
    audio = ModuleType("app.services.cell_report_audio")
    audio.CELL_REPORT_AUDIO_MAX_BYTES = 5 * 1024 * 1024

    def canonical(value):
        assert value == "audio/ogg"
        return value

    audio.canonical_audio_mime = canonical
    for module in (app, services, config, performance, audio):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    path = Path(__file__).resolve().parents[2] / "backend" / "app" / "services" / "storage.py"
    spec = importlib.util.spec_from_file_location("writer_fence_storage_under_test", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class ProviderFixture:
    def __init__(self, mode):
        self.mode, self.now = mode, 100.0
        self.requests, self.clients, self.objects = [], [], {}
        self.pending = None
        self.local = dict(ingress_open=True, worker_running=True, send_gate=False)
        self.stream_closed = False

    def client(self, **options):
        assert options["follow_redirects"] is False and options["trust_env"] is False
        provider = self

        class Client:
            closed = False

            def __enter__(self):
                provider.clients.append(self)
                return self

            def __exit__(self, *_args):
                self.closed = True

            def stream(self, method, url, *, headers, content, timeout):
                assert method == "POST" and url.startswith(
                    "https://storage-fixture.invalid/storage/v1/object/"
                )
                assert headers["Authorization"] == "Bearer FICTIONAL-NOT-A-CREDENTIAL"
                assert timeout > 0

                class Response:
                    def raise_for_status(self):
                        return None

                    def __enter__(self):
                        provider.requests.append((url, content))
                        # A request is already accepted; stopping the local
                        # caller does not control this fictional provider.
                        provider.local.update(ingress_open=False, worker_running=False)
                        provider.pending = (url, content)
                        if provider.mode == "timeout-pending":
                            raise httpx.ReadTimeout("fictional request outcome unknown")
                        provider.complete_pending()
                        provider.now = 102.0 if provider.mode == "late" else 100.1
                        return self

                    def __exit__(self, *_args):
                        provider.stream_closed = True

                return Response()

        return Client()

    def complete_pending(self):
        url, data = self.pending
        self.objects[url] = data
        self.pending = None


def transport(storage_module, provider, monkeypatch):
    monkeypatch.setattr(storage_module.httpx, "Client", provider.client)
    monkeypatch.setattr(storage_module.time, "monotonic", lambda: provider.now)
    settings = SimpleNamespace(
        supabase_url="https://storage-fixture.invalid",
        supabase_service_role_key="FICTIONAL-NOT-A-CREDENTIAL",
        allow_real_sends=False,
        broadcast_async_enabled=False,
    )
    return storage_module.SupabaseStorage(settings)


def upload(client):
    return client.upload_cell_report_audio(
        igreja_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        provider_message_sha256="a" * 64,
        mime_type="audio/ogg",
        raw=b"FICTIONAL-AUDIO",
        deadline_seconds=1.0,
        attempt_token=uuid.UUID("22222222-2222-4222-8222-222222222222"),
    )


def test_preauthorized_storage_transport_can_write_with_closed_send_settings(
    storage_module, monkeypatch
):
    p = ProviderFixture("ok")
    stored = upload(transport(storage_module, p, monkeypatch))
    assert stored.path.endswith("/cell-report-audio/" + "a" * 64 + ".ogg")
    assert len(p.objects) == len(p.requests) == 1 and p.clients[0].closed
    assert p.local["send_gate"] is False and p.stream_closed


def test_client_reports_write_when_result_is_observed_after_deadline(
    storage_module, monkeypatch
):
    p = ProviderFixture("late")
    with pytest.raises(storage_module.StorageLateSuccess) as result:
        upload(transport(storage_module, p, monkeypatch))
    assert p.local == dict(ingress_open=False, worker_running=False, send_gate=False)
    assert len(p.objects) == len(p.requests) == 1
    assert result.value.stored.path.endswith("a" * 64 + ".ogg")
    assert p.clients[0].closed and p.stream_closed


def test_pending_provider_can_finish_after_client_timeout_and_local_hold(
    storage_module, monkeypatch
):
    p = ProviderFixture("timeout-pending")
    with pytest.raises(storage_module.StorageError) as result:
        upload(transport(storage_module, p, monkeypatch))
    assert not isinstance(result.value, storage_module.StorageLateSuccess)
    assert p.clients[0].closed and p.pending is not None and not p.objects
    assert p.local == dict(ingress_open=False, worker_running=False, send_gate=False)
    p.complete_pending()  # Provider fixture only, after the caller returned.
    assert len(p.objects) == 1 and len(p.requests) == 1


class CursorFixture:
    def __init__(self, rows):
        self.active, self.rows, self.queries = rows, [], []

    def execute(self, query, _params=None):
        self.queries.append(query)
        if query == Q_STATS:
            self.rows = [(True,)]
        elif query == Q_READONLY:
            self.rows = []
        elif query == Q_ACTIVE:
            self.rows = self.active
        else:
            assert query.startswith(
                ("BEGIN TRANSACTION", "SELECT set_config", "ROLLBACK")
            )
            self.rows = []

    def fetchall(self):
        return self.rows


class PGFixture:
    def __init__(self, rows):
        self.cur, self.closed = CursorFixture(rows), False

    def cursor(self):
        return self.cur

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    "role,declared,expected",
    [
        ("supabase_storage_admin", 0, 0),
        ("supabase_auth_admin", 0, 0),
        ("supabase_admin", 0, 0),
        ("external_writer", 0, 1),
        ("external_writer", 1, 0),
    ],
)
def test_undeclared_source_count_is_not_global_quiet(
    role, declared, expected, monkeypatch
):
    pg = PGFixture([(role, 1)])
    observer = UnknownWriters(
        scope="c" * 64,
        connect=lambda **_kw: pg,
        endpoint=(frozenset(("192.0.2.8",)), 5432),
        declared_containers=("a" * 64,),
        docker=("/fixture/docker", "unix:///fixture/docker.sock", "/fixture/config"),
    )
    # Host/proc IO is a fixture; execute the real DB sampling/filter contract.
    monkeypatch.setattr(observer, "_host_side", lambda _deadline, _ids: (declared, 0))
    assert observer.observe("c" * 64, timeout=1) == expected
    assert pg.closed and pg.cur.queries[-1] == "ROLLBACK"
    with pytest.raises(Refused, match="database-writing-session"):
        require_quiet(dict(writing_sessions=1, active_leases=0))


def test_quiet_predicate_positive_control_is_only_a_sample(monkeypatch):
    pg = PGFixture([])
    observer = UnknownWriters(
        scope="c" * 64,
        connect=lambda **_kw: pg,
        endpoint=(frozenset(("192.0.2.8",)), 5432),
        declared_containers=("a" * 64,),
        docker=("/fixture/docker", "unix:///fixture/docker.sock", "/fixture/config"),
    )
    monkeypatch.setattr(observer, "_host_side", lambda _deadline, _ids: (0, 0))
    assert observer.observe("c" * 64, timeout=1) == 0
    assert require_quiet(dict(writing_sessions=0, active_leases=0)) is None
    assert pg.closed
