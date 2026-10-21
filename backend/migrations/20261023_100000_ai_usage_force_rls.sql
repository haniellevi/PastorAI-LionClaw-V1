-- Keep the existing igreja_id policy; ensure owners also respect tenant RLS.
-- Separate from the concurrent index because migrate.py executes a file as
-- one command; concurrent index creation must be the sole statement.
SET LOCAL lock_timeout = '2s';
ALTER TABLE public.ai_usage_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_usage_logs FORCE ROW LEVEL SECURITY;
-- Rollback (only restore the pre-migration owner behavior, preserve policy):
-- ALTER TABLE public.ai_usage_logs NO FORCE ROW LEVEL SECURITY;
