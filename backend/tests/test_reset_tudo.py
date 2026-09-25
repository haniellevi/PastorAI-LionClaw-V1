"""Operator-safety tests for the tenant reset CLI."""

from __future__ import annotations

import pytest

from scripts import reset_tudo

from app.services.tenant_deletion import (
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


def _run(
    monkeypatch,
    argv: list[str],
    *,
    input_fn=lambda prompt: (_ for _ in ()).throw(AssertionError(prompt)),
    counts_error: Exception | None = None,
    reset_result: TenantResetResult | None = None,
    reset_error: Exception | None = None,
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
        return reset_result or TenantResetResult(2, 4)

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
    )
    return status, output, session, engine, engine_calls, reset_calls


def test_dry_run_has_counts_but_never_leaks_the_database_url(monkeypatch) -> None:
    url = "postgresql://operator:super-secret@127.0.0.1/reset_db"
    status, output, session, engine, _, reset_calls = _run(
        monkeypatch, ["--database-url", url]
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
        [
            "--database-url",
            "postgresql://operator:secret@localhost/reset_db",
            "--execute",
        ],
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
        [
            "--database-url",
            "postgresql://operator:secret@localhost/reset_db?host=other-host",
        ],
        input_fn=lambda prompt: (_ for _ in ()).throw(AssertionError(prompt)),
        output=output.append,
        engine_factory=engine_factory,
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
        ["--database-url", "postgresql://operator:secret@localhost%2fother/reset_db"],
        output=lambda _line: None,
        engine_factory=engine_factory,
    )

    assert status == 2
    assert called is False


def test_session_factory_failure_disposes_prepared_engine_without_url_leak() -> None:
    output: list[str] = []
    engine = _Engine()

    status = reset_tudo.main(
        ["--database-url", "postgresql://operator:super-secret@localhost/reset_db"],
        output=output.append,
        engine_factory=lambda *_args, **_kwargs: engine,
        session_factory_factory=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError()),
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
        ["--database-url", "postgresql://operator:super-secret@localhost/reset_db"],
        output=output.append,
        engine_factory=lambda *_args, **_kwargs: engine,
        session_factory_factory=lambda **_kwargs: lambda: session,
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
        ["--database-url", "postgresql://operator:secret@localhost/reset_db"],
        counts_error=blocked,
    )

    rendered = "\n".join(output)
    assert status == 3
    assert "BLOCKED_E4B_POPULATED" in rendered
    assert "e4b_holds=2" in rendered and "e4b_receipts=1" in rendered
    assert not reset_calls and session.commits == 0 and session.rollbacks == 1


def test_execute_reports_e4b_recheck_without_commit(monkeypatch, tmp_path) -> None:
    backup = tmp_path / "prior.pg_dump"
    backup.write_bytes(b"synthetic backup marker")
    blocked = E4bPopulatedError({"e4b_second_tenant": 1})
    status, output, session, _, _, reset_calls = _run(
        monkeypatch,
        [
            "--database-url",
            "postgresql://operator:secret@localhost/reset_db",
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
    backup.write_bytes(b"synthetic backup marker")
    status, output, session, _, _, reset_calls = _run(
        monkeypatch,
        [
            "--database-url",
            "postgresql://operator:secret@localhost/reset_db",
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
    backup.write_bytes(b"synthetic backup marker")
    seen_prompt: list[str] = []

    def input_fn(prompt: str) -> str:
        seen_prompt.append(prompt)
        return "127.0.0.1"

    status, output, session, _, _, reset_calls = _run(
        monkeypatch,
        [
            "--database-url",
            "postgresql://operator:secret@127.0.0.1/reset_db",
            "--execute",
            "--backup-path",
            str(backup),
            "--backup-confirmed",
        ],
        input_fn=input_fn,
    )
    assert status == 0
    assert seen_prompt and "127.0.0.1" in seen_prompt[0]
    assert len(reset_calls) == 1 and session.commits == 1
    assert "igrejas_excluidas=2" in "\n".join(output)
    assert session.executed == [
        "SET LOCAL search_path TO public",
        "SET LOCAL search_path TO public",
    ]


def test_execute_aborts_on_eof_without_dml(monkeypatch, tmp_path) -> None:
    backup = tmp_path / "prior.pg_dump"
    backup.write_bytes(b"synthetic backup marker")

    def eof(_prompt: str) -> str:
        raise EOFError

    status, output, session, _, _, reset_calls = _run(
        monkeypatch,
        [
            "--database-url",
            "postgresql://operator:secret@localhost/reset_db",
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
    backup.write_bytes(b"synthetic backup marker")
    status, output, session, _, _, reset_calls = _run(
        monkeypatch,
        [
            "--database-url",
            "postgresql://operator:secret@localhost/reset_db",
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
