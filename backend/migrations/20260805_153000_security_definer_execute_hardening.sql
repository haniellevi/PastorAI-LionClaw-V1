-- Endurece a superfície RPC de funções SECURITY DEFINER no schema public.
--
-- current_igreja_id() continua executável por authenticated porque as policies
-- RLS tenant_isolation dependem dela. Anon não possui fluxo válido que precise
-- resolver tenant.
--
-- As outras duas funções são invocadas exclusivamente por trigger/event trigger.
-- O papel da sessão não precisa de EXECUTE para cada disparo; postgres (owner) e
-- service_role permanecem explícitos para manutenção operacional.

revoke execute on function public.current_igreja_id() from public, anon;
grant execute on function public.current_igreja_id() to authenticated, service_role;

revoke execute on function public.fn_subscription_autoupgrade()
  from public, anon, authenticated;
grant execute on function public.fn_subscription_autoupgrade() to service_role;

-- rls_auto_enable() é uma proteção operacional presente nos projetos atuais,
-- mas não faz parte do histórico mínimo usado por bancos novos/staging. O guard
-- mantém a migration reaplicável nesses ambientes sem esconder outros erros.
do $do$
begin
  if to_regprocedure('public.rls_auto_enable()') is not null then
    execute 'revoke execute on function public.rls_auto_enable() '
            'from public, anon, authenticated';
    execute 'grant execute on function public.rls_auto_enable() to service_role';
  end if;
end
$do$;
