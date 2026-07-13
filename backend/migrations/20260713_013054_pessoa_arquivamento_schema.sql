-- ============================================================================
-- PastorAI — Migration 20260713_013054_pessoa_arquivamento_schema
-- W3: schema auditável de arquivamento de Pessoa. Sem hard delete — NULL em
-- arquivada_em significa pessoa ativa. Reativação e efeitos de desligamento
-- ficam para missão posterior; esta migration é só schema (colunas + FK).
--
-- ADD COLUMN é transacional (≠ ALTER TYPE ADD VALUE): pode usar begin/commit.
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ============================================================================

begin;

alter table pessoas
  add column if not exists arquivada_em timestamptz,
  add column if not exists arquivada_por uuid references app_users(id) on delete set null,
  add column if not exists arquivada_motivo text;

comment on column pessoas.arquivada_em is
  'W3: momento do arquivamento. NULL = pessoa ativa. Sem hard delete de Pessoa.';
comment on column pessoas.arquivada_por is
  'W3: app_user que arquivou a pessoa. ON DELETE SET NULL: se o app_user for removido, esta coluna vira NULL — a pessoa e o registro de arquivada_em/motivo NAO são apagados, só se perde a referência a quem executou a ação.';
comment on column pessoas.arquivada_motivo is
  'W3: motivo textual do arquivamento (auditoria).';

commit;
