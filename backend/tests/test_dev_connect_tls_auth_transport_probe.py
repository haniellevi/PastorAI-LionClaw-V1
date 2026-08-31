from __future__ import annotations

import ast
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import importlib.util
import os
from pathlib import Path
import socket
import ssl
import stat
import sys
import tempfile
import threading
from types import ModuleType
from typing import Any, Iterator

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_ROOT / "scripts" / "probe_dev_connect_tls_auth_transport.py"
PLAN_PATH = (
    BACKEND_ROOT.parent
    / "docs"
    / "governance"
    / "migrations"
    / "dev-connect-tls-auth-transport-probe-plan-v1.json"
)
HOST = "db.abcdefghijklmnopqrst.supabase.co"
PROJECT_REF = "abcdefghijklmnopqrst"
FIXED_NOW = datetime(2026, 8, 31, 15, 0, 0, tzinfo=timezone.utc)


def _load_module() -> ModuleType:
    name = "probe_dev_connect_tls_auth_transport_under_test"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = _load_module()
    monkeypatch.setattr(module, "_utc_now", lambda: FIXED_NOW)
    module._ATTEMPT_STATE.consumed = False
    for key in list(os.environ):
        upper = key.upper()
        if (
            upper.startswith("PG")
            or upper.startswith("SSL")
            or upper.startswith("OPENSSL")
            or upper.startswith("DYLD_")
            or upper in module.RELEVANT_ENV_NAMES
        ):
            monkeypatch.delenv(key, raising=False)
    return module


def _private_file(path: Path, raw: bytes) -> int:
    path.write_bytes(raw)
    path.chmod(0o600)
    return os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))


def _authorization_bytes(
    probe: ModuleType,
    *,
    runner_sha256: str,
    target_host_sha256: str,
    expected_project_ref_sha256: str,
    ca_sha256: str,
    nonce_sha256: str,
    overrides: dict[str, str] | None = None,
) -> bytes:
    values = {
        "authorization_contract": probe.AUTHORIZATION_CONTRACT,
        "gate": probe.AUTHORIZATION_GATE,
        "environment": "DEV",
        "owner": "OWNER-01",
        "executor": "CODEX-ROOT",
        "source_main_git_sha": probe.SOURCE_MAIN_GIT_SHA,
        "runner_sha256": runner_sha256,
        "probe_plan_sha256": probe.PLAN_SHA256,
        "target_host_sha256": target_host_sha256,
        "expected_project_ref_sha256": expected_project_ref_sha256,
        "tls_ca_certificate_sha256": ca_sha256,
        "nonce_sha256": nonce_sha256,
        "not_before": "2026-08-31T14:55:00Z",
        "not_after": "2026-08-31T15:05:00Z",
        "deadline_seconds": "5",
        "single_attempt": "true",
        "retry_allowed": "false",
        "fallback_allowed": "false",
        "password_allowed": "false",
        "authentication_allowed": "false",
        "database_session_allowed": "false",
        "sql_allowed": "false",
        "logs_allowed": "false",
        "prod_allowed": "false",
        "operational_authorization": "false",
        "next_stage_authorized": "false",
    }
    values.update(overrides or {})
    return (
        "".join(f"{key}={values[key]}\n" for key in probe.AUTHORIZATION_KEYS)
    ).encode("ascii")


def _generate_pki(directory: Path, hostname: str = HOST) -> tuple[Path, Path, Path]:
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Test CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_path = directory / "ca.crt"
    cert_path = directory / "server.crt"
    key_path = directory / "server-material.bin"
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    for path in (ca_path, cert_path, key_path):
        path.chmod(0o600)
    return ca_path, cert_path, key_path


class SyntheticPgTlsServer:
    def __init__(self, cert_path: Path, key_path: Path) -> None:
        self.ssl_request = b""
        self.post_tls_payload: bytes | None = None
        self.error: BaseException | None = None
        self._ready = threading.Event()
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self.port = self._server.getsockname()[1]
        self._server.listen(1)
        self._server.settimeout(10)
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._context.load_cert_chain(str(cert_path), str(key_path))
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        assert self._ready.wait(2)

    def _run(self) -> None:
        self._ready.set()
        connection: socket.socket | None = None
        tls_connection: ssl.SSLSocket | None = None
        try:
            connection, _address = self._server.accept()
            connection.settimeout(5)
            while len(self.ssl_request) < 8:
                chunk = connection.recv(8 - len(self.ssl_request))
                if not chunk:
                    break
                self.ssl_request += chunk
            connection.sendall(b"S")
            tls_connection = self._context.wrap_socket(connection, server_side=True)
            connection = None
            tls_connection.settimeout(5)
            try:
                self.post_tls_payload = tls_connection.recv(1)
            except OSError as exc:
                if exc.errno not in {errno.EBADF, errno.ECONNRESET, errno.EPIPE}:
                    raise
                self.post_tls_payload = b""
        except OSError as exc:
            # The client deliberately closes immediately after its handshake or
            # hostname decision. CPython 3.13 can surface that peer-close race as
            # EBADF while the server-side wrapper restores its timeout. The client
            # assertions still prove whether its handshake completed, so this
            # fixture records the absence of a StartupMessage and ignores only
            # that exact post-handshake teardown condition.
            if exc.errno == errno.EBADF:
                self.post_tls_payload = b""
            else:
                self.error = exc
        except BaseException as exc:  # captured for assertion in the test thread
            self.error = exc
        finally:
            for active in (tls_connection, connection):
                if active is not None:
                    try:
                        active.close()
                    except OSError:
                        pass
            self._server.close()

    def finish(self) -> None:
        self._thread.join(10)
        assert not self._thread.is_alive()
        if self.error is not None:
            raise self.error


