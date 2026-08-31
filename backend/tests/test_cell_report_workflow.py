"""Offline tests for the pure WhatsApp cell-report workflow contract."""

from __future__ import annotations

import json
import subprocess
import sys
import types
from decimal import Decimal, Inexact, ROUND_UP, Rounded, localcontext
from pathlib import Path

import pytest

from app.domain import cell_report_workflow as contract
from app.domain.cell_report_workflow import (
    CELL_REPORT_SCOPE_KEY_PREFIX,
    CONFIRMATION_COMMAND_PREFIX,
    EXPLICIT_TERMINAL_REPORT_STATES,
    MAX_REPORT_CORRELATION_KEY_BYTES,
    MAX_REPORT_COUNT,
    MAX_REPORT_OBSERVATIONS_BYTES,
    MAX_REPORT_OBSERVATIONS_LENGTH,
    MAX_REPORT_TEXT_BYTES,
    CellReportWorkflowError,
    CellReportWorkflowErrorCode,
    CellReportWorkflowState,
    build_cell_report_candidate,
    cell_report_candidate_payload,
    cell_report_confirmation_command,
    correlate_cell_report_confirmation,
    mark_cell_report_committed,
    merge_cell_report_candidates,
    parse_cell_report_candidate,
    parse_cell_report_confirmation_command,
    revise_cell_report_workflow,
    revise_cell_report_workflow_from_text,
    start_cell_report_workflow,
    start_cell_report_workflow_from_text,
    terminalize_cell_report_workflow,
    validate_cell_report_workflow,
)
from app.domain.report import parse_cell_report


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CORRELATION_KEY = CELL_REPORT_SCOPE_KEY_PREFIX + ("a" * 64)
OTHER_CORRELATION_KEY = CELL_REPORT_SCOPE_KEY_PREFIX + ("b" * 64)


def _complete_workflow():
    return start_cell_report_workflow(
        correlation_key=CORRELATION_KEY,
        candidate=build_cell_report_candidate(
            presentes=12,
            visitantes=0,
            decisoes=2,
            oferta="1234.50",
            observacoes="Reunião tranquila",
        ),
    )


def _assert_no_float(value: object) -> None:
    assert type(value) is not float
    if isinstance(value, dict):
        for item in value.values():
            _assert_no_float(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _assert_no_float(item)


def test_legacy_extractor_remains_compatible_and_separate() -> None:
    legacy = parse_cell_report(
        "Relatório: 12 presentes, 3 visitantes, 2 decisões, oferta R$ 50,00"
    )
    assert legacy.presentes == 12
    assert legacy.visitantes == 3
    assert legacy.decisoes == 2
    assert legacy.oferta == 50.0
    assert type(legacy.oferta) is float

    candidate = parse_cell_report_candidate(
        "Relatório: 12 presentes, 3 visitantes, 2 decisões, oferta R$ 50,00"
    )
    assert candidate.oferta == "50.00"
    assert type(candidate.oferta) is str


def test_parser_distinguishes_missing_fields_from_explicit_zero() -> None:
    candidate = parse_cell_report_candidate(
        "0 presentes, 0 visitantes, 0 decisões e oferta 0"
    )
    assert candidate.presentes == 0
    assert candidate.visitantes == 0
    assert candidate.decisoes == 0
    assert candidate.oferta == "0.00"
    assert candidate.is_complete
    assert not candidate.is_empty

    missing = parse_cell_report_candidate("0 presentes")
    assert missing.presentes == 0
    assert missing.visitantes is None
    assert missing.decisoes is None
    assert missing.oferta is None
    assert missing.missing_required_fields == (
        "visitantes",
        "decisoes",
        "oferta",
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", "0.00"),
        ("50", "50.00"),
        ("50.25", "50.25"),
        (Decimal("1.2300"), "1.23"),
    ],
)
def test_offering_is_decimal_validated_and_canonical(
    value: Decimal | str,
    expected: str,
) -> None:
    candidate = build_cell_report_candidate(oferta=value)
    assert candidate.oferta == expected
    _assert_no_float(cell_report_candidate_payload(candidate))


