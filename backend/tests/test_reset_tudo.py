"""Operator-safety tests for the tenant reset CLI."""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest

from scripts import reset_tudo

from app.services.tenant_deletion import (
    CleanupTask,
    E4bPopulatedError,
    TenantResetCounts,
    TenantResetPermissionError,
    TenantResetResult,
)


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.executed: list[str] = []

    def execute(self, statement) -> None:
        self.executed.append(str(statement))

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def _counts() -> TenantResetCounts:
    return TenantResetCounts(2, 5, 8, 2, 1, 11)


_DATABASE_URL = "postgresql://operator:synthetic@localhost/reset_db"


def test_help_does_not_offer_database_url_in_argv() -> None:
    help_text = reset_tudo.build_parser().format_help()

    assert "--database-url" not in help_text
    assert "RESET_DATABASE_URL" in help_text
    assert "cabeçalho verificado" in help_text


def test_database_url_in_argv_is_rejected_before_connection() -> None:
    secret_url = "postgresql://operator:argv-secret@localhost/reset_db"
    output: list[str] = []
    called = False

    def engine_factory(*_args, **_kwargs):
        nonlocal called
        called = True
        return _Engine()

    status = reset_tudo.main(
        ["--database-url", secret_url],
        output=output.append,
        engine_factory=engine_factory,
    )

    assert status == 2
    assert called is False
    assert "argv-secret" not in "\n".join(output)


def test_backup_requires_a_recognized_pg_dump_header(tmp_path) -> None:
    backup = tmp_path / "synthetic.dump"
    backup.write_bytes(b"not a pg dump")
    assert reset_tudo.validate_backup_path(str(backup)) is False

    backup.write_bytes(b"PGDMP\x01\x0e\x00synthetic")
    assert reset_tudo.validate_backup_path(str(backup)) is True

    backup.write_bytes(b"-- PostgreSQL database dump\n-- synthetic\n")
    assert reset_tudo.validate_backup_path(str(backup)) is True


def test_backup_never_follows_a_symlink(tmp_path) -> None:
    target = tmp_path / "synthetic.dump"
    target.write_bytes(b"PGDMP\x01\x0e\x00synthetic")
    link = tmp_path / "backup-link.dump"
    os.symlink(target, link)

    assert reset_tudo.validate_backup_path(str(link)) is False


def test_backup_rejects_a_fifo_with_a_nonblocking_open(tmp_path, monkeypatch) -> None:
    fifo = tmp_path / "synthetic.pipe"
    os.mkfifo(fifo)
    keepalive = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
    opened_flags: list[int] = []
    real_open = reset_tudo.os.open

    def tracked_open(path, flags, *args):
        opened_flags.append(flags)
        return real_open(path, flags, *args)

    monkeypatch.setattr(reset_tudo.os, "open", tracked_open)
    try:
        assert reset_tudo.validate_backup_path(str(fifo)) is False
    finally:
        os.close(keepalive)

    assert opened_flags and opened_flags[0] & os.O_NONBLOCK


def test_database_url_comes_from_protected_prompt_without_echo() -> None:
    secret_url = "postgresql://operator:prompt-secret@127.0.0.1/reset_db"
    output: list[str] = []
    session = _Session()
    engine = _Engine()

    status = reset_tudo.main(
        [],
        secret_input=lambda _prompt: secret_url,
        output=output.append,
        engine_factory=lambda *_args, **_kwargs: engine,
        session_factory_factory=lambda **_kwargs: lambda: session,
        environment={},
    )

    assert status == 2
    assert "prompt-secret" not in "\n".join(output)


def test_drain_dry_run_reports_pending_work_as_incomplete(monkeypatch) -> None:
    monkeypatch.setenv(
        "RESET_DATABASE_URL", "postgresql://operator:synthetic@localhost/reset_db"
    )
    state = SimpleNamespace(pending_tasks=(object(),), rejected_tasks=())
    monkeypatch.setattr(
        reset_tudo,
        "load_cleanup_drain_state",
        lambda _session: state,
        raising=False,
    )
    monkeypatch.setattr(
        reset_tudo,
        "run_pending_cleanup",
        lambda *_args, **_kwargs: pytest.fail("dry-run cannot call providers"),
        raising=False,
    )
    output: list[str] = []
    session = _Session()
    engine = _Engine()

    status = reset_tudo.main(
        ["drain-external"],
        output=output.append,
        engine_factory=lambda *_args, **_kwargs: engine,
        session_factory_factory=lambda **_kwargs: lambda: session,
    )

    assert status == 4
    assert "pendentes=1" in "\n".join(output)
    assert session.commits == 0


