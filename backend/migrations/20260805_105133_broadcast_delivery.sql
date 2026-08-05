-- PastorAI — BROADCAST-DELIVERY-1
--
-- Agenda permanece em broadcasts (status rascunho|agendado|enviado), enquanto
-- ocorrências e entregas vivem em tabelas próprias. Não existe ALTER TYPE e
-- não existe backfill: todo broadcast legado mantém proxima_execucao = NULL e,
-- portanto, fica inativo até uma decisão/recriação explícita do proprietário.

begin;

-- ---------------------------------------------------------------------------
-- Agenda persistente. Somente requests novos, com a flag assíncrona ligada,
-- preenchem proxima_execucao.
-- ---------------------------------------------------------------------------
alter table broadcasts
  add column if not exists proxima_execucao timestamptz null;
alter table broadcasts
  add column if not exists claim_ate timestamptz null;
alter table broadcasts
  add column if not exists claim_por text null;

-- NOT VALID preserva linhas legadas com hora fora do contrato sem permitir que
-- novas escritas inválidas passem. 23:59 é válido; 24:00 não é.
alter table broadcasts drop constraint if exists broadcasts_hora_chk;
alter table broadcasts add constraint broadcasts_hora_chk
  check (hora is null or hora ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$') not valid;

create index if not exists idx_broadcasts_agenda_ativa
  on broadcasts (proxima_execucao)
  where status = 'agendado' and proxima_execucao is not null;

-- ---------------------------------------------------------------------------
-- Uma ocorrência materializada por slot. Ela existe mesmo com audiência vazia
-- para distinguir "executou sem destinatários" de "nunca executou".
-- ---------------------------------------------------------------------------
create table if not exists broadcast_execucoes (
  id             uuid primary key default gen_random_uuid(),
  igreja_id      uuid not null references igrejas(id) on delete cascade,
  broadcast_id   uuid not null references broadcasts(id) on delete cascade,
  seq            integer not null,
  data_nominal   date not null,
  hora_nominal   text null,
  iniciada_em    timestamptz null,
  finalizada_em  timestamptz null,
  lease_ate      timestamptz null,
  claim_por      text null,
  criado_em      timestamptz not null default now(),
  constraint broadcast_execucoes_seq_chk check (seq > 0),
  constraint broadcast_execucoes_hora_chk check (
    hora_nominal is null
    or hora_nominal ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
  ),
  constraint broadcast_execucoes_seq_uq unique (broadcast_id, seq)
);

create unique index if not exists broadcast_execucoes_slot_uq
  on broadcast_execucoes (
    igreja_id,
    broadcast_id,
    data_nominal,
    coalesce(hora_nominal, '')
  );
create index if not exists idx_broadcast_execucoes_igreja
  on broadcast_execucoes (igreja_id);
create index if not exists idx_broadcast_execucoes_abertas
  on broadcast_execucoes (igreja_id, criado_em)
  where finalizada_em is null;

-- ---------------------------------------------------------------------------
-- Ledger por destinatário. "aceito" significa apenas HTTP 2xx da Evolution;
-- resultado ambíguo vira "desconhecido" e nunca recebe retry automático.
-- ---------------------------------------------------------------------------
create table if not exists broadcast_entregas (
  id                   uuid primary key default gen_random_uuid(),
  igreja_id            uuid not null references igrejas(id) on delete cascade,
  execucao_id          uuid not null
                         references broadcast_execucoes(id) on delete cascade,
  pessoa_id            uuid null references pessoas(id) on delete set null,
  telefone             text not null,
  status               text not null default 'pendente',
  tentativas           integer not null default 0,
  lease_ate            timestamptz null,
  claim_por            text null,
  ultimo_erro_classe   text null,
  criado_em            timestamptz not null default now(),
  atualizado_em        timestamptz not null default now(),
  constraint broadcast_entregas_status_chk check (status in (
    'pendente',
    'em_envio',
    'aceito',
    'falhou_retentavel',
    'falhou_permanente',
    'desconhecido',
    'suprimido'
  )),
  constraint broadcast_entregas_tentativas_chk check (tentativas >= 0),
  constraint broadcast_entregas_execucao_telefone_uq
    unique (execucao_id, telefone)
);

-- Duas barreiras contra fan-out automático duplicado: uma por pessoa e outra
-- pelo telefone congelado. pessoa_id pode virar NULL após exclusão, por isso o
-- índice parcial e a chave por telefone coexistem.
create unique index if not exists broadcast_entregas_execucao_pessoa_uq
  on broadcast_entregas (execucao_id, pessoa_id)
  where pessoa_id is not null;
create index if not exists idx_broadcast_entregas_pessoa
  on broadcast_entregas (pessoa_id)
  where pessoa_id is not null;
create index if not exists idx_broadcast_entregas_igreja
  on broadcast_entregas (igreja_id);
create index if not exists idx_broadcast_entregas_trabalho
  on broadcast_entregas (igreja_id, execucao_id, status)
  where status in ('pendente', 'em_envio', 'falhou_retentavel');
create index if not exists idx_broadcast_entregas_lease
  on broadcast_entregas (lease_ate)
  where status = 'em_envio';
create index if not exists idx_broadcast_entregas_criado
  on broadcast_entregas (criado_em);

-- ---------------------------------------------------------------------------
-- RLS tenant_isolation nas duas tabelas novas. O worker descobre tenants no
-- papel da conexão e abre uma sessão authenticated nova para cada mutação.
-- ---------------------------------------------------------------------------
alter table broadcast_execucoes enable row level security;
drop policy if exists tenant_isolation on broadcast_execucoes;
create policy tenant_isolation on broadcast_execucoes
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

alter table broadcast_entregas enable row level security;
drop policy if exists tenant_isolation on broadcast_entregas;
create policy tenant_isolation on broadcast_entregas
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

-- O backend usa SET LOCAL ROLE authenticated nas sessões tenant-scoped. Grants
-- explícitos tornam o acesso determinístico mesmo em projetos novos cujo Data
-- API não configure privilégios públicos por default; RLS continua obrigatório.
revoke all privileges on table broadcast_execucoes from public;
revoke all privileges on table broadcast_execucoes from anon;
revoke all privileges on table broadcast_execucoes from authenticated;
revoke all privileges on table broadcast_entregas from public;
revoke all privileges on table broadcast_entregas from anon;
revoke all privileges on table broadcast_entregas from authenticated;
grant select, insert, update, delete on table broadcast_execucoes to authenticated;
grant select, insert, update, delete on table broadcast_entregas to authenticated;

comment on table broadcast_execucoes is
  'Ocorrências persistentes de broadcasts; resultado derivado do ledger.';
comment on table broadcast_entregas is
  'Ledger por destinatário; aceito=HTTP 2xx, desconhecido nunca tem retry automático.';
comment on column broadcast_entregas.telefone is
  'Snapshot para deduplicação; PII proibida em logs e corpos de erro.';

-- Intencionalmente SEM UPDATE de broadcasts: nenhum legado é ativado.

commit;
