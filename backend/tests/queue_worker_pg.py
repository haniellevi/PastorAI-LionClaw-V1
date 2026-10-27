"""Synthetic LOGIN for ``queue_worker_runtime`` on a disposable PG only.

Same contract as ``tests/private_summary_pg.py``: the migration creates the role
NOLOGIN without password; tests grant LOGIN with a random per-run password,
select QUEUE_WORKER_DATABASE_MODE=dedicated with QUEUE_WORKER_DATABASE_URL on the
same disposable database and restore NOLOGIN/no password afterwards. Nothing
here is a real credential.
"""
from __future__ import annotations

import secrets
from contextlib import contextmanager
from types import SimpleNamespace

from tests.conftest_rls import assert_disposable_database

ROLE = 'queue_worker_runtime'


@contextmanager
def queue_worker_login(engine, monkeypatch, *, url_options=None):
    """Yield the URL of the provisioned login; the real selector builds the factory."""
    from app.config import get_settings
    from app.db.queue_worker_session import dispose_queue_worker_engine
    from app.workers import queue_worker as worker
    assert_disposable_database(engine.url.render_as_string(hide_password=False))
    password = secrets.token_urlsafe(24)
    with engine.begin() as c:
        c.exec_driver_sql(f"alter role {ROLE} login password '{password}'")
    url = engine.url.set(username=ROLE, password=password)
    if url_options is not None:  # Adversarial URL settings; never a harness shortcut.
        url = url.update_query_dict({'options': url_options})
    monkeypatch.setenv('QUEUE_WORKER_DATABASE_MODE', 'dedicated')
    monkeypatch.setenv('QUEUE_WORKER_DATABASE_URL', url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    settings = worker.get_settings()
    if isinstance(settings, SimpleNamespace):  # s3_turn replaces the worker settings.
        monkeypatch.setattr(settings, 'queue_worker_database_mode', 'dedicated', raising=False)
    dispose_queue_worker_engine()
    try:
        yield url
    finally:
        dispose_queue_worker_engine()
        monkeypatch.delenv('QUEUE_WORKER_DATABASE_MODE', raising=False)
        monkeypatch.delenv('QUEUE_WORKER_DATABASE_URL', raising=False)
        get_settings.cache_clear()
        with engine.begin() as c:
            c.exec_driver_sql(f'alter role {ROLE} nologin password null')
