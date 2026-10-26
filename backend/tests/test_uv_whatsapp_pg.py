"""Complete UV turns against the full real migration chain and tenant RLS."""
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
from app.workers import queue_worker as worker
from tests.test_uv_turmas_pg import rls_database_url, migrated_database, database, seeded, scoped, principal
from tests.private_send_pg import send_release_login  # noqa: F401
from tests.test_uv_presencas_pg import setup
from tests.test_messages_inbound_idempotency import (
    _seed_tier_a_handoff_anchor, _seed_inbound_anchor, _agent_outcome, _ClassifiedEvolution)

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def uv_turn(database, seeded, monkeypatch):
    from app.uv_whatsapp import policy
    from app.services.llm import LLMClient
    from app.routers.uv import ResponsaveisInput
    from app.services import uv
    v = seeded
    for key, value in dict(APP_ENV='test', AGENT_TERM_VERSION='uv-test',
        WHATSAPP_PILOTO_IGREJA_IDS=str(v['t']), UV_WHATSAPP_ENABLED_IGREJA_IDS=str(v['t']),
        SECRETS_ENCRYPTION_KEY=Fernet.generate_key().decode(), SESSION_JWT_SECRET='uv-synthetic-only',
        ALLOW_REAL_SENDS='true').items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(policy, 'UV_WHATSAPP_APPROVED_RELEASE_ID', 'synthetic-only')
    get_settings.cache_clear()
    def forbidden(*a, **kw):
        raise AssertionError('unexpected external LLM')
    monkeypatch.setattr(LLMClient, 'complete', forbidden)
    factory = sessionmaker(database, expire_on_commit=False)
    @event.listens_for(factory, 'after_begin')
    def bound_database_wait(session, transaction, connection):
        connection.exec_driver_sql("set local statement_timeout='10s'")
    conv, person, _ = _seed_tier_a_handoff_anchor(factory, igreja_id=v['t'], provider_message_id='uv-seed')
    with factory.begin() as s:
        s.execute(text('insert into whatsapp_connections(igreja_id,instance) values(:t,\'uv-test\')'),dict(t=v['t']))
        s.execute(text('update app_users set pessoa_id=:p where id=:u'),dict(p=person,u=v['leader']))
        s.add(ConsentRecord(igreja_id=v['t'],pessoa_id=person,termo_versao='uv-test',aceite_em=dt.datetime.now(dt.UTC)))
        s.add(AgentConfig(igreja_id=v['t'],ativo=True,comportamento='synthetic'))
        s.add(LlmCredential(igreja_id=v['t'],provedor='openai',modelo='gpt-5.6-luna',
            api_key_encrypted=encrypt_secret('synthetic'),validado=True,ativo=True))
    with scoped(database,v['t']) as s:
        tid, mid = setup(s,v)
        uv.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        s.commit()
    yield SimpleNamespace(factory=factory,v=v,conv=conv,person=person,tid=tid,mid=mid)
    get_settings.cache_clear()


def inbound(p, body):
    key = 'uv-' + uuid4().hex
    mid = _seed_inbound_anchor(p.factory,igreja_id=p.v['t'],conversation_id=p.conv,provider_message_id=key,texto=body)
    return dataclasses.replace(_agent_outcome(p.conv,igreja_id=p.v['t'],provider_message_id=key,
        inbound_message_id=mid,instance='uv-test',telefone='5500000000000'),texto=body)


def send(p, body, outcome=None, transport=None):
    class CommittedTransport(_ClassifiedEvolution):
        def send_text_classificado(self, instance, phone, body):
            with p.factory() as s:
                assert s.scalar(select(Message.id).where(Message.conversation_id==p.conv,
                    Message.direcao=='out',Message.texto==body)) is not None
                if body == 'Presença registrada.':
                    assert s.execute(text('select count(*) from uv_presencas_historico')).scalar_one()==1
            return super().send_text_classificado(instance,phone,body)
    transport = transport or CommittedTransport()
    outcome = outcome or inbound(p,body)
    worker.run_agent_for_message(p.factory,outcome,evolution_client=transport)
    with p.factory() as s:
        reply=s.scalars(select(Message).where(Message.conversation_id==p.conv,Message.direcao=='out')
            .order_by(Message.criado_em.desc(),Message.id.desc())).first()
    return outcome, reply, transport


COMMAND='UV presença Turma sintética; aula 1; Aluno sintético; presente'


