-- ============================================================================
-- PastorAI — Migration 20260808_001059_billing_count_active_members
--
-- Regra comercial: o porte do plano é definido por MEMBROS, não por todos os
-- registros de `pessoas`. São faturáveis as pessoas ativas em nível de membro
-- ou acima: membro, discípulo, líder legado e pastor. Contatos, visitantes,
-- CSIM (`sem_interesse`) e arquivados ficam fora.
--
-- Os nomes físicos `subscriptions.pessoas` e `planos.limite_pessoas` são
-- preservados por compatibilidade; passam a representar membros faturáveis.
-- A função mantém o trilho durável introduzido em
-- 20260730_205332_billing_setup_configuration.sql e nunca chama rede.
--
-- Aplicar no Supabase em ordem de nome de arquivo, primeiro em DEV. A promoção
-- para PROD permanece um gate separado, posterior à revisão do código.
-- ============================================================================

begin;

create or replace function fn_subscription_autoupgrade()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_igreja_id uuid;
  v_total int;
  v_sub subscriptions%rowtype;
  v_novo_plano text;
  v_novo_limite int;
  v_novo_preco numeric(10,2);
begin
  -- DELETE não possui NEW; INSERT/UPDATE usam a linha nova. `igreja_id` não é
  -- transferível entre tenants pela aplicação.
  if tg_op = 'DELETE' then
    v_igreja_id := old.igreja_id;
  else
    v_igreja_id := new.igreja_id;
  end if;

  select * into v_sub
    from subscriptions
   where igreja_id = v_igreja_id;
  if not found then
    if tg_op = 'DELETE' then return old; else return new; end if;
  end if;

  select count(*) into v_total
    from pessoas
   where igreja_id = v_igreja_id
     and arquivada_em is null
     and coalesce(sem_interesse, false) is false
     and tipo in ('membro', 'discipulo', 'lider', 'pastor');

  -- Coluna legada: agora espelha somente membros faturáveis ativos.
  update subscriptions
     set pessoas = v_total
   where igreja_id = v_igreja_id;

  if v_sub.limite is not null and v_total > v_sub.limite then
    -- Primeiro degrau ATIVO acima do atual que comporte os membros.
    select p.codigo, p.preco_mensal, p.limite_pessoas
      into v_novo_plano, v_novo_preco, v_novo_limite
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

    if v_novo_plano is not null and v_novo_preco is not null then
      if v_sub.asaas_subscription_id is null then
        -- Sem recorrência remota rastreada, preserva o upgrade local imediato.
        update subscriptions
           set plano = v_novo_plano,
               limite = v_novo_limite
         where igreja_id = v_igreja_id;
        update igrejas
           set plano = v_novo_plano
         where id = v_igreja_id;
      else
        -- Com Asaas, apenas registra a intenção; o worker faz o PUT seguro.
        insert into billing_plan_change_operations
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

-- DELETE, arquivamento, reativação e reclassificação também precisam reduzir
-- ou aumentar o espelho; o trigger anterior não cobria DELETE.
drop trigger if exists trg_subscription_autoupgrade on pessoas;
create trigger trg_subscription_autoupgrade
  after insert or update or delete on pessoas
  for each row
  execute function fn_subscription_autoupgrade();

-- Mantém o endurecimento aplicado em 20260805_153000 após redefinir a função.
revoke all on function public.fn_subscription_autoupgrade()
  from public, anon, authenticated;
grant execute on function public.fn_subscription_autoupgrade() to service_role;

-- Corrige o espelho existente sem esperar uma futura alteração de pessoa.
update subscriptions s
   set pessoas = (
     select count(*)
       from pessoas p
      where p.igreja_id = s.igreja_id
        and p.arquivada_em is null
        and coalesce(p.sem_interesse, false) is false
        and p.tipo in ('membro', 'discipulo', 'lider', 'pastor')
   );

-- Fecha a janela migration-before-backend: uma operação automática ainda em
-- `prepared` comprovadamente não chamou o Asaas. Trava a linha, encerra a
-- intenção legada e cria outra com o alvo calculado por membros. Assim, um
-- worker antigo que já tenha lido a linha não consegue fazer o claim depois
-- do COMMIT (o UPDATE condicional prepared -> processing perde a corrida).
-- Manual e processing/reconciling permanecem intocados.
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

-- Atualiza somente os rótulos padrão; nomes personalizados pelo master ficam
-- intactos.
update planos set nome = 'Até 100 membros'
 where codigo = 'ate_100' and nome in ('Até 100 pessoas', 'Ate 100 pessoas');
update planos set nome = '101–200 membros'
 where codigo = '101_200' and nome in ('101–200 pessoas', '101-200 pessoas');
update planos set nome = '201+ membros'
 where codigo = 'acima_201' and nome = '201+ pessoas';

comment on column subscriptions.pessoas is
  'Nome legado: contagem espelhada de membros faturáveis ativos; não inclui contatos, visitantes, CSIM ou arquivados.';
comment on column planos.limite_pessoas is
  'Nome legado: limite comercial de membros faturáveis do plano; NULL significa ilimitado.';

commit;

-- Verificação pós-migration (somente leitura):
--
-- 1) O espelho deve ser igual à contagem canônica em todos os tenants:
--    select s.igreja_id, s.pessoas as espelho, count(p.id) as membros
--      from subscriptions s
--      left join pessoas p
--        on p.igreja_id = s.igreja_id
--       and p.arquivada_em is null
--       and coalesce(p.sem_interesse, false) is false
--       and p.tipo in ('membro', 'discipulo', 'lider', 'pastor')
--     group by s.igreja_id, s.pessoas
--    having s.pessoas is distinct from count(p.id);
--    ESPERADO: 0 linhas.
--
-- 2) Confirmar o trigger novo:
--    select pg_get_triggerdef(oid)
--      from pg_trigger
--     where tgname = 'trg_subscription_autoupgrade' and not tgisinternal;
--    ESPERADO: AFTER INSERT OR DELETE OR UPDATE ON public.pessoas.
