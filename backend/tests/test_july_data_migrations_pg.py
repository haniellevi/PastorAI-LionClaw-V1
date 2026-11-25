"""Functional characterization of the two July data migrations.

Only a disposable PostgreSQL cluster is supported. Each case gets a fresh
database with a minimal synthetic business schema and the historical trigger
definitions, not the complete release schema or any providers.
"""

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql
from sqlalchemy.engine import make_url

from scripts import migrate
from tests.conftest_rls import IGREJA_A, rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration

M1 = "20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql"
M2 = "20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql"
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

DDL = """
create type pessoa_tipo as enum ('contato','visitante','membro','lider','pastor','discipulo');
create type pessoa_etapa as enum ('ganhar','consolidar','discipular','enviar');
create type pessoa_subetapa as enum ('novo_contato','visitante','em_consolidacao','consolidado');
create table igrejas (id uuid primary key, plano text);
create table pessoas (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null references igrejas(id),
  nome text not null, telefone text not null, tipo pessoa_tipo,
  arquivada_em timestamptz, sem_interesse boolean not null default false,
  apto_lider boolean not null default false,
  presencas_celula integer not null default 0,
  aceitou_jesus boolean not null default false,
  etapa pessoa_etapa, subetapa pessoa_subetapa,
  unique (igreja_id, id)
);
create unique index uq_pessoas_telefone_ativa on pessoas (igreja_id, telefone)
  where arquivada_em is null;
create table celulas (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null references igrejas(id),
  ativo boolean not null default true, lider_id uuid references pessoas(id),
  unique (igreja_id, id)
);
create table celula_membro (
  pessoa_id uuid not null, igreja_id uuid not null, celula_id uuid not null,
  ativo boolean not null default true,
  foreign key (igreja_id, pessoa_id) references pessoas(igreja_id, id),
  foreign key (igreja_id, celula_id) references celulas(igreja_id, id)
);
create table whatsapp_connections (
  igreja_id uuid primary key references igrejas(id), numero text, status text
);
create table planos (
  codigo text primary key, ativo boolean not null, preco_mensal numeric(10,2) not null,
  limite_pessoas integer
);
create table subscriptions (
  id uuid primary key default gen_random_uuid(), igreja_id uuid not null unique references igrejas(id),
  plano text not null, pessoas integer, limite integer, asaas_subscription_id text
);
create table billing_plan_change_operations (
  id uuid primary key default gen_random_uuid(),
  subscription_id uuid not null references subscriptions(id),
  asaas_subscription_id text not null, from_plano text not null, to_plano text not null,
  to_preco numeric(10,2) not null, to_limite integer, to_descricao text,
  origin text not null, status text not null, notify_status text not null,
  created_at timestamptz not null default now()
);
create unique index billing_plan_change_operations_open_uq
  on billing_plan_change_operations(subscription_id)
  where status in ('prepared','processing','reconciling');
create table schema_migrations (name text primary key);
"""


@pytest.fixture
def db(rls_database_url):
    """Create and remove only our freshly named database (CI uses localhost)."""
    base = make_url(rls_database_url)
    if base.host not in {"127.0.0.1", "localhost", "::1"} or base.query:
        raise RuntimeError("July migration test requires a local disposable database")
    name = f"july_data_test_{uuid4().hex}"
    admin_url = base.set(drivername="postgresql", database="postgres")
    test_url = admin_url.set(database=name)
    admin = psycopg2.connect(admin_url.render_as_string(hide_password=False))
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("create database {} template template0").format(sql.Identifier(name)))
        try:
            conn = psycopg2.connect(test_url.render_as_string(hide_password=False))
            try:
                with conn, conn.cursor() as cur:
                    cur.execute(DDL)
                    cur.execute("insert into igrejas(id) values (%s)", (IGREJA_A,))
                yield conn
            finally:
                conn.close()
        finally:
            with admin.cursor() as cur:
                cur.execute(sql.SQL("drop database {}").format(sql.Identifier(name)))
    finally:
        admin.close()


def query(conn, statement, params=None):
    with conn, conn.cursor() as cur:
        cur.execute(statement, params)
        if cur.description is not None:
            return cur.fetchall()


