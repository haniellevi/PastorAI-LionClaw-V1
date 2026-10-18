"""Complete CD turns against the full real migration chain and tenant RLS."""
import dataclasses
import datetime as dt
from types import SimpleNamespace
from uuid import UUID, uuid4
import pytest
from sqlalchemy import text, select, event
from sqlalchemy.orm import sessionmaker
from cryptography.fernet import Fernet
from app.config import get_settings
from app.db.models import AgentConfig, LlmCredential, ConsentRecord, Message
from app.services.crypto import encrypt_secret
from app.services import cd
from app.workers import queue_worker as worker
from tests.test_uv_turmas_pg import rls_database_url, migrated_database, database, seeded, scoped, principal
from tests.test_cd_presencas_pg import setup
from tests.test_messages_inbound_idempotency import (
    _seed_tier_a_handoff_anchor, _seed_inbound_anchor, _agent_outcome, _ClassifiedEvolution)

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def cd_turn(database, seeded, monkeypatch):
    from app.cd_whatsapp import policy
    from app.services.llm import LLMClient
    from app.routers.cd import ResponsaveisInput
    v = seeded
    for key, value in dict(APP_ENV='test', AGENT_TERM_VERSION='cd-test',
        WHATSAPP_PILOTO_IGREJA_IDS=str(v['t']), CD_WHATSAPP_ENABLED_IGREJA_IDS=str(v['t']),
        SECRETS_ENCRYPTION_KEY=Fernet.generate_key().decode(), SESSION_JWT_SECRET='cd-synthetic-only',
        ALLOW_REAL_SENDS='true').items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(policy, 'CD_WHATSAPP_APPROVED_RELEASE_ID', 'synthetic-only')
    get_settings.cache_clear()
    def forbidden(*a, **kw):
        raise AssertionError('unexpected external LLM')
    monkeypatch.setattr(LLMClient, 'complete', forbidden)
    factory = sessionmaker(database, expire_on_commit=False)
    @event.listens_for(factory, 'after_begin')
    def bound_database_wait(session, transaction, connection):
        connection.exec_driver_sql("set local statement_timeout='10s'")
    conv, person, _ = _seed_tier_a_handoff_anchor(factory, igreja_id=v['t'], provider_message_id='cd-seed')
    with factory.begin() as s:
        s.execute(text('insert into whatsapp_connections(igreja_id,instance) values(:t,\'cd-test\')'),dict(t=v['t']))
        s.execute(text('update app_users set pessoa_id=:p where id=:u'),dict(p=person,u=v['leader']))
        s.add(ConsentRecord(igreja_id=v['t'],pessoa_id=person,termo_versao='cd-test',aceite_em=dt.datetime.now(dt.UTC)))
        s.add(AgentConfig(igreja_id=v['t'],ativo=True,comportamento='synthetic'))
        s.add(LlmCredential(igreja_id=v['t'],provedor='openai',modelo='gpt-5.6-luna',
            api_key_encrypted=encrypt_secret('synthetic'),validado=True,ativo=True))
    with scoped(database,v['t']) as s:
        tid, mid, aula = setup(s,v)
        s.execute(text("update cd_turmas set nome='Turma sintética' where id=:id"),dict(id=tid))
        cd.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        s.commit()
    yield SimpleNamespace(factory=factory,v=v,conv=conv,person=person,tid=tid,mid=mid,aula=aula)
    get_settings.cache_clear()


def inbound(p, body):
    key = 'cd-' + uuid4().hex
    mid = _seed_inbound_anchor(p.factory,igreja_id=p.v['t'],conversation_id=p.conv,provider_message_id=key,texto=body)
    return dataclasses.replace(_agent_outcome(p.conv,igreja_id=p.v['t'],provider_message_id=key,
        inbound_message_id=mid,instance='cd-test',telefone='5500000000000'),texto=body)


