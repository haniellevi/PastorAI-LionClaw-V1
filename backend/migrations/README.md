# Migrations

Este projeto usa migrations SQL imperativas e versionadas. Nenhuma migration é
aplicada automaticamente por merge, deploy ou inicialização do backend.

## Convenção de nomes

- Histórico `0001` a `0017`: numeração congelada, sem renomear ou reutilizar.
- Novas migrations: timestamp UTC no formato
  `AAAAMMDD_HHMMSS_slug.sql`.

Para criar o arquivo:

```bash
cd backend
python scripts/new_migration.py "add coluna x em pessoas"
```

O nome ordena o catálogo local, mas não prova que o arquivo foi aplicado em
qualquer ambiente. O histórico nativo do Supabase
`supabase_migrations.schema_migrations` e o ledger de controle do runner
`public.schema_migrations` são objetos diferentes e nunca são reconciliados por
inferência.

## Executor fail-closed

`scripts/apply_migrations.py` possui operações distintas:

- `list`: lista o catálogo local sem conexão;
- `status`: consulta somente um ledger público já seguro e exige prefixo íntegro
  com, no máximo, uma migration pendente;
- `harden-ledger`: endurece um ledger público histórico já existente, sem criar
  ou preencher entradas;
- `bootstrap-ledger`: cria somente o ledger público vazio no contrato
  owner-only final, sem ler ou copiar histórico;
- `apply`: aplica um único arquivo previamente aprovado, com basename, SHA-256
  e confirmação literal, somente quando o ledger já forma o prefixo seguro.

O destino é aceito exclusivamente pela variável de processo
`M06_MIGRATION_DATABASE_URL`. A CLI não aceita DSN em argumento e nunca deve
receber URL, senha, token ou host em conversa, documentação ou log.

O bootstrap exige PostgreSQL 17 e confirmação explícita:

```bash
cd backend
: "${M06_MIGRATION_DATABASE_URL:?injete a URL aprovada pelo canal secreto}"
python scripts/apply_migrations.py bootstrap-ledger \
  --confirm BOOTSTRAP_LEDGER
```

Esse comando não descobre o catálogo local, não consulta ou altera
`supabase_migrations`, não registra migrations e não autoriza `status` ou
`apply`. Em um ledger vazio com múltiplos arquivos locais, ambos continuam
bloqueados.

## Estado operacional atual

`bootstrap-ledger` foi integrado pela PR #323 e comprovado somente offline,
ainda não aplicado, sobre a base
`b43ad92028374fa6763ef10f5eb7a379afd3e7a2`: 42/42 testes unitários, 87/87 em
PostgreSQL 17-alpine descartável em duas execuções independentes e 87/87 em
Supabase PG17 17.6.1.159 descartável em duas execuções independentes, com
revisão de segurança `GO`. A suíte RLS completa, em execução serial limpa no
PostgreSQL 17 descartável, passou em 326/326, com 3803 deselecionados e 2
warnings preexistentes, em 162.77s. A suíte offline integral foi interrompida
após 5 min sem saída ou progresso; o resultado é `INCONCLUSIVO`, não verde nem
falha e não foi reclassificado. Os workflows Backend Tests da PR #323 e do
pós-merge concluíram com `SUCCESS`.

O merge `3a5789c784017ab15a43e28c4270d25af8618359` integrou o código em
`main`. A Vercel produziu Preview e Production automáticos do frontend; essa
metadata não prova deploy do backend, banco ou runtime.

Nenhuma execução ocorreu em DEV ou PROD. Não use `bootstrap-ledger`,
`harden-ledger`, `status`, `apply`, SQL Editor, `apply_migration`, `db push` ou
MCP para preencher, reaplicar ou reconciliar histórico em ambiente
compartilhado.

O pacote deny-state versionado e o verificador stdlib separado do runner, comprovados
offline sobre a base `cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`, foram
integrados pela PR #325, HEAD `d9595c3958fec98a875d15de2b6647d6b1de435e`, no
merge `ab7d09f07db96d5c63a2cc32dddf3f910e23bac2` em
`2026-08-28T20:18:08Z`. O estado é `INTEGRADO / COMPROVADO OFFLINE / DECISÕES
HUMANAS PENDENTES / NÃO APLICADO`. O contrato está em
[`2026-08-28-migration-history-reconciliation-contract.md`](../../docs/decisions/2026-08-28-migration-history-reconciliation-contract.md).
O verificador não acessa banco, rede, ambiente ou variáveis de ambiente, não
executa SQL, DML ou escrita e não infere migration aplicada. Um sucesso
estrutural conserva `OPERATIONAL_AUTHORIZATION=BLOCKED` e não libera qualquer
comando desta CLI.

A prova local preservada é `98/98` testes do verificador, `26/26` testes
documentais e `42/42` testes offline do runner: agregado de
`166 passed/45 skipped`. O template deny-state terminou bloqueado com exit `8`.

O capturador e o materializador desta PR candidata foram comprovados offline
sobre a base de catálogo
`656d1d9eebe90ad4b2cbb35c21939a6796c46bfe`, com 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.
O estado é `CAPTURADOR/MATERIALIZADOR CANDIDATO DA PR / COMPROVADO OFFLINE /
NÃO INTEGRADO / INVENTÁRIOS DEV/PROD AINDA NÃO CAPTURADOS / DECISÕES HUMANAS
PENDENTES / NÃO APLICADO`. A matriz focal concluiu `166/166`, incluindo dois
casos reais de PostgreSQL 17 em container descartável dedicado, e recebeu
revisão independente `GO`. CI verde e a suíte completa permanecem parte do
mesmo gate pré-merge. Não houve uso do Supabase local na porta `54322`, DEV,
PROD, rede, deploy, runner, DML, flag ou runtime.

O SQL allowlisted de captura tem SHA-256
`8b589e5dda722691fead34cbd63cab75a7a22f32e0cf4bdfe64d6cef603866ee`,
é somente um canal nominal e permite extrair apenas o `sanitized_capture` final.
O materializador offline recebe a captura e a chave HMAC por descritores de
arquivo independentes. O digest esperado do target binding entra somente pelo
argumento sanitizado `--expected-target-binding-sha256`; a fonte permanece
independente. `native.name` fica em `null`, e as saídas são criadas com modo
`0600` e `O_EXCL`. Os basenames exatos são
`migration-history-reconciliation-dev-evidence-v1.json` e
`migration-history-reconciliation-prod-evidence-v1.json`. Todo pacote permanece
bloqueado: o materializador começa por `OPERATIONAL_AUTHORIZATION=BLOCKED` e
produz `EVIDENCE_CAPTURED_UNREVIEWED`. O verificador só termina em
`HUMAN_EVIDENCE_BLOCKED` depois de validar a integridade e confirmar o ledger
nativo `PRESENT_COMPLETE` não vazio. Casos anteriores podem terminar em
`INVENTORY_BLOCKED` ou no motivo fail-closed correspondente.

O próximo gate é revisar e integrar esta PR com CI verde. Somente depois será
permitido executar, em gate separado e já autorizado, a captura somente leitura
de DEV e PROD, sem DML ou runner. `bootstrap-ledger`, `harden-ledger`, `status`,
`apply`, deploy, flag e runtime permanecem bloqueados. UV e CD permanecem fora.

## Transações especiais

Algumas migrations históricas com `ALTER TYPE ... ADD VALUE` possuem contrato
transacional próprio. O executor valida os bytes e recusa controles de
transação que possam quebrar a atomicidade. Não remova wrappers ou divida um
arquivo para fazê-lo passar; qualquer incompatibilidade exige revisão da
migration e um gate separado.
