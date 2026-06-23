"""Edge tests for whatsapp/conversations routers: auth, RBAC and webhook."""

from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import AppUser, Conversation, Message, UserRole, WhatsappConnection
from app.db.session import get_db
from app.routers.whatsapp import get_webhook_queue
from app.services.clerk import get_clerk_client
from app.services.evolution import get_evolution_client
from tests.conftest import FakeClerk, FakeSession, make_app_user

_AUTH = {"Authorization": "Bearer good"}


class _FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list = []

    def enqueue(self, payload) -> None:
        self.enqueued.append(payload)


def _client(app, roles: list[str]) -> TestClient:
    app.dependency_overrides[get_db] = lambda: FakeSession(
        app_user=make_app_user(), roles=roles
    )
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


# ---- auth gating ----------------------------------------------------------
def test_conversations_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    assert client.get("/conversations").status_code == 401


def test_whatsapp_connection_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    assert client.get("/whatsapp/connection").status_code == 401


# ---- inbox RBAC (US-11) ---------------------------------------------------
def test_cell_leader_forbidden_on_conversations(app) -> None:
    client = _client(app, roles=["lider_celula"])
    assert client.get("/conversations", headers=_AUTH).status_code == 403


def test_cell_leader_forbidden_on_handoff(app) -> None:
    client = _client(app, roles=["lider_celula"])
    resp = client.post(
        "/conversations/00000000-0000-0000-0000-0000000000aa/handoff",
        json={"to": "human"},
        headers=_AUTH,
    )
    assert resp.status_code == 403


# ---- whatsapp connection RBAC (admin only) --------------------------------
def test_cell_leader_forbidden_on_whatsapp_connection(app) -> None:
    client = _client(app, roles=["lider_celula"])
    assert client.get("/whatsapp/connection", headers=_AUTH).status_code == 403


# ---- inbox messages: auth, RBAC and validation (US-13) --------------------
_CONV_MSGS = "/conversations/00000000-0000-0000-0000-0000000000aa/messages"


def test_messages_history_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    assert client.get(_CONV_MSGS).status_code == 401


def test_cell_leader_forbidden_on_messages_history(app) -> None:
    client = _client(app, roles=["lider_celula"])
    assert client.get(_CONV_MSGS, headers=_AUTH).status_code == 403


def test_send_message_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    assert client.post(_CONV_MSGS, json={"texto": "oi"}).status_code == 401


def test_cell_leader_forbidden_on_send_message(app) -> None:
    client = _client(app, roles=["lider_celula"])
    resp = client.post(_CONV_MSGS, json={"texto": "oi"}, headers=_AUTH)
    assert resp.status_code == 403


def test_send_message_rejects_empty_text(app) -> None:
    client = _client(app, roles=["admin"])
    resp = client.post(_CONV_MSGS, json={"texto": "   "}, headers=_AUTH)
    assert resp.status_code == 422


# ---- inbox media send: auth, RBAC and validation (Etapa 2) ----------------
_CONV_MEDIA = "/conversations/00000000-0000-0000-0000-0000000000aa/messages/media"


def test_send_media_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    resp = client.post(_CONV_MEDIA, json={"mime": "image/png", "base64": "Zm9v"})
    assert resp.status_code == 401


def test_cell_leader_forbidden_on_send_media(app) -> None:
    client = _client(app, roles=["lider_celula"])
    resp = client.post(
        _CONV_MEDIA, json={"mime": "image/png", "base64": "Zm9v"}, headers=_AUTH
    )
    assert resp.status_code == 403


def test_send_media_rejects_missing_fields(app) -> None:
    client = _client(app, roles=["admin"])
    resp = client.post(_CONV_MEDIA, json={"mime": "image/png"}, headers=_AUTH)
    assert resp.status_code == 422


# ---- MessageOut carrega o nome de quem respondeu (Parte A) -----------------
def test_message_out_maps_author_name() -> None:
    from types import SimpleNamespace

    from app.routers.conversations import MessageOut

    m = SimpleNamespace(
        id="m1",
        direcao="out",
        autor="humano",
        autor_nome="Pastor Raniel",
        tipo="texto",
        texto="oi",
        media_mime=None,
        media_nome=None,
        criado_em=None,
    )
    out = MessageOut.from_model(m)
    assert out.autorNome == "Pastor Raniel"
    assert out.autor == "humano"
    assert out.direcao == "out"


