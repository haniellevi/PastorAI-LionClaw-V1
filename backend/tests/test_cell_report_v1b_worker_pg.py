"""Independent V1b inbound and effect proof using fake providers and local PG."""
import datetime as dt
import pytest
from sqlalchemy import event, select, text

from app.db.models import AppUser, CelulaReuniao, CellReportAudioConsentEvent, CellReportAudioInput, CellReportAudioNotice, Conversation, Message
from app.domain.conversations import ParsedMessage
from app.domain.phone import normalize_phone
from app.services import cell_report_audio as audio
from app.services import cell_report_audio_service
from app.services.storage import StoredMedia
from app.workers import queue_worker as worker
from tests.test_cell_report_v1a_worker_pg import (  # noqa: F401
    _ClassifiedEvolution, _IGREJA, _rows, report_turn, s3_turn, msg_engine_fx, rls_database_url,
)

pytestmark = pytest.mark.rls_integration


@pytest.fixture
def audio_turn(report_turn, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(audio, "CELL_REPORT_AUDIO_APPROVED_RELEASE_ID", "synthetic-v1b-reviewed")
    monkeypatch.setenv("CELL_REPORT_AUDIO_ENABLED_IGREJA_IDS", str(_IGREJA))
    monkeypatch.setenv("WHATSAPP_PILOTO_IGREJA_IDS", str(_IGREJA))
    monkeypatch.setenv("ALLOW_REAL_SENDS", "true")
    monkeypatch.setattr(cell_report_audio_service, "get_settings", worker.get_settings)
    # The shared worker fixture creates the real ORM in its private schema.
    # Exact SQL/RLS is exercised separately against public by migration tests.
    monkeypatch.setattr(cell_report_audio_service, "audio_schema_available", lambda session:
        session.execute(text("select to_regclass('msg_idemp1.cell_report_audio_inputs') is not null")).scalar_one())
    get_settings.cache_clear()
    from app.db.models import WhatsappConnection
    with report_turn.factory.begin() as session:
        connection = session.execute(select(WhatsappConnection).where(WhatsappConnection.igreja_id == _IGREJA)).scalar_one()
        connection.status = "online"
    yield report_turn
    get_settings.cache_clear()


def _audio_inbound(turn, provider_id, media_resolver, *, mime="audio/wav"):
    parsed = ParsedMessage(instance="s3-synthetic", provider_message_id=provider_id,
        telefone=normalize_phone("5500000000000"), telefone_raw="5500000000000", texto=None,
        push_name=None, from_me=False, media_kind="audio", media_mime=mime)
    with turn.factory() as session:
        return worker.ingest_message_event_ex(session, parsed, media_resolver=media_resolver)


def _unexpected_media(*_args, **_kwargs):
    pytest.fail("V1b cannot call media providers before its durable inbound commit")


def test_v1b_ingestion_persists_real_audio_and_cleanup_intent_before_media_io(audio_turn):
    outcome = _audio_inbound(audio_turn, "V1B-REAL-INBOUND", _unexpected_media)
    assert outcome.result is worker.IngestionResult.REGISTERED
    rows = _rows(audio_turn, CellReportAudioInput)
    assert len(rows) == 1
    with audio_turn.factory() as session:
        inbound = session.get(Message, outcome.inbound_message_id)
        assert inbound.tipo == "audio" and not inbound.texto
        assert inbound.media_path is None
        assert rows[0].inbound_message_id == inbound.id
        assert rows[0].live_message_id == inbound.id
    assert rows[0].igreja_id == _IGREJA
    assert rows[0].state == "aguardando_aceite"
    assert rows[0].transcription_attempts == 0


def test_v1b_duplicate_audio_inbound_does_not_duplicate_job(audio_turn):
    _audio_inbound(audio_turn, "V1B-INBOUND-ONCE", _unexpected_media)
    duplicate = _audio_inbound(audio_turn, "V1B-INBOUND-ONCE", _unexpected_media)
    assert duplicate.result is worker.IngestionResult.DUPLICATE
    assert len(_rows(audio_turn, CellReportAudioInput)) == 1


def test_v1b_deleted_inbound_replay_cannot_recreate_audio_work(audio_turn):
    original = _audio_inbound(audio_turn, "V1B-DELETED-REPLAY", _unexpected_media)
    with audio_turn.factory.begin() as session:
        session.delete(session.get(Message, original.inbound_message_id))
    replay = _audio_inbound(audio_turn, "V1B-DELETED-REPLAY", _unexpected_media)
    assert replay.result is worker.IngestionResult.DUPLICATE
    assert len(_rows(audio_turn, CellReportAudioInput)) == 1
    assert _rows(audio_turn, CellReportAudioInput)[0].live_message_id is None



@pytest.mark.parametrize("purged", (False, True))
def test_v1b_simultaneous_replay_after_deleted_source_keeps_one_tombstone(audio_turn, purged):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    original = _audio_inbound(audio_turn, "V1B-TOMBSTONE-RACE", _unexpected_media)
    with audio_turn.factory.begin() as session:
        session.delete(session.get(Message, original.inbound_message_id))
        if purged:
            job = session.execute(select(CellReportAudioInput).where(
                CellReportAudioInput.igreja_id == _IGREJA)).scalar_one()
            job.state = "purgada"
            job.purge_state = "purgada"
            job.content_purged_at = dt.datetime.now(dt.timezone.utc)
    barrier = threading.Barrier(2)
    def replay():
        barrier.wait(timeout=5)
        return _audio_inbound(audio_turn, "V1B-TOMBSTONE-RACE", _unexpected_media)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(replay) for _ in range(2)]
        outcomes = [future.result(timeout=15) for future in futures]
    assert all(row.result is worker.IngestionResult.DUPLICATE for row in outcomes)
    assert all(row.inbound_message_id is None for row in outcomes)
    jobs = _rows(audio_turn, CellReportAudioInput)
    assert len(jobs) == 1 and jobs[0].live_message_id is None
    if purged:
        assert jobs[0].state == "purgada" and jobs[0].content_purged_at is not None

