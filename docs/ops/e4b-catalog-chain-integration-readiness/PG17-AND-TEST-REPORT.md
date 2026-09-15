---
mission_id: M-2026-09-14-e4b-catalog-chain-integration-readiness-offline
executed_at: 2026-09-14T14:24:26-03:00
environment: local-offline
candidate_sha: c2157665ce20982594ddc42c729b039e4a94e4b8
branch: rebase/e4b-catalog-chain-readiness-20260914
origin_main_local: 615408514103be1d67bcafa182b5b3b05f1c3e73
origin_backup_e4b_c3: 7b0b6bfd0e1b842d214576a3a1a7eff02acbb307
runtime: preprovisioned-python-3.13.14
result: FAILED_LOCAL_VALIDATION
---

# PG17 e testes, recibo local sanitizado

## Resultado

O candidato falhou na validação local. Não houve correção, alteração de código,
SQL, catálogo, manifesto, flags ou ficha. O runtime pré-provisionado indicado
foi confirmado com Python 3.13.14, pytest 9.1.0 e SQLAlchemy 2.0.50; todos os
checks dinâmicos abaixo usaram esse runtime com ambiente sanitizado, isolamento
do interpretador e sem configuração ou credencial lida.

O modelo efetivo não estava visível por banner, configuração local permitida ou
shell. A missão informa `gpt-5.6-terra` com esforço `max`, mas essa identidade
não foi reatestada de forma independente neste recibo.

## Identidade e estado preservado

| Item | Resultado |
| --- | --- |
| Worktree e branch | Confirmados: worktree atribuída e `rebase/e4b-catalog-chain-readiness-20260914` |
| HEAD candidato | `c2157665ce20982594ddc42c729b039e4a94e4b8` |
| `origin/main` local | `615408514103be1d67bcafa182b5b3b05f1c3e73` |
| Ref de recuperação local | `origin/backup/e4b-c3-catalog-bound-executor-v3` em `7b0b6bfd0e1b842d214576a3a1a7eff02acbb307` |
| Estado inicial | A ficha da missão e o diretório deste recibo já estavam não rastreados e foram preservados |
| Alterações desta execução | Somente este arquivo |

Foram lidos a ficha, `REBASE-REPORT.md`, `MISSION-CONTROL.md`, o manifesto de
persistência, o runbook C3, bootstrap, cobertura, Wiki e os workflows locais
aplicáveis. O recibo de rebase permanece a fonte da identidade operacional,
pois a ficha ainda cita o SHA anterior ao rebase.

## Evidência estática concluída

| Verificação | Resultado |
| --- | --- |
| `git diff --check` entre a base local e o candidato | Exit 0, sem saída |
| `git diff --check` do worktree | Exit 0, sem saída |
| Catálogo declarado | `CATALOG_MIGRATION_COUNT=77` |
| Digest do catálogo | `ed6398ff6cfc15981208631075b724fb128991682e6c7e607acf72fb913a6ac2` |
| SHA-256 do arquivo de head | `9b756191d6a3e89fca61b3c88015b1f76423692e09b12270239389bef63dd1f5` |
| SHA-256 da migration E4b | `6952a2aaca04d6765a0bc77f831b2507e9cf5fd77d80f76e43b0816b06806e6b` |
| SHA-256 do launcher de replay | `753abf57747de9a28f6192617dfd7ea348cb7adf302d7acbd57f280de3d8ce3f` |
| Gates no catálogo | `OPERATIONAL_AUTHORIZATION=BLOCKED`; `NEXT_STAGE_AUTHORIZED=false` |

Os workflows inspecionados foram `migration-catalog-head.yml`,
`backend-tests.yml` e `private-runtime-catalog.yml`. `apply_migrations.py` não
foi invocado.

## Checks source-only e backend offline

