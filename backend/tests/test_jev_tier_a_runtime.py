"""Tier A worker wiring stays outside sessions and fails closed."""

from __future__ import annotations

import uuid
from dataclasses import fields, replace
from types import SimpleNamespace

import pytest

from app.agent import runtime
from app.agent.nodes import empty_turn_effects
from app.db.models import (
    AgendaReminderSubscription,
    AgentConfig,
    Celula,
    ConsentRecord,
    Conversation,
    Igreja,
    Message,
    NotificationOutbox,
    Pessoa,
    WhatsappReminderPreference,
)
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


class _PublicPlanSession:
    """Small session seam for post-wait config and canonical-fact revalidation."""

    def __init__(
        self,
        config: object,
        *,
        church: tuple[object, object] | None = ("Rua institucional", "Domingo, 19:00"),
        cells: tuple[tuple[object, object, object, object], ...] = (),
    ) -> None:
        self.config = config
        self.church = church
        self.cells = cells
        self.statements: list[object] = []
        self.commits = 0

    def execute(self, statement: object) -> SimpleNamespace:
        self.statements.append(statement)
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entities = {item.get("entity") for item in descriptions}
        names = [item.get("name") for item in descriptions]
        if entities == {AgentConfig}:
            return SimpleNamespace(scalar_one_or_none=lambda: self.config)
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert _IGREJA_ID.hex in sql.replace("-", "")
        if entities == {Igreja}:
            assert names == ["endereco_institucional", "horarios_culto"]
            return SimpleNamespace(one_or_none=lambda: self.church)
        if entities == {Celula}:
            assert names == ["bairro", "nome", "dia_reuniao", "horario"]
            assert "celulas.ativo IS true" in sql
            assert "celulas.divulgar_whatsapp IS true" in sql
            return SimpleNamespace(all=lambda: list(self.cells))
        raise AssertionError(f"unexpected public revalidation query: {sql}")

    def commit(self) -> None:
        self.commits += 1


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
            public_info_reply=None,
        )
        ledger[provider_message_id] = intent
        return intent

    monkeypatch.setattr(queue_worker, "_reserve_agent_reply_intent", reserve)


