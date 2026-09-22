"""Authenticated, source-only E4b projection with an inert default boundary.

No default reader, command-line entrypoint, subprocess, archive, network or
consumer invocation exists here. A separately reviewed local Git-object adapter
is injected explicitly by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import threading
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence
import weakref


BLOCKED_RECEIPT_SCHEMA = "e4b-operational-projection-blocked-receipt-v1"
FINAL_RECEIPT_SCHEMA = "e4b-operational-projection-final-receipt-v1"
PATCH_RECEIPT_SCHEMA = "e4b-patch-receipt-v1"
DEPENDENCY_MANIFEST_SCHEMA = "e4b-operational-dependency-manifest-v1"
RUNTIME_STATUS = "NOT_EVALUATED"
FIXED_GIT_ENV = MappingProxyType(
    {
        "GIT_ALLOW_PROTOCOL": "file",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
    }
)
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_RECIPE_ID = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}\Z")
_COMPONENT = re.compile(rb"[A-Za-z0-9._\[\]-]+\Z")
_PUBLICATION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_MAX_RECEIPT_BYTES = 65_536
_MAX_MANIFEST_BYTES = 1_048_576

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
_PROTECTED_DATA_MARKERS = {
    "backup",
    "backups",
    "dump",
    "dumps",
    "export",
    "exports",
    "media",
}
_PROTECTED_DATA_SUFFIXES = (
    ".csv",
    ".flac",
    ".json",
    ".sql",
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


@dataclass(frozen=True)
class SourceTrustAnchors:
    expected_commit_sha: str
    expected_tree_sha: str
    expected_parent_sha: str
    expected_base_sha: str
    expected_ancestry_digest_sha256: str
    expected_patch_receipt_sha256: str
    expected_patch_digest_sha256: str
    expected_patch_recipe_id: str
    expected_patch_recipe_version: int
    expected_manifest_sha256: str


@dataclass(frozen=True)
class RepositoryFacts:
    commit_sha: str
    tree_sha: str
    parent_sha: str
    base_sha: str
    ancestry_digest_sha256: str


@dataclass(frozen=True)
class ManifestFile:
    path: str
    object_id: str
    mode: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ManifestOmission:
    path: str
    object_id: str
    mode: str
    size: int


@dataclass(frozen=True)
class DependencyManifest:
    files: tuple[ManifestFile, ...]
    omitted: tuple[ManifestOmission, ...]


@dataclass(frozen=True)
class FinalProjectionReceipt:
    schema: str
    status: str
    operational_authorization: bool
    commit_sha: str
    tree_sha: str
    parent_sha: str
    base_sha: str
    ancestry_digest_sha256: str
    patch_receipt_sha256: str
    patch_digest_sha256: str
    manifest_sha256: str
    root_digest_sha256: str
    protected_object_commitment_sha256: str
    file_count: int

    def __post_init__(self) -> None:
        if not _valid_final_receipt(self):
            raise ValueError("invalid final projection receipt")

    def to_sanitized_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "status": self.status,
            "operational_authorization": self.operational_authorization,
            "commit_sha": self.commit_sha,
            "tree_sha": self.tree_sha,
            "parent_sha": self.parent_sha,
            "base_sha": self.base_sha,
            "ancestry_digest_sha256": self.ancestry_digest_sha256,
            "patch_receipt_sha256": self.patch_receipt_sha256,
            "patch_digest_sha256": self.patch_digest_sha256,
            "manifest_sha256": self.manifest_sha256,
            "root_digest_sha256": self.root_digest_sha256,
            "protected_object_commitment_sha256": self.protected_object_commitment_sha256,
            "file_count": self.file_count,
        }


def _close_projection_handle_descriptor(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


class ProjectionRootHandle:
    """Private descriptor-backed access to the exact published root."""

    __slots__ = ("_descriptor", "_files", "_finalizer", "_lock", "__weakref__")

    def __init__(self, descriptor: int, files: tuple[ManifestFile, ...]) -> None:
        if (
            type(descriptor) is not int
            or type(files) is not tuple
            or not files
            or any(type(item) is not ManifestFile for item in files)
        ):
            raise ProjectionSourceError("PROJECTION_HANDLE_INVALID")
        self._descriptor: int | None = descriptor
        self._files = files
        self._lock = threading.Lock()
        self._finalizer = weakref.finalize(self, _close_projection_handle_descriptor, descriptor)

    def close(self) -> None:
        with self._lock:
            if self._descriptor is None:
                return
            self._descriptor = None
            finalizer = self._finalizer
        finalizer()

    def read_file(self, relative_path: str) -> bytes:
        descriptor = self._duplicate_open_descriptor()
        try:
            item = _manifest_file_for_handle(self._files, relative_path)
            return _read_projected_file(descriptor, item)
        finally:
            _close_projection_handle_descriptor(descriptor)

    def _duplicate_open_descriptor(self) -> int:
        with self._lock:
            descriptor = self._descriptor
            if type(descriptor) is not int:
                raise ProjectionSourceError("PROJECTION_HANDLE_CLOSED")
            try:
                return os.dup(descriptor)
            except OSError:
                raise ProjectionSourceError("PROJECTION_HANDLE_CLOSED") from None


@dataclass(frozen=True)
class PublishedProjection:
    root_handle: ProjectionRootHandle
    receipt: FinalProjectionReceipt

    def close(self) -> None:
        self.root_handle.close()


class GitBlobReader(Protocol):
    """Injected local object adapter; it must not fetch or use an archive."""

    def inspect_commit(
        self, commit_sha: str, environment: Mapping[str, str]
    ) -> RepositoryFacts: ...

    def list_tree(
        self, tree_sha: str, environment: Mapping[str, str]
    ) -> Sequence[TreeEntry]: ...

    def read_blob(self, object_id: str, environment: Mapping[str, str]) -> bytes: ...


class ProjectionSourceError(RuntimeError):
    """Sanitized, fail-closed source-projection error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _call_reader(reader: object, method_name: str, *arguments: object) -> object:
    """Call the injected adapter without exposing its arbitrary exceptions."""

    try:
        method = getattr(reader, method_name)
        if not callable(method):
            raise TypeError("reader method is not callable")
        return method(*arguments, FIXED_GIT_ENV)
    except ProjectionSourceError:
        raise
    except Exception:
        raise ProjectionSourceError("READER_ADAPTER_FAILURE") from None


