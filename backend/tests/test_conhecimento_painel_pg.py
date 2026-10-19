"""Painel usa autorização viva e PG real, inclusive para leitores e histórico."""
import pytest
from sqlalchemy import text
from tests.test_conhecimento_api_pg import client, create, edit, action, publish
from tests.test_uv_turmas_pg import rls_database_url, migrated_database, database, seeded

pytestmark = pytest.mark.rls_integration


def test_panel_lifecycle_history_and_reader_scope(database, seeded):
    v = seeded
    with client(database, v) as c:
        p = create(c, v)
        panel = c.get('/conhecimento/documentos').json()
        assert panel['pode_criar']
        assert panel['documentos'][0]['versoes'][0]['acoes'] == ['editar', 'enviar-revisao', 'revogar']
        p = edit(c, p)
        publish(c, p)
        new = edit(c, p)
        publish(c, new, p['versao_id'])
        panel = c.get('/conhecimento/documentos').json()
        versions = panel['documentos'][0]['versoes']
        assert [r['estado'] for r in versions] == ['substituida', 'substituida', 'publicada']
        assert not versions[1]['pode_ler']
        assert versions[2]['vigente']
        assert 'conteudo' not in str(panel)
    with client(database, v, 'outsider') as c:
        panel = c.get('/conhecimento/documentos').json()
        assert not panel['pode_criar'] and panel['responsavel_id'] is None
        assert len(panel['documentos'][0]['versoes']) == 1
        assert panel['documentos'][0]['versoes'][0]['acoes'] == []
    with client(database, v) as c:
        assert action(c, new, 'revogar').status_code == 200
        assert c.get('/conhecimento/documentos').json()['documentos'][0]['versoes'][-1]['estado'] == 'revogada'
    with client(database, v, 'outsider') as c:
        assert c.get('/conhecimento/documentos').json()['documentos'] == []


def test_pastor_draft_hidden_until_review_and_no_foreign_area(database, seeded):
    v = seeded
    with database.begin() as s:
        s.execute(text("update user_roles set papel='pastor' where user_id=:u"), dict(u=v['leader']))
    with client(database, v) as c:
        create(c, v)
    with client(database, v, 'leader') as c:
        p = create(c, dict(v, uid=v['leader']))
        p = edit(c, p)
        assert c.get('/conhecimento/documentos').json()['documentos'] == []
        assert c.get('/conhecimento/versoes/' + p['versao_id']).status_code == 404
        assert action(c, p, 'enviar-revisao').status_code == 200
        panel = c.get('/conhecimento/documentos').json()
        assert len(panel['documentos']) == 1
        assert panel['documentos'][0]['versoes'][0]['acoes'] == ['editar', 'revisar']
        assert action(c, p, 'publicar', publicos=['institucional_publico'], vigente_esperada_id=None).status_code == 403
    with database.begin() as s:
        s.execute(text("delete from user_roles where user_id=:u"), dict(u=v['leader']))
    with client(database, v, 'leader') as c:
        panel = c.get('/conhecimento/documentos').json()
        assert not panel['pode_criar'] and panel['documentos'] == []


def test_panel_auth_tenant_and_admin_not_universal_reader(database, seeded):
    v = seeded
    with client(database, v) as c:
        p = create(c, v)
        p = edit(c, p, publicos=['papel:pastor'])
        publish(c, p)
        versions = c.get('/conhecimento/documentos').json()['documentos'][0]['versoes']
        assert all(not r['pode_ler'] for r in versions)
        assert versions[-1]['estado'] == 'publicada'
        assert versions[-1]['acoes'] == ['editar', 'revogar']
        assert c.get('/conhecimento/versoes/' + p['versao_id']).status_code == 404
    with client(database, v, authenticated=False) as c:
        assert c.get('/conhecimento/documentos').status_code == 401
    with client(database, v, 'outsider', 'other') as c:
        assert c.get('/conhecimento/documentos').status_code == 403
    with database.begin() as s:
        s.execute(text("update app_users set status='revogado' where id=:u"), dict(u=v['uid']))
    with client(database, v) as c:
        assert c.get('/conhecimento/documentos').status_code == 403


def test_panel_two_valid_tenants_never_share_metadata(database, seeded):
    v = seeded
    with database.begin() as s:
        s.execute(text("""insert into app_users(id,igreja_id,nome,email,status)
            values(:u,:t,'Admin sintético B','admin-b@example.test','ativo')"""),
            dict(u=v['other'], t=v['other']))
        s.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:t,:u,'admin')"),
            dict(u=v['other'], t=v['other']))
    with client(database, v) as a, client(database, v, 'other', 'other') as b:
        first = create(a, v)
        assert b.get('/conhecimento/documentos').json()['documentos'] == []
        second = create(b, dict(v, uid=v['other']))
        a_ids = [d['id'] for d in a.get('/conhecimento/documentos').json()['documentos']]
        b_ids = [d['id'] for d in b.get('/conhecimento/documentos').json()['documentos']]
        assert a_ids == [first['id']]
        assert b_ids == [second['id']]
        assert b.get('/conhecimento/versoes/' + first['versao_id']).status_code == 404


def test_pastor_recovers_content_free_pending_draft_after_new_session(database, seeded):
    v = seeded
    with database.begin() as s:
        s.execute(text("update user_roles set papel='pastor' where user_id=:u"), dict(u=v['leader']))
    with client(database, v, 'leader') as c:
        p = create(c, dict(v, uid=v['leader']))
    with client(database, v, 'leader') as c:
        panel = c.get('/conhecimento/documentos').json()
        assert panel['documentos'] == []
        assert panel['pendentes'] == [dict(documento_id=p['id'], versao_id=p['versao_id'])]
        assert p['titulo'] not in str(panel) and p['conteudo'] not in str(panel)
        assert action(c, p, 'enviar-revisao').status_code == 200
        assert c.get('/conhecimento/documentos').json()['pendentes'] == []
    with client(database, v, 'outsider') as c:
        assert c.get('/conhecimento/documentos').json()['pendentes'] == []


def test_panel_pages_history_with_bounded_database_round_trips(database, seeded):
    from sqlalchemy import event
    v = seeded
    with client(database, v) as c:
        p = create(c, v)
        for _ in range(25):
            p = edit(c, p)
        queries = []
        def count(connection, cursor, statement, parameters, context, executemany):
            queries.append(statement)
        event.listen(database, 'before_cursor_execute', count)
        try:
            first = c.get('/conhecimento/documentos').json()
        finally:
            event.remove(database, 'before_cursor_execute', count)
        assert len(queries) <= 20
        assert first['tem_mais'] and first['pagina'] == 1
        second = c.get('/conhecimento/documentos?pagina=2').json()
        assert not second['tem_mais']
        versions = first['documentos'][0]['versoes'] + second['documentos'][0]['versoes']
        assert sorted(v['numero'] for v in versions) == list(range(1, 27))
        assert len({v['id'] for v in versions}) == 26
        assert c.get('/conhecimento/documentos?pagina=0').status_code == 422
