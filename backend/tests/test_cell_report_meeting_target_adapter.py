from __future__ import annotations

import datetime as dt
import traceback
import uuid
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.agent.turn_identity import AgentInboundProvider, AgentTurnIdentity
from app.db.tenant_session import TenantScopeError
from app.deps import CurrentUser
from app.services import cell_report_meeting_resolver as meeting_resolver
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
ROLE = uuid.UUID("daaaaaaa-daaa-4daa-8daa-daaaaaaaaaaa")
MEETING = uuid.UUID("ebbbbbbb-ebbb-4ebb-8ebb-ebbbbbbbbbbb")
OTHER_MEETING = uuid.UUID("fccccccc-fccc-4fcc-8fcc-fccccccccccc")
MEETING_DATE = dt.date(2026, 9, 1)
MEETING_TIME = "20:00"
EQUALITY_NOW = dt.datetime(2026, 9, 1, 20, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
AFTER_NOW = dt.datetime(2026, 9, 1, 20, 0, 1, tzinfo=ZoneInfo("America/Sao_Paulo"))


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self._rows = list(rows)

    def all(self) -> list[object]:
        return list(self._rows)


class _NoAutoflush:
    def __init__(self, session: _ReadOnlySession) -> None:
        self.session = session
        self.previous: bool | None = None

    def __enter__(self) -> _ReadOnlySession:
        self.previous = self.session.autoflush
        self.session.no_autoflush_entries += 1
        self.session.autoflush = False
        return self.session

    def __exit__(
        self,
        _exc_type: object,
        _exc_value: object,
        _traceback: object,
    ) -> bool:
        assert self.previous is not None
        self.session.autoflush = self.previous
        self.session.no_autoflush_exits += 1
        return False


class _ReadOnlySession:
    def __init__(
        self,
        responses: list[_Result],
        *,
        active: bool = True,
        root: object | None = None,
        nested: object | None = None,
        execute_error: Exception | None = None,
    ) -> None:
        self.responses = list(responses)
        self.active = active
        self.root = object() if root is None else root
        self.nested = nested
        self.execute_error = execute_error
        self.statements: list[object] = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.flush_calls = 0
        self.write_attempts = 0
        self.autoflush = True
        self.pending_dml = True
        self.implicit_flush_calls = 0
        self.no_autoflush_entries = 0
        self.no_autoflush_exits = 0
        self.autoflush_at_execute: list[bool] = []

    @property
    def no_autoflush(self) -> _NoAutoflush:
        return _NoAutoflush(self)

    def in_transaction(self) -> bool:
        return self.active

    def get_transaction(self) -> object | None:
        return self.root if self.active else None

    def get_nested_transaction(self) -> object | None:
        return self.nested

    def execute(self, statement: object) -> _Result:
        self.autoflush_at_execute.append(self.autoflush)
        if self.autoflush and self.pending_dml:
            self.implicit_flush_calls += 1
            self.flush()
        self.statements.append(statement)
        if self.execute_error is not None:
            raise self.execute_error
        if not self.responses:
            raise AssertionError("unexpected read")
        return self.responses.pop(0)

    def commit(self) -> None:
        self.commit_calls += 1
        self.write_attempts += 1
        raise AssertionError("adapter must not commit")

    def rollback(self) -> None:
        self.rollback_calls += 1
        self.write_attempts += 1
        raise AssertionError("adapter must not roll back")

    def flush(self) -> None:
        self.flush_calls += 1
        self.write_attempts += 1
        raise AssertionError("adapter must not flush")

    def add(self, _value: object) -> None:
        self.write_attempts += 1
        raise AssertionError("adapter must not add")

    def delete(self, _value: object) -> None:
        self.write_attempts += 1
        raise AssertionError("adapter must not delete")

    def begin(self) -> None:
        self.write_attempts += 1
        raise AssertionError("adapter must not open a transaction")

    def begin_nested(self) -> None:
        self.write_attempts += 1
        raise AssertionError("adapter must not open a nested transaction")


class _CountingClock:
    def __init__(self, value: dt.datetime) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> dt.datetime:
        self.calls += 1
        return self.value


def _current_user(**overrides: object) -> CurrentUser:
    values: dict[str, object] = {
        "app_user_id": str(ACCESS),
        "clerk_user_id": "clerk_synthetic_abc",
        "igreja_id": str(TENANT),
        "email": "synthetic@invalid.test",
        "nome": "Synthetic",
        "roles": frozenset({"lider_celula"}),
    }
    values.update(overrides)
    return CurrentUser(**values)


def _identity(**overrides: object) -> AgentTurnIdentity:
    values: dict[str, object] = {
        "igreja_id": TENANT,
        "conversation_id": CONVERSATION,
        "inbound_message_id": INBOUND,
        "provider": AgentInboundProvider.EVOLUTION,
        "provider_message_id": "provider_synthetic_abc",
    }
    values.update(overrides)
    return AgentTurnIdentity(**values)


def _inbound_row(**overrides: object) -> tuple[object, ...]:
    values: dict[str, object] = {
        "inbound_id": INBOUND,
        "message_tenant_id": TENANT,
        "message_conversation_id": CONVERSATION,
        "direction": "in",
        "author": "contato",
        "reply_state": None,
        "provider_message_id": "provider_synthetic_abc",
        "text": "relatorio sintetico",
        "message_type": "texto",
        "media_path": None,
        "media_mime": None,
        "media_name": None,
        "media_size": None,
        "conversation_id": CONVERSATION,
        "conversation_tenant_id": TENANT,
        "actor_pessoa_id": ACTOR,
        "conversation_state": "ia",
        "assumed_by": None,
        "official_number": True,
    }
    values.update(overrides)
    return tuple(values.values())


def _meeting_row(**overrides: object) -> tuple[object, ...]:
    values: dict[str, object] = {
        "meeting_id": MEETING,
        "meeting_tenant_id": TENANT,
        "meeting_cell_id": OTHER_CONVERSATION,
        "meeting_date": MEETING_DATE,
        "meeting_time": MEETING_TIME,
        "meeting_status": "realizada",
        "report_status": "pendente",
        "cell_id": OTHER_CONVERSATION,
        "cell_tenant_id": TENANT,
        "cell_active": True,
        "cell_leader_id": ACTOR,
        "person_id": ACTOR,
        "person_tenant_id": TENANT,
        "person_archived_at": None,
        "person_optout": False,
        "person_without_interest": False,
    }
    values.update(overrides)
    return tuple(values.values())


def _actor_responses() -> list[_Result]:
    return [
        _Result([(ACCESS, TENANT, ACTOR, "ativo")]),
        _Result([(ACCESS, TENANT, ACTOR)]),
        _Result([(ROLE, TENANT, ACCESS, "lider_celula")]),
    ]


def _authorized_session() -> _ReadOnlySession:
    return _ReadOnlySession(
        [
            _Result([_inbound_row()]),
            *_actor_responses(),
            *_actor_responses(),
            _Result([_meeting_row()]),
            *_actor_responses(),
        ]
    )


def _context() -> coordinator._InboundContext:
    return coordinator._InboundContext(
        igreja_id=TENANT,
        conversation_id=CONVERSATION,
        actor_pessoa_id=ACTOR,
        inbound_message_id=INBOUND,
        text="relatorio sintetico",
    )


def _candidate() -> meeting_resolver.CellReportMeetingResolution:
    item = meeting_resolver.CellReportMeetingCandidate(
        reuniao_id=MEETING,
        celula_id=OTHER_CONVERSATION,
        data=MEETING_DATE,
        hora=MEETING_TIME,
        status="realizada",
        relatorio_status="pendente",
    )
    return meeting_resolver.CellReportMeetingResolution(
        status=meeting_resolver.CellReportMeetingResolutionStatus.CANDIDATE,
        candidate=item,
        candidates=(item,),
    )


def _none() -> meeting_resolver.CellReportMeetingResolution:
    return meeting_resolver.CellReportMeetingResolution(
        status=meeting_resolver.CellReportMeetingResolutionStatus.NONE,
        candidate=None,
        candidates=(),
    )


def _ambiguous() -> meeting_resolver.CellReportMeetingResolution:
    first = _candidate().candidate
    assert first is not None
    second = meeting_resolver.CellReportMeetingCandidate(
        reuniao_id=OTHER_MEETING,
        celula_id=OTHER_CONVERSATION,
        data=MEETING_DATE,
        hora="21:00",
        status="realizada",
        relatorio_status="pendente",
    )
    return meeting_resolver.CellReportMeetingResolution(
        status=meeting_resolver.CellReportMeetingResolutionStatus.AMBIGUOUS,
        candidate=None,
        candidates=(first, second),
    )


def _allow_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "require_tenant_scope", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        coordinator,
        "require_tenant_scope",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        meeting_resolver,
        "require_tenant_scope",
        lambda *args, **kwargs: None,
    )


