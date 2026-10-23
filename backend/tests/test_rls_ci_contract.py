"""Contrato offline para a cobertura completa da suite PostgreSQL/RLS no CI."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ci_test_shards import parse_collection, partition_files, verify_artifacts
from tests import conftest as suite_conftest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PYTEST_INI = REPOSITORY_ROOT / "backend" / "pytest.ini"


def _write_shard_artifacts(
    artifact_directory: Path,
    collected_files: dict[str, int],
    assignments: list[list[str]],
    junit_results: list[dict[str, int]],
) -> None:
    shard_count = len(assignments)
    for shard, assigned_files in enumerate(assignments):
        manifest = {
            "schema_version": 1,
            "shard": shard,
            "shard_count": shard_count,
            "collected_files": collected_files,
            "collected_total": sum(collected_files.values()),
            "assigned_files": assigned_files,
            "assigned_total": sum(collected_files[path] for path in assigned_files),
        }
        (artifact_directory / f"rls-shard-{shard}.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        counts = junit_results[shard]
        (artifact_directory / f"rls-results-{shard}.xml").write_text(
            '<testsuites><testsuite '
            f'tests="{counts["tests"]}" '
            f'skipped="{counts["skipped"]}" '
            f'failures="{counts["failures"]}" '
            f'errors="{counts["errors"]}"/>'
            "</testsuites>",
            encoding="utf-8",
        )


def test_shard_verifier_sums_junit_and_accepts_exact_collection_coverage(
    tmp_path: Path,
) -> None:
    collected_files = parse_collection(
        "tests/test_alpha.py::test_one\n"
        "tests/test_alpha.py::test_two\n"
        "tests/test_beta.py::test_three\n"
        "tests/test_gamma.py::test_four\n"
    )
    assignments = partition_files(collected_files, shard_count=2)
    junit_results = [
        {
            "tests": sum(collected_files[path] for path in assigned_files),
            "skipped": 0,
            "failures": 0,
            "errors": 0,
        }
        for assigned_files in assignments
    ]
    _write_shard_artifacts(tmp_path, collected_files, assignments, junit_results)

    output = io.StringIO()
    assert verify_artifacts(tmp_path, 2, "success", output)
    assert "total=4 skipped=0 executed=4 failed=0 errors=0" in output.getvalue()
    assert "OK: suite rls_integration selecionada executou de fato." in output.getvalue()


def test_shard_verifier_rejects_incomplete_junit_and_duplicate_or_missing_files(
    tmp_path: Path,
) -> None:
    cases = [
        (
            1,
            {"tests": 0, "skipped": 0, "failures": 0, "errors": 0},
            "0 testes",
        ),
        (
            1,
            {"tests": 1, "skipped": 1, "failures": 0, "errors": 0},
            "todos os testes rls_integration selecionados em skip",
        ),
        (
            2,
            {"tests": 2, "skipped": 1, "failures": 0, "errors": 0},
            "houve skip parcial",
        ),
        (
            1,
            {"tests": 1, "skipped": 0, "failures": 1, "errors": 0},
            "registrou falha ou erro",
        ),
        (
            1,
            {"tests": 1, "skipped": 0, "failures": 0, "errors": 1},
            "registrou falha ou erro",
        ),
    ]
    for case_index, (collected_count, junit_counts, expected_message) in enumerate(cases):
        artifact_directory = tmp_path / f"case-{case_index}"
        artifact_directory.mkdir()
        collection = "".join(
            f"tests/test_synthetic.py::test_{index}\n"
            for index in range(collected_count)
        )
        collected_files = parse_collection(collection)
        _write_shard_artifacts(
            artifact_directory,
            collected_files,
            [["tests/test_synthetic.py"]],
            [junit_counts],
        )

        output = io.StringIO()
        assert not verify_artifacts(artifact_directory, 1, "success", output)
        assert expected_message in output.getvalue()

    collected_files = parse_collection(
        "tests/test_alpha.py::test_one\n"
        "tests/test_beta.py::test_two\n"
    )
    complete_assignments = partition_files(collected_files, shard_count=2)
    duplicate_assignments = [complete_assignments[0], complete_assignments[0]]
    artifact_directory = tmp_path / "duplicate-files"
    artifact_directory.mkdir()
    _write_shard_artifacts(
        artifact_directory,
        collected_files,
        duplicate_assignments,
        [
            {"tests": 1, "skipped": 0, "failures": 0, "errors": 0},
            {"tests": 1, "skipped": 0, "failures": 0, "errors": 0},
        ],
    )

    output = io.StringIO()
    assert not verify_artifacts(artifact_directory, 2, "success", output)
    assert "arquivo atribuido aos shards" in output.getvalue()
    assert "arquivos sem shard" in output.getvalue()


def test_pytest_rejeita_marker_desconhecido_globalmente() -> None:
    pytest_ini = PYTEST_INI.read_text(encoding="utf-8")

    assert "strict_markers = true" in pytest_ini
    assert "rls_integration:" in pytest_ini


class _SyntheticItem:
    def __init__(
        self,
        *,
        nodeid: str,
        marked: bool,
        fixturenames: tuple[str, ...],
    ) -> None:
        self.nodeid = nodeid
        self._marked = marked
        self.fixturenames = fixturenames

    def get_closest_marker(self, name: str):
        if name == "rls_integration" and self._marked:
            return object()
        return None


def test_hook_rejeita_fixture_rls_sem_marker() -> None:
    item = _SyntheticItem(
        nodeid="tests/test_synthetic.py::test_without_marker",
        marked=False,
        fixturenames=("fixture_local", "rls_database_url"),
    )

    with pytest.raises(pytest.UsageError, match="usa fixture RLS sem marker"):
        suite_conftest.pytest_collection_modifyitems([item])


def test_hook_rejeita_marker_sem_guard_descartavel() -> None:
    item = _SyntheticItem(
        nodeid="tests/test_synthetic.py::test_without_guard",
        marked=True,
        fixturenames=("fixture_local",),
    )

    with pytest.raises(pytest.UsageError, match="marker rls_integration sem guard"):
        suite_conftest.pytest_collection_modifyitems([item])


def test_hook_aceita_marker_com_fixture_transitiva() -> None:
    item = _SyntheticItem(
        nodeid="tests/test_synthetic.py::test_guarded",
        marked=True,
        # O pytest expande dependencias transitivas em item.fixturenames.
        fixturenames=("fixture_local", "rls_database_url"),
    )

    suite_conftest.pytest_collection_modifyitems([item])


@pytest.mark.parametrize("expression", ["rls_integration", "not rls_integration", "", "catalog_canonical_pg17"])
def test_canonical_routing_preserves_explicit_launcher(expression):
    dedicated = SimpleNamespace(get_closest_marker=lambda name: object() if name == "catalog_canonical_pg17" else None)
    ordinary = SimpleNamespace(get_closest_marker=lambda name: None)
    items = [dedicated, ordinary]
    deselected = []
    config = SimpleNamespace(
        getoption=lambda name: expression,
        hook=SimpleNamespace(pytest_deselected=lambda items: deselected.extend(items)),
    )
    suite_conftest.pytest_route_catalog_canonical(config, items)
    if expression in {"rls_integration", "not rls_integration"}:
        assert items == [ordinary]
        assert deselected == [dedicated]
    else:
        assert items == [dedicated, ordinary]
        assert deselected == []
