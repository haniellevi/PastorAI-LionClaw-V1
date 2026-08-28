"""Matriz offline do materializador sanitizado de historico de migrations."""

from __future__ import annotations

import ast
from collections.abc import Iterator
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

import pytest
import psycopg2
from sqlalchemy.engine import make_url

from scripts import capture_migration_history_evidence as capture
from scripts import verify_migration_history_reconciliation as verifier
from tests.conftest_rls import rls_database_url  # noqa: F401


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "backend" / "scripts" / "capture_migration_history_evidence.py"
SQL_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-inventory-capture-v1.sql"
)
KEY = b"k" * 32
AUTHORIZATION = "a" * 64
CAPTURE_DATABASE = "migration_capture_disposable"


@pytest.fixture(scope="module")
def capture_database_url(rls_database_url: str) -> Iterator[str]:
    base = make_url(rls_database_url)
    admin_url = base.set(drivername="postgresql", database="postgres")
    target_url = base.set(drivername="postgresql", database=CAPTURE_DATABASE)
    admin_dsn = admin_url.render_as_string(hide_password=False)
    target_dsn = target_url.render_as_string(hide_password=False)
    admin = psycopg2.connect(admin_dsn)
    try:
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(f"drop database if exists {CAPTURE_DATABASE} with (force)")
            cur.execute(f"create database {CAPTURE_DATABASE}")
    finally:
        admin.close()
    try:
        yield target_dsn
    finally:
        admin = psycopg2.connect(admin_dsn)
        try:
            admin.autocommit = True
            with admin.cursor() as cur:
                cur.execute(
                    f"drop database if exists {CAPTURE_DATABASE} with (force)"
                )
        finally:
            admin.close()


@pytest.fixture
def isolated_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path]:
    migrations = tmp_path / "migrations"
    packets = tmp_path / "packets"
    migrations.mkdir(mode=0o755)
    packets.mkdir(mode=0o755)
    (migrations / "0001_first.sql").write_bytes(b"select 1;\n")
    (migrations / "0002_second.sql").write_bytes(b"select 2;\n")
    for path in migrations.iterdir():
        path.chmod(0o644)
    monkeypatch.setattr(capture, "MIGRATIONS_DIR", migrations)
    monkeypatch.setattr(capture, "PACKETS_DIR", packets)
    monkeypatch.setattr(
        capture,
        "EXPECTED_CATALOG_DIGEST_SHA256",
        capture._catalog_digest(capture._scan_catalog()),
    )
    return migrations, packets


def _sanitized_capture() -> dict[str, Any]:
    return {
        "capture_contract": capture.CAPTURE_CONTRACT,
        "server_version_num": 170006,
        "current_user_matches_session_user": True,
        "system_identifier": "1234567890123456789",
        "database_name": "capture_target_db_93",
        "captured_at_utc": "2026-08-28T21:00:00.123456Z",
        "snapshot_token": "100:200:150,151",
        "isolation_level": "repeatable read",
        "read_only": "on",
        "public_relation_count": 0,
        "public_relkind": None,
        "public_columns_ok": False,
        "public_row_security_active": None,
        "public_rule_count": 0,
        "public_trigger_count": 0,
        "public_rows": [],
        "native_relation_count": 1,
        "native_relkind": "r",
        "native_has_version": True,
        "native_has_name": True,
        "native_name_column_present": True,
        "native_row_security_active": False,
        "native_rule_count": 0,
        "native_trigger_count": 0,
        "native_rows": [
            {"position": 0, "version": "20260828200000", "name": "first"}
        ],
    }


def _expected_target(environment: str, raw: dict[str, Any]) -> str:
    return capture._target_binding(
        bytearray(KEY),
        environment,
        {
            "system_identifier": raw["system_identifier"],
            "database_name": raw["database_name"],
        },
    )


def _open_private_file(tmp_path: Path, name: str, content: bytes) -> int:
    path = tmp_path / name
    path.write_bytes(content)
    path.chmod(0o600)
    return os.open(path, os.O_RDONLY | os.O_CLOEXEC)