def _enable_tier_a(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt one focused wiring test into the synthetic release deliberately."""

    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))
    monkeypatch.setattr(
        semantic_triage,
        "TIER_A_APPROVED_RELEASE_ID",
        "synthetic-release",
    )


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
    plan = _plan(within_limit=within_limit)
    return runtime.TierATurnPreflight(
        **{field.name: getattr(plan, field.name) for field in fields(runtime.TierATurnPreflight)}
    )


def _public_plan() -> runtime.AgentTurnPlan:
    return replace(
        _plan(),
        current_text="Que horas começa o culto?",
        draft_response="Horário de culto: Domingo, 19:00.",
        public_info_reply=True,
    )


def _current_public_config(**changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": _plan().config_id,
        "igreja_id": _IGREJA_ID,
        "ativo": True,
        "comportamento": _plan().config_comportamento,
        "informacoes_publicas": {"horarios_culto": "LEGADO-NAO-PUBLICAR"},
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _allow_public_plan(monkeypatch: pytest.MonkeyPatch) -> tuple[SimpleNamespace, SimpleNamespace]:
    conversation = SimpleNamespace(id=_CONVERSA_ID)
    pessoa = SimpleNamespace(id=_PESSOA_ID)
    monkeypatch.setattr(
        runtime,
        "_load_tier_a_plan_state",
        lambda *_args: (conversation, pessoa, None),
    )
    return conversation, pessoa


def test_public_plan_revalidates_matching_canonical_hours_after_tier_a_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The locked plan and canonical Igreja fact must still agree after HTTP."""

    _allow_public_plan(monkeypatch)
    session = _PublicPlanSession(_current_public_config())
    audits: list[dict[str, object]] = []
    monkeypatch.setattr(
        runtime,
        "log_agent_event",
        lambda _session, **kwargs: audits.append(kwargs),
    )
    monkeypatch.setattr(
        runtime,
        "log_ai_usage",
        lambda *_args, **_kwargs: pytest.fail(
            "consulta pública não pode contabilizar uso de LLM"
        ),
    )
    plan = _public_plan()

    result = runtime.apply_agent_turn_plan(
        session,
        plan=plan,
        response=plan.draft_response,
        usage=object(),
        decision_payload={"handoff": False},
    )

    assert result.response == "Horário de culto: Domingo, 19:00."
    assert result.public_info_reply is True
    assert "LEGADO-NAO-PUBLICAR" not in result.response
    assert session.commits == 1
    assert len(session.statements) == 2
    config_statement, church_statement = session.statements
    assert config_statement._for_update_arg is not None
    assert config_statement.get_execution_options()["populate_existing"] is True
    assert _IGREJA_ID.hex in str(config_statement.compile(compile_kwargs={"literal_binds": True})).replace("-", "")
    assert _IGREJA_ID.hex in str(church_statement.compile(compile_kwargs={"literal_binds": True})).replace("-", "")
    assert audits == [
        {
            "igreja_id": _IGREJA_ID,
            "evento": "jev_tier_a_decision",
            "payload": {"handoff": False},
            "conversation_id": _CONVERSA_ID,
        },
        {
            "igreja_id": _IGREJA_ID,
            "evento": "agent_public_info_reply",
            "payload": {},
            "conversation_id": _CONVERSA_ID,
        },
    ]


def test_public_plan_revalidates_published_canonical_cell_after_tier_a_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cell reply reads only the current public Celula projection."""

    _allow_public_plan(monkeypatch)
    session = _PublicPlanSession(
        _current_public_config(),
        cells=(("Centro", "Esperança", "Terça-feira", "19:00"),),
    )
    monkeypatch.setattr(runtime, "log_agent_event", lambda *_args, **_kwargs: None)
    plan = replace(
        _public_plan(),
        current_text="Tem uma célula no bairro Centro?",
        draft_response=(
            "Há uma célula com informações públicas no bairro Centro: Esperança. "
            "Encontro: Terça-feira, 19:00. Quer falar com a secretaria da igreja "
            "para entrar em contato com o líder da célula?"
        ),
        public_info_secretaria_offer=True,
    )

    result = runtime.apply_agent_turn_plan(
        session,
        plan=plan,
        response=plan.draft_response,
    )

    assert result.response == plan.draft_response
    assert result.secretaria_offer is True
    assert len(session.statements) == 3
    assert session.commits == 1


@pytest.mark.parametrize("church", (None, (None, None), (None, [])))
def test_public_plan_handoffs_when_canonical_hours_are_missing_or_invalid_after_wait(
    monkeypatch: pytest.MonkeyPatch,
    church: tuple[object, object] | None,
) -> None:
    """Missing or invalid canonical facts cannot release the pre-HTTP draft."""

    _allow_public_plan(monkeypatch)
    session = _PublicPlanSession(_current_public_config(), church=church)
    handoffs: list[dict[str, object]] = []
    monkeypatch.setattr(
        runtime,
        "persist_tier_a_handoff",
        lambda _session, **kwargs: handoffs.append(kwargs["decision_payload"])
        or runtime.AgentTurnResult(handled=True, suppressed=True, reason="public_reply_missing"),
    )
    plan = _public_plan()

    result = runtime.apply_agent_turn_plan(
        session,
        plan=plan,
        response=plan.draft_response,
    )

    assert result.response is None
    assert result.suppressed is True
    assert handoffs == [{"erro": "public_reply_missing"}]
    assert len(session.statements) == 2
    assert session.commits == 0


def test_public_plan_handoffs_when_canonical_hours_change_after_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changed facts cannot send either the stale draft or an unreviewed reply."""

    _allow_public_plan(monkeypatch)
    session = _PublicPlanSession(
        _current_public_config(), church=("Rua institucional", "Sábado, 18:00")
    )
    handoffs: list[dict[str, object]] = []
    monkeypatch.setattr(
        runtime,
        "persist_tier_a_handoff",
        lambda _session, **kwargs: handoffs.append(kwargs["decision_payload"])
        or runtime.AgentTurnResult(handled=True, suppressed=True, reason="public_reply_missing"),
    )
    plan = _public_plan()

    result = runtime.apply_agent_turn_plan(
        session,
        plan=plan,
        response=plan.draft_response,
    )

    assert result.response is None
    assert result.suppressed is True
    assert handoffs == [{"erro": "public_reply_missing"}]
    assert len(session.statements) == 2
    assert session.commits == 0


@pytest.mark.parametrize(
    "changes",
    (
        {"id": uuid.uuid4()},
        {"igreja_id": uuid.uuid4()},
        {"ativo": False},
        {"comportamento": "perfil alterado"},
    ),
)
def test_public_plan_handoffs_when_locked_config_no_longer_matches_plan(
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, object],
) -> None:
    """The second lock preserves the existing config-changed fail-safe."""

    conversation, pessoa = _allow_public_plan(monkeypatch)
    session = _PublicPlanSession(_current_public_config(**changes))
    invalid_reasons: list[str] = []
    monkeypatch.setattr(
        runtime,
        "_tier_a_plan_invalid_result",
        lambda *_args, **kwargs: invalid_reasons.append(kwargs["reason"])
        or runtime.AgentTurnResult(handled=True, suppressed=True, reason=kwargs["reason"]),
    )
    monkeypatch.setattr(runtime, "log_agent_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        runtime,
        "load_public_church_info",
        lambda *_args, **_kwargs: pytest.fail(
            "configuração alterada não pode consultar fatos canônicos"
        ),
    )
    plan = _public_plan()

    result = runtime.apply_agent_turn_plan(
        session,
        plan=plan,
        response=plan.draft_response,
    )

    assert (conversation.id, pessoa.id) == (_CONVERSA_ID, _PESSOA_ID)
    assert result.reason == "config_changed"
    assert invalid_reasons == ["config_changed"]


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


