"""Focused guards for the intentionally unavailable E4a write boundary."""

from __future__ import annotations

import ast
import importlib.util
import uuid
from pathlib import Path

import pytest

import app.domain.consent_ledger_receipt as e4_domain
from app.domain.consent_ledger_receipt import (
    ConsentLedgerReceiptAction,
    ConsentLedgerReceiptOperation,
    TenantScopedConsentLedgerReceiptIdempotencyKey,
)
from app.services.consent_ledger_receipt import (
    ConsentLedgerReceiptCoordinator,
    ConsentLedgerReceiptCoordinatorError,
    ConsentLedgerReceiptCoordinatorErrorCode,
)


TENANT = uuid.UUID("10000000-0000-4000-8000-000000000001")
OPERATION = uuid.UUID("20000000-0000-4000-8000-000000000003")
_E4A_COORDINATOR_MODULE = "app.services.consent_ledger_receipt"
_SERVICES_MODULE = "app.services"
_APP_MODULE = "app"


def _operation(
    action: ConsentLedgerReceiptAction = ConsentLedgerReceiptAction.REFUSE_INITIAL,
) -> ConsentLedgerReceiptOperation:
    return ConsentLedgerReceiptOperation(
        operation_id=OPERATION,
        idempotency_key=TenantScopedConsentLedgerReceiptIdempotencyKey.from_persisted(
            igreja_id=TENANT,
            value="e4.consent.receipt.20260909",
        ),
        action=action,
    )


def _assert_unavailable(
    error: pytest.ExceptionInfo[ConsentLedgerReceiptCoordinatorError],
) -> None:
    assert error.value.code is (
        ConsentLedgerReceiptCoordinatorErrorCode.AUTHORITY_ADAPTER_UNAVAILABLE
    )


def test_every_known_action_is_denied_without_a_reviewed_authority_adapter() -> None:
    coordinator = ConsentLedgerReceiptCoordinator()

    for action in ConsentLedgerReceiptAction:
        with pytest.raises(ConsentLedgerReceiptCoordinatorError) as error:
            coordinator.stage_write(_operation(action))
        _assert_unavailable(error)


def test_invalid_operation_is_not_coerced_into_a_write_request() -> None:
    with pytest.raises(ConsentLedgerReceiptCoordinatorError) as error:
        ConsentLedgerReceiptCoordinator().stage_write(object())

    assert error.value.code is ConsentLedgerReceiptCoordinatorErrorCode.INVALID_OPERATION


def test_forged_duck_typed_source_cannot_be_injected() -> None:
    class ForgedSource:
        def resolve(self) -> object:
            return object()

    with pytest.raises(TypeError):
        ConsentLedgerReceiptCoordinator(authority_source=ForgedSource())  # type: ignore[call-arg]


def test_forged_authority_cannot_be_supplied_to_the_write_boundary() -> None:
    with pytest.raises(TypeError):
        ConsentLedgerReceiptCoordinator().stage_write(
            _operation(),
            object(),  # type: ignore[call-arg]
        )


def test_e4a_exposes_no_reconciliation_association_or_lock_contract() -> None:
    coordinator = ConsentLedgerReceiptCoordinator()

    assert not hasattr(coordinator, "reconcile")
    assert not hasattr(coordinator, "declared_lock_order")
    assert not hasattr(e4_domain, "ConsentLedgerReceiptAssociation")
    assert not hasattr(e4_domain, "ConsentLedgerReceiptReconciliationResult")
    assert not hasattr(e4_domain, "CONSENT_LEDGER_RECEIPT_LOCK_ORDER")


def test_e4a_has_no_runtime_database_or_authority_factory_dependency() -> None:
    root = Path(__file__).resolve().parents[2]
    paths = (
        root / "backend/app/domain/consent_ledger_receipt.py",
        root / "backend/app/services/consent_ledger_receipt.py",
    )
    imported: list[str] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "AuthoritySource" not in source
        assert "ServerOwned" not in source
        assert "hmac" not in source
        assert "secrets" not in source
        assert "Protocol" not in source
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
    forbidden = ("agent", "runtime", "sqlalchemy", "app.db", "app.models")
    assert not any(
        forbidden_name in module
        for module in imported
        for forbidden_name in forbidden
    )


def _module_context(application: Path, path: Path) -> tuple[str, str]:
    relative = path.relative_to(application).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
        module = ".".join((_APP_MODULE, *parts))
        return module, module
    module = ".".join((_APP_MODULE, *parts))
    return module, module.rpartition(".")[0]


def _resolve_import_from(
    node: ast.ImportFrom,
    *,
    current_package: str,
) -> str | None:
    if node.level == 0:
        return node.module
    relative_name = "." * node.level + (node.module or "")
    try:
        return importlib.util.resolve_name(relative_name, current_package)
    except (ImportError, ValueError):
        return None


