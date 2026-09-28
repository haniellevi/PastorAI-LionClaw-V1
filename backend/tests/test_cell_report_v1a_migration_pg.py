"""V1a SQL/RLS proof on the separate guarded disposable PG17 database."""
from pathlib import Path
import uuid
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.test_s3_migration_exact_pg import exact_s3_database, rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration
_MIGRATIONS = Path(__file__).parents[1] / 'migrations'
_S3 = _MIGRATIONS / '20260927_170000_whatsapp_privilege_actions.sql'
_V1A = _MIGRATIONS / '20260927_190000_cell_report_whatsapp_v1a.sql'
_TABLES = ('cell_report_drafts', 'cell_report_reminder_preferences', 'cell_report_reminders', 'cell_report_ai_daily_budgets', 'cell_report_ai_reservations')


def _apply(engine, sql):
    raw = engine.raw_connection()
    try:
        raw.autocommit = True
        with raw.cursor() as cursor:
            cursor.execute(sql)
    finally:
        raw.close()


def _seed(c, *, worker_state=False):
    p = {k: uuid.uuid4() for k in ('tenant', 'person', 'cell', 'meeting', 'conversation', 'message', 'draft', 'budget', 'reservation', 'reminder')}
    statements = [
        "insert into igrejas(id,status) values(:tenant,'ativa')",
        "insert into pessoas(id,igreja_id,telefone) values(:person,:tenant,'5500000000000')",
        "insert into celulas(id,igreja_id,lider_id) values(:cell,:tenant,:person)",
        'insert into celula_reuniao(id,igreja_id,celula_id) values(:meeting,:tenant,:cell)',
        "insert into conversations(id,igreja_id,pessoa_id,telefone,estado) values(:conversation,:tenant,:person,'5500000000000','ia')",
        "insert into messages(id,igreja_id,conversation_id,direcao,autor,texto) values(:message,:tenant,:conversation,'in','contato','teste sintético')",
        """insert into cell_report_drafts(id,igreja_id,conversation_id,reuniao_id,actor_pessoa_id,source_message_id,state,revision,started_at,expires_at,updated_at)
            values(:draft,:tenant,:conversation,:meeting,:person,:message,'coletando',1,now(),now()+interval '24 hours',now())""",
        'insert into cell_report_reminder_preferences(igreja_id,pessoa_id,disabled_at,updated_at) values(:tenant,:person,now(),now())',
        """insert into cell_report_reminders(id,igreja_id,reuniao_id,leader_pessoa_id,state,due_at,text_sha256,updated_at)
            values(:reminder,:tenant,:meeting,:person,'pendente',now(),repeat('a',64),now())""",
        """insert into cell_report_ai_daily_budgets(id,igreja_id,budget_day,cost_version,reserved_microusd,settled_microusd,updated_at)
            values(:budget,:tenant,current_date,'synthetic-v1',100,0,now())""",
        """insert into cell_report_ai_reservations(id,igreja_id,draft_id,budget_id,call_number,budget_day,cost_version,state,estimated_microusd,created_at)
            values(:reservation,:tenant,:draft,:budget,1,current_date,'synthetic-v1','reservada',100,now())""",
    ]
    for index, statement in enumerate(statements):
        if worker_state and index == 6:
            _worker(c, p['tenant'])
        c.execute(text(statement), p)
    return p


@pytest.fixture
def v1a_sql(exact_s3_database):
    engine = exact_s3_database
    with engine.begin() as c:
        c.exec_driver_sql('create table public.celula_reuniao(id uuid primary key, igreja_id uuid not null references igrejas(id), celula_id uuid not null references celulas(id));')
    _apply(engine, _S3.read_text())
    _apply(engine, _V1A.read_text())
    with engine.begin() as c:
        a, b = _seed(c), _seed(c)
    return engine, a, b


def _worker(c, tenant, *, subject=''):
    c.exec_driver_sql('set local role authenticated')
    c.execute(text("select set_config('app.tenant_igreja_id',:v,true)"), {'v': str(tenant)})
    c.execute(text("select set_config('request.jwt.claims','',true)"))
    c.execute(text("select set_config('request.jwt.claim.sub',:v,true)"), {'v': subject})


