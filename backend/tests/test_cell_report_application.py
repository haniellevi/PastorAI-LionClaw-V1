from __future__ import annotations

import ast
import datetime as dt
import inspect
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import StatementError

from app.agent.turn_identity import (
    AgentEffectIntent,
    AgentEffectKind,
    AgentTurnIdentity,
    build_agent_effect_intent,
    build_agent_turn_identity,
)
from app.db.models import CelulaReuniao
from app.domain.cell_report_limits import MAX_CELL_REPORT_OBSERVATIONS_LENGTH
from app.domain.cell_report_workflow import CellReportWorkflowState
from app.services import cell_report_application as application


TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
MEETING = uuid.UUID("22222222-2222-2222-2222-222222222222")
CELL = uuid.UUID("33333333-3333-3333-3333-333333333333")
CONVERSATION = uuid.UUID("44444444-4444-4444-4444-444444444444")
ACTOR = uuid.UUID("55555555-5555-5555-5555-555555555555")
ACCESS = uuid.UUID("66666666-6666-6666-6666-666666666666")
ROLE = uuid.UUID("77777777-7777-7777-7777-777777777777")
INBOUND_1 = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")
INBOUND_2 = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2")
INBOUND_FINAL = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3")
INBOUND_FINAL_2 = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa4")
SCOPE = f"cell_report_scope_v1_{'a' * 64}"
OTHER_SCOPE = f"cell_report_scope_v1_{'b' * 64}"
NOW = dt.datetime(2026, 8, 31, 15, 0, tzinfo=dt.timezone.utc)
EXPIRY = NOW + dt.timedelta(minutes=30)


class _ScalarRows:
    def __init__(
        self,
        values: list[object],
        *,
        error: Exception | None = None,
    ) -> None:
        self._values = values
        self._error = error

    def all(self) -> list[object]:
        if self._error is not None:
            raise self._error
        return list(self._values)


class _Result:
    def __init__(
        self,
        *,
        scalars: list[object] | None = None,
        rows: list[object] | None = None,
        rows_error: Exception | None = None,
        scalars_error: Exception | None = None,
    ) -> None:
        self._scalars = scalars or []
        self._rows = rows or []
        self._rows_error = rows_error
        self._scalars_error = scalars_error

    def scalars(self) -> _ScalarRows:
        return _ScalarRows(self._scalars, error=self._scalars_error)

    def all(self) -> list[object]:
        if self._rows_error is not None:
            raise self._rows_error
        return list(self._rows)


class _FakeSession:
    def __init__(
        self,
        responses: list[_Result],
        *,
        transaction_active: bool = True,
        flush_error: Exception | None = None,
        execute_error: Exception | None = None,
    ) -> None:
        self.responses = list(responses)
        self.transaction_active = transaction_active
        self.flush_error = flush_error
        self.execute_error = execute_error
        self.statements: list[object] = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0

    def in_transaction(self) -> bool:
        return self.transaction_active

    def execute(self, statement):
        self.statements.append(statement)
        if self.execute_error is not None:
            raise self.execute_error
        if not self.responses:
            raise AssertionError("unexpected database query")
        return self.responses.pop(0)

    def flush(self) -> None:
        self.flush_calls += 1
        if self.flush_error is not None:
            raise self.flush_error

    def commit(self) -> None:
        self.commit_calls += 1
        raise AssertionError("application service must not commit")

    def rollback(self) -> None:
        self.rollback_calls += 1
        raise AssertionError("application service must not roll back")


def _meeting(**overrides) -> CelulaReuniao:
    values = {
        "id": MEETING,
        "igreja_id": TENANT,
        "celula_id": CELL,
        "data": dt.date(2026, 8, 30),
        "hora": None,
        "status": "realizada",
        "relatorio_status": "pendente",
        "relatorio_snapshot": None,
        "relatorio_enviado_em": None,
        "relatorio_enviado_por": None,
        "oferta_valor": None,
        "observacoes": None,
        "updated_at": None,
    }
    values.update(overrides)
    return CelulaReuniao(**values)


def _leader_row(**overrides) -> tuple[object, ...]:
    values = {
        "cell_id": CELL,
        "cell_tenant_id": TENANT,
        "leader_id": ACTOR,
        "cell_active": True,
        "actor_id": ACTOR,
        "actor_tenant_id": TENANT,
        "actor_archived_at": None,
        "actor_without_interest": False,
        "actor_optout": False,
    }
    values.update(overrides)
    return tuple(values.values())


def _access_row(**overrides) -> tuple[object, ...]:
    values = {
        "access_id": ACCESS,
        "access_tenant_id": TENANT,
        "access_person_id": ACTOR,
    }
    values.update(overrides)
    return tuple(values.values())


def _role_row(**overrides) -> tuple[object, ...]:
    values = {
        "role_id": ROLE,
        "role_tenant_id": TENANT,
        "role_user_id": ACCESS,
        "role_name": "lider_celula",
    }
    values.update(overrides)
    return tuple(values.values())


def _conversation_row(**overrides) -> tuple[object, ...]:
    values = {
        "conversation_id": CONVERSATION,
        "tenant_id": TENANT,
        "person_id": ACTOR,
        "state": "ia",
        "assumed_by": None,
        "official_number": True,
    }
    values.update(overrides)
    return tuple(values.values())


