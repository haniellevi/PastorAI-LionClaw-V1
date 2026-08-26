-- ============================================================================
-- PastorAI: hardening e retenção dos artefatos manuais de recuperação
--
-- Os dois objetos abaixo existem somente em alguns ambientes operacionais. A
-- migration é, portanto, um no-op quando o artefato não existe. Quando existe,
-- preserva linhas, nome, schema e acesso do proprietário, mas fecha a superfície
-- de cliente com ACL mínima e uma policy RLS restritiva explícita.
--
-- A tabela de rollback Clerk permanece no schema public para não invalidar um
-- roteiro de rollback externo ainda em retenção. O backup de credenciais já
-- reside no schema privado recovery e passa a ter RLS como defesa em profundidade.
-- Nenhum artefato é apagado automaticamente. As datas abaixo são gates de revisão,
-- não datas de exclusão.
-- ============================================================================

begin;

set transaction isolation level serializable;

do $migration$
declare
    artifact record;
    target_oid oid;
    target_column text;
    target_columns text[];
    target_role text;
    target_privilege text;
    column_privilege text;
    relation_kind "char";
    rls_enabled boolean;
    policy_count integer;
    exact_policy_count integer;
    row_count_before bigint;
    row_count_after bigint;
    artifacts_found integer := 0;
    service_role_before jsonb := '{}'::jsonb;
    closed_privileges text[] := array[
        'SELECT',
        'INSERT',
        'UPDATE',
        'DELETE',
        'TRUNCATE',
        'REFERENCES',
        'TRIGGER'
    ];
    closed_column_privileges constant text[] := array[
        'SELECT',
        'INSERT',
        'UPDATE',
        'REFERENCES'
    ];
