-- ============================================================================
-- PastorAI — Migration 20260701_193000 — EVT-7 PR2: destinatários de alerta
-- RF-35/RF-39 · SPEC "Módulo Agenda de Eventos"
-- ADR: docs/design/AGENDA-EVENTOS-EVT7-destinatarios-alerta.md
--
-- Cria `agenda_alert_recipients`: config explícita, opt-in, de quem recebe os
-- avisos internos da Agenda por WhatsApp — por igreja, independente de papel e de
-- AppUser.pessoa_id (mata a "dupla exclusão" que zerava os destinatários; ver ADR).
-- `telefone` guarda a chave canônica só-dígitos (mesma normalização de
-- conversations.telefone). Só destinatários `ativo=true` recebem.
--
-- CREATE/índices são transacionais. RLS por tenant como as demais tabelas
-- (current_igreja_id(), mesmo padrão de 0003 / calendar_sync). Idempotente via
-- IF NOT EXISTS. Não toca BYPASSRLS / set_tenant_context.
--
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ============================================================================

begin;

create table if not exists agenda_alert_recipients (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null references igrejas(id) on delete cascade,
  nome text not null,
  telefone text not null,
  ativo boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

comment on table agenda_alert_recipients is
  'Destinatários de avisos internos da Agenda por WhatsApp, por igreja (EVT-7 PR2).';

create index if not exists agenda_alert_recipients_igreja_idx
  on agenda_alert_recipients (igreja_id);

-- Um telefone ATIVO só entra uma vez por igreja (evita envio duplicado). Índice
-- parcial: inativos com o mesmo número não conflitam (histórico preservado).
create unique index if not exists agenda_alert_recipients_igreja_tel_ativo_uq
  on agenda_alert_recipients (igreja_id, telefone)
  where ativo;

-- RLS por tenant (mesmo padrão de 0003 / calendar_sync): só a própria igreja.
alter table agenda_alert_recipients enable row level security;
drop policy if exists tenant_isolation on agenda_alert_recipients;
create policy tenant_isolation on agenda_alert_recipients
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

commit;
