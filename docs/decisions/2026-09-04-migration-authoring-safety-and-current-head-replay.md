# Autoria segura e replay do head corrente de migrations

**Data:** `2026-09-04`

**Estado:** `IMPLEMENTADO E INTEGRADO EM MAIN (PR #366, MERGE 1b233e5) /
CI E PG17 DESCARTÁVEL COMPROVADOS / SEM APLICAÇÃO EM AMBIENTE
COMPARTILHADO / DEV E PROD BLOQUEADOS`

**Base:** `947af39d35544700188461d8c99332df70b57e07`

**Commit local de implementação:**
`9b9395e29cc821d6808738a30a6afe367d4ffbea`

**Merge em `main`:** `1b233e5156ab671d0b56ab705b35f4e5d2011937`, com parent
base `c2fb16ad9a6b028c317c56a0b02c4362ae903e26` e parent da PR
`ef03ae1b51e1d85e8064267646ebeea87fd52b12`.

## Problema

O catálogo de 75 migrations já impedia alteração do prefixo histórico, mas
isso não encerrava a cadeia de segurança para uma migration nova. Restavam
quatro lacunas de código-fonte:

1. o helper de autoria criava apenas um arquivo por nome e não vinculava de
   forma transacional o SQL, a intent e o head candidato ao SHA-base;
2. o verificador longitudinal ainda precisava operar sobre snapshots privados
   autenticados do commit corrente e de sua base, incluindo a evolução normal
   depois do primeiro append;
3. o runner histórico descobria `*.sql` fora do head aprovado e continuava
   tecnicamente invocável como entrypoint direto;
4. não havia replay obrigatório do head corrente em PostgreSQL 17 descartável,
   nem prova do caminho real de uma 76ª migration `TENANT`.

Resolver essas lacunas de fonte não equivale a reconciliar os ledgers vivos,
resolver TLS, atestar DEV/PROD, decidir cutover ou aplicar SQL.

## Decisão

### Autoria em duas fases

`backend/scripts/new_migration.py` passa a expor somente o fluxo explícito
`draft` e `prepare-head`. Ambos exigem o SHA-base completo e autenticam Git,
head, schema, verificador e o próprio helper antes de produzir evidência.

`draft` cria exatamente um SQL com exclusão atômica, `O_NOFOLLOW`, lock
cooperativo e modo inicial `0600`. A primeira linha contém a intent JSON exata
`PASTORAI_MIGRATION_INTENT_V1`; enquanto o marcador de rascunho incompleto ou
qualquer campo obrigatório faltar, a preparação falha fechada.

A fronteira v1 aceita somente `TENANT`. Ela exige relações afetadas, controles
de tenant, referências de decisão, recuperação/compensação e nodeids PG17 e
cross-tenant. `GLOBAL` permanece recusado até possuir contrato e suíte próprios.

`prepare-head` calcula o lote append-only e devolve o head candidato, mas não o
instala. SQL e head precisam entrar juntos na mesma árvore Git, filha do parent
esperado. Isso mantém compare-and-swap sob responsabilidade do publisher
revisado e impede que o helper transforme geração local em autorização.

### Snapshot e CI longitudinal

O verificador de CI autentica os commits e seus parents pelos bytes dos objetos
Git, materializa snapshots privados do commit corrente e da base e mantém um
witness completo antes e depois dos validadores. Caminhos protegidos são
rejeitados no manifesto autenticado antes de `git archive`.

Uma alteração sem migration exige head byte-idêntico à base. Um append exige
exatamente um lote e uma migration terminal, intent completa e parent correto.
Após o primeiro append, mudanças posteriores sem nova migration continuam
válidas sem fabricar outro lote.

O verificador histórico `verify_migration_catalog_head.py` permanece
byte-idêntico, com SHA-256
`2fe1a93bf9c9116426683e7fd86c4f7b7c20753f7ce11a8282d9ca06087ac30d`.
A API aditiva `validated_migration_catalog_snapshot.py` autentica esses bytes
por descritor antes de executá-los e expõe somente uma visão source-only.

### Runner catalog-bound

`backend/scripts/apply_migrations.py` permanece byte-idêntico no SHA-256
`36e63cde6751cd0cb33e1511091068b0b04f10029ace06703eead82e0e836c65`
para preservar a cadeia histórica. Ele não é mais um entrypoint permitido.

`apply_migrations_catalog_bound_v2.py` autentica por descritor a API de snapshot
e o runner legado, e vincula basename, posição, tamanho e hash de cada SQL ao
head validado. Nesta versão, apenas `list` retorna zero. `status`,
`harden-ledger`, `bootstrap-ledger`, `apply` e até `--help` falham antes de DSN
ou conexão. A invocabilidade técnica do arquivo legado continua um risco
residual; documentação e ausência de credencial não são uma sandbox.