def classify_path(path: bytes) -> str:
    """Classify path metadata without requesting content."""

    canonical = _canonical_path(path)
    if canonical is None:
        return "INVALID"
    folded = canonical.casefold()
    folded_parts = folded.split("/")
    folded_basename = folded_parts[-1]
    if folded_basename == ".env" or folded_basename.startswith(".env."):
        return "PROTECTED"
    if any(part in _PROTECTED_DIRECTORIES for part in folded_parts):
        return "PROTECTED"
    if folded_basename.startswith(("id_rsa", "id_ed25519")):
        return "PROTECTED"
    if folded_basename.endswith(_PROTECTED_SUFFIXES):
        return "PROTECTED"
    basename_markers = set(re.split(r"[._-]+", folded_basename))
    if (
        basename_markers & _PROTECTED_DATA_MARKERS
        and folded_basename.endswith(_PROTECTED_DATA_SUFFIXES)
    ):
        return "PROTECTED"
    if folded.startswith("backend/scripts/clerk_"):
        return "PROTECTED"
    if (
        folded.startswith("backend/scripts/target_users")
        and folded_basename.endswith(".json")
    ):
        return "PROTECTED"
    if folded == "backend/scripts/migrate_clerk_production.py":
        return "PROTECTED"
    if canonical in _ELIGIBLE_EXACT or canonical.startswith(_ELIGIBLE_PREFIXES):
        return "ELIGIBLE"
    return "OMITTED"


def preflight_blocked(
    policy: TrustPolicy,
    tree_entries: Sequence[TreeEntry],
    selected_paths: Sequence[str],
    resolution: DependencyResolution,
    patch_receipt_bytes: bytes,
) -> dict[str, object]:
    """Preserved negative precheck with no root, blob or consumer surface."""

    if not _valid_policy(policy):
        return _blocked("TRUST_POLICY_INVALID", "NOT_PROVEN", 0, None, "NOT_READ")
    tree_result = _validate_tree(tree_entries)
    if isinstance(tree_result, str):
        return _blocked(tree_result, "NOT_PROVEN", 0, None, "NOT_READ")
    entries_by_path, protected_ids, commitment = tree_result
    selection_result = _validate_selection(selected_paths, entries_by_path, protected_ids)
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


