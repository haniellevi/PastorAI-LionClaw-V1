-- V4 own-text prayer requests. No activation, data backfill or shared apply.
-- The application release fence and tenant allowlist remain closed.
begin;
set local lock_timeout = '2s';
create unique index if not exists celulas_igreja_id_id_key on public.celulas(igreja_id,id);


CREATE TABLE IF NOT EXISTS public.pedido_oracao_proposta (
	id UUID NOT NULL,
	igreja_id UUID NOT NULL,
	pessoa_id UUID NOT NULL,
	conversation_id UUID NOT NULL,
	source_message_id UUID NOT NULL,
	summary_message_id UUID,
    delivered_at TIMESTAMP WITH TIME ZONE,
	summary TEXT NOT NULL,
	audience TEXT,
	cell_id UUID,
	leader_id UUID,
	authorization_text TEXT,
	term_version TEXT NOT NULL,
	state TEXT DEFAULT 'collecting' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (igreja_id, id),
	UNIQUE (igreja_id, source_message_id),
	FOREIGN KEY(igreja_id, pessoa_id) REFERENCES public.pessoas (igreja_id, id) ON DELETE CASCADE,
	FOREIGN KEY(igreja_id, conversation_id) REFERENCES public.conversations (igreja_id, id) ON DELETE CASCADE,
	FOREIGN KEY(igreja_id, conversation_id, source_message_id) REFERENCES public.messages (igreja_id, conversation_id, id) ON DELETE CASCADE,
	FOREIGN KEY(igreja_id, conversation_id, summary_message_id) REFERENCES public.messages (igreja_id, conversation_id, id) ON DELETE CASCADE,
	FOREIGN KEY(igreja_id, cell_id) REFERENCES public.celulas (igreja_id, id) ON DELETE SET NULL (cell_id),
	FOREIGN KEY(igreja_id, leader_id) REFERENCES public.pessoas (igreja_id, id) ON DELETE SET NULL (leader_id),
	CHECK (state in ('collecting','pending','executed','cancelled','expired')),
	CHECK (audience is null or audience in ('pastoral','pastoral_lider')),
	FOREIGN KEY(igreja_id) REFERENCES public.igrejas (id) ON DELETE CASCADE
)

;

CREATE UNIQUE INDEX IF NOT EXISTS prayer_one_active_proposal ON public.pedido_oracao_proposta (igreja_id, conversation_id) WHERE state in ('collecting','pending');


CREATE TABLE IF NOT EXISTS public.pedido_oracao (
	id UUID NOT NULL,
	igreja_id UUID NOT NULL,
	pessoa_id UUID NOT NULL,
	conversation_id UUID NOT NULL,
	proposal_id UUID NOT NULL,
	confirmation_message_id UUID NOT NULL,
	summary TEXT NOT NULL,
	audience TEXT NOT NULL,
	cell_id UUID,
	leader_id UUID,
	authorization_text TEXT NOT NULL,
	authorization_hash TEXT NOT NULL,
	authorization_version TEXT NOT NULL,
	authorized_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	responsavel_id UUID,
	state TEXT DEFAULT 'open' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	closed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	UNIQUE (igreja_id, id),
	UNIQUE (igreja_id, proposal_id),
	UNIQUE (igreja_id, confirmation_message_id),
	FOREIGN KEY(igreja_id, proposal_id) REFERENCES public.pedido_oracao_proposta (igreja_id, id) ON DELETE CASCADE,
	FOREIGN KEY(igreja_id, pessoa_id) REFERENCES public.pessoas (igreja_id, id) ON DELETE CASCADE,
	FOREIGN KEY(igreja_id, conversation_id) REFERENCES public.conversations (igreja_id, id) ON DELETE CASCADE,
	FOREIGN KEY(igreja_id, conversation_id, confirmation_message_id) REFERENCES public.messages (igreja_id, conversation_id, id) ON DELETE CASCADE,
	FOREIGN KEY(igreja_id, cell_id) REFERENCES public.celulas (igreja_id, id) ON DELETE SET NULL (cell_id),
	FOREIGN KEY(igreja_id, leader_id) REFERENCES public.pessoas (igreja_id, id) ON DELETE SET NULL (leader_id),
	FOREIGN KEY(igreja_id, responsavel_id) REFERENCES public.app_users (igreja_id, id) ON DELETE SET NULL (responsavel_id),
	CHECK (audience in ('pastoral','pastoral_lider')),
	CHECK (state in ('open','assigned','closed')),
	CHECK (length(summary) between 1 and 1000),
	CHECK (length(authorization_hash) = 64),
	FOREIGN KEY(igreja_id) REFERENCES public.igrejas (id) ON DELETE CASCADE
)

