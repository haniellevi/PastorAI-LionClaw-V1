"""Pure offline contract for a WhatsApp cell-report proposal.

This module parses a bounded text into a typed, partial candidate and models
proposal, revision, literal confirmation correlation, and terminal outcomes as
immutable values.  It performs no I/O, accepts no callback, imports no runtime
or persistence code, and is not wired to the agent, worker, database, or
transport.

The confirmation code only correlates a literal command with the current
proposal revision.  It is not authentication, tenant authority, capability,
consent, proof of commit, or permission to execute an effect.  A future trusted
adapter must revalidate all of those facts and persist the canonical report in
one reviewed transaction.

The legacy extractor in :mod:`app.domain.report` intentionally remains
unchanged.  Its ``CellReport.oferta`` is a float consumed by the current
stateless graph.  Values in this workflow contract never contain a float:
offering amounts are validated with :class:`~decimal.Decimal` and stored as a
canonical two-decimal string.

Custom ``repr`` and static error codes reduce accidental disclosure.  The
candidate can still contain private observations, so callers must never log or
blindly serialize its attributes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Final


CELL_REPORT_CANDIDATE_SCHEMA_VERSION: Final = "v1"
CELL_REPORT_WORKFLOW_SCHEMA_VERSION: Final = "v1"
CELL_REPORT_CONFIRMATION_GRAMMAR_VERSION: Final = "v1"

MAX_REPORT_TEXT_BYTES: Final = 16_384
MAX_REPORT_OBSERVATIONS_BYTES: Final = 2_048
MAX_REPORT_CORRELATION_KEY_BYTES: Final = 512
MAX_REPORT_COUNT: Final = 1_000_000
MAX_REPORT_REVISION: Final = 1_000_000
MAX_REPORT_MONEY_TOKEN_BYTES: Final = 32
MAX_REPORT_DECIMAL_DIGITS: Final = 32
# Mirrors ``celula_reuniao.oferta_valor numeric(12, 2)`` without consulting a
# live database: ten integer digits and two fractional digits.
MAX_REPORT_OFFERING_CENTS: Final = 999_999_999_999
CONFIRMATION_CODE_LENGTH: Final = 12
CONFIRMATION_COMMAND_PREFIX: Final = "CONFIRMAR RELATORIO "
CELL_REPORT_SCOPE_KEY_PREFIX: Final = (
    f"cell_report_scope_{CELL_REPORT_WORKFLOW_SCHEMA_VERSION}_"
)
CELL_REPORT_SCOPE_KEY_LENGTH: Final = len(CELL_REPORT_SCOPE_KEY_PREFIX) + 64

_CANDIDATE_DIGEST_PREFIX: Final = (
    f"cell_report_candidate_{CELL_REPORT_CANDIDATE_SCHEMA_VERSION}_"
)
_SCOPE_DIGEST_PREFIX: Final = (
    f"cell_report_scope_{CELL_REPORT_WORKFLOW_SCHEMA_VERSION}_"
)
_PROPOSAL_DIGEST_PREFIX: Final = (
    f"cell_report_proposal_{CELL_REPORT_WORKFLOW_SCHEMA_VERSION}_"
)

_SCOPE_DOMAIN: Final = b"pastorai.cell-report.scope"
_CANDIDATE_DOMAIN: Final = b"pastorai.cell-report.candidate"
_PROPOSAL_DOMAIN: Final = b"pastorai.cell-report.proposal"
_CONFIRMATION_DOMAIN: Final = b"pastorai.cell-report.confirmation"

_REQUIRED_FIELDS: Final = (
    "presentes",
    "visitantes",
    "decisoes",
    "oferta",
)


class CellReportWorkflowState(str, Enum):
    """Closed state vocabulary for the pure report workflow."""

    EMPTY = "EMPTY"
    COLLECTING = "COLLECTING"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    CONFIRMATION_ACCEPTED = "CONFIRMATION_ACCEPTED"
    COMMITTED = "COMMITTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    CONFLICTED = "CONFLICTED"
    REJECTED = "REJECTED"


TERMINAL_REPORT_STATES: Final = frozenset(
    {
        CellReportWorkflowState.COMMITTED,
        CellReportWorkflowState.CANCELLED,
        CellReportWorkflowState.EXPIRED,
        CellReportWorkflowState.CONFLICTED,
        CellReportWorkflowState.REJECTED,
    }
)

EXPLICIT_TERMINAL_REPORT_STATES: Final = frozenset(
    {
        CellReportWorkflowState.CANCELLED,
        CellReportWorkflowState.EXPIRED,
        CellReportWorkflowState.CONFLICTED,
        CellReportWorkflowState.REJECTED,
    }
)

REVISION_ALLOWED_REPORT_STATES: Final = frozenset(
    {
        CellReportWorkflowState.EMPTY,
        CellReportWorkflowState.COLLECTING,
        CellReportWorkflowState.AWAITING_CONFIRMATION,
    }
)


class CellReportWorkflowErrorCode(str, Enum):
    """Sanitized rejection reasons that never include caller material."""

    INVALID_TEXT = "INVALID_TEXT"
    TEXT_LIMIT_EXCEEDED = "TEXT_LIMIT_EXCEEDED"
    INVALID_COUNT = "INVALID_COUNT"
    COUNT_LIMIT_EXCEEDED = "COUNT_LIMIT_EXCEEDED"
    CONFLICTING_FIELD_VALUES = "CONFLICTING_FIELD_VALUES"
    INVALID_OFFERING = "INVALID_OFFERING"
    OFFERING_LIMIT_EXCEEDED = "OFFERING_LIMIT_EXCEEDED"
    INVALID_OBSERVATIONS = "INVALID_OBSERVATIONS"
    OBSERVATIONS_LIMIT_EXCEEDED = "OBSERVATIONS_LIMIT_EXCEEDED"
    INVALID_CORRELATION_KEY = "INVALID_CORRELATION_KEY"
    CORRELATION_KEY_LIMIT_EXCEEDED = "CORRELATION_KEY_LIMIT_EXCEEDED"
    INVALID_CANDIDATE = "INVALID_CANDIDATE"
    INVALID_WORKFLOW = "INVALID_WORKFLOW"
    REVISION_LIMIT_EXCEEDED = "REVISION_LIMIT_EXCEEDED"
    EMPTY_REVISION = "EMPTY_REVISION"
    INVALID_CONFIRMATION_COMMAND = "INVALID_CONFIRMATION_COMMAND"
    CONFIRMATION_CODE_MISMATCH = "CONFIRMATION_CODE_MISMATCH"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"


class CellReportWorkflowError(ValueError):
    """Fail-closed error whose string and repr expose one static code only."""

    def __init__(self, code: CellReportWorkflowErrorCode) -> None:
        self.code = code
        super().__init__(f"cell report workflow rejected: {code.value}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code.value!r})"


def _raise(code: CellReportWorkflowErrorCode) -> None:
    raise CellReportWorkflowError(code)


def _binary_frame(*parts: bytes) -> bytes:
    if any(type(part) is not bytes for part in parts):
        raise TypeError("binary frame requires bytes")
    framed = bytearray(len(parts).to_bytes(4, "big"))
    for part in parts:
        framed.extend(len(part).to_bytes(4, "big"))
        framed.extend(part)
    return bytes(framed)


def _utf8_bytes(
    value: str,
    *,
    invalid: CellReportWorkflowErrorCode,
) -> bytes:
    try:
        return value.encode("utf-8", "strict")
    except UnicodeEncodeError:
        _raise(invalid)


def _normalized_text(value: object) -> str:
    if value is None:
        return ""
    if type(value) is not str:
        _raise(CellReportWorkflowErrorCode.INVALID_TEXT)
    if len(value) > MAX_REPORT_TEXT_BYTES:
        _raise(CellReportWorkflowErrorCode.TEXT_LIMIT_EXCEEDED)
    normalized = unicodedata.normalize(
        "NFC",
        value.replace("\r\n", "\n").replace("\r", "\n"),
    )
    if any(
        unicodedata.category(character)[0] in {"C", "M"}
        and character not in "\n\t"
        for character in normalized
    ):
        _raise(CellReportWorkflowErrorCode.INVALID_TEXT)
    encoded = _utf8_bytes(
        normalized,
        invalid=CellReportWorkflowErrorCode.INVALID_TEXT,
    )
    if len(encoded) > MAX_REPORT_TEXT_BYTES:
        _raise(CellReportWorkflowErrorCode.TEXT_LIMIT_EXCEEDED)
    return normalized


def _normalized_count(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        _raise(CellReportWorkflowErrorCode.INVALID_COUNT)
    if value > MAX_REPORT_COUNT:
        _raise(CellReportWorkflowErrorCode.COUNT_LIMIT_EXCEEDED)
    return value


def _normalize_observations(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        _raise(CellReportWorkflowErrorCode.INVALID_OBSERVATIONS)
    if len(value) > MAX_REPORT_OBSERVATIONS_BYTES:
        _raise(CellReportWorkflowErrorCode.OBSERVATIONS_LIMIT_EXCEEDED)
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        return None
    if any(not character.isprintable() and character not in "\n\t" for character in normalized):
        _raise(CellReportWorkflowErrorCode.INVALID_OBSERVATIONS)
    encoded = _utf8_bytes(
        normalized,
        invalid=CellReportWorkflowErrorCode.INVALID_OBSERVATIONS,
    )
    if len(encoded) > MAX_REPORT_OBSERVATIONS_BYTES:
        _raise(CellReportWorkflowErrorCode.OBSERVATIONS_LIMIT_EXCEEDED)
    return normalized


def _decimal_from_money_string(value: str) -> Decimal:
    if len(value) > MAX_REPORT_MONEY_TOKEN_BYTES:
        _raise(CellReportWorkflowErrorCode.OFFERING_LIMIT_EXCEEDED)
    if not value or value != value.strip():
        _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)
    encoded = _utf8_bytes(
        value,
        invalid=CellReportWorkflowErrorCode.INVALID_OFFERING,
    )
    if len(encoded) > MAX_REPORT_MONEY_TOKEN_BYTES:
        _raise(CellReportWorkflowErrorCode.OFFERING_LIMIT_EXCEEDED)
    if not re.fullmatch(r"[0-9][0-9.,]*", value, flags=re.ASCII):
        _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)

    normalized: str
    if "," in value:
        if value.count(",") != 1:
            _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)
        integer, fraction = value.split(",", 1)
        if len(fraction) not in {1, 2} or not fraction.isascii() or not fraction.isdigit():
            _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)
        if "." in integer:
            groups = integer.split(".")
            if (
                not groups[0]
                or len(groups[0]) > 3
                or any(len(group) != 3 for group in groups[1:])
                or any(not group.isascii() or not group.isdigit() for group in groups)
            ):
                _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)
            integer = "".join(groups)
        normalized = f"{integer}.{fraction}"
    elif "." in value:
        groups = value.split(".")
        if len(groups) == 2 and len(groups[1]) in {1, 2}:
            if any(not group.isascii() or not group.isdigit() for group in groups):
                _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)
            normalized = value
        else:
            if (
                not groups[0]
                or len(groups[0]) > 3
                or any(len(group) != 3 for group in groups[1:])
                or any(not group.isascii() or not group.isdigit() for group in groups)
            ):
                _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)
            normalized = "".join(groups)
    else:
        normalized = value

    try:
        return Decimal(normalized)
    except InvalidOperation:
        _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)


def _canonical_offering(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is Decimal:
        amount = value
    elif type(value) is str:
        if len(value) > MAX_REPORT_MONEY_TOKEN_BYTES:
            _raise(CellReportWorkflowErrorCode.OFFERING_LIMIT_EXCEEDED)
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value, flags=re.ASCII):
            _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)
        try:
            amount = Decimal(value)
        except InvalidOperation:
            _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)
    else:
        _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)

    if not amount.is_finite() or amount.is_signed():
        _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)
    if amount.is_zero():
        return "0.00"

    sign, digits, exponent = amount.as_tuple()
    if sign or len(digits) > MAX_REPORT_DECIMAL_DIGITS:
        _raise(CellReportWorkflowErrorCode.OFFERING_LIMIT_EXCEEDED)
    coefficient = int("".join(str(digit) for digit in digits))
    if exponent >= 0:
        if exponent > MAX_REPORT_DECIMAL_DIGITS:
            _raise(CellReportWorkflowErrorCode.OFFERING_LIMIT_EXCEEDED)
        cents = coefficient * (10 ** (exponent + 2))
    else:
        scale = -exponent
        if scale <= 2:
            cents = coefficient * (10 ** (2 - scale))
        else:
            discarded_places = scale - 2
            if discarded_places >= len(digits):
                _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)
            discarded = digits[-discarded_places:]
            if any(discarded):
                _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)
            cents = coefficient // (10**discarded_places)
    if cents > MAX_REPORT_OFFERING_CENTS:
        _raise(CellReportWorkflowErrorCode.OFFERING_LIMIT_EXCEEDED)
    if cents < 0:
        _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)
    return f"{cents // 100}.{cents % 100:02d}"


def _canonical_report_offering(value: object) -> str | None:
    if type(value) is not str:
        _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)
    return _canonical_offering(_decimal_from_money_string(value))


@dataclass(frozen=True, slots=True, repr=False, init=False)
class CellReportCandidate:
    """Immutable partial candidate with a JSON-safe canonical money string."""

    presentes: int | None
    visitantes: int | None
    decisoes: int | None
    oferta: str | None
    observacoes: str | None

    def __repr__(self) -> str:
        return "CellReportCandidate(<redacted>)"

    @property
    def is_empty(self) -> bool:
        return all(
            value is None
            for value in (
                self.presentes,
                self.visitantes,
                self.decisoes,
                self.oferta,
                self.observacoes,
            )
        )

    @property
    def missing_required_fields(self) -> tuple[str, ...]:
        return tuple(
            field_name
            for field_name in _REQUIRED_FIELDS
            if getattr(self, field_name) is None
        )

    @property
    def is_complete(self) -> bool:
        return not self.missing_required_fields


def build_cell_report_candidate(
    *,
    presentes: int | None = None,
    visitantes: int | None = None,
    decisoes: int | None = None,
    oferta: Decimal | str | None = None,
    observacoes: str | None = None,
) -> CellReportCandidate:
    """Build a validated candidate without admitting a float at any boundary."""

    candidate = object.__new__(CellReportCandidate)
    object.__setattr__(candidate, "presentes", _normalized_count(presentes))
    object.__setattr__(candidate, "visitantes", _normalized_count(visitantes))
    object.__setattr__(candidate, "decisoes", _normalized_count(decisoes))
    object.__setattr__(candidate, "oferta", _canonical_offering(oferta))
    object.__setattr__(
        candidate,
        "observacoes",
        _normalize_observations(observacoes),
    )
    return candidate


_NEGATIVE_SIGNS: Final = "-−–—﹣－"
_NEGATIVE_SIGN_CLASS: Final = f"[{re.escape(_NEGATIVE_SIGNS)}]"
_PRESENTES_LABEL: Final = r"presentes?"
_VISITANTES_LABEL: Final = r"visitantes?"
_DECISOES_LABEL: Final = r"decis(?:ão|ões|ao|oes)"
_COUNT_LABEL: Final = (
    r"(?>presentes|presente|visitantes|visitante|"
    r"decisões|decisão|decisoes|decisao)"
)
_COUNT_LABEL_CLOSED: Final = rf"(?<!\w){_COUNT_LABEL}(?!\w)"
_OFFERING_LABEL: Final = r"(?>ofertas|oferta)"
_OFFERING_LABEL_CLOSED: Final = rf"(?<!\w){_OFFERING_LABEL}(?!\w)"
_WORD_NON_DIGIT: Final = r"(?:[^\W\d])"
_GLUED_NUMBER_TOKEN: Final = (
    rf"(?=\w*{_WORD_NON_DIGIT})(?=\w*[0-9])\w+"
)
_GLUED_MONEY_TOKEN: Final = (
    rf"(?=[\w.,]*{_WORD_NON_DIGIT})(?=[\w.,]*[0-9])[\w.,]+"
)

_COUNT_PATTERNS: Final = {
    "presentes": (
        re.compile(
            rf"(?<![\w+{re.escape(_NEGATIVE_SIGNS)}])"
            rf"([0-9]+)\s+{_PRESENTES_LABEL}(?!\w)",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?<!\w){_PRESENTES_LABEL}(?!\w)"
            r"(?:\s*[:=]\s*|\s+)([0-9]+)(?!\w)",
            re.IGNORECASE,
        ),
    ),
    "visitantes": (
        re.compile(
            rf"(?<![\w+{re.escape(_NEGATIVE_SIGNS)}])"
            rf"([0-9]+)\s+{_VISITANTES_LABEL}(?!\w)",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?<!\w){_VISITANTES_LABEL}(?!\w)"
            r"(?:\s*[:=]\s*|\s+)([0-9]+)(?!\w)",
            re.IGNORECASE,
        ),
    ),
    "decisoes": (
        re.compile(
            rf"(?<![\w+{re.escape(_NEGATIVE_SIGNS)}])"
            rf"([0-9]+)\s+{_DECISOES_LABEL}(?!\w)",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?<!\w){_DECISOES_LABEL}(?!\w)"
            r"(?:\s*[:=]\s*|\s+)([0-9]+)(?!\w)",
            re.IGNORECASE,
        ),
    ),
}

_MONEY_BODY: Final = (
    r"(?:(?:[0-9]{1,3}(?:\.[0-9]{3})+|[0-9]+)"
    r"(?:,[0-9]{1,2})?|[0-9]+\.[0-9]{1,2})"
)
_MONEY_TOKEN: Final = rf"({_MONEY_BODY})(?!\w|[.,][0-9])"
_OPTIONAL_REAL_SUFFIX: Final = (
    r"(?:\s+rea(?:l|is)(?!\w))?(?!\s+rea(?:l|is)\w)"
)
_OFFERING_PATTERNS: Final = (
    re.compile(
        rf"{_OFFERING_LABEL_CLOSED}(?:\s*[:=]\s*|\s+)"
        r"(?:r\$\s*)?"
        rf"{_MONEY_TOKEN}{_OPTIONAL_REAL_SUFFIX}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?<!\w)r\$\s*{_MONEY_TOKEN}{_OPTIONAL_REAL_SUFFIX}",
        re.IGNORECASE,
    ),
)
_OBSERVATIONS_PATTERN: Final = re.compile(
    r"(?:observa(?:ç|c)(?:ão|ao|ões|oes)|obs)\s*[:=-]\s*(.*)\Z",
    re.IGNORECASE | re.DOTALL,
)
_NEGATIVE_COUNT_PATTERN: Final = re.compile(
    r"(?:"
    rf"{_NEGATIVE_SIGN_CLASS}\s*[0-9]+\s*"
    rf"{_COUNT_LABEL}(?!\w)"
    rf"|{_COUNT_LABEL_CLOSED}\s*(?:[:=]\s*)?"
    rf"{_NEGATIVE_SIGN_CLASS}\s*[0-9]+"
    r")",
    re.IGNORECASE,
)
_NEGATIVE_OFFERING_PATTERN: Final = re.compile(
    r"(?:"
    rf"{_OFFERING_LABEL_CLOSED}\s*(?:[:=]\s*)?(?:r\$\s*)?"
    rf"{_NEGATIVE_SIGN_CLASS}\s*[0-9]"
    rf"|{_OFFERING_LABEL_CLOSED}\s*(?:[:=]\s*)?"
    rf"{_NEGATIVE_SIGN_CLASS}\s*(?:r\$\s*)?[0-9]"
    rf"|(?<!\w)r\$\s*{_NEGATIVE_SIGN_CLASS}\s*[0-9]"
    r")",
    re.IGNORECASE,
)
_MALFORMED_COUNT_TOKEN_PATTERN: Final = re.compile(
    r"(?:"
    rf"(?<!\w){_GLUED_NUMBER_TOKEN}(?!\w)\s*{_COUNT_LABEL}(?!\w)"
    rf"|{_COUNT_LABEL_CLOSED}\s*[:=]?\s*"
    rf"{_GLUED_NUMBER_TOKEN}(?!\w)"
    rf"|(?<!\w)[0-9]+\s*{_COUNT_LABEL}(?=\w)"
    rf"|(?<!\w){_COUNT_LABEL}(?=\w)\w*\s*[:=]?\s*[0-9]+(?!\w)"
    rf"|(?<!\w)[0-9]+{_COUNT_LABEL}(?!\w)"
    rf"|{_COUNT_LABEL_CLOSED}[0-9]+(?!\w)"
    rf"|(?<!\w)[0-9]+\s+\w+{_COUNT_LABEL}\w*(?!\w)"
    rf"|(?<!\w)(?=\w*{_COUNT_LABEL})(?=\w*[0-9])\w+(?!\w)"
    rf"|(?<!\w)\w+{_COUNT_LABEL}\w*\s*[:=]?\s*[0-9]+(?!\w)"
    r")",
    re.IGNORECASE,
)
_MALFORMED_OFFERING_TOKEN_PATTERN: Final = re.compile(
    r"(?:"
    rf"{_OFFERING_LABEL_CLOSED}\s*[:=]?\s*(?:r\$\s*)?"
    rf"{_GLUED_MONEY_TOKEN}(?!\w)"
    rf"|(?<!\w)r\$\s*{_GLUED_MONEY_TOKEN}(?!\w)"
    rf"|{_OFFERING_LABEL_CLOSED}\s*[:=]?\s*(?:r\$\s*)?"
    rf"{_MONEY_BODY}(?!\w|[.,][0-9])\s+rea(?:l|is)(?=\w)\w*"
    rf"|(?<!\w)r\$\s*{_MONEY_BODY}(?!\w|[.,][0-9])"
    r"\s+rea(?:l|is)(?=\w)\w*"
    rf"|(?<!\w){_OFFERING_LABEL}(?=\w)\w*\s*[:=]?\s*"
    rf"(?:r\$\s*)?{_MONEY_BODY}(?!\w|[.,][0-9])"
    rf"|{_OFFERING_LABEL_CLOSED}{_MONEY_BODY}(?!\w|[.,][0-9])"
    rf"|(?<!\w)\w+{_OFFERING_LABEL}\w*\s*[:=]?\s*"
    rf"(?:r\$\s*)?{_MONEY_BODY}(?!\w|[.,][0-9])"
    rf"|(?<!\w)(?=\w*{_OFFERING_LABEL})(?=\w*[0-9])\w+(?!\w)"
    r")",
    re.IGNORECASE,
)


def _unique_match(
    patterns: tuple[re.Pattern[str], ...],
    text: str,
    *,
    converter: object,
) -> object | None:
    values: set[object] = set()
    convert = converter
    for pattern in patterns:
        for match in pattern.finditer(text):
            values.add(convert(match.group(1)))  # type: ignore[operator]
    if len(values) > 1:
        _raise(CellReportWorkflowErrorCode.CONFLICTING_FIELD_VALUES)
    return next(iter(values), None)


def _parse_count_token(value: str) -> int:
    if len(value) > 7:
        _raise(CellReportWorkflowErrorCode.COUNT_LIMIT_EXCEEDED)
    try:
        return _normalized_count(int(value))  # type: ignore[return-value]
    except ValueError:
        _raise(CellReportWorkflowErrorCode.INVALID_COUNT)


def parse_cell_report_candidate(text: str | None) -> CellReportCandidate:
    """Parse one bounded message into fields explicitly present in that text."""

    normalized = _normalized_text(text)
    if _NEGATIVE_COUNT_PATTERN.search(normalized) is not None:
        _raise(CellReportWorkflowErrorCode.INVALID_COUNT)
    if _NEGATIVE_OFFERING_PATTERN.search(normalized) is not None:
        _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)
    if _MALFORMED_COUNT_TOKEN_PATTERN.search(normalized) is not None:
        _raise(CellReportWorkflowErrorCode.INVALID_COUNT)
    if _MALFORMED_OFFERING_TOKEN_PATTERN.search(normalized) is not None:
        _raise(CellReportWorkflowErrorCode.INVALID_OFFERING)
    counts = {
        field_name: _unique_match(
            patterns,
            normalized,
            converter=_parse_count_token,
        )
        for field_name, patterns in _COUNT_PATTERNS.items()
    }
    offering = _unique_match(
        _OFFERING_PATTERNS,
        normalized,
        converter=_canonical_report_offering,
    )
    observation_match = _OBSERVATIONS_PATTERN.search(normalized)
    observations = observation_match.group(1) if observation_match else None
    return build_cell_report_candidate(
        presentes=counts["presentes"],  # type: ignore[arg-type]
        visitantes=counts["visitantes"],  # type: ignore[arg-type]
        decisoes=counts["decisoes"],  # type: ignore[arg-type]
        oferta=offering,  # type: ignore[arg-type]
        observacoes=observations,
    )


def merge_cell_report_candidates(
    current: CellReportCandidate,
    patch: CellReportCandidate,
) -> CellReportCandidate:
    """Overlay fields explicitly present in ``patch`` onto ``current``."""

    _validate_candidate(current)
    _validate_candidate(patch)
    return build_cell_report_candidate(
        presentes=(patch.presentes if patch.presentes is not None else current.presentes),
        visitantes=(patch.visitantes if patch.visitantes is not None else current.visitantes),
        decisoes=(patch.decisoes if patch.decisoes is not None else current.decisoes),
        oferta=(patch.oferta if patch.oferta is not None else current.oferta),
        observacoes=(
            patch.observacoes
            if patch.observacoes is not None
            else current.observacoes
        ),
    )


def cell_report_candidate_payload(
    candidate: CellReportCandidate,
) -> dict[str, object]:
    """Return the closed JSON-safe projection; it never contains a float."""

    _validate_candidate(candidate)
    return {
        "schema_version": CELL_REPORT_CANDIDATE_SCHEMA_VERSION,
        "presentes": candidate.presentes,
        "visitantes": candidate.visitantes,
        "decisoes": candidate.decisoes,
        "oferta": candidate.oferta,
        "observacoes": candidate.observacoes,
    }


def _canonical_candidate_bytes(candidate: CellReportCandidate) -> bytes:
    try:
        return json.dumps(
            cell_report_candidate_payload(candidate),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", "strict")
    except (TypeError, UnicodeEncodeError, ValueError):
        _raise(CellReportWorkflowErrorCode.INVALID_CANDIDATE)


def _derive_candidate_digest(candidate: CellReportCandidate) -> str:
    material = _binary_frame(
        _CANDIDATE_DOMAIN,
        CELL_REPORT_CANDIDATE_SCHEMA_VERSION.encode("ascii"),
        _canonical_candidate_bytes(candidate),
    )
    return f"{_CANDIDATE_DIGEST_PREFIX}{hashlib.sha256(material).hexdigest()}"


def _validate_candidate(value: object) -> CellReportCandidate:
    if type(value) is not CellReportCandidate:
        _raise(CellReportWorkflowErrorCode.INVALID_CANDIDATE)
    try:
        expected = build_cell_report_candidate(
            presentes=value.presentes,
            visitantes=value.visitantes,
            decisoes=value.decisoes,
            oferta=value.oferta,
            observacoes=value.observacoes,
        )
    except AttributeError:
        _raise(CellReportWorkflowErrorCode.INVALID_CANDIDATE)
    if expected != value:
        _raise(CellReportWorkflowErrorCode.INVALID_CANDIDATE)
    return value


def _derive_scope_digest(correlation_key: object) -> str:
    if type(correlation_key) is str and len(correlation_key) > MAX_REPORT_CORRELATION_KEY_BYTES:
        _raise(CellReportWorkflowErrorCode.CORRELATION_KEY_LIMIT_EXCEEDED)
    if type(correlation_key) is not str or not re.fullmatch(
        rf"{re.escape(CELL_REPORT_SCOPE_KEY_PREFIX)}[0-9a-f]{{64}}",
        correlation_key,
        flags=re.ASCII,
    ):
        _raise(CellReportWorkflowErrorCode.INVALID_CORRELATION_KEY)
    encoded = _utf8_bytes(
        correlation_key,
        invalid=CellReportWorkflowErrorCode.INVALID_CORRELATION_KEY,
    )
    if len(encoded) > MAX_REPORT_CORRELATION_KEY_BYTES:
        _raise(CellReportWorkflowErrorCode.CORRELATION_KEY_LIMIT_EXCEEDED)
    material = _binary_frame(
        _SCOPE_DOMAIN,
        CELL_REPORT_WORKFLOW_SCHEMA_VERSION.encode("ascii"),
        encoded,
    )
    return f"{_SCOPE_DIGEST_PREFIX}{hashlib.sha256(material).hexdigest()}"


def _derive_proposal_digest(
    *,
    scope_digest: str,
    revision: int,
    candidate_digest: str,
    previous_proposal_digest: str | None,
) -> str:
    material = _binary_frame(
        _PROPOSAL_DOMAIN,
        CELL_REPORT_WORKFLOW_SCHEMA_VERSION.encode("ascii"),
        scope_digest.encode("ascii"),
        revision.to_bytes(8, "big"),
        candidate_digest.encode("ascii"),
        (previous_proposal_digest or "").encode("ascii"),
    )
    return f"{_PROPOSAL_DIGEST_PREFIX}{hashlib.sha256(material).hexdigest()}"


def _derive_confirmation_code(proposal_digest: str) -> str:
    material = _binary_frame(
        _CONFIRMATION_DOMAIN,
        CELL_REPORT_CONFIRMATION_GRAMMAR_VERSION.encode("ascii"),
        proposal_digest.encode("ascii"),
    )
    digest = hashlib.sha256(material).digest()
    return base64.b32encode(digest).decode("ascii")[:CONFIRMATION_CODE_LENGTH]


def _is_prefixed_sha256(value: object, prefix: str) -> bool:
    if type(value) is not str or not value.startswith(prefix):
        return False
    suffix = value[len(prefix) :]
    return len(suffix) == 64 and all(character in "0123456789abcdef" for character in suffix)


def _open_state(candidate: CellReportCandidate) -> CellReportWorkflowState:
    if candidate.is_empty:
        return CellReportWorkflowState.EMPTY
    if candidate.is_complete:
        return CellReportWorkflowState.AWAITING_CONFIRMATION
    return CellReportWorkflowState.COLLECTING


@dataclass(frozen=True, slots=True, repr=False, init=False)
class CellReportWorkflow:
    """Immutable current revision of a pure report proposal workflow."""

    schema_version: str
    scope_digest: str
    revision: int
    candidate: CellReportCandidate
    candidate_digest: str
    previous_proposal_digest: str | None
    proposal_digest: str
    confirmation_code: str | None
    state: CellReportWorkflowState
    accepted_proposal_digest: str | None

    def __repr__(self) -> str:
        return "CellReportWorkflow(<redacted>)"


def _mint_workflow(
    *,
    scope_digest: str,
    revision: int,
    candidate: CellReportCandidate,
    previous_proposal_digest: str | None,
    state: CellReportWorkflowState,
    accepted_proposal_digest: str | None = None,
) -> CellReportWorkflow:
    candidate_digest = _derive_candidate_digest(candidate)
    proposal_digest = _derive_proposal_digest(
        scope_digest=scope_digest,
        revision=revision,
        candidate_digest=candidate_digest,
        previous_proposal_digest=previous_proposal_digest,
    )
    confirmation_code = (
        _derive_confirmation_code(proposal_digest)
        if candidate.is_complete
        else None
    )
    workflow = object.__new__(CellReportWorkflow)
    object.__setattr__(
        workflow,
        "schema_version",
        CELL_REPORT_WORKFLOW_SCHEMA_VERSION,
    )
    object.__setattr__(workflow, "scope_digest", scope_digest)
    object.__setattr__(workflow, "revision", revision)
    object.__setattr__(workflow, "candidate", candidate)
    object.__setattr__(workflow, "candidate_digest", candidate_digest)
    object.__setattr__(
        workflow,
        "previous_proposal_digest",
        previous_proposal_digest,
    )
    object.__setattr__(workflow, "proposal_digest", proposal_digest)
    object.__setattr__(workflow, "confirmation_code", confirmation_code)
    object.__setattr__(workflow, "state", state)
    object.__setattr__(
        workflow,
        "accepted_proposal_digest",
        accepted_proposal_digest,
    )
    return workflow


def start_cell_report_workflow(
    *,
    correlation_key: str,
    candidate: CellReportCandidate | None = None,
) -> CellReportWorkflow:
    """Start revision one, retaining only a digest of one opaque scope key.

    A trusted future adapter must mint a unique scope key for each report
    attempt and enforce its lifecycle.  Restarting this pure contract with the
    same scope and candidate is deliberately deterministic; the resulting code
    still correlates only and is not replay protection or authorization.
    """

    resolved_candidate = (
        build_cell_report_candidate() if candidate is None else candidate
    )
    _validate_candidate(resolved_candidate)
    return _mint_workflow(
        scope_digest=_derive_scope_digest(correlation_key),
        revision=1,
        candidate=resolved_candidate,
        previous_proposal_digest=None,
        state=_open_state(resolved_candidate),
    )


def start_cell_report_workflow_from_text(
    *,
    correlation_key: str,
    text: str | None,
) -> CellReportWorkflow:
    return start_cell_report_workflow(
        correlation_key=correlation_key,
        candidate=parse_cell_report_candidate(text),
    )


def validate_cell_report_workflow(value: object) -> CellReportWorkflow:
    """Recompute every derivable field before a pure transition."""

    if type(value) is not CellReportWorkflow:
        _raise(CellReportWorkflowErrorCode.INVALID_WORKFLOW)
    try:
        schema_version = value.schema_version
        scope_digest = value.scope_digest
        revision = value.revision
        candidate = value.candidate
        candidate_digest = value.candidate_digest
        previous_proposal_digest = value.previous_proposal_digest
        proposal_digest = value.proposal_digest
        confirmation_code = value.confirmation_code
        state = value.state
        accepted_proposal_digest = value.accepted_proposal_digest
    except AttributeError:
        _raise(CellReportWorkflowErrorCode.INVALID_WORKFLOW)
    if (
        schema_version != CELL_REPORT_WORKFLOW_SCHEMA_VERSION
        or not _is_prefixed_sha256(scope_digest, _SCOPE_DIGEST_PREFIX)
        or type(revision) is not int
        or revision < 1
        or revision > MAX_REPORT_REVISION
        or not isinstance(state, CellReportWorkflowState)
        or not _is_prefixed_sha256(candidate_digest, _CANDIDATE_DIGEST_PREFIX)
        or not _is_prefixed_sha256(proposal_digest, _PROPOSAL_DIGEST_PREFIX)
    ):
        _raise(CellReportWorkflowErrorCode.INVALID_WORKFLOW)
    _validate_candidate(candidate)
    if revision == 1:
        if previous_proposal_digest is not None:
            _raise(CellReportWorkflowErrorCode.INVALID_WORKFLOW)
    elif not _is_prefixed_sha256(
        previous_proposal_digest,
        _PROPOSAL_DIGEST_PREFIX,
    ):
        _raise(CellReportWorkflowErrorCode.INVALID_WORKFLOW)
    expected_candidate_digest = _derive_candidate_digest(candidate)
    expected_proposal_digest = _derive_proposal_digest(
        scope_digest=scope_digest,
        revision=revision,
        candidate_digest=expected_candidate_digest,
        previous_proposal_digest=previous_proposal_digest,
    )
    expected_code = (
        _derive_confirmation_code(expected_proposal_digest)
        if candidate.is_complete
        else None
    )
    if (
        not hmac.compare_digest(candidate_digest, expected_candidate_digest)
        or not hmac.compare_digest(proposal_digest, expected_proposal_digest)
        or confirmation_code != expected_code
    ):
        _raise(CellReportWorkflowErrorCode.INVALID_WORKFLOW)

    if state in {
        CellReportWorkflowState.EMPTY,
        CellReportWorkflowState.COLLECTING,
        CellReportWorkflowState.AWAITING_CONFIRMATION,
    }:
        if state is not _open_state(candidate):
            _raise(CellReportWorkflowErrorCode.INVALID_WORKFLOW)
        if accepted_proposal_digest is not None:
            _raise(CellReportWorkflowErrorCode.INVALID_WORKFLOW)
    elif state in {
        CellReportWorkflowState.CONFIRMATION_ACCEPTED,
        CellReportWorkflowState.COMMITTED,
    }:
        if (
            not candidate.is_complete
            or accepted_proposal_digest != proposal_digest
        ):
            _raise(CellReportWorkflowErrorCode.INVALID_WORKFLOW)
    elif (
        accepted_proposal_digest is not None
        and accepted_proposal_digest != proposal_digest
    ):
        _raise(CellReportWorkflowErrorCode.INVALID_WORKFLOW)
    return value


def revise_cell_report_workflow(
    workflow: CellReportWorkflow,
    candidate: CellReportCandidate,
) -> CellReportWorkflow:
    """Replace the candidate and mint a chained revision with a new code."""

    current = validate_cell_report_workflow(workflow)
    replacement = _validate_candidate(candidate)
    if current.state not in REVISION_ALLOWED_REPORT_STATES:
        _raise(CellReportWorkflowErrorCode.INVALID_STATE_TRANSITION)
    if current.revision >= MAX_REPORT_REVISION:
        _raise(CellReportWorkflowErrorCode.REVISION_LIMIT_EXCEEDED)
    return _mint_workflow(
        scope_digest=current.scope_digest,
        revision=current.revision + 1,
        candidate=replacement,
        previous_proposal_digest=current.proposal_digest,
        state=_open_state(replacement),
    )


def revise_cell_report_workflow_from_text(
    workflow: CellReportWorkflow,
    text: str,
) -> CellReportWorkflow:
    """Merge explicitly parsed corrections and mint a fresh revision."""

    current = validate_cell_report_workflow(workflow)
    if current.state not in REVISION_ALLOWED_REPORT_STATES:
        _raise(CellReportWorkflowErrorCode.INVALID_STATE_TRANSITION)
    patch = parse_cell_report_candidate(text)
    if patch.is_empty:
        _raise(CellReportWorkflowErrorCode.EMPTY_REVISION)
    merged = merge_cell_report_candidates(current.candidate, patch)
    return revise_cell_report_workflow(current, merged)


def cell_report_confirmation_command(workflow: CellReportWorkflow) -> str:
    """Render the only admitted literal command for the current proposal."""

    current = validate_cell_report_workflow(workflow)
    if (
        current.state is not CellReportWorkflowState.AWAITING_CONFIRMATION
        or current.confirmation_code is None
    ):
        _raise(CellReportWorkflowErrorCode.INVALID_STATE_TRANSITION)
    return f"{CONFIRMATION_COMMAND_PREFIX}{current.confirmation_code}"


def parse_cell_report_confirmation_command(value: object) -> str:
    """Parse exact ASCII grammar without trimming or case folding."""

    if type(value) is not str:
        _raise(CellReportWorkflowErrorCode.INVALID_CONFIRMATION_COMMAND)
    pattern = (
        rf"{re.escape(CONFIRMATION_COMMAND_PREFIX)}"
        rf"([A-Z2-7]{{{CONFIRMATION_CODE_LENGTH}}})"
    )
    match = re.fullmatch(pattern, value, flags=re.ASCII)
    if match is None:
        _raise(CellReportWorkflowErrorCode.INVALID_CONFIRMATION_COMMAND)
    return match.group(1)


def correlate_cell_report_confirmation(
    workflow: CellReportWorkflow,
    command: str,
) -> CellReportWorkflow:
    """Correlate the exact current code; this performs no authorization."""

    current = validate_cell_report_workflow(workflow)
    if (
        current.state is not CellReportWorkflowState.AWAITING_CONFIRMATION
        or current.confirmation_code is None
    ):
        _raise(CellReportWorkflowErrorCode.INVALID_STATE_TRANSITION)
    supplied_code = parse_cell_report_confirmation_command(command)
    if not hmac.compare_digest(supplied_code, current.confirmation_code):
        _raise(CellReportWorkflowErrorCode.CONFIRMATION_CODE_MISMATCH)
    return _mint_workflow(
        scope_digest=current.scope_digest,
        revision=current.revision,
        candidate=current.candidate,
        previous_proposal_digest=current.previous_proposal_digest,
        state=CellReportWorkflowState.CONFIRMATION_ACCEPTED,
        accepted_proposal_digest=current.proposal_digest,
    )


def mark_cell_report_committed(
    workflow: CellReportWorkflow,
) -> CellReportWorkflow:
    """Project a proven external commit as a value; no commit occurs here."""

    current = validate_cell_report_workflow(workflow)
    if current.state is not CellReportWorkflowState.CONFIRMATION_ACCEPTED:
        _raise(CellReportWorkflowErrorCode.INVALID_STATE_TRANSITION)
    return _mint_workflow(
        scope_digest=current.scope_digest,
        revision=current.revision,
        candidate=current.candidate,
        previous_proposal_digest=current.previous_proposal_digest,
        state=CellReportWorkflowState.COMMITTED,
        accepted_proposal_digest=current.proposal_digest,
    )


def terminalize_cell_report_workflow(
    workflow: CellReportWorkflow,
    state: CellReportWorkflowState,
) -> CellReportWorkflow:
    """Return a pure cancel, expire, conflict, or reject terminal value."""

    current = validate_cell_report_workflow(workflow)
    if (
        type(state) is not CellReportWorkflowState
        or state not in EXPLICIT_TERMINAL_REPORT_STATES
        or current.state in TERMINAL_REPORT_STATES
    ):
        _raise(CellReportWorkflowErrorCode.INVALID_STATE_TRANSITION)
    return _mint_workflow(
        scope_digest=current.scope_digest,
        revision=current.revision,
        candidate=current.candidate,
        previous_proposal_digest=current.previous_proposal_digest,
        state=state,
        accepted_proposal_digest=current.accepted_proposal_digest,
    )