def materialize_authenticated_projection(
    *,
    anchors: SourceTrustAnchors,
    manifest_bytes: bytes,
    patch_receipt_bytes: bytes,
    reader: GitBlobReader,
    destination_parent: str,
    publication_name: str,
) -> PublishedProjection:
    """Materialize only a closed, externally anchored source projection.

    This explicit call is still source-only. It returns a typed source receipt
    with operational authorization fixed to false and never invokes a consumer.
    """

    if not _valid_source_anchors(anchors):
        raise ProjectionSourceError("TRUST_ANCHORS_INVALID")
    if not _valid_external_patch_receipt(anchors, patch_receipt_bytes):
        raise ProjectionSourceError("PATCH_RECEIPT_INVALID")
    manifest = _parse_dependency_manifest(anchors, manifest_bytes)

    facts_before = _call_reader(reader, "inspect_commit", anchors.expected_commit_sha)
    if not _facts_match_anchors(facts_before, anchors):
        raise ProjectionSourceError("REPOSITORY_ANCHOR_MISMATCH")
    tree_before = _call_reader(reader, "list_tree", anchors.expected_tree_sha)
    tree_result = _validate_tree(tree_before, allow_ordinary=True)
    if isinstance(tree_result, str):
        raise ProjectionSourceError(tree_result)
    entries_by_path, protected_ids, protected_commitment = tree_result
    _validate_manifest_against_tree(manifest, entries_by_path, protected_ids)
    tree_digest_before = _tree_metadata_digest(entries_by_path)

    blobs: list[tuple[ManifestFile, bytes]] = []
    for item in manifest.files:
        blob = _call_reader(reader, "read_blob", item.object_id)
        if type(blob) is not bytes or len(blob) != item.size:
            raise ProjectionSourceError("BLOB_SIZE_MISMATCH")
        if not hmac.compare_digest(hashlib.sha256(blob).hexdigest(), item.sha256):
            raise ProjectionSourceError("BLOB_HASH_MISMATCH")
        blobs.append((item, blob))

    facts_after = _call_reader(reader, "inspect_commit", anchors.expected_commit_sha)
    if not _same_facts(facts_before, facts_after) or not _facts_match_anchors(
        facts_after, anchors
    ):
        raise ProjectionSourceError("REPOSITORY_TOCTOU")
    tree_after = _call_reader(reader, "list_tree", anchors.expected_tree_sha)
    tree_after_result = _validate_tree(tree_after, allow_ordinary=True)
    if isinstance(tree_after_result, str):
        raise ProjectionSourceError("TREE_TOCTOU")
    if _tree_metadata_digest(tree_after_result[0]) != tree_digest_before:
        raise ProjectionSourceError("TREE_TOCTOU")

    if type(publication_name) is not str or _PUBLICATION_NAME.fullmatch(publication_name) is None:
        raise ProjectionSourceError("PUBLICATION_NAME_INVALID")
    parent, parent_descriptor = _open_private_destination_parent(destination_parent)
    reservation_name: str | None = None
    reservation_descriptor: int | None = None
    reservation_identity: tuple[int, int] | None = None
    staging_name: str | None = None
    staging_descriptor: int | None = None
    staging_identity: tuple[int, int] | None = None
    try:
        reservation_descriptor = _reserve_publication(parent_descriptor, publication_name)
        reservation_name = publication_name
        reservation_identity = _directory_identity(reservation_descriptor)
        if not _parent_path_matches_descriptor(parent, parent_descriptor):
            raise ProjectionSourceError("DESTINATION_CHANGED")
        staging_name, staging_descriptor = _reserve_staging(parent_descriptor)
        staging_identity = _directory_identity(staging_descriptor)
        for item, blob in blobs:
            _write_staged_file(staging_descriptor, item, blob)
        _verify_private_root(staging_descriptor, manifest.files)
        if not _parent_path_matches_descriptor(parent, parent_descriptor):
            raise ProjectionSourceError("DESTINATION_CHANGED")
        if _entry_exists(reservation_descriptor, "root"):
            raise ProjectionSourceError("PUBLICATION_CONFLICT")
        os.replace(
            staging_name,
            "root",
            src_dir_fd=parent_descriptor,
            dst_dir_fd=reservation_descriptor,
        )
        staging_name = None
        if not _parent_path_matches_descriptor(parent, parent_descriptor):
            raise ProjectionSourceError("DESTINATION_CHANGED")
        if staging_descriptor is None:
            raise ProjectionSourceError("MATERIALIZATION_FAILED")
        receipt = FinalProjectionReceipt(
            schema=FINAL_RECEIPT_SCHEMA,
            status="FINALIZED_SOURCE_ONLY",
            operational_authorization=False,
            commit_sha=anchors.expected_commit_sha,
            tree_sha=anchors.expected_tree_sha,
            parent_sha=anchors.expected_parent_sha,
            base_sha=anchors.expected_base_sha,
            ancestry_digest_sha256=anchors.expected_ancestry_digest_sha256,
            patch_receipt_sha256=anchors.expected_patch_receipt_sha256,
            patch_digest_sha256=anchors.expected_patch_digest_sha256,
            manifest_sha256=anchors.expected_manifest_sha256,
            root_digest_sha256=_root_digest(manifest.files),
            protected_object_commitment_sha256=protected_commitment,
            file_count=len(manifest.files),
        )
        root_handle = _create_projection_root_handle(staging_descriptor, manifest.files)
        staging_descriptor = None
        return PublishedProjection(root_handle=root_handle, receipt=receipt)
    except ProjectionSourceError:
        _cleanup_attempt(
            parent_descriptor,
            staging_name,
            staging_identity,
            reservation_name,
            reservation_identity,
        )
        raise
    except OSError:
        _cleanup_attempt(
            parent_descriptor,
            staging_name,
            staging_identity,
            reservation_name,
            reservation_identity,
        )
        raise ProjectionSourceError("MATERIALIZATION_FAILED") from None
    finally:
        if staging_descriptor is not None:
            os.close(staging_descriptor)
        if reservation_descriptor is not None:
            os.close(reservation_descriptor)
        os.close(parent_descriptor)


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
        _valid_anchor_scalars(
            policy.expected_commit_sha,
            policy.expected_tree_sha,
            policy.expected_parent_sha,
            policy.expected_base_sha,
            policy.expected_ancestry_digest_sha256,
            policy.expected_patch_receipt_sha256,
            policy.expected_patch_digest_sha256,
            policy.expected_patch_recipe_id,
            policy.expected_patch_recipe_version,
        )
    )


def _valid_source_anchors(anchors: object) -> bool:
    if type(anchors) is not SourceTrustAnchors:
        return False
    return _valid_anchor_scalars(
        anchors.expected_commit_sha,
        anchors.expected_tree_sha,
        anchors.expected_parent_sha,
        anchors.expected_base_sha,
        anchors.expected_ancestry_digest_sha256,
        anchors.expected_patch_receipt_sha256,
        anchors.expected_patch_digest_sha256,
        anchors.expected_patch_recipe_id,
        anchors.expected_patch_recipe_version,
    ) and _valid_sha256(anchors.expected_manifest_sha256)


