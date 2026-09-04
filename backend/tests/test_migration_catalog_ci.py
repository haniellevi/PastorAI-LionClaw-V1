from __future__ import annotations

import copy
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from scripts import new_migration as migration_authoring
from scripts import (
    verify_migration_history_divergence_remediation_proposal_v3 as epoch_v3,
)
from scripts import (
    verify_migration_history_schema_expectation_manifest as source_manifest,
)
from scripts import verify_migration_catalog_ci as ci


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "migration-catalog-head.yml"
RLS_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "rls-integration.yml"
CURRENT_SHA = "a" * 40
PRIOR_SHA = "b" * 40


@dataclass
class FakeSnapshot:
    git_sha: str
    repository: Path
    cleaned: bool = False

    def cleanup(self) -> None:
        self.cleaned = True


@dataclass
class FakeTrust:
    root: Path
    prior_content: bytes
    ancestor: bool = True
    snapshots: list[FakeSnapshot] = field(default_factory=list)

    def __post_init__(self) -> None:
        current_repository = self.root / "current"
        prior_repository = self.root / "prior"
        current_repository.mkdir(parents=True)
        prior_head = prior_repository.joinpath(*Path(ci.HEAD_RELATIVE_PATH).parts)
        prior_head.parent.mkdir(parents=True)
        prior_head.write_bytes(self.prior_content)
        self.snapshots = [
            FakeSnapshot(CURRENT_SHA, current_repository),
            FakeSnapshot(PRIOR_SHA, prior_repository),
        ]

    def snapshot_factory(self, git_sha: str) -> FakeSnapshot:
        for snapshot in self.snapshots:
            if snapshot.git_sha == git_sha:
                return snapshot
        raise ci.GitEvidenceError

    def parent_reader(self, git_sha: str) -> tuple[str, ...]:
        if git_sha == CURRENT_SHA:
            return (PRIOR_SHA,) if self.ancestor else ()
        if git_sha == PRIOR_SHA:
            return ()
        raise ci.GitEvidenceError

    def dependencies(self) -> dict[str, Any]:
        modules = ci.VerificationModules(
            catalog_head=ci.catalog_head,
            migration_authoring=migration_authoring,
            source_manifest=source_manifest,
            epoch_v3=epoch_v3,
        )
        return {
            "snapshot_factory": self.snapshot_factory,
            "commit_parent_reader": self.parent_reader,
            "module_loader": lambda _repository: modules,
            "repository_witness": lambda _repository: "stable",
        }


def _pull_request_args() -> dict[str, str]:
    return {
        "event_name": "pull_request",
        "current_sha": CURRENT_SHA,
        "pull_request_base_sha": PRIOR_SHA,
        "push_before_sha": "",
    }


def _verify_with_fake_trust(
    tmp_path: Path,
    *,
    prior_content: bytes,
    ancestor: bool = True,
    arguments: dict[str, str] | None = None,
) -> ci.CiVerificationResult:
    trust = FakeTrust(tmp_path / "trust", prior_content, ancestor=ancestor)
    result = ci.verify_ci(
        **(_pull_request_args() if arguments is None else arguments),
        **trust.dependencies(),
    )
    assert all(snapshot.cleaned for snapshot in trust.snapshots)
    return result


