#!/usr/bin/env python3
"""Executor fail-closed para uma migration SQL explicitamente aprovada.

O histórico local e o ledger ``public.schema_migrations`` podem divergir. Por
isso este módulo nunca reconcilia o histórico ou aplica automaticamente uma
lista de pendências. Escrita de migration requer, sempre, o basename
versionado, o SHA-256 esperado e ``--confirm APPLY``:

    python scripts/apply_migrations.py apply \
      --migration 20260810_031050_explicit_deny_policies_for_closed_tables.sql \
      --sha256 <sha256-exato> \
      --confirm APPLY

O destino é injetado exclusivamente pela variável de ambiente
``M06_MIGRATION_DATABASE_URL``; a CLI não aceita DSN em argv nem a exibe.

``status`` continua exclusivamente read-only, mas falha fechado quando a
situação genérica do ledger não pode ser demonstrada como segura. Não há modo
genérico de ``apply``.

``harden-ledger`` é uma operação de controle excepcional e igualmente
explícita: ela endurece somente o ledger já existente, sem criar, reconciliar
ou registrar migrations. Ela é necessária quando um ledger histórico válido em
estrutura ainda não tem RLS/ACLs compatíveis com o executor de arquivo único.

``bootstrap-ledger`` é a única criação permitida. Ela cria atomicamente um
ledger vazio no contrato final owner-only, sem consultar ou copiar qualquer
histórico externo. O ledger vazio não autoriza aplicação: ``status`` e
``apply`` continuam bloqueados até o histórico ser um prefixo íntegro do
catálogo com, no máximo, uma migration pendente.
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
    ("name", "text", True, None),
    ("applied_at", "timestamp with time zone", True, "now()"),
)
REQUIRED_LEDGER_ROLES = ("anon", "authenticated", "service_role")
OPTIONAL_LEDGER_ROLES = ("agent_runtime",)
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
LEDGER_HARDEN_CONFIRMATION = "HARDEN_LEDGER"
LEDGER_BOOTSTRAP_CONFIRMATION = "BOOTSTRAP_LEDGER"
LEDGER_DENY_POLICY_NAME = "migration_ledger_service_role_bypass_only"
LEDGER_BOOTSTRAP_LOCK_KEYS = (20260828, 32117)
LEDGER_LOCK_TIMEOUT = "5s"
LEDGER_STATEMENT_TIMEOUT = "30s"
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
    applied_at_values: tuple[object, ...] = ()


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


def _parse_hardening_confirmation(value: str) -> str:
    """Aceita a confirmação própria do único hardening permitido."""
    if value != LEDGER_HARDEN_CONFIRMATION:
        raise argparse.ArgumentTypeError("confirmação inválida")
    return value


def _parse_bootstrap_confirmation(value: str) -> str:
    """Aceita somente a confirmação própria da criação do ledger vazio."""
    if value != LEDGER_BOOTSTRAP_CONFIRMATION:
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
               a.attnotnull,
               pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
        from pg_catalog.pg_attribute a
        left join pg_catalog.pg_attrdef default_value
          on default_value.adrelid = a.attrelid
         and default_value.adnum = a.attnum
        where a.attrelid = %s
          and a.attnum > 0
          and not a.attisdropped
        order by a.attnum
        """,
        (relation_oid,),
    )
    columns = tuple(
        (name, data_type, bool(not_null), default)
        for name, data_type, not_null, default in cur.fetchall()
    )
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


def _read_ledger_applied_rows(cur) -> tuple[tuple[str, object], ...]:
    cur.execute(
        f"select name, applied_at from {BOOKKEEPING_TABLE} "
        "order by applied_at, name"
    )
    return tuple((str(name), applied_at) for name, applied_at in cur.fetchall())


def _validate_ledger_catalog_entries(
    cur, catalog_names: tuple[str, ...]
) -> tuple[str, ...]:
    applied_names = tuple(name for name, _applied_at in _read_ledger_applied_rows(cur))
    unknown = sorted(set(applied_names) - set(catalog_names))
    if unknown:
        raise MigrationRunnerError(
            "ledger contém migration desconhecida; abra o gate separado de reconciliação"
        )
    return applied_names


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


def _snapshot_ledger_role_privileges(
    cur,
    role_name: str,
    relation_oid: int,
    columns: tuple[str, ...],
    table_privileges: tuple[str, ...],
) -> dict[str, bool]:
    """Captura privilégios efetivos para provar que o hardening não os reduz."""
    snapshot: dict[str, bool] = {}
    for privilege in table_privileges:
        cur.execute(
            "select has_table_privilege(%s, %s, %s)",
            (role_name, relation_oid, privilege),
        )
        snapshot[f"table:{privilege}"] = bool(cur.fetchone()[0])
    for column in columns:
        for privilege in COLUMN_PRIVILEGES:
            cur.execute(
                "select has_column_privilege(%s, %s, %s, %s)",
                (role_name, relation_oid, column, privilege),
            )
            snapshot[f"column:{column}:{privilege}"] = bool(cur.fetchone()[0])
    return snapshot


