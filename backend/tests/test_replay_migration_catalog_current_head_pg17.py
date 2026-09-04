from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
import psycopg2
import yaml

from tests.conftest_rls import rls_database_url  # noqa: F401


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = (
    REPO_ROOT
    / "backend"
    / "scripts"
    / "replay_migration_catalog_current_head_pg17.py"
)
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "migration-catalog-head.yml"
PG17_IMAGE = (
    "postgres:17.6-trixie@sha256:"
    "00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929"
)


def _load_module() -> ModuleType:
    name = "replay_migration_catalog_current_head_pg17"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def replay() -> ModuleType:
    return _load_module()


def _entry(module: ModuleType, position: int, raw: bytes) -> Any:
    return module.catalog_snapshot.ValidatedCatalogEntry(
        position=position,
        name=f"20990101_0000{position:02d}_future_{position:02d}.sql",
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )


def _snapshot(module: ModuleType, entries: tuple[Any, ...]) -> Any:
    return module.catalog_snapshot.ValidatedCatalogSnapshot(
        head_content_sha256="1" * 64,
        schema_content_sha256="2" * 64,
        catalog_digest_sha256="3" * 64,
        catalog_directory=str(module.catalog.MIGRATIONS_DIR.absolute()),
        entries=entries,
        operational_authorization=False,
        next_stage_authorized=False,
    )


def _synthetic_tenant_migration(
    replay: ModuleType,
    *,
    basename: str,
    affected_relation: str,
    sql: str,
) -> bytes:
    nodeid = (
        "backend/tests/test_replay_migration_catalog_current_head_pg17.py::"
        "test_appended_tenant_migration_replays_end_to_end_on_real_pg17"
    )
    decision = "docs/decisions/2026-09-02-migration-catalog-evolution.md"
    intent = {
        "affected_relations": [affected_relation],
        "artifact_id": replay.migration_authoring.INTENT_ARTIFACT_ID,
        "base_repository_sha": "1" * 40,
        "cross_tenant_test_nodeids": [nodeid],
        "decision_refs": [decision],
        "global_justification": None,
        "migration_basename": basename,
        "next_stage_authorized": False,
        "operational_authorization": False,
        "pg17_test_nodeids": [nodeid],
        "recovery": {
            "kind": "FORWARD_COMPENSATION",
            "reference": decision,
        },
        "scope": "TENANT",
        "tenant_controls": {
            "acl_review": "EXPLICIT_GRANTS_AND_REVOKES",
            "enable_rls": True,
            "force_rls": True,
            "igreja_id_column": "igreja_id",
            "policy_context": "app.tenant_igreja_id",
        },
    }
    encoded = json.dumps(
        intent,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        replay.migration_authoring.INTENT_PREFIX
        + encoded
        + "\n"
        + "-- OPERATIONAL_AUTHORIZATION=BLOCKED\n"
        + "-- NEXT_STAGE_AUTHORIZED=false\n"
        + sql
    ).encode("ascii")


def _install_synthetic_append(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    basename: str,
    content: bytes,
) -> Any:
    real_snapshot = replay.catalog_snapshot.validated_local_catalog_snapshot()
    assert len(real_snapshot.entries) == replay.catalog.HISTORICAL_COUNT == 75
    entry_type = replay.catalog_snapshot.ValidatedCatalogEntry
    appended = entry_type(
        position=replay.catalog.HISTORICAL_COUNT,
        name=basename,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
    )
    entries = (*real_snapshot.entries, appended)
    digest_input = [
        {
            "position": entry.position,
            "name": entry.name,
            "sha256": entry.sha256,
            "size_bytes": entry.size_bytes,
        }
        for entry in entries
    ]
    synthetic_snapshot = replace(
        real_snapshot,
        catalog_digest_sha256=replay.catalog._catalog_digest(digest_input),
        entries=entries,
    )
    original_stable_read = replay.catalog._read_stable_file
    synthetic_path = Path(real_snapshot.catalog_directory) / basename

    def stable_read(path: Path, **kwargs: Any) -> Any:
        if path == synthetic_path:
            return SimpleNamespace(content=content)
        return original_stable_read(path, **kwargs)

    monkeypatch.setattr(
        replay.catalog_snapshot,
        "validated_local_catalog_snapshot",
        lambda: synthetic_snapshot,
    )
    monkeypatch.setattr(replay.catalog, "_read_stable_file", stable_read)
    return synthetic_snapshot


def _dedicated_replay_urls(
    rls_database_url: str, replay: ModuleType
) -> tuple[str, str, str]:
    parsed = urlsplit(rls_database_url)
    assert parsed.scheme == "postgresql+psycopg2"
    assert parsed.hostname in {"127.0.0.1", "::1"}
    assert parsed.username == "postgres"
    assert parsed.password
    assert parsed.port is not None
    base = parsed._replace(path="/postgres", query="", fragment="")
    guarded_test_url = urlunsplit(base)
    replay_url = urlunsplit(
        base._replace(
            scheme="postgresql",
            path=f"/{replay.DISPOSABLE_DATABASE}",
        )
    )
    admin_url = urlunsplit(base._replace(scheme="postgresql"))
    return guarded_test_url, replay_url, admin_url


def _reset_dedicated_replay_database(
    replay: ModuleType,
    admin_url: str,
    *,
    create: bool,
) -> None:
    connection = psycopg2.connect(admin_url, connect_timeout=5)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select current_database(), "
                "current_setting('server_version_num')::integer, "
                "pg_catalog.inet_server_addr(), current_user"
            )
            database, version, address, user = cursor.fetchone()
            assert database == "postgres"
            assert version // 10_000 == 17
            replay._check_non_public_server_address(address)
            assert user == "postgres"
            cursor.execute(
                "select pg_catalog.pg_terminate_backend(pid) "
                "from pg_catalog.pg_stat_activity "
                "where datname = %s and pid <> pg_catalog.pg_backend_pid()",
                (replay.DISPOSABLE_DATABASE,),
            )
            assert replay.DISPOSABLE_DATABASE == (
                "migration_catalog_current_head_disposable"
            )
            cursor.execute(
                "drop database if exists migration_catalog_current_head_disposable"
            )
            if create:
                cursor.execute(
                    "create database migration_catalog_current_head_disposable"
                )
    finally:
        connection.close()


def test_real_current_head_is_loaded_from_public_validated_snapshot(
    replay: ModuleType,
) -> None:
    loaded = replay._load_current_catalog()
    snapshot = replay.catalog_snapshot.validated_local_catalog_snapshot()

    assert len(loaded.migrations) == len(snapshot.entries)
    assert loaded.digest_sha256 == snapshot.catalog_digest_sha256
    assert tuple(item.name for item in loaded.migrations) == tuple(
        item.name for item in snapshot.entries
    )
    assert all(item.sql for item in loaded.migrations)
    assert snapshot.operational_authorization is False
    assert snapshot.next_stage_authorized is False


