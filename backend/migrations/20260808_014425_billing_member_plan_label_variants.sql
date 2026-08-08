-- ============================================================================
-- PastorAI — Migration 20260808_014425_billing_member_plan_label_variants
-- Completa a troca de terminologia dos planos sem alterar nomes personalizados.
-- A base DEV usa a variante legada "101 a 200 pessoas", não contemplada pela
-- migration anterior.
--
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ALTER TYPE ... ADD VALUE: NÃO usar begin/commit (ver README).
-- ============================================================================

begin;

update public.planos
   set nome = '101–200 membros'
 where codigo = '101_200'
   and nome in ('101 a 200 pessoas', '101-200 pessoas', '101–200 pessoas');

commit;
