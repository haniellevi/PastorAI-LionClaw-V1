#!/usr/bin/env python3
"""Author a PRIVATE_RUNTIME policy artifact without creating migration 76.

The V1 ``new_migration.py`` contract is intentionally untouched.  This helper
creates only a reviewable policy draft below ``docs/governance``; it never
changes ``backend/migrations`` or the approved catalog head.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata

try:
    from private_runtime_intent_v2 import (
        INTENT_PREFIX,
        NEXT_STAGE_AUTHORIZED,
        OPERATIONAL_AUTHORIZATION,
        PrivateRuntimeIntentError,
        PrivateRuntimePolicyCandidate,
        content_sha256,
        parse_intent,
        render_draft,
    )
except ImportError:  # pragma: no cover - direct file execution from backend
    _intent_spec = importlib.util.spec_from_file_location(
        "private_runtime_intent_v2_isolated", Path(__file__).with_name("private_runtime_intent_v2.py")
    )
    if _intent_spec is None or _intent_spec.loader is None:
        raise
    _intent_module = importlib.util.module_from_spec(_intent_spec)
    sys.modules[_intent_spec.name] = _intent_module
    _intent_spec.loader.exec_module(_intent_module)
    INTENT_PREFIX = _intent_module.INTENT_PREFIX
    NEXT_STAGE_AUTHORIZED = _intent_module.NEXT_STAGE_AUTHORIZED
    OPERATIONAL_AUTHORIZATION = _intent_module.OPERATIONAL_AUTHORIZATION
    PrivateRuntimeIntentError = _intent_module.PrivateRuntimeIntentError
    PrivateRuntimePolicyCandidate = _intent_module.PrivateRuntimePolicyCandidate
    content_sha256 = _intent_module.content_sha256
    parse_intent = _intent_module.parse_intent
    render_draft = _intent_module.render_draft


REPO_ROOT = Path(__file__).absolute().parents[2]
POLICY_DIR = REPO_ROOT / "docs" / "governance" / "migrations" / "private-runtime"
GIT_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
MAX_DESCRIPTION_CHARS = 160
MAX_SLUG_CHARS = 120


class PrivateRuntimeAuthoringError(RuntimeError):
    exit_code = 4


class UsageError(PrivateRuntimeAuthoringError):
    exit_code = 2


class CollisionError(PrivateRuntimeAuthoringError):
    exit_code = 5


class RepositoryBindingError(PrivateRuntimeAuthoringError):
    exit_code = 7


def slugify(description: str) -> str:
    if (
        type(description) is not str
        or not description.strip()
        or len(description) > MAX_DESCRIPTION_CHARS
        or any(unicodedata.category(char).startswith("C") for char in description)
    ):
        raise UsageError
    normalized = unicodedata.normalize("NFKD", description)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
    if not slug or len(slug) > MAX_SLUG_CHARS:
        raise UsageError
    return slug


def _validated_sha(value: object) -> str:
    if type(value) is not str or GIT_SHA_RE.fullmatch(value) is None or set(value) == {"0"}:
        raise UsageError
    return value


def _git_head() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RepositoryBindingError from exc
    value = completed.stdout.decode("ascii", errors="strict").strip()
    if GIT_SHA_RE.fullmatch(value) is None:
        raise RepositoryBindingError
    return value


def _write_exclusive(path: Path, content: bytes) -> None:
    POLICY_DIR.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    for name in ("O_CLOEXEC", "O_NOFOLLOW"):
        if not hasattr(os, name):
            raise PrivateRuntimeAuthoringError
        flags |= getattr(os, name)
    try:
        descriptor = os.open(path, flags, 0o600)
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise PrivateRuntimeAuthoringError
            offset += written
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        if info.st_nlink != 1 or info.st_size != len(content) or (info.st_mode & 0o777) != 0o600:
            raise PrivateRuntimeAuthoringError
    except FileExistsError as exc:
        raise CollisionError from exc
    except OSError as exc:
        raise PrivateRuntimeAuthoringError from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def draft_private_runtime(description: str, *, expected_sha: str) -> PrivateRuntimePolicyCandidate:
    expected_sha = _validated_sha(expected_sha)
    if _git_head() != expected_sha:
        raise RepositoryBindingError
    slug = slugify(description)
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    basename = f"{timestamp}_{slug}.policy.json"
    content = render_draft(basename=basename, base_repository_sha=expected_sha)
    # The lock is a separate inode from the V1 governance lock and cannot
    # mutate or publish the V1 head.
    POLICY_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = POLICY_DIR / ".authoring.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        path = POLICY_DIR / basename
        _write_exclusive(path, content)
        return PrivateRuntimePolicyCandidate(
            basename=basename,
            content=content,
            content_sha256=content_sha256(content),
        )


def _usage() -> None:
    print(
        "usage: python scripts/new_private_runtime_migration.py "
        'draft-private-runtime --expected-repository-sha <sha> "description"',
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 4 or args[0] != "draft-private-runtime" or args[1] != "--expected-repository-sha":
            raise UsageError
        candidate = draft_private_runtime(args[3], expected_sha=args[2])
    except UsageError:
        _usage()
        print("RESULT=BLOCKED_PRIVATE_RUNTIME_AUTHORING:USAGE")
        print("OPERATIONAL_AUTHORIZATION=BLOCKED")
        print("NEXT_STAGE_AUTHORIZED=false")
        return 2
    except (PrivateRuntimeIntentError, PrivateRuntimeAuthoringError):
        print("RESULT=BLOCKED_PRIVATE_RUNTIME_AUTHORING:SOURCE_ONLY_POLICY_INVALID")
        print("OPERATIONAL_AUTHORIZATION=BLOCKED")
        print("NEXT_STAGE_AUTHORIZED=false")
        return 4
    except Exception:
        print("RESULT=BLOCKED_PRIVATE_RUNTIME_AUTHORING:INTERNAL_ERROR")
        print("OPERATIONAL_AUTHORIZATION=BLOCKED")
        print("NEXT_STAGE_AUTHORIZED=false")
        return 10
    print("RESULT=PRIVATE_RUNTIME_POLICY_DRAFT_CREATED")
    print(f"POLICY_BASENAME={candidate.basename}")
    print(f"POLICY_SHA256={candidate.content_sha256}")
    print(f"INTENT_PREFIX={INTENT_PREFIX}")
    print(f"OPERATIONAL_AUTHORIZATION={str(OPERATIONAL_AUTHORIZATION).lower()}")
    print(f"NEXT_STAGE_AUTHORIZED={str(NEXT_STAGE_AUTHORIZED).lower()}")
    print("CATALOG_MIGRATION_CREATED=false")
    print("CATALOG_HEAD_CHANGED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
