-- Tenant lease-expiry range and creation age for in-flight outbox rows.
SET lock_timeout = '2s';
CREATE INDEX CONCURRENTLY IF NOT EXISTS notification_outbox_lease_igreja_claimed_idx
    ON public.notification_outbox (igreja_id, claimed_until) INCLUDE (created_at)
    WHERE state = 'em_envio' AND claimed_until IS NOT NULL;
-- Rollback (authorized maintenance, --no-transaction):
-- Check validity before retrying a failed build:
-- SELECT indisvalid FROM pg_index
-- WHERE indexrelid = to_regclass('public.notification_outbox_lease_igreja_claimed_idx');
-- If indisvalid=false, drop the invalid index concurrently before retrying;
-- IF NOT EXISTS does not repair an INVALID index.
-- DROP INDEX CONCURRENTLY IF EXISTS public.notification_outbox_lease_igreja_claimed_idx;