def person(conn, tipo, tel="00911110000", *, igreja=IGREJA_A, archived=False,
           csim=False, apto=False, presencas=0, aceitou=False, subetapa="novo_contato"):
    # Seed pre-existing historical rows before installing the triggers.
    return query(
        conn,
        """insert into pessoas
           (igreja_id,nome,telefone,tipo,arquivada_em,sem_interesse,apto_lider,
            presencas_celula,aceitou_jesus,etapa,subetapa)
           values (%s,'Pessoa fictícia',%s,%s,case when %s then now() end,%s,%s,
                   %s,%s,'ganhar',%s) returning id""",
        (igreja, tel, tipo, archived, csim, apto, presencas, aceitou, subetapa),
    )[0][0]


def cell(conn, pessoa, *, igreja=IGREJA_A, cell_active=True, link_active=True, leader=False):
    cid = query(conn, "insert into celulas(igreja_id,ativo,lider_id) values (%s,%s,%s) returning id",
                (igreja, cell_active, pessoa if leader else None))[0][0]
    if not leader:
        query(conn, "insert into celula_membro values (%s,%s,%s,%s)",
              (pessoa, igreja, cid, link_active))


def connection(conn, number, status="online"):
    query(conn, "insert into whatsapp_connections values (%s,%s,%s)", (IGREJA_A, number, status))


def state(conn, pessoa):
    return query(conn, "select tipo,etapa,subetapa from pessoas where id=%s", (pessoa,))[0]


def install_triggers(conn):
    # Exact definitions, without executing unrelated DDL or permission changes.
    pipeline = (MIGRATIONS / "0004_triggers.sql").read_text(encoding="utf-8")
    start = pipeline.index("create or replace function fn_promote_pipeline()")
    end = pipeline.index("execute function fn_promote_pipeline();", start)
    query(conn, pipeline[start:end + len("execute function fn_promote_pipeline();")])
    billing = (MIGRATIONS / "20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade.sql").read_text(encoding="utf-8")
    start = billing.index("create or replace function public.fn_subscription_autoupgrade()")
    end = billing.index("$$;", start)
    query(conn, billing[start:end + len("$$;")])
    trigger = (MIGRATIONS / "20260808_001059_billing_count_active_members.sql").read_text(encoding="utf-8")
    start = trigger.index("create trigger trg_subscription_autoupgrade")
    end = trigger.index("execute function fn_subscription_autoupgrade();", start)
    query(conn, trigger[start:end + len("execute function fn_subscription_autoupgrade();")])


def apply(conn, name):
    assert migrate.cmd_apply(conn, name, transactional=True, lock_timeout=2000) == 0
    assert query(conn, "select name from schema_migrations where name=%s", (name,)) == [(name,)]


@pytest.mark.parametrize(
    "tipo, archived, csim, cell_active, link_active, current",
    [
        ("contato", False, False, True, True, "membro"),
        ("contato", False, False, True, None, "contato"),
        ("visitante", False, False, True, False, "visitante"),
        # Observed historical classification; the business eligibility question
        # (archive, inactive cell and CSIM) is deliberately left for owner review.
        ("visitante", True, False, True, True, "membro"),
        ("contato", False, False, False, True, "membro"),
        ("visitante", False, True, True, True, "membro"),
    ],
    ids=["active", "no-link", "inactive-link", "archived", "inactive-cell", "csim"],
)
def test_m1_classification(db, tipo, archived, csim, cell_active, link_active, current):
    pid = person(db, tipo, archived=archived, csim=csim)
    if link_active is not None:
        cell(db, pid, cell_active=cell_active, link_active=link_active)
    install_triggers(db)
    apply(db, M1)
    assert state(db, pid) == (current, "ganhar", "novo_contato")
    assert query(db, "select arquivada_em is not null,sem_interesse from pessoas where id=%s", (pid,)) == [
        (archived, csim)
    ]


