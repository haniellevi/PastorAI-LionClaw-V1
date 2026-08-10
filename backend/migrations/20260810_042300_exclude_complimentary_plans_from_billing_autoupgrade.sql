-- ============================================================================
-- PastorAI — Migration 20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade
--
-- Forward-only: redefine o trigger de porte sem editar migrations históricas.
-- Plano com preço zero é cortesia concedida somente pelo master e NUNCA pode
-- ser escolhido pelo auto-upgrade (nem no ramo local, nem no trilho Asaas).
--
-- A linha do plano alvo é travada antes de atualizar/enfileirar. O PATCH do
-- catálogo usa o mesmo row lock, impedindo a corrida em que o plano vira
-- cortesia entre a seleção e a criação da operação financeira.
--
-- Também reconcilia apenas operações automáticas PREPARED que apontem para
-- plano zero/ausente. Elas comprovadamente ainda não executaram PUT remoto:
-- fechamos a intenção antiga e, se existir próximo plano pago, criamos outra
-- intenção no mesmo commit. Estados processing/reconciling e operações manuais
-- permanecem intocados porque podem ter atravessado a rede.
--
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo. DEV/PROD são
-- gates separados; esta migration não deve ser aplicada durante a revisão.
-- ============================================================================

begin;

create or replace function public.fn_subscription_autoupgrade()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_igreja_id uuid;
  v_total int;
  v_sub public.subscriptions%rowtype;
  v_novo_plano text;
  v_novo_limite int;
  v_novo_preco numeric(10,2);
begin
  if tg_op = 'DELETE' then
    v_igreja_id := old.igreja_id;
  else
    v_igreja_id := new.igreja_id;
  end if;

  select * into v_sub
    from public.subscriptions
   where igreja_id = v_igreja_id;
  if not found then
    if tg_op = 'DELETE' then return old; else return new; end if;
  end if;

  select count(*) into v_total
    from public.pessoas
   where igreja_id = v_igreja_id
     and arquivada_em is null
     and coalesce(sem_interesse, false) is false
     and tipo in ('membro', 'discipulo', 'lider', 'pastor');

  update public.subscriptions
     set pessoas = v_total
   where igreja_id = v_igreja_id;

  if v_sub.limite is not null and v_total > v_sub.limite then
    -- Primeiro degrau ATIVO, PAGO e suficiente acima do atual. `FOR UPDATE`
    -- serializa esta escolha com a conversão pago <-> cortesia no painel master.
    select p.codigo, p.preco_mensal, p.limite_pessoas
      into v_novo_plano, v_novo_preco, v_novo_limite
      from public.planos p
     where p.ativo is true
       and p.codigo in ('ate_100', '101_200', 'acima_201')
       and p.preco_mensal > 0
       and (p.limite_pessoas is null or v_total <= p.limite_pessoas)
       and case p.codigo
             when 'ate_100' then 1
             when '101_200' then 2
             when 'acima_201' then 3
             else 999
           end > case v_sub.plano
             when 'ate_100' then 1
             when '101_200' then 2
             when 'acima_201' then 3
             else 999
           end
     order by case p.codigo
       when 'ate_100' then 1
       when '101_200' then 2
       when 'acima_201' then 3
       else 999
     end
     limit 1
     for update of p;

    if v_novo_plano is not null and v_novo_preco is not null then
      if v_sub.asaas_subscription_id is null then
        update public.subscriptions
           set plano = v_novo_plano,
               limite = v_novo_limite
         where igreja_id = v_igreja_id;
        update public.igrejas
           set plano = v_novo_plano
         where id = v_igreja_id;
      else
        insert into public.billing_plan_change_operations
          (subscription_id, asaas_subscription_id, from_plano, to_plano,
           to_preco, to_limite, to_descricao, origin, status, notify_status)
        values
          (v_sub.id, v_sub.asaas_subscription_id, v_sub.plano, v_novo_plano,
           v_novo_preco, v_novo_limite,
           'PastorAI — plano ' || v_novo_plano,
           'autoupgrade', 'prepared', 'pending')
        on conflict (subscription_id)
          where status in ('prepared','processing','reconciling')
          do nothing;
      end if;
    end if;
  end if;

  if tg_op = 'DELETE' then return old; else return new; end if;
