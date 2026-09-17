---
id: M-2026-09-17-f2-prod-cohort-a-identity-readonly
status: briefing_candidate_local
environment: local_documental_only
execution_authorized: false
authorization_scope: prepare_briefing_and_collection_package_only
---

# F2 PROD: evidência de identidade da coorte A

## Princípio de decisão

A posição fecha o conjunto observado, mas não prova identidade. Uma entrada só
poderá sair de `UNMATCHED_IN_CATALOG` quando existir vínculo um-para-um por
compromisso de payload, independente de posição, ordem entre linhas, timestamp,
versão e nome. Este briefing não produz esse vínculo e não abre PROD.

## Ficha Mission Control

```yaml
id: M-2026-09-17-f2-prod-cohort-a-identity-readonly
objetivo: preparar o briefing e o pacote exato de uma futura coleta PROD somente leitura para obter compromissos opacos de identidade das 22 entradas da coorte A, sem executar a coleta
preflight:
  repositorio: github.com/haniellevi/PastorAI-LionClaw-V1
  branch: docs/f2-prod-cohort-a-identity-readonly-20260917
  sha_efetivo: 18ecd50472a309de3ac838f898f3a6ade9ff763d
  origin_main_observado: 18ecd50472a309de3ac838f898f3a6ade9ff763d
  worktree_limpo: true
  ambiente: local documental; nenhuma sessão PROD, DEV ou VPS
  horario: 2026-09-17T10:43:30-03:00
  runbook_lido: AGENTS.md; docs/ai/AI-BOOTSTRAP.md; docs/ai/PRD-COVERAGE.md; docs/WIKI-IGREJA12.md; docs/ops/MISSION-CONTROL.md; docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/PROD-UNMATCHED-EVIDENCE-MATRIX.md; docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/REPRODUCIBILITY-RECIPES.md; docs/ops/dev-migration-history-remediation/f2-prod-shape-diagnostic-v2/RANIEL-PROD-DIAG-v2-RUNBOOK.md
  grafo: code-review-graph desabilitado pelo manifesto local
worktree: .worktrees/f2-prod-cohort-a-identity-readonly-20260917
branch: docs/f2-prod-cohort-a-identity-readonly-20260917
sha_base: 18ecd50472a309de3ac838f898f3a6ade9ff763d
especialistas:
  - OpenCode, CONSELHEIRO, conferência somente leitura dos bytes exatos
  - QWEN 3.8 FLASH, CONSELHEIRO, conferência somente leitura dos bytes exatos
fontes_congeladas:
  captura_prod_native_identity_sha256: c7831ca5d17b8c250e2cd7a6bc1a5f65c66ddcd874ddbca214c16f4d067b8830
  derivador_sha256: d3f0e9610ace59d704bb5e77dc49e52f6f115cdf2b7847a8bd7e0b5bcc3c85e8
  json_sanitizado_sha256: 5399bb7db895be26c7fb0dcaf67375d0aa7a78c58c03de80b50ed27a9fd2944d
  coorte_a_posicoes: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 22, 23, 24, 25, 26, 29, 31, 32]
  coorte_a_contagem: 22
arquivos_permitidos:
  - docs/missions/M-2026-09-17-f2-prod-cohort-a-identity-readonly.md
  - docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/BRIEFING.md
  - docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/SOURCE-PINS.md
  - docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/EVIDENCE-CONTRACT.md
  - docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/PROD-READONLY-F2-COHORT-A.sql
  - docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/RANIEL-PROD-COHORT-A-RUNBOOK.md
  - docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/run-pg17-f2-prod-cohort-a-e2e.sh
  - docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/test_validate_f2_prod_cohort_a_package.py
  - docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/CANDIDATE-MANIFEST.md
criterios_de_aceite:
  - o pacote contém ficha, briefing, fontes pinadas, contrato de evidência, SQL proposto, runbook humano, runner PG17 proposto, validação estática e manifesto reproduzível
  - a membresia fica fechada nas 22 posições 1-14, 22-26, 29, 31-32 da ordem version ASC, sem incluir ou preparar a coorte posterior
  - posição, ordem, timestamp, versão e nome não participam do compromisso primário de identidade
  - o SQL observa somente pg_catalog e supabase_migrations.schema_migrations, em REPEATABLE READ READ ONLY, com timeouts 5s/1s/15s, row_security=off e ROLLBACK terminal
  - a saída contém somente ordinais públicos, contagens, estados e hashes opacos; nunca statements, rollback, version, name, idempotency_key ou dado de domínio em claro
  - o compromisso primário usa binding novo e framing fixo sobre o array de statements; rollback e idempotency são compromissos suplementares
  - ausência de statements, colisão entre os 22 compromissos, forma do ledger diferente, cardinalidade diferente de 32, teto excedido ou contrato de sessão inválido falham fechados
  - a captura futura fica fora do repositório em arquivo regular não symlink modo 0600
  - o runner valida hash e modo do SQL antes de lê-lo, usa PostgreSQL 17.6 descartável, rede none, nenhuma porta e ownership explícito do container
  - fixtures sintéticas cobrem 22 entradas selecionadas, posições excluídas, opacidade, unicidade, colisão, cardinalidade, digest, recibo e preservação de container preexistente
  - nenhuma classificação afirma aplicação; match futuro exige bijeção exata e única com compromisso do catálogo produzido sob gate próprio
  - privacy guard 13/13, teste estático, bash -n, git diff --check e manifesto reproduzível passam sem executar SQL
riscos_de_tenant:
  - statements ou identificadores crus podem conter metadados correlacionáveis; o SQL só emite compromissos vinculados a binding novo e a captura fica 0600 fora do repo
  - posição, versão ou nome podem criar falso match por coincidência; esses campos só conferem membresia e são proibidos na decisão de identidade
  - o mesmo payload em duas linhas quebra a bijeção; a coleta aborta em compromisso primário duplicado
  - apontar para ambiente incorreto pode produzir evidência válida do alvo errado; TARGET_DIGEST e atestação humana PROD permanecem âncoras separadas
  - reutilizar binding permite correlação entre coletas; cada tentativa exige binding novo e nenhuma repetição ocorre sem nova conferência
  - um resultado sintético verde pode ser confundido com prova viva; o runner prova somente o contrato offline
plano_de_teste:
  - python3 -I -B docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/test_validate_f2_prod_cohort_a_package.py
  - bash -n docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/run-pg17-f2-prod-cohort-a-e2e.sh
  - PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider backend/tests/test_source_contact_privacy.py
  - git diff --check
  - reproduzir CANDIDATE-MANIFEST.md
  - não executar o runner PG17 nem o SQL nesta fase de briefing
plano_de_rollback:
  - antes de commit, descartar somente os nove arquivos desta worktree
  - depois de publicação e antes do merge, corrigir por novo commit revisado ou fechar o PR
  - não existe compensação de ambiente porque nenhuma sessão, coleta ou escrita é autorizada
fora_de_escopo:
  - abrir, ler, copiar ou derivar novamente captura, derivador ou JSON congelados
  - preparar SQL, runbook, runner, manifesto ou ficha da coorte posterior
  - qualquer sessão, leitura ou coleta PROD, DEV ou VPS
  - executar SQL ou runner, conectar banco, usar credencial, escrever, aplicar migration, epoch, cutover, executor, deploy, envio ou ativação
  - commit, push, PR ou merge antes da conferência dos bytes exatos pelos dois conselheiros
proximo_gate: OWNER_AUTHORIZE_PROD_UNMATCHED_IDENTITY_EVIDENCE_READ_ONLY
encerramento:
  status_final: pendente
  sha_final: pendente
  branch_final: docs/f2-prod-cohort-a-identity-readonly-20260917
  pr: nenhum
  mutacoes: nenhuma fora da worktree documental
  evidencias: pendente
  riscos_residuais: pendente
  registro: pendente
```

## Limite vigente

Raniel autorizou apenas preparar este briefing. O gate
`OWNER_AUTHORIZE_PROD_UNMATCHED_IDENTITY_EVIDENCE_READ_ONLY` permanece
fechado e é o único próximo gate humano. Conselheiros, CI, commit, push ou PR
não consomem esse gate e não abrem coleta.
