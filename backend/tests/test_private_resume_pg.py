"""Full worker turns on the active migration chain; synthetic providers only."""
import os
from urllib.parse import urlsplit

import pytest
from sqlalchemy import text
from tests.test_uv_turmas_pg import migrated_database, database  # noqa: F401
from tests.test_agent_privileged_turn_pg import s3_turn, _inbound, _rows, _IGREJA  # noqa: F401
from tests.test_messages_inbound_idempotency import _ClassifiedEvolution
from app.db.models import Message
from app.db.tenant_session import mark_tenant_scoped
from app.services import private_summaries as summaries
from app.services.llm import LLMClient, LLMUsage, TypedChoiceResult, TypedLLMResult
from app.workers import queue_worker as worker
from app.agent import runtime

pytestmark = pytest.mark.rls_integration


@pytest.fixture(scope='module')
def rls_database_url():
    from tests.conftest_rls import assert_disposable_database
    url = os.environ['UV_TURMAS_DATABASE_URL']  # Missing local PG is failure, never skip.
    assert_disposable_database(url)
    parsed = urlsplit(url)
    assert parsed.hostname in {'localhost', '127.0.0.1', '::1'}
    assert parsed.path == '/uv_turmas_test'
    return url

@pytest.fixture
def msg_engine_fx(database):
    return database

@pytest.fixture
def memory(s3_turn, monkeypatch):
    from app.services import private_resume as resume
    turn = s3_turn
    monkeypatch.setattr(summaries, 'APPROVED_RELEASE_ID', 'synthetic')
    monkeypatch.setattr(summaries, 'APPROVED_IGREJA_IDS', frozenset({str(_IGREJA)}))
    monkeypatch.setattr(resume, 'PRIVATE_RESUME_APPROVED_RELEASE_ID', 'synthetic')
    monkeypatch.setattr(resume, 'PRIVATE_RESUME_APPROVED_IGREJA_IDS', frozenset({str(_IGREJA)}))
    with turn.factory.begin() as s:
        s.execute(text("update messages set texto='Qual o horário do culto?' where conversation_id=:c"), dict(c=turn.conversation_id))
        s.execute(text("insert into private_summary_settings(igreja_id,enabled,monthly_limit_microusd,resume_enabled) values(:t,true,1000000,true)"), dict(t=_IGREJA))
    with turn.factory() as s:
        mark_tenant_scoped(s, _IGREJA, source='resume_test')
        assert summaries.enqueue(s, _IGREJA, turn.conversation_id)
        s.commit()
    assert summaries.process_tasks(turn.factory, provider=lambda **kw: {'topic': 'cultos'}) == 1
    return turn

