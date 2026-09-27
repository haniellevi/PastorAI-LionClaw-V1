"""Independent audio-to-official-report proof, synthetic bytes and fake HTTP."""
import datetime as dt
from types import SimpleNamespace
import pytest
from sqlalchemy import select, text
from app.db.models import (AgentActionProposal, AgentActionReceipt, CellReportAudioInput,
                           CelulaReuniao, Conversation, Message, Pessoa,
                           LlmCredential, WhatsappConnection)
from app.services import cell_report_audio_service as service
from app.services.cell_report_audio import decode_audio_bytes
from app.services.llm import AudioTranscriptionResult
from app.services.storage import StoredMedia, cell_report_audio_storage_path
from tests.cell_report_audio_samples import synthetic_wav
from tests.test_cell_report_v1b_worker_pg import (  # noqa: F401
    audio_turn, report_turn, s3_turn, msg_engine_fx, rls_database_url,
    _IGREJA, _rows, _run, _notice, _audio_inbound, _unexpected_media,
)
from tests.test_cell_report_v1a_worker_pg import _CommittedReceiptEvolution, _REPORT, _snapshot

pytestmark = pytest.mark.rls_integration


def _no_domain_lock(turn):
    # Independent transaction must acquire all relevant rows during each I/O.
    with turn.factory.begin() as session:
        assert session.execute(text("""select count(*) from pg_stat_activity
            where datname=current_database() and pid <> pg_backend_pid()
              and state like 'idle in transaction%'""")).scalar_one() == 0
        for model in (Conversation, CelulaReuniao, CellReportAudioInput):
            session.execute(select(model).where(model.igreja_id == _IGREJA).with_for_update(nowait=True)).all()


def _providers(turn, transcript=_REPORT, *, mime="audio/wav", statuses=()):
    raw = synthetic_wav(duration_ms=250)
    if mime.startswith("audio/ogg"):
        import subprocess
        raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "pipe",
            "-f", "wav", "-i", "pipe:0", "-c:a", "libopus", "-f", "ogg", "pipe:1"],
            input=raw, capture_output=True, check=True, timeout=5).stdout
    counts = dict(download=0, upload=0, transcribe=0, remove=0)
    objects = {}
    class Evolution(_CommittedReceiptEvolution):
        def get_audio_media_bytes_limited(self, instance, key, *, max_bytes, timeout_seconds):
            _no_domain_lock(turn)
            counts['download'] += 1
            assert max_bytes == 5*1024*1024 and timeout_seconds > 0
            return raw, mime
    class Storage:
        def upload_cell_report_audio(self, *, igreja_id, provider_message_sha256, mime_type, raw, deadline_seconds):
            _no_domain_lock(turn)
            counts['upload'] += 1
            path = cell_report_audio_storage_path(igreja_id, provider_message_sha256, mime_type)
            objects[path] = raw
            return StoredMedia(path=path, mime=mime_type, nome=None, tamanho=len(raw))
        def remove_tenant_media(self, igreja_id, paths):
            _no_domain_lock(turn)
            counts['remove'] += 1
            for path in paths:
                assert path.startswith(f'{igreja_id}/cell-report-audio/')
                objects.pop(path, None)
    def transcribe(provedor, api_key, **kwargs):
        _no_domain_lock(turn)
        counts['transcribe'] += 1
        assert 0 < kwargs['timeout_seconds'] <= 180
        assert kwargs['max_retries'] == 0 and kwargs['require_real_result'] is True
        return AudioTranscriptionResult(texto=transcript, duracao_segundos=.25, custo=.000025)
    return SimpleNamespace(evolution=Evolution(turn, *statuses), storage=Storage(), transcribe=transcribe,
                           counts=counts, objects=objects, mime=mime)


def _consented_audio(turn, providers):
    _notice(turn, providers.evolution, 'V1B-FULL-NOTICE')
    _run(turn, 'V1B-FULL-ACCEPT', 'ACEITO AUDIO', providers.evolution)
    outcome = _audio_inbound(turn, 'V1B-FULL-AUDIO', _unexpected_media, mime=providers.mime)
    from app.workers import queue_worker
    outcome.claim_id = 'claim-v1b-full-audio'
    assert queue_worker.run_agent_for_message(turn.factory, outcome,
        evolution_client=providers.evolution) is queue_worker.AgentRunDisposition.COMPLETED
    return outcome