def _ledger_deny_policy_state(cur, relation_oid: int) -> tuple[int, int]:
    """Conta policies e a única policy deny permitida para o ledger."""
    cur.execute(
        """
        select count(*),
               count(*) filter (
                   where p.polname = %s
                     and p.polcmd = '*'
                     and p.polpermissive is false
                     and p.polroles = array[0::oid]
                     and pg_catalog.pg_get_expr(p.polqual, p.polrelid) = 'false'
                     and pg_catalog.pg_get_expr(p.polwithcheck, p.polrelid) = 'false'
               )
        from pg_catalog.pg_policy p
        where p.polrelid = %s
        """,
        (LEDGER_DENY_POLICY_NAME, relation_oid),
    )
    policy_count, exact_count = cur.fetchone()
    return int(policy_count), int(exact_count)


def _validate_ledger_hardening_baseline(
    cur, relation_oid: int, rls_enabled: bool
) -> None:
    """Aceita apenas o estado histórico inseguro ou o estado final idempotente."""
    policy_count, exact_count = _ledger_deny_policy_state(cur, relation_oid)
    if not rls_enabled and policy_count == 0:
        return
    if rls_enabled and policy_count == 1 and exact_count == 1:
        return
    raise MigrationRunnerError(
        "ledger possui estado de RLS ou policy inesperado; abra o gate separado de hardening"
    )


def _ensure_ledger_deny_policy(cur, relation_oid: int) -> None:
    policy_count, exact_count = _ledger_deny_policy_state(cur, relation_oid)
    if policy_count == 0:
        cur.execute(
            f"create policy {LEDGER_DENY_POLICY_NAME} on {BOOKKEEPING_TABLE} "
            "as restrictive for all to public using (false) with check (false)"
        )
        return
    if policy_count != 1 or exact_count != 1:
        raise MigrationRunnerError(
            "ledger possui policy inesperada; a transação foi revertida"
        )


def _validate_required_ledger_roles(cur) -> None:
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


def _server_version_number(cur) -> int:
    cur.execute("show server_version_num")
    return int(cur.fetchone()[0])


def _bootstrap_executor_and_schema(cur) -> tuple[int, int]:
    """Valida o executor e os defaults que afetariam uma tabela nova."""
    server_version = _server_version_number(cur)
    if not 170000 <= server_version < 180000:
        raise MigrationRunnerError(
            "bootstrap do ledger exige PostgreSQL 17 validado pelo projeto"
        )

    _validate_required_ledger_roles(cur)
    cur.execute(
        """
        select executor.oid, namespace.oid,
               pg_catalog.has_schema_privilege(
                   executor.oid, namespace.oid, 'USAGE'
               ),
               pg_catalog.has_schema_privilege(
                   executor.oid, namespace.oid, 'CREATE'
               ),
               executor.rolname,
               current_user = session_user
        from pg_catalog.pg_roles executor
        cross join pg_catalog.pg_namespace namespace
        where executor.rolname = current_user
          and namespace.nspname = %s
        """,
        (LEDGER_SCHEMA,),
    )
    row = cur.fetchone()
    if row is None:
        raise MigrationRunnerError(
            "executor ou schema public ausente; bootstrap do ledger bloqueado"
        )
    (
        executor_oid,
        namespace_oid,
        has_usage,
        has_create,
        executor_name,
        stable_identity,
    ) = row
    if not stable_identity:
        raise MigrationRunnerError(
            "current_user e session_user divergem; bootstrap do ledger bloqueado"
        )
    if executor_name in REQUIRED_LEDGER_ROLES:
        raise MigrationRunnerError(
            "executor não pode ser papel público ou service_role no bootstrap"
        )
    if not has_usage or not has_create:
        raise MigrationRunnerError(
            "executor não possui privilégios mínimos no schema public"
        )

    cur.execute(
        """
        select 1
        from pg_catalog.pg_namespace namespace
        cross join lateral pg_catalog.aclexplode(
            coalesce(
                namespace.nspacl,
                pg_catalog.acldefault('n', namespace.nspowner)
            )
        ) expanded
        where namespace.oid = %s
          and expanded.grantee = 0
          and expanded.privilege_type = 'CREATE'
        limit 1
        """,
        (namespace_oid,),
    )
    if cur.fetchone() is not None:
        raise MigrationRunnerError(
            "PUBLIC possui CREATE no schema public; bootstrap do ledger bloqueado"
        )

    for role_name in _protected_ledger_roles(cur):
        cur.execute(
            "select pg_catalog.has_schema_privilege(%s, %s, 'CREATE')",
            (role_name, namespace_oid),
        )
        if cur.fetchone()[0]:
            raise MigrationRunnerError(
                "papel da aplicação possui CREATE no schema public; "
                "bootstrap do ledger bloqueado"
            )

    cur.execute(
        """
        select 1
        from pg_catalog.pg_default_acl defaults
        cross join lateral pg_catalog.aclexplode(defaults.defaclacl) expanded
        where defaults.defaclrole = %s
          and defaults.defaclobjtype = 'r'
          and defaults.defaclnamespace in (0, %s)
          and expanded.grantee <> %s
        limit 1
        """,
        (executor_oid, namespace_oid, executor_oid),
    )
    if cur.fetchone() is not None:
        raise MigrationRunnerError(
            "default privileges de tabelas concedem acesso fora do owner; "
            "bootstrap do ledger bloqueado"
        )
    return int(executor_oid), int(namespace_oid)