@pytest.mark.parametrize('case', ['available', 'missing', 'suspended', 'unlisted', 'disabled', 'no_release', 'wrong_person', 'optout', 'revoked', 'protected', 'corrected', 'incorrect', 'ordinary', 'during_edit', 'during_delete', 'during_correction', 'retry_protected', 'during_role', 'other_conversation'])
def test_private_resume_full_turn(memory, monkeypatch, case):
    from app.services import private_resume as resume
    turn = memory
    with turn.factory.begin() as s:
        if case == 'missing':
            s.execute(text('delete from private_conversation_summaries'))
        elif case == 'incorrect':
            s.execute(text("update private_conversation_summaries set state='incorrect'"))
        elif case == 'suspended':
            s.execute(text("update private_conversation_summaries set state='suspended'"))
        elif case == 'disabled':
            s.execute(text('update private_summary_settings set resume_enabled=false'))
        elif case == 'wrong_person':
            s.execute(text('update conversations set pessoa_id=:p where id=:c'), dict(p=turn.target_id, c=turn.conversation_id))
        elif case == 'optout':
            s.execute(text('update pessoas set optout=true where id=(select pessoa_id from conversations where id=:c)'), dict(c=turn.conversation_id))
        elif case == 'revoked':
            s.execute(text('delete from user_roles'))
        elif case == 'protected':
            s.execute(text("insert into pedido_oracao_proposta(id,igreja_id,pessoa_id,conversation_id,source_message_id,summary,term_version,expires_at) select gen_random_uuid(),igreja_id,pessoa_id,id,(select id from messages where conversation_id=:c limit 1),'Synthetic','test',now()+interval '1 hour' from conversations where id=:c"), dict(c=turn.conversation_id))
        elif case == 'corrected':
            s.execute(text("update private_conversation_summaries set state='corrected',human_correction=:v"), dict(v=summaries.TOPIC_TEXT['uv']))
    if case == 'unlisted':
        monkeypatch.setattr(resume, 'PRIVATE_RESUME_APPROVED_IGREJA_IDS', frozenset())
    if case == 'no_release':
        monkeypatch.setattr(resume, 'PRIVATE_RESUME_APPROVED_RELEASE_ID', None)
    if case == 'other_conversation':
        from app.db.models import Conversation
        with turn.factory.begin() as s:
            original = s.get(Conversation, turn.conversation_id)
            other = Conversation(igreja_id=_IGREJA, pessoa_id=original.pessoa_id,
                                 telefone=original.telefone, estado='ia', numero_oficial=True)
            s.add(other)
            s.flush()
            turn.conversation_id = other.id
    prompts = []
    usage = LLMUsage(modelo='synthetic', tokens_in=2, tokens_out=1, custo=0)
    monkeypatch.setattr(LLMClient, 'generate_typed', lambda *a, **kw: TypedChoiceResult('nenhuma', usage))
    def answer(_self, system, user, **kw):
        assert turn.engine.pool.checkedout() == 0
        prompts.append(user)
        if case.startswith('during_'):
            with turn.factory.begin() as s:
                if case == 'during_edit':
                    s.execute(text("update messages set texto='Qual o horário do culto?' where provider_message_id='RESUME-'||:case"), dict(case=case))
                elif case == 'during_delete':
                    s.execute(text('delete from private_conversation_summaries'))
                elif case == 'during_role':
                    s.execute(text('delete from user_roles'))
                else:
                    s.execute(text('update private_conversation_summaries set version=version+1'))
        return TypedLLMResult(False, 'Resposta sintética segura.', usage)
    monkeypatch.setattr(LLMClient, 'complete_typed', answer)
    monkeypatch.setattr(runtime, 'decrypt_secret', lambda _: 'synthetic-key')
    request = _inbound(turn, 'RESUME-'+case, 'Qual o horário do culto?' if case == 'ordinary' else 'retomar conversa')
    evolution = _ClassifiedEvolution('falhou_retentavel', 'aceito') if case == 'retry_protected' else _ClassifiedEvolution()
    if case == 'retry_protected':
        with pytest.raises(worker.AgentReplyRetryable):
            worker.run_agent_for_message(turn.factory, request, evolution_client=evolution)
        assert len(evolution.calls) == 1
        with turn.factory.begin() as s:
            s.execute(text("insert into pedido_oracao_proposta(id,igreja_id,pessoa_id,conversation_id,source_message_id,summary,term_version,expires_at) select gen_random_uuid(),igreja_id,pessoa_id,id,(select id from messages where conversation_id=:c and direcao='in' order by criado_em limit 1),'Synthetic','test',now()+interval '1 hour' from conversations where id=:c"), dict(c=turn.conversation_id))
    worker.run_agent_for_message(turn.factory, request, evolution_client=evolution)
    expected = case in {'available', 'corrected', 'retry_protected'} or case.startswith('during_')
    assert any('Memória privada' in p for p in prompts) is expected
    if expected:
        assert (summaries.TOPIC_TEXT['uv'] if case == 'corrected' else summaries.TOPIC_TEXT['cultos']) in prompts[0]
        assert 'derivado, pode errar' in prompts[0]
    if case.startswith('during_'):
        assert evolution.calls == []
        assert not any(m.texto == 'Resposta sintética segura.' for m in _rows(turn, Message))
    elif case == 'retry_protected':
        assert len(evolution.calls) == 1
        assert len(prompts) == 1
    elif case in {'optout', 'wrong_person'}:
        assert prompts == []
        assert all(call[2] != 'Resposta sintética segura.' for call in evolution.calls)
    elif case == 'ordinary':
        assert prompts == []
        assert 'Memória privada' not in evolution.calls[0][2]
    else:
        assert evolution.calls[0][2] == 'Resposta sintética segura.'
        replies = [m for m in _rows(turn, Message) if m.direcao == 'out' and m.texto]
        assert len(replies) == 1
        assert replies[0].agent_reply_state == 'ia'


def test_scope_and_forged_person_cannot_read_memory(memory):
    from dataclasses import replace
    from uuid import uuid4
    from app.services import private_resume as resume
    from app.services.whatsapp_privilege import resolve_whatsapp_privilege_context

    turn = memory
    request = _inbound(turn, 'SCOPE-RESUME', 'retomar conversa')
    with turn.factory() as s:
        mark_tenant_scoped(s, _IGREJA, source='resume_scope_test')
        context = resolve_whatsapp_privilege_context(s, igreja_id=_IGREJA,
            conversation_id=turn.conversation_id, inbound_message_id=request.inbound_message_id)
        assert resume.load(s, context) is not None
        assert resume.load(s, replace(context, pessoa_id=turn.target_id)) is None
    other = uuid4()
    with turn.factory.begin() as s:
        s.execute(text("insert into igrejas(id,nome) values(:t,'Synthetic isolation')"), dict(t=other))
    with turn.factory() as s:
        mark_tenant_scoped(s, other, source='resume_other_tenant_test')
        assert s.scalar(text('select count(*) from private_conversation_summaries')) == 0
        assert resume.load(s, replace(context, igreja_id=other)) is None
