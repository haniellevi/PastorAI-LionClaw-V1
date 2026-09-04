from __future__ import annotations

import ast
import copy
from dataclasses import dataclass
import datetime as dt
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from types import ModuleType
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "backend" / "scripts" / "new_migration.py"
REAL_MIGRATIONS_DIR = REPO_ROOT / "backend" / "migrations"
REAL_HEAD_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-catalog-head-v1.json"
)
REAL_SCHEMA_PATH = REAL_HEAD_PATH.with_name(
    "migration-catalog-head-v1.schema.json"
)


def _load_module() -> ModuleType:
    name = "migration_authoring_under_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


authoring = _load_module()


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    value = completed.stdout.decode("ascii").strip()
    assert authoring.GIT_SHA_RE.fullmatch(value)
    return value


@dataclass(frozen=True)
class Sandbox:
    migrations: Path
    head: Path
    schema: Path
    expected_sha: str


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    migrations = tmp_path / "backend" / "migrations"
    governance = tmp_path / "docs" / "governance" / "migrations"
    migrations.mkdir(parents=True)
    governance.mkdir(parents=True)
    for source in sorted(REAL_MIGRATIONS_DIR.glob("*.sql")):
        shutil.copyfile(source, migrations / source.name)
    head = governance / REAL_HEAD_PATH.name
    schema = governance / REAL_SCHEMA_PATH.name
    shutil.copyfile(REAL_HEAD_PATH, head)
    shutil.copyfile(REAL_SCHEMA_PATH, schema)
    monkeypatch.setattr(authoring, "MIGRATIONS_DIR", migrations)
    monkeypatch.setattr(authoring, "GOVERNANCE_DIR", governance)
    monkeypatch.setattr(authoring, "HEAD_PATH", head)
    monkeypatch.setattr(authoring, "SCHEMA_PATH", schema)
    expected_head = head.read_bytes()
    expected_schema = schema.read_bytes()
    expected_authoring = SCRIPT_PATH.read_bytes()
    expected_verifier = authoring.VERIFIER_PATH.read_bytes()

    expected_sha = _git_head()

    def repository_contract(received_sha: str) -> tuple[bytes, bytes, bytes, bytes]:
        if received_sha != expected_sha:
            raise authoring.RepositoryBindingError
        return (
            expected_head,
            expected_schema,
            expected_authoring,
            expected_verifier,
        )

    monkeypatch.setattr(authoring, "_repository_contract", repository_contract)
    return Sandbox(
        migrations=migrations,
        head=head,
        schema=schema,
        expected_sha=expected_sha,
    )


def _fixed_time(second: int = 0) -> dt.datetime:
    return dt.datetime(2026, 9, 4, 12, 0, second, tzinfo=dt.timezone.utc)


def _draft(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
    *,
    description: str = "add safe authoring example",
    second: int = 0,
) -> tuple[str, Path]:
    monkeypatch.setattr(authoring, "_utc_now", lambda: _fixed_time(second))
    basename = authoring.create_draft(
        description, expected_sha=sandbox.expected_sha
    )
    return basename, sandbox.migrations / basename


