"""Dedicated send-release URL shape, identity probe and non-raising release.

No database: the SQL identity and grants are proven in
test_private_send_runtime_pg.py. Every URL here is synthetic.
"""
import logging
from uuid import uuid4

import pytest

from app.db import private_send_session as session
from app.db import privacy_storage_session as storage_session

REF = 'abcdefghij0123456789'
DIRECT = 'postgresql+psycopg2://private_send_runtime:synthetic@db.example.invalid:5432/postgres'
POOLER = f'postgresql+psycopg2://private_send_runtime.{REF}:synthetic@pooler.example.invalid:5432/postgres'
STORAGE = 'postgresql+psycopg2://private_storage_runtime:synthetic@db.example.invalid:5432/postgres'


def _settings(monkeypatch, **values):
    from app.config import get_settings
    for name in ('PRIVATE_SEND_DATABASE_URL', 'PRIVATE_STORAGE_DATABASE_URL', 'DATABASE_URL',
                 'AGENT_RUNTIME_DATABASE_URL'):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    for module in (session, storage_session):
        monkeypatch.setattr(module, '_engine', None)
        monkeypatch.setattr(module, '_SessionFactory', None)


@pytest.mark.parametrize('username', ('private_send_runtime', f'private_send_runtime.{REF}'))
def test_direct_and_pooler_users_are_accepted(username):
    assert session.is_private_send_url_user(username)


@pytest.mark.parametrize('username', (
    None, '', 'postgres', 'private_storage_runtime', f'private_storage_runtime.{REF}',
    'private_send_runtimex', 'private_send_runtime.', f'private_send_runtime.{REF[:-1]}',
    f'private_send_runtime.{REF}\n', f'private_send_runtime.{REF.upper()}',
))
def test_other_users_are_refused(username):
    assert not session.is_private_send_url_user(username)


@pytest.mark.parametrize('url', (DIRECT, POOLER))
def test_valid_urls_build_a_lazy_factory_without_connecting(monkeypatch, url):
    _settings(monkeypatch, PRIVATE_SEND_DATABASE_URL=url, PRIVATE_STORAGE_DATABASE_URL=STORAGE)
    try:
        assert session.get_private_send_session_factory() is not None
    finally:
        session.dispose_private_send_engine()


@pytest.mark.parametrize('values', (
    {},
    {'DATABASE_URL': DIRECT},  # Never a fallback to the main login.
    {'PRIVATE_SEND_DATABASE_URL': STORAGE},
    {'PRIVATE_SEND_DATABASE_URL': 'postgresql+psycopg2://postgres:synthetic@db.example.invalid/postgres'},
    {'PRIVATE_SEND_DATABASE_URL': DIRECT, 'DATABASE_URL': DIRECT},
    {'PRIVATE_SEND_DATABASE_URL': POOLER, 'AGENT_RUNTIME_DATABASE_URL': POOLER},
    {'PRIVATE_SEND_DATABASE_URL': DIRECT, 'PRIVATE_STORAGE_DATABASE_URL': DIRECT},
    {'PRIVATE_SEND_DATABASE_URL': 'not a url'},
))
def test_missing_or_unsafe_urls_never_fall_back(monkeypatch, values):
    _settings(monkeypatch, **values)
    with pytest.raises(session.PrivateSendUnavailable):
        session.get_private_send_session_factory()


def test_the_two_dedicated_logins_never_accept_each_other(monkeypatch):
    _settings(monkeypatch, PRIVATE_SEND_DATABASE_URL=STORAGE, PRIVATE_STORAGE_DATABASE_URL=DIRECT)
    with pytest.raises(session.PrivateSendUnavailable):
        session.get_private_send_session_factory()
    with pytest.raises(storage_session.PrivateStorageUnavailable):
        storage_session.get_private_storage_session_factory()


def _row(**overrides):
    row = dict(login='private_send_runtime', effective='private_send_runtime', can_login=True,
               inherits=False, superuser=False, bypass=False, createdb=False, createrole=False,
               replication=False, no_memberships=True, row_security='on',
               search_path='pg_catalog, public, pg_temp', tenant='t')
    row.update(overrides)
    return tuple(row.values())


def test_probe_accepts_only_the_exact_login_and_fixed_settings():
    assert session._identity_matches(_row(), 't')
    assert not storage_session._identity_matches(_row(), 't')
    for overrides in ({'login': 'private_storage_runtime'}, {'effective': 'postgres'},
                      {'can_login': False}, {'inherits': True}, {'superuser': True}, {'bypass': True},
                      {'createrole': True}, {'no_memberships': False}, {'row_security': 'off'},
                      {'search_path': 'pg_catalog, public'}, {'tenant': None}):
        assert not session._identity_matches(_row(**overrides), 't'), overrides


def test_release_without_login_retains_and_logs_a_closed_code(monkeypatch, caplog):
    from app.services.private_deletion import finish_agent_send
    _settings(monkeypatch, DATABASE_URL='postgresql+psycopg2://postgres:synthetic@db.example.invalid/postgres')
    tenant, source = uuid4(), uuid4()
    with caplog.at_level(logging.WARNING, logger='app.services.private_deletion'):
        assert finish_agent_send(tenant, source) is False
    [record] = caplog.records
    assert record.event == 'private_send_release_unavailable'
    assert record.error_type == 'PrivateSendUnavailable'
    exposed = caplog.text + repr(record.__dict__)
    for value in (str(tenant), str(source), 'synthetic', 'postgresql'):
        assert value not in exposed


def test_release_never_swallows_base_exceptions(monkeypatch):
    from app.services import private_deletion

    def interrupted():
        raise KeyboardInterrupt
    monkeypatch.setattr(private_deletion, 'get_private_send_session_factory', interrupted)
    with pytest.raises(KeyboardInterrupt):
        private_deletion.finish_agent_send(uuid4(), uuid4())