def _argv(
    *,
    expected_target: str,
    input_fd: int,
    key_fd: int,
    environment: str = "DEV",
) -> list[str]:
    return [
        "capture",
        "--environment",
        environment,
        "--expected-target-binding-sha256",
        expected_target,
        "--authorization-record-sha256",
        AUTHORIZATION,
        "--confirm",
        capture.CONFIRMATION,
        "--input-fd",
        str(input_fd),
        "--target-key-fd",
        str(key_fd),
    ]


def _run(
    tmp_path: Path,
    raw: dict[str, Any],
    *,
    environment: str = "DEV",
    expected_target: str | None = None,
    key: bytes = KEY,
) -> int:
    input_fd = _open_private_file(
        tmp_path, "capture-input.json", json.dumps(raw).encode("ascii")
    )
    key_fd = _open_private_file(tmp_path, "target-key", key)
    try:
        return capture.main(
            _argv(
                expected_target=expected_target or _expected_target(environment, raw),
                input_fd=input_fd,
                key_fd=key_fd,
                environment=environment,
            )
        )
    finally:
        os.close(input_fd)
        os.close(key_fd)


def test_materializes_exact_unreviewed_packet_and_two_private_receipts(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    migrations, packets = isolated_roots
    raw = _sanitized_capture()
    result = _run(tmp_path, raw)
    output = capsys.readouterr()
    assert result == 0
    assert output.err == ""
    assert output.out == (
        f"{capture.OPERATIONAL_BLOCK}\n"
        "EVIDENCE_CAPTURED_UNREVIEWED\n"
        "FILES_MATERIALIZED=3\n"
    )

    names = sorted(path.name for path in packets.iterdir())
    assert names == [
        "migration-history-reconciliation-dev-evidence-v1-native-capture-receipt-v1.json",
        "migration-history-reconciliation-dev-evidence-v1-public-capture-receipt-v1.json",
        "migration-history-reconciliation-dev-evidence-v1.json",
    ]
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in packets.iterdir())
    package = json.loads((packets / names[-1]).read_text(encoding="ascii"))
    assert package["artifact_state"] == "EVIDENCE_CAPTURED_UNREVIEWED"
    assert package["subject"] == {
        "environment": "DEV",
        "target_binding_sha256": _expected_target("DEV", raw),
        "repository_sha": capture.EXPECTED_REPOSITORY_SHA,
        "catalog_path": capture.CATALOG_PATH,
    }
    assert package["reconciliation"] == {
        "state": "NOT_REVIEWED",
        "catalog_entries": [],
        "native_rows": [],
    }
    assert package["attestation"]["state"] == "NOT_ATTESTED"
    assert package["inventories"]["public_ledger"]["capture_state"] == (
        "ABSENT_CONFIRMED"
    )
    assert package["inventories"]["native_ledger"]["capture_state"] == (
        "PRESENT_COMPLETE"
    )

    monkeypatch.setattr(verifier, "MIGRATIONS_DIR", migrations)
    monkeypatch.setattr(verifier, "PACKETS_DIR", packets)
    with pytest.raises(verifier.HumanEvidenceBlockedError):
        validated = verifier._validate_packet_schema(package)
        verifier._verify_semantics(validated)


