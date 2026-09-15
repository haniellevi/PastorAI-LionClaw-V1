\set ON_ERROR_STOP on
\pset pager off
\pset null '[null]'

-- M-MIGRATION-HEAD77-DEV-APPLY-READINESS-READONLY
-- Read-only DEV preflight. Run manually by Raniel only in an already
-- authenticated DEV SQL session. This file contains no connection material.
-- It reads no tenant payload and ends the normal path with ROLLBACK.

BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL search_path = pg_catalog;
SET LOCAL statement_timeout = '10000ms';
SET LOCAL lock_timeout = '2000ms';
SET LOCAL idle_in_transaction_session_timeout = '30000ms';
SET LOCAL row_security = on;

SELECT
  'SESSION_PROOF_V1' AS record_type,
  pg_catalog.current_setting('server_version') AS server_version,
  pg_catalog.current_setting('server_version_num') AS server_version_num,
  pg_catalog.current_setting('transaction_isolation') AS transaction_isolation,
  pg_catalog.current_setting('transaction_read_only') AS transaction_read_only,
  pg_catalog.current_setting('row_security') AS row_security_setting,
  current_user = session_user AS current_user_matches_session_user,
  COALESCE((
    SELECT role_row.rolsuper OR role_row.rolbypassrls
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = current_user
  ), false) AS current_role_superuser_or_bypassrls;

WITH ledger_targets(schema_name, relation_name, ledger_name) AS (
  VALUES
    ('public'::pg_catalog.text, 'schema_migrations'::pg_catalog.text,
     'public.schema_migrations'::pg_catalog.text),
    ('supabase_migrations'::pg_catalog.text,
     'schema_migrations'::pg_catalog.text,
     'supabase_migrations.schema_migrations'::pg_catalog.text)
)
SELECT
  'LEDGER_RELATION' AS record_type,
  target.ledger_name,
  CASE
    WHEN relation_row.oid IS NULL THEN 'ABSENT'
    WHEN relation_row.relkind <> 'r' THEN 'INVALID_KIND'
    ELSE 'PRESENT'
  END AS state,
  relation_row.relkind AS relation_kind,
  relation_row.relpersistence AS persistence,
  relation_row.relrowsecurity AS rls_enabled,
  relation_row.relforcerowsecurity AS rls_forced,
  COALESCE((
    SELECT pg_catalog.count(*)
    FROM pg_catalog.pg_trigger AS trigger_row
    WHERE trigger_row.tgrelid = relation_row.oid
      AND NOT trigger_row.tgisinternal
  ), 0) AS user_trigger_count,
  COALESCE((
    SELECT pg_catalog.count(*)
    FROM pg_catalog.pg_rewrite AS rule_row
    WHERE rule_row.ev_class = relation_row.oid
      AND rule_row.rulename <> '_RETURN'
  ), 0) AS user_rule_count
FROM ledger_targets AS target
LEFT JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.nspname = target.schema_name
LEFT JOIN pg_catalog.pg_class AS relation_row
  ON relation_row.relnamespace = namespace_row.oid
 AND relation_row.relname = target.relation_name
ORDER BY target.ledger_name;

SELECT
  'LEDGER_COLUMN' AS record_type,
  namespace_row.nspname || '.' || relation_row.relname AS ledger_name,
  attribute_row.attnum AS ordinal_position,
  attribute_row.attname AS column_name,
  pg_catalog.format_type(attribute_row.atttypid, attribute_row.atttypmod)
    AS column_type,
  attribute_row.attnotnull AS not_null,
  pg_catalog.pg_get_expr(default_row.adbin, default_row.adrelid, true)
    AS column_default
FROM pg_catalog.pg_attribute AS attribute_row
JOIN pg_catalog.pg_class AS relation_row
  ON relation_row.oid = attribute_row.attrelid
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.oid = relation_row.relnamespace
LEFT JOIN pg_catalog.pg_attrdef AS default_row
  ON default_row.adrelid = attribute_row.attrelid
 AND default_row.adnum = attribute_row.attnum
