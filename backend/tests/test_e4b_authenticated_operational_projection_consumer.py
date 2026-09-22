"""Isolated tests proving that the source-only projection cannot run a consumer."""

from __future__ import annotations

from collections.abc import Mapping
import importlib.util
import inspect
from pathlib import Path
import sys
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = BACKEND_ROOT / "scripts" / "e4b_authenticated_operational_projection_consumer.py"
ANCHORS_PATH = BACKEND_ROOT / "scripts" / "e4b_external_trust_anchors.py"
PROJECTION_PATH = BACKEND_ROOT / "scripts" / "e4b_authenticated_operational_projection.py"
ANCHORS_MODULE_NAME = "e4b_external_trust_anchors"
_MODULE_ABSENT = object()
_MODULE_PREDECESSORS: dict[str, object] = {}
_LOADED_MODULES: dict[str, object] = {}


def load_consumer_module():
    return load_module("e4b_projection_consumer_under_test", MODULE_PATH)


def _remember_predecessor(name: str) -> None:
    if name not in _MODULE_PREDECESSORS:
        _MODULE_PREDECESSORS[name] = sys.modules.get(name, _MODULE_ABSENT)


def _restore_predecessor_if_current(name: str, module: object) -> None:
    if sys.modules.get(name) is not module:
        return
    predecessor = _MODULE_PREDECESSORS[name]
    if predecessor is _MODULE_ABSENT:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = predecessor


def _restore_current_if_partial(name: str, module: object, current: object) -> None:
    if sys.modules.get(name) is not module:
        return
    if current is _MODULE_ABSENT:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = current


def load_module(name: str, path: Path):
    _remember_predecessor(name)
    current_module = sys.modules.get(name, _MODULE_ABSENT)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("candidate module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        _restore_current_if_partial(name, module, current_module)
        raise
    _LOADED_MODULES[name] = module
    return module


def load_external_trust_anchors():
    return load_module(ANCHORS_MODULE_NAME, ANCHORS_PATH)


def tearDownModule() -> None:
    for name, module in tuple(_LOADED_MODULES.items()):
        _restore_predecessor_if_current(name, module)
    _LOADED_MODULES.clear()
    _MODULE_PREDECESSORS.clear()


class ExplodingMapping(Mapping[str, object]):
    def __init__(self) -> None:
        self.get_calls = 0

    def __getitem__(self, _key: str) -> object:
        raise KeyError

    def __iter__(self):
        return iter(())

    def __len__(self) -> int:
        return 0

    def get(self, *_args, **_kwargs) -> object:
        self.get_calls += 1
        raise RuntimeError("receipt.get must not be called")


class ExplodingDict(dict[str, object]):
    def __init__(self) -> None:
        super().__init__()
        self.get_calls = 0

    def get(self, *_args, **_kwargs) -> object:
        self.get_calls += 1
        raise RuntimeError("receipt.get must not be called")


class ProjectionConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.consumer = load_consumer_module()

    def test_blocked_receipt_is_rejected_without_callback_surface(self) -> None:
        receipt = {
            "schema": "e4b-operational-projection-blocked-receipt-v1",
            "status": "BLOCKED",
        }
        with self.assertRaises(self.consumer.ProjectionConsumerDisabled):
            self.consumer.reject_projection_receipt(receipt)
        parameters = inspect.signature(self.consumer.reject_projection_receipt).parameters
        self.assertEqual(tuple(parameters), ("receipt",))

    def test_forged_final_receipt_is_also_rejected(self) -> None:
        receipt = {
            "schema": "e4b-operational-projection-final-receipt-v1",
            "status": "FINAL",
            "projection_root": "/forged",
        }
        with self.assertRaises(self.consumer.ProjectionConsumerDisabled):
            self.consumer.reject_projection_receipt(receipt)

    def test_custom_mapping_and_dict_subclass_are_never_inspected(self) -> None:
        for receipt in (ExplodingMapping(), ExplodingDict()):
            with self.subTest(receipt_type=type(receipt).__name__):
                with self.assertRaisesRegex(
                    self.consumer.ProjectionConsumerDisabled,
                    r"^source-only projection consumer is disabled$",
                ):
                    self.consumer.reject_projection_receipt(receipt)
                self.assertEqual(receipt.get_calls, 0)

    def test_module_has_no_operational_executor_import(self) -> None:
        forbidden = {"subprocess", "socket", "pathlib", "requests", "sqlalchemy"}
        self.assertTrue(forbidden.isdisjoint(self.consumer.__dict__))


class ConsumerBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_external_trust_anchors()
        cls.projection = load_module("e4b_authenticated_operational_projection", PROJECTION_PATH)
        cls.consumer = load_module(
            "e4b_authenticated_operational_projection_consumer", MODULE_PATH
        )

    def _final_receipt(self):
        return self.projection.FinalProjectionReceipt(
            schema="e4b-operational-projection-final-receipt-v1",
            status="FINALIZED_SOURCE_ONLY",
            operational_authorization=False,
            commit_sha="a" * 40,
            tree_sha="b" * 40,
            parent_sha="c" * 40,
            base_sha="d" * 40,
            ancestry_digest_sha256="e" * 64,
            patch_receipt_sha256="f" * 64,
            patch_digest_sha256="1" * 64,
            manifest_sha256="2" * 64,
            root_digest_sha256="3" * 64,
            protected_object_commitment_sha256="4" * 64,
            file_count=2,
        )

    def test_exact_final_receipt_is_accepted_without_execution(self) -> None:
        receipt = self._final_receipt()
        self.assertIs(self.consumer.accept_final_projection_receipt(receipt), receipt)
        self.assertFalse(receipt.operational_authorization)

    def test_blocked_historical_and_mapping_receipts_are_rejected_uninspected(self) -> None:
        blocked = {
            "schema": "e4b-operational-projection-blocked-receipt-v1",
            "status": "BLOCKED",
        }
        historical = {
            "schema": "trusted-repository-snapshot-receipt-v1",
            "status": "FINAL",
        }
        explosive = ExplodingMapping()
        for receipt in (blocked, historical, explosive):
            with self.subTest(receipt_type=type(receipt).__name__):
                with self.assertRaisesRegex(
                    self.consumer.ProjectionConsumerDisabled,
                    r"^final typed projection receipt required$",
                ):
                    self.consumer.accept_final_projection_receipt(receipt)
        self.assertEqual(explosive.get_calls, 0)

    def test_legacy_rejector_stays_constant_and_non_inspecting(self) -> None:
        explosive = ExplodingMapping()
        with self.assertRaisesRegex(
            self.consumer.ProjectionConsumerDisabled,
            r"^source-only projection consumer is disabled$",
        ):
            self.consumer.reject_projection_receipt(explosive)
        self.assertEqual(explosive.get_calls, 0)


if __name__ == "__main__":
    unittest.main()
