# Migrations — processo simples do MVP

Processo definido em `docs/ops/MVP-PLANO-SIMPLIFICACAO.md` (§3.4). O processo
anterior (catálogo, head, atestação, executor catalog-bound) está pausado e
preservado na branch `archive/governanca-2026-09`.

## Criar

1. Crie `backend/migrations/AAAAMMDD_HHMMSS_slug.sql`. O nome define a ordem.
2. Tabela nova de tenant: coluna `igreja_id`, `ENABLE`/`FORCE ROW LEVEL SECURITY`
   e policies por `igreja_id`, no mesmo padrão das tabelas existentes.
3. Escreva o rollback como comentário no fim do arquivo.
4. Nunca edite uma migration que já foi aplicada em DEV ou PROD; crie outra.
5. Não use `BEGIN`/`COMMIT` no arquivo; o aplicador abre a transação.

## Aplicar

```bash
cd backend
MIGRATION_DATABASE_URL="<url do banco>" python scripts/migrate.py status
MIGRATION_DATABASE_URL="<url do banco>" python scripts/migrate.py apply <arquivo>.sql --yes
```

- Aplica um arquivo por vez e registra o nome em `public.schema_migrations`
  na mesma transação.
- `--no-transaction` existe só para `CREATE INDEX CONCURRENTLY`.
- **DEV primeiro.** Depois PROD, com **backup antes** (runbook de produção),
  anotando no registro da fatia (`docs/sprints/`) o que foi aplicado e quando.
- A URL nunca vai para argumento de linha de comando, log ou commit.

## Histórico

`0001`–`0017` são as migrations originais. `private_runtime/` pertence à
fundação D2A, que está pausada; não aplique esses arquivos no MVP.
