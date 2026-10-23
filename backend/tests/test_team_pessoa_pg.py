"""Vínculo administrativo: PostgreSQL local, RLS e dados sintéticos."""
import os
from pathlib import Path
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event, local
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.routers import auth, team
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


def test_admin_team_list_reports_person_link_states_and_tenant_count(database, seeded):
    v = seeded

    def add_member(connection, *, tenant, role, status='ativo', inactive=None):
        user_id = uuid4()
        person_id = uuid4() if inactive else None
        if person_id:
            connection.execute(text("""insert into pessoas
                (id,igreja_id,nome,telefone) values(:p,:t,'Pessoa sintética',:phone)"""), dict(
                    p=person_id, t=tenant, phone=f'55{person_id.int % 10**11:011d}'))
            if inactive == 'arquivada':
                connection.execute(text('update pessoas set arquivada_em=now() where id=:p'), dict(p=person_id))
            else:
                connection.execute(text('update pessoas set sem_interesse=true where id=:p'), dict(p=person_id))
        connection.execute(text("""insert into app_users
            (id,igreja_id,status,nome,email,pessoa_id)
            values(:u,:t,:s,'Conta sintética',:e,:p)"""), dict(
                u=user_id, t=tenant, s=status, e=f'{user_id}@example.test', p=person_id))
        connection.execute(text("""insert into user_roles(igreja_id,user_id,papel)
            values(:t,:u,:r)"""), dict(t=tenant, u=user_id, r=role))
        return user_id

    with database.begin() as connection:
        missing = add_member(connection, tenant=v['t'], role='pastor', status=None)
        archived = add_member(connection, tenant=v['t'], role='lider_g12', inactive='arquivada')
        uninterested = add_member(connection, tenant=v['t'], role='lider_mult', inactive='sem_interesse')
        invited = add_member(connection, tenant=v['t'], role='lider_celula', status='convidado')
        revoked = add_member(connection, tenant=v['t'], role='pastor', status='revogado')
        foreign = add_member(connection, tenant=v['other'], role='admin')

    with client_for(database, v) as client:
        response = client.get('/team?page=1&pageSize=100')
    assert response.status_code == 200, response.text
    body = response.json()
    members = {item['usuarioId']: item for item in body['items']}
    assert members[str(v['uid'])]['pessoa_vinculo'] == 'ativa'
    assert members[str(v['leader'])]['pessoa_vinculo'] == 'ativa'
    assert members[str(missing)]['pessoa_vinculo'] == 'sem_vinculo'
    assert members[str(archived)]['pessoa_vinculo'] == 'pessoa_inativa'
    assert members[str(uninterested)]['pessoa_vinculo'] == 'pessoa_inativa'
    assert members[str(v['outsider'])]['pessoa_vinculo'] == 'sem_vinculo'
    assert members[str(invited)]['pessoa_vinculo'] == 'sem_vinculo'
    assert members[str(revoked)]['pessoa_vinculo'] == 'sem_vinculo'
    assert str(foreign) not in members
    assert body['sem_pessoa_ativa_coordenacao'] == 3


def test_team_list_hides_person_link_signals_from_nonadmin(database, seeded):
    v = seeded
    with client_for(database, v, admin=False) as client:
        response = client.get('/team?page=1&pageSize=100')

    assert response.status_code == 200, response.text
    body = response.json()
    assert body['items']
    assert all('pessoa_vinculo' not in item for item in body['items'])
    assert 'sem_pessoa_ativa_coordenacao' not in body


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