@pytest.mark.parametrize(
    "value",
    [
        1,
        1.0,
        True,
        "",
        " 1.00",
        "1.001",
        "1,001",
        "1..00",
        "NaN",
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-1"),
        Decimal("0.001"),
    ],
)
def test_offering_rejects_float_and_non_exact_or_invalid_values(
    value: object,
) -> None:
    with pytest.raises(CellReportWorkflowError) as exc:
        build_cell_report_candidate(oferta=value)  # type: ignore[arg-type]
    assert exc.value.code in {
        CellReportWorkflowErrorCode.INVALID_OFFERING,
        CellReportWorkflowErrorCode.OFFERING_LIMIT_EXCEEDED,
    }


def test_decimal_context_mutation_cannot_change_amount_or_digests() -> None:
    baseline = _complete_workflow()
    with localcontext() as decimal_context:
        decimal_context.prec = 1
        decimal_context.rounding = ROUND_UP
        decimal_context.traps[Inexact] = True
        decimal_context.traps[Rounded] = True
        mutated = _complete_workflow()
    assert mutated.candidate.oferta == "1234.50"
    assert mutated.candidate_digest == baseline.candidate_digest
    assert mutated.proposal_digest == baseline.proposal_digest
    assert mutated.confirmation_code == baseline.confirmation_code


def test_offering_matches_domain_e2_boundary() -> None:
    boundary = build_cell_report_candidate(oferta="999999.99")
    assert boundary.oferta == "999999.99"

    for overflow in ("1000000.00", Decimal("1000000")):
        with pytest.raises(CellReportWorkflowError) as exc:
            build_cell_report_candidate(oferta=overflow)
        assert exc.value.code is (
            CellReportWorkflowErrorCode.OFFERING_LIMIT_EXCEEDED
        )


def test_parser_extracts_observations_and_rejects_conflicting_values() -> None:
    candidate = parse_cell_report_candidate(
        "presentes: 10, visitantes: 1, decisões: 0, oferta: R$ 25,00, "
        "observações: encontro em paz"
    )
    assert candidate.observacoes == "encontro em paz"

    with pytest.raises(CellReportWorkflowError) as exc:
        parse_cell_report_candidate("10 presentes; corrigindo: 12 presentes")
    assert exc.value.code is CellReportWorkflowErrorCode.CONFLICTING_FIELD_VALUES


@pytest.mark.parametrize(
    ("text", "expected_code"),
    [
        ("-1 presentes", CellReportWorkflowErrorCode.INVALID_COUNT),
        ("presentes -1", CellReportWorkflowErrorCode.INVALID_COUNT),
        ("visitantes: -2", CellReportWorkflowErrorCode.INVALID_COUNT),
        ("decisões = -3", CellReportWorkflowErrorCode.INVALID_COUNT),
        ("oferta -4", CellReportWorkflowErrorCode.INVALID_OFFERING),
        ("oferta: R$ -4,00", CellReportWorkflowErrorCode.INVALID_OFFERING),
        ("R$ -4 de oferta", CellReportWorkflowErrorCode.INVALID_OFFERING),
    ],
)
def test_parser_rejects_negative_values_instead_of_making_them_positive(
    text: str,
    expected_code: CellReportWorkflowErrorCode,
) -> None:
    with pytest.raises(CellReportWorkflowError) as exc:
        parse_cell_report_candidate(text)
    assert exc.value.code is expected_code


@pytest.mark.parametrize("negative_sign", tuple("-−–—﹣－"))
@pytest.mark.parametrize(
    ("template", "expected_code"),
    [
        ("{sign}1 presentes", CellReportWorkflowErrorCode.INVALID_COUNT),
        ("{sign} 1 presentes", CellReportWorkflowErrorCode.INVALID_COUNT),
        ("presentes {sign}1", CellReportWorkflowErrorCode.INVALID_COUNT),
        ("visitantes: {sign} 2", CellReportWorkflowErrorCode.INVALID_COUNT),
        ("{sign}3 decisões", CellReportWorkflowErrorCode.INVALID_COUNT),
        ("decisões = {sign} 3", CellReportWorkflowErrorCode.INVALID_COUNT),
        ("oferta {sign}4", CellReportWorkflowErrorCode.INVALID_OFFERING),
        ("oferta: R$ {sign} 4,00", CellReportWorkflowErrorCode.INVALID_OFFERING),
        ("R$ {sign}4 de oferta", CellReportWorkflowErrorCode.INVALID_OFFERING),
    ],
)
def test_parser_rejects_ascii_and_unicode_negative_signs_in_all_positions(
    negative_sign: str,
    template: str,
    expected_code: CellReportWorkflowErrorCode,
) -> None:
    with pytest.raises(CellReportWorkflowError) as exc:
        parse_cell_report_candidate(template.format(sign=negative_sign))
    assert exc.value.code is expected_code