def _authorized_session(
    meeting: CelulaReuniao,
    *,
    conversations: list[object] | None = None,
    cells_and_people: list[object] | None = None,
    accesses: list[object] | None = None,
    roles: list[object] | None = None,
    transaction_active: bool = True,
    flush_error: Exception | None = None,
) -> _FakeSession:
    return _FakeSession(
        [
            _Result(
                rows=(
                    [_conversation_row()]
                    if conversations is None
                    else conversations
                )
            ),
            _Result(scalars=[meeting]),
            _Result(
                rows=(
                    [_leader_row()]
                    if cells_and_people is None
                    else cells_and_people
                )
            ),
            _Result(rows=[_access_row()] if accesses is None else accesses),
            _Result(rows=[_role_row()] if roles is None else roles),
        ],
        transaction_active=transaction_active,
        flush_error=flush_error,
    )


@pytest.fixture(autouse=True)
def _tenant_scope(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[object, str | None]] = []

    def require_scope(_db, *, expected_igreja_id, source=None):
        calls.append((expected_igreja_id, source))

    monkeypatch.setattr(application, "require_tenant_scope", require_scope)
    return calls


def _propose(
    db: _FakeSession,
    *,
    text: str = (
        "10 presentes, 2 visitantes, 1 decisão, oferta 100,50, "
        "obs: Reunião tranquila"
    ),
    inbound: uuid.UUID = INBOUND_1,
    turn_identity: AgentTurnIdentity | None = None,
    operation_intent: AgentEffectIntent | None = None,
    scope: str = SCOPE,
    conversation: uuid.UUID = CONVERSATION,
    actor: uuid.UUID = ACTOR,
    now: dt.datetime = NOW,
    expiry: dt.datetime = EXPIRY,
    meeting_id: uuid.UUID = MEETING,
):
    identity = turn_identity or _identity(
        conversation=conversation,
        inbound=inbound,
    )
    payload = application.build_cell_report_proposal_effect_payload(
        igreja_id=TENANT,
        reuniao_id=meeting_id,
        conversa_id=conversation,
        ator_pessoa_id=actor,
        correlation_key=scope,
        text=text,
        expires_at=expiry,
    )
    intent = operation_intent or build_agent_effect_intent(
        identity,
        kind=AgentEffectKind.TOOL_CALL,
        ordinal=0,
        payload=payload,
    )
    return application.propose_cell_report(
        db,  # type: ignore[arg-type]
        igreja_id=TENANT,
        reuniao_id=meeting_id,
        conversa_id=conversation,
        ator_pessoa_id=actor,
        correlation_key=scope,
        turn_identity=identity,
        operation_intent=intent,
        text=text,
        now=now,
        expires_at=expiry,
    )


def _confirm(
    db: _FakeSession,
    *,
    command: str,
    inbound: uuid.UUID = INBOUND_FINAL,
    turn_identity: AgentTurnIdentity | None = None,
    submission_intent: AgentEffectIntent | None = None,
    conversation: uuid.UUID = CONVERSATION,
    actor: uuid.UUID = ACTOR,
    now: dt.datetime = NOW + dt.timedelta(minutes=1),
):
    identity = turn_identity or _identity(
        conversation=conversation,
        inbound=inbound,
    )
    payload = application.build_cell_report_confirmation_effect_payload(
        igreja_id=TENANT,
        reuniao_id=MEETING,
        conversa_id=conversation,
        ator_pessoa_id=actor,
        command=command,
    )
    intent = submission_intent or build_agent_effect_intent(
        identity,
        kind=AgentEffectKind.TOOL_CALL,
        ordinal=0,
        payload=payload,
    )
    return application.confirm_cell_report(
        db,  # type: ignore[arg-type]
        igreja_id=TENANT,
        reuniao_id=MEETING,
        conversa_id=conversation,
        ator_pessoa_id=actor,
        command=command,
        turn_identity=identity,
        submission_intent=intent,
        now=now,
    )


def _identity(
    *,
    conversation: uuid.UUID = CONVERSATION,
    inbound: uuid.UUID = INBOUND_1,
) -> AgentTurnIdentity:
    return build_agent_turn_identity(
        igreja_id=TENANT,
        conversation_id=conversation,
        inbound_message_id=inbound,
        provider_message_id=f"provider-{inbound.hex}",
    )


def _proposal_plan(
    *,
    text: str,
    inbound: uuid.UUID,
    meeting_id: uuid.UUID = MEETING,
    conversation: uuid.UUID = CONVERSATION,
    actor: uuid.UUID = ACTOR,
    scope: str = SCOPE,
    expiry: dt.datetime = EXPIRY,
) -> tuple[AgentTurnIdentity, AgentEffectIntent]:
    identity = _identity(conversation=conversation, inbound=inbound)
    payload = application.build_cell_report_proposal_effect_payload(
        igreja_id=TENANT,
        reuniao_id=meeting_id,
        conversa_id=conversation,
        ator_pessoa_id=actor,
        correlation_key=scope,
        text=text,
        expires_at=expiry,
    )
    return identity, build_agent_effect_intent(
        identity,
        kind=AgentEffectKind.TOOL_CALL,
        ordinal=0,
        payload=payload,
    )


def test_propose_persists_closed_pending_jsonb_without_committing(
    _tenant_scope,
) -> None:
    meeting = _meeting()
    db = _authorized_session(meeting)

    result = _propose(db)

    assert result.replayed is False
    assert result.proposal.workflow.state is (
        CellReportWorkflowState.AWAITING_CONFIRMATION
    )
    assert result.confirmation_command is not None
    assert result.confirmation_command.startswith("CONFIRMAR RELATORIO ")
    assert meeting.relatorio_snapshot["schema"] == (
        "cell-report-pending-proposal/v1"
    )
    assert meeting.relatorio_status == "pendente"
    assert meeting.oferta_valor is None
    assert meeting.observacoes is None
    assert meeting.updated_at == NOW
    assert db.flush_calls == 1
    assert db.commit_calls == db.rollback_calls == 0
    assert db.responses == []
    assert _tenant_scope == [(TENANT, "cell_report_application")]


