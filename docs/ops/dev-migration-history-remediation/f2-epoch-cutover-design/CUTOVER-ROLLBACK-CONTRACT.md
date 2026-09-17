# Contrato documental de cutover e rollback

## Limite deste contrato

Este é um desenho de decisão, não um executor. Não contém SQL operacional,
comando de aplicação, migration, conexão, materialização, credencial ou ação em
DEV, PROD ou VPS. Qualquer futura fase executável precisa de autorização humana
separada, trust anchors externos e revisão própria; ela não é consequência
automática deste pacote.

## Invariantes não negociáveis

1. Os ledgers público e nativo são preservados integralmente como fatos
   observados.
2. Não existe backfill, reordenação, `DELETE`, `UPDATE`, inserção retroativa ou
   substituição de uma história por outra.
3. DEV e PROD mantêm epochs, fontes e decisões independentes.
4. Match derivado, posição, ordem, data, hash e cardinalidade não provam
   aplicação.
5. Toda divergência de hash, modo, recibo, fonte, identidade, forma ou
   determinismo interrompe a fase antes de qualquer efeito.

## Fases documentais de um cutover futuro

| Fase | Objetivo limitado | Pré-condições verificáveis | Gate de fase, se futuramente proposto | Falha fechada | Rollback ou compensação |
| --- | --- | --- | --- | --- | --- |
| 0. Revisão e publicação documental | Validar bytes, escopo e fontes sanitizadas. | Manifesto reproduzível, contagens consistentes e ausência de dado privado. | APTO conjunto de OpenCode e QWEN concluído nesta rodada; PR #403 publicado. | Qualquer divergência encerra a revisão. | Reverter apenas por novo commit documental antes do merge. |
| 1. Definição de epoch DEV | Documentar trust anchors próprios de DEV, sem importar PROD. | Atestação humana DEV, fontes DEV congeladas, recibos e forma próprios. | Autorização humana DEV futura, nominal e separada. | Identidade, recibo ou fonte insuficiente. | Manter ledger DEV intacto e registrar a lacuna. |
| 2. Fechamento de lacuna PROD | Avaliar evidência adicional somente se a fonte futura for autorizada. | JSON externo válido, identidade PROD externa e evidência extra das coortes `22/8`. | Autorização humana PROD futura, nominal e separada. | Hash, modo, recibo, forma, identidade ou determinismo divergentes. | Parar, preservar ambos os ledgers e manter `UNMATCHED_IN_CATALOG`. |
| 3. Decisão de cutover | Delimitar impacto, proprietário, tenant, executor e compensação sem alterar história. | Epochs independentes aceitos, critérios operacionais revisados e plano de compensação verificável. | Gate humano novo, específico para a decisão de cutover. | Qualquer pré-condição ausente ou ambiguidade. | Nenhum efeito é iniciado. |
| 4. Fase executável futura | Somente após aprovação explícita, executar um plano fora deste pacote. | Executor revisado, autorização nominal, escopo tenant, observabilidade e compensação aprovados. | Gate humano novo, específico para uma única execução. | Timeout, lock, schema, tenant, autorização ou ledger fora do contrato. | Encerrar, preservar fatos históricos e usar somente compensação futura aprovada. |

Os gates das fases 1 a 4 não são próximos gates e não existem como autorização
vigente. A revisão conjunta da fase 0 foi concluída; o único próximo gate
humano é a decisão nominal de merge do PR #403.

## Critérios de aceite antes de qualquer fase executável futura

| Critério | Evidência exigida | Resultado de falha |
| --- | --- | --- |
| Fonte de catálogo | Pino, árvore, contagem top-level e digest reproduzidos. | Não decidir nem executar. |
| Captura PROD | Modo `0600`, hash externo, recibo terminal, forma e determinismo completos. | Manter lacuna PROD. |
| Identidade | Atestação humana externa, específica do ambiente, distinta do digest de alvo. | Não materializar epoch. |
| Coortes sem match | Evidência adicional sanitizada aceita por gate humano posterior. | Não reclassificar coortes. |
| Ledgers | Prova documental de preservação, sem mutação retroativa. | Interromper a fase. |
| Compensação | Plano verificável que não imite backfill nem reescreva fatos históricos. | Não iniciar cutover. |

## Rollback e compensação

Nesta missão, rollback é somente abandonar o candidato documental local. Não
há compensação de banco porque nenhuma escrita ocorre. Em qualquer fase futura,
o primeiro rollback é interromper antes do efeito e conservar os registros
originais. Se algum efeito futuro exigir compensação, ela precisa ser definida
em autorização e contrato próprios, preservar ambos os ledgers e jamais
fabricar uma aplicação histórica por inserção, atualização, delete ou
reordenação.

## Próximo gate único

Estado vigente após a rodada corretiva do PR #403: OpenCode e QWEN concluíram o APTO conjunto sobre estes bytes, e o commit e o push corretivos foram publicados no PR #403. O MERGE permanece retido até frase nominal de Raniel, e qualquer fase executável exige gate humano próprio.
