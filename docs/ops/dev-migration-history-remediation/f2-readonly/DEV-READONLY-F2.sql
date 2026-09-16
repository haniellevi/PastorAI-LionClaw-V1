\set ON_ERROR_STOP on
-- F2 DEV catalog observation. Raniel executes this file manually only after
-- both counselors approve its exact SHA-256. It has no connection material,
-- writes, domain reads, raw statement output, or unclassified object names.

\if :{?f2_target_binding_sha256}
\else
\qecho F2_ABORT_MISSING_TARGET_BINDING
\quit
\endif

BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL search_path = pg_catalog;
SET LOCAL statement_timeout = '5000ms';
SET LOCAL lock_timeout = '1000ms';
SET LOCAL idle_in_transaction_session_timeout = '15000ms';
SET LOCAL row_security = off;

SELECT (
  :'f2_target_binding_sha256' ~ '^[0-9a-f]{64}$'
) AS f2_target_binding_valid
\gset
\if :f2_target_binding_valid
\else
\qecho F2_ABORT_INVALID_TARGET_BINDING_FORMAT
ROLLBACK;
\quit
\endif

-- Shape guards are silent. Any mismatch returns only the sanitized abort code.
WITH ledger AS (
  SELECT pg_catalog.to_regclass('public.schema_migrations') AS oid
)
SELECT (
  ledger.oid IS NOT NULL
  AND EXISTS (
    SELECT 1 FROM pg_catalog.pg_class AS c
    WHERE c.oid = ledger.oid
      AND c.relkind = 'r'
      AND c.relpersistence = 'p'
      AND c.relrowsecurity
      AND NOT c.relforcerowsecurity
      AND NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_trigger AS t
        WHERE t.tgrelid = c.oid AND NOT t.tgisinternal
      )
      AND NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_rewrite AS r
        WHERE r.ev_class = c.oid AND r.rulename <> '_RETURN'
      )
  )
  AND (
    SELECT pg_catalog.count(*) = 2
      AND pg_catalog.bool_and(
        CASE a.attname
          WHEN 'name' THEN
            a.atttypid = 'pg_catalog.text'::pg_catalog.regtype
            AND a.attnotnull AND d.oid IS NULL
          WHEN 'applied_at' THEN
            a.atttypid = 'pg_catalog.timestamptz'::pg_catalog.regtype
            AND a.attnotnull
            AND pg_catalog.pg_get_expr(d.adbin, d.adrelid, true) = 'now()'
          ELSE false
        END
      )
    FROM pg_catalog.pg_attribute AS a
    LEFT JOIN pg_catalog.pg_attrdef AS d
      ON d.adrelid = a.attrelid AND d.adnum = a.attnum
    WHERE a.attrelid = ledger.oid
      AND a.attnum > 0 AND NOT a.attisdropped
  )
) AS f2_public_ledger_form_ok
FROM ledger
\gset
\if :f2_public_ledger_form_ok
\else
\qecho F2_ABORT_DEV_LEDGER_SHAPE_DRIFT
ROLLBACK;
\quit
\endif
SELECT (pg_catalog.count(*) = 33) AS f2_public_ledger_count_ok
FROM public.schema_migrations
\gset
\if :f2_public_ledger_count_ok
\else
\qecho F2_ABORT_DEV_LEDGER_SHAPE_DRIFT
ROLLBACK;
\quit
\endif