def send(p, body, outcome=None, transport=None):
    class CommittedTransport(_ClassifiedEvolution):
        def send_text_classificado(self, instance, phone, body):
            with p.factory() as s:
                assert s.scalar(select(Message.id).where(Message.conversation_id==p.conv,
                    Message.direcao=='out',Message.texto==body)) is not None
                if body == 'Presença registrada.':
                    assert s.execute(text('select count(*) from cd_presencas_historico')).scalar_one()==1
            return super().send_text_classificado(instance,phone,body)
    transport = transport or CommittedTransport()
    outcome = outcome or inbound(p,body)
    worker.run_agent_for_message(p.factory,outcome,evolution_client=transport)
    with p.factory() as s:
        reply=s.scalars(select(Message).where(Message.conversation_id==p.conv,Message.direcao=='out')
            .order_by(Message.criado_em.desc(),Message.id.desc())).first()
    return outcome, reply, transport


COMMAND='CD presença Turma sintética; aula 1; Aluno sintético; presente'


def count(p):
    with p.factory() as s:
        return s.execute(text('select count(*) from cd_presencas_historico')).scalar_one()


@pytest.mark.parametrize('role',['lider_consol','pastor','admin'])
def test_complete_turn_confirmation_and_replay(cd_turn, role):
    p=cd_turn
    with p.factory.begin() as s:
        s.execute(text('update user_roles set papel=:r where user_id=:u'),dict(r=role,u=p.v['leader']))
        if role in {'pastor','admin'}:
            s.execute(text('update cd_responsaveis set ativo=false'))
    _,r,t=send(p,'CD turma Turma sintética')
    assert len(t.calls)==1 and r.agent_reply_state=='ia'
    assert 'Aluno sintético' in r.texto and 'cumpridas nenhuma' in r.texto
    assert '5500' not in r.texto
    _,r,t=send(p,COMMAND)
    assert 'SIM' in r.texto and len(t.calls)==1
    assert count(p)==0
    outcome,r,t=send(p,'SIM')
    assert r.texto=='Presença registrada.' and len(t.calls)==1 and count(p)==1
    send(p,'SIM',outcome=outcome)
    assert count(p)==1
    _,r,_=send(p,COMMAND.replace('presente','ausente'))
    assert 'SIM' in r.texto
    # A second explicit proposal uses optimistic correction identity, never replaying the old write.
    _,r,_=send(p,'NÃO')
    assert r.texto=='Proposta cancelada.' and count(p)==1


@pytest.mark.parametrize('state',['unlinked','revoked','role','foreign','closed','future','complete','cancelled'])
def test_live_refusal_on_confirmation(cd_turn,state):
    p=cd_turn
    _,r,t=send(p,COMMAND)
    assert 'SIM' in r.texto
    with p.factory.begin() as s:
        if state=='unlinked': s.execute(text('update cd_responsaveis set ativo=false'))
        if state=='revoked': s.execute(text("update app_users set status='revogado' where id=:u"),dict(u=p.v['leader']))
        if state=='role': s.execute(text("update user_roles set papel='operador' where user_id=:u"),dict(u=p.v['leader']))
        if state=='foreign': s.execute(text('update app_users set pessoa_id=null where id=:u'),dict(u=p.v['leader']))
        if state=='closed': cd.close(s,principal(p.v),p.tid)
        if state=='future': s.execute(text("update cd_calendario set data='2099-01-01'"))
        if state=='complete':
            from tests.test_cd_conclusoes_pg import fulfill, finish
            fulfill(s,p.v,p.tid,p.mid)
            finish(s,p.v,p.tid,p.mid)
        if state=='cancelled':
            cd.cancel_enrollment(s,principal(p.v),p.tid,p.mid)
    _,r,t=send(p,'SIM')
    assert len(t.calls)==1 and r.texto!='Presença registrada.'
    assert count(p)==(10 if state=='complete' else 0)


