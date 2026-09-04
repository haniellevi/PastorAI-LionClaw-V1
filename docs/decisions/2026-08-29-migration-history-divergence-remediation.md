# Proposta offline para remediar a divergência do histórico de migrations

**Estado:** `PROPOSTA OFFLINE / MANIFESTO DE FONTE CRIADO / REVISÃO TÉCNICA
CONCLUÍDA / REVISÃO INDEPENDENTE PENDENTE / AMBIENTES NÃO ATESTADOS / NÃO
APLICADA`

**Base:** `f73a631c632a1b37cea07073c91fe6ad2a81e995`

## Decisão que governa esta proposta

A revisão independente terminou em bloqueio. DEV possui ledger público com 33
linhas, 6 linhas nativas e deixa de formar o prefixo do catálogo na posição 25,
com oito posições divergentes. PROD não possui ledger público e contém 32
linhas nativas com nomes sanitizados como `null`. Nenhuma dessas observações
autoriza inferir aplicação.

O registro externo da revisão independente possui SHA-256
`18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133`.
O proprietário aceitou o bloqueio e autorizou apenas esta preparação offline;
o registro externo da decisão possui SHA-256
`0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240`.
Os registros brutos, nomes, contatos e assinaturas não são versionados.

## Princípio de correção

Histórico incompleto não deve ser “consertado” por preencher o ledger. Uma
correção segura precisa preservar os fatos legados, provar o estado estrutural
atual por evidência independente e estabelecer uma fronteira futura sem afirmar
que as 75 migrations foram aplicadas.

Por isso, esta proposta recomenda um corte de época controlado somente depois
de uma atestação completa do schema e das invariantes de dados. O corte futuro
não é um backfill, não torna os dois ledgers equivalentes e não apaga a
divergência histórica. Ele cria uma nova fronteira auditável para migrations
posteriores, em contrato ainda a desenhar e revisar.

## Alternativas

### Reconstrução forense completa

É a alternativa de maior fidelidade histórica quando existem registros
externos suficientes para cada migration. O material atual não oferece essa
prova, especialmente em PROD, e a alternativa permanece bloqueada até que
evidências independentes sejam apresentadas.

### Corte de época após atestação

É a recomendação para análise futura. Antes de qualquer implementação, exige:

1. manifesto offline e versionado de objetos, constraints, funções, policies,
   triggers, grants e invariantes de dados esperados;
2. revisão independente de segurança e arquitetura de banco;
3. missão separada e autorizada de captura somente leitura em cada ambiente;
4. comparação fail-closed entre manifesto e captura, sem inferir aplicação;
5. decisão humana explícita sobre o corte;
6. PR técnica separada para qualquer novo ledger, namespace ou mudança de
   runner;
7. autorização operacional separada para cada ambiente.

Qualquer ausência ou divergência mantém o processo bloqueado.

### Reconstrução do ambiente a partir do catálogo

É o fallback quando nem a história nem o estado estrutural puderem ser
atestados. Exige plano próprio para dados, indisponibilidade, rollback,
integridade, tenant, integrações e continuidade de negócio. Não está autorizada
por esta proposta.

## Contrato machine-readable

O arquivo
[`migration-history-divergence-remediation-proposal-v2.json`](../governance/migrations/migration-history-divergence-remediation-proposal-v2.json)
vincula os seis artefatos, os dois registros humanos opacos, os achados e os
gates futuros. Ele mantém todas as permissões operacionais em `false` e não é
entrada do runner.

`backend/scripts/apply_migrations.py` deve permanecer inalterado nesta missão.
O SHA-256 fixado do runner é
`36e63cde6751cd0cb33e1511091068b0b04f10029ace06703eead82e0e836c65`.
O verificador offline também permanece inalterado, no SHA-256
`9451cbe5054d8c0d7e2754d09dea7f3a9761e8585269ca783eea943dd785dfae`.
Nenhum novo subcomando, migration, marker ou bypass é criado.

O `v1`, SHA-256
`84614e0b140e38d07c11ed4ceb10025b3dbc85b121684da1e1ebdca6d0104e7d`,
permanece byte a byte como o texto ao qual se vinculam a revisão independente
e a decisão do owner já registradas. O `v2` o sucede sem reaproveitar essa
aprovação: declara a emenda, mantém a revisão independente atual pendente e
explicita a derivação canônica como gate separado.

## Manifesto de expectativas da fonte

