"""SEC-4B: corrida TOCTOU na confirmação manual de evento.

Prova, contra um Postgres REAL e DESCARTÁVEL (``RLS_TEST_DATABASE_URL``), que
duas confirmações concorrentes do MESMO evento ``a_confirmar`` não podem ambas
vencer. O fix carrega o ``Event`` com ``SELECT ... FOR UPDATE`` na MESMA
transação da validação + gravação (ver ``app/routers/events.py::confirm_event``):

  * ``test_concurrent_confirm_first_wins_second_409`` — com o lock, a primeira
    confirmação vence; a segunda bloqueia no lock, é liberada, relê o evento já
    ``confirmado`` e cai no 409. Efeito único: exatamente 1 linha em
    ``event_notify_targets`` e um único ``confirmado_por``.
  * ``test_without_lock_double_confirms_regression`` — removendo o lock
    (monkeypatch dropando ``FOR UPDATE`` e sincronizando as duas leituras antes
    de qualquer escrita), o check-then-act deixa AS DUAS passarem e o efeito
    DOBRA (2 linhas em ``event_notify_targets``). É a prova de que o lock é o que
    fecha o caso — não um comentário.

Opt-in como a suíte RLS: sem ``RLS_TEST_DATABASE_URL`` dá skip LIMPO. Roda sob o
papel ``authenticated`` (NOBYPASSRLS) com contexto de tenant — o lock convive com
a RLS. Só toca o banco descartável; nada de runtime de produção.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

import app.routers.events as events_mod
from app.db.models import Base
from app.db.rls import set_tenant_context_for_igreja
from app.deps import CurrentUser
from app.routers.events import (
    ConfirmEventRequest,
    IndividualTargetInput,
    confirm_event,
)

# Fixture opt-in (skip limpo + guard de produção) reusada da suíte RLS. noqa:
# F401 — é usada como fixture do pytest (parâmetro de `engine`).
from tests.conftest_rls import rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration

# UUIDs fixos do cenário. Um único tenant: a corrida é INTRA-tenant (dois
# pastores/abas confirmando o mesmo evento ao mesmo tempo).
IGREJA = "0d0d0d0d-0000-0000-0000-00000000000d"
APP_USER = "0d0d0d0d-0000-0000-0000-0000000000a1"
PESSOA = "0d0d0d0d-0000-0000-0000-0000000000e1"
CONVERSA = "0d0d0d0d-0000-0000-0000-0000000000c1"
EVENT = "0d0d0d0d-0000-0000-0000-0000000000ef"

# Papel `authenticated` (NOBYPASSRLS), current_igreja_id() honrando o GUC
# app.tenant_igreja_id (réplica fiel da migration 20260624_090102) e RLS
# tenant-scoped nas tabelas que o confirm toca. Sem `{}` — string simples.
_SECURITY_SQL = """
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin noinherit nobypassrls;
  end if;
end $$;

create or replace function current_igreja_id()
returns uuid
language sql
stable
security definer
set search_path = public, pg_temp
as $fn$
  select coalesce(
    nullif(current_setting('app.tenant_igreja_id', true), '')::uuid,
    (
      select au.igreja_id
      from public.app_users au
      where au.clerk_user_id = nullif(
        coalesce(
          nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
          current_setting('request.jwt.claim.sub', true)
        ),
        ''
      )
      limit 1
    )
  );
$fn$;

grant usage on schema public to authenticated;
grant select, insert, update, delete on all tables in schema public to authenticated;

alter table events enable row level security;
drop policy if exists tenant_isolation on events;
create policy tenant_isolation on events
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

alter table event_notify_targets enable row level security;
drop policy if exists tenant_isolation on event_notify_targets;
create policy tenant_isolation on event_notify_targets
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

alter table conversations enable row level security;
drop policy if exists tenant_isolation on conversations;
create policy tenant_isolation on conversations
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());
"""

# Seed idempotente (roda como owner/BYPASSRLS). Uma igreja, um pastor, uma
# pessoa com conversa no WhatsApp (fonte do contato individual, D3) e o evento
# alvo em `a_confirmar`.
_SEED_SQL = f"""
insert into igrejas (id, nome)
  values ('{IGREJA}', 'Igreja TOCTOU') on conflict (id) do nothing;

