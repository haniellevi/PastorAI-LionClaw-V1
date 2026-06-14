"""Tests for SLA policy + breach classification (SLA engine — O5).

Pure tests of the deadline math: report 2h, connection 12h, fonovisita 24h, plus
the escalation grace that turns an unanswered charge into an escalation.
"""

from __future__ import annotations

import datetime as dt

from app.domain.sla import (
    SLA_CONNECTION,
    SLA_FONOVISITA,
    SLA_POLICIES,
    SLA_REPORT,
    SlaStatus,
    classify,
    classify_from_start,
    resolve_deadline,
)

_T0 = dt.datetime(2026, 6, 13, 12, 0, tzinfo=dt.timezone.utc)


def _hours(n: float) -> dt.timedelta:
    return dt.timedelta(hours=n)


# ---- policy deadlines -----------------------------------------------------
def test_policies_match_spec_deadlines() -> None:
    assert SLA_POLICIES[SLA_REPORT].deadline_hours == 2
    assert SLA_POLICIES[SLA_CONNECTION].deadline_hours == 12
    assert SLA_POLICIES[SLA_FONOVISITA].deadline_hours == 24


# ---- classify -------------------------------------------------------------
def test_within_deadline_is_ok() -> None:
    policy = SLA_POLICIES[SLA_REPORT]
    deadline = _T0 + _hours(2)
    assert classify(policy=policy, deadline=deadline, now=_T0) is SlaStatus.OK


def test_past_deadline_triggers_cobranca() -> None:
    policy = SLA_POLICIES[SLA_REPORT]
    deadline = _T0  # already due
    now = _T0 + _hours(1)
    assert classify(policy=policy, deadline=deadline, now=now) is SlaStatus.COBRANCA


def test_past_escalation_grace_triggers_escalonamento() -> None:
    policy = SLA_POLICIES[SLA_REPORT]  # grace = 2h after deadline
    deadline = _T0
    now = _T0 + _hours(3)  # past deadline + 2h grace
    assert (
        classify(policy=policy, deadline=deadline, now=now)
        is SlaStatus.ESCALONAMENTO
    )


def test_classify_from_start_uses_policy_window() -> None:
    policy = SLA_POLICIES[SLA_CONNECTION]  # 12h deadline
    # 13h after start: past the 12h deadline but within the 12h escalation grace.
    now = _T0 + _hours(13)
    assert (
        classify_from_start(policy=policy, started_at=_T0, now=now)
        is SlaStatus.COBRANCA
    )


# ---- resolve_deadline -----------------------------------------------------
def test_resolve_deadline_prefers_explicit_prazo() -> None:
    policy = SLA_POLICIES[SLA_FONOVISITA]
    prazo = _T0 + _hours(5)
    resolved = resolve_deadline(policy=policy, prazo=prazo, created_at=_T0, now=_T0)
    assert resolved == prazo


def test_resolve_deadline_derives_from_created_at_when_no_prazo() -> None:
    policy = SLA_POLICIES[SLA_FONOVISITA]  # 24h
    resolved = resolve_deadline(policy=policy, prazo=None, created_at=_T0, now=_T0)
    assert resolved == _T0 + _hours(24)


def test_resolve_deadline_treats_missing_timestamps_as_due_now() -> None:
    policy = SLA_POLICIES[SLA_REPORT]
    resolved = resolve_deadline(policy=policy, prazo=None, created_at=None, now=_T0)
    assert resolved == _T0


def test_naive_datetimes_are_compared_safely() -> None:
    policy = SLA_POLICIES[SLA_REPORT]
    naive_deadline = dt.datetime(2026, 6, 13, 12, 0)  # no tzinfo
    now = _T0 + _hours(1)
    assert classify(policy=policy, deadline=naive_deadline, now=now) is SlaStatus.COBRANCA
