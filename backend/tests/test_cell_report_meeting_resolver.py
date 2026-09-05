from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.deps import CurrentUser
from app.services import cell_report_meeting_resolver as resolver


TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_TENANT = uuid.UUID("99999999-9999-9999-9999-999999999999")
MEETING = uuid.UUID("22222222-2222-2222-2222-222222222222")
MEETING_2 = uuid.UUID("88888888-8888-8888-8888-888888888888")
CELL = uuid.UUID("33333333-3333-3333-3333-333333333333")
ACTOR = uuid.UUID("55555555-5555-5555-5555-555555555555")
ACCESS = uuid.UUID("66666666-6666-6666-6666-666666666666")
ROLE = uuid.UUID("77777777-7777-7777-7777-777777777777")
NOW = dt.datetime(2026, 8, 31, 15, 0, tzinfo=dt.timezone.utc)


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return list(self.rows)


class _FakeSession:
    def __init__(self, responses: list[_Result]) -> None:
        self.responses = list(responses)
        self.statements: list[object] = []
        self.commit_calls = 0
        self.flush_calls = 0

    def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        if not self.responses:
            raise AssertionError("unexpected database query")
        return self.responses.pop(0)

    def commit(self) -> None:
        self.commit_calls += 1
        raise AssertionError("resolver must not commit")

    def flush(self) -> None:
        self.flush_calls += 1
        raise AssertionError("resolver must not flush")


@pytest.fixture(autouse=True)
def _tenant_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolver, "require_tenant_scope", lambda *args, **kwargs: None)


def _current_user(**overrides: object) -> CurrentUser:
    values: dict[str, object] = {
        "app_user_id": str(ACCESS),
        "clerk_user_id": "clerk-user-1",
        "igreja_id": str(TENANT),
        "email": "leader@example.test",
        "nome": "Leader",
        "roles": frozenset({"lider_celula"}),
    }
    values.update(overrides)
    return CurrentUser(**values)


def _meeting_row(**overrides: object) -> tuple[object, ...]:
    values: dict[str, object] = {
        "meeting_id": MEETING,
        "meeting_tenant_id": TENANT,
        "meeting_cell_id": CELL,
        "meeting_date": dt.date(2026, 8, 30),
        "meeting_time": "20:00",
        "meeting_status": "realizada",
        "report_status": "pendente",
        "cell_id": CELL,
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


def _authorized_session(
    meetings: list[tuple[object, ...]],
    *,
    actor_rows: list[object] | None = None,
    access_rows: list[object] | None = None,
    role_rows: list[object] | None = None,
) -> _FakeSession:
    return _FakeSession(
        [
            _Result(
                actor_rows
                if actor_rows is not None
                else [(ACCESS, TENANT, ACTOR, "ativo")]
            ),
            _Result(
                access_rows
                if access_rows is not None
                else [(ACCESS, TENANT, ACTOR)]
            ),
            _Result(
                role_rows
                if role_rows is not None
                else [(ROLE, TENANT, ACCESS, "lider_celula")]
            ),
            _Result(meetings),
        ]
    )


def test_resolves_one_server_bound_pending_meeting_without_writes() -> None:
    db = _authorized_session([_meeting_row()])

    result = resolver.resolve_pending_cell_report_meeting(
        db,
        current_user=_current_user(),
        now=NOW,
    )

    assert result.status is resolver.CellReportMeetingResolutionStatus.CANDIDATE
    assert result.candidate is not None
    assert result.candidate.reuniao_id == MEETING
    assert result.candidates == (result.candidate,)
    assert db.commit_calls == 0
    assert db.flush_calls == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"meeting_tenant_id": OTHER_TENANT, "cell_tenant_id": OTHER_TENANT},
        {"cell_active": False},
        {"meeting_date": dt.date(2026, 9, 1)},
        {"meeting_status": "cancelada"},
        {"report_status": "enviado"},
    ],
)
def test_rejects_cross_tenant_inactive_future_cancelled_or_completed(
    overrides: dict[str, object],
) -> None:
    db = _authorized_session([_meeting_row(**overrides)])

    result = resolver.resolve_pending_cell_report_meeting(
        db,
        current_user=_current_user(),
        now=NOW,
    )

    assert result.status is resolver.CellReportMeetingResolutionStatus.NONE
    assert result.candidate is None
    assert result.candidates == ()


