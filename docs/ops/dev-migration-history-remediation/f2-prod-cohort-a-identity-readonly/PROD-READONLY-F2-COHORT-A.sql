\set ON_ERROR_STOP on
-- Proposta F2 PROD coorte A. Não executar sem gate nominal e APTO conjunto.
-- Fonte física: pg_catalog e supabase_migrations.schema_migrations.
-- Saída: somente estados, contagens e compromissos opacos.

BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL search_path = pg_catalog;
SET LOCAL statement_timeout = '5000ms';
SET LOCAL lock_timeout = '1000ms';
SET LOCAL idle_in_transaction_session_timeout = '15000ms';
SET LOCAL row_security = off;

\if :{?f2_cohort_a_binding}
\else
ROLLBACK;
\qecho F2_ABORT_COHORT_A_BINDING_MISSING
\quit
\endif

SELECT (:'f2_cohort_a_binding' ~ '^[0-9a-f]{64}$') AS f2_binding_ok
\gset
\if :f2_binding_ok
\else
ROLLBACK;
\qecho F2_ABORT_COHORT_A_BINDING_INVALID
\quit
\endif

SELECT (
  pg_catalog.current_setting('transaction_isolation') = 'repeatable read'
  AND pg_catalog.current_setting('transaction_read_only') = 'on'
  AND pg_catalog.current_setting('search_path') = 'pg_catalog'
  AND pg_catalog.current_setting('statement_timeout')::pg_catalog.interval = '5000ms'::pg_catalog.interval
  AND pg_catalog.current_setting('lock_timeout')::pg_catalog.interval = '1000ms'::pg_catalog.interval
  AND pg_catalog.current_setting('idle_in_transaction_session_timeout')::pg_catalog.interval = '15000ms'::pg_catalog.interval
  AND pg_catalog.current_setting('row_security') = 'off'
) AS f2_session_ok
\gset
\if :f2_session_ok
\else
ROLLBACK;
\qecho F2_ABORT_COHORT_A_SESSION_CONTRACT
\quit
\endif

WITH relation_shape AS (
  SELECT
    c.oid,
    c.relkind,
    pg_catalog.count(DISTINCT a.attnum) FILTER (
      WHERE a.attnum > 0 AND NOT a.attisdropped
    ) AS column_count,
    pg_catalog.count(DISTINCT t.oid) FILTER (
      WHERE NOT t.tgisinternal
    ) AS trigger_count,
    pg_catalog.count(DISTINCT r.oid) FILTER (
      WHERE r.rulename <> '_RETURN'
    ) AS rule_count
  FROM pg_catalog.pg_namespace AS n
  JOIN pg_catalog.pg_class AS c
    ON c.relnamespace = n.oid
  LEFT JOIN pg_catalog.pg_attribute AS a
    ON a.attrelid = c.oid
  LEFT JOIN pg_catalog.pg_trigger AS t
    ON t.tgrelid = c.oid
  LEFT JOIN pg_catalog.pg_rewrite AS r
    ON r.ev_class = c.oid
  WHERE n.nspname = 'supabase_migrations'
    AND c.relname = 'schema_migrations'
  GROUP BY c.oid, c.relkind
), columns_ok AS (
  SELECT
    pg_catalog.count(*) = 6
    AND pg_catalog.bool_and(
      (a.attname = 'version' AND a.attnotnull AND pg_catalog.format_type(a.atttypid, a.atttypmod) = 'text')
      OR (a.attname = 'statements' AND NOT a.attnotnull AND pg_catalog.format_type(a.atttypid, a.atttypmod) = 'text[]')
      OR (a.attname = 'name' AND NOT a.attnotnull AND pg_catalog.format_type(a.atttypid, a.atttypmod) = 'text')
      OR (a.attname = 'created_by' AND NOT a.attnotnull AND pg_catalog.format_type(a.atttypid, a.atttypmod) = 'text')
      OR (a.attname = 'idempotency_key' AND NOT a.attnotnull AND pg_catalog.format_type(a.atttypid, a.atttypmod) = 'text')
      OR (a.attname = 'rollback' AND NOT a.attnotnull AND pg_catalog.format_type(a.atttypid, a.atttypmod) = 'text[]')
    ) AS shape_ok
  FROM pg_catalog.pg_namespace AS n
  JOIN pg_catalog.pg_class AS c
    ON c.relnamespace = n.oid
  JOIN pg_catalog.pg_attribute AS a
    ON a.attrelid = c.oid
  WHERE n.nspname = 'supabase_migrations'
    AND c.relname = 'schema_migrations'
    AND a.attnum > 0
    AND NOT a.attisdropped
)
SELECT (
  EXISTS (
    SELECT 1
    FROM relation_shape
    WHERE relkind IN ('r', 'p')
      AND column_count <= 16
      AND trigger_count = 0
      AND rule_count = 0
  )
  AND COALESCE((SELECT shape_ok FROM columns_ok), false)
) AS f2_ledger_shape_ok
\gset
\if :f2_ledger_shape_ok
\else
ROLLBACK;
\qecho F2_ABORT_COHORT_A_LEDGER_SHAPE
\quit
\endif

