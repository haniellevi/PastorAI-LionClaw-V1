"""Synthetic audio through ingestion, real prayer router, domain and inbox RLS."""
import dataclasses
import uuid
import pytest
from sqlalchemy import select, text
from app.db.models import Message
from app.prayer.models import PrayerProposal, PrayerRequest
from app.workers.queue_worker import ingest_message_event_ex, run_agent_for_message
from tests.test_messages_inbound_idempotency import _parsed, _ClassifiedEvolution
from tests.test_prayer_privacy_pg import (  # noqa: F401
    private_prayer, prayer, msg_engine_fx, rls_database_url, TENANT,
    send, client_for, Storage, MARKER,
)

pytestmark = pytest.mark.rls_integration


def audio(p):
    from types import SimpleNamespace
    parsed = dataclasses.replace(
        _parsed(provider_message_id='prayer-audio-' + uuid.uuid4().hex,
                instance='prayer-test', telefone='5500000000000'),
        texto=None, media_kind='audio', media_mime='audio/ogg', media_nome='pedido.ogg',
    )
    path = f'{TENANT}/synthetic/prayer.ogg'
    with p.factory() as db:
        outcome = ingest_message_event_ex(
            db, parsed, media_resolver=lambda *args: SimpleNamespace(
                path=path, mime='audio/ogg', nome='pedido.ogg', tamanho=12),
        )
    return dataclasses.replace(outcome, claim_id='prayer-audio-claim'), path


def test_audio_collection_full_turn_retention_and_deletion(private_prayer, monkeypatch):
    import datetime as dt
    from app.prayer import policy
    p = private_prayer
    send(p, 'Quero iniciar pedido de oração')
    outcome, path = audio(p)
    mid = outcome.inbound_message_id
    # Privacy is already effective before the first audio worker executes.
    with client_for(p, 'admin') as client:
        rows = client.get(f'/conversations/{p.conv}/messages').json()['items']
        assert next(m for m in rows if m['id'] == str(mid))['texto'] == MARKER
    transport = _ClassifiedEvolution()
    run_agent_for_message(p.factory, outcome, evolution_client=transport)
    assert transport.calls
    with p.factory() as db:
        assert db.scalar(select(PrayerProposal.summary)) == 'Pedido de oração em áudio.'
        assert db.get(Message, mid).media_path == path
        assert db.scalar(text('select count(*) from cell_report_audio_inputs')) == 0
    send(p, 'Só pastores')
    send(p, 'SIM')
    with p.factory() as db:
        assert db.scalar(select(PrayerRequest.audience)) == 'pastoral'
    for role in ('admin', 'operador', 'lider_celula', 'pastor'):
        with client_for(p, role) as client:
            urls = client.get(f'/conversations/{p.conv}/messages/media-urls', params={'ids': str(mid)}).json()['urls']
            assert (str(mid) in urls) == (role == 'pastor')
    # Proposal expiry is a processing deadline, never a media TTL.
    with p.factory.begin() as db:
        db.execute(text("update pedido_oracao_proposta set expires_at=now()-interval '48 hours'"))
    from app.services.cell_report_audio_service import purge_cell_report_audio_inputs
    monkeypatch.setattr(policy, 'PRAYER_REQUEST_APPROVED_RELEASE_ID', None)
    purge_cell_report_audio_inputs(
        p.factory, storage=Storage(), now=dt.datetime.now(dt.UTC) + dt.timedelta(days=2),
    )
    with p.factory() as db:
        assert db.get(Message, mid).media_path == path
    with client_for(p, 'admin') as client:
        result = client.delete(f'/conversations/{p.conv}')
        assert result.status_code == 200, result.text
        assert result.json()['camadas']['midias']['pendentes'] == 1
    from app.services.private_deletion import process_storage_tasks
    removed = []
    class Cleanup:
        def remove_tenant_media(self, tenant, paths):
            assert tenant == TENANT
            removed.extend(paths)
    assert process_storage_tasks(p.factory, storage=Cleanup()) == 1
    assert removed == [path]


def test_audio_cannot_be_shared_with_leader(private_prayer):
    p = private_prayer
    send(p, 'Quero iniciar pedido de oração')
    outcome, _ = audio(p)
    run_agent_for_message(p.factory, outcome, evolution_client=_ClassifiedEvolution())
    send(p, 'Pastores e meu líder')
    send(p, 'SIM')
    with p.factory() as db:
        assert db.scalar(select(PrayerRequest)) is None


def test_legacy_shared_collection_audio_is_pastor_only(private_prayer):
    from tests.test_prayer_requests_pg import create_request
    from tests.test_prayer_privacy_pg import scope
    p = private_prayer
    row = create_request(p, 'Pastores e meu líder')
    with p.factory.begin() as db:
        mid = db.get(PrayerProposal, row.proposal_id).source_message_id
        db.get(Message, mid).tipo = 'audio'
        db.get(Message, mid).media_path = f'{TENANT}/synthetic/legacy.ogg'
    for role in ('lider_celula', 'admin', 'pastor'):
        with p.factory() as db:
            scope(db, p, role)
            assert (db.get(Message, mid) is not None) == (role == 'pastor')
        with client_for(p, role) as client:
            rows = client.get(f'/conversations/{p.conv}/messages').json()['items']
            message = next(m for m in rows if m['id'] == str(mid))
            assert (message['texto'] == MARKER) == (role != 'pastor')


def test_prayer_audio_never_enters_report_capture(private_prayer):
    from app.services.cell_report_audio_service import audio_capture_scope_allows
    p = private_prayer
    send(p, 'Quero iniciar pedido de oração')
    outcome, _ = audio(p)
    with p.factory() as db:
        assert not audio_capture_scope_allows(
            db, igreja_id=TENANT, conversation_id=p.conv,
            inbound_message_id=outcome.inbound_message_id,
        )


def test_unavailable_audio_does_not_confirm_invented_request(private_prayer):
    p = private_prayer
    send(p, 'Quero iniciar pedido de oração')
    outcome, _ = audio(p)
    with p.factory.begin() as db:
        db.get(Message, outcome.inbound_message_id).media_path = None
    transport = _ClassifiedEvolution()
    run_agent_for_message(p.factory, outcome, evolution_client=transport)
    assert transport.calls
    with p.factory() as db:
        assert db.scalar(select(PrayerProposal.summary)) == ''
        reply = db.scalars(select(Message).where(Message.direcao == 'out').order_by(Message.criado_em.desc())).first()
        assert 'indisponível' in reply.texto
        assert db.scalar(select(PrayerRequest)) is None
