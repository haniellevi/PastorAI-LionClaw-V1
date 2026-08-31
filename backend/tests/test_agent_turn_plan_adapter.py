from __future__ import annotations

import ast
import json
import uuid
from copy import deepcopy
from decimal import Inexact, ROUND_CEILING, ROUND_DOWN, ROUND_UP, Rounded
from decimal import localcontext
from pathlib import Path

import pytest

import app.agent.turn_plan_adapter as turn_plan_adapter_module
from app.agent.turn_execution import (
    AgentEffectReceiptOutcome,
    build_agent_effect_receipt,
)
from app.agent.turn_identity import (
    MAX_CANONICAL_INTEGER,
    AgentEffectKind,
    build_agent_turn_identity,
)
from app.agent.turn_plan_adapter import (
    AGENT_TURN_OUTPUT_SCHEMA_VERSION,
    MAX_AGENT_TURN_FIELD_BYTES,
    MAX_AGENT_TURN_OUTPUT_EVENTS,
    MAX_AGENT_TURN_RECEIPTS,
    MAX_AGENT_TURN_RESPONSE_BYTES,
    TURN_PLAN_ADAPTER_VERSION,
    AgentTurnOutputEventName,
    AgentTurnOutputRoute,
    AgentTurnPlanAdapterError,
    AgentTurnPlanAdapterErrorCode,
    AgentTurnPlanAdapterStatus,
    build_agent_turn_output_v1,
    project_agent_turn_execution_plan,
    reconcile_agent_turn_output_replay,
    validate_agent_turn_output_v1,
)
from app.domain.cell_report_workflow import (
    MAX_REPORT_COUNT,
    MAX_REPORT_OFFERING_CENTS,
)


IGREJA_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
CONVERSATION_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
INBOUND_MESSAGE_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")


def _identity(
    *,
    igreja_id: uuid.UUID = IGREJA_ID,
    conversation_id: uuid.UUID = CONVERSATION_ID,
    inbound_message_id: uuid.UUID = INBOUND_MESSAGE_ID,
    provider_message_id: str = "wamid.fixed-001",
):
    return build_agent_turn_identity(
        igreja_id=igreja_id,
        conversation_id=conversation_id,
        inbound_message_id=inbound_message_id,
        provider_message_id=provider_message_id,
    )


def _intake_event(update: dict | None = None) -> dict:
    return {"evento": "intake", "payload": {"update": update or {}}}


def _output(
    *,
    route: str = "onboarding",
    response: str | None = "Como posso ajudar?",
    route_event: dict | None = None,
    intake_update: dict | None = None,
    intake_event_update: dict | None = None,
    apply_optout: bool = False,
    apply_consent_version: str | None = None,
    reverse_events: bool = False,
) -> dict:
    update = deepcopy(intake_update or {})
    event_update = deepcopy(intake_event_update)
    if event_update is None:
        event_update = {
            key: value
            for key, value in update.items()
            if key in {"origem", "set_primeiro_contato"}
        }
    if route_event is None:
        route_event = {
            "evento": "onboarding",
            "payload": {"classificacao": "novo_contato"},
        }
    events = [_intake_event(event_update), deepcopy(route_event)]
    if reverse_events:
        events.reverse()
    return {
        "route": route,
        "response": response,
        "turn_effects": {
            "events": events,
            "tool_calls": [],
            "apply_optout": apply_optout,
            "apply_consent_version": apply_consent_version,
            "intake_update": update,
        },
    }


def _report_output(
    *,
    oferta: object = 50.25,
    reverse_events: bool = False,
) -> dict:
    update = {"origem": "whatsapp", "set_primeiro_contato": True}
    return _output(
        route="report_capture",
        response="Relatório recebido.",
        route_event={
            "evento": "report_captured",
            "payload": {
                "relatorio": {
                    "presentes": 12,
                    "visitantes": 2,
                    "decisoes": 1,
                    "oferta": oferta,
                }
            },
        },
        intake_update=update,
        reverse_events=reverse_events,
    )


def _handoff_output() -> dict:
    return _output(
        route="handoff",
        response=None,
        route_event={"evento": "handoff_suspended", "payload": {}},
    )


def _optout_output() -> dict:
    return _output(
        route="optout",
        response="Você não receberá mais comunicados.",
        route_event={"evento": "optout", "payload": {}},
        apply_optout=True,
    )


def _consent_output(*, accepted: bool) -> dict:
    version = "termo-2026-08" if accepted else None
    event = "consent_accepted" if accepted else "consent_presented"
    return _output(
        route="consent",
        response="Consentimento tratado.",
        route_event={
            "evento": event,
            "payload": {"termoVersao": "termo-2026-08"},
        },
        apply_consent_version=version,
    )


