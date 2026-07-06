"""Células PR3-PR9 — fundação de banco: modelos + migrations aditivas.

O harness é in-memory (sem Postgres real), então UNIQUE/CHECK/RLS/trigger não
são exercitados em runtime. Estes testes cobrem o verificável em Python puro +
inspeção do SQL das 7 migrations:

  - os 6 modelos novos (CelulaReuniaoRegistro, CelulaVisitante,
    CelulaSolicitacao, CelulaSolicitacaoEvento, CelulaAviso, CelulaMaterial)
    têm as colunas da SPEC com nullability/defaults e FKs corretas;
  - CelulaReuniao (PR2) recebeu as 5 colunas de relatório preservando as antigas;
  - Multiplicacao (stub) recebeu as colunas aditivas SEM renomear celula_id;
  - FKs de autor/pessoa são ON DELETE SET NULL; estruturais são CASCADE;
  - cada migration existe, é transacional, idempotente e declara RLS/policy;
  - a trilha de auditoria tem o trigger append-only BEFORE UPDATE OR DELETE;
  - a migration de multiplicacoes só adiciona colunas (não renomeia celula_id).

A validação de que as constraints/RLS/trigger realmente aplicam é MANUAL no
Supabase DEV (gate humano) — SQLite não prova RLS.
"""

from __future__ import annotations

import pathlib

from app.db.models import (
    CelulaAviso,
    CelulaMaterial,
    CelulaReuniao,
    CelulaReuniaoRegistro,
    CelulaSolicitacao,
    CelulaSolicitacaoEvento,
    CelulaVisitante,
    Multiplicacao,
)

_MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "migrations"

_MIG_REUNIAO_CAMPOS = _MIG_DIR / "20260705_120000_celula_pr3_reuniao_relatorio_campos.sql"
_MIG_REGISTRO = _MIG_DIR / "20260705_120100_celula_pr3_reuniao_registro.sql"
_MIG_VISITANTE = _MIG_DIR / "20260705_120200_celula_pr3_visitante.sql"
_MIG_SOLICITACAO = _MIG_DIR / "20260705_120300_celula_pr3_solicitacao_evento.sql"
_MIG_AVISO = _MIG_DIR / "20260705_120400_celula_pr3_aviso.sql"
_MIG_MATERIAL = _MIG_DIR / "20260705_120500_celula_pr3_material.sql"
_MIG_MULTIPLICACOES = _MIG_DIR / "20260705_120600_celula_pr3_multiplicacoes_evolucao.sql"

_ALL_MIGRATIONS = [
    _MIG_REUNIAO_CAMPOS,
    _MIG_REGISTRO,
    _MIG_VISITANTE,
    _MIG_SOLICITACAO,
    _MIG_AVISO,
    _MIG_MATERIAL,
    _MIG_MULTIPLICACOES,
]


