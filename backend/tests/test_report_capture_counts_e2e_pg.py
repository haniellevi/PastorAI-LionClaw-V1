"""B15: legacy report capture binds each count to its own label end to end.

A persisted inbound anchor goes through the real worker, trusted context,
privilege resolution from PostgreSQL rows and LangGraph. Only the provider and
the LLM are fakes. The turn must record the aggregate summary event and the
outbound reply, never an individual decision.
"""
from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app.agent import runtime as runtime_module
from app.db.models import (
    AgentActionProposal, AgentConfig, AgentConversationLog, AppUser,
    ConsentRecord, Conversation, Decision, LlmCredential, Message, Pessoa,
    UserRole,
)
from app.services import crypto, semantic_triage
from app.services.llm import LLMClient, LLMResult, LLMUsage
from app.workers import queue_worker as worker_module
from tests.conftest_rls import rls_database_url  # noqa: F401 - fixture dependency
from tests.test_messages_inbound_idempotency import (
    _ClassifiedEvolution, _agent_outcome, _factory, _seed_igreja_with_connection,
    _seed_inbound_anchor, _seed_tier_a_handoff_anchor, msg_engine_fx,  # noqa: F401
)

pytestmark = pytest.mark.rls_integration
_IGREJA = uuid.UUID("b15b15b1-0000-4000-8000-000000000001")
_TERM = "b15-test-v1"
_LEADER_PHONE = "5500000000000"
_CONTACT_PHONE = "5500000000002"
_REPORTS = (
    "presentes: 12\nvisitantes: 3\ndecisões: 1",
    "presentes: 12 visitantes: 3 decisões: 1",
)


@pytest.fixture
def b15_turn(msg_engine_fx: Engine, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    factory = _factory(msg_engine_fx)
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA, instance="b15-synthetic")
    leader_conversation, leader_id, _ = _seed_tier_a_handoff_anchor(
        factory, igreja_id=_IGREJA, provider_message_id="B15-SEED", texto="início sintético",
    )
    now = dt.datetime.now(dt.timezone.utc)
    with factory.begin() as session:
        app_user_id = uuid.uuid4()
        session.add(AppUser(id=app_user_id, igreja_id=_IGREJA, pessoa_id=leader_id,
                            nome="Líder Sintético", email="b15@example.test",
                            clerk_user_id="clerk-b15-synthetic", status="ativo"))
        session.flush()
        session.add(UserRole(igreja_id=_IGREJA, user_id=app_user_id, papel="pastor"))
        contact = Pessoa(igreja_id=_IGREJA, nome="Contato Sintético", telefone=_CONTACT_PHONE)
        session.add(contact)
        session.flush()
        contact_conversation = Conversation(igreja_id=_IGREJA, pessoa_id=contact.id,
                                            telefone=_CONTACT_PHONE, estado="ia",
                                            numero_oficial=True)
        session.add(contact_conversation)
        for pessoa_id in (leader_id, contact.id):
            session.add(ConsentRecord(igreja_id=_IGREJA, pessoa_id=pessoa_id,
                                      termo_versao=_TERM, aceite_em=now))
        session.add(AgentConfig(igreja_id=_IGREJA, comportamento="Teste sintético", ativo=True))
        session.add(LlmCredential(igreja_id=_IGREJA, provedor="openai", modelo="synthetic-model",
                                  api_key_encrypted="cipher-synthetic", validado=True, ativo=True))
        session.flush()
        contact_conversation_id = contact_conversation.id
    settings = SimpleNamespace(agent_term_version=_TERM,
                               agent_trusted_inbound_identity_enabled=False,
                               effective_session_secret="b15-secret-synthetic")
    llm_calls: list[str] = []

    def complete(_self, _system, user):
        llm_calls.append(user)
        return LLMResult(texto="Resposta sintética.",
                         usage=LLMUsage(modelo="synthetic", tokens_in=1, tokens_out=1, custo=0.0))

    monkeypatch.delenv("AGENT_PRIVILEGE_ENABLED_IGREJA_IDS", raising=False)
    monkeypatch.setattr(worker_module, "_whatsapp_reply_enabled", lambda _id: True)
    monkeypatch.setattr(worker_module, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime_module, "get_settings", lambda: settings)
    monkeypatch.setattr(semantic_triage, "tier_a_enabled_from_environment", lambda _id: False)
    monkeypatch.setattr(crypto, "decrypt_secret", lambda _cipher: "synthetic-key")
    monkeypatch.setattr(runtime_module, "decrypt_secret", lambda _cipher: "synthetic-key")
    monkeypatch.setattr(LLMClient, "complete", complete)
    return SimpleNamespace(factory=factory, leader_conversation=leader_conversation,
                           contact_conversation=contact_conversation_id, llm_calls=llm_calls)