def test_v1b_simultaneous_same_audio_has_one_inbound_and_job(audio_turn):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    barrier = threading.Barrier(2)
    def ingest():
        barrier.wait(timeout=5)
        return _audio_inbound(audio_turn, "V1B-RACING-INBOUND", _unexpected_media).result
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(ingest) for _ in range(2)]
        outcomes = [future.result(timeout=15) for future in futures]
    assert outcomes.count(worker.IngestionResult.REGISTERED) == 1
    assert outcomes.count(worker.IngestionResult.DUPLICATE) == 1
    assert len(_rows(audio_turn, CellReportAudioInput)) == 1


def test_v1b_message_and_cleanup_intent_rollback_together(audio_turn, monkeypatch):
    original = cell_report_audio_service.enqueue_audio_input_after_inbound
    def crash_after_enqueue(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic process failure")
    monkeypatch.setattr(cell_report_audio_service, "enqueue_audio_input_after_inbound", crash_after_enqueue)
    with pytest.raises(RuntimeError, match="synthetic process failure"):
        _audio_inbound(audio_turn, "V1B-ROLLBACK", _unexpected_media)
    assert _rows(audio_turn, CellReportAudioInput) == []
    with audio_turn.factory() as session:
        assert session.execute(select(Message.id).where(Message.igreja_id == _IGREJA,
            Message.provider_message_id == "V1B-ROLLBACK")).first() is None


def test_v1b_inert_release_preserves_legacy_without_querying_audio_tables(audio_turn, monkeypatch):
    monkeypatch.setattr(audio, "CELL_REPORT_AUDIO_APPROVED_RELEASE_ID", None)
    statements, media_calls = [], []
    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())
    def legacy_media(*_args):
        media_calls.append(True)
        return StoredMedia(path=f"{_IGREJA}/legacy/synthetic.wav", mime="audio/wav", nome="audio.wav", tamanho=16)
    event.listen(audio_turn.engine, "before_cursor_execute", capture)
    try:
        outcome = _audio_inbound(audio_turn, "V1B-INERT-LEGACY", legacy_media)
    finally:
        event.remove(audio_turn.engine, "before_cursor_execute", capture)
    assert outcome.result is worker.IngestionResult.REGISTERED
    assert media_calls == [True]
    assert not any("cell_report_audio_" in statement for statement in statements)
    assert _rows(audio_turn, CellReportAudioInput) == []


