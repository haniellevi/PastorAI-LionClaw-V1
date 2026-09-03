from __future__ import annotations

import ast
from collections import Counter
import copy
from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "backend" / "scripts" / "verify_migration_catalog_head.py"
HEAD_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-catalog-head-v1.json"
)
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-catalog-head-v1.schema.json"
)


def _load_module() -> ModuleType:
    name = "migration_catalog_head_verifier"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


verifier = _load_module()


def _head() -> dict[str, Any]:
    return verifier._decode_json(HEAD_PATH.read_bytes())


def _schema() -> dict[str, Any]:
    return verifier._decode_json(SCHEMA_PATH.read_bytes())


def _serialized_head(head: dict[str, Any]) -> bytes:
    return (
        json.dumps(head, ensure_ascii=True, indent=2) + "\n"
    ).encode("ascii")


def _approved(head: dict[str, Any]) -> Any:
    content = _serialized_head(head)
    return verifier.ApprovedPriorHead(
        content_sha256=hashlib.sha256(content).hexdigest(),
        head=copy.deepcopy(head),
    )


def _append_batches(
    head: dict[str, Any], additions: list[tuple[str, bytes]]
) -> list[dict[str, Any]]:
    prior_sha256 = _approved(head).content_sha256
    reconstructed = verifier.validate_head(head, _approved_snapshot=True)
    previous_digest = head["current_head"]["digest_sha256"]
    batches = copy.deepcopy(head["append_only_batches"])
    first_sequence = len(batches) + 1
    for sequence, (name, content) in enumerate(
        additions, start=first_sequence
    ):
        entry = {
            "name": name,
            "position": len(reconstructed),
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        reconstructed.append(entry)
        resulting_digest = verifier._catalog_digest(reconstructed)
        batches.append(
            {
                "batch_id": f"migration-catalog-append-{sequence:04d}",
                "entries": [entry],
                "previous_catalog_digest_sha256": previous_digest,
                "resulting_catalog_digest_sha256": resulting_digest,
                "sequence": sequence,
            }
        )
        previous_digest = resulting_digest
    head["append_only_batches"] = batches
    head["previous_approved_head_sha256"] = prior_sha256
    head["current_head"] = {
        "digest_sha256": previous_digest,
        "last_basename": reconstructed[-1]["name"],
        "migration_count": len(reconstructed),
    }
    return reconstructed


def _recompute_chain(head: dict[str, Any]) -> list[dict[str, Any]]:
    reconstructed = copy.deepcopy(head["historical_prefix"]["entries"])
    previous_digest = head["historical_prefix"]["digest_sha256"]
    for sequence, batch in enumerate(head["append_only_batches"], start=1):
        batch["sequence"] = sequence
        batch["batch_id"] = f"migration-catalog-append-{sequence:04d}"
        batch["previous_catalog_digest_sha256"] = previous_digest
        for entry in batch["entries"]:
            entry["position"] = len(reconstructed)
            reconstructed.append(entry)
        previous_digest = verifier._catalog_digest(reconstructed)
        batch["resulting_catalog_digest_sha256"] = previous_digest
    head["current_head"] = {
        "digest_sha256": previous_digest,
        "last_basename": reconstructed[-1]["name"],
        "migration_count": len(reconstructed),
    }
    return reconstructed


def _write_sql(directory: Path, name: str, content: bytes = b"select 1;\n") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(content)
    return path


def test_versioned_head_verifies_real_catalog_and_keeps_gates_closed(
    capsys: Any,
) -> None:
    assert verifier.main([]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.splitlines() == [
        "RESULT=MIGRATION_CATALOG_HEAD_VERIFIED_OFFLINE",
        "CATALOG_MIGRATION_COUNT=75",
        "CATALOG_DIGEST_SHA256="
        "84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f",
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "NEXT_STAGE_AUTHORIZED=false",
    ]

def test_initial_head_is_exact_historical_prefix() -> None:
    head = _head()
    scanned = verifier._scan_catalog()

    assert head["append_only_batches"] == []
    assert head["historical_prefix"]["migration_count"] == 75
    assert head["historical_prefix"]["entries"] == scanned
    assert head["current_head"] == {
        "digest_sha256": verifier.HISTORICAL_DIGEST_SHA256,
        "last_basename": verifier.HISTORICAL_LAST_BASENAME,
        "migration_count": 75,
    }
    assert head["operational_authorization"] is False
    assert head["next_stage_authorized"] is False


def test_versioned_schema_is_exact_and_every_object_is_closed() -> None:
    schema = _schema()
    assert verifier._exact_json(schema, verifier._expected_schema())

    stack: list[Any] = [schema]
    while stack:
        node = stack.pop()
        if type(node) is dict:
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
            stack.extend(node.values())
        elif type(node) is list:
            stack.extend(node)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update({"extra": False}),
        lambda value: value["limits"].update({"extra": 1}),
        lambda value: value["historical_prefix"].update({"extra": 1}),
        lambda value: value["current_head"].update({"extra": 1}),
        lambda value: value.update({"operational_authorization": True}),
        lambda value: value.update({"next_stage_authorized": True}),
        lambda value: value["limits"].update({"max_catalog_files": True}),
        lambda value: value["historical_prefix"].update(
            {"migration_count": True}
        ),
        lambda value: value["historical_prefix"]["entries"][0].update(
            {"position": False}
        ),
        lambda value: value["historical_prefix"]["entries"][0].update(
            {"size_bytes": True}
        ),
        lambda value: value["historical_prefix"]["entries"][0].update(
            {"sha256": "0" * 64}
        ),
        lambda value: value["historical_prefix"]["entries"][0].update(
            {"size_bytes": 1}
        ),
        lambda value: value["historical_prefix"]["entries"][0].update(
            {"name": "0000_rewritten.sql"}
        ),
        lambda value: value["historical_prefix"].update(
            {"digest_sha256": "0" * 64}
        ),
        lambda value: value["historical_prefix"]["entries"].pop(),
        lambda value: value["historical_prefix"]["entries"].reverse(),
    ],
)
def test_historical_prefix_limits_and_gates_are_immutable(mutator: Any) -> None:
    head = copy.deepcopy(_head())
    mutator(head)

    with pytest.raises(verifier.VerificationError):
        verifier.validate_head(head)