def _receipts(identity, plan, outcome=AgentEffectReceiptOutcome.COMMITTED):
    return [
        build_agent_effect_receipt(
            identity,
            plan,
            intent,
            outcome=outcome,
        )
        for intent in plan.effect_intents
    ]


def _assert_error(code, func, *args, **kwargs):
    with pytest.raises(AgentTurnPlanAdapterError) as caught:
        func(*args, **kwargs)
    assert caught.value.code is code
    assert str(caught.value) == f"agent turn plan adapter rejected: {code.value}"
    assert repr(caught.value) == (
        f"AgentTurnPlanAdapterError(code={code.value!r})"
    )


@pytest.mark.parametrize(
    "raw, expected_route, response_present",
    [
        (_output(), AgentTurnOutputRoute.ONBOARDING, True),
        (_handoff_output(), AgentTurnOutputRoute.HANDOFF, False),
        (_optout_output(), AgentTurnOutputRoute.OPTOUT, True),
        (_consent_output(accepted=False), AgentTurnOutputRoute.CONSENT, True),
        (_consent_output(accepted=True), AgentTurnOutputRoute.CONSENT, True),
        (_report_output(), AgentTurnOutputRoute.REPORT_CAPTURE, True),
    ],
)
def test_output_v1_accepts_only_current_closed_routes(
    raw, expected_route, response_present
):
    output = build_agent_turn_output_v1(raw)
    assert output.schema_version == AGENT_TURN_OUTPUT_SCHEMA_VERSION == "v1"
    assert TURN_PLAN_ADAPTER_VERSION == "v1"
    assert output.route is expected_route
    assert (output.response is not None) is response_present
    assert validate_agent_turn_output_v1(output) is output
    assert "wamid" not in repr(output)
    assert "Relatório recebido" not in repr(output)


def test_onboarding_csim_keeps_intake_event_and_final_update_distinct():
    raw = _output(
        intake_update={
            "origem": "whatsapp",
            "set_primeiro_contato": True,
            "sem_interesse": True,
            "sem_interesse_motivo": "comercial/empresa",
        },
        route_event={
            "evento": "onboarding",
            "payload": {"classificacao": "csim"},
        },
    )
    output = build_agent_turn_output_v1(raw)
    intake_payload = json.loads(output.events[0].payload_json)
    final_update = json.loads(output.intake_update_json)
    assert intake_payload == {
        "update": {
            "origem": "whatsapp",
            "set_primeiro_contato": True,
        }
    }
    assert final_update["sem_interesse"] is True
    assert final_update["sem_interesse_motivo"] == "comercial/empresa"


@pytest.mark.parametrize(
    "raw",
    [
        _handoff_output(),
        _optout_output(),
        _consent_output(accepted=False),
        _consent_output(accepted=True),
        _report_output(),
    ],
)
def test_csim_intake_fields_are_forbidden_outside_onboarding(raw):
    candidate = deepcopy(raw)
    candidate["turn_effects"]["intake_update"].update(
        {
            "sem_interesse": True,
            "sem_interesse_motivo": "forged",
        }
    )
    _assert_error(
        AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH,
        build_agent_turn_output_v1,
        candidate,
    )


@pytest.mark.parametrize(
    "classification",
    ["novo_contato", "visitante", "decidido"],
)
def test_non_csim_onboarding_forbids_csim_intake_fields(classification):
    raw = _output(
        intake_update={
            "sem_interesse": True,
            "sem_interesse_motivo": "forged",
        },
        route_event={
            "evento": "onboarding",
            "payload": {"classificacao": classification},
        },
    )
    _assert_error(
        AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH,
        build_agent_turn_output_v1,
        raw,
    )


def test_csim_onboarding_requires_matching_csim_intake_fields():
    raw = _output(
        route_event={
            "evento": "onboarding",
            "payload": {"classificacao": "csim"},
        },
    )
    _assert_error(
        AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH,
        build_agent_turn_output_v1,
        raw,
    )


def test_report_float_is_bound_as_exact_integer_cents():
    output = build_agent_turn_output_v1(_report_output(oferta=50.25))
    report_event = next(
        event
        for event in output.events
        if event.name is AgentTurnOutputEventName.REPORT_CAPTURED
    )
    payload = json.loads(report_event.payload_json)
    assert payload == {
        "relatorio": {
            "decisoes": 1,
            "oferta_centavos": 5025,
            "presentes": 12,
            "visitantes": 2,
        }
    }
    assert b'"oferta"' not in report_event.payload_json


@pytest.mark.parametrize(
    "amount, cents",
    [
        (None, None),
        (0, 0),
        (0.0, 0),
        (0.1, 10),
        (1, 100),
        (10.5, 1050),
        (999_999.99, 99_999_999),
    ],
)
def test_report_amount_normalization_is_deterministic(amount, cents):
    output = build_agent_turn_output_v1(_report_output(oferta=amount))
    report = json.loads(output.events[-1].payload_json)["relatorio"]
    assert report["oferta_centavos"] == cents