@contextmanager
def _main_inputs(
    probe: ModuleType,
    directory: Path,
    ca_path: Path,
    *,
    authorization_overrides: dict[str, str] | None = None,
    expected_authorization_hash_override: str | None = None,
    pin_synthetic_project_ref: bool = True,
) -> Iterator[tuple[list[str], tuple[int, ...], dict[str, str]]]:
    expected_ref_hash = probe._component_sha256("PROJECT_REF", PROJECT_REF)
    original_expected_ref_hash = probe.EXPECTED_DEV_PROJECT_REF_SHA256
    if pin_synthetic_project_ref:
        probe.EXPECTED_DEV_PROJECT_REF_SHA256 = expected_ref_hash
    target_host_hash = probe._component_sha256("TARGET_HOST", HOST)
    nonce = bytes(range(32))
    nonce_hash = hashlib.sha256(nonce).hexdigest()
    ca_hash = hashlib.sha256(ca_path.read_bytes()).hexdigest()
    runner_hash = probe._runner_sha256()
    authorization = _authorization_bytes(
        probe,
        runner_sha256=runner_hash,
        target_host_sha256=target_host_hash,
        expected_project_ref_sha256=expected_ref_hash,
        ca_sha256=ca_hash,
        nonce_sha256=nonce_hash,
        overrides=authorization_overrides,
    )
    authorization_sha256 = hashlib.sha256(authorization).hexdigest()
    descriptors = (
        _private_file(directory / "host.input", HOST.encode("ascii")),
        _private_file(directory / "authorization.input", authorization),
        _private_file(
            directory / "authorization-hash.input",
            (
                expected_authorization_hash_override or authorization_sha256
            ).encode("ascii"),
        ),
        _private_file(directory / "project-ref-hash.input", expected_ref_hash.encode("ascii")),
        _private_file(directory / "nonce.input", nonce),
        os.open(ca_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)),
    )
    argv = [
        "--target-host-fd",
        str(descriptors[0]),
        "--authorization-record-fd",
        str(descriptors[1]),
        "--expected-authorization-record-sha256-fd",
        str(descriptors[2]),
        "--expected-project-ref-sha256-fd",
        str(descriptors[3]),
        "--nonce-fd",
        str(descriptors[4]),
        "--tls-ca-cert-fd",
        str(descriptors[5]),
        "--confirmation",
        probe.CONFIRMATION,
    ]
    try:
        yield argv, descriptors, {
            "runner": runner_hash,
            "authorization": authorization_sha256,
            "ref": expected_ref_hash,
            "host": target_host_hash,
            "ca": ca_hash,
            "nonce": nonce_hash,
        }
    finally:
        probe.EXPECTED_DEV_PROJECT_REF_SHA256 = original_expected_ref_hash
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _parse_output(raw: str) -> dict[str, str]:
    lines = raw.splitlines()
    assert all(line.count("=") == 1 for line in lines)
    result = dict(line.split("=", 1) for line in lines)
    assert len(result) == len(lines)
    return result


def test_source_and_plan_are_exactly_pinned(probe: ModuleType) -> None:
    assert probe.SOURCE_MAIN_GIT_SHA == "36f8d13284a8f4964d0258a2a3b845323a80fe7e"
    assert probe.PLAN_SHA256 == hashlib.sha256(PLAN_PATH.read_bytes()).hexdigest()
    assert probe.EXPECTED_DEV_PROJECT_REF_SHA256 == (
        "7aa91c30e6951cabf8f094a88b62f2b5d2e486cf306ba8596fd89c5850713fd9"
    )
    assert probe.SSL_REQUEST == bytes.fromhex("0000000804d2162f")
    assert probe.PORT == 5432
    probe._load_plan_contract()


def test_ast_has_only_stdlib_transport_and_no_database_or_process_clients() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {
        "psycopg",
        "psycopg2",
        "sqlalchemy",
        "requests",
        "urllib",
        "httpx",
        "aiohttp",
        "subprocess",
        "asyncio",
    }
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "StartupMessage" in source
    assert ".execute(" not in source
    assert "SELECT " not in source.upper()
    assert "password-fd" not in source
    assert "database-url" not in source
    assert "cxmjojnocigekgcxhubi" not in source


def test_cli_exposes_only_private_descriptors_and_confirmation(probe: ModuleType) -> None:
    parser = probe._build_parser()
    destinations = {action.dest for action in parser._actions}
    assert destinations == {
        "target_host_fd",
        "authorization_record_fd",
        "expected_authorization_record_sha256_fd",
        "expected_project_ref_sha256_fd",
        "nonce_fd",
        "tls_ca_cert_fd",
        "confirmation",
    }


@pytest.mark.parametrize(
    "host",
    [
        "db.short.supabase.co",
        "db.ABCDEFGHIJKLMNOPQRST.supabase.co",
        "db.abcdefghijklmnopqrst.supabase.com",
        "aws-1-us-east-1.pooler.supabase.com",
        "127.0.0.1",
        "localhost",
        "db.abcdefghijklmnopqrst.supabase.co.",
        "db.abcdefghijklmnopqrst.supabase.co:5432",
    ],
)
def test_target_host_contract_rejects_every_noncanonical_form(
    probe: ModuleType,
    host: str,
) -> None:
    expected = probe._component_sha256("PROJECT_REF", PROJECT_REF)
    with pytest.raises(probe.InputError):
        probe._decode_target_host(host.encode("ascii"), expected_project_ref_sha256=expected)


def test_target_host_is_bound_to_framed_project_ref_and_host_hash(probe: ModuleType) -> None:
    expected = probe._component_sha256("PROJECT_REF", PROJECT_REF)
    host, host_hash = probe._decode_target_host(
        HOST.encode("ascii"),
        expected_project_ref_sha256=expected,
    )
    assert host == HOST
    assert host_hash == probe._component_sha256("TARGET_HOST", HOST)
    assert PROJECT_REF not in host_hash
    with pytest.raises(probe.InputError):
        probe._decode_target_host(
            HOST.encode("ascii"),
            expected_project_ref_sha256="0" * 64,
        )


@pytest.mark.parametrize(
    ("pattern", "hostname", "expected"),
    [
        (HOST, HOST, True),
        (HOST.upper(), HOST, True),
        ("*.supabase.co", HOST, False),
        ("*.abcdefghijklmnopqrst.supabase.co", HOST, True),
        ("*.*.supabase.co", HOST, False),
        ("db.otherproject0000000.supabase.co", HOST, False),
        ("", HOST, False),
    ],
)
def test_dns_san_matcher_is_strict(
    probe: ModuleType,
    pattern: str,
    hostname: str,
    expected: bool,
) -> None:
    assert probe._dnsname_matches(pattern, hostname) is expected


def test_hostname_verification_requires_dns_san_and_never_uses_common_name(
    probe: ModuleType,
) -> None:
    probe._verify_hostname({"subjectAltName": (("DNS", HOST),)}, HOST)
    with pytest.raises(probe.TransportError):
        probe._verify_hostname({"subject": (("commonName", HOST),)}, HOST)
    with pytest.raises(probe.TransportError):
        probe._verify_hostname({"subjectAltName": (("IP Address", "127.0.0.1"),)}, HOST)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.1",
        "169.254.1.1",
        "::1",
        "fe80::1",
        "0.0.0.0",
    ],
)
def test_address_policy_rejects_non_global_addresses_in_public_mode(
    probe: ModuleType,
    address: str,
) -> None:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr: tuple[Any, ...] = (address, 5432, 0, 0) if family == socket.AF_INET6 else (address, 5432)
    with pytest.raises(probe.TransportError):
        probe._normalize_addresses(
            [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)],
            test_loopback_allowed=False,
        )


