---
id: M-2026-09-17-f2-dev-epoch-design-offline
status: ficha_preparada_aguarda_conferencia_conjunta
environment: local_offline_documental_only
execution_authorized: false
authorization_scope: ficha_only_before_package_bytes
---

# F2: desenho documental do epoch DEV

## Princípio de decisão

O epoch DEV deve vincular uma interpretação conservadora a fontes DEV
congeladas e a uma atestação humana específica do ambiente. Ele não prova
aplicação de migration, não altera ledgers, não importa fatos de PROD e não
autoriza materialização, cutover ou executor.

## Ficha Mission Control

```yaml
id: M-2026-09-17-f2-dev-epoch-design-offline
objetivo: produzir o pacote documental do epoch DEV, com conferência de fonte, trust anchors classificados e lacunas explícitas para materialização futura, sem escrita ou acesso a ambiente
preflight:
  repositorio: github.com/haniellevi/PastorAI-LionClaw-V1
  branch: docs/f2-dev-epoch-design-20260917
  sha_efetivo: 48c57f7bca780b652bf16c096f4d1859918018c9
  origin_main_observado: 48c57f7bca780b652bf16c096f4d1859918018c9
  worktree_limpo: true
  ambiente: local e offline; nenhuma sessão PROD, DEV ou VPS
  horario: 2026-09-17T08:42:17-03:00
  runbook_lido: AGENTS.md; docs/ai/AI-BOOTSTRAP.md; docs/ai/PRD-COVERAGE.md; docs/WIKI-IGREJA12.md; docs/ops/MISSION-CONTROL.md; docs/ops/dev-migration-history-remediation/f2-readonly/RANIEL-READONLY-F2-RUNBOOK.md; docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md; docs/ops/dev-migration-history-remediation/f2-three-state-comparison/STRATEGY-A-B-EPOCH-CUTOVER.md; docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/EPOCH-TRUST-ANCHORS.md
  grafo: code-review-graph desabilitado pelo manifesto local
worktree: .worktrees/f2-dev-epoch-design-20260917
branch: docs/f2-dev-epoch-design-20260917
sha_base: 48c57f7bca780b652bf16c096f4d1859918018c9
especialistas_planejados:
  - FORJA, gpt-5.6-terra max, somente após APTO conjunto desta ficha, para redação documental na worktree da missão
  - OpenCode, CONSELHEIRO, conferência somente leitura da ficha e depois dos bytes exatos
  - QWEN 3.8 FLASH, CONSELHEIRO, conferência somente leitura da ficha e depois dos bytes exatos
fonte_oficial_dev:
  classe: captura externa única, somente leitura e fora do repositório
  sha256: 18d2e78ffc16d26f20f1e58459969c9c3bcc5cf58896c33c6225daedd01f6cb9
  modo: "0600"
  tamanho_bytes: 405404
  horario_coleta: 2026-09-16T13:17:21-03:00
  recibo_terminal: F2_DEV_FINAL_RECEIPT=ROLLBACK_COMPLETED_F2_DEV
  declaracoes_humanas_aceitas:
    - DIGEST_CONFERE
    - PREFIXO_BINDING_0=0/0/0
    - F2_TARGET_DIGEST_VERIFIED_PREFIX_ABSENT
  forma_aceita:
    - sessão DEV em PG170006
    - REPEATABLE READ e read_only
    - row_security=off
    - ledger público com 33 entradas
    - ledger nativo com 6 entradas
  fonte_rejeitada:
    - captura com prefixo SHA-256 5fbd1c8f, SUPERSEDED e proibida como fonte
arquivos_permitidos:
  - docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md
  - docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/SOURCE-CONFERENCE.md
  - docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/DEV-EPOCH-TRUST-ANCHORS.md
  - docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/MATERIALIZABILITY-GAPS.md
  - docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/NO-IMPORT-CONTRACT.md
  - docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/DECISION-PACKET.md
  - docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/FINAL-REPORT.md
  - docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/CANDIDATE-MANIFEST.md
  - docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/CANDIDATE-MANIFEST.md
  - docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/REPRODUCIBILITY-RECIPES.md
fases:
  - F0: conferir esta ficha com OpenCode e QWEN antes de preparar qualquer outro byte
  - F1: conferir somente fontes versionadas e metadados sanitizados; não abrir ou copiar a captura externa
  - F2: classificar cada trust anchor DEV como SATISFEITO, PARCIAL ou FALTANTE, com arquivo e linha
  - F3: documentar o epoch candidato, a regra no-import, as lacunas de materialização e o fix cosmético isolado
  - F4: reproduzir manifesto e validações; obter APTO conjunto dos bytes; commit, push e PR sob a delegação vigente
criterios_de_aceite:
  - a conferência de fonte aceita somente a captura 18d2e78f completa e rejeita 5fbd1c8f como SUPERSEDED
  - o pacote registra hash, modo, tamanho, horário, recibo e forma DEV sem copiar captura, TARGET_DIGEST, binding, conexão, nomes opacos ou dados de domínio
  - a atestação humana de DEV é tratada como trust anchor separado do TARGET_DIGEST e não é presumida a partir dele
  - cada trust anchor recebe estado SATISFEITO, PARCIAL ou FALTANTE com evidência arquivo:linha e razão verificável
  - as classes do epoch são conservadoras e nunca afirmam aplicação por presença, posição, ordem, data, hash ou cardinalidade
  - a regra no-import proíbe usar PROD para concluir DEV e usar DEV para concluir PROD
  - os ledgers público e nativo permanecem fatos históricos integrais, sem backfill, reordenação ou mutação
  - MATERIALIZABILITY-GAPS enumera explicitamente tudo que falta antes de materializar um epoch, incluindo atestação de ambiente, fonte e catálogo autenticados, representação durável, idempotência, executor revisado, rollback ou compensação e autorização nominal
  - nenhuma lacuna é preenchida por inferência; item sem prova permanece FALTANTE
  - o fix cosmético altera somente o placeholder f2-prod-native-identity-cast.txt para f2-prod-native-identity-cast-retry-01.txt no documento já versionado, sem usar a captura PROD; o manifesto legado é regenerado somente para vincular os bytes novos
  - o reprodutor autocanônico do pacote #403 passa contra a receita corrigida
  - a sequência futura fica registrada: missão da coorte A antes da coorte B, sem preparar SQL, runbook, runner ou manifesto PROD nesta missão
  - privacy guard 13/13, git diff --check, manifesto reproduzível e conferência dos dois conselheiros passam nos bytes exatos
riscos_de_tenant:
  - confundir TARGET_DIGEST com identidade humana do ambiente pode vincular a fonte ao alvo errado; a atestação humana é independente e obrigatória
  - copiar a captura ou identificadores opacos pode expor metadados correlacionáveis; somente hash, modo, tamanho, recibo e achados sanitizados entram no repositório
  - inferir aplicação pelo estado estrutural pode legitimar schema incorreto; todas as classes permanecem conservadoras
  - importar ordem ou conclusão de PROD pode contaminar o epoch DEV; a regra no-import é fail-closed
  - aceitar a captura SUPERSEDED quebra a cadeia de custódia; o prefixo 5fbd1c8f é rejeitado explicitamente
  - transformar esta documentação em execução pode afetar tenants e ledgers; banco, executor e materialização ficam fora
plano_de_teste:
  - sha256sum da ficha antes da conferência conjunta
  - validar por busca delimitada que 18d2e78f é a única fonte oficial e 5fbd1c8f aparece somente como SUPERSEDED
  - conferir uma única matriz de trust anchors com estados fechados e referências arquivo:linha
  - conferir que nenhuma conclusão de PROD aparece como prova de DEV e vice-versa
  - conferir que o diff cosmético futuro altera somente o basename do placeholder autorizado
  - reproduzir o CANDIDATE-MANIFEST.md legado do pacote #403 contra os bytes novos e exigir PASS_F2_EPOCH_MANIFEST_REPRODUCIBLE
  - reproduzir CANDIDATE-MANIFEST.md sobre todos os arquivos do pacote final
  - executar PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider backend/tests/test_source_contact_privacy.py e exigir 13/13
  - executar git diff --check e busca por caminhos pessoais, credenciais, bindings, TARGET_DIGEST e dados de domínio
plano_de_rollback:
  - antes do commit, descartar somente os arquivos locais desta missão e restaurar a única linha cosmética se os conselheiros rejeitarem o candidato
  - depois da publicação e antes do merge, corrigir somente por novo commit revisado ou fechar o PR
  - nenhuma compensação de banco existe porque a missão não abre ambiente nem produz escrita
fora_de_escopo:
  - abrir, ler ou copiar a captura DEV externa nesta etapa
  - qualquer sessão PROD, DEV ou VPS
  - SQL novo, migration, ledger write, backfill, reordenação, epoch materializado, cutover, executor, deploy, credencial, envio, billing, broadcast, Brevo ou ativação
  - preparar ou executar as missões PROD das coortes A e B
  - merge; exige frase nominal de Raniel com o número do PR depois de APTO conjunto e CI verde
sequencia_posterior_retida:
  - coorte A primeiro, gate OWNER_AUTHORIZE_PROD_UNMATCHED_IDENTITY_EVIDENCE_READ_ONLY
  - coorte B depois, gate OWNER_AUTHORIZE_PROD_UNMATCHED_FORMAT_AND_IDENTITY_EVIDENCE_READ_ONLY
  - cada coorte terá ficha, SQL read-only, runbook, runner e manifesto próprios, conferidos antes de qualquer execução humana
proximo_gate: Raniel autorizar nominalmente o merge do futuro PR desta missão após APTO conjunto de OpenCode e QWEN, CI verde e threads resolvidas
```

## Limite desta etapa

Somente esta ficha foi preparada. Nenhum outro arquivo do pacote, captura,
ambiente, SQL, runner, manifesto, commit, push ou PR foi criado ou alterado.
