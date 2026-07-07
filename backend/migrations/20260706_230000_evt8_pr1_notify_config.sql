-- ============================================================================
-- PastorAI — Migration 20260706_230000 — EVT-8 PR1: notificação do evento
-- RF-35/RF-39 · SPEC "Módulo Agenda de Eventos"
-- ADR: docs/design/AGENDA-EVENTOS-EVT8-notificacao-evento.md
--
-- Configuração da notificação do PRÓPRIO evento (captura da intenção; o envio
-- real é EVT-9). NÃO confundir com agenda_alert_recipients (EVT-7 PR2 = aviso
-- interno da equipe, config global da igreja).
--
-- 1) events: colunas de agendamento da notificação
--    - notificar_em            timestamptz  quando disparar (D4, normalizado)
--    - notificacao_enviada_em  timestamptz  idempotência do envio agendado
--                                            (NULL + notificar_em = pendente/futuro)
--    - canal                   text         WhatsApp no MVP (D6)
-- 2) event_notify_targets: seleção INDIVIDUAL (D3) — contatos vindos das
--    conversas do WhatsApp (pessoa_id preferido; telefone canônico como fallback).
--
-- Transacional e idempotente (IF NOT EXISTS). RLS por tenant no padrão das demais
-- tabelas (current_igreja_id(), como 0003 / calendar_sync / agenda_alert_recipients).
-- Não toca BYPASSRLS / set_tenant_context.
--
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ============================================================================

begin;

-- 1) events — agendamento da notificação do evento (EVT-8 PR1).
alter table events add column if not exists notificar_em           timestamptz;
alter table events add column if not exists notificacao_enviada_em timestamptz;
alter table events add column if not exists canal                  text;

-- Canal restrito ao MVP (WhatsApp). NOT VALID: não varre as linhas legadas (todas
-- NULL agora); linhas novas já são checadas. Amplia-se a lista quando houver outro
-- canal (EVT-9+).
alter table events drop constraint if exists events_canal_chk;
alter table events add constraint events_canal_chk
  check (canal is null or canal in ('whatsapp')) not valid;

-- 2) event_notify_targets — seleção individual da notificação (EVT-8 PR1, D3).
create table if not exists event_notify_targets (
  id         uuid primary key default gen_random_uuid(),
  event_id   uuid not null references events(id)  on delete cascade,
  igreja_id  uuid not null references igrejas(id) on delete cascade,
  pessoa_id  uuid references pessoas(id) on delete set null,
  telefone   text,
  created_at timestamptz not null default now(),
  -- Pelo menos um identificador (pessoa OU telefone). Sem digitação livre: o
  -- backend só aceita pessoa/telefone que exista em `conversations` do tenant.
  constraint event_notify_targets_identity_chk
    check (pessoa_id is not null or telefone is not null)
);

comment on table event_notify_targets is
  'Contatos individuais da notificação de um evento (EVT-8 PR1); envio real é EVT-9.';

create index if not exists event_notify_targets_event_idx
  on event_notify_targets (event_id);
create index if not exists event_notify_targets_igreja_idx
  on event_notify_targets (igreja_id);

-- Um mesmo contato não entra duas vezes no mesmo evento (dedup por identidade).
-- Índices parciais: um p/ pessoa vinculada, outro p/ telefone puro.
create unique index if not exists event_notify_targets_event_pessoa_uq
  on event_notify_targets (event_id, pessoa_id) where pessoa_id is not null;
create unique index if not exists event_notify_targets_event_tel_uq
  on event_notify_targets (event_id, telefone) where telefone is not null;

-- RLS por tenant (mesmo padrão de 0003 / calendar_sync / agenda_alert_recipients).
alter table event_notify_targets enable row level security;
drop policy if exists tenant_isolation on event_notify_targets;
create policy tenant_isolation on event_notify_targets
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

commit;
