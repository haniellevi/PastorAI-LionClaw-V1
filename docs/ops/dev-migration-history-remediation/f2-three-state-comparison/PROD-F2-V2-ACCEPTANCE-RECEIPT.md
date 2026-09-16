# Recibo de aceitação, F2 PROD v2

## Exceção delimitada de duplicação

| Campo | Estado sanitizado |
| --- | --- |
| Classe da fonte | captura externa de diagnóstico de forma, somente leitura |
| SHA-256 total aceito | `8a8601efc9e6bbc7d8772570a2d78535073c13e999753bf12ea92bdcf6868bd3` |
| Modo e tamanho | `0600`, `2182` bytes |
| Horário explícito da coleta | `2026-09-16T12:52:26-03:00` |
| Regra aceita | `DUPLICATED_IDENTICAL_CAPTURE_2X` |
| Cópias físicas | exatamente `2` |
| SHA-256 de cada metade | `d9f8deff50021757469a6dd0b1ec0ad9858bdd8602b40d1a74514dd24287624d` |
| Observação lógica após deduplicação | exatamente `1` |
| Caminho local e conteúdo | não persistidos |

O validador divide os bytes em duas metades de mesmo tamanho antes de analisar
qualquer registro. Ele aceita somente duas metades byte-idênticas, cada uma com
um digest opaco e um encerramento `ROLLBACK_COMPLETED_F2_PROD_DIAG` terminal.
Uma cópia, três cópias, metades distintas, recibo ausente, recibo não terminal
ou multiplicidade diferente falham fechados.

## Forma aceita e limite de interpretação

A observação lógica aceita mostra ledger público ausente e ledger nativo
presente com cardinalidade `32`. Ela descreve forma e cardinalidade. Não retém
identidade sanitizada dessas 32 entradas, statements, linhas de ledger,
definições, binding, alvo conectado ou dados de domínio.

A duplicação não multiplica a evidência nem repara uma coleta. Foi aceita apenas
porque o contrato congelado exige exatamente as duas metades idênticas. Em uma
coleta futura nominalmente autorizada, a recomendação é incluir a saída uma só
vez, para eliminar esta exceção operacional. Esta recomendação não contém
procedimento executável e não reabre F2.

O único próximo gate deste candidato é parecer `APTO` conjunto de OpenCode e
CLAUDE sobre os mesmos bytes antes de commit, push ou publicação.
