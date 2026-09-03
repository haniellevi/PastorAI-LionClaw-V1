from __future__ import annotations

import ast
import datetime as dt
import inspect
import pickle
import uuid
from types import SimpleNamespace

import pytest

from app.agent.turn_execution import (
    AgentCompatibilityKeyVersion,
    build_agent_effect_compatibility_key,
    build_agent_outbound_reply_reservation_v2,
    build_agent_turn_execution_plan,
)
from app.agent.turn_identity import (
    AgentEffectKind,
    AgentTurnIdentity,
    build_agent_turn_identity,
)
from app.db.models import CelulaReuniao
from app.services import cell_report_application as application
from app.services import cell_report_whatsapp_coordinator as coordinator


TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_TENANT = uuid.UUID("11111111-1111-1111-1111-111111111112")
CONVERSATION = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_CONVERSATION = uuid.UUID("22222222-2222-2222-2222-222222222223")
ACTOR = uuid.UUID("33333333-3333-3333-3333-333333333333")
INBOUND = uuid.UUID("44444444-4444-4444-4444-444444444444")
MEETING = uuid.UUID("55555555-5555-5555-5555-555555555555")
REPLY = uuid.UUID("66666666-6666-6666-6666-666666666666")
CELL = uuid.UUID("77777777-7777-7777-7777-777777777777")
ACCESS = uuid.UUID("88888888-8888-8888-8888-888888888888")
ROLE = uuid.UUID("99999999-9999-9999-9999-999999999999")
NOW = dt.datetime(2026, 9, 3, 21, 0, tzinfo=dt.timezone.utc)
REPORT_TEXT = "presentes: 8; visitantes: 2; decisoes: 1; oferta: 52,50"
CONFIRMATION = "CONFIRMAR RELATORIO AAAAAAAAAAAA"


class _Result:
    def __init__(
        self,
        values: list[object] | None = None,
        *,
        scalars: list[object] | None = None,
    ) -> None:
        self._values = values
        self._scalars = scalars

    def all(self) -> list[object]:
        return list(self._values or [])

    def scalars(self):
        return _Result(self._scalars or [])


class _FakeSession:
    def __init__(
        self,
        responses: list[_Result],
        *,
        transaction_active: bool = True,
    ) -> None:
        self.responses = list(responses)
        self.transaction_active = transaction_active
        self.statements: list[object] = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.begin_calls = 0
        self.flush_calls = 0
        self._transaction = object() if transaction_active else None
        self._nested_transaction = None

    def in_transaction(self) -> bool:
        return self.transaction_active

    def get_transaction(self) -> object | None:
        return self._transaction

    def get_nested_transaction(self) -> object | None:
        return self._nested_transaction

    def replace_transaction(self) -> None:
        self._transaction = object() if self.transaction_active else None

    def replace_nested_transaction(self) -> None:
        self._nested_transaction = object() if self.transaction_active else None

    def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        if not self.responses:
            raise AssertionError("unexpected query")
        return self.responses.pop(0)

    def commit(self) -> None:
        self.commit_calls += 1
        raise AssertionError("coordinator must not commit")

    def rollback(self) -> None:
        self.rollback_calls += 1
        raise AssertionError("coordinator must not roll back")

    def begin(self) -> None:
        self.begin_calls += 1
        raise AssertionError("coordinator must not own a transaction")

    def flush(self) -> None:
        self.flush_calls += 1


class _PermittingGate:
    def __init__(
        self,
        *,
        expires_at: dt.datetime = NOW + dt.timedelta(minutes=5),
        foreign_request: bool = False,
    ) -> None:
        self.expires_at = expires_at
        self.foreign_request = foreign_request
        self.calls: list[coordinator.OperationalConsentRequest] = []

    def authorize_in_transaction(self, _db, request):
        self.calls.append(request)
        request_for_permit = request
        if self.foreign_request:
            request_for_permit = coordinator.OperationalConsentRequest(
                igreja_id=request.igreja_id,
                actor_pessoa_id=request.actor_pessoa_id,
                conversation_id=request.conversation_id,
                inbound_message_id=request.inbound_message_id,
                meeting_id=uuid.UUID("77777777-7777-7777-7777-777777777777"),
                turn_id=request.turn_id,
                operation=request.operation,
            )
        return coordinator._mint_operational_consent_permit(
            request_for_permit,
            expires_at=self.expires_at,
        )


