#!/usr/bin/env python3
"""Authenticate a PRIVATE_RUNTIME append beside the historical V1 catalog.

The public migration catalog has a deliberately closed V1 parser.  A private
runtime migration therefore cannot masquerade as a V1 ``TENANT`` migration:
doing so would either weaken the old proof or force unrelated public RLS
changes.  This adapter is the versioned seam for the new scope.  It accepts
only a V2 header, validates the closed V2 intent, and applies a small lexical
guard to the SQL before the PG17 replay performs catalog-level checks.

This module never approves a migration, opens a database, or changes either
operational gate.  CI/replay callers must authenticate its source bytes before
executing it and must still run the historical V1 verifier over its immutable
snapshot separately.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import re
from pathlib import Path
import sys
from typing import Mapping

try:
    from private_runtime_intent_runtime_v1 import (
        INTENT_PREFIX as V2_INTENT_PREFIX,
        MIGRATION_BASENAME_RE,
        PrivateRuntimeIntentError,
        parse_intent,
    )
except ImportError:  # pragma: no cover - direct ``python -I`` execution
    _intent_spec = importlib.util.spec_from_file_location(
        "private_runtime_intent_runtime_v1_for_catalog_adapter",
        Path(__file__).with_name("private_runtime_intent_runtime_v1.py"),
    )
    if _intent_spec is None or _intent_spec.loader is None:
        raise
    _intent_module = importlib.util.module_from_spec(_intent_spec)
    sys.modules[_intent_spec.name] = _intent_module
    _intent_spec.loader.exec_module(_intent_module)
    V2_INTENT_PREFIX = _intent_module.INTENT_PREFIX
    MIGRATION_BASENAME_RE = _intent_module.MIGRATION_BASENAME_RE
    PrivateRuntimeIntentError = _intent_module.PrivateRuntimeIntentError
    parse_intent = _intent_module.parse_intent


V1_INTENT_PREFIX = "-- PASTORAI_MIGRATION_INTENT_V1="
V2_SCOPE = "PRIVATE_RUNTIME"
ADAPTER_ARTIFACT_ID = "private-runtime-catalog-adapter-v1"
OPERATIONAL_BLOCK = b"OPERATIONAL_AUTHORIZATION=BLOCKED"
NEXT_STAGE_BLOCK = b"NEXT_STAGE_AUTHORIZED=false"
INCOMPLETE_MARKERS = (
    b"MIGRATION_DRAFT_INCOMPLETE",
    b"MIGRATION_POLICY_DRAFT_INCOMPLETE",
)
MAX_CANDIDATE_BYTES = 4_194_304

_REQUIRED_SQL_MARKERS = (
    re.compile(r"\bcreate\s+role\s+agent_projection_owner\b", re.I),
    re.compile(r"\bload_turn_context\b", re.I),
    re.compile(r"\bsecurity\s+definer\b", re.I),
    re.compile(r"\brow_security\b", re.I),
    re.compile(r"\bcreate\s+policy\b", re.I),
)
_FORBIDDEN_SQL_MARKERS = (
    re.compile(r"\bdrop\s+(?:schema|table|role)\b", re.I),
    re.compile(r"\bcreate\s+table\b", re.I),
    re.compile(r"\btruncate\b", re.I),
)


class PrivateRuntimeCatalogAdapterError(ValueError):
    """Raised when a candidate is not a V2 private-runtime append."""


@dataclass(frozen=True)
class PrivateRuntimeCandidate:
    basename: str
    content_sha256: str
    intent: Mapping[str, object]


def _has_terminated_sql_statement(text: str) -> bool:
    """Recognize a semicolon outside PostgreSQL comments and quotations."""

    index = 0
    block_depth = 0
    quote: str | None = None
    dollar_tag: str | None = None
    token_seen = False
    while index < len(text):
        if block_depth:
            if text.startswith("/*", index):
                block_depth += 1
                index += 2
            elif text.startswith("*/", index):
                block_depth -= 1
                index += 2
            else:
                index += 1
            continue
        if dollar_tag is not None:
            if text.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = None
            else:
                index += 1
            continue
        if quote is not None:
            if text[index] == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                else:
                    quote = None
                    index += 1
            elif quote == "'" and text[index] == "\\":
                index += 2
            else:
                index += 1
            continue
        if text.startswith("--", index):
            newline = text.find("\n", index + 2)
            index = len(text) if newline < 0 else newline + 1
            continue
        if text.startswith("/*", index):
            block_depth = 1
            index += 2
            continue
        if text[index] in {"'", '"'}:
            quote = text[index]
            token_seen = True
            index += 1
            continue
        if text[index] == "$":
            match = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", text[index:])
            if match is not None:
                dollar_tag = match.group(0)
                token_seen = True
                index += len(dollar_tag)
                continue
        if text[index] == ";":
            if token_seen:
                return True
            index += 1
            continue
        if not text[index].isspace():
            token_seen = True
        index += 1
    return False


def _validate_sql_shape(content: bytes) -> None:
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PrivateRuntimeCatalogAdapterError("candidate SQL is not UTF-8") from exc
    body = text.split("\n", 1)[1] if "\n" in text else ""
    code = _sql_code_without_comments_and_literals(body)
    if not _has_terminated_sql_statement(body):
        raise PrivateRuntimeCatalogAdapterError("candidate SQL is not terminated")
    if any(marker.search(code) for marker in _FORBIDDEN_SQL_MARKERS):
        raise PrivateRuntimeCatalogAdapterError("candidate SQL widens destructive scope")
    if any(not marker.search(code) for marker in _REQUIRED_SQL_MARKERS):
        raise PrivateRuntimeCatalogAdapterError("candidate SQL lacks private-runtime controls")


def _sql_code_without_comments_and_literals(value: str) -> str:
    """Keep executable-looking SQL while ignoring comment/string decoys."""

    output: list[str] = []
    index = 0
    block_depth = 0
    quote: str | None = None
    while index < len(value):
        character = value[index]
        if block_depth:
            if value.startswith("/*", index):
                block_depth += 1
                index += 2
            elif value.startswith("*/", index):
                block_depth -= 1
                index += 2
            else:
                output.append(" ")
                index += 1
            continue
        if quote is not None:
            if character == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    output.extend((" ", " "))
                    index += 2
                else:
                    quote = None
                    output.append(" ")
                    index += 1
            else:
                output.append(" ")
                index += 1
            continue
        if value.startswith("--", index):
            newline = value.find("\n", index + 2)
            if newline < 0:
                output.extend(" " for _ in value[index:])
                break
            output.extend(" " for _ in value[index:newline])
            output.append("\n")
            index = newline + 1
            continue
        if value.startswith("/*", index):
            block_depth = 1
            output.extend((" ", " "))
            index += 2
            continue
        if character in {"'", '"'}:
            quote = character
            output.append(" ")
            index += 1
            continue
        output.append(character)
        index += 1
    if block_depth or quote is not None:
        raise PrivateRuntimeCatalogAdapterError("candidate SQL has unterminated syntax")
    return "".join(output)


def validate_private_runtime_candidate(
    content: bytes,
    *,
    basename: str,
    expected_sha: str | None = None,
) -> PrivateRuntimeCandidate:
    """Validate one V2-only migration candidate without touching a database."""

    if (
        type(content) is not bytes
        or not content
        or len(content) > MAX_CANDIDATE_BYTES
        or b"\x00" in content
        or type(basename) is not str
        or MIGRATION_BASENAME_RE.fullmatch(basename) is None
    ):
        raise PrivateRuntimeCatalogAdapterError("candidate envelope is invalid")
    if content.count(V2_INTENT_PREFIX.encode("ascii")) != 1:
        raise PrivateRuntimeCatalogAdapterError("V2 marker must be unique")
    if V1_INTENT_PREFIX.encode("ascii") in content:
        raise PrivateRuntimeCatalogAdapterError("private candidate cannot claim V1")
    first_line, separator, _body = content.partition(b"\n")
    if not separator or not first_line.startswith(V2_INTENT_PREFIX.encode("ascii")):
        raise PrivateRuntimeCatalogAdapterError("V2 marker must be the first header")
    if any(content.count(marker) != 1 for marker in (OPERATIONAL_BLOCK, NEXT_STAGE_BLOCK)):
        raise PrivateRuntimeCatalogAdapterError("authorization gates are not closed exactly once")
    if any(marker in content for marker in INCOMPLETE_MARKERS):
        raise PrivateRuntimeCatalogAdapterError("candidate is incomplete")
    try:
        intent = parse_intent(
            content,
            basename=basename,
            expected_sha=expected_sha,
        )
    except PrivateRuntimeIntentError as exc:
        raise PrivateRuntimeCatalogAdapterError("V2 intent is invalid") from exc
    if intent.get("scope") != V2_SCOPE:
        raise PrivateRuntimeCatalogAdapterError("candidate scope is not private runtime")
    _validate_sql_shape(content)
    return PrivateRuntimeCandidate(
        basename=basename,
        content_sha256=hashlib.sha256(content).hexdigest(),
        intent=intent,
    )


def is_private_runtime_candidate(content: bytes) -> bool:
    """Return whether bytes opt into the V2 private adapter path."""

    return (
        type(content) is bytes
        and content.startswith(V2_INTENT_PREFIX.encode("ascii"))
    )


# Descriptive aliases for callers and tests; the adapter remains one API.
validate_candidate = validate_private_runtime_candidate
validate_private_runtime_migration = validate_private_runtime_candidate
