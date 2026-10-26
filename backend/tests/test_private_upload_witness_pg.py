"""Positive witness of a lost upload response, on the complete migration chain (PG17).

Real dedicated login (synthetic LOGIN), two churches, real policies, grants and
locks. Storage is the product client (``SupabaseStorage``) over a fake HTTP
server that commits rows like storage-api: user metadata from ``x-metadata``,
info from the stored row, strict DELETE. Only an exact token releases.
"""
import base64
import dataclasses
import datetime as dt
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import event, text

from app.services import storage as storage_module
from app.services.private_deletion import (
    PrivateStorageRuntime, begin_audio_upload, finish_audio_upload, process_storage_tasks,
)
from app.services.private_upload_witness import _release, reconcile_upload_attempts
from tests.test_private_deletion_pg import api, claim, private_data, runtime, scoped  # noqa: F401
from tests.test_uv_turmas_pg import rls_database_url, migrated_database, database  # noqa: F401

pytestmark = pytest.mark.rls_integration
MIGRATION = '20261030_110000_private_upload_attempt_witness.sql'
ROLE = 'private_storage_runtime'


class FakeStorageApi:
    """Rows like storage-api 6dd28b4: last commit wins, info reads the row."""

    def __init__(self, database, v):
        self.database, self.v = database, v
        self.rows, self.gets, self.deletes = {}, [], []
        self.on_commit = self.on_info = None
        self.lose_response = True
        self.info_override = None

    def handler(self, request):
        prefix = '/storage/v1/object/'
        path = request.url.path
        if request.method == 'POST' and path.startswith(prefix + 'whatsapp-media/'):
            key = path.removeprefix(prefix + 'whatsapp-media/')
            try:
                metadata = json.loads(base64.b64decode(request.headers.get('x-metadata', '')))
            except ValueError:
                metadata = {}  # Malformed metadata is silently dropped.
            self.rows[key] = dict(metadata=metadata if isinstance(metadata, dict) else {},
                                  version=str(uuid.uuid4()), body=request.content)
            if self.on_commit:
                self.on_commit(key, metadata)
            if self.lose_response:  # Committed, but the client never sees the answer.
                raise httpx.ReadTimeout('synthetic response lost after commit', request=request)
            return httpx.Response(200, json={'Key': f'whatsapp-media/{key}'})
        if request.method == 'GET' and path.startswith(prefix + 'info/authenticated/whatsapp-media/'):
            key = path.removeprefix(prefix + 'info/authenticated/whatsapp-media/')
            self.gets.append(key)
            if self.on_info:
                self.on_info(key)
            if self.info_override:
                return self.info_override(key)
            row = self.rows.get(key)
            if row is None:
                return httpx.Response(400, json=dict(statusCode='404', code='NoSuchKey', error='not_found'))
            return httpx.Response(200, json=dict(
                id=str(uuid.uuid4()), name=key, version=row['version'], bucket_id='whatsapp-media',
                size=len(row['body']), metadata=row['metadata'], archived_at=None,
                is_delete_marker=False, is_versioned=False))
        if request.method == 'DELETE' and path == prefix + 'whatsapp-media':
            prefixes = json.loads(request.content)['prefixes']
            self.deletes.extend(prefixes)
            for key in prefixes:
                self.rows.pop(key, None)
            return httpx.Response(200, json=[])
        return httpx.Response(400, json=dict(code='InvalidRequest'))


