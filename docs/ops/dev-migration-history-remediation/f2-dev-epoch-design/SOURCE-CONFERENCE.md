# Conferência de fonte, F2 epoch DEV

## Limite da conferência

Esta conferência usa somente a ficha congelada e os recibos versionados. A
captura externa não foi aberta, copiada, resumida ou incluída no repositório.
Consequentemente, o resultado vincula apenas metadados sanitizados e não
declara aplicação de migration, estado vivo, identidade humana do ambiente ou
equivalência com outro ambiente.

## Fonte oficial aceita

| Campo | Valor sanitizado | Evidência versionada |
| --- | --- | --- |
| Classe | captura externa única, somente leitura e fora do repositório | `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:40-41` |
| SHA-256 | `18d2e78ffc16d26f20f1e58459969c9c3bcc5cf58896c33c6225daedd01f6cb9` | `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:42`; `docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md:7-10` |
| Modo e tamanho | `0600`; `405404` bytes | `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:43-44`; `docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md:9-11` |
| Horário da coleta | `2026-09-16T13:17:21-03:00` | `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:45`; `docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md:10` |
| Recibo terminal | `F2_DEV_FINAL_RECEIPT=ROLLBACK_COMPLETED_F2_DEV` | `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:46`; `docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md:18-21` |
| Forma declarada | sessão DEV `PG170006`, `REPEATABLE READ`, somente leitura, `row_security=off`, ledger público `33` e nativo `6` | `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:51-56`; `docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md:18-25` |
| Declarações humanas técnicas | aceitas separadamente, sem reproduzir identificadores de sessão ou seus valores | `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:47-50`; `docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md:27-30` |

O recebimento técnico acima fecha a integridade documental da fonte declarada.
Ele não converte a declaração humana técnica em atestação da identidade DEV.

## Fonte recusada

| Referência | Estado | Regra |
| --- | --- | --- |
| Prefixo `5fbd1c8f` | `SUPERSEDED` | Nunca é fonte desta missão, mesmo se qualquer outro metadado parecer compatível. |

Evidência: `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:57-58` e
`docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md:11-14`.

## Leitura permitida e limites

As contagens, a forma de sessão e o recibo descrevem uma coleta sanitizada. A
fonte não demonstra que o ledger seja prefixo do catálogo, que uma posição seja
canônica ou que uma migration tenha sido aplicada. O recibo versionado registra
essa limitação expressamente em
`docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md:34-37`.

O catálogo, DEV e PROD continuam estados distintos. A comparação anterior
classifica o DEV como não prefixo e mantém as posições `25` a `32` como
restrição, sem transformar `33` entradas públicas ou `6` nativas em posições
aplicadas. Evidência:
`docs/ops/dev-migration-history-remediation/f2-three-state-comparison/THREE-STATE-COMPARISON.md:17-20`.