def test_partial_proposal_revises_to_complete_and_rotates_code() -> None:
    meeting = _meeting()
    first_db = _authorized_session(meeting)
    first = _propose(
        first_db,
        text="10 presentes e oferta 0",
    )
    assert first.proposal.workflow.state is CellReportWorkflowState.COLLECTING
    assert first.confirmation_command is None

    second_db = _authorized_session(meeting)
    second = _propose(
        second_db,
        text="2 visitantes e 1 decisão",
        inbound=INBOUND_2,
    )
    candidate = second.proposal.workflow.candidate
    assert second.proposal.workflow.revision == 2
    assert candidate.presentes == 10
    assert candidate.visitantes == 2
    assert candidate.decisoes == 1
    assert candidate.oferta == "0.00"
    assert second.confirmation_command is not None
    assert second_db.flush_calls == 1


def test_same_effect_and_semantic_patch_is_replay_without_new_flush() -> None:
    meeting = _meeting()
    original = _propose(_authorized_session(meeting))
    persisted_before = meeting.relatorio_snapshot
    updated_before = meeting.updated_at

    replay_db = _authorized_session(meeting)
    replay = _propose(replay_db)

    assert replay.replayed is True
    assert replay.proposal.workflow.revision == original.proposal.workflow.revision
    assert meeting.relatorio_snapshot is persisted_before
    assert meeting.updated_at == updated_before
    assert replay_db.flush_calls == 0


def test_same_effect_with_different_patch_fails_idempotency_closed() -> None:
    meeting = _meeting()
    _propose(_authorized_session(meeting))
    replay_db = _authorized_session(meeting)

    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(replay_db, text="11 presentes")
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.IDEMPOTENCY_CONFLICT
    )
    assert replay_db.flush_calls == 0


@pytest.mark.parametrize(
    "draft_change",
    [
        {"oferta_valor": Decimal("1.00")},
        {"observacoes": "edição humana concorrente"},
    ],
)
def test_human_draft_change_after_proposal_causes_conflict_not_overwrite(
    draft_change: dict[str, object],
) -> None:
    meeting = _meeting()
    proposal = _propose(_authorized_session(meeting))
    for field_name, value in draft_change.items():
        setattr(meeting, field_name, value)
    db = _authorized_session(meeting)

    with pytest.raises(application.CellReportApplicationError) as raised:
        _confirm(
            db,
            command=proposal.confirmation_command,  # type: ignore[arg-type]
        )
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.REPORT_CONFLICT
    )
    assert meeting.relatorio_status == "pendente"
    assert db.flush_calls == 0


@pytest.mark.parametrize(
    "changed",
    [
        {"scope": OTHER_SCOPE},
        {"conversation": uuid.UUID("88888888-8888-8888-8888-888888888888")},
    ],
)
def test_pending_proposal_cannot_be_swapped_across_scope_or_conversation(
    changed: dict[str, object],
) -> None:
    meeting = _meeting()
    _propose(_authorized_session(meeting))
    changed_conversation = changed.get("conversation", CONVERSATION)
    db = _authorized_session(
        meeting,
        conversations=[
            _conversation_row(conversation_id=changed_conversation)
        ],
    )

    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(db, inbound=INBOUND_2, **changed)  # type: ignore[arg-type]
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.PROPOSAL_BINDING_MISMATCH
    )
    assert db.flush_calls == 0


def test_pending_proposal_cannot_move_to_a_new_current_leader_before_expiry() -> None:
    meeting = _meeting()
    _propose(_authorized_session(meeting))
    new_actor = uuid.UUID("99999999-9999-9999-9999-999999999999")
    db = _authorized_session(
        meeting,
        conversations=[_conversation_row(person_id=new_actor)],
        cells_and_people=[
            _leader_row(leader_id=new_actor, actor_id=new_actor)
        ],
        accesses=[_access_row(access_person_id=new_actor)],
    )

    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(db, inbound=INBOUND_2, actor=new_actor)
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.PROPOSAL_BINDING_MISMATCH
    )
    assert db.flush_calls == 0


