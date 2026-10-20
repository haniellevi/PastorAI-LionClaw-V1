"""Complete ENVIAR turns against the full real migration chain and tenant RLS."""
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
from tests.test_messages_inbound_idempotency import (
    _seed_tier_a_handoff_anchor, _seed_inbound_anchor, _agent_outcome, _ClassifiedEvolution)

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def enviar_turn(database, seeded, monkeypatch):
    from app.enviar_whatsapp import policy
    from app.services.llm import LLMClient
    v = seeded
    for key, value in dict(APP_ENV='test', AGENT_TERM_VERSION='enviar-test',
        WHATSAPP_PILOTO_IGREJA_IDS=str(v['t']), ENVIAR_WHATSAPP_ENABLED_IGREJA_IDS=str(v['t']),
        SECRETS_ENCRYPTION_KEY=Fernet.generate_key().decode(), SESSION_JWT_SECRET='cd-synthetic-only',
        ALLOW_REAL_SENDS='true', CELULAS_REQUESTS_ENABLED='true').items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(policy, 'ENVIAR_WHATSAPP_APPROVED_RELEASE_ID', 'synthetic-only')
    get_settings.cache_clear()
    def forbidden(*a, **kw):
        raise AssertionError('unexpected external LLM')
    monkeypatch.setattr(LLMClient, 'complete', forbidden)
    factory = sessionmaker(database, expire_on_commit=False)
    @event.listens_for(factory, 'after_begin')
    def bound_database_wait(session, transaction, connection):
        connection.exec_driver_sql("set local statement_timeout='10s'")
    conv, person, _ = _seed_tier_a_handoff_anchor(factory, igreja_id=v['t'], provider_message_id='enviar-seed')
    with factory.begin() as s:
        s.execute(text('insert into whatsapp_connections(igreja_id,instance) values(:t,\'enviar-test\')'),dict(t=v['t']))
        s.execute(text('update app_users set pessoa_id=:p where id=:u'),dict(p=person,u=v['leader']))
        s.add(ConsentRecord(igreja_id=v['t'],pessoa_id=person,termo_versao='enviar-test',aceite_em=dt.datetime.now(dt.UTC)))
        s.add(AgentConfig(igreja_id=v['t'],ativo=True,comportamento='synthetic'))
        s.add(LlmCredential(igreja_id=v['t'],provedor='openai',modelo='gpt-5.6-luna',
            api_key_encrypted=encrypt_secret('synthetic'),validado=True,ativo=True))
    with factory.begin() as s:
        s.execute(text("update user_roles set papel='pastor' where user_id=:u"), dict(u=v['leader']))
        cell_id = uuid4()
        s.execute(text("insert into celulas(id,igreja_id,nome,cobertura_espiritual,ativo) values(:id,:t,'Célula sintética','Teste',true)"), dict(id=cell_id,t=v['t']))
    yield SimpleNamespace(factory=factory,v=v,conv=conv,person=person,cell=cell_id)
    get_settings.cache_clear()


def inbound(p, body):
    key = 'enviar-' + uuid4().hex
    mid = _seed_inbound_anchor(p.factory,igreja_id=p.v['t'],conversation_id=p.conv,provider_message_id=key,texto=body)
    return dataclasses.replace(_agent_outcome(p.conv,igreja_id=p.v['t'],provider_message_id=key,
        inbound_message_id=mid,instance='enviar-test',telefone='5500000000000'),texto=body)


def send(p, body, outcome=None, transport=None):
    class CommittedTransport(_ClassifiedEvolution):
        def send_text_classificado(self, instance, phone, body):
            with p.factory() as s:
                assert s.scalar(select(Message.id).where(Message.conversation_id==p.conv,
                    Message.direcao=='out',Message.texto==body)) is not None
                if body == RECEIPT:
                    assert s.execute(text('select count(*) from celula_solicitacao')).scalar_one()==1
            return super().send_text_classificado(instance,phone,body)
    transport = transport or CommittedTransport()
    outcome = outcome or inbound(p,body)
    worker.run_agent_for_message(p.factory,outcome,evolution_client=transport)
    with p.factory() as s:
        reply=s.scalars(select(Message).where(Message.conversation_id==p.conv,Message.direcao=='out')
            .order_by(Message.criado_em.desc(),Message.id.desc())).first()
    return outcome, reply, transport


COMMAND = 'ENVIAR nomear Célula sintética; Aluno sintético'
OPEN = 'ENVIAR abrir Nova sintética; Cobertura teste; Aluno sintético'
RECEIPT = 'Solicitação registrada; aguardando aprovação no painel autenticado.'