@pytest.fixture(autouse=True)
def _tenant_scope(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[object, str | None]] = []

    def require_scope(_db, *, expected_igreja_id, source=None):
        calls.append((expected_igreja_id, source))

    monkeypatch.setattr(coordinator, "require_tenant_scope", require_scope)
    monkeypatch.setattr(application, "require_tenant_scope", require_scope)
    return calls


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(coordinator, "_utc_now", lambda: NOW)
    monkeypatch.setattr(application, "_utc_now", lambda: NOW)


def _identity(
    *,
    tenant: uuid.UUID = TENANT,
    conversation: uuid.UUID = CONVERSATION,
    inbound: uuid.UUID = INBOUND,
) -> AgentTurnIdentity:
    return build_agent_turn_identity(
        igreja_id=tenant,
        conversation_id=conversation,
        inbound_message_id=inbound,
        provider_message_id=f"provider-{inbound.hex}",
    )


def _inbound_row(
    identity: AgentTurnIdentity,
    *,
    text: str = REPORT_TEXT,
    message_tenant: uuid.UUID | None = None,
    message_conversation: uuid.UUID | None = None,
    direction: str = "in",
    author: str = "contato",
    provider_message_id: str | None = None,
    message_type: str = "texto",
    media_path: str | None = None,
    media_mime: str | None = None,
    media_name: str | None = None,
    media_size: int | None = None,
    state: str = "ia",
    assumed_by: uuid.UUID | None = None,
    official_number: bool = True,
) -> tuple[object, ...]:
    return (
        identity.inbound_message_id,
        message_tenant or identity.igreja_id,
        message_conversation or identity.conversation_id,
        direction,
        author,
        None,
        provider_message_id or identity.provider_message_id,
        text,
        message_type,
        media_path,
        media_mime,
        media_name,
        media_size,
        identity.conversation_id,
        identity.igreja_id,
        ACTOR,
        state,
        assumed_by,
        official_number,
    )


def _session_for(
    identity: AgentTurnIdentity,
    *,
    text: str = REPORT_TEXT,
    **row_overrides: object,
) -> _FakeSession:
    return _FakeSession(
        [_Result([_inbound_row(identity, text=text, **row_overrides)])]
    )


def _meeting() -> CelulaReuniao:
    return CelulaReuniao(
        id=MEETING,
        igreja_id=TENANT,
        celula_id=CELL,
        data=dt.date(2026, 9, 2),
        hora=None,
        status="realizada",
        relatorio_status="pendente",
        relatorio_snapshot=None,
        relatorio_enviado_em=None,
        relatorio_enviado_por=None,
        oferta_valor=None,
        observacoes=None,
        updated_at=None,
    )


def _application_authorization_responses(
    meeting: CelulaReuniao,
) -> list[_Result]:
    return [
        _Result(
            [
                (
                    CONVERSATION,
                    TENANT,
                    ACTOR,
                    "ia",
                    None,
                    True,
                )
            ]
        ),
        _Result(scalars=[meeting]),
        _Result(
            [
                (
                    CELL,
                    TENANT,
                    ACTOR,
                    True,
                    ACTOR,
                    TENANT,
                    None,
                    False,
                    False,
                )
            ]
        ),
        _Result([(ACCESS, TENANT, ACTOR)]),
        _Result([(ROLE, TENANT, ACCESS, "lider_celula")]),
    ]


def _proposal_stage_session(
    identity: AgentTurnIdentity,
    meeting: CelulaReuniao,
    *,
    text: str,
) -> _FakeSession:
    responses = [_Result([_inbound_row(identity, text=text)])]
    for _ in range(3):
        responses.extend(_application_authorization_responses(meeting))
    return _FakeSession(responses)


def _target(identity: AgentTurnIdentity) -> coordinator.CellReportMeetingTarget:
    return coordinator._mint_cell_report_meeting_target(
        identity,
        actor_pessoa_id=ACTOR,
        meeting_id=MEETING,
    )


def _expected_confirmation_key(
    identity: AgentTurnIdentity,
) -> str:
    return build_agent_outbound_reply_reservation_v2(identity).key