@pytest.mark.parametrize("mime", ("audio/wav", "audio/ogg; codecs=opus"))
def test_v1b_real_audio_summary_text_confirmation_receipt_and_purge(audio_turn, mime):
    providers = _providers(audio_turn, mime=mime)
    outcome = _consented_audio(audio_turn, providers)
    dispatched = service.dispatch_cell_report_audio_inputs(audio_turn.factory,
        evolution_client=providers.evolution, storage=providers.storage,
        decoder=decode_audio_bytes, transcriber=providers.transcribe, limit=1)
    assert providers.counts['transcribe'] == 1, (dispatched, providers.counts,
        [(row.state, row.terminal_reason) for row in _rows(audio_turn, CellReportAudioInput)])
    assert len([p for p in _rows(audio_turn, AgentActionProposal) if p.state == 'pendente']) == 1
    assert _snapshot(audio_turn)[0] == 'pendente'
    with audio_turn.factory() as session:
        inbound = session.get(Message, outcome.inbound_message_id)
        assert inbound.tipo == 'audio' and inbound.texto is None
    _run(audio_turn, 'V1B-FULL-SIM', 'SIM', providers.evolution)
    assert _snapshot(audio_turn)[0] == 'enviado'
    assert len(_rows(audio_turn, AgentActionReceipt)) == 1
    assert providers.evolution.committed_receipts == 1
    assert all(row.transcript_text is None and row.transcript_sha256 is None
               for row in _rows(audio_turn, CellReportAudioInput))
    before = _snapshot(audio_turn)
    service.purge_cell_report_audio_inputs(audio_turn.factory, storage=providers.storage,
        now=dt.datetime.now(dt.timezone.utc)+dt.timedelta(hours=25), limit=10)
    assert len(providers.objects) == 0, tuple(providers.objects)
    assert _snapshot(audio_turn) == before
    service.purge_cell_report_audio_inputs(audio_turn.factory, storage=providers.storage,
        now=dt.datetime.now(dt.timezone.utc)+dt.timedelta(hours=26), limit=10)
    assert len(_rows(audio_turn, AgentActionReceipt)) == 1
    assert providers.counts['transcribe'] == 1
    assert all(row.transcript_text is None for row in _rows(audio_turn, CellReportAudioInput))



@pytest.mark.parametrize('retries', (1, 2))
def test_v1b_consented_audio_queue_turn_never_enters_text_router(audio_turn, monkeypatch, retries):
    from app.agent import privileged_turn
    from app.workers import queue_worker
    providers = _providers(audio_turn)
    outcome = _consented_audio(audio_turn, providers)
    outcome.claim_id = 'claim-v1b-consented-audio'
    text_calls = []
    def unexpected_text(*args, **kwargs):
        text_calls.append('text')
        return queue_worker.AgentRunDisposition.COMPLETED
    monkeypatch.setattr(privileged_turn, '_run_enabled_turn', unexpected_text)
    monkeypatch.setattr(queue_worker, '_run_active_tier_a_turn', unexpected_text)
    before = list(providers.evolution.calls)
    for _ in range(retries):
        assert queue_worker.run_agent_for_message(audio_turn.factory, outcome,
            evolution_client=providers.evolution) is queue_worker.AgentRunDisposition.COMPLETED
    assert text_calls == []
    assert providers.evolution.calls == before
    job = next(row for row in _rows(audio_turn, CellReportAudioInput)
               if row.inbound_message_id == outcome.inbound_message_id)
    assert job.state == 'pendente' and job.transcription_attempts == 0
    with audio_turn.factory() as session:
        assert session.get(Conversation, audio_turn.conversation_id).estado == 'ia'
    _dispatch(audio_turn, providers)
    assert providers.counts['transcribe'] == 1
    assert len([row for row in _rows(audio_turn, AgentActionProposal) if row.state == 'pendente']) == 1


def _dispatch(turn, providers):
    return service.dispatch_cell_report_audio_inputs(turn.factory,
        evolution_client=providers.evolution, storage=providers.storage,
        decoder=decode_audio_bytes, transcriber=providers.transcribe, limit=1)


