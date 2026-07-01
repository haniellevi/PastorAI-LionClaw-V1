-- ============================================================================
-- PastorAI — Migration 20260701_164352 — EVT-7 PR1: aviso de confirmação
-- RF-35/RF-39 · SPEC "Módulo Agenda de Eventos" · auditoria EVT-7 (PR #78)
-- ADR: docs/design/AGENDA-EVENTOS-EVT0-decisao.md
--
-- Adiciona `events.notificado_em` (timestamptz null) — carimbo de idempotência do
-- aviso síncrono à equipe interna quando um evento é confirmado (POST
-- /events/{id}/confirm), atrás da flag AGENDA_NOTIFY_ENABLED (default off). NULL =
-- ainda não avisado; preenchido = aviso já despachado, não reenvia.
--
-- Só uma coluna nullable (sem ALTER TYPE) => roda em transação. Idempotente via
-- IF NOT EXISTS. A RLS de `events` (tenant_isolation FOR ALL em igreja_id, 0003)
-- já cobre a coluna nova — policy é por linha, não por coluna. Não toca
-- BYPASSRLS / set_tenant_context.
--
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ============================================================================

begin;

alter table events add column if not exists notificado_em timestamptz;

commit;