def test_one_future_append_batch_is_reconstructable_and_verifiable() -> None:
    head = copy.deepcopy(_head())
    prior = _approved(head)
    reconstructed = _append_batches(
        head,
        [("20260902_120000_append_only_example.sql", b"select 1;\n")],
    )

    assert verifier.validate_head(
        head,
        scanned_catalog=reconstructed,
        approved_prior=prior,
    ) == reconstructed
    batch = head["append_only_batches"][0]
    assert batch["previous_catalog_digest_sha256"] == (
        verifier.HISTORICAL_DIGEST_SHA256
    )
    assert batch["resulting_catalog_digest_sha256"] == (
        head["current_head"]["digest_sha256"]
    )


def test_future_append_verifies_end_to_end_against_temporary_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head = copy.deepcopy(_head())
    prior_content = _serialized_head(head)
    name = "20260902_120000_append_only_example.sql"
    content = b"select 1;\n"
    reconstructed = _append_batches(head, [(name, content)])
    catalog = tmp_path / "migrations"
    catalog.mkdir()
    for entry in reconstructed[:-1]:
        source = verifier.MIGRATIONS_DIR / entry["name"]
        (catalog / entry["name"]).write_bytes(source.read_bytes())
    (catalog / name).write_bytes(content)
    head_path = tmp_path / "head.json"
    schema_path = tmp_path / "schema.json"
    head_path.write_text(
        json.dumps(head, ensure_ascii=True, indent=2) + "\n", encoding="ascii"
    )
    schema_path.write_text(
        json.dumps(_schema(), ensure_ascii=True, indent=2) + "\n",
        encoding="ascii",
    )
    monkeypatch.setattr(verifier, "HEAD_PATH", head_path)
    monkeypatch.setattr(verifier, "SCHEMA_PATH", schema_path)
    monkeypatch.setattr(verifier, "MIGRATIONS_DIR", catalog)
    prior_path = tmp_path / "prior.json"
    prior_path.write_bytes(prior_content)
    descriptor = os.open(prior_path, os.O_RDONLY)
    try:
        prior = verifier._approved_prior_head(
            verifier._read_stable_fd(descriptor)
        )
    finally:
        os.close(descriptor)

    assert verifier.verify_versioned_head(approved_prior=prior)[
        "current_head"
    ] == head["current_head"]


def test_longitudinal_update_adds_exactly_one_terminal_batch() -> None:
    initial = copy.deepcopy(_head())
    approved_initial = _approved(initial)
    prior = copy.deepcopy(initial)
    _append_batches(prior, [("20260902_120000_prior.sql", b"select 1;\n")])
    assert verifier.validate_head(
        prior, approved_prior=approved_initial
    )

    approved_prior = _approved(prior)
    current = copy.deepcopy(prior)
    reconstructed = _append_batches(
        current, [("20260902_120001_current.sql", b"select 2;\n")]
    )

    assert verifier.validate_head(
        current,
        scanned_catalog=reconstructed,
        approved_prior=approved_prior,
    ) == reconstructed
    assert current["append_only_batches"][:-1] == prior["append_only_batches"]


