-- ============================================================================
-- PastorAI — Migration 20260706_221311_pessoas_apto_lider_e_converte_legado_tipo_lider
-- Regra de domínio Células (decisão do dono 2026-07-06):
--   "Líder de Célula" é DERIVADO (celulas.lider_id em célula ativa), nunca um
--   tipo manual de pessoa. Aptidão (realizou o Reencontro) vira flag própria.
--
--   1. pessoas.apto_lider boolean not null default false — apto a liderar.
--   2. Backfill: quem era tipo='lider' vira apto (exceto CSIM, que fica fora
--      da visão) e o tipo converte para 'membro'.
--   3. O valor 'lider' PERMANECE no enum pessoa_tipo (remover valor de enum é
--      caro no PG); o bloqueio de escrita é feito na API (routers/contacts.py).
--
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ALTER TYPE ... ADD VALUE: NÃO usar begin/commit (ver README) — não é o caso
-- aqui (sem ALTER TYPE), então esta migration roda em transação normalmente.
-- ============================================================================

begin;

alter table pessoas
  add column if not exists apto_lider boolean not null default false;

comment on column pessoas.apto_lider is
  'Apto a liderar célula (realizou o Reencontro). Liderança efetiva é derivada de celulas.lider_id em célula ativa.';

-- Legado: tipo='lider' era rótulo manual. Vira apto (CSIM fica de fora) e o
-- tipo converte para 'membro'. Idempotente: re-rodar não encontra mais linhas.
--
-- ⚠️ Efeito colateral conhecido e ACEITO: o UPDATE de tipo dispara
-- trg_promote_pipeline (BEFORE UPDATE OF tipo, 0004_triggers.sql) — ex-líder
-- ainda em etapa NULL/'ganhar' com critérios F2 atendidos (presencas>=3 ou
-- aceitou_jesus) avança para consolidar/em_consolidacao, que é o que a state
-- machine faria no próximo toque na linha. Também dispara
-- trg_subscription_autoupgrade (recontagem, inócuo).
update pessoas
   set apto_lider = true
 where tipo = 'lider'
   and sem_interesse = false;

update pessoas
   set tipo = 'membro'
 where tipo = 'lider';

commit;

-- Verificação (rodar após aplicar):
--   select count(*) from pessoas where tipo = 'lider';           -- esperado: 0
--   select count(*) from pessoas where apto_lider;               -- >= nº de ex-líderes não-CSIM
--   select column_name, data_type, column_default
--     from information_schema.columns
--    where table_name = 'pessoas' and column_name = 'apto_lider';
--   -- CSIM liderando célula ativa (estado legado inválido — se >0, reportar
--   -- ao dono e trocar o líder dessas células):
--   select count(*) from celulas c
--     join pessoas p on p.id = c.lider_id
--    where c.ativo and p.sem_interesse;