@pytest.mark.parametrize('model', (Conversation, Pessoa, CelulaReuniao, LlmCredential, WhatsappConnection))
def test_v1b_busy_anchor_defers_without_losing_audio(audio_turn, model):
    providers = _providers(audio_turn)
    outcome = _consented_audio(audio_turn, providers)
    with audio_turn.factory.begin() as blocker:
        blocker.execute(select(model).where(model.igreja_id == _IGREJA).with_for_update()).all()
        attempt = service._claim_next_audio_input(audio_turn.factory, _IGREJA,
            now=dt.datetime.now(dt.timezone.utc))
        assert attempt.claim is None
        row = next(row for row in _rows(audio_turn, CellReportAudioInput)
                   if row.inbound_message_id == outcome.inbound_message_id)
        assert row.state == 'pendente' and row.transcription_attempts == 0
    _dispatch(audio_turn, providers)
    assert providers.counts['transcribe'] == 1


def test_v1b_two_dispatchers_cannot_claim_same_paid_attempt(audio_turn):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    providers = _providers(audio_turn)
    _consented_audio(audio_turn, providers)
    barrier = Barrier(2)
    def claim_once():
        barrier.wait(timeout=5)
        return service._claim_next_audio_input(audio_turn.factory, _IGREJA,
            now=dt.datetime.now(dt.timezone.utc)).claim
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim_once) for _ in range(2)]
        claims = [future.result(timeout=15) for future in futures]
    assert sum(claim is not None for claim in claims) == 1
    assert sum(row.transcription_attempts for row in _rows(audio_turn, CellReportAudioInput)) == 1
    assert providers.counts['transcribe'] == 0


def test_v1b_temporary_contention_after_claim_is_not_revocation(audio_turn):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    from sqlalchemy import event
    import time
    providers = _providers(audio_turn)
    _consented_audio(audio_turn, providers)
    claim = service._claim_next_audio_input(audio_turn.factory, _IGREJA,
        now=dt.datetime.now(dt.timezone.utc)).claim
    assert claim is not None
    attempted = Event()
    def observe(_conn, _cursor, statement, _params, _context, _many):
        if (current_thread().name.startswith('v1b-preflight')
                and 'from conversations' in statement.lower() and 'for update' in statement.lower()):
            attempted.set()
    event.listen(audio_turn.engine, 'before_cursor_execute', observe)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='v1b-preflight') as pool:
            with audio_turn.factory.begin() as blocker:
                blocker.execute(select(Conversation).where(
                    Conversation.id == audio_turn.conversation_id).with_for_update()).scalar_one()
                future = pool.submit(service._run_audio_provider_chain, audio_turn.factory, claim,
                    evolution_client=providers.evolution, storage=providers.storage,
                    decoder=decode_audio_bytes, transcriber=providers.transcribe)
                assert attempted.wait(5)
                time.sleep(.1)
            future.result(timeout=15)
    finally:
        event.remove(audio_turn.engine, 'before_cursor_execute', observe)
    if providers.counts['transcribe'] == 0:
        _dispatch(audio_turn, providers)
    assert providers.counts['transcribe'] == 1
    assert len(_rows(audio_turn, AgentActionProposal)) == 1


@pytest.mark.parametrize('boundary', ('upload', 'transcribe'))
def test_v1b_short_contention_between_provider_phases_preserves_report(audio_turn, boundary):
    from threading import Event, Thread, Timer
    providers = _providers(audio_turn)
    _consented_audio(audio_turn, providers)
    ready, release = Event(), Event()
    holders = []
    def hold_briefly():
        def hold():
            with audio_turn.factory.begin() as session:
                session.execute(select(Conversation).where(
                    Conversation.id == audio_turn.conversation_id).with_for_update()).scalar_one()
                ready.set()
                assert release.wait(5)
        holder = Thread(target=hold)
        holders.append(holder)
        holder.start()
        assert ready.wait(5)
        timer = Timer(.3, release.set)
        holders.append(timer)
        timer.start()
    if boundary == 'upload':
        original = providers.storage.upload_cell_report_audio
        def upload(**kwargs):
            result = original(**kwargs)
            hold_briefly()
            return result
        providers.storage.upload_cell_report_audio = upload
    else:
        original = providers.transcribe
        def transcribe(*args, **kwargs):
            result = original(*args, **kwargs)
            hold_briefly()
            return result
        providers.transcribe = transcribe
    try:
        _dispatch(audio_turn, providers)
    finally:
        release.set()
        for holder in holders:
            holder.join(timeout=5)
            assert not holder.is_alive()
    _dispatch(audio_turn, providers)
    assert providers.counts['transcribe'] == 1
    assert len(_rows(audio_turn, AgentActionProposal)) == 1