@pytest.fixture
def storage_api(database, private_data, monkeypatch):
    v = private_data
    api_server = FakeStorageApi(database, v)
    real_client = httpx.Client
    def streamed(request):  # Like a real transport: an unread body stream.
        response = api_server.handler(request)
        return httpx.Response(response.status_code, headers=response.headers,
                              stream=httpx.ByteStream(response.read()))
    monkeypatch.setattr(storage_module.httpx, 'Client',
                        lambda **kwargs: real_client(transport=httpx.MockTransport(streamed), **kwargs))
    # The info GET uses the async client under its total deadline; same fake server.
    real_async = httpx.AsyncClient
    monkeypatch.setattr(storage_module.httpx, 'AsyncClient',
                        lambda **kwargs: real_async(transport=httpx.MockTransport(streamed), **kwargs))
    api_server.real_async_client = real_async
    api_server.client = storage_module.SupabaseStorage(SimpleNamespace(
        supabase_url='https://storage.example.test', supabase_service_role_key='synthetic-key'))
    api_server.path = storage_module.cell_report_audio_storage_path(v['tenant'], 'a' * 64, 'audio/ogg')
    api_server.foreign = storage_module.cell_report_audio_storage_path(v['other'], 'a' * 64, 'audio/ogg')
    api_server.rows[api_server.foreign] = dict(metadata={'igreja12_attempt': str(uuid.uuid4())},
                                               version=str(uuid.uuid4()), body=b'synthetic other church')
    with database.begin() as c:
        c.execute(text('update cell_report_audio_inputs set storage_path=:p where id=:audio'), dict(v, p=api_server.path))
    api_server.claim = dataclasses.replace(claim(v), storage_path=api_server.path)
    return api_server


def _delete_conversation(database, v):
    with api(database, v) as client:
        deleted = client.delete(f"/conversations/{v['conv']}")
        assert deleted.status_code == 200, deleted.text
        v['receipt'] = deleted.json()['id']


def _lost_upload_during_deletion(database, v, runtime, api_server):
    """Product upload chain; deletion commits while the POST is in flight."""
    from app.services.cell_report_audio_service import _upload_owned_audio
    seen = {}
    def on_commit(key, metadata):
        # The token reached the database (committed) before this POST.
        with database.connect() as c:
            seen['db_token'] = c.execute(text('select attempt_token from private_deletion_uploads where source_id=:audio'),
                                         v).scalar_one()
        seen['marker'] = metadata
        _delete_conversation(database, v)
    api_server.on_commit = on_commit
    token = begin_audio_upload(runtime, api_server.claim)
    assert type(token) is uuid.UUID
    with pytest.raises(storage_module.StorageError) as error:
        _upload_owned_audio(PrivateStorageRuntime(runtime), api_server.claim, lambda: api_server.client.upload_cell_report_audio(
            igreja_id=v['tenant'], provider_message_sha256='a' * 64, mime_type='audio/ogg',
            raw=b'synthetic audio', deadline_seconds=10, attempt_token=token), token)
    assert not isinstance(error.value, storage_module.StorageLateSuccess)
    assert seen == dict(db_token=token, marker={'igreja12_attempt': str(token)})
    api_server.on_commit = None
    return token


def _ownership(database, v):
    with database.connect() as c:
        return c.execute(text('''select attempt_token,witness_check_at,witness_attempts
            from private_deletion_uploads where source_id=:audio'''), v).one_or_none()


def _receipt(database, v):
    with api(database, v) as client:
        return client.get(f"/igreja/private-deletions/{v['receipt']}").json()


def _assert_other_church_untouched(database, v, api_server, runtime):
    from app.db.privacy_storage_session import scope_private_storage
    assert api_server.foreign in api_server.rows and api_server.foreign not in api_server.deletes
    with database.connect() as c:
        assert c.execute(text('select count(*) from messages where igreja_id=:other'), v).scalar_one() == 1
    with runtime() as s:
        scope_private_storage(s, v['other'])
        for table in ('private_deletion_tasks', 'private_deletion_uploads'):
            assert s.execute(text(f'select count(*) from {table}')).scalar_one() == 0


def _no_runtime_lock_or_transaction(database):
    with database.connect() as c:
        open_tx = c.execute(text("""select count(*) from pg_stat_activity where usename=:r
            and state like 'idle in transaction%'"""), dict(r=ROLE)).scalar_one()
        held = c.execute(text("""select count(*) from pg_locks l join pg_stat_activity a on a.pid=l.pid
            where a.usename=:r and (l.locktype='advisory' or l.mode like '%Exclusive%')"""), dict(r=ROLE)).scalar_one()
        return open_tx, held


