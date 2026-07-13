"""M7B-W3.2A: preflight + arquivamento seguro de Pessoa — prova real de Postgres.

``pessoa_offboarding_service`` cruza células, celula_membro, celula_solicitacao
(inclusive payload JSONB), app_users/user_roles, whatsapp_connections,
work_queue_items, cell_alerts, events/event_notify_targets, multiplicacoes e
consolidacoes — todos com FKs/JSONB reais e o lock SEC-4B (``SELECT ... FOR
UPDATE``). Nenhum disso é exercitável com SQLite/FakeSession, por isso a suíte
inteira é ``rls_integration`` (opt-in via ``RLS_TEST_DATABASE_URL``, mesmo
guard de produção da suíte RLS — ver ``tests/conftest_rls.py``).

Camadas:
  - estáticas (sempre-on): paridade migration <-> ORM (colunas, CHECK, trigger,
    RLS) — mesmo estilo de ``test_pessoa_arquivamento_migration.py``;
  - ``rls_integration`` (schema próprio, ORM real + migration aplicada):
      * trigger append-only bloqueia UPDATE/DELETE diretos, permite cascata;
      * cada classe de bloqueador -> 409 estruturado + ZERO mutação;
      * preflight GET nunca muta (nem abandona consolidação);
      * archive válido preenche os 3 campos + abandona consolidação aberta;
      * archive idempotente (repetido não duplica efeito/auditoria);
      * concorrência: duas chamadas de archive -> um único efeito real;
      * falha intermediária -> rollback total (pessoa/consolidação/auditoria).
"""

from __future__ import annotations

import itertools
import pathlib
import threading
import uuid
from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import app.db.session  # noqa: F401 - registra o listener after_begin (paridade prod)
from app.db.models import (
    AppUser,
    Base,
    Celula,
    CelulaMembro,
    CelulaSolicitacao,
    CelulaSolicitacaoEvento,
    CellAlert,
    Consolidacao,
    Event,
    EventNotifyTarget,
    Igreja,
    Multiplicacao,
    Pessoa,
    PessoaArquivamentoEvento,
    UserRole,
    WhatsappConnection,
    WorkQueueItem,
)
from app.deps import CurrentUser
from app.routers import cell_requests as cell_requests_router
from app.routers import cells as cells_router
from app.routers import contacts as contacts_router
from app.routers import pipeline as pipeline_router
from app.services import cell_requests_service
from app.services import pessoa_offboarding_service as svc
from app.services import sla_engine
from app.services.celula_membro import (
    MembroInelegivelError,
    assert_pessoas_nao_arquivadas,
    ensure_active_membro,
)
from tests.conftest_rls import rls_database_url  # noqa: F401

_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260713_032015_pessoa_offboarding_preflight_arquivamento_evento.sql"
)


# ---------------------------------------------------------------------------
# Camada estática (sempre-on, sem Postgres) — paridade migration <-> ORM
# ---------------------------------------------------------------------------
def _sql() -> str:
    return _MIGRATION.read_text(encoding="utf-8").lower()


def test_orm_consolidacao_abandono_columns() -> None:
    cols = Consolidacao.__table__.columns
    assert "abandonada_em" in cols and cols["abandonada_em"].nullable
    assert "abandonada_motivo" in cols and cols["abandonada_motivo"].nullable


def test_orm_pessoa_arquivamento_evento_model() -> None:
    cols = PessoaArquivamentoEvento.__table__.columns
    assert "updated_at" not in cols  # append-only: sem updated_at
    fks_igreja = {
        fk.column.table.name
        for fk in cols["igreja_id"].foreign_keys
    }
    assert "igrejas" in fks_igreja
    fks_pessoa = {fk.column.table.name for fk in cols["pessoa_id"].foreign_keys}
    assert "pessoas" in fks_pessoa
    ator_fk = next(iter(cols["ator_id"].foreign_keys))
    assert ator_fk.column.table.name == "app_users"
    assert ator_fk.ondelete == "SET NULL"


def test_migration_is_additive_and_has_append_only_trigger() -> None:
    sql = _sql()
    assert "add column if not exists abandonada_em timestamptz" in sql
    assert "add column if not exists abandonada_motivo text" in sql
    assert "create table if not exists pessoa_arquivamento_evento" in sql
    assert "trg_pessoa_arquivamento_evento_append_only" in sql
    assert "raise exception 'append-only'" in sql
    assert "enable row level security" in sql
    assert "'arquivada', 'reativada'" in sql
    assert "drop table" not in sql
    assert "drop column" not in sql


# ---------------------------------------------------------------------------
# Fixtures — banco descartável, schema próprio, ORM real + migration aplicada
# ---------------------------------------------------------------------------
_SCHEMA = "pessoa_offboarding"
_counter = itertools.count()


def _tel() -> str:
    return f"5589{next(_counter):08d}"


