"""Adversarial offline oracle for the private catalog before/after delta.

These tests deliberately exercise the runner's independent catalog surface,
not the candidate SQL's self-reported intent.  They use no PostgreSQL
connection; the disposable PG17 replay remains a separate integration proof.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "backend/scripts/replay_private_runtime_catalog_pg17.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = _load(RUNNER_PATH, "private_runtime_catalog_delta_runner_test")

INTENT = {
    "affected_objects": [
        "agent_private",
        "agent_private.current_tenant_id()",
        "agent_private.load_turn_context(uuid)",
        "agent_projection_owner",
        "agent_runtime",
        "public.conversations",
        "public.current_igreja_id()",
        "public.pessoas",
    ]
}

PUBLIC_HELPER_ACL_BEFORE = (
    ("authenticated", "EXECUTE", False, "postgres"),
    ("service_role", "EXECUTE", False, "postgres"),
)
PUBLIC_HELPER_ACL_AFTER = PUBLIC_HELPER_ACL_BEFORE + (
    ("agent_projection_owner", "EXECUTE", False, "postgres"),
)


def _surface(
    *,
    functions: dict[str, tuple[object, ...]] | None = None,
    relations: dict[str, tuple[object, ...]] | None = None,
    columns: dict[str, tuple[object, ...]] | None = None,
) -> object:
    if functions is None:
        functions = {
            "public.current_igreja_id()": _public_helper()
        }
    return runner.CatalogSurface(
        current_role="postgres",
        roles={},
        memberships={},
        schemas={},
        relations=relations or {},
        columns=columns or {},
        functions=functions,
        policies={},
        defaults={},
        types={},
        constraints={},
        triggers={},
    )


def _public_helper(
    acl: tuple[tuple[str, str, bool, str], ...] = PUBLIC_HELPER_ACL_BEFORE,
) -> tuple[object, ...]:
    return (
        "postgres",  # owner
        "sql",  # language
        "uuid",  # return type
        0,  # signature arity
        False,  # returns set
        True,  # SECURITY DEFINER
        "s",  # STABLE
        False,  # STRICT
        ("search_path=public, pg_temp",),
        acl,
        "uuid",  # rendered result signature
        "select coalesce(nullif(current_setting('app.tenant_igreja_id', true), ''), null)",
    )


def _expect_delta_rejected(before: object, after: object) -> None:
    with pytest.raises(runner.DatabaseContractError):
        runner._validate_catalog_delta(before, after, INTENT)


@pytest.mark.parametrize(
    ("field", "index", "replacement"),
    (
        ("owner", 0, "attacker"),
        ("language", 1, "plpgsql"),
        ("return type", 2, "text"),
        ("signature arity", 3, 1),
        ("returns set", 4, True),
        ("security definer", 5, False),
        ("volatility", 6, "v"),
        ("strict", 7, True),
        ("configuration", 8, ("search_path=public, evil",)),
        ("rendered signature", 10, "TABLE(secret text)"),
        ("body", 11, "perform exfiltrate();"),
    ),
)
def test_public_helper_rejects_every_non_acl_metadata_change(
    field: str, index: int, replacement: object
) -> None:
    before = _surface(
        functions={"public.current_igreja_id()": _public_helper()}
    )
    mutated = list(_public_helper())
    mutated[index] = replacement
    after = _surface(
        functions={"public.current_igreja_id()": tuple(mutated)}
    )
    _expect_delta_rejected(before, after)


@pytest.mark.parametrize(
    ("adversary", "acl"),
    (
        (
            "extra PUBLIC execute",
            ("PUBLIC", "EXECUTE", False, "postgres"),
        ),
        (
            "extra anon execute",
            ("anon", "EXECUTE", False, "postgres"),
        ),
        (
            "extra runtime execute",
            ("agent_runtime", "EXECUTE", False, "postgres"),
        ),
        (
            "owner grantable execute",
            ("agent_projection_owner", "EXECUTE", True, "postgres"),
        ),
        (
            "removed historical authenticated grant",
            ("authenticated", "EXECUTE", False, "postgres"),
        ),
        (
            "removed historical service grant",
            ("service_role", "EXECUTE", False, "postgres"),
        ),
    ),
)
def test_public_helper_rejects_acl_drift_beyond_one_owner_execute(
    adversary: str, acl: str
) -> None:
    before = _surface(
        functions={"public.current_igreja_id()": _public_helper()}
    )
    current = list(PUBLIC_HELPER_ACL_BEFORE)
    if adversary.startswith("removed historical"):
        current.remove(acl)
    else:
        current.append(acl)
    after = _surface(
        functions={
            "public.current_igreja_id()": _public_helper(tuple(current))
        }
    )
    _expect_delta_rejected(before, after)


def test_public_helper_allows_only_non_grantable_owner_execute_addition() -> None:
    before = _surface(
        functions={"public.current_igreja_id()": _public_helper()}
    )
    after = _surface(
        functions={
            "public.current_igreja_id()": _public_helper(PUBLIC_HELPER_ACL_AFTER)
        }
    )
    runner._validate_catalog_delta(before, after, INTENT)


RELATIONS = ("public.conversations", "public.pessoas")
RELATION_BASE = ("r", "table_owner", "{table_owner=arwdDxt/table_owner}", True, False)


def _relation_surface(
    relation: str, value: tuple[object, ...] = RELATION_BASE
) -> object:
    return _surface(relations={relation: value})


@pytest.mark.parametrize("relation", RELATIONS)
@pytest.mark.parametrize(
    ("mutation", "index", "replacement"),
    (
        ("owner transfer", 1, "anon"),
        ("ACL transfer to anon", 2, "{table_owner=arwdDxt/table_owner,anon=r/table_owner}"),
        ("ACL transfer to authenticated", 2, "{table_owner=arwdDxt/table_owner,authenticated=r/table_owner}"),
        ("relation kind", 0, "p"),
        ("RLS disabled", 3, False),
        ("FORCE RLS enabled", 4, True),
    ),
)
def test_public_relation_rejects_owner_acl_and_metadata_drift(
    relation: str, mutation: str, index: int, replacement: object
) -> None:
    before = _relation_surface(relation)
    mutated = list(RELATION_BASE)
    mutated[index] = replacement
    after = _relation_surface(relation, tuple(mutated))
    _expect_delta_rejected(before, after)


COLUMNS = {
    "public.pessoas.igreja_id": ("uuid", -1, False, None, "", "", None),
    "public.pessoas.id": ("uuid", -1, False, None, "", "", None),
    "public.pessoas.optout": ("boolean", -1, False, None, "", "", None),
    "public.pessoas.sem_interesse": ("boolean", -1, False, None, "", "", None),
    "public.conversations.igreja_id": ("uuid", -1, False, None, "", "", None),
    "public.conversations.id": ("uuid", -1, False, None, "", "", None),
    "public.conversations.pessoa_id": ("uuid", -1, False, None, "", "", None),
    "public.conversations.estado": (
        "conversation_estado",
        -1,
        False,
        None,
        "",
        "",
        None,
    ),
}


def test_eight_public_columns_allow_only_owner_select_acl_delta() -> None:
    before = _surface(
        functions={"public.current_igreja_id()": _public_helper()},
        columns=dict(COLUMNS),
    )
    after_columns = dict(COLUMNS)
    for name, value in COLUMNS.items():
        after_columns[name] = (
            *value[:6],
            "{agent_projection_owner=r/postgres}",
        )
    after = _surface(
        functions={
            "public.current_igreja_id()": _public_helper(PUBLIC_HELPER_ACL_AFTER)
        },
        columns=after_columns,
    )
    runner._validate_catalog_delta(before, after, INTENT)


@pytest.mark.parametrize("column", tuple(COLUMNS))
@pytest.mark.parametrize(
    ("mutation", "index", "replacement"),
    (
        ("dtype", 0, "text"),
        ("not-null", 1, True),
        ("default", 2, "nextval('attacker')"),
    ),
)
def test_eight_public_columns_reject_non_acl_metadata_changes(
    column: str, mutation: str, index: int, replacement: object
) -> None:
    before = _surface(
        functions={"public.current_igreja_id()": _public_helper()},
        columns=dict(COLUMNS),
    )
    mutated = list(COLUMNS[column])
    mutated[index] = replacement
    after_columns = dict(COLUMNS)
    after_columns[column] = tuple(mutated)
    after = _surface(
        functions={
            "public.current_igreja_id()": _public_helper(PUBLIC_HELPER_ACL_AFTER)
        },
        columns=after_columns,
    )
    _expect_delta_rejected(before, after)
