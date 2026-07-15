-- ============================================================================
-- PastorAI — Migration 20260715_204540 — MSG-IDEMP-1: defesa em profundidade
-- no banco contra duplicação de mensagem INBOUND (Redis TTL/falha/corrida).
--
-- Contexto: o worker (app/workers/queue_worker.py) usa Redis
-- (WebhookQueue.mark_processed_if_new) como PRIMEIRA barreira de idempotência,
-- chaveada pelo id estável da Evolution (`data.key.id`, exposto como
-- `ParsedMessage.provider_message_id`). Essa marca expira em 7 dias
-- (PROCESSED_TTL_SECONDS) e não sobrevive a um Redis indisponível/flush — nesses
-- casos a mesma mensagem redelivrada pela Evolution era reingerida em Postgres
-- sem NENHUMA checagem: `ingest_message_event_ex` sempre fazia INSERT
-- incondicional, duplicando a linha em `messages` e rodando o agente de novo
-- para a mesma mensagem.
--
-- Fecha isso com um índice único PARCIAL em `messages (igreja_id,
-- provider_message_id)`, restrito às linhas INBOUND (`direcao = 'in'`) — só
-- essas carregam um id de provider e só essas o Redis dedupe protege hoje.
-- Mensagens outbound (agente/humano) não têm essa garantia e continuam livres
-- (fora do escopo desta missão).
--
-- `ingest_message_event_ex` (app/workers/queue_worker.py) passa a capturar o
-- IntegrityError de unique_violation no commit final e devolve
-- IngestionResult.DUPLICATE em vez de propagar. A transação inteira
-- (Pessoa/Conversation/Message) faz ROLLBACK atômico nessa violação, então uma
-- corrida na PRIMEIRA mensagem de um contato novo nunca deixa Pessoa/Conversation
-- órfã do lado perdedor. O agente (run_agent_for_message) só roda quando
-- outcome.result == REGISTERED, então a duplicata nunca dispara um novo turno.
--
-- Escopo por igreja_id (multi-tenant, mesmo padrão SEC-4/E13): o MESMO
-- provider_message_id em igrejas diferentes não colide (instâncias distintas).
--
-- Idempotente (`add column if not exists` / `create unique index if not
-- exists`). Sem ALTER TYPE => roda em transação (padrão EVT-1/EVT-6).
--
-- ⚠️ Aplicar manualmente no Supabase, em ordem de nome de arquivo. A criação do
-- índice FALHA se já houver duplicatas inbound (igreja_id, provider_message_id)
-- pré-existentes — comportamento correto (não mascarar dado sujo). Antes de
-- aplicar em DEV/PROD, checar:
--
--   select igreja_id, provider_message_id, count(*)
--     from messages
--    where direcao = 'in' and provider_message_id is not null
--    group by 1, 2 having count(*) > 1;
--
-- Se retornar linhas, resolver (apagar as duplicatas mais recentes, mantendo a
-- mais antiga) antes de reaplicar. A coluna é nova e sempre NULL no histórico
-- existente (nunca foi populada antes desta missão) — não há dado a limpar hoje.
-- ============================================================================

begin;

alter table messages
  add column if not exists provider_message_id text;

create unique index if not exists messages_inbound_provider_id_uidx
  on messages (igreja_id, provider_message_id)
  where direcao = 'in' and provider_message_id is not null;

commit;