WHERE (namespace_row.nspname, relation_row.relname) IN (
  ('public', 'schema_migrations'),
  ('supabase_migrations', 'schema_migrations')
)
  AND attribute_row.attnum > 0
  AND NOT attribute_row.attisdropped
ORDER BY ledger_name, attribute_row.attnum;

-- The two commands below are generated only after their ledger shape is
-- proven. They read migration metadata, not domain rows or E4b relations.
WITH public_shape AS (
  SELECT
    pg_catalog.to_regclass('public.schema_migrations') AS relation_oid,
    (
      SELECT relation_row.relkind = 'r'
      FROM pg_catalog.pg_class AS relation_row
      WHERE relation_row.oid = pg_catalog.to_regclass('public.schema_migrations')
    ) AS is_table,
    (
      SELECT pg_catalog.count(*) = 2
        AND pg_catalog.count(*) FILTER (
          WHERE (attribute_row.attname = 'name'
                 AND attribute_row.atttypid = 'pg_catalog.text'::pg_catalog.regtype)
             OR (attribute_row.attname = 'applied_at'
                 AND attribute_row.atttypid = 'pg_catalog.timestamptz'::pg_catalog.regtype)
        ) = 2
      FROM pg_catalog.pg_attribute AS attribute_row
      WHERE attribute_row.attrelid = pg_catalog.to_regclass('public.schema_migrations')
        AND attribute_row.attnum > 0
        AND NOT attribute_row.attisdropped
    ) AS columns_match,
    NOT pg_catalog.row_security_active(
      pg_catalog.to_regclass('public.schema_migrations')
    ) AS row_security_inactive
)
SELECT CASE
  WHEN relation_oid IS NOT NULL AND is_table AND columns_match
       AND row_security_inactive THEN
    'SELECT ''PUBLIC_LEDGER_ENTRY'' AS record_type, position, name '
    || 'FROM (SELECT (pg_catalog.row_number() OVER (ORDER BY applied_at ASC, name ASC) - 1)::pg_catalog.int8 AS position, name::pg_catalog.text AS name '
    || 'FROM public.schema_migrations ORDER BY applied_at ASC, name ASC LIMIT 2049) AS ledger_rows;'
  ELSE
    'SELECT ''PUBLIC_LEDGER_NOT_QUERIED_INVALID_SHAPE'' AS record_type;'
END AS query_to_run
FROM public_shape
\gexec

WITH native_shape AS (
  SELECT
    pg_catalog.to_regclass('supabase_migrations.schema_migrations') AS relation_oid,
    (
      SELECT relation_row.relkind = 'r'
      FROM pg_catalog.pg_class AS relation_row
      WHERE relation_row.oid = pg_catalog.to_regclass(
        'supabase_migrations.schema_migrations'
      )
    ) AS is_table,
    EXISTS (
      SELECT 1
      FROM pg_catalog.pg_attribute AS attribute_row
      WHERE attribute_row.attrelid = pg_catalog.to_regclass(
              'supabase_migrations.schema_migrations'
            )
        AND attribute_row.attname = 'version'
        AND attribute_row.atttypid = 'pg_catalog.text'::pg_catalog.regtype
        AND attribute_row.attnum > 0
        AND NOT attribute_row.attisdropped
    ) AS has_version,
    NOT pg_catalog.row_security_active(
      pg_catalog.to_regclass('supabase_migrations.schema_migrations')
    ) AS row_security_inactive
)
SELECT CASE
  WHEN relation_oid IS NOT NULL AND is_table AND has_version
       AND row_security_inactive THEN
    'SELECT ''NATIVE_LEDGER_ENTRY'' AS record_type, position, version '
    || 'FROM (SELECT (pg_catalog.row_number() OVER (ORDER BY version ASC) - 1)::pg_catalog.int8 AS position, version::pg_catalog.text AS version '
    || 'FROM supabase_migrations.schema_migrations ORDER BY version ASC LIMIT 2049) AS ledger_rows;'
  ELSE
    'SELECT ''NATIVE_LEDGER_NOT_QUERIED_INVALID_SHAPE'' AS record_type;'
