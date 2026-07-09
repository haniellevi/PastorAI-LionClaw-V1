-- ============================================================================
-- PastorAI — Migration 20260708_221808_igreja_dono_id_grant_update
-- Fix: GRANT ausente em igrejas.dono_id (achado no planejamento 7B-8).
--
-- A migration 20260707_011455_igreja_logo_branding.sql fez
--   `revoke update on igrejas from authenticated;`
-- e devolveu UPDATE só para `logo_path`. `dono_id` ficou de fora: desde então
-- `team.py` (PUT /team/{id}/roles, ao remover o papel admin de quem é o
-- dono_id) faz `igreja.dono_id = None` sob `SET LOCAL ROLE authenticated` e
-- falha com 42501 permission denied — confirmado contra o DEV real via
-- `has_column_privilege('authenticated','public.igrejas','dono_id','UPDATE')`
-- = false (logo_path = true). Antes da migration de branding esse mesmo UPDATE
-- já era um StaleDataError (RLS SELECT-only, 0 linhas casadas) — o bug é
-- pré-existente, essa migration só devolve o grant que faltou.
--
-- Nenhuma policy nova: `igrejas_self_update` (da migration de branding) já
-- cobre dono_id (`using/with check (id = current_igreja_id())`).
--
-- Idempotente (GRANT é idempotente por natureza) e transacional.
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ============================================================================

begin;

grant update (dono_id) on igrejas to authenticated;

commit;
