"""Barreiras fail-closed do runtime do agente por tenant."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.agent import runtime
from app.agent.turn_identity import (
    AgentTurnContractErrorCode,
    AgentTurnIdentityError,
    build_agent_turn_identity,
)
from app.config import Settings
from app.db.rls_observability import TenantScopeVerificationError
from app.workers import queue_worker


class _ScalarResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _RuntimeSession:
    def __init__(self, values: list[object]) -> None:
        self._values = iter(values)
        self.statements: list[object] = []

    def execute(self, statement, params=None) -> _ScalarResult:
        self.statements.append(statement)
        return _ScalarResult(next(self._values))


def _trusted_outcome(*, claim_id: str = "claim-1") -> queue_worker.IngestionOutcome:
    return queue_worker.IngestionOutcome(
        result=queue_worker.IngestionResult.REGISTERED,
        conversation_id=uuid.uuid4(),
        igreja_id=uuid.uuid4(),
        inbound_message_id=uuid.uuid4(),
        provider_message_id="3EB0123456789ABCDEF",
        claim_id=claim_id,
        instance="instancia-de-teste",
        telefone="numero-sintetico",
        texto="mensagem sintética",
        inbound=True,
    )


def test_trusted_inbound_identity_flag_is_default_off(monkeypatch) -> None:
    assert (
        Settings.model_fields["agent_trusted_inbound_identity_enabled"].default
        is False
    )
    assert (
        Settings(
            _env_file=None,
            agent_trusted_inbound_identity_enabled=True,
        ).agent_trusted_inbound_identity_enabled
        is True
    )
    monkeypatch.setenv(
        "AGENT_TRUSTED_INBOUND_IDENTITY_ENABLED",
        "not-a-boolean",
    )
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_queue_claim_does_not_change_stable_turn_id() -> None:
    first = _trusted_outcome(claim_id="claim-a")
    second = queue_worker.IngestionOutcome(
        **{
            **first.__dict__,
            "claim_id": "claim-b",
        }
    )

    first_identity = queue_worker._build_trusted_inbound_turn_identity(first)
    second_identity = queue_worker._build_trusted_inbound_turn_identity(second)

    assert first_identity.turn_id == second_identity.turn_id


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        (
            "conversation_id",
            None,
            queue_worker.TrustedInboundIdentityErrorCode.INVALID_TRUSTED_INBOUND_IDENTITY,
        ),
        (
            "inbound_message_id",
            None,
            queue_worker.TrustedInboundIdentityErrorCode.INVALID_TRUSTED_INBOUND_IDENTITY,
        ),
        (
            "provider_message_id",
            " provider-incompativel ",
            queue_worker.TrustedInboundIdentityErrorCode.INVALID_TRUSTED_INBOUND_IDENTITY,
        ),
        (
            "claim_id",
            None,
            queue_worker.TrustedInboundIdentityErrorCode.INVALID_QUEUE_CLAIM,
        ),
        (
            "claim_id",
            "x" * (queue_worker.MAX_AGENT_CLAIM_ID_BYTES + 1),
            queue_worker.TrustedInboundIdentityErrorCode.INVALID_QUEUE_CLAIM,
        ),
    ],
)
def test_worker_flag_on_rejects_incomplete_identity_before_any_io(
    monkeypatch,
    field: str,
    value: object,
    expected_code: queue_worker.TrustedInboundIdentityErrorCode,
) -> None:
    outcome = _trusted_outcome()
    setattr(outcome, field, value)
    calls: list[str] = []
    monkeypatch.setattr(
        queue_worker,
        "get_settings",
        lambda: SimpleNamespace(agent_trusted_inbound_identity_enabled=True),
    )

    with pytest.raises(
        queue_worker.TrustedInboundIdentityContractError
    ) as raised:
        queue_worker.run_agent_for_message(
            lambda: calls.append("session"),
            outcome,
            lambda: calls.append("ownership"),
            evolution_client=SimpleNamespace(
                send_text=lambda *_args: calls.append("send")
            ),
        )

    assert raised.value.code is expected_code
    assert calls == []
    assert "provider-incompativel" not in str(raised.value)


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "tampered",
        "wrong_igreja",
        "wrong_conversation",
        "wrong_inbound",
        "wrong_provider",
    ],
)
def test_runtime_flag_on_requires_intact_binding_before_any_io(
    monkeypatch,
    case: str,
) -> None:
    igreja_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    inbound_message_id = uuid.uuid4()
    provider_message_id = "3EB0RUNTIME"
    identity = (
        build_agent_turn_identity(
            igreja_id=(uuid.uuid4() if case == "wrong_igreja" else igreja_id),
            conversation_id=(
                uuid.uuid4() if case == "wrong_conversation" else conversation_id
            ),
            inbound_message_id=(
                uuid.uuid4() if case == "wrong_inbound" else inbound_message_id
            ),
            provider_message_id=(
                "3EB0OTHER" if case == "wrong_provider" else provider_message_id
            ),
        )
        if case != "missing"
        else None
    )
    if case == "tampered" and identity is not None:
        object.__setattr__(identity, "turn_id", f"agent_turn_v1_{'0' * 64}")
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: SimpleNamespace(agent_trusted_inbound_identity_enabled=True),
    )

    class _ForbiddenSession:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("identidade inválida não pode consultar o banco")

    with pytest.raises(AgentTurnIdentityError) as raised:
        runtime.process_inbound_message(
            _ForbiddenSession(),
            igreja_id=igreja_id,
            conversation_id=conversation_id,
            texto="mensagem sintética",
            turn_identity=identity,
            inbound_message_id=inbound_message_id,
            provider_message_id=provider_message_id,
        )

    assert raised.value.code is AgentTurnContractErrorCode.INVALID_TURN_IDENTITY


def test_oversized_claim_fails_before_utf8_encoding(monkeypatch) -> None:
    outcome = _trusted_outcome(
        claim_id="x" * (1024 * 1024),
    )
    encode_calls: list[str] = []
    monkeypatch.setattr(
        queue_worker,
        "_encode_agent_claim_id",
        lambda _claim_id: encode_calls.append("encode") or b"forbidden",
    )

    with pytest.raises(
        queue_worker.TrustedInboundIdentityContractError
    ) as raised:
        queue_worker._build_trusted_inbound_turn_identity(outcome)

    assert (
        raised.value.code
        is queue_worker.TrustedInboundIdentityErrorCode.INVALID_QUEUE_CLAIM
    )
    assert encode_calls == []


def test_worker_flag_off_preserves_legacy_runtime_signature(monkeypatch) -> None:
    calls: list[tuple[uuid.UUID, uuid.UUID, str | None]] = []
    outcome = queue_worker.IngestionOutcome(
        result=queue_worker.IngestionResult.REGISTERED,
        conversation_id=uuid.uuid4(),
        igreja_id=uuid.uuid4(),
        inbound=True,
        texto="mensagem sintética",
    )
    monkeypatch.setattr(
        queue_worker,
        "get_settings",
        lambda: SimpleNamespace(agent_trusted_inbound_identity_enabled=False),
    )
    monkeypatch.setattr(queue_worker, "mark_tenant_scoped", lambda *a, **k: None)
    monkeypatch.setattr(queue_worker, "require_tenant_scope", lambda *a, **k: None)

    def legacy_process(
        _session,
        *,
        igreja_id: uuid.UUID,
        conversation_id: uuid.UUID,
        texto: str | None,
    ):
        calls.append((igreja_id, conversation_id, texto))
        return SimpleNamespace(handled=False, suppressed=False, response=None)

    monkeypatch.setattr(runtime, "process_inbound_message", legacy_process)

    disposition = queue_worker.run_agent_for_message(
        lambda: SimpleNamespace(close=lambda: None),
        outcome,
    )

    assert disposition is queue_worker.AgentRunDisposition.COMPLETED
    assert calls == [(outcome.igreja_id, outcome.conversation_id, outcome.texto)]


def test_worker_uses_explicit_dedicated_factory_for_runtime_turn(monkeypatch) -> None:
    outcome = queue_worker.IngestionOutcome(
        result=queue_worker.IngestionResult.REGISTERED,
        conversation_id=uuid.uuid4(),
        igreja_id=uuid.uuid4(),
        inbound=True,
        texto="mensagem sintética",
    )
    calls: list[str] = []

    class _Session:
        def close(self) -> None:
            calls.append("close")

    def primary_factory():
        raise AssertionError("runtime must not use the primary factory")

    def dedicated_factory():
        calls.append("dedicated")
        return _Session()

    monkeypatch.setattr(
        queue_worker,
        "get_settings",
        lambda: SimpleNamespace(agent_trusted_inbound_identity_enabled=False),
    )
    monkeypatch.setattr(
        queue_worker,
        "_scope_dedicated_agent_session",
        lambda session, current: calls.append("dedicated_scope")
        or current.igreja_id,
    )
    monkeypatch.setattr(
        queue_worker,
        "_scope_agent_session",
        lambda *_args, **_kwargs: pytest.fail(
            "primary tenant scope must not be used for dedicated runtime"
        ),
    )
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda *_args, **_kwargs: SimpleNamespace(
            handled=False,
            suppressed=False,
            response=None,
        ),
    )

    disposition = queue_worker.run_agent_for_message(
        primary_factory,
        outcome,
        agent_session_factory=dedicated_factory,
    )

    assert disposition is queue_worker.AgentRunDisposition.COMPLETED
    assert calls == ["dedicated", "dedicated_scope", "close"]


def test_worker_durable_execution_uses_dedicated_factory_only_for_runtime(
    monkeypatch,
) -> None:
    """The reservation/lease remain primary while the turn uses the dedicated session."""

    outcome = _trusted_outcome()
    intent = SimpleNamespace(
        id=uuid.uuid4(),
        state=queue_worker._AGENT_REPLY_RESERVED,
        response="resposta sintética",
        provider_message_id="agent-reply-key",
    )
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        queue_worker,
        "get_settings",
        lambda: SimpleNamespace(agent_trusted_inbound_identity_enabled=False),
    )
    monkeypatch.setattr(
        queue_worker,
        "_reserve_agent_reply_intent",
        lambda factory, current: calls.append(("reserve", factory)) or intent,
    )

    class _Lease:
        def __init__(self, factory, current, key) -> None:
            calls.append(("lease", factory))

        def acquire(self) -> bool:
            return True

        def close(self) -> None:
            calls.append(("lease_close", None))

    monkeypatch.setattr(queue_worker, "_AgentExecutionLease", _Lease)
    monkeypatch.setattr(
        queue_worker,
        "_load_agent_reply_intent",
        lambda factory, current: calls.append(("load", factory)) or intent,
    )
    monkeypatch.setattr(
        queue_worker,
        "_transition_agent_reply_intent",
        lambda factory, current, current_intent, **kwargs: calls.append(
            ("transition", factory)
        )
        or True,
    )
    pending = SimpleNamespace(
        id=intent.id,
        state=queue_worker._AGENT_REPLY_PENDING,
        response=intent.response,
        provider_message_id=intent.provider_message_id,
    )
    monkeypatch.setattr(
        queue_worker,
        "_prepare_agent_reply_intent",
        lambda factory, current, response: calls.append(("prepare", factory))
        or pending,
    )
    monkeypatch.setattr(
        queue_worker,
        "_deliver_agent_reply_intent",
        lambda factory, current, current_intent, guard, **kwargs: calls.append(
            ("deliver", factory)
        ),
    )
    monkeypatch.setattr(
        queue_worker,
        "_scope_agent_execution_session",
        lambda session, current, *, dedicated: calls.append(
            ("scope_dedicated" if dedicated else "scope_primary", session)
        ),
    )
    monkeypatch.setattr(
        runtime,
        "process_inbound_message",
        lambda session, **kwargs: calls.append(("runtime", session))
        or SimpleNamespace(handled=True, suppressed=False, response="resposta sintética"),
    )

    def primary_factory():
        raise AssertionError("primary factory must not open the runtime session")

    class _DedicatedSession:
        def close(self) -> None:
            calls.append(("dedicated_close", None))

    def dedicated_factory():
        calls.append(("dedicated_factory", None))
        return _DedicatedSession()

    disposition = queue_worker.run_agent_for_message(
        primary_factory,
        outcome,
        agent_session_factory=dedicated_factory,
    )

    assert disposition is queue_worker.AgentRunDisposition.COMPLETED
    assert [name for name, _value in calls if name == "dedicated_factory"] == [
        "dedicated_factory"
    ]
    assert [name for name, _value in calls if name == "scope_dedicated"] == [
        "scope_dedicated"
    ]
    assert all(
        name != "scope_primary"
        for name, _value in calls
    )
    assert all(
        value is primary_factory
        for name, value in calls
        if name in {"reserve", "lease", "load", "transition", "prepare", "deliver"}
    )


def test_worker_explicitly_disabled_runtime_never_falls_back_to_primary(
    monkeypatch,
) -> None:
    outcome = _trusted_outcome()
    calls: list[str] = []

    def primary_factory():
        calls.append("primary")
        raise AssertionError("disabled runtime must not open primary session")

    monkeypatch.setattr(
        queue_worker,
        "get_settings",
        lambda: SimpleNamespace(agent_trusted_inbound_identity_enabled=True),
    )

    disposition = queue_worker.run_agent_for_message(
        primary_factory,
        outcome,
        agent_session_factory=None,
    )

    assert disposition is queue_worker.AgentRunDisposition.COMPLETED
    assert calls == []


def test_runtime_marker_selects_dedicated_scope_probe(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    session = SimpleNamespace(
        info={runtime.AGENT_RUNTIME_TENANT_KEY: str(tenant_id)},
    )
    calls: list[tuple[object, object]] = []

    monkeypatch.setattr(
        runtime,
        "verify_agent_runtime_scope",
        lambda current_session, current_tenant: calls.append(
            (current_session, current_tenant)
        ),
    )
    monkeypatch.setattr(
        runtime,
        "require_tenant_scope",
        lambda *_args, **_kwargs: pytest.fail(
            "dedicated runtime must not use authenticated-role scope"
        ),
    )

    runtime._require_agent_session_scope(session, tenant_id)

    assert calls == [(session, tenant_id)]


def test_worker_flag_on_never_falls_back_to_legacy_path(monkeypatch) -> None:
    outcome = _trusted_outcome()
    calls: list[str] = []
    monkeypatch.setattr(
        queue_worker,
        "get_settings",
        lambda: SimpleNamespace(agent_trusted_inbound_identity_enabled=True),
    )
    monkeypatch.setattr(
        queue_worker,
        "_agent_reply_idempotency_key",
        lambda _outcome: None,
    )

    with pytest.raises(
        queue_worker.TrustedInboundIdentityContractError
    ) as raised:
        queue_worker.run_agent_for_message(
            lambda: calls.append("session"),
            outcome,
            lambda: calls.append("ownership"),
        )

    assert (
        raised.value.code
        is queue_worker.TrustedInboundIdentityErrorCode.INVALID_QUEUE_CLAIM
    )
    assert calls == []


def test_worker_flag_on_passes_exact_built_identity_to_runtime(monkeypatch) -> None:
    outcome = _trusted_outcome()
    built_identities: list[object] = []
    runtime_identities: list[object] = []
    calls: list[str] = []
    real_builder = queue_worker._build_trusted_inbound_turn_identity

    def capture_builder(current):
        identity = real_builder(current)
        built_identities.append(identity)
        return identity

    def process(
        _session,
        *,
        igreja_id,
        conversation_id,
        texto,
        turn_identity,
        inbound_message_id,
        provider_message_id,
    ):
        assert inbound_message_id == turn_identity.inbound_message_id
        assert provider_message_id == turn_identity.provider_message_id
        runtime_identities.append(turn_identity)
        return SimpleNamespace(handled=False, suppressed=False, response=None)

    class _OfflineLease:
        def __init__(self, *_args, **_kwargs) -> None:
            calls.append("lease_init")

        def acquire(self) -> bool:
            calls.append("lease_acquire")
            return True

        def close(self) -> None:
            calls.append("lease_close")

    intent = SimpleNamespace(state=queue_worker._AGENT_REPLY_RESERVED)
    monkeypatch.setattr(
        queue_worker,
        "get_settings",
        lambda: SimpleNamespace(agent_trusted_inbound_identity_enabled=True),
    )
    monkeypatch.setattr(
        queue_worker,
        "_build_trusted_inbound_turn_identity",
        capture_builder,
    )
    monkeypatch.setattr(
        queue_worker,
        "_reserve_agent_reply_intent",
        lambda *_args, **_kwargs: intent,
    )
    monkeypatch.setattr(queue_worker, "_AgentExecutionLease", _OfflineLease)
    monkeypatch.setattr(
        queue_worker,
        "_load_agent_reply_intent",
        lambda *_args, **_kwargs: intent,
    )
    monkeypatch.setattr(
        queue_worker,
        "_transition_agent_reply_intent",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(queue_worker, "_scope_agent_session", lambda *a, **k: None)
    monkeypatch.setattr(runtime, "process_inbound_message", process)

    disposition = queue_worker.run_agent_for_message(
        lambda: SimpleNamespace(close=lambda: calls.append("session_close")),
        outcome,
    )

    assert disposition is queue_worker.AgentRunDisposition.COMPLETED
    assert len(built_identities) == 1
    assert runtime_identities == built_identities
    assert runtime_identities[0] is built_identities[0]
    assert calls == [
        "lease_init",
        "lease_acquire",
        "session_close",
        "lease_close",
    ]


@pytest.mark.parametrize(
    "raw_igreja_id",
    [None, "", "   ", "tenant-invalido"],
)
@pytest.mark.parametrize("durable", [False, True])
def test_worker_rejeita_tenant_ausente_ou_invalido_antes_de_efeitos(
    raw_igreja_id,
    durable: bool,
) -> None:
    calls: list[str] = []

    def session_factory():
        calls.append("session")
        raise AssertionError("tenant inválido não pode abrir sessão")

    def ownership_guard() -> None:
        calls.append("ownership")

    outcome = queue_worker.IngestionOutcome(
        result=queue_worker.IngestionResult.REGISTERED,
        conversation_id=uuid.uuid4(),
        igreja_id=raw_igreja_id,
        provider_message_id="provider-1" if durable else None,
        claim_id="claim-1" if durable else None,
        instance="instancia-de-teste",
        telefone="numero-sintetico",
        texto="mensagem sintética",
        inbound=True,
    )

    with pytest.raises(queue_worker.AgentTenantContextError) as raised:
        queue_worker.run_agent_for_message(
            session_factory,
            outcome,
            ownership_guard,
            evolution_client=SimpleNamespace(
                send_text=lambda *_args: calls.append("send")
            ),
        )

    assert calls == []
    assert str(raised.value) in {
        "igreja_id é obrigatório no runtime do agente",
        "igreja_id inválido no runtime do agente",
    }
    assert "tenant-invalido" not in str(raised.value)


def test_worker_sem_conversa_permanece_noop_sem_exigir_tenant() -> None:
    calls: list[str] = []
    outcome = queue_worker.IngestionOutcome(
        result=queue_worker.IngestionResult.IGNORED,
        conversation_id=None,
        igreja_id=None,
    )

    disposition = queue_worker.run_agent_for_message(
        lambda: calls.append("session"),
        outcome,
        lambda: calls.append("ownership"),
    )

    assert disposition is queue_worker.AgentRunDisposition.COMPLETED
    assert calls == []


def test_runtime_rejeita_tenant_invalido_antes_de_tocar_sessao() -> None:
    class _ForbiddenSession:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("tenant inválido não pode consultar o banco")

    with pytest.raises(
        TenantScopeVerificationError,
        match="igreja_id inválido",
    ):
        runtime.process_inbound_message(
            _ForbiddenSession(),
            igreja_id="tenant-invalido",
            conversation_id=uuid.uuid4(),
            texto="mensagem sintética",
        )


def test_runtime_rejeita_conversa_de_outro_tenant_mesmo_se_adapter_violar_filtro(
    monkeypatch,
) -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    conversation_id = uuid.uuid4()
    session = _RuntimeSession(
        [
            SimpleNamespace(
                id=conversation_id,
                igreja_id=tenant_b,
                pessoa_id=uuid.uuid4(),
            )
        ]
    )
    guard_calls: list[uuid.UUID] = []
    monkeypatch.setattr(
        runtime,
        "require_tenant_scope",
        lambda _session, *, expected_igreja_id, source: guard_calls.append(
            expected_igreja_id
        ),
    )

    with pytest.raises(
        TenantScopeVerificationError,
        match="conversa não pertence",
    ):
        runtime.process_inbound_message(
            session,
            igreja_id=tenant_a,
            conversation_id=conversation_id,
            texto="mensagem sintética",
        )

    assert guard_calls == [tenant_a]
    assert len(session.statements) == 1
    assert "conversations.igreja_id" in str(session.statements[0])


def test_runtime_rejeita_conversa_com_id_diferente_do_solicitado(
    monkeypatch,
) -> None:
    tenant_id = uuid.uuid4()
    requested_id = uuid.uuid4()
    session = _RuntimeSession(
        [
            SimpleNamespace(
                id=uuid.uuid4(),
                igreja_id=tenant_id,
                pessoa_id=uuid.uuid4(),
            )
        ]
    )
    monkeypatch.setattr(runtime, "require_tenant_scope", lambda *a, **k: None)

    with pytest.raises(
        TenantScopeVerificationError,
        match="conversa retornada não corresponde",
    ):
        runtime.process_inbound_message(
            session,
            igreja_id=tenant_id,
            conversation_id=requested_id,
            texto="mensagem sintética",
        )

    assert len(session.statements) == 1


def test_runtime_rejeita_pessoa_de_outro_tenant_mesmo_se_adapter_violar_filtro(
    monkeypatch,
) -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    conversation_id = uuid.uuid4()
    pessoa_id = uuid.uuid4()
    session = _RuntimeSession(
        [
            SimpleNamespace(
                id=conversation_id,
                igreja_id=tenant_a,
                pessoa_id=pessoa_id,
            ),
            SimpleNamespace(
                id=pessoa_id,
                igreja_id=tenant_b,
                optout=False,
                sem_interesse=False,
            ),
        ]
    )
    monkeypatch.setattr(runtime, "require_tenant_scope", lambda *a, **k: None)

    with pytest.raises(
        TenantScopeVerificationError,
        match="Pessoa não pertence",
    ):
        runtime.process_inbound_message(
            session,
            igreja_id=tenant_a,
            conversation_id=conversation_id,
            texto="mensagem sintética",
        )

    assert len(session.statements) == 2
    assert "pessoas.igreja_id" in str(session.statements[1])


def test_runtime_rejeita_pessoa_com_id_diferente_da_conversa(
    monkeypatch,
) -> None:
    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    expected_pessoa_id = uuid.uuid4()
    session = _RuntimeSession(
        [
            SimpleNamespace(
                id=conversation_id,
                igreja_id=tenant_id,
                pessoa_id=expected_pessoa_id,
            ),
            SimpleNamespace(
                id=uuid.uuid4(),
                igreja_id=tenant_id,
                optout=False,
                sem_interesse=False,
            ),
        ]
    )
    monkeypatch.setattr(runtime, "require_tenant_scope", lambda *a, **k: None)

    with pytest.raises(
        TenantScopeVerificationError,
        match="Pessoa retornada não corresponde",
    ):
        runtime.process_inbound_message(
            session,
            igreja_id=tenant_id,
            conversation_id=conversation_id,
            texto="mensagem sintética",
        )

    assert len(session.statements) == 2
