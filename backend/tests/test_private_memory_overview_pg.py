"""Real PG17, full migrations, web auth and NOBYPASSRLS; synthetic data only."""
import datetime as dt
import os
import subprocess
import sys
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.services.clerk import get_clerk_client
from app.services.private_memory_overview import memory_overview
from tests.conftest import FakeClerk
from tests.test_operational_usage import db, operational_database, rls_database_url, IGREJA_A, IGREJA_B  # noqa: F401

pytestmark = pytest.mark.rls_integration
PATH = '/operations/private-memory'
MIGRATION = '20261028_100000_private_memory_overview.sql'
INDEX_MIGRATIONS = (
    '20261028_100001_private_erasure_requests_overview_idx.sql',
    '20261028_100002_private_resume_delivered_overview_idx.sql',
)


@pytest.fixture
def client(app, db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk(clerk_user_id='synthetic')
    return TestClient(app, headers={'Authorization': 'Bearer synthetic'})


@pytest.fixture
def inventory(db):
    now = db.scalar(text('select now()'))
    db.execute(text('reset role'))
    db.execute(text("insert into app_users(igreja_id,clerk_user_id,nome,email,status) values(:t,'synthetic-b','Synthetic B','b@example.invalid','ativo')"), dict(t=IGREJA_B))
    db.execute(text("insert into user_roles(igreja_id,user_id,papel) select igreja_id,id,'admin' from app_users where clerk_user_id='synthetic-b'"))
    for tenant in (IGREJA_A, IGREJA_B):
        people = []
        for state, task_state in zip(('available','corrected','suspended','incorrect'), ('queued','running','done','refused')):
            person, conv = uuid4(), uuid4()
            people.append(person)
            db.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:p,:t,'SYNTHETIC_PRIVATE_NAME',:phone)"), dict(p=person,t=tenant,phone=f'550000000000{len(people)}'))
            db.execute(text("insert into conversations(id,igreja_id,pessoa_id,telefone) values(:c,:t,:p,'550000000000')"), dict(c=conv,t=tenant,p=person))
            # Only delivered resume responses count; pending, failed and ordinary
            # replies remain outside the metric. No agent is activated.
            for reply_state, kind in (('ia','private_resume'),('ia_pendente','private_resume'),('ia_falhou','private_resume'),('ia','clarify')):
                db.execute(text("""insert into messages(igreja_id,conversation_id,direcao,autor,texto,agent_reply_state,agent_privilege_context)
                    values(:t,:c,'out','ia','SYNTHETIC_PRIVATE_TEXT',:s,jsonb_build_object('kind',cast(:kind as text)))"""), dict(t=tenant,c=conv,s=reply_state,kind=kind))
            db.execute(text("""insert into private_conversation_summaries
                (igreja_id,conversation_id,pessoa_id,source_revision,deletion_generation,state,summary)
                values(:t,:c,:p,0,0,:s,'SYNTHETIC_PRIVATE_SUMMARY')"""), dict(t=tenant,c=conv,p=person,s=state))
            db.execute(text("""insert into private_summary_tasks(igreja_id,conversation_id,pessoa_id,source_revision,deletion_generation,state)
                values(:t,:c,:p,0,0,:s)"""), dict(t=tenant,c=conv,p=person,s=task_state))
        ages = [-1, 0, 86399, 86400, 259200, 259201] if tenant == IGREJA_A else [864000]
        for index, seconds in enumerate(ages):
            db.execute(text("""insert into private_erasure_requests(igreja_id,pessoa_id,conversation_id,inbound_id,created_at)
                values(:t,:p,:c,:m,:at)"""), dict(t=tenant,p=people[0] if index == 0 else uuid4(),c=uuid4(),m=uuid4(),at=now-dt.timedelta(seconds=seconds)))
        for state in ('aprovado', 'recusado'):
            receipt = uuid4() if state == 'aprovado' else None
            actor = db.scalar(text('select id from app_users where igreja_id=:t'), dict(t=tenant))
            db.execute(text("""insert into private_erasure_requests(igreja_id,pessoa_id,conversation_id,inbound_id,state,decided_at,decided_by,receipt_id)
                values(:t,:p,:c,:m,:s,:at,:actor,:receipt)"""), dict(t=tenant,p=uuid4(),c=uuid4(),m=uuid4(),s=state,at=now,actor=actor,receipt=receipt))
            if receipt:
                db.execute(text("insert into private_deletion_receipts(id,igreja_id,scope,target_id,generation,counts,operation_id) values(:r,:t,'pessoa',:p,1,'{}',:op)"), dict(r=receipt,t=tenant,p=uuid4(),op=uuid4()))
                for cleanup_state in ('pendente','concluida'):
                    db.execute(text("""insert into private_deletion_tasks(igreja_id,receipt_id,source_id,storage_path,state)
                        values(:t,:r,:source,:path,:s)"""), dict(t=tenant,r=receipt,source=uuid4(),s=cleanup_state,path=f'{tenant}/synthetic' if cleanup_state == 'pendente' else None))
    db.execute(text('set local role authenticated'))


