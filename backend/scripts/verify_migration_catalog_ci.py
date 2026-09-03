#!/usr/bin/env python3
"""Verify the migration catalog in GitHub CI without external effects.

The current catalog is read from the checkout.  When it contains an append
batch, the prior head is read from the local Git object database at the
event-provided base commit and supplied to the strict catalog verifier.  No
fetch, network, database, migration runner, or process environment secret is
used by this script.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable

try:
    from scripts import verify_migration_catalog_head as catalog_head
    from scripts import (
        verify_migration_history_divergence_remediation_proposal_v3 as epoch_v3,
    )
    from scripts import (
        verify_migration_history_schema_expectation_manifest as source_manifest,
    )
except ImportError:  # pragma: no cover - direct script execution
    import verify_migration_catalog_head as catalog_head
    import verify_migration_history_divergence_remediation_proposal_v3 as epoch_v3
    import verify_migration_history_schema_expectation_manifest as source_manifest


REPO_ROOT = Path(__file__).absolute().parents[2]
HEAD_RELATIVE_PATH = (
    "docs/governance/migrations/migration-catalog-head-v1.json"
)
SOURCE_MANIFEST_PATH = (
    source_manifest.MANIFEST_DIR / source_manifest.MANIFEST_BASENAME
)

MAX_GIT_CONTROL_OUTPUT_BYTES = 256
GIT_TIMEOUT_SECONDS = 10
GIT_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
GIT_OBJECT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")

VERIFIED_RESULT = "RESULT=MIGRATION_CATALOG_CI_VERIFIED_OFFLINE"
OPERATIONAL_BLOCK = "OPERATIONAL_AUTHORIZATION=BLOCKED"
NEXT_STAGE_BLOCK = "NEXT_STAGE_AUTHORIZED=false"


class CiVerificationError(RuntimeError):
    exit_code = 4
    reason = "CI_CONTRACT_INVALID"


class UsageError(CiVerificationError):
    exit_code = 2
    reason = "USAGE"


class GitEvidenceError(CiVerificationError):
    exit_code = 3
    reason = "LOCAL_GIT_EVIDENCE_INVALID"


@dataclass(frozen=True)
class CiEventContext:
    event_name: str
    current_sha: str
    prior_sha: str


@dataclass(frozen=True)
class CiVerificationResult:
    event_name: str
    migration_count: int
    catalog_digest_sha256: str
    prior_head_required: bool


GitCommand = Callable[[tuple[str, ...], int], bytes]


def _minimal_git_environment() -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.defpath,
    }


def _run_git(args: tuple[str, ...], maximum: int) -> bytes:
    if (
        type(args) is not tuple
        or not args
        or any(type(item) is not str or not item for item in args)
        or type(maximum) is not int
        or maximum < 0
        or maximum > catalog_head.MAX_JSON_BYTES
    ):
        raise GitEvidenceError
    if args[0] not in {"cat-file", "merge-base", "rev-parse"}:
        raise GitEvidenceError
    command = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-C",
        str(REPO_ROOT),
        *args,
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            cwd=REPO_ROOT,
            env=_minimal_git_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise GitEvidenceError from exc
    if completed.returncode != 0 or len(completed.stdout) > maximum:
        raise GitEvidenceError
    return completed.stdout


def _validated_sha(value: object) -> str:
    if (
        type(value) is not str
        or GIT_SHA_RE.fullmatch(value) is None
        or set(value) == {"0"}
    ):
        raise UsageError
    return value


def _event_context(
    *,
    event_name: object,
    current_sha: object,
    pull_request_base_sha: object,
    push_before_sha: object,
) -> CiEventContext:
    current = _validated_sha(current_sha)
    if event_name == "pull_request":
        if push_before_sha != "":
            raise UsageError
        prior = _validated_sha(pull_request_base_sha)
    elif event_name == "push":
        if pull_request_base_sha != "":
            raise UsageError
        prior = _validated_sha(push_before_sha)
    else:
        raise UsageError
    if prior == current:
        raise UsageError
    return CiEventContext(
        event_name=event_name,
        current_sha=current,
        prior_sha=prior,
    )


def _single_line_ascii(content: bytes, pattern: re.Pattern[str]) -> str:
    if (
        type(content) is not bytes
        or len(content) > MAX_GIT_CONTROL_OUTPUT_BYTES
    ):
        raise GitEvidenceError
    try:
        value = content.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise GitEvidenceError from exc
    if pattern.fullmatch(value) is None:
        raise GitEvidenceError
    return value


def _validate_checkout(
    context: CiEventContext,
    git_command: GitCommand,
) -> None:
    current = _single_line_ascii(
        git_command(
            ("rev-parse", "--verify", "HEAD^{commit}"),
            MAX_GIT_CONTROL_OUTPUT_BYTES,
        ),
        GIT_OBJECT_RE,
    )
    if current != context.current_sha:
        raise GitEvidenceError
    prior_type = git_command(
        ("cat-file", "-t", context.prior_sha),
        MAX_GIT_CONTROL_OUTPUT_BYTES,
    )
    if prior_type != b"commit\n":
        raise GitEvidenceError
    git_command(
        ("merge-base", "--is-ancestor", context.prior_sha, "HEAD"),
        MAX_GIT_CONTROL_OUTPUT_BYTES,
    )


def _read_prior_head(
    prior_sha: str,
    git_command: GitCommand,
) -> bytes:
    blob = _single_line_ascii(
        git_command(
            (
                "rev-parse",
                "--verify",
                f"{prior_sha}:{HEAD_RELATIVE_PATH}",
            ),
            MAX_GIT_CONTROL_OUTPUT_BYTES,
        ),
        GIT_OBJECT_RE,
    )
    if git_command(
        ("cat-file", "-t", blob),
        MAX_GIT_CONTROL_OUTPUT_BYTES,
    ) != b"blob\n":
        raise GitEvidenceError
    raw_size = _single_line_ascii(
        git_command(
            ("cat-file", "-s", blob),
            MAX_GIT_CONTROL_OUTPUT_BYTES,
        ),
        re.compile(r"[0-9]{1,10}"),
    )
    size = int(raw_size, 10)
    if size < 1 or size > catalog_head.MAX_JSON_BYTES:
        raise GitEvidenceError
    content = git_command(("cat-file", "blob", blob), size)
    if len(content) != size:
        raise GitEvidenceError
    return content


def verify_ci(
    *,
    event_name: object,
    current_sha: object,
    pull_request_base_sha: object,
    push_before_sha: object,
    git_command: GitCommand = _run_git,
) -> CiVerificationResult:
    context = _event_context(
        event_name=event_name,
        current_sha=current_sha,
        pull_request_base_sha=pull_request_base_sha,
        push_before_sha=push_before_sha,
    )
    _validate_checkout(context, git_command)

    snapshot, _catalog = (
        catalog_head._validated_snapshot_for_historical_consumers()
    )
    batches = snapshot.get("append_only_batches")
    if type(batches) is not list:
        raise CiVerificationError
    approved_prior = None
    if batches:
        prior_content = _read_prior_head(context.prior_sha, git_command)
        approved_prior = catalog_head.ApprovedPriorHead(
            content_sha256=hashlib.sha256(prior_content).hexdigest(),
            head=catalog_head._decode_json(prior_content),
        )

    strict_head = catalog_head.verify_versioned_head(
        approved_prior=approved_prior
    )
    if not catalog_head._exact_json(snapshot, strict_head):
        raise CiVerificationError

    source_manifest.verify_manifest(SOURCE_MANIFEST_PATH)
    epoch_v3.verify_versioned_package()

    current = strict_head["current_head"]
    return CiVerificationResult(
        event_name=context.event_name,
        migration_count=current["migration_count"],
        catalog_digest_sha256=current["digest_sha256"],
        prior_head_required=bool(batches),
    )


def _parse_args(args: list[str]) -> dict[str, str]:
    keys = {
        "--current-sha": "current_sha",
        "--event-name": "event_name",
        "--pull-request-base-sha": "pull_request_base_sha",
        "--push-before-sha": "push_before_sha",
    }
    if len(args) != len(keys) * 2:
        raise UsageError
    parsed: dict[str, str] = {}
    for index in range(0, len(args), 2):
        option = args[index]
        if option not in keys or keys[option] in parsed:
            raise UsageError
        parsed[keys[option]] = args[index + 1]
    if set(parsed) != set(keys.values()):
        raise UsageError
    return parsed


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        parsed = _parse_args(args)
        result = verify_ci(**parsed)
    except CiVerificationError as exc:
        print(f"RESULT=BLOCKED_MIGRATION_CATALOG_CI:{exc.reason}")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return exc.exit_code
    except catalog_head.VerificationError:
        reason = "CURRENT_CATALOG_INVALID"
    except source_manifest.ManifestError:
        reason = "HISTORICAL_SOURCE_MANIFEST_INVALID"
    except epoch_v3.VerificationError:
        reason = "HISTORICAL_EPOCH_V3_INVALID"
    except Exception:
        reason = "INTERNAL_ERROR"
    else:
        print(VERIFIED_RESULT)
        print(f"EVENT_NAME={result.event_name}")
        print(f"CATALOG_MIGRATION_COUNT={result.migration_count}")
        print(f"CATALOG_DIGEST_SHA256={result.catalog_digest_sha256}")
        prior = str(result.prior_head_required).lower()
        print(f"PRIOR_HEAD_REQUIRED={prior}")
        print("HISTORICAL_CONSUMERS=VERIFIED_BLOCKED_ONLY")
        print(OPERATIONAL_BLOCK)
        print(NEXT_STAGE_BLOCK)
        return 0
    print(f"RESULT=BLOCKED_MIGRATION_CATALOG_CI:{reason}")
    print(OPERATIONAL_BLOCK)
    print(NEXT_STAGE_BLOCK)
    return 10


if __name__ == "__main__":
    raise SystemExit(main())
