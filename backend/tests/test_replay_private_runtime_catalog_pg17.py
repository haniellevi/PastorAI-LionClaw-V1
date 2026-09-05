from __future__ import annotations

import importlib.util
import hashlib
import json
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


receipt = _load(
    REPO_ROOT / "backend/scripts/verify_private_runtime_pg17_receipt.py",
    "private_runtime_pg17_receipt_test",
)
private_catalog = receipt._load_private_catalog()
replay = None


@pytest.fixture(autouse=True)
def _load_replay_for_one_test():
    global replay
    names = (
        "_pastorai_public_replay_for_private_runtime_pg17",
        "_pastorai_catalog_snapshot_for_pg17_replay",
        "_pastorai_migration_authoring_for_pg17_replay",
        "_pastorai_validated_migration_catalog_head_verifier_1ced5a715987ce9d",
        "_pastorai_private_catalog_for_private_runtime_pg17",
        "_pastorai_private_intent_for_private_runtime_pg17",
        "_pastorai_private_adapter_for_private_runtime_pg17",
        "private_runtime_intent_runtime_v1",
    )
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    try:
        replay = _load(
            REPO_ROOT / "backend/scripts/replay_private_runtime_catalog_pg17.py",
            "private_runtime_pg17_replay_test",
        )
        yield
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def _expected_receipt() -> tuple[str, ...]:
    return receipt.expected_receipt_lines(
        private_migration_count=1,
        private_digest_sha256="a" * 64,
        private_last_basename="20260904_120000_private_runtime_load_turn_context.sql",
        private_last_sha256="b" * 64,
    )


def test_receipt_requires_the_exact_ordered_byte_sequence() -> None:
    expected = _expected_receipt()
    clean = ("\n".join(expected) + "\n").encode("ascii")
    receipt.validate_receipt_bytes(clean, expected)

    spoofed = [
        clean + b"EXTRA=true\n",
        ("\n".join((*expected, expected[3])) + "\n").encode("ascii"),
        ("\n".join(line + "-spoof" if line.startswith("RESULT=") else line for line in expected) + "\n").encode("ascii"),
        ("\n".join("CROSS_TENANT_EVIDENCE=false" if line == "CROSS_TENANT_EVIDENCE=true" else line for line in expected) + "\n").encode("ascii"),
        ("\n".join(reversed(expected)) + "\n").encode("ascii"),
    ]
    for forged in spoofed:
        with pytest.raises(receipt.ReceiptVerificationError):
            receipt.validate_receipt_bytes(forged, expected)


def test_receipt_contract_rejects_non_single_private_append() -> None:
    with pytest.raises(receipt.ReceiptVerificationError):
        receipt.expected_receipt_lines(
            private_migration_count=2,
            private_digest_sha256="a" * 64,
            private_last_basename="20260904_120000_private_runtime_load_turn_context.sql",
            private_last_sha256="b" * 64,
        )


def test_receipt_file_requires_private_stable_regular_file(tmp_path: Path) -> None:
    target = tmp_path / "receipt"
    target.write_bytes(("\n".join(_expected_receipt()) + "\n").encode("ascii"))
    target.chmod(0o600)
    content = receipt._read_stable_receipt(target, private_catalog)
    assert content.endswith(b"\n")

    link = tmp_path / "receipt-link"
    link.symlink_to(target)
    with pytest.raises(receipt.ReceiptVerificationError):
        receipt._read_stable_receipt(link, private_catalog)

    hardlink = tmp_path / "receipt-hardlink"
    hardlink.hardlink_to(target)
    with pytest.raises(receipt.ReceiptVerificationError):
        receipt._read_stable_receipt(hardlink, private_catalog)


