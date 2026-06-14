-- ============================================================================
-- PastorAI 1.0 — Migration 0006: Hardening — pin search_path nas funcoes de trigger
-- Supabase database linter (0011_function_search_path_mutable): funcoes sem
-- search_path fixo sao vulneraveis a hijack via schema malicioso no search_path
-- do papel chamador. Fixamos `public, pg_temp` em todas as funcoes de trigger.
--
-- Nota: current_igreja_id() ja nasce com search_path fixo (migration 0003).
-- rls_auto_enable() (event trigger do scaffold) ja tem search_path = pg_catalog.
-- As policies RLS continuam usando current_igreja_id() normalmente; este ajuste
-- nao altera comportamento, apenas blinda a resolucao de nomes.
-- ============================================================================

begin;

alter function public.fn_set_updated_at()                set search_path = public, pg_temp;
alter function public.fn_promote_pipeline()              set search_path = public, pg_temp;
alter function public.fn_link_cell_promote()             set search_path = public, pg_temp;
alter function public.fn_report_received_clears_queue()  set search_path = public, pg_temp;
alter function public.fn_decision_opens_consolidation()  set search_path = public, pg_temp;
alter function public.fn_consent_on_inbound()            set search_path = public, pg_temp;
alter function public.fn_subscription_autoupgrade()      set search_path = public, pg_temp;

commit;