def test_longitudinal_anchor_rejects_rewritten_approved_tail() -> None:
    initial = copy.deepcopy(_head())
    prior = copy.deepcopy(initial)
    _append_batches(prior, [("20260902_120000_prior.sql", b"select 1;\n")])
    approved_prior = _approved(prior)
    current = copy.deepcopy(prior)
    _append_batches(
        current, [("20260902_120001_current.sql", b"select 2;\n")]
    )

    rewritten = current["append_only_batches"][0]["entries"][0]
    rewritten["sha256"] = hashlib.sha256(b"rewritten\n").hexdigest()
    rewritten["size_bytes"] = len(b"rewritten\n")
    _recompute_chain(current)

    with pytest.raises(verifier.VerificationError):
        verifier.validate_head(current, approved_prior=approved_prior)


def test_longitudinal_anchor_rejects_omitted_and_renumbered_prior_batch() -> None:
    initial = copy.deepcopy(_head())
    prior = copy.deepcopy(initial)
    _append_batches(prior, [("20260902_120000_prior.sql", b"select 1;\n")])
    approved_prior = _approved(prior)

    current = copy.deepcopy(initial)
    _append_batches(
        current, [("20260902_120001_replacement.sql", b"select 2;\n")]
    )
    current["previous_approved_head_sha256"] = approved_prior.content_sha256

    with pytest.raises(verifier.VerificationError):
        verifier.validate_head(current, approved_prior=approved_prior)


def test_longitudinal_anchor_rejects_missing_or_wrong_prior() -> None:
    initial = copy.deepcopy(_head())
    prior = copy.deepcopy(initial)
    _append_batches(prior, [("20260902_120000_prior.sql", b"select 1;\n")])
    approved_prior = _approved(prior)
    current = copy.deepcopy(prior)
    _append_batches(
        current, [("20260902_120001_current.sql", b"select 2;\n")]
    )

    with pytest.raises(verifier.VerificationError):
        verifier.validate_head(current)

    current["previous_approved_head_sha256"] = "0" * 64
    with pytest.raises(verifier.VerificationError):
        verifier.validate_head(current, approved_prior=approved_prior)


def test_longitudinal_anchor_rejects_rewritten_prior_and_two_new_batches() -> None:
    initial = copy.deepcopy(_head())
    prior = copy.deepcopy(initial)
    _append_batches(prior, [("20260902_120000_prior.sql", b"select 1;\n")])
    approved_prior = _approved(prior)
    current = copy.deepcopy(prior)
    _append_batches(
        current, [("20260902_120001_current.sql", b"select 2;\n")]
    )

    rewritten_prior = copy.deepcopy(prior)
    entry = rewritten_prior["append_only_batches"][0]["entries"][0]
    entry["sha256"] = hashlib.sha256(b"rewritten prior\n").hexdigest()
    entry["size_bytes"] = len(b"rewritten prior\n")
    _recompute_chain(rewritten_prior)
    approved_rewritten = _approved(rewritten_prior)
    current["previous_approved_head_sha256"] = (
        approved_rewritten.content_sha256
    )
    with pytest.raises(verifier.VerificationError):
        verifier.validate_head(current, approved_prior=approved_rewritten)

    two_new = copy.deepcopy(prior)
    _append_batches(
        two_new,
        [
            ("20260902_120001_current.sql", b"select 2;\n"),
            ("20260902_120002_extra.sql", b"select 3;\n"),
        ],
    )
    with pytest.raises(verifier.VerificationError):
        verifier.validate_head(two_new, approved_prior=approved_prior)


def test_batch_count_limit_is_checked_before_batch_digest_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head = copy.deepcopy(_head())
    head["append_only_batches"] = [{}, {}]
    head["previous_approved_head_sha256"] = "0" * 64
    original_digest = verifier._catalog_digest
    digest_calls = 0

    def counted_digest(entries: list[dict[str, Any]]) -> str:
        nonlocal digest_calls
        digest_calls += 1
        return original_digest(entries)

    monkeypatch.setattr(verifier, "MAX_CATALOG_FILES", 76)
    monkeypatch.setattr(verifier, "_catalog_digest", counted_digest)
    with pytest.raises(verifier.VerificationError):
        verifier.validate_head(head)
    assert digest_calls == 1