def test_loopback_is_allowed_only_by_unreachable_cli_sentinel(probe: ModuleType) -> None:
    record = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 5432))
    assert probe._normalize_addresses([record], test_loopback_allowed=True)
    with pytest.raises(probe.TransportError):
        probe._normalize_addresses([record], test_loopback_allowed=False)
    assert "test" not in {action.dest for action in probe._build_parser()._actions}


def test_address_selection_is_unique_and_deterministic(probe: ModuleType) -> None:
    records = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 5432)),
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("1.1.1.1", 5432)),
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 5432)),
    ]
    selected = probe._normalize_addresses(records, test_loopback_allowed=False)
    assert selected == [
        (socket.AF_INET, ("1.1.1.1", 5432)),
        (socket.AF_INET, ("8.8.8.8", 5432)),
    ]


@pytest.mark.parametrize(
    "key",
    [
        "authorization_contract",
        "gate",
        "environment",
        "owner",
        "executor",
        "source_main_git_sha",
        "runner_sha256",
        "probe_plan_sha256",
        "target_host_sha256",
        "expected_project_ref_sha256",
        "tls_ca_certificate_sha256",
        "nonce_sha256",
        "single_attempt",
        "retry_allowed",
        "fallback_allowed",
        "password_allowed",
        "authentication_allowed",
        "database_session_allowed",
        "sql_allowed",
        "logs_allowed",
        "prod_allowed",
        "operational_authorization",
        "next_stage_authorized",
    ],
)
def test_authorization_fails_closed_for_every_bound_field(
    probe: ModuleType,
    key: str,
) -> None:
    runner = probe._runner_sha256()
    ref_hash = probe._component_sha256("PROJECT_REF", PROJECT_REF)
    host_hash = probe._component_sha256("TARGET_HOST", HOST)
    ca_hash = "1" * 64
    nonce_hash = "2" * 64
    raw = _authorization_bytes(
        probe,
        runner_sha256=runner,
        target_host_sha256=host_hash,
        expected_project_ref_sha256=ref_hash,
        ca_sha256=ca_hash,
        nonce_sha256=nonce_hash,
        overrides={key: "tampered"},
    )
    with pytest.raises(probe.AuthorizationError):
        probe._parse_authorization(
            raw,
            runner_sha256=runner,
            target_host_sha256=host_hash,
            expected_project_ref_sha256=ref_hash,
            ca_sha256=ca_hash,
            nonce_sha256=nonce_hash,
            now=FIXED_NOW,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"not_before": "2026-08-31T15:01:00Z"},
        {"not_after": "2026-08-31T14:59:59Z"},
        {"not_after": "2026-08-31T15:30:00Z"},
        {"not_after": "bad"},
        {"deadline_seconds": "0"},
        {"deadline_seconds": "16"},
        {"deadline_seconds": "5.0"},
    ],
)
def test_authorization_window_and_deadline_are_closed(
    probe: ModuleType,
    overrides: dict[str, str],
) -> None:
    runner = probe._runner_sha256()
    ref_hash = probe._component_sha256("PROJECT_REF", PROJECT_REF)
    host_hash = probe._component_sha256("TARGET_HOST", HOST)
    raw = _authorization_bytes(
        probe,
        runner_sha256=runner,
        target_host_sha256=host_hash,
        expected_project_ref_sha256=ref_hash,
        ca_sha256="1" * 64,
        nonce_sha256="2" * 64,
        overrides=overrides,
    )
    with pytest.raises(probe.AuthorizationError):
        probe._parse_authorization(
            raw,
            runner_sha256=runner,
            target_host_sha256=host_hash,
            expected_project_ref_sha256=ref_hash,
            ca_sha256="1" * 64,
            nonce_sha256="2" * 64,
            now=FIXED_NOW,
        )


def test_authorization_rejects_reordering_duplicates_and_raw_sensitive_fields(
    probe: ModuleType,
) -> None:
    runner = probe._runner_sha256()
    ref_hash = probe._component_sha256("PROJECT_REF", PROJECT_REF)
    host_hash = probe._component_sha256("TARGET_HOST", HOST)
    base = _authorization_bytes(
        probe,
        runner_sha256=runner,
        target_host_sha256=host_hash,
        expected_project_ref_sha256=ref_hash,
        ca_sha256="1" * 64,
        nonce_sha256="2" * 64,
    )
    variants = (
        b"\n".join(reversed(base.splitlines())) + b"\n",
        base + b"environment=DEV\n",
        base + f"hostname={HOST}\n".encode(),
        base + b"password=secret\n",
        base.replace(b"\n", b"\r\n"),
    )
    for raw in variants:
        with pytest.raises(probe.AuthorizationError):
            probe._parse_authorization(
                raw,
                runner_sha256=runner,
                target_host_sha256=host_hash,
                expected_project_ref_sha256=ref_hash,
                ca_sha256="1" * 64,
                nonce_sha256="2" * 64,
                now=FIXED_NOW,
            )