END AS query_to_run
FROM native_shape
\gexec

WITH e4b_targets(relation_name) AS (
  VALUES
    ('e4b_consent_hold_events'::pg_catalog.text),
    ('e4b_consent_holds'::pg_catalog.text),
    ('e4b_consent_operations'::pg_catalog.text),
    ('e4b_consent_receipts'::pg_catalog.text),
    ('e4b_consent_retentions'::pg_catalog.text),
    ('e4b_consent_streams'::pg_catalog.text)
)
SELECT
  'E4B_RELATION' AS record_type,
  target.relation_name,
  CASE
    WHEN relation_row.oid IS NULL THEN 'ABSENT'
    WHEN relation_row.relkind NOT IN ('r', 'p') THEN 'INVALID_KIND'
    ELSE 'PRESENT'
  END AS state,
  relation_row.relkind AS relation_kind,
  relation_row.relpersistence AS persistence,
  relation_row.relrowsecurity AS rls_enabled,
  relation_row.relforcerowsecurity AS rls_forced
FROM e4b_targets AS target
LEFT JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.nspname = 'public'
LEFT JOIN pg_catalog.pg_class AS relation_row
  ON relation_row.relnamespace = namespace_row.oid
 AND relation_row.relname = target.relation_name
ORDER BY target.relation_name;

WITH e4b_targets(relation_name) AS (
  VALUES
    ('e4b_consent_hold_events'::pg_catalog.text),
    ('e4b_consent_holds'::pg_catalog.text),
    ('e4b_consent_operations'::pg_catalog.text),
    ('e4b_consent_receipts'::pg_catalog.text),
    ('e4b_consent_retentions'::pg_catalog.text),
    ('e4b_consent_streams'::pg_catalog.text)
)
SELECT
  'E4B_COLUMN' AS record_type,
  relation_row.relname AS relation_name,
  attribute_row.attnum AS ordinal_position,
  attribute_row.attname AS column_name,
  pg_catalog.format_type(attribute_row.atttypid, attribute_row.atttypmod)
    AS column_type,
  attribute_row.attnotnull AS not_null,
  pg_catalog.pg_get_expr(default_row.adbin, default_row.adrelid, true)
    AS column_default,
  attribute_row.attidentity AS identity_kind,
  attribute_row.attgenerated AS generated_kind
FROM e4b_targets AS target
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.nspname = 'public'
JOIN pg_catalog.pg_class AS relation_row
  ON relation_row.relnamespace = namespace_row.oid
 AND relation_row.relname = target.relation_name
JOIN pg_catalog.pg_attribute AS attribute_row
  ON attribute_row.attrelid = relation_row.oid
LEFT JOIN pg_catalog.pg_attrdef AS default_row
  ON default_row.adrelid = attribute_row.attrelid
 AND default_row.adnum = attribute_row.attnum
WHERE attribute_row.attnum > 0
  AND NOT attribute_row.attisdropped
ORDER BY relation_row.relname, attribute_row.attnum;

WITH e4b_targets(relation_name) AS (
  VALUES
    ('e4b_consent_hold_events'::pg_catalog.text),
    ('e4b_consent_holds'::pg_catalog.text),
    ('e4b_consent_operations'::pg_catalog.text),
    ('e4b_consent_receipts'::pg_catalog.text),
    ('e4b_consent_retentions'::pg_catalog.text),
    ('e4b_consent_streams'::pg_catalog.text)
)
SELECT
  'E4B_CONSTRAINT' AS record_type,
  relation_row.relname AS relation_name,
  constraint_row.conname AS constraint_name,
  constraint_row.contype AS constraint_type,
  constraint_row.convalidated AS validated,
  constraint_row.condeferrable AS deferrable,
  constraint_row.condeferred AS initially_deferred,
  pg_catalog.pg_get_constraintdef(constraint_row.oid, true) AS definition
