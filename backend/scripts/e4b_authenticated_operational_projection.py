"""Pure, negative-only validation for the separate E4b projection contract.

This module deliberately has no filesystem, Git, subprocess, network, database,
blob-reader, root-publication, or consumer API. It compares synthetic claims to
synthetic policy; it does not authenticate raw Git objects. A BLOCKED receipt is
diagnostic evidence, never an operational source authentication or execution permit.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from typing import Any, Sequence


BLOCKED_RECEIPT_SCHEMA = "e4b-operational-projection-blocked-receipt-v1"
PATCH_RECEIPT_SCHEMA = "e4b-patch-receipt-v1"
RUNTIME_STATUS = "NOT_EVALUATED"
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_RECIPE_ID = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}\Z")
_COMPONENT = re.compile(rb"[A-Za-z0-9._-]+\Z")

_ELIGIBLE_PREFIXES = (
    "backend/app/",
    "backend/migrations/",
    "backend/scripts/",
    "backend/tests/",
    "docs/governance/migrations/",
    "docs/missions/",
    "docs/ops/e4b-filadelfia-catalog-materialization/",
)
_ELIGIBLE_EXACT = {"backend/requirements.lock"}
_PROTECTED_DIRECTORIES = {
    "backup",
    "backups",
    "dump",
    "dumps",
    "export",
    "exports",
    "media",
    "secrets",
}
_PROTECTED_SUFFIXES = (
    ".7z",
    ".avi",
    ".bak",
    ".backup",
    ".dump",
    ".gif",
    ".jpeg",
    ".jpg",
    ".key",
    ".m4a",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".pem",
    ".png",
    ".sql.gz",
    ".tar",
    ".tgz",
    ".wav",
    ".webm",
    ".webp",
    ".zip",
)


@dataclass(frozen=True)
class TrustPolicy:
    expected_commit_sha: str
    expected_tree_sha: str
    expected_parent_sha: str
    expected_base_sha: str
    expected_ancestry_digest_sha256: str
    expected_patch_receipt_sha256: str
    expected_patch_digest_sha256: str
    expected_patch_recipe_id: str
    expected_patch_recipe_version: int


@dataclass(frozen=True)
class TreeEntry:
    path: bytes
    object_id: str
    kind: str
    mode: str
    size: int


@dataclass(frozen=True)
class DependencyResolution:
    status: str
    required_paths: tuple[str, ...]
    reason: str


def classify_path(path: bytes) -> str:
    """Classify path metadata without requesting content."""

    canonical = _canonical_path(path)
    if canonical is None:
        return "INVALID"
    parts = canonical.split("/")
    basename = parts[-1]
    lower = canonical.lower()
    lower_basename = basename.lower()
    if basename == ".env" or basename.startswith(".env."):
        return "PROTECTED"
    if any(part.lower() in _PROTECTED_DIRECTORIES for part in parts):
        return "PROTECTED"
    if lower_basename.startswith(("id_rsa", "id_ed25519")):
        return "PROTECTED"
    if lower_basename.endswith(_PROTECTED_SUFFIXES):
        return "PROTECTED"
    if canonical.startswith("backend/scripts/clerk_"):
        return "PROTECTED"
    if (
        canonical.startswith("backend/scripts/target_users")
        and lower_basename.endswith(".json")
    ):
        return "PROTECTED"
    if canonical == "backend/scripts/migrate_clerk_production.py":
        return "PROTECTED"
    if canonical in _ELIGIBLE_EXACT or canonical.startswith(_ELIGIBLE_PREFIXES):
        return "ELIGIBLE"
    return "UNKNOWN"


def preflight_blocked(
    policy: TrustPolicy,
    tree_entries: Sequence[TreeEntry],
    selected_paths: Sequence[str],
    resolution: DependencyResolution,
    patch_receipt_bytes: bytes,
) -> dict[str, object]:
    """Validate metadata and always return a non-operational BLOCKED receipt."""

    if not _valid_policy(policy):
        return _blocked("TRUST_POLICY_INVALID", "NOT_PROVEN", 0, None, "NOT_READ")

    tree_result = _validate_tree(tree_entries)
    if isinstance(tree_result, str):
        return _blocked(tree_result, "NOT_PROVEN", 0, None, "NOT_READ")
    entries_by_path, protected_ids, commitment = tree_result

    selection_result = _validate_selection(
        selected_paths, entries_by_path, protected_ids
    )
    if isinstance(selection_result, str):
        return _blocked(selection_result, "NOT_PROVEN", 0, commitment, "NOT_READ")

    if not _valid_patch_receipt(policy, patch_receipt_bytes):
        return _blocked(
            "PATCH_RECEIPT_INVALID",
            "NOT_PROVEN",
            len(selection_result),
            commitment,
            "INVALID",
        )

    if not _valid_resolution(resolution):
        return _blocked(
            "DEPENDENCY_RESOLUTION_INVALID",
            "NOT_PROVEN",
            len(selection_result),
            commitment,
            "VALID",
        )
    if resolution.status == "BLOCKED":
        return _blocked(
            "DEPENDENCY_CLOSURE_NOT_PROVEN",
            "NOT_PROVEN",
            len(selection_result),
            commitment,
            "VALID",
        )
    if tuple(selected_paths) != resolution.required_paths:
        return _blocked(
            "DEPENDENCY_SELECTION_INCOMPLETE",
            "NOT_PROVEN",
            len(selection_result),
            commitment,
            "VALID",
        )
    return _blocked(
        "SOURCE_ONLY_EXECUTION_DISABLED",
        "FORGED_RESOLVED_NOT_EXECUTED",
        len(selection_result),
        commitment,
        "VALID",
    )


def _blocked(
    reason: str,
    closure_status: str,
    selected_path_count: int,
    protected_object_commitment_sha256: str | None,
    patch_receipt_status: str,
) -> dict[str, object]:
    return {
        "schema": BLOCKED_RECEIPT_SCHEMA,
        "status": "BLOCKED",
        "operational_authorization": False,
        "reason": reason,
        "closure_status": closure_status,
        "runtime_status": RUNTIME_STATUS,
        "selected_path_count": selected_path_count,
        "protected_object_commitment_sha256": protected_object_commitment_sha256,
        "patch_receipt_status": patch_receipt_status,
    }


def _canonical_path(path: object) -> str | None:
    if type(path) is not bytes or not path or b"\x00" in path or b"\\" in path:
        return None
    try:
        text = path.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        return None
    parts = text.split("/")
    if any(
        not part
        or part in {".", ".."}
        or _COMPONENT.fullmatch(part.encode("ascii")) is None
        for part in parts
    ):
        return None
    return text


def _valid_policy(policy: object) -> bool:
    if type(policy) is not TrustPolicy:
        return False
    return (
        all(
            type(value) is str and _HEX40.fullmatch(value)
            for value in (
                policy.expected_commit_sha,
                policy.expected_tree_sha,
                policy.expected_parent_sha,
                policy.expected_base_sha,
            )
        )
        and type(policy.expected_ancestry_digest_sha256) is str
        and _HEX64.fullmatch(policy.expected_ancestry_digest_sha256) is not None
        and type(policy.expected_patch_digest_sha256) is str
        and _HEX64.fullmatch(policy.expected_patch_digest_sha256) is not None
        and type(policy.expected_patch_receipt_sha256) is str
        and _HEX64.fullmatch(policy.expected_patch_receipt_sha256) is not None
        and type(policy.expected_patch_recipe_id) is str
        and _RECIPE_ID.fullmatch(policy.expected_patch_recipe_id) is not None
        and type(policy.expected_patch_recipe_version) is int
        and policy.expected_patch_recipe_version > 0
    )


def _validate_tree(
    tree_entries: Sequence[TreeEntry],
) -> tuple[dict[str, TreeEntry], set[str], str] | str:
    if type(tree_entries) not in {tuple, list}:
        return "TREE_METADATA_INVALID"
    entries_by_path: dict[str, TreeEntry] = {}
    protected_ids: set[str] = set()
    casefold_paths: set[str] = set()
    previous: bytes | None = None
    for entry in tree_entries:
        if (
            type(entry) is not TreeEntry
            or type(entry.object_id) is not str
            or _HEX40.fullmatch(entry.object_id) is None
            or type(entry.kind) is not str
            or entry.kind != "blob"
            or type(entry.mode) is not str
            or entry.mode not in {"100644", "100755"}
            or type(entry.size) is not int
            or entry.size < 0
        ):
            return "TREE_METADATA_INVALID"
        canonical = _canonical_path(entry.path)
        if canonical is None:
            return "PATH_INVALID"
        if previous is not None and entry.path <= previous:
            return "TREE_ORDER_INVALID"
        folded = canonical.casefold()
        if folded in casefold_paths:
            return "PATH_CASEFOLD_COLLISION"
        classification = classify_path(entry.path)
        if classification == "UNKNOWN":
            return "UNKNOWN_PATH_CLASS"
        if classification == "INVALID":
            return "PATH_INVALID"
        entries_by_path[canonical] = entry
        casefold_paths.add(folded)
        if classification == "PROTECTED":
            protected_ids.add(entry.object_id)
        previous = entry.path
    if not entries_by_path:
        return "TREE_METADATA_INVALID"
    commitment = hashlib.sha256(
        b"E4B-PROTECTED-OBJECTS-V1\x00"
        + _canonical_json_bytes({"object_ids": sorted(protected_ids), "version": 1})
    ).hexdigest()
    return entries_by_path, protected_ids, commitment


def _validate_selection(
    selected_paths: Sequence[str],
    entries_by_path: dict[str, TreeEntry],
    protected_ids: set[str],
) -> tuple[str, ...] | str:
    if type(selected_paths) not in {tuple, list} or not selected_paths:
        return "SELECTION_INVALID"
    selected = tuple(selected_paths)
    if any(type(path) is not str for path in selected):
        return "SELECTION_INVALID"
    for path in selected:
        try:
            encoded = path.encode("ascii", errors="strict")
        except UnicodeEncodeError:
            return "SELECTION_INVALID"
        if _canonical_path(encoded) != path:
            return "SELECTION_INVALID"
    if selected != tuple(sorted(selected)) or len(selected) != len(set(selected)):
        return "SELECTION_INVALID"
    for path in selected:
        entry = entries_by_path.get(path)
        if entry is None or classify_path(entry.path) != "ELIGIBLE":
            return "SELECTION_INVALID"
        if entry.object_id in protected_ids:
            return "PROTECTED_OBJECT_ALIAS"
    return selected


def _valid_resolution(resolution: object) -> bool:
    if type(resolution) is not DependencyResolution:
        return False
    if (
        type(resolution.status) is not str
        or resolution.status not in {"BLOCKED", "RESOLVED"}
        or type(resolution.reason) is not str
    ):
        return False
    if type(resolution.required_paths) is not tuple:
        return False
    return all(type(path) is str for path in resolution.required_paths)


def _valid_patch_receipt(policy: TrustPolicy, raw: object) -> bool:
    if type(raw) is not bytes or not 0 < len(raw) <= 65_536:
        return False
    digest = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(digest, policy.expected_patch_receipt_sha256):
        return False
    try:
        decoded = json.loads(
            raw.decode("utf-8", errors="strict"), object_pairs_hook=_no_duplicates
        )
    except (UnicodeDecodeError, ValueError, RecursionError):
        return False
    if type(decoded) is not dict or set(decoded) != {"schema", "candidate", "patch"}:
        return False
    candidate = decoded["candidate"]
    patch = decoded["patch"]
    if type(decoded["schema"]) is not str or decoded["schema"] != PATCH_RECEIPT_SCHEMA:
        return False
    if type(candidate) is not dict or set(candidate) != {
        "commit_sha",
        "tree_sha",
        "parent_sha",
        "base_sha",
        "ancestry_digest_sha256",
    }:
        return False
    if type(patch) is not dict or set(patch) != {
        "algorithm",
        "digest_sha256",
        "recipe_id",
        "recipe_version",
    }:
        return False
    if (
        type(patch["algorithm"]) is not str
        or type(patch["recipe_id"]) is not str
        or _RECIPE_ID.fullmatch(patch["recipe_id"]) is None
        or type(patch["recipe_version"]) is not int
    ):
        return False
    return (
        all(
            type(candidate[key]) is str and _HEX40.fullmatch(candidate[key]) is not None
            for key in ("commit_sha", "tree_sha", "parent_sha", "base_sha")
        )
        and type(candidate["ancestry_digest_sha256"]) is str
        and _HEX64.fullmatch(candidate["ancestry_digest_sha256"]) is not None
        and candidate["commit_sha"] == policy.expected_commit_sha
        and candidate["tree_sha"] == policy.expected_tree_sha
        and candidate["parent_sha"] == policy.expected_parent_sha
        and candidate["base_sha"] == policy.expected_base_sha
        and candidate["ancestry_digest_sha256"] == policy.expected_ancestry_digest_sha256
        and patch["algorithm"] == "sha256"
        and type(patch["digest_sha256"]) is str
        and _HEX64.fullmatch(patch["digest_sha256"]) is not None
        and patch["digest_sha256"] == policy.expected_patch_digest_sha256
        and patch["recipe_id"] == policy.expected_patch_recipe_id
        and patch["recipe_version"] == policy.expected_patch_recipe_version
    )


def _no_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
