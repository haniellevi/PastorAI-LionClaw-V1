"""SEC-4B-A: prova de concorrência real do lock pessimista na aprovação.

O TOCTOU vivia em ``cell_requests_service.approve``: o router lia a
``celula_solicitacao`` SEM trava e o serviço revalidava o status em memória
antes de aplicar. Duas aprovações simultâneas liam o mesmo estado `aguardando`
e ambas aplicavam o payload + registravam a decisão. A correção trava a linha
com ``SELECT ... FOR UPDATE`` (``db.refresh(..., with_for_update=True)``) na
MESMA transação que valida → aplica → registra → commita.

Só um Postgres REAL prova o lock entre duas conexões — SQLite/FakeSession não
têm ``FOR UPDATE``. Por isso a suíte é opt-in via ``RLS_TEST_DATABASE_URL``
(mesmo guard de produção da suíte RLS: aborta se a URL cheirar a DEV/PROD) e dá
skip LIMPO sem ela. O schema é criado do zero a partir dos modelos ORM reais
(as mesmas colunas que ``approve`` lê/escreve), num banco DESCARTÁVEL.

Mapa:
  * test_approve_concurrent_one_wins_other_gets_409 — a prova: duas sessões
    independentes aprovam a MESMA solicitação em paralelo; uma vence (200), a
    outra espera o lock, relê o estado já decidido e recebe 409; payload e
    auditoria aplicados UMA vez.
  * test_toctou_reproduces_without_the_lock — regressão: neutraliza a trava
    (refresh vira no-op, modelando o approve pré-SEC-4B) e mostra o MESMO
    cenário duplicando a decisão — i.e., o teste acima falharia sem o lock.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

# Importar session.py registra (uma vez) o listener after_begin do seam de
# tenant — paridade com produção. Como as sessões deste teste NÃO são marcadas
# (não chamam mark_tenant_scoped), o listener é no-op para elas: rodam no papel
# de conexão. O FOR UPDATE é ortogonal à RLS, então o lock é provado do mesmo
# jeito (a suíte RLS dedicada já cobre o isolamento por tenant).
import app.db.session  # noqa: F401
from app.db.models import Base, Celula, CelulaSolicitacao, Igreja, Pessoa
from app.services import cell_requests_service

# Fixture opt-in (guard de produção + skip sem a env var). noqa: F401 — é uma
# fixture do pytest usada por injeção, não uma importação "morta".
from tests.conftest_rls import rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration

# IDs fixos do cenário (uuids válidos, estáveis para asserts).
_IGREJA = uuid.UUID("0a0a0a0a-0000-0000-0000-0000000000aa")
_PASTOR = uuid.UUID("0b0b0b0b-0000-0000-0000-0000000000bb")
_CELL = uuid.UUID("0c0c0c0c-0000-0000-0000-0000000000cc")
_SOL = uuid.UUID("0d0d0d0d-0000-0000-0000-0000000000dd")


# ---------------------------------------------------------------------------
# Schema + seed no banco descartável
# ---------------------------------------------------------------------------
# Schema dedicado (via search_path) para NÃO colidir com o `public` que a suíte
# de integração RLS provisiona no MESMO banco descartável. gen_random_uuid()/now()
# vivem em pg_catalog (sempre no path), então não precisamos de `public` aqui.
_SCHEMA = "sec4b_concurrency"


@pytest.fixture
def approval_engine(rls_database_url: str) -> Iterator[Engine]:
    """Engine contra o Postgres descartável, com schema próprio recriado do zero.

    Todo o ORM cai em ``sec4b_concurrency`` (search_path); ``drop schema ...
    cascade`` isola cada teste sem tocar no ``public`` da suíte RLS. ``create_all``
    materializa as tabelas reais dos modelos (colunas idênticas às que ``approve``
    lê/escreve).
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
    # expire_on_commit=False espelha o get_session_factory() de produção.
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def _seed(factory: sessionmaker) -> None:
    session = factory()
    try:
        session.add(Igreja(id=_IGREJA, nome="Igreja Concorrência"))
        session.flush()
        session.add(Pessoa(id=_PASTOR, igreja_id=_IGREJA, nome="Central", telefone="0"))
        session.flush()
        session.add(
            Celula(
                id=_CELL,
                igreja_id=_IGREJA,
                nome="Célula",
                lider_id=_PASTOR,
                cobertura_espiritual="Rede",
                dia_reuniao="quinta",
            )
        )
        session.flush()
        session.add(
            CelulaSolicitacao(
                id=_SOL,
                igreja_id=_IGREJA,
                celula_id=_CELL,
                solicitante_id=_PASTOR,
                tipo="alterar_dia",
                status="aguardando",
                payload_proposto={"dia_reuniao": "sexta"},
            )
        )
        session.commit()
    finally:
        session.close()