def _assert_read_only(db: _ReadOnlySession) -> None:
    assert db.commit_calls == 0
    assert db.rollback_calls == 0
    assert db.flush_calls == 0
    assert db.write_attempts == 0
    assert db.implicit_flush_calls == 0
    assert db.autoflush is True
    assert db.no_autoflush_entries == db.no_autoflush_exits
    assert not any(db.autoflush_at_execute)


def _forbid_mint(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []

    def fail_mint(*args: object, **kwargs: object) -> coordinator.CellReportMeetingTarget:
        calls.append((args, kwargs))
        raise AssertionError("target must not be minted")

    monkeypatch.setattr(coordinator, "_mint_cell_report_meeting_target", fail_mint)
    return calls


@pytest.mark.parametrize(
    "overrides",
    [
        {"app_user_id": "not-a-uuid"},
        {"igreja_id": "not-a-uuid"},
        {"app_user_id": str(uuid.UUID(int=0))},
        {"clerk_user_id": " clerk_synthetic_abc"},
    ],
)
def test_invalid_current_user_id_or_type_fails_before_scope_or_read(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
) -> None:
    scope_calls: list[object] = []
    monkeypatch.setattr(
        adapter,
        "require_tenant_scope",
        lambda *args, **kwargs: scope_calls.append((args, kwargs)),
    )
    db = _ReadOnlySession([])

    with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as error:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(**overrides),
            turn_identity=_identity(),
            clock=_CountingClock(AFTER_NOW),
        )

    assert error.value.code is adapter.CellReportMeetingTargetAdapterErrorCode.INVALID_IDENTITY
    assert scope_calls == []
    assert db.statements == []
    _assert_read_only(db)


