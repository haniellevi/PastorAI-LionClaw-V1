from __future__ import annotations

import copy
import datetime as dt
import json
import tracemalloc
import uuid

import pytest

from app.domain.cell_report_pending_proposal import (
    CELL_REPORT_PENDING_PROPOSAL_SCHEMA_V1,
    MAX_CELL_REPORT_PROPOSAL_OPERATION_RECEIPTS,
    CellReportPendingProposalError,
    CellReportPendingProposalErrorCode,
    build_cell_report_pending_proposal,
    cell_report_proposal_bindings_match,
    derive_cell_report_proposal_base_state_digest,
    derive_cell_report_proposal_bindings,
    rehydrate_cell_report_pending_proposal,
)
from app.domain.cell_report_workflow import (
    CellReportWorkflowState,
    build_cell_report_candidate,
    correlate_cell_report_confirmation,
    revise_cell_report_workflow,
    start_cell_report_workflow,
)


TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
MEETING = uuid.UUID("22222222-2222-2222-2222-222222222222")
CONVERSATION = uuid.UUID("33333333-3333-3333-3333-333333333333")
ACTOR = uuid.UUID("44444444-4444-4444-4444-444444444444")
SCOPE = f"cell_report_scope_v1_{'a' * 64}"
EFFECT = f"agent_effect_v1_{'b' * 64}"
PAYLOAD_DIGEST = f"agent_payload_v1_{'c' * 64}"
EXPIRY = dt.datetime(
    2026,
    8,
    31,
    18,
    30,
    1,
    123456,
    tzinfo=dt.timezone.utc,
)


def _base_digest() -> str:
    return derive_cell_report_proposal_base_state_digest(
        relatorio_status="pendente",
        oferta_valor=None,
        observacoes=None,
    )


def _candidate():
    return build_cell_report_candidate(
        presentes=12,
        visitantes=2,
        decisoes=1,
        oferta="999999.99",
        observacoes="Reunião tranquila",
    )


def _bindings():
    return derive_cell_report_proposal_bindings(
        igreja_id=TENANT,
        reuniao_id=MEETING,
        conversa_id=CONVERSATION,
        ator_pessoa_id=ACTOR,
    )


def _proposal():
    return build_cell_report_pending_proposal(
        workflow=start_cell_report_workflow(
            correlation_key=SCOPE,
            candidate=_candidate(),
        ),
        bindings=_bindings(),
        expires_at=EXPIRY,
        operation_effect_id=EFFECT,
        operation_payload_digest=PAYLOAD_DIGEST,
        base_state_digest=_base_digest(),
    )


def _effect(index: int) -> str:
    return f"agent_effect_v1_{index:064x}"


def _payload_digest(index: int) -> str:
    return f"agent_payload_v1_{index:064x}"


def test_closed_jsonb_round_trip_is_detached_and_has_no_raw_identity_uuid() -> None:
    proposal = _proposal()
    payload = proposal.to_jsonb()

    assert payload.keys() == {
        "schema",
        "bindings",
        "expires_at",
        "operation_receipts",
        "base_state_digest",
        "workflow",
    }
    assert payload["schema"] == CELL_REPORT_PENDING_PROPOSAL_SCHEMA_V1
    assert payload["expires_at"] == "2026-08-31T18:30:01.123456Z"
    assert payload["operation_receipts"] == [
        {"effect_id": EFFECT, "payload_digest": PAYLOAD_DIGEST}
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for identifier in (TENANT, MEETING, CONVERSATION, ACTOR):
        assert str(identifier) not in encoded
    assert "Reunião tranquila" not in repr(proposal)
    assert "Reunião tranquila" not in repr(proposal.bindings)
    assert "Reunião tranquila" not in repr(proposal.operation_receipts[0])

    hydrated = rehydrate_cell_report_pending_proposal(copy.deepcopy(payload))
    assert hydrated == proposal
    detached = hydrated.to_jsonb()
    detached["bindings"]["actor"] = "changed"  # type: ignore[index]
    assert hydrated.to_jsonb() == payload


def test_bindings_are_domain_separated_and_constant_shape() -> None:
    bindings = _bindings()
    values = tuple(bindings.to_jsonb().values())
    assert len(set(values)) == 4
    assert all(value.endswith(value[-64:]) for value in values)
    assert cell_report_proposal_bindings_match(bindings, bindings)

    other = derive_cell_report_proposal_bindings(
        igreja_id=TENANT,
        reuniao_id=MEETING,
        conversa_id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
        ator_pessoa_id=ACTOR,
    )
    assert not cell_report_proposal_bindings_match(bindings, other)


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        (("schema",), "cell-report-pending-proposal/v99", "UNSUPPORTED_SCHEMA"),
        (("bindings", "actor"), "raw-actor", "INVALID_BINDING"),
        (("expires_at",), "2026-08-31T18:30:01Z", "INVALID_EXPIRY"),
        (
            ("operation_receipts", 0, "effect_id"),
            "free text",
            "INVALID_EFFECT_ID",
        ),
        (
            ("operation_receipts", 0, "payload_digest"),
            "free text",
            "INVALID_OPERATION_RECEIPTS",
        ),
        (("base_state_digest",), "free text", "INVALID_BASE_STATE"),
        (("workflow", "candidate_digest"), "forged", "INVALID_WORKFLOW"),
        (("workflow", "confirmation_code"), "AAAAAAAAAAAA", "INVALID_WORKFLOW"),
        (("workflow", "revision"), True, "INVALID_WORKFLOW"),
    ],
)
def test_hydration_rejects_tampering_with_sanitized_error(
    path: tuple[str | int, ...],
    value: object,
    code: str,
) -> None:
    payload = _proposal().to_jsonb()
    target: object = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(CellReportPendingProposalError) as raised:
        rehydrate_cell_report_pending_proposal(payload)
    assert raised.value.code.value == code
    assert str(TENANT) not in str(raised.value)
    assert "Reunião tranquila" not in repr(raised.value)


