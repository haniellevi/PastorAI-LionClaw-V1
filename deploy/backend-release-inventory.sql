-- Read-only aggregate inventory. psql variables: inventory_role, target_igrejas,
-- require_closed (true after closure and before reopening).
\set ON_ERROR_STOP on
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '10s';
SET LOCAL ROLE :"inventory_role";
SELECT current_database(), current_user, inet_server_addr(), inet_server_port(),
       transaction_timestamp() AS observed_at;
-- Cross-tenant aggregate evidence requires an existing SELECT-only BYPASSRLS
-- role. RLS-filtered emptiness must never stand in for an absent marker.
SELECT rolbypassrls AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreaterole AND NOT rolcreatedb
       AND has_table_privilege(current_user, 'public.consolidation_whatsapp_activation', 'SELECT')
       AND NOT has_table_privilege(current_user, 'public.consolidation_whatsapp_activation', 'INSERT,UPDATE,DELETE,TRUNCATE')
       AND has_table_privilege(current_user, 'public.notification_outbox', 'SELECT')
       AND NOT has_table_privilege(current_user, 'public.notification_outbox', 'INSERT,UPDATE,DELETE,TRUNCATE')
       AND has_table_privilege(current_user, 'public.cell_report_reminders', 'SELECT')
       AND NOT has_table_privilege(current_user, 'public.cell_report_reminders', 'INSERT,UPDATE,DELETE,TRUNCATE')
       AND has_table_privilege(current_user, 'public.consolidacoes', 'SELECT')
       AND NOT has_table_privilege(current_user, 'public.consolidacoes', 'INSERT,UPDATE,DELETE,TRUNCATE')
       AND has_table_privilege(current_user, 'public.work_queue_items', 'SELECT')
       AND NOT has_table_privilege(current_user, 'public.work_queue_items', 'INSERT,UPDATE,DELETE,TRUNCATE') AS role_safe
FROM pg_roles WHERE rolname = current_user
\gset
\if :role_safe
\else
  \echo PARE: role does not prove complete read-only inventory
  SELECT 1 / 0 AS stop_release;
\endif
SELECT cardinality(string_to_array(:'target_igrejas', ',')::uuid[]) > 0
       AND cardinality(string_to_array(:'target_igrejas', ',')::uuid[]) =
           (SELECT count(DISTINCT id) FROM unnest(string_to_array(:'target_igrejas', ',')::uuid[]) id)
       AND NOT EXISTS (SELECT 1 FROM unnest(string_to_array(:'target_igrejas', ',')::uuid[]) id WHERE id IS NULL) AS targets_safe
\gset
\if :targets_safe
\else
  \echo PARE: target set empty or invalid
  SELECT 1 / 0 AS stop_release;
\endif
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
       r.rolname AS owner, current_user AS inventory_role
FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner
WHERE c.oid IN ('public.consolidation_whatsapp_activation'::regclass,
               'public.notification_outbox'::regclass,
               'public.cell_report_reminders'::regclass,
               'public.consolidacoes'::regclass, 'public.work_queue_items'::regclass)
ORDER BY c.relname;
WITH targets AS (SELECT DISTINCT unnest(string_to_array(:'target_igrejas', ',')::uuid[]) AS igreja_id)
SELECT t.igreja_id, a.activated_at, a.gate_open,
       CASE WHEN a.igreja_id IS NULL THEN 'PARE_MARCADOR_AUSENTE'
            WHEN a.gate_open IS FALSE THEN 'FECHADO_OBSERVADO'
            ELSE 'ABERTO' END AS evidence
FROM targets t LEFT JOIN public.consolidation_whatsapp_activation a USING (igreja_id)
ORDER BY t.igreja_id;
SELECT igreja_id, purpose, state, origin_kind, count(*) AS total
FROM public.notification_outbox
WHERE igreja_id = ANY(string_to_array(:'target_igrejas', ',')::uuid[])
GROUP BY igreja_id, purpose, state, origin_kind ORDER BY 1,2,3,4;
SELECT igreja_id, state, count(*) AS total
FROM public.cell_report_reminders
WHERE igreja_id = ANY(string_to_array(:'target_igrejas', ',')::uuid[])
GROUP BY igreja_id, state ORDER BY 1,2;
-- Counts only: source identity, titles, recipients and message bodies are excluded.
SELECT c.igreja_id, c.concluida, (c.abandonada_em IS NOT NULL) AS abandonada,
       (a.activated_at IS NULL OR c.created_at < a.activated_at) AS anterior_ou_epoca_desconhecida,
       count(*) AS total
FROM public.consolidacoes c LEFT JOIN public.consolidation_whatsapp_activation a USING (igreja_id)
WHERE c.igreja_id = ANY(string_to_array(:'target_igrejas', ',')::uuid[])
GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
SELECT w.igreja_id, w.tipo, w.status,
       (a.activated_at IS NULL OR w.created_at < a.activated_at) AS anterior_ou_epoca_desconhecida,
       count(*) AS total
FROM public.work_queue_items w LEFT JOIN public.consolidation_whatsapp_activation a USING (igreja_id)
WHERE w.igreja_id = ANY(string_to_array(:'target_igrejas', ',')::uuid[])
  AND w.tipo IN ('fonovisita', 'conectar_celula')
GROUP BY 1,2,3,4 ORDER BY 1,2,3,4;
WITH targets AS (SELECT DISTINCT unnest(string_to_array(:'target_igrejas', ',')::uuid[]) AS igreja_id)
SELECT bool_and(a.igreja_id IS NOT NULL AND a.activated_at IS NOT NULL
                AND (NOT :'require_closed'::boolean OR a.gate_open IS FALSE)) AS marker_safe
FROM targets t LEFT JOIN public.consolidation_whatsapp_activation a USING (igreja_id)
\gset
\if :marker_safe
\else
  \echo PARE: marker absent, epoch unknown or closure not observed
  SELECT 1 / 0 AS stop_release;
\endif
ROLLBACK;