@pytest.mark.parametrize("marker", (True, False, None))
def test_reply_intent_preserves_persisted_public_origin_marker(marker) -> None:
    message = SimpleNamespace(
        id=uuid.uuid4(),
        agent_reply_state=queue_worker._AGENT_REPLY_PENDING,
        autor="ia",
        texto="resposta sintética",
        provider_message_id="agent-reply:synthetic",
        public_info_reply=marker,
    )

    intent = queue_worker._intent_from_message(message)

    assert intent.public_info_reply is marker


def _active_settings() -> semantic_triage.TriageSettings:
    return semantic_triage.TriageSettings(
        _env_file=None,
        typesafe_api_key="synthetic-key",
        jev_enabled_igreja_ids=str(_IGREJA_ID),
    )


def test_tier_a_flag_without_approved_release_keeps_legacy_path(monkeypatch) -> None:
    """A populated allowlist alone must not convert legacy turns to handoffs."""

    monkeypatch.setenv("JEV_ENABLED_IGREJA_IDS", str(_IGREJA_ID))
    monkeypatch.setattr(semantic_triage, "TIER_A_APPROVED_RELEASE_ID", None)
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("Tier A inerte não pode preparar o turno")
        ),
    )

    assert (
        queue_worker._run_active_tier_a_turn(
            lambda: _Session(),
            lambda: _Session(),
            _outcome(),
            igreja_id=_IGREJA_ID,
            turn_identity=None,
            uses_dedicated_agent_session=False,
            ownership_guard=None,
            evolution_client=object(),
        )
        is None
    )


def test_active_tier_a_rejects_long_input_before_platform_or_provider(monkeypatch) -> None:
    handoffs: list[dict[str, object]] = []
    _enable_tier_a(monkeypatch)
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
    _enable_tier_a(monkeypatch)
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