def test_default_gate_rejects_before_application_proposal(
    monkeypatch: pytest.MonkeyPatch,
):
    identity = _identity()
    session = _session_for(identity)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("proposal must not run without operational consent")

    monkeypatch.setattr(
        coordinator,
        "prepare_cell_report_proposal_cycle",
        unexpected,
    )

    with pytest.raises(coordinator.CellReportCoordinatorError) as excinfo:
        coordinator.stage_whatsapp_cell_report_proposal(
            session,
            turn_identity=identity,
            target=_target(identity),
        )

    assert excinfo.value.code is (
        coordinator.CellReportCoordinatorErrorCode.OPERATIONAL_CONSENT_DENIED
    )
    assert len(session.statements) == 1
    assert session.commit_calls == session.rollback_calls == session.begin_calls == 0


def test_proposal_derives_all_untrusted_values_from_persisted_inbound(
    monkeypatch: pytest.MonkeyPatch,
):
    identity = _identity()
    session = _session_for(identity)
    captured: dict[str, object] = {}
    proposal = SimpleNamespace(confirmation_command="CONFIRMAR RELATORIO TOKEN")
    cycle = object()

    def stage(_db, **kwargs):
        captured.update(kwargs)
        return proposal

    monkeypatch.setattr(
        coordinator,
        "prepare_cell_report_proposal_cycle",
        lambda *_args, **_kwargs: cycle,
    )
    monkeypatch.setattr(
        coordinator,
        "build_cell_report_proposal_effect_payload_for_cycle",
        lambda received_cycle, *, text: {
            "schema": "test-cell-report-cycle-payload/v1",
            "cycle_is_expected": received_cycle is cycle,
            "text": text,
        },
    )
    monkeypatch.setattr(coordinator, "propose_cell_report_from_cycle", stage)

    result = coordinator.stage_whatsapp_cell_report_proposal(
        session,
        turn_identity=identity,
        target=_target(identity),
        consent_gate=_PermittingGate(),
    )

    intent = captured["operation_intent"]
    assert isinstance(intent, type(result.operation_intent))
    assert captured["cycle"] is cycle
    assert captured["text"] == REPORT_TEXT
    assert intent.kind is AgentEffectKind.TOOL_CALL
    assert intent.ordinal == 0
    assert result.reply_text.endswith("CONFIRMAR RELATORIO TOKEN")
    assert result.requires_caller_commit is True
    assert session.commit_calls == session.rollback_calls == session.begin_calls == 0


def test_real_offline_proposal_stage_revises_a_live_managed_cycle(
    monkeypatch: pytest.MonkeyPatch,
):
    meeting = _meeting()
    first_identity = _identity()
    first_session = _proposal_stage_session(
        first_identity,
        meeting,
        text="10 presentes e oferta 0",
    )
    first = coordinator.stage_whatsapp_cell_report_proposal(
        first_session,
        turn_identity=first_identity,
        target=_target(first_identity),
        consent_gate=_PermittingGate(),
    )
    first_expiry = first.proposal.proposal.expires_at

    later = NOW + dt.timedelta(minutes=1)
    monkeypatch.setattr(coordinator, "_utc_now", lambda: later)
    second_identity = _identity(
        inbound=uuid.UUID("44444444-4444-4444-4444-444444444445")
    )
    second_session = _proposal_stage_session(
        second_identity,
        meeting,
        text="2 visitantes e 1 decisão",
    )
    second = coordinator.stage_whatsapp_cell_report_proposal(
        second_session,
        turn_identity=second_identity,
        target=_target(second_identity),
        consent_gate=_PermittingGate(
            expires_at=later + dt.timedelta(minutes=5)
        ),
    )

    assert first.proposal.proposal.workflow.revision == 1
    assert second.proposal.proposal.workflow.revision == 2
    assert second.proposal.proposal.expires_at == first_expiry
    assert second.proposal.proposal.workflow.candidate.presentes == 10
    assert second.proposal.proposal.workflow.candidate.visitantes == 2
    assert second.proposal.proposal.workflow.candidate.decisoes == 1
    assert second.proposal.proposal.workflow.candidate.oferta == "0.00"
    assert first_session.flush_calls == second_session.flush_calls == 1
    assert first_session.commit_calls == first_session.rollback_calls == 0
    assert second_session.commit_calls == second_session.rollback_calls == 0


