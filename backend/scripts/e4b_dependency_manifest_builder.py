"""Pure E4b closed-manifest construction relative to declared synthetic inputs."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re


DEPENDENCY_MANIFEST_SCHEMA = "e4b-operational-dependency-manifest-v1"
MAX_MANIFEST_BYTES = 1_048_576
# The only count quota bounds work before entry traversal. It is conservative
# relative to the parser's 1 MiB envelope; exact serialized bytes remain
# authoritative, so canonical path length is not capped here.
MAX_INVENTORY_ENTRIES = 4_096
# Declared file sizes stay within the signed 64-bit physical-file range before
# any decimal conversion for canonical JSON.
_MAX_FILE_SIZE = (1 << 63) - 1
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
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
_ERROR_CODES = frozenset(
    {
        "CANDIDATE_INVALID",
        "CONFLICTING_IDENTITY",
        "COVERAGE_EXTRA",
        "COVERAGE_MISSING",
        "DIGEST_CONFLICT",
        "DUPLICATE_IDENTITY",
        "DYNAMIC",
        "EMPTY_SELECTION",
        "INVENTORY_ABSENT",
        "INVENTORY_INVALID",
        "INVENTORY_LIMIT",
        "MANIFEST_DRIFT",
        "MANIFEST_EMPTY",
        "ORDER_INVALID",
        "PROTECTED_OBJECT_ALIAS",
        "PROVENANCE_DRIFT",
        "RESOLUTION_INVALID",
        "RESULT_INVALID",
        "SELECTION_DUPLICATE",
        "SELECTION_INVALID",
        "SERIALIZATION_LIMIT",
        "UNKNOWN",
    }
)


class ClosedManifestError(RuntimeError):
    """Finite error categories for a source-only, pure boundary."""

    def __init__(self, code: str) -> None:
        self.code = code if code in _ERROR_CODES else "RESULT_INVALID"
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    commit_sha: str
    tree_sha: str
    parent_sha: str
    base_sha: str
    ancestry_digest_sha256: str


@dataclass(frozen=True, slots=True)
class InventoryMetadata:
    """Declared inventory metadata. It deliberately has no content digest."""

    path: str
    object_id: str
    mode: str
    size: int


@dataclass(frozen=True, slots=True)
class DependencyInventory:
    entries: tuple[InventoryMetadata, ...]


@dataclass(frozen=True, slots=True)
class ResolvedSelection:
    """Synthetic selected path plus its declared digest, never used for omitted paths."""

    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ManifestResolution:
    status: str
    selected: tuple[ResolvedSelection, ...]


@dataclass(frozen=True, slots=True)
class EmptyManifestResult:
    candidate: CandidateIdentity
    status: str = "EMPTY"


@dataclass(frozen=True, slots=True)
class ResolvedManifestResult:
    candidate: CandidateIdentity
    inventory: tuple[InventoryMetadata, ...]
    selected: tuple[ResolvedSelection, ...]
    status: str = "RESOLVED"


def build_closed_manifest(
    candidate: CandidateIdentity,
    inventory: DependencyInventory | None,
    resolution: ManifestResolution,
) -> EmptyManifestResult | ResolvedManifestResult:
    """Build a partition closed only relative to declared inventory and selection."""

    _validate_candidate(candidate)
    entries, classifications = _normalize_inventory(inventory)
    selected = _normalize_resolution(resolution, len(entries))
    if not entries:
        if selected:
            raise ClosedManifestError("SELECTION_INVALID")
        return EmptyManifestResult(candidate=candidate)
    if not selected:
        raise ClosedManifestError("EMPTY_SELECTION")
    _validate_selected_partition(entries, classifications, selected, "SELECTION_INVALID")
    return ResolvedManifestResult(candidate=candidate, inventory=entries, selected=selected)


def serialize_closed_manifest(result: ResolvedManifestResult) -> bytes:
    """Serialize a valid nonempty result into canonical parser-shaped JSON bytes."""

    entries, selected, omitted = _validate_resolved_layout(result)
    entries_by_path = {entry.path: entry for entry in entries}
    if _serialized_manifest_size(result.candidate, entries_by_path, selected, omitted) > MAX_MANIFEST_BYTES:
        raise ClosedManifestError("SERIALIZATION_LIMIT")
    payload = {
        "schema": DEPENDENCY_MANIFEST_SCHEMA,
        "candidate": _candidate_payload(result.candidate),
        "files": [
            {
                "path": selection.path,
                "object_id": entries_by_path[selection.path].object_id,
                "mode": entries_by_path[selection.path].mode,
                "size": entries_by_path[selection.path].size,
                "sha256": selection.sha256,
            }
            for selection in selected
        ],
        "omitted": [
            {
                "path": entry.path,
                "object_id": entry.object_id,
                "mode": entry.mode,
                "size": entry.size,
            }
            for entry in omitted
        ],
    }
    try:
        raw = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii") + b"\n"
    except (OverflowError, TypeError, ValueError):
        raise ClosedManifestError("SERIALIZATION_LIMIT") from None
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ClosedManifestError("SERIALIZATION_LIMIT")
    return raw


def verify_closed_manifest(
    result: ResolvedManifestResult,
    candidate: CandidateIdentity,
    inventory: DependencyInventory | None,
    resolution: ManifestResolution,
) -> None:
    """Recheck declared relative closure, provenance, order and synthetic drift."""

    actual_entries, actual_selected, _omitted = _validate_resolved_layout(result)
    _validate_candidate(candidate)
    expected = build_closed_manifest(candidate, inventory, resolution)
    if type(expected) is EmptyManifestResult:
        raise ClosedManifestError("MANIFEST_EMPTY")
    if result.candidate != candidate:
        raise ClosedManifestError("PROVENANCE_DRIFT")
    expected_paths = {entry.path for entry in expected.inventory}
    actual_paths = {entry.path for entry in actual_entries}
    if expected_paths - actual_paths:
        raise ClosedManifestError("COVERAGE_MISSING")
    if actual_paths - expected_paths:
        raise ClosedManifestError("COVERAGE_EXTRA")
    if actual_entries != expected.inventory or actual_selected != expected.selected:
        raise ClosedManifestError("MANIFEST_DRIFT")


def _validate_candidate(candidate: object) -> None:
    if type(candidate) is not CandidateIdentity:
        raise ClosedManifestError("CANDIDATE_INVALID")
    values = (
        candidate.commit_sha,
        candidate.tree_sha,
        candidate.parent_sha,
        candidate.base_sha,
    )
    if not all(type(value) is str and _HEX40.fullmatch(value) is not None for value in values):
        raise ClosedManifestError("CANDIDATE_INVALID")
    if (
        type(candidate.ancestry_digest_sha256) is not str
        or _HEX64.fullmatch(candidate.ancestry_digest_sha256) is None
    ):
        raise ClosedManifestError("CANDIDATE_INVALID")


def _normalize_inventory(
    inventory: DependencyInventory | None,
) -> tuple[tuple[InventoryMetadata, ...], dict[str, str]]:
    if inventory is None:
        raise ClosedManifestError("INVENTORY_ABSENT")
    if type(inventory) is not DependencyInventory or type(inventory.entries) is not tuple:
        raise ClosedManifestError("INVENTORY_INVALID")
    if len(inventory.entries) > MAX_INVENTORY_ENTRIES:
        raise ClosedManifestError("INVENTORY_LIMIT")

    by_path: dict[str, InventoryMetadata] = {}
    classifications: dict[str, str] = {}
    casefold_paths: dict[str, str] = {}
    for entry in inventory.entries:
        classification = _validate_inventory_metadata(entry)
        previous = by_path.get(entry.path)
        if previous is not None:
            if previous == entry:
                raise ClosedManifestError("DUPLICATE_IDENTITY")
            raise ClosedManifestError("CONFLICTING_IDENTITY")
        folded = entry.path.casefold()
        previous_path = casefold_paths.get(folded)
        if previous_path is not None and previous_path != entry.path:
            raise ClosedManifestError("CONFLICTING_IDENTITY")
        by_path[entry.path] = entry
        classifications[entry.path] = classification
        casefold_paths[folded] = entry.path

    entries = tuple(by_path[path] for path in sorted(by_path))
    for entry in entries:
        classification = classifications[entry.path]
        if classification == "UNKNOWN":
            raise ClosedManifestError("UNKNOWN")
        if classification == "INVALID":
            raise ClosedManifestError("INVENTORY_INVALID")
    return entries, classifications


def _normalize_resolution(
    resolution: object,
    inventory_count: int,
) -> tuple[ResolvedSelection, ...]:
    if type(resolution) is not ManifestResolution or type(resolution.status) is not str:
        raise ClosedManifestError("RESOLUTION_INVALID")
    if resolution.status == "UNKNOWN":
        raise ClosedManifestError("UNKNOWN")
    if resolution.status == "DYNAMIC":
        raise ClosedManifestError("DYNAMIC")
    if resolution.status != "RESOLVED" or type(resolution.selected) is not tuple:
        raise ClosedManifestError("RESOLUTION_INVALID")
    if len(resolution.selected) > inventory_count:
        raise ClosedManifestError("SELECTION_INVALID")
    by_path: dict[str, ResolvedSelection] = {}
    for selection in resolution.selected:
        _validate_selection(selection)
        previous = by_path.get(selection.path)
        if previous is not None:
            if previous.sha256 == selection.sha256:
                raise ClosedManifestError("SELECTION_DUPLICATE")
            raise ClosedManifestError("DIGEST_CONFLICT")
        by_path[selection.path] = selection
    return tuple(by_path[path] for path in sorted(by_path))


def _validate_inventory_metadata(entry: object) -> str:
    if type(entry) is not InventoryMetadata:
        raise ClosedManifestError("INVENTORY_INVALID")
    if (
        type(entry.path) is not str
        or type(entry.object_id) is not str
        or _HEX40.fullmatch(entry.object_id) is None
        or type(entry.mode) is not str
        or entry.mode not in {"100644", "100755"}
        or type(entry.size) is not int
        or entry.size < 0
        or entry.size > _MAX_FILE_SIZE
    ):
        raise ClosedManifestError("INVENTORY_INVALID")
    return _classify_path(entry.path)


def _validate_selection(selection: object) -> None:
    if (
        type(selection) is not ResolvedSelection
        or _canonical_path(getattr(selection, "path", None)) is None
        or type(selection.sha256) is not str
        or _HEX64.fullmatch(selection.sha256) is None
    ):
        raise ClosedManifestError("SELECTION_INVALID")


def _validate_resolved_layout(
    result: object,
) -> tuple[tuple[InventoryMetadata, ...], tuple[ResolvedSelection, ...], tuple[InventoryMetadata, ...]]:
    if type(result) is EmptyManifestResult:
        raise ClosedManifestError("MANIFEST_EMPTY")
    if type(result) is not ResolvedManifestResult:
        raise ClosedManifestError("RESULT_INVALID")
    _validate_candidate(result.candidate)
    if (
        type(result.status) is not str
        or result.status != "RESOLVED"
        or type(result.inventory) is not tuple
        or type(result.selected) is not tuple
    ):
        raise ClosedManifestError("RESULT_INVALID")
    entries, classifications = _normalize_inventory(DependencyInventory(result.inventory))
    selected = _normalize_resolution(
        ManifestResolution(status="RESOLVED", selected=result.selected), len(entries)
    )
    if entries != result.inventory or selected != result.selected:
        raise ClosedManifestError("ORDER_INVALID")
    if not entries or not selected:
        raise ClosedManifestError("MANIFEST_EMPTY")
    omitted = _validate_selected_partition(entries, classifications, selected, "RESULT_INVALID")
    return entries, selected, omitted


def _validate_selected_partition(
    entries: tuple[InventoryMetadata, ...],
    classifications: dict[str, str],
    selected: tuple[ResolvedSelection, ...],
    invalid_code: str,
) -> tuple[InventoryMetadata, ...]:
    entries_by_path = {entry.path: entry for entry in entries}
    selected_paths = {selection.path for selection in selected}
    if len(selected_paths) != len(selected) or not selected:
        raise ClosedManifestError(invalid_code)
    if any(path not in entries_by_path for path in selected_paths):
        raise ClosedManifestError(invalid_code)
    if any(classifications[path] != "ELIGIBLE" for path in selected_paths):
        raise ClosedManifestError(invalid_code)
    protected_ids = {
        entry.object_id
        for entry in entries
        if classifications[entry.path] == "PROTECTED"
    }
    if any(entries_by_path[path].object_id in protected_ids for path in selected_paths):
        raise ClosedManifestError("PROTECTED_OBJECT_ALIAS")
    return tuple(entry for entry in entries if entry.path not in selected_paths)


def _candidate_payload(candidate: CandidateIdentity) -> dict[str, str]:
    return {
        "commit_sha": candidate.commit_sha,
        "tree_sha": candidate.tree_sha,
        "parent_sha": candidate.parent_sha,
        "base_sha": candidate.base_sha,
        "ancestry_digest_sha256": candidate.ancestry_digest_sha256,
    }


def _serialized_manifest_size(
    candidate: CandidateIdentity,
    entries_by_path: dict[str, InventoryMetadata],
    selected: tuple[ResolvedSelection, ...],
    omitted: tuple[InventoryMetadata, ...],
) -> int:
    candidate_size = _json_object_size(
        (
            ("ancestry_digest_sha256", _json_string_size(candidate.ancestry_digest_sha256)),
            ("base_sha", _json_string_size(candidate.base_sha)),
            ("commit_sha", _json_string_size(candidate.commit_sha)),
            ("parent_sha", _json_string_size(candidate.parent_sha)),
            ("tree_sha", _json_string_size(candidate.tree_sha)),
        )
    )
    files_size = _json_array_size(
        tuple(_selected_payload_size(entries_by_path[selection.path], selection) for selection in selected)
    )
    omitted_size = _json_array_size(tuple(_omitted_payload_size(entry) for entry in omitted))
    return _json_object_size(
        (
            ("candidate", candidate_size),
            ("files", files_size),
            ("omitted", omitted_size),
            ("schema", _json_string_size(DEPENDENCY_MANIFEST_SCHEMA)),
        )
    ) + 1


def _selected_payload_size(entry: InventoryMetadata, selection: ResolvedSelection) -> int:
    return _json_object_size(
        (
            ("mode", _json_string_size(entry.mode)),
            ("object_id", _json_string_size(entry.object_id)),
            ("path", _json_string_size(selection.path)),
            ("sha256", _json_string_size(selection.sha256)),
            ("size", _json_integer_size(entry.size)),
        )
    )


def _omitted_payload_size(entry: InventoryMetadata) -> int:
    return _json_object_size(
        (
            ("mode", _json_string_size(entry.mode)),
            ("object_id", _json_string_size(entry.object_id)),
            ("path", _json_string_size(entry.path)),
            ("size", _json_integer_size(entry.size)),
        )
    )


def _json_object_size(items: tuple[tuple[str, int], ...]) -> int:
    return 2 + max(0, len(items) - 1) + sum(
        _json_string_size(key) + 1 + value_size for key, value_size in items
    )


def _json_array_size(item_sizes: tuple[int, ...]) -> int:
    return 2 + max(0, len(item_sizes) - 1) + sum(item_sizes)


def _json_string_size(value: str) -> int:
    return len(value) + 2


def _json_integer_size(value: int) -> int:
    return len(str(value))


def _classify_path(path: object) -> str:
    canonical = _canonical_path(path)
    if canonical is None:
        return "INVALID"
    folded = canonical.casefold()
    parts = folded.split("/")
    basename = parts[-1]
    if basename == ".env" or basename.startswith(".env."):
        return "PROTECTED"
    if any(part in _PROTECTED_DIRECTORIES for part in parts):
        return "PROTECTED"
    if basename.startswith(("id_rsa", "id_ed25519")):
        return "PROTECTED"
    if basename.endswith(_PROTECTED_SUFFIXES):
        return "PROTECTED"
    if folded.startswith("backend/scripts/clerk_"):
        return "PROTECTED"
    if folded.startswith("backend/scripts/target_users") and basename.endswith(".json"):
        return "PROTECTED"
    if folded == "backend/scripts/migrate_clerk_production.py":
        return "PROTECTED"
    if canonical in _ELIGIBLE_EXACT or canonical.startswith(_ELIGIBLE_PREFIXES):
        return "ELIGIBLE"
    return "UNKNOWN"


def _canonical_path(path: object) -> str | None:
    if type(path) is not str:
        return None
    try:
        encoded = path.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        return None
    if not encoded or b"\x00" in encoded or b"\\" in encoded:
        return None
    parts = path.split("/")
    if any(
        not part
        or part in {".", ".."}
        or _COMPONENT.fullmatch(part.encode("ascii")) is None
        for part in parts
    ):
        return None
    return path
