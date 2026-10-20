-- Private operational summaries only; no prompt consumer, WhatsApp or activation.
begin;
set local lock_timeout='2s';
alter table public.conversations add column private_summary_revision bigint not null default 0;
create table public.private_summary_settings (
 igreja_id uuid primary key references public.igrejas(id) on delete cascade,
 enabled boolean not null default false,
 monthly_limit_microusd bigint not null default 0 check(monthly_limit_microusd>=0)
);
create table public.private_summary_budget (
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 month date not null, reserved_microusd bigint not null check(reserved_microusd>=0),
 primary key(igreja_id,month)
);
create table public.private_conversation_summaries (
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 conversation_id uuid not null, pessoa_id uuid not null,
 version bigint not null default 1 check(version>0),
 source_revision bigint not null, deletion_generation bigint not null,
 state text not null check(state in ('available','corrected','incorrect','suspended')),
 summary text check(summary is null or length(summary) between 1 and 1000),
 human_correction text check(human_correction is null or length(human_correction) between 1 and 1000),
 corrected_by uuid, updated_at timestamptz not null default now(),
 generator_version text not null default 'operational-pt-br-v1',
 primary key(igreja_id,conversation_id),
 foreign key(igreja_id,conversation_id) references public.conversations(igreja_id,id) on delete cascade,
 foreign key(igreja_id,pessoa_id) references public.pessoas(igreja_id,id) on delete cascade,
 foreign key(igreja_id,corrected_by) references public.app_users(igreja_id,id) on delete set null(corrected_by),
 check(state not in ('available','corrected') or summary is not null)
);
create table public.private_summary_sources (
 igreja_id uuid not null, conversation_id uuid not null, message_id uuid not null,
 primary key(igreja_id,conversation_id,message_id),
 foreign key(igreja_id,conversation_id) references public.private_conversation_summaries(igreja_id,conversation_id) on delete cascade,
 foreign key(igreja_id,conversation_id,message_id) references public.messages(igreja_id,conversation_id,id) on delete cascade
);
create table public.private_summary_tasks (
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 id uuid not null default gen_random_uuid(), conversation_id uuid not null, pessoa_id uuid not null,
 source_revision bigint not null, deletion_generation bigint not null,
 requester_id uuid,
 foreign key(igreja_id,requester_id) references public.app_users(igreja_id,id) on delete cascade,
 state text not null default 'queued' check(state in ('queued','running','done','refused')),
 created_at timestamptz not null default now(), started_at timestamptz, error_code text,
 primary key(igreja_id,id), unique(igreja_id,conversation_id,source_revision),
 foreign key(igreja_id,conversation_id) references public.conversations(igreja_id,id) on delete cascade,
 foreign key(igreja_id,pessoa_id) references public.pessoas(igreja_id,id) on delete cascade
);
create index private_summary_tasks_queue on public.private_summary_tasks(state,created_at);
-- Closed vocabulary is deliberately conservative. Unknown text, including any
-- free-form third party/identity/pastoral narrative, is never sent to a model.
create function public.private_summary_topic(body text) returns text
language sql immutable set search_path=pg_catalog,public as $$
 select case lower(btrim(body))
 when 'quero saber os horários dos cultos' then 'cultos'
 when 'qual o horário do culto?' then 'cultos'
 when 'como faço minha matrícula na uv?' then 'uv'
 when 'quero informações sobre a universidade da vida' then 'uv'
 when 'como faço minha matrícula na capacitação destino?' then 'cd'
 when 'quero informações sobre a capacitação destino' then 'cd'
 else null end
$$;
create function public.private_summary_worker() returns boolean
language sql stable set search_path=pg_catalog,public as $$
 select session_user not in ('authenticator','authenticated','anon') and public.prayer_jwt_sub() is null