def test_lost_response_is_released_only_by_exact_witness_and_cleaned(database, private_data, runtime, storage_api):
    v = private_data
    now = dt.datetime.now(dt.UTC)
    token = _lost_upload_during_deletion(database, v, runtime, storage_api)
    assert storage_api.rows[storage_api.path]['metadata'] == {'igreja12_attempt': str(token)}
    assert _ownership(database, v)[0] == token
    # Without a witness, elapsed time never releases: the audio stays, receipt pending.
    for days in (2, 30):
        process_storage_tasks(runtime, storage=storage_api.client, now=now + dt.timedelta(days=days))
    assert storage_api.path in storage_api.rows and storage_api.path not in storage_api.deletes
    assert _receipt(database, v)['estado'] == 'pendente'
    # No lock or transaction of the login stays open during the Storage GET.
    during = []
    storage_api.on_info = lambda _key: during.append(_no_runtime_lock_or_transaction(database))
    assert reconcile_upload_attempts(runtime, storage=storage_api.client, now=now) == 1
    assert storage_api.gets == [storage_api.path] and during == [(0, 0)]
    assert _ownership(database, v) is None
    assert process_storage_tasks(runtime, storage=storage_api.client) == 1
    assert storage_api.path not in storage_api.rows and storage_api.path in storage_api.deletes
    done = _receipt(database, v)
    assert done['estado'] == 'concluido'
    assert done['camadas']['midias'] == dict(encontradas=2, apagadas=2, pendentes=0, falhas=0)
    _assert_other_church_untouched(database, v, storage_api, runtime)


@pytest.mark.parametrize('case', ('aborted', 'other_token', 'malformed_marker', 'versioned',
                                  'storage_down', 'timeout', 'legacy'))
def test_unproven_or_legacy_ownership_is_never_released(database, private_data, runtime, storage_api, case):
    v = private_data
    now = dt.datetime.now(dt.UTC)
    _lost_upload_during_deletion(database, v, runtime, storage_api)
    if case == 'aborted':  # Indistinguishable from in flight: no committed row.
        storage_api.rows.pop(storage_api.path)
    elif case == 'other_token':  # Another writer committed last (D2).
        storage_api.rows[storage_api.path]['metadata'] = {'igreja12_attempt': str(uuid.uuid4())}
    elif case == 'malformed_marker':  # Storage committed without metadata (C).
        storage_api.rows[storage_api.path]['metadata'] = {}
    elif case == 'versioned':
        storage_api.info_override = lambda key: httpx.Response(200, json=dict(
            name=key, version=str(uuid.uuid4()), bucket_id='whatsapp-media',
            metadata=storage_api.rows[key]['metadata'], archived_at=None,
            is_delete_marker=False, is_versioned=True))
    elif case == 'storage_down':
        storage_api.info_override = lambda _key: httpx.Response(503, json={'error': 'unavailable'})
    elif case == 'timeout':
        def slow(_key):
            raise httpx.ReadTimeout('synthetic info timeout')
        storage_api.info_override = slow
    else:  # Ownership from the previous release carries no token.
        with database.begin() as c:
            c.execute(text('update private_deletion_uploads set attempt_token=null where source_id=:audio'), v)
    for offset in (dt.timedelta(0), dt.timedelta(days=1), dt.timedelta(days=30), dt.timedelta(days=400)):
        assert reconcile_upload_attempts(runtime, storage=storage_api.client, now=now + offset) == 0
        process_storage_tasks(runtime, storage=storage_api.client, now=now + offset)
    assert _ownership(database, v) is not None
    assert storage_api.path not in storage_api.deletes
    assert len(storage_api.gets) == (0 if case == 'legacy' else 4)  # Legacy is never read.
    pending = _receipt(database, v)
    assert pending['estado'] == 'pendente' and pending['camadas']['midias']['pendentes'] == 1
    _assert_other_church_untouched(database, v, storage_api, runtime)


