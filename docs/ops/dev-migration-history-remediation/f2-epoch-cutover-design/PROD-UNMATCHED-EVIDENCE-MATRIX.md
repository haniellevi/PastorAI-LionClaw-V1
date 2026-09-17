# Matriz de evidência PROD sem match

## Estado sanitizado aceito

O JSON externo permanece fora do repositório, com modo `0600` e SHA-256
`5399bb7db895be26c7fb0dcaf67375d0aa7a78c58c03de80b50ed27a9fd2944d`.
Ele registra `32` posições PROD: `2` `MATCHED_BY_DERIVED_KEY` e `30`
`UNMATCHED_IN_CATALOG`. Nenhuma posição, hash ou classe deste anexo prova
aplicação. Não há hash derivado por posição neste pacote.

`2 + 30 = 32`.

## Coortes PROD sem match

| Coorte | Posições | Contagem | Estado sanitizado | Evidência extra necessária antes de qualquer reclassificação | Gate nominal futuro, não vigente | Conclusão atual |
| --- | --- | ---: | --- | --- | --- | --- |
| A | `1-14, 22-26, 29, 31-32` | `22` | `NO_UNIQUE_DERIVED_KEY` com `NAME_SECONDARY_HASH_MATCH` | Compromisso sanitizado e verificável de identidade um-para-um, independente de posição, ordem, hash de timestamp e nome; proveniência do ledger e atestação humana específica de PROD. | `OWNER_AUTHORIZE_PROD_UNMATCHED_IDENTITY_EVIDENCE_READ_ONLY` | Permanece `UNMATCHED_IN_CATALOG`; o sinal secundário de nome não promove match. |
| B | `15-21, 30` | `8` | `NO_UNIQUE_DERIVED_KEY` com `NAME_SECONDARY_HASH_NO_MATCH` | Tudo o que a coorte A exige, mais atestação sanitizada de formato ou nomenclatura que explique a incompatibilidade sem expor nome cru ou valor de ledger. | `OWNER_AUTHORIZE_PROD_UNMATCHED_FORMAT_AND_IDENTITY_EVIDENCE_READ_ONLY` | Permanece `UNMATCHED_IN_CATALOG`; não há base para aproximar por data, ordem ou cardinalidade. |

`22 + 8 = 30`. Os gates da tabela são requisitos humanos posteriores e não
são o próximo gate deste candidato. Nenhuma leitura adicional, coleta, conexão
ou inferência causal é autorizada agora.

## Lado do catálogo

| Coorte | Contagem | Estado | Tratamento documental |
| --- | ---: | --- | --- |
| Chave derivável sem posição PROD | `58` | `PROD_KEY_ABSENT` | Permanece `CATALOG_ENTRY_WITHOUT_PROD_KEY`; ausência de chave não prova ausência de aplicação. |
| Basename não derivável | `17` | `BASENAME_NOT_DERIVABLE` | Permanece `CATALOG_ENTRY_WITHOUT_PROD_KEY`; o inventário individual está no anexo próprio. |

`58 + 17 = 75`, e `2 + 75 = 77` no catálogo top-level fechado. O único SQL
recursivo em `private_runtime` não integra esses números, pois o contrato atual
é top-level e uma inclusão futura exigiria outro contrato.

## Aceite futuro de determinismo

Somente no mesmo pino, catálogo top-level e captura congelada, a derivação
precisa reproduzir o JSON byte a byte e o SHA-256 declarado. Divergência de
hash, modo, recibo, fonte, identidade, forma ou determinismo falha fechada.
Mesmo um resultado determinístico mantém as três classes como evidência
candidata, sem afirmar aplicação.

## Próximo gate único

Estado vigente após a rodada corretiva do PR #403: OpenCode e QWEN concluíram o APTO conjunto sobre estes bytes, e o commit e o push corretivos foram publicados no PR #403. O MERGE permanece retido até frase nominal de Raniel, e qualquer fase executável exige gate humano próprio.