def test_v1b_budget_refusal_purges_uploaded_object_without_transcribing(audio_turn, monkeypatch):
    providers = _providers(audio_turn)
    outcome = _consented_audio(audio_turn, providers)
    monkeypatch.setattr(service, 'reserve_audio_transcription_budget', lambda *a, **k: None)
    _dispatch(audio_turn, providers)
    row = next(row for row in _rows(audio_turn, CellReportAudioInput)
               if row.inbound_message_id == outcome.inbound_message_id)
    assert providers.counts['transcribe'] == 0
    assert row.state not in ('pendente', 'processando', 'transcrita')
    service.purge_cell_report_audio_inputs(audio_turn.factory, storage=providers.storage, limit=10)
    assert len(providers.objects) == 0, tuple(providers.objects)


@pytest.mark.parametrize('boundary', ('gate', 'expired', 'lease_expired',
                                      'credential_disabled', 'connection_offline'))
def test_v1b_claim_does_not_authorize_later_egress(audio_turn, monkeypatch, boundary):
    providers = _providers(audio_turn)
    _consented_audio(audio_turn, providers)
    claim = service._claim_next_audio_input(audio_turn.factory, _IGREJA,
        now=dt.datetime.now(dt.timezone.utc)).claim
    assert claim is not None
    if boundary == 'gate':
        monkeypatch.setenv('CELL_REPORT_AUDIO_ENABLED_IGREJA_IDS', '')
    elif boundary in ('expired', 'lease_expired'):
        with audio_turn.factory.begin() as session:
            row = session.get(CellReportAudioInput, claim.input_id)
            if boundary == 'expired':
                row.received_at -= dt.timedelta(hours=23)
                row.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
            else:
                row.lease_until = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
    else:
        with audio_turn.factory.begin() as session:
            if boundary == 'credential_disabled':
                row = session.execute(select(LlmCredential).where(LlmCredential.igreja_id == _IGREJA)).scalar_one()
                row.ativo = False
            else:
                row = session.execute(select(WhatsappConnection).where(WhatsappConnection.igreja_id == _IGREJA)).scalar_one()
                row.status = 'offline'
    service._run_audio_provider_chain(audio_turn.factory, claim,
        evolution_client=providers.evolution, storage=providers.storage,
        decoder=decode_audio_bytes, transcriber=providers.transcribe)
    assert providers.counts == dict(download=0, upload=0, transcribe=0, remove=0)


@pytest.mark.parametrize('reason', ('revoke', 'handoff', 'crisis', 'optout'))
def test_v1b_terminal_flow_erases_working_transcript_immediately(audio_turn, reason):
    transcript = {'handoff': 'quero falar com um pastor', 'crisis': 'quero me matar',
                  'optout': 'SAIR'}.get(reason, _REPORT)
    providers = _providers(audio_turn, transcript=transcript)
    outcome = _consented_audio(audio_turn, providers)
    _dispatch(audio_turn, providers)
    if reason == 'revoke':
        _run(audio_turn, 'V1B-REVOKE-AFTER-SUMMARY', 'PARAR AUDIO', providers.evolution)
    row = next(row for row in _rows(audio_turn, CellReportAudioInput)
               if row.inbound_message_id == outcome.inbound_message_id)
    assert row.transcript_text is None and row.transcript_sha256 is None
    assert not any(row.state == 'pendente' for row in _rows(audio_turn, AgentActionProposal))
    assert _snapshot(audio_turn)[0] == 'pendente'
    if reason == 'optout':
        from app.db.models import ConsentRecord
        with audio_turn.factory() as session:
            pessoa_id = session.get(Conversation, audio_turn.conversation_id).pessoa_id
            assert session.get(Pessoa, pessoa_id).optout is True
        assert any(row.termo_versao.startswith('optout:') for row in _rows(audio_turn, ConsentRecord))
    if reason == 'revoke':
        _run(audio_turn, 'V1B-SIM-AFTER-REVOKE', 'SIM', providers.evolution)
        assert _snapshot(audio_turn)[0] == 'pendente'
        assert _rows(audio_turn, AgentActionReceipt) == []