def count(p):
    with p.factory() as s:
        return s.execute(text('select count(*) from celula_solicitacao')).scalar_one()


def unchanged(p):
    with p.factory() as s:
        assert s.execute(text('select count(*) from celulas')).scalar_one() == 1
        assert s.execute(text('select lider_id from celulas where id=:id'),dict(id=p.cell)).scalar_one() is None
        assert not s.execute(text('select apto_lider from pessoas where id=:id'),dict(id=p.v['p'])).scalar_one()
        assert s.execute(text('select count(*) from enviar_avaliacoes')).scalar_one() == 0


@pytest.mark.parametrize('command', [COMMAND, OPEN])
@pytest.mark.parametrize('role', ['pastor','admin','lider_celula'])
def test_complete_confirmed_request_no_leadership(enviar_turn, role, command):
    p=enviar_turn
    with p.factory.begin() as s:
        s.execute(text('update user_roles set papel=:r where user_id=:u'),dict(r=role,u=p.v['leader']))
        if role == 'lider_celula':
            s.execute(text('update celulas set lider_id=:p where id=:id'),dict(p=p.person,id=p.cell))
            s.execute(text('insert into celula_membro(igreja_id,celula_id,pessoa_id) values(:t,:c,:p)'),dict(t=p.v['t'],c=p.cell,p=p.v['p']))
    _,r,t=send(p,command)
    assert 'SIM' in r.texto and len(t.calls)==1 and count(p)==0
    outcome,r,t=send(p,'SIM')
    assert r.texto==RECEIPT and len(t.calls)==1 and count(p)==1
    send(p,'SIM',outcome=outcome)
    _,r,t=send(p,'SIM')
    assert 'já registrada' in r.texto and count(p)==1
    with p.factory() as s:
        row=s.execute(text('select status,tipo from celula_solicitacao')).one()
        assert row.status=='aguardando' and row.tipo==('nomear_lider' if command==COMMAND else 'abrir_celula')
        assert s.execute(text("select count(*) from celula_solicitacao_evento where acao='criada'")).scalar_one()==1
        assert s.execute(text('select count(*) from celulas')).scalar_one()==1
        assert s.execute(text('select lider_id from celulas where id=:id'),dict(id=p.cell)).scalar_one()==(p.person if role=='lider_celula' else None)
        assert s.execute(text('select count(*) from enviar_avaliacoes')).scalar_one()==0
    _,r,t=send(p,'ENVIAR solicitações')
    assert 'aguardando' in r.texto and len(t.calls)==1


@pytest.mark.parametrize('state',['role','revoked','unlinked','foreign'])
def test_permission_revalidated_on_confirmation(enviar_turn,state):
    p=enviar_turn
    send(p,COMMAND)
    with p.factory.begin() as s:
        if state=='role': s.execute(text("update user_roles set papel='operador' where user_id=:u"),dict(u=p.v['leader']))
        if state=='revoked': s.execute(text("update app_users set status='revogado' where id=:u"),dict(u=p.v['leader']))
        if state=='unlinked': s.execute(text('update app_users set pessoa_id=null where id=:u'),dict(u=p.v['leader']))
        if state=='foreign': s.execute(text('update pessoas set igreja_id=:t where id=:p'),dict(t=p.v['other'],p=p.v['p']))
    _,r,t=send(p,'SIM')
    assert r.texto!=RECEIPT and count(p)==0 and len(t.calls)==1
    unchanged(p)


@pytest.mark.parametrize('body',['ENVIAR','ENVIAR pessoa Aluno sintético',COMMAND,OPEN])
def test_unauthorized_role_refused(enviar_turn,body):
    p=enviar_turn
    with p.factory.begin() as s:
        s.execute(text("update user_roles set papel='operador' where user_id=:u"),dict(u=p.v['leader']))
    _,r,t=send(p,body)
    assert 'Sem permissão' in r.texto and 'Aluno sintético' not in r.texto and len(t.calls)==1
    assert count(p)==0
    unchanged(p)


def test_minimal_read_uses_official_domain(enviar_turn):
    p=enviar_turn
    _,r,t=send(p,'ENVIAR pessoa Aluno sintético')
    assert len(t.calls)==1
    assert all(x in r.texto for x in ['UV','CD certificado','Reencontro','referência não informada'])
    assert '5500' not in r.texto
    assert count(p)==0


