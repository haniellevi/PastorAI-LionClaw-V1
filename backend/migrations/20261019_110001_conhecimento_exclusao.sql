-- Official document erasure, including linked official quotes in messages.
set local lock_timeout='2s';
do $$ begin
 if not exists(select 1 from pg_roles where rolname=current_user and (rolsuper or rolbypassrls)) then
  raise exception 'Migration owner requires BYPASSRLS';
 end if;
end $$;
-- Audit identifiers survive; content-derived fingerprints are erased atomically.
alter table public.conhecimento_operacoes drop constraint conhecimento_operacoes_igreja_id_documento_id_versao_id_fkey;
-- Keep insertion-time FK semantics, while existing audit IDs can outlive erasure.
create function public.conhecimento_validar_operacao() returns trigger
language plpgsql set search_path=pg_catalog as $$
begin
 if current_user='authenticated' and (new.igreja_id is distinct from public.current_igreja_id()
    or new.igreja_id is distinct from nullif(current_setting('app.tenant_igreja_id',true),'')::uuid) then
  raise exception 'Escopo editorial inválido' using errcode='42501';
 end if;
 perform id from public.conhecimento_versoes where igreja_id=new.igreja_id
 and documento_id=new.documento_id and id=new.versao_id for key share;
 if not found then raise exception 'Referência editorial inválida' using errcode='23503'; end if;
 return new;
end $$;
revoke all on function public.conhecimento_validar_operacao() from public,anon,authenticated,service_role;
create trigger conhecimento_operacao_referencia before insert on public.conhecimento_operacoes
 for each row execute function public.conhecimento_validar_operacao();

-- Knowledge follows the application's legacy NULL-as-active convention.
-- Keep private_deletion_admin() unchanged: private erasure has a separate contract.
create function public.conhecimento_exclusao_admin() returns boolean
language sql stable security definer set search_path=pg_catalog as $$
 select session_user not in ('authenticator','authenticated','anon') and exists(
  select 1 from public.app_users u join public.user_roles r on r.user_id=u.id and r.igreja_id=u.igreja_id
  where u.igreja_id=public.current_igreja_id() and (u.status is null or u.status='ativo') and r.papel='admin'
   and u.clerk_user_id=coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',
                              nullif(current_setting('request.jwt.claim.sub',true),'')))
$$;
revoke all on function public.conhecimento_exclusao_admin() from public,anon,authenticated,service_role;
grant execute on function public.conhecimento_exclusao_admin() to authenticated;

create table public.conhecimento_exclusoes (
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 operacao_id uuid not null, documento_id uuid not null, ator_id uuid not null,
 versoes bigint not null, trechos bigint not null,
 concluida_em timestamptz not null default clock_timestamp(),
 primary key(igreja_id,operacao_id), unique(igreja_id,documento_id),
 constraint conhecimento_exclusoes_ator_fk foreign key(igreja_id,ator_id)
 references public.app_users(igreja_id,id) on delete no action deferrable initially deferred
);
alter table public.conhecimento_exclusoes enable row level security;
alter table public.conhecimento_exclusoes force row level security;
create policy receipt_read on public.conhecimento_exclusoes for select to authenticated
 using(igreja_id=public.current_igreja_id()
 and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
 and public.conhecimento_exclusao_admin());
revoke all on public.conhecimento_exclusoes from public,anon,authenticated,service_role;
grant select on public.conhecimento_exclusoes to authenticated;

-- A receipt is also a tombstone: old requests cannot recreate the same identity.
create function public.conhecimento_impedir_recriacao() returns trigger
language plpgsql security definer set search_path=pg_catalog as $$
begin
 perform pg_advisory_xact_lock(hashtextextended('conhecimento-documento:'||new.igreja_id||':'||new.id,0));
 if exists(select 1 from public.conhecimento_exclusoes where igreja_id=new.igreja_id and documento_id=new.id) then
  raise exception 'Documento excluído não pode ser recriado' using errcode='23505';
 end if;
 return new;
end $$;
revoke all on function public.conhecimento_impedir_recriacao() from public,anon,authenticated,service_role;
create trigger conhecimento_documento_tombstone before insert on public.conhecimento_documentos
 for each row execute function public.conhecimento_impedir_recriacao();

