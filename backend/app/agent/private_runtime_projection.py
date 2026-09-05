"""Read-only adapter for the private runtime turn-context projection.

The dedicated ``agent_runtime`` role is intentionally unable to query the
application's ``public`` ORM models.  The only domain read admitted by this
slice is the reviewed SQL function
``agent_private.load_turn_context(uuid)``.  This adapter keeps the database
boundary narrow and turns the function's six-column result into an immutable,
server-owned value before the agent runtime can inspect it.

The tenant argument is derived by the server from the persisted inbound
message.  It is not supplied by a model and is checked against both the
already-proven dedicated-session marker and the returned row.  A missing row
is deliberately indistinguishable from a cross-tenant/non-visible row.  No
ORM model, primary ``DATABASE_URL`` fallback, writer, or commit belongs here.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.agent_runtime_session import AGENT_RUNTIME_TENANT_KEY
from app.domain.conversations import VALID_ESTADOS


PRIVATE_RUNTIME_PROJECTION_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "igreja_id",
        "conversation_id",
        "pessoa_id",
        "conversation_state",
        "pessoa_optout",
        "pessoa_sem_interesse",
    }
)

# Keep the function call parameterized.  ``select *`` is intentional: if a
# future migration changes the function's returned table, strict shape
# validation below must reject the changed contract instead of silently
# discarding a column.
PRIVATE_RUNTIME_PROJECTION_SQL = text(
    "select * from agent_private.load_turn_context(:p_conversation_id)"
)


class PrivateRuntimeProjectionError(RuntimeError):
    """Base class for static, non-sensitive projection failures."""


class PrivateRuntimeProjectionUnavailable(PrivateRuntimeProjectionError):
    """The function/database boundary is absent or could not be read."""

    def __init__(self) -> None:
        # Never include the driver exception: it may contain a DSN, hostname,
        # role, SQL, or another private deployment detail.
        super().__init__("private runtime projection unavailable")


class PrivateRuntimeProjectionValidationError(PrivateRuntimeProjectionError):
    """The function returned a shape or value outside the closed contract."""

    def __init__(self) -> None:
        super().__init__("private runtime projection validation failed")


class PrivateRuntimeProjectionScopeError(PrivateRuntimeProjectionError):
    """The adapter was called without the already-proven dedicated scope."""

    def __init__(self) -> None:
        super().__init__("private runtime projection requires dedicated scope")


@dataclass(frozen=True, slots=True, repr=False)
class PrivateRuntimeProjection:
    """Immutable six-field turn context returned by the private projection.

    IDs are deliberately accepted only as non-nil ``uuid.UUID`` instances.
    The PostgreSQL function returns UUID columns, and accepting strings here
    would make it too easy for a caller-controlled value to cross this
    authority boundary.  The two boolean fields are separate gates: a global
    opt-out and the existing ``sem_interesse`` suppression are never inferred
    from each other.
    """

    igreja_id: uuid.UUID
    conversation_id: uuid.UUID
    pessoa_id: uuid.UUID
    conversation_state: str
    pessoa_optout: bool
    pessoa_sem_interesse: bool

    def __post_init__(self) -> None:
        for value in (
            self.igreja_id,
            self.conversation_id,
            self.pessoa_id,
        ):
            if type(value) is not uuid.UUID or value.int == 0:
                raise PrivateRuntimeProjectionValidationError()
        if (
            type(self.conversation_state) is not str
            or not self.conversation_state
            or self.conversation_state != self.conversation_state.strip()
            or self.conversation_state not in VALID_ESTADOS
        ):
            raise PrivateRuntimeProjectionValidationError()
        if type(self.pessoa_optout) is not bool:  # noqa: E721
            raise PrivateRuntimeProjectionValidationError()
        if type(self.pessoa_sem_interesse) is not bool:  # noqa: E721
            raise PrivateRuntimeProjectionValidationError()

    def __repr__(self) -> str:
        # Do not make raw tenant/person/conversation IDs appear in routine
        # debug logs.  The object remains available to the trusted server code.
        return "PrivateRuntimeProjection(<redacted>)"

    @property
    def automation_suppressed(self) -> bool:
        """Return the two server-resolved suppression gates as one predicate."""
        return self.pessoa_optout or self.pessoa_sem_interesse


def _require_uuid(value: object) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        raise PrivateRuntimeProjectionValidationError()
    return value


def _require_dedicated_scope(session: Session, tenant_id: uuid.UUID) -> None:
    """Require the marker installed only after the dedicated SQL probe.

    ``runtime.py`` performs the authoritative role/tenant re-probe immediately
    before this adapter.  Requiring the marker here prevents direct callers
    from accidentally using the primary application session, without adding a
    second SQL call to the one-call projection contract.
    """

    info = getattr(session, "info", None)
    if not isinstance(info, Mapping):
        raise PrivateRuntimeProjectionScopeError()
    if info.get(AGENT_RUNTIME_TENANT_KEY) != str(tenant_id):
        raise PrivateRuntimeProjectionScopeError()


def _row_mapping(row: object) -> dict[str, Any]:
    """Extract a mapping without accepting positional/ambiguous row shapes."""

    try:
        if isinstance(row, Mapping):
            mapping = dict(row)
        else:
            row_mapping = getattr(row, "_mapping", None)
            if not isinstance(row_mapping, Mapping):
                raise PrivateRuntimeProjectionValidationError()
            mapping = dict(row_mapping)
    except PrivateRuntimeProjectionError:
        raise
    except Exception:
        raise PrivateRuntimeProjectionValidationError() from None
    if any(type(key) is not str for key in mapping):  # noqa: E721
        raise PrivateRuntimeProjectionValidationError()
    if frozenset(mapping) != PRIVATE_RUNTIME_PROJECTION_COLUMNS:
        raise PrivateRuntimeProjectionValidationError()
    return mapping


def _projection_from_row(
    row: object,
    *,
    expected_igreja_id: uuid.UUID,
    expected_conversation_id: uuid.UUID,
) -> PrivateRuntimeProjection:
    values = _row_mapping(row)
    projection = PrivateRuntimeProjection(
        igreja_id=values["igreja_id"],
        conversation_id=values["conversation_id"],
        pessoa_id=values["pessoa_id"],
        conversation_state=values["conversation_state"],
        pessoa_optout=values["pessoa_optout"],
        pessoa_sem_interesse=values["pessoa_sem_interesse"],
    )
    if projection.igreja_id != expected_igreja_id:
        raise PrivateRuntimeProjectionValidationError()
    if projection.conversation_id != expected_conversation_id:
        raise PrivateRuntimeProjectionValidationError()
    return projection


class PrivateRuntimeProjectionStore:
    """One-session, read-only store for the six-field private projection."""

    __slots__ = ("_session",)

    def __init__(self, session: Session) -> None:
        self._session = session

    def load_turn_context(
        self,
        igreja_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> PrivateRuntimeProjection | None:
        """Load one trusted turn context, or ``None`` when it is not visible.

        The session must already be in the transaction established and proved
        by ``scope_agent_runtime_session``.  Exactly one SQL ``execute`` is
        performed on the private function; no ORM query or fallback is
        available from this class.
        """

        tenant_id = _require_uuid(igreja_id)
        requested_conversation_id = _require_uuid(conversation_id)
        _require_dedicated_scope(self._session, tenant_id)

        result: Any | None = None
        try:
            result = self._session.execute(
                PRIVATE_RUNTIME_PROJECTION_SQL,
                {"p_conversation_id": requested_conversation_id},
            )
            rows = list(result.mappings().fetchmany(2))
        except PrivateRuntimeProjectionError:
            raise
        except Exception:
            # Function absent, denied, connection loss, or any other driver
            # error has one sanitized runtime outcome.  No cause is attached.
            raise PrivateRuntimeProjectionUnavailable() from None
        finally:
            # A future function regression must not leave an unbounded result
            # cursor open after the two-row cardinality probe.
            if result is not None:
                try:
                    close = getattr(result, "close", None)
                    if callable(close):
                        close()
                except Exception:
                    pass

        if not rows:
            # The SQL function intentionally hides absent and cross-tenant
            # conversations alike.
            return None
        if len(rows) != 1:
            raise PrivateRuntimeProjectionValidationError()
        return _projection_from_row(
            rows[0],
            expected_igreja_id=tenant_id,
            expected_conversation_id=requested_conversation_id,
        )


def load_private_runtime_projection(
    session: Session,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> PrivateRuntimeProjection | None:
    """Functional entry point used by the runtime boundary."""

    return PrivateRuntimeProjectionStore(session).load_turn_context(
        igreja_id,
        conversation_id,
    )


__all__ = [
    "PRIVATE_RUNTIME_PROJECTION_COLUMNS",
    "PRIVATE_RUNTIME_PROJECTION_SQL",
    "PrivateRuntimeProjection",
    "PrivateRuntimeProjectionError",
    "PrivateRuntimeProjectionScopeError",
    "PrivateRuntimeProjectionStore",
    "PrivateRuntimeProjectionUnavailable",
    "PrivateRuntimeProjectionValidationError",
    "load_private_runtime_projection",
]