@pytest.mark.parametrize(
    "amount, cents",
    [
        (MAX_REPORT_OFFERING_CENTS // 100, 999_999_999_900),
        (9_999_999_999.99, MAX_REPORT_OFFERING_CENTS),
    ],
)
def test_report_amount_accepts_numeric_12_2_boundary(amount, cents):
    output = build_agent_turn_output_v1(_report_output(oferta=amount))
    report = json.loads(output.events[-1].payload_json)["relatorio"]
    assert report["oferta_centavos"] == cents


@pytest.mark.parametrize(
    "precision, rounding, trapped_signals",
    [
        (2, ROUND_DOWN, ()),
        (2, ROUND_CEILING, (Inexact, Rounded)),
        (50, ROUND_UP, (Rounded,)),
    ],
)
def test_report_amount_and_hashes_ignore_decimal_context(
    precision,
    rounding,
    trapped_signals,
):
    with localcontext() as context:
        context.prec = precision
        context.rounding = rounding
        for signal in context.traps:
            context.traps[signal] = False
        for signal in trapped_signals:
            context.traps[signal] = True

        output = build_agent_turn_output_v1(_report_output(oferta=50.25))
        plan = project_agent_turn_execution_plan(_identity(), output)

    report = json.loads(output.events[-1].payload_json)["relatorio"]
    assert report["oferta_centavos"] == 5025
    assert output.output_digest == (
        "agent_turn_output_v1_"
        "040fbef173960c97fb1bd3f6016b531ad02c07b70f4478ccc6010c67fc457e38"
    )
    assert plan.plan_digest == (
        "agent_plan_v1_"
        "2c49a951ba6ca8c3ff9213e091cd4c3a18dbbebbcbd5101c680b1c49c2e8f17a"
    )


@pytest.mark.parametrize(
    "amount",
    [
        True,
        -1,
        -0.0,
        -0.01,
        1.001,
        float("nan"),
        float("inf"),
        float("-inf"),
        "50.25",
        object(),
        10_000_000_000,
        10_000_000_000.0,
        MAX_CANONICAL_INTEGER,
    ],
)
def test_report_amount_rejects_ambiguous_or_out_of_range_values(amount):
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_REPORT_AMOUNT,
        build_agent_turn_output_v1,
        _report_output(oferta=amount),
    )


def test_event_order_never_allocates_transient_ordinals():
    identity = _identity()
    first_output = build_agent_turn_output_v1(_report_output())
    second_output = build_agent_turn_output_v1(
        _report_output(reverse_events=True)
    )
    assert first_output.events == second_output.events
    assert first_output.output_digest == second_output.output_digest

    first_plan = project_agent_turn_execution_plan(identity, first_output)
    second_plan = project_agent_turn_execution_plan(identity, second_output)
    assert first_plan == second_plan
    audit_ordinals = [
        intent.ordinal
        for intent in first_plan.effect_intents
        if intent.kind is AgentEffectKind.AUDIT_EVENT
    ]
    assert audit_ordinals == [0, 10, 60]


def test_projected_plan_blocks_tool_call_effects_and_orders_reply_last():
    plan = project_agent_turn_execution_plan(_identity(), _report_output())
    assert AgentEffectKind.TOOL_CALL not in {
        intent.kind for intent in plan.effect_intents
    }
    assert plan.effect_intents[-1].kind is AgentEffectKind.OUTBOUND_REPLY
    assert len(plan.effect_intents) == 5


def test_no_plan_is_first_execution_unsupported():
    resolution = reconcile_agent_turn_output_replay(
        _identity(), _output(), [], []
    )
    assert (
        resolution.status
        is AgentTurnPlanAdapterStatus.FIRST_EXECUTION_UNSUPPORTED
    )
    assert resolution.effect_count == 4
    assert resolution.terminal_receipt_count == 0
    assert "EXECUTABLE" not in {
        item.name for item in AgentTurnPlanAdapterStatus
    }


@pytest.mark.parametrize("missing_index", [0, 1, 2, -1])
def test_any_missing_receipt_is_first_execution_unsupported(missing_index):
    identity = _identity()
    output = _report_output()
    plan = project_agent_turn_execution_plan(identity, output)
    receipts = _receipts(identity, plan)
    receipts.pop(missing_index)
    resolution = reconcile_agent_turn_output_replay(
        identity, output, [plan], receipts
    )
    assert (
        resolution.status
        is AgentTurnPlanAdapterStatus.FIRST_EXECUTION_UNSUPPORTED
    )
    assert resolution.terminal_receipt_count == len(plan.effect_intents) - 1