$$;
-- SQL revalidation also protects direct SELECT, not only HTTP/service callers.
create function public.private_summary_origin_valid(t uuid,c uuid,p uuid) returns boolean
language sql stable security definer set search_path=pg_catalog,public as $$
 select t=public.current_igreja_id() and exists(
 select 1 from public.conversations cv join public.pessoas person on person.igreja_id=cv.igreja_id and person.id=cv.pessoa_id
 where cv.igreja_id=t and cv.id=c and cv.pessoa_id=p and person.arquivada_em is null and not person.optout
 and public.private_deletion_phone_key(cv.telefone)<>''
 and public.private_deletion_phone_key(cv.telefone)=public.private_deletion_phone_key(person.telefone)
 and (select count(*) from public.pessoas peers where peers.igreja_id=t and peers.arquivada_em is null
  and public.private_deletion_phone_key(peers.telefone)=public.private_deletion_phone_key(cv.telefone))=1
 and (select count(*) from public.messages m where m.igreja_id=t and m.conversation_id=c) between 1 and 40
 and not exists(select 1 from public.messages m where m.igreja_id=t and m.conversation_id=c and (
   m.direcao<>'in' or m.autor<>'contato' or coalesce(m.tipo,'texto')<>'texto' or m.media_path is not null
   or m.agent_privilege_context is not null or public.private_summary_topic(m.texto) is null))
 and not exists(select 1 from public.pedido_oracao_mensagem pm where pm.igreja_id=t and pm.conversation_id=c)
 and not exists(select 1 from public.pedido_oracao_proposta pr where pr.igreja_id=t and pr.conversation_id=c)
 and not exists(select 1 from public.cell_report_audio_inputs ai where ai.igreja_id=t and (ai.conversation_id=c or ai.live_conversation_id=c))
 )
$$;
create function public.private_summary_reader(t uuid,c uuid) returns boolean
language sql stable security definer set search_path=pg_catalog,public as $$
 select t=public.current_igreja_id() and exists(
 select 1 from public.app_users a join public.user_roles r on r.igreja_id=a.igreja_id and r.user_id=a.id
 join public.conversations cv on cv.igreja_id=a.igreja_id and cv.id=c
 where a.igreja_id=t and a.status='ativo' and a.clerk_user_id=public.prayer_jwt_sub() and r.papel in ('admin','pastor')
 and (a.pessoa_id is null or exists(select 1 from public.pessoas p where p.igreja_id=t and p.id=a.pessoa_id and p.arquivada_em is null))
 and (r.papel='admin' or not exists(select 1 from public.role_permissions rp where rp.igreja_id=t and rp.papel::text=r.papel::text)
 or exists(select 1 from public.role_permissions rp where rp.igreja_id=t and rp.papel::text=r.papel::text and rp.tela='inbox'))
 )
$$;
-- No HTTP role can enable generation or edit budget/tasks/sources. Worker
-- identity follows #509's trusted backend connection without a JWT subject.
do $$ declare n text; begin
 foreach n in array array['private_summary_settings','private_summary_budget','private_conversation_summaries','private_summary_sources','private_summary_tasks'] loop
 execute format('alter table public.%I enable row level security',n);
 execute format('alter table public.%I force row level security',n);
 execute format('revoke all on public.%I from public,anon,authenticated,service_role',n);
 execute format('grant select,insert,update,delete on public.%I to authenticated',n);
 execute format('create policy summary_worker on public.%I to authenticated using(igreja_id=public.current_igreja_id() and public.private_summary_worker()) with check(igreja_id=public.current_igreja_id() and public.private_summary_worker())',n);
 end loop;
end $$;
create policy summary_reader on public.private_conversation_summaries for select to authenticated using(
 public.private_summary_reader(igreja_id,conversation_id) and public.private_summary_origin_valid(igreja_id,conversation_id,pessoa_id)
 and source_revision=(select private_summary_revision from public.conversations c where c.igreja_id=private_conversation_summaries.igreja_id and c.id=conversation_id)
 and state<>'suspended');
