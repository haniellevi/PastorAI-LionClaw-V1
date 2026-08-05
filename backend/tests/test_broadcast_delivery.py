"""Unit coverage for scheduling, retry quarantine, and revalidation."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

import app.services.broadcast_delivery as delivery
from app.services.evolution import BroadcastSendResult

UTC = dt.timezone.utc


def test_schedule_accepts_2359_and_uses_sao_paulo() -> None:
    instant = delivery.scheduled_instant(dt.date(2026, 8, 5), "23:59")
    assert instant == dt.datetime(2026, 8, 6, 2, 59, tzinfo=UTC)
    assert delivery.nominal_slot(instant) == (dt.date(2026, 8, 5), "23:59")


@pytest.mark.parametrize("hour", ["24:00", "09:60", "9:00", "abc"])
def test_schedule_rejects_invalid_hour(hour) -> None:
    with pytest.raises(ValueError):
        delivery.scheduled_instant(dt.date(2026, 8, 5), hour)


def test_schedule_without_hour_defaults_to_midnight() -> None:
    instant = delivery.scheduled_instant(dt.date(2026, 8, 5), None)
    assert delivery.nominal_slot(instant) == (dt.date(2026, 8, 5), "00:00")
    assert delivery.nominal_slot(
        delivery.scheduled_instant(dt.date(2026, 8, 5), "")
    ) == (dt.date(2026, 8, 5), "00:00")


def test_daily_recurrence_skips_missed_slots_without_catchup() -> None:
    current = delivery.scheduled_instant(dt.date(2026, 8, 1), "09:00")
    now = delivery.scheduled_instant(dt.date(2026, 8, 5), "12:00")

    following = delivery.next_occurrence(current, "daily", now=now)

    assert following is not None
    assert delivery.nominal_slot(following) == (dt.date(2026, 8, 6), "09:00")


def test_weekly_and_biweekly_skip_forward() -> None:
    current = delivery.scheduled_instant(dt.date(2026, 7, 1), "19:30")
    now = delivery.scheduled_instant(dt.date(2026, 8, 5), "20:00")

    weekly = delivery.next_occurrence(current, "weekly", now=now)
    biweekly = delivery.next_occurrence(current, "biweekly", now=now)

    assert weekly is not None and delivery.nominal_slot(weekly) == (
        dt.date(2026, 8, 12),
        "19:30",
    )
    assert biweekly is not None and delivery.nominal_slot(biweekly) == (
        dt.date(2026, 8, 12),
        "19:30",
    )


def test_monthly_preserves_day_31_with_calendar_monthrange() -> None:
    january = delivery.scheduled_instant(dt.date(2027, 1, 31), "10:00")
    february = delivery.next_occurrence(
        january,
        "monthly",
        now=delivery.scheduled_instant(dt.date(2027, 2, 1), "00:00"),
        anchor_day=31,
    )
    assert february is not None
    assert delivery.nominal_slot(february) == (dt.date(2027, 2, 28), "10:00")

    march = delivery.next_occurrence(
        february,
        "monthly",
        now=delivery.scheduled_instant(dt.date(2027, 3, 1), "00:00"),
        anchor_day=31,
    )
    assert march is not None
    assert delivery.nominal_slot(march) == (dt.date(2027, 3, 31), "10:00")


def test_monthly_uses_february_29_in_leap_year() -> None:
    january = delivery.scheduled_instant(dt.date(2028, 1, 31), "10:00")
    following = delivery.next_occurrence(
        january,
        "monthly",
        now=delivery.scheduled_instant(dt.date(2028, 2, 1), "00:00"),
        anchor_day=31,
    )
    assert following is not None
    assert delivery.nominal_slot(following) == (dt.date(2028, 2, 29), "10:00")


def test_once_has_no_following_occurrence() -> None:
    current = delivery.scheduled_instant(dt.date(2026, 8, 5), "10:00")
    assert delivery.next_occurrence(current, "once", now=current) is None
    assert delivery.next_occurrence(current, None, now=current) is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"arquivada_em": dt.datetime.now(UTC)}, "pessoa_arquivada"),
        ({"consentimento": False}, "sem_consentimento"),
        ({"optout": True}, "optout"),
        ({"telefone": "sem telefone"}, "telefone_invalido"),
    ],
)
def test_recipient_is_revalidated_before_every_attempt(overrides, reason) -> None:
    values = {
        "arquivada_em": None,
        "consentimento": True,
        "optout": False,
        "telefone": "+55 (11) 99999-0000",
    }
    values.update(overrides)
    phone, actual_reason = delivery.recipient_delivery_phone(SimpleNamespace(**values))
    assert phone is None
    assert actual_reason == reason


def test_valid_recipient_phone_is_digits_only() -> None:
    person = SimpleNamespace(
        arquivada_em=None,
        consentimento=True,
        optout=False,
        telefone="+55 (11) 99999-0000",
    )
    assert delivery.recipient_delivery_phone(person) == ("5511999990000", None)


def test_phone_change_after_materialization_is_suppressed() -> None:
    person = SimpleNamespace(
        arquivada_em=None,
        consentimento=True,
        optout=False,
        telefone="5511888880000",
    )
    assert delivery.recipient_phone_for_delivery(
        person, snapshot_phone="5511999990000"
    ) == (None, "telefone_alterado")


class _ScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one(self):
        return self.value

    def all(self):
        return self.value


class _FinalizeSession:
    def __init__(self, *, remaining: int) -> None:
        self.remaining = remaining
        self.broadcast_id = uuid.uuid4()
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _ScalarResult(self.remaining)
        if len(self.statements) == 2:
            return _ScalarResult(self.broadcast_id)
        return None


def test_once_is_marked_sent_only_when_execution_is_done() -> None:
    session = _FinalizeSession(remaining=0)

    assert delivery._finalize_execution_if_done(
        session,
        uuid.uuid4(),
        now=dt.datetime(2026, 8, 5, tzinfo=UTC),
    ) is True

    assert len(session.statements) == 4
    final_update = str(session.statements[-1])
    assert "UPDATE broadcasts SET status=" in final_update
    assert "broadcasts.proxima_execucao IS NULL" in final_update


def test_open_execution_does_not_mark_broadcast_sent() -> None:
    session = _FinalizeSession(remaining=1)

    assert delivery._finalize_execution_if_done(
        session,
        uuid.uuid4(),
        now=dt.datetime(2026, 8, 5, tzinfo=UTC),
    ) is False
    assert len(session.statements) == 1


def test_terminal_result_never_calls_failures_sent() -> None:
    assert delivery.execution_result_status({"aceito": 2}) == "enviado"
    assert delivery.execution_result_status(
        {"aceito": 1, "falhou_permanente": 1}
    ) == "parcial"
    assert delivery.execution_result_status({"desconhecido": 2}) == "desconhecido"
    assert delivery.execution_result_status({"falhou_permanente": 2}) == "falhou"
    assert delivery.execution_result_status({"suprimido": 2}) == "suprimido"
    assert delivery.execution_result_status({}) == "concluido_sem_destinatarios"


def test_retry_delay_is_exponential_and_honors_provider_floor() -> None:
    assert delivery.retry_delay_seconds(1) == 30
    assert delivery.retry_delay_seconds(2) == 60
    assert delivery.retry_delay_seconds(3, 300) == 300
    assert delivery.retry_delay_seconds(3, 3600) == 3600
    assert delivery.retry_delay_seconds(99) == 1800


class _SequenceEvolution:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def send_text_classificado(self, instance, phone, message):
        self.calls += 1
        return self.outcomes.pop(0)


def _install_in_memory_dispatch(monkeypatch):
    igreja_id = uuid.uuid4()
    state = {"status": "pendente", "attempts": 0}
    claim = delivery.DeliveryClaim(
        igreja_id=igreja_id,
        entrega_id=uuid.uuid4(),
        execucao_id=uuid.uuid4(),
        instance="igreja-1",
        telefone="5511999990000",
        mensagem="aviso",
    )

    monkeypatch.setattr(
        delivery, "_discover_delivery_tenants", lambda _factory: [igreja_id]
    )

    def claim_next(*args, max_attempts, **kwargs):
        if state["status"] not in {"pendente", "falhou_retentavel"}:
            return delivery.ClaimDecision()
        if state["attempts"] >= max_attempts:
            state["status"] = "falhou_permanente"
            return delivery.ClaimDecision(progressed=True)
        state["status"] = "em_envio"
        state["attempts"] += 1
        return delivery.ClaimDecision(claim=claim, progressed=True)

    def record(_factory, _claim, result, *, max_attempts, **kwargs):
        state["status"] = result.status
        if result.status == "falhou_retentavel" and state["attempts"] >= max_attempts:
            state["status"] = "falhou_permanente"
        return True

    monkeypatch.setattr(delivery, "_claim_next_delivery", claim_next)
    monkeypatch.setattr(delivery, "_record_delivery_result", record)
    return state


def test_proven_pre_send_failure_is_retried(monkeypatch) -> None:
    state = _install_in_memory_dispatch(monkeypatch)
    evolution = _SequenceEvolution(
        [
            BroadcastSendResult("falhou_retentavel", "connect_error"),
            BroadcastSendResult("aceito"),
        ]
    )

    actions = delivery.dispatch_pending_deliveries(
        lambda: None,
        evolution,
        now=dt.datetime(2026, 8, 5, tzinfo=UTC),
        worker_id="worker-1",
        limit=5,
        send_interval_ms=0,
    )

    assert actions == 2
    assert evolution.calls == 2
    assert state["status"] == "aceito"


def test_ambiguous_result_is_never_retried(monkeypatch) -> None:
    state = _install_in_memory_dispatch(monkeypatch)
    evolution = _SequenceEvolution(
        [BroadcastSendResult("desconhecido", "read_timeout")]
    )

    actions = delivery.dispatch_pending_deliveries(
        lambda: None,
        evolution,
        now=dt.datetime(2026, 8, 5, tzinfo=UTC),
        worker_id="worker-1",
        limit=5,
        send_interval_ms=0,
    )

    assert actions == 1
    assert evolution.calls == 1
    assert state["status"] == "desconhecido"


def test_optout_between_safe_failure_and_retry_suppresses(monkeypatch) -> None:
    igreja_id = uuid.uuid4()
    state = {"status": "pendente", "attempts": 0}
    person = SimpleNamespace(
        arquivada_em=None,
        consentimento=True,
        optout=False,
        telefone="5511999990000",
    )
    claim = delivery.DeliveryClaim(
        igreja_id=igreja_id,
        entrega_id=uuid.uuid4(),
        execucao_id=uuid.uuid4(),
        instance="igreja-1",
        telefone="5511999990000",
        mensagem="aviso",
    )
    monkeypatch.setattr(
        delivery, "_discover_delivery_tenants", lambda _factory: [igreja_id]
    )

    def claim_next(*args, **kwargs):
        if state["status"] not in {"pendente", "falhou_retentavel"}:
            return delivery.ClaimDecision()
        phone, _reason = delivery.recipient_delivery_phone(person)
        if phone is None:
            state["status"] = "suprimido"
            return delivery.ClaimDecision(progressed=True)
        state["status"] = "em_envio"
        state["attempts"] += 1
        return delivery.ClaimDecision(claim=claim, progressed=True)

    def record(*args, **kwargs):
        state["status"] = "falhou_retentavel"
        person.optout = True
        return True

    monkeypatch.setattr(delivery, "_claim_next_delivery", claim_next)
    monkeypatch.setattr(delivery, "_record_delivery_result", record)
    evolution = _SequenceEvolution(
        [BroadcastSendResult("falhou_retentavel", "connect_error")]
    )

    actions = delivery.dispatch_pending_deliveries(
        lambda: None,
        evolution,
        now=dt.datetime(2026, 8, 5, tzinfo=UTC),
        worker_id="worker-1",
        limit=5,
        send_interval_ms=0,
    )

    assert actions == 2  # one network attempt + one suppression transition
    assert evolution.calls == 1
    assert state["status"] == "suprimido"


def test_reaper_has_independent_cross_tenant_discovery(monkeypatch) -> None:
    igreja_id = uuid.uuid4()
    calls: list[uuid.UUID] = []

    class Session:
        info: dict = {}

        def close(self):
            pass

        def rollback(self):  # pragma: no cover - only on failure
            pass

    monkeypatch.setattr(
        delivery,
        "_discover_orphan_tenants",
        lambda _factory, now: [igreja_id],
    )
    monkeypatch.setattr(delivery, "mark_tenant_scoped", lambda *args, **kwargs: None)

    def reap(_session, church, **kwargs):
        calls.append(church)
        return 1

    monkeypatch.setattr(delivery, "_reap_tenant_deliveries", reap)

    assert delivery.reap_orphaned_deliveries(
        Session,
        now=dt.datetime(2026, 8, 5, tzinfo=UTC),
    ) == 1
    assert calls == [igreja_id]