def _protected_ledger_roles(cur) -> tuple[str, ...]:
    """Inclui agent_runtime somente quando o papel opcional existe."""
    cur.execute(
        "select rolname from pg_catalog.pg_roles where rolname = any(%s)",
        (list(OPTIONAL_LEDGER_ROLES),),
    )
    optional = tuple(sorted(str(row[0]) for row in cur.fetchall()))
    return (*REQUIRED_LEDGER_ROLES, *optional)


def _named_ledger_relation(cur) -> int | None:
    """Resolve qualquer objeto relacional homônimo sem aceitar relkind por engano."""
    cur.execute(
        """
        select c.oid
        from pg_catalog.pg_class c
        join pg_catalog.pg_namespace n on n.oid = c.relnamespace
        where n.nspname = %s
          and c.relname = %s
        """,
        (LEDGER_SCHEMA, LEDGER_NAME),
    )
    rows = cur.fetchall()
    if len(rows) > 1:
        raise MigrationRunnerError(
            "há objetos homônimos inesperados; bootstrap do ledger bloqueado"
        )
    return int(rows[0][0]) if rows else None


def _validate_no_standalone_ledger_type(cur, relation_oid: int | None) -> None:
    """Recusa enum/domínio/composite solto que impediria CREATE TABLE seguro."""
    cur.execute(
        """
        select t.typtype, t.typrelid
        from pg_catalog.pg_type t
        join pg_catalog.pg_namespace n on n.oid = t.typnamespace
        where n.nspname = %s
          and t.typname = %s
        """,
        (LEDGER_SCHEMA, LEDGER_NAME),
    )
    rows = tuple((str(kind), int(type_relation)) for kind, type_relation in cur.fetchall())
    expected = () if relation_oid is None else (("c", relation_oid),)
    if rows != expected:
        raise MigrationRunnerError(
            "há tipo homônimo ou metadata relacional divergente; "
            "bootstrap do ledger bloqueado"
        )