def _module_bindings(
    tree: ast.AST,
    *,
    current_package: str,
) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for entry in node.names:
                local_name = entry.asname or entry.name.partition(".")[0]
                bindings[local_name] = (
                    entry.name if entry.asname else entry.name.partition(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_import_from(node, current_package=current_package)
            if base is None:
                continue
            for entry in node.names:
                if entry.name == "*":
                    continue
                bindings[entry.asname or entry.name] = f"{base}.{entry.name}"
    return bindings


def _resolved_expression_name(
    node: ast.expr,
    bindings: dict[str, str],
) -> str | None:
    if isinstance(node, ast.Name):
        return bindings.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _resolved_expression_name(node.value, bindings)
        return None if base is None else f"{base}.{node.attr}"
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
    ):
        base = _resolved_expression_name(node.args[0], bindings)
        attribute = _static_string(node.args[1])
        return None if base is None or attribute is None else f"{base}.{attribute}"
    if isinstance(node, ast.Subscript):
        base = _resolved_expression_name(node.value, bindings)
        attribute = _static_string(node.slice)
        if base is None or attribute is None:
            return None
        if base.endswith(".__dict__"):
            base = base[: -len(".__dict__")]
        return f"{base}.{attribute}"
    return None


def _static_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and type(node.value) is str:
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left)
        right = _static_string(node.right)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        values: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and type(value.value) is str:
                values.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                resolved = _static_string(value.value)
                if resolved is None or value.format_spec is not None:
                    return None
                values.append(resolved)
            else:
                return None
        return "".join(values)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and isinstance(node.func.value, ast.Constant)
        and type(node.func.value.value) is str
        and len(node.args) == 1
        and isinstance(node.args[0], (ast.List, ast.Tuple))
    ):
        parts = [_static_string(value) for value in node.args[0].elts]
        if any(part is None for part in parts):
            return None
        return node.func.value.value.join(part for part in parts if part is not None)
    return None


def _dynamic_import_references_coordinator(
    node: ast.Call,
    *,
    bindings: dict[str, str],
    current_package: str,
) -> bool:
    function_name = _resolved_expression_name(node.func, bindings)
    is_builtin_import = function_name == "__import__"
    is_importlib_loader = function_name in {
        "importlib.import_module",
        "importlib.reload",
        "importlib.util.find_spec",
        "importlib.util.module_from_spec",
    }
    if not is_builtin_import and not is_importlib_loader:
        return False
    if not node.args:
        return True
    module_name = _static_string(node.args[0])
    if module_name is None:
        return True
    if module_name.startswith("."):
        package = current_package
        for keyword in node.keywords:
            if keyword.arg == "package":
                package = _static_string(keyword.value) or ""
                break
        try:
            module_name = importlib.util.resolve_name(module_name, package)
        except (ImportError, ValueError):
            return True
    if is_builtin_import and (
        module_name == "importlib" or module_name.startswith("importlib.")
    ):
        return True
    return module_name in {
        _E4A_COORDINATOR_MODULE,
        _SERVICES_MODULE,
        _APP_MODULE,
    } or module_name.startswith(f"{_E4A_COORDINATOR_MODULE}.")


def _tree_references_e4a_coordinator(
    tree: ast.AST,
    *,
    current_package: str,
) -> bool:
    bindings = _module_bindings(tree, current_package=current_package)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                entry.name == _E4A_COORDINATOR_MODULE
                for entry in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_import_from(node, current_package=current_package)
            if base == _E4A_COORDINATOR_MODULE:
                return True
            if base == _SERVICES_MODULE and any(
                entry.name in {"consent_ledger_receipt", "*"}
                for entry in node.names
            ):
                return True
        elif isinstance(node, ast.Attribute):
            resolved = _resolved_expression_name(node, bindings)
            if resolved == _E4A_COORDINATOR_MODULE or (
                resolved is not None
                and resolved.startswith(f"{_E4A_COORDINATOR_MODULE}.")
            ):
                return True
        elif isinstance(node, ast.Call) and _dynamic_import_references_coordinator(
            node,
            bindings=bindings,
            current_package=current_package,
        ):
            return True
    return False


def test_e4a_coordinator_has_no_application_caller() -> None:
    application = Path(__file__).resolve().parents[2] / "backend/app"
    coordinator_path = application / "services/consent_ledger_receipt.py"
    for path in application.rglob("*.py"):
        if path == coordinator_path:
            continue
        _module, package = _module_context(application, path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not _tree_references_e4a_coordinator(
            tree,
            current_package=package,
        ), "E4a não pode ganhar caller público ou interno"

    rejected_imports = (
        ("from . import consent_ledger_receipt", "app.services"),
        ("from ..services import consent_ledger_receipt", "app.routers"),
        ("from app.services import consent_ledger_receipt", "app.routers"),
        ("from app.services import *", "app.routers"),
        (
            "import app.services as services\nservices.consent_ledger_receipt",
            "app.routers",
        ),
        (
            "from app import services\nservices.consent_ledger_receipt",
            "app.routers",
        ),
        (
            "import app.services\napp.services.consent_ledger_receipt",
            "app.routers",
        ),
        (
            "import importlib\n"
            "importlib.import_module('app.services.' + 'consent_ledger_receipt')",
            "app.routers",
        ),
        (
            "from importlib import import_module as load\n"
            "load(f\"app.services.{'consent_ledger_receipt'}\")",
            "app.routers",
        ),
        (
            "import importlib\n"
            "module_name = 'app.services.consent_ledger_receipt'\n"
            "importlib.import_module(module_name)",
            "app.routers",
        ),
        (
            "import importlib\n"
            "importlib.import_module('.consent_ledger_receipt', "
            "package='app.services')",
            "app.routers",
        ),
        (
            "import importlib\n"
            "getattr(importlib, 'import_module')("
            "'app.services.consent_ledger_receipt')",
            "app.routers",
        ),
        (
            "import importlib\n"
            "importlib.__dict__['import_module']("
            "'app.services.consent_ledger_receipt')",
            "app.routers",
        ),
        (
            "loader = __import__('importlib')\n"
            "loader.import_module('app.services.consent_ledger_receipt')",
            "app.routers",
        ),
        ("__import__('app.services.consent_ledger_receipt')", "app.routers"),
    )
    for source, package in rejected_imports:
        assert _tree_references_e4a_coordinator(
            ast.parse(source),
            current_package=package,
        ), source
