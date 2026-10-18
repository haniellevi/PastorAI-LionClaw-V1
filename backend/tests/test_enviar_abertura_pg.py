"""Abertura sem origem na cadeia real de migrations, dados sintéticos."""
from sqlalchemy import text
import pytest
from app.db.models import AppUser, Celula, CelulaSolicitacao, Pessoa
from tests.test_enviar_nomeacao_pg import nomination, decider, approve  # noqa: F401
from tests.test_enviar_avaliacoes_pg import sample, actor, scoped  # noqa: F401
from tests.test_whatsapp_integrated_pg import migrated_factory  # noqa: F401
from tests.conftest_rls import rls_database_url  # noqa: F401
pytestmark = pytest.mark.rls_integration


def create(v, **patch):
    response = v['client'].post('/cell-requests', json=dict(tipo='abrir_celula',
        payload_proposto=dict(nome='Nova sintética', cobertura_espiritual='Cobertura sintética',
            novo_lider_id=str(v['p'])) | patch))
    assert response.status_code == 201, response.text
    assert response.json()['celula_id'] is None
    return response.json()


def test_open_without_origin_atomic_idempotent_and_legacy_untouched(nomination):
    v = nomination; row = create(v)
    with scoped(v) as s: assert s.scalar(text('select count(*) from celulas')) == 1
    assert approve(v, row).status_code == 403
    decider(v)
    assert approve(v, row, confirmar_execucao=False).status_code == 422
    assert approve(v, row, versao_proposta=0).status_code == 409
    response = approve(v, row)
    assert response.status_code == 200, response.text
    assert approve(v, row).status_code == 200
    with scoped(v) as s:
        assert s.scalar(text('select count(*) from celulas')) == 2
        assert s.scalar(text('select count(*) from celulas where lider_id=:p and ativo'), dict(p=v['p'])) == 1
        assert s.get(Celula, v['cell']).lider_id == v['leader']
        assert s.scalar(text("select count(*) from celula_solicitacao_evento where solicitacao_id=:id and acao='aprovada'"),dict(id=row['id'])) == 1
        assert s.get(CelulaSolicitacao, row['id']).celula_id is None


def test_direct_creation_with_leader_refused(nomination):
    v = nomination
    response = v['client'].post('/cells', json=dict(nome='Contorno', coberturaEspiritual='Teste', liderId=str(v['p'])))
    assert response.status_code == 409, response.text
    with scoped(v) as s: assert s.scalar(text('select count(*) from celulas')) == 1


@pytest.mark.parametrize('state', ['candidate','unlinked','removed_role','revoked_actor','not_apt','csim','archived','other_leadership','unusable_access','no_evaluation','negative_evaluation'])
def test_opening_revalidates_and_keeps_legacy(nomination, state):
    from app.db.models import AppUser, Pessoa
    from tests.test_enviar_avaliacoes_pg import decide, command
    v=nomination
    if state=='no_evaluation':
        from uuid import uuid4
        v['p']=uuid4(); u=uuid4()
        with v['factory'].begin() as s:
            s.add(Pessoa(id=v['p'],igreja_id=v['t'],nome='Legado sem avaliação',telefone=str(v['p']),apto_lider=True));s.flush()
            s.add(AppUser(id=u,igreja_id=v['t'],pessoa_id=v['p'],nome='Candidato',email=f'{u}@example.test',status='ativo',clerk_user_id=str(u)))
    row=create(v); u,p=decider(v)
    with v['factory'].begin() as s:
        if state=='candidate': s.get(AppUser,u).pessoa_id=v['p']
        if state=='unlinked': s.get(AppUser,u).pessoa_id=None
        if state=='removed_role': s.execute(text('delete from user_roles where user_id=:u'),dict(u=u))
        if state=='revoked_actor': s.get(AppUser,u).status='revogado'
        if state=='not_apt': s.get(Pessoa,v['p']).apto_lider=False
        if state=='csim': s.get(Pessoa,v['p']).sem_interesse=True
        if state=='archived': s.execute(text('update pessoas set arquivada_em=now() where id=:p'),dict(p=v['p']))
        if state=='other_leadership': s.add(Celula(igreja_id=v['t'],nome='Outra',cobertura_espiritual='Teste',ativo=True,lider_id=v['p']))
        if state=='unusable_access': s.get(AppUser,v['candidate_user']).status='revogado'
    if state=='negative_evaluation':
        with scoped(v) as s: decide(s,v,command(decisao='nao_apto',origem='avaliacao'),who=v['who']);s.commit()
    response=approve(v,row)
    assert response.status_code in (403,409,422),response.text
    with scoped(v) as s:
        assert s.scalar(text("select count(*) from celulas where nome='Nova sintética'"))==0
        assert s.get(Celula,v['cell']).lider_id==v['leader']
        assert s.get(CelulaSolicitacao,row['id']).status=='aguardando'


