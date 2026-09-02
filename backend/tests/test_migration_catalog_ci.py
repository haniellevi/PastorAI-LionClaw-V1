from __future__ import annotations

import copy
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts import verify_migration_catalog_ci as ci


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "migration-catalog-head.yml"
CURRENT_SHA = "a" * 40
PRIOR_SHA = "b" * 40
BLOB_SHA = "c" * 40


@dataclass
class FakeGit:
    current_sha: str = CURRENT_SHA
    prior_sha: str = PRIOR_SHA
    prior_content: bytes | None = None
    ancestor: bool = True
    calls: list[tuple[tuple[str, ...], int]] = field(default_factory=list)

    def __call__(self, args: tuple[str, ...], maximum: int) -> bytes:
        self.calls.append((args, maximum))
        if args == ("rev-parse", "--verify", "HEAD^{commit}"):
            return f"{self.current_sha}\n".encode("ascii")
        if args == ("cat-file", "-t", self.prior_sha):
            return b"commit\n"
        if args == (
            "merge-base",
            "--is-ancestor",
            self.prior_sha,
            "HEAD",
        ):
            if not self.ancestor:
                raise ci.GitEvidenceError
            return b""
        prior_path = f"{self.prior_sha}:{ci.HEAD_RELATIVE_PATH}"
        if args == ("rev-parse", "--verify", prior_path):
            if self.prior_content is None:
                raise ci.GitEvidenceError
            return f"{BLOB_SHA}\n".encode("ascii")
        if args == ("cat-file", "-t", BLOB_SHA):
            return b"blob\n"
        if args == ("cat-file", "-s", BLOB_SHA):
            if self.prior_content is None:
                raise ci.GitEvidenceError
            return f"{len(self.prior_content)}\n".encode("ascii")
        if args == ("cat-file", "blob", BLOB_SHA):
            if self.prior_content is None:
                raise ci.GitEvidenceError
            return self.prior_content
        raise AssertionError(f"comando Git inesperado: {args!r}")


def _pull_request_args() -> dict[str, str]:
    return {
        "event_name": "pull_request",
        "current_sha": CURRENT_SHA,
        "pull_request_base_sha": PRIOR_SHA,
        "push_before_sha": "",
    }