insert into app_users (id, igreja_id, nome, email, clerk_user_id)
  values ('{APP_USER}', '{IGREJA}', 'Pastor', 'pastor@toctou.test', 'clerk-confirm')
  on conflict (id) do nothing;

insert into pessoas (id, igreja_id, nome, telefone)
  values ('{PESSOA}', '{IGREJA}', 'Contato TOCTOU', '5511999990000')
  on conflict (id) do nothing;

insert into conversations (id, igreja_id, pessoa_id, telefone)
  values ('{CONVERSA}', '{IGREJA}', '{PESSOA}', '5511999990000')
  on conflict (id) do nothing;

insert into events (id, igreja_id, titulo, status)
  values ('{EVENT}', '{IGREJA}', 'Evento a confirmar', 'a_confirmar')
  on conflict (id) do nothing;
"""


# Banco dedicado (não `public` do RLS_TEST_DATABASE_URL): a suíte RLS
# (test_rls_invariant) semeia um `pessoas` mínimo e um `create_all` do schema
# COMPLETO aqui deixaria `pessoas.telefone` NOT NULL, quebrando aquele seed se
# compartilhassem o mesmo banco. Um banco descartável próprio evita qualquer
# colisão em qualquer ordem de execução (inclusive no CI).
_TOCTOU_DB = "toctou_disposable"


def _drop_and_create_db(admin_url: object, db_name: str) -> None:
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f"drop database if exists {db_name} with (force)")
            conn.exec_driver_sql(f"create database {db_name}")
    finally:
        admin.dispose()


@pytest.fixture(scope="module")
def engine(rls_database_url: str) -> Iterator[Engine]:  # noqa: F811
    """Postgres descartável DEDICADO com o schema real (metadata) + RLS/role."""
    base = make_url(rls_database_url)
    admin_url = base.set(database="postgres")
    _drop_and_create_db(admin_url, _TOCTOU_DB)
    eng = create_engine(
        base.set(database=_TOCTOU_DB), pool_size=5, max_overflow=5, future=True
    )
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.exec_driver_sql(_SECURITY_SQL)
    try:
        yield eng
    finally:
        eng.dispose()
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
        try:
            with admin.connect() as conn:
                conn.exec_driver_sql(
                    f"drop database if exists {_TOCTOU_DB} with (force)"
                )
        finally:
            admin.dispose()


@pytest.fixture
def factory(engine: Engine) -> Callable[[], Session]:
    """Fábrica espelhando a Session do app (expire_on_commit=False)."""
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


@pytest.fixture
def fresh_event(engine: Engine) -> None:
    """(Re)semeia e volta o evento para `a_confirmar`, zerando efeitos anteriores.

    Torna cada teste independente da ordem — a corrida sempre parte do mesmo
    estado limpo.
    """
    with engine.begin() as conn:
        conn.exec_driver_sql(_SEED_SQL)
        conn.execute(
            text("delete from event_notify_targets where event_id = :e"),
            {"e": EVENT},
        )
        conn.execute(
            text(
                "update events set status='a_confirmar', confirmado_em=null, "
                "confirmado_por=null, canal=null, publico_alvo=null, "
                "antecedencia_horas=null, mensagem_confirmacao=null, "
                "notificar_em=null, notificado_em=null where id = :e"
            ),
            {"e": EVENT},
        )


def _current_user() -> CurrentUser:
    return CurrentUser(
        app_user_id=APP_USER,
        clerk_user_id="clerk-confirm",
        igreja_id=IGREJA,
        email="pastor@toctou.test",
        nome="Pastor",
        roles=frozenset({"pastor"}),
    )


def _run_two_confirms(
    factory: Callable[[], Session], *, barrier_before: bool
) -> dict[str, tuple[str, object]]:
    """Dispara duas confirmações concorrentes do mesmo evento.

    Cada thread tem sua própria Session/conexão e contexto de tenant. Com
    `barrier_before=True`, ambas chegam juntas ao `confirm` (maximiza a
    contenção real do lock). O resultado por thread é ('ok', status) |
    ('http', code) | ('err', repr).
    """
    results: dict[str, tuple[str, object]] = {}
    barrier = threading.Barrier(2, timeout=20)
    payload = ConfirmEventRequest(contatos=[IndividualTargetInput(pessoaId=PESSOA)])

    def worker(name: str) -> None:
        session = factory()
        try:
            set_tenant_context_for_igreja(session, IGREJA)
            if barrier_before:
                barrier.wait()
            out = confirm_event(
                event_id=EVENT,
                payload=payload,
                db=session,
                current_user=_current_user(),
            )
            results[name] = ("ok", out.status)
        except HTTPException as exc:
            results[name] = ("http", exc.status_code)
        except BaseException as exc:  # noqa: BLE001 - captura p/ o join não pendurar
            results[name] = ("err", repr(exc))
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(n,)) for n in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return results


def _event_final_state(engine: Engine) -> tuple[str, object, int]:
    """(status, confirmado_por, nº de targets) lidos como owner (fora da RLS)."""
    with engine.begin() as conn:
        status_row, confirmado_por = conn.execute(
            text("select status, confirmado_por from events where id = :e"),
            {"e": EVENT},
        ).one()
        target_count = conn.execute(
            text("select count(*) from event_notify_targets where event_id = :e"),
            {"e": EVENT},
        ).scalar_one()
    return status_row, confirmado_por, target_count


def test_concurrent_confirm_first_wins_second_409(
    factory: Callable[[], Session], fresh_event: None, engine: Engine
) -> None:
    """Com o `SELECT ... FOR UPDATE`: uma vence, a outra recebe 409; efeito único."""
    results = _run_two_confirms(factory, barrier_before=True)

    assert len(results) == 2, results
    oks = [v for v in results.values() if v[0] == "ok"]
    http = [v for v in results.values() if v[0] == "http"]
    errs = [v for v in results.values() if v[0] == "err"]

    assert not errs, f"nenhuma thread deveria estourar erro inesperado: {results}"
    assert len(oks) == 1, f"exatamente uma confirmação deve vencer: {results}"
    assert oks[0][1] == "confirmado"
    assert len(http) == 1 and http[0][1] == 409, f"a outra deve ser 409: {results}"

    status_final, confirmado_por, target_count = _event_final_state(engine)
    assert status_final == "confirmado"
    assert confirmado_por is not None
    assert target_count == 1, f"efeito deve ser único: {target_count} targets"


def test_without_lock_double_confirms_regression(
    factory: Callable[[], Session],
    fresh_event: None,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sem o lock, o check-then-act deixa as DUAS vencerem e dobra o efeito.

    Removemos apenas o lock (o downstream — guard, update, insert, commit — é o
    código real) e sincronizamos as duas leituras antes de qualquer escrita.
    """
    barrier = threading.Barrier(2, timeout=20)
    real_get_event = events_mod._get_event

    def _get_event_no_lock(
        db: Session,
        current_user: CurrentUser,
        event_id: str,
        *,
        for_update: bool = False,
    ) -> object:
        event = real_get_event(db, current_user, event_id, for_update=False)
        # Ambas as threads leem `a_confirmar` ANTES de qualquer gravação.
        barrier.wait()
        return event

    monkeypatch.setattr(events_mod, "_get_event", _get_event_no_lock)

    results = _run_two_confirms(factory, barrier_before=False)

    assert len(results) == 2, results
    oks = [v for v in results.values() if v[0] == "ok"]
    _status, _confirmado_por, target_count = _event_final_state(engine)

    assert len(oks) == 2, f"sem lock as duas atravessam o guard: {results}"
    assert target_count == 2, f"sem lock o efeito dobra: esperado 2, veio {target_count}"
