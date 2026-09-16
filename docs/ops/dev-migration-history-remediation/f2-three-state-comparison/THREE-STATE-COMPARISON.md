# Comparação de três estados, catálogo, DEV e PROD

## Estados que podem ser comparados

| Estado | Evidência aceita | O que informa | O que não informa |
| --- | --- | --- | --- |
| Catálogo Git/replay | `77` entradas, validação source-only no SHA base | O conjunto versionado que a fonte descreve | Estado de DEV, PROD ou aplicação |
| DEV observado | ledger público `33`, nativo `6`, catálogo opaco | Forma e chaves observadas sob a sessão declarada | Prefixo do catálogo, aplicação ou causalidade |
| PROD v2 observado | público ausente, nativo `32`, forma de ledger | Forma e cardinalidade da observação lógica deduplicada | Identidade das 32 entradas, aplicação ou causalidade |

O catálogo de `77` é fonte Git e resultado de replay local, não um ambiente.
Os ledgers e o schema observados são registros de presença e forma, não prova de
que uma migration tenha sido aplicada.

## Resultado comparativo conservador

DEV não é prefixo do catálogo. A divergência das posições `25` a `32` já foi
documentada em F1 e permanece uma restrição para qualquer epoch. As `33`
entradas públicas não podem ser convertidas em reconhecimento de `33` posições
canônicas, e as `6` entradas nativas não resolvem esse vínculo.

PROD usa mecanismo diferente: o ledger público está ausente e somente a
cardinalidade nativa `32` foi observada. Como a coleta v2 não reteve identidade
sanitizada dessas entradas, não é possível mapear PROD contra catálogo ou DEV.
Essa lacuna é obrigatória para qualquer epoch PROD futuro.

| Comparação | Estado | Razão |
| --- | --- | --- |
| Catálogo `77` x DEV público `33` | `INCONCLUSIVE_NON_PREFIX` | O recorte F1 registra divergências `25` a `32`; presença não equivale a aplicação. |
| Catálogo `77` x DEV nativo `6` | `INCONCLUSIVE_IDENTITY_LIMITED` | Existem hashes opacos, porém não uma equivalência de histórico declarada. |
| Catálogo `77` x PROD nativo `32` | `NOT_COMPARABLE_IDENTITY_UNAVAILABLE` | A fonte PROD v2 prova somente cardinalidade e forma. |
| DEV x PROD | `MECHANISM_DIVERGENT` | DEV tem dois ledgers observados; PROD v2 somente o nativo. |

Um ensaio da estratégia A em DEV é útil para a divergência DEV, porém não
representa PROD isoladamente. Nenhuma comparação acima autoriza escrita,
backfill, reordenação, migration, executor ou cutover.

O único próximo gate deste candidato é parecer `APTO` conjunto de OpenCode e
CLAUDE sobre os mesmos bytes antes de commit, push ou publicação.
