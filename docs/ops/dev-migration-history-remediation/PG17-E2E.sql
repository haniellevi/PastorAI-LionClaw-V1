\set ON_ERROR_STOP on

-- Local disposable fixture only. It contains no production names, tenant rows,
-- personal data, credentials, or externally reachable target. Each required
-- custom-grantee path has a distinct fixture and runner assertion.

CREATE SCHEMA supabase_migrations;
CREATE SCHEMA agent_private;
CREATE SCHEMA recovery;

CREATE TABLE public.schema_migrations (
  name pg_catalog.text NOT NULL,
  applied_at pg_catalog.timestamptz NOT NULL DEFAULT pg_catalog.now()
);

CREATE TABLE supabase_migrations.schema_migrations (
  version pg_catalog.text NOT NULL,
  statements pg_catalog.text[] NULL
);

INSERT INTO public.schema_migrations (name, applied_at)
SELECT
  'f1_synthetic_public_ledger_' || series_row.value::pg_catalog.text || '.sql',
  pg_catalog.timestamptz '2026-09-15 00:00:00+00'
    + series_row.value * pg_catalog.interval '1 second'
FROM pg_catalog.generate_series(1, 33) AS series_row(value);

INSERT INTO supabase_migrations.schema_migrations (version, statements)
VALUES
  (
    '00000000000001',
    ARRAY[
      '/* f1_initial_comment */ CREATE TABLE f1_statement_comment_not_output ();'
    ]::pg_catalog.text[]
  ),
  ('00000000000002', ARRAY['SELECT 1;']::pg_catalog.text[]),
  ('00000000000003', ARRAY['SELECT 2;']::pg_catalog.text[]),
  ('00000000000004', ARRAY['SELECT 3;']::pg_catalog.text[]),
  ('00000000000005', ARRAY['SELECT 4;']::pg_catalog.text[]),
  ('00000000000006', ARRAY['SELECT 5;']::pg_catalog.text[]);

CREATE ROLE f1_e2e_custom_grantee NOLOGIN;
CREATE ROLE f1_e2e_default_owner NOLOGIN;
CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticator NOLOGIN;
CREATE ROLE supabase_storage_admin NOLOGIN;
CREATE ROLE pgbouncer NOLOGIN;
CREATE ROLE supabase_realtime_admin NOLOGIN;
CREATE ROLE supabase_replication_admin NOLOGIN;

CREATE TABLE public.f1_public_acl_fixture (
  id pg_catalog.int4 PRIMARY KEY
);

CREATE TABLE agent_private.f1_agent_private_acl_fixture (
  id pg_catalog.int4 PRIMARY KEY
);

CREATE TABLE recovery.f1_masked_recovery_relation (
  id pg_catalog.int4 NOT NULL,
  payload pg_catalog.int4 NOT NULL,
  CONSTRAINT f1_masked_recovery_constraint CHECK (id > 0)
);

CREATE INDEX f1_masked_recovery_index
  ON recovery.f1_masked_recovery_relation (payload);

ALTER TABLE recovery.f1_masked_recovery_relation ENABLE ROW LEVEL SECURITY;

CREATE POLICY f1_masked_recovery_policy
  ON recovery.f1_masked_recovery_relation
  FOR SELECT
  TO PUBLIC
  USING (true);

CREATE FUNCTION public.f1_public_acl_function()
RETURNS pg_catalog.int4
LANGUAGE sql
AS 'SELECT 17';

CREATE FUNCTION agent_private.f1_agent_private_acl_function()
RETURNS pg_catalog.int4
LANGUAGE sql
AS 'SELECT 17';

CREATE FUNCTION recovery.f1_recovery_acl_function()
RETURNS pg_catalog.int4
LANGUAGE sql
AS 'SELECT 17';

CREATE FUNCTION recovery.f1_masked_recovery_trigger_function()
RETURNS trigger
LANGUAGE plpgsql
AS $fixture$
BEGIN
  RETURN NEW;
END;
$fixture$;

CREATE TRIGGER f1_masked_recovery_trigger
  BEFORE INSERT OR UPDATE ON recovery.f1_masked_recovery_relation
  FOR EACH ROW
  EXECUTE FUNCTION recovery.f1_masked_recovery_trigger_function();

GRANT USAGE ON SCHEMA public, agent_private, recovery TO f1_e2e_custom_grantee;
GRANT USAGE ON SCHEMA agent_private TO anon;
GRANT USAGE ON SCHEMA recovery TO PUBLIC;
GRANT SELECT ON TABLE
  public.f1_public_acl_fixture,
  agent_private.f1_agent_private_acl_fixture,
  recovery.f1_masked_recovery_relation
  TO f1_e2e_custom_grantee;
GRANT EXECUTE ON FUNCTION
  public.f1_public_acl_function(),
  agent_private.f1_agent_private_acl_function(),
  recovery.f1_recovery_acl_function()
  TO f1_e2e_custom_grantee;

GRANT USAGE ON SCHEMA public TO
  authenticator,
  supabase_storage_admin,
  pgbouncer,
  supabase_realtime_admin,
  supabase_replication_admin;

ALTER DEFAULT PRIVILEGES FOR ROLE f1_e2e_default_owner
  IN SCHEMA public
  GRANT SELECT ON TABLES TO f1_e2e_custom_grantee;

ALTER DEFAULT PRIVILEGES FOR ROLE f1_e2e_default_owner
  IN SCHEMA agent_private
  GRANT SELECT ON TABLES TO f1_e2e_custom_grantee;

ALTER DEFAULT PRIVILEGES FOR ROLE f1_e2e_default_owner
  IN SCHEMA recovery
  GRANT SELECT ON TABLES TO f1_e2e_custom_grantee;

ALTER DEFAULT PRIVILEGES FOR ROLE f1_e2e_default_owner
  GRANT SELECT ON TABLES TO f1_e2e_custom_grantee;

\i /f1/DEV-READONLY-F1.sql
