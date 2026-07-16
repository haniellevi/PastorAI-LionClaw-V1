"""CONSOL-1: prova de concorrência real do índice único de consolidação aberta.

``registrar_decisao`` (app/agent/tools.py) e ``launch_decision``
(app/routers/consolidacao.py) inserem uma ``decisions`` e dão flush —
``trg_decision_opens_consolidation`` (AFTER INSERT em ``decisions``) SEMPRE
insere uma ``consolidacoes`` nova, sem checar se a pessoa já tem uma ABERTA.
Duas decisões concorrentes para a MESMA pessoa disparam o trigger nas duas
transações e, sem trava, ambas inseririam → duas consolidações abertas para a
mesma pessoa. O trigger roda dentro do próprio INSERT em ``decisions``: não há
linha a travar antes dele — a garantia correta é o índice único PARCIAL
``uq_consolidacoes_pessoa_aberta`` (``pessoa_id`` onde ``concluida = false AND
abandonada_em IS NULL``), que serializa a corrida no banco.

Só um Postgres REAL prova isso entre duas conexões — SQLite/FakeSession não
têm o índice parcial nem o trigger. Suíte opt-in via ``RLS_TEST_DATABASE_URL``
(mesmo guard anti DEV/PROD da suíte RLS), skip LIMPO sem ela. Schema criado do
zero a partir dos modelos ORM reais (que já carregam o índice em
``__table_args__``) MAIS uma réplica fiel do trigger (SQL puro, igual a
``backend/migrations/0004_triggers.sql``), num banco DESCARTÁVEL.

Mapa:
  * test_http_concurrent_decisions_one_wins_other_gets_409 — painel: duas
    sessões independentes lançam a MESMA decisão (mesma pessoa) em paralelo;
    uma cria (201/"created"), a outra recebe 409; UMA única consolidação
    aberta sobrevive.
  * test_agent_tool_concurrent_decisions_one_wins_other_gets_toolerror —
    agente: o mesmo cenário via ``registrar_decisao``; a perdedora recebe
    ``ToolError`` determinístico.
  * test_toctou_reproduces_without_index — regressão: índice DROPADO ⇒ ambas
    commitam (DUAS consolidações abertas). Prova que o índice é o fix.
  * test_single_decision_still_opens_consolidation_and_stage_via_trigger —
    uma decisão isolada continua abrindo decisão + consolidação + etapa
    inicial pelo trigger (caminho feliz intocado).
  * test_concluded_consolidation_does_not_block_new_decision /
    test_abandoned_consolidation_does_not_block_new_decision — encerrada
    (concluída ou abandonada) sai do índice; uma nova decisão para a mesma
    pessoa abre uma consolidação nova.
  * test_different_pessoas_do_not_collide — pessoas diferentes nunca colidem.
  * test_router_non_unique_integrity_error_is_not_mapped_to_409 /
    test_tool_non_unique_integrity_error_is_not_mapped_to_toolerror —
    determinismo: só unique_violation (23505) é traduzido; qualquer outra
    IntegrityError sobe inalterada.
  * test_agent_tool_preserves_pending_session_mutation_across_toolerror —
    revisão externa da PR#179: ``registrar_decisao`` roda na Session
    COMPARTILHADA por turno de ``app/agent/runtime.py`` (intake/consentimento/
    optout/tools anteriores mutam a MESMA session antes dela rodar). Um
    ``session.rollback()`` global no 23505 desfaria essas mutações também —
    por isso o INSERT da Decision roda dentro de um SAVEPOINT
    (``session.begin_nested()``); no unique_violation, só o SAVEPOINT é
    desfeito (``ROLLBACK TO SAVEPOINT``), nunca a transação externa. Prova:
    pessoa já com consolidação aberta ⇒ 2ª decisão dispara 23505⇒ToolError;
    uma mutação de intake pendente na mesma Session sobrevive ao commit
    externo; nenhuma 2ª Decision/consolidação é criada.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

# Importar session.py registra (uma vez) o listener after_begin do seam de tenant
# — paridade com produção. As sessões deste teste NÃO são marcadas ⇒ no-op.
import app.db.session  # noqa: F401
from app.agent.tools import ToolError, registrar_decisao
from app.db.models import AppUser, Base, Igreja, Pessoa, UserRole
from app.deps import CurrentUser
from app.routers.consolidacao import LaunchDecisionRequest, launch_decision

# Fixture opt-in (guard de produção + skip sem a env var). noqa: F401 — fixture
# do pytest usada por injeção, não importação "morta".
from tests.conftest_rls import rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration

# Igreja A + pessoa/app_user consolidador. IDs fixos (uuids válidos, estáveis).
_IGREJA_A = uuid.UUID("0e0e1e0e-0000-0000-0000-00000000ee01")
_PESSOA_A = uuid.UUID("0f0f1f0f-0000-0000-0000-00000000ff01")
_PESSOA_A2 = uuid.UUID("0f0f1f0f-0000-0000-0000-00000000ff02")
_APPUSER_A = uuid.UUID("0a111a11-0000-0000-0000-00000000aa01")

_SCHEMA = "consol1_open_unique"

# Réplica fiel de fn_decision_opens_consolidation / trg_decision_opens_consolidation
# (backend/migrations/0004_triggers.sql). Base.metadata.create_all cria as
# tabelas (com o índice único em __table_args__); o trigger em si não é
# modelado no ORM, então é recriado aqui, igual à produção.
_TRIGGER_SQL = """
create or replace function fn_decision_opens_consolidation()
returns trigger
language plpgsql
as $$
declare
  v_consolidacao_id uuid;