@pytest.mark.parametrize('bypass', [False, True])
@pytest.mark.parametrize('leadership', ['active', 'inactive', 'foreign', 'none'])
def test_link_reconciles_persisted_leader_role(database, seeded, bypass, leadership):
    v = seeded
    subject = 'clerk_synthetic_link'
    with database.begin() as c:
        c.execute(text('update app_users set clerk_user_id=:s where id=:u'),
                  dict(s=subject, u=v['outsider']))
        if leadership != 'none':
            # The legacy FK permits a foreign cell to reference this Pessoa.
            # Even BYPASSRLS must not derive a role from another church.
            c.execute(text("insert into celulas(igreja_id,nome,lider_id,ativo,cobertura_espiritual) "
                           "values(:t,'Célula sintética',:p,:a,'Teste sintético')"),
                      dict(t=v['other'] if leadership == 'foreign' else v['t'],
                           p=v['p'], a=leadership != 'inactive'))
        other_roles = c.execute(text('select igreja_id,user_id,papel from user_roles where user_id<>:u order by id'),
                                dict(u=v['outsider'])).all()
        replacement = c.scalar(text('select pessoa_id from app_users where id=:u'), dict(u=v['leader']))
    with client_for(database, v, bypass=bypass) as client:
        for _ in range(2):
            response = client.put(f"/team/{v['outsider']}/pessoa", json={'pessoaId': str(v['p'])})
            assert response.status_code == 200, response.text
        if leadership == 'active':
            # Use a fresh eligible Pessoa so duplicate-access validation does
            # not mask the active-leadership guard on replacement.
            with database.begin() as c:
                c.execute(text('update app_users set pessoa_id=null where id=:u'), dict(u=v['leader']))
            for destination in (None, str(replacement)):
                response = client.put(f"/team/{v['outsider']}/pessoa", json={'pessoaId': destination})
                assert response.status_code == 409
                assert 'Transfira ou encerre' in response.json()['detail']
    expected = {'operador', 'lider_celula'} if leadership == 'active' else {'operador'}
    with Session(database) as db:
        # Exercise the real persisted-role authentication path on a new session.
        clerk = SimpleNamespace(verify_session_token=lambda _: SimpleNamespace(clerk_user_id=subject, claims={}))
        current = get_current_user('Bearer synthetic-session', db, clerk)
        assert current.roles == frozenset(expected)
    with database.connect() as c:
        assert c.execute(text('select igreja_id,user_id,papel from user_roles where user_id<>:u order by id'),
                         dict(u=v['outsider'])).all() == other_roles
        assert c.scalar(text('select count(*) from team_pessoa_eventos')) == 1


def test_leader_link_role_and_audit_rollback_together(database, seeded):
    from sqlalchemy.exc import IntegrityError
    v = seeded
    with database.begin() as c:
        c.execute(text("insert into celulas(igreja_id,nome,lider_id,ativo,cobertura_espiritual) "
                       "values(:t,'Célula sintética',:p,true,'Teste sintético')"), dict(t=v['t'], p=v['p']))

    def reject_commit(db):
        db.flush()
        assert db.scalar(text("select count(*) from user_roles where user_id=:u and papel='lider_celula'"),
                         dict(u=v['outsider'])) == 1
        assert db.scalar(text('select count(*) from team_pessoa_eventos')) == 1
        raise IntegrityError('synthetic commit failure', {}, None)

    event.listen(Session, 'before_commit', reject_commit)
    try:
        with client_for(database, v) as client:
            response = client.put(f"/team/{v['outsider']}/pessoa", json={'pessoaId': str(v['p'])})
            assert response.status_code == 409
    finally:
        event.remove(Session, 'before_commit', reject_commit)
    with database.connect() as c:
        assert c.scalar(text('select pessoa_id from app_users where id=:u'), dict(u=v['outsider'])) is None
        assert c.execute(text('select papel from user_roles where user_id=:u'), dict(u=v['outsider'])).scalars().all() == ['operador']
        assert c.scalar(text('select count(*) from team_pessoa_eventos')) == 0


