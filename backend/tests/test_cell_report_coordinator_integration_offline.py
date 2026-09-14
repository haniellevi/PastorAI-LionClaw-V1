from __future__ import annotations

import datetime as dt
import inspect
import uuid
from dataclasses import dataclass

import pytest

from app.agent.turn_identity import AgentInboundProvider, AgentTurnIdentity
from app.deps import CurrentUser
from app.services import cell_report_meeting_target_adapter as adapter
from app.services import cell_report_whatsapp_coordinator as coordinator


TENANT = uuid.UUID("a1111111-a111-4a11-8a11-a11111111111")
OTHER_TENANT = uuid.UUID("b2222222-b222-4b22-8b22-b22222222222")
CONVERSATION = uuid.UUID("c3333333-c333-4c33-8c33-c33333333333")
OTHER_CONVERSATION = uuid.UUID("d4444444-d444-4d44-8d44-d44444444444")
INBOUND = uuid.UUID("e5555555-e555-4e55-8e55-e55555555555")
OTHER_INBOUND = uuid.UUID("f6666666-f666-4f66-8f66-f66666666666")
ACTOR = uuid.UUID("a7777777-a777-4a77-8a77-a77777777777")
OTHER_ACTOR = uuid.UUID("b8888888-b888-4b88-8b88-b88888888888")
ACCESS = uuid.UUID("c9999999-c999-4c99-8c99-c99999999999")
ROLE = uuid.UUID("daaaaaaa-daaa-4daa-daaa-daaaaaaaaaaa")
CELL = uuid.UUID("ebbbbbbb-ebbb-4ebb-8ebb-ebbbbbbbbbbb")
MEETING = uuid.UUID("fccccccc-fccc-4fcc-8fcc-fccccccccccc")
OTHER_MEETING = uuid.UUID("addddddd-addd-4add-8add-addddddddddd")
NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.timezone.utc)
MEETING_DATE = dt.date(2026, 9, 1)
MEETING_TIME = "20:00"


@dataclass(frozen=True, slots=True)
class _ScopeRow:
    """Read-only stand-in for the exact RLS probe row, never a scope setter."""

    role: str | None
    igreja_id: str | None
    tenant_guc: str | None


_MISSING = object()


class _ReadResult:
    def __init__(
        self,
        rows: list[object] | None = None,
        *,
        one: object = _MISSING,
    ) -> None:
        self._rows = None if rows is None else list(rows)
        self._one = one

    def all(self) -> list[object]:
        if self._rows is None:
            raise AssertionError("read-only result was expected to use one()")
        return list(self._rows)

    def one(self) -> object:
        if self._one is _MISSING:
            raise AssertionError("read-only result was expected to use all()")
        return self._one


class _NoAutoflush:
    def __init__(self, session: _DirtyReadOnlySession) -> None:
        self._session = session
        self._previous: bool | None = None

    def __enter__(self) -> _DirtyReadOnlySession:
        self._previous = self._session.autoflush
        self._session.no_autoflush_entries += 1
        self._session.autoflush = False
        return self._session

    def __exit__(
        self,
        _exception_type: object,
        _exception: object,
        _traceback: object,
    ) -> bool:
        assert self._previous is not None
        self._session.autoflush = self._previous
        self._session.no_autoflush_exits += 1
        return False