def test_meeting_target_cannot_be_constructed_from_a_raw_uuid():
    with pytest.raises(TypeError):
        coordinator.CellReportMeetingTarget(MEETING)  # type: ignore[call-arg]


def test_process_local_target_and_permit_cannot_be_serialized():
    identity = _identity()
    target = _target(identity)
    request = coordinator.OperationalConsentRequest(
        igreja_id=TENANT,
        actor_pessoa_id=ACTOR,
        conversation_id=CONVERSATION,
        inbound_message_id=INBOUND,
        meeting_id=MEETING,
        turn_id=identity.turn_id,
        operation=coordinator.CellReportOperation.PROPOSAL,
    )
    permit = coordinator._mint_operational_consent_permit(
        request,
        expires_at=NOW + dt.timedelta(minutes=5),
    )

    with pytest.raises(TypeError):
        pickle.dumps(target)
    with pytest.raises(TypeError):
        pickle.dumps(permit)


def test_meeting_target_is_bound_to_its_exact_inbound_and_actor():
    original = _identity()
    later = _identity(
        inbound=uuid.UUID("44444444-4444-4444-4444-444444444445")
    )
    session = _session_for(later)

    with pytest.raises(coordinator.CellReportCoordinatorError) as excinfo:
        coordinator.stage_whatsapp_cell_report_proposal(
            session,
            turn_identity=later,
            target=_target(original),
            consent_gate=_PermittingGate(),
        )

    assert excinfo.value.code is (
        coordinator.CellReportCoordinatorErrorCode.MEETING_TARGET_INVALID
    )


def test_tampered_meeting_target_is_rejected_before_consent_or_application():
    identity = _identity()
    target = _target(identity)
    object.__setattr__(
        target,
        "_meeting_id",
        uuid.UUID("55555555-5555-5555-5555-555555555556"),
    )
    session = _session_for(identity)
    gate = _PermittingGate()

    with pytest.raises(coordinator.CellReportCoordinatorError) as excinfo:
        coordinator.stage_whatsapp_cell_report_proposal(
            session,
            turn_identity=identity,
            target=target,
            consent_gate=gate,
        )

    assert excinfo.value.code is (
        coordinator.CellReportCoordinatorErrorCode.MEETING_TARGET_INVALID
    )
    assert gate.calls == []


def test_invalid_inbound_binding_is_rejected_before_consent_or_application(
    monkeypatch: pytest.MonkeyPatch,
):
    identity = _identity()
    session = _session_for(identity, message_tenant=OTHER_TENANT)
    gate = _PermittingGate()

    monkeypatch.setattr(
        coordinator,
        "prepare_cell_report_proposal_cycle",
        lambda *_args, **_kwargs: pytest.fail("must not reach application"),
    )

    with pytest.raises(coordinator.CellReportCoordinatorError) as excinfo:
        coordinator.stage_whatsapp_cell_report_proposal(
            session,
            turn_identity=identity,
            target=_target(identity),
            consent_gate=gate,
        )

    assert excinfo.value.code is (
        coordinator.CellReportCoordinatorErrorCode.INBOUND_BINDING_INVALID
    )
    assert gate.calls == []
    assert session.commit_calls == session.rollback_calls == session.begin_calls == 0


@pytest.mark.parametrize(
    ("message_type", "media_path"),
    (
        ("audio", "igreja/conversa/audio.ogg"),
        ("imagem", "igreja/conversa/imagem.jpg"),
        ("arquivo", "igreja/conversa/documento.pdf"),
        ("texto", "igreja/conversa/nao-deveria-existir.txt"),
    ),
)
def test_media_or_nontext_inbound_is_rejected_before_consent_or_application(
    monkeypatch: pytest.MonkeyPatch,
    message_type: str,
    media_path: str,
):
    identity = _identity()
    session = _session_for(
        identity,
        message_type=message_type,
        media_path=media_path,
    )
    gate = _PermittingGate()
    monkeypatch.setattr(
        coordinator,
        "prepare_cell_report_proposal_cycle",
        lambda *_args, **_kwargs: pytest.fail("must not reach application"),
    )

    with pytest.raises(coordinator.CellReportCoordinatorError) as excinfo:
        coordinator.stage_whatsapp_cell_report_proposal(
            session,
            turn_identity=identity,
            target=_target(identity),
            consent_gate=gate,
        )

    assert excinfo.value.code is (
        coordinator.CellReportCoordinatorErrorCode.INBOUND_BINDING_INVALID
    )
    assert gate.calls == []
    assert session.commit_calls == session.rollback_calls == session.begin_calls == 0


