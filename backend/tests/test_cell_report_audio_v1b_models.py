"""ORM contract for V1b audio provenance and short-lived private content."""

from __future__ import annotations

from app.db.models import (
    CellReportAudioConsentEvent,
    CellReportAudioInput,
    CellReportAudioNotice,
    CellReportAudioReservation,
)


def test_audio_input_keeps_cleanup_anchor_after_live_message_or_conversation_delete() -> None:
    columns = set(CellReportAudioInput.__table__.columns.keys())
    foreign_keys = {
        constraint.name: tuple(element.parent.name for element in constraint.elements)
        for constraint in CellReportAudioInput.__table__.foreign_key_constraints
    }

    assert {
        "igreja_id",
        "conversation_id",
        "inbound_message_id",
        "provider_message_sha256",
        "live_pessoa_id",
        "live_conversation_id",
        "live_message_id",
        "storage_path",
        "content_sha256",
        "received_at",
        "expires_at",
        "state",
        "lease_token",
        "lease_until",
        "transcript_text",
        "purge_state",
        "content_purged_at",
    } <= columns
    assert foreign_keys["cell_report_audio_inputs_igreja_fkey"] == ("igreja_id",)
    assert foreign_keys["cell_report_audio_inputs_live_pessoa_fkey"] == (
        "igreja_id",
        "live_pessoa_id",
    )
    assert foreign_keys["cell_report_audio_inputs_live_conversation_fkey"] == (
        "igreja_id",
        "live_conversation_id",
    )
    assert foreign_keys["cell_report_audio_inputs_live_message_fkey"] == (
        "igreja_id",
        "live_conversation_id",
        "live_message_id",
    )
    assert CellReportAudioInput.__table__.c.transcript_text.type.length is None


def test_audio_consent_is_versioned_and_notice_anchored() -> None:
    notice_columns = set(CellReportAudioNotice.__table__.columns.keys())
    event_columns = set(CellReportAudioConsentEvent.__table__.columns.keys())
    event_constraints = {
        constraint.name for constraint in CellReportAudioConsentEvent.__table__.constraints
    }

    assert {"igreja_id", "pessoa_id", "notice_message_id", "version", "state", "delivered_at"} <= notice_columns
    assert {"igreja_id", "pessoa_id", "source_message_id", "notice_id", "command", "version", "occurred_at"} <= event_columns
    assert "cell_report_audio_consent_events_source_once_key" in event_constraints


def test_audio_reservation_binds_private_input_to_shared_report_budget() -> None:
    columns = set(CellReportAudioReservation.__table__.columns.keys())
    unique_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in CellReportAudioReservation.__table__.constraints
        if constraint.name
    }
    foreign_keys = {
        constraint.name: tuple(element.parent.name for element in constraint.elements)
        for constraint in CellReportAudioReservation.__table__.foreign_key_constraints
    }

    assert {
        "igreja_id",
        "audio_input_id",
        "reuniao_id",
        "budget_id",
        "audio_number",
        "estimated_microusd",
        "actual_microusd",
        "state",
    } <= columns
    assert foreign_keys["cell_report_audio_reservations_tenant_input_fkey"] == (
        "igreja_id",
        "audio_input_id",
    )
    assert foreign_keys["cell_report_audio_reservations_tenant_meeting_fkey"] == (
        "igreja_id",
        "reuniao_id",
    )
    assert unique_constraints[
        "cell_report_audio_reservations_meeting_audio_number_key"
    ] == ("igreja_id", "reuniao_id", "audio_number")
