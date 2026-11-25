"""Legacy UV records survive M20 and remain usable in the current chain."""
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.models import Pessoa
from app.services import cd, uv
from app.services.enviar_read import ler_evidencias_oficiais
from tests.test_cd_matriculas_pg import command
from tests.test_cd_turmas_pg import create
from tests.test_uv_conclusao_pg import marco
from tests.test_uv_turmas_pg import rls_database_url, replay_database, scoped, principal, seeded

pytestmark = pytest.mark.rls_integration
M20 = '20261018_100000_enviar_reencontro.sql'


def test_pre_m20_history_and_legacy_enrollment(rls_database_url):
    state = {}

    def before_migration(engine, filename):
        if filename != M20:
            return
        v = seeded.__wrapped__(engine)
        state.update(v=v, tid=uuid4(), mid=uuid4())
        with engine.begin() as c:
            c.execute(text("insert into uv_turmas(id,igreja_id,nome,criada_por) values(:tid,:t,'Turma sintética',:uid)"), state | v)
            c.execute(text('insert into uv_matriculas(id,igreja_id,turma_id,pessoa_id,criada_por) values(:mid,:t,:tid,:p,:uid)'), state | v)
            for kind in ('encontro', 'batismo'):
                c.execute(text("insert into uv_marcos(id,igreja_id,pessoa_id,turma_id,matricula_id,tipo,data,anterior_turma,validada_por) values(:id,:t,:p,:tid,:mid,:kind,'2020-01-01',true,:uid)"), state | v | dict(id=uuid4(), kind=kind))
            c.execute(text('update pessoas set apto_proxima_cd=true where id=:p'), v)
            state['history'] = c.execute(text('select * from uv_marcos order by tipo')).mappings().all()
            state['person'] = c.execute(text('select etapa,apto_proxima_cd,apto_lider from pessoas where id=:p'), v).one()

    engine = replay_database(rls_database_url, before_migration)
    try:
        v = state['v']
        with scoped(engine, v['t']) as s:
            rows = s.execute(text('select * from uv_marcos order by tipo')).mappings().all()
            assert len(rows) == 2
            for old, current in zip(state['history'], rows):
                assert all(current[key] == value for key, value in old.items())
                assert current['revogada'] is False
                assert all(current[key] is None for key in ('revogada_por', 'revogada_em', 'motivo_revogacao'))
            assert s.execute(text('select etapa,apto_proxima_cd,apto_lider from pessoas where id=:p'), v).one() == state['person']
            assert s.scalar(text('select count(*) from uv_conclusoes')) == 0
            tid = create(s, v)
            cd.enroll(s, principal(v), tid, command(v))
            assert cd.list_enrollments(s, principal(v), tid)[0]['origem_aptidao'] == 'legado'
            reencontro = uv.milestone(s, principal(v), state['tid'], state['mid'], 'reencontro', marco())
            person = s.get(Pessoa, v['p'])
            evidence = ler_evidencias_oficiais(s, person, igreja_id=v['t'])
            assert evidence['reencontro']['estado'] == 'comprovada'
            assert str(reencontro['id']) in evidence['reencontro']['referencia']
            assert evidence['uv']['estado'] == 'nao_informada'
            assert evidence['cd']['estado'] == 'nao_informada'
            s.refresh(person)
            assert person.etapa == state['person'].etapa
            assert not person.apto_lider
            assert s.scalar(text('select count(*) from uv_conclusoes')) == 0
    finally:
        engine.dispose()