def test_invalid_turn_identity_or_cross_tenant_fails_before_scope_or_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_calls: list[object] = []
    monkeypatch.setattr(
        adapter,
        "require_tenant_scope",
        lambda *args, **kwargs: scope_calls.append((args, kwargs)),
    )
    db = _ReadOnlySession([])

    with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as invalid_error:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(),
            turn_identity=object(),  # type: ignore[arg-type]
            clock=_CountingClock(AFTER_NOW),
        )
    assert invalid_error.value.code is adapter.CellReportMeetingTargetAdapterErrorCode.INVALID_IDENTITY

    with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as tenant_error:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(),
            turn_identity=_identity(igreja_id=OTHER_TENANT),
            clock=_CountingClock(AFTER_NOW),
        )
    assert tenant_error.value.code is adapter.CellReportMeetingTargetAdapterErrorCode.INVALID_IDENTITY
    assert scope_calls == []
    assert db.statements == []
    _assert_read_only(db)


def test_initial_rls_failure_stops_before_inbound_resolver_or_mint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_scope(*args: object, **kwargs: object) -> None:
        assert kwargs["expected_igreja_id"] == TENANT
        raise TenantScopeError("synthetic scope divergence")

    monkeypatch.setattr(adapter, "require_tenant_scope", reject_scope)
    db = _ReadOnlySession([])
    mint_calls = _forbid_mint(monkeypatch)

    with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as error:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(),
            turn_identity=_identity(),
            clock=_CountingClock(AFTER_NOW),
        )

    assert error.value.code is adapter.CellReportMeetingTargetAdapterErrorCode.TENANT_SCOPE_REQUIRED
    assert db.statements == []
    assert mint_calls == []
    _assert_read_only(db)