def test_receipt_expected_digest_is_derived_from_authenticated_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_directory = tmp_path / "private_runtime"
    private_directory.mkdir()
    name = "20260904_120000_private_runtime_load_turn_context.sql"
    content = b"select 1;\n"
    sql_path = private_directory / name
    sql_path.write_bytes(content)
    entry = {
        "name": name,
        "position": 0,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }
    resulting_digest = private_catalog.private_digest([entry])
    head = private_catalog.default_head()
    head["private_entries"] = [entry]
    head["append_only_batches"] = [
        {
            "batch_id": "private-runtime-catalog-append-0001",
            "entries": [entry],
            "previous_private_digest_sha256": private_catalog.private_digest([]),
            "resulting_private_digest_sha256": resulting_digest,
            "sequence": 1,
        }
    ]
    head["current_head"] = {
        "last_basename": name,
        "private_digest_sha256": resulting_digest,
        "private_migration_count": 1,
    }
    head_path = tmp_path / "private-runtime-catalog-head-v1.json"
    head_path.write_bytes(json.dumps(head).encode("utf-8"))
    monkeypatch.setattr(receipt, "PRIVATE_HEAD_PATH", head_path)
    monkeypatch.setattr(receipt, "PRIVATE_DIRECTORY", private_directory)

    expected = receipt._authenticated_expected(private_catalog)
    assert f"PRIVATE_CATALOG_DIGEST_SHA256={resulting_digest}" in expected
    assert f"PRIVATE_CATALOG_LAST_SHA256={entry['sha256']}" in expected
    clean = ("\n".join(expected) + "\n").encode("ascii")
    receipt.validate_receipt_bytes(clean, expected)


@pytest.mark.parametrize(
    "value",
    [
        "postgresql://postgres:postgres@127.0.0.1:5432/postgres",
        "postgresql://postgres:postgres@0.0.0.0:5432/migration_catalog_current_head_disposable",
        "postgresql://postgres:postgres@127.0.0.1:5432/migration_catalog_current_head_disposable?sslmode=disable",
        "postgresql://postgres:postgres@127.0.0.1:5432/migration_catalog_current_head_disposable#fragment",
    ],
)
def test_runner_rejects_non_disposable_or_non_loopback_dsn(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(replay.DATABASE_URL_ENV, value)
    with pytest.raises(replay.TargetGuardError):
        replay._read_disposable_url()


def test_runner_freezes_source_before_opening_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        replay.DATABASE_URL_ENV,
        "postgresql://postgres:postgres@127.0.0.1:5432/migration_catalog_current_head_disposable",
    )
    def reject_source() -> object:
        raise replay.SourceContractError

    monkeypatch.setattr(replay, "_load_composed_source", reject_source)
    called = False

    def connect(database_url: str, **kwargs: object) -> object:
        nonlocal called
        called = True
        assert database_url.startswith("postgresql://postgres:postgres@127.0.0.1:")
        assert kwargs["connect_timeout"] == 5
        assert kwargs["application_name"] == "pastorai-private-runtime-catalog-pg17-replay"
        raise AssertionError("source contract must fail before connecting")

    with pytest.raises(replay.SourceContractError):
        replay.replay_private_runtime_catalog_pg17(connect=connect)
    assert called is False


def test_owner_policy_expression_is_exactly_bound_to_the_immutable_helper() -> None:
    assert replay._tenant_policy_expression(
        "(igreja_id = agent_private.current_tenant_id())"
    )
    assert replay._tenant_policy_expression(
        "(agent_private.current_tenant_id() = igreja_id)"
    )
    for expression in (
        "igreja_id = current_setting('app.tenant_igreja_id', true)::uuid",
        "igreja_id = agent_private.current_tenant_id() or true",
        "igreja_id = public.current_igreja_id()",
        "igreja_id is not null",
    ):
        assert not replay._tenant_policy_expression(expression)


class _TenantHelperCursor:
    def __init__(self, acl: tuple[bool, bool, bool, bool, bool]) -> None:
        self.acl = acl
        self.sql = ""

    def execute(
        self, sql: str, _parameters: tuple[object, ...] = ()
    ) -> None:
        self.sql = sql

    def fetchone(self) -> tuple[object, ...]:
        if "has_function_privilege" in self.sql:
            return self.acl
        if "procedure.proowner" in self.sql:
            return (
                100,
                "sql",
                "uuid",
                0,
                False,
                False,
                "s",
                False,
                False,
                ("search_path=pg_catalog",),
                "select nullif(pg_catalog.current_setting('app.tenant_igreja_id', true), '')::pg_catalog.uuid",
                None,
            )
        if "to_regrole(current_user)" in self.sql:
            return (100,)
        raise AssertionError(f"unexpected query: {self.sql}")


