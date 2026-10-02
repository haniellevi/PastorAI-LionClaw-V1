"""S3 WhatsApp actions through the real worker and disposable PostgreSQL.

The provider and LLM are fakes.  The source anchor, proposal, outbound fence,
confirmation, domain effect and receipt remain real committed database rows.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import hmac
import json
import uuid
from threading import Barrier, Event, Lock, current_thread
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.agent import runtime as runtime_module
from app.db.models import (
    AgentActionProposal, AgentActionReceipt, AgentConfig, AppUser, Celula,
    CelulaMembro, CelulaPresenca, CelulaReuniao, ConsentRecord, Decision,
    LlmCredential, Message, Pessoa, UserRole, AiUsageLog, Conversation,
)
from app.services import crypto, semantic_triage, whatsapp_privilege
from app.services.agent_privilege_routing import ChoiceSelection
from app.services.llm import LLMClient, LLMUsage, TypedChoiceResult
from app.workers import queue_worker as worker_module
from tests.conftest_rls import rls_database_url  # noqa: F401 - fixture dependency
from tests.test_consolidacao_open_unique_concurrency import _TRIGGER_SQL
from tests.test_messages_inbound_idempotency import (
    _ClassifiedEvolution, _agent_outcome, _factory, _seed_igreja_with_connection,
    _seed_inbound_anchor, _seed_tier_a_handoff_anchor, msg_engine_fx,
)

pytestmark = pytest.mark.rls_integration
_IGREJA = uuid.UUID("4a4a4a4a-0000-4000-8000-000000000001")
_TERM = "s3-test-v1"
_PHONE = "5500000000000"


@pytest.fixture
def s3_turn(msg_engine_fx: Engine, monkeypatch: pytest.MonkeyPatch):
    """Reuse MSG-IDEMP's isolated PG schema and install the real decision trigger."""
    factory = _factory(msg_engine_fx)
    _seed_igreja_with_connection(factory, igreja_id=_IGREJA, instance="s3-synthetic")
    conversation_id, actor_id, _ = _seed_tier_a_handoff_anchor(
        factory, igreja_id=_IGREJA, provider_message_id="S3-SEED", texto="início sintético",
    )
    with msg_engine_fx.begin() as connection:
        connection.exec_driver_sql(_TRIGGER_SQL)
    target_id = uuid.uuid4()
    cell_id = uuid.uuid4()
    meeting_id = uuid.uuid4()
    app_user_id = uuid.uuid4()
    with factory.begin() as session:
        session.add(Pessoa(id=target_id, igreja_id=_IGREJA, nome="Alvo Sintético", telefone="5500000000001"))
        session.flush()
        session.add(AppUser(id=app_user_id, igreja_id=_IGREJA, pessoa_id=actor_id,
                            nome="Operador Sintético", email="s3@example.test",
                            clerk_user_id="clerk-s3-synthetic", status="ativo"))
        session.flush()
        session.add(UserRole(igreja_id=_IGREJA, user_id=app_user_id, papel="pastor"))
        session.add(ConsentRecord(igreja_id=_IGREJA, pessoa_id=actor_id,
                                  termo_versao=_TERM, aceite_em=dt.datetime.now(dt.timezone.utc)))
        session.add(AgentConfig(igreja_id=_IGREJA, comportamento="Teste sintético", ativo=True))
        session.add(LlmCredential(igreja_id=_IGREJA, provedor="openai", modelo="gpt-5.6-luna",
                                  api_key_encrypted="cipher-synthetic", validado=True, ativo=True))
        session.add(Celula(id=cell_id, igreja_id=_IGREJA, nome="Célula Sintética",
                           lider_id=actor_id, cobertura_espiritual="Pastor sintético", ativo=True))
        session.flush()
        session.add(CelulaReuniao(id=meeting_id, igreja_id=_IGREJA, celula_id=cell_id,
                                  data=dt.date.today(), status="planejada"))
        session.add(CelulaMembro(igreja_id=_IGREJA, celula_id=cell_id,
                                 pessoa_id=target_id, ativo=True))
    settings = SimpleNamespace(agent_term_version=_TERM,
                               agent_trusted_inbound_identity_enabled=False,
                               effective_session_secret="s3-secret-synthetic")
    monkeypatch.setattr(whatsapp_privilege, "PRIVILEGE_APPROVED_RELEASE_ID", "synthetic-approved-release")
    monkeypatch.setenv("AGENT_PRIVILEGE_ENABLED_IGREJA_IDS", str(_IGREJA))
    monkeypatch.setattr(worker_module, "_whatsapp_reply_enabled", lambda _id: True)
    monkeypatch.setattr(worker_module, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime_module, "get_settings", lambda: settings)
    monkeypatch.setattr(whatsapp_privilege, "get_settings", lambda: settings)
    monkeypatch.setattr(semantic_triage, "tier_a_enabled_from_environment", lambda _id: False)
    monkeypatch.setattr(crypto, "decrypt_secret", lambda _cipher: "synthetic-key")
    return SimpleNamespace(factory=factory, engine=msg_engine_fx,
                           conversation_id=conversation_id, app_user_id=app_user_id,
                           target_id=target_id, meeting_id=meeting_id)


def _inbound(turn, provider_id: str, text: str):
    inbound_id = _seed_inbound_anchor(
        turn.factory, igreja_id=_IGREJA, conversation_id=turn.conversation_id,
        provider_message_id=provider_id, texto=text,
    )
    return _agent_outcome(turn.conversation_id, provider_message_id=provider_id,
                          claim_id=f"claim-{provider_id}", inbound_message_id=inbound_id,
                          igreja_id=_IGREJA, instance="s3-synthetic", telefone=_PHONE)


def _rows(turn, model):
    with turn.factory() as session:
        return session.execute(select(model).where(model.igreja_id == _IGREJA)).scalars().all()


def _effect_count(turn, action: str) -> int:
    model = Decision if action == "registrar_decisao" else CelulaPresenca
    with turn.factory() as session:
        return session.execute(select(func.count()).select_from(model).where(
            model.igreja_id == _IGREJA, model.pessoa_id == turn.target_id,
        )).scalar_one()


def _fake_choices(monkeypatch, turn, action: str, *, invalid: bool = False) -> list[str]:
    calls: list[str] = []

    def choose(_self, _system, user_prompt, *, schema_name, choices, timeout_seconds):
        # SQLAlchemy's checked-out connection count is zero at every LLM boundary.
        # A held transaction or row lock would make this assertion fail.
        assert turn.engine.pool.checkedout() == 0
        assert timeout_seconds > 0
        calls.append(schema_name)
        state = json.loads(user_prompt)
        if invalid:
            return ChoiceSelection("not-in-schema")
        if schema_name == "s3_route":
            selected = "restrita"
        elif schema_name == "s3_tool":
            selected = action
        else:
            selected = next(handle for handle, summary in state["candidatos"].items()
                            if "Alvo Sintético" in summary)
        assert selected in choices
        return TypedChoiceResult(selected, LLMUsage(modelo="synthetic", tokens_in=3, tokens_out=1, custo=0.0001))

    monkeypatch.setattr(LLMClient, "generate_typed", choose)
    return calls


def _revoke_role(turn):
    with turn.factory.begin() as session:
        session.execute(delete(UserRole).where(UserRole.igreja_id == _IGREJA,
                                                UserRole.user_id == turn.app_user_id))


@pytest.mark.parametrize("action", ("registrar_decisao", "marcar_presenca"))
def test_whatsapp_action_requires_delivered_summary_and_new_sim_once(s3_turn, monkeypatch, action):
    calls = _fake_choices(monkeypatch, s3_turn, action)
    evolution = _ClassifiedEvolution()
    request = _inbound(s3_turn, f"S3-REQUEST-{action}", f"Pedido sintético {action} de Alvo Sintético")
    assert worker_module.run_agent_for_message(s3_turn.factory, request,
                                                evolution_client=evolution) is worker_module.AgentRunDisposition.COMPLETED
    proposals = _rows(s3_turn, AgentActionProposal)
    assert len(proposals) == 1
    assert proposals[0].action == action
    assert proposals[0].state == "pendente"
    assert proposals[0].summary_message_id is not None
    assert proposals[0].delivered_at is not None
    with s3_turn.factory() as session:
        summary = session.get(Message, proposals[0].summary_message_id)
        assert summary is not None
        assert summary.agent_reply_state == worker_module._AGENT_REPLY_CONFIRMED
        assert summary.agent_privilege_context["kind"] == "summary"
    assert _effect_count(s3_turn, action) == 0
    assert _rows(s3_turn, AgentActionReceipt) == []
    assert len(evolution.calls) == 1
    assert "Responda SIM ou NÃO" in evolution.calls[0][2]
    assert calls == ["s3_route", "s3_tool", "s3_handle"]
    assert len(_rows(s3_turn, AiUsageLog)) == 3

    confirmation = _inbound(s3_turn, f"S3-CONFIRM-{action}", "SIM")
    assert worker_module.run_agent_for_message(s3_turn.factory, confirmation,
                                                evolution_client=evolution) is worker_module.AgentRunDisposition.COMPLETED
    assert _effect_count(s3_turn, action) == 1
    receipts = _rows(s3_turn, AgentActionReceipt)
    assert len(receipts) == 1
    assert receipts[0].proposal_id == proposals[0].id
    assert receipts[0].confirmation_message_id == confirmation.inbound_message_id
    assert len(evolution.calls) == 2
    assert "Comprovante:" in evolution.calls[1][2]
    assert _rows(s3_turn, AgentActionProposal)[0].state == "executada"
    assert calls == ["s3_route", "s3_tool", "s3_handle"]

    for outcome in (request, confirmation, request, confirmation):
        worker_module.run_agent_for_message(s3_turn.factory, outcome, evolution_client=evolution)
    assert _effect_count(s3_turn, action) == 1
    assert len(_rows(s3_turn, AgentActionReceipt)) == 1
    assert len(evolution.calls) == 2
    assert calls == ["s3_route", "s3_tool", "s3_handle"]
    assert len(_rows(s3_turn, AiUsageLog)) == 3


