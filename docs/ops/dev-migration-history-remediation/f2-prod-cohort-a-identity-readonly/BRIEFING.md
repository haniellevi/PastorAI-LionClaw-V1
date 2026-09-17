# Briefing, evidência PROD da coorte A

## Objetivo observável

Preparar uma coleta humana futura que emita, para exatamente 22 entradas do
ledger nativo, compromissos opacos do payload de execução. O resultado serve
para testar uma hipótese de vínculo um-para-um com o catálogo em etapa offline
posterior. Nenhum compromisso, isoladamente, prova aplicação.

## Escopo fechado

A membresia vem do JSON sanitizado congelado e contém as posições
`1-14, 22-26, 29, 31-32`, total `22`, na ordenação `version ASC` do
ledger nativo. A posição seleciona o conjunto e permite conferir que nenhuma
linha saiu ou entrou. Ela é proibida como prova de identidade.

A evidência primária exclui posição, ordem entre linhas, timestamp, version e
name. O SQL propõe um compromisso com binding novo sobre o array de statements
com framing fixo. Rollback e idempotency recebem compromissos suplementares,
sem valores crus.

## Entregáveis deste briefing

1. `SOURCE-PINS.md` fixa as três fontes anteriores e a membresia.
2. `EVIDENCE-CONTRACT.md` define o que pode e não pode sustentar um match.
3. `PROD-READONLY-F2-COHORT-A.sql` é uma proposta fail-closed, nunca executada
   nesta missão.
4. `RANIEL-PROD-COHORT-A-RUNBOOK.md` descreve a operação humana futura.
5. `run-pg17-f2-prod-cohort-a-e2e.sh` e o validador estático formam a proposta
   de prova local, também não executada nesta missão.
6. `CANDIDATE-MANIFEST.md` vincula todos os bytes.

## Critério de reclassificação futura

Cada uma das 22 entradas precisa ter um compromisso primário único e corresponder
a exatamente um compromisso de catálogo produzido independentemente. Nenhum
candidato pode ser reutilizado. Os 22 hashes de versão e nome precisam apenas
reproduzir a membresia congelada; eles não contam como evidência de identidade.

Falha de unicidade, ausência de payload, divergência de fonte, alvo, forma,
modo, hash, cardinalidade ou recibo mantém toda entrada afetada como
`UNMATCHED_IN_CATALOG`.

## Limites

Este briefing não lê fontes externas, não abre PROD, não executa SQL e não
antecipa a missão posterior. A captura futura fica fora do repositório, modo
`0600`, e não pode ser publicada. O único próximo gate é
`OWNER_AUTHORIZE_PROD_UNMATCHED_IDENTITY_EVIDENCE_READ_ONLY`.