def _validate_ledger_physical_shape(
    cur, relation_oid: int, executor_oid: int, *, require_empty: bool = True
) -> tuple[str, ...]:
    """Exige a forma física mínima e exata do ledger criado pelo bootstrap."""
    cur.execute(
        """
        select c.relkind, c.relpersistence, c.relrowsecurity,
               c.relforcerowsecurity, c.relowner, c.reloptions,
               c.relreplident, access_method.amname
        from pg_catalog.pg_class c
        left join pg_catalog.pg_am access_method on access_method.oid = c.relam
        where c.oid = %s
        """,
        (relation_oid,),
    )
    row = cur.fetchone()
    if row is None:
        raise MigrationRunnerError("ledger desapareceu durante o bootstrap")
    (
        relation_kind,
        persistence,
        rls_enabled,
        force_rls,
        owner_oid,
        relation_options,
        replica_identity,
        access_method,
    ) = row
    if (
        relation_kind != "r"
        or persistence != "p"
        or not rls_enabled
        or force_rls
        or int(owner_oid) != executor_oid
        or relation_options is not None
        or replica_identity != "d"
        or access_method != "heap"
    ):
        raise MigrationRunnerError(
            "objeto homônimo ou contrato físico do ledger é incompatível"
        )

    columns = _validate_ledger_schema(cur, relation_oid)
    cur.execute(
        """
        select con.contype, con.convalidated, con.condeferrable, con.condeferred,
               array(
                   select attribute.attname
                   from unnest(con.conkey) with ordinality key(attnum, position)
                   join pg_catalog.pg_attribute attribute
                     on attribute.attrelid = con.conrelid
                    and attribute.attnum = key.attnum
                   order by key.position
               )
        from pg_catalog.pg_constraint con
        where con.conrelid = %s
        order by con.oid
        """,
        (relation_oid,),
    )
    constraints = tuple(
        (
            str(kind),
            bool(validated),
            bool(deferrable),
            bool(deferred),
            tuple(keys),
        )
        for kind, validated, deferrable, deferred, keys in cur.fetchall()
    )
    if constraints != (("p", True, False, False, ("name",)),):
        raise MigrationRunnerError("constraints do ledger divergem do contrato exato")

    cur.execute(
        """
        select index.indisprimary, index.indisunique, index.indisvalid,
               index.indisready, index.indislive, index.indisexclusion,
               index.indimmediate, index.indpred is null,
               index.indexprs is null, index.indnkeyatts, index.indnatts,
               access_method.amname,
               array(
                   select attribute.attname
                   from unnest(index.indkey) with ordinality key(attnum, position)
                   join pg_catalog.pg_attribute attribute
                     on attribute.attrelid = index.indrelid
                    and attribute.attnum = key.attnum
                   order by key.position
               ),
               array(
                   select operator_class.opcname
                   from unnest(index.indclass::oid[]) with ordinality
                        classes(opclass_oid, position)
                   join pg_catalog.pg_opclass operator_class
                     on operator_class.oid = classes.opclass_oid
                   order by classes.position
               ),
               array(
                   select collation_entry.collname
                   from unnest(index.indcollation::oid[]) with ordinality
                        collations(collation_oid, position)
                   join pg_catalog.pg_collation collation_entry
                     on collation_entry.oid = collations.collation_oid
                   order by collations.position
               ),
               index.indoption::smallint[]
        from pg_catalog.pg_index index
        join pg_catalog.pg_class index_relation
          on index_relation.oid = index.indexrelid
        join pg_catalog.pg_am access_method
          on access_method.oid = index_relation.relam
        where index.indrelid = %s
        order by index.indexrelid
        """,
        (relation_oid,),
    )
    indexes = tuple(cur.fetchall())
    if len(indexes) != 1:
        raise MigrationRunnerError("índices do ledger divergem do contrato exato")
    index = indexes[0]
    if (
        tuple(bool(value) for value in index[:9])
        != (True, True, True, True, True, False, True, True, True)
        or int(index[9]) != 1
        or int(index[10]) != 1
        or str(index[11]) != "btree"
        or tuple(index[12]) != ("name",)
        or tuple(index[13]) != ("text_ops",)
        or tuple(index[14]) != ("default",)
        or tuple(index[15]) != (0,)
    ):
        raise MigrationRunnerError("índice primário do ledger diverge do contrato exato")

    cur.execute(
        """
        select
          (select count(*) from pg_catalog.pg_trigger
           where tgrelid = %s and not tgisinternal),
          (select count(*) from pg_catalog.pg_rewrite
           where ev_class = %s),
          (select count(*) from pg_catalog.pg_inherits
           where inhrelid = %s or inhparent = %s)
        """,
        (relation_oid, relation_oid, relation_oid, relation_oid),
    )
    if tuple(int(value) for value in cur.fetchone()) != (0, 0, 0):
        raise MigrationRunnerError(
            "ledger contém trigger, rule, herança ou partição inesperada"
        )

    if require_empty:
        cur.execute(f"select count(*) from {BOOKKEEPING_TABLE}")
        if int(cur.fetchone()[0]) != 0:
            raise MigrationRunnerError(
                "bootstrap aceita somente o ledger vazio; reconciliação é outro gate"
            )
    return columns


def _validate_ledger_no_user_trigger_or_rule(cur, relation_oid: int) -> None:
    cur.execute(
        """
        select
          (select count(*) from pg_catalog.pg_trigger
           where tgrelid = %s and not tgisinternal),
          (select count(*) from pg_catalog.pg_rewrite
           where ev_class = %s)
        """,
        (relation_oid, relation_oid),
    )
    if tuple(int(value) for value in cur.fetchone()) != (0, 0):
        raise MigrationRunnerError("ledger contém trigger ou rule inesperada")


