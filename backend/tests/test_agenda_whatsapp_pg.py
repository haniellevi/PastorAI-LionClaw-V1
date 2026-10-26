"""Complete local agenda turns against the full real migration chain and tenant RLS."""
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
from tests.test_uv_turmas_pg import migrated_database, database, seeded
from tests.private_send_pg import send_release_login  # noqa: F401
from tests.test_messages_inbound_idempotency import (
    _seed_tier_a_handoff_anchor, _seed_inbound_anchor, _agent_outcome, _ClassifiedEvolution)

pytestmark = pytest.mark.rls_integration


@pytest.fixture(scope='module')
def rls_database_url():
    # Missing PG is a hard failure for this suite, never a skip.
    import os
    from urllib.parse import urlsplit
    from tests.conftest_rls import assert_disposable_database
    url = os.environ['UV_TURMAS_DATABASE_URL']
    assert_disposable_database(url)
    parsed = urlsplit(url)
    assert parsed.hostname in {'127.0.0.1', 'localhost', '::1'}
    assert parsed.path == '/uv_turmas_test'
    return url



@pytest.fixture
def agenda_turn(database, seeded, monkeypatch):
    from app.agenda_whatsapp import policy
    from app.services import whatsapp_privilege
    from app.services.llm import LLMClient
    v = seeded
    for key, value in dict(APP_ENV='test', AGENT_TERM_VERSION='agenda-test',
        WHATSAPP_PILOTO_IGREJA_IDS=str(v['t']), AGENDA_WRITE_WHATSAPP_ENABLED_IGREJA_IDS=str(v['t']),
        SECRETS_ENCRYPTION_KEY=Fernet.generate_key().decode(), SESSION_JWT_SECRET='agenda-synthetic-only',
        ALLOW_REAL_SENDS='true', ASAAS_BILLING_ENABLED='false', BREVO_SEND_MODE='off',
        BROADCAST_ASYNC_ENABLED='false').items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(policy, 'AGENDA_WRITE_WHATSAPP_APPROVED_RELEASE_ID', 'synthetic-only')
    monkeypatch.setattr(whatsapp_privilege, 'PRIVILEGE_APPROVED_RELEASE_ID', 'synthetic-only')
    monkeypatch.setenv('AGENT_PRIVILEGE_ENABLED_IGREJA_IDS', str(v['t']))
    get_settings.cache_clear()
    def forbidden(*a, **kw):
        raise AssertionError('unexpected external LLM')
    monkeypatch.setattr(LLMClient, 'complete', forbidden)
    factory = sessionmaker(database, expire_on_commit=False)
    @event.listens_for(factory, 'after_begin')
    def bound_database_wait(session, transaction, connection):
        connection.exec_driver_sql("set local statement_timeout='10s'")
    conv, person, _ = _seed_tier_a_handoff_anchor(factory, igreja_id=v['t'], provider_message_id='agenda-seed')
    with factory.begin() as s:
        s.execute(text('insert into whatsapp_connections(igreja_id,instance) values(:t,\'agenda-test\')'),dict(t=v['t']))
        s.execute(text('update app_users set pessoa_id=:p where id=:u'),dict(p=person,u=v['leader']))
        s.add(ConsentRecord(igreja_id=v['t'],pessoa_id=person,termo_versao='agenda-test',aceite_em=dt.datetime.now(dt.UTC)))
        s.add(AgentConfig(igreja_id=v['t'],ativo=True,comportamento='synthetic'))
        s.add(LlmCredential(igreja_id=v['t'],provedor='openai',modelo='gpt-5.6-luna',
            api_key_encrypted=encrypt_secret('synthetic'),validado=True,ativo=True))
    with factory.begin() as s:
        s.execute(text("update user_roles set papel='pastor' where user_id=:u"), dict(u=v['leader']))
    yield SimpleNamespace(factory=factory,v=v,conv=conv,person=person)
    get_settings.cache_clear()



