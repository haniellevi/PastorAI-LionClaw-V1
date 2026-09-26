"""Tier A worker wiring stays outside sessions and fails closed."""

from __future__ import annotations

import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.agent import runtime
from app.agent.nodes import empty_turn_effects
from app.db.models import Conversation, Message, Pessoa
from app.services import semantic_triage
from app.workers import queue_worker


_IGREJA_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_CONVERSA_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_PESSOA_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
_INBOUND_ID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


class _Session:
    def __init__(self) -> None:
        self.closed = False
        self.cross_tenant = False

    def close(self) -> None:
        self.closed = True

    def in_transaction(self) -> bool:
        return False


class _Lease:
    def __init__(self, acquired: bool = True) -> None:
        self.acquired = acquired
        self.closed = False

    def acquire(self) -> bool:
        return self.acquired

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _no_existing_tier_a_reply_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Focused wiring tests supply no PostgreSQL reply ledger by default."""

    ledger: dict[str, queue_worker._AgentReplyIntent] = {}

    monkeypatch.setattr(
        queue_worker,
        "_load_agent_reply_intent",
        lambda *_args, **kwargs: ledger.get(kwargs["intent_provider_message_id"]),
    )
    def reserve(*_args, **kwargs):
        provider_message_id = kwargs["intent_provider_message_id"]
        intent = queue_worker._AgentReplyIntent(
            id=uuid.uuid4(),
            state=queue_worker._AGENT_REPLY_RESERVED,
            response="",
            provider_message_id=provider_message_id,
        )
        ledger[provider_message_id] = intent
        return intent

    monkeypatch.setattr(queue_worker, "_reserve_agent_reply_intent", reserve)


def _plan(*, within_limit: bool = True) -> runtime.AgentTurnPlan:
    return runtime.AgentTurnPlan(
        igreja_id=_IGREJA_ID,
        conversation_id=_CONVERSA_ID,
        pessoa_id=_PESSOA_ID,
        inbound_message_id=_INBOUND_ID,
        provider_message_id="inbound-synthetic",
        current_text="mensagem sintética",
        tier_a_input_within_limit=within_limit,
        config_id=uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
        config_comportamento="Tom sintético.",
        credential_id=uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        credential_provedor="openai",
        credential_model="gpt-5.6-luna",
        credential_key_encrypted="encrypted-synthetic",
        accepted_consent_version="synthetic-v1",
        term_version="synthetic-v1",
        effects=empty_turn_effects(),
        draft_response="rascunho sintético",
        system_prompt="sistema",
        user_prompt="mensagem sintética",
    )


def _preflight(*, within_limit: bool = True) -> runtime.TierATurnPreflight:
    return runtime.TierATurnPreflight(
        **{
            key: value
            for key, value in _plan(within_limit=within_limit).__dict__.items()
            if key
            not in {
                "effects",
                "draft_response",
                "system_prompt",
                "user_prompt",
                "public_info_reply",
            }
        }
    )


def _outcome() -> queue_worker.IngestionOutcome:
    return queue_worker.IngestionOutcome(
        result=queue_worker.IngestionResult.REGISTERED,
        conversation_id=_CONVERSA_ID,
        igreja_id=_IGREJA_ID,
        inbound=True,
        texto="mensagem sintética",
        provider_message_id="inbound-synthetic",
        claim_id="claim-synthetic",
        inbound_message_id=_INBOUND_ID,
    )


def _active_settings() -> semantic_triage.TriageSettings:
    return semantic_triage.TriageSettings(
        _env_file=None,
        typesafe_api_key="synthetic-key",
        jev_enabled_igreja_ids=str(_IGREJA_ID),
    )


def test_active_tier_a_rejects_long_input_before_platform_or_provider(monkeypatch) -> None:
    handoffs: list[dict[str, object]] = []
    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))
    monkeypatch.setattr(queue_worker, "_scope_agent_execution_session", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_a, **_k: SimpleNamespace(
            reason=None,
            preflight=_preflight(within_limit=False),
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_tier_a_effective_settings",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("input longo não pode consultar plataforma")
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_run_tier_a_batch",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("input longo não pode chamar Jev")
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_persist_tier_a_handoff",
        lambda *_a, **kwargs: handoffs.append(kwargs["decision_payload"])
        or queue_worker.AgentRunDisposition.COMPLETED,
    )

    result = queue_worker._run_active_tier_a_turn(
        lambda: _Session(),
        lambda: _Session(),
        _outcome(),
        igreja_id=_IGREJA_ID,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=object(),
    )

    assert result is queue_worker.AgentRunDisposition.COMPLETED
    assert handoffs == [
        {
            "risco_crise": False,
            "pede_humano": False,
            "pede_optout": False,
            "handoff": True,
            "erro": "limite_entrada",
            "latencia_ms": 0,
        }
    ]


def test_active_tier_a_runs_jev_and_typed_llm_without_open_session_or_lease(
    monkeypatch,
) -> None:
    observed: list[str] = []
    session = _Session()
    effective = SimpleNamespace(settings=_active_settings())
    decision = semantic_triage.TierADecision(
        risco_crise=False,
        pede_humano=False,
        pede_optout=False,
        handoff=False,
        erro=None,
        latencia_ms=1,
    )
    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))
    monkeypatch.setattr(queue_worker, "_scope_agent_execution_session", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_a, **kwargs: (
            SimpleNamespace(reason=None, preflight=_preflight())
            if kwargs.get("tier_a_preflight")
            else SimpleNamespace(reason=None, plan=_plan())
        ),
    )
    monkeypatch.setattr(queue_worker, "_tier_a_effective_settings", lambda *_a: effective)
    monkeypatch.setattr(semantic_triage, "tier_a_egress_allowed", lambda *_a, **_k: True)

    def run_jev(
        _effective: object,
        _igreja_id: object,
        _text: str,
        _timeout: float,
        _release: object,
    ) -> object:
        assert session.in_transaction() is False
        observed.append("jev")
        return decision

    def run_llm(_plan: object, *, timeout_seconds: float) -> object:
        assert session.in_transaction() is False
        assert timeout_seconds <= 4
        observed.append("llm")
        return SimpleNamespace(handoff=False, resposta="resposta sintética", usage=None)

    monkeypatch.setattr(queue_worker, "_run_tier_a_batch", run_jev)
    monkeypatch.setattr(runtime, "reply_tier_a_plan_with_llm", run_llm)
    monkeypatch.setattr(
        queue_worker,
        "_complete_tier_a_reply_intent",
        lambda *_a, **kwargs: observed.append("durable")
        or kwargs["apply"](object())
        or queue_worker.AgentRunDisposition.COMPLETED,
    )
    monkeypatch.setattr(
        runtime,
        "apply_agent_turn_plan",
        lambda _session, **kwargs: observed.append("apply")
        or SimpleNamespace(handled=True, suppressed=False, response=kwargs["response"]),
    )

    result = queue_worker._run_active_tier_a_turn(
        lambda: session,
        lambda: session,
        _outcome(),
        igreja_id=_IGREJA_ID,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=object(),
    )

    assert result is not None
    assert observed == ["jev", "llm", "durable", "apply"]


def test_tier_a_gate_revoked_after_jev_handoffs_before_llm(monkeypatch) -> None:
    """A platform revocation after Jev blocks the old turn before LLM work."""

    observed: list[str] = []
    decision = semantic_triage.TierADecision(
        risco_crise=False,
        pede_humano=False,
        pede_optout=False,
        handoff=False,
        erro=None,
        latencia_ms=1,
    )
    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))
    monkeypatch.setattr(queue_worker, "_scope_agent_execution_session", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_a, **kwargs: (
            SimpleNamespace(reason=None, preflight=_preflight())
            if kwargs.get("tier_a_preflight")
            else SimpleNamespace(reason=None, plan=_plan())
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_tier_a_effective_settings",
        lambda *_a: SimpleNamespace(settings=_active_settings()),
    )
    monkeypatch.setattr(semantic_triage, "tier_a_egress_allowed", lambda *_a, **_k: True)
    monkeypatch.setattr(
        queue_worker,
        "_run_tier_a_batch",
        lambda *_a: observed.append("jev") or decision,
    )
    monkeypatch.setattr(queue_worker, "_tier_a_egress_still_allowed", lambda *_a, **_k: False)
    monkeypatch.setattr(
        runtime,
        "reply_tier_a_plan_with_llm",
        lambda *_a, **_k: observed.append("llm"),
    )
    monkeypatch.setattr(
        queue_worker,
        "_persist_tier_a_handoff",
        lambda *_a, **kwargs: observed.append(kwargs["decision_payload"]["erro"])
        or queue_worker.AgentRunDisposition.COMPLETED,
    )

    result = queue_worker._run_active_tier_a_turn(
        lambda: _Session(),
        lambda: _Session(),
        _outcome(),
        igreja_id=_IGREJA_ID,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=object(),
    )

    assert result is queue_worker.AgentRunDisposition.COMPLETED
    assert observed == ["jev", "gate_fechado"]


def test_tier_a_gate_revoked_after_llm_never_applies_stale_reply(monkeypatch) -> None:
    """A second platform read fences a response produced before revocation."""

    observed: list[str] = []
    decision = semantic_triage.TierADecision(
        risco_crise=False,
        pede_humano=False,
        pede_optout=False,
        handoff=False,
        erro=None,
        latencia_ms=1,
    )
    allowed = iter((True, True, False))
    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))
    monkeypatch.setattr(queue_worker, "_scope_agent_execution_session", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_a, **kwargs: (
            SimpleNamespace(reason=None, preflight=_preflight())
            if kwargs.get("tier_a_preflight")
            else SimpleNamespace(reason=None, plan=_plan())
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_tier_a_effective_settings",
        lambda *_a: SimpleNamespace(settings=_active_settings()),
    )
    monkeypatch.setattr(semantic_triage, "tier_a_egress_allowed", lambda *_a, **_k: True)
    monkeypatch.setattr(queue_worker, "_run_tier_a_batch", lambda *_a: decision)
    monkeypatch.setattr(
        queue_worker,
        "_tier_a_egress_still_allowed",
        lambda *_a, **_k: next(allowed),
    )
    monkeypatch.setattr(
        runtime,
        "reply_tier_a_plan_with_llm",
        lambda *_a, **_k: observed.append("llm")
        or SimpleNamespace(handoff=False, resposta="resposta sintética", usage=None),
    )
    monkeypatch.setattr(
        queue_worker,
        "_complete_tier_a_reply_intent",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("resposta revogada não pode ser aplicada")
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_persist_tier_a_handoff",
        lambda *_a, **kwargs: observed.append(kwargs["decision_payload"]["erro"])
        or queue_worker.AgentRunDisposition.COMPLETED,
    )

    result = queue_worker._run_active_tier_a_turn(
        lambda: _Session(),
        lambda: _Session(),
        _outcome(),
        igreja_id=_IGREJA_ID,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=object(),
    )

    assert result is queue_worker.AgentRunDisposition.COMPLETED
    assert observed == ["llm", "gate_fechado"]


def test_typed_llm_receives_bounded_context_and_only_handoff_envelope(monkeypatch) -> None:
    captured: list[tuple[str, str, float]] = []

    class FakeClient:
        def __init__(self, *_args: object) -> None:
            pass

        def complete_typed(
            self,
            system_prompt: str,
            user_prompt: str,
            *,
            timeout_seconds: float,
        ) -> object:
            captured.append((system_prompt, user_prompt, timeout_seconds))
            return SimpleNamespace(handoff=False, resposta="resposta sintética", usage=None)

    monkeypatch.setattr(runtime, "decrypt_secret", lambda _value: "synthetic-key")
    monkeypatch.setattr(runtime, "LLMClient", FakeClient)

    result = runtime.reply_tier_a_plan_with_llm(_plan(), timeout_seconds=1.0)

    assert result is not None
    assert len(captured) == 1
    system_prompt, user_prompt, timeout_seconds = captured[0]
    assert "JSON" in system_prompt
    assert "handoff" in system_prompt
    assert "risco" in system_prompt.casefold()
    assert "mensagem sintética" in user_prompt
    assert timeout_seconds == 1.0


def test_active_non_onboarding_turn_handoffs_before_legacy_effects(monkeypatch) -> None:
    handoffs: list[dict[str, object]] = []
    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))
    monkeypatch.setattr(queue_worker, "_scope_agent_execution_session", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_a, **kwargs: (
            SimpleNamespace(reason=None, preflight=_preflight())
            if kwargs.get("tier_a_preflight")
            else (_ for _ in ()).throw(
                AssertionError("crise Tier A não pode chegar aos efeitos legados")
            )
        ),
    )
    effective = SimpleNamespace(settings=_active_settings())
    monkeypatch.setattr(queue_worker, "_tier_a_effective_settings", lambda *_a: effective)
    monkeypatch.setattr(semantic_triage, "tier_a_egress_allowed", lambda *_a, **_k: True)
    monkeypatch.setattr(
        queue_worker,
        "_run_tier_a_batch",
        lambda *_a: semantic_triage.TierADecision(
            risco_crise=True,
            pede_humano=False,
            pede_optout=False,
            handoff=True,
            erro=None,
            latencia_ms=1,
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_persist_tier_a_handoff",
        lambda *_a, **kwargs: handoffs.append(kwargs["decision_payload"])
        or queue_worker.AgentRunDisposition.COMPLETED,
    )

    result = queue_worker._run_active_tier_a_turn(
        lambda: _Session(),
        lambda: _Session(),
        _outcome(),
        igreja_id=_IGREJA_ID,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=object(),
    )

    assert result is queue_worker.AgentRunDisposition.COMPLETED
    assert handoffs[0]["risco_crise"] is True


def test_listed_bad_transport_config_handoffs_instead_of_legacy(monkeypatch) -> None:
    handoffs: list[dict[str, object]] = []
    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))
    monkeypatch.setattr(queue_worker, "_scope_agent_execution_session", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_a, **_k: SimpleNamespace(reason=None, preflight=_preflight()),
    )
    monkeypatch.setattr(
        semantic_triage,
        "get_triage_settings",
        lambda: (_ for _ in ()).throw(ValueError("invalid synthetic config")),
    )
    monkeypatch.setattr(
        queue_worker,
        "_persist_tier_a_handoff",
        lambda *_a, **kwargs: handoffs.append(kwargs["decision_payload"])
        or queue_worker.AgentRunDisposition.COMPLETED,
    )

    result = queue_worker._run_active_tier_a_turn(
        lambda: _Session(),
        lambda: _Session(),
        _outcome(),
        igreja_id=_IGREJA_ID,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=object(),
    )

    assert result is queue_worker.AgentRunDisposition.COMPLETED
    assert handoffs[0]["erro"] == "gate_fechado"


def test_empty_active_flag_ignores_invalid_optional_transport_config(monkeypatch) -> None:
    monkeypatch.delenv("JEV_ENABLED_IGREJA_IDS", raising=False)
    monkeypatch.setattr(
        semantic_triage,
        "get_triage_settings",
        lambda: (_ for _ in ()).throw(ValueError("must not be parsed")),
    )

    result = queue_worker._run_active_tier_a_turn(
        lambda: (_ for _ in ()).throw(AssertionError("legado não abre sessão Tier A")),
        lambda: (_ for _ in ()).throw(AssertionError("legado não abre sessão Tier A")),
        _outcome(),
        igreja_id=_IGREJA_ID,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=object(),
    )

    assert result is None


def test_tier_a_terminal_tombstone_skips_retriage_and_transport(monkeypatch) -> None:
    """A retry sees the inbound's terminal fence before Jev, LLM or delivery."""

    calls: list[str] = []
    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))
    monkeypatch.setattr(
        queue_worker,
        "_load_agent_reply_intent",
        lambda *_args, **_kwargs: queue_worker._AgentReplyIntent(
            id=uuid.uuid4(),
            state=queue_worker._AGENT_REPLY_SUPPRESSED,
            response="",
            provider_message_id="agent-reply:synthetic",
        ),
    )
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("tombstone não pode reabrir o runtime")
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_run_tier_a_batch",
        lambda *_args, **_kwargs: calls.append("jev"),
    )

    result = queue_worker._run_active_tier_a_turn(
        lambda: (_ for _ in ()).throw(AssertionError("não deve abrir sessão")),
        lambda: (_ for _ in ()).throw(AssertionError("não deve abrir sessão")),
        _outcome(),
        igreja_id=_IGREJA_ID,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=SimpleNamespace(send_text=lambda *_args: calls.append("send")),
    )

    assert result is queue_worker.AgentRunDisposition.COMPLETED
    assert calls == []


