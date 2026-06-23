-- ============================================================================
-- PastorAI — Migration 20260623_103319_pessoa_sem_interesse_csim
-- Onda 1 (#1): classificação de contato. Adiciona o flag CSIM (contato sem
-- interesse ministerial — empresa, gente de outra cidade, sem vínculo possível)
-- + o motivo. CSIM fica FORA do funil pastoral (ganhar→consolidar→...).
-- Estende US-10 (contato vs visitante). "contato" vs "visitante" reusa o enum
-- pessoa_subetapa já existente (novo_contato / visitante) — sem coluna nova.
--
-- ADD COLUMN é transacional (≠ ALTER TYPE ADD VALUE): pode usar begin/commit.
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ============================================================================

begin;

alter table pessoas
  add column if not exists sem_interesse boolean not null default false,
  add column if not exists sem_interesse_motivo text;

comment on column pessoas.sem_interesse is
  'CSIM (#1): contato sem interesse ministerial — excluído do funil pastoral.';
comment on column pessoas.sem_interesse_motivo is
  'CSIM: motivo curto da classificação (ex.: empresa, outra cidade).';

commit;