def inbound(p, body):
    key = 'agenda-' + uuid4().hex
    mid = _seed_inbound_anchor(p.factory,igreja_id=p.v['t'],conversation_id=p.conv,provider_message_id=key,texto=body)
    return dataclasses.replace(_agent_outcome(p.conv,igreja_id=p.v['t'],provider_message_id=key,
        inbound_message_id=mid,instance='agenda-test',telefone='5500000000000'),texto=body)


def send(p, body, outcome=None, transport=None):
    class CommittedTransport(_ClassifiedEvolution):
        def send_text_classificado(self, instance, phone, body):
            with p.factory() as s:
                reply = s.scalars(select(Message).where(Message.conversation_id == p.conv,
                    Message.direcao == 'out', Message.texto == body).order_by(Message.criado_em.desc())).first()
                assert reply is not None  # A different connection sees reply/domain commit.
                raw = reply.agent_privilege_context or {}
                if raw.get('kind') == 'agenda_local' and raw.get('stage') == 'receipt':
                    from app.db.models import Event
                    row = s.get(Event, UUID(raw['event_id']))
                    assert (row is None) == (raw['action'] == 'delete')
                    if row:
                        assert row.data.isoformat() == raw['date']
            return super().send_text_classificado(instance, phone, body)
    transport = transport or CommittedTransport()
    outcome = outcome or inbound(p, body)
    worker.run_agent_for_message(p.factory, outcome, evolution_client=transport)
    with p.factory() as s:
        reply = s.scalars(select(Message).where(Message.conversation_id==p.conv,Message.direcao=='out')
            .order_by(Message.criado_em.desc(),Message.id.desc())).first()
    return outcome, reply, transport


CREATE = 'AGENDA criar Culto; 2026-12-01; 19:00'


def count(p):
    with p.factory() as s:
        return s.execute(text('select count(*) from events')).scalar_one()


@pytest.mark.parametrize('role', ['pastor', 'admin'])
def test_complete_crud_and_repeated_sim(agenda_turn, role):
    p = agenda_turn
    with p.factory.begin() as s:
        s.execute(text('update user_roles set papel=:r where user_id=:u'), dict(r=role,u=p.v['leader']))
    _, reply, transport = send(p, CREATE)
    assert 'SIM' in reply.texto and count(p) == 0 and len(transport.calls) == 1
    outcome, reply, transport = send(p, 'SIM')
    assert reply.agent_privilege_context['stage'] == 'receipt' and count(p) == 1
    event_id = reply.agent_privilege_context['event_id']
    assert event_id in reply.texto
    send(p, 'SIM', outcome=outcome)
    _, reply, _ = send(p, 'SIM')
    assert 'já registrada' in reply.texto and count(p) == 1
    send(p, f'AGENDA alterar {event_id}; 2026-12-02; 20:00')
    _, reply, _ = send(p, 'SIM')
    assert reply.agent_privilege_context['action'] == 'update'
    with p.factory() as s:
        row = s.execute(text('select data,hora from events')).one()
        assert row.data == dt.date(2026,12,2) and row.hora == '20:00'
    send(p, f'AGENDA cancelar {event_id}')
    _, reply, _ = send(p, 'SIM')
    assert reply.agent_privilege_context['action'] == 'delete' and count(p) == 0
    _, reply, _ = send(p, 'SIM')
    assert 'já registrada' in reply.texto and count(p) == 0


@pytest.mark.parametrize('role', ['operador', 'membro', 'lider_celula'])
def test_unauthorized_write(agenda_turn, role):
    p = agenda_turn
    with p.factory.begin() as s:
        s.execute(text('update user_roles set papel=:r where user_id=:u'), dict(r=role,u=p.v['leader']))
    _, reply, transport = send(p, CREATE)
    assert 'Sem permissão' in reply.texto and len(transport.calls) == 1 and count(p) == 0


