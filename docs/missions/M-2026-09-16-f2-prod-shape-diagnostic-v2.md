---
id: M-2026-09-16-f2-prod-shape-diagnostic-v2
status: preparacao_local_autorizada
prepared_at: 2026-09-16T00:35:00-03:00
environment: local_disposable_pg17_only
execution_authorized: false_pending_joint_precollection_review
---

# F2 PROD v2: diagnostico somente leitura da forma dos ledgers

## Ficha Mission Control

```yaml
id: M-2026-09-16-f2-prod-shape-diagnostic-v2
objetivo: produzir um diagnostico sanitizado e somente leitura da forma atual dos dois ledgers em PROD, sem tratar drift como erro e sem comparar com DEV
preflight:
  repositorio: github.com/haniellevi/PastorAI-LionClaw-V1
  branch: docs/dev-migration-history-remediation-f2-readonly-20260915
  sha_efetivo: f856f53f48e79a53609ff699d5603119f60202e0
  worktree_limpo: false; somente o pacote F2 aprovado e esta missao aparecem como arquivos locais nao rastreados
  ambiente: local; nenhuma sessao PROD ou DEV nesta preparacao
  horario: 2026-09-16T00:35:00-03:00
  runbook_lido: docs/ops/MISSION-CONTROL.md; docs/ops/MAESTRI-PERSISTENCE-MANIFEST.md; docs/missions/M-2026-09-15-f2-prod-readonly-collection.md; docs/ops/dev-migration-history-remediation/f2-readonly/RANIEL-READONLY-F2-RUNBOOK.md
  grafo: nao disponivel; code-review-graph permanece desabilitado
worktree: .worktrees/dev-migration-history-remediation-f2-readonly-20260915
branch: docs/dev-migration-history-remediation-f2-readonly-20260915
sha_base: f856f53f48e79a53609ff699d5603119f60202e0
especialistas:
  - FORJA, gpt-5.6-terra max, implementacao local no worktree F2
  - OpenCode, CONSELHEIRO, revisao pre-coleta somente leitura
  - CLAUDE, CONSELHEIRO, revisao pre-coleta somente leitura
arquivos_permitidos:
  - docs/missions/M-2026-09-16-f2-prod-shape-diagnostic-v2.md
  - docs/ops/dev-migration-history-remediation/f2-prod-shape-diagnostic-v2/PROD-READONLY-F2-DIAG-v2.sql
  - docs/ops/dev-migration-history-remediation/f2-prod-shape-diagnostic-v2/RANIEL-PROD-DIAG-v2-RUNBOOK.md
  - docs/ops/dev-migration-history-remediation/f2-prod-shape-diagnostic-v2/run-pg17-f2-prod-diag-v2-e2e.sh
  - docs/ops/dev-migration-history-remediation/f2-prod-shape-diagnostic-v2/F2-PROD-DIAG-v2-CANDIDATE-MANIFEST.md
criterios_de_aceite:
  - o pacote F2 anterior permanece byte-identico
  - o SQL relata existencia e forma dos ledgers, cardinalidades, colunas, triggers e rules sem imprimir nome inesperado ou conteudo de statement
  - drift de forma e resultado; somente fonte, privacidade, binding, sessao, timeout ou teto excedido abortam
  - todas as listagens tem teto declarado e o excesso retorna codigo sanitizado antes de qualquer evidencia parcial
  - o SQL usa uma transacao REPEATABLE READ READ ONLY, timeouts 5000/1000/15000 ms, row_security off, ROLLBACK e recibo terminal por qecho
  - o runner PostgreSQL 17 descartavel, sem rede e sem porta, prova todas as classes de drift, opacidade, digest, limites e rollback
  - o manifesto fecha o conjunto exato e reproduz todos os hashes
  - OpenCode e CLAUDE marcam APTO os mesmos bytes antes de qualquer coleta PROD
riscos_de_tenant:
  - nome de objeto inesperado pode identificar estrutura privada; toda referencia nao allowlisted vira digest opaco
  - conteudo do ledger nativo pode conter SQL ou dado sensivel; nenhuma linha ou statement e lido ou emitido
  - consulta de relacao errada pode tocar dominio; fontes ficam restritas a pg_catalog e aos dois ledgers canonicos por OID validado
  - listagem ilimitada pode produzir carga ou vazamento; cada classe possui teto validado antes da primeira linha de evidencia
  - alvo incorreto pode gerar prova enganosa; binding novo produz TARGET_DIGEST e e verificado fora da transcricao
plano_de_teste:
  - runner PostgreSQL 17.6 local descartavel com rede none e nenhuma porta publicada
  - fixtures: public ausente e presente, cardinalidade diferente, coluna extra, tipo trocado, notnull diferente, trigger e rule inesperados, teto excedido, digest estavel e sensivel ao alvo
  - inspecao source-only de fontes, comandos proibidos, qecho terminal e ausencia de nomes crus nas saidas
  - privacy guard do repositorio, git diff --check e reproducao do manifesto
plano_de_rollback:
  - remover somente os cinco arquivos locais desta missao se o candidato for rejeitado
  - o runner remove o container descartavel em trap e nao publica porta
  - uma coleta futura sempre termina em ROLLBACK; aborto ou erro encerra a sessao sem repeticao automatica
proximo_gate: APTO conjunto de OpenCode e CLAUDE sobre SQL, runbook, runner, manifesto e hashes exatos antes de Raniel executar PROD fora do pico
```

## Evidencia do gatilho

O SQL PROD F2 estrito, SHA-256
`a30be6984b09ad558a615b0440c4a656c61f3d70ef1ba4ac988512d66de66285`,
retornou somente `F2_ABORT_PROD_LEDGER_SHAPE_DRIFT` em
2026-09-16T00:12:59-03:00. A captura de 33 bytes, modo 0600, tem SHA-256
`f6e943f7bf63aa637a4999969b0e101cd0f6649591e6ab24198f274798759f32`.
Nenhuma escrita, coleta DEV ou comparacao foi feita. O evento prova mudanca de
forma em relacao a evidencia historica; nao prova causa nem migration aplicada.

## Limites

Esta missao prepara bytes e testes locais. Ficam fora: abrir sessao PROD ou
DEV, comparar ambientes, desenhar epoch/cutover, implementar executor, criar ou
aplicar migration, escrever em banco, acessar credenciais, commitar, publicar,
fazer push ou merge. O pacote F2 anterior permanece congelado e separado.
