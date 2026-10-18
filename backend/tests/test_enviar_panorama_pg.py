"""Leitura Enviar com escopo real, RLS e dados sintéticos."""
from dataclasses import replace
from uuid import uuid4
import pytest
from app.db.models import AppUser, Celula, CelulaMembro, Pessoa, UserRole
from tests.test_enviar_nomeacao_pg import nomination, create, decider, approve  # noqa: F401
from tests.test_enviar_avaliacoes_pg import sample, actor, scoped  # noqa: F401
from tests.test_whatsapp_integrated_pg import migrated_factory  # noqa: F401
from tests.conftest_rls import rls_database_url  # noqa: F401
pytestmark = pytest.mark.rls_integration


def test_coordinator_search_pagination_and_minimal_fields(nomination):
    v=nomination
    with v['factory'].begin() as s:s.get(Pessoa,v['p']).nome='Candidato da consulta'
    response=v['client'].get('/enviar/pessoas',params={'q':'Candidato da consulta','page_size':1})
    assert response.status_code==200,response.text
    data=response.json()
    assert len(data['items'])==1 and data['total']>=1
    item=data['items'][0]
    assert set(item)=={'id','nome','situacao','origem','pendencias','ultima_avaliacao','apto_lider'}
    assert set(item['ultima_avaliacao'])=={'id','decisao','criada_em','versao_regras'}
    assert item['origem']=='legado' and item['situacao']=='pendente'
    assert len(item['pendencias'])==3
    assert v['client'].get('/enviar/pessoas?q=inexistente').json()['total']==0
    assert v['client'].get('/enviar/pessoas?page_size=101').status_code==422
    assert v['client'].get('/enviar/pessoas?page=0').status_code==422
    assert v['client'].get('/enviar/pessoas?page=999').json()['items']==[]


def test_leader_scope_uses_canonical_membership_and_rejects_other_roles(nomination):
    from sqlalchemy import text
    v=nomination
    with v['factory'].begin() as s:
        s.get(Celula,v['cell']).lider_id=v['actor_p']
        s.add(CelulaMembro(igreja_id=v['t'],celula_id=v['cell'],pessoa_id=v['p'],ativo=True,papel='membro'))
        s.execute(text('delete from user_roles where user_id=:u'),dict(u=v['u']))
        s.add(UserRole(igreja_id=v['t'],user_id=v['u'],papel='lider_celula'))
    v['who']=replace(actor(v),roles=frozenset({'lider_celula'}))
    items=v['client'].get('/enviar/pessoas').json()['items']
    assert {i['id'] for i in items}=={str(v['p']),str(v['actor_p'])}
    assert v['client'].get('/enviar/pessoas',params={'q':'Líder legado'}).json()['total']==0
    with v['factory'].begin() as s:s.get(Celula,v['cell']).ativo=False
    assert {i['id'] for i in v['client'].get('/enviar/pessoas').json()['items']}=={str(v['actor_p'])}
    v['who']=replace(actor(v),roles=frozenset({'membro'}))
    assert v['client'].get('/enviar/pessoas').status_code==403
    assert v['client'].get('/enviar/historico').status_code==403


def test_history_scope_and_tenant_idor(nomination):
    from sqlalchemy import text
    v=nomination;row=create(v);decider_id,decider_person=decider(v)
    assert approve(v,row).status_code==200
    result=v['client'].get('/enviar/historico').json()
    assert result['total']==1 and result['items'][0]['tipo']=='nomear_lider'
    assert set(result['items'][0])=={'id','tipo','status','criada_em','decidido_em','celula_id'}
    v['who']=replace(actor(v),igreja_id=str(v['other']))
    assert v['client'].get('/enviar/pessoas').status_code==403  # access belongs to another tenant
    assert v['client'].get('/enviar/historico').status_code==403
    v['who']=replace(actor(v),app_user_id=str(decider_id),roles=frozenset({'lider_celula'}))
    with v['factory'].begin() as s:
        s.execute(text('delete from user_roles where user_id=:u'),dict(u=decider_id))
        s.add(UserRole(igreja_id=v['t'],user_id=decider_id,papel='lider_celula'))
    assert v['client'].get('/enviar/historico').json()['total']==0
    with v['factory'].begin() as s:s.get(Celula,v['cell']).lider_id=decider_person
    assert v['client'].get('/enviar/historico').json()['total']==0  # leading cell cannot expose another author's request
    with v['factory'].begin() as s:s.get(AppUser,decider_id).status='revogado'
    assert v['client'].get('/enviar/pessoas').status_code==403



def test_groups_and_literal_search_do_not_promote_legacy(nomination):
    from tests.test_enviar_avaliacoes_pg import decide, command
    v=nomination
    aptos=v['client'].get('/enviar/pessoas?grupo=aptos').json()
    assert {p['id'] for p in aptos['items']}=={str(v['p'])}
    assert aptos['items'][0]['situacao']=='pendente'  # human legacy decision != formation proof
    assert str(v['p']) not in {p['id'] for p in v['client'].get('/enviar/pessoas?grupo=pendentes').json()['items']}
    assert v['client'].get('/enviar/pessoas?q=%25').json()['total']==0
    with scoped(v) as s:decide(s,v,command(decisao='nao_apto',origem='avaliacao'));s.commit()
    assert v['client'].get('/enviar/pessoas?grupo=aptos').json()['total']==0
    assert str(v['p']) in {p['id'] for p in v['client'].get('/enviar/pessoas?grupo=pendentes').json()['items']}


def test_other_church_data_never_enters_coordinator_lists(nomination):
    from app.db.models import CelulaSolicitacao
    v=nomination
    with v['factory'].begin() as s:
        s.get(Pessoa,v['foreign']).nome='Pessoa externa exclusiva'
        s.add(CelulaSolicitacao(igreja_id=v['other'],tipo='abrir_celula',candidato_id=v['foreign'],
            payload_proposto=dict(novo_lider_id=str(v['foreign']),nome='Externa',cobertura_espiritual='Teste')))
    assert v['client'].get('/enviar/pessoas?q=externa').json()['total']==0
    assert v['client'].get('/enviar/historico').json()['total']==0


def test_history_opening_multiplication_search_and_pagination(nomination):
    from tests.test_enviar_abertura_pg import create as opening
    from tests.test_enviar_snapshot_pg import multiplication_request
    v=nomination;opening(v);multiplication_request(v)
    page=v['client'].get('/enviar/historico?page_size=1').json()
    assert page['total']==2 and len(page['items'])==1
    second=v['client'].get('/enviar/historico?page_size=1&page=2').json()
    assert second['items'][0]['id']!=page['items'][0]['id']
    assert v['client'].get('/enviar/historico?q=multiplicacao').json()['total']==1
    assert v['client'].get('/enviar/historico',params={'q':'Multiplicação'}).json()['total']==1
    assert v['client'].get('/enviar/historico?q=Abertura').json()['total']==1
    assert v['client'].get('/enviar/historico?q=Célula').json()['total']==1
    assert v['client'].get('/enviar/historico?q=inexistente').json()['items']==[]


def test_leader_retains_own_request_history_after_leadership_changes(nomination):
    from sqlalchemy import text
    v=nomination;create(v)
    with v['factory'].begin() as s:
        s.execute(text('delete from user_roles where user_id=:u'),dict(u=v['u']))
        s.add(UserRole(igreja_id=v['t'],user_id=v['u'],papel='lider_celula'))
    v['who']=replace(actor(v),roles=frozenset({'lider_celula'}))
    assert v['client'].get('/enviar/historico').json()['total']==1