def test_role_revoked_before_sim_cannot_execute_pending_proposal(s3_turn, monkeypatch):
    calls = _fake_choices(monkeypatch, s3_turn, "marcar_presenca")
    evolution = _ClassifiedEvolution()
    request = _inbound(s3_turn, "S3-ROLE-REQUEST", "Confirme presença de Alvo Sintético")
    worker_module.run_agent_for_message(s3_turn.factory, request, evolution_client=evolution)
    assert _rows(s3_turn, AgentActionProposal)[0].state == "pendente"
    _revoke_role(s3_turn)
    confirmation = _inbound(s3_turn, "S3-ROLE-SIM", "SIM")
    worker_module.run_agent_for_message(s3_turn.factory, confirmation, evolution_client=evolution)
    assert _effect_count(s3_turn, "marcar_presenca") == 0
    assert _rows(s3_turn, AgentActionReceipt) == []
    assert calls == ["s3_route", "s3_tool", "s3_handle"]


def test_summary_retry_after_role_revocation_never_sends_or_executes(s3_turn, monkeypatch):
    calls = _fake_choices(monkeypatch, s3_turn, "registrar_decisao")
    evolution = _ClassifiedEvolution("falhou_retentavel", "aceito")
    request = _inbound(s3_turn, "S3-RETRY-REQUEST", "Registre decisão de Alvo Sintético")
    with pytest.raises(worker_module.AgentReplyRetryable):
        worker_module.run_agent_for_message(s3_turn.factory, request,
                                            evolution_client=evolution)
    assert len(evolution.calls) == 1
    assert _rows(s3_turn, AgentActionProposal)[0].state == "preparada"
    _revoke_role(s3_turn)
    worker_module.run_agent_for_message(s3_turn.factory, request, evolution_client=evolution)
    assert len(evolution.calls) == 1
    assert _effect_count(s3_turn, "registrar_decisao") == 0
    assert _rows(s3_turn, AgentActionReceipt) == []
    assert calls == ["s3_route", "s3_tool", "s3_handle"]


def test_invalid_typed_choice_handoffs_without_proposal_or_effect(s3_turn, monkeypatch):
    calls = _fake_choices(monkeypatch, s3_turn, "registrar_decisao", invalid=True)
    evolution = _ClassifiedEvolution()
    request = _inbound(s3_turn, "S3-SCHEMA-REQUEST", "Pedido sintético de Alvo Sintético")
    worker_module.run_agent_for_message(s3_turn.factory, request, evolution_client=evolution)
    assert calls == ["s3_route"]
    assert evolution.calls == []
    assert _rows(s3_turn, AgentActionProposal) == []
    assert _rows(s3_turn, AgentActionReceipt) == []
    assert _effect_count(s3_turn, "registrar_decisao") == 0


def test_explicit_handoff_revokes_delivered_proposal_even_after_ia_resumes(s3_turn, monkeypatch):
    _fake_choices(monkeypatch, s3_turn, "marcar_presenca")
    evolution = _ClassifiedEvolution()
    request = _inbound(s3_turn, "S3-HUMAN-REQUEST", "Confirme presença de Alvo Sintético")
    worker_module.run_agent_for_message(s3_turn.factory, request, evolution_client=evolution)
    assert _rows(s3_turn, AgentActionProposal)[0].state == "pendente"
    request_human = _inbound(s3_turn, "S3-HUMAN-HANDOFF", "quero falar com um pastor")
    worker_module.run_agent_for_message(s3_turn.factory, request_human, evolution_client=evolution)
    assert _rows(s3_turn, AgentActionProposal)[0].state == "cancelada"
    with s3_turn.factory.begin() as session:
        conversation = session.get(Conversation, s3_turn.conversation_id)
        assert conversation.estado == "humano"
        conversation.estado = "ia"
    confirmation = _inbound(s3_turn, "S3-HUMAN-SIM", "SIM")
    worker_module.run_agent_for_message(s3_turn.factory, confirmation, evolution_client=evolution)
    assert _effect_count(s3_turn, "marcar_presenca") == 0
    assert _rows(s3_turn, AgentActionReceipt) == []


def test_typed_handoff_records_actual_usage_once(s3_turn, monkeypatch):
    def handoff(_self, *_args, **_kwargs):
        assert s3_turn.engine.pool.checkedout() == 0
        return TypedChoiceResult("handoff", LLMUsage(modelo="synthetic", tokens_in=3, tokens_out=1, custo=0.0001))
    monkeypatch.setattr(LLMClient, "generate_typed", handoff)
    request = _inbound(s3_turn, "S3-TYPED-HANDOFF", "Pedido sintético de Alvo Sintético")
    evolution = _ClassifiedEvolution()
    for _ in range(2):
        worker_module.run_agent_for_message(s3_turn.factory, request, evolution_client=evolution)
    assert len(_rows(s3_turn, AiUsageLog)) == 1
    assert evolution.calls == []


def test_regular_reply_uses_typed_suppression_without_open_transaction(s3_turn, monkeypatch):
    from app.services.llm import TypedLLMResult
    calls = []
    usage = LLMUsage(modelo='synthetic', tokens_in=2, tokens_out=1, custo=0.0001)
    def choose(_self, *_args, **_kwargs):
        assert s3_turn.engine.pool.checkedout() == 0
        calls.append('route')
        return TypedChoiceResult('nenhuma', usage)
    def answer(_self, *_args, **_kwargs):
        assert s3_turn.engine.pool.checkedout() == 0
        calls.append('answer')
        return TypedLLMResult(False, 'Resposta sintética segura.', usage)
    monkeypatch.setattr(LLMClient, 'generate_typed', choose)
    monkeypatch.setattr(LLMClient, 'complete_typed', answer)
    monkeypatch.setattr(runtime_module, 'decrypt_secret', lambda _cipher: 'synthetic-key')
    evolution = _ClassifiedEvolution()
    request = _inbound(s3_turn, 'S3-GENERAL', 'Explique uma informação geral')
    worker_module.run_agent_for_message(s3_turn.factory, request, evolution_client=evolution)
    assert calls == ['route', 'answer']
    assert evolution.calls[0][2] == 'Resposta sintética segura.'
    assert len(_rows(s3_turn, AiUsageLog)) == 2
    assert _rows(s3_turn, AgentActionProposal) == []


def test_action_sim_never_accepts_a_changed_lgpd_term(s3_turn, monkeypatch):
    _fake_choices(monkeypatch, s3_turn, 'marcar_presenca')
    evolution = _ClassifiedEvolution()
    request = _inbound(s3_turn, 'S3-TERM-REQUEST', 'Confirme presença de Alvo Sintético')
    worker_module.run_agent_for_message(s3_turn.factory, request, evolution_client=evolution)
    settings = SimpleNamespace(agent_term_version='new-synthetic-term',
                               agent_trusted_inbound_identity_enabled=False,
                               effective_session_secret='s3-secret-synthetic')
    monkeypatch.setattr(runtime_module, 'get_settings', lambda: settings)
    monkeypatch.setattr(whatsapp_privilege, 'get_settings', lambda: settings)
    confirmation = _inbound(s3_turn, 'S3-TERM-SIM', 'SIM')
    worker_module.run_agent_for_message(s3_turn.factory, confirmation, evolution_client=evolution)
    assert _rows(s3_turn, AgentActionProposal)[0].state == 'cancelada'
    assert _effect_count(s3_turn, 'marcar_presenca') == 0
    assert all(row.termo_versao != 'new-synthetic-term' for row in _rows(s3_turn, ConsentRecord))


@pytest.mark.parametrize('changed', ['phone', 'instance'])
def test_summary_retry_rejects_mismatched_destination(s3_turn, monkeypatch, changed):
    from dataclasses import replace
    _fake_choices(monkeypatch, s3_turn, 'registrar_decisao')
    evolution = _ClassifiedEvolution('falhou_retentavel', 'aceito')
    request = _inbound(s3_turn, 'S3-DEST-REQUEST', 'Registre decisão de Alvo Sintético')
    with pytest.raises(worker_module.AgentReplyRetryable):
        worker_module.run_agent_for_message(s3_turn.factory, request, evolution_client=evolution)
    unsafe = replace(request, **({'telefone': '5500000000009'} if changed == 'phone' else {'instance': 'other-synthetic'}))
    worker_module.run_agent_for_message(s3_turn.factory, unsafe, evolution_client=evolution)
    assert len(evolution.calls) == 1
    assert _rows(s3_turn, AgentActionProposal)[0].state == 'cancelada'


def test_private_action_summary_is_excluded_from_later_llm_history(s3_turn, monkeypatch):
    _fake_choices(monkeypatch, s3_turn, 'registrar_decisao')
    evolution = _ClassifiedEvolution()
    request = _inbound(s3_turn, 'S3-HISTORY-REQUEST', 'Registre decisão de Alvo Sintético')
    worker_module.run_agent_for_message(s3_turn.factory, request, evolution_client=evolution)
    next_turn = _inbound(s3_turn, 'S3-HISTORY-NEXT', 'Outra pergunta')
    with s3_turn.factory() as session:
        history = runtime_module._load_recent_conversation_history(session,
            igreja_id=_IGREJA, conversation_id=s3_turn.conversation_id,
            current_message_id=next_turn.inbound_message_id,
            provider_message_id=next_turn.provider_message_id)
    assert all('Responda SIM ou NÃO' not in text for _, _, text in history)
    assert any('Registre decisão de Alvo Sintético' in text for _, _, text in history)


