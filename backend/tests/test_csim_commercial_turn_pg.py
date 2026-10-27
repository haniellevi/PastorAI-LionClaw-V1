"""B5: CSIM comercial pelo turno real do worker em PostgreSQL descartável.

Inbound persistido -> ``run_agent_for_message`` -> catálogo/roteador/grafo reais
-> ``onboarding_node`` -> ``_apply_intake`` -> resposta persistida e entregue ao
Evolution fake. Só o LLM BYO (falha forçada: vale o rascunho determinístico) e
o Evolution são falsos; Jev e o turno privilegiado ficam com seus gates
fechados (padrão), então o turno segue o caminho legado da igreja piloto.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.agent import runtime as runtime_module
from app.db.models import (
    AgentConfig,
    AgentConversationLog,
    ConsentRecord,
    Conversation,
    LlmCredential,
    Message,
    Pessoa,
)
from app.services.llm import LLMClient, LLMProviderError
from app.workers import queue_worker as worker_module
from tests.conftest_rls import rls_database_url  # noqa: F401 - fixture dependency
from tests.test_messages_inbound_idempotency import (
    _IGREJA_A,
    _IGREJA_B,
    _ClassifiedEvolution,
    _agent_outcome,
    _factory,
    _seed_agent_conversation,
    _seed_igreja_with_connection,
    _seed_inbound_anchor,
    msg_engine_fx,  # noqa: F401 - fixture dependency
)

pytestmark = pytest.mark.rls_integration

_TERM = "b5-csim-synthetic-term"
_CLOSE = "No momento não conseguimos seguir o atendimento por aqui"
_GREETING = "Que bom falar com você!"


@pytest.fixture
def csim_turn(msg_engine_fx: Engine, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    factory = _factory(msg_engine_fx)
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA_A, instance="igreja-1")
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA_B, instance="igreja-b")
    conversation_id = _seed_agent_conversation(factory, igreja_id=_IGREJA_A)
    other_conversation_id = _seed_agent_conversation(factory, igreja_id=_IGREJA_B)
    with factory.begin() as session:
        conversation = session.get(Conversation, conversation_id)
        for igreja_id in (_IGREJA_A, _IGREJA_B):
            session.add(
                AgentConfig(igreja_id=igreja_id, comportamento="Sintético", ativo=True)
            )
            session.add(
                LlmCredential(
                    igreja_id=igreja_id,
                    provedor="openai",
                    modelo="gpt-5.6-luna",
                    api_key_encrypted="cipher-synthetic",
                    validado=True,
                    ativo=True,
                )
            )
        session.add(
            ConsentRecord(
                igreja_id=_IGREJA_A,
                pessoa_id=conversation.pessoa_id,
                termo_versao=_TERM,
                aceite_em=dt.datetime.now(dt.timezone.utc),
            )
        )
        other = session.get(Conversation, other_conversation_id)
        pessoa_id = conversation.pessoa_id
        other_pessoa_id = other.pessoa_id

    settings = SimpleNamespace(
        agent_term_version=_TERM,
        agent_trusted_inbound_identity_enabled=False,
        agent_default_model="gpt-5.6-luna",
        effective_session_secret="b5-secret-synthetic",
    )
    monkeypatch.delenv("JEV_ENABLED_IGREJA_IDS", raising=False)
    monkeypatch.delenv("AGENT_PRIVILEGE_ENABLED_IGREJA_IDS", raising=False)
    # Igreja A é a piloto do WhatsApp (equivale a listá-la em whatsapp_piloto).
    monkeypatch.setattr(
        worker_module, "_whatsapp_reply_enabled", lambda gid: gid == _IGREJA_A
    )
    monkeypatch.setattr(worker_module, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime_module, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime_module, "decrypt_secret", lambda _c: "synthetic-key")

    def _llm_down(*_args, **_kwargs):
        raise LLMProviderError("synthetic outage")

    monkeypatch.setattr(LLMClient, "complete", _llm_down)
    return SimpleNamespace(
        factory=factory,
        conversation_id=conversation_id,
        pessoa_id=pessoa_id,
        other_pessoa_id=other_pessoa_id,
    )


def _send(turn, provider_id: str, texto: str) -> _ClassifiedEvolution:
    inbound_id = _seed_inbound_anchor(
        turn.factory,
        igreja_id=_IGREJA_A,
        conversation_id=turn.conversation_id,
        provider_message_id=provider_id,
        texto=texto,
    )
    evolution = _ClassifiedEvolution()
    worker_module.run_agent_for_message(
        turn.factory,
        _agent_outcome(
            turn.conversation_id,
            provider_message_id=provider_id,
            claim_id=f"claim-{provider_id}",
            inbound_message_id=inbound_id,
        ),
        evolution_client=evolution,
    )
    return evolution


def _pessoa(turn, pessoa_id=None) -> Pessoa:
    with turn.factory() as session:
        return session.get(Pessoa, pessoa_id or turn.pessoa_id)


def _outbound_texts(turn) -> list[str]:
    with turn.factory() as session:
        return list(
            session.execute(
                select(Message.texto)
                .where(
                    Message.igreja_id == _IGREJA_A,
                    Message.conversation_id == turn.conversation_id,
                    Message.direcao == "out",
                    Message.texto.is_not(None),
                )
                .order_by(Message.criado_em)
            ).scalars()
        )


def _events(turn, evento: str) -> int:
    with turn.factory() as session:
        return len(
            session.execute(
                select(AgentConversationLog.id).where(
                    AgentConversationLog.igreja_id == _IGREJA_A,
                    AgentConversationLog.evento == evento,
                )
            ).all()
        )


def _set_pessoa(turn, **values) -> None:
    with turn.factory.begin() as session:
        pessoa = session.get(Pessoa, turn.pessoa_id)
        for key, value in values.items():
            setattr(pessoa, key, value)


@pytest.mark.parametrize(
    "texto",
    [
        "trabalho numa empresa e quero conhecer a célula",
        "minha empresa fechou, preciso de oração",
        "paguei o boleto do curso?",
        # Terceira pessoa / pergunta genérica não é oferta do próprio contato.
        "meu filho quer vender produtos, preciso de oração por ele",
        "como vender produtos para ajudar a igreja?",
        "os vizinhos querem oferecer publicidade, peço oração",
    ],
)
def test_former_false_positive_keeps_contact_in_funnel(csim_turn, texto) -> None:
    evolution = _send(csim_turn, "B5-FP-1", texto)

    pessoa = _pessoa(csim_turn)
    assert pessoa.sem_interesse is False
    assert pessoa.sem_interesse_motivo is None
    assert len(evolution.calls) == 1
    assert _GREETING in evolution.calls[0][2]
    assert _CLOSE not in evolution.calls[0][2]

    # O contato segue no funil: o turno seguinte também é respondido.
    follow_up = _send(csim_turn, "B5-FP-2", "qual o horário?")
    assert len(follow_up.calls) == 1
    assert _events(csim_turn, "agent_suppressed_csim") == 0
    assert len(_outbound_texts(csim_turn)) == 2


def test_explicit_commercial_offer_still_closes_and_suppresses(csim_turn) -> None:
    evolution = _send(
        csim_turn, "B5-OFFER-1", "quero apresentar uma proposta comercial"
    )

    pessoa = _pessoa(csim_turn)
    assert pessoa.sem_interesse is True
    assert pessoa.sem_interesse_motivo == "comercial/empresa"
    assert len(evolution.calls) == 1
    assert _CLOSE in evolution.calls[0][2]

    follow_up = _send(
        csim_turn, "B5-OFFER-2", "trabalho numa empresa e quero conhecer a célula"
    )
    assert follow_up.calls == []
    assert _events(csim_turn, "agent_suppressed_csim") == 1
    assert _pessoa(csim_turn).sem_interesse is True
    # A outra igreja não é tocada pelo turno da igreja A.
    other = _pessoa(csim_turn, csim_turn.other_pessoa_id)
    assert other.sem_interesse is False


def test_existing_csim_is_not_cleared_by_former_false_positive(csim_turn) -> None:
    _set_pessoa(csim_turn, sem_interesse=True, sem_interesse_motivo="comercial/empresa")

    evolution = _send(csim_turn, "B5-KEEP-1", "minha empresa fechou, preciso de oração")

    pessoa = _pessoa(csim_turn)
    assert pessoa.sem_interesse is True
    assert pessoa.sem_interesse_motivo == "comercial/empresa"
    assert evolution.calls == []
    assert _outbound_texts(csim_turn) == []


def test_existing_optout_refuses_before_classification(csim_turn) -> None:
    _set_pessoa(csim_turn, optout=True)

    evolution = _send(csim_turn, "B5-OPTOUT-1", "quero oferecer publicidade")

    pessoa = _pessoa(csim_turn)
    assert pessoa.optout is True
    assert pessoa.sem_interesse is False
    assert evolution.calls == []
    assert _outbound_texts(csim_turn) == []
