from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.domain.cell_report_v1a import parse_v1a_cell_report_text
from app.domain.cell_report_snapshot import validate_cell_report_snapshot_v2
from app.services import cell_report_finalizer as finalizer


TENANT = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
MEETING = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
ACTOR = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
PROPOSAL = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
NOW = dt.datetime(2026, 9, 27, 15, tzinfo=dt.timezone.utc)


class _Session:
    def __init__(self) -> None:
        self.flushes = 0
        self.commits = 0

    def flush(self) -> None:
        self.flushes += 1

    def commit(self) -> None:
        self.commits += 1


def test_v1a_finalizer_materializes_only_aggregates_without_committing(monkeypatch) -> None:
    meeting = SimpleNamespace(
        id=MEETING,
        igreja_id=TENANT,
        data=dt.date(2026, 9, 26),
        hora="19:00",
        status="realizada",
        relatorio_status="pendente",
        relatorio_enviado_em=None,
        relatorio_enviado_por=None,
        relatorio_snapshot=None,
        oferta_valor=None,
        observacoes="não preservar",
        updated_at=None,
    )
    monkeypatch.setattr(
        finalizer,
        "_lock_owned_meeting",
        lambda *_args, **_kwargs: meeting,
    )
    monkeypatch.setattr(finalizer, "require_tenant_scope", lambda *_args, **_kwargs: None)
    session = _Session()

    result = finalizer.finalize_v1a_cell_report(
        session,
        igreja_id=TENANT,
        reuniao_id=MEETING,
        actor_pessoa_id=ACTOR,
        candidate=parse_v1a_cell_report_text(
            "8 presentes; 2 visitantes; 1 decisão; oferta: 42,50"
        ),
        proposal_id=PROPOSAL,
        draft_payload_sha256="a" * 64,
        now=NOW,
    )

    assert result.meeting_id == MEETING
    assert result.snapshot["totals"] == {
        "presentes": 8,
        "visitantes": 2,
        "decisoes": 1,
    }
    assert result.snapshot["oferta_valor"] == "42.50"
    assert result.snapshot["observacoes"] is None
    assert result.snapshot["presencas"] == []
    assert result.snapshot["visitantes"] == []
    assert result.snapshot["records"] == []
    assert meeting.relatorio_status == "enviado"
    assert meeting.relatorio_enviado_por == ACTOR
    assert meeting.oferta_valor == Decimal("42.50")
    assert meeting.observacoes is None
    assert session.flushes == 1
    assert session.commits == 0


@pytest.mark.parametrize(
    ("meeting_date", "meeting_time"),
    [
        (dt.date(2026, 9, 26), "19:00"),
        (NOW.date(), None),
        (NOW.date(), "23:59"),
    ],
)
def test_human_finalizer_uses_the_same_terminal_boundary_without_commit(
    meeting_date: dt.date,
    meeting_time: str | None,
) -> None:
    meeting = SimpleNamespace(
        id=MEETING,
        igreja_id=TENANT,
        data=meeting_date,
        hora=meeting_time,
        status="realizada",
        relatorio_status="pendente",
        relatorio_enviado_em=None,
        relatorio_enviado_por=None,
        relatorio_snapshot=None,
        oferta_valor=None,
        observacoes="nota do painel",
        updated_at=None,
    )
    session = _Session()
    human_snapshot = {
        "meeting_id": str(MEETING),
        "presencas": [{"pessoa_id": str(ACTOR), "estado": "compareceu"}],
        "visitantes": [],
        "records": [],
    }

    result = finalizer.finalize_human_cell_report(
        session,
        igreja_id=TENANT,
        meeting=meeting,
        actor_pessoa_id=ACTOR,
        snapshot=human_snapshot,
        oferta_valor=Decimal("42.50"),
        observacoes="nota do painel",
        now=NOW,
    )

    assert result.meeting_id == MEETING
    assert result.snapshot is not human_snapshot
    assert result.snapshot["relatorio_status"] == "enviado"
    assert meeting.relatorio_status == "enviado"
    assert meeting.relatorio_enviado_por == ACTOR
    assert meeting.oferta_valor == Decimal("42.50")
    assert meeting.observacoes == "nota do painel"
    assert session.flushes == 1
    assert session.commits == 0


