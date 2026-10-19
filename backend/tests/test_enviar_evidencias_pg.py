"""Official evidence through real formation services and tenant PostgreSQL."""
from uuid import uuid4
from types import SimpleNamespace as DTO
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from app.db.models import Pessoa
from app.routers.uv import ConclusaoInput, ResponsaveisInput
from app.services import uv, cd
from app.services.enviar_read import ler_evidencias_oficiais, ler_pendencias_oficiais
from app.services.enviar_avaliacoes import aptidao_vigente, _snapshot
from tests.test_uv_turmas_pg import rls_database_url, migrated_database, database, seeded, scoped, principal
from tests.test_uv_conclusao_pg import complete, marco
from tests.test_cd_conclusoes_pg import short_course, second, finish, issue
from tests.test_cd_turmas_pg import create
from tests.test_cd_matriculas_pg import command, legacy

pytestmark = pytest.mark.rls_integration


def certificate(s, v):
    legacy(s,v)
    c=short_course(s,v)
    for tid in (create(s,v,c),second(s,v,c)):
        mid=cd.enroll(s,principal(v),tid,command(v))['id']
        finish(s,v,tid,mid,equivalence=True)
    return c,issue(s,v,c['id'])


def test_official_chain_reissue_revocation_and_no_automatic_promotion(database,seeded):
    v=seeded
    with database.begin() as c:
        actor_person=uuid4()
        c.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:p,:t,'Coordenação sintética','550000000002')"),dict(p=actor_person,t=v['t']))
        c.execute(text('update app_users set pessoa_id=:p where id=:u'),dict(p=actor_person,u=v['uid']))
    with scoped(database,v['t']) as s:
        person=s.get(Pessoa,v['p'])
        tid,mid=complete(s,v)
        conclusion=uv.finish(s,principal(v),tid,mid,ConclusaoInput(id=uuid4(),confirmado=True))
        c,cert=certificate(s,v)
        milestone=uv.milestone(s,principal(v),tid,mid,'reencontro',marco())
        result,evidence=_snapshot(s,person)
        assert result.situacao=='apto_para_avaliacao'
        assert all(e['estado']=='comprovada' and e['referencia'] for e in evidence.values())
        assert str(conclusion['id']) in evidence['uv']['referencia']
        assert str(cert['codigo']) in evidence['cd']['referencia']
        assert str(milestone['id']) in evidence['reencontro']['referencia']
        s.refresh(person)
        assert not person.apto_lider and not aptidao_vigente(s,person)
        from app.services.enviar_avaliacoes import registrar_avaliacao
        from app.routers.enviar import AvaliacaoInput
        decision=registrar_avaliacao(s,principal(v),v['p'],AvaliacaoInput(id=uuid4(),decisao='apto',origem='avaliacao',motivo='Formação oficial conferida'))
        assert decision.evidencias==evidence and aptidao_vigente(s,person)
        from app.services.enviar_avaliacoes import snapshot_aptidao
        snapshot=snapshot_aptidao(s,person)
        assert snapshot['criterios']==dict.fromkeys(('uv','cd','reencontro'),'comprovada')
        assert snapshot['referencias']=={k:r['referencia'] for k,r in evidence.items()}
        cd.revoke_certificate(s,principal(v),cert['id'],DTO(motivo='Correção sintética'))
        assert ler_pendencias_oficiais(s,person,igreja_id=v['t']).motivo=='evidencia_revogada'
        assert ler_evidencias_oficiais(s,person,igreja_id=v['t'])['cd']['estado']=='revogada'
        new=issue(s,v,c['id'])
        assert str(new['id']) in ler_evidencias_oficiais(s,person,igreja_id=v['t'])['cd']['referencia']
        assert ler_pendencias_oficiais(s,person,igreja_id=v['t']).situacao=='apto_para_avaliacao'
        uv.revoke_milestone(s,principal(v),tid,mid,'reencontro',DTO(motivo='Validação incorreta'))
        assert ler_evidencias_oficiais(s,person,igreja_id=v['t'])['reencontro']['estado']=='revogada'
        assert ler_pendencias_oficiais(s,person,igreja_id=v['t']).motivo=='evidencia_revogada'
        s.refresh(person)
        assert person.apto_lider and not aptidao_vigente(s,person)


