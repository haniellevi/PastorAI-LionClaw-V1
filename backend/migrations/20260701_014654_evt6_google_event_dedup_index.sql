-- ============================================================================
-- PastorAI — Migration 20260701_014654 — EVT-6 PR6.3: dedup de import Google
-- SPEC "Módulo Agenda de Eventos" · ADR docs/design/AGENDA-EVENTOS-EVT0-decisao.md
--
-- Índice único PARCIAL em events (igreja_id, google_event_id) para impedir, no
-- nível do banco, dois eventos com o mesmo google_event_id DENTRO da mesma igreja.
-- Fecha a dedup que hoje é só em código (app/routers/calendar.py::import_events,
-- PR6.2 — o comentário lá aponta "o índice único parcial vem no PR6.3").
--
-- Por que PARCIAL (WHERE google_event_id is not null):
--   eventos manuais têm google_event_id NULL. Sem o predicado, dois eventos
--   manuais colidiriam (NULL não é distinto em UNIQUE do Postgres antes do
--   NULLS NOT DISTINCT). O parcial só indexa linhas importadas do Google.
--
-- Escopo por igreja_id: o MESMO google_event_id em igrejas DIFERENTES é
--   permitido (multi-tenant) — a unicidade é (igreja_id, google_event_id).
--
-- Idempotente: `create unique index if not exists` (no-op se já existe).
-- Não abre ALTER TYPE => roda em transação (padrão EVT-1).
-- Não toca RLS/policies (índice é por linha, ortogonal à policy tenant_isolation
--   de events em 0003) nem BYPASSRLS / set_tenant_context.
--
-- ⚠️ Aplicar manualmente no Supabase, em ordem de nome de arquivo. `create
--   unique index` FALHA se já houver duplicatas (igreja_id, google_event_id) na
--   tabela — o que é o comportamento correto (não mascarar dado sujo). A dedup em
--   código do PR6.2 já evita gerar essas duplicatas; se a criação falhar, limpar
--   as duplicatas antes de reaplicar.
-- ============================================================================

begin;

-- ponytail: índice não-concurrent (lock breve de escrita em events). A tabela é
-- pequena por tenant e a aplicação é manual/fora de pico; trocar por CREATE
-- UNIQUE INDEX CONCURRENTLY (fora de transação) só se events crescer a ponto do
-- lock incomodar.
create unique index if not exists events_igreja_google_event_uidx
  on events (igreja_id, google_event_id)
  where google_event_id is not null;

commit;
