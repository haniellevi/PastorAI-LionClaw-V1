"""PG17 proof for public-profile revalidation after Tier A's external wait."""

from __future__ import annotations

import threading
import time
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.agent import runtime
from app.agent.nodes import empty_turn_effects
from app.db.models import AgentConfig, AgentConversationLog, AiUsageLog, LlmCredential
from app.workers import queue_worker
from tests.conftest_rls import rls_database_url  # noqa: F401
from tests.test_messages_inbound_idempotency import (
    _IGREJA_A,
    _agent_outcome,
    _factory,
    _seed_igreja_with_connection,
    _seed_tier_a_handoff_anchor,
    msg_engine_fx,
)

pytestmark = pytest.mark.rls_integration


def _seed_public_plan(
    factory: sessionmaker,
) -> tuple[queue_worker.IngestionOutcome, runtime.AgentTurnPlan, uuid.UUID]:
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA_A, instance="igreja-s2")
    conversation_id, pessoa_id, inbound_message_id = _seed_tier_a_handoff_anchor(
        factory,
        igreja_id=_IGREJA_A,
        provider_message_id="S2-PUBLIC-TIER-A",
        texto="Que horas começa o culto?",
    )
    session = factory()
    try:
        config = AgentConfig(
            igreja_id=_IGREJA_A,
            comportamento="Tom público sintético.",
            ativo=True,
            informacoes_publicas={"horarios_culto": "Sábado, 18:00"},
        )
        credential = LlmCredential(
            igreja_id=_IGREJA_A,
            provedor="synthetic",
            modelo="synthetic",
            api_key_encrypted="synthetic",
            validado=True,
            ativo=True,
        )
        session.add_all((config, credential))
        session.commit()
        outcome = _agent_outcome(
            conversation_id,
            provider_message_id="S2-PUBLIC-TIER-A",
            claim_id="s2-public-tier-a",
            inbound_message_id=inbound_message_id,
        )
        return outcome, runtime.AgentTurnPlan(
            igreja_id=_IGREJA_A,
            conversation_id=conversation_id,
            pessoa_id=pessoa_id,
            inbound_message_id=inbound_message_id,
            provider_message_id="S2-PUBLIC-TIER-A",
            current_text="Que horas começa o culto?",
            tier_a_input_within_limit=True,
            config_id=config.id,
            config_comportamento=config.comportamento,
            credential_id=credential.id,
            credential_provedor=credential.provedor,
            credential_model=credential.modelo,
            credential_key_encrypted=credential.api_key_encrypted,
            accepted_consent_version=None,
            term_version="s2-public-profile",
            effects=empty_turn_effects(),
            draft_response="Horário de culto: Sábado, 18:00.",
            system_prompt="sistema sintético",
            user_prompt="mensagem sintética",
            public_info_reply=True,
        ), config.id
    finally:
        session.close()


def _scope(session, outcome: queue_worker.IngestionOutcome) -> None:
    queue_worker._scope_agent_session(session, outcome)


def _assert_empty_public_audit_and_no_usage(
    factory: sessionmaker,
    outcome: queue_worker.IngestionOutcome,
) -> None:
    session = factory()
    try:
        _scope(session, outcome)
        audit = session.execute(
            select(AgentConversationLog).where(
                AgentConversationLog.igreja_id == _IGREJA_A,
                AgentConversationLog.conversation_id == outcome.conversation_id,
                AgentConversationLog.evento == "agent_public_info_reply",
            )
        ).scalar_one()
        usages = session.execute(
            select(AiUsageLog).where(AiUsageLog.igreja_id == _IGREJA_A)
        ).scalars().all()
    finally:
        session.close()
    assert audit.payload is None
    assert usages == []