def test_optout_confirmation_source_marker_recovers_without_retriaging(monkeypatch) -> None:
    """Only the typed marker for this inbound may resume its confirmation C."""

    observed: list[str] = []
    outcome = _outcome()
    source_key = queue_worker._tier_a_optout_source_idempotency_key(outcome)
    confirmation_key = runtime.consent_rules.tier_a_optout_confirmation_key(
        _IGREJA_ID,
        _CONVERSA_ID,
    )
    source = queue_worker._AgentReplyIntent(
        id=uuid.uuid4(),
        state=queue_worker._AGENT_REPLY_NO_RESPONSE,
        response="",
        provider_message_id=source_key,
    )
    confirmation = queue_worker._AgentReplyIntent(
        id=uuid.uuid4(),
        state=queue_worker._AGENT_REPLY_PENDING,
        response="Confirmação sintética",
        provider_message_id=confirmation_key,
    )
    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))

    def load_intent(*_args, **kwargs):
        key = kwargs["intent_provider_message_id"]
        if key == source_key:
            return source
        if key == confirmation_key:
            return confirmation
        raise AssertionError("retry de A não pode consultar outra chave")

    monkeypatch.setattr(queue_worker, "_load_agent_reply_intent", load_intent)
    monkeypatch.setattr(
        queue_worker,
        "_resume_tier_a_optout_confirmation",
        lambda *_args, **kwargs: observed.append(kwargs["confirmation_key"])
        or queue_worker.AgentRunDisposition.COMPLETED,
    )
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("marcador de A não pode reclassificar")
        ),
    )

    result = queue_worker._run_active_tier_a_turn(
        lambda: (_ for _ in ()).throw(AssertionError("não deve abrir sessão")),
        lambda: (_ for _ in ()).throw(AssertionError("não deve abrir sessão")),
        outcome,
        igreja_id=_IGREJA_ID,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=object(),
    )

    assert result is queue_worker.AgentRunDisposition.COMPLETED
    assert observed == [confirmation_key]