### Replay em PostgreSQL 17 descartável

O workflow possui jobs separados e frescos para:

1. verificar a evolução source-only;
2. reproduzir o head corrente no PostgreSQL
   `17.6-trixie` fixado por digest e exposto somente em loopback;
3. executar todos os nodeids declarados por migrations append-only;
4. executar a suíte de guardas e validar seu JUnit.

O checkout torna-se somente leitura antes de executar o replay ou testes
candidatos. Receipts têm limite, formato exato e supervisores stdlib sob
`python -I -S`; os executores PG17 e de testes usam `python -I -P`. O primeiro
job source-only ainda usa `python -P -B`, sem `-I`; isso permanece P2 e não é
alterado nesta reconciliação porque a extensão v4 ancora os bytes exatos do
workflow do Commit A. Jobs que executam testes candidatos são terminais e não
alimentam outra decisão de segurança.

O replay inventaria todas as tabelas e partições `public` antes e depois de
cada append `TENANT`. Relação nova precisa estar declarada e terminar com
`igreja_id NOT NULL`, RLS habilitada e forçada, sem ACL direta de `PUBLIC` e
com policy restritiva tenant-bound para `ALL`. Drop/rename, enfraquecimento e
mudança de fronteira não declarada falham fechados. Fraquezas históricas
inalteradas não são reclassificadas como conformes.

## Limites explícitos da prova

O replay não prova SQL arbitrário. A análise automática não cobre outros
schemas, views/materialized views, foreign tables, funções ou operadores,
triggers, roles/memberships, `BYPASSRLS`, ownership, grants a roles nomeadas,
schema/default ACLs ou equivalência semântica ampla. DML e DDL que preservem os
cinco sinais resumidos também exigem revisão humana. Coleta e execução de um
nodeid não provam, sozinhas, que o teste é relevante para o SQL.

O serviço PostgreSQL descartável é evidência de reprodutibilidade local/CI;
não é DEV, PROD nem o banco Supabase de qualquer igreja.

## Provas no commit local

O commit `9b9395e` é filho direto de `947af39` e contém somente código,
workflow, testes e documentação dessa camada. A verificação focal terminou em
`274 passed, 6 skipped`; os seis casos PG17 opt-in executaram em instância
descartável exata e terminaram em `6 passed, 94 deselected`.

O replay integral das 75 migrations no PostgreSQL 17 descartável produziu:

```text
RESULT=MIGRATION_CATALOG_CURRENT_HEAD_REPLAYED_PG17_DISPOSABLE
CATALOG_MIGRATION_COUNT=75
CATALOG_DIGEST_SHA256=84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f
POSTGRESQL_MAJOR=17
```

O E2E construiu uma 76ª migration sintética a partir dos 75 bytes reais. O
caso forte foi aceito; relação declarada fraca, relação forte não declarada e
relação adicional sem `igreja_id` foram recusadas.

Após o commit, o verificador percorreu o caminho Git real com current SHA
`9b9395e` e prior SHA `947af39`, terminando em:

```text
RESULT=MIGRATION_CATALOG_CI_VERIFIED_OFFLINE
EVENT_NAME=push
CATALOG_MIGRATION_COUNT=75
CATALOG_DIGEST_SHA256=84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f
HISTORICAL_CONSUMERS=VERIFIED_BLOCKED_ONLY
OPERATIONAL_AUTHORIZATION=BLOCKED
NEXT_STAGE_AUTHORIZED=false
```

Duas revisões independentes concluíram `P0=0`, `P1=0` para a consolidação
local. Durante a revisão foram encontrados e corrigidos antes do commit: ruído
do pytest contaminando o receipt de sete linhas e invisibilidade de tabela nova
sem `igreja_id` no delta. Ambos possuem testes de regressão.

## Extensão de governança v4

A proposta
`migration-history-divergence-remediation-proposal-v4.json` é uma extensão
aditiva e source-only da proposta v3. Ela não substitui nem reinterpreta os
bytes, as evidências de ambiente ou a decisão de cutover de v1-v3. Seu anchor é
o Commit A `9b9395e`; todas as permissões, em 17 campos, permanecem `false`, DEV e
PROD preservam seus bloqueios anteriores, a revisão independente v3 continua
pendente e nenhum cutover é declarado.

O pacote não fixa contagem ou digest do catálogo. O verificador autentica a
API de snapshot e os artefatos do Commit A, lê duas vezes o catálogo validado e
exige igualdade exata entre as duas leituras. Um pacote válido continua
bloqueado, termina com exit `8` e emite apenas o receipt source-only de seis
linhas. O workflow separado `migration-divergence-v4.yml` valida esse contrato
sem segredo, DSN, banco, runner ou ambiente compartilhado.

