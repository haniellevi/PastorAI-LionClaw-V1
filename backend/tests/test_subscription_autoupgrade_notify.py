"""SEC-4: idempotência do aviso de autoupgrade (`notify_autoupgrade`).

Espelha `test_sla_engine.py` — mesma estratégia de fake session simulando o
índice único parcial `agent_conversation_logs_idem_marker_uidx` sem precisar
de Postgres real (Postgres real coberto à parte em
`test_agent_event_idempotency_index.py`). Nunca envia WhatsApp de verdade —
`FakeEvolution` só registra as chamadas.
"""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError

from app.db.models import (
    AgentConversationLog,
    AppUser,
    Pessoa,
    Subscription,
    UserRole,
    WhatsappConnection,
)
from app.deps import ADMIN_ROLE
from app.services.billing_worker import _autoupgrade_event_name, notify_autoupgrade
from app.services.evolution import EvolutionError

_IGREJA = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_OTHER_IGREJA = uuid.UUID("00000000-0000-0000-0000-0000000000a2")


class _FakeScalars:
    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return list(self._items)


class _FakeResult:
    def __init__(self, items: list) -> None:
        self._items = items

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._items)

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def first(self):
        return self._items[0] if self._items else None


class FakeSubscriptionSession:
    """Mesma mecânica de reserva/rollback de FakeSlaSession, entidades da
    Subscription/autoupgrade."""

    def __init__(
        self,
        *,
        subscription=None,
        connection=None,
        admin_user_ids=None,
        users=None,
        pessoas=None,
        preexisting_markers=None,
    ) -> None:
        self.subscription = subscription
        self.connection = connection
        self.admin_user_ids = admin_user_ids or []
        self.users = users or {}
        self.pessoas = pessoas or {}
        self.added: list = []
        self.deleted: list = []
        self.committed = False
        self.rolled_back = False
        self.reserved_markers: set[tuple] = set(preexisting_markers or ())
        self._pending_markers: list = []
        self._pending_all: list = []
        # Gap-2: log cronológico de toda operação de sessão + envio, usado
        # pra provar que nenhuma query roda entre a reserva do marcador e o
        # send_text (ver test_notify_does_not_query_or_hold_transaction_during_send).
        self.event_log: list[str] = []

    def execute(self, statement, params=None) -> _FakeResult:
        descriptions = getattr(statement, "column_descriptions", None)
        if not descriptions:
            self.event_log.append("execute:raw")
            return _FakeResult([])
        entity = descriptions[0].get("entity")
        self.event_log.append(f"execute:{getattr(entity, '__name__', entity)}")
        if entity is Subscription:
            return _FakeResult([self.subscription] if self.subscription else [])
        if entity is WhatsappConnection:
            return _FakeResult([self.connection] if self.connection else [])
        if entity is AgentConversationLog:
            return _FakeResult([])  # notify_autoupgrade só usa isto pro SELECT-checagem inicial
        if entity is UserRole:
            return _FakeResult(self.admin_user_ids)
        return _FakeResult([])

    def get(self, model, ident):
        self.event_log.append(f"get:{model.__name__}")
        if model is AppUser:
            return self.users.get(ident)
        if model is Pessoa:
            return self.pessoas.get(ident)
        return None

    def add(self, obj) -> None:
        self.event_log.append(f"add:{type(obj).__name__}")
        self.added.append(obj)
        self._pending_all.append(obj)
        if isinstance(obj, AgentConversationLog):
            self._pending_markers.append(obj)

    def flush(self) -> None:
        self.event_log.append("flush")
        for row in self._pending_markers:
            key = (row.igreja_id, row.evento)
            if key in self.reserved_markers:
                raise IntegrityError(
                    "insert", {}, Exception("duplicate key value violates "
                    "unique constraint agent_conversation_logs_idem_marker_uidx")
                )
            self.reserved_markers.add(key)
        self._pending_markers.clear()

    def commit(self) -> None:
        self.event_log.append("commit")
        self.committed = True
        self._pending_all.clear()

    def rollback(self) -> None:
        self.event_log.append("rollback")
        self.rolled_back = True
        for obj in self._pending_all:
            if obj in self.added:
                self.added.remove(obj)
            if isinstance(obj, AgentConversationLog):
                self.reserved_markers.discard((obj.igreja_id, obj.evento))
        self._pending_all.clear()
        self._pending_markers.clear()

    def delete(self, obj) -> None:
        self.event_log.append(f"delete:{type(obj).__name__}")
        self.deleted.append(obj)
        if obj in self.added:
            self.added.remove(obj)
        if isinstance(obj, AgentConversationLog):
            self.reserved_markers.discard((obj.igreja_id, obj.evento))


class FakeEvolution:
    def __init__(self, *, fail: bool = False, event_log: list[str] | None = None) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self._fail = fail
        self._event_log = event_log

    def send_text(self, instance: str, telefone: str, texto: str) -> bool:
        if self._event_log is not None:
            self._event_log.append("send_text")
        if self._fail:
            raise EvolutionError("simulated send failure — no WhatsApp real")
        self.sent.append((instance, telefone, texto))
        return True


def _admin(igreja_id, *, telefone="+5511999990000"):
    admin_user = uuid.uuid4()
    admin_pessoa = uuid.uuid4()
    return {
        "admin_user_ids": [admin_user],
        "users": {admin_user: AppUser(
            igreja_id=igreja_id, nome="Admin", email="a@x.com", pessoa_id=admin_pessoa
        )},
        "pessoas": {admin_pessoa: Pessoa(
            igreja_id=igreja_id, nome="Admin", telefone=telefone
        )},
    }