def test_runner_rejects_extra_immutable_helper_grant() -> None:
    valid = _TenantHelperCursor((True, True, True, False, False))
    replay._validate_tenant_helper(valid, runtime_oid=200, owner_oid=300)

    extra_grant = _TenantHelperCursor((True, True, True, False, True))
    with pytest.raises(replay.DatabaseContractError):
        replay._validate_tenant_helper(extra_grant, runtime_oid=200, owner_oid=300)


class _ProjectionFunctionCursor:
    def __init__(self, acl: tuple[bool, bool, bool, bool]) -> None:
        self.acl = acl
        self.sql = ""
        self.statements: list[str] = []

    def execute(
        self, sql: str, _parameters: tuple[object, ...] = ()
    ) -> None:
        if "has_function_privilege('public'" in sql:
            raise AssertionError("PUBLIC must be checked through aclexplode(grantee=0)")
        self.sql = sql
        self.statements.append(sql)

    def fetchone(self) -> tuple[object, ...]:
        if "privilege.grantee = 0" in self.sql:
            return self.acl
        if "procedure.proowner" in self.sql:
            return (
                300,
                "plpgsql",
                "record",
                1,
                "uuid",
                True,
                True,
                "s",
                True,
                ("row_security=on", "search_path=pg_catalog, agent_private"),
                "select agent_private.current_tenant_id() from public.conversations join public.pessoas on true",
                "TABLE(igreja_id uuid, conversation_id uuid, pessoa_id uuid, conversation_state text, pessoa_optout boolean, pessoa_sem_interesse boolean)",
                None,
            )
        raise AssertionError(f"unexpected query: {self.sql}")


def test_projection_validator_uses_type_identity_and_structured_public_acl() -> None:
    _public, _scaffold, private = replay._load_composed_source()
    valid = _ProjectionFunctionCursor((True, True, False, False))
    replay._validate_projection_function(
        valid,
        owner_oid=300,
        runtime_oid=400,
        private=private.migrations[-1],
    )
    assert any("oidvectortypes(procedure.proargtypes)" in sql for sql in valid.statements)
    assert any("privilege.grantee = 0" in sql for sql in valid.statements)

    forged_public_execute = _ProjectionFunctionCursor((True, True, True, False))
    with pytest.raises(replay.DatabaseContractError):
        replay._validate_projection_function(
            forged_public_execute,
            owner_oid=300,
            runtime_oid=400,
            private=private.migrations[-1],
        )


class _DefaultAclCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.sql = ""

    def execute(
        self, sql: str, _parameters: tuple[object, ...] = ()
    ) -> None:
        self.sql = sql

    def fetchone(self) -> tuple[object, ...]:
        if "to_regrole(current_user)" in self.sql:
            return (100,)
        raise AssertionError(f"unexpected query: {self.sql}")

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


def test_default_acl_validator_accepts_empty_acl_and_rejects_grants() -> None:
    replay._validate_default_acl(_DefaultAclCursor([]), runtime_oid=200, owner_oid=300)
    for forged in (
        [(100, "r", 0, "SELECT", False)],
        [(100, "r", 200, "SELECT", False)],
        [(100, "f", 300, "EXECUTE", True)],
    ):
        with pytest.raises(replay.DatabaseContractError):
            replay._validate_default_acl(
                _DefaultAclCursor(forged), runtime_oid=200, owner_oid=300
            )


class _OwnerPolicyCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def execute(
        self, _sql: str, _parameters: tuple[object, ...] = ()
    ) -> None:
        return None

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