@pytest.mark.parametrize(
    "number, phone, archived, status, link_active, leader, current",
    [
        ("550091110000", "+55 (00) 99111-0000", False, "online", None, False, "contato"),
        ("550091110000", "0091110000", False, "online", False, False, "contato"),
        ("550091110000", "5500991110000", False, "online", None, False, "contato"),
        ("550091110000", "01991110000", False, "online", None, False, "membro"),
        ("550091110000", "---", False, "online", None, False, "membro"),
        ("550091110000", "00991110000", False, "online", True, False, "membro"),
        # Historical characterization only: archived records, ambiguous phone
        # identity and offline leadership cases still require business review.
        ("550091110000", "00991110000", True, "online", None, False, "contato"),
        ("0032224444", "00932224444", False, "online", None, False, "contato"),
        ("550091110000", "00991110000", False, "offline", None, True, "contato"),
    ],
    ids=["masked", "legacy-inactive-link", "country-code", "different-ddd", "empty-canonical", "active-member",
         "archived", "landline-ambiguity", "offline-cell-leader"],
)
def test_m2_classification(db, number, phone, archived, status, link_active, leader, current):
    pid = person(db, "membro", phone, archived=archived, apto=leader)
    connection(db, number, status)
    if link_active is not None or leader:
        cell(db, pid, link_active=link_active, leader=leader)
    install_triggers(db)
    apply(db, M2)
    assert state(db, pid) == (current, "ganhar", "novo_contato")
    assert query(db, "select arquivada_em is not null,apto_lider from pessoas where id=%s", (pid,)) == [
        (archived, leader)
    ]


@pytest.mark.parametrize("tipo", [None, "contato", "visitante", "discipulo", "lider", "pastor"])
def test_m2_preserves_other_classifications(db, tipo):
    pid = person(db, tipo, "00991110000")
    connection(db, "00991110000")
    install_triggers(db)
    apply(db, M2)
    assert state(db, pid) == (tipo, "ganhar", "novo_contato")


def test_pipeline_updates_both_migrations(db):
    visitor = person(db, "visitante", "00911112222", presencas=3, subetapa="visitante")
    cell(db, visitor)
    official = person(db, "membro", "00991110000", aceitou=True)
    connection(db, "00991110000")
    install_triggers(db)
    assert state(db, visitor) == ("visitante", "ganhar", "visitante")
    assert state(db, official) == ("membro", "ganhar", "novo_contato")
    apply(db, M1)
    assert state(db, visitor) == ("membro", "consolidar", "em_consolidacao")
    assert state(db, official) == ("membro", "ganhar", "novo_contato")
    apply(db, M2)
    assert state(db, visitor) == ("membro", "consolidar", "em_consolidacao")
    assert state(db, official) == ("contato", "consolidar", "em_consolidacao")


@pytest.mark.parametrize("plan, remote_id, after_plan, operations", [
    ("ate_100", None, "101_200", []),
    ("ate_100", "sub_sintetico", "ate_100", [("prepared", "autoupgrade", "101_200")]),
    ("cortesia", None, "cortesia", []),
], ids=["local-paid", "prepared-only", "complimentary"])
def test_billing_sequence(db, plan, remote_id, after_plan, operations):
    query(db, """insert into planos values
        ('ate_100',true,99,2),('101_200',true,199,4),('cortesia',true,0,2)""")
    query(db, "update igrejas set plano=%s where id=%s", (plan, IGREJA_A))
    query(db, """insert into subscriptions (igreja_id,plano,pessoas,limite,asaas_subscription_id)
                 values (%s,%s,2,2,%s)""", (IGREJA_A, plan, remote_id))
    official = person(db, "membro", "00991110000")
    person(db, "membro", "00922223333")
    candidate = person(db, "contato", "00933334444")
    cell(db, candidate)
    archived = person(db, "visitante", "00944445555", archived=True)
    csim = person(db, "visitante", "00955556666", csim=True)
    cell(db, archived)
    cell(db, csim)
    connection(db, "00991110000")
    install_triggers(db)

    def billing_state():
        return query(db, """select s.pessoas,s.plano,i.plano,s.limite
                          from subscriptions s join igrejas i on i.id=s.igreja_id""")

    def local_operations():
        return query(db, "select status,origin,to_plano from billing_plan_change_operations")

    assert billing_state() == [(2, plan, plan, 2)]
    assert local_operations() == []
    apply(db, M1)
    assert state(db, candidate)[0] == state(db, archived)[0] == state(db, csim)[0] == "membro"
    limit = 4 if after_plan == "101_200" else 2
    assert billing_state() == [(3, after_plan, after_plan, limit)]
    assert local_operations() == operations
    apply(db, M2)
    assert state(db, official)[0] == "contato"
    # Current behavior: the count falls back but a prior local upgrade or
    # prepared intent remains, despite no provider being present or called.
    assert billing_state() == [(2, after_plan, after_plan, limit)]
    assert local_operations() == operations
