\set ON_ERROR_STOP on
\pset pager off
\pset null '[null]'

-- F1 catalog-bound observation only. Run manually by Raniel in an already
-- authenticated DEV session. This file contains no connection material and
-- emits no target binding, unexpected role name/OID, SQL statement, or domain row.
-- Allowlisted grantee names are emitted only with their explicit classification.
-- Verify this file's SHA-256 in F1-CANDIDATE-MANIFEST.md before use.

\if :{?f1_target_binding_sha256}
\else
\echo F1_ABORT_MISSING_TARGET_BINDING
\quit 3
\endif

BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL search_path = pg_catalog;
SET LOCAL statement_timeout = '15000ms';
SET LOCAL lock_timeout = '2000ms';
SET LOCAL idle_in_transaction_session_timeout = '30000ms';
SET LOCAL row_security = off;

SELECT CASE
  WHEN :'f1_target_binding_sha256' ~ '^[0-9a-f]{64}$' THEN true
  ELSE false
END AS f1_target_binding_is_valid
\gset

\if :f1_target_binding_is_valid
\else
\echo F1_ABORT_INVALID_TARGET_BINDING_FORMAT
ROLLBACK;
\quit 3
\endif

SELECT
  'TARGET_DIGEST' AS record_type,
  pg_catalog.encode(
    pg_catalog.sha256(
      pg_catalog.convert_to(
        :'f1_target_binding_sha256' || pg_catalog.chr(31) ||
        pg_catalog.current_database() || pg_catalog.chr(31) ||
        COALESCE(
          pg_catalog.inet_server_port()::pg_catalog.text,
          'UNIX_SOCKET'
        ) || pg_catalog.chr(31) ||
        pg_catalog.current_setting('server_version_num'),
        'UTF8'
      )
    ),
    'hex'
  ) AS "TARGET_DIGEST";

SELECT
  'F1_SESSION' AS record_type,
  pg_catalog.current_setting('server_version_num') AS server_version_num,
  pg_catalog.current_setting('transaction_isolation') AS transaction_isolation,
  pg_catalog.current_setting('transaction_read_only') AS transaction_read_only,
  pg_catalog.current_setting('row_security') AS row_security_setting,
  current_user = session_user AS current_user_matches_session_user,
  COALESCE((
    SELECT role_row.rolsuper OR role_row.rolbypassrls
    FROM pg_catalog.pg_roles AS role_row
    WHERE role_row.rolname = current_user
  ), false) AS current_role_superuser_or_bypassrls,
  'TARGET_BINDING_PRESENT_FORMAT_VALID_NOT_PRINTED' AS target_binding_state;

WITH ledger_targets(schema_name, relation_name, ledger_ref) AS (
  VALUES
    ('public'::pg_catalog.text, 'schema_migrations'::pg_catalog.text,
     'PUBLIC_LEDGER'::pg_catalog.text),
    ('supabase_migrations'::pg_catalog.text,
     'schema_migrations'::pg_catalog.text,
     'NATIVE_LEDGER'::pg_catalog.text)
)
SELECT
  'LEDGER_RELATION' AS record_type,
  target.ledger_ref,
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
ORDER BY target.ledger_ref;

SELECT
  'LEDGER_COLUMN' AS record_type,
  CASE
    WHEN namespace_row.nspname = 'public' THEN 'PUBLIC_LEDGER'
    ELSE 'NATIVE_LEDGER'
  END AS ledger_ref,
  attribute_row.attnum AS ordinal_position,
  attribute_row.attname AS column_name,
  pg_catalog.format_type(attribute_row.atttypid, attribute_row.atttypmod)
    AS column_type,
  attribute_row.attnotnull AS not_null,
  CASE
    WHEN default_row.oid IS NULL THEN 'NO_DEFAULT'
    ELSE pg_catalog.md5(
      pg_catalog.pg_get_expr(default_row.adbin, default_row.adrelid, true)
    )
  END AS default_definition_md5
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
ORDER BY ledger_ref, attribute_row.attnum;

WITH public_ledger_shape AS (
  SELECT
    pg_catalog.to_regclass('public.schema_migrations') AS relation_oid,
    EXISTS (
      SELECT 1
      FROM pg_catalog.pg_class AS relation_row
      WHERE relation_row.oid = pg_catalog.to_regclass('public.schema_migrations')
        AND relation_row.relkind = 'r'
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
    ) AS columns_match
)
SELECT (
  relation_oid IS NOT NULL AND is_table AND columns_match
) AS f1_public_ledger_shape_valid
FROM public_ledger_shape
\gset

\if :f1_public_ledger_shape_valid
SELECT
  'PUBLIC_LEDGER_COUNT_EXPECTATION' AS record_type,
  CASE
    WHEN pg_catalog.count(*) = 33 THEN 'EXPECTED_33'
    ELSE 'UNEXPECTED_COUNT'
  END AS state
FROM public.schema_migrations;

SELECT (pg_catalog.count(*) = 33) AS f1_public_ledger_count_expected
FROM public.schema_migrations
\gset

\if :f1_public_ledger_count_expected
SELECT
  'PUBLIC_LEDGER_ENTRY' AS record_type,
  (pg_catalog.row_number() OVER (ORDER BY applied_at ASC, name ASC) - 1)::pg_catalog.int8 AS position,
  pg_catalog.md5(name) AS migration_name_md5,
  (applied_at IS NULL) AS applied_at_null
FROM public.schema_migrations
ORDER BY applied_at ASC, name ASC
LIMIT 33;
\else
\echo F1_ABORT_UNEXPECTED_PUBLIC_LEDGER_COUNT
ROLLBACK;
\quit 4
\endif
\else
\echo F1_ABORT_PUBLIC_LEDGER_INVALID_SHAPE
ROLLBACK;
\quit 4
\endif

