-- ============================================================================
-- PastorAI — Migration 20260705_120400 — Células PR3-PR9 (e): tabela
-- `celula_aviso` (avisos da célula / da Central).
-- Fontes: docs/sprints.json (feat-001.e / feat-011 avisos + alcance E15).
--
-- Aviso publicado pelo líder (origem='celula', escopo='celula') ou pela Central
-- (origem='central', escopo 'celula' ou 'igreja'). Quando escopo='igreja',
-- celula_id é NULL (vale para toda a igreja). igreja_id PRÓPRIO + policy própria.
--
--   celula_id ON DELETE CASCADE (nullable p/ escopo=igreja)
--   autor_id  ON DELETE SET NULL (FK de autor)
--
-- `notificado_em` é o ponto de extensão do disparo (cell_notify.py no-op só
-- grava a intenção; sem WhatsApp real). `ativo=false` = inativado (sem edição
-- no MVP: corrigir = desativar e criar novo). `updated_at` gerenciado pela app.
-- CREATE/índices transacionais + idempotentes. Não aplicada automaticamente.
-- ============================================================================

begin;

create table if not exists celula_aviso (
  id            uuid primary key default gen_random_uuid(),
  igreja_id     uuid not null references igrejas(id) on delete cascade,
  celula_id     uuid references celulas(id) on delete cascade,
  autor_id      uuid references pessoas(id) on delete set null,
  origem        text not null,
  escopo        text not null,
  titulo        text not null,
  conteudo      text not null,
  ativo         boolean not null default true,
  publicado_em  timestamptz not null default now(),
  notificado_em timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz,
  constraint celula_aviso_origem_chk check (origem in ('celula', 'central')),
  constraint celula_aviso_escopo_chk check (escopo in ('celula', 'igreja'))
);

comment on table celula_aviso is
  'Aviso da célula (origem=celula) ou da Central (origem=central), com escopo celula/igreja (Células PR3-PR9). celula_id NULL quando escopo=igreja. igreja_id próprio + RLS própria. celula_id CASCADE, autor_id SET NULL. notificado_em = ponto de extensão do disparo (no-op no MVP).';

-- Índices exigidos pela SPEC 2.1.6 (batem exatamente):
--   idx_celula_aviso_feed   (igreja_id, ativo, publicado_em desc) -> feed principal
--   idx_celula_aviso_celula (igreja_id, celula_id)               -> avisos por célula
create index if not exists idx_celula_aviso_feed
  on celula_aviso (igreja_id, ativo, publicado_em desc);
create index if not exists idx_celula_aviso_celula
  on celula_aviso (igreja_id, celula_id);

alter table celula_aviso enable row level security;
drop policy if exists tenant_isolation on celula_aviso;
create policy tenant_isolation on celula_aviso
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

commit;
