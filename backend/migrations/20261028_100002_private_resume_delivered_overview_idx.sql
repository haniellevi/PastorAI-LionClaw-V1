-- Tenant index for delivered private resumes, without blocking WhatsApp writes.
-- Apply via migrate.py --no-transaction, preserving existing ENABLE/FORCE RLS.
SET lock_timeout = '2s';
CREATE INDEX CONCURRENTLY IF NOT EXISTS private_resume_delivered_overview_idx
    ON public.messages (igreja_id)
    WHERE direcao='out' AND autor='ia' AND agent_reply_state='ia'
    AND agent_privilege_context->>'kind'='private_resume';
-- Rollback (authorized maintenance, --no-transaction):
-- Before retrying a failed build, check whether the index exists and is valid:
-- SELECT indisvalid FROM pg_index
-- WHERE indexrelid = to_regclass('public.private_resume_delivered_overview_idx');
-- IF NOT EXISTS does not repair an INVALID index. Drop it concurrently first:
-- DROP INDEX CONCURRENTLY IF EXISTS public.private_resume_delivered_overview_idx;
-- Existing ENABLE/FORCE ROW LEVEL SECURITY and policies remain unchanged.
