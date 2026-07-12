"""SEC-4B / E13: prova de concorrência real do índice único na CRIAÇÃO.

``create_cell_request`` fazia SELECT (``_has_open_conflict`` — matriz E13/§6.8) e,
se não achasse solicitação aberta conflitante, INSERT — SEM trava. Duas criações
concorrentes passavam as DUAS pelo SELECT antes de qualquer COMMIT e ambas
inseriam → DUAS solicitações abertas para o mesmo conflito (E13 violado).
``FOR UPDATE`` NÃO resolve check→insert: não existe linha a travar antes do
INSERT. A garantia é no banco — índices únicos PARCIAIS sobre os statuses ABERTOS
(``uq_celula_solicitacao_aberta_tipo`` / ``uq_celula_solicitacao_aberta_membro``);
a 2ª criação concorrente recebe ``unique_violation``, que o router traduz para 409.

Só um Postgres REAL prova isso entre duas conexões — SQLite/FakeSession não têm o
índice parcial nem o comportamento de bloqueio. Suíte opt-in via
``RLS_TEST_DATABASE_URL`` (mesmo guard de produção da suíte RLS: aborta se a URL
cheirar a DEV/PROD) e skip LIMPO sem ela. O schema é criado do zero a partir dos
modelos ORM reais (que já carregam os índices em ``__table_args__``), num banco
DESCARTÁVEL.

Mapa:
  * test_create_concurrent_one_wins_other_gets_409 — a prova ponta-a-ponta: duas
    sessões independentes criam o MESMO conflito em paralelo; uma vence, a outra
    recebe 409 (pelo pré-check OU pelo índice — ambos os 409 são válidos); UMA
    única solicitação e UM único evento `criada` sobrevivem.
  * test_create_index_serializes_when_precheck_races — isola o ÍNDICE: neutraliza
    o pré-check (``_has_open_conflict`` → False, modelando as duas leituras que
    perdem a corrida) e prova que só o índice serializa: uma vence, a outra 409.
  * test_create_toctou_reproduces_without_index — regressão: pré-check neutralizado
    + índices DROPADOS → ambas commitam (DUAS linhas). Prova que o índice é o fix.
  * test_create_different_churches_do_not_collide — multi-tenant: mesmo tipo em
    igrejas diferentes NÃO colide (escopo por igreja_id).
  * test_create_after_decision_allows_new_open — histórico preservado: decidida a
    solicitação (sai dos statuses abertos), uma nova do mesmo tipo pode abrir.
  * test_member_index_serializes_direct_insert — o índice de membro (endpoint
    barra tipo de membro com 403; exercitado por INSERT direto): transferir e
    remover a MESMA pessoa colidem; pessoas diferentes não.
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
from app.db.models import AppUser, Base, Celula, CelulaSolicitacao, Igreja, Pessoa
from app.deps import CurrentUser
from app.routers import cell_requests
from app.routers.cell_requests import CreateCellRequest, create_cell_request
from app.services import cell_requests_service

# Fixture opt-in (guard de produção + skip sem a env var). noqa: F401 — fixture
# do pytest usada por injeção, não importação "morta".
from tests.conftest_rls import rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration

# Igreja A + líder/app_user/célula. IDs fixos (uuids válidos, estáveis).
_IGREJA_A = uuid.UUID("0e0e0e0e-0000-0000-0000-00000000ee01")
_PESSOA_A = uuid.UUID("0f0f0f0f-0000-0000-0000-00000000ff01")
_APPUSER_A = uuid.UUID("0a11a11a-0000-0000-0000-00000000aa01")
_CELL_A = uuid.UUID("1c1c1c1c-0000-0000-0000-00000000cc01")
_MEMBER_A = uuid.UUID("0d0d0d0d-0000-0000-0000-00000000dd01")
_MEMBER_A2 = uuid.UUID("0d0d0d0d-0000-0000-0000-00000000dd02")

# Igreja B (multi-tenant): mesmo cenário, tenant diferente.
_IGREJA_B = uuid.UUID("0e0e0e0e-0000-0000-0000-00000000ee02")
_PESSOA_B = uuid.UUID("0f0f0f0f-0000-0000-0000-00000000ff02")
_APPUSER_B = uuid.UUID("0a11a11a-0000-0000-0000-00000000aa02")
_CELL_B = uuid.UUID("1c1c1c1c-0000-0000-0000-00000000cc02")

# Schema dedicado (via search_path) para NÃO colidir com o `public` da suíte RLS
# no MESMO banco descartável.
_SCHEMA = "sec4b_create"

_TIPO = "alterar_dia"
_PAYLOAD = {"dia_reuniao": "sexta"}


# ---------------------------------------------------------------------------
# Schema + seed no banco descartável
# ---------------------------------------------------------------------------
@pytest.fixture
def create_engine_fx(rls_database_url: str) -> Iterator[Engine]:
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
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade;")
        engine.dispose()


def _factory(engine: Engine) -> sessionmaker:
    # expire_on_commit=False espelha o get_session_factory() de produção.
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def _seed_church(
    factory: sessionmaker,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    app_user_id: uuid.UUID,
    cell_id: uuid.UUID,
    extra_pessoas: tuple[uuid.UUID, ...] = (),
) -> None:
    """Igreja + líder (Pessoa) + app_user vinculado + célula liderada por ele."""
    session = factory()
    try:
        session.add(Igreja(id=igreja_id, nome="Igreja"))
        session.flush()
        session.add(Pessoa(id=pessoa_id, igreja_id=igreja_id, nome="Líder", telefone="0"))
        for i, extra in enumerate(extra_pessoas):
            session.add(
                Pessoa(id=extra, igreja_id=igreja_id, nome=f"Membro{i}", telefone=str(i + 1))
            )
        session.flush()
        session.add(
            AppUser(
                id=app_user_id,
                igreja_id=igreja_id,
                pessoa_id=pessoa_id,
                nome="Líder",
                email="lider@example.com",
                clerk_user_id=f"clerk-{app_user_id}",
            )
        )
        session.add(
            Celula(
                id=cell_id,
                igreja_id=igreja_id,
                nome="Célula",
                cobertura_espiritual="Rede",
                dia_reuniao="quinta",
                lider_id=pessoa_id,
            )
        )
        session.commit()
    finally:
        session.close()


def _leader_user(igreja_id: uuid.UUID, app_user_id: uuid.UUID) -> CurrentUser:
    return CurrentUser(
        app_user_id=str(app_user_id),
        clerk_user_id=f"clerk-{app_user_id}",
        igreja_id=str(igreja_id),
        email="lider@example.com",
        nome="Líder",
        roles=frozenset({"lider"}),
    )


def _count_solicitacoes(factory: sessionmaker, igreja_id: uuid.UUID | None = None) -> int:
    session = factory()
    try:
        if igreja_id is None:
            return int(
                session.execute(
                    text("select count(*) from celula_solicitacao")
                ).scalar_one()
            )
        return int(
            session.execute(
                text("select count(*) from celula_solicitacao where igreja_id = :i"),
                {"i": str(igreja_id)},
            ).scalar_one()
        )
    finally:
        session.close()


def _count_events(factory: sessionmaker, acao: str) -> int:
    session = factory()
    try:
        return int(
            session.execute(
                text("select count(*) from celula_solicitacao_evento where acao = :a"),
                {"a": acao},
            ).scalar_one()
        )
    finally:
        session.close()


def _open_count(factory: sessionmaker) -> int:
    session = factory()
    try:
        return int(
            session.execute(
                text(
                    "select count(*) from celula_solicitacao "
                    "where status in ('aguardando','ajuste_solicitado')"
                )
            ).scalar_one()
        )
    finally:
        session.close()


def _run_two_creates(
    factory: sessionmaker,
    *,
    cell_id: uuid.UUID,
    user: CurrentUser,
) -> dict[int, tuple]:
    """Duas sessões independentes criam a MESMA solicitação em paralelo.

    Cada thread abre a própria sessão e só dispara após a barreira — maximiza a
    sobreposição real da corrida. Resultado por thread: ``('ok', status)`` ou
    ``('http', codigo)``.
    """
    barrier = threading.Barrier(2)
    out: dict[int, tuple] = {}

    def worker(idx: int) -> None:
        session = factory()
        try:
            body = CreateCellRequest(
                celula_id=str(cell_id), tipo=_TIPO, payload_proposto=dict(_PAYLOAD)
            )
            barrier.wait(timeout=15)
            res = create_cell_request(body, db=session, current_user=user)
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


# ---------------------------------------------------------------------------
# A prova ponta-a-ponta
# ---------------------------------------------------------------------------
def test_create_concurrent_one_wins_other_gets_409(create_engine_fx: Engine) -> None:
    factory = _factory(create_engine_fx)
    _seed_church(
        factory,
        igreja_id=_IGREJA_A,
        pessoa_id=_PESSOA_A,
        app_user_id=_APPUSER_A,
        cell_id=_CELL_A,
    )

    out = _run_two_creates(factory, cell_id=_CELL_A, user=_leader_user(_IGREJA_A, _APPUSER_A))

    # Exatamente uma cria (aguardando); a outra recebe 409 — pelo pré-check OU
    # pelo índice, ambos válidos. UMA solicitação e UM evento `criada` sobrevivem.
    assert sorted(out.values()) == [("http", 409), ("ok", "aguardando")], out
    assert _count_solicitacoes(factory) == 1
    assert _count_events(factory, "criada") == 1


# ---------------------------------------------------------------------------
# Isola o ÍNDICE: neutraliza o pré-check para as duas leituras perderem a corrida
# ---------------------------------------------------------------------------
def test_create_index_serializes_when_precheck_races(
    create_engine_fx: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Modela a janela TOCTOU: ambas as criações passam o pré-check (leram 0
    # abertas antes de qualquer commit). Só o índice único as serializa.
    monkeypatch.setattr(cell_requests, "_has_open_conflict", lambda *a, **k: False)

    factory = _factory(create_engine_fx)
    _seed_church(
        factory,
        igreja_id=_IGREJA_A,
        pessoa_id=_PESSOA_A,
        app_user_id=_APPUSER_A,
        cell_id=_CELL_A,
    )

    out = _run_two_creates(factory, cell_id=_CELL_A, user=_leader_user(_IGREJA_A, _APPUSER_A))

    # Com o pré-check fora, o 409 SÓ pode vir do índice (unique_violation → 409).
    assert sorted(out.values()) == [("http", 409), ("ok", "aguardando")], out
    assert _count_solicitacoes(factory) == 1
    assert _count_events(factory, "criada") == 1


def test_create_toctou_reproduces_without_index(
    create_engine_fx: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regressão: sem os índices o TOCTOU volta (duas solicitações abertas)."""
    monkeypatch.setattr(cell_requests, "_has_open_conflict", lambda *a, **k: False)
    with create_engine_fx.begin() as conn:
        conn.exec_driver_sql(f"drop index {_SCHEMA}.uq_celula_solicitacao_aberta_tipo")
        conn.exec_driver_sql(f"drop index {_SCHEMA}.uq_celula_solicitacao_aberta_membro")

    factory = _factory(create_engine_fx)
    _seed_church(
        factory,
        igreja_id=_IGREJA_A,
        pessoa_id=_PESSOA_A,
        app_user_id=_APPUSER_A,
        cell_id=_CELL_A,
    )

    out = _run_two_creates(factory, cell_id=_CELL_A, user=_leader_user(_IGREJA_A, _APPUSER_A))

    # Sem o índice e sem o pré-check, ambas criam → DUAS solicitações abertas.
    assert sorted(out.values()) == [("ok", "aguardando"), ("ok", "aguardando")], out
    assert _count_solicitacoes(factory) == 2
    assert _count_events(factory, "criada") == 2