def test_pending_tier_a_reply_retries_transport_without_retriage(monkeypatch) -> None:
    """Only a pending reply for this inbound may resume transport on retry."""

    observed: list[object] = []
    outcome = _outcome()
    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))
    monkeypatch.setattr(queue_worker, "_AgentExecutionLease", lambda *_args: _Lease())
    monkeypatch.setattr(
        queue_worker,
        "_load_agent_reply_intent",
        lambda *_args, **_kwargs: queue_worker._AgentReplyIntent(
            id=uuid.uuid4(),
            state=queue_worker._AGENT_REPLY_PENDING,
            response="resposta sintética",
            provider_message_id="agent-reply:synthetic",
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_deliver_agent_reply_intent",
        lambda *_args, **_kwargs: observed.append("deliver"),
    )
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("retry pendente não pode reclassificar")
        ),
    )

    result = queue_worker._run_active_tier_a_turn(
        lambda: (_ for _ in ()).throw(AssertionError("não deve abrir sessão")),
        lambda: (_ for _ in ()).throw(AssertionError("não deve abrir sessão")),
        outcome,
        igreja_id=_IGREJA_ID,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=object(),
    )

    assert result is queue_worker.AgentRunDisposition.COMPLETED
    assert observed == ["deliver"]


def test_reserved_tier_a_reply_keeps_legacy_recovery_path(monkeypatch) -> None:
    """A crash before execution may still reach the existing reservation CAS."""

    observed: list[str] = []
    reserved = queue_worker._AgentReplyIntent(
        id=uuid.uuid4(),
        state=queue_worker._AGENT_REPLY_RESERVED,
        response="",
        provider_message_id="agent-reply:synthetic",
    )
    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))
    monkeypatch.setattr(queue_worker, "_scope_agent_execution_session", lambda *_a, **_k: None)
    monkeypatch.setattr(queue_worker, "_load_agent_reply_intent", lambda *_a, **_k: reserved)
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_args, **kwargs: (
            SimpleNamespace(reason=None, preflight=_preflight())
            if kwargs.get("tier_a_preflight")
            else SimpleNamespace(reason=None, plan=replace(_plan(), public_info_reply=True))
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_tier_a_effective_settings",
        lambda *_args: SimpleNamespace(settings=_active_settings()),
    )
    monkeypatch.setattr(semantic_triage, "tier_a_egress_allowed", lambda *_a, **_k: True)
    monkeypatch.setattr(
        queue_worker,
        "_run_tier_a_batch",
        lambda *_args: observed.append("jev")
        or semantic_triage.TierADecision(
            risco_crise=False,
            pede_humano=False,
            pede_optout=False,
            handoff=False,
            erro=None,
            latencia_ms=1,
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_complete_tier_a_reply_intent",
        lambda *_args, **_kwargs: observed.append("cas")
        or queue_worker.AgentRunDisposition.COMPLETED,
    )

    result = queue_worker._run_active_tier_a_turn(
        lambda: _Session(),
        lambda: _Session(),
        _outcome(),
        igreja_id=_IGREJA_ID,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=object(),
    )

    assert result is queue_worker.AgentRunDisposition.COMPLETED
    assert observed == ["jev", "cas"]


def test_executing_tier_a_reply_is_quarantined_without_retriage(monkeypatch) -> None:
    """A crash after execution began is ambiguous, never a new Tier A turn."""

    observed: list[object] = []
    executing = queue_worker._AgentReplyIntent(
        id=uuid.uuid4(),
        state=queue_worker._AGENT_REPLY_EXECUTING,
        response="",
        provider_message_id="agent-reply:synthetic",
    )
    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))
    monkeypatch.setattr(queue_worker, "_AgentExecutionLease", lambda *_args: _Lease())
    monkeypatch.setattr(queue_worker, "_load_agent_reply_intent", lambda *_a, **_k: executing)
    monkeypatch.setattr(
        queue_worker,
        "_quarantine_agent_execution",
        lambda *_args: observed.append("quarantine"),
    )
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ia_executando não pode reclassificar")
        ),
    )

    result = queue_worker._run_active_tier_a_turn(
        lambda: (_ for _ in ()).throw(AssertionError("não deve abrir sessão")),
        lambda: (_ for _ in ()).throw(AssertionError("não deve abrir sessão")),
        _outcome(),
        igreja_id=_IGREJA_ID,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=object(),
    )

    assert result is queue_worker.AgentRunDisposition.COMPLETED
    assert observed == ["quarantine"]