end;
$$;

-- Corrige somente alvos automáticos ainda comprovadamente pré-rede.
do $reconcile_zero_price_prepared_upgrades$
declare
  v_op record;
  v_total integer;
  v_target_code text;
  v_target_price numeric(10,2);
  v_target_limit integer;
begin
  for v_op in
    select o.id,
           o.subscription_id,
           s.igreja_id,
           s.plano as current_plan,
           s.limite as current_limit,
           s.asaas_subscription_id as current_asaas_subscription_id
      from public.billing_plan_change_operations o
      join public.subscriptions s on s.id = o.subscription_id
      left join public.planos old_target on old_target.codigo = o.to_plano
     where o.origin = 'autoupgrade'
       and o.status = 'prepared'
       and (old_target.codigo is null or old_target.preco_mensal <= 0)
     order by o.created_at, o.id
     for update of o
  loop
    select count(*) into v_total
      from public.pessoas p
     where p.igreja_id = v_op.igreja_id
       and p.arquivada_em is null
       and coalesce(p.sem_interesse, false) is false
       and p.tipo in ('membro', 'discipulo', 'lider', 'pastor');

    v_target_code := null;
    v_target_price := null;
    v_target_limit := null;

    if v_op.current_limit is not null and v_total > v_op.current_limit then
      select p.codigo, p.preco_mensal, p.limite_pessoas
        into v_target_code, v_target_price, v_target_limit
        from public.planos p
       where p.ativo is true
         and p.codigo in ('ate_100', '101_200', 'acima_201')
         and p.preco_mensal > 0
         and (p.limite_pessoas is null or v_total <= p.limite_pessoas)
         and case p.codigo
               when 'ate_100' then 1
               when '101_200' then 2
               when 'acima_201' then 3
               else 999
             end > case v_op.current_plan
               when 'ate_100' then 1
               when '101_200' then 2
               when 'acima_201' then 3
               else 999
             end
       order by case p.codigo
         when 'ate_100' then 1
         when '101_200' then 2
         when 'acima_201' then 3
         else 999
       end
       limit 1
       for update of p;
    end if;

    update public.billing_plan_change_operations
       set status = 'failed',
           notify_status = 'skipped',
           error = 'Auto-upgrade de cortesia bloqueado antes do PUT.',
           attempt_started_at = null,
           updated_at = now()
     where id = v_op.id
       and status = 'prepared';

    if found
       and v_op.current_asaas_subscription_id is not null
       and v_target_code is not null then
      insert into public.billing_plan_change_operations
        (subscription_id, asaas_subscription_id, from_plano, to_plano,
         to_preco, to_limite, to_descricao, origin, status, notify_status)
      values
        (v_op.subscription_id, v_op.current_asaas_subscription_id,
         v_op.current_plan, v_target_code, v_target_price, v_target_limit,
         'PastorAI — plano ' || v_target_code,
         'autoupgrade', 'prepared', 'pending')
      on conflict (subscription_id)
        where status in ('prepared','processing','reconciling')
        do nothing;
    end if;
  end loop;
end;
$reconcile_zero_price_prepared_upgrades$;

-- Mantém o hardening de SECURITY DEFINER após a redefinição.
revoke all on function public.fn_subscription_autoupgrade()
  from public, anon, authenticated;
grant execute on function public.fn_subscription_autoupgrade() to service_role;

commit;

-- Verificação pós-migration (somente leitura): esperado = 0 linhas.
-- select o.id, o.subscription_id, o.to_plano
--   from public.billing_plan_change_operations o
--   left join public.planos p on p.codigo = o.to_plano
--  where o.origin = 'autoupgrade'
--    and o.status = 'prepared'
--    and (p.codigo is null or p.preco_mensal <= 0);
