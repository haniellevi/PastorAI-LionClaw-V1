"""Contrato offline para a cobertura completa da suite PostgreSQL/RLS no CI."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import conftest as suite_conftest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "rls-integration.yml"
PYTEST_INI = REPOSITORY_ROOT / "backend" / "pytest.ini"


def _marker_step(workflow: str) -> str:
    return workflow.split(
        "- name: Rodar toda a suite marcada rls_integration",
        maxsplit=1,
    )[1].split(
        "- name: Verificar execucao integral da suite RLS",
        maxsplit=1,
    )[0]


def test_workflow_coleta_todo_backend_por_marker_sem_allowlist_manual() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker_step = _marker_step(workflow)

    assert "--strict-markers" in marker_step
    assert "-m rls_integration" in marker_step
    assert "--junitxml=rls-results.xml" in marker_step
    assert "\n            tests\n" in marker_step
    assert "tests/test_" not in marker_step


def test_workflow_falha_com_skip_parcial_ou_zero_testes() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "if total == 0:" in workflow
    assert "if executed == 0:" in workflow
    assert "if skipped != 0:" in workflow
    assert "if failed != 0 or errors != 0:" in workflow


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
