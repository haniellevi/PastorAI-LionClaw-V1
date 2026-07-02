"""EVT-7 PR2 — CRUD dos destinatários de alerta da Agenda (admin-only).

Harness offline (FakeSession-style, como test_events_crud_evt2): roteia a auth
(AppUser/UserRole) e os selects de AgendaAlertRecipient por entidade, sem DB real.
Cobre o contrato HTTP novo (/calendar/recipients):

  - GET    /calendar/recipients          lista (admin); 403 p/ não-admin;
  - POST   /calendar/recipients          cria, normaliza telefone; 409 dup ativo;
                                          422 telefone sem dígitos; 403 não-admin;
  - PUT    /calendar/recipients/{id}     edita/desativa (admin); 404; 403 não-admin;
  - DELETE /calendar/recipients/{id}     remove (admin); 404; 403 não-admin.

Nenhum endpoint envia nada (o envio é do event_notify, atrás da flag). Também
verifica que modelo e migration espelham a tabela.
"""

from __future__ import annotations

import pathlib
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AgendaAlertRecipient, AppUser
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_RID = "00000000-0000-0000-0000-0000000000c1"


class _R:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class RecipientSession:
    """Roteia auth (AppUser/UserRole) + selects de AgendaAlertRecipient.

    ``recipient`` responde o lookup por id (scalar_one_or_none); ``recipients``
    responde a lista / o dedup (scalars().all()). Nenhum teste precisa dos dois
    papéis de ``recipients`` ao mesmo tempo, então cada cenário fixa o que usa.
    """

    def __init__(self, *, app_user, roles, recipient=None, recipients=None) -> None:
        self.app_user = app_user
        self.roles = roles
        self.recipient = recipient
        self.recipients = recipients or []
        self.committed = False
        self.added = None
        self.deleted = None

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is AgendaAlertRecipient:
            return _R(scalar=self.recipient, scalars=self.recipients)
        return _R(scalars=self.roles)

    def add(self, obj) -> None:
        self.added = obj

    def delete(self, obj) -> None:
        self.deleted = obj

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        # O DB atribui id (server_default gen_random_uuid) e ativo (default true)
        # no flush; simulamos aqui para o RecipientOut serializar.
        if getattr(obj, "id", None) is None:
            obj.id = uuid.UUID(_RID)
        if getattr(obj, "ativo", None) is None:
            obj.ativo = True

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


_IGREJA = "00000000-0000-0000-0000-000000000001"


def _recipient(*, rid=_RID, nome="Secretaria", telefone="11999990000", ativo=True):
    return SimpleNamespace(
        id=rid, igreja_id=_IGREJA, nome=nome, telefone=telefone, ativo=ativo
    )