def test_legacy_does_not_attest_uv_and_scope_is_explicit(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        legacy(s,v)
        s.execute(text('update pessoas set apto_lider=true where id=:p'),dict(p=v['p']))
        person=s.get(Pessoa,v['p'])
        result=ler_pendencias_oficiais(s,person,igreja_id=v['t'])
        assert result.aviso_legado=='origem legada, comprovação pendente'
        assert {p.criterio for p in result.pendencias}=={'uv','cd','reencontro'}
        with pytest.raises(ValueError): ler_evidencias_oficiais(s,person,igreja_id=v['other'])


@pytest.mark.parametrize('operation',['validate','revoke'])
def test_reencontro_requires_live_coordination(database,seeded,operation):
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=complete(s,v)
        uv.responsaveis(s,principal(v),tid,ResponsaveisInput(usuarios=[v['leader']]))
        if operation=='revoke': uv.milestone(s,principal(v),tid,mid,'reencontro',marco())
        with pytest.raises(HTTPException) as exc:
            if operation=='validate': uv.milestone(s,principal(v,'leader'),tid,mid,'reencontro',marco())
            else: uv.revoke_milestone(s,principal(v,'leader'),tid,mid,'reencontro',DTO(motivo='Correção'))
        assert exc.value.status_code==403


def test_uv_of_another_church_does_not_count_even_under_bypassrls(database,seeded):
    from sqlalchemy.orm import Session
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=complete(s,v)
        uv.finish(s,principal(v),tid,mid,ConclusaoInput(id=uuid4(),confirmado=True))
        s.commit()
    foreign=uuid4()
    with database.begin() as c:
        c.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:p,:t,'Outra pessoa sintética','550000000003')"),dict(p=foreign,t=v['other']))
    with Session(database) as s:
        person=s.get(Pessoa,foreign)
        assert ler_evidencias_oficiais(s,person,igreja_id=v['other'])['uv']==dict(estado='nao_informada',referencia=None)
        assert ler_evidencias_oficiais(s,s.get(Pessoa,v['p']),igreja_id=v['t'])['uv']['estado']=='comprovada'


@pytest.mark.parametrize('table',['uv_marcos','uv_conclusoes'])
def test_official_evidence_cannot_be_forged_via_postgrest(database,seeded,table):
    from sqlalchemy.orm import Session
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=complete(s,v)
        uv.milestone(s,principal(v),tid,mid,'reencontro',marco())
        uv.finish(s,principal(v),tid,mid,ConclusaoInput(id=uuid4(),confirmado=True))
        s.commit()
    with database.begin() as c:
        c.exec_driver_sql("do $$ begin if not exists(select 1 from pg_roles where rolname='authenticator') then create role authenticator nologin; end if; end $$")
        c.exec_driver_sql('grant authenticated to authenticator')
        c.execute(text("update app_users set clerk_user_id='synthetic-clerk' where id=:u"),dict(u=v['uid']))
    with scoped(database,v['t']) as s:
        s.execute(text('set local session authorization authenticator'))
        s.execute(text('set local role authenticated'))
        assert s.scalar(text(f'select count(*) from {table}'))==0
        assert s.scalar(text(f"select has_table_privilege('service_role',:t,'SELECT')"),dict(t=table)) is False
    with Session(database) as s:
        s.execute(text('set local role authenticated'))
        s.execute(text("select set_config('request.jwt.claims',:c,true)"),dict(c='{"sub":"synthetic-clerk"}'))
        assert s.scalar(text(f'select count(*) from {table}'))==0


def test_reencontro_http_validation_revocation_is_audited_and_idempotent(database,seeded):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.uv import router
    from app.db.session import get_db
    from app.deps import get_current_user
    v=seeded
    with scoped(database,v['t']) as s:
        tid,mid=complete(s,v)
        uv.close(s,principal(v),tid)  # Reencontro belongs to Pessoa after UV too.
        s.commit()
    app=FastAPI(); app.include_router(router)
    def db():
        with scoped(database,v['t']) as s: yield s
    app.dependency_overrides[get_db]=db
    app.dependency_overrides[get_current_user]=lambda:principal(v)
    path=f'/uv/turmas/{tid}/matriculas/{mid}/marcos/reencontro'
    payload=marco().model_dump(mode='json')
    with TestClient(app) as client:
        assert client.post(path,json=payload | dict(validada_por=str(v['leader']))).status_code==422
        first=client.post(path,json=payload)
        assert first.status_code==200,first.text
        assert first.json()['validada_por']==str(v['uid'])
        assert client.post(path,json=payload).json()==first.json()
        assert client.post(path+'/revogar',json=dict(motivo=' ')).status_code==422
        revoked=client.post(path+'/revogar',json=dict(motivo='Registro conferido incorretamente'))
        assert revoked.status_code==200,revoked.text
        assert revoked.json()['revogada_por']==str(v['uid']) and revoked.json()['revogada_em']
        assert client.post(path+'/revogar',json=dict(motivo='Registro conferido incorretamente')).json()==revoked.json()
        assert client.post(path+'/revogar',json=dict(motivo='Outro motivo')).status_code==409
    with scoped(database,v['t']) as s:
        assert not s.get(Pessoa,v['p']).apto_lider
        assert ler_evidencias_oficiais(s,s.get(Pessoa,v['p']),igreja_id=v['t'])['reencontro']['estado']=='revogada'
