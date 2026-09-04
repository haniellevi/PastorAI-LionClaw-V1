from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import os
from pathlib import Path
import shutil
import uuid

import pytest

from scripts import validated_migration_catalog_snapshot as snapshot_api


def _expect_verifier_rejection(path: Path) -> None:
    with pytest.raises(RuntimeError, match="^catalog verifier unavailable$"):
        snapshot_api._load_catalog_verifier(
            path,
            module_name=f"_pastorai_rejected_verifier_{uuid.uuid4().hex}",
        )


def test_catalog_verifier_is_the_authenticated_historical_source() -> None:
    verifier_path = Path(snapshot_api.catalog.__file__)

    assert verifier_path == snapshot_api.VERIFIER_PATH
    assert hashlib.sha256(verifier_path.read_bytes()).hexdigest() == (
        snapshot_api.CATALOG_VERIFIER_SHA256
    )


def test_public_catalog_snapshot_is_immutable_source_evidence() -> None:
    snapshot = snapshot_api.validated_local_catalog_snapshot()
    catalog = snapshot_api.catalog
    head = catalog._decode_json(catalog.HEAD_PATH.read_bytes())

    assert snapshot.head_content_sha256 == hashlib.sha256(
        catalog.HEAD_PATH.read_bytes()
    ).hexdigest()
    assert snapshot.schema_content_sha256 == hashlib.sha256(
        catalog.SCHEMA_PATH.read_bytes()
    ).hexdigest()
    assert snapshot.catalog_digest_sha256 == head["current_head"]["digest_sha256"]
    assert snapshot.catalog_directory == os.fspath(catalog.MIGRATIONS_DIR.absolute())
    assert len(snapshot.entries) == head["current_head"]["migration_count"]
    assert snapshot.entries[-1] == snapshot_api.ValidatedCatalogEntry(
        position=74,
        name=catalog.HISTORICAL_LAST_BASENAME,
        sha256=head["historical_prefix"]["entries"][-1]["sha256"],
        size_bytes=head["historical_prefix"]["entries"][-1]["size_bytes"],
    )
    assert snapshot.operational_authorization is False
    assert snapshot.next_stage_authorized is False

    with pytest.raises(FrozenInstanceError):
        snapshot.entries[0].name = "rewritten.sql"


def test_snapshot_fails_closed_when_head_changes_during_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = snapshot_api.catalog
    original = catalog._stable_file_unchanged
    calls = 0

    def changed(*args: object, **kwargs: object) -> bool:
        nonlocal calls
        calls += 1
        return False if calls == 1 else original(*args, **kwargs)

    monkeypatch.setattr(catalog, "_stable_file_unchanged", changed)

    with pytest.raises(catalog.ArtifactIoError):
        snapshot_api.validated_local_catalog_snapshot()


def test_verifier_content_is_authenticated_before_execution(tmp_path: Path) -> None:
    sentinel = tmp_path / "must-not-exist"
    malicious = tmp_path / "verify_migration_catalog_head.py"
    malicious.write_text(
        "from pathlib import Path\n"
        f"Path({os.fspath(sentinel)!r}).write_text('executed')\n",
        encoding="utf-8",
    )

    _expect_verifier_rejection(malicious)

    assert not sentinel.exists()


def test_verifier_loader_rejects_symlink(tmp_path: Path) -> None:
    link = tmp_path / "verify_migration_catalog_head.py"
    link.symlink_to(snapshot_api.VERIFIER_PATH)

    _expect_verifier_rejection(link)


def test_verifier_loader_rejects_hardlink(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    shutil.copyfile(snapshot_api.VERIFIER_PATH, source)
    link = tmp_path / "verify_migration_catalog_head.py"
    os.link(source, link)

    _expect_verifier_rejection(link)


def test_verifier_loader_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "verify_migration_catalog_head.py"
    os.mkfifo(fifo)

    _expect_verifier_rejection(fifo)


def test_verifier_loader_rejects_non_regular_file(tmp_path: Path) -> None:
    directory = tmp_path / "verify_migration_catalog_head.py"
    directory.mkdir()

    _expect_verifier_rejection(directory)


def test_verifier_loader_rejects_oversized_source(tmp_path: Path) -> None:
    oversized = tmp_path / "verify_migration_catalog_head.py"
    with oversized.open("wb") as handle:
        handle.truncate(snapshot_api.MAX_VERIFIER_BYTES + 1)

    _expect_verifier_rejection(oversized)