def test_v1a_sql_second_application_preserves_rows_and_oids(v1a_sql):
    engine, _, _ = v1a_sql
    with engine.connect() as c:
        before = {t: c.execute(text('select cast(:t as regclass)::oid'), {'t': t}).scalar_one() for t in _TABLES}
    with engine.begin() as c:
        for table in _TABLES:
            c.exec_driver_sql(f'grant delete on {table} to authenticated')
    _apply(engine, _V1A.read_text())
    with engine.connect() as c:
        for table in _TABLES:
            assert not c.execute(text("select has_table_privilege('authenticated',:t,'DELETE')"), {'t': table}).scalar_one()
            assert c.execute(text('select cast(:t as regclass)::oid'), {'t': table}).scalar_one() == before[table]
            assert c.exec_driver_sql(f'select count(*) from {table}').scalar_one() == 2
            assert c.execute(text('select relrowsecurity and relforcerowsecurity from pg_class where oid=cast(:t as regclass)'), {'t': table}).scalar_one()
            for role in ('anon', 'agent_runtime'):
                assert not c.execute(text("select has_table_privilege(:r,:t,'SELECT')"), {'r': role, 't': table}).scalar_one()


@pytest.mark.parametrize('table', _TABLES)
def test_v1a_worker_cannot_read_or_update_other_tenant(v1a_sql, table):
    engine, a, b = v1a_sql
    with engine.begin() as c:
        _worker(c, a['tenant'])
        assert c.exec_driver_sql(f'select count(*) from {table}').scalar_one() == 1
        assert c.execute(text(f'update {table} set igreja_id=:t where igreja_id=:t'), {'t': b['tenant']}).rowcount == 0
        assert c.execute(text(f'select count(*) from {table} where igreja_id=:t'), {'t': b['tenant']}).scalar_one() == 0


@pytest.mark.parametrize('table', _TABLES)
def test_v1a_panel_identity_cannot_read_or_update_private_worker_state(v1a_sql, table):
    engine, a, _ = v1a_sql
    with engine.begin() as c:
        _worker(c, a['tenant'], subject='clerk-synthetic')
        assert c.exec_driver_sql(f'select count(*) from {table}').scalar_one() == 0
        assert c.execute(text(f'update {table} set igreja_id=:t where igreja_id=:t'), {'t': a['tenant']}).rowcount == 0


@pytest.mark.parametrize('table,key', [('cell_report_drafts', 'draft'), ('cell_report_reminders', 'reminder')])
def test_v1a_meeting_reference_cannot_cross_tenants(v1a_sql, table, key):
    engine, a, b = v1a_sql
    with pytest.raises(DBAPIError) as err:
        with engine.begin() as c:
            _worker(c, a['tenant'])
            c.execute(text(f'update {table} set reuniao_id=:meeting where id=:id'), {'meeting': b['meeting'], 'id': a[key]})
    assert err.value.orig.pgcode == '23503'


@pytest.mark.parametrize('subject,other_tenant', [('clerk-synthetic', False), ('', True)])
def test_v1a_write_policy_denies_panel_and_other_tenant(v1a_sql, subject, other_tenant):
    engine, a, b = v1a_sql
    with pytest.raises(DBAPIError) as err:
        with engine.begin() as c:
            _worker(c, a['tenant'], subject=subject)
            c.execute(text("""insert into cell_report_ai_daily_budgets(igreja_id,budget_day,cost_version,reserved_microusd,settled_microusd,updated_at)
                values(:tenant,current_date+1,'synthetic-v1',0,0,now())"""), {'tenant': b['tenant'] if other_tenant else a['tenant']})
    assert err.value.orig.pgcode == '42501'


def test_v1a_worker_inserts_and_updates_all_five_private_relations(v1a_sql):
    engine, _, _ = v1a_sql
    with engine.begin() as c:
        own = _seed(c, worker_state=True)
        for table in _TABLES:
            assert c.execute(text(f'select count(*) from {table} where igreja_id=:t'), {'t': own['tenant']}).scalar_one() == 1
            assert c.execute(text(f'update {table} set igreja_id=:t where igreja_id=:t'), {'t': own['tenant']}).rowcount == 1


@pytest.mark.parametrize('table', _TABLES)
def test_v1a_delete_is_denied_even_for_the_own_tenant(v1a_sql, table):
    engine, a, b = v1a_sql
    for tenant in (a['tenant'], b['tenant']):
        with pytest.raises(DBAPIError) as err:
            with engine.begin() as c:
                _worker(c, a['tenant'])
                c.execute(text(f'delete from {table} where igreja_id=:t'), {'t': tenant})
        assert err.value.orig.pgcode == '42501'


