"""Human decisions on the real migration chain in disposable PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.db.models import AppUser, Celula, CelulaSolicitacao, Igreja, Pessoa, UserRole
from app.db.session import get_db
from app.db.tenant_session import mark_tenant_scoped
from app.deps import CurrentUser, get_current_user
from tests.conftest_rls import rls_database_url  # noqa: F401
from tests.test_whatsapp_integrated_pg import migrated_factory  # noqa: F401
pytestmark = pytest.mark.rls_integration

@pytest.fixture
def sample(migrated_factory):
    v={k:uuid4() for k in ('t','other','p','foreign','actor_p','u','request','cell')}
    with migrated_factory.begin() as s:
        s.add_all([Igreja(id=v['t'],nome='Igreja sintética'),Igreja(id=v['other'],nome='Outra sintética')]); s.flush()
        for key,tenant in [('p','t'),('actor_p','t'),('foreign','other')]:
            s.add(Pessoa(id=v[key],igreja_id=v[tenant],nome='Pessoa sintética',telefone=str(v[key]),apto_lider=key=='p'))
        s.flush()
        s.add(AppUser(id=v['u'],igreja_id=v['t'],pessoa_id=v['actor_p'],nome='Coordenação sintética',email=f"{v['u']}@example.test",status='ativo')); s.flush()
        s.add(UserRole(igreja_id=v['t'],user_id=v['u'],papel='pastor'))
    v['factory']=migrated_factory
    return v

def actor(v):
    return CurrentUser(app_user_id=str(v['u']),igreja_id=str(v['t']),clerk_user_id='synthetic',nome='Sintético',email='synthetic@example.test',roles=frozenset({'pastor'}))

def scoped(v,tenant=None):
    s=v['factory'](); mark_tenant_scoped(s,tenant or v['t'],source='enviar_test'); return s

def command(**kw):
    from app.routers.enviar import AvaliacaoInput
    return AvaliacaoInput(**(dict(id=uuid4(),decisao='apto',motivo='Histórico conferido',origem='legado')|kw))

def decide(s,v,payload=None,who=None,person=None):
    from app.services.enviar_avaliacoes import registrar_avaliacao
    return registrar_avaliacao(s,who or actor(v),person or v['p'],payload or command())

def denied(action,code):
    with pytest.raises(HTTPException) as e: action()
    assert e.value.status_code==code

def test_legacy_without_backfill_and_atomic_decision(sample):
    from app.services.enviar_avaliacoes import historico_pessoa
    v=sample
    with scoped(v) as s:
        before=historico_pessoa(s,actor(v),v['p'])
        assert before['origem']=='legado' and before['avaliacoes']==[]
        assert before['pendencias']['aviso_legado']=='origem legada, comprovação pendente'
        row=decide(s,v)
        assert row.origem=='legado' and row.autor_id==v['u']
        assert row.evidencias['uv']=={'estado':'indisponivel_nesta_base','referencia':None}
        assert row.versao_regras=='enviar-v1-provisoria'
        s.commit()
        assert s.get(Pessoa,v['p']).apto_lider
        assert s.scalar(text('select count(*) from enviar_eventos where avaliacao_id=:id'),dict(id=row.id))==1
        decide(s,v,command(decisao='nao_apto',origem='avaliacao')); s.rollback()
        assert s.get(Pessoa,v['p']).apto_lider

def test_concurrency_idempotency_and_old_retry_never_restores_projection(sample):
    v=sample; payload=command()
    def run():
        with scoped(v) as s:
            row=decide(s,v,payload); s.commit(); return row.id
    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(lambda _:run(),range(2)))==[payload.id,payload.id]
    with scoped(v) as s:
        denied(lambda:decide(s,v,command(id=payload.id,motivo='Outro motivo')),409)
        assert s.scalar(text('select count(*) from enviar_avaliacoes'))==1
        assert s.scalar(text('select count(*) from enviar_eventos'))==1
        decide(s,v,command(decisao='nao_apto',origem='avaliacao')); s.commit()
        decide(s,v,payload); s.commit()
        assert not s.get(Pessoa,v['p']).apto_lider

@pytest.mark.parametrize('state,code',[('role',403),('self',403),('csim',422),('archived',422),('evidence',422),('not_legacy',422),('foreign',404),('revoked',403)])
def test_guards(sample,state,code):
    v=sample
    with v['factory'].begin() as s:
        if state=='self': s.get(AppUser,v['u']).pessoa_id=v['p']
        if state=='csim': s.get(Pessoa,v['p']).sem_interesse=True
        if state=='archived': s.execute(text('update pessoas set arquivada_em=now() where id=:p'),{'p':v['p']})
        if state=='not_legacy': s.get(Pessoa,v['p']).apto_lider=False
        if state=='revoked': s.get(AppUser,v['u']).status='revogado'
    with scoped(v) as s:
        denied(lambda:decide(s,v,command(origem='avaliacao') if state=='evidence' else None,
            who=replace(actor(v),roles=frozenset({'membro'})) if state=='role' else None,
            person=v['foreign'] if state=='foreign' else None),code)
        s.rollback()
        assert s.scalar(text('select count(*) from enviar_avaliacoes'))==0

def test_request_author_cannot_decide(sample):
    v=sample
    with v['factory'].begin() as s:
        s.add(Celula(id=v['cell'],igreja_id=v['t'],nome='Célula sintética',cobertura_espiritual='Teste',ativo=True)); s.flush()
        s.add(CelulaSolicitacao(id=v['request'],igreja_id=v['t'],celula_id=v['cell'],solicitante_id=v['actor_p'],tipo='multiplicacao',status='aguardando',payload_proposto={'novo_lider_id':str(v['p'])}))
    with scoped(v) as s:
        denied(lambda:decide(s,v,command(solicitacao_id=v['request'])),403)
        denied(lambda:decide(s,v,command(solicitacao_id=uuid4())),403)

def test_rls_immutable_events_and_composite_fks(sample):
    v=sample
    with scoped(v) as s: decide(s,v); s.commit()
    with scoped(v,v['other']) as s:
        assert s.scalar(text('select count(*) from enviar_avaliacoes'))==0
        assert s.scalar(text('select count(*) from enviar_eventos'))==0
    for table in ['enviar_avaliacoes','enviar_eventos']:
        for sql in [f'update {table} set igreja_id=igreja_id',f'delete from {table}']:
            with v['factory']() as s,pytest.raises(DBAPIError): s.execute(text(sql))
    with scoped(v) as s,pytest.raises(DBAPIError):
        s.execute(text("insert into enviar_avaliacoes(id,igreja_id,pessoa_id,decisao,origem,motivo,autor_id,evidencias,versao_regras) values(:id,:t,:foreign,'nao_apto','avaliacao','Motivo',:u,'{}','v1')"),{k:val for k,val in dict(v,id=uuid4()).items() if k!='factory'})

def test_http_patch_csim_and_existing_leader(sample,app):
    v=sample
    def db():
        with scoped(v) as s: yield s
    app.dependency_overrides[get_db]=db
    app.dependency_overrides[get_current_user]=lambda:replace(actor(v),roles=frozenset({'admin'}))
    with TestClient(app) as client:
        url=f"/enviar/pessoas/{v['p']}/avaliacoes"
        assert client.get(url).status_code==200
        assert client.post(url,json=command().model_dump(mode='json')).status_code==201
        assert client.patch(f"/contacts/{v['p']}",json={'aptoLider':False}).status_code==409
        assert client.patch(f"/contacts/{v['p']}",json={'semInteresse':True}).status_code==200
        assert client.patch(f"/contacts/{v['p']}",json={'semInteresse':True}).status_code==200
        with scoped(v) as s:
            assert not s.get(Pessoa,v['p']).apto_lider
            assert s.scalar(text("select count(*) from enviar_avaliacoes where origem='csim'"))==1
        assert client.patch(f"/contacts/{v['p']}",json={'semInteresse':False}).status_code==200
    with v['factory'].begin() as s: s.add(Celula(id=v['cell'],igreja_id=v['t'],nome='Célula existente',cobertura_espiritual='Teste',ativo=True,lider_id=v['p']))
    with TestClient(app) as client:
        assert client.patch(f"/contacts/{v['p']}",json={'semInteresse':True}).status_code==409
        assert client.post(url,json=command(decisao='nao_apto',origem='avaliacao').model_dump(mode='json')).status_code==201
    with scoped(v) as s:
        assert s.get(Celula,v['cell']).lider_id==v['p'] and s.get(Celula,v['cell']).ativo

def test_request_cannot_be_omitted_to_bypass_segregation(sample):
    v=sample
    with v['factory'].begin() as s:
        s.add(Celula(id=v['cell'],igreja_id=v['t'],nome='Célula sintética',cobertura_espiritual='Teste',ativo=True)); s.flush()
        s.add(CelulaSolicitacao(id=v['request'],igreja_id=v['t'],celula_id=v['cell'],solicitante_id=v['actor_p'],tipo='multiplicacao',status='aguardando',payload_proposto={'novo_lider_id':str(v['p'])}))
    with scoped(v) as s: denied(lambda:decide(s,v),403)


def test_http_forbidden_idor_and_input_validation(sample,app):
    v=sample
    def db():
        with scoped(v) as s: yield s
    app.dependency_overrides[get_db]=db
    who=actor(v)
    app.dependency_overrides[get_current_user]=lambda:who
    with TestClient(app) as c:
        url=f"/enviar/pessoas/{v['p']}/avaliacoes"
        for method in [c.get,lambda path:c.post(path,json=command().model_dump(mode='json'))]:
            assert method(f"/enviar/pessoas/{v['foreign']}/avaliacoes").status_code==404
        for bad in [dict(motivo='  '),dict(motivo='x'*301),dict(origem='csim'),dict(evidencias={'uv':'comprovada'})]:
            assert c.post(url,json=command().model_dump(mode='json')|bad).status_code==422
        who=replace(who,roles=frozenset({'membro'}))
        assert c.get(url).status_code==403
        assert c.post(url,json=command().model_dump(mode='json')).status_code==403


def test_rls_rejects_unpinned_and_direct_authenticated_sessions(sample):
    v=sample
    with scoped(v) as s: decide(s,v); s.commit()
    with v['factory']() as s:
        s.execute(text('set local role authenticated'))
        assert s.scalar(text('select count(*) from enviar_avaliacoes'))==0
    with v['factory']() as s:
        s.execute(text('set local session authorization authenticated'))
        s.execute(text("select set_config('app.tenant_igreja_id',:t,true)"),dict(t=str(v['t'])))
        assert s.scalar(text('select count(*) from enviar_avaliacoes'))==0
        assert s.scalar(text('select count(*) from enviar_eventos'))==0
    with scoped(v) as s:
        for table in ['enviar_avaliacoes','enviar_eventos']:
            assert not s.scalar(text("select has_table_privilege('authenticated',:tab,'DELETE')"),dict(tab=table))
            assert not s.scalar(text("select has_table_privilege('authenticated',:tab,'UPDATE')"),dict(tab=table))
        assert not s.scalar(text("select has_table_privilege('authenticated','enviar_eventos','INSERT')"))


def test_lock_revalidates_after_competing_negative_decision(sample):
    from threading import Event
    v=sample; started=Event()
    def waiting():
        with scoped(v) as s:
            started.set()
            denied(lambda:decide(s,v),422)
    with scoped(v) as s,ThreadPoolExecutor(1) as pool:
        decide(s,v,command(decisao='nao_apto',origem='avaliacao'))
        future=pool.submit(waiting)
        assert started.wait(3)
        s.commit()
        future.result(timeout=10)
    with scoped(v) as s:
        assert not s.get(Pessoa,v['p']).apto_lider
        assert s.scalar(text('select count(*) from enviar_avaliacoes'))==1


def test_waiting_decision_revalidates_authorization_after_person_lock(sample,monkeypatch):
    """A revoked coordinator cannot use authority cached before waiting for a lock."""
    from threading import Event
    from app.services import enviar_avaliacoes as service
    v=sample; reached_lock=Event(); real_load=service._pessoa
    def instrumented_load(*args,**kwargs):
        if kwargs.get('lock'): reached_lock.set()
        return real_load(*args,**kwargs)
    monkeypatch.setattr(service,'_pessoa',instrumented_load)
    def waiting():
        with scoped(v) as s: denied(lambda:decide(s,v),403)
    with scoped(v) as holder,ThreadPoolExecutor(1) as pool:
        holder.execute(text('select id from pessoas where id=:p for update'),dict(p=v['p']))
        future=pool.submit(waiting)
        try:
            assert reached_lock.wait(3)
            with v['factory'].begin() as admin:
                admin.execute(text("update app_users set status='revogado' where id=:u"),dict(u=v['u']))
        finally:
            holder.rollback()
        future.result(timeout=10)
    with scoped(v) as s: assert s.scalar(text('select count(*) from enviar_avaliacoes'))==0