@pytest.mark.parametrize(
    "invisible",
    (
        "\u200b",
        "\u2060",
        "\u200e",
        "\u200f",
        "\ufeff",
        "\u0301",
        "\u034f",
        "\ufe0f",
        "\u20e3",
    ),
)
def test_parser_rejects_invisible_format_controls_before_matching(
    invisible: str,
) -> None:
    for text in (
        invisible,
        f"−{invisible}1 presentes",
        f"visitantes −{invisible}2",
        f"oferta −{invisible}3",
    ):
        with pytest.raises(CellReportWorkflowError) as exc:
            parse_cell_report_candidate(text)
        assert exc.value.code is CellReportWorkflowErrorCode.INVALID_TEXT


def test_nfc_keeps_legitimate_portuguese_accents_before_mark_rejection() -> None:
    candidate = parse_cell_report_candidate(
        "1 decisão, observações: reunião em comunhão"
    )
    assert candidate.decisoes == 1
    assert candidate.observacoes == "reunião em comunhão"


@pytest.mark.parametrize(
    "text",
    [
        "10abc presentes",
        "abc10 presentes",
        "presentes 10abc",
        "presentes abc10",
        "1presentesx",
        "1presentes",
        "presentes1",
        "10 presentesx",
        "presentesx 10",
        "10 xpresentes",
        "xpresentes 10",
        "10xpresentes",
        "xpresentes10",
        "10ç presentes",
        "presentes 10é",
        "10_ presentes",
        "presentes _10",
    ],
)
def test_count_tokens_require_closed_unicode_word_boundaries(text: str) -> None:
    with pytest.raises(CellReportWorkflowError) as exc:
        parse_cell_report_candidate(text)
    assert exc.value.code is CellReportWorkflowErrorCode.INVALID_COUNT


@pytest.mark.parametrize(
    "text",
    [
        "oferta 10abc",
        "oferta10",
        "oferta abc10",
        "oferta 10ç",
        "oferta 10_",
        "oferta 10 reaisx",
        "oferta 10 reaisé",
        "R$ 10abc",
        "R$ 10 reaisx",
        "ofertax 10",
        "xoferta 10",
        "10xoferta",
        "xoferta10",
    ],
)
def test_offering_tokens_require_closed_unicode_word_boundaries(text: str) -> None:
    with pytest.raises(CellReportWorkflowError) as exc:
        parse_cell_report_candidate(text)
    assert exc.value.code is CellReportWorkflowErrorCode.INVALID_OFFERING


def test_closed_natural_language_money_suffix_remains_supported() -> None:
    assert parse_cell_report_candidate("oferta 10 reais").oferta == "10.00"
    assert parse_cell_report_candidate("oferta R$ 1.234,50").oferta == "1234.50"


def test_candidate_payload_is_closed_json_safe_and_has_no_decimal_or_float() -> None:
    candidate = _complete_workflow().candidate
    payload = cell_report_candidate_payload(candidate)
    assert payload == {
        "schema_version": "v1",
        "presentes": 12,
        "visitantes": 0,
        "decisoes": 2,
        "oferta": "1234.50",
        "observacoes": "Reunião tranquila",
    }
    _assert_no_float(payload)
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, CellReportWorkflowState.EMPTY),
        ("", CellReportWorkflowState.EMPTY),
        ("10 presentes", CellReportWorkflowState.COLLECTING),
        (
            "10 presentes, 0 visitantes, 0 decisões, oferta 0",
            CellReportWorkflowState.AWAITING_CONFIRMATION,
        ),
    ],
)
def test_initial_state_is_derived_from_candidate_completeness(
    text: str | None,
    expected: CellReportWorkflowState,
) -> None:
    workflow = start_cell_report_workflow_from_text(
        correlation_key=CORRELATION_KEY,
        text=text,
    )
    assert workflow.state is expected
    assert (workflow.confirmation_code is not None) is (
        expected is CellReportWorkflowState.AWAITING_CONFIRMATION
    )
    assert validate_cell_report_workflow(workflow) is workflow


@pytest.mark.parametrize("invalid_candidate", [False, 0, "", [], {}])
def test_start_rejects_every_non_none_falsy_candidate(
    invalid_candidate: object,
) -> None:
    with pytest.raises(CellReportWorkflowError) as exc:
        start_cell_report_workflow(
            correlation_key=CORRELATION_KEY,
            candidate=invalid_candidate,  # type: ignore[arg-type]
        )
    assert exc.value.code is CellReportWorkflowErrorCode.INVALID_CANDIDATE


