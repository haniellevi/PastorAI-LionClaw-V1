# Catálogo separado da projeção privada do runtime

**Data:** `2026-09-05`

**Estado:** `CANDIDATO OFFLINE / HEAD PRIVADO COM 1 ENTRADA / REPLAY PG17 COMPOSTO VALIDADO LOCALMENTE / GATE OPERACIONAL FECHADO / RUNTIME NÃO HABILITADO`

**Base auditada:** `64838cd3f1c6604ef091a940e19f704616d500b3`

## Decisão

A projeção privada do runtime terá um stream versionado separado do catálogo
V1. O catálogo público permanece com suas 75 migrations e com o digest
histórico `84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.
O artefato `private-runtime-catalog-head-v1.json` ancora esse digest e contém
atualmente um append privado de uma entrada candidata autenticada. A composição `75 + 1` foi
validada no replay composto; ela não transforma o catálogo V1 em “76”, nem
permite que o verificador V1 aplique um stream desconhecido.

O head privado atual contém a entrada candidata
`20260905_035815_load_private_runtime_turn_context.sql`, com SHA
`af8f8f88fef3a0db8db7453294dab8cdd948df7922fb55b51b2d8caefaf630fc` e digest
privado resultante `1644f51e4538700418ed3c9a507ed999ae61cbbc6295c5681873b32908bde080`.
SQL e head só podem ser materializados juntos pelo CLI real
`private_runtime_migration_authoring_v1.py`, nos subcomandos `draft` /
`prepare-head`, com `base_repository_sha`, parent autenticado, digest anterior,
digest resultante, posição e SHA dos bytes. Um prior arbitrário, drift, arquivo
extra, symlink, hardlink ou alteração dos bytes das 75 migrations falha fechado.
Preparar um head não autoriza aplicação. O header da candidata deve apontar para este ADR;
a política source-only de `2026-09-04` é apenas o predecessor histórico e não
substitui este contrato executável.

## Contrato executável

O contrato da função futura `agent_private.load_turn_context(uuid)` é uma tabela
com exatamente estas seis colunas, sem JSONB ou campos adicionais. IDs, estado e
flags continuam vínculos tenant-privados; este contrato não afirma ausência de PII:

| Coluna | Tipo |
|---|---|
| `igreja_id` | `uuid` |
| `conversation_id` | `uuid` |
| `pessoa_id` | `uuid` |
| `conversation_state` | `text` |
| `pessoa_optout` | `boolean` |
| `pessoa_sem_interesse` | `boolean` |

A função é `SECURITY DEFINER`, `STABLE`, `STRICT`, `row_security=on`, com
`search_path=pg_catalog, agent_private`, owner dedicado
`agent_projection_owner`. Esse owner é `NOLOGIN`, `NOINHERIT`, `NOSUPERUSER`,
`NOBYPASSRLS`, sem memberships e sem credenciais. Ele recebe somente `SELECT`
nas colunas necessárias de `public.pessoas` e `public.conversations` e
`EXECUTE` no helper; o runtime recebe apenas `USAGE` do schema e `EXECUTE` da
função, nunca grants diretos às tabelas.

`agent_private.current_tenant_id()` permanece o helper V1
`SECURITY INVOKER`/`STABLE`, com `search_path=pg_catalog`, corpo, owner e ACL
fechados. O grant explícito mínimo ao owner dedicado é verificado, assim como
o `EXECUTE` do helper público necessário para preservar as políticas web. O
tenant vem exclusivamente desse helper e do GUC server-owned
`app.tenant_igreja_id`; GUC ausente ou inválido falha de modo sanitizado.

O SQL usa `ALTER DEFAULT PRIVILEGES IN SCHEMA agent_private` somente para
revogar grants futuros de `PUBLIC`, `agent_runtime` e
`agent_projection_owner`. Esse comando é limitado ao schema e não altera os
defaults globais. Em PostgreSQL, o estado seguro pode não materializar uma
linha em `pg_default_acl` para esse schema; portanto, `pg_default_acl` vazio é
legítimo e não deve ser convertido em uma exigência artificial de uma linha
para cada tipo de objeto. A ausência da linha também não prova isolamento por
si só: cada função, policy, role e ACL instalada continua sujeita ao
inventário fechado e à verificação de grants perigosos. Qualquer função ou
objeto futuro precisa de grants explícitos e revisão própria; este ADR não
promete que o REVOKE por schema modifica defaults globais.

As relações públicas preservam suas políticas web. Não há alteração global de
`FORCE ROW LEVEL SECURITY`: o valor permanece `false`; policies específicas do
owner e uma barreira tenant-bound exigem o tenant correto sem ampliar a
autoridade web. Ausência, conversa de outro tenant ou conversa inexistente
retorna zero linhas. O runtime não recebe `SELECT`, `INSERT`, `UPDATE` ou
`DELETE` direto e qualquer DML é negado.

## Prova e CI

O verificador source-only executa sempre a prova histórica V1 autenticada e a
prova do stream privado separado. O runner sucessor
`replay_private_runtime_catalog_pg17.py` autentica os bytes das 75 migrations, o head privado
e a candidata; em uma instância nova, loopback e descartável
`migration_catalog_current_head_disposable`, aplica primeiro os 75 e depois o
append privado, sem ledger. Depois exige PG17, delta exato dos objetos
declarados, owner/roles, ACLs, default ACLs, RLS/policies, isolamento A/B,
`SELECT` direto negado e DML negado.

O workflow `private-runtime-catalog.yml` é acionado em `pull_request` e `push`
com sucesso obrigatório na revisão deste pacote. Isso não afirma
que branch protection ou rulesets estejam configurados. O workflow emite um
receipt fechado somente após todas essas pós-condições. O verificador do receipt
exige bytes, ordem, conjunto, digest, basename e SHA exatos; extras, duplicatas,
linhas contraditórias, spoof de resultado e receipt fora de arquivo regular
0600 são rejeitados. Os testes source-only cobrem o envelope e a cadeia de
fonte; a suíte PG17 sintética cobre ACL/policies, inclusive `OR true`, e rollback.
Em `2026-09-05`, o tooling executou e concluiu o replay composto real `75 + 1` em
container PG17.6 efêmero e loopback (`postgres:17.6-trixie@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929`),
com SQL `af8f8f88fef3a0db8db7453294dab8cdd948df7922fb55b51b2d8caefaf630fc`,
head `30a91f4db9e73586f353cf92f1e2d6d96865f7332d4d6ec6f8003c7e62751eb7`,
digest privado `1644f51e4538700418ed3c9a507ed999ae61cbbc6295c5681873b32908bde080`
e runner `b2238903a0522fd21d68ebc664c4281480e8a5ba1fbac8d7c7a36f28a6e6250c`.
Os 11 testes PG17 adversariais independentes e 55 testes unitários de delta passaram;
o receipt sanitizado foi verificado com hash
`2296f772204c6585af245a158f9f40fff27c127f891a5e14ad275ce4f80993f2`.
Isso é evidência local, não prova de CI remoto ou de uma PR aberta.

## Rollback, riscos e limites

Antes de conectar, a autoria e o runner rejeitam fonte não autenticada, head
inconsistente, alvo compartilhado, DSN fora de loopback ou banco com nome errado.
Após conectar, o runner exige servidor PG17, schema/banco fresco, roles
permitidas e transação ociosa antes de aplicar qualquer SQL. Depois de cada
aplicação, valida o delta exato declarado; se uma falha ocorrer enquanto houver
transação aberta, o runner emite `ROLLBACK` SQL explícito, exige sessão ociosa e
preserva o erro original. Isso não desfaz migrations já commitadas; com qualquer
falha não há receipt nem instalação do head. O descarte do banco/serviço efêmero
é responsabilidade da infraestrutura do job ou orquestrador, não do runner.
Uma correção futura deve ser um novo append privado ou compensação versionada
revisada, nunca reescrita dos bytes das 75 migrations ou do append já aprovado.

Isso prova somente fonte autenticada e, quando executado, reprodutibilidade em
PG17 descartável. Não prova migration aplicada em DEV/PROD, banco compartilhado,
credencial, login, provisionamento, flag, deploy, consentimento, legalidade ou
produção. O runner novo é deliberadamente distinto do stub source-only V5;
V5 permanece histórico e não é reclassificado como replay real.

O runtime permanece sem caller operacional: uma leitura válida ainda termina
em `runtime_effects_unavailable`; ausência, erro ou shape inválido termina em
`runtime_projection_unavailable`. Não há LLM, envio, writer, commit, worker ou
efeito vivo.

## Gate

O único gate futuro deste recorte é
`OWNER_AUTHORIZE_PRIVATE_RUNTIME_PROJECTION_ENVIRONMENT_PREFLIGHT`, atualmente
fechado. Ele autoriza somente preflight nominal do ambiente conforme runbook;
não autoriza aplicar SQL, ativar o agente ou enviar mensagens. Esta decisão não abre gate legal, de consentimento, credencial,
ambiente compartilhado ou canário; esses efeitos continuam sem autorização
nominal.

## Referências

- [`2026-09-04-private-runtime-migration-policy-v2.md`](2026-09-04-private-runtime-migration-policy-v2.md), política V5 source-only preservada;
- [`private-runtime-catalog-head-v1.json`](../governance/migrations/private-runtime-catalog-head-v1.json), head separado;
- `backend/scripts/private_runtime_migration_authoring_v1.py`, autoria e `prepare-head`;
- `backend/scripts/private_runtime_catalog_v1.py`, catálogo fechado;
- `backend/scripts/replay_private_runtime_catalog_pg17.py`, replay composto;
- `backend/scripts/verify_private_runtime_pg17_receipt.py`, receipt fechado;
- `.github/workflows/private-runtime-catalog.yml`, CI obrigatório.
