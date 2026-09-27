\set ON_ERROR_STOP on
begin;
create temporary table s2b_messages (
  igreja_id integer not null, conversation_id integer not null,
  id integer primary key, unique (igreja_id, conversation_id, id)
);
create temporary table s2b_conversations (
  igreja_id integer not null, id integer primary key,
  offer_state text, offer_id integer, response_id integer,
  foreign key (igreja_id, id, offer_id)
    references s2b_messages (igreja_id, conversation_id, id) on delete no action,
  foreign key (igreja_id, id, response_id)
    references s2b_messages (igreja_id, conversation_id, id) on delete no action,
  check ((offer_state is null and offer_id is null and response_id is null)
      or (offer_state = 'consumida' and offer_id is not null and response_id is not null))
);
alter table s2b_messages add foreign key (conversation_id)
  references s2b_conversations(id) on delete cascade;
create function pg_temp.s2b_cleanup() returns trigger language plpgsql as $$
begin
  update pg_temp.s2b_conversations set offer_state=null, offer_id=null, response_id=null
  where igreja_id=old.igreja_id and id=old.conversation_id
    and (offer_id=old.id or response_id=old.id);
  return old;
end $$;
create trigger s2b_cleanup before delete on s2b_messages
for each row execute function pg_temp.s2b_cleanup();
insert into s2b_conversations(igreja_id,id) values (1,11),(2,22);
insert into s2b_messages values (1,11,111),(1,11,112),(2,22,221),(2,22,222);
update s2b_conversations set offer_state='consumida',offer_id=111,response_id=112 where id=11;
update s2b_conversations set offer_state='consumida',offer_id=221,response_id=222 where id=22;
do $$ begin
  begin
    update s2b_conversations set offer_id=221 where id=11;
    raise exception 'cross-tenant aceito indevidamente';
  exception when foreign_key_violation then null; end;
end $$;
delete from s2b_messages where id=111;
do $$ begin
  if exists(select 1 from s2b_conversations where id=11 and offer_state is not null)
    then raise exception 'cleanup falhou'; end if;
  if not exists(select 1 from s2b_conversations where id=22 and offer_state='consumida')
    then raise exception 'tenant B alterado'; end if;
end $$;
delete from s2b_conversations where id=22;
do $$ begin
  if exists(select 1 from s2b_messages where conversation_id=22)
    then raise exception 'cascade falhou'; end if;
end $$;
delete from s2b_messages where igreja_id=1;
delete from s2b_conversations where igreja_id=1;
select 'S2B_NO_ACTION_TRIGGER_PROOF_OK' as result;
rollback;
