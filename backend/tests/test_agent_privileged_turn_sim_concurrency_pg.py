"""Concurrent confirmation proofs over the integrated S3 worker fixture.

Imports real worker fixtures; all database state is disposable and providers are fakes.
"""

from __future__ import annotations

import threading

import pytest

from tests.test_agent_privileged_turn_pg import (
    _ClassifiedEvolution, _effect_count, _fake_choices, _inbound, _rows,
    s3_turn, msg_engine_fx, rls_database_url,
)

from app.db.models import AgentActionProposal, AgentActionReceipt
from app.services import agent_privilege_catalog as catalog
from app.workers import queue_worker as worker_module


pytestmark = pytest.mark.rls_integration


def _join(*threads: threading.Thread) -> None:
    for thread in threads:
        thread.join(timeout=8)
        assert not thread.is_alive(), "thread de confirmação não terminou"


def _run_two_confirmations_concurrently(s3_turn, evolution, first, second):
    """Run independently persisted affirmative anchors at the same instant."""

    start = threading.Barrier(3)
    results: list[object] = []
    failures: list[BaseException] = []
    result_lock = threading.Lock()

    def invoke(outcome) -> None:
        try:
            start.wait(timeout=5)
            result = worker_module.run_agent_for_message(
                s3_turn.factory,
                outcome,
                evolution_client=evolution,
            )
        except BaseException as exc:  # asserted by the rollback proof below
            with result_lock:
                failures.append(exc)
        else:
            with result_lock:
                results.append(result)

    first_thread = threading.Thread(target=invoke, args=(first,), daemon=True)
    second_thread = threading.Thread(target=invoke, args=(second,), daemon=True)
    first_thread.start()
    second_thread.start()
    start.wait(timeout=5)
    _join(first_thread, second_thread)
    return results, failures


def test_two_persisted_sim_confirmations_execute_one_action_once(s3_turn, monkeypatch):
    """Two different inbound ``SIM`` rows cannot execute or route twice."""

    calls = _fake_choices(monkeypatch, s3_turn, "registrar_decisao")
    evolution = _ClassifiedEvolution()
    request = _inbound(s3_turn, "S3-SIM-RACE-REQUEST", "Pedido sintético")
    worker_module.run_agent_for_message(
        s3_turn.factory, request, evolution_client=evolution
    )
    assert _rows(s3_turn, AgentActionProposal)[0].state == "pendente"

    first = _inbound(s3_turn, "S3-SIM-RACE-ONE", "SIM")
    second = _inbound(s3_turn, "S3-SIM-RACE-TWO", "SIM")
    assert first.inbound_message_id != second.inbound_message_id

    results, failures = _run_two_confirmations_concurrently(
        s3_turn, evolution, first, second
    )

    assert failures == []
    assert len(results) == 2
    assert _effect_count(s3_turn, "registrar_decisao") == 1
    proposals = _rows(s3_turn, AgentActionProposal)
    receipts = _rows(s3_turn, AgentActionReceipt)
    assert len(proposals) == 1
    assert proposals[0].state == "executada"
    assert proposals[0].confirmation_message_id in {
        first.inbound_message_id,
        second.inbound_message_id,
    }
    assert len(receipts) == 1
    assert receipts[0].confirmation_message_id == proposals[0].confirmation_message_id
    # A competing confirmation is consumed by the proposal boundary, never
    # re-routed into a second action proposal.
    assert calls == ["s3_route", "s3_tool", "s3_handle"]
    assert len(evolution.calls) == 2

    for outcome in (first, second):
        worker_module.run_agent_for_message(
            s3_turn.factory, outcome, evolution_client=evolution
        )
    assert _effect_count(s3_turn, "registrar_decisao") == 1
    assert len(_rows(s3_turn, AgentActionReceipt)) == 1
    assert len(_rows(s3_turn, AgentActionProposal)) == 1
    assert calls == ["s3_route", "s3_tool", "s3_handle"]
    assert len(evolution.calls) == 2


def test_failed_confirmation_transaction_rolls_back_before_competing_sim_executes(
    s3_turn, monkeypatch
):
    """A failed callback rolls back its effect; the competing SIM may win once."""

    _fake_choices(monkeypatch, s3_turn, "marcar_presenca")
    evolution = _ClassifiedEvolution()
    request = _inbound(s3_turn, "S3-SIM-ROLLBACK-REQUEST", "Pedido sintético")
    worker_module.run_agent_for_message(
        s3_turn.factory, request, evolution_client=evolution
    )
    assert _rows(s3_turn, AgentActionProposal)[0].state == "pendente"

    first = _inbound(s3_turn, "S3-SIM-ROLLBACK-ONE", "SIM")
    second = _inbound(s3_turn, "S3-SIM-ROLLBACK-TWO", "SIM")
    original = catalog.execute_catalog_action
    entered_callback = threading.Event()
    release_failure = threading.Event()
    calls_lock = threading.Lock()
    attempts = 0

    def fail_first(*args, **kwargs):
        nonlocal attempts
        with calls_lock:
            attempts += 1
            attempt = attempts
        result = original(*args, **kwargs)
        if attempt == 1:
            entered_callback.set()
            assert release_failure.wait(timeout=5), "segunda confirmação não foi iniciada"
            raise RuntimeError("falha sintética após efeito pendente")
        return result

    monkeypatch.setattr(catalog, "execute_catalog_action", fail_first)

    results: list[object] = []
    failures: list[BaseException] = []
    lock = threading.Lock()

    def invoke(outcome, *, started: threading.Event | None = None) -> None:
        if started is not None:
            started.set()
        try:
            result = worker_module.run_agent_for_message(
                s3_turn.factory, outcome, evolution_client=evolution
            )
        except BaseException as exc:
            with lock:
                failures.append(exc)
        else:
            with lock:
                results.append(result)

    first_thread = threading.Thread(target=invoke, args=(first,), daemon=True)
    first_thread.start()
    assert entered_callback.wait(timeout=5), "primeira confirmação não entrou no callback"
    second_started = threading.Event()
    second_thread = threading.Thread(
        target=invoke, args=(second,), kwargs={"started": second_started}, daemon=True
    )
    second_thread.start()
    assert second_started.wait(timeout=5)
    release_failure.set()
    _join(first_thread, second_thread)

    assert len(results) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], RuntimeError)
    assert attempts == 2
    assert _effect_count(s3_turn, "marcar_presenca") == 1
    proposals = _rows(s3_turn, AgentActionProposal)
    receipts = _rows(s3_turn, AgentActionReceipt)
    assert len(proposals) == 1
    assert proposals[0].state == "executada"
    assert len(receipts) == 1
    assert receipts[0].confirmation_message_id == second.inbound_message_id
    assert len(evolution.calls) == 2

    worker_module.run_agent_for_message(
        s3_turn.factory, first, evolution_client=evolution
    )
    assert _effect_count(s3_turn, "marcar_presenca") == 1
    assert len(_rows(s3_turn, AgentActionReceipt)) == 1
    assert len(evolution.calls) == 2
