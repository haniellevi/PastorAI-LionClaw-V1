-- S2b: fatos públicos canônicos em igrejas/celulas e estado durável da oferta
-- de secretaria. Esta migration é aditiva: não recria policies, não força
-- RLS e amplia somente o UPDATE por coluna de Igreja para os dois fatos novos.
-- As relações já pertencem à fronteira tenant.

set local lock_timeout = '2s';

alter table public.igrejas
  add column if not exists endereco_institucional text,
  add column if not exists horarios_culto text;

alter table public.celulas
  add column if not exists bairro text,
  add column if not exists divulgar_whatsapp boolean not null default false;

alter table public.conversations
  add column if not exists secretaria_oferta_estado text,
  add column if not exists secretaria_oferta_message_id uuid,
  add column if not exists secretaria_oferta_expira_em timestamptz,
  add column if not exists secretaria_oferta_resposta_message_id uuid;

-- NULL identifies pre-classifier rows. New pending replies write an explicit
-- TRUE or FALSE value when their response is persisted.
alter table public.messages
  add column if not exists public_info_reply boolean;

-- The triple is intentionally redundant with messages.id alone: it lets both
-- offer anchors prove the same tenant and conversation as their owner.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.messages'::regclass
      and conname = 'messages_igreja_id_conversation_id_id_key'
  ) then
    alter table public.messages
      add constraint messages_igreja_id_conversation_id_id_key
      unique (igreja_id, conversation_id, id);
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.conversations'::regclass
      and conname = 'conversations_secretaria_oferta_anchor_tenant_fkey'
  ) then
    alter table public.conversations
      add constraint conversations_secretaria_oferta_anchor_tenant_fkey
      foreign key (igreja_id, id, secretaria_oferta_message_id)
      references public.messages (igreja_id, conversation_id, id)
      on delete no action;
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.conversations'::regclass
      and conname = 'conversations_secretaria_oferta_response_tenant_fkey'
  ) then
    alter table public.conversations
      add constraint conversations_secretaria_oferta_response_tenant_fkey
      foreign key (igreja_id, id, secretaria_oferta_resposta_message_id)
      references public.messages (igreja_id, conversation_id, id)
      on delete no action;
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.messages'::regclass
      and conname = 'messages_public_info_reply_ia_chk'
  ) then
    alter table public.messages
      add constraint messages_public_info_reply_ia_chk
      check (
        public_info_reply is null
        or (direcao = 'out' and autor = 'ia' and agent_reply_state is not null)
      ) not valid;
  end if;
end $$;

alter table public.messages
  validate constraint messages_public_info_reply_ia_chk;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.igrejas'::regclass
      and conname = 'igrejas_endereco_institucional_400_chk'
  ) then
    alter table public.igrejas
      add constraint igrejas_endereco_institucional_400_chk
      check (endereco_institucional is null or length(endereco_institucional) <= 400)
      not valid;
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.igrejas'::regclass
      and conname = 'igrejas_horarios_culto_400_chk'
  ) then
    alter table public.igrejas
      add constraint igrejas_horarios_culto_400_chk
      check (horarios_culto is null or length(horarios_culto) <= 400)
      not valid;
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.celulas'::regclass
      and conname = 'celulas_bairro_120_chk'
  ) then
    alter table public.celulas
      add constraint celulas_bairro_120_chk
      check (bairro is null or length(bairro) <= 120)
      not valid;
  end if;
end $$;

alter table public.igrejas
  validate constraint igrejas_endereco_institucional_400_chk;
alter table public.igrejas
  validate constraint igrejas_horarios_culto_400_chk;
alter table public.celulas
  validate constraint celulas_bairro_120_chk;

-- Backfill somente os dois fatos estruturados que o S2 anterior já validava.
-- Destino não vazio e todo o JSON legado permanecem intocados; não há criação
-- de célula nem publicação inferida por este UPDATE.
do $$
begin
  if exists (
    select 1 from pg_attribute
    where attrelid = 'public.agent_configs'::regclass
      and attname = 'informacoes_publicas'
      and not attisdropped
  ) then
    update public.igrejas as igreja
    set
      endereco_institucional = case
        when nullif(btrim(igreja.endereco_institucional), '') is null
          and jsonb_typeof(config.informacoes_publicas) = 'object'
          and jsonb_typeof(config.informacoes_publicas -> 'endereco_igreja') = 'string'
          and length(btrim(config.informacoes_publicas ->> 'endereco_igreja')) between 1 and 400
        then btrim(config.informacoes_publicas ->> 'endereco_igreja')
        else igreja.endereco_institucional
      end,
      horarios_culto = case
        when nullif(btrim(igreja.horarios_culto), '') is null
          and jsonb_typeof(config.informacoes_publicas) = 'object'
          and jsonb_typeof(config.informacoes_publicas -> 'horarios_culto') = 'string'
          and length(btrim(config.informacoes_publicas ->> 'horarios_culto')) between 1 and 400
        then btrim(config.informacoes_publicas ->> 'horarios_culto')
        else igreja.horarios_culto
      end
    from public.agent_configs as config
    where config.igreja_id = igreja.id
      and (
        nullif(btrim(igreja.endereco_institucional), '') is null
        or nullif(btrim(igreja.horarios_culto), '') is null
      );
  end if;
