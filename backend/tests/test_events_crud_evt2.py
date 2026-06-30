"""EVT-2 — CRUD de eventos + confirmação manual.

Harness offline (FakeSession-style): roteia a auth (AppUser/UserRole) e o lookup
do Event por entidade, sem DB real. Cobre os contratos HTTP novos:

  - GET    /events/{id}          encontrado / 404 (inexistente ou outro tenant);
  - PUT    /events/{id}          edita campos permitidos;
  - DELETE /events/{id}          remove (204);
  - POST   /events/{id}/confirm  seta status/confirmado_em/confirmado_por; 409 se
                                  já confirmado;
  - POST   /events               bloqueia lider_g12, permite pastor/admin.

O filtro `igreja_id` no nível de query (defesa em profundidade além da RLS) é
provado inspecionando o PREDICADO WHERE do SELECT por id (`statement.whereclause`),
que exclui a projeção de colunas — `events.igreja_id` só aparece ali se `_get_event`
realmente filtra por tenant (e a asserção falha se o predicado for removido). O fake
ignora o WHERE ao devolver o objeto canônico, então o 404 "outro tenant" é simulado
com event=None (é o que a RLS + filtro igreja_id produziriam); a barreira efetiva
entre tenants é a RLS, exercitada fora deste harness offline.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Event
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_EID = "00000000-0000-0000-0000-0000000000e2"
# id do app_user dono (igual ao de make_app_user) — vira confirmado_por.
_UID = "00000000-0000-0000-0000-0000000000a1"


class _R:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class EventSession:
    """Roteia auth (AppUser/UserRole) + o lookup do Event por id."""

    def __init__(self, *, app_user, roles, event) -> None:
        self.app_user = app_user
        self.roles = roles
        self.event = event
        self.committed = False
        self.deleted = None
        self.added = None
        self.last_event_stmt = None

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is Event:
            self.last_event_stmt = statement
            return _R(scalar=self.event)
        return _R(scalars=self.roles)

    def add(self, obj) -> None:
        self.added = obj

    def delete(self, obj) -> None:
        self.deleted = obj

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


def make_event(
    *,
    status="confirmado",
    confirmado_em=None,
    confirmado_por=None,
    titulo="Culto",
    data=dt.date(2026, 1, 1),
    hora="19:30",
    descricao="Domingo",
):
    return SimpleNamespace(
        id=_EID,
        igreja_id="00000000-0000-0000-0000-000000000001",
        titulo=titulo,
        data=data,
        hora=hora,
        descricao=descricao,
        google_event_id=None,
        status=status,
        origem="manual",
        recorrencia="pontual",
        confirmado_em=confirmado_em,
        confirmado_por=confirmado_por,
    )


def _wire(app, *, session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def _session(*, roles, event=None):
    return EventSession(app_user=make_app_user(), roles=roles, event=event)


def _last_event_where(session) -> str:
    """SQL apenas do predicado WHERE do último SELECT de Event (sem a projeção).

    `str(stmt.whereclause)` rende só a cláusula WHERE — ex.:
    ``events.id = :id_1 AND events.igreja_id = :igreja_id_1`` — então a presença
    de ``events.igreja_id`` aqui prova o filtro de tenant, não a lista de colunas
    do SELECT (onde igreja_id sempre apareceria por ser coluna mapeada). Substring
    de ``tabela.coluna`` é estável a espaçamento/nome de bind param.
    """
    where = getattr(session.last_event_stmt, "whereclause", None)
    return str(where) if where is not None else ""


# ---- GET /events/{id} ------------------------------------------------------
def test_get_event_found(app) -> None:
    session = _session(roles=["admin"], event=make_event())
    resp = _wire(app, session=session).get(f"/events/{_EID}", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == _EID
    assert body["titulo"] == "Culto"
    assert body["status"] == "confirmado"
    assert body["origem"] == "manual"
    # Prova o filtro de tenant NO PREDICADO WHERE (não na projeção): _get_event
    # filtra por Event.id E Event.igreja_id. A asserção falha se o predicado
    # igreja_id for removido do router (defesa em profundidade além da RLS).
    where_sql = _last_event_where(session)
    assert "events.id" in where_sql
    assert "events.igreja_id" in where_sql


def test_get_event_404_other_tenant_or_missing(app) -> None:
    # event=None simula tanto inexistente quanto evento de outro tenant (que a
    # RLS + filtro igreja_id removeriam do resultado).
    session = _session(roles=["admin"], event=None)
    resp = _wire(app, session=session).get(f"/events/{_EID}", headers=_AUTH)
    assert resp.status_code == 404


def test_get_event_malformed_id_is_404(app) -> None:
    session = _session(roles=["admin"], event=make_event())
    resp = _wire(app, session=session).get("/events/nao-e-uuid", headers=_AUTH)
    assert resp.status_code == 404


# ---- PUT /events/{id} ------------------------------------------------------
def test_put_updates_allowed_fields(app) -> None:
    event = make_event(titulo="Antigo", hora="19:30", descricao="x")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).put(
        f"/events/{_EID}",
        headers=_AUTH,
        json={"titulo": "Culto Novo", "hora": "20:00", "descricao": "Atualizado"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["titulo"] == "Culto Novo"
    assert body["hora"] == "20:00"
    assert body["descricao"] == "Atualizado"
    assert event.titulo == "Culto Novo"
    assert event.hora == "20:00"
    assert session.committed is True


def test_put_omitted_fields_unchanged(app) -> None:
    event = make_event(titulo="Mantido", hora="19:30")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).put(
        f"/events/{_EID}", headers=_AUTH, json={"descricao": "só isso"}
    )
    assert resp.status_code == 200
    assert event.titulo == "Mantido"
    assert event.hora == "19:30"
    assert event.descricao == "só isso"


def test_put_rejects_invalid_hora(app) -> None:
    session = _session(roles=["pastor"], event=make_event())
    resp = _wire(app, session=session).put(
        f"/events/{_EID}", headers=_AUTH, json={"hora": "25:99"}
    )
    assert resp.status_code == 422


def test_put_404_when_missing(app) -> None:
    session = _session(roles=["pastor"], event=None)
    resp = _wire(app, session=session).put(
        f"/events/{_EID}", headers=_AUTH, json={"titulo": "X"}
    )
    assert resp.status_code == 404


# ---- DELETE /events/{id} ---------------------------------------------------
def test_delete_removes(app) -> None:
    event = make_event()
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).delete(f"/events/{_EID}", headers=_AUTH)
    assert resp.status_code == 204
    assert session.deleted is event
    assert session.committed is True


def test_delete_404_when_missing(app) -> None:
    session = _session(roles=["pastor"], event=None)
    resp = _wire(app, session=session).delete(f"/events/{_EID}", headers=_AUTH)
    assert resp.status_code == 404


# ---- POST /events/{id}/confirm ---------------------------------------------
def test_confirm_sets_status_and_audit_fields(app) -> None:
    event = make_event(status="a_confirmar")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm", headers=_AUTH
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirmado"
    assert body["confirmadoEm"] is not None
    assert body["confirmadoPor"] == _UID
    assert event.status == "confirmado"
    assert event.confirmado_em is not None
    assert str(event.confirmado_por) == _UID
    assert session.committed is True


def test_confirm_already_confirmed_is_409(app) -> None:
    event = make_event(status="confirmado")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm", headers=_AUTH
    )
    assert resp.status_code == 409
    # não mexeu no evento.
    assert event.confirmado_em is None


def test_confirm_404_when_missing(app) -> None:
    session = _session(roles=["pastor"], event=None)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm", headers=_AUTH
    )
    assert resp.status_code == 404


# ---- POST /events — gate de papel (remove lider_g12) -----------------------
def test_create_blocks_lider_g12(app) -> None:
    session = _session(roles=["lider_g12"])
    resp = _wire(app, session=session).post(
        "/events",
        headers=_AUTH,
        json={"titulo": "Culto", "data": "2026-01-01", "hora": "19:30"},
    )
    assert resp.status_code == 403


def test_create_allows_pastor(app) -> None:
    session = _session(roles=["pastor"])
    resp = _wire(app, session=session).post(
        "/events",
        headers=_AUTH,
        json={"titulo": "Culto", "data": "2026-01-01", "hora": "19:30"},
    )
    assert resp.status_code == 200
    assert session.added is not None


def test_create_allows_admin(app) -> None:
    session = _session(roles=["admin"])
    resp = _wire(app, session=session).post(
        "/events",
        headers=_AUTH,
        json={"titulo": "Culto", "data": "2026-01-01", "hora": "19:30"},
    )
    assert resp.status_code == 200


# ---- POST /events — EVT-6 PR6.0: push Google legado desarmado ---------------
def test_create_does_not_call_legacy_google_push(app, monkeypatch) -> None:
    """O create NÃO invoca mais `GoogleCalendarClient.create_event`.

    O push legado usava o token GLOBAL de settings (risco multi-tenant) e gerava
    órfãos (PUT não ressincroniza, DELETE não remove). Aqui patchamos o método do
    cliente legado para registrar qualquer chamada: o evento deve ser criado só no
    banco, sem tocar esse caminho. Se alguém reintroduzir o push global, `calls`
    deixa de ser vazio e este teste falha.
    """
    calls: list = []

    def _record(self, **kwargs):  # pragma: no cover - não deve ser chamado
        calls.append(kwargs)
        return "should-not-be-used"

    monkeypatch.setattr(
        "app.services.google_calendar.GoogleCalendarClient.create_event", _record
    )

    session = _session(roles=["pastor"])
    resp = _wire(app, session=session).post(
        "/events",
        headers=_AUTH,
        json={"titulo": "Culto", "data": "2026-01-01", "hora": "19:30"},
    )

    assert resp.status_code == 200
    assert calls == []  # push legado nunca chamado
    assert session.added is not None
    body = resp.json()
    # contrato preservado: sem google_event_id => não sincronizado.
    assert body["sincronizado"] is False
    assert body.get("googleEventId") is None
