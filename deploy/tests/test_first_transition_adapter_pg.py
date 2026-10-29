"""Only the caller-owned loopback first_transition_test DB; never a host/Redis test."""
import contextlib
import io
import os
from pathlib import Path
import runpy
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from first_transition_adapter import (
    LocalDatabase, LocalEvidence, LocalTransition, Refused, baseline_digest, prepare,
)
from initial_transition_files import Journal

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def plan():
    return prepare(ROOT)


@pytest.fixture
def database(plan, tmp_path):
    url = os.environ.get('FIRST_TRANSITION_LOCAL_URL', '')
    nonce = os.environ.get('FIRST_TRANSITION_LOCAL_NONCE', '')
    if not url:
        pytest.skip('requires explicitly owned disposable first_transition_test')
    # Validate endpoint and marker BEFORE the synthetic reset.
    with LocalDatabase(url, nonce):
        pass
    import psycopg2
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    migrations = tmp_path / 'migrations'
    migrations.mkdir()
    (scripts / 'migrate.py').write_bytes(plan.executor)
    for m in plan.migrations:
        (migrations / m.name).write_bytes(m.sql)
    runner = runpy.run_path(str(scripts / 'migrate.py'))
    with psycopg2.connect(url) as connection:
        with connection.cursor() as cur:
            cur.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public')
            for role, bypass in [('anon', False), ('authenticated', False), ('service_role', True)]:
                cur.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,))
                if not cur.fetchone():
                    cur.execute(f"CREATE ROLE {role} NOLOGIN {'BYPASSRLS' if bypass else 'NOBYPASSRLS'}")
            for obj in ('TABLES', 'SEQUENCES', 'FUNCTIONS'):
                cur.execute(f'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON {obj} TO anon,authenticated,service_role')
            cur.execute('CREATE TABLE public.schema_migrations(name text PRIMARY KEY)')
    for name in plan.baseline:
        m = next(m for m in plan.migrations if m.name == name)
        with contextlib.closing(psycopg2.connect(url)) as connection, contextlib.redirect_stdout(io.StringIO()):
            runner['cmd_apply'](connection, name, transactional=not m.concurrent,
                                lock_timeout=0 if m.concurrent else (5000 if name.startswith('20260827_175634_') else 2000))
    # Nonempty synthetic domain and FORCE-RLS data make data-loss mutations observable.
    with contextlib.closing(psycopg2.connect(url)) as seeded:
        with seeded.cursor() as cur:
            cur.execute("""INSERT INTO igrejas(id,nome) VALUES
                ('dddddddd-0000-4000-8000-000000000001','Synthetic restore fixture');
                INSERT INTO pessoas(id,igreja_id,nome,telefone,tipo) VALUES
                ('eeeeeeee-0000-4000-8000-000000000001','dddddddd-0000-4000-8000-000000000001',
                 'Synthetic restore person','550000000009','contato');
                CREATE TABLE public.first_transition_fixture(igreja_id uuid PRIMARY KEY,payload text NOT NULL);
                ALTER TABLE public.first_transition_fixture ENABLE ROW LEVEL SECURITY;
                ALTER TABLE public.first_transition_fixture FORCE ROW LEVEL SECURITY;
                CREATE POLICY tenant_isolation ON public.first_transition_fixture TO authenticated
                    USING (igreja_id=public.current_igreja_id()) WITH CHECK (igreja_id=public.current_igreja_id());
                INSERT INTO public.first_transition_fixture VALUES
                    ('dddddddd-0000-4000-8000-000000000001','fictitious restore payload')""")
        seeded.commit()
    return url, nonce


def evidence(plan, db):
    return LocalEvidence.synthetic(plan.digest, baseline_digest(db.observe()))


def execute_sql(database, sql, params=None, *, autocommit=False):
    import psycopg2
    connection = psycopg2.connect(database[0])
    connection.autocommit = autocommit
    try:
        with connection.cursor() as cur:
            cur.execute(sql, params)
            result = cur.fetchall() if cur.description else None
        if not autocommit:
            connection.commit()
        return result
    finally:
        connection.close()