def test_receipts_preserve_recomputable_provenance_without_raw_target_or_snapshot(
    isolated_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    _migrations, packets = isolated_roots
    raw = _sanitized_capture()
    assert _run(tmp_path, raw) == 0
    receipts = [
        json.loads(path.read_text(encoding="ascii"))
        for path in packets.iterdir()
        if "receipt" in path.name
    ]
    assert len(receipts) == 2
    snapshot_hashes = set()
    capture_hashes = set()
    for receipt in receipts:
        serialized = json.dumps(receipt, sort_keys=True)
        assert raw["system_identifier"] not in serialized
        assert '"database_name"' not in serialized
        assert raw["database_name"] not in serialized
        assert raw["snapshot_token"] not in serialized
        snapshot = receipt["snapshot_record"]
        assert snapshot["snapshot_record_sha256"] == capture._framed_sha256(
            "pastorai/migration-history/snapshot-record/v1", snapshot["preimage"]
        )
        record = receipt["capture_record"]
        domain = (
            "pastorai/migration-history/capture-record/public/v1"
            if receipt["receipt_role"] == "PUBLIC_LEDGER_CAPTURE"
            else "pastorai/migration-history/capture-record/native/v1"
        )
        assert record["capture_record_sha256"] == capture._framed_sha256(
            domain, record["preimage"]
        )
        snapshot_hashes.add(snapshot["snapshot_record_sha256"])
        capture_hashes.add(record["capture_record_sha256"])
    assert len(snapshot_hashes) == 1
    assert len(capture_hashes) == 2
    assert not snapshot_hashes.intersection(capture_hashes)


def test_package_and_repository_are_bound_into_receipts_against_cross_package_swap(
    isolated_roots: tuple[Path, Path]
) -> None:
    _migrations, _packets = isolated_roots
    raw = capture._validate_capture(_sanitized_capture())
    catalog = capture._scan_catalog()
    target = _expected_target("DEV", _sanitized_capture())
    first = capture._build_artifacts(
        environment="DEV",
        authorization_record=AUTHORIZATION,
        target_binding=target,
        catalog_entries=catalog,
        capture=raw,
    )
    second = capture._build_artifacts(
        environment="PROD",
        authorization_record=AUTHORIZATION,
        target_binding=target,
        catalog_entries=catalog,
        capture=raw,
    )
    for index in (1, 2):
        assert first[index]["snapshot_record"]["snapshot_record_sha256"] != second[
            index
        ]["snapshot_record"]["snapshot_record_sha256"]
        assert first[index]["capture_record"]["capture_record_sha256"] != second[
            index
        ]["capture_record"]["capture_record_sha256"]


def test_expected_catalog_digest_matches_fixed_repository_catalog() -> None:
    assert len(capture._scan_catalog()) == 75
    assert capture._catalog_digest(capture._scan_catalog()) == (
        capture.EXPECTED_CATALOG_DIGEST_SHA256
    )


@pytest.mark.parametrize("mutation", ["modify", "add", "remove"])
def test_catalog_drift_blocks_before_input_read_or_output(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    migrations, packets = isolated_roots
    if mutation == "modify":
        (migrations / "0001_first.sql").write_bytes(b"select 9;\n")
    elif mutation == "add":
        added = migrations / "0003_added.sql"
        added.write_bytes(b"select 3;\n")
        added.chmod(0o644)
    else:
        (migrations / "0002_second.sql").unlink()
    monkeypatch.setattr(
        capture,
        "_read_sanitized_input",
        lambda _descriptor: pytest.fail("catalog drift must block before input"),
    )
    assert capture.EXPECTED_REPOSITORY_SHA == (
        "656d1d9eebe90ad4b2cbb35c21939a6796c46bfe"
    )
    assert _run(tmp_path, _sanitized_capture()) == capture.CatalogError.exit_code
    assert list(packets.iterdir()) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("server_version_num", 160999),
        ("current_user_matches_session_user", False),
        ("isolation_level", "read committed"),
        ("read_only", "off"),
        ("snapshot_token", "not-a-snapshot"),
        ("native_relkind", "v"),
        ("native_row_security_active", True),
        ("native_rule_count", 1),
        ("native_trigger_count", 1),
        ("native_has_version", False),
    ],
)
def test_invalid_capture_metadata_is_blocked_without_outputs(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    _migrations, packets = isolated_roots
    raw = _sanitized_capture()
    raw[field] = value
    assert _run(tmp_path, raw) == capture.InventoryError.exit_code
    assert list(packets.iterdir()) == []


def test_public_exact_shape_and_absence_are_fail_closed(
    isolated_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    _migrations, packets = isolated_roots
    raw = _sanitized_capture()
    raw["public_columns_ok"] = True
    assert _run(tmp_path, raw) == capture.InventoryError.exit_code
    assert list(packets.iterdir()) == []


@pytest.mark.parametrize(
    "rows_key,rows",
    [
        (
            "public_rows",
            [{"position": 0, "name": "0001.sql"}] * (capture.MAX_CAPTURE_ROWS + 1),
        ),
        (
            "native_rows",
            [
                {"position": index, "version": "20260828200000", "name": "first"}
                for index in range(capture.MAX_CAPTURE_ROWS + 1)
            ],
        ),
    ],
)
def test_row_limit_never_truncates_into_complete_capture(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    rows_key: str,
    rows: list[dict[str, Any]],
) -> None:
    _migrations, packets = isolated_roots
    raw = _sanitized_capture()
    raw[rows_key] = rows
    if rows_key == "public_rows":
        raw.update(
            public_relation_count=1,
            public_relkind="r",
            public_columns_ok=True,
            public_row_security_active=False,
        )
    assert _run(tmp_path, raw) == capture.InventoryError.exit_code
    assert list(packets.iterdir()) == []


def test_wrong_target_binding_and_bad_key_fail_without_echo_or_output(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    raw = _sanitized_capture()
    assert _run(tmp_path, raw, expected_target="f" * 64) == (
        capture.TargetBindingError.exit_code
    )
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert raw["system_identifier"] not in output
    assert raw["database_name"] not in output
    assert list(packets.iterdir()) == []

    assert _run(tmp_path, raw, key=b"short") == capture.TargetBindingError.exit_code
    assert list(packets.iterdir()) == []


def test_raw_and_hex_target_keys_produce_same_binding(
    isolated_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    _migrations, packets = isolated_roots
    raw = _sanitized_capture()
    assert _run(tmp_path, raw, key=KEY.hex().encode("ascii")) == 0
    package = json.loads(
        (
            packets
            / "migration-history-reconciliation-dev-evidence-v1.json"
        ).read_text("ascii")
    )
    assert package["subject"]["target_binding_sha256"] == _expected_target("DEV", raw)


def test_sanitized_input_and_key_may_arrive_through_closed_fifos(
    isolated_roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _migrations, packets = isolated_roots
    raw = _sanitized_capture()
    input_read, input_write = os.pipe()
    key_read, key_write = os.pipe()
    try:
        os.write(input_write, json.dumps(raw).encode("ascii"))
        os.write(key_write, KEY)
        os.close(input_write)
        os.close(key_write)
        result = capture.main(
            _argv(
                expected_target=_expected_target("DEV", raw),
                input_fd=input_read,
                key_fd=key_read,
            )
        )
    finally:
        os.close(input_read)
        os.close(key_read)
    assert result == 0
    assert len(list(packets.iterdir())) == 3
    assert capture.OPERATIONAL_BLOCK in capsys.readouterr().out


def test_regular_input_refstat_detects_in_place_mutation(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _migrations, packets = isolated_roots
    raw = _sanitized_capture()
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(raw), encoding="ascii")
    input_path.chmod(0o600)
    key_path = tmp_path / "key"
    key_path.write_bytes(KEY)
    key_path.chmod(0o600)
    input_fd = os.open(input_path, os.O_RDONLY)
    key_fd = os.open(key_path, os.O_RDONLY)
    real_read = capture._read_fd_bytes

    def mutating_read(descriptor: int, maximum: int) -> bytes:
        content = real_read(descriptor, maximum)
        if descriptor == input_fd:
            input_path.chmod(0o400)
        return content

    monkeypatch.setattr(capture, "_read_fd_bytes", mutating_read)
    try:
        result = capture.main(
            _argv(
                expected_target=_expected_target("DEV", raw),
                input_fd=input_fd,
                key_fd=key_fd,
            )
        )
    finally:
        os.close(input_fd)
        os.close(key_fd)
    assert result == capture.InputError.exit_code
    assert list(packets.iterdir()) == []


def test_regular_key_refstat_detects_in_place_mutation(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _migrations, packets = isolated_roots
    raw = _sanitized_capture()
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(raw), encoding="ascii")
    input_path.chmod(0o600)
    key_path = tmp_path / "key"
    key_path.write_bytes(KEY)
    key_path.chmod(0o600)
    input_fd = os.open(input_path, os.O_RDONLY)
    key_fd = os.open(key_path, os.O_RDONLY)
    real_read = capture._read_fd_bytes

    def mutating_read(descriptor: int, maximum: int) -> bytes:
        content = real_read(descriptor, maximum)
        if descriptor == key_fd:
            key_path.chmod(0o400)
        return content

    monkeypatch.setattr(capture, "_read_fd_bytes", mutating_read)
    try:
        result = capture.main(
            _argv(
                expected_target=_expected_target("DEV", raw),
                input_fd=input_fd,
                key_fd=key_fd,
            )
        )
    finally:
        os.close(input_fd)
        os.close(key_fd)
    assert result == capture.TargetBindingError.exit_code
    assert list(packets.iterdir()) == []


def test_all_zero_target_key_is_rejected(
    isolated_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    _migrations, packets = isolated_roots
    assert _run(tmp_path, _sanitized_capture(), key=b"\x00" * 32) == (
        capture.TargetBindingError.exit_code
    )
    assert list(packets.iterdir()) == []


def test_input_and_key_regular_files_must_be_private(
    isolated_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    _migrations, packets = isolated_roots
    raw = _sanitized_capture()
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(raw), encoding="ascii")
    input_path.chmod(0o644)
    key_path = tmp_path / "key"
    key_path.write_bytes(KEY)
    key_path.chmod(0o600)
    input_fd = os.open(input_path, os.O_RDONLY)
    key_fd = os.open(key_path, os.O_RDONLY)
    try:
        result = capture.main(
            _argv(
                expected_target=_expected_target("DEV", raw),
                input_fd=input_fd,
                key_fd=key_fd,
            )
        )
    finally:
        os.close(input_fd)
        os.close(key_fd)
    assert result == capture.InputError.exit_code
    assert list(packets.iterdir()) == []


def test_nested_duplicate_and_float_input_are_rejected(
    isolated_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    _migrations, _packets = isolated_roots
    with pytest.raises(capture.InputError):
        capture._parse_input(b'{"outer":{"secret":1,"secret":2}}')
    with pytest.raises(capture.InputError):
        capture._parse_input(b'{"value":1.5}')


def test_existing_output_is_never_overwritten_and_partial_outputs_are_cleaned(
    isolated_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    _migrations, packets = isolated_roots
    existing = packets / "migration-history-reconciliation-dev-evidence-v1.json"
    existing.write_bytes(b"sentinel")
    existing.chmod(0o600)
    assert _run(tmp_path, _sanitized_capture()) == capture.OutputError.exit_code
    assert existing.read_bytes() == b"sentinel"
    assert sorted(path.name for path in packets.iterdir()) == [existing.name]


def test_output_path_inode_swap_is_detected_and_attacker_file_is_not_deleted(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _migrations, packets = isolated_roots
    target = packets / capture.CANONICAL_OUTPUT_BASENAMES["DEV"]
    sentinel = b"attacker-sentinel"
    real_write = capture._write_all
    swapped = False

    def swapping_write(descriptor: int, content: bytes) -> None:
        nonlocal swapped
        real_write(descriptor, content)
        if not swapped:
            swapped = True
            target.unlink()
            target.write_bytes(sentinel)
            target.chmod(0o600)

    monkeypatch.setattr(capture, "_write_all", swapping_write)
    assert _run(tmp_path, _sanitized_capture()) == capture.OutputError.exit_code
    assert target.read_bytes() == sentinel
    assert sorted(path.name for path in packets.iterdir()) == [target.name]


def test_output_directory_chmod_during_write_is_detected(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _migrations, packets = isolated_roots
    real_write = capture._write_all
    changed = False

    def chmod_during_write(descriptor: int, content: bytes) -> None:
        nonlocal changed
        real_write(descriptor, content)
        if not changed:
            changed = True
            packets.chmod(0o700)

    monkeypatch.setattr(capture, "_write_all", chmod_during_write)
    assert _run(tmp_path, _sanitized_capture()) == capture.OutputError.exit_code
    assert list(packets.iterdir()) == []


def test_output_directory_replacement_during_write_is_detected(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _migrations, packets = isolated_roots
    original = packets.with_name("packets-original")
    real_write = capture._write_all
    replaced = False

    def replace_during_write(descriptor: int, content: bytes) -> None:
        nonlocal replaced
        real_write(descriptor, content)
        if not replaced:
            replaced = True
            packets.rename(original)
            packets.mkdir(mode=0o755)

    monkeypatch.setattr(capture, "_write_all", replace_during_write)
    assert _run(tmp_path, _sanitized_capture()) == capture.OutputError.exit_code
    assert list(packets.iterdir()) == []
    assert list(original.iterdir()) == []


def test_output_hardlink_created_during_write_is_detected(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _migrations, packets = isolated_roots
    target = packets / capture.CANONICAL_OUTPUT_BASENAMES["DEV"]
    attacker_link = packets / "attacker-hardlink"
    real_write = capture._write_all
    linked = False

    def hardlink_during_write(descriptor: int, content: bytes) -> None:
        nonlocal linked
        real_write(descriptor, content)
        if not linked:
            linked = True
            os.link(target, attacker_link)

    monkeypatch.setattr(capture, "_write_all", hardlink_during_write)
    assert _run(tmp_path, _sanitized_capture()) == capture.OutputError.exit_code
    assert not target.exists()
    assert attacker_link.is_file()


@pytest.mark.parametrize("attack", ["rewrite_same_size", "chmod"])
def test_output_change_between_final_check_and_directory_reopen_is_detected(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    _migrations, packets = isolated_roots
    target = packets / capture.CANONICAL_OUTPUT_BASENAMES["DEV"]
    real_open_directory = capture._open_directory
    packets_open_count = 0

    def attack_before_reopen(
        path: Path, error_type: type[capture.CaptureError]
    ) -> tuple[int, capture.FileSnapshot]:
        nonlocal packets_open_count
        if path == packets:
            packets_open_count += 1
            if packets_open_count == 2:
                if attack == "rewrite_same_size":
                    content = target.read_bytes()
                    target.write_bytes(b"X" + content[1:])
                else:
                    target.chmod(0o400)
        return real_open_directory(path, error_type)

    monkeypatch.setattr(capture, "_open_directory", attack_before_reopen)
    assert _run(tmp_path, _sanitized_capture()) == capture.OutputError.exit_code
    assert list(packets.iterdir()) == []


def test_native_human_like_name_is_redacted_from_all_materialized_artifacts(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    raw = _sanitized_capture()
    marker = "joao_silva_private"
    raw["native_rows"][0]["name"] = marker
    assert _run(tmp_path, raw) == 0
    captured = capsys.readouterr()
    materialized = captured.out + captured.err
    for path in packets.iterdir():
        materialized += path.read_text(encoding="ascii")
    assert marker not in materialized
    package = json.loads(
        (
            packets / capture.CANONICAL_OUTPUT_BASENAMES["DEV"]
        ).read_text(encoding="ascii")
    )
    assert package["inventories"]["native_ledger"]["rows"][0]["name"] is None


def test_native_name_is_redacted_even_when_it_matches_a_catalog_stem(
    isolated_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    _migrations, packets = isolated_roots
    raw = _sanitized_capture()
    raw["native_rows"][0]["name"] = "0001_first"
    assert _run(tmp_path, raw) == 0
    package = json.loads(
        (
            packets / capture.CANONICAL_OUTPUT_BASENAMES["DEV"]
        ).read_text(encoding="ascii")
    )
    assert package["inventories"]["native_ledger"]["rows"][0]["name"] is None


def test_public_ledger_known_out_of_order_subset_is_materialized(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migrations, packets = isolated_roots
    third = migrations / "0003_third.sql"
    third.write_bytes(b"select 3;\n")
    third.chmod(0o644)
    monkeypatch.setattr(
        capture,
        "EXPECTED_CATALOG_DIGEST_SHA256",
        capture._catalog_digest(capture._scan_catalog()),
    )
    raw = _sanitized_capture()
    raw.update(
        public_relation_count=1,
        public_relkind="r",
        public_columns_ok=True,
        public_row_security_active=False,
        public_rows=[
            {"position": 0, "name": "0002_second.sql"},
            {"position": 1, "name": "0001_first.sql"},
        ],
    )
    assert _run(tmp_path, raw) == 0
    package = json.loads(
        (
            packets / capture.CANONICAL_OUTPUT_BASENAMES["DEV"]
        ).read_text(encoding="ascii")
    )
    assert package["inventories"]["public_ledger"]["rows"] == raw["public_rows"]


def test_public_ledger_unknown_name_is_blocked_without_echo_or_output(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    raw = _sanitized_capture()
    raw.update(
        public_relation_count=1,
        public_relkind="r",
        public_columns_ok=True,
        public_row_security_active=False,
        public_rows=[{"position": 0, "name": "member_private.sql"}],
    )
    assert _run(tmp_path, raw) == capture.InventoryError.exit_code
    captured = capsys.readouterr()
    assert "member_private.sql" not in captured.out + captured.err
    assert list(packets.iterdir()) == []


def test_environment_selects_the_only_canonical_output_basename(
    isolated_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    _migrations, packets = isolated_roots
    raw = _sanitized_capture()
    assert _run(tmp_path, raw, environment="PROD") == 0
    assert capture.CANONICAL_OUTPUT_BASENAMES["PROD"] in {
        path.name for path in packets.iterdir()
    }
    assert not any("-dev-" in path.name for path in packets.iterdir())


def test_sql_is_pinned_read_only_and_explicitly_rolls_back() -> None:
    sql = SQL_PATH.read_bytes()
    assert hashlib.sha256(sql).hexdigest() == capture.CAPTURE_SQL_SHA256
    text = sql.decode("ascii").lower()
    assert text.startswith("begin transaction isolation level repeatable read read only;")
    assert text.endswith("\nrollback;\n")
    assert "pg_catalog.pg_control_system()" in text
    assert "limit 2049" in text
    assert "idle_in_transaction_session_timeout" in text
    assert "pg_catalog.coalesce" not in text
    assert "name::pg_catalog.text as name from supabase_migrations" not in text
    assert text.count(
        "version::pg_catalog.text as version, null::pg_catalog.text as name "
        "from supabase_migrations.schema_migrations"
    ) == 2
    assert "insert " not in text
    assert "update " not in text
    assert "delete " not in text
    assert "create " not in text
    assert "alter " not in text
    assert "drop " not in text


@pytest.mark.rls_integration
@pytest.mark.parametrize(
    "public_present,native_has_name",
    [(False, True), (True, False)],
)
def test_exact_capture_sql_bytes_on_postgresql17_are_read_only_and_complete(
    capture_database_url: str,
    public_present: bool,
    native_has_name: bool,
) -> None:
    with psycopg2.connect(capture_database_url) as setup, setup.cursor() as cur:
        cur.execute("drop table if exists public.schema_migrations cascade")
        cur.execute("drop schema if exists supabase_migrations cascade")
        cur.execute("create schema supabase_migrations")
        if public_present:
            cur.execute(
                """
                create table public.schema_migrations (
                    name text primary key,
                    applied_at timestamptz not null default now()
                )
                """
            )
            cur.execute(
                "insert into public.schema_migrations (name) values (%s)",
                ("0001_first.sql",),
            )
        if native_has_name:
            cur.execute(
                """
                create table supabase_migrations.schema_migrations (
                    version text primary key,
                    name text
                )
                """
            )
            cur.execute(
                "insert into supabase_migrations.schema_migrations "
                "(version, name) values (%s, %s)",
                ("20260828200000", "0001_first"),
            )
        else:
            cur.execute(
                """
                create table supabase_migrations.schema_migrations (
                    version text primary key
                )
                """
            )
            cur.execute(
                "insert into supabase_migrations.schema_migrations "
                "(version) values (%s)",
                ("20260828200000",),
            )

    sql_bytes = SQL_PATH.read_bytes()
    rollback_bytes = b"rollback;\n"
    assert sql_bytes.endswith(rollback_bytes)
    capture_bytes = sql_bytes[: -len(rollback_bytes)]
    assert capture_bytes + rollback_bytes == sql_bytes
    connection = psycopg2.connect(capture_database_url)
    connection.autocommit = True
    try:
        with connection.cursor() as cur:
            cur.execute(capture_bytes.decode("ascii"))
            row = cur.fetchone()
            assert row is not None and len(row) == 1
            result = row[0]
            cur.execute(rollback_bytes.decode("ascii"))
        assert connection.get_transaction_status() == (
            psycopg2.extensions.TRANSACTION_STATUS_IDLE
        )
    finally:
        connection.close()

    assert result["capture_contract"] == capture.CAPTURE_CONTRACT
    assert 170000 <= result["server_version_num"] <= 179999
    assert result["current_user_matches_session_user"] is True
    assert result["isolation_level"] == "repeatable read"
    assert result["read_only"] == "on"
    assert result["public_relation_count"] == int(public_present)
    assert result["public_rows"] == (
        [{"position": 0, "name": "0001_first.sql"}] if public_present else []
    )
    assert result["native_relation_count"] == 1
    assert result["native_has_name"] is native_has_name
    assert result["native_name_column_present"] is native_has_name
    assert result["native_rows"] == [
        {
            "position": 0,
            "version": "20260828200000",
            "name": None,
        }
    ]

    with psycopg2.connect(capture_database_url) as check, check.cursor() as cur:
        cur.execute("select count(*) from supabase_migrations.schema_migrations")
        assert cur.fetchone() == (1,)
        if public_present:
            cur.execute("select count(*) from public.schema_migrations")
            assert cur.fetchone() == (1,)


def test_sql_drift_blocks_before_input_or_output(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _migrations, packets = isolated_roots
    drift = tmp_path / "capture.sql"
    drift.write_bytes(SQL_PATH.read_bytes() + b"\n")
    drift.chmod(0o644)
    monkeypatch.setattr(capture, "CAPTURE_SQL_PATH", drift)
    with pytest.raises(capture.SqlContractError):
        capture._validate_runtime_and_sql()
    assert list(packets.iterdir()) == []


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--environment", "DEV"],
        ["--environment", "dev", "--confirm", capture.CONFIRMATION],
        ["--unknown", "secret-value"],
        ["--repository-sha", "b" * 40],
        ["--output-basename", "migration-history-reconciliation-dev.json"],
    ],
)
def test_cli_is_sanitized_and_rejected_before_io(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        capture,
        "_validate_runtime_and_sql",
        lambda: pytest.fail("invalid CLI must not touch local inputs"),
    )
    result = capture.main(["capture", *argv])
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert result == 2
    assert "secret-value" not in output
    assert output.splitlines()[0] == capture.OPERATIONAL_BLOCK


def test_help_is_blocked_and_has_no_side_effect(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        capture,
        "_validate_runtime_and_sql",
        lambda: pytest.fail("help must not inspect runtime"),
    )
    assert capture.main(["capture", "--help"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == f"{capture.OPERATIONAL_BLOCK}\n{capture.HELP_TEXT}\n"


def test_materializer_has_no_database_network_runner_environment_or_proc_dependency() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Attribute):
            attributes.add(node.attr)
    assert not imported.intersection(
        {
            "psycopg2",
            "sqlalchemy",
            "socket",
            "subprocess",
            "requests",
            "urllib",
            "http",
            "asyncio",
        }
    )
    assert "apply_migrations" not in source
    assert "verify_migration_history_reconciliation" not in source
    assert "/proc" not in source
    assert not attributes.intersection({"environ", "getenv", "putenv", "unsetenv"})


def test_binary_framing_matches_offline_verifier_without_importing_it() -> None:
    value = {"z": [None, True, 7, "á"], "a": {"x": False}}
    assert capture._framed_sha256("pastorai/test/v1", value) == (
        "46e0599f943c4214180d8f2941b986f9650f5ac7aa93917eb07f5c4009de05c6"
    )
    assert capture._framed_sha256("pastorai/test/v1", value) == verifier._framed_sha256(
        "pastorai/test/v1", value
    )


def test_environment_is_cryptographically_bound_against_dev_prod_swap() -> None:
    raw = _sanitized_capture()
    assert _expected_target("DEV", raw) != _expected_target("PROD", raw)


def test_catalog_change_between_scans_blocks_before_materialization(
    isolated_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _migrations, packets = isolated_roots
    original = capture._scan_catalog
    calls = 0

    def changing_catalog() -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        result = original()
        if calls == 2:
            changed = copy.deepcopy(result)
            changed[0]["sha256"] = "0" * 64
            return changed
        return result

    monkeypatch.setattr(capture, "_scan_catalog", changing_catalog)
    assert _run(tmp_path, _sanitized_capture()) == capture.CatalogError.exit_code
    assert list(packets.iterdir()) == []
