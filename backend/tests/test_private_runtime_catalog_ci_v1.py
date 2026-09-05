from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_SHA = "a" * 40
CURRENT_SHA = "b" * 40
AUTHENTICATED_BASE_SHA = "64838cd3f1c6604ef091a940e19f704616d500b3"
ADVANCED_BASE_SHA = "c" * 40
ADVANCED_CURRENT_SHA = "d" * 40
HISTORICAL_DIGEST = (
    "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f"
)
PRIVATE_BASENAME = "20260905_035815_load_private_runtime_turn_context.sql"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


catalog_ci = _load(
    REPO_ROOT / "backend/scripts/verify_private_runtime_catalog_ci.py",
    "private_runtime_catalog_ci_test",
)
catalog = _load(
    REPO_ROOT / "backend/scripts/private_runtime_catalog_v1.py",
    "private_runtime_catalog_ci_catalog_test",
)
intent_runtime = _load(
    REPO_ROOT / "backend/scripts/private_runtime_intent_runtime_v1.py",
    "private_runtime_intent_runtime_ci_catalog_test",
)
adapter = _load(
    REPO_ROOT / "backend/scripts/private_runtime_catalog_adapter_v1.py",
    "private_runtime_catalog_adapter_ci_catalog_test",
)


@dataclass
class _Snapshot:
    git_sha: str
    repository: Path
    cleaned: bool = False

    def cleanup(self) -> None:
        self.cleaned = True


def _empty_snapshot(root: Path, sha: str) -> _Snapshot:
    (root / "docs/governance/migrations").mkdir(parents=True)
    (root / "backend/migrations/private_runtime").mkdir(parents=True)
    (root / "docs/governance/migrations/private-runtime-catalog-head-v1.json").write_bytes(
        (json.dumps(catalog.default_head()) + "\n").encode("ascii")
    )
    return _Snapshot(sha, root)