@pytest.mark.parametrize('state', ['role', 'revoked', 'unlinked'])
def test_revalidate_actor_on_sim(agenda_turn, state):
    p = agenda_turn
    send(p, CREATE)
    with p.factory.begin() as s:
        if state == 'role': s.execute(text("update user_roles set papel='operador' where user_id=:u"),dict(u=p.v['leader']))
        if state == 'revoked': s.execute(text("update app_users set status='revogado' where id=:u"),dict(u=p.v['leader']))
        if state == 'unlinked': s.execute(text('update app_users set pessoa_id=null where id=:u'),dict(u=p.v['leader']))
    _, reply, _ = send(p, 'SIM')
    assert 'Sem permissão' in reply.texto and count(p) == 0


@pytest.mark.parametrize('answer', ['NÃO', 'SIM!', 'confirmo'])
def test_only_literal_sim_writes(agenda_turn, answer):
    p = agenda_turn
    send(p, CREATE)
    _, reply, transport = send(p, answer)
    assert len(transport.calls) == 1 and count(p) == 0
    assert 'cancelada' in reply.texto if answer == 'NÃO' else 'somente SIM' in reply.texto


@pytest.mark.parametrize('fence', ['release', 'church', 'privilege'])
def test_disabled_never_executes_domain(agenda_turn, monkeypatch, fence):
    from app.agenda_whatsapp import policy
    from app.services import whatsapp_privilege
    from app.agenda_whatsapp import service
    from app.services.llm import LLMClient, LLMResult, LLMUsage
    p = agenda_turn
    if fence == 'release': monkeypatch.setattr(policy,'AGENDA_WRITE_WHATSAPP_APPROVED_RELEASE_ID',None)
    if fence == 'church': monkeypatch.setenv('AGENDA_WRITE_WHATSAPP_ENABLED_IGREJA_IDS','')
    if fence == 'privilege': monkeypatch.setattr(whatsapp_privilege,'PRIVILEGE_APPROVED_RELEASE_ID',None)
    def forbidden(*a, **kw): raise AssertionError('disabled domain')
    monkeypatch.setattr(service,'actor',forbidden)
    monkeypatch.setattr(LLMClient,'complete',lambda *a,**kw: LLMResult('Recurso indisponível.',LLMUsage('synthetic',0,0,0)))
    _, reply, _ = send(p, CREATE)
    assert count(p) == 0 and (reply.agent_privilege_context or {}).get('kind') != 'agenda_local'


def test_receipt_retry_does_not_duplicate(agenda_turn, send_release_login):
    p = agenda_turn
    send(p, CREATE)
    outcome = inbound(p, 'SIM')
    with pytest.raises(worker.AgentReplyRetryable):
        send(p, 'SIM', outcome=outcome, transport=_ClassifiedEvolution('falhou_retentavel'))
    assert count(p) == 1
    _, reply, transport = send(p, 'SIM', outcome=outcome)
    assert reply.agent_privilege_context['stage'] == 'receipt' and len(transport.calls) == 1 and count(p) == 1


@pytest.mark.parametrize('state', ['changed', 'foreign', 'google', 'recurrence', 'notification'])
def test_changed_or_unsupported_target_refused(agenda_turn, state):
    p = agenda_turn
    send(p, CREATE); _, receipt, _ = send(p, 'SIM')
    eid = receipt.agent_privilege_context['event_id']
    if state == 'changed': send(p, f'AGENDA alterar {eid}; 2026-12-02; 20:00')
    with p.factory.begin() as s:
        if state == 'changed': s.execute(text("update events set hora='21:00' where id=:id"),dict(id=eid))
        if state == 'foreign': s.execute(text('update events set igreja_id=:t where id=:id'),dict(t=p.v['other'],id=eid))
        if state == 'google': s.execute(text("update events set google_event_id='synthetic' where id=:id"),dict(id=eid))
        if state == 'recurrence': s.execute(text("update events set recorrencia='semanal',dia_semana=2 where id=:id"),dict(id=eid))
        if state == 'notification': s.execute(text("update events set notificar_em=now()+interval '1 day' where id=:id"),dict(id=eid))
    _, reply, _ = send(p, 'SIM' if state == 'changed' else f'AGENDA cancelar {eid}')
    assert reply.agent_privilege_context['stage'] != 'proposal' and count(p) == 1
    assert reply.agent_privilege_context['stage'] != 'receipt'


