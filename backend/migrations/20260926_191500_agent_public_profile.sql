-- S2: fatos públicos estruturados do agente, por igreja.
--
-- `agent_configs` já é relação tenant: igreja_id, RLS e a policy
-- `tenant_isolation` vêm de 0002/0003. Esta migration não recria policy,
-- muda ACL nem força RLS; apenas reafirma que RLS segue habilitada.

alter table public.agent_configs
  add column if not exists informacoes_publicas jsonb not null default '{}'::jsonb;

alter table public.agent_configs
  alter column informacoes_publicas set default '{}'::jsonb;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.agent_configs'::regclass
      and conname = 'agent_configs_informacoes_publicas_objeto'
  ) then
    alter table public.agent_configs
      add constraint agent_configs_informacoes_publicas_objeto
      check (jsonb_typeof(informacoes_publicas) = 'object');
  end if;
end $$;

-- A policy é por linha, portanto a nova coluna herda o isolamento existente.
-- Não usar FORCE ROW LEVEL SECURITY: a baseline de 0003 não o faz aqui.
alter table public.agent_configs enable row level security;

do $$
declare
  alvo constant regclass := 'public.agent_configs'::regclass;
begin
  if not exists (
    select 1
    from pg_attribute
    where attrelid = alvo
      and attname = 'informacoes_publicas'
      and atttypid = 'jsonb'::regtype
      and attnotnull
      and not attisdropped
  ) then
    raise exception 'agent_configs.informacoes_publicas não ficou jsonb NOT NULL';
  end if;
  if not exists (
    select 1
    from pg_attrdef definicao
    join pg_attribute coluna
      on coluna.attrelid = definicao.adrelid
      and coluna.attnum = definicao.adnum
    where definicao.adrelid = alvo
      and coluna.attname = 'informacoes_publicas'
      and pg_get_expr(definicao.adbin, definicao.adrelid) = '''{}''::jsonb'
  ) then
    raise exception 'agent_configs.informacoes_publicas não ficou com default {}';
  end if;
  if not exists (
    select 1
    from pg_constraint
    where conrelid = alvo
      and conname = 'agent_configs_informacoes_publicas_objeto'
      and contype = 'c'
  ) then
    raise exception 'agent_configs: CHECK de objeto público ausente';
  end if;
  if not (select relrowsecurity from pg_class where oid = alvo) then
    raise exception 'agent_configs: RLS desligada';
  end if;
  if not exists (
    select 1
    from pg_policy
    where polrelid = alvo
      and polname = 'tenant_isolation'
      and polcmd = '*'
  ) then
    raise exception 'agent_configs: policy tenant_isolation ausente';
  end if;
end $$;

-- Rollback de aplicação: reverter o código, que ignora a coluna.
-- Rollback físico é destrutivo e deve ser uma migration futura revisada:
-- ALTER TABLE public.agent_configs
--   DROP CONSTRAINT IF EXISTS agent_configs_informacoes_publicas_objeto;
-- ALTER TABLE public.agent_configs DROP COLUMN IF EXISTS informacoes_publicas;
