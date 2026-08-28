"""Contrato offline e fail-closed da reconciliação humana de migrations."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any

import pytest

from scripts import verify_migration_history_reconciliation as verifier


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "backend" / "scripts" / "verify_migration_history_reconciliation.py"
SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "migration-history-reconciliation.schema.json"
)
TEMPLATE_PATH = (
    REPO_ROOT
    / "docs"
    / "governance"
    / "migrations"
    / "packets"
    / "migration-history-reconciliation-template-v1.json"
)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
SHA_G = "3" * 64
SHA_H = "4" * 64
SHA_I = "5" * 64
SHA_J = "6" * 64
SHA_K = "7" * 64
SHA_L = "8" * 64
SHA_M = "9" * 64
TARGET_SHA = "1" * 64


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
    (migrations / "0001_first.sql").chmod(0o644)
    (migrations / "0002_second.sql").chmod(0o644)
    monkeypatch.setattr(verifier, "MIGRATIONS_DIR", migrations)
    monkeypatch.setattr(verifier, "PACKETS_DIR", packets)
    return migrations, packets


def _catalog_packet() -> dict[str, Any]:
    entries = verifier._scan_catalog()
    return {
        "algorithm": verifier.CATALOG_ALGORITHM,
        "entries": entries,
        "digest_sha256": verifier._framed_sha256(
            "pastorai/migration-history/catalog/v1",
            {"algorithm": verifier.CATALOG_ALGORITHM, "entries": entries},
        ),
    }


def _inventory(
    *,
    source: str,
    query_contract: str,
    rows: list[dict[str, Any]],
    capture_record_sha256: str,
    capture_state: str = "PRESENT_COMPLETE",
) -> dict[str, Any]:
    domain = (
        "pastorai/migration-history/public-ledger/v1"
        if source == verifier.PUBLIC_SOURCE
        else "pastorai/migration-history/native-ledger/v1"
    )
    return {
        "source": source,
        "capture_state": capture_state,
        "target_binding_sha256": TARGET_SHA,
        "captured_at_utc": "2026-08-28T16:00:00Z",
        "authorization_record_sha256": SHA_A,
        "capture_record_sha256": capture_record_sha256,
        "snapshot_record_sha256": SHA_I,
        "completeness_attested": True,
        "query_contract": query_contract,
        "rows": rows,
        "rows_digest_sha256": verifier._framed_sha256(
            domain,
            {"source": source, "query_contract": query_contract, "rows": rows},
        ),
    }


def _complete_packet() -> dict[str, Any]:
    catalog = _catalog_packet()
    public_rows = [
        {
            "position": 0,
            "name": catalog["entries"][0]["name"],
        }
    ]
    native_rows = [{"position": 0, "version": "20260828150000", "name": None}]
    packet: dict[str, Any] = {
        "contract_version": verifier.CONTRACT_VERSION,
        "package_id": "packet",
        "artifact_state": "HUMAN_REVIEW_COMPLETE",
        "safety_contract": dict(verifier.SAFETY_CONTRACT),
        "subject": {
            "environment": "DEV",
            "target_binding_sha256": TARGET_SHA,
            "repository_sha": "2" * 40,
            "catalog_path": verifier.CATALOG_PATH,
        },
        "catalog": catalog,
        "inventories": {
            "public_ledger": _inventory(
                source=verifier.PUBLIC_SOURCE,
                query_contract=verifier.PUBLIC_QUERY_CONTRACT,
                rows=public_rows,
                capture_record_sha256=SHA_B,
            ),
            "native_ledger": _inventory(
                source=verifier.NATIVE_SOURCE,
                query_contract=verifier.NATIVE_QUERY_CONTRACT,
                rows=native_rows,
                capture_record_sha256=SHA_C,
            ),
        },
        "reconciliation": {
            "state": "HUMAN_REVIEW_COMPLETE",
            "catalog_entries": [
                {
                    "position": 0,
                    "catalog_name": catalog["entries"][0]["name"],
                    "human_determination": "APPLIED_CONFIRMED",
                    "public_row_position": 0,
                    "native_row_positions": [0],
                    "basis_record_sha256": [SHA_J, SHA_B, SHA_C],
                    "evidence_record_sha256": SHA_J,
                    "decision_record_sha256": SHA_D,
                },
                {
                    "position": 1,
                    "catalog_name": catalog["entries"][1]["name"],
                    "human_determination": "APPLIED_CONFIRMED",
                    "public_row_position": None,
                    "native_row_positions": [],
                    "basis_record_sha256": [SHA_K, SHA_B, SHA_C],
                    "evidence_record_sha256": SHA_K,
                    "decision_record_sha256": SHA_E,
                },
            ],
            "native_rows": [
                {
                    "native_row_position": 0,
                    "disposition": "MAPS_TO_CATALOG",
                    "catalog_names": [catalog["entries"][0]["name"]],
                    "basis_record_sha256": [SHA_L, SHA_B, SHA_C],
                    "evidence_record_sha256": SHA_L,
                    "decision_record_sha256": SHA_M,
                }
            ],
        },
        "attestation": {
            "state": "ATTESTED_REVIEW_ONLY",
            "inventory_attestation_record_sha256": SHA_F,
            "migration_owner_decision_record_sha256": SHA_G,
            "independent_review_record_sha256": SHA_H,
            "attested_at_utc": "2026-08-28T17:00:00Z",
            "payload_sha256": None,
        },
    }
    _refresh_attestation(packet)
    return packet


def _unreviewed_packet() -> dict[str, Any]:
    packet = _complete_packet()
    packet["package_id"] = verifier.UNREVIEWED_PACKAGE_IDS["DEV"]
    packet["artifact_state"] = "EVIDENCE_CAPTURED_UNREVIEWED"
    packet["subject"]["repository_sha"] = verifier.EXPECTED_CAPTURE_REPOSITORY_SHA
    packet["reconciliation"] = {
        "state": "NOT_REVIEWED",
        "catalog_entries": [],
        "native_rows": [],
    }
    packet["attestation"] = {
        "state": "NOT_ATTESTED",
        "inventory_attestation_record_sha256": None,
        "migration_owner_decision_record_sha256": None,
        "independent_review_record_sha256": None,
        "attested_at_utc": None,
        "payload_sha256": None,
    }
    return packet


def _refresh_catalog_digest(packet: dict[str, Any]) -> None:
    packet["catalog"]["digest_sha256"] = verifier._framed_sha256(
        "pastorai/migration-history/catalog/v1",
        {
            "algorithm": packet["catalog"]["algorithm"],
            "entries": packet["catalog"]["entries"],
        },
    )


def _refresh_inventory_digest(packet: dict[str, Any], key: str) -> None:
    inventory = packet["inventories"][key]
    domain = (
        "pastorai/migration-history/public-ledger/v1"
        if key == "public_ledger"
        else "pastorai/migration-history/native-ledger/v1"
    )
    inventory["rows_digest_sha256"] = verifier._framed_sha256(
        domain,
        {
            "source": inventory["source"],
            "query_contract": inventory["query_contract"],
            "rows": inventory["rows"],
        },
    )


def _refresh_attestation(packet: dict[str, Any]) -> None:
    payload = {
        key: packet[key]
        for key in (
            "contract_version",
            "package_id",
            "artifact_state",
            "safety_contract",
            "subject",
            "catalog",
            "inventories",
            "reconciliation",
        )
    }
    packet["attestation"]["payload_sha256"] = verifier._framed_sha256(
        "pastorai/migration-history/attestation/v1", payload
    )


def _write_packet(packets: Path, packet: dict[str, Any], name: str = "packet.json") -> Path:
    path = packets / name
    path.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o644)
    return path


def _main_for_packet(
    packets: Path,
    packet: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str]:
    basename = (
        f"{packet['package_id']}.json"
        if packet["artifact_state"] == "EVIDENCE_CAPTURED_UNREVIEWED"
        else "packet.json"
    )
    _write_packet(packets, packet, basename)
    result = verifier.main(["verifier", "--packet", basename])
    captured = capsys.readouterr()
    return result, captured.out + captured.err


def test_complete_packet_is_only_valid_for_human_review(
    isolated_roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    assert len(packet["inventories"]["public_ledger"]["rows"]) == 1
    assert sum(
        entry["human_determination"] == "APPLIED_CONFIRMED"
        for entry in packet["reconciliation"]["catalog_entries"]
    ) == 2
    result, output = _main_for_packet(packets, packet, capsys)
    assert result == 0
    assert output == "OPERATIONAL_AUTHORIZATION=BLOCKED\nVALID_FOR_HUMAN_REVIEW_ONLY\n"


def test_captured_unreviewed_packet_is_integrity_checked_then_human_blocked(
    isolated_roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _migrations, packets = isolated_roots
    result, output = _main_for_packet(packets, _unreviewed_packet(), capsys)
    assert result == verifier.HumanEvidenceBlockedError.exit_code
    assert output == (
        "OPERATIONAL_AUTHORIZATION=BLOCKED\n"
        "RECONCILIATION_CONTRACT_BLOCKED:HUMAN_EVIDENCE_BLOCKED\n"
    )


@pytest.mark.parametrize("mutation,expected", [
    ("snapshot_mismatch", verifier.InventoryBlockedError.exit_code),
    ("rows_digest", verifier.SchemaError.exit_code),
    ("native_empty", verifier.InventoryBlockedError.exit_code),
])
def test_captured_unreviewed_does_not_hide_inventory_integrity_failures(
    isolated_roots: tuple[Path, Path],
    mutation: str,
    expected: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    packet = _unreviewed_packet()
    if mutation == "snapshot_mismatch":
        packet["inventories"]["native_ledger"]["snapshot_record_sha256"] = SHA_G
    elif mutation == "rows_digest":
        packet["inventories"]["public_ledger"]["rows_digest_sha256"] = SHA_G
    else:
        packet["inventories"]["native_ledger"]["rows"] = []
        _refresh_inventory_digest(packet, "native_ledger")
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == expected


@pytest.mark.parametrize("inventory_name", ["public_ledger", "native_ledger"])
def test_captured_unreviewed_requires_both_inventories_captured(
    isolated_roots: tuple[Path, Path],
    inventory_name: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    packet = _unreviewed_packet()
    packet["inventories"][inventory_name].update(
        capture_state="NOT_CAPTURED",
        target_binding_sha256=None,
        captured_at_utc=None,
        authorization_record_sha256=None,
        capture_record_sha256=None,
        snapshot_record_sha256=None,
        completeness_attested=False,
        rows=[],
        rows_digest_sha256=None,
    )
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.SchemaError.exit_code


@pytest.mark.parametrize("mutation", ["review_state", "decision", "attestation"])
def test_captured_unreviewed_cannot_smuggle_review_or_attestation(
    isolated_roots: tuple[Path, Path],
    mutation: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    packet = _unreviewed_packet()
    if mutation == "review_state":
        packet["reconciliation"]["state"] = "HUMAN_REVIEW_INCOMPLETE"
    elif mutation == "decision":
        packet["reconciliation"] = copy.deepcopy(
            _complete_packet()["reconciliation"]
        )
    else:
        packet["attestation"] = copy.deepcopy(_complete_packet()["attestation"])
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.SchemaError.exit_code


@pytest.mark.parametrize("mutation", ["repository_sha", "dev_prod_swap"])
def test_captured_unreviewed_is_bound_to_baseline_and_environment_basename(
    isolated_roots: tuple[Path, Path],
    mutation: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    packet = _unreviewed_packet()
    if mutation == "repository_sha":
        packet["subject"]["repository_sha"] = "b" * 40
    else:
        packet["package_id"] = verifier.UNREVIEWED_PACKAGE_IDS["PROD"]
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.SchemaError.exit_code


def test_template_is_deny_state_with_exact_current_catalog() -> None:
    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert template["artifact_state"] == "TEMPLATE_NOT_EVIDENCE"
    assert template["subject"]["environment"] == "UNBOUND"
    assert template["subject"]["target_binding_sha256"] is None
    assert len(template["catalog"]["entries"]) == 75
    expected_entries = []
    for position, path in enumerate(sorted((REPO_ROOT / "backend" / "migrations").glob("*.sql"))):
        content = path.read_bytes()
        expected_entries.append(
            {
                "position": position,
                "name": path.name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        )
    assert template["catalog"]["entries"] == expected_entries
    assert all(
        inventory["capture_state"] == "NOT_CAPTURED"
        for inventory in template["inventories"].values()
    )
    validated = verifier._validate_packet_schema(template)
    with pytest.raises(verifier.HumanEvidenceBlockedError):
        verifier._verify_semantics(validated)


def test_binary_framing_has_stable_golden_vector_and_key_order() -> None:
    value = {"z": [None, True, 7, "á"], "a": {"x": False}}
    expected = "46e0599f943c4214180d8f2941b986f9650f5ac7aa93917eb07f5c4009de05c6"
    assert verifier._framed_sha256("pastorai/test/v1", value) == expected
    assert verifier._framed_sha256("pastorai/test/v1", value) == verifier._framed_sha256(
        "pastorai/test/v1", {"a": {"x": False}, "z": [None, True, 7, "á"]}
    )
    assert verifier._framed_sha256("pastorai/test/v2", value) != expected
    assert verifier._framed_sha256("pastorai/test/v1", ["ab", "c"]) != verifier._framed_sha256(
        "pastorai/test/v1", ["a", "bc"]
    )


@pytest.mark.parametrize(
    "argv",
    [
        (),
        ("--packet", "../secret.json"),
        ("--packet", "/tmp/secret.json"),
        ("--packet", "Packet.json"),
        ("--packet", "packet.json", "postgresql://secret.invalid/db"),
        ("--unknown", "token-secret"),
    ],
)
def test_cli_errors_are_sanitized_before_io(
    argv: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        verifier,
        "_load_packet_bytes",
        lambda _name: pytest.fail("invalid CLI must not read a packet"),
    )
    result = verifier.main(["verifier", *argv])
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert result in {2, 3}
    assert "secret" not in output
    assert verifier.OPERATIONAL_BLOCK in output
    assert output.splitlines()[0] == verifier.OPERATIONAL_BLOCK


def test_help_is_static_and_blocked_before_any_explanation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = verifier.main(["verifier", "--help"])
    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert captured.out == f"{verifier.OPERATIONAL_BLOCK}\n{verifier.HELP_TEXT}\n"


@pytest.mark.parametrize(
    "raw",
    [
        b'{"contract_version":"1.0","contract_version":"secret"}',
        b"\xef\xbb\xbf{}",
        b"\xff\xfe",
        b'{"value":NaN}',
        b'{"value":1.25}',
        (b'{"a":' * 40) + b"null" + (b"}" * 40),
    ],
)
def test_invalid_json_is_blocked_without_echo(
    isolated_roots: tuple[Path, Path],
    raw: bytes,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    (packets / "packet.json").write_bytes(raw)
    (packets / "packet.json").chmod(0o644)
    result = verifier.main(["verifier", "--packet", "packet.json"])
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert result == verifier.SchemaError.exit_code
    assert output == (
        "OPERATIONAL_AUTHORIZATION=BLOCKED\n"
        "RECONCILIATION_CONTRACT_BLOCKED:SCHEMA_INVALID\n"
    )


def test_nested_duplicate_key_is_rejected(
    isolated_roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _migrations, packets = isolated_roots
    packet_path = packets / "packet.json"
    packet_path.write_bytes(b'{"outer":{"key":1,"key":2}}')
    packet_path.chmod(0o644)
    result = verifier.main(["verifier", "--packet", "packet.json"])
    output = capsys.readouterr()
    assert result == verifier.SchemaError.exit_code
    assert output.out + output.err == (
        f"{verifier.OPERATIONAL_BLOCK}\n"
        "RECONCILIATION_CONTRACT_BLOCKED:SCHEMA_INVALID\n"
    )


def test_packet_over_size_limit_is_rejected_before_json_parse(
    isolated_roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _migrations, packets = isolated_roots
    packet_path = packets / "packet.json"
    packet_path.write_bytes(b"{" + b"x" * verifier.MAX_PACKET_BYTES)
    packet_path.chmod(0o644)
    result = verifier.main(["verifier", "--packet", "packet.json"])
    output = capsys.readouterr()
    assert result == verifier.PacketIoError.exit_code
    assert output.out + output.err == (
        f"{verifier.OPERATIONAL_BLOCK}\n"
        "RECONCILIATION_CONTRACT_BLOCKED:PACKET_IO_INVALID\n"
    )


def test_extra_key_and_strict_boolean_are_rejected(
    isolated_roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    packet["secret_value"] = "must-never-be-echoed"
    result, output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.SchemaError.exit_code
    assert "must-never-be-echoed" not in output

    packet = _complete_packet()
    packet["inventories"]["public_ledger"]["completeness_attested"] = 1
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.SchemaError.exit_code

    packet = _complete_packet()
    packet["catalog"]["entries"][0]["position"] = True
    _refresh_catalog_digest(packet)
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.SchemaError.exit_code


@pytest.mark.parametrize(
    "kind", ["symlink", "hardlink", "group_writable", "world_writable", "executable"]
)
def test_packet_filesystem_hardening(
    isolated_roots: tuple[Path, Path], kind: str
) -> None:
    _migrations, packets = isolated_roots
    source = packets / "source.json"
    source.write_text("{}", encoding="utf-8")
    source.chmod(0o644)
    target = packets / "packet.json"
    if kind == "symlink":
        target.symlink_to(source.name)
    elif kind == "hardlink":
        os.link(source, target)
    else:
        target.write_text("{}", encoding="utf-8")
        target.chmod(
            0o664
            if kind == "group_writable"
            else 0o666
            if kind == "world_writable"
            else 0o755
        )
    with pytest.raises(verifier.PacketIoError):
        verifier._load_packet_bytes(target.name)


def test_packet_fifo_is_rejected_without_blocking(
    isolated_roots: tuple[Path, Path],
) -> None:
    _migrations, packets = isolated_roots
    fifo = packets / "packet.json"
    os.mkfifo(fifo)
    with pytest.raises(verifier.PacketIoError):
        verifier._load_packet_bytes(fifo.name)


def test_group_writable_roots_are_rejected(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    migrations, packets = isolated_roots
    packets.chmod(0o775)
    with pytest.raises(verifier.PacketIoError):
        verifier._load_packet_bytes("packet.json")
    packets.chmod(0o755)
    migrations.chmod(0o775)
    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog()


def test_packet_toctou_is_detected(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _migrations, packets = isolated_roots
    packet_path = packets / "packet.json"
    packet_path.write_text("{}", encoding="utf-8")
    packet_path.chmod(0o644)
    real_read = verifier._read_fd_bytes

    def changing_read(descriptor: int, expected_size: int, maximum_size: int) -> bytes:
        content = real_read(descriptor, expected_size, maximum_size)
        packet_path.write_text('{"changed":true}', encoding="utf-8")
        packet_path.chmod(0o644)
        return content

    monkeypatch.setattr(verifier, "_read_fd_bytes", changing_read)
    with pytest.raises(verifier.PacketIoError):
        verifier._load_packet_bytes(packet_path.name)


def test_catalog_root_symlink_and_file_hardlink_are_rejected(
    isolated_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    migrations, _packets = isolated_roots
    symlink_root = tmp_path / "linked-migrations"
    symlink_root.symlink_to(migrations, target_is_directory=True)
    monkeypatch.setattr(verifier, "MIGRATIONS_DIR", symlink_root)
    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog()

    monkeypatch.setattr(verifier, "MIGRATIONS_DIR", migrations)
    os.link(migrations / "0001_first.sql", migrations / "0003_link.sql")
    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog()


@pytest.mark.parametrize("target", ["script", "catalog", "packet"])
def test_symlink_in_any_trusted_path_ancestor_is_rejected(
    isolated_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target: str,
) -> None:
    _migrations, _packets = isolated_roots
    real_root = tmp_path / "real-root"
    real_root.mkdir(mode=0o755)
    real_root.chmod(0o755)
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(real_root, target_is_directory=True)

    if target == "script":
        scripts = real_root / "backend" / "scripts"
        scripts.mkdir(parents=True, mode=0o755)
        (real_root / "backend").chmod(0o755)
        scripts.chmod(0o755)
        script = scripts / "verifier.py"
        script.write_bytes(SCRIPT_PATH.read_bytes())
        script.chmod(0o644)
        monkeypatch.setattr(
            verifier, "SCRIPT_PATH", linked_root / "backend" / "scripts" / "verifier.py"
        )
        with pytest.raises(verifier.PacketIoError):
            verifier._validate_runtime_layout()
    elif target == "catalog":
        migrations = real_root / "backend" / "migrations"
        migrations.mkdir(parents=True, mode=0o755)
        (real_root / "backend").chmod(0o755)
        migrations.chmod(0o755)
        migration = migrations / "0001.sql"
        migration.write_bytes(b"select 1;\n")
        migration.chmod(0o644)
        monkeypatch.setattr(
            verifier, "MIGRATIONS_DIR", linked_root / "backend" / "migrations"
        )
        with pytest.raises(verifier.CatalogDriftError):
            verifier._scan_catalog()
    else:
        migrations_governance = real_root / "docs" / "governance" / "migrations"
        packets = migrations_governance / "packets"
        packets.mkdir(parents=True, mode=0o755)
        for directory in (
            real_root / "docs",
            real_root / "docs" / "governance",
            migrations_governance,
            packets,
        ):
            directory.chmod(0o755)
        packet = packets / "packet.json"
        packet.write_bytes(b"{}")
        packet.chmod(0o644)
        monkeypatch.setattr(
            verifier,
            "PACKETS_DIR",
            linked_root / "docs" / "governance" / "migrations" / "packets",
        )
        with pytest.raises(verifier.PacketIoError):
            verifier._load_packet_bytes("packet.json")


def test_group_writable_trusted_ancestor_is_rejected(
    isolated_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _migrations, _packets = isolated_roots
    unsafe = tmp_path / "unsafe"
    migrations = unsafe / "migrations"
    unsafe.mkdir(mode=0o755)
    migrations.mkdir(mode=0o755)
    unsafe.chmod(0o775)
    migrations.chmod(0o755)
    migration = migrations / "0001.sql"
    migration.write_bytes(b"select 1;\n")
    migration.chmod(0o644)
    monkeypatch.setattr(verifier, "MIGRATIONS_DIR", migrations)
    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog()

@pytest.mark.parametrize("field", ["name", "sha256", "size_bytes", "position"])
def test_catalog_packet_drift_is_blocked(
    isolated_roots: tuple[Path, Path],
    field: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    entry = packet["catalog"]["entries"][0]
    if field == "name":
        entry[field] = "0000_unknown.sql"
    elif field == "sha256":
        entry[field] = SHA_A
    elif field == "size_bytes":
        entry[field] += 1
    else:
        entry[field] = 1
    _refresh_catalog_digest(packet)
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result in {verifier.SchemaError.exit_code, verifier.CatalogDriftError.exit_code}


def test_catalog_change_after_packet_is_catalog_drift(
    isolated_roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    migrations, packets = isolated_roots
    packet = _complete_packet()
    (migrations / "0002_second.sql").write_bytes(b"changed\n")
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.CatalogDriftError.exit_code


def test_catalog_total_size_limit_is_enforced(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _migrations, _packets = isolated_roots
    monkeypatch.setattr(verifier, "MAX_CATALOG_BYTES", 19)
    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog()


def test_catalog_file_mutation_after_read_is_detected(
    isolated_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    migrations, _packets = isolated_roots
    real_read = verifier._read_regular_at
    changed = False

    def mutate_after_read(
        directory_fd: int,
        basename: str,
        *,
        maximum_size: int,
        error_type: type[verifier.VerificationError],
    ) -> tuple[bytes, verifier.FileSnapshot]:
        nonlocal changed
        result = real_read(
            directory_fd,
            basename,
            maximum_size=maximum_size,
            error_type=error_type,
        )
        if basename == "0001_first.sql" and not changed:
            changed = True
            migration = migrations / basename
            migration.write_bytes(b"select 9;\n")
            migration.chmod(0o644)
        return result

    monkeypatch.setattr(verifier, "_read_regular_at", mutate_after_read)
    with pytest.raises(verifier.CatalogDriftError):
        verifier._scan_catalog()


def test_package_id_is_lowercase_and_bound_to_basename(
    isolated_roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    _write_packet(packets, packet, "different.json")
    result = verifier.main(["verifier", "--packet", "different.json"])
    assert result == verifier.SchemaError.exit_code
    captured = capsys.readouterr()
    assert verifier.OPERATIONAL_BLOCK in (captured.out + captured.err)

    packet["package_id"] = "Packet"
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.SchemaError.exit_code


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("not_captured", verifier.InventoryBlockedError.exit_code),
        ("wrong_target", verifier.SchemaError.exit_code),
        ("missing_authorization", verifier.SchemaError.exit_code),
        ("rows_digest", verifier.SchemaError.exit_code),
        ("native_empty", verifier.InventoryBlockedError.exit_code),
    ],
)
def test_inventory_fail_closed_states(
    isolated_roots: tuple[Path, Path],
    mutation: str,
    expected: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    native = packet["inventories"]["native_ledger"]
    if mutation == "not_captured":
        native.update(
            capture_state="NOT_CAPTURED",
            target_binding_sha256=None,
            captured_at_utc=None,
            authorization_record_sha256=None,
            capture_record_sha256=None,
            snapshot_record_sha256=None,
            completeness_attested=False,
            rows=[],
            rows_digest_sha256=None,
        )
    elif mutation == "wrong_target":
        native["target_binding_sha256"] = SHA_E
    elif mutation == "missing_authorization":
        native["authorization_record_sha256"] = None
    elif mutation == "rows_digest":
        native["rows_digest_sha256"] = SHA_E
    else:
        native["rows"] = []
        _refresh_inventory_digest(packet, "native_ledger")
        packet["reconciliation"]["catalog_entries"][0]["native_row_positions"] = []
        packet["reconciliation"]["native_rows"] = []
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == expected


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("public_unknown", verifier.LedgerDivergenceError.exit_code),
        ("public_not_prefix", verifier.LedgerDivergenceError.exit_code),
        ("unresolved_catalog", verifier.HumanEvidenceBlockedError.exit_code),
        ("missing_evidence", verifier.SchemaError.exit_code),
        ("native_unresolved", verifier.HumanEvidenceBlockedError.exit_code),
        ("native_edge_mismatch", verifier.LedgerDivergenceError.exit_code),
        ("not_attested", verifier.AttestationBlockedError.exit_code),
        ("attestation_drift", verifier.AttestationBlockedError.exit_code),
    ],
)
def test_human_and_ledger_semantics_fail_closed(
    isolated_roots: tuple[Path, Path],
    mutation: str,
    expected: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    if mutation == "public_unknown":
        packet["inventories"]["public_ledger"]["rows"][0]["name"] = "9999_unknown.sql"
        _refresh_inventory_digest(packet, "public_ledger")
    elif mutation == "public_not_prefix":
        packet["inventories"]["public_ledger"]["rows"][0]["name"] = (
            packet["catalog"]["entries"][1]["name"]
        )
        _refresh_inventory_digest(packet, "public_ledger")
    elif mutation == "unresolved_catalog":
        packet["reconciliation"]["catalog_entries"][0].update(
            human_determination="UNRESOLVED",
            basis_record_sha256=[],
            evidence_record_sha256=None,
            decision_record_sha256=None,
        )
    elif mutation == "missing_evidence":
        packet["reconciliation"]["catalog_entries"][0]["evidence_record_sha256"] = None
    elif mutation == "native_unresolved":
        packet["reconciliation"]["native_rows"][0].update(
            disposition="UNRESOLVED",
            catalog_names=[],
            basis_record_sha256=[],
            evidence_record_sha256=None,
            decision_record_sha256=None,
        )
    elif mutation == "native_edge_mismatch":
        packet["reconciliation"]["native_rows"][0]["catalog_names"] = [
            packet["catalog"]["entries"][1]["name"]
        ]
    elif mutation == "not_attested":
        packet["attestation"] = {
            "state": "NOT_ATTESTED",
            "inventory_attestation_record_sha256": None,
            "migration_owner_decision_record_sha256": None,
            "independent_review_record_sha256": None,
            "attested_at_utc": None,
            "payload_sha256": None,
        }
    elif mutation == "attestation_drift":
        packet["attestation"]["payload_sha256"] = SHA_E
    if mutation != "attestation_drift" and mutation != "not_attested":
        _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == expected


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("one_basis", verifier.HumanEvidenceBlockedError.exit_code),
        ("capture_only", verifier.HumanEvidenceBlockedError.exit_code),
        ("decision_in_basis", verifier.HumanEvidenceBlockedError.exit_code),
        ("duplicate_basis", verifier.SchemaError.exit_code),
        ("duplicate_attestation", verifier.SchemaError.exit_code),
    ],
)
def test_independent_human_records_are_mandatory(
    isolated_roots: tuple[Path, Path],
    mutation: str,
    expected: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    decision = packet["reconciliation"]["catalog_entries"][0]
    if mutation == "one_basis":
        decision["basis_record_sha256"] = [SHA_A]
    elif mutation == "capture_only":
        decision["basis_record_sha256"] = [SHA_B, SHA_C]
    elif mutation == "decision_in_basis":
        decision["basis_record_sha256"] = [SHA_J, SHA_B, SHA_C, SHA_D]
    elif mutation == "duplicate_basis":
        decision["basis_record_sha256"] = [SHA_A, SHA_A]
    else:
        packet["attestation"]["independent_review_record_sha256"] = packet[
            "attestation"
        ]["migration_owner_decision_record_sha256"]
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == expected


@pytest.mark.parametrize(
    "collision",
    ["authorization", "capture", "snapshot", "decision", "attestation"],
)
def test_typed_decision_evidence_cannot_reuse_global_records(
    isolated_roots: tuple[Path, Path],
    collision: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    decision = packet["reconciliation"]["catalog_entries"][0]
    evidence = {
        "authorization": SHA_A,
        "capture": SHA_B,
        "snapshot": SHA_I,
        "decision": SHA_D,
        "attestation": SHA_F,
    }[collision]
    decision["evidence_record_sha256"] = evidence
    decision["basis_record_sha256"] = sorted({SHA_B, SHA_C, evidence})
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.HumanEvidenceBlockedError.exit_code


@pytest.mark.parametrize(
    "collision",
    ["authorization", "capture", "snapshot", "attestation"],
)
def test_decision_records_cannot_reuse_any_global_provenance_role(
    isolated_roots: tuple[Path, Path],
    collision: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    packet["reconciliation"]["catalog_entries"][0]["decision_record_sha256"] = {
        "authorization": SHA_A,
        "capture": SHA_B,
        "snapshot": SHA_I,
        "attestation": SHA_F,
    }[collision]
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.HumanEvidenceBlockedError.exit_code


@pytest.mark.parametrize(
    "collision,expected",
    [
        ("capture_authorization", verifier.InventoryBlockedError.exit_code),
        ("snapshot_authorization", verifier.InventoryBlockedError.exit_code),
        ("attestation_authorization", verifier.AttestationBlockedError.exit_code),
        ("attestation_capture", verifier.AttestationBlockedError.exit_code),
        ("attestation_snapshot", verifier.AttestationBlockedError.exit_code),
    ],
)
def test_global_provenance_roles_are_disjoint_except_shared_snapshot(
    isolated_roots: tuple[Path, Path],
    collision: str,
    expected: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    if collision == "capture_authorization":
        packet["inventories"]["native_ledger"]["capture_record_sha256"] = SHA_A
    elif collision == "snapshot_authorization":
        for inventory in packet["inventories"].values():
            inventory["snapshot_record_sha256"] = SHA_A
    elif collision == "attestation_authorization":
        packet["attestation"]["inventory_attestation_record_sha256"] = SHA_A
    elif collision == "attestation_capture":
        packet["attestation"]["inventory_attestation_record_sha256"] = SHA_B
    else:
        packet["attestation"]["inventory_attestation_record_sha256"] = SHA_I
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == expected


@pytest.mark.parametrize(
    "collision", ["duplicate_evidence", "duplicate_decision", "cross_role"]
)
def test_all_decision_and_evidence_records_are_unique_and_cross_disjoint(
    isolated_roots: tuple[Path, Path],
    collision: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    first, second = packet["reconciliation"]["catalog_entries"]
    if collision == "duplicate_evidence":
        second["evidence_record_sha256"] = first["evidence_record_sha256"]
        second["basis_record_sha256"] = list(first["basis_record_sha256"])
    elif collision == "duplicate_decision":
        second["decision_record_sha256"] = first["decision_record_sha256"]
    else:
        second["evidence_record_sha256"] = first["decision_record_sha256"]
        second["basis_record_sha256"] = sorted(
            {SHA_B, SHA_C, first["decision_record_sha256"]}
        )
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.HumanEvidenceBlockedError.exit_code


def test_public_absent_cannot_turn_global_authorization_into_applied_evidence(
    isolated_roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    public = packet["inventories"]["public_ledger"]
    public["capture_state"] = "ABSENT_CONFIRMED"
    public["rows"] = []
    _refresh_inventory_digest(packet, "public_ledger")
    for decision in packet["reconciliation"]["catalog_entries"]:
        decision["public_row_position"] = None
    first = packet["reconciliation"]["catalog_entries"][0]
    first["evidence_record_sha256"] = SHA_A
    first["basis_record_sha256"] = [SHA_A, SHA_B, SHA_C]
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.HumanEvidenceBlockedError.exit_code


@pytest.mark.parametrize("decision_position", [0, 1])
def test_applied_and_not_applied_determinations_require_own_positive_evidence(
    isolated_roots: tuple[Path, Path],
    decision_position: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    decision = packet["reconciliation"]["catalog_entries"][decision_position]
    if decision_position == 1:
        decision["human_determination"] = "NOT_APPLIED_CONFIRMED"
    decision["evidence_record_sha256"] = None
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.SchemaError.exit_code


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("capture_time", verifier.InventoryBlockedError.exit_code),
        ("same_capture_record", verifier.InventoryBlockedError.exit_code),
        ("snapshot_mismatch", verifier.InventoryBlockedError.exit_code),
        ("snapshot_equals_capture", verifier.InventoryBlockedError.exit_code),
        ("attestation_before_capture", verifier.AttestationBlockedError.exit_code),
        ("native_many_to_one", verifier.LedgerDivergenceError.exit_code),
    ],
)
def test_snapshot_and_native_correlation_contract(
    isolated_roots: tuple[Path, Path],
    mutation: str,
    expected: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    if mutation == "capture_time":
        packet["inventories"]["native_ledger"]["captured_at_utc"] = (
            "2026-08-28T16:00:01Z"
        )
    elif mutation == "same_capture_record":
        packet["inventories"]["native_ledger"]["capture_record_sha256"] = SHA_B
    elif mutation == "snapshot_mismatch":
        packet["inventories"]["native_ledger"]["snapshot_record_sha256"] = SHA_G
    elif mutation == "snapshot_equals_capture":
        packet["inventories"]["public_ledger"]["snapshot_record_sha256"] = SHA_B
        packet["inventories"]["native_ledger"]["snapshot_record_sha256"] = SHA_B
    elif mutation == "attestation_before_capture":
        packet["attestation"]["attested_at_utc"] = "2026-08-28T15:59:59Z"
    else:
        packet["reconciliation"]["native_rows"][0]["catalog_names"] = [
            entry["name"] for entry in packet["catalog"]["entries"]
        ]
        packet["reconciliation"]["catalog_entries"][1]["native_row_positions"] = [0]
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == expected


def test_public_rows_must_preserve_captured_query_order(
    isolated_roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    catalog = packet["catalog"]["entries"]
    packet["inventories"]["public_ledger"]["rows"] = [
        {"position": 0, "name": catalog[1]["name"]},
        {"position": 1, "name": catalog[0]["name"]},
    ]
    packet["reconciliation"]["catalog_entries"][1]["public_row_position"] = 1
    _refresh_inventory_digest(packet, "public_ledger")
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.LedgerDivergenceError.exit_code


def test_more_than_one_pending_and_gap_are_blocked(
    isolated_roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    first = packet["reconciliation"]["catalog_entries"][0]
    first.update(
        human_determination="NOT_APPLIED_CONFIRMED",
        public_row_position=None,
        native_row_positions=[],
    )
    packet["inventories"]["public_ledger"]["rows"] = []
    _refresh_inventory_digest(packet, "public_ledger")
    packet["reconciliation"]["native_rows"][0].update(
        disposition="NON_CATALOG_HISTORY_CONFIRMED", catalog_names=[]
    )
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.LedgerDivergenceError.exit_code

    packet = _complete_packet()
    for entry in packet["reconciliation"]["catalog_entries"]:
        entry.update(
            human_determination="NOT_APPLIED_CONFIRMED",
            public_row_position=None,
            native_row_positions=[],
        )
    packet["inventories"]["public_ledger"]["rows"] = []
    _refresh_inventory_digest(packet, "public_ledger")
    packet["reconciliation"]["native_rows"][0].update(
        disposition="NON_CATALOG_HISTORY_CONFIRMED", catalog_names=[]
    )
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.LedgerDivergenceError.exit_code


def test_native_version_must_be_a_valid_utc_timestamp(
    isolated_roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    packet["inventories"]["native_ledger"]["rows"][0]["version"] = "20260230000000"
    _refresh_inventory_digest(packet, "native_ledger")
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.SchemaError.exit_code


@pytest.mark.parametrize(
    "name",
    [
        "joao_private",
        "native.name",
        "operator@example",
        "127.0.0.1",
        "free text",
        "MixedCase",
    ],
)
def test_native_name_must_always_be_null(
    isolated_roots: tuple[Path, Path],
    name: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _migrations, packets = isolated_roots
    packet = _complete_packet()
    packet["inventories"]["native_ledger"]["rows"][0]["name"] = name
    _refresh_inventory_digest(packet, "native_ledger")
    _refresh_attestation(packet)
    result, output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.SchemaError.exit_code
    assert name not in output


def test_query_contracts_fix_isolation_projection_and_order(
    isolated_roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert "ISOLATION=REPEATABLE_READ_READ_ONLY" in verifier.PUBLIC_QUERY_CONTRACT
    assert "ORDER=applied_at_ASC,name_ASC" in verifier.PUBLIC_QUERY_CONTRACT
    assert "PROJECTION=position,name" in verifier.PUBLIC_QUERY_CONTRACT
    assert "ISOLATION=REPEATABLE_READ_READ_ONLY" in verifier.NATIVE_QUERY_CONTRACT
    assert "ORDER=version_ASC" in verifier.NATIVE_QUERY_CONTRACT
    assert verifier.NATIVE_QUERY_CONTRACT.endswith(
        "PROJECTION=position,version,name_NULL_REDACTED"
    )

    _migrations, packets = isolated_roots
    packet = _complete_packet()
    packet["inventories"]["public_ledger"]["query_contract"] = (
        "PUBLIC_LEDGER_V1|ISOLATION=READ_COMMITTED|ORDER=name_ASC"
    )
    _refresh_inventory_digest(packet, "public_ledger")
    _refresh_attestation(packet)
    result, _output = _main_for_packet(packets, packet, capsys)
    assert result == verifier.SchemaError.exit_code


def test_verifier_source_has_no_effectful_dependencies_or_write_flags() -> None:
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
    assert "capture_migration_history_evidence" not in source
    assert not attributes.intersection(
        {
            "environ",
            "getenv",
            "putenv",
            "unsetenv",
            "write",
            "write_text",
            "write_bytes",
            "unlink",
            "remove",
            "rename",
            "replace",
        }
    )
    assert not any(
        forbidden in source
        for forbidden in (
            "O_WRONLY",
            "O_RDWR",
            "O_CREAT",
            "O_TRUNC",
            "O_APPEND",
        )
    )


def test_runtime_audit_hook_observes_no_network_subprocess_or_write_event() -> None:
    harness = f"""