@pytest.mark.parametrize(
    ("final_pending", "final_rejected", "expected_status"),
    [(0, 0, 0), (1, 0, 4), (0, 1, 5), (1, 1, 4)],
)
def test_drain_execute_runs_committed_pending_tasks_and_rechecks_outcome(
    monkeypatch, final_pending: int, final_rejected: int, expected_status: int
) -> None:
    monkeypatch.setenv(
        "RESET_DATABASE_URL", "postgresql://operator:synthetic@localhost/reset_db"
    )
    task = CleanupTask(
        task_id=uuid.uuid4(),
        igreja_id=uuid.uuid4(),
        kind="clerk_user",
        payload={"clerk_user_id": "clerk-deleted-tenant"},
    )
    states = [
        SimpleNamespace(pending_tasks=(task,), rejected_tasks=()),
        SimpleNamespace(pending_tasks=(task,), rejected_tasks=()),
        SimpleNamespace(
            pending_tasks=(task,) * final_pending,
            rejected_tasks=(object(),) * final_rejected,
        ),
    ]
    load_calls = 0
    cleanup_calls: list[object] = []

    def load(_session):
        nonlocal load_calls
        state = states[min(load_calls, len(states) - 1)]
        load_calls += 1
        return state

    def cleanup(_session, actor, tasks, **_providers):
        cleanup_calls.append((actor, tasks))
        return (SimpleNamespace(status="done"),)

    monkeypatch.setattr(reset_tudo, "load_cleanup_drain_state", load, raising=False)
    monkeypatch.setattr(reset_tudo, "run_pending_cleanup", cleanup, raising=False)
    session = _Session()
    engine = _Engine()

    status = reset_tudo.main(
        ["drain-external", "--execute"],
        input_fn=lambda _prompt: "localhost",
        output=lambda _line: None,
        engine_factory=lambda *_args, **_kwargs: engine,
        session_factory_factory=lambda **_kwargs: lambda: session,
        cleanup_clients_factory=lambda: (object(), object(), object(), object()),
    )

    assert status == expected_status
    assert load_calls >= 2
    assert cleanup_calls and cleanup_calls[0][1] == (task,)
    assert getattr(cleanup_calls[0][0], "execution_host", None) == "localhost"


@pytest.mark.parametrize(
    ("pending", "rejected", "expected_status"),
    [
        (0, 0, 0),
        (1, 0, 4),
        (0, 1, 5),
        (1, 1, 4),
    ],
)
def test_drain_exit_status_distinguishes_pending_and_terminal_rejection(
    monkeypatch, pending: int, rejected: int, expected_status: int
) -> None:
    monkeypatch.setenv(
        "RESET_DATABASE_URL", "postgresql://operator:synthetic@localhost/reset_db"
    )
    state = SimpleNamespace(
        pending_tasks=(object(),) * pending,
        rejected_tasks=(object(),) * rejected,
    )
    monkeypatch.setattr(
        reset_tudo,
        "load_cleanup_drain_state",
        lambda _session: state,
        raising=False,
    )
    output: list[str] = []

    status = reset_tudo.main(
        ["drain-external"],
        output=output.append,
        engine_factory=lambda *_args, **_kwargs: _Engine(),
        session_factory_factory=lambda **_kwargs: lambda: _Session(),
    )

    assert status == expected_status
    assert f"pendentes={pending}" in "\n".join(output)
    assert f"rejeitadas={rejected}" in "\n".join(output)