class _DirtyReadOnlySession:
    """Session double with pending DML that permits only protected SELECTs.

    This emulates a caller-owned dirty session.  Any unprotected read triggers
    an implicit flush, and every explicit write primitive is an AssertionError.
    It is deliberately a read-only RLS probe double, not a writer or a consent
    substitute.
    """

    def __init__(
        self,
        responses: list[_ReadResult],
        *,
        active: bool = True,
    ) -> None:
        self.responses = list(responses)
        self.active = active
        self.root = object() if active else None
        self.nested = None
        self.autoflush = True
        self.pending_dml = True
        self.statements: list[object] = []
        self.autoflush_at_execute: list[bool] = []
        self.transaction_handles_seen: list[object | None] = []
        self.nested_handles_seen: list[object | None] = []
        self.no_autoflush_entries = 0
        self.no_autoflush_exits = 0
        self.implicit_flush_calls = 0
        self.flush_calls = 0
        self.write_attempts: list[str] = []

    @property
    def no_autoflush(self) -> _NoAutoflush:
        return _NoAutoflush(self)

    def in_transaction(self) -> bool:
        return self.active

    def get_transaction(self) -> object | None:
        self.transaction_handles_seen.append(self.root)
        return self.root

    def get_nested_transaction(self) -> object | None:
        self.nested_handles_seen.append(self.nested)
        return self.nested

    def execute(self, statement: object) -> _ReadResult:
        if not _is_read_statement(statement):
            self._deny_write("DML execute")
        self.autoflush_at_execute.append(self.autoflush)
        if self.autoflush and self.pending_dml:
            self.implicit_flush_calls += 1
            self.flush()
        self.statements.append(statement)
        if not self.responses:
            raise AssertionError("unexpected read in offline composition")
        return self.responses.pop(0)

    def commit(self, *_args: object, **_kwargs: object) -> None:
        self._deny_write("commit")

    def rollback(self, *_args: object, **_kwargs: object) -> None:
        self._deny_write("rollback")

    def flush(self, *_args: object, **_kwargs: object) -> None:
        self.flush_calls += 1
        self._deny_write("flush")

    def add(self, *_args: object, **_kwargs: object) -> None:
        self._deny_write("add")

    def add_all(self, *_args: object, **_kwargs: object) -> None:
        self._deny_write("add_all")

    def delete(self, *_args: object, **_kwargs: object) -> None:
        self._deny_write("delete")

    def merge(self, *_args: object, **_kwargs: object) -> None:
        self._deny_write("merge")

    def begin(self, *_args: object, **_kwargs: object) -> None:
        self._deny_write("begin")

    def begin_nested(self, *_args: object, **_kwargs: object) -> None:
        self._deny_write("begin_nested")

    def bulk_save_objects(self, *_args: object, **_kwargs: object) -> None:
        self._deny_write("bulk_save_objects")

    def bulk_insert_mappings(self, *_args: object, **_kwargs: object) -> None:
        self._deny_write("bulk_insert_mappings")

    def bulk_update_mappings(self, *_args: object, **_kwargs: object) -> None:
        self._deny_write("bulk_update_mappings")

    def _deny_write(self, operation: str) -> None:
        self.write_attempts.append(operation)
        raise AssertionError(f"offline read-only session refuses {operation}")


class _CountingClock:
    def __init__(self, value: dt.datetime) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> dt.datetime:
        self.calls += 1
        return self.value


