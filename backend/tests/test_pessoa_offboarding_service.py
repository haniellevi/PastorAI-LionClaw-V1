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
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import app.db.session  # noqa: F401 - registra o listener after_begin (paridade prod)
from app.db.models import (
    AppUser,
    Base,
    Celula,
    CelulaMembro,
    CelulaSolicitacao,
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
from app.services import pessoa_offboarding_service as svc
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
        # Stub de current_igreja_id(): só precisa EXISTIR para a policy da
        # migration parsear. A conexão roda como owner do banco descartável
        # (bypassa RLS por padrão), então isolamento de tenant real não é o
        # que esta suíte prova — isso já é coberto por tests/test_rls_*.py.
        conn.exec_driver_sql(
            "create or replace function current_igreja_id() returns uuid "
            "language sql stable as $$ select nullif(current_setting("
            "'app.tenant_igreja_id', true), '')::uuid $$;"
        )

    tables_sem_evento = [
        t for t in Base.metadata.sorted_tables if t.name != "pessoa_arquivamento_evento"
    ]
    Base.metadata.create_all(engine, tables=tables_sem_evento)

    with engine.begin() as conn:
        conn.exec_driver_sql(_MIGRATION.read_text(encoding="utf-8"))

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
