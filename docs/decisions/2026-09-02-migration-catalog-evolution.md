# Catálogo evolutivo de migrations e consumidores históricos

**Estado:** `M1A-M1E E M1I INTEGRADAS (PR #361, merge 8aacf98d) /
M1J-R5 INTEGRADA E ENCERRADA (PR #363, merge c2fb16ad) /
CATÁLOGO CORRENTE COM 75 MIGRATIONS / OPERAÇÃO BLOQUEADA`

**Base histórica da fundação:** `e5d07e60c2eb9dafae671323bde60d1fa1be5749`

**Base histórica da reconciliação M1J-R2/R5:** `8aacf98d9abbfd945226afb652ef38efa2fc6cfa`

**Snapshot versionado pós-M1J:** `c2fb16ad9a6b028c317c56a0b02c4362ae903e26`

**Snapshot corrente de `main` após a PR #366:**
`1b233e5156ab671d0b56ab705b35f4e5d2011937`

## Decisão

O catálogo deixa de usar a contagem corrente como sinônimo do snapshot
histórico. O artefato `migration-catalog-head-v1.json` mantém os 75 arquivos
anteriores, seu digest e seu último basename como prefixo imutável. O head
corrente é reconstruído por lotes append-only de exatamente uma migration e
continua com `operational_authorization=false` e
`next_stage_authorized=false`.

O verificador estrito exige o conteúdo completo do head anteriormente
aprovado quando existe um lote novo. A âncora é recebida por descritor de
arquivo e serve somente para provar a evolução longitudinal. Um hash válido
não autoriza criar, aplicar ou executar uma migration.

## Compatibilidade histórica

Consumidores históricos podem validar um snapshot local do head apenas para
recuperar o prefixo imutável. Essa leitura valida a cadeia completa e a
correspondência exata com o diretório corrente, mas não substitui a prova
longitudinal do verificador estrito.

O manifesto de expectativa de schema e a derivação canônica continuam
vinculados somente aos 75 arquivos históricos. O verificador da proposta v3
compara o template histórico com esse mesmo prefixo. Uma migration posterior,
quando representada por um lote válido no head, não altera capability counts,
fingerprint ou evidência histórica.

O materializador de captura v1 e
`verify_migration_history_reconciliation.py` permanecem artefatos históricos
de hash fixado. Eles não são gates do catálogo corrente e não foram alterados.
Os pacotes v1, v2 e v3, seus schemas, o fingerprint e os recibos existentes
também permanecem byte-idênticos.

O SHA-256 `8d7712be4f63ead2eff2c9e7af236e610b0c148acb07c85ebcd81db1f6d0877d`
repetido nos registros anteriores identifica a versão histórica do verificador
v3 antes desta adaptação. Ele continua sendo evidência daquele artefato e não
deve ser substituído retroativamente nem interpretado como hash dos bytes
candidatos da M1B.

## Integração CI

O workflow dedicado `migration-catalog-head.yml` executa em `pull_request` e
em push para `main`, com `contents: read`, histórico completo no checkout e sem
credencial persistida. O histórico completo garante que o `before` continue
disponível após um push com múltiplos commits. O contexto do evento fornece o
SHA corrente e exatamente um ancestral: base do pull request ou `before` do
push. O orquestrador valida o checkout e a ancestralidade usando somente
objetos Git locais.

Sem lotes append-only, o head inicial é verificado sem abrir o blob anterior.
Quando existe um lote, o orquestrador exige que o head anterior exista no
ancestral do evento, limita seu tamanho antes da leitura e o entrega ao
verificador estrito como prova longitudinal. Ausência, ambiguidade, SHA zero,
objeto não blob, ancestral inválido, mais de um lote novo ou reescrita do
prefixo bloqueiam o job.

Depois do head estrito, o job source-only valida o manifesto histórico e a
estrutura bloqueada da proposta v3. Na composição candidata pós-Commit A, jobs
isolados adicionais provisionam PostgreSQL 17 descartável, limitado ao
loopback, para o replay do head e para testes de guarda. Eles não recebem DSN
ou segredo de ambiente compartilhado, não acessam DEV ou PROD, não chamam
`apply_migrations.py` e não transformam CI verde em autorização operacional. A
afirmação de que o workflow inteiro não acessa banco descreve apenas a versão
integrada pela PR #361, não o candidato local corrente.

## Provas e limites

