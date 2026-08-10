-- ============================================================================
-- PastorAI — M06: políticas explícitas para tabelas fechadas
--
-- O estado auditado em PROD tem RLS sem policy nas quatro tabelas abaixo, mas
-- o histórico mínimo não habilitava RLS em password_reset_tokens. A migration
-- fecha essa lacuna de reconstrução: habilita RLS explicitamente antes de
-- tornar a negação intencional para o linter do Supabase. Grants e RLS são
-- controles independentes; esta migration não concede nem revoga privilégios.
-- O papel proprietário e papéis com BYPASSRLS continuam fora da avaliação de
-- policies, como antes.
--
-- A migration é fail-closed também diante de drift de catálogo: exige todas as
-- tabelas, trava-as antes de inspecionar as policies e aceita somente dois
-- estados por tabela: nenhuma policy (primeira aplicação) ou exatamente a
-- policy restritiva abaixo (reaplicação). Qualquer outro estado aborta toda a
-- transação antes de alterar RLS ou criar policies.
-- ============================================================================

begin;

do $migration$
declare
    target_table text;
    target_oid oid;
    policy_count integer;
    exact_policy_count integer;
    rls_enabled boolean;
    target_tables constant text[] := array[
        'password_reset_tokens',
        'platform_admins',
        'platform_audit_log',
        'platform_orchestrator'
    ];
begin
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
    end loop;
end
$migration$;

commit;
