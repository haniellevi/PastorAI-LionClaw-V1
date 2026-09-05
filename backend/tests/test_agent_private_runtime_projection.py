"""Offline tests for the private runtime projection read boundary."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import uuid

import pytest

from app.agent.private_runtime_projection import (
    PRIVATE_RUNTIME_PROJECTION_COLUMNS,
    PrivateRuntimeProjection,
    PrivateRuntimeProjectionScopeError,
    PrivateRuntimeProjectionStore,
    PrivateRuntimeProjectionUnavailable,
    PrivateRuntimeProjectionValidationError,
)
from app.db.agent_runtime_session import AGENT_RUNTIME_TENANT_KEY


TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_TENANT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
CONVERSATION_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_CONVERSATION_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
PERSON_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


class _MappingsResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows
        self.close_calls = 0

    def mappings(self) -> _MappingsResult:
        return self

    def fetchmany(self, size: int) -> list[object]:
        return list(self._rows[:size])

    def close(self) -> None:
        self.close_calls += 1


class _FakeSession:
    def __init__(
        self,
        rows: list[object] | None = None,
        *,
        error: Exception | None = None,
        tenant_id: uuid.UUID = TENANT_ID,
    ) -> None:
        self.info = {AGENT_RUNTIME_TENANT_KEY: str(tenant_id)}
        self.rows = rows if rows is not None else [_row()]
        self.error = error
        self.execute_calls: list[tuple[object, dict[str, object]]] = []
        self.write_calls: list[str] = []
        self.result: _MappingsResult | None = None

    def execute(self, statement, params=None) -> _MappingsResult:
        self.execute_calls.append((statement, params))
        if self.error is not None:
            raise self.error
        self.result = _MappingsResult(self.rows)
        return self.result

    def add(self, *_args, **_kwargs) -> None:
        self.write_calls.append("add")

    def commit(self) -> None:
        self.write_calls.append("commit")


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "igreja_id": TENANT_ID,
        "conversation_id": CONVERSATION_ID,
        "pessoa_id": PERSON_ID,
        "conversation_state": "ia",
        "pessoa_optout": False,
        "pessoa_sem_interesse": False,
    }
    row.update(overrides)
    return row


def _load(session: _FakeSession) -> PrivateRuntimeProjection | None:
    return PrivateRuntimeProjectionStore(session).load_turn_context(
        TENANT_ID,
        CONVERSATION_ID,
    )


def test_valid_projection_is_immutable_and_preserves_both_gates() -> None:
    session = _FakeSession(
        rows=[
            _row(
                pessoa_optout=True,
                pessoa_sem_interesse=False,
            )
        ]
    )

    projection = _load(session)

    assert isinstance(projection, PrivateRuntimeProjection)
    assert projection.igreja_id == TENANT_ID
    assert projection.conversation_id == CONVERSATION_ID
    assert projection.pessoa_id == PERSON_ID
    assert projection.conversation_state == "ia"
    assert projection.pessoa_optout is True
    assert projection.pessoa_sem_interesse is False
    assert projection.automation_suppressed is True
    assert repr(projection) == "PrivateRuntimeProjection(<redacted>)"
    assert session.result is not None
    assert session.result.close_calls == 1
    with pytest.raises(FrozenInstanceError):
        projection.pessoa_optout = False  # type: ignore[misc]


def test_projection_calls_only_parameterized_private_function_once() -> None:
    session = _FakeSession()

    projection = _load(session)

    assert projection is not None
    assert len(session.execute_calls) == 1
    statement, params = session.execute_calls[0]
    sql = str(statement).lower()
    assert "agent_private.load_turn_context" in sql
    assert "public" not in sql
    assert "select *" in sql
    assert params == {"p_conversation_id": CONVERSATION_ID}
    assert session.write_calls == []
    assert session.result is not None
    assert session.result.close_calls == 1


def test_empty_projection_is_absent_and_does_not_fallback() -> None:
    session = _FakeSession(rows=[])

    assert _load(session) is None
    assert len(session.execute_calls) == 1
    assert session.write_calls == []
    assert session.result is not None
    assert session.result.close_calls == 1


def test_database_or_absent_function_error_is_sanitized() -> None:
    secret = "postgresql://owner:secret@private-db.invalid/app"
    session = _FakeSession(error=RuntimeError(secret))

    with pytest.raises(PrivateRuntimeProjectionUnavailable) as raised:
        _load(session)

    assert str(raised.value) == "private runtime projection unavailable"
    assert secret not in str(raised.value)
    assert raised.value.__cause__ is None
    assert len(session.execute_calls) == 1
    assert session.write_calls == []
    assert session.result is None


@pytest.mark.parametrize(
    "session",
    [
        _FakeSession(tenant_id=OTHER_TENANT_ID),
        _FakeSession(tenant_id=uuid.UUID(int=0)),
    ],
)
def test_store_requires_the_server_pinned_dedicated_tenant_scope(
    session: _FakeSession,
) -> None:
    with pytest.raises(PrivateRuntimeProjectionScopeError):
        _load(session)

    assert session.execute_calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"igreja_id": OTHER_TENANT_ID},
        {"conversation_id": OTHER_CONVERSATION_ID},
        {"pessoa_id": None},
        {"pessoa_id": str(PERSON_ID)},
    ],
)
def test_tenant_conversation_person_identity_mismatch_is_rejected(
    overrides: dict[str, object],
) -> None:
    session = _FakeSession(rows=[_row(**overrides)])

    with pytest.raises(PrivateRuntimeProjectionValidationError):
        _load(session)

    assert len(session.execute_calls) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"conversation_state": ""},
        {"conversation_state": " ia"},
        {"conversation_state": "desconhecido"},
        {"conversation_state": uuid.uuid4()},
        {"pessoa_optout": 1},
        {"pessoa_optout": None},
        {"pessoa_sem_interesse": 0},
        {"pessoa_sem_interesse": None},
    ],
)
def test_malformed_values_are_rejected_strictly(
    overrides: dict[str, object],
) -> None:
    session = _FakeSession(rows=[_row(**overrides)])

    with pytest.raises(PrivateRuntimeProjectionValidationError):
        _load(session)


@pytest.mark.parametrize(
    "row",
    [
        {**_row(), "unexpected": True},
        {key: value for key, value in _row().items() if key != "pessoa_id"},
        {1: "non-string column"},
    ],
)
def test_rows_must_match_the_exact_six_column_shape(row: dict[object, object]) -> None:
    session = _FakeSession(rows=[row])

    with pytest.raises(PrivateRuntimeProjectionValidationError):
        _load(session)

    assert len(session.execute_calls) == 1


def test_multiple_rows_are_rejected_instead_of_choosing_an_ambiguous_context() -> None:
    session = _FakeSession(rows=[_row(), _row()])

    with pytest.raises(PrivateRuntimeProjectionValidationError):
        _load(session)

    assert len(session.execute_calls) == 1


@pytest.mark.parametrize(
    ("pessoa_optout", "pessoa_sem_interesse", "suppressed"),
    [
        (False, False, False),
        (True, False, True),
        (False, True, True),
        (True, True, True),
    ],
)
def test_false_and_true_gate_invariants_are_independent(
    pessoa_optout: bool,
    pessoa_sem_interesse: bool,
    suppressed: bool,
) -> None:
    session = _FakeSession(
        rows=[
            _row(
                pessoa_optout=pessoa_optout,
                pessoa_sem_interesse=pessoa_sem_interesse,
            )
        ]
    )

    projection = _load(session)

    assert projection is not None
    assert projection.pessoa_optout is pessoa_optout
    assert projection.pessoa_sem_interesse is pessoa_sem_interesse
    assert projection.automation_suppressed is suppressed


def test_contract_columns_are_closed_and_exposed_for_callers() -> None:
    assert PRIVATE_RUNTIME_PROJECTION_COLUMNS == frozenset(
        {
            "igreja_id",
            "conversation_id",
            "pessoa_id",
            "conversation_state",
            "pessoa_optout",
            "pessoa_sem_interesse",
        }
    )
