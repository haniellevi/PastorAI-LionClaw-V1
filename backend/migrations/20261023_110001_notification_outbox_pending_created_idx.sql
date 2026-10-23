-- Tenant and oldest pending outbox rows for /operations/pending.
SET lock_timeout = '2s';
CREATE INDEX CONCURRENTLY IF NOT EXISTS notification_outbox_pending_igreja_created_idx
    ON public.notification_outbox (igreja_id, created_at) INCLUDE (due_at)
    WHERE state = 'pendente';
-- Rollback (authorized maintenance, --no-transaction):
-- Check validity before retrying a failed build:
-- SELECT indisvalid FROM pg_index
-- WHERE indexrelid = to_regclass('public.notification_outbox_pending_igreja_created_idx');
-- If indisvalid=false, drop the invalid index concurrently before retrying;
-- IF NOT EXISTS does not repair an INVALID index.
-- DROP INDEX CONCURRENTLY IF EXISTS public.notification_outbox_pending_igreja_created_idx;