create function public.conhecimento_guardar_exclusao() returns trigger
language plpgsql set search_path=pg_catalog as $$
declare did uuid;
begin
 if not exists(select 1 from public.igrejas where id=old.igreja_id) then return old; end if;
 if tg_table_name='conhecimento_documentos' then did:=old.id; else did:=old.documento_id; end if;
 if pg_trigger_depth()<>2
    or old.igreja_id is distinct from public.current_igreja_id()
    or not public.conhecimento_exclusao_admin()
    or current_user<>(select pg_get_userbyid(proowner) from pg_proc
      where oid='public.conhecimento_excluir_documento(uuid,uuid,uuid,uuid)'::regprocedure)
    or not exists(select 1 from public.conhecimento_exclusoes e
      where e.igreja_id=old.igreja_id and e.documento_id=
        did
      and e.operacao_id=nullif(current_setting('app.conhecimento_exclusao',true),'')::uuid) then
  raise exception 'Exclusão somente pela operação autenticada' using errcode='42501';
 end if;
 return old;
end $$;
revoke all on function public.conhecimento_guardar_exclusao() from public,anon,authenticated,service_role;
-- No UPDATE exemption: immutable snapshot trigger remains untouched.
create trigger conhecimento_exclusao_guard before delete on public.conhecimento_versoes
 for each row execute function public.conhecimento_guardar_exclusao();
create trigger conhecimento_documento_exclusao_guard before delete on public.conhecimento_documentos
 for each row execute function public.conhecimento_guardar_exclusao();

-- Only a nested receipt trigger can delete; direct DELETE cannot forge depth.
create function public.conhecimento_apagar_com_recibo() returns trigger
language plpgsql security definer set search_path=pg_catalog as $$
begin
 if new.igreja_id is distinct from public.current_igreja_id()
    or new.igreja_id is distinct from nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
    or not public.conhecimento_exclusao_admin()
    or not exists(select 1 from public.app_users u join public.user_roles r
       on r.igreja_id=u.igreja_id and r.user_id=u.id
       where u.igreja_id=new.igreja_id and u.id=new.ator_id and (u.status is null or u.status='ativo') and r.papel='admin'
       and u.clerk_user_id=coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',
                                  nullif(current_setting('request.jwt.claim.sub',true),''))) then
  raise exception 'Recibo exige administrador web da igreja' using errcode='42501';
 end if;
 perform set_config('app.conhecimento_exclusao',new.operacao_id::text,true);
 -- Internal version FKs reference one statement's entire deletion set.
 update public.conhecimento_documentos set rascunho_id=null,vigente_id=null where igreja_id=new.igreja_id and id=new.documento_id;
 delete from public.conhecimento_versoes where igreja_id=new.igreja_id and documento_id=new.documento_id;
 -- FK CASCADE removes chunks and their stored tsvector/GIN entries atomically.
 delete from public.conhecimento_documentos where igreja_id=new.igreja_id and id=new.documento_id;
 perform set_config('app.conhecimento_exclusao','',true);
 return new;
end $$;
revoke all on function public.conhecimento_apagar_com_recibo() from public,anon,authenticated,service_role;
create trigger conhecimento_recibo_apagar after insert on public.conhecimento_exclusoes
 for each row execute function public.conhecimento_apagar_com_recibo();

