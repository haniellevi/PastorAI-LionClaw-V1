---
id: M-2026-09-16-f2-three-state-comparison-epoch-cutover
status: preparacao_documental_autorizada
environment: local_readonly
execution_authorized: false
---

# F2: comparação de três estados e desenho A/B com epoch/cutover

## Ficha Mission Control

```yaml
id: M-2026-09-16-f2-three-state-comparison-epoch-cutover
objetivo: congelar os recibos sanitizados de DEV e PROD v2, comparar catálogo 77, DEV 33/6 e PROD ausente/32, e propor estratégia A/B com epochs próprios por ambiente sem escrita
preflight:
  repositorio: github.com/haniellevi/PastorAI-LionClaw-V1
  branch: docs/dev-migration-history-remediation-f2-readonly-20260915
  sha_efetivo: f856f53f48e79a53609ff699d5603119f60202e0
  worktree_limpo: false; somente pacotes F2 locais autorizados e não rastreados
  ambiente: local; evidências externas sanitizadas são somente leitura
  horario: 2026-09-16
  runbook_lido: docs/ops/MISSION-CONTROL.md; docs/missions/M-2026-09-15-f2-prod-readonly-collection.md; docs/missions/M-2026-09-16-f2-prod-shape-diagnostic-v2.md; docs/ops/dev-migration-history-remediation/f1-analysis/STRATEGY-A-B-DECISION-PACKET.md
  grafo: não disponível; code-review-graph permanece desabilitado
worktree: .worktrees/dev-migration-history-remediation-f2-readonly-20260915
branch: docs/dev-migration-history-remediation-f2-readonly-20260915
sha_base: f856f53f48e79a53609ff699d5603119f60202e0
especialistas:
  - FORJA, gpt-5.6-terra max, elaboração documental e validador offline
  - OpenCode, CONSELHEIRO, conferência somente leitura
  - CLAUDE, CONSELHEIRO, conferência somente leitura
arquivos_permitidos:
  - docs/missions/M-2026-09-16-f2-three-state-comparison-epoch-cutover.md
  - docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md
  - docs/ops/dev-migration-history-remediation/f2-three-state-comparison/PROD-F2-V2-ACCEPTANCE-RECEIPT.md
  - docs/ops/dev-migration-history-remediation/f2-three-state-comparison/THREE-STATE-INVENTORY.json
  - docs/ops/dev-migration-history-remediation/f2-three-state-comparison/THREE-STATE-COMPARISON.md
  - docs/ops/dev-migration-history-remediation/f2-three-state-comparison/STRATEGY-A-B-EPOCH-CUTOVER.md
  - docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DECISION-PACKET.md
  - docs/ops/dev-migration-history-remediation/f2-three-state-comparison/validate_f2_capture_contract.py
  - docs/ops/dev-migration-history-remediation/f2-three-state-comparison/test_validate_f2_capture_contract.py
  - docs/ops/dev-migration-history-remediation/f2-three-state-comparison/F2-THREE-STATE-CANDIDATE-MANIFEST.md
criterios_de_aceite:
  - a captura DEV oficial fecha por hash, modo, tamanho, recibo, digest, prefixo e forma 33/6; a captura 5fbd1c8f é marcada SUPERSEDED e proibida como fonte
  - a captura PROD aceita somente DUPLICATED_IDENTICAL_CAPTURE_2X; o validador deduplica ao ler e rejeita cópia única, três cópias ou metades diferentes
  - nenhuma transcrição, TARGET_DIGEST, binding, conexão, senha, dado de domínio ou caminho pessoal entra no repositório
  - a comparação distingue catálogo fonte, ledger observado e schema observado; não usa presença como prova de aplicação
  - o pacote declara que DEV e PROD divergem no mecanismo e que o ensaio DEV não representa PROD sozinho
  - estratégias A e B têm custo, risco, rollback ou compensação e critérios verificáveis
  - o desenho usa epochs específicos por ambiente, preserva ledgers sem backfill ou reordenação e não contém comando de escrita
  - qualquer aplicação, coleta adicional, executor, commit, push ou publicação continua fora
  - OpenCode e CLAUDE marcam APTO os mesmos bytes antes de qualquer publicação
riscos_de_tenant:
  - transcrições podem conter identificadores opacos reutilizáveis; ficam fora do repo e o validador não os imprime
  - presença estrutural pode ser confundida com aplicação; todas as classes preservam UNKNOWN ou INCONCLUSIVE quando a evidência não decide
  - usar o ensaio DEV como substituto de PROD pode legitimar mecanismo incorreto; epochs e trust anchors são separados por ambiente
  - alterar ou completar ledger pode apagar a história; o desenho proíbe backfill, reordenação e mutação retroativa
plano_de_teste:
  - validar as duas capturas oficiais somente por contrato, emitindo apenas resumo sanitizado
  - testes sintéticos rejeitam PROD simples, triplicado, não idêntico, recibo ausente ou não terminal, e DEV com forma diferente
  - validar catálogo fonte 77 no SHA exato sem abrir banco
  - reproduzir manifesto, executar privacy guard e git diff --check
plano_de_rollback:
  - descartar somente os dez arquivos locais desta missão se o pacote for rejeitado
  - nenhuma compensação de banco existe porque não há escrita
proximo_gate: APTO conjunto de OpenCode e CLAUDE sobre o candidato comparativo exato antes de commit, push, publicação ou qualquer desenho executável
```

## Fontes congeladas

DEV usa somente a captura externa oficial SHA-256
`18d2e78ffc16d26f20f1e58459969c9c3bcc5cf58896c33c6225daedd01f6cb9`,
modo `0600`, 405404 bytes, e as declarações humanas
`DIGEST_CONFERE`, `PREFIXO_BINDING_0=0/0/0` e
`F2_TARGET_DIGEST_VERIFIED_PREFIX_ABSENT`. A captura anterior
`5fbd1c8f...` está `SUPERSEDED` e não pode ser usada.

PROD v2 usa somente a captura externa SHA-256
`8a8601efc9e6bbc7d8772570a2d78535073c13e999753bf12ea92bdcf6868bd3`,
modo `0600`, 2182 bytes, sob
`DUPLICATED_IDENTICAL_CAPTURE_2X`. Cada metade tem SHA-256
`d9f8deff50021757469a6dd0b1ec0ad9858bdd8602b40d1a74514dd24287624d`,
um digest e um recibo terminal. A duplicação é deduplicada na leitura e não
altera a evidência de forma. Qualquer outro formato reprova.

## Fora de escopo

Não há escrita, migration, aplicação, ledger update, banco, executor, epoch
materializado, cutover, recriação DEV, PROD write, credencial, commit, push,
PR, publicação, deploy ou ativação. Os arquivos F1, F2 read-only e PROD v2 já
congelados permanecem byte-idênticos.