def test_inventory_boundaries_and_payload_absence(db, inventory, client):
    assert db.scalar(text('select not rolsuper and not rolbypassrls from pg_roles where rolname=current_user'))
    response = client.get(PATH, params={'igreja_id': IGREJA_B})
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'private, no-store'
    result = response.json()
    assert result == {
        'pedidos_exclusao': {'pendentes': 6, 'vencidos': 0, 'prazo_dias': 15, 'prazo_versao': 'v1', 'atendidos': 1, 'recusados': 1,
            'mais_antigo_segundos': 259201,
            'faixas_idade': {'menos_24h': 3, 'de_1_a_3_dias': 2, 'mais_3_dias': 1}},
        'resumos_ativos': 1, 'retomadas_entregues': 4,
        'tarefas_resumo': {'queued': 1, 'running': 1, 'done': 1, 'refused': 1},
        'limpezas_privadas': {'pendente': 1, 'concluida': 1},
    }
    assert 'SYNTHETIC_PRIVATE' not in response.text
    assert IGREJA_A not in response.text and IGREJA_B not in response.text
    # Summary tasks remain worker-only. Cleanup retains its existing admin read.
    assert db.scalar(text('select count(*) from private_summary_tasks')) == 0
    assert db.scalar(text('select count(*) from private_deletion_tasks')) == 2
    assert db.scalar(text('select count(*) from private_deletion_tasks where igreja_id=:b'), dict(b=IGREJA_B)) == 0
    assert db.scalar(text('select count(*) from private_erasure_requests where igreja_id=:b'), dict(b=IGREJA_B)) == 0


def test_empty_is_zero_with_no_oldest_age(db, client):
    response = client.get(PATH)
    assert response.status_code == 200
    result = response.json()
    assert result['pedidos_exclusao'] == {'pendentes': 0, 'vencidos': 0, 'prazo_dias': 15, 'prazo_versao': 'v1', 'atendidos': 0, 'recusados': 0,
        'mais_antigo_segundos': None, 'faixas_idade': {'menos_24h': 0, 'de_1_a_3_dias': 0, 'mais_3_dias': 0}}
    assert result['resumos_ativos'] == result['retomadas_entregues'] == 0
    assert sum(result['tarefas_resumo'].values()) == sum(result['limpezas_privadas'].values()) == 0


def test_b_admin_sees_only_b_and_cannot_pass_a(db, inventory, app, client):
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk(clerk_user_id='synthetic-b')
    # An independent request would have no tenant GUC from the earlier fixture.
    db.execute(text("select set_config('app.tenant_igreja_id','',true)"))
    response = client.get(PATH, params={'igreja_id': IGREJA_A})
    assert response.status_code == 200, response.text
    assert response.json()['pedidos_exclusao']['pendentes'] == 1
    assert response.json()['pedidos_exclusao']['mais_antigo_segundos'] == 864000
    with pytest.raises(DBAPIError) as error, db.begin_nested():
        db.scalar(text('select private_memory_overview(:t)'), dict(t=IGREJA_A))
    assert error.value.orig.pgcode == '42501'


@pytest.mark.parametrize('status', [None, 'ativo', 'convidado', 'revogado'])
def test_private_memory_requires_explicit_active_status(db, inventory, client, app, status):
    db.execute(text('reset role'))
    actor = db.scalar(text("update app_users set status=:s where clerk_user_id='synthetic' returning id"), dict(s=status))
    db.execute(text('set local role authenticated'))
    response = client.get(PATH)
    assert response.status_code == (200 if status == 'ativo' else 403)
    if response.status_code == 200:
        assert response.json()['pedidos_exclusao']['pendentes'] == 6
    else:
        with pytest.raises(DBAPIError) as error, db.begin_nested():
            db.scalar(text('select private_memory_overview(:t)'), dict(t=IGREJA_A))
        assert error.value.orig.pgcode == '42501'
    # A stale identity must also be rejected by require_active_admin itself.
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        app_user_id=str(actor),clerk_user_id='synthetic',igreja_id=IGREJA_A,
        nome='Synthetic',email='synthetic@example.invalid',roles=frozenset({'admin'}))
    assert client.get(PATH).status_code == response.status_code


