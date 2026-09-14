# Correction report: E4b catalog chain integration readiness

## Identificação

- Horário local: 2026-09-14T14:42:17-03:00.
- Ambiente: worktree local offline, sem rede, banco, Docker, credenciais ou efeitos externos.
- Worktree: `.` (raiz da worktree atribuída).
- Branch: `rebase/e4b-catalog-chain-readiness-20260914`.
- Base exigida: `615408514103be1d67bcafa182b5b3b05f1c3e73`.
- Candidato commitado examinado: `c2157665ce20982594ddc42c729b039e4a94e4b8`.
- Modelo efetivo: não exposto pela configuração local; a designação nominal recebida não foi usada como prova.

## Diagnóstico

O intent da migration E4b no candidato commitado declarava `base_repository_sha` como `c151c73c2768c7af9193c17b2707d47a42ffb7cc`. A verificação de CI para pull request exige que esse campo seja idêntico à base fornecida, `615408514103be1d67bcafa182b5b3b05f1c3e73`; por isso o comando exato fechou com `MIGRATION_INTENT_INVALID`.

O head público contém 77 migrations e dois batches append-only. A fixture usada pela prova real ainda reconstruía a cabeça inicial de 75 e a comparava diretamente com o campo `previous_approved_head_sha256` da cabeça de 77. Esse campo deve ancorar o prior aprovado imediato de 76, não a cabeça inicial de 75. As expectativas reais de 76 em três provas permitidas tinham a mesma causa. As fixtures sintéticas de 76 foram preservadas.

Por inspeção do entrypoint de replay, falhas de catálogo e intent são transformadas em `SOURCE_CONTRACT_INVALID` antes de abrir socket. `DATABASE_CONTRACT_INVALID` é emitido pelas verificações do alvo PostgreSQL, ou por uma exceção posterior de execução. Assim, a falha NEXO de contrato de banco não decorre da incompatibilidade 76 para 77. Nenhuma investigação do alvo foi feita, pois exigiria a fase PG17 separada e Docker continua proibido aqui.

## Correção delimitada

- `backend/migrations/20260910_142830_add_e4b_consent_persistence.sql`: somente a primeira linha foi alterada, reconciliando `base_repository_sha` para a base real exigida.
- `docs/governance/migrations/migration-catalog-head-v1.json`: somente o SHA do SQL E4b e os digests de batch e cabeça derivados foram atualizados.
- `backend/tests/migration_catalog_fixtures.py`: a reconstrução do prior imediato agora usa o serializador canônico `new_migration._serialize_head`; a reconstrução sintética inicial de 75 permanece disponível.
- `backend/tests/test_migration_catalog_head.py`: a prova real reconstitui e autentica o prior imediato de 76, aceita a cabeça real de 77 e mantém os gates bloqueados.
- `backend/tests/test_validated_migration_catalog_snapshot.py`: a prova real autentica os dois entries append-only nas posições 75 e 76.
- `backend/tests/test_replay_migration_catalog_current_head_pg17.py`: as duas expectativas do snapshot real e do append adversarial foram ajustadas para 77 e 78; loops e fixtures sintéticas de 76 não foram modificados.

Não foram alterados verificador, runner, schema, manifesto, gates, relações, nodeids, lógica E4b ou SQL além do campo de intent permitido.

## Evidência de hashes e imutabilidade

- SHA do SQL E4b após a alteração, calculado com `sha256`: `64c031beea4d74feed83337ea623173d0f8d848c685ffcf5365b279a6ea7d1fd`.
- Tamanho do SQL E4b: `49631` bytes.
- Digest resultante do batch 0002 e da cabeça de 77, calculado com o helper canônico `verify_migration_catalog_head._catalog_digest`: `162854e0f753f5ad867aacae6b450d46d5c4bd68f8c3089be144d133ddc73801`.
- SHA do arquivo de head no worktree após a correção: `88e588660f995f774fe298d2bd4e5ea80d399006379661156b7eff28a6940a57`.
- `previous_approved_head_sha256` permaneceu `38aac6b4349c168f38d24a1f1cfc81843139dce938f596cd92d30b261dbe3dd3`.
- `git show 615408514103be1d67bcafa182b5b3b05f1c3e73:docs/governance/migrations/migration-catalog-head-v1.json | sha256sum` retornou exatamente `38aac6b4349c168f38d24a1f1cfc81843139dce938f596cd92d30b261dbe3dd3`. A prova em `test_migration_catalog_head.py` também reconstitui o mesmo prior de 76 e verifica que seus batches são os dois batches atuais menos o último.

