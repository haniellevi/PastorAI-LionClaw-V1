"""Shared operations leave the transaction to the human/proposal caller.

R2 doubles inspect scoped SELECTs and requested locks, not PG serialization,
RLS, uniqueness races or rollback. Only the Orchestrator executes these tests.
"""
import datetime as dt
from inspect import signature
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BinaryExpression, BindParameter, BooleanClauseList, True_
from app.db.models import AppUser, Celula, CelulaMembro, CelulaPresenca, CelulaReuniao
from app.deps import CurrentUser
from app.domain import cell_meetings_schedule as schedule
from app.services import ministerial_actions as human
from app.services.ministerial_actions import confirm_meeting_attendance, register_decision

TENANT = UUID(int=1)
PERSON = UUID(int=2)
MEETING = UUID(int=3)
CELL = UUID(int=4)


def actor(role='pastor'):
    return CurrentUser(app_user_id=str(UUID(int=5)), clerk_user_id='synthetic',
                       igreja_id=str(TENANT), email='', nome='', roles=frozenset({role}))


def rows(*values):
    db = MagicMock()
    db.execute.side_effect = [SimpleNamespace(scalar_one_or_none=lambda value=value: value)
                              for value in values]
    return db


def test_decision_cell_leader_cannot_gain_consolidation_authority():
    db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        register_decision(db, actor('lider_celula'), pessoa_id=PERSON, vinculo='visitante')
    assert exc.value.status_code == 403
    db.add.assert_not_called()


def test_decision_missing_tenant_person_fails_before_write():
    db = rows(None)
    with pytest.raises(HTTPException) as exc:
        register_decision(db, actor(), pessoa_id=PERSON, vinculo='visitante')
    assert exc.value.status_code == 404
    assert 'pessoas.igreja_id' in str(db.execute.call_args.args[0])
    db.add.assert_not_called()


def test_decision_does_not_commit_proposal_before_receipt_intent():
    person = SimpleNamespace(id=PERSON, aceitou_jesus=False)
    consolidation = SimpleNamespace(id=UUID(int=6))
    db = rows(person, consolidation)
    assert register_decision(db, actor(), pessoa_id=PERSON, vinculo='visitante') is consolidation
    assert person.aceitou_jesus
    db.commit.assert_not_called()
    query = str(db.execute.call_args.args[0].whereclause)
    assert 'consolidacoes.igreja_id' in query
    assert 'consolidacoes.origin_decision_id' in query
    assert 'consolidacoes.pessoa_id' not in query


def test_presence_requires_membership_in_exact_meeting_cell():
    meeting = SimpleNamespace(id=MEETING, celula_id=CELL)
    cell = SimpleNamespace(id=CELL, igreja_id=TENANT, lider_id=UUID(int=9))
    db = rows(meeting, UUID(int=10), cell, SimpleNamespace(id=PERSON), None)
    with pytest.raises(HTTPException) as exc:
        confirm_meeting_attendance(db, actor(), reuniao_id=MEETING, pessoa_id=PERSON)
    assert exc.value.status_code == 403
    statement = str(db.execute.call_args.args[0])
    assert 'celula_membro.igreja_id' in statement
    assert 'celula_membro.celula_id' in statement
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.fixture
def own_presence_db(monkeypatch):
    now = dt.datetime(2030, 1, 1, 1, 0, tzinfo=dt.timezone.utc)
    state = SimpleNamespace(now=now, statements=[], before_presence_read=None)
    state.user = SimpleNamespace(id=UUID(int=5), igreja_id=TENANT, pessoa_id=PERSON)
    state.meeting = SimpleNamespace(id=MEETING, igreja_id=TENANT, celula_id=CELL,
                                   data=dt.date(2029, 12, 31), hora="22:00")
    state.cell = SimpleNamespace(id=CELL, igreja_id=TENANT, ativo=True, lider_id=UUID(int=9))
    state.member = SimpleNamespace(id=UUID(int=8), igreja_id=TENANT,
                                   celula_id=CELL, pessoa_id=PERSON, ativo=True)
    state.attendance = None
    db = state.db = MagicMock()

    def clock(now=None):
        return (state.now if now is None else now).astimezone(schedule.SAO_PAULO_TZ)

    class FrozenDateTime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return state.now.astimezone(tz) if tz else state.now.replace(tzinfo=None)

    monkeypatch.setattr(schedule, "now_in_sao_paulo", clock)
    monkeypatch.setattr(human, "dt", SimpleNamespace(datetime=FrozenDateTime, timezone=dt.timezone))

    def matches(expression, row):
        if isinstance(expression, BooleanClauseList):
            assert expression.operator is operators.and_
            return all(matches(clause, row) for clause in expression.clauses)
        assert isinstance(expression, BinaryExpression)
        assert expression.operator in (operators.eq, operators.is_)
        expected = expression.right.value if isinstance(expression.right, BindParameter) else True
        assert isinstance(expression.right, (BindParameter, True_))
        return getattr(row, expression.left.key) == expected

    def execute(statement):
        state.statements.append(statement)
        description = statement.column_descriptions[0]
        model = description["entity"]
        mapping = {AppUser: state.user, CelulaReuniao: state.meeting,
                   Celula: state.cell, CelulaMembro: state.member, CelulaPresenca: state.attendance}
        assert model in mapping, "unexpected own-presence SELECT"
        if model is CelulaPresenca and state.before_presence_read is not None:
            state.before_presence_read()
        row = mapping[model]
        if row is not None and not matches(statement.whereclause, row):
            row = None
        value = row if row is None or description["expr"] is model else getattr(row, description["expr"].key)
        return SimpleNamespace(scalar_one_or_none=lambda: value)

    db.execute.side_effect = execute
    return state


