-- ============================================================================
-- PastorAI 1.0 — Migration 0002: Schema completo de tabelas
-- SPEC secao 2.1. Fundacoes: F1 (igreja_id em toda tabela), F2/F6/F7 (pessoa
-- unificada com estado e lider_id), F8 (logs de IA).
--
-- Nota sobre FKs circulares: pessoas.celula_id -> celulas e celulas.lider_id ->
-- pessoas formam um ciclo. As tabelas sao criadas na ordem possivel e as FKs
-- circulares sao adicionadas via ALTER TABLE ao final.
-- ============================================================================

begin;

-- ----------------------------------------------------------------------------
-- igrejas (tenants — F1). Unica tabela SEM igreja_id (ela e o tenant).
-- ----------------------------------------------------------------------------
create table if not exists igrejas (
  id          uuid primary key default gen_random_uuid(),
  nome        text not null,
  status      igreja_status not null default 'ativa',
  plano       text,                              -- ate_100 / 101_200 / acima_201
  created_at  timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- pessoas (modelo unificado — F2/F6/F7)
-- celula_id e lider_id sao FKs nullable. celula_id FK adicionada ao final.
-- ----------------------------------------------------------------------------
create table if not exists pessoas (
  id                 uuid primary key default gen_random_uuid(),
  igreja_id          uuid not null references igrejas(id) on delete cascade,
  nome               text not null,
  telefone           text not null,
  email              text,
  genero             pessoa_genero,
  faixa_etaria       text,
  endereco           text,
  tipo               pessoa_tipo,
  etapa              pessoa_etapa,
  subetapa           pessoa_subetapa,
  presencas_celula   int not null default 0,
  aceitou_jesus      boolean not null default false,
  acompanhamento     pessoa_acompanhamento,
  origem             text,
  primeiro_contato   timestamptz,
  celula_id          uuid,                        -- FK -> celulas (adicionada ao final)
  lider_id           uuid references pessoas(id) on delete set null,  -- F7 (auto-FK)
  consentimento      boolean not null default false,
  optout             boolean not null default false,
  apto_proxima_cd    boolean not null default false,
  created_at         timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- app_users (acesso ao painel via Clerk)
-- ----------------------------------------------------------------------------
create table if not exists app_users (
  id             uuid primary key default gen_random_uuid(),
  igreja_id      uuid not null references igrejas(id) on delete cascade,
  clerk_user_id  text unique,
  pessoa_id      uuid references pessoas(id) on delete set null,
  nome           text not null,
  email          text not null,
  status         app_user_status,
  created_at     timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- user_roles (papeis acumulados — F3)
-- ----------------------------------------------------------------------------
create table if not exists user_roles (
  id         uuid primary key default gen_random_uuid(),
  igreja_id  uuid not null references igrejas(id) on delete cascade,
  user_id    uuid not null references app_users(id) on delete cascade,
  papel      user_role_papel not null,
  unique (user_id, papel)
);

-- ----------------------------------------------------------------------------
-- role_permissions (matriz papel x tela — delta-010)
-- ----------------------------------------------------------------------------
create table if not exists role_permissions (
  id         uuid primary key default gen_random_uuid(),
  igreja_id  uuid not null references igrejas(id) on delete cascade,
  papel      role_perm_papel not null,
  tela       text not null,
  unique (igreja_id, papel, tela)
);

-- ----------------------------------------------------------------------------
-- celulas
-- ----------------------------------------------------------------------------
create table if not exists celulas (
  id                    uuid primary key default gen_random_uuid(),
  igreja_id             uuid not null references igrejas(id) on delete cascade,
  nome                  text not null,
  lider_id              uuid references pessoas(id) on delete set null,
  dia_reuniao           text,
  cobertura_espiritual  text not null,
  ativo                 boolean not null default true,
  created_at            timestamptz not null default now()
);

-- pessoas.celula_id FK (apos celulas existir)
do $$ begin
  alter table pessoas
    add constraint pessoas_celula_id_fkey
    foreign key (celula_id) references celulas(id) on delete set null;
exception when duplicate_object then null; end $$;

-- ----------------------------------------------------------------------------
-- cell_alerts
-- ----------------------------------------------------------------------------
create table if not exists cell_alerts (
  id             uuid primary key default gen_random_uuid(),
  igreja_id      uuid not null references igrejas(id) on delete cascade,
  celula_id      uuid not null references celulas(id) on delete cascade,
  pessoa_id      uuid not null references pessoas(id) on delete cascade,
  gatilho        text,
  acao_esperada  text,
  tratado        boolean not null default false,
  created_at     timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- conversations
-- ----------------------------------------------------------------------------
create table if not exists conversations (
  id               uuid primary key default gen_random_uuid(),
  igreja_id        uuid not null references igrejas(id) on delete cascade,
  pessoa_id        uuid references pessoas(id) on delete set null,
  telefone         text not null,
  estado           conversation_estado,
  assumido_por     uuid references app_users(id) on delete set null,
  assumido_em      timestamptz,
  ultima_mensagem  text,
  nao_lidas        int not null default 0,
  espera_desde     timestamptz,
  numero_oficial   boolean not null default true,
  updated_at       timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- messages (historico cronologico)
-- ----------------------------------------------------------------------------
create table if not exists messages (
  id               uuid primary key default gen_random_uuid(),
  igreja_id        uuid not null references igrejas(id) on delete cascade,
  conversation_id  uuid not null references conversations(id) on delete cascade,
  direcao          message_direcao not null,
  autor            message_autor not null,
  texto            text,
  criado_em        timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- work_queue_items
-- ----------------------------------------------------------------------------
create table if not exists work_queue_items (
  id              uuid primary key default gen_random_uuid(),
  igreja_id       uuid not null references igrejas(id) on delete cascade,
  tipo            work_queue_tipo not null,
  titulo          text not null,
  contexto        text,
  pessoa_id       uuid references pessoas(id) on delete set null,
  responsavel_id  uuid references app_users(id) on delete set null,
  status          work_queue_status,
  prazo           timestamptz,
  prioridade      int,
  created_at      timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- reports
-- ----------------------------------------------------------------------------
create table if not exists reports (
  id            uuid primary key default gen_random_uuid(),
  igreja_id     uuid not null references igrejas(id) on delete cascade,
  celula_id     uuid not null references celulas(id) on delete cascade,
  semana        text not null,
  data_reuniao  date,
  presentes     int,
  visitantes    int,
  decisoes      int,
  oferta        numeric,
  observacoes   text,
  status        report_status,
  origem        report_origem,
  created_at    timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- broadcasts
-- ----------------------------------------------------------------------------
create table if not exists broadcasts (
  id                uuid primary key default gen_random_uuid(),
  igreja_id         uuid not null references igrejas(id) on delete cascade,
  titulo            text not null,
  mensagem          text not null,
  segmentos         text[] not null,
  modo              broadcast_modo not null,
  data              date,
  hora              text,
  repeticao         broadcast_repeticao,
  alcance           int,
  ignorados_optout  int,
  status            broadcast_status,
  created_at        timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- events
-- ----------------------------------------------------------------------------
create table if not exists events (
  id               uuid primary key default gen_random_uuid(),
  igreja_id        uuid not null references igrejas(id) on delete cascade,
  titulo           text not null,
  data             date not null,
  hora             text,
  descricao        text,
  google_event_id  text,
  created_at       timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- whatsapp_connections (1:1 com igreja — igreja_id UNIQUE)
-- ----------------------------------------------------------------------------
create table if not exists whatsapp_connections (
  id           uuid primary key default gen_random_uuid(),
  igreja_id    uuid not null unique references igrejas(id) on delete cascade,
  numero       text,
  status       whatsapp_status,
  instance     text,
  ultima_sync  timestamptz
);

-- ----------------------------------------------------------------------------
-- agent_configs (1:1 com igreja — igreja_id UNIQUE)
-- ----------------------------------------------------------------------------
create table if not exists agent_configs (
  id             uuid primary key default gen_random_uuid(),
  igreja_id      uuid not null unique references igrejas(id) on delete cascade,
  nome           text,
  tom            text,
  comportamento  text not null,
  publico_alvo   text[],
  acessos        text[],
  ativo          boolean not null default true
);

-- ----------------------------------------------------------------------------
-- llm_credentials (1:1 com igreja — igreja_id UNIQUE)
-- ----------------------------------------------------------------------------
create table if not exists llm_credentials (
  id                uuid primary key default gen_random_uuid(),
  igreja_id         uuid not null unique references igrejas(id) on delete cascade,
  provedor          text not null,
  api_key_encrypted text not null,
  validado          boolean not null default false,
  ativo             boolean not null default false
);

-- ----------------------------------------------------------------------------
-- crons
-- ----------------------------------------------------------------------------
create table if not exists crons (
  id              uuid primary key default gen_random_uuid(),
  igreja_id       uuid not null references igrejas(id) on delete cascade,
  nome            text not null,
  frequencia      text not null,
  gatilho_estado  text,
  acao            text,
  ativo           boolean not null default true
);

-- ----------------------------------------------------------------------------
-- subscriptions (1:1 com igreja — igreja_id UNIQUE)
-- ----------------------------------------------------------------------------
create table if not exists subscriptions (
  id                     uuid primary key default gen_random_uuid(),
  igreja_id              uuid not null unique references igrejas(id) on delete cascade,
  plano                  text not null,
  status                 subscription_status,
  pessoas                int,
  limite                 int,
  proxima_cobranca       date,
  asaas_customer_id      text,
  asaas_subscription_id  text,
  setup_pago             boolean not null default false
);

-- ----------------------------------------------------------------------------
-- system_managers
-- ----------------------------------------------------------------------------
create table if not exists system_managers (
  id                 uuid primary key default gen_random_uuid(),
  igreja_id          uuid not null references igrejas(id) on delete cascade,
  nome               text not null,
  email              text not null,
  papel_operacional  system_manager_papel
);

-- ----------------------------------------------------------------------------
-- consolidacoes
-- ----------------------------------------------------------------------------
create table if not exists consolidacoes (
  id              uuid primary key default gen_random_uuid(),
  igreja_id       uuid not null references igrejas(id) on delete cascade,
  pessoa_id       uuid not null references pessoas(id) on delete cascade,
  tipo            consolidacao_tipo,
  responsavel_id  uuid references app_users(id) on delete set null,
  progresso       int not null default 0,
  concluida       boolean not null default false,
  prazo_conexao   timestamptz,
  created_at      timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- consolidacao_etapas (trilha individual)
-- ----------------------------------------------------------------------------
create table if not exists consolidacao_etapas (
  id               uuid primary key default gen_random_uuid(),
  igreja_id        uuid not null references igrejas(id) on delete cascade,
  consolidacao_id  uuid not null references consolidacoes(id) on delete cascade,
  etapa            text,
  concluida        boolean not null default false,
  confirmada_por   uuid references app_users(id) on delete set null,
  confirmada_em    timestamptz
);

-- ----------------------------------------------------------------------------
-- decisions
-- ----------------------------------------------------------------------------
create table if not exists decisions (
  id              uuid primary key default gen_random_uuid(),
  igreja_id       uuid not null references igrejas(id) on delete cascade,
  pessoa_id       uuid not null references pessoas(id) on delete cascade,
  origem          text,
  vinculo         decision_vinculo not null,
  celula_id       uuid references celulas(id) on delete set null,
  responsavel_id  uuid references app_users(id) on delete set null,
  prazo_conexao   timestamptz,
  created_at      timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- multiplicacoes
-- ----------------------------------------------------------------------------
create table if not exists multiplicacoes (
  id             uuid primary key default gen_random_uuid(),
  igreja_id      uuid not null references igrejas(id) on delete cascade,
  celula_id      uuid not null references celulas(id) on delete cascade,
  status         multiplicacao_status,
  data_prevista  date,
  descendencia   text,
  novo_lider_id  uuid references pessoas(id) on delete set null,
  supervisao_ok  boolean not null default false,
  aprovada_por   uuid references app_users(id) on delete set null
);

-- ----------------------------------------------------------------------------
-- consent_records (LGPD)
-- ----------------------------------------------------------------------------
create table if not exists consent_records (
  id           uuid primary key default gen_random_uuid(),
  igreja_id    uuid not null references igrejas(id) on delete cascade,
  pessoa_id    uuid not null references pessoas(id) on delete cascade,
  termo_versao text,
  aceite_em    timestamptz
);

-- ----------------------------------------------------------------------------
-- ai_usage_logs (auditoria de IA — F8)
-- ----------------------------------------------------------------------------
create table if not exists ai_usage_logs (
  id          uuid primary key default gen_random_uuid(),
  igreja_id   uuid not null references igrejas(id) on delete cascade,
  modelo      text,
  tokens_in   int,
  tokens_out  int,
  custo       numeric,
  ferramenta  text,
  created_at  timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- agent_conversation_logs (logs do agente — F8)
-- ----------------------------------------------------------------------------
create table if not exists agent_conversation_logs (
  id               uuid primary key default gen_random_uuid(),
  igreja_id        uuid not null references igrejas(id) on delete cascade,
  conversation_id  uuid references conversations(id) on delete set null,
  evento           text,
  payload          jsonb,
  created_at       timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- Indices de suporte ao isolamento por tenant e joins frequentes
-- ----------------------------------------------------------------------------
create index if not exists idx_pessoas_igreja            on pessoas (igreja_id);
create index if not exists idx_pessoas_celula            on pessoas (celula_id);
create index if not exists idx_pessoas_lider             on pessoas (lider_id);
create index if not exists idx_app_users_igreja          on app_users (igreja_id);
create index if not exists idx_app_users_clerk           on app_users (clerk_user_id);
create index if not exists idx_user_roles_igreja         on user_roles (igreja_id);
create index if not exists idx_role_permissions_igreja   on role_permissions (igreja_id);
create index if not exists idx_celulas_igreja            on celulas (igreja_id);
create index if not exists idx_cell_alerts_igreja        on cell_alerts (igreja_id);
create index if not exists idx_conversations_igreja      on conversations (igreja_id);
create index if not exists idx_messages_igreja           on messages (igreja_id);
create index if not exists idx_messages_conversation     on messages (conversation_id);
create index if not exists idx_work_queue_igreja         on work_queue_items (igreja_id);
create index if not exists idx_reports_igreja            on reports (igreja_id);
create index if not exists idx_reports_celula            on reports (celula_id);
create index if not exists idx_broadcasts_igreja         on broadcasts (igreja_id);
create index if not exists idx_events_igreja             on events (igreja_id);
create index if not exists idx_crons_igreja              on crons (igreja_id);
create index if not exists idx_system_managers_igreja    on system_managers (igreja_id);
create index if not exists idx_consolidacoes_igreja      on consolidacoes (igreja_id);
create index if not exists idx_consol_etapas_igreja      on consolidacao_etapas (igreja_id);
create index if not exists idx_decisions_igreja          on decisions (igreja_id);
create index if not exists idx_multiplicacoes_igreja     on multiplicacoes (igreja_id);
create index if not exists idx_consent_records_igreja    on consent_records (igreja_id);
create index if not exists idx_ai_usage_logs_igreja      on ai_usage_logs (igreja_id);
create index if not exists idx_agent_conv_logs_igreja    on agent_conversation_logs (igreja_id);

commit;