def test_confirmation_materializes_v2_and_leaves_commit_to_caller() -> None:
    meeting = _meeting()
    proposal = _propose(_authorized_session(meeting))
    db = _authorized_session(meeting)
    identity = _identity(inbound=INBOUND_FINAL)
    expected_intent = build_agent_effect_intent(
        identity,
        kind=AgentEffectKind.TOOL_CALL,
        ordinal=0,
        payload=application.build_cell_report_confirmation_effect_payload(
            igreja_id=TENANT,
            reuniao_id=MEETING,
            conversa_id=CONVERSATION,
            ator_pessoa_id=ACTOR,
            command=proposal.confirmation_command,  # type: ignore[arg-type]
        ),
    )

    result = _confirm(
        db,
        command=proposal.confirmation_command,  # type: ignore[arg-type]
        turn_identity=identity,
        submission_intent=expected_intent,
    )

    assert result.replayed is False
    assert result.requires_caller_commit is True
    assert result.accepted_workflow is not None
    assert result.accepted_workflow.state is (
        CellReportWorkflowState.CONFIRMATION_ACCEPTED
    )
    assert result.snapshot == meeting.relatorio_snapshot
    assert result.snapshot == {
        "schema": "cell-report/v2",
        "totals": {"presentes": 10, "visitantes": 2, "decisoes": 1},
        "oferta_valor": "100.50",
        "observacoes": "Reunião tranquila",
        "submission_effect_id": expected_intent.effect_id,
        "submission_payload_digest": expected_intent.payload_digest,
        "presencas": [],
        "visitantes": [],
        "records": [],
    }
    assert result.snapshot["submission_effect_id"] == expected_intent.effect_id
    assert result.snapshot["submission_payload_digest"] == (
        expected_intent.payload_digest
    )
    assert meeting.relatorio_status == "enviado"
    assert meeting.oferta_valor == Decimal("100.50")
    assert type(meeting.oferta_valor) is Decimal
    assert meeting.observacoes == "Reunião tranquila"
    assert meeting.relatorio_enviado_por == ACTOR
    assert meeting.relatorio_enviado_em == NOW + dt.timedelta(minutes=1)
    assert db.flush_calls == 1
    assert db.commit_calls == db.rollback_calls == 0
    assert "Reunião tranquila" not in repr(result)


def test_human_e2_offering_boundary_is_preserved_through_final_snapshot() -> None:
    meeting = _meeting()
    proposal = _propose(
        _authorized_session(meeting),
        text=(
            "1 presente, 0 visitantes, 0 decisões, "
            "oferta 999999,99"
        ),
    )
    result = _confirm(
        _authorized_session(meeting),
        command=proposal.confirmation_command,  # type: ignore[arg-type]
    )
    assert result.snapshot["oferta_valor"] == "999999.99"
    assert meeting.oferta_valor == Decimal("999999.99")


def test_human_observation_boundary_materializes_without_late_failure() -> None:
    observations = "x" * MAX_CELL_REPORT_OBSERVATIONS_LENGTH
    meeting = _meeting()
    proposal = _propose(
        _authorized_session(meeting),
        text=(
            "1 presente, 0 visitantes, 0 decisões, oferta 0, "
            f"obs: {observations}"
        ),
    )

    result = _confirm(
        _authorized_session(meeting),
        command=proposal.confirmation_command,  # type: ignore[arg-type]
    )

    assert result.snapshot["observacoes"] == observations
    assert meeting.observacoes == observations


def test_observation_over_human_limit_fails_before_database_access() -> None:
    observations = "x" * (MAX_CELL_REPORT_OBSERVATIONS_LENGTH + 1)
    db = _FakeSession([])

    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(
            db,
            text=(
                "1 presente, 0 visitantes, 0 decisões, oferta 0, "
                f"obs: {observations}"
            ),
        )

    assert raised.value.code is (
        application.CellReportApplicationErrorCode.INVALID_ARGUMENT
    )
    assert db.statements == []
    assert db.flush_calls == 0


def test_final_same_effect_replays_after_persistence_without_flush() -> None:
    meeting = _meeting()
    proposal = _propose(_authorized_session(meeting))
    _confirm(
        _authorized_session(meeting),
        command=proposal.confirmation_command,  # type: ignore[arg-type]
    )

    replay_db = _authorized_session(meeting)
    replay = _confirm(
        replay_db,
        command=proposal.confirmation_command,  # type: ignore[arg-type]
    )
    assert replay.replayed is True
    assert replay.requires_caller_commit is False
    assert replay.accepted_workflow is None
    assert replay.snapshot["submission_effect_id"] == (
        meeting.relatorio_snapshot["submission_effect_id"]
    )
    assert replay.snapshot["submission_payload_digest"] == (
        meeting.relatorio_snapshot["submission_payload_digest"]
    )
    assert replay_db.flush_calls == 0


def test_final_different_effect_conflicts_instead_of_double_submit() -> None:
    meeting = _meeting()
    proposal = _propose(_authorized_session(meeting))
    _confirm(
        _authorized_session(meeting),
        command=proposal.confirmation_command,  # type: ignore[arg-type]
    )
    conflict_db = _authorized_session(meeting)

    with pytest.raises(application.CellReportApplicationError) as raised:
        _confirm(
            conflict_db,
            command=proposal.confirmation_command,  # type: ignore[arg-type]
            inbound=INBOUND_FINAL_2,
        )
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.REPORT_CONFLICT
    )
    assert conflict_db.flush_calls == 0


def test_wrong_current_code_rejects_without_mutating_pending_proposal() -> None:
    meeting = _meeting()
    proposal = _propose(_authorized_session(meeting))
    before = meeting.relatorio_snapshot
    wrong = "A" * 12
    if proposal.confirmation_command == f"CONFIRMAR RELATORIO {wrong}":
        wrong = "B" * 12
    db = _authorized_session(meeting)

    with pytest.raises(application.CellReportApplicationError) as raised:
        _confirm(db, command=f"CONFIRMAR RELATORIO {wrong}")
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.CONFIRMATION_REJECTED
    )
    assert meeting.relatorio_snapshot is before
    assert meeting.relatorio_status == "pendente"
    assert db.flush_calls == 0


def test_confirmation_from_another_conversation_cannot_consume_proposal() -> None:
    meeting = _meeting()
    proposal = _propose(_authorized_session(meeting))
    other_conversation = uuid.UUID(
        "88888888-8888-8888-8888-888888888888"
    )
    db = _authorized_session(
        meeting,
        conversations=[
            _conversation_row(conversation_id=other_conversation)
        ],
    )

    with pytest.raises(application.CellReportApplicationError) as raised:
        _confirm(
            db,
            command=proposal.confirmation_command,  # type: ignore[arg-type]
            conversation=other_conversation,
        )
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.PROPOSAL_BINDING_MISMATCH
    )
    assert meeting.relatorio_status == "pendente"
    assert db.flush_calls == 0


