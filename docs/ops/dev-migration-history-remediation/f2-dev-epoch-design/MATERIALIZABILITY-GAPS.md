# Lacunas para materializar um epoch DEV

## Princípio

Materializar um epoch exigiria uma interpretação durável, idempotente e
autorizada de fontes autenticadas. A existência de captura, ledger, forma de
sessão ou contagem não satisfaz esse limiar. Este documento enumera lacunas,
sem propor ação executável para fechá-las.

| Lacuna | Estado atual | Prova exigida antes de materialização | Por que não pode ser inferida |
| --- | --- | --- | --- |
| Atestação humana específica de DEV | `FALTANTE` | Declaração humana externa que associe o rótulo DEV à fonte congelada, sem substituir o controle técnico de integridade. | O recibo limita-se à coleta e declara que não demonstra essa identidade. |
| Fonte DEV autenticada para uso materializável | `PARCIAL` | Custódia e elegibilidade da fonte no processo futuro, preservando SHA-256, modo, tamanho e recibo. | Integridade do arquivo não prova por si só autoridade para interpretar ou materializar. |
| Catálogo autenticado no pino aplicável | `FALTANTE` | Pino, árvore, universo e digest reproduzíveis, vinculados ao epoch DEV futuro. | O catálogo Git descreve fonte versionada, não estado ou identidade do ambiente. |
| Mapeamento conservador da divergência | `PARCIAL` | Modelo de classes que mantenha as posições divergentes sem promover presença a aplicação. | DEV não é prefixo do catálogo e os dois ledgers não resolvem o vínculo. |
| Representação durável do epoch | `FALTANTE` | Contrato de armazenamento, integridade, retenção e leitura com escopo definido. | Este pacote contém somente documentos e não cria registro persistente. |
| Idempotência | `FALTANTE` | Chave estável, verificação de repetição e comportamento seguro para tentativa já registrada. | Não há operação autorizada da qual derivar uma chave ou recibo. |
| Executor revisado | `FALTANTE` | Executor delimitado, revisão independente, controles de tenant, limites e evidência de teste pertinente. | SQL, runner e executor estão fora do escopo da missão. |
| Rollback ou compensação | `FALTANTE` | Plano verificável que preserve os dois ledgers e não simule backfill. | Nenhum efeito foi desenhado ou autorizado para receber compensação. |
| Autorização nominal | `FALTANTE` | Autorização humana posterior, específica para a futura materialização. | A autorização futura desta missão é documental e não se estende a ambiente ou escrita. |

As lacunas são derivadas da ficha em
`docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md:78-84,108-118` e do
limite de identidade do recibo em
`docs/ops/dev-migration-history-remediation/f2-three-state-comparison/DEV-F2-SEALED-RECEIPT.md:34-37`.

## Consequência fail-closed

Enquanto qualquer lacuna acima persistir, o único resultado correto é manter o
epoch DEV não materializado. Não se admite preencher uma lacuna com evidência
PROD, presença de ledger, ordem, data, contagem, forma estrutural ou match de
hash. Os dois ledgers continuam preservados integralmente como fatos
históricos, sem backfill, reordenação, inserção retroativa, atualização ou
remoção.
