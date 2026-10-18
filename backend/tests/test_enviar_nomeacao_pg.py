"""Nomeação web sobre a cadeia real de migrations, com dados sintéticos."""
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.models import AppUser, Celula, CelulaSolicitacao, Pessoa, UserRole
from app.db.session import get_db
from app.deps import get_current_user
from tests.test_enviar_avaliacoes_pg import sample, actor, scoped, decide  # noqa: F401
from tests.conftest_rls import rls_database_url  # noqa: F401
from tests.test_whatsapp_integrated_pg import migrated_factory  # noqa: F401

pytestmark = pytest.mark.rls_integration

@pytest.fixture
def nomination(sample, app):
    v = sample
    v['leader'], v['candidate_user'] = uuid4(), uuid4()
    with v['factory'].begin() as s:
        s.add(Pessoa(id=v['leader'], igreja_id=v['t'], nome='Líder legado', telefone=str(v['leader']))); s.flush()
        s.add(Celula(id=v['cell'], igreja_id=v['t'], nome='Célula sintética', cobertura_espiritual='Teste', ativo=True, lider_id=v['leader']))
        s.add(AppUser(id=v['candidate_user'], igreja_id=v['t'], pessoa_id=v['p'], nome='Candidato', email=f"{v['candidate_user']}@example.test", status='ativo', clerk_user_id=str(v['candidate_user'])))
        s.get(AppUser,v['u']).clerk_user_id=str(v['u'])
        s.flush()
        s.add(UserRole(igreja_id=v['t'], user_id=v['candidate_user'], papel='pastor'))
    with scoped(v) as s:
        decide(s,v); s.commit()
    def db():
        with scoped(v) as s: yield s
    v['who'] = actor(v)
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda:v['who']
    with TestClient(app) as c:
        v['client'] = c
        yield v


def create(v):
    response=v['client'].post('/cell-requests',json=dict(celula_id=str(v['cell']),tipo='nomear_lider',payload_proposto={'novo_lider_id':str(v['p'])}))
    assert response.status_code==201,response.text
    return response.json()


def approve(v, row, **kw):
    return v['client'].post(f"/cell-requests/{row['id']}/approve",json=dict(confirmar_execucao=True,versao_proposta=row['versao_proposta'])|kw)


def decider(v):
    u,p=uuid4(),uuid4()
    with v['factory'].begin() as s:
        s.add(Pessoa(id=p,igreja_id=v['t'],nome='Decisor sintético',telefone=str(p))); s.flush()
        s.add(AppUser(id=u,igreja_id=v['t'],pessoa_id=p,nome='Decisor',email=f'{u}@example.test',status='ativo',clerk_user_id=str(u)));s.flush()
        s.add(UserRole(igreja_id=v['t'],user_id=u,papel='pastor'))
    v['who']=replace(actor(v),app_user_id=str(u),clerk_user_id=str(u))
    return u,p


def test_full_decision_confirmation_version_and_idempotency(nomination):
    v=nomination; row=create(v)
    assert approve(v,row).status_code==403  # author
    decider(v)
    assert approve(v,row,confirmar_execucao=False).status_code==422
    assert approve(v,row,versao_proposta=0).status_code==409
    response=approve(v,row)
    assert response.status_code==200,response.text
    assert approve(v,row).status_code==200
    with scoped(v) as s:
        assert s.get(Celula,v['cell']).lider_id==v['p']
        assert s.scalar(text("select count(*) from celula_solicitacao_evento where solicitacao_id=:id and acao='aprovada'"),dict(id=row['id']))==1


@pytest.mark.parametrize('state', ['candidate','unlinked','removed_role','revoked_actor','not_apt','csim','archived','revoked_evidence','other_leadership','unusable_access'])
def test_guards_leave_legacy_untouched(nomination,state):
    v=nomination;row=create(v);u,p=decider(v)
    with v['factory'].begin() as s:
        if state=='candidate':s.get(AppUser,u).pessoa_id=v['p']
        if state=='unlinked':s.get(AppUser,u).pessoa_id=None
        if state=='removed_role':s.execute(text('delete from user_roles where user_id=:u'),dict(u=u))
        if state=='revoked_actor':s.get(AppUser,u).status='revogado'
        if state=='not_apt':s.get(Pessoa,v['p']).apto_lider=False
        if state=='csim':s.get(Pessoa,v['p']).sem_interesse=True
        if state=='archived':s.execute(text('update pessoas set arquivada_em=now() where id=:p'),dict(p=v['p']))
        if state=='other_leadership':s.add(Celula(igreja_id=v['t'],nome='Outra',cobertura_espiritual='Teste',ativo=True,lider_id=v['p']))
        if state=='unusable_access':s.get(AppUser,v['candidate_user']).status='revogado'
    if state=='revoked_evidence':
        from tests.test_enviar_avaliacoes_pg import command
        with scoped(v) as s:decide(s,v,command(decisao='nao_apto',origem='avaliacao'),who=v['who']);s.commit()
    response=approve(v,row)
    assert response.status_code in (403,409,422),response.text
    with scoped(v) as s:
        assert s.get(Celula,v['cell']).lider_id==v['leader']
        assert s.get(Celula,v['cell']).ativo
        assert s.get(CelulaSolicitacao,row['id']).status=='aguardando'