def test_external_transaction_is_required_before_any_inbound_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_scopes(monkeypatch)
    db = _ReadOnlySession([], active=False)
    mint_calls = _forbid_mint(monkeypatch)

    with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as error:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(),
            turn_identity=_identity(),
            clock=_CountingClock(AFTER_NOW),
        )

    assert error.value.code is adapter.CellReportMeetingTargetAdapterErrorCode.INBOUND_REJECTED
    assert db.statements == []
    assert mint_calls == []
    _assert_read_only(db)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [_inbound_row(), _inbound_row()],
        [_inbound_row(message_tenant_id=OTHER_TENANT)],
        [_inbound_row(message_conversation_id=OTHER_CONVERSATION)],
        [_inbound_row(direction="out")],
        [_inbound_row(author="ia")],
        [_inbound_row(provider_message_id="provider_synthetic_other")],
        [_inbound_row(message_type="audio")],
        [_inbound_row(media_path="synthetic-media")],
        [_inbound_row(conversation_state="humano")],
        [_inbound_row(actor_pessoa_id=uuid.UUID(int=0))],
        [_inbound_row(text="   ")],
    ],
)
def test_absent_duplicate_or_adulterated_inbound_never_reaches_resolver_or_mint(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[object],
) -> None:
    _allow_scopes(monkeypatch)
    db = _ReadOnlySession([_Result(rows)])
    mint_calls = _forbid_mint(monkeypatch)

    def unexpected_resolver(*args: object, **kwargs: object) -> object:
        raise AssertionError("resolver must not run for invalid inbound")

    monkeypatch.setattr(
        meeting_resolver,
        "resolve_pending_cell_report_meeting",
        unexpected_resolver,
    )

    with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as error:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(),
            turn_identity=_identity(),
            clock=_CountingClock(AFTER_NOW),
        )

    assert error.value.code is adapter.CellReportMeetingTargetAdapterErrorCode.INBOUND_REJECTED
    assert len(db.statements) == 1
    assert mint_calls == []
    _assert_read_only(db)


def test_actor_mismatch_before_resolution_never_calls_clock_resolver_or_mint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_scopes(monkeypatch)
    root = object()
    db = _ReadOnlySession([], root=root)
    monkeypatch.setattr(
        coordinator,
        "_load_bound_inbound",
        lambda *args, **kwargs: (_context(), (root, None)),
    )
    monkeypatch.setattr(meeting_resolver, "_load_actor_pessoa_id", lambda *args, **kwargs: OTHER_ACTOR)
    mint_calls = _forbid_mint(monkeypatch)
    clock = _CountingClock(AFTER_NOW)

    with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as error:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(),
            turn_identity=_identity(),
            clock=clock,
        )

    assert error.value.code is adapter.CellReportMeetingTargetAdapterErrorCode.ACTOR_BINDING_INVALID
    assert clock.calls == 0
    assert mint_calls == []
    _assert_read_only(db)


@pytest.mark.parametrize("resolution", [_none(), _ambiguous()])
def test_none_or_ambiguous_resolution_fails_closed_without_mint(
    monkeypatch: pytest.MonkeyPatch,
    resolution: meeting_resolver.CellReportMeetingResolution,
) -> None:
    _allow_scopes(monkeypatch)
    root = object()
    db = _ReadOnlySession([], root=root)
    monkeypatch.setattr(
        coordinator,
        "_load_bound_inbound",
        lambda *args, **kwargs: (_context(), (root, None)),
    )
    monkeypatch.setattr(meeting_resolver, "_load_actor_pessoa_id", lambda *args, **kwargs: ACTOR)
    monkeypatch.setattr(
        meeting_resolver,
        "resolve_pending_cell_report_meeting",
        lambda *args, **kwargs: resolution,
    )
    mint_calls = _forbid_mint(monkeypatch)
    clock = _CountingClock(AFTER_NOW)

    with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as error:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(),
            turn_identity=_identity(),
            clock=clock,
        )

    assert error.value.code is adapter.CellReportMeetingTargetAdapterErrorCode.RESOLUTION_NOT_CANDIDATE
    assert clock.calls == 1
    assert mint_calls == []
    _assert_read_only(db)


def test_resolver_overflow_is_sanitized_and_never_mints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_scopes(monkeypatch)
    root = object()
    db = _ReadOnlySession([], root=root)
    monkeypatch.setattr(
        coordinator,
        "_load_bound_inbound",
        lambda *args, **kwargs: (_context(), (root, None)),
    )
    monkeypatch.setattr(meeting_resolver, "_load_actor_pessoa_id", lambda *args, **kwargs: ACTOR)

    def overflow(*args: object, **kwargs: object) -> object:
        raise meeting_resolver.CellReportMeetingResolverError(
            meeting_resolver.CellReportMeetingResolverErrorCode.TOO_MANY_CANDIDATES
        )

    monkeypatch.setattr(meeting_resolver, "resolve_pending_cell_report_meeting", overflow)
    mint_calls = _forbid_mint(monkeypatch)

    with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as error:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(),
            turn_identity=_identity(),
            clock=_CountingClock(AFTER_NOW),
        )

    assert error.value.code is adapter.CellReportMeetingTargetAdapterErrorCode.RESOLUTION_REJECTED
    assert mint_calls == []
    _assert_read_only(db)