@pytest.mark.parametrize('body',['ENVIAR aprovar nomeação','ENVIAR avaliar apto','ENVIAR validar Reencontro','ENVIAR revogar certificado'])
def test_sensitive_tools_absent(enviar_turn,body):
    p=enviar_turn
    _,r,t=send(p,body)
    assert 'painel autenticado' in r.texto and len(t.calls)==1
    assert count(p)==0
    unchanged(p)


@pytest.mark.parametrize('answer',['NÃO','Sim!', 'sim.', 'confirmo','SIM por favor'])
def test_explicit_literal_confirmation(enviar_turn,answer,monkeypatch):
    p=enviar_turn
    _,proposal,_=send(p,COMMAND)
    from app.services.llm import LLMClient, LLMResult, LLMUsage
    monkeypatch.setattr(LLMClient,'complete',lambda *a,**kw:LLMResult('Esclareça.',LLMUsage('synthetic',0,0,0)))
    _,r,t=send(p,answer)
    assert len(t.calls)==1 and count(p)==0
    if answer=='NÃO':
        assert r.texto=='Proposta cancelada.'
    elif answer=='SIM por favor':
        assert r.texto=='Esclareça.'
    else:
        assert r.texto=='Para registrar a solicitação, responda somente SIM ou NÃO em até 10 minutos da proposta original.'
        assert r.agent_privilege_context['proposal']==proposal.agent_privilege_context['proposal']
        assert r.agent_privilege_context['delivered_at']==proposal.agent_privilege_context['delivered_at']
        _,r,_=send(p,'SIM')
        assert r.texto==RECEIPT and count(p)==1


@pytest.mark.parametrize('fence',['release','church','human'])
def test_disabled_no_domain_execution(enviar_turn,monkeypatch,fence):
    from app.enviar_whatsapp import policy, service
    p=enviar_turn
    if fence=='release': monkeypatch.setattr(policy,'ENVIAR_WHATSAPP_APPROVED_RELEASE_ID',None)
    elif fence=='church': monkeypatch.setenv('ENVIAR_WHATSAPP_ENABLED_IGREJA_IDS','')
    else:
        monkeypatch.setenv('CELULAS_REQUESTS_ENABLED','false');get_settings.cache_clear()
    if fence!='human':
        def forbidden(*a,**kw): raise AssertionError('disabled touched domain')
        monkeypatch.setattr(service,'actor',forbidden)
    from app.services.llm import LLMClient, LLMResult, LLMUsage
    monkeypatch.setattr(LLMClient,'complete',lambda *a,**kw:LLMResult('Recurso indisponível.',LLMUsage('synthetic',0,0,0)))
    send(p,COMMAND)
    assert count(p)==0
    unchanged(p)


@pytest.mark.parametrize('body',['Quero parar de receber mensagens','Quero me matar','Quero falar com humano'])
def test_priority_paths(enviar_turn,body):
    p=enviar_turn
    send(p,COMMAND)
    send(p,body)
    assert count(p)==0
    with p.factory() as s:
        replies=s.scalars(select(Message).where(Message.conversation_id==p.conv,Message.direcao=='out')).all()
        assert not any(r.agent_privilege_context and r.agent_privilege_context.get('kind')=='enviar'
            and r.agent_privilege_context.get('inbound_message_id')==str(s.scalar(select(Message.id).where(Message.texto==body,Message.direcao=='in'))) for r in replies)


@pytest.mark.parametrize('state',['optout','consent','handoff'])
def test_contact_suppressed_before_any_response(enviar_turn,state):
    from app.enviar_whatsapp.turn import run_enviar_turn
    p=enviar_turn
    with p.factory.begin() as s:
        if state=='optout': s.execute(text('update pessoas set optout=true where id=:p'),dict(p=p.person))
        if state=='consent': s.execute(text('delete from consent_records'))
        if state=='handoff': s.execute(text("update conversations set estado='humano'"))
    transport=_ClassifiedEvolution()
    assert run_enviar_turn(p.factory,p.factory,inbound(p,COMMAND),igreja_id=p.v['t'],
        uses_dedicated_agent_session=False,ownership_guard=None,evolution_client=transport) is None
    assert not transport.calls and count(p)==0