@pytest.mark.parametrize('role', ['pastor', 'lider_g12', 'lider_celula', 'operador', 'membro', None])
def test_web_and_sql_refuse_non_admin_even_with_stale_claims(db, client, app, role):
    db.execute(text('reset role'))
    actor = db.scalar(text("select id from app_users where clerk_user_id='synthetic'"))
    db.execute(text('delete from user_roles where user_id=:id'), dict(id=actor))
    if role:
        db.execute(text('insert into user_roles(igreja_id,user_id,papel) values(:t,:id,:r)'), dict(t=IGREJA_A,id=actor,r=role))
    db.execute(text('set local role authenticated'))
    assert client.get(PATH).status_code == 403
    # Simulate a stale CurrentUser: SQL still revalidates the actual role.
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        app_user_id=str(actor),clerk_user_id='synthetic',igreja_id=IGREJA_A,
        nome='Synthetic',email='synthetic@example.invalid',roles=frozenset({'admin'}))
    savepoint = db.begin_nested()
    try:
        assert client.get(PATH).status_code == 403
    finally:
        savepoint.rollback()
    with pytest.raises(DBAPIError) as error, db.begin_nested():
        db.scalar(text('select private_memory_overview(:t)'), dict(t=IGREJA_A))
    assert error.value.orig.pgcode == '42501'


def test_archived_binding_denied(db, client):
    db.execute(text('reset role'))
    person = uuid4()
    db.execute(text("insert into pessoas(id,igreja_id,nome,telefone,arquivada_em) values(:p,:t,'Synthetic archived','5500000000099',now())"), dict(p=person,t=IGREJA_A))
    db.execute(text("update app_users set pessoa_id=:p where clerk_user_id='synthetic'"), dict(p=person))
    db.execute(text('set local role authenticated'))
    assert client.get(PATH).status_code == 403


def test_requires_web_identity(db, client):
    assert client.get(PATH, headers={'Authorization': ''}).status_code == 401
    db.execute(text("select set_config('request.jwt.claims','',true),set_config('request.jwt.claim.sub','',true)"))
    with pytest.raises(DBAPIError), db.begin_nested():
        db.scalar(text('select private_memory_overview(:t)'), dict(t=IGREJA_A))


def test_forged_tenant_context_is_denied(db, inventory):
    db.execute(text("select set_config('app.tenant_igreja_id',:t,true)"), dict(t=IGREJA_B))
    with pytest.raises(DBAPIError) as error, db.begin_nested():
        db.scalar(text('select private_memory_overview(:t)'), dict(t=IGREJA_B))
    assert error.value.orig.pgcode == '42501'


def test_future_pending_age_is_clamped_to_zero(db, client):
    db.execute(text('reset role'))
    db.execute(text("""insert into private_erasure_requests(igreja_id,pessoa_id,conversation_id,inbound_id,created_at)
        values(:t,:p,:c,:m,now()+interval '1 hour')"""), dict(t=IGREJA_A,p=uuid4(),c=uuid4(),m=uuid4()))
    db.execute(text('set local role authenticated'))
    result = client.get(PATH).json()['pedidos_exclusao']
    assert result['pendentes'] == result['faixas_idade']['menos_24h'] == 1
    assert result['mais_antigo_segundos'] == 0
    assert result['vencidos'] == 0


def test_sla_count_uses_versioned_fifteen_day_deadline_and_tenant_scope(db, inventory, client):
    db.execute(text('reset role'))
    for tenant, age in ((IGREJA_A, 16), (IGREJA_A, 14), (IGREJA_B, 20)):
        db.execute(text("""insert into private_erasure_requests(igreja_id,pessoa_id,conversation_id,inbound_id,created_at)
            values(:t,:p,:c,:m,now()-make_interval(days=>:age))"""),
            dict(t=tenant,p=uuid4(),c=uuid4(),m=uuid4(),age=age))
    db.execute(text('set local role authenticated'))
    response = client.get(PATH)
    assert response.status_code == 200, response.text
    assert response.json()['pedidos_exclusao']['vencidos'] == 1
    assert response.json()['pedidos_exclusao']['prazo_dias'] == 15