def test_expired_proposal_cannot_be_confirmed(s3_turn, monkeypatch):
    calls = _fake_choices(monkeypatch, s3_turn, 'marcar_presenca')
    evolution = _ClassifiedEvolution()
    worker_module.run_agent_for_message(s3_turn.factory,
        _inbound(s3_turn, 'S3-EXPIRE-REQUEST', 'Confirme presença de Alvo Sintético'), evolution_client=evolution)
    with s3_turn.factory.begin() as session:
        proposal = session.execute(select(AgentActionProposal).where(
            AgentActionProposal.igreja_id == _IGREJA)).scalar_one()
        proposal.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
    worker_module.run_agent_for_message(s3_turn.factory,
        _inbound(s3_turn, 'S3-EXPIRE-SIM', 'SIM'), evolution_client=evolution)
    assert _effect_count(s3_turn, 'marcar_presenca') == 0
    assert _rows(s3_turn, AgentActionReceipt) == []
    assert _rows(s3_turn, AgentActionProposal)[0].state == 'expirada'
    assert calls == ['s3_route', 's3_tool', 's3_handle']


def test_domain_effect_rolls_back_if_receipt_transaction_fails(s3_turn, monkeypatch):
    from app.services import agent_privilege_catalog as catalog
    _fake_choices(monkeypatch, s3_turn, 'registrar_decisao')
    evolution = _ClassifiedEvolution()
    worker_module.run_agent_for_message(s3_turn.factory,
        _inbound(s3_turn, 'S3-ROLLBACK-REQUEST', 'Registre decisão de Alvo Sintético'), evolution_client=evolution)
    original = catalog.execute_catalog_action
    def failing(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('synthetic failure after domain flush')
    monkeypatch.setattr(catalog, 'execute_catalog_action', failing)
    confirmation = _inbound(s3_turn, 'S3-ROLLBACK-SIM', 'SIM')
    with pytest.raises(RuntimeError, match='synthetic failure'):
        worker_module.run_agent_for_message(s3_turn.factory, confirmation, evolution_client=evolution)
    assert _effect_count(s3_turn, 'registrar_decisao') == 0
    assert _rows(s3_turn, AgentActionReceipt) == []
    assert _rows(s3_turn, AgentActionProposal)[0].state == 'pendente'
    assert len(evolution.calls) == 1
    monkeypatch.setattr(catalog, 'execute_catalog_action', original)
    worker_module.run_agent_for_message(s3_turn.factory, confirmation, evolution_client=evolution)
    assert _effect_count(s3_turn, 'registrar_decisao') == 1
    assert len(_rows(s3_turn, AgentActionReceipt)) == 1
    assert len(evolution.calls) == 2


@pytest.mark.parametrize('collision', ['person', 'person_beyond_limit', 'cell', 'meeting'])
def test_ambiguous_targets_have_no_action_handle(s3_turn, collision):
    from app.services.whatsapp_privilege import resolve_whatsapp_privilege_context
    from app.services.agent_privilege_catalog import build_catalog
    if collision in {'person', 'person_beyond_limit'}:
        with s3_turn.factory.begin() as session:
            if collision == 'person_beyond_limit':
                for n in range(12):
                    session.add(Pessoa(igreja_id=_IGREJA, nome=f'Aa Sintético {n}', telefone=f'55000000001{n:02}'))
            session.add(Pessoa(igreja_id=_IGREJA, nome='ALVO Sintetico', telefone='5500000000999'))
    elif collision == 'cell':
        with s3_turn.factory.begin() as session:
            session.add(Celula(igreja_id=_IGREJA, nome='CELULA SINTETICA',
                cobertura_espiritual='Teste', ativo=True))
    else:
        with s3_turn.factory.begin() as session:
            original = session.get(CelulaReuniao, s3_turn.meeting_id)
            session.add(CelulaReuniao(igreja_id=_IGREJA, celula_id=original.celula_id,
                data=original.data, status='planejada'))
    request = _inbound(s3_turn, 'S3-AMBIGUOUS', 'Pedido sintético de Alvo Sintético')
    with s3_turn.factory() as session:
        worker_module._scope_agent_execution_session(session, request, dedicated=False)
        context = resolve_whatsapp_privilege_context(session, igreja_id=_IGREJA,
            conversation_id=s3_turn.conversation_id, inbound_message_id=request.inbound_message_id)
        _, targets = build_catalog(session, context)
    for target in targets.values():
        if target.arguments.get('pessoa_id') == str(s3_turn.target_id):
            assert target.code != 'marcar_presenca'
            if collision in {'person', 'person_beyond_limit'}:
                assert target.code != 'registrar_decisao'


def test_summary_retry_revalidates_target_membership_before_send(s3_turn, monkeypatch):
    _fake_choices(monkeypatch, s3_turn, 'marcar_presenca')
    evolution = _ClassifiedEvolution('falhou_retentavel', 'aceito')
    request = _inbound(s3_turn, 'S3-MEMBERSHIP-RETRY', 'Confirme presença de Alvo Sintético')
    with pytest.raises(worker_module.AgentReplyRetryable):
        worker_module.run_agent_for_message(s3_turn.factory, request, evolution_client=evolution)
    with s3_turn.factory.begin() as session:
        member = session.execute(select(CelulaMembro).where(
            CelulaMembro.igreja_id == _IGREJA, CelulaMembro.pessoa_id == s3_turn.target_id)).scalar_one()
        member.ativo = False
    worker_module.run_agent_for_message(s3_turn.factory, request, evolution_client=evolution)
    assert len(evolution.calls) == 1
    assert _rows(s3_turn, AgentActionProposal)[0].state == 'cancelada'


def test_expired_identity_challenge_is_not_sent_on_retry(s3_turn, monkeypatch):
    from app.db.models import AgentIdentityChallenge
    def choose(_self, *_args, schema_name, **_kwargs):
        assert s3_turn.engine.pool.checkedout() == 0
        return ChoiceSelection({'s3_route': 'restrita', 's3_tool': 'consultar_vinculo', 's3_handle': 'h1'}[schema_name])
    monkeypatch.setattr(LLMClient, 'generate_typed', choose)
    evolution = _ClassifiedEvolution('falhou_retentavel', 'aceito')
    request = _inbound(s3_turn, 'S3-CHALLENGE-EXPIRES', 'Consulte meu vínculo')
    with pytest.raises(worker_module.AgentReplyRetryable):
        worker_module.run_agent_for_message(s3_turn.factory, request, evolution_client=evolution)
    with s3_turn.factory.begin() as session:
        challenge = session.execute(select(AgentIdentityChallenge).where(
            AgentIdentityChallenge.igreja_id == _IGREJA)).scalar_one()
        challenge.issued_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=6)
        challenge.challenge_expires_at = challenge.issued_at + dt.timedelta(minutes=5)
    worker_module.run_agent_for_message(s3_turn.factory, request, evolution_client=evolution)
    assert len(evolution.calls) == 1
    with s3_turn.factory() as session:
        reply = session.execute(select(Message).where(Message.igreja_id == _IGREJA,
            Message.agent_privilege_context['kind'].astext == 'challenge')).scalar_one()
        assert reply.agent_reply_state == worker_module._AGENT_REPLY_SUPPRESSED


def test_target_revoked_during_routing_handoffs_without_rerouting(s3_turn, monkeypatch):
    calls = _fake_choices(monkeypatch, s3_turn, 'marcar_presenca')
    original = LLMClient.generate_typed
    def choose(self, *args, schema_name, **kwargs):
        answer = original(self, *args, schema_name=schema_name, **kwargs)
        if schema_name == 's3_handle':
            with s3_turn.factory.begin() as session:
                member = session.execute(select(CelulaMembro).where(
                    CelulaMembro.igreja_id == _IGREJA,
                    CelulaMembro.pessoa_id == s3_turn.target_id)).scalar_one()
                member.ativo = False
        return answer
    monkeypatch.setattr(LLMClient, 'generate_typed', choose)
    evolution = _ClassifiedEvolution()
    request = _inbound(s3_turn, 'S3-REVOKED-DURING-ROUTE', 'Confirme presença de Alvo Sintético')
    for _ in range(2):
        worker_module.run_agent_for_message(s3_turn.factory, request, evolution_client=evolution)
    assert calls == ['s3_route', 's3_tool', 's3_handle']
    assert evolution.calls == []
    assert _rows(s3_turn, AgentActionProposal) == []
    with s3_turn.factory() as session:
        assert session.get(Conversation, s3_turn.conversation_id).estado == 'humano'


@pytest.mark.parametrize('acceptance', ['Aceito', 'sim, concordo'])
def test_changed_term_cancels_old_action_before_any_acceptance(s3_turn, monkeypatch, acceptance):
    _fake_choices(monkeypatch, s3_turn, 'marcar_presenca')
    evolution = _ClassifiedEvolution()
    worker_module.run_agent_for_message(s3_turn.factory,
        _inbound(s3_turn, 'S3-TERM-AFFIX-REQUEST', 'Confirme presença de Alvo Sintético'), evolution_client=evolution)
    settings = SimpleNamespace(agent_term_version='new-synthetic-term',
        agent_trusted_inbound_identity_enabled=False, effective_session_secret='s3-secret-synthetic')
    monkeypatch.setattr(runtime_module, 'get_settings', lambda: settings)
    monkeypatch.setattr(whatsapp_privilege, 'get_settings', lambda: settings)
    monkeypatch.setattr(runtime_module, '_reply_with_llm', lambda *_a, **_k: (None, None))
    worker_module.run_agent_for_message(s3_turn.factory,
        _inbound(s3_turn, 'S3-TERM-AFFIX-ACCEPT', acceptance), evolution_client=evolution)
    assert _rows(s3_turn, AgentActionProposal)[0].state == 'cancelada'
    worker_module.run_agent_for_message(s3_turn.factory,
        _inbound(s3_turn, 'S3-TERM-AFFIX-SIM', 'SIM'), evolution_client=evolution)
    assert _effect_count(s3_turn, 'marcar_presenca') == 0
    assert _rows(s3_turn, AgentActionReceipt) == []


@pytest.mark.parametrize('text,expected', [('oi', False), ('registre uma decisão', False),
    ('registre decisão de Alvo Sintético', True)])
