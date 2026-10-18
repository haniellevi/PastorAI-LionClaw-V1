"""Snapshots de aprovação reais, sem dados pessoais adicionais."""
import pytest
from sqlalchemy import select
from app.db.models import CelulaSolicitacaoEvento, EnviarAvaliacao
from tests.test_enviar_nomeacao_pg import nomination, create, decider, approve  # noqa: F401
from tests.test_enviar_abertura_pg import create as opening
from tests.test_enviar_avaliacoes_pg import sample, actor, scoped  # noqa: F401
from tests.test_whatsapp_integrated_pg import migrated_factory  # noqa: F401
from tests.conftest_rls import rls_database_url  # noqa: F401
pytestmark = pytest.mark.rls_integration

@pytest.mark.parametrize('kind', ['nomeacao', 'abertura'])
def test_approval_records_minimal_current_evidence_once(nomination, kind):
    v = nomination
    row = create(v) if kind == 'nomeacao' else opening(v)
    decider(v)
    assert approve(v, row).status_code == 200
    assert approve(v, row).status_code == 200
    with scoped(v) as s:
        events = s.scalars(select(CelulaSolicitacaoEvento).where(
            CelulaSolicitacaoEvento.solicitacao_id == row['id'],
            CelulaSolicitacaoEvento.acao == 'aprovada')).all()
        assert len(events) == 1
        snapshot = events[0].payload_snapshot['aptidao']
        latest = s.scalars(select(EnviarAvaliacao).where(EnviarAvaliacao.pessoa_id == v['p'])).one()
        assert snapshot == dict(avaliacao_id=str(latest.id), avaliada_em=latest.criada_em.isoformat(),
            versao_regras=latest.versao_regras, criterios=dict(uv='indisponivel_nesta_base',
            cd='indisponivel_nesta_base', reencontro='pendente'))


def multiplication_request(v):
    from uuid import uuid4
    from app.db.models import CelulaMembro, CelulaSolicitacao, Pessoa
    member = uuid4()
    with v['factory'].begin() as s:
        s.add(Pessoa(id=member, igreja_id=v['t'], nome='Membro sintético', telefone=str(member), celula_id=v['cell']))
        s.flush()
        s.add(CelulaMembro(igreja_id=v['t'], celula_id=v['cell'], pessoa_id=member, ativo=True, papel='membro'))
        request = CelulaSolicitacao(igreja_id=v['t'], celula_id=v['cell'], solicitante_id=v['leader'],
            tipo='multiplicacao', payload_proposto=dict(novo_lider_id=str(v['p']),
                nome_nova_celula='Multiplicada sintética', membros_transferidos_ids=[str(member)]))
        s.add(request); s.flush()
        return request.id, member


def approve_multiplication(v, request_id):
    from app.db.models import Celula, CelulaSolicitacao
    from app.services.cell_requests_service import approve as service_approve
    with scoped(v) as s:
        return service_approve(s, solicitacao=s.get(CelulaSolicitacao, request_id),
            cell=s.get(Celula,v['cell']), actor_pessoa_id=v['actor_p'],
            approver_app_user_id=v['u'], idempotency_key=str(request_id))


def test_multiplication_snapshot_transfer_and_idempotency(nomination):
    from app.db.models import CelulaMembro, Multiplicacao, Pessoa
    v=nomination; request_id, member=multiplication_request(v)
    approve_multiplication(v,request_id)
    approve_multiplication(v,request_id)
    with scoped(v) as s:
        multiplication=s.scalars(select(Multiplicacao)).one()
        assert s.get(Pessoa,member).celula_id==multiplication.celula_nova_id
        memberships=s.scalars(select(CelulaMembro).where(CelulaMembro.pessoa_id==member)).all()
        assert len(memberships)==2 and sum(m.ativo for m in memberships)==1
        event=s.scalars(select(CelulaSolicitacaoEvento).where(CelulaSolicitacaoEvento.acao=='aprovada')).one()
        assert set(event.payload_snapshot['aptidao'])=={'avaliacao_id','avaliada_em','versao_regras','criterios'}
        assert set(event.payload_snapshot['aptidao']['criterios'])=={'uv','cd','reencontro'}


def test_multiplication_negative_decision_after_request(nomination):
    from fastapi import HTTPException
    from tests.test_enviar_avaliacoes_pg import decide, command
    v=nomination; request_id,_=multiplication_request(v)
    with scoped(v) as s:
        decide(s,v,command(decisao='nao_apto',origem='avaliacao'));s.commit()
    with pytest.raises(HTTPException) as error: approve_multiplication(v,request_id)
    assert error.value.status_code in (409, 422)


def test_multiplication_snapshot_failure_rolls_back_transfers(nomination,monkeypatch):
    from app.db.models import Celula, CelulaMembro, CelulaSolicitacao, Multiplicacao, Pessoa
    from app.services import cell_requests_service
    v=nomination; request_id,member=multiplication_request(v)
    def fail(*args,**kwargs):
        args[0].flush()
        raise RuntimeError('synthetic audit failure')
    monkeypatch.setattr(cell_requests_service,'_append_event',fail)
    with pytest.raises(RuntimeError,match='synthetic audit failure'):approve_multiplication(v,request_id)
    with scoped(v) as s:
        assert s.get(Pessoa,member).celula_id==v['cell']
        assert len(s.scalars(select(CelulaMembro).where(CelulaMembro.pessoa_id==member)).all())==1
        assert s.scalar(select(CelulaMembro.ativo).where(CelulaMembro.pessoa_id==member))
        assert s.scalars(select(Multiplicacao)).all()==[]
        assert len(s.scalars(select(Celula)).all())==1
        assert s.get(CelulaSolicitacao,request_id).status=='aguardando'
        assert s.scalars(select(CelulaSolicitacaoEvento)).all()==[]


def test_waiting_multiplication_revalidates_committed_evaluation(nomination):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep
    from fastapi import HTTPException
    from sqlalchemy import text
    from tests.test_enviar_avaliacoes_pg import decide, command
    from app.services.cell_requests_service import approve as service_approve
    from app.db.models import Celula, CelulaSolicitacao
    v=nomination; request_id,_=multiplication_request(v);ready=Event();pid=[]
    def waiting():
        with scoped(v) as s:
            request=s.get(CelulaSolicitacao,request_id);cell=s.get(Celula,v['cell'])
            pid.append(s.scalar(text('select pg_backend_pid()')));ready.set()
            with pytest.raises(HTTPException) as error:
                service_approve(s,solicitacao=request,cell=cell,actor_pessoa_id=v['actor_p'],
                    approver_app_user_id=v['u'],idempotency_key=str(request_id))
            assert error.value.status_code in (409, 422)
    with scoped(v) as holder,ThreadPoolExecutor(1) as pool:
        decide(holder,v,command(decisao='nao_apto',origem='avaliacao'))
        future=pool.submit(waiting)
        try:
            assert ready.wait(3)
            with v['factory']() as observer:
                deadline=monotonic()+5
                while not observer.scalar(text('select cardinality(pg_blocking_pids(:pid))>0'),dict(pid=pid[0])):
                    assert monotonic()<deadline
                    sleep(.02)
        finally: holder.commit()
        future.result(timeout=10)
    with scoped(v) as s:
        assert len(s.scalars(select(Celula)).all())==1
        assert s.get(CelulaSolicitacao,request_id).status=='aguardando'