def test_exact_51_migrations_and_idempotent_replay(plan, database, tmp_path, monkeypatch):
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        receipt = evidence(plan, db)
        result = LocalTransition(plan, db, journal).run(receipt)
        assert result == dict(status='database-verified', ledger=129, production_ready=False,
                              services='simulated-held', host_verified=False, legacy_resume_allowed=False)
        assert not db.observe()['invalid']
        monkeypatch.setattr(db, 'apply', lambda *_: pytest.fail('completed replay must not reapply SQL'))
        assert LocalTransition(plan, db, journal).run(receipt) == result
        assert len(journal.find('done')) == 51
        execute_sql(database, 'DELETE FROM schema_migrations WHERE name=%s', (plan.pending[-1].name,))
        with pytest.raises(Refused, match='ledger-regressed'):
            LocalTransition(plan, db, journal).run(receipt)
    assert execute_sql(database, "SELECT count(*) FROM pg_roles WHERE rolname IN ('private_storage_runtime','private_send_runtime','private_summary_runtime','queue_worker_runtime') AND NOT rolcanlogin") == [(4,)]


def test_unowned_database_refused(database):
    with pytest.raises(Refused):
        with LocalDatabase(database[0], '00000000-0000-0000-0000-000000000000'):
            pytest.fail('must refuse an unowned database')


def test_other_client_and_parallel_controller_refused(database):
    import psycopg2
    with LocalDatabase(*database) as db:
        with psycopg2.connect(database[0]):
            with pytest.raises(Refused, match='other-database-client'):
                db.observe()
        with pytest.raises(Refused):
            with LocalDatabase(*database):
                pytest.fail('advisory lock must refuse parallel execution')


def test_duplicates_refused_without_reconciliation_or_ddl(plan, database, tmp_path):
    execute_sql(database, """INSERT INTO igrejas(id,nome) VALUES ('aaaaaaaa-0000-4000-8000-000000000001','Synthetic');
        INSERT INTO pessoas(id,igreja_id,nome,telefone) VALUES ('bbbbbbbb-0000-4000-8000-000000000001','aaaaaaaa-0000-4000-8000-000000000001','Synthetic','550000000001');
        INSERT INTO app_users(igreja_id,pessoa_id,nome,email) VALUES
        ('aaaaaaaa-0000-4000-8000-000000000001','bbbbbbbb-0000-4000-8000-000000000001','Synthetic A','a@example.test'),
        ('aaaaaaaa-0000-4000-8000-000000000001','bbbbbbbb-0000-4000-8000-000000000001','Synthetic B','b@example.test')""")
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        summary = db.full_preflight(plan, 78)
        assert summary['duplicates'] == 1 and summary['read_only'] is True
        assert 'bbbbbbbb-0000-4000-8000-000000000001' not in str(summary)
        with pytest.raises(Refused, match='aggregate-preflight-finding'):
            LocalTransition(plan, db, journal).run(evidence(plan, db))
        assert journal.last('adapter-ddl-marker') is None
        assert len(db.observe()['ledger']) == 78


def test_stale_backup_receipt_refused_before_marker(plan, database, tmp_path):
    with LocalDatabase(*database) as db:
        receipt = evidence(plan, db)
    execute_sql(database, 'CREATE TABLE public.synthetic_new_object(id integer)')
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused, match='local-evidence-mismatch'):
            LocalTransition(plan, db, journal).run(receipt)
        assert journal.last('adapter-ddl-marker') is None
        assert len(db.observe()['ledger']) == 78


