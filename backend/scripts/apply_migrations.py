#!/usr/bin/env python3
"""Executor fail-closed para uma migration SQL explicitamente aprovada.

O histórico local e o ledger ``public.schema_migrations`` podem divergir. Por
isso este módulo nunca reconcilia, cria o ledger, ou aplica automaticamente uma
lista de pendências. Escrita requer, sempre, o basename versionado, o SHA-256
esperado e ``--confirm APPLY``:

    python scripts/apply_migrations.py apply \
      --migration 20260810_031050_explicit_deny_policies_for_closed_tables.sql \
      --sha256 <sha256-exato> \
      --confirm APPLY

O destino é injetado exclusivamente pela variável de ambiente
``M06_MIGRATION_DATABASE_URL``; a CLI não aceita DSN em argv nem a exibe.

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


MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"
DATABASE_URL_ENV = "M06_MIGRATION_DATABASE_URL"
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
DOLLAR_QUOTE_START_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
TRANSACTION_CONTROL_RE = re.compile(
    r"^(?:"
    r"begin\b|start\s+transaction\b|commit\b|end\b|"
    r"rollback\b|abort\b|savepoint\b|release(?:\s+savepoint)?\b|"
    r"prepare\s+transaction\b|"
    r"set\s+(?:(?:local|session)\s+)?transaction\b|"
    r"set\s+session\s+characteristics\s+as\s+transaction\b"
    r")",
    re.IGNORECASE,
)
SAFE_BEGIN_RE = re.compile(r"^begin$", re.IGNORECASE)
SAFE_SERIALIZABLE_RE = re.compile(
    r"^set\s+transaction\s+isolation\s+level\s+serializable$", re.IGNORECASE
)
SAFE_COMMIT_RE = re.compile(r"^commit$", re.IGNORECASE)
USAGE_ERROR_MESSAGE = "ERRO: argumentos inválidos. Use --help para opções suportadas."


class MigrationRunnerError(RuntimeError):
    """Erro conhecido, seguro para exibir sem SQL, DSN ou credenciais."""

    exit_code = 7


class MigrationSelectionError(MigrationRunnerError):
    exit_code = 4


class MigrationExecutionError(MigrationRunnerError):
    exit_code = 5


class CliUsageError(RuntimeError):
    """Erro de uso deliberadamente sem detalhes fornecidos pelo operador."""


class SanitizedArgumentParser(argparse.ArgumentParser):
    """ArgumentParser que nunca reflete valores recebidos em argv."""

    def error(self, _message: str) -> None:
        # O argparse padrão inclui o argumento inesperado/valor inválido no
        # stderr. Isso pode transformar uma DSN, token ou senha colada por
        # engano em log persistente. O texto recebido não é sequer formatado.
        raise CliUsageError


@dataclass(frozen=True)
class FileIdentity:
    """Identidade estável usada para recusar troca de arquivo durante o apply."""

    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def from_stat(cls, result: os.stat_result) -> "FileIdentity":
        return cls(
            device=int(result.st_dev),
            inode=int(result.st_ino),
            size=int(result.st_size),
            mtime_ns=int(result.st_mtime_ns),
            # No Windows, lstat e fstat podem expor ctime distintos para o
            # mesmo arquivo em volumes sincronizados. Inode, tamanho e mtime
            # continuam conferidos; em POSIX ctime reforça a detecção de swap.
            ctime_ns=int(result.st_ctime_ns) if os.name != "nt" else 0,
        )


@dataclass(frozen=True)
class MigrationFile:
    """Entrada imutável do catálogo, ancorada na raiz versionada."""

    path: pathlib.Path
    root: pathlib.Path
    root_identity: FileIdentity
    identity: FileIdentity

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class SqlStatement:
    """Statement SQL e sua forma sem comentários para validação de controle."""

    raw: str
    normalized: str


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


def resolve_database_url(args: argparse.Namespace) -> str | None:
    """Lê a URL somente do ambiente; o atributo privado existe para testes."""
    raw = getattr(args, "_database_url_for_test", None) or os.environ.get(
        DATABASE_URL_ENV
    )
    return normalize_url(raw) if raw else None


def _migration_root() -> pathlib.Path:
    configured = pathlib.Path(MIGRATIONS_DIR)
    try:
        configured_stat = configured.lstat()
    except FileNotFoundError as exc:
        raise MigrationRunnerError("diretório versionado de migrations não existe") from exc
    if stat.S_ISLNK(configured_stat.st_mode):
        raise MigrationRunnerError("diretório versionado de migrations não pode usar symlink")
    if not stat.S_ISDIR(configured_stat.st_mode):
        raise MigrationRunnerError("diretório versionado de migrations é inválido")
    root = configured.resolve(strict=True)
    configured_absolute = configured.absolute()
    if os.path.normcase(os.fspath(root)) != os.path.normcase(
        os.fspath(configured_absolute)
    ):
        raise MigrationRunnerError("diretório versionado de migrations não pode usar symlink")
    return root


def _validate_catalog(paths: list[pathlib.Path], root: pathlib.Path) -> list[MigrationFile]:
    seen: set[str] = set()
    seen_casefold: set[str] = set()
    root_identity = FileIdentity.from_stat(root.lstat())
    candidates: list[MigrationFile] = []

    for path in paths:
        if path.parent != root:
            raise MigrationSelectionError("catálogo contém arquivo fora da raiz versionada")
        try:
            path_stat = path.lstat()
        except FileNotFoundError as exc:
            raise MigrationSelectionError("catálogo mudou durante a validação") from exc
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise MigrationSelectionError("catálogo contém arquivo não regular ou symlink")
        if not MIGRATION_BASENAME_RE.fullmatch(path.name):
            raise MigrationSelectionError("catálogo contém basename de migration inválido")
        if path.name in seen or path.name.casefold() in seen_casefold:
            raise MigrationSelectionError("catálogo contém nome de migration duplicado")
        seen.add(path.name)
        seen_casefold.add(path.name.casefold())
        candidates.append(
            MigrationFile(
                path=path,
                root=root,
                root_identity=root_identity,
                identity=FileIdentity.from_stat(path_stat),
            )
        )
    return candidates


def discover_migrations() -> list[MigrationFile]:
    """Retorna somente arquivos SQL regulares e inequívocos, por basename."""
    root = _migration_root()
    migrations = sorted(root.glob("*.sql"), key=lambda path: path.name)
    return _validate_catalog(migrations, root)


def resolve_selected_migration(
    selected_name: str | None, migrations: list[MigrationFile]
) -> MigrationFile:
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

    matches = [candidate for candidate in migrations if candidate.name == selected_name]
    if len(matches) != 1:
        raise MigrationSelectionError("a migration selecionada não existe ou é ambígua")
    return matches[0]


def _parse_migration_basename(value: str) -> str:
    """Recusa cedo formatos impossíveis, antes de ler o catálogo."""
    if (
        not isinstance(value, str)
        or value != value.strip()
        or "/" in value
        or "\\" in value
        or ":" in value
        or PurePosixPath(value).name != value
        or PureWindowsPath(value).name != value
        or not MIGRATION_BASENAME_RE.fullmatch(value)
    ):
        raise argparse.ArgumentTypeError("migration inválida")
    return value


def _parse_sha256(value: str) -> str:
    """Valida a forma do hash antes de descobrir ou ler migrations."""
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("SHA-256 inválido")
    return value


def _parse_confirmation(value: str) -> str:
    """Aceita somente a confirmação literal antes de qualquer efeito lateral."""
    if value != "APPLY":
        raise argparse.ArgumentTypeError("confirmação inválida")
    return value


def _open_catalog_file(candidate: MigrationFile) -> int:
    """Abre o arquivo por descriptor e recusa symlink/troca após o catálogo."""
    try:
        root_stat = candidate.root.lstat()
    except FileNotFoundError as exc:
        raise MigrationSelectionError("diretório de migrations mudou durante a validação") from exc
    if (
        stat.S_ISLNK(root_stat.st_mode)
        or not stat.S_ISDIR(root_stat.st_mode)
        or FileIdentity.from_stat(root_stat) != candidate.root_identity
    ):
        raise MigrationSelectionError("diretório de migrations mudou durante a validação")

    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    use_dir_fd = os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY")
    if use_dir_fd:
        root_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
        try:
            root_fd = os.open(os.fspath(candidate.root), root_flags)
        except OSError as exc:
            raise MigrationSelectionError("não foi possível abrir o diretório de migrations") from exc
        try:
            if FileIdentity.from_stat(os.fstat(root_fd)) != candidate.root_identity:
                raise MigrationSelectionError("diretório de migrations mudou durante a validação")
            return os.open(candidate.name, file_flags, dir_fd=root_fd)
        except OSError as exc:
            raise MigrationSelectionError("arquivo de migration mudou durante a validação") from exc
        finally:
            os.close(root_fd)

    try:
        candidate_stat = candidate.path.lstat()
        if (
            stat.S_ISLNK(candidate_stat.st_mode)
            or not stat.S_ISREG(candidate_stat.st_mode)
            or FileIdentity.from_stat(candidate_stat) != candidate.identity
        ):
            raise MigrationSelectionError("arquivo de migration mudou durante a validação")
        return os.open(os.fspath(candidate.path), file_flags)
    except OSError as exc:
        raise MigrationSelectionError("arquivo de migration mudou durante a validação") from exc


def _read_verified_migration(candidate: MigrationFile, expected_hash: str | None) -> str:
    if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
        raise MigrationSelectionError("--sha256 deve ter exatamente 64 caracteres hexadecimais")

    try:
        fd = _open_catalog_file(candidate)
    except MigrationSelectionError:
        raise
    try:
        initial_stat = os.fstat(fd)
        if (
            not stat.S_ISREG(initial_stat.st_mode)
            or FileIdentity.from_stat(initial_stat) != candidate.identity
        ):
            raise MigrationSelectionError("arquivo de migration mudou durante a validação")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        final_stat = os.fstat(fd)
        if FileIdentity.from_stat(final_stat) != candidate.identity:
            raise MigrationSelectionError("arquivo de migration mudou durante a validação")
        content = b"".join(chunks)
    except OSError as exc:
        raise MigrationSelectionError("não foi possível ler a migration selecionada") from exc
    finally:
        os.close(fd)

    actual_hash = hashlib.sha256(content).hexdigest()
    if actual_hash != expected_hash.lower():
        raise MigrationSelectionError("o SHA-256 informado não confere com a migration selecionada")

    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MigrationSelectionError("a migration selecionada não é UTF-8 válida") from exc


def _split_sql_statements(sql: str) -> list[SqlStatement]:
    """Divide SQL em statements ignorando comentários, strings e dollar quotes."""
    statements: list[SqlStatement] = []
    raw: list[str] = []
    normalized: list[str] = []
    index = 0
    quote: str | None = None
    dollar_tag: str | None = None
    block_depth = 0

    def emit() -> None:
        raw_statement = "".join(raw)
        normalized_statement = "".join(normalized)
        if normalized_statement.strip():
            statements.append(SqlStatement(raw_statement, normalized_statement))
        raw.clear()
        normalized.clear()

    while index < len(sql):
        char = sql[index]

        if block_depth:
            if sql.startswith("/*", index):
                raw.extend(("/", "*"))
                normalized.extend((" ", " "))
                block_depth += 1
                index += 2
            elif sql.startswith("*/", index):
                raw.extend(("*", "/"))
                normalized.extend((" ", " "))
                block_depth -= 1
                index += 2
            else:
                raw.append(char)
                normalized.append("\n" if char == "\n" else " ")
                index += 1
            continue

        if dollar_tag is not None:
            if sql.startswith(dollar_tag, index):
                raw.append(dollar_tag)
                normalized.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
            else:
                raw.append(char)
                normalized.append(char)
                index += 1
            continue

        if quote is not None:
            raw.append(char)
            normalized.append(char)
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    raw.append(sql[index + 1])
                    normalized.append(sql[index + 1])
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if sql.startswith("--", index):
            while index < len(sql) and sql[index] != "\n":
                raw.append(sql[index])
                normalized.append(" ")
                index += 1
            continue
        if sql.startswith("/*", index):
            raw.extend(("/", "*"))
            normalized.extend((" ", " "))
            block_depth = 1
            index += 2
            continue
        if char in ("'", '"'):
            quote = char
            raw.append(char)
            normalized.append(char)
            index += 1
            continue
        if char == "$":
            match = DOLLAR_QUOTE_START_RE.match(sql, index)
            if match is not None:
                dollar_tag = match.group(0)
                raw.append(dollar_tag)
                normalized.append(dollar_tag)
                index = match.end()
                continue
        if char == ";":
            emit()
            index += 1
            continue

        raw.append(char)
        normalized.append(char)
        index += 1

    emit()
    return statements


def _compact_sql(statement: SqlStatement) -> str:
    return " ".join(statement.normalized.split())


def prepare_transactional_sql(sql: str) -> str:
    """Aceita apenas o wrapper externo conhecido; qualquer outro controle aborta.

    O executor mantém uma única transação que engloba migration e ledger. O
    scanner ignora strings, comentários e dollar quotes para não confundir uma
    palavra literal com um comando, mas não tenta reinterpretar SQL arbitrário.
    """
    statements = _split_sql_statements(sql)
    controls = [
        (index, _compact_sql(statement))
        for index, statement in enumerate(statements)
        if TRANSACTION_CONTROL_RE.match(_compact_sql(statement))
    ]
    if not controls:
        return sql

    safe_wrapper = (
        len(controls) in (2, 3)
        and controls[0][0] == 0
        and controls[-1][0] == len(statements) - 1
        and SAFE_BEGIN_RE.fullmatch(controls[0][1])
        and SAFE_COMMIT_RE.fullmatch(controls[-1][1])
        and (
            len(controls) == 2
            or (
                controls[1][0] == 1
                and SAFE_SERIALIZABLE_RE.fullmatch(controls[1][1])
            )
        )
    )
    if safe_wrapper:
        body_start = 2 if len(controls) == 3 else 1
        body = statements[body_start:-1]
        if body:
            return ";\n".join(statement.raw.strip() for statement in body) + ";\n"

    raise MigrationSelectionError(
        "a migration contém controle transacional não suportado pelo executor atômico"
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


def _role_has_ledger_privilege(
    cur,
    role_oid: int,
    relation_oid: int,
    columns: tuple[str, ...],
    table_privileges: tuple[str, ...],
) -> bool:
    for privilege in table_privileges:
        cur.execute(
            "select has_table_privilege(%s, %s, %s)",
            (role_oid, relation_oid, privilege),
        )
        if cur.fetchone()[0]:
            return True
    for column in columns:
        for privilege in COLUMN_PRIVILEGES:
            cur.execute(
                "select has_column_privilege(%s, %s, %s, %s)",
                (role_oid, relation_oid, column, privilege),
            )
            if cur.fetchone()[0]:
                return True
    return False


def _validate_reachable_ledger_roles(
    cur,
    principal: str,
    relation_oid: int,
    relation_owner_oid: int,
    columns: tuple[str, ...],
    table_privileges: tuple[str, ...],
) -> None:
    """Recusa acesso presente ou potencial por INHERIT, SET ou ADMIN OPTION."""
    cur.execute(
        """
        with recursive admin_set_reachable(role_oid) as (
            select r.oid
            from pg_catalog.pg_roles r
            where r.rolname = %s

            union

            select membership.roleid
            from admin_set_reachable
            join pg_catalog.pg_auth_members membership
              on membership.member = admin_set_reachable.role_oid
            where membership.set_option or membership.admin_option
        )
        select r.oid,
               r.rolname,
               r.rolsuper,
               r.rolbypassrls,
               r.rolcreaterole
        from admin_set_reachable
        join pg_catalog.pg_roles r on r.oid = admin_set_reachable.role_oid
        """,
        (principal,),
    )
    for (
        role_oid,
        _role_name,
        role_superuser,
        role_bypass_rls,
        role_create_role,
    ) in cur.fetchall():
        if (
            role_superuser
            or role_bypass_rls
            or role_create_role
            or role_oid == relation_owner_oid
            or _role_has_ledger_privilege(
                cur,
                int(role_oid),
                relation_oid,
                columns,
                table_privileges,
            )
        ):
            raise MigrationRunnerError(
                "ledger possui caminho de membership ou privilégio efetivo para papel público; "
                "abra o gate separado de hardening"
            )


def _validate_ledger_security(cur, relation_oid: int, columns: tuple[str, ...], rls_enabled: bool) -> None:
    if not rls_enabled:
        raise MigrationRunnerError(
            "ledger não tem RLS habilitado; abra o gate separado de hardening"
        )

    cur.execute(
        """
        select oid, rolname, rolsuper, rolbypassrls, rolcreaterole
        from pg_catalog.pg_roles
        where rolname = any(%s)
        """,
        (list(REQUIRED_LEDGER_ROLES),),
    )
    roles = {
        name: {
            "oid": int(role_oid),
            "superuser": bool(superuser),
            "bypass_rls": bool(bypass_rls),
            "create_role": bool(create_role),
        }
        for role_oid, name, superuser, bypass_rls, create_role in cur.fetchall()
    }
    if set(roles) != set(REQUIRED_LEDGER_ROLES):
        raise MigrationRunnerError(
            "roles esperados do ledger estão ausentes; abra o gate separado de hardening"
        )
    if (
        roles["anon"]["superuser"]
        or roles["anon"]["bypass_rls"]
        or roles["anon"]["create_role"]
        or roles["authenticated"]["superuser"]
        or roles["authenticated"]["bypass_rls"]
        or roles["authenticated"]["create_role"]
        or not roles["service_role"]["bypass_rls"]
    ):
        raise MigrationRunnerError(
            "roles do ledger não atendem ao contrato de segurança; abra o gate separado de hardening"
        )

    cur.execute("show server_version_num")
    server_version = int(cur.fetchone()[0])
    if server_version < 160000:
        raise MigrationRunnerError(
            "PostgreSQL 16+ é necessário para validar memberships do ledger"
        )
    cur.execute("select relowner from pg_catalog.pg_class where oid = %s", (relation_oid,))
    relation_owner = cur.fetchone()
    if relation_owner is None:
        raise MigrationRunnerError("ledger ausente durante a validação de segurança")
    table_privileges = _table_privileges(server_version)
    for role in ("anon", "authenticated"):
        _validate_reachable_ledger_roles(
            cur,
            role,
            relation_oid,
            int(relation_owner[0]),
            columns,
            table_privileges,
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
            f"ERRO: injete {DATABASE_URL_ENV} no ambiente do processo.",
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

    url = resolve_database_url(args)
    if not url:
        print(
            f"ERRO: injete {DATABASE_URL_ENV} no ambiente do processo.",
            file=sys.stderr,
        )
        return 2

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
    parser = SanitizedArgumentParser(
        prog="apply_migrations.py",
        allow_abbrev=False,
        description=(
            "Executor fail-closed de uma migration aprovada. Não cria ledger e "
            "não aplica pendências automaticamente."
        )
    )
    sub = parser.add_subparsers(
        dest="command", required=True, parser_class=SanitizedArgumentParser
    )

    sub.add_parser(
        "list", help="lista arquivos versionados; não conecta", allow_abbrev=False
    )

    p_status = sub.add_parser(
        "status",
        help="preflight genérico read-only; falha se houver drift",
        allow_abbrev=False,
    )
    p_apply = sub.add_parser(
        "apply",
        help="aplica somente um arquivo com nome, hash e confirmação",
        allow_abbrev=False,
    )
    p_apply.add_argument(
        "--migration",
        default=None,
        type=_parse_migration_basename,
        help="basename exato do arquivo SQL",
    )
    p_apply.add_argument(
        "--sha256",
        default=None,
        type=_parse_sha256,
        help="SHA-256 exato do arquivo",
    )
    p_apply.add_argument(
        "--confirm",
        default=None,
        type=_parse_confirmation,
        help="confirmação explícita; use exatamente APPLY",
    )
    return parser


def main(argv: list[str]) -> int:
    try:
        args = build_parser().parse_args(argv[1:])
    except CliUsageError:
        print(USAGE_ERROR_MESSAGE, file=sys.stderr)
        return 2
    handlers = {"list": cmd_list, "status": cmd_status, "apply": cmd_apply}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
