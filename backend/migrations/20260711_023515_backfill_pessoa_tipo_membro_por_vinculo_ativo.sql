-- ============================================================================
-- PastorAI — Migration 20260711_023515 — Missão M7B-W1
-- Backfill: toda Pessoa com vínculo ATIVO em celula_membro é, no mínimo,
-- "membro". Corrige o histórico em que pessoas com celula_membro.ativo=true
-- ficaram com tipo NULL / "contato" / "visitante" (o vínculo canônico não
-- promovia o tipo — corrigido no seam ensure_active_membro nesta mesma PR).
--
-- Regra (idêntica ao seam de código):
--   * tipo IS NULL, 'contato' ou 'visitante'  -> promove para 'membro';
--   * 'membro', 'discipulo', 'lider', 'pastor' -> PRESERVA (nunca rebaixa).
--
-- Tenant-safe: o EXISTS casa pessoa e vínculo pelo MESMO igreja_id — nunca
-- promove uma pessoa por causa de um vínculo de outra igreja. (No SQL editor
-- a conexão é `postgres`/BYPASSRLS e enxerga todos os tenants; por isso o
-- join por igreja_id é obrigatório aqui.)
--
-- Somente DML: não altera schema, enum, índice, RLS nem policy. Idempotente —
-- reexecutar não toca em nada (as linhas já viraram 'membro', que não casa o
-- predicado). Roda em transação (sem ALTER TYPE).
--
-- ⚠️ Aplicar manualmente no Supabase, em ordem de nome de arquivo.
--    Aplicar PRIMEIRO em DEV, rodar as queries de verificação (abaixo), e só
--    então em PROD. NÃO aplicada em nenhum ambiente por esta missão.
-- ============================================================================

begin;

update pessoas p
set tipo = 'membro'
where (p.tipo is null or p.tipo in ('contato', 'visitante'))
  and exists (
    select 1
    from celula_membro cm
    where cm.pessoa_id = p.id
      and cm.igreja_id = p.igreja_id
      and cm.ativo = true
  );

commit;

-- ============================================================================
-- VERIFICAÇÃO (rodar manualmente; não faz parte da transação acima)
-- ============================================================================
--
-- 1) Divergências restantes após o backfill — ESPERADO: 0.
--    (Nenhuma pessoa com vínculo ativo pode continuar null/contato/visitante.)
--
--    select count(*) as divergencias_restantes
--    from pessoas p
--    where (p.tipo is null or p.tipo in ('contato', 'visitante'))
--      and exists (
--        select 1 from celula_membro cm
--        where cm.pessoa_id = p.id
--          and cm.igreja_id = p.igreja_id
--          and cm.ativo = true
--      );
--
-- 2) Contagem por tipo das pessoas COM vínculo ativo (visão pós-backfill).
--    Espera-se zero em 'contato'/'visitante'/NULL.
--
--    select coalesce(p.tipo, '(null)') as tipo, count(*) as qtd
--    from pessoas p
--    where exists (
--      select 1 from celula_membro cm
--      where cm.pessoa_id = p.id
--        and cm.igreja_id = p.igreja_id
--        and cm.ativo = true
--    )
--    group by p.tipo
--    order by 1;
--
-- 3) Prova de que pastor/discipulo/lider NÃO foram alterados.
--    O UPDATE nunca casa esses tipos (WHERE os exclui), logo são intocados por
--    construção. Rode esta contagem ANTES e DEPOIS do backfill: os números têm
--    de ser IDÊNTICOS.
--
--    select p.tipo, count(*) as qtd
--    from pessoas p
--    where p.tipo in ('discipulo', 'lider', 'pastor')
--      and exists (
--        select 1 from celula_membro cm
--        where cm.pessoa_id = p.id
--          and cm.igreja_id = p.igreja_id
--          and cm.ativo = true
--      )
--    group by p.tipo
--    order by p.tipo;
-- ============================================================================