def _serialized(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode(
        "ascii"
    )


def _future_catalog(
    tmp_path: Path,
) -> tuple[Path, Path, Path, bytes, dict[str, Any]]:
    prior_content = ci.catalog_head.HEAD_PATH.read_bytes()
    head = ci.catalog_head._decode_json(prior_content)
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    historical_entries = head["historical_prefix"]["entries"]
    for entry in historical_entries:
        source = ci.catalog_head.MIGRATIONS_DIR / entry["name"]
        (migrations / entry["name"]).write_bytes(source.read_bytes())

    new_name = "20260902_120000_ci_append_example.sql"
    new_content = b"select 1;\n"
    (migrations / new_name).write_bytes(new_content)
    addition = {
        "position": len(historical_entries),
        "name": new_name,
        "sha256": hashlib.sha256(new_content).hexdigest(),
        "size_bytes": len(new_content),
    }
    current_entries = copy.deepcopy(historical_entries) + [addition]
    resulting_digest = ci.catalog_head._catalog_digest(current_entries)
    head["append_only_batches"] = [
        {
            "batch_id": "migration-catalog-append-0001",
            "entries": [addition],
            "previous_catalog_digest_sha256": (
                ci.catalog_head.HISTORICAL_DIGEST_SHA256
            ),
            "resulting_catalog_digest_sha256": resulting_digest,
            "sequence": 1,
        }
    ]
    head["current_head"] = {
        "digest_sha256": resulting_digest,
        "last_basename": new_name,
        "migration_count": 76,
    }
    head["previous_approved_head_sha256"] = hashlib.sha256(
        prior_content
    ).hexdigest()
    head_path = tmp_path / "head.json"
    schema_path = tmp_path / "head.schema.json"
    head_path.write_bytes(_serialized(head))
    schema_path.write_bytes(ci.catalog_head.SCHEMA_PATH.read_bytes())
    return migrations, head_path, schema_path, prior_content, head


def _point_catalog_at(
    monkeypatch: pytest.MonkeyPatch,
    *,
    migrations: Path,
    head_path: Path,
    schema_path: Path,
) -> None:
    monkeypatch.setattr(ci.catalog_head, "MIGRATIONS_DIR", migrations)
    monkeypatch.setattr(ci.catalog_head, "HEAD_PATH", head_path)
    monkeypatch.setattr(ci.catalog_head, "SCHEMA_PATH", schema_path)
    monkeypatch.setattr(ci.source_manifest, "MIGRATIONS_DIR", migrations)


def test_current_initial_head_verifies_without_reading_prior_blob() -> None:
    git = FakeGit()

    result = ci.verify_ci(**_pull_request_args(), git_command=git)

    assert result == ci.CiVerificationResult(
        event_name="pull_request",
        migration_count=75,
        catalog_digest_sha256=ci.catalog_head.HISTORICAL_DIGEST_SHA256,
        prior_head_required=False,
    )
    assert not any(
        call[0][:2] == ("cat-file", "blob") for call in git.calls
    )


def test_append_head_uses_event_ancestor_as_exact_approved_prior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior_content = b'{"prior":"head"}\n'
    snapshot = {
        "append_only_batches": [{"sequence": 1}],
        "current_head": {
            "digest_sha256": "d" * 64,
            "migration_count": 76,
        },
    }
    received: list[Any] = []
    git = FakeGit(prior_content=prior_content)

    monkeypatch.setattr(
        ci.catalog_head,
        "_validated_snapshot_for_historical_consumers",
        lambda: (snapshot, [object()] * 76),
    )

    def strict_verification(*, approved_prior: Any) -> dict[str, Any]:
        received.append(approved_prior)
        return snapshot

    monkeypatch.setattr(
        ci.catalog_head,
        "verify_versioned_head",
        strict_verification,
    )
    monkeypatch.setattr(ci.source_manifest, "verify_manifest", lambda path: None)
    monkeypatch.setattr(ci.epoch_v3, "verify_versioned_package", lambda: None)

    result = ci.verify_ci(**_pull_request_args(), git_command=git)

    assert result.prior_head_required is True
    assert result.migration_count == 76
    assert len(received) == 1
    assert received[0].content_sha256 == hashlib.sha256(
        prior_content
    ).hexdigest()
    assert received[0].head == {"prior": "head"}
    assert (("cat-file", "blob", BLOB_SHA), len(prior_content)) in git.calls


def test_future_append_verifies_end_to_end_with_exact_git_prior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations, head_path, schema_path, prior_content, expected_head = (
        _future_catalog(tmp_path)
    )
    _point_catalog_at(
        monkeypatch,
        migrations=migrations,
        head_path=head_path,
        schema_path=schema_path,
    )

    result = ci.verify_ci(
        **_pull_request_args(),
        git_command=FakeGit(prior_content=prior_content),
    )

    assert result == ci.CiVerificationResult(
        event_name="pull_request",
        migration_count=76,
        catalog_digest_sha256=expected_head["current_head"][
            "digest_sha256"
        ],
        prior_head_required=True,
    )


def test_future_append_rejects_wrong_git_prior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations, head_path, schema_path, _prior_content, _head = (
        _future_catalog(tmp_path)
    )
    _point_catalog_at(
        monkeypatch,
        migrations=migrations,
        head_path=head_path,
        schema_path=schema_path,
    )

    with pytest.raises(ci.catalog_head.VerificationError):
        ci.verify_ci(
            **_pull_request_args(),
            git_command=FakeGit(prior_content=b"{}\n"),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"event_name": "workflow_dispatch"},
        {"current_sha": "0" * 40},
        {"current_sha": "A" * 40},
        {"pull_request_base_sha": ""},
        {"push_before_sha": "f" * 40},
    ],
)
def test_invalid_or_ambiguous_event_context_fails_closed(
    overrides: dict[str, str],
) -> None:
    values = _pull_request_args()
    values.update(overrides)
    with pytest.raises(ci.UsageError):
        ci.verify_ci(**values, git_command=FakeGit())


def test_push_uses_before_sha_and_rejects_non_ancestor() -> None:
    values = {
        "event_name": "push",
        "current_sha": CURRENT_SHA,
        "pull_request_base_sha": "",
        "push_before_sha": PRIOR_SHA,
    }
    with pytest.raises(ci.GitEvidenceError):
        ci.verify_ci(
            **values,
            git_command=FakeGit(ancestor=False),
        )


