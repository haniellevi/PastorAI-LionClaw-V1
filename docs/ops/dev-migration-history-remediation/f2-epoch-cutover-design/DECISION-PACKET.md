# Pacote de decisão, F2 epoch e cutover offline

## Decisão documental

Recomendo a estratégia A: epochs separados para DEV e PROD, cada um ligado a
suas próprias trust anchors, sem reordenar, preencher ou reinterpretar o
ledger do outro ambiente. O objetivo é preservar o desvio observado e tornar
as lacunas verificáveis antes de qualquer decisão operacional futura. Esta
recomendação não materializa epoch, cutover, executor, migration ou escrita.

## Universo de fonte fechado

| Item | Fato sanitizado aceito |
| --- | --- |
| Pino de derivação e `origin/main` observados | `de1ea1e659be9a4f2a988740b72a9ed8edd68bfb` |
| Árvore `backend/migrations` | `ff84b1274a342ea47e1e378446ed72caa27cef4b` |
| Catálogo histórico | `77` arquivos `.sql` top-level |
| Arquivos `.sql` recursivos | `78` |
| Digest dos `77` basenames | `950bde59ce2b65b4596a6ca9ecf284a85aa18ba49dba9b8cac6913004b8fa415` |
| Checkout primário observado por QWEN | `108cb4eb80f3ff1a7d2de2d3f9eeeba74ac2a27b`, branch `docs/consent-tarefas-operacionais-filadelfia-approved` |

O checkout observado por QWEN é somente um checkout observado, nunca
`main`. A fonte de catálogo deste pacote é o pino acima, com seleção direta de
`backend/migrations`. O único SQL recursivo fora do top-level fica sob
`backend/migrations/private_runtime/` e está excluído do catálogo histórico.
Essa exclusão é obrigatória porque o contrato atual do catálogo e do derivador
usa apenas arquivos diretos. Incluir `private_runtime` exigiria contrato
próprio e mudaria o universo `77/75`; não é permitido neste desenho.

## Evidência PROD e limites de interpretação

O JSON sanitizado externo permanece fora do repositório, em modo `0600`, com
SHA-256 `5399bb7db895be26c7fb0dcaf67375d0aa7a78c58c03de80b50ed27a9fd2944d`.
O resultado aceito contém `2` posições
`MATCHED_BY_DERIVED_KEY` e `30` `UNMATCHED_IN_CATALOG`; no lado do catálogo,
há `2` correspondências e `75` `CATALOG_ENTRY_WITHOUT_PROD_KEY`.

Essas classificações descrevem apenas consistência candidata de formato. Um
match, uma posição, uma data, uma ordem ou um hash não prova aplicação de
migration. Hashes de chaves de 14 dígitos são enumeráveis e não constituem
anonimização.

## Direção por ambiente

| Ambiente | Epoch futuro | Âncora exigida | Proibição de importação |
| --- | --- | --- | --- |
| DEV | Epoch DEV independente | Identidade humana atestada, fontes DEV congeladas e catálogo autenticado no pino aplicável | Não importar ordem, presença, match ou conclusão de PROD. |
| PROD | Epoch PROD independente | Identidade humana atestada, JSON sanitizado congelado, recibo, forma e catálogo autenticado no pino aplicável | Não importar ordem, presença, match ou conclusão de DEV. |

Os dois ledgers, público e nativo, permanecem fatos históricos distintos e
íntegros. São proibidos backfill, reordenação, `DELETE`, `UPDATE`, inserção
retroativa ou qualquer tentativa de fazer um ledger simular o outro.

## Lacunas que permanecem bloqueadas

As coortes PROD `22/8` e as coortes de catálogo `58/17` são tratadas nos
anexos deste pacote. A lacuna não é sinal para completar uma história por
ordem, nome ou cardinalidade. Cada coleta adicional, se vier a ser considerada,
exige autorização nominal futura, fonte delimitada, recibo e revisão próprios.
Nenhuma leitura nova é autorizada por este candidato.

## Controles fail-closed

Uma fase futura para antes de qualquer efeito quando falhar hash, modo `0600`,
recibo terminal, fonte, identidade, forma, determinismo ou preservação dos dois
ledgers. O artefato JSON só é aceito se, com o mesmo pino, catálogo e captura
congelada, a derivação reproduzir os mesmos bytes e o SHA-256 declarado.

## Próximo gate único

Estado vigente após a rodada corretiva do PR #403: OpenCode e QWEN concluíram o APTO conjunto sobre estes bytes, e o commit e o push corretivos foram publicados no PR #403. O MERGE permanece retido até frase nominal de Raniel, e qualquer fase executável exige gate humano próprio.