def count(p):
    with p.factory() as s:
        return s.execute(text('select count(*) from uv_presencas_historico')).scalar_one()


@pytest.mark.parametrize('role',['lider_consol','pastor','admin'])
def test_complete_turn_confirmation_and_replay(uv_turn, role):
    p=uv_turn
    with p.factory.begin() as s:
        s.execute(text('update user_roles set papel=:r where user_id=:u'),dict(r=role,u=p.v['leader']))
        if role in {'pastor','admin'}:
            s.execute(text('update uv_responsaveis set ativo=false'))
    _,r,t=send(p,'UV turma Turma sintética')
    assert len(t.calls)==1 and r.agent_reply_state=='ia'
    assert 'Aluno sintético' in r.texto and 'pendentes 1, 2' in r.texto
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


@pytest.mark.parametrize('state',['unlinked','revoked','role','foreign','closed','future','complete'])
def test_live_refusal_on_confirmation(uv_turn,state):
    p=uv_turn
    _,r,t=send(p,COMMAND)
    assert 'SIM' in r.texto
    with p.factory.begin() as s:
        if state=='unlinked': s.execute(text('update uv_responsaveis set ativo=false'))
        if state=='revoked': s.execute(text("update app_users set status='revogado' where id=:u"),dict(u=p.v['leader']))
        if state=='role': s.execute(text("update user_roles set papel='operador' where user_id=:u"),dict(u=p.v['leader']))
        if state=='foreign': s.execute(text('update app_users set pessoa_id=null where id=:u'),dict(u=p.v['leader']))
        if state=='closed': s.execute(text('update uv_turmas set encerrada=true'))
        if state=='future': s.execute(text("update uv_atividades set data='2099-01-01'"))
        if state=='complete':
            s.execute(text("insert into uv_conclusoes(id,igreja_id,pessoa_id,turma_id,matricula_id,confirmada_por,etapa_anterior,etapa_resultante,origem_aptidao) values(:id,:t,:p,:tid,:mid,:u,'consolidar','discipular','conclusao_uv')"),dict(id=uuid4(),t=p.v['t'],p=p.v['p'],tid=p.tid,mid=p.mid,u=p.v['uid']))
    _,r,t=send(p,'SIM')
    assert len(t.calls)==1 and r.texto!='Presença registrada.'
    assert count(p)==0


@pytest.mark.parametrize('state',['unlinked','role','revoked'])
def test_denied_read_without_leaking_students(uv_turn,state):
    p=uv_turn
    with p.factory.begin() as s:
        if state=='unlinked': s.execute(text('update uv_responsaveis set ativo=false'))
        if state=='role': s.execute(text("update user_roles set papel='operador' where user_id=:u"),dict(u=p.v['leader']))
        if state=='revoked': s.execute(text("update app_users set status='revogado' where id=:u"),dict(u=p.v['leader']))
    _,r,t=send(p,'UV turma Turma sintética')
    assert len(t.calls)==1 and 'Aluno sintético' not in r.texto and count(p)==0


@pytest.mark.parametrize('body',['Quero parar de receber mensagens','Quero me matar','Quero falar com humano'])
def test_priority_paths(uv_turn,body):
    p=uv_turn
    send(p,COMMAND)
    _,r,_=send(p,body)
    assert (r.agent_privilege_context or {}).get('kind')!='uv'
    assert count(p)==0


@pytest.mark.parametrize('state',['optout','consent','handoff'])
def test_contact_suppressed_before_response(uv_turn,state):
    from app.uv_whatsapp.turn import run_uv_turn
    p=uv_turn
    with p.factory.begin() as s:
        if state=='optout': s.execute(text('update pessoas set optout=true where id=:p'),dict(p=p.person))
        if state=='consent': s.execute(text('delete from consent_records'))
        if state=='handoff': s.execute(text("update conversations set estado='humano'"))
    transport=_ClassifiedEvolution()
    assert run_uv_turn(p.factory,p.factory,inbound(p,COMMAND),igreja_id=p.v['t'],
        uses_dedicated_agent_session=False,ownership_guard=None,evolution_client=transport) is None
    assert not transport.calls and count(p)==0