def test_unknown_reads_are_scheduled_with_bounded_backoff(database, private_data, runtime, storage_api):
    v = private_data
    now = dt.datetime.now(dt.UTC)
    _lost_upload_during_deletion(database, v, runtime, storage_api)
    storage_api.rows.pop(storage_api.path)
    assert reconcile_upload_attempts(runtime, storage=storage_api.client, now=now) == 0
    _, check_at, attempts = _ownership(database, v)
    assert attempts == 1 and check_at == now + dt.timedelta(seconds=60)
    # Same tick again: no second read of the same unknown.
    assert reconcile_upload_attempts(runtime, storage=storage_api.client, now=now + dt.timedelta(seconds=59)) == 0
    assert len(storage_api.gets) == 1
    assert reconcile_upload_attempts(runtime, storage=storage_api.client, now=now + dt.timedelta(seconds=60)) == 0
    assert len(storage_api.gets) == 2 and _ownership(database, v)[2] == 2
    with database.begin() as c:
        c.execute(text('update private_deletion_uploads set witness_attempts=40,witness_check_at=null where source_id=:audio'), v)
    assert reconcile_upload_attempts(runtime, storage=storage_api.client, now=now) == 0
    assert _ownership(database, v)[1] == now + dt.timedelta(hours=1)  # Capped; never an expiry.
    # The scheduled read is only a schedule: a later exact witness still releases.
    storage_api.rows[storage_api.path] = dict(metadata={'igreja12_attempt': str(_ownership(database, v)[0])},
                                              version=str(uuid.uuid4()), body=b'synthetic audio')
    assert reconcile_upload_attempts(runtime, storage=storage_api.client, now=now + dt.timedelta(hours=1)) == 1


def test_late_finish_after_witness_release_is_harmless(database, private_data, runtime, storage_api):
    v = private_data
    now = dt.datetime.now(dt.UTC)
    token = _lost_upload_during_deletion(database, v, runtime, storage_api)
    assert reconcile_upload_attempts(runtime, storage=storage_api.client, now=now) == 1
    assert process_storage_tasks(runtime, storage=storage_api.client) == 2  # Audio and image.
    assert _receipt(database, v)['estado'] == 'concluido'
    # The original writer's 2xx arrives now: CAS removes nothing, reopen re-deletes.
    finish_audio_upload(runtime, storage_api.claim, token)
    assert _ownership(database, v) is None
    assert process_storage_tasks(runtime, storage=storage_api.client, now=now + dt.timedelta(minutes=1)) == 1
    assert _receipt(database, v)['estado'] == 'concluido'
    assert storage_api.deletes.count(storage_api.path) == 2 and storage_api.path not in storage_api.rows


def test_stale_finish_and_stale_witness_never_remove_a_newer_attempt(database, private_data, runtime, storage_api):
    v = private_data
    first = begin_audio_upload(runtime, storage_api.claim)
    finish_audio_upload(runtime, storage_api.claim, first)  # Normal confirmed upload.
    second = begin_audio_upload(runtime, storage_api.claim)  # Real begin of a newer attempt.
    assert type(second) is uuid.UUID and second != first
    finish_audio_upload(runtime, storage_api.claim, first)  # Stale finish: CAS keeps the new one.
    finish_audio_upload(runtime, storage_api.claim, None)   # Legacy form matches only NULL rows.
    kept = _ownership(database, v)
    assert kept is not None and kept[0] == second
    _delete_conversation(database, v)
    with runtime() as s:
        job = s.execute(text('select * from private_storage_upload_witness_due(now(),10)')).mappings().one()
    from app.db.privacy_storage_session import scope_private_storage
    with runtime() as s:  # A delayed reconciler that witnessed only the first attempt.
        scope_private_storage(s, v['tenant'])
        assert _release(s, dict(job), first, storage_api.path) is False
        s.commit()
    assert _ownership(database, v)[0] == second
    with runtime() as s:
        scope_private_storage(s, v['tenant'])
        assert _release(s, dict(job), second, storage_api.path) is True
        s.commit()
    assert _ownership(database, v) is None


@pytest.mark.parametrize('change', ('new_attempt', 'path', 'concluded'))
def test_change_during_get_keeps_ownership(database, private_data, runtime, storage_api, change):
    v = private_data
    now = dt.datetime.now(dt.UTC)
    token = _lost_upload_during_deletion(database, v, runtime, storage_api)
    replacement = uuid.uuid4()
    def during_get(_key):
        with database.begin() as c:
            if change == 'new_attempt':  # Another attempt now owns the source.
                c.execute(text('update private_deletion_uploads set attempt_token=:t where source_id=:audio'),
                          dict(v, t=replacement))
            elif change == 'path':
                c.execute(text("""update private_deletion_tasks set storage_path=:p where source_id=:audio"""),
                          dict(v, p=f"{v['tenant']}/cell-report-audio/{'b' * 64}.ogg"))
            else:
                c.execute(text("""update private_deletion_tasks set state='concluida',storage_path=null
                    where source_id=:audio"""), v)
    storage_api.on_info = during_get
    assert reconcile_upload_attempts(runtime, storage=storage_api.client, now=now) == 0
    assert _ownership(database, v)[0] == (replacement if change == 'new_attempt' else token)