create function public.conhecimento_excluir_documento(p_tenant uuid,p_documento uuid,p_operacao uuid,p_ator uuid)
returns jsonb language plpgsql security definer set search_path=pg_catalog as $$
declare recibo public.conhecimento_exclusoes; nversoes bigint; ntrechos bigint; mensagens uuid[]; conversas uuid[];
begin
 if p_tenant is distinct from public.current_igreja_id()
    or p_tenant is distinct from nullif(current_setting('app.tenant_igreja_id',true),'')::uuid
    or not public.conhecimento_exclusao_admin() then
  raise exception 'Exige administrador web da igreja' using errcode='42501';
 end if;
 -- Lock live identity/role through commit, in the same order as the human service.
 perform u.id from public.app_users u join public.user_roles r
   on r.igreja_id=u.igreja_id and r.user_id=u.id
   where u.igreja_id=p_tenant and u.id=p_ator and (u.status is null or u.status='ativo') and r.papel='admin'
   and u.clerk_user_id=coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub',
                               nullif(current_setting('request.jwt.claim.sub',true),'')) for share of u,r;
 if not found then raise exception 'Ator web indisponível' using errcode='42501'; end if;
 perform pg_advisory_xact_lock(hashtextextended('conhecimento-excluir:'||p_tenant||':'||p_operacao,0));
 select * into recibo from public.conhecimento_exclusoes where igreja_id=p_tenant and operacao_id=p_operacao;
 if found then
  if recibo.documento_id<>p_documento or recibo.ator_id<>p_ator then
   raise exception 'Operação reutilizada' using errcode='23505';
  end if;
  return to_jsonb(recibo)||jsonb_build_object('estado','concluido');
 end if;
 perform pg_advisory_xact_lock(hashtextextended('conhecimento-documento:'||p_tenant||':'||p_documento,0));
 perform id from public.conhecimento_documentos where igreja_id=p_tenant and id=p_documento for update;
 if not found then return null; end if;
 select count(*) into nversoes from public.conhecimento_versoes where igreja_id=p_tenant and documento_id=p_documento;
 select count(*) into ntrechos from public.conhecimento_trechos c join public.conhecimento_versoes v
 on v.igreja_id=c.igreja_id and v.id=c.versao_id where v.igreja_id=p_tenant and v.documento_id=p_documento;
 -- Fingerprints must no longer serve as an oracle for erased payloads.
 update public.conhecimento_operacoes set fingerprint=repeat('0',64)
 where igreja_id=p_tenant and documento_id=p_documento;
 -- Capture original text/identity before redaction, under message locks.
 select coalesce(array_agg(m.id),'{}'::uuid[]),coalesce(array_agg(m.conversation_id),'{}'::uuid[])
 into mensagens,conversas from (
   select m.* from public.messages m
 where m.igreja_id=p_tenant and m.agent_privilege_context->>'kind'='conhecimento'
 and exists(select 1 from jsonb_array_elements(
   case when jsonb_typeof(m.agent_privilege_context->'fontes')='array'
     then m.agent_privilege_context->'fontes' else '[]'::jsonb end) f
   where f->>'documento_id'=p_documento::text or exists(
     select 1 from public.conhecimento_versoes v where v.igreja_id=p_tenant
     and v.documento_id=p_documento and v.id::text=f->>'versao_id')) for update
 ) m;
 -- Preview may contain an older quote, or a stale/truncated latest message.
 update public.conversations c set ultima_mensagem='[Conhecimento oficial excluído]'
 where c.igreja_id=p_tenant and c.id=any(conversas) and (
   exists(select 1 from public.messages m where m.igreja_id=p_tenant
     and m.conversation_id=c.id and m.id=any(mensagens) and m.texto=c.ultima_mensagem)
   or (select m.id from public.messages m where m.igreja_id=p_tenant
       and m.conversation_id=c.id order by m.criado_em desc,m.id desc limit 1)=any(mensagens));
 -- #526 may be installed later. Remove corrections too, which ordinary source
 -- invalidation intentionally retains. Sources cascade; its trigger clears jobs.
 if to_regclass('public.private_conversation_summaries') is not null then
   execute 'delete from public.private_conversation_summaries where igreja_id=$1 and conversation_id=any($2)'
     using p_tenant,conversas;
 end if;
 -- #525 sources are server-owned metadata; redact the complete composite quote.
 update public.messages m set texto='[Conhecimento oficial excluído]',
   agent_reply_state='ia_suprimida',
   agent_privilege_context=jsonb_build_object('kind','conhecimento','stage','excluido')
 where m.igreja_id=p_tenant and m.id=any(mensagens);
 insert into public.conhecimento_exclusoes(igreja_id,operacao_id,documento_id,ator_id,versoes,trechos)
 values(p_tenant,p_operacao,p_documento,p_ator,nversoes,ntrechos) returning * into recibo;
 return to_jsonb(recibo)||jsonb_build_object('estado','concluido');
end $$;
revoke all on function public.conhecimento_excluir_documento(uuid,uuid,uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.conhecimento_excluir_documento(uuid,uuid,uuid,uuid) to authenticated;
-- Rollback manual, callers stopped. Erased content is not recoverable here.
-- begin;
-- set local lock_timeout='2s';
-- lock table public.conhecimento_documentos,public.conhecimento_versoes,public.conhecimento_operacoes,public.conhecimento_exclusoes in access exclusive mode;
-- do $$ begin if exists(select 1 from public.conhecimento_exclusoes) then
-- raise exception 'Preservar recibos e auditoria; rollback indisponível'; end if; end $$;
-- drop trigger conhecimento_exclusao_guard on public.conhecimento_versoes;
-- drop trigger conhecimento_documento_exclusao_guard on public.conhecimento_documentos;
-- drop function public.conhecimento_guardar_exclusao();
-- drop trigger conhecimento_recibo_apagar on public.conhecimento_exclusoes;
-- drop function public.conhecimento_apagar_com_recibo();
-- drop function public.conhecimento_excluir_documento(uuid,uuid,uuid,uuid);
-- drop trigger conhecimento_documento_tombstone on public.conhecimento_documentos;
-- drop function public.conhecimento_impedir_recriacao();
-- drop table public.conhecimento_exclusoes;
-- drop function public.conhecimento_exclusao_admin();
-- drop trigger conhecimento_operacao_referencia on public.conhecimento_operacoes;
-- drop function public.conhecimento_validar_operacao();
-- alter table public.conhecimento_operacoes add foreign key(igreja_id,documento_id,versao_id) references public.conhecimento_versoes(igreja_id,documento_id,id);
-- commit;
