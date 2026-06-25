#!/usr/bin/env python3
"""Aplica as migrations SQL, em ordem de nome, contra um DATABASE_URL alvo.

B1 — staging isolado. Este runner serve para preparar o banco de um **projeto
Supabase de STAGING** (não produção). Ele NÃO roda nada ao ser importado e NÃO
aplica nada sem o subcomando `apply` + confirmação explícita do operador.

Hoje as migrations são aplicadas à mão no SQL editor do Supabase (ver
migrations/README.md). Este script automatiza só a ordem e o registro do que já
subiu, mantendo o mesmo conteúdo SQL — útil para reconstruir staging do zero.

Uso (a partir de backend/):

    # 1) Só listar as migrations na ORDEM de aplicação (não conecta ao banco):
    python scripts/apply_migrations.py list

    # 2) Ver o que já foi aplicado x pendente (read-only; precisa do banco):
    python scripts/apply_migrations.py status --database-url "postgresql://..."

    # 3) Aplicar as pendentes (pede confirmação digitando o host de destino):
    python scripts/apply_migrations.py apply --database-url "postgresql://..."

O DATABASE_URL pode vir da flag `--database-url` OU da variável de ambiente
`STAGING_DATABASE_URL`. Nunca é embutido no código. A senha nunca é impressa.

Controle de versões aplicadas: o runner cria e mantém uma tabela
`schema_migrations(name, applied_at)` no banco alvo (idempotente). Migrations
idempotentes podem ser reaplicadas sem dano; o registro evita reaplicá-las.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
from urllib.parse import urlsplit, urlunsplit

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"
# Qualificada com o schema (public) para casar com o to_regclass de get_applied
# e não depender do search_path da conexão alvo.
BOOKKEEPING_TABLE = "public.schema_migrations"


# ---------------------------------------------------------------------------
# Descoberta e ordenação
# ---------------------------------------------------------------------------
def discover_migrations() -> list[pathlib.Path]:
    """Retorna os arquivos .sql em ORDEM ALFABÉTICA de nome (a regra do projeto).

    `0001`–`0017` ordenam antes dos nomes por timestamp `AAAAMMDD_...`. Ver
    migrations/README.md. O README e qualquer outro .md são ignorados.
    """
    return sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda p: p.name)


def normalize_url(url: str) -> str:
    """Aceita a forma `postgresql+psycopg2://` (usada pelo app) e devolve a
    forma `postgresql://` que o psycopg2.connect entende."""
    if url and url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql://", 1)
    return url


def mask_url(url: str) -> str:
    """Mascara a senha da connection string para exibição (nunca logar segredo)."""
    try:
        parts = urlsplit(url)
        if parts.password:
            safe_netloc = parts.netloc.replace(f":{parts.password}@", ":***@")
            parts = parts._replace(netloc=safe_netloc)
        return urlunsplit(parts)
    except ValueError:
        return "<url ilegível>"


def resolve_database_url(args: argparse.Namespace) -> str | None:
    """DATABASE_URL alvo: flag tem prioridade, senão a env STAGING_DATABASE_URL."""
    raw = getattr(args, "database_url", None) or os.environ.get("STAGING_DATABASE_URL")
    return normalize_url(raw) if raw else None


# ---------------------------------------------------------------------------
# Acesso ao banco (psycopg2 importado de forma preguiçosa)
# ---------------------------------------------------------------------------
def _connect(url: str):
    try:
        import psycopg2  # lazy: `list` funciona sem o driver instalado
    except ImportError:  # pragma: no cover - ambiente sem deps
        print(
            "ERRO: psycopg2 não está instalado. Rode dentro do venv do backend "
            "(pip install -r requirements.txt).",
            file=sys.stderr,
        )
        raise SystemExit(3)

    try:
        conn = psycopg2.connect(url)
    except psycopg2.Error as exc:
        # Cobre OperationalError (host/credencial) e ProgrammingError (DSN
        # malformado). Mensagem enxuta — o erro do libpq não contém a senha — e
        # sem traceback.
        print(f"ERRO ao conectar ao destino: {exc}".strip(), file=sys.stderr)
        raise SystemExit(6)
    # Autocommit replica o SQL editor do Supabase: cada arquivo controla sua
    # própria transação via `begin;/commit;` quando os tem, e as migrations de
    # `ALTER TYPE ... ADD VALUE` (sem begin/commit) rodam fora de transação.
    conn.autocommit = True
    return conn


def get_applied(cur) -> set[str]:
    """Nomes já registrados em schema_migrations. READ-ONLY: se a tabela ainda
    não existe, devolve vazio sem criá-la (quem cria é só o `apply`)."""
    cur.execute("select to_regclass(%s)", (BOOKKEEPING_TABLE,))
    if cur.fetchone()[0] is None:
        return set()
    cur.execute(f"select name from {BOOKKEEPING_TABLE}")
    return {row[0] for row in cur.fetchall()}


def ensure_bookkeeping(cur) -> None:
    """Cria a tabela de controle (idempotente). Só chamada no caminho `apply`."""
    cur.execute(
        f"""
        create table if not exists {BOOKKEEPING_TABLE} (
            name text primary key,
            applied_at timestamptz not null default now()
        )
        """
    )


# ---------------------------------------------------------------------------
# Subcomandos
# ---------------------------------------------------------------------------
def cmd_list(_args: argparse.Namespace) -> int:
    migrations = discover_migrations()
    if not migrations:
        print(f"Nenhuma migration encontrada em {MIGRATIONS_DIR}", file=sys.stderr)
        return 1
    print(f"Migrations em ordem de aplicação ({len(migrations)}):")
    for i, path in enumerate(migrations, 1):
        print(f"  {i:>2}. {path.name}")
    print("\nEste comando é apenas informativo — nada foi aplicado.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    url = resolve_database_url(args)
    if not url:
        print(
            "ERRO: informe o destino com --database-url ou STAGING_DATABASE_URL.",
            file=sys.stderr,
        )
        return 2
    migrations = discover_migrations()
    conn = _connect(url)
    try:
        with conn.cursor() as cur:
            applied = get_applied(cur)
    finally:
        conn.close()

    print(f"Destino: {mask_url(url)}")
    print(f"Migrations no repo: {len(migrations)} | registradas: {len(applied)}\n")
    pending = []
    for path in migrations:
        done = path.name in applied
        print(f"  [{'x' if done else ' '}] {path.name}")
        if not done:
            pending.append(path)
    print(f"\nPendentes: {len(pending)}. (Read-only — nada foi aplicado.)")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    url = resolve_database_url(args)
    if not url:
        print(
            "ERRO: informe o destino com --database-url ou STAGING_DATABASE_URL.",
            file=sys.stderr,
        )
        return 2

    migrations = discover_migrations()
    if not migrations:
        print(f"Nenhuma migration em {MIGRATIONS_DIR}", file=sys.stderr)
        return 1

    # Confirmação interativa é obrigatória — abortamos ANTES de abrir conexão
    # quando não há terminal (cron/CI/pipe), para nunca aplicar sem um humano.
    if not sys.stdin.isatty():
        print(
            "ERRO: `apply` exige confirmação interativa num terminal (stdin não é "
            "um tty). Use `status` para inspecionar sem aplicar. "
            "Abortado — nada foi aplicado.",
            file=sys.stderr,
        )
        return 4

    conn = _connect(url)
    try:
        with conn.cursor() as cur:
            ensure_bookkeeping(cur)
            applied = get_applied(cur)
        pending = [p for p in migrations if p.name not in applied]

        host = urlsplit(url).hostname or "<host desconhecido>"
        print(f"Destino: {mask_url(url)}")
        print(f"Host:    {host}\n")

        if not pending:
            print("Nada a aplicar — todas as migrations já constam como aplicadas.")
            return 0

        print(f"Vão ser aplicadas {len(pending)} migration(s), nesta ordem:")
        for i, path in enumerate(pending, 1):
            print(f"  {i:>2}. {path.name}")

        print(
            "\n⚠️  Confirme que este é o banco de STAGING (NUNCA produção).\n"
            "    O guard de envios reais (B2) ainda não existe."
        )
        try:
            typed = input(
                f'\nDigite EXATAMENTE o host para confirmar ("{host}"): '
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAbortado — nada foi aplicado.", file=sys.stderr)
            return 4
        if typed != host:
            print("Host não confere. Abortado — nada foi aplicado.", file=sys.stderr)
            return 4

        print()
        for i, path in enumerate(pending, 1):
            sql = path.read_text(encoding="utf-8")
            print(f"  ({i}/{len(pending)}) aplicando {path.name} ...", flush=True)
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        f"insert into {BOOKKEEPING_TABLE}(name) values (%s) "
                        "on conflict (name) do nothing",
                        (path.name,),
                    )
            except Exception as exc:  # noqa: BLE001 - reportar e parar no 1º erro
                print(
                    f"\nFALHOU em {path.name}: {type(exc).__name__}: {exc}\n"
                    "Parando no 1º erro. As migrations já concluídas ficam "
                    "registradas em schema_migrations; como as migrations são "
                    "idempotentes (IF NOT EXISTS / ON CONFLICT), basta corrigir a "
                    "causa e rodar `apply` de novo para retomar as pendentes — "
                    "reexecutar um arquivo parcialmente aplicado é seguro.",
                    file=sys.stderr,
                )
                return 5
        print(f"\nOK — {len(pending)} migration(s) aplicada(s) e registrada(s).")
        return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Aplica as migrations em ordem contra um DATABASE_URL alvo (staging). "
            "Nunca aplica nada sem o subcomando `apply` + confirmação."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="lista as migrations em ordem (não conecta ao banco)")

    p_status = sub.add_parser(
        "status", help="mostra aplicadas x pendentes (read-only; precisa do banco)"
    )
    p_apply = sub.add_parser(
        "apply", help="aplica as pendentes (exige confirmação interativa do host)"
    )
    for p in (p_status, p_apply):
        p.add_argument(
            "--database-url",
            default=None,
            help="connection string do banco ALVO (senão usa STAGING_DATABASE_URL)",
        )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    handlers = {"list": cmd_list, "status": cmd_status, "apply": cmd_apply}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