def _report_proposal(c, p, *, state='executada', meeting=None):
    ids = {key: uuid.uuid4() for key in ('proposal', 'user', 'conversation', 'source')}
    params = dict(p, **ids, state=state, target=meeting or p['meeting'])
    c.execute(text("insert into app_users(id,igreja_id,pessoa_id,status) values(:user,:tenant,:person,'ativo')"), params)
    c.execute(text("insert into conversations(id,igreja_id,pessoa_id,telefone,estado) values(:conversation,:tenant,:person,'5500000000000','ia')"), params)
    c.execute(text("insert into messages(id,igreja_id,conversation_id,direcao,autor,texto) values(:source,:tenant,:conversation,'in','contato','teste sintético')"), params)
    c.execute(text("""insert into agent_action_proposals(
        id,igreja_id,conversation_id,actor_pessoa_id,actor_app_user_id,
        source_message_id,action,target_kind,target_id,arguments_json,
        arguments_sha256,scope_fingerprint,summary_sha256,state)
        values(:proposal,:tenant,:conversation,:person,:user,:source,
        'enviar_relatorio_celula','reuniao',:target,'{}'::jsonb,
        repeat('a',64),repeat('b',64),repeat('c',64),:state)"""), params)
    return ids['proposal']


def test_report_effect_uniqueness_rejects_replay_after_different_proposal(v1a_sql):
    engine, a, b = v1a_sql
    with engine.begin() as c:
        for state in ('cancelada', 'expirada', 'rejeitada'):
            _report_proposal(c, a, state=state)
        original = _report_proposal(c, a)
        # A distinct meeting and tenant are independent effects.
        other = uuid.uuid4()
        c.execute(text('insert into celula_reuniao(id,igreja_id,celula_id) values(:id,:tenant,:cell)'), dict(a, id=other))
        _report_proposal(c, a, meeting=other)
        _report_proposal(c, b)
    with pytest.raises(DBAPIError) as err:
        with engine.begin() as c:
            _report_proposal(c, a)
    assert err.value.orig.pgcode == '23505'
    with engine.connect() as c:
        ids = c.execute(text("select id from agent_action_proposals where igreja_id=:tenant and target_id=:meeting and state='executada'"), a).scalars().all()
        assert ids == [original]


def test_report_effect_unique_index_serializes_different_proposal_transactions(v1a_sql):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    engine, a, _ = v1a_sql
    with engine.begin() as c:
        proposals = [_report_proposal(c, a, state='preparada') for _ in range(2)]
    barrier = threading.Barrier(2)
    def execute(proposal):
        try:
            with engine.begin() as c:
                _worker(c, a['tenant'])
                c.exec_driver_sql("set local statement_timeout='5s'")
                barrier.wait(timeout=5)
                # Deliberately bypass all application row locks and guards.
                c.execute(text("update agent_action_proposals set state='executada' where id=:id"), {'id': proposal})
            return 'committed'
        except DBAPIError as err:
            return err.orig.pgcode
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, proposals))
    assert sorted(results) == ['23505', 'committed']
    with engine.connect() as c:
        assert c.execute(text("select count(*) from agent_action_proposals where igreja_id=:tenant and target_id=:meeting and state='executada'"), a).scalar_one() == 1


@pytest.mark.parametrize('mismatch', ('keys', 'predicate'))
def test_v1a_reapply_rejects_an_incompatible_same_name_effect_index(v1a_sql, mismatch):
    engine, _, _ = v1a_sql
    index = 'agent_action_proposals_v1a_one_executed_meeting_idx'
    keys = 'id' if mismatch == 'keys' else 'igreja_id,target_id,action'
    operator = 'or' if mismatch == 'predicate' else 'and'
    with engine.begin() as c:
        c.exec_driver_sql(f'drop index {index}')
        c.exec_driver_sql(f"create unique index {index} on agent_action_proposals ({keys}) where action='enviar_relatorio_celula' {operator} state='executada'")
    import psycopg2
    with pytest.raises(psycopg2.Error, match='índice único V1a') as err:
        _apply(engine, _V1A.read_text())
    assert err.value.pgcode == 'P0001'
