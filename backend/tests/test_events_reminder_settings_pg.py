"""Panel event reminder settings against disposable PostgreSQL RLS."""
from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Event
from app.db.session import get_db
from app.db.tenant_session import mark_tenant_scoped
from app.deps import CurrentUser, get_current_user
from tests.conftest_rls import rls_database_url  # noqa: F401
from tests.test_messages_inbound_idempotency import msg_engine_fx  # noqa: F401
from tests.test_whatsapp_agenda_pg import _TENANT_A, _TENANT_B, agenda_rls

pytestmark = pytest.mark.rls_integration


def _user(tenant: uuid.UUID, roles: tuple[str, ...]) -> CurrentUser:
    return CurrentUser(
        app_user_id=str(uuid.uuid5(tenant, "agenda-author")),
        clerk_user_id=f"clerk-{tenant.hex}",
        igreja_id=str(tenant),
        email=f"agenda-{tenant.hex}@example.test",
        nome="Autor Sintético",
        roles=frozenset(roles),
    )


def _client(app, factory, tenant: uuid.UUID, roles: tuple[str, ...]):
    session = factory()
    mark_tenant_scoped(session, tenant, source="agenda_reminder_settings_api")
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: _user(tenant, roles)
    return TestClient(app), session


def _read_event(
    factory, tenant: uuid.UUID, event_id: uuid.UUID
) -> tuple[int | None, list[str] | None, str | None]:
    session = factory()
    try:
        mark_tenant_scoped(session, tenant, source="agenda_reminder_settings_assert")
        event = session.execute(
            select(Event).where(Event.igreja_id == tenant, Event.id == event_id)
        ).scalar_one()
        return event.antecedencia_horas, event.publico_alvo, event.canal
    finally:
        session.rollback()
        session.close()


def test_pastor_can_create_event_with_reminder_settings_pg(
    app, agenda_rls, rls_database_url: str
):
    client, session = _client(app, agenda_rls, _TENANT_A, ("pastor",))
    response = client.post(
        "/events",
        json={
            "titulo": "Encontro sintético",
            "data": (dt.date.today() + dt.timedelta(days=7)).isoformat(),
            "hora": "19:30",
            "antecedenciaHoras": 24,
            "publicoAlvo": ["lideres_celula"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["antecedenciaHoras"] == 24
    assert body["publicoAlvo"] == ["lideres_celula"]
    assert body["canal"] == "whatsapp"
    assert _read_event(agenda_rls, _TENANT_A, uuid.UUID(body["id"])) == (
        24,
        ["lideres_celula"],
        "whatsapp",
    )
    session.close()


def test_pastor_can_edit_event_reminder_settings_pg(
    app, agenda_rls, rls_database_url: str
):
    event_id = uuid.uuid5(_TENANT_A, "agenda-event")
    client, session = _client(app, agenda_rls, _TENANT_A, ("pastor",))
    response = client.put(
        f"/events/{event_id}",
        json={
            "antecedenciaHoras": 2,
            "publicoAlvo": ["pastores", "lideres_celula"],
        },
    )

    assert response.status_code == 200
    assert response.json()["antecedenciaHoras"] == 2
    assert response.json()["publicoAlvo"] == ["pastores", "lideres_celula"]
    assert _read_event(agenda_rls, _TENANT_A, event_id) == (
        2,
        ["pastores", "lideres_celula"],
        "whatsapp",
    )
    session.close()


def test_removing_relative_window_preserves_absolute_reminder_pg(
    app, agenda_rls, rls_database_url: str
):
    event_id = uuid.uuid5(_TENANT_A, "agenda-event")
    absolute_at = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
    with agenda_rls.begin() as setup:
        mark_tenant_scoped(setup, _TENANT_A, source="agenda_reminder_absolute_setup")
        event = setup.execute(
            select(Event).where(Event.igreja_id == _TENANT_A, Event.id == event_id)
        ).scalar_one()
        event.publico_alvo = ["toda_igreja"]
        event.antecedencia_horas = 24
        event.notificar_em = absolute_at
        event.canal = "whatsapp"

    client, session = _client(app, agenda_rls, _TENANT_A, ("pastor",))
    response = client.put(
        f"/events/{event_id}",
        json={"antecedenciaHoras": None},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["antecedenciaHoras"] is None
    assert body["canal"] == "whatsapp"
    assert dt.datetime.fromisoformat(
        body["notificarEm"].replace("Z", "+00:00")
    ) == absolute_at
    assert _read_event(agenda_rls, _TENANT_A, event_id) == (
        None,
        ["toda_igreja"],
        "whatsapp",
    )
    session.close()


def test_member_cannot_edit_event_reminder_settings_pg(
    app, agenda_rls, rls_database_url: str
):
    event_id = uuid.uuid5(_TENANT_A, "agenda-event")
    client, session = _client(app, agenda_rls, _TENANT_A, ("membro",))
    response = client.put(
        f"/events/{event_id}",
        json={
            "antecedenciaHoras": 2,
            "publicoAlvo": ["pastores"],
        },
    )

    assert response.status_code == 403
    assert _read_event(agenda_rls, _TENANT_A, event_id) == (None, None, None)
    session.close()


def test_pastor_cannot_edit_another_church_event_reminder_settings_pg(
    app, agenda_rls, rls_database_url: str
):
    other_event_id = uuid.uuid5(_TENANT_B, "agenda-event")
    client, session = _client(app, agenda_rls, _TENANT_A, ("pastor",))
    response = client.put(
        f"/events/{other_event_id}",
        json={
            "antecedenciaHoras": 2,
            "publicoAlvo": ["pastores"],
        },
    )

    assert response.status_code == 404
    assert _read_event(agenda_rls, _TENANT_B, other_event_id) == (None, None, None)
    session.close()
