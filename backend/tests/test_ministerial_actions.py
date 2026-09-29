"""Shared operations leave the transaction to the human/proposal caller."""
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import HTTPException
from app.deps import CurrentUser
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
