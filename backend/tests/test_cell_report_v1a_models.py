from __future__ import annotations

from app.db.models import (
    AgentActionProposal,
    CellReportAiDailyBudget,
    CellReportAiReservation,
    CellReportDraft,
    CellReportReminder,
    CellReportReminderPreference,
    CelulaReuniao,
)


def test_v1a_models_keep_draft_content_separate_from_s3_delivery_authority() -> None:
    draft_columns = set(CellReportDraft.__table__.columns.keys())
    reminder_columns = set(CellReportReminder.__table__.columns.keys())
    preference_columns = set(CellReportReminderPreference.__table__.columns.keys())

    assert {
        "igreja_id",
        "conversation_id",
        "reuniao_id",
        "actor_pessoa_id",
        "source_message_id",
        "candidate_json",
        "candidate_sha256",
        "revision",
        "state",
        "expires_at",
        "content_purged_at",
    } <= draft_columns
    assert {"igreja_id", "reuniao_id", "leader_pessoa_id", "state", "due_at"} <= reminder_columns
    assert {"igreja_id", "pessoa_id", "disabled_at"} <= preference_columns
    assert CellReportDraft.__table__.c.candidate_json.type.none_as_null is True


def test_v1a_budget_is_versioned_and_reservation_is_bound_to_one_draft_call() -> None:
    budget_columns = set(CellReportAiDailyBudget.__table__.columns.keys())
    reservation_columns = set(CellReportAiReservation.__table__.columns.keys())
    constraints = {constraint.name for constraint in CellReportAiReservation.__table__.constraints}

    assert {"igreja_id", "budget_day", "cost_version", "reserved_microusd", "settled_microusd"} <= budget_columns
    assert {"igreja_id", "draft_id", "call_number", "budget_day", "cost_version", "state", "estimated_microusd", "actual_microusd"} <= reservation_columns
    assert "cell_report_ai_reservations_draft_call_once_key" in constraints


def test_v1a_action_is_closed_to_meeting_target_in_orm_contract() -> None:
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in AgentActionProposal.__table__.constraints
        if getattr(constraint, "sqltext", None) is not None and constraint.name
    }

    assert "enviar_relatorio_celula" in checks["agent_action_proposals_action_closed"]
    assert "reuniao" in checks["agent_action_proposals_target_kind_closed"]


def test_v1a_meeting_references_are_scoped_by_tenant_in_orm_contract() -> None:
    meeting_constraints = {constraint.name for constraint in CelulaReuniao.__table__.constraints}
    draft_foreign_keys = {
        constraint.name: tuple(element.parent.name for element in constraint.elements)
        for constraint in CellReportDraft.__table__.foreign_key_constraints
    }
    reminder_foreign_keys = {
        constraint.name: tuple(element.parent.name for element in constraint.elements)
        for constraint in CellReportReminder.__table__.foreign_key_constraints
    }

    assert "celula_reuniao_igreja_id_id_key" in meeting_constraints
    assert draft_foreign_keys["cell_report_drafts_reuniao_fkey"] == (
        "igreja_id",
        "reuniao_id",
    )
    assert reminder_foreign_keys["cell_report_reminders_reuniao_fkey"] == (
        "igreja_id",
        "reuniao_id",
    )