def test_closed_read_and_future_refused(uv_turn):
    p=uv_turn
    with p.factory.begin() as s:
        s.execute(text("update uv_atividades set data='2099-01-01'"))
    _,r,_=send(p,COMMAND)
    assert 'futura' in r.texto and count(p)==0
    with p.factory.begin() as s:
        s.execute(text('update uv_turmas set encerrada=true'))
    _,r,_=send(p,'UV turma Turma sintética')
    assert 'encerrada' in r.texto and 'Aluno sintético' in r.texto
    _,r,_=send(p,COMMAND)
    assert 'encerrada' in r.texto and count(p)==0


def test_other_church_is_not_visible(uv_turn):
    p=uv_turn
    with p.factory.begin() as s:
        s.execute(text("insert into uv_turmas(id,igreja_id,nome) values(:id,:t,'Turma estrangeira')"),dict(id=uuid4(),t=p.v['other']))
    _,r,t=send(p,'UV turma Turma estrangeira')
    assert len(t.calls)==1 and 'não encontrado' in r.texto and count(p)==0
    _,r,_=send(p,'UV')
    assert 'Turma estrangeira' not in r.texto


def test_expired_or_undelivered_proposal_never_writes(uv_turn):
    from app.uv_whatsapp.turn import _handle, _contact
    p=uv_turn
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


def test_retry_receipt_after_commit_never_writes_again(uv_turn,send_release_login):
    p=uv_turn
    send(p,COMMAND)
    # A classified provider failure leaves the committed domain write and pending reply.
    outcome=inbound(p,'SIM')
    with pytest.raises(worker.AgentReplyRetryable):
        send(p,'SIM',outcome=outcome,transport=_ClassifiedEvolution('falhou_retentavel'))
    assert count(p)==1
    _,r,t=send(p,'SIM',outcome=outcome)
    assert count(p)==1 and len(t.calls)==1 and r.texto=='Presença registrada.'


def test_revoked_before_delivery_suppresses_private_reply(uv_turn):
    from app.uv_whatsapp.turn import reply_still_authorized
    from app.db.models import Conversation
    p=uv_turn
    _,r,_=send(p,'UV turma Turma sintética')
    with p.factory.begin() as s:
        s.execute(text('update uv_responsaveis set ativo=false'))
    with scoped(p.factory.kw['bind'],p.v['t']) as s:
        assert not reply_still_authorized(s,s.get(Message,r.id),conversation=s.get(Conversation,p.conv),
            recipient_phone='5500000000000',instance='uv-test')


def test_reposicao_and_explicit_correction(uv_turn):
    p=uv_turn
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
        current=s.execute(text('select anterior_id,presente,modalidade from uv_presencas')).one()
        assert str(current.anterior_id)==proposal['anterior_id']
        assert (current.presente,current.modalidade)==(True,'reposicao')



def test_confirmation_persisted_before_proposal_delivery_is_refused(uv_turn):
    p=uv_turn
    _,r,_=send(p,COMMAND)
    outcome=inbound(p,'SIM')
    with p.factory.begin() as s:
        # Simulate a SIM already in the queue before the proposal transport returned.
        proposal=s.get(Message,r.id)
        proposal.agent_privilege_context=dict(proposal.agent_privilege_context,
            delivered_at=(dt.datetime.now(dt.UTC)+dt.timedelta(seconds=1)).isoformat())
    from app.uv_whatsapp.turn import _contact, _handle
    with scoped(p.factory.kw['bind'],p.v['t']) as s:
        response,_=_handle(s,_contact(s,outcome),s.get(Message,outcome.inbound_message_id))
        assert response!='Presença registrada.'
        s.commit()
    assert count(p)==0


def test_fresh_repeated_sim_does_not_execute_again(uv_turn):
    p=uv_turn
    send(p,COMMAND)
    send(p,'SIM')
    _,r,t=send(p,'SIM')
    assert count(p)==1 and len(t.calls)==1
    assert 'já registrada' in r.texto


@pytest.mark.parametrize('kind',['list','read'])
def test_changed_read_projection_is_suppressed(uv_turn,kind):
    from app.uv_whatsapp.turn import reply_still_authorized
    from app.db.models import Conversation
    p=uv_turn
    _,r,_=send(p,'UV' if kind=='list' else 'UV turma Turma sintética')
    with p.factory.begin() as s:
        if kind=='list': s.execute(text('update uv_responsaveis set ativo=false'))
        else: s.execute(text('update pessoas set arquivada_em=now() where id=:p'),dict(p=p.v['p']))
    with scoped(p.factory.kw['bind'],p.v['t']) as s:
        assert not reply_still_authorized(s,s.get(Message,r.id),conversation=s.get(Conversation,p.conv),
            recipient_phone='5500000000000',instance='uv-test')