def _run(turn, conversation_id: uuid.UUID, phone: str, provider_id: str, texto: str):
    inbound_id = _seed_inbound_anchor(
        turn.factory, igreja_id=_IGREJA, conversation_id=conversation_id,
        provider_message_id=provider_id, texto=texto,
    )
    outcome = _agent_outcome(conversation_id, provider_message_id=provider_id,
                             claim_id=f"claim-{provider_id}", inbound_message_id=inbound_id,
                             igreja_id=_IGREJA, instance="b15-synthetic", telefone=phone)
    evolution = _ClassifiedEvolution()
    disposition = worker_module.run_agent_for_message(turn.factory, outcome,
                                                       evolution_client=evolution)
    assert disposition is worker_module.AgentRunDisposition.COMPLETED
    return evolution


def _report_events(turn, conversation_id: uuid.UUID) -> list[dict]:
    with turn.factory() as session:
        return [row.payload for row in session.execute(
            select(AgentConversationLog).where(
                AgentConversationLog.igreja_id == _IGREJA,
                AgentConversationLog.conversation_id == conversation_id,
                AgentConversationLog.evento == "report_captured",
            )
        ).scalars()]


def _outbound(turn, conversation_id: uuid.UUID) -> list[str]:
    with turn.factory() as session:
        return list(session.execute(
            select(Message.texto).where(
                Message.igreja_id == _IGREJA,
                Message.conversation_id == conversation_id,
                Message.direcao == "out",
            ).order_by(Message.criado_em)
        ).scalars())


def _count(turn, model) -> int:
    with turn.factory() as session:
        return session.execute(select(func.count()).select_from(model).where(
            model.igreja_id == _IGREJA)).scalar_one()


@pytest.mark.parametrize("texto", _REPORTS)
def test_ministerial_report_binds_counts_to_labels(b15_turn, texto):
    evolution = _run(b15_turn, b15_turn.leader_conversation, _LEADER_PHONE, "B15-REPORT", texto)

    events = _report_events(b15_turn, b15_turn.leader_conversation)
    assert len(events) == 1
    resumo = events[0]["relatorio"]
    assert (resumo["presentes"], resumo["visitantes"], resumo["decisoes"]) == (12, 3, 1)
    expected = "12 presentes, 3 visitantes, 1 decisões"
    assert len(evolution.calls) == 1
    assert expected in evolution.calls[0][2]
    assert "confirmação humana" in evolution.calls[0][2]
    assert any(expected in (out or "") for out in _outbound(b15_turn, b15_turn.leader_conversation))
    # Report replies are deterministic and create no individual records.
    assert b15_turn.llm_calls == []
    assert _count(b15_turn, Decision) == 0
    assert _count(b15_turn, AgentActionProposal) == 0


@pytest.mark.parametrize("texto", _REPORTS)
def test_non_ministerial_report_text_gets_no_report_confirmation(b15_turn, texto):
    evolution = _run(b15_turn, b15_turn.contact_conversation, _CONTACT_PHONE, "B15-CONTACT", texto)

    assert _report_events(b15_turn, b15_turn.contact_conversation) == []
    assert len(evolution.calls) == 1
    assert "Relatório recebido" not in evolution.calls[0][2]
    assert all("Relatório recebido" not in (out or "")
               for out in _outbound(b15_turn, b15_turn.contact_conversation))
    assert _count(b15_turn, Decision) == 0
    assert _count(b15_turn, AgentActionProposal) == 0