def _complete(
    path: Path,
    sandbox: Sandbox,
    *,
    scope: str = "TENANT",
) -> bytes:
    text = path.read_text(encoding="ascii")
    first_line, body = text.split("\n", 1)
    assert first_line.startswith(authoring.INTENT_PREFIX)
    intent = authoring.catalog._decode_json(
        first_line[len(authoring.INTENT_PREFIX):].encode("ascii")
    )
    decision = "docs/decisions/2026-09-02-migration-catalog-evolution.md"
    nodeid = (
        "backend/tests/test_cell_requests_create_concurrency.py::"
        "test_create_different_churches_do_not_collide"
    )
    intent["affected_relations"] = ["public.authoring_test"]
    intent["decision_refs"] = [decision]
    intent["pg17_test_nodeids"] = [nodeid]
    intent["recovery"] = {
        "kind": "FORWARD_COMPENSATION",
        "reference": decision,
    }
    intent["scope"] = scope
    if scope == "TENANT":
        intent["cross_tenant_test_nodeids"] = [nodeid]
        intent["global_justification"] = None
        intent["tenant_controls"] = {
            "acl_review": "EXPLICIT_GRANTS_AND_REVOKES",
            "enable_rls": True,
            "force_rls": True,
            "igreja_id_column": "igreja_id",
            "policy_context": "app.tenant_igreja_id",
        }
    else:
        intent["cross_tenant_test_nodeids"] = []
        intent["global_justification"] = "Global catalog control table."
        intent["tenant_controls"] = None
    first_line = authoring.INTENT_PREFIX + json.dumps(
        intent,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    text = first_line + "\n" + body
    text = text.replace("-- MIGRATION_DRAFT_INCOMPLETE\n", "")
    text += (
        "create table authoring_test "
        "(id uuid primary key, igreja_id uuid not null);\n"
        "alter table authoring_test enable row level security;\n"
        "alter table authoring_test force row level security;\n"
        "revoke all on authoring_test from public;\n"
    )
    content = text.encode("ascii")
    path.write_bytes(content)
    return content


def _decoded(path: Path) -> dict[str, Any]:
    return authoring.catalog._decode_json(path.read_bytes())


def _rewrite_intent(path: Path, mutator: Any) -> None:
    text = path.read_text(encoding="utf-8")
    first_line, body = text.split("\n", 1)
    intent = authoring.catalog._decode_json(
        first_line[len(authoring.INTENT_PREFIX):].encode("ascii")
    )
    mutator(intent)
    encoded = json.dumps(
        intent,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    path.write_text(
        authoring.INTENT_PREFIX + encoded + "\n" + body,
        encoding="utf-8",
    )


def test_slugify_is_bounded_ascii_and_never_falls_back() -> None:
    assert authoring.slugify("Adicionar coração à célula") == (
        "adicionar_coracao_a_celula"
    )
    for invalid in ("", "   ", "🔥", "line\nbreak", "x" * 161):
        with pytest.raises(authoring.UsageError):
            authoring.slugify(invalid)


def test_versioned_head_serialization_is_initially_byte_identical() -> None:
    raw = REAL_HEAD_PATH.read_bytes()
    head = authoring.catalog._decode_json(raw)
    assert authoring._serialize_head(head, raw) == raw


def test_draft_creates_one_private_source_and_leaves_contract_unchanged(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior_head = sandbox.head.read_bytes()
    prior_schema = sandbox.schema.read_bytes()

    basename, path = _draft(sandbox, monkeypatch)

    assert path.name == basename
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    content = path.read_bytes()
    assert content.startswith(authoring.INTENT_PREFIX.encode("ascii"))
    assert b"MIGRATION_DRAFT_INCOMPLETE" in content
    assert b"OPERATIONAL_AUTHORIZATION=BLOCKED" in content
    assert b"NEXT_STAGE_AUTHORIZED=false" in content
    assert b"Never apply it manually" in content
    assert sandbox.head.read_bytes() == prior_head
    assert sandbox.schema.read_bytes() == prior_schema
    with pytest.raises(authoring.catalog.CatalogDriftError):
        authoring.catalog.validate_head(
            _decoded(sandbox.head),
            scanned_catalog=authoring.catalog._scan_catalog(
                sandbox.migrations
            ),
            _approved_snapshot=True,
        )


def test_legacy_one_step_cli_is_rejected_without_creating_a_file(
    sandbox: Sandbox, capsys: pytest.CaptureFixture[str]
) -> None:
    before = sorted(sandbox.migrations.iterdir())
    assert authoring.main(["unsafe old invocation"]) == 2
    assert sorted(sandbox.migrations.iterdir()) == before
    output = capsys.readouterr()
    assert "--expected-repository-sha" in output.err
    assert "RESULT=BLOCKED_MIGRATION_AUTHORING:USAGE" in output.out
    assert authoring.OPERATIONAL_BLOCK in output.out
    assert authoring.NEXT_STAGE_BLOCK in output.out


def test_draft_cli_reports_source_only_closed_state(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(authoring, "_utc_now", lambda: _fixed_time())
    result = authoring.main(
        [
            "draft",
            "--expected-repository-sha",
            sandbox.expected_sha,
            "new tenant table",
        ]
    )
    assert result == 0
    output = capsys.readouterr().out
    assert "RESULT=MIGRATION_DRAFT_CREATED" in output
    assert "CATALOG_HEAD_UPDATE_REQUIRED=true" in output
    assert authoring.OPERATIONAL_BLOCK in output
    assert authoring.NEXT_STAGE_BLOCK in output
    assert str(sandbox.migrations.parent) not in output


def test_structured_tenant_intent_is_accepted(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    basename, path = _draft(sandbox, monkeypatch)
    _complete(path, sandbox, scope="TENANT")

    candidate = authoring.prepare_head(
        basename, expected_sha=sandbox.expected_sha
    )

    assert candidate.batch_id == "migration-catalog-append-0001"
    assert sandbox.head.read_bytes() == REAL_HEAD_PATH.read_bytes()


def test_structured_global_intent_is_rejected_by_tenant_only_v1_boundary(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    basename, path = _draft(sandbox, monkeypatch)
    _complete(path, sandbox, scope="GLOBAL")

    with pytest.raises(authoring.DraftIncompleteError):
        authoring.prepare_head(basename, expected_sha=sandbox.expected_sha)


def test_global_intent_with_empty_relation_list_is_still_rejected(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    basename, path = _draft(sandbox, monkeypatch)
    _complete(path, sandbox, scope="GLOBAL")
    _rewrite_intent(path, lambda intent: intent.update({"affected_relations": []}))

    with pytest.raises(authoring.DraftIncompleteError):
        authoring.prepare_head(basename, expected_sha=sandbox.expected_sha)


@pytest.mark.parametrize(
    "protected",
    (
        "backend/.env",
        "backend/.env.production",
        "backend/.envrc",
        "backend/.environment",
        "docs/decisions/2026-09-04-private.pem",
        "docs/decisions/2026-09-04-private.key",
        "docs/secrets/operator.md",
        "backend/scripts/clerk_export.py",
        "backend/scripts/target_users_prod.json",
        "backend/scripts/migrate_clerk_production.py",
        "docs/dumps/production.dump",
        "docs/backups/production.sql",
        "docs/media/pastoral-call.mp3",
        "docs/decisions/id_rsa_recovery.md",
    ),
)
def test_protected_references_are_denied_before_any_reader_call(
    monkeypatch: pytest.MonkeyPatch,
    protected: str,
) -> None:
    reads = 0

    def forbidden_reader(*_args: object, **_kwargs: object) -> object:
        nonlocal reads
        reads += 1
        raise AssertionError("protected paths must not reach stat/open")

    monkeypatch.setattr(authoring.catalog, "_read_stable_file", forbidden_reader)

    relative = Path(protected)
    assert authoring._is_protected_repository_path(relative) is True
    assert authoring._stable_repository_reference(
        protected, reference_kind="decision"
    ) is False
    assert authoring._stable_repository_reference(
        protected, reference_kind="recovery"
    ) is False
    assert reads == 0


@pytest.mark.parametrize(
    "path",
    (
        "backups/production.sql",
        "docs/dumps/live.dump",
        "exports/people.csv",
        "docs/media/pastoral-call.mp3",
        "backend/.env.production",
        "backend/scripts/clerk_export.py",
    ),
)
def test_snapshot_manifest_rejects_sensitive_paths_before_archive(
    path: str,
) -> None:
    manifest = (
        b"100644 blob "
        + b"a" * 40
        + b" 12\t"
        + path.encode("utf-8")
        + b"\x00"
    )

    with pytest.raises(authoring.trusted_snapshot.GitEvidenceError):
        authoring._reject_protected_snapshot_manifest(manifest)


def test_snapshot_manifest_keeps_public_and_sanitized_product_images() -> None:
    manifest = (
        b"100644 blob "
        + b"a" * 40
        + b" 12\tfrontend/public/icon-192.png\x00"
        + b"100644 blob "
        + b"b" * 40
        + b" 12\tdocs/research/login-sanitizado.jpg\x00"
    )

    authoring._reject_protected_snapshot_manifest(manifest)


def test_reference_kinds_have_separate_canonical_allowlists() -> None:
    decision = "docs/decisions/2026-09-02-migration-catalog-evolution.md"
    runbook = "docs/ops/PRODUCTION-RUNBOOK.md"

    assert authoring._stable_repository_reference(
        decision, reference_kind="decision"
    )
    assert authoring._stable_repository_reference(
        decision, reference_kind="recovery"
    )
    assert not authoring._stable_repository_reference(
        runbook, reference_kind="decision"
    )
    assert authoring._stable_repository_reference(
        runbook, reference_kind="recovery"
    )
    assert not authoring._stable_repository_reference(
        "docs/ai/AI-BOOTSTRAP.md", reference_kind="decision"
    )


def test_declared_test_requires_rls_marker_on_function_or_module() -> None:
    assert authoring._valid_test_nodeid(
        "backend/tests/test_cell_requests_create_concurrency.py::"
        "test_create_different_churches_do_not_collide"
    )
    assert authoring._valid_test_nodeid(
        "backend/tests/test_apply_migrations.py::"
        "test_bootstrap_ledger_creates_exact_owner_only_contract_and_rerun_is_noop"
    )
    assert not authoring._valid_test_nodeid(
        "backend/tests/test_new_migration.py::"
        "test_structured_tenant_intent_is_accepted"
    )


@pytest.mark.parametrize(
    "source",
    (
        "def test_case():\n    pass\n",
        "import pytest\n@pytest.mark.rls_integration\n"
        "@pytest.mark.skip\ndef test_case():\n    pass\n",
        "import pytest\n@pytest.mark.rls_integration\n"
        "@pytest.mark.xfail\ndef test_case():\n    pass\n",
        "import pytest\n@pytest.mark.rls_integration\n"
        "def test_case():\n    pytest.skip('not executed')\n",
        "import pytest\npytestmark = [pytest.mark.rls_integration, "
        "pytest.mark.skipif(True)]\ndef test_case():\n    pass\n",
    ),
)
def test_declared_test_rejects_unmarked_skip_and_xfail_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    root = tmp_path / "repository"
    path = root / "backend" / "tests" / "test_declared.py"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    monkeypatch.setattr(authoring, "REPO_ROOT", root)

    assert not authoring._valid_test_nodeid(
        "backend/tests/test_declared.py::test_case"
    )


def test_block_comment_is_not_mistaken_for_sql(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    basename, path = _draft(sandbox, monkeypatch)
    completed = _complete(path, sandbox)
    prefix = completed.split(b"create table authoring_test", 1)[0]
    path.write_bytes(prefix + b"/* prose only; nested /* still */ comment */\n")

    with pytest.raises(authoring.DraftIncompleteError):
        authoring.prepare_head(basename, expected_sha=sandbox.expected_sha)


@pytest.mark.parametrize(
    "mutator",
    (
        lambda intent: intent.pop("decision_refs"),
        lambda intent: intent.update({"operational_authorization": True}),
        lambda intent: intent["tenant_controls"].update({"force_rls": False}),
        lambda intent: intent["tenant_controls"].update({"enable_rls": 1}),
        lambda intent: intent["tenant_controls"].update({"force_rls": 1}),
        lambda intent: intent.update({"cross_tenant_test_nodeids": []}),
        lambda intent: intent.update(
            {"pg17_test_nodeids": ["backend/tests/test_missing.py::test_missing"]}
        ),
        lambda intent: intent.update({"decision_refs": ["../outside.md"]}),
        lambda intent: intent.update(
            {"recovery": {"kind": "ROLLBACK", "reference": "TODO"}}
        ),
        lambda intent: intent.update({"affected_relations": []}),
        lambda intent: intent.update(
            {"affected_relations": ["public.valid", "private.secret"]}
        ),
        lambda intent: intent.update(
            {
                "pg17_test_nodeids": [
                    "backend/tests/test_new_migration.py::"
                    "test_structured_tenant_intent_is_accepted"
                ],
                "cross_tenant_test_nodeids": [
                    "backend/tests/test_new_migration.py::"
                    "test_structured_tenant_intent_is_accepted"
                ],
            }
        ),
    ),
)
def test_structured_intent_rejects_missing_or_unverifiable_controls(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
    mutator: Any,
) -> None:
    basename, path = _draft(sandbox, monkeypatch)
    _complete(path, sandbox)
    _rewrite_intent(path, mutator)

    with pytest.raises(authoring.DraftIncompleteError):
        authoring.prepare_head(basename, expected_sha=sandbox.expected_sha)


def test_prepare_head_builds_exactly_one_valid_longitudinal_batch(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior_content = sandbox.head.read_bytes()
    prior_head = _decoded(sandbox.head)
    basename, path = _draft(sandbox, monkeypatch)
    migration_content = _complete(path, sandbox)

    candidate = authoring.prepare_head(
        basename, expected_sha=sandbox.expected_sha
    )

    assert candidate.batch_id == "migration-catalog-append-0001"
    assert candidate.previous_approved_head_sha256 == hashlib.sha256(
        prior_content
    ).hexdigest()
    assert candidate.content_sha256 == hashlib.sha256(candidate.content).hexdigest()
    assert sandbox.head.read_bytes() == prior_content
    current = authoring.catalog._decode_json(candidate.content)
    assert current["operational_authorization"] is False
    assert current["next_stage_authorized"] is False
    assert current["previous_approved_head_sha256"] == (
        candidate.previous_approved_head_sha256
    )
    assert current["current_head"]["migration_count"] == 76
    assert current["current_head"]["last_basename"] == basename
    batch = current["append_only_batches"][-1]
    assert batch["batch_id"] == candidate.batch_id
    assert batch["sequence"] == 1
    assert batch["entries"] == [
        {
            "name": basename,
            "position": 75,
            "sha256": hashlib.sha256(migration_content).hexdigest(),
            "size_bytes": len(migration_content),
        }
    ]
    approved = authoring.catalog.ApprovedPriorHead(
        content_sha256=candidate.previous_approved_head_sha256,
        head=prior_head,
    )
    scanned = authoring.catalog._scan_catalog(sandbox.migrations)
    assert authoring.catalog.validate_head(
        current,
        scanned_catalog=scanned,
        approved_prior=approved,
    ) == scanned


def test_prepare_head_preserves_historical_prefix_bytes(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = sandbox.head.read_bytes()
    marker = b'  "append_only_batches":'
    prefix = prior[: prior.index(marker)]
    basename, path = _draft(sandbox, monkeypatch)
    _complete(path, sandbox)

    candidate = authoring.prepare_head(
        basename, expected_sha=sandbox.expected_sha
    )

    assert candidate.content.startswith(prefix)
    assert sandbox.head.read_bytes() == prior
    assert sandbox.schema.read_bytes() == REAL_SCHEMA_PATH.read_bytes()
    assert authoring.catalog._decode_json(candidate.content)["historical_prefix"] == (
        authoring.catalog._decode_json(prior)["historical_prefix"]
    )


def test_prepare_head_cli_keeps_approval_and_operation_closed(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    basename, path = _draft(sandbox, monkeypatch)
    _complete(path, sandbox)
    result = authoring.main(
        [
            "prepare-head",
            "--expected-repository-sha",
            sandbox.expected_sha,
            basename,
        ]
    )
    assert result == 0
    output = capsys.readouterr().out
    assert "RESULT=MIGRATION_APPEND_CANDIDATE_PREPARED" in output
    assert "APPEND_BATCH_ID=migration-catalog-append-0001" in output
    assert authoring.OPERATIONAL_BLOCK in output
    assert authoring.NEXT_STAGE_BLOCK in output
    assert "APPROVED=true" not in output
    assert "CATALOG_HEAD_UPDATE_PERFORMED=false" in output
    encoded = next(
        line.split("=", 1)[1]
        for line in output.splitlines()
        if line.startswith("HEAD_CANDIDATE_CONTENT_BASE64=")
    )
    decoded = base64.b64decode(encoded, validate=True)
    assert hashlib.sha256(decoded).hexdigest() in output
    assert sandbox.head.read_bytes() == REAL_HEAD_PATH.read_bytes()
    assert str(sandbox.head.parent) not in output


@pytest.mark.parametrize(
    "mutation",
    [
        lambda content: content,
        lambda content: content.replace(
            b"MIGRATION_DRAFT_INCOMPLETE", b""
        ),
        lambda content: b"\xff" + content.replace(b"TODO", b"done"),
        lambda content: b"\x00" + content.replace(b"TODO", b"done"),
    ],
)
def test_prepare_head_rejects_incomplete_or_invalid_source(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
    mutation: Any,
) -> None:
    prior = sandbox.head.read_bytes()
    basename, path = _draft(sandbox, monkeypatch)
    path.write_bytes(mutation(path.read_bytes()))

    with pytest.raises(authoring.DraftIncompleteError):
        authoring.prepare_head(basename, expected_sha=sandbox.expected_sha)

    assert sandbox.head.read_bytes() == prior


def test_prepare_head_rejects_zero_or_two_terminal_additions(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(authoring.AuthoringError):
        authoring.prepare_head(
            "20260904_120000_missing.sql",
            expected_sha=sandbox.expected_sha,
        )

    first, first_path = _draft(sandbox, monkeypatch)
    _complete(first_path, sandbox)
    second = "20260904_120001_second.sql"
    (sandbox.migrations / second).write_text("select 2;\n", encoding="ascii")
    with pytest.raises(authoring.AuthoringError):
        authoring.prepare_head(first, expected_sha=sandbox.expected_sha)


def test_repository_sha_and_contract_bytes_are_mandatory(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(authoring, "_utc_now", lambda: _fixed_time())
    with pytest.raises(authoring.RepositoryBindingError):
        authoring.create_draft(
            "wrong sha",
            expected_sha="1" * len(sandbox.expected_sha),
        )

    sandbox.head.write_bytes(sandbox.head.read_bytes() + b"\n")
    with pytest.raises(authoring.RepositoryBindingError):
        authoring.create_draft(
            "dirty head", expected_sha=sandbox.expected_sha
        )


def test_dirty_schema_is_rejected_before_draft(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(authoring, "_utc_now", lambda: _fixed_time())
    sandbox.schema.write_bytes(sandbox.schema.read_bytes() + b"\n")
    with pytest.raises(authoring.RepositoryBindingError):
        authoring.create_draft(
            "dirty schema", expected_sha=sandbox.expected_sha
        )


def test_clock_rollback_and_existing_tail_block_draft(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        authoring,
        "_utc_now",
        lambda: dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    )
    with pytest.raises(authoring.AuthoringError):
        authoring.create_draft(
            "clock rollback", expected_sha=sandbox.expected_sha
        )

    monkeypatch.setattr(authoring, "_utc_now", lambda: _fixed_time())
    orphan = sandbox.migrations / "20260904_115959_orphan.sql"
    orphan.write_text("select 1;\n", encoding="ascii")
    with pytest.raises(authoring.AuthoringError):
        authoring.create_draft(
            "second orphan", expected_sha=sandbox.expected_sha
        )


def test_exclusive_creation_never_follows_or_truncates_symlink(
    sandbox: Sandbox,
) -> None:
    target = sandbox.migrations.parent / "protected.txt"
    target.write_bytes(b"do not overwrite")
    basename = "20260904_120000_symlink.sql"
    (sandbox.migrations / basename).symlink_to(target)

    with pytest.raises(authoring.DraftCollisionError):
        authoring._create_file_exclusive(
            sandbox.migrations, basename, b"select 1;\n"
        )

    assert target.read_bytes() == b"do not overwrite"


def test_exclusive_creation_never_truncates_existing_regular_file(
    sandbox: Sandbox,
) -> None:
    basename = "20260904_120000_existing.sql"
    path = sandbox.migrations / basename
    path.write_bytes(b"preserve me")

    with pytest.raises(authoring.DraftCollisionError):
        authoring._create_file_exclusive(
            sandbox.migrations, basename, b"replacement"
        )

    assert path.read_bytes() == b"preserve me"


def test_hardlinked_candidate_is_rejected(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    basename, path = _draft(sandbox, monkeypatch)
    _complete(path, sandbox)
    os.link(path, sandbox.migrations.parent / "second-link.sql")
    prior = sandbox.head.read_bytes()

    with pytest.raises(authoring.catalog.CatalogDriftError):
        authoring.prepare_head(basename, expected_sha=sandbox.expected_sha)

    assert sandbox.head.read_bytes() == prior


def test_lock_collision_blocks_without_touching_catalog(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = sandbox.head.read_bytes()
    monkeypatch.setattr(authoring, "_utc_now", lambda: _fixed_time())
    descriptor = os.open(sandbox.head.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(authoring.AuthoringError):
            authoring.create_draft(
                "blocked writer", expected_sha=sandbox.expected_sha
            )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    assert sandbox.head.read_bytes() == prior


def test_prepare_head_never_publishes_or_calls_replace(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    basename, path = _draft(sandbox, monkeypatch)
    _complete(path, sandbox)
    prior = sandbox.head.read_bytes()
    monkeypatch.setattr(
        authoring.os,
        "replace",
        lambda *_args, **_kwargs: pytest.fail("prepare-head must not publish"),
    )

    candidate = authoring.prepare_head(
        basename, expected_sha=sandbox.expected_sha
    )

    assert candidate.content != prior
    assert sandbox.head.read_bytes() == prior


def test_contract_change_before_final_validation_is_detected(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    basename, path = _draft(sandbox, monkeypatch)
    _complete(path, sandbox)
    prior_head = sandbox.head.read_bytes()
    external_schema = sandbox.schema.read_bytes() + b"\n"
    original_check = authoring._require_contract_unchanged

    def raced_check(state: object, expected_sha: str) -> None:
        sandbox.schema.write_bytes(external_schema)
        original_check(state, expected_sha)

    monkeypatch.setattr(authoring, "_require_contract_unchanged", raced_check)
    with pytest.raises(authoring.RepositoryBindingError):
        authoring.prepare_head(basename, expected_sha=sandbox.expected_sha)
    assert sandbox.head.read_bytes() == prior_head
    assert sandbox.schema.read_bytes() == external_schema


def test_partial_draft_failure_preserves_own_inode_for_explicit_recovery(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    basename = "20260904_120000_partial.sql"
    path = sandbox.migrations / basename

    def failed_write(descriptor: int, _content: bytes) -> None:
        os.write(descriptor, b"partial")
        raise authoring.AuthoringIoError

    monkeypatch.setattr(authoring, "_write_all", failed_write)
    with pytest.raises(authoring.AuthoringIoError):
        authoring._create_file_exclusive(
            sandbox.migrations, basename, b"complete content"
        )

    assert path.read_bytes() == b"partial"


def test_second_longitudinal_append_preserves_prior_batch(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, first_path = _draft(sandbox, monkeypatch)
    _complete(first_path, sandbox)
    first_candidate = authoring.prepare_head(
        first, expected_sha=sandbox.expected_sha
    )
    first_head_content = first_candidate.content
    first_head = authoring.catalog._decode_json(first_head_content)
    sandbox.head.write_bytes(first_head_content)
    script_content = SCRIPT_PATH.read_bytes()
    verifier_content = authoring.VERIFIER_PATH.read_bytes()

    monkeypatch.setattr(
        authoring,
        "_repository_contract",
        lambda _sha: (
            first_head_content,
            sandbox.schema.read_bytes(),
            script_content,
            verifier_content,
        ),
    )
    second, second_path = _draft(
        sandbox,
        monkeypatch,
        description="second safe append",
        second=1,
    )
    _complete(second_path, sandbox)
    second_candidate = authoring.prepare_head(
        second, expected_sha=sandbox.expected_sha
    )

    current = authoring.catalog._decode_json(second_candidate.content)
    assert current["append_only_batches"][:-1] == (
        first_head["append_only_batches"]
    )
    assert current["append_only_batches"][-1]["sequence"] == 2
    assert current["previous_approved_head_sha256"] == hashlib.sha256(
        first_head_content
    ).hexdigest()
    approved = authoring.catalog.ApprovedPriorHead(
        content_sha256=hashlib.sha256(first_head_content).hexdigest(),
        head=first_head,
    )
    scanned = authoring.catalog._scan_catalog(sandbox.migrations)
    assert authoring.catalog.validate_head(
        current,
        scanned_catalog=scanned,
        approved_prior=approved,
    ) == scanned


def test_script_static_smoke_uses_sanitized_snapshot_and_no_database_imports() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])

    assert imports.isdisjoint(
        {
            "http",
            "httpx",
            "psycopg",
            "requests",
            "socket",
            "sqlalchemy",
            "urllib",
        }
    )
    for forbidden in (
        "os.environ",
        "os.getenv",
        "M06_MIGRATION_DATABASE_URL",
        "apply_migrations",
        "git push",
        "git fetch",
        '"merge-base"',
    ):
        assert forbidden not in source
    assert "os.replace" not in source
    assert "os.unlink" not in source
    assert "CATALOG_HEAD_UPDATE_PERFORMED=false" in source
    assert "GIT_OBJECT_DIRECTORY" in source
    assert "GIT_CONFIG_COUNT" in source
    assert "GIT_ALTERNATE_OBJECT_DIRECTORIES" in source
    assert "_create_repository_snapshot" in source
    assert authoring.CATALOG_VERIFIER_SHA256 == hashlib.sha256(
        authoring.VERIFIER_PATH.read_bytes()
    ).hexdigest()
    assert authoring.TRUSTED_SNAPSHOT_SHA256 == hashlib.sha256(
        authoring.TRUSTED_SNAPSHOT_PATH.read_bytes()
    ).hexdigest()