def test_catalog_shortlists_only_names_explicit_in_persisted_request(s3_turn, text, expected):
    from app.services.whatsapp_privilege import resolve_whatsapp_privilege_context
    from app.services.agent_privilege_catalog import build_catalog, ACTIONS
    request = _inbound(s3_turn, 'S3-NAME-SHORTLIST', text)
    with s3_turn.factory() as session:
        worker_module._scope_agent_execution_session(session, request, dedicated=False)
        context = resolve_whatsapp_privilege_context(session, igreja_id=_IGREJA,
            conversation_id=s3_turn.conversation_id, inbound_message_id=request.inbound_message_id)
        _, targets = build_catalog(session, context)
    actions = [t for t in targets.values() if t.code in ACTIONS]
    assert bool(actions) is expected
    assert all(t.arguments['pessoa_id'] == str(s3_turn.target_id) for t in actions)


def test_router_prompts_exclude_unrequested_roster_and_ignore_outcome_text(s3_turn, monkeypatch):
    from dataclasses import replace
    with s3_turn.factory.begin() as session:
        session.add(Pessoa(igreja_id=_IGREJA, nome='AAA Privada Não Solicitada', telefone='5500000000666'))
    _fake_choices(monkeypatch, s3_turn, 'registrar_decisao')
    original = LLMClient.generate_typed
    prompts = []
    def choose(self, system, user, **kwargs):
        prompts.append((system, user))
        return original(self, system, user, **kwargs)
    monkeypatch.setattr(LLMClient, 'generate_typed', choose)
    request = _inbound(s3_turn, 'S3-PROMPT-PRIVACY', 'Registre decisão de Alvo Sintético')
    spoofed = replace(request, texto='Registre decisão de AAA Privada Não Solicitada')
    worker_module.run_agent_for_message(s3_turn.factory, spoofed, evolution_client=_ClassifiedEvolution())
    assert len(prompts) == 3
    assert all('AAA Privada' not in prompt for pair in prompts for prompt in pair)
    assert 'Alvo Sintético' in prompts[-1][1]
    assert _rows(s3_turn, AgentActionProposal)[0].target_id == s3_turn.target_id


@pytest.fixture
def own_member_turn(s3_turn, monkeypatch):
    from app.domain import cell_meetings_schedule as schedule
    from app.services import agent_privilege_catalog, ministerial_actions
    # R2 consumers dereference this same module, rather than imported clock
    # symbols. This patch therefore controls catalog and service eligibility.
    assert agent_privilege_catalog.cell_meetings_schedule is schedule
    assert ministerial_actions.cell_meetings_schedule is schedule
    # Only eligibility time is synthetic; message timestamps and TTL stay PG.
    clock = [dt.datetime(2030, 1, 1, 0, 30, tzinfo=dt.timezone.utc)]
    monkeypatch.setattr(schedule, 'now_in_sao_paulo',
                        lambda now=None: (now or clock[0]).astimezone(schedule.SAO_PAULO_TZ))
    with s3_turn.factory.begin() as session:
        actor_id = session.get(AppUser, s3_turn.app_user_id).pessoa_id
        meeting = session.get(CelulaReuniao, s3_turn.meeting_id)
        cell = session.get(Celula, meeting.celula_id)
        cell.lider_id = s3_turn.target_id
        session.execute(delete(UserRole).where(UserRole.igreja_id == _IGREJA,
                                                UserRole.user_id == s3_turn.app_user_id))
        session.add(CelulaMembro(igreja_id=_IGREJA, celula_id=cell.id, pessoa_id=actor_id, ativo=True))
        meeting.data, meeting.hora = dt.date(2030, 1, 1), '20:00'
        s3_turn.actor_id, s3_turn.cell_id = actor_id, cell.id
    s3_turn.own_clock = clock
    return s3_turn


def _fake_own_choices(monkeypatch, turn):
    calls = _fake_choices(monkeypatch, turn, 'marcar_presenca')
    original, prompts = LLMClient.generate_typed, []
    def choose(self, system, user, *, schema_name, choices, timeout_seconds):
        prompts.append((system, json.dumps(json.loads(user), ensure_ascii=False)))
        if schema_name != 's3_handle':
            return original(self, system, user, schema_name=schema_name,
                            choices=choices, timeout_seconds=timeout_seconds)
        assert turn.engine.pool.checkedout() == 0 and timeout_seconds > 0
        candidates = json.loads(user)['candidatos']
        own = [handle for handle, summary in candidates.items()
               if summary.startswith('Confirmar minha presença')]
        assert len(own) == 1 and own[0] in choices
        calls.append(schema_name)
        return TypedChoiceResult(own[0], LLMUsage(modelo='synthetic', tokens_in=3, tokens_out=1, custo=0.0001))
    monkeypatch.setattr(LLMClient, 'generate_typed', choose)
    return calls, prompts


def _own_pending(turn, monkeypatch):
    from app.services.whatsapp_privilege import PrivilegeContext, resolve_whatsapp_privilege_context
    calls, prompts = _fake_own_choices(monkeypatch, turn)
    evolution = _ClassifiedEvolution()
    request = _inbound(turn, 'OWN-REQUEST', 'Quero confirmar minha presença na próxima reunião da minha célula.')
    with turn.factory() as session:
        worker_module._scope_agent_execution_session(session, request, dedicated=False)
        context = resolve_whatsapp_privilege_context(session, igreja_id=_IGREJA,
            conversation_id=turn.conversation_id, inbound_message_id=request.inbound_message_id)
        assert type(context) is PrivilegeContext
        assert context.roles == frozenset() and context.owned_cell_ids == ()
        assert context.pessoa_id == turn.actor_id
    worker_module.run_agent_for_message(turn.factory, request, evolution_client=evolution)
    assert calls == ['s3_route', 's3_tool', 's3_handle']
    rows = _rows(turn, AgentActionProposal)
    assert len(rows) == 1 and rows[0].state == 'pendente'
    assert rows[0].summary_message_id is not None and rows[0].delivered_at is not None
    with turn.factory() as session:
        summary = session.get(Message, rows[0].summary_message_id)
        assert summary is not None and summary.agent_reply_state == worker_module._AGENT_REPLY_CONFIRMED
        assert summary.agent_privilege_context['kind'] == 'summary'
    assert _rows(turn, CelulaPresenca) == _rows(turn, AgentActionReceipt) == []
    return evolution, calls, prompts, request


def test_own_member_pg_summary_sim_replay_and_panel_source(own_member_turn, monkeypatch):
    from app.routers.cell_discipulo import _find_presenca
    turn = own_member_turn
    evolution, calls, _, _ = _own_pending(turn, monkeypatch)
    proposal = _rows(turn, AgentActionProposal)[0]
    assert (proposal.action, proposal.target_kind, proposal.target_id) == ('marcar_presenca', 'pessoa', turn.actor_id)
    assert proposal.arguments_json == {'pessoa_id': str(turn.actor_id), 'reuniao_id': str(turn.meeting_id)}
    assert len(evolution.calls) == 1 and 'Responda SIM ou NÃO' in evolution.calls[0][2]
    confirmation = _inbound(turn, 'OWN-SIM', 'SIM')
    worker_module.run_agent_for_message(turn.factory, confirmation, evolution_client=evolution)
    presence, receipt = _rows(turn, CelulaPresenca), _rows(turn, AgentActionReceipt)
    assert len(presence) == len(receipt) == 1
    assert (presence[0].pessoa_id, presence[0].reuniao_id, presence[0].origem, presence[0].estado) == (
        turn.actor_id, turn.meeting_id, 'auto', 'confirmada')
    assert receipt[0].proposal_id == proposal.id and receipt[0].effect_reference == str(presence[0].id)
    assert receipt[0].confirmation_message_id == confirmation.inbound_message_id
    assert _rows(turn, AgentActionProposal)[0].state == 'executada'
    assert len(evolution.calls) == 2 and 'Comprovante:' in evolution.calls[1][2]
    for outcome in (confirmation, _inbound(turn, 'OWN-NEW-SIM', 'SIM')):
        worker_module.run_agent_for_message(turn.factory, outcome, evolution_client=evolution)
    assert len(_rows(turn, CelulaPresenca)) == len(_rows(turn, AgentActionReceipt)) == len(_rows(turn, AgentActionProposal)) == 1
    assert calls == ['s3_route', 's3_tool', 's3_handle'] and len(evolution.calls) == 2
    with turn.factory() as session:
        worker_module._scope_agent_execution_session(session, confirmation, dedicated=False)
        source = _find_presenca(session, _IGREJA, turn.meeting_id, turn.actor_id)
        assert source is not None and source.id == presence[0].id and source.origem == 'auto'


@pytest.mark.parametrize('revocation', ['membership', 'meeting_passed'])
def test_own_member_pg_revalidates_membership_and_sao_paulo_time(own_member_turn, monkeypatch, revocation):
    turn = own_member_turn
    evolution, calls, _, _ = _own_pending(turn, monkeypatch)
    if revocation == 'membership':
        with turn.factory.begin() as session:
            member = session.execute(select(CelulaMembro).where(CelulaMembro.igreja_id == _IGREJA,
                CelulaMembro.pessoa_id == turn.actor_id, CelulaMembro.celula_id == turn.cell_id)).scalar_one()
            member.ativo = False
    else:
        turn.own_clock[0] += dt.timedelta(days=1)  # Jan 1, 21:30 in São Paulo, after 20:00.
    worker_module.run_agent_for_message(turn.factory, _inbound(turn, 'OWN-REVOKED-SIM', 'SIM'), evolution_client=evolution)
    assert _rows(turn, CelulaPresenca) == _rows(turn, AgentActionReceipt) == []
    assert _rows(turn, AgentActionProposal)[0].state == 'rejeitada'
    assert calls == ['s3_route', 's3_tool', 's3_handle']
    assert all('Comprovante:' not in call[2] for call in evolution.calls)