def _validate_bootstrap_owner_only_acl(
    cur, relation_oid: int, executor_oid: int, columns: tuple[str, ...]
) -> None:
    """Prova ACL direta owner-only e nenhum acesso efetivo público/server-side."""
    server_version = _server_version_number(cur)
    cur.execute(
        """
        select expanded.grantor, expanded.grantee,
               expanded.privilege_type, expanded.is_grantable
        from pg_catalog.pg_class relation
        cross join lateral pg_catalog.aclexplode(
            coalesce(
                relation.relacl,
                pg_catalog.acldefault('r', relation.relowner)
            )
        ) expanded
        where relation.oid = %s
        order by expanded.grantee, expanded.privilege_type
        """,
        (relation_oid,),
    )
    actual_acl = {
        (int(grantor), int(grantee), str(privilege).upper(), bool(grantable))
        for grantor, grantee, privilege, grantable in cur.fetchall()
    }
    expected_acl = {
        (executor_oid, executor_oid, privilege, False)
        for privilege in _table_privileges(server_version)
    }
    if actual_acl != expected_acl:
        raise MigrationRunnerError("ACL do ledger não é estritamente owner-only")

    cur.execute(
        """
        select 1
        from pg_catalog.pg_attribute attribute
        cross join lateral pg_catalog.aclexplode(attribute.attacl) expanded
        where attribute.attrelid = %s
          and attribute.attnum > 0
          and not attribute.attisdropped
        limit 1
        """,
        (relation_oid,),
    )
    if cur.fetchone() is not None:
        raise MigrationRunnerError("ACL de coluna do ledger não é owner-only")

    table_privileges = _table_privileges(server_version)
    for role_name in _protected_ledger_roles(cur):
        effective = _snapshot_ledger_role_privileges(
            cur,
            role_name,
            relation_oid,
            columns,
            table_privileges,
        )
        if any(effective.values()):
            raise MigrationRunnerError(
                "papel público ou service_role mantém privilégio efetivo no ledger"
            )

        cur.execute(
            """
            with recursive reachable(role_oid) as (
                select oid
                from pg_catalog.pg_roles
                where rolname = %s

                union

                select membership.roleid
                from reachable
                join pg_catalog.pg_auth_members membership
                  on membership.member = reachable.role_oid
                where membership.inherit_option
                   or membership.set_option
                   or membership.admin_option
            )
            select 1 from reachable where role_oid = %s limit 1
            """,
            (role_name, executor_oid),
        )
        if cur.fetchone() is not None:
            raise MigrationRunnerError(
                "papel público ou service_role alcança o owner por membership"
            )


def _validate_bootstrap_final_contract(
    cur, relation_oid: int, executor_oid: int
) -> None:
    columns = _validate_ledger_physical_shape(cur, relation_oid, executor_oid)
    if _ledger_deny_policy_state(cur, relation_oid) != (1, 1):
        raise MigrationRunnerError("policy deny do ledger diverge do contrato exato")
    _validate_ledger_no_user_trigger_or_rule(cur, relation_oid)
    _validate_bootstrap_owner_only_acl(cur, relation_oid, executor_oid, columns)
    _validate_ledger_security(cur, relation_oid, columns, rls_enabled=True)


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

    _validate_required_ledger_roles(cur)

    server_version = _server_version_number(cur)
    if server_version < 160000:
        raise MigrationRunnerError(
            "PostgreSQL 16+ é necessário para validar memberships do ledger"
        )
    cur.execute("select relowner from pg_catalog.pg_class where oid = %s", (relation_oid,))
    relation_owner = cur.fetchone()
    if relation_owner is None:
        raise MigrationRunnerError("ledger ausente durante a validação de segurança")
    table_privileges = _table_privileges(server_version)
    optional_roles = tuple(
        role for role in _protected_ledger_roles(cur) if role in OPTIONAL_LEDGER_ROLES
    )
    for role in ("anon", "authenticated", *optional_roles):
        _validate_reachable_ledger_roles(
            cur,
            role,
            relation_oid,
            int(relation_owner[0]),
            columns,
            table_privileges,
        )


def _validate_ledger_executor_owner(cur, relation_oid: int) -> int:
    cur.execute(
        """
        select current_user = session_user,
               relation.relowner = executor.oid,
               not relation.relforcerowsecurity,
               executor.oid
        from pg_catalog.pg_class relation
        join pg_catalog.pg_roles executor on executor.rolname = current_user
        where relation.oid = %s
        """,
        (relation_oid,),
    )
    row = cur.fetchone()
    if row is None or not all(bool(value) for value in row[:3]):
        raise MigrationRunnerError(
            "executor, owner ou modo FORCE RLS diverge do contrato do ledger"
        )
    return int(row[3])


def _validate_general_ledger_acl(cur, relation_oid: int) -> None:
    """No legado, somente owner e service_role podem constar na ACL direta."""
    cur.execute(
        """
        select relation.relowner, service.oid
        from pg_catalog.pg_class relation
        join pg_catalog.pg_roles service on service.rolname = 'service_role'
        where relation.oid = %s
        """,
        (relation_oid,),
    )
    row = cur.fetchone()
    if row is None:
        raise MigrationRunnerError("ledger ausente durante validação de ACL")
    allowed_grantees = {int(row[0]), int(row[1])}
    cur.execute(
        """
        select expanded.grantee
        from pg_catalog.pg_class relation
        cross join lateral pg_catalog.aclexplode(
            coalesce(
                relation.relacl,
                pg_catalog.acldefault('r', relation.relowner)
            )
        ) expanded
        where relation.oid = %s

        union all

        select expanded.grantee
        from pg_catalog.pg_attribute attribute
        cross join lateral pg_catalog.aclexplode(attribute.attacl) expanded
        where attribute.attrelid = %s
          and attribute.attnum > 0
          and not attribute.attisdropped
        """,
        (relation_oid, relation_oid),
    )
    if any(int(grantee) not in allowed_grantees for (grantee,) in cur.fetchall()):
        raise MigrationRunnerError("ACL do ledger concede acesso a papel inesperado")