def _strong_own(state, **overrides):
    # Missing internal parameter is an explicit RED assertion, not a TypeError
    # collection/runtime error. No substitute implementation is exercised.
    assert "expected_actor_pessoa_id" in signature(confirm_meeting_attendance).parameters, \
        "strengthened own-WhatsApp service contract is absent"
    kwargs = dict(reuniao_id=MEETING, pessoa_id=None, expected_actor_pessoa_id=PERSON)
    kwargs.update(overrides)
    return confirm_meeting_attendance(state.db, actor('membro'), **kwargs)


def _assert_scoped_lock(statement, model, **expected):
    assert statement.column_descriptions[0]["entity"] is model
    assert statement._for_update_arg is not None, "scoped row lock was not requested"
    predicates = [node for node in visitors.iterate(statement.whereclause)
                  if isinstance(node, BinaryExpression)]
    for key, value in expected.items():
        assert any(getattr(node.left, "table", None) is not None
                   and node.left.table.name == model.__table__.name and node.left.key == key
                   and node.operator is (operators.is_ if key == 'ativo' else operators.eq)
                   and ((isinstance(node.right, BindParameter) and type(node.right.value) is type(value)
                         and node.right.value == value)
                        or (value is True and isinstance(node.right, True_))) for node in predicates), \
            "required tenant/identity/active predicate is absent"


def test_strengthened_own_requests_exact_scoped_locks_in_domain_order(own_presence_db):
    state = own_presence_db
    attendance = _strong_own(state)
    assert (attendance.igreja_id, attendance.reuniao_id, attendance.pessoa_id,
            attendance.estado, attendance.origem) == (TENANT, MEETING, PERSON, 'confirmada', 'auto')
    assert len(state.statements) == 5
    for statement, model, keys in zip(state.statements,
            (AppUser, CelulaReuniao, Celula, CelulaMembro, CelulaPresenca),
            (dict(id=UUID(int=5), igreja_id=TENANT), dict(id=MEETING, igreja_id=TENANT),
             dict(id=CELL, igreja_id=TENANT, ativo=True),
             dict(igreja_id=TENANT, celula_id=CELL, pessoa_id=PERSON, ativo=True),
             dict(igreja_id=TENANT, reuniao_id=MEETING, pessoa_id=PERSON))):
        _assert_scoped_lock(statement, model, **keys)
    state.db.add.assert_called_once_with(attendance)
    state.db.commit.assert_not_called()
    state.db.rollback.assert_not_called()


@pytest.mark.parametrize("revocation", ['inactive_cell', 'relink', 'inactive_member', 'missing_member', 'past'])
def test_strengthened_own_rejects_current_revocation_without_effect(own_presence_db, revocation):
    state = own_presence_db
    if revocation == 'inactive_cell':
        state.cell.ativo = False
    elif revocation == 'relink':
        state.user.pessoa_id = UUID(int=9)
    elif revocation == 'inactive_member':
        state.member.ativo = False
    elif revocation == 'missing_member':
        state.member = None
    else:
        state.now += dt.timedelta(seconds=1)
    with pytest.raises(HTTPException) as exc:
        _strong_own(state)
    assert exc.value.status_code in (403, 404, 409)
    state.db.add.assert_not_called()
    state.db.commit.assert_not_called()