def test_expired_proposal_rejects_confirmation_at_exact_boundary() -> None:
    meeting = _meeting()
    proposal = _propose(_authorized_session(meeting))
    db = _authorized_session(meeting)

    with pytest.raises(application.CellReportApplicationError) as raised:
        _confirm(
            db,
            command=proposal.confirmation_command,  # type: ignore[arg-type]
            now=EXPIRY,
        )
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.PROPOSAL_EXPIRED
    )
    assert db.flush_calls == 0


def test_different_operation_can_replace_expired_proposal_under_same_row_lock() -> None:
    meeting = _meeting()
    original = _propose(_authorized_session(meeting))
    new_conversation = uuid.UUID("88888888-8888-8888-8888-888888888888")
    db = _authorized_session(
        meeting,
        conversations=[
            _conversation_row(conversation_id=new_conversation)
        ],
    )

    replacement = _propose(
        db,
        text="7 presentes, 0 visitantes, 0 decisões, oferta 0",
        inbound=INBOUND_2,
        scope=OTHER_SCOPE,
        conversation=new_conversation,
        now=EXPIRY,
        expiry=EXPIRY + dt.timedelta(minutes=30),
    )

    assert replacement.replayed is False
    assert replacement.proposal.workflow.revision == 1
    assert replacement.proposal.workflow.proposal_digest != (
        original.proposal.workflow.proposal_digest
    )
    assert replacement.proposal.workflow.candidate.presentes == 7
    assert replacement.proposal.expires_at == EXPIRY + dt.timedelta(minutes=30)
    assert db.flush_calls == 1


def test_same_operation_cannot_resurrect_its_expired_proposal() -> None:
    meeting = _meeting()
    _propose(_authorized_session(meeting))
    db = _authorized_session(meeting)

    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(
            db,
            now=EXPIRY,
            expiry=EXPIRY + dt.timedelta(minutes=30),
        )
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.IDEMPOTENCY_CONFLICT
    )
    assert db.flush_calls == 0


def test_new_operation_must_rotate_scope_after_expiry() -> None:
    meeting = _meeting()
    _propose(_authorized_session(meeting))
    db = _authorized_session(meeting)

    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(
            db,
            inbound=INBOUND_2,
            now=EXPIRY,
            expiry=EXPIRY + dt.timedelta(minutes=30),
        )
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.PROPOSAL_EXPIRED
    )
    assert db.flush_calls == 0


@pytest.mark.parametrize(
    ("meeting_rows", "code"),
    [
        ([], application.CellReportApplicationErrorCode.MEETING_NOT_FOUND),
        (
            [_meeting(), _meeting()],
            application.CellReportApplicationErrorCode.DATA_INTEGRITY,
        ),
    ],
)
def test_zero_or_multiple_locked_meetings_fail_closed(
    meeting_rows: list[object],
    code: application.CellReportApplicationErrorCode,
) -> None:
    db = _FakeSession(
        [
            _Result(rows=[_conversation_row()]),
            _Result(scalars=meeting_rows),
        ]
    )
    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(db)
    assert raised.value.code is code
    assert db.flush_calls == 0


@pytest.mark.parametrize(
    ("accesses", "roles"),
    [
        ([], [_role_row()]),
        ([_access_row(), _access_row(access_id=uuid.uuid4())], [_role_row()]),
        ([_access_row()], []),
        ([_access_row()], [_role_row(role_name="membro")]),
        ([_access_row()], [_role_row(role_tenant_id=uuid.uuid4())]),
    ],
)
def test_unusable_or_nonministerial_access_never_authorizes(
    accesses: list[object],
    roles: list[object],
) -> None:
    meeting = _meeting()
    db = _authorized_session(meeting, accesses=accesses, roles=roles)
    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(db)
    assert raised.value.code in {
        application.CellReportApplicationErrorCode.ACTOR_NOT_AUTHORIZED,
        application.CellReportApplicationErrorCode.DATA_INTEGRITY,
    }
    assert meeting.relatorio_snapshot is None
    assert db.flush_calls == 0


@pytest.mark.parametrize(
    "leader_rows",
    [
        [],
        [_leader_row(cell_active=False)],
        [_leader_row(leader_id=uuid.uuid4())],
        [_leader_row(actor_archived_at=NOW)],
        [_leader_row(actor_without_interest=True)],
    ],
)
def test_revoked_leadership_or_inactive_actor_fails_before_access_lookup(
    leader_rows: list[object],
) -> None:
    meeting = _meeting()
    db = _authorized_session(meeting, cells_and_people=leader_rows)
    with pytest.raises(application.CellReportApplicationError):
        _propose(db)
    assert meeting.relatorio_snapshot is None
    assert db.flush_calls == 0


def test_unknown_pending_jsonb_is_never_overwritten() -> None:
    legacy = {"presencas": [], "observacoes": "private"}
    meeting = _meeting(relatorio_snapshot=legacy)
    db = _authorized_session(meeting)
    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(db)
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.REPORT_CONFLICT
    )
    assert meeting.relatorio_snapshot is legacy
    assert db.flush_calls == 0


