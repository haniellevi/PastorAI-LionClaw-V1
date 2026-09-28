\set ON_ERROR_STOP on
BEGIN TRANSACTION READ ONLY;
\echo == ESTADO FINAL DO LEDGER ==
SELECT c.oid::regclass AS tabela, pg_get_userbyid(c.relowner) AS dono, c.relrowsecurity AS rls, c.relforcerowsecurity AS force_rls, c.relacl::text AS acl
  FROM pg_class c WHERE c.oid = to_regclass('public.schema_migrations');
SELECT r AS role,
       has_table_privilege(r, 'public.schema_migrations', 'SELECT') AS sel,
       has_table_privilege(r, 'public.schema_migrations', 'INSERT') AS ins,
       has_table_privilege(r, 'public.schema_migrations', 'UPDATE') AS upd,
       has_table_privilege(r, 'public.schema_migrations', 'DELETE') AS del,
       has_table_privilege(r, 'public.schema_migrations', 'TRUNCATE') AS trunc,
       has_table_privilege(r, 'public.schema_migrations', 'MAINTAIN') AS maint
  FROM unnest(ARRAY['anon', 'authenticated', 'service_role', 'postgres']) AS r;
SELECT a.attnum, a.attname, format_type(a.atttypid, a.atttypmod) AS tipo, a.attnotnull AS not_null, pg_get_expr(d.adbin, d.adrelid) AS padrao
  FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
 WHERE a.attrelid = to_regclass('public.schema_migrations') AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum;
SELECT conname, pg_get_constraintdef(oid) AS definicao FROM pg_constraint WHERE conrelid = to_regclass('public.schema_migrations') ORDER BY 1;
SELECT count(*) AS policies FROM pg_policy WHERE polrelid = to_regclass('public.schema_migrations');
SELECT origem, count(*) FROM public.schema_migrations GROUP BY 1 ORDER BY 1;
SELECT min(applied_at) AS registrado_em_min, max(applied_at) AS registrado_em_max FROM public.schema_migrations;
SELECT md5(string_agg(name || ':' || origem, ',' ORDER BY name COLLATE "C")) AS lista_md5, '1a5c405f1a7efd47945ffab969fba706' AS esperado FROM public.schema_migrations;
\echo == DEFAULT PRIVILEGES E TRIGGER (devem estar iguais a antes) ==
SELECT pg_get_userbyid(d.defaclrole) AS role, d.defaclobjtype AS tipo, d.defaclacl::text AS acl
  FROM pg_default_acl d JOIN pg_namespace n ON n.oid = d.defaclnamespace WHERE n.nspname = 'public' ORDER BY 1, 2;
SELECT evtname, evtenabled, md5(pg_get_functiondef(evtfoid)) AS func_md5 FROM pg_event_trigger WHERE evtname = 'ensure_rls';
SELECT count(*) AS tabelas_public, count(*) FILTER (WHERE NOT c.relrowsecurity) AS sem_rls, count(*) FILTER (WHERE c.relforcerowsecurity) AS com_force
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p');
\echo == NOMES REGISTRADOS ==
SELECT name, origem FROM public.schema_migrations ORDER BY name COLLATE "C";
ROLLBACK;
