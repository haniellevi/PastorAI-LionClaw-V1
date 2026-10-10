"""RED for catalog-bound own presence, synthetic and offline.

Existing catalog, proposal/confirmation and human service run unchanged.
The session double supports direct SELECT predicates, not SQL joins, RLS,
locks, UNIQUE races or a real transaction. Query oracles check bound values.
The public confirmation turn has fake preflight/context/worker delivery seams;
it does not test webhook ingestion, identity resolution, external routing,
WhatsApp transport or an HTTP panel. No product result is fabricated.
Only the Orchestrator's reviewed offline launcher may execute this module.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import datetime as dt
from contextlib import contextmanager
from dataclasses import fields, replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BinaryExpression, BindParameter, BooleanClauseList
from sqlalchemy.sql.elements import False_, Grouping, Null, True_

from app.agent import privileged_turn as turn
from app.db.models import (
    AgentActionProposal, AgentActionReceipt, AppUser, Celula, CelulaMembro,
    CelulaPresenca, CelulaReuniao, Conversation, Message, Pessoa,
)
from app.domain import cell_meetings_schedule as schedule
from app.domain.agent_reply import AGENT_REPLY_CONFIRMED, AGENT_REPLY_PENDING, AGENT_REPLY_RESERVED
from app.routers import cell_discipulo as panel
from app.services import agent_action_proposals as proposals
from app.services import agent_privilege_catalog as catalog
from app.services import ministerial_actions as human
from app.services.whatsapp_privilege import PrivilegeContext, PublicWhatsappContext


TENANT, ACTOR, PERSON, CELL, MEETING, CONVERSATION, REQUEST, SUMMARY, CONFIRM, REPLY, OTHER = (
    UUID(int=value) for value in range(1, 12)
)
NOW = dt.datetime(2030, 1, 1, 0, 30, tzinfo=dt.timezone.utc)
REQUEST_TEXT = "Quero confirmar minha presença na próxima reunião da minha célula."


def _context(**changes):
    values = dict(igreja_id=TENANT, app_user_id=ACTOR, pessoa_id=PERSON,
                  conversation_id=CONVERSATION, inbound_message_id=REQUEST,
                  roles=frozenset({"membro"}), role_snapshot=((UUID(int=20), "membro"),),
                  owned_cell_ids=(), credential_fingerprint="1" * 64,
                  phone_fingerprint="2" * 64, authorization_fingerprint="3" * 64,
                  proof_id=None, proof_until=None, sensitive=False,
                  scope_fingerprint="4" * 64, context_fingerprint="5" * 64)
    values.update(changes)
    return PrivilegeContext(**values)


def _value(expression, row):
    if isinstance(expression, BindParameter):
        return expression.value
    if isinstance(expression, True_):
        return True
    if isinstance(expression, False_):
        return False
    if isinstance(expression, Null):
        return None
    key = getattr(expression, "key", None)
    assert key is not None and hasattr(row, key), "unsupported synthetic SELECT field"
    return getattr(row, key)


def _matches(expression, row):
    if expression is None:
        return True
    if isinstance(expression, Grouping):
        return _matches(expression.element, row)
    if isinstance(expression, BooleanClauseList):
        if expression.operator is operators.and_:
            return all(_matches(item, row) for item in expression.clauses)
        assert expression.operator is operators.or_, "unsupported synthetic SELECT boolean"
        return any(_matches(item, row) for item in expression.clauses)
    assert isinstance(expression, BinaryExpression), "unsupported synthetic SELECT predicate"
    left, right = _value(expression.left, row), _value(expression.right, row)
    op = expression.operator
    if op in (operators.eq, operators.is_):
        return left == right
    if op in (operators.ne, operators.is_not):
        return left != right
    if op is operators.in_op:
        return left in right
    if op is operators.not_in_op:
        return left not in right
    assert op in (operators.ge, operators.gt, operators.le, operators.lt), "unsupported synthetic SELECT operator"
    if op is operators.ge:
        return left >= right
    if op is operators.gt:
        return left > right
    if op is operators.le:
        return left <= right
    return left < right


class _Rows:
    def __init__(self, values):
        self.values = values

    def scalar_one_or_none(self):
        assert len(self.values) <= 1, "ambiguous synthetic scalar result"
        return self.values[0] if self.values else None

    def scalars(self):
        return self

    def all(self):
        return list(self.values)

    def __iter__(self):
        return iter(self.values)


class _Session:
    """Small direct-select fixture; never connects or executes SQL."""

    def __init__(self):
        self.tables = {model: [] for model in (
            Pessoa, AppUser, Celula, CelulaMembro, CelulaReuniao, CelulaPresenca,
            Conversation, Message, AgentActionProposal, AgentActionReceipt,
        )}
        self.statements = []
        self.events = []
        self.committed_presence = ()
        self.fail_commit = False
        self.next_id = 100

    def seed(self, model, **values):
        if model is Message:
            values = {"provider_message_id": None, "agent_reply_state": None,
                      "agent_privilege_context": None, "criado_em": NOW, **values}
        row = SimpleNamespace(**values)
        self.tables[model].append(row)
        return row

    def execute(self, statement):
        self.statements.append(statement)
        descriptions = statement.column_descriptions
        model = descriptions[0]["entity"]
        assert model in self.tables, "unsupported synthetic SELECT entity"
        # Cross-table joins need a separately reviewed fixture, not silent
        # success from this direct-select double.
        froms = statement.get_final_froms()
        assert len(froms) == 1 and getattr(froms[0], "name", None) == model.__table__.name, "unsupported synthetic SELECT join"
        values = [row for row in self.tables[model] if _matches(statement.whereclause, row)]
        if model is CelulaReuniao:
            for column in reversed(tuple(statement._order_by_clauses)):
                assert column.key in ("data", "id"), "unsupported synthetic meeting ordering"
                values.sort(key=lambda row: getattr(row, column.key))
        limit = statement._limit_clause
        if limit is not None:
            values = values[:limit.value]
        if descriptions[0]["expr"] is not model:
            projected = [tuple(_value(item["expr"], row) for item in descriptions) for row in values]
            values = [item[0] for item in projected] if len(descriptions) == 1 else projected
        return _Rows(values)

    def add(self, row):
        model = type(row)
        assert model in (CelulaPresenca, AgentActionProposal, AgentActionReceipt), "unexpected synthetic write"
        if row.id is None:
            row.id = UUID(int=self.next_id)
            self.next_id += 1
        if model is AgentActionProposal:
            row.created_at = NOW
        self.tables[model].append(row)
        self.events.append(("add", model.__name__))

    def flush(self):
        self.events.append(("flush",))

    def refresh(self, row):
        assert row in self.tables[type(row)]

    @contextmanager
    def begin_nested(self):
        yield

    def commit(self):
        if self.fail_commit:
            self.events.append(("commit_failed",))
            raise RuntimeError("SYNTHETIC_COMMIT_FAILURE")
        self.committed_presence = tuple(
            (row.igreja_id, row.reuniao_id, row.pessoa_id, row.estado, row.origem)
            for row in self.tables[CelulaPresenca]
        )
        self.events.append(("commit",))

    def rollback(self):
        # Records caller behavior only; does not emulate DB rollback.
        self.events.append(("rollback",))

    def close(self):
        pass


def _has_filter(statement, model, key, op, expected):
    if statement.whereclause is None:
        return False
    for node in visitors.iterate(statement.whereclause):
        if not isinstance(node, BinaryExpression) or node.operator is not op:
            continue
        left = node.left
        table = getattr(left, "table", None)
        if table is None or table.name != model.__table__.name or left.key != key:
            continue
        right = node.right
        value = right.value if isinstance(right, BindParameter) else True if isinstance(right, True_) else None
        if type(value) is type(expected) and value == expected:
            return True
    return False


def _assert_query(db, model, **expected):
    assert any(all(_has_filter(statement, model, key, operators.is_ if key == "ativo" else operators.eq, value)
                   for key, value in expected.items()) for statement in db.statements), "required scoped predicate absent"


def _own_targets(db, context):
    options, mapping = catalog.build_catalog(db, context)
    targets = [target for target in mapping.values() if target.code == "marcar_presenca"]
    return options, targets


@pytest.fixture
def world(monkeypatch):
    db = _Session()
    member = db.seed(CelulaMembro, igreja_id=TENANT, pessoa_id=PERSON, celula_id=CELL, ativo=True)
    event = db.seed(CelulaReuniao, id=MEETING, igreja_id=TENANT, celula_id=CELL,
                    data=dt.date(2030, 1, 1), hora="20:00")
    db.seed(Celula, id=CELL, igreja_id=TENANT, nome="CELULA-SINTETICA", ativo=True, lider_id=OTHER)
    db.seed(Pessoa, id=PERSON, igreja_id=TENANT, nome="MEMBRO-SINTETICO", arquivada_em=None, lider_id=None)
    db.seed(Pessoa, id=OTHER, igreja_id=TENANT, nome="TERCEIRO-SINTETICO", arquivada_em=None, lider_id=None)
    actor = db.seed(AppUser, id=ACTOR, igreja_id=TENANT, pessoa_id=PERSON)
    conversation = db.seed(Conversation, id=CONVERSATION, igreja_id=TENANT,
                           estado="ia", assumido_por=None, secretaria_oferta_estado=None)
    request = db.seed(Message, id=REQUEST, igreja_id=TENANT, conversation_id=CONVERSATION,
                      texto=REQUEST_TEXT, direcao="in", autor="pessoa", criado_em=NOW)
    summary = db.seed(Message, id=SUMMARY, igreja_id=TENANT, conversation_id=CONVERSATION,
                      texto="", direcao="out", autor="ia", agent_reply_state=AGENT_REPLY_RESERVED)
    confirmation = db.seed(Message, id=CONFIRM, igreja_id=TENANT, conversation_id=CONVERSATION,
                           texto="SIM", direcao="in", autor="pessoa", criado_em=NOW + dt.timedelta(seconds=2))
    reply = db.seed(Message, id=REPLY, igreja_id=TENANT, conversation_id=CONVERSATION,
                    provider_message_id="SYNTHETIC-REPLY", texto="", direcao="out", autor="ia",
                    agent_reply_state=AGENT_REPLY_RESERVED, agent_privilege_context=None)
    current = _context(inbound_message_id=CONFIRM)
    result = SimpleNamespace(db=db, member=member, event=event, actor=actor,
                             request=request, summary=summary, confirmation=confirmation,
                             reply=reply, conversation=conversation, context=_context(), current=current)
    monkeypatch.setattr(catalog, "agenda_enabled_from_environment", lambda _tenant: False)
    monkeypatch.setattr(catalog, "consolidation_enabled_from_environment", lambda _tenant: False)
    monkeypatch.setattr(schedule, "now_in_sao_paulo", lambda now=None: (now or NOW).astimezone(schedule.SAO_PAULO_TZ))

    class _Date(dt.date):
        @classmethod
        def today(cls):
            return NOW.date()  # Deliberately UTC host date, different from São Paulo.

    class _DateTime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)

    frozen_dt = SimpleNamespace(date=_Date, datetime=_DateTime, timedelta=dt.timedelta, timezone=dt.timezone)
    monkeypatch.setattr(catalog, "dt", frozen_dt)
    monkeypatch.setattr(human, "dt", frozen_dt)
    monkeypatch.setattr(proposals, "_database_now", lambda _db, now: now if now is not None else NOW + dt.timedelta(seconds=3))

    def tenant_scope(session, *, expected_igreja_id, source):
        assert session is db and expected_igreja_id == TENANT and source == "agent_action_proposals"

    monkeypatch.setattr(proposals, "require_tenant_scope", tenant_scope)
    monkeypatch.setattr(proposals, "resolve_whatsapp_privilege_context", lambda *_args, **_kwargs: result.current)
    result.human_spy = Mock(wraps=human.confirm_meeting_attendance)
    monkeypatch.setattr(catalog, "confirm_meeting_attendance", result.human_spy)
    return result


def _stage(world):
    options, targets = _own_targets(world.db, world.context)
    assert len(targets) == 1, "missing unique own-presence candidate"
    target = targets[0]
    assert dict(target.arguments) == {"pessoa_id": str(PERSON), "reuniao_id": str(MEETING)}
    assert turn._apply_selection(world.db, world.context, target, world.summary,
                                 current_text=world.request.texto, conversation=world.conversation)
    assert len(world.db.tables[AgentActionProposal]) == 1
    row = world.db.tables[AgentActionProposal][0]
    assert (row.action, row.target_kind, row.target_id, row.actor_pessoa_id, row.actor_app_user_id) == (
        "marcar_presenca", "pessoa", PERSON, PERSON, ACTOR)
    assert row.state == "preparada"
    assert world.summary.agent_privilege_context["kind"] == "summary"
    assert "SIM" in world.summary.texto
    assert not world.db.tables[CelulaPresenca]
    assert not world.db.committed_presence
    assert ("commit",) not in world.db.events
    return row


def _pending(world):
    row = _stage(world)
    world.summary.agent_reply_state = AGENT_REPLY_CONFIRMED
    proposals.promote_action_proposal_after_delivery(
        world.db, igreja_id=TENANT, conversation_id=CONVERSATION, proposal_id=row.id,
        summary_message_id=SUMMARY, now=NOW + dt.timedelta(seconds=1))
    assert row.state == "pendente"
    return row


def _public_confirmation(world, monkeypatch):
    # Only the preflight/worker transport and resolved-identity boundaries are
    # doubled. The entire local proposal/confirmation/domain chain stays real.
    from app.agent import runtime
    from app.services import whatsapp_privilege
    from app.workers import queue_worker as qw

    outcome = SimpleNamespace(igreja_id=TENANT, conversation_id=CONVERSATION,
                              inbound_message_id=CONFIRM, provider_message_id="SYNTHETIC-INBOUND",
                              texto=world.confirmation.texto)
    delivered = []
    monkeypatch.setattr(turn, "_run_audio_local_turn", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(turn, "_local_audio_consent", lambda *_args: False)
    monkeypatch.setattr(turn, "_enabled", lambda _tenant: True)
    monkeypatch.setattr(turn, "time", SimpleNamespace(monotonic=lambda: 1000.0))
    monkeypatch.setattr(runtime, "process_inbound_message", lambda *_args, **_kwargs: SimpleNamespace(
        reason="tier_a_prepared", preflight=SimpleNamespace(current_text=world.confirmation.texto)))
    monkeypatch.setattr(runtime, "_load_tier_a_plan_state", lambda *_args: (None, None, None))
    monkeypatch.setattr(whatsapp_privilege, "resolve_whatsapp_privilege_context", lambda *_args, **_kwargs: world.current)
    monkeypatch.setattr(qw, "_scope_agent_execution_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(qw, "_agent_reply_idempotency_key", lambda _outcome: "SYNTHETIC-REPLY")
    monkeypatch.setattr(qw, "_reserve_agent_reply_intent", lambda *_args: world.reply)
    monkeypatch.setattr(turn, "_read_reply", lambda *_args: None if world.reply.agent_reply_state == AGENT_REPLY_RESERVED
                        else SimpleNamespace(state=world.reply.agent_reply_state))

    def deliver(*_args, **_kwargs):
        assert ("commit",) in world.db.events, "delivery before successful commit"
        world.db.events.append(("deliver",))
        delivered.append((world.reply.texto, world.db.committed_presence))

    monkeypatch.setattr(qw, "_deliver_agent_reply_intent", deliver)
    world.delivered = delivered
    return turn.run_privileged_turn(lambda: world.db, lambda: world.db, outcome,
        igreja_id=TENANT, turn_identity=None, uses_dedicated_agent_session=False,
        ownership_guard=None, evolution_client=object())


@pytest.mark.parametrize("text", [REQUEST_TEXT,
    "Confirmar minha presença na próxima reunião da minha célula.",
    "Eu confirmo minha presença na próxima reunião da minha célula."])
def test_explicit_own_request_builds_closed_server_target(world, text):
    world.request.texto = text
    options, targets = _own_targets(world.db, world.context)
    assert len(targets) == 1
    assert dict(targets[0].arguments) == {"pessoa_id": str(PERSON), "reuniao_id": str(MEETING)}
    assert any(option.code == "marcar_presenca" and len(option.candidates) == 1 for option in options)
    assert world.context.owned_cell_ids == ()
    _assert_query(world.db, Message, igreja_id=TENANT, conversation_id=CONVERSATION, id=REQUEST, direcao="in")
    _assert_query(world.db, CelulaMembro, igreja_id=TENANT, pessoa_id=PERSON, ativo=True)
    _assert_query(world.db, CelulaReuniao, igreja_id=TENANT, celula_id=CELL)
    assert not world.db.tables[CelulaPresenca]


@pytest.mark.parametrize("text", ["Presença", "Vou à célula", "SIM", "CONFIRMO",
    "Quero confirmar a presença de TERCEIRO-SINTETICO.",
    "Quero confirmar minha presença e a de TERCEIRO-SINTETICO.",
    "Não quero confirmar minha presença na próxima reunião da minha célula.",
    "Talvez eu confirme minha presença na próxima reunião da minha célula."])
def test_vague_third_party_negated_or_conditional_request_has_no_own_candidate(world, text):
    world.request.texto = text
    _, targets = _own_targets(world.db, world.context)
    assert targets == []
    world.human_spy.assert_not_called()
    assert not world.db.tables[AgentActionProposal]


@pytest.mark.parametrize("change", ["missing", "inactive", "other_tenant", "other_person", "inactive_cell"])
def test_catalog_requires_current_real_member_association(world, change):
    if change == "missing":
        world.db.tables[CelulaMembro].clear()
    elif change == "inactive":
        world.member.ativo = False
    elif change == "other_tenant":
        world.member.igreja_id = OTHER
    elif change == "other_person":
        world.member.pessoa_id = OTHER
    else:
        world.db.tables[Celula][0].ativo = False
    _, targets = _own_targets(world.db, world.context)
    assert targets == []
    assert not world.db.tables[CelulaPresenca]


def test_no_meeting_has_no_own_candidate(world):
    world.db.tables[CelulaReuniao].clear()
    assert _own_targets(world.db, world.context)[1] == []


@pytest.mark.parametrize("next_requested", [True, False])
def test_three_future_occurrences_choose_only_explicit_next(world, next_requested):
    # R2 semantic correction: the old RED treated the canonical "próxima"
    # request as generic ambiguity. The original bytes remain with ROOT.
    world.request.texto = REQUEST_TEXT if next_requested else REQUEST_TEXT.replace("próxima ", "")
    for number, day in ((40, 3), (41, 2)):
        world.db.seed(CelulaReuniao, id=UUID(int=number), igreja_id=TENANT,
                      celula_id=CELL, data=dt.date(2030, 1, day), hora="20:00")
    targets = _own_targets(world.db, world.context)[1]
    assert [target.arguments["reuniao_id"] for target in targets] == ([str(MEETING)] if next_requested else [])


def test_next_orders_same_date_by_hour_not_uuid_or_seed_order(world):
    world.event.hora = "23:00"
    world.db.seed(CelulaReuniao, id=OTHER, igreja_id=TENANT, celula_id=CELL,
                  data=world.event.data, hora="22:00")
    world.db.seed(CelulaReuniao, id=UUID(int=40), igreja_id=TENANT, celula_id=CELL,
                  data=world.event.data, hora="20:00")
    targets = _own_targets(world.db, world.context)[1]
    assert [target.arguments["reuniao_id"] for target in targets] == [str(UUID(int=40))]


@pytest.mark.parametrize("tie_hour,expected", [("20:00", []), ("23:00", [str(MEETING)])])
def test_only_tie_at_earliest_occurrence_blocks_next(world, tie_hour, expected):
    for number in (40, 41):
        world.db.seed(CelulaReuniao, id=UUID(int=number), igreja_id=TENANT,
                      celula_id=CELL, data=world.event.data, hora=tie_hour)
    assert [target.arguments["reuniao_id"] for target in _own_targets(world.db, world.context)[1]] == expected


@pytest.mark.parametrize("unknown_hour", [None, "hora-desconhecida"])
def test_unknown_hour_blocks_ordering_multiple_occurrences_on_first_date(world, unknown_hour):
    world.db.seed(CelulaReuniao, id=OTHER, igreja_id=TENANT, celula_id=CELL,
                  data=world.event.data, hora=unknown_hour)
    assert _own_targets(world.db, world.context)[1] == []


def test_single_occurrence_on_first_date_may_have_no_hour_per_e4(world):
    world.event.hora = None
    world.db.seed(CelulaReuniao, id=OTHER, igreja_id=TENANT, celula_id=CELL,
                  data=dt.date(2030, 1, 2), hora="20:00")
    assert [target.arguments["reuniao_id"] for target in _own_targets(world.db, world.context)[1]] == [str(MEETING)]


def test_two_passed_today_do_not_hide_later_eligible_occurrence(world):
    world.event.data, world.event.hora = dt.date(2029, 12, 31), "20:00"
    world.db.seed(CelulaReuniao, id=OTHER, igreja_id=TENANT, celula_id=CELL,
                  data=world.event.data, hora="21:00")
    world.db.seed(CelulaReuniao, id=UUID(int=40), igreja_id=TENANT, celula_id=CELL,
                  data=world.event.data, hora="22:00")
    assert [target.arguments["reuniao_id"] for target in _own_targets(world.db, world.context)[1]] == [str(UUID(int=40))]


@pytest.mark.parametrize("sentinel,next_requested,expected", [
    ("tie", True, []), ("unknown", True, []),
    ("later", True, [str(UUID(int=1000))]), ("later", False, []),
])
def test_window_64_plus_sentinel_never_hides_candidate_date_ambiguity(world, sentinel, next_requested, expected):
    world.request.texto = REQUEST_TEXT if next_requested else REQUEST_TEXT.replace("próxima ", "")
    world.db.tables[CelulaReuniao].clear()
    for number in reversed(range(65)):
        world.db.seed(CelulaReuniao, id=UUID(int=1000 + number), igreja_id=TENANT,
                      celula_id=CELL,
                      data=dt.date(2030, 1, 2 if number == 64 and sentinel == "later" else 1),
                      hora=None if number == 64 and sentinel == "unknown" else
                           "20:00" if number == 0 or number == 64 else "23:00")
    targets = _own_targets(world.db, world.context)[1]
    assert [target.arguments["reuniao_id"] for target in targets] == expected
    queries = [statement for statement in world.db.statements
               if statement.column_descriptions[0]["entity"] is CelulaReuniao]
    assert len(queries) == 1
    query = queries[0]
    assert query._limit_clause is not None and query._limit_clause.value == 65
    assert tuple(column.key for column in query._order_by_clauses) == ("data", "id")
    assert _has_filter(query, CelulaReuniao, "data", operators.ge, dt.date(2029, 12, 31))
    assert _has_filter(query, CelulaReuniao, "igreja_id", operators.eq, TENANT)
    assert _has_filter(query, CelulaReuniao, "celula_id", operators.eq, CELL)


@pytest.mark.parametrize("next_requested", [True, False])
def test_truncation_before_first_eligible_occurrence_fails_closed(world, next_requested):
    world.request.texto = REQUEST_TEXT if next_requested else REQUEST_TEXT.replace("próxima ", "")
    world.db.tables[CelulaReuniao].clear()
    for number in range(66):
        world.db.seed(CelulaReuniao, id=UUID(int=1000 + number), igreja_id=TENANT,
                      celula_id=CELL, data=dt.date(2029, 12, 31),
                      hora="20:00" if number < 64 else "22:00")
    assert _own_targets(world.db, world.context)[1] == []


def test_catalog_captures_one_sao_paulo_now_for_entire_selection(world, monkeypatch):
    reads = []

    def clock(now=None):
        reads.append(now)
        return (NOW if now is None else now).astimezone(schedule.SAO_PAULO_TZ)

    monkeypatch.setattr(schedule, "now_in_sao_paulo", clock)
    world.db.seed(CelulaReuniao, id=OTHER, igreja_id=TENANT, celula_id=CELL,
                  data=dt.date(2030, 1, 2), hora="20:00")
    _own_targets(world.db, world.context)
    assert reads.count(None) == 1
    assert all(value == NOW for value in reads if value is not None)


@pytest.mark.parametrize("hora,eligible", [("21:29", False), ("21:30", True), ("21:31", True)])
def test_catalog_exact_time_equality_has_not_passed_per_e4(world, hora, eligible):
    world.event.data, world.event.hora = dt.date(2029, 12, 31), hora
    assert len(_own_targets(world.db, world.context)[1]) == (1 if eligible else 0)


@pytest.mark.parametrize("data,hora,eligible", [
    (dt.date(2029, 12, 30), "20:00", False),
    (dt.date(2029, 12, 31), "20:00", False),
    (dt.date(2029, 12, 31), "22:00", True),
    (dt.date(2030, 1, 1), "20:00", True),
])
def test_catalog_eligibility_uses_sao_paulo_not_utc_host_date(world, data, hora, eligible):
    world.event.data, world.event.hora = data, hora
    assert schedule.meeting_has_passed(data=data, hora=hora, now=NOW) is not eligible
    targets = _own_targets(world.db, world.context)[1]
    assert len(targets) == (1 if eligible else 0)


def test_inbound_and_meeting_are_scoped_to_current_tenant_and_cell(world):
    world.request.igreja_id = OTHER
    assert _own_targets(world.db, world.context)[1] == []
    world.request.igreja_id = TENANT
    world.event.igreja_id = OTHER
    assert _own_targets(world.db, world.context)[1] == []
    world.event.igreja_id = TENANT
    world.event.celula_id = OTHER
    assert _own_targets(world.db, world.context)[1] == []


def test_catalog_selection_stages_existing_action_without_presence_or_commit(world):
    _stage(world)
    world.human_spy.assert_not_called()


@pytest.mark.parametrize("word", ["SIM", "CONFIRMO"])
def test_public_confirmation_executes_real_service_before_committed_receipt(world, monkeypatch, word):
    row = _pending(world)
    world.confirmation.texto = word
    _public_confirmation(world, monkeypatch)
    assert row.state == "executada"
    assert world.reply.agent_reply_state == AGENT_REPLY_PENDING
    assert world.reply.agent_privilege_context["kind"] == "receipt"
    assert world.reply.texto.startswith("Registro confirmado. Comprovante: ")
    expected = ((TENANT, MEETING, PERSON, "confirmada", "auto"),)
    assert world.delivered == [(world.reply.texto, expected)]
    assert world.db.events.index(("commit",)) < world.db.events.index(("deliver",))
    world.human_spy.assert_called_once()
    _assert_query(world.db, AppUser, id=ACTOR, igreja_id=TENANT)
    _assert_query(world.db, CelulaMembro, igreja_id=TENANT, pessoa_id=PERSON, celula_id=CELL, ativo=True)
    _assert_query(world.db, CelulaPresenca, igreja_id=TENANT, pessoa_id=PERSON, reuniao_id=MEETING)
    # The panel's actual shared lookup reads the same record, no ready response.
    source = panel._find_presenca(world.db, TENANT, MEETING, PERSON)
    assert source is world.db.tables[CelulaPresenca][0]
    assert panel._map_minha_presenca(source.estado) == "confirmou"


def test_undelivered_summary_never_executes_presence(world, monkeypatch):
    row = _stage(world)
    _public_confirmation(world, monkeypatch)
    assert row.state == "preparada"
    assert not world.db.committed_presence
    world.human_spy.assert_not_called()
    assert world.reply.agent_privilege_context["kind"] != "receipt"


def test_selection_revalidates_membership_after_model_window(world):
    _, targets = _own_targets(world.db, world.context)
    assert len(targets) == 1
    world.member.ativo = False
    assert not turn._apply_selection(world.db, world.context, targets[0], world.summary,
                                    current_text=REQUEST_TEXT, conversation=world.conversation)
    assert not world.db.tables[AgentActionProposal]


@pytest.mark.parametrize("change", ["membership", "actor", "meeting_tenant", "meeting_cell", "past"])
def test_confirmation_revalidates_domain_facts_before_any_presence(world, monkeypatch, change):
    row = _pending(world)
    if change == "membership":
        world.member.ativo = False
    elif change == "actor":
        world.actor.pessoa_id = OTHER
    elif change == "meeting_tenant":
        world.event.igreja_id = OTHER
    elif change == "meeting_cell":
        world.event.celula_id = OTHER
    else:
        world.event.data, world.event.hora = dt.date(2029, 12, 31), "20:00"
    _public_confirmation(world, monkeypatch)
    assert row.state == "rejeitada"
    assert not world.db.tables[CelulaPresenca]
    assert not world.db.tables[AgentActionReceipt]
    assert "Registro confirmado." not in world.reply.texto


def test_context_revocation_and_optout_do_not_execute_or_deliver_success(world, monkeypatch):
    row = _pending(world)
    world.current = PublicWhatsappContext(igreja_id=TENANT, conversation_id=CONVERSATION, inbound_message_id=CONFIRM)
    assert _public_confirmation(world, monkeypatch) is None
    assert row.state == "pendente"
    assert not world.db.committed_presence
    world.human_spy.assert_not_called()
    assert world.delivered == []


def test_changed_server_actor_cancels_pending_proposal(world, monkeypatch):
    row = _pending(world)
    world.current = replace(world.current, pessoa_id=OTHER, app_user_id=OTHER)
    _public_confirmation(world, monkeypatch)
    assert row.state == "cancelada"
    world.human_spy.assert_not_called()
    assert not world.db.tables[CelulaPresenca]


def test_commit_failure_never_delivers_success(world, monkeypatch):
    _pending(world)
    world.db.fail_commit = True
    with pytest.raises(RuntimeError, match="^SYNTHETIC_COMMIT_FAILURE$"):
        _public_confirmation(world, monkeypatch)
    assert world.delivered == []
    assert world.db.committed_presence == ()
    assert ("rollback",) in world.db.events


def test_same_confirmation_replays_receipt_without_reexecuting_service(world):
    row = _pending(world)
    kwargs = dict(igreja_id=TENANT, conversation_id=CONVERSATION, confirmation_message_id=CONFIRM,
                  disposition=proposals.ProposalDisposition.CONFIRM,
                  execute=lambda execution: turn._execute(world.db, execution),
                  now=NOW + dt.timedelta(seconds=3))
    first = proposals.resolve_and_execute_action_proposal(world.db, **kwargs)
    second = proposals.resolve_and_execute_action_proposal(world.db, **kwargs)
    assert first.status.value == "executed" and second.status.value == "receipt"
    assert first.receipt_id == second.receipt_id
    assert row.state == "executada"
    assert len(world.db.tables[CelulaPresenca]) == len(world.db.tables[AgentActionReceipt]) == 1
    world.human_spy.assert_called_once()
    assert ("commit",) not in world.db.events


def test_execution_self_arguments_use_service_and_are_idempotent(world):
    args = {"pessoa_id": str(PERSON), "reuniao_id": str(MEETING)}
    first = catalog.execute_catalog_action(world.db, world.context, "marcar_presenca", args)
    second = catalog.execute_catalog_action(world.db, world.context, "marcar_presenca", args)
    assert first == second
    assert len(world.db.tables[CelulaPresenca]) == 1
    row = world.db.tables[CelulaPresenca][0]
    assert (row.pessoa_id, row.estado, row.origem) == (PERSON, "confirmada", "auto")
    assert ("commit",) not in world.db.events


def test_own_adapter_passes_expected_actor_uuid_without_explicit_target_to_service(world):
    catalog.execute_catalog_action(world.db, world.context, "marcar_presenca",
                                   {"pessoa_id": str(PERSON), "reuniao_id": str(MEETING)})
    kwargs = world.human_spy.call_args.kwargs
    assert kwargs["reuniao_id"] == MEETING
    assert kwargs.get("pessoa_id") is None
    assert kwargs.get("expected_actor_pessoa_id") == PERSON
    assert type(kwargs["expected_actor_pessoa_id"]) is UUID


@pytest.mark.parametrize("change", ["inactive_cell", "relink", "revoked_member", "time_passed"])
def test_service_revalidates_after_catalog_precheck_before_presence_or_receipt(world, monkeypatch, change):
    world.event.data, world.event.hora = dt.date(2029, 12, 31), "22:00"
    row = _pending(world)
    entered = []

    def after_precheck(db, user, **kwargs):
        entered.append(True)
        assert not db.tables[CelulaPresenca] and not db.tables[AgentActionReceipt]
        if change == "inactive_cell":
            db.tables[Celula][0].ativo = False
        elif change == "relink":
            world.actor.pessoa_id = OTHER
        elif change == "revoked_member":
            world.member.ativo = False
        else:
            later = NOW + dt.timedelta(minutes=30, seconds=1)
            monkeypatch.setattr(schedule, "now_in_sao_paulo",
                                lambda now=None: (later if now is None else now).astimezone(schedule.SAO_PAULO_TZ))
        # The mutation models the gap before the service acquires locks;
        # it does not emulate concurrent changes to already locked PG rows.
        return human.confirm_meeting_attendance(db, user, **kwargs)

    world.human_spy.side_effect = after_precheck
    _public_confirmation(world, monkeypatch)
    assert entered == [True]
    assert row.state == "rejeitada"
    assert not world.db.tables[CelulaPresenca]
    assert not world.db.tables[AgentActionReceipt]
    assert "Registro confirmado." not in world.reply.texto


def test_member_never_executes_for_third_person_even_with_leadership_cell_ids(world):
    context = replace(world.context, owned_cell_ids=(CELL,))
    with pytest.raises(HTTPException) as caught:
        catalog.execute_catalog_action(world.db, context, "marcar_presenca",
                                       {"pessoa_id": str(OTHER), "reuniao_id": str(MEETING)})
    assert caught.value.status_code == 403
    world.human_spy.assert_not_called()
    assert not world.db.tables[CelulaPresenca]


@pytest.mark.parametrize("past", [False, True])
@pytest.mark.parametrize("role", ["pastor", "lider_celula"])
def test_existing_leadership_third_party_service_path_remains_distinct(world, past, role):
    if past:
        world.event.data = dt.date(2029, 12, 30)
    if role == "lider_celula":
        world.db.tables[Celula][0].lider_id = PERSON
    world.db.seed(CelulaMembro, igreja_id=TENANT, pessoa_id=OTHER, celula_id=CELL, ativo=True)
    context = replace(world.context, roles=frozenset({role}))
    result = catalog.execute_catalog_action(world.db, context, "marcar_presenca",
                                            {"pessoa_id": str(OTHER), "reuniao_id": str(MEETING)})
    row = world.db.tables[CelulaPresenca][0]
    assert result == str(row.id)
    assert (row.pessoa_id, row.origem) == (OTHER, "lider")
    world.human_spy.assert_called_once()


def test_execution_rejects_already_passed_own_meeting_without_write(world):
    world.event.data, world.event.hora = dt.date(2029, 12, 31), "20:00"
    with pytest.raises(HTTPException) as caught:
        catalog.execute_catalog_action(world.db, world.context, "marcar_presenca",
                                       {"pessoa_id": str(PERSON), "reuniao_id": str(MEETING)})
    assert caught.value.status_code == 409
    assert not world.db.tables[CelulaPresenca]


def test_structural_claims_do_not_replace_server_owned_privilege_context(world):
    claims = SimpleNamespace(**{item.name: getattr(world.context, item.name) for item in fields(world.context)})
    assert _own_targets(world.db, claims)[1] == []
    with pytest.raises(HTTPException) as caught:
        catalog.execute_catalog_action(world.db, claims, "marcar_presenca",
                                       {"pessoa_id": str(PERSON), "reuniao_id": str(MEETING)})
    assert caught.value.status_code == 403
    world.human_spy.assert_not_called()


def test_fake_scope_controls_return_no_row_for_wrong_tenant_person_or_cell(world):
    # Positive controls for the double, separate from product-query assertions.
    query = select(CelulaMembro).where(CelulaMembro.igreja_id == TENANT,
        CelulaMembro.pessoa_id == PERSON, CelulaMembro.celula_id == CELL, CelulaMembro.ativo.is_(True))
    assert world.db.execute(query).scalar_one_or_none() is world.member
    for column in (CelulaMembro.igreja_id, CelulaMembro.pessoa_id, CelulaMembro.celula_id):
        assert world.db.execute(query.where(column == OTHER)).scalar_one_or_none() is None
    world.member.ativo = False
    assert world.db.execute(query).scalar_one_or_none() is None
