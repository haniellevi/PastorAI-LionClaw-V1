"""Offline contract tests for the aggregate ``cell-report/v2`` snapshot."""

from __future__ import annotations

import inspect
import json
import tracemalloc
from decimal import Decimal, Inexact, ROUND_UP, Rounded, localcontext

import pytest

from app.domain.cell_report_snapshot import (
    CELL_REPORT_SNAPSHOT_SCHEMA_V2,
    MAX_CELL_REPORT_OBSERVACOES_BYTES,
    MAX_CELL_REPORT_TOTAL,
    CellReportSnapshotErrorCode,
    CellReportSnapshotValidationError,
    build_cell_report_snapshot_v2,
    has_cell_report_snapshot_schema_marker,
    has_cell_report_snapshot_v2_marker,
    validate_cell_report_snapshot_v2,
)

_EFFECT_ID = "agent_effect_v1_" + ("a" * 64)


def _snapshot(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "presentes": 12,
        "visitantes": 3,
        "decisoes": 1,
        "oferta_valor": Decimal("150.50"),
        "observacoes": "Reunião concluída.",
        "submission_effect_id": _EFFECT_ID,
    }
    values.update(overrides)
    return build_cell_report_snapshot_v2(**values)  # type: ignore[arg-type]


def _assert_code(code: CellReportSnapshotErrorCode, fn) -> None:
    with pytest.raises(CellReportSnapshotValidationError) as exc_info:
        fn()
    assert exc_info.value.code is code
    assert str(exc_info.value) == f"cell report snapshot rejected: {code.value}"


def test_builder_emits_exact_jsonb_shape_without_individual_people() -> None:
    snapshot = _snapshot()

    assert snapshot == {
        "schema": CELL_REPORT_SNAPSHOT_SCHEMA_V2,
        "totals": {"presentes": 12, "visitantes": 3, "decisoes": 1},
        "oferta_valor": "150.50",
        "observacoes": "Reunião concluída.",
        "submission_effect_id": _EFFECT_ID,
        "presencas": [],
        "visitantes": [],
        "records": [],
    }
    assert "pessoa" not in json.dumps(snapshot, ensure_ascii=False).lower()
    assert json.loads(json.dumps(snapshot, ensure_ascii=False)) == snapshot


def test_builder_normalizes_money_and_optional_observacoes() -> None:
    snapshot = _snapshot(
        oferta_valor="001.2",
        observacoes="  encontro tranquilo  ",
    )
    assert snapshot["oferta_valor"] == "1.20"
    assert snapshot["observacoes"] == "encontro tranquilo"

    empty = _snapshot(
        oferta_valor=Decimal("-0.00"),
        observacoes=" \n ",
    )
    assert empty["oferta_valor"] == "0.00"
    assert empty["observacoes"] is None


def test_money_bytes_ignore_mutated_process_decimal_context() -> None:
    expected = _snapshot(oferta_valor=Decimal("150.50"))["oferta_valor"]

    with localcontext() as context:
        context.prec = 1
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        assert _snapshot(oferta_valor=Decimal("150.5000"))["oferta_valor"] == expected
        assert _snapshot(oferta_valor="1e2")["oferta_valor"] == "100.00"


def test_money_rejects_oversized_text_before_decimal_parsing() -> None:
    _assert_code(
        CellReportSnapshotErrorCode.INVALID_OFFER,
        lambda: _snapshot(oferta_valor="1" * 10_000),
    )


def test_money_rejects_oversized_prebuilt_decimal_coefficient() -> None:
    pathological = Decimal((0, (1,) + ((0,) * 10_000), -10_000))

    _assert_code(
        CellReportSnapshotErrorCode.INVALID_OFFER,
        lambda: _snapshot(oferta_valor=pathological),
    )