import os
import runpy
import sys

WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

def audit(event, args):
    if event.startswith(("socket.", "subprocess.")) or event in {{"os.system", "os.posix_spawn"}}:
        raise RuntimeError("forbidden external effect")
    if event == "open":
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        if isinstance(mode, str) and any(marker in mode for marker in "wax+"):
            raise RuntimeError("forbidden write")
        if isinstance(flags, int) and flags & WRITE_FLAGS:
            raise RuntimeError("forbidden write")

sys.addaudithook(audit)
sys.argv = [
    {str(SCRIPT_PATH)!r},
    "--packet",
    "migration-history-reconciliation-template-v1.json",
]
try:
    runpy.run_path({str(SCRIPT_PATH)!r}, run_name="__main__")
except SystemExit as exc:
    raise SystemExit(0 if exc.code == 8 else 91)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", harness],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert verifier.OPERATIONAL_BLOCK in result.stdout + result.stderr


def test_schema_is_closed_and_encodes_blocking_literals() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    safety = schema["$defs"]["safetyContract"]["properties"]
    assert safety["offline_only"]["const"] is True
    for key in set(verifier.SAFETY_CONTRACT) - {"offline_only"}:
        assert safety[key]["const"] == "BLOCKED"
    assert (
        schema["$defs"]["catalogEntry"]["properties"]["size_bytes"]["maximum"]
        == verifier.MAX_MIGRATION_BYTES
    )

    captured_unreviewed_rule = next(
        rule
        for rule in schema["allOf"]
        if rule["if"]["properties"]["artifact_state"].get("const")
        == "EVIDENCE_CAPTURED_UNREVIEWED"
    )
    captured_subject = captured_unreviewed_rule["then"]["properties"]["subject"][
        "properties"
    ]
    assert captured_subject["environment"]["enum"] == ["DEV", "PROD"]
    assert captured_subject["target_binding_sha256"] == {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$",
    }
    assert captured_subject["repository_sha"] == {
        "const": verifier.EXPECTED_CAPTURE_REPOSITORY_SHA
    }
    captured_properties = captured_unreviewed_rule["then"]["properties"]
    for inventory_name in ("public_ledger", "native_ledger"):
        assert captured_properties["inventories"]["properties"][inventory_name][
            "properties"
        ]["capture_state"]["enum"] == ["ABSENT_CONFIRMED", "PRESENT_COMPLETE"]
    assert captured_properties["reconciliation"]["properties"] == {
        "state": {"const": "NOT_REVIEWED"},
        "catalog_entries": {"maxItems": 0},
        "native_rows": {"maxItems": 0},
    }
    captured_attestation = captured_properties["attestation"]["properties"]
    assert captured_attestation["state"] == {"const": "NOT_ATTESTED"}
    for key in verifier.ATTESTATION_KEYS - {"state"}:
        assert captured_attestation[key] == {"type": "null"}
    environment_package_rules = {
        rule["if"]["properties"]["subject"]["properties"]["environment"][
            "const"
        ]: rule["then"]["properties"]["package_id"]["const"]
        for rule in schema["allOf"]
        if "subject" in rule["if"].get("properties", {})
        and "package_id" in rule["then"].get("properties", {})
    }
    assert environment_package_rules == verifier.UNREVIEWED_PACKAGE_IDS

    def assert_closed_objects(value: Any) -> None:
        if type(value) is dict:
            if value.get("type") == "object":
                assert value.get("additionalProperties") is False
            for nested in value.values():
                assert_closed_objects(nested)
        elif type(value) is list:
            for nested in value:
                assert_closed_objects(nested)

    assert_closed_objects(schema)


