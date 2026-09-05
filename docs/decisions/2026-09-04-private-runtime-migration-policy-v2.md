# Política source-only do runtime privado V2

**Estado:** `POLICY_ONLY / NÃO APROVADA / SEM MIGRATION 76`

Esta decisão cria uma fronteira V2 separada da autoria/replay V1. O contrato
V1 `TENANT` e seus artefatos byte-pinados não são editados nem reinterpretados.

## Contrato fechado

O artefato `migration-authoring-intent-v2` usa o prefixo
`PASTORAI_MIGRATION_INTENT_V2` e declara `scope=PRIVATE_RUNTIME`. Ele descreve,
sem aplicar, a futura superfície privada:

- schema `agent_private`, owner explícito da migration, sem uso de `PUBLIC`;
- role `agent_runtime` `NOLOGIN`, `NOINHERIT`, `NOSUPERUSER`, `NOBYPASSRLS`,
  sem memberships;
- `agent_private.current_tenant_id()` preservado como helper `SECURITY INVOKER`,
  `STABLE`, `search_path` fixo `pg_catalog`, owner da migration, retorno `uuid`
  e fonte `app.tenant_igreja_id`;
- contrato separado para a futura `agent_private.load_turn_context(uuid)` como
  `SECURITY DEFINER`, `STABLE`, `search_path` fixo `pg_catalog,agent_private`,
  sem instalar a função agora;
- execução somente para `agent_runtime`, sem grants diretos a `PUBLIC`;
- relações privadas futuras com `igreja_id NOT NULL`, RLS habilitada/forçada,
  owner explícito, `SELECT` somente e zero privilégios de escrita;
- configuração explícita de `AGENT_RUNTIME_DATABASE_URL`, fronteira read-only
  e gates `false`.

O modelo permite declarar futuras funções de leitura e relações privadas sem
inventar uma tabela ou alterar o catálogo atual. Referências de decisão,
recuperação e nodeids planejados para testes PG17/cross-tenant são obrigatórios
no artefato completo; esta política não afirma que esses testes foram
executados.

## Execução e replay

`new_private_runtime_migration.py draft-private-runtime` cria apenas um
artefato de política em `docs/governance/migrations/private-runtime/`; não cria
SQL em `backend/migrations`, não altera o head e não abre autorização.

`replay_private_runtime_migration_pg17.py` é um dispatcher aditivo. V1 retorna
à sua implementação histórica; V2 valida somente o contrato source-only. A
captura de snapshot e o delta são deliberadamente `NOT_IMPLEMENTED` e falham
antes de tocar cursor ou banco; portanto schema, role, `rolconfig`, memberships,
funções, ACL, `pg_default_acl`, RLS e identidades não são tratados como
capturados. O entrypoint CLI é estritamente source-only: não conecta a
PostgreSQL, não afirma delta PG17/cross-tenant e não consulta ambiente
compartilhado.

## Limites e próximo gate

O contrato não prova equivalência semântica do SQL futuro, ownership global,
default ACLs ou políticas fora da superfície declarada. A migration real,
grants, credenciais, aplicação, DEV, PROD, flags, runtime e cutover continuam
bloqueados. O próximo gate único é uma revisão humana independente da política
V2 e de sua proposta de schema antes de qualquer autoria de migration.
