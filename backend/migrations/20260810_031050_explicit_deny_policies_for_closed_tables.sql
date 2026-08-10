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

        if target_oid is not null then
            execute format(
                'alter table public.%I enable row level security',
                target_table
            );

            if not exists (
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
        end if;
    end loop;
end
$migration$;

commit;
