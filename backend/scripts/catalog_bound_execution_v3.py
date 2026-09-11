#!/usr/bin/env python3
"""Autonomous V3 source-only catalog-binding boundary.

The module contains only the literal C3 binding and strict structural checks.
It deliberately has no source discovery, external verification, or operational
path. A structurally valid request therefore remains unverified.
"""

from __future__ import annotations

import argparse
import dataclasses
import enum
import json
import sys
import typing


USAGE_EXIT = 2
BLOCKED_EXIT = 8
PROGRAM = "catalog-bound-execution-v3"
MAX_ENVELOPE_JSON_CHARS = 4_096
_LOWER_HEX = "0123456789abcdef"


class InputRejected(Exception):
    """Raised for an invalid local request without reflecting its content."""


class VerificationStatus(str, enum.Enum):
    """States that V3 may report after source-only structural validation."""

    EXTERNAL_AUTHORIZATION_UNVERIFIED = "EXTERNAL_AUTHORIZATION_UNVERIFIED"
    DURABLE_REPLAY_UNVERIFIED = "DURABLE_REPLAY_UNVERIFIED"
    CUTOVER_UNVERIFIED = "CUTOVER_UNVERIFIED"


class VerificationType(str, enum.Enum):
    """The three intentionally distinct external-verification shapes."""

    ENVELOPE = "envelope"
    REPLAY = "replay"
    CUTOVER = "cutover"


def _is_lower_hex(value: object, length: int) -> bool:
    return (
        type(value) is str
        and len(value) == length
        and all(character in _LOWER_HEX for character in value)
    )


@dataclasses.dataclass(frozen=True, slots=True)
class C3Binding:
    """Immutable literal identity for the C3 candidate supplied to V3."""

    repository_sha1: str
    sql_sha256: str
    head_sha256: str
    catalog_digest_sha256: str

    def __post_init__(self) -> None:
        if not (
            _is_lower_hex(self.repository_sha1, 40)
            and _is_lower_hex(self.sql_sha256, 64)
            and _is_lower_hex(self.head_sha256, 64)
            and _is_lower_hex(self.catalog_digest_sha256, 64)
        ):
            raise ValueError("invalid C3 binding literal")


C3_BINDING = C3Binding(
    repository_sha1="02a4f1aecfcf0433455e1b5c93a96b10e2358a55",
    sql_sha256="6952a2aaca04d6765a0bc77f831b2507e9cf5fd77d80f76e43b0816b06806e6b",
    head_sha256="9b756191d6a3e89fca61b3c88015b1f76423692e09b12270239389bef63dd1f5",
    catalog_digest_sha256="ed6398ff6cfc15981208631075b724fb128991682e6c7e607acf72fb913a6ac2",
)


@dataclasses.dataclass(frozen=True, slots=True)
class ExternalAuthorizationEnvelope:
    """Shape for a future external authorization assertion, never its proof."""

    binding: C3Binding
    status: VerificationStatus = VerificationStatus.EXTERNAL_AUTHORIZATION_UNVERIFIED

    def __post_init__(self) -> None:
        if (
            self.binding != C3_BINDING
            or self.status is not VerificationStatus.EXTERNAL_AUTHORIZATION_UNVERIFIED
        ):
            raise InputRejected()


@dataclasses.dataclass(frozen=True, slots=True)
class DurableReplayReceipt:
    """Shape for a future durable replay assertion, never its proof."""

    binding: C3Binding
    status: VerificationStatus = VerificationStatus.DURABLE_REPLAY_UNVERIFIED

    def __post_init__(self) -> None:
        if (
            self.binding != C3_BINDING
            or self.status is not VerificationStatus.DURABLE_REPLAY_UNVERIFIED
        ):
            raise InputRejected()


@dataclasses.dataclass(frozen=True, slots=True)
class EpochCutoverDecision:
    """Shape for a future cutover assertion, never its proof."""

    binding: C3Binding
    status: VerificationStatus = VerificationStatus.CUTOVER_UNVERIFIED

    def __post_init__(self) -> None:
        if (
            self.binding != C3_BINDING
            or self.status is not VerificationStatus.CUTOVER_UNVERIFIED
        ):
            raise InputRejected()


VerificationEnvelope = (
    ExternalAuthorizationEnvelope | DurableReplayReceipt | EpochCutoverDecision
)
_BINDING_FIELDS = (
    "repository_sha1",
    "sql_sha256",
    "head_sha256",
    "catalog_digest_sha256",
)


def c3_binding_payload() -> dict[str, str]:
    """Return a fresh JSON-compatible view of the immutable literal."""

    return {
        "repository_sha1": C3_BINDING.repository_sha1,
        "sql_sha256": C3_BINDING.sql_sha256,
        "head_sha256": C3_BINDING.head_sha256,
        "catalog_digest_sha256": C3_BINDING.catalog_digest_sha256,
    }


def _require_exact_fields(value: object, fields: tuple[str, ...]) -> dict[str, object]:
    if type(value) is not dict or set(value) != set(fields):
        raise InputRejected()
    return typing.cast(dict[str, object], value)