def _valid_anchor_scalars(
    commit_sha: object,
    tree_sha: object,
    parent_sha: object,
    base_sha: object,
    ancestry_digest: object,
    patch_receipt_digest: object,
    patch_digest: object,
    recipe_id: object,
    recipe_version: object,
) -> bool:
    return (
        all(
            type(value) is str and _HEX40.fullmatch(value) is not None
            for value in (commit_sha, tree_sha, parent_sha, base_sha)
        )
        and _valid_sha256(ancestry_digest)
        and _valid_sha256(patch_receipt_digest)
        and _valid_sha256(patch_digest)
        and type(recipe_id) is str
        and _RECIPE_ID.fullmatch(recipe_id) is not None
        and type(recipe_version) is int
        and recipe_version > 0
    )


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _HEX64.fullmatch(value) is not None


def _validate_tree(
    tree_entries: object,
    *,
    allow_ordinary: bool = False,
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
        if classification == "OMITTED" and not allow_ordinary:
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
    if not _valid_policy(policy):
        return False
    return _validate_patch_receipt_fields(
        raw,
        policy.expected_commit_sha,
        policy.expected_tree_sha,
        policy.expected_parent_sha,
        policy.expected_base_sha,
        policy.expected_ancestry_digest_sha256,
        policy.expected_patch_receipt_sha256,
        policy.expected_patch_digest_sha256,
        policy.expected_patch_recipe_id,
        policy.expected_patch_recipe_version,
    )


def _valid_external_patch_receipt(anchors: SourceTrustAnchors, raw: object) -> bool:
    return _validate_patch_receipt_fields(
        raw,
        anchors.expected_commit_sha,
        anchors.expected_tree_sha,
        anchors.expected_parent_sha,
        anchors.expected_base_sha,
        anchors.expected_ancestry_digest_sha256,
        anchors.expected_patch_receipt_sha256,
        anchors.expected_patch_digest_sha256,
        anchors.expected_patch_recipe_id,
        anchors.expected_patch_recipe_version,
    )


def _validate_patch_receipt_fields(
    raw: object,
    commit_sha: str,
    tree_sha: str,
    parent_sha: str,
    base_sha: str,
    ancestry_digest: str,
    receipt_digest: str,
    patch_digest: str,
    recipe_id: str,
    recipe_version: int,
) -> bool:
    if type(raw) is not bytes or not 0 < len(raw) <= _MAX_RECEIPT_BYTES:
        return False
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), receipt_digest):
        return False
    decoded = _strict_json(raw)
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
        _candidate_matches(
            candidate, commit_sha, tree_sha, parent_sha, base_sha, ancestry_digest
        )
        and patch["algorithm"] == "sha256"
        and _valid_sha256(patch["digest_sha256"])
        and hmac.compare_digest(patch["digest_sha256"], patch_digest)
        and hmac.compare_digest(patch["recipe_id"], recipe_id)
        and patch["recipe_version"] == recipe_version
    )


def _strict_json(raw: bytes) -> object | None:
    try:
        return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None


def _no_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _candidate_matches(
    candidate: object,
    commit_sha: str,
    tree_sha: str,
    parent_sha: str,
    base_sha: str,
    ancestry_digest: str,
) -> bool:
    if type(candidate) is not dict or set(candidate) != {
        "commit_sha",
        "tree_sha",
        "parent_sha",
        "base_sha",
        "ancestry_digest_sha256",
    }:
        return False
    if not all(
        type(candidate[key]) is str and _HEX40.fullmatch(candidate[key]) is not None
        for key in ("commit_sha", "tree_sha", "parent_sha", "base_sha")
    ) or not _valid_sha256(candidate["ancestry_digest_sha256"]):
        return False
    return (
        hmac.compare_digest(candidate["commit_sha"], commit_sha)
        and hmac.compare_digest(candidate["tree_sha"], tree_sha)
        and hmac.compare_digest(candidate["parent_sha"], parent_sha)
        and hmac.compare_digest(candidate["base_sha"], base_sha)
        and hmac.compare_digest(candidate["ancestry_digest_sha256"], ancestry_digest)
    )


def _parse_dependency_manifest(
    anchors: SourceTrustAnchors, raw: object
) -> DependencyManifest:
    if type(raw) is not bytes or not 0 < len(raw) <= _MAX_MANIFEST_BYTES:
        raise ProjectionSourceError("MANIFEST_INVALID")
    if not hmac.compare_digest(
        hashlib.sha256(raw).hexdigest(), anchors.expected_manifest_sha256
    ):
        raise ProjectionSourceError("MANIFEST_ANCHOR_MISMATCH")
    decoded = _strict_json(raw)
    if type(decoded) is not dict or set(decoded) != {
        "schema",
        "candidate",
        "files",
        "omitted",
    }:
        raise ProjectionSourceError("MANIFEST_INVALID")
    if type(decoded["schema"]) is not str or decoded["schema"] != DEPENDENCY_MANIFEST_SCHEMA:
        raise ProjectionSourceError("MANIFEST_INVALID")
    if not _candidate_matches(
        decoded["candidate"],
        anchors.expected_commit_sha,
        anchors.expected_tree_sha,
        anchors.expected_parent_sha,
        anchors.expected_base_sha,
        anchors.expected_ancestry_digest_sha256,
    ):
        raise ProjectionSourceError("MANIFEST_ANCHOR_MISMATCH")
    files = decoded["files"]
    omitted = decoded["omitted"]
    if type(files) is not list or not files or type(omitted) is not list:
        raise ProjectionSourceError("MANIFEST_INVALID")
    parsed: list[ManifestFile] = []
    previous: str | None = None
    for raw_file in files:
        item = _parse_manifest_file(raw_file)
        if previous is not None and item.path <= previous:
            raise ProjectionSourceError("MANIFEST_INVALID")
        parsed.append(item)
        previous = item.path
    parsed_omitted: list[ManifestOmission] = []
    previous = None
    covered_paths = {item.path for item in parsed}
    for raw_omission in omitted:
        omission = _parse_manifest_omission(raw_omission)
        if (
            (previous is not None and omission.path <= previous)
            or omission.path in covered_paths
        ):
            raise ProjectionSourceError("MANIFEST_INVALID")
        parsed_omitted.append(omission)
        covered_paths.add(omission.path)
        previous = omission.path
    return DependencyManifest(files=tuple(parsed), omitted=tuple(parsed_omitted))