def test_direct_upsert_cannot_replace_legacy_leader(nomination):
    v=nomination
    response=v['client'].post('/cells',json=dict(id=str(v['cell']),nome='Célula sintética',coberturaEspiritual='Teste',liderId=str(v['p'])))
    assert response.status_code==409,response.text
    with scoped(v) as s: assert s.get(Celula,v['cell']).lider_id==v['leader']


def test_adjust_resubmit_new_version_and_candidate_cannot_reject_or_adjust(nomination):
    v=nomination; row=create(v)
    v['who']=replace(actor(v),app_user_id=str(v['candidate_user']))
    for action in ('reject','request-adjustment'):
        response=v['client'].post(f"/cell-requests/{row['id']}/{action}",json={'observacao_central':'Revisar'})
        assert response.status_code==403,response.text
    decider(v)
    assert v['client'].post(f"/cell-requests/{row['id']}/request-adjustment",json={'observacao_central':'Conferir proposta'}).status_code==200
    v['who']=actor(v)
    response=v['client'].put(f"/cell-requests/{row['id']}/resubmit",json={'payload_proposto':row['payload_proposto']})
    assert response.status_code==200,response.text
    updated=response.json()
    assert updated['versao_proposta']==row['versao_proposta']+1
    decider(v)
    assert approve(v,row).status_code==409
    assert approve(v,updated).status_code==200


def test_idor_cell_candidate_request_and_rls(nomination):
    v=nomination
    bad=v['client'].post('/cell-requests',json=dict(celula_id=str(v['cell']),tipo='nomear_lider',payload_proposto={'novo_lider_id':str(v['foreign'])}))
    assert bad.status_code==422,bad.text
    row=create(v)
    v['who']=replace(actor(v),igreja_id=str(v['other']))
    assert approve(v,row).status_code==404
    assert v['client'].get(f"/cell-requests/{row['id']}").status_code==404
    v['who']=actor(v)
    with scoped(v,v['other']) as s:
        assert s.get(CelulaSolicitacao,row['id']) is None


def test_failure_after_leadership_rolls_back_effects_and_audit(nomination,monkeypatch):
    from app.services import cell_requests_service as service
    v=nomination;row=create(v);decider(v)
    def failure(*a,**kw):raise RuntimeError('synthetic audit failure')
    monkeypatch.setattr(service,'_append_event',failure)
    with pytest.raises(RuntimeError,match='synthetic audit failure'): approve(v,row)
    with scoped(v) as s:
        assert s.get(Celula,v['cell']).lider_id==v['leader']
        assert s.get(CelulaSolicitacao,row['id']).status=='aguardando'
        assert s.scalar(text("select count(*) from user_roles where user_id=:u and papel='lider_celula'"),dict(u=v['candidate_user']))==0
        assert s.scalar(text("select count(*) from celula_solicitacao_evento where solicitacao_id=:id"),dict(id=row['id']))==1


def test_concurrent_requests_for_same_cell_only_one_is_open(nomination):
    from concurrent.futures import ThreadPoolExecutor
    v=nomination
    def run(_):
        return v['client'].post('/cell-requests',json=dict(celula_id=str(v['cell']),tipo='nomear_lider',payload_proposto={'novo_lider_id':str(v['p'])})).status_code
    with ThreadPoolExecutor(2) as pool: assert sorted(pool.map(run,range(2)))==[201,409]


