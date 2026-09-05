#!/usr/bin/env python3
"""Source-only dispatcher for the PRIVATE_RUNTIME V2 policy.

There is deliberately no PostgreSQL driver, cursor execution, DDL, or replay
implementation in this module. The V1 migration replay remains in its
byte-pinned module. Names retained for callers that probe a candidate surface
fail closed with ``NOT_IMPLEMENTED`` before touching a cursor, so a fake
snapshot cannot be mistaken for PG17 or cross-tenant proof.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import ipaddress
import importlib.util
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.parse import urlsplit

try:
    from private_runtime_intent_v2 import (
        INTENT_PREFIX as V2_INTENT_PREFIX,
        PrivateRuntimeIntentError,
        parse_intent,
    )
except ImportError:  # pragma: no cover - isolated ``python -I`` execution
    _intent_spec = importlib.util.spec_from_file_location(
        "private_runtime_intent_v2_isolated", Path(__file__).with_name("private_runtime_intent_v2.py")
    )
    if _intent_spec is None or _intent_spec.loader is None:
        raise
    _intent_module = importlib.util.module_from_spec(_intent_spec)
    sys.modules[_intent_spec.name] = _intent_module
    _intent_spec.loader.exec_module(_intent_module)
    V2_INTENT_PREFIX = _intent_module.INTENT_PREFIX
    PrivateRuntimeIntentError = _intent_module.PrivateRuntimeIntentError
    parse_intent = _intent_module.parse_intent


V1_INTENT_PREFIX = "-- PASTORAI_MIGRATION_INTENT_V1="
SCOPE_V1 = "TENANT"
SCOPE_V2 = "PRIVATE_RUNTIME"
DATABASE_URL_ENV = "MIGRATION_PRIVATE_RUNTIME_REPLAY_DATABASE_URL"
DISPOSABLE_DATABASE = "migration_private_runtime_disposable"
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
NEXT_STAGE_BLOCK = "NEXT_STAGE_AUTHORIZED=false"
ENVIRONMENT_BLOCK = "SHARED_ENVIRONMENT_ATTESTATION=false"


class PrivateRuntimeReplayError(RuntimeError):
    exit_code = 10


class SourceContractError(PrivateRuntimeReplayError):
    exit_code = 4


class TargetGuardError(PrivateRuntimeReplayError):
    exit_code = 5


class PrivateRuntimeDeltaError(PrivateRuntimeReplayError):
    exit_code = 6


class ReplayNotImplementedError(PrivateRuntimeReplayError):
    """The policy intentionally has no executable PG17 replay yet."""

    exit_code = 9


@dataclass(frozen=True)
class DispatchedIntent:
    version: str
    scope: str
    intent: Mapping[str, object] | None


@dataclass(frozen=True)
class PrivateRuntimeSurface:
    """Test-only shape; it is never accepted as replay evidence."""

    schema: Mapping[str, object] | None
    runtime_role: Mapping[str, object] | None
    memberships: tuple[tuple[str, str], ...]
    functions: tuple[Mapping[str, object], ...]
    relations: tuple[Mapping[str, object], ...]
    grants: tuple[Mapping[str, object], ...]
    config: tuple[tuple[str, str], ...]


def dispatch_intent(
    content: bytes, *, basename: str | None = None
) -> DispatchedIntent:
    """Route V2 to its closed source validator and leave V1 untouched."""

    if type(content) is not bytes:
        raise SourceContractError
    if content.startswith(V2_INTENT_PREFIX.encode("ascii")):
        try:
            return DispatchedIntent("V2", SCOPE_V2, parse_intent(content, basename=basename))
        except PrivateRuntimeIntentError as exc:
            raise SourceContractError from exc
    if content.startswith(V1_INTENT_PREFIX.encode("ascii")):
        return DispatchedIntent("V1", SCOPE_V1, None)
    raise SourceContractError


def validate_fresh_private_runtime_surface(surface: PrivateRuntimeSurface) -> None:
    """Fail closed: fresh-target validation is not implemented in V2."""

    raise ReplayNotImplementedError("fresh PG17 target validation is not implemented")


def validate_fresh_private_runtime_database(cursor: Any) -> None:
    """Fail before touching a cursor; this package never probes a database."""

    raise ReplayNotImplementedError("PG17 database validation is not implemented")


def validate_private_runtime_delta(
    before: PrivateRuntimeSurface,
    after: PrivateRuntimeSurface,
    intent: Mapping[str, object],
) -> None:
    """Reject all candidate deltas until a separately reviewed replay exists."""

    raise ReplayNotImplementedError(
        "private-runtime catalog delta replay is not implemented; source policy only"
    )


def capture_private_runtime_surface(cursor: Any) -> PrivateRuntimeSurface:
    """Fail before touching a cursor; no catalog capture is claimed here."""

    raise ReplayNotImplementedError("pg_catalog capture is not implemented")


def _read_disposable_url() -> str:
    """Validate a future loopback-only URL without connecting to it."""

    raw = os.environ.get(DATABASE_URL_ENV)
    if not raw or raw != raw.strip() or len(raw) > 4096:
        raise TargetGuardError
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        address = ipaddress.ip_address(host) if host else None
        port = parsed.port
    except (ValueError, UnicodeError) as exc:
        raise TargetGuardError from exc
    if (
        parsed.scheme not in {"postgresql", "postgres"}
        or address is None
        or not address.is_loopback
        or parsed.path != f"/{DISPOSABLE_DATABASE}"
        or parsed.query
        or parsed.fragment
        or parsed.username != "postgres"
        or not parsed.password
        or port is None
        or port < 1024
        or port > 65535
    ):
        raise TargetGuardError
    return raw


# Compatibility names are intentionally fail-closed stubs, not replay APIs.
_dispatch_intent = dispatch_intent
validate_private_runtime_security_delta = validate_private_runtime_delta
capture_private_runtime_security_surface = capture_private_runtime_surface


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--policy", required=True)
    args = sys.argv[1:] if argv is None else argv
    try:
        parsed = parser.parse_args(args)
        content = Path(parsed.policy).read_bytes()
        dispatched = dispatch_intent(content, basename=Path(parsed.policy).name)
        if dispatched.version != "V2":
            raise SourceContractError
    except (OSError, PrivateRuntimeReplayError, PrivateRuntimeIntentError, ValueError):
        print("RESULT=BLOCKED_PRIVATE_RUNTIME_POLICY:SOURCE_CONTRACT_INVALID", file=sys.stderr)
        return 4
    print(OPERATIONAL_BLOCK)
    print(NEXT_STAGE_BLOCK)
    print(ENVIRONMENT_BLOCK)
    print("RESULT=PRIVATE_RUNTIME_POLICY_SOURCE_CONTRACT_VERIFIED")
    print("SCOPE=PRIVATE_RUNTIME")
    print("PG17_REPLAY_IMPLEMENTED=false")
    print("PG17_REPLAY_EXECUTED=false")
    print("CROSS_TENANT_EVIDENCE=false")
    print("CATALOG_MIGRATION_CREATED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
