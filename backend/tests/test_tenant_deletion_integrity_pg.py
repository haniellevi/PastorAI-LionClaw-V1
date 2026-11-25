"""Nominal platform deletion with administrative authors on the full active schema."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AppUser
from app.db.tenant_session import mark_cross_tenant
from app.deps import get_platform_admin
from app.services.auth_sessions import register_session
from app.services.clerk import ClerkIdentity
from app.services.tenant_deletion import TenantDeletionActor, delete_tenant_locally, reset_all_tenants
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


@pytest.fixture
def administrative_requests(database, administrative_authorship):
    """Existing legitimate pending requests and their inbounds in both churches."""
    v = administrative_authorship
    with database.begin() as c:
        other_inbound = c.scalar(text('select id from messages where conversation_id=:conv3'), v)
        for tenant, person, conv, inbound in (
            (v['tenant'], v['person'], v['conv'], v['message']),
            (v['other'], v['person3'], v['conv3'], other_inbound),
        ):
            params = dict(t=tenant, p=person, c=conv, m=inbound, r=uuid4())
            c.execute(text("""insert into private_erasure_requests
                (id,igreja_id,pessoa_id,conversation_id,inbound_id)
                values(:r,:t,:p,:c,:m)"""), params)
            c.execute(text("""insert into private_erasure_request_inbounds
                (igreja_id,inbound_id,request_id) values(:t,:m,:r)"""), params)
    return v


def _receipt_event(executor, tenant, actor_id, actor_email, execution_host=None):
    params = dict(tenant=tenant)
    receipt_id = executor.execute(text("""select id from private_deletion_receipts
        where igreja_id=:tenant and scope='igreja' and target_id=:tenant and operation_id=:tenant"""), params).scalar_one()
    event = executor.execute(text("""select id,actor_id,actor_email,alvo_tipo,detalhe
        from platform_audit_log where alvo_id=:tenant and acao='tenant_deletion.private_receipt_linked'"""), params).one()
    detail = dict(version=1, receipt_id=str(receipt_id))
    if execution_host is not None:
        detail['execution_host'] = execution_host
    assert (event.actor_id, event.actor_email, event.alvo_tipo, event.detalhe) == (actor_id, actor_email, 'igreja', detail)
    return event.id, receipt_id


def test_nominal_platform_delete_preserves_administrators_and_receipts(database, administrative_requests):
    v = administrative_requests
    # The requesting platform admin is from the surviving church. The target
    # has a platform identity and official authorship, but no active session.
    clerk = _register_session(database, v['other_admin'], v['other_clerk'])
    other_before = _snapshot(database, v['other'], v['other_admin'])
    prior = _snapshot(database, v['tenant'], v['admin'])
    assert prior['team_pessoa_eventos'] and prior['private_erasure_requests'] and prior['private_erasure_request_inbounds']
    assert _delete(database, v, clerk).deleted_now
    _assert_committed(database, v)
    assert _snapshot(database, v['other'], v['other_admin']) == other_before
    after = _snapshot(database, v['tenant'], v['admin'])
    for table in ('team_pessoa_eventos', 'private_erasure_requests', 'private_erasure_request_inbounds'):
        assert after[table] == prior[table]
    with database.connect() as c:
        event = _receipt_event(c, v['tenant'], v['other_admin'], 'other@example.invalid')
    retry = _delete(database, v, clerk)
    assert not retry.deleted_now
    with database.connect() as c:
        assert _receipt_event(c, v['tenant'], v['other_admin'], 'other@example.invalid') == event
    assert _snapshot(database, v['tenant'], v['admin']) == after

    # A fresh session for the detached identity still authorizes console use.
    clerk = _register_session(database, v['admin'], v['clerk'])
    with Session(database) as s:
        assert get_platform_admin('Bearer synthetic', s, clerk).app_user_id == str(v['admin'])


_COMMON_TABLES = (
    'app_users', 'pessoas', 'user_roles', 'conversations', 'messages',
    'responsabilidades_setor', 'cell_report_audio_inputs', 'auth_sessions', 'team_pessoa_eventos',
    'private_deletion_receipts', 'private_deletion_tasks',
    'private_deletion_members', 'private_deletion_dependencies', 'private_deletion_event_fences',
    'private_erasure_requests', 'private_erasure_request_inbounds',
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


@pytest.mark.parametrize('commit', [True, False], ids=['commit', 'rollback'])
def test_integral_reset_receipt_events_share_one_transaction(database, administrative_requests, commit):
    v = administrative_requests
    pairs = ((v['tenant'], v['admin']), (v['other'], v['other_admin']))
    before = {tenant: _snapshot(database, tenant, admin) for tenant, admin in pairs}
    actor = TenantDeletionActor(None, 'reset_tudo', 'synthetic-local')
    with Session(database) as s:
        mark_cross_tenant(s, source='synthetic_nominal_reset_receipts')
        result = reset_all_tenants(s, actor)
        assert result.igrejas_deleted == 2
        events = {tenant: _receipt_event(s, tenant, None, actor.email, actor.execution_host)
                  for tenant, _ in pairs}
        # Neither church nor its event/receipt is committed separately.
        for tenant, admin in pairs:
            assert _snapshot(database, tenant, admin) == before[tenant]
        if commit:
            s.commit()
        else:
            s.rollback()
    if not commit:
        for tenant, admin in pairs:
            assert _snapshot(database, tenant, admin) == before[tenant]
        return
    for tenant, admin in pairs:
        with database.connect() as c:
            assert _receipt_event(c, tenant, None, actor.email, actor.execution_host) == events[tenant]
            assert c.scalar(text('select count(*) from igrejas where id=:t'), dict(t=tenant)) == 0
            assert c.scalar(text('select count(*) from app_users where id=:u and igreja_id is null'), dict(u=admin)) == 1
        after = _snapshot(database, tenant, admin)
        for table in ('team_pessoa_eventos', 'private_erasure_requests', 'private_erasure_request_inbounds'):
            assert after[table] == before[tenant][table]
    after = {tenant: _snapshot(database, tenant, admin) for tenant, admin in pairs}
    with Session(database) as s, s.begin():
        mark_cross_tenant(s, source='synthetic_nominal_reset_receipts_retry')
        retry = reset_all_tenants(s, actor)
        assert retry.igrejas_deleted == 0
        assert retry.pending_tasks == result.pending_tasks
    for tenant, admin in pairs:
        assert _snapshot(database, tenant, admin) == after[tenant]