class _AlwaysFailTripwire:
    """A negative reachability probe, never a fake writer or consent gate."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    def __call__(self, *_args: object, **_kwargs: object) -> object:
        self.calls += 1
        raise AssertionError(f"{self.name} must remain unreachable before consent")


def _is_read_statement(statement: object) -> bool:
    kind = type(statement).__name__
    if kind == "Select":
        return True
    if kind != "TextClause":
        return False
    text = getattr(statement, "text", None)
    return type(text) is str and text.lstrip().lower().startswith("select")


def _rows(rows: list[object]) -> _ReadResult:
    return _ReadResult(rows)


def _scope(
    tenant: uuid.UUID,
    *,
    role: str | None = "authenticated",
    igreja_id: str | None | object = _MISSING,
    tenant_guc: str | None | object = _MISSING,
) -> _ReadResult:
    return _ReadResult(
        one=_ScopeRow(
            role=role,
            igreja_id=str(tenant) if igreja_id is _MISSING else igreja_id,
            tenant_guc=str(tenant) if tenant_guc is _MISSING else tenant_guc,
        )
    )


def _current_user() -> CurrentUser:
    return CurrentUser(
        app_user_id=str(ACCESS),
        clerk_user_id="clerk-synthetic-coordination",
        igreja_id=str(TENANT),
        email="coordination@invalid.test",
        nome="Coordenação Sintética",
        roles=frozenset({"lider_celula"}),
    )


def _identity(
    *,
    tenant: uuid.UUID = TENANT,
    conversation: uuid.UUID = CONVERSATION,
    inbound: uuid.UUID = INBOUND,
) -> AgentTurnIdentity:
    return AgentTurnIdentity(
        igreja_id=tenant,
        conversation_id=conversation,
        inbound_message_id=inbound,
        provider=AgentInboundProvider.EVOLUTION,
        provider_message_id=f"synthetic-provider-{inbound.hex}",
    )


def _inbound_row(
    identity: AgentTurnIdentity,
    *,
    actor: uuid.UUID = ACTOR,
    provider_message_id: str | None = None,
) -> tuple[object, ...]:
    return (
        identity.inbound_message_id,
        identity.igreja_id,
        identity.conversation_id,
        "in",
        "contato",
        None,
        identity.provider_message_id
        if provider_message_id is None
        else provider_message_id,
        "relatorio sintetico",
        "texto",
        None,
        None,
        None,
        None,
        identity.conversation_id,
        identity.igreja_id,
        actor,
        "ia",
        None,
        True,
    )


def _actor_responses(tenant: uuid.UUID, actor: uuid.UUID = ACTOR) -> list[_ReadResult]:
    return [
        _rows([(ACCESS, tenant, actor, "ativo")]),
        _rows([(ACCESS, tenant, actor)]),
        _rows([(ROLE, tenant, ACCESS, "lider_celula")]),
    ]


def _meeting_row(
    *,
    meeting_id: uuid.UUID = MEETING,
    tenant: uuid.UUID = TENANT,
    actor: uuid.UUID = ACTOR,
    meeting_time: str = MEETING_TIME,
) -> tuple[object, ...]:
    return (
        meeting_id,
        tenant,
        CELL,
        MEETING_DATE,
        meeting_time,
        "realizada",
        "pendente",
        CELL,
        tenant,
        True,
        actor,
        actor,
        tenant,
        None,
        False,
        False,
    )


def _adapter_responses(
    identity: AgentTurnIdentity,
    *,
    meeting_rows: list[object],
    reaches_mint: bool,
) -> list[_ReadResult]:
    responses = [
        _scope(identity.igreja_id),
        _scope(identity.igreja_id),
        _rows([_inbound_row(identity)]),
        *_actor_responses(identity.igreja_id),
        _scope(identity.igreja_id),
        *_actor_responses(identity.igreja_id),
        _rows(meeting_rows),
    ]
    if reaches_mint:
        responses.extend(
            [
                _scope(identity.igreja_id),
                *_actor_responses(identity.igreja_id),
            ]
        )
    return responses


def _stage_responses(
    identity: AgentTurnIdentity,
    *,
    inbound: tuple[object, ...] | None = None,
    scope: _ReadResult | None = None,
) -> list[_ReadResult]:
    return [
        _scope(identity.igreja_id) if scope is None else scope,
        _rows([_inbound_row(identity) if inbound is None else inbound]),
    ]


def _resolve_real_target(
    db: _DirtyReadOnlySession,
    *,
    identity: AgentTurnIdentity,
    clock: _CountingClock,
) -> coordinator.CellReportMeetingTarget:
    target = adapter.resolve_cell_report_meeting_target(
        db,  # type: ignore[arg-type]
        current_user=_current_user(),
        turn_identity=identity,
        clock=clock,
    )
    assert type(target) is coordinator.CellReportMeetingTarget
    assert target.meeting_id == MEETING
    return target


def _install_downstream_tripwires(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_AlwaysFailTripwire, ...]:
    tripwires = (
        _AlwaysFailTripwire("prepare_cell_report_proposal_cycle"),
        _AlwaysFailTripwire("build_cell_report_proposal_effect_payload_for_cycle"),
        _AlwaysFailTripwire("propose_cell_report_from_cycle"),
    )
    for name, tripwire in zip(
        (
            "prepare_cell_report_proposal_cycle",
            "build_cell_report_proposal_effect_payload_for_cycle",
            "propose_cell_report_from_cycle",
        ),
        tripwires,
        strict=True,
    ):
        monkeypatch.setattr(coordinator, name, tripwire)
    return tripwires


def _assert_tripwires_unreached(
    tripwires: tuple[_AlwaysFailTripwire, ...],
) -> None:
    assert [tripwire.calls for tripwire in tripwires] == [0, 0, 0]


def _assert_read_only(
    db: _DirtyReadOnlySession,
    *,
    expected_reads: int,
) -> None:
    assert len(db.statements) == expected_reads
    assert db.responses == []
    assert db.pending_dml is True
    assert db.implicit_flush_calls == 0
    assert db.flush_calls == 0
    assert db.write_attempts == []
    assert db.autoflush_at_execute == [False] * expected_reads
    assert all(_is_read_statement(statement) for statement in db.statements)
    assert db.autoflush is True
    assert db.no_autoflush_entries == db.no_autoflush_exits == 2


def _assert_sanitized_code(error: object, expected: object) -> None:
    assert getattr(error, "code") is expected
    rendered = f"{error!r} {error}"
    assert str(TENANT) not in rendered
    assert str(INBOUND) not in rendered
    assert "coordination@invalid.test" not in rendered


def test_real_adapter_target_hits_real_default_deny_before_application_staging_or_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    db = _DirtyReadOnlySession(
        _adapter_responses(identity, meeting_rows=[_meeting_row()], reaches_mint=True)
        + _stage_responses(identity)
    )
    clock = _CountingClock(NOW)
    tripwires = _install_downstream_tripwires(monkeypatch)
    default = inspect.signature(
        coordinator.stage_whatsapp_cell_report_proposal
    ).parameters["consent_gate"].default

    assert default is coordinator.DENY_ALL_OPERATIONAL_CONSENT_GATE
    assert type(default) is coordinator.DenyAllOperationalConsentGate
    with db.no_autoflush:
        target = _resolve_real_target(db, identity=identity, clock=clock)
        with pytest.raises(coordinator.CellReportCoordinatorError) as refusal:
            coordinator.stage_whatsapp_cell_report_proposal(
                db,  # type: ignore[arg-type]
                turn_identity=identity,
                target=target,
            )

    _assert_sanitized_code(
        refusal.value,
        coordinator.CellReportCoordinatorErrorCode.OPERATIONAL_CONSENT_DENIED,
    )
    assert clock.calls == 1
    assert db.transaction_handles_seen
    assert all(handle is db.root for handle in db.transaction_handles_seen)
    assert all(handle is None for handle in db.nested_handles_seen)
    _assert_tripwires_unreached(tripwires)
    _assert_read_only(db, expected_reads=17)


@pytest.mark.parametrize(
    "case",
    ["adulterated_target", "other_tenant", "other_inbound", "other_actor"],
)
def test_target_and_boundary_adulterations_reject_before_default_consent_or_effects(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    identity = _identity()
    stage_identity = identity
    stage_inbound = _inbound_row(stage_identity)
    if case == "other_tenant":
        stage_identity = _identity(
            tenant=OTHER_TENANT,
            conversation=OTHER_CONVERSATION,
            inbound=OTHER_INBOUND,
        )
        stage_inbound = _inbound_row(stage_identity)
    elif case == "other_inbound":
        stage_identity = _identity(inbound=OTHER_INBOUND)
        stage_inbound = _inbound_row(stage_identity)
    elif case == "other_actor":
        stage_inbound = _inbound_row(stage_identity, actor=OTHER_ACTOR)

    db = _DirtyReadOnlySession(
        _adapter_responses(identity, meeting_rows=[_meeting_row()], reaches_mint=True)
        + _stage_responses(stage_identity, inbound=stage_inbound)
    )
    clock = _CountingClock(NOW)
    tripwires = _install_downstream_tripwires(monkeypatch)

    with db.no_autoflush:
        target = _resolve_real_target(db, identity=identity, clock=clock)
        if case == "adulterated_target":
            object.__setattr__(target, "_meeting_id", OTHER_MEETING)
        with pytest.raises(coordinator.CellReportCoordinatorError) as refusal:
            coordinator.stage_whatsapp_cell_report_proposal(
                db,  # type: ignore[arg-type]
                turn_identity=stage_identity,
                target=target,
            )

    _assert_sanitized_code(
        refusal.value,
        coordinator.CellReportCoordinatorErrorCode.MEETING_TARGET_INVALID,
    )
    assert clock.calls == 1
    _assert_tripwires_unreached(tripwires)
    _assert_read_only(db, expected_reads=17)


def test_inbound_changed_after_real_target_resolution_is_rejected_before_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    db = _DirtyReadOnlySession(
        _adapter_responses(identity, meeting_rows=[_meeting_row()], reaches_mint=True)
        + _stage_responses(
            identity,
            inbound=_inbound_row(
                identity,
                provider_message_id="synthetic-provider-altered-after-resolution",
            ),
        )
    )
    clock = _CountingClock(NOW)
    tripwires = _install_downstream_tripwires(monkeypatch)

    with db.no_autoflush:
        target = _resolve_real_target(db, identity=identity, clock=clock)
        with pytest.raises(coordinator.CellReportCoordinatorError) as refusal:
            coordinator.stage_whatsapp_cell_report_proposal(
                db,  # type: ignore[arg-type]
                turn_identity=identity,
                target=target,
            )

    _assert_sanitized_code(
        refusal.value,
        coordinator.CellReportCoordinatorErrorCode.INBOUND_BINDING_INVALID,
    )
    assert clock.calls == 1
    _assert_tripwires_unreached(tripwires)
    _assert_read_only(db, expected_reads=17)


@pytest.mark.parametrize("scenario", ["none", "ambiguous", "overflow"])
def test_non_candidate_resolution_never_reaches_coordinator_stage(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    identity = _identity()
    if scenario == "none":
        meeting_rows: list[object] = []
        expected = adapter.CellReportMeetingTargetAdapterErrorCode.RESOLUTION_NOT_CANDIDATE
    elif scenario == "ambiguous":
        meeting_rows = [_meeting_row(), _meeting_row(meeting_id=OTHER_MEETING)]
        expected = adapter.CellReportMeetingTargetAdapterErrorCode.RESOLUTION_NOT_CANDIDATE
    else:
        meeting_rows = [
            _meeting_row(
                meeting_id=uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"offline-coordinator-overflow-{index}",
                )
            )
            for index in range(101)
        ]
        expected = adapter.CellReportMeetingTargetAdapterErrorCode.RESOLUTION_REJECTED
    db = _DirtyReadOnlySession(
        _adapter_responses(identity, meeting_rows=meeting_rows, reaches_mint=False)
    )
    clock = _CountingClock(NOW)
    tripwires = _install_downstream_tripwires(monkeypatch)

    with db.no_autoflush:
        with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as refusal:
            _resolve_real_target(db, identity=identity, clock=clock)

    _assert_sanitized_code(refusal.value, expected)
    assert clock.calls == 1
    _assert_tripwires_unreached(tripwires)
    _assert_read_only(db, expected_reads=11)


def test_missing_external_transaction_rejects_before_scope_or_domain_read() -> None:
    identity = _identity()
    db = _DirtyReadOnlySession([], active=False)
    clock = _CountingClock(NOW)

    with db.no_autoflush:
        with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as refusal:
            _resolve_real_target(db, identity=identity, clock=clock)

    _assert_sanitized_code(
        refusal.value,
        adapter.CellReportMeetingTargetAdapterErrorCode.INBOUND_REJECTED,
    )
    assert clock.calls == 0
    _assert_read_only(db, expected_reads=0)


def test_rls_loss_after_real_target_resolution_stops_before_inbound_or_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    db = _DirtyReadOnlySession(
        _adapter_responses(identity, meeting_rows=[_meeting_row()], reaches_mint=True)
        + [
            _scope(
                TENANT,
                tenant_guc=str(OTHER_TENANT),
            )
        ]
    )
    clock = _CountingClock(NOW)
    tripwires = _install_downstream_tripwires(monkeypatch)

    with db.no_autoflush:
        target = _resolve_real_target(db, identity=identity, clock=clock)
        with pytest.raises(coordinator.CellReportCoordinatorError) as refusal:
            coordinator.stage_whatsapp_cell_report_proposal(
                db,  # type: ignore[arg-type]
                turn_identity=identity,
                target=target,
            )

    _assert_sanitized_code(
        refusal.value,
        coordinator.CellReportCoordinatorErrorCode.TENANT_SCOPE_INVALID,
    )
    assert clock.calls == 1
    _assert_tripwires_unreached(tripwires)
    _assert_read_only(db, expected_reads=16)