def test_hydration_rejects_extra_or_missing_keys() -> None:
    extra = _proposal().to_jsonb()
    extra["future"] = "ignored"
    with pytest.raises(CellReportPendingProposalError, match="INVALID_PROPOSAL"):
        rehydrate_cell_report_pending_proposal(extra)

    missing = _proposal().to_jsonb()
    del missing["workflow"]
    with pytest.raises(CellReportPendingProposalError, match="INVALID_PROPOSAL"):
        rehydrate_cell_report_pending_proposal(missing)


def test_pending_envelope_rejects_confirmation_accepted_workflow() -> None:
    workflow = start_cell_report_workflow(
        correlation_key=SCOPE,
        candidate=_candidate(),
    )
    accepted = correlate_cell_report_confirmation(
        workflow,
        f"CONFIRMAR RELATORIO {workflow.confirmation_code}",
    )
    assert accepted.state is CellReportWorkflowState.CONFIRMATION_ACCEPTED

    with pytest.raises(CellReportPendingProposalError, match="INVALID_PENDING_STATE"):
        build_cell_report_pending_proposal(
            workflow=accepted,
            bindings=_bindings(),
            expires_at=EXPIRY,
            operation_effect_id=EFFECT,
            operation_payload_digest=PAYLOAD_DIGEST,
            base_state_digest=_base_digest(),
        )


def test_receipt_history_is_ordered_unique_and_exactly_matches_revision() -> None:
    first = build_cell_report_pending_proposal(
        workflow=start_cell_report_workflow(
            correlation_key=SCOPE,
            candidate=build_cell_report_candidate(presentes=1),
        ),
        bindings=_bindings(),
        expires_at=EXPIRY,
        operation_effect_id=_effect(1),
        operation_payload_digest=_payload_digest(1),
        base_state_digest=_base_digest(),
    )
    revised_workflow = revise_cell_report_workflow(
        first.workflow,
        build_cell_report_candidate(
            presentes=1,
            visitantes=0,
            decisoes=0,
            oferta="0.00",
        ),
    )
    second = build_cell_report_pending_proposal(
        workflow=revised_workflow,
        bindings=_bindings(),
        expires_at=EXPIRY,
        operation_effect_id=_effect(2),
        operation_payload_digest=_payload_digest(2),
        base_state_digest=_base_digest(),
        prior_operation_receipts=first.operation_receipts,
    )
    assert [item.effect_id for item in second.operation_receipts] == [
        _effect(1),
        _effect(2),
    ]
    assert second.last_operation_effect_id == _effect(2)
    assert second.last_operation_payload_digest == _payload_digest(2)

    truncated = second.to_jsonb()
    receipts = truncated["operation_receipts"]
    truncated["operation_receipts"] = receipts[-1:]  # type: ignore[index]
    with pytest.raises(
        CellReportPendingProposalError,
        match="INVALID_OPERATION_RECEIPTS",
    ):
        rehydrate_cell_report_pending_proposal(truncated)

    with pytest.raises(
        CellReportPendingProposalError,
        match="INVALID_OPERATION_RECEIPTS",
    ):
        build_cell_report_pending_proposal(
            workflow=revised_workflow,
            bindings=_bindings(),
            expires_at=EXPIRY,
            operation_effect_id=_effect(1),
            operation_payload_digest=_payload_digest(1),
            base_state_digest=_base_digest(),
            prior_operation_receipts=first.operation_receipts,
        )


