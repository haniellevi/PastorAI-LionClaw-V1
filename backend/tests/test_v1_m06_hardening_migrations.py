"""Guardas estruturais das migrations propostas pela Missão 06."""

from pathlib import Path


MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
POLICIES = MIGRATIONS / "20260810_031050_explicit_deny_policies_for_closed_tables.sql"
FK_INDEX = (
    MIGRATIONS
    / "20260810_031051_index_agent_conversation_logs_conversation_foreign_key.sql"
)


def _sql(path: Path) -> str:
    executable_lines = (
        line.split("--", 1)[0]
        for line in path.read_text(encoding="utf-8").lower().splitlines()
    )
    return " ".join("\n".join(executable_lines).split())


def test_closed_tables_receive_only_an_explicit_deny_policy() -> None:
    sql = _sql(POLICIES)

    for table in (
        "password_reset_tokens",
        "platform_admins",
        "platform_audit_log",
        "platform_orchestrator",
    ):
        assert f"'{table}'" in sql

    assert "create policy service_role_bypass_only" in sql
    assert "for all to public using (false) with check (false)" in sql
    assert "from pg_policy" in sql
    assert "not exists" in sql
    assert sql.count("create policy") == 1

    # Esta onda não muda grants nem substitui policies que possam surgir antes
    # do gate de aplicação.
    assert "grant " not in sql
    assert "revoke " not in sql
    assert "drop policy" not in sql
    assert "disable row level security" not in sql
    assert "using (true)" not in sql
    assert "with check (true)" not in sql


def test_agent_conversation_fk_index_is_additive_and_idempotent() -> None:
    sql = _sql(FK_INDEX)

    assert (
        "create index concurrently if not exists "
        "idx_agent_conversation_logs_conversation_id_fk "
        "on public.agent_conversation_logs (conversation_id)"
    ) in sql
    assert sql.count("create index") == 1
    assert "begin;" not in sql
    assert "commit;" not in sql
    assert "drop index" not in sql
    assert "reindex" not in sql