def test_own_member_pg_foreign_and_third_targets_never_enter_prompt_or_effect(own_member_turn, monkeypatch):
    from app.services.agent_privilege_catalog import build_catalog
    from app.services.whatsapp_privilege import resolve_whatsapp_privilege_context
    turn = own_member_turn
    tenant, person, cell, meeting = (uuid.UUID(int=value) for value in range(900, 904))
    _seed_igreja_with_connection(turn.factory, igreja_id=tenant, instance='own-foreign-synthetic')
    with turn.factory.begin() as session:
        session.add(Pessoa(id=person, igreja_id=tenant, nome='FOREIGN-SYNTHETIC', telefone=_PHONE))
        session.flush()
        session.add(Celula(id=cell, igreja_id=tenant, nome='FOREIGN-CELL-SYNTHETIC', lider_id=person,
                          cobertura_espiritual='Cobertura sintética', ativo=True))
        session.flush()
        session.add(CelulaMembro(igreja_id=tenant, pessoa_id=person, celula_id=cell, ativo=True))
        session.add(CelulaReuniao(id=meeting, igreja_id=tenant, celula_id=cell,
                                data=dt.date(2030, 1, 1), hora='20:00', status='planejada'))
    evolution, _, prompts, request = _own_pending(turn, monkeypatch)
    with turn.factory() as session:
        worker_module._scope_agent_execution_session(session, request, dedicated=False)
        context = resolve_whatsapp_privilege_context(session, igreja_id=_IGREJA,
            conversation_id=turn.conversation_id, inbound_message_id=request.inbound_message_id)
        _, mapping = build_catalog(session, context)
        targets = [target for target in mapping.values() if target.code == 'marcar_presenca']
        assert len(targets) == 1 and dict(targets[0].arguments) == {
            'pessoa_id': str(turn.actor_id), 'reuniao_id': str(turn.meeting_id)}
    assert len(prompts) == 3
    assert all(marker not in prompt for pair in prompts for prompt in pair for marker in (
        'Alvo Sintético', 'FOREIGN-SYNTHETIC', 'FOREIGN-CELL-SYNTHETIC',
        str(turn.target_id), str(tenant), str(person), str(cell), str(meeting)))
    worker_module.run_agent_for_message(turn.factory, _inbound(turn, 'OWN-ISOLATED-SIM', 'SIM'), evolution_client=evolution)
    assert [row.pessoa_id for row in _rows(turn, CelulaPresenca)] == [turn.actor_id]
    with turn.factory() as session:
        assert session.execute(select(func.count()).select_from(CelulaPresenca).where(CelulaPresenca.igreja_id == tenant)).scalar_one() == 0
    third_request = _inbound(turn, 'OWN-THIRD-REQUEST', 'Quero confirmar a presença de Alvo Sintético.')
    with turn.factory() as session:
        worker_module._scope_agent_execution_session(session, third_request, dedicated=False)
        context = resolve_whatsapp_privilege_context(session, igreja_id=_IGREJA,
            conversation_id=turn.conversation_id, inbound_message_id=third_request.inbound_message_id)
        assert not any(target.code == 'marcar_presenca' for target in build_catalog(session, context)[1].values())


