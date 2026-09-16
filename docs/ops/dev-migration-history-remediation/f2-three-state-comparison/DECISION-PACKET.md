# Pacote de decisão, F2 três estados

## Decisão recomendada

Recomendo manter a estratégia A como recomendação documental, com epochs
específicos por ambiente e preservação integral dos dois ledgers observados.
Ela é a única opção que enfrenta explicitamente a divergência DEV sem usar a
contagem de PROD como equivalência histórica. A estratégia B pode existir como
controle limpo se vier a ser elegível, mas não substitui a reconciliação PROD.

## Base de decisão

| Tema | Estado |
| --- | --- |
| Catálogo | `77` entradas source-only no SHA `f856f53f48e79a53609ff699d5603119f60202e0` |
| DEV | recibo selado, `33` entradas públicas e `6` nativas; captura anterior superseded rejeitada |
| PROD v2 | recibo aceito sob `DUPLICATED_IDENTICAL_CAPTURE_2X`; público ausente e nativo `32` |
| Mecanismos | divergentes: DEV observa público e nativo; PROD v2 observa somente o nativo |
| Posições F1 | `25` a `32` permanecem divergentes e bloqueiam leitura de prefixo |
| Lacuna crítica PROD | a identidade sanitizada das `32` entradas nativas não foi coletada |
| Autorização operacional | bloqueada; não há escrita, executor, migration ou cutover |

## Regras obrigatórias para desenho posterior

1. Catálogo, DEV e PROD permanecem três estados distintos. Nenhum é convertido
   em prova causal sobre os outros.
2. Cada epoch precisa de âncora específica do ambiente. O digest vincula uma
   coleta ao alvo conectado, enquanto a identidade DEV ou PROD depende de
   atestação humana e de âncora externa confiável.
3. Os dois ledgers são preservados. Backfill, reordenação e mutação retroativa
   não são mecanismos de reconciliação aceitos.
4. Falha de hash, modo, cópia, recibo, privacidade, fonte, identidade ou forma
   interrompe a respectiva fase antes de qualquer efeito.
5. A ausência de identidade das `32` entradas PROD é uma lacuna, não um convite
   a inferir aplicação, ordem ou causa.

## Limites e não autorizações

Este pacote não contém SQL, migration, comando de aplicação, coleta viva,
executor, backfill, mudança em ledger, conexão, credencial ou inferência causal.
O resultado dos testes locais prova apenas o parser e as fontes exercitadas. A
captura PROD v2 prova forma e cardinalidade, não identificação das entradas.

## Próximo gate único

Parecer `APTO` conjunto de OpenCode e CLAUDE sobre o candidato exato antes de
commit, push ou publicação. Até esse parecer, a recomendação A não autoriza
qualquer ação fora deste pacote documental.
