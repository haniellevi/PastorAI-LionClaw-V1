"""Shared product limits for human and agent cell-report paths.

These values express the reviewed domain boundary, which can be narrower than
the physical PostgreSQL column capacity.  Keeping them outside routers and
agent code prevents either interface from silently granting a wider write
range than the other.
"""

from typing import Final


MAX_CELL_REPORT_AGGREGATE_COUNT: Final = 1_000_000
MAX_CELL_REPORT_OFFERING_CENTS: Final = 99_999_999
MAX_CELL_REPORT_OFFERING_DECIMAL_TEXT: Final = "999999.99"
MAX_CELL_REPORT_OBSERVATIONS_LENGTH: Final = 2_000
MAX_CELL_REPORT_OBSERVATIONS_BYTES: Final = 8_000


__all__ = [
    "MAX_CELL_REPORT_AGGREGATE_COUNT",
    "MAX_CELL_REPORT_OBSERVATIONS_BYTES",
    "MAX_CELL_REPORT_OBSERVATIONS_LENGTH",
    "MAX_CELL_REPORT_OFFERING_CENTS",
    "MAX_CELL_REPORT_OFFERING_DECIMAL_TEXT",
]
