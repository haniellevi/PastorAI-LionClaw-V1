#!/usr/bin/env python3
"""Read-only release preflight for the migration batch recorded in ROADMAP.md.

The database connection is forced into a read-only repeatable-read transaction.
This script executes SELECT statements only and never changes a gate, ledger,
schema, or row.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys
from dataclasses import dataclass
from uuid import UUID

try:
    from . import migrate
except ImportError:  # Direct invocation: python3 backend/scripts/release_preflight.py
    import migrate  # type: ignore[no-redef]


DATABASE_URL_ENV = "MIGRATION_DATABASE_URL"
LEDGER = "public.schema_migrations"
BASELINE_DATE = "20261014"
BACKUP_SCHEMA = "public"
CORE_TABLES = ("app_users", "celula_solicitacao", "celulas")

_CREATE_TABLE = re.compile(
    r"""^[ \t]*create\s+(?:unlogged\s+)?table\s+
        (?:if\s+not\s+exists\s+)?
        (?:(?:"?([A-Za-z_][A-Za-z_0-9$]*)"?)\s*\.\s*)?
        "?([A-Za-z_][A-Za-z_0-9$]*)"?
    """,
    re.IGNORECASE | re.MULTILINE | re.VERBOSE,
)


class PreflightError(RuntimeError):
    """A required schema or safe read-only database contract is unavailable."""


@dataclass(frozen=True)
class MigrationState:
    name: str
    state: str


@dataclass(frozen=True)
class CellFkFinding:
    request_id: UUID
    church_id: UUID
    cell_id: UUID


@dataclass(frozen=True)
class DuplicateFinding:
    church_id: UUID
    person_id: UUID
    rows: int


@dataclass(frozen=True)
class PreflightReport:
    migrations: tuple[MigrationState, ...]
    unknown_applied_count: int
    fk_findings: tuple[CellFkFinding, ...]
    duplicate_findings: tuple[DuplicateFinding, ...]
    expected_backup_tables: tuple[str, ...]
    missing_backup_tables: tuple[str, ...]

    @property
    def has_findings(self) -> bool:
        return bool(
            self.unknown_applied_count
            or self.fk_findings
            or self.duplicate_findings
            or self.missing_backup_tables
        )


def _as_uuid(value: object) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PreflightError("a consulta retornou um identificador fora do formato UUID") from exc


def _applied_migrations(cursor) -> set[str]:
    cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (LEDGER,))
    if not cursor.fetchone()[0]:
        raise PreflightError(f"{LEDGER} não existe neste banco")
    cursor.execute(f"SELECT name FROM {LEDGER}")
    return {row[0] for row in cursor.fetchall()}


def _candidate_tables(files: list[str], applied: set[str]) -> tuple[str, ...]:
    """Return tables created after the 14/10 baseline by applied migrations."""
    names: set[str] = set()
    for name in files:
        if name not in applied or name[:8] <= BASELINE_DATE:
            continue
        path = migrate.MIGRATIONS_DIR / name
        try:
            sql = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PreflightError("não foi possível ler o catálogo local de migrations") from exc
        for match in _CREATE_TABLE.finditer(sql):
            schema, table = match.groups()
            if schema is None or schema.lower() == BACKUP_SCHEMA:
                names.add(table.lower())
    return tuple(sorted(names))


def _require_public_tables(cursor, tables: tuple[str, ...]) -> tuple[str, ...]:
    cursor.execute(
        """
        SELECT expected.table_name
        FROM unnest(%s::text[]) AS expected(table_name)
        LEFT JOIN pg_catalog.pg_class AS relation
          ON relation.relname = expected.table_name
         AND relation.relkind IN ('r', 'p')
        LEFT JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
         AND namespace.nspname = %s
        WHERE relation.oid IS NULL OR namespace.oid IS NULL
        ORDER BY expected.table_name
        """,
        (list(tables), BACKUP_SCHEMA),
    )
    return tuple(row[0] for row in cursor.fetchall())


def inspect_connection(connection) -> PreflightReport:
    """Inspect one DB snapshot; leave the read-only transaction open for caller."""
    try:
        connection.set_session(
            readonly=True,
            isolation_level="REPEATABLE READ",
            autocommit=False,
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('transaction_read_only')")
            if cursor.fetchone()[0] != "on":
                raise PreflightError("a conexão não iniciou em transação somente leitura")

            cursor.execute(
                """
                SELECT COALESCE(
                    (SELECT role.rolsuper OR role.rolbypassrls
                     FROM pg_catalog.pg_roles AS role
                     WHERE role.rolname = current_user),
                    false
                )
                """
            )
            if not cursor.fetchone()[0]:
                raise PreflightError(
                    "a role não pode ignorar RLS; o preflight poderia ocultar linhas"
                )

            missing_core = _require_public_tables(cursor, CORE_TABLES)
            if missing_core:
                raise PreflightError(
                    "faltam tabelas necessárias no schema public: "
                    + ", ".join(missing_core)
                )

            files = migrate.migration_files()
            applied = _applied_migrations(cursor)
            pending = set(migrate.pending(files, applied))
            migration_states = tuple(
                MigrationState(name, "PENDENTE" if name in pending else "APLICADA")
                for name in files
            )
            unknown_applied_count = len(applied - set(files))

            cursor.execute(
                """
                SELECT request.id::text, request.igreja_id::text, request.celula_id::text
                FROM public.celula_solicitacao AS request
                WHERE request.igreja_id IS NOT NULL
                  AND request.celula_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM public.celulas AS cell
                    WHERE cell.igreja_id = request.igreja_id
                      AND cell.id = request.celula_id
                  )
                ORDER BY request.id
                """
            )
            fk_findings = tuple(
                CellFkFinding(_as_uuid(row[0]), _as_uuid(row[1]), _as_uuid(row[2]))
                for row in cursor.fetchall()
            )

            cursor.execute(
                """
                SELECT igreja_id::text, pessoa_id::text, count(*)
                FROM public.app_users
                WHERE pessoa_id IS NOT NULL
                GROUP BY igreja_id, pessoa_id
                HAVING count(*) > 1
                ORDER BY igreja_id, pessoa_id
                """
            )
            duplicate_findings = tuple(
                DuplicateFinding(_as_uuid(row[0]), _as_uuid(row[1]), int(row[2]))
                for row in cursor.fetchall()
            )

            expected_backup_tables = _candidate_tables(files, applied)
            missing_backup_tables = _require_public_tables(
                cursor, expected_backup_tables
            )

            return PreflightReport(
                migrations=migration_states,
                unknown_applied_count=unknown_applied_count,
                fk_findings=fk_findings,
                duplicate_findings=duplicate_findings,
                expected_backup_tables=expected_backup_tables,
                missing_backup_tables=missing_backup_tables,
            )
    except PreflightError:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise PreflightError("falha de leitura no preflight; nenhum dado foi alterado") from exc


def render_report(report: PreflightReport, stream=None) -> None:
    stream = stream or sys.stdout
    applied_count = sum(row.state == "APLICADA" for row in report.migrations)
    pending_count = sum(row.state == "PENDENTE" for row in report.migrations)
    print(
        "migrations: "
        f"arquivos={len(report.migrations)} aplicadas={applied_count} "
        f"pendentes={pending_count} sem_arquivo={report.unknown_applied_count}",
        file=stream,
    )
    for row in report.migrations:
        print(f"{row.state} {row.name}", file=stream)

    print(f"celula_solicitacao_fk_violations={len(report.fk_findings)}", file=stream)
    for finding in report.fk_findings:
        print(
            "celula_solicitacao_fk "
            f"id={finding.request_id} igreja_id={finding.church_id} "
            f"celula_id={finding.cell_id}",
            file=stream,
        )

    print(f"app_users_duplicate_groups={len(report.duplicate_findings)}", file=stream)
    for finding in report.duplicate_findings:
        print(
            "app_users_duplicate "
            f"igreja_id={finding.church_id} pessoa_id={finding.person_id} "
            f"linhas={finding.rows}",
            file=stream,
        )

    print(
        "backup_public_tables: "
        f"esperadas={len(report.expected_backup_tables)} "
        f"ausentes={len(report.missing_backup_tables)}",
        file=stream,
    )
    for table in report.missing_backup_tables:
        print(f"backup_public_table_missing=public.{table}", file=stream)

    result = "ACHADOS" if report.has_findings else "SEM_ACHADOS"
    print(f"RESULTADO={result}", file=stream)


def _connect():
    url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not url:
        raise PreflightError(f"defina {DATABASE_URL_ENV} no ambiente seguro")
    import psycopg2

    return psycopg2.connect(url)


def main() -> int:
    connection = None
    try:
        connection = _connect()
        report = inspect_connection(connection)
        render_report(report)
        return 1 if report.has_findings else 0
    except PreflightError as exc:
        print(f"RELEASE_PREFLIGHT_FALHOU: {exc}", file=sys.stderr)
        return 2
    finally:
        if connection is not None:
            if not connection.closed:
                connection.rollback()
                connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
