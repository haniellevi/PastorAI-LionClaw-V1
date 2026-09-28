"""Durable V1b audio-input anchors, without provider or database I/O."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from types import SimpleNamespace

from app.services import cell_report_audio_service as service


TENANT = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
CONVERSATION = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
PESSOA = uuid.UUID("00000000-0000-0000-0000-0000000000c3")
INBOUND = uuid.UUID("00000000-0000-0000-0000-0000000000d4")


class _Session:
    def __init__(self) -> None:
        self.added: list[object] = []

    def execute(self, _statement):
        return SimpleNamespace(scalar_one_or_none=lambda: None)

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        return None


def test_enqueue_keeps_immutable_cleanup_anchor_but_no_transcript_or_url() -> None:
    session = _Session()
    received_at = dt.datetime(2026, 9, 27, 15, tzinfo=dt.UTC)

    result = service.enqueue_audio_input_after_inbound(
        session,
        igreja_id=TENANT,
        conversation_id=CONVERSATION,
        pessoa_id=PESSOA,
        inbound_message_id=INBOUND,
        provider_message_id="trusted-provider-message",
        declared_mime="audio/ogg",
        now=received_at,
    )

    assert result.created is True
    assert result.state == "aguardando_aceite"
    assert len(session.added) == 1
    row = session.added[0]
    assert row.igreja_id == TENANT
    assert row.conversation_id == CONVERSATION
    assert row.pessoa_id == PESSOA
    assert row.inbound_message_id == INBOUND
    assert row.live_conversation_id == CONVERSATION
    assert row.live_pessoa_id == PESSOA
    assert row.live_message_id == INBOUND
    assert row.provider_message_sha256 == hashlib.sha256(
        b"trusted-provider-message"
    ).hexdigest()
    assert row.storage_path == f"{TENANT}/cell-report-audio/{row.provider_message_sha256}.ogg"
    assert row.transcript_text is None
    assert row.expires_at == received_at + dt.timedelta(hours=24)
    assert row.purge_state == "ativa"


def _privilege_context() -> object:
    from app.services.whatsapp_privilege import PrivilegeContext

    return PrivilegeContext(
        igreja_id=TENANT,
        conversation_id=CONVERSATION,
        inbound_message_id=INBOUND,
        pessoa_id=PESSOA,
        app_user_id=uuid.UUID("00000000-0000-0000-0000-0000000000e5"),
        roles=frozenset({"lider_celula"}),
        role_snapshot=(),
        owned_cell_ids=(uuid.UUID("00000000-0000-0000-0000-0000000000f6"),),
        credential_fingerprint="credential",
        phone_fingerprint="phone",
        authorization_fingerprint="authorization",
        proof_id=None,
        proof_until=None,
        sensitive=False,
        scope_fingerprint="scope",
        context_fingerprint="context",
    )


def test_audio_capture_scope_requires_privileged_context_and_one_eligible_meeting(
    monkeypatch,
) -> None:
    from app.services import cell_report_v1a_service
    from app.services import whatsapp_privilege

    monkeypatch.setattr(
        whatsapp_privilege,
        "resolve_whatsapp_privilege_context",
        lambda *_args, **_kwargs: _privilege_context(),
    )
    monkeypatch.setattr(
        cell_report_v1a_service,
        "_eligible_meeting",
        lambda *_args, **kwargs: object() if kwargs["lock"] is False else None,
    )

    assert service.audio_capture_scope_allows(
        _Session(),
        igreja_id=TENANT,
        conversation_id=CONVERSATION,
        inbound_message_id=INBOUND,
    ) is True

    monkeypatch.setattr(
        whatsapp_privilege,
        "resolve_whatsapp_privilege_context",
        lambda *_args, **_kwargs: object(),
    )
    assert service.audio_capture_scope_allows(
        _Session(),
        igreja_id=TENANT,
        conversation_id=CONVERSATION,
        inbound_message_id=INBOUND,
    ) is False


def test_audio_acceptance_does_not_survive_a_later_lgpd_acceptance(monkeypatch) -> None:
    accepted_at = dt.datetime(2026, 9, 27, 15, tzinfo=dt.UTC)
    later_lgpd = dt.datetime(2026, 9, 27, 16, tzinfo=dt.UTC)
    event = service.CellReportAudioConsentEvent(
        id=uuid.uuid4(),
        igreja_id=TENANT,
        pessoa_id=PESSOA,
        conversation_id=CONVERSATION,
        source_message_id=INBOUND,
        notice_id=uuid.uuid4(),
        command="aceito",
        version="v1",
        occurred_at=accepted_at,
    )

    class _EventSession:
        def execute(self, _statement):
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [event]),
            )

    monkeypatch.setattr(
        service,
        "_current_lgpd_acceptance",
        lambda *_args, **_kwargs: SimpleNamespace(aceite_em=later_lgpd),
    )

    assert service._active_audio_consent(
        _EventSession(),
        igreja_id=TENANT,
        pessoa_id=PESSOA,
        now=later_lgpd,
    ) is None


def test_newer_audio_revocation_from_another_version_still_wins(monkeypatch) -> None:
    accepted_at = dt.datetime(2026, 9, 27, 15, tzinfo=dt.UTC)
    revoked_at = dt.datetime(2026, 9, 27, 16, tzinfo=dt.UTC)
    accepted = service.CellReportAudioConsentEvent(
        id=uuid.uuid4(),
        igreja_id=TENANT,
        pessoa_id=PESSOA,
        conversation_id=CONVERSATION,
        source_message_id=INBOUND,
        notice_id=uuid.uuid4(),
        command="aceito",
        version="v1",
        occurred_at=accepted_at,
    )
    revoked = service.CellReportAudioConsentEvent(
        id=uuid.uuid4(),
        igreja_id=TENANT,
        pessoa_id=PESSOA,
        conversation_id=CONVERSATION,
        source_message_id=uuid.uuid4(),
        notice_id=None,
        command="revogado",
        version="v0",
        occurred_at=revoked_at,
    )

    class _EventSession:
        def execute(self, _statement):
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [revoked, accepted]),
            )

    monkeypatch.setattr(
        service,
        "_current_lgpd_acceptance",
        lambda *_args, **_kwargs: SimpleNamespace(aceite_em=accepted_at - dt.timedelta(minutes=1)),
    )

    assert service._active_audio_consent(
        _EventSession(),
        igreja_id=TENANT,
        pessoa_id=PESSOA,
        now=revoked_at,
    ) is None


def test_audio_provider_tombstone_is_found_without_a_live_message() -> None:
    tombstone = service.CellReportAudioInput(
        id=uuid.uuid4(),
        igreja_id=TENANT,
        conversation_id=CONVERSATION,
        pessoa_id=PESSOA,
        inbound_message_id=INBOUND,
        provider_message_sha256=hashlib.sha256(b"provider-audio").hexdigest(),
        storage_path=f"{TENANT}/cell-report-audio/x.ogg",
        state="purgada",
        transcription_attempts=0,
        purge_state="purgada",
        purge_attempts=0,
        received_at=dt.datetime(2026, 9, 27, 15, tzinfo=dt.UTC),
        expires_at=dt.datetime(2026, 9, 28, 15, tzinfo=dt.UTC),
        updated_at=dt.datetime(2026, 9, 28, 15, tzinfo=dt.UTC),
    )

    class _TombstoneSession:
        def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: tombstone)

    assert service.find_audio_input_by_provider(
        _TombstoneSession(),
        igreja_id=TENANT,
        provider_message_id="provider-audio",
    ) is tombstone


def test_audio_consent_rejects_a_source_that_is_not_the_explicit_command() -> None:
    from app.db.models import Conversation, Message, Pessoa
    from app.services.cell_report_audio import AudioConsentCommand

    conversation = Conversation(
        id=CONVERSATION,
        igreja_id=TENANT,
        pessoa_id=PESSOA,
        telefone="5500000000000",
        estado="ia",
        numero_oficial=True,
    )
    pessoa = Pessoa(id=PESSOA, igreja_id=TENANT, nome="Pessoa sintética", telefone="5500000000000")
    source = Message(
        id=INBOUND,
        igreja_id=TENANT,
        conversation_id=CONVERSATION,
        direcao="in",
        autor="contato",
        texto="SIM",
        tipo="texto",
        criado_em=dt.datetime(2026, 9, 27, 15, tzinfo=dt.UTC),
    )
    values = iter((conversation, pessoa, source))

    class _SourceSession:
        def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: next(values))

    result = service.record_audio_consent_command(
        _SourceSession(),
        igreja_id=TENANT,
        pessoa_id=PESSOA,
        conversation_id=CONVERSATION,
        source_message_id=INBOUND,
        command=AudioConsentCommand.ACCEPT,
        now=dt.datetime(2026, 9, 27, 16, tzinfo=dt.UTC),
    )

    assert result.handled is False


def test_audio_consent_rejects_audio_caption_that_looks_like_command() -> None:
    from app.db.models import Conversation, Message, Pessoa
    from app.services.cell_report_audio import AudioConsentCommand

    conversation = Conversation(
        id=CONVERSATION,
        igreja_id=TENANT,
        pessoa_id=PESSOA,
        telefone="5500000000000",
        estado="ia",
        numero_oficial=True,
    )
    pessoa = Pessoa(id=PESSOA, igreja_id=TENANT, nome="Pessoa sintética", telefone="5500000000000")
    source = Message(
        id=INBOUND,
        igreja_id=TENANT,
        conversation_id=CONVERSATION,
        direcao="in",
        autor="contato",
        texto="ACEITO AUDIO",
        tipo="audio",
        criado_em=dt.datetime(2026, 9, 27, 15, tzinfo=dt.UTC),
    )
    values = iter((conversation, pessoa, source))

    class _SourceSession:
        def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: next(values))

    result = service.record_audio_consent_command(
        _SourceSession(),
        igreja_id=TENANT,
        pessoa_id=PESSOA,
        conversation_id=CONVERSATION,
        source_message_id=INBOUND,
        command=AudioConsentCommand.ACCEPT,
        now=dt.datetime(2026, 9, 27, 16, tzinfo=dt.UTC),
    )

    assert result.handled is False


def test_pending_audio_notice_does_not_authorize_retry_after_gate_revocation(monkeypatch) -> None:
    monkeypatch.setattr(service, "cell_report_audio_enabled_from_environment", lambda _tenant: False)

    class _NoQuerySession:
        def execute(self, _statement):
            raise AssertionError("gate fechado não consulta aviso pendente")

    assert service.audio_notice_still_pending(
        _NoQuerySession(),
        igreja_id=TENANT,
        pessoa_id=PESSOA,
        conversation_id=CONVERSATION,
        notice_message_id=uuid.uuid4(),
    ) is False


def test_expired_handoff_recovery_runs_even_after_send_gate_closes(monkeypatch) -> None:
    from app.services import outbound_guard

    input_id = uuid.uuid4()
    attempts = iter(
        (
            service._AudioHandoffRecoveryAttempt(True, False, input_id),
            service._AudioHandoffRecoveryAttempt(False, True),
        )
    )
    observed: list[tuple[uuid.UUID, tuple[uuid.UUID, ...]]] = []

    monkeypatch.setattr(service, "_discover_audio_tenants", lambda _factory: (TENANT,))
    monkeypatch.setattr(
        service,
        "_recover_expired_audio_handoff",
        lambda _factory, tenant, *, now, excluded_input_ids: (
            observed.append((tenant, excluded_input_ids)) or next(attempts)
        ),
    )
    monkeypatch.setattr(outbound_guard, "external_sends_allowed", lambda: False)
    monkeypatch.setattr(
        service,
        "_claim_next_audio_input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("gate fechado não inicia novo trabalho")
        ),
    )

    result = service.dispatch_cell_report_audio_inputs(
        lambda: object(),
        evolution_client=object(),
        storage=object(),
        decoder=lambda *_args, **_kwargs: None,
        transcriber=lambda *_args, **_kwargs: None,
        limit=2,
    )

    assert result == service.AudioDispatchResult(claimed=0, completed=1)
    assert observed == [(TENANT, ()), (TENANT, (input_id,))]


def test_handoff_database_error_remains_recoverable(monkeypatch) -> None:
    claim = service.AudioInputClaim(
        igreja_id=TENANT,
        input_id=uuid.uuid4(),
        conversation_id=CONVERSATION,
        pessoa_id=PESSOA,
        inbound_message_id=INBOUND,
        provider_message_id="provider-audio",
        instance="instance",
        phone="5500000000000",
        declared_mime="audio/ogg",
        provider_message_sha256="a" * 64,
        lease_token=uuid.uuid4(),
        lease_until=dt.datetime(2026, 9, 27, 15, tzinfo=dt.UTC),
        credential_provider="openai",
        credential_key_encrypted="encrypted",
        credential_model="model",
    )

    class _FailingSession:
        rolled_back = False
        closed = False

        def rollback(self) -> None:
            self.rolled_back = True

        def close(self) -> None:
            self.closed = True

    session = _FailingSession()
    monkeypatch.setattr(service, "_scoped", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()))

    assert service._handoff_audio_claim_failure(
        lambda: session,
        claim,
        reason="prazo",
        ambiguous=False,
    ) is None
    assert session.rolled_back is True
    assert session.closed is True


def test_deadline_contention_leaves_claim_for_durable_handoff_recovery(monkeypatch) -> None:
    claim = service.AudioInputClaim(
        igreja_id=TENANT,
        input_id=uuid.uuid4(),
        conversation_id=CONVERSATION,
        pessoa_id=PESSOA,
        inbound_message_id=INBOUND,
        provider_message_id="provider-audio",
        instance="instance",
        phone="5500000000000",
        declared_mime="audio/ogg",
        provider_message_sha256="b" * 64,
        lease_token=uuid.uuid4(),
        lease_until=dt.datetime(2026, 9, 27, 15, tzinfo=dt.UTC),
        credential_provider="openai",
        credential_key_encrypted="encrypted",
        credential_model="model",
    )
    monkeypatch.setattr(
        service,
        "_handoff_audio_claim_failure",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        service,
        "_wait_for_audio_authorization",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            service._AudioClaimDeadlineExceeded("prazo")
        ),
    )
    monkeypatch.setattr(
        service,
        "_terminalize_audio_claim",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("não terminaliza sem cerca humana")
        ),
    )

    service._handoff_audio_claim_after_boundary(
        lambda: object(),
        claim,
        deadline_at=0.0,
        reason="prazo",
        ambiguous=False,
        storage_attempted=False,
    )


def test_immediate_audio_expiry_never_extends_the_24_hour_window() -> None:
    received_at = dt.datetime(2026, 9, 27, 12, tzinfo=dt.UTC)
    row = SimpleNamespace(
        received_at=received_at,
        expires_at=received_at + dt.timedelta(hours=24),
    )

    assert service._immediate_audio_expiry(
        row,
        received_at + dt.timedelta(hours=25),
    ) == row.expires_at
    assert service._immediate_audio_expiry(row, received_at) == received_at + dt.timedelta(
        microseconds=1
    )


def test_public_purge_runs_handoff_recovery_before_selecting_content(monkeypatch) -> None:
    observed: list[object] = []
    monkeypatch.setattr(
        service,
        "recover_expired_audio_handoffs",
        lambda factory, *, now, limit: observed.append((factory, now, limit)) or 0,
    )
    monkeypatch.setattr(service, "_discover_audio_tenants", lambda _factory: ())
    factory = lambda: object()  # noqa: E731
    now = dt.datetime(2026, 9, 28, 12, tzinfo=dt.UTC)

    assert service.purge_cell_report_audio_inputs(
        factory,
        storage=object(),
        now=now,
        limit=3,
    ) == 0
    assert observed == [(factory, now, 3)]
