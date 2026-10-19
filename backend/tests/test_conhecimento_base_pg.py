"""Official knowledge: real migration chain and live authorization, synthetic PG."""
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError, DBAPIError

from tests.test_uv_turmas_pg import (rls_database_url, migrated_database, database,
                                      seeded, scoped, principal)

pytestmark = pytest.mark.rls_integration


def snapshot(db, v, *, audience=None, state='rascunho', tenant=None, author=None):
    t = tenant or v['t']
    uid = author or v['uid']
    doc, ver = uuid4(), uuid4()
    db.execute(text('''insert into conhecimento_documentos
        (id,igreja_id,titulo,assunto,responsavel_id,autor_id)
        values(:d,:t,'FAQ sintética','institucional',:u,:u)'''), dict(d=doc,t=t,u=uid))
    db.execute(text("""insert into conhecimento_versoes
        (id,igreja_id,documento_id,conteudo,origem,autor_id,publicos)
        values(:v,:t,:d,'Texto sintético','redacao_manual',:u,:a)"""),
        dict(v=ver,t=t,d=doc,u=uid,a=audience or []))
    if state=='publicada':
        db.execute(text("update conhecimento_versoes set estado='em_revisao' where id=:v"),dict(v=ver))
        db.execute(text("""update conhecimento_versoes set estado='publicada',
            aprovador_id=:u,aprovada_em=now(),publicada_em=now() where id=:v"""),dict(u=uid,v=ver))
    db.execute(text('''update conhecimento_documentos set rascunho_id=:v,
        vigente_id=:p where igreja_id=:t and id=:d'''),
        dict(v=ver,p=ver if state=='publicada' else None,t=t,d=doc))
    return doc, ver


@pytest.mark.parametrize('role,publicos,expected', [
    ('admin',['papel:pastor'],False),
    ('pastor',['papel:pastor'],True), ('membro',['papel:pastor'],False),
    ('operador',['institucional_publico'],True), ('membro',['membros'],True),
    ('pastor',['membros'],False), ('membro',['papel:membro'],True),
])
def test_live_reader_role_and_deny_default(database,seeded,role,publicos,expected):
    from app.services.conhecimento import pode_ler
    v=seeded
    with database.begin() as c:
        c.execute(text('update user_roles set papel=:r where user_id=:u'),dict(r=role,u=v['leader']))
    with scoped(database,v['t']) as s:
        _,ver=snapshot(s,v,audience=publicos,state='publicada')
        assert pode_ler(s,principal(v,'leader'),ver) is expected
        assert not pode_ler(s,principal(v,'leader',tenant='other'),ver)


def test_visitors_drafts_revocation_and_live_role(database,seeded):
    from app.services.conhecimento import pode_ler, Visitante
    v=seeded
    with scoped(database,v['t']) as s:
        doc,ver=snapshot(s,v)
        assert pode_ler(s,principal(v),ver)
        assert not pode_ler(s,principal(v,'leader'),ver)
        assert not pode_ler(s,Visitante(v['t']),ver)
        _,pub=snapshot(s,v,audience=['institucional_publico'],state='publicada')
        assert pode_ler(s,Visitante(v['t']),pub)
        assert not pode_ler(s,Visitante(v['other']),pub)
        s.execute(text("update conhecimento_versoes set estado='revogada',revogada_em=now(),revogador_id=:u where id=:v"),dict(u=v['uid'],v=pub))
        assert not pode_ler(s,Visitante(v['t']),pub)
        s.execute(text("update app_users set status='revogado' where id=:u"),dict(u=v['uid']))
        assert not pode_ler(s,principal(v),ver)


@pytest.mark.parametrize('column,expression',[
    ('conteudo',"'Alterado'"),('origem',"'outra'"),('autor_id','null'),
    ('publicos',"array['institucional_publico']"),('hash',"'x'"),
    ('documento_id','gen_random_uuid()'),('igreja_id','gen_random_uuid()'),
    ('criada_em','now()'),
])
def test_version_is_immutable_even_for_owner(database,seeded,column,expression):
    v=seeded
    with scoped(database,v['t']) as s: _,ver=snapshot(s,v); s.commit()
    with database.begin() as c:
        with pytest.raises(DBAPIError):
            c.execute(text(f'update conhecimento_versoes set {column}={expression} where id=:v'),dict(v=ver))