def test_v1b_summary_retry_reuses_transcript_without_second_provider_call(audio_turn):
    providers = _providers(audio_turn, statuses=('aceito', 'falhou_retentavel', 'aceito'))
    _consented_audio(audio_turn, providers)
    _dispatch(audio_turn, providers)
    proposal = _rows(audio_turn, AgentActionProposal)[0]
    assert proposal.delivered_at is None
    _dispatch(audio_turn, providers)
    assert _rows(audio_turn, AgentActionProposal)[0].delivered_at is not None
    assert providers.counts['transcribe'] == providers.counts['download'] == providers.counts['upload'] == 1


def test_v1b_expired_audio_cannot_deliver_pending_summary(audio_turn):
    providers = _providers(audio_turn, statuses=('aceito', 'falhou_retentavel', 'aceito'))
    outcome = _consented_audio(audio_turn, providers)
    _dispatch(audio_turn, providers)
    assert _rows(audio_turn, AgentActionProposal)[0].delivered_at is None
    sends = len(providers.evolution.calls)
    with audio_turn.factory.begin() as session:
        row = session.execute(select(CellReportAudioInput).where(
            CellReportAudioInput.inbound_message_id == outcome.inbound_message_id)).scalar_one()
        row.received_at -= dt.timedelta(hours=23)
        row.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
    _dispatch(audio_turn, providers)
    assert len(providers.evolution.calls) == sends
    assert _rows(audio_turn, AgentActionProposal)[0].delivered_at is None


def test_v1b_ambiguous_transcription_does_not_retry_paid_call(audio_turn):
    providers = _providers(audio_turn)
    _consented_audio(audio_turn, providers)
    def timeout(*args, **kwargs):
        _no_domain_lock(audio_turn)
        providers.counts['transcribe'] += 1
        raise TimeoutError('synthetic ambiguous timeout')
    providers.transcribe = timeout
    _dispatch(audio_turn, providers)
    _dispatch(audio_turn, providers)
    assert providers.counts['transcribe'] == 1
    assert _rows(audio_turn, AgentActionProposal) == []
    assert all(row.transcript_text is None for row in _rows(audio_turn, CellReportAudioInput))
    with audio_turn.factory() as session:
        assert session.get(Conversation, audio_turn.conversation_id).estado == 'humano'


def test_v1b_late_transcription_result_hands_off_without_staging(audio_turn, monkeypatch):
    providers = _providers(audio_turn)
    _consented_audio(audio_turn, providers)
    real_clock = service.time.monotonic
    elapsed = [0.0]
    monkeypatch.setattr(service.time, 'monotonic', lambda: real_clock() + elapsed[0])
    original = providers.transcribe
    def late(*args, **kwargs):
        result = original(*args, **kwargs)
        elapsed[0] = 181.0
        return result
    providers.transcribe = late
    _dispatch(audio_turn, providers)
    assert providers.counts['transcribe'] == 1
    assert _rows(audio_turn, AgentActionProposal) == []
    assert _rows(audio_turn, AgentActionReceipt) == []
    with audio_turn.factory() as session:
        assert session.get(Conversation, audio_turn.conversation_id).estado == 'humano'



