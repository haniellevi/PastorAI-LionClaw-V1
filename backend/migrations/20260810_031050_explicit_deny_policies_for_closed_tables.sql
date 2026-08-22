-- ============================================================================
-- PastorAI — M06: políticas explícitas para tabelas fechadas
--
-- O estado auditado em PROD tem RLS sem policy nas quatro tabelas abaixo, mas
-- o histórico mínimo não habilitava RLS em password_reset_tokens. A migration
-- fecha essa lacuna de reconstrução: habilita RLS explicitamente antes de
-- tornar a negação intencional para o linter do Supabase. Grants e RLS são
-- controles independentes: além da policy, a migration revoga explicitamente
-- todos os privilégios de tabela e coluna de PUBLIC/anon/authenticated. Isso
-- inclui SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES e TRIGGER; no
-- PostgreSQL 17, também inclui MAINTAIN. O service_role não recebe GRANT nem
-- REVOKE aqui e papéis com BYPASSRLS continuam fora da avaliação de policies,
-- como antes.
--
-- A migration é fail-closed também diante de drift de catálogo: exige todas as
-- tabelas, trava-as antes de inspecionar as policies e aceita somente dois
-- estados por tabela: nenhuma policy (primeira aplicação) ou exatamente a
-- policy restritiva abaixo (reaplicação). Qualquer outro estado aborta toda a
-- transação antes de alterar RLS ou criar policies.
-- ============================================================================

begin;

-- PostgreSQL 16 introduziu as opções individuais de membership. A migration
-- precisa de SET e ADMIN para auditar tanto caminhos atuais de SET ROLE quanto
-- memberships que podem habilitar SET ROLE posteriormente; em versão anterior,
-- falha fechada em vez de alegar uma proteção incompleta.
set transaction isolation level serializable;

