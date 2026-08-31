#!/usr/bin/env python3
"""One-shot, sanitized DEV PostgreSQL transport probe.

The probe stops immediately after PostgreSQL SSL negotiation, a verified TLS
handshake and hostname verification.  It never sends a StartupMessage, user,
database, password or SQL.  Operational use still requires a separately
authorized, byte-bound record supplied through private file descriptors.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import socket
import ssl
import stat
import struct
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any


SOURCE_MAIN_GIT_SHA = "36f8d13284a8f4964d0258a2a3b845323a80fe7e"
PLAN_SHA256 = "5d0b1e4d8f3609b5409b9007a7ffb94e4dbebc17bc3bf4a342d5a281dbfa7f36"
EXPECTED_DEV_PROJECT_REF_SHA256 = (
    "7aa91c30e6951cabf8f094a88b62f2b5d2e486cf306ba8596fd89c5850713fd9"
)
PLAN_BASENAME = "dev-connect-tls-auth-transport-probe-plan-v1.json"
CONFIRMATION = "PROBE_DEV_CONNECT_TLS_AUTH_TRANSPORT_ONCE"
AUTHORIZATION_CONTRACT = "PASTORAI_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE_AUTH_V1"
AUTHORIZATION_GATE = "SEPARATE_NOMINAL_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE_AUTHORIZATION"
SINGLE_USE_SCOPE = "PROCESS_INVOCATION_ONLY"
DIRECT_HOST_RE = re.compile(r"db\.([a-z0-9]{20})\.supabase\.co")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ISO_UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
DNS_SAN_RE = re.compile(r"(?:\*\.)?[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")

PORT = 5432
MAX_HOST_BYTES = 253
MAX_AUTHORIZATION_BYTES = 16 * 1024
MAX_CA_BYTES = 1024 * 1024
MAX_PLAN_BYTES = 64 * 1024
MAX_RUNNER_BYTES = 256 * 1024
MAX_RESOLVED_ADDRESSES = 32
MAX_AUTHORIZATION_WINDOW_SECONDS = 15 * 60
MIN_DEADLINE_SECONDS = 1
MAX_DEADLINE_SECONDS = 15
SSL_REQUEST = struct.pack(">II", 8, 80877103)

PHASES = (
    "PRECONNECT_GUARDS",
    "DNS_RESOLUTION",
    "ADDRESS_POLICY",
    "TCP_CONNECT",
    "PG_SSL_NEGOTIATION",
    "TLS_HANDSHAKE",
    "TLS_HOSTNAME_VERIFICATION",
    "SOCKET_CLOSE",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / PLAN_BASENAME
)

CLI_FLAGS = {
    "--target-host-fd",
    "--authorization-record-fd",
    "--expected-authorization-record-sha256-fd",
    "--expected-project-ref-sha256-fd",
    "--nonce-fd",
    "--tls-ca-cert-fd",
    "--confirmation",
}

RELEVANT_ENV_NAMES = {
    "DATABASE_URL",
    "M06_MIGRATION_DATABASE_URL",
    "SUPABASE_DB_URL",
    "SUPABASE_DATABASE_URL",
    "HOSTALIASES",
    "LOCALDOMAIN",
    "RES_OPTIONS",
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
}

AUTHORIZATION_KEYS = (
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
    "not_before",
    "not_after",
    "deadline_seconds",
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
)


class ProbeError(RuntimeError):
    exit_code = 10
    reason = "INTERNAL_ERROR"

    def __init__(self, *, failure_phase: str | None = None) -> None:
        super().__init__()
        self.failure_phase = failure_phase


class UsageError(ProbeError):
    exit_code = 2
    reason = "USAGE"


class InputError(ProbeError):
    exit_code = 3
    reason = "INPUT_INVALID"


class AuthorizationError(ProbeError):
    exit_code = 4
    reason = "AUTHORIZATION_INVALID"


class ContractError(ProbeError):
    exit_code = 5
    reason = "CONTRACT_INVALID"


class DeadlineError(ProbeError):
    exit_code = 6
    reason = "DEADLINE_EXCEEDED"


class TransportError(ProbeError):
    exit_code = 7
    reason = "TRANSPORT_BLOCKED"


class CleanupError(ProbeError):
    exit_code = 8
    reason = "CLEANUP_BLOCKED"


class AttemptConsumedError(ProbeError):
    exit_code = 9
    reason = "ATTEMPT_CONSUMED"


class SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise UsageError


@dataclass(frozen=True)
class Authorization:
    record_sha256: str
    deadline_seconds: int


@dataclass(frozen=True)
class CaWitness:
    descriptor: int
    snapshot: tuple[int, ...]
    size: int
    offset: int
    sha256: str


@dataclass
class ProbeState:
    dns_resolved: bool = False
    address_policy_passed: bool = False
    tcp_connected: bool = False
    pg_ssl_negotiated: bool = False
    tls_handshake_completed: bool = False
    tls_hostname_verified: bool = False
    socket_closed: bool = True


@dataclass
class AttemptState:
    consumed: bool = False


_ATTEMPT_STATE = AttemptState()
_TEST_ONLY_LOOPBACK_SENTINEL = object()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _frame(label: str, raw: str) -> bytes:
    label_bytes = label.encode("ascii")
    raw_bytes = raw.encode("utf-8")
    return label_bytes + struct.pack(">Q", len(raw_bytes)) + raw_bytes


def _component_sha256(label: str, raw: str) -> str:
    return hashlib.sha256(_frame(label, raw)).hexdigest()


def _stat_snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_uid,
        info.st_gid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _directory_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _file_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _read_stable_public_file(path: Path, maximum: int) -> bytes:
    parent = path.parent
    basename = path.name
    first_parent_fd: int | None = None
    file_fd: int | None = None
    second_parent_fd: int | None = None
    second_file_fd: int | None = None
    try:
        parent_info = parent.lstat()
        if not stat.S_ISDIR(parent_info.st_mode):
            raise ContractError
        first_parent_fd = os.open(parent, _directory_flags())
        opened_parent = os.fstat(first_parent_fd)
        if _stat_snapshot(opened_parent) != _stat_snapshot(parent_info):
            raise ContractError
        nominal_info = os.stat(basename, dir_fd=first_parent_fd, follow_symlinks=False)
        file_fd = os.open(basename, _file_flags(), dir_fd=first_parent_fd)
        before = os.fstat(file_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or before.st_gid != os.getegid()
            or before.st_size <= 0
            or before.st_size > maximum
            or _stat_snapshot(before) != _stat_snapshot(nominal_info)
        ):
            raise ContractError
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if (
            not raw
            or len(raw) > maximum
            or _stat_snapshot(os.fstat(file_fd)) != _stat_snapshot(before)
        ):
            raise ContractError
        second_parent_info = parent.lstat()
        second_parent_fd = os.open(parent, _directory_flags())
        if (
            _stat_snapshot(second_parent_info) != _stat_snapshot(parent_info)
            or _stat_snapshot(os.fstat(second_parent_fd))
            != _stat_snapshot(opened_parent)
        ):
            raise ContractError
        second_file_fd = os.open(basename, _file_flags(), dir_fd=second_parent_fd)
        if _stat_snapshot(os.fstat(second_file_fd)) != _stat_snapshot(before):
            raise ContractError
        return raw
    except (OSError, ContractError):
        raise ContractError from None
    finally:
        for descriptor in (
            second_file_fd,
            second_parent_fd,
            file_fd,
            first_parent_fd,
        ):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def _read_private_fd(descriptor: int, maximum: int) -> bytes:
    if descriptor < 3:
        raise InputError
    try:
        before = os.fstat(descriptor)
    except OSError:
        raise InputError from None
    if not (stat.S_ISREG(before.st_mode) or stat.S_ISFIFO(before.st_mode)):
        raise InputError
    if (
        before.st_uid != os.geteuid()
        or before.st_gid != os.getegid()
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_nlink != 1
    ):
        raise InputError
    if stat.S_ISREG(before.st_mode):
        try:
            offset = os.lseek(descriptor, 0, os.SEEK_CUR)
        except OSError:
            raise InputError from None
        if before.st_size <= 0 or before.st_size > maximum or offset != 0:
            raise InputError
    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            chunk = os.read(descriptor, min(65_536, maximum + 1 - total))
        except OSError:
            raise InputError from None
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum:
            raise InputError
    if total == 0:
        raise InputError
    try:
        after = os.fstat(descriptor)
    except OSError:
        raise InputError from None
    if _stat_snapshot(after) != _stat_snapshot(before):
        raise InputError
    return b"".join(chunks)


def _pread_sha256(descriptor: int, size: int) -> str:
    digest = hashlib.sha256()
    position = 0
    while position < size:
        try:
            chunk = os.pread(descriptor, min(65_536, size - position), position)
        except OSError:
            raise InputError from None
        if not chunk:
            raise InputError
        digest.update(chunk)
        position += len(chunk)
    try:
        if os.pread(descriptor, 1, size):
            raise InputError
    except OSError:
        raise InputError from None
    return digest.hexdigest()


def _witness_ca_fd(descriptor: int) -> CaWitness:
    if descriptor < 3:
        raise InputError
    try:
        before = os.fstat(descriptor)
        offset = os.lseek(descriptor, 0, os.SEEK_CUR)
        access_mode = fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE
    except OSError:
        raise InputError from None
    if (
        not stat.S_ISREG(before.st_mode)
        or access_mode != os.O_RDONLY
        or before.st_uid != os.geteuid()
        or before.st_gid != os.getegid()
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_nlink != 1
        or offset != 0
        or before.st_size <= 0
        or before.st_size > MAX_CA_BYTES
    ):
        raise InputError
    digest = _pread_sha256(descriptor, before.st_size)
    try:
        after = os.fstat(descriptor)
        after_offset = os.lseek(descriptor, 0, os.SEEK_CUR)
    except OSError:
        raise InputError from None
    snapshot = _stat_snapshot(before)
    if _stat_snapshot(after) != snapshot or after_offset != offset:
        raise InputError
    return CaWitness(descriptor, snapshot, before.st_size, offset, digest)


def _revalidate_ca_fd(witness: CaWitness) -> None:
    try:
        before = os.fstat(witness.descriptor)
        offset = os.lseek(witness.descriptor, 0, os.SEEK_CUR)
    except OSError:
        raise InputError from None
    if _stat_snapshot(before) != witness.snapshot or offset != witness.offset:
        raise InputError
    digest = _pread_sha256(witness.descriptor, witness.size)
    try:
        after = os.fstat(witness.descriptor)
        after_offset = os.lseek(witness.descriptor, 0, os.SEEK_CUR)
    except OSError:
        raise InputError from None
    if (
        _stat_snapshot(after) != witness.snapshot
        or after_offset != witness.offset
        or not hmac.compare_digest(digest, witness.sha256)
    ):
        raise InputError


def _close_descriptors(descriptors: Sequence[int]) -> None:
    for descriptor in descriptors:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _with_phase(error: ProbeError, phase: str) -> ProbeError:
    if phase not in PHASES:
        raise ValueError("invalid transport probe phase")
    if error.failure_phase is None:
        error.failure_phase = phase
    return error


def _validate_hash_bytes(raw: bytes) -> str:
    try:
        value = raw.decode("ascii")
    except UnicodeDecodeError:
        raise InputError from None
    if SHA256_RE.fullmatch(value) is None:
        raise InputError
    return value


def _runner_sha256() -> str:
    return hashlib.sha256(
        _read_stable_public_file(Path(__file__).resolve(), MAX_RUNNER_BYTES)
    ).hexdigest()


def _load_plan_contract() -> None:
    raw = _read_stable_public_file(PLAN_PATH, MAX_PLAN_BYTES)
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), PLAN_SHA256):
        raise ContractError
    try:
        plan = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ContractError from None
    try:
        contract = plan["future_probe_contract"]
        target = contract["target_contract"]
        wire = contract["wire_contract"]
        policy = contract["dns_and_address_policy"]
        tls_policy = contract["tls_policy"]
        input_policy = contract["input_policy"]
    except (KeyError, TypeError):
        raise ContractError from None
    if (
        plan.get("artifact_kind") != "DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE_PLAN"
        or plan.get("contract_version") != 1
        or plan.get("execution_disabled") is not True
        or plan.get("operational_authorization") is not False
        or plan.get("next_stage_authorized") is not False
        or target.get("environment") != "DEV"
        or target.get("endpoint_kind") != "DIRECT_POSTGRES_TRANSPORT_ONLY"
        or target.get("port") != PORT
        or wire.get("postgres_sslrequest_hex") != SSL_REQUEST.hex()
        or wire.get("required_server_response") != "S"
        or any(
            wire.get(name) is not False
            for name in (
                "startup_message_allowed",
                "authentication_allowed",
                "database_session_allowed",
                "sql_allowed",
            )
        )
        or policy.get("resolve_count_max") != 1
        or policy.get("all_resolved_addresses_must_be_global") is not True
        or policy.get("retry_allowed") is not False
        or policy.get("fallback_allowed") is not False
        or tls_policy.get("mode") != "VERIFY_FULL_EXPLICIT_CA"
        or tls_policy.get("explicit_ca_required") is not True
        or tls_policy.get("system_ca_fallback_allowed") is not False
        or input_policy.get("password_allowed") is not False
        or input_policy.get("database_user_allowed") is not False
        or input_policy.get("database_name_allowed") is not False
        or input_policy.get("dsn_allowed") is not False
    ):
        raise ContractError


def _assert_sanitized_argv(argv: Sequence[str]) -> None:
    for item in argv:
        if item in CLI_FLAGS or item == CONFIRMATION or item.isdecimal():
            continue
        else:
            raise UsageError


def _assert_clean_environment(environ: Mapping[str, str]) -> None:
    for name in environ:
        upper = name.upper()
        if (
            upper.startswith("PG")
            or upper.startswith("SSL")
            or upper.startswith("OPENSSL")
            or upper.startswith("DYLD_")
            or upper in RELEVANT_ENV_NAMES
        ):
            raise InputError


def _parse_timestamp(value: str) -> datetime:
    if ISO_UTC_RE.fullmatch(value) is None:
        raise AuthorizationError
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        raise AuthorizationError from None


def _parse_authorization(
    raw: bytes,
    *,
    runner_sha256: str,
    target_host_sha256: str,
    expected_project_ref_sha256: str,
    ca_sha256: str,
    nonce_sha256: str,
    now: datetime,
) -> Authorization:
    if b"\r" in raw or not raw.endswith(b"\n") or raw.startswith(b"\n"):
        raise AuthorizationError
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError:
        raise AuthorizationError from None
    if len(lines) != len(AUTHORIZATION_KEYS):
        raise AuthorizationError
    values: dict[str, str] = {}
    for expected_key, line in zip(AUTHORIZATION_KEYS, lines, strict=True):
        if line.count("=") != 1:
            raise AuthorizationError
        key, value = line.split("=", 1)
        if key != expected_key or not value or key in values:
            raise AuthorizationError
        values[key] = value
    expected = {
        "authorization_contract": AUTHORIZATION_CONTRACT,
        "gate": AUTHORIZATION_GATE,
        "environment": "DEV",
        "owner": "OWNER-01",
        "executor": "CODEX-ROOT",
        "source_main_git_sha": SOURCE_MAIN_GIT_SHA,
        "runner_sha256": runner_sha256,
        "probe_plan_sha256": PLAN_SHA256,
        "target_host_sha256": target_host_sha256,
        "expected_project_ref_sha256": expected_project_ref_sha256,
        "tls_ca_certificate_sha256": ca_sha256,
        "nonce_sha256": nonce_sha256,
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
    for key, value in expected.items():
        if not hmac.compare_digest(values[key], value):
            raise AuthorizationError
    try:
        deadline_seconds = int(values["deadline_seconds"], 10)
    except ValueError:
        raise AuthorizationError from None
    if not MIN_DEADLINE_SECONDS <= deadline_seconds <= MAX_DEADLINE_SECONDS:
        raise AuthorizationError
    not_before = _parse_timestamp(values["not_before"])
    not_after = _parse_timestamp(values["not_after"])
    window_seconds = (not_after - not_before).total_seconds()
    if (
        not 0 < window_seconds <= MAX_AUTHORIZATION_WINDOW_SECONDS
        or now < not_before
        or now > not_after
    ):
        raise AuthorizationError
    return Authorization(hashlib.sha256(raw).hexdigest(), deadline_seconds)


def _decode_target_host(
    raw: bytes,
    *,
    expected_project_ref_sha256: str,
) -> tuple[str, str]:
    try:
        host = raw.decode("ascii")
    except UnicodeDecodeError:
        raise InputError from None
    if host != host.casefold() or len(host) > MAX_HOST_BYTES:
        raise InputError
    match = DIRECT_HOST_RE.fullmatch(host)
    if match is None:
        raise InputError
    project_ref = match.group(1)
    observed_ref_hash = _component_sha256("PROJECT_REF", project_ref)
    if not hmac.compare_digest(observed_ref_hash, expected_project_ref_sha256):
        raise InputError
    return host, _component_sha256("TARGET_HOST", host)


def _consume_attempt() -> None:
    if _ATTEMPT_STATE.consumed:
        raise AttemptConsumedError
    _ATTEMPT_STATE.consumed = True


@dataclass(frozen=True)
class Deadline:
    expires_at: float

    def remaining(self) -> float:
        remaining = self.expires_at - time.monotonic()
        if remaining <= 0:
            raise DeadlineError
        return remaining


@contextmanager
def _deadline_scope(seconds: int) -> Iterator[Deadline]:
    if threading.current_thread() is not threading.main_thread():
        raise InputError
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    if previous_timer != (0.0, 0.0):
        raise InputError

    def alarm_handler(_signum: int, _frame: Any) -> None:
        raise DeadlineError

    signal.signal(signal.SIGALRM, alarm_handler)
    deadline = Deadline(time.monotonic() + seconds)
    signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        yield deadline
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)


def _normalize_addresses(
    records: Sequence[tuple[int, int, int, str, tuple[Any, ...]]],
    *,
    test_loopback_allowed: bool,
) -> list[tuple[int, tuple[Any, ...]]]:
    normalized: dict[tuple[int, bytes], tuple[int, tuple[Any, ...]]] = {}
    for family, socktype, protocol, _canonname, sockaddr in records:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            raise TransportError
        if socktype != socket.SOCK_STREAM or protocol not in {0, socket.IPPROTO_TCP}:
            raise TransportError
        if not isinstance(sockaddr, tuple) or len(sockaddr) < 2:
            raise TransportError
        try:
            address = ipaddress.ip_address(str(sockaddr[0]))
        except ValueError:
            raise TransportError from None
        if not address.is_global and not (test_loopback_allowed and address.is_loopback):
            raise TransportError
        if address.version == 4:
            canonical_sockaddr: tuple[Any, ...] = (str(address), PORT)
        else:
            canonical_sockaddr = (str(address), PORT, 0, 0)
        normalized[(address.version, address.packed)] = (family, canonical_sockaddr)
    if not normalized or len(normalized) > MAX_RESOLVED_ADDRESSES:
        raise TransportError
    return [normalized[key] for key in sorted(normalized)]


def _dnsname_matches(pattern: str, hostname: str) -> bool:
    candidate = pattern.casefold().rstrip(".")
    expected = hostname.casefold().rstrip(".")
    if DNS_SAN_RE.fullmatch(candidate) is None:
        return False
    if "*" not in candidate:
        return hmac.compare_digest(candidate, expected)
    if not candidate.startswith("*.") or candidate.count("*") != 1:
        return False
    suffix = candidate[2:]
    expected_labels = expected.split(".")
    suffix_labels = suffix.split(".")
    return (
        len(expected_labels) == len(suffix_labels) + 1
        and hmac.compare_digest(".".join(expected_labels[1:]), suffix)
    )


def _verify_hostname(certificate: Mapping[str, Any], hostname: str) -> None:
    subject_alt_name = certificate.get("subjectAltName")
    if not isinstance(subject_alt_name, (list, tuple)):
        raise TransportError
    dns_names: list[str] = []
    for entry in subject_alt_name:
        if (
            isinstance(entry, tuple)
            and len(entry) == 2
            and entry[0] == "DNS"
            and isinstance(entry[1], str)
        ):
            dns_names.append(entry[1])
    if not dns_names or not any(_dnsname_matches(item, hostname) for item in dns_names):
        raise TransportError


def _build_tls_context(ca_witness: CaWitness) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if hasattr(ssl, "OP_NO_COMPRESSION"):
        context.options |= ssl.OP_NO_COMPRESSION
    try:
        context.load_verify_locations(cafile=f"/proc/self/fd/{ca_witness.descriptor}")
    except (OSError, ssl.SSLError):
        raise InputError from None
    if context.verify_mode != ssl.CERT_REQUIRED or context.check_hostname:
        raise ContractError
    return context


Resolver = Callable[
    [str, int, int, int, int],
    Sequence[tuple[int, int, int, str, tuple[Any, ...]]],
]
SocketFactory = Callable[[int, int, int], socket.socket]


def _run_transport_probe(
    *,
    hostname: str,
    ca_witness: CaWitness,
    deadline_seconds: int,
    state: ProbeState,
    resolver: Resolver = socket.getaddrinfo,
    socket_factory: SocketFactory = socket.socket,
    port: int = PORT,
    _test_only_loopback_sentinel: object | None = None,
) -> None:
    if port != PORT and _test_only_loopback_sentinel is not _TEST_ONLY_LOOPBACK_SENTINEL:
        raise InputError
    test_loopback_allowed = _test_only_loopback_sentinel is _TEST_ONLY_LOOPBACK_SENTINEL
    phase = "PRECONNECT_GUARDS"
    raw_socket: socket.socket | None = None
    tls_socket: ssl.SSLSocket | None = None
    pending: ProbeError | None = None
    context = _build_tls_context(ca_witness)
    try:
        with _deadline_scope(deadline_seconds) as deadline:
            phase = "DNS_RESOLUTION"
            records = resolver(
                hostname,
                port,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
            )
            deadline.remaining()
            state.dns_resolved = True

            phase = "ADDRESS_POLICY"
            addresses = _normalize_addresses(
                records,
                test_loopback_allowed=test_loopback_allowed,
            )
            family, sockaddr = addresses[0]
            if port != PORT:
                if family == socket.AF_INET:
                    sockaddr = (sockaddr[0], port)
                else:
                    sockaddr = (sockaddr[0], port, 0, 0)
            state.address_policy_passed = True

            phase = "TCP_CONNECT"
            raw_socket = socket_factory(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
            state.socket_closed = False
            raw_socket.settimeout(deadline.remaining())
            raw_socket.connect(sockaddr)
            state.tcp_connected = True

            phase = "PG_SSL_NEGOTIATION"
            raw_socket.settimeout(deadline.remaining())
            raw_socket.sendall(SSL_REQUEST)
            response = raw_socket.recv(1)
            if response != b"S":
                raise TransportError
            state.pg_ssl_negotiated = True

            phase = "TLS_HANDSHAKE"
            raw_socket.settimeout(deadline.remaining())
            tls_socket = context.wrap_socket(
                raw_socket,
                server_hostname=hostname,
                do_handshake_on_connect=False,
            )
            raw_socket = None
            tls_socket.settimeout(deadline.remaining())
            tls_socket.do_handshake()
            state.tls_handshake_completed = True

            phase = "TLS_HOSTNAME_VERIFICATION"
            certificate = tls_socket.getpeercert()
            if not isinstance(certificate, dict):
                raise TransportError
            _verify_hostname(certificate, hostname)
            state.tls_hostname_verified = True
            deadline.remaining()
    except ProbeError as exc:
        pending = _with_phase(exc, phase)
    except (OSError, ssl.SSLError, ValueError):
        pending = TransportError(failure_phase=phase)
    finally:
        phase = "SOCKET_CLOSE"
        close_failed = False
        for active_socket in (tls_socket, raw_socket):
            if active_socket is None:
                continue
            try:
                active_socket.close()
            except Exception:
                close_failed = True
        if not close_failed:
            state.socket_closed = True
        elif pending is None:
            pending = CleanupError(failure_phase=phase)
    if pending is not None:
        raise pending


def _build_parser() -> argparse.ArgumentParser:
    parser = SanitizedArgumentParser(add_help=False)
    parser.add_argument("--target-host-fd", required=True, type=int)
    parser.add_argument("--authorization-record-fd", required=True, type=int)
    parser.add_argument(
        "--expected-authorization-record-sha256-fd",
        required=True,
        type=int,
    )
    parser.add_argument("--expected-project-ref-sha256-fd", required=True, type=int)
    parser.add_argument("--nonce-fd", required=True, type=int)
    parser.add_argument("--tls-ca-cert-fd", required=True, type=int)
    parser.add_argument("--confirmation", required=True)
    return parser


def _deny_lines() -> tuple[str, ...]:
    return (
        "ENVIRONMENT=DEV",
        "HISTORICAL_FAILURE_PHASE=CONNECT_TLS_AUTH",
        "HISTORICAL_AUTHENTICATION_OUTCOME=UNKNOWN",
        "ROOT_CAUSE=UNDETERMINED",
        "OPERATIONAL_AUTHORIZATION=false",
        "NEXT_STAGE_AUTHORIZED=false",
        "PROD_ACCESSED=false",
        "AUTHENTICATION_ATTEMPTED=false",
        "DATABASE_SESSION_ESTABLISHED=false",
        "SQL_EXECUTED=false",
        "LOGS_QUERIED=false",
        "CAPTURE_EXECUTED=false",
        "MATERIALIZATION_EXECUTED=false",
        f"SINGLE_USE_SCOPE={SINGLE_USE_SCOPE}",
    )


def _state_lines(state: ProbeState) -> tuple[str, ...]:
    return (
        f"DNS_RESOLVED={str(state.dns_resolved).lower()}",
        f"ADDRESS_POLICY_PASSED={str(state.address_policy_passed).lower()}",
        f"TCP_CONNECTED={str(state.tcp_connected).lower()}",
        f"PG_SSL_NEGOTIATED={str(state.pg_ssl_negotiated).lower()}",
        f"TLS_HANDSHAKE_COMPLETED={str(state.tls_handshake_completed).lower()}",
        f"TLS_HOSTNAME_VERIFIED={str(state.tls_hostname_verified).lower()}",
        f"SOCKET_CLOSED={str(state.socket_closed).lower()}",
    )


def _print_blocked(reason: str, phase: str, state: ProbeState) -> None:
    if phase not in PHASES:
        raise ValueError("invalid transport probe phase")
    for line in _deny_lines():
        print(line)
    for line in _state_lines(state):
        print(line)
    print(f"TRANSPORT_PROBE_FAILURE_PHASE={phase}")
    print(f"RESULT=BLOCKED_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE:{reason}")


def main(
    argv: list[str] | None = None,
    *,
    _resolver: Resolver = socket.getaddrinfo,
    _socket_factory: SocketFactory = socket.socket,
    _port: int = PORT,
    _test_only_loopback_sentinel: object | None = None,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    descriptors: tuple[int, ...] = ()
    ca_witness: CaWitness | None = None
    ca_revalidated = False
    nonce_buffer: bytearray | None = None
    state = ProbeState()
    phase = "PRECONNECT_GUARDS"
    try:
        _assert_sanitized_argv(arguments)
        args = _build_parser().parse_args(arguments)
        if args.confirmation != CONFIRMATION:
            raise UsageError
        candidate_descriptors = (
            args.target_host_fd,
            args.authorization_record_fd,
            args.expected_authorization_record_sha256_fd,
            args.expected_project_ref_sha256_fd,
            args.nonce_fd,
            args.tls_ca_cert_fd,
        )
        if len(set(candidate_descriptors)) != len(candidate_descriptors) or any(
            item < 3 for item in candidate_descriptors
        ):
            raise UsageError
        descriptors = candidate_descriptors
        _consume_attempt()
        _assert_clean_environment(os.environ)
        _load_plan_contract()
        runner_sha256 = _runner_sha256()
        read_once = descriptors[:-1]
        try:
            host_raw = _read_private_fd(args.target_host_fd, MAX_HOST_BYTES)
            authorization_raw = _read_private_fd(
                args.authorization_record_fd,
                MAX_AUTHORIZATION_BYTES,
            )
            expected_authorization_record_sha256 = _validate_hash_bytes(
                _read_private_fd(
                    args.expected_authorization_record_sha256_fd,
                    64,
                )
            )
            expected_project_ref_sha256 = _validate_hash_bytes(
                _read_private_fd(args.expected_project_ref_sha256_fd, 64)
            )
            nonce_buffer = bytearray(_read_private_fd(args.nonce_fd, 32))
            ca_witness = _witness_ca_fd(args.tls_ca_cert_fd)
        finally:
            _close_descriptors(read_once)
            descriptors = (args.tls_ca_cert_fd,)
        if ca_witness is None or nonce_buffer is None or len(nonce_buffer) != 32:
            raise InputError
        if not hmac.compare_digest(
            expected_project_ref_sha256,
            EXPECTED_DEV_PROJECT_REF_SHA256,
        ):
            raise InputError
        hostname, target_host_sha256 = _decode_target_host(
            host_raw,
            expected_project_ref_sha256=expected_project_ref_sha256,
        )
        nonce_sha256 = hashlib.sha256(nonce_buffer).hexdigest()
        authorization_record_sha256 = hashlib.sha256(authorization_raw).hexdigest()
        if not hmac.compare_digest(
            authorization_record_sha256,
            expected_authorization_record_sha256,
        ):
            raise AuthorizationError
        authorization = _parse_authorization(
            authorization_raw,
            runner_sha256=runner_sha256,
            target_host_sha256=target_host_sha256,
            expected_project_ref_sha256=expected_project_ref_sha256,
            ca_sha256=ca_witness.sha256,
            nonce_sha256=nonce_sha256,
            now=_utc_now(),
        )
        _revalidate_ca_fd(ca_witness)
        phase = "DNS_RESOLUTION"
        pending: ProbeError | None = None
        try:
            _run_transport_probe(
                hostname=hostname,
                ca_witness=ca_witness,
                deadline_seconds=authorization.deadline_seconds,
                state=state,
                resolver=_resolver,
                socket_factory=_socket_factory,
                port=_port,
                _test_only_loopback_sentinel=_test_only_loopback_sentinel,
            )
        except ProbeError as exc:
            pending = exc
        try:
            _revalidate_ca_fd(ca_witness)
            ca_revalidated = True
        except ProbeError as exc:
            if pending is None:
                pending = _with_phase(exc, "SOCKET_CLOSE")
        if pending is not None:
            raise pending
        for line in _deny_lines():
            print(line)
        print(f"RUNNER_SHA256={runner_sha256}")
        print(f"PROBE_PLAN_SHA256={PLAN_SHA256}")
        print(f"AUTHORIZATION_RECORD_SHA256={authorization.record_sha256}")
        print(f"EXPECTED_PROJECT_REF_SHA256={expected_project_ref_sha256}")
        print(f"TARGET_HOST_SHA256={target_host_sha256}")
        print(f"TLS_CA_CERTIFICATE_SHA256={ca_witness.sha256}")
        print(f"ATTEMPT_NONCE_SHA256={nonce_sha256}")
        print("TLS_MODE=VERIFY_FULL_EXPLICIT_CA")
        for line in _state_lines(state):
            print(line)
        print("TRANSPORT_PROBE_PHASE=SOCKET_CLOSE")
        print("RESULT=DEV_CONNECT_TLS_AUTH_TRANSPORT_OBSERVED_NOT_HISTORICAL_CAUSE")
        return 0
    except ProbeError as exc:
        _print_blocked(exc.reason, exc.failure_phase or phase, state)
        return exc.exit_code
    except Exception:
        _print_blocked("INTERNAL_ERROR", phase, state)
        return ProbeError.exit_code
    finally:
        if ca_witness is not None and not ca_revalidated:
            try:
                _revalidate_ca_fd(ca_witness)
            except ProbeError:
                pass
        if descriptors:
            _close_descriptors(descriptors)
        if nonce_buffer is not None:
            nonce_buffer[:] = b"\x00" * len(nonce_buffer)


if __name__ == "__main__":
    raise SystemExit(main())