def test_nomination_failure_rolls_back_cell_and_audit(nomination,monkeypatch):
    from app.services import cell_requests_service as service
    v=nomination;row=create(v);decider(v)
    real=service.set_cell_leadership
    def fail(*a,**kw):
        real(*a,**kw)
        a[0].flush()  # force cell + derived role to reach PostgreSQL before failure
        raise RuntimeError('synthetic nomination failure')
    monkeypatch.setattr(service,'set_cell_leadership',fail)
    with pytest.raises(RuntimeError,match='synthetic nomination failure'): approve(v,row)
    with scoped(v) as s:
        assert s.scalar(text('select count(*) from celulas'))==1
        assert s.get(CelulaSolicitacao,row['id']).status=='aguardando'
        assert s.scalar(text("select count(*) from celula_solicitacao_evento where solicitacao_id=:id"),dict(id=row['id']))==1
        assert s.scalar(text("select count(*) from user_roles where user_id=:u and papel='lider_celula'"),dict(u=v['candidate_user']))==0


def test_two_approvals_execute_once(nomination):
    from concurrent.futures import ThreadPoolExecutor
    v=nomination; row=create(v); decider(v)
    with ThreadPoolExecutor(2) as pool: codes=list(pool.map(lambda _:approve(v,row).status_code,range(2)))
    assert all(code in (200,409) for code in codes) and 200 in codes
    with scoped(v) as s:
        assert s.scalar(text('select count(*) from celulas'))==2
        assert s.scalar(text("select count(*) from celula_solicitacao_evento where solicitacao_id=:id and acao='aprovada'"),dict(id=row['id']))==1


def test_existing_name_rule_is_preserved_and_no_origin_constraint(nomination):
    from sqlalchemy.exc import IntegrityError
    v=nomination; row=create(v,nome='Célula sintética'); decider(v)
    # Existing cadastro has no active-name uniqueness rule. Preserve legacy names.
    assert approve(v,row).status_code==200
    with scoped(v) as s:
        assert s.scalar(text("select count(*) from celulas where nome='Célula sintética'"))==2
        with pytest.raises(IntegrityError):
            s.add(CelulaSolicitacao(igreja_id=v['t'],tipo='alterar_dia',payload_proposto={'dia_reuniao':'Segunda'}));s.flush()
        s.rollback()
    with scoped(v) as s:
        with pytest.raises(IntegrityError):
            s.add(CelulaSolicitacao(igreja_id=v['t'],celula_id=v['cell'],tipo='abrir_celula',candidato_id=v['p'],payload_proposto=row['payload_proposto']));s.flush()
        s.rollback()


def test_opening_idor_and_service_role(nomination):
    from dataclasses import replace
    v=nomination
    response=v['client'].post('/cell-requests',json={'tipo':'abrir_celula','payload_proposto':dict(nome='Externa',cobertura_espiritual='Teste',novo_lider_id=str(v['foreign']))})
    assert response.status_code==422,response.text
    row=create(v)
    v['who']=replace(actor(v),igreja_id=str(v['other']))
    assert approve(v,row).status_code==404
    assert v['client'].get(f"/cell-requests/{row['id']}").status_code==404
    with scoped(v,v['other']) as s: assert s.get(CelulaSolicitacao,row['id']) is None
    with scoped(v) as s:
        assert not s.scalar(text("select has_table_privilege('service_role','celula_solicitacao','INSERT')"))


