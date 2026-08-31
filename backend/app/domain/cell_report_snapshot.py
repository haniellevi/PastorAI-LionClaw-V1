"""Pure contract for the aggregate ``cell-report/v2`` JSONB snapshot.

This module performs no I/O and carries no tenant or authorization context.
Those boundaries remain the responsibility of a future application service
before it may persist the returned JSON object.  The contract deliberately
stores only aggregate counts.  The legacy individual arrays are present and
must stay empty, so a WhatsApp aggregate can never invent people or leak
person-level facts into the canonical meeting snapshot.

``submission_effect_id`` and ``submission_payload_digest`` preserve the exact
planned effect identity and its canonical payload binding. Their public
grammars are validated so free text or PII cannot occupy either field, but
this module neither recomputes nor authenticates them. The pair is not tenant
identity, authorization proof, provenance or a global durable receipt.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Final

from app.domain.cell_report_limits import (
    MAX_CELL_REPORT_AGGREGATE_COUNT,
    MAX_CELL_REPORT_OBSERVATIONS_BYTES,
    MAX_CELL_REPORT_OBSERVATIONS_LENGTH,
    MAX_CELL_REPORT_OFFERING_DECIMAL_TEXT,
)

CELL_REPORT_SNAPSHOT_SCHEMA_V2: Final = "cell-report/v2"
MAX_CELL_REPORT_TOTAL: Final = MAX_CELL_REPORT_AGGREGATE_COUNT
MAX_CELL_REPORT_OBSERVACOES_LENGTH: Final = (
    MAX_CELL_REPORT_OBSERVATIONS_LENGTH
)
MAX_CELL_REPORT_OBSERVACOES_BYTES: Final = MAX_CELL_REPORT_OBSERVATIONS_BYTES
MAX_CELL_REPORT_OFFER: Final = Decimal(MAX_CELL_REPORT_OFFERING_DECIMAL_TEXT)
MAX_MONEY_INPUT_LENGTH: Final = 64

SUBMISSION_EFFECT_ID_PREFIX: Final = "agent_effect_v1_"
MAX_SUBMISSION_EFFECT_ID_BYTES: Final = len(SUBMISSION_EFFECT_ID_PREFIX) + 64
SUBMISSION_PAYLOAD_DIGEST_PREFIX: Final = "agent_payload_v1_"
MAX_SUBMISSION_PAYLOAD_DIGEST_BYTES: Final = (
    len(SUBMISSION_PAYLOAD_DIGEST_PREFIX) + 64
)

_CANONICAL_MONEY_RE: Final = re.compile(r"(?:0|[1-9][0-9]{0,5})\.[0-9]{2}\Z")
_SUBMISSION_EFFECT_ID_RE: Final = re.compile(
    rf"{re.escape(SUBMISSION_EFFECT_ID_PREFIX)}[0-9a-f]{{64}}\Z"
)
_SUBMISSION_PAYLOAD_DIGEST_RE: Final = re.compile(
    rf"{re.escape(SUBMISSION_PAYLOAD_DIGEST_PREFIX)}[0-9a-f]{{64}}\Z"
)
_TOTAL_KEYS: Final = frozenset({"presentes", "visitantes", "decisoes"})
_INDIVIDUAL_ARRAY_KEYS: Final = ("presencas", "visitantes", "records")
_SNAPSHOT_KEYS: Final = frozenset(
    {
        "schema",
        "totals",
        "oferta_valor",
        "observacoes",
        "submission_effect_id",
        "submission_payload_digest",
        *_INDIVIDUAL_ARRAY_KEYS,
    }
)


class CellReportSnapshotErrorCode(str, Enum):
    """Static fail-closed reasons that never echo snapshot content."""

    INVALID_SNAPSHOT = "INVALID_SNAPSHOT"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"
    INVALID_TOTALS = "INVALID_TOTALS"
    INVALID_TOTAL = "INVALID_TOTAL"
    INVALID_OFFER = "INVALID_OFFER"
    INVALID_OBSERVACOES = "INVALID_OBSERVACOES"
    INVALID_SUBMISSION_EFFECT_ID = "INVALID_SUBMISSION_EFFECT_ID"
    INVALID_SUBMISSION_PAYLOAD_DIGEST = (
        "INVALID_SUBMISSION_PAYLOAD_DIGEST"
    )
    INDIVIDUAL_DATA_FORBIDDEN = "INDIVIDUAL_DATA_FORBIDDEN"


class CellReportSnapshotValidationError(ValueError):
    """Reject malformed aggregate snapshots without exposing their values."""

    def __init__(self, code: CellReportSnapshotErrorCode) -> None:
        self.code = code
        super().__init__(f"cell report snapshot rejected: {code.value}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code.value!r})"


def _reject(code: CellReportSnapshotErrorCode) -> None:
    raise CellReportSnapshotValidationError(code)


def _require_total(value: object) -> int:
    if type(value) is not int or value < 0 or value > MAX_CELL_REPORT_TOTAL:
        _reject(CellReportSnapshotErrorCode.INVALID_TOTAL)
    return value


def _normalize_money(value: object) -> str | None:
    """Return fixed-point money for a builder input, never a JSON number."""

    if value is None:
        return None
    if type(value) not in (Decimal, str):
        _reject(CellReportSnapshotErrorCode.INVALID_OFFER)
    if type(value) is str and (
        not value
        or len(value) > MAX_MONEY_INPUT_LENGTH
        or value != value.strip()
    ):
        _reject(CellReportSnapshotErrorCode.INVALID_OFFER)
    try:
        parsed = value if type(value) is Decimal else Decimal(value)
    except (InvalidOperation, ValueError):
        _reject(CellReportSnapshotErrorCode.INVALID_OFFER)
    if (
        not parsed.is_finite()
        or parsed.is_signed()
        or parsed < 0
        or parsed > MAX_CELL_REPORT_OFFER
    ):
        _reject(CellReportSnapshotErrorCode.INVALID_OFFER)

    # ``Decimal.quantize`` and arithmetic use the process-global decimal
    # context.  Snapshot bytes must not change when another library mutates
    # precision, rounding or traps, so fixed-point rendering uses only the
    # exact coefficient/exponent tuple.
    if parsed == 0:
        return "0.00"
    sign, raw_digits, raw_exponent = parsed.as_tuple()
    if sign:
        _reject(CellReportSnapshotErrorCode.INVALID_OFFER)
    # A caller may hand us a pre-built ``Decimal`` with an arbitrarily large
    # coefficient even when its exponent makes the numeric value tiny.  Bound
    # the tuple before allocating a joined coefficient or invoking ``int``.
    if len(raw_digits) > MAX_MONEY_INPUT_LENGTH:
        _reject(CellReportSnapshotErrorCode.INVALID_OFFER)
    digits = list(raw_digits)
    exponent = raw_exponent
    while exponent < -2 and digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    if exponent < -2:
        _reject(CellReportSnapshotErrorCode.INVALID_OFFER)
    coefficient = int("".join(str(digit) for digit in digits))
    cents = coefficient * (10 ** (exponent + 2))
    whole, fraction = divmod(cents, 100)
    return f"{whole}.{fraction:02d}"


def _require_canonical_money(value: object) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not str or _CANONICAL_MONEY_RE.fullmatch(value) is None:
        _reject(CellReportSnapshotErrorCode.INVALID_OFFER)
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        _reject(CellReportSnapshotErrorCode.INVALID_OFFER)
    if parsed < 0 or parsed > MAX_CELL_REPORT_OFFER:
        _reject(CellReportSnapshotErrorCode.INVALID_OFFER)
    return parsed


def _normalize_observacoes(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        _reject(CellReportSnapshotErrorCode.INVALID_OBSERVACOES)
    if len(value) > MAX_CELL_REPORT_OBSERVACOES_LENGTH:
        _reject(CellReportSnapshotErrorCode.INVALID_OBSERVACOES)
    normalized = unicodedata.normalize(
        "NFC",
        value.replace("\r\n", "\n").replace("\r", "\n"),
    ).strip()
    if not normalized:
        return None
    return _require_canonical_observacoes(normalized)


def _require_canonical_observacoes(value: object) -> str | None:
    if value is None:
        return None
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_CELL_REPORT_OBSERVACOES_LENGTH
    ):
        _reject(CellReportSnapshotErrorCode.INVALID_OBSERVACOES)
    if value != value.strip():
        _reject(CellReportSnapshotErrorCode.INVALID_OBSERVACOES)
    if unicodedata.normalize("NFC", value) != value:
        _reject(CellReportSnapshotErrorCode.INVALID_OBSERVACOES)
    if any(
        not character.isprintable() and character not in "\n\t"
        for character in value
    ):
        _reject(CellReportSnapshotErrorCode.INVALID_OBSERVACOES)
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeEncodeError:
        _reject(CellReportSnapshotErrorCode.INVALID_OBSERVACOES)
    if len(encoded) > MAX_CELL_REPORT_OBSERVACOES_BYTES:
        _reject(CellReportSnapshotErrorCode.INVALID_OBSERVACOES)
    return value


def _require_submission_effect_id(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != MAX_SUBMISSION_EFFECT_ID_BYTES
        or _SUBMISSION_EFFECT_ID_RE.fullmatch(value) is None
    ):
        _reject(CellReportSnapshotErrorCode.INVALID_SUBMISSION_EFFECT_ID)
    return value


def _require_submission_payload_digest(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != MAX_SUBMISSION_PAYLOAD_DIGEST_BYTES
        or _SUBMISSION_PAYLOAD_DIGEST_RE.fullmatch(value) is None
    ):
        _reject(
            CellReportSnapshotErrorCode.INVALID_SUBMISSION_PAYLOAD_DIGEST
        )
    return value


@dataclass(frozen=True, slots=True, repr=False)
class CellReportTotals:
    """Validated aggregate counts, with no person-level material."""

    presentes: int
    visitantes: int
    decisoes: int

    def __post_init__(self) -> None:
        _require_total(self.presentes)
        _require_total(self.visitantes)
        _require_total(self.decisoes)

    def __repr__(self) -> str:
        return "CellReportTotals()"


@dataclass(frozen=True, slots=True, repr=False)
class CellReportSnapshotV2:
    """Typed validated view of one ``cell-report/v2`` JSONB value."""

    totals: CellReportTotals
    oferta_valor: Decimal | None = field(repr=False)
    observacoes: str | None = field(repr=False)
    submission_effect_id: str = field(repr=False)
    submission_payload_digest: str = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.totals) is not CellReportTotals:
            _reject(CellReportSnapshotErrorCode.INVALID_TOTALS)
        if (
            self.oferta_valor is not None
            and type(self.oferta_valor) is not Decimal
        ):
            _reject(CellReportSnapshotErrorCode.INVALID_OFFER)
        canonical_money = _normalize_money(self.oferta_valor)
        if canonical_money is not None and Decimal(canonical_money) != self.oferta_valor:
            _reject(CellReportSnapshotErrorCode.INVALID_OFFER)
        _require_canonical_observacoes(self.observacoes)
        _require_submission_effect_id(self.submission_effect_id)
        _require_submission_payload_digest(self.submission_payload_digest)

    def __repr__(self) -> str:
        return f"CellReportSnapshotV2(schema={CELL_REPORT_SNAPSHOT_SCHEMA_V2!r})"

    def to_jsonb(self) -> dict[str, object]:
        """Return a detached JSON object safe for a future JSONB writer."""

        if type(self.totals) is not CellReportTotals:
            _reject(CellReportSnapshotErrorCode.INVALID_TOTALS)
        presentes = _require_total(self.totals.presentes)
        visitantes = _require_total(self.totals.visitantes)
        decisoes = _require_total(self.totals.decisoes)
        if (
            self.oferta_valor is not None
            and type(self.oferta_valor) is not Decimal
        ):
            _reject(CellReportSnapshotErrorCode.INVALID_OFFER)
        oferta = _normalize_money(self.oferta_valor)
        observacoes = _require_canonical_observacoes(self.observacoes)
        submission_effect_id = _require_submission_effect_id(
            self.submission_effect_id
        )
        submission_payload_digest = _require_submission_payload_digest(
            self.submission_payload_digest
        )
        return {
            "schema": CELL_REPORT_SNAPSHOT_SCHEMA_V2,
            "totals": {
                "presentes": presentes,
                "visitantes": visitantes,
                "decisoes": decisoes,
            },
            "oferta_valor": oferta,
            "observacoes": observacoes,
            "submission_effect_id": submission_effect_id,
            "submission_payload_digest": submission_payload_digest,
            "presencas": [],
            "visitantes": [],
            "records": [],
        }


def build_cell_report_snapshot_v2(
    *,
    presentes: int,
    visitantes: int,
    decisoes: int,
    oferta_valor: Decimal | str | None,
    observacoes: str | None,
    submission_effect_id: str,
    submission_payload_digest: str,
) -> dict[str, object]:
    """Build the canonical aggregate JSONB shape without persisting it."""

    totals = CellReportTotals(
        presentes=_require_total(presentes),
        visitantes=_require_total(visitantes),
        decisoes=_require_total(decisoes),
    )
    oferta = _normalize_money(oferta_valor)
    snapshot = CellReportSnapshotV2(
        totals=totals,
        oferta_valor=Decimal(oferta) if oferta is not None else None,
        observacoes=_normalize_observacoes(observacoes),
        submission_effect_id=_require_submission_effect_id(submission_effect_id),
        submission_payload_digest=_require_submission_payload_digest(
            submission_payload_digest
        ),
    )
    return snapshot.to_jsonb()


def has_cell_report_snapshot_v2_marker(value: object) -> bool:
    """True only for an explicit v2 marker; it does not validate the payload."""

    return (
        type(value) is dict
        and value.get("schema") == CELL_REPORT_SNAPSHOT_SCHEMA_V2
    )


def has_cell_report_snapshot_schema_marker(value: object) -> bool:
    """True when a versioned snapshot declares any schema marker."""

    return type(value) is dict and "schema" in value


def validate_cell_report_snapshot_v2(value: object) -> CellReportSnapshotV2:
    """Validate an untrusted JSONB value and return its immutable typed view."""

    if type(value) is not dict:
        _reject(CellReportSnapshotErrorCode.INVALID_SNAPSHOT)
    if "schema" not in value:
        _reject(CellReportSnapshotErrorCode.INVALID_SNAPSHOT)
    if value["schema"] != CELL_REPORT_SNAPSHOT_SCHEMA_V2:
        _reject(CellReportSnapshotErrorCode.UNSUPPORTED_SCHEMA)
    if len(value) != len(_SNAPSHOT_KEYS) or value.keys() != _SNAPSHOT_KEYS:
        _reject(CellReportSnapshotErrorCode.INVALID_SNAPSHOT)

    totals_value = value.get("totals")
    if type(totals_value) is not dict:
        _reject(CellReportSnapshotErrorCode.INVALID_TOTALS)
    if (
        len(totals_value) != len(_TOTAL_KEYS)
        or totals_value.keys() != _TOTAL_KEYS
    ):
        _reject(CellReportSnapshotErrorCode.INVALID_TOTALS)

    for key in _INDIVIDUAL_ARRAY_KEYS:
        individual = value.get(key)
        if type(individual) is not list or individual:
            _reject(CellReportSnapshotErrorCode.INDIVIDUAL_DATA_FORBIDDEN)

    return CellReportSnapshotV2(
        totals=CellReportTotals(
            presentes=_require_total(totals_value.get("presentes")),
            visitantes=_require_total(totals_value.get("visitantes")),
            decisoes=_require_total(totals_value.get("decisoes")),
        ),
        oferta_valor=_require_canonical_money(value.get("oferta_valor")),
        observacoes=_require_canonical_observacoes(value.get("observacoes")),
        submission_effect_id=_require_submission_effect_id(
            value.get("submission_effect_id")
        ),
        submission_payload_digest=_require_submission_payload_digest(
            value.get("submission_payload_digest")
        ),
    )


__all__ = [
    "CELL_REPORT_SNAPSHOT_SCHEMA_V2",
    "CellReportSnapshotErrorCode",
    "CellReportSnapshotV2",
    "CellReportSnapshotValidationError",
    "CellReportTotals",
    "build_cell_report_snapshot_v2",
    "has_cell_report_snapshot_schema_marker",
    "has_cell_report_snapshot_v2_marker",
    "validate_cell_report_snapshot_v2",
]
