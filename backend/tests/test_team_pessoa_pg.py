"""Vínculo administrativo: PostgreSQL local, RLS e dados sintéticos."""
import os
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
from tests.test_uv_turmas_pg import migrated_database, database, seeded, scoped, principal
from tests.conftest_rls import assert_disposable_database

pytestmark = pytest.mark.rls_integration


@pytest.fixture(scope='module')
def rls_database_url():
    url = os.environ['UV_TURMAS_DATABASE_URL']
    assert_disposable_database(url)
    from sqlalchemy.engine import make_url
    parsed = make_url(url)
    assert parsed.host == '127.0.0.1' and parsed.database == 'uv_turmas_test'
    return url


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
        rows = c.execute(text('select operacao from team_pessoa_eventos order by criado_em')).scalars().all()
        assert rows == ['vincular', 'desvincular']


@pytest.mark.parametrize('bypass', [False, True])
@pytest.mark.parametrize('kind,expected', [('other_person',404), ('other_user',404), ('inactive',409), ('uninterested',409), ('duplicate',409), ('nonadmin',403)])
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
            s.execute(text("insert into team_pessoa_eventos(igreja_id,actor_id,usuario_id,operacao) values(:t,:a,:u,'vincular')"), dict(t=v['t'],a=v['uid'],u=v['outsider']))
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
    with client_for(database, v) as client:
        assert client.put(f"/team/{v['uid']}/pessoa", json={'pessoaId': str(v['p'])}).status_code == 200
        assert client.put(f"/team/{v['uid']}/pessoa", json={}).status_code == 422
        assert client.put(f"/team/{v['uid']}/pessoa", json={'pessoaId': 'invalid'}).status_code == 422
        assert client.put(f"/team/{v['uid']}/pessoa", json={'pessoaId': None, 'papeis':['admin']}).status_code == 422
    with database.connect() as c:
        assert c.scalar(text('select pessoa_id from app_users where id=:u'), dict(u=v['uid'])) == v['p']
        assert c.scalar(text('select count(*) from app_users')) == 3


def test_concurrent_users_cannot_claim_same_person(database, seeded):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    v = seeded
    barrier = Barrier(2)
    def link(user):
        with client_for(database, v) as client:
            barrier.wait(timeout=10)
            return client.put(f'/team/{user}/pessoa', json={'pessoaId': str(v['p'])}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(link, [v['leader'], v['outsider']]))
    assert sorted(results) == [200, 409]
    with database.connect() as c:
        assert c.scalar(text('select count(*) from app_users where pessoa_id=:p'), dict(p=v['p'])) == 1
        assert c.scalar(text('select count(*) from team_pessoa_eventos')) == 1
