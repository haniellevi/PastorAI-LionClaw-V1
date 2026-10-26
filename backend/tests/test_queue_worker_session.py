"""Queue worker database mode selector, dedicated URL shape and identity probe.

No database: the real LOGIN, migration and the full queue unit of work are
proven in test_queue_worker_runtime_pg.py. Every URL here is synthetic.
"""
import pytest
from sqlalchemy.engine import URL

from app.db import queue_worker_session as session
from app.workers import queue_worker as worker

REF = 'abcdefghij0123456789'
DIRECT = 'postgresql+psycopg2://queue_worker_runtime:synthetic@db.example.invalid:5432/postgres'


def _supabase_pooler(port):
    """Synthetic shared-pooler URL: Supabase's documented host suffix, fake region/ref/password."""
    return URL.create('postgresql+psycopg2', username=f'queue_worker_runtime.{REF}', password='synthetic',
                      host='synthetic-region.pooler.supabase.com', port=port,
                      database='postgres').render_as_string(hide_password=False)


POOLER = _supabase_pooler(5432)  # Session mode.
TRANSACTION_POOLER = _supabase_pooler(6543)
MAIN = 'postgresql+psycopg2://postgres:synthetic@db.example.invalid/postgres'
URL_NAMES = ('QUEUE_WORKER_DATABASE_MODE', 'QUEUE_WORKER_DATABASE_URL', 'DATABASE_URL',
             'AGENT_RUNTIME_DATABASE_URL', 'PRIVATE_STORAGE_DATABASE_URL',
             'PRIVATE_SEND_DATABASE_URL', 'PRIVATE_SUMMARY_DATABASE_URL')


class _MainSpy:
    """Stand-in for the main login factory: any resolution or use is recorded."""

    def __init__(self):
        self.resolved = 0
        self.opened = 0
        self.info = {}

    def resolve(self):
        self.resolved += 1
        return self

    def __call__(self):
        self.opened += 1
        raise AssertionError('main login session opened')


class _Queue:
    _redis = None


@pytest.fixture
def env(monkeypatch):
    from app.config import get_settings
    main = _MainSpy()
    monkeypatch.setattr(worker, 'get_session_factory', main.resolve)

    def apply(**values):
        for name in URL_NAMES:
            monkeypatch.delenv(name, raising=False)
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()
        monkeypatch.setattr(session, '_engine', None)
        monkeypatch.setattr(session, '_SessionFactory', None)
        return main
    yield apply
    session.dispose_queue_worker_engine()
    get_settings.cache_clear()


def _queue_worker(**kwargs):
    return worker.QueueWorker(queue=_Queue(), worker_id='QW-UNIT', heartbeat_publisher=lambda *_a: None, **kwargs)


# --- Mode selector: legacy by default, dedicated only when explicit.

def test_default_mode_is_legacy_main_factory_without_resolving_the_dedicated_one(env, monkeypatch):
    main = env(DATABASE_URL=MAIN)

    def dedicated():
        raise AssertionError('dedicated factory resolved in legacy mode')
    monkeypatch.setattr(session, 'get_queue_worker_session_factory', dedicated)
    qw = _queue_worker()
    assert qw._session_factory is main and main.resolved == 1 and main.opened == 0


@pytest.mark.parametrize('url', (DIRECT, POOLER, 'not a url'))
def test_dedicated_url_alone_never_activates_the_dedicated_mode(env, monkeypatch, url):
    main = env(DATABASE_URL=MAIN, QUEUE_WORKER_DATABASE_URL=url)

    def dedicated():
        raise AssertionError('URL alone activated the dedicated mode')
    monkeypatch.setattr(session, 'get_queue_worker_session_factory', dedicated)
    assert _queue_worker()._session_factory is main


def test_explicit_legacy_mode_keeps_the_main_factory(env):
    main = env(DATABASE_URL=MAIN, QUEUE_WORKER_DATABASE_MODE='legacy', QUEUE_WORKER_DATABASE_URL=DIRECT)
    assert _queue_worker()._session_factory is main


@pytest.mark.parametrize('url', (DIRECT, POOLER))
def test_dedicated_mode_builds_only_the_dedicated_lazy_factory(env, url):
    main = env(DATABASE_URL=MAIN, QUEUE_WORKER_DATABASE_MODE='dedicated', QUEUE_WORKER_DATABASE_URL=url)
    factory = _queue_worker()._session_factory
    assert factory is session.get_queue_worker_session_factory()
    assert factory.kw['info'] == {session.QUEUE_WORKER_SESSION_FLAG: True}
    assert factory.kw['bind'].url.username.split('.')[0] == session.QUEUE_WORKER_ROLE
    assert main.resolved == 0 and main.opened == 0


@pytest.mark.parametrize('values', (
    {},  # No URL: the main login is never a fallback.
    {'QUEUE_WORKER_DATABASE_URL': MAIN},
    {'QUEUE_WORKER_DATABASE_URL': 'not a url'},
    {'QUEUE_WORKER_DATABASE_URL': DIRECT.replace('queue_worker_runtime', 'private_send_runtime')},
    {'QUEUE_WORKER_DATABASE_URL': DIRECT.replace('queue_worker_runtime', 'queue_worker_runtimex')},
    {'QUEUE_WORKER_DATABASE_URL': DIRECT, 'DATABASE_URL': DIRECT},
    {'QUEUE_WORKER_DATABASE_URL': DIRECT, 'AGENT_RUNTIME_DATABASE_URL': DIRECT},
    {'QUEUE_WORKER_DATABASE_URL': DIRECT, 'PRIVATE_STORAGE_DATABASE_URL': DIRECT},
    {'QUEUE_WORKER_DATABASE_URL': DIRECT, 'PRIVATE_SEND_DATABASE_URL': DIRECT},
    {'QUEUE_WORKER_DATABASE_URL': DIRECT, 'PRIVATE_SUMMARY_DATABASE_URL': DIRECT},
    # Known Supabase transaction pooler: the session advisory lease cannot hold there.
    {'QUEUE_WORKER_DATABASE_URL': TRANSACTION_POOLER},
))
def test_dedicated_mode_without_a_valid_url_fails_closed_without_fallback(env, values):
    main = env(**{'DATABASE_URL': MAIN, 'QUEUE_WORKER_DATABASE_MODE': 'dedicated', **values})
    with pytest.raises(session.QueueWorkerUnavailable) as error:
        _queue_worker()
    assert 'synthetic' not in str(error.value) and 'example.invalid' not in str(error.value)
    assert main.resolved == 0 and main.opened == 0