A matriz focal cobre o catálogo real de 75 arquivos e um catálogo sintético de
76 arquivos em diretório temporário. No cenário futuro, o caminho estrito
recusa ausência do head anterior, aceita a âncora correta e os consumidores
históricos continuam lendo exatamente 75 entradas. Tail não representado,
reescrita do prefixo, digest divergente e gates verdadeiros falham fechado.

Esta decisão não cria migration SQL nem altera o runner. A prova corrente usa
somente PostgreSQL 17 descartável/loopback; não acessa banco compartilhado,
DEV ou PROD e não autoriza commit, PR, merge, deploy, flag ou runtime.

## Atualização pós-commit M1A-M1C (2026-09-02)

O gate `OWNER_AUTHORIZE_COMMIT_M1_MIGRATION_CATALOG_EVOLUTION_FOUNDATION` foi
consumido por autorização humana nominal, exclusivamente no escopo declarado:
um commit local dos 14 arquivos e hashes congelados de M1A/M1B/M1C. O commit
técnico é `1150fe92ba67dbcb82b230b9a044472a1e1d9d8d`, na branch
`feat/migration-catalog-head-v1`, sobre a base `e5d07e60c2eb9dafae671323bde60d1fa1be5749`.

Esse consumo não autorizou e não executou push, PR, CI remoto, migration SQL,
banco, DEV, PROD, rede, merge ou deploy. `operational_authorization` e
`next_stage_authorized` permanecem `false` em todos os artefatos.

## Atualização pós-commit M1D-M1E (2026-09-03)

O gate `OWNER_AUTHORIZE_COMMIT_M1D_M1E_MIGRATION_CATALOG_HARDENING` foi
consumido exclusivamente para o commit local
`2e381c326953d879f781bf39ea08ca1e2c510835`, com parent
`1150fe92ba67dbcb82b230b9a044472a1e1d9d8d`, na branch
`feat/migration-catalog-head-v1`, sobre a base
`e5d07e60c2eb9dafae671323bde60d1fa1be5749`.

Nenhuma dessas integrações locais prova push, CI remoto, merge, migration,
banco, DEV, PROD ou deploy. `operational_authorization=false` e
`next_stage_authorized=false` continuam estritos.

A M1D reconciliou exclusivamente a documentação pós-commit de M1A-M1C.

A M1E aperfeiçoou o verificador estrito e acrescentou os testes adversariais.
Ela introduziu `_directory_identity`, `_stable_file_unchanged`, ajustes de call
sites e quatro testes adversariais para separar a identidade de segurança de um
diretório ancestral dos metadados voláteis.

A M1E corrigiu falsos positivos causados por mudanças legítimas em metadados
voláteis de diretórios ancestrais ou pais:

- `links` — pode mudar especialmente com criação ou remoção de subdiretórios;
- `size`, `mtime_ns` e `ctime_ns` — podem mudar com alterações legítimas nas entradas do diretório.

A M1E continua exigindo invariavelmente os cinco campos de identidade:

- `device` — prova que o objeto está no mesmo filesystem;
- `inode` — prova que é o mesmo objeto no filesystem;
- `mode` — prova que tipo e permissões não mudaram;
- `uid` — prova que o owner não mudou;
- `gid` — prova que o grupo não mudou.

Bytes e metadados completos dos arquivos (`FileSnapshot` com todos os nove
campos) continuam estritos. O diretório do catálogo e cada migration
continuam sob comparação integral durante o scan. A troca de ancestral,
chmod, mudança de ownership e cadeia divergente continuam falhando fechado.

## Evidência da revisão independente M1D-M1E

A revisão independente da M1D-M1E produziu veredito técnico GO com as
seguintes evidências offline:

- matriz focal: 89 passed;
- repetição: 20/20 rodadas aprovadas (89 passed cada);
- bateria ampliada: 383 passed, 45 skipped, 1 deselected;
- teste isolado desselecionado: falha fechada por modo 0775 preexistente
  no diretório `docs/governance/migrations/` — condição preexistente não
  introduzida pela M1E e não bloqueante para esta correção;
- veredito técnico: GO;
- nenhum banco, rede, migration ou ambiente consultado.

A limitação preexistente do modo `0775` não é regressão da M1E. A inspeção
posterior confirmou que o primeiro ancestral inseguro é o próprio diretório
`/home/raniel-linux/workspace`; portanto, aplicar `chmod` somente ao catálogo
não resolveria a cadeia e alterar o workspace compartilhado afetaria outras
worktrees. A política sucessora preserva esse diagnóstico histórico e exige um
snapshot privado do SHA exato, conforme
[`2026-09-03-trusted-repository-snapshot-policy.md`](2026-09-03-trusted-repository-snapshot-policy.md).

