"""Independent V1b SQL proof using only the guarded disposable PG17 database."""
from pathlib import Path
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.test_cell_report_v1a_migration_pg import (  # noqa: F401
    _apply, _worker, exact_s3_database, rls_database_url, v1a_sql,
)

pytestmark = pytest.mark.rls_integration
_MIGRATIONS = Path(__file__).parents[1] / "migrations"
_SQL = _MIGRATIONS / "20260927_210000_cell_report_audio_v1b.sql"
_TABLES = (
    "cell_report_audio_notices", "cell_report_audio_consent_events",
    "cell_report_audio_inputs", "cell_report_audio_reservations",
)


def _seed_audio(connection, parent):
    p = dict(parent, **{key: uuid.uuid4() for key in ("audio", "notice", "consent", "audio_reservation")})
    statements = (
        """insert into cell_report_audio_notices
            (id,igreja_id,pessoa_id,conversation_id,notice_message_id,version,state,created_at,delivered_at)
            values(:notice,:tenant,:person,:conversation,:message,'synthetic-v1','entregue',now(),now())""",
        """insert into cell_report_audio_consent_events
            (id,igreja_id,pessoa_id,conversation_id,source_message_id,notice_id,command,version,occurred_at)
            values(:consent,:tenant,:person,:conversation,:message,:notice,'aceito','synthetic-v1',now())""",
        """insert into cell_report_audio_inputs
            (id,igreja_id,conversation_id,pessoa_id,inbound_message_id,
             live_conversation_id,live_pessoa_id,live_message_id,
             provider_message_sha256,storage_path,state,transcription_attempts,
             purge_state,purge_attempts,received_at,expires_at,updated_at)
            values(:audio,:tenant,:conversation,:person,:message,
                   :conversation,:person,:message,repeat('a',64),
                   cast(:tenant as text)||'/cell-report-audio/'||cast(:audio as text),
                   'pendente',0,'ativa',0,now(),now()+interval '24 hours',now())""",
        """insert into cell_report_audio_reservations
            (id,igreja_id,audio_input_id,reuniao_id,budget_id,audio_number,
             budget_day,cost_version,state,estimated_microusd,created_at)
            values(:audio_reservation,:tenant,:audio,:meeting,:budget,1,
                   current_date,'synthetic-v1','reservada',12000,now())""",
    )
    for statement in statements:
        connection.execute(text(statement), p)
    return p


@pytest.fixture
def v1b_sql(v1a_sql):
    engine, a, b = v1a_sql
    _apply(engine, _SQL.read_text())
    with engine.begin() as c:
        own, other = _seed_audio(c, a), _seed_audio(c, b)
    return engine, own, other


def test_v1b_exact_sql_is_idempotent_and_restores_minimal_acl(v1b_sql):
    engine, _, _ = v1b_sql
    with engine.begin() as c:
        before = {table: c.execute(text("select cast(:t as regclass)::oid"), {"t": table}).scalar_one() for table in _TABLES}
        for table in _TABLES:
            c.exec_driver_sql(f"grant delete on {table} to authenticated")
    _apply(engine, _SQL.read_text())
    with engine.connect() as c:
        for table in _TABLES:
            assert c.execute(text("select cast(:t as regclass)::oid"), {"t": table}).scalar_one() == before[table]
            assert c.exec_driver_sql(f"select count(*) from {table}").scalar_one() == 2
            assert c.execute(text("select relrowsecurity and relforcerowsecurity from pg_class where oid=cast(:t as regclass)"), {"t": table}).scalar_one()
            assert not c.execute(text("select has_table_privilege('authenticated',:t,'DELETE')"), {"t": table}).scalar_one()
            for role in ("anon", "agent_runtime"):
                assert not c.execute(text("select has_table_privilege(:r,:t,'SELECT')"), {"r": role, "t": table}).scalar_one()


@pytest.mark.parametrize("table", _TABLES)
def test_v1b_worker_sees_only_own_tenant_and_cannot_touch_other(v1b_sql, table):
    engine, a, b = v1b_sql
    with engine.begin() as c:
        _worker(c, a["tenant"])
        assert c.exec_driver_sql(f"select count(*) from {table}").scalar_one() == 1
        assert c.execute(text(f"update {table} set igreja_id=:tenant where igreja_id=:tenant"), {"tenant": b["tenant"]}).rowcount == 0


