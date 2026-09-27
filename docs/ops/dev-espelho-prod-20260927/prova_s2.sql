-- ============================================================================
-- prova_s2.sql - checagens de catálogo SÓ LEITURA para 20260926_191500
-- (agent_public_profile), no mesmo formato de ../prod-ledger-20260926/prova_objetos.sql
-- (migration, check_id, kind, ok, detail). O kit de 26/09 cobre até a5244ca e
-- não inclui esta migration. Não lê linhas de tabela.
--
--   psql service=... -X --csv -f prova_s2.sql
-- ============================================================================
\set ON_ERROR_STOP on
BEGIN TRANSACTION READ ONLY;

SELECT checks.migration, checks.check_id, checks.kind, checks.ok, checks.detail
FROM (
  SELECT '20260926_191500_agent_public_profile.sql'::text AS migration, 'c01_col'::text AS check_id,
         'column'::text AS kind, x.ok,
         ('agent_configs.informacoes_publicas jsonb NOT NULL DEFAULT ''{}''::jsonb | observed: ' || x.obs)::text AS detail
    FROM (SELECT coalesce(a.atttypid = 'jsonb'::regtype AND a.attnotnull
                          AND pg_get_expr(d.adbin, d.adrelid) = '''{}''::jsonb', false) AS ok,
                 CASE WHEN a.attname IS NULL THEN 'absent'
                      ELSE format('type=%s not_null=%s default=%s', format_type(a.atttypid, a.atttypmod),
                                  a.attnotnull, coalesce(pg_get_expr(d.adbin, d.adrelid), 'none')) END AS obs
            FROM (SELECT 1) AS dummy
            LEFT JOIN pg_attribute AS a
                   ON a.attrelid = to_regclass('public.agent_configs') AND a.attname = 'informacoes_publicas'
                  AND a.attnum > 0 AND NOT a.attisdropped
            LEFT JOIN pg_attrdef AS d ON d.adrelid = a.attrelid AND d.adnum = a.attnum) AS x
  UNION ALL
  SELECT '20260926_191500_agent_public_profile.sql', 'c02_check', 'constraint', x.ok,
         ('CHECK agent_configs_informacoes_publicas_objeto (jsonb_typeof = object), validada | observed: ' || x.obs)
    FROM (SELECT coalesce(c.contype = 'c' AND c.convalidated
                          AND regexp_replace(lower(pg_get_constraintdef(c.oid)), '[[:space:]]+', '', 'g')
                              LIKE '%jsonb_typeof(informacoes_publicas)=''object''::text%', false) AS ok,
                 CASE WHEN c.oid IS NULL THEN 'absent'
                      ELSE format('type=%s validated=%s', c.contype, c.convalidated) END AS obs
            FROM (SELECT 1) AS dummy
            LEFT JOIN pg_constraint AS c
                   ON c.conrelid = to_regclass('public.agent_configs')
                  AND c.conname = 'agent_configs_informacoes_publicas_objeto') AS x
  UNION ALL
  SELECT '20260926_191500_agent_public_profile.sql', 'c03_rls_policy', 'rls', x.ok,
         ('agent_configs com RLS, sem FORCE e com tenant_isolation (fraca: vem de 0002/0003) | observed: ' || x.obs)
    FROM (SELECT coalesce(c.relrowsecurity AND NOT c.relforcerowsecurity
                          AND EXISTS (SELECT 1 FROM pg_policy AS p WHERE p.polrelid = c.oid
                                        AND p.polname = 'tenant_isolation' AND p.polcmd = '*'), false) AS ok,
                 CASE WHEN c.oid IS NULL THEN 'absent'
                      ELSE format('rls=%s force=%s', c.relrowsecurity, c.relforcerowsecurity) END AS obs
            FROM (SELECT 1) AS dummy
            LEFT JOIN pg_class AS c ON c.oid = to_regclass('public.agent_configs')) AS x
) AS checks
ORDER BY checks.migration, checks.check_id;

ROLLBACK;
