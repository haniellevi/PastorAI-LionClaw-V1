-- Tenant and oldest actionable work-queue items for /operations/pending.
SET lock_timeout = '2s';
CREATE INDEX CONCURRENTLY IF NOT EXISTS work_queue_pending_igreja_created_idx
    ON public.work_queue_items (igreja_id, created_at)
    WHERE status IS NULL OR status IN ('aberto', 'assumido');
-- Rollback (authorized maintenance, --no-transaction):
-- Check validity before retrying a failed build:
-- SELECT indisvalid FROM pg_index
-- WHERE indexrelid = to_regclass('public.work_queue_pending_igreja_created_idx');
-- If indisvalid=false, drop the invalid index concurrently before retrying;
-- IF NOT EXISTS does not repair an INVALID index.
-- DROP INDEX CONCURRENTLY IF EXISTS public.work_queue_pending_igreja_created_idx;