@pytest.mark.parametrize('state', ['expired','undelivered'])
def test_expired_or_undelivered_proposal(agenda_turn, monkeypatch, state):
    from app.services.llm import LLMClient, LLMResult, LLMUsage
    p = agenda_turn
    _, reply, _ = send(p, CREATE)
    with p.factory.begin() as s:
        row = s.get(Message, reply.id)
        if state == 'expired': row.criado_em = dt.datetime.now(dt.UTC)-dt.timedelta(hours=1)
        else: row.agent_privilege_context = {k:v for k,v in row.agent_privilege_context.items() if k != 'delivered_at'}
    monkeypatch.setattr(LLMClient,'complete',lambda *a,**kw: LLMResult('Sem proposta válida.',LLMUsage('synthetic',0,0,0)))
    send(p, 'SIM')
    assert count(p) == 0


def test_read_uses_panel_visibility_and_safe_projection(agenda_turn):
    p = agenda_turn
    # Use a date inside the next 30 days, as the panel list filter does.
    day = dt.datetime.now(dt.UTC).date()+dt.timedelta(days=2)
    send(p, f'AGENDA criar Culto; {day}; 19:00'); send(p, 'SIM')
    with p.factory.begin() as s:
        s.execute(text("insert into events(igreja_id,titulo,data) values(:t,'Evento vizinho',:d)"),dict(t=p.v['other'],d=day))
        s.execute(text("update user_roles set papel='membro' where user_id=:u"),dict(u=p.v['leader']))
    _, reply, transport = send(p, 'AGENDA consultar')
    assert 'Culto' in reply.texto and 'vizinho' not in reply.texto and len(transport.calls) == 1
    assert reply.agent_privilege_context['stage'] == 'read'


@pytest.mark.parametrize('body', ['Quero parar de receber mensagens','Quero me matar','Quero falar com humano'])
def test_priority_paths(agenda_turn, body):
    p = agenda_turn
    send(p, CREATE)
    outcome, _, _ = send(p, body)
    assert count(p) == 0
    with p.factory() as s:
        assert not any((r.agent_privilege_context or {}).get('kind') == 'agenda_local'
            and (r.agent_privilege_context or {}).get('inbound_message_id') == str(outcome.inbound_message_id)
            for r in s.scalars(select(Message).where(Message.direcao=='out')))


def test_two_preexisting_sim_anchors_share_one_committed_operation(agenda_turn):
    # Both inbound timestamps precede the receipt; the consumed original proposal
    # must carry the same durable receipt, rather than execute a second writer.
    p = agenda_turn
    send(p, CREATE)
    first, second = inbound(p, 'SIM'), inbound(p, 'SIM')
    send(p, 'SIM', outcome=first)
    _, reply, _ = send(p, 'SIM', outcome=second)
    assert 'já registrada' in reply.texto and count(p) == 1


def test_domain_and_receipt_rollback_together(agenda_turn, monkeypatch):
    from app.agenda_whatsapp import catalog
    p = agenda_turn
    send(p, CREATE)
    original = catalog.execute
    def fail_after_domain_write(db, user, proposal):
        original(db, user, proposal)
        raise RuntimeError('synthetic failure before receipt')
    monkeypatch.setattr(catalog, 'execute', fail_after_domain_write)
    with pytest.raises(RuntimeError, match='synthetic failure'):
        send(p, 'SIM')
    assert count(p) == 0
    with p.factory() as s:
        assert not any((m.agent_privilege_context or {}).get('stage') == 'receipt'
            for m in s.scalars(select(Message).where(Message.direcao == 'out')))