def test_crash_after_commit_adopts_exact_journaled_migration(plan, database, tmp_path, monkeypatch):
    receipt = None
    first = plan.pending[0].name
    calls = []
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        receipt = evidence(plan, db)
        apply = db.apply
        def crash(plan, migration):
            calls.append(migration.name)
            apply(plan, migration)
            raise KeyboardInterrupt()
        monkeypatch.setattr(db, 'apply', crash)
        with pytest.raises(KeyboardInterrupt):
            LocalTransition(plan, db, journal).run(receipt)
        assert len(db.observe()['ledger']) == 79
        assert journal.last('done', 'adapter-migration:' + first) is None
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused, match='explicit-local-retry-required'):
            LocalTransition(plan, db, journal).run(receipt)
        assert LocalTransition(plan, db, journal).run(receipt, retry=True)['ledger'] == 129
        assert journal.last('done', 'adapter-migration:' + first)['recovered'] is True
        assert calls == [first]


def test_failure_before_commit_holds_and_requires_explicit_retry(plan, database, tmp_path, monkeypatch):
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        receipt = evidence(plan, db)
        apply = db.apply
        monkeypatch.setattr(db, 'apply', lambda *_: (_ for _ in ()).throw(Refused('migration-failed')))
        with pytest.raises(Refused, match='migration-failed'):
            LocalTransition(plan, db, journal).run(receipt)
        assert len(db.observe()['ledger']) == 78
        assert journal.last('adapter-ddl-marker')['irrevocable'] is True
        assert journal.last('adapter-failed')['legacy_resume_allowed'] is False
        monkeypatch.setattr(db, 'apply', apply)
        assert LocalTransition(plan, db, journal).run(receipt, retry=True)['ledger'] == 129


def test_invalid_concurrent_index_is_preserved_and_blocks_retry(plan, database, tmp_path, monkeypatch):
    import psycopg2
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        receipt = evidence(plan, db)
        apply = db.apply
        def fail(plan, migration):
            if migration.concurrent:
                execute_sql(database, 'CREATE TABLE public.synthetic_duplicate_index(id integer); INSERT INTO public.synthetic_duplicate_index VALUES (1),(1)')
                with pytest.raises(psycopg2.errors.UniqueViolation):
                    execute_sql(database, 'CREATE UNIQUE INDEX CONCURRENTLY synthetic_invalid ON public.synthetic_duplicate_index(id)', autocommit=True)
                raise Refused('migration-failed')
            apply(plan, migration)
        monkeypatch.setattr(db, 'apply', fail)
        with pytest.raises(Refused, match='migration-failed'):
            LocalTransition(plan, db, journal).run(receipt)
        assert db.observe()['invalid'] == ('synthetic_invalid',)
        assert 78 < len(db.observe()['ledger']) < 129
        with pytest.raises(Refused, match='invalid-index'):
            LocalTransition(plan, db, journal).run(receipt, retry=True)
        assert db.observe()['invalid'] == ('synthetic_invalid',)


@pytest.mark.parametrize(('point', 'backfill_drift'), [
    ('before-intent', False), ('after-intent', False), ('before-commit', False),
    ('after-commit', False), ('before-receipt', False), ('before-intent', True)])
