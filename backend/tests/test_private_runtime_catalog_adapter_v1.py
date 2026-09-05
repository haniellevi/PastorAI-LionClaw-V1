from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_SHA = "648fa5aa0abcf15881110c3548a3ec6c381c289c"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


intent = _load(
    REPO_ROOT / "backend/scripts/private_runtime_intent_runtime_v1.py",
    "private_runtime_intent_runtime_v1_adapter_test",
)
adapter = _load(
    REPO_ROOT / "backend/scripts/private_runtime_catalog_adapter_v1.py",
    "private_runtime_catalog_adapter_v1_test",
)
catalog = _load(
    REPO_ROOT / "backend/scripts/private_runtime_catalog_v1.py",
    "private_runtime_catalog_v1_test",
)
author = _load(
    REPO_ROOT / "backend/scripts/private_runtime_migration_authoring_v1.py",
    "private_runtime_migration_authoring_v1_test",
)


def _candidate(name: str) -> bytes:
    value = intent.default_intent(basename=name, base_repository_sha=BASE_SHA)
    value["decision_refs"] = [
        "docs/decisions/2026-09-04-private-runtime-migration-policy-v2.md"
    ]
    value["recovery"] = {
        "kind": "FORWARD_COMPENSATION",
        "reference": "docs/decisions/2026-09-04-private-runtime-migration-policy-v2.md",
    }
    nodeid = "backend/tests/test_private_runtime_catalog_adapter_v1.py::test_adapter_accepts_private_candidate"
    value["pg17_test_nodeids"] = [nodeid]
    value["cross_tenant_test_nodeids"] = [nodeid]
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return (
        f"-- PASTORAI_MIGRATION_INTENT_V2={encoded}\n"
        "-- OPERATIONAL_AUTHORIZATION=BLOCKED\n"
        "-- NEXT_STAGE_AUTHORIZED=false\n"
        "begin;\n"
        "set local row_security = on;\n"
        "create role agent_projection_owner nologin noinherit nosuperuser nobypassrls;\n"
        "create policy agent_projection_owner_tenant_barrier on public.conversations\n"
        "  as restrictive for all to agent_projection_owner\n"
        "  using (igreja_id = agent_private.current_tenant_id())\n"
        "  with check (igreja_id = agent_private.current_tenant_id());\n"
        "create function agent_private.load_turn_context(uuid) returns table\n"
        "  (igreja_id uuid, conversation_id uuid, pessoa_id uuid,\n"
        "   conversation_state text, pessoa_optout boolean, pessoa_sem_interesse boolean)\n"
        "  language plpgsql stable strict security definer\n"
        "  set search_path = pg_catalog, agent_private\n"
        "  as $function$ begin return; end $function$;\n"
        "commit;\n"
    ).encode("ascii")


def test_adapter_accepts_private_candidate() -> None:
    name = "20260905_030000_private_runtime_adapter_synthetic.sql"
    candidate = adapter.validate_private_runtime_candidate(
        _candidate(name), basename=name, expected_sha=BASE_SHA
    )
    assert candidate.basename == name
    assert candidate.intent["scope"] == "PRIVATE_RUNTIME"
    assert len(candidate.content_sha256) == 64


def test_intent_binds_preserved_public_helper_execute_grant() -> None:
    controls = intent.default_private_runtime_controls()
    owner_grants = controls["acl"]["direct_projection_owner_grants"]
    assert "public.current_igreja_id()" in {
        item["object"] for item in owner_grants
    }
    assert "public.current_igreja_id()" in intent.default_intent(
        basename="20260905_030004_private_runtime_adapter_synthetic.sql",
        base_repository_sha=BASE_SHA,
    )["affected_objects"]
    web_helper_grant = next(
        item
        for item in owner_grants
        if item["object"] == "public.current_igreja_id()"
    )
    assert web_helper_grant == {
        "object": "public.current_igreja_id()",
        "grantee": "agent_projection_owner",
        "privilege": "EXECUTE",
        "grantable": False,
    }


def test_adapter_rejects_v1_claim_and_comment_decoys() -> None:
    name = "20260905_030001_private_runtime_adapter_synthetic.sql"
    content = _candidate(name)
    with pytest.raises(adapter.PrivateRuntimeCatalogAdapterError):
        adapter.validate_private_runtime_candidate(
            b"-- PASTORAI_MIGRATION_INTENT_V1={}\n" + content,
            basename=name,
            expected_sha=BASE_SHA,
        )
    decoy = content.replace(
        b"create role agent_projection_owner",
        b"-- create role agent_projection_owner",
        1,
    )
    with pytest.raises(adapter.PrivateRuntimeCatalogAdapterError):
        adapter.validate_private_runtime_candidate(
            decoy, basename=name, expected_sha=BASE_SHA
        )


