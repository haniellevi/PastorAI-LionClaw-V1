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


def load_consumer_module():
    spec = importlib.util.spec_from_file_location("e4b_projection_consumer_under_test", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("projection consumer module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


if __name__ == "__main__":
    unittest.main()
