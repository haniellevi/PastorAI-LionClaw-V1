"""Tests for the SLA engine: breach detection + WhatsApp charge/escalation (O5).

Uses in-memory fakes (no DB, no Evolution network). Verifies that a blown
deadline charges the leader, an unanswered charge escalates to coordination and
opens a coordination work item, and dispatch is idempotent.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from app.db.models import (
    AgentConversationLog,
    AppUser,
    Consolidacao,
    Pessoa,
    UserRole,
    WhatsappConnection,
    WorkQueueItem,
)
from app.domain.sla import SlaStatus
from app.services.sla_engine import SlaEngine, scan_breaches

_IGREJA = uuid.UUID("00000000-0000-0000-0000-000000000001")
_T0 = dt.datetime(2026, 6, 13, 12, 0, tzinfo=dt.timezone.utc)


def _hours(n: float) -> dt.timedelta:
    return dt.timedelta(hours=n)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
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

    def all(self) -> list:
        return list(self._items)


class FakeSlaSession:
    """Routes execute() by entity; session.get() by (model, id)."""

    def __init__(
        self,
        *,
        work_items=None,
        consolidacoes=None,
        connection=None,
        coordination_user_ids=None,
        users=None,
        pessoas=None,
        existing_dispatch=False,
    ) -> None:
        self.work_items = work_items or []
        self.consolidacoes = consolidacoes or []
        self.connection = connection
        self.coordination_user_ids = coordination_user_ids or []
        self.users = users or {}
        self.pessoas = pessoas or {}
        self.existing_dispatch = existing_dispatch
        self.added: list = []
        self.committed = False
        self.rolled_back = False

    def execute(self, statement, params=None) -> _FakeResult:
        descriptions = getattr(statement, "column_descriptions", None)
        if not descriptions:
            return _FakeResult([])
        entity = descriptions[0].get("entity")
        if entity is WorkQueueItem:
            return _FakeResult(self.work_items)
        if entity is Consolidacao:
            return _FakeResult(self.consolidacoes)
        if entity is WhatsappConnection:
            return _FakeResult([self.connection] if self.connection else [])
        if entity is AgentConversationLog:
            return _FakeResult([object()] if self.existing_dispatch else [])
        if entity is UserRole:
            return _FakeResult(self.coordination_user_ids)
        return _FakeResult([])

    def get(self, model, ident):
        if model is AppUser:
            return self.users.get(ident)
        if model is Pessoa:
            return self.pessoas.get(ident)
        return None

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class FakeEvolution:
    """Records send_text calls instead of hitting the network."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send_text(self, instance: str, telefone: str, texto: str) -> bool:
        self.sent.append((instance, telefone, texto))
        return True


def _work_item(*, tipo: str, prazo: dt.datetime, status: str = "aberto", **kw):
    item = WorkQueueItem(
        igreja_id=_IGREJA,
        tipo=tipo,
        titulo=f"{tipo} pendente",
        status=status,
        prazo=prazo,
        **kw,
    )
    item.id = uuid.uuid4()
    return item


# ---------------------------------------------------------------------------
# scan_breaches
# ---------------------------------------------------------------------------
def test_scan_detects_overdue_report_as_cobranca() -> None:
    item = _work_item(tipo="relatorio", prazo=_T0)  # due exactly at now
    session = FakeSlaSession(work_items=[item])
    breaches = scan_breaches(session, _IGREJA, now=_T0 + _hours(1))
    assert len(breaches) == 1
    assert breaches[0].kind == "relatorio"
    assert breaches[0].status is SlaStatus.COBRANCA


def test_scan_ignores_resolved_items() -> None:
    item = _work_item(tipo="relatorio", prazo=_T0, status="resolvido")
    session = FakeSlaSession(work_items=[item])
    assert scan_breaches(session, _IGREJA, now=_T0 + _hours(10)) == []


def test_scan_ignores_non_timed_tipo() -> None:
    item = _work_item(tipo="atendimento", prazo=_T0)
    session = FakeSlaSession(work_items=[item])
    assert scan_breaches(session, _IGREJA, now=_T0 + _hours(10)) == []