def test_prepare_head_is_private_and_does_not_change_public_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_dir = tmp_path / "private_runtime"
    head_path = tmp_path / "private-runtime-catalog-head-v1.json"
    private_dir.mkdir()
    initial = catalog.default_head()
    head_path.write_bytes((json.dumps(initial, indent=2) + "\n").encode("ascii"))
    name = "20260905_030002_private_runtime_adapter_synthetic.sql"
    candidate_path = private_dir / name
    candidate_path.write_bytes(_candidate(name))
    candidate_path.chmod(0o600)

    public_before = (REPO_ROOT / "docs/governance/migrations/migration-catalog-head-v1.json").read_bytes()
    monkeypatch.setattr(author, "PRIVATE_DIR", private_dir)
    monkeypatch.setattr(author, "PRIVATE_HEAD_PATH", head_path)
    monkeypatch.setattr(author, "_git_head", lambda: BASE_SHA)
    monkeypatch.setattr(author, "_verify_public_baseline", lambda: None)

    prepared = author.prepare_head(name, expected_sha=BASE_SHA)
    resulting = json.loads(prepared.content.decode("ascii"))
    assert prepared.batch_id == "private-runtime-catalog-append-0001"
    assert resulting["historical_public_migration_count"] == 75
    assert resulting["current_head"]["private_migration_count"] == 1
    assert resulting["private_entries"][0]["name"] == name
    catalog.validate_head(resulting, scanned_entries=[resulting["private_entries"][0]])
    assert head_path.read_bytes() == (json.dumps(initial, indent=2) + "\n").encode("ascii")
    assert (REPO_ROOT / "docs/governance/migrations/migration-catalog-head-v1.json").read_bytes() == public_before


def test_draft_creates_incomplete_private_sql_without_public_head_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_dir = tmp_path / "private_runtime"
    head_path = tmp_path / "private-runtime-catalog-head-v1.json"
    private_dir.mkdir()
    head_path.write_bytes((json.dumps(catalog.default_head(), indent=2) + "\n").encode("ascii"))
    monkeypatch.setattr(author, "PRIVATE_DIR", private_dir)
    monkeypatch.setattr(author, "PRIVATE_HEAD_PATH", head_path)
    monkeypatch.setattr(author, "_git_head", lambda: BASE_SHA)
    monkeypatch.setattr(author, "_verify_public_baseline", lambda: None)

    name = author.create_draft("synthetic private adapter", expected_sha=BASE_SHA)
    content = (private_dir / name).read_bytes()
    assert name.endswith(".sql")
    assert (private_dir / name).stat().st_mode & 0o777 == 0o600
    assert b"PRIVATE_RUNTIME_MIGRATION_DRAFT_INCOMPLETE" in content
    with pytest.raises(adapter.PrivateRuntimeCatalogAdapterError):
        adapter.validate_private_runtime_candidate(content, basename=name, expected_sha=BASE_SHA)


def test_catalog_rejects_arbitrary_approved_prior() -> None:
    with pytest.raises(catalog.PrivateRuntimeCatalogError):
        catalog.validate_head(catalog.default_head(), approved_prior={"not": "a head"})


def test_catalog_rejects_sql_symlink_and_hardlink(tmp_path: Path) -> None:
    private_dir = tmp_path / "private_runtime"
    private_dir.mkdir()
    target = tmp_path / "outside.sql"
    target.write_bytes(b"select 1;\n")

    symlink = private_dir / "20260905_030003_symlink.sql"
    symlink.symlink_to(target)
    with pytest.raises(catalog.PrivateRuntimeCatalogError):
        catalog.scan_directory(private_dir)

    symlink.unlink()
    hardlink = private_dir / "20260905_030003_hardlink.sql"
    os.link(target, hardlink)
    with pytest.raises(catalog.PrivateRuntimeCatalogError):
        catalog.scan_directory(private_dir)


def test_catalog_rejects_unexpected_sidecar_file(tmp_path: Path) -> None:
    private_dir = tmp_path / "private_runtime"
    private_dir.mkdir()
    (private_dir / "README.txt").write_text("not a migration", encoding="ascii")
    with pytest.raises(catalog.PrivateRuntimeCatalogError):
        catalog.scan_directory(private_dir)


def test_catalog_rejects_symlinked_ancestor_and_json_link(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    private_dir = real_dir / "private_runtime"
    private_dir.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(real_dir, target_is_directory=True)
    with pytest.raises(catalog.PrivateRuntimeCatalogError):
        catalog.scan_directory(alias / "private_runtime")

    real_head = tmp_path / "head.json"
    real_head.write_bytes((json.dumps(catalog.default_head()) + "\n").encode("ascii"))
    linked_head = tmp_path / "linked-head.json"
    linked_head.symlink_to(real_head)
    with pytest.raises(catalog.PrivateRuntimeCatalogError):
        catalog.read_json(linked_head)


def test_private_head_schema_closes_nested_objects() -> None:
    schema = json.loads(
        (
            REPO_ROOT
            / "docs/governance/migrations/private-runtime-catalog-head-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    current = schema["$defs"]["currentHead"]
    assert current["additionalProperties"] is False
    assert set(current["required"]) == {
        "last_basename",
        "private_digest_sha256",
        "private_migration_count",
    }
    assert set(current["properties"]) == set(current["required"])
    limits = schema["$defs"]["limits"]
    assert limits["additionalProperties"] is False
    assert set(limits["required"]) == {
        "max_catalog_bytes",
        "max_catalog_files",
        "max_migration_bytes",
        "max_migrations_per_batch",
    }
    assert set(limits["properties"]) == set(limits["required"])
