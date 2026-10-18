-- Enviar PR 4: candidato tenant-bound; proposta versionada. Sem backfill de líderes.
set lock_timeout='2s';
alter table public.celula_solicitacao
 drop constraint celula_solicitacao_tipo_chk,
 add column candidato_id uuid,
 add column versao_proposta integer not null default 1 check(versao_proposta>0),
 add constraint celula_solicitacao_tipo_chk check(tipo in (
 'alterar_dia','alterar_horario','alterar_endereco','alterar_anfitriao',
 'alterar_auxiliar','transferir_membro','remover_membro','multiplicacao','nomear_lider')),
 add constraint nomeacao_celula_tenant_fk foreign key(igreja_id,celula_id)
 references public.celulas(igreja_id,id) on delete cascade not valid,
 add constraint nomeacao_candidato_tenant_fk foreign key(igreja_id,candidato_id)
 references public.pessoas(igreja_id,id) on delete cascade,
 add constraint nomeacao_payload_chk check (
   (tipo='nomear_lider' and candidato_id is not null
    and payload_proposto->>'novo_lider_id' is not null
    and payload_proposto->>'novo_lider_id'=candidato_id::text
    and payload_atual is not null and payload_atual ? 'lider_id')
   or (tipo<>'nomear_lider' and candidato_id is null));
-- Approved person deletion also removes its private nomination and event derivatives.
-- Existing table keeps its tenant RLS. No provider/database role can write
-- these sensitive requests directly; writes require the authenticated web API.
-- Owner backend connection remains tenant scoped by application and RLS context.
revoke all on public.celula_solicitacao from public,anon,service_role;
-- authenticated is the pinned backend tenant role. Preserve existing grants;
-- authorization remains checked server-side, with candidate/author segregation.
-- Rollback (after restoring callers and preserving all nomination history):
-- Do not discard requests or demote leaders as part of rollback.
-- alter table public.celula_solicitacao drop constraint nomeacao_payload_chk,
-- drop constraint nomeacao_celula_tenant_fk,
-- drop constraint nomeacao_candidato_tenant_fk, drop column candidato_id,
-- drop column versao_proposta;
-- Restore the previous type check only after archival of nomear_lider requests.
-- alter table public.celula_solicitacao drop constraint celula_solicitacao_tipo_chk,
-- add constraint celula_solicitacao_tipo_chk check(tipo in (
-- 'alterar_dia','alterar_horario','alterar_endereco','alterar_anfitriao',
-- 'alterar_auxiliar','transferir_membro','remover_membro','multiplicacao'));
-- Privileges revoked from service_role/public/anon must not be restored by rollback.