def test_valid_migration_inserted_inside_historical_prefix_is_rejected() -> None:
    head = copy.deepcopy(_head())
    entries = head["historical_prefix"]["entries"]
    inserted = {
        "name": "0001a_inserted_inside_prefix.sql",
        "position": 1,
        "sha256": hashlib.sha256(b"select 1;\n").hexdigest(),
        "size_bytes": len(b"select 1;\n"),
    }
    entries.insert(1, inserted)
    for position, entry in enumerate(entries):
        entry["position"] = position

    with pytest.raises(verifier.VerificationError):
        verifier.validate_head(head)


def test_real_historical_byte_change_fails_through_full_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = tmp_path / "migrations"
    catalog.mkdir()
    for entry in _head()["historical_prefix"]["entries"]:
        source = verifier.MIGRATIONS_DIR / entry["name"]
        (catalog / entry["name"]).write_bytes(source.read_bytes())
    first = catalog / _head()["historical_prefix"]["entries"][0]["name"]
    first.write_bytes(first.read_bytes() + b"\n")
    head_path = tmp_path / "head.json"
    schema_path = tmp_path / "schema.json"
    head_path.write_bytes(HEAD_PATH.read_bytes())
    schema_path.write_bytes(SCHEMA_PATH.read_bytes())
    monkeypatch.setattr(verifier, "HEAD_PATH", head_path)
    monkeypatch.setattr(verifier, "SCHEMA_PATH", schema_path)
    monkeypatch.setattr(verifier, "MIGRATIONS_DIR", catalog)

    with pytest.raises(verifier.CatalogDriftError):
        verifier.verify_versioned_head()


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value["append_only_batches"][0].update({"sequence": True}),
        lambda value: value["append_only_batches"][0].update({"sequence": 2}),
        lambda value: value["append_only_batches"][0].update(
            {"batch_id": "migration-catalog-append-9999"}
        ),
        lambda value: value["append_only_batches"][0].update(
            {"previous_catalog_digest_sha256": "0" * 64}
        ),
        lambda value: value["append_only_batches"][0].update(
            {"resulting_catalog_digest_sha256": "0" * 64}
        ),
        lambda value: value["append_only_batches"][0]["entries"][0].update(
            {"position": 76}
        ),
        lambda value: value["append_only_batches"][0]["entries"][0].update(
            {"size_bytes": True}
        ),
        lambda value: value["current_head"].update({"migration_count": 75}),
        lambda value: value["current_head"].update({"digest_sha256": "0" * 64}),
    ],
)
def test_append_batch_chain_and_current_head_fail_closed(mutator: Any) -> None:
    head = copy.deepcopy(_head())
    prior = _approved(head)
    _append_batches(
        head,
        [("20260902_120000_append_only_example.sql", b"select 1;\n")],
    )
    mutator(head)

    with pytest.raises(verifier.VerificationError):
        verifier.validate_head(head, approved_prior=prior)


def test_append_batch_requires_exactly_one_entry() -> None:
    head = copy.deepcopy(_head())
    _append_batches(
        head,
        [("20260902_120000_append_only_example.sql", b"select 1;\n")],
    )
    extra = copy.deepcopy(head["append_only_batches"][0]["entries"][0])
    extra.update(
        {
            "name": "20260902_120001_second.sql",
            "position": 76,
            "sha256": hashlib.sha256(b"select 2;\n").hexdigest(),
        }
    )
    head["append_only_batches"][0]["entries"].append(extra)

    with pytest.raises(verifier.VerificationError):
        verifier.validate_head(head)


def test_append_name_must_be_strictly_after_previous_name() -> None:
    head = copy.deepcopy(_head())
    entry = copy.deepcopy(head["historical_prefix"]["entries"][-1])
    entry["position"] = 75
    head["append_only_batches"] = [
        {
            "batch_id": "migration-catalog-append-0001",
            "entries": [entry],
            "previous_catalog_digest_sha256": verifier.HISTORICAL_DIGEST_SHA256,
            "resulting_catalog_digest_sha256": "0" * 64,
            "sequence": 1,
        }
    ]

    with pytest.raises(verifier.VerificationError):
        verifier.validate_head(head)


def test_casefold_duplicate_across_batches_is_rejected() -> None:
    head = copy.deepcopy(_head())
    _append_batches(
        head,
        [
            ("20260902_120000_CASE.sql", b"select 1;\n"),
            ("20260902_120000_case.sql", b"select 2;\n"),
        ],
    )

    with pytest.raises(verifier.VerificationError):
        verifier.validate_head(head)