@pytest.mark.parametrize(
    ("semantic_handoff", "expected_outcome", "expected_error"),
    (
        (True, "handoff", None),
        (False, "falha", "llm_falha"),
    ),
    ids=("semantic_handoff", "adapter_failure"),
)
def test_typed_llm_handoff_records_effective_outcome_without_rewriting_jev(
    monkeypatch,
    semantic_handoff: bool,
    expected_outcome: str,
    expected_error: str | None,
) -> None:
    """The handoff audit keeps Jev's signals and records the LLM's own result."""

    captured: list[dict[str, object]] = []
    usage = SimpleNamespace(
        modelo="gpt-5.6-luna",
        tokens_in=7,
        tokens_out=3,
        custo=0.01,
    )
    decision = semantic_triage.TierADecision(
        risco_crise=False,
        pede_humano=False,
        pede_optout=False,
        handoff=False,
        erro=None,
        latencia_ms=1,
    )
    _enable_tier_a(monkeypatch)
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
    monkeypatch.setattr(queue_worker, "_tier_a_egress_still_allowed", lambda *_a, **_k: True)
    monkeypatch.setattr(queue_worker, "_run_tier_a_batch", lambda *_a: decision)
    monkeypatch.setattr(
        runtime,
        "reply_tier_a_plan_with_llm",
        lambda *_a, **_k: (
            SimpleNamespace(handoff=True, resposta=None, usage=usage)
            if semantic_handoff
            else None
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_persist_tier_a_handoff",
        lambda *_a, **kwargs: captured.append(kwargs)
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
    assert len(captured) == 1
    payload = captured[0]["decision_payload"]
    assert payload["handoff"] is False
    assert payload["erro"] is None
    assert payload["llm_outcome"] == expected_outcome
    assert payload["llm_erro"] == expected_error
    assert payload["llm_handoff"] is (True if semantic_handoff else None)
    assert captured[0]["usage"] is (usage if semantic_handoff else None)


def test_typed_llm_success_records_effective_outcome(monkeypatch) -> None:
    """A normal typed response remains auditable as an LLM response."""

    captured: list[dict[str, object]] = []
    decision = semantic_triage.TierADecision(
        risco_crise=False,
        pede_humano=False,
        pede_optout=False,
        handoff=False,
        erro=None,
        latencia_ms=1,
    )
    _enable_tier_a(monkeypatch)
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
    monkeypatch.setattr(queue_worker, "_tier_a_egress_still_allowed", lambda *_a, **_k: True)
    monkeypatch.setattr(queue_worker, "_run_tier_a_batch", lambda *_a: decision)
    monkeypatch.setattr(
        runtime,
        "reply_tier_a_plan_with_llm",
        lambda *_a, **_k: SimpleNamespace(
            handoff=False,
            resposta="resposta sintética",
            usage=None,
        ),
    )
    def complete(*_args: object, **kwargs: object) -> queue_worker.AgentRunDisposition:
        kwargs["apply"](object())
        return queue_worker.AgentRunDisposition.COMPLETED

    monkeypatch.setattr(queue_worker, "_complete_tier_a_reply_intent", complete)
    monkeypatch.setattr(
        runtime,
        "apply_agent_turn_plan",
        lambda _session, **kwargs: captured.append(kwargs)
        or SimpleNamespace(handled=True, suppressed=False, response="resposta sintética"),
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
    assert len(captured) == 1
    decision_payload = captured[0]["decision_payload"]
    assert decision_payload["llm_outcome"] == "resposta"
    assert decision_payload["llm_erro"] is None
    assert decision_payload["llm_handoff"] is False


def test_typed_llm_budget_exhaustion_is_audited_without_a_call(monkeypatch) -> None:
    """A spent wall budget is distinct from a failed LLM invocation."""

    captured: list[dict[str, object]] = []
    decision = semantic_triage.TierADecision(
        risco_crise=False,
        pede_humano=False,
        pede_optout=False,
        handoff=False,
        erro=None,
        latencia_ms=1,
    )

    class ExpiredBeforeLlm:
        def __init__(self) -> None:
            self.calls = 0

        def external_timeout(self, _cap: float) -> float | None:
            self.calls += 1
            return 1.0 if self.calls == 1 else None

    _enable_tier_a(monkeypatch)
    monkeypatch.setattr(queue_worker, "TurnBudget", ExpiredBeforeLlm)
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
    monkeypatch.setattr(queue_worker, "_tier_a_egress_still_allowed", lambda *_a, **_k: True)
    monkeypatch.setattr(queue_worker, "_run_tier_a_batch", lambda *_a: decision)
    monkeypatch.setattr(
        runtime,
        "reply_tier_a_plan_with_llm",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("orçamento esgotado não pode chamar LLM")
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_persist_tier_a_handoff",
        lambda *_a, **kwargs: captured.append(kwargs)
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
    payload = captured[0]["decision_payload"]
    assert payload["handoff"] is False
    assert payload["erro"] is None
    assert payload["llm_outcome"] == "nao_chamado"
    assert payload["llm_erro"] == "orcamento_esgotado"
    assert payload["llm_handoff"] is None


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
    _enable_tier_a(monkeypatch)
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


@pytest.mark.parametrize("semantic_handoff", (True, False))
def test_tier_a_gate_revoked_after_llm_keeps_typed_usage_and_outcome(
    monkeypatch,
    semantic_handoff: bool,
) -> None:
    """A revocation fences effects without discarding the completed LLM result."""

    observed: list[str] = []
    captured: list[dict[str, object]] = []
    usage = SimpleNamespace(
        modelo="gpt-5.6-luna",
        tokens_in=7,
        tokens_out=3,
        custo=0.01,
    )
    decision = semantic_triage.TierADecision(
        risco_crise=False,
        pede_humano=False,
        pede_optout=False,
        handoff=False,
        erro=None,
        latencia_ms=1,
    )
    allowed = iter((True, True, False))
    _enable_tier_a(monkeypatch)
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
        or SimpleNamespace(
            handoff=semantic_handoff,
            resposta=None if semantic_handoff else "resposta sintética",
            usage=usage,
        ),
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
        lambda *_a, **kwargs: captured.append(kwargs)
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
    assert observed == ["llm"]
    assert len(captured) == 1
    payload = captured[0]["decision_payload"]
    assert payload["handoff"] is False
    assert payload["erro"] is None
    assert payload["llm_outcome"] == ("handoff" if semantic_handoff else "resposta")
    assert payload["llm_erro"] is None
    assert payload["llm_handoff"] is semantic_handoff
    assert payload["effect_erro"] == "gate_fechado"
    assert captured[0]["usage"] is usage


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
    _enable_tier_a(monkeypatch)
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
    _enable_tier_a(monkeypatch)
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
    _enable_tier_a(monkeypatch)
    monkeypatch.setattr(
        queue_worker,
        "_load_agent_reply_intent",
        lambda *_args, **_kwargs: queue_worker._AgentReplyIntent(
            id=uuid.uuid4(),
            state=queue_worker._AGENT_REPLY_SUPPRESSED,
            response="",
            provider_message_id="agent-reply:synthetic",
            public_info_reply=None,
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
        public_info_reply=None,
    )
    confirmation = queue_worker._AgentReplyIntent(
        id=uuid.uuid4(),
        state=queue_worker._AGENT_REPLY_PENDING,
        response="Confirmação sintética",
        provider_message_id=confirmation_key,
        public_info_reply=False,
    )
    _enable_tier_a(monkeypatch)

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
    _enable_tier_a(monkeypatch)
    monkeypatch.setattr(queue_worker, "_AgentExecutionLease", lambda *_args: _Lease())
    monkeypatch.setattr(
        queue_worker,
        "_load_agent_reply_intent",
        lambda *_args, **_kwargs: queue_worker._AgentReplyIntent(
            id=uuid.uuid4(),
            state=queue_worker._AGENT_REPLY_PENDING,
            response="resposta sintética",
            provider_message_id="agent-reply:synthetic",
            public_info_reply=False,
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
        public_info_reply=None,
    )
    _enable_tier_a(monkeypatch)
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
        public_info_reply=None,
    )
    _enable_tier_a(monkeypatch)
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
        public_info_reply=None,
    )
    _enable_tier_a(monkeypatch)
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
    _enable_tier_a(monkeypatch)
    monkeypatch.setattr(queue_worker, "_scope_agent_execution_session", lambda *_a, **_k: None)

    def load_intent(*_args, **kwargs):
        observed.append(kwargs["intent_provider_message_id"])
        if kwargs["intent_provider_message_id"] == confirmation_key:
            return queue_worker._AgentReplyIntent(
                id=uuid.uuid4(),
                state=queue_worker._AGENT_REPLY_PENDING,
                response="confirmação sintética",
                provider_message_id=confirmation_key,
                public_info_reply=False,
            )
        if kwargs["intent_provider_message_id"] == reply_key:
            return queue_worker._AgentReplyIntent(
                id=uuid.uuid4(),
                state=queue_worker._AGENT_REPLY_RESERVED,
                response="",
                provider_message_id=reply_key,
                public_info_reply=None,
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
    _enable_tier_a(monkeypatch)
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

    def scalars(self) -> "_Scalars":
        return _Scalars([] if self.value is None else [self.value])


class _Scalars:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def __iter__(self):
        return iter(self.values)

    def all(self) -> list[object]:
        return list(self.values)


class _SairSession:
    def __init__(self, conversation: object, pessoa: object) -> None:
        self.conversation = conversation
        self.pessoa = pessoa
        self.pessoa_queries = 0
        self.added: list[object] = []
        self.commits = 0
        self.fence_updates = 0
        self.proposal_updates = 0
        self.reminder_proposal_updates = 0
        self.outbox_updates = 0
        self.conversation_updates = 0

    def execute(self, statement: object, _params: object = None) -> _Scalar:
        if getattr(statement, "is_update", False):
            if statement.table.name == Message.__tablename__:
                self.fence_updates += 1
            elif statement.table.name == "agent_action_proposals":
                sql = str(statement)
                values = list(statement.compile().params.values())
                if "lembretes_recusados" in values:
                    assert "agent_action_proposals.igreja_id" in sql
                    assert "agent_action_proposals.actor_pessoa_id" in sql
                    assert _IGREJA_ID in values and _PESSOA_ID in values
                    assert "configurar_lembrete_agenda" in values
                    self.reminder_proposal_updates += 1
                else:
                    assert "agent_action_proposals.igreja_id" in sql
                    assert "agent_action_proposals.conversation_id" in sql
                    assert "agent_action_proposals.state IN" in sql
                    assert _IGREJA_ID in values and _CONVERSA_ID in values
                    assert "cancelada" in values and "handoff_or_optout" in values
                    assert any(isinstance(value, (list, tuple)) and
                               set(value) == {"preparada", "pendente"} for value in values)
                    self.proposal_updates += 1
            elif statement.table.name == Conversation.__tablename__:
                self.conversation_updates += 1
            elif statement.table.name == "notification_outbox":
                values = list(statement.compile().params.values())
                assert _IGREJA_ID in values and _PESSOA_ID in values
                self.outbox_updates += 1
            else:
                raise AssertionError("SAIR explícito tentou atualizar tabela inesperada")
            return _Scalar(None)
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is Conversation:
            return _Scalar(self.conversation)
        if entity is Pessoa:
            self.pessoa_queries += 1
            return _Scalar(self.pessoa)
        if entity in {
            WhatsappReminderPreference,
            AgendaReminderSubscription,
            NotificationOutbox,
        }:
            return _Scalar(None)
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
        "app.services.notification_outbox._scoped", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "app.services.cell_report_reminders.disable_cell_report_reminders",
        lambda *_a, **_k: False,
    )
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
    assert sum(isinstance(value, ConsentRecord) for value in session.added) == 1
    preferences = [
        value for value in session.added if isinstance(value, WhatsappReminderPreference)
    ]
    assert {value.reminder_kind for value in preferences} == {"agenda", "cell_report"}
    assert all(value.state == "disabled" for value in preferences)
    assert session.commits == 1
    assert session.fence_updates == 1
    assert session.proposal_updates == 1
    assert session.reminder_proposal_updates == 1
    assert session.outbox_updates == 2
    assert session.conversation_updates == 1
