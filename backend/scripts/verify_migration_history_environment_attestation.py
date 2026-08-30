#!/usr/bin/env python3
"""Verify two sanitized environment artifacts offline and fail closed."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from pathlib import Path
import sys
from typing import Any, NoReturn

try:
    from scripts import materialize_migration_history_environment_attestation as materializer
except ModuleNotFoundError:
    import materialize_migration_history_environment_attestation as materializer


OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
SUCCESS = "ENVIRONMENT_ATTESTATION_PAIR_VALIDATED_BLOCKED"
MAX_ARTIFACT_BYTES = materializer.MAX_OUTPUT_BYTES
TOP_LEVEL_KEYS = {
    "artifact_id", "artifact_state", "capture_record_sha256", "contract_version",
    "data_invariants", "domains", "environment_attestation_complete", "ledgers",
    "operational_authorization", "pre_capture_binding", "profile_sha256", "source",
    "surfaces", "unknown_owners",
}


class VerificationError(RuntimeError):
    exit_code = 10
    reason = "INTERNAL_ERROR"


class UsageError(VerificationError):
    exit_code = 2
    reason = "USAGE"


class ArtifactError(VerificationError):
    exit_code = 3
    reason = "ARTIFACT_INVALID"


class PairReuseError(VerificationError):
    exit_code = 4
    reason = "ENVIRONMENT_PAIR_SWAP_OR_REUSE"


class EnvironmentEvidenceBlocked(VerificationError):
    exit_code = 8
    reason = "ENVIRONMENT_EVIDENCE_BLOCKED"


class SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise UsageError


def _json_loads(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ArtifactError
            result[key] = value
        return result
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=reject_duplicates,
            parse_float=lambda _value: (_ for _ in ()).throw(ArtifactError()),
            parse_constant=lambda _value: (_ for _ in ()).throw(ArtifactError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactError from exc
    if type(value) is not dict:
        raise ArtifactError
    return value


def _read_artifact(path: Path, expected_basename: str) -> dict[str, Any]:
    if path.name != expected_basename:
        raise ArtifactError
    try:
        raw = materializer._read_stable_nominal_file(
            path, MAX_ARTIFACT_BYTES, private=True, error=ArtifactError
        )
    except (OSError, materializer.AttestationError) as exc:
        raise ArtifactError from exc
    return _json_loads(raw)


def _walk(value: Any) -> None:
    if type(value) is dict:
        for key, child in value.items():
            if type(key) is not str or key.casefold() in materializer.FORBIDDEN_FINAL_KEYS:
                raise ArtifactError
            _walk(child)
    elif type(value) is list:
        for child in value:
            _walk(child)
    elif value is not None and type(value) not in {bool, int, str}:
        raise ArtifactError


def _validate_artifact(artifact: dict[str, Any], environment: str, profile: dict[str, Any]) -> None:
    if set(artifact) != TOP_LEVEL_KEYS:
        raise ArtifactError
    _walk(artifact)
    if artifact["artifact_id"] != f"migration-history-environment-attestation-{environment.casefold()}-v1":
        raise ArtifactError
    if artifact["contract_version"] != materializer.CONTRACT_VERSION:
        raise ArtifactError
    if artifact["artifact_state"] not in {
        "BLOCKED_DATA_INVARIANTS", "BLOCKED_PLATFORM_SURFACES_UNATTESTED",
        "BLOCKED_SCHEMA_METADATA_DIVERGENCE",
    }:
        raise ArtifactError
    if artifact["operational_authorization"] is not False:
        raise ArtifactError
    if artifact["environment_attestation_complete"] is not False:
        raise ArtifactError
    if artifact["profile_sha256"] != materializer.PROFILE_SHA256:
        raise ArtifactError
    if artifact["surfaces"] != {
        "data_api": "PLATFORM_SURFACES_UNATTESTED",
        "realtime": "PLATFORM_SURFACES_UNATTESTED",
    }:
        raise ArtifactError
    expected_source = {
        "canonical_schema_fingerprint_sha256": profile["canonical_schema_fingerprint_sha256"],
        "capture_sql_sha256": materializer.CAPTURE_SQL_SHA256,
        "source_catalog_digest_sha256": profile["source_catalog_digest_sha256"],
    }
    if artifact["source"] != expected_source:
        raise ArtifactError
    binding = artifact["pre_capture_binding"]
    if type(binding) is not dict or set(binding) != {
        "authorization_record_sha256", "environment", "hmac_sha256",
        "nonce_sha256", "target_binding_contract", "target_binding_sha256",
    }:
        raise ArtifactError
    if binding["environment"] != environment:
        raise ArtifactError
    if binding["target_binding_contract"] != materializer.TARGET_BINDING_CONTRACT:
        raise ArtifactError
    for key in (
        "authorization_record_sha256", "hmac_sha256", "nonce_sha256",
        "target_binding_sha256",
    ):
        materializer._validate_hash(binding.get(key), ArtifactError)
    materializer._validate_hash(artifact.get("capture_record_sha256"), ArtifactError)
    domains = artifact["domains"]
    if type(domains) is not list or len(domains) != len(profile["domains"]):
        raise ArtifactError
    blocked = False
    for observed, expected in zip(domains, profile["domains"], strict=True):
        if type(observed) is not dict or observed.get("name") != expected["name"]:
            raise ArtifactError
        if observed.get("comparison") != expected["comparison"]:
            raise ArtifactError
        if observed.get("expected_entry_count") != expected["entry_count"]:
            raise ArtifactError
        if observed.get("expected_sha256") != expected["sha256"]:
            raise ArtifactError
        if type(observed.get("observed_entry_count")) is not int or observed["observed_entry_count"] < 0:
            raise ArtifactError
        materializer._validate_hash(observed.get("observed_sha256"), ArtifactError)
        state = "MATCH" if (
            observed["observed_entry_count"] == expected["entry_count"]
            and hmac.compare_digest(observed["observed_sha256"], expected["sha256"])
        ) else "MISMATCH"
        if observed.get("state") != state:
            raise ArtifactError
        blocked |= state != "MATCH"
    invariants = artifact["data_invariants"]
    if type(invariants) is not list or len(invariants) != 8:
        raise ArtifactError
    for value, contract in zip(invariants, profile["data_invariants"], strict=True):
        if type(value) is not dict or set(value) != {
            "id", "state", "checks_executed", "violation_count"
        }:
            raise ArtifactError
        if value["id"] != contract["id"] or value["state"] not in {"PASS","FAIL","UNKNOWN","ERROR"}:
            raise ArtifactError
        if type(value["checks_executed"]) is not int or value["checks_executed"] < 0:
            raise ArtifactError
        if type(value["violation_count"]) is not int or value["violation_count"] < 0:
            raise ArtifactError
        if value["state"] == "PASS" and value["violation_count"] != 0:
            raise ArtifactError
        expected_checks = contract.get("checks_expected")
        if (
            type(expected_checks) is not int
            or value["checks_executed"] not in {0, expected_checks}
        ):
            raise ArtifactError
        if value["state"] in {"PASS", "FAIL"} and value["checks_executed"] != expected_checks:
            raise ArtifactError
        if value["state"] == "FAIL" and value["violation_count"] < 1:
            raise ArtifactError
        if value["state"] in {"UNKNOWN", "ERROR"} and value["violation_count"] != 0:
            raise ArtifactError
        if value["state"] == "ERROR" and value["checks_executed"] != 0:
            raise ArtifactError
        blocked |= value["state"] != "PASS"
    if (
        invariants[2]["id"] != "APPEND_ONLY_AUDIT_INTEGRITY"
        or invariants[2]["state"] != "UNKNOWN"
        or invariants[2]["checks_executed"] not in {
            0, profile["data_invariants"][2]["checks_expected"]
        }
        or invariants[2]["violation_count"] != 0
    ):
        raise ArtifactError
    unknown = artifact["unknown_owners"]
    if type(unknown) is not dict or set(unknown) != {"count", "fingerprint_sha256"}:
        raise ArtifactError
    if type(unknown["count"]) is not int or unknown["count"] < 0:
        raise ArtifactError
    materializer._validate_hash(unknown.get("fingerprint_sha256"), ArtifactError)
    blocked |= unknown["count"] != 0
    structural_metadata_blocked = (
        any(domain["state"] != "MATCH" for domain in domains)
        or unknown["count"] != 0
    )
    if structural_metadata_blocked:
        if any(
            item["state"] != "UNKNOWN"
            or item["checks_executed"] != 0
            or item["violation_count"] != 0
            for item in invariants
        ):
            raise ArtifactError
    elif invariants[2]["checks_executed"] != profile["data_invariants"][2]["checks_expected"]:
        raise ArtifactError
    ledgers = artifact["ledgers"]
    if type(ledgers) is not dict or set(ledgers) != {"native", "public"}:
        raise ArtifactError
    if any(item not in {"ABSENT","PRESENT","INVALID","UNKNOWN"} for item in ledgers.values()):
        raise ArtifactError
    blocked |= ledgers["public"] != "ABSENT"
    metadata_blocked = (
        any(domain["state"] != "MATCH" for domain in domains)
        or unknown["count"] != 0
        or ledgers["public"] != "ABSENT"
    )
    expected_state = (
        "BLOCKED_SCHEMA_METADATA_DIVERGENCE"
        if metadata_blocked
        else "BLOCKED_DATA_INVARIANTS" if blocked
        else "BLOCKED_PLATFORM_SURFACES_UNATTESTED"
    )
    if artifact["artifact_state"] != expected_state:
        raise ArtifactError


def verify(dev_path: Path, prod_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = materializer._load_contracts()
    dev = _read_artifact(dev_path, materializer.ARTIFACT_BASENAMES["DEV"])
    prod = _read_artifact(prod_path, materializer.ARTIFACT_BASENAMES["PROD"])
    _validate_artifact(dev, "DEV", profile)
    _validate_artifact(prod, "PROD", profile)
    dev_binding = dev["pre_capture_binding"]
    prod_binding = prod["pre_capture_binding"]
    distinct_pairs = (
        (dev_binding["target_binding_sha256"], prod_binding["target_binding_sha256"]),
        (dev_binding["authorization_record_sha256"], prod_binding["authorization_record_sha256"]),
        (dev_binding["nonce_sha256"], prod_binding["nonce_sha256"]),
        (dev_binding["hmac_sha256"], prod_binding["hmac_sha256"]),
        (dev["capture_record_sha256"], prod["capture_record_sha256"]),
    )
    if any(hmac.compare_digest(first, second) for first, second in distinct_pairs):
        raise PairReuseError
    return dev, prod


def build_parser() -> argparse.ArgumentParser:
    parser = SanitizedArgumentParser(add_help=False)
    parser.add_argument("--dev-artifact", required=True, type=Path)
    parser.add_argument("--prod-artifact", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    print(OPERATIONAL_BLOCK)
    try:
        args = build_parser().parse_args(argv)
        verify(args.dev_artifact, args.prod_artifact)
    except VerificationError as exc:
        print(f"ENVIRONMENT_PAIR_VERIFICATION_BLOCKED:{exc.reason}", file=sys.stderr)
        return exc.exit_code
    except materializer.AttestationError:
        print("ENVIRONMENT_PAIR_VERIFICATION_BLOCKED:ARTIFACT_INVALID", file=sys.stderr)
        return ArtifactError.exit_code
    except Exception:
        print("ENVIRONMENT_PAIR_VERIFICATION_BLOCKED:INTERNAL_ERROR", file=sys.stderr)
        return 10
    print("ENVIRONMENT_ATTESTATION_COMPLETE=false")
    print(SUCCESS)
    return EnvironmentEvidenceBlocked.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
