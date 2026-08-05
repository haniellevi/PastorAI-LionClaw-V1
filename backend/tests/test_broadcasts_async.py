"""Router contracts for the boot-time broadcast async rollout flag."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.routers.broadcasts as broadcasts_router
from app.db.models import AppUser, Broadcast, Celula, Pessoa, WhatsappConnection
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from app.services.evolution import get_evolution_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_INSTANCE = "igreja-piloto"


class _Result:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


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
            return _Result(scalars=[])
        return _Result(scalars=["admin"])

    def add(self, value) -> None:
        self.added.append(value)

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
    monkeypatch, async_enabled: bool, *, sends_enabled: bool = True
) -> None:
    monkeypatch.setattr(
        broadcasts_router,
        "get_settings",
        lambda: SimpleNamespace(
            broadcast_async_enabled=async_enabled,
            external_sends_enabled=sends_enabled,
        ),
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


def test_flag_false_preserves_synchronous_now_contract(app, monkeypatch) -> None:
    _set_rollout(monkeypatch, False)
    client, session, evolution = _wire(
        app, people=[_person()], connection=_connection()
    )

    response = client.post(
        "/broadcasts", headers=_AUTH, json=_payload(mode="agora")
    )

    assert response.status_code == 200
    assert response.json()["status"] == "enviado"
    assert response.json()["enviados"] == 1
    assert len(evolution.sent) == 1
    saved = next(value for value in session.added if isinstance(value, Broadcast))
    assert saved.status == "enviado"
    assert saved.proxima_execucao is None


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
    assert saved.proxima_execucao is not None


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