@pytest.mark.parametrize("outside_scope", (
    "human_conversation", "assumed_conversation", "no_active_user",
    "no_pending_meeting", "ambiguous_meetings",
))
def test_v1b_preserves_inbox_audio_outside_authorized_report_scope(audio_turn, outside_scope):
    with audio_turn.factory.begin() as session:
        if outside_scope == "human_conversation":
            session.get(Conversation, audio_turn.conversation_id).estado = "humano"
        elif outside_scope == "assumed_conversation":
            session.get(Conversation, audio_turn.conversation_id).assumido_por = audio_turn.app_user_id
        elif outside_scope == "no_active_user":
            session.get(AppUser, audio_turn.app_user_id).pessoa_id = None
        else:
            meeting = session.get(CelulaReuniao, audio_turn.meeting_id)
            if outside_scope == "no_pending_meeting":
                meeting.status = "cancelada"
            else:
                session.add(CelulaReuniao(igreja_id=_IGREJA, celula_id=meeting.celula_id,
                    data=meeting.data - dt.timedelta(days=7), hora="19:00", status="planejada"))
    calls = []
    path = f"{_IGREJA}/legacy/synthetic.wav"
    def legacy_media(*_args):
        calls.append(True)
        return StoredMedia(path=path, mime="audio/wav", nome="audio.wav", tamanho=16)
    outcome = _audio_inbound(audio_turn, f"V1B-OUTSIDE-{outside_scope}", legacy_media)
    assert calls == [True]
    assert _rows(audio_turn, CellReportAudioInput) == []
    with audio_turn.factory() as session:
        assert session.get(Message, outcome.inbound_message_id).media_path == path


def _run(turn, provider_id, text, evolution):
    from tests.test_agent_privileged_turn_pg import _inbound
    outcome = _inbound(turn, provider_id, text)
    # Match the queue outcome as well as the persisted message anchor.
    outcome.texto = text
    disposition = worker.run_agent_for_message(turn.factory, outcome, evolution_client=evolution)
    assert disposition is worker.AgentRunDisposition.COMPLETED
    return outcome


def _notice(turn, evolution, provider_id="V1B-NOTICE-AUDIO"):
    outcome = _audio_inbound(turn, provider_id, _unexpected_media)
    # The queue assigns its durable claim before invoking the agent.
    outcome.claim_id = f"claim-{provider_id}"
    worker.run_agent_for_message(turn.factory, outcome, evolution_client=evolution)
    return outcome


def test_v1b_consent_requires_delivered_notice_and_explicit_new_text(audio_turn):
    evolution = _ClassifiedEvolution()
    first_audio = _notice(audio_turn, evolution)
    notices = _rows(audio_turn, CellReportAudioNotice)
    assert len(notices) == 1 and notices[0].state == "entregue"
    assert notices[0].delivered_at is not None
    assert any("ACEITO AUDIO" in body.upper() for _, _, body in evolution.calls)
    assert _rows(audio_turn, CellReportAudioConsentEvent) == []
    _run(audio_turn, "V1B-GENERIC-SIM", "SIM", evolution)
    assert _rows(audio_turn, CellReportAudioConsentEvent) == []
    accepted = _run(audio_turn, "V1B-EXPLICIT-ACCEPT", "ACEITO AUDIO", evolution)
    events = _rows(audio_turn, CellReportAudioConsentEvent)
    assert len(events) == 1
    assert events[0].command == "aceito"
    assert events[0].source_message_id == accepted.inbound_message_id
    assert events[0].version == audio.CELL_REPORT_AUDIO_CONSENT_VERSION
    # The pre-consent audio is not activated retroactively.
    old = next(row for row in _rows(audio_turn, CellReportAudioInput)
               if row.inbound_message_id == first_audio.inbound_message_id)
    assert old.state not in {"pendente", "processando", "transcrita"}
    assert old.transcription_attempts == 0


def test_v1b_audio_consent_revocation_is_versioned_and_idempotent(audio_turn):
    evolution = _ClassifiedEvolution()
    _notice(audio_turn, evolution)
    _run(audio_turn, "V1B-REVOKE-ACCEPT", "ACEITO AUDIO", evolution)
    revoked = _run(audio_turn, "V1B-REVOKE", "PARAR AUDIO", evolution)
    worker.run_agent_for_message(audio_turn.factory, revoked, evolution_client=evolution)
    events = _rows(audio_turn, CellReportAudioConsentEvent)
    revocations = [row for row in events if row.command == "revogado"]
    assert len(revocations) == 1
    assert revocations[0].source_message_id == revoked.inbound_message_id
    assert revocations[0].version == audio.CELL_REPORT_AUDIO_CONSENT_VERSION