def inspect_ledger(cur, catalog_names: tuple[str, ...]) -> LedgerState:
    """Valida estrutura e segurança do ledger sem criar ou alterar nada."""
    relation_oid, rls_enabled = _ledger_relation(cur)
    executor_oid = _validate_ledger_executor_owner(cur, relation_oid)
    columns = _validate_ledger_physical_shape(
        cur, relation_oid, executor_oid, require_empty=False
    )
    _validate_general_ledger_acl(cur, relation_oid)
    _validate_ledger_security(cur, relation_oid, columns, rls_enabled)
    if _ledger_deny_policy_state(cur, relation_oid) != (1, 1):
        raise MigrationRunnerError(
            "policy deny do ledger diverge do contrato seguro"
        )
    _validate_ledger_no_user_trigger_or_rule(cur, relation_oid)

    applied_rows = _read_ledger_applied_rows(cur)
    applied_names = tuple(name for name, _applied_at in applied_rows)
    unknown = sorted(set(applied_names) - set(catalog_names))
    if unknown:
        raise MigrationRunnerError(
            "ledger contém migration desconhecida; abra o gate separado de reconciliação"
        )
    if not applied_names:
        raise MigrationRunnerError(
            "ledger vazio não comprova histórico; reconciliação humana está bloqueada"
        )

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

    return LedgerState(
        relation_oid=relation_oid,
        applied_names=applied_names,
        applied_at_values=tuple(applied_at for _name, applied_at in applied_rows),
    )


def _inspect_ledger_fail_closed(
    cur, catalog_names: tuple[str, ...]
) -> LedgerState:
    """Converte erro inesperado de catálogo em recusa segura, sem detalhes."""
    try:
        return inspect_ledger(cur, catalog_names)
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
            cur.execute(
                "set transaction isolation level repeatable read read only"
            )
            cur.execute("set local search_path = pg_catalog")
            cur.execute(
                "select pg_catalog.set_config('lock_timeout', %s, true)",
                (LEDGER_LOCK_TIMEOUT,),
            )
            cur.execute(
                "select pg_catalog.set_config('statement_timeout', %s, true)",
                (LEDGER_STATEMENT_TIMEOUT,),
            )
            state = _inspect_ledger_fail_closed(cur, catalog_names)
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


