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

## Próximo gate único

`SEPARATE_NOMINAL_DEV_READ_ONLY_PREFLIGHT_AUTHORIZATION` pode autorizar somente
o preflight de identidade de DEV, em leitura e com autorização separada. Não
autoriza captura, materialização de artefato, runner, DML, migration,
reconciliação, backfill, deploy, flag ou runtime. PROD está explicitamente
fora.