def test_multiple_meetings_are_ambiguous_in_deterministic_order() -> None:
    later = _meeting_row(
        meeting_id=MEETING_2,
        meeting_date=dt.date(2026, 8, 30),
        meeting_time="21:00",
    )
    earlier = _meeting_row(
        meeting_date=dt.date(2026, 8, 29),
        meeting_time="20:00",
    )
    db = _authorized_session([later, earlier])

    result = resolver.resolve_pending_cell_report_meeting(
        db,
        current_user=_current_user(),
        now=NOW,
    )

    assert result.status is resolver.CellReportMeetingResolutionStatus.AMBIGUOUS
    assert result.candidate is None
    assert [item.reuniao_id for item in result.candidates] == [MEETING, MEETING_2]


def test_suggested_id_is_only_accepted_after_full_revalidation() -> None:
    db = _authorized_session([_meeting_row()])

    result = resolver.resolve_pending_cell_report_meeting(
        db,
        current_user=_current_user(),
        now=NOW,
        suggested_reuniao_id=str(MEETING),
    )

    assert result.status is resolver.CellReportMeetingResolutionStatus.CANDIDATE
    assert result.candidate is not None
    assert result.candidate.reuniao_id == MEETING

    other_db = _authorized_session(
        [_meeting_row(meeting_id=MEETING_2, meeting_tenant_id=OTHER_TENANT)]
    )
    rejected = resolver.resolve_pending_cell_report_meeting(
        other_db,
        current_user=_current_user(),
        now=NOW,
        suggested_reuniao_id=str(MEETING_2),
    )
    assert rejected.status is resolver.CellReportMeetingResolutionStatus.NONE


def test_invalid_actor_or_meeting_id_fails_closed() -> None:
    db = _authorized_session([])

    with pytest.raises(resolver.CellReportMeetingResolverError) as actor_error:
        resolver.resolve_pending_cell_report_meeting(
            db,
            current_user=_current_user(app_user_id="not-a-uuid"),
            now=NOW,
        )
    assert (
        actor_error.value.code
        is resolver.CellReportMeetingResolverErrorCode.INVALID_IDENTITY
    )
    assert not db.statements

    with pytest.raises(resolver.CellReportMeetingResolverError) as meeting_error:
        resolver.resolve_pending_cell_report_meeting(
            db,
            current_user=_current_user(),
            now=NOW,
            suggested_reuniao_id="not-a-uuid",
        )
    assert (
        meeting_error.value.code
        is resolver.CellReportMeetingResolverErrorCode.INVALID_MEETING_ID
    )


def test_inactive_or_ambiguous_authenticated_access_does_not_choose_an_actor() -> None:
    inactive = _authorized_session(
        [_meeting_row()],
        actor_rows=[(ACCESS, TENANT, ACTOR, "revogado")],
    )
    assert resolver.resolve_pending_cell_report_meeting(
        inactive,
        current_user=_current_user(),
        now=NOW,
    ).status is resolver.CellReportMeetingResolutionStatus.NONE

    duplicate_access = _authorized_session(
        [_meeting_row()],
        access_rows=[(ACCESS, TENANT, ACTOR), (MEETING_2, TENANT, ACTOR)],
    )
    assert resolver.resolve_pending_cell_report_meeting(
        duplicate_access,
        current_user=_current_user(),
        now=NOW,
    ).status is resolver.CellReportMeetingResolutionStatus.NONE