@pytest.mark.parametrize('model', (Conversation, Pessoa))
@pytest.mark.parametrize('gates_off', (False, True))
@pytest.mark.parametrize('purge_first', (False, True))
@pytest.mark.parametrize('release_race', (False, True))
def test_v1b_deadline_handoff_survives_contention_and_retries_without_io(audio_turn, monkeypatch, model, gates_off, purge_first, release_race):
    from threading import Event, Thread
    providers = _providers(audio_turn)
    _consented_audio(audio_turn, providers)
    ready, release = Event(), Event()
    real_clock = service.time.monotonic
    real_utc = service._utc_now
    elapsed = [0.0]
    monkeypatch.setattr(service, '_utc_now', lambda now: real_utc(now) + dt.timedelta(seconds=elapsed[0]) if now is None else real_utc(now))
    monkeypatch.setattr(service.time, 'monotonic', lambda: real_clock() + elapsed[0])
    def hold():
        with audio_turn.factory.begin() as session:
            session.execute(select(model).where(model.igreja_id == _IGREJA).with_for_update()).all()
            ready.set()
            assert release.wait(15)
    holder = Thread(target=hold)
    original = providers.transcribe
    def late(*args, **kwargs):
        result = original(*args, **kwargs)
        holder.start()
        assert ready.wait(5)
        elapsed[0] = 181.0
        return result
    providers.transcribe = late
    original_handoff = service._handoff_audio_claim_failure
    def release_after_busy(*args, **kwargs):
        result = original_handoff(*args, **kwargs)
        if result is None and release_race:
            release.set()
            holder.join(timeout=5)
            assert not holder.is_alive()
        return result
    monkeypatch.setattr(service, '_handoff_audio_claim_failure', release_after_busy)
    try:
        _dispatch(audio_turn, providers)
        assert providers.counts['transcribe'] == 1
        assert _rows(audio_turn, AgentActionProposal) == []
    finally:
        release.set()
        holder.join(timeout=5)
    assert not holder.is_alive()
    before = dict(providers.counts)
    if gates_off:
        from app.services import cell_report_audio
        from app.config import get_settings
        monkeypatch.setattr(cell_report_audio, 'CELL_REPORT_AUDIO_APPROVED_RELEASE_ID', None)
        monkeypatch.setenv('CELL_REPORT_AUDIO_ENABLED_IGREJA_IDS', '')
        monkeypatch.setenv('ALLOW_REAL_SENDS', 'false')
        get_settings.cache_clear()
    if purge_first:
        elapsed[0] = 25 * 3600
        service.purge_cell_report_audio_inputs(audio_turn.factory, storage=providers.storage,
            now=service._utc_now(None), limit=10)
    _dispatch(audio_turn, providers)
    assert providers.counts['download'] == before['download']
    assert providers.counts['upload'] == before['upload']
    assert providers.counts['transcribe'] == 1
    with audio_turn.factory() as session:
        assert session.get(Conversation, audio_turn.conversation_id).estado == 'humano'
    assert _rows(audio_turn, AgentActionProposal) == []
    assert all(row.transcript_text is None for row in _rows(audio_turn, CellReportAudioInput))


def test_v1b_audio_sim_never_confirms_a_pending_report(audio_turn):
    providers = _providers(audio_turn, transcript='SIM')
    _consented_audio(audio_turn, providers)
    _run(audio_turn, 'V1B-TEXT-REPORT-BEFORE-AUDIO-SIM', _REPORT, providers.evolution)
    assert len(_rows(audio_turn, AgentActionProposal)) == 1
    _dispatch(audio_turn, providers)
    assert _snapshot(audio_turn)[0] == 'pendente'
    assert _rows(audio_turn, AgentActionReceipt) == []


def test_v1b_purge_retries_with_flags_off_after_source_deletion(audio_turn, monkeypatch):
    providers = _providers(audio_turn)
    outcome = _consented_audio(audio_turn, providers)
    _dispatch(audio_turn, providers)
    with audio_turn.factory.begin() as session:
        session.delete(session.get(Message, outcome.inbound_message_id))
    monkeypatch.setenv('CELL_REPORT_AUDIO_ENABLED_IGREJA_IDS', '')
    original = providers.storage.remove_tenant_media
    def unavailable(*args, **kwargs):
        _no_domain_lock(audio_turn)
        raise OSError('synthetic storage outage')
    providers.storage.remove_tenant_media = unavailable
    now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=25)
    service.purge_cell_report_audio_inputs(audio_turn.factory, storage=providers.storage, now=now)
    assert providers.objects
    assert all(row.transcript_text is None for row in _rows(audio_turn, CellReportAudioInput))
    providers.storage.remove_tenant_media = original
    service.purge_cell_report_audio_inputs(audio_turn.factory, storage=providers.storage, now=now)
    assert len(providers.objects) == 0, tuple(providers.objects)


