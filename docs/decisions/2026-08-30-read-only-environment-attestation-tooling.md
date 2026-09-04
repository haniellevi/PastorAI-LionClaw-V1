# Tooling separado de atestação de ambiente somente leitura

**Data:** 2026-08-30

**Estado:** `INTEGRADO E COMPROVADO OFFLINE / AMBIENTES NÃO CONSULTADOS / OPERAÇÃO BLOQUEADA`

**Base técnica:** `1072e6a8e85d201a1c82f37a8ddeac5417300c49`

**Commit técnico:** `be958ce96e65d3d497923b7f5f912676634e9587`

## Decisão

Foi implementado um capturador e comparador separado do runner de migrations para
preparar uma futura atestação nominal de schema. O tooling não aplica nem
repara migrations, não cria ou preenche ledgers e não autoriza DML, backfill,
deploy, flag ou runtime.

Esta missão foi estritamente offline. Nenhuma consulta foi feita a DEV ou PROD
e nenhum artefato ambiental foi produzido. O estado continua
`OPERATIONAL_AUTHORIZATION=BLOCKED`, com
`environment_attestation_complete=false`.

## Contrato técnico versionado

O contrato é composto por:

- preflight de identidade em
  [`migration-history-environment-identity-preflight-v1.sql`](../governance/migrations/migration-history-environment-identity-preflight-v1.sql);
- captura estrutural e invariantes em
  [`migration-history-environment-attestation-capture-v1.sql`](../governance/migrations/migration-history-environment-attestation-capture-v1.sql);
- perfil allowlisted em
  [`migration-history-environment-attestation-profile-v1.json`](../governance/migrations/migration-history-environment-attestation-profile-v1.json);
- envelope JSON em
  [`migration-history-environment-attestation.schema.json`](../governance/migrations/migration-history-environment-attestation.schema.json);
- materializador e verificador separados em
  [`materialize_migration_history_environment_attestation.py`](../../backend/scripts/materialize_migration_history_environment_attestation.py)
  e
  [`verify_migration_history_environment_attestation.py`](../../backend/scripts/verify_migration_history_environment_attestation.py).

Uma captura futura só pode usar PostgreSQL 17 com TLS, transação
`REPEATABLE READ READ ONLY`, `current_user=session_user`, uma conexão e um
snapshot, além de visibilidade integral comprovada por `rolsuper` ou
`rolbypassrls` com `row_security=off`. O preflight, a metadata e os oito
invariantes são vinculados à mesma prova de sessão. O `ROLLBACK` é obrigatório.

O comparador cobre 14 domínios estruturais contra o fingerprint canônico
offline. Extensões extras e versões permanecem observacionais; owners fora da
normalização permitida produzem contagem e hash e bloqueiam. Os ledgers nativo
e público formam domínio separado. Data API e Realtime permanecem
`PLATFORM_SURFACES_UNATTESTED`.

Os oito invariantes têm seleção, tabelas e SHA-256 allowlisted. Drift
estrutural impede preparar queries de dados e produz oito resultados `UNKNOWN`
com zero checks. Erro SQL recuperável fica isolado por savepoint e produz
`ERROR`; perda de conexão, transporte, sessão ou falha de rollback aborta tudo
sem artefato parcial. `APPEND_ONLY_AUDIT_INTEGRITY` permanece `UNKNOWN` por
contrato, porque um snapshot não prova imutabilidade histórica.

O materializador exige diretórios e arquivos privados, recusa symlink,
hardlink e troca de inode, valida os mesmos bytes por descriptors seguros e
remove o alvo parcial quando a continuidade nominal falha. A saída é
sanitizada e não contém DSN, host, usuário, OID, timestamp ou dados de negócio.

## Limites deliberados

O JSON Schema valida o envelope estrutural e os valores fixos que consegue
expressar. Ele não substitui a validação semântica completa. O verificador
Python é obrigatório para aceitar qualquer artefato.