@pytest.mark.parametrize(
    ("conversations", "code"),
    [
        ([], application.CellReportApplicationErrorCode.ACTOR_NOT_AUTHORIZED),
        (
            [_conversation_row(), _conversation_row()],
            application.CellReportApplicationErrorCode.DATA_INTEGRITY,
        ),
        (
            [_conversation_row(person_id=uuid.uuid4())],
            application.CellReportApplicationErrorCode.DATA_INTEGRITY,
        ),
        (
            [_conversation_row(tenant_id=uuid.uuid4())],
            application.CellReportApplicationErrorCode.DATA_INTEGRITY,
        ),
        (
            [_conversation_row(state="humano")],
            application.CellReportApplicationErrorCode.ACTOR_NOT_AUTHORIZED,
        ),
        (
            [_conversation_row(assumed_by=ACCESS)],
            application.CellReportApplicationErrorCode.ACTOR_NOT_AUTHORIZED,
        ),
        (
            [_conversation_row(state="unknown")],
            application.CellReportApplicationErrorCode.DATA_INTEGRITY,
        ),
        (
            [_conversation_row(official_number=False)],
            application.CellReportApplicationErrorCode.DATA_INTEGRITY,
        ),
    ],
)
def test_conversation_binding_handoff_and_official_number_fail_closed(
    conversations: list[object],
    code: application.CellReportApplicationErrorCode,
) -> None:
    meeting = _meeting()
    db = _authorized_session(meeting, conversations=conversations)
    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(db)
    assert raised.value.code is code
    assert meeting.relatorio_snapshot is None
    assert db.flush_calls == 0


@pytest.mark.parametrize(
    ("meeting_overrides", "code"),
    [
        (
            {"status": "cancelada"},
            application.CellReportApplicationErrorCode.REPORT_CONFLICT,
        ),
        (
            {"data": dt.date(2026, 9, 1), "status": "planejada"},
            application.CellReportApplicationErrorCode.REPORT_CONFLICT,
        ),
        (
            {"status": "inventada"},
            application.CellReportApplicationErrorCode.DATA_INTEGRITY,
        ),
        (
            {"relatorio_status": "inventado"},
            application.CellReportApplicationErrorCode.DATA_INTEGRITY,
        ),
        (
            {"relatorio_enviado_em": NOW},
            application.CellReportApplicationErrorCode.DATA_INTEGRITY,
        ),
        (
            {"relatorio_enviado_por": ACTOR},
            application.CellReportApplicationErrorCode.DATA_INTEGRITY,
        ),
    ],
)
def test_meeting_eligibility_and_pending_shape_are_revalidated_under_lock(
    meeting_overrides: dict[str, object],
    code: application.CellReportApplicationErrorCode,
) -> None:
    meeting = _meeting(**meeting_overrides)
    db = _authorized_session(meeting)
    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(db)
    assert raised.value.code is code
    assert meeting.relatorio_snapshot is None
    assert db.flush_calls == 0


def test_actor_optout_revokes_report_authority_before_access_lookup() -> None:
    meeting = _meeting()
    db = _authorized_session(
        meeting,
        cells_and_people=[_leader_row(actor_optout=True)],
    )
    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(db)
    assert raised.value.code in {
        application.CellReportApplicationErrorCode.ACTOR_NOT_AUTHORIZED,
        application.CellReportApplicationErrorCode.DATA_INTEGRITY,
    }
    assert meeting.relatorio_snapshot is None
    assert db.flush_calls == 0


def test_input_and_persisted_expiry_are_bounded_fail_closed() -> None:
    too_long = _FakeSession([])
    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(
            too_long,
            expiry=NOW + application.MAX_CELL_REPORT_PROPOSAL_TTL
            + dt.timedelta(microseconds=1),
        )
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.EXPIRY_LIMIT_EXCEEDED
    )
    assert too_long.statements == []

    meeting = _meeting()
    proposal = _propose(_authorized_session(meeting))
    meeting.relatorio_snapshot["expires_at"] = (
        "9999-12-31T23:59:59.999999Z"
    )
    db = _authorized_session(meeting)
    with pytest.raises(application.CellReportApplicationError) as raised:
        _confirm(
            db,
            command=proposal.confirmation_command,  # type: ignore[arg-type]
        )
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.PROPOSAL_CORRUPT
    )
    assert meeting.relatorio_status == "pendente"
    assert db.flush_calls == 0


def test_stale_a_retry_after_b_is_conflict_not_reapplied_revision() -> None:
    first_text = "10 presentes e oferta 0"
    identity_a, intent_a = _proposal_plan(
        text=first_text,
        inbound=INBOUND_1,
    )
    meeting = _meeting()
    _propose(
        _authorized_session(meeting),
        text=first_text,
        turn_identity=identity_a,
        operation_intent=intent_a,
    )
    second = _propose(
        _authorized_session(meeting),
        text="2 visitantes e 1 decisão",
        inbound=INBOUND_2,
    )
    before = meeting.relatorio_snapshot
    db = _authorized_session(meeting)

    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(
            db,
            text=first_text,
            turn_identity=identity_a,
            operation_intent=intent_a,
        )
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.REPORT_CONFLICT
    )
    assert meeting.relatorio_snapshot is before
    assert second.proposal.workflow.revision == 2
    assert db.flush_calls == 0


