-- ============================================================================
-- PastorAI — Migration 20260623_122044_calendar_sync_oauth_por_igreja
-- Módulo de Eventos, Fase 1: conectar a agenda Google existente da igreja.
-- Tabela 1:1 por igreja com os tokens OAuth (cifrados em app, via Fernet) e o
-- calendar_id escolhido. Colunas de sync_token / watch-channel entram nas
-- Fases 3/4. RLS por tenant como as demais tabelas (current_igreja_id()).
--
-- ADD/CREATE é transacional. Aplicar manualmente no Supabase, em ordem de nome.
-- ============================================================================

begin;

create table if not exists calendar_sync (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null unique references igrejas(id) on delete cascade,
  google_calendar_id text,
  refresh_token_encrypted text,
  access_token_encrypted text,
  access_token_expira_em timestamptz,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

comment on table calendar_sync is
  'OAuth + estado de sync do Google Calendar por igreja (módulo de eventos F1).';

-- RLS por tenant (mesmo padrão de 0003): só enxerga/escreve a própria igreja.
alter table calendar_sync enable row level security;
drop policy if exists tenant_isolation on calendar_sync;
create policy tenant_isolation on calendar_sync
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

commit;