def _parse_manifest_file(raw_file: object) -> ManifestFile:
    if type(raw_file) is not dict or set(raw_file) != {
        "path",
        "object_id",
        "mode",
        "size",
        "sha256",
    }:
        raise ProjectionSourceError("MANIFEST_INVALID")
    path = raw_file["path"]
    object_id = raw_file["object_id"]
    mode = raw_file["mode"]
    size = raw_file["size"]
    digest = raw_file["sha256"]
    if (
        type(path) is not str
        or type(object_id) is not str
        or _HEX40.fullmatch(object_id) is None
        or type(mode) is not str
        or mode not in {"100644", "100755"}
        or type(size) is not int
        or size < 0
        or not _valid_sha256(digest)
    ):
        raise ProjectionSourceError("MANIFEST_INVALID")
    try:
        encoded = path.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        raise ProjectionSourceError("MANIFEST_INVALID") from None
    if _canonical_path(encoded) != path or classify_path(encoded) != "ELIGIBLE":
        raise ProjectionSourceError("MANIFEST_INVALID")
    return ManifestFile(path=path, object_id=object_id, mode=mode, size=size, sha256=digest)


def _parse_manifest_omission(raw_omission: object) -> ManifestOmission:
    if type(raw_omission) is not dict or set(raw_omission) != {
        "path",
        "object_id",
        "mode",
        "size",
    }:
        raise ProjectionSourceError("MANIFEST_INVALID")
    path = raw_omission["path"]
    object_id = raw_omission["object_id"]
    mode = raw_omission["mode"]
    size = raw_omission["size"]
    if (
        type(path) is not str
        or type(object_id) is not str
        or _HEX40.fullmatch(object_id) is None
        or type(mode) is not str
        or mode not in {"100644", "100755"}
        or type(size) is not int
        or size < 0
    ):
        raise ProjectionSourceError("MANIFEST_INVALID")
    try:
        encoded = path.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        raise ProjectionSourceError("MANIFEST_INVALID") from None
    if _canonical_path(encoded) != path or classify_path(encoded) not in {
        "ELIGIBLE",
        "OMITTED",
        "PROTECTED",
    }:
        raise ProjectionSourceError("MANIFEST_INVALID")
    return ManifestOmission(path=path, object_id=object_id, mode=mode, size=size)


def _facts_match_anchors(facts: object, anchors: SourceTrustAnchors) -> bool:
    if type(facts) is not RepositoryFacts:
        return False
    if not all(
        type(value) is str and _HEX40.fullmatch(value) is not None
        for value in (facts.commit_sha, facts.tree_sha, facts.parent_sha, facts.base_sha)
    ) or not _valid_sha256(facts.ancestry_digest_sha256):
        return False
    return (
        hmac.compare_digest(facts.commit_sha, anchors.expected_commit_sha)
        and hmac.compare_digest(facts.tree_sha, anchors.expected_tree_sha)
        and hmac.compare_digest(facts.parent_sha, anchors.expected_parent_sha)
        and hmac.compare_digest(facts.base_sha, anchors.expected_base_sha)
        and hmac.compare_digest(
            facts.ancestry_digest_sha256, anchors.expected_ancestry_digest_sha256
        )
    )


def _same_facts(first: object, second: object) -> bool:
    if type(first) is not RepositoryFacts or type(second) is not RepositoryFacts:
        return False
    return (
        hmac.compare_digest(first.commit_sha, second.commit_sha)
        and hmac.compare_digest(first.tree_sha, second.tree_sha)
        and hmac.compare_digest(first.parent_sha, second.parent_sha)
        and hmac.compare_digest(first.base_sha, second.base_sha)
        and hmac.compare_digest(first.ancestry_digest_sha256, second.ancestry_digest_sha256)
    )


def _validate_manifest_against_tree(
    manifest: DependencyManifest,
    entries_by_path: dict[str, TreeEntry],
    protected_ids: set[str],
) -> None:
    covered_paths: set[str] = set()
    for item in manifest.files:
        entry = entries_by_path.get(item.path)
        if entry is None or classify_path(entry.path) != "ELIGIBLE":
            raise ProjectionSourceError("MANIFEST_TREE_DRIFT")
        if entry.object_id in protected_ids:
            raise ProjectionSourceError("PROTECTED_OBJECT_ALIAS")
        if (
            not hmac.compare_digest(entry.object_id, item.object_id)
            or entry.mode != item.mode
            or entry.size != item.size
        ):
            raise ProjectionSourceError("MANIFEST_TREE_DRIFT")
        covered_paths.add(item.path)
    for omission in manifest.omitted:
        entry = entries_by_path.get(omission.path)
        if entry is None:
            raise ProjectionSourceError("MANIFEST_TREE_DRIFT")
        if (
            not hmac.compare_digest(entry.object_id, omission.object_id)
            or entry.mode != omission.mode
            or entry.size != omission.size
        ):
            raise ProjectionSourceError("MANIFEST_TREE_DRIFT")
        covered_paths.add(omission.path)
    if set(entries_by_path) != covered_paths:
        raise ProjectionSourceError("MANIFEST_TREE_DRIFT")


