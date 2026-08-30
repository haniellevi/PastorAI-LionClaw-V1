begin transaction isolation level repeatable read read only;

select pg_catalog.set_config('search_path', 'pg_catalog', true);
select pg_catalog.set_config('statement_timeout', '15000', true);
select pg_catalog.set_config('lock_timeout', '1000', true);
select pg_catalog.set_config('idle_in_transaction_session_timeout', '15000', true);
select pg_catalog.set_config('row_security', 'off', true);

select pg_catalog.json_build_object(
    'identity_contract', 'MIGRATION_HISTORY_ENVIRONMENT_IDENTITY_PREFLIGHT_V1',
    'system_identifier', control.system_identifier::pg_catalog.text,
    'database_name', pg_catalog.current_database(),
    'server_version_num', pg_catalog.current_setting('server_version_num')::pg_catalog.int8,
    'current_user_matches_session_user', current_user = session_user,
    'tls', coalesce((
        select ssl from pg_catalog.pg_stat_ssl
         where pid = pg_catalog.pg_backend_pid()
    ), false),
    'isolation_level', pg_catalog.current_setting('transaction_isolation'),
    'read_only', pg_catalog.current_setting('transaction_read_only')
    ,'full_visibility', coalesce((
        select r.rolsuper or r.rolbypassrls
          from pg_catalog.pg_roles r
         where r.rolname = current_user
    ), false)
) as transient_private_identity
from pg_catalog.pg_control_system() as control;

rollback;