def test_missing_transaction_is_rejected_before_any_database_query():
    identity = _identity()
    session = _FakeSession([], transaction_active=False)

    with pytest.raises(coordinator.CellReportCoordinatorError) as excinfo:
        coordinator.stage_whatsapp_cell_report_proposal(
            session,
            turn_identity=identity,
            target=_target(identity),
            consent_gate=_PermittingGate(),
        )

    assert excinfo.value.code is (
        coordinator.CellReportCoordinatorErrorCode.TRANSACTION_REQUIRED
    )
    assert session.statements == []


def test_expired_or_foreign_permit_is_rejected_before_application(
    monkeypatch: pytest.MonkeyPatch,
):
    identity = _identity()
    for gate in (
        _PermittingGate(expires_at=NOW),
        _PermittingGate(foreign_request=True),
    ):
        session = _session_for(identity)
        monkeypatch.setattr(
            coordinator,
            "prepare_cell_report_proposal_cycle",
            lambda *_args, **_kwargs: pytest.fail("must not reach application"),
        )
        with pytest.raises(coordinator.CellReportCoordinatorError) as excinfo:
            coordinator.stage_whatsapp_cell_report_proposal(
                session,
                turn_identity=identity,
                target=_target(identity),
                consent_gate=gate,
            )
        assert excinfo.value.code is (
            coordinator.CellReportCoordinatorErrorCode.OPERATIONAL_CONSENT_DENIED
        )


def test_consent_gate_cannot_close_the_caller_transaction_before_staging():
    class _ClosingGate(_PermittingGate):
        def authorize_in_transaction(self, db, request):
            permit = super().authorize_in_transaction(db, request)
            db.transaction_active = False
            return permit

    identity = _identity()
    session = _session_for(identity)

    with pytest.raises(coordinator.CellReportCoordinatorError) as excinfo:
        coordinator.stage_whatsapp_cell_report_proposal(
            session,
            turn_identity=identity,
            target=_target(identity),
            consent_gate=_ClosingGate(),
        )

    assert excinfo.value.code is (
        coordinator.CellReportCoordinatorErrorCode.TRANSACTION_REQUIRED
    )
    assert session.commit_calls == session.rollback_calls == session.begin_calls == 0


def test_consent_gate_cannot_replace_the_caller_transaction_before_staging():
    class _ReplacingGate(_PermittingGate):
        def authorize_in_transaction(self, db, request):
            permit = super().authorize_in_transaction(db, request)
            db.replace_transaction()
            return permit

    identity = _identity()
    session = _session_for(identity)

    with pytest.raises(coordinator.CellReportCoordinatorError) as excinfo:
        coordinator.stage_whatsapp_cell_report_proposal(
            session,
            turn_identity=identity,
            target=_target(identity),
            consent_gate=_ReplacingGate(),
        )

    assert excinfo.value.code is (
        coordinator.CellReportCoordinatorErrorCode.TRANSACTION_REQUIRED
    )
    assert session.commit_calls == session.rollback_calls == session.begin_calls == 0


def test_consent_gate_cannot_replace_a_nested_transaction_before_staging():
    class _ReplacingNestedGate(_PermittingGate):
        def authorize_in_transaction(self, db, request):
            permit = super().authorize_in_transaction(db, request)
            db.replace_nested_transaction()
            return permit

    identity = _identity()
    session = _session_for(identity)

    with pytest.raises(coordinator.CellReportCoordinatorError) as excinfo:
        coordinator.stage_whatsapp_cell_report_proposal(
            session,
            turn_identity=identity,
            target=_target(identity),
            consent_gate=_ReplacingNestedGate(),
        )

    assert excinfo.value.code is (
        coordinator.CellReportCoordinatorErrorCode.TRANSACTION_REQUIRED
    )
    assert session.commit_calls == session.rollback_calls == session.begin_calls == 0