create policy summary_source_reader on public.private_summary_sources for select to authenticated using(
 exists(select 1 from public.private_conversation_summaries s where s.igreja_id=private_summary_sources.igreja_id and s.conversation_id=private_summary_sources.conversation_id));
create function public.private_summary_correct(c uuid,expected_version bigint,correction text,incorrect boolean) returns boolean
language plpgsql security definer set search_path=pg_catalog,public as $$
declare t uuid:=public.current_igreja_id(); person uuid; revision bigint;
begin
 if not public.private_summary_reader(t,c) then raise exception 'summary denied' using errcode='42501'; end if;
 perform pg_advisory_xact_lock_shared(hashtextextended('private-content:'||t::text,0));
 select pessoa_id,private_summary_revision into person,revision from public.conversations where igreja_id=t and id=c for update;
 if not public.private_summary_origin_valid(t,c,person) then return false; end if;
 if not incorrect and (correction is null or length(btrim(correction)) not between 1 and 1000
  or public.private_summary_topic(correction) is null) then
  raise exception 'Operational correction required' using errcode='22023';
 end if;
 update public.private_conversation_summaries set summary=case when incorrect then null else correction end,
 human_correction=case when incorrect then null else correction end, state=case when incorrect then 'incorrect' else 'corrected' end,
 version=version+1,source_revision=revision,updated_at=now(),corrected_by=(select id from public.app_users where igreja_id=t and clerk_user_id=public.prayer_jwt_sub())
 where igreja_id=t and conversation_id=c and version=expected_version;
 return found;
end $$;
-- Web enqueue accepts no model-provided identity or source list.
create function public.private_summary_enqueue(c uuid) returns uuid
language plpgsql security definer set search_path=pg_catalog,public as $$
declare t uuid:=public.current_igreja_id(); person uuid; revision bigint; generation bigint; job uuid;
begin
 if not public.private_summary_reader(t,c) then raise exception 'summary denied' using errcode='42501'; end if;
 perform pg_advisory_xact_lock_shared(hashtextextended('private-content:'||t::text,0));
 select pessoa_id,private_summary_revision,deletion_generation into person,revision,generation
 from public.conversations where igreja_id=t and id=c for update;
 if not public.private_summary_origin_valid(t,c,person) or not exists(select 1 from public.private_summary_settings
 where igreja_id=t and enabled and monthly_limit_microusd>0) then return null; end if;
 insert into public.private_summary_tasks(igreja_id,conversation_id,pessoa_id,source_revision,deletion_generation,requester_id)
 values(t,c,person,revision,generation,(select id from public.app_users where igreja_id=t and clerk_user_id=public.prayer_jwt_sub())) on conflict(igreja_id,conversation_id,source_revision)
 do update set conversation_id=excluded.conversation_id returning id into job;
 return job;
end $$;
revoke all on function public.private_summary_enqueue(uuid) from public,anon,authenticated,service_role;
grant execute on function public.private_summary_enqueue(uuid) to authenticated;
-- Any source mutation invalidates publication. Human correction remains a live
-- constraint after an ordinary edit/append; deletion/protection removes it too.
create function public.private_summary_source_changed() returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
declare t uuid; c uuid; destructive boolean:=false;
begin
 if tg_op='DELETE' then t:=old.igreja_id; c:=old.conversation_id; destructive:=true;
 else t:=new.igreja_id; c:=new.conversation_id; end if;
 if tg_table_name='pedido_oracao_mensagem' then destructive:=true; end if;
 update public.conversations set private_summary_revision=private_summary_revision+1 where igreja_id=t and id=c;
 if destructive then delete from public.private_conversation_summaries where igreja_id=t and conversation_id=c;
 else
 update public.private_conversation_summaries set summary=null,state=case when state='incorrect' then state else 'suspended' end
 where igreja_id=t and conversation_id=c;
 end if;
 delete from public.private_summary_tasks where igreja_id=t and conversation_id=c;
 if tg_op='DELETE' then return old; end if; return new;