def test_v1a_finalizer_keeps_the_closed_v2_snapshot_unchanged(monkeypatch) -> None:
    meeting = SimpleNamespace(
        id=MEETING,
        igreja_id=TENANT,
        data=dt.date(2026, 9, 26),
        hora="19:00",
        status="realizada",
        relatorio_status="pendente",
        relatorio_enviado_em=None,
        relatorio_enviado_por=None,
        relatorio_snapshot=None,
        oferta_valor=None,
        observacoes=None,
        updated_at=None,
    )
    monkeypatch.setattr(finalizer, "_lock_owned_meeting", lambda *_args, **_kwargs: meeting)
    monkeypatch.setattr(finalizer, "require_tenant_scope", lambda *_args, **_kwargs: None)
    session = _Session()

    result = finalizer.finalize_v1a_cell_report(
        session,
        igreja_id=TENANT,
        reuniao_id=MEETING,
        actor_pessoa_id=ACTOR,
        candidate=parse_v1a_cell_report_text(
            "8 presentes; 2 visitantes; 1 decisão; oferta: 42,50"
        ),
        proposal_id=PROPOSAL,
        draft_payload_sha256="a" * 64,
        now=NOW,
    )

    assert validate_cell_report_snapshot_v2(result.snapshot).totals.presentes == 8


def test_v1a_finalizer_refuses_duplicate_or_incomplete_report(monkeypatch) -> None:
    meeting = SimpleNamespace(
        id=MEETING,
        igreja_id=TENANT,
        data=dt.date(2026, 9, 26),
        hora="19:00",
        status="realizada",
        relatorio_status="enviado",
        relatorio_enviado_em=NOW,
        relatorio_enviado_por=ACTOR,
        relatorio_snapshot={},
        updated_at=NOW,
    )
    monkeypatch.setattr(finalizer, "_lock_owned_meeting", lambda *_args, **_kwargs: meeting)
    monkeypatch.setattr(finalizer, "require_tenant_scope", lambda *_args, **_kwargs: None)

    with pytest.raises(finalizer.CellReportFinalizerError):
        finalizer.finalize_v1a_cell_report(
            _Session(),
            igreja_id=TENANT,
            reuniao_id=MEETING,
            actor_pessoa_id=ACTOR,
            candidate=parse_v1a_cell_report_text("8 presentes"),
            proposal_id=PROPOSAL,
            draft_payload_sha256="a" * 64,
            now=NOW,
        )


@pytest.mark.parametrize(
    ("meeting_status", "meeting_date", "meeting_time"),
    [
        ("cancelada", dt.date(2026, 9, 26), "19:00"),
        ("planejada", dt.date(2026, 9, 28), "19:00"),
        ("realizada", NOW.date(), None),
    ],
)
def test_v1a_finalizer_refuses_cancelled_future_or_timeless_meeting_without_mutation(
    monkeypatch,
    meeting_status: str,
    meeting_date: dt.date,
    meeting_time: str,
) -> None:
    meeting = SimpleNamespace(
        id=MEETING,
        igreja_id=TENANT,
        data=meeting_date,
        hora=meeting_time,
        status=meeting_status,
        relatorio_status="pendente",
        relatorio_enviado_em=None,
        relatorio_enviado_por=None,
        relatorio_snapshot=None,
        oferta_valor=None,
        observacoes=None,
        updated_at=None,
    )
    monkeypatch.setattr(finalizer, "_lock_owned_meeting", lambda *_args, **_kwargs: meeting)
    monkeypatch.setattr(finalizer, "require_tenant_scope", lambda *_args, **_kwargs: None)
    session = _Session()

    with pytest.raises(finalizer.CellReportFinalizerError):
        finalizer.finalize_v1a_cell_report(
            session,
            igreja_id=TENANT,
            reuniao_id=MEETING,
            actor_pessoa_id=ACTOR,
            candidate=parse_v1a_cell_report_text(
                "8 presentes; 2 visitantes; 1 decisão; oferta: 42,50"
            ),
            proposal_id=PROPOSAL,
            draft_payload_sha256="a" * 64,
            now=NOW,
        )

    assert meeting.relatorio_status == "pendente"
    assert meeting.relatorio_enviado_em is None
    assert meeting.relatorio_enviado_por is None
    assert meeting.relatorio_snapshot is None
    assert session.flushes == 0
    assert session.commits == 0