FROM e4b_targets AS target
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.nspname = 'public'
JOIN pg_catalog.pg_class AS relation_row
  ON relation_row.relnamespace = namespace_row.oid
 AND relation_row.relname = target.relation_name
JOIN pg_catalog.pg_constraint AS constraint_row
  ON constraint_row.conrelid = relation_row.oid
ORDER BY relation_row.relname, constraint_row.conname;

WITH e4b_targets(relation_name) AS (
  VALUES
    ('e4b_consent_hold_events'::pg_catalog.text),
    ('e4b_consent_holds'::pg_catalog.text),
    ('e4b_consent_operations'::pg_catalog.text),
    ('e4b_consent_receipts'::pg_catalog.text),
    ('e4b_consent_retentions'::pg_catalog.text),
    ('e4b_consent_streams'::pg_catalog.text)
)
SELECT
  'E4B_INDEX' AS record_type,
  relation_row.relname AS relation_name,
  index_row.relname AS index_name,
  index_meta.indisunique AS is_unique,
  index_meta.indisprimary AS is_primary,
  index_meta.indisvalid AS is_valid,
  index_meta.indisready AS is_ready,
  pg_catalog.pg_get_indexdef(index_row.oid, 0, true) AS definition
FROM e4b_targets AS target
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.nspname = 'public'
JOIN pg_catalog.pg_class AS relation_row
  ON relation_row.relnamespace = namespace_row.oid
 AND relation_row.relname = target.relation_name
JOIN pg_catalog.pg_index AS index_meta
  ON index_meta.indrelid = relation_row.oid
JOIN pg_catalog.pg_class AS index_row
  ON index_row.oid = index_meta.indexrelid
ORDER BY relation_row.relname, index_row.relname;

WITH e4b_targets(relation_name) AS (
  VALUES
    ('e4b_consent_hold_events'::pg_catalog.text),
    ('e4b_consent_holds'::pg_catalog.text),
    ('e4b_consent_operations'::pg_catalog.text),
    ('e4b_consent_receipts'::pg_catalog.text),
    ('e4b_consent_retentions'::pg_catalog.text),
    ('e4b_consent_streams'::pg_catalog.text)
)
SELECT
  'E4B_POLICY' AS record_type,
  relation_row.relname AS relation_name,
  policy_row.polname AS policy_name,
  policy_row.polpermissive AS is_permissive,
  policy_row.polcmd AS command_code,
  CASE
    WHEN policy_row.polroles = ARRAY[0]::pg_catalog.oid[] THEN 'PUBLIC_ONLY'
    WHEN policy_row.polroles @> ARRAY[0]::pg_catalog.oid[] THEN 'PUBLIC_PLUS_OTHER'
    ELSE 'NAMED_ROLES'
  END AS role_scope,
  pg_catalog.pg_get_expr(policy_row.polqual, policy_row.polrelid, true)
    AS using_expression,
  pg_catalog.pg_get_expr(policy_row.polwithcheck, policy_row.polrelid, true)
    AS with_check_expression
FROM e4b_targets AS target
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.nspname = 'public'
JOIN pg_catalog.pg_class AS relation_row
  ON relation_row.relnamespace = namespace_row.oid
 AND relation_row.relname = target.relation_name
JOIN pg_catalog.pg_policy AS policy_row
  ON policy_row.polrelid = relation_row.oid
ORDER BY relation_row.relname, policy_row.polname;