def test_partial_corrections_merge_without_treating_zero_as_absent() -> None:
    workflow = start_cell_report_workflow_from_text(
        correlation_key=CORRELATION_KEY,
        text="10 presentes",
    )
    revised = revise_cell_report_workflow_from_text(
        workflow,
        "0 visitantes, 0 decisões, oferta R$ 0,00",
    )
    assert revised.revision == 2
    assert revised.candidate.presentes == 10
    assert revised.candidate.visitantes == 0
    assert revised.candidate.decisoes == 0
    assert revised.candidate.oferta == "0.00"
    assert revised.state is CellReportWorkflowState.AWAITING_CONFIRMATION


def test_merge_keeps_unmentioned_fields_and_overwrites_explicit_zero() -> None:
    current = build_cell_report_candidate(
        presentes=12,
        visitantes=2,
        decisoes=1,
        oferta="20.00",
    )
    patch = build_cell_report_candidate(visitantes=0)
    merged = merge_cell_report_candidates(current, patch)
    assert merged.presentes == 12
    assert merged.visitantes == 0
    assert merged.decisoes == 1
    assert merged.oferta == "20.00"


def test_correction_chains_revision_and_invalidates_previous_code() -> None:
    original = _complete_workflow()
    original_command = cell_report_confirmation_command(original)
    corrected = revise_cell_report_workflow_from_text(
        original,
        "correção: 13 presentes",
    )
    assert corrected.revision == original.revision + 1
    assert corrected.previous_proposal_digest == original.proposal_digest
    assert corrected.candidate_digest != original.candidate_digest
    assert corrected.proposal_digest != original.proposal_digest
    assert corrected.confirmation_code != original.confirmation_code
    assert corrected.state is CellReportWorkflowState.AWAITING_CONFIRMATION

    with pytest.raises(CellReportWorkflowError) as exc:
        correlate_cell_report_confirmation(corrected, original_command)
    assert exc.value.code is CellReportWorkflowErrorCode.CONFIRMATION_CODE_MISMATCH
    assert corrected.state is CellReportWorkflowState.AWAITING_CONFIRMATION


def test_even_identical_revision_gets_a_new_digest_and_code() -> None:
    original = _complete_workflow()
    revised = revise_cell_report_workflow(original, original.candidate)
    assert revised.candidate_digest == original.candidate_digest
    assert revised.proposal_digest != original.proposal_digest
    assert revised.confirmation_code != original.confirmation_code


def test_correction_after_confirmation_acceptance_is_blocked() -> None:
    original = _complete_workflow()
    accepted = correlate_cell_report_confirmation(
        original,
        cell_report_confirmation_command(original),
    )
    with pytest.raises(CellReportWorkflowError) as text_error:
        revise_cell_report_workflow_from_text(accepted, "13 presentes")
    assert text_error.value.code is (
        CellReportWorkflowErrorCode.INVALID_STATE_TRANSITION
    )

    replacement = build_cell_report_candidate(
        presentes=13,
        visitantes=0,
        decisoes=2,
        oferta="1234.50",
    )
    with pytest.raises(CellReportWorkflowError) as candidate_error:
        revise_cell_report_workflow(accepted, replacement)
    assert candidate_error.value.code is (
        CellReportWorkflowErrorCode.INVALID_STATE_TRANSITION
    )


def test_confirmation_grammar_is_literal_and_case_sensitive() -> None:
    workflow = _complete_workflow()
    command = cell_report_confirmation_command(workflow)
    assert command == f"{CONFIRMATION_COMMAND_PREFIX}{workflow.confirmation_code}"
    assert parse_cell_report_confirmation_command(command) == workflow.confirmation_code

    invalid_commands = (
        command.lower(),
        f" {command}",
        f"{command} ",
        command.replace(" ", "  ", 1),
        command.replace("RELATORIO", "RELATÓRIO"),
        "CONFIRMAR RELATORIO",
        "CONFIRMAR RELATORIO ABCD",
        "sim",
    )
    for invalid in invalid_commands:
        with pytest.raises(CellReportWorkflowError) as exc:
            parse_cell_report_confirmation_command(invalid)
        assert exc.value.code is CellReportWorkflowErrorCode.INVALID_CONFIRMATION_COMMAND