def test_author_caption_prefixes_name_for_whatsapp() -> None:
    # O contato precisa ver QUEM respondeu: o nome vai prefixado no texto.
    from app.routers.conversations import _author_caption

    assert _author_caption("Pastor Raniel", "oi") == "*Pastor Raniel:*\noi"
    assert _author_caption("Pastor Raniel", None) == "*Pastor Raniel:*"
    assert _author_caption("Pastor Raniel", "") == "*Pastor Raniel:*"


# ---- validation -----------------------------------------------------------
def test_handoff_rejects_invalid_target(app) -> None:
    client = _client(app, roles=["admin"])
    resp = client.post(
        "/conversations/00000000-0000-0000-0000-0000000000aa/handoff",
        json={"to": "bot"},
        headers=_AUTH,
    )
    assert resp.status_code == 422


def test_whatsapp_connection_rejects_invalid_action(app) -> None:
    client = _client(app, roles=["admin"])
    resp = client.post(
        "/whatsapp/connection", json={"action": "delete"}, headers=_AUTH
    )
    assert resp.status_code == 422


# ---- webhook signature ----------------------------------------------------
def _webhook_client(app) -> TestClient:
    app.dependency_overrides[get_webhook_queue] = lambda: _FakeQueue()
    return TestClient(app)


def test_webhook_rejects_invalid_signature(app, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "evolution_webhook_secret", "topsecret")
    client = _webhook_client(app)
    resp = client.post(
        "/whatsapp/webhook",
        content=b'{"event":"messages.upsert"}',
        headers={"x-evolution-signature": "wrong"},
    )
    assert resp.status_code == 401


def test_webhook_accepts_valid_signature(app, monkeypatch) -> None:
    secret = "topsecret"
    monkeypatch.setattr(get_settings(), "evolution_webhook_secret", secret)
    queue = _FakeQueue()
    app.dependency_overrides[get_webhook_queue] = lambda: queue
    client = TestClient(app)

    body = json.dumps({"event": "messages.upsert", "instance": "igreja-1"}).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    resp = client.post(
        "/whatsapp/webhook",
        content=body,
        headers={"x-evolution-signature": sig},
    )
    assert resp.status_code == 202
    assert len(queue.enqueued) == 1


def test_webhook_accepts_valid_query_token(app, monkeypatch) -> None:
    # Evolution v2 self-hosted authenticates via the URL query string (?token=).
    secret = "topsecret"
    monkeypatch.setattr(get_settings(), "evolution_webhook_secret", secret)
    queue = _FakeQueue()
    app.dependency_overrides[get_webhook_queue] = lambda: queue
    client = TestClient(app)

    body = json.dumps({"event": "messages.upsert", "instance": "igreja-1"}).encode()
    resp = client.post(
        f"/whatsapp/webhook?token={secret}",
        content=body,
    )
    assert resp.status_code == 202
    assert len(queue.enqueued) == 1


def test_webhook_rejects_invalid_query_token(app, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "evolution_webhook_secret", "topsecret")
    client = _webhook_client(app)
    resp = client.post(
        "/whatsapp/webhook?token=wrong",
        content=b'{"event":"messages.upsert"}',
    )
    assert resp.status_code == 401


# ---- excluir conversa: auth, RBAC e sucesso (hard delete, admin-only) ------
_CONV_DELETE = "/conversations/00000000-0000-0000-0000-0000000000aa"


def test_delete_conversation_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    assert client.delete(_CONV_DELETE).status_code == 401


def test_cell_leader_forbidden_on_delete_conversation(app) -> None:
    client = _client(app, roles=["lider_celula"])
    assert client.delete(_CONV_DELETE, headers=_AUTH).status_code == 403


def test_pastor_forbidden_on_delete_conversation(app) -> None:
    # Exclusão é admin-only mesmo para papéis com acesso ao inbox (pastor).
    client = _client(app, roles=["pastor"])
    assert client.delete(_CONV_DELETE, headers=_AUTH).status_code == 403


class _DelResult:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def all(self):
        # require_screen("inbox") consulta role_permissions; matriz vazia → cai
        # nos defaults (pastor/operador/lider_g12 têm inbox; lider_celula não).
        return []