@pytest.mark.parametrize('state',['unlinked','role','revoked'])
def test_denied_read_without_leaking_students(cd_turn,state):
    p=cd_turn
    with p.factory.begin() as s:
        if state=='unlinked': s.execute(text('update cd_responsaveis set ativo=false'))
        if state=='role': s.execute(text("update user_roles set papel='operador' where user_id=:u"),dict(u=p.v['leader']))
        if state=='revoked': s.execute(text("update app_users set status='revogado' where id=:u"),dict(u=p.v['leader']))
    _,r,t=send(p,'CD turma Turma sintética')
    assert len(t.calls)==1 and 'Aluno sintético' not in r.texto and count(p)==0


@pytest.mark.parametrize('body',['Quero parar de receber mensagens','Quero me matar','Quero falar com humano'])
def test_priority_paths(cd_turn,body):
    p=cd_turn
    send(p,COMMAND)
    _,r,_=send(p,body)
    assert (r.agent_privilege_context or {}).get('kind')!='cd'
    assert count(p)==0


@pytest.mark.parametrize('state',['optout','consent','handoff'])
def test_contact_suppressed_before_response(cd_turn,state):
    from app.cd_whatsapp.turn import run_cd_turn
    p=cd_turn
    with p.factory.begin() as s:
        if state=='optout': s.execute(text('update pessoas set optout=true where id=:p'),dict(p=p.person))
        if state=='consent': s.execute(text('delete from consent_records'))
        if state=='handoff': s.execute(text("update conversations set estado='humano'"))
    transport=_ClassifiedEvolution()
    assert run_cd_turn(p.factory,p.factory,inbound(p,COMMAND),igreja_id=p.v['t'],
        uses_dedicated_agent_session=False,ownership_guard=None,evolution_client=transport) is None
    assert not transport.calls and count(p)==0


def test_closed_read_and_future_refused(cd_turn):
    p=cd_turn
    with p.factory.begin() as s:
        s.execute(text("update cd_calendario set data='2099-01-01'"))
    _,r,_=send(p,COMMAND)
    assert 'futura' in r.texto and count(p)==0
    with p.factory.begin() as s:
        cd.close(s,principal(p.v),p.tid)
    _,r,_=send(p,'CD turma Turma sintética')
    assert 'encerrada' in r.texto and 'Aluno sintético' in r.texto
    _,r,_=send(p,COMMAND)
    assert 'encerrada' in r.texto and count(p)==0


def test_other_church_is_not_visible(cd_turn):
    p=cd_turn
    with p.factory.begin() as s:
        from tests.test_cd_turmas_pg import create
        from app.routers.cd import NomeInput
        s.execute(text("insert into app_users(id,igreja_id,status,nome,email) values(:u,:u,'ativo','Outro sintético','other@example.test')"),dict(u=p.v['other']))
        s.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:u,:u,'admin')"),dict(u=p.v['other']))
        foreign=dict(p.v,t=p.v['other'],uid=p.v['other'])
        tid=create(s,foreign)
        cd.rename_turma(s,principal(foreign),tid,NomeInput(nome='Turma estrangeira'))
    _,r,t=send(p,'CD turma Turma estrangeira')
    assert len(t.calls)==1 and 'não encontrado' in r.texto and count(p)==0
    _,r,_=send(p,'CD')
    assert 'Turma estrangeira' not in r.texto


def test_expired_or_undelivered_proposal_never_writes(cd_turn):
    from app.cd_whatsapp.turn import _handle, _contact
    p=cd_turn
    _,r,_=send(p,COMMAND)
    with p.factory.begin() as s:
        s.execute(text("update messages set criado_em=now()-interval '1 hour' where id=:id"),dict(id=r.id))
    outcome=inbound(p,'SIM')
    with scoped(p.factory.kw['bind'],p.v['t']) as s:
        contact=_contact(s,outcome)
        source=s.get(Message,outcome.inbound_message_id)
        response,_=_handle(s,contact,source)
        assert response!='Presença registrada.'
        s.commit()
    assert count(p)==0