WITH ledger AS (
  SELECT pg_catalog.to_regclass(
    'supabase_migrations.schema_migrations'
  ) AS oid
)
SELECT (
  ledger.oid IS NOT NULL
  AND EXISTS (
    SELECT 1 FROM pg_catalog.pg_class AS c
    WHERE c.oid = ledger.oid
      AND c.relkind = 'r'
      AND c.relpersistence = 'p'
      AND NOT c.relrowsecurity
      AND NOT c.relforcerowsecurity
      AND NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_trigger AS t
        WHERE t.tgrelid = c.oid AND NOT t.tgisinternal
      )
      AND NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_rewrite AS r
        WHERE r.ev_class = c.oid AND r.rulename <> '_RETURN'
      )
  )
  AND (
    SELECT pg_catalog.count(*) = 6
      AND pg_catalog.bool_and(
        CASE a.attname
          WHEN 'version' THEN
            a.atttypid = 'pg_catalog.text'::pg_catalog.regtype
            AND a.attnotnull AND d.oid IS NULL
          WHEN 'statements' THEN
            a.atttypid = 'pg_catalog.text[]'::pg_catalog.regtype
            AND NOT a.attnotnull AND d.oid IS NULL
          WHEN 'name' THEN
            a.atttypid = 'pg_catalog.text'::pg_catalog.regtype
            AND NOT a.attnotnull AND d.oid IS NULL
          WHEN 'created_by' THEN
            a.atttypid = 'pg_catalog.text'::pg_catalog.regtype
            AND NOT a.attnotnull AND d.oid IS NULL
          WHEN 'idempotency_key' THEN
            a.atttypid = 'pg_catalog.text'::pg_catalog.regtype
            AND NOT a.attnotnull AND d.oid IS NULL
          WHEN 'rollback' THEN
            a.atttypid = 'pg_catalog.text[]'::pg_catalog.regtype
            AND NOT a.attnotnull AND d.oid IS NULL
          ELSE false
        END
      )
    FROM pg_catalog.pg_attribute AS a
    LEFT JOIN pg_catalog.pg_attrdef AS d
      ON d.adrelid = a.attrelid AND d.adnum = a.attnum
    WHERE a.attrelid = ledger.oid
      AND a.attnum > 0 AND NOT a.attisdropped
  )
) AS f2_native_ledger_form_ok
FROM ledger
\gset
\if :f2_native_ledger_form_ok
\else
\qecho F2_ABORT_DEV_LEDGER_SHAPE_DRIFT
ROLLBACK;
\quit
\endif

SELECT (pg_catalog.count(*) = 6) AS f2_native_ledger_count_ok
FROM supabase_migrations.schema_migrations
\gset
\if :f2_native_ledger_count_ok
\else
\qecho F2_ABORT_DEV_LEDGER_SHAPE_DRIFT
ROLLBACK;
\quit
\endif

