"""Barreiras fail-closed do runtime do agente por tenant."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.agent import runtime
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