@pytest.mark.parametrize(
    "outcome",
    [
        AgentEffectReceiptOutcome.COMMITTED,
        AgentEffectReceiptOutcome.NOOP,
        AgentEffectReceiptOutcome.REJECTED,
    ],
)
def test_exact_plan_and_one_terminal_receipt_per_effect_is_terminal_replay(
    outcome,
):
    identity = _identity()
    output = _report_output()
    plan = project_agent_turn_execution_plan(identity, output)
    receipts = list(reversed(_receipts(identity, plan, outcome)))
    resolution = reconcile_agent_turn_output_replay(
        identity, output, [plan], receipts
    )
    assert resolution.status is AgentTurnPlanAdapterStatus.REPLAY_TERMINAL
    assert resolution.effect_count == len(plan.effect_intents)
    assert resolution.terminal_receipt_count == len(plan.effect_intents)
    assert resolution.plan_digest == plan.plan_digest


@pytest.mark.parametrize(
    "raw",
    [
        _output(),
        _handoff_output(),
        _optout_output(),
        _consent_output(accepted=False),
        _consent_output(accepted=True),
        _report_output(),
    ],
)
def test_every_closed_route_reconciles_only_after_all_terminal_receipts(raw):
    identity = _identity()
    plan = project_agent_turn_execution_plan(identity, raw)
    resolution = reconcile_agent_turn_output_replay(
        identity,
        raw,
        [plan],
        _receipts(identity, plan),
    )
    assert resolution.status is AgentTurnPlanAdapterStatus.REPLAY_TERMINAL


def test_duplicate_plan_rows_fail_closed():
    identity = _identity()
    output = _output()
    plan = project_agent_turn_execution_plan(identity, output)
    _assert_error(
        AgentTurnPlanAdapterErrorCode.PLAN_CONFLICT,
        reconcile_agent_turn_output_replay,
        identity,
        output,
        [plan, plan],
        [],
    )


def test_changed_output_conflicts_with_existing_plan():
    identity = _identity()
    original = _output(response="Primeira resposta")
    changed = _output(response="Resposta alterada")
    stored = project_agent_turn_execution_plan(identity, original)
    _assert_error(
        AgentTurnPlanAdapterErrorCode.PLAN_CONFLICT,
        reconcile_agent_turn_output_replay,
        identity,
        changed,
        [stored],
        [],
    )


def test_cross_tenant_plan_fails_closed():
    first_identity = _identity()
    other_identity = _identity(
        igreja_id=uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    )
    output = _output()
    foreign_plan = project_agent_turn_execution_plan(first_identity, output)
    _assert_error(
        AgentTurnPlanAdapterErrorCode.PLAN_CONFLICT,
        reconcile_agent_turn_output_replay,
        other_identity,
        output,
        [foreign_plan],
        [],
    )


@pytest.mark.parametrize(
    "identity",
    [
        None,
        object(),
        "agent_turn_v1_" + "0" * 64,
    ],
)
def test_invalid_expected_identity_is_rejected_before_projection(identity):
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_EXPECTED_IDENTITY,
        project_agent_turn_execution_plan,
        identity,
        _output(),
    )


def test_receipt_from_another_turn_is_unexpected():
    identity = _identity()
    other_identity = _identity(
        inbound_message_id=uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    )
    output = _output()
    plan = project_agent_turn_execution_plan(identity, output)
    other_plan = project_agent_turn_execution_plan(other_identity, output)
    foreign_receipt = _receipts(other_identity, other_plan)[0]
    _assert_error(
        AgentTurnPlanAdapterErrorCode.UNEXPECTED_RECEIPT,
        reconcile_agent_turn_output_replay,
        identity,
        output,
        [plan],
        [foreign_receipt],
    )


def test_duplicate_receipt_for_one_effect_is_conflict():
    identity = _identity()
    output = _output()
    plan = project_agent_turn_execution_plan(identity, output)
    receipts = _receipts(identity, plan)
    receipts.append(receipts[0])
    _assert_error(
        AgentTurnPlanAdapterErrorCode.RECEIPT_CONFLICT,
        reconcile_agent_turn_output_replay,
        identity,
        output,
        [plan],
        receipts,
    )


def test_receipts_without_a_stored_plan_are_never_replay_evidence():
    identity = _identity()
    output = _output()
    plan = project_agent_turn_execution_plan(identity, output)
    _assert_error(
        AgentTurnPlanAdapterErrorCode.UNEXPECTED_RECEIPT,
        reconcile_agent_turn_output_replay,
        identity,
        output,
        [],
        [_receipts(identity, plan)[0]],
    )


def test_mutated_receipt_material_is_rejected():
    identity = _identity()
    output = _output()
    plan = project_agent_turn_execution_plan(identity, output)
    receipts = _receipts(identity, plan)
    object.__setattr__(
        receipts[0],
        "receipt_digest",
        "agent_receipt_material_v1_" + "0" * 64,
    )
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_RECEIPT,
        reconcile_agent_turn_output_replay,
        identity,
        output,
        [plan],
        receipts,
    )