@pytest.mark.parametrize('winner', ['activation', 'link'])
def test_activation_and_link_cannot_overwrite_identity(database, seeded, winner):
    v = seeded
    with database.begin() as c:
        c.execute(text("update app_users set status='convidado',email='invite-race@example.test' where id=:u"),
                  dict(u=v['outsider']))
        initial_people = c.scalar(text('select count(*) from pessoas'))
    paused, release, waiting = Event(), Event(), Event()
    participant = local()
    blocked = {}
    calls = []

    class Clerk:
        def verify_invite_token(self, _):
            return str(v['outsider'])

        def find_user_id_by_email(self, _):
            calls.append('lookup')
            return None

        def create_user(self, *_):
            calls.append('create')
            if winner == 'activation':
                paused.set()
                assert release.wait(15)
            return 'clerk_synthetic_race'

    def before_execute(conn, _cursor, statement, _params, _context, _many):
        if getattr(participant, 'name', None) in {'activation', 'link'} - {winner}:
            blocked['pid'] = conn.connection.dbapi_connection.get_backend_pid()
            waiting.set()

    def after_execute(_conn, _cursor, statement, _params, _context, _many):
        if (winner == 'link' and getattr(participant, 'name', None) == 'link'
                and statement.lower().startswith('update app_users set pessoa_id')):
            paused.set()
            assert release.wait(15)

    def run(name):
        participant.name = name
        with (Session(database, autoflush=False) if name == 'activation' else scoped(database, v['t'])) as db:
            db.execute(text("set local lock_timeout='10s'"))
            try:
                if name == 'activation':
                    auth.activate(
                        Request({'type': 'http', 'client': ('127.0.0.1', 1234)}),
                        auth.ActivateRequest(token='synthetic', password='synthetic-password', telefone='550000000077'),
                        db, Clerk(), SimpleNamespace(enforce_ip=lambda *_: None),
                    )
                else:
                    team.link_pessoa(v['outsider'], team.PessoaLinkRequest(pessoaId=v['p']), db, principal(v))
                return 200
            except HTTPException as exc:
                return exc.status_code

    event.listen(database, 'before_cursor_execute', before_execute)
    event.listen(database, 'after_cursor_execute', after_execute)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run, winner)
            try:
                assert paused.wait(10)
                second = pool.submit(run, 'link' if winner == 'activation' else 'activation')
                assert waiting.wait(10)
                deadline = time.monotonic() + 5
                with database.connect() as c:
                    while not c.scalar(text('select cardinality(pg_blocking_pids(:pid))'), blocked):
                        assert time.monotonic() < deadline, 'A segunda sessão não aguardou o lock'
                        time.sleep(0.01)
                assert not first.done() and not second.done()
            finally:
                release.set()
            assert first.result(timeout=10) == 200
            assert second.result(timeout=10) == 409
    finally:
        event.remove(database, 'before_cursor_execute', before_execute)
        event.remove(database, 'after_cursor_execute', after_execute)
    with database.connect() as c:
        pessoa, state, clerk_id = c.execute(text('select pessoa_id,status,clerk_user_id from app_users where id=:u'),
                                           dict(u=v['outsider'])).one()
        if winner == 'activation':
            assert pessoa != v['p'] and pessoa is not None
            assert state == 'ativo' and clerk_id == 'clerk_synthetic_race'
            assert calls == ['lookup', 'create']
            assert c.scalar(text('select count(*) from pessoas')) == initial_people + 1
            assert c.scalar(text('select id from pessoas where telefone=:p'), dict(p='550000000077')) == pessoa
            assert c.scalar(text('select count(*) from team_pessoa_eventos')) == 0
        else:
            assert pessoa == v['p'] and state == 'convidado' and clerk_id is None
            assert calls == []
            assert c.scalar(text('select count(*) from pessoas')) == initial_people
            assert c.scalar(text('select count(*) from pessoas where telefone=:p'), dict(p='550000000077')) == 0
            assert c.execute(text('select operacao,pessoa_id from team_pessoa_eventos')).one() == ('vincular', v['p'])