@pytest.mark.parametrize("invalid_source", ("audio", "audio_with_caption", "wrong_text", "before_notice"))
def test_v1b_audio_acceptance_requires_explicit_text_created_after_notice(audio_turn, invalid_source):
    import uuid
    from tests.test_agent_privileged_turn_pg import _inbound
    source = _inbound(audio_turn, "V1B-INVALID-CONSENT", "ACEITO AUDIO")
    now = dt.datetime.now(dt.timezone.utc)
    with audio_turn.factory.begin() as session:
        conversation = session.get(Conversation, audio_turn.conversation_id)
        notice_message = Message(id=uuid.uuid4(), igreja_id=_IGREJA,
            conversation_id=conversation.id, direcao="out", autor="agente", tipo="texto",
            texto="Aviso sintético", criado_em=now-dt.timedelta(seconds=2))
        session.add(notice_message)
        session.flush()
        session.add(CellReportAudioNotice(id=uuid.uuid4(), igreja_id=_IGREJA,
            pessoa_id=conversation.pessoa_id, conversation_id=conversation.id,
            notice_message_id=notice_message.id, version=audio.CELL_REPORT_AUDIO_CONSENT_VERSION,
            state="entregue", created_at=now-dt.timedelta(seconds=2),
            delivered_at=now-dt.timedelta(seconds=1)))
        inbound = session.get(Message, source.inbound_message_id)
        if invalid_source == "audio":
            inbound.tipo, inbound.texto = "audio", None
        elif invalid_source == "audio_with_caption":
            inbound.tipo, inbound.texto = "audio", "ACEITO AUDIO"
        elif invalid_source == "wrong_text":
            inbound.tipo, inbound.texto = "texto", "SIM"
        else:
            inbound.criado_em = now-dt.timedelta(seconds=3)
        session.flush()
        result = cell_report_audio_service.record_audio_consent_command(session,
            igreja_id=_IGREJA, pessoa_id=conversation.pessoa_id,
            conversation_id=conversation.id, source_message_id=inbound.id,
            command=audio.AudioConsentCommand.ACCEPT, now=now)
        assert not result.handled
    assert _rows(audio_turn, CellReportAudioConsentEvent) == []


def test_v1b_missing_schema_preserves_legacy_inbox(audio_turn):
    calls = []
    def legacy_media(*_args):
        calls.append(True)
        return StoredMedia(path=f"{_IGREJA}/legacy/synthetic.wav", mime="audio/wav", nome="audio.wav", tamanho=16)
    with audio_turn.factory.begin() as session:
        session.execute(text("alter table cell_report_audio_inputs rename to cell_report_audio_inputs_unavailable"))
    try:
        outcome = _audio_inbound(audio_turn, "V1B-SCHEMA-MISSING", legacy_media)
        assert outcome.result is worker.IngestionResult.REGISTERED
        assert calls == [True]
        with audio_turn.factory() as session:
            assert session.get(Message, outcome.inbound_message_id).media_path.endswith("/legacy/synthetic.wav")
    finally:
        with audio_turn.factory.begin() as session:
            session.execute(text("alter table cell_report_audio_inputs_unavailable rename to cell_report_audio_inputs"))


@pytest.mark.parametrize("later_event", ("global_revocation", "global_reacceptance", "other_audio_version"))
def test_v1b_newer_consent_event_cannot_revive_old_audio_acceptance(audio_turn, later_event):
    import uuid
    from app.db.models import ConsentRecord
    from tests.test_agent_privileged_turn_pg import _inbound, _TERM
    evolution = _ClassifiedEvolution()
    _notice(audio_turn, evolution)
    _run(audio_turn, "V1B-OLD-ACCEPT", "ACEITO AUDIO", evolution)
    revoke_source = _inbound(audio_turn, "V1B-VERSIONED-REVOKE", "PARAR AUDIO")
    now = dt.datetime.now(dt.timezone.utc)
    with audio_turn.factory.begin() as session:
        person = session.get(Conversation, audio_turn.conversation_id).pessoa_id
        assert service_consent(session, person, now) is not None
        if later_event == "other_audio_version":
            session.add(CellReportAudioConsentEvent(id=uuid.uuid4(), igreja_id=_IGREJA,
                pessoa_id=person, conversation_id=audio_turn.conversation_id,
                source_message_id=revoke_source.inbound_message_id, command="revogado",
                version="synthetic-other-version", occurred_at=now))
        else:
            version = "optout:"+_TERM if later_event == "global_revocation" else _TERM
            session.add(ConsentRecord(igreja_id=_IGREJA, pessoa_id=person,
                termo_versao=version, aceite_em=now))
        session.flush()
        assert service_consent(session, person, now+dt.timedelta(seconds=1)) is None