def test_equal_meeting_time_is_ineligible_and_clock_is_called_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_scopes(monkeypatch)
    db = _authorized_session()
    clock = _CountingClock(EQUALITY_NOW)
    mint_calls = _forbid_mint(monkeypatch)

    with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as error:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(),
            turn_identity=_identity(),
            clock=clock,
        )

    assert error.value.code is adapter.CellReportMeetingTargetAdapterErrorCode.RESOLUTION_NOT_CANDIDATE
    assert clock.calls == 1
    assert mint_calls == []
    assert len(db.statements) == 8
    _assert_read_only(db)


def test_dirty_session_no_autoflush_suppresses_implicit_flush_and_mints_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_scopes(monkeypatch)
    db = _authorized_session()
    identity = _identity()
    clock = _CountingClock(AFTER_NOW)

    target = adapter.resolve_cell_report_meeting_target(
        db,
        current_user=_current_user(),
        turn_identity=identity,
        clock=clock,
    )

    assert type(target) is coordinator.CellReportMeetingTarget
    assert target.meeting_id == MEETING
    assert clock.calls == 1
    assert len(db.statements) == 11
    _assert_read_only(db)
    assert coordinator._require_meeting_target(
        target,
        identity=identity,
        context=_context(),
    ) is target

    with pytest.raises(coordinator.CellReportCoordinatorError):
        coordinator._require_meeting_target(
            target,
            identity=_identity(inbound_message_id=OTHER_INBOUND),
            context=_context(),
        )
    with pytest.raises(coordinator.CellReportCoordinatorError):
        coordinator._require_meeting_target(
            target,
            identity=identity,
            context=coordinator._InboundContext(
                igreja_id=TENANT,
                conversation_id=CONVERSATION,
                actor_pessoa_id=OTHER_ACTOR,
                inbound_message_id=INBOUND,
                text="relatorio sintetico",
            ),
        )
    object.__setattr__(target, "_meeting_id", OTHER_MEETING)
    with pytest.raises(coordinator.CellReportCoordinatorError):
        coordinator._require_meeting_target(
            target,
            identity=identity,
            context=_context(),
        )


@pytest.mark.parametrize("initial_autoflush", [True, False])
def test_no_autoflush_restores_original_state_after_rejected_inbound(
    monkeypatch: pytest.MonkeyPatch,
    initial_autoflush: bool,
) -> None:
    _allow_scopes(monkeypatch)
    db = _ReadOnlySession([_Result([_inbound_row(direction="out")])])
    db.autoflush = initial_autoflush
    mint_calls = _forbid_mint(monkeypatch)

    with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as error:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(),
            turn_identity=_identity(),
            clock=_CountingClock(AFTER_NOW),
        )

    assert error.value.code is adapter.CellReportMeetingTargetAdapterErrorCode.INBOUND_REJECTED
    assert len(db.statements) == 1
    assert db.implicit_flush_calls == 0
    assert db.flush_calls == 0
    assert db.write_attempts == 0
    assert db.autoflush_at_execute == [False]
    assert db.autoflush is initial_autoflush
    assert db.no_autoflush_entries == db.no_autoflush_exits == 1
    assert mint_calls == []


@pytest.mark.parametrize("swap_nested", [False, True])
def test_transaction_handle_swap_after_resolution_rejects_before_mint(
    monkeypatch: pytest.MonkeyPatch,
    swap_nested: bool,
) -> None:
    _allow_scopes(monkeypatch)
    root = object()
    nested = object()
    db = _ReadOnlySession([], root=root, nested=nested)
    monkeypatch.setattr(
        coordinator,
        "_load_bound_inbound",
        lambda *args, **kwargs: (_context(), (root, nested)),
    )
    monkeypatch.setattr(meeting_resolver, "_load_actor_pessoa_id", lambda *args, **kwargs: ACTOR)

    def resolve_and_swap(*args: object, **kwargs: object) -> meeting_resolver.CellReportMeetingResolution:
        if swap_nested:
            db.nested = object()
        else:
            db.root = object()
        return _candidate()

    monkeypatch.setattr(meeting_resolver, "resolve_pending_cell_report_meeting", resolve_and_swap)
    mint_calls = _forbid_mint(monkeypatch)

    with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as error:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(),
            turn_identity=_identity(),
            clock=_CountingClock(AFTER_NOW),
        )

    assert error.value.code is adapter.CellReportMeetingTargetAdapterErrorCode.TRANSACTION_BINDING_INVALID
    assert mint_calls == []
    _assert_read_only(db)


