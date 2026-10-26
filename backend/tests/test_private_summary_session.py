"""Dedicated summary-generation URL shape, identity probe and fail-closed cycle.

No database: the SQL identity, grants and the full cycle are proven in
test_private_summary_runtime_pg.py. Every URL here is synthetic.
"""
import logging

import pytest

from app.db import private_send_session as send_session
from app.db import private_summary_session as session
from app.db import privacy_storage_session as storage_session

REF = 'abcdefghij0123456789'
DIRECT = 'postgresql+psycopg2://private_summary_runtime:synthetic@db.example.invalid:5432/postgres'
POOLER = f'postgresql+psycopg2://private_summary_runtime.{REF}:synthetic@pooler.example.invalid:5432/postgres'
SEND = 'postgresql+psycopg2://private_send_runtime:synthetic@db.example.invalid:5432/postgres'
STORAGE = 'postgresql+psycopg2://private_storage_runtime:synthetic@db.example.invalid:5432/postgres'
MAIN = 'postgresql+psycopg2://postgres:synthetic@db.example.invalid/postgres'


def _settings(monkeypatch, **values):
    from app.config import get_settings
    for name in ('PRIVATE_SUMMARY_DATABASE_URL', 'PRIVATE_SEND_DATABASE_URL', 'PRIVATE_STORAGE_DATABASE_URL',
                 'DATABASE_URL', 'AGENT_RUNTIME_DATABASE_URL'):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    for module in (session, send_session, storage_session):
        monkeypatch.setattr(module, '_engine', None)
        monkeypatch.setattr(module, '_SessionFactory', None)


@pytest.mark.parametrize('username', ('private_summary_runtime', f'private_summary_runtime.{REF}'))
def test_direct_and_pooler_users_are_accepted(username):
    assert session.is_private_summary_url_user(username)


@pytest.mark.parametrize('username', (
    None, '', 'postgres', 'private_send_runtime', 'private_storage_runtime', 'authenticated',
    'private_summary_runtimex', 'private_summary_runtime.', f'private_summary_runtime.{REF[:-1]}',
    f'private_summary_runtime.{REF}\n', f'private_summary_runtime.{REF.upper()}',
))
def test_other_users_are_refused(username):
    assert not session.is_private_summary_url_user(username)


@pytest.mark.parametrize('url', (DIRECT, POOLER))
def test_valid_urls_build_a_lazy_factory_without_connecting(monkeypatch, url):
    _settings(monkeypatch, PRIVATE_SUMMARY_DATABASE_URL=url, PRIVATE_SEND_DATABASE_URL=SEND,
              PRIVATE_STORAGE_DATABASE_URL=STORAGE, DATABASE_URL=MAIN)
    try:
        assert session.get_private_summary_session_factory() is not None
    finally:
        session.dispose_private_summary_engine()


@pytest.mark.parametrize('values', (
    {},
    {'DATABASE_URL': DIRECT},  # Never a fallback to the main login.
    {'PRIVATE_SUMMARY_DATABASE_URL': SEND},
    {'PRIVATE_SUMMARY_DATABASE_URL': MAIN},
    {'PRIVATE_SUMMARY_DATABASE_URL': DIRECT, 'DATABASE_URL': DIRECT},
    {'PRIVATE_SUMMARY_DATABASE_URL': POOLER, 'AGENT_RUNTIME_DATABASE_URL': POOLER},
    {'PRIVATE_SUMMARY_DATABASE_URL': DIRECT, 'PRIVATE_STORAGE_DATABASE_URL': DIRECT},
    {'PRIVATE_SUMMARY_DATABASE_URL': DIRECT, 'PRIVATE_SEND_DATABASE_URL': DIRECT},
    {'PRIVATE_SUMMARY_DATABASE_URL': 'not a url'},
))
def test_missing_or_unsafe_urls_never_fall_back(monkeypatch, values):
    _settings(monkeypatch, **values)
    with pytest.raises(session.PrivateSummaryUnavailable):
        session.get_private_summary_session_factory()


def test_the_other_dedicated_logins_never_accept_the_summary_url(monkeypatch):
    _settings(monkeypatch, PRIVATE_SUMMARY_DATABASE_URL=DIRECT, PRIVATE_SEND_DATABASE_URL=DIRECT)
    with pytest.raises(send_session.PrivateSendUnavailable):
        send_session.get_private_send_session_factory()
    _settings(monkeypatch, PRIVATE_SUMMARY_DATABASE_URL=DIRECT, PRIVATE_STORAGE_DATABASE_URL=DIRECT)
    with pytest.raises(storage_session.PrivateStorageUnavailable):
        storage_session.get_private_storage_session_factory()


