"""Vínculo administrativo: PostgreSQL local, RLS e dados sintéticos."""
import os
from pathlib import Path
import subprocess
import sys
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.routers.team import router
from tests.test_uv_turmas_pg import migrated_database, seeded, scoped, principal
from tests.conftest_rls import assert_disposable_database

pytestmark = pytest.mark.rls_integration
MIGRATION = '20261025_100000_team_pessoa.sql'


@pytest.fixture(scope='module')
def rls_database_url():
    url = os.environ['UV_TURMAS_DATABASE_URL']
    assert_disposable_database(url)
    from sqlalchemy.engine import make_url
    parsed = make_url(url)
    assert parsed.host == '127.0.0.1' and parsed.database == 'uv_turmas_test'
    return url


@pytest.fixture
def database(migrated_database):
    with migrated_database.begin() as c:
        # A trilha sobrevive às origens; limpeza explícita só no PG sintético.
        c.exec_driver_sql('delete from team_pessoa_eventos; delete from igrejas')
    return migrated_database


def client_for(database, v, *, admin=True, bypass=False):
    app = FastAPI()
    app.include_router(router)
    def db():
        with (Session(database) if bypass else scoped(database, v['t'])) as s:
            yield s
    user = principal(v)
    if not admin:
        user = replace(user, roles=frozenset({'pastor'}))
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_link_unlink_idempotent_and_audited(database, seeded):
    v = seeded
    with client_for(database, v) as client:
        for pessoa in (str(v['p']), str(v['p']), None, None):
            r = client.put(f"/team/{v['outsider']}/pessoa", json={'pessoaId': pessoa})
            assert r.status_code == 200, r.text
            assert r.json() == dict(usuarioId=str(v['outsider']), pessoaId=pessoa)
    with database.connect() as c:
        assert c.scalar(text('select pessoa_id from app_users where id=:u'), dict(u=v['outsider'])) is None
        assert c.scalar(text('select status from app_users where id=:u'), dict(u=v['outsider'])) == 'ativo'
        assert c.execute(text('select papel from user_roles where user_id=:u'), dict(u=v['outsider'])).scalars().all() == ['operador']
        rows = c.execute(text('select operacao,pessoa_id,igreja_id,actor_id,usuario_id from team_pessoa_eventos order by criado_em')).all()
        assert rows == [(operation, v['p'], v['t'], v['uid'], v['outsider'])
                        for operation in ('vincular', 'desvincular')]


@pytest.mark.parametrize('bypass', [False, True])
@pytest.mark.parametrize('kind,expected', [('other_person',404), ('other_user',404), ('inactive',409), ('uninterested',409), ('duplicate',409), ('revoked',409), ('nonadmin',403)])
def test_refusals(database, seeded, kind, expected, bypass):
    v = seeded
    person, user = v['p'], v['outsider']
    with database.begin() as c:
        if kind == 'other_person':
            person = uuid4()
            c.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:p,:t,'Pessoa sintética','550000000099')"), dict(p=person,t=v['other']))
        if kind == 'other_user':
            user = uuid4()
            c.execute(text("insert into app_users(id,igreja_id,nome,email) values(:u,:t,'Usuário sintético','other@example.test')"), dict(u=user,t=v['other']))
        if kind == 'inactive':
            c.execute(text('update pessoas set arquivada_em=now() where id=:p'), dict(p=person))
        if kind == 'uninterested':
            c.execute(text("update pessoas set sem_interesse=true,sem_interesse_motivo='Teste sintético' where id=:p"), dict(p=person))
        if kind == 'duplicate':
            person = c.scalar(text('select pessoa_id from app_users where id=:u'), dict(u=v['uid']))
        if kind == 'revoked':
            c.execute(text("update app_users set status='revogado' where id=:u"), dict(u=user))
    with client_for(database, v, admin=kind != 'nonadmin', bypass=bypass) as client:
        r = client.put(f'/team/{user}/pessoa', json={'pessoaId': str(person)})
        assert r.status_code == expected, r.text
    with database.connect() as c:
        assert c.scalar(text('select count(*) from team_pessoa_eventos')) == 0
        assert c.scalar(text('select pessoa_id from app_users where id=:u'), dict(u=v['outsider'])) is None