# ---------------------------------------------------------------------------
# Multi-tenant: igrejas diferentes NÃO colidem
# ---------------------------------------------------------------------------
def test_create_different_churches_do_not_collide(create_engine_fx: Engine) -> None:
    factory = _factory(create_engine_fx)
    _seed_church(
        factory,
        igreja_id=_IGREJA_A,
        pessoa_id=_PESSOA_A,
        app_user_id=_APPUSER_A,
        cell_id=_CELL_A,
    )
    _seed_church(
        factory,
        igreja_id=_IGREJA_B,
        pessoa_id=_PESSOA_B,
        app_user_id=_APPUSER_B,
        cell_id=_CELL_B,
    )

    barrier = threading.Barrier(2)
    out: dict[int, tuple] = {}
    specs = {
        0: (_CELL_A, _leader_user(_IGREJA_A, _APPUSER_A)),
        1: (_CELL_B, _leader_user(_IGREJA_B, _APPUSER_B)),
    }

    def worker(idx: int) -> None:
        cell_id, user = specs[idx]
        session = factory()
        try:
            body = CreateCellRequest(
                celula_id=str(cell_id), tipo=_TIPO, payload_proposto=dict(_PAYLOAD)
            )
            barrier.wait(timeout=15)
            res = create_cell_request(body, db=session, current_user=user)
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

    # Mesmo tipo, mesma "posição" — mas igrejas diferentes ⇒ ambas criam.
    assert sorted(out.values()) == [("ok", "aguardando"), ("ok", "aguardando")], out
    assert _count_solicitacoes(factory, _IGREJA_A) == 1
    assert _count_solicitacoes(factory, _IGREJA_B) == 1


