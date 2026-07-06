-- ============================================================================
-- PastorAI — Migration 20260705_120000 — Células PR3-PR9 (a): campos de
-- relatório em `celula_reuniao`.
-- Fontes: docs/sprints.json (feat-001.a / feat-007 ciclo do relatório) +
--         docs/design/CELULAS-DECISOES-FINAIS.md (3.5).
--
-- 100% ADITIVO sobre o PR2: apenas ALTER (add column if not exists) em
-- `celula_reuniao`, sem tocar em nenhuma outra tabela e sem recriar nada
-- (RNF-17). Adiciona o ciclo de relatório da reunião:
--
--   relatorio_status      text  NOT NULL DEFAULT 'pendente'  CHECK in (pendente, enviado)
--   relatorio_enviado_em  timestamptz
--   relatorio_enviado_por uuid  FK pessoas ON DELETE SET NULL (autor)
--   oferta_valor          numeric(12,2)
--   observacoes           text
--
-- `updated_at` continua gerenciado pela aplicação (sem trigger). A policy RLS
-- vigente de `celula_reuniao` (20260704_100000) já cobre as colunas novas.
--
-- ALTER transacional + idempotente (add column if not exists / DO block p/ o
-- CHECK). Não aplicada automaticamente: rodar manualmente no Supabase (DEV
-- primeiro), em ordem de nome de arquivo.
-- ============================================================================

begin;

-- relatorio_status: ciclo do relatório. Coluna nasce com DEFAULT 'pendente',
-- que preenche eventuais linhas legadas => NOT NULL é seguro.
alter table celula_reuniao
  add column if not exists relatorio_status text not null default 'pendente';

do $$ begin
  alter table celula_reuniao add constraint celula_reuniao_relatorio_status_chk
    check (relatorio_status in ('pendente', 'enviado'));
exception when duplicate_object then null; end $$;

-- quem/quando enviou o relatório (preenchidos no submit).
alter table celula_reuniao
  add column if not exists relatorio_enviado_em timestamptz;
-- FK de autor: ON DELETE SET NULL (não apaga a reunião se a pessoa sair).
alter table celula_reuniao
  add column if not exists relatorio_enviado_por uuid
  references pessoas(id) on delete set null;

-- oferta arrecadada na reunião (validação de faixa [0, 999999.99] fica na app).
alter table celula_reuniao
  add column if not exists oferta_valor numeric(12, 2);

-- observações livres do relatório.
alter table celula_reuniao
  add column if not exists observacoes text;

-- snapshot imutável do relatório consolidado, gravado no submit (E10/E11):
-- congela presenças/visitantes/registros/oferta/observações para que a leitura
-- pós-envio não reflita alterações posteriores em celula_presenca (o endpoint
-- PR2 de presença é upsert sempre-200 e não trava após o envio).
alter table celula_reuniao
  add column if not exists relatorio_snapshot jsonb;

-- Índice para a fila de relatórios da Central (US-16/RF-20) e a saúde
-- (US-18/RF-22): consultam relatorio_status + data direto na reunião.
create index if not exists idx_celula_reuniao_relatorio_status
  on celula_reuniao (igreja_id, relatorio_status, data);

commit;
