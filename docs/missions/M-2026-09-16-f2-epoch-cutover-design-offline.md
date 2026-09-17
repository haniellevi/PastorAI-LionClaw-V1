---
id: M-2026-09-16-f2-epoch-cutover-design-offline
status: execucao_documental_local_autorizada
environment: local_offline_documental_only
execution_authorized: true
---

# F2: desenho documental de epochs e cutover

## Princípio de decisão

A reconciliação deve preservar o histórico observado de cada ambiente e separar
âncora, epoch e decisão operacional por ambiente. Um casamento derivado é
apenas evidência de consistência de formato. Ele não prova aplicação e não
permite importar a ordem de DEV para PROD ou de PROD para DEV.

## Ficha Mission Control

```yaml
id: M-2026-09-16-f2-epoch-cutover-design-offline
objetivo: produzir o desenho documental da estratégia A para epochs DEV e PROD independentes, tratamento explícito das lacunas 30/75, catálogo fonte fechado e cutover futuro fail-closed, sem escrita ou materialização
preflight:
  repositorio: github.com/haniellevi/PastorAI-LionClaw-V1
  branch: docs/f2-epoch-cutover-design-20260916
  sha_efetivo: de1ea1e659be9a4f2a988740b72a9ed8edd68bfb
  origin_main_observado: de1ea1e659be9a4f2a988740b72a9ed8edd68bfb
  checkout_primario_observado_pelo_qwen: 108cb4eb80f3ff1a7d2de2d3f9eeeba74ac2a27b, branch docs/consent-tarefas-operacionais-filadelfia-approved, não é main
  worktree_limpo: true antes desta ficha
  ambiente: local e offline; nenhuma sessão PROD, DEV ou VPS
  horario: 2026-09-16 America/Sao_Paulo
  runbook_lido: AGENTS.md; docs/ai/AI-BOOTSTRAP.md; docs/ai/PRD-COVERAGE.md; docs/WIKI-IGREJA12.md; docs/ops/MAESTRI-PERSISTENCE-MANIFEST.md; docs/ops/MISSION-CONTROL.md; docs/missions/M-2026-09-16-f2-three-state-comparison-epoch-cutover.md; docs/missions/M-2026-09-16-f2-prod-native-ledger-identity-readonly.md; docs/ops/dev-migration-history-remediation/f2-three-state-comparison/STRATEGY-A-B-EPOCH-CUTOVER.md
  grafo: code-review-graph desabilitado pelo manifesto local
worktree: .worktrees/f2-epoch-cutover-design-20260916
branch: docs/f2-epoch-cutover-design-20260916
sha_base: de1ea1e659be9a4f2a988740b72a9ed8edd68bfb
especialistas:
  - FORJA, gpt-5.6-terra max, redação documental no worktree desta missão
  - OpenCode, CONSELHEIRO, conferência somente leitura do candidato exato
  - QWEN 3.8 FLASH, CONSELHEIRO, conferência somente leitura do candidato exato
arquivos_permitidos:
  - docs/missions/M-2026-09-16-f2-epoch-cutover-design-offline.md
  - docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/DECISION-PACKET.md
  - docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/EPOCH-TRUST-ANCHORS.md
  - docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/PROD-UNMATCHED-EVIDENCE-MATRIX.md
  - docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/NON-DERIVABLE-CATALOG-INVENTORY.md
  - docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/CUTOVER-ROLLBACK-CONTRACT.md
  - docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/REPRODUCIBILITY-RECIPES.md
  - docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/CANDIDATE-MANIFEST.md
criterios_de_aceite:
  - epochs DEV e PROD têm trust anchors próprios e não importam ordem ou conclusão entre ambientes
  - o pacote trata explicitamente 30 entradas PROD sem match e 75 entradas do catálogo sem chave PROD, sem afirmar aplicação
  - o catálogo fonte inclui somente os 77 arquivos SQL top-level de backend/migrations no pino de1ea1e; private_runtime fica explicitamente excluído e justificado
  - os 17 basenames não deriváveis aparecem individualmente, cada qual com motivo explícito
  - o pacote contém receitas reexecutáveis para seleção top-level, catalog_ref, digest de basenames e derivação determinística
  - repetir a derivação no mesmo pino e com a mesma captura congelada reproduz o JSON byte a byte
  - cada coorte sanitizada das 30 entradas sem match declara evidência adicional necessária e o gate humano que poderia autorizar obtê-la; nenhuma leitura nova é feita
  - os dois ledgers são preservados integralmente, sem backfill, reordenação ou mutação retroativa
  - plano documental de cutover contém precondições, critérios de aceite, abortos, rollback ou compensação e fail-closed por hash, modo, recibo, fonte, identidade e forma
  - o JSON externo permanece modo 0600 e não é copiado ao repositório
  - nenhum caminho pessoal, binding, digest de alvo, valor de ledger, hash derivado por posição ou dado de domínio entra no pacote
  - privacy guard, git diff --check e manifesto reproduzível passam no candidato exato
riscos_de_tenant:
  - inferir aplicação a partir de match ou ordem pode legitimar schema incorreto; toda classificação permanece evidência candidata
  - misturar epochs pode importar uma história de migration para outro ambiente; trust anchors são independentes
  - hashes de timestamps de 14 dígitos são enumeráveis; o JSON fica externo, modo 0600 e sob gate
  - alterar ledgers destrói a evidência do desvio; o desenho proíbe backfill e reordenação
  - incluir private_runtime sem contrato próprio mudaria o universo 77 e tornaria as contagens 30/75 ambíguas
plano_de_teste:
  - conferir inventário top-level 77 e recursive 78 no pino de1ea1e, sem abrir conteúdo de dados ou ambiente
  - reproduzir digest dos 77 basenames e catalog_ref por receita versionada
  - executar derivador no mesmo pino e captura congelada e exigir JSON byte-idêntico por SHA-256, sem imprimir o JSON
  - conferir contagens 2 matched, 30 unmatched, 2 matched no catálogo e 75 sem chave PROD
  - validar que 17 basenames não deriváveis têm linhas individuais e motivo
  - executar privacy guard, busca por caminho pessoal, git diff --check e reprodução do manifesto
plano_de_rollback:
  - descartar somente os arquivos locais desta missão se os conselheiros rejeitarem o candidato
  - nenhuma compensação de banco existe porque esta missão não produz escrita
fora_de_escopo:
  - PROD, DEV, VPS, banco, migration, ledger write, executor, epoch materializado, cutover, deploy, credencial, envio, billing, broadcast, Brevo e ativação
  - commit, push, PR e merge
proximo_gate: OpenCode e QWEN 3.8 FLASH conferem os mesmos bytes do pacote; após APTO conjunto, qualquer commit, push, PR ou fase executável exige decisão humana própria
```

## Fontes congeladas permitidas

O pacote usa somente os resultados sanitizados já aceitos: catálogo top-level
com 77 entradas no pino `de1ea1e659be9a4f2a988740b72a9ed8edd68bfb`, árvore
Git `ff84b1274a342ea47e1e378446ed72caa27cef4b`, captura PROD congelada
sob recibo externo e JSON sanitizado SHA-256
`5399bb7db895be26c7fb0dcaf67375d0aa7a78c58c03de80b50ed27a9fd2944d`,
modo `0600`. O JSON não entra no repositório.

A classificação aceita é estritamente: duas entradas
`MATCHED_BY_DERIVED_KEY`, trinta `UNMATCHED_IN_CATALOG`, duas entradas de
catálogo correspondentes e setenta e cinco
`CATALOG_ENTRY_WITHOUT_PROD_KEY`. Nenhuma classe prova aplicação.