def _owner_policy_rows(
    *,
    barrier_command: str = "r",
    barrier_check: str | None = None,
) -> list[tuple[object, ...]]:
    tenant = "(igreja_id = agent_private.current_tenant_id())"
    return [
        (
            "public.pessoas.agent_projection_owner_select_pessoas",
            "r",
            True,
            (300,),
            tenant,
            None,
        ),
        (
            "public.pessoas.agent_projection_owner_tenant_barrier_pessoas",
            barrier_command,
            False,
            (300,),
            tenant,
            barrier_check,
        ),
        (
            "public.conversations.agent_projection_owner_select_conversations",
            "r",
            True,
            (300,),
            tenant,
            None,
        ),
        (
            "public.conversations.agent_projection_owner_tenant_barrier_conversations",
            barrier_command,
            False,
            (300,),
            tenant,
            barrier_check,
        ),
    ]


def test_owner_policy_validator_accepts_select_barrier_only() -> None:
    replay._validate_owner_policies(
        _OwnerPolicyCursor(_owner_policy_rows()),
        owner_oid=300,
    )
    for forged in (
        _owner_policy_rows(barrier_command="*"),
        _owner_policy_rows(barrier_check="true"),
    ):
        with pytest.raises(replay.DatabaseContractError):
            replay._validate_owner_policies(
                _OwnerPolicyCursor(forged),
                owner_oid=300,
            )