@pytest.mark.parametrize('state',['expired','undelivered'])
def test_expired_or_undelivered_never_writes(enviar_turn,state):
    p=enviar_turn
    _,r,_=send(p,COMMAND)
    with p.factory.begin() as s:
        row=s.get(Message,r.id)
        if state=='expired': row.criado_em=dt.datetime.now(dt.UTC)-dt.timedelta(hours=1)
        else:
            row.agent_privilege_context={k:v for k,v in row.agent_privilege_context.items() if k!='delivered_at'}
    from app.services.llm import LLMClient, LLMResult, LLMUsage
    from pytest import MonkeyPatch
    with MonkeyPatch.context() as mp:
        mp.setattr(LLMClient,'complete',lambda *a,**kw:LLMResult('Sem proposta válida.',LLMUsage('synthetic',0,0,0)))
        send(p,'SIM')
    assert count(p)==0


@pytest.mark.parametrize('answer', ['Sim!', 'confirmo'])
@pytest.mark.parametrize('retry_seconds', [599, 600, 601])
def test_clarification_retry_respects_original_deadline(enviar_turn, monkeypatch, answer, retry_seconds):
    from app.enviar_whatsapp import turn
    p = enviar_turn
    _, proposal, _ = send(p, COMMAND)
    delivered = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=598)
    # The answer arrives just before expiry; transport fails before delivery.
    with p.factory.begin() as s:
        row = s.get(Message, proposal.id)
        row.criado_em = delivered - dt.timedelta(seconds=1)
        row.agent_privilege_context = dict(row.agent_privilege_context, delivered_at=delivered.isoformat())
    outcome = inbound(p, answer)
    monkeypatch.setattr(turn, 'now', lambda db: delivered + dt.timedelta(seconds=598))
    with pytest.raises(worker.AgentReplyRetryable):
        send(p, answer, outcome=outcome, transport=_ClassifiedEvolution('falhou_retentavel'))
    monkeypatch.setattr(turn, 'now', lambda db: delivered + dt.timedelta(seconds=retry_seconds))
    _, reply, transport = send(p, answer, outcome=outcome)
    assert reply.agent_privilege_context['delivered_at'] == delivered.isoformat()
    assert len(transport.calls) == (1 if retry_seconds < 600 else 0)
    assert reply.agent_reply_state == ('ia' if retry_seconds < 600 else 'ia_suprimida')
    assert count(p) == 0
    unchanged(p)


def test_retry_receipt_after_commit(enviar_turn):
    p=enviar_turn
    send(p,COMMAND)
    outcome=inbound(p,'SIM')
    with pytest.raises(worker.AgentReplyRetryable):
        send(p,'SIM',outcome=outcome,transport=_ClassifiedEvolution('falhou_retentavel'))
    assert count(p)==1
    _,r,t=send(p,'SIM',outcome=outcome)
    assert r.texto==RECEIPT and len(t.calls)==1 and count(p)==1
    unchanged(p)


def test_other_church_targets_not_visible(enviar_turn):
    p=enviar_turn
    with p.factory.begin() as s:
        s.execute(text('update pessoas set igreja_id=:t where id=:p'),dict(t=p.v['other'],p=p.v['p']))
    _,r,t=send(p,COMMAND)
    assert len(t.calls)==1 and 'não encontrado' in r.texto and count(p)==0
    _,r,t=send(p,'ENVIAR')
    assert 'Aluno sintético' not in r.texto


def test_read_revocation_before_transport(enviar_turn):
    from app.enviar_whatsapp.turn import reply_still_authorized
    from app.db.models import Conversation
    p=enviar_turn
    _,reply,_=send(p,'ENVIAR pessoa Aluno sintético')
    with p.factory.begin() as s:
        s.execute(text("update user_roles set papel='operador' where user_id=:u"),dict(u=p.v['leader']))
    with scoped(p.factory.kw['bind'],p.v['t']) as s:
        assert not reply_still_authorized(s,s.get(Message,reply.id),conversation=s.get(Conversation,p.conv),
            recipient_phone='5500000000000',instance='enviar-test')


def test_unrelated_enviar_reaches_normal_agent_without_role(enviar_turn,monkeypatch):
    p=enviar_turn
    with p.factory.begin() as s:
        s.execute(text('delete from user_roles where user_id=:u'),dict(u=p.v['leader']))
    from app.services.llm import LLMClient, LLMResult, LLMUsage
    monkeypatch.setattr(LLMClient,'complete',lambda *a,**kw:LLMResult('Resposta normal à foto.',LLMUsage('synthetic',0,0,0)))
    _,r,t=send(p,'Enviar foto da célula')
    assert r.texto=='Resposta normal à foto.' and len(t.calls)==1 and count(p)==0