begin
  insert into consolidacoes (igreja_id, pessoa_id, tipo, responsavel_id, progresso, concluida, prazo_conexao)
  values (new.igreja_id, new.pessoa_id, 'individual', new.responsavel_id, 0, false, new.prazo_conexao)
  returning id into v_consolidacao_id;

  insert into consolidacao_etapas (igreja_id, consolidacao_id, etapa, concluida)
  values (new.igreja_id, v_consolidacao_id, 'aceitou_jesus', true);

  if new.vinculo = 'visitante' then
    insert into work_queue_items (igreja_id, tipo, titulo, contexto, pessoa_id, responsavel_id, status, prazo, prioridade)
    values (
      new.igreja_id,
      'conectar_celula',
      'Conectar nova decisao a uma celula',
      'Decisao ' || new.id::text || ' (visitante) — conectar em ate 24h',
      new.pessoa_id,
      new.responsavel_id,
      'aberto',
      now() + interval '24 hours',
      1
    );
  end if;

  return new;
end;
$$;

drop trigger if exists trg_decision_opens_consolidation on decisions;
create trigger trg_decision_opens_consolidation
  after insert on decisions
  for each row
  execute function fn_decision_opens_consolidation();
"""


# ---------------------------------------------------------------------------
# Schema + seed no banco descartável
# ---------------------------------------------------------------------------
@pytest.fixture
def engine_fx(rls_database_url: str) -> Iterator[Engine]:
    """Engine contra o Postgres descartável, schema próprio recriado do zero."""
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
    with engine.begin() as conn:
        conn.exec_driver_sql(_TRIGGER_SQL)
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade;")
        engine.dispose()


def _factory(engine: Engine, **kwargs) -> sessionmaker:
    # expire_on_commit=False espelha o get_session_factory() de produção.
    return sessionmaker(bind=engine, future=True, expire_on_commit=False, **kwargs)


def _seed_church(
    factory: sessionmaker,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    app_user_id: uuid.UUID,
    extra_pessoas: tuple[uuid.UUID, ...] = (),
) -> None:
    """Igreja + pessoa(s) + app_user com papel lider_consol."""
    session = factory()
    try:
        session.add(Igreja(id=igreja_id, nome="Igreja"))
        session.flush()
        session.add(Pessoa(id=pessoa_id, igreja_id=igreja_id, nome="Pessoa", telefone="0"))
        for i, extra in enumerate(extra_pessoas):
            session.add(
                Pessoa(id=extra, igreja_id=igreja_id, nome=f"Pessoa{i}", telefone=str(i + 1))
            )
        session.flush()
        session.add(
            AppUser(
                id=app_user_id,
                igreja_id=igreja_id,
                nome="Consolidador",
                email="consolidador@example.com",
                clerk_user_id=f"clerk-{app_user_id}",
            )
        )
        session.flush()
        session.add(UserRole(igreja_id=igreja_id, user_id=app_user_id, papel="lider_consol"))
        session.commit()
    finally:
        session.close()


def _consol_user(igreja_id: uuid.UUID, app_user_id: uuid.UUID) -> CurrentUser:
    return CurrentUser(
        app_user_id=str(app_user_id),
        clerk_user_id=f"clerk-{app_user_id}",
        igreja_id=str(igreja_id),
        email="consolidador@example.com",
        nome="Consolidador",
        roles=frozenset({"lider_consol"}),
    )


def _open_count(factory: sessionmaker, pessoa_id: uuid.UUID | None = None) -> int:
    session = factory()
    try:
        if pessoa_id is None:
            return int(
                session.execute(
                    text(
                        "select count(*) from consolidacoes "
                        "where concluida = false and abandonada_em is null"
                    )
                ).scalar_one()
            )
        return int(
            session.execute(
                text(
                    "select count(*) from consolidacoes where pessoa_id = :p "
                    "and concluida = false and abandonada_em is null"
                ),
                {"p": str(pessoa_id)},
            ).scalar_one()
        )
    finally:
        session.close()


def _total_consolidacoes(factory: sessionmaker, pessoa_id: uuid.UUID) -> int:
    session = factory()
    try:
        return int(
            session.execute(
                text("select count(*) from consolidacoes where pessoa_id = :p"),
                {"p": str(pessoa_id)},
            ).scalar_one()
        )
    finally:
        session.close()


def _run_two_http_decisions(
    factory: sessionmaker, *, pessoa_id: uuid.UUID, user: CurrentUser
) -> dict[int, tuple]:
    """Duas sessões independentes lançam a MESMA decisão em paralelo (painel).

    Cada thread abre a própria sessão e só dispara após a barreira — maximiza a
    sobreposição real da corrida. Resultado por thread: ``('ok', status)`` ou
    ``('http', codigo)``.
    """
    barrier = threading.Barrier(2)
    out: dict[int, tuple] = {}

    def worker(idx: int) -> None:
        session = factory()
        try:
            payload = LaunchDecisionRequest(pessoa=str(pessoa_id), vinculo="visitante")
            barrier.wait(timeout=15)
            res = launch_decision(payload, db=session, current_user=user)
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


def _run_two_tool_decisions(
    factory: sessionmaker, *, igreja_id: uuid.UUID, pessoa_id: uuid.UUID
) -> dict[int, tuple]:
    """Duas sessões independentes lançam a MESMA decisão em paralelo (agente)."""
    barrier = threading.Barrier(2)
    out: dict[int, tuple] = {}

    def worker(idx: int) -> None:
        session = factory()
        try:
            barrier.wait(timeout=15)
            try:
                result = registrar_decisao(
                    session, igreja_id=igreja_id, pessoa_id=pessoa_id, vinculo="visitante"
                )
                session.commit()  # o runtime do agente comita no fim do turno
                out[idx] = ("ok", result.detalhe["decisionId"])
            except ToolError as exc:
                out[idx] = ("tool_error", str(exc))
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    return out


# ---------------------------------------------------------------------------
# A prova ponta-a-ponta: painel + agente
# ---------------------------------------------------------------------------
def test_http_concurrent_decisions_one_wins_other_gets_409(engine_fx: Engine) -> None:
    factory = _factory(engine_fx)
    _seed_church(factory, igreja_id=_IGREJA_A, pessoa_id=_PESSOA_A, app_user_id=_APPUSER_A)
    user = _consol_user(_IGREJA_A, _APPUSER_A)

    out = _run_two_http_decisions(factory, pessoa_id=_PESSOA_A, user=user)

    assert sorted(out.values()) == [("http", 409), ("ok", "created")], out
    assert _open_count(factory, _PESSOA_A) == 1
    assert _total_consolidacoes(factory, _PESSOA_A) == 1


def test_agent_tool_concurrent_decisions_one_wins_other_gets_toolerror(
    engine_fx: Engine,
) -> None:
    factory = _factory(engine_fx)
    _seed_church(factory, igreja_id=_IGREJA_A, pessoa_id=_PESSOA_A, app_user_id=_APPUSER_A)

    out = _run_two_tool_decisions(factory, igreja_id=_IGREJA_A, pessoa_id=_PESSOA_A)

    kinds = sorted(kind for kind, _ in out.values())
    assert kinds == ["ok", "tool_error"], out
    assert _open_count(factory, _PESSOA_A) == 1
    assert _total_consolidacoes(factory, _PESSOA_A) == 1


# ---------------------------------------------------------------------------
# Regressão: sem o índice, o TOCTOU volta (duas consolidações abertas)
# ---------------------------------------------------------------------------
def test_toctou_reproduces_without_index(engine_fx: Engine) -> None:
    with engine_fx.begin() as conn:
        conn.exec_driver_sql(f"drop index {_SCHEMA}.uq_consolidacoes_pessoa_aberta")

    factory = _factory(engine_fx)
    _seed_church(factory, igreja_id=_IGREJA_A, pessoa_id=_PESSOA_A, app_user_id=_APPUSER_A)
    user = _consol_user(_IGREJA_A, _APPUSER_A)

    out = _run_two_http_decisions(factory, pessoa_id=_PESSOA_A, user=user)

    # Sem o índice, ambas commitam → DUAS consolidações abertas (bug reproduzido).
    assert sorted(out.values()) == [("ok", "created"), ("ok", "created")], out
    assert _open_count(factory, _PESSOA_A) == 2


# ---------------------------------------------------------------------------
# Caminho feliz intocado: decisão única continua abrindo tudo pelo trigger
# ---------------------------------------------------------------------------
def test_single_decision_still_opens_consolidation_and_stage_via_trigger(
    engine_fx: Engine,
) -> None:
    factory = _factory(engine_fx)
    _seed_church(factory, igreja_id=_IGREJA_A, pessoa_id=_PESSOA_A, app_user_id=_APPUSER_A)
    user = _consol_user(_IGREJA_A, _APPUSER_A)

    session = factory()
    try:
        result = launch_decision(
            LaunchDecisionRequest(pessoa=str(_PESSOA_A), vinculo="visitante"),
            db=session,
            current_user=user,
        )
        assert result.status == "created"
        assert result.prazoConexao is not None
    finally:
        session.close()

    session = factory()
    try:
        n_decisions = session.execute(
            text("select count(*) from decisions where pessoa_id = :p"),
            {"p": str(_PESSOA_A)},
        ).scalar_one()
        etapas = session.execute(
            text(
                "select ce.etapa, ce.concluida from consolidacao_etapas ce "
                "join consolidacoes c on c.id = ce.consolidacao_id "
                "where c.pessoa_id = :p"
            ),
            {"p": str(_PESSOA_A)},
        ).all()
    finally:
        session.close()

    assert n_decisions == 1
    assert _open_count(factory, _PESSOA_A) == 1
    assert etapas == [("aceitou_jesus", True)]


# ---------------------------------------------------------------------------
# Encerrada (concluída ou abandonada) não bloqueia nova decisão
# ---------------------------------------------------------------------------
def test_concluded_consolidation_does_not_block_new_decision(engine_fx: Engine) -> None:
    factory = _factory(engine_fx)
    _seed_church(factory, igreja_id=_IGREJA_A, pessoa_id=_PESSOA_A, app_user_id=_APPUSER_A)
    user = _consol_user(_IGREJA_A, _APPUSER_A)

    session = factory()
    try:
        launch_decision(
            LaunchDecisionRequest(pessoa=str(_PESSOA_A), vinculo="visitante"),
            db=session,
            current_user=user,
        )
    finally:
        session.close()

    # Encerra a consolidação aberta (concluída) — sai do índice.
    session = factory()
    try:
        session.execute(
            text("update consolidacoes set concluida = true where pessoa_id = :p"),
            {"p": str(_PESSOA_A)},
        )
        session.commit()
    finally:
        session.close()

    # Nova decisão para a MESMA pessoa agora é permitida.
    session = factory()
    try:
        second = launch_decision(
            LaunchDecisionRequest(pessoa=str(_PESSOA_A), vinculo="visitante"),
            db=session,
            current_user=user,
        )
        assert second.status == "created"
    finally:
        session.close()

    assert _total_consolidacoes(factory, _PESSOA_A) == 2  # 1 concluída + 1 aberta
    assert _open_count(factory, _PESSOA_A) == 1


def test_abandoned_consolidation_does_not_block_new_decision(engine_fx: Engine) -> None:
    factory = _factory(engine_fx)
    _seed_church(factory, igreja_id=_IGREJA_A, pessoa_id=_PESSOA_A, app_user_id=_APPUSER_A)
    user = _consol_user(_IGREJA_A, _APPUSER_A)

    session = factory()
    try:
        launch_decision(
            LaunchDecisionRequest(pessoa=str(_PESSOA_A), vinculo="visitante"),
            db=session,
            current_user=user,
        )
    finally:
        session.close()

    # Abandona a consolidação aberta — sai do índice (independente de concluida).
    session = factory()
    try:
        session.execute(
            text(
                "update consolidacoes set abandonada_em = now(), "
                "abandonada_motivo = 'teste' where pessoa_id = :p"
            ),
            {"p": str(_PESSOA_A)},
        )
        session.commit()
    finally:
        session.close()

    session = factory()
    try:
        second = launch_decision(
            LaunchDecisionRequest(pessoa=str(_PESSOA_A), vinculo="visitante"),
            db=session,
            current_user=user,
        )
        assert second.status == "created"
    finally:
        session.close()

    assert _total_consolidacoes(factory, _PESSOA_A) == 2  # 1 abandonada + 1 aberta
    assert _open_count(factory, _PESSOA_A) == 1


# ---------------------------------------------------------------------------
# Pessoas diferentes nunca colidem
# ---------------------------------------------------------------------------
def test_different_pessoas_do_not_collide(engine_fx: Engine) -> None:
    factory = _factory(engine_fx)
    _seed_church(
        factory,
        igreja_id=_IGREJA_A,
        pessoa_id=_PESSOA_A,
        app_user_id=_APPUSER_A,
        extra_pessoas=(_PESSOA_A2,),
    )
    user = _consol_user(_IGREJA_A, _APPUSER_A)

    barrier = threading.Barrier(2)
    out: dict[int, tuple] = {}
    specs = {0: _PESSOA_A, 1: _PESSOA_A2}

    def worker(idx: int) -> None:
        pessoa_id = specs[idx]
        session = factory()
        try:
            payload = LaunchDecisionRequest(pessoa=str(pessoa_id), vinculo="visitante")
            barrier.wait(timeout=15)
            res = launch_decision(payload, db=session, current_user=user)
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

    assert sorted(out.values()) == [("ok", "created"), ("ok", "created")], out
    assert _open_count(factory, _PESSOA_A) == 1
    assert _open_count(factory, _PESSOA_A2) == 1


# ---------------------------------------------------------------------------
# Determinismo do mapeamento: SÓ unique_violation (23505) é traduzido
# ---------------------------------------------------------------------------
class _NonUniqueOrig(Exception):
    pgcode = "23503"  # foreign_key_violation — NÃO é unique_violation


def test_router_non_unique_integrity_error_is_not_mapped_to_409(
    engine_fx: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uma IntegrityError DIFERENTE de unique (ex.: FK 23503) NÃO vira 409 —
    sobe inalterada. Guarda a regressão de "engolir todo IntegrityError como
    conflito", preservando o mapeamento DETERMINÍSTICO (só 23505 → 409).
    """
    # autoflush=False: só o .flush() explícito do router deve falhar, não o
    # autoflush do SELECT de Pessoa que roda antes dele.
    factory = _factory(engine_fx, autoflush=False)
    _seed_church(factory, igreja_id=_IGREJA_A, pessoa_id=_PESSOA_A, app_user_id=_APPUSER_A)
    user = _consol_user(_IGREJA_A, _APPUSER_A)

    def _boom(self: Session) -> None:
        raise IntegrityError("insert", {}, _NonUniqueOrig())

    monkeypatch.setattr(Session, "flush", _boom)

    session = factory()
    try:
        with pytest.raises(IntegrityError):
            launch_decision(
                LaunchDecisionRequest(pessoa=str(_PESSOA_A), vinculo="visitante"),
                db=session,
                current_user=user,
            )
    finally:
        session.close()