def test_money_matches_numeric_12_2_database_boundary() -> None:
    assert (
        _snapshot(oferta_valor="999999.99")["oferta_valor"]
        == "999999.99"
    )
    _assert_code(
        CellReportSnapshotErrorCode.INVALID_OFFER,
        lambda: _snapshot(oferta_valor="1000000.00"),
    )


@pytest.mark.parametrize(
    "value",
    [
        10.5,
        1,
        True,
        Decimal("1.001"),
        Decimal("-0.01"),
        Decimal("1000000.00"),
        Decimal("NaN"),
        Decimal("Infinity"),
        "not-money",
    ],
)
def test_builder_rejects_unsafe_offer_input(value: object) -> None:
    _assert_code(
        CellReportSnapshotErrorCode.INVALID_OFFER,
        lambda: _snapshot(oferta_valor=value),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("presentes", -1),
        ("presentes", True),
        ("visitantes", 1.0),
        ("decisoes", MAX_CELL_REPORT_TOTAL + 1),
    ],
)
def test_builder_rejects_noncanonical_totals(field: str, value: object) -> None:
    _assert_code(
        CellReportSnapshotErrorCode.INVALID_TOTAL,
        lambda: _snapshot(**{field: value}),
    )


def test_validator_returns_immutable_typed_aggregate() -> None:
    parsed = validate_cell_report_snapshot_v2(_snapshot())

    assert parsed.totals.presentes == 12
    assert parsed.totals.visitantes == 3
    assert parsed.totals.decisoes == 1
    assert parsed.oferta_valor == Decimal("150.50")
    assert parsed.observacoes == "Reunião concluída."
    assert parsed.submission_effect_id == _EFFECT_ID

    with pytest.raises((AttributeError, TypeError)):
        parsed.totals.presentes = 99  # type: ignore[misc]


def test_typed_view_serializes_to_a_detached_json_object() -> None:
    parsed = validate_cell_report_snapshot_v2(_snapshot())
    first = parsed.to_jsonb()
    second = parsed.to_jsonb()

    assert first == second
    assert first is not second
    assert first["totals"] is not second["totals"]
    assert first["presencas"] is not second["presencas"]

    first["presencas"].append({"pessoa_id": "forged"})  # type: ignore[union-attr]
    assert second["presencas"] == []
    assert parsed.to_jsonb()["presencas"] == []


@pytest.mark.parametrize("array_key", ["presencas", "visitantes", "records"])
def test_validator_rejects_any_individual_array_material(array_key: str) -> None:
    snapshot = _snapshot()
    snapshot[array_key] = [{"nome": "Pessoa inventada"}]

    _assert_code(
        CellReportSnapshotErrorCode.INDIVIDUAL_DATA_FORBIDDEN,
        lambda: validate_cell_report_snapshot_v2(snapshot),
    )


@pytest.mark.parametrize("array_key", ["presencas", "visitantes", "records"])
def test_validator_requires_plain_empty_lists(array_key: str) -> None:
    snapshot = _snapshot()
    snapshot[array_key] = ()

    _assert_code(
        CellReportSnapshotErrorCode.INDIVIDUAL_DATA_FORBIDDEN,
        lambda: validate_cell_report_snapshot_v2(snapshot),
    )


def test_validator_is_exact_about_schema_and_top_level_keys() -> None:
    wrong_schema = _snapshot()
    wrong_schema["schema"] = "cell-report/v3"
    _assert_code(
        CellReportSnapshotErrorCode.UNSUPPORTED_SCHEMA,
        lambda: validate_cell_report_snapshot_v2(wrong_schema),
    )

    extra = _snapshot()
    extra["pessoas"] = []
    _assert_code(
        CellReportSnapshotErrorCode.INVALID_SNAPSHOT,
        lambda: validate_cell_report_snapshot_v2(extra),
    )

    missing = _snapshot()
    missing.pop("records")
    _assert_code(
        CellReportSnapshotErrorCode.INVALID_SNAPSHOT,
        lambda: validate_cell_report_snapshot_v2(missing),
    )