def _wire(app, *, session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def _session(*, roles, recipient=None, recipients=None) -> RecipientSession:
    return RecipientSession(
        app_user=make_app_user(),
        roles=roles,
        recipient=recipient,
        recipients=recipients,
    )


# ---- GET /calendar/recipients ----------------------------------------------
def test_list_returns_recipients_for_admin(app) -> None:
    session = _session(
        roles=["admin"],
        recipients=[_recipient(nome="A"), _recipient(rid="x", nome="B", ativo=False)],
    )
    resp = _wire(app, session=session).get("/calendar/recipients", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["recipients"]) == 2
    first = body["recipients"][0]
    assert set(first) == {"id", "nome", "telefone", "ativo"}  # sem segredo
    assert first["nome"] == "A"


def test_list_blocks_non_admin(app) -> None:
    session = _session(roles=["pastor"])
    resp = _wire(app, session=session).get("/calendar/recipients", headers=_AUTH)
    assert resp.status_code == 403


# ---- POST /calendar/recipients ---------------------------------------------
def test_create_admin_normalizes_phone(app) -> None:
    session = _session(roles=["admin"], recipients=[])
    resp = _wire(app, session=session).post(
        "/calendar/recipients",
        headers=_AUTH,
        json={"nome": "  Pastor  ", "telefone": "+55 (11) 99999-0000"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["nome"] == "Pastor"
    assert body["telefone"] == "11999990000"  # normalize_phone: dígitos, sem 55
    assert body["ativo"] is True
    assert session.added is not None
    assert session.added.telefone == "11999990000"
    assert session.committed is True


def test_create_rejects_phone_without_digits(app) -> None:
    session = _session(roles=["admin"], recipients=[])
    resp = _wire(app, session=session).post(
        "/calendar/recipients",
        headers=_AUTH,
        json={"nome": "X", "telefone": "sem-numero"},
    )
    assert resp.status_code == 422


def test_create_conflict_when_active_dup_exists(app) -> None:
    # recipients não-vazio simula um destinatário ATIVO já com esse telefone.
    session = _session(roles=["admin"], recipients=[uuid.uuid4()])
    resp = _wire(app, session=session).post(
        "/calendar/recipients",
        headers=_AUTH,
        json={"nome": "X", "telefone": "11999990000"},
    )
    assert resp.status_code == 409
    assert session.added is None


def test_create_blocks_non_admin(app) -> None:
    session = _session(roles=["pastor"], recipients=[])
    resp = _wire(app, session=session).post(
        "/calendar/recipients",
        headers=_AUTH,
        json={"nome": "X", "telefone": "11999990000"},
    )
    assert resp.status_code == 403


# ---- PUT /calendar/recipients/{id} -----------------------------------------
def test_update_edits_and_deactivates(app) -> None:
    rec = _recipient(nome="Antigo", ativo=True)
    session = _session(roles=["admin"], recipient=rec, recipients=[])
    resp = _wire(app, session=session).put(
        f"/calendar/recipients/{_RID}",
        headers=_AUTH,
        json={"nome": "Novo", "ativo": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["nome"] == "Novo"
    assert body["ativo"] is False
    assert rec.nome == "Novo"
    assert rec.ativo is False
    assert session.committed is True


def test_update_conflict_on_reactivate_dup(app) -> None:
    rec = _recipient(ativo=False)
    session = _session(roles=["admin"], recipient=rec, recipients=[uuid.uuid4()])
    resp = _wire(app, session=session).put(
        f"/calendar/recipients/{_RID}", headers=_AUTH, json={"ativo": True}
    )
    assert resp.status_code == 409


def test_update_404_when_missing(app) -> None:
    session = _session(roles=["admin"], recipient=None)
    resp = _wire(app, session=session).put(
        f"/calendar/recipients/{_RID}", headers=_AUTH, json={"nome": "X"}
    )
    assert resp.status_code == 404


def test_update_blocks_non_admin(app) -> None:
    session = _session(roles=["pastor"], recipient=_recipient())
    resp = _wire(app, session=session).put(
        f"/calendar/recipients/{_RID}", headers=_AUTH, json={"nome": "X"}
    )
    assert resp.status_code == 403


# ---- DELETE /calendar/recipients/{id} --------------------------------------
def test_delete_removes(app) -> None:
    rec = _recipient()
    session = _session(roles=["admin"], recipient=rec)
    resp = _wire(app, session=session).delete(
        f"/calendar/recipients/{_RID}", headers=_AUTH
    )
    assert resp.status_code == 204
    assert session.deleted is rec
    assert session.committed is True


def test_delete_404_when_missing(app) -> None:
    session = _session(roles=["admin"], recipient=None)
    resp = _wire(app, session=session).delete(
        f"/calendar/recipients/{_RID}", headers=_AUTH
    )
    assert resp.status_code == 404


def test_delete_blocks_non_admin(app) -> None:
    session = _session(roles=["pastor"], recipient=_recipient())
    resp = _wire(app, session=session).delete(
        f"/calendar/recipients/{_RID}", headers=_AUTH
    )
    assert resp.status_code == 403


# ---- modelo + migration ----------------------------------------------------
def test_model_and_migration_mirror_table() -> None:
    cols = AgendaAlertRecipient.__table__.columns
    for name in ("igreja_id", "nome", "telefone", "ativo", "created_at", "updated_at"):
        assert name in cols
    assert cols["nome"].nullable is False
    assert cols["telefone"].nullable is False
    assert cols["ativo"].nullable is False
    assert cols["updated_at"].nullable is True

    mig = (
        pathlib.Path(__file__).resolve().parents[1]
        / "migrations"
        / "20260701_193000_evt7_pr2_agenda_alert_recipients.sql"
    )
    sql = mig.read_text(encoding="utf-8").lower()
    assert "create table if not exists agenda_alert_recipients" in sql
    assert "references igrejas(id) on delete cascade" in sql
    assert "where ativo" in sql  # índice único parcial só p/ ativos
    assert "enable row level security" in sql
    assert "tenant_isolation" in sql
