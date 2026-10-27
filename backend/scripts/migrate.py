#!/usr/bin/env python3
"""Aplicador simples de migrations (backend/migrations/README.md; planejamento em ROADMAP.md).

    MIGRATION_DATABASE_URL=... python scripts/migrate.py status
    MIGRATION_DATABASE_URL=... python scripts/migrate.py apply 20261001_120000_slug.sql --yes

Regras:
- a URL vem só da variável de ambiente (nunca por argumento, nunca impressa);
- `apply` aplica UM arquivo por vez, dentro de uma transação, e registra o nome em
  `public.schema_migrations` na mesma transação; exige `--yes`;
- `--lock-timeout` (padrão 2s na transação; 0 desliga; máximo 60s) fixa o limite com
  SET LOCAL na transação da própria migration e o confere antes e depois: a
  migration pode apertá-lo, nunca afrouxar nem desligar (senão, rollback). Não é
  limite rígido durante o SQL, que pode mudar o GUC no meio e restaurá-lo;
- `--no-transaction` só para arquivos com `CREATE INDEX CONCURRENTLY` (sem
  `--lock-timeout`; vale o `SET lock_timeout` inicial do próprio arquivo);
- em PROD: faça backup antes (runbook) e anote a aplicação no registro da fatia.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"
DATABASE_URL_ENV = "MIGRATION_DATABASE_URL"
LEDGER = "public.schema_migrations"
# Migrations de frentes pausadas (governança E4B/consentimento) trazem este
# marcador no cabeçalho: ficam fora de `status` e `apply` até a Fase 5.
PAUSED_MARKER = "OPERATIONAL_AUTHORIZATION=BLOCKED"
_TX_LINE = re.compile(r"^\s*(begin|commit|rollback|start\s+transaction)\s*;\s*$", re.I)
_SESSION_LOCK_TIMEOUT = re.compile(
    r"\A(?:\s|--[^\n]*\n)*SET\s+lock_timeout\s*=\s*'[^'\n]+'\s*;", re.I
)
DEFAULT_LOCK_TIMEOUT = "2s"
_LOCK_TIMEOUT = re.compile(r"\A(?:0|([1-9][0-9]*)(ms|s))\Z")
_LOCK_TIMEOUT_MAX_MS = 60_000


def lock_timeout_ms(raw: str) -> int:
    """`--lock-timeout` em milissegundos: 0 (sem limite) ou N ms/s, até 60s."""
    match = _LOCK_TIMEOUT.match(raw.strip())
    if not match:
        raise argparse.ArgumentTypeError("use 0 (sem limite) ou um valor como 500ms, 2s ou 5s")
    if match.group(1) is None:
        return 0
    ms = int(match.group(1)) * (1000 if match.group(2) == "s" else 1)
    if ms > _LOCK_TIMEOUT_MAX_MS:
        raise argparse.ArgumentTypeError("o máximo é 60s")
    return ms


def is_paused(path: pathlib.Path) -> bool:
    return PAUSED_MARKER in path.read_text(encoding="utf-8")


def migration_files(directory: pathlib.Path = MIGRATIONS_DIR) -> list[str]:
    """Arquivos .sql do topo da pasta, em ordem de nome (= ordem de aplicação),
    sem as migrations pausadas."""
    return sorted(
        p.name for p in directory.glob("*.sql") if p.is_file() and not is_paused(p)
    )


def strip_outer_transaction(sql: str) -> str:
    """Remove o `begin;`/`commit;` externo para o runner controlar a transação.

    Assim a migration e o registro no ledger são confirmados juntos. Qualquer
    outro controle de transação no arquivo é recusado.
    """
    lines = sql.splitlines()

    def _is_code(line: str) -> bool:
        stripped = line.strip()
        return bool(stripped) and not stripped.startswith("--")

    code_idx = [i for i, line in enumerate(lines) if _is_code(line)]
    if code_idx:
        first, last = code_idx[0], code_idx[-1]
        if (
            first != last
            and re.match(r"^\s*begin\s*;\s*$", lines[first], re.I)
            and re.match(r"^\s*commit\s*;\s*$", lines[last], re.I)
        ):
            lines = lines[:first] + lines[first + 1 : last] + lines[last + 1 :]
    if any(_TX_LINE.match(line) for line in lines):
        raise ValueError("controle de transação no meio da migration")
    return "\n".join(lines) + "\n"


def pending(files: list[str], applied: set[str]) -> list[str]:
    return [name for name in files if name not in applied]


def _connect():
    url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not url:
        sys.exit(f"defina {DATABASE_URL_ENV}")
    import psycopg2  # import tardio: os testes unitários não precisam do driver

    return psycopg2.connect(url)


def _applied(cur) -> set[str]:
    cur.execute("SELECT to_regclass(%s)", (LEDGER,))
    if cur.fetchone()[0] is None:
        sys.exit(f"{LEDGER} não existe neste banco; crie o ledger antes de aplicar")
    cur.execute(f"SELECT name FROM {LEDGER}")
    return {row[0] for row in cur.fetchall()}


def cmd_status(conn) -> int:
    with conn.cursor() as cur:
        applied = _applied(cur)
    files = migration_files()
    todo = pending(files, applied)
    unknown = sorted(applied - set(files))
    print(f"aplicadas: {len(applied)}  arquivos: {len(files)}  pendentes: {len(todo)}")
    for name in todo:
        print(f"  PENDENTE  {name}")
    for name in unknown:
        print(f"  NO BANCO, SEM ARQUIVO  {name}")
    return 0


def _lock_timeout_ativo(cur) -> int:
    # SHOW não adquire snapshot: a migration ainda pode definir seu isolamento.
    cur.execute("SHOW lock_timeout")
    raw = str(cur.fetchone()[0])
    match = re.fullmatch(r"(\d+)(ms|s|min|h|d)?", raw)
    if not match:
        raise RuntimeError("lock_timeout retornado pelo servidor não reconhecido")
    units = {None: 1, "ms": 1, "s": 1000, "min": 60_000, "h": 3_600_000, "d": 86_400_000}
    return int(match.group(1)) * units[match.group(2)]


def cmd_apply(conn, name: str, *, transactional: bool, lock_timeout: int = 0) -> int:
    path = MIGRATIONS_DIR / name
    if path.name != name or not path.is_file() or path.suffix != ".sql":
        sys.exit(f"arquivo inválido: {name}")
    if (isinstance(lock_timeout, bool) or not isinstance(lock_timeout, int)
            or not 0 <= lock_timeout <= _LOCK_TIMEOUT_MAX_MS):
        sys.exit("lock_timeout inválido: use 0 a 60000 ms")
    if lock_timeout and not transactional:
        sys.exit("--lock-timeout vale só dentro da transação; com --no-transaction use 0")
    if is_paused(path):
        sys.exit(f"{name} pertence a uma frente pausada ({PAUSED_MARKER})")
    try:
        sql = strip_outer_transaction(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        sys.exit(f"{name}: {exc}")
    with conn.cursor() as cur:
        if name in _applied(cur):
            sys.exit(f"{name} já está registrada em {LEDGER}")
    conn.commit()
    if not transactional:
        conn.autocommit = True
    try:
        with conn.cursor() as cur:
            if not transactional:
                # Multiple statements in one execute create an implicit
                # transaction, even with autocommit. Keep concurrent DDL alone.
                setting = _SESSION_LOCK_TIMEOUT.match(sql)
                if setting:
                    cur.execute(setting.group())
                    sql = sql[setting.end():]
            if lock_timeout:
                # SET LOCAL na transação da própria migration: o pooler ignora PGOPTIONS
                # e um SET de sessão pode ficar em outra conexão do pool.
                # SELECT set_config/pg_settings impediria SET TRANSACTION ISOLATION
                # LEVEL nos arquivos históricos. Use só comandos utilitários aqui.
                cur.execute("SET LOCAL lock_timeout = %s", (f"{lock_timeout}ms",))
                if _lock_timeout_ativo(cur) != lock_timeout:
                    raise RuntimeError("lock_timeout não ficou ativo na transação: nada foi aplicado")
            cur.execute(sql)
            if lock_timeout:
                ativo = _lock_timeout_ativo(cur)
                if not 0 < ativo <= lock_timeout:
                    raise RuntimeError(
                        f"a migration deixou lock_timeout em {ativo}ms (pedido: {lock_timeout}ms): "
                        "nada foi aplicado; se esta migration revisada exige limite maior, "
                        "reaplique com --lock-timeout explícito"
                    )
            cur.execute(f"INSERT INTO {LEDGER} (name) VALUES (%s)", (name,))
        if transactional:
            conn.commit()
    except Exception:
        if transactional:
            conn.rollback()
        raise
    print(f"aplicada: {name}")
    if lock_timeout:
        print(f"lock_timeout: {lock_timeout}ms")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="lista migrations pendentes")
    ap = sub.add_parser("apply", help="aplica UMA migration")
    ap.add_argument("name", help="nome do arquivo em backend/migrations")
    ap.add_argument("--yes", action="store_true", help="confirma a escrita")
    ap.add_argument(
        "--no-transaction",
        action="store_true",
        help="só para CREATE INDEX CONCURRENTLY",
    )
    ap.add_argument(
        "--lock-timeout",
        type=lock_timeout_ms,
        help=f"espera máxima por lock na transação (padrão {DEFAULT_LOCK_TIMEOUT}; 0 desliga)",
    )
    args = parser.parse_args(argv)
    if args.cmd == "apply" and not args.yes:
        parser.error("apply exige --yes")
    if args.cmd == "apply" and args.no_transaction and args.lock_timeout:
        parser.error("--lock-timeout vale só dentro da transação; com --no-transaction use 0")
    conn = _connect()
    try:
        if args.cmd == "status":
            return cmd_status(conn)
        if args.lock_timeout is not None:
            lock = args.lock_timeout
        else:
            lock = 0 if args.no_transaction else lock_timeout_ms(DEFAULT_LOCK_TIMEOUT)
        return cmd_apply(conn, args.name, transactional=not args.no_transaction, lock_timeout=lock)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
