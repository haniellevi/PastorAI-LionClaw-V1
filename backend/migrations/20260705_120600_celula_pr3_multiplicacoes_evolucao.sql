-- ============================================================================
-- PastorAI — Migration 20260705_120600 — Células PR3-PR9 (g): evolução aditiva
-- do stub `multiplicacoes`.
-- Fontes: docs/sprints.json (feat-001.g / feat-010 multiplicação transacional
--         e idempotente) + docs/design/CELULAS-DECISOES-FINAIS.md (3.4/3.6).
--
-- EVOLUI (não recria — RNF-17) a tabela `multiplicacoes` (JÁ EXISTE em 0002,
-- com igreja_id NOT NULL + RLS/tenant_isolation aplicada em 0003). NÃO renomeia
-- `celula_id` — ela permanece como a célula de ORIGEM. Colunas aditivas:
--
--   solicitacao_id  uuid NOT NULL UNIQUE  FK celula_solicitacao ON DELETE CASCADE
--   idempotency_key text (índice único PARCIAL por-tenant: (igreja_id,
--                         idempotency_key) where not null)
--   celula_nova_id  uuid  FK celulas ON DELETE SET NULL (célula gerada)
--   created_at      timestamptz NOT NULL DEFAULT now()
--   updated_at      timestamptz (gerenciado pela app)
--
-- solicitacao_id + idempotency_key barram reprocesso/duplo clique (RNF-06/07).
-- igreja_id já existe: NÃO é adicionado. A policy tenant_isolation é apenas
-- RE-AFIRMADA (idempotente) sobre a coluna igreja_id existente do stub.
--
-- NOTA (NOT NULL em solicitacao_id): o stub não tem linhas de negócio no MVP
-- (PR "Núcleo que hoje não existe"); a coluna nasce sem default e recebe NOT
-- NULL. Requer ausência de linhas órfãs sem solicitação no ambiente-alvo.
--
-- ALTER/índices transacionais + idempotentes. Não aplicada automaticamente.
-- ============================================================================

begin;

-- ----------------------------------------------------------------------------
-- solicitacao_id: origem transacional da multiplicação (1:1 com a solicitação
-- aprovada). FK CASCADE + UNIQUE. NOT NULL aplicado após criar a coluna.
-- ----------------------------------------------------------------------------
alter table multiplicacoes add column if not exists solicitacao_id uuid;

do $$ begin
  alter table multiplicacoes add constraint multiplicacoes_solicitacao_fk
    foreign key (solicitacao_id) references celula_solicitacao(id) on delete cascade;
exception when duplicate_object then null; end $$;

-- UNIQUE (1 multiplicação por solicitação) via índice único dedicado.
create unique index if not exists multiplicacoes_solicitacao_uq
  on multiplicacoes (solicitacao_id);

-- Exigência de não-nulo via CHECK NOT VALID (mesmo idioma de celulas_horario_chk
-- e celula_reuniao_hora_chk): NÃO escaneia/rejeita linhas legadas do stub — que,
-- por a coluna ser nova, nascem todas com solicitacao_id NULL — mas ENFORCE em
-- todo INSERT/UPDATE novo. Assim a migration nunca aborta numa tabela com dados
-- pré-existentes (o POST /multiplicacoes esteve LIVE), e o fluxo transacional
-- (que sempre grava solicitacao_id) fica garantido daqui pra frente. Um
-- VALIDATE posterior pode endurecer após limpar/backfillar o legado.
do $$ begin
  alter table multiplicacoes add constraint multiplicacoes_solicitacao_nn
    check (solicitacao_id is not null) not valid;
exception when duplicate_object then null; end $$;

-- ----------------------------------------------------------------------------
-- idempotency_key: barra reprocesso da mesma aprovação. Índice único PARCIAL
-- (só quando não nulo), mesmo padrão do dedup do EVT-6.
-- ----------------------------------------------------------------------------
alter table multiplicacoes add column if not exists idempotency_key text;

-- SPEC 2.1.8/2.2.3: índice único PARCIAL por-tenant (igreja_id, idempotency_key)
-- where idempotency_key is not null — unicidade escopada à igreja, não global.
create unique index if not exists multiplicacoes_idempotency_key_uq
  on multiplicacoes (igreja_id, idempotency_key) where idempotency_key is not null;

-- ----------------------------------------------------------------------------
-- celula_nova_id: célula GERADA pela multiplicação. FK SET NULL (não apaga o
-- histórico da multiplicação se a nova célula for removida). celula_id
-- permanece intacta como a célula de ORIGEM.
-- ----------------------------------------------------------------------------
alter table multiplicacoes add column if not exists celula_nova_id uuid;

do $$ begin
  alter table multiplicacoes add constraint multiplicacoes_celula_nova_fk
    foreign key (celula_nova_id) references celulas(id) on delete set null;
exception when duplicate_object then null; end $$;

create index if not exists idx_multiplicacoes_celula_nova
  on multiplicacoes (celula_nova_id);

-- ----------------------------------------------------------------------------
-- timestamps. created_at com default preenche linhas legadas => NOT NULL seguro.
-- updated_at gerenciado pela aplicação (sem trigger).
-- ----------------------------------------------------------------------------
alter table multiplicacoes
  add column if not exists created_at timestamptz not null default now();
alter table multiplicacoes
  add column if not exists updated_at timestamptz;

-- ----------------------------------------------------------------------------
-- RLS: re-afirma o padrão tenant_isolation sobre a coluna igreja_id EXISTENTE
-- do stub (já aplicado em 0003). Idempotente. NÃO adiciona igreja_id.
-- ----------------------------------------------------------------------------
alter table multiplicacoes enable row level security;
drop policy if exists tenant_isolation on multiplicacoes;
create policy tenant_isolation on multiplicacoes
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

commit;
