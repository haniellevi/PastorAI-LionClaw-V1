-- ============================================================================
-- PastorAI 1.0 — Migration 0007: Remove dados de demonstracao do seed
-- Remove APENAS as "Amostras de dominio" da secao 7 do 0005_seed.sql
-- (delta-003 — explicitamente "NAO sao dados de producao").
--
-- MANTEM intacto o bootstrap da igreja piloto (igreja, subscription,
-- whatsapp_connection, agent_config, role_permissions, app_user admin e a
-- pessoa do Pastor Piloto). Deve ser executado com service role (bypassa RLS).
--
-- Idempotente: deletes por UUID/atributo fixo — re-executar e no-op.
-- Verificado contra o banco ativo: nenhum dado real depende destes registros
-- (0 multiplicacoes, 0 decisions, 0 consolidacoes, 0 consent_records, 0 cell_alerts).
--
-- IDs fixos da secao 7 (deterministicos):
--   pessoa Maria Visitante ...... 00000000-0000-0000-0000-0000000000b2
--   pessoa Joao em Consolidacao .. 00000000-0000-0000-0000-0000000000b3
--   pessoa Ana Membro ............ 00000000-0000-0000-0000-0000000000b4
--   celula Central ............... 00000000-0000-0000-0000-0000000000c1
--   conversa demo ................ 00000000-0000-0000-0000-0000000000d1
-- ============================================================================

begin;

-- 1) Mensagens da conversa demo (cascade tambem cobre, mas explicito p/ clareza)
delete from messages
 where conversation_id = '00000000-0000-0000-0000-0000000000d1';

-- 2) Conversa de inbox demo (Maria Visitante)
delete from conversations
 where id = '00000000-0000-0000-0000-0000000000d1';

-- 3) Item de fila demo (relatorio pendente da Celula Central) — sem UUID fixo
delete from work_queue_items
 where igreja_id = '00000000-0000-0000-0000-000000000001'
   and tipo = 'relatorio'
   and titulo = 'Relatorio da Celula Central pendente';

-- 4) Relatorio de exemplo da Celula Central (semana 2026-W23) — sem UUID fixo.
--    (Seria removido por cascade ao apagar a celula; explicito por seguranca.)
delete from reports
 where igreja_id = '00000000-0000-0000-0000-000000000001'
   and celula_id = '00000000-0000-0000-0000-0000000000c1'
   and semana = '2026-W23';

-- 5) Contatos de demonstracao (visitantes/membro de amostra).
--    Cascade cobre consolidacoes/decisions/consent_records/cell_alerts (0 hoje).
delete from pessoas
 where id in (
   '00000000-0000-0000-0000-0000000000b2',  -- Maria Visitante
   '00000000-0000-0000-0000-0000000000b3',  -- Joao em Consolidacao
   '00000000-0000-0000-0000-0000000000b4'   -- Ana Membro
 );

-- 6) Celula piloto de amostra (lider = Pastor Piloto; lider_id fica intacto).
--    Cascade cobre reports/cell_alerts/multiplicacoes residuais (0 hoje).
delete from celulas
 where id = '00000000-0000-0000-0000-0000000000c1';

commit;
