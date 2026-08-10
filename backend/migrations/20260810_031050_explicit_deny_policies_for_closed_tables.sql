-- ============================================================================
-- PastorAI — M06: políticas explícitas para tabelas fechadas
--
-- As quatro tabelas abaixo já usam RLS sem policy, o que equivale a negar todo
-- acesso sujeito a RLS. Esta migration preserva esse comportamento e torna a
-- intenção explícita para o linter do Supabase. O papel proprietário e papéis
-- com BYPASSRLS continuam fora da avaliação de policies, como antes.
--
-- A policy só é criada quando a tabela existe e ainda não possui policy. Se o
-- estado mudar antes da aplicação, a migration não sobrepõe a nova decisão.
-- ============================================================================

begin;

do $migration$
declare
    target_table text;
    target_oid regclass;
begin
    foreach target_table in array array[
        'password_reset_tokens',
        'platform_admins',
        'platform_audit_log',
        'platform_orchestrator'
    ]
    loop
        target_oid := to_regclass(format('public.%I', target_table));

        if target_oid is not null
           and not exists (
               select 1
               from pg_policy
               where polrelid = target_oid
           )
        then
            execute format(
                'create policy service_role_bypass_only on public.%I '
                'for all to public using (false) with check (false)',
                target_table
            );
        end if;
    end loop;
end
$migration$;

commit;
