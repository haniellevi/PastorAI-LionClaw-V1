-- ============================================================================
-- PastorAI — Migration 20260705_120100 — Células PR3-PR9 (b): tabela
-- `celula_reuniao_registro` (registros pastorais de uma reunião).
-- Fontes: docs/sprints.json (feat-001.b / feat-006 "POST records persiste
--         decisao/oracao/observacao ... com autor_id do contexto").
--
-- Um registro pastoral por linha (decisão / oração / observação) vinculado a uma
-- reunião materializada (celula_reuniao, PR2). É oculto do discípulo: só
-- líder/Central leem (regra na app). igreja_id PRÓPRIO + policy tenant_isolation
-- dedicada (a RLS não herda por FK), padrão idêntico ao PR1/PR2.
--
--   reuniao_id  ON DELETE CASCADE (parte da ocorrência — DB-DEC-04)
--   autor_id    ON DELETE SET NULL (FK de autor: não apaga o registro)
--
-- `updated_at` gerenciado pela aplicação (sem trigger). CREATE/índices
-- transacionais + idempotentes. Não aplicada automaticamente.
-- ============================================================================

begin;

create table if not exists celula_reuniao_registro (
  id          uuid primary key default gen_random_uuid(),
  igreja_id   uuid not null references igrejas(id) on delete cascade,
  reuniao_id  uuid not null references celula_reuniao(id) on delete cascade,
  tipo        text not null,
  conteudo    text not null,
  pessoa_id   uuid references pessoas(id) on delete set null,
  autor_id    uuid references pessoas(id) on delete set null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz,
  constraint celula_reuniao_registro_tipo_chk
    check (tipo in ('decisao', 'oracao', 'observacao'))
);

comment on table celula_reuniao_registro is
  'Registro pastoral (decisão/oração/observação) de uma reunião de célula (Células PR3-PR9). Oculto do discípulo. igreja_id próprio + RLS própria. reuniao_id CASCADE, autor_id SET NULL.';

create index if not exists idx_celula_reuniao_registro_igreja
  on celula_reuniao_registro (igreja_id);
create index if not exists idx_celula_reuniao_registro_reuniao
  on celula_reuniao_registro (igreja_id, reuniao_id, tipo);

alter table celula_reuniao_registro enable row level security;
drop policy if exists tenant_isolation on celula_reuniao_registro;
create policy tenant_isolation on celula_reuniao_registro
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

commit;