def test_receipt_history_rejects_new_operation_at_33_without_eviction() -> None:
    meeting = _meeting()
    first = _propose(_authorized_session(meeting))
    assert first.proposal.workflow.revision == 1
    for index in range(2, 33):
        current = _propose(
            _authorized_session(meeting),
            text=f"{index} presentes",
            inbound=uuid.UUID(int=1000 + index),
        )
    assert current.proposal.workflow.revision == 32
    assert len(current.proposal.operation_receipts) == 32
    first_receipt = current.proposal.operation_receipts[0]

    db = _authorized_session(meeting)
    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(
            db,
            text="33 presentes",
            inbound=uuid.UUID(int=1033),
        )
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.OPERATION_LIMIT_EXCEEDED
    )
    persisted = application._hydrate_pending(meeting.relatorio_snapshot)
    assert persisted.operation_receipts[0] == first_receipt
    assert len(persisted.operation_receipts) == 32
    assert db.flush_calls == 0


def test_effect_target_binding_rejects_reuse_before_any_database_query() -> None:
    identity, intent = _proposal_plan(
        text="1 presente",
        inbound=INBOUND_1,
    )
    other_meeting = uuid.UUID("99999999-1111-1111-1111-111111111111")
    db = _FakeSession([])
    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(
            db,
            text="1 presente",
            meeting_id=other_meeting,
            turn_identity=identity,
            operation_intent=intent,
        )
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.IDEMPOTENCY_CONFLICT
    )
    assert db.statements == []


def test_effect_contract_explicitly_does_not_claim_global_cross_row_receipt() -> None:
    identity = _identity(inbound=INBOUND_1)
    first_payload = application.build_cell_report_proposal_effect_payload(
        igreja_id=TENANT,
        reuniao_id=MEETING,
        conversa_id=CONVERSATION,
        ator_pessoa_id=ACTOR,
        correlation_key=SCOPE,
        text="1 presente",
        expires_at=EXPIRY,
    )
    second_payload = application.build_cell_report_proposal_effect_payload(
        igreja_id=TENANT,
        reuniao_id=uuid.UUID("99999999-1111-1111-1111-111111111111"),
        conversa_id=CONVERSATION,
        ator_pessoa_id=ACTOR,
        correlation_key=SCOPE,
        text="1 presente",
        expires_at=EXPIRY,
    )
    first = build_agent_effect_intent(
        identity,
        kind=AgentEffectKind.TOOL_CALL,
        ordinal=0,
        payload=first_payload,
    )
    second = build_agent_effect_intent(
        identity,
        kind=AgentEffectKind.TOOL_CALL,
        ordinal=0,
        payload=second_payload,
    )
    assert first.effect_id == second.effect_id
    assert first.payload_digest != second.payload_digest


def test_final_replay_binds_exact_command_and_conversation() -> None:
    meeting = _meeting()
    proposal = _propose(_authorized_session(meeting))
    _confirm(
        _authorized_session(meeting),
        command=proposal.confirmation_command,  # type: ignore[arg-type]
    )
    wrong_code = "AAAAAAAAAAAA"
    if proposal.confirmation_command == f"CONFIRMAR RELATORIO {wrong_code}":
        wrong_code = "BBBBBBBBBBBB"
    wrong_command = f"CONFIRMAR RELATORIO {wrong_code}"
    identity = _identity(inbound=INBOUND_FINAL)
    wrong_intent = build_agent_effect_intent(
        identity,
        kind=AgentEffectKind.TOOL_CALL,
        ordinal=0,
        payload=application.build_cell_report_confirmation_effect_payload(
            igreja_id=TENANT,
            reuniao_id=MEETING,
            conversa_id=CONVERSATION,
            ator_pessoa_id=ACTOR,
            command=wrong_command,
        ),
    )
    assert wrong_intent.effect_id == (
        meeting.relatorio_snapshot["submission_effect_id"]
    )
    assert wrong_intent.payload_digest != (
        meeting.relatorio_snapshot["submission_payload_digest"]
    )
    wrong_command_db = _authorized_session(meeting)
    with pytest.raises(application.CellReportApplicationError) as raised:
        _confirm(
            wrong_command_db,
            command=wrong_command,
            turn_identity=identity,
            submission_intent=wrong_intent,
        )
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.REPORT_CONFLICT
    )

    other_conversation = uuid.UUID(
        "88888888-8888-8888-8888-888888888888"
    )
    other_db = _authorized_session(
        meeting,
        conversations=[
            _conversation_row(conversation_id=other_conversation)
        ],
    )
    with pytest.raises(application.CellReportApplicationError) as raised:
        _confirm(
            other_db,
            command=proposal.confirmation_command,  # type: ignore[arg-type]
            conversation=other_conversation,
        )
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.REPORT_CONFLICT
    )
    assert wrong_command_db.flush_calls == other_db.flush_calls == 0