@pytest.mark.parametrize("table", _TABLES)
def test_v1b_panel_identity_has_no_private_audio_state(v1b_sql, table):
    engine, a, _ = v1b_sql
    with engine.begin() as c:
        _worker(c, a["tenant"], subject="clerk-synthetic")
        assert c.exec_driver_sql(f"select count(*) from {table}").scalar_one() == 0
        assert c.execute(text(f"update {table} set igreja_id=:tenant where igreja_id=:tenant"), {"tenant": a["tenant"]}).rowcount == 0


@pytest.mark.parametrize("table", _TABLES)
def test_v1b_worker_cannot_delete_cleanup_or_consent_state(v1b_sql, table):
    engine, a, _ = v1b_sql
    with pytest.raises(DBAPIError) as error:
        with engine.begin() as c:
            _worker(c, a["tenant"])
            c.execute(text(f"delete from {table} where igreja_id=:tenant"), {"tenant": a["tenant"]})
    assert error.value.orig.pgcode == "42501"


@pytest.mark.parametrize("column,other_key", (
    ("live_pessoa_id", "person"), ("live_conversation_id", "conversation"),
    ("live_message_id", "message"),
))
def test_v1b_live_audio_anchor_rejects_other_tenant(v1b_sql, column, other_key):
    engine, a, b = v1b_sql
    with pytest.raises(DBAPIError) as error:
        with engine.begin() as c:
            _worker(c, a["tenant"])
            c.execute(text(f"update cell_report_audio_inputs set {column}=:foreign where id=:id"), {"foreign": b[other_key], "id": a["audio"]})
    assert error.value.orig.pgcode == "23503"


@pytest.mark.parametrize("table,key,live_column", (
    ("messages", "message", "live_message_id"),
    ("conversations", "conversation", "live_conversation_id"),
    ("pessoas", "person", "live_pessoa_id"),
))
def test_v1b_source_deletion_preserves_cleanup_anchor(v1b_sql, table, key, live_column):
    engine, a, _ = v1b_sql
    with engine.begin() as c:
        before = c.execute(text("select storage_path,provider_message_sha256,inbound_message_id,received_at from cell_report_audio_inputs where id=:id"), {"id": a["audio"]}).one()
        c.execute(text(f"delete from {table} where id=:id"), {"id": a[key]})
        after = c.execute(text(f"select storage_path,provider_message_sha256,inbound_message_id,received_at,{live_column} from cell_report_audio_inputs where id=:id"), {"id": a["audio"]}).one()
        assert tuple(after[:4]) == tuple(before)
        assert after[4] is None


@pytest.mark.parametrize("column,other_key", (
    ("audio_input_id", "audio"), ("reuniao_id", "meeting"), ("budget_id", "budget"),
))
def test_v1b_audio_budget_foreign_keys_cannot_cross_tenants(v1b_sql, column, other_key):
    engine, a, b = v1b_sql
    with pytest.raises(DBAPIError) as error:
        with engine.begin() as c:
            _worker(c, a["tenant"])
            c.execute(text(f"update cell_report_audio_reservations set {column}=:foreign where id=:id"), {"foreign": b[other_key], "id": a["audio_reservation"]})
    assert error.value.orig.pgcode == "23503"


@pytest.mark.parametrize("assignment", (
    "expires_at=received_at + interval '24 hours 1 second'",
    "expires_at=received_at",
    "transcription_attempts=2",
    "provider_message_sha256='not-a-digest'",
    "purge_state='unknown'",
))
def test_v1b_database_rejects_invalid_retention_or_retranscription(v1b_sql, assignment):
    engine, a, _ = v1b_sql
    with pytest.raises(DBAPIError) as error:
        with engine.begin() as c:
            _worker(c, a["tenant"])
            c.execute(text(f"update cell_report_audio_inputs set {assignment} where id=:id"), {"id": a["audio"]})
    assert error.value.orig.pgcode == "23514"


def test_v1b_database_rejects_duplicate_inbound_across_rows(v1b_sql):
    engine, a, _ = v1b_sql
    with pytest.raises(DBAPIError) as error:
        with engine.begin() as c:
            _worker(c, a["tenant"])
            c.execute(text("""insert into cell_report_audio_inputs
                (id,igreja_id,conversation_id,pessoa_id,inbound_message_id,
                 provider_message_sha256,storage_path,state,transcription_attempts,
                 purge_state,purge_attempts,received_at,expires_at,updated_at)
                select gen_random_uuid(),igreja_id,conversation_id,pessoa_id,inbound_message_id,
                       provider_message_sha256,storage_path,'pendente',0,'ativa',0,
                       received_at,expires_at,updated_at
                from cell_report_audio_inputs where id=:id"""), {"id": a["audio"]})
    assert error.value.orig.pgcode == "23505"