O arquivo
[`migration-history-schema-expectation-manifest-v1.json`](../governance/migrations/migration-history-schema-expectation-manifest-v1.json)
fixa o catálogo versionado de 75 migrations, seu digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`,
âncoras críticas e os domínios que uma atestação futura precisará comparar. O
verificador offline
`backend/scripts/verify_migration_history_schema_expectation_manifest.py`
termina com `SCHEMA_EXPECTATION_MANIFEST_VERIFIED_SOURCE_ONLY`, mantendo
`OPERATIONAL_AUTHORIZATION=BLOCKED` e
`ENVIRONMENT_ATTESTATION_COMPLETE=false`.

Esse manifesto descreve somente o que a fonte versionada espera. SQL dinâmico,
condicional e mutações históricas impedem que uma leitura estática prove o
schema final de DEV ou PROD. Nenhum ambiente foi consultado nesta missão.
O objeto `offline_derivation_target` fixa PostgreSQL 17 a partir da imagem
descartável versionada em `.github/workflows/rls-integration.yml` e do SHA-256
desse workflow; não é observação de ambiente. O campo
`current_environment_version_attested` permanece `false`. Da mesma forma,
`declared_base_sha` é rótulo de contexto; o vínculo autoritativo dos bytes é o
digest do catálogo.

## Revisão técnica desta missão

A revisão técnica concluiu `PASS_FOR_SOURCE_MANIFEST_ONLY`: o desenho permanece
fail-closed, não altera o runner e não aprova o corte de época. Esta revisão foi
feita pelo mesmo executor que preparou o manifesto e está registrada como
`TECHNICAL_SELF_REVIEW_NOT_INDEPENDENT`; portanto, ela não substitui a revisão
independente de segurança e arquitetura de banco.

## Evidência offline vinculada ao commit

O artefato
[`migration-history-schema-expectation-test-evidence-b44c203-v1.json`](../governance/migrations/migration-history-schema-expectation-test-evidence-b44c203-v1.json)
registra a execução sobre o commit técnico exato
`b44c2030a73d5543bb326ca0922c082df30d6a42`: `264 passed, 47 skipped`.
O recorte contém seis módulos relacionados. Os 47 skips exigem PostgreSQL
descartável e não são tratados como evidência positiva. Bytecode e cache do
pytest ficaram desabilitados. Nenhum banco ou ambiente compartilhado foi
aberto, a suíte integral do backend não foi executada e
`operational_authorization` permanece `false`.

## Limites desta missão

Esta preparação não acessa DEV ou PROD, não usa rede, não executa SQL ou DML,
não cria ou preenche ledger, não aplica migration, não faz backfill, não altera
runner, deploy, flag ou runtime. `OPERATIONAL_AUTHORIZATION=BLOCKED` permanece
o único estado operacional válido.

## Evolução posterior registrada

A derivação canônica prevista por esta proposta foi reproduzida e verificada
somente offline, em PostgreSQL 17 descartável. A decisão, as duas execuções
idênticas e suas limitações estão em
[`2026-08-29-offline-canonical-schema-derivation.md`](2026-08-29-offline-canonical-schema-derivation.md).
Ela não atesta DEV, PROD, Data API ou Realtime e não modifica esta proposta,
os pacotes ou o runner. `OPERATIONAL_AUTHORIZATION=BLOCKED` permanece válido.

A PR #334, HEAD `a864730f0b678cca39cebfa6bb378243ba031cd6`, foi integrada no
merge `c8427b1a505c0aad2a5f675d3bf456ee33716690`; o Git registra
`commit date=2026-08-29T21:21:15Z`, e o GitHub registra
`mergedAt=2026-08-29T21:21:16Z`. Os seis checks da PR e os seis pós-merge
concluíram com `SUCCESS`; os detalhes da API do deployment automático Vercel
frontend Production `6160229001` estão na evidência detalhada em
[`decisão de derivação offline`](2026-08-29-offline-canonical-schema-derivation.md).
Os checks provam apenas o comportamento exercitado naquele SHA; a metadata do
deployment prova somente o frontend e não prova backend, banco, migration,
runtime ou atestação de ambiente.

O tooling posterior de atestação somente leitura foi implementado no commit
`be958ce96e65d3d497923b7f5f912676634e9587`, sobre a base
`1072e6a8e85d201a1c82f37a8ddeac5417300c49`. O tooling está documentado em
[`2026-08-30-read-only-environment-attestation-tooling.md`](2026-08-30-read-only-environment-attestation-tooling.md).
As provas terminaram em `81 passed` de `81` no foco offline,
`367 passed, 47 skipped` na seleção relacionada e `82 passed` de `82` no foco
PostgreSQL 17 TLS descartável. Sarah/Terra concluiu `GO`; o healthcheck de
Claude Opus passou, mas a revisão completa travou com `Execution error` e não
conta como revisão concluída.

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
O JSON Schema valida somente o envelope e exige o verificador Python; o HMAC é
apenas correlação e anti-swap, sem autorização humana nem observação direta do
project ref. Data API e Realtime permanecem
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

Em 2026-08-30, já no `main`
`64cc157d649256a4a9819741f4276c0420590fd1`, duas invocações DEV foram feitas
sob autorizações humanas nominais distintas e exclusivas, cada uma limitada a
`PROCESS_INVOCATION_ONLY`. O timestamp operacional preciso não foi preservado;
nenhum horário UTC foi inferido. Ambas terminaram com exit `7`,
`RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED`, `ROLLBACK_CONFIRMED=false` e
`CONNECTION_CLOSED=true`. Em ambas, `OPERATIONAL_AUTHORIZATION=false`,
`NEXT_STAGE_AUTHORIZED=false`, `CAPTURE_EXECUTED=false`,
`MATERIALIZATION_EXECUTED=false` e `PROD_ACCESSED=false`. Esses campos não
provam se houve conexão, não provam sucesso ou falha de autenticação e não
identificam a causa raiz.

O diagnóstico posterior passou em `2/2` no caminho full-main sobre PostgreSQL
17 TLS descartável e em `97/97` no foco offline. O runner permaneceu intacto,
SHA-256 `1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f`,
assim como o workflow, SHA-256
`80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf`.
A prova PG17 ampliada tem SHA-256
`ddbc092216604e65cf86070d409837c7d328da96116ae5ea8d0947195b421b9e`.
Essa prova local não reclassifica DEV nem determina a causa do bloqueio. A
evidência detalhada está em
[`diagnóstico do preflight de identidade de DEV`](2026-08-30-dev-identity-preflight-diagnostics.md).
Estado: `DUAS INVOCACOES DEV BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO
CONSULTADO / OPERACAO BLOQUEADA`.

A PR #342, HEAD `5076c47b19fffe503e823d68c6dadfc59b11ed5d`, integrou a
prova diagnóstica no merge `bc202da6c0ef83e03ded4392e508441cd4d6a188`, com
`mergedAt=2026-08-30T15:24:45Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Canonical `33319560819`, Environment Attestation PG17
`33319560923`, E2E `33319560908`, RLS `33319560769`, Backend `33319560836`,
Frontend `33319560781` e Tooling `33319560786`. A Vercel registrou o
deployment frontend Production `6168185324`, com status `17531418022`,
`state=success` e `created_at=updated_at=2026-08-30T15:25:32Z`. Essa metadata
prova somente o frontend e não prova backend, banco ou runtime.