def test_tool_non_unique_integrity_error_is_not_mapped_to_toolerror(
    engine_fx: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _factory(engine_fx, autoflush=False)
    _seed_church(factory, igreja_id=_IGREJA_A, pessoa_id=_PESSOA_A, app_user_id=_APPUSER_A)

    def _boom(self: Session) -> None:
        raise IntegrityError("insert", {}, _NonUniqueOrig())

    monkeypatch.setattr(Session, "flush", _boom)

    session = factory()
    try:
        with pytest.raises(IntegrityError):
            registrar_decisao(
                session, igreja_id=_IGREJA_A, pessoa_id=_PESSOA_A, vinculo="visitante"
            )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# PR#179 (revisão externa): savepoint isola a Decision — não derruba o turno
# ---------------------------------------------------------------------------
def test_agent_tool_preserves_pending_session_mutation_across_toolerror(
    engine_fx: Engine,
) -> None:
    """1ª decisão abre a consolidação; 2ª (mesma pessoa) dispara 23505.

    Antes da 2ª chamada, muta ``pessoa.origem`` na MESMA Session SEM
    flush/commit — espelha ``_apply_intake`` rodando antes de
    ``_execute_tools`` em ``app/agent/runtime.py::process_inbound_message``
    (a Session é compartilhada pelo turno inteiro, um único commit no fim).
    Sem o SAVEPOINT, o ``session.rollback()`` global desfaria essa mutação
    junto com a Decision recusada — o bug que a revisão externa apontou.
    """
    factory = _factory(engine_fx)
    _seed_church(factory, igreja_id=_IGREJA_A, pessoa_id=_PESSOA_A, app_user_id=_APPUSER_A)

    # Pré-condição (item 1 do blocker): pessoa já tem consolidação aberta.
    session = factory()
    try:
        registrar_decisao(
            session, igreja_id=_IGREJA_A, pessoa_id=_PESSOA_A, vinculo="visitante"
        )
        session.commit()
    finally:
        session.close()
    assert _open_count(factory, _PESSOA_A) == 1

    # Turno do agente: intake pendente (item 2) + 2ª decisão ⇒ ToolError (item 3).
    session = factory()
    try:
        pessoa = session.get(Pessoa, _PESSOA_A)
        pessoa.origem = "intake-pendente-mesmo-turno"
        with pytest.raises(ToolError):
            registrar_decisao(
                session, igreja_id=_IGREJA_A, pessoa_id=_PESSOA_A, vinculo="visitante"
            )
        # O commit é do RUNTIME (dono da transação), não da tool.
        session.commit()
    finally:
        session.close()

    # Item 4: commit externo preserva a mutação de intake anterior.
    session = factory()
    try:
        reloaded = session.get(Pessoa, _PESSOA_A)
        assert reloaded.origem == "intake-pendente-mesmo-turno"
    finally:
        session.close()

    # Item 5: nenhuma 2ª Decision nem 2ª Consolidacao — só a 1ª sobrevive.
    assert _total_consolidacoes(factory, _PESSOA_A) == 1
    assert _open_count(factory, _PESSOA_A) == 1
    session = factory()
    try:
        n_decisions = session.execute(
            text("select count(*) from decisions where pessoa_id = :p"),
            {"p": str(_PESSOA_A)},
        ).scalar_one()
    finally:
        session.close()
    assert n_decisions == 1
