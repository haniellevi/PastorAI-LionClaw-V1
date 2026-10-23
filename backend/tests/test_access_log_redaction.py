"""Uvicorn access logs must not retain query-string values."""

import logging

import pytest

from app.main import _install_uvicorn_access_log_filter, _redact_access_query


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
        "/whatsapp/webhook?redacted=%3Credacted%3E&redacted=%3Credacted%3E"
        in caplog.text
    )
    assert f'" {status_code}' in caplog.text


def test_access_query_redacts_unknown_names_and_keeps_safe_pagination_names():
    assert _redact_access_query(
        "/whatsapp/webhook?SEGREDO&token=synthetic&Page=2&limit=10&offset=20"
    ) == (
        "/whatsapp/webhook?redacted=%3Credacted%3E&redacted=%3Credacted%3E"
        "&Page=%3Credacted%3E&limit=%3Credacted%3E&offset=%3Credacted%3E"
    )


@pytest.mark.parametrize("logger_name", ["httpx", "httpcore"])
def test_http_client_loggers_are_limited_to_warning(logger_name):
    assert logging.getLogger(logger_name).level == logging.WARNING


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