def test_wrong_definer_owner_fails_instead_of_reporting_filtered_zero(db):
    db.execute(text('reset role'))
    db.execute(text('create role memory6b_test_owner nologin nosuperuser nobypassrls inherit'))
    db.execute(text('grant authenticated to memory6b_test_owner'))
    db.execute(text('alter function private_memory_overview(uuid) owner to memory6b_test_owner'))
    db.execute(text('set local role authenticated'))
    with pytest.raises(DBAPIError) as error, db.begin_nested():
        db.scalar(text('select private_memory_overview(:t)'), dict(t=IGREJA_A))
    assert error.value.orig.pgcode == '42501'
    assert 'row-level security' in str(error.value.orig)


def test_function_acl_rls_and_indexes(db):
    for role in ('anon', 'service_role'):
        assert db.scalar(text("select has_function_privilege(:r,'private_memory_overview(uuid)','execute')"), dict(r=role)) is False
    for table in ('private_erasure_requests','private_conversation_summaries','private_summary_tasks','private_deletion_tasks','messages'):
        assert db.scalar(text('select relrowsecurity and relforcerowsecurity from pg_class where oid=cast(:t as regclass)'), dict(t=table))
    for index in ('private_erasure_requests_overview_idx','private_resume_delivered_overview_idx'):
        assert db.scalar(text('select indisvalid from pg_index where indexrelid=cast(:i as regclass)'), dict(i=index))
    assert db.scalar(text("select proconfig from pg_proc where oid='private_memory_overview(uuid)'::regprocedure")) == ['search_path=pg_catalog, public', 'row_security=off']


def test_rollback_and_accumulated_upgrade_keep_inventory(db, inventory, rls_database_url):
    """Rollback, upgrade and replay via migrate.py preserve existing inventory."""
    from scripts import migrate
    db.execute(text('reset role'))
    db.execute(text("update private_erasure_requests set created_at=now()-interval '2 days' where state='pendente'"))
    db.execute(text('set local role authenticated'))
    before = memory_overview(db, UUID(IGREJA_A))
    # Other connections cannot see this test transaction. Commit the synthetic
    # seed only for this upgrade proof; the module fixture resets the database.
    db.commit()
    engine = db.get_bind()
    with engine.begin() as c:
        c.exec_driver_sql('drop function public.private_memory_overview(uuid)')
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as c:
        c.exec_driver_sql('drop index concurrently if exists public.private_resume_delivered_overview_idx')
        c.exec_driver_sql('drop index concurrently if exists public.private_erasure_requests_overview_idx')
    for _ in range(2):
        # The second pass keeps all objects, exercising CREATE OR REPLACE and
        # IF NOT EXISTS after a missing ledger entry (concurrent DDL recovery).
        with engine.begin() as c:
            for name in (MIGRATION, *INDEX_MIGRATIONS):
                c.execute(text('delete from schema_migrations where name=:n'), dict(n=name))
        for name in (MIGRATION, *INDEX_MIGRATIONS):
            cmd = [sys.executable, str(migrate.__file__), 'apply', name, '--yes']
            if name in INDEX_MIGRATIONS:
                cmd.append('--no-transaction')
            result = subprocess.run(cmd,
                env=dict(os.environ, MIGRATION_DATABASE_URL=rls_database_url.replace('postgresql+psycopg2:', 'postgresql:')),
                capture_output=True, text=True)
            assert result.returncode == 0, f'{name}: {result.stderr}'
        db.execute(text('set local role authenticated'))
        db.execute(text("select set_config('app.tenant_igreja_id',:t,true),set_config('request.jwt.claim.sub','synthetic',true)"), dict(t=IGREJA_A))
        after = memory_overview(db, UUID(IGREJA_A))
        assert after.pedidos_exclusao.mais_antigo_segundos >= before.pedidos_exclusao.mais_antigo_segundos
        exclude_age = {'pedidos_exclusao': {'mais_antigo_segundos'}}
        assert after.model_dump(exclude=exclude_age) == before.model_dump(exclude=exclude_age)
        test_function_acl_rls_and_indexes(db)
        db.rollback()
    # The request ledger intentionally survives church deletion; remove only
    # these synthetic committed audit rows so later tests stay independent.
    with engine.begin() as c:
        c.exec_driver_sql('delete from private_erasure_requests; delete from private_deletion_tasks; delete from private_deletion_receipts')
