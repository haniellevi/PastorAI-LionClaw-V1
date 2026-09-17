# Contrato de não importação DEV e PROD

## Escopo semântico

Um epoch é uma interpretação limitada da evidência do próprio ambiente. O
epoch DEV futuro só poderá considerar fontes DEV autenticadas e seus próprios
trust anchors. Um eventual epoch PROD exige fontes e anchors próprios. Nenhum
dos dois é criado por este pacote.

## Proibições fechadas

| Operação proibida | Regra |
| --- | --- |
| Usar ordem DEV para concluir PROD, ou ordem PROD para concluir DEV | A ordem de cada ledger pertence ao ambiente que a emitiu. |
| Converter presença em um ambiente em ausência no outro | Ledgers público e nativo não são equivalentes, inclusive dentro do mesmo ambiente. |
| Promover posição, contagem, data ou hash a aplicação | Esses sinais descrevem forma ou observação, não causalidade. |
| Promover match de formato a equivalência histórica | Match candidato não prova aplicação. |
| Usar um ensaio DEV como fechamento de lacuna PROD | A identidade e a fonte PROD permanecem independentes. |
| Usar PROD para preencher lacuna DEV | A atestação humana, o catálogo aplicável e a representação DEV precisam de prova própria. |

Evidência do contrato de separação:
`docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/EPOCH-TRUST-ANCHORS.md:5-8,24-31`.
Evidência do mecanismo divergente:
`docs/ops/dev-migration-history-remediation/f2-three-state-comparison/THREE-STATE-COMPARISON.md:22-32`.

## Preservação dos ledgers

O ledger público e o ledger nativo permanecem fatos históricos integrais. Este
contrato proíbe backfill, reordenação, exclusão, atualização, inserção
retroativa, renomeação interpretativa ou qualquer tentativa de fazer um ledger
simular o outro. A obrigação está alinhada à ficha em
`docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:81-82` e ao desenho
anterior em
`docs/ops/dev-migration-history-remediation/f2-three-state-comparison/STRATEGY-A-B-EPOCH-CUTOVER.md:5-9`.

## Resultado diante de ambiguidade

Qualquer fonte, vínculo ou classificação insuficiente mantém o respectivo
epoch não materializado. O resultado não é falha parcial de aplicação, porque
nenhuma aplicação é autorizada; é somente a conservação explícita da lacuna.
