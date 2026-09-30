-- psql -X -v ON_ERROR_STOP=1 -v inventory_role=<ROLE_REVISADA> -f this_file
\set ON_ERROR_STOP on
BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '10s';
SET LOCAL ROLE :"inventory_role";
SELECT current_database(), current_user, inet_server_addr(), inet_server_port(), transaction_timestamp();
SELECT rolbypassrls AND NOT rolcanlogin AND NOT rolsuper
       AND has_table_privilege(current_user, 'public.schema_migrations', 'SELECT')
       AND NOT has_table_privilege(current_user, 'public.schema_migrations', 'INSERT,UPDATE,DELETE,TRUNCATE') AS role_safe
FROM pg_roles WHERE rolname=current_user
\gset
\if :role_safe
\else
  \echo PARE: ledger read scope unverifiable
  SELECT 1 / 0 AS stop_release;
\endif
SELECT CASE WHEN name ~ '^[A-Za-z0-9_]+\.sql$' THEN name ELSE '<invalid name>' END AS name
FROM public.schema_migrations ORDER BY name;
SELECT count(*) AS total,
       count(*) FILTER (WHERE name ~ '^00(0[1-9]|1[0-7])_.*\.sql$') AS legacy_0001_0017
FROM public.schema_migrations;
SELECT lpad(n::text,4,'0') AS legacy_prefix, count(m.name) AS entries
FROM generate_series(1,17) n
LEFT JOIN public.schema_migrations m ON left(m.name,5)=lpad(n::text,4,'0') || '_'
GROUP BY n ORDER BY n;
ROLLBACK;