def test_mutated_plan_digest_is_rejected():
    identity = _identity()
    output = _output()
    plan = project_agent_turn_execution_plan(identity, output)
    object.__setattr__(plan, "plan_digest", "agent_plan_v1_" + "0" * 64)
    _assert_error(
        AgentTurnPlanAdapterErrorCode.PLAN_CONFLICT,
        reconcile_agent_turn_output_replay,
        identity,
        output,
        [plan],
        [],
    )


@pytest.mark.parametrize("plans", [None, {}, (), object(), (item for item in ())])
def test_plan_collection_requires_plain_list_or_tuple(plans):
    if plans == ():
        resolution = reconcile_agent_turn_output_replay(
            _identity(), _output(), plans, []
        )
        assert (
            resolution.status
            is AgentTurnPlanAdapterStatus.FIRST_EXECUTION_UNSUPPORTED
        )
        return
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_PLAN_COLLECTION,
        reconcile_agent_turn_output_replay,
        _identity(),
        _output(),
        plans,
        [],
    )


@pytest.mark.parametrize("receipts", [None, {}, object(), (item for item in ())])
def test_receipt_collection_requires_plain_list_or_tuple(receipts):
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_RECEIPT_COLLECTION,
        reconcile_agent_turn_output_replay,
        _identity(),
        _output(),
        [],
        receipts,
    )


def test_receipt_collection_bound_is_checked_before_iteration():
    identity = _identity()
    output = _output()
    plan = project_agent_turn_execution_plan(identity, output)
    receipt = _receipts(identity, plan)[0]
    _assert_error(
        AgentTurnPlanAdapterErrorCode.RECEIPT_LIMIT_EXCEEDED,
        reconcile_agent_turn_output_replay,
        identity,
        output,
        [plan],
        [receipt] * (MAX_AGENT_TURN_RECEIPTS + 1),
    )


def test_tool_calls_are_blocked_even_when_structurally_plausible():
    raw = _output()
    raw["turn_effects"]["tool_calls"] = [
        {"ferramenta": "registrar_decisao", "args": {}}
    ]
    _assert_error(
        AgentTurnPlanAdapterErrorCode.TOOL_CALLS_FORBIDDEN,
        build_agent_turn_output_v1,
        raw,
    )


@pytest.mark.parametrize("tool_calls", [(), {}, None, ""])
def test_tool_calls_container_must_be_an_exact_empty_list(tool_calls):
    raw = _output()
    raw["turn_effects"]["tool_calls"] = tool_calls
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT,
        build_agent_turn_output_v1,
        raw,
    )


def test_duplicate_events_are_rejected_before_plan_allocation():
    raw = _output()
    raw["turn_effects"]["events"].append(
        deepcopy(raw["turn_effects"]["events"][0])
    )
    _assert_error(
        AgentTurnPlanAdapterErrorCode.DUPLICATE_OUTPUT_EVENT,
        build_agent_turn_output_v1,
        raw,
    )


def test_unknown_event_is_rejected():
    raw = _output()
    raw["turn_effects"]["events"][1]["evento"] = "model_invented_event"
    _assert_error(
        AgentTurnPlanAdapterErrorCode.UNKNOWN_OUTPUT_EVENT,
        build_agent_turn_output_v1,
        raw,
    )


def test_known_but_wrong_route_event_is_rejected():
    raw = _output()
    raw["turn_effects"]["events"][1] = {
        "evento": "optout",
        "payload": {},
    }
    _assert_error(
        AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH,
        build_agent_turn_output_v1,
        raw,
    )


def test_event_count_is_bounded_before_event_validation():
    raw = _output()
    raw["turn_effects"]["events"] = [object()] * (
        MAX_AGENT_TURN_OUTPUT_EVENTS + 1
    )
    _assert_error(
        AgentTurnPlanAdapterErrorCode.TURN_OUTPUT_LIMIT_EXCEEDED,
        build_agent_turn_output_v1,
        raw,
    )


@pytest.mark.parametrize(
    "value, code",
    [
        (
            "x" * (MAX_AGENT_TURN_RESPONSE_BYTES + 1),
            AgentTurnPlanAdapterErrorCode.TURN_OUTPUT_LIMIT_EXCEEDED,
        ),
        ("\ud800", AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT),
    ],
)
def test_response_is_bounded_and_valid_utf8(value, code):
    raw = _output()
    raw["response"] = value
    _assert_error(
        code,
        build_agent_turn_output_v1,
        raw,
    )


