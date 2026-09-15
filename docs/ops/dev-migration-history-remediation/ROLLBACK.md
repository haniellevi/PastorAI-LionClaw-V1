# Rollback F1

## Escopo

F1 cria apenas este diretório documental e um teste local PostgreSQL 17
descartável. Nenhuma migration nova foi criada. Nenhuma sessão DEV, VPS ou
PROD foi aberta por agente. `public.schema_migrations` e
`supabase_migrations.schema_migrations` não recebem `INSERT`, `UPDATE`,
`DELETE`, backfill, reordenação ou cópia.

## Reversão por ambiente

| Ambiente | Estado produzido | Rollback permitido |
| --- | --- | --- |
| Local source-only | arquivos sob este diretório | descartar somente o patch F1 após decisão humana; não tocar a ficha |
| PostgreSQL 17 descartável | fixture sintética em container sem rede | parada do container identificado pelo runner, que usa `--rm` |
| DEV futuro | uma transação `REPEATABLE READ READ ONLY` | `ROLLBACK;` no fim normal ou após qualquer erro |
| VPS e PROD | nenhum | nenhuma ação |

Não há rollback de ledger porque F1 não tem escrita de ledger. Se uma execução
humana falhar antes de `ROLLBACK_COMPLETED_F1`, Raniel executa apenas
`ROLLBACK;`, preserva a saída sanitizada parcial e encerra. Não reaplica,
reordena, corrige ACL, cria epoch ou tenta compensação.

Qualquer correção futura de schema ou histórico precisa de missão e gate novos,
incluindo revisão humana, replay PostgreSQL 17, contrato tenant/RLS/ACL e uma
compensação forward-only quando aplicável.
