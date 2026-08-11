#!/usr/bin/env python3
"""Executor fail-closed para uma migration SQL explicitamente aprovada.

O histórico local e o ledger ``public.schema_migrations`` podem divergir. Por
isso este módulo nunca reconcilia, cria o ledger, ou aplica automaticamente uma
lista de pendências. Escrita requer, sempre, o basename versionado, o SHA-256
esperado e ``--confirm APPLY``:

    python scripts/apply_migrations.py apply \
      --database-url "postgresql://..." \
      --migration 20260810_031050_explicit_deny_policies_for_closed_tables.sql \
      --sha256 <sha256-exato> \
      --confirm APPLY

``status`` continua exclusivamente read-only, mas falha fechado quando a
situação genérica do ledger não pode ser demonstrada como segura. Não há modo
genérico de ``apply``.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit, urlunsplit


MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"
LEDGER_SCHEMA = "public"
LEDGER_NAME = "schema_migrations"
BOOKKEEPING_TABLE = f"{LEDGER_SCHEMA}.{LEDGER_NAME}"
EXPECTED_LEDGER_COLUMNS = (
    ("name", "text", True),
    ("applied_at", "timestamp with time zone", True),
)
REQUIRED_LEDGER_ROLES = ("anon", "authenticated", "service_role")
TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)
COLUMN_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "REFERENCES")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
MIGRATION_BASENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.sql$")
OUTER_BEGIN_RE = re.compile(r"^\s*begin\s*;\s*(?:--.*)?$", re.IGNORECASE)
OUTER_COMMIT_RE = re.compile(r"^\s*commit\s*;\s*(?:--.*)?$", re.IGNORECASE)
TRANSACTION_SETTING_RE = re.compile(
    r"^\s*set\s+transaction\b.*;\s*(?:--.*)?$", re.IGNORECASE
)
SERIALIZABLE_SETTING_RE = re.compile(
    r"^\s*set\s+transaction\s+isolation\s+level\s+serializable\s*;\s*(?:--.*)?$",
    re.IGNORECASE,
)


class MigrationRunnerError(RuntimeError):
    """Erro conhecido, seguro para exibir sem SQL, DSN ou credenciais."""

    exit_code = 7


class MigrationSelectionError(MigrationRunnerError):
    exit_code = 4


class MigrationExecutionError(MigrationRunnerError):
    exit_code = 5


@dataclass(frozen=True)
class LedgerState:
    """Snapshot read-only do ledger já validado."""

    relation_oid: int
    applied_names: tuple[str, ...]


def normalize_url(url: str) -> str:
    """Converte a variante SQLAlchemy para a forma aceita pelo psycopg2."""
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql://", 1)
    return url


def mask_url(url: str) -> str:
    """Mascara a senha de uma DSN antes de qualquer exibição."""
    try:
        parts = urlsplit(url)
        if parts.password:
            safe_netloc = parts.netloc.replace(f":{parts.password}@", ":***@")
            parts = parts._replace(netloc=safe_netloc)
        return urlunsplit(parts)
    except ValueError:
        return "<url ilegível>"


def resolve_database_url(args: argparse.Namespace) -> str | None:
    """A flag tem prioridade; o fallback legado não é impresso."""
    raw = getattr(args, "database_url", None) or os.environ.get(
        "STAGING_DATABASE_URL"
    )
    return normalize_url(raw) if raw else None


def _migration_root() -> pathlib.Path:
    try:
        root = MIGRATIONS_DIR.resolve(strict=True)
    except FileNotFoundError as exc:
        raise MigrationRunnerError("diretório versionado de migrations não existe") from exc
    if not root.is_dir():
        raise MigrationRunnerError("diretório versionado de migrations é inválido")
    return root


def _validate_catalog(paths: list[pathlib.Path], root: pathlib.Path) -> None:
    seen: set[str] = set()
    seen_casefold: set[str] = set()

    for path in paths:
        if path.parent.resolve() != root:
            raise MigrationSelectionError("catálogo contém arquivo fora da raiz versionada")
        if path.is_symlink() or not path.is_file():
            raise MigrationSelectionError("catálogo contém arquivo não regular ou symlink")
        if not stat.S_ISREG(path.stat().st_mode):
            raise MigrationSelectionError("catálogo contém arquivo não regular")
        if not MIGRATION_BASENAME_RE.fullmatch(path.name):
            raise MigrationSelectionError("catálogo contém basename de migration inválido")
        if path.name in seen or path.name.casefold() in seen_casefold:
            raise MigrationSelectionError("catálogo contém nome de migration duplicado")
        seen.add(path.name)
        seen_casefold.add(path.name.casefold())


def discover_migrations() -> list[pathlib.Path]:
    """Retorna somente arquivos SQL regulares e inequívocos, por basename."""
    root = _migration_root()
    migrations = sorted(root.glob("*.sql"), key=lambda path: path.name)
    _validate_catalog(migrations, root)
    return migrations


def resolve_selected_migration(
    selected_name: str | None, migrations: list[pathlib.Path]
) -> pathlib.Path:
    """Aceita somente um basename regular já presente no catálogo versionado."""
    if not isinstance(selected_name, str) or not selected_name:
        raise MigrationSelectionError("informe --migration com o basename exato")
    if selected_name != selected_name.strip():
        raise MigrationSelectionError("o nome da migration não pode ter espaços externos")
    if (
        "/" in selected_name
        or "\\" in selected_name
        or ":" in selected_name
        or PurePosixPath(selected_name).name != selected_name
        or PureWindowsPath(selected_name).name != selected_name
        or not MIGRATION_BASENAME_RE.fullmatch(selected_name)
    ):
        raise MigrationSelectionError(
            "--migration aceita somente basename regular dentro do diretório versionado"
        )

    matches = [path for path in migrations if path.name == selected_name]
    if len(matches) != 1:
        raise MigrationSelectionError("a migration selecionada não existe ou é ambígua")
    return matches[0]


def _read_verified_migration(path: pathlib.Path, expected_hash: str | None) -> str:
    if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
        raise MigrationSelectionError("--sha256 deve ter exatamente 64 caracteres hexadecimais")

    content = path.read_bytes()
    actual_hash = hashlib.sha256(content).hexdigest()
    if actual_hash != expected_hash.lower():
        raise MigrationSelectionError("o SHA-256 informado não confere com a migration selecionada")

    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MigrationSelectionError("a migration selecionada não é UTF-8 válida") from exc


def _is_ignorable_line(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("--")


def prepare_transactional_sql(sql: str) -> str:
    """Remove apenas um wrapper externo ``BEGIN``/``COMMIT`` inequívoco.

    O executor cria sua própria transação para que a migration e a inserção no
    ledger tenham o mesmo commit. Qualquer controle transacional menos claro é
    recusado; tentar "adivinhar" SQL arbitrário enfraqueceria a atomicidade.
    """
    lines = sql.splitlines(keepends=True)
    begin_lines = [index for index, line in enumerate(lines) if OUTER_BEGIN_RE.fullmatch(line)]
    commit_lines = [index for index, line in enumerate(lines) if OUTER_COMMIT_RE.fullmatch(line)]
    transaction_setting_lines = [
        index for index, line in enumerate(lines) if TRANSACTION_SETTING_RE.fullmatch(line)
    ]
    if any(
        not SERIALIZABLE_SETTING_RE.fullmatch(lines[index])
        for index in transaction_setting_lines
    ):
        raise MigrationSelectionError(
            "a migration contém isolamento transacional não suportado pelo executor atômico"
        )
    if len(transaction_setting_lines) > 1:
        raise MigrationSelectionError(
            "a migration contém controles transacionais ambíguos"
        )

    if not begin_lines and not commit_lines:
        return "".join(
            line
            for index, line in enumerate(lines)
            if index not in transaction_setting_lines
        )
    if len(begin_lines) != 1 or len(commit_lines) != 1:
        raise MigrationSelectionError(
            "a migration contém controle transacional não suportado pelo executor atômico"
        )

    begin_index = begin_lines[0]
    commit_index = commit_lines[0]
    if begin_index >= commit_index:
        raise MigrationSelectionError("wrapper transacional da migration é inválido")
    if any(not _is_ignorable_line(line) for line in lines[:begin_index]) or any(
        not _is_ignorable_line(line) for line in lines[commit_index + 1 :]
    ):
        raise MigrationSelectionError(
            "o wrapper transacional deve envolver todo o conteúdo executável"
        )

    return "".join(
        line
        for index, line in enumerate(lines[begin_index + 1 : commit_index], begin_index + 1)
        if index not in transaction_setting_lines
    )


def _connect(url: str):
    try:
        import psycopg2  # lazy: `list` funciona sem o driver instalado
    except ImportError:  # pragma: no cover - ambiente sem deps
        print(
            "ERRO: psycopg2 não está instalado. A partir de backend/, rode no "
            "venv: python -m pip install --require-hashes -r requirements.lock.",
            file=sys.stderr,
        )
        raise SystemExit(3)

    try:
        conn = psycopg2.connect(url)
    except psycopg2.Error:
        print(
            "ERRO ao conectar ao destino. Detalhes de conexão foram omitidos.",
            file=sys.stderr,
        )
        raise SystemExit(6)

    # Escrita usa uma única transação explícita. Leituras sempre fazem rollback
    # antes de fechar para não persistir qualquer estado de sessão.
    conn.autocommit = False
    return conn


def _ledger_relation(cur) -> tuple[int, bool]:
    cur.execute(
        """
        select c.oid, c.relrowsecurity
        from pg_catalog.pg_class c
        join pg_catalog.pg_namespace n on n.oid = c.relnamespace
        where n.nspname = %s
          and c.relname = %s
          and c.relkind = 'r'
        """,
        (LEDGER_SCHEMA, LEDGER_NAME),
    )
    row = cur.fetchone()
    if row is None:
        raise MigrationRunnerError(
            "ledger public.schema_migrations ausente ou incompatível; "
            "abra o gate separado de hardening do ledger"
        )
    return int(row[0]), bool(row[1])


def _validate_ledger_schema(cur, relation_oid: int) -> tuple[str, ...]:
    cur.execute(
        """
        select a.attname,
               pg_catalog.format_type(a.atttypid, a.atttypmod),
               a.attnotnull
        from pg_catalog.pg_attribute a
        where a.attrelid = %s
          and a.attnum > 0
          and not a.attisdropped
        order by a.attnum
        """,
        (relation_oid,),
    )
    columns = tuple((name, data_type, bool(not_null)) for name, data_type, not_null in cur.fetchall())
    if columns != EXPECTED_LEDGER_COLUMNS:
        raise MigrationRunnerError(
            "schema do ledger é incompatível; abra o gate separado de hardening"
        )

    cur.execute(
        f"select name from {BOOKKEEPING_TABLE} group by name having count(*) > 1 limit 1"
    )
    if cur.fetchone() is not None:
        raise MigrationRunnerError(
            "ledger contém entradas duplicadas; abra o gate separado de reconciliação"
        )

    cur.execute(
        """
        select array_agg(attribute.attname order by key_columns.ordinality)
        from pg_catalog.pg_constraint con
        cross join lateral unnest(con.conkey)
            with ordinality as key_columns(attnum, ordinality)
        join pg_catalog.pg_attribute attribute
          on attribute.attrelid = con.conrelid
         and attribute.attnum = key_columns.attnum
        where con.conrelid = %s
          and con.contype = 'p'
        """,
        (relation_oid,),
    )
    primary_key = tuple(cur.fetchone()[0] or ())
    if primary_key != ("name",):
        raise MigrationRunnerError(
            "ledger não possui chave primária compatível; abra o gate separado de hardening"
        )

    return tuple(column[0] for column in columns)


def _table_privileges(server_version: int) -> tuple[str, ...]:
    return (*TABLE_PRIVILEGES, "MAINTAIN") if server_version >= 170000 else TABLE_PRIVILEGES


def _validate_ledger_security(cur, relation_oid: int, columns: tuple[str, ...], rls_enabled: bool) -> None:
    if not rls_enabled:
        raise MigrationRunnerError(
            "ledger não tem RLS habilitado; abra o gate separado de hardening"
        )

    cur.execute(
        "select rolname, rolbypassrls from pg_catalog.pg_roles where rolname = any(%s)",
        (list(REQUIRED_LEDGER_ROLES),),
    )
    roles = {name: bool(bypass_rls) for name, bypass_rls in cur.fetchall()}
    if set(roles) != set(REQUIRED_LEDGER_ROLES):
        raise MigrationRunnerError(
            "roles esperados do ledger estão ausentes; abra o gate separado de hardening"
        )
    if roles["anon"] or roles["authenticated"] or not roles["service_role"]:
        raise MigrationRunnerError(
            "roles do ledger não atendem ao contrato de segurança; abra o gate separado de hardening"
        )

    cur.execute("show server_version_num")
    server_version = int(cur.fetchone()[0])
    for role in ("anon", "authenticated"):
        for privilege in _table_privileges(server_version):
            cur.execute(
                "select has_table_privilege(%s, %s, %s)",
                (role, relation_oid, privilege),
            )
            if cur.fetchone()[0]:
                raise MigrationRunnerError(
                    "ledger possui privilégio efetivo para papel público; "
                    "abra o gate separado de hardening"
                )
        for column in columns:
            for privilege in COLUMN_PRIVILEGES:
                cur.execute(
                    "select has_column_privilege(%s, %s, %s, %s)",
                    (role, relation_oid, column, privilege),
                )
                if cur.fetchone()[0]:
                    raise MigrationRunnerError(
                        "ledger possui privilégio por coluna para papel público; "
                        "abra o gate separado de hardening"
                    )


def inspect_ledger(
    cur, catalog_names: tuple[str, ...], *, require_generic_consistency: bool
) -> LedgerState:
    """Valida estrutura e segurança do ledger sem criar ou alterar nada."""
    relation_oid, rls_enabled = _ledger_relation(cur)
    columns = _validate_ledger_schema(cur, relation_oid)
    _validate_ledger_security(cur, relation_oid, columns, rls_enabled)

    cur.execute(f"select name from {BOOKKEEPING_TABLE} order by applied_at, name")
    applied_names = tuple(row[0] for row in cur.fetchall())
    unknown = sorted(set(applied_names) - set(catalog_names))
    if unknown:
        raise MigrationRunnerError(
            "ledger contém migration desconhecida; abra o gate separado de reconciliação"
        )

    if require_generic_consistency:
        expected_prefix = catalog_names[: len(applied_names)]
        if applied_names != expected_prefix:
            raise MigrationRunnerError(
                "ordem do ledger diverge do catálogo; aplicação genérica está bloqueada"
            )
        pending_count = len(catalog_names) - len(applied_names)
        if pending_count > 1:
            raise MigrationRunnerError(
                "há múltiplas migrations pendentes; aplicação genérica está bloqueada"
            )

    return LedgerState(relation_oid=relation_oid, applied_names=applied_names)


def _inspect_ledger_fail_closed(
    cur, catalog_names: tuple[str, ...], *, require_generic_consistency: bool
) -> LedgerState:
    """Converte erro inesperado de catálogo em recusa segura, sem detalhes."""
    try:
        return inspect_ledger(
            cur,
            catalog_names,
            require_generic_consistency=require_generic_consistency,
        )
    except MigrationRunnerError:
        raise
    except Exception as exc:  # noqa: BLE001 - catálogo inesperado é bloqueio
        raise MigrationRunnerError(
            "não foi possível validar o ledger com segurança; "
            "abra o gate separado de hardening"
        ) from exc


def _rollback_quietly(conn) -> None:
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001 - não substituir o erro seguro original
        pass


def _print_abort(error: MigrationRunnerError) -> int:
    print(f"ERRO: {error}. Nenhuma migration foi aplicada.", file=sys.stderr)
    return error.exit_code


def cmd_list(_args: argparse.Namespace) -> int:
    try:
        migrations = discover_migrations()
    except MigrationRunnerError as error:
        return _print_abort(error)
    if not migrations:
        print("Nenhuma migration encontrada no diretório versionado.", file=sys.stderr)
        return 1
    print(f"Migrations versionadas ({len(migrations)}):")
    for index, path in enumerate(migrations, 1):
        print(f"  {index:>2}. {path.name}")
    print("\nComando informativo: nenhuma conexão ou escrita foi feita.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    url = resolve_database_url(args)
    if not url:
        print(
            "ERRO: informe o destino com --database-url ou STAGING_DATABASE_URL.",
            file=sys.stderr,
        )
        return 2

    try:
        migrations = discover_migrations()
    except MigrationRunnerError as error:
        return _print_abort(error)
    catalog_names = tuple(path.name for path in migrations)

    conn = _connect(url)
    try:
        with conn.cursor() as cur:
            state = _inspect_ledger_fail_closed(
                cur, catalog_names, require_generic_consistency=True
            )
        _rollback_quietly(conn)
    except MigrationRunnerError as error:
        _rollback_quietly(conn)
        return _print_abort(error)
    finally:
        conn.close()

    pending_count = len(catalog_names) - len(state.applied_names)
    print(f"Destino: {mask_url(url)}")
    print(
        f"Ledger seguro: {len(state.applied_names)} registradas | "
        f"{pending_count} pendente(s)."
    )
    print("Status é read-only; aplicação genérica permanece bloqueada.")
    return 0


def _has_single_file_selection(args: argparse.Namespace) -> bool:
    return all(
        isinstance(getattr(args, attribute, None), str)
        and bool(getattr(args, attribute, None))
        for attribute in ("migration", "sha256", "confirm")
    )


def cmd_apply(args: argparse.Namespace) -> int:
    """Aplica somente um arquivo já conferido, nunca uma lista de pendências."""
    url = resolve_database_url(args)
    if not url:
        print(
            "ERRO: informe o destino com --database-url ou STAGING_DATABASE_URL.",
            file=sys.stderr,
        )
        return 2
    if not _has_single_file_selection(args):
        print(
            "ERRO: aplicação genérica está bloqueada. Informe --migration, "
            "--sha256 e --confirm APPLY para um único arquivo.",
            file=sys.stderr,
        )
        return 4
    if args.confirm != "APPLY":
        print(
            "ERRO: confirmação inválida. Use exatamente --confirm APPLY.",
            file=sys.stderr,
        )
        return 4

    try:
        migrations = discover_migrations()
        selected = resolve_selected_migration(args.migration, migrations)
        sql = prepare_transactional_sql(_read_verified_migration(selected, args.sha256))
    except MigrationRunnerError as error:
        return _print_abort(error)

    catalog_names = tuple(path.name for path in migrations)
    conn = _connect(url)
    try:
        with conn.cursor() as cur:
            # Esta é a primeira instrução da transação. A migration M06 já
            # declara SERIALIZABLE; o wrapper foi removido em memória para que
            # o mesmo isolamento cubra também a validação e o insert no ledger.
            cur.execute("set transaction isolation level serializable")
            # Confirma existência antes de LOCK TABLE; nenhum caminho cria o
            # ledger. Reinspecionamos depois do lock para fechar TOCTOU.
            try:
                _ledger_relation(cur)
                cur.execute(
                    f"lock table {BOOKKEEPING_TABLE} in share row exclusive mode"
                )
                state = _inspect_ledger_fail_closed(
                    cur, catalog_names, require_generic_consistency=False
                )
            except MigrationRunnerError:
                raise
            except Exception as exc:  # noqa: BLE001 - bloqueio seguro do ledger
                raise MigrationRunnerError(
                    "não foi possível validar o ledger com segurança; "
                    "abra o gate separado de hardening"
                ) from exc
            if selected.name in state.applied_names:
                _rollback_quietly(conn)
                print(
                    "A migration selecionada já consta no ledger; nenhuma SQL foi executada."
                )
                return 0

            cur.execute(sql)
            cur.execute(
                f"insert into {BOOKKEEPING_TABLE}(name) values (%s)",
                (selected.name,),
            )
        conn.commit()
    except MigrationRunnerError as error:
        _rollback_quietly(conn)
        return _print_abort(error)
    except Exception:  # noqa: BLE001 - não expor SQL, DSN ou segredos
        _rollback_quietly(conn)
        print(
            "ERRO: a migration selecionada falhou e a transação foi revertida.",
            file=sys.stderr,
        )
        return MigrationExecutionError.exit_code
    finally:
        conn.close()

    print(
        "OK — uma única migration com SHA-256 conferido foi aplicada e registrada "
        "na mesma transação."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Executor fail-closed de uma migration aprovada. Não cria ledger e "
            "não aplica pendências automaticamente."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="lista arquivos versionados; não conecta")

    p_status = sub.add_parser(
        "status", help="preflight genérico read-only; falha se houver drift"
    )
    p_apply = sub.add_parser(
        "apply", help="aplica somente um arquivo com nome, hash e confirmação"
    )
    for command in (p_status, p_apply):
        command.add_argument(
            "--database-url",
            default=None,
            help="connection string do banco alvo; senão usa STAGING_DATABASE_URL",
        )
    p_apply.add_argument("--migration", default=None, help="basename exato do arquivo SQL")
    p_apply.add_argument("--sha256", default=None, help="SHA-256 exato do arquivo")
    p_apply.add_argument(
        "--confirm",
        default=None,
        help="confirmação explícita; use exatamente APPLY",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    handlers = {"list": cmd_list, "status": cmd_status, "apply": cmd_apply}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
