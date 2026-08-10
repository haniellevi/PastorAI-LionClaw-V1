-- ============================================================================
-- PastorAI — M06: índice da FK de logs do agente para conversas
--
-- O advisor de PROD sinalizou a FK sem índice e a tabela já concentra cerca de
-- 67 mil linhas. O índice reduz scans ao consultar/remover a conversa pai.
-- A criação é aditiva, idempotente pelo nome e concorrente para não bloquear
-- INSERT/UPDATE/DELETE durante a construção.
--
-- IMPORTANTE: CREATE INDEX CONCURRENTLY deve ser o único comando executável do
-- arquivo e não pode rodar dentro de BEGIN/COMMIT. Antes e depois da aplicação,
-- validar nome, definição, indisvalid, indisready e indislive (runbook M06).
-- ============================================================================

create index concurrently if not exists idx_agent_conversation_logs_conversation_id_fk
    on public.agent_conversation_logs (conversation_id);