SELECT
  pg_catalog.count(*) = 32
  AND pg_catalog.count(*) <= 256
  AND pg_catalog.count(DISTINCT version) = 32
  AS f2_ledger_cardinality_ok
FROM supabase_migrations.schema_migrations
\gset
\if :f2_ledger_cardinality_ok
\else
ROLLBACK;
\qecho F2_ABORT_COHORT_A_LEDGER_CARDINALITY
\quit
\endif

WITH ordered AS (
  SELECT
    pg_catalog.row_number() OVER (ORDER BY version ASC)::pg_catalog.int4 AS scope_ordinal,
    version,
    statements,
    name,
    idempotency_key,
    rollback
  FROM supabase_migrations.schema_migrations
), cohort AS (
  SELECT *
  FROM ordered
  WHERE scope_ordinal = ANY (
    ARRAY[1,2,3,4,5,6,7,8,9,10,11,12,13,14,22,23,24,25,26,29,31,32]::pg_catalog.int4[]
  )
)
SELECT (
  pg_catalog.count(*) = 22
  AND pg_catalog.bool_and(statements IS NOT NULL AND pg_catalog.cardinality(statements) > 0)
) AS f2_cohort_material_ok
FROM cohort
\gset
\if :f2_cohort_material_ok
\else
ROLLBACK;
\qecho F2_ABORT_COHORT_A_IDENTITY_MATERIAL
\quit
\endif

WITH ordered AS (
  SELECT
    pg_catalog.row_number() OVER (ORDER BY version ASC)::pg_catalog.int4 AS scope_ordinal,
    statements
  FROM supabase_migrations.schema_migrations
), cohort AS (
  SELECT *
  FROM ordered
  WHERE scope_ordinal = ANY (
    ARRAY[1,2,3,4,5,6,7,8,9,10,11,12,13,14,22,23,24,25,26,29,31,32]::pg_catalog.int4[]
  )
), commitments AS (
  SELECT pg_catalog.encode(
    pg_catalog.sha256(
      pg_catalog.convert_to(
        :'f2_cohort_a_binding' || pg_catalog.chr(31) ||
        'F2-PROD-COHORT-A-FORWARD-v1' || pg_catalog.chr(31) ||
        pg_catalog.cardinality(statements)::pg_catalog.text || pg_catalog.chr(31) ||
        pg_catalog.array_to_json(statements)::pg_catalog.text,
        'UTF8'
      )
    ),
    'hex'
  ) AS forward_identity_ref
  FROM cohort
)
SELECT (
  pg_catalog.count(*) = 22
  AND pg_catalog.count(DISTINCT forward_identity_ref) = 22
) AS f2_commitments_unique
FROM commitments
\gset
\if :f2_commitments_unique
\else
ROLLBACK;
\qecho F2_ABORT_COHORT_A_IDENTITY_COLLISION
\quit
\endif

SELECT
  'TARGET_DIGEST' AS record_type,
  pg_catalog.encode(
    pg_catalog.sha256(
      pg_catalog.convert_to(
        :'f2_cohort_a_binding' || pg_catalog.chr(31) ||
        pg_catalog.current_database() || pg_catalog.chr(31) ||
        COALESCE(pg_catalog.inet_server_port()::pg_catalog.text, 'UNIX_SOCKET') ||
        pg_catalog.chr(31) ||
        pg_catalog.current_setting('server_version_num'),
        'UTF8'
      )
    ),
    'hex'
  ) AS target_digest;

