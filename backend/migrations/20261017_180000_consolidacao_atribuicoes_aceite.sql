-- G12 PR3: convites novos; nenhum backfill ou aceite presumido do legado.
set local lock_timeout = '2s';
create table public.consolidacao_atribuicoes (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null references public.igrejas(id) on delete cascade,
  consolidacao_id uuid not null,
  responsavel_id uuid not null,
  atribuida_por uuid not null,
  status text not null default 'atribuida'
    check (status in ('atribuida','aceita','recusada','expirada','substituida')),
  criada_em timestamptz not null default clock_timestamp(),
  prazo_aceite timestamptz not null,
  respondida_em timestamptz,
  autoatribuicao boolean not null default false,
  unique (igreja_id, id),
  foreign key (igreja_id, consolidacao_id)
    references public.consolidacoes(igreja_id, id) on delete cascade,
  foreign key (igreja_id, responsavel_id)
    references public.app_users(igreja_id, id),
  foreign key (igreja_id, atribuida_por)
    references public.app_users(igreja_id, id),
  check (prazo_aceite = criada_em + interval '24 hours'),
  check ((status = 'atribuida') = (respondida_em is null)),
  check (not autoatribuicao or status = 'aceita')
);
create unique index consolidacao_convite_pendente
  on public.consolidacao_atribuicoes(igreja_id, consolidacao_id)
  where status = 'atribuida';
create index consolidacao_atribuicoes_historico
  on public.consolidacao_atribuicoes(igreja_id, consolidacao_id, criada_em);
alter table public.consolidacao_atribuicoes enable row level security;
alter table public.consolidacao_atribuicoes force row level security;
create policy tenant_isolation on public.consolidacao_atribuicoes
  for all to authenticated
  using (igreja_id = public.current_igreja_id())
  with check (igreja_id = public.current_igreja_id());
revoke all on public.consolidacao_atribuicoes from public, anon, authenticated;
grant select, insert, update on public.consolidacao_atribuicoes to authenticated;
-- Convites também invalidam propostas antigas (inclusive ABA sem troca efetiva).
create or replace function public.fn_consolidacoes_assignment_revision()
returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if new.responsavel_id is distinct from old.responsavel_id
     or new.assignment_revision = old.assignment_revision + 1 then
    new.assignment_revision := old.assignment_revision + 1;
  elsif new.assignment_revision is distinct from old.assignment_revision then
    raise exception 'assignment_revision é gerenciada pelo servidor';
  end if;
  return new;
end;
$$;
-- O recibo antigo continua válido no histórico; writers novos informam o convite.
alter table public.agent_action_receipts drop constraint agent_action_receipts_receipt_text_closed;
alter table public.agent_action_receipts add constraint agent_action_receipts_receipt_text_closed
  check (receipt_text in ('Registro confirmado.', 'Relatório confirmado.',
    'Lembrete confirmado.', 'Fonovisita confirmada.', 'Consolidação atribuída.',
    'Lembretes de consolidação ativados.', 'Convite registrado. Aceite pendente no painel.'));
-- Rollback: suspender writers novos e preservar/exportar histórico privado em
-- alvo autorizado antes de remover. Não promover candidatos nem invalidar legado.
-- drop table public.consolidacao_atribuicoes;
-- Restaurar fn_consolidacoes_assignment_revision() da migration V3 antes de
-- voltar aos writers antigos; não restaurar uma revisão anterior do contador.
-- create or replace function public.fn_consolidacoes_assignment_revision()
-- returns trigger language plpgsql set search_path = public, pg_temp as $$
-- begin
--   if new.responsavel_id is distinct from old.responsavel_id then
--     new.assignment_revision := old.assignment_revision + 1;
--   elsif new.assignment_revision is distinct from old.assignment_revision then
--     raise exception 'assignment_revision é gerenciada pelo servidor';
--   end if;
--   return new;
-- end;
-- $$;
-- Manter o check aditivo de recibos: recibos novos existentes não devem ser apagados.
