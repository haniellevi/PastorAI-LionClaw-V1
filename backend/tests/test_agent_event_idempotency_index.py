"""SEC-4 — prova, contra Postgres real, que o índice único parcial
`agent_conversation_logs_idem_marker_uidx` (migration
`20260709_204500_sec4_agent_event_idempotency_marker_uidx.sql`) protege os
marcadores de dedupe de SLA/autoupgrade, sem afetar eventos comuns.

Não dá pra provar constraint de banco com FakeSession (SQL nunca roda de
verdade) — por isso este arquivo é integração pura contra Postgres descartável,
mesmo padrão de `test_rls_invariant.py`: sem `RLS_TEST_DATABASE_URL`, skip
limpo; com a env var, roda de verdade.

Aplica o ARQUIVO da migration real (não uma cópia manual do SQL), para provar
o artefato que de fato vai pro Supabase, não uma reimplementação que pode
divergir dele.
"""

from __future__ import annotations

import pathlib
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.agent.masking import release_agent_event, reserve_agent_event
from tests.conftest_rls import IGREJA_A, IGREJA_B, rls_database_url, rls_engine, rls_seeded  # noqa: F401

pytestmark = pytest.mark.rls_integration

_MIGRATION_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "migrations"
    / "20260709_204500_sec4_agent_event_idempotency_marker_uidx.sql"
)

# FK real pra igrejas(id) — conftest_rls já cria e semeia IGREJA_A/IGREJA_B,
# então usar a tabela/coluna real (não uma cópia solta) exercita o mesmo
# caminho que `reserve_agent_event`/`release_agent_event` usam em produção
# (o model ORM real `AgentConversationLog` também referencia igrejas.id).
_TABLE_SQL = """
create table if not exists agent_conversation_logs (
  id               uuid primary key default gen_random_uuid(),
  igreja_id        uuid not null references igrejas(id) on delete cascade,
  conversation_id  uuid,
  evento           text,
  payload          jsonb,
  created_at       timestamptz not null default now()
);
"""


@pytest.fixture
def idem_engine(rls_engine: Engine, rls_seeded: dict[str, str]) -> Engine:
    """Provisiona agent_conversation_logs + aplica a migration real (idempotente)."""
    with rls_engine.begin() as conn:
        conn.execute(text(_TABLE_SQL))
        conn.execute(text(_MIGRATION_PATH.read_text(encoding="utf-8")))
    return rls_engine


@pytest.fixture
def orm_session(idem_engine: Engine):
    """Sessão ORM real — usada pra chamar reserve_agent_event/release_agent_event
    de verdade (não a query SQL crua de _insert_marker), provando o CÓDIGO de
    produção, não só o índice isolado."""
    factory = sessionmaker(bind=idem_engine, future=True)
    session: Session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _insert_marker(engine: Engine, *, igreja_id: str, evento: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "insert into agent_conversation_logs (igreja_id, evento) "
                "values (:igreja_id, :evento)"
            ),
            {"igreja_id": igreja_id, "evento": evento},
        )


def test_duplicate_sla_marker_same_igreja_violates_unique_index(
    idem_engine: Engine,
) -> None:
    evento = f"sla_cobranca:work_queue:{uuid.uuid4()}"
    _insert_marker(idem_engine, igreja_id=IGREJA_A, evento=evento)

    with pytest.raises(IntegrityError):
        _insert_marker(idem_engine, igreja_id=IGREJA_A, evento=evento)


def test_duplicate_autoupgrade_marker_same_igreja_violates_unique_index(
    idem_engine: Engine,
) -> None:
    # Sufixo uuid: evita colisão com dado de execuções anteriores contra o
    # mesmo Postgres descartável (o teste commita de verdade, não usa rollback).
    evento = f"subscription_upgrade:plano-{uuid.uuid4()}"
    _insert_marker(idem_engine, igreja_id=IGREJA_A, evento=evento)

    with pytest.raises(IntegrityError):
        _insert_marker(idem_engine, igreja_id=IGREJA_A, evento=evento)


def test_same_marker_different_igreja_does_not_conflict(idem_engine: Engine) -> None:
    """Multi-tenant: o mesmo marcador em igrejas diferentes é permitido."""
    evento = f"subscription_upgrade:plano-{uuid.uuid4()}"
    _insert_marker(idem_engine, igreja_id=IGREJA_A, evento=evento)
    # Não levanta — (igreja_id, evento) é diferente do primeiro insert.
    _insert_marker(idem_engine, igreja_id=IGREJA_B, evento=evento)


def test_non_marker_events_can_repeat_freely(idem_engine: Engine) -> None:
    """O índice é PARCIAL — eventos comuns (handoff, consent, intake, ...) que
    legitimamente se repetem não são afetados."""
    _insert_marker(idem_engine, igreja_id=IGREJA_A, evento="handoff")
    # Duas linhas "handoff" pra mesma igreja — não é marcador, não conflita.
    _insert_marker(idem_engine, igreja_id=IGREJA_A, evento="handoff")


# ---------------------------------------------------------------------------
# Código de produção real (reserve_agent_event / release_agent_event) contra
# Postgres real — não só o índice isolado via SQL cru acima.
# ---------------------------------------------------------------------------
def test_reserve_agent_event_wins_then_second_call_loses(orm_session: Session) -> None:
    evento = f"sla_cobranca:work_queue:{uuid.uuid4()}"

    first = reserve_agent_event(orm_session, igreja_id=IGREJA_A, evento=evento)
    assert first is not None

    second = reserve_agent_event(orm_session, igreja_id=IGREJA_A, evento=evento)
    assert second is None  # perdeu a corrida de verdade, contra o índice real


def test_release_agent_event_allows_retry(orm_session: Session) -> None:
    evento = f"subscription_upgrade:plano-{uuid.uuid4()}"

    reserved = reserve_agent_event(orm_session, igreja_id=IGREJA_A, evento=evento)
    assert reserved is not None

    release_agent_event(orm_session, reserved)

    # Liberado: uma nova reserva pro MESMO marcador tem que funcionar agora.
    retried = reserve_agent_event(orm_session, igreja_id=IGREJA_A, evento=evento)
    assert retried is not None