@pytest.mark.parametrize('change', ('gate', 'revoke', 'human'))
def test_v1b_provider_return_cannot_restore_revoked_authority(audio_turn, monkeypatch, change):
    providers = _providers(audio_turn)
    _consented_audio(audio_turn, providers)
    original = providers.transcribe
    def mutate_before_return(*args, **kwargs):
        result = original(*args, **kwargs)
        if change == 'gate':
            monkeypatch.setenv('CELL_REPORT_AUDIO_ENABLED_IGREJA_IDS', '')
        elif change == 'revoke':
            _run(audio_turn, 'V1B-REVOKE-IN-FLIGHT', 'PARAR AUDIO', providers.evolution)
        else:
            with audio_turn.factory.begin() as session:
                session.get(Conversation, audio_turn.conversation_id).estado = 'humano'
        return result
    providers.transcribe = mutate_before_return
    _dispatch(audio_turn, providers)
    assert providers.counts['transcribe'] == 1
    assert _rows(audio_turn, AgentActionProposal) == []
    assert all(row.transcript_text is None for row in _rows(audio_turn, CellReportAudioInput))
    assert _snapshot(audio_turn)[0] == 'pendente'


@pytest.mark.parametrize('ambiguous', (False, True))
def test_v1b_late_upload_after_purge_reopens_durable_cleanup(audio_turn, ambiguous):
    providers = _providers(audio_turn)
    _consented_audio(audio_turn, providers)
    original = providers.storage.upload_cell_report_audio
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=25)
    def late_upload(**kwargs):
        service.purge_cell_report_audio_inputs(audio_turn.factory, storage=providers.storage, now=future)
        # A provider can acknowledge/write after the original lease expired.
        result = original(**kwargs)
        if ambiguous:
            raise TimeoutError('synthetic upload committed without acknowledgement')
        return result
    providers.storage.upload_cell_report_audio = late_upload
    _dispatch(audio_turn, providers)
    assert providers.counts['transcribe'] == 0
    service.purge_cell_report_audio_inputs(audio_turn.factory, storage=providers.storage,
        now=future + dt.timedelta(hours=1))
    assert len(providers.objects) == 0, tuple(providers.objects)
    assert _rows(audio_turn, AgentActionProposal) == []


def test_v1b_old_delete_ack_cannot_close_cleanup_reopened_by_late_upload(audio_turn):
    providers = _providers(audio_turn)
    outcome = _consented_audio(audio_turn, providers)
    original = providers.storage.upload_cell_report_audio
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=25)
    excluded = tuple(row.id for row in _rows(audio_turn, CellReportAudioInput)
                     if row.inbound_message_id != outcome.inbound_message_id)
    old_claims = []
    def upload_after_delete(**kwargs):
        # Maintenance fences an expired provider claim before leasing its
        # physical delete. Keep this split to exercise the stale delete ACK.
        service.recover_expired_audio_handoffs(audio_turn.factory, now=future)
        claim, _, _ = service._claim_audio_purge(audio_turn.factory, _IGREJA,
            now=future, excluded_input_ids=excluded)
        assert claim is not None
        providers.storage.remove_tenant_media(_IGREJA, [claim.storage_path])
        old_claims.append(claim)
        return original(**kwargs)
    providers.storage.upload_cell_report_audio = upload_after_delete
    _dispatch(audio_turn, providers)
    assert len(old_claims) == 1 and providers.counts['transcribe'] == 0
    service._finish_audio_purge(audio_turn.factory, old_claims[0], now=future, removed=True)
    service.purge_cell_report_audio_inputs(audio_turn.factory, storage=providers.storage,
        now=future + dt.timedelta(hours=1))
    assert len(providers.objects) == 0, tuple(providers.objects)


def test_v1b_spelled_audio_reuses_v1a_paid_extraction_and_confirmation(audio_turn, monkeypatch):
    from tests.test_cell_report_v1a_extraction_pg import _fake_extractor, _WORDS
    calls = _fake_extractor(audio_turn, monkeypatch)
    providers = _providers(audio_turn, transcript=_WORDS)
    _consented_audio(audio_turn, providers)
    _dispatch(audio_turn, providers)
    assert calls == [{'presentes': 'dez', 'visitantes': 'dois', 'decisoes': 'uma', 'oferta': 'trinta reais'}]
    assert len(_rows(audio_turn, AgentActionProposal)) == 1
    _run(audio_turn, 'V1B-SPELLED-SIM', 'SIM', providers.evolution)
    assert _snapshot(audio_turn)[0] == 'enviado'
    assert len(_rows(audio_turn, AgentActionReceipt)) == 1