def _run_two_approvals(factory: sessionmaker) -> dict[int, tuple]:
    """Duas sessões independentes aprovam a MESMA solicitação em paralelo.

    Cada thread lê solicitação+célula SEM trava (como o router faz) e só então
    chama ``approve`` — a barreira maximiza a sobreposição real da corrida.
    Resultado por thread: ``('ok', status)`` ou ``('http', codigo)``.
    """
    barrier = threading.Barrier(2)
    out: dict[int, tuple] = {}

    def worker(idx: int) -> None:
        session = factory()
        try:
            solicitacao = session.get(CelulaSolicitacao, _SOL)
            cell = session.get(Celula, _CELL)
            barrier.wait(timeout=15)
            res = cell_requests_service.approve(
                session,
                solicitacao=solicitacao,
                cell=cell,
                actor_pessoa_id=_PASTOR,
                approver_app_user_id=None,
                idempotency_key=None,
            )
            out[idx] = ("ok", res.status)
        except HTTPException as exc:
            out[idx] = ("http", exc.status_code)
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    return out


def _counts(factory: sessionmaker) -> tuple[int, str, str]:
    """(eventos 'aprovada', dia_reuniao aplicado, status da solicitação)."""
    session = factory()
    try:
        eventos = session.execute(
            text(
                "select count(*) from celula_solicitacao_evento "
                "where acao = 'aprovada' and solicitacao_id = :sid"
            ),
            {"sid": _SOL},
        ).scalar_one()
        dia = session.execute(
            text("select dia_reuniao from celulas where id = :cid"), {"cid": _CELL}
        ).scalar_one()
        status = session.execute(
            text("select status from celula_solicitacao where id = :sid"), {"sid": _SOL}
        ).scalar_one()
        return int(eventos), dia, status
    finally:
        session.close()


# ---------------------------------------------------------------------------
# A prova
# ---------------------------------------------------------------------------
def test_approve_concurrent_one_wins_other_gets_409(approval_engine: Engine) -> None:
    factory = _factory(approval_engine)
    _seed(factory)

    out = _run_two_approvals(factory)

    # Exatamente uma vence (200/aprovada); a outra, após aguardar o lock e reler
    # o estado já decidido, recebe 409. (Quem vence varia — é corrida real.)
    assert sorted(out.values()) == [("http", 409), ("ok", "aprovada")], out

    eventos, dia, status = _counts(factory)
    assert eventos == 1, f"decisão deve ser registrada UMA vez; veio {eventos}"
    assert dia == "sexta"  # payload aplicado uma única vez
    assert status == "aprovada"


def test_toctou_reproduces_without_the_lock(
    approval_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regressão: sem o ``FOR UPDATE`` o TOCTOU volta.

    Neutraliza a trava (``Session.refresh`` vira no-op — modela o ``approve``
    pré-SEC-4B, que revalidava o status em memória sem reler a linha sob lock).
    As duas aprovações passam o check com o estado obsoleto e ambas aplicam → a
    decisão é registrada DUAS vezes. Prova que o teste acima falharia sem o lock.
    """
    monkeypatch.setattr(Session, "refresh", lambda self, obj, **kwargs: None)

    factory = _factory(approval_engine)
    _seed(factory)

    out = _run_two_approvals(factory)

    # Sem o lock ambas "vencem" e a auditoria de aprovação é duplicada.
    assert sorted(out.values()) == [("ok", "aprovada"), ("ok", "aprovada")], out
    eventos, _dia, _status = _counts(factory)
    assert eventos == 2, f"sem o lock a decisão duplica; veio {eventos}"