def _tree_metadata_digest(entries_by_path: dict[str, TreeEntry]) -> str:
    rows = [
        {
            "path": path,
            "object_id": entry.object_id,
            "kind": entry.kind,
            "mode": entry.mode,
            "size": entry.size,
        }
        for path, entry in entries_by_path.items()
    ]
    return hashlib.sha256(_canonical_json_bytes({"entries": rows, "version": 1})).hexdigest()


def _open_private_destination_parent(destination_parent: object) -> tuple[str, int]:
    if type(destination_parent) is not str or not os.path.isabs(destination_parent):
        raise ProjectionSourceError("DESTINATION_INVALID")
    normalized = os.path.abspath(destination_parent)
    if os.path.realpath(normalized) != normalized:
        raise ProjectionSourceError("DESTINATION_INVALID")
    try:
        descriptor = os.open(normalized, _directory_open_flags())
    except OSError:
        raise ProjectionSourceError("DESTINATION_INVALID") from None
    valid = False
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise ProjectionSourceError("DESTINATION_INVALID")
        valid = True
    finally:
        if not valid:
            os.close(descriptor)
    return normalized, descriptor


def _parent_path_matches_descriptor(parent: str, parent_descriptor: int) -> bool:
    try:
        current_descriptor = os.open(parent, _directory_open_flags())
    except OSError:
        return False
    try:
        current = os.fstat(current_descriptor)
        expected = os.fstat(parent_descriptor)
    except OSError:
        return False
    finally:
        os.close(current_descriptor)
    return current.st_dev == expected.st_dev and current.st_ino == expected.st_ino


def _reserve_publication(parent_descriptor: int, publication_name: str) -> int:
    try:
        os.mkdir(publication_name, 0o700, dir_fd=parent_descriptor)
    except FileExistsError:
        raise ProjectionSourceError("PUBLICATION_CONFLICT") from None
    return _open_reserved_private_directory(parent_descriptor, publication_name)


def _reserve_staging(parent_descriptor: int) -> tuple[str, int]:
    for _ in range(128):
        name = f".e4b-stage-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent_descriptor)
        except FileExistsError:
            continue
        return name, _open_reserved_private_directory(parent_descriptor, name)
    raise ProjectionSourceError("MATERIALIZATION_FAILED")


def _open_reserved_private_directory(parent_descriptor: int, name: str) -> int:
    descriptor: int | None = None
    valid = False
    try:
        descriptor = _open_private_child_directory(parent_descriptor, name)
        os.fchmod(descriptor, 0o700)
        _validate_private_directory_descriptor(descriptor)
        valid = True
        return descriptor
    finally:
        if not valid:
            if descriptor is not None:
                os.close(descriptor)
            # No trusted inode identity exists if opening or validation failed.
            # Retain the name rather than deleting a possibly replaced directory.


def _entry_exists(parent_descriptor: int, name: str) -> bool:
    try:
        os.lstat(name, dir_fd=parent_descriptor)
    except FileNotFoundError:
        return False
    except OSError:
        raise ProjectionSourceError("MATERIALIZATION_LINK_INVALID") from None
    return True


def _write_staged_file(root_descriptor: int, item: ManifestFile, blob: bytes) -> None:
    components = item.path.split("/")
    if not components or any(not component for component in components):
        raise ProjectionSourceError("MATERIALIZATION_PATH_INVALID")
    if type(root_descriptor) is not int:
        raise ProjectionSourceError("MATERIALIZATION_PATH_INVALID")
    _validate_private_directory_descriptor(root_descriptor)
    parent_descriptor = os.dup(root_descriptor)
    try:
        for component in components[:-1]:
            child_descriptor = _open_or_create_private_directory(parent_descriptor, component)
            os.close(parent_descriptor)
            parent_descriptor = child_descriptor
        _write_private_regular_file(
            parent_descriptor,
            components[-1],
            blob,
            _private_mode(item.mode),
            item.sha256,
        )
    finally:
        os.close(parent_descriptor)


def _directory_open_flags() -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise ProjectionSourceError("MATERIALIZATION_NOFOLLOW_UNAVAILABLE")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    return flags


def _open_private_child_directory(parent_descriptor: int, name: str) -> int:
    try:
        descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_descriptor)
    except OSError:
        raise ProjectionSourceError("MATERIALIZATION_LINK_INVALID") from None
    valid = False
    try:
        _validate_private_directory_descriptor(descriptor)
        valid = True
    finally:
        if not valid:
            os.close(descriptor)
    return descriptor


def _open_or_create_private_directory(parent_descriptor: int, component: str) -> int:
    try:
        os.mkdir(component, 0o700, dir_fd=parent_descriptor)
    except FileExistsError:
        pass
    descriptor = _open_private_child_directory(parent_descriptor, component)
    valid = False
    try:
        os.fchmod(descriptor, 0o700)
        _validate_private_directory_descriptor(descriptor)
        valid = True
    finally:
        if not valid:
            os.close(descriptor)
    return descriptor


