-- ============================================================================
-- PastorAI — Migration 20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade
--
-- Forward-only: redefine o trigger de porte sem editar migrations históricas.
-- Plano com preço zero é cortesia concedida somente pelo master e NUNCA pode
-- ser escolhido pelo auto-upgrade (nem no ramo local, nem no trilho Asaas).
--
-- Ordem canônica de locks: Igreja -> Planos (codigo ordenado) -> operação ->
-- Subscription. O trigger cria ou trava a operação ANTES da Subscription; a
-- reconciliação usa o mesmo sufixo operação -> Subscription. Isso elimina os
-- ciclos Plano -> Igreja e Subscription -> operação que causavam deadlock.
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
  v_igreja_plano text;
  v_igreja_preco numeric(10,2);
  v_igreja_limite int;
  v_total int;
  v_sub_snapshot public.subscriptions%rowtype;
  v_sub public.subscriptions%rowtype;
  v_novo_plano text;
  v_novo_limite int;
  v_novo_preco numeric(10,2);
  v_inserted_operation_id uuid;
  v_locked_operation_id uuid;
begin
  if tg_op = 'DELETE' then
    v_igreja_id := old.igreja_id;
  else
    v_igreja_id := new.igreja_id;
  end if;

  -- A concessão master em igrejas.plano é a autoridade do entitlement. Trava
  -- primeiro a Igreja; checkout e painel master usam a mesma primeira linha.
  select i.plano into v_igreja_plano
    from public.igrejas i
   where i.id = v_igreja_id
   for update of i;
  if not found then
    if tg_op = 'DELETE' then return old; else return new; end if;
  end if;

  -- Todos os planos possivelmente tocados são travados em ordem estável, igual
  -- ao helper Python lock_plan_rows_for_billing.
  perform 1
    from public.planos p
   where p.codigo = v_igreja_plano
      or p.codigo in ('ate_100', '101_200', 'acima_201')
   order by p.codigo
   for update of p;

  select p.preco_mensal, p.limite_pessoas
    into v_igreja_preco, v_igreja_limite
    from public.planos p
   where p.codigo = v_igreja_plano;

  -- Snapshot sem row lock: ele serve apenas para decidir se existe uma
  -- operação correspondente a reservar. A Subscription só será travada depois
  -- da operação, preservando o sufixo canônico usado pela reconciliação.
  select * into v_sub_snapshot
    from public.subscriptions s
   where s.igreja_id = v_igreja_id;
  if not found then
    if tg_op = 'DELETE' then return old; else return new; end if;
  end if;

  select count(*) into v_total
    from public.pessoas
   where igreja_id = v_igreja_id
     and arquivada_em is null
     and coalesce(sem_interesse, false) is false
     and tipo in ('membro', 'discipulo', 'lider', 'pastor');

  -- Catálogo ausente é estado inválido e falha fechado sem reatribuir plano.
  if v_igreja_preco is null then
    if tg_op = 'DELETE' then return old; else return new; end if;
  end if;

  -- Descobre o alvo a partir do snapshot, ainda sem tocar a Subscription. Se
  -- houver recorrência remota, reserva a operação antes do row lock final.
  if v_igreja_preco > 0
     and v_sub_snapshot.limite is not null
     and v_total > v_sub_snapshot.limite then
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
           end > case v_sub_snapshot.plano
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
     limit 1;
  end if;

  if v_novo_plano is not null
     and v_novo_preco is not null
     and v_sub_snapshot.asaas_subscription_id is not null then
    insert into public.billing_plan_change_operations
      (subscription_id, asaas_subscription_id, from_plano, to_plano,
       to_preco, to_limite, to_descricao, origin, status, notify_status)
    values
      (v_sub_snapshot.id, v_sub_snapshot.asaas_subscription_id,
       v_sub_snapshot.plano, v_novo_plano, v_novo_preco, v_novo_limite,
       'PastorAI — plano ' || v_novo_plano,
       'autoupgrade', 'prepared', 'pending')
    on conflict (subscription_id)
      where status in ('prepared','processing','reconciling')
      do nothing
    returning id into v_inserted_operation_id;
  end if;

  -- Uma operação manual/automática já aberta também é o slot correspondente.
  -- Trave-a mesmo nos ramos cortesia/local antes de tocar a Subscription.
  select o.id into v_locked_operation_id
    from public.billing_plan_change_operations o
   where o.subscription_id = v_sub_snapshot.id
     and o.status in ('prepared','processing','reconciling')
   order by o.created_at, o.id
   limit 1
   for update of o;

  select * into v_sub
    from public.subscriptions s
   where s.id = v_sub_snapshot.id
     and s.igreja_id = v_igreja_id
   for update of s;
  if not found then
    if tg_op = 'DELETE' then return old; else return new; end if;
  end if;

  -- Cortesia da Igreja sempre vence um snapshot histórico pago da Subscription.
  -- Mantém apenas o espelho local coerente; nunca cria/cancela cobrança remota.
  if v_igreja_preco <= 0 then
    update public.subscriptions
       set pessoas = v_total,
           plano = v_igreja_plano,
           limite = v_igreja_limite
     where id = v_sub.id;
    if tg_op = 'DELETE' then return old; else return new; end if;
  end if;

  update public.subscriptions
     set pessoas = v_total
   where id = v_sub.id;

  -- Revalida o alvo com a Subscription agora travada. Planos e Igreja seguem
  -- bloqueados; qualquer reserva criada por este trigger é corrigida ou
  -- removida no mesmo commit, sem estado parcial visível.
  v_novo_plano := null;
  v_novo_preco := null;
  v_novo_limite := null;
  if v_sub.limite is not null and v_total > v_sub.limite then
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
     limit 1;
  end if;

  if v_inserted_operation_id is not null
     and (v_novo_plano is null or v_sub.asaas_subscription_id is null) then
    delete from public.billing_plan_change_operations
     where id = v_inserted_operation_id;
    v_locked_operation_id := null;
  end if;

  if v_novo_plano is not null and v_novo_preco is not null then
    if v_sub.asaas_subscription_id is null then
      -- Operação aberta legada/ambígua impede promoção local. Sem operação,
      -- esta assinatura é puramente local e pode avançar no mesmo commit.
      if v_locked_operation_id is null then
        update public.subscriptions
           set plano = v_novo_plano,
               limite = v_novo_limite
         where id = v_sub.id;
        update public.igrejas
           set plano = v_novo_plano
         where id = v_igreja_id;
      end if;
    elsif v_inserted_operation_id is not null then
      update public.billing_plan_change_operations
         set asaas_subscription_id = v_sub.asaas_subscription_id,
             from_plano = v_sub.plano,
             to_plano = v_novo_plano,
             to_preco = v_novo_preco,
             to_limite = v_novo_limite,
             to_descricao = 'PastorAI — plano ' || v_novo_plano
       where id = v_inserted_operation_id;
    end if;
    -- Se a recorrência apareceu depois do snapshot e não há operação travada,
    -- falha fechado: atualiza só a contagem; um próximo evento/recovery cria o
    -- claim na ordem correta, nunca depois de já ter travado a Subscription.
  end if;

  if tg_op = 'DELETE' then return old; else return new; end if;
