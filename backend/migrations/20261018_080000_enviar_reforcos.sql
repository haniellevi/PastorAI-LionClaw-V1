-- Enviar P2: event audit stays private; tenant FK fully checked.
set lock_timeout = '2s';
revoke all on public.celula_solicitacao_evento from public, anon, service_role;
-- Preserve authenticated grants used by the tenant-scoped backend.
alter table public.celula_solicitacao validate constraint nomeacao_celula_tenant_fk;
-- Rollback: restore callers first. Preserve requests, events and tenant isolation.
-- Validation does not change enforcement; prefer leaving the validated FK in place.
-- If the previous validation state is required (same tenant FK still enforced):
-- alter table public.celula_solicitacao drop constraint nomeacao_celula_tenant_fk;
-- alter table public.celula_solicitacao add constraint nomeacao_celula_tenant_fk
-- foreign key (igreja_id,celula_id) references public.celulas(igreja_id,id)
-- on delete cascade not valid;
-- Never restore provider/public privileges or delete audit history in rollback.
