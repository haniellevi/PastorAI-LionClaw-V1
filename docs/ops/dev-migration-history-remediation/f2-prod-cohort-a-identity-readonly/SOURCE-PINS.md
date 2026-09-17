# Fontes congeladas e membresia

## Pinos obrigatórios

| Fonte | SHA-256 | Custódia | Uso permitido neste briefing |
| --- | --- | --- | --- |
| Captura PROD native identity aceita | `c7831ca5d17b8c250e2cd7a6bc1a5f65c66ddcd874ddbca214c16f4d067b8830` | externa, modo `0600` | referência por hash; não abrir ou copiar |
| Derivador aprovado | `d3f0e9610ace59d704bb5e77dc49e52f6f115cdf2b7847a8bd7e0b5bcc3c85e8` | externo ao pacote | referência por hash; não executar |
| JSON sanitizado aceito | `5399bb7db895be26c7fb0dcaf67375d0aa7a78c58c03de80b50ed27a9fd2944d` | externo, modo `0600` | referência por hash; não abrir ou copiar |
| Base documental | `18ecd50472a309de3ac838f898f3a6ade9ff763d` | Git | fonte versionada desta missão |

O resultado derivado anterior registrou `32` posições PROD, com `2`
`MATCHED_BY_DERIVED_KEY` e `30` `UNMATCHED_IN_CATALOG`. Isso não prova
aplicação. O digest de 14 dígitos e o hash de nome são enumeráveis e servem
somente para consistência de formato e membresia.

## Coorte fechada

```text
1,2,3,4,5,6,7,8,9,10,11,12,13,14,22,23,24,25,26,29,31,32
```

A contagem obrigatória é `22`. A seleção futura usa `row_number() OVER
(ORDER BY version ASC)` somente para recuperar este conjunto. Qualquer
duplicidade de version, cardinalidade total diferente de `32` ou divergência
nos hashes congelados da membresia falha fechada antes de reclassificação.

## Regra de custódia

Antes de qualquer leitura futura, o operador confere arquivo regular,
não-symlink, modo e SHA-256. Hash e modo divergentes encerram o procedimento.
O pacote atual não possui os caminhos externos, não tenta descobri-los e não
abre os arquivos.

O próximo gate único permanece
`OWNER_AUTHORIZE_PROD_UNMATCHED_IDENTITY_EVIDENCE_READ_ONLY`.
