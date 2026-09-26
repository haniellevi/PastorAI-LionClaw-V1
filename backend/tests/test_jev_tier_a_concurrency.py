"""PostgreSQL proof that a delayed Tier A reply cannot outlive a human handoff."""

from __future__ import annotations

import threading
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from app.agent import runtime as runtime_module
from app.db.models import AgentConfig, Conversation, LlmCredential, Message
from app.services import semantic_triage
from app.workers import queue_worker as worker_module
from tests.conftest_rls import rls_database_url  # noqa: F401 - fixture dependency
from tests.test_messages_inbound_idempotency import (
    _ClassifiedEvolution,
    _IGREJA_A,
    _agent_outcome,
    _factory,
    _seed_igreja_with_connection,
    _seed_tier_a_handoff_anchor,
    msg_engine_fx,
)

pytestmark = pytest.mark.rls_integration


def test_handoff_and_ia_release_fence_older_llm_turn(
    msg_engine_fx: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B's committed handoff must defeat A even after an operator resumes IA."""

    factory = _factory(msg_engine_fx)
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA_A, instance="igreja-1")
    conversation_id, pessoa_id, inbound_a_id = _seed_tier_a_handoff_anchor(
        factory,
        igreja_id=_IGREJA_A,
        provider_message_id="TIER-A-RACE-A",
        texto="entrada A sintética",
    )
    session = factory()
    try:
        inbound_b = Message(
            igreja_id=_IGREJA_A,
            conversation_id=conversation_id,
            direcao="in",
            autor="contato",
            texto="entrada B sintética",
            tipo="texto",
            provider_message_id="TIER-A-RACE-B",
        )
        config = AgentConfig(
            igreja_id=_IGREJA_A, comportamento="perfil sintético", ativo=True
        )
        credential = LlmCredential(
            igreja_id=_IGREJA_A,
            provedor="synthetic",
            modelo="synthetic",
            api_key_encrypted="synthetic",
            validado=True,
            ativo=True,
        )
        session.add_all([inbound_b, config, credential])
        session.commit()
        inbound_b_id = inbound_b.id
        config_id = config.id
        credential_id = credential.id
    finally:
        session.close()

    def preflight(inbound_id: uuid.UUID, provider_id: str, text: str):
        return runtime_module.TierATurnPreflight(
            igreja_id=_IGREJA_A,
            conversation_id=conversation_id,
            pessoa_id=pessoa_id,
            inbound_message_id=inbound_id,
            provider_message_id=provider_id,
            current_text=text,
            tier_a_input_within_limit=True,
            config_id=config_id,
            config_comportamento="perfil sintético",
            credential_id=credential_id,
            credential_provedor="synthetic",
            credential_model="synthetic",
            credential_key_encrypted="synthetic",
            accepted_consent_version=None,
            term_version="test-v1",
        )

    plan_a = runtime_module.AgentTurnPlan(
        **vars(preflight(inbound_a_id, "TIER-A-RACE-A", "entrada A sintética")),
        effects={
            "events": [],
            "tool_calls": [],
            "apply_optout": False,
            "apply_consent_version": None,
            "intake_update": {},
        },
        draft_response="rascunho sintético",
        system_prompt="sistema sintético",
        user_prompt="entrada A sintética",
    )
    plan_b = preflight(inbound_b_id, "TIER-A-RACE-B", "entrada B sintética")
    outcome_a = _agent_outcome(
        conversation_id,
        provider_message_id="TIER-A-RACE-A",
        claim_id="tier-a-race-a",
        inbound_message_id=inbound_a_id,
    )
    outcome_b = _agent_outcome(
        conversation_id,
        provider_message_id="TIER-A-RACE-B",
        claim_id="tier-a-race-b",
        inbound_message_id=inbound_b_id,
    )
    reply_key_a = worker_module._agent_reply_idempotency_key(outcome_a)
    assert reply_key_a is not None

    def process(_session, **kwargs):
        if kwargs.get("tier_a_preflight"):
            return runtime_module.AgentTurnResult(handled=True, preflight=plan_a)
        assert kwargs.get("defer_onboarding_plan")
        return runtime_module.AgentTurnResult(handled=True, plan=plan_a)

    entered_llm = threading.Event()
    release_llm = threading.Event()
    handoff_committed = threading.Event()
    ia_released = threading.Event()
    errors: list[BaseException] = []
    dispositions: list[worker_module.AgentRunDisposition] = []
    evolution = _ClassifiedEvolution("aceito")

    def blocked_llm(_plan, *, timeout_seconds):
        assert timeout_seconds > 0
        entered_llm.set()
        assert release_llm.wait(timeout=10), "LLM sintético não foi liberado"
        return SimpleNamespace(
            handoff=False, resposta="resposta tardia de A", usage=None
        )

    monkeypatch.setattr(runtime_module, "process_inbound_message", process)
    monkeypatch.setattr(runtime_module, "reply_tier_a_plan_with_llm", blocked_llm)
    monkeypatch.setattr(
        runtime_module,
        "get_settings",
        lambda: SimpleNamespace(agent_term_version="test-v1"),
    )
    monkeypatch.setattr(
        worker_module,
        "get_settings",
        lambda: SimpleNamespace(agent_trusted_inbound_identity_enabled=False),
    )
    monkeypatch.setattr(worker_module, "_whatsapp_reply_enabled", lambda _id: True)
    monkeypatch.setattr(semantic_triage, "tier_a_enabled_from_environment", lambda _id: True)
    monkeypatch.setattr(semantic_triage, "tier_a_egress_allowed", lambda *_a, **_k: True)
    monkeypatch.setattr(worker_module, "_tier_a_effective_settings", lambda *_a: object())
    monkeypatch.setattr(
        worker_module,
        "_run_tier_a_batch",
        lambda *_a: semantic_triage.TierADecision(
            risco_crise=False,
            pede_humano=False,
            pede_optout=False,
            handoff=False,
            erro=None,
            latencia_ms=1,
        ),
    )

    def run_a() -> None:
        try:
            dispositions.append(
                worker_module.run_agent_for_message(
                    factory, outcome_a, evolution_client=evolution
                )
            )
        except BaseException as exc:  # surface failures from the worker thread
            errors.append(exc)

    def handoff_b_then_release_ia() -> None:
        try:
            session = factory()
            try:
                worker_module._scope_agent_session(session, outcome_b)
                result = runtime_module.persist_tier_a_handoff(
                    session,
                    plan=plan_b,
                    decision_payload={
                        "risco_crise": False,
                        "pede_humano": True,
                        "pede_optout": False,
                        "handoff": True,
                        "erro": None,
                        "latencia_ms": 1,
                    },
                    reply_provider_message_id=worker_module._agent_reply_idempotency_key(
                        outcome_b
                    ),
                )
                assert result.handled and result.suppressed
            finally:
                session.close()
            handoff_committed.set()

            session = factory()
            try:
                worker_module._scope_agent_session(session, outcome_b)
                session.execute(
                    update(Conversation)
                    .where(
                        Conversation.id == conversation_id,
                        Conversation.igreja_id == _IGREJA_A,
                    )
                    .values(estado="ia")
                )
                session.commit()
            finally:
                session.close()
            ia_released.set()
        except BaseException as exc:  # surface failures from the competing writer
            errors.append(exc)

    thread_a = threading.Thread(target=run_a, daemon=True)
    thread_b = threading.Thread(target=handoff_b_then_release_ia, daemon=True)
    try:
        thread_a.start()
        assert entered_llm.wait(timeout=5), "A não alcançou o LLM"
        thread_b.start()
        assert handoff_committed.wait(timeout=5), "B não confirmou handoff com A no LLM"
        assert ia_released.wait(timeout=5), "operador não liberou IA após handoff"

        # A reply fence must already be durable before A's external call returns.
        session = factory()
        try:
            worker_module._scope_agent_session(session, outcome_a)
            state = session.execute(
                select(Message.agent_reply_state).where(
                    Message.igreja_id == _IGREJA_A,
                    Message.conversation_id == conversation_id,
                    Message.provider_message_id == reply_key_a,
                )
            ).scalar_one_or_none()
            assert state == worker_module._AGENT_REPLY_SUPPRESSED
        finally:
            session.close()
    finally:
        release_llm.set()
        thread_a.join(timeout=10)
        if thread_b.ident is not None:
            thread_b.join(timeout=10)

    assert not thread_a.is_alive() and not thread_b.is_alive()
    assert not errors
    assert dispositions == [worker_module.AgentRunDisposition.COMPLETED]
    assert evolution.calls == []
    session = factory()
    try:
        worker_module._scope_agent_session(session, outcome_a)
        conversation = session.get(Conversation, conversation_id)
        assert conversation is not None and conversation.estado == "ia"
        reply = session.execute(
            select(Message).where(
                Message.igreja_id == _IGREJA_A,
                Message.conversation_id == conversation_id,
                Message.provider_message_id == reply_key_a,
            )
        ).scalar_one()
        assert reply.agent_reply_state == worker_module._AGENT_REPLY_SUPPRESSED
        assert reply.texto is None
    finally:
        session.close()