@pytest.mark.parametrize(
    "raw",
    [
        _output(
            route_event={
                "evento": "onboarding",
                "payload": {
                    "classificacao": "x" * (MAX_AGENT_TURN_FIELD_BYTES + 1)
                },
            }
        ),
        _output(
            route="consent",
            response="Consentimento tratado.",
            route_event={
                "evento": "consent_accepted",
                "payload": {"termoVersao": "termo-2026-08"},
            },
            apply_consent_version="x" * (MAX_AGENT_TURN_FIELD_BYTES + 1),
        ),
    ],
)
def test_output_fields_are_bounded_before_canonicalization(raw):
    _assert_error(
        AgentTurnPlanAdapterErrorCode.TURN_OUTPUT_LIMIT_EXCEEDED,
        build_agent_turn_output_v1,
        raw,
    )


def test_oversized_whitespace_hits_static_limit_before_content_scan():
    raw = _output(
        response=" " * (MAX_AGENT_TURN_RESPONSE_BYTES + 1),
    )
    _assert_error(
        AgentTurnPlanAdapterErrorCode.TURN_OUTPUT_LIMIT_EXCEEDED,
        build_agent_turn_output_v1,
        raw,
    )


@pytest.mark.parametrize(
    "raw",
    [
        _output(response="á" * ((MAX_AGENT_TURN_RESPONSE_BYTES // 2) + 1)),
        _output(
            route_event={
                "evento": "onboarding",
                "payload": {
                    "classificacao": "á"
                    * ((MAX_AGENT_TURN_FIELD_BYTES // 2) + 1)
                },
            }
        ),
    ],
)
def test_multibyte_strings_are_bounded_by_encoded_bytes(raw):
    _assert_error(
        AgentTurnPlanAdapterErrorCode.TURN_OUTPUT_LIMIT_EXCEEDED,
        build_agent_turn_output_v1,
        raw,
    )


@pytest.mark.parametrize("value", [" leading", "trailing ", "line\nbreak"])
def test_bounded_strings_reject_edge_whitespace_and_controls(value):
    raw = _output(response=value)
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT,
        build_agent_turn_output_v1,
        raw,
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda raw: raw.update({"unknown": True}),
        lambda raw: raw["turn_effects"].update({"unknown": True}),
        lambda raw: raw["turn_effects"]["events"][0].update(
            {"unknown": True}
        ),
        lambda raw: raw.update({"route": "unknown"}),
        lambda raw: raw.update({"response": None}),
        lambda raw: raw["turn_effects"].update({"apply_optout": 1}),
        lambda raw: raw["turn_effects"].update(
            {"apply_consent_version": 1}
        ),
        lambda raw: raw["turn_effects"].update(
            {"intake_update": {"unknown": True}}
        ),
    ],
)
def test_output_envelope_is_exact_and_closed(mutator):
    raw = _output()
    mutator(raw)
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT,
        build_agent_turn_output_v1,
        raw,
    )


@pytest.mark.parametrize(
    "field, value",
    [
        ("presentes", True),
        ("presentes", -1),
        ("presentes", MAX_CANONICAL_INTEGER + 1),
        ("visitantes", 1.0),
        ("decisoes", "1"),
    ],
)
def test_report_counts_are_exact_nonnegative_integers_or_null(field, value):
    raw = _report_output()
    raw["turn_effects"]["events"][1]["payload"]["relatorio"][field] = value
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT,
        build_agent_turn_output_v1,
        raw,
    )


def test_report_counts_share_the_workflow_boundary():
    accepted = _report_output()
    report = accepted["turn_effects"]["events"][1]["payload"]["relatorio"]
    report["presentes"] = MAX_REPORT_COUNT
    output = build_agent_turn_output_v1(accepted)
    normalized = json.loads(output.events[-1].payload_json)["relatorio"]
    assert normalized["presentes"] == MAX_REPORT_COUNT

    rejected = _report_output()
    report = rejected["turn_effects"]["events"][1]["payload"]["relatorio"]
    report["presentes"] = MAX_REPORT_COUNT + 1
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT,
        build_agent_turn_output_v1,
        rejected,
    )


@pytest.mark.parametrize(
    "update",
    [
        {"origem": "email"},
        {"set_primeiro_contato": False},
        {"sem_interesse": False},
        {"sem_interesse": True},
        {"sem_interesse_motivo": "comercial"},
        {"sem_interesse": True, "sem_interesse_motivo": 1},
        {"unknown": True},
    ],
)
def test_intake_update_vocabulary_is_closed(update):
    raw = _output(intake_update=update)
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT,
        build_agent_turn_output_v1,
        raw,
    )


def test_consent_event_and_effect_version_must_match():
    raw = _consent_output(accepted=True)
    raw["turn_effects"]["apply_consent_version"] = "other-version"
    _assert_error(
        AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH,
        build_agent_turn_output_v1,
        raw,
    )


def test_optout_flag_must_match_the_route():
    raw = _optout_output()
    raw["turn_effects"]["apply_optout"] = False
    _assert_error(
        AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH,
        build_agent_turn_output_v1,
        raw,
    )