def _sql(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8").lower()


# ---- helpers de FK ---------------------------------------------------------
def _fk_target(model, col: str) -> str:
    fks = list(model.__table__.c[col].foreign_keys)
    assert len(fks) == 1, f"{col} deveria ter exatamente 1 FK"
    return fks[0].column.table.name


def _fk_ondelete(model, col: str) -> str:
    fks = list(model.__table__.c[col].foreign_keys)
    return (fks[0].ondelete or "").upper()


# ============================================================================
# feat-001 / feat-002 — arquivos e estrutura
# ============================================================================
def test_seven_migration_files_exist() -> None:
    for path in _ALL_MIGRATIONS:
        assert path.exists(), f"migration faltando: {path.name}"
    assert len(_ALL_MIGRATIONS) == 7


def test_all_migrations_transactional() -> None:
    for path in _ALL_MIGRATIONS:
        sql = _sql(path)
        assert sql.strip().startswith("--") or "begin;" in sql
        assert "begin;" in sql, f"{path.name} não é transacional"
        assert "commit;" in sql, f"{path.name} não fecha a transação"


# ============================================================================
# (a) celula_reuniao: 5 colunas de relatório preservando as do PR2
# ============================================================================
def test_celula_reuniao_relatorio_columns() -> None:
    cols = CelulaReuniao.__table__.columns
    # colunas antigas (PR2) preservadas
    for name in ("id", "igreja_id", "celula_id", "data", "hora", "tema", "status"):
        assert name in cols, f"coluna PR2 {name} sumiu de celula_reuniao"
    # colunas novas (PR3)
    for name in (
        "relatorio_status",
        "relatorio_enviado_em",
        "relatorio_enviado_por",
        "oferta_valor",
        "observacoes",
    ):
        assert name in cols, f"coluna nova {name} faltando em celula_reuniao"
    assert cols["relatorio_status"].nullable is False
    assert "pendente" in str(cols["relatorio_status"].server_default.arg)
    assert cols["relatorio_enviado_em"].nullable is True
    assert cols["relatorio_enviado_por"].nullable is True
    assert cols["oferta_valor"].nullable is True
    assert cols["observacoes"].nullable is True
    # FK de autor -> pessoas, SET NULL
    assert _fk_target(CelulaReuniao, "relatorio_enviado_por") == "pessoas"
    assert _fk_ondelete(CelulaReuniao, "relatorio_enviado_por") == "SET NULL"


def test_migration_reuniao_campos_additive_and_check() -> None:
    sql = _sql(_MIG_REUNIAO_CAMPOS)
    assert "alter table celula_reuniao" in sql
    assert "add column if not exists relatorio_status text not null default 'pendente'" in sql
    assert "celula_reuniao_relatorio_status_chk" in sql
    for value in ("'pendente'", "'enviado'"):
        assert value in sql
    assert "numeric(12, 2)" in sql or "numeric(12,2)" in sql
    assert "references pessoas(id) on delete set null" in sql
    # índice da fila de relatórios (SPEC 2.1.1)
    assert "idx_celula_reuniao_relatorio_status" in sql
    assert "(igreja_id, relatorio_status, data)" in sql
    # aditivo: nada de drop/rename
    assert "drop table" not in sql
    assert "rename" not in sql


# ============================================================================
# (b) celula_reuniao_registro
# ============================================================================
def test_celula_reuniao_registro_model() -> None:
    cols = CelulaReuniaoRegistro.__table__.columns
    for name in ("id", "igreja_id", "reuniao_id", "tipo", "conteudo", "pessoa_id",
                 "autor_id", "created_at", "updated_at"):
        assert name in cols
    assert cols["igreja_id"].nullable is False
    assert cols["reuniao_id"].nullable is False
    assert cols["tipo"].nullable is False
    assert cols["conteudo"].nullable is False
    assert cols["pessoa_id"].nullable is True
    assert cols["autor_id"].nullable is True
    assert _fk_target(CelulaReuniaoRegistro, "igreja_id") == "igrejas"
    assert _fk_target(CelulaReuniaoRegistro, "reuniao_id") == "celula_reuniao"
    assert _fk_target(CelulaReuniaoRegistro, "pessoa_id") == "pessoas"
    assert _fk_ondelete(CelulaReuniaoRegistro, "igreja_id") == "CASCADE"
    assert _fk_ondelete(CelulaReuniaoRegistro, "reuniao_id") == "CASCADE"
    assert _fk_ondelete(CelulaReuniaoRegistro, "pessoa_id") == "SET NULL"
    assert _fk_ondelete(CelulaReuniaoRegistro, "autor_id") == "SET NULL"


def test_migration_registro() -> None:
    sql = _sql(_MIG_REGISTRO)
    assert "create table if not exists celula_reuniao_registro" in sql
    assert "references celula_reuniao(id) on delete cascade" in sql
    assert "references pessoas(id) on delete set null" in sql
    assert "celula_reuniao_registro_tipo_chk" in sql
    for value in ("'decisao'", "'oracao'", "'observacao'"):
        assert value in sql
    assert "idx_celula_reuniao_registro_igreja" in sql
    assert "idx_celula_reuniao_registro_reuniao" in sql
    # índice da SPEC 2.1.2 inclui tipo
    assert "(igreja_id, reuniao_id, tipo)" in sql


# ============================================================================
# (c) celula_visitante
# ============================================================================
def test_celula_visitante_model() -> None:
    cols = CelulaVisitante.__table__.columns
    for name in ("id", "igreja_id", "reuniao_id", "expectativa_id",
                 "nome_visitante", "telefone", "observacao", "created_at",
                 "updated_at"):
        assert name in cols
    assert cols["nome_visitante"].nullable is False
    assert cols["expectativa_id"].nullable is True
    assert cols["telefone"].nullable is True
    assert _fk_target(CelulaVisitante, "reuniao_id") == "celula_reuniao"
    assert _fk_target(CelulaVisitante, "expectativa_id") == "celula_expectativa_visitante"
    assert _fk_ondelete(CelulaVisitante, "reuniao_id") == "CASCADE"
    # link opcional: apagar a expectativa NÃO apaga o comparecimento real
    assert _fk_ondelete(CelulaVisitante, "expectativa_id") == "SET NULL"


def test_migration_visitante() -> None:
    sql = _sql(_MIG_VISITANTE)
    assert "create table if not exists celula_visitante" in sql
    assert "references celula_expectativa_visitante(id) on delete set null" in sql
    # sem UNIQUE na tabela de visitante
    for line in sql.splitlines():
        if "unique index" in line and "celula_visitante" in line:
            raise AssertionError("celula_visitante não deve ter UNIQUE")
    assert "idx_celula_visitante_igreja" in sql
    assert "idx_celula_visitante_reuniao" in sql


# ============================================================================
# (d) celula_solicitacao + celula_solicitacao_evento + trigger append-only
# ============================================================================
def test_celula_solicitacao_model() -> None:
    cols = CelulaSolicitacao.__table__.columns
    for name in ("id", "igreja_id", "celula_id", "solicitante_id", "pessoa_id",
                 "tipo", "status", "payload_proposto", "payload_atual", "motivo",
                 "observacao_central", "decidido_por", "decidido_em",
                 "created_at", "updated_at"):
        assert name in cols
    assert cols["tipo"].nullable is False
    assert cols["status"].nullable is False
    assert "aguardando" in str(cols["status"].server_default.arg)
    assert cols["payload_proposto"].nullable is False
    assert cols["payload_atual"].nullable is True
    assert _fk_target(CelulaSolicitacao, "celula_id") == "celulas"
    assert _fk_ondelete(CelulaSolicitacao, "celula_id") == "CASCADE"
    for col in ("solicitante_id", "pessoa_id", "decidido_por"):
        assert _fk_ondelete(CelulaSolicitacao, col) == "SET NULL"


def test_celula_solicitacao_evento_model_append_only() -> None:
    cols = CelulaSolicitacaoEvento.__table__.columns
    for name in ("id", "igreja_id", "solicitacao_id", "acao", "autor_id",
                 "payload_snapshot", "de_status", "para_status", "observacao",
                 "created_at"):
        assert name in cols
    assert cols["acao"].nullable is False
    assert cols["payload_snapshot"].nullable is False
    # append-only: NÃO tem updated_at
    assert "updated_at" not in cols
    assert _fk_target(CelulaSolicitacaoEvento, "solicitacao_id") == "celula_solicitacao"
    assert _fk_ondelete(CelulaSolicitacaoEvento, "solicitacao_id") == "CASCADE"
    assert _fk_ondelete(CelulaSolicitacaoEvento, "autor_id") == "SET NULL"


def test_migration_solicitacao_types_and_status() -> None:
    sql = _sql(_MIG_SOLICITACAO)
    assert "create table if not exists celula_solicitacao" in sql
    assert "create table if not exists celula_solicitacao_evento" in sql
    assert "jsonb" in sql
    # 8 tipos de solicitação
    for value in (
        "'alterar_dia'", "'alterar_horario'", "'alterar_endereco'",
        "'alterar_anfitriao'", "'alterar_auxiliar'", "'transferir_membro'",
        "'remover_membro'", "'multiplicacao'",
    ):
        assert value in sql, f"tipo {value} faltando"
    # status
    for value in ("'aguardando'", "'aprovada'", "'rejeitada'",
                  "'ajuste_solicitado'", "'cancelada'"):
        assert value in sql, f"status {value} faltando"
    # tipos de evento (coluna canônica = acao) + snapshot obrigatório
    assert "celula_solicitacao_evento_acao_chk" in sql
    assert "check (acao in (" in sql
    assert "payload_snapshot jsonb not null" in sql
    for value in ("'criada'", "'reenviada'"):
        assert value in sql
    # decisão da Central: colunas canônicas decidido_por/decidido_em
    assert "decidido_por" in sql
    assert "decidido_em" in sql


def test_migration_append_only_trigger() -> None:
    sql = _sql(_MIG_SOLICITACAO)
    assert "trg_celula_solicitacao_evento_append_only" in sql
    assert "before update or delete on celula_solicitacao_evento" in sql
    assert "raise exception 'append-only'" in sql


# ============================================================================
# (e) celula_aviso
# ============================================================================
def test_celula_aviso_model() -> None:
    cols = CelulaAviso.__table__.columns
    for name in ("id", "igreja_id", "celula_id", "autor_id", "origem", "escopo",
                 "titulo", "conteudo", "ativo", "publicado_em", "notificado_em",
                 "created_at", "updated_at"):
        assert name in cols
    # celula_id NULL quando escopo=igreja
    assert cols["celula_id"].nullable is True
    assert cols["origem"].nullable is False
    assert cols["escopo"].nullable is False
    assert cols["ativo"].nullable is False
    assert _fk_ondelete(CelulaAviso, "celula_id") == "CASCADE"
    assert _fk_ondelete(CelulaAviso, "autor_id") == "SET NULL"


def test_migration_aviso() -> None:
    sql = _sql(_MIG_AVISO)
    assert "create table if not exists celula_aviso" in sql
    assert "celula_aviso_origem_chk" in sql
    assert "celula_aviso_escopo_chk" in sql
    for value in ("'celula'", "'central'", "'igreja'"):
        assert value in sql
    # SPEC 2.1.6: índice de feed nomeado com (igreja_id, ativo, publicado_em desc)
    assert "idx_celula_aviso_feed" in sql
    assert "on celula_aviso (igreja_id, ativo, publicado_em desc)" in sql
    assert "idx_celula_aviso_celula" in sql


# ============================================================================
# (f) celula_material
# ============================================================================
def test_celula_material_model() -> None:
    cols = CelulaMaterial.__table__.columns
    for name in ("id", "igreja_id", "autor_id", "titulo", "descricao", "url",
                 "tipo", "ativo", "publicado_em", "created_at", "updated_at"):
        assert name in cols
    assert cols["titulo"].nullable is False
    # SPEC 2.1.7: url e tipo são NULLABLE (sem upload real no MVP)
    assert cols["url"].nullable is True
    assert cols["tipo"].nullable is True
    assert cols["descricao"].nullable is True
    assert _fk_ondelete(CelulaMaterial, "autor_id") == "SET NULL"


def test_migration_material() -> None:
    sql = _sql(_MIG_MATERIAL)
    assert "create table if not exists celula_material" in sql
    # SPEC 2.1.7: índice de feed nomeado com (igreja_id, ativo, publicado_em desc)
    assert "idx_celula_material_feed" in sql
    assert "on celula_material (igreja_id, ativo, publicado_em desc)" in sql


# ============================================================================
# (g) multiplicacoes: evolução aditiva SEM renomear celula_id
# ============================================================================
def test_multiplicacoes_model_additive() -> None:
    cols = Multiplicacao.__table__.columns
    # celula_id preservado (origem)
    assert "celula_id" in cols
    assert _fk_target(Multiplicacao, "celula_id") == "celulas"
    # colunas novas
    for name in ("solicitacao_id", "idempotency_key", "celula_nova_id",
                 "created_at", "updated_at"):
        assert name in cols, f"coluna nova {name} faltando em multiplicacoes"
    assert cols["solicitacao_id"].nullable is False
    assert _fk_target(Multiplicacao, "solicitacao_id") == "celula_solicitacao"
    assert _fk_ondelete(Multiplicacao, "solicitacao_id") == "CASCADE"
    assert _fk_target(Multiplicacao, "celula_nova_id") == "celulas"
    assert _fk_ondelete(Multiplicacao, "celula_nova_id") == "SET NULL"


def test_migration_multiplicacoes_no_rename_and_partial_unique() -> None:
    sql = _sql(_MIG_MULTIPLICACOES)
    assert "alter table multiplicacoes" in sql
    # NÃO renomeia celula_id nem recria a tabela
    assert "rename" not in sql
    assert "create table" not in sql
    assert "drop table" not in sql
    # solicitacao_id UNIQUE FK CASCADE + não-nulo via CHECK NOT VALID (não aborta
    # numa tabela com linhas legadas do stub; enforce em toda linha nova).
    assert "add column if not exists solicitacao_id uuid" in sql
    assert "references celula_solicitacao(id) on delete cascade" in sql
    assert "multiplicacoes_solicitacao_uq" in sql
    assert "check (solicitacao_id is not null) not valid" in sql
    assert "set not null" not in sql  # não usa SET NOT NULL (aborta com legado)
    # idempotency_key: índice único PARCIAL POR-TENANT where not null
    # SPEC 2.1.8/2.2.3: unique (igreja_id, idempotency_key) where not null
    assert "multiplicacoes_idempotency_key_uq" in sql
    assert "on multiplicacoes (igreja_id, idempotency_key) where idempotency_key is not null" in sql
    # celula_nova_id FK SET NULL
    assert "references celulas(id) on delete set null" in sql
    # NÃO adiciona igreja_id (já existe no stub)
    assert "add column if not exists igreja_id" not in sql
    # RLS re-afirmada
    assert "enable row level security" in sql
    assert "create policy tenant_isolation on multiplicacoes" in sql


# ============================================================================
# feat-003 — RLS/policy tenant_isolation em todas as tabelas novas
# ============================================================================
def test_rls_tenant_isolation_on_all_new_tables() -> None:
    checks = {
        _MIG_REGISTRO: "celula_reuniao_registro",
        _MIG_VISITANTE: "celula_visitante",
        _MIG_AVISO: "celula_aviso",
        _MIG_MATERIAL: "celula_material",
    }
    for path, tbl in checks.items():
        sql = _sql(path)
        assert f"alter table {tbl} enable row level security" in sql
        assert f"create policy tenant_isolation on {tbl}" in sql
        assert "using (igreja_id = current_igreja_id())" in sql
        assert "with check (igreja_id = current_igreja_id())" in sql
    # a migration (d) tem 2 tabelas -> 2 policies
    sql_d = _sql(_MIG_SOLICITACAO)
    assert sql_d.count("create policy tenant_isolation") == 2
    for tbl in ("celula_solicitacao", "celula_solicitacao_evento"):
        assert f"alter table {tbl} enable row level security" in sql_d


def test_no_updated_at_trigger_anywhere() -> None:
    # Nenhum trigger de updated_at em nenhuma migration do módulo.
    for path in _ALL_MIGRATIONS:
        sql = _sql(path)
        assert "set_updated_at" not in sql
        assert "updated_at()" not in sql