def test_expected_authorization_digest_mismatch_blocks_before_dns(
    probe: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with tempfile.TemporaryDirectory(prefix="pastorai-transport-probe-") as raw_dir:
        directory = Path(raw_dir)
        ca_path, _cert_path, _key_path = _generate_pki(directory)
        resolver_calls = 0

        def resolver(*_args: Any) -> list[Any]:
            nonlocal resolver_calls
            resolver_calls += 1
            raise AssertionError("DNS must not run")

        with _main_inputs(
            probe,
            directory,
            ca_path,
            expected_authorization_hash_override="0" * 64,
        ) as (argv, _descriptors, _expected):
            assert probe.main(argv, _resolver=resolver) == probe.AuthorizationError.exit_code
        output = _parse_output(capsys.readouterr().out)
        assert resolver_calls == 0
        assert output["TRANSPORT_PROBE_FAILURE_PHASE"] == "PRECONNECT_GUARDS"
        assert output["DNS_RESOLVED"] == "false"


def test_compiled_dev_project_hash_blocks_target_swap_before_dns(
    probe: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with tempfile.TemporaryDirectory(prefix="pastorai-transport-probe-") as raw_dir:
        directory = Path(raw_dir)
        ca_path, _cert_path, _key_path = _generate_pki(directory)
        resolver_calls = 0

        def resolver(*_args: Any) -> list[Any]:
            nonlocal resolver_calls
            resolver_calls += 1
            raise AssertionError("DNS must not run")

        with _main_inputs(
            probe,
            directory,
            ca_path,
            pin_synthetic_project_ref=False,
        ) as (argv, _descriptors, _expected):
            assert probe.main(argv, _resolver=resolver) == probe.InputError.exit_code
        output = _parse_output(capsys.readouterr().out)
        assert resolver_calls == 0
        assert output["TRANSPORT_PROBE_FAILURE_PHASE"] == "PRECONNECT_GUARDS"
        assert output["DNS_RESOLVED"] == "false"


def test_ca_fd_requires_regular_readonly_private_single_link(probe: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "ca.crt"
    path.write_bytes(b"synthetic-ca")
    path.chmod(0o600)
    descriptor = os.open(path, os.O_RDONLY)
    try:
        witness = probe._witness_ca_fd(descriptor)
        assert witness.sha256 == hashlib.sha256(b"synthetic-ca").hexdigest()
        probe._revalidate_ca_fd(witness)
    finally:
        os.close(descriptor)
    path.chmod(0o640)
    descriptor = os.open(path, os.O_RDONLY)
    try:
        with pytest.raises(probe.InputError):
            probe._witness_ca_fd(descriptor)
    finally:
        os.close(descriptor)


def test_ca_fd_rejects_writable_hardlink_empty_and_offset(probe: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "ca.crt"
    path.write_bytes(b"synthetic-ca")
    path.chmod(0o600)
    hardlink = tmp_path / "ca-copy.crt"
    os.link(path, hardlink)
    descriptor = os.open(path, os.O_RDONLY)
    try:
        with pytest.raises(probe.InputError):
            probe._witness_ca_fd(descriptor)
    finally:
        os.close(descriptor)
    hardlink.unlink()
    descriptor = os.open(path, os.O_RDWR)
    try:
        with pytest.raises(probe.InputError):
            probe._witness_ca_fd(descriptor)
    finally:
        os.close(descriptor)
    path.write_bytes(b"")
    descriptor = os.open(path, os.O_RDONLY)
    try:
        with pytest.raises(probe.InputError):
            probe._witness_ca_fd(descriptor)
    finally:
        os.close(descriptor)
    path.write_bytes(b"synthetic-ca")
    descriptor = os.open(path, os.O_RDONLY)
    os.lseek(descriptor, 1, os.SEEK_SET)
    try:
        with pytest.raises(probe.InputError):
            probe._witness_ca_fd(descriptor)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    "name",
    [
        "PGHOST",
        "SSL_CERT_FILE",
        "OPENSSL_CONF",
        "DATABASE_URL",
        "SUPABASE_DB_URL",
        "HOSTALIASES",
        "LOCALDOMAIN",
        "RES_OPTIONS",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
    ],
)
def test_relevant_inherited_environment_is_rejected_before_network(
    probe: ModuleType,
    name: str,
) -> None:
    with pytest.raises(probe.InputError):
        probe._assert_clean_environment({name: "sensitive"})


def test_full_main_loopback_sends_only_sslrequest_and_no_startup_message(
    probe: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with tempfile.TemporaryDirectory(prefix="pastorai-transport-probe-") as raw_dir:
        directory = Path(raw_dir)
        ca_path, cert_path, key_path = _generate_pki(directory)
        server = SyntheticPgTlsServer(cert_path, key_path)
        server.start()

        def resolver(
            _host: str,
            _port: int,
            _family: int,
            _socktype: int,
            _protocol: int,
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

        with _main_inputs(probe, directory, ca_path) as (argv, descriptors, expected):
            names_before = {path.name for path in directory.iterdir()}
            descriptor_snapshots = {
                descriptor: os.fstat(descriptor) for descriptor in descriptors
            }
            exit_code = probe.main(
                argv,
                _resolver=resolver,
                _port=server.port,
                _test_only_loopback_sentinel=probe._TEST_ONLY_LOOPBACK_SENTINEL,
            )
            assert exit_code == 0
            for descriptor in descriptors:
                try:
                    reopened = os.fstat(descriptor)
                except OSError as exc:
                    assert exc.errno == errno.EBADF
                else:
                    original = descriptor_snapshots[descriptor]
                    assert (
                        reopened.st_dev,
                        reopened.st_ino,
                        reopened.st_mode,
                    ) != (
                        original.st_dev,
                        original.st_ino,
                        original.st_mode,
                    )
            assert {path.name for path in directory.iterdir()} == names_before
        server.finish()
        captured = capsys.readouterr()
        assert captured.err == ""
        output = _parse_output(captured.out)
        assert output["RESULT"] == "DEV_CONNECT_TLS_AUTH_TRANSPORT_OBSERVED_NOT_HISTORICAL_CAUSE"
        assert output["RUNNER_SHA256"] == expected["runner"]
        assert output["AUTHORIZATION_RECORD_SHA256"] == expected["authorization"]
        assert output["EXPECTED_PROJECT_REF_SHA256"] == expected["ref"]
        assert output["TARGET_HOST_SHA256"] == expected["host"]
        assert output["TLS_CA_CERTIFICATE_SHA256"] == expected["ca"]
        assert output["ATTEMPT_NONCE_SHA256"] == expected["nonce"]
        assert output["TLS_MODE"] == "VERIFY_FULL_EXPLICIT_CA"
        assert output["HISTORICAL_FAILURE_PHASE"] == "CONNECT_TLS_AUTH"
        assert output["HISTORICAL_AUTHENTICATION_OUTCOME"] == "UNKNOWN"
        assert output["ROOT_CAUSE"] == "UNDETERMINED"
        assert output["AUTHENTICATION_ATTEMPTED"] == "false"
        assert output["DATABASE_SESSION_ESTABLISHED"] == "false"
        assert output["SQL_EXECUTED"] == "false"
        assert output["LOGS_QUERIED"] == "false"
        assert output["OPERATIONAL_AUTHORIZATION"] == "false"
        assert output["NEXT_STAGE_AUTHORIZED"] == "false"
        assert output["DNS_RESOLVED"] == "true"
        assert output["ADDRESS_POLICY_PASSED"] == "true"
        assert output["TCP_CONNECTED"] == "true"
        assert output["PG_SSL_NEGOTIATED"] == "true"
        assert output["TLS_HANDSHAKE_COMPLETED"] == "true"
        assert output["TLS_HANDSHAKE_FAILURE_CATEGORY"] == "NOT_APPLICABLE"
        assert output["TLS_HOSTNAME_VERIFIED"] == "true"
        assert output["SOCKET_CLOSED"] == "true"
        assert output["TRANSPORT_PROBE_PHASE"] == "SOCKET_CLOSE"
        assert HOST not in captured.out
        assert PROJECT_REF not in captured.out
        assert server.ssl_request == probe.SSL_REQUEST
        assert server.post_tls_payload == b""


def test_hostname_mismatch_blocks_after_verified_chain_without_leaking(
    probe: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wrong_host = "db.zzzzzzzzzzzzzzzzzzzz.supabase.co"
    with tempfile.TemporaryDirectory(prefix="pastorai-transport-probe-") as raw_dir:
        directory = Path(raw_dir)
        ca_path, cert_path, key_path = _generate_pki(directory, wrong_host)
        server = SyntheticPgTlsServer(cert_path, key_path)
        server.start()

        def resolver(*_args: Any) -> list[tuple[int, int, int, str, tuple[Any, ...]]]:
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", server.port))]

        with _main_inputs(probe, directory, ca_path) as (argv, _descriptors, _expected):
            exit_code = probe.main(
                argv,
                _resolver=resolver,
                _port=server.port,
                _test_only_loopback_sentinel=probe._TEST_ONLY_LOOPBACK_SENTINEL,
            )
            assert exit_code == probe.TransportError.exit_code
        server.finish()
        captured = capsys.readouterr()
        output = _parse_output(captured.out)
        assert output["TRANSPORT_PROBE_FAILURE_PHASE"] == "TLS_HOSTNAME_VERIFICATION"
        assert output["TLS_HANDSHAKE_COMPLETED"] == "true"
        assert output["TLS_HANDSHAKE_FAILURE_CATEGORY"] == "NOT_APPLICABLE"
        assert output["TLS_HOSTNAME_VERIFIED"] == "false"
        assert output["SOCKET_CLOSED"] == "true"
        assert HOST not in captured.out
        assert wrong_host not in captured.out


def test_dns_failure_is_sanitized_and_preserves_deny_state(
    probe: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with tempfile.TemporaryDirectory(prefix="pastorai-transport-probe-") as raw_dir:
        directory = Path(raw_dir)
        ca_path, _cert_path, _key_path = _generate_pki(directory)

        def resolver(*_args: Any) -> list[Any]:
            raise socket.gaierror("secret-host password credential ip")

        with _main_inputs(probe, directory, ca_path) as (argv, _descriptors, _expected):
            exit_code = probe.main(
                argv,
                _resolver=resolver,
                _test_only_loopback_sentinel=probe._TEST_ONLY_LOOPBACK_SENTINEL,
            )
            assert exit_code == probe.TransportError.exit_code
        captured = capsys.readouterr()
        output = _parse_output(captured.out)
        assert output["TRANSPORT_PROBE_FAILURE_PHASE"] == "DNS_RESOLUTION"
        assert output["DNS_RESOLVED"] == "false"
        assert output["SOCKET_CLOSED"] == "true"
        assert output["OPERATIONAL_AUTHORIZATION"] == "false"
        assert output["NEXT_STAGE_AUTHORIZED"] == "false"
        assert "secret-host" not in captured.out
        assert "credential" not in captured.out
        assert captured.err == ""


def test_private_address_blocks_before_socket_creation(
    probe: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with tempfile.TemporaryDirectory(prefix="pastorai-transport-probe-") as raw_dir:
        directory = Path(raw_dir)
        ca_path, _cert_path, _key_path = _generate_pki(directory)
        socket_calls = 0

        def resolver(*_args: Any) -> list[tuple[int, int, int, str, tuple[Any, ...]]]:
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.1", 5432))]

        def socket_factory(*_args: Any) -> socket.socket:
            nonlocal socket_calls
            socket_calls += 1
            raise AssertionError("socket must not be created")

        with _main_inputs(probe, directory, ca_path) as (argv, _descriptors, _expected):
            exit_code = probe.main(argv, _resolver=resolver, _socket_factory=socket_factory)
            assert exit_code == probe.TransportError.exit_code
        output = _parse_output(capsys.readouterr().out)
        assert socket_calls == 0
        assert output["TRANSPORT_PROBE_FAILURE_PHASE"] == "ADDRESS_POLICY"
        assert output["DNS_RESOLVED"] == "true"
        assert output["ADDRESS_POLICY_PASSED"] == "false"


class FakeRawSocket:
    def __init__(
        self,
        *,
        connect_error: BaseException | None = None,
        send_error: BaseException | None = None,
        recv_error: BaseException | None = None,
        response: bytes = b"S",
        close_error: bool = False,
    ) -> None:
        self.connect_error = connect_error
        self.send_error = send_error
        self.recv_error = recv_error
        self.response = response
        self.close_error = close_error
        self.connected_to: tuple[Any, ...] | None = None
        self.sent = b""
        self.closed = False

    def settimeout(self, _timeout: float) -> None:
        return None

    def connect(self, sockaddr: tuple[Any, ...]) -> None:
        self.connected_to = sockaddr
        if self.connect_error is not None:
            raise self.connect_error

    def sendall(self, raw: bytes) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent += raw

    def recv(self, _size: int) -> bytes:
        if self.recv_error is not None:
            raise self.recv_error
        return self.response

    def close(self) -> None:
        if self.close_error:
            raise OSError("secret close failure")
        self.closed = True


class FakeTlsSocket:
    def __init__(
        self,
        raw_socket: FakeRawSocket,
        *,
        handshake_error: BaseException | None = None,
        certificate: dict[str, Any] | None = None,
        close_error: bool = False,
    ) -> None:
        self.raw_socket = raw_socket
        self.handshake_error = handshake_error
        self.certificate = certificate or {"subjectAltName": (("DNS", HOST),)}
        self.close_error = close_error

    def settimeout(self, _timeout: float) -> None:
        return None

    def do_handshake(self) -> None:
        if self.handshake_error is not None:
            raise self.handshake_error

    def getpeercert(self) -> dict[str, Any]:
        return self.certificate

    def close(self) -> None:
        if self.close_error:
            raise OSError("secret close failure")
        self.raw_socket.closed = True


class FakeTlsContext:
    def __init__(
        self,
        *,
        handshake_error: BaseException | None = None,
        certificate: dict[str, Any] | None = None,
        close_error: bool = False,
    ) -> None:
        self.handshake_error = handshake_error
        self.certificate = certificate
        self.close_error = close_error

    def wrap_socket(
        self,
        raw_socket: FakeRawSocket,
        *,
        server_hostname: str,
        do_handshake_on_connect: bool,
    ) -> FakeTlsSocket:
        assert server_hostname == HOST
        assert do_handshake_on_connect is False
        return FakeTlsSocket(
            raw_socket,
            handshake_error=self.handshake_error,
            certificate=self.certificate,
            close_error=self.close_error,
        )


def _global_resolver(*_args: Any) -> list[tuple[int, int, int, str, tuple[Any, ...]]]:
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("8.8.8.8", 5432),
        )
    ]


def _dummy_ca(probe: ModuleType) -> Any:
    return probe.CaWitness(99, (1,) * 9, 1, 0, "0" * 64)


def test_tcp_failure_wins_over_later_close_failure_and_is_sanitized(
    probe: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_socket = FakeRawSocket(
        connect_error=OSError("secret endpoint credential"),
        close_error=True,
    )
    monkeypatch.setattr(probe, "_build_tls_context", lambda _ca: FakeTlsContext())
    state = probe.ProbeState()
    with pytest.raises(probe.TransportError) as exc_info:
        probe._run_transport_probe(
            hostname=HOST,
            ca_witness=_dummy_ca(probe),
            deadline_seconds=2,
            state=state,
            resolver=_global_resolver,
            socket_factory=lambda *_args: raw_socket,
        )
    assert exc_info.value.failure_phase == "TCP_CONNECT"
    assert state.dns_resolved is True
    assert state.address_policy_passed is True
    assert state.tcp_connected is False
    assert state.socket_closed is False


def test_pg_ssl_negotiation_rejects_non_s_response_and_sends_exactly_eight_bytes(
    probe: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_socket = FakeRawSocket(response=b"N")
    monkeypatch.setattr(probe, "_build_tls_context", lambda _ca: FakeTlsContext())
    state = probe.ProbeState()
    with pytest.raises(probe.TransportError) as exc_info:
        probe._run_transport_probe(
            hostname=HOST,
            ca_witness=_dummy_ca(probe),
            deadline_seconds=2,
            state=state,
            resolver=_global_resolver,
            socket_factory=lambda *_args: raw_socket,
        )
    assert exc_info.value.failure_phase == "PG_SSL_NEGOTIATION"
    assert raw_socket.sent == probe.SSL_REQUEST
    assert len(raw_socket.sent) == 8
    assert state.tcp_connected is True
    assert state.pg_ssl_negotiated is False
    assert state.socket_closed is True


def test_tls_handshake_failure_is_separate_from_hostname_verification(
    probe: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_socket = FakeRawSocket()
    monkeypatch.setattr(
        probe,
        "_build_tls_context",
        lambda _ca: FakeTlsContext(handshake_error=ssl.SSLError("secret ca")),
    )
    state = probe.ProbeState()
    with pytest.raises(probe.TransportError) as exc_info:
        probe._run_transport_probe(
            hostname=HOST,
            ca_witness=_dummy_ca(probe),
            deadline_seconds=2,
            state=state,
            resolver=_global_resolver,
            socket_factory=lambda *_args: raw_socket,
        )
    assert exc_info.value.failure_phase == "TLS_HANDSHAKE"
    assert state.pg_ssl_negotiated is True
    assert state.tls_handshake_completed is False
    assert state.tls_handshake_failure_category == "TLS_PROTOCOL_ERROR"
    assert state.tls_hostname_verified is False
    assert state.socket_closed is True


@pytest.mark.parametrize(
    ("error_kind", "expected_category"),
    [
        ("certificate", "CERTIFICATE_VERIFICATION_ERROR"),
        ("protocol", "TLS_PROTOCOL_ERROR"),
        ("transport", "TRANSPORT_IO_ERROR"),
        ("local", "LOCAL_VALIDATION_ERROR"),
        ("deadline", "DEADLINE_EXCEEDED"),
    ],
)
def test_tls_handshake_failure_category_is_static_and_never_leaks_exception(
    probe: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    error_kind: str,
    expected_category: str,
) -> None:
    errors: dict[str, BaseException] = {
        "certificate": ssl.SSLCertVerificationError(1, "secret certificate"),
        "protocol": ssl.SSLError("secret protocol"),
        "transport": OSError("secret endpoint"),
        "local": ValueError("secret hostname"),
        "deadline": probe.DeadlineError(),
    }
    raw_socket = FakeRawSocket()
    monkeypatch.setattr(
        probe,
        "_build_tls_context",
        lambda _ca: FakeTlsContext(handshake_error=errors[error_kind]),
    )
    state = probe.ProbeState()
    with pytest.raises(probe.ProbeError) as exc_info:
        probe._run_transport_probe(
            hostname=HOST,
            ca_witness=_dummy_ca(probe),
            deadline_seconds=2,
            state=state,
            resolver=_global_resolver,
            socket_factory=lambda *_args: raw_socket,
        )
    assert exc_info.value.failure_phase == "TLS_HANDSHAKE"
    assert state.tls_handshake_failure_category == expected_category
    output = "\n".join(probe._state_lines(state))
    assert output.count("TLS_HANDSHAKE_FAILURE_CATEGORY=") == 1
    assert "secret" not in output


@pytest.mark.parametrize(
    ("operation", "expected_phase", "expected_category"),
    [
        ("dns", "DNS_RESOLUTION", "NOT_APPLICABLE"),
        ("tcp", "TCP_CONNECT", "NOT_APPLICABLE"),
        ("ssl_request_send", "PG_SSL_NEGOTIATION", "NOT_APPLICABLE"),
        ("ssl_request_recv", "PG_SSL_NEGOTIATION", "NOT_APPLICABLE"),
        ("tls_handshake", "TLS_HANDSHAKE", "DEADLINE_EXCEEDED"),
    ],
)
def test_socket_timeout_is_deadline_before_generic_oserror_at_each_boundary(
    probe: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    operation: str,
    expected_phase: str,
    expected_category: str,
) -> None:
    timeout_error: TimeoutError
    if operation in {"dns", "ssl_request_recv", "tls_handshake"}:
        timeout_error = socket.timeout("secret timeout host credential")
    else:
        timeout_error = TimeoutError("secret timeout host credential")

    resolver = _global_resolver
    raw_socket = FakeRawSocket(
        connect_error=timeout_error if operation == "tcp" else None,
        send_error=timeout_error if operation == "ssl_request_send" else None,
        recv_error=timeout_error if operation == "ssl_request_recv" else None,
    )
    if operation == "dns":

        def timeout_resolver(*_args: Any) -> list[Any]:
            raise timeout_error

        resolver = timeout_resolver
    handshake_error = timeout_error if operation == "tls_handshake" else None
    monkeypatch.setattr(
        probe,
        "_build_tls_context",
        lambda _ca: FakeTlsContext(handshake_error=handshake_error),
    )
    state = probe.ProbeState()

    with pytest.raises(probe.DeadlineError) as exc_info:
        probe._run_transport_probe(
            hostname=HOST,
            ca_witness=_dummy_ca(probe),
            deadline_seconds=2,
            state=state,
            resolver=resolver,
            socket_factory=lambda *_args: raw_socket,
        )

    assert exc_info.value.failure_phase == expected_phase
    assert exc_info.value.reason == "DEADLINE_EXCEEDED"
    assert str(exc_info.value) == ""
    assert state.tls_handshake_failure_category == expected_category
    probe._print_blocked(exc_info.value.reason, expected_phase, state)
    output = capsys.readouterr().out
    assert output.count("TLS_HANDSHAKE_FAILURE_CATEGORY=") == 1
    assert f"TLS_HANDSHAKE_FAILURE_CATEGORY={expected_category}" in output
    assert output.count("TRANSPORT_PROBE_FAILURE_PHASE=") == 1
    assert f"TRANSPORT_PROBE_FAILURE_PHASE={expected_phase}" in output
    assert output.endswith(
        "RESULT=BLOCKED_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE:DEADLINE_EXCEEDED\n"
    )
    assert "secret" not in output
    assert HOST not in output
    assert PROJECT_REF not in output


def test_socket_timeout_during_hostname_verification_preserves_phase_and_sanitization(
    probe: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_socket = FakeRawSocket()
    monkeypatch.setattr(probe, "_build_tls_context", lambda _ca: FakeTlsContext())

    def timeout_hostname_verification(
        _certificate: dict[str, Any],
        _hostname: str,
    ) -> None:
        raise socket.timeout("secret hostname timeout credential")

    monkeypatch.setattr(probe, "_verify_hostname", timeout_hostname_verification)
    state = probe.ProbeState()

    with pytest.raises(probe.DeadlineError) as exc_info:
        probe._run_transport_probe(
            hostname=HOST,
            ca_witness=_dummy_ca(probe),
            deadline_seconds=2,
            state=state,
            resolver=_global_resolver,
            socket_factory=lambda *_args: raw_socket,
        )

    assert exc_info.value.failure_phase == "TLS_HOSTNAME_VERIFICATION"
    assert exc_info.value.reason == "DEADLINE_EXCEEDED"
    assert str(exc_info.value) == ""
    assert state.tls_handshake_completed is True
    assert state.tls_handshake_failure_category == "NOT_APPLICABLE"
    assert state.tls_hostname_verified is False
    assert state.socket_closed is True
    probe._print_blocked(exc_info.value.reason, exc_info.value.failure_phase, state)
    output = capsys.readouterr().out
    assert "TRANSPORT_PROBE_FAILURE_PHASE=TLS_HOSTNAME_VERIFICATION" in output
    assert "TLS_HANDSHAKE_FAILURE_CATEGORY=NOT_APPLICABLE" in output
    assert output.endswith(
        "RESULT=BLOCKED_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE:DEADLINE_EXCEEDED\n"
    )
    assert "secret" not in output
    assert HOST not in output
    assert PROJECT_REF not in output


def test_primary_handshake_timeout_wins_over_later_socket_close_failure(
    probe: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_socket = FakeRawSocket()
    monkeypatch.setattr(
        probe,
        "_build_tls_context",
        lambda _ca: FakeTlsContext(
            handshake_error=socket.timeout("secret primary timeout credential"),
            close_error=True,
        ),
    )
    state = probe.ProbeState()

    with pytest.raises(probe.DeadlineError) as exc_info:
        probe._run_transport_probe(
            hostname=HOST,
            ca_witness=_dummy_ca(probe),
            deadline_seconds=2,
            state=state,
            resolver=_global_resolver,
            socket_factory=lambda *_args: raw_socket,
        )

    assert exc_info.value.failure_phase == "TLS_HANDSHAKE"
    assert exc_info.value.reason == "DEADLINE_EXCEEDED"
    assert str(exc_info.value) == ""
    assert state.pg_ssl_negotiated is True
    assert state.tls_handshake_completed is False
    assert state.tls_handshake_failure_category == "DEADLINE_EXCEEDED"
    assert state.tls_hostname_verified is False
    assert state.socket_closed is False
    probe._print_blocked(exc_info.value.reason, exc_info.value.failure_phase, state)
    output = capsys.readouterr().out
    assert output.count("TRANSPORT_PROBE_FAILURE_PHASE=") == 1
    assert "TRANSPORT_PROBE_FAILURE_PHASE=TLS_HANDSHAKE" in output
    assert "TRANSPORT_PROBE_FAILURE_PHASE=SOCKET_CLOSE" not in output
    assert "TLS_HANDSHAKE_FAILURE_CATEGORY=DEADLINE_EXCEEDED" in output
    assert "SOCKET_CLOSED=false" in output
    assert output.endswith(
        "RESULT=BLOCKED_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE:DEADLINE_EXCEEDED\n"
    )
    assert "secret" not in output
    assert HOST not in output
    assert PROJECT_REF not in output


def test_isolated_socket_close_failure_has_own_phase(
    probe: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_socket = FakeRawSocket()
    monkeypatch.setattr(
        probe,
        "_build_tls_context",
        lambda _ca: FakeTlsContext(close_error=True),
    )
    state = probe.ProbeState()
    with pytest.raises(probe.CleanupError) as exc_info:
        probe._run_transport_probe(
            hostname=HOST,
            ca_witness=_dummy_ca(probe),
            deadline_seconds=2,
            state=state,
            resolver=_global_resolver,
            socket_factory=lambda *_args: raw_socket,
        )
    assert exc_info.value.failure_phase == "SOCKET_CLOSE"
    assert state.tls_hostname_verified is True
    assert state.socket_closed is False


def test_overall_deadline_interrupts_dns_without_starting_tcp(
    probe: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe, "_build_tls_context", lambda _ca: FakeTlsContext())
    socket_calls = 0

    def slow_resolver(*_args: Any) -> list[Any]:
        probe.time.sleep(2)
        return []

    def socket_factory(*_args: Any) -> FakeRawSocket:
        nonlocal socket_calls
        socket_calls += 1
        return FakeRawSocket()

    state = probe.ProbeState()
    with pytest.raises(probe.DeadlineError) as exc_info:
        probe._run_transport_probe(
            hostname=HOST,
            ca_witness=_dummy_ca(probe),
            deadline_seconds=1,
            state=state,
            resolver=slow_resolver,
            socket_factory=socket_factory,
        )
    assert exc_info.value.failure_phase == "DNS_RESOLUTION"
    assert socket_calls == 0
    assert state.dns_resolved is False
    assert state.socket_closed is True


def test_post_transport_ca_drift_blocks_success_at_socket_close_boundary(
    probe: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with tempfile.TemporaryDirectory(prefix="pastorai-transport-probe-") as raw_dir:
        directory = Path(raw_dir)
        ca_path, _cert_path, _key_path = _generate_pki(directory)
        revalidations = 0

        def revalidate(_witness: Any) -> None:
            nonlocal revalidations
            revalidations += 1
            if revalidations >= 2:
                raise probe.InputError

        def fake_transport(**kwargs: Any) -> None:
            state = kwargs["state"]
            state.dns_resolved = True
            state.address_policy_passed = True
            state.tcp_connected = True
            state.pg_ssl_negotiated = True
            state.tls_handshake_completed = True
            state.tls_hostname_verified = True
            state.socket_closed = True

        monkeypatch.setattr(probe, "_revalidate_ca_fd", revalidate)
        monkeypatch.setattr(probe, "_run_transport_probe", fake_transport)
        with _main_inputs(probe, directory, ca_path) as (argv, _descriptors, _expected):
            assert probe.main(argv) == probe.InputError.exit_code
        output = _parse_output(capsys.readouterr().out)
        assert output["TRANSPORT_PROBE_FAILURE_PHASE"] == "SOCKET_CLOSE"
        assert output["TLS_HOSTNAME_VERIFIED"] == "true"
        assert output["RESULT"].startswith("BLOCKED_")
        assert revalidations >= 2


def test_primary_transport_failure_wins_over_post_ca_drift(
    probe: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with tempfile.TemporaryDirectory(prefix="pastorai-transport-probe-") as raw_dir:
        directory = Path(raw_dir)
        ca_path, _cert_path, _key_path = _generate_pki(directory)
        revalidations = 0

        def revalidate(_witness: Any) -> None:
            nonlocal revalidations
            revalidations += 1
            if revalidations >= 2:
                raise probe.InputError

        def fake_transport(**_kwargs: Any) -> None:
            raise probe.TransportError(failure_phase="TCP_CONNECT")

        monkeypatch.setattr(probe, "_revalidate_ca_fd", revalidate)
        monkeypatch.setattr(probe, "_run_transport_probe", fake_transport)
        with _main_inputs(probe, directory, ca_path) as (argv, _descriptors, _expected):
            assert probe.main(argv) == probe.TransportError.exit_code
        output = _parse_output(capsys.readouterr().out)
        assert output["TRANSPORT_PROBE_FAILURE_PHASE"] == "TCP_CONNECT"
        assert output["RESULT"].endswith(":TRANSPORT_BLOCKED")
        assert revalidations >= 2


def test_wrong_confirmation_duplicate_fds_and_sensitive_argv_block_preconnect(
    probe: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert probe.main(["--target-host-fd", "3", "postgresql://secret"]) == probe.UsageError.exit_code
    first = _parse_output(capsys.readouterr().out)
    assert first["TRANSPORT_PROBE_FAILURE_PHASE"] == "PRECONNECT_GUARDS"
    probe._ATTEMPT_STATE.consumed = False
    argv = [
        "--target-host-fd", "3",
        "--authorization-record-fd", "3",
        "--expected-authorization-record-sha256-fd", "4",
        "--expected-project-ref-sha256-fd", "5",
        "--nonce-fd", "6",
        "--tls-ca-cert-fd", "7",
        "--confirmation", probe.CONFIRMATION,
    ]
    assert probe.main(argv) == probe.UsageError.exit_code
    second = _parse_output(capsys.readouterr().out)
    assert second["TRANSPORT_PROBE_FAILURE_PHASE"] == "PRECONNECT_GUARDS"


def test_attempt_is_process_invocation_only_and_cannot_be_reused(probe: ModuleType) -> None:
    probe._consume_attempt()
    with pytest.raises(probe.AttemptConsumedError):
        probe._consume_attempt()


def test_failure_phase_allowlist_and_output_never_accept_dynamic_exception(
    probe: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(ValueError):
        probe._print_blocked("secret exception", "dynamic-secret-phase", probe.ProbeState())
    assert capsys.readouterr().out == ""
    probe._print_blocked("TRANSPORT_BLOCKED", "TCP_CONNECT", probe.ProbeState())
    output = capsys.readouterr().out
    assert output.count("TRANSPORT_PROBE_FAILURE_PHASE=") == 1
    assert output.count("TLS_HANDSHAKE_FAILURE_CATEGORY=NOT_APPLICABLE") == 1
    assert "exception" not in output

    state = probe.ProbeState(tls_handshake_failure_category="dynamic-secret")
    with pytest.raises(ValueError):
        probe._state_lines(state)


def test_deadline_scope_restores_handler_and_timer(probe: ModuleType) -> None:
    before_handler = probe.signal.getsignal(probe.signal.SIGALRM)
    before_timer = probe.signal.getitimer(probe.signal.ITIMER_REAL)
    with probe._deadline_scope(1) as deadline:
        assert 0 < deadline.remaining() <= 1
    assert probe.signal.getsignal(probe.signal.SIGALRM) == before_handler
    assert probe.signal.getitimer(probe.signal.ITIMER_REAL) == before_timer


def test_plan_and_runner_do_not_change_historical_preflight() -> None:
    historical = BACKEND_ROOT / "scripts" / "preflight_migration_history_environment_identity.py"
    assert hashlib.sha256(historical.read_bytes()).hexdigest() == (
        "8da631fbb602488bb8c82ce1529c9d8ba17acbae8a318ea9b0fc24cdd8f65cd2"
    )
    plan = PLAN_PATH.read_text(encoding="utf-8")
    assert '"execution_disabled": true' in plan
    assert '"implementation_present": false' in plan
    assert '"network_capability_present": false' in plan
