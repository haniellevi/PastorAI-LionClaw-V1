"""Contrato de leitura leve e segura dos eventos no Painel de Hoje."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from app.db.models import Event
from app.deps import CurrentUser
from app.routers._common import PaginationParams
from app.routers.events import _get_event, list_events


class _Result:
    def __init__(self, *, rows=None, scalar=None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))

    def scalar_one(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _CaptureSession:
    def __init__(self, rows: list[Event], total: int) -> None:
        self.rows = rows
        self.total = total
        self.statements: list[object] = []

    def execute(self, statement):
        self.statements.append(statement)
        if "count(" in str(statement).lower():
            return _Result(scalar=self.total)
        return _Result(rows=self.rows)


def _user(*roles: str) -> CurrentUser:
    return CurrentUser(
        app_user_id="00000000-0000-0000-0000-0000000000a1",
        clerk_user_id="clerk-events",
        igreja_id="00000000-0000-0000-0000-000000000001",
        email="eventos@example.test",
        nome="Eventos",
        roles=frozenset(roles),
    )


def _event() -> Event:
    return Event(
        id=uuid.UUID("00000000-0000-0000-0000-0000000000e1"),
        igreja_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        titulo="Culto",
        data=dt.date(2026, 8, 12),
        hora="19:30",
        status="confirmado",
        origem="manual",
        recorrencia="pontual",
    )


def _sql(statement: object) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


def test_member_future_page_filters_drafts_before_pagination_and_count() -> None:
    session = _CaptureSession([_event()], total=17)

    result = list_events(
        pagination=PaginationParams(page=1, page_size=3),
        from_date=dt.date(2026, 8, 11),
        db=session,
        current_user=_user("membro"),
    )

    assert result.total == 17
    assert [item.titulo for item in result.items] == ["Culto"]
    assert len(session.statements) == 2

    page_sql, count_sql = map(_sql, session.statements)
    for sql in (page_sql, count_sql):
        assert "events.igreja_id" in sql
        assert "events.data >= '2026-08-11'" in sql
        assert "events.status IS NULL" in sql
        assert "events.status != 'a_confirmar'" in sql
    assert "ORDER BY events.data ASC NULLS LAST" in page_sql
    assert "events.hora ASC NULLS LAST" in page_sql
    assert "events.id ASC" in page_sql
    assert "LIMIT 3" in page_sql


def test_pastor_page_can_receive_confirmation_drafts() -> None:
    session = _CaptureSession([_event()], total=2)

    result = list_events(
        pagination=PaginationParams(page=1, page_size=6),
        from_date=dt.date(2026, 8, 11),
        db=session,
        current_user=_user("pastor"),
    )

    assert result.total == 2
    page_sql, count_sql = map(_sql, session.statements)
    assert "events.status != 'a_confirmar'" not in page_sql
    assert "events.status != 'a_confirmar'" not in count_sql


def test_admin_has_the_same_draft_visibility_as_confirm_endpoint() -> None:
    session = _CaptureSession([_event()], total=1)

    list_events(
        pagination=PaginationParams(page=1, page_size=6),
        from_date=dt.date(2026, 8, 11),
        db=session,
        current_user=_user("admin"),
    )

    page_sql, count_sql = map(_sql, session.statements)
    assert "events.status != 'a_confirmar'" not in page_sql
    assert "events.status != 'a_confirmar'" not in count_sql


def test_direct_event_read_uses_the_same_draft_visibility_gate() -> None:
    event = _event()
    member_session = _CaptureSession([event], total=1)
    pastor_session = _CaptureSession([event], total=1)

    assert _get_event(member_session, _user("membro"), str(event.id)) is event
    assert _get_event(pastor_session, _user("pastor"), str(event.id)) is event

    member_sql = _sql(member_session.statements[0])
    pastor_sql = _sql(pastor_session.statements[0])
    assert "events.id" in member_sql
    assert "events.igreja_id" in member_sql
    assert "events.status IS NULL" in member_sql
    assert "events.status != 'a_confirmar'" in member_sql
    assert "events.status != 'a_confirmar'" not in pastor_sql