def test_sigkill_recovery_at_migration_boundaries(plan, database, tmp_path, point, backfill_drift):
    import signal
    import subprocess
    with LocalDatabase(*database) as db:
        receipt = evidence(plan, db)
    journal_dir = tmp_path / 'journal'
    script = r'''
import os,signal,sys,runpy
from pathlib import Path
from first_transition_adapter import LocalDatabase,LocalEvidence,LocalTransition,prepare
from initial_transition_files import Journal
plan=prepare(Path(sys.argv[1]))
point=sys.argv[3]
def die():
    os.kill(os.getpid(),signal.SIGKILL)
with LocalDatabase(os.environ['FIRST_TRANSITION_LOCAL_URL'],os.environ['FIRST_TRANSITION_LOCAL_NONCE']) as db, Journal(Path(sys.argv[2])) as journal:
    append=journal.append
    def record(kind,**fields):
        migration=fields.get('step','').startswith('adapter-migration:')
        if migration and ((point=='before-intent' and kind=='intent') or (point=='before-receipt' and kind=='done')):
            die()
        event=append(kind,**fields)
        if migration and point=='after-intent' and kind=='intent':
            die()
        return event
    journal.append=record
    apply=db.apply
    def execute(plan,migration):
        if point=='before-commit':
            import psycopg2
            stage=Path(sys.argv[2])/'transaction-stage'
            (stage/'scripts').mkdir(parents=True)
            (stage/'migrations').mkdir()
            (stage/'scripts/migrate.py').write_bytes(plan.executor)
            (stage/'migrations'/migration.name).write_bytes(migration.sql)
            runner=runpy.run_path(str(stage/'scripts/migrate.py'))
            connection=psycopg2.connect(os.environ['FIRST_TRANSITION_LOCAL_URL'])
            class CommitBarrier:
                @property
                def autocommit(self): return connection.autocommit
                @autocommit.setter
                def autocommit(self,value): connection.autocommit=value
                def cursor(self): return connection.cursor()
                def rollback(self): return connection.rollback()
                def commit(self): die()
            runner['cmd_apply'](CommitBarrier(),migration.name,transactional=True,lock_timeout=2000)
        else:
            apply(plan,migration)
        if point=='after-commit':
            die()
    db.apply=execute
    LocalTransition(plan,db,journal).run(LocalEvidence.synthetic(plan.digest,os.environ['LOCAL_BASELINE_DIGEST']))
'''
    env = dict(PATH='/usr/bin:/bin', PYTHONPATH=str(ROOT / 'deploy'), PYTHON_DOTENV_DISABLED='1',
               PYTHONDONTWRITEBYTECODE='1',
               FIRST_TRANSITION_LOCAL_URL=database[0], FIRST_TRANSITION_LOCAL_NONCE=database[1],
               LOCAL_BASELINE_DIGEST=receipt.baseline_digest)
    result = subprocess.run([sys.executable, '-c', script, str(ROOT), str(journal_dir), point],
                            cwd=tmp_path, env=env, capture_output=True, timeout=30)
    assert result.returncode == -signal.SIGKILL
    committed = point in ('after-commit', 'before-receipt')
    with LocalDatabase(*database) as db, Journal(journal_dir) as journal:
        first = plan.pending[0].name
        assert len(db.observe()['ledger']) == (79 if committed else 78)
        assert journal.last('adapter-failed') is None
        if backfill_drift:
            execute_sql(database, "UPDATE pessoas SET apto_proxima_cd=true WHERE id='eeeeeeee-0000-4000-8000-000000000001'")
            with pytest.raises(Refused, match='pre-ddl-backfill-candidate'):
                LocalTransition(plan, db, journal).run(receipt, retry=True)
            assert len(db.observe()['ledger']) == 78
            execute_sql(database, "UPDATE pessoas SET apto_proxima_cd=false WHERE id='eeeeeeee-0000-4000-8000-000000000001'")
        assert journal.last('done', 'adapter-migration:' + first) is None
        with pytest.raises(Refused, match='explicit-local-retry-required'):
            LocalTransition(plan, db, journal).run(receipt)
        assert LocalTransition(plan, db, journal).run(receipt, retry=True)['ledger'] == 129
        assert journal.last('done', 'adapter-migration:' + first).get('recovered', False) is committed


def test_journal_refuses_another_disposable_identity(plan, database, tmp_path, monkeypatch):
    from uuid import uuid4
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        receipt = evidence(plan, db)
        monkeypatch.setattr(db, 'apply', lambda *_: (_ for _ in ()).throw(Refused('migration-failed')))
        with pytest.raises(Refused):
            LocalTransition(plan, db, journal).run(receipt)
    other_nonce = str(uuid4())
    execute_sql(database, 'COMMENT ON DATABASE first_transition_test IS %s',
                ('igreja12-local-disposable:' + other_nonce,))
    try:
        with LocalDatabase(database[0], other_nonce) as db, Journal(tmp_path / 'journal') as journal:
            with pytest.raises(Refused, match='database-changed'):
                LocalTransition(plan, db, journal).run(receipt, retry=True)
    finally:
        execute_sql(database, 'COMMENT ON DATABASE first_transition_test IS %s',
                    ('igreja12-local-disposable:' + database[1],))