def test_two_cells_compete_for_same_person_only_one_appointment(nomination):
    from concurrent.futures import ThreadPoolExecutor
    v=nomination;row=create(v);second=uuid4()
    with v['factory'].begin() as s:
        s.add(Celula(id=second,igreja_id=v['t'],nome='Segunda sintética',cobertura_espiritual='Teste',ativo=True,lider_id=v['leader']))
    response=v['client'].post('/cell-requests',json=dict(celula_id=str(second),tipo='nomear_lider',payload_proposto={'novo_lider_id':str(v['p'])}))
    assert response.status_code==201,response.text
    decider(v)
    with ThreadPoolExecutor(2) as pool: codes=list(pool.map(lambda r:approve(v,r).status_code,[row,response.json()]))
    assert sorted(codes)==[200,409]
    with scoped(v) as s:
        assert s.scalar(text('select count(*) from celulas where lider_id=:p and ativo'),dict(p=v['p']))==1


def test_role_removed_during_candidate_lock_is_revalidated(nomination):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep
    from app.services.cell_requests_service import approve as service_approve
    from fastapi import HTTPException
    v=nomination;row=create(v);u,p=decider(v);loaded=Event();pid=[]
    def waiting():
        with scoped(v) as s:
            cached=s.get(AppUser,u)
            assert any(r.papel=='pastor' for r in cached.roles)
            req=s.get(CelulaSolicitacao,row['id']);cell=s.get(Celula,v['cell'])
            pid.append(s.scalar(text('select pg_backend_pid()')));loaded.set()
            with pytest.raises(HTTPException) as err:
                service_approve(s,solicitacao=req,cell=cell,actor_pessoa_id=p,approver_app_user_id=u,
                    idempotency_key=None,confirmar_execucao=True,versao_proposta=1)
            assert err.value.status_code==403
    with scoped(v) as holder,ThreadPoolExecutor(1) as pool:
        holder.execute(text('select id from pessoas where id=:p for update'),dict(p=v['p']))
        future=pool.submit(waiting)
        try:
            assert loaded.wait(3)
            with v['factory'].begin() as admin:
                deadline=monotonic()+5
                while not admin.scalar(text('select cardinality(pg_blocking_pids(:pid))>0'),dict(pid=pid[0])):
                    assert monotonic()<deadline
                    sleep(.02)
                admin.execute(text('delete from user_roles where user_id=:u'),dict(u=u))
        finally:holder.rollback()
        future.result(timeout=10)
    with scoped(v) as s:assert s.get(Celula,v['cell']).lider_id==v['leader']


def test_leadership_refreshes_cached_aptitude_after_lock(nomination):
    from fastapi import HTTPException
    from app.services.cell_leadership import _load_candidate_for_update
    v=nomination
    with scoped(v) as s:
        cached=s.get(Pessoa,v['p']);assert cached.apto_lider
        with v['factory'].begin() as other:other.get(Pessoa,v['p']).apto_lider=False
        with pytest.raises(HTTPException) as err:_load_candidate_for_update(s,igreja_id=v['t'],pessoa_id=v['p'])
        assert err.value.status_code==422
        assert not cached.apto_lider


def test_approved_tenant_deletion_removes_nomination_derivatives(nomination):
    from app.services.tenant_deletion import delete_tenant_locally,TenantDeletionActor
    v=nomination;row=create(v)
    with v['factory']() as s:
        delete_tenant_locally(s,v['t'],TenantDeletionActor(app_user_id=None,email='synthetic@example.test'));s.commit()
        assert s.get(CelulaSolicitacao,row['id']) is None
        assert s.scalar(text('select count(*) from celula_solicitacao_evento where solicitacao_id=:id'),dict(id=row['id']))==0