def test_v1b_database_rejects_message_from_another_conversation_in_same_tenant(v1b_sql):
    engine, a, _ = v1b_sql
    conversation, message = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as c:
        c.execute(text("insert into conversations(id,igreja_id,pessoa_id,telefone,estado) values(:id,:tenant,:person,'5500000000002','ia')"), dict(a, id=conversation))
        c.execute(text("insert into messages(id,igreja_id,conversation_id,direcao,autor,texto) values(:id,:tenant,:conversation,'in','contato','sintético')"), dict(a, id=message, conversation=conversation))
    with pytest.raises(DBAPIError) as error:
        with engine.begin() as c:
            _worker(c, a["tenant"])
            c.execute(text("update cell_report_audio_inputs set live_message_id=:message where id=:id"), {"message": message, "id": a["audio"]})
    assert error.value.orig.pgcode == "23503"


def _another_audio(c, p):
    message, audio_input = uuid.uuid4(), uuid.uuid4()
    c.execute(text("insert into messages(id,igreja_id,conversation_id,direcao,autor,texto) values(:id,:tenant,:conversation,'in','contato',null)"), dict(p, id=message))
    c.execute(text("""insert into cell_report_audio_inputs
        (id,igreja_id,conversation_id,pessoa_id,inbound_message_id,
         live_conversation_id,live_pessoa_id,live_message_id,
         provider_message_sha256,storage_path,state,transcription_attempts,
         purge_state,purge_attempts,received_at,expires_at,updated_at)
        select :new_id,igreja_id,conversation_id,pessoa_id,:new_message,
               conversation_id,pessoa_id,:new_message,
               md5(cast(:new_message as text))||md5(cast(:new_id as text)),cast(igreja_id as text)||'/cell-report-audio/'||cast(:new_id as text),
               'pendente',0,'ativa',0,received_at,expires_at,updated_at
        from cell_report_audio_inputs where id=:old_id"""),
        {"new_id": audio_input, "new_message": message, "old_id": p["audio"]})
    return audio_input


def test_v1b_concurrent_reservations_cannot_reuse_report_audio_number(v1b_sql):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    engine, a, _ = v1b_sql
    with engine.begin() as c:
        inputs = [_another_audio(c, a) for _ in range(2)]
    barrier = threading.Barrier(2)
    def reserve(audio_input):
        try:
            with engine.begin() as c:
                _worker(c, a["tenant"])
                c.exec_driver_sql("set local statement_timeout='5s'")
                barrier.wait(timeout=5)
                # Bypass application locks deliberately: SQL owns the final limit.
                c.execute(text("""insert into cell_report_audio_reservations
                    (id,igreja_id,audio_input_id,reuniao_id,budget_id,audio_number,
                     budget_day,cost_version,state,estimated_microusd,created_at)
                    values(:id,:tenant,:input,:meeting,:budget,2,
                           current_date,'synthetic-v1','reservada',12000,now())"""),
                    dict(a, id=uuid.uuid4(), input=audio_input))
            return "committed"
        except DBAPIError as error:
            return error.orig.pgcode
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve, item) for item in inputs]
        outcomes = [future.result(timeout=10) for future in futures]
    assert sorted(outcomes) == ["23505", "committed"]
    with engine.connect() as c:
        assert c.execute(text("select count(*) from cell_report_audio_reservations where igreja_id=:tenant and reuniao_id=:meeting and audio_number=2"), a).scalar_one() == 1


def test_v1b_provider_digest_tombstone_rejects_replay_after_source_deletion(v1b_sql):
    engine, a, _ = v1b_sql
    with engine.begin() as c:
        c.execute(text("delete from messages where id=:message"), a)
    with pytest.raises(DBAPIError) as error:
        with engine.begin() as c:
            _worker(c, a["tenant"])
            c.execute(text("""insert into cell_report_audio_inputs
                (id,igreja_id,conversation_id,pessoa_id,inbound_message_id,
                 provider_message_sha256,storage_path,state,transcription_attempts,
                 purge_state,purge_attempts,received_at,expires_at,updated_at)
                select gen_random_uuid(),igreja_id,conversation_id,pessoa_id,gen_random_uuid(),
                       provider_message_sha256,storage_path,'pendente',0,'ativa',0,
                       received_at,expires_at,updated_at
                from cell_report_audio_inputs where id=:audio"""), a)
    assert error.value.orig.pgcode == "23505"