def test_runner_delta_allows_only_the_declared_public_helper_acl_change() -> None:
    def surface(
        functions: dict[str, tuple[object, ...]],
        *,
        relations: dict[str, tuple[object, ...]] | None = None,
        columns: dict[str, tuple[object, ...]] | None = None,
    ) -> object:
        return replay.CatalogSurface(
            current_role="postgres",
            roles={},
            memberships={},
            schemas={},
            relations={} if relations is None else relations,
            columns={} if columns is None else columns,
            functions=functions,
            policies={},
            defaults={},
            types={},
            constraints={},
            triggers={},
        )

    def helper(acl: object, *, body: str = "select current_setting('x')") -> tuple[object, ...]:
        return (
            "postgres",
            "sql",
            "uuid",
            0,
            False,
            False,
            "s",
            False,
            ("search_path=pg_catalog",),
            acl,
            "uuid",
            body,
        )

    intent = {
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
    before_acl = [["PUBLIC", "EXECUTE", False, "postgres"]]
    after_acl = [
        ["PUBLIC", "EXECUTE", False, "postgres"],
        ["agent_projection_owner", "EXECUTE", False, "postgres"],
    ]
    replay._validate_catalog_delta(
        surface({"public.current_igreja_id()": helper(before_acl)}),
        surface({"public.current_igreja_id()": helper(after_acl)}),
        intent,
    )
    undeclared = dict(intent)
    undeclared["affected_objects"] = [
        item for item in intent["affected_objects"]
        if item != "public.current_igreja_id()"
    ]
    with pytest.raises(replay.DatabaseContractError):
        replay._validate_catalog_delta(
            surface({"public.current_igreja_id()": helper(before_acl)}),
            surface({"public.current_igreja_id()": helper(after_acl)}),
            undeclared,
        )

    for forged in (
        helper(after_acl, body="select current_setting('different')"),
        helper(
            [
                ["PUBLIC", "EXECUTE", False, "postgres"],
                ["agent_projection_owner", "EXECUTE", True, "postgres"],
            ]
        ),
        helper(
            [
                ["PUBLIC", "EXECUTE", False, "postgres"],
                ["agent_projection_owner", "EXECUTE", False, "postgres"],
                ["agent_runtime", "EXECUTE", False, "postgres"],
            ]
        ),
        helper("{agent_projection_owner=X/postgres}"),
    ):
        with pytest.raises(replay.DatabaseContractError):
            replay._validate_catalog_delta(
                surface({"public.current_igreja_id()": helper(before_acl)}),
                surface({"public.current_igreja_id()": forged}),
                intent,
            )

    relation_before = {
        "public.pessoas": ("r", "postgres", "{postgres=arwdDxt/postgres}", True, False)
    }
    relation_after = {
        "public.pessoas": ("r", "agent_projection_owner", "{postgres=arwdDxt/postgres}", True, False)
    }
    with pytest.raises(replay.DatabaseContractError):
        replay._validate_catalog_delta(
            surface(
                {"public.current_igreja_id()": helper(before_acl)},
                relations=relation_before,
            ),
            surface(
                {"public.current_igreja_id()": helper(after_acl)},
                relations=relation_after,
            ),
            intent,
        )

    column_before = {
        "public.pessoas.igreja_id": ("uuid", -1, False, None, "", "", None)
    }
    column_acl_after = {
        "public.pessoas.igreja_id": (
            "uuid",
            -1,
            False,
            None,
            "",
            "",
            "{agent_projection_owner=r/postgres}",
        )
    }
    replay._validate_catalog_delta(
        surface(
            {"public.current_igreja_id()": helper(before_acl)},
            columns=column_before,
        ),
        surface(
            {"public.current_igreja_id()": helper(after_acl)},
            columns=column_acl_after,
        ),
        intent,
    )
    column_default_after = dict(column_acl_after)
    column_default_after["public.pessoas.igreja_id"] = (
        "uuid",
        -1,
        False,
        "'forged'::text",
        "",
        "",
        "{agent_projection_owner=r/postgres}",
    )
    with pytest.raises(replay.DatabaseContractError):
        replay._validate_catalog_delta(
            surface(
                {"public.current_igreja_id()": helper(before_acl)},
                columns=column_before,
            ),
            surface(
                {"public.current_igreja_id()": helper(after_acl)},
                columns=column_default_after,
            ),
            intent,
        )


def test_runner_cli_requires_canonical_private_stream_paths() -> None:
    assert replay.main(
        [
            "--catalog-head",
            "docs/governance/migrations/migration-catalog-head-v1.json",
            "--private-directory",
            "backend/migrations/private_runtime",
            "--confirmation",
            replay.CONFIRMATION,
        ]
    ) == replay.CliUsageError.exit_code


class _FakeDatabaseError(Exception):
    def __init__(self, pgcode: str, message: str) -> None:
        super().__init__(message)
        self.pgcode = pgcode


class _RollbackNoopCursor:
    def __init__(self, connection: "_RollbackNoopConnection") -> None:
        self.connection = connection
        self.rows: list[tuple[object, ...]] = []
        self.row: tuple[object, ...] | None = None

    def __enter__(self) -> "_RollbackNoopCursor":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        return None

    def execute(
        self, sql: str, parameters: tuple[object, ...] = ()
    ) -> None:
        self.connection.statements.append(sql)
        normalized = " ".join(sql.lower().split())
        self.rows = []
        self.row = None
        if normalized == "begin":
            self.connection.status = 2
            return
        if normalized == "rollback":
            if self.connection.fail_sql_rollback:
                raise _FakeDatabaseError("XX000", "rollback cleanup failure")
            self.connection.status = 0
            self.connection.role = "postgres"
            self.connection.tenant = ""
            return
        if normalized.startswith("set local role "):
            self.connection.role = normalized.rsplit(" ", 1)[-1]
            return
        if "set_config" in normalized:
            self.connection.tenant = str(parameters[1])
            return
        if "current_user" in normalized and "current_setting" in normalized:
            self.row = (self.connection.role, "postgres", self.connection.tenant)
            return
        if normalized == "private-failing":
            self.connection.status = 3
            raise _FakeDatabaseError("XX000", "private apply failure")
        if "select * from agent_private.load_turn_context" in normalized:
            if self.connection.tenant == "not-a-uuid":
                self.connection.status = 3
                raise _FakeDatabaseError("22023", "invalid tenant context")
            conversation_id = str(parameters[0])
            rows = {
                (
                    "11111111-1111-4111-8111-111111111111",
                    "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                ): (
                    "11111111-1111-4111-8111-111111111111",
                    "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    "ia",
                    False,
                    True,
                ),
                (
                    "22222222-2222-4222-8222-222222222222",
                    "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                ): (
                    "22222222-2222-4222-8222-222222222222",
                    "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                    "humano",
                    True,
                    False,
                ),
            }
            value = rows.get((self.connection.tenant, conversation_id))
            self.rows = [] if value is None else [value]
            return
        if (
            normalized.startswith("select igreja_id from public.pessoas")
            or normalized.startswith("select nome from public.pessoas")
            or normalized.startswith("insert into public.pessoas (id, igreja_id, nome, telefone)")
            or normalized.startswith("update public.pessoas set nome")
            or normalized.startswith("delete from public.pessoas where id =")
        ):
            self.connection.status = 3
            raise _FakeDatabaseError("42501", "permission denied")

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self.row


class _RollbackNoopConnection:
    def __init__(self, *, fail_sql_rollback: bool = False) -> None:
        self.autocommit = True
        self.status = 0
        self.role = "postgres"
        self.tenant = ""
        self.fail_sql_rollback = fail_sql_rollback
        self.python_rollback_calls = 0
        self.statements: list[str] = []
        self.closed = False

    def cursor(self) -> _RollbackNoopCursor:
        return _RollbackNoopCursor(self)

    def get_transaction_status(self) -> int:
        return self.status

    def rollback(self) -> None:
        self.python_rollback_calls += 1

    def close(self) -> None:
        self.closed = True


def test_runtime_validation_uses_sql_rollback_and_cleans_local_scope() -> None:
    connection = _RollbackNoopConnection()

    assert replay._validate_runtime_behaviour(connection) == (True, True)
    assert connection.python_rollback_calls == 0
    assert sum(sql.strip().lower() == "rollback" for sql in connection.statements) == 12
    assert connection.get_transaction_status() == replay.TRANSACTION_STATUS_IDLE
    assert connection.role == "postgres"
    assert connection.tenant == ""


def test_projection_error_remains_primary_when_sql_cleanup_fails() -> None:
    connection = _RollbackNoopConnection(fail_sql_rollback=True)

    with pytest.raises(_FakeDatabaseError) as caught:
        replay._select_projection(
            connection,
            role=replay.PRIVATE_RUNTIME_ROLE,
            tenant="not-a-uuid",
            conversation_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        )

    assert caught.value.pgcode == "22023"
    assert str(caught.value) == "invalid tenant context"
    assert connection.python_rollback_calls == 0


@pytest.mark.parametrize("fail_sql_rollback", [False, True])
def test_private_apply_error_preserves_primary_with_sql_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    fail_sql_rollback: bool,
) -> None:
    connection = _RollbackNoopConnection(fail_sql_rollback=fail_sql_rollback)

    private_migration = replay.LoadedPrivateMigration(
        position=0,
        name="20260905_035815_load_private_runtime_turn_context.sql",
        sha256="a" * 64,
        sql="private-failing",
        intent={},
    )
    private_loaded = replay.LoadedPrivateCatalog(
        digest_sha256="b" * 64,
        migrations=(private_migration,),
    )
    public_loaded = SimpleNamespace(migrations=())
    monkeypatch.setattr(
        replay,
        "_load_composed_source",
        lambda: (public_loaded, "scaffold", private_loaded),
    )
    monkeypatch.setattr(
        replay,
        "_read_disposable_url",
        lambda: ("postgresql://synthetic", replay.DISPOSABLE_DATABASE),
    )
    monkeypatch.setattr(replay, "_capture_catalog_surface", lambda _cursor: None)
    monkeypatch.setattr(replay.public_replay, "_validate_fresh_database", lambda _cursor, _name: 170006)
    monkeypatch.setattr(replay.public_replay, "_ensure_ledgers_absent", lambda _cursor: None)
    monkeypatch.setattr(replay, "_validate_catalog_delta", lambda _before, _after, _intent: None)

    def connect(_database_url: str, **_kwargs: object) -> _RollbackNoopConnection:
        return connection

    with pytest.raises(replay.MigrationReplayError) as caught:
        replay.replay_private_runtime_catalog_pg17(connect=connect)

    assert isinstance(caught.value.__cause__, _FakeDatabaseError)
    assert caught.value.__cause__.pgcode == "XX000"
    assert str(caught.value.__cause__) == "private apply failure"
    assert connection.python_rollback_calls == 0
    assert sum(sql.strip().lower() == "rollback" for sql in connection.statements) == 1
    if not fail_sql_rollback:
        assert connection.get_transaction_status() == replay.TRANSACTION_STATUS_IDLE
        assert connection.role == "postgres"
        assert connection.tenant == ""
    assert connection.closed is True
