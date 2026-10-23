"""Uvicorn access logs must not retain query-string values."""

import logging

import pytest

from app.main import _install_uvicorn_access_log_filter


@pytest.mark.parametrize("status_code", [202, 401])
def test_access_log_redacts_query_values_for_success_and_error(caplog, status_code):
    _install_uvicorn_access_log_filter()
    access_logger = logging.getLogger("uvicorn.access")
    marker = "synthetic-webhook-secret-marker"

    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        access_logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:12345",
            "POST",
            f"/whatsapp/webhook?token={marker}&debug={marker}",
            "1.1",
            status_code,
        )

    assert marker not in caplog.text
    assert (
        "/whatsapp/webhook?token=%3Credacted%3E&debug=%3Credacted%3E"
        in caplog.text
    )
    assert f'" {status_code}' in caplog.text


def test_access_log_filter_drops_unrecognized_record_shape():
    from app.main import _UvicornAccessLogFilter

    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="synthetic query token=marker",
        args=(),
        exc_info=None,
    )

    assert _UvicornAccessLogFilter().filter(record) is False