def test_unique_index_and_audit_rls(database, seeded):
    from sqlalchemy.exc import IntegrityError, ProgrammingError
    v = seeded
    with database.begin() as c:
        with pytest.raises(IntegrityError):
            with c.begin_nested():
                c.execute(text('update app_users set pessoa_id=(select pessoa_id from app_users where id=:a) where id=:u'), dict(a=v['uid'],u=v['outsider']))
    with client_for(database, v) as client:
        assert client.put(f"/team/{v['outsider']}/pessoa", json={'pessoaId': str(v['p'])}).status_code == 200
    with scoped(database, v['other']) as s:
        assert s.scalar(text('select count(*) from team_pessoa_eventos')) == 0
        with pytest.raises(ProgrammingError):
            s.execute(text("insert into team_pessoa_eventos(igreja_id,actor_id,usuario_id,pessoa_id,operacao) values(:t,:a,:u,:p,'vincular')"), dict(t=v['t'],a=v['uid'],u=v['outsider'],p=v['p']))
    with scoped(database, v['t']) as s:
        assert s.scalar(text('select count(*) from team_pessoa_eventos')) == 1
        with pytest.raises(ProgrammingError):
            s.execute(text('delete from team_pessoa_eventos'))


def test_unlink_or_replace_leader_refused(database, seeded):
    v = seeded
    with database.begin() as c:
        person = c.scalar(text('select pessoa_id from app_users where id=:u'), dict(u=v['uid']))
        c.execute(text("insert into celulas(id,igreja_id,nome,lider_id,ativo,cobertura_espiritual) values(:id,:t,'Célula sintética',:p,true,'Teste sintético')"), dict(id=uuid4(),t=v['t'],p=person))
    with client_for(database, v) as client:
        for dest in (None, str(v['p'])):
            r = client.put(f"/team/{v['uid']}/pessoa", json={'pessoaId': dest})
            assert r.status_code == 409, r.text
        assert client.put(f"/team/{v['uid']}/pessoa", json={'pessoaId': str(person)}).status_code == 200


def test_existing_link_replaced_without_changing_access(database, seeded):
    v = seeded
    with database.connect() as c:
        previous = c.scalar(text('select pessoa_id from app_users where id=:u'), dict(u=v['uid']))
    with client_for(database, v) as client:
        assert client.put(f"/team/{v['uid']}/pessoa", json={'pessoaId': str(v['p'])}).status_code == 200
        assert client.put(f"/team/{v['uid']}/pessoa", json={}).status_code == 422
        assert client.put(f"/team/{v['uid']}/pessoa", json={'pessoaId': 'invalid'}).status_code == 422
        assert client.put(f"/team/{v['uid']}/pessoa", json={'pessoaId': None, 'papeis':['admin']}).status_code == 422
    with database.connect() as c:
        assert c.scalar(text('select pessoa_id from app_users where id=:u'), dict(u=v['uid'])) == v['p']
        assert c.scalar(text('select count(*) from app_users')) == 3
        assert c.execute(text('select operacao,pessoa_id from team_pessoa_eventos order by criado_em')).all() == [
            ('desvincular', previous), ('vincular', v['p']),
        ]


@pytest.mark.parametrize('state', [None, 'ativo', 'convidado'])
def test_link_preserves_access_status(database, seeded, state):
    v = seeded
    with database.begin() as c:
        c.execute(text('update app_users set status=:s where id=:u'), dict(s=state,u=v['outsider']))
    with client_for(database, v) as client:
        assert client.put(f"/team/{v['outsider']}/pessoa", json={'pessoaId': str(v['p'])}).status_code == 200
    with database.connect() as c:
        assert c.scalar(text('select status from app_users where id=:u'), dict(u=v['outsider'])) == state


def test_revoked_existing_link_refuses_relink_but_allows_unlink(database, seeded):
    v = seeded
    with database.begin() as c:
        c.execute(text("update app_users set pessoa_id=:p,status='revogado' where id=:u"), dict(p=v['p'],u=v['outsider']))
    with client_for(database, v) as client:
        response = client.put(f"/team/{v['outsider']}/pessoa", json={'pessoaId': str(v['p'])})
        assert response.status_code == 409
        assert 'Reative o acesso' in response.json()['detail']
        with database.connect() as c:
            assert c.scalar(text('select count(*) from team_pessoa_eventos')) == 0
        assert client.put(f"/team/{v['outsider']}/pessoa", json={'pessoaId': None}).status_code == 200
    with database.connect() as c:
        assert c.scalar(text('select status from app_users where id=:u'), dict(u=v['outsider'])) == 'revogado'
        assert c.execute(text('select operacao,pessoa_id from team_pessoa_eventos')).one() == ('desvincular', v['p'])


@pytest.mark.parametrize('origin', ['usuario', 'actor', 'igreja', 'pessoa'])
def test_audit_survives_origin_deletion(database, seeded, origin):
    v = seeded
    with client_for(database, v) as client:
        assert client.put(f"/team/{v['outsider']}/pessoa", json={'pessoaId': str(v['p'])}).status_code == 200
        assert client.put(f"/team/{v['outsider']}/pessoa", json={'pessoaId': None}).status_code == 200
    with database.begin() as c:
        before = c.execute(text('select * from team_pessoa_eventos order by criado_em')).all()
        table, key = {'usuario': ('app_users', 'outsider'), 'actor': ('app_users', 'uid'),
                      'igreja': ('igrejas', 't'), 'pessoa': ('pessoas', 'p')}[origin]
        c.execute(text(f'delete from {table} where id=:id'), dict(id=v[key]))
        assert c.execute(text('select * from team_pessoa_eventos order by criado_em')).all() == before