def test_receipt_history_never_evicts_and_rejects_operation_33() -> None:
    workflow = start_cell_report_workflow(
        correlation_key=SCOPE,
        candidate=build_cell_report_candidate(presentes=0),
    )
    proposal = build_cell_report_pending_proposal(
        workflow=workflow,
        bindings=_bindings(),
        expires_at=EXPIRY,
        operation_effect_id=_effect(1),
        operation_payload_digest=_payload_digest(1),
        base_state_digest=_base_digest(),
    )
    for index in range(2, MAX_CELL_REPORT_PROPOSAL_OPERATION_RECEIPTS + 1):
        workflow = revise_cell_report_workflow(
            proposal.workflow,
            build_cell_report_candidate(presentes=index),
        )
        proposal = build_cell_report_pending_proposal(
            workflow=workflow,
            bindings=_bindings(),
            expires_at=EXPIRY,
            operation_effect_id=_effect(index),
            operation_payload_digest=_payload_digest(index),
            base_state_digest=_base_digest(),
            prior_operation_receipts=proposal.operation_receipts,
        )
    assert len(proposal.operation_receipts) == 32
    assert proposal.operation_receipts[0].effect_id == _effect(1)

    workflow_33 = revise_cell_report_workflow(
        proposal.workflow,
        build_cell_report_candidate(presentes=33),
    )
    with pytest.raises(
        CellReportPendingProposalError,
        match="INVALID_OPERATION_RECEIPTS",
    ):
        build_cell_report_pending_proposal(
            workflow=workflow_33,
            bindings=_bindings(),
            expires_at=EXPIRY,
            operation_effect_id=_effect(33),
            operation_payload_digest=_payload_digest(33),
            base_state_digest=_base_digest(),
            prior_operation_receipts=proposal.operation_receipts,
        )


def test_base_state_digest_detects_human_changes_without_exposing_text() -> None:
    empty = _base_digest()
    offer = derive_cell_report_proposal_base_state_digest(
        relatorio_status="pendente",
        oferta_valor="1.20",
        observacoes=None,
    )
    private_text = "private pastoral observation"
    observation = derive_cell_report_proposal_base_state_digest(
        relatorio_status="pendente",
        oferta_valor=None,
        observacoes=private_text,
    )
    assert len({empty, offer, observation}) == 3
    assert private_text not in observation

    with pytest.raises(CellReportPendingProposalError, match="INVALID_BASE_STATE"):
        derive_cell_report_proposal_base_state_digest(
            relatorio_status="enviado",
            oferta_valor=None,
            observacoes=None,
        )


def test_expiry_builder_canonicalizes_offset_and_rejects_naive_datetime() -> None:
    offset = dt.timezone(dt.timedelta(hours=-3))
    proposal = build_cell_report_pending_proposal(
        workflow=_proposal().workflow,
        bindings=_proposal().bindings,
        expires_at=dt.datetime(2026, 8, 31, 15, 30, 1, 123456, tzinfo=offset),
        operation_effect_id=EFFECT,
        operation_payload_digest=PAYLOAD_DIGEST,
        base_state_digest=_base_digest(),
    )
    assert proposal.expires_at == EXPIRY

    with pytest.raises(
        CellReportPendingProposalError,
        match=CellReportPendingProposalErrorCode.INVALID_EXPIRY.value,
    ):
        build_cell_report_pending_proposal(
            workflow=_proposal().workflow,
            bindings=_proposal().bindings,
            expires_at=dt.datetime(2026, 8, 31, 18, 30),
            operation_effect_id=EFFECT,
            operation_payload_digest=PAYLOAD_DIGEST,
            base_state_digest=_base_digest(),
        )


def test_large_top_level_or_receipt_collection_fails_before_nested_reads() -> None:
    huge = {f"attacker-{index}": index for index in range(200_000)}
    huge["schema"] = CELL_REPORT_PENDING_PROPOSAL_SCHEMA_V1
    with pytest.raises(CellReportPendingProposalError, match="INVALID_PROPOSAL"):
        rehydrate_cell_report_pending_proposal(huge)

    payload = _proposal().to_jsonb()
    payload["operation_receipts"] = [None] * 200_000
    with pytest.raises(
        CellReportPendingProposalError,
        match="INVALID_OPERATION_RECEIPTS",
    ):
        rehydrate_cell_report_pending_proposal(payload)


def test_oversized_nested_workflow_digest_rejects_without_large_slice() -> None:
    payload = _proposal().to_jsonb()
    payload["workflow"]["scope_digest"] = (  # type: ignore[index]
        "cell_report_scope_v1_" + ("a" * 5_000_000)
    )

    tracemalloc.start()
    with pytest.raises(
        CellReportPendingProposalError,
        match="INVALID_WORKFLOW",
    ):
        rehydrate_cell_report_pending_proposal(payload)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert peak < 1_000_000
