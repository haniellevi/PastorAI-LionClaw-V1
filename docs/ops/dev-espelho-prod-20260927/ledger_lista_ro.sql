-- ledger_lista_ro.sql - SÓ LEITURA: nomes e origens de public.schema_migrations (CSV),
-- entrada do montar_recriacao.py. Não lê tabela da aplicação.
--   psql service=... -X -q --csv -f ledger_lista_ro.sql > ledger_prod.csv
\set ON_ERROR_STOP on
BEGIN TRANSACTION READ ONLY;
SELECT name, origem FROM public.schema_migrations ORDER BY name COLLATE "C";
ROLLBACK;