def cmd_harden_ledger(args: argparse.Namespace) -> int:
    """Endurece somente o ledger histórico existente, em transação atômica.

    Esta não é uma aplicação de migration e não altera os nomes já registrados.
    O único estado inicial aceito é o ledger estruturalmente válido sem RLS e
    sem policies, ou o estado final já endurecido. Qualquer drift faz rollback.
    """
    if getattr(args, "confirm", None) != LEDGER_HARDEN_CONFIRMATION:
        print(
            f"ERRO: hardening do ledger requer --confirm {LEDGER_HARDEN_CONFIRMATION}.",
            file=sys.stderr,
        )
        return 4

    try:
        migrations = discover_migrations()
    except MigrationRunnerError as error:
        return _print_abort(error)
    catalog_names = tuple(path.name for path in migrations)

    url = resolve_database_url(args)
    if not url:
        print(
            f"ERRO: injete {DATABASE_URL_ENV} no ambiente do processo.",
            file=sys.stderr,
        )
        return 2

    conn = _connect(url)
    try:
        with conn.cursor() as cur:
            # Deve ser a primeira instrução da transação para cobrir leitura,
            # lock, RLS, policy, ACL e a verificação pós-condição no mesmo commit.
            cur.execute("set transaction isolation level serializable")
            cur.execute("set local search_path = pg_catalog")
            cur.execute(
                "select pg_catalog.set_config('lock_timeout', %s, true)",
                (LEDGER_LOCK_TIMEOUT,),
            )
            cur.execute(
                "select pg_catalog.set_config('statement_timeout', %s, true)",
                (LEDGER_STATEMENT_TIMEOUT,),
            )
            _ledger_relation(cur)
            cur.execute(f"lock table {BOOKKEEPING_TABLE} in access exclusive mode")

            relation_oid, rls_enabled = _ledger_relation(cur)
            columns = _validate_ledger_schema(cur, relation_oid)
            _validate_ledger_catalog_entries(cur, catalog_names)
            _validate_required_ledger_roles(cur)
            _validate_ledger_hardening_baseline(cur, relation_oid, rls_enabled)

            server_version = _server_version_number(cur)
            service_role_before = _snapshot_ledger_role_privileges(
                cur,
                "service_role",
                relation_oid,
                columns,
                _table_privileges(server_version),
            )

            cur.execute(f"alter table {BOOKKEEPING_TABLE} enable row level security")
            _ensure_ledger_deny_policy(cur, relation_oid)
            if _ledger_deny_policy_state(cur, relation_oid) != (1, 1):
                raise MigrationRunnerError(
                    "policy deny do ledger não atingiu a pós-condição esperada; "
                    "a transação foi revertida"
                )
            cur.execute(
                f"revoke all privileges on table {BOOKKEEPING_TABLE} "
                "from public, anon, authenticated"
            )
            for column in columns:
                cur.execute(
                    f"revoke select ({column}), insert ({column}), update ({column}), "
                    f"references ({column}) on table {BOOKKEEPING_TABLE} "
                    "from public, anon, authenticated"
                )

            service_role_after = _snapshot_ledger_role_privileges(
                cur,
                "service_role",
                relation_oid,
                columns,
                _table_privileges(server_version),
            )
            if service_role_after != service_role_before:
                raise MigrationRunnerError(
                    "hardening reduziria privilégios efetivos de service_role; "
                    "abra o gate separado de hardening"
                )

            _validate_ledger_security(cur, relation_oid, columns, rls_enabled=True)
        conn.commit()
    except MigrationRunnerError as error:
        _rollback_quietly(conn)
        return _print_abort(error)
    except Exception:  # noqa: BLE001 - não expor SQL, DSN ou credenciais
        _rollback_quietly(conn)
        print(
            "ERRO: hardening do ledger falhou e a transação foi revertida.",
            file=sys.stderr,
        )
        return MigrationExecutionError.exit_code
    finally:
        conn.close()

    print(
        "OK — ledger existente endurecido com RLS, policy deny e ACLs verificadas. "
        "Nenhuma migration foi aplicada ou registrada."
    )
    return 0