def test_rls_or_actor_change_after_resolution_rejects_before_mint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = object()
    db = _ReadOnlySession([], root=root)
    scope_calls = 0

    def scope(*args: object, **kwargs: object) -> None:
        nonlocal scope_calls
        scope_calls += 1
        if scope_calls == 2:
            raise TenantScopeError("synthetic post-resolution divergence")

    monkeypatch.setattr(adapter, "require_tenant_scope", scope)
    monkeypatch.setattr(coordinator, "require_tenant_scope", lambda *args, **kwargs: None)
    monkeypatch.setattr(meeting_resolver, "require_tenant_scope", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        coordinator,
        "_load_bound_inbound",
        lambda *args, **kwargs: (_context(), (root, None)),
    )
    monkeypatch.setattr(meeting_resolver, "_load_actor_pessoa_id", lambda *args, **kwargs: ACTOR)
    monkeypatch.setattr(meeting_resolver, "resolve_pending_cell_report_meeting", lambda *args, **kwargs: _candidate())
    mint_calls = _forbid_mint(monkeypatch)

    with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as error:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(),
            turn_identity=_identity(),
            clock=_CountingClock(AFTER_NOW),
        )

    assert error.value.code is adapter.CellReportMeetingTargetAdapterErrorCode.TENANT_SCOPE_REQUIRED
    assert scope_calls == 2
    assert mint_calls == []
    _assert_read_only(db)


def test_actor_change_after_resolution_rejects_before_mint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_scopes(monkeypatch)
    root = object()
    db = _ReadOnlySession([], root=root)
    actors = iter((ACTOR, OTHER_ACTOR))
    monkeypatch.setattr(
        coordinator,
        "_load_bound_inbound",
        lambda *args, **kwargs: (_context(), (root, None)),
    )
    monkeypatch.setattr(meeting_resolver, "_load_actor_pessoa_id", lambda *args, **kwargs: next(actors))
    monkeypatch.setattr(meeting_resolver, "resolve_pending_cell_report_meeting", lambda *args, **kwargs: _candidate())
    mint_calls = _forbid_mint(monkeypatch)

    with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as error:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(),
            turn_identity=_identity(),
            clock=_CountingClock(AFTER_NOW),
        )

    assert error.value.code is adapter.CellReportMeetingTargetAdapterErrorCode.ACTOR_BINDING_INVALID
    assert mint_calls == []
    _assert_read_only(db)


def test_clock_failure_and_resolver_database_failure_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_scopes(monkeypatch)
    root = object()
    db = _ReadOnlySession([], root=root)
    monkeypatch.setattr(
        coordinator,
        "_load_bound_inbound",
        lambda *args, **kwargs: (_context(), (root, None)),
    )
    monkeypatch.setattr(meeting_resolver, "_load_actor_pessoa_id", lambda *args, **kwargs: ACTOR)
    mint_calls = _forbid_mint(monkeypatch)

    def bad_clock() -> dt.datetime:
        raise RuntimeError("synthetic-clock-detail")

    try:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(),
            turn_identity=_identity(),
            clock=bad_clock,
        )
    except adapter.CellReportMeetingTargetAdapterError as error:
        clock_error = error
        clock_trace = traceback.format_exc()
    else:
        pytest.fail("clock failure should be sanitized")
    assert clock_error.code is adapter.CellReportMeetingTargetAdapterErrorCode.CLOCK_INVALID
    assert "synthetic-clock-detail" not in clock_trace

    def database_failure(*args: object, **kwargs: object) -> object:
        raise meeting_resolver.CellReportMeetingResolverError(
            meeting_resolver.CellReportMeetingResolverErrorCode.DATA_UNAVAILABLE
        )

    monkeypatch.setattr(meeting_resolver, "resolve_pending_cell_report_meeting", database_failure)
    with pytest.raises(adapter.CellReportMeetingTargetAdapterError) as resolution_error:
        adapter.resolve_cell_report_meeting_target(
            db,
            current_user=_current_user(),
            turn_identity=_identity(),
            clock=_CountingClock(AFTER_NOW),
        )
    assert resolution_error.value.code is adapter.CellReportMeetingTargetAdapterErrorCode.RESOLUTION_REJECTED
    assert mint_calls == []
    _assert_read_only(db)
