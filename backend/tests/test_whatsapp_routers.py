"""Edge tests for whatsapp/conversations routers: auth, RBAC and webhook."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import (
    AppUser,
    Celula,
    CelulaMembro,
    Conversation,
    Message,
    Pessoa,
    UserRole,
    WhatsappConnection,
)
from app.db.session import get_db
from app.routers import whatsapp as whatsapp_router
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
def test_member_forbidden_on_conversations(app) -> None:
    # Papel sem inbox (membro). lider_celula passou a ter acesso restrito (#5).
    client = _client(app, roles=["membro"])
    assert client.get("/conversations", headers=_AUTH).status_code == 403


def test_member_forbidden_on_handoff(app) -> None:
    client = _client(app, roles=["membro"])
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


def test_member_forbidden_on_messages_history(app) -> None:
    client = _client(app, roles=["membro"])
    assert client.get(_CONV_MSGS, headers=_AUTH).status_code == 403


def test_send_message_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    assert client.post(_CONV_MSGS, json={"texto": "oi"}).status_code == 401


def test_member_forbidden_on_send_message(app) -> None:
    client = _client(app, roles=["membro"])
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


def test_member_forbidden_on_send_media(app) -> None:
    client = _client(app, roles=["membro"])
    resp = client.post(
        _CONV_MEDIA, json={"mime": "image/png", "base64": "Zm9v"}, headers=_AUTH
    )
    assert resp.status_code == 403


def test_send_media_rejects_missing_fields(app) -> None:
    client = _client(app, roles=["admin"])
    resp = client.post(_CONV_MEDIA, json={"mime": "image/png"}, headers=_AUTH)
    assert resp.status_code == 422


def test_send_media_guard_blocks_before_storage_upload(monkeypatch) -> None:
    """Gate fechado não pode deixar objeto órfão no Supabase Storage."""
    from app.routers import conversations

    app_user_id = uuid.uuid4()
    igreja_id = uuid.uuid4()
    conv = SimpleNamespace(
        id=uuid.uuid4(),
        estado="humano",
        assumido_por=app_user_id,
        telefone="5511999990000",
    )
    connection = SimpleNamespace(status="online", instance="igreja-1")

    class _Result:
        def scalar_one_or_none(self):
            return connection

    class _DB:
        def execute(self, _query):
            return _Result()

    class _ForbiddenStorage:
        def upload(self, *args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("Storage não deve ser tocado com gate fechado")

    class _ForbiddenEvolution:
        def send_media(self, *args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("Evolution não deve ser tocada com gate fechado")

    monkeypatch.setattr(
        conversations, "_get_conversation_for_update", lambda *_args: conv
    )
    monkeypatch.setattr(
        conversations, "_authorize_conversation_view", lambda *_args: None
    )
    monkeypatch.setattr(conversations, "external_sends_allowed", lambda: False)

    with pytest.raises(HTTPException) as exc_info:
        conversations.send_media_message(
            str(conv.id),
            conversations.SendMediaRequest(mime="image/png", base64="Zm9v"),
            db=_DB(),
            current_user=SimpleNamespace(
                igreja_id=str(igreja_id),
                app_user_id=str(app_user_id),
                chat_nome=None,
                nome="Pastor Teste",
            ),
            evolution=_ForbiddenEvolution(),
            storage=_ForbiddenStorage(),
        )

    assert exc_info.value.status_code == 503


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
def test_get_webhook_queue_reuses_one_instance_per_process(monkeypatch) -> None:
    sentinel = object()
    builds = 0

    def build_queue():
        nonlocal builds
        builds += 1
        return sentinel

    get_webhook_queue.cache_clear()
    monkeypatch.setattr(whatsapp_router, "WebhookQueue", build_queue)
    try:
        assert get_webhook_queue() is sentinel
        assert get_webhook_queue() is sentinel
        assert builds == 1
    finally:
        get_webhook_queue.cache_clear()


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


def test_webhook_offloads_sync_redis_enqueue(app, monkeypatch) -> None:
    secret = "topsecret"
    monkeypatch.setattr(get_settings(), "evolution_webhook_secret", secret)
    queue = _FakeQueue()
    app.dependency_overrides[get_webhook_queue] = lambda: queue
    calls: list[tuple] = []

    async def fake_run_in_threadpool(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return func(*args, **kwargs)

    monkeypatch.setattr(
        whatsapp_router,
        "run_in_threadpool",
        fake_run_in_threadpool,
    )
    client = TestClient(app)
    body = json.dumps({"event": "messages.upsert", "instance": "igreja-1"}).encode()

    resp = client.post(
        f"/whatsapp/webhook?token={secret}",
        content=body,
    )

    assert resp.status_code == 202
    assert len(calls) == 1
    assert calls[0][1] == (json.loads(body),)
    assert queue.enqueued == [json.loads(body)]


def test_webhook_rejects_declared_oversize_before_read(app, monkeypatch) -> None:
    monkeypatch.setattr(whatsapp_router, "MAX_WEBHOOK_BODY_BYTES", 16)
    client = _webhook_client(app)

    resp = client.post(
        "/whatsapp/webhook",
        content=b"",
        headers={"content-length": "17"},
    )

    assert resp.status_code == 413


def test_webhook_rejects_actual_oversize_after_read(app, monkeypatch) -> None:
    monkeypatch.setattr(whatsapp_router, "MAX_WEBHOOK_BODY_BYTES", 16)
    client = _webhook_client(app)

    resp = client.post(
        "/whatsapp/webhook",
        content=b"x" * 17,
        # Simulates a missing/dishonest upstream framing size: the actual-byte
        # check must still reject the buffered body.
        headers={"content-length": "1"},
    )

    assert resp.status_code == 413


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
        # nos defaults (pastor/operador/lider_g12/lider_consol/lider_celula têm
        # inbox; membro não).
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


def test_member_forbidden_on_mark_read(app) -> None:
    client = _client(app, roles=["membro"])
    assert client.post(_CONV_READ, headers=_AUTH).status_code == 403


def test_mark_read_zeroes_unread(app) -> None:
    conv = SimpleNamespace(id="00000000-0000-0000-0000-0000000000aa", nao_lidas=5)
    session = DeleteConvSession(app_user=make_app_user(), roles=["pastor"], conv=conv)
    client = _del_client(app, session)
    resp = client.post(_CONV_READ, headers=_AUTH)
    assert resp.status_code == 204
    assert conv.nao_lidas == 0
    assert session.committed is True


def test_responsavel_cannot_mark_read_others_conversation(app) -> None:
    # #5: responsável (visão restrita) recebe 404 numa conversa que não é dele.
    conv = SimpleNamespace(
        id="00000000-0000-0000-0000-0000000000aa",
        nao_lidas=5,
        assumido_por="00000000-0000-0000-0000-0000000000c9",  # outro usuário
    )
    session = DeleteConvSession(app_user=make_app_user(), roles=["lider_g12"], conv=conv)
    client = _del_client(app, session)
    resp = client.post(_CONV_READ, headers=_AUTH)
    assert resp.status_code == 404
    assert conv.nao_lidas == 5  # não zerou


# ---- transferir conversa (reatribuir o atendimento) -----------------------
_CONV_TRANSFER = "/conversations/00000000-0000-0000-0000-0000000000aa/transfer"
_TARGET_ID = "00000000-0000-0000-0000-0000000000c9"
_SELF_ID = "00000000-0000-0000-0000-0000000000a1"  # = make_app_user().id
_IGREJA_ID = "00000000-0000-0000-0000-000000000001"
_OTHER_IGREJA_ID = "00000000-0000-0000-0000-000000000002"


class TransferSession:
    """Routes auth + transfer lookups, distinguishing caller vs target by order.

    `get_current_user` faz a 1ª busca de AppUser/UserRole (o chamador); o endpoint
    de transferência faz a 2ª (o destino). Roteamos por ordem de chamada.
    """

    def __init__(
        self,
        *,
        app_user,
        roles,
        conv,
        target,
        target_roles,
        target_roles_igreja_id=_IGREJA_ID,
    ) -> None:
        self.app_user = app_user
        self.roles = roles
        self.conv = conv
        self.target = target
        self.target_roles = target_roles
        self.target_roles_igreja_id = target_roles_igreja_id
        self._appuser = 0
        self._userrole = 0
        self.committed = False
        self.flushes = 0
        self.target_statements: list = []
        self.target_role_statements: list = []

    def execute(self, statement, params=None) -> _DelResult:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            self._appuser += 1
            if self._appuser == 1:
                return _DelResult(scalar=self.app_user)

            self.target_statements.append(statement)
            target = self.target
            if target is None:
                return _DelResult()
            where_clause = getattr(statement, "whereclause", None)
            where = str(
                where_clause.compile(compile_kwargs={"literal_binds": True})
            ).lower()
            target_igreja = str(getattr(target, "igreja_id", _IGREJA_ID))
            target_status = getattr(target, "status", "ativo")
            if "app_users.igreja_id" in where and target_igreja != _IGREJA_ID:
                return _DelResult()
            if (
                "app_users.status" in where
                and target_status not in {None, "ativo"}
            ):
                return _DelResult()
            return _DelResult(scalar=target)
        if ent is Conversation:
            return _DelResult(scalar=self.conv)
        if ent is UserRole:
            self._userrole += 1
            if self._userrole == 1:
                return _DelResult(scalars=self.roles)
            self.target_role_statements.append(statement)
            where_clause = getattr(statement, "whereclause", None)
            where = str(
                where_clause.compile(compile_kwargs={"literal_binds": True})
            ).lower()
            if (
                "user_roles.igreja_id" in where
                and self.target_roles_igreja_id != _IGREJA_ID
            ):
                return _DelResult(scalars=[])
            return _DelResult(scalars=self.target_roles)
        return _DelResult()

    def flush(self) -> None:
        self.flushes += 1

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


def _transfer_target(
    *,
    igreja_id=_IGREJA_ID,
    status="ativo",
    nome="Pastora Ana",
    chat_nome=None,
):
    return SimpleNamespace(
        id=_TARGET_ID,
        igreja_id=uuid.UUID(igreja_id),
        status=status,
        nome=nome,
        chat_nome=chat_nome,
    )


def test_transfer_requires_auth(app) -> None:
    client = _client(app, roles=["admin"])
    assert client.post(_CONV_TRANSFER, json={"toUserId": _TARGET_ID}).status_code == 401


def test_member_forbidden_on_transfer(app) -> None:
    client = _client(app, roles=["membro"])
    resp = client.post(_CONV_TRANSFER, json={"toUserId": _TARGET_ID}, headers=_AUTH)
    assert resp.status_code == 403


def test_transfer_by_holder_succeeds(app) -> None:
    target = _transfer_target()
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
    assert session.flushes == 1
    target_where = str(
        session.target_statements[0].whereclause.compile(
            compile_kwargs={"literal_binds": True}
        )
    ).lower()
    assert "app_users.igreja_id" in target_where
    assert "app_users.status is null" in target_where
    assert "app_users.status = 'ativo'" in target_where
    role_where = str(
        session.target_role_statements[0].whereclause.compile(
            compile_kwargs={"literal_binds": True}
        )
    ).lower()
    assert "user_roles.user_id" in role_where
    assert "user_roles.igreja_id" in role_where


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
    target = _transfer_target(nome="Membro")
    session = TransferSession(
        app_user=make_app_user(),
        roles=["admin"],  # admin pula a trava de detentor
        conv=_held_conv(estado="ia", holder=None),
        target=target,
        target_roles=["membro"],  # sem acesso ao inbox
    )
    client = _del_client(app, session)
    resp = client.post(_CONV_TRANSFER, json={"toUserId": _TARGET_ID}, headers=_AUTH)
    assert resp.status_code == 422
    assert session.flushes == 0
    assert session.committed is False


def test_transfer_to_cell_leader_succeeds(app) -> None:
    # #5: líder de célula passou a ser destino válido (responsável, visão restrita).
    target = _transfer_target(nome="Líder Célula")
    session = TransferSession(
        app_user=make_app_user(),
        roles=["admin"],
        conv=_held_conv(estado="ia", holder=None),
        target=target,
        target_roles=["lider_celula"],
    )
    client = _del_client(app, session)
    resp = client.post(_CONV_TRANSFER, json={"toUserId": _TARGET_ID}, headers=_AUTH)
    assert resp.status_code == 200
    assert resp.json()["assumidoPor"] == _TARGET_ID


@pytest.mark.parametrize("caller_role", ["lider_celula", "operador"])
def test_restricted_holder_can_transfer_to_eligible_target(app, caller_role) -> None:
    session = TransferSession(
        app_user=make_app_user(),
        roles=[caller_role],
        conv=_held_conv(),
        target=_transfer_target(),
        target_roles=["pastor"],
    )

    resp = _del_client(app, session).post(
        _CONV_TRANSFER,
        json={"toUserId": _TARGET_ID},
        headers=_AUTH,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["assumidoPor"] == _TARGET_ID


def test_responsavel_cannot_transfer_others_conversation(app) -> None:
    # #5: responsável (visão restrita) recebe 404 ao mexer numa conversa alheia.
    session = TransferSession(
        app_user=make_app_user(),
        roles=["lider_g12"],
        conv=_held_conv(estado="humano", holder=_TARGET_ID),  # de outra pessoa
        target=None,
        target_roles=[],
    )
    client = _del_client(app, session)
    resp = client.post(_CONV_TRANSFER, json={"toUserId": _TARGET_ID}, headers=_AUTH)
    assert resp.status_code == 404


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


@pytest.mark.parametrize(
    "target",
    [
        _transfer_target(igreja_id=_OTHER_IGREJA_ID),
        _transfer_target(status="revogado"),
        _transfer_target(status="convidado"),
    ],
    ids=["cross-tenant", "revoked", "invited"],
)
def test_transfer_rejects_inactive_or_cross_tenant_target_without_mutation(
    app, target
) -> None:
    conv = _held_conv(estado="ia", holder=None)
    session = TransferSession(
        app_user=make_app_user(),
        roles=["admin"],
        conv=conv,
        target=target,
        target_roles=["pastor"],
    )

    resp = _del_client(app, session).post(
        _CONV_TRANSFER,
        json={"toUserId": _TARGET_ID},
        headers=_AUTH,
    )

    assert resp.status_code == 404, resp.text
    assert conv.estado == "ia"
    assert conv.assumido_por is None
    assert session.target_role_statements == []
    assert session.flushes == 0
    assert session.committed is False


def test_transfer_rejects_capability_from_role_row_of_other_tenant(app) -> None:
    conv = _held_conv(estado="ia", holder=None)
    session = TransferSession(
        app_user=make_app_user(),
        roles=["admin"],
        conv=conv,
        target=_transfer_target(),
        target_roles=["pastor"],
        target_roles_igreja_id=_OTHER_IGREJA_ID,
    )

    resp = _del_client(app, session).post(
        _CONV_TRANSFER,
        json={"toUserId": _TARGET_ID},
        headers=_AUTH,
    )

    assert resp.status_code == 422, resp.text
    assert conv.estado == "ia"
    assert conv.assumido_por is None
    assert session.flushes == 0
    assert session.committed is False


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


def test_member_forbidden_on_photo(app) -> None:
    client = _client(app, roles=["membro"])
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
def _conn_eq_predicates(statement) -> dict[str, str]:
    preds: dict[str, str] = {}
    clause = getattr(statement, "whereclause", None)
    stack = [clause] if clause is not None else []
    while stack:
        node = stack.pop()
        left = getattr(node, "left", None)
        right = getattr(node, "right", None)
        if left is not None and right is not None:
            key = getattr(left, "key", None)
            value = getattr(right, "value", None)
            if key is not None and value is not None:
                preds[key] = str(value)
            continue
        stack.extend(getattr(node, "clauses", []) or [])
    return preds


class _ConnSession:
    """Routes auth (AppUser/UserRole) + the WhatsappConnection lookup.

    Também roteia Pessoa/Celula/CelulaMembro para o guard de conflito ministerial
    da conexão (M7B-W1.2): sem essas rotas, a query de conflito cairia no default
    (roles) e quebraria os testes de POST /connection com número. `pessoas` são
    os candidatos (o service confirma o telefone em Python); `leads`/`membros` são
    conjuntos de pessoa_id com liderança / vínculo ativo.
    """

    def __init__(
        self, *, app_user, roles, conn, pessoas=(), leads=frozenset(), membros=frozenset()
    ) -> None:
        self.app_user = app_user
        self.roles = roles
        self.conn = conn
        self.pessoas = list(pessoas)
        self.leads = {str(p) for p in leads}
        self.membros = {str(p) for p in membros}
        self.committed = False

    def execute(self, statement, params=None) -> _DelResult:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _DelResult(scalar=self.app_user)
        if ent is WhatsappConnection:
            return _DelResult(scalar=self.conn)
        if ent is Pessoa:
            return _DelResult(scalars=self.pessoas)
        if ent is Celula:
            pid = _conn_eq_predicates(statement).get("lider_id")
            return _DelResult(scalar=("celula" if pid in self.leads else None))
        if ent is CelulaMembro:
            pid = _conn_eq_predicates(statement).get("pessoa_id")
            return _DelResult(scalar=("membro" if pid in self.membros else None))
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


class _FakeEvoStatusDisconnect:
    """fetch_status devolve um resultado fixo e disconnect é registrado."""

    def __init__(self, result) -> None:
        self.result = result
        self.disconnected: list[str] = []

    def fetch_status(self, instance):
        return self.result

    def disconnect(self, instance):
        from app.services.evolution import ConnectionResult

        self.disconnected.append(instance)
        return ConnectionResult(status="offline")


def test_get_connection_fails_closed_on_ministerial_conflict(app) -> None:
    # M7B-W1.2 (fluxo QR): o número pareado só é conhecido no GET; se pertence a
    # pastor/líder/membro, FALHA FECHADO — disconnect() é chamado, o número NÃO é
    # persistido, o estado fica offline e o admin recebe 409 acionável.
    from app.services.evolution import ConnectionResult

    conn = SimpleNamespace(
        instance="igreja-x", numero=None, status="reconectando", ultima_sync=None
    )
    pastor = SimpleNamespace(
        id="00000000-0000-0000-0000-0000000000d1",
        igreja_id="00000000-0000-0000-0000-000000000001",
        nome="Pastor Raniel",
        tipo="pastor",
        telefone="+55 (89) 99431-5927",
    )
    session = _ConnSession(
        app_user=make_app_user(), roles=["admin"], conn=conn, pessoas=[pastor]
    )
    evo = _FakeEvoStatusDisconnect(
        ConnectionResult(status="online", numero="558994315927")
    )
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    app.dependency_overrides[get_evolution_client] = lambda: evo
    client = TestClient(app)

    resp = client.get("/whatsapp/connection", headers=_AUTH)
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "whatsapp_conflito_ministerial"
    assert detail["conflitos"][0]["vinculos"] == ["pastor"]
    assert evo.disconnected == ["igreja-x"]  # falhou fechado: desconectou
    assert conn.numero is None  # número conflitante NÃO persistido
    assert conn.status == "offline"  # estado local coerente
    assert session.committed is True


def test_get_connection_no_conflict_keeps_normal_qr_flow(app) -> None:
    # Sem conflito, o QR segue normal: número pareado é persistido, sem disconnect.
    from app.services.evolution import ConnectionResult

    conn = SimpleNamespace(
        instance="igreja-x", numero=None, status="reconectando", ultima_sync=None
    )
    session = _ConnSession(
        app_user=make_app_user(), roles=["admin"], conn=conn, pessoas=[]
    )
    evo = _FakeEvoStatusDisconnect(
        ConnectionResult(status="online", numero="558994315927")
    )
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    app.dependency_overrides[get_evolution_client] = lambda: evo
    client = TestClient(app)

    resp = client.get("/whatsapp/connection", headers=_AUTH)
    assert resp.status_code == 200
    assert conn.numero == "558994315927"  # persistido
    assert evo.disconnected == []  # nada desconectado


class _FakeEvoConnect:
    """Captura os argumentos de connect/reconnect e devolve um resultado fixo."""

    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[tuple] = []

    def connect(self, instance, numero=None):
        self.calls.append(("connect", instance, numero))
        return self.result

    def reconnect(self, instance, numero=None):
        self.calls.append(("reconnect", instance, numero))
        return self.result


def test_post_connection_number_forces_reset_reconnect(app) -> None:
    # Um número explícito é pedido de código: rota SEMPRE por reconnect (reset da
    # sessão), mesmo com action="connect" — senão uma sessão QR já em "connecting"
    # faria o Evolution ignorar o número. O número é higienizado (só dígitos).
    from app.services.evolution import ConnectionResult

    conn = SimpleNamespace(
        instance="igreja-x", numero=None, status="reconectando", ultima_sync=None
    )
    session = _ConnSession(app_user=make_app_user(), roles=["admin"], conn=conn)
    evo = _FakeEvoConnect(ConnectionResult(status="reconectando", pairing_code="ABCD-1234"))
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    app.dependency_overrides[get_evolution_client] = lambda: evo
    client = TestClient(app)

    resp = client.post(
        "/whatsapp/connection",
        json={"action": "connect", "numero": "55-11-99999-8888"},
        headers=_AUTH,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pairingCode"] == "ABCD-1234"
    assert body["status"] == "reconectando"
    # action="connect" + número -> reconnect (reset), nunca connect direto.
    assert evo.calls == [("reconnect", "igreja-x", "5511999998888")]
    assert session.committed is True


def test_post_connection_qr_path_ignores_saved_number(app) -> None:
    # Caminho QR (sem número no payload) não reaproveita o número salvo: "Gerar
    # novo QR" (reconnect sem número) não pode virar pedido de código.
    from app.services.evolution import ConnectionResult

    conn = SimpleNamespace(
        instance="igreja-x", numero="5511999998888", status="offline", ultima_sync=None
    )
    session = _ConnSession(app_user=make_app_user(), roles=["admin"], conn=conn)
    evo = _FakeEvoConnect(ConnectionResult(status="reconectando", qr="QR"))
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    app.dependency_overrides[get_evolution_client] = lambda: evo
    client = TestClient(app)

    resp = client.post(
        "/whatsapp/connection", json={"action": "reconnect"}, headers=_AUTH
    )
    assert resp.status_code == 200
    assert resp.json()["qr"] == "QR"
    # número salvo NÃO é enviado no caminho QR.
    assert evo.calls == [("reconnect", "igreja-x", None)]


def test_post_connection_blocks_ministerial_conflict(app) -> None:
    # M7B-W1.2: conectar um número que já pertence a uma pessoa com vínculo
    # ministerial (aqui, pastor) é 409 acionável — ANTES de qualquer chamada à
    # Evolution e sem mutar o banco. O número casa por telefone normalizado.
    from app.services.evolution import ConnectionResult

    conn = SimpleNamespace(
        instance="igreja-x", numero=None, status="offline", ultima_sync=None
    )
    pastor = SimpleNamespace(
        id="00000000-0000-0000-0000-0000000000d1",
        igreja_id="00000000-0000-0000-0000-000000000001",
        nome="Pastor Raniel",
        tipo="pastor",
        telefone="+55 (89) 99431-5927",
    )
    session = _ConnSession(
        app_user=make_app_user(), roles=["admin"], conn=conn, pessoas=[pastor]
    )
    evo = _FakeEvoConnect(ConnectionResult(status="reconectando", pairing_code="X"))
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    app.dependency_overrides[get_evolution_client] = lambda: evo
    client = TestClient(app)

    resp = client.post(
        "/whatsapp/connection",
        json={"action": "connect", "numero": "558994315927"},
        headers=_AUTH,
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "whatsapp_conflito_ministerial"
    assert detail["conflitos"][0]["vinculos"] == ["pastor"]
    # Evolution NÃO foi chamada; nada persistido.
    assert evo.calls == []
    assert session.committed is False


def test_post_connection_allows_when_no_conflict(app) -> None:
    # Número sem pessoa ministerial correspondente conecta normalmente (guard não
    # atrapalha o caminho feliz).
    from app.services.evolution import ConnectionResult

    conn = SimpleNamespace(
        instance="igreja-x", numero=None, status="offline", ultima_sync=None
    )
    session = _ConnSession(
        app_user=make_app_user(), roles=["admin"], conn=conn, pessoas=[]
    )
    evo = _FakeEvoConnect(ConnectionResult(status="reconectando", pairing_code="ABCD"))
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    app.dependency_overrides[get_evolution_client] = lambda: evo
    client = TestClient(app)

    resp = client.post(
        "/whatsapp/connection",
        json={"action": "connect", "numero": "558994315927"},
        headers=_AUTH,
    )
    assert resp.status_code == 200
    assert resp.json()["pairingCode"] == "ABCD"
    assert evo.calls == [("reconnect", "igreja-x", "558994315927")]


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