def test_retry_receipt_after_commit_never_writes_again(cd_turn):
    p=cd_turn
    send(p,COMMAND)
    # A classified provider failure leaves the committed domain write and pending reply.
    outcome=inbound(p,'SIM')
    with pytest.raises(worker.AgentReplyRetryable):
        send(p,'SIM',outcome=outcome,transport=_ClassifiedEvolution('falhou_retentavel'))
    assert count(p)==1
    _,r,t=send(p,'SIM',outcome=outcome)
    assert count(p)==1 and len(t.calls)==1 and r.texto=='Presença registrada.'


def test_revoked_before_delivery_suppresses_private_reply(cd_turn):
    from app.cd_whatsapp.turn import reply_still_authorized
    from app.db.models import Conversation
    p=cd_turn
    _,r,_=send(p,'CD turma Turma sintética')
    with p.factory.begin() as s:
        s.execute(text('update cd_responsaveis set ativo=false'))
    with scoped(p.factory.kw['bind'],p.v['t']) as s:
        assert not reply_still_authorized(s,s.get(Message,r.id),conversation=s.get(Conversation,p.conv),
            recipient_phone='5500000000000',instance='cd-test')


def test_reposicao_and_explicit_correction(cd_turn):
    p=cd_turn
    send(p,COMMAND.replace('presente','ausente'))
    send(p,'SIM')
    assert count(p)==1
    _,r,_=send(p,COMMAND.replace('presente','reposição'))
    assert 'Correção: atual ausente → novo reposição presente' in r.texto
    proposal=r.agent_privilege_context['proposal']
    assert proposal['anterior_id']
    assert proposal['anterior'] == dict(presente=False, modalidade='regular')
    # Committed transport helper counts a single write only for the first receipt.
    _,r,_=send(p,'SIM',transport=_ClassifiedEvolution())
    assert r.texto=='Presença registrada.' and count(p)==2
    with p.factory() as s:
        current=s.execute(text('select anterior_id,presente,modalidade from cd_presencas')).one()
        assert str(current.anterior_id)==proposal['anterior_id']
        assert (current.presente,current.modalidade)==(True,'reposicao')



def test_confirmation_persisted_before_proposal_delivery_is_refused(cd_turn):
    p=cd_turn
    _,r,_=send(p,COMMAND)
    outcome=inbound(p,'SIM')
    with p.factory.begin() as s:
        # Simulate a SIM already in the queue before the proposal transport returned.
        proposal=s.get(Message,r.id)
        proposal.agent_privilege_context=dict(proposal.agent_privilege_context,
            delivered_at=(dt.datetime.now(dt.UTC)+dt.timedelta(seconds=1)).isoformat())
    from app.cd_whatsapp.turn import _contact, _handle
    with scoped(p.factory.kw['bind'],p.v['t']) as s:
        response,_=_handle(s,_contact(s,outcome),s.get(Message,outcome.inbound_message_id))
        assert response!='Presença registrada.'
        s.commit()
    assert count(p)==0


def test_fresh_repeated_sim_does_not_execute_again(cd_turn):
    p=cd_turn
    send(p,COMMAND)
    send(p,'SIM')
    _,r,t=send(p,'SIM')
    assert count(p)==1 and len(t.calls)==1
    assert 'já registrada' in r.texto


@pytest.mark.parametrize('kind',['list','read'])
def test_changed_read_projection_is_suppressed(cd_turn,kind):
    from app.cd_whatsapp.turn import reply_still_authorized
    from app.db.models import Conversation
    p=cd_turn
    _,r,_=send(p,'CD' if kind=='list' else 'CD turma Turma sintética')
    with p.factory.begin() as s:
        if kind=='list': s.execute(text('update cd_responsaveis set ativo=false'))
        else: s.execute(text('update pessoas set arquivada_em=now() where id=:p'),dict(p=p.v['p']))
    with scoped(p.factory.kw['bind'],p.v['t']) as s:
        assert not reply_still_authorized(s,s.get(Message,r.id),conversation=s.get(Conversation,p.conv),
            recipient_phone='5500000000000',instance='cd-test')


