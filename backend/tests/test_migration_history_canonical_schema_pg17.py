from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts import derive_migration_history_canonical_schema as derivation


def test_main_interface_derives_full_catalog_on_dedicated_postgresql_17(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if not os.environ.get(derivation.DATABASE_URL_ENV):
        pytest.skip("dedicated disposable PostgreSQL 17 URL is not configured")
    configured_output = os.environ.get(
        "CANONICAL_SCHEMA_DERIVATION_TEST_OUTPUT_DIR"
    )
    output = Path(configured_output) if configured_output else tmp_path / "artifact"
    if not output.exists():
        output.mkdir(mode=0o700)
    output.chmod(0o700)

    assert derivation.main(
        [
            "--confirmation",
            derivation.CONFIRMATION,
            "--output-dir",
            str(output),
        ]
    ) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        derivation.OPERATIONAL_BLOCK,
        "ENVIRONMENT_ATTESTATION_COMPLETE=false",
        derivation.SUCCESS,
    ]
    assert captured.err == ""

    target = output / derivation.OUTPUT_BASENAME
    artifact = json.loads(target.read_text(encoding="utf-8"))

    assert artifact["replay"]["complete"] is True
    assert artifact["replay"]["migration_count"] == 75
    assert artifact["replay"]["public_ledger_absent"] is True
    assert artifact["replay"]["native_ledger_absent"] is True
    assert artifact["operational_authorization"] is False
    assert artifact["environment_attestation_complete"] is False
    assert len(artifact["domains"]) == 15