def test_changed_intent_is_refused_before_retry(plan, database, tmp_path, monkeypatch):
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        receipt = evidence(plan, db)
        monkeypatch.setattr(db, 'apply', lambda *_: (_ for _ in ()).throw(Refused('migration-failed')))
        with pytest.raises(Refused):
            LocalTransition(plan, db, journal).run(receipt)
        journal.append('intent', step='adapter-migration:' + plan.pending[0].name, sql_sha256='0' * 64)
        with pytest.raises(Refused, match='migration-intent-changed'):
            LocalTransition(plan, db, journal).run(receipt, retry=True)
        assert len(db.observe()['ledger']) == 78


def test_nonprefix_ledger_is_refused(plan, database, tmp_path, monkeypatch):
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        receipt = evidence(plan, db)
        monkeypatch.setattr(db, 'apply', lambda *_: (_ for _ in ()).throw(Refused('migration-failed')))
        with pytest.raises(Refused):
            LocalTransition(plan, db, journal).run(receipt)
    execute_sql(database, 'INSERT INTO schema_migrations(name) VALUES (%s)', (plan.pending[1].name,))
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused, match='ledger-not-prefix'):
            LocalTransition(plan, db, journal).run(receipt, retry=True)
        assert len(db.observe()['ledger']) == 79


def test_full_preflight_blocks_unsafe_definer_before_first_ddl(plan, database, tmp_path):
    execute_sql(database, """CREATE ROLE first_transition_unsafe_owner NOLOGIN NOBYPASSRLS;
        CREATE FUNCTION public.private_memory_overview(uuid) RETURNS jsonb LANGUAGE sql
        SECURITY DEFINER SET row_security=off AS $$SELECT '{}'::jsonb$$;
        ALTER FUNCTION public.private_memory_overview(uuid) OWNER TO first_transition_unsafe_owner""")
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        receipt = evidence(plan, db)
        with pytest.raises(Refused, match='full-preflight-findings'):
            LocalTransition(plan, db, journal).run(receipt)
        assert len(db.observe()['ledger']) == 78
        assert journal.last('adapter-ddl-marker') is None


def test_full_preflight_reads_catalog_without_calling_definer(plan, database):
    execute_sql(database, """CREATE FUNCTION public.private_memory_overview(uuid) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET row_security=off
        AS $$BEGIN RAISE EXCEPTION 'synthetic function must not run'; END$$""")
    with LocalDatabase(*database) as db:
        result = db.full_preflight(plan, 78)
        assert result['read_only'] is True
        assert result['definer_examined'] == 1
        assert result['definer_findings'] == 0


def test_full_preflight_refuses_role_that_cannot_see_rls_rows(plan, database, tmp_path, monkeypatch):
    import psycopg2
    scripts = tmp_path / 'preflight_scripts'
    scripts.mkdir()
    (scripts / 'migrate.py').write_bytes(plan.executor)
    (scripts / 'release_preflight.py').write_bytes(plan.preflight)
    monkeypatch.syspath_prepend(str(scripts))
    monkeypatch.delitem(sys.modules, 'migrate', raising=False)
    preflight = runpy.run_path(str(scripts / 'release_preflight.py'))
    with contextlib.closing(psycopg2.connect(database[0])) as connection:
        connection.autocommit = True
        with connection.cursor() as cur:
            cur.execute('SET ROLE authenticated')
        with pytest.raises(preflight['PreflightError'], match='role não pode ignorar RLS'):
            preflight['inspect_connection'](connection)