# ---------------------------------------------------------------------------
# Histórico preservado: decidida a solicitação, uma nova do mesmo tipo pode abrir
# ---------------------------------------------------------------------------
def test_create_after_decision_allows_new_open(create_engine_fx: Engine) -> None:
    factory = _factory(create_engine_fx)
    _seed_church(
        factory,
        igreja_id=_IGREJA_A,
        pessoa_id=_PESSOA_A,
        app_user_id=_APPUSER_A,
        cell_id=_CELL_A,
    )
    user = _leader_user(_IGREJA_A, _APPUSER_A)

    # 1ª criação: nasce aguardando.
    session = factory()
    try:
        first = create_cell_request(
            CreateCellRequest(
                celula_id=str(_CELL_A), tipo=_TIPO, payload_proposto=dict(_PAYLOAD)
            ),
            db=session,
            current_user=user,
        )
        first_id = uuid.UUID(first.id)
    finally:
        session.close()

    # Decide (cancela) → sai dos statuses ABERTOS: libera a "vaga" do índice.
    session = factory()
    try:
        sol = session.get(CelulaSolicitacao, first_id)
        cell_requests_service.cancel(session, solicitacao=sol, actor_pessoa_id=_PESSOA_A)
    finally:
        session.close()

    # 2ª criação do MESMO tipo agora é permitida (a 1ª não está mais aberta).
    session = factory()
    try:
        second = create_cell_request(
            CreateCellRequest(
                celula_id=str(_CELL_A), tipo=_TIPO, payload_proposto=dict(_PAYLOAD)
            ),
            db=session,
            current_user=user,
        )
        assert second.status == "aguardando"
        assert second.id != first.id
    finally:
        session.close()

    assert _count_solicitacoes(factory) == 2  # 1 cancelada (histórico) + 1 aberta
    assert _open_count(factory) == 1


