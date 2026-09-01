"""Closed-shape tests for the schema-less human report snapshot."""

from __future__ import annotations

import datetime as dt
import uuid
from copy import deepcopy
from decimal import Decimal

import pytest

from app.domain.cell_report_legacy_snapshot import (
    is_canonical_legacy_human_report_snapshot,
)

MEETING = uuid.UUID("11111111-1111-1111-1111-111111111111")
PERSON = uuid.UUID("22222222-2222-2222-2222-222222222222")
VISITOR = uuid.UUID("33333333-3333-3333-3333-333333333333")
EXPECTATION = uuid.UUID("44444444-4444-4444-4444-444444444444")
RECORD = uuid.UUID("55555555-5555-5555-5555-555555555555")
ACTOR = uuid.UUID("66666666-6666-6666-6666-666666666666")
MEETING_DATE = dt.date(2026, 8, 31)
SENT_AT = dt.datetime(2026, 8, 31, 18, 0, tzinfo=dt.timezone.utc)
NIL_UUID = str(uuid.UUID(int=0))


def _snapshot() -> dict[str, object]:
    return {
        "meeting_id": str(MEETING),
        "data": MEETING_DATE.isoformat(),
        "tema": "Encontro",
        "relatorio_status": "enviado",
        "oferta_valor": 12.5,
        "observacoes": "Revisado no painel",
        "presencas": [
            {
                "pessoa_id": str(PERSON),
                "estado": "compareceu",
                "origem": "lider",
            }
        ],
        "visitantes": [
            {
                "id": str(VISITOR),
                "nome_visitante": "Visitante",
                "expectativa_id": str(EXPECTATION),
                "observacao": "Primeira visita",
            }
        ],
        "records": [
            {
                "id": str(RECORD),
                "tipo": "decisao",
                "conteudo": "Registro pastoral",
                "pessoa_id": str(PERSON),
            }
        ],
    }


def _recognize(
    value: object,
    **overrides: object,
) -> bool:
    metadata = {
        "meeting_id": MEETING,
        "meeting_date": MEETING_DATE,
        "meeting_tema": "Encontro",
        "meeting_status": "enviado",
        "meeting_oferta_valor": Decimal("12.50"),
        "meeting_observacoes": "Revisado no painel",
        "meeting_sent_at": SENT_AT,
        "meeting_sent_by": ACTOR,
        "expected_actor_id": ACTOR,
    }
    metadata.update(overrides)
    return is_canonical_legacy_human_report_snapshot(value, **metadata)


def test_recognizes_complete_legacy_panel_projection() -> None:
    assert _recognize(_snapshot()) is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("meeting_id", "11111111-1111-1111-1111-11111111111A"),
        ("data", "2026-8-31"),
        ("tema", "Outro"),
        ("relatorio_status", "pendente"),
        ("oferta_valor", 12.51),
        ("observacoes", "Outra"),
        ("presencas", "invalid"),
        ("visitantes", "invalid"),
        ("records", "invalid"),
    ],
)
def test_rejects_wrong_top_level_value(field: str, value: object) -> None:
    snapshot = _snapshot()
    snapshot[field] = value
    assert _recognize(snapshot) is False


@pytest.mark.parametrize(
    ("collection", "field"),
    [
        (None, "meeting_id"),
        ("presencas", "pessoa_id"),
        ("visitantes", "id"),
        ("visitantes", "expectativa_id"),
        ("records", "id"),
        ("records", "pessoa_id"),
    ],
)
def test_rejects_nil_uuid_in_every_legacy_shape_position(
    collection: str | None,
    field: str,
) -> None:
    snapshot = deepcopy(_snapshot())
    if collection is None:
        snapshot[field] = NIL_UUID
    else:
        snapshot[collection][0][field] = NIL_UUID

    assert _recognize(snapshot) is False


@pytest.mark.parametrize(
    "metadata",
    [
        {"meeting_id": uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")},
        {"meeting_date": dt.date(2026, 9, 1)},
        {"meeting_tema": "Outro"},
        {"meeting_status": "pendente"},
        {"meeting_oferta_valor": Decimal("12.51")},
        {"meeting_observacoes": "Outra"},
        {"meeting_sent_at": None},
        {"meeting_sent_at": SENT_AT.replace(tzinfo=None)},
        {"meeting_sent_by": uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")},
        {"expected_actor_id": uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")},
    ],
)
def test_requires_snapshot_to_match_locked_meeting_metadata(
    metadata: dict[str, object],
) -> None:
    assert _recognize(_snapshot(), **metadata) is False


@pytest.mark.parametrize(
    ("collection", "replacement"),
    [
        (
            "presencas",
            {"pessoa_id": str(PERSON), "estado": "desconhecido", "origem": "lider"},
        ),
        (
            "presencas",
            {"pessoa_id": str(PERSON), "estado": [], "origem": {}},
        ),
        (
            "presencas",
            {"pessoa_id": "not-uuid", "estado": "compareceu", "origem": "lider"},
        ),
        (
            "visitantes",
            {
                "id": str(VISITOR),
                "nome_visitante": "Visitante",
                "expectativa_id": "not-uuid",
                "observacao": None,
            },
        ),
        (
            "records",
            {
                "id": str(RECORD),
                "tipo": [],
                "conteudo": "Registro",
                "pessoa_id": None,
            },
        ),
    ],
)
def test_rejects_malformed_nested_items(
    collection: str,
    replacement: dict[str, object],
) -> None:
    snapshot = deepcopy(_snapshot())
    snapshot[collection] = [replacement]
    assert _recognize(snapshot) is False


@pytest.mark.parametrize("collection", ["presencas", "visitantes", "records"])
def test_rejects_duplicate_nested_identity(collection: str) -> None:
    snapshot = deepcopy(_snapshot())
    snapshot[collection] = [
        snapshot[collection][0],
        deepcopy(snapshot[collection][0]),
    ]
    assert _recognize(snapshot) is False


def test_rejects_extra_or_missing_keys_at_every_level() -> None:
    extra_top = _snapshot()
    extra_top["schema"] = "unexpected"
    assert _recognize(extra_top) is False

    missing_top = _snapshot()
    missing_top.pop("records")
    assert _recognize(missing_top) is False

    nested = _snapshot()
    nested["presencas"][0]["extra"] = True
    assert _recognize(nested) is False


@pytest.mark.parametrize("money", [True, float("nan"), float("inf"), -1.0, 1.001])
def test_rejects_noncanonical_json_money(money: object) -> None:
    snapshot = _snapshot()
    snapshot["oferta_valor"] = money
    assert _recognize(snapshot, meeting_oferta_valor=money) is False
