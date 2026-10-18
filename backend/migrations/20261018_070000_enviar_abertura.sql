-- Enviar PR 5: abertura sem origem. Nenhum backfill ou alteração de líderes.
set lock_timeout='2s';
alter table public.celula_solicitacao
 alter column celula_id drop not null,
 drop constraint celula_solicitacao_tipo_chk,
 drop constraint nomeacao_payload_chk,
 add constraint celula_solicitacao_tipo_chk check(tipo in (
 'alterar_dia','alterar_horario','alterar_endereco','alterar_anfitriao',
 'alterar_auxiliar','transferir_membro','remover_membro','multiplicacao','nomear_lider','abrir_celula')),
 add constraint abertura_origem_chk check ((tipo='abrir_celula') = (celula_id is null)),
 add constraint nomeacao_payload_chk check (
   (tipo in ('nomear_lider','abrir_celula') and candidato_id is not null
    and payload_proposto->>'novo_lider_id' is not null
    and payload_proposto->>'novo_lider_id'=candidato_id::text
    and (tipo='abrir_celula' or (payload_atual is not null and payload_atual ? 'lider_id')))
   or (tipo not in ('nomear_lider','abrir_celula') and candidato_id is null));
-- Existing composite (igreja_id,celula_id) and candidate FKs remain in force;
-- only opening may omit origin. Existing tenant RLS and event audit preserved.
revoke all on public.celula_solicitacao from public,anon,service_role;
-- Rollback: restore callers first; preserve opening requests/events externally
-- through the approved privacy procedure before restoring NOT NULL/type checks.
-- Never delete opening history or demote leaders to make rollback pass.
-- alter table public.celula_solicitacao drop constraint abertura_origem_chk;
-- alter table public.celula_solicitacao alter column celula_id set not null;
-- Restore celula_solicitacao_tipo_chk and nomeacao_payload_chk from
-- 20261018_060000_enviar_nomeacao.sql only after preserving opening history.
-- Do not restore revoked provider privileges.
