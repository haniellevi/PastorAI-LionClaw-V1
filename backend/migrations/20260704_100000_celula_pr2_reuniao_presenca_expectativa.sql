-- ============================================================================
-- PastorAI — Migration 20260704_100000 — Células PR2: reunião / presença /
-- expectativa de visitante.
-- Fontes: SPEC §2.1 (Células PR2) + DB-DEC-04 (todas as FKs novas ON DELETE
--         CASCADE) + docs/design/CELULAS-DECISOES-FINAIS.md.
--
-- 100% ADITIVO sobre o PR1: cria 3 tabelas NOVAS e NÃO toca em nenhuma tabela
-- do PR1 (celulas, pessoas, celula_membro, multiplicacoes) — sem ALTER/DROP.
--
--   (1) celula_reuniao          — ocorrência materializada da célula (uma reunião)
--   (2) celula_presenca         — presença por pessoa em uma reunião
--   (3) celula_expectativa_visitante — visitantes esperados p/ uma reunião
--
-- Cada tabela carrega igreja_id PRÓPRIO (a RLS não herda por FK) e tem sua
-- própria policy tenant_isolation cobrindo ALL — padrão idêntico ao PR1
-- (20260703_123803) e a agenda_alert_recipients. Sem triggers: updated_at é
-- gerenciado pela aplicação. Sem seed.
--
-- CREATE/índices transacionais + idempotente (if not exists / DO block / drop
-- policy if exists). Não toca BYPASSRLS / set_tenant_context. Aplicar
-- manualmente no Supabase (DEV primeiro), em ordem de nome de arquivo.
-- ============================================================================

begin;

-- ----------------------------------------------------------------------------
-- (1) celula_reuniao: ocorrência materializada da célula
-- ----------------------------------------------------------------------------
create table if not exists celula_reuniao (
  id          uuid primary key default gen_random_uuid(),
  igreja_id   uuid not null references igrejas(id) on delete cascade,
  celula_id   uuid not null references celulas(id) on delete cascade,
  data        date not null,
  hora        text,
  tema        text,
  status      text not null default 'planejada',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz
);

comment on table celula_reuniao is
  'Ocorrência materializada de uma célula (Células PR2). igreja_id próprio + RLS própria (não herda por FK). celula_id ON DELETE CASCADE (DB-DEC-04).';

-- hora no formato HH:MM (24h). NOT VALID: não escaneia/rejeita linhas legadas,
-- só valida inserts/updates novos (mesmo padrão de celulas_horario_chk no PR1
-- e de events.hora em EVT-1).
do $$ begin
  alter table celula_reuniao add constraint celula_reuniao_hora_chk
    check (hora is null or hora ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$') not valid;
exception when duplicate_object then null; end $$;

-- status restrito ao ciclo de vida da reunião.
do $$ begin
  alter table celula_reuniao add constraint celula_reuniao_status_chk
    check (status in ('planejada', 'confirmada', 'realizada', 'cancelada'));
exception when duplicate_object then null; end $$;

-- Uma reunião por (igreja, célula, data, hora). coalesce(hora,'') evita que
-- duas reuniões com hora NULL na mesma data colidam de forma errada com o NULL
-- do índice (NULL nunca é igual a NULL).
create unique index if not exists celula_reuniao_slot_uq
  on celula_reuniao (igreja_id, celula_id, data, coalesce(hora, ''));

create index if not exists celula_reuniao_igreja_idx
  on celula_reuniao (igreja_id);
create index if not exists celula_reuniao_igreja_celula_idx
  on celula_reuniao (igreja_id, celula_id);
create index if not exists celula_reuniao_igreja_celula_data_idx
  on celula_reuniao (igreja_id, celula_id, data);

-- RLS por tenant (mesmo padrão do PR1 / agenda_alert_recipients).
alter table celula_reuniao enable row level security;
drop policy if exists tenant_isolation on celula_reuniao;
create policy tenant_isolation on celula_reuniao
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

-- ----------------------------------------------------------------------------
-- (2) celula_presenca: presença por pessoa em uma reunião
-- ----------------------------------------------------------------------------
create table if not exists celula_presenca (
  id          uuid primary key default gen_random_uuid(),
  igreja_id   uuid not null references igrejas(id) on delete cascade,
  reuniao_id  uuid not null references celula_reuniao(id) on delete cascade,
  pessoa_id   uuid not null references pessoas(id) on delete cascade,
  estado      text not null,
  origem      text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz
);

comment on table celula_presenca is
  'Presença de uma pessoa em uma reunião de célula (Células PR2). reuniao_id/pessoa_id ON DELETE CASCADE (DB-DEC-04).';

-- estado da presença: confirmada (aguardada) / compareceu / ausente.
do $$ begin
  alter table celula_presenca add constraint celula_presenca_estado_chk
    check (estado in ('confirmada', 'compareceu', 'ausente'));
exception when duplicate_object then null; end $$;

-- Uma linha de presença por (igreja, reunião, pessoa).
create unique index if not exists celula_presenca_pessoa_uq
  on celula_presenca (igreja_id, reuniao_id, pessoa_id);

create index if not exists celula_presenca_igreja_idx
  on celula_presenca (igreja_id);
create index if not exists celula_presenca_igreja_reuniao_idx
  on celula_presenca (igreja_id, reuniao_id);

alter table celula_presenca enable row level security;
drop policy if exists tenant_isolation on celula_presenca;
create policy tenant_isolation on celula_presenca
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

-- ----------------------------------------------------------------------------
-- (3) celula_expectativa_visitante: visitantes esperados p/ uma reunião
-- ----------------------------------------------------------------------------
-- SEM UNIQUE: a mesma pessoa pode registrar vários visitantes esperados para a
-- mesma reunião (uma linha por visitante), e não há chave natural aqui.
create table if not exists celula_expectativa_visitante (
  id                  uuid primary key default gen_random_uuid(),
  igreja_id           uuid not null references igrejas(id) on delete cascade,
  reuniao_id          uuid not null references celula_reuniao(id) on delete cascade,
  pessoa_id           uuid not null references pessoas(id) on delete cascade,
  nome_visitante      text not null,
  observacao_oracao   text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz
);

comment on table celula_expectativa_visitante is
  'Visitante esperado por um membro para uma reunião de célula (Células PR2). Sem UNIQUE. reuniao_id/pessoa_id ON DELETE CASCADE (DB-DEC-04).';

create index if not exists celula_expectativa_igreja_idx
  on celula_expectativa_visitante (igreja_id);
create index if not exists celula_expectativa_igreja_reuniao_idx
  on celula_expectativa_visitante (igreja_id, reuniao_id);
create index if not exists celula_expectativa_igreja_pessoa_idx
  on celula_expectativa_visitante (igreja_id, pessoa_id);

alter table celula_expectativa_visitante enable row level security;
drop policy if exists tenant_isolation on celula_expectativa_visitante;
create policy tenant_isolation on celula_expectativa_visitante
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

commit;