def service_consent(session, person, now):
    return cell_report_audio_service._active_audio_consent(session,
        igreja_id=_IGREJA, pessoa_id=person, now=now)


@pytest.mark.parametrize("gate", ("audio_release", "audio_allowlist", "report_release", "privilege_release", "agent_inactive"))
def test_v1b_pending_notice_retry_obeys_current_cumulative_gates(audio_turn, monkeypatch, gate):
    from app.db.models import AgentConfig
    from app.services import cell_report_whatsapp, whatsapp_privilege
    outcome = _audio_inbound(audio_turn, "V1B-NOTICE-RETRY-GATE", _unexpected_media)
    outcome.claim_id = "claim-V1B-NOTICE-RETRY-GATE"
    evolution = _ClassifiedEvolution("falhou_retentavel", "aceito")
    with pytest.raises(worker.AgentReplyRetryable):
        worker.run_agent_for_message(audio_turn.factory, outcome, evolution_client=evolution)
    assert len(evolution.calls) == 1
    assert _rows(audio_turn, CellReportAudioNotice)[0].state == "preparado"
    if gate == "audio_release":
        monkeypatch.setattr(audio, "CELL_REPORT_AUDIO_APPROVED_RELEASE_ID", None)
    elif gate == "audio_allowlist":
        monkeypatch.setenv("CELL_REPORT_AUDIO_ENABLED_IGREJA_IDS", "")
    elif gate == "report_release":
        monkeypatch.setattr(cell_report_whatsapp, "CELL_REPORT_APPROVED_RELEASE_ID", None)
    elif gate == "privilege_release":
        monkeypatch.setattr(whatsapp_privilege, "PRIVILEGE_APPROVED_RELEASE_ID", None)
    else:
        with audio_turn.factory.begin() as session:
            config = session.execute(select(AgentConfig).where(AgentConfig.igreja_id == _IGREJA)).scalar_one()
            config.ativo = False
    worker.run_agent_for_message(audio_turn.factory, outcome, evolution_client=evolution)
    assert len(evolution.calls) == 1
    assert _rows(audio_turn, CellReportAudioNotice)[0].state != "entregue"


@pytest.mark.parametrize("closed_gate", ("human", "agent_inactive", "unlinked_actor", "optout"))
def test_v1b_new_audio_acceptance_requires_current_authorized_actor(audio_turn, closed_gate):
    from app.db.models import AgentConfig, Pessoa
    evolution = _ClassifiedEvolution()
    _notice(audio_turn, evolution)
    with audio_turn.factory.begin() as session:
        conversation = session.get(Conversation, audio_turn.conversation_id)
        if closed_gate == "human":
            conversation.estado = "humano"
        elif closed_gate == "agent_inactive":
            session.execute(select(AgentConfig).where(AgentConfig.igreja_id == _IGREJA)).scalar_one().ativo = False
        elif closed_gate == "unlinked_actor":
            session.get(AppUser, audio_turn.app_user_id).pessoa_id = None
        else:
            session.get(Pessoa, conversation.pessoa_id).optout = True
    denied = _run(audio_turn, "V1B-GATE-ACCEPT", "ACEITO AUDIO", evolution)
    assert not any(row.command == "aceito" for row in _rows(audio_turn, CellReportAudioConsentEvent))
    with audio_turn.factory.begin() as session:
        conversation = session.get(Conversation, audio_turn.conversation_id)
        conversation.estado = "ia"
        session.get(Pessoa, conversation.pessoa_id).optout = False
        session.get(AppUser, audio_turn.app_user_id).pessoa_id = conversation.pessoa_id
        session.execute(select(AgentConfig).where(AgentConfig.igreja_id == _IGREJA)).scalar_one().ativo = True
    worker.run_agent_for_message(audio_turn.factory, denied, evolution_client=evolution)
    assert not any(row.command == "aceito" for row in _rows(audio_turn, CellReportAudioConsentEvent))
