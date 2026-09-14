# Revalidação local do catálogo E4b

Data da evidência: 2026-09-14T14:59:49-03:00.

## Primeiro recibo, preservado

`FAILED_LOCAL_REVALIDATION`. A correção de fonte do catálogo passou os guardas estáticos, o CI de catálogo, os testes de head e snapshot, a suíte E4b/V3 de fonte, o guarda de privacidade e o guarda de replay. A revalidação não atesta o replay direto 77 nem os 18 oráculos E4b em PostgreSQL 17, e a suíte offline completa do backend terminou com falhas. Não houve alteração de código, SQL, catálogo, manifesto, flags ou ficha.

## Identidade e limites

| Campo | Evidência |
| --- | --- |
| Missão | `M-2026-09-14-e4b-catalog-chain-integration-readiness-offline` |
| Branch | `rebase/e4b-catalog-chain-readiness-20260914` |
| Candidato | `36999c2f9bfca8035afb886509440fc3760d9154` |
| Base e `origin/main` local | `615408514103be1d67bcafa182b5b3b05f1c3e73` |
| Estado no preflight | limpo |
| Runtime local pinado | Python 3.13.14, pytest 9.1.0, SQLAlchemy 2.0.50 |

O candidato foi confirmado por `git rev-parse HEAD`. A correção de identidade foi recebida antes de qualquer teste desta revalidação: nenhuma evidência abaixo é atribuída ao SHA expandido incorretamente. O ref local `origin/backup` não resolveu durante a coleta, portanto não foi usado como evidência.

Foram lidos `CORRECTION-REPORT.md`, `REBASE-REPORT.md`, o diff entre `c2157665ce20982594ddc42c729b039e4a94e4b8` e o candidato correto, os workflows locais e o runbook/intent E4b aplicável. O diff confirmado atualiza a âncora de base, o catálogo e os testes associados a 76/77. O recibo histórico em `PG17-AND-TEST-REPORT.md` permaneceu intacto.

Não foram usadas rede externa, credenciais reais, ambientes DEV/PROD, `apply_migrations.py`, commit, push, PR, merge ou qualquer ativação. O PostgreSQL usado abaixo foi local, sintético e descartável.

## Integridade da fonte

| Artefato | SHA-256 |
| --- | --- |
| `docs/governance/migrations/migration-catalog-head-v1.json` | `88e588660f995f774fe298d2bd4e5ea80d399006379661156b7eff28a6940a57` |
| `backend/migrations/20260910_142830_add_e4b_consent_persistence.sql` | `64c031beea4d74feed83337ea623173d0f8d848c685ffcf5365b279a6ea7d1fd` |
| `backend/scripts/replay_migration_catalog_current_head_pg17.py` | `753abf57747de9a28f6192617dfd7ea348cb7adf302d7acbd57f280de3d8ce3f` |

O verificador de CI de catálogo retornou exit 0, 77 migrations e digest `162854e0f753f5ad867aacae6b450d46d5c4bd68f8c3089be144d133ddc73801`. Manteve `HISTORICAL_CONSUMERS=VERIFIED_BLOCKED_ONLY`, `OPERATIONAL_AUTHORIZATION=BLOCKED` e `NEXT_STAGE_AUTHORIZED=false`.

## Checks de fonte e guardas

| Check | Resultado |
| --- | --- |
| `verify_migration_catalog_ci.py` com candidato e base exatos | exit 0 |
| `test_migration_catalog_ci.py` completo | 35 aprovados, exit 0 |
| `test_migration_catalog_head.py` e `test_validated_migration_catalog_snapshot.py` completos | 80 aprovados, exit 0 |
| suíte E4b/V3 de fonte | 156 aprovados, exit 0 |
| guarda de privacidade de contato | 13 aprovados, exit 0 |
| guarda de replay de catálogo PG17 | 100 aprovados, exit 0 |
| `git diff --check` contra a base e no worktree limpo | exit 0 nos dois casos |

## Replay 77 e oráculos PG17

O entrypoint autorizado foi invocado diretamente, sem contêiner pré-criado e com a confirmação exigida. Retornou exit 5 com `MIGRATION_CATALOG_CURRENT_HEAD_REPLAY_BLOCKED:DISPOSABLE_LOOPBACK_TARGET_REQUIRED`, além de `OPERATIONAL_AUTHORIZATION=BLOCKED` e `NEXT_STAGE_AUTHORIZED=false`. O resultado não constitui prova de replay 77. Não houve tentativa alternativa nem chamada de `apply_migrations.py`.

