"""Pure, inert parsing boundary for synthetic E4b external trust anchors.

This module parses only caller-provided bytes. It neither locates nor verifies
an operational source. A future reviewed snapshot authority may supply a
``VerifiedSourceTrustAnchors`` capability; this slice intentionally provides
no runtime construction, adoption, conversion, or deserialization route.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re


ANCHOR_BUNDLE_SCHEMA = "e4b-external-trust-anchors-v1"
ANCHOR_BUNDLE_VERSION = 1
ANCHOR_BUNDLE_ALGORITHM = "sha256"
SUPPORTED_PATCH_RECIPE_ID = "e4b-patch-replay"
SUPPORTED_PATCH_RECIPE_VERSION = 1
MAX_ANCHOR_BUNDLE_BYTES = 1_024

_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ANCHOR_FIELDS = (
    "expected_commit_sha",
    "expected_tree_sha",
    "expected_parent_sha",
    "expected_base_sha",
    "expected_ancestry_digest_sha256",
    "expected_patch_receipt_sha256",
    "expected_patch_digest_sha256",
    "expected_patch_recipe_id",
    "expected_patch_recipe_version",
    "expected_manifest_sha256",
)
_BUNDLE_FIELDS = ("schema", "version", "algorithm", *_ANCHOR_FIELDS)
_OBJECT_ID_FIELDS = (
    "expected_commit_sha",
    "expected_tree_sha",
    "expected_parent_sha",
    "expected_base_sha",
)
_DIGEST_FIELDS = (
    "expected_ancestry_digest_sha256",
    "expected_patch_receipt_sha256",
    "expected_patch_digest_sha256",
    "expected_manifest_sha256",
)


class ExternalAnchorErrorCode(str, Enum):
    ABSENT = "ANCHOR_ABSENT"
    MALFORMED = "ANCHOR_MALFORMED"
    NON_CANONICAL = "ANCHOR_NON_CANONICAL"
    FIELD_MISSING = "ANCHOR_FIELD_MISSING"
    FIELD_UNKNOWN = "ANCHOR_FIELD_UNKNOWN"
    FIELD_DUPLICATE = "ANCHOR_FIELD_DUPLICATE"
    DIGEST_MALFORMED = "ANCHOR_DIGEST_MALFORMED"
    ALGORITHM_UNSUPPORTED = "ANCHOR_ALGORITHM_UNSUPPORTED"
    SCHEMA_UNSUPPORTED = "ANCHOR_SCHEMA_UNSUPPORTED"
    VERSION_UNSUPPORTED = "ANCHOR_VERSION_UNSUPPORTED"
    RECIPE_UNSUPPORTED = "ANCHOR_RECIPE_UNSUPPORTED"
    RECIPE_VERSION_UNSUPPORTED = "ANCHOR_RECIPE_VERSION_UNSUPPORTED"
    LIMIT_EXCEEDED = "ANCHOR_LIMIT_EXCEEDED"
    VERIFIED_UNAVAILABLE = "VERIFIED_ANCHORS_UNAVAILABLE"


class ExternalTrustAnchorError(RuntimeError):
    """Closed, content-free error surface for anchor parsing and capabilities."""

    def __init__(self, code: ExternalAnchorErrorCode) -> None:
        self.code = (
            code.value
            if type(code) is ExternalAnchorErrorCode
            else ExternalAnchorErrorCode.MALFORMED.value
        )
        super().__init__(self.code)


class _DuplicateFieldError(ValueError):
    pass


class _MalformedAnchorBundle(ValueError):
    pass


@dataclass(frozen=True)
class ParsedSourceTrustAnchors:
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


class VerifiedSourceTrustAnchors(tuple):
    """Opaque capability reserved for a future immutable snapshot supplier."""

    __slots__ = ()

    def __new__(cls, *_args: object, **_kwargs: object):
        _raise(ExternalAnchorErrorCode.VERIFIED_UNAVAILABLE)

    expected_commit_sha = property(lambda self: self[0])
    expected_tree_sha = property(lambda self: self[1])
    expected_parent_sha = property(lambda self: self[2])
    expected_base_sha = property(lambda self: self[3])
    expected_ancestry_digest_sha256 = property(lambda self: self[4])
    expected_patch_receipt_sha256 = property(lambda self: self[5])
    expected_patch_digest_sha256 = property(lambda self: self[6])
    expected_patch_recipe_id = property(lambda self: self[7])
    expected_patch_recipe_version = property(lambda self: self[8])
    expected_manifest_sha256 = property(lambda self: self[9])

    def __copy__(self):
        _raise(ExternalAnchorErrorCode.VERIFIED_UNAVAILABLE)

    def __deepcopy__(self, _memo: object):
        _raise(ExternalAnchorErrorCode.VERIFIED_UNAVAILABLE)

    def __reduce__(self):
        _raise(ExternalAnchorErrorCode.VERIFIED_UNAVAILABLE)

    def __reduce_ex__(self, _protocol: object):
        _raise(ExternalAnchorErrorCode.VERIFIED_UNAVAILABLE)


def parse_source_trust_anchor_bundle(raw: bytes | None) -> ParsedSourceTrustAnchors:
    """Parse exactly one canonical synthetic bundle from in-memory bytes."""

    if raw is None:
        _raise(ExternalAnchorErrorCode.ABSENT)
    if type(raw) is not bytes or not raw:
        _raise(ExternalAnchorErrorCode.MALFORMED)
    if len(raw) > MAX_ANCHOR_BUNDLE_BYTES:
        _raise(ExternalAnchorErrorCode.LIMIT_EXCEEDED)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _raise(ExternalAnchorErrorCode.MALFORMED)
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_fields,
            parse_constant=_reject_non_json_constant,
        )
    except _DuplicateFieldError:
        _raise(ExternalAnchorErrorCode.FIELD_DUPLICATE)
    except (_MalformedAnchorBundle, json.JSONDecodeError, RecursionError):
        _raise(ExternalAnchorErrorCode.MALFORMED)
    if type(decoded) is not dict:
        _raise(ExternalAnchorErrorCode.MALFORMED)
    _validate_bundle_fields(decoded)
    parsed = ParsedSourceTrustAnchors(**{name: decoded[name] for name in _ANCHOR_FIELDS})
    if raw != serialize_source_trust_anchor_bundle(parsed):
        _raise(ExternalAnchorErrorCode.NON_CANONICAL)
    return parsed


def serialize_source_trust_anchor_bundle(parsed: ParsedSourceTrustAnchors) -> bytes:
    """Serialize a parsed bundle with exact field order and one final LF."""

    if type(parsed) is not ParsedSourceTrustAnchors:
        _raise(ExternalAnchorErrorCode.MALFORMED)
    values = _anchor_values(parsed)
    _validate_anchor_values(values)
    payload = {
        "schema": ANCHOR_BUNDLE_SCHEMA,
        "version": ANCHOR_BUNDLE_VERSION,
        "algorithm": ANCHOR_BUNDLE_ALGORITHM,
        **{name: value for name, value in zip(_ANCHOR_FIELDS, values, strict=True)},
    }
    raw = (
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        .encode("ascii")
        + b"\n"
    )
    if len(raw) > MAX_ANCHOR_BUNDLE_BYTES:
        _raise(ExternalAnchorErrorCode.LIMIT_EXCEEDED)
    return raw


def is_valid_verified_source_trust_anchors(value: object) -> bool:
    """Lexically validate a capability supplied by a future trusted authority."""

    if type(value) is not VerifiedSourceTrustAnchors:
        return False
    if len(value) != len(_ANCHOR_FIELDS):
        return False
    try:
        _validate_anchor_values(_anchor_values(value))
    except (AttributeError, ExternalTrustAnchorError):
        return False
    return True


def _raise(code: ExternalAnchorErrorCode) -> None:
    raise ExternalTrustAnchorError(code)


def _reject_duplicate_fields(pairs: list[tuple[object, object]]) -> dict[object, object]:
    result: dict[object, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateFieldError()
        result[key] = value
    return result


def _reject_non_json_constant(_value: str) -> None:
    raise _MalformedAnchorBundle()


def _validate_bundle_fields(bundle: dict[object, object]) -> None:
    keys = set(bundle)
    expected = set(_BUNDLE_FIELDS)
    if keys - expected:
        _raise(ExternalAnchorErrorCode.FIELD_UNKNOWN)
    if expected - keys:
        _raise(ExternalAnchorErrorCode.FIELD_MISSING)
    if type(bundle["schema"]) is not str:
        _raise(ExternalAnchorErrorCode.MALFORMED)
    if bundle["schema"] != ANCHOR_BUNDLE_SCHEMA:
        _raise(ExternalAnchorErrorCode.SCHEMA_UNSUPPORTED)
    if type(bundle["version"]) is not int:
        _raise(ExternalAnchorErrorCode.MALFORMED)
    if bundle["version"] != ANCHOR_BUNDLE_VERSION:
        _raise(ExternalAnchorErrorCode.VERSION_UNSUPPORTED)
    if type(bundle["algorithm"]) is not str:
        _raise(ExternalAnchorErrorCode.MALFORMED)
    if bundle["algorithm"] != ANCHOR_BUNDLE_ALGORITHM:
        _raise(ExternalAnchorErrorCode.ALGORITHM_UNSUPPORTED)
    _validate_anchor_values(tuple(bundle[name] for name in _ANCHOR_FIELDS))


def _anchor_values(value: object) -> tuple[object, ...]:
    return tuple(getattr(value, name) for name in _ANCHOR_FIELDS)


def _validate_anchor_values(values: tuple[object, ...]) -> None:
    by_name = dict(zip(_ANCHOR_FIELDS, values, strict=True))
    for name in _OBJECT_ID_FIELDS:
        candidate = by_name[name]
        if type(candidate) is not str or _HEX40.fullmatch(candidate) is None:
            _raise(ExternalAnchorErrorCode.DIGEST_MALFORMED)
    for name in _DIGEST_FIELDS:
        candidate = by_name[name]
        if type(candidate) is not str or _HEX64.fullmatch(candidate) is None:
            _raise(ExternalAnchorErrorCode.DIGEST_MALFORMED)
    recipe_id = by_name["expected_patch_recipe_id"]
    if type(recipe_id) is not str:
        _raise(ExternalAnchorErrorCode.MALFORMED)
    if recipe_id != SUPPORTED_PATCH_RECIPE_ID:
        _raise(ExternalAnchorErrorCode.RECIPE_UNSUPPORTED)
    recipe_version = by_name["expected_patch_recipe_version"]
    if type(recipe_version) is not int:
        _raise(ExternalAnchorErrorCode.MALFORMED)
    if recipe_version != SUPPORTED_PATCH_RECIPE_VERSION:
        _raise(ExternalAnchorErrorCode.RECIPE_VERSION_UNSUPPORTED)


__all__ = (
    "ANCHOR_BUNDLE_ALGORITHM",
    "ANCHOR_BUNDLE_SCHEMA",
    "ANCHOR_BUNDLE_VERSION",
    "ExternalAnchorErrorCode",
    "ExternalTrustAnchorError",
    "MAX_ANCHOR_BUNDLE_BYTES",
    "ParsedSourceTrustAnchors",
    "VerifiedSourceTrustAnchors",
    "is_valid_verified_source_trust_anchors",
    "parse_source_trust_anchor_bundle",
    "serialize_source_trust_anchor_bundle",
)