def test_schema_and_runtime_contract_keys_and_limits_are_in_parity() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    definitions = schema["$defs"]
    assert set(schema["required"]) == verifier.TOP_LEVEL_KEYS
    assert set(definitions["publicInventory"]["required"]) == verifier.INVENTORY_KEYS
    assert set(definitions["nativeInventory"]["required"]) == verifier.INVENTORY_KEYS
    assert (
        definitions["publicInventory"]["properties"]["query_contract"]["const"]
        == verifier.PUBLIC_QUERY_CONTRACT
    )
    assert (
        definitions["nativeInventory"]["properties"]["query_contract"]["const"]
        == verifier.NATIVE_QUERY_CONTRACT
    )
    assert definitions["nativeRow"]["properties"]["name"] == {"const": None}
    assert (
        definitions["catalogEntry"]["properties"]["size_bytes"]["maximum"]
        == verifier.MAX_MIGRATION_BYTES
    )
    assert set(definitions["catalogDecision"]["required"]) == (
        verifier.CATALOG_DECISION_KEYS
    )
    assert set(definitions["nativeDecision"]["required"]) == (
        verifier.NATIVE_DECISION_KEYS
    )
    assert "snapshot_record_sha256" in verifier.INVENTORY_KEYS
    assert "evidence_record_sha256" in verifier.CATALOG_DECISION_KEYS
    assert "evidence_record_sha256" in verifier.NATIVE_DECISION_KEYS


def test_template_contains_no_environment_or_personal_pseudonyms() -> None:
    raw = TEMPLATE_PATH.read_text(encoding="utf-8")
    lowered = raw.lower()
    assert "operator_identity" not in lowered
    assert "reviewer_identity" not in lowered
    assert "@" not in raw
    assert "postgresql://" not in lowered
    assert "project_ref" not in lowered
    assert json.loads(raw)["safety_contract"] == verifier.SAFETY_CONTRACT