def test_live_execution_lease_keeps_tier_a_intent_in_flight(monkeypatch) -> None:
    """A second worker cannot quarantine an execution still owned elsewhere."""

    executing = queue_worker._AgentReplyIntent(
        id=uuid.uuid4(),
        state=queue_worker._AGENT_REPLY_EXECUTING,
        response="",
        provider_message_id="agent-reply:synthetic",
    )
    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))
    monkeypatch.setattr(queue_worker, "_load_agent_reply_intent", lambda *_a, **_k: executing)
    monkeypatch.setattr(queue_worker, "_AgentExecutionLease", lambda *_args: _Lease(False))
    monkeypatch.setattr(
        queue_worker,
        "_quarantine_agent_execution",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("lease viva não pode ser quarentenada")
        ),
    )
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("lease viva não pode reclassificar")
        ),
    )

    result = queue_worker._run_active_tier_a_turn(
        lambda: (_ for _ in ()).throw(AssertionError("não deve abrir sessão")),
        lambda: (_ for _ in ()).throw(AssertionError("não deve abrir sessão")),
        _outcome(),
        igreja_id=_IGREJA_ID,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=object(),
    )

    assert result is queue_worker.AgentRunDisposition.IN_FLIGHT


def test_pending_confirmation_from_another_turn_cannot_bypass_current_triage(
    monkeypatch,
) -> None:
    """A conversation key never transports an old confirmation before new triage."""

    observed: list[object] = []
    confirmation_key = runtime.consent_rules.tier_a_optout_confirmation_key(
        _IGREJA_ID,
        _CONVERSA_ID,
    )
    outcome = replace(
        _outcome(),
        provider_message_id="inbound-crise-sintetica",
        claim_id="claim-crise-sintetica",
        inbound_message_id=uuid.uuid4(),
    )
    reply_key = queue_worker._agent_reply_idempotency_key(outcome)
    assert reply_key is not None
    decision = semantic_triage.TierADecision(
        risco_crise=True,
        pede_humano=False,
        pede_optout=False,
        handoff=True,
        erro=None,
        latencia_ms=1,
    )
    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))
    monkeypatch.setattr(queue_worker, "_scope_agent_execution_session", lambda *_a, **_k: None)

    def load_intent(*_args, **kwargs):
        observed.append(kwargs["intent_provider_message_id"])
        if kwargs["intent_provider_message_id"] == confirmation_key:
            return queue_worker._AgentReplyIntent(
                id=uuid.uuid4(),
                state=queue_worker._AGENT_REPLY_PENDING,
                response="confirmação sintética",
                provider_message_id=confirmation_key,
            )
        if kwargs["intent_provider_message_id"] == reply_key:
            return queue_worker._AgentReplyIntent(
                id=uuid.uuid4(),
                state=queue_worker._AGENT_REPLY_RESERVED,
                response="",
                provider_message_id=reply_key,
            )
        return None

    monkeypatch.setattr(queue_worker, "_load_agent_reply_intent", load_intent)
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_args, **kwargs: SimpleNamespace(
            reason=None,
            preflight=_preflight(),
        )
        if kwargs.get("tier_a_preflight")
        else (_ for _ in ()).throw(
            AssertionError("crise Tier A não pode seguir ao plano")
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_tier_a_effective_settings",
        lambda *_args: SimpleNamespace(settings=_active_settings()),
    )
    monkeypatch.setattr(semantic_triage, "tier_a_egress_allowed", lambda *_a, **_k: True)
    monkeypatch.setattr(
        queue_worker,
        "_run_tier_a_batch",
        lambda *_args: observed.append("jev") or decision,
    )
    monkeypatch.setattr(
        queue_worker,
        "_deliver_agent_reply_intent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("confirmação pendente não pode transportar antes da crise")
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_persist_tier_a_handoff",
        lambda *_args, **_kwargs: observed.append("handoff")
        or queue_worker.AgentRunDisposition.COMPLETED,
    )

    result = queue_worker._run_active_tier_a_turn(
        lambda: _Session(),
        lambda: _Session(),
        outcome,
        igreja_id=_IGREJA_ID,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=object(),
    )

    assert result is queue_worker.AgentRunDisposition.COMPLETED
    assert "jev" in observed
    assert "handoff" in observed
    assert confirmation_key not in observed


