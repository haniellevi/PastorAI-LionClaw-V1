\set ON_ERROR_STOP on
-- F2 PROD v2 observa exclusivamente a forma dos dois ledgers canônicos.
-- Raniel executa este arquivo somente depois do APTO conjunto sobre estes bytes.
-- Não há material de conexão, escrita, leitura de domínio ou texto de statement.

BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL search_path = pg_catalog;
SET LOCAL statement_timeout = '5000ms';
SET LOCAL lock_timeout = '1000ms';
SET LOCAL idle_in_transaction_session_timeout = '15000ms';
SET LOCAL row_security = off;

\if :{?f2_prod_diag_binding}
\else
ROLLBACK;
\qecho F2_ABORT_BINDING_MISSING
\quit
\endif

SELECT (:'f2_prod_diag_binding' ~ '^[0-9a-f]{64}$') AS f2_binding_format_ok
\gset
\if :f2_binding_format_ok
\else
ROLLBACK;
\qecho F2_ABORT_BINDING_INVALID
\quit
\endif

-- Todas as verificações abaixo são silenciosas e precedem a primeira evidência.
SELECT (
  pg_catalog.current_setting('transaction_isolation') = 'repeatable read'
  AND pg_catalog.current_setting('transaction_read_only') = 'on'
  AND pg_catalog.current_setting('search_path') = 'pg_catalog'
  AND pg_catalog.current_setting('statement_timeout')::pg_catalog.interval = '5000ms'::pg_catalog.interval
  AND pg_catalog.current_setting('lock_timeout')::pg_catalog.interval = '1000ms'::pg_catalog.interval
  AND pg_catalog.current_setting('idle_in_transaction_session_timeout')::pg_catalog.interval = '15000ms'::pg_catalog.interval
  AND pg_catalog.current_setting('row_security') = 'off'
) AS f2_session_contract_ok
\gset
\if :f2_session_contract_ok
\else
ROLLBACK;
\qecho F2_ABORT_SESSION_CONTRACT
\quit
\endif

WITH target_ledgers(ledger_ref, schema_name, relation_name) AS (
  VALUES
    ('PUBLIC_LEDGER'::pg_catalog.text,
     'public'::pg_catalog.text,
     'schema_migrations'::pg_catalog.text),
    ('NATIVE_LEDGER'::pg_catalog.text,
     'supabase_migrations'::pg_catalog.text,
     'schema_migrations'::pg_catalog.text)
), observed AS (
  SELECT
    target.ledger_ref,
    c.relkind,
    COALESCE(columns_meta.column_count, 0) AS column_count,
    COALESCE(triggers_meta.trigger_count, 0) AS trigger_count,
    COALESCE(rules_meta.rule_count, 0) AS rule_count
  FROM target_ledgers AS target
  LEFT JOIN pg_catalog.pg_namespace AS n
    ON n.nspname = target.schema_name
  LEFT JOIN pg_catalog.pg_class AS c
    ON c.relnamespace = n.oid AND c.relname = target.relation_name
  LEFT JOIN LATERAL (
    SELECT pg_catalog.count(*) AS column_count
    FROM pg_catalog.pg_attribute AS a
    WHERE a.attrelid = c.oid
      AND a.attnum > 0
      AND NOT a.attisdropped
  ) AS columns_meta ON true
  LEFT JOIN LATERAL (
    SELECT pg_catalog.count(*) AS trigger_count
    FROM pg_catalog.pg_trigger AS t
    WHERE t.tgrelid = c.oid
      AND NOT t.tgisinternal
  ) AS triggers_meta ON true
  LEFT JOIN LATERAL (
    SELECT pg_catalog.count(*) AS rule_count
    FROM pg_catalog.pg_rewrite AS r
    WHERE r.ev_class = c.oid
      AND r.rulename <> '_RETURN'
  ) AS rules_meta ON true
)
SELECT
  pg_catalog.bool_and(
    column_count <= 16
    AND trigger_count <= 8
    AND rule_count <= 8
  ) AS f2_observation_ceilings_ok,
  pg_catalog.bool_or(
    ledger_ref = 'PUBLIC_LEDGER' AND relkind IN ('r', 'p')
  ) AS f2_public_countable,
  pg_catalog.bool_or(
    ledger_ref = 'NATIVE_LEDGER' AND relkind IN ('r', 'p')
  ) AS f2_native_countable
FROM observed
\gset
\if :f2_observation_ceilings_ok
\else
ROLLBACK;
\qecho F2_ABORT_OBSERVATION_CEILING
\quit
\endif