## Atualização pós-commit M1I (2026-09-03)

O gate `OWNER_AUTHORIZE_COMMIT_M1I_POSTCOMMIT_RECONCILIATION` foi consumido
exclusivamente para o commit local `03d1cd2a7072b391e8f148d150dc6888d709bc34`,
com parent `2e381c326953d879f781bf39ea08ca1e2c510835`, na branch
`feat/migration-catalog-head-v1`, sobre a base
`e5d07e60c2eb9dafae671323bde60d1fa1be5749`.

Esse consumo reconciliou exclusivamente a documentação pós-commit nos quatro
documentos autorizados sem alterar código ou testes, mantendo
`operational_authorization=false` e `next_stage_authorized=false`.

## Preflight remoto, push e abertura da PR #361 (2026-09-03)

O gate `OWNER_AUTHORIZE_REMOTE_READ_PREFLIGHT_M1_MIGRATION_CATALOG` foi consumido
exclusivamente para consulta remota somente leitura de `refs/heads/main` via
`git ls-remote`, confirmando a base `e5d07e60c2eb9dafae671323bde60d1fa1be5749`
sem realizar fetch, pull ou mutação de referências.

Em seguida, o gate `OWNER_AUTHORIZE_PUSH_AND_PR_M1_MIGRATION_CATALOG` foi
consumido por autorização humana nominal exclusivamente para:
1. push da branch `feat/migration-catalog-head-v1` (HEAD `03d1cd2a`);
2. abertura da PR #361 contra `main` (observando `mergeStateStatus=CLEAN` antes do merge);
3. execução automática dos checks de CI (10/10 concluídos com sucesso) e Vercel
   Preview (`Ready`);
4. consulta somente leitura dos resultados da PR e CI.

Esse gate não autorizou merge, migration SQL, runner, banco, DEV, PROD,
deploy manual ou qualquer efeito operacional.

## Integração em main via PR #361 (2026-09-03)

As entregas M1A-M1E e M1I foram integradas em `main` pela PR #361
(https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/361).

O gate `OWNER_AUTHORIZE_MERGE_PR_361_MIGRATION_CATALOG` foi consumido
exclusivamente pelo merge autorizado da PR #361 via merge commit.

O merge commit é `8aacf98d9abbfd945226afb652ef38efa2fc6cfa`, com dois
parents:
- Parent 1 (`main` anterior): `e5d07e60c2eb9dafae671323bde60d1fa1be5749`
- Parent 2 (`feat/migration-catalog-head-v1`): `03d1cd2a7072b391e8f148d150dc6888d709bc34`

A árvore do merge commit `8aacf98d` coincide exatamente com a árvore de
`03d1cd2a7072b391e8f148d150dc6888d709bc34`. Após o merge, a API reportou
`mergeStateStatus=UNKNOWN`, distinguindo-se do estado `CLEAN` observado
durante a fase aberta.

Os oito workflows pós-merge no GitHub Actions em `main` concluíram com sucesso:
- `Migration Catalog Head / migration-catalog-head` (16s);
- `Tooling Static Checks / tooling-static` (25s);
- `Environment Attestation PG17 / environment-attestation-pg17` (54s);
- `Canonical Schema Derivation / canonical-schema-derivation` (1m11s);
- `E2E Critical / e2e-critical` (1m35s);
- `Frontend CI / frontend-ci` (1m51s);
- `RLS Integration / rls-integration` (1m52s);
- `Backend Tests / backend-tests` (2m17s).