@pytest.mark.parametrize('body',['ENVIAR pessoa Aluno sintético',COMMAND,OPEN])
def test_leader_cannot_target_other_leaders_person_or_cell(enviar_turn,body):
    p=enviar_turn
    with p.factory.begin() as s:
        s.execute(text("update user_roles set papel='lider_celula' where user_id=:u"),dict(u=p.v['leader']))
        other_person=s.execute(text('select pessoa_id from app_users where id=:u'),dict(u=p.v['uid'])).scalar_one()
        s.execute(text('update celulas set lider_id=:p where id=:c'),dict(p=other_person,c=p.cell))
        s.execute(text('insert into celula_membro(igreja_id,celula_id,pessoa_id) values(:t,:c,:p)'),dict(t=p.v['t'],c=p.cell,p=p.v['p']))
    _,r,t=send(p,body)
    assert 'não encontrado' in r.texto and len(t.calls)==1 and count(p)==0
    _,r,_=send(p,'ENVIAR')
    assert 'Aluno sintético' not in r.texto


def test_leader_cannot_nominate_other_leaders_cell(enviar_turn):
    p=enviar_turn
    with p.factory.begin() as s:
        s.execute(text("update user_roles set papel='lider_celula' where user_id=:u"),dict(u=p.v['leader']))
        own=uuid4()
        s.execute(text("insert into celulas(id,igreja_id,nome,cobertura_espiritual,lider_id,ativo) values(:c,:t,'Própria','Teste',:p,true)"),dict(c=own,t=p.v['t'],p=p.person))
        s.execute(text('insert into celula_membro(igreja_id,celula_id,pessoa_id) values(:t,:c,:p)'),dict(t=p.v['t'],c=own,p=p.v['p']))
        s.execute(text('update celulas set lider_id=(select pessoa_id from app_users where id=:u) where id=:c'),dict(u=p.v['uid'],c=p.cell))
    _,r,t=send(p,COMMAND)
    assert 'não encontrado' in r.texto and len(t.calls)==1 and count(p)==0


def test_history_excludes_other_author_even_for_visible_cell(enviar_turn):
    p=enviar_turn
    send(p,COMMAND)
    send(p,'SIM')
    with p.factory.begin() as s:
        own=s.execute(text('select id from celula_solicitacao')).scalar_one()
        foreign=uuid4()
        s.execute(text("insert into celula_solicitacao(id,igreja_id,tipo,celula_id,solicitante_id,payload_proposto,payload_atual,candidato_id,status) select :id,igreja_id,tipo,celula_id,(select pessoa_id from app_users where id=:u),payload_proposto,payload_atual,candidato_id,'rejeitada' from celula_solicitacao where id=:own"),dict(id=foreign,u=p.v['uid'],own=own))
        s.execute(text("update user_roles set papel='lider_celula' where user_id=:u"),dict(u=p.v['leader']))
        s.execute(text('update celulas set lider_id=:p where id=:c'),dict(p=p.person,c=p.cell))
    _,r,t=send(p,'ENVIAR solicitações')
    assert str(own) in r.texto and str(foreign) not in r.texto and len(t.calls)==1


@pytest.mark.parametrize('command',['ENVIAR','ENVIAR solicitações'])
@pytest.mark.parametrize('size',[25,26])
def test_pagination_notice(enviar_turn,command,size):
    p=enviar_turn
    if command=='ENVIAR solicitações':
        send(p,COMMAND)
        send(p,'SIM')
    with p.factory.begin() as s:
        if command=='ENVIAR':
            s.execute(text('delete from decisions'))
            s.execute(text('update pessoas set arquivada_em=now()'))
            for n in range(size-1):
                s.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:id,:t,:name,:phone)"),dict(id=uuid4(),t=p.v['t'],name=f'Pessoa teste {n:02}',phone=f'550000001{n:03}'))
            # Keep the known sender active for server contact resolution.
            s.execute(text('update pessoas set arquivada_em=null where id=:p'),dict(p=p.person))
        else:
            for _ in range(size-1):
                s.execute(text("insert into celula_solicitacao(id,igreja_id,tipo,celula_id,solicitante_id,payload_proposto,payload_atual,candidato_id,status) select :id,igreja_id,tipo,celula_id,solicitante_id,payload_proposto,payload_atual,candidato_id,'rejeitada' from celula_solicitacao limit 1"),dict(id=uuid4()))
    _,r,t=send(p,command)
    assert len(t.calls)==1
    assert ('Há mais resultados, use o painel.' in r.texto)==(size>25)
