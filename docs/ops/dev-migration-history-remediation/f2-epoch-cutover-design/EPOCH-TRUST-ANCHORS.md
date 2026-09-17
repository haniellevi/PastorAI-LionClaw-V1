# Epochs e trust anchors independentes

## Regra de separação

Um epoch registra uma interpretação limitada de evidência congelada para um
único ambiente. Ele não declara migration aplicada, não altera ledger e não
autoriza cutover. DEV e PROD não compartilham epoch, ordem, presença,
conclusão, recibo ou atestação de identidade.

## Trust anchors por ambiente

| Elemento | Epoch DEV futuro | Epoch PROD futuro |
| --- | --- | --- |
| Identidade do ambiente | Atestação humana externa específica de DEV, separada do digest de coleta. | Atestação humana externa específica de PROD, separada do digest de coleta. |
| Fonte observada | Captura DEV própria, congelada e com recibo próprio. | JSON sanitizado externo próprio, SHA-256 `5399bb7db895be26c7fb0dcaf67375d0aa7a78c58c03de80b50ed27a9fd2944d`, modo `0600` e recibo próprio. |
| Catálogo | Pino autenticado aplicável ao epoch DEV. | Pino `de1ea1e659be9a4f2a988740b72a9ed8edd68bfb`, árvore `ff84b1274a342ea47e1e378446ed72caa27cef4b` e universo top-level de `77`. |
| Forma e determinismo | Contrato de forma validado antes da interpretação. | Contrato de forma validado e derivação byte-idêntica no mesmo pino, catálogo e captura. |
| Resultado permitido | Classes conservadoras, sem inferência causal. | Classes conservadoras, sem inferência causal. |

O catálogo é uma fonte versionada comum de formato, não uma âncora de
identidade de ambiente. A observação de `origin/main` e do pino de derivação
não substitui atestação humana de DEV ou PROD.

## Importações proibidas

| Não importar | Razão |
| --- | --- |
| Ordem DEV para PROD, ou PROD para DEV | A ordem de cada ledger pertence ao ambiente que a emitiu. |
| Presença em um ambiente como ausência no outro | Ledgers público e nativo não são equivalentes, mesmo dentro do mesmo ambiente. |
| Match de formato como decisão de aplicação | Chaves de 14 dígitos são enumeráveis e o match não prova aplicação. |
| Conclusão de um ensaio DEV como fechamento de lacuna PROD | PROD exige sua própria identidade, recibo, forma e trust anchor. |

## Estados de trust anchor

| Verificação | Estado necessário antes de um epoch | Falha fechada |
| --- | --- | --- |
| Pino e árvore de catálogo | SHA Git e árvore correspondem ao pacote declarado. | Divergência de SHA, contagem ou digest encerra a fase. |
| Captura externa | Modo `0600`, hash, recibo terminal e forma completos. | Ausência, duplicidade, modo inadequado ou recibo inválido encerra a fase. |
| Identidade | Atestação humana externa e específica do ambiente. | Digest de alvo, conexão ou nome observado não substitui a atestação. |
| Derivação | Mesmo pino, catálogo e captura reproduzem o JSON byte a byte. | SHA diferente ou saída não determinística encerra a fase. |
| Ledgers | Ambos são preservados como observação. | Backfill, reordenação ou mutação retroativa invalida o desenho. |

## Coletas posteriores, ainda não autorizadas

Uma futura coleta da coorte PROD com nome secundário compatível exigiria o
gate nominal posterior, não vigente,
`OWNER_AUTHORIZE_PROD_UNMATCHED_IDENTITY_EVIDENCE_READ_ONLY`. A coorte sem
compatibilidade de nome secundário exigiria, além disso, o gate nominal
posterior, não vigente,
`OWNER_AUTHORIZE_PROD_UNMATCHED_FORMAT_AND_IDENTITY_EVIDENCE_READ_ONLY`.
Esses rótulos descrevem pré-requisitos de uma autorização humana futura; eles
não são próximos gates, não autorizam leitura agora e não substituem o parecer
conjunto exigido para este candidato.

## Próximo gate único

O próximo gate permanece parecer `APTO` conjunto de OpenCode e QWEN 3.8 FLASH
sobre os bytes exatos deste pacote. Nenhum epoch é materializado até existir
autorização humana própria em fase futura.