def test_checkout_must_equal_event_current_sha() -> None:
    with pytest.raises(ci.GitEvidenceError):
        ci.verify_ci(
            **_pull_request_args(),
            git_command=FakeGit(current_sha="e" * 40),
        )


def test_prior_blob_size_is_bounded_before_content_read() -> None:
    calls: list[tuple[str, ...]] = []

    def oversized(args: tuple[str, ...], maximum: int) -> bytes:
        calls.append(args)
        if args[0] == "rev-parse":
            return f"{BLOB_SHA}\n".encode("ascii")
        if args == ("cat-file", "-t", BLOB_SHA):
            return b"blob\n"
        if args == ("cat-file", "-s", BLOB_SHA):
            return f"{ci.catalog_head.MAX_JSON_BYTES + 1}\n".encode("ascii")
        raise AssertionError("conteúdo do blob não deveria ser lido")

    with pytest.raises(ci.GitEvidenceError):
        ci._read_prior_head(PRIOR_SHA, oversized)
    assert ("cat-file", "blob", BLOB_SHA) not in calls


def test_git_runner_accepts_only_local_read_only_subcommands() -> None:
    with pytest.raises(ci.GitEvidenceError):
        ci._run_git(("fetch", "origin"), 10)
    with pytest.raises(ci.GitEvidenceError):
        ci._run_git(("push", "origin"), 10)


def test_main_success_output_keeps_both_gates_closed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        ci,
        "verify_ci",
        lambda **kwargs: ci.CiVerificationResult(
            event_name="push",
            migration_count=76,
            catalog_digest_sha256="d" * 64,
            prior_head_required=True,
        ),
    )
    args = [
        "--event-name",
        "push",
        "--current-sha",
        CURRENT_SHA,
        "--pull-request-base-sha",
        "",
        "--push-before-sha",
        PRIOR_SHA,
    ]

    assert ci.main(args) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.splitlines() == [
        "RESULT=MIGRATION_CATALOG_CI_VERIFIED_OFFLINE",
        "EVENT_NAME=push",
        "CATALOG_MIGRATION_COUNT=76",
        f"CATALOG_DIGEST_SHA256={'d' * 64}",
        "PRIOR_HEAD_REQUIRED=true",
        "HISTORICAL_CONSUMERS=VERIFIED_BLOCKED_ONLY",
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "NEXT_STAGE_AUTHORIZED=false",
    ]


def test_main_failure_is_sanitized_and_fail_closed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_like = "sensitive-invalid-value"
    assert ci.main(["--event-name", secret_like]) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert secret_like not in output.out
    assert output.out.splitlines() == [
        "RESULT=BLOCKED_MIGRATION_CATALOG_CI:USAGE",
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "NEXT_STAGE_AUTHORIZED=false",
    ]


def test_workflow_is_minimal_read_only_and_runs_the_ci_verifier() -> None:
    workflow = yaml.load(
        WORKFLOW_PATH.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    assert set(workflow) == {
        "concurrency",
        "jobs",
        "name",
        "on",
        "permissions",
    }
    assert workflow["on"] == {
        "pull_request": "",
        "push": {"branches": ["main"]},
    }
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["migration-catalog-head"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == "5"
    assert "services" not in job

    checkout, setup, verification = job["steps"]
    assert checkout["uses"] == (
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    )
    assert checkout["with"] == {
        "fetch-depth": "0",
        "persist-credentials": "false",
    }
    assert setup["uses"] == (
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
    )
    assert setup["with"] == {"python-version": "3.13.14"}
    assert verification["working-directory"] == "backend"
    assert set(verification["env"]) == {
        "MIGRATION_CATALOG_CURRENT_SHA",
        "MIGRATION_CATALOG_EVENT_NAME",
        "MIGRATION_CATALOG_PR_BASE_SHA",
        "MIGRATION_CATALOG_PUSH_BEFORE_SHA",
    }
    command = verification["run"]
    assert "scripts/verify_migration_catalog_ci.py" in command
    assert "--current-sha" in command
    assert "--pull-request-base-sha" in command
    assert "--push-before-sha" in command
    normalized = WORKFLOW_PATH.read_text(encoding="utf-8").lower()
    for forbidden in (
        "pull_request_target",
        "secrets.",
        "apply_migrations.py",
        "m06_migration_database_url",
        "curl ",
        "wget ",
        "git fetch",
        "git push",
    ):
        assert forbidden not in normalized