def test_two_reconcilers_release_once(database, private_data, runtime, storage_api):
    v = private_data
    now = dt.datetime.now(dt.UTC)
    _lost_upload_during_deletion(database, v, runtime, storage_api)
    start, results, errors = threading.Barrier(2), [], []
    def run():
        try:
            start.wait(5)
            results.append(reconcile_upload_attempts(runtime, storage=storage_api.client, now=now))
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
    workers = [threading.Thread(target=run) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(30)
    assert errors == [] and sorted(results) == [0, 1]
    assert len(storage_api.gets) == 1 and _ownership(database, v) is None
    # Both reach the release with the same token: the real locks + CAS allow one.
    token = uuid.uuid4()
    with database.begin() as c:
        c.execute(text('''insert into private_deletion_uploads(igreja_id,source_id,conversation_id,generation,attempt_token)
            values(:tenant,:audio,:conv,0,:t)'''), dict(v, t=token))
    with runtime() as s:
        job = dict(s.execute(text('select * from private_storage_upload_witness_due(:n,10)'), dict(n=now)).mappings().one())
    from app.db.privacy_storage_session import scope_private_storage
    barrier, released = threading.Barrier(2), []
    def release():
        with runtime() as s:
            scope_private_storage(s, v['tenant'])
            barrier.wait(5)
            released.append(_release(s, job, token, storage_api.path))
            s.commit()
    workers = [threading.Thread(target=release) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(30)
    assert sorted(released) == [False, True] and _ownership(database, v) is None


def _waiting_on_lock(database, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with database.connect() as c:
            if c.execute(text("""select count(*) from pg_stat_activity where usename=:r
                and wait_event_type='Lock'"""), dict(r=ROLE)).scalar_one():
                return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize('first', ('witness', 'finish'))
def test_witness_and_finish_serialize_without_deadlock(database, private_data, runtime, storage_api, first):
    from app.db.privacy_storage_session import scope_private_storage
    v = private_data
    now = dt.datetime.now(dt.UTC)
    token = _lost_upload_during_deletion(database, v, runtime, storage_api)
    with runtime() as s:
        job = dict(s.execute(text('select * from private_storage_upload_witness_due(:n,10)'), dict(n=now)).mappings().one())
    ready, proceed, outcome, errors = threading.Event(), threading.Event(), {}, []
    def witness(hold):
        try:
            with runtime() as s:
                scope_private_storage(s, v['tenant'])
                s.execute(text("select set_config('lock_timeout','10s',true)"))
                outcome['witness'] = _release(s, job, token, storage_api.path)
                if hold:
                    ready.set()
                    assert proceed.wait(10)
                s.commit()
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
    def held_finish_factory():
        s = runtime()
        event.listen(s, 'before_commit', lambda _s: (ready.set(), proceed.wait(10)))
        return s
    def finish(hold):
        try:
            finish_audio_upload(held_finish_factory if hold else runtime, storage_api.claim, token)
            outcome['finish'] = True
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
    holder = threading.Thread(target=witness if first == 'witness' else finish, args=(True,))
    holder.start()
    assert ready.wait(10)  # The holder has its receipt lock, task row and (CAS) delete.
    waiter = threading.Thread(target=finish if first == 'witness' else witness, args=(False,))
    waiter.start()
    assert _waiting_on_lock(database)  # Real lock wait, not a mock.
    proceed.set()
    holder.join(30)
    waiter.join(30)
    assert errors == [] and not holder.is_alive() and not waiter.is_alive()
    assert outcome == dict(witness=first == 'witness', finish=True)
    assert _ownership(database, v) is None
    with database.connect() as c:  # Reopen kept the task pending for a strict DELETE.
        assert c.execute(text("select state from private_deletion_tasks where source_id=:audio"), v).scalar_one() == 'pendente'
    assert process_storage_tasks(runtime, storage=storage_api.client, now=now + dt.timedelta(minutes=1)) == 2
    assert _receipt(database, v)['estado'] == 'concluido'


def test_temp_table_cannot_shadow_witness_or_finish(database, private_data, runtime, storage_api):
    v = private_data
    now = dt.datetime.now(dt.UTC)
    token = _lost_upload_during_deletion(database, v, runtime, storage_api)
    with runtime() as s:  # Session-lived TEMP tables named like the real ones.
        s.execute(text('''create temp table private_deletion_uploads(igreja_id uuid,source_id uuid,
            attempt_token uuid,witness_check_at timestamptz,witness_attempts integer)'''))
        s.execute(text('''create temp table private_deletion_tasks(id uuid,igreja_id uuid,receipt_id uuid,
            source_id uuid,state text,storage_path text,attempts integer,error_code text,next_attempt_at timestamptz)'''))
        s.commit()
    with runtime() as s:  # The pool hands back that same connection.
        assert s.execute(text("select to_regclass('pg_temp.private_deletion_uploads') is not null")).scalar_one()
    assert reconcile_upload_attempts(runtime, storage=storage_api.client, now=now) == 1
    assert _ownership(database, v) is None
    finish_audio_upload(runtime, storage_api.claim, token)
    with database.connect() as c:
        assert c.execute(text("select state from private_deletion_tasks where source_id=:audio"), v).scalar_one() == 'pendente'
    assert process_storage_tasks(runtime, storage=storage_api.client) == 2


def test_main_login_and_http_sessions_cannot_use_witness_functions(database, private_data, runtime, storage_api):
    v = private_data
    _lost_upload_during_deletion(database, v, runtime, storage_api)
    with database.connect() as c:
        check = lambda sql, **kw: c.execute(text(sql), kw).scalar_one()
        assert not check("select has_column_privilege(:r,'private_deletion_uploads','attempt_token','UPDATE')", r=ROLE)
        assert check("select has_column_privilege(:r,'private_deletion_uploads','witness_check_at','UPDATE')", r=ROLE)
        assert not check("select has_table_privilege(:r,'private_deletion_uploads','INSERT')", r=ROLE)
        for other in ('authenticated', 'anon', 'service_role'):
            for function in ('private_storage_begin_upload_attempt(uuid,uuid,uuid,bigint)',
                             'private_storage_upload_witness_due(timestamptz,integer)'):
                assert not check("select has_function_privilege(:r,:f,'EXECUTE')", r=other, f=function)
    for admin in (False, True):
        for sql in ('select * from private_storage_upload_witness_due(now(),10)',
                    'select private_storage_begin_upload_attempt(:t,:s,:c,0)'):
            with scoped(database, v['tenant'], admin=admin) as s:
                with pytest.raises(Exception) as error:
                    s.execute(text(sql), dict(t=v['tenant'], s=uuid.uuid4(), c=v['conv2']))
                assert getattr(error.value.orig, 'pgcode', None) == '42501'
    # The runtime cannot forge a token, and tenant B's runtime sees nothing of A.
    from app.db.privacy_storage_session import scope_private_storage
    with runtime() as s:
        scope_private_storage(s, v['tenant'])
        with pytest.raises(Exception) as error:
            s.execute(text('update private_deletion_uploads set attempt_token=gen_random_uuid()'))
        assert getattr(error.value.orig, 'pgcode', None) == '42501'
    with runtime() as s:
        scope_private_storage(s, v['other'])
        assert s.execute(text('update private_deletion_uploads set witness_attempts=0')).rowcount == 0
        with pytest.raises(Exception) as error:
            s.execute(text('select private_storage_begin_upload_attempt(:t,:s,:c,0)'),
                      dict(t=v['tenant'], s=uuid.uuid4(), c=v['conv2']))
        assert getattr(error.value.orig, 'pgcode', None) == '42501'
    with runtime() as s:
        with pytest.raises(Exception) as error:
            s.execute(text('select * from private_storage_upload_witness_due(now(),101)'))
        assert getattr(error.value.orig, 'pgcode', None) == '22023'


def _rollback_sql():
    from scripts import migrate
    block = (migrate.MIGRATIONS_DIR / MIGRATION).read_text().split('-- BEGIN;\n', 1)[1].split('-- COMMIT;', 1)[0]
    return '\n'.join(line[3:] if line.startswith('-- ') else line[2:] for line in block.splitlines())


def test_rollback_keeps_retained_ownership_and_reapplies_through_migrate(database, private_data, runtime, storage_api):
    from tests.test_uv_turmas_pg import ROOT
    v = private_data
    _lost_upload_during_deletion(database, v, runtime, storage_api)
    with database.begin() as c:
        c.exec_driver_sql(_rollback_sql(), execution_options={'no_parameters': True})
    with database.connect() as c:
        check = lambda sql, **kw: c.execute(text(sql), kw).scalar_one()
        assert check("""select count(*) from pg_proc where proname in
            ('private_storage_begin_upload_attempt','private_storage_upload_witness_due')""") == 0
        assert check("""select count(*) from information_schema.columns where table_name='private_deletion_uploads'
            and column_name in ('attempt_token','witness_check_at','witness_attempts')""") == 0
        assert check('select count(*) from schema_migrations where name=:n', n=MIGRATION) == 0
        # The retained ownership is now legacy: it still blocks the receipt.
        assert check('select count(*) from private_deletion_uploads where source_id=:audio', audio=v['audio']) == 1
        assert check("select has_function_privilege(:r,'private_storage_begin_upload(uuid,uuid,uuid,bigint)','EXECUTE')", r=ROLE)
    assert process_storage_tasks(runtime, storage=storage_api.client) == 1  # Image only.
    assert _receipt(database, v)['estado'] == 'pendente' and storage_api.path in storage_api.rows
    env = dict(os.environ, MIGRATION_DATABASE_URL=database.url.render_as_string(hide_password=False).replace(
        'postgresql+psycopg2:', 'postgresql:'))
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/migrate.py'), 'apply', MIGRATION, '--yes'],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    # Legacy stays out of reconciliation after reapply; a new attempt gets a token.
    assert reconcile_upload_attempts(runtime, storage=storage_api.client) == 0 and storage_api.gets == []
    assert _ownership(database, v)[0] is None


@pytest.mark.parametrize('first', ('reservation', 'finish'))
def test_read_reservation_holds_one_row_lock_and_never_cycles(database, private_data, runtime, storage_api, first):
    """The reservation locks only the ownership row and never waits while holding it."""
    from app.db.privacy_storage_session import scope_private_storage
    from app.services.private_upload_witness import _claim_read
    v = private_data
    now = dt.datetime.now(dt.UTC)
    token = _lost_upload_during_deletion(database, v, runtime, storage_api)
    with runtime() as s:
        job = dict(s.execute(text('select * from private_storage_upload_witness_due(:n,10)'), dict(n=now)).mappings().one())
    ready, proceed, outcome, errors = threading.Event(), threading.Event(), {}, []
    def reservation(hold):
        try:
            with runtime() as s:
                scope_private_storage(s, v['tenant'])
                s.execute(text("select set_config('lock_timeout','10s',true)"))
                outcome['reservation'] = _claim_read(s, job, now)
                if hold:
                    ready.set()
                    assert proceed.wait(10)
                s.commit()
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
    def held_finish_factory():
        s = runtime()
        event.listen(s, 'before_commit', lambda _s: (ready.set(), proceed.wait(10)))
        return s
    def finish(hold):
        try:
            finish_audio_upload(held_finish_factory if hold else runtime, storage_api.claim, token)
            outcome['finish'] = True
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
    holder = threading.Thread(target=reservation if first == 'reservation' else finish, args=(True,))
    holder.start()
    assert ready.wait(10)
    if first == 'reservation':
        # Cleanup never locks ownership rows: it runs while the reservation is open.
        assert process_storage_tasks(runtime, storage=storage_api.client) == 1  # Image only.
    waiter = threading.Thread(target=finish if first == 'reservation' else reservation, args=(False,))
    waiter.start()
    assert _waiting_on_lock(database)  # Real row-lock wait on the ownership.
    proceed.set()
    holder.join(30)
    waiter.join(30)
    assert errors == [] and not holder.is_alive() and not waiter.is_alive()
    assert outcome['finish'] is True and _ownership(database, v) is None
    # Reservation first: it got the token; finish first: the row was gone.
    assert outcome['reservation'] == ((token, storage_api.path) if first == 'reservation' else None)


def _failing_commit_factory(runtime, fail_on):
    """Real dedicated sessions; the ``fail_on``-th one raises before its COMMIT.

    Sessions of one reconcile: 1 discovery (no commit), 2 read reservation, 3 release.
    """
    opened = []
    def factory():
        s = runtime()
        opened.append(s)
        if len(opened) == fail_on:
            def fail(_session):
                raise RuntimeError('synthetic database failure before COMMIT')
            event.listen(s, 'before_commit', fail)
        return s
    return factory


@pytest.mark.parametrize('failure', ('reservation', 'release'))
def test_database_failure_before_commit_never_releases_or_reports_success(
        database, private_data, runtime, storage_api, failure):
    v = private_data
    now = dt.datetime.now(dt.UTC)
    token = _lost_upload_during_deletion(database, v, runtime, storage_api)
    factory = _failing_commit_factory(runtime, 2 if failure == 'reservation' else 3)
    assert reconcile_upload_attempts(factory, storage=storage_api.client, now=now) == 0  # No false success.
    kept = _ownership(database, v)
    assert kept is not None and kept[0] == token
    if failure == 'reservation':  # Rolled back: no GET, schedule untouched.
        assert storage_api.gets == [] and tuple(kept[1:]) == (None, 0)
    else:  # Exact witness read, release rolled back: only the schedule stands.
        assert storage_api.gets == [storage_api.path]
        assert tuple(kept[1:]) == (now + dt.timedelta(seconds=60), 1)
    with database.connect() as c:
        assert c.execute(text('select state from private_deletion_tasks where source_id=:audio'), v).scalar_one() == 'pendente'
    process_storage_tasks(runtime, storage=storage_api.client)
    assert storage_api.path not in storage_api.deletes and storage_api.path in storage_api.rows
    assert _receipt(database, v)['estado'] == 'pendente'
    # A failure only reschedules: the next due round releases normally and cleanup completes.
    later = now + dt.timedelta(seconds=60)
    assert reconcile_upload_attempts(runtime, storage=storage_api.client, now=later) == 1
    assert _ownership(database, v) is None
    assert process_storage_tasks(runtime, storage=storage_api.client) == 1
    assert storage_api.path in storage_api.deletes and _receipt(database, v)['estado'] == 'concluido'


def test_slow_storage_is_cut_and_cleanup_of_the_tick_continues(
        database, private_data, runtime, storage_api, monkeypatch):
    """Real loopback server trickling headers: the witness gives up at its deadline."""
    import socket
    import threading
    v = private_data
    _lost_upload_during_deletion(database, v, runtime, storage_api)
    monkeypatch.setattr(storage_module.httpx, 'AsyncClient', storage_api.real_async_client)
    monkeypatch.setattr(storage_module, '_ATTEMPT_INFO_TIMEOUT_SECONDS', 0.6)
    listener = socket.create_server(('127.0.0.1', 0))
    seen = {}
    def trickle():
        conn, _ = listener.accept()
        with conn:
            conn.recv(65536)
            try:
                for byte in b'HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n' * 50:
                    conn.sendall(bytes([byte]))
                    time.sleep(0.05)
            except OSError:
                seen['closed_by_client'] = True
        listener.close()
    server = threading.Thread(target=trickle, daemon=True)
    server.start()
    slow = storage_module.SupabaseStorage(SimpleNamespace(
        supabase_url=f'http://127.0.0.1:{listener.getsockname()[1]}', supabase_service_role_key='synthetic-key'))
    progress = []
    started = time.monotonic()
    assert reconcile_upload_attempts(runtime, storage=slow, progress=lambda: progress.append(time.monotonic())) == 0
    assert time.monotonic() - started < 0.6 + 1.0 and len(progress) == 1  # Heartbeat progress per job.
    server.join(5)
    assert seen == {'closed_by_client': True}
    assert _ownership(database, v) is not None  # A cut read proves nothing.
    # The rest of the tick runs right after: the image task of the same receipt is cleaned.
    assert process_storage_tasks(runtime, storage=storage_api.client) == 1
    assert _receipt(database, v)['estado'] == 'pendente'
