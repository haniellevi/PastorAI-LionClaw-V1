#!/usr/bin/env python3
"""Closed executable intent for the private runtime projection (V2).

``private_runtime_intent_v2.py`` is the byte-pinned V5 policy artifact.  It
continues to describe the historical, source-only proposal and must not be
rewritten when the executable projection is introduced.  This module is the
versioned successor used by the separate private-runtime catalog adapter.

The intent is deliberately descriptive: it authenticates the shape and the
security boundary of a candidate, but it does not grant authority to a
caller, connect to PostgreSQL, or claim that a replay has happened.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping


INTENT_PREFIX = "-- PASTORAI_MIGRATION_INTENT_V2="
INTENT_ARTIFACT_ID = "migration-authoring-intent-v2"
SCOPE = "PRIVATE_RUNTIME"
OPERATIONAL_AUTHORIZATION = False
NEXT_STAGE_AUTHORIZED = False
GIT_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
MIGRATION_BASENAME_RE = re.compile(
    r"^[0-9]{8}_[0-9]{6}_[a-z][a-z0-9_]{0,119}\.sql\Z"
)
EXPECTED_AFFECTED_OBJECTS = frozenset(
    {
        "agent_private",
        "agent_private.current_tenant_id()",
        "agent_private.load_turn_context(uuid)",
        "agent_projection_owner",
        "agent_runtime",
        "public.conversations",
        "public.current_igreja_id()",
        "public.pessoas",
    }
)

PROJECTION_COLUMNS = [
    {"name": "igreja_id", "type": "uuid"},
    {"name": "conversation_id", "type": "uuid"},
    {"name": "pessoa_id", "type": "uuid"},
    {"name": "conversation_state", "type": "text"},
    {"name": "pessoa_optout", "type": "boolean"},
    {"name": "pessoa_sem_interesse", "type": "boolean"},
]

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
        "projection_owner_role",
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
        "return_columns",
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
        "direct_projection_owner_grants",
    }
)
CONFIG_KEYS = frozenset(
    {
        "tenant_guc",
        "runtime_database_url_env",
        "read_only_boundary",
        "role_config",
        "default_acl_policy",
        "gates",
    }
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
    """Raised when a private projection intent widens or omits controls."""


def _is_sha(value: object) -> bool:
    return (
        type(value) is str
        and GIT_SHA_RE.fullmatch(value) is not None
        and set(value) != {"0"}
    )


def _closed_string_list(value: object, *, allow_empty: bool = False) -> bool:
    if type(value) is not list or (not allow_empty and not value):
        return False
    if not all(type(item) is str and item.strip() for item in value):
        return False
    return len(value) == len(set(value))


def _closed_projection_columns(value: object) -> bool:
    if type(value) is not list or value != PROJECTION_COLUMNS:
        return False
    return all(
        type(column) is dict
        and set(column) == {"name", "type"}
        and type(column["name"]) is str
        and type(column["type"]) is str
        for column in value
    )


def _closed_grant_list(value: object, *, expected: list[dict[str, object]] | None = None) -> bool:
    if type(value) is not list:
        return False
    normalized: list[tuple[object, ...]] = []
    for item in value:
        if type(item) is not dict or set(item) != {"object", "grantee", "privilege", "grantable"}:
            return False
        if (
            not all(type(item[key]) is str and item[key].strip() for key in ("object", "grantee", "privilege"))
            or item["grantee"].upper() in {"PUBLIC", "ANONYMOUS"}
            or item["grantable"] is not False
        ):
            return False
        normalized.append((item["object"], item["grantee"], item["privilege"], item["grantable"]))
    if len(normalized) != len(set(normalized)):
        return False
    return expected is None or value == expected


def _role(name: str) -> dict[str, object]:
    return {
        "name": name,
        "login": False,
        "inherit": False,
        "superuser": False,
        "createrole": False,
        "createdb": False,
        "replication": False,
        "bypassrls": False,
        "memberships": [],
    }


def default_private_runtime_controls() -> dict[str, object]:
    """Return the exact closed contract for the installed projection."""

    helper = {
        "identity": "agent_private.current_tenant_id()",
        "schema": "agent_private",
        "name": "current_tenant_id",
        "returns": "uuid",
        "return_columns": [],
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
    projection_owner = "agent_projection_owner"
    return {
        "schema": {
            "name": "agent_private",
            "owner": "CURRENT_MIGRATION_ROLE",
            "public_usage": False,
            "runtime_usage": True,
        },
        "runtime_role": _role("agent_runtime"),
        "projection_owner_role": _role(projection_owner),
        "tenant_context": {
            "name": "current_tenant_id",
            "schema": "agent_private",
            "guc": "app.tenant_igreja_id",
            "returns": "uuid",
            "source": "current_setting('app.tenant_igreja_id', true)",
            "null_behavior": "NULL_WHEN_UNSET",
        },
        "functions": [helper],
        "projection_function": {
            "identity": "agent_private.load_turn_context(uuid)",
            "schema": "agent_private",
            "name": "load_turn_context",
            "returns": "TABLE",
            "return_columns": PROJECTION_COLUMNS,
            "security_definer": True,
            "volatility": "STABLE",
            "strict": True,
            "search_path": ["pg_catalog", "agent_private"],
            "owner": projection_owner,
            "execute_grantees": ["agent_runtime"],
            "public_execute": False,
            "read_only": True,
            "writes_allowed": False,
            "lifecycle": "FUTURE_PROJECTION_CONTRACT",
        },
        # There are no new private relations.  The projection reads the two
        # existing public relations through exact column grants and their
        # existing RLS policies plus an owner-specific tenant barrier.
        "relations": [],
        "acl": {
            "schema_usage": ["agent_runtime", projection_owner],
            "relation_select": [],
            "function_execute": ["agent_runtime"],
            "direct_public_grants": [],
            "direct_runtime_grants": [
                {"object": "agent_private", "grantee": "agent_runtime", "privilege": "USAGE", "grantable": False},
                {"object": "agent_private.current_tenant_id()", "grantee": "agent_runtime", "privilege": "EXECUTE", "grantable": False},
                {"object": "agent_private.load_turn_context(uuid)", "grantee": "agent_runtime", "privilege": "EXECUTE", "grantable": False},
            ],
            "direct_projection_owner_grants": [
                {"object": "agent_private", "grantee": projection_owner, "privilege": "USAGE", "grantable": False},
                {"object": "agent_private.current_tenant_id()", "grantee": projection_owner, "privilege": "EXECUTE", "grantable": False},
                {"object": "public.current_igreja_id()", "grantee": projection_owner, "privilege": "EXECUTE", "grantable": False},
                {"object": "public.pessoas", "grantee": projection_owner, "privilege": "SELECT(igreja_id,id,optout,sem_interesse)", "grantable": False},
                {"object": "public.conversations", "grantee": projection_owner, "privilege": "SELECT(igreja_id,id,pessoa_id,estado)", "grantable": False},
            ],
        },
        "config": {
            "tenant_guc": "app.tenant_igreja_id",
            "runtime_database_url_env": "AGENT_RUNTIME_DATABASE_URL",
            "read_only_boundary": True,
            "role_config": ["row_security=on", "search_path=pg_catalog, agent_private"],
            "default_acl_policy": "NO_RUNTIME_OR_PROJECTION_OWNER_DEFAULT_PRIVILEGES",
            "gates": {"operational_authorization": False, "next_stage_authorized": False},
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
            "agent_private.load_turn_context(uuid)",
            "agent_projection_owner",
            "agent_runtime",
            "public.conversations",
            "public.current_igreja_id()",
            "public.pessoas",
        ],
        "private_runtime_controls": default_private_runtime_controls(),
        "decision_refs": ["TODO"],
        "recovery": {"kind": "TODO", "reference": "TODO"},
        "pg17_test_nodeids": ["TODO"],
        "cross_tenant_test_nodeids": ["TODO"],
        "operational_authorization": False,
        "next_stage_authorized": False,
    }


def _validate_role(value: object, expected_name: str) -> None:
    if type(value) is not dict or set(value) != ROLE_KEYS or value != _role(expected_name):
        raise PrivateRuntimeIntentError("role contract is invalid")


def _validate_controls(controls: object) -> None:
    if type(controls) is not dict or set(controls) != CONTROL_KEYS:
        raise PrivateRuntimeIntentError("private runtime controls are not closed")
    if controls["schema"] != {
        "name": "agent_private",
        "owner": "CURRENT_MIGRATION_ROLE",
        "public_usage": False,
        "runtime_usage": True,
    }:
        raise PrivateRuntimeIntentError("private schema contract is invalid")
    _validate_role(controls["runtime_role"], "agent_runtime")
    _validate_role(controls["projection_owner_role"], "agent_projection_owner")
    expected_tenant = default_private_runtime_controls()["tenant_context"]
    tenant = controls["tenant_context"]
    if type(tenant) is not dict or set(tenant) != TENANT_CONTEXT_KEYS or tenant != expected_tenant:
        raise PrivateRuntimeIntentError("tenant context contract is invalid")

    functions = controls["functions"]
    if type(functions) is not list or len(functions) != 1:
        raise PrivateRuntimeIntentError("helper function contract is invalid")
    helper = functions[0]
    if type(helper) is not dict or set(helper) != FUNCTION_KEYS:
        raise PrivateRuntimeIntentError("helper function contract is not closed")
    if (
        helper["identity"] != "agent_private.current_tenant_id()"
        or helper["schema"] != "agent_private"
        or helper["name"] != "current_tenant_id"
        or helper["returns"] != "uuid"
        or helper["return_columns"] != []
        or helper["security_definer"] is not False
        or helper["volatility"] != "STABLE"
        or helper["strict"] is not False
        or helper["search_path"] != ["pg_catalog"]
        or helper["owner"] != "CURRENT_MIGRATION_ROLE"
        or helper["execute_grantees"] != ["agent_runtime"]
        or helper["public_execute"] is not False
        or helper["read_only"] is not True
        or helper["writes_allowed"] is not False
        or helper["lifecycle"] != "EXISTING_HELPER"
    ):
        raise PrivateRuntimeIntentError("helper function contract is invalid")

    projection = controls["projection_function"]
    if type(projection) is not dict or set(projection) != FUNCTION_KEYS:
        raise PrivateRuntimeIntentError("projection function contract is not closed")
    if (
        projection["identity"] != "agent_private.load_turn_context(uuid)"
        or projection["schema"] != "agent_private"
        or projection["name"] != "load_turn_context"
        or projection["returns"] != "TABLE"
        or not _closed_projection_columns(projection["return_columns"])
        or projection["security_definer"] is not True
        or projection["volatility"] != "STABLE"
        or projection["strict"] is not True
        or projection["search_path"] != ["pg_catalog", "agent_private"]
        or projection["owner"] != "agent_projection_owner"
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
    expected_acl = default_private_runtime_controls()["acl"]
    if (
        acl["schema_usage"] != expected_acl["schema_usage"]
        or acl["relation_select"] != []
        or acl["function_execute"] != ["agent_runtime"]
        or acl["direct_public_grants"] != []
        or not _closed_grant_list(acl["direct_runtime_grants"], expected=expected_acl["direct_runtime_grants"])
        or not _closed_grant_list(acl["direct_projection_owner_grants"], expected=expected_acl["direct_projection_owner_grants"])
    ):
        raise PrivateRuntimeIntentError("ACL contract grants an unsafe principal")

    config = controls["config"]
    if type(config) is not dict or set(config) != CONFIG_KEYS:
        raise PrivateRuntimeIntentError("runtime configuration is not closed")
    if config != default_private_runtime_controls()["config"]:
        raise PrivateRuntimeIntentError("runtime configuration widens authority")


def validate_intent(
    intent: Mapping[str, object],
    *,
    basename: str | None = None,
    expected_sha: str | None = None,
) -> dict[str, object]:
    """Validate and return a detached private-runtime intent."""

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
        or MIGRATION_BASENAME_RE.fullmatch(value_basename) is None
        or (basename is not None and value_basename != basename)
    ):
        raise PrivateRuntimeIntentError("private migration basename is invalid")
    objects = intent["affected_objects"]
    if (
        type(objects) is not list
        or not objects
        or objects != sorted(objects)
        or len(objects) != len(set(objects))
        or not all(type(item) is str and item.strip() for item in objects)
        or set(objects) != EXPECTED_AFFECTED_OBJECTS
    ):
        raise PrivateRuntimeIntentError("affected objects are invalid")
    _validate_controls(intent["private_runtime_controls"])
    refs = intent["decision_refs"]
    if not _closed_string_list(refs) or not all(DECISION_REFERENCE_RE.fullmatch(item) for item in refs):
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


def parse_intent(
    content: bytes,
    *,
    basename: str | None = None,
    expected_sha: str | None = None,
) -> dict[str, object]:
    """Parse exactly one V2 header and validate the executable contract."""

    if (
        type(content) is not bytes
        or b"\x00" in content
        or b"PRIVATE_RUNTIME_MIGRATION_DRAFT_INCOMPLETE" in content
        or content.count(b"OPERATIONAL_AUTHORIZATION=BLOCKED") != 1
        or content.count(b"NEXT_STAGE_AUTHORIZED=false") != 1
    ):
        raise PrivateRuntimeIntentError("invalid private-runtime bytes")
    first_line, separator, _body = content.partition(b"\n")
    prefix = INTENT_PREFIX.encode("ascii")
    if not separator or not first_line.startswith(prefix) or content.count(prefix) != 1:
        raise PrivateRuntimeIntentError("V2 intent prefix is missing or not unique")
    try:
        intent = json.loads(first_line[len(prefix) :].decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrivateRuntimeIntentError("V2 intent JSON is invalid") from exc
    return validate_intent(intent, basename=basename, expected_sha=expected_sha)


def render_draft(*, basename: str, base_repository_sha: str) -> bytes:
    value = default_intent(basename=basename, base_repository_sha=base_repository_sha)
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return (
        (INTENT_PREFIX + encoded + "\n").encode("ascii")
        + b"-- PRIVATE_RUNTIME_MIGRATION_DRAFT_INCOMPLETE\n"
        + b"-- Complete decision/recovery references and PG17/cross-tenant nodeids.\n"
        + b"-- This candidate is source-only; no catalog or database is changed.\n"
        + b"-- OPERATIONAL_AUTHORIZATION=BLOCKED\n"
        + b"-- NEXT_STAGE_AUTHORIZED=false\n"
    )


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


validate_private_runtime_intent = validate_intent
parse_private_runtime_intent = parse_intent


@dataclass(frozen=True)
class PrivateRuntimeProjectionCandidate:
    basename: str
    content: bytes
    content_sha256: str