@pytest.mark.parametrize("entity", ['user', 'meeting', 'cell', 'member'])
def test_strengthened_own_never_reads_a_cross_tenant_row(own_presence_db, entity):
    state = own_presence_db
    getattr(state, entity).igreja_id = UUID(int=99)
    with pytest.raises(HTTPException) as exc:
        _strong_own(state)
    assert exc.value.status_code in (403, 404, 409)
    state.db.add.assert_not_called()
    state.db.commit.assert_not_called()


def test_expected_actor_does_not_grant_member_authority_to_explicit_third_target(own_presence_db):
    state = own_presence_db
    with pytest.raises(HTTPException) as exc:
        _strong_own(state, pessoa_id=UUID(int=9))
    assert exc.value.status_code in (403, 422)
    state.db.add.assert_not_called()
    state.db.commit.assert_not_called()


@pytest.mark.parametrize("existing", [False, True])
def test_time_is_rechecked_after_presence_lookup_before_insert_or_update(own_presence_db, existing):
    state = own_presence_db
    if existing:
        state.attendance = SimpleNamespace(id=UUID(int=12), igreja_id=TENANT,
            reuniao_id=MEETING, pessoa_id=PERSON, estado='ausente', origem='lider', updated_at=None)
    state.before_presence_read = lambda: setattr(state, 'now', state.now + dt.timedelta(seconds=1))
    with pytest.raises(HTTPException) as exc:
        _strong_own(state)
    assert exc.value.status_code == 409
    state.db.add.assert_not_called()
    state.db.commit.assert_not_called()
    if existing:
        assert (state.attendance.estado, state.attendance.origem, state.attendance.updated_at) == ('ausente', 'lider', None)


@pytest.mark.parametrize("offset,allowed", [(-1, True), (0, True), (1, False)])
def test_strengthened_own_exact_time_equality_has_not_passed_e4(own_presence_db, offset, allowed):
    state = own_presence_db
    state.now += dt.timedelta(seconds=offset)
    if allowed:
        attendance = _strong_own(state)
        assert (attendance.pessoa_id, attendance.origem, attendance.estado) == (PERSON, 'auto', 'confirmada')
    else:
        with pytest.raises(HTTPException) as exc:
            _strong_own(state)
        assert exc.value.status_code == 409
        state.db.add.assert_not_called()
    state.db.commit.assert_not_called()


@pytest.mark.parametrize("explicit_own", [False, True])
def test_legacy_own_human_call_without_internal_parameter_keeps_prior_semantics(own_presence_db, explicit_own):
    state = own_presence_db
    state.meeting.data = dt.date(2029, 12, 30)
    state.cell.ativo = False
    attendance = confirm_meeting_attendance(state.db, actor('membro'),
        reuniao_id=MEETING, pessoa_id=PERSON if explicit_own else None)
    assert (attendance.pessoa_id, attendance.estado, attendance.origem) == (PERSON, 'confirmada', 'auto')
    state.db.commit.assert_not_called()


def test_legacy_pastor_third_party_historical_call_keeps_prior_semantics(monkeypatch):
    meeting = SimpleNamespace(id=MEETING, celula_id=CELL, data=dt.date(2029, 12, 30), hora='20:00')
    cell = SimpleNamespace(id=CELL, igreja_id=TENANT, ativo=False, lider_id=UUID(int=9))
    db = rows(meeting, UUID(int=10), cell, SimpleNamespace(id=PERSON),
              SimpleNamespace(pessoa_id=PERSON), None)
    fixed = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
    class FrozenDateTime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed
    monkeypatch.setattr(human, 'dt', SimpleNamespace(datetime=FrozenDateTime, timezone=dt.timezone))
    attendance = confirm_meeting_attendance(db, actor(), reuniao_id=MEETING, pessoa_id=PERSON)
    assert (attendance.pessoa_id, attendance.estado, attendance.origem) == (PERSON, 'confirmada', 'lider')
    db.commit.assert_not_called()
