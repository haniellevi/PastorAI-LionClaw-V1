#!/usr/bin/env python3
"""Monta a transação única que recria o schema public do DEV igual ao do PROD.

Não conecta em banco nenhum: lê arquivos e escreve um .sql para revisão (Sarah)
e execução (com "ok" do proprietário). Entradas, todas lidas só com leitura:

    python3 montar_recriacao.py \\
      --dump prod_public_schema.sql \\      # pg_dump --schema-only --schema=public do PROD
      --fingerprint fingerprint_prod.csv \\ # fingerprint_ro.sql no PROD (psql -q --csv)
      --ledger ledger_prod.csv \\           # ledger_lista_ro.sql no PROD (psql -q --csv)
      --estado-dev 291:<md5> \\             # inventario_ro.sql §10 no DEV (trava)
      --ledger-dev 33 \\                    # linhas do ledger antigo do DEV (trava)
      [--ensure-rls] \\                     # recria o event trigger ensure_rls igual ao do PROD
      --saida recriar_dev.sql

    PGSERVICEFILE=~/.config/pastorai/pg_service.conf \\
      psql service=pastorai_dev -X -q -f recriar_dev.sql

O .sql gerado, numa transação: (1) trava no DEV inspecionado; (2) apaga os
objetos de public, mantendo o schema, sua ACL e os default privileges do
Supabase; (3) aplica a planta do PROD; (4) zera o que os default privileges deram
a anon/authenticated/service_role na criação; (5) aplica as ACLs exatas do PROD;
(6) grava o ledger com as mesmas linhas e origens; (7) compara a impressão digital
objeto por objeto com a do PROD e aborta se houver diferença. Recusa dump com
dado, SET SESSION AUTHORIZATION, dono diferente de postgres ou tipo inesperado.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import pathlib
import re
import secrets
import string
import sys
from datetime import datetime, timezone

KIT = pathlib.Path(__file__).resolve().parent
ORIGENS = frozenset({"PROVA_OBJETO", "BASELINE_V1_HISTORICO", "MIGRATE_PY"})
_HEADER = re.compile(r"^-- Name: (?P<name>.*); Type: (?P<type>[A-Z ]+); Schema: (?P<schema>[^;]+); Owner: (?P<owner>[^;]*)")
_SET = re.compile(r"^SET ([a-z_]+) = (.*);$")
_NOME_MIGRATION = re.compile(r"^[0-9]{4}_[a-z0-9_]+\.sql$|^[0-9]{8}_[0-9]{6}_[a-z0-9_]+\.sql$")
# Entradas do dump que não entram: o schema public, sua ACL e seu comentário ficam
# os do DEV; os default privileges são do Supabase (os de supabase_admin nem dá).
_DESCARTA = {("SCHEMA", "public"), ("ACL", "SCHEMA public"), ("COMMENT", "SCHEMA public")}
_TIPOS = frozenset({
    "TABLE", "VIEW", "MATERIALIZED VIEW", "SEQUENCE", "SEQUENCE OWNED BY", "DEFAULT", "CONSTRAINT",
    "CHECK CONSTRAINT", "FK CONSTRAINT", "INDEX", "INDEX ATTACH", "TABLE ATTACH", "TRIGGER",
    "POLICY", "ROW SECURITY", "FUNCTION", "PROCEDURE", "AGGREGATE", "TYPE", "DOMAIN", "COMMENT",
    "ACL", "DEFAULT ACL", "SCHEMA", "RULE",
})
# Nada de dado, troca de usuário ou meta-comando dentro da planta.
_PROIBIDO = re.compile(
    r"^(COPY |INSERT INTO|SET SESSION AUTHORIZATION|RESET SESSION AUTHORIZATION|SET ROLE|"
    r"SELECT pg_catalog\.setval|-- Data for Name:)", re.M)


class Erro(Exception):
    pass


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trecho(path: pathlib.Path, marca: str) -> str:
    """Texto entre '-- <marca>:inicio' e '-- <marca>:fim' (as linhas das marcas ficam fora)."""
    linhas = path.read_text(encoding="utf-8").splitlines()
    ini = next(i for i, l in enumerate(linhas) if l.startswith(f"-- {marca}:inicio"))
    fim = next(i for i, l in enumerate(linhas) if l.startswith(f"-- {marca}:fim"))
    return "\n".join(linhas[ini + 1:fim])


def ler_dump(path: pathlib.Path) -> tuple[list[str], list[str], dict[str, int]]:
    """Devolve (planta, permissões, contagem por tipo) a partir do dump em texto."""
    # Bytes exatos: corpos de função no PROD têm \r\n (gravados fora do repo); o
    # read_text converteria para \n e a função restaurada ficaria diferente.
    texto = path.read_bytes().decode("utf-8")
    if "-- PostgreSQL database dump" not in texto or "-- PostgreSQL database dump complete" not in texto:
        raise Erro("o dump não parece completo (faltam o cabeçalho ou o fim do pg_dump)")
    if _PROIBIDO.search(texto):
        raise Erro("o dump tem dado, troca de usuário ou setval: recusado")
    linhas = texto.split("\n")
    fim = next(i for i, l in enumerate(linhas) if l == "-- PostgreSQL database dump complete")
    linhas = linhas[:fim - 1]  # tira "--" + "dump complete" + \unrestrict
    blocos: list[tuple[dict[str, str] | None, list[str]]] = [(None, [])]
    i = 0
    while i < len(linhas):
        m = _HEADER.match(linhas[i]) if i > 0 and linhas[i - 1] == "--" else None
        if m and i + 1 < len(linhas) and linhas[i + 1] == "--":
            blocos[-1][1].pop()  # o "--" de abertura pertence ao cabeçalho novo
            blocos.append((m.groupdict(), ["--", linhas[i], "--"]))
            i += 2
            continue
        blocos[-1][1].append(linhas[i])
        i += 1
    planta: list[str] = []
    permissoes: list[str] = []
    contagem: dict[str, int] = {}
    for cab, corpo in blocos:
        if cab is None:  # preâmbulo: SETs de sessão viram SET LOCAL
            planta.extend(_preambulo(corpo))
            continue
        tipo, nome, dono, schema = cab["type"], cab["name"], cab["owner"], cab["schema"]
        if tipo not in _TIPOS:
            raise Erro(f"tipo de entrada inesperado no dump: {tipo} ({nome})")
        if (tipo, nome) in _DESCARTA or tipo == "DEFAULT ACL":
            continue
        if schema != "public" or dono != "postgres":
            raise Erro(f"entrada fora de public ou com dono {dono}: {tipo} {nome}")
        if any(l.startswith("\\") for l in corpo):
            raise Erro(f"meta-comando do psql dentro da entrada {tipo} {nome}")
        corpo = [_set_local(l) for l in corpo]
        (permissoes if tipo == "ACL" else planta).extend(corpo)
        contagem[tipo] = contagem.get(tipo, 0) + 1
    return planta, permissoes, contagem


def _set_local(linha: str) -> str:
    m = _SET.match(linha)
    return f"SET LOCAL {m.group(1)} = {m.group(2)};" if m else linha


def _preambulo(corpo: list[str]) -> list[str]:
    saida = []
    for linha in corpo:
        if linha.startswith("\\restrict") or linha.startswith("\\unrestrict"):
            continue  # o arquivo gerado tem o seu próprio \restrict em volta de tudo
        m = _SET.match(linha)
        if m and m.group(1) in {"statement_timeout", "lock_timeout", "idle_in_transaction_session_timeout",
                                "transaction_timeout"}:
            continue  # valem os limites da transação, não os zeros do pg_dump
        if linha == "SELECT pg_catalog.set_config('search_path', '', false);":
            linha = "SELECT pg_catalog.set_config('search_path', '', true);"
        saida.append(_set_local(linha))
    if any(l.startswith("\\") for l in saida):
        raise Erro("meta-comando inesperado no preâmbulo do dump")
    return saida


def ler_fingerprint(path: pathlib.Path) -> list[tuple[str, str, str]]:
    linhas = [l for l in path.read_text(encoding="utf-8").splitlines()
              if l and l not in {"BEGIN", "SET", "ROLLBACK"}]
    leitor = csv.reader(io.StringIO("\n".join(linhas)))
    if next(leitor) != ["secao", "objeto", "md5"]:
        raise Erro("fingerprint sem o cabeçalho secao,objeto,md5")
    itens, totais = [], {}
    for secao, objeto, md5 in leitor:
        if objeto.startswith("*TOTAL*"):
            totais[secao] = (objeto, md5)
        else:
            itens.append((secao, objeto, md5))
    # Confere os totais do próprio arquivo: pega arquivo truncado ou editado.
    por_secao: dict[str, list[tuple[str, str]]] = {}
    for secao, objeto, md5 in itens:
        por_secao.setdefault(secao, []).append((objeto, md5))
    for secao, pares in por_secao.items():
        pares.sort(key=lambda p: p[0].encode())
        esperado = hashlib.md5(",".join(f"{o}={m}" for o, m in pares).encode()).hexdigest()
        if totais.get(secao) != (f"*TOTAL* ({len(pares)})", esperado):
            raise Erro(f"total da seção {secao} não bate com as linhas do fingerprint")
    publico = sorted(((s, o, m) for s, o, m in itens if s != "plataforma"), key=lambda r: (r[0].encode(), r[1].encode()))
    esperado = hashlib.md5(",".join(f"{s}:{o}={m}" for s, o, m in publico).encode()).hexdigest()
    if totais.get("~public") != (f"*TOTAL* ({len(publico)})", esperado):
        raise Erro("total de public não bate com as linhas do fingerprint")
    return itens


def ler_ledger(path: pathlib.Path, itens_fp: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    linhas = [l for l in path.read_text(encoding="utf-8").splitlines()
              if l and l not in {"BEGIN", "ROLLBACK"}]
    leitor = csv.reader(io.StringIO("\n".join(linhas)))
    if next(leitor) != ["name", "origem"]:
        raise Erro("ledger sem o cabeçalho name,origem")
    linhas_ledger = [(n, o) for n, o in leitor]
    for nome, origem in linhas_ledger:
        if not _NOME_MIGRATION.match(nome) or origem not in ORIGENS:
            raise Erro(f"linha de ledger inválida: {nome!r} {origem!r}")
    if len({n for n, _ in linhas_ledger}) != len(linhas_ledger):
        raise Erro("nome repetido no ledger")
    ordenadas = sorted(linhas_ledger, key=lambda r: r[0].encode())
    interno = hashlib.md5(",".join(f"{n}:{o}" for n, o in ordenadas).encode()).hexdigest()
    esperado = hashlib.md5(f"{len(ordenadas)}:{interno}".encode()).hexdigest()
    fp = [m for s, o, m in itens_fp if s == "ledger" and o == "public.schema_migrations"]
    if fp != [esperado]:
        raise Erro("o ledger não é o mesmo que o fingerprint do PROD registrou")
    return ordenadas


def literal(valor: str) -> str:
    return "'" + valor.replace("'", "''") + "'"


def montar(args: argparse.Namespace) -> str:
    planta, permissoes, contagem = ler_dump(args.dump)
    itens_fp = ler_fingerprint(args.fingerprint)
    ledger = ler_ledger(args.ledger, itens_fp)
    n_dev, md5_dev = args.estado_dev.split(":")
    if not n_dev.isdigit() or not re.fullmatch(r"[0-9a-f]{32}", md5_dev):
        raise Erro("--estado-dev deve ser <objetos>:<md5>")
    ensure = [m for s, o, m in itens_fp if s == "plataforma" and o == "event_trigger:ensure_rls"]
    if args.ensure_rls and not args.ensure_rls_def:
        raise Erro("--ensure-rls exige --ensure-rls-def '<evento>|<tags ou vazio>'")
    if args.ensure_rls and len(ensure) != 1:
        raise Erro("--ensure-rls pedido, mas o fingerprint do PROD não tem event_trigger:ensure_rls")

    chave = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(40))
    estado = trecho(KIT / "inventario_ro.sql", "estado")
    dependentes = trecho(KIT / "inventario_ro.sql", "dependentes")
    itens_sql = trecho(KIT / "fingerprint_ro.sql", "itens")
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    resumo = ", ".join(f"{t}={n}" for t, n in sorted(contagem.items()))

    out: list[str] = []
    w = out.append
    w("-- ============================================================================")
    w(f"-- recriar_dev.sql - GERADO por montar_recriacao.py em {agora}. Não editar à mão.")
    w("-- Recria o schema public do DEV igual ao do PROD numa transação única.")
    w(f"-- dump        sha256 {sha256(args.dump)}")
    w(f"-- fingerprint sha256 {sha256(args.fingerprint)} ({len(itens_fp)} linhas)")
    w(f"-- ledger      sha256 {sha256(args.ledger)} ({len(ledger)} linhas)")
    w(f"-- entradas do dump usadas: {resumo}")
    w(f"-- trava: public do DEV com {n_dev} objetos ({md5_dev}) e ledger antigo com {args.ledger_dev} linhas")
    w("-- Qualquer conferência que falhar desfaz tudo (ROLLBACK): nada fica pela metade.")
    w("--   PGSERVICEFILE=~/.config/pastorai/pg_service.conf psql service=pastorai_dev -X -q -f recriar_dev.sql")
    w("-- ============================================================================")
    w("\\set ON_ERROR_STOP on")
    w(f"\\restrict {chave}")
    w("BEGIN;")
    w("SET LOCAL lock_timeout = '5s';")
    w("SET LOCAL statement_timeout = '900s';")
    w("SET LOCAL search_path = pg_catalog, pg_temp;")
    w("SET LOCAL client_min_messages = warning;")
    w("")
    w("-- 1. TRAVA: só segue no DEV inspecionado (o PROD tem ledger com origem e outro estado).")
    w("DO $trava$")
    w("DECLARE n bigint; m text;")
    w("BEGIN")
    w("  IF current_user <> 'postgres' THEN RAISE EXCEPTION 'conexão inesperada: %', current_user; END IF;")
    w("  IF current_setting('server_version_num')::int / 10000 <> 17 THEN")
    w("    RAISE EXCEPTION 'versão inesperada: %', current_setting('server_version');")
    w("  END IF;")
    w("  IF to_regclass('public.schema_migrations') IS NULL THEN")
    w("    RAISE EXCEPTION 'ledger ausente: este não é o DEV inspecionado';")
    w("  END IF;")
    w("  IF EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'public.schema_migrations'::regclass")
    w("               AND attname = 'origem' AND attnum > 0 AND NOT attisdropped) THEN")
    w("    RAISE EXCEPTION 'o ledger já tem a coluna origem (formato do PROD): alvo errado, nada foi feito';")
    w("  END IF;")
    w("  SELECT count(*) INTO n FROM public.schema_migrations;")
    w(f"  IF n <> {int(args.ledger_dev)} THEN")
    w("    RAISE EXCEPTION 'ledger do DEV com % linhas (esperado " + str(int(args.ledger_dev)) + "): o DEV mudou', n;")
    w("  END IF;")
    w("  SELECT e.objetos, e.estado_public_md5 INTO n, m FROM (")
    w(estado)
    w("  ) AS e;")
    w(f"  IF n <> {int(n_dev)} OR m IS DISTINCT FROM {literal(md5_dev)} THEN")
    w("    RAISE EXCEPTION 'o schema public do DEV mudou desde a inspeção (% objetos, %)', n, m;")
    w("  END IF;")
    w("  IF EXISTS (")
    w(dependentes)
    w("  ) THEN")
    w("    RAISE EXCEPTION 'há objeto de fora de public que depende de public: revisar antes';")
    w("  END IF;")
    if args.ensure_rls:
        w("  IF EXISTS (SELECT 1 FROM pg_event_trigger WHERE evtname = 'ensure_rls') THEN")
        w("    RAISE EXCEPTION 'o DEV já tem ensure_rls: revisar antes';")
        w("  END IF;")
    w("END")
    w("$trava$;")
    w("")
    w("-- 2. APAGA os objetos de public. Ficam o schema, sua ACL e os default privileges do Supabase.")
    w("DO $apaga$")
    w("DECLARE nomes text[]; tipos text[];")
    w("BEGIN")
    w("  SELECT array_agg(format('%I.%I', 'public', c.relname)), array_agg(CASE c.relkind WHEN 'v' THEN 'VIEW'")
    w("           WHEN 'm' THEN 'MATERIALIZED VIEW' WHEN 'S' THEN 'SEQUENCE' WHEN 'f' THEN 'FOREIGN TABLE' ELSE 'TABLE' END)")
    w("    INTO nomes, tipos")
    w("    FROM pg_class AS c")
    w("   WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')")
    w("     AND NOT EXISTS (SELECT 1 FROM pg_depend AS d WHERE d.classid = 'pg_class'::regclass")
    w("                       AND d.objid = c.oid AND d.deptype = 'e');")
    w("  FOR i IN 1 .. coalesce(array_length(nomes, 1), 0) LOOP")
    w("    EXECUTE format('DROP %s IF EXISTS %s CASCADE', tipos[i], nomes[i]);")
    w("  END LOOP;")
    w("  SELECT array_agg(p.oid::regprocedure::text), array_agg(CASE p.prokind WHEN 'p' THEN 'PROCEDURE'")
    w("           WHEN 'a' THEN 'AGGREGATE' ELSE 'FUNCTION' END)")
    w("    INTO nomes, tipos")
    w("    FROM pg_proc AS p")
    w("   WHERE p.pronamespace = 'public'::regnamespace")
    w("     AND NOT EXISTS (SELECT 1 FROM pg_depend AS d WHERE d.classid = 'pg_proc'::regclass")
    w("                       AND d.objid = p.oid AND d.deptype = 'e')")
    w("     AND NOT EXISTS (SELECT 1 FROM pg_event_trigger AS e WHERE e.evtfoid = p.oid);")
    w("  FOR i IN 1 .. coalesce(array_length(nomes, 1), 0) LOOP")
    w("    EXECUTE format('DROP %s IF EXISTS %s CASCADE', tipos[i], nomes[i]);")
    w("  END LOOP;")
    w("  SELECT array_agg(format('%I.%I', 'public', t.typname)), array_agg(CASE t.typtype WHEN 'd' THEN 'DOMAIN' ELSE 'TYPE' END)")
    w("    INTO nomes, tipos")
    w("    FROM pg_type AS t")
    w("   WHERE t.typnamespace = 'public'::regnamespace")
    w("     AND (t.typtype IN ('e', 'd', 'r') OR (t.typtype = 'c' AND (SELECT c.relkind FROM pg_class AS c")
    w("                                                               WHERE c.oid = t.typrelid) = 'c'))")
    w("     AND NOT EXISTS (SELECT 1 FROM pg_depend AS d WHERE d.classid = 'pg_type'::regclass")
    w("                       AND d.objid = t.oid AND d.deptype = 'e');")
    w("  FOR i IN 1 .. coalesce(array_length(nomes, 1), 0) LOOP")
    w("    EXECUTE format('DROP %s IF EXISTS %s CASCADE', tipos[i], nomes[i]);")
    w("  END LOOP;")
    w("  IF EXISTS (SELECT 1 FROM pg_class AS c WHERE c.relnamespace = 'public'::regnamespace")
    w("               AND NOT EXISTS (SELECT 1 FROM pg_depend AS d WHERE d.classid = 'pg_class'::regclass")
    w("                                 AND d.objid = c.oid AND d.deptype = 'e'))")
    w("     OR EXISTS (SELECT 1 FROM pg_proc AS p WHERE p.pronamespace = 'public'::regnamespace")
    w("               AND NOT EXISTS (SELECT 1 FROM pg_depend AS d WHERE d.classid = 'pg_proc'::regclass")
    w("                                 AND d.objid = p.oid AND d.deptype = 'e')")
    w("               AND NOT EXISTS (SELECT 1 FROM pg_event_trigger AS e WHERE e.evtfoid = p.oid))")
    w("     OR EXISTS (SELECT 1 FROM pg_type AS t WHERE t.typnamespace = 'public'::regnamespace")
    w("               AND NOT EXISTS (SELECT 1 FROM pg_depend AS d WHERE d.classid = 'pg_type'::regclass")
    w("                                 AND d.objid = t.oid AND d.deptype = 'e')) THEN")
    w("    RAISE EXCEPTION 'public não ficou vazio depois de apagar';")
    w("  END IF;")
    w("END")
    w("$apaga$;")
    w("")
    w("-- 3. PLANTA DO PROD: dump só de schema, sem schema public, ACLs e default privileges.")
    out.extend(planta)
    w("")
    w("-- 4. ZERA o que os default privileges do Supabase deram na criação: a partir daqui")
    w("--    cada objeto fica só com o dono, e o passo 5 põe exatamente as permissões do PROD.")
    w("SET LOCAL search_path = pg_catalog, pg_temp;")
    w("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated, service_role;")
    w("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated, service_role;")
    w("REVOKE ALL ON ALL ROUTINES IN SCHEMA public FROM anon, authenticated, service_role;")
    w("")
    w("-- 5. PERMISSÕES EXATAS DO PROD (entradas ACL do dump).")
    out.extend(permissoes)
    w("")
    w(f"-- 6. LEDGER: as mesmas {len(ledger)} linhas e origens do PROD (applied_at = hoje, no DEV).")
    w("INSERT INTO public.schema_migrations (name, origem) VALUES")
    w(",\n".join(f"  ({literal(n)}, {literal(o)})" for n, o in ledger) + ";")
    if args.ensure_rls:
        evento, _, tags = args.ensure_rls_def.partition("|")
        if evento not in {"ddl_command_start", "ddl_command_end", "sql_drop", "table_rewrite"}:
            raise Erro("evento inválido em --ensure-rls-def")
        quando = ""
        if tags:
            lista = [t.strip() for t in tags.split(",")]
            if not all(re.fullmatch(r"[A-Z ]+", t) for t in lista):
                raise Erro("tags inválidas em --ensure-rls-def")
            quando = " WHEN TAG IN (" + ", ".join(literal(t) for t in lista) + ")"
        w("")
        w("-- 7. EVENT TRIGGER ensure_rls igual ao do PROD (liga a RLS em tabela nova de public).")
        w(f"CREATE EVENT TRIGGER ensure_rls ON {evento}{quando} EXECUTE FUNCTION public.rls_auto_enable();")
        w("DO $ensure$")
        w("BEGIN")
        w("  IF (SELECT md5(concat_ws('|', e.evtevent, e.evtenabled, e.evttags::text, e.evtfoid::regprocedure::text,")
        w("                            pg_get_userbyid(e.evtowner), md5(pg_get_functiondef(e.evtfoid))))")
        w("        FROM pg_event_trigger AS e WHERE e.evtname = 'ensure_rls')")
        w(f"     IS DISTINCT FROM {literal(ensure[0])} THEN")
        w("    RAISE EXCEPTION 'ensure_rls do DEV ficou diferente do PROD: nada foi gravado';")
        w("  END IF;")
        w("END")
        w("$ensure$;")
    w("")
    w("-- 8. CONFERÊNCIA: impressão digital objeto por objeto igual à do PROD.")
    w("SET LOCAL search_path = pg_catalog, pg_temp;")
    w("CREATE TEMP TABLE fp_prod (secao text, objeto text, md5 text, PRIMARY KEY (secao, objeto)) ON COMMIT DROP;")
    w("INSERT INTO pg_temp.fp_prod (secao, objeto, md5) VALUES")
    w(",\n".join(f"  ({literal(s)}, {literal(o)}, {literal(m)})" for s, o, m in itens_fp) + ";")
    w("CREATE TEMP TABLE fp_dev ON COMMIT DROP AS")
    w(itens_sql + ";")
    w("SELECT 'DIFERENTE' AS resultado, coalesce(p.secao, d.secao) AS secao, coalesce(p.objeto, d.objeto) AS objeto,")
    w("       p.md5 AS prod, d.md5 AS dev")
    w("  FROM pg_temp.fp_prod AS p FULL JOIN pg_temp.fp_dev AS d ON d.secao = p.secao AND d.objeto = p.objeto")
    w(" WHERE p.md5 IS DISTINCT FROM d.md5")
    w(" ORDER BY 2, 3;")
    w("DO $confere$")
    w("DECLARE n bigint;")
    w("BEGIN")
    w("  SELECT count(*) INTO n")
    w("    FROM pg_temp.fp_prod AS p FULL JOIN pg_temp.fp_dev AS d ON d.secao = p.secao AND d.objeto = p.objeto")
    w("   WHERE p.md5 IS DISTINCT FROM d.md5"
      "     AND (coalesce(p.secao, d.secao) <> 'plataforma'"
      + (" OR coalesce(p.objeto, d.objeto) = 'event_trigger:ensure_rls'" if args.ensure_rls else "") + ");")
    w("  IF n > 0 THEN")
    w("    RAISE EXCEPTION 'o DEV ficou diferente do PROD em % objeto(s) de public: nada foi gravado', n;")
    w("  END IF;")
    w("END")
    w("$confere$;")
    w("")
    w("SELECT 'DEV recriado igual ao PROD: ' || count(*) || ' objetos de public conferidos' AS resultado")
    w("  FROM pg_temp.fp_dev WHERE secao <> 'plataforma';")
    w("COMMIT;")
    w(f"\\unrestrict {chave}")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dump", type=pathlib.Path, required=True)
    ap.add_argument("--fingerprint", type=pathlib.Path, required=True)
    ap.add_argument("--ledger", type=pathlib.Path, required=True)
    ap.add_argument("--estado-dev", required=True)
    ap.add_argument("--ledger-dev", type=int, required=True)
    ap.add_argument("--ensure-rls", action="store_true")
    ap.add_argument("--ensure-rls-def", default="", help="'<evento>|<tags separadas por vírgula ou vazio>'")
    ap.add_argument("--saida", type=pathlib.Path, required=True)
    args = ap.parse_args(argv)
    try:
        sql = montar(args)
    except (Erro, StopIteration, ValueError) as exc:
        print(f"recusado: {exc}", file=sys.stderr)
        return 1
    args.saida.write_bytes(sql.encode("utf-8"))
    print(f"gerado: {args.saida} sha256 {sha256(args.saida)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
