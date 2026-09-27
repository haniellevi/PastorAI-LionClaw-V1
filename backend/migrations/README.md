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
- **DEV primeiro.** Depois PROD, com **backup antes** (runbook de produção),
  anotando no registro da fatia (`docs/sprints/`) o que foi aplicado e quando.
- A URL nunca vai para argumento de linha de comando, log ou commit.

## Pausadas

Arquivos com `-- OPERATIONAL_AUTHORIZATION=BLOCKED` (E4B e laboratório de
evidência de consentimento) ficam fora de `status` e `apply` até a Fase 5.

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

Observação Sarah registrada na branch V1b, mantendo PR430 `a8bf21d` congelado:
a guarda do índice compara texto de `pg_get_expr`. A representação depende da
versão PostgreSQL; divergência aborta com segurança, mas exige revisão e replay
antes de adotar outra versão. A prova atual cobre PostgreSQL17.

## V1b: áudio do relatório de célula (candidata)

`20260927_210000_cell_report_audio_v1b.sql` depende da V1a e acrescenta quatro
tabelas privadas: avisos de áudio, eventos de aceite/revogação, entradas de áudio
e reservas. Mantém RLS/FORCE RLS, policies de worker, FKs compostas e somente
SELECT/INSERT/UPDATE. Reaplicar revoga DELETE residual. O número de áudio é
único por igreja/reunião e limitado a três; reservas encerradas conservam esse
número. O custo é compartilhado com as quatro extrações textuais permitidas.

As referências vivas de pessoa/conversa/mensagem podem ser anuladas por
exclusão; a âncora imutável e a chave de storage sobrevivem para limpeza.
Âncora sem fonte viva não autoriza processamento. Purga continua com flags
fechadas. Antes de qualquer rollback destrutivo, concluir a remoção dos objetos
e registrar ausência de pendências, conforme comentário no SQL.

A migration usa `lock_timeout='2s'` e não altera os SQLs congelados 426/428/430.
Somente PostgreSQL17 descartável foi usado nesta missão. Aplicação compartilhada
e deploy mantêm gates próprios; `CELL_REPORT_AUDIO_ENABLED_IGREJA_IDS` vazia e
`CELL_REPORT_AUDIO_APPROVED_RELEASE_ID=None` ficam cumulativos a V1a/S3.