class DeleteConvSession:
    """Routes auth (AppUser/UserRole) + the conversation/messages lookups."""

    def __init__(self, *, app_user, roles, conv, media=None) -> None:
        self.app_user = app_user
        self.roles = roles
        self.conv = conv
        self.media = media or []
        self.deleted: list = []
        self.committed = False

    def execute(self, statement, params=None) -> _DelResult:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _DelResult(scalar=self.app_user)
        if ent is Conversation:
            return _DelResult(scalar=self.conv)
        if ent is Message:
            return _DelResult(scalars=self.media)
        return _DelResult(scalars=self.roles)

    def delete(self, obj) -> None:
        self.deleted.append(obj)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


def _del_client(app, session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def test_delete_conversation_success(app) -> None:
    conv = SimpleNamespace(id="00000000-0000-0000-0000-0000000000aa")
    session = DeleteConvSession(
        app_user=make_app_user(), roles=["admin"], conv=conv, media=[]
    )
    client = _del_client(app, session)
    resp = client.delete(_CONV_DELETE, headers=_AUTH)
    assert resp.status_code == 204
    assert session.deleted == [conv]
    assert session.committed is True


def test_delete_conversation_not_found(app) -> None:
    session = DeleteConvSession(app_user=make_app_user(), roles=["admin"], conv=None)
    client = _del_client(app, session)
    assert client.delete(_CONV_DELETE, headers=_AUTH).status_code == 404


# ---- marcar como lida (US-13) ---------------------------------------------
_CONV_READ = "/conversations/00000000-0000-0000-0000-0000000000aa/read"


def test_mark_read_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    assert client.post(_CONV_READ).status_code == 401


def test_cell_leader_forbidden_on_mark_read(app) -> None:
    client = _client(app, roles=["lider_celula"])
    assert client.post(_CONV_READ, headers=_AUTH).status_code == 403


def test_mark_read_zeroes_unread(app) -> None:
    conv = SimpleNamespace(id="00000000-0000-0000-0000-0000000000aa", nao_lidas=5)
    session = DeleteConvSession(app_user=make_app_user(), roles=["pastor"], conv=conv)
    client = _del_client(app, session)
    resp = client.post(_CONV_READ, headers=_AUTH)
    assert resp.status_code == 204
    assert conv.nao_lidas == 0
    assert session.committed is True


# ---- transferir conversa (reatribuir o atendimento) -----------------------
_CONV_TRANSFER = "/conversations/00000000-0000-0000-0000-0000000000aa/transfer"
_TARGET_ID = "00000000-0000-0000-0000-0000000000c9"
_SELF_ID = "00000000-0000-0000-0000-0000000000a1"  # = make_app_user().id


class TransferSession:
    """Routes auth + transfer lookups, distinguishing caller vs target by order.

    `get_current_user` faz a 1ª busca de AppUser/UserRole (o chamador); o endpoint
    de transferência faz a 2ª (o destino). Roteamos por ordem de chamada.
    """

    def __init__(self, *, app_user, roles, conv, target, target_roles) -> None:
        self.app_user = app_user
        self.roles = roles
        self.conv = conv
        self.target = target
        self.target_roles = target_roles
        self._appuser = 0
        self._userrole = 0
        self.committed = False

    def execute(self, statement, params=None) -> _DelResult:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            self._appuser += 1
            return _DelResult(
                scalar=self.app_user if self._appuser == 1 else self.target
            )
        if ent is Conversation:
            return _DelResult(scalar=self.conv)
        if ent is UserRole:
            self._userrole += 1
            return _DelResult(
                scalars=self.roles if self._userrole == 1 else self.target_roles
            )
        return _DelResult()

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


def _held_conv(estado="humano", holder=_SELF_ID):
    return SimpleNamespace(
        id="00000000-0000-0000-0000-0000000000aa",
        estado=estado,
        assumido_por=holder,
        assumido_em=None,
        espera_desde=None,
    )


def test_transfer_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    assert client.post(_CONV_TRANSFER, json={"toUserId": _TARGET_ID}).status_code == 401


def test_cell_leader_forbidden_on_transfer(app) -> None:
    client = _client(app, roles=["lider_celula"])
    resp = client.post(_CONV_TRANSFER, json={"toUserId": _TARGET_ID}, headers=_AUTH)
    assert resp.status_code == 403


def test_transfer_by_holder_succeeds(app) -> None:
    target = SimpleNamespace(id=_TARGET_ID, nome="Pastora Ana", chat_nome=None)
    session = TransferSession(
        app_user=make_app_user(),
        roles=["pastor"],
        conv=_held_conv(),
        target=target,
        target_roles=["lider_g12"],
    )
    client = _del_client(app, session)
    resp = client.post(_CONV_TRANSFER, json={"toUserId": _TARGET_ID}, headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["assumidoPor"] == _TARGET_ID
    assert body["assumidoPorNome"] == "Pastora Ana"
    assert body["estado"] == "humano"
    assert session.committed is True


def test_transfer_non_admin_not_holder_conflict(app) -> None:
    session = TransferSession(
        app_user=make_app_user(),
        roles=["pastor"],
        conv=_held_conv(estado="ia", holder=None),
        target=None,
        target_roles=[],
    )
    client = _del_client(app, session)
    resp = client.post(_CONV_TRANSFER, json={"toUserId": _TARGET_ID}, headers=_AUTH)
    assert resp.status_code == 409


def test_transfer_rejects_target_without_inbox_access(app) -> None:
    target = SimpleNamespace(id=_TARGET_ID, nome="Membro", chat_nome=None)
    session = TransferSession(
        app_user=make_app_user(),
        roles=["admin"],  # admin pula a trava de detentor
        conv=_held_conv(estado="ia", holder=None),
        target=target,
        target_roles=["lider_celula"],  # sem acesso ao inbox
    )
    client = _del_client(app, session)
    resp = client.post(_CONV_TRANSFER, json={"toUserId": _TARGET_ID}, headers=_AUTH)
    assert resp.status_code == 422


def test_transfer_target_not_found(app) -> None:
    session = TransferSession(
        app_user=make_app_user(),
        roles=["admin"],
        conv=_held_conv(estado="ia", holder=None),
        target=None,
        target_roles=[],
    )
    client = _del_client(app, session)
    resp = client.post(_CONV_TRANSFER, json={"toUserId": _TARGET_ID}, headers=_AUTH)
    assert resp.status_code == 404


def test_transfer_rejects_invalid_user_id(app) -> None:
    client = _client(app, roles=["admin"])
    resp = client.post(_CONV_TRANSFER, json={"toUserId": "not-a-uuid"}, headers=_AUTH)
    assert resp.status_code == 422


# ---- foto de perfil do contato (Etapa 4) ----------------------------------
_CONV_PHOTO = "/conversations/00000000-0000-0000-0000-0000000000aa/photo"


class _FakeEvo:
    def __init__(self, url) -> None:
        self._url = url

    def fetch_profile_picture_url(self, instance, telefone):
        return self._url


class PhotoSession:
    def __init__(self, *, app_user, roles, conv, conn) -> None:
        self.app_user = app_user
        self.roles = roles
        self.conv = conv
        self.conn = conn

    def execute(self, statement, params=None) -> _DelResult:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _DelResult(scalar=self.app_user)
        if ent is Conversation:
            return _DelResult(scalar=self.conv)
        if ent is WhatsappConnection:
            return _DelResult(scalar=self.conn)
        return _DelResult(scalars=self.roles)

    def close(self) -> None:  # pragma: no cover
        pass


def test_photo_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    assert client.get(_CONV_PHOTO).status_code == 401


def test_cell_leader_forbidden_on_photo(app) -> None:
    client = _client(app, roles=["lider_celula"])
    assert client.get(_CONV_PHOTO, headers=_AUTH).status_code == 403


def test_photo_returns_url(app) -> None:
    conv = SimpleNamespace(id="00000000-0000-0000-0000-0000000000aa", telefone="5599")
    conn = SimpleNamespace(instance="igreja-x")
    session = PhotoSession(
        app_user=make_app_user(), roles=["pastor"], conv=conv, conn=conn
    )
    client = _del_client(app, session)
    app.dependency_overrides[get_evolution_client] = lambda: _FakeEvo("https://cdn/x.jpg")
    resp = client.get(_CONV_PHOTO, headers=_AUTH)
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://cdn/x.jpg"


def test_photo_none_without_connection(app) -> None:
    conv = SimpleNamespace(id="00000000-0000-0000-0000-0000000000aa", telefone="5599")
    session = PhotoSession(
        app_user=make_app_user(), roles=["pastor"], conv=conv, conn=None
    )
    client = _del_client(app, session)
    app.dependency_overrides[get_evolution_client] = lambda: _FakeEvo("https://cdn/x.jpg")
    resp = client.get(_CONV_PHOTO, headers=_AUTH)
    assert resp.status_code == 200
    assert resp.json()["url"] is None


# ---- GET /connection captura o número pareado da Evolution (#3) ------------
class _ConnSession:
    """Routes auth (AppUser/UserRole) + the WhatsappConnection lookup."""

    def __init__(self, *, app_user, roles, conn) -> None:
        self.app_user = app_user
        self.roles = roles
        self.conn = conn
        self.committed = False

    def execute(self, statement, params=None) -> _DelResult:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _DelResult(scalar=self.app_user)
        if ent is WhatsappConnection:
            return _DelResult(scalar=self.conn)
        return _DelResult(scalars=self.roles)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


class _FakeEvoStatus:
    def __init__(self, result) -> None:
        self.result = result
        self.asked: list[str] = []

    def fetch_status(self, instance):
        self.asked.append(instance)
        return self.result


def test_get_connection_captures_paired_number(app) -> None:
    # Após o pareamento, o número vem da Evolution (fetchInstances), é persistido
    # e exibido — connect/reconnect nunca trazem o número na fase do QR.
    from app.services.evolution import ConnectionResult

    conn = SimpleNamespace(
        instance="igreja-x", numero=None, status="reconectando", ultima_sync=None
    )
    session = _ConnSession(app_user=make_app_user(), roles=["admin"], conn=conn)
    evo = _FakeEvoStatus(ConnectionResult(status="online", numero="5511999999999"))
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    app.dependency_overrides[get_evolution_client] = lambda: evo
    client = TestClient(app)

    resp = client.get("/whatsapp/connection", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["numero"] == "5511999999999"
    assert body["status"] == "online"
    assert conn.numero == "5511999999999"  # persistido no banco
    assert conn.status == "online"
    assert session.committed is True
    assert evo.asked == ["igreja-x"]


def test_get_connection_falls_back_when_evolution_down(app) -> None:
    # Evolution indisponível não pode quebrar a tela: cai nos valores do banco.
    from app.services.evolution import EvolutionError

    conn = SimpleNamespace(
        instance="igreja-x", numero="5500", status="online", ultima_sync=None
    )
    session = _ConnSession(app_user=make_app_user(), roles=["admin"], conn=conn)

    class _BoomEvo:
        def fetch_status(self, instance):
            raise EvolutionError("down")

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    app.dependency_overrides[get_evolution_client] = lambda: _BoomEvo()
    client = TestClient(app)

    resp = client.get("/whatsapp/connection", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["numero"] == "5500"
    assert body["status"] == "online"
    assert session.committed is False  # nada mudou → sem commit


def test_numero_from_jid_strips_suffixes() -> None:
    from app.services.evolution import numero_from_jid

    assert numero_from_jid("5511999999999@s.whatsapp.net") == "5511999999999"
    assert numero_from_jid("5511999999999:12@s.whatsapp.net") == "5511999999999"
    assert numero_from_jid(None) is None
    assert numero_from_jid("") is None
    assert numero_from_jid("@s.whatsapp.net") is None


def test_fetch_instances_parsing_both_shapes() -> None:
    from app.services.evolution import EvolutionClient

    flat = {
        "name": "igreja-x",
        "connectionStatus": "open",
        "ownerJid": "5599@s.whatsapp.net",
    }
    nested = {
        "instance": {
            "instanceName": "igreja-x",
            "status": "open",
            "owner": "5588@s.whatsapp.net",
        }
    }
    assert EvolutionClient._state_and_owner(flat) == ("open", "5599@s.whatsapp.net")
    assert EvolutionClient._state_and_owner(nested) == ("open", "5588@s.whatsapp.net")

    body = [{"name": "other", "connectionStatus": "close"}, flat]
    assert EvolutionClient._select_instance(body, "igreja-x")["name"] == "igreja-x"
    # sem match → cai no primeiro dict (servidor de instância única)
    assert EvolutionClient._select_instance([nested], "zzz") == nested