Para os oráculos foi criado somente um alvo sintético próprio, usando `postgres@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929`, contêiner `pastorai-e4b-catalog-revalidation-oracles-pg17-20260914` (`2ac14a318bde`), porta loopback `55439` e estado de saúde `healthy`. O runbook indicou o fixture `RLS_TEST_DATABASE_URL` e os 18 oráculos E4b foram selecionados sem skip.

Resultado dos oráculos: exit 1, 18 erros, 0 aprovados e 0 skips, em 9,04 segundos. Todos os erros ocorreram na preparação do fixture com `psycopg2.OperationalError` sanitizado. A execução não foi corrigida, repetida ou ampliada.

O guarda de replay completo foi então executado no mesmo alvo descartável: 100 aprovados em 5,17 segundos, exit 0. Depois, o contêiner foi removido com exit 0; a consulta por seu nome não retornou contêiner e a porta `55439` não possuía listener.

## Suíte backend offline do workflow

A suíte complementar do workflow foi executada uma única vez, com ambiente sanitizado e limite de 20 minutos. Ela concluiu em 85,58 segundos, portanto sem timeout: 6.905 coletados, 382 desmarcados, 6.523 selecionados, 6.381 aprovados, 135 falhas, 7 skips e 66 warnings, exit 1.

Os casos capturados de forma sanitizada incluem falhas em `test_capture_migration_history_evidence.py`, `test_consent_evidence_store_source_boundary.py`, `test_dev_connect_tls_auth_transport_probe_plan.py`, `test_migration_history_environment_attestation.py`, `test_private_runtime_catalog_ci_v1.py`, `test_public_private_catalog_compatibility.py`, `test_replay_private_runtime_catalog_pg17.py` e `test_verify_migration_history_reconciliation.py`. O traceback sanitizado dos primeiros casos mostra retorno esperado 0 recebido 3 e `CatalogError` durante validação do layout local de catálogo. Nenhum dado sensível, caminho absoluto ou saída bruta foi retido neste artefato.

## Conclusão e próximo gate do primeiro recibo

Os checks de fonte específicos da correção estão verdes, mas a prova local completa permanece falha pelos três resultados negativos registrados: replay direto sem alvo descartável fornecido, 18 erros dos oráculos E4b PG17 e 135 falhas da suíte backend offline. Teste verde neste relatório prova somente os comandos identificados neste SHA.

Próximo gate único: decisão nominal de Raniel sobre push e PR somente após correção autorizada dos bloqueios, revalidação completa e LENTE independente. Esta revalidação não satisfaz esses pré-requisitos.

## Continuação local com alvo contratual

Data da evidência complementar: 2026-09-14T15:10:43-03:00. Esta seção preserva o primeiro recibo acima e registra a continuação no mesmo candidato, sem reexecução da suíte backend offline completa.

### Alvo único e diagnóstico inicial

Foi criado um único PostgreSQL local, sintético e descartável: imagem `postgres:17.6-trixie`, fixada em `postgres@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929`; contêiner `pastorai-e4b-catalog-revalidation-pg176-20260914` (`0485e686e7ef`); porta loopback `55439`. A versão confirmada foi PostgreSQL 17.6. O banco administrativo `postgres` iniciou sem relações e o banco `migration_catalog_current_head_disposable` iniciou vazio. A senha foi sintética e não foi registrada.

Antes do replay, foi reproduzido somente `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_catalog_001_matches_r4_manifest`. Exit 1, 0 pass e 0 skip. O traceback sanitizado não repetiu o `OperationalError` anterior: bloqueou em B2 porque `anon`, `authenticated`, `service_role` e `agent_runtime` precisavam existir antes do replay C3. Isso identifica uma pré-condição do alvo vazio, não uma falha de fonte E4b. Não foi aplicado SQL manualmente.

### Modos oficiais do entrypoint

O modo de replay foi executado uma vez com `MIGRATION_CATALOG_REPLAY_DATABASE_URL` apontado ao banco descartável e a confirmação oficial. Resultado: exit 0, `RESULT=MIGRATION_CATALOG_CURRENT_HEAD_REPLAYED_PG17_DISPOSABLE`, 77 migrations, digest `162854e0f753f5ad867aacae6b450d46d5c4bd68f8c3089be144d133ddc73801` e `POSTGRESQL_MAJOR=17`. O próprio replay forneceu as roles B2 globais exigidas pelos oráculos, sem intervenção manual.

