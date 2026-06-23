-- ============================================================================
-- PastorAI — Migration 20260623_154500_pessoa_tipo_add_contato
-- US-10 / jornada G12: adiciona o tipo de ENTRADA "contato" ao enum
-- pessoa_tipo (contato → visitante → membro → líder → pastor). Quem fala pela
-- 1ª vez nasce como "contato"; vira "visitante" só por evento real (líder
-- cadastra, consolidação ou check-in na igreja) — nunca por autodeclaração.
--
-- ALTER TYPE ADD VALUE NÃO pode rodar dentro de transação (≠ ADD COLUMN):
-- por isso SEM begin/commit. Idempotente via IF NOT EXISTS. Aplicar
-- manualmente no Supabase, em ordem de nome de arquivo.
-- ============================================================================

alter type pessoa_tipo add value if not exists 'contato' before 'visitante';