def test_v1b_text_correction_then_confirmation_purges_original_transcript(audio_turn):
    providers = _providers(audio_turn)
    _consented_audio(audio_turn, providers)
    _dispatch(audio_turn, providers)
    _run(audio_turn, 'V1B-TEXT-CORRECTION', 'Correção: presentes: 12', providers.evolution)
    _run(audio_turn, 'V1B-TEXT-CORRECTION-SIM', 'SIM', providers.evolution)
    assert _snapshot(audio_turn)[0] == 'enviado'
    assert all(row.transcript_text is None for row in _rows(audio_turn, CellReportAudioInput))


def test_v1b_three_transcriptions_and_four_extractions_are_independent_caps(audio_turn, monkeypatch):
    from tests.test_cell_report_v1a_extraction_pg import _fake_extractor
    from app.db.models import CellReportAudioReservation, CellReportAiReservation
    calls = _fake_extractor(audio_turn, monkeypatch,
        payload={'presentes': 10, 'visitantes': None, 'decisoes': None, 'oferta_centavos': None})
    providers = _providers(audio_turn, transcript='Relatório: presentes: dez')
    _consented_audio(audio_turn, providers)
    _dispatch(audio_turn, providers)
    for index in range(2):
        _audio_inbound(audio_turn, f'V1B-AUDIO-CAP-{index}', _unexpected_media)
        _dispatch(audio_turn, providers)
    assert providers.counts['transcribe'] == 3, (
        [(row.state, row.terminal_reason) for row in _rows(audio_turn, CellReportAudioInput)],
        [(row.state, row.estimated_microusd, row.actual_microusd) for row in _rows(audio_turn, CellReportAiReservation)],
        calls)
    assert len(_rows(audio_turn, CellReportAudioReservation)) == 3
    assert len(calls) == 3
    # A fourth text extraction remains available independently of the audio cap.
    _run(audio_turn, 'V1B-FOURTH-TEXT-EXTRACTION', 'Correção: presentes: dez', providers.evolution)
    assert len(calls) == 4
    assert len(_rows(audio_turn, CellReportAiReservation)) == 4
    _audio_inbound(audio_turn, 'V1B-FOURTH-AUDIO-DENIED', _unexpected_media)
    _dispatch(audio_turn, providers)
    assert providers.counts['transcribe'] == 3
    assert len(_rows(audio_turn, CellReportAudioReservation)) == 3


def test_v1b_shared_church_daily_budget_denies_audio_before_openai(audio_turn):
    from app.services.cell_report_whatsapp import _locked_daily_budget
    providers = _providers(audio_turn)
    _consented_audio(audio_turn, providers)
    now = dt.datetime.now(dt.timezone.utc)
    with audio_turn.factory.begin() as session:
        budget = _locked_daily_budget(session, igreja_id=_IGREJA, budget_day=now.date(), now=now)
        budget.settled_microusd = 2_000_000
    _dispatch(audio_turn, providers)
    assert providers.counts['transcribe'] == 0
    assert _rows(audio_turn, AgentActionProposal) == []


def test_v1a_text_extraction_survives_audio_schema_not_installed(audio_turn, monkeypatch):
    from tests.test_cell_report_v1a_extraction_pg import _fake_extractor, _WORDS
    from app.services import cell_report_audio
    monkeypatch.setattr(cell_report_audio, 'CELL_REPORT_AUDIO_APPROVED_RELEASE_ID', None)
    with audio_turn.factory.begin() as session:
        session.execute(text('DROP TABLE msg_idemp1.cell_report_audio_reservations, '
            'msg_idemp1.cell_report_audio_inputs, msg_idemp1.cell_report_audio_consent_events, '
            'msg_idemp1.cell_report_audio_notices'))
    calls = _fake_extractor(audio_turn, monkeypatch)
    providers = _providers(audio_turn)
    _run(audio_turn, 'V1A-WITHOUT-AUDIO-SCHEMA', _WORDS, providers.evolution)
    assert len(calls) == 1
    assert len(_rows(audio_turn, AgentActionProposal)) == 1
    assert providers.counts['download'] == providers.counts['upload'] == providers.counts['transcribe'] == 0