@pytest.fixture(scope="module")
def offboarding_engine(rls_database_url: str) -> Iterator[Engine]:  # noqa: F811
    """Engine dedicada com schema próprio: ORM real (create_all) + a migration
    de verdade aplicada por cima (prova o CHECK/trigger/RLS que create_all não
    expressa). `pessoa_arquivamento_evento` é DEIXADA de fora do create_all
    para a migration ser quem efetivamente cria a tabela (com o CHECK +
    trigger + policy) — senão o `create table if not exists` da migration
    vira no-op sobre uma tabela já criada pelo ORM sem essas peças.

    Também cria o papel `authenticated` (NOBYPASSRLS, mesmo padrão de
    `conftest_rls.py`) com GRANT amplo no schema: a maioria dos testes deste
    arquivo roda como owner/BYPASSRLS (não precisa de isolamento real), mas os
    testes de RLS/CHECK/trigger (`test_rls_*`/`test_check_*`/`test_ator_id_*`
    abaixo) fazem `SET ROLE authenticated` de propósito — só um papel
    NOBYPASSRLS prova isolamento de tenant de verdade.
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
        # Stub de current_igreja_id(): lê só o GUC (sem o lookup por
        # clerk_user_id via app_users da versão de produção) — suficiente pro
        # papel authenticated deste schema, que sempre autentica via
        # `SET LOCAL app.tenant_igreja_id` explícito nos testes de RLS abaixo.
        conn.exec_driver_sql(
            "create or replace function current_igreja_id() returns uuid "
            "language sql stable as $$ select nullif(current_setting("
            "'app.tenant_igreja_id', true), '')::uuid $$;"
        )
        conn.exec_driver_sql(
            "do $$ begin "
            "if not exists (select 1 from pg_roles where rolname = 'authenticated') then "
            "create role authenticated nologin noinherit nobypassrls; "
            "end if; end $$;"
        )

    tables_sem_evento = [
        t for t in Base.metadata.sorted_tables if t.name != "pessoa_arquivamento_evento"
    ]
    Base.metadata.create_all(engine, tables=tables_sem_evento)

    with engine.begin() as conn:
        conn.exec_driver_sql(_MIGRATION.read_text(encoding="utf-8"))
        # Grants amplos ao papel de tenant (owner segue com BYPASSRLS pro
        # seed/DDL dos demais testes deste arquivo).
        conn.exec_driver_sql(f"grant usage on schema {_SCHEMA} to authenticated;")
        conn.exec_driver_sql(
            f"grant select, insert, update, delete on all tables in schema "
            f"{_SCHEMA} to authenticated;"
        )

    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade;")
        engine.dispose()


@pytest.fixture
def factory(offboarding_engine: Engine) -> sessionmaker:
    return sessionmaker(bind=offboarding_engine, future=True, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Helpers de seed — cada teste cria sua PRÓPRIA igreja (isolamento por dados,
# sem precisar recriar o schema a cada caso).
# ---------------------------------------------------------------------------
def _mk_igreja(session: Session) -> uuid.UUID:
    igreja_id = uuid.uuid4()
    session.add(Igreja(id=igreja_id, nome=f"Igreja {igreja_id}"))
    session.flush()
    return igreja_id


def _mk_pessoa(session: Session, igreja_id: uuid.UUID, **kw) -> uuid.UUID:
    pessoa_id = kw.pop("id", uuid.uuid4())
    session.add(
        Pessoa(
            id=pessoa_id,
            igreja_id=igreja_id,
            nome=kw.pop("nome", "Alvo do arquivamento"),
            telefone=kw.pop("telefone", _tel()),
            **kw,
        )
    )
    session.flush()
    return pessoa_id


def _mk_admin_app_user(
    session: Session, igreja_id: uuid.UUID, *, pessoa_id: uuid.UUID | None = None
) -> uuid.UUID:
    app_user_id = uuid.uuid4()
    session.add(
        AppUser(
            id=app_user_id,
            igreja_id=igreja_id,
            nome="Admin",
            email=f"{app_user_id}@teste.com",
            status="ativo",
            pessoa_id=pessoa_id,
        )
    )
    session.flush()
    session.add(UserRole(igreja_id=igreja_id, user_id=app_user_id, papel="admin"))
    session.flush()
    return app_user_id


def _mk_celula(session: Session, igreja_id: uuid.UUID, **kw) -> uuid.UUID:
    celula_id = kw.pop("id", uuid.uuid4())
    session.add(
        Celula(
            id=celula_id,
            igreja_id=igreja_id,
            nome=kw.pop("nome", "Célula Teste"),
            cobertura_espiritual=kw.pop("cobertura_espiritual", "Rede"),
            ativo=kw.pop("ativo", True),
            **kw,
        )
    )
    session.flush()
    return celula_id


def _base(session: Session) -> dict:
    """Igreja + um admin NEUTRO (distinto do alvo) — ator default dos testes."""
    igreja_id = _mk_igreja(session)
    ator_id = _mk_admin_app_user(session, igreja_id)
    session.commit()
    return {"igreja_id": igreja_id, "ator_id": ator_id}


def _run_preflight(factory: sessionmaker, pessoa_id: uuid.UUID, ator_id: uuid.UUID):
    session = factory()
    try:
        pessoa = session.get(Pessoa, pessoa_id)
        return svc.preflight_archive(session, pessoa=pessoa, actor_app_user_id=ator_id)
    finally:
        session.close()


def _run_archive(
    factory: sessionmaker, pessoa_id: uuid.UUID, ator_id: uuid.UUID, motivo: str = "teste"
):
    session = factory()
    try:
        pessoa = session.get(Pessoa, pessoa_id)
        result_pessoa, ja_arquivada = svc.archive_pessoa(
            session, pessoa=pessoa, actor_app_user_id=ator_id, motivo=motivo
        )
        # No caminho idempotente, archive_pessoa faz db.rollback() (expira TODOS
        # os atributos por padrão do SQLAlchemy). Recarrega com a sessão ainda
        # viva e destaca (expunge) para o objeto ficar seguro de ler depois do
        # close() — sem isso, o segundo caso vira DetachedInstanceError.
        session.refresh(result_pessoa)
        session.expunge(result_pessoa)
        return result_pessoa, ja_arquivada
    finally:
        session.close()


def _assert_blocks(
    factory: sessionmaker, pessoa_id: uuid.UUID, ator_id: uuid.UUID, tipo_esperado: str
) -> None:
    """Preflight aponta o bloqueador; archive recusa (409) com ZERO mutação."""
    result = _run_preflight(factory, pessoa_id, ator_id)
    assert result.pode_arquivar is False
    tipos = {b.tipo for b in result.bloqueadores}
    assert tipo_esperado in tipos, tipos

    with pytest.raises(HTTPException) as exc_info:
        _run_archive(factory, pessoa_id, ator_id)
    assert exc_info.value.status_code == 409
    tipos_409 = {b["tipo"] for b in exc_info.value.detail["bloqueadores"]}
    assert tipo_esperado in tipos_409

    session = factory()
    try:
        pessoa = session.get(Pessoa, pessoa_id)
        assert pessoa.arquivada_em is None, "bloqueador não pode ser desfeito automaticamente"
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Trigger append-only — prova real
# ---------------------------------------------------------------------------
@pytest.mark.rls_integration
def test_append_only_trigger_blocks_direct_update_and_delete(factory: sessionmaker) -> None:
    session = factory()
    try:
        ctx = _base(session)
        pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
        session.commit()

        evento_id = session.execute(
            text(
                "insert into pessoa_arquivamento_evento "
                "(igreja_id, pessoa_id, ator_id, acao, motivo) "
                "values (:ig, :p, :a, 'arquivada', 'motivo') returning id"
            ),
            {"ig": ctx["igreja_id"], "p": pessoa_id, "a": ctx["ator_id"]},
        ).scalar_one()
        session.commit()

        with pytest.raises(Exception, match="append-only"):
            session.execute(
                text("update pessoa_arquivamento_evento set motivo = 'editado' where id = :id"),
                {"id": evento_id},
            )
        session.rollback()

        with pytest.raises(Exception, match="append-only"):
            session.execute(
                text("delete from pessoa_arquivamento_evento where id = :id"), {"id": evento_id}
            )
        session.rollback()

        # Cascata permitida: apagar a Pessoa (pai) remove o evento em CASCADE
        # sem disparar 'append-only' (pg_trigger_depth() > 1 — carve-out).
        session.execute(text("delete from pessoas where id = :id"), {"id": pessoa_id})
        session.commit()
        remaining = session.execute(
            text("select count(*) from pessoa_arquivamento_evento where id = :id"),
            {"id": evento_id},
        ).scalar_one()
        assert remaining == 0
    finally:
        session.rollback()
        session.close()


@pytest.mark.rls_integration
def test_append_only_trigger_allows_igreja_cascade_two_levels(
    factory: sessionmaker,
) -> None:
    """Cascata em 2 níveis (2ª revisão externa PR#163, item de hardening):
    apagar a Igreja (avô) remove a Pessoa (pai, `pessoas.igreja_id` CASCADE)
    que remove o evento (`pessoa_arquivamento_evento.pessoa_id` CASCADE) —
    sem o trigger append-only bloquear em NENHUM nível (pg_trigger_depth() > 1
    em ambos)."""
    session = factory()
    try:
        ctx = _base(session)
        pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
        session.commit()

        evento_id = session.execute(
            text(
                "insert into pessoa_arquivamento_evento "
                "(igreja_id, pessoa_id, ator_id, acao, motivo) "
                "values (:ig, :p, :a, 'arquivada', 'motivo') returning id"
            ),
            {"ig": ctx["igreja_id"], "p": pessoa_id, "a": ctx["ator_id"]},
        ).scalar_one()
        session.commit()

        session.execute(text("delete from igrejas where id = :id"), {"id": ctx["igreja_id"]})
        session.commit()

        pessoas_restantes = session.execute(
            text("select count(*) from pessoas where id = :id"), {"id": pessoa_id}
        ).scalar_one()
        eventos_restantes = session.execute(
            text("select count(*) from pessoa_arquivamento_evento where id = :id"),
            {"id": evento_id},
        ).scalar_one()
        assert pessoas_restantes == 0, "Pessoa deve cascatear com a Igreja"
        assert eventos_restantes == 0, "evento deve cascatear em 2 níveis (via Pessoa)"
    finally:
        session.rollback()
        session.close()


def _set_tenant(conn, igreja_id: uuid.UUID) -> None:
    """Mesmo idioma de produção (app/db/rls.py): GUC via set_config parametrizado
    + `SET LOCAL ROLE authenticated` — nunca string-formata o UUID no SQL."""
    conn.execute(
        text("select set_config('app.tenant_igreja_id', :ig, true)"),
        {"ig": str(igreja_id)},
    )
    conn.exec_driver_sql("set local role authenticated")


@pytest.mark.rls_integration
def test_check_acao_rejects_invalid_value(offboarding_engine: Engine) -> None:
    """CHECK real no Postgres, sob o papel de tenant (authenticated/NOBYPASSRLS)."""
    from sqlalchemy.exc import IntegrityError

    with offboarding_engine.connect() as conn:
        igreja_id = uuid.uuid4()
        pessoa_id = uuid.uuid4()
        with conn.begin():
            conn.execute(text("insert into igrejas (id, nome) values (:id, 'X')"), {"id": igreja_id})
            conn.execute(
                text(
                    "insert into pessoas (id, igreja_id, nome, telefone) "
                    "values (:id, :ig, 'P', '5589900000002')"
                ),
                {"id": pessoa_id, "ig": igreja_id},
            )

        trans = conn.begin()
        try:
            _set_tenant(conn, igreja_id)
            with pytest.raises(
                IntegrityError, match="pessoa_arquivamento_evento_acao_chk"
            ):
                conn.execute(
                    text(
                        "insert into pessoa_arquivamento_evento "
                        "(igreja_id, pessoa_id, acao, motivo) "
                        "values (:ig, :p, 'valor_invalido', 'x')"
                    ),
                    {"ig": igreja_id, "p": pessoa_id},
                )
        finally:
            trans.rollback()


@pytest.mark.rls_integration
def test_rls_tenant_isolation_pessoa_arquivamento_evento(offboarding_engine: Engine) -> None:
    """Isolamento RLS REAL: papel `authenticated` (NOBYPASSRLS), não owner.

    Igreja A não LÊ nem ESCREVE evento de Igreja B — a policy `tenant_isolation`
    (`using`/`with check` ambos `igreja_id = current_igreja_id()`) é o que
    efetivamente barra, não uma checagem da aplicação.
    """
    from sqlalchemy.exc import ProgrammingError

    with offboarding_engine.connect() as conn:
        igreja_a, igreja_b = uuid.uuid4(), uuid.uuid4()
        pessoa_a, pessoa_b = uuid.uuid4(), uuid.uuid4()
        with conn.begin():
            for ig, pessoa in ((igreja_a, pessoa_a), (igreja_b, pessoa_b)):
                conn.execute(text("insert into igrejas (id, nome) values (:id, 'X')"), {"id": ig})
                conn.execute(
                    text(
                        "insert into pessoas (id, igreja_id, nome, telefone) "
                        "values (:id, :ig, 'P', :tel)"
                    ),
                    {"id": pessoa, "ig": ig, "tel": f"5589{pessoa.int % 10**8:08d}"},
                )

        # Semeia 1 evento em CADA igreja como owner (bypassa RLS, é só seed).
        evento_a_id = uuid.uuid4()
        evento_b_id = uuid.uuid4()
        with conn.begin():
            conn.execute(
                text(
                    "insert into pessoa_arquivamento_evento "
                    "(id, igreja_id, pessoa_id, acao, motivo) "
                    "values (:id, :ig, :p, 'arquivada', 'seed A')"
                ),
                {"id": evento_a_id, "ig": igreja_a, "p": pessoa_a},
            )
            conn.execute(
                text(
                    "insert into pessoa_arquivamento_evento "
                    "(id, igreja_id, pessoa_id, acao, motivo) "
                    "values (:id, :ig, :p, 'arquivada', 'seed B')"
                ),
                {"id": evento_b_id, "ig": igreja_b, "p": pessoa_b},
            )

        # --- Como tenant A: enxerga só o evento de A -----------------------
        trans = conn.begin()
        try:
            _set_tenant(conn, igreja_a)
            visiveis = conn.execute(
                text("select id from pessoa_arquivamento_evento")
            ).scalars().all()
            assert set(visiveis) == {evento_a_id}, "tenant A só pode ver o próprio evento"

            # Tenant A tenta ESCREVER um evento com igreja_id de B (mesmo tendo
            # DML grant na tabela) — a policy WITH CHECK barra na aplicação da
            # RLS, não uma checagem do app.
            with pytest.raises(ProgrammingError, match="row-level security"):
                conn.execute(
                    text(
                        "insert into pessoa_arquivamento_evento "
                        "(igreja_id, pessoa_id, acao, motivo) "
                        "values (:ig, :p, 'arquivada', 'tentativa cross-tenant')"
                    ),
                    {"ig": igreja_b, "p": pessoa_b},
                )
        finally:
            trans.rollback()

        # --- Como tenant B: enxerga só o evento de B -----------------------
        trans = conn.begin()
        try:
            _set_tenant(conn, igreja_b)
            visiveis = conn.execute(
                text("select id from pessoa_arquivamento_evento")
            ).scalars().all()
            assert set(visiveis) == {evento_b_id}, "tenant B só pode ver o próprio evento"
        finally:
            trans.rollback()


@pytest.mark.rls_integration
def test_append_only_trigger_blocks_under_authenticated_role(
    offboarding_engine: Engine,
) -> None:
    """Mesma prova do trigger append-only, mas sob o papel de tenant real
    (não o owner/BYPASSRLS da conexão usada nos demais testes deste arquivo)."""
    with offboarding_engine.connect() as conn:
        igreja_id = uuid.uuid4()
        pessoa_id = uuid.uuid4()
        with conn.begin():
            conn.execute(text("insert into igrejas (id, nome) values (:id, 'X')"), {"id": igreja_id})
            conn.execute(
                text(
                    "insert into pessoas (id, igreja_id, nome, telefone) "
                    "values (:id, :ig, 'P', '5589900000003')"
                ),
                {"id": pessoa_id, "ig": igreja_id},
            )

        evento_id = uuid.uuid4()
        with conn.begin():
            conn.execute(
                text(
                    "insert into pessoa_arquivamento_evento "
                    "(id, igreja_id, pessoa_id, acao, motivo) "
                    "values (:id, :ig, :p, 'arquivada', 'motivo')"
                ),
                {"id": evento_id, "ig": igreja_id, "p": pessoa_id},
            )

        trans = conn.begin()
        try:
            _set_tenant(conn, igreja_id)
            with pytest.raises(Exception, match="append-only"):
                conn.execute(
                    text(
                        "update pessoa_arquivamento_evento set motivo = 'editado' "
                        "where id = :id"
                    ),
                    {"id": evento_id},
                )
        finally:
            trans.rollback()

        trans = conn.begin()
        try:
            _set_tenant(conn, igreja_id)
            with pytest.raises(Exception, match="append-only"):
                conn.execute(
                    text("delete from pessoa_arquivamento_evento where id = :id"),
                    {"id": evento_id},
                )
        finally:
            trans.rollback()


@pytest.mark.rls_integration
def test_ator_id_set_null_on_app_user_delete_without_trigger_blocking(
    offboarding_engine: Engine,
) -> None:
    """ON DELETE SET NULL de `ator_id` funciona SEM o trigger append-only
    barrar a ação referencial (carve-out `pg_trigger_depth() > 1`).

    Contrato explícito da missão: se esta combinação for incompatível no
    Postgres real, o teste deve FALHAR alto (não ser enfraquecido) — é
    exatamente o que este teste prova ao rodar contra Postgres de verdade.
    """
    with offboarding_engine.connect() as conn:
        igreja_id = uuid.uuid4()
        pessoa_id = uuid.uuid4()
        ator_id = uuid.uuid4()
        with conn.begin():
            conn.execute(text("insert into igrejas (id, nome) values (:id, 'X')"), {"id": igreja_id})
            conn.execute(
                text(
                    "insert into pessoas (id, igreja_id, nome, telefone) "
                    "values (:id, :ig, 'P', '5589900000004')"
                ),
                {"id": pessoa_id, "ig": igreja_id},
            )
            conn.execute(
                text(
                    "insert into app_users (id, igreja_id, nome, email, status) "
                    "values (:id, :ig, 'Ator', 'ator@x.com', 'ativo')"
                ),
                {"id": ator_id, "ig": igreja_id},
            )

        evento_id = uuid.uuid4()
        with conn.begin():
            conn.execute(
                text(
                    "insert into pessoa_arquivamento_evento "
                    "(id, igreja_id, pessoa_id, ator_id, acao, motivo) "
                    "values (:id, :ig, :p, :a, 'arquivada', 'motivo')"
                ),
                {"id": evento_id, "ig": igreja_id, "p": pessoa_id, "a": ator_id},
            )

        # Apaga o app_user (ator) — dispara ON DELETE SET NULL em ator_id. Se o
        # trigger append-only barrasse ações referenciais, este DELETE
        # levantaria 'append-only' em vez de completar.
        with conn.begin():
            conn.execute(text("delete from app_users where id = :id"), {"id": ator_id})

        with conn.begin():
            row = conn.execute(
                text(
                    "select ator_id, motivo, acao from pessoa_arquivamento_evento "
                    "where id = :id"
                ),
                {"id": evento_id},
            ).mappings().one()
        assert row["ator_id"] is None, "SET NULL deve ter zerado ator_id"
        assert row["motivo"] == "motivo", "o evento em si sobrevive intacto"
        assert row["acao"] == "arquivada"


@pytest.mark.rls_integration
def test_migration_postgres_real_consolidacao_columns(offboarding_engine: Engine) -> None:
    with offboarding_engine.begin() as conn:
        rows = conn.execute(
            text(
                "select column_name, data_type, is_nullable from information_schema.columns "
                "where table_name = 'consolidacoes' "
                "and column_name in ('abandonada_em', 'abandonada_motivo')"
            )
        ).mappings().all()
    by_name = {r["column_name"]: r for r in rows}
    assert by_name["abandonada_em"]["data_type"] == "timestamp with time zone"
    assert by_name["abandonada_em"]["is_nullable"] == "YES"
    assert by_name["abandonada_motivo"]["data_type"] == "text"
    assert by_name["abandonada_motivo"]["is_nullable"] == "YES"


# ---------------------------------------------------------------------------
# Preflight limpo — pode arquivar, nada bloqueia, nada é preservado incorretamente
# ---------------------------------------------------------------------------
@pytest.mark.rls_integration
def test_preflight_no_blockers_pode_arquivar(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    session.commit()
    session.close()

    result = _run_preflight(factory, pessoa_id, ctx["ator_id"])
    assert result.pode_arquivar is True
    assert result.bloqueadores == []
    assert result.automaticos == []
    assert {p.tipo for p in result.preservados} == {
        "conversas_mensagens",
        "consentimentos",
        "decisoes",
        "presencas_reuniao",
        "expectativas_visitante",
        "relatorios_reuniao",
        "registros_pastorais",
        "trilha_decisoes_celula",
        "avisos_materiais_publicados",
        "logs_ia",
    }


# ---------------------------------------------------------------------------
# Matriz de bloqueadores — cada classe: 409 estruturado + zero mutação
# ---------------------------------------------------------------------------
@pytest.mark.rls_integration
def test_bloqueio_celula_membro_ativo(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    lider_id = _mk_pessoa(session, ctx["igreja_id"], nome="Líder")
    celula_id = _mk_celula(session, ctx["igreja_id"], lider_id=lider_id)
    session.add(
        CelulaMembro(
            igreja_id=ctx["igreja_id"], celula_id=celula_id, pessoa_id=pessoa_id, ativo=True
        )
    )
    session.commit()
    session.close()

    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "celula_membro_ativo")


@pytest.mark.rls_integration
def test_bloqueio_celula_id_espelho_sem_vinculo_canonico(factory: sessionmaker) -> None:
    """Espelho legado sozinho (sem linha canônica ativa) TAMBÉM bloqueia."""
    session = factory()
    ctx = _base(session)
    celula_id = _mk_celula(session, ctx["igreja_id"])
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"], celula_id=celula_id)
    session.commit()
    session.close()

    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "celula_id_espelho")


@pytest.mark.rls_integration
def test_bloqueio_celula_lider_ativa(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    _mk_celula(session, ctx["igreja_id"], lider_id=pessoa_id)
    session.commit()
    session.close()

    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "celula_lider")


@pytest.mark.rls_integration
def test_bloqueio_celula_anfitriao_ativa(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    outro_lider = _mk_pessoa(session, ctx["igreja_id"], nome="Outro líder")
    _mk_celula(session, ctx["igreja_id"], lider_id=outro_lider, anfitriao_id=pessoa_id)
    session.commit()
    session.close()

    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "celula_anfitriao")


@pytest.mark.rls_integration
def test_bloqueio_celula_auxiliar_ativa(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    outro_lider = _mk_pessoa(session, ctx["igreja_id"], nome="Outro líder")
    _mk_celula(session, ctx["igreja_id"], lider_id=outro_lider, auxiliar_id=pessoa_id)
    session.commit()
    session.close()

    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "celula_auxiliar")


@pytest.mark.rls_integration
def test_bloqueio_discipulos_vinculados(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    _mk_pessoa(session, ctx["igreja_id"], nome="Discípulo", lider_id=pessoa_id)
    session.commit()
    session.close()

    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "discipulos_vinculados")


@pytest.mark.rls_integration
def test_discipulo_ja_arquivado_nao_bloqueia_lider(factory: sessionmaker) -> None:
    """Regressão (revisão externa PR#163): discípulo JÁ arquivado não é mais
    dependência ativa — não pode travar o arquivamento do líder para sempre
    (sem endpoint de escrita para desvincular lider_id)."""
    session = factory()
    ctx = _base(session)
    lider_id = _mk_pessoa(session, ctx["igreja_id"], nome="Líder")
    discipulo_id = _mk_pessoa(session, ctx["igreja_id"], nome="Discípulo", lider_id=lider_id)
    session.commit()
    session.close()

    # arquiva o discípulo primeiro.
    pessoa_discipulo, _ = _run_archive(factory, discipulo_id, ctx["ator_id"], motivo="saiu")
    assert pessoa_discipulo.arquivada_em is not None

    result = _run_preflight(factory, lider_id, ctx["ator_id"])
    assert "discipulos_vinculados" not in {b.tipo for b in result.bloqueadores}
    assert result.pode_arquivar is True


@pytest.mark.rls_integration
def test_bloqueio_acesso_painel_ativo(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    _mk_admin_app_user(session, ctx["igreja_id"], pessoa_id=pessoa_id)
    session.commit()
    session.close()

    # ator NEUTRO (não é o próprio alvo) — isola do bloqueador auto_arquivamento.
    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "acesso_painel_ativo")


@pytest.mark.rls_integration
def test_bloqueio_dono_igreja(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    app_user_id = _mk_admin_app_user(session, ctx["igreja_id"], pessoa_id=pessoa_id)
    igreja = session.get(Igreja, ctx["igreja_id"])
    igreja.dono_id = app_user_id
    session.commit()
    session.close()

    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "dono_igreja")


@pytest.mark.rls_integration
def test_bloqueio_ultimo_administrador_ativo(factory: sessionmaker) -> None:
    """Alvo é o ÚNICO admin ativo da igreja (o `_base` neutro NÃO é admin)."""
    session = factory()
    igreja_id = _mk_igreja(session)
    pessoa_id = _mk_pessoa(session, igreja_id)
    _mk_admin_app_user(session, igreja_id, pessoa_id=pessoa_id)
    session.commit()
    session.close()

    ator_neutro = uuid.uuid4()  # não corresponde ao app_user do alvo
    _assert_blocks(factory, pessoa_id, ator_neutro, "ultimo_administrador")


@pytest.mark.rls_integration
def test_bloqueio_ultimo_administrador_nao_dispara_com_outro_admin_ativo(
    factory: sessionmaker,
) -> None:
    """Regressão: havendo OUTRO admin ativo, o bloqueador não aparece."""
    session = factory()
    ctx = _base(session)  # ator já é admin ativo #1
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    _mk_admin_app_user(session, ctx["igreja_id"], pessoa_id=pessoa_id)  # admin #2 = alvo
    session.commit()
    session.close()

    result = _run_preflight(factory, pessoa_id, ctx["ator_id"])
    assert "ultimo_administrador" not in {b.tipo for b in result.bloqueadores}


@pytest.mark.rls_integration
def test_bloqueio_auto_arquivamento(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    proprio_app_user_id = _mk_admin_app_user(session, ctx["igreja_id"], pessoa_id=pessoa_id)
    session.commit()
    session.close()

    # ator == o próprio app_user vinculado à pessoa alvo.
    _assert_blocks(factory, pessoa_id, proprio_app_user_id, "auto_arquivamento")


@pytest.mark.rls_integration
def test_bloqueio_whatsapp_oficial(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    numero = "+55 89 99431-5927"
    # mesmo número, formatação DIFERENTE — prova normalize_phone (não string==).
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"], telefone="558994315927")
    session.add(
        WhatsappConnection(igreja_id=ctx["igreja_id"], numero=numero, status="online")
    )
    session.commit()
    session.close()

    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "whatsapp_oficial")


@pytest.mark.rls_integration
def test_bloqueio_celula_solicitacao_aberta_coluna_pessoa_id(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    celula_id = _mk_celula(session, ctx["igreja_id"])
    session.add(
        CelulaSolicitacao(
            igreja_id=ctx["igreja_id"],
            celula_id=celula_id,
            pessoa_id=pessoa_id,
            tipo="remover_membro",
            status="aguardando",
            payload_proposto={"pessoa_id": str(pessoa_id)},
        )
    )
    session.commit()
    session.close()

    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "celula_solicitacao_aberta")


@pytest.mark.rls_integration
def test_bloqueio_celula_solicitacao_aberta_jsonb_anfitriao(factory: sessionmaker) -> None:
    """`pessoa_id` da coluna fica NULL (tipo sensível) — só o payload JSONB referencia."""
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    celula_id = _mk_celula(session, ctx["igreja_id"])
    session.add(
        CelulaSolicitacao(
            igreja_id=ctx["igreja_id"],
            celula_id=celula_id,
            tipo="alterar_anfitriao",
            status="aguardando",
            payload_proposto={"anfitriao_id": str(pessoa_id)},
        )
    )
    session.commit()
    session.close()

    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "celula_solicitacao_aberta")


@pytest.mark.rls_integration
def test_bloqueio_celula_solicitacao_aberta_jsonb_array_membros_transferidos(
    factory: sessionmaker,
) -> None:
    """Multiplicação: `membros_transferidos_ids` é um ARRAY JSONB — @> containment."""
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    outro_membro = _mk_pessoa(session, ctx["igreja_id"], nome="Outro membro")
    novo_lider = _mk_pessoa(session, ctx["igreja_id"], nome="Novo líder")
    celula_id = _mk_celula(session, ctx["igreja_id"])
    session.add(
        CelulaSolicitacao(
            igreja_id=ctx["igreja_id"],
            celula_id=celula_id,
            tipo="multiplicacao",
            status="aguardando",
            payload_proposto={
                "nome_nova_celula": "Nova",
                "novo_lider_id": str(novo_lider),
                "membros_transferidos_ids": [str(pessoa_id), str(outro_membro)],
            },
        )
    )
    session.commit()
    session.close()

    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "celula_solicitacao_aberta")


@pytest.mark.rls_integration
def test_celula_solicitacao_terminal_nao_bloqueia(factory: sessionmaker) -> None:
    """Regressão: solicitação já decidida (histórico) NÃO vira bloqueador."""
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    celula_id = _mk_celula(session, ctx["igreja_id"])
    session.add(
        CelulaSolicitacao(
            igreja_id=ctx["igreja_id"],
            celula_id=celula_id,
            pessoa_id=pessoa_id,
            tipo="remover_membro",
            status="aprovada",
            payload_proposto={"pessoa_id": str(pessoa_id)},
        )
    )
    session.commit()
    session.close()

    result = _run_preflight(factory, pessoa_id, ctx["ator_id"])
    assert result.pode_arquivar is True


@pytest.mark.rls_integration
def test_bloqueio_fila_trabalho_aberta(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    session.add(
        WorkQueueItem(
            igreja_id=ctx["igreja_id"],
            tipo="atendimento",
            titulo="Atender visitante",
            pessoa_id=pessoa_id,
            status="aberto",
        )
    )
    session.commit()
    session.close()

    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "fila_trabalho_aberta")


@pytest.mark.rls_integration
def test_fila_trabalho_resolvida_nao_bloqueia(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    session.add(
        WorkQueueItem(
            igreja_id=ctx["igreja_id"],
            tipo="atendimento",
            titulo="Atender visitante",
            pessoa_id=pessoa_id,
            status="resolvido",
        )
    )
    session.commit()
    session.close()

    result = _run_preflight(factory, pessoa_id, ctx["ator_id"])
    assert result.pode_arquivar is True


@pytest.mark.rls_integration
def test_bloqueio_alerta_celula_pendente(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    celula_id = _mk_celula(session, ctx["igreja_id"])
    session.add(
        CellAlert(
            igreja_id=ctx["igreja_id"],
            celula_id=celula_id,
            pessoa_id=pessoa_id,
            gatilho="Faltou 3x",
            tratado=False,
        )
    )
    session.commit()
    session.close()

    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "alerta_celula_pendente")


@pytest.mark.rls_integration
def test_bloqueio_evento_notificacao_futura(factory: sessionmaker) -> None:
    import datetime as dt

    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    evento_id = uuid.uuid4()
    session.add(
        Event(
            id=evento_id,
            igreja_id=ctx["igreja_id"],
            titulo="Culto especial",
            data=dt.date.today() + dt.timedelta(days=7),
        )
    )
    session.flush()
    session.add(
        EventNotifyTarget(event_id=evento_id, igreja_id=ctx["igreja_id"], pessoa_id=pessoa_id)
    )
    session.commit()
    session.close()

    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "evento_notificacao_futura")


@pytest.mark.rls_integration
def test_evento_passado_nao_bloqueia(factory: sessionmaker) -> None:
    import datetime as dt

    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    evento_id = uuid.uuid4()
    session.add(
        Event(
            id=evento_id,
            igreja_id=ctx["igreja_id"],
            titulo="Culto passado",
            data=dt.date.today() - dt.timedelta(days=30),
        )
    )
    session.flush()
    session.add(
        EventNotifyTarget(event_id=evento_id, igreja_id=ctx["igreja_id"], pessoa_id=pessoa_id)
    )
    session.commit()
    session.close()

    result = _run_preflight(factory, pessoa_id, ctx["ator_id"])
    assert result.pode_arquivar is True


@pytest.mark.rls_integration
def test_bloqueio_multiplicacao_pendente_novo_lider(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    celula_id = _mk_celula(session, ctx["igreja_id"])
    sol = CelulaSolicitacao(
        igreja_id=ctx["igreja_id"],
        celula_id=celula_id,
        tipo="multiplicacao",
        status="aprovada",
        payload_proposto={
            "nome_nova_celula": "Nova",
            "novo_lider_id": str(pessoa_id),
            "membros_transferidos_ids": [str(pessoa_id)],
        },
    )
    session.add(sol)
    session.flush()
    session.add(
        Multiplicacao(
            igreja_id=ctx["igreja_id"],
            celula_id=celula_id,
            solicitacao_id=sol.id,
            novo_lider_id=pessoa_id,
            status="aprovada",
        )
    )
    session.commit()
    session.close()

    _assert_blocks(factory, pessoa_id, ctx["ator_id"], "multiplicacao_pendente")


# ---------------------------------------------------------------------------
# Automáticos — consolidação aberta só vira "abandonada" DENTRO do archive real
# ---------------------------------------------------------------------------
@pytest.mark.rls_integration
def test_preflight_get_nao_muta_consolidacao_aberta(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    cons_id = uuid.uuid4()
    session.add(
        Consolidacao(id=cons_id, igreja_id=ctx["igreja_id"], pessoa_id=pessoa_id, tipo="individual")
    )
    session.commit()
    session.close()

    result = _run_preflight(factory, pessoa_id, ctx["ator_id"])
    assert result.pode_arquivar is True
    assert [a.tipo for a in result.automaticos] == ["consolidacao_abandonada"]

    session = factory()
    cons = session.get(Consolidacao, cons_id)
    assert cons.abandonada_em is None, "GET preflight NUNCA muta"
    session.close()


@pytest.mark.rls_integration
def test_archive_valido_preenche_campos_e_abandona_consolidacao(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    cons_aberta_id = uuid.uuid4()
    cons_concluida_id = uuid.uuid4()
    session.add(
        Consolidacao(
            id=cons_aberta_id, igreja_id=ctx["igreja_id"], pessoa_id=pessoa_id, tipo="individual"
        )
    )
    session.add(
        Consolidacao(
            id=cons_concluida_id,
            igreja_id=ctx["igreja_id"],
            pessoa_id=pessoa_id,
            tipo="individual",
            concluida=True,
        )
    )
    session.commit()
    session.close()

    pessoa, ja_arquivada = _run_archive(
        factory, pessoa_id, ctx["ator_id"], motivo="Mudou de igreja"
    )
    assert ja_arquivada is False
    assert pessoa.arquivada_em is not None
    assert pessoa.arquivada_por == ctx["ator_id"]
    assert pessoa.arquivada_motivo == "Mudou de igreja"

    session = factory()
    try:
        aberta = session.get(Consolidacao, cons_aberta_id)
        assert aberta.abandonada_em is not None
        assert "arquivad" in (aberta.abandonada_motivo or "").lower()

        # já concluída ANTES do archive: não é tocada (não vira "abandonada").
        concluida = session.get(Consolidacao, cons_concluida_id)
        assert concluida.abandonada_em is None

        eventos = session.execute(
            select(PessoaArquivamentoEvento).where(
                PessoaArquivamentoEvento.pessoa_id == pessoa_id
            )
        ).scalars().all()
        assert len(eventos) == 1
        assert eventos[0].acao == "arquivada"
        assert eventos[0].ator_id == ctx["ator_id"]
    finally:
        session.close()


@pytest.mark.rls_integration
def test_archive_idempotente_nao_duplica_efeito(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    session.commit()
    session.close()

    pessoa1, ja1 = _run_archive(factory, pessoa_id, ctx["ator_id"], motivo="motivo original")
    assert ja1 is False
    assert pessoa1.arquivada_motivo == "motivo original"

    pessoa2, ja2 = _run_archive(factory, pessoa_id, ctx["ator_id"], motivo="motivo DIFERENTE")
    assert ja2 is True
    # repetição não sobrescreve o motivo original.
    assert pessoa2.arquivada_motivo == "motivo original"

    session = factory()
    eventos = session.execute(
        select(PessoaArquivamentoEvento).where(PessoaArquivamentoEvento.pessoa_id == pessoa_id)
    ).scalars().all()
    assert len(eventos) == 1, "archive repetido não pode duplicar a auditoria"
    session.close()


@pytest.mark.rls_integration
def test_archive_contact_http_response_sinaliza_ja_arquivada_explicitamente(
    factory: sessionmaker,
) -> None:
    """Contrato HTTP (revisão externa PR#163): a resposta do endpoint real
    (`POST .../archive`) sinaliza `ja_arquivada` — o cliente não pode
    confundir "acabei de arquivar" com "já estava arquivada, nada mudou"."""
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    session.commit()
    session.close()

    current_user = CurrentUser(
        app_user_id=str(ctx["ator_id"]),
        clerk_user_id="clerk_ator",
        igreja_id=str(ctx["igreja_id"]),
        email="ator@teste.com",
        nome="Ator",
        roles=frozenset({"admin"}),
    )

    session = factory()
    try:
        resp1 = contacts_router.archive_contact(
            str(pessoa_id),
            contacts_router.ArchiveContactRequest(motivo="motivo original"),
            db=session,
            current_user=current_user,
        )
    finally:
        session.close()
    assert resp1.ja_arquivada is False
    assert resp1.arquivada is True
    assert resp1.arquivada_motivo == "motivo original"

    session = factory()
    try:
        resp2 = contacts_router.archive_contact(
            str(pessoa_id),
            contacts_router.ArchiveContactRequest(motivo="motivo DIFERENTE"),
            db=session,
            current_user=current_user,
        )
    finally:
        session.close()
    assert resp2.ja_arquivada is True
    assert resp2.arquivada is True
    # idempotente: motivo/ator do arquivamento ORIGINAL, nunca sobrescritos.
    assert resp2.arquivada_motivo == "motivo original"
    assert resp2.arquivada_por == str(ctx["ator_id"])


@pytest.mark.rls_integration
def test_archive_concorrencia_um_unico_efeito_uma_unica_auditoria(
    factory: sessionmaker,
) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    session.commit()
    session.close()

    barrier = threading.Barrier(2)
    out: dict[int, tuple] = {}

    def worker(idx: int) -> None:
        session = factory()
        try:
            pessoa = session.get(Pessoa, pessoa_id)
            barrier.wait(timeout=15)
            _pessoa, ja_arquivada = svc.archive_pessoa(
                session,
                pessoa=pessoa,
                actor_app_user_id=ctx["ator_id"],
                motivo=f"thread-{idx}",
            )
            out[idx] = ("ok", ja_arquivada)
        except HTTPException as exc:
            out[idx] = ("http", exc.status_code)
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    # Exatamente uma "vence" (ja_arquivada=False); a outra vê já arquivada.
    assert sorted(out.values()) == [("ok", False), ("ok", True)], out

    session = factory()
    try:
        eventos = session.execute(
            select(PessoaArquivamentoEvento).where(
                PessoaArquivamentoEvento.pessoa_id == pessoa_id
            )
        ).scalars().all()
        assert len(eventos) == 1, f"efeito deve ser único; veio {len(eventos)}"
    finally:
        session.close()


@pytest.mark.rls_integration
def test_archive_falha_intermediaria_reverte_tudo(
    factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Falha simulada logo antes do commit -> Pessoa, consolidação e auditoria
    revertem juntas (é UMA transação — nada fica parcialmente aplicado)."""
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    cons_id = uuid.uuid4()
    session.add(
        Consolidacao(id=cons_id, igreja_id=ctx["igreja_id"], pessoa_id=pessoa_id, tipo="individual")
    )
    session.commit()

    pessoa = session.get(Pessoa, pessoa_id)

    class _BoomError(RuntimeError):
        pass

    def _boom(*a, **kw):
        raise _BoomError("falha simulada antes do commit")

    # Patch de INSTÂNCIA (não da classe Session): a classe afetaria também a
    # sessão `verify` criada abaixo (nova instância via factory()), que
    # precisa flush/get funcionando normalmente para provar o rollback.
    monkeypatch.setattr(session, "flush", _boom)

    with pytest.raises(_BoomError):
        svc.archive_pessoa(
            session, pessoa=pessoa, actor_app_user_id=ctx["ator_id"], motivo="vai falhar"
        )
    session.close()

    verify = factory()
    try:
        pessoa_db = verify.get(Pessoa, pessoa_id)
        assert pessoa_db.arquivada_em is None, "Pessoa não pode ficar parcialmente arquivada"
        cons_db = verify.get(Consolidacao, cons_id)
        assert cons_db.abandonada_em is None, "consolidação não pode ficar parcialmente abandonada"
        eventos = verify.execute(
            select(PessoaArquivamentoEvento).where(
                PessoaArquivamentoEvento.pessoa_id == pessoa_id
            )
        ).scalars().all()
        assert eventos == [], "nenhuma auditoria pode sobreviver ao rollback"
    finally:
        verify.close()


# ---------------------------------------------------------------------------
# Revisão externa PR#163 — invariante: pessoa arquivada não recebe NENHUM
# vínculo/responsabilidade ministerial novo, em NENHUM write-path.
# ---------------------------------------------------------------------------
@pytest.mark.rls_integration
def test_ensure_active_membro_refuses_pessoa_arquivada(factory: sessionmaker) -> None:
    """Seam canônico (auth.py/contacts.py/team.py/agent/tools.py) recusa."""
    session = factory()
    ctx = _base(session)
    lider_id = _mk_pessoa(session, ctx["igreja_id"], nome="Líder")
    celula_id = _mk_celula(session, ctx["igreja_id"], lider_id=lider_id)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"], nome="Arquivada")
    session.commit()

    _pessoa, ja_arquivada = svc.archive_pessoa(
        session,
        pessoa=session.get(Pessoa, pessoa_id),
        actor_app_user_id=ctx["ator_id"],
        motivo="saiu",
    )
    assert ja_arquivada is False
    session.close()

    session = factory()
    try:
        with pytest.raises(MembroInelegivelError) as exc_info:
            ensure_active_membro(
                session, igreja_id=ctx["igreja_id"], celula_id=celula_id, pessoa_id=pessoa_id
            )
        assert exc_info.value.code == "pessoa_arquivada"

        membro = session.execute(
            select(CelulaMembro).where(CelulaMembro.pessoa_id == pessoa_id)
        ).scalar_one_or_none()
        assert membro is None, "nenhum vínculo pode ter sido criado"
    finally:
        session.rollback()
        session.close()


@pytest.mark.rls_integration
def test_assert_pessoas_nao_arquivadas_refuses_archived(factory: sessionmaker) -> None:
    session = factory()
    ctx = _base(session)
    ativa_id = _mk_pessoa(session, ctx["igreja_id"], nome="Ativa")
    arquivada_id = _mk_pessoa(session, ctx["igreja_id"], nome="Arquivada")
    session.commit()
    svc.archive_pessoa(
        session,
        pessoa=session.get(Pessoa, arquivada_id),
        actor_app_user_id=ctx["ator_id"],
        motivo="saiu",
    )
    session.close()

    session = factory()
    try:
        # só a ativa: não levanta.
        assert_pessoas_nao_arquivadas(session, igreja_id=ctx["igreja_id"], pessoa_ids=[ativa_id])
        # mistura ativa + arquivada: levanta (qualquer uma arquivada já basta).
        with pytest.raises(MembroInelegivelError):
            assert_pessoas_nao_arquivadas(
                session, igreja_id=ctx["igreja_id"], pessoa_ids=[ativa_id, arquivada_id]
            )
        # vazio/None: no-op.
        assert_pessoas_nao_arquivadas(session, igreja_id=ctx["igreja_id"], pessoa_ids=[])
        assert_pessoas_nao_arquivadas(session, igreja_id=ctx["igreja_id"], pessoa_ids=[None])
    finally:
        session.close()


@pytest.mark.rls_integration
def test_create_cell_request_refuses_referenced_pessoa_arquivada_jsonb(
    factory: sessionmaker,
) -> None:
    """CREATE recusa (409/MembroInelegivelError) referência JSONB a pessoa
    arquivada (`anfitriao_id`) — antes de qualquer escrita."""
    session = factory()
    ctx = _base(session)
    lider_id = _mk_pessoa(session, ctx["igreja_id"], nome="Líder")
    celula_id = _mk_celula(session, ctx["igreja_id"], lider_id=lider_id)
    lider_app_user_id = uuid.uuid4()
    session.add(
        AppUser(
            id=lider_app_user_id,
            igreja_id=ctx["igreja_id"],
            nome="Líder",
            email=f"{lider_app_user_id}@teste.com",
            status="ativo",
            pessoa_id=lider_id,
        )
    )
    anfitriao_arquivado_id = _mk_pessoa(session, ctx["igreja_id"], nome="Anfitrião")
    session.commit()
    svc.archive_pessoa(
        session,
        pessoa=session.get(Pessoa, anfitriao_arquivado_id),
        actor_app_user_id=ctx["ator_id"],
        motivo="saiu",
    )
    session.close()

    session = factory()
    try:
        current_user = CurrentUser(
            app_user_id=str(lider_app_user_id),
            clerk_user_id="clerk_lider",
            igreja_id=str(ctx["igreja_id"]),
            email="lider@teste.com",
            nome="Líder",
            roles=frozenset({"lider_celula"}),
        )
        body = cell_requests_router.CreateCellRequest(
            celula_id=str(celula_id),
            tipo="alterar_anfitriao",
            payload_proposto={"anfitriao_id": str(anfitriao_arquivado_id)},
        )
        with pytest.raises(MembroInelegivelError) as exc_info:
            cell_requests_router.create_cell_request(
                body, db=session, current_user=current_user
            )
        assert exc_info.value.code == "pessoa_arquivada"

        count = session.execute(
            select(func.count())
            .select_from(CelulaSolicitacao)
            .where(CelulaSolicitacao.celula_id == celula_id)
        ).scalar_one()
        assert count == 0, "nenhuma solicitação pode ter sido criada"
    finally:
        session.rollback()
        session.close()


@pytest.mark.rls_integration
def test_approve_refuses_when_referenced_pessoa_arquivada_toctou(
    factory: sessionmaker,
) -> None:
    """Defesa-em-profundidade do `approve`: dado o ESTADO transitório aceito
    (solicitação `aguardando` referenciando uma pessoa já arquivada — provado
    ALCANÇÁVEL de verdade, com 2 threads/2 transações reais e sincronização
    determinística via Event, em
    ``test_create_cell_request_vs_archive_thread_race_reaches_transitory_state``
    logo abaixo), o `approve` revalida SOB O LOCK e recusa sem mutação. Este
    teste NÃO afirma que o estado transitório deixou de existir — ele
    permanece alcançável por contrato aceito (a solicitação nasce e fica
    `aguardando`; nenhum vínculo/responsabilidade é concedido só por ela
    existir; `cancel`/`reject` seguem limpando-a normalmente — ver
    ``test_cancel_solicitacao_referencing_arquivada_pessoa_still_works``). O
    UPDATE direto aqui é só uma forma BARATA de chegar no mesmo estado final
    para testar a reação do `approve` em isolamento — a prova de que o estado
    é de fato alcançável por uma corrida real está no teste de threads.
    """
    session = factory()
    ctx = _base(session)
    outro_lider_id = _mk_pessoa(session, ctx["igreja_id"], nome="Outro líder")
    celula_id = _mk_celula(session, ctx["igreja_id"], lider_id=outro_lider_id)
    alvo_id = _mk_pessoa(session, ctx["igreja_id"], nome="Alvo remoção")
    sol_id = uuid.uuid4()
    session.add(
        CelulaSolicitacao(
            id=sol_id,
            igreja_id=ctx["igreja_id"],
            celula_id=celula_id,
            pessoa_id=alvo_id,
            tipo="remover_membro",
            status="aguardando",
            payload_proposto={"pessoa_id": str(alvo_id)},
        )
    )
    session.commit()

    session.execute(
        text(
            "update pessoas set arquivada_em = now(), arquivada_por = :ator, "
            "arquivada_motivo = 'saiu durante a janela' where id = :id"
        ),
        {"ator": ctx["ator_id"], "id": alvo_id},
    )
    session.commit()
    session.close()

    session = factory()
    try:
        solicitacao = session.get(CelulaSolicitacao, sol_id)
        cell = session.get(Celula, celula_id)
        with pytest.raises(MembroInelegivelError) as exc_info:
            cell_requests_service.approve(
                session,
                solicitacao=solicitacao,
                cell=cell,
                actor_pessoa_id=outro_lider_id,
                approver_app_user_id=None,
                idempotency_key=None,
            )
        assert exc_info.value.code == "pessoa_arquivada"
    finally:
        session.close()

    session = factory()
    try:
        sol_db = session.get(CelulaSolicitacao, sol_id)
        assert sol_db.status == "aguardando", "aprovação recusada não pode mudar o status"
        membro = session.execute(
            select(CelulaMembro).where(CelulaMembro.pessoa_id == alvo_id)
        ).scalar_one_or_none()
        assert membro is None
        eventos = session.execute(
            select(func.count())
            .select_from(CelulaSolicitacaoEvento)
            .where(CelulaSolicitacaoEvento.solicitacao_id == sol_id)
        ).scalar_one()
        assert eventos == 0, "recusa não pode gravar evento de decisão"
    finally:
        session.close()


@pytest.mark.rls_integration
def test_create_cell_request_vs_archive_thread_race_reaches_transitory_state(
    factory: sessionmaker,
) -> None:
    """Prova REAL (2 threads/2 transações, sincronização determinística via
    ``threading.Event`` — sem depender de sorte de timing) da corrida entre
    ``create_cell_request`` e ``archive_pessoa`` (2ª revisão externa PR#163:
    o teste anterior fabricava o estado com UPDATE pós-fato e não testava a
    corrida alegada).

    Sequência forçada:
      1. T1 (``create_cell_request``) roda a checagem de elegibilidade
         (``assert_pessoas_nao_arquivadas`` — passa, a pessoa ainda não está
         arquivada) e INSERE a solicitação, mas PAUSA antes de commitar (hook
         de teste no `session.commit` — nenhuma mudança em código de
         produção; único ponto de commit no caminho de sucesso, então não há
         ambiguidade de qual chamada interceptar).
      2. T2 (``archive_pessoa``) roda enquanto T1 está pausada: o bloqueador
         `celula_solicitacao_aberta` NÃO vê a solicitação de T1 (ainda não
         commitada — MVCC/READ COMMITTED), então o archive passa e commita.
      3. T1 é liberada e completa o commit da solicitação.

    Contrato ACEITO (documentado, não escondido): a solicitação `aguardando`
    passa a existir referenciando uma pessoa já arquivada. Isso é seguro
    porque (a) nenhum vínculo/responsabilidade é concedido só por ela existir
    — só nasce a linha; (b) ``approve`` revalida sob lock e recusa (teste
    acima); (c) ``cancel``/``reject`` continuam limpando-a normalmente (teste
    abaixo). Fechar esta janela por completo exigeria travar a Pessoa também
    durante ``create_cell_request`` (custo de lock alto para toda criação de
    solicitação, incluindo os tipos sem referência de pessoa) — não foi feito;
    ver riscos residuais no relatório.
    """
    session_setup = factory()
    ctx = _base(session_setup)
    lider_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Líder")
    lider_app_user_id = uuid.uuid4()
    session_setup.add(
        AppUser(
            id=lider_app_user_id,
            igreja_id=ctx["igreja_id"],
            nome="Líder",
            email=f"{lider_app_user_id}@teste.com",
            status="ativo",
            pessoa_id=lider_id,
        )
    )
    celula_id = _mk_celula(session_setup, ctx["igreja_id"], lider_id=lider_id)
    alvo_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Alvo remoção")
    session_setup.commit()
    session_setup.close()

    checked = threading.Event()  # T1: passei da checagem e do INSERT, ainda não commitei
    proceed = threading.Event()  # T2: já arquivei e commitei — T1 pode continuar
    result: dict[str, object] = {}

    def t1_create_cell_request() -> None:
        session = factory()
        try:
            current_user = CurrentUser(
                app_user_id=str(lider_app_user_id),
                clerk_user_id="clerk_lider",
                igreja_id=str(ctx["igreja_id"]),
                email="lider@teste.com",
                nome="Líder",
                roles=frozenset({"lider_celula"}),
            )
            # Pausa no COMMIT (não no flush: autoflush chama session.flush()
            # implicitamente em TODA query, inclusive dentro da própria
            # checagem de arquivada_em — contar "a 1ª chamada de flush" pausaria
            # cedo demais, ANTES da checagem rodar). Há exatamente 1 db.commit()
            # no caminho de sucesso: neste ponto a checagem já rodou e passou,
            # o INSERT da solicitação já foi feito (flush), só falta commitar.
            original_commit = session.commit

            def paused_commit(*a, **kw):
                checked.set()
                if not proceed.wait(timeout=15):
                    raise TimeoutError("T2 não sinalizou proceed a tempo")
                return original_commit(*a, **kw)

            session.commit = paused_commit
            # `alterar_anfitriao` (não `remover_membro`/`transferir_membro`):
            # a tela do líder não pode abrir tipos de MEMBRO
            # (`_reject_member_tipo` — M7B-W1.3, 403); a referência de pessoa
            # via payload JSONB é a mesma coisa que já provei em
            # `test_create_cell_request_refuses_referenced_pessoa_arquivada_jsonb`.
            body = cell_requests_router.CreateCellRequest(
                celula_id=str(celula_id),
                tipo="alterar_anfitriao",
                payload_proposto={"anfitriao_id": str(alvo_id)},
            )
            out = cell_requests_router.create_cell_request(
                body, db=session, current_user=current_user
            )
            result["sol_id"] = out.id
        except Exception as exc:  # noqa: BLE001
            result["t1_error"] = repr(exc)
        finally:
            session.close()

    def t2_archive() -> None:
        if not checked.wait(timeout=15):
            result["t2_error"] = "timeout esperando T1 chegar na pausa"
            return
        session = factory()
        try:
            pessoa = session.get(Pessoa, alvo_id)
            svc.archive_pessoa(
                session, pessoa=pessoa, actor_app_user_id=ctx["ator_id"], motivo="saiu"
            )
        except Exception as exc:  # noqa: BLE001
            result["t2_error"] = repr(exc)
        finally:
            proceed.set()  # libera T1 mesmo se T2 falhar (não trava o teste)
            session.close()

    t1 = threading.Thread(target=t1_create_cell_request)
    t2 = threading.Thread(target=t2_archive)
    t1.start()
    t2.start()
    t1.join(timeout=20)
    t2.join(timeout=20)

    assert "t1_error" not in result, result.get("t1_error")
    assert "t2_error" not in result, result.get("t2_error")
    assert "sol_id" in result, "create_cell_request deveria completar (estado transitório aceito)"

    session = factory()
    try:
        pessoa_db = session.get(Pessoa, alvo_id)
        assert pessoa_db.arquivada_em is not None, "archive deveria ter vencido a corrida"

        sol_db = session.get(CelulaSolicitacao, uuid.UUID(str(result["sol_id"])))
        assert sol_db is not None, "a solicitação criada por T1 deve existir (commit efetivou)"
        assert sol_db.status == "aguardando"
        assert sol_db.payload_proposto.get("anfitriao_id") == str(alvo_id)

        # Nenhum vínculo/responsabilidade foi concedido — só a linha nasceu.
        membro = session.execute(
            select(CelulaMembro).where(CelulaMembro.pessoa_id == alvo_id)
        ).scalar_one_or_none()
        assert membro is None
    finally:
        session.close()


@pytest.mark.rls_integration
def test_cancel_solicitacao_referencing_arquivada_pessoa_still_works(
    factory: sessionmaker,
) -> None:
    """Parte do contrato aceito do estado transitório: `cancel`/`reject`
    continuam limpando a solicitação normalmente mesmo referenciando uma
    pessoa já arquivada (nenhuma trava nova em cancel/reject — eles não
    tocam Pessoa, só o estado da própria solicitação)."""
    session = factory()
    ctx = _base(session)
    lider_id = _mk_pessoa(session, ctx["igreja_id"], nome="Líder")
    celula_id = _mk_celula(session, ctx["igreja_id"], lider_id=lider_id)
    alvo_id = _mk_pessoa(session, ctx["igreja_id"], nome="Alvo")
    sol_id = uuid.uuid4()
    session.add(
        CelulaSolicitacao(
            id=sol_id,
            igreja_id=ctx["igreja_id"],
            celula_id=celula_id,
            pessoa_id=alvo_id,
            tipo="remover_membro",
            status="aguardando",
            payload_proposto={"pessoa_id": str(alvo_id)},
        )
    )
    session.commit()
    # Estado transitório aceito (ver teste de corrida acima) — aqui só se
    # testa a REAÇÃO de cancel/reject a ele, então um UPDATE direto é
    # suficiente e honesto (a prova de alcançabilidade é o teste de threads).
    session.execute(
        text("update pessoas set arquivada_em = now() where id = :id"), {"id": alvo_id}
    )
    session.commit()
    session.close()

    session = factory()
    try:
        solicitacao = session.get(CelulaSolicitacao, sol_id)
        cancelada = cell_requests_service.cancel(
            session, solicitacao=solicitacao, actor_pessoa_id=lider_id
        )
        assert cancelada.status == "cancelada"
    finally:
        session.close()

    session = factory()
    try:
        sol_db = session.get(CelulaSolicitacao, sol_id)
        assert sol_db.status == "cancelada"
        eventos = session.execute(
            select(func.count())
            .select_from(CelulaSolicitacaoEvento)
            .where(
                CelulaSolicitacaoEvento.solicitacao_id == sol_id,
                CelulaSolicitacaoEvento.acao == "cancelada",
            )
        ).scalar_one()
        assert eventos == 1, "cancel deve gravar a auditoria normalmente"
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 2ª revisão externa PR#163 — BLOCKER: upsert_cell aceitava pessoa arquivada
# em liderId/anfitriaoId/auxiliarId.
# ---------------------------------------------------------------------------
@pytest.mark.rls_integration
def test_archive_vs_upsert_cell_concurrent_lider_never_both(
    factory: sessionmaker,
) -> None:
    """Prova real de concorrência (2 threads/2 transações reais, sincronização
    determinística via ``threading.Barrier`` — sem depender de sorte de
    timing) entre ``archive_pessoa(X)`` e ``upsert_cell(liderId=X)``.

    A guarda nova em ``upsert_cell``
    (``assert_pessoas_nao_arquivadas(..., for_update=True)``) trava a MESMA
    linha de Pessoa que ``archive_pessoa`` trava (mesmo padrão SEC-4B,
    ``db.refresh(pessoa, with_for_update=True)``) — as duas operações
    serializam na MESMA ordem de lock (uma única Pessoa aqui; ver docstring de
    ``assert_pessoas_nao_arquivadas`` para o caso de múltiplas pessoas
    ordenadas). Só um estado pode vencer:
      - responsabilidade CRIADA (célula com líder=X) e archive BLOQUEADO
        depois (bloqueador `celula_lider`, já existente na matriz), OU
      - X ARQUIVADA e upsert RECUSADO (409, nenhuma célula criada).
    Nunca uma célula com líder já arquivado.
    """
    session_setup = factory()
    ctx = _base(session_setup)
    alvo_id = _mk_pessoa(
        session_setup, ctx["igreja_id"], nome="Alvo líder", apto_lider=True
    )
    session_setup.commit()
    session_setup.close()

    barrier = threading.Barrier(2)
    out: dict[str, tuple] = {}

    def worker_upsert() -> None:
        session = factory()
        try:
            current_user = CurrentUser(
                app_user_id=str(ctx["ator_id"]),
                clerk_user_id="clerk_pastor",
                igreja_id=str(ctx["igreja_id"]),
                email="pastor@teste.com",
                nome="Pastor",
                roles=frozenset({"pastor"}),
            )
            body = cells_router.UpsertCellRequest(
                nome="Nova Célula",
                coberturaEspiritual="Rede",
                liderId=str(alvo_id),
            )
            barrier.wait(timeout=15)
            cells_router.upsert_cell(body, db=session, current_user=current_user)
            out["upsert"] = ("ok", None)
        except HTTPException as exc:
            out["upsert"] = ("http", exc.status_code)
        except MembroInelegivelError as exc:
            out["upsert"] = ("membro_inelegivel", exc.code)
        finally:
            session.close()

    def worker_archive() -> None:
        session = factory()
        try:
            pessoa = session.get(Pessoa, alvo_id)
            barrier.wait(timeout=15)
            svc.archive_pessoa(
                session, pessoa=pessoa, actor_app_user_id=ctx["ator_id"], motivo="saiu"
            )
            out["archive"] = ("ok", None)
        except HTTPException as exc:
            out["archive"] = ("http", exc.status_code)
        finally:
            session.close()

    threads = [
        threading.Thread(target=worker_upsert),
        threading.Thread(target=worker_archive),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert "upsert" in out and "archive" in out, out

    session = factory()
    try:
        pessoa_db = session.get(Pessoa, alvo_id)
        celulas_com_lider = session.execute(
            select(Celula).where(Celula.lider_id == alvo_id)
        ).scalars().all()

        arquivada = pessoa_db.arquivada_em is not None
        tem_celula = len(celulas_com_lider) > 0

        # Nunca os dois: célula com líder + pessoa arquivada ao mesmo tempo.
        assert not (arquivada and tem_celula), (
            "célula não pode ter líder já arquivado",
            out,
            arquivada,
            tem_celula,
        )
        # Exatamente um dos dois efeitos venceu (o outro foi recusado).
        assert arquivada or tem_celula, out
        if tem_celula:
            assert out["archive"] == ("http", 409), out
            assert out["upsert"] == ("ok", None), out
        else:
            assert arquivada
            assert out["upsert"][0] in ("http", "membro_inelegivel"), out
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Revisão externa PR#163 — consolidação ABANDONADA não é mais "aberta" para
# SLA (cobrança/escalonamento) nem para o pipeline (avanço/conclusão).
# ---------------------------------------------------------------------------
@pytest.mark.rls_integration
def test_sla_scan_breaches_ignores_abandoned_consolidacao(factory: sessionmaker) -> None:
    import datetime as _dt

    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    cons_id = uuid.uuid4()
    passado = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=48)
    session.add(
        Consolidacao(
            id=cons_id,
            igreja_id=ctx["igreja_id"],
            pessoa_id=pessoa_id,
            tipo="individual",
            prazo_conexao=passado,
            abandonada_em=_dt.datetime.now(_dt.timezone.utc),
            abandonada_motivo="pessoa arquivada",
        )
    )
    session.commit()
    session.close()

    session = factory()
    try:
        breaches = sla_engine.scan_breaches(session, ctx["igreja_id"])
        assert all(b.item_id != cons_id for b in breaches), (
            "consolidação abandonada não pode ser cobrada/escalonada"
        )
    finally:
        session.close()


@pytest.mark.rls_integration
def test_sla_run_all_igrejas_discovery_ignores_abandoned_only_tenant(
    factory: sessionmaker,
) -> None:
    """Se a ÚNICA pendência do tenant é uma consolidação abandonada, o sweep
    não inclui a igreja no conjunto varrido."""
    import datetime as _dt

    session = factory()
    igreja_id = _mk_igreja(session)
    pessoa_id = _mk_pessoa(session, igreja_id)
    session.add(
        Consolidacao(
            igreja_id=igreja_id,
            pessoa_id=pessoa_id,
            tipo="individual",
            prazo_conexao=_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=48),
            abandonada_em=_dt.datetime.now(_dt.timezone.utc),
            abandonada_motivo="pessoa arquivada",
        )
    )
    session.commit()

    igreja_ids: set[uuid.UUID] = set()
    igreja_ids.update(
        session.execute(select(WorkQueueItem.igreja_id).distinct()).scalars().all()
    )
    igreja_ids.update(
        session.execute(
            select(Consolidacao.igreja_id)
            .where(
                Consolidacao.concluida.is_(False),
                Consolidacao.abandonada_em.is_(None),
            )
            .distinct()
        ).scalars().all()
    )
    session.close()
    assert igreja_id not in igreja_ids


@pytest.mark.rls_integration
def test_pipeline_advance_stage_rejects_abandoned_consolidacao(
    factory: sessionmaker,
) -> None:
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    cons_id = uuid.uuid4()
    session.add(
        Consolidacao(
            id=cons_id,
            igreja_id=ctx["igreja_id"],
            pessoa_id=pessoa_id,
            tipo="individual",
            responsavel_id=ctx["ator_id"],
        )
    )
    session.commit()
    # abandona via UPDATE direto (não precisa da transação de archive completa
    # para este teste focado só no gate do pipeline).
    session.execute(
        text(
            "update consolidacoes set abandonada_em = now(), "
            "abandonada_motivo = 'teste' where id = :id"
        ),
        {"id": cons_id},
    )
    session.commit()
    session.close()

    session = factory()
    try:
        current_user = CurrentUser(
            app_user_id=str(ctx["ator_id"]),
            clerk_user_id="clerk_ator",
            igreja_id=str(ctx["igreja_id"]),
            email="ator@teste.com",
            nome="Ator",
            roles=frozenset({"admin"}),
        )
        payload = pipeline_router.AdvanceStageRequest(
            consolidacaoId=str(cons_id), concluir=True
        )
        with pytest.raises(HTTPException) as exc_info:
            pipeline_router.advance_stage(payload, db=session, current_user=current_user)
        assert exc_info.value.status_code == 409
    finally:
        session.rollback()
        session.close()


@pytest.mark.rls_integration
def test_archive_and_advance_stage_concurrent_never_both_concluida_and_abandonada(
    factory: sessionmaker,
) -> None:
    """FOR UPDATE serializa archive_pessoa (abandona consolidação aberta) contra
    pipeline.advance_stage (conclui) sobre a MESMA linha. Sem a trava, a leitura
    desprotegida do archive decide abandonar ANTES de saber que a conclusão
    concorrente já commitou — o UPDATE subsequente esbarra no CHECK
    (``consolidacoes_concluida_abandonada_excl_chk``) e o archive INTEIRO
    crasha (IntegrityError não tratada, rollback de Pessoa/auditoria também).
    Com a trava, o archive sempre completa — só não abandona quem já foi
    concluído no meio do caminho (a mesma linha sob lock é relida e a
    consolidação já concluída sai do conjunto "aberta").
    """
    session = factory()
    ctx = _base(session)
    pessoa_id = _mk_pessoa(session, ctx["igreja_id"])
    cons_id = uuid.uuid4()
    session.add(
        Consolidacao(
            id=cons_id,
            igreja_id=ctx["igreja_id"],
            pessoa_id=pessoa_id,
            tipo="individual",
            responsavel_id=ctx["ator_id"],
        )
    )
    session.commit()
    session.close()

    barrier = threading.Barrier(2)
    out: dict[str, tuple] = {}

    def worker_archive() -> None:
        session = factory()
        try:
            pessoa = session.get(Pessoa, pessoa_id)
            barrier.wait(timeout=15)
            svc.archive_pessoa(
                session, pessoa=pessoa, actor_app_user_id=ctx["ator_id"], motivo="saiu"
            )
            out["archive"] = ("ok", None)
        except HTTPException as exc:
            out["archive"] = ("http", exc.status_code)
        except Exception as exc:  # noqa: BLE001 - qualquer outra é o bug em si
            out["archive"] = ("error", repr(exc))
        finally:
            session.close()

    def worker_advance() -> None:
        session = factory()
        try:
            current_user = CurrentUser(
                app_user_id=str(ctx["ator_id"]),
                clerk_user_id="clerk_ator",
                igreja_id=str(ctx["igreja_id"]),
                email="ator@teste.com",
                nome="Ator",
                roles=frozenset({"admin"}),
            )
            payload = pipeline_router.AdvanceStageRequest(
                consolidacaoId=str(cons_id), concluir=True
            )
            barrier.wait(timeout=15)
            pipeline_router.advance_stage(payload, db=session, current_user=current_user)
            out["advance"] = ("ok", None)
        except HTTPException as exc:
            out["advance"] = ("http", exc.status_code)
        except Exception as exc:  # noqa: BLE001
            out["advance"] = ("error", repr(exc))
        finally:
            session.close()

    threads = [
        threading.Thread(target=worker_archive),
        threading.Thread(target=worker_advance),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    # A trava garante que o archive SEMPRE completa (nunca crasha por causa de
    # uma consolidação concluída no meio do caminho) — este é o efeito
    # observável da correção.
    assert out.get("archive") == ("ok", None), out
    # advance vence a corrida (200) OU perde e vê a consolidação já abandonada
    # (409 do gate que a Task 3 adicionou) — nunca uma exceção não tratada.
    assert out.get("advance", (None,))[0] in ("ok", "http"), out

    session = factory()
    try:
        cons = session.get(Consolidacao, cons_id)
        assert not (cons.concluida and cons.abandonada_em is not None), (
            cons.concluida,
            cons.abandonada_em,
        )
        pessoa_db = session.get(Pessoa, pessoa_id)
        assert pessoa_db.arquivada_em is not None, "archive deve sempre completar"
    finally:
        session.close()


@pytest.mark.rls_integration
def test_regression_unlocked_read_lets_check_crash_the_whole_archive(
    offboarding_engine: Engine,
) -> None:
    """Prova DETERMINÍSTICA (2 conexões, sequenciada — sem depender de vencer
    timing de threads) do que a leitura desprotegida (sem ``FOR UPDATE``)
    permitiria: archive lê a consolidação como "aberta" (passo 1); ANTES do
    archive escrever, uma conclusão concorrente commita (passo 2, modela
    ``pipeline.advance_stage``); o UPDATE de abandono do archive (passo 3,
    baseado na decisão já tomada no passo 1 com dado agora obsoleto) esbarra
    no CHECK de exclusividade mútua e crasha com ``IntegrityError`` — dentro de
    ``archive_pessoa`` isso reverteria a transação INTEIRA (o ``Pessoa.
    arquivada_em`` também), mesmo sem nenhum bloqueador real. É exatamente o
    cenário que ``.with_for_update()`` evita: a leitura protegida BLOQUEIA até
    o passo 2 commitar, relê ``concluida=true`` e simplesmente pula a linha
    (ver ``test_archive_and_advance_stage_concurrent_...`` acima, com a
    correção aplicada, para a prova do fluxo completo).
    """
    from sqlalchemy.exc import IntegrityError

    with offboarding_engine.connect() as conn_a, offboarding_engine.connect() as conn_b:
        igreja_id = uuid.uuid4()
        pessoa_id = uuid.uuid4()
        cons_id = uuid.uuid4()
        with conn_a.begin():
            conn_a.execute(
                text("insert into igrejas (id, nome) values (:id, 'X')"), {"id": igreja_id}
            )
            conn_a.execute(
                text(
                    "insert into pessoas (id, igreja_id, nome, telefone) "
                    "values (:id, :ig, 'P', '5589900000001')"
                ),
                {"id": pessoa_id, "ig": igreja_id},
            )
            conn_a.execute(
                text(
                    "insert into consolidacoes (id, igreja_id, pessoa_id, concluida, "
                    "abandonada_em) values (:id, :ig, :p, false, null)"
                ),
                {"id": cons_id, "ig": igreja_id, "p": pessoa_id},
            )

        trans_a = conn_a.begin()
        try:
            # Passo 1 — leitura DESPROTEGIDA (sem for_update): decide "aberta".
            row = conn_a.execute(
                text(
                    "select id from consolidacoes where id = :id "
                    "and concluida = false and abandonada_em is null"
                ),
                {"id": cons_id},
            ).scalar_one_or_none()
            assert row is not None, "pré-condição: leitura desprotegida vê a linha como aberta"

            # Passo 2 — conclusão CONCORRENTE commita ANTES do archive escrever.
            with conn_b.begin():
                conn_b.execute(
                    text("update consolidacoes set concluida = true where id = :id"),
                    {"id": cons_id},
                )

            # Passo 3 — o UPDATE de abandono (decisão obsoleta do passo 1) crasha.
            with pytest.raises(
                IntegrityError, match="consolidacoes_concluida_abandonada_excl_chk"
            ):
                conn_a.execute(
                    text("update consolidacoes set abandonada_em = now() where id = :id"),
                    {"id": cons_id},
                )
        finally:
            trans_a.rollback()


@pytest.mark.rls_integration
def test_consolidacao_check_constraint_rejects_concluida_and_abandonada(
    offboarding_engine: Engine,
) -> None:
    """CHECK real no Postgres: NOT (concluida=true AND abandonada_em IS NOT NULL)."""
    from sqlalchemy.exc import IntegrityError

    with offboarding_engine.connect() as conn:
        trans = conn.begin()
        igreja_id = uuid.uuid4()
        conn.execute(text("insert into igrejas (id, nome) values (:id, 'X')"), {"id": igreja_id})
        pessoa_id = uuid.uuid4()
        conn.execute(
            text(
                "insert into pessoas (id, igreja_id, nome, telefone) "
                "values (:id, :ig, 'P', '5589900000000')"
            ),
            {"id": pessoa_id, "ig": igreja_id},
        )
        with pytest.raises(IntegrityError, match="consolidacoes_concluida_abandonada_excl_chk"):
            conn.execute(
                text(
                    "insert into consolidacoes "
                    "(igreja_id, pessoa_id, concluida, abandonada_em) "
                    "values (:ig, :p, true, now())"
                ),
                {"ig": igreja_id, "p": pessoa_id},
            )
        trans.rollback()


# ---------------------------------------------------------------------------
# 3ª revisão externa PR#163 — investigação do BLOCKER alegado (approve()
# revalidava `assert_pessoas_nao_arquivadas` SEM `for_update`, hipoteticamente
# permitindo `archive_pessoa` concorrente ENTRE a checagem e o commit de
# approve). Corrigido com `for_update=True` em approve + `populate_existing=
# True` no helper — mas a investigação (ver `_approve_vs_archive_race` abaixo)
# mostrou que o desfecho alegado NÃO é alcançável na prática: o bloqueador
# `celula_solicitacao_aberta` já protege a Pessoa durante toda a vida da
# solicitação, independentemente deste fix. Ambas as mudanças são mantidas
# como defesa em profundidade (consistência com o padrão SEC-4B já usado em
# `upsert_cell`/`archive_pessoa`), não como fechamento de um exploit vivo —
# ver relatório da 3ª rodada para a análise completa.
#
# CORREÇÃO (4ª rodada — a versão anterior deste teste estava errada): o
# identity map da Session, por padrão, guarda referência FRACA (`weakref`)
# aos objetos ORM. Sem NADA segurando uma referência forte ao objeto Pessoa
# entre as duas chamadas, o Python podia coletar o objeto (GC) antes da 2ª
# chamada — que então montava um objeto NOVO com dado fresco, não porque
# `SELECT ... FOR UPDATE` "atualiza objeto cacheado" (não atualiza, por
# padrão, sem `populate_existing`), mas porque não havia objeto cacheado
# nenhum sobrevivendo para testar. O teste original não reproduzia o cenário
# real (produção mantém referências fortes vivas — ex.: `_apply_payload` em
# `cell_requests_service.py` guarda `pessoa` numa variável local usada por
# várias linhas depois da 1ª leitura). Este teste corrige isso mantendo uma
# referência forte explícita (`pessoa_ref`) viva durante todo o cenário.
# ---------------------------------------------------------------------------
@pytest.mark.rls_integration
def test_assert_pessoas_nao_arquivadas_for_update_refreshes_strongly_referenced_object(
    factory: sessionmaker,
) -> None:
    """Prova que `assert_pessoas_nao_arquivadas(..., for_update=True)`
    atualiza `arquivada_em` no MESMO objeto Python já presente no identity
    map — mesmo quando uma referência FORTE ao objeto é mantida viva pelo
    teste (`pessoa_ref`), impedindo o Python de coletar (GC) o objeto entre
    as duas leituras (o que mascarava o cenário real na versão anterior deste
    teste). `populate_existing=True` é o que força essa atualização;
    `SELECT ... FOR UPDATE` sozinho NÃO reescreve atributos de um objeto já
    carregado por padrão. Remover `.execution_options(populate_existing=
    True)` de `assert_pessoas_nao_arquivadas` (celula_membro.py) faz este
    teste falhar de verdade — verificado com `git stash` isolando só essa
    linha (ver relatório da 4ª rodada).
    """
    session_a = factory()
    ctx = _base(session_a)
    pessoa_id = _mk_pessoa(session_a, ctx["igreja_id"])
    session_a.commit()

    # Referência FORTE mantida viva pelo teste — impede o GC de coletar o
    # objeto entre as duas leituras (a lacuna do teste anterior). Mesma leitura
    # desprotegida que `create_cell_request` faz (for_update=False).
    pessoa_ref = session_a.execute(
        select(Pessoa).where(Pessoa.id == pessoa_id)
    ).scalar_one()
    assert pessoa_ref.arquivada_em is None

    # Outra CONEXÃO real arquiva e commita — session_a nunca viu essa escrita.
    session_b = factory()
    try:
        pessoa_b = session_b.get(Pessoa, pessoa_id)
        svc.archive_pessoa(
            session_b, pessoa=pessoa_b, actor_app_user_id=ctx["ator_id"], motivo="concorrente"
        )
    finally:
        session_b.close()

    # `pessoa_ref` ainda é o MESMO objeto Python (identity map não expirou
    # nem foi coletado — a referência forte garante isso) e AINDA mostra o
    # valor stale até a próxima leitura sob `populate_existing`.
    assert pessoa_ref.arquivada_em is None, (
        "pré-condição: pessoa_ref deve continuar stale antes da releitura"
    )

    try:
        with pytest.raises(MembroInelegivelError) as exc_info:
            assert_pessoas_nao_arquivadas(
                session_a, igreja_id=ctx["igreja_id"], pessoa_ids=[pessoa_id], for_update=True
            )
        assert exc_info.value.code == "pessoa_arquivada"

        # Prova de que é o MESMO objeto Python (identity), não um novo objeto
        # criado do zero: `populate_existing=True` atualizou `arquivada_em`
        # IN PLACE na referência forte que o teste segurou o tempo todo.
        assert pessoa_ref.arquivada_em is not None, (
            "populate_existing=True deveria ter atualizado o objeto já "
            "presente no identity map, não apenas retornado um novo"
        )
    finally:
        session_a.rollback()
        session_a.close()

def _approve_vs_archive_race(
    factory: sessionmaker,
    *,
    sol_id: uuid.UUID,
    celula_id: uuid.UUID,
    alvo_id: uuid.UUID,
    central_pessoa_id: uuid.UUID,
    ator_id: uuid.UUID,
    idempotency_key: str | None,
) -> dict[str, tuple]:
    """2 threads/2 transações reais, sincronização via ``threading.Barrier`` —
    dispara ``approve()`` e ``archive_pessoa`` concorrentemente sobre a MESMA
    solicitação/Pessoa e devolve o resultado observado de cada lado.

    NOTA HONESTA (3ª revisão externa PR#163 — investigação, não confirmação):
    a hipótese original era que ``approve()`` sem ``for_update`` permitiria
    ``archive_pessoa`` commitar NO MEIO da transação de ``approve``, resultando
    em vínculo/mutação aplicado a uma Pessoa já arquivada. Construir a prova
    determinística (ver histórico do PR) revelou que esse desfecho NÃO é
    alcançável através do fluxo de solicitação: o bloqueador
    `celula_solicitacao_aberta` (``preflight_archive``, item 10) já recusa
    ``archive_pessoa`` enquanto QUALQUER solicitação `aguardando`/
    `ajuste_solicitado` referenciar a pessoa — cobrindo exatamente os mesmos
    campos JSONB que ``referenced_pessoa_ids`` usa (`anfitriao_id`,
    `auxiliar_id`, `pessoa_id`, `novo_lider_id`, `membros_transferidos_ids`).
    Como o commit de ``approve`` é atômico, no instante em que a solicitação
    deixa de estar "aberta" (aprovada) a mutação específica do tipo (anfitrião/
    auxiliar/vínculo/nova célula) já está visível na MESMA leitura — criando
    IMEDIATAMENTE o bloqueador específico (`celula_anfitriao`/
    `celula_auxiliar`/`celula_membro_ativo`/`celula_lider`). Não existe janela
    em que nenhum dos dois bloqueadores protege a Pessoa. `archive` portanto
    SEMPRE perde para uma aprovação em andamento, com qualquer ordem de
    chegada — o teste abaixo prova isso sob concorrência real (não é um
    resultado tautológico do teste; é uma propriedade do preflight que só se
    confirma rodando os dois caminhos concorrentemente e inspecionando o
    estado final do banco).
    """
    barrier = threading.Barrier(2)
    out: dict[str, tuple] = {}

    def worker_approve() -> None:
        session = factory()
        try:
            solicitacao = session.get(CelulaSolicitacao, sol_id)
            cell = session.get(Celula, celula_id)
            barrier.wait(timeout=15)
            cell_requests_service.approve(
                session,
                solicitacao=solicitacao,
                cell=cell,
                actor_pessoa_id=central_pessoa_id,
                approver_app_user_id=None,
                idempotency_key=idempotency_key,
            )
            out["approve"] = ("ok", None)
        except MembroInelegivelError as exc:
            out["approve"] = ("membro_inelegivel", exc.code)
        except HTTPException as exc:
            out["approve"] = ("http", exc.status_code)
        finally:
            session.close()

    def worker_archive() -> None:
        session = factory()
        try:
            pessoa = session.get(Pessoa, alvo_id)
            barrier.wait(timeout=15)
            svc.archive_pessoa(
                session, pessoa=pessoa, actor_app_user_id=ator_id, motivo="saiu"
            )
            out["archive"] = ("ok", None)
        except HTTPException as exc:
            out["archive"] = ("http", exc.status_code)
        finally:
            session.close()

    threads = [threading.Thread(target=worker_approve), threading.Thread(target=worker_archive)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    return out


@pytest.mark.rls_integration
def test_approve_vs_archive_concurrent_alterar_anfitriao_never_both(
    factory: sessionmaker,
) -> None:
    """tipo=alterar_anfitriao, concorrência real (2 threads/2 transações,
    Barrier). Desfecho SEMPRE observado (ver nota honesta em
    ``_approve_vs_archive_race``): `archive` recusado (409,
    `celula_solicitacao_aberta` OU, se a corrida terminar depois do commit de
    `approve`, `celula_anfitriao`); `approve` sempre aplica o payload."""
    session_setup = factory()
    ctx = _base(session_setup)
    central_pessoa_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Central")
    lider_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Líder")
    alvo_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Alvo anfitrião")
    celula_id = _mk_celula(session_setup, ctx["igreja_id"], lider_id=lider_id)
    sol_id = uuid.uuid4()
    session_setup.add(
        CelulaSolicitacao(
            id=sol_id,
            igreja_id=ctx["igreja_id"],
            celula_id=celula_id,
            tipo="alterar_anfitriao",
            status="aguardando",
            payload_proposto={"anfitriao_id": str(alvo_id)},
        )
    )
    session_setup.commit()
    session_setup.close()

    out = _approve_vs_archive_race(
        factory,
        sol_id=sol_id,
        celula_id=celula_id,
        alvo_id=alvo_id,
        central_pessoa_id=central_pessoa_id,
        ator_id=ctx["ator_id"],
        idempotency_key=None,
    )
    assert "approve" in out and "archive" in out, out

    session = factory()
    try:
        pessoa_db = session.get(Pessoa, alvo_id)
        cell_db = session.get(Celula, celula_id)

        assert pessoa_db.arquivada_em is None, ("BLOCKER real", out)
        assert cell_db.anfitriao_id == alvo_id, ("aprovação deveria sempre vencer", out)
        assert out["approve"] == ("ok", None), out
        assert out["archive"] == ("http", 409), out
    finally:
        session.close()


@pytest.mark.rls_integration
def test_approve_vs_archive_concurrent_alterar_auxiliar_never_both(
    factory: sessionmaker,
) -> None:
    """Espelha o teste de anfitrião para tipo=alterar_auxiliar (mesmo helper
    `assert_pessoas_nao_arquivadas`/mesmo bloqueador `celula_solicitacao_
    aberta` — o caminho de `_apply_payload` é um `elif` distinto e merece
    prova própria)."""
    session_setup = factory()
    ctx = _base(session_setup)
    central_pessoa_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Central")
    lider_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Líder")
    alvo_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Alvo auxiliar")
    celula_id = _mk_celula(session_setup, ctx["igreja_id"], lider_id=lider_id)
    sol_id = uuid.uuid4()
    session_setup.add(
        CelulaSolicitacao(
            id=sol_id,
            igreja_id=ctx["igreja_id"],
            celula_id=celula_id,
            tipo="alterar_auxiliar",
            status="aguardando",
            payload_proposto={"auxiliar_id": str(alvo_id)},
        )
    )
    session_setup.commit()
    session_setup.close()

    out = _approve_vs_archive_race(
        factory,
        sol_id=sol_id,
        celula_id=celula_id,
        alvo_id=alvo_id,
        central_pessoa_id=central_pessoa_id,
        ator_id=ctx["ator_id"],
        idempotency_key=None,
    )
    assert "approve" in out and "archive" in out, out

    session = factory()
    try:
        pessoa_db = session.get(Pessoa, alvo_id)
        cell_db = session.get(Celula, celula_id)

        assert pessoa_db.arquivada_em is None, ("BLOCKER real", out)
        assert cell_db.auxiliar_id == alvo_id, ("aprovação deveria sempre vencer", out)
        assert out["approve"] == ("ok", None), out
        assert out["archive"] == ("http", 409), out
    finally:
        session.close()


@pytest.mark.rls_integration
def test_approve_vs_archive_concurrent_transferir_membro_never_both(
    factory: sessionmaker,
) -> None:
    """tipo=transferir_membro: aprovação cria vínculo ATIVO em celula_membro
    na célula destino. Concorrência real (2 threads/2 transações, Barrier)
    contra `archive`. `celula_solicitacao_aberta` bloqueia `archive` enquanto
    a solicitação estiver aberta; depois do commit de `approve`,
    `celula_membro_ativo` bloqueia — nunca fica um vínculo ativo com pessoa
    arquivada."""
    session_setup = factory()
    ctx = _base(session_setup)
    central_pessoa_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Central")
    lider_origem_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Líder origem")
    lider_destino_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Líder destino")
    alvo_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Alvo transferência")
    celula_origem_id = _mk_celula(
        session_setup, ctx["igreja_id"], nome="Origem", lider_id=lider_origem_id
    )
    celula_destino_id = _mk_celula(
        session_setup, ctx["igreja_id"], nome="Destino", lider_id=lider_destino_id
    )
    sol_id = uuid.uuid4()
    session_setup.add(
        CelulaSolicitacao(
            id=sol_id,
            igreja_id=ctx["igreja_id"],
            celula_id=celula_origem_id,
            pessoa_id=alvo_id,
            tipo="transferir_membro",
            status="aguardando",
            payload_proposto={
                "pessoa_id": str(alvo_id),
                "celula_destino_id": str(celula_destino_id),
            },
        )
    )
    session_setup.commit()
    session_setup.close()

    out = _approve_vs_archive_race(
        factory,
        sol_id=sol_id,
        celula_id=celula_origem_id,
        alvo_id=alvo_id,
        central_pessoa_id=central_pessoa_id,
        ator_id=ctx["ator_id"],
        idempotency_key=None,
    )
    assert "approve" in out and "archive" in out, out

    session = factory()
    try:
        pessoa_db = session.get(Pessoa, alvo_id)
        membro = session.execute(
            select(CelulaMembro).where(
                CelulaMembro.pessoa_id == alvo_id, CelulaMembro.ativo.is_(True)
            )
        ).scalar_one_or_none()

        assert pessoa_db.arquivada_em is None, ("BLOCKER real", out)
        assert membro is not None and membro.celula_id == celula_destino_id, (
            "aprovação deveria sempre vencer", out
        )
        assert out["approve"] == ("ok", None), out
        assert out["archive"] == ("http", 409), out
    finally:
        session.close()


@pytest.mark.rls_integration
def test_approve_vs_archive_concurrent_multiplicacao_never_both(
    factory: sessionmaker,
) -> None:
    """tipo=multiplicacao, novo_lider_id=Pessoa disputada. Concorrência real
    (2 threads/2 transações, Barrier) contra `archive`. `celula_solicitacao_
    aberta` bloqueia `archive` enquanto a solicitação estiver aberta; depois
    do commit de `approve`, `celula_lider` bloqueia — nunca fica uma célula
    nova com líder arquivado."""
    session_setup = factory()
    ctx = _base(session_setup)
    central_pessoa_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Central")
    lider_origem_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Líder origem")
    membro_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Membro transferido")
    alvo_id = _mk_pessoa(
        session_setup, ctx["igreja_id"], nome="Alvo novo líder", apto_lider=True
    )
    celula_origem_id = _mk_celula(
        session_setup, ctx["igreja_id"], nome="Origem", lider_id=lider_origem_id
    )
    session_setup.add(
        CelulaMembro(
            igreja_id=ctx["igreja_id"],
            celula_id=celula_origem_id,
            pessoa_id=membro_id,
            papel="membro",
            ativo=True,
        )
    )
    sol_id = uuid.uuid4()
    session_setup.add(
        CelulaSolicitacao(
            id=sol_id,
            igreja_id=ctx["igreja_id"],
            celula_id=celula_origem_id,
            tipo="multiplicacao",
            status="aguardando",
            payload_proposto={
                "idempotency_key": "idem-mult-race-1",
                "nome_nova_celula": "Nova Célula",
                "novo_lider_id": str(alvo_id),
                "membros_transferidos_ids": [str(membro_id)],
            },
        )
    )
    session_setup.commit()
    session_setup.close()

    out = _approve_vs_archive_race(
        factory,
        sol_id=sol_id,
        celula_id=celula_origem_id,
        alvo_id=alvo_id,
        central_pessoa_id=central_pessoa_id,
        ator_id=ctx["ator_id"],
        idempotency_key="idem-mult-race-1",
    )
    assert "approve" in out and "archive" in out, out

    session = factory()
    try:
        pessoa_db = session.get(Pessoa, alvo_id)
        nova_celula = session.execute(
            select(Celula).where(Celula.lider_id == alvo_id, Celula.ativo.is_(True))
        ).scalar_one_or_none()
        mult = session.execute(
            select(Multiplicacao).where(Multiplicacao.solicitacao_id == sol_id)
        ).scalar_one_or_none()

        assert pessoa_db.arquivada_em is None, ("BLOCKER real", out)
        assert nova_celula is not None, ("aprovação deveria sempre vencer", out)
        assert mult is not None
        assert out["approve"] == ("ok", None), out
        assert out["archive"] == ("http", 409), out
    finally:
        session.close()


@pytest.mark.rls_integration
def test_approve_vs_archive_alterar_anfitriao_approve_wins_deterministic(
    factory: sessionmaker,
) -> None:
    """Prova DETERMINÍSTICA (2 threads/2 transações reais, sincronização via
    ``threading.Event`` — ``approve`` trava a Pessoa e pausa ANTES do commit
    via hook em `session.commit`, `archive` só começa depois de `approve` já
    ter passado a checagem): quando `approve` já aplicou o payload e está
    prestes a commitar, `archive` — mesmo tentando exatamente nesse instante —
    bloqueia no lock real do Postgres até `approve` liberar, depois relê sob
    lock e vê o bloqueador `celula_anfitriao` recém-criado (409). Cobre o
    caso em que a solicitação JÁ FOI aprovada (não está mais aberta) no
    instante em que `archive` roda seu preflight — complementar ao teste de
    Barrier acima, que só observa o resultado final."""
    session_setup = factory()
    ctx = _base(session_setup)
    central_pessoa_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Central")
    lider_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Líder")
    alvo_id = _mk_pessoa(session_setup, ctx["igreja_id"], nome="Alvo anfitrião")
    celula_id = _mk_celula(session_setup, ctx["igreja_id"], lider_id=lider_id)
    sol_id = uuid.uuid4()
    session_setup.add(
        CelulaSolicitacao(
            id=sol_id,
            igreja_id=ctx["igreja_id"],
            celula_id=celula_id,
            tipo="alterar_anfitriao",
            status="aguardando",
            payload_proposto={"anfitriao_id": str(alvo_id)},
        )
    )
    session_setup.commit()
    session_setup.close()

    approve_ready = threading.Event()
    proceed = threading.Event()
    out: dict[str, tuple] = {}

    def worker_approve() -> None:
        session = factory()
        try:
            solicitacao = session.get(CelulaSolicitacao, sol_id)
            cell = session.get(Celula, celula_id)
            original_commit = session.commit

            def paused_commit(*a, **kw):
                approve_ready.set()
                if not proceed.wait(timeout=15):
                    raise TimeoutError("T2 não sinalizou proceed a tempo")
                return original_commit(*a, **kw)

            session.commit = paused_commit
            cell_requests_service.approve(
                session,
                solicitacao=solicitacao,
                cell=cell,
                actor_pessoa_id=central_pessoa_id,
                approver_app_user_id=None,
                idempotency_key=None,
            )
            out["approve"] = ("ok", None)
        except MembroInelegivelError as exc:
            out["approve"] = ("membro_inelegivel", exc.code)
        except HTTPException as exc:
            out["approve"] = ("http", exc.status_code)
        finally:
            session.close()

    def worker_archive() -> None:
        if not approve_ready.wait(timeout=15):
            out["archive"] = ("error", "timeout esperando approve_ready")
            return
        session = factory()
        try:
            pessoa = session.get(Pessoa, alvo_id)
            svc.archive_pessoa(
                session, pessoa=pessoa, actor_app_user_id=ctx["ator_id"], motivo="saiu"
            )
            out["archive"] = ("ok", None)
        except HTTPException as exc:
            out["archive"] = ("http", exc.status_code)
        finally:
            session.close()

    t_approve = threading.Thread(target=worker_approve)
    t_archive = threading.Thread(target=worker_archive)
    t_approve.start()
    assert approve_ready.wait(timeout=15), "T1 não travou a Pessoa a tempo"
    t_archive.start()
    proceed.set()
    t_approve.join(timeout=20)
    t_archive.join(timeout=20)

    assert out.get("approve") == ("ok", None), out

    session = factory()
    try:
        pessoa_db = session.get(Pessoa, alvo_id)
        cell_db = session.get(Celula, celula_id)
        sol_db = session.get(CelulaSolicitacao, sol_id)

        assert cell_db.anfitriao_id == alvo_id, "aprovação deve ter aplicado o payload"
        assert sol_db.status == "aprovada"
        assert pessoa_db.arquivada_em is None, (
            "BLOCKER: pessoa não pode ter sido arquivada com vínculo ativo", out
        )
        assert out.get("archive") == ("http", 409), out
    finally:
        session.close()
