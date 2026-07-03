-- ============================================================================
-- PastorAI — Migration 20260703_123803 — Células PR1: schema/base de célula
-- Fontes: docs/design/PLANO-IMPLEMENTACAO-CELULAS.md (§5, PR1) +
--         docs/design/CELULAS-DECISOES-FINAIS.md (3.1–3.6).
--
-- (1) EVOLUI a tabela `celulas` (JÁ EXISTE em 0002) — NÃO recria — com os campos
--     que faltavam: sensíveis (anfitriao_id, auxiliar_id, endereco, horario; dia
--     e horário são sensíveis por 3.2) e leves (link_grupo, link_localizacao,
--     mensagem_convite). A policy RLS vigente de `celulas` já cobre colunas novas.
-- (2) CRIA a tabela filha `celula_membro` — vínculo CANÔNICO pessoa↔célula (Q1).
--     `pessoas.celula_id` fica como espelho legado, sem remoção (aditivo).
--     Regra "1 pessoa → 1 célula ativa" via índice único parcial `where ativo`.
--     RLS por tenant própria (não herda por FK).
--
-- Q2: anfitrião/auxiliar são FKs sensíveis EM `celulas` (fonte de verdade);
-- `celula_membro.papel` é rótulo do vínculo, não substitui esses campos.
--
-- CREATE/índices transacionais + idempotente (if not exists / DO block / drop
-- policy if exists). Não toca BYPASSRLS / set_tenant_context / multiplicacoes.
-- Aplicar manualmente no Supabase (DEV primeiro), em ordem de nome de arquivo.
-- ============================================================================

begin;

-- ----------------------------------------------------------------------------
-- (1) celulas: campos sensíveis (3.2) + leves
-- ----------------------------------------------------------------------------
alter table celulas add column if not exists anfitriao_id uuid
  references pessoas(id) on delete set null;
alter table celulas add column if not exists auxiliar_id uuid
  references pessoas(id) on delete set null;
alter table celulas add column if not exists endereco text;
alter table celulas add column if not exists horario text;
alter table celulas add column if not exists link_grupo text;
alter table celulas add column if not exists link_localizacao text;
alter table celulas add column if not exists mensagem_convite text;

-- horario no formato HH:MM (24h). NOT VALID: não escaneia/rejeita linhas legadas,
-- só valida inserts/updates novos (mesmo padrão de events.hora em EVT-1).
do $$ begin
  alter table celulas add constraint celulas_horario_chk
    check (horario is null or horario ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$') not valid;
exception when duplicate_object then null; end $$;

-- ----------------------------------------------------------------------------
-- (2) celula_membro: vínculo canônico pessoa↔célula
-- ----------------------------------------------------------------------------
-- papel do vínculo (rótulo). Anfitrião/auxiliar "de verdade" da célula são as FKs
-- sensíveis acima (Q2); aqui é só a função da pessoa dentro da célula.
do $$ begin
  create type celula_membro_papel as enum ('membro', 'auxiliar', 'anfitriao');
exception when duplicate_object then null; end $$;

create table if not exists celula_membro (
  id          uuid primary key default gen_random_uuid(),
  igreja_id   uuid not null references igrejas(id) on delete cascade,
  celula_id   uuid not null references celulas(id) on delete cascade,
  pessoa_id   uuid not null references pessoas(id) on delete cascade,
  papel       celula_membro_papel not null default 'membro',
  ativo       boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz
);

comment on table celula_membro is
  'Vínculo canônico pessoa<->célula (Células PR1). pessoas.celula_id fica como espelho legado (Q1).';

create index if not exists celula_membro_igreja_idx on celula_membro (igreja_id);
create index if not exists celula_membro_celula_idx on celula_membro (celula_id);
create index if not exists celula_membro_pessoa_idx on celula_membro (pessoa_id);

-- Regra "1 pessoa -> 1 célula ATIVA" por igreja. Índice parcial: vínculos
-- inativos (histórico) não conflitam.
create unique index if not exists celula_membro_pessoa_ativa_uq
  on celula_membro (igreja_id, pessoa_id) where ativo;

-- RLS por tenant (mesmo padrão de 0003 / agenda_alert_recipients): só a própria
-- igreja. A tabela filha carrega igreja_id próprio + policy própria (não herda
-- por FK).
alter table celula_membro enable row level security;
drop policy if exists tenant_isolation on celula_membro;
create policy tenant_isolation on celula_membro
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

commit;
