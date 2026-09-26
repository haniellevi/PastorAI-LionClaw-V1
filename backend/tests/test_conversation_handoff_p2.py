"""P2 regression for the durable AI-reply fence on manual handoff."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
import uuid

from app.routers import conversations as conversations_router


def test_manual_handoff_uses_the_durable_agent_reply_fence(monkeypatch) -> None:
    igreja_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    holder_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=conversation_id,
        igreja_id=igreja_id,
        estado="ia",
        assumido_por=None,
        assumido_em=None,
        espera_desde=None,
    )
    calls: list[tuple[object, uuid.UUID, uuid.UUID]] = []

    class Session:
        def flush(self) -> None:
            pass

        def refresh(self, _value: object) -> None:
            pass

        def commit(self) -> None:
            pass

    session = Session()
    monkeypatch.setattr(
        conversations_router,
        "_get_conversation_for_update",
        lambda _db, _conversation_id: conversation,
    )
    monkeypatch.setattr(
        conversations_router,
        "_authorize_conversation_view",
        lambda _conversation, _current_user: None,
    )
    monkeypatch.setattr(
        conversations_router,
        "fence_agent_replies_for_handoff",
        lambda db, *, igreja_id, conversation_id: calls.append(
            (db, igreja_id, conversation_id)
        ),
        raising=False,
    )

    conversations_router.handoff(
        str(conversation_id),
        conversations_router.HandoffRequest(to="human"),
        db=session,  # type: ignore[arg-type]
        current_user=SimpleNamespace(app_user_id=str(holder_id)),
    )

    assert calls == [(session, igreja_id, conversation_id)]


def test_manual_release_clears_waiting_timestamp_without_refencing(monkeypatch) -> None:
    igreja_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=conversation_id,
        igreja_id=igreja_id,
        estado="humano",
        assumido_por=None,
        assumido_em=None,
        espera_desde=dt.datetime(2026, 9, 26, tzinfo=dt.UTC),
    )
    fence_calls: list[tuple[object, uuid.UUID, uuid.UUID]] = []

    class Session:
        def flush(self) -> None:
            pass

        def refresh(self, _value: object) -> None:
            pass

        def commit(self) -> None:
            pass

    session = Session()
    monkeypatch.setattr(
        conversations_router,
        "_get_conversation_for_update",
        lambda _db, _conversation_id: conversation,
    )
    monkeypatch.setattr(
        conversations_router,
        "_authorize_conversation_view",
        lambda _conversation, _current_user: None,
    )
    monkeypatch.setattr(
        conversations_router,
        "fence_agent_replies_for_handoff",
        lambda db, *, igreja_id, conversation_id: fence_calls.append(
            (db, igreja_id, conversation_id)
        ),
        raising=False,
    )

    conversations_router.handoff(
        str(conversation_id),
        conversations_router.HandoffRequest(to="ia"),
        db=session,  # type: ignore[arg-type]
        current_user=SimpleNamespace(app_user_id=str(uuid.uuid4())),
    )

    assert conversation.estado == "ia"
    assert conversation.assumido_por is None
    assert conversation.assumido_em is None
    assert conversation.espera_desde is None
    assert fence_calls == []
