"""Pure recognizer for the closed human cell-report snapshot projection.

The panel predates the versioned aggregate snapshot and persists one schema-less
JSON object.  This module recognizes only the exact object the panel can build.
It performs no I/O, never returns snapshot content, and fails closed with a
boolean so malformed schema-less data remains a data-integrity failure.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Final

from app.domain.cell_report_limits import (
    MAX_CELL_REPORT_AGGREGATE_COUNT,
    MAX_CELL_REPORT_OBSERVATIONS_BYTES,
    MAX_CELL_REPORT_OBSERVATIONS_LENGTH,
    MAX_CELL_REPORT_OFFERING_DECIMAL_TEXT,
)

LEGACY_HUMAN_REPORT_STATUS: Final = "enviado"
_MAX_TEMA_LENGTH: Final = 120
_MAX_VISITOR_NAME_LENGTH: Final = 120
_MAX_RECORD_CONTENT_LENGTH: Final = 2_000
_MAX_OFFER: Final = Decimal(MAX_CELL_REPORT_OFFERING_DECIMAL_TEXT)

_REPORT_KEYS: Final = frozenset(
    {
        "meeting_id",
        "data",
        "tema",
        "relatorio_status",
        "oferta_valor",
        "observacoes",
        "presencas",
        "visitantes",
        "records",
    }
)
_PRESENCE_KEYS: Final = frozenset({"pessoa_id", "estado", "origem"})
_VISITOR_KEYS: Final = frozenset(
    {"id", "nome_visitante", "expectativa_id", "observacao"}
)
_RECORD_KEYS: Final = frozenset({"id", "tipo", "conteudo", "pessoa_id"})
_PRESENCE_STATES: Final = frozenset({"confirmada", "compareceu", "ausente"})
_PRESENCE_ORIGINS: Final = frozenset({None, "auto", "lider"})
_RECORD_TYPES: Final = frozenset({"decisao", "oracao", "observacao"})


def _has_exact_keys(value: object, expected: frozenset[str]) -> bool:
    return (
        type(value) is dict
        and len(value) == len(expected)
        and value.keys() == expected
    )


def _is_canonical_uuid(value: object, expected: uuid.UUID | None = None) -> bool:
    if type(value) is not str or len(value) != 36:
        return False
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        return False
    if parsed.int == 0 or str(parsed) != value:
        return False
    return expected is None or parsed == expected


def _is_optional_canonical_uuid(value: object) -> bool:
    return value is None or _is_canonical_uuid(value)


def _is_bounded_text(
    value: object,
    *,
    maximum: int,
    optional: bool,
    maximum_bytes: int | None = None,
) -> bool:
    if value is None:
        return optional
    if type(value) is not str or not value or value != value.strip():
        return False
    if len(value) > maximum:
        return False
    if maximum_bytes is not None:
        try:
            if len(value.encode("utf-8", "strict")) > maximum_bytes:
                return False
        except UnicodeEncodeError:
            return False
    return True


def _canonical_money(value: object) -> Decimal | None:
    if value is None:
        return None
    if type(value) not in {int, float}:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if (
        not parsed.is_finite()
        or parsed < 0
        or parsed > _MAX_OFFER
        or parsed.as_tuple().exponent < -2
        or (parsed.is_zero() and parsed.is_signed())
    ):
        return None
    return parsed


def _expected_money(value: object) -> Decimal | None:
    if value is None:
        return None
    if type(value) not in {Decimal, int, float}:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed < 0 or parsed > _MAX_OFFER:
        return None
    return parsed


def _valid_presence(item: object) -> bool:
    estado = item.get("estado") if type(item) is dict else None
    origem = item.get("origem") if type(item) is dict else None
    return (
        _has_exact_keys(item, _PRESENCE_KEYS)
        and _is_canonical_uuid(item.get("pessoa_id"))
        and type(estado) is str
        and estado in _PRESENCE_STATES
        and (origem is None or type(origem) is str)
        and origem in _PRESENCE_ORIGINS
    )


def _valid_visitor(item: object) -> bool:
    return (
        _has_exact_keys(item, _VISITOR_KEYS)
        and _is_canonical_uuid(item.get("id"))
        and _is_bounded_text(
            item.get("nome_visitante"),
            maximum=_MAX_VISITOR_NAME_LENGTH,
            optional=False,
        )
        and _is_optional_canonical_uuid(item.get("expectativa_id"))
        and (
            item.get("observacao") is None
            or _is_bounded_text(
                item.get("observacao"),
                maximum=MAX_CELL_REPORT_OBSERVATIONS_LENGTH,
                maximum_bytes=MAX_CELL_REPORT_OBSERVATIONS_BYTES,
                optional=False,
            )
        )
    )


def _valid_record(item: object) -> bool:
    record_type = item.get("tipo") if type(item) is dict else None
    return (
        _has_exact_keys(item, _RECORD_KEYS)
        and _is_canonical_uuid(item.get("id"))
        and type(record_type) is str
        and record_type in _RECORD_TYPES
        and _is_bounded_text(
            item.get("conteudo"),
            maximum=_MAX_RECORD_CONTENT_LENGTH,
            optional=False,
        )
        and _is_optional_canonical_uuid(item.get("pessoa_id"))
    )


def _valid_closed_list(
    value: object,
    *,
    validator: Callable[[object], bool],
    identity_key: str,
) -> bool:
    if type(value) is not list or len(value) > MAX_CELL_REPORT_AGGREGATE_COUNT:
        return False
    seen: set[str] = set()
    for item in value:
        if type(item) is not dict or not validator(item):
            return False
        identity = item[identity_key]
        if type(identity) is not str:
            return False
        if identity in seen:
            return False
        seen.add(identity)
    return True


def is_canonical_legacy_human_report_snapshot(
    value: object,
    *,
    meeting_id: uuid.UUID,
    meeting_date: dt.date,
    meeting_tema: str | None,
    meeting_status: str,
    meeting_oferta_valor: Decimal | int | float | None,
    meeting_observacoes: str | None,
    meeting_sent_at: dt.datetime | None,
    meeting_sent_by: uuid.UUID | None,
    expected_actor_id: uuid.UUID,
) -> bool:
    """Return whether ``value`` is the exact legacy panel snapshot for a meeting."""

    if (
        type(meeting_id) is not uuid.UUID
        or type(meeting_date) is not dt.date
        or type(meeting_sent_at) is not dt.datetime
        or meeting_sent_at.tzinfo is None
        or meeting_sent_at.utcoffset() is None
        or type(meeting_sent_by) is not uuid.UUID
        or type(expected_actor_id) is not uuid.UUID
        or meeting_sent_by != expected_actor_id
        or meeting_status != LEGACY_HUMAN_REPORT_STATUS
        or not _has_exact_keys(value, _REPORT_KEYS)
    ):
        return False
    data = value.get("data")
    if type(data) is not str or len(data) != 10:
        return False
    try:
        parsed_date = dt.date.fromisoformat(data)
    except ValueError:
        return False
    if parsed_date.isoformat() != data or parsed_date != meeting_date:
        return False

    tema = value.get("tema")
    if tema is not None and not _is_bounded_text(
        tema,
        maximum=_MAX_TEMA_LENGTH,
        optional=False,
    ):
        return False
    if tema != meeting_tema:
        return False

    observacoes = value.get("observacoes")
    if observacoes is not None and not _is_bounded_text(
        observacoes,
        maximum=MAX_CELL_REPORT_OBSERVATIONS_LENGTH,
        maximum_bytes=MAX_CELL_REPORT_OBSERVATIONS_BYTES,
        optional=False,
    ):
        return False
    if observacoes != meeting_observacoes:
        return False

    snapshot_money_value = value.get("oferta_valor")
    if (snapshot_money_value is None) != (meeting_oferta_valor is None):
        return False
    if snapshot_money_value is not None:
        snapshot_money = _canonical_money(snapshot_money_value)
        expected_money = _expected_money(meeting_oferta_valor)
        if snapshot_money is None or expected_money is None:
            return False
        if snapshot_money != expected_money:
            return False

    presencas = value.get("presencas")
    visitantes = value.get("visitantes")
    records = value.get("records")
    return (
        _is_canonical_uuid(value.get("meeting_id"), meeting_id)
        and value.get("relatorio_status") == LEGACY_HUMAN_REPORT_STATUS
        and _valid_closed_list(
            presencas,
            validator=_valid_presence,
            identity_key="pessoa_id",
        )
        and _valid_closed_list(
            visitantes,
            validator=_valid_visitor,
            identity_key="id",
        )
        and _valid_closed_list(
            records,
            validator=_valid_record,
            identity_key="id",
        )
    )


__all__ = [
    "LEGACY_HUMAN_REPORT_STATUS",
    "is_canonical_legacy_human_report_snapshot",
]
