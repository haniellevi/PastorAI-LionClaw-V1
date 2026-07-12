-- ============================================================================
-- PastorAI — Migration 20260711_224403 — SEC-4B / E13: unicidade da solicitação
-- ABERTA por célula (fecha o TOCTOU check→insert da CRIAÇÃO).
--
-- Fonte do finding: create_cell_request (app/routers/cell_requests.py) fazia
--   SELECT `_has_open_conflict` (matriz E13/§6.8) e, se não achasse solicitação
--   aberta conflitante, INSERT — sem trava. Duas criações concorrentes passam as
--   duas pelo SELECT antes de qualquer COMMIT e ambas inserem → DUAS solicitações
--   abertas para o mesmo conflito (E13 violado). FOR UPDATE NÃO resolve: não há
--   linha a travar antes do INSERT. A garantia correta é no banco.
--
-- Estes índices únicos PARCIAIS impõem "no máximo UMA aberta conflitante por
-- célula". A 2ª criação concorrente do MESMO conflito recebe unique_violation,
-- que o router traduz determinístico para 409 (mesma resposta do pré-check, que
-- segue como caminho rápido). As transições (approve/reject/cancel/…) NÃO são
-- tocadas — já protegidas por SEC-4B-A/C.
--
-- Chave exata (espelha a matriz E13 e a invariante pessoa_id IS NOT NULL ⟺ tipo
-- de membro, garantida por conflict_pessoa_id em app/domain/cell_requests.py):
--   (1) tipos sensíveis / multiplicação  → (igreja_id, celula_id, tipo)  [pessoa_id NULL]
--   (2) transferir/remover membro        → (igreja_id, celula_id, pessoa_id) [pessoa_id NOT NULL]
--       SEM o tipo na chave: transferir e remover a MESMA pessoa colidem (E13).
--
-- Por que PARCIAL (só statuses ABERTOS): status terminal (aprovada/rejeitada/
--   cancelada) SAI do índice → o histórico é preservado e uma NOVA solicitação
--   do mesmo tipo/pessoa pode ser aberta depois que a anterior é decidida.
--
-- Escopo por igreja_id ⇒ o MESMO conflito em igrejas DIFERENTES é permitido
--   (multi-tenant). Índice é físico, ortogonal à RLS/policy tenant_isolation
--   (não a toca). Idempotente (`create unique index if not exists`), transacional
--   (sem ALTER TYPE).
--
-- ⚠️ Aplicar manualmente no Supabase (DEV primeiro), em ordem de nome de arquivo.
--   `create unique index` FALHA se já houver DUPLICATAS abertas conflitantes —
--   comportamento correto (não mascarar dado sujo). Detectar ANTES de aplicar:
--
--     -- (1) sensíveis / multiplicação
--     select igreja_id, celula_id, tipo, count(*)
--       from celula_solicitacao
--      where status in ('aguardando','ajuste_solicitado') and pessoa_id is null
--      group by 1,2,3 having count(*) > 1;
--     -- (2) membro
--     select igreja_id, celula_id, pessoa_id, count(*)
--       from celula_solicitacao
--      where status in ('aguardando','ajuste_solicitado') and pessoa_id is not null
--      group by 1,2,3 having count(*) > 1;
--
--   Se retornarem linhas, resolver (cancelar/decidir as duplicatas) antes de
--   reaplicar. Em PROD o fluxo está atrás da flag CELULAS_REQUESTS_ENABLED (OFF):
--   normalmente não há dado a limpar.
-- ============================================================================

begin;

create unique index if not exists uq_celula_solicitacao_aberta_tipo
  on celula_solicitacao (igreja_id, celula_id, tipo)
  where status in ('aguardando', 'ajuste_solicitado') and pessoa_id is null;

create unique index if not exists uq_celula_solicitacao_aberta_membro
  on celula_solicitacao (igreja_id, celula_id, pessoa_id)
  where status in ('aguardando', 'ajuste_solicitado') and pessoa_id is not null;

commit;