def _serialized(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode(
        "ascii"
    )


def test_repository_witness_accepts_zero_length_git_blob(tmp_path: Path) -> None:
    repository = tmp_path / "private-snapshot"
    repository.mkdir(mode=0o700)
    os.chmod(repository, 0o700)
    empty = repository / "tracked-empty-file"
    empty.write_bytes(b"")
    os.chmod(empty, 0o600)

    witness = ci._repository_witness(repository)

    assert len(witness) == 64
    assert int(witness, 16) >= 0


@pytest.mark.parametrize(
    "path",
    (
        "backups/production.sql",
        "docs/dumps/live.dump",
        "exports/people.csv",
        "docs/media/pastoral-call.mp3",
        "backend/.env.production",
        "docs/decisions/operator.pem",
        "backend/scripts/clerk_export.py",
        "backend/scripts/target_users_prod.json",
        "backend/scripts/migrate_clerk_production.py",
    ),
)
def test_ci_snapshot_manifest_rejects_protected_paths_before_archive(
    path: str,
) -> None:
    manifest = (
        b"100644 blob "
        + b"a" * 40
        + b" 12\t"
        + path.encode("utf-8")
        + b"\x00"
    )

    with pytest.raises(ci.trusted_snapshot.GitEvidenceError):
        ci._reject_protected_snapshot_manifest(manifest)


def test_ci_snapshot_manifest_allows_public_and_sanitized_product_images() -> None:
    manifest = (
        b"100644 blob "
        + b"a" * 40
        + b" 12\tfrontend/public/icon-192.png\x00"
        + b"100644 blob "
        + b"b" * 40
        + b" 12\tdocs/research/login-sanitizado.jpg\x00"
    )

    ci._reject_protected_snapshot_manifest(manifest)


def _migration_with_intent(name: str, base_sha: str) -> bytes:
    decision = "docs/decisions/2026-09-02-migration-catalog-evolution.md"
    intent = {
        "affected_relations": ["public.tenant_catalog_probe"],
        "artifact_id": "migration-authoring-intent-v1",
        "base_repository_sha": base_sha,
        "cross_tenant_test_nodeids": [
            "backend/tests/test_rls_invariant.py::"
            "test_t2_tenant_isolation_a_sees_only_a"
        ],
        "decision_refs": [decision],
        "global_justification": None,
        "migration_basename": name,
        "next_stage_authorized": False,
        "operational_authorization": False,
        "pg17_test_nodeids": [
            "backend/tests/test_apply_migrations.py::"
            "test_bootstrap_ledger_creates_exact_owner_only_contract_and_rerun_is_noop",
            "backend/tests/test_rls_invariant.py::"
            "test_t2_tenant_isolation_a_sees_only_a",
        ],
        "recovery": {
            "kind": "FORWARD_COMPENSATION",
            "reference": decision,
        },
        "scope": "TENANT",
        "tenant_controls": {
            "acl_review": "EXPLICIT_GRANTS_AND_REVOKES",
            "enable_rls": True,
            "force_rls": True,
            "igreja_id_column": "igreja_id",
            "policy_context": "app.tenant_igreja_id",
        },
    }
    return (
        "-- PASTORAI_MIGRATION_INTENT_V1="
        + json.dumps(
            intent,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n-- OPERATIONAL_AUTHORIZATION=BLOCKED\n"
        + "-- NEXT_STAGE_AUTHORIZED=false\n"
        + "select 1;\n"
    ).encode("ascii")


def _future_catalog(
    tmp_path: Path,
    *,
    new_content: bytes | None = None,
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
    if new_content is None:
        new_content = _migration_with_intent(new_name, PRIOR_SHA)
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
    catalog_modules = {
        ci.catalog_head,
        source_manifest.catalog_head,
        epoch_v3.catalog_head,
    }
    for catalog_module in catalog_modules:
        monkeypatch.setattr(catalog_module, "MIGRATIONS_DIR", migrations)
        monkeypatch.setattr(catalog_module, "HEAD_PATH", head_path)
        monkeypatch.setattr(catalog_module, "SCHEMA_PATH", schema_path)
    monkeypatch.setattr(source_manifest, "MIGRATIONS_DIR", migrations)


def test_current_initial_head_requires_exact_unchanged_prior_blob(
    tmp_path: Path,
) -> None:
    result = _verify_with_fake_trust(
        tmp_path,
        prior_content=ci.catalog_head.HEAD_PATH.read_bytes(),
    )

    assert result == ci.CiVerificationResult(
        event_name="pull_request",
        migration_count=75,
        catalog_digest_sha256=ci.catalog_head.HISTORICAL_DIGEST_SHA256,
        prior_head_required=False,
    )


def test_initial_head_byte_change_without_append_is_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(ci.GitEvidenceError):
        _verify_with_fake_trust(
            tmp_path,
            prior_content=ci.catalog_head.HEAD_PATH.read_bytes() + b"\n",
        )


def test_append_head_uses_event_ancestor_as_exact_approved_prior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior_content = b'{"prior":"head"}\n'
    snapshot = {
        "append_only_batches": [
            {"sequence": 1, "entries": [{"name": "synthetic.sql"}]}
        ],
        "current_head": {
            "digest_sha256": "d" * 64,
            "migration_count": 76,
        },
    }
    received: list[Any] = []

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
    monkeypatch.setattr(
        ci.catalog_head,
        "_read_stable_file",
        lambda path, *_args, **_kwargs: SimpleNamespace(
            content=(prior_content if "/prior/" in str(path) else b"current\n")
        ),
    )
    monkeypatch.setattr(
        ci.catalog_head,
        "_stable_file_unchanged",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        migration_authoring,
        "_validate_candidate_intent",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(source_manifest, "verify_manifest", lambda path: None)
    monkeypatch.setattr(epoch_v3, "verify_versioned_package", lambda: None)

    result = _verify_with_fake_trust(
        tmp_path,
        prior_content=prior_content,
    )

    assert result.prior_head_required is True
    assert result.migration_count == 76
    assert len(received) == 1
    assert received[0].content_sha256 == hashlib.sha256(
        prior_content
    ).hexdigest()
    assert received[0].head == {"prior": "head"}


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

    result = _verify_with_fake_trust(
        tmp_path / "verify",
        prior_content=prior_content,
    )

    assert result == ci.CiVerificationResult(
        event_name="pull_request",
        migration_count=76,
        catalog_digest_sha256=expected_head["current_head"][
            "digest_sha256"
        ],
        prior_head_required=True,
    )


def test_future_append_without_structured_intent_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations, head_path, schema_path, prior_content, _head = _future_catalog(
        tmp_path,
        new_content=(
            b"-- OPERATIONAL_AUTHORIZATION=BLOCKED\n"
            b"-- NEXT_STAGE_AUTHORIZED=false\n"
            b"select 1;\n"
        ),
    )
    _point_catalog_at(
        monkeypatch,
        migrations=migrations,
        head_path=head_path,
        schema_path=schema_path,
    )

    with pytest.raises(ci.CandidateIntentError):
        _verify_with_fake_trust(
            tmp_path / "verify",
            prior_content=prior_content,
        )


def test_ordinary_pr_after_first_append_accepts_exact_unchanged_base_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations, head_path, schema_path, _initial, expected_head = (
        _future_catalog(tmp_path)
    )
    _point_catalog_at(
        monkeypatch,
        migrations=migrations,
        head_path=head_path,
        schema_path=schema_path,
    )
    unchanged_base_head = head_path.read_bytes()

    result = _verify_with_fake_trust(
        tmp_path / "verify",
        prior_content=unchanged_base_head,
    )

    assert result == ci.CiVerificationResult(
        event_name="pull_request",
        migration_count=76,
        catalog_digest_sha256=expected_head["current_head"][
            "digest_sha256"
        ],
        prior_head_required=True,
    )


def test_format_only_head_change_after_append_is_not_treated_as_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations, head_path, schema_path, _initial, _expected_head = (
        _future_catalog(tmp_path)
    )
    _point_catalog_at(
        monkeypatch,
        migrations=migrations,
        head_path=head_path,
        schema_path=schema_path,
    )
    semantically_same_base = head_path.read_bytes().replace(b"\n", b"\r\n")

    with pytest.raises(ci.CurrentCatalogError):
        _verify_with_fake_trust(
            tmp_path / "verify",
            prior_content=semantically_same_base,
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

    with pytest.raises(ci.CurrentCatalogError):
        _verify_with_fake_trust(
            tmp_path / "verify",
            prior_content=b"{}\n",
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
        ci.verify_ci(**values)


def test_push_uses_before_sha_and_rejects_non_ancestor(tmp_path: Path) -> None:
    values = {
        "event_name": "push",
        "current_sha": CURRENT_SHA,
        "pull_request_base_sha": "",
        "push_before_sha": PRIOR_SHA,
    }
    with pytest.raises(ci.GitEvidenceError):
        _verify_with_fake_trust(
            tmp_path,
            prior_content=ci.catalog_head.HEAD_PATH.read_bytes(),
            ancestor=False,
            arguments=values,
        )


def test_snapshot_identity_must_equal_event_current_sha(tmp_path: Path) -> None:
    trust = FakeTrust(
        tmp_path / "trust", ci.catalog_head.HEAD_PATH.read_bytes()
    )
    trust.snapshots[0].git_sha = "e" * 40
    with pytest.raises(ci.GitEvidenceError):
        ci.verify_ci(
            **_pull_request_args(),
            **trust.dependencies(),
        )


def test_authenticated_commit_parents_rejects_oid_content_mismatch() -> None:
    raw = (
        b"tree " + (b"0" * 40) + b"\n"
        b"author A <a@example.invalid> 0 +0000\n"
        b"committer A <a@example.invalid> 0 +0000\n\nmessage\n"
    )
    commit_sha = ci.trusted_snapshot._hash_git_object("sha1", "commit", raw)

    def tampered(
        _root: Path, _args: tuple[str, ...], _maximum: int
    ) -> bytes:
        return raw + b"tampered"

    with pytest.raises(ci.trusted_snapshot.GitEvidenceError):
        ci._authenticated_commit_parents(
            commit_sha,
            object_format="sha1",
            git_control=tampered,
        )


def test_sanitized_control_plane_drops_checkout_and_ambient_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, Any] = {}
    monkeypatch.setenv("GIT_REPLACE_REF_BASE", "refs/replace/attacker")
    monkeypatch.setenv("GIT_ALTERNATE_OBJECT_DIRECTORIES", "/untrusted")

    def run(command: list[str], **kwargs: Any) -> Any:
        observed["command"] = command
        observed["environment"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout=f"{CURRENT_SHA}\n".encode())

    monkeypatch.setattr(ci.subprocess, "run", run)
    monkeypatch.setattr(ci, "_reject_object_alternates", lambda _fd: None)
    plane = ci._SanitizedGitControlPlane(
        repository_root=tmp_path / "checkout",
        root=tmp_path / "private",
        root_identity=(1, 2),
        git_dir=tmp_path / "private" / "git-control",
        object_fd=9,
        object_format="sha1",
    )

    assert plane.control(
        tmp_path / "checkout",
        ("cat-file", "commit", CURRENT_SHA),
        ci.trusted_snapshot.MAX_CONTROL_OUTPUT_BYTES,
    ) == f"{CURRENT_SHA}\n".encode()
    command = observed["command"]
    assert "--git-dir" in command
    assert str(plane.git_dir) in command
    assert str(tmp_path / "checkout" / ".git") not in " ".join(command)
    environment = observed["environment"]
    assert environment["GIT_OBJECT_DIRECTORY"] == "/proc/self/fd/9"
    assert environment["GIT_CONFIG_COUNT"] == "0"
    assert environment["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert environment["GIT_CONFIG_SYSTEM"] == "/dev/null"
    assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert environment["GIT_NO_LAZY_FETCH"] == "1"
    assert environment["GIT_ALLOW_PROTOCOL"] == ""
    assert environment["GIT_PROTOCOL_FROM_USER"] == "0"
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert "GIT_REPLACE_REF_BASE" not in environment
    assert environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] == ""


def test_sanitized_control_plane_rejects_protected_manifest_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = (
        b"100644 blob "
        + b"a" * 40
        + b" 12\tdocs/backups/production.sql\x00"
    )

    monkeypatch.setattr(
        ci.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=manifest,
        ),
    )
    monkeypatch.setattr(ci, "_reject_object_alternates", lambda _fd: None)
    plane = ci._SanitizedGitControlPlane(
        repository_root=tmp_path / "checkout",
        root=tmp_path / "private",
        root_identity=(1, 2),
        git_dir=tmp_path / "private" / "git-control",
        object_fd=9,
        object_format="sha1",
    )

    with pytest.raises(ci.trusted_snapshot.GitEvidenceError):
        plane.control(
            tmp_path / "checkout",
            (
                "ls-tree",
                "-r",
                "-t",
                "-l",
                "-z",
                "--full-tree",
                CURRENT_SHA,
            ),
            ci.trusted_snapshot.MAX_MANIFEST_BYTES,
        )


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


def test_declared_rls_nodeids_are_executed_by_the_fixed_rls_job_contract() -> None:
    workflow = RLS_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "-m rls_integration" in workflow
    assert "--strict-markers" in workflow
    assert "--junitxml=rls-results.xml" in workflow
    assert "if total == 0:" in workflow
    assert "if executed == 0:" in workflow
    assert "if skipped != 0:" in workflow
    assert "if failed != 0 or errors != 0:" in workflow
    authoring_source = Path(migration_authoring.__file__).read_text(
        encoding="utf-8"
    )
    assert '"rls_integration" not in module_markers | function_markers' in (
        authoring_source
    )
    assert '("pytest", "skip")' in authoring_source
    assert '("pytest", "xfail")' in authoring_source