;

CREATE INDEX IF NOT EXISTS prayer_recipient_idx ON public.pedido_oracao (igreja_id, state, created_at);

create or replace function public.prayer_jwt_sub() returns text
language sql stable set search_path = pg_catalog, public as $$
 select nullif(coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',
                        current_setting('request.jwt.claim.sub',true)),'')
$$;
revoke all on function public.prayer_jwt_sub() from public;
grant execute on function public.prayer_jwt_sub() to authenticated;

create or replace function public.prayer_is_reader(tenant uuid, person uuid, audience text, cell uuid, leader uuid)
returns boolean language sql stable set search_path = pg_catalog, public as $$
 select exists (
  select 1 from public.app_users a
  where a.igreja_id=tenant and a.status='ativo' and a.clerk_user_id=public.prayer_jwt_sub()
    and (a.pessoa_id is null or exists(select 1 from public.pessoas active_actor
      where active_actor.igreja_id=tenant and active_actor.id=a.pessoa_id and active_actor.arquivada_em is null))
    and (exists(select 1 from public.user_roles r where r.igreja_id=tenant and r.user_id=a.id and r.papel='pastor')
      or (audience='pastoral_lider' and a.pessoa_id=leader and exists(
       select 1 from public.celulas c
       join public.celula_membro m on m.igreja_id=c.igreja_id and m.celula_id=c.id
       join public.pessoas p on p.igreja_id=m.igreja_id and p.id=m.pessoa_id
       where c.igreja_id=tenant and c.id=cell and c.ativo and c.lider_id=leader
         and m.pessoa_id=person and m.ativo and p.arquivada_em is null
         and (p.celula_id is null or p.celula_id=c.id)
      )))
 )
$$;
revoke all on function public.prayer_is_reader(uuid,uuid,text,uuid,uuid) from public;
grant execute on function public.prayer_is_reader(uuid,uuid,text,uuid,uuid) to authenticated;

alter table public.pedido_oracao_proposta enable row level security;
alter table public.pedido_oracao_proposta force row level security;
alter table public.pedido_oracao enable row level security;
alter table public.pedido_oracao force row level security;
revoke all on public.pedido_oracao_proposta, public.pedido_oracao from public, authenticated;
grant select,insert,update,delete on public.pedido_oracao_proposta to authenticated;
grant select,insert on public.pedido_oracao to authenticated;
grant update(state,responsavel_id,closed_at) on public.pedido_oracao to authenticated;

-- The server worker has a proven tenant GUC and no panel JWT (existing S3 pattern).
drop policy if exists prayer_proposal_worker on public.pedido_oracao_proposta;
create policy prayer_proposal_worker on public.pedido_oracao_proposta to authenticated
 using(igreja_id=public.current_igreja_id() and public.prayer_jwt_sub() is null)
 with check(igreja_id=public.current_igreja_id() and public.prayer_jwt_sub() is null);
drop policy if exists prayer_request_read on public.pedido_oracao;
create policy prayer_request_read on public.pedido_oracao for select to authenticated
 using(igreja_id=public.current_igreja_id() and (public.prayer_jwt_sub() is null
   or public.prayer_is_reader(igreja_id,pessoa_id,audience,cell_id,leader_id)));
drop policy if exists prayer_request_insert on public.pedido_oracao;
create policy prayer_request_insert on public.pedido_oracao for insert to authenticated
 with check(igreja_id=public.current_igreja_id() and public.prayer_jwt_sub() is null);
drop policy if exists prayer_request_update on public.pedido_oracao;
create policy prayer_request_update on public.pedido_oracao for update to authenticated
 using(igreja_id=public.current_igreja_id() and public.prayer_is_reader(igreja_id,pessoa_id,audience,cell_id,leader_id))
 with check(igreja_id=public.current_igreja_id() and public.prayer_is_reader(igreja_id,pessoa_id,audience,cell_id,leader_id));