def _candidate_content(base_sha: str) -> bytes:
    """Build a complete V2 envelope without using a repository migration."""

    intent = intent_runtime.default_intent(
        basename=PRIVATE_BASENAME,
        base_repository_sha=base_sha,
    )
    intent["decision_refs"] = [
        "docs/decisions/2026-09-05-private-runtime-projection-catalog.md"
    ]
    intent["recovery"] = {
        "kind": "REVERSIBLE",
        "reference": "docs/ops/private-runtime-catalog.md",
    }
    nodeid = (
        "backend/tests/test_private_runtime_projection_pg17.py::"
        "test_private_runtime_projection_pg17"
    )
    intent["pg17_test_nodeids"] = [nodeid]
    intent["cross_tenant_test_nodeids"] = [nodeid]
    encoded = json.dumps(
        intent,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    body = (
        "create role agent_projection_owner;\n"
        "create function load_turn_context() returns void "
        "language sql security definer stable as $$select 1;$$;\n"
        "set row_security = on;\n"
        "create policy private_projection on private_projection "
        "using (true);\n"
    )
    return (
        (intent_runtime.INTENT_PREFIX + encoded + "\n").encode("ascii")
        + b"-- OPERATIONAL_AUTHORIZATION=BLOCKED\n"
        + b"-- NEXT_STAGE_AUTHORIZED=false\n"
        + body.encode("ascii")
    )


def _non_empty_snapshot(
    root: Path,
    sha: str,
    content: bytes,
) -> tuple[_Snapshot, dict[str, object]]:
    snapshot = _empty_snapshot(root, sha)
    migration_path = (
        snapshot.repository / "backend/migrations/private_runtime" / PRIVATE_BASENAME
    )
    migration_path.write_bytes(content)
    entry = {
        "position": 0,
        "name": PRIVATE_BASENAME,
        "sha256": catalog._sha256(content),
        "size_bytes": len(content),
    }
    digest = catalog.private_digest([entry])
    head = catalog.default_head()
    head["private_entries"] = [entry]
    head["append_only_batches"] = [
        {
            "batch_id": "private-runtime-catalog-append-0001",
            "entries": [entry],
            "previous_private_digest_sha256": catalog.private_digest([]),
            "resulting_private_digest_sha256": digest,
            "sequence": 1,
        }
    ]
    head["current_head"] = {
        "last_basename": PRIVATE_BASENAME,
        "private_digest_sha256": digest,
        "private_migration_count": 1,
    }
    head_path = (
        snapshot.repository
        / "docs/governance/migrations/private-runtime-catalog-head-v1.json"
    )
    head_path.write_bytes((json.dumps(head) + "\n").encode("ascii"))
    return snapshot, entry


def _source_result(entry: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        public_migration_count=75,
        public_digest_sha256=HISTORICAL_DIGEST,
        private_migration_count=1,
        private_digest_sha256=catalog.private_digest([entry]),
        private_last_basename=PRIVATE_BASENAME,
    )


def _legacy_verifier(**_kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(
        migration_count=75,
        catalog_digest_sha256=HISTORICAL_DIGEST,
    )


def _private_module(source_result: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        verify=lambda: source_result,
        private_catalog=catalog,
        adapter=adapter,
    )


def test_closed_string_list_rejects_unexpected_container_without_type_error() -> None:
    runtime = _load(
        REPO_ROOT / "backend/scripts/private_runtime_intent_runtime_v1.py",
        "private_runtime_intent_runtime_ci_type_test",
    )
    for value in ({"unexpected": True}, ("tuple",), "string", ["ok", {"bad": 1}]):
        assert runtime._closed_string_list(value) is False


def test_ci_runs_legacy_proof_and_combines_empty_private_stream(
    tmp_path: Path,
) -> None:
    current = _empty_snapshot(tmp_path / "current", CURRENT_SHA)
    prior = _Snapshot(BASE_SHA, tmp_path / "prior")
    prior.repository.mkdir()
    calls: list[dict[str, object]] = []

    def legacy_verifier(**kwargs: object) -> object:
        calls.append(kwargs)
        return SimpleNamespace(
            migration_count=75,
            catalog_digest_sha256=HISTORICAL_DIGEST,
        )

    source_result = SimpleNamespace(
        public_migration_count=75,
        public_digest_sha256=HISTORICAL_DIGEST,
        private_migration_count=0,
        private_digest_sha256=catalog.private_digest([]),
        private_last_basename=catalog.HISTORICAL_LAST_BASENAME,
    )
    private_module = SimpleNamespace(
        verify=lambda: source_result,
        private_catalog=catalog,
        adapter=SimpleNamespace(),
    )

    def snapshots(sha: str) -> _Snapshot:
        return current if sha == CURRENT_SHA else prior

    result = catalog_ci.verify_ci(
        event_name="pull_request",
        current_sha=CURRENT_SHA,
        pull_request_base_sha=BASE_SHA,
        push_before_sha="",
        snapshot_factory=snapshots,
        commit_parent_reader=lambda sha: (BASE_SHA,) if sha == CURRENT_SHA else (),
        module_loader=lambda _repository: private_module,
        repository_witness=lambda _repository: "stable",
        legacy_verifier=legacy_verifier,
    )

    assert calls and calls[0]["event_name"] == "pull_request"
    assert result.public_migration_count == 75
    assert result.private_migration_count == 0
    assert result.combined_migration_count == 75
    assert result.private_append_verified is False
    assert current.cleaned and prior.cleaned


def test_ci_rejects_a_private_directory_without_anchored_prior_head(
    tmp_path: Path,
) -> None:
    current = _empty_snapshot(tmp_path / "current", CURRENT_SHA)
    prior_root = tmp_path / "prior"
    prior_root.mkdir()
    (prior_root / "backend/migrations/private_runtime").mkdir(parents=True)
    prior = _Snapshot(BASE_SHA, prior_root)
    source_result = SimpleNamespace(
        public_migration_count=75,
        public_digest_sha256=HISTORICAL_DIGEST,
        private_migration_count=0,
        private_digest_sha256=catalog.private_digest([]),
        private_last_basename=catalog.HISTORICAL_LAST_BASENAME,
    )
    private_module = SimpleNamespace(
        verify=lambda: source_result,
        private_catalog=catalog,
        adapter=SimpleNamespace(),
    )

    with pytest.raises(catalog_ci.HistoricalProofError):
        catalog_ci.verify_ci(
            event_name="pull_request",
            current_sha=CURRENT_SHA,
            pull_request_base_sha=BASE_SHA,
            push_before_sha="",
            snapshot_factory=lambda sha: current if sha == CURRENT_SHA else prior,
            commit_parent_reader=lambda sha: (BASE_SHA,) if sha == CURRENT_SHA else (),
            module_loader=lambda _repository: private_module,
            repository_witness=lambda _repository: "stable",
            legacy_verifier=lambda **_kwargs: SimpleNamespace(
                migration_count=75,
                catalog_digest_sha256=HISTORICAL_DIGEST,
            ),
        )


def test_ci_accepts_first_private_append_from_authenticated_64838_base(
    tmp_path: Path,
) -> None:
    content = _candidate_content(AUTHENTICATED_BASE_SHA)
    current, entry = _non_empty_snapshot(
        tmp_path / "current", CURRENT_SHA, content
    )
    prior = _empty_snapshot(tmp_path / "prior", AUTHENTICATED_BASE_SHA)
    private_module = _private_module(_source_result(entry))

    result = catalog_ci.verify_ci(
        event_name="pull_request",
        current_sha=CURRENT_SHA,
        pull_request_base_sha=AUTHENTICATED_BASE_SHA,
        push_before_sha="",
        snapshot_factory=lambda sha: (
            current if sha == CURRENT_SHA else prior
        ),
        commit_parent_reader=lambda sha: (
            (AUTHENTICATED_BASE_SHA,) if sha == CURRENT_SHA else ()
        ),
        module_loader=lambda _repository: private_module,
        repository_witness=lambda _repository: "stable",
        legacy_verifier=_legacy_verifier,
    )

    assert result.private_migration_count == 1
    assert result.combined_migration_count == 76
    assert result.private_append_verified is True
    assert current.cleaned and prior.cleaned


def test_ci_accepts_unchanged_non_empty_head_after_base_advances(
    tmp_path: Path,
) -> None:
    content = _candidate_content(AUTHENTICATED_BASE_SHA)
    prior, entry = _non_empty_snapshot(
        tmp_path / "prior", ADVANCED_BASE_SHA, content
    )
    current, current_entry = _non_empty_snapshot(
        tmp_path / "current", ADVANCED_CURRENT_SHA, content
    )
    assert current_entry == entry

    class NoAppendAdapter:
        def validate_private_runtime_candidate(self, **_kwargs: object) -> None:
            raise AssertionError("unchanged private head must not be re-authored")

    private_module = _private_module(_source_result(entry))
    private_module.adapter = NoAppendAdapter()
    result = catalog_ci.verify_ci(
        event_name="pull_request",
        current_sha=ADVANCED_CURRENT_SHA,
        pull_request_base_sha=ADVANCED_BASE_SHA,
        push_before_sha="",
        snapshot_factory=lambda sha: (
            current if sha == ADVANCED_CURRENT_SHA else prior
        ),
        commit_parent_reader=lambda sha: (
            (ADVANCED_BASE_SHA,) if sha == ADVANCED_CURRENT_SHA else ()
        ),
        module_loader=lambda _repository: private_module,
        repository_witness=lambda _repository: "stable",
        legacy_verifier=_legacy_verifier,
    )

    assert result.private_migration_count == 1
    assert result.combined_migration_count == 76
    assert result.private_append_verified is False
    assert current.cleaned and prior.cleaned


def test_ci_rejects_new_private_header_based_on_wrong_sha(
    tmp_path: Path,
) -> None:
    wrong_sha = "e" * 40
    current, entry = _non_empty_snapshot(
        tmp_path / "current",
        CURRENT_SHA,
        _candidate_content(wrong_sha),
    )
    prior = _empty_snapshot(tmp_path / "prior", AUTHENTICATED_BASE_SHA)
    private_module = _private_module(_source_result(entry))

    with pytest.raises(catalog_ci.PrivateSourceError):
        catalog_ci.verify_ci(
            event_name="pull_request",
            current_sha=CURRENT_SHA,
            pull_request_base_sha=AUTHENTICATED_BASE_SHA,
            push_before_sha="",
            snapshot_factory=lambda sha: (
                current if sha == CURRENT_SHA else prior
            ),
            commit_parent_reader=lambda sha: (
                (AUTHENTICATED_BASE_SHA,) if sha == CURRENT_SHA else ()
            ),
            module_loader=lambda _repository: private_module,
            repository_witness=lambda _repository: "stable",
            legacy_verifier=_legacy_verifier,
        )

    assert current.cleaned and prior.cleaned


def test_ci_rejects_non_authenticated_prior_for_non_empty_head(
    tmp_path: Path,
) -> None:
    content = _candidate_content(AUTHENTICATED_BASE_SHA)
    prior, entry = _non_empty_snapshot(
        tmp_path / "prior", AUTHENTICATED_BASE_SHA, content
    )
    current, current_entry = _non_empty_snapshot(
        tmp_path / "current", CURRENT_SHA, content
    )
    assert current_entry == entry
    private_module = _private_module(_source_result(entry))

    with pytest.raises(catalog_ci.GitEvidenceError):
        catalog_ci.verify_ci(
            event_name="pull_request",
            current_sha=CURRENT_SHA,
            pull_request_base_sha=AUTHENTICATED_BASE_SHA,
            push_before_sha="",
            snapshot_factory=lambda sha: (
                current if sha == CURRENT_SHA else prior
            ),
            commit_parent_reader=lambda _sha: (),
            module_loader=lambda _repository: private_module,
            repository_witness=lambda _repository: "stable",
            legacy_verifier=_legacy_verifier,
        )

    assert current.cleaned and prior.cleaned


def test_workflow_requires_source_proof_and_real_pg17_receipt() -> None:
    workflow = (
        REPO_ROOT / ".github/workflows/private-runtime-catalog.yml"
    ).read_text(encoding="utf-8")
    receipt_verifier = (
        REPO_ROOT / "backend/scripts/verify_private_runtime_pg17_receipt.py"
    ).read_text(encoding="utf-8")
    proof_text = workflow + receipt_verifier
    for marker in (
        "verify_private_runtime_catalog_ci.py",
        "replay_private_runtime_catalog_pg17.py",
        "postgres:17.6-trixie@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929",
        "PG17_REPLAY_EXECUTED=true",
        "CROSS_TENANT_EVIDENCE=true",
        "COMBINED_CATALOG_MIGRATION_COUNT=76",
    ):
        assert marker in proof_text
    assert "verify_private_runtime_pg17_receipt.py" in workflow
    assert "migration_catalog_current_head_disposable" in workflow
    assert "migration_private_runtime_disposable" not in workflow
    assert "if: ${{ always() }}" in workflow
    assert "tuple(lines) != tuple(expected)" in receipt_verifier
    assert "len(lines) != len(set(lines))" in receipt_verifier


def test_workflow_runs_private_projection_pg17_matrix_without_suppression() -> None:
    workflow = (
        REPO_ROOT / ".github/workflows/private-runtime-catalog.yml"
    ).read_text(encoding="utf-8")
    marker = "  private-runtime-projection-pg17:"
    assert marker in workflow
    projection_job = workflow.split(marker, 1)[1]

    assert "needs: private-runtime-source" in projection_job
    assert (
        "postgres:17.6-trixie@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929"
        in projection_job
    )
    assert "POSTGRES_DB: private_runtime_projection_disposable" in projection_job
    assert (
        "RLS_TEST_DATABASE_URL: postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/"
        "private_runtime_projection_disposable"
        in projection_job
    )
    assert 'python-version: "3.13.14"' in projection_job
    assert "pip install --require-hashes -r requirements.lock" in projection_job
    assert "assert_disposable_database" in projection_job

    nodeids = (
        "tests/test_private_runtime_projection_pg17.py::test_private_runtime_projection_pg17",
        "tests/test_private_runtime_projection_pg17.py::test_private_runtime_projection_security_adversaries",
        "tests/test_private_runtime_projection_pg17.py::test_private_runtime_projection_rollback_atomicity",
    )
    assert sum(projection_job.count(nodeid) for nodeid in nodeids) == 3
    assert "--junitxml=$RUNNER_TEMP/private-runtime-projection-pg17.xml" not in projection_job
    assert '--junitxml="$report"' in projection_job
    assert "-o xfail_strict=true" in projection_job
    assert "if total != 11 or len(cases) != 11:" in projection_job
    assert "if skipped or failed or errors:" in projection_job
    assert "private-runtime-pg17.receipt" not in projection_job
    for forbidden in (
        "--disable-warnings",
        "--deselect",
        "--ignore",
        "--continue-on-collection-errors",
        "--lf",
        "--last-failed",
    ):
        assert forbidden not in projection_job

    # The authenticated source/replay job remains separate; the projection
    # matrix is additive and cannot silently replace the 75+1 proof.
    assert "  private-runtime-pg17:" in workflow
    assert "replay_private_runtime_catalog_pg17.py" in workflow