Os artefatos locais da extensão foram verificados em `61 passed` e o
verificador direto produziu
`RESULT=BLOCKED_MIGRATION_DIVERGENCE_V4:SOURCE_EXTENSION_VERIFIED`, com
`OPERATIONAL_AUTHORIZATION=BLOCKED` e `NEXT_STAGE_AUTHORIZED=false`. Os hashes
SHA-256 são:

- proposta: `92b1c33ab3e2cd0a6c9b5ad486a317c229d7aefc7c60da88913716d58345e6ac`;
- schema: `e10d8922a68a6f475191330dbecf0c00b2e5ffccf03e9fb4726bdcb30c4d494f`;
- verificador: `3cb09957b283b254bb88b97456e065a18f390d707fcbd77c71530f8052266af3`;
- testes: `34d77cf7aa0b3c8b67d01f59296947dec86bd4028fcecd719b7493202b8d3a2d`;
- workflow: `7cbc0c47e527e5c7a5b56c6450d159ac49946793dd60fba6559b601fb5f3e27d`.

Durante a validação de CI da própria PR, os workflows descartáveis foram
corrigidos para usar loopback literal, para separar os SHAs exclusivos de
`pull_request` e `push` e para manter os guards de replay que exigem cluster
fresco no job PG17 dedicado, fora da suite RLS que cria roles globais. Os pins
v4, o manifesto de expectativa de schema e o pin transitivo do executor de
atestações v2 foram então recalculados antes da integração. A correção preserva
todos os bytes v1--v3, as permissões bloqueadas e o estado de DEV, PROD e
cutover.

Essa extensão organiza a prova de fonte; não resolve divergência de ledger,
TLS, drift manual, Data API, Realtime, revisão v3, trust anchors externos,
anti-replay, cutover ou aplicação em ambiente vivo.

O SHA do repositório dentro do v4 é uma âncora declarada: a revisão confirmou
separadamente no Git que os hashes pertencem ao Commit A, mas o verificador v4
não consulta objetos Git para provar essa associação em runtime. Seu leitor
autentica o descritor final e os bytes, porém não prende por file descriptor
toda a cadeia de diretórios nem revalida a entrada nomeada depois da leitura.
Esses dois limites permanecem P2 local/de trust e não autorizam usar o pacote
como atestado operacional.

## Permissões e estado operacional

Nesta worktree foram observados diretório da worktree e `backend/migrations`
em `0755`, com SQL histórico em `0644`. Essa observação é local e não durável.
Os ancestrais `/home/raniel-linux/workspace` e o repositório principal
permanecem `0775`; outros worktrees e consumidores legados não foram
normalizados. O P2 global de permissões continua aberto.

O estado vivo não foi consultado nem alterado:

- DEV permanece `BLOCKED_LEDGER_DIVERGENCE`;
- PROD permanece `BLOCKED_EVIDENCE_INSUFFICIENT`;
- a falha histórica DEV em `TLS_HANDSHAKE` continua sem causa determinada;
- presença/definição dos sete índices manuais de DEV permanece não atestada;
- Data API, Realtime e comportamento append-only vivo exigem evidência própria;
- revisão independente da proposta v3, trust anchors externos, anti-replay,
  cutover e aplicação continuam pendentes.

O gate de revisão remota desta frente permitiu o push e a abertura da PR #366.
Ela foi integrada por merge commit
`1b233e5156ab671d0b56ab705b35f4e5d2011937` (parent 1 `c2fb16ad`, parent 2
`ef03ae1b`). Os 12 check-runs pós-merge concluíram com sucesso, incluindo
replay/guards PG17, RLS, backend e E2E. O deployment Vercel Production
`6262210648` concluiu com sucesso e comprova somente o frontend.

O merge não autoriza nem comprova operação de banco. Não houve migration
aplicada, runner contra banco compartilhado, acesso a DEV/PROD, alteração de
flag, deploy manual ou runtime vivo. `operational_authorization=false` e
`next_stage_authorized=false` continuam estritos.

## Rollback

Como não houve efeito vivo, o rollback do código integrado exige uma nova PR
revisada; nenhum ledger deve ser preenchido, reescrito ou inferido para
“alinhar” o ambiente ao catálogo.

## Próximo gate único

`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_SAFETY_R1` foi consumido
exclusivamente para preflight remoto, push, abertura da PR #366 e observação do
CI/Preview. O gate de continuidade desta reconciliação documental é
`OWNER_AUTHORIZE_COMMIT_MIGRATION_SAFETY_POSTMERGE_RECONCILIATION_R1`; ele não
autoriza banco compartilhado, DEV, PROD, captura viva, migration, runner,
cutover, deploy manual ou alteração de flags.