def test_confirmation_only_correlates_and_commit_is_a_separate_pure_transition() -> None:
    awaiting = _complete_workflow()
    accepted = correlate_cell_report_confirmation(
        awaiting,
        cell_report_confirmation_command(awaiting),
    )
    assert accepted.state is CellReportWorkflowState.CONFIRMATION_ACCEPTED
    assert accepted.accepted_proposal_digest == accepted.proposal_digest
    assert accepted.state is not CellReportWorkflowState.COMMITTED

    committed = mark_cell_report_committed(accepted)
    assert committed.state is CellReportWorkflowState.COMMITTED
    assert committed.proposal_digest == accepted.proposal_digest


def test_commit_without_current_confirmation_is_rejected() -> None:
    with pytest.raises(CellReportWorkflowError) as exc:
        mark_cell_report_committed(_complete_workflow())
    assert exc.value.code is CellReportWorkflowErrorCode.INVALID_STATE_TRANSITION


@pytest.mark.parametrize("terminal_state", sorted(EXPLICIT_TERMINAL_REPORT_STATES, key=str))
def test_cancel_expire_conflict_and_reject_are_pure_terminal_values(
    terminal_state: CellReportWorkflowState,
) -> None:
    terminal = terminalize_cell_report_workflow(_complete_workflow(), terminal_state)
    assert terminal.state is terminal_state
    assert validate_cell_report_workflow(terminal) is terminal
    with pytest.raises(CellReportWorkflowError) as exc:
        revise_cell_report_workflow_from_text(terminal, "13 presentes")
    assert exc.value.code is CellReportWorkflowErrorCode.INVALID_STATE_TRANSITION


def test_committed_is_terminal_and_cannot_be_revised_or_terminalized() -> None:
    awaiting = _complete_workflow()
    accepted = correlate_cell_report_confirmation(
        awaiting,
        cell_report_confirmation_command(awaiting),
    )
    committed = mark_cell_report_committed(accepted)
    with pytest.raises(CellReportWorkflowError):
        revise_cell_report_workflow_from_text(committed, "13 presentes")
    with pytest.raises(CellReportWorkflowError):
        terminalize_cell_report_workflow(
            committed,
            CellReportWorkflowState.CONFLICTED,
        )


def test_fixed_vector_freezes_cross_process_determinism() -> None:
    workflow = _complete_workflow()
    assert workflow.scope_digest == (
        "cell_report_scope_v1_"
        "ceff37a4a0c6334cb367c6942f579e7d2b2999f35db26dc288985257cd4d4463"
    )
    assert workflow.candidate_digest == (
        "cell_report_candidate_v1_"
        "263c4481a7e582f5dce15c5503d7d41f6806dc9faf8484435439ea66ff54d7dd"
    )
    assert workflow.proposal_digest == (
        "cell_report_proposal_v1_"
        "5bd62807702a4862e9b1a40a75910fde6086dea7b56212cf52d40e30a29c1262"
    )
    assert workflow.confirmation_code == "HYM77JEATP7L"


def test_same_vector_is_identical_in_fresh_processes_with_different_hash_seed() -> None:
    script = """
import json
from app.domain.cell_report_workflow import build_cell_report_candidate, start_cell_report_workflow
c = build_cell_report_candidate(presentes=12, visitantes=0, decisoes=2, oferta='1234.50', observacoes='Reunião tranquila')
w = start_cell_report_workflow(correlation_key='cell_report_scope_v1_' + ('a' * 64), candidate=c)
print(json.dumps([w.scope_digest, w.candidate_digest, w.proposal_digest, w.confirmation_code]))
"""
    outputs = []
    for seed in ("1", "987654"):
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=BACKEND_ROOT,
            env={
                "PYTHONPATH": str(BACKEND_ROOT),
                "PYTHONHASHSEED": seed,
                "PYTHONIOENCODING": "utf-8",
            },
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        outputs.append(completed.stdout)
    assert outputs[0] == outputs[1]


