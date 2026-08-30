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

Até a missão anterior, nenhuma execução havia ocorrido em DEV ou PROD. A
captura somente leitura documentada abaixo não altera esse estado de aplicação.
Não use `bootstrap-ledger`, `harden-ledger`, `status`, `apply`, SQL Editor,
`apply_migration`, `db push` ou MCP para preencher, reaplicar ou reconciliar
histórico em ambiente compartilhado.

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

O capturador e o materializador foram integrados pela PR #327, no merge
`f9201a06495fad138e313e4149ad9275ff896900`, e o hotfix da PR #328 foi integrado
no merge `04e5c1720bf89313718c4159a2ac9d0eeeed3c25`. O catálogo usado tem base
`656d1d9eebe90ad4b2cbb35c21939a6796c46bfe`, 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.

O SQL allowlisted de captura tem SHA-256
`8b589e5dda722691fead34cbd63cab75a7a22f32e0cf4bdfe64d6cef603866ee`,
é somente um canal nominal e permite extrair apenas o `sanitized_capture` final.
O materializador offline recebe a captura e a chave HMAC por descritores de
arquivo independentes. O digest esperado do target binding entra somente pelo
argumento sanitizado `--expected-target-binding-sha256`; a fonte permanece
independente. `native.name` fica em `null`. Na materialização local, as saídas
são originalmente criadas com modo `0600` e `O_EXCL`; depois do versionamento,
a proteção depende da sanitização e da ACL do repositório, não do modo do
checkout. Os basenames exatos são
`migration-history-reconciliation-dev-evidence-v1.json` e
`migration-history-reconciliation-prod-evidence-v1.json`. Todo pacote permanece
bloqueado: o materializador começa por `OPERATIONAL_AUTHORIZATION=BLOCKED` e
produz `EVIDENCE_CAPTURED_UNREVIEWED`. O verificador só termina em
`HUMAN_EVIDENCE_BLOCKED` depois de validar a integridade e confirmar o ledger
nativo `PRESENT_COMPLETE` não vazio. Casos anteriores podem terminar em
`INVENTORY_BLOCKED` ou no motivo fail-closed correspondente.

O estado atual é `INVENTÁRIOS DEV E PROD CAPTURADOS / REVISÃO INDEPENDENTE
BLOQUEADA CONCLUÍDA / DECISÃO OWNER-01 REGISTRADA / NÃO APLICADO`. Em PostgreSQL 17,
DEV registrou 33 linhas no ledger público e 6 no nativo em
`2026-08-28T22:43:11.454382Z`; PROD registrou o ledger público
`ABSENT_CONFIRMED`, com 0 linhas, e 32 linhas no nativo em
`2026-08-28T22:47:43.965243Z`. `native.name` permaneceu `null`. Os seis artefatos
foram originalmente materializados localmente com modo `0600` e `O_EXCL`;
versionados, sua proteção depende da sanitização e da ACL do repositório,
não do modo do checkout. Ambos os pacotes estão
`EVIDENCE_CAPTURED_UNREVIEWED`, terminaram no verificador com exit `8` e
`HUMAN_EVIDENCE_BLOCKED`, e a checagem conjunta terminou `CROSS_PACKAGE_OK`.
A matriz focal offline pós-captura passou com `163 passed, 2 skipped` em
`1.40s`; isso não é suíte integral nem reexecução PostgreSQL.

A PR #329 integrou e versionou os seis artefatos, com HEAD
`c5ae430aa865dbd6371953d43e4a4447ca8e6618`, no merge
`341f38a7f1c6993c74d85e99748cb60046cd4501` em `2026-08-29T00:04:50Z`. Os
cinco workflows da PR e os cinco pós-merge concluíram com `SUCCESS`. O merge
gerou o deployment automático Vercel frontend Production `6150482852`, com
`SUCCESS`, em `2026-08-29T00:05:33Z`. Essa metadata prova somente o frontend,
sem provar deploy manual ou do backend, banco ou runtime. A integração versiona
a evidência sanitizada já capturada, mas não revisa os inventários, não aplica
migration e não libera o runner ou qualquer autorização operacional.

