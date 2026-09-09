"""Offline contract tests for the public-76/private-1 composition boundary."""

from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


replay = _load(
    REPO_ROOT / "backend/scripts/replay_private_runtime_catalog_pg17.py",
    "public_private_catalog_compatibility_replay_test",
)
receipt = _load(
    REPO_ROOT / "backend/scripts/verify_private_runtime_pg17_receipt.py",
    "public_private_catalog_compatibility_receipt_test",
)


def test_full_public_head_is_authenticated_before_private_prefix_binding() -> None:
    public, _scaffold, private = replay._load_composed_source()
    prefix, append = replay._split_public_catalog(public)

    assert len(public.migrations) == 76
    assert len(prefix) == replay.HISTORICAL_COUNT == 75
    assert len((append,)) == replay.PUBLIC_APPEND_COUNT
    assert append.scope == "TENANT"
    assert public.digest_sha256 != replay.HISTORICAL_DIGEST_SHA256
    assert private.migrations
    assert private.migrations[0].position == 0


def test_prefix_tampering_fails_closed_even_when_current_digest_is_present() -> None:
    public, _scaffold, _private = replay._load_composed_source()
    tampered_prefix = replace(public.migrations[0], sha256="0" * 64)
    forged = replace(
        public,
        migrations=(tampered_prefix, *public.migrations[1:]),
    )
    with pytest.raises(replay.SourceContractError):
        replay._split_public_catalog(forged)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda append: replace(append, scope=None),
        lambda append: replace(append, affected_relations=()),
        lambda append: replace(append, pg17_test_nodeids=()),
        lambda append: replace(append, cross_tenant_test_nodeids=()),
    ],
)
def test_public_append_controls_are_not_bypassed(
    mutator,
) -> None:
    public, _scaffold, _private = replay._load_composed_source()
    prefix = public.migrations[: replay.HISTORICAL_COUNT]
    forged_append = mutator(public.migrations[-1])
    forged = replace(public, migrations=(*prefix, forged_append))
    with pytest.raises(replay.SourceContractError):
        replay._split_public_catalog(forged)


def test_receipt_binds_full_public_state_and_both_composition_orders() -> None:
    common = dict(
        private_migration_count=1,
        private_digest_sha256="a" * 64,
        private_last_basename="20260904_120000_private_runtime_load_turn_context.sql",
        private_last_sha256="b" * 64,
        public_migration_count=76,
        public_digest_sha256="d" * 64,
        public_append_count=1,
        public_append_last_basename="20260909_004005_consent_evidence_store_lab.sql",
        public_append_last_sha256="e" * 64,
        source_git_sha="f" * 40,
    )
    receipts = [
        receipt.expected_receipt_lines(
            **common,
            composition_order=order,
        )
        for order in receipt.COMPOSITION_ORDERS
    ]

    assert len(receipts) == 2
    for lines in receipts:
        assert "PUBLIC_HISTORICAL_MIGRATION_COUNT=75" in lines
        assert "PUBLIC_CATALOG_MIGRATION_COUNT=76" in lines
        assert "PUBLIC_CATALOG_APPEND_COUNT=1" in lines
        assert "COMBINED_CATALOG_MIGRATION_COUNT=77" in lines
        assert "SOURCE_GIT_SHA=" + "f" * 40 in lines
    assert receipts[0] != receipts[1]


def test_receipt_rejects_legacy_75_plus_private_composition() -> None:
    with pytest.raises(receipt.ReceiptVerificationError):
        receipt.expected_receipt_lines(
            private_migration_count=1,
            private_digest_sha256="a" * 64,
            private_last_basename="20260904_120000_private_runtime_load_turn_context.sql",
            private_last_sha256="b" * 64,
            public_migration_count=75,
            public_digest_sha256=receipt.HISTORICAL_DIGEST_SHA256,
            public_append_count=0,
        )


def test_composition_order_is_closed() -> None:
    assert replay.COMPOSITION_ORDERS == (
        replay.COMPOSITION_PUBLIC_APPEND_THEN_PRIVATE,
        replay.COMPOSITION_PRIVATE_THEN_PUBLIC_APPEND,
    )
    with pytest.raises(replay.CliUsageError):
        replay.replay_private_runtime_catalog_pg17(
            connect=lambda *_args, **_kwargs: None,
            composition_order="PUBLIC_ONLY",
            _source_git_sha="f" * 40,
        )