do $migration$
declare
    target_table text;
    target_oid oid;
    target_columns text[];
    target_column text;
    policy_count integer;
    exact_policy_count integer;
    rls_enabled boolean;
    target_role text;
    target_privilege text;
    column_privilege text;
    reachable_role record;
    service_role_before jsonb := '{}'::jsonb;
    target_tables constant text[] := array[
        'password_reset_tokens',
        'platform_admins',
        'platform_audit_log',
        'platform_orchestrator'
    ];
    closed_roles constant text[] := array['anon', 'authenticated'];
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
    if current_setting('server_version_num')::integer < 160000 then
        raise exception using
            errcode = 'P0001',
            message = 'M06 fail-closed: PostgreSQL 16+ is required for SET ROLE membership inspection';
    end if;

    -- MAINTAIN foi adicionado aos privilégios de tabela no PostgreSQL 17.
    -- A migration continua compatível com o PostgreSQL 16 do CI, mas verifica
    -- esse privilégio adicional quando o catálogo do destino o suporta.
    if current_setting('server_version_num')::integer >= 170000 then
        closed_privileges := array_append(closed_privileges, 'MAINTAIN');
    end if;

    -- Valida primeiro a existência das quatro tabelas. Uma ausência é drift,
    -- não um estado idempotente, e deve impedir o registro de sucesso.
    foreach target_table in array target_tables
    loop
        select c.oid
          into target_oid
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public'
           and c.relname = target_table
           and c.relkind in ('r', 'p');

        if target_oid is null then
            raise exception using
                errcode = 'P0001',
                message = format(
                    'M06 fail-closed: required table public.%I is missing',
                    target_table
                );
        end if;
    end loop;

    foreach target_role in array closed_roles
    loop
        if not exists (select 1 from pg_roles where rolname = target_role) then
            raise exception using
                errcode = 'P0001',
                message = format(
                    'M06 fail-closed: required role %I is missing',
                    target_role
                );
        end if;
    end loop;

    if not exists (
        select 1
          from pg_roles
         where rolname = 'service_role'
           and rolbypassrls
    ) then
        raise exception using
            errcode = 'P0001',
            message = 'M06 fail-closed: required BYPASSRLS service_role is missing';
    end if;

    -- Serializa qualquer DDL concorrente sobre as tabelas e fecha a janela
    -- entre a inspeção do catálogo e a criação/validação das policies.
    foreach target_table in array target_tables
    loop
        execute format(
            'lock table public.%I in access exclusive mode',
            target_table
        );
    end loop;

    -- Preflight integral: nenhuma tabela é alterada até todas apresentarem um
    -- estado aceito. PUBLIC é representado pelo OID zero em pg_policy.polroles.
    foreach target_table in array target_tables
    loop
        select c.oid
          into strict target_oid
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public'
           and c.relname = target_table
           and c.relkind in ('r', 'p');

        select count(*),
               count(*) filter (
                   where p.polname = 'service_role_bypass_only'
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
                    'M06 fail-closed: unexpected policy state on public.%I',
                    target_table
                ),
                detail = format(
                    'expected no policy or exactly one restrictive '
                    'service_role_bypass_only policy; found %s policies '
                    '(%s exact)',
                    policy_count,
                    exact_policy_count
                );
        end if;
    end loop;

    -- Revogar PUBLIC não pode reduzir os privilégios efetivos que o backend já
    -- usava como service_role. Capturamos a matriz antes de mudar ACLs e, no
    -- final, abortamos se qualquer direito previamente efetivo desaparecer.
    foreach target_table in array target_tables
    loop
        select c.oid
          into strict target_oid
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public'
           and c.relname = target_table
           and c.relkind in ('r', 'p');

        select coalesce(array_agg(a.attname order by a.attnum), array[]::text[])
          into target_columns
          from pg_attribute a
         where a.attrelid = target_oid
           and a.attnum > 0
           and not a.attisdropped;

        foreach target_privilege in array closed_privileges
        loop
            service_role_before := service_role_before || jsonb_build_object(
                format('%s:table:%s', target_table, target_privilege),
                has_table_privilege('service_role', target_oid, target_privilege)
            );
        end loop;

        foreach target_column in array target_columns
        loop
            foreach column_privilege in array closed_column_privileges
            loop
                service_role_before := service_role_before || jsonb_build_object(
                    format(
                        '%s:column:%s:%s',
                        target_table,
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
    end loop;

    -- Somente depois do preflight de todas as tabelas o estado é aplicado.
    foreach target_table in array target_tables
    loop
        select c.oid
          into strict target_oid
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public'
           and c.relname = target_table
           and c.relkind in ('r', 'p');

        execute format(
            'alter table public.%I enable row level security',
            target_table
        );

        select count(*)
          into policy_count
          from pg_policy p
         where p.polrelid = target_oid;

        if policy_count = 0 then
            execute format(
                'create policy service_role_bypass_only on public.%I '
                'as restrictive for all to public '
                'using (false) with check (false)',
                target_table
            );
        end if;

        -- REVOKE ALL PRIVILEGES cobre todos os privilégios de tabela aplicáveis
        -- ao servidor (inclusive MAINTAIN no PostgreSQL 17), sem tocar no
        -- service_role. PostgreSQL também remove as ACLs de coluna
        -- correspondentes ao revogar a ACL da tabela; a revogação explícita por
        -- coluna abaixo é uma defesa redundante e deixa a pós-condição auditável.
        execute format(
            'revoke all privileges on table public.%I from public, anon, authenticated',
            target_table
        );

        select coalesce(array_agg(a.attname order by a.attnum), array[]::text[])
          into target_columns
          from pg_attribute a
         where a.attrelid = target_oid
           and a.attnum > 0
           and not a.attisdropped;

        foreach target_column in array target_columns
        loop
            execute format(
                'revoke select (%I), insert (%I), update (%I), references (%I) '
                'on table public.%I from public, anon, authenticated',
                target_column,
                target_column,
                target_column,
                target_column,
                target_table
            );
        end loop;
    end loop;

    -- Pós-condição explícita: uma falha aqui também reverte integralmente todos
    -- os ALTER TABLE/CREATE POLICY executados nesta transação.
    foreach target_table in array target_tables
    loop
        select c.oid, c.relrowsecurity
          into strict target_oid, rls_enabled
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public'
           and c.relname = target_table
           and c.relkind in ('r', 'p');

        select count(*),
               count(*) filter (
                   where p.polname = 'service_role_bypass_only'
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
                    'M06 fail-closed: final RLS state invalid on public.%I',
                    target_table
                );
        end if;

        select coalesce(array_agg(a.attname order by a.attnum), array[]::text[])
          into target_columns
          from pg_attribute a
         where a.attrelid = target_oid
           and a.attnum > 0
           and not a.attisdropped;

        foreach target_role in array closed_roles
        loop
            foreach target_privilege in array closed_privileges
            loop
                if has_table_privilege(target_role, target_oid, target_privilege) then
                    raise exception using
                        errcode = 'P0001',
                        message = format(
                            'M06 fail-closed: unexpected effective %s privilege '
                            'for role %I on public.%I',
                            target_privilege,
                            target_role,
                            target_table
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
                                'M06 fail-closed: unexpected effective %s column privilege '
                                'for role %I on public.%I.%I',
                                column_privilege,
                                target_role,
                                target_table,
                                target_column
                            );
                    end if;
                end loop;
            end loop;

            -- INHERIT, SET e ADMIN são atributos diferentes desde PostgreSQL
            -- 16. As verificações has_* acima capturam privilégios herdados.
            -- Este CTE percorre tanto SET ROLE atual quanto ADMIN OPTION: quem
            -- administra uma membership pode conceder a si mesmo SET depois.
            -- UNION deduplica papéis e termina mesmo diante de múltiplos
            -- caminhos ou de um catálogo corrompido com ciclo. Um papel
            -- alcançável não pode contornar a negação se for superuser,
            -- BYPASSRLS, CREATEROLE, proprietário ou ainda enxergar uma ACL.
            for reachable_role in
                with recursive admin_set_reachable(role_oid) as (
                    select r.oid
                      from pg_roles r
                     where r.rolname = target_role

                    union

                    select membership.roleid
                       from admin_set_reachable
                       join pg_auth_members membership
                        on membership.member = admin_set_reachable.role_oid
                     where membership.set_option or membership.admin_option
                )
                select distinct r.oid,
                                 r.rolname,
                                 r.rolsuper,
                                 r.rolbypassrls,
                                 r.rolcreaterole
                  from admin_set_reachable
                  join pg_roles r on r.oid = admin_set_reachable.role_oid
            loop
                if reachable_role.rolsuper or reachable_role.rolbypassrls then
                    raise exception using
                        errcode = 'P0001',
                        message = format(
                            'M06 fail-closed: ADMIN/SET-reachable role %I has BYPASSRLS or SUPERUSER',
                            reachable_role.rolname
                        );
                end if;

                if reachable_role.rolcreaterole then
                    raise exception using
                        errcode = 'P0001',
                        message = format(
                            'M06 fail-closed: ADMIN/SET-reachable role %I has CREATEROLE',
                            reachable_role.rolname
                        );
                end if;

                if exists (
                    select 1
                      from pg_class c
                     where c.oid = target_oid
                       and c.relowner = reachable_role.oid
                ) then
                    raise exception using
                        errcode = 'P0001',
                        message = format(
                            'M06 fail-closed: ADMIN/SET-reachable role %I owns public.%I',
                            reachable_role.rolname,
                            target_table
                        );
                end if;

                foreach target_privilege in array closed_privileges
                loop
                    if has_table_privilege(
                        reachable_role.oid,
                        target_oid,
                        target_privilege
                    ) then
                        raise exception using
                            errcode = 'P0001',
                            message = format(
                                'M06 fail-closed: ADMIN/SET-reachable role %I has effective %s '
                                'table privilege on public.%I',
                                reachable_role.rolname,
                                target_privilege,
                                target_table
                            );
                    end if;
                end loop;

                foreach target_column in array target_columns
                loop
                    foreach column_privilege in array closed_column_privileges
                    loop
                        if has_column_privilege(
                            reachable_role.oid,
                            target_oid,
                            target_column,
                            column_privilege
                        ) then
                            raise exception using
                                errcode = 'P0001',
                                message = format(
                                    'M06 fail-closed: ADMIN/SET-reachable role %I has effective %s '
                                    'column privilege on public.%I.%I',
                                    reachable_role.rolname,
                                    column_privilege,
                                    target_table,
                                    target_column
                                );
                        end if;
                    end loop;
                end loop;
            end loop;
        end loop;

        foreach target_privilege in array closed_privileges
        loop
            if (service_role_before ->> format(
                '%s:table:%s',
                target_table,
                target_privilege
            ))::boolean
            and not has_table_privilege('service_role', target_oid, target_privilege) then
                raise exception using
                    errcode = 'P0001',
                    message = format(
                        'M06 fail-closed: service_role lost effective %s table privilege '
                        'on public.%I',
                        target_privilege,
                        target_table
                    );
            end if;
        end loop;

        foreach target_column in array target_columns
        loop
            foreach column_privilege in array closed_column_privileges
            loop
                if (service_role_before ->> format(
                    '%s:column:%s:%s',
                    target_table,
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
                            'M06 fail-closed: service_role lost effective %s column privilege '
                            'on public.%I.%I',
                            column_privilege,
                            target_table,
                            target_column
                        );
                end if;
            end loop;
        end loop;
    end loop;
end
$migration$;

commit;
