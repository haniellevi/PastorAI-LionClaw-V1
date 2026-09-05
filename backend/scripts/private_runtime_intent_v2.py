#!/usr/bin/env python3
"""Closed, source-only contract for the private ``agent_runtime`` boundary.

This module is deliberately independent from the V1 migration authoring and
replay modules.  A V2 intent describes a future private-runtime migration; it
does not add an entry to the public migration catalog and it never authorizes
database access.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


INTENT_PREFIX = "-- PASTORAI_MIGRATION_INTENT_V2="
INTENT_ARTIFACT_ID = "migration-authoring-intent-v2"
SCOPE = "PRIVATE_RUNTIME"
OPERATIONAL_AUTHORIZATION = False
NEXT_STAGE_AUTHORIZED = False
GIT_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
POLICY_BASENAME_RE = re.compile(
    r"^[0-9]{8}_[0-9]{6}_[a-z][a-z0-9_]{0,119}\.policy\.json\Z"
)

REQUIRED_KEYS = frozenset(
    {
        "artifact_id",
        "base_repository_sha",
        "migration_basename",
        "scope",
        "affected_objects",
        "private_runtime_controls",
        "decision_refs",
        "recovery",
        "pg17_test_nodeids",
        "cross_tenant_test_nodeids",
        "operational_authorization",
        "next_stage_authorized",
    }
)
CONTROL_KEYS = frozenset(
    {
        "schema",
        "runtime_role",
        "tenant_context",
        "functions",
        "projection_function",
        "relations",
        "acl",
        "config",
    }
)
SCHEMA_KEYS = frozenset({"name", "owner", "public_usage", "runtime_usage"})
ROLE_KEYS = frozenset(
    {
        "name",
        "login",
        "inherit",
        "superuser",
        "createrole",
        "createdb",
        "replication",
        "bypassrls",
        "memberships",
    }
)
TENANT_CONTEXT_KEYS = frozenset(
    {"name", "schema", "guc", "returns", "source", "null_behavior"}
)
FUNCTION_KEYS = frozenset(
    {
        "identity",
        "schema",
        "name",
        "returns",
        "security_definer",
        "volatility",
        "strict",
        "search_path",
        "owner",
        "execute_grantees",
        "public_execute",
        "read_only",
        "writes_allowed",
        "lifecycle",
    }
)
RELATION_KEYS = frozenset(
    {
        "schema",
        "name",
        "owner",
        "purpose",
        "tenant_column",
        "rls_enabled",
        "rls_forced",
        "public_acl",
        "runtime_privileges",
        "runtime_write_privileges",
    }
)
ACL_KEYS = frozenset(
    {
        "schema_usage",
        "relation_select",
        "function_execute",
        "direct_public_grants",
        "direct_runtime_grants",
    }
)
CONFIG_KEYS = frozenset(
    {"tenant_guc", "runtime_database_url_env", "read_only_boundary", "role_config", "gates"}
)
RECOVERY_KEYS = frozenset({"kind", "reference"})
DECISION_REFERENCE_RE = re.compile(
    r"^docs/decisions/[0-9]{4}-[0-9]{2}-[0-9]{2}-"
    r"[a-z0-9][a-z0-9_.-]{0,159}\.md\Z"
)
TEST_NODEID_RE = re.compile(
    r"^backend/tests/test_[A-Za-z0-9_]+\.py::test_[A-Za-z0-9_]+\Z"
)


class PrivateRuntimeIntentError(ValueError):
    """Raised when a V2 policy is incomplete or tries to widen authority."""


def _is_sha(value: object) -> bool:
    return type(value) is str and GIT_SHA_RE.fullmatch(value) is not None and set(value) != {"0"}


def _closed_string_list(value: object, *, allow_empty: bool = False) -> bool:
    return (
        type(value) is list
        and (allow_empty or bool(value))
        and len(value) == len(set(value))
        and all(type(item) is str and item.strip() for item in value)
    )


def _closed_grant_list(value: object) -> bool:
    if type(value) is not list:
        return False
    normalized: list[tuple[str, str, str]] = []
    for item in value:
        if type(item) is not dict or set(item) != {"object", "grantee", "privilege"}:
            return False
        values = (item["object"], item["grantee"], item["privilege"])
        if not all(type(part) is str and part.strip() for part in values):
            return False
        if item["grantee"].upper() in {"PUBLIC", "ANONYMOUS"}:
            return False
        normalized.append(values)
    return len(normalized) == len(set(normalized))


def default_private_runtime_controls() -> dict[str, object]:
    """Return the only V2 control shape accepted by this policy revision."""

    return {
        "schema": {
            "name": "agent_private",
            "owner": "CURRENT_MIGRATION_ROLE",
            "public_usage": False,
            "runtime_usage": True,
        },
        "runtime_role": {
            "name": "agent_runtime",
            "login": False,
            "inherit": False,
            "superuser": False,
            "createrole": False,
            "createdb": False,
            "replication": False,
            "bypassrls": False,
            "memberships": [],
        },
        "tenant_context": {
            "name": "current_tenant_id",
            "schema": "agent_private",
            "guc": "app.tenant_igreja_id",
            "returns": "uuid",
            "source": "current_setting('app.tenant_igreja_id', true)",
            "null_behavior": "NULL_WHEN_UNSET",
        },
        "functions": [
            {
                "identity": "agent_private.current_tenant_id()",
                "schema": "agent_private",
                "name": "current_tenant_id",
                "returns": "uuid",
                "security_definer": False,
                "volatility": "STABLE",
                "strict": False,
                "search_path": ["pg_catalog"],
                "owner": "CURRENT_MIGRATION_ROLE",
                "execute_grantees": ["agent_runtime"],
                "public_execute": False,
                "read_only": True,
                "writes_allowed": False,
                "lifecycle": "EXISTING_HELPER",
            }
        ],
        "projection_function": {
            "identity": "agent_private.load_turn_context(uuid)",
            "schema": "agent_private",
            "name": "load_turn_context",
            "returns": "jsonb",
            "security_definer": True,
            "volatility": "STABLE",
            "strict": True,
            "search_path": ["pg_catalog", "agent_private"],
            "owner": "CURRENT_MIGRATION_ROLE",
            "execute_grantees": ["agent_runtime"],
            "public_execute": False,
            "read_only": True,
            "writes_allowed": False,
            "lifecycle": "FUTURE_PROJECTION_CONTRACT",
        },
        # Relations are intentionally empty in policy-only V2.  A later
        # migration must declare each private relation and its RLS contract.
        "relations": [],
        "acl": {
            "schema_usage": ["agent_runtime"],
            "relation_select": [],
            "function_execute": ["agent_runtime"],
            "direct_public_grants": [],
            "direct_runtime_grants": [
                {"object": "agent_private", "grantee": "agent_runtime", "privilege": "USAGE"},
                {"object": "agent_private.current_tenant_id()", "grantee": "agent_runtime", "privilege": "EXECUTE"},
            ],
        },
        "config": {
            "tenant_guc": "app.tenant_igreja_id",
            "runtime_database_url_env": "AGENT_RUNTIME_DATABASE_URL",
            "read_only_boundary": True,
            "role_config": [
                "row_security=on",
                "search_path=pg_catalog, agent_private",
            ],
            "gates": {
                "operational_authorization": False,
                "next_stage_authorized": False,
            },
        },
    }


def default_intent(*, basename: str, base_repository_sha: str) -> dict[str, object]:
    return {
        "artifact_id": INTENT_ARTIFACT_ID,
        "base_repository_sha": base_repository_sha,
        "migration_basename": basename,
        "scope": SCOPE,
        "affected_objects": [
            "agent_private",
            "agent_private.current_tenant_id()",
            "agent_runtime",
        ],
        "private_runtime_controls": default_private_runtime_controls(),
        "decision_refs": ["TODO"],
        "recovery": {"kind": "TODO", "reference": "TODO"},
        "pg17_test_nodeids": ["TODO"],
        "cross_tenant_test_nodeids": ["TODO"],
        "operational_authorization": False,
        "next_stage_authorized": False,
    }


def _validate_controls(controls: object) -> None:
    if type(controls) is not dict or set(controls) != CONTROL_KEYS:
        raise PrivateRuntimeIntentError("private runtime controls are not closed")
    schema = controls["schema"]
    if type(schema) is not dict or set(schema) != SCHEMA_KEYS or schema != {
        "name": "agent_private",
        "owner": "CURRENT_MIGRATION_ROLE",
        "public_usage": False,
        "runtime_usage": True,
    }:
        raise PrivateRuntimeIntentError("private schema contract is invalid")
    role = controls["runtime_role"]
    expected_role = default_private_runtime_controls()["runtime_role"]
    if type(role) is not dict or set(role) != ROLE_KEYS or role != expected_role:
        raise PrivateRuntimeIntentError("runtime role contract is invalid")
    tenant = controls["tenant_context"]
    expected_tenant = default_private_runtime_controls()["tenant_context"]
    if type(tenant) is not dict or set(tenant) != TENANT_CONTEXT_KEYS or tenant != expected_tenant:
        raise PrivateRuntimeIntentError("tenant context contract is invalid")
    functions = controls["functions"]
    if type(functions) is not list or not 1 <= len(functions) <= 16:
        raise PrivateRuntimeIntentError("function contract is invalid")
    identities: set[str] = set()
    for function in functions:
        if type(function) is not dict or set(function) != FUNCTION_KEYS:
            raise PrivateRuntimeIntentError("security-definer function contract is invalid")
        identity = function["identity"]
        if (
            type(identity) is not str
            or not identity.startswith("agent_private.")
            or identity in identities
            or function["schema"] != "agent_private"
            or function["returns"] != "uuid"
            or function["owner"] != "CURRENT_MIGRATION_ROLE"
            or function["security_definer"] is not False
            or function["volatility"] != "STABLE"
            or function["search_path"] != ["pg_catalog"]
            or function["execute_grantees"] != ["agent_runtime"]
            or function["public_execute"] is not False
            or function["read_only"] is not True
            or function["writes_allowed"] is not False
            or function["lifecycle"] != "EXISTING_HELPER"
        ):
            raise PrivateRuntimeIntentError("security-definer function contract is invalid")
        identities.add(identity)
    if "agent_private.current_tenant_id()" not in identities:
        raise PrivateRuntimeIntentError("current_tenant_id is mandatory")
    projection = controls["projection_function"]
    if type(projection) is not dict or set(projection) != FUNCTION_KEYS:
        raise PrivateRuntimeIntentError("projection function contract is invalid")
    if (
        projection["identity"] != "agent_private.load_turn_context(uuid)"
        or projection["schema"] != "agent_private"
        or projection["name"] != "load_turn_context"
        or projection["returns"] != "jsonb"
        or projection["security_definer"] is not True
        or projection["volatility"] != "STABLE"
        or projection["strict"] is not True
        or projection["search_path"] != ["pg_catalog", "agent_private"]
        or projection["owner"] != "CURRENT_MIGRATION_ROLE"
        or projection["execute_grantees"] != ["agent_runtime"]
        or projection["public_execute"] is not False
        or projection["read_only"] is not True
        or projection["writes_allowed"] is not False
        or projection["lifecycle"] != "FUTURE_PROJECTION_CONTRACT"
    ):
        raise PrivateRuntimeIntentError("projection function contract is invalid")
    relations = controls["relations"]
    if type(relations) is not list:
        raise PrivateRuntimeIntentError("relation contract is invalid")
    for relation in relations:
        if type(relation) is not dict or set(relation) != RELATION_KEYS:
            raise PrivateRuntimeIntentError("relation contract is not closed")
        if (
            relation["schema"] != "agent_private"
            or relation["owner"] != "CURRENT_MIGRATION_ROLE"
            or relation["tenant_column"] != "igreja_id"
            or relation["rls_enabled"] is not True
            or relation["rls_forced"] is not True
            or relation["public_acl"] is not False
            or type(relation["runtime_privileges"]) is not list
            or type(relation["runtime_write_privileges"]) is not list
            or relation["runtime_write_privileges"]
            or any(item != "SELECT" for item in relation["runtime_privileges"])
        ):
            raise PrivateRuntimeIntentError("private relation is not read-only tenant-bound")
    acl = controls["acl"]
    if type(acl) is not dict or set(acl) != ACL_KEYS:
        raise PrivateRuntimeIntentError("ACL contract is not closed")
    if (
        acl["schema_usage"] != ["agent_runtime"]
        or acl["function_execute"] != ["agent_runtime"]
        or acl["direct_public_grants"] != []
        or not _closed_string_list(acl["relation_select"], allow_empty=True)
        or not _closed_grant_list(acl["direct_runtime_grants"])
    ):
        raise PrivateRuntimeIntentError("ACL contract grants an unsafe principal")
    config = controls["config"]
    if type(config) is not dict or set(config) != CONFIG_KEYS:
        raise PrivateRuntimeIntentError("runtime configuration is not closed")
    if (
        config["tenant_guc"] != "app.tenant_igreja_id"
        or config["runtime_database_url_env"] != "AGENT_RUNTIME_DATABASE_URL"
        or config["read_only_boundary"] is not True
        or config["role_config"] != [
            "row_security=on",
            "search_path=pg_catalog, agent_private",
        ]
        or config["gates"] != {"operational_authorization": False, "next_stage_authorized": False}
    ):
        raise PrivateRuntimeIntentError("runtime configuration widens authority")


def validate_intent(
    intent: Mapping[str, object], *, basename: str | None = None, expected_sha: str | None = None
) -> dict[str, object]:
    """Validate a V2 intent and return a detached copy."""

    if type(intent) is not dict or set(intent) != REQUIRED_KEYS:
        raise PrivateRuntimeIntentError("intent keys are not closed")
    if intent["artifact_id"] != INTENT_ARTIFACT_ID or intent["scope"] != SCOPE:
        raise PrivateRuntimeIntentError("not a private-runtime V2 intent")
    if not _is_sha(intent["base_repository_sha"]):
        raise PrivateRuntimeIntentError("base repository SHA is invalid")
    if expected_sha is not None and intent["base_repository_sha"] != expected_sha:
        raise PrivateRuntimeIntentError("base repository SHA mismatch")
    value_basename = intent["migration_basename"]
    if (
        type(value_basename) is not str
        or POLICY_BASENAME_RE.fullmatch(value_basename) is None
        or (basename is not None and value_basename != basename)
    ):
        raise PrivateRuntimeIntentError("policy basename is invalid")
    objects = intent["affected_objects"]
    if (
        type(objects) is not list
        or not objects
        or objects != sorted(objects)
        or len(objects) != len(set(objects))
        or not all(type(item) is str and item.strip() for item in objects)
    ):
        raise PrivateRuntimeIntentError("affected objects are invalid")
    if not {
        "agent_private",
        "agent_private.current_tenant_id()",
        "agent_runtime",
    }.issubset(objects):
        raise PrivateRuntimeIntentError("required private-runtime objects are missing")
    _validate_controls(intent["private_runtime_controls"])
    refs = intent["decision_refs"]
    if (
        not _closed_string_list(refs)
        or not all(DECISION_REFERENCE_RE.fullmatch(item) for item in refs)
    ):
        raise PrivateRuntimeIntentError("decision references are invalid")
    recovery = intent["recovery"]
    if (
        type(recovery) is not dict
        or set(recovery) != RECOVERY_KEYS
        or recovery["kind"] not in {"REVERSIBLE", "FORWARD_COMPENSATION"}
        or type(recovery["reference"]) is not str
        or not recovery["reference"].startswith("docs/")
    ):
        raise PrivateRuntimeIntentError("recovery contract is invalid")
    pg17 = intent["pg17_test_nodeids"]
    cross = intent["cross_tenant_test_nodeids"]
    if (
        not _closed_string_list(pg17)
        or not all(TEST_NODEID_RE.fullmatch(item) for item in pg17)
        or not _closed_string_list(cross)
        or not all(TEST_NODEID_RE.fullmatch(item) for item in cross)
        or not set(cross).issubset(set(pg17))
    ):
        raise PrivateRuntimeIntentError("PG17/cross-tenant tests are incomplete")
    if intent["operational_authorization"] is not False or intent["next_stage_authorized"] is not False:
        raise PrivateRuntimeIntentError("policy gates must remain closed")
    return json.loads(json.dumps(intent, ensure_ascii=True, sort_keys=True))


def parse_intent(content: bytes, *, basename: str | None = None, expected_sha: str | None = None) -> dict[str, object]:
    if (
        type(content) is not bytes
        or b"\x00" in content
        or b"MIGRATION_POLICY_DRAFT_INCOMPLETE" in content
        or content.count(b"OPERATIONAL_AUTHORIZATION=BLOCKED") != 1
        or content.count(b"NEXT_STAGE_AUTHORIZED=false") != 1
    ):
        raise PrivateRuntimeIntentError("invalid policy bytes")
    first_line, separator, _body = content.partition(b"\n")
    prefix = INTENT_PREFIX.encode("ascii")
    if not separator or not first_line.startswith(prefix):
        raise PrivateRuntimeIntentError("V2 intent prefix is missing")
    try:
        intent = json.loads(first_line[len(prefix) :].decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrivateRuntimeIntentError("V2 intent JSON is invalid") from exc
    return validate_intent(intent, basename=basename, expected_sha=expected_sha)


def render_draft(*, basename: str, base_repository_sha: str) -> bytes:
    intent = default_intent(basename=basename, base_repository_sha=base_repository_sha)
    encoded = json.dumps(intent, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return (
        INTENT_PREFIX.encode("ascii")
        + encoded.encode("ascii")
        + b"\n-- MIGRATION_POLICY_DRAFT_INCOMPLETE\n"
        + b"-- Complete decision/recovery references and PG17/cross-tenant nodeids.\n"
        + b"-- This policy is not a catalog migration and has no operational authority.\n"
        + b"-- OPERATIONAL_AUTHORIZATION=BLOCKED\n"
        + b"-- NEXT_STAGE_AUTHORIZED=false\n"
    )


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# Stable descriptive aliases make the dispatcher contract easy to consume
# without exposing any V1 parser internals.
validate_private_runtime_intent = validate_intent
parse_private_runtime_intent = parse_intent


@dataclass(frozen=True)
class PrivateRuntimePolicyCandidate:
    basename: str
    content: bytes
    content_sha256: str