def test_probable_optout_precedes_a_public_info_reply(monkeypatch) -> None:
    """Tier A's inferred opt-out never sends a deterministic public answer first."""

    observed: list[object] = []
    decision = semantic_triage.TierADecision(
        risco_crise=False,
        pede_humano=False,
        pede_optout=True,
        handoff=False,
        erro=None,
        latencia_ms=1,
    )
    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))
    monkeypatch.setattr(queue_worker, "_scope_agent_execution_session", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_args, **kwargs: (
            SimpleNamespace(reason=None, preflight=_preflight())
            if kwargs.get("tier_a_preflight")
            else (_ for _ in ()).throw(
                AssertionError("opt-out provável não pode chegar à rota pública")
            )
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_tier_a_effective_settings",
        lambda *_args: SimpleNamespace(settings=_active_settings()),
    )
    monkeypatch.setattr(semantic_triage, "tier_a_egress_allowed", lambda *_a, **_k: True)
    monkeypatch.setattr(queue_worker, "_run_tier_a_batch", lambda *_a: decision)
    monkeypatch.setattr(
        runtime,
        "apply_tier_a_optout_confirmation",
        lambda _session, **_kwargs: observed.append("confirmation")
        or SimpleNamespace(handled=True, suppressed=False, response="sintética"),
    )
    monkeypatch.setattr(
        queue_worker,
        "_resume_tier_a_optout_confirmation",
        lambda *_args, **kwargs: observed.append(kwargs["confirmation_key"])
        or queue_worker.AgentRunDisposition.COMPLETED,
    )
    monkeypatch.setattr(
        runtime,
        "apply_agent_turn_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("resposta pública não pode vencer opt-out provável")
        ),
    )

    result = queue_worker._run_active_tier_a_turn(
        lambda: _Session(),
        lambda: _Session(),
        _outcome(),
        igreja_id=_IGREJA_ID,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=object(),
    )

    assert result is not None
    assert observed == [
        "confirmation",
        runtime.consent_rules.tier_a_optout_confirmation_key(
            _IGREJA_ID,
            _CONVERSA_ID,
        ),
    ]


