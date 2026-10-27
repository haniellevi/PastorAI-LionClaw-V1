"""Synthetic LOGIN for ``private_storage_runtime`` on a disposable PG only.

The migration creates the role NOLOGIN without password. Tests grant LOGIN with
a random per-run password, point PRIVATE_STORAGE_DATABASE_URL at the same
disposable database and restore NOLOGIN/no password afterwards. Nothing here
is a real credential.

Isolated-schema harnesses adapt only the fixed transaction search_path
constant to their synthetic namespace; identity, grants and RLS are unchanged
and the URL never carries a search_path. Full-chain suites keep the production
default ``pg_catalog, public, pg_temp``.
"""
from __future__ import annotations

import secrets
from contextlib import contextmanager

from tests.conftest_rls import assert_disposable_database


@contextmanager
def private_storage_login(engine, monkeypatch, *, schema=None, url_options=None):
    from app.config import get_settings
    from app.db import privacy_storage_session
    from app.db.privacy_storage_session import (
        dispose_private_storage_engine, get_private_storage_session_factory,
    )
    assert_disposable_database(engine.url.render_as_string(hide_password=False))
    password = secrets.token_urlsafe(24)
    with engine.begin() as c:
        c.exec_driver_sql(f"alter role private_storage_runtime login password '{password}'")
    url = engine.url.set(username='private_storage_runtime', password=password)
    if url_options is not None:  # Adversarial URL settings; never a harness shortcut.
        url = url.update_query_dict({'options': url_options})
    if schema is not None:
        monkeypatch.setattr(privacy_storage_session, 'PRIVATE_STORAGE_SEARCH_PATH', f'pg_catalog, {schema}, pg_temp')
    monkeypatch.setenv('PRIVATE_STORAGE_DATABASE_URL', url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    dispose_private_storage_engine()
    try:
        yield get_private_storage_session_factory()
    finally:
        dispose_private_storage_engine()
        monkeypatch.delenv('PRIVATE_STORAGE_DATABASE_URL', raising=False)
        get_settings.cache_clear()
        with engine.begin() as c:
            c.exec_driver_sql('alter role private_storage_runtime nologin password null')