## Comandos e resultados

Todos os comandos abaixo usaram Python `3.13.14`, `env -i`, `PYTHONDONTWRITEBYTECODE=1`, sem banco e sem rede.

1. `python -I -B backend/scripts/verify_migration_catalog_head.py --prior-head-fd 3`, com fd regular contendo o head de 76 extraído da base: passou.

   Resultado: `RESULT=MIGRATION_CATALOG_HEAD_VERIFIED_OFFLINE`, `CATALOG_MIGRATION_COUNT=77`, digest `162854e0f753f5ad867aacae6b450d46d5c4bd68f8c3089be144d133ddc73801`, autorização operacional bloqueada e próximo estágio falso.

2. `python -I -B -m pytest --noconftest -p no:cacheprovider -m 'not rls_integration' tests/test_e4b_consent_migration.py tests/test_migration_catalog_head.py tests/test_validated_migration_catalog_snapshot.py tests/test_replay_migration_catalog_current_head_pg17.py tests/test_catalog_bound_execution_v3.py`: `217 passed, 6 deselected in 1.95s`.

3. `python -I -B -m pytest --noconftest -p no:cacheprovider tests/test_migration_catalog_ci.py`: `1 failed, 34 passed in 0.80s`. A falha é `test_current_appended_head_requires_longitudinal_prior`, linha 304, cuja asserção literal ainda exige `migration_count=76` para a cabeça real de 77. O arquivo não integra a allowlist recebida e não foi alterado. O subconjunto restante, executado com `-k 'not current_appended_head_requires_longitudinal_prior'`, passou com 34 testes.

4. Comando exato solicitado: `python -I -B backend/scripts/verify_migration_catalog_ci.py --event-name pull_request --current-sha c2157665ce20982594ddc42c729b039e4a94e4b8 --pull-request-base-sha 615408514103be1d67bcafa182b5b3b05f1c3e73 --push-before-sha ''`: exit 6, `RESULT=BLOCKED_MIGRATION_CATALOG_CI:MIGRATION_INTENT_INVALID`.

   Esse resultado é esperado e continua sendo evidência negativa do commit imutável `c2157665...`: o script autentica e materializa snapshots privados dos commits informados, portanto não lê a correção deliberadamente deixada sem commit no worktree. Não foi criado commit temporário, ref, merge ou qualquer escrita Git para contornar essa propriedade. A execução verde desse comando exige um SHA futuro que contenha as alterações, sob autorização de commit do Orquestrador.

5. `git diff --check`: passou sem saída. O diff rastreado contém seis arquivos permitidos, com `100 insertions` e `29 deletions`; este relatório é adicional e permanece não rastreado por instrução.

## Limites e próximo gate

O erro `DATABASE_CONTRACT_INVALID` e os dois `OperationalError` de alvo sintético permanecem sem diagnóstico nesta fase, porque não são consequência do head 76 para 77 e investigar o alvo exigiria PostgreSQL descartável. A única decisão humana que destrava a continuidade é autorizar uma fase própria de replay PG17 para o alvo, incluindo o ambiente descartável correspondente.

Além disso, a asserção real desatualizada em `backend/tests/test_migration_catalog_ci.py` não pode ser corrigida sem ampliar a allowlist. O Orquestrador deve decidir se a próxima alteração autorizada inclui esse teste e um commit do candidato, para que o comando de CI autentique o novo SHA. Nada foi commitado, enviado, mesclado ou ativado.