def test_migration_duplicate_preflight_and_accumulated_upgrade(database, seeded, rls_database_url):
    v = seeded
    other_person, other_user, duplicate_user = uuid4(), uuid4(), uuid4()
    runner = Path(__file__).resolve().parents[1] / 'scripts/migrate.py'
    env = dict(os.environ, MIGRATION_DATABASE_URL=rls_database_url.replace('postgresql+psycopg2:', 'postgresql:'))

    def apply():
        return subprocess.run([sys.executable, str(runner), 'apply', MIGRATION, '--yes'],
                              env=env, capture_output=True, text=True)

    with database.begin() as c:
        # Reconstitui o estado acumulado imediatamente anterior à migration.
        c.exec_driver_sql('drop table team_pessoa_eventos; drop index app_users_pessoa_unica_por_igreja')
        c.execute(text('delete from schema_migrations where name=:m'), dict(m=MIGRATION))
        person = c.scalar(text('select pessoa_id from app_users where id=:u'), dict(u=v['uid']))
        c.execute(text('update app_users set pessoa_id=:p where id=:u'), dict(p=person,u=v['outsider']))
        c.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:p,:t,'Duplicidade sintética','550000000099')"), dict(p=other_person,t=v['other']))
        for user in (other_user, duplicate_user):
            c.execute(text("insert into app_users(id,igreja_id,pessoa_id,nome,email) values(:u,:t,:p,'Duplicidade sintética','duplicate@example.test')"), dict(u=user,t=v['other'],p=other_person))
        before = c.execute(text('select id,igreja_id,pessoa_id from app_users order by id')).all()
    try:
        result = apply()
        assert result.returncode != 0
        assert '2 grupo(s) duplicado(s)' in result.stderr
        for identity in (v['t'], person, v['other'], other_person):
            assert str(identity) in result.stderr
        for private in ('Duplicidade sintética', 'duplicate@example.test', '550000000099',
                        str(v['uid']), str(v['outsider']), str(other_user), str(duplicate_user)):
            assert private not in result.stderr
        with database.connect() as c:
            assert c.execute(text('select id,igreja_id,pessoa_id from app_users order by id')).all() == before
            assert c.scalar(text("select to_regclass('public.app_users_pessoa_unica_por_igreja')")) is None
            assert c.scalar(text("select to_regclass('public.team_pessoa_eventos')")) is None
            assert c.scalar(text('select count(*) from schema_migrations where name=:m'), dict(m=MIGRATION)) == 0
    finally:
        # Decisão manual simulada: somente os dois vínculos perdedores são soltos.
        with database.begin() as c:
            for user in (v['outsider'], duplicate_user):
                c.execute(text('update app_users set pessoa_id=null where id=:u'), dict(u=user))
            reconciled = c.execute(text('select id,igreja_id,pessoa_id from app_users order by id')).all()
        result = apply()
        assert result.returncode == 0, result.stderr
    with database.connect() as c:
        assert c.execute(text('select id,igreja_id,pessoa_id from app_users order by id')).all() == reconciled
        assert c.scalar(text('select count(*) from team_pessoa_eventos')) == 0
        assert c.scalar(text('select count(*) from schema_migrations where name=:m'), dict(m=MIGRATION)) == 1
        assert c.execute(text("select relrowsecurity,relforcerowsecurity from pg_class where oid='public.team_pessoa_eventos'::regclass")).one() == (True, True)


def test_concurrent_users_cannot_claim_same_person(database, seeded):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    v = seeded
    users = [v['leader'], v['outsider']]
    with database.connect() as c:
        previous = dict(c.execute(text('select id,pessoa_id from app_users')).all())
    barrier = Barrier(2)
    def link(user):
        with client_for(database, v) as client:
            barrier.wait(timeout=10)
            return client.put(f'/team/{user}/pessoa', json={'pessoaId': str(v['p'])}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(link, users))
    assert sorted(results) == [200, 409]
    winner = users[results.index(200)]
    with database.connect() as c:
        assert c.execute(text('select id from app_users where pessoa_id=:p'), dict(p=v['p'])).scalars().all() == [winner]
        expected = [('desvincular', previous[winner], winner)] if previous[winner] else []
        expected.append(('vincular', v['p'], winner))
        assert c.execute(text('select operacao,pessoa_id,usuario_id from team_pessoa_eventos order by criado_em')).all() == expected