def test_concurrent_confirmations_write_once(cd_turn):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    p=cd_turn
    send(p,COMMAND)
    outcomes=[inbound(p,'SIM'),inbound(p,'SIM')]
    barrier=Barrier(2)
    def attempt(outcome):
        barrier.wait(timeout=10)
        return send(p,'SIM',outcome=outcome,transport=_ClassifiedEvolution())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(attempt,o) for o in outcomes]
        for f in futures:
            _,r,t=f.result(timeout=20)
            assert len(t.calls)==1
            assert 'registrada' in t.calls[0][2]
    assert count(p)==1


@pytest.mark.parametrize('stage',['proposal','receipt'])
@pytest.mark.parametrize('body',['Peço oração por mim: preciso de força.',
    'Não aguento mais, quero sumir pra sempre.', 'Qual o horário do culto?'])
def test_cd_dialog_never_captures_unrelated_inbound(cd_turn,stage,body):
    from app.cd_whatsapp.turn import run_cd_turn
    p=cd_turn
    send(p,COMMAND)
    if stage=='receipt': send(p,'SIM')
    transport=_ClassifiedEvolution()
    assert run_cd_turn(p.factory,p.factory,inbound(p,body),igreja_id=p.v['t'],
        uses_dedicated_agent_session=False,ownership_guard=None,evolution_client=transport) is None
    assert not transport.calls
    assert count(p)==(1 if stage=='receipt' else 0)


def test_same_value_has_no_proposal(cd_turn):
    p=cd_turn
    send(p,COMMAND)
    send(p,'SIM')
    _,r,t=send(p,COMMAND)
    assert 'já registrada' in r.texto and len(t.calls)==1
    assert r.agent_privilege_context['stage'] != 'proposal'
    assert count(p)==1


def test_changed_record_refuses_confirmation(cd_turn):
    from tests.test_cd_presencas_pg import payload
    p=cd_turn
    send(p,COMMAND.replace('presente','ausente'))
    send(p,'SIM')
    _,r,_=send(p,COMMAND)
    assert 'Correção: atual ausente → novo presente' in r.texto
    with scoped(p.factory.kw['bind'],p.v['t']) as s:
        # A competing correction can even restore the same value; identity still changed.
        cd.attendance(s,principal(p.v),p.tid,p.mid,p.aula,
            payload(presente=False,anterior_id=UUID(r.agent_privilege_context['proposal']['anterior_id'])))
        s.commit()
    _,r,t=send(p,'SIM',transport=_ClassifiedEvolution())
    assert 'nova proposta' in r.texto and len(t.calls)==1
    assert count(p)==2
    with p.factory() as s:
        assert s.execute(text('select presente from cd_presencas')).scalar_one() is False


def test_second_sim_while_receipt_pending(cd_turn):
    p=cd_turn
    send(p,COMMAND)
    outcome=inbound(p,'SIM')
    with pytest.raises(worker.AgentReplyRetryable):
        send(p,'SIM',outcome=outcome,transport=_ClassifiedEvolution('falhou_retentavel'))
    _,r,t=send(p,'SIM')
    assert 'aguarde' in r.texto.lower() and len(t.calls)==1
    assert count(p)==1


def test_no_after_receipt_is_not_cd_pending(cd_turn):
    from app.cd_whatsapp.turn import run_cd_turn
    p=cd_turn
    send(p,COMMAND)
    send(p,'SIM')
    transport=_ClassifiedEvolution()
    assert run_cd_turn(p.factory,p.factory,inbound(p,'não'),igreja_id=p.v['t'],
        uses_dedicated_agent_session=False,ownership_guard=None,evolution_client=transport) is None
    assert not transport.calls and count(p)==1


