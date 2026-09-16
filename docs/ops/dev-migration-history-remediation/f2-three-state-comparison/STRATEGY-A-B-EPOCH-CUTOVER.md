# Estratégias A/B e desenho documental de epoch/cutover

## Princípio de decisão

Um epoch é uma âncora de interpretação por ambiente, não uma declaração de
aplicação nem uma alteração retroativa do histórico. Por isso, cada ambiente
precisa de âncora própria, fonte própria e limites próprios. Os dois ledgers
existentes devem permanecer preservados, sem backfill, reordenação ou correção
silenciosa.

## Estratégias avaliadas

| Critério | A. Reconciliação documental do ambiente divergente | B. Controle limpo, se elegível |
| --- | --- | --- |
| Objeto | Exercita a divergência que precisa permanecer explícita em DEV e depois em PROD. | Exercita uma instalação separada e limpa. |
| Epoch | Um epoch DEV e um epoch PROD, cada qual ligado a sua própria âncora. | Pode ter epoch próprio, sem substituir os epochs dos ambientes divergentes. |
| Ledgers existentes | Preservados como observação histórica, sem backfill ou reordenação. | O DEV existente continua preservado; o controle não o reescreve. |
| Risco principal | Tratar presença como aplicação. Mitigação: classes inconclusivas e falha fechada. | Produzir conforto indevido por não representar o legado PROD. |
| Valor para PROD | Maior, mas depende da lacuna de identidade sanitizada das 32 entradas nativas. | Somente complementar, pois não reconcilia PROD. |

## Recomendação

Recomendo a estratégia A como desenho futuro. Ela preserva os dois ledgers e
força a distinção entre catálogo, observação DEV e observação PROD. A escolha
não materializa epoch, cutover ou executor. A estratégia B continua apenas um
controle limpo potencialmente elegível; ela não substitui reconciliação PROD e
não deve ser tratada como remediação do ambiente divergente.

## Fases documentais futuras

| Fase | Pré-condições e trust anchors | Classe fail-closed | Critério de aceite | Rollback ou compensação |
| --- | --- | --- | --- | --- |
| 0. Congelamento | SHA de fonte, recibos selados, declaração humana de ambiente e revisão independente | hash, modo, recibo, forma ou privacidade fora do contrato | Fontes independentes aceitas sem conteúdo bruto | descartar somente artefatos documentais não publicados |
| 1. Epoch DEV | Identidade humana atestada, catálogo autenticado, mapeamento conservador das posições divergentes | vínculo ausente, não-prefixo ou ambiguidades de chave | Epoch DEV descreve somente classes e preserva ambos os ledgers | nenhum ledger é revertido, porque nenhum ledger é alterado |
| 2. Lacuna PROD | Identidade sanitizada das 32 entradas nativas, âncora externa confiável e forma validada | identidade das entradas ausente, fonte duplicada fora do contrato ou âncora insuficiente | Epoch PROD separado, sem importar a ordem DEV | parar antes de qualquer efeito e manter a lacuna registrada |
| 3. Plano de cutover | Aprovação humana nominal, executor revisado, critérios operacionais e plano de compensação próprios | autorização, tenant, lock, timeout, schema ou ledger não comprovados | Plano verificável e reversível em escopo delimitado | compensação futura deve preservar fatos históricos e nunca simular backfill |

As fases têm controles separados por ambiente e não são autorizações vigentes.
Em especial, a fase PROD permanece bloqueada até existir identidade sanitizada
das `32` entradas, pois a coleta v2 não a forneceu. Nenhuma fase futura pode
usar um ensaio DEV como substituto dessa lacuna.

O único próximo gate deste candidato é parecer `APTO` conjunto de OpenCode e
CLAUDE sobre os mesmos bytes antes de commit, push ou publicação.