O HMAC pré-captura serve somente para correlação e proteção anti-swap entre a
autorização registrada, o ambiente declarado, o alvo esperado sanitizado, a
identidade transitória e o nonce. Ele não concede autorização humana e não
prova observação direta do project ref. Identidade bruta só pode existir no
canal transitório privado e nunca no artefato.

O tooling permanece separado de `apply_migrations.py`. Nenhum estado produzido
por ele pode liberar runner, `bootstrap-ledger`, `harden-ledger`, `status`,
`apply`, migration, reconciliação, corte de época, DML, backfill, deploy, flag
ou runtime.

## Evidência técnica

- prova focal offline: `81 passed` de `81`;
- seleção relacionada: `367 passed, 47 skipped`;
- prova focal PostgreSQL 17 com TLS e alvo descartável: `82 passed` de `82`.

Sarah, executada em Codex Terra, concluiu `GO` técnico. O healthcheck de Claude
Opus passou, porém a revisão completa travou com `Execution error`; portanto,
ela não conta como revisão concluída e não substitui o parecer Sarah/Terra.
Skips não são evidência positiva e nenhuma dessas provas atesta DEV ou PROD.

## Integração e CI pós-merge

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
prova backend, banco ou runtime. Nenhum DEV ou PROD foi consultado e nenhum
artefato ambiental foi produzido. `OPERATIONAL_AUTHORIZATION=BLOCKED` e
`environment_attestation_complete=false` permanecem obrigatórios.

## Evolução posterior registrada

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
não autoriza retry, nova invocação DEV, consulta a PROD, banco ou SQL,
exportação ou persistência de
logs, captura, materialização, DML, migration, reconciliação, backfill, deploy,
flag ou runtime. PROD continua fora. Posteriormente, esse caminho foi
supersedido pelos diagnósticos de fase e pelo probe transport-only executados
sob autorizações humanas nominais próprias. O identificador permanece somente
como registro histórico e não é gate corrente nem próximo hoje.

Na worktree atual, a árvore de migrations foi normalizada localmente para
diretórios `0755` e arquivos `0644`; o snapshot privado descrito em
[`2026-09-03-trusted-repository-snapshot-policy.md`](2026-09-03-trusted-repository-snapshot-policy.md)
comprova offline somente esse recorte. Isso não é uma correção universal ou
durável: os ancestrais do workspace e do repositório principal permanecem
`0775`, e o `chmod` local pode não sobreviver a um novo checkout. O P2 global
de permissões continua aberto.

O gate
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE` foi
consumido exclusivamente para o candidato local descrito em
[`2026-09-03-migration-environment-attestation-executor-v2.md`](2026-09-03-migration-environment-attestation-executor-v2.md).
Ele faz identidade e captura na mesma conexão/PID, porém em duas transações e
dois snapshots `REPEATABLE READ READ ONLY` separados, cada qual encerrado por
`ROLLBACK`. O executor tem prova unitária offline; sua prova PG17 descartável
está implementada e ainda depende de execução sem skips no CI do commit
candidato. Não houve credencial, captura viva, DEV, PROD, migration ou runner.
A falha DEV histórica em `TLS_HANDSHAKE` continua sem causa determinada.

O gate
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`
foi proposto no recorte do executor v2, mas não foi consumido. Depois do Commit
A local `9b9395e29cc821d6808738a30a6afe367d4ffbea`, ele foi substituído pela
consolidação
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_SAFETY_R1`, agora o
único estágio global corrente, fechado e não autorizado. Seu eventual consumo
fica restrito à consulta remota somente leitura de `refs/heads/main`, ao
preflight da base, ao push da branch candidata, à abertura da PR e à observação
do CI e do Vercel Preview automáticos. O commit local não afirma integração, CI
remoto ou estado de ambiente. O gate consolidado não autoriza merge, banco
compartilhado, DEV, PROD, migration, runner ou alteração de flags;
`operational_authorization=false` e `next_stage_authorized=false` permanecem
estritos.

O estágio funcional
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_EXECUTOR_V2_EXTERNAL_TRUST_ANCHORS_OFFLINE`
continua futuro, não corrente e não autorizado; a consolidação atual não o
consome nem o antecipa.