def test_scope_key_is_opaque_versioned_and_external_replay_boundary_is_explicit() -> None:
    first = _complete_workflow()
    same_scope_restart = _complete_workflow()
    other_scope = start_cell_report_workflow(
        correlation_key=OTHER_CORRELATION_KEY,
        candidate=first.candidate,
    )

    # Pure restart is deterministic. A trusted adapter must never reuse the
    # scope as an authorization or replay-prevention substitute.
    assert same_scope_restart.scope_digest == first.scope_digest
    assert same_scope_restart.proposal_digest == first.proposal_digest
    assert same_scope_restart.confirmation_code == first.confirmation_code

    assert other_scope.scope_digest != first.scope_digest
    assert other_scope.proposal_digest != first.proposal_digest
    assert other_scope.confirmation_code != first.confirmation_code


@pytest.mark.parametrize(
    "invalid_key",
    [
        "11111111-2222-3333-4444-555555555555",
        "pastoral.private@example.test",
        "agent_turn_v1_0123456789abcdef",
        CELL_REPORT_SCOPE_KEY_PREFIX + ("A" * 64),
        CELL_REPORT_SCOPE_KEY_PREFIX + ("g" * 64),
        CELL_REPORT_SCOPE_KEY_PREFIX + ("a" * 63),
        f" {CORRELATION_KEY}",
    ],
)
def test_scope_key_rejects_pii_and_noncanonical_grammar(invalid_key: str) -> None:
    with pytest.raises(CellReportWorkflowError) as exc:
        start_cell_report_workflow(correlation_key=invalid_key)
    assert exc.value.code is CellReportWorkflowErrorCode.INVALID_CORRELATION_KEY
    assert invalid_key not in str(exc.value)
    assert invalid_key not in repr(exc.value)


def test_unicode_normalization_produces_the_same_candidate_digest() -> None:
    composed = build_cell_report_candidate(
        presentes=1,
        visitantes=0,
        decisoes=0,
        oferta="0",
        observacoes="Reunião",
    )
    decomposed = build_cell_report_candidate(
        presentes=1,
        visitantes=0,
        decisoes=0,
        oferta="0",
        observacoes="Reunia\u0303o",
    )
    first = start_cell_report_workflow(
        correlation_key=CORRELATION_KEY,
        candidate=composed,
    )
    second = start_cell_report_workflow(
        correlation_key=CORRELATION_KEY,
        candidate=decomposed,
    )
    assert first.candidate == second.candidate
    assert first.candidate_digest == second.candidate_digest
    assert first.proposal_digest == second.proposal_digest


def test_repr_and_errors_never_expose_uuid_or_private_observations() -> None:
    secret_uuid = "11111111-2222-3333-4444-555555555555"
    private_text = "pastoral.private@example.test"
    candidate = build_cell_report_candidate(
        presentes=1,
        visitantes=0,
        decisoes=0,
        oferta="0",
        observacoes=private_text,
    )
    workflow = start_cell_report_workflow(
        correlation_key=CORRELATION_KEY,
        candidate=candidate,
    )
    assert secret_uuid not in repr(candidate)
    assert private_text not in repr(candidate)
    assert secret_uuid not in repr(workflow)
    assert private_text not in repr(workflow)

    with pytest.raises(CellReportWorkflowError) as exc:
        correlate_cell_report_confirmation(
            workflow,
            "CONFIRMAR RELATORIO AAAAAAAAAAAA",
        )
    rendered = f"{exc.value!s} {exc.value!r}"
    assert secret_uuid not in rendered
    assert private_text not in rendered
    assert workflow.confirmation_code not in rendered

    with pytest.raises(CellReportWorkflowError) as key_error:
        start_cell_report_workflow(correlation_key=secret_uuid)
    assert secret_uuid not in str(key_error.value)
    assert secret_uuid not in repr(key_error.value)


def test_large_inputs_fail_before_unicode_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden_normalize(*_args: object) -> str:
        nonlocal calls
        calls += 1
        raise AssertionError("normalization must not run")

    monkeypatch.setattr(
        contract,
        "unicodedata",
        types.SimpleNamespace(normalize=forbidden_normalize),
    )
    with pytest.raises(CellReportWorkflowError) as text_error:
        parse_cell_report_candidate("x" * (MAX_REPORT_TEXT_BYTES + 1))
    assert text_error.value.code is CellReportWorkflowErrorCode.TEXT_LIMIT_EXCEEDED

    with pytest.raises(CellReportWorkflowError) as observation_error:
        build_cell_report_candidate(
            observacoes="x" * (MAX_REPORT_OBSERVATIONS_BYTES + 1)
        )
    assert observation_error.value.code is (
        CellReportWorkflowErrorCode.OBSERVATIONS_LIMIT_EXCEEDED
    )
    assert calls == 0


