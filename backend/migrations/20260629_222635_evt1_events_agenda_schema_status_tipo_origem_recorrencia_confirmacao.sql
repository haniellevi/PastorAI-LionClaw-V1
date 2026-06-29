-- ============================================================================
-- PastorAI — Migration 20260629_222635 — EVT-1: schema da Agenda de Eventos
-- RF-35/RF-39 · SPEC "Módulo Agenda de Eventos" · delta-049/050/051
-- ADR: docs/design/AGENDA-EVENTOS-EVT0-decisao.md
--
-- Estende a tabela `events` existente (NÃO cria tabela paralela — regra #4 / §2
-- do ADR) para suportar o MVP EVT-1..5: status, tipo, origem, recorrência por
-- dia da semana e campos de confirmação/comunicação (persistidos, sem envio).
--
-- Sem ALTER TYPE ... ADD VALUE (só CREATE TYPE novo) => roda em transação.
-- Idempotente: enums via DO/duplicate_object; colunas/constraints via IF NOT
-- EXISTS / guard. RLS de `events` (tenant_isolation FOR ALL em igreja_id, ver
-- 0003) já cobre as colunas novas — policy é por linha, não por coluna; nada a
-- alterar aqui. Não toca BYPASSRLS / set_tenant_context.
--
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ============================================================================

begin;

-- ----------------------------------------------------------------------------
-- Enums (idempotentes via DO blocks — padrão 0001)
-- ----------------------------------------------------------------------------

-- events.status: evento manual nasce 'confirmado'; Google import (EVT-6) entra
-- 'a_confirmar'. Antes do EVT-6, 'a_confirmar' só por seed/teste (§8 do ADR).
do $$ begin
  create type event_status as enum ('confirmado', 'a_confirmar');
exception when duplicate_object then null; end $$;

-- events.tipo: categorias iniciais da spec (cor por tipo na UI). Enum segue o
-- padrão do projeto (20+ enums em 0001); valores novos entram via ALTER TYPE.
do $$ begin
  create type event_tipo as enum ('culto', 'reuniao', 'celula', 'especial', 'conferencia');
exception when duplicate_object then null; end $$;

-- events.origem: distingue criação manual de import do Google (EVT-6).
do $$ begin
  create type event_origem as enum ('manual', 'google');
exception when duplicate_object then null; end $$;

-- events.recorrencia: 'pontual' = data específica (visões Mês/Ano);
-- 'semanal' = toda semana no dia_semana (visão Semana). §3 do ADR.
do $$ begin
  create type event_recorrencia as enum ('pontual', 'semanal');
exception when duplicate_object then null; end $$;

-- ----------------------------------------------------------------------------
-- Colunas novas em events
-- ----------------------------------------------------------------------------

-- status / origem / recorrencia: NOT NULL com default => backfill automático
-- das linhas existentes (status='confirmado', origem='manual', recorrencia='pontual').
alter table events add column if not exists status      event_status      not null default 'confirmado';
alter table events add column if not exists origem      event_origem      not null default 'manual';
alter table events add column if not exists recorrencia event_recorrencia not null default 'pontual';

-- tipo: NULLABLE — eventos legados não têm categoria conhecida; não fabricamos uma.
alter table events add column if not exists tipo event_tipo;

-- dia_semana: 0=domingo .. 6=sábado, só para recorrencia='semanal'.
alter table events add column if not exists dia_semana smallint;

-- Campos de confirmação/comunicação (EVT-5 preenche; aqui só persistem, sem envio).
alter table events add column if not exists publico_alvo         text[];
alter table events add column if not exists antecedencia_horas   integer;
alter table events add column if not exists mensagem_confirmacao text;
alter table events add column if not exists confirmado_em        timestamptz;
alter table events add column if not exists confirmado_por       uuid references app_users(id) on delete set null;

-- `data` deixa de ser NOT NULL: eventos semanais não têm data específica.
-- Loosening seguro — toda linha existente já tem data preenchida.
alter table events alter column data drop not null;

-- ----------------------------------------------------------------------------
-- Constraints (evitam estado impossível; ver §4/§8 do ADR)
-- ----------------------------------------------------------------------------

-- Coerência recorrência × data × dia_semana:
--   pontual  -> data obrigatória, sem dia_semana
--   semanal  -> dia_semana obrigatório (data opcional p/ data de início)
-- Validada na hora: todas as linhas existentes são pontuais com data preenchida.
do $$ begin
  alter table events add constraint events_recorrencia_chk check (
    (recorrencia = 'pontual' and data is not null and dia_semana is null)
    or (recorrencia = 'semanal' and dia_semana is not null)
  );
exception when duplicate_object then null; end $$;

-- dia_semana no intervalo válido.
do $$ begin
  alter table events add constraint events_dia_semana_chk
    check (dia_semana is null or dia_semana between 0 and 6);
exception when duplicate_object then null; end $$;

-- antecedência não-negativa.
do $$ begin
  alter table events add constraint events_antecedencia_chk
    check (antecedencia_horas is null or antecedencia_horas >= 0);
exception when duplicate_object then null; end $$;

-- hora no formato HH:MM (24h). NOT VALID: protege linhas novas/atualizadas sem
-- escanear/rejeitar dados legados que possam ter `hora` inválida (Google sync
-- desligado podia persistir texto livre — §6 do ADR / req. EVT-1). A validação
-- no payload é reforçada no schema Pydantic do router (HH:MM).
do $$ begin
  alter table events add constraint events_hora_formato_chk
    check (hora is null or hora ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$') not valid;
exception when duplicate_object then null; end $$;

commit;