def test_crossed_candidates_and_approvers_share_ordered_access_locks(nomination,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.services import cell_requests_service as service
    from tests.test_enviar_avaliacoes_pg import command
    v=nomination;first=create(v)
    p2,u2,c2,l2=uuid4(),uuid4(),uuid4(),uuid4()
    with v['factory'].begin() as s:
        s.add_all([Pessoa(id=p2,igreja_id=v['t'],nome='Candidato B',telefone=str(p2),apto_lider=True),Pessoa(id=l2,igreja_id=v['t'],nome='Líder B',telefone=str(l2))]);s.flush()
        s.add(AppUser(id=u2,igreja_id=v['t'],pessoa_id=p2,nome='Candidato B',email=f'{u2}@example.test',status='ativo',clerk_user_id=str(u2)))
        s.add(Celula(id=c2,igreja_id=v['t'],lider_id=l2,nome='Célula B',cobertura_espiritual='Teste',ativo=True));s.flush()
        s.add(UserRole(igreja_id=v['t'],user_id=u2,papel='pastor'))
    with scoped(v) as s:decide(s,v,command(),person=p2);s.commit()
    response=v['client'].post('/cell-requests',json=dict(celula_id=str(c2),tipo='nomear_lider',payload_proposto={'novo_lider_id':str(p2)}))
    assert response.status_code==201,response.text
    second=response.json();barrier=Barrier(2);original=service._lock_leadership_identities
    def lock(*a,**kw):
        barrier.wait(timeout=10)
        return original(*a,**kw)
    monkeypatch.setattr(service,'_lock_leadership_identities',lock)
    def run(args):
        request_id,user,person=args
        with scoped(v) as s:
            req=s.get(CelulaSolicitacao,request_id)
            service.approve(s,solicitacao=req,cell=s.get(Celula,req.celula_id),actor_pessoa_id=person,
                approver_app_user_id=user,idempotency_key=None,confirmar_execucao=True,versao_proposta=1)
            return req.status
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(run,item) for item in [(first['id'],u2,p2),(second['id'],v['candidate_user'],v['p'])]]
        assert [f.result(timeout=20) for f in futures]==['aprovada','aprovada']


def test_effective_leader_can_request_but_not_decide(nomination):
    v=nomination;u=uuid4()
    with v['factory'].begin() as s:
        s.add(AppUser(id=u,igreja_id=v['t'],pessoa_id=v['leader'],nome='Líder',email=f'{u}@example.test',status='ativo',clerk_user_id=str(u)));s.flush()
        s.add(UserRole(igreja_id=v['t'],user_id=u,papel='lider_celula'))
    v['who']=replace(actor(v),app_user_id=str(u),roles=frozenset({'lider_celula'}))
    row=create(v)
    assert approve(v,row).status_code==403
    decider(v)
    assert approve(v,row).status_code==200