def test_drain_reapplies_public_search_path_before_each_committed_task(monkeypatch) -> None:
    monkeypatch.setenv(
        "RESET_DATABASE_URL", "postgresql://operator:synthetic@localhost/reset_db"
    )
    tasks = tuple(
        CleanupTask(
            task_id=uuid.uuid4(),
            igreja_id=uuid.uuid4(),
            kind="clerk_user",
            payload={"clerk_user_id": f"clerk-deleted-tenant-{index}"},
        )
        for index in range(2)
    )
    states = [
        SimpleNamespace(pending_tasks=tasks, rejected_tasks=()),
        SimpleNamespace(pending_tasks=tasks, rejected_tasks=()),
        SimpleNamespace(pending_tasks=(), rejected_tasks=()),
    ]
    load_calls = 0

    def load(_session):
        nonlocal load_calls
        state = states[min(load_calls, len(states) - 1)]
        load_calls += 1
        return state

    class TransactionSession(_Session):
        def __init__(self) -> None:
            super().__init__()
            self.search_path: str | None = None
            self.local_search_path = False

        def execute(self, statement) -> None:
            super().execute(statement)
            if "SET LOCAL search_path TO public" in str(statement):
                self.search_path = "public"
                self.local_search_path = True

        def commit(self) -> None:
            super().commit()
            if self.local_search_path:
                self.search_path = None
                self.local_search_path = False

        def rollback(self) -> None:
            super().rollback()
            if self.local_search_path:
                self.search_path = None
                self.local_search_path = False

    session = TransactionSession()
    setup_calls = 0

    def cleanup(received_session, _actor, received_tasks, **providers):
        nonlocal setup_calls
        assert received_session is session and received_tasks == tasks
        before_task = providers["before_task"]
        for _task in received_tasks:
            before_task(session)
            setup_calls += 1
            assert session.search_path == "public"
            session.commit()
            assert session.search_path is None
        return tuple(SimpleNamespace(status="done") for _task in received_tasks)

    monkeypatch.setattr(reset_tudo, "load_cleanup_drain_state", load, raising=False)
    monkeypatch.setattr(reset_tudo, "run_pending_cleanup", cleanup, raising=False)

    status = reset_tudo.main(
        ["drain-external", "--execute"],
        input_fn=lambda _prompt: "localhost",
        output=lambda _line: None,
        engine_factory=lambda *_args, **_kwargs: _Engine(),
        session_factory_factory=lambda **_kwargs: lambda: session,
        cleanup_clients_factory=lambda: (object(), object(), object(), object()),
    )

    assert status == 0
    assert setup_calls == 2


def _run(
    monkeypatch,
    argv: list[str],
    *,
    input_fn=lambda prompt: (_ for _ in ()).throw(AssertionError(prompt)),
    counts_error: Exception | None = None,
    reset_result: TenantResetResult | None = None,
    reset_error: Exception | None = None,
    database_url: str = _DATABASE_URL,
):
    output: list[str] = []
    session = _Session()
    engine = _Engine()
    engine_calls: list[object] = []
    reset_calls: list[object] = []

    def collect(_session):
        if counts_error is not None:
            raise counts_error
        return _counts()

    monkeypatch.setattr(reset_tudo, "collect_reset_counts", collect)

    def reset(session_arg, actor):
        reset_calls.append((session_arg, actor))
        if reset_error is not None:
            raise reset_error
        return reset_result or TenantResetResult(2, 0)

    monkeypatch.setattr(reset_tudo, "reset_all_tenants", reset)

    def engine_factory(url, **kwargs):
        engine_calls.append((url, kwargs))
        return engine

    def factory_factory(**kwargs):
        assert kwargs["bind"] is engine
        return lambda: session

    status = reset_tudo.main(
        argv,
        input_fn=input_fn,
        output=output.append,
        engine_factory=engine_factory,
        session_factory_factory=factory_factory,
        environment={"RESET_DATABASE_URL": database_url},
    )
    return status, output, session, engine, engine_calls, reset_calls


def test_dry_run_has_counts_but_never_leaks_the_database_url(monkeypatch) -> None:
    url = "postgresql://operator:super-secret@127.0.0.1/reset_db"
    status, output, session, engine, _, reset_calls = _run(
        monkeypatch, [], database_url=url
    )
    rendered = "\n".join(output)
    assert status == 0
    assert "host=127.0.0.1" in rendered
    assert "igrejas=2" in rendered
    assert "Dry-run" in rendered
    assert "super-secret" not in rendered and url not in rendered
    assert not reset_calls and session.commits == 0 and engine.disposed is True
    assert session.executed == ["SET LOCAL search_path TO public"]