A revisão independente bloqueada foi concluída e registrada sob o SHA-256
`18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133`;
ela bloqueou DEV por divergência do ledger e PROD por evidência insuficiente.
A decisão OWNER-01 registrada está vinculada pelo SHA-256
`0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240`,
manteve a autorização operacional falsa e abriu somente uma proposta técnica
offline. Os registros externos não são versionados.

A captura foi somente leitura, sem DML, runner, `bootstrap-ledger`,
`harden-ledger`, `status`, `apply`, deploy, flag ou runtime. O manifesto
estático de expectativas da fonte foi criado sobre a base
`7f18f7e8b44cd50e6f6033867fb97bfa9eb9c9e6`, com 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.
Ele é `SOURCE_LEVEL_EXPECTATION_ONLY`, não prova o schema final de DEV ou PROD
e permanece com `OPERATIONAL_AUTHORIZATION=BLOCKED`. A revisão técnica foi
feita pelo mesmo executor e não é independente.

A derivação canônica foi reproduzida e verificada somente offline, duas vezes,
em PostgreSQL 17 descartável, sobre a base
`07d2c05c687d1a0e8deeacbb7f8b16fbdd0e4e86`. A decisão, os 75/75 arquivos,
as provas A/B idênticas e os limites estão em
[`2026-08-29-offline-canonical-schema-derivation.md`](../../docs/decisions/2026-08-29-offline-canonical-schema-derivation.md).
Ela não atesta DEV, PROD, Data API ou Realtime e não libera este executor.
`OPERATIONAL_AUTHORIZATION=BLOCKED` permanece obrigatório.

A PR #334, HEAD `a864730f0b678cca39cebfa6bb378243ba031cd6`, foi integrada no
merge `c8427b1a505c0aad2a5f675d3bf456ee33716690`; o Git registra
`commit date=2026-08-29T21:21:15Z`, e o GitHub registra
`mergedAt=2026-08-29T21:21:16Z`. Os seis checks da PR e os seis pós-merge
concluíram com `SUCCESS`; os detalhes da API do deployment automático Vercel
frontend Production `6160229001` estão na evidência detalhada em
[`2026-08-29-offline-canonical-schema-derivation.md`](../../docs/decisions/2026-08-29-offline-canonical-schema-derivation.md).
Os checks provam apenas o comportamento exercitado naquele SHA; a metadata do
deployment prova somente o frontend e não prova backend, banco, migration,
runtime ou atestação de ambiente.

O tooling separado de atestação somente leitura foi implementado no commit
`be958ce96e65d3d497923b7f5f912676634e9587`, sobre a base
`1072e6a8e85d201a1c82f37a8ddeac5417300c49`. A decisão está em
[`2026-08-30-read-only-environment-attestation-tooling.md`](../../docs/decisions/2026-08-30-read-only-environment-attestation-tooling.md).
As provas terminaram em `81 passed` de `81` no foco offline,
`367 passed, 47 skipped` na seleção relacionada e `82 passed` de `82` no foco
PostgreSQL 17 TLS descartável. Sarah/Terra concluiu `GO`; Claude Opus passou no
healthcheck, mas a revisão completa travou com `Execution error` e não conta
como concluída.

A PR #337, HEAD `abf6f823336b81e93ec1c942dcd5a357d8ac797c`, integrou o tooling
no merge `278afb205a3b4735d4aeb66e2e585f71fd562ef7`, com
`mergedAt=2026-08-30T11:38:16Z`. Os sete workflows do push em `main`
concluíram com `SUCCESS`: Environment Attestation PG17 `33309430738`, Frontend
CI `33309430763`, Canonical Schema Derivation `33309430775`, Backend Tests
`33309430797`, Tooling Static Checks `33309430744`, E2E Critical `33309430731`
e RLS Integration `33309430799`.