@pytest.mark.parametrize('operation', ['link', 'revoke'])
def test_activation_existing_person_serializes_before_team_mutation(database, seeded, operation):
    """Parte A: convite já vinculado não forma ciclo Igreja/Pessoa na ativação."""
    v = seeded
    destination = uuid4()
    with database.begin() as c:
        c.execute(text("update app_users set status='convidado',email='invite-linked-race@example.test',pessoa_id=:p where id=:u"),
                  dict(p=v['p'], u=v['outsider']))
        c.execute(text("insert into celulas(igreja_id,nome,lider_id,ativo,cobertura_espiritual) "
                       "values(:t,'Célula sintética',:p,true,'Teste sintético')"),
                  dict(t=v['t'], p=v['p']))
        if operation == 'link':
            c.execute(text("insert into pessoas(id,igreja_id,nome,telefone) "
                           "values(:p,:t,'Destino sintético','550000000078')"),
                      dict(p=destination, t=v['t']))
        c.execute(text("delete from user_roles where user_id=:u and papel='lider_celula'"),
                  dict(u=v['outsider']))
        initial_people = c.scalar(text('select count(*) from pessoas'))

    clerk_paused, release_clerk, team_lock_started = Event(), Event(), Event()
    role_insert_started, release_role_insert = Event(), Event()
    participant = local()
    activation_pid = {}
    team_wait = {}

    class Clerk:
        def verify_invite_token(self, _):
            return str(v['outsider'])

        def find_user_id_by_email(self, _):
            return None

        def create_user(self, *_):
            clerk_paused.set()
            assert release_clerk.wait(8), 'A ativação não foi liberada pelo teste'
            return 'clerk_synthetic_existing_person_race'

        def delete_user(self, *_):
            return None

    def before_execute(conn, _cursor, statement, _params, _context, _many):
        name = getattr(participant, 'name', None)
        pid = conn.connection.dbapi_connection.get_backend_pid()
        normalized = ' '.join(statement.lower().split())
        if name == 'activation':
            activation_pid.setdefault('pid', pid)
        if name == 'team' and ' for update' in normalized and (
            ' from igrejas ' in normalized or ' from pessoas ' in normalized
        ):
            team_wait.update(pid=pid, current_statement=normalized)
            team_lock_started.set()
        if name == 'activation' and normalized.startswith('insert into user_roles'):
            role_insert_started.set()
            assert release_role_insert.wait(5), 'A inserção sintética de papel não foi liberada'

    def run_activation():
        participant.name = 'activation'
        with Session(database, autoflush=False) as db:
            db.execute(text("set local lock_timeout='1500ms'"))
            try:
                auth.activate(
                    Request({'type': 'http', 'client': ('127.0.0.1', 1234)}),
                    auth.ActivateRequest(token='synthetic', password='synthetic-password', telefone=None),
                    db, Clerk(), SimpleNamespace(enforce_ip=lambda *_: None),
                )
                return ('ok', 200)
            except HTTPException as exc:
                db.rollback()
                return ('http', exc.status_code)
            except DBAPIError as exc:
                db.rollback()
                return ('db', getattr(exc.orig, 'pgcode', None))

    def run_team():
        participant.name = 'team'
        with scoped(database, v['t']) as db:
            db.execute(text("set local lock_timeout='4s'"))
            try:
                if operation == 'link':
                    team.link_pessoa(
                        v['outsider'],
                        team.PessoaLinkRequest(pessoaId=destination),
                        db,
                        principal(v),
                    )
                else:
                    team.revoke_member(str(v['outsider']), db, principal(v))
                return ('ok', 200)
            except HTTPException as exc:
                db.rollback()
                return ('http', exc.status_code)
            except DBAPIError as exc:
                db.rollback()
                return ('db', getattr(exc.orig, 'pgcode', None))

    event.listen(database, 'before_cursor_execute', before_execute)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            activation = pool.submit(run_activation)
            try:
                assert clerk_paused.wait(5), 'A ativação não chegou à chamada sintética do Clerk'
                team_mutation = pool.submit(run_team)
                assert team_lock_started.wait(5), 'A operação de equipe não iniciou sua trava'
                deadline = time.monotonic() + 3
                with database.connect() as c:
                    blockers = []
                    while time.monotonic() < deadline:
                        blockers = c.scalar(
                            text('select pg_blocking_pids(:pid)'),
                            dict(pid=team_wait['pid']),
                        )
                        if activation_pid.get('pid') in blockers:
                            team_wait['blocked_statement'] = team_wait['current_statement']
                            break
                        time.sleep(0.01)
                    assert activation_pid.get('pid') in blockers, (
                        'A operação de equipe não aguardou a conexão de ativação'
                    )
                release_clerk.set()
                assert role_insert_started.wait(5), 'A ativação não sincronizou o papel de liderança'
                release_role_insert.set()
                cycle_deadline = time.monotonic() + 0.75
                mutual_wait_observed = False
                with database.connect() as c:
                    while time.monotonic() < cycle_deadline:
                        blockers = c.scalar(
                            text('select pg_blocking_pids(:pid)'),
                            dict(pid=activation_pid['pid']),
                        )
                        if team_wait['pid'] in blockers:
                            mutual_wait_observed = True
                            break
                        time.sleep(0.01)
            finally:
                release_clerk.set()
                release_role_insert.set()
            activation_result = activation.result(timeout=6)
            team_result = team_mutation.result(timeout=6)
    finally:
        release_clerk.set()
        event.remove(database, 'before_cursor_execute', before_execute)

    # Na ordem antiga, a equipe segurava a Igreja enquanto aguardava Pessoa;
    # a FK de user_roles fechava o ciclo e o PostgreSQL cancelava uma transação.
    assert activation_result == ('ok', 200), (
        f'ativação={activation_result}, equipe={team_result}, '
        f'espera_equipe={team_wait["blocked_statement"]!r}, ciclo={mutual_wait_observed}'
    )
    assert team_result == ('http', 409), (
        f'ativação={activation_result}, equipe={team_result}, '
        f'espera_equipe={team_wait["blocked_statement"]!r}, ciclo={mutual_wait_observed}'
    )
    assert ' from igrejas ' in team_wait['blocked_statement']
    assert not mutual_wait_observed
    with database.connect() as c:
        pessoa, state, clerk_id = c.execute(
            text('select pessoa_id,status,clerk_user_id from app_users where id=:u'),
            dict(u=v['outsider']),
        ).one()
        assert pessoa == v['p']
        assert state == 'ativo'
        assert clerk_id == 'clerk_synthetic_existing_person_race'
        assert c.scalar(text('select count(*) from pessoas')) == initial_people
        assert c.scalar(text('select count(*) from team_pessoa_eventos')) == 0
        assert c.scalar(text("select count(*) from user_roles where user_id=:u and papel='lider_celula'"),
                        dict(u=v['outsider'])) == 1