def test_validator_is_exact_about_totals_and_canonical_money() -> None:
    extra_total = _snapshot()
    extra_total["totals"]["membros"] = 20  # type: ignore[index]
    _assert_code(
        CellReportSnapshotErrorCode.INVALID_TOTALS,
        lambda: validate_cell_report_snapshot_v2(extra_total),
    )

    for money in ("1", "01.00", "1.0", "1.000", 1, 1.0):
        forged = _snapshot()
        forged["oferta_valor"] = money
        _assert_code(
            CellReportSnapshotErrorCode.INVALID_OFFER,
            lambda forged=forged: validate_cell_report_snapshot_v2(forged),
        )


def test_submission_effect_id_requires_the_public_content_free_grammar() -> None:
    parsed = validate_cell_report_snapshot_v2(_snapshot())
    assert parsed.submission_effect_id == _EFFECT_ID

    invalid_values = (
        "",
        "future-format:not-a-uuid/123",
        "agent_effect_v1_" + ("A" * 64),
        "agent_effect_v1_" + ("g" * 64),
        "agent_effect_v1_" + ("a" * 63),
        "agent_effect_v1_" + ("a" * 65),
        " " * 1_000_000,
        "\ud800",
    )
    for value in invalid_values:
        _assert_code(
            CellReportSnapshotErrorCode.INVALID_SUBMISSION_EFFECT_ID,
            lambda value=value: _snapshot(submission_effect_id=value),
        )