def test_public_profile_refreshes_a_stale_identity_map_before_locked_apply(
    msg_engine_fx: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An edit committed before the lock refreshes the same cached config row."""

    factory = _factory(msg_engine_fx)
    outcome, plan, config_id = _seed_public_plan(factory)
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: SimpleNamespace(agent_term_version="s2-public-profile"),
    )

    worker_session = factory()
    editor_session = factory()
    try:
        _scope(worker_session, outcome)
        stale_config = worker_session.execute(
            select(AgentConfig).where(
                AgentConfig.id == config_id,
                AgentConfig.igreja_id == _IGREJA_A,
            )
        ).scalar_one()
        assert stale_config.informacoes_publicas == {"horarios_culto": "Sábado, 18:00"}

        _scope(editor_session, outcome)
        editor_session.execute(
            update(AgentConfig)
            .where(AgentConfig.id == config_id, AgentConfig.igreja_id == _IGREJA_A)
            .values(informacoes_publicas={"horarios_culto": "Domingo, 19:00"})
        )
        editor_session.commit()

        result = runtime.apply_agent_turn_plan(
            worker_session,
            plan=plan,
            response=plan.draft_response,
        )
    finally:
        editor_session.close()
        worker_session.close()

    assert result.response == "Horário de culto: Domingo, 19:00."
    assert stale_config.informacoes_publicas == {"horarios_culto": "Domingo, 19:00"}
    _assert_empty_public_audit_and_no_usage(factory, outcome)


def test_public_profile_lock_serializes_an_edit_started_after_revalidation(
    msg_engine_fx: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A writer beginning after the lock cannot alter that turn's reply."""

    factory = _factory(msg_engine_fx)
    outcome, plan, config_id = _seed_public_plan(factory)
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: SimpleNamespace(agent_term_version="s2-public-profile"),
    )
    original_resolver = runtime.resolve_public_info_reply
    config_locked = threading.Event()
    release_apply = threading.Event()
    editor_started = threading.Event()
    editor_finished = threading.Event()
    errors: list[BaseException] = []
    result_holder: list[runtime.AgentTurnResult] = []
    apply_pid: list[int] = []
    editor_pid: list[int] = []

    def pause_after_lock(current_text: object, public_info: object) -> str | None:
        config_locked.set()
        assert release_apply.wait(timeout=10), "aplicação pública não foi liberada"
        return original_resolver(current_text, public_info)

    monkeypatch.setattr(runtime, "resolve_public_info_reply", pause_after_lock)

    def apply_turn() -> None:
        session = factory()
        try:
            _scope(session, outcome)
            apply_pid.append(
                int(session.execute(text("select pg_backend_pid()")).scalar_one())
            )
            result_holder.append(
                runtime.apply_agent_turn_plan(
                    session,
                    plan=plan,
                    response=plan.draft_response,
                )
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            session.close()

    def edit_profile() -> None:
        session = factory()
        try:
            _scope(session, outcome)
            editor_pid.append(
                int(session.execute(text("select pg_backend_pid()")).scalar_one())
            )
            editor_started.set()
            session.execute(
                update(AgentConfig)
                .where(AgentConfig.id == config_id, AgentConfig.igreja_id == _IGREJA_A)
                .values(informacoes_publicas={"horarios_culto": "Domingo, 19:00"})
            )
            session.commit()
            editor_finished.set()
        except BaseException as exc:
            errors.append(exc)
        finally:
            session.close()

    apply_thread = threading.Thread(target=apply_turn, daemon=True)
    editor_thread = threading.Thread(target=edit_profile, daemon=True)
    try:
        apply_thread.start()
        assert config_locked.wait(timeout=5), "configuração não foi bloqueada"
        editor_thread.start()
        assert editor_started.wait(timeout=5), "editor não iniciou a alteração"
        deadline = time.monotonic() + 5
        blocking_pids: list[int] = []
        while time.monotonic() < deadline:
            with msg_engine_fx.connect() as observer:
                blocking_pids = list(
                    observer.execute(
                        text("select pg_blocking_pids(:editor_pid)"),
                        {"editor_pid": editor_pid[0]},
                    ).scalar_one()
                )
            if apply_pid[0] in blocking_pids:
                break
            time.sleep(0.02)
        assert apply_pid[0] in blocking_pids
        assert not editor_finished.is_set(), "editor concluiu antes da liberação"
    finally:
        release_apply.set()
        apply_thread.join(timeout=10)
        editor_thread.join(timeout=10)

    assert not apply_thread.is_alive() and not editor_thread.is_alive()
    assert not errors
    assert [result.response for result in result_holder] == [
        "Horário de culto: Sábado, 18:00."
    ]
    assert editor_finished.is_set()
    _assert_empty_public_audit_and_no_usage(factory, outcome)

    session = factory()
    try:
        _scope(session, outcome)
        current_profile = session.execute(
            select(AgentConfig.informacoes_publicas).where(
                AgentConfig.id == config_id,
                AgentConfig.igreja_id == _IGREJA_A,
            )
        ).scalar_one()
    finally:
        session.close()
    assert current_profile == {"horarios_culto": "Domingo, 19:00"}
