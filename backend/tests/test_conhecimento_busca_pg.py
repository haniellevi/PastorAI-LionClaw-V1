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
        s.execute(text('revoke insert on conhecimento_trechos from authenticated'))
    try:
        with client(database, v) as c:
            with pytest.raises(DBAPIError):
                action(c, replacement, 'publicar', publicos=replacement['publicos'], vigente_esperada_id=p['versao_id'])
        with scoped(database, v['t']) as s:
            assert s.execute(text('select vigente_id from conhecimento_documentos where id=:d'), dict(d=p['id'])).scalar() == UUID(p['versao_id'])
            assert s.execute(text('select count(*) from conhecimento_trechos where versao_id=:v'), dict(v=replacement['versao_id'])).scalar() == 0
    finally:
        with database.begin() as s:
            s.execute(text('grant insert on conhecimento_trechos to authenticated'))


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