@pytest.mark.parametrize('state', ['optout','consent','handoff','inactive','global'])
def test_contact_gate_suppresses_before_response(agenda_turn, monkeypatch, state):
    from app.agenda_whatsapp.turn import run_agenda_turn
    p = agenda_turn
    with p.factory.begin() as s:
        if state == 'optout': s.execute(text('update pessoas set optout=true where id=:p'),dict(p=p.person))
        if state == 'consent': s.execute(text('delete from consent_records'))
        if state == 'handoff': s.execute(text("update conversations set estado='humano'"))
        if state == 'inactive': s.query(AgentConfig).update({AgentConfig.ativo: False})
    if state == 'global':
        monkeypatch.setenv('ALLOW_REAL_SENDS','false'); get_settings.cache_clear()
    transport = _ClassifiedEvolution()
    assert run_agenda_turn(p.factory, p.factory, inbound(p, CREATE), igreja_id=p.v['t'],
        uses_dedicated_agent_session=False, ownership_guard=None, evolution_client=transport) is None
    assert not transport.calls and count(p) == 0


@pytest.mark.parametrize('state', ['role','event','release'])
def test_proposal_revalidated_before_transport(agenda_turn, monkeypatch, state):
    from app.agenda_whatsapp.turn import reply_still_authorized
    from app.agenda_whatsapp import policy
    from app.db.models import Conversation
    from tests.test_uv_turmas_pg import scoped
    p = agenda_turn
    send(p, CREATE); _, receipt, _ = send(p, 'SIM')
    eid = receipt.agent_privilege_context['event_id']
    _, proposal, _ = send(p, f'AGENDA alterar {eid}; 2026-12-02; 20:00')
    with p.factory.begin() as s:
        if state == 'role': s.execute(text("update user_roles set papel='operador' where user_id=:u"),dict(u=p.v['leader']))
        if state == 'event': s.execute(text("update events set hora='21:00' where id=:id"),dict(id=eid))
    if state == 'release': monkeypatch.setattr(policy,'AGENDA_WRITE_WHATSAPP_APPROVED_RELEASE_ID',None)
    with scoped(p.factory.kw['bind'],p.v['t']) as s:
        assert not reply_still_authorized(s,s.get(Message,proposal.id),conversation=s.get(Conversation,p.conv),
            recipient_phone='5500000000000',instance='agenda-test')


def test_drafts_are_not_exposed_without_web_proof(agenda_turn):
    p = agenda_turn
    day = dt.datetime.now(dt.UTC).date()+dt.timedelta(days=2)
    with p.factory.begin() as s:
        s.execute(text("insert into events(igreja_id,titulo,data,status) values(:t,'Culto',:d,'a_confirmar')"),dict(t=p.v['t'],d=day))
    _, reply, _ = send(p, 'AGENDA consultar')
    assert 'Nenhum evento' in reply.texto and 'Culto' not in reply.texto


def test_concurrent_sim_turns_never_duplicate(agenda_turn):
    from concurrent.futures import ThreadPoolExecutor
    p = agenda_turn
    send(p, CREATE)
    anchors = [inbound(p, 'SIM'), inbound(p, 'SIM')]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(send,p,'SIM',outcome=o) for o in anchors]
        for future in futures:
            future.result(timeout=30)
    assert count(p) == 1


@pytest.mark.parametrize('field', ['actor_id', 'proposal'])
@pytest.mark.parametrize('answer', ['SIM', 'confirmo'])
def test_malformed_proposal_is_safe(agenda_turn, field, answer):
    p = agenda_turn
    _, proposal, _ = send(p, CREATE)
    with p.factory.begin() as s:
        row = s.get(Message, proposal.id)
        row.agent_privilege_context = {k:v for k,v in row.agent_privilege_context.items() if k != field}
    _, reply, transport = send(p, answer)
    assert 'inválida' in reply.texto and len(transport.calls) == 1 and count(p) == 0