Após esse replay, o mesmo oráculo de diagnóstico passou: exit 0, 1 pass e 0 skip. Os 18 oráculos E4b declarados também foram executados isoladamente para obter resultado e nodeids visíveis: exit 0, 18 coletados, 18 passados e 0 skips em 3,34 segundos. A lista declarada e coletada foi:

```text
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_catalog_001_matches_r4_manifest
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_parent_001_requires_synthetic_parent_anchors
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_rls_001_enforces_force_and_tenant_policies
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_guc_001_exercises_positive_and_negative_tenant_matrix
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_acl_001_verifies_revokes_and_ephemeral_memberships
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_dataapi_001_denies_known_roles_without_guc
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_chain_001_commits_complete_chain_and_rejects_partial
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_chain_002_rejects_invalid_withdraw_origins_and_streams
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_replay_001_rehydrates_exact_and_conflicts_tenant_scoped
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_imm_001_rejects_immutable_updates_and_deletes
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_imm_002_allows_only_stream_hold_retention_transitions
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_auth_001_validates_historical_operator_role_links
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_ret_001_validates_confirmed_at_and_utc_retention
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_hold_001_projects_holds_and_serializes_subject
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_lock_001_orders_tenant_scoped_advisory_locks
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_rollback_001_removes_partial_state_and_releases_locks
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_commit_001_reconciles_precommit_and_uncertain_commit
backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_noskip_001_collects_exact_oracle_manifest
```

O segundo modo oficial do entrypoint, com `RLS_TEST_DATABASE_URL` apontado a `/postgres` e a confirmação oficial, retornou exit 8 duas vezes com `MIGRATION_CATALOG_CURRENT_HEAD_REPLAY_BLOCKED:DECLARED_TESTS_NOT_FULLY_EXECUTED`. A segunda tentativa incluiu `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`; o resultado foi idêntico. O launcher descarta deliberadamente a saída interna do pytest quando há falha, por isso não expôs uma contagem oficial de coletados ou passados. A fonte do launcher permite concluir apenas que alguma condição de auditoria falhou. Como os mesmos 18 nodeids passaram fora dele no mesmo alvo, não há evidência de falha nos corpos dos oráculos; também não há evidência suficiente para atribuir o exit 8 a uma condição específica do auditor. Não houve terceira tentativa nem alteração de código.

### Classificação das 135 falhas anteriores

A suíte backend offline anterior não foi repetida. As 135 falhas registradas nela pertencem às oito famílias já listadas no primeiro recibo. Todas as oito rotas de teste existem na base `615408514103be1d67bcafa182b5b3b05f1c3e73`, e `git diff --quiet` confirmou que nenhuma delas foi modificada entre essa base e o candidato. Os quatro casos sanitizados de `test_capture_migration_history_evidence.py` também existem na base, nas linhas 189, 242, 312 e 331.

Classificação: `FORA_DO_DIFF_E4B_NA_FONTE`. Isso exclui atribuição direta pela alteração desses arquivos, mas não prova que os 135 casos já falhavam na base, pois a base não foi executada. Não foi encontrada relação estática direta entre essas famílias e os arquivos alterados no candidato.

### Teardown e veredito atual

O contêiner foi removido com exit 0. A consulta posterior não encontrou seu nome e a porta loopback `55439` não tinha listener. Nenhum outro contêiner desta continuação foi criado.

Veredito: `BLOCKED_FOR_OFFICIAL_DECLARED_TEST_RECEIPT`. O replay oficial 77 e os 18 oráculos E4b no alvo contratual passaram, mas o segundo modo oficial do entrypoint não emitiu recibo válido e repetiu exit 8. O candidato não deve avançar para push ou PR até que esse bloqueio do launcher seja corrigido em mudança autorizada, revalidado integralmente e submetido à LENTE independente.

## Diagnóstico complementar da agregação de nodeids