class _Scalar:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value

    def one_or_none(self) -> object:
        return self.value


class _SairSession:
    def __init__(self, conversation: object, pessoa: object) -> None:
        self.conversation = conversation
        self.pessoa = pessoa
        self.pessoa_queries = 0
        self.added: list[object] = []
        self.commits = 0
        self.fence_updates = 0

    def execute(self, statement: object, _params: object = None) -> _Scalar:
        if getattr(statement, "is_update", False):
            self.fence_updates += 1
            return _Scalar(None)
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is Conversation:
            return _Scalar(self.conversation)
        if entity is Pessoa:
            self.pessoa_queries += 1
            return _Scalar(self.pessoa)
        if entity is Message:
            return _Scalar((__import__("datetime").datetime.now(__import__("datetime").UTC), "SAIR"))
        raise AssertionError("SAIR explícito não pode chegar a config, credencial ou LLM")

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1


def test_explicit_sair_persists_before_agent_config_or_tier_a(monkeypatch) -> None:
    conversation = SimpleNamespace(
        id=_CONVERSA_ID,
        igreja_id=_IGREJA_ID,
        pessoa_id=_PESSOA_ID,
        estado="ia",
    )
    pessoa = SimpleNamespace(
        id=_PESSOA_ID,
        igreja_id=_IGREJA_ID,
        optout=False,
        sem_interesse=False,
    )
    session = _SairSession(conversation, pessoa)
    monkeypatch.setattr(runtime, "require_tenant_scope", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: SimpleNamespace(
            agent_trusted_inbound_identity_enabled=False,
            agent_term_version="synthetic-v1",
        ),
    )
    monkeypatch.setattr(runtime, "log_agent_event", lambda *_a, **_k: None)

    result = runtime.process_inbound_message(
        session,
        igreja_id=_IGREJA_ID,
        conversation_id=_CONVERSA_ID,
        texto="SAIR",
        inbound_message_id=_INBOUND_ID,
        provider_message_id="inbound-synthetic",
    )

    assert result.suppressed is True
    assert result.reason == "optout_aplicado"
    assert pessoa.optout is True
    assert len(session.added) == 1
    assert session.commits == 1
    assert session.fence_updates == 1
