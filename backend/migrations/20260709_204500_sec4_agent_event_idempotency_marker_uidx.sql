-- ============================================================================
-- PastorAI — Migration 20260709_204500 — SEC-4: idempotência de marcadores
-- (agent_conversation_logs) — ALTO-005 / BAIXO-005
--
-- Índice único PARCIAL em agent_conversation_logs (igreja_id, evento) SOMENTE
-- para os MARCADORES de idempotência de envio externo:
--   - SLA:        'sla_<status>:<source>:<item_id>'  (app/services/sla_engine.py)
--   - Autoupgrade:'subscription_upgrade:<plano>'      (app/routers/subscription.py)
--
-- Por que existe:
--   Hoje os dois fluxos fazem SELECT (_already_dispatched) e, se não achar
--   marcador, ENVIAM primeiro (Evolution) e só DEPOIS gravam o marcador
--   (log_agent_event) — não é "reserva-antes-do-send". Sem constraint de banco,
--   duas execuções concorrentes podem passar as duas pelo SELECT antes de
--   qualquer uma commitar o marcador, e as duas enviam (duplicado).
--
--   Este índice fecha a metade "nunca existem 2 linhas de marcador iguais" —
--   uma segunda tentativa de INSERT do MESMO marcador vira IntegrityError.
--   Isso já evita duplicar o REGISTRO (e detecta a corrida em log/teste), mas
--   **não** evita sozinho o duplo envio em si — pra isso, o código precisa
--   passar a reservar o marcador (INSERT) ANTES do send_text e só enviar se o
--   INSERT tiver sucesso (ON CONFLICT DO NOTHING → já despachado, não envia).
--   Essa mudança de ordem no código é trabalho futuro, fora do escopo desta
--   migration (ver riscos restantes no relatório do PR).
--
-- Por que PARCIAL (só os prefixos de marcador):
--   agent_conversation_logs guarda MUITOS eventos por igreja que se REPETEM
--   legitimamente (handoff, consent, intake, ...). Uma unicidade global em
--   (igreja_id, evento) quebraria esses. O predicado indexa apenas as linhas de
--   marcador de dedupe, que são únicas por construção (item+estágio / plano).
--
-- Escopo por igreja_id: o MESMO marcador em igrejas DIFERENTES é permitido
--   (multi-tenant). A unicidade é (igreja_id, evento). O índice é físico, logo
--   ortogonal à RLS/policy tenant_isolation (0003) — não a toca.
--
-- Idempotente: `create unique index if not exists` (no-op se já existe).
-- Não abre ALTER TYPE => roda em transação (padrão EVT-1/EVT-6).
--
-- ⚠️ Aplicar manualmente no Supabase, em ordem de nome de arquivo. `create unique
--   index` FALHA se já houver duplicatas (igreja_id, evento) nas linhas de
--   marcador — comportamento correto (não mascarar dado sujo). O check em código
--   (_already_dispatched / SELECT do evento) já evita gerar duplicatas; se a
--   criação falhar, limpar as duplicatas de marcador antes de reaplicar.
-- ============================================================================

begin;

create unique index if not exists agent_conversation_logs_idem_marker_uidx
  on agent_conversation_logs (igreja_id, evento)
  where evento like 'sla\_%' escape '\'
     or evento like 'subscription\_upgrade:%' escape '\';

commit;