Data da evidência complementar: 2026-09-14T15:16:21-03:00. Esta investigação usou um novo e único PostgreSQL 17.6 sintético, local e descartável: imagem fixada em `postgres@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929`, contêiner `pastorai-e4b-catalog-revalidation-aggregate-pg176-20260914` (`52fadd65e6b1`) e porta loopback `55439`. Não houve rede externa, SQL manual, `apply_migrations.py` ou nova execução do launcher de testes declarados.

O replay oficial 77 foi executado uma vez no banco descartável: exit 0, `RESULT=MIGRATION_CATALOG_CURRENT_HEAD_REPLAYED_PG17_DISPOSABLE`, 77 migrations, digest `162854e0f753f5ad867aacae6b450d46d5c4bd68f8c3089be144d133ddc73801` e `POSTGRESQL_MAJOR=17`.

Pela API Python do launcher, `_declared_test_nodeids(_load_current_catalog())` retornou 37 nodeids: 19 da migration evidence-store v1 e 18 da migration E4b. Exatamente esses 37 nodeids foram executados uma vez via pytest CLI, com `RLS_TEST_DATABASE_URL` no banco administrativo `/postgres`, `--strict-markers`, `--runxfail`, `-o addopts=`, `-p no:cacheprovider`, `-q` e `--tb=short`.

Resultado do pytest CLI: exit 1, 37 coletados, 27 passados, 10 erros e 0 skips, em 5,36 segundos. Os 18 E4b passaram. Entre os 19 evidence-store, os nove nodeids de `test_consent_evidence_store_pg17.py` passaram e os dez nodeids canônicos abaixo falharam exclusivamente na fase `setup`:

```text
setup  backend/tests/test_consent_evidence_store_canonical_pg17.py::test_canonical_pg17_historical_ledger_writer_remains_permission_denied
setup  backend/tests/test_consent_evidence_store_canonical_pg17.py::test_canonical_pg17_person_cascade_two_tenants
setup  backend/tests/test_consent_evidence_store_canonical_pg17.py::test_canonical_pg17_uow_commit_and_readonly_observation
setup  backend/tests/test_consent_evidence_store_canonical_pg17.py::test_canonical_pg17_uow_concurrent_replay
setup  backend/tests/test_consent_evidence_store_canonical_pg17.py::test_canonical_pg17_uow_rollback_and_ambiguous_commit
setup  backend/tests/test_consent_evidence_store_canonical_pg17.py::test_historical_pg17_concurrent_delete_existing_challenge_cascades_chain
setup  backend/tests/test_consent_evidence_store_canonical_pg17.py::test_historical_pg17_concurrent_delete_new_challenge_cascades_chain
setup  backend/tests/test_consent_evidence_store_canonical_pg17.py::test_historical_pg17_person_cascade_preserves_two_tenants_and_ledger
setup  backend/tests/test_consent_evidence_store_canonical_pg17.py::test_historical_pg17_refusal_before_withdrawal_barrier
setup  backend/tests/test_consent_evidence_store_canonical_pg17.py::test_historical_pg17_withdrawal_before_refusal_barrier
```

O traceback foi sanitizado. Em todos os dez casos, o fixture canônico exige que o banco descartável `migration_catalog_current_head_disposable` ainda não exista. Após o replay oficial 77, esse banco necessariamente existe; a asserção de setup falhou por essa condição. Não houve falha nas fases `call` ou `teardown`.

Conclusão diagnóstica: o exit 8 do launcher não decorre de bug do auditor. O launcher agrega 37 nodeids e sua regra falha fechada quando há qualquer relatório falho ou quando passados não igualam coletados. Os dez erros de setup satisfazem ambas as condições. A causa é um conflito de contrato de ciclo de vida entre o replay oficial, que exige e preenche o banco alvo, e os dez testes canônicos evidence-store, que exigem que esse mesmo banco esteja ausente. O resultado anterior de 18 E4b verdes continua válido, mas não basta para o recibo agregado.

Teardown complementar: o contêiner foi removido com exit 0; a consulta posterior não encontrou seu nome e a porta loopback `55439` não possuía listener.

Veredito atual: `BLOCKED_BY_DECLARED_TEST_CONTRACT_CONFLICT`. Não há evidência de regressão nos 18 oráculos E4b ou no replay 77. Há evidência direta de que o conjunto agregado declarado não pode passar no mesmo ciclo de vida de alvo exigido pelo launcher. O próximo passo exige mudança autorizada do contrato ou do launcher, nova revalidação completa e LENTE independente antes de qualquer push ou PR.