WITH native_ledger_shape AS (
  SELECT
    pg_catalog.to_regclass('supabase_migrations.schema_migrations') AS relation_oid,
    EXISTS (
      SELECT 1
      FROM pg_catalog.pg_class AS relation_row
      WHERE relation_row.oid = pg_catalog.to_regclass(
              'supabase_migrations.schema_migrations'
            )
        AND relation_row.relkind = 'r'
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
    EXISTS (
      SELECT 1
      FROM pg_catalog.pg_attribute AS attribute_row
      WHERE attribute_row.attrelid = pg_catalog.to_regclass(
              'supabase_migrations.schema_migrations'
            )
        AND attribute_row.attname = 'statements'
        AND attribute_row.atttypid = 'pg_catalog.text[]'::pg_catalog.regtype
        AND attribute_row.attnum > 0
        AND NOT attribute_row.attisdropped
    ) AS has_statements
)
SELECT (
  relation_oid IS NOT NULL AND is_table AND has_version AND has_statements
) AS f1_native_ledger_shape_valid
FROM native_ledger_shape
\gset

\if :f1_native_ledger_shape_valid
SELECT
  'NATIVE_LEDGER_COUNT_EXPECTATION' AS record_type,
  CASE
    WHEN pg_catalog.count(*) = 6 THEN 'EXPECTED_6'
    ELSE 'UNEXPECTED_COUNT'
  END AS state
FROM supabase_migrations.schema_migrations;

SELECT (pg_catalog.count(*) = 6) AS f1_native_ledger_count_expected
FROM supabase_migrations.schema_migrations
\gset

\if :f1_native_ledger_count_expected
SELECT
  'NATIVE_LEDGER_ENTRY' AS record_type,
  (pg_catalog.row_number() OVER (ORDER BY version ASC) - 1)::pg_catalog.int8 AS position,
  pg_catalog.md5(version) AS version_md5,
  pg_catalog.cardinality(statements) AS statement_count
FROM supabase_migrations.schema_migrations
ORDER BY version ASC
LIMIT 6;

SELECT
  'NATIVE_LEDGER_STATEMENT_FINGERPRINT' AS record_type,
  (pg_catalog.row_number() OVER (ORDER BY version ASC) - 1)::pg_catalog.int8 AS position,
  CASE
    WHEN statements IS NULL THEN 'STATEMENTS_NULL'
    ELSE pg_catalog.md5(
      pg_catalog.array_to_string(statements, pg_catalog.chr(31), '<NULL>')
    )
  END AS statements_md5_or_state,
  CASE
    WHEN statements IS NULL THEN 'STATEMENTS_NULL'
    WHEN EXISTS (
      SELECT 1
      FROM pg_catalog.unnest(statements) AS statement_text
      WHERE pg_catalog.lower(
        pg_catalog.regexp_replace(
          statement_text,
          E'^[[:space:]]*(/\\*([^*]|\\*+[^*/])*\\*/|--[^\\r\\n]*[\\r\\n])[[:space:]]*',
          '',
          ''
        )
      ) ~ '^(create|alter|drop|grant|revoke)[[:space:]]'
    ) THEN 'NON_SENSITIVE_DDL_PATTERN_PRESENT'
    ELSE 'NO_NON_SENSITIVE_DDL_PATTERN'
  END AS statement_pattern
FROM supabase_migrations.schema_migrations
ORDER BY version ASC
LIMIT 6;
\else
\echo F1_ABORT_UNEXPECTED_NATIVE_LEDGER_COUNT
ROLLBACK;
\quit 4
\endif
\else
\echo F1_ABORT_NATIVE_LEDGER_INVALID_SHAPE
ROLLBACK;
\quit 4
\endif

SELECT
  'CATALOG_SCHEMA' AS record_type,
  CASE namespace_row.nspname
    WHEN 'recovery' THEN 'RECOVERY_SCHEMA_OPAQUE'
    ELSE namespace_row.nspname
  END AS schema_ref,
  CASE WHEN namespace_row.nspacl IS NULL THEN 'NO_DIRECT_NSPACL' ELSE 'DIRECT_NSPACL_PRESENT' END AS acl_state
FROM pg_catalog.pg_namespace AS namespace_row
WHERE namespace_row.nspname IN ('public', 'agent_private', 'recovery')
ORDER BY schema_ref;

SELECT
  'CATALOG_RELATION' AS record_type,
  CASE namespace_row.nspname
    WHEN 'recovery' THEN 'RECOVERY_SCHEMA_OPAQUE'
    ELSE namespace_row.nspname
  END AS schema_ref,
  CASE
    WHEN namespace_row.nspname = 'recovery'
      OR relation_row.relname LIKE '\_clerk%' ESCAPE '\'
      THEN 'OPAQUE_RELATION_' || pg_catalog.md5(relation_row.relname)
    ELSE relation_row.relname
  END AS relation_ref,
  relation_row.relkind AS relation_kind,
  relation_row.relpersistence AS persistence,
  relation_row.relrowsecurity AS rls_enabled,
  relation_row.relforcerowsecurity AS rls_forced,
  relation_row.relreplident AS replica_identity,
  CASE WHEN relation_row.relacl IS NULL THEN 'NO_DIRECT_RELACL' ELSE 'DIRECT_RELACL_PRESENT' END AS acl_state
FROM pg_catalog.pg_class AS relation_row
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.oid = relation_row.relnamespace
WHERE namespace_row.nspname IN ('public', 'agent_private', 'recovery')
  AND relation_row.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
ORDER BY schema_ref, relation_ref;

SELECT
  'CATALOG_COLUMN' AS record_type,
  CASE namespace_row.nspname
    WHEN 'recovery' THEN 'RECOVERY_SCHEMA_OPAQUE'
    ELSE namespace_row.nspname
  END AS schema_ref,
  CASE
    WHEN namespace_row.nspname = 'recovery'
      OR relation_row.relname LIKE '\_clerk%' ESCAPE '\'
      THEN 'OPAQUE_RELATION_' || pg_catalog.md5(relation_row.relname)
    ELSE relation_row.relname
  END AS relation_ref,
  attribute_row.attnum AS ordinal_position,
  CASE
    WHEN namespace_row.nspname = 'recovery'
      OR relation_row.relname LIKE '\_clerk%' ESCAPE '\'
      THEN 'OPAQUE_COLUMN_' || pg_catalog.md5(attribute_row.attname)
    ELSE attribute_row.attname
  END AS column_ref,
  pg_catalog.format_type(attribute_row.atttypid, attribute_row.atttypmod) AS column_type,
  attribute_row.attnotnull AS not_null,
  attribute_row.attidentity AS identity_kind,
  attribute_row.attgenerated AS generated_kind,
  CASE
    WHEN default_row.oid IS NULL THEN 'NO_DEFAULT'
    ELSE pg_catalog.md5(
      pg_catalog.pg_get_expr(default_row.adbin, default_row.adrelid, true)
    )
  END AS default_definition_md5
FROM pg_catalog.pg_attribute AS attribute_row
JOIN pg_catalog.pg_class AS relation_row
  ON relation_row.oid = attribute_row.attrelid
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.oid = relation_row.relnamespace
LEFT JOIN pg_catalog.pg_attrdef AS default_row
  ON default_row.adrelid = attribute_row.attrelid
 AND default_row.adnum = attribute_row.attnum
WHERE namespace_row.nspname IN ('public', 'agent_private', 'recovery')
  AND relation_row.relkind IN ('r', 'p')
  AND attribute_row.attnum > 0
  AND NOT attribute_row.attisdropped
ORDER BY schema_ref, relation_ref, attribute_row.attnum;

SELECT
  'CATALOG_CONSTRAINT' AS record_type,
  CASE namespace_row.nspname
    WHEN 'recovery' THEN 'RECOVERY_SCHEMA_OPAQUE'
    ELSE namespace_row.nspname
  END AS schema_ref,
  CASE
    WHEN namespace_row.nspname = 'recovery'
      OR relation_row.relname LIKE '\_clerk%' ESCAPE '\'
      THEN 'OPAQUE_RELATION_' || pg_catalog.md5(relation_row.relname)
    ELSE relation_row.relname
  END AS relation_ref,
  CASE
    WHEN namespace_row.nspname = 'recovery'
      OR relation_row.relname LIKE '\_clerk%' ESCAPE '\'
      THEN 'OPAQUE_CONSTRAINT_' || pg_catalog.md5(constraint_row.conname)
    ELSE constraint_row.conname
  END AS constraint_ref,
  constraint_row.contype AS constraint_type,
  constraint_row.convalidated AS validated,
  constraint_row.condeferrable AS deferrable,
  constraint_row.condeferred AS initially_deferred,
  pg_catalog.md5(pg_catalog.pg_get_constraintdef(constraint_row.oid, true))
    AS definition_md5
FROM pg_catalog.pg_constraint AS constraint_row
JOIN pg_catalog.pg_class AS relation_row
  ON relation_row.oid = constraint_row.conrelid
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.oid = relation_row.relnamespace
WHERE namespace_row.nspname IN ('public', 'agent_private', 'recovery')
ORDER BY schema_ref, relation_ref, constraint_ref;

SELECT
  'CATALOG_INDEX' AS record_type,
  CASE namespace_row.nspname
    WHEN 'recovery' THEN 'RECOVERY_SCHEMA_OPAQUE'
    ELSE namespace_row.nspname
  END AS schema_ref,
  CASE
    WHEN namespace_row.nspname = 'recovery'
      OR relation_row.relname LIKE '\_clerk%' ESCAPE '\'
      THEN 'OPAQUE_RELATION_' || pg_catalog.md5(relation_row.relname)
    ELSE relation_row.relname
  END AS relation_ref,
  CASE
    WHEN namespace_row.nspname = 'recovery'
      OR relation_row.relname LIKE '\_clerk%' ESCAPE '\'
      THEN 'OPAQUE_INDEX_' || pg_catalog.md5(index_relation.relname)
    ELSE index_relation.relname
  END AS index_ref,
  index_meta.indisunique AS is_unique,
  index_meta.indisprimary AS is_primary,
  index_meta.indisvalid AS is_valid,
  index_meta.indisready AS is_ready,
  index_meta.indislive AS is_live,
  pg_catalog.md5(pg_catalog.pg_get_indexdef(index_relation.oid, 0, true))
    AS definition_md5,
  CASE
    WHEN index_meta.indpred IS NULL THEN 'NO_PREDICATE'
    ELSE pg_catalog.md5(pg_catalog.pg_get_expr(index_meta.indpred, index_meta.indrelid, true))
  END AS predicate_md5
FROM pg_catalog.pg_index AS index_meta
JOIN pg_catalog.pg_class AS relation_row
  ON relation_row.oid = index_meta.indrelid
JOIN pg_catalog.pg_class AS index_relation
  ON index_relation.oid = index_meta.indexrelid
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.oid = relation_row.relnamespace
WHERE namespace_row.nspname IN ('public', 'agent_private', 'recovery')
ORDER BY schema_ref, relation_ref, index_ref;

SELECT
  'CATALOG_RLS_POLICY' AS record_type,
  CASE namespace_row.nspname
    WHEN 'recovery' THEN 'RECOVERY_SCHEMA_OPAQUE'
    ELSE namespace_row.nspname
  END AS schema_ref,
  CASE
    WHEN namespace_row.nspname = 'recovery'
      OR relation_row.relname LIKE '\_clerk%' ESCAPE '\'
      THEN 'OPAQUE_RELATION_' || pg_catalog.md5(relation_row.relname)
    ELSE relation_row.relname
  END AS relation_ref,
  relation_row.relrowsecurity AS rls_enabled,
  relation_row.relforcerowsecurity AS rls_forced,
  CASE
    WHEN policy_row.oid IS NULL THEN 'POLICY_ABSENT'
    WHEN namespace_row.nspname = 'recovery'
      OR relation_row.relname LIKE '\_clerk%' ESCAPE '\'
      THEN 'OPAQUE_POLICY_' || pg_catalog.md5(policy_row.polname)
    ELSE policy_row.polname
  END AS policy_ref,
  policy_row.polpermissive AS is_permissive,
  policy_row.polcmd AS command_code,
  CASE
    WHEN policy_row.oid IS NULL THEN 'NO_POLICY'
    WHEN policy_row.polroles = ARRAY[0]::pg_catalog.oid[] THEN 'PUBLIC_ONLY'
    WHEN policy_row.polroles @> ARRAY[0]::pg_catalog.oid[] THEN 'PUBLIC_PLUS_NAMED'
    ELSE 'NAMED_ROLES_ONLY'
  END AS role_scope,
  CASE
    WHEN policy_row.oid IS NULL OR policy_row.polqual IS NULL THEN 'NO_USING_EXPRESSION'
    ELSE pg_catalog.md5(pg_catalog.pg_get_expr(policy_row.polqual, policy_row.polrelid, true))
  END AS using_expression_md5,
  CASE
    WHEN policy_row.oid IS NULL OR policy_row.polwithcheck IS NULL THEN 'NO_CHECK_EXPRESSION'
    ELSE pg_catalog.md5(pg_catalog.pg_get_expr(policy_row.polwithcheck, policy_row.polrelid, true))
  END AS check_expression_md5,
  CASE
    WHEN policy_row.oid IS NULL THEN false
    ELSE pg_catalog.strpos(
      COALESCE(
        pg_catalog.pg_get_expr(policy_row.polqual, policy_row.polrelid, true),
        ''
      ) || COALESCE(
        pg_catalog.pg_get_expr(policy_row.polwithcheck, policy_row.polrelid, true),
        ''
      ),
      'app.tenant_igreja_id'
    ) > 0
  END AS mentions_tenant_guc
FROM pg_catalog.pg_class AS relation_row
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.oid = relation_row.relnamespace
LEFT JOIN pg_catalog.pg_policy AS policy_row
  ON policy_row.polrelid = relation_row.oid
WHERE namespace_row.nspname IN ('public', 'agent_private', 'recovery')
  AND relation_row.relkind IN ('r', 'p')
ORDER BY schema_ref, relation_ref, policy_ref;

SELECT
  'CATALOG_FUNCTION' AS record_type,
  CASE namespace_row.nspname
    WHEN 'recovery' THEN 'RECOVERY_SCHEMA_OPAQUE'
    ELSE namespace_row.nspname
  END AS schema_ref,
  CASE
    WHEN namespace_row.nspname = 'recovery' THEN 'OPAQUE_FUNCTION_' || pg_catalog.md5(procedure_row.proname)
    ELSE procedure_row.proname
  END AS function_ref,
  procedure_row.prokind AS function_kind,
  language_row.lanname AS language_name,
  procedure_row.provolatile AS volatility,
  procedure_row.prosecdef AS security_definer,
  procedure_row.proleakproof AS leakproof,
  pg_catalog.md5(COALESCE(pg_catalog.array_to_string(procedure_row.proconfig, ',', '<NULL>'), '<NO_CONFIG>'))
    AS config_md5,
  pg_catalog.md5(pg_catalog.pg_get_functiondef(procedure_row.oid)) AS definition_md5
FROM pg_catalog.pg_proc AS procedure_row
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.oid = procedure_row.pronamespace
JOIN pg_catalog.pg_language AS language_row
  ON language_row.oid = procedure_row.prolang
WHERE namespace_row.nspname IN ('public', 'agent_private', 'recovery')
ORDER BY schema_ref, function_ref, procedure_row.oid;

SELECT
  'CATALOG_TRIGGER' AS record_type,
  CASE namespace_row.nspname
    WHEN 'recovery' THEN 'RECOVERY_SCHEMA_OPAQUE'
    ELSE namespace_row.nspname
  END AS schema_ref,
  CASE
    WHEN namespace_row.nspname = 'recovery'
      OR relation_row.relname LIKE '\_clerk%' ESCAPE '\'
      THEN 'OPAQUE_RELATION_' || pg_catalog.md5(relation_row.relname)
    ELSE relation_row.relname
  END AS relation_ref,
  CASE
    WHEN namespace_row.nspname = 'recovery'
      OR relation_row.relname LIKE '\_clerk%' ESCAPE '\'
      THEN 'OPAQUE_TRIGGER_' || pg_catalog.md5(trigger_row.tgname)
    ELSE trigger_row.tgname
  END AS trigger_ref,
  trigger_row.tgenabled AS enabled_code,
  CASE
    WHEN namespace_row.nspname = 'recovery'
      OR relation_row.relname LIKE '\_clerk%' ESCAPE '\'
      OR function_namespace.nspname = 'recovery'
      THEN 'OPAQUE_FUNCTION_' || pg_catalog.md5(function_row.proname)
    ELSE function_namespace.nspname || '.' || function_row.proname
  END AS function_ref,
  pg_catalog.md5(pg_catalog.pg_get_triggerdef(trigger_row.oid, true)) AS definition_md5
FROM pg_catalog.pg_trigger AS trigger_row
JOIN pg_catalog.pg_class AS relation_row
  ON relation_row.oid = trigger_row.tgrelid
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.oid = relation_row.relnamespace
JOIN pg_catalog.pg_proc AS function_row
  ON function_row.oid = trigger_row.tgfoid
JOIN pg_catalog.pg_namespace AS function_namespace
  ON function_namespace.oid = function_row.pronamespace
WHERE namespace_row.nspname IN ('public', 'agent_private', 'recovery')
  AND NOT trigger_row.tgisinternal
ORDER BY schema_ref, relation_ref, trigger_ref;

SELECT
  'CATALOG_TYPE' AS record_type,
  namespace_row.nspname AS schema_ref,
  type_row.typname AS type_name,
  type_row.typtype AS type_kind,
  COALESCE((
    SELECT pg_catalog.count(*)
    FROM pg_catalog.pg_enum AS enum_row
    WHERE enum_row.enumtypid = type_row.oid
  ), 0) AS enum_label_count,
  COALESCE((
    SELECT pg_catalog.md5(
      pg_catalog.string_agg(enum_row.enumlabel, pg_catalog.chr(31) ORDER BY enum_row.enumsortorder)
    )
    FROM pg_catalog.pg_enum AS enum_row
    WHERE enum_row.enumtypid = type_row.oid
  ), 'NO_ENUM_LABELS') AS enum_labels_md5
FROM pg_catalog.pg_type AS type_row
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.oid = type_row.typnamespace
WHERE namespace_row.nspname IN ('public', 'agent_private')
  AND type_row.typtype IN ('e', 'd')
ORDER BY schema_ref, type_name;

WITH runtime_role AS (
  SELECT *
  FROM pg_catalog.pg_roles
  WHERE rolname = 'agent_runtime'
)
SELECT
  'CATALOG_ROLE_AGENT_RUNTIME' AS record_type,
  CASE WHEN runtime_role.oid IS NULL THEN 'ABSENT' ELSE 'PRESENT' END AS state,
  COALESCE(runtime_role.rolcanlogin, false) AS can_login,
  COALESCE(runtime_role.rolinherit, false) AS inherit,
  COALESCE(runtime_role.rolsuper, false) AS superuser,
  COALESCE(runtime_role.rolbypassrls, false) AS bypass_rls,
  COALESCE(runtime_role.rolcreatedb, false) AS create_db,
  COALESCE(runtime_role.rolcreaterole, false) AS create_role,
  COALESCE(runtime_role.rolreplication, false) AS replication,
  COALESCE(runtime_role.rolconnlimit, -1) AS connection_limit,
  CASE
    WHEN runtime_role.oid IS NULL THEN 'ROLE_ABSENT'
    ELSE pg_catalog.md5(
      COALESCE(pg_catalog.array_to_string(runtime_role.rolconfig, ',', '<NULL>'), '<NO_CONFIG>')
    )
  END AS config_md5
FROM (SELECT 1) AS singleton
LEFT JOIN runtime_role ON true;

WITH runtime_role AS (
  SELECT oid
  FROM pg_catalog.pg_roles
  WHERE rolname = 'agent_runtime'
)
SELECT
  'CATALOG_ROLE_AGENT_RUNTIME_MEMBERSHIP' AS record_type,
  COALESCE((
    SELECT pg_catalog.count(*)
    FROM pg_catalog.pg_auth_members AS membership_row
    JOIN runtime_role ON true
    WHERE membership_row.member = runtime_role.oid
       OR membership_row.roleid = runtime_role.oid
  ), 0) AS membership_edge_count
FROM (SELECT 1) AS singleton;

WITH allowlisted_roles(rolname, grantee_class) AS (
  VALUES
    ('anon'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('authenticated'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('service_role'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('agent_runtime'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('postgres'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('supabase_admin'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('supabase_auth_admin'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('dashboard_user'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('authenticator'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('supabase_storage_admin'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('pgbouncer'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('supabase_realtime_admin'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('supabase_replication_admin'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text)
), target_schemas(scope_ref, nspname) AS (
  VALUES
    ('PUBLIC_SCHEMA'::pg_catalog.text, 'public'::pg_catalog.name),
    ('AGENT_PRIVATE_SCHEMA'::pg_catalog.text, 'agent_private'::pg_catalog.name),
    ('RECOVERY_SCHEMA_OPAQUE'::pg_catalog.text, 'recovery'::pg_catalog.name)
)
SELECT
  'SCHEMA_ACL_DIRECT_GRANTEE' AS record_type,
  target.scope_ref,
  CASE
    WHEN namespace_row.oid IS NULL THEN 'TARGET_SCHEMA_ABSENT'
    WHEN acl_row.grantee IS NULL THEN 'NO_DIRECT_NSPACL'
    WHEN acl_row.grantee = 0 THEN 'PUBLIC'
    ELSE COALESCE(allowlisted_roles.grantee_class, 'UNEXPECTED_CUSTOM_GRANTEE')
  END AS grantee_class,
  CASE
    WHEN namespace_row.oid IS NULL THEN 'TARGET_SCHEMA_ABSENT'
    WHEN acl_row.grantee IS NULL THEN 'NO_DIRECT_GRANTEE'
    WHEN acl_row.grantee = 0 THEN 'PUBLIC'
    WHEN allowlisted_roles.rolname IS NOT NULL
      THEN allowlisted_roles.rolname::pg_catalog.text
    ELSE 'UNEXPECTED_CUSTOM_GRANTEE'
  END AS grantee_ref,
  COALESCE(acl_row.privilege_type, 'NONE') AS privilege_type,
  COALESCE(acl_row.is_grantable, false) AS is_grantable
FROM target_schemas AS target
LEFT JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.nspname = target.nspname
LEFT JOIN LATERAL pg_catalog.aclexplode(namespace_row.nspacl) AS acl_row ON true
LEFT JOIN pg_catalog.pg_roles AS grantee_role
  ON grantee_role.oid = acl_row.grantee
LEFT JOIN allowlisted_roles
  ON allowlisted_roles.rolname = grantee_role.rolname
ORDER BY target.scope_ref, grantee_class, privilege_type;

WITH allowlisted_roles(rolname, grantee_class) AS (
  VALUES
    ('anon'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('authenticated'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('service_role'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('agent_runtime'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('postgres'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('supabase_admin'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('supabase_auth_admin'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('dashboard_user'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('authenticator'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('supabase_storage_admin'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('pgbouncer'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('supabase_realtime_admin'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('supabase_replication_admin'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text)
), target_schemas(scope_ref, nspname) AS (
  VALUES
    ('PUBLIC_SCHEMA'::pg_catalog.text, 'public'::pg_catalog.name),
    ('AGENT_PRIVATE_SCHEMA'::pg_catalog.text, 'agent_private'::pg_catalog.name),
    ('RECOVERY_SCHEMA_OPAQUE'::pg_catalog.text, 'recovery'::pg_catalog.name)
)
SELECT
  'RELACL_DIRECT_GRANTEE' AS record_type,
  target.scope_ref,
  CASE
    WHEN target.scope_ref = 'RECOVERY_SCHEMA_OPAQUE'
      OR relation_row.relname LIKE '\_clerk%' ESCAPE '\'
      THEN 'OPAQUE_RELATION_' || pg_catalog.md5(relation_row.relname)
    ELSE relation_row.relname
  END AS relation_ref,
  relation_row.relkind AS relation_kind,
  CASE
    WHEN acl_row.grantee IS NULL THEN 'NO_DIRECT_RELACL'
    WHEN acl_row.grantee = 0 THEN 'PUBLIC'
    ELSE COALESCE(allowlisted_roles.grantee_class, 'UNEXPECTED_CUSTOM_GRANTEE')
  END AS grantee_class,
  CASE
    WHEN acl_row.grantee IS NULL THEN 'NO_DIRECT_GRANTEE'
    WHEN acl_row.grantee = 0 THEN 'PUBLIC'
    WHEN allowlisted_roles.rolname IS NOT NULL
      THEN allowlisted_roles.rolname::pg_catalog.text
    ELSE 'UNEXPECTED_CUSTOM_GRANTEE'
  END AS grantee_ref,
  COALESCE(acl_row.privilege_type, 'NONE') AS privilege_type,
  COALESCE(acl_row.is_grantable, false) AS is_grantable
FROM target_schemas AS target
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.nspname = target.nspname
JOIN pg_catalog.pg_class AS relation_row
  ON relation_row.relnamespace = namespace_row.oid
LEFT JOIN LATERAL pg_catalog.aclexplode(relation_row.relacl) AS acl_row ON true
LEFT JOIN pg_catalog.pg_roles AS grantee_role
  ON grantee_role.oid = acl_row.grantee
LEFT JOIN allowlisted_roles
  ON allowlisted_roles.rolname = grantee_role.rolname
WHERE relation_row.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
ORDER BY target.scope_ref, relation_ref, grantee_class, privilege_type;

WITH allowlisted_roles(rolname, grantee_class) AS (
  VALUES
    ('anon'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('authenticated'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('service_role'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('agent_runtime'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('postgres'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('supabase_admin'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('supabase_auth_admin'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('dashboard_user'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('authenticator'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('supabase_storage_admin'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('pgbouncer'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('supabase_realtime_admin'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('supabase_replication_admin'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text)
), target_schemas(scope_ref, nspname) AS (
  VALUES
    ('PUBLIC_SCHEMA'::pg_catalog.text, 'public'::pg_catalog.name),
    ('AGENT_PRIVATE_SCHEMA'::pg_catalog.text, 'agent_private'::pg_catalog.name),
    ('RECOVERY_SCHEMA_OPAQUE'::pg_catalog.text, 'recovery'::pg_catalog.name)
)
SELECT
  'PROACL_DIRECT_GRANTEE' AS record_type,
  target.scope_ref,
  CASE
    WHEN target.scope_ref = 'RECOVERY_SCHEMA_OPAQUE'
      THEN 'OPAQUE_FUNCTION_' || pg_catalog.md5(procedure_row.proname)
    ELSE procedure_row.proname
  END AS function_ref,
  procedure_row.prokind AS function_kind,
  CASE
    WHEN acl_row.grantee IS NULL THEN 'NO_DIRECT_PROACL'
    WHEN acl_row.grantee = 0 THEN 'PUBLIC'
    ELSE COALESCE(allowlisted_roles.grantee_class, 'UNEXPECTED_CUSTOM_GRANTEE')
  END AS grantee_class,
  CASE
    WHEN acl_row.grantee IS NULL THEN 'NO_DIRECT_GRANTEE'
    WHEN acl_row.grantee = 0 THEN 'PUBLIC'
    WHEN allowlisted_roles.rolname IS NOT NULL
      THEN allowlisted_roles.rolname::pg_catalog.text
    ELSE 'UNEXPECTED_CUSTOM_GRANTEE'
  END AS grantee_ref,
  COALESCE(acl_row.privilege_type, 'NONE') AS privilege_type,
  COALESCE(acl_row.is_grantable, false) AS is_grantable
FROM target_schemas AS target
JOIN pg_catalog.pg_namespace AS namespace_row
  ON namespace_row.nspname = target.nspname
JOIN pg_catalog.pg_proc AS procedure_row
  ON procedure_row.pronamespace = namespace_row.oid
LEFT JOIN LATERAL pg_catalog.aclexplode(procedure_row.proacl) AS acl_row ON true
LEFT JOIN pg_catalog.pg_roles AS grantee_role
  ON grantee_role.oid = acl_row.grantee
LEFT JOIN allowlisted_roles
  ON allowlisted_roles.rolname = grantee_role.rolname
ORDER BY target.scope_ref, function_ref, procedure_row.oid, grantee_class, privilege_type;

WITH target_schema_names(scope_ref, nspname) AS (
  VALUES
    ('PUBLIC_SCHEMA'::pg_catalog.text, 'public'::pg_catalog.name),
    ('AGENT_PRIVATE_SCHEMA'::pg_catalog.text, 'agent_private'::pg_catalog.name),
    ('RECOVERY_SCHEMA_OPAQUE'::pg_catalog.text, 'recovery'::pg_catalog.name)
), target_scopes(scope_ref, nspoid) AS (
  SELECT target.scope_ref, namespace_row.oid
  FROM target_schema_names AS target
  LEFT JOIN pg_catalog.pg_namespace AS namespace_row
    ON namespace_row.nspname = target.nspname
  UNION ALL
  SELECT 'GLOBAL_NAMESPACE'::pg_catalog.text, 0::pg_catalog.oid
)
SELECT
  'DEFAULT_ACL_SCOPE' AS record_type,
  scope.scope_ref,
  pg_catalog.count(default_acl_row.oid) AS default_acl_row_count
FROM target_scopes AS scope
LEFT JOIN pg_catalog.pg_default_acl AS default_acl_row
  ON default_acl_row.defaclnamespace = scope.nspoid
GROUP BY scope.scope_ref
ORDER BY scope.scope_ref;

WITH allowlisted_roles(rolname, grantee_class) AS (
  VALUES
    ('anon'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('authenticated'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('service_role'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('agent_runtime'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('postgres'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('supabase_admin'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('supabase_auth_admin'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('dashboard_user'::pg_catalog.name, 'ALLOWLIST_ROLE'::pg_catalog.text),
    ('authenticator'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('supabase_storage_admin'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('pgbouncer'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('supabase_realtime_admin'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text),
    ('supabase_replication_admin'::pg_catalog.name, 'PLATFORM_ROLE'::pg_catalog.text)
), target_schema_names(scope_ref, nspname) AS (
  VALUES
    ('PUBLIC_SCHEMA'::pg_catalog.text, 'public'::pg_catalog.name),
    ('AGENT_PRIVATE_SCHEMA'::pg_catalog.text, 'agent_private'::pg_catalog.name),
    ('RECOVERY_SCHEMA_OPAQUE'::pg_catalog.text, 'recovery'::pg_catalog.name)
), target_scopes(scope_ref, nspoid) AS (
  SELECT target.scope_ref, namespace_row.oid
  FROM target_schema_names AS target
  LEFT JOIN pg_catalog.pg_namespace AS namespace_row
    ON namespace_row.nspname = target.nspname
  UNION ALL
  SELECT 'GLOBAL_NAMESPACE'::pg_catalog.text, 0::pg_catalog.oid
)
SELECT
  'DEFAULT_ACL_DIRECT_GRANTEE' AS record_type,
  scope.scope_ref,
  COALESCE(default_acl_row.defaclobjtype, '?') AS object_kind,
  CASE
    WHEN scope.nspoid IS NULL AND scope.scope_ref <> 'GLOBAL_NAMESPACE'
      THEN 'TARGET_SCHEMA_ABSENT'
    WHEN default_acl_row.oid IS NULL THEN 'NO_DIRECT_DEFAULT_ACL'
    WHEN acl_row.grantee IS NULL THEN 'NO_DIRECT_DEFAULT_ACL'
    WHEN acl_row.grantee = 0 THEN 'PUBLIC'
    ELSE COALESCE(allowlisted_roles.grantee_class, 'UNEXPECTED_CUSTOM_GRANTEE')
  END AS grantee_class,
  CASE
    WHEN scope.nspoid IS NULL AND scope.scope_ref <> 'GLOBAL_NAMESPACE'
      THEN 'TARGET_SCHEMA_ABSENT'
    WHEN default_acl_row.oid IS NULL OR acl_row.grantee IS NULL
      THEN 'NO_DIRECT_GRANTEE'
    WHEN acl_row.grantee = 0 THEN 'PUBLIC'
    WHEN allowlisted_roles.rolname IS NOT NULL
      THEN allowlisted_roles.rolname::pg_catalog.text
    ELSE 'UNEXPECTED_CUSTOM_GRANTEE'
  END AS grantee_ref,
  COALESCE(acl_row.privilege_type, 'NONE') AS privilege_type,
  COALESCE(acl_row.is_grantable, false) AS is_grantable
FROM target_scopes AS scope
LEFT JOIN pg_catalog.pg_default_acl AS default_acl_row
  ON default_acl_row.defaclnamespace = scope.nspoid
LEFT JOIN LATERAL pg_catalog.aclexplode(default_acl_row.defaclacl) AS acl_row ON true
LEFT JOIN pg_catalog.pg_roles AS grantee_role
  ON grantee_role.oid = acl_row.grantee
LEFT JOIN allowlisted_roles
  ON allowlisted_roles.rolname = grantee_role.rolname
ORDER BY scope.scope_ref, object_kind, grantee_class, privilege_type;

WITH allowlisted_roles(rolname) AS (
  VALUES
    ('anon'::pg_catalog.name),
    ('authenticated'::pg_catalog.name),
    ('service_role'::pg_catalog.name),
    ('agent_runtime'::pg_catalog.name),
    ('postgres'::pg_catalog.name),
    ('supabase_admin'::pg_catalog.name),
    ('supabase_auth_admin'::pg_catalog.name),
    ('dashboard_user'::pg_catalog.name),
    ('authenticator'::pg_catalog.name),
    ('supabase_storage_admin'::pg_catalog.name),
    ('pgbouncer'::pg_catalog.name),
    ('supabase_realtime_admin'::pg_catalog.name),
    ('supabase_replication_admin'::pg_catalog.name)
), target_schemas(scope_ref, nspname) AS (
  VALUES
    ('PUBLIC_SCHEMA'::pg_catalog.text, 'public'::pg_catalog.name),
    ('AGENT_PRIVATE_SCHEMA'::pg_catalog.text, 'agent_private'::pg_catalog.name),
    ('RECOVERY_SCHEMA_OPAQUE'::pg_catalog.text, 'recovery'::pg_catalog.name)
), target_scopes(scope_ref, nspoid) AS (
  SELECT target.scope_ref, namespace_row.oid
  FROM target_schemas AS target
  LEFT JOIN pg_catalog.pg_namespace AS namespace_row
    ON namespace_row.nspname = target.nspname
  UNION ALL
  SELECT 'GLOBAL_NAMESPACE'::pg_catalog.text, 0::pg_catalog.oid
), direct_grants(scope_ref, grantee) AS (
  SELECT target.scope_ref, acl_row.grantee
  FROM target_schemas AS target
  JOIN pg_catalog.pg_namespace AS namespace_row
    ON namespace_row.nspname = target.nspname
  CROSS JOIN LATERAL pg_catalog.aclexplode(namespace_row.nspacl) AS acl_row
  UNION ALL
  SELECT target.scope_ref, acl_row.grantee
  FROM target_schemas AS target
  JOIN pg_catalog.pg_namespace AS namespace_row
    ON namespace_row.nspname = target.nspname
  JOIN pg_catalog.pg_class AS relation_row
    ON relation_row.relnamespace = namespace_row.oid
  CROSS JOIN LATERAL pg_catalog.aclexplode(relation_row.relacl) AS acl_row
  WHERE relation_row.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
  UNION ALL
  SELECT target.scope_ref, acl_row.grantee
  FROM target_schemas AS target
  JOIN pg_catalog.pg_namespace AS namespace_row
    ON namespace_row.nspname = target.nspname
  JOIN pg_catalog.pg_proc AS procedure_row
    ON procedure_row.pronamespace = namespace_row.oid
  CROSS JOIN LATERAL pg_catalog.aclexplode(procedure_row.proacl) AS acl_row
  UNION ALL
  SELECT scope.scope_ref, acl_row.grantee
  FROM target_scopes AS scope
  JOIN pg_catalog.pg_default_acl AS default_acl_row
    ON default_acl_row.defaclnamespace = scope.nspoid
  CROSS JOIN LATERAL pg_catalog.aclexplode(default_acl_row.defaclacl) AS acl_row
), summary AS (
  SELECT
    scope.scope_ref,
    pg_catalog.count(*) FILTER (
      WHERE direct_grants.grantee <> 0
        AND allowlisted_roles.rolname IS NULL
    ) AS unexpected_direct_grant_count
  FROM target_scopes AS scope
  LEFT JOIN direct_grants
    ON direct_grants.scope_ref = scope.scope_ref
  LEFT JOIN pg_catalog.pg_roles AS grantee_role
    ON grantee_role.oid = direct_grants.grantee
  LEFT JOIN allowlisted_roles
    ON allowlisted_roles.rolname = grantee_role.rolname
  GROUP BY scope.scope_ref
)
SELECT
  'UNEXPECTED_CUSTOM_GRANTEE_SUMMARY' AS record_type,
  summary.scope_ref,
  summary.unexpected_direct_grant_count,
  CASE
    WHEN summary.unexpected_direct_grant_count > 0
      THEN 'UNEXPECTED_CUSTOM_GRANTEE'
    ELSE 'NO_UNEXPECTED_CUSTOM_GRANTEE_OBSERVED'
  END AS state
FROM summary
ORDER BY summary.scope_ref;

SELECT
  'PREFLIGHT_SCOPE' AS record_type,
  'PG_CATALOG_AND_TWO_LEDGERS_ONLY' AS assertion,
  'NO_DOMAIN_ROWS_SELECTED' AS domain_data_assertion,
  'NO_LEDGER_STATEMENT_TEXT_PRINTED' AS statement_assertion,
  'ALLOWLISTED_GRANTEE_REF_OR_PUBLIC_ONLY_UNEXPECTED_OPAQUE' AS grantee_assertion,
  'TARGET_DIGEST_ONLY_NO_TARGET_COMPONENTS_PRINTED' AS target_assertion,
  'ROW_SECURITY_OFF_FAIL_CLOSED' AS row_security_assertion,
  'EXPECTED_33_PUBLIC_AND_6_NATIVE_OR_ABORT' AS ledger_count_assertion,
  'PUBLIC_AGENT_PRIVATE_RECOVERY_AND_GLOBAL_ACL_SCOPES' AS acl_scope_assertion;

ROLLBACK;
\echo ROLLBACK_COMPLETED_F1