def test_observations_share_the_human_2000_character_utf8_boundary() -> None:
    ascii_boundary = "x" * MAX_REPORT_OBSERVATIONS_LENGTH
    multibyte_boundary = "🙂" * MAX_REPORT_OBSERVATIONS_LENGTH

    assert (
        build_cell_report_candidate(observacoes=ascii_boundary).observacoes
        == ascii_boundary
    )
    assert (
        build_cell_report_candidate(observacoes=multibyte_boundary).observacoes
        == multibyte_boundary
    )
    assert len(multibyte_boundary.encode("utf-8")) == (
        MAX_REPORT_OBSERVATIONS_BYTES
    )

    for oversized in (
        "x" * (MAX_REPORT_OBSERVATIONS_LENGTH + 1),
        "🙂" * (MAX_REPORT_OBSERVATIONS_LENGTH + 1),
    ):
        with pytest.raises(CellReportWorkflowError) as exc_info:
            build_cell_report_candidate(observacoes=oversized)
        assert exc_info.value.code is (
            CellReportWorkflowErrorCode.OBSERVATIONS_LIMIT_EXCEEDED
        )


@pytest.mark.parametrize(
    "text",
    (
        "a" * MAX_REPORT_TEXT_BYTES,
        "1" * MAX_REPORT_TEXT_BYTES,
        "a1" * (MAX_REPORT_TEXT_BYTES // 2),
    ),
)
def test_maximum_bounded_adversarial_tokens_do_not_trigger_partial_matches(
    text: str,
) -> None:
    assert parse_cell_report_candidate(text).is_empty


def test_other_bounds_and_empty_revision_fail_closed() -> None:
    with pytest.raises(CellReportWorkflowError) as count_error:
        build_cell_report_candidate(presentes=MAX_REPORT_COUNT + 1)
    assert count_error.value.code is CellReportWorkflowErrorCode.COUNT_LIMIT_EXCEEDED

    with pytest.raises(CellReportWorkflowError) as parsed_count_error:
        parse_cell_report_candidate("10000000 presentes")
    assert parsed_count_error.value.code is (
        CellReportWorkflowErrorCode.COUNT_LIMIT_EXCEEDED
    )

    with pytest.raises(CellReportWorkflowError) as key_error:
        start_cell_report_workflow(
            correlation_key="x" * (MAX_REPORT_CORRELATION_KEY_BYTES + 1)
        )
    assert key_error.value.code is (
        CellReportWorkflowErrorCode.CORRELATION_KEY_LIMIT_EXCEEDED
    )

    with pytest.raises(CellReportWorkflowError) as money_error:
        build_cell_report_candidate(oferta=Decimal("1E+999999999"))
    assert money_error.value.code is CellReportWorkflowErrorCode.OFFERING_LIMIT_EXCEEDED

    with pytest.raises(CellReportWorkflowError) as revision_error:
        revise_cell_report_workflow_from_text(_complete_workflow(), "sem correção")
    assert revision_error.value.code is CellReportWorkflowErrorCode.EMPTY_REVISION


def test_structural_tampering_is_detected_with_sanitized_error() -> None:
    workflow = _complete_workflow()
    object.__setattr__(workflow, "proposal_digest", "forged")
    with pytest.raises(CellReportWorkflowError) as exc:
        validate_cell_report_workflow(workflow)
    assert exc.value.code is CellReportWorkflowErrorCode.INVALID_WORKFLOW
    assert "forged" not in str(exc.value)

    empty_shell = object.__new__(contract.CellReportWorkflow)
    with pytest.raises(CellReportWorkflowError) as shell_error:
        validate_cell_report_workflow(empty_shell)
    assert shell_error.value.code is CellReportWorkflowErrorCode.INVALID_WORKFLOW


def test_module_has_no_io_runtime_worker_or_callback_surface() -> None:
    source = Path(contract.__file__).read_text(encoding="utf-8")
    forbidden = (
        "sqlalchemy",
        "app.db",
        "app.agent",
        "app.workers",
        "requests",
        "httpx",
        "socket",
        "subprocess",
        "os.environ",
        "Callable",
    )
    lowered = source.lower()
    for token in forbidden:
        assert token.lower() not in lowered

    for value in vars(contract).values():
        if callable(value) and getattr(value, "__module__", None) == contract.__name__:
            parameters = getattr(value, "__annotations__", {})
            assert not any("callback" in name.lower() for name in parameters)
