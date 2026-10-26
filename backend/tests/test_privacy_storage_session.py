"""Dedicated private Storage URL shape and identity probe, without a database.

The URL user is only a pre-connection shape check; the SQL probe on every
transaction is the identity proof (see test_private_storage_runtime_pg.py).
"""
import pytest

from app.db import privacy_storage_session as session

REF = 'abcdefghij0123456789'


@pytest.mark.parametrize('username', ('private_storage_runtime', f'private_storage_runtime.{REF}'))
def test_direct_and_supabase_pooler_users_are_accepted(username):
    assert session.is_private_storage_url_user(username)


@pytest.mark.parametrize('username', (
    None, '', 'postgres', f'postgres.{REF}', 'private_storage_runtimex', 'private_storage_runtime.',
    f'private_storage_runtime.{REF[:-1]}', f'private_storage_runtime.{REF}0',
    f'private_storage_runtime.{REF.upper()}', f'private_storage_runtime.{REF[:-1]}-',
    f'private_storage_runtime.{REF}\n', f'Private_storage_runtime.{REF}',
    f'private_storage_runtime.{REF}.extra', 'agent_runtime',
))
def test_other_users_are_refused(username):
    assert not session.is_private_storage_url_user(username)


def _settings(monkeypatch, **values):
    from app.config import get_settings
    for name in ('PRIVATE_STORAGE_DATABASE_URL', 'DATABASE_URL', 'AGENT_RUNTIME_DATABASE_URL'):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    monkeypatch.setattr(session, '_engine', None)
    monkeypatch.setattr(session, '_SessionFactory', None)


POOLER = f'postgresql+psycopg2://private_storage_runtime.{REF}:synthetic@pooler.example.invalid:5432/postgres'
DIRECT = 'postgresql+psycopg2://private_storage_runtime:synthetic@db.example.invalid:5432/postgres'


@pytest.mark.parametrize('url', (DIRECT, POOLER))
def test_valid_urls_build_a_lazy_factory_without_connecting(monkeypatch, url):
    _settings(monkeypatch, PRIVATE_STORAGE_DATABASE_URL=url)
    try:
        assert session.get_private_storage_session_factory() is not None
    finally:
        session.dispose_private_storage_engine()


@pytest.mark.parametrize('values', (
    {},
    {'PRIVATE_STORAGE_DATABASE_URL': 'postgresql+psycopg2://postgres:synthetic@db.example.invalid/postgres'},
    {'PRIVATE_STORAGE_DATABASE_URL': f'postgresql+psycopg2://postgres.{REF}:synthetic@pooler.example.invalid/postgres'},
    {'PRIVATE_STORAGE_DATABASE_URL': DIRECT, 'DATABASE_URL': DIRECT},
    {'PRIVATE_STORAGE_DATABASE_URL': POOLER, 'AGENT_RUNTIME_DATABASE_URL': POOLER},
    {'PRIVATE_STORAGE_DATABASE_URL': 'not a url'},
))
def test_missing_or_unsafe_urls_never_fall_back(monkeypatch, values):
    _settings(monkeypatch, **values)
    with pytest.raises(session.PrivateStorageUnavailable):
        session.get_private_storage_session_factory()


def _row(**overrides):
    row = dict(login='private_storage_runtime', effective='private_storage_runtime', can_login=True,
               inherits=False, superuser=False, bypass=False, createdb=False, createrole=False,
               replication=False, no_memberships=True, row_security='on',
               search_path='pg_catalog, public, pg_temp', tenant='t')
    row.update(overrides)
    return tuple(row.values())


def test_probe_accepts_only_the_exact_login_and_fixed_settings():
    assert session._identity_matches(_row(), 't')
    for overrides in ({'login': f'private_storage_runtime.{REF}'}, {'effective': 'postgres'},
                      {'can_login': False}, {'inherits': True}, {'superuser': True}, {'bypass': True},
                      {'no_memberships': False}, {'row_security': 'off'},
                      {'search_path': 'private_storage_runtime, public'}, {'search_path': 'pg_catalog, public'},
                      {'tenant': 'other'}):
        assert not session._identity_matches(_row(**overrides), 't'), overrides
