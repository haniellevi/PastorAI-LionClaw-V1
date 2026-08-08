-- PastorAI — idempotência de eventos outbound do provider.
--
-- O worker já serializa cada (igreja_id, provider_message_id) com um advisory
-- lock transacional. Este índice é a barreira final para eventos `fromMe` e
-- mantém a consulta sob o fence indexada, sem varrer todas as mensagens da
-- igreja. O índice inbound existente permanece inalterado.
--
-- Gate antes de aplicar em qualquer ambiente:
--
--   select igreja_id, provider_message_id, count(*)
--     from messages
--    where direcao = 'out' and provider_message_id is not null
--    group by 1, 2 having count(*) > 1;
--
-- Se houver linhas, deduplicar com revisão humana antes desta migration. A
-- criação falha de propósito diante de dado duplicado; nada é apagado aqui.
--
-- Este arquivo contém de propósito UM ÚNICO comando executável. O runner usa
-- autocommit e `CREATE INDEX CONCURRENTLY` não pode rodar dentro de
-- BEGIN/COMMIT nem junto de outro comando no mesmo batch. Ao usar o SQL Editor,
-- executar somente este arquivo/comando, sem opção de transação.
--
-- Não usar IF NOT EXISTS: uma tentativa concorrente que falha pode deixar um
-- índice homônimo INVALID. Nesse caso IF NOT EXISTS faria no-op e permitiria ao
-- runner registrar uma barreira que não está utilizável.
--
-- Após aplicar, verificar `pg_index.indisvalid`, `indisready`, `indislive`,
-- `indisunique` e `pg_get_indexdef` para este nome. Se a criação falhar e o
-- índice ficar INVALID, corrigir a causa, executar com aprovação explícita:
--
--   drop index concurrently messages_outbound_provider_id_uidx;
--
-- e reaplicar. Se o índice estiver válido mas o registro em
-- `schema_migrations` tiver falhado, validar a definição e registrar a
-- migration manualmente; não reaplicar às cegas.

create unique index concurrently messages_outbound_provider_id_uidx
  on messages (igreja_id, provider_message_id)
  where direcao = 'out' and provider_message_id is not null;
