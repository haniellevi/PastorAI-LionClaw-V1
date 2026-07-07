"""Superficie unica da invariante de isolamento por tenant (D5) — PR1.

Estritamente aditivo: prova a invariante ATUAL como baseline de nao-regressao,
contra um Postgres REAL e DESCARTAVEL (RLS_TEST_DATABASE_URL). Sem essa env var,
TODOS os testes deste arquivo dao skip LIMPO (via a fixture rls_database_url).

Mapa T1-T6 (SPEC secao 8):
  * T1: sessao no papel `authenticated` SEM contexto de tenant nao le nada;
        contexto de igreja inexistente => 0 linhas.
  * T2: contexto na igreja A ve so A, nunca B — e o simetrico para B.
  * T3: PR2 seam — apos mark_tenant_scoped(A) + commit(), uma nova transacao
        (query/refresh reais) permanece escopada em A via o listener after_begin.
  * T4: PR3-B — caminho do worker migrado ao seam: fase cross-tenant (lookup
        por instance) -> promote_to_tenant escopa a igreja; promover sem a fase
        precedente ou para outra igreja ja pinada FALHA.
  * T5-probe / T6-probe: sinal read-only de observabilidade (PR1).
  * T5-seam: sem vazamento de role/GUC pelo pool (a proxima sessao sem marca
        NAO herda o escopo da anterior).
  * T6-seam: listener fail-closed — reaplicar o escopo num banco onde o papel
        authenticated sumiu derruba a transacao (nunca segue em BYPASSRLS).

RLS so pode ser validada contra Postgres real — nunca SQLite/PGLite/FakeSession
(o FakeSession do conftest.py so verifica o SQL emitido). Por isso este arquivo
e integracao pura, marcado `rls_integration`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Uuid, create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

# Importar session.py REGISTRA (uma vez) o listener after_begin do seam (D2). Sem
# este import a suite de integracao rodaria isolada e o seam nao estaria plugado.
import app.db.session  # noqa: F401
from app.db.rls import set_tenant_context, set_tenant_context_for_igreja
from app.db.rls_observability import probe_tenant_scope
from app.db.tenant_session import (
    TenantPromotionError,
    mark_cross_tenant,
    mark_tenant_scoped,
    promote_to_tenant,
)

# Fixtures/constantes vindas do modulo opt-in (nao e um conftest.py, logo
# importadas explicitamente). noqa: F401 — sao usadas como fixtures do pytest.
from tests.conftest_rls import (  # noqa: F401
    CLERK_A,
    CLERK_B,
    IGREJA_A,
    IGREJA_B,
    rls_database_url,
    rls_engine,
    rls_seeded,
)


class _SeamBase(DeclarativeBase):
    """Base ORM local (isolada do Base do app) para o T3 exercitar refresh real
    sobre a tabela minima `pessoas` do banco descartavel."""


class _Pessoa(_SeamBase):
    __tablename__ = "pessoas"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    igreja_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    nome: Mapped[str] = mapped_column()

# Toda a suite exige Postgres real.
pytestmark = pytest.mark.rls_integration


# ---------------------------------------------------------------------------
# Helpers locais
# ---------------------------------------------------------------------------
@pytest.fixture
def make_session(rls_engine: Engine) -> Iterator:
    """Fabrica de sessoes que sempre faz rollback (isola cada checagem).

    Cada sessao abre uma transacao no papel de conexao (owner/BYPASSRLS); o
    teste dropa para `authenticated` via set_tenant_context_for_igreja ou
    `set local role authenticated` conforme o cenario. O rollback no fim reverte
    o SET LOCAL ROLE e o GUC, sem vazar estado entre checagens.
    """
    factory = sessionmaker(bind=rls_engine, future=True)

    sessions: list[Session] = []

    def _open() -> Session:
        session = factory()
        sessions.append(session)
        return session

    try:
        yield _open
    finally:
        for session in sessions:
            session.rollback()
            session.close()


def _pessoa_igrejas(session: Session) -> list[str]:
    rows = session.execute(text("select igreja_id from pessoas")).scalars().all()
    return [str(r) for r in rows]


# ---------------------------------------------------------------------------
# T1 — sem contexto, nada vaza
# ---------------------------------------------------------------------------
def test_t1_authenticated_without_context_reads_nothing(
    rls_seeded: dict[str, str], make_session
) -> None:
    session = make_session()
    # Papel authenticated (NOBYPASSRLS), porem SEM contexto de tenant.
    session.execute(text("set local role authenticated"))
    assert _pessoa_igrejas(session) == []

    # Contexto fixado numa igreja INEXISTENTE => 0 linhas.
    set_tenant_context_for_igreja(session, str(uuid.uuid4()))
    assert _pessoa_igrejas(session) == []


# ---------------------------------------------------------------------------
# T2 — isolamento A<->B
# ---------------------------------------------------------------------------
def test_t2_tenant_isolation_a_sees_only_a(
    rls_seeded: dict[str, str], make_session
) -> None:
    session = make_session()
    set_tenant_context_for_igreja(session, IGREJA_A)
    igrejas = _pessoa_igrejas(session)
    assert igrejas, "igreja A deveria enxergar ao menos a propria linha"
    assert all(v == IGREJA_A for v in igrejas)
    assert IGREJA_B not in igrejas


def test_t2_tenant_isolation_b_sees_only_b(
    rls_seeded: dict[str, str], make_session
) -> None:
    session = make_session()
    set_tenant_context_for_igreja(session, IGREJA_B)
    igrejas = _pessoa_igrejas(session)
    assert igrejas, "igreja B deveria enxergar ao menos a propria linha"
    assert all(v == IGREJA_B for v in igrejas)
    assert IGREJA_A not in igrejas


# ---------------------------------------------------------------------------
# T3 — PR2 seam: leitura pos-commit reabre o escopo via o listener after_begin
# ---------------------------------------------------------------------------
def test_t3_seam_reopens_scope_after_commit(
    rls_seeded: dict[str, str], make_session
) -> None:
    session = make_session()
    # Marca a sessao no tenant A (aplica o escopo na transacao atual).
    mark_tenant_scoped(session, IGREJA_A, actor_sub=CLERK_A, source="test-t3")
    pessoa = session.execute(select(_Pessoa)).scalars().one()
    assert str(pessoa.igreja_id) == IGREJA_A

    # commit() reverte o SET LOCAL ROLE e o GUC (transaction-local). Sem o seam,
    # uma leitura pos-commit rodaria no papel de conexao (BYPASSRLS).
    session.commit()

    # Nova transacao: o listener after_begin reaplica o escopo de A. Exercita
    # refresh() E uma query nova reais (nao apenas atributo ja carregado).
    session.refresh(pessoa)
    assert str(pessoa.igreja_id) == IGREJA_A

    igrejas = _pessoa_igrejas(session)
    assert igrejas, "apos commit o seam deve reabrir o escopo e ver A"
    assert all(v == IGREJA_A for v in igrejas)
    assert IGREJA_B not in igrejas  # isolamento preservado pos-commit

    signal = probe_tenant_scope(session)
    assert signal.is_scoped is True
    assert signal.role == "authenticated"
    assert signal.igreja_id == IGREJA_A


# ---------------------------------------------------------------------------
# T4 — PR3-B: caminho do worker (fase cross-tenant -> promocao) tenant-scoped
# ---------------------------------------------------------------------------
def test_t4_worker_cross_tenant_then_promote_is_scoped(
    rls_seeded: dict[str, str], make_session
) -> None:
    """Replica o seam do worker (ingest): fase cross-tenant (lookup por
    instance) roda em BYPASSRLS; apos promote_to_tenant, as leituras ficam
    escopadas a igreja alvo e NAO enxergam outros tenants."""
    session = make_session()

    # Fase 1 (D4): cross-tenant explicito. No papel de conexao (BYPASSRLS) a
    # sessao enxerga AMBAS as igrejas — e assim o worker acha a WhatsappConnection
    # de qualquer instance antes de conhecer a igreja.
    mark_cross_tenant(session, source="test-t4-ingest")
    assert {IGREJA_A, IGREJA_B} <= set(_pessoa_igrejas(session))
    unscoped = probe_tenant_scope(session)
    assert unscoped.is_scoped is False

    # Fase 2 (D4): promocao explicita ao tenant A. A ordem virou estrutura.
    promote_to_tenant(session, IGREJA_A, source="test-t4-ingest")

    igrejas = _pessoa_igrejas(session)
    assert igrejas, "apos promover, a sessao deve ver a igreja A"
    assert all(v == IGREJA_A for v in igrejas)
    assert IGREJA_B not in igrejas  # isolamento pos-promocao

    scoped = probe_tenant_scope(session)
    assert scoped.is_scoped is True
    assert scoped.role == "authenticated"
    assert scoped.igreja_id == IGREJA_A


def test_t4_promote_without_cross_tenant_phase_fails(
    rls_seeded: dict[str, str], make_session
) -> None:
    """Promover uma sessao que NAO passou pela fase cross-tenant FALHA: a ordem
    'lookup-antes-de-promocao' e uma invariante executavel (nao um comentario)."""
    session = make_session()
    with pytest.raises(TenantPromotionError):
        promote_to_tenant(session, IGREJA_A, source="test-t4-no-phase")


def test_t4_promote_to_different_igreja_after_pin_fails(
    rls_seeded: dict[str, str], make_session
) -> None:
    """Pinning (D3): uma sessao ja pinada num tenant NAO pode ser promovida a
    outra igreja."""
    session = make_session()
    mark_cross_tenant(session, source="test-t4-pin")
    promote_to_tenant(session, IGREJA_A, source="test-t4-pin")
    # Ja pinada em A: promover para B FALHA (nao re-fixa silenciosamente).
    with pytest.raises(TenantPromotionError):
        promote_to_tenant(session, IGREJA_B, source="test-t4-pin")


# ---------------------------------------------------------------------------
# T5 / T6 — sinal de observabilidade read-only
# ---------------------------------------------------------------------------
def test_t5_probe_reports_unscoped_for_connection_role(
    rls_seeded: dict[str, str], make_session
) -> None:
    session = make_session()
    # Papel de conexao (owner/BYPASSRLS), sem SET ROLE e sem GUC de tenant.
    signal = probe_tenant_scope(session)
    assert signal.is_scoped is False
    assert signal.role != "authenticated"
    assert signal.igreja_id is None


def test_t6_probe_reports_scoped_for_authenticated(
    rls_seeded: dict[str, str], make_session
) -> None:
    session = make_session()
    set_tenant_context_for_igreja(session, IGREJA_A)
    signal = probe_tenant_scope(session)
    assert signal.is_scoped is True
    assert signal.role == "authenticated"
    assert signal.igreja_id == IGREJA_A


# ---------------------------------------------------------------------------
# T5-seam — sem vazamento de role/GUC pelo pool de conexoes
# ---------------------------------------------------------------------------
def test_t5_seam_no_role_guc_leak_via_pool(
    rls_seeded: dict[str, str], rls_database_url: str
) -> None:
    # Pool de 1 conexao (sem overflow): s1 e s2 reusam a MESMA conexao fisica.
    engine = create_engine(
        rls_database_url, pool_size=1, max_overflow=0, future=True
    )
    try:
        factory = sessionmaker(bind=engine, future=True)

        s1 = factory()
        mark_tenant_scoped(s1, IGREJA_A, source="test-t5")
        assert probe_tenant_scope(s1).igreja_id == IGREJA_A
        # close() faz rollback: SET LOCAL ROLE e GUC revertem por transacao; a
        # conexao volta ao pool no papel de conexao (BYPASSRLS), sem escopo.
        s1.close()

        # s2 pega a MESMA conexao, SEM marca: nao pode herdar o escopo de A.
        s2 = factory()
        try:
            signal = probe_tenant_scope(s2)
            assert signal.is_scoped is False
            assert signal.role != "authenticated"
            assert signal.igreja_id is None
            # Papel de conexao (BYPASSRLS) enxerga AMBAS as igrejas — prova de
            # que a sessao nova NAO ficou presa no escopo de A.
            igrejas = set(_pessoa_igrejas(s2))
            assert {IGREJA_A, IGREJA_B} <= igrejas
        finally:
            s2.close()
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# T6-seam — listener fail-closed: reaplicar o escopo falha => transacao cai
# ---------------------------------------------------------------------------
def test_t6_seam_listener_fail_closed(
    rls_seeded: dict[str, str], rls_engine: Engine
) -> None:
    factory = sessionmaker(bind=rls_engine, future=True)
    session = factory()
    # 1) Escopo aplicado normalmente (papel authenticated existe).
    mark_tenant_scoped(session, IGREJA_A, source="test-t6")
    assert probe_tenant_scope(session).igreja_id == IGREJA_A
    session.commit()  # reverte SET LOCAL; session.info permanece marcada

    admin = rls_engine.connect()
    renamed = False
    try:
        # 2) Remove o papel `authenticated` (rename e transacional/reversivel).
        admin.exec_driver_sql(
            "alter role authenticated rename to authenticated_off_t6"
        )
        admin.commit()
        renamed = True

        # 3) Nova transacao dispara o listener -> 'set local role authenticated'
        # falha (papel ausente). Fail-closed: a excecao PROPAGA e a transacao
        # cai — NUNCA segue silenciosamente em BYPASSRLS.
        with pytest.raises(DBAPIError):
            session.execute(select(_Pessoa)).scalars().all()
    finally:
        session.rollback()
        session.close()
        if renamed:
            admin.exec_driver_sql(
                "alter role authenticated_off_t6 rename to authenticated"
            )
            admin.commit()
        admin.close()


# ---------------------------------------------------------------------------
# Prova de coexistencia: 1 caminho HTTP read-only + 1 leitura do worker rodam
# com a sessao marcada pelo seam, junto do contexto legado (mesmo tenant). PR2
# nao remove nenhum ensure_tenant_context — apenas prova o seam ao lado dele.
# ---------------------------------------------------------------------------
def test_seam_http_readonly_path_coexists(
    rls_seeded: dict[str, str], make_session
) -> None:
    session = make_session()
    # Legado HTTP (ensure_tenant_context): claim Clerk resolve o tenant A.
    set_tenant_context(session, CLERK_A)
    assert probe_tenant_scope(session).igreja_id == IGREJA_A

    # Seam (novo): marca A. Coexiste com o claim — ambos produzem o mesmo tenant.
    mark_tenant_scoped(
        session, IGREJA_A, actor_sub=CLERK_A, actor_role="pastor", source="http-proof"
    )
    signal = probe_tenant_scope(session)
    assert signal.is_scoped is True
    assert signal.igreja_id == IGREJA_A

    igrejas = _pessoa_igrejas(session)
    assert igrejas and all(v == IGREJA_A for v in igrejas)
    assert IGREJA_B not in igrejas


def test_seam_worker_readonly_path_coexists(
    rls_seeded: dict[str, str], make_session
) -> None:
    session = make_session()
    # Legado do worker (set_tenant_context_for_igreja): GUC escopa o tenant B.
    set_tenant_context_for_igreja(session, IGREJA_B)
    assert probe_tenant_scope(session).igreja_id == IGREJA_B

    # Seam (novo): marca B. Coexistencia idempotente — mesmo tenant.
    mark_tenant_scoped(session, IGREJA_B, source="worker-proof")
    signal = probe_tenant_scope(session)
    assert signal.is_scoped is True
    assert signal.igreja_id == IGREJA_B

    igrejas = _pessoa_igrejas(session)
    assert igrejas and all(v == IGREJA_B for v in igrejas)
    assert IGREJA_A not in igrejas
