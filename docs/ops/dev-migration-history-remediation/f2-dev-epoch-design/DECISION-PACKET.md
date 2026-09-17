# Pacote de decisão, epoch DEV F2

## Decisão

Recomendo manter o desenho `DEV_EPOCH_UNMATERIALIZED`. A fonte DEV aceita
possui integridade documental e forma sanitizada confirmadas, porém faltam a
atestação humana específica do ambiente, catálogo autenticado aplicável,
representação durável, idempotência, executor revisado, rollback ou
compensação e autorização nominal para materialização.

Essa decisão preserva a diferença entre fonte, interpretação e efeito. Ela não
declara que uma migration tenha sido aplicada e não autoriza mutação de ledger,
cutover, executor ou ambiente vivo.

## Base de decisão

| Tema | Estado conservador | Evidência |
| --- | --- | --- |
| Fonte DEV | aceita somente pelo SHA-256 completo, modo `0600`, tamanho, horário e recibo declarados | `SOURCE-CONFERENCE.md` |
| Forma DEV | sessão declarada com ledger público `33` e nativo `6` | `SOURCE-CONFERENCE.md` |
| Interpretação de histórico | `INCONCLUSIVE_NON_PREFIX` para o lado público e `INCONCLUSIVE_IDENTITY_LIMITED` para o nativo | `docs/ops/dev-migration-history-remediation/f2-three-state-comparison/THREE-STATE-COMPARISON.md:17-20,27-32` |
| Identidade humana DEV | `FALTANTE` | `DEV-EPOCH-TRUST-ANCHORS.md` |
| Materialização | bloqueada pelas lacunas enumeradas | `MATERIALIZABILITY-GAPS.md` |
| Separação DEV e PROD | obrigatória, sem importação de ordem, presença ou conclusão | `NO-IMPORT-CONTRACT.md` |

## Ajuste cosmético isolado

O único arquivo existente alterado por esta missão troca o basename de
placeholder `f2-prod-native-identity-cast.txt` por
`f2-prod-native-identity-cast-retry-01.txt` em
`docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/REPRODUCIBILITY-RECIPES.md`.
Não há alteração de receita, captura, ambiente, interpretação, SQL, runner ou
manifesto do pacote anterior. O hash atual desse arquivo é vinculado pelo
manifesto deste candidato.

## Fora de escopo

Coortes A/B de PROD, SQL, runners, coleta adicional, epoch materializado,
executor, backfill, reordenação, escrita, banco, DEV, PROD e VPS permanecem
fora desta missão. A documentação não prepara nem autoriza uma fase executável.

## Próximo gate humano único

Depois de o candidato exato receber parecer conjunto `APTO` de OpenCode e QWEN
e de a CI estar verde, Raniel poderá proferir a frase nominal: `Autorizo o
merge do PR <número> da missão M-2026-09-17-f2-dev-epoch-design-offline.` Essa
frase é o único gate humano deste pacote. O parecer e a CI são pré-condições
verificáveis, não gates concorrentes.
