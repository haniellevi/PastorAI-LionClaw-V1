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