def test_active_sender_in_b_cannot_change_class_in_a(cd_turn):
    p=cd_turn
    with p.factory.begin() as s:
        s.execute(text('update cd_turmas set nome=:name where id=:id'),dict(name='Turma exclusiva A',id=p.tid))
        s.execute(text('delete from cd_responsaveis'))
        s.execute(text('delete from user_roles where user_id=:u'),dict(u=p.v['leader']))
        s.execute(text('update app_users set pessoa_id=null where id=:u'),dict(u=p.v['leader']))
        s.execute(text('update app_users set igreja_id=:t,pessoa_id=:p where id=:u'),dict(t=p.v['other'],p=None,u=p.v['leader']))
        # Move the synthetic sender's entire contact context into B, with an active B user.
        s.execute(text('update conversations set pessoa_id=null where id=:id'),dict(id=p.conv))
        s.execute(text('delete from consent_records'))
        s.execute(text('delete from messages where conversation_id=:id'),dict(id=p.conv))
        s.execute(text('update pessoas set igreja_id=:t where id=:p'),dict(t=p.v['other'],p=p.person))
        s.execute(text('update conversations set igreja_id=:t,pessoa_id=:p where id=:id'),dict(t=p.v['other'],p=p.person,id=p.conv))
        s.execute(text('update app_users set pessoa_id=:p where id=:u'),dict(p=p.person,u=p.v['leader']))
        s.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:t,:u,'admin')"),dict(t=p.v['other'],u=p.v['leader']))
        for table in ['whatsapp_connections','agent_configs','llm_credentials']:
            s.execute(text(f'update {table} set igreja_id=:t where igreja_id=:old'),dict(t=p.v['other'],old=p.v['t']))
        s.add(ConsentRecord(igreja_id=p.v['other'],pessoa_id=p.person,termo_versao='cd-test',aceite_em=dt.datetime.now(dt.UTC)))
    from pytest import MonkeyPatch
    with MonkeyPatch.context() as mp:
        mp.setenv('WHATSAPP_PILOTO_IGREJA_IDS',str(p.v['other']))
        mp.setenv('CD_WHATSAPP_ENABLED_IGREJA_IDS',str(p.v['other']))
        get_settings.cache_clear()
        p.v=dict(p.v,t=p.v['other'])
        _,r,t=send(p,COMMAND.replace('Turma sintética','Turma exclusiva A'))
        assert len(t.calls)==1 and 'não encontrado' in r.texto
        assert r.agent_privilege_context['stage'] != 'proposal'
        assert count(p)==0


@pytest.mark.parametrize('body',['CD concluir módulo Ana','CD certificado Ana','CD equivalência Ana'])
def test_sensitive_actions_only_panel(cd_turn,body):
    p=cd_turn
    _,r,t=send(p,body)
    assert len(t.calls)==1 and 'painel autenticado' in r.texto
    assert count(p)==0
    with p.factory() as s:
        for table in ['cd_conclusoes','cd_certificados']:
            assert s.execute(text(f'select count(*) from {table}')).scalar_one()==0


def test_saved_names_with_whitespace(cd_turn):
    p=cd_turn
    with p.factory.begin() as s:
        s.execute(text("update cd_turmas set nome='  Turma   sintética  ' where id=:id"),dict(id=p.tid))
        s.execute(text("update pessoas set nome='  Aluno   sintético  ' where id=:id"),dict(id=p.v['p']))
    _,r,t=send(p,COMMAND)
    assert len(t.calls)==1 and 'SIM' in r.texto
    _,r,t=send(p,'SIM')
    assert r.texto=='Presença registrada.' and count(p)==1


@pytest.mark.parametrize('fence',['release','church'])
def test_disabled_worker_has_no_cd_effect(cd_turn,monkeypatch,fence):
    from app.cd_whatsapp import policy, service
    p=cd_turn
    if fence=='release': monkeypatch.setattr(policy,'CD_WHATSAPP_APPROVED_RELEASE_ID',None)
    else: monkeypatch.setenv('CD_WHATSAPP_ENABLED_IGREJA_IDS','')
    def forbidden(*a,**kw): raise AssertionError('disabled CD touched domain')
    monkeypatch.setattr(service,'actor',forbidden)
    # Ordinary worker fallback is simulated; the CD path must never invoke it.
    from app.services.llm import LLMClient, LLMResult, LLMUsage
    monkeypatch.setattr(LLMClient,'complete',lambda *a,**kw:LLMResult('Recurso indisponível.', LLMUsage('synthetic',0,0,0)))
    send(p,COMMAND)
    assert count(p)==0