def test_permit_is_revalidated_against_the_clock_after_gate_returns(
    monkeypatch: pytest.MonkeyPatch,
):
    now = {"value": NOW}
    monkeypatch.setattr(coordinator, "_utc_now", lambda: now["value"])

    class _SlowGate(_PermittingGate):
        def authorize_in_transaction(self, db, request):
            permit = super().authorize_in_transaction(db, request)
            now["value"] = NOW + dt.timedelta(minutes=6)
            return permit

    identity = _identity()
    session = _session_for(identity)
    monkeypatch.setattr(
        coordinator,
        "prepare_cell_report_proposal_cycle",
        lambda *_args, **_kwargs: pytest.fail("must not reach application"),
    )

    with pytest.raises(coordinator.CellReportCoordinatorError) as excinfo:
        coordinator.stage_whatsapp_cell_report_proposal(
            session,
            turn_identity=identity,
            target=_target(identity),
            consent_gate=_SlowGate(),
        )

    assert excinfo.value.code is (
        coordinator.CellReportCoordinatorErrorCode.OPERATIONAL_CONSENT_DENIED
    )


def test_proposal_revalidates_permit_immediately_before_application_write(
    monkeypatch: pytest.MonkeyPatch,
):
    now = {"value": NOW}
    monkeypatch.setattr(coordinator, "_utc_now", lambda: now["value"])
    identity = _identity()
    session = _session_for(identity)
    cycle = object()

    monkeypatch.setattr(
        coordinator,
        "prepare_cell_report_proposal_cycle",
        lambda *_args, **_kwargs: cycle,
    )

    def delayed_payload(_cycle, *, text):
        now["value"] = NOW + dt.timedelta(minutes=6)
        return {
            "schema": "test-cell-report-cycle-payload/v1",
            "cycle_is_expected": _cycle is cycle,
            "text": text,
        }

    monkeypatch.setattr(
        coordinator,
        "build_cell_report_proposal_effect_payload_for_cycle",
        delayed_payload,
    )
    monkeypatch.setattr(
        coordinator,
        "propose_cell_report_from_cycle",
        lambda *_args, **_kwargs: pytest.fail("must not reach application write"),
    )

    with pytest.raises(coordinator.CellReportCoordinatorError) as excinfo:
        coordinator.stage_whatsapp_cell_report_proposal(
            session,
            turn_identity=identity,
            target=_target(identity),
            consent_gate=_PermittingGate(),
        )

    assert excinfo.value.code is (
        coordinator.CellReportCoordinatorErrorCode.OPERATIONAL_CONSENT_DENIED
    )


def test_confirmation_revalidates_permit_immediately_before_unit_of_work(
    monkeypatch: pytest.MonkeyPatch,
):
    now = {"value": NOW}
    monkeypatch.setattr(coordinator, "_utc_now", lambda: now["value"])
    identity = _identity()
    session = _session_for(identity, text=CONFIRMATION)
    reservation = coordinator.CellReportReplyReservation(
        REPLY,
        _expected_confirmation_key(identity),
    )
    original_plan = coordinator.build_agent_turn_execution_plan

    def delayed_plan(*args, **kwargs):
        plan = original_plan(*args, **kwargs)
        now["value"] = NOW + dt.timedelta(minutes=6)
        return plan

    monkeypatch.setattr(
        coordinator,
        "build_agent_turn_execution_plan",
        delayed_plan,
    )
    monkeypatch.setattr(
        coordinator,
        "stage_confirmed_cell_report_turn",
        lambda *_args, **_kwargs: pytest.fail("must not reach unit of work"),
    )

    with pytest.raises(coordinator.CellReportCoordinatorError) as excinfo:
        coordinator.stage_confirmed_whatsapp_cell_report(
            session,
            turn_identity=identity,
            target=_target(identity),
            reply_reservation=reservation,
            consent_gate=_PermittingGate(),
        )

    assert excinfo.value.code is (
        coordinator.CellReportCoordinatorErrorCode.OPERATIONAL_CONSENT_DENIED
    )