begin
    if current_setting('server_version_num')::integer >= 170000 then
        closed_privileges := array_append(closed_privileges, 'MAINTAIN');
    end if;

    -- Preflight integral. Um catálogo inesperado aborta a transação antes de
    -- qualquer ACL, RLS, policy ou comentário ser alterado.
    for artifact in
        select *
        from (
            values
                (
                    'public'::text,
                    '_clerk_migration_rollback_20260823_032220'::text,
                    false,
                    date '2026-11-21',
                    'Rollback da migração Clerk de 2026-08-23'
                ),
                (
                    'recovery'::text,
                    'encrypted_credentials_backup_20260805'::text,
                    true,
                    date '2026-11-03',
                    'Backup de credenciais cifradas de 2026-08-05'
                )
        ) as configured(
            schema_name,
            table_name,
            close_service_role,
            review_after,
            purpose
        )
    loop
        select c.oid, c.relkind
          into target_oid, relation_kind
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = artifact.schema_name
           and c.relname = artifact.table_name;

        if target_oid is null then
            continue;
        end if;

        artifacts_found := artifacts_found + 1;

        if relation_kind not in ('r', 'p') then
            raise exception using
                errcode = 'P0001',
                message = format(
                    'recovery hardening fail-closed: %I.%I is not a table',
                    artifact.schema_name,
                    artifact.table_name
                );
        end if;

        foreach target_role in array array['anon', 'authenticated', 'service_role']
        loop
            if not exists (select 1 from pg_roles where rolname = target_role) then
                raise exception using
                    errcode = 'P0001',
                    message = format(
                        'recovery hardening fail-closed: required role %I is missing',
                        target_role
                    );
            end if;
        end loop;

        execute format(
            'lock table %I.%I in access exclusive mode',
            artifact.schema_name,
            artifact.table_name
        );

        select count(*),
               count(*) filter (
                   where p.polname = 'recovery_artifact_deny_all'
                     and p.polcmd = '*'
                     and p.polpermissive is false
                     and p.polroles = array[0::oid]
                     and pg_get_expr(p.polqual, p.polrelid) = 'false'
                     and pg_get_expr(p.polwithcheck, p.polrelid) = 'false'
               )
          into policy_count, exact_policy_count
          from pg_policy p
         where p.polrelid = target_oid;

        if policy_count <> 0
           and not (policy_count = 1 and exact_policy_count = 1)
        then
            raise exception using
                errcode = 'P0001',
                message = format(
                    'recovery hardening fail-closed: unexpected policy state on %I.%I',
                    artifact.schema_name,
                    artifact.table_name
                );
        end if;
    end loop;

    if artifacts_found = 0 then
        return;
    end if;

    -- Aplicação e pós-condições por artefato. A transação preserva atomicidade
    -- entre as duas tabelas quando ambas existem.
    for artifact in
        select *
        from (
            values
                (
                    'public'::text,
                    '_clerk_migration_rollback_20260823_032220'::text,
                    false,
                    date '2026-11-21',
                    'Rollback da migração Clerk de 2026-08-23'
                ),
                (
                    'recovery'::text,
                    'encrypted_credentials_backup_20260805'::text,
                    true,
                    date '2026-11-03',
                    'Backup de credenciais cifradas de 2026-08-05'
                )
        ) as configured(
            schema_name,
            table_name,
            close_service_role,
            review_after,
            purpose
        )
    loop
        select c.oid
          into target_oid
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = artifact.schema_name
           and c.relname = artifact.table_name
           and c.relkind in ('r', 'p');

        if target_oid is null then
            continue;
        end if;

        execute format(
            'select count(*) from %I.%I',
            artifact.schema_name,
            artifact.table_name
        ) into row_count_before;

        select coalesce(array_agg(a.attname order by a.attnum), array[]::text[])
          into target_columns
          from pg_attribute a
         where a.attrelid = target_oid
           and a.attnum > 0
           and not a.attisdropped;

        -- O rollback Clerk já permitia manutenção pelo service_role. Revogar
        -- PUBLIC não pode reduzir acidentalmente esse acesso operacional.
        if not artifact.close_service_role then
            foreach target_privilege in array closed_privileges
            loop
                service_role_before := service_role_before || jsonb_build_object(
                    format(
                        '%s.%s:table:%s',
                        artifact.schema_name,
                        artifact.table_name,
                        target_privilege
                    ),
                    has_table_privilege('service_role', target_oid, target_privilege)
                );
            end loop;

            foreach target_column in array target_columns
            loop
                foreach column_privilege in array closed_column_privileges
                loop
                    service_role_before := service_role_before || jsonb_build_object(
                        format(
                            '%s.%s:column:%s:%s',
                            artifact.schema_name,
                            artifact.table_name,
                            target_column,
                            column_privilege
                        ),
                        has_column_privilege(
                            'service_role',
                            target_oid,
                            target_column,
                            column_privilege
                        )
                    );
                end loop;
            end loop;
        end if;

        execute format(
            'alter table %I.%I enable row level security',
            artifact.schema_name,
            artifact.table_name
        );

        select count(*)
          into policy_count
          from pg_policy p
         where p.polrelid = target_oid;

        if policy_count = 0 then
            execute format(
                'create policy recovery_artifact_deny_all on %I.%I '
                'as restrictive for all to public '
                'using (false) with check (false)',
                artifact.schema_name,
                artifact.table_name
            );
        end if;

        if artifact.close_service_role then
            execute format(
                'revoke all privileges on table %I.%I '
                'from public, anon, authenticated, service_role',
                artifact.schema_name,
                artifact.table_name
            );
        else
            execute format(
                'revoke all privileges on table %I.%I '
                'from public, anon, authenticated',
                artifact.schema_name,
                artifact.table_name
            );
        end if;

        foreach target_column in array target_columns
        loop
            if artifact.close_service_role then
                execute format(
                    'revoke select (%I), insert (%I), update (%I), references (%I) '
                    'on table %I.%I from public, anon, authenticated, service_role',
                    target_column,
                    target_column,
                    target_column,
                    target_column,
                    artifact.schema_name,
                    artifact.table_name
                );
            else
                execute format(
                    'revoke select (%I), insert (%I), update (%I), references (%I) '
                    'on table %I.%I from public, anon, authenticated',
                    target_column,
                    target_column,
                    target_column,
                    target_column,
                    artifact.schema_name,
                    artifact.table_name
                );
            end if;
        end loop;

        if artifact.schema_name = 'recovery' then
            execute
                'revoke all privileges on schema recovery '
                'from public, anon, authenticated, service_role';
        end if;

        execute format(
            'comment on table %I.%I is %L',
            artifact.schema_name,
            artifact.table_name,
            format(
                '%s. %s recovery artifact. Review retention on or after %s; '
                'deletion requires verified backup and explicit human authorization.',
                artifact.purpose,
                case
                    when artifact.close_service_role then 'Owner-only'
                    else 'Owner and existing service_role'
                end,
                artifact.review_after
            )
        );

        select c.relrowsecurity
          into strict rls_enabled
          from pg_class c
         where c.oid = target_oid;

        select count(*),
               count(*) filter (
                   where p.polname = 'recovery_artifact_deny_all'
                     and p.polcmd = '*'
                     and p.polpermissive is false
                     and p.polroles = array[0::oid]
                     and pg_get_expr(p.polqual, p.polrelid) = 'false'
                     and pg_get_expr(p.polwithcheck, p.polrelid) = 'false'
               )
          into policy_count, exact_policy_count
          from pg_policy p
         where p.polrelid = target_oid;

        if not rls_enabled or policy_count <> 1 or exact_policy_count <> 1 then
            raise exception using
                errcode = 'P0001',
                message = format(
                    'recovery hardening fail-closed: final RLS state invalid on %I.%I',
                    artifact.schema_name,
                    artifact.table_name
                );
        end if;

        foreach target_role in array
            case
                when artifact.close_service_role
                    then array['anon', 'authenticated', 'service_role']
                else array['anon', 'authenticated']
            end
        loop
            foreach target_privilege in array closed_privileges
            loop
                if has_table_privilege(target_role, target_oid, target_privilege) then
                    raise exception using
                        errcode = 'P0001',
                        message = format(
                            'recovery hardening fail-closed: unexpected %s privilege '
                            'for role %I on %I.%I',
                            target_privilege,
                            target_role,
                            artifact.schema_name,
                            artifact.table_name
                        );
                end if;
            end loop;

            foreach target_column in array target_columns
            loop
                foreach column_privilege in array closed_column_privileges
                loop
                    if has_column_privilege(
                        target_role,
                        target_oid,
                        target_column,
                        column_privilege
                    ) then
                        raise exception using
                            errcode = 'P0001',
                            message = format(
                                'recovery hardening fail-closed: unexpected %s column '
                                'privilege for role %I on %I.%I.%I',
                                column_privilege,
                                target_role,
                                artifact.schema_name,
                                artifact.table_name,
                                target_column
                            );
                    end if;
                end loop;
            end loop;
        end loop;

        if artifact.schema_name = 'recovery' then
            foreach target_role in array array['anon', 'authenticated', 'service_role']
            loop
                if has_schema_privilege(target_role, 'recovery', 'USAGE')
                   or has_schema_privilege(target_role, 'recovery', 'CREATE')
                then
                    raise exception using
                        errcode = 'P0001',
                        message = format(
                            'recovery hardening fail-closed: role %I can access recovery schema',
                            target_role
                        );
                end if;
            end loop;
        else
            foreach target_privilege in array closed_privileges
            loop
                if (service_role_before ->> format(
                    '%s.%s:table:%s',
                    artifact.schema_name,
                    artifact.table_name,
                    target_privilege
                ))::boolean
                and not has_table_privilege(
                    'service_role',
                    target_oid,
                    target_privilege
                ) then
                    raise exception using
                        errcode = 'P0001',
                        message = format(
                            'recovery hardening fail-closed: service_role lost %s on %I.%I',
                            target_privilege,
                            artifact.schema_name,
                            artifact.table_name
                        );
                end if;
            end loop;

            foreach target_column in array target_columns
            loop
                foreach column_privilege in array closed_column_privileges
                loop
                    if (service_role_before ->> format(
                        '%s.%s:column:%s:%s',
                        artifact.schema_name,
                        artifact.table_name,
                        target_column,
                        column_privilege
                    ))::boolean
                    and not has_column_privilege(
                        'service_role',
                        target_oid,
                        target_column,
                        column_privilege
                    ) then
                        raise exception using
                            errcode = 'P0001',
                            message = format(
                                'recovery hardening fail-closed: service_role lost %s '
                                'on %I.%I.%I',
                                column_privilege,
                                artifact.schema_name,
                                artifact.table_name,
                                target_column
                            );
                    end if;
                end loop;
            end loop;
        end if;

        execute format(
            'select count(*) from %I.%I',
            artifact.schema_name,
            artifact.table_name
        ) into row_count_after;

        if row_count_after <> row_count_before then
            raise exception using
                errcode = 'P0001',
                message = format(
                    'recovery hardening fail-closed: row count changed on %I.%I',
                    artifact.schema_name,
                    artifact.table_name
                );
        end if;
    end loop;
end
$migration$;

commit;
