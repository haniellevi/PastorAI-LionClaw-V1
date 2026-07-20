-- ============================================================================
-- PastorAI — Migration 20260720_191143_consent_records_ator_id_reoptin
-- FECH-05/OPTIN-1 (decisão 1 de docs/decisions/2026-07-18-decisoes-fechamento-mvp.md):
-- a reativação administrativa de comunicações ("re-opt-in") deve registrar QUEM
-- reativou de forma durável. Adiciona `consent_records.ator_id` — o app_user
-- autenticado que executou a ação administrativa.
--
-- NULL = consentimento registrado por fluxo automático (consent inbound do
-- agente, optout via WhatsApp) e todo o legado. Nenhum backfill: a ausência de
-- ator é a informação correta para esses registros.
--
-- Espelha `pessoa_arquivamento_evento.ator_id` (migration 20260713_032015):
-- ON DELETE SET NULL — apagar o app_user não pode apagar nem travar a trilha
-- de consentimento. Sem índice novo e sem mudança de RLS (a tabela já é
-- coberta pela policy de tenant existente).
--
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ============================================================================

begin;

alter table consent_records
  add column if not exists ator_id uuid null
    references app_users(id) on delete set null;

comment on column consent_records.ator_id is
  'App_user que registrou o consentimento quando a origem é ação administrativa '
  '(ex.: reoptin). NULL = fluxo automático (consent inbound, optout) e legado.';

commit;