# ---------------------------------------------------------------------------
# Índice de membro (endpoint barra tipo de membro com 403 — exercício direto)
# ---------------------------------------------------------------------------
def test_member_index_serializes_direct_insert(create_engine_fx: Engine) -> None:
    factory = _factory(create_engine_fx)
    _seed_church(
        factory,
        igreja_id=_IGREJA_A,
        pessoa_id=_PESSOA_A,
        app_user_id=_APPUSER_A,
        cell_id=_CELL_A,
        extra_pessoas=(_MEMBER_A, _MEMBER_A2),
    )

    def _add_member_request(pessoa_id: uuid.UUID, tipo: str) -> None:
        session = factory()
        try:
            session.add(
                CelulaSolicitacao(
                    igreja_id=_IGREJA_A,
                    celula_id=_CELL_A,
                    solicitante_id=_PESSOA_A,
                    pessoa_id=pessoa_id,
                    tipo=tipo,
                    status="aguardando",
                    payload_proposto={"pessoa_id": str(pessoa_id)},
                )
            )
            session.commit()
        finally:
            session.close()

    # transferir_membro da pessoa X.
    _add_member_request(_MEMBER_A, "transferir_membro")

    # remover_membro da MESMA pessoa X colide (tipo fora da chave — matriz E13).
    with pytest.raises(IntegrityError):
        _add_member_request(_MEMBER_A, "remover_membro")

    # Pessoa DIFERENTE na mesma célula NÃO colide.
    _add_member_request(_MEMBER_A2, "remover_membro")

    assert _open_count(factory) == 2  # pessoa X (transferir) + pessoa Y (remover)


# ---------------------------------------------------------------------------
# Determinismo do mapeamento: SÓ unique_violation (23505) vira 409
# ---------------------------------------------------------------------------
def test_create_non_unique_integrity_error_is_not_mapped_to_409(
    create_engine_fx: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uma violação de integridade DIFERENTE de unique (ex.: FK 23503) NÃO é
    mascarada como 409 — sobe (vira 500) porque não é conflito de estado. Guarda
    a regressão de "engolir todo IntegrityError como conflito", preservando o
    mapeamento DETERMINÍSTICO (só 23505 → 409).
    """
    factory = _factory(create_engine_fx)
    _seed_church(
        factory,
        igreja_id=_IGREJA_A,
        pessoa_id=_PESSOA_A,
        app_user_id=_APPUSER_A,
        cell_id=_CELL_A,
    )
    user = _leader_user(_IGREJA_A, _APPUSER_A)

    class _NonUniqueOrig(Exception):
        pgcode = "23503"  # foreign_key_violation — NÃO é unique_violation

    # Falha no commit com um IntegrityError não-unique (após o INSERT real). O
    # handler deve rollbackar e RE-LEVANTAR (não converter para 409).
    monkeypatch.setattr(
        Session, "commit", lambda self: (_ for _ in ()).throw(
            IntegrityError("insert", {}, _NonUniqueOrig())
        )
    )

    session = factory()
    try:
        with pytest.raises(IntegrityError):
            create_cell_request(
                CreateCellRequest(
                    celula_id=str(_CELL_A), tipo=_TIPO, payload_proposto=dict(_PAYLOAD)
                ),
                db=session,
                current_user=user,
            )
    finally:
        session.close()
