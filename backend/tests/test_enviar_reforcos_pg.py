"""Regressões P2 com PostgreSQL e dados sintéticos."""
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from app.db.models import AppUser, Celula, CelulaSolicitacao, Pessoa
from app.domain.enviar import ResultadoEnviar, SituacaoEnviar
from app.services import enviar_avaliacoes
from app.services.cell_multiplication_service import execute_multiplication
from tests.test_enviar_nomeacao_pg import nomination, create, decider, approve  # noqa: F401
from tests.test_enviar_abertura_pg import create as opening
from tests.test_enviar_avaliacoes_pg import sample, actor, scoped, decide, command  # noqa: F401
from tests.test_whatsapp_integrated_pg import migrated_factory  # noqa: F401
from tests.conftest_rls import rls_database_url  # noqa: F401
pytestmark = pytest.mark.rls_integration


def multiply(s, v):
    payload=dict(novo_lider_id=str(v['p']), membros_transferidos_ids=[], nome_nova_celula='Multiplicada')
    request=CelulaSolicitacao(igreja_id=v['t'],celula_id=v['cell'],tipo='multiplicacao',payload_proposto=payload)
    s.add(request);s.flush()
    return execute_multiplication(s, igreja_id=v['t'], cell_origin=s.get(Celula,v['cell']),
        payload=payload, solicitacao_id=request.id, idempotency_key=str(uuid4()))


@pytest.mark.parametrize('kind',['nomeacao','abertura','multiplicacao'])
def test_revoked_evidence_blocks_new_leadership(nomination,monkeypatch,kind):
    v=nomination
    monkeypatch.setattr(enviar_avaliacoes,'ler_pendencias_pessoa',lambda *a,**kw:
        ResultadoEnviar(situacao=SituacaoEnviar.BLOQUEADO,motivo='evidencia_revogada'))
    if kind=='multiplicacao':
        with scoped(v) as s,pytest.raises(HTTPException) as error: multiply(s,v)
        assert error.value.status_code==409
    else:
        row=create(v) if kind=='nomeacao' else opening(v)
        decider(v)
        assert approve(v,row).status_code==409
    with scoped(v) as s:
        assert s.get(Celula,v['cell']).lider_id==v['leader']
        assert s.scalar(text('select count(*) from celulas'))==1


@pytest.mark.parametrize('evaluation',['ausente','nao_apto'])
def test_multiplication_requires_current_evaluation(nomination,evaluation):
    v=nomination
    if evaluation=='ausente':
        v['p']=uuid4()
        with v['factory'].begin() as s:
            s.add(Pessoa(id=v['p'],igreja_id=v['t'],nome='Legado sintético',telefone=str(v['p']),apto_lider=True));s.flush()
            s.get(AppUser,v['candidate_user']).pessoa_id=v['p']
    else:
        with scoped(v) as s: decide(s,v,command(decisao='nao_apto',origem='avaliacao'));s.commit()
        with v['factory'].begin() as s:s.get(Pessoa,v['p']).apto_lider=True
    with scoped(v) as s,pytest.raises(HTTPException) as error: multiply(s,v)
    assert error.value.status_code==409


def test_event_privileges_and_validated_tenant_fk(nomination):
    with scoped(nomination) as s:
        for role in ('anon','service_role'):
            for privilege in ('SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER'):
                assert not s.scalar(text('select has_table_privilege(:role,:table,:privilege)'),dict(role=role,table='celula_solicitacao_evento',privilege=privilege))
        assert s.scalar(text("select has_table_privilege('authenticated','celula_solicitacao_evento','INSERT')"))
        assert s.scalar(text("select convalidated from pg_constraint where conname='nomeacao_celula_tenant_fk'"))


@pytest.mark.parametrize('day',['seg','Segunda-feira','segunda'])
def test_opening_normalizes_day_and_returns_created_cell(nomination,day):
    v=nomination;row=opening(v,dia_reuniao=day);decider(v)
    response=approve(v,row)
    assert response.status_code==200,response.text
    created=response.json()['celula_criada_id']
    assert created
    assert approve(v,row).json()['celula_criada_id']==created
    assert v['client'].get(f"/cell-requests/{row['id']}").json()['celula_criada_id']==created
    assert next(r for r in v['client'].get('/cell-requests').json()['items'] if r['id']==row['id'])['celula_criada_id']==created
    with scoped(v) as s:assert s.get(Celula,created).dia_reuniao=='Segunda-feira'


def test_opening_rejects_invalid_day(nomination):
    v=nomination
    response=v['client'].post('/cell-requests',json=dict(tipo='abrir_celula',payload_proposto=dict(nome='Nova',cobertura_espiritual='Teste',novo_lider_id=str(v['p']),dia_reuniao='qualquer dia')))
    assert response.status_code==422


def test_evaluated_multiplication_preserves_legacy_and_is_idempotent(nomination):
    v=nomination
    with scoped(v) as s:
        result=multiply(s,v)
        replay=execute_multiplication(s,igreja_id=v['t'],cell_origin=s.get(Celula,v['cell']),
            payload={},solicitacao_id=result.solicitacao_id,idempotency_key=result.idempotency_key)
        assert replay.id==result.id
        assert s.get(Celula,v['cell']).lider_id==v['leader']
        assert s.get(Celula,result.celula_nova_id).lider_id==v['p']
        s.commit()
    with scoped(v) as s:assert s.scalar(text('select count(*) from celulas'))==2
