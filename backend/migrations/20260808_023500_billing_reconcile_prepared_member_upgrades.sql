-- ============================================================================
-- PastorAI — Migration 20260808_023500_billing_reconcile_prepared_member_upgrades
--
-- Compensação forward-only para ambientes que aplicaram a primeira versão de
-- 20260808_001059 antes de ela fechar a janela migration-before-backend.
-- Em PROD novo, 001059 já faz esta reconciliação e este arquivo vira no-op.
-- Nunca chama rede e nunca altera operação manual/processing/reconciling.
-- ============================================================================

begin;

do $reconcile_prepared_member_upgrades$
declare
  v_op record;
  v_total integer;
  v_target_code text;
  v_target_price numeric(10,2);
  v_target_limit integer;
  v_target_description text;
begin
  for v_op in
    select o.id,
           o.subscription_id,
           o.asaas_subscription_id as operation_asaas_subscription_id,
           o.to_plano,
           o.to_preco,
           o.to_limite,
           o.to_descricao,
           s.igreja_id,
           s.plano as current_plan,
           s.limite as current_limit,
           s.asaas_subscription_id as current_asaas_subscription_id
      from billing_plan_change_operations o
      join subscriptions s on s.id = o.subscription_id
     where o.origin = 'autoupgrade'
       and o.status = 'prepared'
     order by o.created_at, o.id
     for update of o
  loop
    select count(*) into v_total
      from pessoas p
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
        from planos p
       where p.ativo is true
         and p.codigo in ('ate_100', '101_200', 'acima_201')
         and p.preco_mensal is not null
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
       limit 1;
    end if;

    v_target_description := case
      when v_target_code is null then null
      else 'PastorAI — plano ' || v_target_code
    end;

    if v_op.current_asaas_subscription_id is null
       or v_op.operation_asaas_subscription_id
            is distinct from v_op.current_asaas_subscription_id
       or v_op.to_plano is distinct from v_target_code
       or v_op.to_preco is distinct from v_target_price
       or v_op.to_limite is distinct from v_target_limit
       or v_op.to_descricao is distinct from v_target_description then
      update billing_plan_change_operations
         set status = 'failed',
             notify_status = 'skipped',
             error = 'Substituída antes do PUT pela contagem de membros ativos.',
             attempt_started_at = null,
             updated_at = now()
       where id = v_op.id
         and status = 'prepared';

      if v_op.current_asaas_subscription_id is not null
         and v_target_code is not null then
        insert into billing_plan_change_operations
          (subscription_id, asaas_subscription_id, from_plano, to_plano,
           to_preco, to_limite, to_descricao, origin, status, notify_status)
        values
          (v_op.subscription_id, v_op.current_asaas_subscription_id,
           v_op.current_plan, v_target_code, v_target_price, v_target_limit,
           v_target_description, 'autoupgrade', 'prepared', 'pending')
        on conflict (subscription_id)
          where status in ('prepared','processing','reconciling')
          do nothing;
      end if;
    end if;
  end loop;
end;
$reconcile_prepared_member_upgrades$;

commit;

-- Verificação pós-migration (somente leitura):
-- Não deve restar operação automática PREPARED cujo alvo congelado diverge do
-- catálogo/contagem de membros. O worker novo revalida novamente antes do PUT.