def test_real_synthetic_dump_restore_checks_schema_and_counts(plan, database):
    with LocalDatabase(*database) as db:
        before = db.observe()
        receipt = db.rehearse_backup(plan)
        assert receipt['scope'] == 'synthetic-database-only'
        assert receipt['restore_verified'] is True
        assert receipt['content_verified'] is False
        assert receipt['archive_persisted'] is False
        assert receipt['plan_digest'] == plan.digest
        assert len(receipt['archive_sha256']) == 64
        assert receipt['tables'] > 0
        assert all(version.startswith('17.') for version in receipt['tools'].values())
        assert db.observe() == before
    assert execute_sql(database, "SELECT count(*) FROM pg_database WHERE datname LIKE 'first_transition_restore_%'") == [(0,)]


def test_corrupt_synthetic_archive_is_refused_and_restore_db_removed(plan, database, monkeypatch):
    import subprocess
    run = subprocess.run
    def corrupt(command, **kwargs):
        if str(command[0]).endswith('/pg_restore') and '--version' not in command:
            Path(command[-1]).write_bytes(b'synthetic corrupt archive')
        return run(command, **kwargs)
    monkeypatch.setattr(subprocess, 'run', corrupt)
    with LocalDatabase(*database) as db:
        with pytest.raises(Refused, match='local-restore-failed'):
            db.rehearse_backup(plan)
        assert len(db.observe()['ledger']) == 78
    assert execute_sql(database, "SELECT count(*) FROM pg_database WHERE datname LIKE 'first_transition_restore_%'") == [(0,)]


def test_failed_synthetic_dump_blocks_first_ddl(plan, database, tmp_path, monkeypatch):
    import errno
    import subprocess
    run = subprocess.run
    def full_disk(command, **kwargs):
        if str(command[0]).endswith('/pg_dump') and '--version' not in command:
            raise OSError(errno.ENOSPC, 'synthetic full disk')
        return run(command, **kwargs)
    monkeypatch.setattr(subprocess, 'run', full_disk)
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused, match='local-backup-tool-failed'):
            LocalTransition(plan, db, journal).run(evidence(plan, db))
        assert len(db.observe()['ledger']) == 78
        assert journal.last('adapter-ddl-marker') is None


def test_host_contract_and_real_database_are_bound_end_to_end(plan, database, tmp_path):
    from first_transition_host_contract import LocalHostContract
    from test_first_transition_host_contract import FakeHost
    port = FakeHost()
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        host = LocalHostContract(port, journal)
        contained = host.contain()
        receipt = LocalEvidence.synthetic(plan.digest, baseline_digest(db.observe()),
                                          host_digest=contained['fingerprint'])
        result = LocalTransition(plan, db, journal, host=host).run(receipt)
        assert result['ledger'] == 129 and result['host_verified'] is False
        assert journal.last('adapter-local-restore')['restore_verified'] is True
        assert journal.last('adapter-preflight')['pending'] == 0
        assert all(not state['running'] for state in port.data['services'].values())
        assert not any(operation in ('start', 'restart') for operation, _ in port.calls)


def test_host_drift_after_first_commit_blocks_the_next_migration(plan, database, tmp_path, monkeypatch):
    from first_transition_host_contract import LocalHostContract
    from test_first_transition_host_contract import FakeHost
    port = FakeHost()
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        host = LocalHostContract(port, journal)
        contained = host.contain()
        receipt = LocalEvidence.synthetic(plan.digest, baseline_digest(db.observe()),
                                          host_digest=contained['fingerprint'])
        apply = db.apply
        def drift(plan, migration):
            apply(plan, migration)
            port.data['services']['queue-worker']['restart_count'] += 1
            port.data['services']['queue-worker']['running'] = True
        monkeypatch.setattr(db, 'apply', drift)
        with pytest.raises(Refused, match='local-host-identity-or-support-changed'):
            LocalTransition(plan, db, journal, host=host).run(receipt)
        assert len(db.observe()['ledger']) == 79
        assert journal.last('adapter-failed')['legacy_resume_allowed'] is False