def test_adjust_resubmit_and_effective_leader_requests(nomination):
    from dataclasses import replace
    from app.db.models import AppUser
    v=nomination
    with v['factory'].begin() as s:
        s.get(Celula,v['cell']).lider_id=v['actor_p']
        s.execute(text('delete from user_roles where user_id=:u'),dict(u=v['u']))
    v['who']=replace(actor(v),roles=frozenset({'lider_celula'}))
    row=create(v);decider(v)
    assert v['client'].post(f"/cell-requests/{row['id']}/request-adjustment",json={'observacao_central':'Conferir nome'}).status_code==200
    v['who']=replace(actor(v),roles=frozenset({'lider_celula'}))
    response=v['client'].put(f"/cell-requests/{row['id']}/resubmit",json={'payload_proposto':row['payload_proposto']|{'nome':'Revisada'}})
    assert response.status_code==200,response.text
    assert response.json()['versao_proposta']==2
    decider(v)
    assert approve(v,row).status_code==409
    assert approve(v,response.json()).status_code==200


def test_direct_creation_without_leader_remains_usable(nomination):
    v=nomination
    response=v['client'].post('/cells',json={'nome':'Sem líder','coberturaEspiritual':'Teste'})
    assert response.status_code==200,response.text
    assert response.json()['liderId'] is None


def test_opening_role_removed_during_lock_is_revalidated(nomination):
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
            req=s.get(CelulaSolicitacao,row['id']);cell=None
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



def test_duplicate_opening_retries_and_concurrent_creation_are_rejected(nomination):
    from concurrent.futures import ThreadPoolExecutor
    v=nomination
    body={'tipo':'abrir_celula','payload_proposto':dict(nome='Nova sintética',cobertura_espiritual='Teste',novo_lider_id=str(v['p']))}
    with ThreadPoolExecutor(2) as pool:
        responses=list(pool.map(lambda _:v['client'].post('/cell-requests',json=body),range(2)))
    assert sorted(r.status_code for r in responses)==[201,409]
    assert v['client'].post('/cell-requests',json=body).status_code==409
    row=next(r.json() for r in responses if r.status_code==201)
    assert v['client'].post(f"/cell-requests/{row['id']}/cancel").status_code==200
    assert v['client'].post('/cell-requests',json=body).status_code==201
    with scoped(v) as s:
        assert s.scalar(text("select count(*) from celula_solicitacao where tipo='abrir_celula' and status='aguardando'"))==1
        assert s.scalar(text('select count(*) from celulas'))==1


def test_resubmit_cannot_compete_with_open_request_for_candidate(nomination):
    from uuid import uuid4
    v=nomination; first=create(v); second_person=uuid4()
    with v['factory'].begin() as s:
        s.add(Pessoa(id=second_person,igreja_id=v['t'],nome='Outro candidato',telefone=str(second_person)))
    second=create(v,novo_lider_id=str(second_person))
    decider(v)
    assert v['client'].post(f"/cell-requests/{second['id']}/request-adjustment",json={'observacao_central':'Rever candidato'}).status_code==200
    v['who']=actor(v)
    response=v['client'].put(f"/cell-requests/{second['id']}/resubmit",json={'payload_proposto':first['payload_proposto']})
    assert response.status_code==409,response.text
    with scoped(v) as s:
        row=s.get(CelulaSolicitacao,second['id'])
        assert row.status=='ajuste_solicitado' and row.candidato_id==second_person and row.versao_proposta==1


@pytest.mark.parametrize('tipo', ['abrir_celula','nomear_lider'])
def test_resubmit_changes_typed_candidate_and_payload_atomically(nomination,tipo):
    from uuid import uuid4
    from tests.test_enviar_nomeacao_pg import create as create_nomination
    v=nomination; row=create(v) if tipo=='abrir_celula' else create_nomination(v)
    candidate=uuid4()
    with v['factory'].begin() as s:
        s.add(Pessoa(id=candidate,igreja_id=v['t'],nome='Candidato revisado',telefone=str(candidate)))
    decider(v)
    assert v['client'].post(f"/cell-requests/{row['id']}/request-adjustment",json={'observacao_central':'Rever candidato'}).status_code==200
    v['who']=actor(v)
    response=v['client'].put(f"/cell-requests/{row['id']}/resubmit",json={'payload_proposto':row['payload_proposto']|{'novo_lider_id':str(candidate)}})
    assert response.status_code==200,response.text
    assert response.json()['candidato_id']==str(candidate) and response.json()['versao_proposta']==2
    with scoped(v) as s:
        stored=s.get(CelulaSolicitacao,row['id'])
        assert stored.candidato_id==candidate and stored.payload_proposto['novo_lider_id']==str(candidate)
