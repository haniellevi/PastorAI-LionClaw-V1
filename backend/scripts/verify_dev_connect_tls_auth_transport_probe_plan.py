#!/usr/bin/env python3
"""Verify the disabled DEV transport-probe plan without network capability."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import sys


PLAN_BASENAME = "dev-connect-tls-auth-transport-probe-plan-v1.json"
SCHEMA_BASENAME = "dev-connect-tls-auth-transport-probe-plan.schema.json"
SCHEMA_SHA256 = "431b413ff8c14ea331269116b13e7ebf1f1f9cdb80ddf7b23c8182c2437648bb"
MAX_PLAN_BYTES = 64 * 1024
MAX_SCHEMA_BYTES = 128 * 1024

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = REPO_ROOT / "docs" / "governance" / "migrations" / PLAN_BASENAME
DEFAULT_SCHEMA = REPO_ROOT / "docs" / "governance" / "migrations" / SCHEMA_BASENAME

OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
SUCCESS = "DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE_PLAN_VERIFIED_OFFLINE"


class VerificationError(RuntimeError):
    exit_code = 10
    reason = "INTERNAL_ERROR"


class UsageError(VerificationError):
    exit_code = 2
    reason = "USAGE"


class ArtifactError(VerificationError):
    exit_code = 3
    reason = "ARTIFACT_INVALID"


class SchemaDriftError(VerificationError):
    exit_code = 4
    reason = "SCHEMA_DRIFT"


class ContractError(VerificationError):
    exit_code = 5
    reason = "PLAN_CONTRACT_INVALID"


class SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise UsageError


def _strict_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        left_dict = left
        right_dict = right
        return set(left_dict) == set(right_dict) and all(
            _strict_equal(left_dict[key], right_dict[key]) for key in left_dict
        )
    if type(left) is list:
        left_list = left
        right_list = right
        return len(left_list) == len(right_list) and all(
            _strict_equal(first, second)
            for first, second in zip(left_list, right_list, strict=True)
        )
    return left == right


def _json_loads(raw: bytes) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ArtifactError
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_float=lambda _value: (_ for _ in ()).throw(ArtifactError()),
            parse_constant=lambda _value: (_ for _ in ()).throw(ArtifactError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactError from exc
    if type(value) is not dict:
        raise ArtifactError
    return value


def _read_stable_file(path: Path, expected_basename: str, limit: int) -> bytes:
    if path.name != expected_basename:
        raise ArtifactError
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ArtifactError
        if before.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ArtifactError
        if before.st_size < 2 or before.st_size > limit:
            raise ArtifactError
        raw = path.read_bytes()
        after = path.lstat()
    except OSError as exc:
        raise ArtifactError from exc
    stable_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
        raise ArtifactError
    if len(raw) != before.st_size:
        raise ArtifactError
    return raw


def _matches_json_type(value: object, declared: str) -> bool:
    return {
        "object": type(value) is dict,
        "array": type(value) is list,
        "string": type(value) is str,
        "integer": type(value) is int,
        "boolean": type(value) is bool,
        "null": value is None,
    }.get(declared, False)


def _validate_schema_instance(value: object, schema: object) -> None:
    if type(schema) is not dict:
        raise SchemaDriftError

    declared_type = schema.get("type")
    if declared_type is not None:
        if type(declared_type) is not str or not _matches_json_type(value, declared_type):
            raise ContractError

    if "const" in schema and not _strict_equal(value, schema["const"]):
        raise ContractError

    if "enum" in schema:
        enum_values = schema["enum"]
        if type(enum_values) is not list or not any(
            _strict_equal(value, candidate) for candidate in enum_values
        ):
            raise ContractError

    if type(value) is str and "pattern" in schema:
        pattern = schema["pattern"]
        if type(pattern) is not str or re.fullmatch(pattern, value) is None:
            raise ContractError

    if type(value) is dict:
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        if type(required) is not list or not all(type(item) is str for item in required):
            raise SchemaDriftError
        if type(properties) is not dict:
            raise SchemaDriftError
        if any(key not in value for key in required):
            raise ContractError
        unknown = set(value) - set(properties)
        if unknown and schema.get("additionalProperties") is False:
            raise ContractError
        for key, child in value.items():
            child_schema = properties.get(key)
            if child_schema is None:
                if schema.get("additionalProperties") is not True:
                    raise ContractError
                continue
            _validate_schema_instance(child, child_schema)

    if type(value) is list:
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if minimum is not None and (type(minimum) is not int or len(value) < minimum):
            raise ContractError
        if maximum is not None and (type(maximum) is not int or len(value) > maximum):
            raise ContractError
        if schema.get("uniqueItems") is True:
            for index, item in enumerate(value):
                if any(_strict_equal(item, other) for other in value[index + 1 :]):
                    raise ContractError
        prefix_items = schema.get("prefixItems", [])
        if type(prefix_items) is not list:
            raise SchemaDriftError
        for item, child_schema in zip(value, prefix_items, strict=False):
            _validate_schema_instance(item, child_schema)
        remaining = value[len(prefix_items) :]
        item_schema = schema.get("items")
        if item_schema is False and remaining:
            raise ContractError
        if type(item_schema) is dict:
            for item in remaining if prefix_items else value:
                _validate_schema_instance(item, item_schema)


def _validate_schema_contract(schema: dict[str, object], raw: bytes) -> None:
    if hashlib.sha256(raw).hexdigest() != SCHEMA_SHA256:
        raise SchemaDriftError
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise SchemaDriftError
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise SchemaDriftError


def verify(plan_path: Path, schema_path: Path) -> dict[str, object]:
    schema_raw = _read_stable_file(schema_path, SCHEMA_BASENAME, MAX_SCHEMA_BYTES)
    plan_raw = _read_stable_file(plan_path, PLAN_BASENAME, MAX_PLAN_BYTES)
    schema = _json_loads(schema_raw)
    plan = _json_loads(plan_raw)
    _validate_schema_contract(schema, schema_raw)
    _validate_schema_instance(plan, schema)
    binding = plan.get("schema_binding")
    if type(binding) is not dict or binding.get("sha256") != SCHEMA_SHA256:
        raise ContractError
    if plan.get("execution_disabled") is not True:
        raise ContractError
    mission = plan.get("mission_evidence")
    if type(mission) is not dict or any(value is not False for value in mission.values()):
        raise ContractError
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = SanitizedArgumentParser(add_help=False)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    return parser


def main(argv: list[str] | None = None) -> int:
    print(OPERATIONAL_BLOCK)
    print("EXECUTION_DISABLED=true")
    try:
        args = build_parser().parse_args(argv)
        plan = verify(args.plan, args.schema)
    except VerificationError as exc:
        print(f"OFFLINE_PROBE_PLAN_VERIFICATION_BLOCKED:{exc.reason}", file=sys.stderr)
        return exc.exit_code
    except Exception:
        print("OFFLINE_PROBE_PLAN_VERIFICATION_BLOCKED:INTERNAL_ERROR", file=sys.stderr)
        return VerificationError.exit_code
    root_cause = plan["interpretation_boundary"]
    if type(root_cause) is not dict or root_cause.get("root_cause") != "UNDETERMINED":
        print("OFFLINE_PROBE_PLAN_VERIFICATION_BLOCKED:PLAN_CONTRACT_INVALID", file=sys.stderr)
        return ContractError.exit_code
    print("ROOT_CAUSE=UNDETERMINED")
    print("NEXT_STAGE_AUTHORIZED=false")
    print(SUCCESS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
