-- ============================================================================
-- PastorAI — Migration 20260720_014832 — UNIQ-PESSOA-1: unicidade do telefone
-- por tenant entre pessoas ATIVAS.
--
-- Finding: não existe UNIQUE/índice único de telefone em `pessoas`. Os três
-- pontos que criam Pessoa por telefone (queue-worker de inbound —
-- app/workers/queue_worker.py; POST /contacts — app/routers/contacts.py;
-- ativação de convite — app/routers/auth.py) fazem "procura-antes-de-criar",
-- mas isso é TOCTOU: duas criações concorrentes do MESMO telefone/tenant não
-- veem uma à outra e ambas inserem → duas Pessoas para o mesmo número. Sem
-- garantia no banco, nada serializa a corrida.
--
-- Este índice único PARCIAL impõe "no máximo UMA pessoa ATIVA por
-- (igreja_id, telefone)". A 2ª criação concorrente recebe unique_violation
-- (SQLSTATE 23505); o código (savepoint em app/services/pessoa_dedup.py)
-- re-busca a Pessoa vencedora do MESMO tenant e segue com ela — o caminho feliz
-- fica idêntico ao de hoje (padrão CONSOL-1 / SEC-4B).
--
-- Chave: (igreja_id, telefone), parcial sobre `arquivada_em IS NULL`.
--   * igreja_id: multi-tenant — o mesmo número pode existir em igrejas
--     diferentes (não há colisão cross-tenant a evitar).
--   * arquivada_em IS NULL: só pessoas ATIVAS. Não há hard delete de Pessoa
--     (arquivamento é soft, W3); uma pessoa arquivada NÃO bloqueia recriar uma
--     ativa com o mesmo telefone — a arquivada sai do índice.
--
-- FORMA ESCOLHIDA: telefone BRUTO (coluna `telefone`), NÃO a expressão do
-- sufixo de 8 dígitos usada na dedupe (right(regexp_replace(telefone,'\D',''
-- ,'g'), 8)). Motivo — o sufixo é apenas um FILTRO de estreitamento barato na
-- dedupe do código, que SEMPRE confirma a igualdade canônica completa em Python
-- (normalize_phone) logo depois, JUSTAMENTE porque o sufixo é ambíguo: dois
-- números REALMENTE distintos (DDDs diferentes, mesmo número local de 8
-- dígitos) compartilham o mesmo sufixo. Um índice ÚNICO sobre o sufixo
-- rejeitaria esses números legítimos e distintos (falso-positivo, falha dura na
-- criação de uma pessoa válida) — regressão inaceitável e contrária ao próprio
-- design da dedupe. O índice bruto nunca gera falso-positivo e trava exatamente
-- a corrida real (duas inserções com o MESMO texto de telefone — ex.: duas
-- mensagens inbound do mesmo número, que usam parsed.telefone_raw idêntico). A
-- unicidade canônica (variações +55 / 9º dígito) permanece garantida na dedupe
-- da aplicação, como já era. FASE A confirmou ZERO duplicatas em DEV, então o
-- índice entra limpo.
--
-- Índice físico, ortogonal à RLS/policy tenant_isolation (não a toca).
-- Idempotente (`create unique index if not exists`), transacional (sem
-- ALTER TYPE).
--
-- ⚠️ Aplicar manualmente no Supabase (DEV primeiro), em ordem de nome de
-- arquivo. `create unique index` FALHA se já houver duplicatas ATIVAS — correto
-- (não mascarar dado sujo). Detectar ANTES de aplicar:
--
--     select igreja_id, telefone, count(*)
--       from pessoas
--      where arquivada_em is null
--      group by 1, 2 having count(*) > 1;
--
--   Se retornar linhas, resolver (arquivar/mesclar as duplicatas) antes de
--   reaplicar.
-- ============================================================================

begin;

create unique index if not exists uq_pessoas_telefone_ativa
  on pessoas (igreja_id, telefone)
  where arquivada_em is null;

commit;
