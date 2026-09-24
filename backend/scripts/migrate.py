#!/usr/bin/env python3
"""Aplicador simples de migrations (processo do MVP, docs/ops/MVP-PLANO-SIMPLIFICACAO.md §3.4).

    MIGRATION_DATABASE_URL=... python scripts/migrate.py status
    MIGRATION_DATABASE_URL=... python scripts/migrate.py apply 20261001_120000_slug.sql --yes

Regras:
- a URL vem só da variável de ambiente (nunca por argumento, nunca impressa);
- `apply` aplica UM arquivo por vez, dentro de uma transação, e registra o nome em
  `public.schema_migrations` na mesma transação; exige `--yes`;
- `--no-transaction` só para arquivos com `CREATE INDEX CONCURRENTLY`;
- em PROD: faça backup antes (runbook) e anote a aplicação no registro da fatia.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"
DATABASE_URL_ENV = "MIGRATION_DATABASE_URL"
LEDGER = "public.schema_migrations"


def migration_files(directory: pathlib.Path = MIGRATIONS_DIR) -> list[str]:
    """Arquivos .sql do topo da pasta, em ordem de nome (= ordem de aplicação)."""
    return sorted(p.name for p in directory.glob("*.sql") if p.is_file())


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


def cmd_apply(conn, name: str, *, transactional: bool) -> int:
    path = MIGRATIONS_DIR / name
    if path.name != name or not path.is_file() or path.suffix != ".sql":
        sys.exit(f"arquivo inválido: {name}")
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        if name in _applied(cur):
            sys.exit(f"{name} já está registrada em {LEDGER}")
    conn.commit()
    if not transactional:
        conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(f"INSERT INTO {LEDGER} (name) VALUES (%s)", (name,))
        if transactional:
            conn.commit()
    except Exception:
        if transactional:
            conn.rollback()
        raise
    print(f"aplicada: {name}")
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
    args = parser.parse_args(argv)
    if args.cmd == "apply" and not args.yes:
        parser.error("apply exige --yes")
    conn = _connect()
    try:
        if args.cmd == "status":
            return cmd_status(conn)
        return cmd_apply(conn, args.name, transactional=not args.no_transaction)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
