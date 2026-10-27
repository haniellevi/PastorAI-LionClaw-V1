"""Synthetic LOGIN for ``private_summary_runtime`` on a disposable PG only.

Same contract as ``tests/private_send_pg.py``: the migration creates the role
NOLOGIN without password; tests grant LOGIN with a random per-run password,
point PRIVATE_SUMMARY_DATABASE_URL at the same disposable database and restore
NOLOGIN/no password afterwards. Nothing here is a real credential.
"""
from __future__ import annotations

import secrets
from contextlib import contextmanager

from tests.conftest_rls import assert_disposable_database

ROLE = 'private_summary_runtime'


@contextmanager
def private_summary_login(engine, monkeypatch, *, url_options=None):
    from app.config import get_settings
    from app.db.private_summary_session import (
        dispose_private_summary_engine, get_private_summary_session_factory,
    )
    assert_disposable_database(engine.url.render_as_string(hide_password=False))
    password = secrets.token_urlsafe(24)
    with engine.begin() as c:
        c.exec_driver_sql(f"alter role {ROLE} login password '{password}'")
    url = engine.url.set(username=ROLE, password=password)
    if url_options is not None:  # Adversarial URL settings; never a harness shortcut.
        url = url.update_query_dict({'options': url_options})
    monkeypatch.setenv('PRIVATE_SUMMARY_DATABASE_URL', url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    dispose_private_summary_engine()
    try:
        yield get_private_summary_session_factory()
    finally:
        dispose_private_summary_engine()
        monkeypatch.delenv('PRIVATE_SUMMARY_DATABASE_URL', raising=False)
        get_settings.cache_clear()
        with engine.begin() as c:
            c.exec_driver_sql(f'alter role {ROLE} nologin password null')
