-- Read-only aggregate for an active admin's own church. No queue payload or
-- person/source identifiers leave the database function.
CREATE OR REPLACE FUNCTION public.operations_notification_outbox_pending_metrics(
    p_igreja_id uuid,
    p_measured_at timestamptz
)
RETURNS TABLE (
    queue_state text,
    item_count bigint,
    oldest_age_seconds double precision,
    overdue_count bigint,
    oldest_overdue_age_seconds double precision
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $function$
DECLARE
    v_claims text;
    v_sub text;
    v_measured_at timestamptz := coalesce(p_measured_at, statement_timestamp());
BEGIN
    v_claims := current_setting('request.jwt.claims', true);
    IF v_claims IS NOT NULL AND v_claims <> '' THEN
        BEGIN
            v_sub := v_claims::jsonb ->> 'sub';
        EXCEPTION WHEN invalid_text_representation THEN
            v_sub := NULL;
        END;
    END IF;
    v_sub := coalesce(
        nullif(v_sub, ''),
        nullif(current_setting('request.jwt.claim.sub', true), '')
    );

    IF p_igreja_id IS NULL
       OR p_igreja_id IS DISTINCT FROM public.current_igreja_id()
       OR v_sub IS NULL
       OR NOT EXISTS (
            SELECT 1
            FROM public.app_users AS principal
            JOIN public.user_roles AS principal_role
              ON principal_role.igreja_id = principal.igreja_id
             AND principal_role.user_id = principal.id
            WHERE principal.igreja_id = p_igreja_id
              AND principal.clerk_user_id = v_sub
              AND (principal.status IS NULL OR principal.status = 'ativo')
              AND principal_role.papel = 'admin'
       ) THEN
        RAISE EXCEPTION 'not authorized' USING ERRCODE = '42501';
    END IF;

    RETURN QUERY
    SELECT 'pending'::text,
           count(*)::bigint,
           max(greatest(0::numeric,
               extract(epoch FROM (v_measured_at - outbox.created_at))))::double precision,
           count(*) FILTER (WHERE outbox.due_at <= v_measured_at)::bigint,
           (max(greatest(0::numeric,
               extract(epoch FROM (v_measured_at - outbox.due_at))))
               FILTER (WHERE outbox.due_at <= v_measured_at))::double precision
    FROM public.notification_outbox AS outbox
    WHERE outbox.igreja_id = p_igreja_id AND outbox.state = 'pendente'
    UNION ALL
    SELECT 'retryable'::text,
           count(*)::bigint,
           max(greatest(0::numeric,
               extract(epoch FROM (v_measured_at - outbox.created_at))))::double precision,
           count(*) FILTER (WHERE outbox.due_at <= v_measured_at)::bigint,
           (max(greatest(0::numeric,
               extract(epoch FROM (v_measured_at - outbox.due_at))))
               FILTER (WHERE outbox.due_at <= v_measured_at))::double precision
    FROM public.notification_outbox AS outbox
    WHERE outbox.igreja_id = p_igreja_id AND outbox.state = 'retry'
    UNION ALL
    SELECT 'expired_lease'::text,
           count(*)::bigint,
           max(greatest(0::numeric,
               extract(epoch FROM (v_measured_at - outbox.created_at))))::double precision,
           count(*)::bigint,
           max(greatest(0::numeric,
               extract(epoch FROM (v_measured_at - outbox.claimed_until))))::double precision
    FROM public.notification_outbox AS outbox
    WHERE outbox.igreja_id = p_igreja_id
      AND outbox.state = 'em_envio'
      AND outbox.claimed_until IS NOT NULL
      AND outbox.claimed_until <= v_measured_at;
END;
$function$;

REVOKE ALL ON FUNCTION public.operations_notification_outbox_pending_metrics(uuid, timestamptz)
    FROM public, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.operations_notification_outbox_pending_metrics(uuid, timestamptz)
    TO authenticated;

-- Rollback (authorized maintenance):
-- Dropping the function also removes its explicit ACL.
-- DROP FUNCTION IF EXISTS public.operations_notification_outbox_pending_metrics(uuid, timestamptz);