def test_concurrent_confirmations_write_once(uv_turn):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    p=uv_turn
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
def test_uv_dialog_never_captures_unrelated_inbound(uv_turn,stage,body):
    from app.uv_whatsapp.turn import run_uv_turn
    p=uv_turn
    send(p,COMMAND)
    if stage=='receipt': send(p,'SIM')
    transport=_ClassifiedEvolution()
    assert run_uv_turn(p.factory,p.factory,inbound(p,body),igreja_id=p.v['t'],
        uses_dedicated_agent_session=False,ownership_guard=None,evolution_client=transport) is None
    assert not transport.calls
    assert count(p)==(1 if stage=='receipt' else 0)


def test_same_value_has_no_proposal(uv_turn):
    p=uv_turn
    send(p,COMMAND)
    send(p,'SIM')
    _,r,t=send(p,COMMAND)
    assert 'já registrada' in r.texto and len(t.calls)==1
    assert r.agent_privilege_context['stage'] != 'proposal'
    assert count(p)==1


def test_changed_record_refuses_confirmation(uv_turn):
    from app.services import uv
    from tests.test_uv_presencas_pg import payload
    p=uv_turn
    send(p,COMMAND.replace('presente','ausente'))
    send(p,'SIM')
    _,r,_=send(p,COMMAND)
    assert 'Correção: atual ausente → novo presente' in r.texto
    with scoped(p.factory.kw['bind'],p.v['t']) as s:
        # A competing correction can even restore the same value; identity still changed.
        uv.attendance(s,principal(p.v),p.tid,p.mid,1,
            payload(presente=False,anterior_id=UUID(r.agent_privilege_context['proposal']['anterior_id'])))
        s.commit()
    _,r,t=send(p,'SIM',transport=_ClassifiedEvolution())
    assert 'nova proposta' in r.texto and len(t.calls)==1
    assert count(p)==2
    with p.factory() as s:
        assert s.execute(text('select presente from uv_presencas')).scalar_one() is False


def test_second_sim_while_receipt_pending(uv_turn):
    p=uv_turn
    send(p,COMMAND)
    outcome=inbound(p,'SIM')
    with pytest.raises(worker.AgentReplyRetryable):
        send(p,'SIM',outcome=outcome,transport=_ClassifiedEvolution('falhou_retentavel'))
    _,r,t=send(p,'SIM')
    assert 'aguarde' in r.texto.lower() and len(t.calls)==1
    assert count(p)==1


def test_no_after_receipt_is_not_uv_pending(uv_turn):
    from app.uv_whatsapp.turn import run_uv_turn
    p=uv_turn
    send(p,COMMAND)
    send(p,'SIM')
    transport=_ClassifiedEvolution()
    assert run_uv_turn(p.factory,p.factory,inbound(p,'não'),igreja_id=p.v['t'],
        uses_dedicated_agent_session=False,ownership_guard=None,evolution_client=transport) is None
    assert not transport.calls and count(p)==1


def test_active_sender_in_b_cannot_change_class_in_a(uv_turn):
    p=uv_turn
    with p.factory.begin() as s:
        s.execute(text('update uv_turmas set nome=:name where id=:id'),dict(name='Turma exclusiva A',id=p.tid))
        s.execute(text('delete from uv_responsaveis'))
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
        s.add(ConsentRecord(igreja_id=p.v['other'],pessoa_id=p.person,termo_versao='uv-test',aceite_em=dt.datetime.now(dt.UTC)))
    from pytest import MonkeyPatch
    with MonkeyPatch.context() as mp:
        mp.setenv('WHATSAPP_PILOTO_IGREJA_IDS',str(p.v['other']))
        mp.setenv('UV_WHATSAPP_ENABLED_IGREJA_IDS',str(p.v['other']))
        get_settings.cache_clear()
        p.v=dict(p.v,t=p.v['other'])
        _,r,t=send(p,COMMAND.replace('Turma sintética','Turma exclusiva A'))
        assert len(t.calls)==1 and 'não encontrado' in r.texto
        assert r.agent_privilege_context['stage'] != 'proposal'
        assert count(p)==0