def test_raw_input_mutation_cannot_change_detached_output_or_plan():
    identity = _identity()
    raw = _report_output()
    output = build_agent_turn_output_v1(raw)
    plan = project_agent_turn_execution_plan(identity, output)

    raw["response"] = "mutated"
    raw["turn_effects"]["intake_update"].clear()
    raw["turn_effects"]["events"].clear()

    assert validate_agent_turn_output_v1(output) is output
    assert project_agent_turn_execution_plan(identity, output) == plan


@pytest.mark.parametrize(
    "field, forged, expected_code",
    [
        ("schema_version", "v2", AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT),
        ("route", "onboarding", AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT),
        (
            "response",
            "forged response",
            AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT,
        ),
        ("apply_optout", True, AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH),
        (
            "apply_consent_version",
            "forged",
            AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH,
        ),
        (
            "output_digest",
            "agent_turn_output_v1_" + "0" * 64,
            AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT,
        ),
        (
            "intake_update_json",
            b'{"unknown":true}',
            AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT,
        ),
    ],
)
def test_forged_output_snapshot_is_revalidated(field, forged, expected_code):
    output = build_agent_turn_output_v1(_output())
    object.__setattr__(output, field, forged)
    _assert_error(
        expected_code,
        validate_agent_turn_output_v1,
        output,
    )


def test_forged_event_ordinal_is_rejected():
    output = build_agent_turn_output_v1(_output())
    object.__setattr__(output.events[0], "ordinal", 999)
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT,
        validate_agent_turn_output_v1,
        output,
    )


def test_forged_event_payload_is_rejected():
    output = build_agent_turn_output_v1(_output())
    object.__setattr__(output.events[0], "payload_json", b'{"update":{}} ')
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT,
        validate_agent_turn_output_v1,
        output,
    )


def test_forged_report_amount_is_rejected_even_with_recomputed_digest():
    output = build_agent_turn_output_v1(_report_output())
    report_event = next(
        event
        for event in output.events
        if event.name is AgentTurnOutputEventName.REPORT_CAPTURED
    )
    object.__setattr__(
        report_event,
        "payload_json",
        (
            b'{"relatorio":{"decisoes":1,"oferta_centavos":'
            b'1000000000000,"presentes":12,"visitantes":2}}'
        ),
    )
    material = turn_plan_adapter_module._output_material(
        route=output.route,
        response=output.response,
        events=output.events,
        apply_optout=output.apply_optout,
        apply_consent_version=output.apply_consent_version,
        intake_update=json.loads(output.intake_update_json),
    )
    object.__setattr__(
        output,
        "output_digest",
        turn_plan_adapter_module._derive_output_digest(material),
    )
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_REPORT_AMOUNT,
        validate_agent_turn_output_v1,
        output,
    )


@pytest.mark.parametrize(
    "payload_json",
    [
        b'{"value":' + (b"9" * 5_000) + b"}",
        (b"[" * 2_000) + b"0" + (b"]" * 2_000),
    ],
)
@pytest.mark.parametrize("target", ["event", "intake_update"])
def test_forged_json_parser_limits_are_sanitized(payload_json, target):
    output = build_agent_turn_output_v1(_output())
    if target == "event":
        object.__setattr__(output.events[0], "payload_json", payload_json)
    else:
        object.__setattr__(output, "intake_update_json", payload_json)
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT,
        validate_agent_turn_output_v1,
        output,
    )


def test_revalidation_rejects_forged_csim_coherence():
    raw = _output(
        intake_update={
            "origem": "whatsapp",
            "set_primeiro_contato": True,
            "sem_interesse": True,
            "sem_interesse_motivo": "comercial/empresa",
        },
        route_event={
            "evento": "onboarding",
            "payload": {"classificacao": "csim"},
        },
    )
    forged_event = build_agent_turn_output_v1(raw)
    onboarding = next(
        event
        for event in forged_event.events
        if event.name is AgentTurnOutputEventName.ONBOARDING
    )
    object.__setattr__(
        onboarding,
        "payload_json",
        b'{"classificacao":"novo_contato"}',
    )
    _assert_error(
        AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH,
        validate_agent_turn_output_v1,
        forged_event,
    )

    forged_update = build_agent_turn_output_v1(raw)
    object.__setattr__(
        forged_update,
        "intake_update_json",
        b'{"origem":"whatsapp","set_primeiro_contato":true}',
    )
    _assert_error(
        AgentTurnPlanAdapterErrorCode.OUTPUT_EVENT_MISMATCH,
        validate_agent_turn_output_v1,
        forged_update,
    )


def test_snapshot_event_tuple_must_remain_in_canonical_order():
    output = build_agent_turn_output_v1(_output())
    object.__setattr__(output, "events", tuple(reversed(output.events)))
    _assert_error(
        AgentTurnPlanAdapterErrorCode.INVALID_TURN_OUTPUT,
        validate_agent_turn_output_v1,
        output,
    )


