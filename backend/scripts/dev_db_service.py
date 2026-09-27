#!/usr/bin/env python3
"""Guarda o acesso ao banco do DEV neste computador sem expor a URL.

    python3 backend/scripts/dev_db_service.py            # pergunta a URL, sem eco
    python3 backend/scripts/dev_db_service.py --remover  # apaga o acesso salvo

Grava ~/.config/pastorai/pg_service.conf e ~/.config/pastorai/pgpass (modo
0600) com o serviço libpq `pastorai_dev`. Depois, psql, pg_dump e o
migrate.py usam só o nome do serviço, nunca a URL:

    PGSERVICEFILE=~/.config/pastorai/pg_service.conf psql service=pastorai_dev
    PGSERVICEFILE=~/.config/pastorai/pg_service.conf \\
      MIGRATION_DATABASE_URL=service=pastorai_dev python scripts/migrate.py status

Regras:
- URL e senha são lidas sem eco e nunca impressas, nem em mensagem de erro;
- recusa a URL de PROD e exige o ref do projeto DEV no host ou no usuário;
- só roda em terminal interativo (sem terminal, o getpass ecoaria a senha).
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

PROD_REF = "pffafnchtxbimpwyaczq"
DEV_REF = "cxmjojnocigekgcxhubi"  # Igreja12-dev (docs/ops/DEV-SMOKE-USERS.md)
SERVICE = "pastorai_dev"
CONFIG_DIR = Path.home() / ".config" / "pastorai"
SERVICE_FILE = CONFIG_DIR / "pg_service.conf"
PASS_FILE = CONFIG_DIR / "pgpass"
_REF = re.compile(r"^[a-z]{20}$")
# Alguns terminais embrulham a colagem nestes códigos invisíveis.
_PASTE_MARKERS = ("\x1b[200~", "\x1b[201~")
# A URL pode vir no meio do texto: aspas, DATABASE_URL=..., psql '...', jdbc:...
_URI = re.compile(r"postgres(?:ql)?://[^\s'\"]+")
_PSQL_FLAG = re.compile(r"(?:^|\s)-([hpdU])\s*(\S+)")
# ":[YOUR-PASSWORD]@" copiado do painel; o urlsplit confunde colchetes com IPv6.
_PLACEHOLDER = re.compile(r":\[[^\]@/]*\]@")
_PLACEHOLDER_VALUE = re.compile(r"^\[.*\]$")
_OPTIONS = frozenset({"sslmode", "connect_timeout"})
_PASTE_HINT = "cole com Ctrl+Shift+V ou com o botão direito do mouse → Colar"


class Recusa(Exception):
    """Erro com mensagem segura para o proprietário (sem URL nem senha)."""


def _service_value(value: str) -> str:
    # pg_service.conf não aceita aspas: recusa o que não dá para gravar sem ambiguidade.
    if not value or value != value.strip() or value.startswith("#") or any(
        c in value for c in "\r\n\x00"
    ):
        raise Recusa("a URL tem um trecho inválido")
    return value


def _pgpass_value(value: str) -> str:
    if not value or any(c in value for c in "\r\n\x00"):
        raise Recusa("a senha tem um caractere inválido")
    return value.replace("\\", "\\\\").replace(":", "\\:")


def clean_input(text: str) -> str:
    """Tira os códigos de colagem e os espaços das pontas; recusa tecla de controle."""
    for marker in _PASTE_MARKERS:
        text = text.replace(marker, "")
    text = text.strip()
    if not text:
        raise Recusa(f"não chegou nada. No terminal, {_PASTE_HINT}")
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise Recusa(f"chegaram teclas de controle (talvez Ctrl+V). C{_PASTE_HINT[1:]}")
    return text


def _from_uri(uri: str) -> tuple[str, int | None, str, str | None, str | None, dict[str, str]]:
    try:
        parts = urlsplit(_PLACEHOLDER.sub("@", uri, count=1))
        port = parts.port
    except ValueError:
        raise Recusa(
            "a URL está incompleta ou a senha dentro dela tem caractere especial; "
            "deixe [YOUR-PASSWORD] na URL e digite a senha na pergunta seguinte"
        ) from None
    query = dict(parse_qsl(parts.query, keep_blank_values=True))  # jdbc: ?user=&password=
    user = unquote(parts.username) if parts.username else query.get("user")
    password = unquote(parts.password) if parts.password else query.get("password")
    dbname = unquote(parts.path.removeprefix("/"))
    return unquote(parts.hostname or ""), port, dbname, user, password, query


def _from_psql(command: str) -> tuple[str, int | None, str, str | None, None, dict[str, str]]:
    flags = {key: value.strip("'\"") for key, value in _PSQL_FLAG.findall(command)}
    if not flags.get("p", "5432").isdigit():
        raise Recusa("o comando psql colado está incompleto")
    port = int(flags["p"]) if "p" in flags else None
    return flags.get("h", ""), port, flags.get("d", ""), flags.get("U"), None, {}


def parse_connection(text: str, ref: str) -> tuple[dict[str, str], str | None]:
    """Devolve (conexão sem senha, senha ou None) já com as travas DEV/PROD."""
    raw = clean_input(text)
    if PROD_REF in raw or PROD_REF in unquote(raw):
        raise Recusa("essa é a URL de PRODUÇÃO")
    if match := _URI.search(raw):
        host, port, dbname, user, password, query = _from_uri(match.group(0))
    elif raw.startswith("psql "):
        host, port, dbname, user, password, query = _from_psql(raw)
    else:
        raise Recusa(
            f"recebi {len(raw)} caracteres, mas nada começando com postgresql://. "
            "No Supabase, em Connect, copie a URL do tipo URI (Session pooler)"
        )
    if not host or not user:
        raise Recusa("a URL está incompleta: faltou o servidor ou o usuário")
    if ref not in host and ref not in user:
        raise Recusa(f"a URL não é do projeto DEV esperado ({ref})")
    if port is None:
        port = 5432
    if port == 6543 and host.endswith(".pooler.supabase.com"):
        # Mesmo pooler em modo sessão: pg_dump e SET LOCAL funcionam sem surpresa.
        print("Aviso: troquei a porta 6543 (modo transação) pela 5432 (modo sessão).")
        port = 5432
    conn = {
        "host": _service_value(host),
        "port": str(port),
        "dbname": _service_value(dbname or "postgres"),
        "user": _service_value(user),
        "sslmode": "require",
    }
    for key in sorted(_OPTIONS & query.keys()):
        conn[key] = _service_value(query[key])
    if password is not None and (not password or _PLACEHOLDER_VALUE.match(password)):
        password = None
    return conn, password


def service_text(conn: dict[str, str], ref: str) -> str:
    lines = [f"# PastorAI DEV (ref {ref}); gerado por backend/scripts/dev_db_service.py", f"[{SERVICE}]"]
    lines += [f"{key}={value}" for key, value in conn.items()]
    lines.append(f"passfile={_service_value(str(PASS_FILE))}")
    lines.append("application_name=pastorai-dev-ops")
    return "\n".join(lines) + "\n"


def pgpass_text(conn: dict[str, str], password: str) -> str:
    fields = [conn["host"], conn["port"], conn["dbname"], conn["user"], password]
    return ":".join(_pgpass_value(v) for v in fields) + "\n"


def _prepare_dir() -> None:
    if CONFIG_DIR.is_symlink():
        raise Recusa(f"{CONFIG_DIR} é um link simbólico")
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)


def _unlink_regular(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode):
        raise Recusa(f"{path} existe e não é um arquivo comum")
    path.unlink()


def _write_restricted(path: Path, content: str) -> None:
    _unlink_regular(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def _redact(text: str, conn: dict[str, str], password: str) -> str:
    for secret, mark in ((password, "***"), (conn["host"], "<servidor>"), (conn["user"], "<usuario>")):
        text = text.replace(secret, mark)
    return text


def _test_connection(conn: dict[str, str], password: str) -> None:
    psql = shutil.which("psql")
    if not psql:
        print("Acesso salvo. (psql não encontrado: não testei a conexão.)")
        return
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(Path.home()),
        "PGSERVICEFILE": str(SERVICE_FILE),
        "PGSERVICE": SERVICE,
        "PGCONNECT_TIMEOUT": "15",
        "PSQL_HISTORY": "/dev/null",
    }
    query = "SELECT current_setting('server_version') || ' | ' || current_user"
    try:
        result = subprocess.run(
            [psql, "-X", "-A", "-t", "-q", "-v", "ON_ERROR_STOP=1", "-c", query],
            env=env, capture_output=True, text=True, timeout=60, check=False,
        )
    except subprocess.TimeoutExpired:
        print("Acesso salvo, mas o teste de conexão demorou demais.")
        return
    if result.returncode == 0:
        print(f"Conexão com o DEV funcionando: PostgreSQL {result.stdout.strip()}")
        return
    first = (result.stderr.strip().splitlines() or ["erro desconhecido"])[0]
    print("Acesso salvo, mas a conexão falhou: " + _redact(first, conn, password))
    print("Confira a URL e a senha e rode o comando de novo (ele substitui o acesso salvo).")


def cmd_save(ref: str) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise Recusa("rode este comando num terminal interativo")
    print(f"Projeto DEV esperado: {ref}.")
    print(f"A tela fica em branco enquanto você cola: é normal. Para colar, {_PASTE_HINT}.")
    conn, password = parse_connection(getpass.getpass("URL do banco do DEV, depois Enter: "), ref)
    if password is None:
        password = clean_input(getpass.getpass("Senha do banco do DEV, depois Enter: "))
    pass_content = pgpass_text(conn, password)
    service_content = service_text(conn, ref)
    _prepare_dir()
    try:
        _write_restricted(PASS_FILE, pass_content)
        _write_restricted(SERVICE_FILE, service_content)
    except BaseException:
        for path in (SERVICE_FILE, PASS_FILE):
            path.unlink(missing_ok=True)
        raise
    print(f"Acesso salvo em {CONFIG_DIR} (só o seu usuário lê).")
    _test_connection(conn, password)
    return 0


def cmd_remove() -> int:
    for path in (SERVICE_FILE, PASS_FILE):
        _unlink_regular(path)
    print("Acesso ao DEV removido deste computador.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default=DEV_REF, help="ref do projeto DEV no Supabase")
    parser.add_argument("--remover", action="store_true", help="apaga o acesso salvo")
    args = parser.parse_args(argv)
    try:
        if args.remover:
            return cmd_remove()
        if not _REF.match(args.ref) or args.ref == PROD_REF:
            raise Recusa("ref inválido para o DEV")
        return cmd_save(args.ref)
    except Recusa as exc:
        print(f"Nada foi gravado: {exc}.", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado. Nada foi gravado.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