@pytest.mark.parametrize('table',['conhecimento_documentos','conhecimento_versoes','conhecimento_operacoes'])
def test_rls_and_acl(database,seeded,table):
    v=seeded
    with scoped(database,v['t']) as s: snapshot(s,v); s.commit()
    with scoped(database,v['other']) as s:
        assert s.execute(text(f'select count(*) from {table}')).scalar()==0
        assert not s.execute(text("select has_table_privilege(current_user,:t,'DELETE')"),dict(t=table)).scalar()
        with pytest.raises(ProgrammingError):
            s.execute(text(f"insert into {table}(id,igreja_id) values(:id,:t)"),dict(id=uuid4(),t=v['t']))
    with database.connect() as c:
        assert c.execute(text('select relrowsecurity and relforcerowsecurity from pg_class where relname=:t'),dict(t=table)).scalar()
        for role in ['anon','service_role']:
            assert not c.execute(text("select has_table_privilege(:r,:t,'SELECT,INSERT,UPDATE,DELETE')"),dict(r=role,t=table)).scalar()


@pytest.mark.parametrize('edge',['autor','responsavel','documento','vigente'])
def test_cross_church_relations_refused(database,seeded,edge):
    v=seeded
    with database.begin() as c:
        c.execute(text("insert into app_users(id,igreja_id,status,nome,email) values(:u,:t,'ativo','Equipe sintética','outro@example.test')"),dict(u=v['other'],t=v['other']))
        _,other=snapshot(c,v,tenant=v['other'],author=v['other'])
    with scoped(database,v['t']) as s:
        doc,ver=snapshot(s,v)
        sql={
          'autor':"insert into conhecimento_documentos(id,igreja_id,titulo,assunto,responsavel_id,autor_id) values(:id,:t,'X','X',:u,:other)",
          'responsavel':"insert into conhecimento_documentos(id,igreja_id,titulo,assunto,responsavel_id,autor_id) values(:id,:t,'X','X',:other,:u)",
          'documento':"insert into conhecimento_versoes(id,igreja_id,documento_id,conteudo,origem,autor_id) values(:id,:t,:other,'X','manual',:u)",
          'vigente':"update conhecimento_documentos set vigente_id=:foreign where id=:d",
        }[edge]
        with pytest.raises(IntegrityError):
            s.execute(text(sql),dict(id=uuid4(),t=v['t'],u=v['uid'],other=v['other'],foreign=other,d=doc))


