-- Tenant and oldest active outbound IA intents for /operations/pending.
SET lock_timeout = '2s';
CREATE INDEX CONCURRENTLY IF NOT EXISTS messages_pending_agent_igreja_created_idx
    ON public.messages (igreja_id, criado_em)
    WHERE direcao = 'out' AND autor = 'ia'
      AND agent_reply_state IN (
          'ia_reservada', 'ia_executando', 'ia_pendente', 'ia_em_transporte'
      );
-- Rollback (authorized maintenance, --no-transaction):
-- Check validity before retrying a failed build:
-- SELECT indisvalid FROM pg_index
-- WHERE indexrelid = to_regclass('public.messages_pending_agent_igreja_created_idx');
-- If indisvalid=false, drop the invalid index concurrently before retrying;
-- IF NOT EXISTS does not repair an INVALID index.
-- DROP INDEX CONCURRENTLY IF EXISTS public.messages_pending_agent_igreja_created_idx;