def cmd_bootstrap_ledger(args: argparse.Namespace) -> int:
    """Cria somente o ledger vazio owner-only, sem reconciliar histórico."""
    if getattr(args, "confirm", None) != LEDGER_BOOTSTRAP_CONFIRMATION:
        print(
            "ERRO: bootstrap do ledger requer "
            f"--confirm {LEDGER_BOOTSTRAP_CONFIRMATION}.",
            file=sys.stderr,
        )
        return 4

    url = resolve_database_url(args)
    if not url:
        print(
            f"ERRO: injete {DATABASE_URL_ENV} no ambiente do processo.",
            file=sys.stderr,
        )
        return 2

    conn = _connect(url)
    already_bootstrapped = False
    try:
        with conn.cursor() as cur:
            cur.execute("set transaction isolation level serializable")
            cur.execute("set local search_path = pg_catalog")
            cur.execute(
                "select pg_catalog.set_config('lock_timeout', %s, true)",
                (LEDGER_LOCK_TIMEOUT,),
            )
            cur.execute(
                "select pg_catalog.set_config('statement_timeout', %s, true)",
                (LEDGER_STATEMENT_TIMEOUT,),
            )
            cur.execute(
                "select pg_catalog.pg_advisory_xact_lock(%s, %s)",
                LEDGER_BOOTSTRAP_LOCK_KEYS,
            )
            executor_oid, _namespace_oid = _bootstrap_executor_and_schema(cur)
            relation_oid = _named_ledger_relation(cur)
            _validate_no_standalone_ledger_type(cur, relation_oid)

            if relation_oid is not None:
                _validate_bootstrap_final_contract(cur, relation_oid, executor_oid)
                already_bootstrapped = True
            else:
                cur.execute(
                    f"""
                    create table {BOOKKEEPING_TABLE} (
                        name text not null,
                        applied_at timestamp with time zone not null
                            default pg_catalog.now(),
                        primary key (name)
                    )
                    """
                )
                relation_oid = _named_ledger_relation(cur)
                if relation_oid is None:
                    raise MigrationRunnerError(
                        "ledger não apareceu após a criação; transação revertida"
                    )
                _validate_no_standalone_ledger_type(cur, relation_oid)
                cur.execute(
                    f"alter table {BOOKKEEPING_TABLE} enable row level security"
                )
                _ensure_ledger_deny_policy(cur, relation_oid)
                cur.execute(
                    f"revoke all privileges on table {BOOKKEEPING_TABLE} "
                    "from public, anon, authenticated, service_role"
                )
                protected_roles = _protected_ledger_roles(cur)
                if "agent_runtime" in protected_roles:
                    cur.execute(
                        f"revoke all privileges on table {BOOKKEEPING_TABLE} "
                        "from agent_runtime"
                    )
                for column in ("name", "applied_at"):
                    cur.execute(
                        f"revoke select ({column}), insert ({column}), "
                        f"update ({column}), references ({column}) "
                        f"on table {BOOKKEEPING_TABLE} "
                        "from public, anon, authenticated, service_role"
                    )
                    if "agent_runtime" in protected_roles:
                        cur.execute(
                            f"revoke select ({column}), insert ({column}), "
                            f"update ({column}), references ({column}) "
                            f"on table {BOOKKEEPING_TABLE} from agent_runtime"
                        )
                _validate_bootstrap_final_contract(cur, relation_oid, executor_oid)

        if already_bootstrapped:
            _rollback_quietly(conn)
        else:
            conn.commit()
    except MigrationRunnerError as error:
        _rollback_quietly(conn)
        return _print_abort(error)
    except Exception:  # noqa: BLE001 - não expor SQL, DSN ou credenciais
        _rollback_quietly(conn)
        print(
            "ERRO: bootstrap do ledger falhou e a transação foi revertida.",
            file=sys.stderr,
        )
        return MigrationExecutionError.exit_code
    finally:
        conn.close()

    if already_bootstrapped:
        print(
            "Ledger vazio já atende ao contrato owner-only; nenhuma mutação foi feita."
        )
    else:
        print(
            "OK: ledger vazio criado atomicamente com RLS, policy deny e ACL "
            "owner-only. Nenhuma migration foi aplicada ou registrada."
        )
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
            cur.execute("set local search_path = pg_catalog")
            cur.execute(
                "select pg_catalog.set_config('lock_timeout', %s, true)",
                (LEDGER_LOCK_TIMEOUT,),
            )
            cur.execute(
                "select pg_catalog.set_config('statement_timeout', %s, true)",
                (LEDGER_STATEMENT_TIMEOUT,),
            )
            # Confirma existência antes de LOCK TABLE; nenhum caminho cria o
            # ledger. Reinspecionamos depois do lock para fechar TOCTOU.
            try:
                _ledger_relation(cur)
                cur.execute(
                    f"lock table {BOOKKEEPING_TABLE} in share row exclusive mode"
                )
                state = _inspect_ledger_fail_closed(cur, catalog_names)
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
            cur.execute("set local search_path = pg_catalog")
            cur.execute(
                "select pg_catalog.set_config('lock_timeout', %s, true)",
                (LEDGER_LOCK_TIMEOUT,),
            )
            cur.execute(
                "select pg_catalog.set_config('statement_timeout', %s, true)",
                (LEDGER_STATEMENT_TIMEOUT,),
            )
            state_before_insert = _inspect_ledger_fail_closed(cur, catalog_names)
            if state_before_insert != state:
                raise MigrationRunnerError(
                    "migration alterou o ledger antes do registro autorizado"
                )
            cur.execute(
                f"insert into {BOOKKEEPING_TABLE}(name) values (%s) returning name",
                (selected.name,),
            )
            returned = tuple(str(row[0]) for row in cur.fetchall())
            if returned != (selected.name,):
                raise MigrationRunnerError(
                    "insert no ledger não retornou exatamente a migration selecionada"
                )
            final_state = _inspect_ledger_fail_closed(cur, catalog_names)
            expected_names = (*state.applied_names, selected.name)
            if (
                final_state.relation_oid != state.relation_oid
                or final_state.applied_names != expected_names
            ):
                raise MigrationRunnerError(
                    "pós-condição do ledger diverge do prefixo autorizado"
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
            "Executor fail-closed de uma migration aprovada. O bootstrap cria "
            "somente ledger vazio e não aplica pendências automaticamente."
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
    p_harden = sub.add_parser(
        "harden-ledger",
        help="endurece somente o ledger existente após confirmação explícita",
        allow_abbrev=False,
    )
    p_harden.add_argument(
        "--confirm",
        default=None,
        type=_parse_hardening_confirmation,
        help=f"confirmação explícita; use exatamente {LEDGER_HARDEN_CONFIRMATION}",
    )
    p_bootstrap = sub.add_parser(
        "bootstrap-ledger",
        help="cria somente ledger vazio owner-only após confirmação explícita",
        allow_abbrev=False,
    )
    p_bootstrap.add_argument(
        "--confirm",
        default=None,
        type=_parse_bootstrap_confirmation,
        help=(
            "confirmação explícita; use exatamente "
            f"{LEDGER_BOOTSTRAP_CONFIRMATION}"
        ),
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
    handlers = {
        "list": cmd_list,
        "status": cmd_status,
        "harden-ledger": cmd_harden_ledger,
        "bootstrap-ledger": cmd_bootstrap_ledger,
        "apply": cmd_apply,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