SELECT
  'TARGET_DIGEST' AS record_type,
  pg_catalog.encode(
    pg_catalog.sha256(
      pg_catalog.convert_to(
        :'f2_prod_diag_binding' || pg_catalog.chr(31) ||
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
  'PROD_DIAG' AS collection_class,
  pg_catalog.current_setting('server_version_num') AS server_version_num,
  'REPEATABLE_READ' AS isolation_state,
  'READ_ONLY_ON' AS read_only_state,
  'SEARCH_PATH_PG_CATALOG' AS search_path_state,
  'STATEMENT_TIMEOUT_5000MS' AS statement_timeout_state,
  'LOCK_TIMEOUT_1000MS' AS lock_timeout_state,
  'IDLE_TIMEOUT_15000MS' AS idle_timeout_state,
  'ROW_SECURITY_OFF' AS row_security_state,
  'BINDING_64HEX_ACCEPTED_NOT_PRINTED' AS binding_state;

SELECT
  'PREFLIGHT_SCOPE' AS record_type,
  'PG_CATALOG_AND_TWO_CANONICAL_LEDGERS_ONLY' AS source_scope,
  'NO_DOMAIN_ROWS_OR_LEDGER_STATEMENT_TEXT' AS privacy_scope,
  'COLUMN_CEILING_16' AS column_ceiling,
  'TRIGGER_CEILING_8' AS trigger_ceiling,
  'RULE_CEILING_8' AS rule_ceiling;

WITH target_ledgers(ledger_ref, schema_name, relation_name) AS (
  VALUES
    ('PUBLIC_LEDGER'::pg_catalog.text,
     'public'::pg_catalog.text,
     'schema_migrations'::pg_catalog.text),
    ('NATIVE_LEDGER'::pg_catalog.text,
     'supabase_migrations'::pg_catalog.text,
     'schema_migrations'::pg_catalog.text)
)
SELECT
  'LEDGER_RELATION' AS record_type,
  target.ledger_ref,
  CASE WHEN c.oid IS NULL THEN 'ABSENT' ELSE 'PRESENT' END AS existence_state,
  COALESCE(c.relkind::pg_catalog.text, 'ABSENT') AS relkind,
  COALESCE(c.relpersistence::pg_catalog.text, 'ABSENT') AS relpersistence,
  CASE WHEN c.oid IS NULL THEN 'NOT_APPLICABLE'
       WHEN c.relrowsecurity THEN 'RLS_ENABLED' ELSE 'RLS_DISABLED' END AS rls_state,
  CASE WHEN c.oid IS NULL THEN 'NOT_APPLICABLE'
       WHEN c.relforcerowsecurity THEN 'RLS_FORCED' ELSE 'RLS_NOT_FORCED' END AS forced_rls_state,
  COALESCE(triggers_meta.trigger_count, 0) AS user_trigger_count,
  COALESCE(rules_meta.rule_count, 0) AS user_rule_count
FROM target_ledgers AS target
LEFT JOIN pg_catalog.pg_namespace AS n
  ON n.nspname = target.schema_name
LEFT JOIN pg_catalog.pg_class AS c
  ON c.relnamespace = n.oid AND c.relname = target.relation_name
LEFT JOIN LATERAL (
  SELECT pg_catalog.count(*) AS trigger_count
  FROM pg_catalog.pg_trigger AS t
  WHERE t.tgrelid = c.oid
    AND NOT t.tgisinternal
) AS triggers_meta ON true
LEFT JOIN LATERAL (
  SELECT pg_catalog.count(*) AS rule_count
  FROM pg_catalog.pg_rewrite AS r
  WHERE r.ev_class = c.oid
    AND r.rulename <> '_RETURN'
) AS rules_meta ON true
ORDER BY target.ledger_ref;

\if :f2_public_countable
SELECT
  'LEDGER_CARDINALITY' AS record_type,
  'PUBLIC_LEDGER' AS ledger_ref,
  'TABLE_OR_PARTITIONED' AS cardinality_state,
  pg_catalog.count(*)::pg_catalog.int8 AS row_count
FROM public.schema_migrations;
\else
SELECT
  'LEDGER_CARDINALITY' AS record_type,
  'PUBLIC_LEDGER' AS ledger_ref,
  'NOT_TABLE_OR_PARTITIONED' AS cardinality_state,
  NULL::pg_catalog.int8 AS row_count;
\endif

\if :f2_native_countable
SELECT
  'LEDGER_CARDINALITY' AS record_type,
  'NATIVE_LEDGER' AS ledger_ref,
  'TABLE_OR_PARTITIONED' AS cardinality_state,
  pg_catalog.count(*)::pg_catalog.int8 AS row_count
FROM supabase_migrations.schema_migrations;
\else
SELECT
  'LEDGER_CARDINALITY' AS record_type,
  'NATIVE_LEDGER' AS ledger_ref,
  'NOT_TABLE_OR_PARTITIONED' AS cardinality_state,
  NULL::pg_catalog.int8 AS row_count;
\endif

WITH target_ledgers(ledger_ref, schema_name, relation_name) AS (
  VALUES
    ('PUBLIC_LEDGER'::pg_catalog.text,
     'public'::pg_catalog.text,
     'schema_migrations'::pg_catalog.text),
    ('NATIVE_LEDGER'::pg_catalog.text,
     'supabase_migrations'::pg_catalog.text,
     'schema_migrations'::pg_catalog.text)
)
SELECT
  'LEDGER_COLUMN' AS record_type,
  target.ledger_ref,
  a.attnum AS ordinal_position,
  CASE
    WHEN target.ledger_ref = 'PUBLIC_LEDGER'
         AND a.attname IN ('name', 'applied_at') THEN a.attname
    WHEN target.ledger_ref = 'NATIVE_LEDGER'
         AND a.attname IN (
           'version', 'statements', 'name', 'created_by', 'idempotency_key', 'rollback'
         ) THEN a.attname
    ELSE 'OPAQUE_COLUMN_' || pg_catalog.md5(
      target.schema_name || pg_catalog.chr(31) || target.relation_name ||
      pg_catalog.chr(31) || a.attname
    )
  END AS column_ref,
  CASE
    WHEN type_namespace.nspname = 'pg_catalog'
      THEN pg_catalog.format_type(a.atttypid, a.atttypmod)
    ELSE 'OPAQUE_TYPE_' || pg_catalog.md5(
      type_namespace.nspname || pg_catalog.chr(31) || type_catalog.typname
    )
  END AS column_type,
  a.attnotnull AS not_null,
  CASE
    WHEN d.oid IS NULL THEN 'NO_DEFAULT'
    ELSE pg_catalog.md5(pg_catalog.pg_get_expr(d.adbin, d.adrelid, true))
  END AS default_md5
FROM target_ledgers AS target
JOIN pg_catalog.pg_namespace AS n
  ON n.nspname = target.schema_name
JOIN pg_catalog.pg_class AS c
  ON c.relnamespace = n.oid AND c.relname = target.relation_name
JOIN pg_catalog.pg_attribute AS a
  ON a.attrelid = c.oid
JOIN pg_catalog.pg_type AS type_catalog
  ON type_catalog.oid = a.atttypid
JOIN pg_catalog.pg_namespace AS type_namespace
  ON type_namespace.oid = type_catalog.typnamespace
LEFT JOIN pg_catalog.pg_attrdef AS d
  ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE a.attnum > 0
  AND NOT a.attisdropped
ORDER BY target.ledger_ref, a.attnum;

WITH target_ledgers(ledger_ref, schema_name, relation_name) AS (
  VALUES
    ('PUBLIC_LEDGER'::pg_catalog.text,
     'public'::pg_catalog.text,
     'schema_migrations'::pg_catalog.text),
    ('NATIVE_LEDGER'::pg_catalog.text,
     'supabase_migrations'::pg_catalog.text,
     'schema_migrations'::pg_catalog.text)
)
SELECT
  'LEDGER_TRIGGER' AS record_type,
  target.ledger_ref,
  'OPAQUE_TRIGGER_' || pg_catalog.md5(
    target.schema_name || pg_catalog.chr(31) || target.relation_name ||
    pg_catalog.chr(31) || t.tgname
  ) AS trigger_ref,
  t.tgenabled AS enabled_state,
  pg_catalog.md5(pg_catalog.pg_get_triggerdef(t.oid, true)) AS definition_md5
FROM target_ledgers AS target
JOIN pg_catalog.pg_namespace AS n
  ON n.nspname = target.schema_name
JOIN pg_catalog.pg_class AS c
  ON c.relnamespace = n.oid AND c.relname = target.relation_name
JOIN pg_catalog.pg_trigger AS t
  ON t.tgrelid = c.oid
WHERE NOT t.tgisinternal
ORDER BY target.ledger_ref, trigger_ref;

WITH target_ledgers(ledger_ref, schema_name, relation_name) AS (
  VALUES
    ('PUBLIC_LEDGER'::pg_catalog.text,
     'public'::pg_catalog.text,
     'schema_migrations'::pg_catalog.text),
    ('NATIVE_LEDGER'::pg_catalog.text,
     'supabase_migrations'::pg_catalog.text,
     'schema_migrations'::pg_catalog.text)
)
SELECT
  'LEDGER_RULE' AS record_type,
  target.ledger_ref,
  'OPAQUE_RULE_' || pg_catalog.md5(
    target.schema_name || pg_catalog.chr(31) || target.relation_name ||
    pg_catalog.chr(31) || r.rulename
  ) AS rule_ref,
  pg_catalog.md5(pg_catalog.pg_get_ruledef(r.oid, true)) AS definition_md5
FROM target_ledgers AS target
JOIN pg_catalog.pg_namespace AS n
  ON n.nspname = target.schema_name
JOIN pg_catalog.pg_class AS c
  ON c.relnamespace = n.oid AND c.relname = target.relation_name
JOIN pg_catalog.pg_rewrite AS r
  ON r.ev_class = c.oid
WHERE r.rulename <> '_RETURN'
ORDER BY target.ledger_ref, rule_ref;

ROLLBACK;
\qecho ROLLBACK_COMPLETED_F2_PROD_DIAG
\quit
