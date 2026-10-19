"""Authorized lexical retrieval over real disposable PostgreSQL."""
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services.conhecimento import Visitante, buscar
from tests.test_conhecimento_api_pg import client, create, edit, publish, action
from tests.test_uv_turmas_pg import (rls_database_url, migrated_database, database,
                                    seeded, scoped, principal)

pytestmark = pytest.mark.rls_integration


def published(c, v, content='Orientação de oração para famílias', audience=None):
    p = create(c, v)
    p = edit(c, p, conteudo=content, publicos=audience or ['institucional_publico'])
    publish(c, p)
    return p


def test_audience_before_ranking_and_limit(database, seeded):
    v = seeded
    with client(database, v) as c:
        hidden = published(c, v, 'oração ' * 100, ['papel:admin'])
        public = published(c, v)
    with client(database, v, 'outsider') as c:
        r = c.get('/conhecimento/busca', params=dict(q='oração', limite=1))
        assert r.status_code == 200, r.text
        assert len(r.json()) == 1
        assert r.json()[0]['versao_id'] == public['versao_id']
        assert hidden['versao_id'] not in r.text
        assert set(r.json()[0]) == {'titulo', 'versao_id', 'secao', 'ordem', 'trecho'}
    with scoped(database, v['t']) as s:
        assert len(buscar(s, principal(v), 'oração')) == 2
        results = buscar(s, Visitante(v['t']), 'oração', 1)
        assert [str(r['versao_id']) for r in results] == [public['versao_id']]


def test_current_replaced_revoked_empty_and_accents(database, seeded):
    v = seeded
    with client(database, v) as c:
        p = published(c, v)
        assert len(c.get('/conhecimento/busca?q=oracao').json()) == 1
        assert c.get('/conhecimento/busca?q=inexistente').json() == []
        replacement = edit(c, p, conteudo='Orientação de batismo')
        assert len(c.get('/conhecimento/busca?q=oração').json()) == 1
        publish(c, replacement, p['versao_id'])
        assert c.get('/conhecimento/busca?q=oração').json() == []
        assert c.get('/conhecimento/busca?q=batismo').json()[0]['versao_id'] == replacement['versao_id']
        assert action(c, replacement, 'revogar').status_code == 200
        assert c.get('/conhecimento/busca?q=batismo').json() == []


def test_tenant_rls_fks_and_acl(database, seeded):
    v = seeded
    with client(database, v) as c:
        p = published(c, v)
    with scoped(database, v['other']) as s:
        assert buscar(s, Visitante(v['other']), 'oração') == []
        assert s.execute(text('select count(*) from conhecimento_trechos')).scalar() == 0
        with pytest.raises(DBAPIError):
            s.execute(text('''insert into conhecimento_trechos
                (igreja_id,versao_id,ordem,secao,texto,busca)
                values(:t,:v,1,'X','X',to_tsvector('portuguese','X'))'''),
                dict(t=v['other'], v=UUID(p['versao_id'])))
    with database.connect() as s:
        assert s.execute(text("select relrowsecurity and relforcerowsecurity from pg_class where oid='conhecimento_trechos'::regclass")).scalar()
        for role in ('anon', 'service_role'):
            assert not s.execute(text("select has_table_privilege(:r,'conhecimento_trechos','SELECT')"), dict(r=role)).scalar()
        assert not s.execute(text("select has_table_privilege('authenticated','conhecimento_trechos','UPDATE')")).scalar()


def test_atomic_chunks_and_failure_rolls_back_publication(database, seeded):
    v = seeded
    with client(database, v) as c:
        p = published(c, v, 'oração ' * 1000)
    with scoped(database, v['t']) as s:
        chunks = s.execute(text('select texto from conhecimento_trechos where versao_id=:v order by ordem'), dict(v=p['versao_id'])).scalars().all()
        assert ''.join(chunks) == p['conteudo']
        assert len(chunks) > 1
    with client(database, v) as c:
        replacement = edit(c, p)
        assert action(c, replacement, 'enviar-revisao').status_code == 200
    with database.begin() as s:
        s.exec_driver_sql("""create function public.test_reject_chunk() returns trigger
            language plpgsql as $$ begin raise exception 'synthetic chunk failure'; end $$;
            create trigger test_reject_chunk before insert on conhecimento_trechos
            for each row execute function public.test_reject_chunk()""")
    try:
        with client(database, v) as c:
            with pytest.raises(DBAPIError):
                action(c, replacement, 'publicar', publicos=replacement['publicos'], vigente_esperada_id=p['versao_id'])
        with scoped(database, v['t']) as s:
            assert s.execute(text('select vigente_id from conhecimento_documentos where id=:d'), dict(d=p['id'])).scalar() == UUID(p['versao_id'])
            assert s.execute(text('select count(*) from conhecimento_trechos where versao_id=:v'), dict(v=replacement['versao_id'])).scalar() == 0
    finally:
        with database.begin() as s:
            s.exec_driver_sql('drop trigger test_reject_chunk on conhecimento_trechos; drop function public.test_reject_chunk()')


def test_authentication_live_identity_and_bounds(database, seeded):
    v = seeded
    with client(database, v, authenticated=False) as c:
        assert c.get('/conhecimento/busca?q=oração').status_code == 401
    with client(database, v) as c:
        for params in (dict(q=' '), dict(q='x', limite=21), dict(q='x' * 201)):
            assert c.get('/conhecimento/busca', params=params).status_code == 422
    with database.begin() as s:
        s.execute(text("update app_users set status='revogado' where id=:u"), dict(u=v['uid']))
    with client(database, v) as c:
        assert c.get('/conhecimento/busca?q=oração').status_code == 403


