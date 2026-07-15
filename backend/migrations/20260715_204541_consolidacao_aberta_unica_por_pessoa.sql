-- ============================================================================
-- PastorAI — Migration 20260715_204541 — CONSOL-1: unicidade da consolidação
-- ABERTA por pessoa (fecha o TOCTOU do INSERT feito por
-- fn_decision_opens_consolidation, disparado por trg_decision_opens_consolidation
-- em AFTER INSERT em `decisions`).
--
-- Fonte do finding: registrar_decisao (app/agent/tools.py) e launch_decision
-- (app/routers/consolidacao.py) inserem uma `decisions` e dão flush — o trigger
-- SEMPRE insere uma nova `consolidacoes`, sem checar se a pessoa já tem uma
-- ABERTA. Duas decisões concorrentes para a MESMA pessoa disparam o trigger nas
-- duas transações, e AMBAS inserem → duas consolidações abertas para a mesma
-- pessoa. Não há linha a travar antes do INSERT (o trigger roda dentro do
-- próprio INSERT em `decisions`) — a garantia correta é o índice no banco,
-- espelhando o padrão de SEC-4B/E13
-- (20260711_224403_celula_solicitacao_e13_open_unique.sql).
--
-- Este índice único PARCIAL impõe "no máximo UMA consolidação aberta por
-- pessoa". A 2ª decisão concorrente para a mesma pessoa recebe unique_violation
-- na consolidação disparada pelo trigger, propagada para fora do `session.flush()`
-- do chamador (router e tool), que traduz determinístico:
--   - painel HTTP  (POST /consolidacao/decisao): 409 Conflict
--   - agente       (registrar_decisao):          ToolError
--
-- Chave: pessoa_id, parcial sobre "aberta" = concluida = false AND
-- abandonada_em IS NULL (mesma definição usada por
-- consolidacoes_concluida_abandonada_excl_chk, W3.2A). Concluída ou abandonada
-- SAI do índice → o histórico é preservado e uma NOVA consolidação para a mesma
-- pessoa pode abrir depois (nova decisão após a anterior encerrar).
--
-- Escopo por pessoa_id (não por igreja_id): cada pessoa pertence a exatamente
-- UMA igreja (pessoas.igreja_id NOT NULL, sem transferência entre tenants), então
-- pessoa_id já é suficiente — não há colisão cross-tenant a evitar aqui (ao
-- contrário de celula_solicitacao, cuja chave de conflito é por célula).
--
-- Índice é físico, ortogonal à RLS/policy tenant_isolation (não a toca).
-- Idempotente (`create unique index if not exists`), transacional (sem ALTER
-- TYPE).
--
-- ⚠️ Aplicar manualmente no Supabase (DEV primeiro), em ordem de nome de
-- arquivo. `create unique index` FALHA se já houver duplicatas abertas —
-- comportamento correto (não mascarar dado sujo). Detectar ANTES de aplicar:
--
--     select pessoa_id, count(*)
--       from consolidacoes
--      where concluida = false and abandonada_em is null
--      group by 1 having count(*) > 1;
--
--   Se retornar linhas, resolver (concluir/abandonar as duplicatas) antes de
--   reaplicar.
-- ============================================================================

begin;

create unique index if not exists uq_consolidacoes_pessoa_aberta
  on consolidacoes (pessoa_id)
  where concluida = false and abandonada_em is null;

commit;