def test_direct_postgrest_even_with_forged_guc_cannot_read(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s: snapshot(s,v); s.commit()
    with database.begin() as c:
        c.exec_driver_sql("do $$ begin if not exists(select 1 from pg_roles where rolname='authenticator') then create role authenticator nologin; end if; end $$")
        c.exec_driver_sql('grant authenticated to authenticator')
    with database.connect() as c:
        tx=c.begin()
        try:
            c.exec_driver_sql('set session authorization authenticator')
            c.exec_driver_sql('set local role authenticated')
            c.execute(text("select set_config('app.tenant_igreja_id',:t,true)"),dict(t=str(v['t'])))
            assert c.execute(text('select count(*) from conhecimento_versoes')).scalar()==0
        finally:
            tx.rollback(); c.exec_driver_sql('reset session authorization'); c.commit()


def test_publish_requires_explicit_audience(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        _,ver=snapshot(s,v)
        s.execute(text("update conhecimento_versoes set estado='em_revisao' where id=:v"),dict(v=ver))
        with pytest.raises(IntegrityError):
            s.execute(text("""update conhecimento_versoes set estado='publicada',aprovador_id=:u,
                aprovada_em=now(),publicada_em=now() where id=:v"""),dict(u=v['uid'],v=ver))


def test_responsible_pastor_review_scope(database,seeded):
    from app.services.conhecimento import pode_ler
    v=seeded
    with database.begin() as c:
        c.execute(text("update user_roles set papel='pastor' where user_id=:u"),dict(u=v['leader']))
    with scoped(database,v['t']) as s:
        doc,ver=snapshot(s,v)
        assert not pode_ler(s,principal(v,'leader'),ver)
        s.execute(text("update conhecimento_versoes set estado='em_revisao' where id=:v"),dict(v=ver))
        assert not pode_ler(s,principal(v,'leader'),ver)
        # Responsibility is immutable metadata of the document. Seed another.
    with database.begin() as c:
        doc,ver=snapshot(c,v,author=v['leader'])
        c.execute(text("update conhecimento_versoes set estado='em_revisao' where id=:v"),dict(v=ver))
    with scoped(database,v['t']) as s:
        assert pode_ler(s,principal(v,'leader'),ver)
        s.execute(text("delete from user_roles where user_id=:u"),dict(u=v['leader']))
        assert not pode_ler(s,principal(v,'leader'),ver)


def test_valid_cross_scope_insert_is_denied_by_rls(database,seeded):
    v=seeded
    with scoped(database,v['other']) as s:
        with pytest.raises(ProgrammingError) as exc:
            s.execute(text("""insert into conhecimento_documentos
                (id,igreja_id,titulo,assunto,responsavel_id,autor_id)
                values(:id,:t,'Sintético','FAQ',:u,:u)"""),dict(id=uuid4(),t=v['t'],u=v['uid']))
        assert exc.value.orig.pgcode=='42501'


@pytest.mark.parametrize('edge',['anterior','rascunho','aprovador','revisor','revogador'])
def test_remaining_composite_foreign_keys(database,seeded,edge):
    v=seeded
    with database.begin() as c:
        c.execute(text("""insert into app_users(id,igreja_id,status,nome,email)
            values(:u,:t,'ativo','Equipe sintética','outro@example.test')"""),dict(u=v['other'],t=v['other']))
        _,other=snapshot(c,v,tenant=v['other'],author=v['other'])
    with scoped(database,v['t']) as s:
        doc,ver=snapshot(s,v)
        sql={
          'anterior':"""insert into conhecimento_versoes(id,igreja_id,documento_id,anterior_id,conteudo,origem,autor_id)
              values(:id,:t,:d,:foreign,'X','manual',:u)""",
          'rascunho':"update conhecimento_documentos set rascunho_id=:foreign where id=:d",
          'aprovador':"update conhecimento_versoes set aprovador_id=:other,aprovada_em=now() where id=:v",
          'revisor':"update conhecimento_versoes set revisada_por=:other,revisada_em=now() where id=:v",
          'revogador':"update conhecimento_versoes set revogador_id=:other,revogada_em=now() where id=:v",
        }[edge]
        with pytest.raises(IntegrityError) as exc:
            s.execute(text(sql),dict(id=uuid4(),t=v['t'],u=v['uid'],other=v['other'],foreign=other,d=doc,v=ver))
        assert exc.value.orig.pgcode=='23503'


def test_editorial_receipts_are_scoped_append_only(database,seeded):
    v=seeded
    with scoped(database,v['t']) as s:
        doc,ver=snapshot(s,v)
        s.execute(text('''insert into conhecimento_operacoes
            (igreja_id,id,documento_id,versao_id,ator_id,tipo,fingerprint)
            values(:t,:id,:d,:v,:u,'criar',:h)'''),dict(t=v['t'],id=uuid4(),d=doc,v=ver,u=v['uid'],h='a'*64))
        s.commit()
    with scoped(database,v['other']) as s:
        assert s.execute(text('select count(*) from conhecimento_operacoes')).scalar()==0
        for grant in ['UPDATE','DELETE']:
            assert not s.execute(text('select has_table_privilege(current_user,:t,:g)'),dict(t='conhecimento_operacoes',g=grant)).scalar()


@pytest.mark.parametrize('foreign_tenant',[False,True])
def test_receipt_must_reference_same_document_and_church(database,seeded,foreign_tenant):
    v=seeded
    with database.begin() as c:
        if foreign_tenant:
            c.execute(text("""insert into app_users(id,igreja_id,status,nome,email)
                values(:u,:t,'ativo','Equipe','outro@example.test')"""),dict(u=v['other'],t=v['other']))
        _,other=snapshot(c,v,tenant=v['other'] if foreign_tenant else v['t'],author=v['other'] if foreign_tenant else v['uid'])
    with scoped(database,v['t']) as s:
        doc,ver=snapshot(s,v)
        with pytest.raises(IntegrityError) as exc:
            s.execute(text("""insert into conhecimento_operacoes
                (igreja_id,id,documento_id,versao_id,ator_id,tipo,fingerprint)
                values(:t,:id,:d,:v,:u,'criar',:h)"""),
                dict(t=v['t'],id=uuid4(),d=doc,v=other,u=v['uid'],h='a'*64))
        assert exc.value.orig.pgcode=='23503'
