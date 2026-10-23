"""Checks that application services do not depend on HTTP routers."""

import ast
from pathlib import Path


def _is_router_module(module: str | None) -> bool:
    return module == "app.routers" or bool(module and module.startswith("app.routers."))


def _resolve_import_from(module: str | None, level: int, package: str) -> str | None:
    if level == 0:
        return module

    package_parts = package.split(".")
    if level > len(package_parts):
        return None

    resolved_parts = package_parts[: len(package_parts) - level + 1]
    if module:
        resolved_parts.extend(module.split("."))
    return ".".join(resolved_parts)


def _imports_routers(source: str, *, package: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(_is_router_module(alias.name) for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            imported_module = _resolve_import_from(node.module, node.level, package)
            if _is_router_module(imported_module):
                return True

            if any(
                _is_router_module(
                    f"{imported_module}.{alias.name}" if imported_module else alias.name
                )
                for alias in node.names
            ):
                return True
    return False


def test_detector_catches_absolute_router_imports() -> None:
    assert _imports_routers(
        "from app.routers.contacts import list_contacts", package="app.services"
    )
    assert _imports_routers("import app.routers.contacts", package="app.services")


def test_detector_resolves_relative_router_imports_from_package() -> None:
    assert _imports_routers("from ..routers import contacts", package="app.services")
    assert _imports_routers(
        "from ...routers import contacts", package="app.services.contacts"
    )


def test_detector_catches_router_import_aliases() -> None:
    assert _imports_routers(
        "from app import routers as route_layer", package="app.services"
    )
    assert _imports_routers("import app.routers as route_layer", package="app.services")


def test_services_do_not_import_routers() -> None:
    repository = Path(__file__).resolve().parents[2]
    app = repository / "backend" / "app"
    services = repository / "backend" / "app" / "services"
    violations = []

    for source in sorted(services.rglob("*.py")):
        package = ".".join(("app", *source.relative_to(app).parent.parts))
        imports_router = _imports_routers(
            source.read_text(encoding="utf-8"), package=package
        )
        if imports_router:
            violations.append(source.relative_to(repository).as_posix())

    assert not violations, "Services import app.routers:\n" + "\n".join(violations)
