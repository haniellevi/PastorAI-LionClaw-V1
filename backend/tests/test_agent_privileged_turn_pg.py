"""S3 WhatsApp actions through the real worker and disposable PostgreSQL.

The provider and LLM are fakes.  The source anchor, proposal, outbound fence,
confirmation, domain effect and receipt remain real committed database rows.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine

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
        prompts.append(user)
        return original(self, system, user, **kwargs)
    monkeypatch.setattr(LLMClient, 'generate_typed', choose)
    request = _inbound(s3_turn, 'S3-PROMPT-PRIVACY', 'Registre decisão de Alvo Sintético')
    spoofed = replace(request, texto='Registre decisão de AAA Privada Não Solicitada')
    worker_module.run_agent_for_message(s3_turn.factory, spoofed, evolution_client=_ClassifiedEvolution())
    assert len(prompts) == 3
    assert all('AAA Privada' not in prompt for prompt in prompts)
    assert 'Alvo Sintético' in prompts[-1]
    assert _rows(s3_turn, AgentActionProposal)[0].target_id == s3_turn.target_id
