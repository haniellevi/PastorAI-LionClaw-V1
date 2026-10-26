"""Synthetic LOGIN for ``private_send_runtime`` on a disposable PG only.

Same contract as ``tests/private_storage_pg.py``: the migration creates the
role NOLOGIN without password; tests grant LOGIN with a random per-run
password, point PRIVATE_SEND_DATABASE_URL at the same disposable database and
restore NOLOGIN/no password afterwards. Nothing here is a real credential.
"""
from __future__ import annotations

import secrets
from contextlib import contextmanager

import pytest

from tests.conftest_rls import assert_disposable_database


@contextmanager
def private_send_login(engine, monkeypatch, *, schema=None, url_options=None):
    from app.config import get_settings
    from app.db import private_send_session
    from app.db.private_send_session import dispose_private_send_engine, get_private_send_session_factory
    assert_disposable_database(engine.url.render_as_string(hide_password=False))
    password = secrets.token_urlsafe(24)
    with engine.begin() as c:
        c.exec_driver_sql(f"alter role private_send_runtime login password '{password}'")
    url = engine.url.set(username='private_send_runtime', password=password)
    if url_options is not None:  # Adversarial URL settings; never a harness shortcut.
        url = url.update_query_dict({'options': url_options})
    if schema is not None:
        monkeypatch.setattr(private_send_session, 'PRIVATE_SEND_SEARCH_PATH', f'pg_catalog, {schema}, pg_temp')
    monkeypatch.setenv('PRIVATE_SEND_DATABASE_URL', url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    dispose_private_send_engine()
    try:
        yield get_private_send_session_factory()
    finally:
        dispose_private_send_engine()
        monkeypatch.delenv('PRIVATE_SEND_DATABASE_URL', raising=False)
        get_settings.cache_clear()
        with engine.begin() as c:
            c.exec_driver_sql('alter role private_send_runtime nologin password null')


MIGRATION = '20261030_120000_private_send_release_identity.sql'


def install_private_send_release(engine, schema):
    """The real release migration in an isolated ``create_all`` schema.

    Only the schema qualifier changes (as the prayer privacy harness does);
    role guard, grants, revokes and functions are the migration's own. The
    migration replaces the 20261018_090000 worker policy; a bare ``create_all``
    schema lacks it, so the harness then installs a placeholder of that name.
    """
    from scripts import migrate
    assert_disposable_database(engine.url.render_as_string(hide_password=False))
    sql = migrate.strip_outer_transaction((migrate.MIGRATIONS_DIR / MIGRATION).read_text())
    sql = sql.replace('public.', f'{schema}.').replace(
        'pg_catalog,public', f'pg_catalog,{schema}').replace('on schema public', f'on schema {schema}')
    with engine.begin() as c:
        c.exec_driver_sql(f"""do $$ begin if not exists(select 1 from pg_policy where polname='send_worker'
            and polrelid='{schema}.private_deletion_sends'::regclass) then
            create policy send_worker on {schema}.private_deletion_sends for all to authenticated using(true);
            end if; end $$""")
        c.exec_driver_sql(sql, execution_options={'no_parameters': True})


@pytest.fixture
def send_release_login(database, monkeypatch):
    """Full migration chain: the synthetic dedicated login releases send ownership.

    Retry tests need it; without the login ownership is retained and the same
    intent is never resent (fail-closed).
    """
    with private_send_login(database, monkeypatch) as factory:
        yield factory