def test_execute_requires_backup_attestation_before_prompt(monkeypatch) -> None:
    status, output, _, _, _, reset_calls = _run(
        monkeypatch,
        ["--execute"],
    )
    assert status == 2
    assert "host=localhost" in "\n".join(output)
    assert "--backup-confirmed" in "\n".join(output)
    assert not reset_calls


def test_redirecting_libpq_query_is_rejected_before_connection_or_prompt(monkeypatch) -> None:
    output: list[str] = []
    called = False

    def engine_factory(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("connection must not be prepared")

    status = reset_tudo.main(
        [],
        input_fn=lambda prompt: (_ for _ in ()).throw(AssertionError(prompt)),
        output=output.append,
        engine_factory=engine_factory,
        environment={
            "RESET_DATABASE_URL": "postgresql://operator:secret@localhost/reset_db?host=other-host"
        },
    )
    assert status == 2
    assert called is False
    assert "secret" not in "\n".join(output)


def test_encoded_host_is_rejected_before_connection(monkeypatch) -> None:
    called = False

    def engine_factory(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("connection must not be prepared")

    status = reset_tudo.main(
        [],
        output=lambda _line: None,
        engine_factory=engine_factory,
        environment={
            "RESET_DATABASE_URL": "postgresql://operator:secret@localhost%2fother/reset_db"
        },
    )

    assert status == 2
    assert called is False


def test_session_factory_failure_disposes_prepared_engine_without_url_leak() -> None:
    output: list[str] = []
    engine = _Engine()

    status = reset_tudo.main(
        [],
        output=output.append,
        engine_factory=lambda *_args, **_kwargs: engine,
        session_factory_factory=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError()),
        environment={
            "RESET_DATABASE_URL": "postgresql://operator:super-secret@localhost/reset_db"
        },
    )

    assert status == 2
    assert engine.disposed is True
    assert "super-secret" not in "\n".join(output)


def test_dry_run_hides_reset_role_failure_and_never_executes(monkeypatch) -> None:
    output: list[str] = []
    engine = _Engine()
    session = _Session()
    monkeypatch.setattr(
        reset_tudo,
        "collect_reset_counts",
        lambda _session: (_ for _ in ()).throw(TenantResetPermissionError("synthetic")),
    )

    status = reset_tudo.main(
        [],
        output=output.append,
        engine_factory=lambda *_args, **_kwargs: engine,
        session_factory_factory=lambda **_kwargs: lambda: session,
        environment={
            "RESET_DATABASE_URL": "postgresql://operator:super-secret@localhost/reset_db"
        },
    )

    assert status == 2
    assert session.commits == 0 and session.rollbacks == 1
    assert engine.disposed is True
    assert "super-secret" not in "\n".join(output)


def test_inherited_libpq_redirect_environment_is_rejected_without_reading_it() -> None:
    with pytest.raises(reset_tudo.ResetTargetError):
        reset_tudo.parse_target_database_url(
            "postgresql://operator:secret@localhost/reset_db",
            environment={"PGSERVICE": object()},
        )


@pytest.mark.parametrize("environment", ({"PGPORT": object()}, {"PGOPTIONS": object()}))
def test_inherited_libpq_port_or_options_are_rejected_without_connection(
    environment,
) -> None:
    with pytest.raises(reset_tudo.ResetTargetError):
        reset_tudo.parse_target_database_url(
            "postgresql://operator:secret@localhost/reset_db",
            environment=environment,
        )


def test_dry_run_reports_populated_e4b_without_reset_mutation(monkeypatch) -> None:
    blocked = E4bPopulatedError({"e4b_holds": 2, "e4b_receipts": 1})
    status, output, session, _, _, reset_calls = _run(
        monkeypatch,
        [],
        counts_error=blocked,
    )

    rendered = "\n".join(output)
    assert status == 3
    assert "BLOCKED_E4B_POPULATED" in rendered
    assert "e4b_holds=2" in rendered and "e4b_receipts=1" in rendered
    assert not reset_calls and session.commits == 0 and session.rollbacks == 1


def test_execute_reports_e4b_recheck_without_commit(monkeypatch, tmp_path) -> None:
    backup = tmp_path / "prior.pg_dump"
    backup.write_bytes(b"PGDMP\x01\x0e\x00synthetic")
    blocked = E4bPopulatedError({"e4b_second_tenant": 1})
    status, output, session, _, _, reset_calls = _run(
        monkeypatch,
        [
            "--execute",
            "--backup-path",
            str(backup),
            "--backup-confirmed",
        ],
        input_fn=lambda _prompt: "localhost",
        reset_error=blocked,
    )

    rendered = "\n".join(output)
    assert status == 3
    assert "BLOCKED_E4B_POPULATED" in rendered
    assert "e4b_second_tenant=1" in rendered
    assert len(reset_calls) == 1
    assert session.commits == 0 and session.rollbacks >= 2


def test_execute_aborts_when_typed_host_differs(monkeypatch, tmp_path) -> None:
    backup = tmp_path / "prior.pg_dump"
    backup.write_bytes(b"PGDMP\x01\x0e\x00synthetic")
    status, output, session, _, _, reset_calls = _run(
        monkeypatch,
        [
            "--execute",
            "--backup-path",
            str(backup),
            "--backup-confirmed",
        ],
        input_fn=lambda prompt: "other-host",
    )
    assert status == 2
    assert "host não confere" in "\n".join(output)
    assert not reset_calls and session.commits == 0


def test_execute_runs_only_after_exact_interactive_host_confirmation(monkeypatch, tmp_path) -> None:
    backup = tmp_path / "prior.pg_dump"
    backup.write_bytes(b"PGDMP\x01\x0e\x00synthetic")
    seen_prompt: list[str] = []

    def input_fn(prompt: str) -> str:
        seen_prompt.append(prompt)
        return "127.0.0.1"

    status, output, session, _, _, reset_calls = _run(
        monkeypatch,
        [
            "--execute",
            "--backup-path",
            str(backup),
            "--backup-confirmed",
        ],
        input_fn=input_fn,
        database_url="postgresql://operator:secret@127.0.0.1/reset_db",
    )
    assert status == 0
    assert seen_prompt and "127.0.0.1" in seen_prompt[0]
    assert len(reset_calls) == 1 and session.commits == 1
    assert "igrejas_excluidas=2" in "\n".join(output)
    assert session.executed == [
        "SET LOCAL search_path TO public",
        "SET LOCAL search_path TO public",
    ]


def test_execute_commits_reset_but_reports_pending_external_cleanup(
    monkeypatch, tmp_path
) -> None:
    backup = tmp_path / "prior.pg_dump"
    backup.write_bytes(b"PGDMP\x01\x0e\x00synthetic")
    status, output, session, _, _, reset_calls = _run(
        monkeypatch,
        ["--execute", "--backup-path", str(backup), "--backup-confirmed"],
        input_fn=lambda _prompt: "localhost",
        reset_result=TenantResetResult(2, 4),
    )

    assert status == 4
    assert session.commits == 1
    assert len(reset_calls) == 1
    assert "limpezas_externas_pendentes=4" in "\n".join(output)


def test_execute_aborts_on_eof_without_dml(monkeypatch, tmp_path) -> None:
    backup = tmp_path / "prior.pg_dump"
    backup.write_bytes(b"PGDMP\x01\x0e\x00synthetic")

    def eof(_prompt: str) -> str:
        raise EOFError

    status, output, session, _, _, reset_calls = _run(
        monkeypatch,
        [
            "--execute",
            "--backup-path",
            str(backup),
            "--backup-confirmed",
        ],
        input_fn=eof,
    )
    assert status == 2
    assert "não recebida" in "\n".join(output)
    assert not reset_calls and session.commits == 0


def test_execute_failure_requires_audit_confirmation_before_retry(monkeypatch, tmp_path) -> None:
    backup = tmp_path / "prior.pg_dump"
    backup.write_bytes(b"PGDMP\x01\x0e\x00synthetic")
    status, output, session, _, _, reset_calls = _run(
        monkeypatch,
        [
            "--execute",
            "--backup-path",
            str(backup),
            "--backup-confirmed",
        ],
        input_fn=lambda _prompt: "localhost",
        reset_error=RuntimeError("synthetic post-commit ambiguity"),
    )
    assert status == 2
    assert len(reset_calls) == 1
    assert session.commits == 0 and session.rollbacks >= 2
    assert "confirme o resultado pelo audit antes de repetir" in "\n".join(output)