end $$;
create trigger private_summary_message_changed after insert or update of texto,tipo,media_path,agent_privilege_context,conversation_id,direcao,autor or delete on public.messages for each row execute function public.private_summary_source_changed();
create trigger private_summary_prayer_protected after insert or update on public.pedido_oracao_mensagem for each row execute function public.private_summary_source_changed();
-- Identity and responsibility changes cannot transfer retained memories.
create function public.private_summary_identity_changed() returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
begin
 if tg_table_name='conversations' then
 delete from public.private_conversation_summaries where igreja_id=old.igreja_id and conversation_id=old.id;
 delete from public.private_summary_tasks where igreja_id=old.igreja_id and conversation_id=old.id;
 new.private_summary_revision:=old.private_summary_revision+1;
 else
 delete from public.private_conversation_summaries where igreja_id=old.igreja_id and pessoa_id=old.id;
 delete from public.private_summary_tasks where igreja_id=old.igreja_id and pessoa_id=old.id;
 update public.conversations set private_summary_revision=private_summary_revision+1 where igreja_id=old.igreja_id and pessoa_id=old.id;
 end if;
 return new;
end $$;
create trigger private_summary_identity before update of pessoa_id,telefone,assumido_por on public.conversations for each row
 when(old.pessoa_id is distinct from new.pessoa_id or old.telefone is distinct from new.telefone or old.assumido_por is distinct from new.assumido_por)
 execute function public.private_summary_identity_changed();
create trigger private_summary_person before update of igreja_id,telefone,celula_id,lider_id,arquivada_em,optout on public.pessoas for each row
 when(old.igreja_id is distinct from new.igreja_id or old.telefone is distinct from new.telefone or old.celula_id is distinct from new.celula_id or old.lider_id is distinct from new.lider_id or old.arquivada_em is distinct from new.arquivada_em or old.optout is distinct from new.optout)
 execute function public.private_summary_identity_changed();
-- Canonical membership may change independently of pessoas.celula_id.
create function public.private_summary_membership_changed() returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
begin
 if tg_op<>'INSERT' then
  delete from public.private_conversation_summaries where igreja_id=old.igreja_id and pessoa_id=old.pessoa_id;
  delete from public.private_summary_tasks where igreja_id=old.igreja_id and pessoa_id=old.pessoa_id;
  update public.conversations set private_summary_revision=private_summary_revision+1 where igreja_id=old.igreja_id and pessoa_id=old.pessoa_id;
 end if;
 if tg_op<>'DELETE' then
  delete from public.private_conversation_summaries where igreja_id=new.igreja_id and pessoa_id=new.pessoa_id;
  delete from public.private_summary_tasks where igreja_id=new.igreja_id and pessoa_id=new.pessoa_id;
  update public.conversations set private_summary_revision=private_summary_revision+1 where igreja_id=new.igreja_id and pessoa_id=new.pessoa_id;
  return new;
 end if;
 return old;
end $$;
create trigger private_summary_membership after insert or update of pessoa_id,celula_id,ativo or delete
 on public.celula_membro for each row execute function public.private_summary_membership_changed();
-- Explicitly revoke default Supabase function grants, including trigger helpers.
do $$ declare sig text; begin
 foreach sig in array array['private_summary_topic(text)','private_summary_worker()','private_summary_origin_valid(uuid,uuid,uuid)','private_summary_reader(uuid,uuid)','private_summary_correct(uuid,bigint,text,boolean)','private_summary_source_changed()','private_summary_identity_changed()','private_summary_membership_changed()'] loop
 execute 'revoke all on function public.'||sig||' from public,anon,authenticated,service_role';
 end loop;
end $$;
grant execute on function public.private_summary_topic(text),public.private_summary_worker(),public.private_summary_origin_valid(uuid,uuid,uuid),public.private_summary_reader(uuid,uuid),public.private_summary_correct(uuid,bigint,text,boolean) to authenticated;

