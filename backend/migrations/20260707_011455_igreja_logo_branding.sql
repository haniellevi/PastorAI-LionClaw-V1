-- ============================================================================
-- PastorAI — Migration 20260707_011455_igreja_logo_branding
-- Missão 4 (Branding / Identidade Visual por igreja) — PR1 backend.
-- Spec: docs/design/BRANDING-IDENTIDADE-VISUAL-IGREJA.md (D1).
--
-- Adiciona igrejas.logo_path (ponteiro para o objeto no bucket público
-- `church-logos`; o binário NUNCA entra no Postgres) e abre o caminho de
-- escrita do tenant, hoje inexistente: a RLS de `igrejas` tem policy só de
-- SELECT (0003), então um UPDATE sob `SET LOCAL ROLE authenticated` seria um
-- no-op silencioso de 0 linhas. A policy nova restringe o UPDATE à própria
-- linha e o GRANT POR COLUNA garante que o tenant só consegue alterar
-- logo_path — nome/status/plano/dono_id não são graváveis diretamente pelo
-- tenant. (plano continua sendo atualizado pelo trigger de auto-upgrade, que
-- por isso é elevado a SECURITY DEFINER abaixo; o master escreve via service
-- role / BYPASSRLS.)
--
-- ⚠️ O bucket `church-logos` (público) é criado MANUALMENTE no Supabase em
-- DEV e PROD — fora de migration. Ver runbook na spec (§6).
--
-- Idempotente e transacional; não altera dados existentes.
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ============================================================================

begin;

alter table igrejas
  add column if not exists logo_path text null;

comment on column igrejas.logo_path is
  'Missão 4: path da logo customizada no bucket público church-logos ({igreja_id}/logo-*.ext). NULL = sem logo (a UI mostra o nome da igreja como fallback).';

-- Escrita do tenant na própria linha (a leitura já é coberta por
-- igrejas_self_select, da 0003). drop+create para idempotência.
drop policy if exists igrejas_self_update on igrejas;
create policy igrejas_self_update on igrejas
  for update
  using (id = current_igreja_id())
  with check (id = current_igreja_id());

-- Grant por coluna: mesmo com a policy de UPDATE, o role authenticated só
-- pode escrever logo_path. (revoke+grant são idempotentes por natureza.)
revoke update on igrejas from authenticated;
grant update (logo_path) on igrejas to authenticated;

-- O revoke acima retira o UPDATE table-wide que o `authenticated` tinha por
-- padrão. Isso quebraria o trigger de auto-upgrade de plano
-- (fn_subscription_autoupgrade, 0004): ele faz `update igrejas set plano` a
-- partir do INSERT de uma pessoa, que roda sob role `authenticated` — e agora
-- `plano` está fora do grant por coluna, então o UPDATE falharia com
-- "permission denied" (42501) e ABORTARIA o cadastro da pessoa ao estourar o
-- limite. Dar `grant update(plano)` ao tenant resolveria, mas permitiria o
-- tenant escalar o próprio plano de billing pela policy nova — o oposto da
-- intenção. Então elevamos o trigger para SECURITY DEFINER: ele passa a rodar
-- como o owner (BYPASSRLS + grants plenos), o auto-upgrade volta a funcionar
-- (e passa a refletir em igrejas.plano, corrigindo um no-op silencioso que já
-- existia sob a RLS SELECT-only) sem conceder `plano` ao tenant. Seguro:
-- search_path já está pinado em `public, pg_temp` (0006) e a função filtra
-- tudo por new.igreja_id (a igreja da pessoa inserida sob o próprio tenant).
alter function public.fn_subscription_autoupgrade() security definer;

commit;