def test_word_on_section_boundary(database, seeded):
    with client(database, seeded) as c:
        p = published(c, seeded, 'x ' * 999 + 'oração')
        result = c.get('/conhecimento/busca?q=oração').json()
        assert len(result) == 1
        assert result[0]['versao_id'] == p['versao_id']


@pytest.mark.parametrize('state', ['publicada', 'rascunho'])
def test_authenticated_cannot_plant_chunks(database, seeded, state):
    v = seeded
    with client(database, v) as c:
        p = published(c, v) if state == 'publicada' else create(c, v)
    with scoped(database, v['t']) as s:
        with pytest.raises(DBAPIError) as exc:
            s.execute(text("""insert into conhecimento_trechos
                (igreja_id,versao_id,ordem,secao,texto,busca)
                values(:t,:v,99,'Falso','Falso',to_tsvector('portuguese','Falso'))"""),
                dict(t=v['t'], v=p['versao_id']))
        assert exc.value.orig.pgcode == '42501'


@pytest.mark.parametrize('link', ['active', 'missing', 'archived'])
def test_members_audience_requires_live_person(database, seeded, link):
    v = seeded
    with client(database, v) as c:
        p = published(c, v, audience=['membros'])
    with database.begin() as s:
        s.execute(text("update user_roles set papel='membro' where user_id=:u"), dict(u=v['outsider']))
        s.execute(text("update pessoas set tipo='membro', arquivada_em=case when :archived then now() end where id=:p"),
                  dict(p=v['p'], archived=link == 'archived'))
        if link != 'missing':
            s.execute(text('update app_users set pessoa_id=:p where id=:u'), dict(p=v['p'], u=v['outsider']))
    with client(database, v, 'outsider') as c:
        r = c.get('/conhecimento/busca', params=dict(q='oração'))
        assert r.status_code == 200, r.text
        assert [x['versao_id'] for x in r.json()] == ([p['versao_id']] if link == 'active' else [])


def test_http_search_isolates_two_published_tenants(database, seeded):
    v = seeded
    with database.begin() as s:
        s.execute(text("insert into app_users(id,igreja_id,nome,email,status) values(:u,:u,'Outro','other@example.test','ativo')"), dict(u=v['other']))
        s.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:u,:u,'admin')"), dict(u=v['other']))
    other = dict(v, t=v['other'], uid=v['other'])
    with client(database, v) as c:
        a = published(c, v)
    with client(database, other) as c:
        b = published(c, other)
    for tenant, own, hidden in ((v, a, b), (other, b, a)):
        with client(database, tenant) as c:
            r = c.get('/conhecimento/busca', params=dict(q='oração'))
            assert r.status_code == 200, r.text
            assert [x['versao_id'] for x in r.json()] == [own['versao_id']]
            assert hidden['versao_id'] not in r.text


@pytest.mark.parametrize('control', ['\x00', '\x01', '\t', '\n', '\r', '\x1f', '\x7f', '\x85'])
def test_http_search_rejects_control_characters(database, seeded, control):
    with client(database, seeded) as c:
        assert c.get('/conhecimento/busca', params=dict(q='oração' + control)).status_code == 422


@pytest.mark.parametrize('state', ['publicada', 'rascunho'])
def test_insert_guard_also_rejects_privileged_direct_insert(database, seeded, state):
    v = seeded
    with client(database, v) as c:
        p = published(c, v) if state == 'publicada' else create(c, v)
    with database.connect() as s:
        with pytest.raises(DBAPIError) as exc:
            s.execute(text("""insert into conhecimento_trechos
                (igreja_id,versao_id,ordem,secao,texto,busca)
                values(:t,:v,99,'Falso','Falso',to_tsvector('portuguese','Falso'))"""),
                dict(t=v['t'], v=p['versao_id']))
        assert exc.value.orig.pgcode == '42501'
        assert 'somente pelo gatilho' in str(exc.value)


@pytest.mark.parametrize('corrupt', [False, True])
def test_migration_backfill_is_complete_or_aborts(database, seeded, corrupt):
    from pathlib import Path
    from scripts.migrate import strip_outer_transaction

    with client(database, seeded) as c:
        p = published(c, seeded)
    # Transactional replay of the exact SQL; rollback restores the test schema.
    with database.connect() as s:
        s.exec_driver_sql('drop trigger conhecimento_publicacao_trechos on conhecimento_versoes')
        s.exec_driver_sql('drop table conhecimento_trechos')
        s.exec_driver_sql('drop function conhecimento_gerar_trechos(), conhecimento_validar_trecho(), conhecimento_dividir(text)')
        s.exec_driver_sql('drop text search configuration public.conhecimento_portuguese')
        if corrupt:
            # Synthetic legacy corruption must fail closed, not disappear from search.
            s.exec_driver_sql('alter table conhecimento_versoes disable trigger conhecimento_snapshot')
            s.exec_driver_sql('alter table conhecimento_versoes drop constraint conhecimento_versoes_conteudo_check')
            s.execute(text("update conhecimento_versoes set conteudo='' where id=:v"), dict(v=p['versao_id']))
        sql = strip_outer_transaction((Path(__file__).resolve().parents[1] /
            'migrations/20261018_140000_conhecimento_trechos.sql').read_text())
        if corrupt:
            with pytest.raises(DBAPIError, match='versão publicada sem trechos após backfill'):
                s.exec_driver_sql(sql, execution_options={'no_parameters': True})
        else:
            s.exec_driver_sql(sql, execution_options={'no_parameters': True})
            assert s.execute(text('select count(*) from conhecimento_trechos where versao_id=:v'), dict(v=p['versao_id'])).scalar() > 0