-- No output precedes successful completion of all environment-specific guards.
SELECT
  'TARGET_DIGEST' AS record_type,
  pg_catalog.encode(
    pg_catalog.sha256(
      pg_catalog.convert_to(
        :'f2_target_binding_sha256' || pg_catalog.chr(31) ||
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
  ) AS target_digest;

SELECT
  'F2_SESSION' AS record_type,
  'DEV' AS environment_class,
  pg_catalog.current_setting('server_version_num') AS server_version_num,
  pg_catalog.current_setting('transaction_isolation') AS transaction_isolation,
  pg_catalog.current_setting('transaction_read_only') AS transaction_read_only,
  pg_catalog.current_setting('statement_timeout') AS statement_timeout,
  pg_catalog.current_setting('lock_timeout') AS lock_timeout,
  pg_catalog.current_setting('idle_in_transaction_session_timeout') AS idle_timeout,
  pg_catalog.current_setting('row_security') AS row_security_setting,
  current_user = session_user AS current_user_matches_session_user,
  COALESCE((
    SELECT r.rolsuper OR r.rolbypassrls
    FROM pg_catalog.pg_roles AS r
    WHERE r.rolname = current_user
  ), false) AS current_role_superuser_or_bypassrls,
  'TARGET_BINDING_PRESENT_FORMAT_VALID_NOT_PRINTED' AS binding_state;

WITH targets(schema_name, relation_name, ledger_ref) AS (
  VALUES
    ('public'::pg_catalog.text, 'schema_migrations'::pg_catalog.text,
     'PUBLIC_LEDGER'::pg_catalog.text),
    ('supabase_migrations'::pg_catalog.text, 'schema_migrations'::pg_catalog.text,
     'NATIVE_LEDGER'::pg_catalog.text)
)
SELECT
  'LEDGER_RELATION' AS record_type,
  target.ledger_ref,
  CASE
    WHEN c.oid IS NULL THEN 'ABSENT'
    WHEN c.relkind = 'r' THEN 'PRESENT'
    ELSE 'INVALID_KIND'
  END AS state,
  c.relkind AS relation_kind,
  c.relpersistence AS persistence,
  c.relrowsecurity AS rls_enabled,
  c.relforcerowsecurity AS rls_forced,
  COALESCE((SELECT pg_catalog.count(*) FROM pg_catalog.pg_trigger AS t
            WHERE t.tgrelid = c.oid AND NOT t.tgisinternal), 0) AS user_trigger_count,
  COALESCE((SELECT pg_catalog.count(*) FROM pg_catalog.pg_rewrite AS r
            WHERE r.ev_class = c.oid AND r.rulename <> '_RETURN'), 0) AS user_rule_count
FROM targets AS target
LEFT JOIN pg_catalog.pg_namespace AS n ON n.nspname = target.schema_name
LEFT JOIN pg_catalog.pg_class AS c
  ON c.relnamespace = n.oid AND c.relname = target.relation_name
ORDER BY target.ledger_ref;

SELECT
  'LEDGER_COLUMN' AS record_type,
  CASE WHEN n.nspname = 'public' THEN 'PUBLIC_LEDGER' ELSE 'NATIVE_LEDGER' END AS ledger_ref,
  a.attnum AS ordinal_position,
  a.attname AS column_name,
  pg_catalog.format_type(a.atttypid, a.atttypmod) AS column_type,
  a.attnotnull AS not_null,
  CASE WHEN d.oid IS NULL THEN 'NO_DEFAULT'
       ELSE pg_catalog.md5(pg_catalog.pg_get_expr(d.adbin, d.adrelid, true)) END AS default_md5
FROM pg_catalog.pg_attribute AS a
JOIN pg_catalog.pg_class AS c ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
LEFT JOIN pg_catalog.pg_attrdef AS d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE (n.nspname, c.relname) IN (
  ('public', 'schema_migrations'),
  ('supabase_migrations', 'schema_migrations')
)
  AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY ledger_ref, a.attnum;

SELECT
  'PUBLIC_LEDGER_COUNT_EXPECTATION' AS record_type,
  'EXPECTED_33' AS state;
SELECT
  'PUBLIC_LEDGER_ENTRY' AS record_type,
  (pg_catalog.row_number() OVER (ORDER BY applied_at ASC, name ASC) - 1)::pg_catalog.int8 AS position,
  pg_catalog.md5(name) AS migration_name_md5,
  (applied_at IS NULL) AS applied_at_null
FROM public.schema_migrations
ORDER BY applied_at ASC, name ASC
LIMIT 33;

SELECT
  'NATIVE_LEDGER_COUNT_EXPECTATION' AS record_type,
  'EXPECTED_6' AS state;

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
  CASE WHEN statements IS NULL THEN 'STATEMENTS_NULL'
       ELSE pg_catalog.md5(pg_catalog.array_to_string(statements, pg_catalog.chr(31), '<NULL>')) END
    AS statements_md5_or_state,
  CASE
    WHEN statements IS NULL THEN 'STATEMENTS_NULL'
    WHEN EXISTS (
      SELECT 1 FROM pg_catalog.unnest(statements) AS statement_text
      WHERE pg_catalog.lower(pg_catalog.regexp_replace(
        statement_text,
        E'^[[:space:]]*(/\\*([^*]|\\*+[^*/])*\\*/|--[^\\r\\n]*[\\r\\n])[[:space:]]*',
        '', ''
      )) ~ '^(create|alter|drop|grant|revoke)[[:space:]]'
    ) THEN 'NON_SENSITIVE_DDL_PATTERN_PRESENT'
    ELSE 'NO_NON_SENSITIVE_DDL_PATTERN'
  END AS statement_pattern
FROM supabase_migrations.schema_migrations
ORDER BY version ASC
LIMIT 6;

-- All domain object identifiers are opaque. Only canonical ledger identifiers
-- and explicitly public role names may be emitted in clear text.
WITH target_schemas(nspname, scope_ref) AS (
  VALUES ('public'::pg_catalog.text, 'PUBLIC_SCHEMA'::pg_catalog.text),
         ('agent_private'::pg_catalog.text, 'AGENT_PRIVATE_SCHEMA'::pg_catalog.text),
         ('recovery'::pg_catalog.text, 'RECOVERY_SCHEMA'::pg_catalog.text)
), allowlisted_roles(rolname) AS (
  VALUES ('postgres'), ('anon'), ('authenticated'), ('service_role'),
         ('agent_runtime'), ('authenticator'), ('supabase_storage_admin'),
         ('pgbouncer'), ('supabase_realtime_admin'), ('supabase_replication_admin')
)
SELECT
  'CATALOG_SCHEMA' AS record_type,
  target.scope_ref,
  CASE WHEN n.oid IS NULL THEN 'ABSENT' ELSE 'PRESENT' END AS state,
  CASE
    WHEN owner.rolname IN (SELECT rolname FROM allowlisted_roles) THEN 'ALLOWLIST_ROLE'
    WHEN owner.rolname LIKE 'pg\_%' ESCAPE '\' THEN 'PREDEFINED_ROLE'
    ELSE 'UNEXPECTED_CUSTOM_OWNER'
  END AS owner_class,
  CASE WHEN n.nspacl IS NULL THEN 'NO_DIRECT_NSPACL' ELSE 'DIRECT_NSPACL_PRESENT' END AS acl_state
FROM target_schemas AS target
LEFT JOIN pg_catalog.pg_namespace AS n ON n.nspname = target.nspname
LEFT JOIN pg_catalog.pg_roles AS owner ON owner.oid = n.nspowner
ORDER BY target.scope_ref;

WITH allowlisted_roles(rolname) AS (
  VALUES ('postgres'), ('anon'), ('authenticated'), ('service_role'),
         ('agent_runtime'), ('authenticator'), ('supabase_storage_admin'),
         ('pgbouncer'), ('supabase_realtime_admin'), ('supabase_replication_admin')
)
SELECT
  'CATALOG_RELATION' AS record_type,
  CASE n.nspname WHEN 'public' THEN 'PUBLIC_SCHEMA'
       WHEN 'agent_private' THEN 'AGENT_PRIVATE_SCHEMA' ELSE 'RECOVERY_SCHEMA' END AS scope_ref,
  CASE WHEN n.nspname = 'public' AND c.relname = 'schema_migrations'
       THEN 'schema_migrations'
       ELSE 'OPAQUE_RELATION_' || pg_catalog.md5(n.nspname || pg_catalog.chr(31) || c.relname) END AS relation_ref,
  c.relkind AS relation_kind,
  c.relpersistence AS persistence,
  c.relrowsecurity AS rls_enabled,
  c.relforcerowsecurity AS rls_forced,
  c.relreplident AS replica_identity,
  CASE
    WHEN owner.rolname IN (SELECT rolname FROM allowlisted_roles) THEN 'ALLOWLIST_ROLE'
    WHEN owner.rolname LIKE 'pg\_%' ESCAPE '\' THEN 'PREDEFINED_ROLE'
    ELSE 'UNEXPECTED_CUSTOM_OWNER'
  END AS owner_class,
  CASE WHEN c.relacl IS NULL THEN 'NO_DIRECT_RELACL' ELSE 'DIRECT_RELACL_PRESENT' END AS acl_state
FROM pg_catalog.pg_class AS c
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
LEFT JOIN pg_catalog.pg_roles AS owner ON owner.oid = c.relowner
WHERE n.nspname IN ('public', 'agent_private', 'recovery')
  AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
ORDER BY scope_ref, relation_ref;

SELECT
  'CATALOG_COLUMN' AS record_type,
  CASE n.nspname WHEN 'public' THEN 'PUBLIC_SCHEMA'
       WHEN 'agent_private' THEN 'AGENT_PRIVATE_SCHEMA' ELSE 'RECOVERY_SCHEMA' END AS scope_ref,
  CASE WHEN n.nspname = 'public' AND c.relname = 'schema_migrations'
       THEN 'schema_migrations'
       ELSE 'OPAQUE_RELATION_' || pg_catalog.md5(n.nspname || pg_catalog.chr(31) || c.relname) END AS relation_ref,
  a.attnum AS ordinal_position,
  CASE WHEN n.nspname = 'public' AND c.relname = 'schema_migrations'
       THEN a.attname
       ELSE 'OPAQUE_COLUMN_' || pg_catalog.md5(n.nspname || pg_catalog.chr(31) || c.relname || pg_catalog.chr(31) || a.attname) END AS column_ref,
  pg_catalog.format_type(a.atttypid, a.atttypmod) AS column_type,
  a.attnotnull AS not_null,
  a.attidentity AS identity_kind,
  a.attgenerated AS generated_kind,
  CASE WHEN d.oid IS NULL THEN 'NO_DEFAULT'
       ELSE pg_catalog.md5(pg_catalog.pg_get_expr(d.adbin, d.adrelid, true)) END AS default_md5
FROM pg_catalog.pg_attribute AS a
JOIN pg_catalog.pg_class AS c ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
LEFT JOIN pg_catalog.pg_attrdef AS d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE n.nspname IN ('public', 'agent_private', 'recovery')
  AND c.relkind IN ('r', 'p')
  AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY scope_ref, relation_ref, a.attnum;

SELECT
  'CATALOG_CONSTRAINT' AS record_type,
  CASE n.nspname WHEN 'public' THEN 'PUBLIC_SCHEMA'
       WHEN 'agent_private' THEN 'AGENT_PRIVATE_SCHEMA' ELSE 'RECOVERY_SCHEMA' END AS scope_ref,
  'OPAQUE_RELATION_' || pg_catalog.md5(n.nspname || pg_catalog.chr(31) || c.relname) AS relation_ref,
  'OPAQUE_CONSTRAINT_' || pg_catalog.md5(n.nspname || pg_catalog.chr(31) || c.relname || pg_catalog.chr(31) || con.conname) AS constraint_ref,
  con.contype AS constraint_type,
  con.convalidated AS validated,
  con.condeferrable AS deferrable,
  con.condeferred AS initially_deferred,
  pg_catalog.md5(pg_catalog.pg_get_constraintdef(con.oid, true)) AS definition_md5
FROM pg_catalog.pg_constraint AS con
JOIN pg_catalog.pg_class AS c ON c.oid = con.conrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname IN ('public', 'agent_private', 'recovery')
ORDER BY scope_ref, relation_ref, constraint_ref;

SELECT
  'CATALOG_INDEX' AS record_type,
  CASE n.nspname WHEN 'public' THEN 'PUBLIC_SCHEMA'
       WHEN 'agent_private' THEN 'AGENT_PRIVATE_SCHEMA' ELSE 'RECOVERY_SCHEMA' END AS scope_ref,
  'OPAQUE_RELATION_' || pg_catalog.md5(n.nspname || pg_catalog.chr(31) || c.relname) AS relation_ref,
  'OPAQUE_INDEX_' || pg_catalog.md5(n.nspname || pg_catalog.chr(31) || ci.relname) AS index_ref,
  i.indisunique AS is_unique,
  i.indisprimary AS is_primary,
  i.indisvalid AS is_valid,
  i.indisready AS is_ready,
  i.indislive AS is_live,
  pg_catalog.md5(pg_catalog.pg_get_indexdef(ci.oid, 0, true)) AS definition_md5,
  CASE WHEN i.indpred IS NULL THEN 'NO_PREDICATE'
       ELSE pg_catalog.md5(pg_catalog.pg_get_expr(i.indpred, i.indrelid, true)) END AS predicate_md5
FROM pg_catalog.pg_index AS i
JOIN pg_catalog.pg_class AS c ON c.oid = i.indrelid
JOIN pg_catalog.pg_class AS ci ON ci.oid = i.indexrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname IN ('public', 'agent_private', 'recovery')
ORDER BY scope_ref, relation_ref, index_ref;

SELECT
  'CATALOG_RLS_POLICY' AS record_type,
  CASE n.nspname WHEN 'public' THEN 'PUBLIC_SCHEMA'
       WHEN 'agent_private' THEN 'AGENT_PRIVATE_SCHEMA' ELSE 'RECOVERY_SCHEMA' END AS scope_ref,
  'OPAQUE_RELATION_' || pg_catalog.md5(n.nspname || pg_catalog.chr(31) || c.relname) AS relation_ref,
  'OPAQUE_POLICY_' || pg_catalog.md5(n.nspname || pg_catalog.chr(31) || c.relname || pg_catalog.chr(31) || p.polname) AS policy_ref,
  p.polcmd AS command,
  p.polpermissive AS permissive,
  pg_catalog.md5(COALESCE(pg_catalog.pg_get_expr(p.polqual, p.polrelid, true), '<NULL>')) AS using_md5,
  pg_catalog.md5(COALESCE(pg_catalog.pg_get_expr(p.polwithcheck, p.polrelid, true), '<NULL>')) AS check_md5
FROM pg_catalog.pg_policy AS p
JOIN pg_catalog.pg_class AS c ON c.oid = p.polrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname IN ('public', 'agent_private', 'recovery')
ORDER BY scope_ref, relation_ref, policy_ref;

SELECT
  'CATALOG_TRIGGER' AS record_type,
  CASE n.nspname WHEN 'public' THEN 'PUBLIC_SCHEMA'
       WHEN 'agent_private' THEN 'AGENT_PRIVATE_SCHEMA' ELSE 'RECOVERY_SCHEMA' END AS scope_ref,
  'OPAQUE_RELATION_' || pg_catalog.md5(n.nspname || pg_catalog.chr(31) || c.relname) AS relation_ref,
  'OPAQUE_TRIGGER_' || pg_catalog.md5(n.nspname || pg_catalog.chr(31) || c.relname || pg_catalog.chr(31) || t.tgname) AS trigger_ref,
  t.tgenabled AS enabled_state,
  pg_catalog.md5(pg_catalog.pg_get_triggerdef(t.oid, true)) AS definition_md5
FROM pg_catalog.pg_trigger AS t
JOIN pg_catalog.pg_class AS c ON c.oid = t.tgrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname IN ('public', 'agent_private', 'recovery')
  AND NOT t.tgisinternal
ORDER BY scope_ref, relation_ref, trigger_ref;

WITH allowlisted_roles(rolname) AS (
  VALUES ('postgres'), ('anon'), ('authenticated'), ('service_role'),
         ('agent_runtime'), ('authenticator'), ('supabase_storage_admin'),
         ('pgbouncer'), ('supabase_realtime_admin'), ('supabase_replication_admin')
)
SELECT
  'CATALOG_FUNCTION' AS record_type,
  CASE n.nspname WHEN 'public' THEN 'PUBLIC_SCHEMA'
       WHEN 'agent_private' THEN 'AGENT_PRIVATE_SCHEMA' ELSE 'RECOVERY_SCHEMA' END AS scope_ref,
  'OPAQUE_FUNCTION_' || pg_catalog.md5(
    n.nspname || pg_catalog.chr(31) || p.proname || pg_catalog.chr(31) ||
    pg_catalog.pg_get_function_identity_arguments(p.oid)
  ) AS function_ref,
  p.prokind AS function_kind,
  p.prosecdef AS security_definer,
  p.provolatile AS volatility,
  p.proparallel AS parallel_safety,
  pg_catalog.md5(pg_catalog.pg_get_function_identity_arguments(p.oid)) AS identity_arguments_md5,
  CASE
    WHEN p.prokind = 'a' THEN 'AGGREGATE_DEFINITION_NOT_EXTRACTED'
    ELSE pg_catalog.md5(pg_catalog.pg_get_functiondef(p.oid))
  END AS definition_md5,
  CASE
    WHEN owner.rolname IN (SELECT rolname FROM allowlisted_roles) THEN 'ALLOWLIST_ROLE'
    WHEN owner.rolname LIKE 'pg\_%' ESCAPE '\' THEN 'PREDEFINED_ROLE'
    ELSE 'UNEXPECTED_CUSTOM_OWNER'
  END AS owner_class,
  CASE WHEN p.proacl IS NULL THEN 'NO_DIRECT_PROACL' ELSE 'DIRECT_PROACL_PRESENT' END AS acl_state
FROM pg_catalog.pg_proc AS p
JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
LEFT JOIN pg_catalog.pg_roles AS owner ON owner.oid = p.proowner
WHERE n.nspname IN ('public', 'agent_private', 'recovery')
ORDER BY scope_ref, function_ref;

-- ACL rows emit names only for the explicit public allowlist. Predefined and
-- unexpected grantees stay classified but opaque.
WITH allowlisted_roles(rolname) AS (
  VALUES ('postgres'), ('anon'), ('authenticated'), ('service_role'),
         ('agent_runtime'), ('authenticator'), ('supabase_storage_admin'),
         ('pgbouncer'), ('supabase_realtime_admin'), ('supabase_replication_admin')
), grants AS (
  SELECT
    CASE n.nspname WHEN 'public' THEN 'PUBLIC_SCHEMA'
         WHEN 'agent_private' THEN 'AGENT_PRIVATE_SCHEMA' ELSE 'RECOVERY_SCHEMA' END AS scope_ref,
    acl.grantee, acl.privilege_type, acl.is_grantable
  FROM pg_catalog.pg_namespace AS n
  CROSS JOIN LATERAL pg_catalog.aclexplode(n.nspacl) AS acl
  WHERE n.nspname IN ('public', 'agent_private', 'recovery')
)
SELECT
  'SCHEMA_ACL_DIRECT_GRANTEE' AS record_type,
  grants.scope_ref,
  CASE WHEN grants.grantee = 0 THEN 'PUBLIC'
       WHEN role.rolname IN (SELECT rolname FROM allowlisted_roles) THEN 'ALLOWLIST_ROLE'
       WHEN role.rolname LIKE 'pg\_%' ESCAPE '\' THEN 'PREDEFINED_ROLE'
       ELSE 'UNEXPECTED_CUSTOM_GRANTEE' END AS grantee_class,
  CASE WHEN grants.grantee = 0 THEN 'PUBLIC'
       WHEN role.rolname IN (SELECT rolname FROM allowlisted_roles) THEN role.rolname
       WHEN role.rolname LIKE 'pg\_%' ESCAPE '\' THEN 'PREDEFINED_ROLE'
       ELSE 'UNEXPECTED_CUSTOM_GRANTEE' END AS grantee_ref,
  grants.privilege_type,
  grants.is_grantable
FROM grants
LEFT JOIN pg_catalog.pg_roles AS role ON role.oid = grants.grantee
ORDER BY scope_ref, grantee_class, grantee_ref, privilege_type;

WITH allowlisted_roles(rolname) AS (
  VALUES ('postgres'), ('anon'), ('authenticated'), ('service_role'),
         ('agent_runtime'), ('authenticator'), ('supabase_storage_admin'),
         ('pgbouncer'), ('supabase_realtime_admin'), ('supabase_replication_admin')
), grants AS (
  SELECT n.nspname, c.relname, c.relkind,
         acl.grantee, acl.privilege_type, acl.is_grantable
  FROM pg_catalog.pg_class AS c
  JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
  CROSS JOIN LATERAL pg_catalog.aclexplode(c.relacl) AS acl
  WHERE n.nspname IN ('public', 'agent_private', 'recovery')
    AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
)
SELECT
  'RELACL_DIRECT_GRANTEE' AS record_type,
  CASE grants.nspname WHEN 'public' THEN 'PUBLIC_SCHEMA'
       WHEN 'agent_private' THEN 'AGENT_PRIVATE_SCHEMA' ELSE 'RECOVERY_SCHEMA' END AS scope_ref,
  CASE WHEN grants.nspname = 'public' AND grants.relname = 'schema_migrations'
       THEN 'schema_migrations'
       ELSE 'OPAQUE_RELATION_' || pg_catalog.md5(grants.nspname || pg_catalog.chr(31) || grants.relname) END AS relation_ref,
  grants.relkind AS relation_kind,
  CASE WHEN grants.grantee = 0 THEN 'PUBLIC'
       WHEN role.rolname IN (SELECT rolname FROM allowlisted_roles) THEN 'ALLOWLIST_ROLE'
       WHEN role.rolname LIKE 'pg\_%' ESCAPE '\' THEN 'PREDEFINED_ROLE'
       ELSE 'UNEXPECTED_CUSTOM_GRANTEE' END AS grantee_class,
  CASE WHEN grants.grantee = 0 THEN 'PUBLIC'
       WHEN role.rolname IN (SELECT rolname FROM allowlisted_roles) THEN role.rolname
       WHEN role.rolname LIKE 'pg\_%' ESCAPE '\' THEN 'PREDEFINED_ROLE'
       ELSE 'UNEXPECTED_CUSTOM_GRANTEE' END AS grantee_ref,
  grants.privilege_type,
  grants.is_grantable
FROM grants
LEFT JOIN pg_catalog.pg_roles AS role ON role.oid = grants.grantee
ORDER BY scope_ref, relation_ref, grantee_class, grantee_ref, privilege_type;

WITH allowlisted_roles(rolname) AS (
  VALUES ('postgres'), ('anon'), ('authenticated'), ('service_role'),
         ('agent_runtime'), ('authenticator'), ('supabase_storage_admin'),
         ('pgbouncer'), ('supabase_realtime_admin'), ('supabase_replication_admin')
), grants AS (
  SELECT n.nspname, p.proname,
         pg_catalog.pg_get_function_identity_arguments(p.oid) AS identity_arguments,
         acl.grantee, acl.privilege_type, acl.is_grantable
  FROM pg_catalog.pg_proc AS p
  JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
  CROSS JOIN LATERAL pg_catalog.aclexplode(p.proacl) AS acl
  WHERE n.nspname IN ('public', 'agent_private', 'recovery')
)
SELECT
  'PROACL_DIRECT_GRANTEE' AS record_type,
  CASE grants.nspname WHEN 'public' THEN 'PUBLIC_SCHEMA'
       WHEN 'agent_private' THEN 'AGENT_PRIVATE_SCHEMA' ELSE 'RECOVERY_SCHEMA' END AS scope_ref,
  'OPAQUE_FUNCTION_' || pg_catalog.md5(
    grants.nspname || pg_catalog.chr(31) || grants.proname || pg_catalog.chr(31) || grants.identity_arguments
  ) AS function_ref,
  CASE WHEN grants.grantee = 0 THEN 'PUBLIC'
       WHEN role.rolname IN (SELECT rolname FROM allowlisted_roles) THEN 'ALLOWLIST_ROLE'
       WHEN role.rolname LIKE 'pg\_%' ESCAPE '\' THEN 'PREDEFINED_ROLE'
       ELSE 'UNEXPECTED_CUSTOM_GRANTEE' END AS grantee_class,
  CASE WHEN grants.grantee = 0 THEN 'PUBLIC'
       WHEN role.rolname IN (SELECT rolname FROM allowlisted_roles) THEN role.rolname
       WHEN role.rolname LIKE 'pg\_%' ESCAPE '\' THEN 'PREDEFINED_ROLE'
       ELSE 'UNEXPECTED_CUSTOM_GRANTEE' END AS grantee_ref,
  grants.privilege_type,
  grants.is_grantable
FROM grants
LEFT JOIN pg_catalog.pg_roles AS role ON role.oid = grants.grantee
ORDER BY scope_ref, function_ref, grantee_class, grantee_ref, privilege_type;

WITH target_scopes(scope_ref, nspoid) AS (
  SELECT CASE n.nspname WHEN 'public' THEN 'PUBLIC_SCHEMA'
              WHEN 'agent_private' THEN 'AGENT_PRIVATE_SCHEMA' ELSE 'RECOVERY_SCHEMA' END,
         n.oid
  FROM pg_catalog.pg_namespace AS n
  WHERE n.nspname IN ('public', 'agent_private', 'recovery')
  UNION ALL SELECT 'GLOBAL_NAMESPACE'::pg_catalog.text, 0::pg_catalog.oid
), allowlisted_roles(rolname) AS (
  VALUES ('postgres'), ('anon'), ('authenticated'), ('service_role'),
         ('agent_runtime'), ('authenticator'), ('supabase_storage_admin'),
         ('pgbouncer'), ('supabase_realtime_admin'), ('supabase_replication_admin')
), grants AS (
  SELECT scope.scope_ref, d.defaclobjtype,
         acl.grantee, acl.privilege_type, acl.is_grantable
  FROM target_scopes AS scope
  JOIN pg_catalog.pg_default_acl AS d ON d.defaclnamespace = scope.nspoid
  CROSS JOIN LATERAL pg_catalog.aclexplode(d.defaclacl) AS acl
)
SELECT
  'DEFAULT_ACL_DIRECT_GRANTEE' AS record_type,
  grants.scope_ref,
  grants.defaclobjtype AS object_type,
  CASE WHEN grants.grantee = 0 THEN 'PUBLIC'
       WHEN role.rolname IN (SELECT rolname FROM allowlisted_roles) THEN 'ALLOWLIST_ROLE'
       WHEN role.rolname LIKE 'pg\_%' ESCAPE '\' THEN 'PREDEFINED_ROLE'
       ELSE 'UNEXPECTED_CUSTOM_GRANTEE' END AS grantee_class,
  CASE WHEN grants.grantee = 0 THEN 'PUBLIC'
       WHEN role.rolname IN (SELECT rolname FROM allowlisted_roles) THEN role.rolname
       WHEN role.rolname LIKE 'pg\_%' ESCAPE '\' THEN 'PREDEFINED_ROLE'
       ELSE 'UNEXPECTED_CUSTOM_GRANTEE' END AS grantee_ref,
  grants.privilege_type,
  grants.is_grantable
FROM grants
LEFT JOIN pg_catalog.pg_roles AS role ON role.oid = grants.grantee
ORDER BY scope_ref, object_type, grantee_class, grantee_ref, privilege_type;

SELECT
  'PREFLIGHT_SCOPE' AS record_type,
  'PG_CATALOG_INFORMATION_SCHEMA_AND_TWO_LEDGERS_ONLY' AS source_assertion,
  'ZERO_DOMAIN_ROWS' AS domain_assertion,
  'ZERO_LEDGER_STATEMENT_TEXT' AS statement_assertion,
  'OPAQUE_DOMAIN_OBJECT_NAMES' AS object_name_assertion,
  'OPAQUE_UNEXPECTED_AND_PREDEFINED_ROLE_NAMES' AS role_name_assertion,
  'TARGET_DIGEST_UTF8_HEX' AS target_assertion,
  'ROW_SECURITY_OFF_FAIL_CLOSED' AS row_security_assertion,
  'PUBLIC_33_AND_NATIVE_6_OR_ABORT' AS ledger_shape_assertion;

ROLLBACK;
\qecho F2_DEV_FINAL_RECEIPT=ROLLBACK_COMPLETED_F2_DEV
