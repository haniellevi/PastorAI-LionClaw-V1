"""B4 (decisão de 12/11/2026): regras únicas de opt-out e de visitante por canal."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.domain.consent import OPTOUT_HUMAN_SEND_BLOCKED_DETAIL, outbound_blocked_by_optout
from app.domain.visitor import (
    CANAL_PAINEL, CANAL_WHATSAPP, PAST_MEETING_WHATSAPP_TEXT,
    visitor_referral_meeting_allowed,
)
from app.services.ministerial_actions import register_own_visitor_expectation


def test_optout_blocks_any_outbound():
    assert outbound_blocked_by_optout(True) is True
    assert outbound_blocked_by_optout(False) is False
    assert "opt-out" in OPTOUT_HUMAN_SEND_BLOCKED_DETAIL


@pytest.mark.parametrize(("canal", "passed", "allowed"), [
    (CANAL_PAINEL, True, True),
    (CANAL_PAINEL, False, True),
    (CANAL_WHATSAPP, True, False),
    (CANAL_WHATSAPP, False, True),
    ("sms", False, False),
])
def test_visitor_referral_rule_by_channel(canal, passed, allowed):
    assert visitor_referral_meeting_allowed(canal=canal, meeting_passed=passed) is allowed


def test_visitor_rule_fails_closed_on_non_bool():
    assert visitor_referral_meeting_allowed(canal=CANAL_PAINEL, meeting_passed=None) is False


def test_whatsapp_text_points_to_panel():
    assert "painel" in PAST_MEETING_WHATSAPP_TEXT


@pytest.mark.parametrize(("canal", "expected_actor"), [
    (CANAL_WHATSAPP, None),
    (CANAL_PAINEL, uuid.uuid4()),
])
def test_service_rejects_channel_actor_mismatch(canal, expected_actor):
    user = SimpleNamespace(igreja_id=str(uuid.uuid4()), app_user_id=str(uuid.uuid4()))
    with pytest.raises(HTTPException) as error:
        register_own_visitor_expectation(
            object(), user, reuniao_id=uuid.uuid4(), nome_visitante="Visitante",
            expected_actor_pessoa_id=expected_actor, canal=canal,
        )
    assert error.value.status_code == 403
