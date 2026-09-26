"""Regression coverage for atomic tenant deletion and cleanup ownership."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.deps import PlatformAdminUser
from app.routers import platform_admin
from app.services.asaas import AsaasClient, AsaasError, AsaasOwnershipError
from app.services.clerk import ClerkAuthError, ClerkClient
from app.services.evolution import EvolutionClient, EvolutionError
from app.services.tenant_deletion import (
    CleanupTask,
    TenantDeletionActor,
    TenantDeletionBlocked,
    TenantDeletionResult,
    run_pending_cleanup,
)
from app.services.storage import StorageError, StoragePathError, tenant_owned_paths


class _Result:
    def __init__(self, scalar=None, values=()) -> None:
        self._scalar = scalar
        self._values = list(values)

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class _CleanupSession:
    def __init__(self) -> None:
        self.existing_clerk_user = None
        self.existing_media_igreja_id = None
        self.existing_igreja_id = None
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.statements: list[object] = []
        self.events: list[object] = []

    def execute(self, statement):
        self.statements.append(statement)
        rendered = str(statement)
        if "platform_audit_log" in rendered:
            task_id = str(statement.compile().params.get("param_1", ""))
            task_events = [
                event
                for event in self.events
                if getattr(event, "detalhe", {}).get("task_id") == task_id
            ]
            if "FOR UPDATE" in rendered:
                return _Result(task_events[0] if task_events else None)
            return _Result(values=task_events)
        if "app_users.clerk_user_id" in rendered:
            return _Result(self.existing_clerk_user)
        if "messages.media_path" in rendered:
            return _Result(self.existing_media_igreja_id)
        if "igrejas.id" in rendered:
            return _Result(self.existing_igreja_id)
        return _Result()

    def add(self, item) -> None:
        self.added.append(item)
        if getattr(item, "acao", None):
            self.events.append(item)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _FailingClerk:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fails = True

    def delete_user(self, clerk_user_id: str) -> None:
        self.calls.append(clerk_user_id)
        if self.fails:
            raise RuntimeError("synthetic upstream failure")


def _task() -> CleanupTask:
    return CleanupTask(
        task_id=uuid.uuid4(),
        igreja_id=uuid.uuid4(),
        kind="clerk_user",
        payload={"clerk_user_id": "clerk-deleted-tenant"},
    )


def _queue_tasks(session: _CleanupSession, *tasks: CleanupTask) -> None:
    for task in tasks:
        session.events.append(
            SimpleNamespace(
                acao="tenant_deletion.cleanup_pending",
                alvo_id=task.igreja_id,
                detalhe={
                    "task_id": str(task.task_id),
                    "kind": task.kind,
                    "payload": task.payload,
                },
            )
        )


def test_retry_rechecks_a_surviving_clerk_binding_before_deleting() -> None:
    session = _CleanupSession()
    clerk = _FailingClerk()
    task = _task()
    _queue_tasks(session, task)
    actor = TenantDeletionActor(None, "master@example.test")

    first = run_pending_cleanup(
        session,
        actor,
        (task,),
        clerk=clerk,
        evolution=object(),
        asaas=object(),
        storage=object(),
    )
    assert first[0].status == "pending"
    assert clerk.calls == ["clerk-deleted-tenant"]
    assert session.added[-1].acao == "tenant_deletion.cleanup_retry"

    # A retry must never delete an identifier rebound after the local tenant
    # transaction completed. The short claim transaction revalidates it.
    session.existing_clerk_user = uuid.uuid4()
    clerk.fails = False
    second = run_pending_cleanup(
        session,
        actor,
        (task,),
        clerk=clerk,
        evolution=object(),
        asaas=object(),
        storage=object(),
    )
    assert second[0].status == "rejected"
    assert clerk.calls == ["clerk-deleted-tenant"]
    assert session.added[-1].acao == "tenant_deletion.cleanup_rejected"
    assert not any("LOCK TABLE" in str(statement) for statement in session.statements)


def test_cleanup_audit_records_the_confirmed_execution_host() -> None:
    session = _CleanupSession()
    task = _task()
    _queue_tasks(session, task)

    class WorkingClerk:
        def delete_user(self, _clerk_user_id: str) -> None:
            return None

    outcomes = run_pending_cleanup(
        session,
        TenantDeletionActor(
            None,
            "reset_tudo",
            execution_host="localhost",
        ),
        (task,),
        clerk=WorkingClerk(),
        evolution=object(),
        asaas=object(),
        storage=object(),
    )

    assert outcomes[0].status == "done"
    assert session.added[-1].detalhe["execution_host"] == "localhost"


def test_cleanup_calls_transaction_setup_before_every_task() -> None:
    session = _CleanupSession()
    first = _task()
    second = CleanupTask(
        task_id=uuid.uuid4(),
        igreja_id=uuid.uuid4(),
        kind="clerk_user",
        payload={"clerk_user_id": "clerk-deleted-tenant-second"},
    )
    _queue_tasks(session, first, second)
    setup_calls: list[uuid.UUID] = []

    class WorkingClerk:
        def delete_user(self, _clerk_user_id: str) -> None:
            return None

    outcomes = run_pending_cleanup(
        session,
        TenantDeletionActor(None, "reset_tudo"),
        (first, second),
        clerk=WorkingClerk(),
        evolution=object(),
        asaas=object(),
        storage=object(),
        before_task=lambda _session: setup_calls.append(uuid.uuid4()),
    )

    assert [outcome.status for outcome in outcomes] == ["done", "done"]
    assert len(setup_calls) == 6


def test_delete_route_commits_local_manifest_before_cleanup(monkeypatch) -> None:
    order: list[str] = []
    target_id = uuid.uuid4()
    task = _task()

    class _Db:
        commits = 0
        rollbacks = 0

        def commit(self) -> None:
            self.commits += 1
            order.append("commit")

        def rollback(self) -> None:
            self.rollbacks += 1

    db = _Db()

    def local_delete(received_db, igreja_id, actor):
        assert received_db is db and igreja_id == target_id
        order.append("local")
        return TenantDeletionResult(target_id, True, (task,))

    def cleanup(received_db, actor, tasks, **providers):
        assert received_db is db and tasks == (task,)
        assert db.commits == 1
        order.append("cleanup")
        return ()

    monkeypatch.setattr(platform_admin, "delete_tenant_locally", local_delete)
    monkeypatch.setattr(platform_admin, "run_pending_cleanup", cleanup)
    admin = PlatformAdminUser(str(uuid.uuid4()), "clerk-master", "m@test", "Master")

    platform_admin.delete_igreja(
        str(target_id),
        db,
        admin,
        clerk=object(),
        evolution=object(),
        asaas=object(),
        storage=object(),
    )
    assert order == ["local", "commit", "cleanup"]


def test_delete_route_rolls_back_e4b_block_without_provider_call(monkeypatch) -> None:
    class _Db:
        rollbacks = 0

        def rollback(self) -> None:
            self.rollbacks += 1

    db = _Db()
    called = False

    def blocked(*_args, **_kwargs):
        raise TenantDeletionBlocked("dados E4B imutáveis")

    def cleanup(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(platform_admin, "delete_tenant_locally", blocked)
    monkeypatch.setattr(platform_admin, "run_pending_cleanup", cleanup)
    admin = PlatformAdminUser(str(uuid.uuid4()), "clerk-master", "m@test", "Master")

    with pytest.raises(Exception) as caught:
        platform_admin.delete_igreja(
            str(uuid.uuid4()),
            db,
            admin,
            clerk=object(),
            evolution=object(),
            asaas=object(),
            storage=object(),
        )
    assert getattr(caught.value, "status_code", None) == 409
    assert db.rollbacks == 1
    assert called is False


def test_storage_cleanup_rejects_encoded_or_windows_escape_paths() -> None:
    igreja_id = uuid.uuid4()
    assert tenant_owned_paths(igreja_id, [f"{igreja_id}/provider/a1b2.jpg"])
    for path in (
        f"{igreja_id}/provider/%2e%2e/other.jpg",
        f"{igreja_id}/provider/..\\other.jpg",
        f"{igreja_id}/provider/a%2fb.jpg",
    ):
        with pytest.raises(StoragePathError):
            tenant_owned_paths(igreja_id, [path])


def test_storage_retry_rejects_any_rebound_path_even_with_the_old_tenant_id() -> None:
    session = _CleanupSession()
    task = CleanupTask(
        task_id=uuid.uuid4(),
        igreja_id=uuid.uuid4(),
        kind="storage_media",
        payload={"paths": []},
    )
    path = f"{task.igreja_id}/provider/deadbeef.jpg"
    task = CleanupTask(task.task_id, task.igreja_id, task.kind, {"paths": [path]})
    _queue_tasks(session, task)
    session.existing_media_igreja_id = task.igreja_id

    class _Storage:
        calls: list[list[str]] = []

        def remove_tenant_media_namespace(self, _igreja_id, **_kwargs) -> None:
            self.calls.append([])

    storage = _Storage()
    outcomes = run_pending_cleanup(
        session,
        TenantDeletionActor(None, "master@example.test"),
        (task,),
        clerk=object(),
        evolution=object(),
        asaas=object(),
        storage=storage,
    )

    assert outcomes[0].status == "rejected"
    assert storage.calls == []


def test_storage_cleanup_rejects_a_restored_tenant_before_namespace_delete() -> None:
    session = _CleanupSession()
    task = CleanupTask(
        task_id=uuid.uuid4(),
        igreja_id=uuid.uuid4(),
        kind="storage_media",
        payload={"paths": []},
    )
    _queue_tasks(session, task)
    session.existing_igreja_id = task.igreja_id

    class _Storage:
        def remove_tenant_media_namespace(self, *_args, **_kwargs) -> None:
            pytest.fail("a restored tenant namespace cannot be removed")

    outcomes = run_pending_cleanup(
        session,
        TenantDeletionActor(None, "master@example.test"),
        (task,),
        clerk=object(),
        evolution=object(),
        asaas=object(),
        storage=_Storage(),
    )

    assert [outcome.status for outcome in outcomes] == ["rejected"]


@pytest.mark.parametrize("stage", ("page", "delete"))
def test_storage_namespace_failure_keeps_the_cleanup_pending(stage: str) -> None:
    session = _CleanupSession()
    task = CleanupTask(
        task_id=uuid.uuid4(),
        igreja_id=uuid.uuid4(),
        kind="storage_media",
        payload={"paths": []},
    )
    _queue_tasks(session, task)
    renewals = 0

    class _Storage:
        def remove_tenant_media_namespace(self, _igreja_id, *, before_request) -> None:
            nonlocal renewals
            before_request()
            renewals += 1
            raise StorageError(f"synthetic {stage} failure")

    outcomes = run_pending_cleanup(
        session,
        TenantDeletionActor(None, "master@example.test"),
        (task,),
        clerk=object(),
        evolution=object(),
        asaas=object(),
        storage=_Storage(),
    )

    assert [outcome.status for outcome in outcomes] == ["pending"]
    assert renewals == 1
    assert session.added[-1].acao == "tenant_deletion.cleanup_retry"


def _asaas_settings() -> SimpleNamespace:
    return SimpleNamespace(
        asaas_api_url="https://asaas.test",
        asaas_api_key="test-key",
        external_sends_enabled=True,
        asaas_billing_writes_enabled=True,
        is_production=False,
    )


def _evolution_settings(*, external_sends_enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        evolution_api_url="https://evolution.test",
        evolution_api_key="test-key",
        external_sends_enabled=external_sends_enabled,
        is_production=False,
    )


def _mock_http(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "Client", fake_client)


def test_evolution_delete_accepts_documented_success_shape(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "SUCCESS", "error": False})

    _mock_http(monkeypatch, handler)
    client = EvolutionClient(_evolution_settings())
    try:
        assert client.delete_instance("tenant-instance") is True
    finally:
        client.close()

    assert [request.method for request in requests] == ["DELETE"]
    assert str(requests[0].url).endswith("/instance/delete/tenant-instance")


def test_evolution_delete_treats_missing_instance_as_complete(monkeypatch) -> None:
    _mock_http(monkeypatch, lambda _request: httpx.Response(404))
    client = EvolutionClient(_evolution_settings())
    try:
        assert client.delete_instance("tenant-instance") is True
    finally:
        client.close()


def test_evolution_delete_normalizes_timeout_for_durable_retry(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    _mock_http(monkeypatch, handler)
    client = EvolutionClient(_evolution_settings())
    try:
        with pytest.raises(EvolutionError):
            client.delete_instance("tenant-instance")
    finally:
        client.close()


def test_evolution_delete_gate_closed_does_not_prepare_http_client(monkeypatch) -> None:
    client = EvolutionClient(_evolution_settings(external_sends_enabled=False))
    monkeypatch.setattr(
        client, "_http_client", lambda *_args: pytest.fail("HTTP must not run")
    )
    assert client.delete_instance("tenant-instance") is False


def test_asaas_cancel_gate_closed_does_not_start_http(monkeypatch) -> None:
    settings = _asaas_settings()
    settings.asaas_billing_writes_enabled = False
    _mock_http(monkeypatch, lambda _request: pytest.fail("HTTP must not run"))

    assert (
        AsaasClient(settings).cancel_subscription(
            "sub_expected", expected_external_reference="pastorai-x"
        )
        is False
    )


def test_asaas_cancel_checks_remote_id_before_delete(monkeypatch) -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(
            200, json={"id": "sub-other", "externalReference": "pastorai-x"}
        )

    _mock_http(monkeypatch, handler)
    with pytest.raises(AsaasOwnershipError):
        AsaasClient(_asaas_settings()).cancel_subscription(
            "sub_expected", expected_external_reference="pastorai-x"
        )
    assert methods == ["GET"]


def test_asaas_cancel_rejects_path_like_id_without_request(monkeypatch) -> None:
    _mock_http(monkeypatch, lambda request: pytest.fail("HTTP must not run"))
    with pytest.raises(AsaasError):
        AsaasClient(_asaas_settings()).cancel_subscription(
            "sub_expected/../other", expected_external_reference="pastorai-x"
        )


def test_clerk_cleanup_rejects_path_like_id_before_http(monkeypatch) -> None:
    client = ClerkClient(SimpleNamespace(clerk_secret_key="synthetic"))
    monkeypatch.setattr(
        client, "_http_client", lambda: pytest.fail("HTTP must not run")
    )
    with pytest.raises(ClerkAuthError):
        client.delete_user("clerk_user/../other")


def test_invalid_durable_external_ids_are_rejected_without_provider_calls() -> None:
    session = _CleanupSession()
    actor = TenantDeletionActor(None, "master@example.test")
    tasks = (
        CleanupTask(
            uuid.uuid4(),
            uuid.uuid4(),
            "clerk_user",
            {"clerk_user_id": "clerk_user/../other"},
        ),
        CleanupTask(
            uuid.uuid4(),
            uuid.uuid4(),
            "asaas_subscription",
            {
                "subscription_id": "sub_expected/../other",
                "external_reference": "pastorai-x",
            },
        ),
    )
    _queue_tasks(session, *tasks)

    outcomes = run_pending_cleanup(
        session,
        actor,
        tasks,
        clerk=object(),
        evolution=object(),
        asaas=object(),
        storage=object(),
    )

    assert [outcome.status for outcome in outcomes] == ["rejected", "rejected"]


def test_asaas_cancel_requires_deleted_true(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"id": "sub_expected", "externalReference": "pastorai-x"},
            )
        return httpx.Response(200, json={"id": "sub_expected", "deleted": False})

    _mock_http(monkeypatch, handler)
    with pytest.raises(AsaasError):
        AsaasClient(_asaas_settings()).cancel_subscription(
            "sub_expected", expected_external_reference="pastorai-x"
        )