@pytest.mark.parametrize('legacy_payload', [False, True])
def test_title_is_persisted_canonically(agenda_turn, legacy_payload):
    p = agenda_turn
    _, proposal, _ = send(p, 'AGENDA criar cUlTo; 2026-12-01; 19:00')
    assert proposal.agent_privilege_context['proposal']['payload']['titulo'] == 'Culto'
    if legacy_payload:
        with p.factory.begin() as s:
            row = s.get(Message, proposal.id)
            raw = dict(row.agent_privilege_context)
            raw['proposal'] = dict(raw['proposal'], payload=dict(raw['proposal']['payload'], titulo='cUlTo'))
            row.agent_privilege_context = raw
    send(p, 'SIM')
    with p.factory() as s:
        assert s.execute(text('select titulo from events')).scalar_one() == 'Culto'


@pytest.mark.parametrize('command', ['alterar', 'cancelar'])
def test_foreign_event_id_cannot_be_written(agenda_turn, command):
    p = agenda_turn
    eid = uuid4()
    with p.factory.begin() as s:
        s.execute(text("insert into events(id,igreja_id,titulo,data,hora) values(:id,:t,'Culto','2026-12-01','19:00')"),
            dict(id=eid, t=p.v['other']))
    body = f'AGENDA {command} {eid}' + ('; 2026-12-02; 20:00' if command == 'alterar' else '')
    _, reply, _ = send(p, body)
    assert reply.agent_privilege_context['stage'] == 'denied'
    with p.factory() as s:
        assert s.execute(text('select igreja_id,data,hora from events where id=:id'), dict(id=eid)).one() == (
            p.v['other'], dt.date(2026,12,1), '19:00')


@pytest.mark.parametrize('state', ['event', 'role'])
def test_read_delivery_stable_but_revalidates_roles(agenda_turn, state):
    from app.agenda_whatsapp.turn import reply_still_authorized
    from app.db.models import Conversation
    from tests.test_uv_turmas_pg import scoped
    p = agenda_turn
    _, reply, _ = send(p, 'AGENDA consultar')
    with p.factory.begin() as s:
        if state == 'event':
            s.execute(text("insert into events(igreja_id,titulo,data) values(:t,'Culto',current_date)"), dict(t=p.v['t']))
        else:
            s.execute(text("update user_roles set papel='membro' where user_id=:u"), dict(u=p.v['leader']))
    with scoped(p.factory.kw['bind'], p.v['t']) as s:
        allowed = reply_still_authorized(s, s.get(Message,reply.id), conversation=s.get(Conversation,p.conv),
            recipient_phone='5500000000000', instance='agenda-test')
    assert allowed == (state == 'event')


@pytest.mark.parametrize('body,kind', [('ENVIAR','enviar'), ('CD','cd'), ('UV','uv'),
    ('quero iniciar pedido de oração','prayer'),
    ('QUERO SOLICITAR EXCLUSAO DO MEU CONTEUDO PRIVADO','private_erasure'),
    ('retomar conversa','clarify')])