def test_confirmation_builds_canonical_v2_plan_and_delegates_once(
    monkeypatch: pytest.MonkeyPatch,
):
    identity = _identity()
    session = _session_for(identity, text=CONFIRMATION)
    key = _expected_confirmation_key(identity)
    reservation = coordinator.CellReportReplyReservation(REPLY, key)
    captured: dict[str, object] = {}
    staged = SimpleNamespace(requires_caller_commit=True, replayed=False)

    def stage(_db, **kwargs):
        captured.update(kwargs)
        return staged

    monkeypatch.setattr(coordinator, "stage_confirmed_cell_report_turn", stage)

    result = coordinator.stage_confirmed_whatsapp_cell_report(
        session,
        turn_identity=identity,
        target=_target(identity),
        reply_reservation=reservation,
        consent_gate=_PermittingGate(),
    )

    assert captured["igreja_id"] == TENANT
    assert captured["conversa_id"] == CONVERSATION
    assert captured["ator_pessoa_id"] == ACTOR
    assert captured["reuniao_id"] == MEETING
    assert captured["command"] == CONFIRMATION
    assert captured["reply_message_id"] == REPLY
    assert captured["expected_reply_provider_key"] == key
    assert captured["reply_key_version"] is AgentCompatibilityKeyVersion.V2
    assert captured["reply_text"] == coordinator.CELL_REPORT_CONFIRMATION_REPLY
    assert result.reply_provider_key == key
    assert result.submission_intent.kind is AgentEffectKind.TOOL_CALL
    assert result.audit_intent.kind is AgentEffectKind.AUDIT_EVENT
    assert result.reply_intent.kind is AgentEffectKind.OUTBOUND_REPLY
    assert (
        result.submission_intent.ordinal
        == result.audit_intent.ordinal
        == result.reply_intent.ordinal
        == 0
    )
    plan = build_agent_turn_execution_plan(
        identity,
        (
            result.submission_intent,
            result.audit_intent,
            result.reply_intent,
        ),
    )
    assert (
        build_agent_effect_compatibility_key(
            identity,
            plan,
            result.reply_intent,
            version=AgentCompatibilityKeyVersion.V2,
        ).key
        == key
    )
    assert session.commit_calls == session.rollback_calls == session.begin_calls == 0


def test_confirmation_rejects_nonmatching_v2_reservation_before_stage(
    monkeypatch: pytest.MonkeyPatch,
):
    identity = _identity()
    session = _session_for(identity, text=CONFIRMATION)
    reservation = coordinator.CellReportReplyReservation(
        REPLY,
        "agent_effect_key_v2_" + ("a" * 64),
    )
    monkeypatch.setattr(
        coordinator,
        "stage_confirmed_cell_report_turn",
        lambda *_args, **_kwargs: pytest.fail("must not reach unit of work"),
    )

    with pytest.raises(coordinator.CellReportCoordinatorError) as excinfo:
        coordinator.stage_confirmed_whatsapp_cell_report(
            session,
            turn_identity=identity,
            target=_target(identity),
            reply_reservation=reservation,
            consent_gate=_PermittingGate(),
        )

    assert excinfo.value.code is (
        coordinator.CellReportCoordinatorErrorCode.REPLY_RESERVATION_INVALID
    )
    assert session.commit_calls == session.rollback_calls == session.begin_calls == 0


def test_coordinator_accepts_no_graph_output_or_raw_actor_parameters():
    proposal_parameters = inspect.signature(
        coordinator.stage_whatsapp_cell_report_proposal
    ).parameters
    confirmation_parameters = inspect.signature(
        coordinator.stage_confirmed_whatsapp_cell_report
    ).parameters
    forbidden = {
        "igreja_id",
        "conversa_id",
        "ator_pessoa_id",
        "inbound_message_id",
        "text",
        "command",
        "tool_calls",
        "graph_output",
        "claim_id",
        "reply_text",
        "reply_key_version",
        "now",
        "correlation_key",
        "expires_at",
    }
    assert not (set(proposal_parameters) & forbidden)
    assert not (set(confirmation_parameters) & forbidden)


def test_coordinator_has_no_runtime_worker_transport_or_transaction_ownership():
    source = inspect.getsource(coordinator)
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    call_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                call_names.add(node.func.attr)
            elif isinstance(node.func, ast.Name):
                call_names.add(node.func.id)

    prohibited_import_fragments = (
        "app.agent.runtime",
        "app.agent.graph",
        "app.workers",
        "app.services.evolution",
        "requests",
        "httpx",
        "socket",
    )
    assert not any(
        module.startswith(fragment) for module in imported_modules
        for fragment in prohibited_import_fragments
    )
    assert not ({"commit", "rollback", "begin", "send"} & call_names)