end;
$$;

-- Corrige somente alvos automáticos ainda comprovadamente pré-rede.
do $reconcile_zero_price_prepared_upgrades$
declare
  v_op record;
  v_current_plan text;
  v_current_limit integer;
  v_current_asaas_subscription_id text;
  v_total integer;
  v_target_code text;
  v_target_price numeric(10,2);
  v_target_limit integer;
begin
  for v_op in
    select o.id,
           o.subscription_id,
           s.igreja_id,
           o.to_plano
      from public.billing_plan_change_operations o
      join public.subscriptions s on s.id = o.subscription_id
      left join public.planos old_target on old_target.codigo = o.to_plano
     where o.origin = 'autoupgrade'
       and o.status = 'prepared'
       and (old_target.codigo is null or old_target.preco_mensal <= 0)
     order by o.created_at, o.id
  loop
    -- Mesmo prefixo canônico do trigger e do painel master. O cursor acima só
    -- descobre candidatos; toda condição é revalidada depois dos locks.
    perform 1 from public.igrejas i
     where i.id = v_op.igreja_id
     for update of i;
    if not found then continue; end if;

    perform 1 from public.planos p
     where p.codigo = v_op.to_plano
        or p.codigo in ('ate_100', '101_200', 'acima_201')
     order by p.codigo
     for update of p;

    perform 1
      from public.billing_plan_change_operations o
      left join public.planos old_target on old_target.codigo = o.to_plano
     where o.id = v_op.id
       and o.origin = 'autoupgrade'
       and o.status = 'prepared'
       and (old_target.codigo is null or old_target.preco_mensal <= 0)
     for update of o;
    if not found then continue; end if;

    select s.plano, s.limite, s.asaas_subscription_id
      into v_current_plan, v_current_limit, v_current_asaas_subscription_id
      from public.subscriptions s
     where s.id = v_op.subscription_id
       and s.igreja_id = v_op.igreja_id
     for update of s;
    if not found then continue; end if;

    select count(*) into v_total
      from public.pessoas p
     where p.igreja_id = v_op.igreja_id
       and p.arquivada_em is null
       and coalesce(p.sem_interesse, false) is false
       and p.tipo in ('membro', 'discipulo', 'lider', 'pastor');

    v_target_code := null;
    v_target_price := null;
    v_target_limit := null;

    if v_current_limit is not null and v_total > v_current_limit then
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
             end > case v_current_plan
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
       and v_current_asaas_subscription_id is not null
       and v_target_code is not null then
      insert into public.billing_plan_change_operations
        (subscription_id, asaas_subscription_id, from_plano, to_plano,
         to_preco, to_limite, to_descricao, origin, status, notify_status)
      values
        (v_op.subscription_id, v_current_asaas_subscription_id,
         v_current_plan, v_target_code, v_target_price, v_target_limit,
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
