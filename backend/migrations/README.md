# Migrations — processo simples do MVP

Processo definido em `docs/ops/MVP-PLANO-SIMPLIFICACAO.md` (§3.4). O processo
anterior (catálogo, head, atestação, executor catalog-bound) está pausado e
preservado na branch `archive/governanca-2026-09`.

## Criar

1. Crie `backend/migrations/AAAAMMDD_HHMMSS_slug.sql`. O nome define a ordem.
2. Tabela nova de tenant: coluna `igreja_id`, `ENABLE`/`FORCE ROW LEVEL SECURITY`
   e policies por `igreja_id`, no mesmo padrão das tabelas existentes.
3. Escreva o rollback como comentário no fim do arquivo.
4. Nunca edite uma migration que já foi aplicada em PROD; crie outra. No
   banco local, basta `./dev.sh reset`.
5. O aplicador controla a transação. Um `begin;`/`commit;` que envolve o
   arquivo inteiro é removido automaticamente (é o padrão histórico).
   Qualquer outro controle de transação no meio do arquivo é recusado.

## Aplicar

```bash
cd backend
MIGRATION_DATABASE_URL="<url do banco>" python scripts/migrate.py status
MIGRATION_DATABASE_URL="<url do banco>" python scripts/migrate.py apply <arquivo>.sql --yes
```

- Aplica um arquivo por vez e registra o nome em `public.schema_migrations`
  na mesma transação.
- `--no-transaction` existe só para `CREATE INDEX CONCURRENTLY`.
- **Local primeiro.** `./dev.sh reset` recria o banco local do zero com todas
  as migrations e os dados de teste; `./dev.sh up` aplica as pendentes
  (`docs/ops/AMBIENTE-LOCAL.md`). PROD só no release, com **backup antes**
  (runbook de produção), anotando no registro da fatia (`docs/sprints/`) o que
  foi aplicado e quando.
- A URL nunca vai para argumento de linha de comando, log ou commit.

## Pausadas

Arquivos com `-- OPERATIONAL_AUTHORIZATION=BLOCKED` (E4B, laboratório de
evidência de consentimento, sessão dedicada D2A e consentimento por finalidade)
ficam fora de `status` e `apply` até a Fase 5.

## Histórico

`0001`–`0017` são as migrations originais. `private_runtime/` pertence à
fundação D2A, que está pausada; não aplique esses arquivos no MVP.

## V1a: relatório de célula por texto (candidata)

`20260927_190000_cell_report_whatsapp_v1a.sql` depende da migration S3
`20260927_170000_whatsapp_privilege_actions.sql`. Acrescenta estado privado
de rascunho, preferências/lembretes e reservas de custo, com RLS, e amplia
o catálogo S3 somente para o relatório agregado. O worker recebe apenas SELECT/INSERT/UPDATE nas cinco tabelas novas; reaplicar revoga DELETE residual. Um índice parcial único impede duas propostas V1a executadas para a mesma igreja/reunião/ação. Propostas canceladas/expiradas não impedem a correção. A execução usa
`lock_timeout = '2s'`; se o lock não vier, parar e tentar em outra janela.

A verificação local usa PostgreSQL 17 descartável e aplica o SQL duas vezes.
Isso não prova aplicação em DEV/PROD. Preservar os SQLs congelados das PRs
426/428, reconciliar a base e revisar novamente antes de qualquer aplicação.
A flag `CELL_REPORT_ENABLED_IGREJA_IDS` fica vazia e
`CELL_REPORT_APPROVED_RELEASE_ID=None`; migration e deploy não ativam envios.
Rollback comentado no próprio SQL exige tratar pendências antes de remover
o schema; relatórios já confirmados continuam sendo registros do domínio.