A Vercel registrou o deployment frontend Production `6166209567`, com
`state=success`; o deployment e seu status registraram
`created_at=2026-08-30T11:39:02Z`. Essa metadata prova somente o frontend e não
prova backend, banco ou runtime. O estado corrente é
`INTEGRADO E COMPROVADO OFFLINE / AMBIENTES NÃO CONSULTADOS / OPERAÇÃO BLOQUEADA`.

Nenhum DEV ou PROD foi consultado e nenhum artefato ambiental foi produzido.
O JSON Schema valida somente o envelope; o verificador Python é obrigatório.
O HMAC é correlação e anti-swap, não autorização humana nem observação direta
do project ref. Data API e Realtime permanecem
`PLATFORM_SURFACES_UNATTESTED`, `OPERATIONAL_AUTHORIZATION=BLOCKED` e
`environment_attestation_complete=false`.

Sobre a base versionada `fe7dcd394bd1cfdc96204ad994bcba9f0c96adb4`, o runner
DEV preflight-only foi implementado e comprovado offline antes da integração.
Os SHA-256
congelados são: runner
`1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f`, testes
unitários `d96fab1afe99531e3cee0f84bc285876de303ed0265fa41c51f8da9a7bcab0a0`,
prova PG17 `ceecfe9afa09066e4863e93be556b8f92c00a2992e0a0aef3b4253458f6fc318`,
testes de atestação existentes
`68f9790a734f8adf78db8a716a5c2d99adad165f00737f922db90afa614b4ed8` e
workflow `80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf`.
Os unitários passaram em `210/210`; duas provas locais sequenciais no
PostgreSQL 17 TLS passaram em `1/1` para a atestação existente e `1/1` para o
runner com CA por FD.

A PR #340, HEAD `b29d3f494eabc3a04fe7f2c434758ad274f03930`, integrou o
runner no merge `82413edb884125d4d8f6e7946ffcaaf48ed8491c`, com
`mergedAt=2026-08-30T13:55:11Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: E2E `33315460948`, Frontend `33315460933`, Tooling
`33315460941`, RLS `33315460942`, Backend `33315460949`, Environment
Attestation PG17 `33315460934` e Canonical Schema Derivation `33315460939`.
A Vercel registrou o deployment frontend Production `6167369343`, com
`state=success`, em `2026-08-30T13:55:56Z`. Essa metadata prova somente o
frontend e não prova backend, banco ou runtime.

O contrato usa `TLS_MODE=VERIFY_FULL_EXPLICIT_CA` e exige que o digest da CA,
`TLS_CA_CERTIFICATE_SHA256`, esteja vinculado à autorização. O escopo
`PROCESS_INVOCATION_ONLY` exige nova autorização nominal para cada invocação.
O HMAC serve somente correlação e anti-swap e não substitui autorização humana.
O resultado produz zero arquivo, zero recibo, zero captura e zero
materialização. Os buffers de chave e nonce são zerados, os descritores são
fechados e os certificados TLS temporários são removidos após a prova. DEV e
PROD não foram consultados. PROD está explicitamente
fora. PROD continua fora. Estado:
`INTEGRADO E COMPROVADO OFFLINE / DEV/PROD NÃO CONSULTADOS / OPERAÇÃO
BLOQUEADA`.

O gate seguinte é `SEPARATE_NOMINAL_DEV_READ_ONLY_PREFLIGHT_AUTHORIZATION`.
Ele exige uma autorização humana nova e exclusiva para uma invocação
process-only (`PROCESS_INVOCATION_ONLY`) do preflight de identidade de DEV.
Não autoriza captura, materialização, DML,
reconciliação de ledger, corte de época, `bootstrap-ledger`, `harden-ledger`,
`status`, `apply`, migration, backfill, deploy, flag ou runtime. PROD continua
fora. UV e CD permanecem fora.

## Transações especiais

Algumas migrations históricas com `ALTER TYPE ... ADD VALUE` possuem contrato
transacional próprio. O executor valida os bytes e recusa controles de
transação que possam quebrar a atomicidade. Não remova wrappers ou divida um
arquivo para fazê-lo passar; qualquer incompatibilidade exige revisão da
migration e um gate separado.
