"""EVT-1 — schema/model da Agenda de Eventos.

O harness de testes é in-memory (FakeSession não persiste), então não há como
exercitar a migration SQL, a RLS ou os CHECK do Postgres aqui. Estes testes
cobrem o que é verificável em Python puro:

  - o modelo `Event` ganhou as colunas do EVT-1 com a nullability/defaults certos
    (espelhando o backfill da migration);
  - `data` virou nullable (eventos semanais);
  - o validador de `hora` (HH:MM) do payload aceita/rejeita o esperado;
  - o POST /events continua devolvendo 422 para hora inválida (contrato HTTP).

A validação da migration em si (enums, constraints, RLS) é por revisão do SQL —
ver docs/design/AGENDA-EVENTOS-EVT0-decisao.md e a própria migration.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.db.models import Event
from app.db.session import get_db
from app.routers.events import CreateEventRequest, EventOut
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user

_AUTH = {"Authorization": "Bearer good"}


def _client(app) -> TestClient:
    app.dependency_overrides[get_db] = lambda: FakeSession(
        app_user=make_app_user(), roles=["admin"]
    )
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


# ---- model: colunas novas + defaults/backfill ------------------------------
def test_event_model_has_evt1_columns() -> None:
    cols = Event.__table__.columns
    for name in (
        "status",
        "tipo",
        "origem",
        "recorrencia",
        "dia_semana",
        "publico_alvo",
        "antecedencia_horas",
        "mensagem_confirmacao",
        "confirmado_em",
        "confirmado_por",
    ):
        assert name in cols, f"coluna {name} faltando no modelo Event"


def test_event_model_backfill_defaults() -> None:
    """status/origem/recorrencia são NOT NULL com default => backfill seguro."""
    cols = Event.__table__.columns
    for name, default in (
        ("status", "confirmado"),
        ("origem", "manual"),
        ("recorrencia", "pontual"),
    ):
        col = cols[name]
        assert col.nullable is False, f"{name} deveria ser NOT NULL"
        assert col.server_default is not None, f"{name} deveria ter server_default"
        assert default in str(col.server_default.arg), (
            f"{name} default deveria ser '{default}'"
        )


def test_event_model_optional_columns_are_nullable() -> None:
    cols = Event.__table__.columns
    # `data` agora é nullable (eventos semanais não têm data específica).
    assert cols["data"].nullable is True
    for name in (
        "tipo",
        "dia_semana",
        "publico_alvo",
        "antecedencia_horas",
        "mensagem_confirmacao",
        "confirmado_em",
        "confirmado_por",
    ):
        assert cols[name].nullable is True, f"{name} deveria ser nullable"


def test_confirmado_por_fk_to_app_users() -> None:
    fks = list(Event.__table__.c.confirmado_por.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "app_users"


# ---- schema: validação de hora (HH:MM) -------------------------------------
@pytest.mark.parametrize("hora", ["00:00", "09:05", "19:30", "23:59"])
def test_create_event_accepts_valid_hora(hora: str) -> None:
    req = CreateEventRequest(titulo="Culto", data=dt.date(2026, 1, 1), hora=hora)
    assert req.hora == hora


@pytest.mark.parametrize("hora", ["24:00", "19:60", "7:30", "1930", "19h30", "abc"])
def test_create_event_rejects_invalid_hora(hora: str) -> None:
    with pytest.raises(ValidationError):
        CreateEventRequest(titulo="Culto", data=dt.date(2026, 1, 1), hora=hora)


def test_create_event_blank_hora_becomes_none() -> None:
    req = CreateEventRequest(titulo="Culto", data=dt.date(2026, 1, 1), hora="  ")
    assert req.hora is None


# ---- EventOut: serializa evento semanal (data=None) sem quebrar ------------
def test_eventout_from_model_handles_null_data() -> None:
    """Evento semanal não tem data específica; EventOut.data agora é opcional,
    senão o GET /events estouraria 500 ao serializar uma linha data=None."""
    ev = Event(
        id=uuid.uuid4(),
        titulo="Culto de quarta",
        data=None,
        recorrencia="semanal",
        dia_semana=3,
    )
    out = EventOut.from_model(ev)
    assert out.data is None
    assert out.titulo == "Culto de quarta"


# ---- HTTP: contrato 422 (espelha test_event_requires_data) -----------------
def test_post_events_rejects_invalid_hora(app) -> None:
    resp = _client(app).post(
        "/events",
        json={"titulo": "Culto", "data": "2026-01-01", "hora": "25:99"},
        headers=_AUTH,
    )
    assert resp.status_code == 422