@pytest.mark.parametrize('mode', ('', 'Dedicated', 'LEGACY', ' legacy', 'dedicated ', 'both', 'true'))
def test_ambiguous_mode_refuses_both_factories(env, monkeypatch, mode):
    main = env(DATABASE_URL=MAIN, QUEUE_WORKER_DATABASE_MODE=mode, QUEUE_WORKER_DATABASE_URL=DIRECT)

    def dedicated():
        raise AssertionError('dedicated factory resolved for an ambiguous mode')
    monkeypatch.setattr(session, 'get_queue_worker_session_factory', dedicated)
    with pytest.raises(session.QueueWorkerUnavailable):
        _queue_worker()
    assert main.resolved == 0


def test_injected_factory_is_kept_without_consulting_the_mode(env):
    main = env(QUEUE_WORKER_DATABASE_MODE='ambiguous')
    injected = _MainSpy()
    assert _queue_worker(session_factory=injected)._session_factory is injected
    assert main.resolved == 0 and injected.opened == 0


@pytest.mark.parametrize('username', ('queue_worker_runtime', f'queue_worker_runtime.{REF}'))
def test_direct_and_pooler_users_are_accepted(username):
    assert session.is_queue_worker_url_user(username)


@pytest.mark.parametrize('username', (
    None, '', 'postgres', 'authenticated', 'private_send_runtime', 'queue_worker_runtimex',
    'queue_worker_runtime.', f'queue_worker_runtime.{REF[:-1]}', f'queue_worker_runtime.{REF.upper()}',
))
def test_other_users_are_refused(username):
    assert not session.is_queue_worker_url_user(username)


# --- Identity probe: both roles, the membership and the per-connection state.

def _row(**overrides):
    row = dict(
        login='queue_worker_runtime', effective='queue_worker_runtime', role='none',
        can_login=True, inherits=False, superuser=False, bypass=False, createdb=False,
        createrole=False, replication=False, membership_exact=True, members_safe=True, login_objects_safe=True,
        auth_superuser=False, auth_bypass=False, auth_createdb=False, auth_createrole=False,
        auth_replication=False, auth_no_memberships=True, auth_owns_no_table=True,
        tenant=None, jwt_claims=None, jwt_sub=None, search_path='pg_catalog, public, pg_temp',
        row_security='on', no_temp_relations=True)
    row.update(overrides)
    return tuple(row.values())


SCOPED = dict(effective='authenticated', role='authenticated', tenant='t')


def test_probe_accepts_only_the_exact_state_before_and_after_scope():
    assert session._identity_problem(_row(), tenant=None) is None
    assert session._identity_problem(_row(**SCOPED), tenant='t') is None
    # Order of hooks: login state is never accepted as scoped, nor the reverse.
    assert session._identity_problem(_row(), tenant='t') == 'effective_not_authenticated'
    assert session._identity_problem(_row(**SCOPED), tenant=None) == 'effective_not_login'
    assert session._identity_problem(_row(**{**SCOPED, 'tenant': 'u'}), tenant='t') == 'tenant_mismatch'
    assert session._identity_problem(None, tenant=None) == 'no_role_row'


@pytest.mark.parametrize('overrides,reason', (
    ({'login': 'postgres'}, 'session_user'),
    ({'can_login': False}, 'nologin'),
    ({'inherits': True}, 'inherit'),
    ({'superuser': True}, 'superuser'),
    ({'bypass': True}, 'bypassrls'),
    ({'createdb': True}, 'createdb'),
    ({'createrole': True}, 'createrole'),
    ({'replication': True}, 'replication'),
    ({'membership_exact': False}, 'membership'),
    ({'members_safe': False}, 'login_members'),
    ({'login_objects_safe': False}, 'login_privileges'),
    ({'auth_superuser': True}, 'authenticated_superuser'),
    ({'auth_bypass': True}, 'authenticated_bypassrls'),
    ({'auth_createdb': True}, 'authenticated_createdb'),
    ({'auth_createrole': True}, 'authenticated_createrole'),
    ({'auth_replication': True}, 'authenticated_replication'),
    ({'auth_no_memberships': False}, 'authenticated_memberships'),
    ({'auth_owns_no_table': False}, 'authenticated_owns_tables'),
    ({'jwt_claims': '{"sub":"x"}'}, 'jwt_claims'),
    ({'jwt_sub': 'x'}, 'jwt_claim_sub'),
    ({'search_path': 'pg_temp, public'}, 'search_path'),
    ({'row_security': 'off'}, 'row_security'),
    ({'no_temp_relations': False}, 'temp_relations'),
    ({'tenant': 't'}, 'tenant_guc_before_scope'),
))
def test_probe_refuses_each_unsafe_value(overrides, reason):
    assert session._identity_problem(_row(**overrides), tenant=None) == reason
