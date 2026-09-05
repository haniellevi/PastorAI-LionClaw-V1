from __future__ import annotations

import os
import socket
import ssl
import tempfile
from pathlib import Path
from typing import Any

import pytest

from tests.test_dev_connect_tls_auth_transport_probe import (
    FIXED_NOW,
    HOST,
    PROJECT_REF,
    SyntheticPgTlsServer,
    _generate_pki,
    _load_module,
    _main_inputs,
    _parse_output,
)


def test_untrusted_private_ca_is_certificate_verification_error(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = _load_module()
    monkeypatch.setattr(probe, "_utc_now", lambda: FIXED_NOW)
    for key in list(os.environ):
        upper = key.upper()
        if (
            upper.startswith(("PG", "SSL", "OPENSSL", "DYLD_"))
            or upper in probe.RELEVANT_ENV_NAMES
        ):
            monkeypatch.delenv(key, raising=False)
    with tempfile.TemporaryDirectory(prefix="pastorai-ca-trust-regression-") as raw_dir:
        directory = Path(raw_dir)
        server_directory = directory / "server"
        supplied_ca_directory = directory / "supplied-ca"
        server_directory.mkdir()
        supplied_ca_directory.mkdir()
        _server_ca, cert_path, key_path = _generate_pki(server_directory)
        supplied_ca, _unused_cert, _unused_key = _generate_pki(supplied_ca_directory)
        server = SyntheticPgTlsServer(cert_path, key_path)
        server.start()

        def resolver(
            *_args: Any,
        ) -> list[tuple[int, int, int, str, tuple[Any, ...]]]:
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("127.0.0.1", server.port),
                )
            ]

        try:
            with _main_inputs(probe, directory, supplied_ca) as (
                argv,
                _descriptors,
                _expected,
            ):
                exit_code = probe.main(
                    argv,
                    _resolver=resolver,
                    _port=server.port,
                    _test_only_loopback_sentinel=probe._TEST_ONLY_LOOPBACK_SENTINEL,
                )
        finally:
            try:
                server.finish()
            except ssl.SSLError as error:
                # The client correctly aborts the peer handshake after the
                # untrusted CA assertion.  Keep the join mandatory, but accept
                # only the TLS alert variants caused by that deliberate abort.
                if error.reason not in {
                    "TLSV1_ALERT_DECRYPT_ERROR",
                    "TLSV1_ALERT_INTERNAL_ERROR",
                    "TLSV1_ALERT_UNKNOWN_CA",
                    "SSLV3_ALERT_BAD_CERTIFICATE",
                }:
                    raise

        captured = capsys.readouterr()
        output = _parse_output(captured.out)

        assert captured.err == ""
        assert exit_code == probe.TransportError.exit_code
        assert output["TRANSPORT_PROBE_FAILURE_PHASE"] == "TLS_HANDSHAKE"
        assert output["TLS_HANDSHAKE_FAILURE_CATEGORY"] == (
            "CERTIFICATE_VERIFICATION_ERROR"
        )
        assert output["PG_SSL_NEGOTIATED"] == "true"
        assert output["TLS_HANDSHAKE_COMPLETED"] == "false"
        assert output["TLS_HOSTNAME_VERIFIED"] == "false"
        assert output["SOCKET_CLOSED"] == "true"
        assert output["AUTHENTICATION_ATTEMPTED"] == "false"
        assert output["DATABASE_SESSION_ESTABLISHED"] == "false"
        assert output["SQL_EXECUTED"] == "false"
        assert output["OPERATIONAL_AUTHORIZATION"] == "false"
        assert output["NEXT_STAGE_AUTHORIZED"] == "false"
        assert HOST not in captured.out
        assert PROJECT_REF not in captured.out
        assert "Synthetic Test CA" not in captured.out