WITH e4b_targets(relation_name) AS (
  VALUES
    ('e4b_consent_hold_events'::pg_catalog.text),
    ('e4b_consent_holds'::pg_catalog.text),
    ('e4b_consent_operations'::pg_catalog.text),
    ('e4b_consent_receipts'::pg_catalog.text),
    ('e4b_consent_retentions'::pg_catalog.text),
    ('e4b_consent_streams'::pg_catalog.text)
), target_grantees(grantee_name, role_oid, role_exists) AS (
  SELECT 'PUBLIC'::pg_catalog.text, 0::pg_catalog.oid, true
  UNION ALL
  SELECT expected.grantee_name, role_row.oid, role_row.oid IS NOT NULL
  FROM (VALUES
    ('anon'::pg_catalog.text),
    ('authenticated'::pg_catalog.text),
    ('service_role'::pg_catalog.text),
    ('agent_runtime'::pg_catalog.text)
  ) AS expected(grantee_name)
  LEFT JOIN pg_catalog.pg_roles AS role_row
    ON role_row.rolname = expected.grantee_name
)
SELECT
  'E4B_ACL' AS record_type,
  relation_row.relname AS relation_name,
  grantee.grantee_name,
  grantee.role_exists,
  COALESCE(pg_catalog.array_agg(acl_row.privilege_type ORDER BY acl_row.privilege_type)
    FILTER (WHERE acl_row.privilege_type IS NOT NULL),
    ARRAY[]::pg_catalog.text[]) AS privileges,
  COALESCE(pg_catalog.bool_or(acl_row.is_grantable)
    FILTER (WHERE acl_row.privilege_type IS NOT NULL), false) AS any_grantable
FROM e4b_targets AS target
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.nspname = 'public'
JOIN pg_catalog.pg_class AS relation_row
  ON relation_row.relnamespace = namespace_row.oid
 AND relation_row.relname = target.relation_name
CROSS JOIN target_grantees AS grantee
LEFT JOIN LATERAL pg_catalog.aclexplode(
  COALESCE(relation_row.relacl,
    pg_catalog.acldefault('r'::"char", relation_row.relowner))
) AS acl_row
  ON grantee.role_oid IS NOT NULL
 AND acl_row.grantee = grantee.role_oid
GROUP BY relation_row.relname, grantee.grantee_name,
         grantee.role_exists
ORDER BY relation_row.relname, grantee.grantee_name;

WITH e4b_targets(relation_name) AS (
  VALUES
    ('e4b_consent_hold_events'::pg_catalog.text),
    ('e4b_consent_holds'::pg_catalog.text),
    ('e4b_consent_operations'::pg_catalog.text),
    ('e4b_consent_receipts'::pg_catalog.text),
    ('e4b_consent_retentions'::pg_catalog.text),
    ('e4b_consent_streams'::pg_catalog.text)
)
SELECT
  'E4B_TRIGGER' AS record_type,
  relation_row.relname AS relation_name,
  trigger_row.tgname AS trigger_name,
  trigger_row.tgenabled AS enabled_code,
  function_row.proname AS function_name,
  function_row.prosecdef AS function_security_definer,
  pg_catalog.pg_get_triggerdef(trigger_row.oid, true) AS definition
FROM e4b_targets AS target
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.nspname = 'public'
JOIN pg_catalog.pg_class AS relation_row
  ON relation_row.relnamespace = namespace_row.oid
 AND relation_row.relname = target.relation_name
JOIN pg_catalog.pg_trigger AS trigger_row
  ON trigger_row.tgrelid = relation_row.oid
 AND NOT trigger_row.tgisinternal
JOIN pg_catalog.pg_proc AS function_row
  ON function_row.oid = trigger_row.tgfoid
ORDER BY relation_row.relname, trigger_row.tgname;

SELECT
  'PREFLIGHT_SCOPE' AS record_type,
  'NO_E4B_DOMAIN_ROWS_SELECTED' AS assertion,
  'LEDGER_METADATA_AND_PGCATALOG_ONLY' AS scope;

ROLLBACK;