def test_flush_error_is_sanitized_and_suppresses_private_exception_chain() -> None:
    private_text = "private.person@example.invalid"
    error = StatementError(
        "write failed",
        "INSERT INTO cell_report",
        {"observacoes": private_text},
        RuntimeError(private_text),
    )
    meeting = _meeting()
    db = _authorized_session(meeting, flush_error=error)
    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(
            db,
            text=(
                "1 presente, 0 visitantes, 0 decisões, oferta 0, "
                f"obs: {private_text}"
            ),
        )
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.DATA_INTEGRITY
    )
    assert private_text not in str(raised.value)
    assert private_text not in repr(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert db.flush_calls == 1


@pytest.mark.parametrize("fetch_path", ["execute", "rows", "scalars"])
def test_fetch_time_database_error_is_sanitized_for_every_result_shape(
    fetch_path: str,
) -> None:
    private_text = "private.fetch@example.invalid"
    error = StatementError(
        "fetch failed",
        "SELECT cell_report",
        {"private": private_text},
        RuntimeError(private_text),
    )
    if fetch_path == "execute":
        db = _FakeSession([], execute_error=error)
    elif fetch_path == "rows":
        responses = [_Result(rows_error=error)]
        db = _FakeSession(responses)
    else:
        responses = [
            _Result(rows=[_conversation_row()]),
            _Result(scalars_error=error),
        ]
        db = _FakeSession(responses)

    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(db)

    assert raised.value.code is (
        application.CellReportApplicationErrorCode.DATA_INTEGRITY
    )
    assert private_text not in str(raised.value)
    assert private_text not in repr(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert db.flush_calls == 0


def test_tenant_scope_database_error_is_sanitized_before_domain_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_text = "private.scope@example.invalid"
    error = StatementError(
        "scope failed",
        "SELECT tenant_scope",
        {"private": private_text},
        RuntimeError(private_text),
    )

    def fail_scope(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(application, "require_tenant_scope", fail_scope)
    db = _FakeSession([])

    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(db)

    assert raised.value.code is (
        application.CellReportApplicationErrorCode.DATA_INTEGRITY
    )
    assert private_text not in str(raised.value)
    assert private_text not in repr(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert db.statements == []
    assert db.flush_calls == 0


def test_invalid_input_and_missing_transaction_fail_before_domain_queries() -> None:
    no_transaction = _FakeSession([], transaction_active=False)
    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(no_transaction)
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.TRANSACTION_REQUIRED
    )
    assert no_transaction.statements == []

    invalid = _FakeSession([])
    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(invalid, text="oferta 1000000.00")
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.INVALID_ARGUMENT
    )
    assert invalid.statements == []

    malformed_command = _FakeSession([])
    with pytest.raises(application.CellReportApplicationError) as raised:
        _confirm(malformed_command, command="confirmar")
    assert raised.value.code is (
        application.CellReportApplicationErrorCode.INVALID_ARGUMENT
    )
    assert malformed_command.statements == []

    private_text = "private.person@example.invalid"
    private = _FakeSession([])
    with pytest.raises(application.CellReportApplicationError) as raised:
        _propose(private, text=private_text)
    assert private_text not in str(raised.value)
    assert private_text not in repr(raised.value)
    assert private.statements == []


def test_sql_shape_locks_explicit_tenant_target_and_server_side_authority() -> None:
    statements = [
        application._conversation_actor_statement(
            igreja_id=TENANT,
            conversa_id=CONVERSATION,
            ator_pessoa_id=ACTOR,
        ),
        application._locked_meeting_statement(
            igreja_id=TENANT,
            reuniao_id=MEETING,
        ),
        application._active_leader_statement(
            igreja_id=TENANT,
            celula_id=CELL,
            ator_pessoa_id=ACTOR,
        ),
        application._usable_access_statement(
            igreja_id=TENANT,
            ator_pessoa_id=ACTOR,
        ),
        application._ministerial_role_statement(
            igreja_id=TENANT,
            app_user_id=ACCESS,
        ),
    ]
    sql = [
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": False},
            )
        )
        for statement in statements
    ]

    assert "conversations.igreja_id" in sql[0]
    assert "conversations.id" in sql[0]
    assert "conversations.pessoa_id" in sql[0]
    assert "conversations.estado" in sql[0]
    assert "conversations.assumido_por" in sql[0]
    assert "conversations.numero_oficial" in sql[0]
    assert "LIMIT" in sql[0] and "FOR UPDATE" in sql[0]
    assert "celula_reuniao.igreja_id" in sql[1]
    assert "celula_reuniao.id" in sql[1]
    assert "LIMIT" in sql[1] and "FOR UPDATE" in sql[1]
    assert "celulas.igreja_id" in sql[2]
    assert "celulas.lider_id" in sql[2]
    assert "celulas.ativo IS true" in sql[2]
    assert "pessoas.igreja_id" in sql[2]
    assert "pessoas.arquivada_em IS NULL" in sql[2]
    assert "pessoas.sem_interesse IS false" in sql[2]
    assert "pessoas.optout IS false" in sql[2]
    assert "FOR UPDATE" in sql[2]
    assert "app_users.igreja_id" in sql[3]
    assert "app_users.pessoa_id" in sql[3]
    assert "app_users.clerk_user_id IS NOT NULL" in sql[3]
    assert "app_users.status IS NULL" in sql[3]
    assert "app_users.status =" in sql[3]
    assert "LIMIT" in sql[3] and "FOR UPDATE" in sql[3]
    assert "user_roles.igreja_id" in sql[4]
    assert "user_roles.user_id" in sql[4]
    assert "user_roles.papel IN" in sql[4]
    assert "FOR UPDATE" in sql[4]


def test_success_path_acquires_locks_in_one_canonical_order() -> None:
    db = _authorized_session(_meeting())
    _propose(db)
    sql = [
        str(statement.compile(dialect=postgresql.dialect()))
        for statement in db.statements
    ]
    assert len(sql) == 5
    assert "FROM conversations" in sql[0]
    assert "FROM celula_reuniao" in sql[1]
    assert "FROM celulas JOIN pessoas" in sql[2]
    assert "FROM app_users" in sql[3]
    assert "FROM user_roles" in sql[4]
    assert all("FOR UPDATE" in statement for statement in sql)


def test_application_module_never_owns_transaction_completion_or_runtime() -> None:
    source = inspect.getsource(application)
    tree = ast.parse(source)
    method_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert method_calls.isdisjoint({"begin", "commit", "rollback"})
    assert "app.agent.runtime" not in source
    assert "queue_worker" not in source
