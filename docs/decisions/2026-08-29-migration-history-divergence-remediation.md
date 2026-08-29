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

## Próximo gate único

A derivação canônica prevista por esta proposta foi reproduzida e verificada
somente offline, em PostgreSQL 17 descartável. A decisão, as duas execuções
idênticas e suas limitações estão em
[`2026-08-29-offline-canonical-schema-derivation.md`](2026-08-29-offline-canonical-schema-derivation.md).
Ela não atesta DEV, PROD, Data API ou Realtime e não modifica esta proposta,
os pacotes ou o runner. `OPERATIONAL_AUTHORIZATION=BLOCKED` permanece válido.

Antes do merge, a exigência é revisão e CI dedicado verde desta PR.
Depois da integração, o único gate será
`SEPARATE_READ_ONLY_ENVIRONMENT_ATTESTATION`, em missão e autorização próprias.
Ele não autoriza DML, reconciliação de ledger, corte de época, alteração ou
execução do runner, migration, backfill, deploy, flag ou runtime.