def test_other_flows_route_with_pending_agenda(agenda_turn, monkeypatch, body, kind):
    from app.enviar_whatsapp import policy as enviar
    from app.cd_whatsapp import policy as cd
    from app.uv_whatsapp import policy as uv
    from app.prayer import policy as prayer
    from app.services import private_erasure_requests as erasure, private_resume
    from app.services.llm import LLMClient, TypedChoiceResult, TypedLLMResult, LLMUsage
    from app.agent import runtime
    p = agenda_turn
    for module, release, allowlist in [
        (enviar, 'ENVIAR_WHATSAPP_APPROVED_RELEASE_ID', 'ENVIAR_WHATSAPP_ENABLED_IGREJA_IDS'),
        (cd, 'CD_WHATSAPP_APPROVED_RELEASE_ID', 'CD_WHATSAPP_ENABLED_IGREJA_IDS'),
        (uv, 'UV_WHATSAPP_APPROVED_RELEASE_ID', 'UV_WHATSAPP_ENABLED_IGREJA_IDS'),
        (prayer, 'PRAYER_REQUEST_APPROVED_RELEASE_ID', 'PRAYER_REQUEST_ENABLED_IGREJA_IDS')]:
        monkeypatch.setattr(module, release, 'synthetic')
        monkeypatch.setenv(allowlist, str(p.v['t']))
    monkeypatch.setattr(erasure, 'APPROVED_RELEASE_ID', 'synthetic')
    monkeypatch.setattr(erasure, 'APPROVED_IGREJA_IDS', frozenset({str(p.v['t'])}))
    with p.factory.begin() as s:
        s.execute(text('insert into private_erasure_request_settings(igreja_id,enabled) values(:t,true)'), dict(t=p.v['t']))
    with p.factory.begin() as s:
        s.execute(text("update app_users set clerk_user_id='agenda-synthetic' where id=:u"), dict(u=p.v['leader']))
    usage = LLMUsage('synthetic',0,0,0)
    monkeypatch.setattr(LLMClient, 'generate_typed', lambda *a, **kw: TypedChoiceResult('nenhuma', usage))
    monkeypatch.setattr(LLMClient, 'complete_typed', lambda *a, **kw: TypedLLMResult(False, 'Resposta sintética de retomada.', usage))
    monkeypatch.setattr(runtime, 'decrypt_secret', lambda _: 'synthetic-key')
    resume_calls = []
    original_load = private_resume.load
    def load(db, context):
        resume_calls.append(context.inbound_message_id)
        return original_load(db, context)
    monkeypatch.setattr(private_resume, 'load', load)
    send(p, CREATE)
    outcome, reply, transport = send(p, body)
    assert len(transport.calls) == 1 and count(p) == 0
    assert reply.agent_privilege_context['kind'] == kind
    if body == 'retomar conversa':
        assert resume_calls == [outcome.inbound_message_id]
        assert reply.texto == 'Resposta sintética de retomada.'


@pytest.mark.parametrize('read_enabled', [True, False])
@pytest.mark.parametrize('write_enabled', [True, False])
@pytest.mark.parametrize('panel_user', [True, False])
def test_bare_agenda_preserves_existing_query(agenda_turn, monkeypatch, read_enabled, write_enabled, panel_user):
    from app.agenda_whatsapp import policy
    from app.services import whatsapp_agenda
    from app.services.llm import LLMClient, TypedChoiceResult, TypedLLMResult, LLMResult, LLMUsage
    from app.agent import runtime
    p = agenda_turn
    if not write_enabled:
        monkeypatch.setattr(policy, 'AGENDA_WRITE_WHATSAPP_APPROVED_RELEASE_ID', None)
    monkeypatch.setattr(whatsapp_agenda, 'AGENDA_WHATSAPP_APPROVED_RELEASE_ID', 'synthetic' if read_enabled else None)
    monkeypatch.setenv('AGENDA_WHATSAPP_ENABLED_IGREJA_IDS', str(p.v['t']))
    if not panel_user:
        with p.factory.begin() as s:
            s.execute(text('update app_users set pessoa_id=null where id=:u'), dict(u=p.v['leader']))
    usage = LLMUsage('synthetic',0,0,0)
    monkeypatch.setattr(LLMClient, 'generate_typed', lambda *a, **kw: TypedChoiceResult('nenhuma', usage))
    monkeypatch.setattr(LLMClient, 'complete_typed', lambda *a, **kw: TypedLLMResult(False, 'Consulta anterior.', usage))
    monkeypatch.setattr(LLMClient, 'complete', lambda *a, **kw: LLMResult('Consulta anterior.', usage))
    monkeypatch.setattr(runtime, 'decrypt_secret', lambda _: 'synthetic-key')
    _, reply, transport = send(p, 'AGENDA')
    assert len(transport.calls) == 1
    assert (reply.agent_privilege_context or {}).get('kind') != 'agenda_local'
    assert 'Sem permissão' not in reply.texto