SELECT
  'F2_SESSION' AS record_type,
  'PROD_COHORT_A_IDENTITY' AS collection_class,
  pg_catalog.current_setting('server_version_num') AS server_version_num,
  'REPEATABLE_READ' AS isolation_state,
  'READ_ONLY_ON' AS read_only_state,
  'ROW_SECURITY_OFF' AS row_security_state,
  'BINDING_ACCEPTED_NOT_PRINTED' AS binding_state;

SELECT
  'COHORT_SCOPE' AS record_type,
  'VERSION_ASC_MEMBERSHIP_ONLY' AS ordering_role,
  '1-14,22-26,29,31-32' AS positions,
  22::pg_catalog.int4 AS expected_count,
  'POSITION_VERSION_NAME_PROHIBITED_FOR_IDENTITY' AS identity_rule;

WITH ordered AS (
  SELECT
    pg_catalog.row_number() OVER (ORDER BY version ASC)::pg_catalog.int4 AS scope_ordinal,
    version,
    statements,
    name,
    idempotency_key,
    rollback
  FROM supabase_migrations.schema_migrations
), cohort AS (
  SELECT *
  FROM ordered
  WHERE scope_ordinal = ANY (
    ARRAY[1,2,3,4,5,6,7,8,9,10,11,12,13,14,22,23,24,25,26,29,31,32]::pg_catalog.int4[]
  )
)
SELECT
  'COHORT_A_ENTRY' AS record_type,
  scope_ordinal,
  pg_catalog.md5(version) AS version_membership_md5,
  pg_catalog.md5(COALESCE(name, '')) AS name_membership_md5,
  pg_catalog.cardinality(statements) AS statements_count,
  COALESCE(pg_catalog.cardinality(rollback), 0) AS rollback_count,
  CASE WHEN idempotency_key IS NULL THEN 'ABSENT' ELSE 'PRESENT' END AS idempotency_state,
  pg_catalog.encode(
    pg_catalog.sha256(
      pg_catalog.convert_to(
        :'f2_cohort_a_binding' || pg_catalog.chr(31) ||
        'F2-PROD-COHORT-A-FORWARD-v1' || pg_catalog.chr(31) ||
        pg_catalog.cardinality(statements)::pg_catalog.text || pg_catalog.chr(31) ||
        pg_catalog.array_to_json(statements)::pg_catalog.text,
        'UTF8'
      )
    ),
    'hex'
  ) AS forward_identity_ref,
  CASE
    WHEN rollback IS NULL THEN 'ABSENT'
    ELSE pg_catalog.encode(
      pg_catalog.sha256(
        pg_catalog.convert_to(
          :'f2_cohort_a_binding' || pg_catalog.chr(31) ||
          'F2-PROD-COHORT-A-ROLLBACK-v1' || pg_catalog.chr(31) ||
          pg_catalog.cardinality(rollback)::pg_catalog.text || pg_catalog.chr(31) ||
          pg_catalog.array_to_json(rollback)::pg_catalog.text,
          'UTF8'
        )
      ),
      'hex'
    )
  END AS rollback_identity_ref,
  CASE
    WHEN idempotency_key IS NULL THEN 'ABSENT'
    ELSE pg_catalog.encode(
      pg_catalog.sha256(
        pg_catalog.convert_to(
          :'f2_cohort_a_binding' || pg_catalog.chr(31) ||
          'F2-PROD-COHORT-A-IDEMPOTENCY-v1' || pg_catalog.chr(31) ||
          idempotency_key,
          'UTF8'
        )
      ),
      'hex'
    )
  END AS idempotency_identity_ref
FROM cohort
ORDER BY scope_ordinal;

SELECT
  'COHORT_A_SUMMARY' AS record_type,
  22::pg_catalog.int4 AS emitted_entries,
  'PRIMARY_COMMITMENTS_UNIQUE' AS uniqueness_state,
  'NO_APPLICATION_CLAIM' AS interpretation;

ROLLBACK;
\qecho ROLLBACK_COMPLETED_F2_PROD_COHORT_A_IDENTITY
\quit
