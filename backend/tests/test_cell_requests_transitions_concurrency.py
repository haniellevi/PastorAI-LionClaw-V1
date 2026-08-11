"""SEC-4B-C: prova de concorrência real do lock nas transições irmãs.

SEC-4B-A fechou o TOCTOU só em ``approve``. As transições irmãs de decisão da
mesma ``celula_solicitacao`` — ``reject``, ``request_adjustment``, ``resubmit`` e
``cancel`` — liam o estado SEM trava e revalidavam o status em memória antes de
gravar a decisão + a auditoria. Dois decisores concorrentes (ou o cruzamento de
duas transições sobre a MESMA linha aberta) passavam o mesmo check com o estado
obsoleto e ambos aplicavam → auditoria duplicada e/ou decisão sobrescrita (lost
update). A correção trava a linha com ``SELECT ... FOR UPDATE``
(``db.refresh(..., with_for_update=True)``) na MESMA transação que valida →
grava → registra → commita (idêntico ao ``approve``).

Só um Postgres REAL prova o lock entre duas conexões — SQLite/FakeSession não
têm ``FOR UPDATE``. Suíte opt-in via ``RLS_TEST_DATABASE_URL`` (mesmo guard de
produção da suíte RLS: aborta se a URL cheirar a DEV/PROD) e skip LIMPO sem ela.
O schema é criado do zero a partir dos modelos ORM reais, num banco DESCARTÁVEL.

Mapa (parametrizado nas 4 transições mutáveis):
  * test_transition_concurrent_one_wins_other_gets_409 — a prova: duas sessões
    independentes disparam a MESMA transição em paralelo; uma vence (estado
    final), a outra espera o lock, relê o estado já decidido e recebe 409; a
    auditoria da transição é registrada UMA vez.
  * test_transition_toctou_reproduces_without_the_lock — regressão: neutraliza a
    trava (refresh vira no-op, modelando o pré-SEC-4B-C) e mostra a auditoria
    duplicada — i.e., o teste acima falharia sem o lock.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

# Importar session.py registra (uma vez) o listener after_begin do seam de
# tenant — paridade com produção. Como as sessões deste teste NÃO são marcadas,
# o listener é no-op para elas. O FOR UPDATE é ortogonal à RLS.
import app.db.session  # noqa: F401
from app.db.models import Base, Celula, CelulaSolicitacao, Igreja, Pessoa
from app.services import cell_requests_service

# Fixture opt-in (guard de produção + skip sem a env var). noqa: F401 — é uma
# fixture do pytest usada por injeção, não uma importação "morta".
from tests.conftest_rls import rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration

# IDs fixos do cenário (uuids válidos, estáveis para asserts).
_IGREJA = uuid.UUID("0e0e0e0e-0000-0000-0000-0000000000ee")
_PASTOR = uuid.UUID("0f0f0f0f-0000-0000-0000-0000000000ff")
_CELL = uuid.UUID("1c1c1c1c-0000-0000-0000-0000000000cc")
_SOL = uuid.UUID("1d1d1d1d-0000-0000-0000-0000000000dd")

# Schema dedicado (via search_path) para NÃO colidir com o `public` que a suíte
# de integração RLS provisiona no MESMO banco descartável.
_SCHEMA = "sec4bc_transitions"


# ---------------------------------------------------------------------------
# Cenários por transição: (status inicial, chamada do serviço, ação de auditoria,
# status final esperado do vencedor).
# ---------------------------------------------------------------------------
def _call_reject(session: Session, sol: CelulaSolicitacao) -> CelulaSolicitacao:
    return cell_requests_service.reject(
        session, solicitacao=sol, actor_pessoa_id=_PASTOR, observacao_central="não"
    )


def _call_request_adjustment(
    session: Session, sol: CelulaSolicitacao
) -> CelulaSolicitacao:
    return cell_requests_service.request_adjustment(
        session, solicitacao=sol, actor_pessoa_id=_PASTOR, observacao_central="ajuste"
    )


def _call_resubmit(session: Session, sol: CelulaSolicitacao) -> CelulaSolicitacao:
    return cell_requests_service.resubmit(
        session,
        solicitacao=sol,
        actor_pessoa_id=_PASTOR,
        new_payload={"dia_reuniao": "sabado"},
    )


def _call_cancel(session: Session, sol: CelulaSolicitacao) -> CelulaSolicitacao:
    return cell_requests_service.cancel(
        session, solicitacao=sol, actor_pessoa_id=_PASTOR
    )


def _call_approve(session: Session, sol: CelulaSolicitacao) -> CelulaSolicitacao:
    # approve exige a célula (aplica o payload nela); o router a carrega SEM trava.
    cell = session.get(Celula, _CELL)
    return cell_requests_service.approve(
        session,
        solicitacao=sol,
        cell=cell,
        actor_pessoa_id=_PASTOR,
        approver_app_user_id=None,
        idempotency_key=None,
    )


_Case = Callable[[Session, CelulaSolicitacao], CelulaSolicitacao]

# (status_inicial, call, acao_evento, status_final_do_vencedor)
_CASES = [
    pytest.param("aguardando", _call_reject, "rejeitada", "rejeitada", id="reject"),
    pytest.param(
        "aguardando",
        _call_request_adjustment,
        "ajuste_solicitado",
        "ajuste_solicitado",
        id="request_adjustment",
    ),
    pytest.param(
        "ajuste_solicitado", _call_resubmit, "reenviada", "aguardando", id="resubmit"
    ),
    pytest.param("aguardando", _call_cancel, "cancelada", "cancelada", id="cancel"),
]


# ---------------------------------------------------------------------------
# Schema + seed no banco descartável
# ---------------------------------------------------------------------------
@pytest.fixture
def transitions_engine(rls_database_url: str) -> Iterator[Engine]:
    """Engine contra o Postgres descartável, com schema próprio recriado do zero."""
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


def _seed(factory: sessionmaker, status_inicial: str) -> None:
    session = factory()
    try:
        session.add(Igreja(id=_IGREJA, nome="Igreja Transições"))
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
                status=status_inicial,
                payload_proposto={"dia_reuniao": "sexta"},
            )
        )
        session.commit()
    finally:
        session.close()


def _run_two(factory: sessionmaker, call: _Case) -> dict[int, tuple]:
    """Duas sessões independentes disparam a MESMA transição em paralelo.

    Cada thread lê a solicitação SEM trava (como o router faz) e só então chama o
    serviço — a barreira maximiza a sobreposição real da corrida. Resultado por
    thread: ``('ok', status)`` ou ``('http', codigo)``.
    """
    barrier = threading.Barrier(2)
    out: dict[int, tuple] = {}

    def worker(idx: int) -> None:
        session = factory()
        try:
            solicitacao = session.get(CelulaSolicitacao, _SOL)
            barrier.wait(timeout=15)
            res = call(session, solicitacao)
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


def _run_pair(factory: sessionmaker, call_a: _Case, call_b: _Case) -> dict[int, tuple]:
    """Como ``_run_two``, mas cada thread dispara uma transição DIFERENTE.

    Prova a corrida CRUZADA (ex.: cancel∥approve) sobre a MESMA linha aberta:
    ambas leem o estado `aguardando` sem trava e só então chamam o serviço.
    """
    barrier = threading.Barrier(2)
    out: dict[int, tuple] = {}
    calls = {0: call_a, 1: call_b}

    def worker(idx: int) -> None:
        session = factory()
        try:
            solicitacao = session.get(CelulaSolicitacao, _SOL)
            barrier.wait(timeout=15)
            res = calls[idx](session, solicitacao)
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


def _event_count(factory: sessionmaker, acao: str) -> int:
    session = factory()
    try:
        return int(
            session.execute(
                text(
                    "select count(*) from celula_solicitacao_evento "
                    "where acao = :a and solicitacao_id = :s"
                ),
                {"a": acao, "s": _SOL},
            ).scalar_one()
        )
    finally:
        session.close()


def _status(factory: sessionmaker) -> str:
    session = factory()
    try:
        return session.execute(
            text("select status from celula_solicitacao where id = :s"), {"s": _SOL}
        ).scalar_one()
    finally:
        session.close()


def _dia_reuniao(factory: sessionmaker) -> str:
    session = factory()
    try:
        return session.execute(
            text("select dia_reuniao from celulas where id = :c"), {"c": _CELL}
        ).scalar_one()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# A prova
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status_inicial,call,acao,status_final", _CASES)
def test_transition_concurrent_one_wins_other_gets_409(
    transitions_engine: Engine,
    status_inicial: str,
    call: _Case,
    acao: str,
    status_final: str,
) -> None:
    factory = _factory(transitions_engine)
    _seed(factory, status_inicial)

    out = _run_two(factory, call)

    # Exatamente uma vence (status final); a outra, após aguardar o lock e reler
    # o estado já decidido, recebe 409. (Quem vence varia — é corrida real.)
    assert sorted(out.values()) == [("http", 409), ("ok", status_final)], out
    assert _event_count(factory, acao) == 1, "a decisão deve ser registrada UMA vez"
    assert _status(factory) == status_final


@pytest.mark.parametrize("status_inicial,call,acao,status_final", _CASES)
def test_transition_toctou_reproduces_without_the_lock(
    transitions_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    status_inicial: str,
    call: _Case,
    acao: str,
    status_final: str,
) -> None:
    """Regressão: sem o ``FOR UPDATE`` o TOCTOU volta.

    Neutraliza a trava (``Session.refresh`` vira no-op — modela a transição
    pré-SEC-4B-C, que revalidava o status em memória sem reler a linha sob lock).
    As duas chamadas passam o check com o estado obsoleto e ambas aplicam → a
    decisão é registrada DUAS vezes. Prova que o teste acima falharia sem o lock.
    """
    monkeypatch.setattr(Session, "refresh", lambda self, obj, **kwargs: None)

    factory = _factory(transitions_engine)
    _seed(factory, status_inicial)

    out = _run_two(factory, call)

    # Sem o lock ambas passam o check com o estado obsoleto e commitam (nenhuma
    # cai no 409) — a decisão é registrada DUAS vezes.
    assert sorted(out.values()) == [("ok", status_final), ("ok", status_final)], out
    assert _event_count(factory, acao) == 2, "sem o lock a decisão duplica"


# ---------------------------------------------------------------------------
# Corrida CRUZADA: cancel∥approve — o par mais perigoso (approve escreve em
# `celulas`; cancel só na própria linha). O lock compartilhado sobre a MESMA
# linha da solicitação serializa as duas: se cancel vence, approve relê o estado
# já `cancelada`, cai no 409 e NÃO aplica o payload → nenhuma escrita órfã em
# `celulas`. Prova a ausência de dupla aplicação de efeitos entre transições.
# ---------------------------------------------------------------------------
def test_cross_transition_cancel_vs_approve_no_orphan_effect(
    transitions_engine: Engine,
) -> None:
    factory = _factory(transitions_engine)
    _seed(factory, "aguardando")  # célula dia="quinta"; payload aprovaria dia="sexta"

    out = _run_pair(factory, _call_cancel, _call_approve)

    # Exatamente uma vence; a outra, sob o MESMO lock de linha, relê o estado já
    # decidido e recebe 409. (Quem vence varia — é corrida real.)
    kinds = sorted(k for k, _ in out.values())
    assert kinds == ["http", "ok"], out
    vencedor = next(v for k, v in out.values() if k == "ok")
    perdedor = next(v for k, v in out.values() if k == "http")
    assert perdedor == 409
    assert vencedor in ("cancelada", "aprovada")

    status = _status(factory)
    dia = _dia_reuniao(factory)
    aprovadas = _event_count(factory, "aprovada")
    canceladas = _event_count(factory, "cancelada")
    assert status == vencedor

    if vencedor == "aprovada":
        # approve venceu: payload aplicado UMA vez; cancel foi barrado (409).
        assert dia == "sexta"
        assert (aprovadas, canceladas) == (1, 0)
    else:
        # cancel venceu: approve foi barrado ANTES de aplicar — SEM escrita órfã.
        assert dia == "quinta"
        assert (aprovadas, canceladas) == (0, 1)
