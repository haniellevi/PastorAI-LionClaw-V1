# Recibo selado, F2 DEV

## Vínculo da fonte

| Campo | Estado sanitizado |
| --- | --- |
| Classe da fonte | captura externa única, somente leitura |
| SHA-256 da captura aceita | `18d2e78ffc16d26f20f1e58459969c9c3bcc5cf58896c33c6225daedd01f6cb9` |
| Modo e tamanho | `0600`, `405404` bytes |
| Cópias físicas e lógicas | `1` e `1` |
| Captura anterior | prefixo `5fbd1c8f` está `SUPERSEDED` e é rejeitado como fonte |
| Caminho local | não persistido |
| Conteúdo da captura | não copiado para este pacote |

## Contrato validado

O validador offline deste candidato confirmou uma única ocorrência opaca de
`TARGET_DIGEST`, sessão `DEV` em `PG170006`, `REPEATABLE READ`, somente leitura
e `row_security=off`. O encerramento válido foi
`ROLLBACK_COMPLETED_F2_DEV`; não houve aborto F2.

O contrato também fechou `33` entradas no ledger público e `6` no ledger
nativo, com seis fingerprints nativos. A observação de catálogo foi aceita
somente em formatos conhecidos, com nomes não canônicos mantidos opacos.

As declarações humanas recebidas separadamente são `DIGEST_CONFERE`,
`PREFIXO_BINDING_0=0/0/0` e `F2_TARGET_DIGEST_VERIFIED_PREFIX_ABSENT`. Elas não
revelam binding, conexão, digest ou conteúdo da captura e não são inferidas do
schema.

## Limite do recibo

Este recibo prova somente que a captura externa com esses metadados satisfez o
contrato sanitizado. Ledgers, relações e assinaturas observadas não provam que
migrations foram aplicadas, que a ordem seja um prefixo do catálogo, nem que a
identidade humana de DEV esteja demonstrada pelo digest conectado.

O único próximo gate deste candidato é parecer `APTO` conjunto de OpenCode e
CLAUDE sobre os mesmos bytes antes de commit, push ou publicação.
