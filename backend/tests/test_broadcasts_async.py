"""Router contracts for the boot-time broadcast async rollout flag."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.routers.broadcasts as broadcasts_router
from app.db.models import (
    AppUser,
    Broadcast,
    BroadcastEntrega,
    BroadcastExecucao,
    Celula,
    Pessoa,
    WhatsappConnection,
)
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from app.services.evolution import get_evolution_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {
    "Authorization": "Bearer good",
    "Idempotency-Key": "00000000-0000-4000-8000-000000000001",
}
_INSTANCE = "igreja-piloto"


class _Result:
    def __init__(self, *, scalar=None, scalars=None, rows=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def all(self):
        return list(self._rows)


class AsyncBroadcastSession:
    def __init__(self, *, people, connection=None) -> None:
        self.app_user = make_app_user()
        self.people = list(people)
        self.connection = connection
        self.added: list[object] = []
        self.commits = 0

    def execute(self, statement, params=None):
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is AppUser:
            return _Result(scalar=self.app_user)
        if entity is Pessoa:
            return _Result(scalars=self.people)
        if entity is Celula:
            return _Result(scalars=[])
        if entity is WhatsappConnection:
            return _Result(scalar=self.connection)
        if entity is Broadcast:
            saved = next(
                (
                    value
                    for value in self.added
                    if isinstance(value, Broadcast)
                    and value.idempotency_key is not None
                ),
                None,
            )
            return _Result(scalar=saved, scalars=[])
        if entity is BroadcastExecucao:
            execution = next(
                (
                    value
                    for value in self.added
                    if isinstance(value, BroadcastExecucao)
                ),
                None,
            )
            return _Result(scalar=execution.id if execution else None)
        if entity is BroadcastEntrega:
            counts: dict[str, int] = {}
            for value in self.added:
                if isinstance(value, BroadcastEntrega):
                    counts[value.status] = counts.get(value.status, 0) + 1
            return _Result(rows=list(counts.items()))
        return _Result(scalars=["admin"])

    def add(self, value) -> None:
        self.added.append(value)

    def add_all(self, values) -> None:
        self.added.extend(values)

    def flush(self) -> None:
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid.uuid4()

    def refresh(self, value) -> None:
        if getattr(value, "id", None) is None:
            value.id = uuid.uuid4()

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:  # pragma: no cover - TestClient cleanup
        pass


class FakeEvolution:
    def __init__(self, *, forbid_network: bool = False) -> None:
        self.forbid_network = forbid_network
        self.sent: list[tuple[str, str, str]] = []

    def send_text(self, instance: str, phone: str, message: str) -> bool:
        if self.forbid_network:
            raise AssertionError("async request must not fan out")
        self.sent.append((instance, phone, message))
        return True


def _person(*, consent=True, optout=False, phone="11999990000"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        telefone=phone,
        tipo="membro",
        consentimento=consent,
        optout=optout,
        arquivada_em=None,
    )


def _connection(*, online=True):
    return SimpleNamespace(
        instance=_INSTANCE,
        status="online" if online else "offline",
    )


def _wire(app, *, people, connection=None, forbid_network=False):
    session = AsyncBroadcastSession(people=people, connection=connection)
    evolution = FakeEvolution(forbid_network=forbid_network)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    app.dependency_overrides[get_evolution_client] = lambda: evolution
    return TestClient(app), session, evolution


def _payload(*, mode="agora", schedule=None):
    body = {
        "titulo": "Aviso",
        "mensagem": "Mensagem de teste",
        "segmentos": ["todos"],
        "modo": mode,
    }
    if schedule is not None:
        body["agendamento"] = schedule
    return body


def _set_rollout(
    monkeypatch,
    async_enabled: bool,
    *,
    sends_enabled: bool = True,
    worker_ready: bool = True,
) -> None:
    monkeypatch.setattr(
        broadcasts_router,
        "get_settings",
        lambda: SimpleNamespace(
            broadcast_async_enabled=async_enabled,
            external_sends_enabled=sends_enabled,
            redis_url="redis://test/0",
        ),
    )
    monkeypatch.setattr(
        broadcasts_router,
        "broadcast_worker_ready",
        lambda _url: worker_ready,
    )


def test_flag_false_rejects_schedule_before_persisting(app, monkeypatch) -> None:
    _set_rollout(monkeypatch, False)
    client, session, evolution = _wire(
        app, people=[_person()], connection=_connection()
    )

    response = client.post(
        "/broadcasts",
        headers=_AUTH,
        json=_payload(
            mode="agendado",
            schedule={"data": "2099-01-31", "hora": "23:59", "repeticao": "once"},
        ),
    )

    assert response.status_code == 503
    assert not any(isinstance(value, Broadcast) for value in session.added)
    assert session.commits == 0
    assert evolution.sent == []


def test_outbound_gate_rejects_immediate_before_persisting(app, monkeypatch) -> None:
    _set_rollout(monkeypatch, True, sends_enabled=False)
    client, session, evolution = _wire(
        app, people=[_person()], connection=_connection()
    )

    response = client.post(
        "/broadcasts", headers=_AUTH, json=_payload(mode="agora")
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Envios externos ainda não habilitados."
    assert not any(isinstance(value, Broadcast) for value in session.added)
    assert session.commits == 0
    assert evolution.sent == []


def test_flag_false_rejects_immediate_without_dispatcher(app, monkeypatch) -> None:
    _set_rollout(monkeypatch, False)
    client, session, evolution = _wire(
        app, people=[_person()], connection=_connection()
    )

    response = client.post(
        "/broadcasts", headers=_AUTH, json=_payload(mode="agora")
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Despacho seguro de comunicados ainda não habilitado."
    )
    assert session.added == []
    assert evolution.sent == []


def test_flag_true_now_persists_queue_without_network(app, monkeypatch) -> None:
    _set_rollout(monkeypatch, True)
    client, session, evolution = _wire(
        app,
        people=[_person()],
        connection=_connection(),
        forbid_network=True,
    )

    response = client.post(
        "/broadcasts", headers=_AUTH, json=_payload(mode="agora")
    )

    assert response.status_code == 202
    assert response.json()["status"] == "enfileirado"
    assert response.json()["enviados"] == 0
    assert response.json()["alcancePrevisto"] == 1
    assert evolution.sent == []
    saved = next(value for value in session.added if isinstance(value, Broadcast))
    assert saved.status == "agendado"
    assert saved.repeticao == "once"
    assert saved.proxima_execucao is None
    execution = next(
        value for value in session.added if isinstance(value, BroadcastExecucao)
    )
    delivery = next(
        value for value in session.added if isinstance(value, BroadcastEntrega)
    )
    assert response.json()["execucaoId"] == str(execution.id)
    assert delivery.execucao_id == execution.id
    assert delivery.telefone == "11999990000"


def test_async_now_freezes_recipients_before_worker_tick(app, monkeypatch) -> None:
    _set_rollout(monkeypatch, True)
    reviewed = _person(phone="11999990001")
    client, session, evolution = _wire(
        app,
        people=[reviewed],
        connection=_connection(),
        forbid_network=True,
    )

    response = client.post(
        "/broadcasts", headers=_AUTH, json=_payload(mode="agora")
    )
    session.people.append(_person(phone="11999990002"))

    assert response.status_code == 202
    assert evolution.sent == []
    deliveries = [
        value for value in session.added if isinstance(value, BroadcastEntrega)
    ]
    assert [(row.pessoa_id, row.telefone) for row in deliveries] == [
        (reviewed.id, "11999990001")
    ]


def test_async_requires_idempotency_key_before_persisting(app, monkeypatch) -> None:
    _set_rollout(monkeypatch, True)
    client, session, evolution = _wire(
        app, people=[_person()], connection=_connection(), forbid_network=True
    )

    response = client.post(
        "/broadcasts",
        headers={"Authorization": "Bearer good"},
        json=_payload(mode="agora"),
    )

    assert response.status_code == 400
    assert session.added == []
    assert evolution.sent == []


def test_async_retry_with_same_key_reuses_ledger(app, monkeypatch) -> None:
    _set_rollout(monkeypatch, True)
    client, session, evolution = _wire(
        app,
        people=[_person(phone="11999990001")],
        connection=_connection(),
        forbid_network=True,
    )

    first = client.post("/broadcasts", headers=_AUTH, json=_payload(mode="agora"))
    second = client.post("/broadcasts", headers=_AUTH, json=_payload(mode="agora"))

    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert len([x for x in session.added if isinstance(x, Broadcast)]) == 1
    assert len([x for x in session.added if isinstance(x, BroadcastExecucao)]) == 1
    assert len([x for x in session.added if isinstance(x, BroadcastEntrega)]) == 1
    assert evolution.sent == []


def test_reusing_idempotency_key_for_other_payload_is_rejected(
    app, monkeypatch
) -> None:
    _set_rollout(monkeypatch, True)
    client, session, _evolution = _wire(
        app,
        people=[_person(phone="11999990001")],
        connection=_connection(),
        forbid_network=True,
    )

    first = client.post("/broadcasts", headers=_AUTH, json=_payload(mode="agora"))
    changed = _payload(mode="agora")
    changed["mensagem"] = "Outro comunicado"
    second = client.post("/broadcasts", headers=_AUTH, json=changed)

    assert first.status_code == 202
    assert second.status_code == 409
    assert len([x for x in session.added if isinstance(x, Broadcast)]) == 1


def test_idempotent_replay_reports_real_terminal_ledger(app, monkeypatch) -> None:
    _set_rollout(monkeypatch, True)
    client, session, _evolution = _wire(
        app,
        people=[_person(phone="11999990001")],
        connection=_connection(),
        forbid_network=True,
    )

    first = client.post("/broadcasts", headers=_AUTH, json=_payload(mode="agora"))
    saved = next(value for value in session.added if isinstance(value, Broadcast))
    delivery = next(
        value for value in session.added if isinstance(value, BroadcastEntrega)
    )
    saved.status = "enviado"
    delivery.status = "falhou_permanente"

    replay = client.post("/broadcasts", headers=_AUTH, json=_payload(mode="agora"))

    assert first.status_code == 202
    assert replay.status_code == 200
    assert replay.json()["status"] == "falhou"
    assert replay.json()["enviados"] == 0


def test_flag_true_schedules_future_recurring_broadcast(app, monkeypatch) -> None:
    _set_rollout(monkeypatch, True)
    client, session, evolution = _wire(
        app, people=[_person()], connection=None, forbid_network=True
    )

    response = client.post(
        "/broadcasts",
        headers=_AUTH,
        json=_payload(
            mode="agendado",
            schedule={
                "data": "2099-01-31",
                "hora": "23:59",
                "repeticao": "monthly",
            },
        ),
    )

    assert response.status_code == 202
    assert response.json()["status"] == "agendado"
    assert response.json()["agendadoPara"] == "2099-01-31T23:59"
    assert evolution.sent == []
    saved = next(value for value in session.added if isinstance(value, Broadcast))
    assert saved.repeticao == "monthly"
    assert saved.proxima_execucao is not None


def test_async_now_requires_online_official_instance_without_persisting(
    app, monkeypatch
) -> None:
    _set_rollout(monkeypatch, True)
    client, session, _evolution = _wire(
        app, people=[_person()], connection=_connection(online=False)
    )

    response = client.post(
        "/broadcasts", headers=_AUTH, json=_payload(mode="agora")
    )

    assert response.status_code == 422
    assert not any(isinstance(value, Broadcast) for value in session.added)
    assert session.commits == 0


def test_async_request_fails_closed_without_worker_heartbeat(app, monkeypatch) -> None:
    _set_rollout(monkeypatch, True, worker_ready=False)
    client, session, evolution = _wire(
        app, people=[_person()], connection=_connection(), forbid_network=True
    )

    response = client.post(
        "/broadcasts", headers=_AUTH, json=_payload(mode="agora")
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Worker de comunicados indisponível."
    assert session.added == []
    assert evolution.sent == []


def test_async_zero_reach_still_records_blocked_draft(app, monkeypatch) -> None:
    _set_rollout(monkeypatch, True)
    client, session, evolution = _wire(
        app,
        people=[_person(optout=True)],
        connection=None,
        forbid_network=True,
    )

    response = client.post(
        "/broadcasts", headers=_AUTH, json=_payload(mode="agora")
    )

    assert response.status_code == 200
    assert response.json()["status"] == "bloqueado"
    assert evolution.sent == []
    saved = next(value for value in session.added if isinstance(value, Broadcast))
    assert saved.status == "rascunho"
    assert saved.proxima_execucao is None


def test_capabilities_follow_boot_time_flag(app, monkeypatch) -> None:
    client, _session, _evolution = _wire(app, people=[])

    _set_rollout(monkeypatch, False)
    disabled = client.get("/broadcasts/capabilities", headers=_AUTH)
    assert disabled.status_code == 200
    assert disabled.json() == {
        "agendamentoDisponivel": False,
        "motivo": "despacho_indisponivel",
    }

    _set_rollout(monkeypatch, True)
    enabled = client.get("/broadcasts/capabilities", headers=_AUTH)
    assert enabled.status_code == 200
    assert enabled.json() == {"agendamentoDisponivel": True, "motivo": None}

    _set_rollout(monkeypatch, True, sends_enabled=False)
    outbound_blocked = client.get("/broadcasts/capabilities", headers=_AUTH)
    assert outbound_blocked.status_code == 200
    assert outbound_blocked.json() == {
        "agendamentoDisponivel": False,
        "motivo": "envios_externos_desabilitados",
    }