def _parse_binding(value: object) -> C3Binding:
    candidate = _require_exact_fields(value, _BINDING_FIELDS)
    if candidate != c3_binding_payload():
        raise InputRejected()
    return C3_BINDING


def parse_verification_envelope(value: object) -> VerificationEnvelope:
    """Validate one strict external-verification shape against literal C3."""

    envelope = _require_exact_fields(value, ("type", "binding"))
    kind = envelope["type"]
    if type(kind) is not str:
        raise InputRejected()
    binding = _parse_binding(envelope["binding"])
    if kind == VerificationType.ENVELOPE.value:
        return ExternalAuthorizationEnvelope(binding=binding)
    if kind == VerificationType.REPLAY.value:
        return DurableReplayReceipt(binding=binding)
    if kind == VerificationType.CUTOVER.value:
        return EpochCutoverDecision(binding=binding)
    raise InputRejected()


def validate_envelope_json(value: object) -> VerificationEnvelope:
    """Decode a bounded inline JSON value and validate its exact shape."""

    if type(value) is not str or len(value) > MAX_ENVELOPE_JSON_CHARS:
        raise InputRejected()
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        raise InputRejected() from None
    return parse_verification_envelope(decoded)


def _verification_type_for(envelope: VerificationEnvelope) -> VerificationType:
    if type(envelope) is ExternalAuthorizationEnvelope:
        return VerificationType.ENVELOPE
    if type(envelope) is DurableReplayReceipt:
        return VerificationType.REPLAY
    if type(envelope) is EpochCutoverDecision:
        return VerificationType.CUTOVER
    raise InputRejected()


def _base_payload() -> dict[str, object]:
    return {
        "catalog_bound_execution": "V3_SOURCE_ONLY",
        "binding": c3_binding_payload(),
        "operational_authorization": "BLOCKED",
        "next_stage_authorized": False,
    }


def describe_payload() -> dict[str, object]:
    """Describe V3's fixed boundary without claiming external verification."""

    payload = _base_payload()
    payload["command"] = "describe"
    payload["verification_types"] = {
        VerificationType.ENVELOPE.value: (
            VerificationStatus.EXTERNAL_AUTHORIZATION_UNVERIFIED.value
        ),
        VerificationType.REPLAY.value: VerificationStatus.DURABLE_REPLAY_UNVERIFIED.value,
        VerificationType.CUTOVER.value: VerificationStatus.CUTOVER_UNVERIFIED.value,
    }
    return payload


def validation_payload(envelope: VerificationEnvelope) -> dict[str, object]:
    """Report structural acceptance while preserving the unverified state."""

    payload = _base_payload()
    payload["command"] = "validate"
    payload["verification_type"] = _verification_type_for(envelope).value
    payload["result"] = envelope.status.value
    return payload


def _blocked_status_for(command: str) -> VerificationStatus:
    if command in ("reconcile", "reconciliation"):
        return VerificationStatus.DURABLE_REPLAY_UNVERIFIED
    if command == "cutover":
        return VerificationStatus.CUTOVER_UNVERIFIED
    return VerificationStatus.EXTERNAL_AUTHORIZATION_UNVERIFIED


def blocked_payload(command: str) -> dict[str, object]:
    """Return the deterministic pre-operation denial for an unsafe command."""

    payload = _base_payload()
    payload["command"] = command
    payload["result"] = _blocked_status_for(command).value
    return payload


def _rejected_payload() -> dict[str, object]:
    payload = _base_payload()
    payload["result"] = "INPUT_REJECTED"
    return payload


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))


class _Parser(argparse.ArgumentParser):
    """Argparse variant that never prints untrusted syntax back to callers."""

    def error(self, message: str) -> typing.NoReturn:
        raise InputRejected()

    def exit(
        self, status: int = 0, message: str | None = None
    ) -> typing.NoReturn:
        raise InputRejected()


def build_parser() -> argparse.ArgumentParser:
    """Build the closed V3 command surface."""

    parser = _Parser(prog=PROGRAM, add_help=False)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("describe", add_help=False)
    validate = commands.add_parser("validate", add_help=False)
    validate.add_argument("--envelope", required=True)
    for command in (
        "apply",
        "bootstrap",
        "bootstrap-ledger",
        "harden",
        "harden-ledger",
        "reconcile",
        "reconciliation",
        "cutover",
        "legacy-ledger",
    ):
        commands.add_parser(command, add_help=False)
    return parser


def main(argv: typing.Sequence[str] | None = None) -> int:
    """Run the source-only CLI without an operational path."""

    arguments = list(sys.argv[1:] if argv is None else argv[1:])
    try:
        parsed = build_parser().parse_args(arguments)
        if parsed.command == "describe":
            _emit(describe_payload())
            return 0
        if parsed.command == "validate":
            _emit(validation_payload(validate_envelope_json(parsed.envelope)))
            return 0
        _emit(blocked_payload(parsed.command))
        return BLOCKED_EXIT
    except InputRejected:
        _emit(_rejected_payload())
        return USAGE_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