def _validate_private_directory_descriptor(descriptor: int) -> None:
    try:
        info = os.fstat(descriptor)
    except OSError:
        raise ProjectionSourceError("MATERIALIZATION_LINK_INVALID") from None
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ProjectionSourceError("MATERIALIZATION_LINK_INVALID")


def _directory_identity(descriptor: int) -> tuple[int, int]:
    try:
        info = os.fstat(descriptor)
    except OSError:
        raise ProjectionSourceError("MATERIALIZATION_LINK_INVALID") from None
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ProjectionSourceError("MATERIALIZATION_LINK_INVALID")
    return info.st_dev, info.st_ino


def _write_private_regular_file(
    parent_descriptor: int,
    name: str,
    blob: bytes,
    private_mode: int,
    expected_digest: str,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, private_mode, dir_fd=parent_descriptor)
    except OSError:
        raise ProjectionSourceError("MATERIALIZATION_LINK_INVALID") from None
    try:
        os.fchmod(descriptor, private_mode)
        offset = 0
        while offset < len(blob):
            written = os.write(descriptor, blob[offset:])
            if written <= 0:
                raise OSError("short write")
            offset += written
    finally:
        os.close(descriptor)
    digest = _hash_private_regular_at(parent_descriptor, name, private_mode)
    if not hmac.compare_digest(digest, expected_digest):
        raise ProjectionSourceError("MATERIALIZATION_HASH_MISMATCH")


def _read_private_regular_at(parent_descriptor: int, name: str, expected_mode: int) -> bytes:
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_descriptor
        )
    except OSError:
        raise ProjectionSourceError("MATERIALIZATION_LINK_INVALID") from None
    chunks: list[bytes] = []
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != expected_mode
        ):
            raise ProjectionSourceError("MATERIALIZATION_LINK_INVALID")
        while True:
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_nlink != after.st_nlink
        or stat.S_IMODE(after.st_mode) != expected_mode
        or not stat.S_ISREG(after.st_mode)
    ):
        raise ProjectionSourceError("MATERIALIZATION_TOCTOU")
    return b"".join(chunks)


def _hash_private_regular_at(parent_descriptor: int, name: str, expected_mode: int) -> str:
    return hashlib.sha256(
        _read_private_regular_at(parent_descriptor, name, expected_mode)
    ).hexdigest()


def _expected_private_directories(manifest: tuple[ManifestFile, ...]) -> set[str]:
    directories = {""}
    for item in manifest:
        current: list[str] = []
        for component in item.path.split("/")[:-1]:
            current.append(component)
            directories.add("/".join(current))
    return directories


def _verify_private_root(root_descriptor: int, manifest: tuple[ManifestFile, ...]) -> None:
    if type(root_descriptor) is not int:
        raise ProjectionSourceError("MATERIALIZATION_PATH_INVALID")
    expected = {item.path: item for item in manifest}
    expected_directories = _expected_private_directories(manifest)
    actual: set[str] = set()
    actual_directories: set[str] = set()
    _verify_private_directory(
        root_descriptor,
        "",
        expected,
        expected_directories,
        actual,
        actual_directories,
    )
    if actual_directories != expected_directories:
        raise ProjectionSourceError("MATERIALIZATION_DIRECTORYSET_MISMATCH")
    if actual != set(expected):
        raise ProjectionSourceError("MATERIALIZATION_FILESET_MISMATCH")


def _verify_private_directory(
    directory_descriptor: int,
    relative_directory: str,
    expected: dict[str, ManifestFile],
    expected_directories: set[str],
    actual: set[str],
    actual_directories: set[str],
) -> None:
    if relative_directory not in expected_directories:
        raise ProjectionSourceError("MATERIALIZATION_EXTRA_DIRECTORY")
    _validate_private_directory_descriptor(directory_descriptor)
    actual_directories.add(relative_directory)
    try:
        names = os.listdir(directory_descriptor)
    except OSError:
        raise ProjectionSourceError("MATERIALIZATION_LINK_INVALID") from None
    for name in names:
        relative = name if not relative_directory else f"{relative_directory}/{name}"
        try:
            info = os.lstat(name, dir_fd=directory_descriptor)
        except OSError:
            raise ProjectionSourceError("MATERIALIZATION_LINK_INVALID") from None
        if stat.S_ISLNK(info.st_mode):
            raise ProjectionSourceError("MATERIALIZATION_LINK_INVALID")
        if stat.S_ISDIR(info.st_mode):
            if relative not in expected_directories:
                raise ProjectionSourceError("MATERIALIZATION_EXTRA_DIRECTORY")
            child_descriptor = _open_private_child_directory(directory_descriptor, name)
            try:
                _verify_private_directory(
                    child_descriptor,
                    relative,
                    expected,
                    expected_directories,
                    actual,
                    actual_directories,
                )
            finally:
                os.close(child_descriptor)
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ProjectionSourceError("MATERIALIZATION_LINK_INVALID")
        item = expected.get(relative)
        if item is None:
            raise ProjectionSourceError("MATERIALIZATION_EXTRA_FILE")
        digest = _hash_private_regular_at(
            directory_descriptor, name, _private_mode(item.mode)
        )
        if not hmac.compare_digest(digest, item.sha256):
            raise ProjectionSourceError("MATERIALIZATION_HASH_MISMATCH")
        actual.add(relative)