| Check | Exit | Resultado exato |
| --- | ---: | --- |
| Verificador CI-equivalente do catálogo | 6 | `RESULT=BLOCKED_MIGRATION_CATALOG_CI:MIGRATION_INTENT_INVALID` |
| Teste canônico 76/77, `test_migration_catalog_head.py` | 1 | 2 falhas, 69 aprovações, 0 skips, 0,56 s |
| Suíte focal E4b/V3 source-only | 1 | 1 falha, 224 aprovações, 6 skips, 2,83 s |
| Guarda de privacidade de contatos-fonte | 0 | 13 aprovações, 0 skips, 1,587 s |
| Suíte backend offline, `-m "not rls_integration"` | 130 | Timeout controlado ao atingir 20 minutos do workflow; não houve resumo ou contagem emitidos |
| Guardas PG17 do launcher de replay | 1 | 6 falhas, 94 aprovações, 0 skips, 1,52 s |

Os seis skips da primeira execução focal eram os guardas RLS de
`test_replay_migration_catalog_current_head_pg17.py`, inicialmente sem alvo
descartável configurado. Eles foram executados sem skip no contêiner PG17 limpo
descrito adiante.

### Casos falhos, traceback sanitizado

- `test_versioned_head_verifies_real_catalog_and_keeps_gates_closed` falhou na
  âncora do head aprovado anterior.
- `test_initial_head_is_exact_historical_prefix` encontrou 77 migrations onde
  a expectativa ainda é 76.
- `test_public_catalog_snapshot_is_immutable_source_evidence` encontrou 77
  entradas no snapshot onde a expectativa ainda é 76.
- Nos guardas PG17, dois casos de validador de relação e delta de segurança
  encerraram com `psycopg2.OperationalError` na conexão sintética de loopback.
- Quatro casos sintéticos de append do guarda PG17 falharam antes do replay
  esperado porque a asserção interna ainda exige 76 entradas, enquanto o
  snapshot contém 77.

Não foi incluída saída de banco, DSN, SQL de caso parametrizado, dado pessoal,
segredo ou caminho absoluto. O timeout da suíte completa não produziu traceback
ou lista de casos antes da interrupção controlada.

## PG17, replay e teardown

| Item | Replay do head | Guardas PG17 |
| --- | --- | --- |
| Imagem local fixada | `postgres@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929` | Mesma imagem |
| Contêiner exclusivo | `pastorai-e4b-catalog-chain-integration-readiness-pg17-20260914` | `pastorai-e4b-catalog-chain-integration-readiness-pg17-guard-20260914` |
| Identificador do contêiner | `89aa0eb9a79b` | `4ae9fb31ba4c` |
| Porta | `127.0.0.1:55437` | `127.0.0.1:55437`, reutilizada após liberação |
| Saúde antes do check | `healthy` | `healthy` |
| Entry point do replay | `replay_migration_catalog_current_head_pg17.py` com a confirmação nominal exigida | Não aplicável |
| Resultado | Exit 6, `MIGRATION_CATALOG_CURRENT_HEAD_REPLAY_BLOCKED:DATABASE_CONTRACT_INVALID` | Exit 1, 6 falhas e 94 aprovações |
| Contagem e digest recebidos do replay | Não emitidos, pois o replay bloqueou antes do recibo de sucesso | Não aplicável |
| Teardown | `docker rm -f` exit 0 | `docker rm -f` exit 0 |

Depois dos dois teardowns, os filtros pelos dois nomes de contêiner ficaram
vazios e a porta `55437` não tinha escuta TCP. Nenhum contêiner, banco ou porta
da missão permaneceu ativo.

Nenhuma operação atingiu DEV, PROD, banco compartilhado, credencial real,
WhatsApp, ativação, envio, migration aplicada, push, PR ou rede externa. Os
estados permanecem `OPERATIONAL_AUTHORIZATION=BLOCKED`,
`NEXT_STAGE_AUTHORIZED=false` e
`SHARED_ENVIRONMENT_ATTESTATION=false`.

## Próximo gate único

Raniel decide sobre push e PR somente após a correção do candidato, nova
validação local completa e LENTE independente. Esse gate não autoriza aplicação
de migration, ambiente compartilhado ou qualquer efeito externo.