def _row(**overrides):
    row = dict(login='private_summary_runtime', effective='private_summary_runtime', can_login=True,
               inherits=False, superuser=False, bypass=False, createdb=False, createrole=False,
               replication=False, no_memberships=True, row_security='on',
               search_path='pg_catalog, public, pg_temp', tenant='t')
    row.update(overrides)
    return tuple(row.values())


def test_probe_accepts_only_the_exact_login_and_fixed_settings():
    assert session._identity_matches(_row(), 't')
    assert session._identity_matches(_row(tenant=None), None)  # Unpinned discovery.
    assert not send_session._identity_matches(_row(), 't')
    for overrides in ({'login': 'private_send_runtime'}, {'effective': 'postgres'},
                      {'can_login': False}, {'inherits': True}, {'superuser': True}, {'bypass': True},
                      {'createrole': True}, {'no_memberships': False}, {'row_security': 'off'},
                      {'search_path': 'pg_catalog, public'}, {'tenant': None}):
        assert not session._identity_matches(_row(**overrides), 't'), overrides


# --- process_tasks: gates first, then only the dedicated login, never a fallback.

class _Spy:
    """A main-login stand-in: records any use; a real query would be a failure."""

    def __init__(self):
        self.opened = 0
        self.queries = []
        self.info = {}

    def __call__(self):
        self.opened += 1
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kwargs):
        self.queries.append(args)
        raise AssertionError('main login queried')

    scalar = scalar_one = execute


@pytest.fixture
def open_gates(monkeypatch):
    from app.services import private_summaries as mem
    monkeypatch.setattr(mem, 'APPROVED_RELEASE_ID', 'synthetic-test')
    monkeypatch.setattr(mem, 'APPROVED_IGREJA_IDS', frozenset({'00000000-0000-0000-0000-00000000000a'}))
    return mem


def test_closed_gates_return_before_resolving_any_factory(monkeypatch):
    from app.services import private_summaries as mem

    def resolve():
        raise AssertionError('factory resolved with closed gates')
    monkeypatch.setattr(mem, 'get_private_summary_session_factory', resolve)
    calls = []
    assert mem.process_tasks(provider=lambda **kw: calls.append(kw)) == 0
    monkeypatch.setattr(mem, 'APPROVED_RELEASE_ID', 'synthetic-test')
    assert mem.process_tasks(provider=lambda **kw: calls.append(kw)) == 0  # Empty allowlist.
    assert calls == []


def test_closed_external_gate_returns_before_resolving_any_factory(monkeypatch, open_gates):
    mem = open_gates

    def resolve():
        raise AssertionError('factory resolved with ALLOW_REAL_SENDS closed')
    monkeypatch.setattr(mem, 'get_private_summary_session_factory', resolve)
    monkeypatch.setenv('ALLOW_REAL_SENDS', 'false')
    from app.config import get_settings
    get_settings.cache_clear()
    assert mem.process_tasks() == 0  # Real provider path, gate closed.


@pytest.mark.parametrize('values', ({}, {'PRIVATE_SUMMARY_DATABASE_URL': MAIN},
                                    {'PRIVATE_SUMMARY_DATABASE_URL': DIRECT, 'DATABASE_URL': DIRECT}))
def test_missing_login_fails_closed_without_fallback(monkeypatch, caplog, open_gates, values):
    mem = open_gates
    _settings(monkeypatch, **{'DATABASE_URL': MAIN, **values})
    calls = []
    with caplog.at_level(logging.WARNING, logger='app.services.private_summaries'):
        assert mem.process_tasks(provider=lambda **kw: calls.append(kw)) == 0
    assert calls == []
    [record] = caplog.records
    assert record.event == 'private_summary_runtime_unavailable'
    assert record.error_type == 'PrivateSummaryUnavailable'
    exposed = caplog.text + repr(record.__dict__)
    for value in ('synthetic', 'postgresql', '00000000-0000-0000-0000-00000000000a'):
        assert value not in exposed


def test_injected_main_factory_is_refused_before_any_query(caplog, open_gates):
    mem = open_gates
    spy = _Spy()
    calls = []
    with caplog.at_level(logging.WARNING, logger='app.services.private_summaries'):
        assert mem.process_tasks(spy, provider=lambda **kw: calls.append(kw)) == 0
    assert spy.queries == [] and calls == []
    assert [r.event for r in caplog.records] == ['private_summary_runtime_unavailable']
    assert caplog.records[0].error_type == 'PrivateSummaryScopeError'
