-- Tenant/time index for the admin's rolling usage projection (#537 P2).
-- Runner supports --no-transaction: no write-blocking index build.
-- Preserve the existing igreja_id policy; no new grants or tenant access.
SET lock_timeout = '2s';
CREATE INDEX CONCURRENTLY IF NOT EXISTS ai_usage_logs_igreja_created_at_idx
    ON public.ai_usage_logs (igreja_id, created_at);
-- Rollback (authorized maintenance, --no-transaction):
-- Before retrying a failed build, check whether the index exists and is valid:
-- SELECT indisvalid FROM pg_index
-- WHERE indexrelid = to_regclass('public.ai_usage_logs_igreja_created_at_idx');
-- If indisvalid=false, drop it concurrently before retrying the migration.
-- IF NOT EXISTS does not repair an INVALID index.
-- DROP INDEX CONCURRENTLY IF EXISTS public.ai_usage_logs_igreja_created_at_idx;
-- Existing ENABLE/FORCE ROW LEVEL SECURITY and policies remain unchanged.