A integração não repetiu o preflight, não consultou logs, não fez novo acesso a
DEV ou PROD e não determinou a causa do exit `7`. Runner e workflow permanecem
intactos. Estado: `INTEGRADO E COMPROVADO OFFLINE / DUAS INVOCACOES DEV
BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO CONSULTADO / OPERACAO
BLOQUEADA`.

Naquele recorte histórico, foi proposto o gate
`SEPARATE_NOMINAL_DEV_FAILURE_LOGS_READ_ONLY_REVIEW_AUTHORIZATION`. O gate
proposto não foi consumido. Ele exigiria uma autorização humana nova, nominal,
exclusiva e separada para uma única revisão read-only e sanitizada dos logs da
falha DEV. A fonte, os filtros e a janela temporal mínima ainda não foram
delimitados e precisariam constar da autorização antes de qualquer acesso;
nenhum horário é inferido. Nenhum log foi acessado nesta PR. O gate proposto
não autoriza retry, nova invocação DEV, consulta a
PROD, banco ou SQL, exportação ou persistência de logs, captura,
materialização, DML, reconciliação de ledger, corte de época, migration,
backfill, deploy, flag ou runtime. PROD continua fora. Posteriormente, esse
caminho foi supersedido pelos diagnósticos de fase e pelo probe transport-only
executados sob autorizações humanas nominais próprias. O identificador
permanece somente como registro histórico e não é gate corrente nem próximo
hoje.

A política de permissões foi implementada e comprovada offline pelo snapshot
privado descrito em
[`2026-09-03-trusted-repository-snapshot-policy.md`](2026-09-03-trusted-repository-snapshot-policy.md).

O gate
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE` foi
consumido exclusivamente para o candidato local descrito em
[`2026-09-03-migration-environment-attestation-executor-v2.md`](2026-09-03-migration-environment-attestation-executor-v2.md).
Ele faz identidade e captura na mesma conexão/PID, mas em duas transações e
dois snapshots `REPEATABLE READ READ ONLY` separados. Seu artefato v1 continua
bloqueado, não aprova o pacote v3 e não reclassifica DEV
`BLOCKED_LEDGER_DIVERGENCE` ou PROD `BLOCKED_EVIDENCE_INSUFFICIENT`.

O único estágio corrente global é
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`,
restrito à consulta remota somente leitura de `refs/heads/main`, ao preflight da
base, ao push da branch candidata, à abertura da PR e à observação do CI e do
Vercel Preview automáticos. Não autoriza merge, banco compartilhado, DEV, PROD,
migration, runner ou alteração de flags;
`operational_authorization=false` e `next_stage_authorized=false` permanecem
estritos.

Somente após a integração posterior sob gate próprio e o CI verde, o estágio
funcional futuro poderá ser
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_EXECUTOR_V2_EXTERNAL_TRUST_ANCHORS_OFFLINE`;
ele não é o estágio corrente nem está autorizado.
