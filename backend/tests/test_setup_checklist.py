"""Setup checklist (Missão 7B-7) — GET /setup/checklist.

Cada item reflete estado real, sem bloquear nada (RF §3): identidade (logo),
equipe (mais de 1 usuário ativo), células (>0), whatsapp (status "online"),
agente (credencial BYO validada+ativa) e, só para o DONO, assinatura (status
"ativa" — mesmo gate owner-only da tela #assinatura). Harness offline
(FakeSession por entidade, como test_church_branding.py).
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import (
    AppUser,
    Igreja,
    LlmCredential,
    Subscription,
    UserRole,
    WhatsappConnection,
)
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_IGREJA = "00000000-0000-0000-0000-000000000001"


class _R:
    def __init__(self, *, scalar=None, scalar_one=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalar_one = scalar_one
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar_one

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class SetupSession:
    """Roteia auth (AppUser/UserRole) + as leituras do checklist por entidade.

    Consultas de contagem (``func.count()``) não carregam entidade mapeada
    (``column_descriptions[0]["entity"] is None``), então são roteadas pelo
    nome da tabela no SQL compilado.
    """

    def __init__(
        self,
        *,
        app_user=None,
        roles=None,
        igreja=None,
        team_count=1,
        cell_count=0,
        whatsapp=None,
        credential=None,
        subscription=None,
    ) -> None:
        self.app_user = app_user or make_app_user()
        self.roles = roles if roles is not None else ["admin"]
        self.igreja = igreja
        self.team_count = team_count
        self.cell_count = cell_count
        self.whatsapp = whatsapp
        self.credential = credential
        self.subscription = subscription

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is UserRole:
            return _R(scalars=self.roles)
        if ent is Igreja:
            return _R(scalar=self.igreja)
        if ent is WhatsappConnection:
            return _R(scalar=self.whatsapp)
        if ent is LlmCredential:
            return _R(scalar=self.credential)
        if ent is Subscription:
            return _R(scalar=self.subscription)
        sql = str(statement)
        if "FROM app_users" in sql:
            return _R(scalar_one=self.team_count)
        if "FROM celulas" in sql:
            return _R(scalar_one=self.cell_count)
        return _R()  # text() do set_tenant_context

    def commit(self) -> None:  # pragma: no cover - nada a persistir
        pass

    def close(self) -> None:  # pragma: no cover
        pass


def _wire(app, *, session: SetupSession) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def _igreja(*, logo_path=None):
    return SimpleNamespace(id=_IGREJA, logo_path=logo_path)


def _owner_session(**kwargs) -> SetupSession:
    """Sessão do DONO (make_app_user já é o dono_id da própria igreja)."""
    kwargs.setdefault("igreja", _igreja())
    return SetupSession(**kwargs)


# ---- auth / gating ----------------------------------------------------------
def test_requires_auth(app) -> None:
    resp = _wire(app, session=_owner_session()).get("/setup/checklist")
    assert resp.status_code == 401


def test_forbidden_for_non_admin(app) -> None:
    session = SetupSession(igreja=_igreja(), roles=["membro"])
    resp = _wire(app, session=session).get("/setup/checklist", headers=_AUTH)
    assert resp.status_code == 403


# ---- estado "tudo pendente" ---------------------------------------------------
def test_everything_pending_for_owner_reports_six_items(app) -> None:
    resp = _wire(app, session=_owner_session()).get("/setup/checklist", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    ids = {item["id"] for item in body["items"]}
    assert ids == {"identidade", "equipe", "celulas", "whatsapp", "agente", "assinatura"}
    assert all(item["done"] is False for item in body["items"])
    assert body["pendingCount"] == 6


def test_non_owner_admin_never_sees_assinatura(app) -> None:
    non_owner = make_app_user(dono_id="00000000-0000-0000-0000-0000000000c9")
    session = SetupSession(app_user=non_owner, igreja=_igreja())
    resp = _wire(app, session=session).get("/setup/checklist", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    ids = {item["id"] for item in body["items"]}
    assert "assinatura" not in ids
    assert len(body["items"]) == 5
    assert body["pendingCount"] == 5


# ---- cada item reflete o estado real -----------------------------------------
def test_identidade_done_when_logo_set(app) -> None:
    session = _owner_session(igreja=_igreja(logo_path=f"{_IGREJA}/logo-abc.png"))
    resp = _wire(app, session=session).get("/setup/checklist", headers=_AUTH)
    item = next(i for i in resp.json()["items"] if i["id"] == "identidade")
    assert item["done"] is True


def test_equipe_done_when_more_than_one_active_user(app) -> None:
    session = _owner_session(team_count=3)
    resp = _wire(app, session=session).get("/setup/checklist", headers=_AUTH)
    item = next(i for i in resp.json()["items"] if i["id"] == "equipe")
    assert item["done"] is True


def test_celulas_done_when_at_least_one_exists(app) -> None:
    session = _owner_session(cell_count=2)
    resp = _wire(app, session=session).get("/setup/checklist", headers=_AUTH)
    item = next(i for i in resp.json()["items"] if i["id"] == "celulas")
    assert item["done"] is True


def test_whatsapp_done_only_when_status_online(app) -> None:
    reconectando = _owner_session(whatsapp=SimpleNamespace(status="reconectando"))
    resp = _wire(app, session=reconectando).get("/setup/checklist", headers=_AUTH)
    item = next(i for i in resp.json()["items"] if i["id"] == "whatsapp")
    assert item["done"] is False

    online = _owner_session(whatsapp=SimpleNamespace(status="online"))
    resp = _wire(app, session=online).get("/setup/checklist", headers=_AUTH)
    item = next(i for i in resp.json()["items"] if i["id"] == "whatsapp")
    assert item["done"] is True


def test_agente_requires_credential_validado_and_ativo(app) -> None:
    invalido = _owner_session(
        credential=SimpleNamespace(validado=True, ativo=False)
    )
    resp = _wire(app, session=invalido).get("/setup/checklist", headers=_AUTH)
    item = next(i for i in resp.json()["items"] if i["id"] == "agente")
    assert item["done"] is False

    ativo = _owner_session(credential=SimpleNamespace(validado=True, ativo=True))
    resp = _wire(app, session=ativo).get("/setup/checklist", headers=_AUTH)
    item = next(i for i in resp.json()["items"] if i["id"] == "agente")
    assert item["done"] is True


def test_assinatura_done_only_when_status_ativa(app) -> None:
    pendente = _owner_session(subscription=SimpleNamespace(status="pendente"))
    resp = _wire(app, session=pendente).get("/setup/checklist", headers=_AUTH)
    item = next(i for i in resp.json()["items"] if i["id"] == "assinatura")
    assert item["done"] is False

    ativa = _owner_session(subscription=SimpleNamespace(status="ativa"))
    resp = _wire(app, session=ativa).get("/setup/checklist", headers=_AUTH)
    item = next(i for i in resp.json()["items"] if i["id"] == "assinatura")
    assert item["done"] is True


def test_pending_count_matches_done_items_when_all_configured(app) -> None:
    session = _owner_session(
        igreja=_igreja(logo_path=f"{_IGREJA}/logo-abc.png"),
        team_count=3,
        cell_count=1,
        whatsapp=SimpleNamespace(status="online"),
        credential=SimpleNamespace(validado=True, ativo=True),
        subscription=SimpleNamespace(status="ativa"),
    )
    resp = _wire(app, session=session).get("/setup/checklist", headers=_AUTH)
    body = resp.json()
    assert all(item["done"] is True for item in body["items"])
    assert body["pendingCount"] == 0
