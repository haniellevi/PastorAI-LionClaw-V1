# Pacote de decisão F1, estratégia A ou B

## Base decisória congelada

| Campo | Valor sanitizado |
| --- | --- |
| Evidência externa | SHA-256 `b1c3e1bda63b55e7c5496d318bcf039d9a4d130de60ced535d918be233313e1b`, modo `0600`, coleta `2026-09-15T11:18:39-03:00` |
| SQL F1 preservado | `8829decd0f0101329058ad07900ce7b7ca8b1c4fe5695f4e3cec05cff4bf288c` |
| Agregado F1 preservado | `956187b9711ea9d67e9f8fdf31c3980e3ebbf64da98401c275f1dc80d2a91a29` |
| Transação | `PG170006`, `REPEATABLE READ`, `read_only=on`, `row_security=off` |
| Coleta | `TARGET_DIGEST` presente, `EXPECTED_33`, `EXPECTED_6`, abortos F1 `0`, históricos `0/0`, nenhum record de domínio |
| Encerramento | Recibo externo declarado `ROLLBACK_COMPLETED_F1`; índice opaco confirma comando psql de rollback, sem transcrição copiada |
| Declaração humana separada | `DEV_DATA_DISPOSITION=NO_VALUE_NO_PII` |
| Referência local | Replay oficial e traço do harness em PG17.6 descartável, `77/77`, banco recriado via `postgres` antes do traço e contrato fresh validado |
| Comparação opaca | Anexo canônico `ad5e21e746967862555899a1c5c7c2d90ee6c020edbbab85edfcbac241644b57`, `1901` registros de referência, `2959` DEV, `1209` payloads iguais |

A declaração de disposição é uma afirmação humana recebida separadamente. Ela
não foi inferida da transcrição, do schema, da ausência de relações ou dos
ledgers. Sua presença não autoriza recriação, apagamento, mudança de ledger ou
qualquer outro efeito externo.

## Resultado da reauditoria estrutural

A matriz agora contém `13` efeitos físicos presentes, `17` parciais ou
conflitantes, `5` ausentes e `9` não decidíveis por schema. O replay local
reclassificou doze linhas cujo vínculo anterior dependia de contagem e nome,
mas não fechava por chave segura, hash ou flag contra a referência. A auditoria
dos 44 SQLs continua excluindo comentários, literais, FKs para relações
preexistentes e helpers `pg_temp`.

Em particular, a migration 5 tem exatamente três relações próprias na fonte,
mas suas três chaves relacionais não fecham contra DEV; a migration 30 possui
seis alvos relacionais e não usa `recovery` como schema, pois
`monthly_recovery` é apenas literal ou comentário; a migration 39 tem 13
constraints e 11 índices explícitos, com três índices adicionais de suporte a
constraints no coletor e helpers temporários excluídos. Essas correções não
convertem presença física em prova de aplicação ou em reconhecimento de
histórico.

O item 18 fica parcial: suas contagens fecham, mas `R1` não é `EQUAL` porque
uma chave do traço não aparece na referência. O índice opaco V3 também separa
`ACL_ONLY` quando toda diferença atribuível está somente em `acl_state` de
schema ou relation. Essa variação pode ser esperada entre execução local e
contrato de plataforma Supabase, não prova drift DEV isoladamente e permanece
parcial. Grants diretos, default ACL e grantee permanecem diferenças de
definição, nunca `ACL_ONLY`.

Nas posições divergentes 25 a 32, três itens fecham por referência e cinco
ficam parciais. O ledger público aplicado continua não-prefixo do catálogo, e
o anexo preserva as dependências de epoch/cutover sem alterar a ordem
registrada.

## Achados que limitam a decisão

- `agent_private`, `recovery` e `agent_runtime` estão ausentes na coleta
  sanitizada. Isso bloqueia qualquer pressuposto de runtime privado disponível.
- O schema público contém exatamente dois privilégios diretos opacos, `CREATE`
  e `USAGE`, classificados como `UNEXPECTED_CUSTOM_GRANTEE`. A hipótese
  provável é `pg_database_owner`, porém o estado permanece `UNRESOLVED`:
  nenhum nome ou OID de grantee foi desvendado, solicitado ou registrado.
- Uma investigação futura de `PREDEFINED_ROLE` com padrão `pg_%` é proposta
  apenas para F2 ou coleta PROD nominalmente autorizada. Ela não integra esta
  análise e não reduz o bloqueio ACL atual.
- Os dezessete itens parciais bloqueiam conclusão positiva para si mesmos; os nove
  `NOT_SCHEMA_DECIDABLE` preservam a incerteza sobre DML, seed, reconciliação
  ou no-op condicional. Nenhuma ausência de leitura de dados foi compensada por
  inferência.
- O runbook congelado SHA-256 `c4729a0e585408439313cda89011f22a04112877d4cf89361c3061a49226d58e`
  usa `\prompt`; conforme o cliente, isso pode ecoar o binding no scrollback
  visual. A execução F1 encerrada deixou arquivo sem binding, históricos `0/0`
  e limpeza de scrollback reportada, mas não reteve prova do buffer visual. Esta
  limitação não reabre nem repete F1. Qualquer F2 ou PROD futura exige canal de
  entrada sem eco, com o valor ausente de argv e de histórico, sob gate próprio.

## Comparação A/B

| Critério | A. Reconciliar DEV divergente | B. Recriar DEV limpo |
| --- | --- | --- |
| Objeto de ensaio | O ambiente com o mesmo tipo de drift que precisa ser tratado em PROD. | Uma instalação nova, sem reproduzir por si só a divergência legada. |
| Relação com a matriz | Trata 17 parciais, 5 ausências, 9 limites de DML e ACL opaca por classes explícitas. | Pode validar um catálogo limpo, mas não resolve as assinaturas já presentes, parciais ou ausentes no ambiente divergente. |
| Ledgers | Preserva ambos, sem backfill, reordenação ou alteração retroativa. | O DEV atual continua preservado; um ambiente novo não corrige seu histórico. |
| Risco principal | Legitimar drift se presença estrutural for tratada como aplicação. Mitigação: catálogo vinculado, classes explícitas e falha fechada. | Criar falso conforto por ensaiar instalação limpa sem representar o legado divergente que PROD também terá. |
| Condição atual | Elegível apenas para desenho documental futuro, sem banco nem aplicação. | Elegível somente por `NO_VALUE_NO_PII`; continua não autorizada. |
| Valor para PROD | Alto, pois exercita epoch e cutover do tipo de divergência que PROD exige. | Parcial, pois não ensaia reconciliação do legado PROD. |

## Decisão recomendada

Recomendo a estratégia A. Ela ensaia a divergência que também precisa ser
tratada em PROD e mantém os dois ledgers preservados, as classes da matriz
visíveis e os limites de DML explícitos. Esta recomendação não autoriza F2,
epoch, executor, migration, aplicação, coleta PROD ou mudança em DEV.

A estratégia B fica somente elegível pela declaração humana
`DEV_DATA_DISPOSITION=NO_VALUE_NO_PII`. Ela não está autorizada, não deve
destruir ou trocar DEV e não substitui o ensaio da estratégia A. Mesmo em uma
decisão futura, exigiria autorização destrutiva nominal, preservação do ambiente
existente, critérios de aceite e gate próprio.

## Próximo gate único

Os dois conselheiros conferem o candidato exato após esta correção, sem
execução de SQL ou acesso a ambiente. Até uma decisão conjunta posterior, este
pacote permanece análise documental e não autoriza banco, DEV, VPS, PROD,
recriação, migration, ledger, role lookup ou cutover.