-- Admin may erase approved offboarding content without obtaining read access.
-- Fixed search_path, tenant revalidation, no arbitrary SQL and no returned content.
create or replace function public.delete_prayer_requests_for_person(tenant uuid, person uuid)
returns void language plpgsql security definer set search_path=pg_catalog,public as $$
begin
 if tenant is distinct from public.current_igreja_id() or tenant is null then
   raise exception 'prayer deletion scope denied' using errcode='42501';
 end if;
 if public.prayer_jwt_sub() is not null and not exists(
   select 1 from public.app_users a join public.user_roles r on r.igreja_id=a.igreja_id and r.user_id=a.id
   where a.igreja_id=tenant and a.status='ativo' and a.clerk_user_id=public.prayer_jwt_sub() and r.papel='admin'
 ) then raise exception 'prayer deletion denied' using errcode='42501'; end if;
 delete from public.pedido_oracao where igreja_id=tenant and pessoa_id=person;
 delete from public.pedido_oracao_proposta where igreja_id=tenant and pessoa_id=person;
end $$;
revoke all on function public.delete_prayer_requests_for_person(uuid,uuid) from public;
grant execute on function public.delete_prayer_requests_for_person(uuid,uuid) to authenticated;

-- A handoff/opt-out must never resurrect an old prayer SIM, even if its flag
-- closes in between. Parent-row authorization is enforced by existing RLS.
create or replace function public.prayer_cancel_pending() returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
begin
 if tg_table_name='conversations' then
  update public.pedido_oracao_proposta set state='cancelled'
   where igreja_id=new.igreja_id and conversation_id=new.id and state in ('collecting','pending');
 else
  update public.pedido_oracao_proposta set state='cancelled'
   where igreja_id=new.igreja_id and pessoa_id=new.id and state in ('collecting','pending');
 end if;
 return new;
end $$;
revoke all on function public.prayer_cancel_pending() from public;
drop trigger if exists prayer_handoff_cancel on public.conversations;
create trigger prayer_handoff_cancel after update of estado on public.conversations
 for each row when (new.estado='humano') execute function public.prayer_cancel_pending();
drop trigger if exists prayer_optout_cancel on public.pessoas;
create trigger prayer_optout_cancel after update of optout on public.pessoas
 for each row when (new.optout) execute function public.prayer_cancel_pending();

-- One conversation can have only one confirmation protocol at a time. Both
-- proposal writers already lock its conversation; retain that fence here too.
create or replace function public.prayer_supersede_other_protocol() returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
begin
 perform 1 from public.conversations where igreja_id=new.igreja_id and id=new.conversation_id for update;
 if tg_table_name='pedido_oracao_proposta' then
  update public.agent_action_proposals set state='cancelada', terminal_reason='superseded_by_prayer'
   where igreja_id=new.igreja_id and conversation_id=new.conversation_id and state in ('preparada','pendente');
 else
  update public.pedido_oracao_proposta set state='cancelled'
   where igreja_id=new.igreja_id and conversation_id=new.conversation_id and state in ('collecting','pending');
 end if;
 return new;
end $$;
revoke all on function public.prayer_supersede_other_protocol() from public;
drop trigger if exists prayer_supersede_s3 on public.pedido_oracao_proposta;
create trigger prayer_supersede_s3 after insert on public.pedido_oracao_proposta
 for each row when (new.state in ('collecting','pending')) execute function public.prayer_supersede_other_protocol();
drop trigger if exists s3_supersede_prayer on public.agent_action_proposals;
create trigger s3_supersede_prayer after insert on public.agent_action_proposals
 for each row when (new.state in ('preparada','pendente')) execute function public.prayer_supersede_other_protocol();

commit;

-- ROLLBACK (manual, never part of apply): keep activation closed and drain replies.
-- Preserve confirmed requests and their authorization under the approved privacy
-- policy before any destructive removal. Do not recreate notifications or reopen
-- old gates. Only after explicit approval and no pending requests:
-- DROP FUNCTION public.delete_prayer_requests_for_person(uuid,uuid);
-- DROP TRIGGER prayer_handoff_cancel ON public.conversations;
-- DROP TRIGGER prayer_optout_cancel ON public.pessoas;
-- DROP FUNCTION public.prayer_cancel_pending();
-- DROP TRIGGER s3_supersede_prayer ON public.agent_action_proposals;
-- DROP TRIGGER prayer_supersede_s3 ON public.pedido_oracao_proposta;
-- DROP FUNCTION public.prayer_supersede_other_protocol();
-- DROP TABLE public.pedido_oracao;
-- DROP TABLE public.pedido_oracao_proposta;
-- DROP FUNCTION public.prayer_is_reader(uuid,uuid,text,uuid,uuid);
-- DROP FUNCTION public.prayer_jwt_sub();
