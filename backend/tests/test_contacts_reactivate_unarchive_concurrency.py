"""FECH-05/FECH-06 — concorrência real dos endpoints administrativos de volta.

`reactivate_communications` e `unarchive_contact` leem a Pessoa com
``SELECT ... FOR UPDATE`` (``with_for_update()``) antes de decidir o estado.
Sem o lock, duas requisições simultâneas passam juntas pela verificação
(optout=True / arquivada) e AMBAS gravam efeito: dois ConsentRecords de
reoptin ou dois eventos 'reativada'. Com o lock, a transação perdedora só lê
o estado APÓS o commit da vencedora e cai no ramo previsto pelo contrato:
``ja_ativa=True`` no re-optin, 409 "Pessoa não está arquivada" no unarchive.

Só um Postgres REAL prova isso (FOR UPDATE + transações concorrentes de
conexões independentes) — FakeSession não executa SQL. Mesmo padrão opt-in
das demais suítes de corrida (``RLS_TEST_DATABASE_URL``; skip limpo sem ela).
As funções dos endpoints são chamadas diretamente com sessões independentes e
um ``CurrentUser`` construído — RBAC (require_role) e HTTP são exercitados nos
testes offline de FakeSession; aqui a prova é o comportamento transacional.
"""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

# Importar session.py registra (uma vez) o listener after_begin do seam de
# tenant — paridade com produção. Sessões não marcadas ⇒ no-op.
import app.db.session  # noqa: F401
from app.db.models import AppUser, Base, Igreja, Pessoa
from app.deps import CurrentUser
from app.routers.contacts import reactivate_communications, unarchive_contact

# Fixture opt-in (guard de produção + skip sem a env var). noqa: F401 — fixture
# do pytest usada por injeção, não importação "morta".
from tests.conftest_rls import rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration

_SCHEMA = "fech2_concurrency"
_IGREJA = uuid.UUID("3c3c3c3c-0000-0000-0000-00000000cc01")
_ADMIN = uuid.UUID("3c3c3c3c-0000-0000-0000-00000000ad01")


@pytest.fixture
def engine_fx(rls_database_url: str) -> Iterator[Engine]:
    """Engine contra o Postgres descartável, schema próprio recriado do zero.

    ``Base.metadata.create_all`` materializa ``consent_records.ator_id`` (novo
    no model, migration 20260720_191143) e ``pessoa_arquivamento_evento`` com
    o CHECK do enum — as mesmas definições das migrations.
    """
    engine = create_engine(
        rls_database_url,
        future=True,
        connect_args={"options": f"-c search_path={_SCHEMA}"},
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"drop schema if exists {_SCHEMA} cascade; create schema {_SCHEMA};"
        )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade;")
        engine.dispose()


def _factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def _current_user() -> CurrentUser:
    return CurrentUser(
        app_user_id=str(_ADMIN),
        clerk_user_id="clerk-admin",
        igreja_id=str(_IGREJA),
        email="admin@igreja.test",
        nome="Admin",
        roles=frozenset({"admin"}),
    )


def _seed(factory: sessionmaker, *, optout: bool, arquivada: bool) -> uuid.UUID:
    session = factory()
    try:
        session.add(Igreja(id=_IGREJA, nome="Igreja"))
        session.flush()
        session.add(
            AppUser(id=_ADMIN, igreja_id=_IGREJA, clerk_user_id="clerk-admin")
        )
        pessoa_id = uuid.uuid4()
        session.add(
            Pessoa(
                id=pessoa_id,
                igreja_id=_IGREJA,
                nome="Pessoa Corrida",
                telefone="11912340001",
                optout=optout,
                arquivada_em=(
                    dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc)
                    if arquivada
                    else None
                ),
                arquivada_motivo="Mudou de cidade" if arquivada else None,
            )
        )
        session.commit()
        return pessoa_id
    finally:
        session.close()


def _run_pair(factory: sessionmaker, target) -> dict[int, object]:
    """Duas sessões independentes chamam `target(session)` em paralelo.

    Barreira maximiza a sobreposição; join com timeout prova ausência de
    deadlock (um FOR UPDATE esquecido em aberto travaria a segunda thread).
    """
    barrier = threading.Barrier(2)
    out: dict[int, object] = {}

    def worker(idx: int) -> None:
        session = factory()
        try:
            barrier.wait(timeout=15)
            try:
                out[idx] = target(session)
            except HTTPException as exc:
                out[idx] = exc
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert all(not t.is_alive() for t in threads), "deadlock: thread presa no lock"
    assert len(out) == 2, f"thread morreu sem resultado: {out}"
    return out


def _count(factory: sessionmaker, sql: str, pessoa_id: uuid.UUID) -> int:
    session = factory()
    try:
        return int(
            session.execute(text(sql), {"p": pessoa_id}).scalar_one()
        )
    finally:
        session.close()


def test_concurrent_reactivations_yield_one_consent(engine_fx: Engine) -> None:
    """Duas reativações simultâneas: UMA efetiva, UM ConsentRecord, a outra
    observa ja_ativa=True. Sem o with_for_update, ambas leriam optout=True e
    gravariam dois consentimentos de reoptin."""
    factory = _factory(engine_fx)
    pessoa_id = _seed(factory, optout=True, arquivada=False)

    out = _run_pair(
        factory,
        lambda session: reactivate_communications(
            str(pessoa_id), db=session, current_user=_current_user()
        ),
    )

    responses = list(out.values())
    assert all(not isinstance(r, HTTPException) for r in responses), responses
    ja_ativa = sorted(r.ja_ativa for r in responses)
    # Exatamente uma efetiva (False) e uma idempotente pós-lock (True).
    assert ja_ativa == [False, True], responses

    assert (
        _count(
            factory,
            "select count(*) from consent_records where pessoa_id = :p",
            pessoa_id,
        )
        == 1
    )
    # Autoria durável no registro persistido (não só na resposta HTTP).
    session = factory()
    try:
        ator = session.execute(
            text("select ator_id from consent_records where pessoa_id = :p"),
            {"p": pessoa_id},
        ).scalar_one()
    finally:
        session.close()
    assert ator == _ADMIN
    assert (
        _count(
            factory,
            "select count(*) from pessoas where id = :p and optout = false",
            pessoa_id,
        )
        == 1
    )


def test_concurrent_unarchives_yield_one_event(engine_fx: Engine) -> None:
    """Dois unarchives simultâneos: UM evento 'reativada'; o segundo observa a
    pessoa já reativada e recebe o 409 do contrato atual. Sem o lock, ambos
    leriam arquivada e gravariam dois eventos."""
    factory = _factory(engine_fx)
    pessoa_id = _seed(factory, optout=False, arquivada=True)

    out = _run_pair(
        factory,
        lambda session: unarchive_contact(
            str(pessoa_id), db=session, current_user=_current_user()
        ),
    )

    responses = list(out.values())
    winners = [r for r in responses if not isinstance(r, HTTPException)]
    losers = [r for r in responses if isinstance(r, HTTPException)]
    assert len(winners) == 1 and len(losers) == 1, responses
    assert winners[0].arquivada is False
    assert losers[0].status_code == 409
    assert losers[0].detail == "Pessoa não está arquivada"

    assert (
        _count(
            factory,
            "select count(*) from pessoa_arquivamento_evento "
            "where pessoa_id = :p and acao = 'reativada'",
            pessoa_id,
        )
        == 1
    )
    assert (
        _count(
            factory,
            "select count(*) from pessoas where id = :p and arquivada_em is null",
            pessoa_id,
        )
        == 1
    )
