-- Tenant/state/age index for the private memory inventory.
-- Apply via migrate.py --no-transaction, preserving existing ENABLE/FORCE RLS.
SET lock_timeout = '2s';
CREATE INDEX CONCURRENTLY IF NOT EXISTS private_erasure_requests_overview_idx
    ON public.private_erasure_requests (igreja_id, state, created_at);
-- Rollback (authorized maintenance, --no-transaction):
-- Before retrying a failed build, check whether the index exists and is valid:
-- SELECT indisvalid FROM pg_index
-- WHERE indexrelid = to_regclass('public.private_erasure_requests_overview_idx');
-- IF NOT EXISTS does not repair an INVALID index. Drop it concurrently first:
-- DROP INDEX CONCURRENTLY IF EXISTS public.private_erasure_requests_overview_idx;
-- Existing ENABLE/FORCE ROW LEVEL SECURITY and policies remain unchanged.
