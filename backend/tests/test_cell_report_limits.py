from decimal import Decimal

from app.domain.cell_report_limits import (
    MAX_CELL_REPORT_AGGREGATE_COUNT,
    MAX_CELL_REPORT_OFFERING_CENTS,
    MAX_CELL_REPORT_OFFERING_DECIMAL_TEXT,
)
from app.domain.cell_report_snapshot import (
    MAX_CELL_REPORT_OFFER,
    MAX_CELL_REPORT_TOTAL,
)
from app.domain.cell_report_workflow import (
    MAX_REPORT_COUNT,
    MAX_REPORT_OFFERING_CENTS,
)
from app.routers.cell_meetings import _OFERTA_MAX


def test_human_and_agent_report_limits_share_one_domain_boundary() -> None:
    assert MAX_CELL_REPORT_AGGREGATE_COUNT == 1_000_000
    assert MAX_REPORT_COUNT == MAX_CELL_REPORT_AGGREGATE_COUNT
    assert MAX_CELL_REPORT_TOTAL == MAX_CELL_REPORT_AGGREGATE_COUNT

    assert MAX_CELL_REPORT_OFFERING_DECIMAL_TEXT == "999999.99"
    assert MAX_CELL_REPORT_OFFERING_CENTS == 99_999_999
    assert MAX_REPORT_OFFERING_CENTS == MAX_CELL_REPORT_OFFERING_CENTS
    assert MAX_CELL_REPORT_OFFER == Decimal(
        MAX_CELL_REPORT_OFFERING_DECIMAL_TEXT
    )
    assert Decimal(str(_OFERTA_MAX)) * 100 == MAX_CELL_REPORT_OFFERING_CENTS
