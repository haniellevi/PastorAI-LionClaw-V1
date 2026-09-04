from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "backend" / "scripts"
WRAPPER_PATH = SCRIPTS_DIR / "apply_migrations_catalog_bound_v2.py"
LEGACY_PATH = SCRIPTS_DIR / "apply_migrations.py"


def _load_wrapper() -> Any:
    scripts_path = os.fspath(SCRIPTS_DIR)
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
    name = "apply_migrations_catalog_bound_v2_under_test"
    spec = importlib.util.spec_from_file_location(name, WRAPPER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


wrapper = _load_wrapper()


def _snapshot(root: Path) -> Any:
    entries = tuple(
        wrapper.migration_catalog.ValidatedCatalogEntry(
            position=position,
            name=path.name,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            size_bytes=path.stat().st_size,
        )
        for position, path in enumerate(sorted(root.glob("*.sql")))
    )
    return wrapper.migration_catalog.ValidatedCatalogSnapshot(
        head_content_sha256="1" * 64,
        schema_content_sha256="2" * 64,
        catalog_digest_sha256="3" * 64,
        catalog_directory=os.fspath(root.absolute()),
        entries=entries,
        operational_authorization=False,
        next_stage_authorized=False,
    )


@pytest.fixture
def bound_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Path, Any]:
    root = tmp_path / "migrations"
    root.mkdir()
    (root / "20260903_000001_first.sql").write_text("select 1;\n", encoding="utf-8")
    (root / "20260903_000002_second.sql").write_text("select 2;\n", encoding="utf-8")
    legacy = wrapper._load_legacy_runner()
    legacy.MIGRATIONS_DIR = root
    snapshot = _snapshot(root)
    monkeypatch.setattr(
        wrapper.migration_catalog,
        "validated_local_catalog_snapshot",
        lambda: snapshot,
    )
    return legacy, root, snapshot


def test_legacy_runner_is_authenticated_before_execution() -> None:
    content = wrapper._verified_legacy_bytes()
    assert hashlib.sha256(content).hexdigest() == wrapper.LEGACY_RUNNER_SHA256
    legacy = wrapper._load_legacy_runner()
    assert legacy.__file__ == os.fspath(LEGACY_PATH)
    assert callable(legacy.discover_migrations)


def test_snapshot_api_is_authenticated_before_execution() -> None:
    content = wrapper._read_pinned_snapshot_api()
    assert hashlib.sha256(content).hexdigest() == wrapper.SNAPSHOT_API_SHA256
    assert wrapper.migration_catalog is not None
    assert callable(wrapper.migration_catalog.validated_local_catalog_snapshot)


