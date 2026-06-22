#!/usr/bin/env python3
"""Cria uma nova migration com nome por timestamp UTC.

Evita a colisão de número entre branches paralelas (dois `0008`, dois `0012`…):
cada branch gera um nome único sem precisar coordenar o "próximo número".

Uso (a partir de backend/):
    python scripts/new_migration.py "add coluna x em pessoas"

Gera: backend/migrations/AAAAMMDD_HHMMSS_add_coluna_x_em_pessoas.sql
Ordena alfabeticamente DEPOIS do histórico 0001–0017. Ver migrations/README.md.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import re
import sys

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return slug or "migration"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or not " ".join(argv[1:]).strip():
        print('uso: python scripts/new_migration.py "descrição curta"', file=sys.stderr)
        return 2

    slug = slugify(" ".join(argv[1:]))
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = MIGRATIONS_DIR / f"{ts}_{slug}.sql"

    if path.exists():  # praticamente impossível (resolução de segundos), mas seguro
        print(f"já existe: {path.name}", file=sys.stderr)
        return 1

    header = "-- " + "=" * 76 + "\n"
    path.write_text(
        header
        + f"-- PastorAI — Migration {ts}_{slug}\n"
        + "-- TODO: descrever (RF/US/SPEC) e o que muda.\n"
        + "--\n"
        + "-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.\n"
        + "-- ALTER TYPE ... ADD VALUE: NÃO usar begin/commit (ver README).\n"
        + header
        + "\n",
        encoding="utf-8",
    )
    print(f"criada: backend/migrations/{path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
