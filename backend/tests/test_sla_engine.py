"""Tests for the SLA engine: breach detection + WhatsApp charge/escalation (O5).

Uses in-memory fakes (no DB, no Evolution network). Verifies that a blown
deadline charges the leader, an unanswered charge escalates to coordination and
opens a coordination work item, and dispatch is idempotent.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from app.db.models import (
    AgentConversationLog,
    AppUser,
    Consolidacao,
    Pessoa,
    UserRole,
    WhatsappConnection,
    WorkQueueItem,
)
from app.db.tenant_session import TENANT_IGREJA_KEY, TENANT_META_KEY
from app.domain.sla import SlaStatus
from app.services.evolution import EvolutionError
from app.services.sla_engine import (
    SlaBreach,
    SlaEngine,
    _coordination_item_event_name,
    _dispatch_event_name,
    run_all_igrejas,
    scan_breaches,
)

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
        preexisting_markers=None,
    ) -> None:
        self.work_items = work_items or []
        self.consolidacoes = consolidacoes or []
        self.connection = connection
        self.coordination_user_ids = coordination_user_ids or []
        self.users = users or {}
        self.pessoas = pessoas or {}
        self.existing_dispatch = existing_dispatch
        self.added: list = []
        self.deleted: list = []
        self.committed = False
        self.rolled_back = False
        # SEC-4: simula o índice único parcial pra provar a corrida de reserva
        # sem precisar de Postgres real (Postgres real é coberto à parte em
        # tests/test_agent_event_idempotency_index.py). Chave: (igreja_id, evento).
        # `preexisting_markers`: marcadores já "commitados por outro processo"
        # ANTES desta chamada — simula a corrida perdida.
        self.reserved_markers: set[tuple] = set(preexisting_markers or ())
        self._pending_markers: list = []
        self._pending_all: list = []

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
        self._pending_all.append(obj)
        if isinstance(obj, AgentConversationLog):
            self._pending_markers.append(obj)

    def flush(self) -> None:
        # SEC-4: simula a constraint única parcial (igreja_id, evento) —
        # dispara aqui, igual o INSERT real dispararia no banco.
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
        self.committed = True
        self._pending_all.clear()

    def rollback(self) -> None:
        self.rolled_back = True
        # Desfaz TUDO que foi adicionado desde o último commit (mesma semântica
        # de um ROLLBACK real descartar as mudanças não commitadas da sessão —
        # inclusive o item de coordenação criado junto com a reserva perdida).
        for obj in self._pending_all:
            if obj in self.added:
                self.added.remove(obj)
            if isinstance(obj, AgentConversationLog):
                self.reserved_markers.discard((obj.igreja_id, obj.evento))
        self._pending_all.clear()
        self._pending_markers.clear()

    def delete(self, obj) -> None:
        self.deleted.append(obj)
        if obj in self.added:
            self.added.remove(obj)
        if isinstance(obj, AgentConversationLog):
            self.reserved_markers.discard((obj.igreja_id, obj.evento))


class FakeEvolution:
    """Records send_text calls instead of hitting the network."""

    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self._fail = fail

    def send_text(self, instance: str, telefone: str, texto: str) -> bool:
        if self._fail:
            raise EvolutionError("simulated send failure — no WhatsApp real")
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


def test_dispatch_loses_concurrent_reservation_race_never_sends() -> None:
    """SEC-4: duas tentativas concorrentes pro MESMO marcador — a que perde a
    reserva (índice único já ocupado por outro processo) nunca chega a enviar.

    `_already_dispatched` (SELECT barato) não vê a corrida — é exatamente o
    gap que a reserva atômica fecha. Por isso o teste pré-semeia
    `reserved_markers` (simulando outro processo que já reservou e commitou
    ANTES desta chamada) sem marcar `existing_dispatch`, pra provar que a
    proteção real vem da reserva, não do SELECT."""
    item = _work_item(tipo="relatorio", prazo=_T0)
    breach_evento = _dispatch_event_name(
        SlaBreach(
            igreja_id=_IGREJA, source="work_queue", item_id=item.id,
            kind="relatorio", status=SlaStatus.COBRANCA, titulo="x",
        )
    )
    session = FakeSlaSession(
        work_items=[item],
        connection=SimpleNamespace(instance="igreja-1"),
        preexisting_markers={(_IGREJA, breach_evento)},  # outro processo já reservou
    )
    evo = FakeEvolution()
    engine = SlaEngine(evolution=evo)
    handled = engine.run_for_igreja(session, _IGREJA, now=_T0 + _hours(1))

    assert handled == []
    assert evo.sent == []  # nunca envia — perdeu a corrida antes de qualquer send


def test_dispatch_releases_marker_on_total_send_failure() -> None:
    """SEC-4 (at-least-once): envio falhou pra todo destinatário tentado —
    libera a reserva, pra próxima varredura tentar de novo (não perde a
    cobrança silenciosamente)."""
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
    evo = FakeEvolution(fail=True)
    engine = SlaEngine(evolution=evo)
    handled = engine.run_for_igreja(session, _IGREJA, now=_T0 + _hours(1))

    assert handled == []  # não conta como despachado — falhou de verdade
    assert evo.sent == []
    # A reserva foi liberada: nenhum marcador AgentConversationLog sobrevive.
    assert not any(isinstance(o, AgentConversationLog) for o in session.added)
    assert session.reserved_markers == set()


def test_dispatch_same_item_different_igreja_both_send() -> None:
    """A chave de dedupe é (igreja_id, evento) — o mesmo item_id em igrejas
    diferentes não colide (multi-tenant, espelha
    test_agent_event_idempotency_index.py::test_same_marker_different_igreja_does_not_conflict
    contra Postgres real)."""
    other_igreja = uuid.UUID("00000000-0000-0000-0000-000000000002")
    shared_item_id = uuid.uuid4()

    def _breach(igreja):
        return SlaBreach(
            igreja_id=igreja, source="work_queue", item_id=shared_item_id,
            kind="relatorio", status=SlaStatus.COBRANCA, titulo="x",
        )

    session = FakeSlaSession(connection=SimpleNamespace(instance="igreja-1"))
    evo = FakeEvolution()
    engine = SlaEngine(evolution=evo)

    assert engine._dispatch(session, _breach(_IGREJA), "igreja-1") is True
    assert engine._dispatch(session, _breach(other_igreja), "igreja-1") is True
    assert len(evo.sent) == 0  # sem destinatário resolvível, mas ambos "despacham" (log-only)
    assert session.reserved_markers == {
        (_IGREJA, _dispatch_event_name(_breach(_IGREJA))),
        (other_igreja, _dispatch_event_name(_breach(other_igreja))),
    }


def test_dispatch_event_name_matches_idempotency_marker_pattern() -> None:
    """SEC-4: o marcador tem que bater com o predicado `sla\\_%` do índice único
    parcial (agent_conversation_logs_idem_marker_uidx) — senão o INSERT do
    marcador não fica protegido pela constraint de banco."""
    for status in SlaStatus:
        breach = SlaBreach(
            igreja_id=_IGREJA,
            source="work_queue",
            item_id=uuid.uuid4(),
            kind="relatorio",
            status=status,
            titulo="x",
        )
        assert _dispatch_event_name(breach).startswith("sla_")


def test_dispatch_escalation_failure_then_retry_creates_only_one_workqueueitem() -> None:
    """SEC-4 gap-2: a 1ª tentativa falha no envio (reserva de envio liberada,
    retry permitido) — a 2ª tentativa (mesma breach) reenvia com sucesso, mas
    NÃO recria o WorkQueueItem de coordenação já commitado na 1ª."""
    coord_user = uuid.uuid4()
    coord_pessoa = uuid.uuid4()
    item = _work_item(tipo="relatorio", prazo=_T0)
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
    breach = SlaBreach(
        igreja_id=_IGREJA, source="work_queue", item_id=item.id,
        kind="relatorio", status=SlaStatus.ESCALONAMENTO, titulo="x",
    )

    result1 = SlaEngine(evolution=FakeEvolution(fail=True))._dispatch(
        session, breach, "igreja-1"
    )
    assert result1 is False  # falha total -> reserva de ENVIO liberada
    assert sum(1 for o in session.added if isinstance(o, WorkQueueItem)) == 1

    evo_retry = FakeEvolution()
    result2 = SlaEngine(evolution=evo_retry)._dispatch(session, breach, "igreja-1")

    assert result2 is True  # retry reenvia com sucesso (não perde o aviso)
    assert evo_retry.sent and evo_retry.sent[0][1] == "+5511999990009"
    # O item de coordenação NÃO duplicou no retry.
    assert sum(1 for o in session.added if isinstance(o, WorkQueueItem)) == 1


def test_dispatch_escalation_concurrent_reservation_never_duplicates_workqueueitem() -> None:
    """SEC-4 gap-2: outro processo já venceu a reserva PERMANENTE do item de
    coordenação (marcador pré-existente, simulando uma varredura concorrente
    ou uma tentativa anterior) — esta chamada não cria um segundo
    WorkQueueItem, mas segue enviando o WhatsApp normalmente (a duplicação do
    ITEM não deve bloquear o ENVIO, que tem seu próprio marcador)."""
    coord_user = uuid.uuid4()
    coord_pessoa = uuid.uuid4()
    item = _work_item(tipo="relatorio", prazo=_T0)
    breach = SlaBreach(
        igreja_id=_IGREJA, source="work_queue", item_id=item.id,
        kind="relatorio", status=SlaStatus.ESCALONAMENTO, titulo="x",
    )
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
        preexisting_markers={(_IGREJA, _coordination_item_event_name(breach))},
    )
    evo = FakeEvolution()

    result = SlaEngine(evolution=evo)._dispatch(session, breach, "igreja-1")

    assert result is True
    assert evo.sent and evo.sent[0][1] == "+5511999990009"
    assert not any(isinstance(o, WorkQueueItem) for o in session.added)


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


# ---------------------------------------------------------------------------
# run_all_igrejas — sweep com sessão tenant-scoped por igreja (PR3-B / D3)
# ---------------------------------------------------------------------------
class _DiscoverySession:
    """Sessão compartilhada usada SÓ para a descoberta cross-tenant dos ids.

    Roteia os dois selects de coluna (WorkQueueItem.igreja_id /
    Consolidacao.igreja_id) pela entidade-mãe, devolvendo os UUIDs semeados.
    """

    def __init__(self, *, work_igrejas=None, cons_igrejas=None) -> None:
        self._work = work_igrejas or []
        self._cons = cons_igrejas or []

    def execute(self, statement, params=None) -> _FakeResult:
        entity = statement.column_descriptions[0].get("entity")
        if entity is WorkQueueItem:
            return _FakeResult(self._work)
        if entity is Consolidacao:
            return _FakeResult(self._cons)
        return _FakeResult([])


class _TenantSession:
    """Sessão por-igreja: registra o seam (info) e a marca de fechamento."""

    def __init__(self) -> None:
        self.info: dict = {}
        self.closed = False
        self.rolled_back = False
        self.tenant_calls: list[tuple[str, dict | None]] = []

    def execute(self, statement, params=None) -> _FakeResult:
        # Só o seam (set_tenant_context_for_igreja) emite text() aqui.
        self.tenant_calls.append((str(statement), params))
        return _FakeResult([])

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class _RecordingEngine:
    """Exige que a sessão recebida já esteja pinada no igreja_id (seam antes)."""

    def __init__(self, *, boom_on=None) -> None:
        self.calls: list = []
        self._boom_on = boom_on

    def run_for_igreja(self, session, igreja_id, now=None) -> list:
        # Prova do pinning: o seam marcou a sessão ANTES de o engine rodar.
        assert session.info.get(TENANT_IGREJA_KEY) == str(igreja_id)
        assert session.info[TENANT_META_KEY]["source"] == "cron_sla"
        self.calls.append((session, igreja_id))
        if self._boom_on is not None and igreja_id == self._boom_on:
            raise RuntimeError("engine boom")
        return [object()]


def test_run_all_igrejas_scopes_a_new_session_per_igreja() -> None:
    ig_a = uuid.uuid4()
    ig_b = uuid.uuid4()
    # Descoberta: A vem da work_queue; B aparece nas duas fontes (set dedupa).
    discovery = _DiscoverySession(work_igrejas=[ig_a, ig_b], cons_igrejas=[ig_b])

    created: list[_TenantSession] = []

    def factory() -> _TenantSession:
        s = _TenantSession()
        created.append(s)
        return s

    engine = _RecordingEngine()
    total = run_all_igrejas(discovery, engine, _T0, session_factory=factory)

    # Uma nova sessão tenant-scoped por igreja distinta (A e B).
    assert len(created) == 2
    assert {ig for _, ig in engine.calls} == {ig_a, ig_b}
    # Cada sessão foi fechada ao fim da iteração (sem vazar role/GUC ao pool).
    assert all(s.closed for s in created)
    # Cada engine.run_for_igreja recebeu a sessão criada NAQUELA iteração — logo
    # nenhuma sessão foi remarcada para outra igreja (respeita o pinning de D3).
    assert {id(s) for s in created} == {id(s) for s, _ in engine.calls}
    # O seam emitiu o SQL de escopo (set_config app.tenant_igreja_id) por sessão.
    for s in created:
        joined = " ".join(sql for sql, _ in s.tenant_calls)
        assert "app.tenant_igreja_id" in joined
        assert "set local role authenticated" in joined
    assert total == 2


def test_run_all_igrejas_closes_session_even_when_engine_raises() -> None:
    ig_a = uuid.uuid4()
    ig_b = uuid.uuid4()
    discovery = _DiscoverySession(work_igrejas=[ig_a, ig_b])

    created: list[_TenantSession] = []

    def factory() -> _TenantSession:
        s = _TenantSession()
        created.append(s)
        return s

    engine = _RecordingEngine(boom_on=ig_a)
    total = run_all_igrejas(discovery, engine, _T0, session_factory=factory)

    # A falha de um tenant não derruba os demais; a sessão que falhou foi
    # revertida e fechada, sem devolver a conexão ao pool em role authenticated.
    assert len(created) == 2
    assert all(s.closed for s in created)
    failed = next(s for s, ig in _pairs(engine, ig_a))
    assert failed.rolled_back is True
    # Só o tenant saudável contribuiu para o total.
    assert total == 1


def _pairs(engine: _RecordingEngine, igreja_id):
    """Pares (sessão, igreja) do engine para uma igreja específica."""
    return [(s, ig) for s, ig in engine.calls if ig == igreja_id]