def test_altered_snapshot_api_is_rejected_without_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "must-not-exist"
    altered = tmp_path / "validated_migration_catalog_snapshot.py"
    altered.write_text(
        "from pathlib import Path\n"
        f"Path({os.fspath(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(wrapper, "SNAPSHOT_API_PATH", altered)

    with pytest.raises(wrapper.CatalogBindingError):
        wrapper._load_pinned_snapshot_api()

    assert not marker.exists()


@pytest.mark.parametrize("kind", ("symlink", "hardlink", "fifo"))
def test_non_regular_or_multiply_linked_snapshot_api_is_rejected_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    candidate = tmp_path / "validated_migration_catalog_snapshot.py"
    if kind == "symlink":
        candidate.symlink_to(wrapper.SNAPSHOT_API_PATH)
    elif kind == "hardlink":
        source = tmp_path / "source.py"
        source.write_bytes(wrapper.SNAPSHOT_API_PATH.read_bytes())
        os.link(source, candidate)
    else:
        os.mkfifo(candidate)
    monkeypatch.setattr(wrapper, "SNAPSHOT_API_PATH", candidate)

    with pytest.raises(wrapper.CatalogBindingError):
        wrapper._read_pinned_snapshot_api()


def test_wrapper_list_starts_with_isolated_python_path() -> None:
    completed = subprocess.run(
        [sys.executable, "-P", os.fspath(WRAPPER_PATH), "list"],
        cwd=REPO_ROOT,
        check=False,
        env={
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": os.defpath,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )

    assert completed.returncode == 0
    assert completed.stderr == b""
    assert b"CATALOG_BOUND_V2=VERIFIED_SOURCE_ONLY\n" in completed.stdout
    assert b"OPERATIONAL_AUTHORIZATION=BLOCKED\n" in completed.stdout
    assert b"NEXT_STAGE_AUTHORIZED=false\n" in completed.stdout


def test_altered_legacy_runner_is_rejected(tmp_path: Path) -> None:
    altered = tmp_path / "apply_migrations.py"
    altered.write_bytes(LEGACY_PATH.read_bytes() + b"\n")
    with pytest.raises(wrapper.LegacyIntegrityError):
        wrapper._load_legacy_runner(altered)


def test_symlinked_legacy_runner_is_rejected(tmp_path: Path) -> None:
    link = tmp_path / "apply_migrations.py"
    link.symlink_to(LEGACY_PATH)
    with pytest.raises(wrapper.LegacyIntegrityError):
        wrapper._load_legacy_runner(link)


def test_hardlinked_legacy_runner_is_rejected(tmp_path: Path) -> None:
    copied = tmp_path / "trusted-copy.py"
    copied.write_bytes(LEGACY_PATH.read_bytes())
    linked = tmp_path / "linked-copy.py"
    os.link(copied, linked)
    with pytest.raises(wrapper.LegacyIntegrityError):
        wrapper._load_legacy_runner(copied)


def test_fifo_legacy_runner_is_rejected_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "apply_migrations.py"
    os.mkfifo(fifo)
    with pytest.raises(wrapper.LegacyIntegrityError):
        wrapper._load_legacy_runner(fifo)


def test_exact_catalog_names_order_sizes_and_hashes_are_bound(
    bound_catalog: tuple[Any, Path, Any],
) -> None:
    legacy, _root, snapshot = bound_catalog
    binding = wrapper._build_catalog_binding(legacy)
    assert binding.snapshot == snapshot
    assert tuple(candidate.name for candidate in binding.migrations) == tuple(
        entry.name for entry in snapshot.entries
    )
    assert tuple(candidate.identity.size for candidate in binding.migrations) == tuple(
        entry.size_bytes for entry in snapshot.entries
    )


def test_extra_sql_file_is_rejected(
    bound_catalog: tuple[Any, Path, Any],
) -> None:
    legacy, root, _snapshot_value = bound_catalog
    (root / "20260903_000003_extra.sql").write_text("select 3;\n", encoding="utf-8")
    with pytest.raises(wrapper.CatalogBindingError):
        wrapper._build_catalog_binding(legacy)


@pytest.mark.parametrize("tamper", ["size", "hash", "utf8"])
def test_size_hash_and_utf8_tampering_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    root = tmp_path / "migrations"
    root.mkdir()
    path = root / "20260903_000001_first.sql"
    path.write_bytes(b"select 1;\n")
    legacy = wrapper._load_legacy_runner()
    legacy.MIGRATIONS_DIR = root

    if tamper == "utf8":
        path.write_bytes(b"select '\xff';\n")
        snapshot = _snapshot(root)
    else:
        snapshot = _snapshot(root)
        if tamper == "size":
            path.write_bytes(b"select 100;\n")
        else:
            path.write_bytes(b"select 2;\n")
    monkeypatch.setattr(
        wrapper.migration_catalog,
        "validated_local_catalog_snapshot",
        lambda: snapshot,
    )

    with pytest.raises(wrapper.CatalogBindingError):
        wrapper._build_catalog_binding(legacy)


def test_snapshot_change_during_binding_is_rejected(
    bound_catalog: tuple[Any, Path, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy, _root, snapshot = bound_catalog
    changed = replace(snapshot, catalog_digest_sha256="4" * 64)
    snapshots = iter((snapshot, changed))
    monkeypatch.setattr(
        wrapper.migration_catalog,
        "validated_local_catalog_snapshot",
        lambda: next(snapshots),
    )
    with pytest.raises(wrapper.CatalogBindingError):
        wrapper._build_catalog_binding(legacy)


def test_operator_hash_must_equal_the_catalog_entry_exactly(
    bound_catalog: tuple[Any, Path, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy, _root, snapshot = bound_catalog
    calls = 0

    def forbidden_connect(_url: str) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError("connection must remain unreachable")

    legacy._connect = forbidden_connect
    monkeypatch.setattr(wrapper, "_load_legacy_runner", lambda: legacy)
    entry = snapshot.entries[0]
    result = wrapper.main(
        [
            "apply_migrations_catalog_bound_v2.py",
            "apply",
            "--migration",
            entry.name,
            "--sha256",
            entry.sha256.upper(),
            "--confirm",
            "APPLY",
        ]
    )
    captured = capsys.readouterr()
    assert result == wrapper.CATALOG_EXIT
    assert "CATALOG_BOUND_V2_BLOCKED:OPERATOR_HASH_NOT_CATALOG_HEAD" in captured.err
    assert calls == 0


@pytest.mark.parametrize(
    "arguments",
    [
        ["status"],
        ["harden-ledger", "--confirm", "HARDEN_LEDGER"],
        ["bootstrap-ledger", "--confirm", "BOOTSTRAP_LEDGER"],
        ["apply"],
    ],
)
def test_database_commands_are_explicitly_blocked_without_any_connection(
    bound_catalog: tuple[Any, Path, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
) -> None:
    legacy, _root, snapshot = bound_catalog
    entry = snapshot.entries[0]
    if arguments == ["apply"]:
        arguments = [
            "apply",
            "--migration",
            entry.name,
            "--sha256",
            entry.sha256,
            "--confirm",
            "APPLY",
        ]
    connection_calls = 0

    def forbidden_connect(_url: str) -> None:
        nonlocal connection_calls
        connection_calls += 1
        raise AssertionError("connection must remain unreachable")

    legacy._connect = forbidden_connect
    monkeypatch.setattr(wrapper, "_load_legacy_runner", lambda: legacy)
    secret = "postgresql://user:never-print-this@example.invalid/database"
    monkeypatch.setenv(legacy.DATABASE_URL_ENV, secret)

    result = wrapper.main(["apply_migrations_catalog_bound_v2.py", *arguments])
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert result == wrapper.AUTHORIZATION_EXIT
    assert (
        "CATALOG_BOUND_V2_BLOCKED:"
        "TRUST_ANCHOR_AND_AUTHORIZATION_CONTEXT_UNAVAILABLE"
    ) in captured.err
    assert "OPERATIONAL_AUTHORIZATION=BLOCKED" in captured.out
    assert "NEXT_STAGE_AUTHORIZED=false" in captured.out
    assert secret not in combined
    assert "never-print-this" not in combined
    assert connection_calls == 0


def test_list_is_source_only_and_never_connects(
    bound_catalog: tuple[Any, Path, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy, _root, snapshot = bound_catalog
    connection_calls = 0

    def forbidden_connect(_url: str) -> None:
        nonlocal connection_calls
        connection_calls += 1
        raise AssertionError("connection must remain unreachable")

    legacy._connect = forbidden_connect
    monkeypatch.setattr(wrapper, "_load_legacy_runner", lambda: legacy)

    assert wrapper.main(["apply_migrations_catalog_bound_v2.py", "list"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "CATALOG_BOUND_V2=VERIFIED_SOURCE_ONLY" in captured.out
    assert f"CATALOG_ENTRY_COUNT={len(snapshot.entries)}" in captured.out
    assert "OPERATIONAL_AUTHORIZATION=BLOCKED" in captured.out
    assert "NEXT_STAGE_AUTHORIZED=false" in captured.out
    assert connection_calls == 0


def test_hooks_restore_original_functions_on_success_and_exception(
    bound_catalog: tuple[Any, Path, Any],
) -> None:
    legacy, _root, _snapshot_value = bound_catalog
    binding = wrapper._build_catalog_binding(legacy)
    originals = (
        legacy.discover_migrations,
        legacy._read_verified_migration,
        legacy._connect,
    )
    with wrapper._catalog_bound_hooks(legacy, binding):
        assert legacy.discover_migrations is not originals[0]
        assert legacy._read_verified_migration is not originals[1]
        assert legacy._connect is not originals[2]
    assert (
        legacy.discover_migrations,
        legacy._read_verified_migration,
        legacy._connect,
    ) == originals

    with pytest.raises(RuntimeError):
        with wrapper._catalog_bound_hooks(legacy, binding):
            raise RuntimeError("test-only")
    assert (
        legacy.discover_migrations,
        legacy._read_verified_migration,
        legacy._connect,
    ) == originals


def test_connect_hook_revalidates_snapshot_and_never_calls_original(
    bound_catalog: tuple[Any, Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy, _root, snapshot = bound_catalog
    reads = 0

    def snapshot_reader() -> Any:
        nonlocal reads
        reads += 1
        return snapshot

    monkeypatch.setattr(
        wrapper.migration_catalog,
        "validated_local_catalog_snapshot",
        snapshot_reader,
    )
    original_calls = 0

    def original_connect(_url: str) -> None:
        nonlocal original_calls
        original_calls += 1

    legacy._connect = original_connect
    binding = wrapper._build_catalog_binding(legacy)
    reads_before_connect = reads
    with wrapper._catalog_bound_hooks(legacy, binding):
        with pytest.raises(wrapper.AuthorizationUnavailableError):
            legacy._connect("not-a-real-dsn")
    assert reads == reads_before_connect + 1
    assert original_calls == 0
    assert legacy._connect is original_connect


def test_connect_hook_blocks_changed_snapshot_before_authorization_check(
    bound_catalog: tuple[Any, Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy, _root, snapshot = bound_catalog
    current = [snapshot]
    monkeypatch.setattr(
        wrapper.migration_catalog,
        "validated_local_catalog_snapshot",
        lambda: current[0],
    )
    binding = wrapper._build_catalog_binding(legacy)
    current[0] = replace(snapshot, head_content_sha256="5" * 64)
    with wrapper._catalog_bound_hooks(legacy, binding):
        with pytest.raises(wrapper.CatalogBindingError):
            legacy._connect("not-a-real-dsn")


def test_invalid_cli_value_is_not_reflected_and_catalog_is_not_read(
    bound_catalog: tuple[Any, Path, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy, _root, _snapshot_value = bound_catalog
    snapshot_reads = 0

    def forbidden_snapshot() -> Any:
        nonlocal snapshot_reads
        snapshot_reads += 1
        raise AssertionError("invalid CLI must stop before catalog access")

    monkeypatch.setattr(wrapper, "_load_legacy_runner", lambda: legacy)
    monkeypatch.setattr(
        wrapper.migration_catalog,
        "validated_local_catalog_snapshot",
        forbidden_snapshot,
    )
    secret = "postgresql://user:secret@example.invalid/db"
    result = wrapper.main(
        ["apply_migrations_catalog_bound_v2.py", "status", f"--dsn={secret}"]
    )
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert result == wrapper.USAGE_EXIT
    assert "CATALOG_BOUND_V2_BLOCKED:USAGE" in captured.err
    assert secret not in combined
    assert "secret" not in combined
    assert snapshot_reads == 0


@pytest.mark.parametrize(
    "arguments",
    (["--help"], ["apply", "--help"], ["list", "--help"]),
)
def test_help_never_becomes_a_second_successful_command(
    bound_catalog: tuple[Any, Path, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
) -> None:
    legacy, _root, _snapshot_value = bound_catalog
    snapshot_reads = 0

    def forbidden_snapshot() -> Any:
        nonlocal snapshot_reads
        snapshot_reads += 1
        raise AssertionError("help must stop before catalog access")

    monkeypatch.setattr(wrapper, "_load_legacy_runner", lambda: legacy)
    monkeypatch.setattr(
        wrapper.migration_catalog,
        "validated_local_catalog_snapshot",
        forbidden_snapshot,
    )

    result = wrapper.main(["apply_migrations_catalog_bound_v2.py", *arguments])
    captured = capsys.readouterr()
    assert result != 0
    assert "CATALOG_BOUND_V2_BLOCKED:REQUEST_REJECTED" in captured.err
    assert "OPERATIONAL_AUTHORIZATION=BLOCKED" in captured.out
    assert "NEXT_STAGE_AUTHORIZED=false" in captured.out
    assert snapshot_reads == 0


def test_wrapper_has_no_network_or_historical_proposal_dependency() -> None:
    source = WRAPPER_PATH.read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "socket" not in source
    assert "urllib" not in source
    assert "requests" not in source
    assert "divergence_remediation_proposal" not in source
    assert wrapper.LEGACY_RUNNER_SHA256 in source
    assert wrapper.SNAPSHOT_API_SHA256 in source
    assert "from scripts import validated_migration_catalog_snapshot" not in source
    assert "import validated_migration_catalog_snapshot" not in source
    assert "validated_local_catalog_snapshot" in source


def test_legacy_cli_commands_survive_only_in_explicit_historical_records() -> None:
    command = "python scripts/apply_migrations.py"
    found: list[Path] = []
    protected_parts = {
        "backup",
        "backups",
        "dump",
        "dumps",
        "export",
        "exports",
        "media",
        "secrets",
    }
    for path in (REPO_ROOT / "docs").rglob("*.md"):
        relative = path.relative_to(REPO_ROOT)
        if (
            any(part.casefold() in protected_parts for part in relative.parts)
            or path.name == ".env"
            or path.name.startswith(".env.")
        ):
            continue
        text = path.read_text(encoding="utf-8")
        if command not in text:
            continue
        found.append(relative)
        assert "REGISTRO HISTÓRICO — NÃO EXECUTAR" in text[:700]

    assert sorted(found) == [
        Path("docs/security/2026-08-10-v1-m06-hardening.md"),
        Path("docs/security/2026-08-20-v1-ledger-hardening-gate.md"),
    ]

    for path in (
        REPO_ROOT / ".github" / "workflows",
        REPO_ROOT / "backend" / "scripts",
    ):
        for candidate in path.rglob("*"):
            if not candidate.is_file() or candidate == LEGACY_PATH:
                continue
            if candidate.suffix not in {".py", ".yml", ".yaml", ".sh"}:
                continue
            source = candidate.read_text(encoding="utf-8")
            assert command not in source