def test_output_digest_binds_response_and_route_effects():
    onboarding = build_agent_turn_output_v1(_output())
    optout = build_agent_turn_output_v1(_optout_output())
    changed_response = build_agent_turn_output_v1(
        _output(response="Outra resposta")
    )
    assert len({
        onboarding.output_digest,
        optout.output_digest,
        changed_response.output_digest,
    }) == 3


def test_fixed_cross_process_vector_for_report_output_and_plan():
    identity = _identity()
    output = build_agent_turn_output_v1(_report_output())
    plan = project_agent_turn_execution_plan(identity, output)

    assert output.output_digest == (
        "agent_turn_output_v1_"
        "040fbef173960c97fb1bd3f6016b531ad02c07b70f4478ccc6010c67fc457e38"
    )
    assert plan.plan_digest == (
        "agent_plan_v1_"
        "2c49a951ba6ca8c3ff9213e091cd4c3a18dbbebbcbd5101c680b1c49c2e8f17a"
    )
    assert [intent.effect_id for intent in plan.effect_intents] == [
        "agent_effect_v1_"
        "c9016058da2c306739fdc1c279a9976d0575f5a0ff74e30ec843083e7228f42c",
        "agent_effect_v1_"
        "f75a8ed90c6b6129066765825501f4ebfbc53ccebf379708e42be3b2a254d304",
        "agent_effect_v1_"
        "f1c6eb3b0f013927894a6a5c7bb49b146fc0749d51d873b2f5a15bd25fc821a7",
        "agent_effect_v1_"
        "a5648f22b5302a49446ffe43cebcfdcb82e12f2b6ccf0921e0350c794449d417",
        "agent_effect_v1_"
        "50ddd85405e7b663697c380823c86eab9428a3649c3d79b136a7bff9dff60939",
    ]


def test_error_and_repr_never_echo_private_output_or_identity():
    secret = "PRIVATE-PASTORAL-CONTENT"
    raw = _output(response=secret)
    raw["turn_effects"]["tool_calls"] = [{"secret": secret}]
    with pytest.raises(AgentTurnPlanAdapterError) as caught:
        build_agent_turn_output_v1(raw)
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)

    output = build_agent_turn_output_v1(_output(response=secret))
    resolution = reconcile_agent_turn_output_replay(
        _identity(provider_message_id=secret), output, [], []
    )
    assert secret not in repr(output)
    assert secret not in repr(resolution)


def test_snapshot_reprs_are_static_after_field_forgery():
    secret = "PRIVATE-FORGED-MATERIAL"

    class ForgedValue:
        value = secret

        def __repr__(self):
            return secret

    output = build_agent_turn_output_v1(_output())
    event = output.events[0]
    resolution = reconcile_agent_turn_output_replay(
        _identity(), output, [], []
    )

    object.__setattr__(event, "schema_version", secret)
    object.__setattr__(event, "name", ForgedValue())
    object.__setattr__(event, "ordinal", secret)
    object.__setattr__(output, "schema_version", secret)
    object.__setattr__(output, "route", ForgedValue())
    object.__setattr__(output, "events", ForgedValue())
    object.__setattr__(resolution, "status", ForgedValue())
    object.__setattr__(resolution, "effect_count", secret)
    object.__setattr__(resolution, "terminal_receipt_count", secret)

    assert repr(event) == "AgentTurnOutputEventV1(<redacted>)"
    assert repr(output) == "AgentTurnOutputV1(<redacted>)"
    assert repr(resolution) == "AgentTurnPlanReplayResolution(<redacted>)"


def test_module_has_no_operational_imports_or_io_calls():
    source_path = (
        Path(__file__).parents[1] / "app" / "agent" / "turn_plan_adapter.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called_names.add(node.func.id)

    forbidden_import_prefixes = (
        "os",
        "time",
        "random",
        "socket",
        "subprocess",
        "sqlalchemy",
        "app.models",
        "app.workers",
        "app.agent.runtime",
        "app.agent.graph",
        "app.agent.nodes",
    )
    assert not any(
        module == prefix or module.startswith(prefix + ".")
        for module in imported
        for prefix in forbidden_import_prefixes
    )
    assert called_names.isdisjoint({"open", "print", "input", "exec", "eval"})
    assert "Callable" not in source
    assert "callback" not in source.lower()


def test_status_vocabulary_is_closed_and_never_grants_execution():
    assert tuple(item.value for item in AgentTurnPlanAdapterStatus) == (
        "FIRST_EXECUTION_UNSUPPORTED",
        "REPLAY_TERMINAL",
    )
    assert not hasattr(AgentTurnPlanAdapterStatus, "EXECUTABLE")