def test_scanned_catalog_must_match_reconstructed_catalog_exactly() -> None:
    head = _head()
    scanned = copy.deepcopy(head["historical_prefix"]["entries"])
    scanned[0]["sha256"] = "0" * 64

    with pytest.raises(verifier.CatalogDriftError):
        verifier.validate_head(head, scanned_catalog=scanned)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"a":1,"a":2}',
        b"\xef\xbb\xbf{}",
        b'{"a":1.0}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b"[]",
    ],
)
def test_json_parser_rejects_ambiguous_or_non_exact_values(payload: bytes) -> None:
    with pytest.raises(verifier.VerificationError):
        verifier._decode_json(payload)


def test_schema_field_addition_is_rejected() -> None:
    schema = copy.deepcopy(_schema())
    schema["properties"]["extra"] = {"type": "boolean"}

    with pytest.raises(verifier.VerificationError):
        verifier._require_exact(schema, verifier._expected_schema())


def test_scanner_rejects_symlink_file_and_symlink_parent(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    outside = tmp_path / "outside.sql"
    outside.write_bytes(b"select 1;\n")
    catalog.mkdir()
    (catalog / "0001_symlink.sql").symlink_to(outside)

    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog(catalog)

    real_catalog = tmp_path / "real-catalog"
    _write_sql(real_catalog, "0001_valid.sql")
    alias = tmp_path / "catalog-alias"
    alias.symlink_to(real_catalog, target_is_directory=True)
    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog(alias)


def test_scanner_rejects_hardlink_and_non_regular_file(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    source = _write_sql(catalog, "0001_source.sql")
    os.link(source, catalog / "0002_hardlink.sql")

    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog(catalog)

    fifo_catalog = tmp_path / "fifo-catalog"
    fifo_catalog.mkdir()
    os.mkfifo(fifo_catalog / "0001_fifo.sql")
    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog(fifo_catalog)


@pytest.mark.parametrize(
    "names",
    [
        ["bad name.sql"],
        ["A.sql", "a.sql"],
    ],
)
def test_scanner_rejects_invalid_or_casefold_duplicate_names(
    tmp_path: Path, names: list[str]
) -> None:
    catalog = tmp_path / "catalog"
    for name in names:
        _write_sql(catalog, name)

    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog(catalog)


def test_scanner_checks_count_file_size_and_total_before_accepting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = tmp_path / "count"
    _write_sql(catalog, "0001_one.sql")
    _write_sql(catalog, "0002_two.sql")
    monkeypatch.setattr(verifier, "MAX_CATALOG_FILES", 1)
    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog(catalog)

    monkeypatch.setattr(verifier, "MAX_CATALOG_FILES", 10)
    oversized = tmp_path / "oversized"
    _write_sql(oversized, "0001_large.sql", b"12345")
    monkeypatch.setattr(verifier, "MAX_MIGRATION_BYTES", 4)
    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog(oversized)

    monkeypatch.setattr(verifier, "MAX_MIGRATION_BYTES", 10)
    total = tmp_path / "total"
    _write_sql(total, "0001_one.sql", b"123")
    _write_sql(total, "0002_two.sql", b"456")
    monkeypatch.setattr(verifier, "MAX_CATALOG_BYTES", 5)
    reads = 0
    original_read = verifier._read_regular_at

    def counted_read(*args: Any, **kwargs: Any) -> Any:
        nonlocal reads
        reads += 1
        return original_read(*args, **kwargs)

    monkeypatch.setattr(verifier, "_read_regular_at", counted_read)
    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog(total)
    assert reads == 0


def test_scanner_rejects_excess_non_sql_entries_before_reading_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = tmp_path / "catalog"
    _write_sql(catalog, "0001_valid.sql")
    for index in range(verifier.MAX_CATALOG_FILES + 1):
        (catalog / f"noise-{index:04d}.txt").write_bytes(b"x")
    reads = 0
    original_read = verifier._read_regular_at

    def counted_read(*args: Any, **kwargs: Any) -> Any:
        nonlocal reads
        reads += 1
        return original_read(*args, **kwargs)

    monkeypatch.setattr(verifier, "_read_regular_at", counted_read)
    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog(catalog)
    assert reads == 0


def test_scanner_accepts_exact_total_entry_limit_with_non_sql_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = tmp_path / "catalog"
    _write_sql(catalog, "0001_valid.sql")
    for index in range(3):
        (catalog / f"documentation-{index}.txt").write_bytes(b"x")
    monkeypatch.setattr(verifier, "MAX_CATALOG_FILES", 4)

    entries = verifier._scan_catalog(catalog)
    assert [entry["name"] for entry in entries] == ["0001_valid.sql"]


def test_scanner_detects_file_change_after_stable_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = tmp_path / "catalog"
    path = _write_sql(catalog, "0001_race.sql")
    original = verifier._read_regular_at
    changed = False

    def mutate_after_read(*args: Any, **kwargs: Any) -> Any:
        nonlocal changed
        result = original(*args, **kwargs)
        if not changed:
            changed = True
            path.write_bytes(b"select 2;\n")
        return result

    monkeypatch.setattr(verifier, "_read_regular_at", mutate_after_read)
    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog(catalog)


def test_scanner_detects_change_between_directory_listings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = tmp_path / "catalog"
    _write_sql(catalog, "0001_stable.sql")
    original = verifier._bounded_directory_listing
    calls = 0

    def changed_listing(descriptor: int) -> list[str]:
        nonlocal calls
        calls += 1
        listing = original(descriptor)
        if calls == 2:
            return [*listing, "late-entry"]
        return listing

    monkeypatch.setattr(verifier, "_bounded_directory_listing", changed_listing)
    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog(catalog)


def test_scanner_detects_replaced_ancestor_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    catalog = root / "backend" / "migrations"
    _write_sql(catalog, "0001_stable.sql")
    original = verifier._read_regular_at
    replaced = False

    def replace_ancestor(*args: Any, **kwargs: Any) -> Any:
        nonlocal replaced
        result = original(*args, **kwargs)
        if not replaced:
            replaced = True
            backend = root / "backend"
            backend.rename(root / "backend-before-swap")
            replacement = root / "backend" / "migrations"
            _write_sql(replacement, "0001_stable.sql")
        return result

    monkeypatch.setattr(verifier, "_read_regular_at", replace_ancestor)
    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog(catalog)


def test_directory_chain_recheck_ignores_only_volatile_metadata(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "root" / "backend" / "migrations"
    catalog.mkdir(parents=True)
    opened = verifier._open_directory(catalog, verifier.CatalogDriftError)
    try:
        recorded = opened.chain
    finally:
        os.close(opened.descriptor)

    volatile = tuple(
        replace(
            snapshot,
            links=snapshot.links + 1,
            size=snapshot.size + 1,
            mtime_ns=snapshot.mtime_ns + 1,
            ctime_ns=snapshot.ctime_ns + 1,
        )
        for snapshot in recorded
    )
    verifier._verify_directory_chain(
        catalog, volatile, verifier.CatalogDriftError
    )

    for field in ("device", "inode", "mode", "uid", "gid"):
        replaced_ancestor = list(volatile)
        snapshot = replaced_ancestor[1]
        replaced_ancestor[1] = replace(
            snapshot, **{field: getattr(snapshot, field) + 1}
        )
        with pytest.raises(verifier.CatalogDriftError):
            verifier._verify_directory_chain(
                catalog,
                tuple(replaced_ancestor),
                verifier.CatalogDriftError,
            )

    with pytest.raises(verifier.CatalogDriftError):
        verifier._verify_directory_chain(
            catalog, volatile[:-1], verifier.CatalogDriftError
        )


def test_directory_open_ignores_unrelated_child_metadata_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "identity-root"
    catalog = root / "migrations"
    catalog.mkdir(parents=True)
    original_stat = verifier.os.stat
    changed = False

    def mutate_before_named_stat(*args: Any, **kwargs: Any) -> os.stat_result:
        nonlocal changed
        if (
            not changed
            and args
            and args[0] == root.name
            and kwargs.get("dir_fd") is not None
            and kwargs.get("follow_symlinks") is False
        ):
            changed = True
            os.mkdir(root / "unrelated-child")
        return original_stat(*args, **kwargs)

    monkeypatch.setattr(verifier.os, "stat", mutate_before_named_stat)
    opened = verifier._open_directory(catalog, verifier.CatalogDriftError)
    try:
        assert changed
        assert opened.chain[-1].inode == original_stat(catalog).st_ino
    finally:
        os.close(opened.descriptor)


def test_stable_artifact_read_ignores_unrelated_sibling_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "artifact.json"
    path.write_bytes(b"{}\n")
    original_read = verifier._read_regular_at
    changed = False

    def create_sibling_after_read(*args: Any, **kwargs: Any) -> Any:
        nonlocal changed
        result = original_read(*args, **kwargs)
        if not changed:
            changed = True
            (tmp_path / "unrelated.json").write_bytes(b"{}\n")
        return result

    monkeypatch.setattr(verifier, "_read_regular_at", create_sibling_after_read)
    record = verifier._read_stable_file(path)

    assert changed
    assert record.content == b"{}\n"


def test_stable_file_recheck_keeps_file_strict_and_parent_identity_only(
    tmp_path: Path,
) -> None:
    path = tmp_path / "artifact.json"
    path.write_bytes(b"{}\n")
    recorded = verifier._read_stable_file(path)
    volatile_parent = replace(
        recorded,
        parent=replace(
            recorded.parent,
            links=recorded.parent.links + 1,
            size=recorded.parent.size + 1,
            mtime_ns=recorded.parent.mtime_ns + 1,
            ctime_ns=recorded.parent.ctime_ns + 1,
        ),
    )

    assert verifier._stable_file_unchanged(volatile_parent, recorded)
    assert not verifier._stable_file_unchanged(
        replace(
            volatile_parent,
            parent=replace(
                volatile_parent.parent,
                inode=volatile_parent.parent.inode + 1,
            ),
        ),
        recorded,
    )
    assert not verifier._stable_file_unchanged(
        replace(
            volatile_parent,
            file=replace(
                volatile_parent.file,
                mtime_ns=volatile_parent.file.mtime_ns + 1,
            ),
        ),
        recorded,
    )


@pytest.mark.parametrize("fail", [False, True])
def test_directory_descriptors_are_closed_on_success_and_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail: bool,
) -> None:
    catalog = tmp_path / "catalog"
    _write_sql(catalog, "0001_valid.sql")
    original_open = verifier.os.open
    original_close = verifier.os.close
    opened: list[int] = []
    closed: list[int] = []

    def tracked_open(*args: Any, **kwargs: Any) -> int:
        descriptor = original_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def tracked_close(descriptor: int) -> None:
        closed.append(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(verifier.os, "open", tracked_open)
    monkeypatch.setattr(verifier.os, "close", tracked_close)
    if fail:
        monkeypatch.setattr(verifier, "MAX_CATALOG_BYTES", 1)
        with pytest.raises(verifier.CatalogDriftError):
            verifier._scan_catalog(catalog)
    else:
        assert len(verifier._scan_catalog(catalog)) == 1

    assert Counter(opened) == Counter(closed)


def test_stable_artifact_reader_rejects_symlink_and_hardlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="ascii")
    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(target)
    with pytest.raises(verifier.ArtifactIoError):
        verifier._read_stable_file(symlink)

    hardlink = tmp_path / "hardlink.json"
    os.link(target, hardlink)
    with pytest.raises(verifier.ArtifactIoError):
        verifier._read_stable_file(hardlink)


def test_cli_rejects_arguments_and_artifact_errors_without_sensitive_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    assert verifier.main(["--head", "/sensitive/example.json"]) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert "/sensitive" not in output.out
    assert "Traceback" not in output.out
    assert output.out.splitlines() == [
        "RESULT=BLOCKED_MIGRATION_CATALOG_HEAD:USAGE",
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "NEXT_STAGE_AUTHORIZED=false",
    ]

    missing = tmp_path / "sensitive-artifact-name.json"
    monkeypatch.setattr(verifier, "HEAD_PATH", missing)
    assert verifier.main([]) == verifier.ArtifactIoError.exit_code
    output = capsys.readouterr()
    assert output.err == ""
    assert str(missing) not in output.out
    assert "Traceback" not in output.out
    assert output.out.splitlines() == [
        "RESULT=BLOCKED_MIGRATION_CATALOG_HEAD:ARTIFACT_IO_INVALID",
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "NEXT_STAGE_AUTHORIZED=false",
    ]


def test_cli_future_head_requires_and_accepts_stable_prior_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    prior = copy.deepcopy(_head())
    prior_content = _serialized_head(prior)
    current = copy.deepcopy(prior)
    reconstructed = _append_batches(
        current, [("20260902_120000_future.sql", b"select 1;\n")]
    )
    catalog = tmp_path / "migrations"
    catalog.mkdir()
    for entry in reconstructed[:-1]:
        source = verifier.MIGRATIONS_DIR / entry["name"]
        (catalog / entry["name"]).write_bytes(source.read_bytes())
    (catalog / reconstructed[-1]["name"]).write_bytes(b"select 1;\n")
    head_path = tmp_path / "current.json"
    schema_path = tmp_path / "schema.json"
    prior_path = tmp_path / "prior.json"
    head_path.write_bytes(_serialized_head(current))
    schema_path.write_bytes(SCHEMA_PATH.read_bytes())
    prior_path.write_bytes(prior_content)
    monkeypatch.setattr(verifier, "HEAD_PATH", head_path)
    monkeypatch.setattr(verifier, "SCHEMA_PATH", schema_path)
    monkeypatch.setattr(verifier, "MIGRATIONS_DIR", catalog)

    assert verifier.main([]) == verifier.VerificationError.exit_code
    without_prior = capsys.readouterr()
    assert "CONTRACT_INVALID" in without_prior.out
    assert verifier.OPERATIONAL_BLOCK in without_prior.out
    assert verifier.NEXT_STAGE_BLOCK in without_prior.out

    descriptor = os.open(prior_path, os.O_RDONLY)
    try:
        assert verifier.main(["--prior-head-fd", str(descriptor)]) == 0
        os.fstat(descriptor)
    finally:
        os.close(descriptor)
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.splitlines() == [
        "RESULT=MIGRATION_CATALOG_HEAD_VERIFIED_OFFLINE",
        "CATALOG_MIGRATION_COUNT=76",
        f"CATALOG_DIGEST_SHA256={current['current_head']['digest_sha256']}",
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "NEXT_STAGE_AUTHORIZED=false",
    ]

    original_verify = verifier.verify_versioned_head

    def mutate_prior_after_verification(*args: Any, **kwargs: Any) -> Any:
        result = original_verify(*args, **kwargs)
        prior_path.write_bytes(prior_path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(
        verifier, "verify_versioned_head", mutate_prior_after_verification
    )
    descriptor = os.open(prior_path, os.O_RDONLY)
    try:
        assert verifier.main(["--prior-head-fd", str(descriptor)]) == (
            verifier.ArtifactIoError.exit_code
        )
    finally:
        os.close(descriptor)
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.splitlines() == [
        "RESULT=BLOCKED_MIGRATION_CATALOG_HEAD:ARTIFACT_IO_INVALID",
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "NEXT_STAGE_AUTHORIZED=false",
    ]


def test_prior_fd_is_limited_stable_regular_and_single_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior_path = tmp_path / "prior.json"
    prior_path.write_bytes(_serialized_head(_head()))
    hardlink = tmp_path / "prior-hardlink.json"
    os.link(prior_path, hardlink)
    descriptor = os.open(prior_path, os.O_RDONLY)
    try:
        with pytest.raises(verifier.ArtifactIoError):
            verifier._read_stable_fd(descriptor)
    finally:
        os.close(descriptor)
    hardlink.unlink()

    descriptor = os.open(prior_path, os.O_RDONLY)
    original_pread = verifier.os.pread
    changed = False

    def mutate_during_read(*args: Any, **kwargs: Any) -> bytes:
        nonlocal changed
        chunk = original_pread(*args, **kwargs)
        if not changed:
            changed = True
            prior_path.write_bytes(prior_path.read_bytes() + b" ")
        return chunk

    monkeypatch.setattr(verifier.os, "pread", mutate_during_read)
    try:
        with pytest.raises(verifier.ArtifactIoError):
            verifier._read_stable_fd(descriptor)
    finally:
        os.close(descriptor)


def test_prior_fd_duplicate_is_closed_on_success_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior_path = tmp_path / "prior.json"
    prior_path.write_bytes(_serialized_head(_head()))
    original_dup = verifier.os.dup
    original_close = verifier.os.close
    duplicated: list[int] = []
    closed: list[int] = []

    def tracked_dup(descriptor: int) -> int:
        duplicate = original_dup(descriptor)
        duplicated.append(duplicate)
        return duplicate

    def tracked_close(descriptor: int) -> None:
        closed.append(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(verifier.os, "dup", tracked_dup)
    monkeypatch.setattr(verifier.os, "close", tracked_close)
    source = os.open(prior_path, os.O_RDONLY)
    try:
        assert verifier._read_stable_fd(source).content
        original_pread = verifier.os.pread

        def failed_pread(*_args: Any, **_kwargs: Any) -> bytes:
            raise OSError("synthetic read failure")

        monkeypatch.setattr(verifier.os, "pread", failed_pread)
        with pytest.raises(verifier.ArtifactIoError):
            verifier._read_stable_fd(source)
        monkeypatch.setattr(verifier.os, "pread", original_pread)
    finally:
        os.close(source)

    assert len(duplicated) == 2
    assert all(
        closed.count(descriptor) == count
        for descriptor, count in Counter(duplicated).items()
    )


def test_verifier_has_no_external_effect_capabilities() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
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
            "subprocess",
            "urllib",
        }
    )
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "os.environ" not in source
    assert "os.getenv" not in source
    assert "Popen(" not in source
    assert "run(" not in source