end $$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.conversations'::regclass
      and conname = 'conversations_secretaria_oferta_estado_chk'
  ) then
    alter table public.conversations
      add constraint conversations_secretaria_oferta_estado_chk
      check (
        coalesce((
          (secretaria_oferta_estado is null
            and secretaria_oferta_message_id is null
            and secretaria_oferta_expira_em is null
            and secretaria_oferta_resposta_message_id is null)
          or
          (secretaria_oferta_estado = 'preparada'
            and secretaria_oferta_message_id is not null
            and secretaria_oferta_expira_em is null
            and secretaria_oferta_resposta_message_id is null)
          or
          (secretaria_oferta_estado = 'aceite_aguardando_ancora'
            and secretaria_oferta_message_id is not null
            and secretaria_oferta_expira_em is null
            and secretaria_oferta_resposta_message_id is not null)
          or
          (secretaria_oferta_estado = 'pendente'
            and secretaria_oferta_message_id is not null
            and secretaria_oferta_expira_em is not null
            and secretaria_oferta_resposta_message_id is null)
          or
          (secretaria_oferta_estado = 'consumida'
            and secretaria_oferta_message_id is not null
            and secretaria_oferta_expira_em is null
            and secretaria_oferta_resposta_message_id is not null)
          or
          (secretaria_oferta_estado = 'cancelada'
            and secretaria_oferta_message_id is not null
            and secretaria_oferta_expira_em is null)
          or
          (secretaria_oferta_estado = 'expirada'
            and secretaria_oferta_message_id is not null
            and secretaria_oferta_expira_em is null
            and secretaria_oferta_resposta_message_id is null)
        ), false)
      ) not valid;
  end if;
end $$;

alter table public.conversations
  validate constraint conversations_secretaria_oferta_estado_chk;

-- The composite FKs reject a mismatched tenant/conversation anchor. This
-- SECURITY INVOKER cleanup runs before a matching message delete, so the
-- state CHECK remains valid without blocking approved tenant deletion.
create or replace function public.clear_secretaria_offer_before_message_delete()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
  update public.conversations
  set
    secretaria_oferta_estado = null,
    secretaria_oferta_message_id = null,
    secretaria_oferta_expira_em = null,
    secretaria_oferta_resposta_message_id = null
  where igreja_id = old.igreja_id
    and id = old.conversation_id
    and (
      secretaria_oferta_message_id = old.id
      or secretaria_oferta_resposta_message_id = old.id
    );
  return old;
end;
$$;

drop trigger if exists clear_secretaria_offer_before_message_delete on public.messages;
create trigger clear_secretaria_offer_before_message_delete
before delete on public.messages
for each row execute function public.clear_secretaria_offer_before_message_delete();

-- Reafirma as barreiras existentes. Não acrescentar FORCE nem trocar policies.
-- A baseline de branding concedeu UPDATE de Igreja por coluna, então este
-- contrato amplia apenas as duas colunas novas e não devolve plano/status.
alter table public.igrejas enable row level security;
alter table public.celulas enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;

grant update (endereco_institucional, horarios_culto)
  on public.igrejas to authenticated;

do $$
declare
  alvo regclass;
begin
  foreach alvo in array array[
    'public.igrejas'::regclass,
    'public.celulas'::regclass,
    'public.conversations'::regclass,
    'public.messages'::regclass
  ] loop
    if not (select relrowsecurity from pg_class where oid = alvo) then
      raise exception 'RLS desligada para %', alvo;
    end if;
  end loop;
  if not exists (
    select 1 from pg_policy
    where polrelid = 'public.igrejas'::regclass
      and polname = 'igrejas_self_select'
  ) then
    raise exception 'policy igrejas_self_select ausente';
  end if;
  if not exists (
    select 1 from pg_policy
    where polrelid = 'public.celulas'::regclass
      and polname = 'tenant_isolation' and polcmd = '*'
  ) or not exists (
    select 1 from pg_policy
    where polrelid = 'public.conversations'::regclass
      and polname = 'tenant_isolation' and polcmd = '*'
  ) or not exists (
    select 1 from pg_policy
    where polrelid = 'public.messages'::regclass
      and polname = 'tenant_isolation' and polcmd = '*'
  ) then
    raise exception 'policy tenant_isolation ausente';
  end if;
end $$;

-- Rollback de aplicação: reverter o código, que ignora os campos novos.
-- Rollback físico perde estado de oferta e exige migration futura revisada.
-- A ordem abaixo preserva as FKs compostas até a limpeza do estado:
-- drop trigger if exists clear_secretaria_offer_before_message_delete on public.messages;
-- drop function if exists public.clear_secretaria_offer_before_message_delete();
-- revoke update (endereco_institucional, horarios_culto) on public.igrejas from authenticated;
-- alter table public.conversations
--   drop constraint if exists conversations_secretaria_oferta_response_tenant_fkey,
--   drop constraint if exists conversations_secretaria_oferta_anchor_tenant_fkey,
--   drop constraint if exists conversations_secretaria_oferta_estado_chk,
--   drop column if exists secretaria_oferta_resposta_message_id,
--   drop column if exists secretaria_oferta_expira_em,
--   drop column if exists secretaria_oferta_message_id,
--   drop column if exists secretaria_oferta_estado;
-- alter table public.messages
--   drop constraint if exists messages_public_info_reply_ia_chk,
--   drop column if exists public_info_reply;
-- alter table public.messages
--   drop constraint if exists messages_igreja_id_conversation_id_id_key;
-- alter table public.celulas drop column if exists divulgar_whatsapp,
--   drop column if exists bairro;
-- alter table public.igrejas drop column if exists horarios_culto,
--   drop column if exists endereco_institucional;