def test_changed_adapter_artifact_manifest_cannot_resume_a_journal(plan, database, tmp_path, monkeypatch):
    from dataclasses import replace
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        receipt = evidence(plan, db)
        monkeypatch.setattr(db, 'apply', lambda *_: (_ for _ in ()).throw(Refused('migration-failed')))
        with pytest.raises(Refused, match='migration-failed'):
            LocalTransition(plan, db, journal).run(receipt)
        assert set(journal.last('adapter-init')['adapter_sources']) == {
            'first_transition_adapter.py', 'first_transition_local_backup.py', 'first_transition_host_contract.py',
            'initial_transition_files.py', 'initial_transition_ops.py', 'release_topology.py'}
        changed = replace(plan, adapter_sources=((plan.adapter_sources[0][0], '0' * 64), *plan.adapter_sources[1:]))
        with pytest.raises(Refused, match='plan-changed'):
            LocalTransition(changed, db, journal).run(receipt, retry=True)
        assert len(db.observe()['ledger']) == 78


@pytest.mark.parametrize('kind', ['index', 'table', 'sequence'])
def test_pending_index_collision_is_refused_before_marker(plan, database, tmp_path, kind):
    index = next(m.indexes[0] for m in plan.pending if m.concurrent)
    command = {'index': f'CREATE INDEX {index} ON public.pessoas(id)',
               'table': f'CREATE TABLE public.{index}(id integer)',
               'sequence': f'CREATE SEQUENCE public.{index}'}[kind]
    execute_sql(database, command)
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        with pytest.raises(Refused, match='concurrent-index-without-ledger'):
            LocalTransition(plan, db, journal).run(evidence(plan, db))
        assert journal.last('adapter-ddl-marker') is None
        assert len(db.observe()['ledger']) == 78


def test_successful_retry_clears_old_failure_for_readonly_replay(plan, database, tmp_path, monkeypatch):
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        receipt = evidence(plan, db)
        apply = db.apply
        monkeypatch.setattr(db, 'apply', lambda *_: (_ for _ in ()).throw(Refused('migration-failed')))
        with pytest.raises(Refused):
            LocalTransition(plan, db, journal).run(receipt)
        monkeypatch.setattr(db, 'apply', apply)
        assert LocalTransition(plan, db, journal).run(receipt, retry=True)['ledger'] == 129
        assert LocalTransition(plan, db, journal).run(receipt)['ledger'] == 129


@pytest.mark.parametrize('candidate', ['aptitude', 'member', 'official-number'])
def test_pre_ddl_backfill_candidates_still_require_zero(plan, database, tmp_path, candidate):
    tenant = 'dddddddd-0000-4000-8000-000000000001'
    person = 'eeeeeeee-0000-4000-8000-000000000001'
    if candidate == 'aptitude':
        execute_sql(database, 'UPDATE pessoas SET apto_proxima_cd=true WHERE id=%s', (person,))
    elif candidate == 'official-number':
        execute_sql(database, 'UPDATE pessoas SET tipo=\'membro\' WHERE id=%s', (person,))
        execute_sql(database, 'INSERT INTO whatsapp_connections(igreja_id,numero) VALUES (%s,%s)', (tenant, '550000000009'))
    else:
        execute_sql(database, """INSERT INTO celulas(id,igreja_id,nome,cobertura_espiritual)
            VALUES ('ffffffff-0000-4000-8000-000000000001',%s,'Synthetic cell','synthetic');
            INSERT INTO celula_membro(igreja_id,celula_id,pessoa_id) VALUES
            (%s,'ffffffff-0000-4000-8000-000000000001',%s);
            UPDATE pessoas SET tipo='contato' WHERE id=%s""", (tenant, tenant, person, person))
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        observed = db.observe()
        if candidate == 'aptitude':
            assert observed['aptitude_backfill'] == 1
        else:
            field = 'membro_por_vinculo' if candidate == 'member' else 'numero_atendimento'
            assert observed['backfills'][field] == 1
        assert observed['duplicates'] == observed['invalid_links'] == 0
        with pytest.raises(Refused, match='pre-ddl-backfill-candidate'):
            LocalTransition(plan, db, journal).run(evidence(plan, db))
        assert journal.last('adapter-ddl-marker') is None
        assert len(db.observe()['ledger']) == 78


