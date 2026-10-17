-- G12 PR2: real cell visit evidence; manual panel classification is audited.
-- No backfill, decision, consolidation, queue creation or external effects.
begin;
set local lock_timeout = '2s';
create unique index if not exists visitante_tenant_meeting_id
 on public.celula_visitante(igreja_id,reuniao_id,id);
create table if not exists public.evento_visita (
 id uuid primary key,
 igreja_id uuid not null,
 pessoa_id uuid not null,
 reuniao_id uuid,
 visitante_id uuid,
 registrado_por uuid not null,
 tipo text not null,
 origem text not null,
 data_ocorrencia timestamptz not null,
 data_registro timestamptz not null default now(),
 unique(igreja_id,id),
 constraint visit_person_meeting_once unique(igreja_id,pessoa_id,reuniao_id),
 foreign key(igreja_id,pessoa_id) references public.pessoas(igreja_id,id) on delete cascade,
 foreign key(igreja_id,reuniao_id) references public.celula_reuniao(igreja_id,id) on delete cascade,
 foreign key(igreja_id,reuniao_id,visitante_id) references public.celula_visitante(igreja_id,reuniao_id,id) on delete cascade,
 foreign key(igreja_id,registrado_por) references public.app_users(igreja_id,id) deferrable initially deferred,
 check((tipo='visita_celula' and origem='painel_lider' and reuniao_id is not null and visitante_id is not null)
    or (tipo='manual_painel' and origem='painel_pipeline' and reuniao_id is null and visitante_id is null)),
 check(data_ocorrencia <= data_registro)
);

-- Invoker helpers reuse the authenticated server JWT and existing RBAC.
create or replace function public.visit_actor() returns uuid language sql stable as $$
 select id from public.app_users where igreja_id=public.current_igreja_id()
 and clerk_user_id=coalesce(nullif(current_setting('request.jwt.claim.sub',true),''),
   nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub')
 and (status is null or status='ativo') limit 1
$$;
create or replace function public.visit_role(roles text[]) returns boolean language sql stable as $$
 select exists(select 1 from public.user_roles where igreja_id=public.current_igreja_id()
 and user_id=public.visit_actor() and papel=any(roles))
$$;
create or replace function public.visit_leads(meeting uuid) returns boolean language sql stable as $$
 select exists(select 1 from public.celula_reuniao r join public.celulas c
 on c.id=r.celula_id and c.igreja_id=r.igreja_id join public.app_users u
 on u.igreja_id=c.igreja_id and u.pessoa_id=c.lider_id
 where r.id=meeting and r.igreja_id=public.current_igreja_id()
 and u.id=public.visit_actor() and c.ativo)
$$;
alter table public.evento_visita enable row level security;
alter table public.evento_visita force row level security;
create policy visit_read on public.evento_visita for select to authenticated
 using (igreja_id=public.current_igreja_id() and (
   coalesce(nullif(current_setting('request.jwt.claim.sub',true),''), nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub') is null or public.visit_role(array['admin','pastor','lider_g12','lider_consol'])
   or (public.visit_role(array['admin','pastor','lider_celula']) and public.visit_leads(reuniao_id))));
create policy visit_insert on public.evento_visita for insert to authenticated
 with check(igreja_id=public.current_igreja_id() and registrado_por=public.visit_actor()
 and data_ocorrencia <= statement_timestamp()
 and ((tipo='manual_painel' and public.visit_role(array['admin','pastor','lider_g12','lider_consol']))
 or (tipo='visita_celula' and public.visit_role(array['admin','pastor','lider_celula']) and public.visit_leads(reuniao_id)
 and exists(select 1 from public.celula_reuniao r where r.id=evento_visita.reuniao_id and r.igreja_id=evento_visita.igreja_id
   and r.status <> 'cancelada' and r.relatorio_status <> 'enviado'
   and ((r.data + coalesce(nullif(r.hora,''),'00:00')::time) at time zone 'America/Sao_Paulo') <= statement_timestamp()
   and data_ocorrencia = ((r.data + coalesce(nullif(r.hora,''),'00:00')::time) at time zone 'America/Sao_Paulo')))));
create policy visit_delete on public.evento_visita for delete to authenticated
 using(igreja_id=public.current_igreja_id() and public.visit_role(array['admin']));
revoke all on public.evento_visita from public, authenticated;
grant select, insert, delete on public.evento_visita to authenticated;
-- Immutable evidence: no UPDATE grant or policy. Person offboarding deletes it.
commit;
-- Rollback: preserve approved records before removing the schema; no automatic
-- downgrades or re-interpretation of existing people.
-- drop table public.evento_visita;
-- drop function public.visit_leads(uuid);
-- drop function public.visit_role(text[]);
-- drop function public.visit_actor();
-- drop index public.visitante_tenant_meeting_id;
