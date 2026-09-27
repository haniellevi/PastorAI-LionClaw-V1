-- ============================================================================
-- native_ledger.sql - READ-ONLY look at the Supabase CLI migration ledger
-- supabase_migrations.schema_migrations (never prints its "statements" column).
--
-- Sections:
--   1) existence of the ledger (catalog lookup + to_regclass, never errors)
--   2) its column names/types          (only if it exists and is readable)
--   3) row count
--   4) version, name ordered by version (version only if "name" is missing)
--   5) distinct created_by values with counts, only if that column exists.
--      NOTE: Supabase may store operator e-mails in created_by.
--   6) EXTRA: public.schema_migrations, the ledger written by
--      backend/scripts/migrate.py (existence, columns, count, names only).
--
-- Guarding uses psql \gset + \if, so absent tables are never referenced in SQL
-- sent to the server. One READ ONLY transaction, ROLLBACK at the end.
-- Run (example):  psql "$DATABASE_URL" -X -f native_ledger.sql
-- ============================================================================
\set ON_ERROR_STOP on
BEGIN TRANSACTION READ ONLY;

-- 1) existence
SELECT n.oid IS NOT NULL AS supabase_migrations_schema_exists,
       c.oid IS NOT NULL AS schema_migrations_table_exists,
       CASE WHEN n.oid IS NOT NULL AND has_schema_privilege(n.oid, 'USAGE')
            THEN to_regclass('supabase_migrations.schema_migrations')::text
       END AS to_regclass_result,
       CASE WHEN c.oid IS NOT NULL
            THEN has_schema_privilege(n.oid, 'USAGE') AND has_table_privilege(c.oid, 'SELECT')
       END AS current_user_can_select
FROM (SELECT 1) AS d
LEFT JOIN pg_namespace AS n ON n.nspname = 'supabase_migrations'
LEFT JOIN pg_class AS c
       ON c.relnamespace = n.oid AND c.relname = 'schema_migrations'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f');

SELECT coalesce(c.oid IS NOT NULL AND has_schema_privilege(n.oid, 'USAGE')
                AND has_table_privilege(c.oid, 'SELECT'), false) AS can_list,
       EXISTS (SELECT 1 FROM pg_attribute AS a WHERE a.attrelid = c.oid AND a.attname = 'version'
                  AND a.attnum > 0 AND NOT a.attisdropped) AS has_version,
       EXISTS (SELECT 1 FROM pg_attribute AS a WHERE a.attrelid = c.oid AND a.attname = 'name'
                  AND a.attnum > 0 AND NOT a.attisdropped) AS has_name,
       EXISTS (SELECT 1 FROM pg_attribute AS a WHERE a.attrelid = c.oid AND a.attname = 'created_by'
                  AND a.attnum > 0 AND NOT a.attisdropped) AS has_created_by
FROM (SELECT 1) AS d
LEFT JOIN pg_namespace AS n ON n.nspname = 'supabase_migrations'
LEFT JOIN pg_class AS c
       ON c.relnamespace = n.oid AND c.relname = 'schema_migrations'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
\gset sm_

\if :sm_can_list
  -- 2) columns
  SELECT a.attnum AS ordinal, a.attname AS column_name,
         format_type(a.atttypid, a.atttypmod) AS data_type
  FROM pg_attribute AS a
  WHERE a.attrelid = 'supabase_migrations.schema_migrations'::regclass
    AND a.attnum > 0 AND NOT a.attisdropped
  ORDER BY a.attnum;

  -- 3) row count
  SELECT count(*) AS supabase_ledger_row_count
  FROM supabase_migrations.schema_migrations;

  -- 4) version, name (statements column intentionally never selected)
  \if :sm_has_version
    \if :sm_has_name
      SELECT version, name
      FROM supabase_migrations.schema_migrations
      ORDER BY version;
    \else
      SELECT version
      FROM supabase_migrations.schema_migrations
      ORDER BY version;
    \endif
  \else
    SELECT 'column version does not exist: listing skipped' AS supabase_ledger_listing;
  \endif

  -- 5) created_by distribution
  \if :sm_has_created_by
    SELECT CASE WHEN created_by LIKE '%@%' THEN '<email mascarado>' ELSE created_by END AS created_by,
           count(*) AS migrations
    FROM supabase_migrations.schema_migrations
    GROUP BY 1
    ORDER BY 1 NULLS FIRST;
  \else
    SELECT 'column created_by does not exist' AS supabase_ledger_created_by;
  \endif
\else
  SELECT 'supabase_migrations.schema_migrations is absent or not readable by current_user: nothing listed'
         AS supabase_ledger;
\endif

-- 6) EXTRA: ledger of backend/scripts/migrate.py (public.schema_migrations)
SELECT coalesce(c.oid IS NOT NULL AND has_table_privilege(c.oid, 'SELECT'), false) AS can_list,
       c.oid IS NOT NULL AS table_exists,
       EXISTS (SELECT 1 FROM pg_attribute AS a WHERE a.attrelid = c.oid AND a.attname = 'name'
                  AND a.attnum > 0 AND NOT a.attisdropped) AS has_name
FROM (SELECT 1) AS d
LEFT JOIN pg_namespace AS n ON n.nspname = 'public'
LEFT JOIN pg_class AS c
       ON c.relnamespace = n.oid AND c.relname = 'schema_migrations'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
\gset ps_

\if :ps_can_list
  SELECT a.attnum AS ordinal, a.attname AS column_name,
         format_type(a.atttypid, a.atttypmod) AS data_type
  FROM pg_attribute AS a
  WHERE a.attrelid = 'public.schema_migrations'::regclass
    AND a.attnum > 0 AND NOT a.attisdropped
  ORDER BY a.attnum;

  SELECT count(*) AS migrate_py_ledger_row_count
  FROM public.schema_migrations;

  \if :ps_has_name
    SELECT name AS migrate_py_ledger_name
    FROM public.schema_migrations
    ORDER BY name;
  \endif
\else
  SELECT 'public.schema_migrations (migrate.py ledger) is absent or not readable by current_user'
         AS migrate_py_ledger;
\endif

ROLLBACK;
