"""Checks that application services do not depend on HTTP routers."""

import ast
from pathlib import Path


def test_services_do_not_import_routers() -> None:
    repository = Path(__file__).resolve().parents[2]
    services = repository / "backend" / "app" / "services"
    violations = []

    for source in sorted(services.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        imports_router = any(
            (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and (node.module == "app.routers" or node.module.startswith("app.routers."))
            )
            or (
                isinstance(node, ast.Import)
                and any(
                    alias.name == "app.routers" or alias.name.startswith("app.routers.")
                    for alias in node.names
                )
            )
            for node in ast.walk(tree)
        )
        if imports_router:
            violations.append(source.relative_to(repository).as_posix())

    assert not violations, "Services import app.routers:\n" + "\n".join(violations)