O deployment Vercel Production automático decorrente do merge concluiu com
sucesso (`Ready`, https://vercel.com/raniel-levis-projects/pastorai-frontend-prod/Zu3UjbDN42QYPwsnDxN4rToQwDCr)
e aplica-se exclusivamente ao frontend Next.js.

CI verde e deployment frontend não provam migration, banco de dados, backend,
DEV, PROD, flags ou runtime. `operational_authorization=false` e
`next_stage_authorized=false` continuam estritos.

## Preflight e atualização local pós-merge (2026-09-03)

O gate `OWNER_AUTHORIZE_REMOTE_READ_FETCH_M1J_POSTMERGE_BASE` foi inicialmente
bloqueado pela política shell do executor e posteriormente concluído com
sucesso pelo supervisor Codex, que realizou o fetch mínimo sem checkout e
atualizou `origin/main` localmente de `e5d07e60` para `8aacf98d` sem alterar o
working tree.

## Worktree e reconciliação canônica M1J-R2/R3/R4/R5 (2026-09-03)

O gate `OWNER_AUTHORIZE_CREATE_WORKTREE_AND_EDIT_M1J_R2_CANONICAL_RECONCILIATION`
foi consumido com a criação da worktree `m1j-postmerge-reconciliation-v2` sobre
a base `8aacf98d` pelo supervisor Codex, e a edição exclusiva dos seis documentos
autorizados pelo executor Antigravity.

Não houve commit, rede, banco, migration, deploy ou efeito operacional.
A worktree anterior `migration-catalog-head-v1` permaneceu intacta.

O gate de commit `OWNER_AUTHORIZE_COMMIT_M1J_R2_CANONICAL_RECONCILIATION` não foi
consumido e foi substituído pela revisão corretiva R3.

O gate `OWNER_AUTHORIZE_EDIT_M1J_R3_CORRECT_CANONICAL_DRIFT` foi consumido para
a correção documental R3.

O gate de commit `OWNER_AUTHORIZE_COMMIT_M1J_R3_CANONICAL_RECONCILIATION` foi
proposto, não consumido e substituído após a revisão do Codex detectar
divergência entre os documentos canônicos e o teste.

O gate `OWNER_AUTHORIZE_EDIT_M1J_R4_DOC_TEST_CANONICAL_RECONCILIATION` foi
consumido para a correção documental ampliada e do teste.

O gate de commit `OWNER_AUTHORIZE_COMMIT_M1J_R4_CANONICAL_RECONCILIATION` foi
proposto, não consumido e substituído após duas falhas determinísticas
encontradas pelo Codex na execução do teste documental.

O gate `OWNER_AUTHORIZE_EDIT_M1J_R5_FINAL_DOC_TEST_ALIGNMENT` foi consumido
exclusivamente para esta correção final de alinhamento entre documentos e testes.

O gate `OWNER_AUTHORIZE_COMMIT_M1J_R5_CANONICAL_RECONCILIATION` foi consumido
exclusivamente para o commit local
`2218049902635239280af141980a30c3c3477c4c`, com parent obrigatório
`8aacf98d9abbfd945226afb652ef38efa2fc6cfa`, mensagem
`docs: reconcile M1J post-merge canonical state` e exatamente os 15 arquivos
autorizados. O working tree ficou limpo; não houve rede nessa etapa.

O gate
`OWNER_AUTHORIZE_REMOTE_READ_PREFLIGHT_M1J_R5_CANONICAL_RECONCILIATION` foi
consumido exclusivamente para `git ls-remote`: confirmou `refs/heads/main` em
`8aacf98d` e a ausência da branch remota
`docs/m1j-postmerge-reconciliation-v2`, sem alterar refs locais.

O gate `OWNER_AUTHORIZE_PUSH_AND_PR_M1J_R5_CANONICAL_RECONCILIATION` foi
consumido exclusivamente para enviar `2218049` sem force, abrir a PR #363
contra `main` em `8aacf98d` e observar seus resultados. Os dez checks da PR
concluíram com sucesso e `mergeStateStatus=CLEAN`. O deployment automático da
PR foi classificado como Vercel Preview (`6251176874`); não era Production.

O gate `OWNER_AUTHORIZE_MERGE_PR_363_M1J_R5_CANONICAL_RECONCILIATION` foi
consumido exclusivamente para o merge por merge commit. A PR #363 foi
integrada em `2026-09-03T19:28:24Z` pelo commit
`c2fb16ad9a6b028c317c56a0b02c4362ae903e26`, com parent 1 `8aacf98d` e
parent 2 `2218049`. Os nove check-runs pós-merge, incluindo `public-health`,
foram revalidados com sucesso pelo supervisor nesta missão. Conforme a
evidência GitHub/Vercel igualmente revalidada, o
deployment automático `6251268132` declarou `environment=Production` e
`state=success`; essa prova é exclusiva do frontend Next.js e não comprova
backend, banco, migration, DEV, PROD de banco, flags ou runtime.

Por fim, o gate `OWNER_AUTHORIZE_REMOTE_READ_FETCH_M1J_R5_POSTMERGE_STATE` foi
consumido para um fetch mínimo que avançou somente
`refs/remotes/origin/main` de `8aacf98d` para `c2fb16ad`. Os parents foram
confirmados, a árvore de `c2fb16ad` coincidiu com a de `2218049`, a branch
local permaneceu em `2218049` e o working tree ficou limpo. Nenhuma branch
local foi movida. Com essa reconciliação, M1J está encerrada e `8aacf98d`
permanece somente como base histórica.

Os gates relacionados à PR #354 são estritamente históricos e já consumidos,
nunca constituindo gates correntes.

`operational_authorization=false` e `next_stage_authorized=false` continuam
estritos. Nenhuma operação viva, migration ou cutover foi autorizada pela M1J.

## Política de permissões sucessora

A primitiva de snapshot privado foi implementada e comprovada offline, sem
enfraquecer os verificadores nem alterar o checkout compartilhado. A mitigação
é parcial: a worktree candidata corrente foi observada em `0755`, mas o
repositório principal e ancestrais do workspace permanecem `0775`, o `chmod`
local não é durável, consumidores legados de apply, capture e reconcile ainda
não foram migrados transitivamente e o bootstrap exige um launcher externo
confiável. O P2 de permissões permanece aberto globalmente.

## Próximo estágio único

O gate `OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`
foi consumido exclusivamente para o candidato local descrito em
[`2026-09-03-migration-environment-attestation-executor-v2.md`](2026-09-03-migration-environment-attestation-executor-v2.md).
O executor reutiliza o catálogo a partir do snapshot privado do SHA exato e
emite somente artefato v1 sanitizado e bloqueado. Identidade e captura usam a
mesma conexão/PID, porém duas transações e dois snapshots PostgreSQL separados.
Ele não prova migration aplicada, não conclui a revisão v3 e não libera runner.

## Reconciliação local pós-commit — estado pré-PR #366 (2026-09-03)

O último snapshot integrado de `main` observado e disponível localmente é o
merge `c2fb16ad9a6b028c317c56a0b02c4362ae903e26`. Esta reconciliação não realizou
nova leitura remota; o preflight remoto do próximo gate deve confirmar se o tip
de `main` ainda coincide com esse SHA. Sobre esse snapshot, a primitiva de
snapshot confiável foi fixada no commit local
`11ae294fd4459e55cb31b3342fb8f0a766ac0a03`; o executor v2 foi fixado no
commit local seguinte `1b299e7fcc709ae2528db1c3f76aa15f14dbcf06`, cujo parent é
`11ae294`. Naquele recorte, ambos permaneciam não integrados e não provavam CI remoto, conexão,
captura, migration, banco compartilhado, DEV ou PROD.

No snapshot privado `0700/0600` do SHA `1b299e7`, a seleção ampla contabilizou
961 testes, com 801 aprovados, 160 skips, zero falhas e zero erros. A regressão
separada do probe histórico de transporte TLS passou `125/125`, sem testar o
executor v2 ou o job PG17. A seleção focal no checkout compartilhado coletou
186 itens, com 183 aprovados, três skips PG17 e zero falhas após a reconciliação
documental. A decisão do executor v2 registra composição, runtime e horários. A
prova PostgreSQL 17 sem skips ainda depende do CI/PR do commit local.

O SHA-256 histórico `8d7712be4f63ead2eff2c9e7af236e610b0c148acb07c85ebcd81db1f6d0877d`
permanece vinculado aos bytes pré-adaptação do verificador da proposta v3. Ele
não deve ser substituído retroativamente. O pacote v3 congelado permanece em
`076d04ed179c5128c4707c07cacd8240896101a9bea62e328d2d0569900cd10e`.
Os bytes correntes do verificador adaptado
`backend/scripts/verify_migration_history_divergence_remediation_proposal_v3.py`
têm SHA-256 `efcc9be299241793c74e5c4174a4dc44f3b14507d1585d9daa5a407ab38f13f8`.

A reconciliação canônica complementar sobre o parent `1b299e7` abrange
exatamente 20 arquivos: `SPEC.md`, `SPEC_PROGRESS.md`,
`backend/migrations/README.md`,
`backend/tests/test_d2b2b2_decision_packet_docs.py`, `deploy/STAGING.md`,
`docs/Docs20260611_163530/PRD20260611_163530.md`,
`docs/WIKI-IGREJA12.md`, `docs/ai/AI-BOOTSTRAP.md`,
`docs/ai/PRD-COVERAGE.md`,
`docs/audits/2026-08-27-d1-security-scope-audit.md`,
`docs/decisions/2026-08-28-d2b2-purpose-consent-ledger.md`,
`docs/decisions/2026-08-28-d2b2b1-consent-security-boundary.md`, os ADRs
D2B2b2 e D2B2b3A, esta decisão, as decisões do executor v2 e do snapshot
confiável, o guia de revisão humana, `docs/ops/POST-V1-MISSION-REGISTER.md` e
`docs/ops/PRODUCTION-RUNBOOK.md`. Os 19 documentos distinguem observação
histórica de estado vivo atual e registram a procedência das matrizes offline;
o único arquivo de teste troca a antiga exigência em tempo presente pela
exigência explícita de observação histórica e estado atual não revalidado.
Nenhum código de runtime, migration, schema ou workflow foi alterado nessa
reconciliação.

## Atualização pós-Commit A de segurança — estado pré-PR #366 (2026-09-04)

O commit local `9b9395e29cc821d6808738a30a6afe367d4ffbea`, parent
`947af39d35544700188461d8c99332df70b57e07`, consolida o autor
`new_migration.py` com fases `draft`/`prepare-head` source-only e somente
`TENANT`, o snapshot validado, o wrapper catalog-bound v2 limitado a `list` e o
replay do catálogo corrente em PG17 descartável/loopback. Naquele recorte, não
estava integrado e não houve push, PR ou CI remoto.

O verificador longitudinal no próprio SHA concluiu com 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.
A focal concluiu `274 passed, 6 skipped`; os testes PG17 reais terminaram `6/6`
e incluem E2E sintético de 76ª migration `TENANT`; duas revisões independentes
concluíram `P0=0` e `P1=0`.

O `apply_migrations.py` legado permanece fisicamente invocável e é risco
residual. O replay não atesta views, outros schemas, funções, roles ou
memberships, `BYPASSRLS`, grants nomeados, schema/default ACLs ou semântica
ampla de DML/DDL. Worktree e migrations foram observadas em `0755` e SQL em
`0644`, mas ancestrais workspace/repositório continuam `0775` e o `chmod` local
não é durável; o P2 global permanece aberto.

DEV permanece `BLOCKED_LEDGER_DIVERGENCE`, PROD permanece
`BLOCKED_EVIDENCE_INSUFFICIENT`, a falha TLS DEV histórica segue sem solução e
revisão independente v3, cutover, atestação viva e aplicação continuam
pendentes. `operational_authorization=false` e `next_stage_authorized=false`.

A proposta v4 local estende v3 apenas para vincular a segurança source-only do
Commit A. Ela preserva os contratos históricos e os estados de ambiente e
cutover, mantém todas as permissões falsas e exige duas leituras idênticas do
snapshot validado sem embutir contagem ou digest. O resultado válido permanece
bloqueado com exit `8`; seus testes dedicados terminaram `61/61`.

O gate
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`
foi proposto, não consumido e substituído. O único estágio corrente fechado é
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_SAFETY_R1`, limitado ao
preflight remoto read-only, push da branch candidata, abertura de PR e
observação do CI/Preview automáticos. Não autoriza merge, banco compartilhado,
DEV, PROD, migration, runner de aplicação ou flags. Trust anchors externos
permanecem futuros, não correntes e não autorizados.

## Atualização pós-merge da segurança de autoria e replay (2026-09-04)

A segurança de autoria/replay de migrations e a extensão source-only v4 foram
integradas em `main` pela PR #366 no merge
`1b233e5156ab671d0b56ab705b35f4e5d2011937`, com parents `c2fb16ad` e
`ef03ae1b`. Os 12 check-runs pós-merge terminaram com sucesso, incluindo
catálogo, divergência v4, replay/guards PostgreSQL 17, RLS, backend e E2E.
O deployment Vercel Production `6262210648` terminou com sucesso e comprova
somente o frontend.

A integração não executou migration em banco compartilhado e não acessou
DEV/PROD. O P2 de permissões de host permanece aberto; trust anchors externos,
TLS DEV, revisão v3, cutover, atestação viva e aplicação continuam pendentes.
`operational_authorization=false` e `next_stage_authorized=false` continuam
estritos. O gate de continuidade desta reconciliação documental é
`OWNER_AUTHORIZE_COMMIT_MIGRATION_SAFETY_POSTMERGE_RECONCILIATION_R1`.