def test_creation_and_approval_use_same_participant_order(nomination,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.services import cell_requests_service as service
    from app.routers.cell_requests import create_cell_request,CreateCellRequest
    v=nomination;row=create(v);u,p=decider(v);cell2=uuid4()
    with v['factory'].begin() as s:s.add(Celula(id=cell2,igreja_id=v['t'],nome='Outro alvo',cobertura_espiritual='Teste',lider_id=v['leader'],ativo=True))
    original=service._lock_leadership_identities;barrier=Barrier(2)
    def lock(*a,**kw):
        barrier.wait(timeout=10)
        return original(*a,**kw)
    monkeypatch.setattr(service,'_lock_leadership_identities',lock)
    def creating():
        with scoped(v) as s:
            return create_cell_request(CreateCellRequest(celula_id=str(cell2),tipo='nomear_lider',payload_proposto={'novo_lider_id':str(v['p'])}),db=s,current_user=v['who']).status
    def approving():
        with scoped(v) as s:
            req=s.get(CelulaSolicitacao,row['id'])
            return service.approve(s,solicitacao=req,cell=s.get(Celula,v['cell']),actor_pessoa_id=p,
                approver_app_user_id=u,idempotency_key=None,confirmar_execucao=True,versao_proposta=1).status
    with ThreadPoolExecutor(2) as pool:
        a,b=pool.submit(creating),pool.submit(approving)
        assert a.result(timeout=20)=='aguardando'
        assert b.result(timeout=20)=='aprovada'


def test_latest_negative_evaluation_blocks_even_stale_true_projection(nomination):
    from tests.test_enviar_avaliacoes_pg import command
    v=nomination;row=create(v);decider(v)
    with scoped(v) as s:decide(s,v,command(decisao='nao_apto',origem='avaliacao'),who=v['who']);s.commit()
    with v['factory'].begin() as s:s.get(Pessoa,v['p']).apto_lider=True
    response=approve(v,row)
    assert response.status_code==409,response.text
    assert 'revisão pastoral' in response.json()['detail']
    with scoped(v) as s: assert s.get(Celula,v['cell']).lider_id==v['leader']


def test_no_evaluation_cannot_turn_legacy_flag_into_new_appointment(nomination):
    v=nomination;v['p']=uuid4();u=uuid4()
    with v['factory'].begin() as s:
        s.add(Pessoa(id=v['p'],igreja_id=v['t'],nome='Legado não avaliado',telefone=str(v['p']),apto_lider=True));s.flush()
        s.add(AppUser(id=u,igreja_id=v['t'],pessoa_id=v['p'],nome='Legado',email=f'{u}@example.test',status='ativo',clerk_user_id=str(u)))
    row=create(v);decider(v)
    assert approve(v,row).status_code==409


def test_foreign_cell_cannot_be_targeted_and_service_role_has_no_direct_write(nomination):
    v=nomination;foreign_cell=uuid4()
    with v['factory'].begin() as s:s.add(Celula(id=foreign_cell,igreja_id=v['other'],nome='Alvo externo',cobertura_espiritual='Teste',ativo=True))
    response=v['client'].post('/cell-requests',json=dict(celula_id=str(foreign_cell),tipo='nomear_lider',payload_proposto={'novo_lider_id':str(v['p'])}))
    assert response.status_code==404
    with scoped(v) as s:
        assert not s.scalar(text("select has_table_privilege('service_role','celula_solicitacao','INSERT')"))
        assert not s.scalar(text("select has_table_privilege('service_role','celula_solicitacao','UPDATE')"))


def test_negative_decision_opens_pastoral_review_without_removing_leadership(nomination):
    from app.services.enviar_avaliacoes import historico_pessoa
    from tests.test_enviar_avaliacoes_pg import command
    v=nomination;row=create(v);decider(v)
    assert approve(v,row).status_code==200
    with scoped(v) as s:
        decide(s,v,command(decisao='nao_apto',origem='avaliacao'),who=v['who']);s.commit()
        history=historico_pessoa(s,v['who'],v['p'])
        assert history['revisao_pastoral_pendente']
        assert s.get(Celula,v['cell']).lider_id==v['p'] and s.get(Celula,v['cell']).ativo


def test_linked_negative_evaluation_and_approval_do_not_deadlock(nomination,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic,sleep
    from app.services import enviar_avaliacoes as evaluations,cell_requests_service as requests
    from tests.test_enviar_avaliacoes_pg import command
    from fastapi import HTTPException
    v=nomination;row=create(v);u,p=decider(v)
    locked=Event();proceed=Event();approval_started=Event();pids=[]
    original=evaluations._pessoa
    def paused(*a,**kw):
        person=original(*a,**kw);locked.set();assert proceed.wait(10);return person
    monkeypatch.setattr(evaluations,'_pessoa',paused)
    def evaluate():
        with scoped(v) as s:
            decide(s,v,command(decisao='nao_apto',origem='avaliacao',solicitacao_id=row['id']),who=v['who']);s.commit()
    def approve_waiting():
        with scoped(v) as s:
            req=s.get(CelulaSolicitacao,row['id']);cell=s.get(Celula,v['cell'])
            pids.append(s.scalar(text('select pg_backend_pid()')));approval_started.set()
            with pytest.raises(HTTPException) as err:
                requests.approve(s,solicitacao=req,cell=cell,actor_pessoa_id=p,approver_app_user_id=u,
                    idempotency_key=None,confirmar_execucao=True,versao_proposta=1)
            assert err.value.status_code==409
    with ThreadPoolExecutor(2) as pool:
        evaluating=pool.submit(evaluate)
        assert locked.wait(5)
        approving=pool.submit(approve_waiting)
        try:
            assert approval_started.wait(5)
            with v['factory']() as monitor:
                deadline=monotonic()+5
                while not monitor.scalar(text('select cardinality(pg_blocking_pids(:pid))>0'),dict(pid=pids[0])):
                    assert monotonic()<deadline
                    sleep(.02)
        finally:proceed.set()
        evaluating.result(timeout=15);approving.result(timeout=15)
    with scoped(v) as s:assert s.get(Celula,v['cell']).lider_id==v['leader']


def test_legacy_null_access_status_keeps_nomination_workflow_usable(nomination):
    v=nomination
    with v['factory'].begin() as s:s.get(AppUser,v['u']).status=None
    row=create(v)
    u,p=decider(v)
    with v['factory'].begin() as s:s.get(AppUser,u).status=None
    adjustment=v['client'].post(f"/cell-requests/{row['id']}/request-adjustment",json={'observacao_central':'Revisar'})
    assert adjustment.status_code==200,adjustment.text
    v['who']=actor(v)
    resubmit=v['client'].put(f"/cell-requests/{row['id']}/resubmit",json={'payload_proposto':row['payload_proposto']})
    assert resubmit.status_code==200,resubmit.text
    v['who']=replace(actor(v),app_user_id=str(u),clerk_user_id=str(u))
    assert approve(v,resubmit.json()).status_code==200