def test_replay_dependencies_and_scaffold_are_byte_pinned(
    replay: ModuleType,
) -> None:
    assert hashlib.sha256(replay.AUTHORING_PATH.read_bytes()).hexdigest() == (
        replay.AUTHORING_SHA256
    )
    assert hashlib.sha256(replay.SNAPSHOT_API_PATH.read_bytes()).hexdigest() == (
        replay.SNAPSHOT_API_SHA256
    )
    assert hashlib.sha256(replay.SCAFFOLD_PATH.read_bytes()).hexdigest() == (
        replay.SCAFFOLD_SHA256
    )
    assert hashlib.sha256(replay.SCAFFOLD_SCHEMA_PATH.read_bytes()).hexdigest() == (
        replay.SCAFFOLD_SCHEMA_SHA256
    )


def test_replay_dependency_is_authenticated_before_execution(
    replay: ModuleType,
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "must-not-exist"
    malicious = tmp_path / "new_migration.py"
    malicious.write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed')\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="^replay dependency unavailable$"):
        replay._load_pinned_local_module(
            module_name="_pastorai_rejected_replay_dependency",
            path=malicious,
            expected_sha256=replay.AUTHORING_SHA256,
        )

    assert not sentinel.exists()


def test_catalog_loader_accepts_tenant_only_for_an_appended_current_head(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_by_name: dict[str, bytes] = {}
    entries = []
    for position in range(76):
        raw = f"select {position};\n".encode("ascii")
        entry = _entry(replay, position, raw)
        raw_by_name[entry.name] = raw
        entries.append(entry)
    snapshot = _snapshot(replay, tuple(entries))

    monkeypatch.setattr(
        replay.catalog_snapshot,
        "validated_local_catalog_snapshot",
        lambda: snapshot,
    )

    def stable_read(path: Path, **_kwargs: Any) -> Any:
        return SimpleNamespace(content=raw_by_name[path.name])

    monkeypatch.setattr(replay.catalog, "_read_stable_file", stable_read)
    monkeypatch.setattr(
        replay.migration_authoring,
        "_validate_candidate_intent_for_replay",
        lambda _record, *, basename: {
            "scope": "TENANT",
            "affected_relations": ["public.future_tenant_relation"],
            "pg17_test_nodeids": [
                "backend/tests/test_declared.py::test_pg17_contract"
            ],
            "cross_tenant_test_nodeids": [
                "backend/tests/test_declared.py::test_pg17_contract"
            ],
        },
    )

    loaded = replay._load_current_catalog()

    assert len(loaded.migrations) == 76
    assert loaded.migrations[-1].position == 75
    assert loaded.migrations[-1].sql == "select 75;\n"
    assert loaded.migrations[-1].scope == "TENANT"
    assert loaded.migrations[-1].affected_relations == (
        "public.future_tenant_relation",
    )
    assert loaded.migrations[-1].pg17_test_nodeids == (
        "backend/tests/test_declared.py::test_pg17_contract",
    )
    assert loaded.migrations[-1].cross_tenant_test_nodeids == (
        "backend/tests/test_declared.py::test_pg17_contract",
    )


def test_catalog_loader_rejects_global_scope_for_appended_head(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_by_name: dict[str, bytes] = {}
    entries = []
    for position in range(76):
        raw = f"select {position};\n".encode("ascii")
        entry = _entry(replay, position, raw)
        raw_by_name[entry.name] = raw
        entries.append(entry)
    snapshot = _snapshot(replay, tuple(entries))
    monkeypatch.setattr(
        replay.catalog_snapshot,
        "validated_local_catalog_snapshot",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        replay.catalog,
        "_read_stable_file",
        lambda path, **_kwargs: SimpleNamespace(content=raw_by_name[path.name]),
    )
    monkeypatch.setattr(
        replay.migration_authoring,
        "_validate_candidate_intent_for_replay",
        lambda _record, *, basename: {
            "scope": "GLOBAL",
            "affected_relations": ["public.future_global_relation"],
            "pg17_test_nodeids": [
                "backend/tests/test_declared.py::test_pg17_contract"
            ],
            "cross_tenant_test_nodeids": [],
        },
    )

    with pytest.raises(replay.SourceContractError):
        replay._load_current_catalog()


def test_catalog_loader_blocks_byte_drift_before_any_database_read(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"select 1;\n"
    snapshot = _snapshot(replay, (_entry(replay, 0, raw),))
    monkeypatch.setattr(
        replay.catalog_snapshot,
        "validated_local_catalog_snapshot",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        replay.catalog,
        "_read_stable_file",
        lambda *_args, **_kwargs: SimpleNamespace(content=b"select 2;\n"),
    )

    with pytest.raises(replay.SourceContractError):
        replay._load_current_catalog()


def test_catalog_loader_blocks_snapshot_change_during_load(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"select 1;\n"
    before = _snapshot(replay, (_entry(replay, 0, raw),))
    after = replace(before, head_content_sha256="4" * 64)
    snapshots = iter((before, after))
    monkeypatch.setattr(
        replay.catalog_snapshot,
        "validated_local_catalog_snapshot",
        lambda: next(snapshots),
    )
    monkeypatch.setattr(
        replay.catalog,
        "_read_stable_file",
        lambda *_args, **_kwargs: SimpleNamespace(content=raw),
    )

    with pytest.raises(replay.SourceContractError):
        replay._load_current_catalog()


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        " postgresql://postgres:postgres@127.0.0.1:5432/"
        "migration_catalog_current_head_disposable",
        "postgresql://postgres:postgres@example.com:5432/"
        "migration_catalog_current_head_disposable",
        "postgresql://postgres:postgres@127.0.0.1:5432/postgres",
        "postgresql://postgres:postgres@127.0.0.1:5432/"
        "migration_catalog_current_head_disposable?sslmode=disable",
        "postgresql://other:postgres@127.0.0.1:5432/"
        "migration_catalog_current_head_disposable",
        "postgresql://postgres@127.0.0.1:5432/"
        "migration_catalog_current_head_disposable",
        "postgresql://postgres:postgres@127.0.0.1/"
        "migration_catalog_current_head_disposable",
        "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/"
        "migration_catalog_current_head_disposable",
        "postgresql://postgres:postgres@localhost:5432/"
        "migration_catalog_current_head_disposable",
        "postgresql://postgres:postgres@10.0.0.7:5432/"
        "migration_catalog_current_head_disposable",
    ],
)
def test_target_guard_rejects_non_exact_disposable_loopback_dsn(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv(replay.DATABASE_URL_ENV, raising=False)
    else:
        monkeypatch.setenv(replay.DATABASE_URL_ENV, value)

    with pytest.raises(replay.TargetGuardError):
        replay._read_disposable_url()


def test_target_guard_accepts_dedicated_loopback_database(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = (
        "postgresql://postgres:postgres@127.0.0.1:5432/"
        "migration_catalog_current_head_disposable"
    )
    monkeypatch.setenv(replay.DATABASE_URL_ENV, dsn)

    assert replay._read_disposable_url() == (
        dsn,
        "migration_catalog_current_head_disposable",
    )


def test_target_guard_accepts_literal_ipv6_loopback(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = (
        "postgresql://postgres:postgres@[::1]:5432/"
        "migration_catalog_current_head_disposable"
    )
    monkeypatch.setenv(replay.DATABASE_URL_ENV, dsn)
    assert replay._read_disposable_url() == (
        dsn,
        "migration_catalog_current_head_disposable",
    )


class QueueCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = iter(rows)
        self.executed: list[str] = []

    def execute(self, sql: str, _parameters: object = None) -> None:
        self.executed.append(sql)

    def fetchone(self) -> tuple[Any, ...]:
        return next(self.rows)


def test_fresh_database_guard_requires_pg17_empty_schema_and_no_roles(
    replay: ModuleType,
) -> None:
    cursor = QueueCursor(
        [
            (
                replay.DISPOSABLE_DATABASE,
                170006,
                "172.18.0.2",
                "postgres",
                "postgres",
                "off",
            ),
            (0,),
            (0,),
            (True, True),
        ]
    )

    assert replay._validate_fresh_database(
        cursor, replay.DISPOSABLE_DATABASE
    ) == 170006


@pytest.mark.parametrize(
    "rows",
    [
        [("wrong", 170006, "127.0.0.1", "postgres", "postgres", "off")],
        [
            (
                "migration_catalog_current_head_disposable",
                160010,
                "127.0.0.1",
                "postgres",
                "postgres",
                "off",
            )
        ],
        [
            (
                "migration_catalog_current_head_disposable",
                170006,
                "8.8.8.8",
                "postgres",
                "postgres",
                "off",
            )
        ],
        [
            (
                "migration_catalog_current_head_disposable",
                170006,
                "127.0.0.1",
                "postgres",
                "postgres",
                "off",
            ),
            (1,),
        ],
    ],
)
def test_fresh_database_guard_rejects_wrong_or_nonfresh_target(
    replay: ModuleType,
    rows: list[tuple[Any, ...]],
) -> None:
    with pytest.raises(replay.DatabaseContractError):
        replay._validate_fresh_database(
            QueueCursor(rows), replay.DISPOSABLE_DATABASE
        )


class RecordingCursor:
    def __init__(self, connection: "RecordingConnection") -> None:
        self.connection = connection
        self.executed: list[str] = []

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, sql: str, _parameters: object = None) -> None:
        self.executed.append(sql)
        if sql == "BROKEN":
            raise RuntimeError("database message containing a secret")
        if sql == "LEAVES TRANSACTION OPEN":
            self.connection.transaction_status = 2


class RecordingConnection:
    def __init__(self) -> None:
        self.autocommit = False
        self.closed = False
        self.transaction_status = 0
        self.cursor_instance = RecordingCursor(self)

    def cursor(self) -> RecordingCursor:
        return self.cursor_instance

    def get_transaction_status(self) -> int:
        return self.transaction_status

    def close(self) -> None:
        self.closed = True


def _prepare_replay(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    sql_values: tuple[str, ...] = ("MIGRATION A", "MIGRATION B"),
) -> None:
    migrations = tuple(
        module.LoadedMigration(
            position=position,
            name=f"migration_{position}.sql",
            sha256=str(position) * 64,
            sql=sql,
        )
        for position, sql in enumerate(sql_values, start=1)
    )
    monkeypatch.setattr(
        module,
        "_load_current_catalog",
        lambda: module.LoadedCatalog("a" * 64, migrations),
    )
    monkeypatch.setattr(
        module, "_load_historical_compatibility_scaffold", lambda: "SCAFFOLD"
    )
    monkeypatch.setattr(
        module,
        "_read_disposable_url",
        lambda: ("sanitized-loopback-dsn", module.DISPOSABLE_DATABASE),
    )
    monkeypatch.setattr(
        module, "_validate_fresh_database", lambda _cursor, _name: 170006
    )
    monkeypatch.setattr(module, "_ensure_ledgers_absent", lambda _cursor: None)


def test_replay_executes_scaffold_and_each_current_entry_then_closes(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_replay(replay, monkeypatch)
    connection = RecordingConnection()
    connect_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def connect(*args: Any, **kwargs: Any) -> RecordingConnection:
        connect_calls.append((args, kwargs))
        return connection

    result = replay.replay_current_head_pg17(connect)

    assert result == replay.ReplayResult("a" * 64, 2, 170006)
    assert connect_calls == [
        (
            ("sanitized-loopback-dsn",),
            {
                "connect_timeout": 5,
                "application_name": "pastorai-current-head-pg17-replay",
            },
        )
    ]
    assert connection.autocommit is True
    assert connection.cursor_instance.executed[-3:] == [
        "SCAFFOLD",
        "MIGRATION A",
        "MIGRATION B",
    ]
    assert connection.closed is True


def test_replay_rejects_invalid_source_before_connecting(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        replay,
        "_load_current_catalog",
        lambda: (_ for _ in ()).throw(replay.SourceContractError()),
    )
    connect_calls = 0

    def forbidden_connect(*_args: Any, **_kwargs: Any) -> None:
        nonlocal connect_calls
        connect_calls += 1
        raise AssertionError("invalid source must fail before connect")

    with pytest.raises(replay.SourceContractError):
        replay.replay_current_head_pg17(forbidden_connect)
    assert connect_calls == 0


class TenantContractCursor:
    def __init__(
        self,
        metadata: tuple[Any, ...] | None = (True, True, True, False),
        policies: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self.metadata = metadata
        self.policies = (
            [
                (
                    "tenant_isolation",
                    "*",
                    False,
                    [0],
                    "igreja_id = current_setting('app.tenant_igreja_id', true)::uuid",
                    "igreja_id = current_setting('app.tenant_igreja_id', true)::uuid",
                )
            ]
            if policies is None
            else policies
        )
        self.executed: list[tuple[str, object]] = []

    def execute(self, sql: str, parameters: object = None) -> None:
        self.executed.append((sql, parameters))

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.metadata

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.policies


def test_policy_normalization_never_removes_whitespace_inside_literals(
    replay: ModuleType,
) -> None:
    assert replay._tenant_bound_policy_expression(
        " ( igreja_id = current_setting("
        "'app.tenant_igreja_id', true )::uuid ) "
    )
    assert not replay._tenant_bound_policy_expression(
        "igreja_id = current_setting("
        "'app. tenant_igreja_id', true)::uuid"
    )
    assert not replay._tenant_bound_policy_expression(
        "igreja_id = current_setting('APP.TENANT_IGREJA_ID', true)::uuid"
    )
    assert not replay._tenant_bound_policy_expression(
        "igreja_id = current_setting('app.tenant_igreja_id, true)::uuid"
    )


def test_tenant_relation_postcondition_queries_are_parameterized_and_strict(
    replay: ModuleType,
) -> None:
    cursor = TenantContractCursor()

    replay._validate_tenant_relations(cursor, ("public.cell_reports",))

    assert len(cursor.executed) == 2
    assert cursor.executed[0][1] == ("public", "cell_reports")
    assert cursor.executed[1][1] == ("public", "cell_reports")
    assert "relrowsecurity" in cursor.executed[0][0]
    assert "relforcerowsecurity" in cursor.executed[0][0]
    assert "tenant_column.attnotnull" in cursor.executed[0][0]
    assert "relation_acl.grantee = 0" in cursor.executed[0][0]
    assert "column_acl.grantee = 0" in cursor.executed[0][0]
    assert "protected_column.attacl is not null" in cursor.executed[0][0]
    assert "'{}'::pg_catalog.aclitem[]" not in cursor.executed[0][0]
    assert "pg_catalog.pg_policy" in cursor.executed[1][0]


@pytest.mark.parametrize(
    "metadata, policies",
    (
        (None, []),
        ((False, True, True, False), []),
        ((True, False, True, False), []),
        ((True, True, False, False), []),
        ((True, True, True, True), []),
        ((True, True, True, False), []),
        (
            (True, True, True, False),
            [
                (
                    "tenant_isolation",
                    "*",
                    False,
                    [0],
                    "igreja_id is not null",
                    "igreja_id is not null",
                )
            ],
        ),
        (
            (True, True, True, False),
            [("tenant_isolation", "*", False, [0], None, None)],
        ),
        (
            (True, True, True, False),
            [
                (
                    "tenant_select_only",
                    "r",
                    False,
                    [0],
                    "igreja_id = current_setting('app.tenant_igreja_id', true)::uuid",
                    None,
                )
            ],
        ),
        (
            (True, True, True, False),
            [
                (
                    "literal_only",
                    "*",
                    False,
                    [0],
                    "'app.tenant_igreja_id' = 'app.tenant_igreja_id'",
                    "'app.tenant_igreja_id' = 'app.tenant_igreja_id'",
                )
            ],
        ),
        (
            (True, True, True, False),
            [
                (
                    "permissive_not_a_barrier",
                    "*",
                    True,
                    [0],
                    "igreja_id = current_setting('app.tenant_igreja_id', true)::uuid",
                    "igreja_id = current_setting('app.tenant_igreja_id', true)::uuid",
                )
            ],
        ),
        (
            (True, True, True, False),
            [
                (
                    "wrong_role",
                    "*",
                    False,
                    [123],
                    "igreja_id = current_setting('app.tenant_igreja_id', true)::uuid",
                    "igreja_id = current_setting('app.tenant_igreja_id', true)::uuid",
                )
            ],
        ),
        (
            (True, True, True, False),
            [
                (
                    "token_smuggling",
                    "*",
                    False,
                    [0],
                    "igreja_id is not null and current_setting('other', true) = "
                    "'app.tenant_igreja_id'",
                    "igreja_id is not null and current_setting('other', true) = "
                    "'app.tenant_igreja_id'",
                )
            ],
        ),
        (
            (True, True, True, False),
            [
                (
                    "or_true",
                    "*",
                    False,
                    [0],
                    "igreja_id = current_setting('app.tenant_igreja_id', true)::uuid or true",
                    "igreja_id = current_setting('app.tenant_igreja_id', true)::uuid or true",
                )
            ],
        ),
    ),
)
def test_tenant_relation_postconditions_fail_closed_on_each_missing_control(
    replay: ModuleType,
    metadata: tuple[Any, ...] | None,
    policies: list[tuple[Any, ...]],
) -> None:
    cursor = TenantContractCursor(metadata=metadata, policies=policies)

    with pytest.raises(replay.DatabaseContractError):
        replay._validate_tenant_relations(cursor, ("public.cell_reports",))


@pytest.mark.parametrize(
    "relations",
    (
        (),
        ("private.cell_reports",),
        ("public.cell_reports;drop table churches",),
        ("public.z", "public.a"),
        ("public.a", "public.a"),
    ),
)
def test_tenant_relation_allowlist_is_explicit_sorted_and_injection_safe(
    replay: ModuleType,
    relations: tuple[str, ...],
) -> None:
    cursor = TenantContractCursor()

    with pytest.raises(replay.DatabaseContractError):
        replay._validate_tenant_relations(cursor, relations)
    assert cursor.executed == []


@pytest.mark.rls_integration
def test_tenant_relation_validator_executes_against_real_pg17(
    replay: ModuleType,
    rls_database_url: str,
) -> None:
    dsn = rls_database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    relation = "migration_catalog_tenant_contract_probe"
    with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(f"drop table if exists public.{relation}")
        cursor.execute(
            f"create table public.{relation} "
            "(id uuid primary key, igreja_id uuid not null)"
        )
        cursor.execute(f"alter table public.{relation} enable row level security")
        cursor.execute(f"alter table public.{relation} force row level security")
        cursor.execute(f"revoke all on table public.{relation} from public")
        cursor.execute(
            f"create policy tenant_barrier on public.{relation} "
            "as restrictive for all to public "
            "using (igreja_id = current_setting('app.tenant_igreja_id', true)::uuid) "
            "with check "
            "(igreja_id = current_setting('app.tenant_igreja_id', true)::uuid)"
        )
        replay._validate_tenant_relations(cursor, (f"public.{relation}",))

        cursor.execute(f"alter table public.{relation} no force row level security")
        with pytest.raises(replay.DatabaseContractError):
            replay._validate_tenant_relations(cursor, (f"public.{relation}",))
        cursor.execute(f"drop table public.{relation}")


@pytest.mark.rls_integration
def test_tenant_security_delta_executes_against_real_pg17(
    replay: ModuleType,
    rls_database_url: str,
) -> None:
    dsn = rls_database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    legacy = "migration_catalog_tenant_delta_legacy"
    appended = "migration_catalog_tenant_delta_appended"
    with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(f"drop table if exists public.{appended}")
        cursor.execute(f"drop table if exists public.{legacy}")
        cursor.execute(
            f"create table public.{legacy} "
            "(id uuid primary key, igreja_id uuid not null)"
        )
        cursor.execute(f"alter table public.{legacy} enable row level security")
        cursor.execute(f"revoke all on table public.{legacy} from public")
        before = replay._capture_public_tenant_security_surface(cursor)

        cursor.execute(
            f"create table public.{appended} "
            "(id uuid primary key, igreja_id uuid not null)"
        )
        cursor.execute(f"alter table public.{appended} enable row level security")
        cursor.execute(f"alter table public.{appended} force row level security")
        cursor.execute(f"revoke all on table public.{appended} from public")
        cursor.execute(
            f"create policy tenant_barrier on public.{appended} "
            "as restrictive for all to public "
            "using (igreja_id = current_setting('app.tenant_igreja_id', true)::uuid) "
            "with check "
            "(igreja_id = current_setting('app.tenant_igreja_id', true)::uuid)"
        )
        after = replay._capture_public_tenant_security_surface(cursor)
        replay._validate_tenant_security_delta(
            before,
            after,
            (f"public.{appended}",),
        )
        replay._validate_tenant_relations(cursor, (f"public.{appended}",))

        cursor.execute(f"drop table public.{appended}")
        cursor.execute(f"drop table public.{legacy}")


@pytest.mark.rls_integration
def test_appended_tenant_migration_replays_end_to_end_on_real_pg17(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    rls_database_url: str,
) -> None:
    relation = "public.migration_catalog_e2e_tenant_append"
    basename = "20990101_000001_e2e_tenant_append.sql"
    content = _synthetic_tenant_migration(
        replay,
        basename=basename,
        affected_relation=relation,
        sql="""
create table public.migration_catalog_e2e_tenant_append (
  id uuid primary key,
  igreja_id uuid not null
);
alter table public.migration_catalog_e2e_tenant_append enable row level security;
alter table public.migration_catalog_e2e_tenant_append force row level security;
revoke all on table public.migration_catalog_e2e_tenant_append from public;
create policy migration_catalog_e2e_tenant_barrier
  on public.migration_catalog_e2e_tenant_append
  as restrictive for all to public
  using (igreja_id = current_setting('app.tenant_igreja_id', true)::uuid)
  with check (igreja_id = current_setting('app.tenant_igreja_id', true)::uuid);
""",
    )
    synthetic = _install_synthetic_append(
        replay,
        monkeypatch,
        basename=basename,
        content=content,
    )
    _guarded_url, replay_url, admin_url = _dedicated_replay_urls(
        rls_database_url,
        replay,
    )
    _reset_dedicated_replay_database(replay, admin_url, create=True)
    monkeypatch.setenv(replay.DATABASE_URL_ENV, replay_url)
    try:
        result = replay.replay_current_head_pg17()

        assert result.migration_count == 76
        assert result.catalog_digest_sha256 == synthetic.catalog_digest_sha256
        assert result.postgres_version_num // 10_000 == 17
        with psycopg2.connect(replay_url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                assert replay._tenant_relation_security_state(
                    cursor,
                    relation,
                ) == replay.TenantSecurityState(True, True, True, False, True)
    finally:
        _reset_dedicated_replay_database(replay, admin_url, create=False)


@pytest.mark.rls_integration
@pytest.mark.parametrize(
    "declared_relation, sql",
    (
        (
            "public.migration_catalog_e2e_declared_weak",
            """
create table public.migration_catalog_e2e_declared_weak (
  id uuid primary key,
  igreja_id uuid
);
""",
        ),
        (
            "public.migration_catalog_e2e_declared_placeholder",
            """
create table public.migration_catalog_e2e_undeclared_strong (
  id uuid primary key,
  igreja_id uuid not null
);
alter table public.migration_catalog_e2e_undeclared_strong enable row level security;
alter table public.migration_catalog_e2e_undeclared_strong force row level security;
revoke all on table public.migration_catalog_e2e_undeclared_strong from public;
create policy migration_catalog_e2e_undeclared_barrier
  on public.migration_catalog_e2e_undeclared_strong
  as restrictive for all to public
  using (igreja_id = current_setting('app.tenant_igreja_id', true)::uuid)
  with check (igreja_id = current_setting('app.tenant_igreja_id', true)::uuid);
""",
        ),
        (
            "public.migration_catalog_e2e_declared_strong_with_extra",
            """
create table public.migration_catalog_e2e_declared_strong_with_extra (
  id uuid primary key,
  igreja_id uuid not null
);
alter table public.migration_catalog_e2e_declared_strong_with_extra
  enable row level security;
alter table public.migration_catalog_e2e_declared_strong_with_extra
  force row level security;
revoke all on table public.migration_catalog_e2e_declared_strong_with_extra
  from public;
create policy migration_catalog_e2e_declared_strong_barrier
  on public.migration_catalog_e2e_declared_strong_with_extra
  as restrictive for all to public
  using (igreja_id = current_setting('app.tenant_igreja_id', true)::uuid)
  with check (igreja_id = current_setting('app.tenant_igreja_id', true)::uuid);
create table public.migration_catalog_e2e_undeclared_without_tenant (
  id uuid primary key
);
""",
        ),
    ),
)
def test_appended_tenant_migration_e2e_rejects_weak_or_undeclared_delta(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    rls_database_url: str,
    declared_relation: str,
    sql: str,
) -> None:
    basename = "20990101_000002_e2e_rejected_tenant_append.sql"
    content = _synthetic_tenant_migration(
        replay,
        basename=basename,
        affected_relation=declared_relation,
        sql=sql,
    )
    _install_synthetic_append(
        replay,
        monkeypatch,
        basename=basename,
        content=content,
    )
    _guarded_url, replay_url, admin_url = _dedicated_replay_urls(
        rls_database_url,
        replay,
    )
    _reset_dedicated_replay_database(replay, admin_url, create=True)
    monkeypatch.setenv(replay.DATABASE_URL_ENV, replay_url)
    try:
        with pytest.raises(replay.DatabaseContractError):
            replay.replay_current_head_pg17()
    finally:
        _reset_dedicated_replay_database(replay, admin_url, create=False)


class TenantSurfaceCursor:
    def __init__(self, relations: list[str]) -> None:
        self.relations = relations
        self.current_sql = ""
        self.executed: list[str] = []

    def execute(self, sql: str, _parameters: object = None) -> None:
        self.current_sql = sql
        self.executed.append(sql)

    def fetchone(self) -> tuple[bool, bool, bool, bool]:
        return (True, False, True, False)

    def fetchall(self) -> list[tuple[Any, ...]]:
        if "select 'public.' || c.relname" in self.current_sql:
            return [(relation,) for relation in self.relations]
        return []


def test_public_tenant_security_surface_is_derived_from_the_database(
    replay: ModuleType,
) -> None:
    relations = ["public.cell_reports", "public.pessoas"]
    cursor = TenantSurfaceCursor(relations)

    surface = replay._capture_public_tenant_security_surface(cursor)

    assert tuple(surface) == tuple(relations)
    assert set(surface.values()) == {
        replay.TenantSecurityState(True, False, True, False, False)
    }
    assert "pg_catalog.pg_class" in cursor.executed[0]
    assert "pg_catalog.pg_attribute" not in cursor.executed[0]


def test_public_tenant_security_surface_has_no_32_relation_product_ceiling(
    replay: ModuleType,
) -> None:
    relations = [f"public.tenant_{index:02d}" for index in range(33)]
    surface = replay._capture_public_tenant_security_surface(
        TenantSurfaceCursor(relations)
    )
    assert tuple(surface) == tuple(relations)


@pytest.mark.parametrize(
    "rows",
    ([], [("public.ok", "unexpected")], [(1,)]),
)
def test_all_public_relation_discovery_fails_closed(
    replay: ModuleType,
    rows: list[tuple[Any, ...]],
) -> None:
    cursor = SimpleNamespace(
        execute=lambda _sql: None,
        fetchall=lambda: rows,
    )
    with pytest.raises(replay.DatabaseContractError):
        replay._capture_public_tenant_security_surface(cursor)


def test_tenant_security_delta_allows_unchanged_historical_weakness(
    replay: ModuleType,
) -> None:
    weak = replay.TenantSecurityState(True, False, True, False, False)
    surface = {"public.legacy": weak}
    replay._validate_tenant_security_delta(
        surface,
        surface.copy(),
        ("public.declared",),
    )


@pytest.mark.parametrize(
    "current",
    (
        (False, True, True, False, True),
        (True, False, True, False, True),
        (True, True, False, False, True),
        (True, True, True, True, True),
        (True, True, True, False, False),
    ),
)
def test_tenant_security_delta_rejects_every_boundary_regression(
    replay: ModuleType,
    current: tuple[bool, bool, bool, bool, bool],
) -> None:
    secure = replay.TenantSecurityState(True, True, True, False, True)
    with pytest.raises(replay.DatabaseContractError):
        replay._validate_tenant_security_delta(
            {"public.tenant": secure},
            {"public.tenant": replay.TenantSecurityState(*current)},
            ("public.tenant",),
        )


def test_tenant_security_delta_rejects_drop_rename_and_undeclared_change(
    replay: ModuleType,
) -> None:
    weak = replay.TenantSecurityState(True, False, True, False, False)
    secure = replay.TenantSecurityState(True, True, True, False, True)
    with pytest.raises(replay.DatabaseContractError):
        replay._validate_tenant_security_delta(
            {"public.old_name": weak},
            {"public.new_name": secure},
            ("public.new_name",),
        )
    with pytest.raises(replay.DatabaseContractError):
        replay._validate_tenant_security_delta(
            {"public.tenant": weak},
            {"public.tenant": secure},
            ("public.other",),
        )


def test_tenant_security_delta_requires_new_relation_to_be_strong_and_declared(
    replay: ModuleType,
) -> None:
    weak = replay.TenantSecurityState(True, False, True, False, False)
    secure = replay.TenantSecurityState(True, True, True, False, True)
    before = {"public.legacy": weak}
    replay._validate_tenant_security_delta(
        before,
        {**before, "public.new_tenant": secure},
        ("public.new_tenant",),
    )
    with pytest.raises(replay.DatabaseContractError):
        replay._validate_tenant_security_delta(
            before,
            {**before, "public.new_tenant": weak},
            ("public.new_tenant",),
        )
    with pytest.raises(replay.DatabaseContractError):
        replay._validate_tenant_security_delta(
            before,
            {**before, "public.new_tenant": secure},
            ("public.other",),
        )


def test_tenant_postconditions_run_immediately_after_its_migration(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = replay.LoadedMigration(
        position=75,
        name="20990101_000000_tenant.sql",
        sha256="a" * 64,
        sql="TENANT MIGRATION",
        scope="TENANT",
        affected_relations=("public.cell_reports",),
    )
    monkeypatch.setattr(
        replay,
        "_load_current_catalog",
        lambda: replay.LoadedCatalog("a" * 64, (migration,)),
    )
    monkeypatch.setattr(
        replay, "_load_historical_compatibility_scaffold", lambda: "SCAFFOLD"
    )
    monkeypatch.setattr(
        replay,
        "_read_disposable_url",
        lambda: ("sanitized-loopback-dsn", replay.DISPOSABLE_DATABASE),
    )
    monkeypatch.setattr(
        replay, "_validate_fresh_database", lambda _cursor, _name: 170006
    )
    monkeypatch.setattr(replay, "_ensure_ledgers_absent", lambda _cursor: None)
    connection = RecordingConnection()
    observed: list[tuple[list[str], tuple[str, ...]]] = []
    weak = replay.TenantSecurityState(True, False, True, False, False)
    surfaces = iter(
        (
            {"public.legacy": weak},
            {"public.legacy": weak},
        )
    )
    deltas: list[tuple[dict[str, Any], dict[str, Any], tuple[str, ...]]] = []

    def validate(cursor: RecordingCursor, relations: tuple[str, ...]) -> None:
        observed.append((list(cursor.executed), relations))

    monkeypatch.setattr(replay, "_validate_tenant_relations", validate)
    monkeypatch.setattr(
        replay,
        "_capture_public_tenant_security_surface",
        lambda _cursor: next(surfaces),
    )
    monkeypatch.setattr(
        replay,
        "_validate_tenant_security_delta",
        lambda before, after, relations: deltas.append(
            (before, after, relations)
        ),
    )

    replay.replay_current_head_pg17(lambda *_args, **_kwargs: connection)

    assert len(observed) == 1
    assert observed[0][0][-2:] == ["SCAFFOLD", "TENANT MIGRATION"]
    assert observed[0][1] == ("public.cell_reports",)
    assert len(deltas) == 1
    assert deltas[0][2] == ("public.cell_reports",)


DECLARED_NODEID = (
    "backend/tests/test_apply_migrations.py::"
    "test_bootstrap_ledger_creates_exact_owner_only_contract_and_rerun_is_noop"
)


def _loaded_declared_append(
    replay: ModuleType,
    *,
    nodeids: tuple[str, ...] = (DECLARED_NODEID,),
    cross_tenant: tuple[str, ...] = (DECLARED_NODEID,),
) -> Any:
    migration = replay.LoadedMigration(
        position=replay.catalog.HISTORICAL_COUNT,
        name="20990101_000000_declared_test.sql",
        sha256="a" * 64,
        sql="select 1;",
        scope="TENANT",
        affected_relations=("public.declared_test",),
        pg17_test_nodeids=nodeids,
        cross_tenant_test_nodeids=cross_tenant,
    )
    return replay.LoadedCatalog("b" * 64, (migration,))


def _test_report(
    *,
    passed: bool = False,
    skipped: bool = False,
    failed: bool = False,
    wasxfail: str | None = None,
    when: str = "call",
) -> Any:
    return SimpleNamespace(
        passed=passed,
        skipped=skipped,
        failed=failed,
        wasxfail=wasxfail,
        when=when,
    )


def test_declared_runner_allows_historical_head_without_declared_tests(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical = replay.LoadedMigration(
        position=replay.catalog.HISTORICAL_COUNT - 1,
        name="historical.sql",
        sha256="a" * 64,
        sql="select 1;",
    )
    monkeypatch.setattr(
        replay,
        "_load_current_catalog",
        lambda: replay.LoadedCatalog("b" * 64, (historical,)),
    )
    monkeypatch.delenv(replay.RLS_TEST_DATABASE_URL_ENV, raising=False)

    def forbidden_pytest(*_args: Any, **_kwargs: Any) -> int:
        raise AssertionError("pytest must not run for the historical-only head")

    assert replay.run_declared_migration_tests(forbidden_pytest) == (
        replay.DeclaredTestsResult(0, 0, 0)
    )


@pytest.mark.parametrize(
    "nodeids, cross_tenant",
    (
        ((), ()),
        ((DECLARED_NODEID,), ("backend/tests/test_other.py::test_other",)),
    ),
)
def test_declared_runner_rejects_append_without_complete_nodeid_contract(
    replay: ModuleType,
    nodeids: tuple[str, ...],
    cross_tenant: tuple[str, ...],
) -> None:
    with pytest.raises(replay.SourceContractError):
        replay._declared_test_nodeids(
            _loaded_declared_append(
                replay,
                nodeids=nodeids,
                cross_tenant=cross_tenant,
            )
        )


@pytest.mark.parametrize(
    "value",
    (
        None,
        "postgresql://postgres:postgres@127.0.0.1:5432/postgres",
        "postgresql+psycopg2://postgres:postgres@example.com:5432/postgres",
        "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/rls_disposable",
        "postgresql+psycopg2://postgres@127.0.0.1:5432/postgres",
        "postgresql+psycopg2://postgres:postgres@127.0.0.1/postgres",
        "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/postgres?x=1",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/postgres",
        "postgresql+psycopg2://postgres:postgres@192.168.1.5:5432/postgres",
    ),
)
def test_declared_runner_target_is_exact_loopback_postgres(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv(replay.RLS_TEST_DATABASE_URL_ENV, raising=False)
    else:
        monkeypatch.setenv(replay.RLS_TEST_DATABASE_URL_ENV, value)
    with pytest.raises(replay.TargetGuardError):
        replay._require_declared_tests_target()


def test_declared_runner_executes_every_parameterized_case_via_pytest_api(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    loaded = _loaded_declared_append(replay)
    monkeypatch.setattr(replay, "_load_current_catalog", lambda: loaded)
    monkeypatch.setenv(
        replay.RLS_TEST_DATABASE_URL_ENV,
        "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/postgres",
    )
    observed: dict[str, Any] = {}
    original_directory = Path.cwd()

    def successful_pytest(args: list[str], *, plugins: list[Any]) -> int:
        print("pytest progress must not enter the receipt")
        print("pytest warning must not enter the receipt", file=sys.stderr)
        observed["args"] = args
        observed["cwd"] = Path.cwd()
        audit = plugins[0]
        items = [
            SimpleNamespace(
                nodeid=(
                    "tests/test_apply_migrations.py::"
                    "test_bootstrap_ledger_creates_exact_owner_only_contract_"
                    f"and_rerun_is_noop[{case}]"
                )
            )
            for case in ("first", "second")
        ]
        audit.pytest_collection_modifyitems(items)
        for _item in items:
            audit.pytest_runtest_logreport(_test_report(passed=True))
        return 0

    result = replay.run_declared_migration_tests(successful_pytest)

    assert result == replay.DeclaredTestsResult(1, 2, 2)
    assert Path.cwd() == original_directory
    assert observed["cwd"] == REPO_ROOT / "backend"
    assert "--strict-markers" in observed["args"]
    assert "--runxfail" in observed["args"]
    assert DECLARED_NODEID.removeprefix("backend/") in observed["args"]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize(
    "mode",
    (
        "zero",
        "extra",
        "skip",
        "failure",
        "xfail",
        "xpass",
        "nonzero",
        "exception",
    ),
)
def test_declared_runner_fails_closed_unless_every_case_passes(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    monkeypatch.setattr(
        replay,
        "_load_current_catalog",
        lambda: _loaded_declared_append(replay),
    )
    monkeypatch.setenv(
        replay.RLS_TEST_DATABASE_URL_ENV,
        "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/postgres",
    )
    original_directory = Path.cwd()

    def failing_pytest(_args: list[str], *, plugins: list[Any]) -> int:
        audit = plugins[0]
        if mode == "exception":
            raise RuntimeError("untrusted pytest failure")
        if mode == "zero":
            return 0
        item = SimpleNamespace(
            nodeid=(
                "tests/test_apply_migrations.py::"
                "test_bootstrap_ledger_creates_exact_owner_only_contract_"
                "and_rerun_is_noop"
            )
        )
        items = [item]
        if mode == "extra":
            items.append(SimpleNamespace(nodeid="tests/test_other.py::test_other"))
        audit.pytest_collection_modifyitems(items)
        if mode == "skip":
            audit.pytest_runtest_logreport(
                _test_report(skipped=True, when="setup")
            )
        elif mode == "failure":
            audit.pytest_runtest_logreport(_test_report(failed=True))
        elif mode == "xfail":
            audit.pytest_runtest_logreport(
                _test_report(skipped=True, wasxfail="expected")
            )
        elif mode == "xpass":
            audit.pytest_runtest_logreport(
                _test_report(passed=True, wasxfail="unexpected pass")
            )
        else:
            audit.pytest_runtest_logreport(_test_report(passed=True))
        return 1 if mode == "nonzero" else 0

    with pytest.raises(replay.DeclaredTestsError):
        replay.run_declared_migration_tests(failing_pytest)
    assert Path.cwd() == original_directory


@pytest.mark.parametrize(
    "sql, error_type",
    [
        ("BROKEN", "MigrationReplayError"),
        ("LEAVES TRANSACTION OPEN", "MigrationReplayError"),
    ],
)
def test_replay_blocks_sql_failure_or_open_transaction_and_closes(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    sql: str,
    error_type: str,
) -> None:
    _prepare_replay(replay, monkeypatch, (sql,))
    connection = RecordingConnection()

    with pytest.raises(getattr(replay, error_type)):
        replay.replay_current_head_pg17(lambda *_args, **_kwargs: connection)

    assert connection.closed is True


def test_main_reports_only_sanitized_failure_and_closed_gates(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    def blocked() -> Any:
        raise replay.DatabaseContractError("postgresql://user:secret@example")

    monkeypatch.setattr(replay, "replay_current_head_pg17", blocked)

    assert replay.main(["--confirmation", replay.CONFIRMATION]) == 6
    output = capsys.readouterr()
    combined = output.out + output.err
    assert "secret" not in combined
    assert output.out.splitlines() == [
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "NEXT_STAGE_AUTHORIZED=false",
        "SHARED_ENVIRONMENT_ATTESTATION=false",
    ]
    assert output.err.strip() == (
        "MIGRATION_CATALOG_CURRENT_HEAD_REPLAY_BLOCKED:"
        "DATABASE_CONTRACT_INVALID"
    )


def test_main_reports_declared_test_counts_with_closed_gates(
    replay: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    monkeypatch.setattr(
        replay,
        "run_declared_migration_tests",
        lambda: replay.DeclaredTestsResult(2, 4, 4),
    )

    assert replay.main(
        ["--confirmation", replay.DECLARED_TESTS_CONFIRMATION]
    ) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.splitlines() == [
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "NEXT_STAGE_AUTHORIZED=false",
        "SHARED_ENVIRONMENT_ATTESTATION=false",
        "RESULT=DECLARED_MIGRATION_TESTS_EXECUTED_PG17_DISPOSABLE",
        "DECLARED_NODEID_COUNT=2",
        "COLLECTED_TEST_COUNT=4",
        "PASSED_TEST_COUNT=4",
    ]


def _workflow_jobs() -> dict[str, Any]:
    workflow = yaml.load(
        WORKFLOW_PATH.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert isinstance(workflow, dict)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    return jobs


def _named_step(job: dict[str, Any], name: str) -> dict[str, Any]:
    steps = job.get("steps")
    assert isinstance(steps, list)
    matches = [step for step in steps if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def _job_dependencies(job: dict[str, Any]) -> set[str]:
    needs = job.get("needs")
    if needs is None:
        return set()
    if isinstance(needs, str):
        return {needs}
    assert isinstance(needs, list)
    assert all(isinstance(item, str) for item in needs)
    return set(needs)


def test_workflow_runs_replay_first_in_a_fresh_read_only_pg17_job() -> None:
    jobs = _workflow_jobs()
    assert set(jobs) == {
        "migration-catalog-head",
        "replay-current-head-pg17",
        "declared-nodeids-pg17",
        "replay-guard-tests",
    }
    replay_job = jobs["replay-current-head-pg17"]
    assert _job_dependencies(replay_job) == {"migration-catalog-head"}
    assert replay_job["services"]["postgres"]["image"] == PG17_IMAGE
    assert replay_job["services"]["postgres"]["ports"] == [
        "127.0.0.1:5432:5432"
    ]

    steps = replay_job["steps"]
    execute_index = next(
        index for index, step in enumerate(steps) if step.get("id") == "execute-replay"
    )
    readonly_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Tornar o checkout somente leitura antes do replay"
    )
    assert readonly_index < execute_index
    assert all(
        "scripts/" not in step.get("run", "") for step in steps[:execute_index]
    )
    assert "chmod -R a-w -- \"$GITHUB_WORKSPACE\"" in steps[readonly_index]["run"]
    install = _named_step(replay_job, "Instalar runtime fixado pelo lockfile")
    assert "python -I -S -m venv" in install["run"]
    assert 'bin/python" -I -m pip install --require-hashes' in install["run"]

    execute = steps[execute_index]
    assert execute["continue-on-error"] == "true"
    assert "scripts/replay_migration_catalog_current_head_pg17.py" in execute["run"]
    assert (
        "--confirmation REPLAY_MIGRATION_CATALOG_CURRENT_HEAD_PG17_DISPOSABLE"
        in execute["run"]
    )
    assert "head -c 4097" in execute["run"]
    assert 'bin/python" -I -P' in execute["run"]
    assert "MIGRATION_CATALOG_REPLAY_DATABASE_URL" in execute["env"]


def test_workflow_replay_receipt_is_bounded_and_exact() -> None:
    replay_job = _workflow_jobs()["replay-current-head-pg17"]
    verification = _named_step(replay_job, "Validar receipt exato do replay")
    command = verification["run"]

    assert "always()" in verification["if"]
    assert "python -I -S -" in command
    assert "steps.execute-replay.outcome" in verification["env"][
        "REPLAY_EXECUTION_OUTCOME"
    ]
    assert 'if not receipt_path.is_file():' in command
    assert "if not raw or len(raw) > 4096:" in command
    assert 'if raw != ("\\n".join(expected) + "\\n").encode("ascii"):' in command
    for exact_line in (
        "OPERATIONAL_AUTHORIZATION=BLOCKED",
        "NEXT_STAGE_AUTHORIZED=false",
        "SHARED_ENVIRONMENT_ATTESTATION=false",
        "RESULT=MIGRATION_CATALOG_CURRENT_HEAD_REPLAYED_PG17_DISPOSABLE",
        "CATALOG_MIGRATION_COUNT={migration_count}",
        "CATALOG_DIGEST_SHA256={digest}",
        "POSTGRESQL_MAJOR=17",
    ):
        assert exact_line in command


def test_workflow_declared_nodeids_are_isolated_and_receipt_verified() -> None:
    jobs = _workflow_jobs()
    nodeid_job = jobs["declared-nodeids-pg17"]
    assert _job_dependencies(nodeid_job) == {"replay-current-head-pg17"}
    assert nodeid_job["services"]["postgres"]["image"] == PG17_IMAGE
    assert all(
        "declared-nodeids-pg17" not in _job_dependencies(job)
        for job in jobs.values()
    )

    steps = nodeid_job["steps"]
    execute_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("id") == "execute-declared-nodeids"
    )
    readonly_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Tornar o checkout somente leitura antes dos nodeids"
    )
    assert readonly_index < execute_index
    detection = _named_step(
        nodeid_job,
        "Detectar lote append-only sem executar código candidato",
    )
    assert "python -I -S -" in detection["run"]
    execute = steps[execute_index]
    assert execute["continue-on-error"] == "true"
    assert "steps.declared-contract.outputs.required == 'true'" in execute["if"]
    assert (
        "--confirmation RUN_DECLARED_MIGRATION_TESTS_PG17_DISPOSABLE"
        in execute["run"]
    )
    assert "head -c 4097" in execute["run"]
    assert 'bin/python" -I -P' in execute["run"]

    verification = _named_step(
        nodeid_job, "Validar receipt exato dos nodeids declarados"
    )
    command = verification["run"]
    assert "always()" in verification["if"]
    assert "python -I -S -" in command
    assert "if not raw or len(raw) > 4096" in command
    assert "if len(lines) != 7 or lines[:4] != expected_prefix:" in command
    assert "if nodeids <= 0 or collected < nodeids or passed != collected:" in command
    for exact_line in (
        "RESULT=DECLARED_MIGRATION_TESTS_EXECUTED_PG17_DISPOSABLE",
        "DECLARED_NODEID_COUNT=",
        "COLLECTED_TEST_COUNT=",
        "PASSED_TEST_COUNT=",
    ):
        assert exact_line in command


def test_workflow_guard_tests_are_terminal_and_require_a_nonempty_clean_junit() -> None:
    jobs = _workflow_jobs()
    guard_job = jobs["replay-guard-tests"]
    assert _job_dependencies(guard_job) == {"replay-current-head-pg17"}
    assert guard_job["services"]["postgres"]["image"] == PG17_IMAGE
    assert all(
        "replay-guard-tests" not in _job_dependencies(job) for job in jobs.values()
    )

    steps = guard_job["steps"]
    execute_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("id") == "execute-guard-tests"
    )
    readonly_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name")
        == "Tornar o checkout somente leitura antes dos testes de guarda"
    )
    assert readonly_index < execute_index
    execute = steps[execute_index]
    assert execute["continue-on-error"] == "true"
    assert "--junitxml=\"$RUNNER_TEMP/migration-catalog-replay-guards.xml\"" in execute[
        "run"
    ]
    assert "tests/test_replay_migration_catalog_current_head_pg17.py" in execute["run"]
    assert 'bin/python" -I -P -m pytest' in execute["run"]

    verification = _named_step(guard_job, "Validar JUnit dos testes de guarda")
    command = verification["run"]
    assert "always()" in verification["if"]
    assert "python -I -S -" in command
    assert "if not report_path.is_file():" in command
    assert "if size < 1 or size > 4_194_304:" in command
    assert "ET.fromstring(report_path.read_bytes())" in command
    assert "if tests <= 0 or total(\"failures\") or total(\"errors\")" in command
    assert 'or total("skipped"):' in command


def test_workflow_declared_runner_keeps_strict_pytest_contract() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert '"--strict-markers"' in source
    assert '"--runxfail"' in source
    assert "pytest_main(pytest_args, plugins=[audit])" in source


def test_new_replay_does_not_import_or_replace_a_migration_runner() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "validated_local_catalog_snapshot()" in source
    assert "catalog = catalog_snapshot.catalog" in source
    assert "import verify_migration_catalog_head" not in source
    assert "derive_migration_history_canonical_schema" not in source
    assert "apply_migrations" not in source
    assert "canonical_schema_fingerprint_sha256" not in source
    assert "MIGRATION_CATALOG_REPLAY_DATABASE_URL" in source