-- Same #518 erasure path, count/remove summaries before any source cascades.
create or replace function public.private_delete_content(p_tenant uuid,p_scope text,p_target uuid,p_operation uuid) returns uuid
language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_id uuid; v_generation bigint := 1; v_messages integer; v_audio integer; v_media integer; v_logs integer; v_sends integer;
 v_conversations uuid[]; v_inputs uuid[]; v_counts jsonb; v_table text; v_count integer; v_summaries integer;
begin
 if p_scope not in ('conversa','pessoa','igreja') or (p_scope='igreja' and p_target<>p_tenant) then
  raise exception 'Escopo inválido' using errcode='22023';
 end if;
 -- Ingestion takes the shared tenant barrier before touching Pessoa/conversa.
 -- Take this before any parent/child row lock, including from platform reset.
 perform pg_advisory_xact_lock(hashtextextended('private-content:'||p_tenant::text,0));
 -- Serialize retries and concurrent erasures of this target. No network in TX.
 perform pg_advisory_xact_lock(hashtextextended(p_tenant::text||p_scope||p_target::text,0));
 select id into v_id from public.private_deletion_receipts where igreja_id=p_tenant
  and scope=p_scope and target_id=p_target and operation_id=p_operation;
 if found then return v_id; end if;
 if p_scope='pessoa' then
  perform id from public.pessoas where igreja_id=p_tenant and id=p_target for key share;
 elsif p_scope='igreja' then
  perform id from public.igrejas where id=p_tenant for key share;
 else
  select deletion_generation+1 into v_generation from public.conversations
   where igreja_id=p_tenant and id=p_target for update;
 end if;
 if not found then
  if p_scope='conversa' then
   select id into v_id from public.private_deletion_receipts where igreja_id=p_tenant and scope=p_scope and target_id=p_target;
  end if;
  return v_id;
 end if;
 -- Shared ingestion barrier prevents new conversations during the snapshot.
 -- Parent KEY SHARE prevents cadastral removal without inverting worker locks.
 select coalesce(array_agg(id),'{}'::uuid[]) into v_conversations from public.conversations c where c.igreja_id=p_tenant and
  (p_scope='igreja' or (p_scope='conversa' and c.id=p_target) or (p_scope='pessoa' and (
   c.pessoa_id=p_target or c.id in(
    select conversation_id from public.pedido_oracao_proposta where igreja_id=p_tenant and pessoa_id=p_target
    union select conversation_id from public.pedido_oracao where igreja_id=p_tenant and pessoa_id=p_target
    union select conversation_id from public.agent_identity_challenges where igreja_id=p_tenant and pessoa_id=p_target
    union select conversation_id from public.agent_identity_proofs where igreja_id=p_tenant and pessoa_id=p_target
    union select conversation_id from public.agent_action_proposals where igreja_id=p_tenant and actor_pessoa_id=p_target
    union select conversation_id from public.cell_report_drafts where igreja_id=p_tenant and actor_pessoa_id=p_target
    union select conversation_id from public.cell_report_audio_inputs where igreja_id=p_tenant and (pessoa_id=p_target or live_pessoa_id=p_target)
    union select live_conversation_id from public.cell_report_audio_inputs where igreja_id=p_tenant and (pessoa_id=p_target or live_pessoa_id=p_target)
    union select conversation_id from public.cell_report_audio_notices where igreja_id=p_tenant and pessoa_id=p_target
    union select conversation_id from public.cell_report_audio_consent_events where igreja_id=p_tenant and pessoa_id=p_target
   ) or (c.pessoa_id is null and public.private_deletion_phone_key(c.telefone)<>'' and public.private_deletion_phone_key(c.telefone)=(
     select public.private_deletion_phone_key(telefone) from public.pessoas where igreja_id=p_tenant and id=p_target))
  )));
 perform id from public.conversations where igreja_id=p_tenant and id=any(v_conversations) order by id for update;
 update public.conversations set deletion_generation=deletion_generation+1 where igreja_id=p_tenant and id=any(v_conversations);
 select coalesce(array_agg(a.id),'{}'::uuid[]) into v_inputs from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
  (p_scope='igreja' or (p_scope='pessoa' and (a.pessoa_id=p_target or a.live_pessoa_id=p_target)) or
   a.conversation_id=any(v_conversations) or a.live_conversation_id=any(v_conversations) or
   a.inbound_message_id in(select id from public.messages where igreja_id=p_tenant and conversation_id=any(v_conversations)) or
   a.live_message_id in(select id from public.messages where igreja_id=p_tenant and conversation_id=any(v_conversations)));
 -- This row lock plus removal invalidates leases, including nullable live anchors.
 perform id from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
  a.id=any(v_inputs) for update;
 select count(*) into v_messages from public.messages where igreja_id=p_tenant and conversation_id=any(v_conversations);
 select count(*) filter(where a.transcript_text is not null) into v_audio from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
  a.id=any(v_inputs);
 delete from public.agent_conversation_logs where igreja_id=p_tenant and conversation_id=any(v_conversations);
 get diagnostics v_logs = row_count;
 select count(*) into v_sends from public.private_deletion_sends where igreja_id=p_tenant and conversation_id=any(v_conversations);
 delete from public.private_conversation_summaries where igreja_id=p_tenant and
  (p_scope='igreja' or (p_scope='pessoa' and pessoa_id=p_target) or conversation_id=any(v_conversations));
 get diagnostics v_summaries = row_count;
 delete from public.private_summary_tasks where igreja_id=p_tenant and
  (p_scope='igreja' or (p_scope='pessoa' and pessoa_id=p_target) or conversation_id=any(v_conversations));
 insert into public.private_deletion_receipts(igreja_id,scope,target_id,generation,operation_id,counts)
 values(p_tenant,p_scope,p_target,v_generation,p_operation,jsonb_build_object('mensagens',v_messages,'transcricoes',v_audio,'resumos',v_summaries,'checkpoints',0,'vetores',0,'logs_agente',v_logs,'envios',v_sends)) returning id into v_id;
 update public.private_deletion_receipts set person_id=case when p_scope='pessoa' then p_target
  when p_scope='conversa' then (select pessoa_id from public.conversations where igreja_id=p_tenant and id=p_target) end where id=v_id;
 if p_scope<>'conversa' then
  -- Old conversation receipts predate person provenance: conservatively include
  -- their outstanding cleanup, rather than claim a complete erasure without it.
  insert into public.private_deletion_dependencies(igreja_id,receipt_id,dependency_id)
  select p_tenant,v_id,r.id from public.private_deletion_receipts r where r.igreja_id=p_tenant and r.id<>v_id
   and (p_scope='igreja' or r.person_id=p_target or r.person_id is null);
 end if;
 insert into public.private_deletion_members(igreja_id,receipt_id,conversation_id)
 select p_tenant,v_id,unnest(v_conversations);
 -- Enumerate all installed cascades before deleting their source anchors.
 v_counts := '{}'::jsonb;
 foreach v_table in array array['agent_identity_challenges','agent_identity_proofs','agent_action_proposals',
  'agent_action_receipts','cell_report_drafts','cell_report_audio_notices','cell_report_audio_consent_events',
  'pedido_oracao','pedido_oracao_proposta','pedido_oracao_mensagem'] loop
  if to_regclass('public.'||v_table) is null then continue; end if;
  execute format('select count(*) from public.%I where igreja_id=$1 and conversation_id=any($2)',v_table)
   into v_count using p_tenant,v_conversations;
  v_counts := v_counts || jsonb_build_object(v_table,v_count);
 end loop;
 select count(*) into v_count from public.cell_report_audio_inputs where igreja_id=p_tenant and id=any(v_inputs);
 v_counts := v_counts || jsonb_build_object('entradas_audio',v_count);
 -- Unanchored logs cannot prove personal ownership. Scrub payloads, retaining
 -- operational dedupe markers so deletion cannot cause a real-send retry.
 if p_scope in ('pessoa','igreja') then
  update public.agent_conversation_logs set payload=null where igreja_id=p_tenant and conversation_id is null and payload is not null;
  get diagnostics v_count = row_count;
  v_counts := v_counts || jsonb_build_object('logs_sem_ancora',v_count);
 end if;
 update public.private_deletion_receipts set counts=counts||v_counts where id=v_id;
 insert into public.private_deletion_event_fences(igreja_id,event_token,receipt_id)
 select p_tenant,md5(p_tenant::text||':'||event_digest)::uuid,v_id from (
  select encode(sha256(convert_to(provider_message_id,'UTF8')),'hex') event_digest from public.messages
   where igreja_id=p_tenant and conversation_id=any(v_conversations) and provider_message_id is not null
  union
  select provider_message_sha256 from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
   a.id=any(v_inputs)
 ) events on conflict(igreja_id,event_token) do nothing;
 -- Persist external work before deleting any source references. Prefer the V1b
 -- source id on shared paths so late-upload recovery finds the same task.
 insert into public.private_deletion_tasks(igreja_id,receipt_id,source_id,storage_path,next_attempt_at)
 select p_tenant,v_id,id,storage_path,ready_at from (
  select distinct on(storage_path) id,storage_path,ready_at from (
   select a.id,a.storage_path,coalesce(a.lease_until,now()) as ready_at,0 priority
    from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
    a.id=any(v_inputs)
   union all
   select id,media_path,now(),1 from public.messages where igreja_id=p_tenant and conversation_id=any(v_conversations) and media_path is not null
  ) paths where storage_path is not null order by storage_path,priority
 ) objects;
 get diagnostics v_media = row_count;
 update public.private_deletion_receipts set counts=counts||jsonb_build_object('midias',v_media) where id=v_id;
 delete from public.cell_report_audio_inputs a where a.igreja_id=p_tenant and
  a.id=any(v_inputs);
 -- Clear the entire offer state atomically to satisfy its CHECK and both
 -- tenant-composite NO ACTION message FKs, independently of fallback triggers.
 update public.conversations set secretaria_oferta_estado=null,
  secretaria_oferta_message_id=null, secretaria_oferta_expira_em=null,
  secretaria_oferta_resposta_message_id=null
 where igreja_id=p_tenant and id=any(v_conversations);
 -- Explicit deletion also supports protected inbox composite NO ACTION FKs.
 delete from public.messages where igreja_id=p_tenant and conversation_id=any(v_conversations);
 delete from public.conversations where igreja_id=p_tenant and id=any(v_conversations);
 return v_id;
end $$;
commit;
-- ROLLBACK (contain/drain workers first; deleted content cannot be restored):
-- DROP FUNCTION public.private_summary_enqueue(uuid);
-- Restore private_delete_content from 20261019_090001 before dropping tables.
-- DROP TRIGGER private_summary_message_changed ON public.messages;
-- DROP TRIGGER private_summary_prayer_protected ON public.pedido_oracao_mensagem;
-- DROP TRIGGER private_summary_identity ON public.conversations;
-- DROP TRIGGER private_summary_membership ON public.celula_membro;
-- DROP FUNCTION public.private_summary_membership_changed();
-- DROP TRIGGER private_summary_person ON public.pessoas;
-- DROP FUNCTION public.private_summary_source_changed(),public.private_summary_identity_changed(),public.private_summary_correct(uuid,bigint,text,boolean);
-- DROP TABLE public.private_summary_sources,public.private_summary_tasks,public.private_conversation_summaries,public.private_summary_budget,public.private_summary_settings;
-- DROP FUNCTION public.private_summary_reader(uuid,uuid),public.private_summary_origin_valid(uuid,uuid,uuid),public.private_summary_worker(),public.private_summary_topic(text);
-- ALTER TABLE public.conversations DROP COLUMN private_summary_revision;
