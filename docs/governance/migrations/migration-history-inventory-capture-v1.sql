begin transaction isolation level repeatable read read only;

select pg_catalog.set_config('search_path', 'pg_catalog', true);
select pg_catalog.set_config('statement_timeout', '15000', true);
select pg_catalog.set_config('lock_timeout', '2000', true);
select pg_catalog.set_config('idle_in_transaction_session_timeout', '15000', true);

with relation_state as (
    select
        (
            select pg_catalog.count(*)
            from pg_catalog.pg_class as c
            join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
            where n.nspname = 'public'
              and c.relname = 'schema_migrations'
        ) as public_relation_count,
        (
            select pg_catalog.max(c.relkind)
            from pg_catalog.pg_class as c
            join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
            where n.nspname = 'public'
              and c.relname = 'schema_migrations'
        ) as public_relkind,
        (
            select
                pg_catalog.count(*) = 2
                and pg_catalog.count(*) filter (
                    where
                        (a.attname = 'name'
                         and a.atttypid = 'pg_catalog.text'::pg_catalog.regtype)
                        or
                        (a.attname = 'applied_at'
                         and a.atttypid = 'pg_catalog.timestamptz'::pg_catalog.regtype)
                ) = 2
            from pg_catalog.pg_attribute as a
            join pg_catalog.pg_class as c on c.oid = a.attrelid
            join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
            where n.nspname = 'public'
              and c.relname = 'schema_migrations'
              and a.attnum > 0
              and not a.attisdropped
        ) as public_columns_ok,
        case
            when pg_catalog.to_regclass('public.schema_migrations') is null then null
            else pg_catalog.row_security_active(
                pg_catalog.to_regclass('public.schema_migrations')
            )
        end as public_row_security_active,
        (
            select pg_catalog.count(*)
            from pg_catalog.pg_rewrite as r
            where r.ev_class = pg_catalog.to_regclass('public.schema_migrations')
              and r.rulename <> '_RETURN'
        ) as public_rule_count,
        (
            select pg_catalog.count(*)
            from pg_catalog.pg_trigger as t
            where t.tgrelid = pg_catalog.to_regclass('public.schema_migrations')
              and not t.tgisinternal
        ) as public_trigger_count,
        (
            select pg_catalog.count(*)
            from pg_catalog.pg_class as c
            join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
            where n.nspname = 'supabase_migrations'
              and c.relname = 'schema_migrations'
        ) as native_relation_count,
        (
            select pg_catalog.max(c.relkind)
            from pg_catalog.pg_class as c
            join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
            where n.nspname = 'supabase_migrations'
              and c.relname = 'schema_migrations'
        ) as native_relkind,
        pg_catalog.to_regclass('supabase_migrations.schema_migrations') is not null
          and exists (
              select 1
              from pg_catalog.pg_attribute as a
              where a.attrelid = pg_catalog.to_regclass(
                    'supabase_migrations.schema_migrations'
                )
                and a.attname = 'version'
                and a.atttypid = 'pg_catalog.text'::pg_catalog.regtype
                and a.attnum > 0
                and not a.attisdropped
          ) as native_has_version,
        pg_catalog.to_regclass('supabase_migrations.schema_migrations') is not null
          and exists (
              select 1
              from pg_catalog.pg_attribute as a
              where a.attrelid = pg_catalog.to_regclass(
                    'supabase_migrations.schema_migrations'
                )
                and a.attname = 'name'
                and a.atttypid = 'pg_catalog.text'::pg_catalog.regtype
                and a.attnum > 0
                and not a.attisdropped
          ) as native_has_name,
        (
            select pg_catalog.count(*) = 1
            from pg_catalog.pg_attribute as a
            where a.attrelid = pg_catalog.to_regclass(
                    'supabase_migrations.schema_migrations'
                )
              and a.attname = 'name'
              and a.attnum > 0
              and not a.attisdropped
        ) as native_name_column_present,
        case
            when pg_catalog.to_regclass(
                'supabase_migrations.schema_migrations'
            ) is null then null
            else pg_catalog.row_security_active(
                pg_catalog.to_regclass('supabase_migrations.schema_migrations')
            )
        end as native_row_security_active,
        (
            select pg_catalog.count(*)
            from pg_catalog.pg_rewrite as r
            where r.ev_class = pg_catalog.to_regclass(
                'supabase_migrations.schema_migrations'
            )
              and r.rulename <> '_RETURN'
        ) as native_rule_count,
        (
            select pg_catalog.count(*)
            from pg_catalog.pg_trigger as t
            where t.tgrelid = pg_catalog.to_regclass(
                'supabase_migrations.schema_migrations'
            )
              and not t.tgisinternal
        ) as native_trigger_count
),
captured as (
    select
        'MIGRATION_HISTORY_INVENTORY_CAPTURE_V1'::pg_catalog.text
            as capture_contract,
        pg_catalog.current_setting('server_version_num')::pg_catalog.int8
            as server_version_num,
        current_user = session_user
            as current_user_matches_session_user,
        control.system_identifier::pg_catalog.text as system_identifier,
        pg_catalog.current_database()::pg_catalog.text as database_name,
        pg_catalog.to_char(
            pg_catalog.transaction_timestamp() at time zone 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ) as captured_at_utc,
        pg_catalog.pg_current_snapshot()::pg_catalog.text as snapshot_token,
        pg_catalog.current_setting('transaction_isolation') as isolation_level,
        pg_catalog.current_setting('transaction_read_only') as read_only,
        relation_state.*,
        case
            when relation_state.public_relation_count = 1
             and relation_state.public_relkind = 'r'
             and relation_state.public_columns_ok
             and not relation_state.public_row_security_active
             and relation_state.public_rule_count = 0
             and relation_state.public_trigger_count = 0
            then pg_catalog.query_to_xml(
                'select (pg_catalog.row_number() over (order by applied_at asc, name asc) - 1)::pg_catalog.int8 as position, name::pg_catalog.text as name from public.schema_migrations order by applied_at asc, name asc limit 2049',
                true,
                false,
                ''
            )
        end as public_doc,
        case
            when relation_state.native_relation_count = 1
             and relation_state.native_relkind = 'r'
             and relation_state.native_has_version
             and not relation_state.native_row_security_active
             and relation_state.native_rule_count = 0
             and relation_state.native_trigger_count = 0
             and relation_state.native_has_name
            then pg_catalog.query_to_xml(
                'select (pg_catalog.row_number() over (order by version asc) - 1)::pg_catalog.int8 as position, version::pg_catalog.text as version, null::pg_catalog.text as name from supabase_migrations.schema_migrations order by version asc limit 2049',
                true,
                false,
                ''
            )
            when relation_state.native_relation_count = 1
             and relation_state.native_relkind = 'r'
             and relation_state.native_has_version
             and not relation_state.native_name_column_present
             and not relation_state.native_row_security_active
             and relation_state.native_rule_count = 0
             and relation_state.native_trigger_count = 0
            then pg_catalog.query_to_xml(
                'select (pg_catalog.row_number() over (order by version asc) - 1)::pg_catalog.int8 as position, version::pg_catalog.text as version, null::pg_catalog.text as name from supabase_migrations.schema_migrations order by version asc limit 2049',
                true,
                false,
                ''
            )
        end as native_doc
    from relation_state
    cross join pg_catalog.pg_control_system() as control
),
public_rows as (
    select coalesce(
        pg_catalog.json_agg(
            pg_catalog.json_build_object(
                'position', x.position,
                'name', x.name
            )
            order by x.position
        ),
        '[]'::pg_catalog.json
    ) as rows
    from captured as c
    cross join lateral xmltable(
        '/table/row'
        passing c.public_doc
        columns
            position pg_catalog.int8 path 'position',
            name pg_catalog.text path 'name'
    ) as x
),
native_rows as (
    select coalesce(
        pg_catalog.json_agg(
            pg_catalog.json_build_object(
                'position', x.position,
                'version', x.version,
                'name', nullif(x.name, '')
            )
            order by x.position
        ),
        '[]'::pg_catalog.json
    ) as rows
    from captured as c
    cross join lateral xmltable(
        '/table/row'
        passing c.native_doc
        columns
            position pg_catalog.int8 path 'position',
            version pg_catalog.text path 'version',
            name pg_catalog.text path 'name'
    ) as x
)
select pg_catalog.json_build_object(
    'capture_contract', c.capture_contract,
    'server_version_num', c.server_version_num,
    'current_user_matches_session_user', c.current_user_matches_session_user,
    'system_identifier', c.system_identifier,
    'database_name', c.database_name,
    'captured_at_utc', c.captured_at_utc,
    'snapshot_token', c.snapshot_token,
    'isolation_level', c.isolation_level,
    'read_only', c.read_only,
    'public_relation_count', c.public_relation_count,
    'public_relkind', c.public_relkind,
    'public_columns_ok', c.public_columns_ok,
    'public_row_security_active', c.public_row_security_active,
    'public_rule_count', c.public_rule_count,
    'public_trigger_count', c.public_trigger_count,
    'public_rows', p.rows,
    'native_relation_count', c.native_relation_count,
    'native_relkind', c.native_relkind,
    'native_has_version', c.native_has_version,
    'native_has_name', c.native_has_name,
    'native_name_column_present', c.native_name_column_present,
    'native_row_security_active', c.native_row_security_active,
    'native_rule_count', c.native_rule_count,
    'native_trigger_count', c.native_trigger_count,
    'native_rows', n.rows
) as sanitized_capture
from captured as c
cross join public_rows as p
cross join native_rows as n;

rollback;