@pytest.mark.parametrize('body',['sim!', 'confirmo', 'SIM por favor'])
def test_literal_confirmation_required(cd_turn,body):
    p=cd_turn
    send(p,COMMAND)
    from app.cd_whatsapp.turn import _contact, _handle
    outcome=inbound(p,body)
    with scoped(p.factory.kw['bind'],p.v['t']) as s:
        response,_=_handle(s,_contact(s,outcome),s.get(Message,outcome.inbound_message_id))
        assert response!='Presença registrada.'
        s.commit()
    assert count(p)==0


def test_lesson_not_in_configured_module_refused(cd_turn):
    p=cd_turn
    from app.routers.cd import CurriculoInput, TurmaInput
    from tests.test_cd_matriculas_pg import command
    with scoped(p.factory.kw['bind'],p.v['t']) as s:
        course=cd.create_curriculo(s,principal(p.v),CurriculoInput(id=uuid4(),nome='Curso curto',versao='curto',aulas_por_modulo=[1]))
        # Cancel in the first curriculum to allow a new explicit enrollment.
        cd.cancel_enrollment(s,principal(p.v),p.tid,p.mid)
        tid=cd.create_turma(s,principal(p.v),TurmaInput(id=uuid4(),nome='Curta',curriculo_id=course['id'],modulo_id=course['modulos'][0]['id']))['id']
        cd.enroll(s,principal(p.v),tid,command(p.v))
        from app.routers.cd import ResponsaveisInput
        cd.responsaveis(s,principal(p.v),tid,ResponsaveisInput(usuarios=[p.v['leader']]))
        s.commit()
    _,r,t=send(p,COMMAND.replace('Turma sintética','Curta').replace('aula 1','aula 100'))
    assert 'Aula não encontrada' in r.texto and len(t.calls)==1
    assert count(p)==0


@pytest.mark.parametrize('first', ['uv', 'cd'])
def test_uv_and_cd_pending_proposals_do_not_cross_domains(cd_turn, monkeypatch, first):
    from app.services import uv
    from app.uv_whatsapp import policy
    from app.routers.uv import ResponsaveisInput
    from tests.test_uv_presencas_pg import setup as setup_uv
    p=cd_turn
    monkeypatch.setattr(policy,'UV_WHATSAPP_APPROVED_RELEASE_ID','synthetic-only')
    monkeypatch.setenv('UV_WHATSAPP_ENABLED_IGREJA_IDS',str(p.v['t']))
    get_settings.cache_clear()
    with scoped(p.factory.kw['bind'],p.v['t']) as s:
        tid,_=setup_uv(s,p.v)
        uv.responsaveis(s,principal(p.v),tid,ResponsaveisInput(usuarios=[p.v['leader']]))
        s.commit()
    uv_command=COMMAND.replace('CD presença','UV presença')
    _,r,_=send(p,uv_command if first=='uv' else COMMAND)
    assert 'SIM' in r.texto and r.agent_privilege_context['kind']==first
    if first=='cd':
        _,r,_=send(p,uv_command)
        assert 'SIM' in r.texto and r.agent_privilege_context['kind']=='uv'
    _,r,t=send(p,'SIM',transport=_ClassifiedEvolution())
    assert r.texto=='Presença registrada.' and len(t.calls)==1
    assert r.agent_privilege_context['kind']=='uv' and count(p)==0
    with p.factory() as s:
        assert s.execute(text('select count(*) from uv_presencas_historico')).scalar_one()==1
        assert s.execute(text('select count(*) from cd_presencas')).scalar_one()==0
    # The earlier CD proposal cannot be resurrected by a later confirmation.
    send(p,'SIM',transport=_ClassifiedEvolution())
    assert count(p)==0
