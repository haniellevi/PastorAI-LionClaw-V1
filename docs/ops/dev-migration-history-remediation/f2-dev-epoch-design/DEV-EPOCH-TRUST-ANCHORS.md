# Trust anchors do epoch DEV

## Regra de classificação

`SATISFEITO` significa que o fato sanitizado possui evidência versionada
identificada. `PARCIAL` significa que há evidência útil, porém insuficiente
para materialização. `FALTANTE` significa que nenhuma inferência pode ocupar o
lugar da prova exigida. Nenhum estado abaixo afirma migration aplicada.

| Trust anchor | Estado | Evidência arquivo:linha | Razão verificável |
| --- | --- | --- | --- |
| Integridade da captura DEV aceita | `SATISFEITO` | `docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md:7-14` | SHA-256 completo, modo, tamanho, horário e cópia declarada estão registrados. |
| Unicidade e supersessão da fonte | `SATISFEITO` | `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:57-58`; `docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md:11-12` | A fonte anterior é explicitamente `SUPERSEDED` e não pode ser reutilizada. |
| Recibo terminal e ausência de aborto | `SATISFEITO` | `docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md:18-21` | Há recibo terminal aceito e o contrato versionado declara ausência de aborto F2. |
| Forma da sessão e dos dois ledgers | `SATISFEITO` | `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:51-56`; `docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md:23-25` | A sessão e as cardinalidades sanitizadas foram fixadas sem transportar conteúdo. |
| Declarações humanas de conferência técnica | `SATISFEITO` | `docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md:27-30` | As declarações foram recebidas separadamente e não expõem componentes da sessão. |
| Identidade humana específica do ambiente DEV | `FALTANTE` | `docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md:34-37`; `docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/EPOCH-TRUST-ANCHORS.md:14,20-22` | O vínculo técnico da coleta não substitui atestação humana externa e específica de DEV. |
| Catálogo autenticado aplicável ao epoch DEV | `FALTANTE` | `docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/EPOCH-TRUST-ANCHORS.md:14-18,35-40` | O catálogo é fonte versionada de forma; falta vinculá-lo autenticadamente ao epoch DEV pretendido. |
| Leitura conservadora da divergência | `PARCIAL` | `docs/ops/dev-migration-history-remediation/f2-three-state-comparison/THREE-STATE-COMPARISON.md:17-20,27-32` | O não prefixo e a divergência são conhecidos, mas não há mapeamento materializável de histórico. |
| Contrato de não importação entre ambientes | `SATISFEITO` | `docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/EPOCH-TRUST-ANCHORS.md:24-31`; `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:81-82` | Ordem, presença, match e conclusão não podem cruzar a fronteira DEV/PROD. |
| Preservação documental dos dois ledgers | `SATISFEITO` | `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:82`; `docs/ops/dev-migration-history-remediation/f2-three-state-comparison/STRATEGY-A-B-EPOCH-CUTOVER.md:5-9` | O desenho proíbe backfill, reordenação e mutação retroativa. |
| Representação durável e idempotência do epoch | `FALTANTE` | `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:83-84` | Não existe representação durável ou chave idempotente autorizada neste pacote. |
| Executor revisado e rollback ou compensação | `FALTANTE` | `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:83,111` | Executor, escrita e materialização estão fora do escopo e não possuem prova para esta finalidade. |
| Autorização nominal de materialização | `FALTANTE` | `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:111-118` | A única autorização futura desta missão trata de merge documental, não de materialização. |

## Resultado

O epoch DEV permanece `UNMATERIALIZED`. Os anchors satisfeitos preservam a
fonte e a leitura limitada; qualquer item `FALTANTE` impede materialização.
Os itens `PARCIAL` não podem ser promovidos por posição, ordem, contagem, data
ou hash.
