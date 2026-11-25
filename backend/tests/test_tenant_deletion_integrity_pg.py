"""Nominal platform deletion with administrative authors on the full active schema."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AppUser
from app.deps import get_platform_admin
from app.services.auth_sessions import register_session
from app.services.clerk import ClerkIdentity
from app.services.tenant_deletion import TenantDeletionActor, delete_tenant_locally
from tests.test_private_deletion_pg import (
    database,  # noqa: F401
    migrated_database,  # noqa: F401
    private_data,  # noqa: F401
    responsibilities,  # noqa: F401
    rls_database_url,  # noqa: F401
)

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def administrative_authorship(database, responsibilities):
    v = responsibilities
    with database.begin() as c:
        v['clerk'] = f"synthetic-{v['admin']}"
        c.execute(text("update app_users set clerk_user_id=:clerk,pessoa_id=:person where id=:admin"), v)
        c.execute(text("insert into platform_admins(app_user_id,email) values(:admin,'synthetic@example.invalid')"), v)
        c.execute(text('update igrejas set dono_id=:admin where id=:tenant'), v)
        # The team migration explicitly keeps this technical audit trail when
        # a church, user or person is deleted.
        c.execute(text("""insert into team_pessoa_eventos(igreja_id,actor_id,usuario_id,pessoa_id,operacao)
            values(:tenant,:admin,:admin,:person,'vincular')"""), v)
        v['other_admin'] = c.scalar(text('select id from app_users where igreja_id=:other'), v)
        v['other_clerk'] = f"synthetic-{v['other_admin']}"
        c.execute(text('update app_users set clerk_user_id=:other_clerk where id=:other_admin'), v)
        c.execute(text("insert into platform_admins(app_user_id,email) values(:other_admin,'other@example.invalid')"), v)
        c.execute(text('update igrejas set dono_id=:other_admin where id=:other'), v)
    return v


def _delete(database, v, clerk):
    with Session(database) as s, s.begin():
        admin = get_platform_admin('Bearer synthetic', s, clerk)
        actor = TenantDeletionActor(UUID(admin.app_user_id), admin.email)
        return delete_tenant_locally(s, v['tenant'], actor)


def _seed_uv(c, tenant, author):
    params = dict(t=tenant, actor=author, turma=uuid4())
    c.execute(text("insert into uv_turmas(id,igreja_id,nome,criada_por) values(:turma,:t,'Synthetic',:actor)"), params)
    c.execute(text("insert into uv_atividades(igreja_id,turma_id,ordem,aula,tipo,data,criada_por) values(:t,:turma,1,1,'aula',current_date,:actor)"), params)
    c.execute(text("insert into uv_responsaveis(igreja_id,turma_id,usuario_id,atribuido_por) values(:t,:turma,:actor,:actor)"), params)


def _seed_cd(c, tenant, author):
    params = dict(t=tenant, actor=author, curriculo=uuid4(), modulo=uuid4(), aula=uuid4(), turma=uuid4(), nivel=uuid4())
    c.execute(text("insert into cd_curriculos(id,igreja_id,nome,versao,criada_por) values(:curriculo,:t,'Synthetic','1',:actor)"), params)
    c.execute(text("insert into cd_niveis(id,igreja_id,curriculo_id,numero,nome) values(:nivel,:t,:curriculo,1,'Synthetic')"), params)
    c.execute(text("insert into cd_modulos(id,igreja_id,curriculo_id,nivel_id,numero,nome) values(:modulo,:t,:curriculo,:nivel,1,'Synthetic')"), params)
    c.execute(text("insert into cd_aulas(id,igreja_id,modulo_id,numero,nome) values(:aula,:t,:modulo,1,'Synthetic')"), params)
    c.execute(text("insert into cd_turmas(id,igreja_id,curriculo_id,modulo_id,nome,criada_por) values(:turma,:t,:curriculo,:modulo,'Synthetic',:actor)"), params)
    c.execute(text("insert into cd_calendario(igreja_id,turma_id,modulo_id,aula_id,data,criada_por,atualizada_por) values(:t,:turma,:modulo,:aula,current_date,:actor,:actor)"), params)
    c.execute(text("insert into cd_responsaveis(igreja_id,turma_id,usuario_id,atribuido_por) values(:t,:turma,:actor,:actor)"), params)


def _seed_knowledge(c, tenant, author):
    params = dict(t=tenant, actor=author, doc=uuid4(), version=uuid4(), operation=uuid4())
    c.execute(text("insert into conhecimento_documentos(id,igreja_id,titulo,assunto,responsavel_id,autor_id) values(:doc,:t,'Synthetic','Synthetic',:actor,:actor)"), params)
    c.execute(text("insert into conhecimento_versoes(id,igreja_id,documento_id,conteudo,origem,autor_id) values(:version,:t,:doc,'Synthetic','Synthetic',:actor)"), params)
    c.execute(text('update conhecimento_documentos set rascunho_id=:version where id=:doc'), params)
    c.execute(text("insert into conhecimento_operacoes(igreja_id,id,documento_id,versao_id,ator_id,tipo,fingerprint) values(:t,:operation,:doc,:version,:actor,'criar',repeat('a',64))"), params)


def _register_session(database, admin_id, clerk_user_id):
    now = datetime.now(timezone.utc)
    identity = ClerkIdentity(clerk_user_id, dict(jti=f"synthetic-{uuid4()}", iat=now, exp=now+timedelta(hours=1)))
    clerk = SimpleNamespace(verify_session_token=lambda _: identity)
    with Session(database) as s, s.begin():
        register_session(s, clerk, 'synthetic', s.get(AppUser, admin_id))
    return clerk


def _assert_committed(database, v):
    with database.connect() as c:
        assert c.scalar(text('select count(*) from igrejas where id=:tenant'), v) == 0
        assert c.scalar(text('select count(*) from igrejas where id=:other and dono_id=:other_admin'), v) == 1
        assert c.execute(text('select igreja_id,pessoa_id,clerk_user_id from app_users where id=:admin'), v).one() == (None, None, v['clerk'])
        assert c.scalar(text('select count(*) from platform_admins where app_user_id in (:admin,:other_admin)'), v) == 2
        for table in ('pessoas', 'messages', 'responsabilidades_setor'):
            assert c.scalar(text(f'select count(*) from {table} where igreja_id=:tenant'), v) == 0
            assert c.scalar(text(f'select count(*) from {table} where igreja_id=:other'), v) == 1
        assert c.scalar(text("select count(*) from platform_audit_log where alvo_id=:tenant and acao='tenant_deletion.local_deleted' and actor_id=:other_admin"), v) == 1
        assert c.scalar(text("select count(*) from private_deletion_receipts where igreja_id=:tenant and scope='igreja'"), v) == 1
        assert c.scalar(text('select count(*) from private_deletion_tasks where igreja_id=:tenant'), v) > 0


def test_nominal_platform_delete_preserves_administrators_and_receipts(database, administrative_authorship):
    v = administrative_authorship
    # The requesting platform admin is from the surviving church. The target
    # has a platform identity and official authorship, but no active session.
    clerk = _register_session(database, v['other_admin'], v['other_clerk'])
    other_before = _snapshot(database, v['other'], v['other_admin'])
    team_audit_before = _snapshot(database, v['tenant'], v['admin'])['team_pessoa_eventos']
    assert team_audit_before
    assert _delete(database, v, clerk).deleted_now
    _assert_committed(database, v)
    assert _snapshot(database, v['other'], v['other_admin']) == other_before
    assert _snapshot(database, v['tenant'], v['admin'])['team_pessoa_eventos'] == team_audit_before

    # A fresh session for the detached identity still authorizes console use.
    clerk = _register_session(database, v['admin'], v['clerk'])
    with Session(database) as s:
        assert get_platform_admin('Bearer synthetic', s, clerk).app_user_id == str(v['admin'])


_COMMON_TABLES = (
    'app_users', 'pessoas', 'user_roles', 'conversations', 'messages',
    'responsabilidades_setor', 'cell_report_audio_inputs', 'auth_sessions', 'team_pessoa_eventos',
    'private_deletion_receipts', 'private_deletion_tasks',
    'private_deletion_members', 'private_deletion_dependencies', 'private_deletion_event_fences',
)


def _snapshot(database, tenant, admin, domain_tables=()):
    """Compare full synthetic rows, including references and durable artifacts."""
    predicates = {
        **{table: 'igreja_id = :tenant' for table in (*_COMMON_TABLES, *domain_tables)},
        'igrejas': 'id = :tenant',
        'platform_admins': 'app_user_id = :admin',
        'platform_audit_log': 'alvo_id = :tenant',
    }
    with database.connect() as c:
        return {
            table: c.scalar(text(f"""select jsonb_agg(to_jsonb(r) order by to_jsonb(r)::text)
                from {table} r where {predicate}"""), dict(tenant=tenant, admin=admin))
            for table, predicate in predicates.items()
        }


@pytest.mark.parametrize('dependency', ['session', 'uv', 'cd', 'knowledge'])
def test_nominal_delete_currently_rolls_back_on_unresolved_reference(database, administrative_authorship, dependency):
    """Item 29 (M3) characterization, not a requirement to keep the defect.

    Pending a reviewed correction, a rejected nominal operation must be atomic;
    it must never silently discard session metadata or leave partial receipts.
    Update this characterization when the corresponding dependency is fixed.
    """
    v = administrative_authorship
    if dependency == 'session':
        # Real session registration, then real console authorization of the
        # administrative identity belonging to the church being deleted.
        clerk = _register_session(database, v['admin'], v['clerk'])
        tables = ('auth_sessions',)
    else:
        clerk = _register_session(database, v['other_admin'], v['other_clerk'])
        seeder, tables = {
            'uv': (_seed_uv, ('uv_turmas', 'uv_atividades', 'uv_responsaveis')),
            'cd': (_seed_cd, ('cd_curriculos', 'cd_niveis', 'cd_modulos', 'cd_aulas', 'cd_turmas', 'cd_calendario', 'cd_responsaveis')),
            'knowledge': (_seed_knowledge, ('conhecimento_documentos', 'conhecimento_versoes', 'conhecimento_operacoes')),
        }[dependency]
        with database.begin() as c:
            seeder(c, v['tenant'], v['admin'])
            seeder(c, v['other'], v['other_admin'])
    before = _snapshot(database, v['tenant'], v['admin'], tables)
    other_before = _snapshot(database, v['other'], v['other_admin'], tables)
    with pytest.raises(IntegrityError) as error:
        _delete(database, v, clerk)
    assert error.value.orig.pgcode == '23503'
    assert any(error.value.orig.diag.constraint_name.startswith(table) for table in tables)
    assert _snapshot(database, v['tenant'], v['admin'], tables) == before
    assert _snapshot(database, v['other'], v['other_admin'], tables) == other_before