def test_scan_detects_consolidacao_connection_deadline() -> None:
    cons = Consolidacao(
        igreja_id=_IGREJA,
        pessoa_id=uuid.uuid4(),
        concluida=False,
        prazo_conexao=_T0,
    )
    cons.id = uuid.uuid4()
    session = FakeSlaSession(consolidacoes=[cons])
    breaches = scan_breaches(session, _IGREJA, now=_T0 + _hours(13))
    assert len(breaches) == 1
    assert breaches[0].kind == "conexao"


# ---------------------------------------------------------------------------
# dispatch (charge / escalation / idempotency)
# ---------------------------------------------------------------------------
def test_charge_sends_whatsapp_to_responsible_leader() -> None:
    leader_user = uuid.uuid4()
    leader_pessoa = uuid.uuid4()
    item = _work_item(tipo="relatorio", prazo=_T0, responsavel_id=leader_user)
    session = FakeSlaSession(
        work_items=[item],
        connection=SimpleNamespace(instance="igreja-1"),
        users={leader_user: AppUser(
            igreja_id=_IGREJA, nome="Líder", email="l@x.com", pessoa_id=leader_pessoa
        )},
        pessoas={leader_pessoa: Pessoa(
            igreja_id=_IGREJA, nome="Líder", telefone="+5511999990001"
        )},
    )
    evo = FakeEvolution()
    engine = SlaEngine(evolution=evo)
    handled = engine.run_for_igreja(session, _IGREJA, now=_T0 + _hours(1))

    assert len(handled) == 1
    assert len(evo.sent) == 1
    assert evo.sent[0][1] == "+5511999990001"
    assert session.committed is True
    # A dispatch audit log was written.
    assert any(isinstance(o, AgentConversationLog) for o in session.added)


def test_escalation_notifies_coordination_and_opens_work_item() -> None:
    coord_user = uuid.uuid4()
    coord_pessoa = uuid.uuid4()
    item = _work_item(tipo="relatorio", prazo=_T0)  # no responsavel
    session = FakeSlaSession(
        work_items=[item],
        connection=SimpleNamespace(instance="igreja-1"),
        coordination_user_ids=[coord_user],
        users={coord_user: AppUser(
            igreja_id=_IGREJA, nome="Pastor", email="p@x.com", pessoa_id=coord_pessoa
        )},
        pessoas={coord_pessoa: Pessoa(
            igreja_id=_IGREJA, nome="Pastor", telefone="+5511999990009"
        )},
    )
    evo = FakeEvolution()
    engine = SlaEngine(evolution=evo)
    # 3h past the 2h deadline -> beyond the 2h escalation grace.
    handled = engine.run_for_igreja(session, _IGREJA, now=_T0 + _hours(3))

    assert handled and handled[0].status is SlaStatus.ESCALONAMENTO
    assert evo.sent and evo.sent[0][1] == "+5511999990009"
    # A coordination work item was opened.
    assert any(
        isinstance(o, WorkQueueItem) and o.tipo == "atendimento"
        for o in session.added
    )


def test_dispatch_is_idempotent_when_already_logged() -> None:
    item = _work_item(tipo="relatorio", prazo=_T0)
    session = FakeSlaSession(
        work_items=[item],
        connection=SimpleNamespace(instance="igreja-1"),
        existing_dispatch=True,  # a prior dispatch is already recorded
    )
    evo = FakeEvolution()
    engine = SlaEngine(evolution=evo)
    handled = engine.run_for_igreja(session, _IGREJA, now=_T0 + _hours(1))

    assert handled == []
    assert evo.sent == []


def test_no_instance_logs_without_sending() -> None:
    item = _work_item(tipo="relatorio", prazo=_T0)
    session = FakeSlaSession(work_items=[item], connection=None)
    evo = FakeEvolution()
    engine = SlaEngine(evolution=evo)
    handled = engine.run_for_igreja(session, _IGREJA, now=_T0 + _hours(1))

    # Detected and logged (so it is not re-detected forever), but nothing sent.
    assert len(handled) == 1
    assert evo.sent == []
    assert any(isinstance(o, AgentConversationLog) for o in session.added)
