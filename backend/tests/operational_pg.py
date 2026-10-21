"""Dedicated synthetic PG, real active migration chain through the runner."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@pytest.fixture(scope='module')
def rls_database_url():
    from tests.conftest_rls import assert_disposable_database
    url = os.environ['OPERATIONAL_TEST_DATABASE_URL']
    assert_disposable_database(url)
    parsed = make_url(url)
    assert parsed.host == '127.0.0.1' and parsed.database == 'obs_d2_test' and not parsed.query
    return url


@pytest.fixture(scope='module', params=['fresh', 'upgrade'])
def operational_database(request, rls_database_url):
    from scripts import migrate
    url = rls_database_url
    engine = create_engine(url)
    with engine.begin() as c:
        c.exec_driver_sql('drop schema public cascade; create schema public')
        for role in ('anon', 'authenticated', 'service_role'):
            c.exec_driver_sql(f"do $$ begin if not exists(select 1 from pg_roles where rolname='{role}') then create role {role}; end if; end $$")
            c.exec_driver_sql(f"alter role {role} nologin {'bypassrls' if role == 'service_role' else 'nobypassrls'}")
        c.exec_driver_sql('grant usage on schema public to anon, authenticated, service_role')
        for obj in ('tables', 'sequences', 'functions'):
            c.exec_driver_sql(f'alter default privileges in schema public grant all on {obj} to anon, authenticated, service_role')
        c.exec_driver_sql('create table schema_migrations(name text primary key)')
    for filename in migrate.migration_files():
        if filename == '20261023_100000_ai_usage_force_rls.sql' and request.param == 'upgrade':
            with engine.begin() as c:
                c.exec_driver_sql("insert into igrejas(id,nome) values('aaaaaaaa-0000-0000-0000-000000000001','Synthetic legacy')")
                c.exec_driver_sql("insert into ai_usage_logs(igreja_id,tokens_in) values('aaaaaaaa-0000-0000-0000-000000000001',42)")
        body = (migrate.MIGRATIONS_DIR / filename).read_text()
        cmd = [sys.executable, str(Path(migrate.__file__)), 'apply', filename, '--yes']
        if any('index concurrently' in line.lower() for line in body.splitlines() if not line.lstrip().startswith('--')):
            cmd.append('--no-transaction')
        result = subprocess.run(cmd, env=dict(os.environ, MIGRATION_DATABASE_URL=url.replace('postgresql+psycopg2:', 'postgresql:')), capture_output=True, text=True)
        assert result.returncode == 0, f'{filename}: {result.stderr}'
    if request.param == 'upgrade':
        with engine.connect() as c:
            assert c.scalar(text('select tokens_in from ai_usage_logs')) == 42
    yield engine
    engine.dispose()