def _private_mode(git_mode: str) -> int:
    if git_mode == "100644":
        return 0o600
    if git_mode == "100755":
        return 0o700
    raise ProjectionSourceError("TREE_METADATA_INVALID")


def _create_projection_root_handle(
    root_descriptor: int, files: tuple[ManifestFile, ...]
) -> ProjectionRootHandle:
    return ProjectionRootHandle(root_descriptor, files)


def _manifest_file_for_handle(
    files: tuple[ManifestFile, ...], relative_path: object
) -> ManifestFile:
    if type(relative_path) is not str:
        raise ProjectionSourceError("PROJECTION_HANDLE_PATH_INVALID")
    try:
        encoded = relative_path.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        raise ProjectionSourceError("PROJECTION_HANDLE_PATH_INVALID") from None
    if _canonical_path(encoded) != relative_path:
        raise ProjectionSourceError("PROJECTION_HANDLE_PATH_INVALID")
    for item in files:
        if item.path == relative_path:
            return item
    raise ProjectionSourceError("PROJECTION_HANDLE_PATH_INVALID")


def _read_projected_file(root_descriptor: int, item: ManifestFile) -> bytes:
    if type(root_descriptor) is not int or type(item) is not ManifestFile:
        raise ProjectionSourceError("PROJECTION_HANDLE_INVALID")
    components = item.path.split("/")
    if not components or any(not component for component in components):
        raise ProjectionSourceError("PROJECTION_HANDLE_PATH_INVALID")
    try:
        parent_descriptor = os.dup(root_descriptor)
    except OSError:
        raise ProjectionSourceError("PROJECTION_HANDLE_CLOSED") from None
    try:
        _validate_private_directory_descriptor(parent_descriptor)
        for component in components[:-1]:
            child_descriptor = _open_private_child_directory(parent_descriptor, component)
            os.close(parent_descriptor)
            parent_descriptor = child_descriptor
        content = _read_private_regular_at(
            parent_descriptor, components[-1], _private_mode(item.mode)
        )
    finally:
        _close_projection_handle_descriptor(parent_descriptor)
    if len(content) != item.size or not hmac.compare_digest(
        hashlib.sha256(content).hexdigest(), item.sha256
    ):
        raise ProjectionSourceError("PROJECTION_HANDLE_INTEGRITY_INVALID")
    return content


def _root_digest(manifest: tuple[ManifestFile, ...]) -> str:
    payload = {
        "files": [
            {
                "path": item.path,
                "sha256": item.sha256,
                "mode": item.mode,
                "size": item.size,
            }
            for item in manifest
        ],
        "version": 1,
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _cleanup_attempt(
    parent_descriptor: int,
    staging_name: str | None,
    staging_identity: tuple[int, int] | None,
    reservation_name: str | None,
    reservation_identity: tuple[int, int] | None,
) -> None:
    if staging_name is not None:
        _remove_owned_tree_at(parent_descriptor, staging_name, staging_identity)
    if reservation_name is not None:
        _remove_owned_tree_at(parent_descriptor, reservation_name, reservation_identity)


def _remove_owned_tree_at(
    parent_descriptor: int,
    name: str,
    expected_identity: tuple[int, int] | None = None,
) -> None:
    try:
        descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_descriptor)
    except OSError:
        return
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            return
        if expected_identity is not None and (info.st_dev, info.st_ino) != expected_identity:
            return
        _remove_owned_children(descriptor)
        if expected_identity is not None:
            # A directory cannot be unlinked by descriptor with portable stdlib APIs.
            # Retain the empty attempt shell instead of racing on a mutable name.
            return
        try:
            current = os.lstat(name, dir_fd=parent_descriptor)
        except OSError:
            return
        if current.st_dev != info.st_dev or current.st_ino != info.st_ino:
            return
        try:
            os.rmdir(name, dir_fd=parent_descriptor)
        except OSError:
            return
    finally:
        os.close(descriptor)


def _remove_owned_children(directory_descriptor: int) -> None:
    try:
        names = os.listdir(directory_descriptor)
    except OSError:
        return
    for name in names:
        try:
            info = os.lstat(name, dir_fd=directory_descriptor)
        except OSError:
            continue
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            _remove_owned_tree_at(directory_descriptor, name)
            continue
        try:
            os.unlink(name, dir_fd=directory_descriptor)
        except OSError:
            continue


def _valid_final_receipt(receipt: object) -> bool:
    if type(receipt) is not FinalProjectionReceipt:
        return False
    return (
        type(receipt.schema) is str
        and receipt.schema == FINAL_RECEIPT_SCHEMA
        and type(receipt.status) is str
        and receipt.status == "FINALIZED_SOURCE_ONLY"
        and type(receipt.operational_authorization) is bool
        and receipt.operational_authorization is False
        and all(
            type(value) is str and _HEX40.fullmatch(value) is not None
            for value in (
                receipt.commit_sha,
                receipt.tree_sha,
                receipt.parent_sha,
                receipt.base_sha,
            )
        )
        and all(
            _valid_sha256(value)
            for value in (
                receipt.ancestry_digest_sha256,
                receipt.patch_receipt_sha256,
                receipt.patch_digest_sha256,
                receipt.manifest_sha256,
                receipt.root_digest_sha256,
                receipt.protected_object_commitment_sha256,
            )
        )
        and type(receipt.file_count) is int
        and receipt.file_count > 0
    )


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