def test_valid_destination_aptitude_is_not_a_repeated_pre_ddl_gate(plan, database, tmp_path, monkeypatch):
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        receipt = evidence(plan, db)
        apply = db.apply
        def grant_after_schema(plan, migration):
            apply(plan, migration)
            if migration.name == '20261017_230000_uv_marcos_conclusao.sql':
                # Its uv_origem_aptidao trigger fills 'legado' for later grants.
                execute_sql(database, "UPDATE pessoas SET apto_proxima_cd=true WHERE id='eeeeeeee-0000-4000-8000-000000000001'")
        monkeypatch.setattr(db, 'apply', grant_after_schema)
        assert LocalTransition(plan, db, journal).run(receipt)['ledger'] == 129
        assert db.observe()['aptitude_backfill'] == 1
    assert execute_sql(database, "SELECT origem_aptidao_cd FROM pessoas WHERE id='eeeeeeee-0000-4000-8000-000000000001'") == [('legado',)]


def test_excluding_force_rls_fixture_data_is_detected_on_restore(plan, database, monkeypatch):
    import subprocess
    run = subprocess.run
    def omit_data(command, **kwargs):
        if str(command[0]).endswith('/pg_dump') and '--version' not in command:
            command = [*command, '--exclude-table-data=public.first_transition_fixture']
        return run(command, **kwargs)
    monkeypatch.setattr(subprocess, 'run', omit_data)
    with LocalDatabase(*database) as db:
        with pytest.raises(Refused, match='local-restore-mismatch'):
            db.rehearse_backup(plan)
        assert len(db.observe()['ledger']) == 78
    assert execute_sql(database, "SELECT count(*) FROM pg_database WHERE datname LIKE 'first_transition_restore_%'") == [(0,)]


def test_libpq_hostaddr_environment_cannot_redirect_local_connections(plan, database, monkeypatch):
    monkeypatch.setenv('PGHOSTADDR', '127.0.0.2')
    with LocalDatabase(*database) as db:
        assert db.rehearse_backup(plan)['restore_verified'] is True


@pytest.mark.parametrize('change', ['missing', 'definition'])
def test_completed_index_drift_refuses_replay(plan, database, tmp_path, change):
    index = 'messages_pending_agent_igreja_created_idx'
    with LocalDatabase(*database) as db, Journal(tmp_path / 'journal') as journal:
        receipt = evidence(plan, db)
        LocalTransition(plan, db, journal).run(receipt)
        execute_sql(database, f'DROP INDEX public.{index}')
        if change == 'definition':
            execute_sql(database, f'CREATE INDEX {index} ON public.pessoas(id)')
        with pytest.raises(Refused, match='reviewed-index-(missing|changed)'):
            LocalTransition(plan, db, journal).run(receipt)
        assert len(db.observe()['ledger']) == 129


@pytest.mark.parametrize('changed_owner', [False, True])
def test_restore_comment_failure_cleans_only_claimed_identity(plan, database, monkeypatch, changed_owner):
    import psycopg2
    from psycopg2 import sql
    import first_transition_local_backup as backup
    targets = []
    def fail_comment(connection, target, nonce):
        targets.append(target)
        if changed_owner:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('ALTER DATABASE {} OWNER TO authenticated').format(sql.Identifier(target)))
        raise psycopg2.OperationalError('synthetic comment failure')
    monkeypatch.setattr(backup, 'mark_restore', fail_comment)
    with LocalDatabase(*database) as db:
        code = 'local-restore-ownership-changed' if changed_owner else 'local-backup-database-failed'
        with pytest.raises(Refused, match=code):
            db.rehearse_backup(plan)
        remaining = execute_sql(database, 'SELECT datname FROM pg_database WHERE datname=%s', (targets[0],))
        assert bool(remaining) is changed_owner
        if changed_owner:
            # Fixture-only cleanup of the exact UUID generated in this test.
            with db.conn.cursor() as cursor:
                cursor.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(targets[0])))