def test_observacoes_are_bounded_normalized_utf8_text() -> None:
    accepted = _snapshot(observacoes="  Reunia\u0303o\r\nlinha 2\r  ")
    assert accepted["observacoes"] == "Reunião\nlinha 2"

    controls = ("pastor\x00dados", "pastor\x1bdados", "pastor\u202edados")
    for value in controls:
        _assert_code(
            CellReportSnapshotErrorCode.INVALID_OBSERVACOES,
            lambda value=value: _snapshot(observacoes=value),
        )

    for value in (
        "x" * 2001,
        "🙂" * ((MAX_CELL_REPORT_OBSERVACOES_BYTES // 4) + 1),
        " " * 1_000_000,
        "\ud800",
    ):
        _assert_code(
            CellReportSnapshotErrorCode.INVALID_OBSERVACOES,
            lambda value=value: _snapshot(observacoes=value),
        )

    forged = _snapshot()
    forged["observacoes"] = " trailing "
    _assert_code(
        CellReportSnapshotErrorCode.INVALID_OBSERVACOES,
        lambda: validate_cell_report_snapshot_v2(forged),
    )

    for noncanonical in ("Reunia\u0303o", "linha 1\r\nlinha 2", *controls):
        forged = _snapshot()
        forged["observacoes"] = noncanonical
        _assert_code(
            CellReportSnapshotErrorCode.INVALID_OBSERVACOES,
            lambda forged=forged: validate_cell_report_snapshot_v2(forged),
        )


def test_oversized_collections_fail_without_proportional_validation_copy() -> None:
    huge_top_level = {"schema": CELL_REPORT_SNAPSHOT_SCHEMA_V2}
    huge_top_level.update({f"extra-{index}": None for index in range(200_000)})

    huge_totals = _snapshot()
    huge_totals["totals"] = {
        f"extra-{index}": index for index in range(200_000)
    }

    huge_array = _snapshot()
    huge_array["presencas"] = [None] * 200_000

    cases = (
        (huge_top_level, CellReportSnapshotErrorCode.INVALID_SNAPSHOT),
        (huge_totals, CellReportSnapshotErrorCode.INVALID_TOTALS),
        (huge_array, CellReportSnapshotErrorCode.INDIVIDUAL_DATA_FORBIDDEN),
    )
    for payload, expected_code in cases:
        tracemalloc.start()
        _assert_code(
            expected_code,
            lambda payload=payload: validate_cell_report_snapshot_v2(payload),
        )
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert peak < 1_000_000


def test_marker_detection_never_mistakes_legacy_for_v2() -> None:
    legacy = {
        "presencas": [],
        "visitantes": [],
        "records": [],
        "oferta_valor": 10.0,
    }
    assert has_cell_report_snapshot_v2_marker(legacy) is False
    assert has_cell_report_snapshot_schema_marker(legacy) is False
    assert has_cell_report_snapshot_v2_marker(_snapshot()) is True
    assert has_cell_report_snapshot_schema_marker(_snapshot()) is True

    malformed_v2 = {"schema": CELL_REPORT_SNAPSHOT_SCHEMA_V2}
    assert has_cell_report_snapshot_v2_marker(malformed_v2) is True
    _assert_code(
        CellReportSnapshotErrorCode.INVALID_SNAPSHOT,
        lambda: validate_cell_report_snapshot_v2(malformed_v2),
    )


def test_unknown_version_is_explicitly_unsupported() -> None:
    future = _snapshot()
    future["schema"] = "cell-report/v3"

    assert has_cell_report_snapshot_v2_marker(future) is False
    assert has_cell_report_snapshot_schema_marker(future) is True
    _assert_code(
        CellReportSnapshotErrorCode.UNSUPPORTED_SCHEMA,
        lambda: validate_cell_report_snapshot_v2(future),
    )

    sparse_future = {"schema": "cell-report/v3"}
    _assert_code(
        CellReportSnapshotErrorCode.UNSUPPORTED_SCHEMA,
        lambda: validate_cell_report_snapshot_v2(sparse_future),
    )


def test_error_and_snapshot_repr_do_not_expose_sensitive_text() -> None:
    secret_effect = "agent_effect_v1_" + ("b" * 64)
    secret_notes = "pastoral text must not appear"
    parsed = validate_cell_report_snapshot_v2(
        _snapshot(
            submission_effect_id=secret_effect,
            observacoes=secret_notes,
        )
    )
    assert secret_effect not in repr(parsed)
    assert secret_notes not in repr(parsed)

    try:
        _snapshot(submission_effect_id="bad\nvalue")
    except CellReportSnapshotValidationError as exc:
        assert "bad" not in str(exc)
        assert "bad" not in repr(exc)
    else:  # pragma: no cover
        raise AssertionError("expected validation error")


def test_repr_stays_static_after_low_level_field_forgery() -> None:
    parsed = validate_cell_report_snapshot_v2(_snapshot())
    object.__setattr__(parsed.totals, "presentes", "forged-private-value")
    object.__setattr__(parsed, "submission_effect_id", "forged-effect-value")

    assert "forged" not in repr(parsed)
    assert "forged" not in repr(parsed.totals)


def test_serializer_revalidates_low_level_field_forgery() -> None:
    forged_total = validate_cell_report_snapshot_v2(_snapshot())
    object.__setattr__(forged_total.totals, "presentes", True)
    _assert_code(
        CellReportSnapshotErrorCode.INVALID_TOTAL,
        forged_total.to_jsonb,
    )

    forged_effect = validate_cell_report_snapshot_v2(_snapshot())
    object.__setattr__(forged_effect, "submission_effect_id", "free text")
    _assert_code(
        CellReportSnapshotErrorCode.INVALID_SUBMISSION_EFFECT_ID,
        forged_effect.to_jsonb,
    )

    forged_offer = validate_cell_report_snapshot_v2(_snapshot())
    object.__setattr__(forged_offer, "oferta_valor", "1.20")
    _assert_code(
        CellReportSnapshotErrorCode.INVALID_OFFER,
        forged_offer.to_jsonb,
    )


def test_builder_contract_has_no_tenant_rbac_or_io_parameters() -> None:
    assert tuple(inspect.signature(build_cell_report_snapshot_v2).parameters) == (
        "presentes",
        "visitantes",
        "decisoes",
        "oferta_valor",
        "observacoes",
        "submission_effect_id",
    )