def test_autoupgrade_event_name_matches_idempotency_marker_pattern() -> None:
    """O marcador tem que bater com o predicado `subscription\\_upgrade:%` do
    índice único parcial (agent_conversation_logs_idem_marker_uidx) — senão o
    INSERT do marcador não fica protegido pela constraint de banco."""
    for plano in ("ate_100", "ate_500", "comunidade", "plano-com-hifen"):
        assert _autoupgrade_event_name(plano).startswith("subscription_upgrade:")
        assert _autoupgrade_event_name(plano) == f"subscription_upgrade:{plano}"


def test_first_call_notifies_and_reserves_marker() -> None:
    admin = _admin(_IGREJA)
    session = FakeSubscriptionSession(
        subscription=Subscription(igreja_id=_IGREJA, plano="comunidade"),
        connection=WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1"),
        **admin,
    )
    evo = FakeEvolution()

    result = notify_autoupgrade(session, _IGREJA, evo)

    assert result == "sent"
    assert len(evo.sent) == 1
    evento = _autoupgrade_event_name("comunidade")
    assert (_IGREJA, evento) in session.reserved_markers


def test_second_call_is_idempotent_no_resend() -> None:
    evento = _autoupgrade_event_name("comunidade")
    admin = _admin(_IGREJA)
    session = FakeSubscriptionSession(
        subscription=Subscription(igreja_id=_IGREJA, plano="comunidade"),
        connection=WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1"),
        preexisting_markers={(_IGREJA, evento)},  # já avisado antes
        **admin,
    )
    evo = FakeEvolution()

    result = notify_autoupgrade(session, _IGREJA, evo)

    assert result == "already"
    assert evo.sent == []


def test_concurrent_reservation_loses_never_sends() -> None:
    """SEC-4: outro processo já reservou o MESMO marcador ANTES da checagem
    barata (SELECT) enxergar — a checagem não vê a corrida, a reserva atômica
    fecha o gap."""
    evento = _autoupgrade_event_name("comunidade")
    admin = _admin(_IGREJA)
    session = FakeSubscriptionSession(
        subscription=Subscription(igreja_id=_IGREJA, plano="comunidade"),
        connection=WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1"),
        preexisting_markers={(_IGREJA, evento)},
        **admin,
    )
    evo = FakeEvolution()

    result = notify_autoupgrade(session, _IGREJA, evo)

    assert result == "already"
    assert evo.sent == []


def test_send_failure_releases_marker_for_retry() -> None:
    """SEC-4 (at-least-once): falha total do envio libera a reserva pra
    próxima chamada tentar de novo — não perde o aviso silenciosamente."""
    admin = _admin(_IGREJA)
    session = FakeSubscriptionSession(
        subscription=Subscription(igreja_id=_IGREJA, plano="comunidade"),
        connection=WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1"),
        **admin,
    )
    evo = FakeEvolution(fail=True)

    result = notify_autoupgrade(session, _IGREJA, evo)

    assert result == "retry"
    assert evo.sent == []
    assert not any(isinstance(o, AgentConversationLog) for o in session.added)
    assert session.reserved_markers == set()


def test_notify_does_not_query_or_hold_transaction_during_send() -> None:
    """Gap-2: nenhum db.execute/db.get roda entre o commit da reserva e o
    send_text — prova que a leitura de conexão/telefones foi movida pra ANTES
    da reserva (senão o autobegin do SQLAlchemy reabriria uma transação que
    ficaria pendurada durante a chamada externa)."""
    admin = _admin(_IGREJA)
    session = FakeSubscriptionSession(
        subscription=Subscription(igreja_id=_IGREJA, plano="comunidade"),
        connection=WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1"),
        **admin,
    )
    evo = FakeEvolution(event_log=session.event_log)

    result = notify_autoupgrade(session, _IGREJA, evo)

    assert result == "sent"
    assert evo.sent  # o teste teria um event_log incompleto se nada tivesse enviado
    reserve_commit_idx = session.event_log.index("commit")  # commit da reserva (1º e único antes do send)
    send_idx = session.event_log.index("send_text")
    assert send_idx > reserve_commit_idx
    between = session.event_log[reserve_commit_idx + 1 : send_idx]
    assert not any(e.startswith(("execute", "get", "add", "flush")) for e in between), (
        f"query/transação entre a reserva e o send_text: {between}"
    )


def test_same_plano_different_igreja_both_notify() -> None:
    """A chave de dedupe é (igreja_id, evento) — o mesmo `plano` (logo o
    mesmo `evento`) em igrejas diferentes não colide."""
    admin_a = _admin(_IGREJA)
    session = FakeSubscriptionSession(
        subscription=Subscription(igreja_id=_IGREJA, plano="comunidade"),
        connection=WhatsappConnection(igreja_id=_IGREJA, instance="igreja-1"),
        **admin_a,
    )
    evo_a = FakeEvolution()
    assert notify_autoupgrade(session, _IGREJA, evo_a) == "sent"

    admin_b = _admin(_OTHER_IGREJA)
    session.subscription = Subscription(igreja_id=_OTHER_IGREJA, plano="comunidade")
    session.connection = WhatsappConnection(igreja_id=_OTHER_IGREJA, instance="igreja-2")
    session.admin_user_ids = admin_b["admin_user_ids"]
    session.users = admin_b["users"]
    session.pessoas = admin_b["pessoas"]
    evo_b = FakeEvolution()
    assert notify_autoupgrade(session, _OTHER_IGREJA, evo_b) == "sent"

    evento = _autoupgrade_event_name("comunidade")
    assert session.reserved_markers == {(_IGREJA, evento), (_OTHER_IGREJA, evento)}