def test_own_member_pg_failure_after_domain_flush_rolls_back_before_delivery(own_member_turn, monkeypatch):
    from app.services import agent_privilege_catalog as catalog
    turn = own_member_turn
    evolution, _, _, _ = _own_pending(turn, monkeypatch)
    original = catalog.execute_catalog_action
    def failing(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('synthetic own failure after flush')
    monkeypatch.setattr(catalog, 'execute_catalog_action', failing)
    confirmation = _inbound(turn, 'OWN-FAILURE-SIM', 'SIM')
    with pytest.raises(RuntimeError, match='^synthetic own failure after flush$'):
        worker_module.run_agent_for_message(turn.factory, confirmation, evolution_client=evolution)
    assert _rows(turn, CelulaPresenca) == _rows(turn, AgentActionReceipt) == []
    assert _rows(turn, AgentActionProposal)[0].state == 'pendente' and len(evolution.calls) == 1


@pytest.mark.parametrize('locked', ['actor', 'meeting', 'cell', 'member', 'presence'])
def test_own_member_pg_service_locks_block_independent_updates_until_rollback(own_member_turn, locked):
    from app.deps import CurrentUser
    from app.services.ministerial_actions import confirm_meeting_attendance
    from app.services.whatsapp_privilege import PrivilegeContext, resolve_whatsapp_privilege_context
    turn = own_member_turn
    if locked == 'presence':
        with turn.factory.begin() as session:
            session.add(CelulaPresenca(id=uuid.UUID(int=950), igreja_id=_IGREJA,
                reuniao_id=turn.meeting_id, pessoa_id=turn.actor_id, estado='ausente', origem='lider'))
    statements = {
        'actor': update(AppUser).where(AppUser.igreja_id == _IGREJA,
            AppUser.id == turn.app_user_id).values(nome='Ator sintético atualizado'),
        'meeting': update(CelulaReuniao).where(CelulaReuniao.igreja_id == _IGREJA,
            CelulaReuniao.id == turn.meeting_id).values(hora='21:00'),
        'cell': update(Celula).where(Celula.igreja_id == _IGREJA,
            Celula.id == turn.cell_id).values(ativo=False),
        'member': update(CelulaMembro).where(CelulaMembro.igreja_id == _IGREJA,
            CelulaMembro.celula_id == turn.cell_id,
            CelulaMembro.pessoa_id == turn.actor_id).values(ativo=False),
        'presence': update(CelulaPresenca).where(CelulaPresenca.igreja_id == _IGREJA,
            CelulaPresenca.reuniao_id == turn.meeting_id,
            CelulaPresenca.pessoa_id == turn.actor_id).values(estado='ausente'),
    }
    request = _inbound(turn, 'OWN-LOCK-REQUEST',
        'Quero confirmar minha presença na próxima reunião da minha célula.')
    with turn.factory() as transaction_a:
        worker_module._scope_agent_execution_session(transaction_a, request, dedicated=False)
        context = resolve_whatsapp_privilege_context(transaction_a, igreja_id=_IGREJA,
            conversation_id=turn.conversation_id, inbound_message_id=request.inbound_message_id)
        assert type(context) is PrivilegeContext and context.pessoa_id == turn.actor_id
        user = CurrentUser(app_user_id=str(context.app_user_id), igreja_id=str(context.igreja_id),
            clerk_user_id='', email='', nome='', roles=context.roles)
        attendance = confirm_meeting_attendance(transaction_a, user, reuniao_id=turn.meeting_id,
            pessoa_id=None, expected_actor_pessoa_id=context.pessoa_id)
        assert (attendance.pessoa_id, attendance.estado, attendance.origem) == (turn.actor_id, 'confirmada', 'auto')
        backend_a = transaction_a.execute(text('SELECT pg_backend_pid()')).scalar_one()
        with turn.factory() as transaction_b:
            transaction_b.execute(text("SET LOCAL lock_timeout = '100ms'"))
            assert transaction_b.execute(text('SELECT pg_backend_pid()')).scalar_one() != backend_a
            with pytest.raises(DBAPIError) as exc:
                transaction_b.execute(statements[locked])
            code = getattr(exc.value.orig, 'sqlstate', None) or getattr(exc.value.orig, 'pgcode', None)
            assert code == '55P03'
            transaction_b.rollback()
        # Release A without committing its presence insert/update. No sleeps,
        # threads, extra engines or mocked locking are involved.
        transaction_a.rollback()
    with turn.factory.begin() as transaction_b:
        transaction_b.execute(text("SET LOCAL lock_timeout = '100ms'"))
        assert transaction_b.execute(statements[locked]).rowcount == 1
    assert _rows(turn, AgentActionReceipt) == []
    if locked != 'presence':
        assert _rows(turn, CelulaPresenca) == []


@pytest.mark.parametrize('revocation', ['actor_relink', 'inactive_cell'])
def test_own_member_pg_committed_actor_or_cell_revocation_before_sim_has_no_effect(own_member_turn, monkeypatch, revocation):
    from app.services.llm import TypedLLMResult
    from app.services.whatsapp_privilege import PrivilegeContext, PublicWhatsappContext, resolve_whatsapp_privilege_context
    turn = own_member_turn
    evolution, _, _, _ = _own_pending(turn, monkeypatch)
    with turn.factory.begin() as transaction_b:
        if revocation == 'actor_relink':
            statement = update(AppUser).where(AppUser.igreja_id == _IGREJA,
                AppUser.id == turn.app_user_id, AppUser.pessoa_id == turn.actor_id).values(pessoa_id=turn.target_id)
        else:
            statement = update(Celula).where(Celula.igreja_id == _IGREJA,
                Celula.id == turn.cell_id, Celula.ativo.is_(True)).values(ativo=False)
        assert transaction_b.execute(statement).rowcount == 1
    confirmation = _inbound(turn, 'OWN-COMMITTED-REVOCATION-SIM', 'SIM')
    with turn.factory() as session:
        worker_module._scope_agent_execution_session(session, confirmation, dedicated=False)
        context = resolve_whatsapp_privilege_context(session, igreja_id=_IGREJA,
            conversation_id=turn.conversation_id, inbound_message_id=confirmation.inbound_message_id)
        if revocation == 'actor_relink':
            assert type(context) is PublicWhatsappContext
        else:
            assert type(context) is PrivilegeContext and context.pessoa_id == turn.actor_id
    if revocation == 'actor_relink':
        # Loss of the privileged identity can enter the ordinary reply path.
        # Keep its existing LLM seams synthetic too, without faking resolution.
        usage = LLMUsage(modelo='synthetic', tokens_in=2, tokens_out=1, custo=0.0001)
        def no_action(_self, *_args, choices, **_kwargs):
            assert turn.engine.pool.checkedout() == 0 and 'nenhuma' in choices
            return TypedChoiceResult('nenhuma', usage)
        def safe_reply(_self, *_args, **_kwargs):
            assert turn.engine.pool.checkedout() == 0
            return TypedLLMResult(False, 'Resposta sintética segura.', usage)
        monkeypatch.setattr(LLMClient, 'generate_typed', no_action)
        monkeypatch.setattr(LLMClient, 'complete_typed', safe_reply)
        monkeypatch.setattr(runtime_module, 'decrypt_secret', lambda _cipher: 'synthetic-key')
    worker_module.run_agent_for_message(turn.factory, confirmation, evolution_client=evolution)
    assert _rows(turn, CelulaPresenca) == _rows(turn, AgentActionReceipt) == []
    assert _rows(turn, AgentActionProposal)[0].state != 'executada'
    assert all('Comprovante:' not in call[2] for call in evolution.calls)


def test_own_member_pg_confirmation_exactly_at_meeting_start_is_eligible_e4(own_member_turn, monkeypatch):
    turn = own_member_turn
    evolution, _, _, _ = _own_pending(turn, monkeypatch)
    turn.own_clock[0] = dt.datetime(2030, 1, 1, 23, 0, tzinfo=dt.timezone.utc)  # Jan 1, 20:00 São Paulo.
    confirmation = _inbound(turn, 'OWN-E4-EQUALITY-SIM', 'SIM')
    worker_module.run_agent_for_message(turn.factory, confirmation, evolution_client=evolution)
    presence, receipts = _rows(turn, CelulaPresenca), _rows(turn, AgentActionReceipt)
    assert len(presence) == len(receipts) == 1
    assert (presence[0].pessoa_id, presence[0].reuniao_id, presence[0].origem) == (turn.actor_id, turn.meeting_id, 'auto')
    assert receipts[0].effect_reference == str(presence[0].id)
    assert receipts[0].confirmation_message_id == confirmation.inbound_message_id
    assert _rows(turn, AgentActionProposal)[0].state == 'executada'
    assert len(evolution.calls) == 2 and 'Comprovante:' in evolution.calls[-1][2]


@pytest.mark.parametrize('calendar,eligible', [
    ('next_many', True), ('generic_many', False), ('earliest_tie', False),
    ('absent_two', False), ('absent_single', True),
    ('sentinel_same_date', False), ('sentinel_later_date', True),
])
def test_own_member_pg_bounded_next_selection_from_real_meetings(own_member_turn, calendar, eligible):
    from app.services.agent_privilege_catalog import build_catalog
    from app.services.whatsapp_privilege import PrivilegeContext, resolve_whatsapp_privilege_context
    turn = own_member_turn
    with turn.factory.begin() as session:
        if calendar == 'absent_single':
            session.get(CelulaReuniao, turn.meeting_id).hora = None
        if calendar in ('next_many', 'generic_many', 'absent_single'):
            extra = [(dt.date(2030, 1, 2), '20:00'), (dt.date(2030, 1, 3), '20:00')]
        elif calendar in ('earliest_tie', 'absent_two'):
            extra = [(dt.date(2030, 1, 1), None if calendar == 'absent_two' else '20:00')]
        else:
            # 64 rows on the first date, including the seeded 20:00; row 65
            # either leaves that date complete or makes it incomplete.
            extra = [(dt.date(2030, 1, 1), '23:00')] * 63
            extra.append((dt.date(2030, 1, 2 if calendar == 'sentinel_later_date' else 1), '23:00'))
        for number, (date, hour) in enumerate(extra):
            session.add(CelulaReuniao(id=uuid.UUID(int=1000 + number), igreja_id=_IGREJA,
                celula_id=turn.cell_id, data=date, hora=hour, status='planejada'))
    message = 'Quero confirmar minha presença na próxima reunião da minha célula.'
    if calendar == 'generic_many':
        message = message.replace('próxima ', '')
    request = _inbound(turn, 'OWN-NEXT-CALENDAR', message)
    with turn.factory() as session:
        worker_module._scope_agent_execution_session(session, request, dedicated=False)
        context = resolve_whatsapp_privilege_context(session, igreja_id=_IGREJA,
            conversation_id=turn.conversation_id, inbound_message_id=request.inbound_message_id)
        assert type(context) is PrivilegeContext and context.owned_cell_ids == ()
        targets = [target for target in build_catalog(session, context)[1].values()
                   if target.code == 'marcar_presenca']
        assert [dict(target.arguments) for target in targets] == ([{
            'pessoa_id': str(turn.actor_id), 'reuniao_id': str(turn.meeting_id)}] if eligible else [])
    assert _rows(turn, AgentActionProposal) == _rows(turn, AgentActionReceipt) == _rows(turn, CelulaPresenca) == []


@pytest.fixture
def own_member_unique_turn(own_member_turn):
    # Only this disposable fixture mirrors the existing PR2 migration index.
    # Base.metadata has no presence UNIQUE index; no migration is executed.
    with own_member_turn.engine.begin() as connection:
        connection.exec_driver_sql(
            'CREATE UNIQUE INDEX celula_presenca_pessoa_uq '
            'ON celula_presenca (igreja_id, reuniao_id, pessoa_id)')
        definition = connection.execute(text(
            "SELECT indisunique, indisvalid, indnkeyatts, "
            "pg_get_indexdef(indexrelid, 1, true), "
            "pg_get_indexdef(indexrelid, 2, true), "
            "pg_get_indexdef(indexrelid, 3, true) "
            "FROM pg_index WHERE indexrelid = "
            "'msg_idemp1.celula_presenca_pessoa_uq'::regclass")).one()
        assert tuple(definition) == (True, True, 3, 'igreja_id', 'reuniao_id', 'pessoa_id')
    return own_member_turn


def test_own_member_pg_existing_unique_index_rejects_duplicate_in_savepoint(own_member_unique_turn):
    turn = own_member_unique_turn
    with turn.factory.begin() as session:
        session.add(CelulaPresenca(id=uuid.UUID(int=1910), igreja_id=_IGREJA,
            reuniao_id=turn.meeting_id, pessoa_id=turn.actor_id, estado='confirmada', origem='auto'))
        session.flush()
        with pytest.raises(IntegrityError) as exc:
            with session.begin_nested():
                session.add(CelulaPresenca(id=uuid.UUID(int=1911), igreja_id=_IGREJA,
                    reuniao_id=turn.meeting_id, pessoa_id=turn.actor_id, estado='confirmada', origem='auto'))
                session.flush()
        code = getattr(exc.value.orig, 'sqlstate', None) or getattr(exc.value.orig, 'pgcode', None)
        assert code == '23505'
        assert session.execute(select(func.count()).select_from(CelulaPresenca).where(
            CelulaPresenca.igreja_id == _IGREJA, CelulaPresenca.reuniao_id == turn.meeting_id,
            CelulaPresenca.pessoa_id == turn.actor_id)).scalar_one() == 1
    assert len(_rows(turn, CelulaPresenca)) == 1
    # This proves the constraint/savepoint, not the service's concurrent retry.


class _HttpProtocolQueue:
    """In-memory queue markers only; no Redis lease/recovery infrastructure."""
    def __init__(self):
        self.enqueued = []
        self._markers = {}
        self._lock = Lock()

    def enqueue(self, payload):
        with self._lock:
            self.enqueued.append(payload)

    def claim_processing(self, message_id, claim_id):
        with self._lock:
            marker = self._markers.get(message_id)
            if marker is None:
                self._markers[message_id] = (claim_id, False)
                return worker_module.ProcessingClaim.NEW
            if marker == (claim_id, False):
                return worker_module.ProcessingClaim.RESUMED
            return worker_module.ProcessingClaim.REJECTED

    def mark_processed(self, message_id, claim_id):
        with self._lock:
            assert self._markers[message_id] == (claim_id, False)
            self._markers[message_id] = (claim_id, True)

    def release_processed(self, message_id, claim_id):
        with self._lock:
            if self._markers.get(message_id) == (claim_id, False):
                del self._markers[message_id]


@pytest.fixture
def own_http_turn(own_member_unique_turn, monkeypatch):
    from app.routers import whatsapp
    turn = own_member_unique_turn
    turn.http_calls, turn.http_prompts = _fake_own_choices(monkeypatch, turn)
    turn.http_queue, turn.http_evolution, turn.http_outcomes = _HttpProtocolQueue(), _ClassifiedEvolution(), []
    turn.http_secret = 'http-presence-synthetic-only'
    monkeypatch.setattr(whatsapp, 'get_settings', lambda: SimpleNamespace(
        evolution_webhook_secret=turn.http_secret))
    app = FastAPI()
    app.include_router(whatsapp.router)
    app.dependency_overrides[whatsapp.get_webhook_queue] = lambda: turn.http_queue

    def real_runner(factory, outcome, ownership_guard):
        turn.http_outcomes.append(outcome)
        return worker_module.run_agent_for_message(factory, outcome, ownership_guard,
            evolution_client=turn.http_evolution)

    turn.http_worker = worker_module.QueueWorker(queue=turn.http_queue,
        session_factory=turn.factory, agent_runner=real_runner, media_resolver=None,
        worker_id='HTTP-PG-SYNTHETIC', heartbeat_publisher=lambda *_args: None)
    # No TestClient context manager: no lifespan/startup is invoked.
    turn.http_client = TestClient(app)
    try:
        yield turn
    finally:
        turn.http_client.close()
        app.dependency_overrides.clear()


def _http_enqueue(turn, provider_id, message):
    payload = {'event': 'messages.upsert', 'instance': 's3-synthetic', 'data': {
        'key': {'remoteJid': f'{_PHONE}@s.whatsapp.net', 'fromMe': False, 'id': provider_id},
        'pushName': 'Contato sintético', 'message': {'conversation': message}}}
    body = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    signature = hmac.new(turn.http_secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    queued = len(turn.http_queue.enqueued)
    response = turn.http_client.post('/whatsapp/webhook', content=body,
        headers={'content-type': 'application/json', 'x-evolution-signature': signature})
    assert response.status_code == 202 and response.json() == {'status': 'queued'}
    assert len(turn.http_queue.enqueued) == queued + 1
    captured = turn.http_queue.enqueued[-1]
    assert captured == json.loads(body)
    return worker_module._Envelope(payload=captured, claim_id=f'HTTP-PG-CLAIM-{queued + 1}')


def _http_pending(turn):
    before = len(_rows(turn, Message)), len(_rows(turn, Pessoa))
    envelope = _http_enqueue(turn, 'HTTP-OWN-REQUEST',
        'Quero confirmar minha presença na próxima reunião da minha célula.')
    assert (len(_rows(turn, Message)), len(_rows(turn, Pessoa))) == before
    assert turn.http_worker.handle_envelope(envelope) is worker_module.IngestionResult.REGISTERED
    request = [row for row in _rows(turn, Message) if row.provider_message_id == 'HTTP-OWN-REQUEST']
    assert len(request) == 1 and request[0].direcao == 'in'
    assert request[0].igreja_id == _IGREJA and request[0].conversation_id == turn.conversation_id
    assert len(_rows(turn, Pessoa)) == before[1]
    with turn.factory() as session:
        assert session.get(Conversation, turn.conversation_id).pessoa_id == turn.actor_id
    proposals = _rows(turn, AgentActionProposal)
    assert len(proposals) == 1 and proposals[0].state == 'pendente'
    assert proposals[0].target_id == turn.actor_id and proposals[0].delivered_at is not None
    assert proposals[0].arguments_json == {'pessoa_id': str(turn.actor_id), 'reuniao_id': str(turn.meeting_id)}
    summary = next(row for row in _rows(turn, Message) if row.id == proposals[0].summary_message_id)
    assert summary.agent_reply_state == worker_module._AGENT_REPLY_CONFIRMED
    assert summary.agent_privilege_context['kind'] == 'summary' and 'Responda SIM ou NÃO' in summary.texto
    assert _rows(turn, CelulaPresenca) == _rows(turn, AgentActionReceipt) == []
    assert len(turn.http_evolution.calls) == 1
    assert turn.http_calls == ['s3_route', 's3_tool', 's3_handle']
    assert all(marker not in prompt for pair in turn.http_prompts for prompt in pair
               for marker in ('Alvo Sintético', str(turn.target_id)))
    return request[0], summary, proposals[0]


def test_own_member_http_pg_webhook_worker_sim_duplicate_and_panel_sources(own_http_turn):
    from app.deps import CurrentUser
    from app.routers.cell_discipulo import get_my_next_meeting
    from app.routers.conversations import list_messages
    from app.routers._common import PaginationParams
    turn = own_http_turn
    request, summary, proposal = _http_pending(turn)
    confirmation = _http_enqueue(turn, 'HTTP-OWN-SIM', 'SIM')
    assert turn.http_worker.handle_envelope(confirmation) is worker_module.IngestionResult.REGISTERED
    presence, receipts = _rows(turn, CelulaPresenca), _rows(turn, AgentActionReceipt)
    assert len(presence) == len(receipts) == 1
    assert (presence[0].pessoa_id, presence[0].reuniao_id, presence[0].origem, presence[0].estado) == (
        turn.actor_id, turn.meeting_id, 'auto', 'confirmada')
    assert receipts[0].proposal_id == proposal.id and receipts[0].effect_reference == str(presence[0].id)
    messages = _rows(turn, Message)
    assert all(row.tipo == 'texto' and row.media_path is None for row in messages)
    sim = next(row for row in messages if row.provider_message_id == 'HTTP-OWN-SIM')
    assert receipts[0].confirmation_message_id == sim.id
    final = [row for row in messages if row.agent_reply_state == worker_module._AGENT_REPLY_CONFIRMED
             and (row.agent_privilege_context or {}).get('kind') == 'receipt']
    assert len(final) == 1 and 'Comprovante:' in final[0].texto
    assert _rows(turn, AgentActionProposal)[0].state == 'executada'
    assert len(turn.http_evolution.calls) == 2 and len(turn.http_outcomes) == 2
    duplicate = _http_enqueue(turn, 'HTTP-OWN-SIM', 'SIM')
    assert turn.http_worker.handle_envelope(duplicate) is worker_module.IngestionResult.DUPLICATE
    assert len(_rows(turn, CelulaPresenca)) == len(_rows(turn, AgentActionReceipt)) == 1
    assert len(_rows(turn, Message)) == len(messages)
    assert len(turn.http_evolution.calls) == len(turn.http_outcomes) == 2
    member = CurrentUser(app_user_id=str(turn.app_user_id), igreja_id=str(_IGREJA),
        clerk_user_id='clerk-s3-synthetic', email='', nome='', roles=frozenset())
    with turn.factory() as session:
        projection = get_my_next_meeting(db=session, current_user=member)
        assert projection.meeting is not None and projection.meeting.id == str(turn.meeting_id)
        assert projection.meeting.minha_presenca == 'confirmou'
    admin = CurrentUser(app_user_id=str(turn.app_user_id), igreja_id=str(_IGREJA),
        clerk_user_id='clerk-s3-synthetic', email='', nome='', roles=frozenset({'admin'}))
    def no_media(_paths):
        raise AssertionError('unexpected media/storage I/O in text-only fixture')
    options = dict(pagination=PaginationParams(page=1, page_size=100),
        storage=SimpleNamespace(sign=no_media), latest=False, include_media=True, before=None, after=None)
    with turn.factory() as session:
        page = list_messages(str(turn.conversation_id), db=session, current_user=admin, **options)
    visible = {item.id: item for item in page.items}
    assert page.total == len(messages)
    for row in (request, sim, summary, final[0]):
        assert str(row.id) in visible and visible[str(row.id)].texto == row.texto
    # Receipt is a separate table; the panel DTO contains the final Message.
    assert str(receipts[0].id) not in visible
    wrong_admin = CurrentUser(app_user_id=str(turn.app_user_id), igreja_id=str(uuid.UUID(int=1999)),
        clerk_user_id='clerk-s3-synthetic', email='', nome='', roles=frozenset({'admin'}))
    with turn.factory() as session, pytest.raises(HTTPException) as exc:
        list_messages(str(turn.conversation_id), db=session, current_user=wrong_admin, **options)
    assert exc.value.status_code == 404


def test_own_member_http_pg_invalid_hmac_never_enqueues_or_executes_sql(own_http_turn):
    turn = own_http_turn
    models = (Message, Pessoa, AgentActionProposal, CelulaPresenca, AgentActionReceipt)
    before = tuple(len(_rows(turn, model)) for model in models)
    sql_attempts = []
    def record_sql(_connection, _cursor, _statement, _parameters, _context, _executemany):
        sql_attempts.append(True)
    event.listen(turn.engine, 'before_cursor_execute', record_sql)
    try:
        response = turn.http_client.post('/whatsapp/webhook', content=b'{invalid-json',
            headers={'content-type': 'application/json', 'x-evolution-signature': 'invalid-synthetic'})
    finally:
        event.remove(turn.engine, 'before_cursor_execute', record_sql)
    assert response.status_code == 401
    assert turn.http_queue.enqueued == turn.http_outcomes == turn.http_evolution.calls == []
    assert sql_attempts == []
    assert tuple(len(_rows(turn, model)) for model in models) == before


def test_own_member_http_pg_failure_before_commit_rolls_back_and_same_sim_recovers(own_http_turn):
    turn = own_http_turn
    _, _, proposal = _http_pending(turn)
    confirmation = _http_enqueue(turn, 'HTTP-OWN-COMMIT-SIM', 'SIM')
    intercepted = []
    def reject_domain_commit(session):
        if session.get_bind() is not turn.engine or session.in_nested_transaction():
            return
        # No autoflush: select only rows already flushed by the real service
        # and receipt writer in this exact proposal transaction.
        with session.no_autoflush:
            presence_count = session.execute(select(func.count()).select_from(CelulaPresenca).where(
                CelulaPresenca.igreja_id == _IGREJA, CelulaPresenca.reuniao_id == turn.meeting_id,
                CelulaPresenca.pessoa_id == turn.actor_id)).scalar_one()
            receipt_count = session.execute(select(func.count()).select_from(AgentActionReceipt).where(
                AgentActionReceipt.igreja_id == _IGREJA,
                AgentActionReceipt.proposal_id == proposal.id)).scalar_one()
        if presence_count == receipt_count == 1:
            intercepted.append(True)
            raise RuntimeError('SYNTHETIC_BEFORE_DOMAIN_COMMIT')
    event.listen(turn.factory.class_, 'before_commit', reject_domain_commit)
    try:
        with pytest.raises(RuntimeError, match='^SYNTHETIC_BEFORE_DOMAIN_COMMIT$'):
            turn.http_worker.handle_envelope(confirmation)
    finally:
        event.remove(turn.factory.class_, 'before_commit', reject_domain_commit)
    assert intercepted == [True]
    assert turn.engine.pool.checkedout() == 0
    assert _rows(turn, CelulaPresenca) == _rows(turn, AgentActionReceipt) == []
    assert _rows(turn, AgentActionProposal)[0].state == 'pendente'
    assert len(turn.http_evolution.calls) == 1
    assert all('Comprovante:' not in call[2] for call in turn.http_evolution.calls)
    assert all('Comprovante:' not in (row.texto or '') for row in _rows(turn, Message))
    # Recovery reuses the captured HTTP envelope/claim/provider id, matching
    # the worker's RESUMED protocol, rather than a fresh duplicate delivery.
    assert turn.http_worker.handle_envelope(confirmation) is worker_module.IngestionResult.DUPLICATE
    presence, receipts = _rows(turn, CelulaPresenca), _rows(turn, AgentActionReceipt)
    assert len(presence) == len(receipts) == 1
    assert receipts[0].proposal_id == proposal.id and receipts[0].effect_reference == str(presence[0].id)
    assert _rows(turn, AgentActionProposal)[0].state == 'executada'
    assert len(turn.http_evolution.calls) == 2 and 'Comprovante:' in turn.http_evolution.calls[-1][2]
    assert len([row for row in _rows(turn, Message) if row.provider_message_id == 'HTTP-OWN-COMMIT-SIM']) == 1
    # Injection is before COMMIT, not an ambiguous driver/network outcome.


def test_own_member_pg_two_sim_workers_serialize_one_proposal_and_receipt(own_http_turn):
    turn = own_http_turn
    _, _, proposal = _http_pending(turn)
    envelopes = [_http_enqueue(turn, f'HTTP-OWN-CONCURRENT-SIM-{number}', 'SIM') for number in (1, 2)]
    connection_gate, agent_gate = Barrier(2, timeout=8), Barrier(2, timeout=8)
    backend_ids, observation_lock = {}, Lock()
    runner_threads, runner_backend_ids = set(), {}
    prefix = 'OWN-CONFIRM-PG'

    def bounded_transaction(_session, _transaction, connection):
        name = current_thread().name
        if connection.engine is not turn.engine or not name.startswith(prefix):
            return
        with observation_lock:
            if name in runner_threads and name not in runner_backend_ids:
                # First after_begin inside the real privileged turn, after
                # ingestion closed. Read the psycopg2 PID without extra SQL,
                # a barrier, or a change to transaction/lock ordering.
                runner_backend_ids[name] = connection.connection.driver_connection.get_backend_pid()
        connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
        connection.exec_driver_sql("SET LOCAL statement_timeout = '8s'")
        with observation_lock:
            first = name not in backend_ids
            if first:
                backend_ids[name] = connection.exec_driver_sql('SELECT pg_backend_pid()').scalar_one()
        if first:
            # Both actual ingestion transactions hold independent PG
            # connections here. No extra control connection is substituted.
            connection_gate.wait(timeout=8)

    def simultaneous_runner(factory, outcome, ownership_guard):
        # Ingestion has committed/closed before either real agent starts.
        agent_gate.wait(timeout=8)
        with observation_lock:
            runner_threads.add(current_thread().name)
        return worker_module.run_agent_for_message(factory, outcome, ownership_guard,
            evolution_client=turn.http_evolution)

    workers = [worker_module.QueueWorker(queue=turn.http_queue, session_factory=turn.factory,
        agent_runner=simultaneous_runner, media_resolver=None, worker_id=f'OWN-CONCURRENT-{number}',
        heartbeat_publisher=lambda *_args: None) for number in (1, 2)]
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix=prefix)
    event.listen(turn.factory.class_, 'after_begin', bounded_transaction)
    try:
        futures = [pool.submit(worker.handle_envelope, envelope) for worker, envelope in zip(workers, envelopes)]
        results = [future.result(timeout=25) for future in futures]
    finally:
        connection_gate.abort()
        agent_gate.abort()
        try:
            pool.shutdown(wait=True, cancel_futures=True)
        finally:
            event.remove(turn.factory.class_, 'after_begin', bounded_transaction)
    assert results == [worker_module.IngestionResult.REGISTERED] * 2
    assert len(backend_ids) == 2 and len(set(backend_ids.values())) == 2
    assert set(runner_backend_ids) == runner_threads and len(runner_backend_ids) == 2
    assert len(set(runner_backend_ids.values())) == 2
    assert turn.engine.pool.checkedout() == 0
    presence, receipts = _rows(turn, CelulaPresenca), _rows(turn, AgentActionReceipt)
    assert len(presence) == len(receipts) == 1
    assert (presence[0].pessoa_id, presence[0].reuniao_id, presence[0].origem) == (turn.actor_id, turn.meeting_id, 'auto')
    assert receipts[0].proposal_id == proposal.id and receipts[0].effect_reference == str(presence[0].id)
    messages = _rows(turn, Message)
    sims = [row for row in messages if row.provider_message_id in {
        'HTTP-OWN-CONCURRENT-SIM-1', 'HTTP-OWN-CONCURRENT-SIM-2'}]
    assert len(sims) == 2 and all(row.direcao == 'in' for row in sims)
    assert receipts[0].confirmation_message_id in {row.id for row in sims}
    assert _rows(turn, AgentActionProposal)[0].state == 'executada'
    assert len([call for call in turn.http_evolution.calls if 'Comprovante:' in call[2]]) == 1
    assert len([row for row in messages if row.agent_reply_state == worker_module._AGENT_REPLY_CONFIRMED
                and 'Comprovante:' in (row.texto or '')]) == 1
    assert turn.http_calls == ['s3_route', 's3_tool', 's3_handle']
    # Future.result propagates any unhandled driver/23505 error. The second
    # confirmation may be silent or a safe clarification; no content imposed.


def test_own_member_pg_real_legacy_unique_conflict_requeries_same_presence(own_member_unique_turn):
    from app.deps import CurrentUser
    from app.services.ministerial_actions import confirm_meeting_attendance
    turn = own_member_unique_turn
    legacy_user_id = uuid.UUID(int=1990)
    with turn.factory.begin() as session:
        session.add(AppUser(id=legacy_user_id, igreja_id=_IGREJA, pessoa_id=turn.target_id,
            nome='Pastor legado sintético', email='legacy-synthetic@example.test',
            clerk_user_id='clerk-own-legacy-synthetic', status='ativo'))
        session.flush()
        session.add(UserRole(id=uuid.UUID(int=1991), igreja_id=_IGREJA, user_id=legacy_user_id, papel='pastor'))
    own = CurrentUser(app_user_id=str(turn.app_user_id), igreja_id=str(_IGREJA),
        clerk_user_id='clerk-s3-synthetic', email='', nome='', roles=frozenset())
    legacy = CurrentUser(app_user_id=str(legacy_user_id), igreja_id=str(_IGREJA),
        clerk_user_id='clerk-own-legacy-synthetic', email='', nome='', roles=frozenset({'pastor'}))
    scope = _inbound(turn, 'OWN-LEGACY-SERVICE-SCOPE',
        'Quero confirmar minha presença na próxima reunião da minha célula.')
    insert_reached, unique_errors, insert_attempts = Event(), [], []
    prefix = 'OWN-LEGACY-PG'

    def legacy_insert(statement):
        normalized = statement.lstrip().lower()
        return normalized.startswith(('insert into celula_presenca ', 'insert into msg_idemp1.celula_presenca '))

    def observe_insert(connection, _cursor, statement, _parameters, _context, _executemany):
        if connection.engine is turn.engine and current_thread().name.startswith(prefix) and legacy_insert(statement):
            insert_attempts.append(True)
            # Observe the INSERT dispatch only, before server execution;
            # this event does not establish a physical FK/UNIQUE wait.
            insert_reached.set()

    def observe_error(context):
        if (context.connection is not None and context.connection.engine is turn.engine
            and current_thread().name.startswith(prefix) and legacy_insert(context.statement or '')):
            code = getattr(context.original_exception, 'sqlstate', None) or getattr(context.original_exception, 'pgcode', None)
            if code == '23505':
                unique_errors.append(code)
        # Never replace or suppress the real driver exception.

    def legacy_writer(backend_a):
        with turn.factory() as transaction_b:
            worker_module._scope_agent_execution_session(transaction_b, scope, dedicated=False)
            transaction_b.execute(text("SET LOCAL lock_timeout = '5s'"))
            transaction_b.execute(text("SET LOCAL statement_timeout = '8s'"))
            assert transaction_b.execute(text('SELECT pg_backend_pid()')).scalar_one() != backend_a
            attendance = confirm_meeting_attendance(transaction_b, legacy,
                reuniao_id=turn.meeting_id, pessoa_id=turn.actor_id)
            identity = attendance.id
            assert (attendance.pessoa_id, attendance.reuniao_id, attendance.origem) == (turn.actor_id, turn.meeting_id, 'lider')
            transaction_b.commit()
            return identity

    transaction_a = turn.factory()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=prefix)
    event.listen(turn.engine, 'before_cursor_execute', observe_insert)
    event.listen(turn.engine, 'handle_error', observe_error)
    try:
        worker_module._scope_agent_execution_session(transaction_a, scope, dedicated=False)
        transaction_a.execute(text("SET LOCAL lock_timeout = '5s'"))
        transaction_a.execute(text("SET LOCAL statement_timeout = '8s'"))
        backend_a = transaction_a.execute(text('SELECT pg_backend_pid()')).scalar_one()
        attendance = confirm_meeting_attendance(transaction_a, own, reuniao_id=turn.meeting_id,
            pessoa_id=None, expected_actor_pessoa_id=turn.actor_id)
        own_presence_id = attendance.id
        assert attendance.origem == 'auto' and transaction_a.in_transaction()
        future = pool.submit(legacy_writer, backend_a)
        if not insert_reached.wait(timeout=8):
            if future.done():
                future.result(timeout=1)  # Surface a real pre-INSERT failure.
            pytest.fail('legacy INSERT was not reached under own locks; interleaving unavailable')
        # Only INSERT dispatch has been observed here. The genuine 23505
        # below proves the stale lookup/INSERT/savepoint/requery conflict;
        # no particular physical wait mechanism is asserted.
        transaction_a.commit()
        legacy_presence_id = future.result(timeout=15)
    finally:
        # On any failure release A before joining B, whose SQL timeouts bound
        # waits. All threads finish before schema teardown/listener removal.
        try:
            try:
                transaction_a.rollback()
            finally:
                transaction_a.close()
        finally:
            try:
                pool.shutdown(wait=True, cancel_futures=True)
            finally:
                try:
                    event.remove(turn.engine, 'before_cursor_execute', observe_insert)
                finally:
                    event.remove(turn.engine, 'handle_error', observe_error)
    assert insert_attempts == [True] and unique_errors == ['23505']
    assert legacy_presence_id == own_presence_id
    presence = _rows(turn, CelulaPresenca)
    assert len(presence) == 1 and presence[0].id == own_presence_id
    assert (presence[0].pessoa_id, presence[0].origem, presence[0].estado) == (turn.actor_id, 'lider', 'confirmada')
    assert _rows(turn, AgentActionReceipt) == []
    assert turn.engine.pool.checkedout() == 0
    # Service/savepoint/requery proof only; the previous test covers the own
    # proposal ledger. This is not a forced retry of the serialized own branch.
