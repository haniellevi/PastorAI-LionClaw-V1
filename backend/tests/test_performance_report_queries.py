"""Read pages must be bounded before hydration, independent of tenant size."""

from app.routers._common import PaginationParams
from app.routers.reports import list_reports
from tests.test_reports import ReportsSession, PAST, make_reuniao, week_of
from tests.test_events_dashboard_read_model import _user
from tests.test_cell_central import _central_session, _wire


def test_report_page_has_database_limit_and_count():
    session = ReportsSession(roles=["pastor"], reunioes=[make_reuniao(reuniao_id="r1", data=PAST)])
    original = session.execute
    statements = []

    def capture(statement, params=None):
        statements.append(statement)
        return original(statement, params)

    session.execute = capture
    list_reports(semana=week_of(PAST), pagination=PaginationParams(page=2, page_size=1),
                 db=session, current_user=_user("pastor"))
    assert any(getattr(getattr(s, "_limit_clause", None), "value", None) == 1
               and getattr(getattr(s, "_offset_clause", None), "value", None) == 1 for s in statements)
    assert any("count(" in str(s).lower() for s in statements)


def test_central_pending_page_limits_rows_in_sql(app):
    session = _central_session()
    response = _wire(app, session=session).get(
        "/cell-central/pending-reports?page=2&page_size=3", headers={"Authorization": "Bearer good"}
    )
    assert response.status_code == 200
    assert any("LIMIT" in sql and "OFFSET" in sql for sql in session.executed_sql)
