# Kit de conferência do ledger de PROD — 26/09/2026

Arquivos usados na sessão operacional de 26/09 para decidir, com prova, quais migrations
já estavam aplicadas em PROD e criar o ledger `public.schema_migrations`. Registro da sessão:
[`docs/sprints/2026-09-26-prod-sessao-a-ledger-e-deploy.md`](../../sprints/2026-09-26-prod-sessao-a-ledger-e-deploy.md).
Serve também para provar que o DEV recriado ficou igual ao PROD **no catálogo**
(tabelas, colunas, índices, funções, policies, grants). As checagens não provam
dados: os dados de referência de migrations só de dados ou mistas (por exemplo
`0009`, `0012` e `0014`) precisam de conferência própria antes de copiar o ledger.

| Arquivo | O que é | Efeito no banco |
|---|---|---|
| `prova_objetos.sql` | 243 checagens de catálogo para as 79 migrations de `a5244ca` (tabelas, colunas, índices, constraints, funções por trecho distintivo, policies, grants). Uma linha por checagem: `migration, check_id, kind, ok, detail`. | Só leitura (`BEGIN TRANSACTION READ ONLY … ROLLBACK`); não lê linhas de tabela da aplicação. |
| `prova_objetos_notes.md` | O que cada migration faz, quais checagens discriminam e o resultado da validação offline. | — |
| `prova_prod_resultado_20260926.csv` | Resultado de `prova_objetos.sql` em PROD em 26/09 (referência para comparar com o DEV). | — |
| `native_ledger.sql` | Lista `version, name` do ledger nativo do Supabase (e-mails de `created_by` mascarados) e o estado do ledger público. | Só leitura. |
| `ledger_bootstrap_prod_20260926.sql` | SQL **executado em PROD** em 2026-09-26 20:11:54 UTC que criou o ledger com as 69 linhas nominais. Guarda de segurança: aborta se o ledger já existir ou se `rls_auto_enable()` for diferente do medido em PROD. | Escrita — **não reexecutar em PROD**. |
| `ledger_estado_final_ro.sql` | Leitura do estado final do ledger (dono, RLS/FORCE, ACL, colunas, contagens, md5 do conteúdo). | Só leitura. |
| `agent_configs_fingerprint.sql` | md5 de dono, RLS/FORCE, ACL da tabela e das colunas, policies (roles e expressões), constraints e triggers de `agent_configs`. Em PROD: `702ca5fe4df1772d21c6755d47c55915` antes e depois da S2. | Só leitura. |

## Como foi validado

- As 243 checagens foram testadas numa réplica PostgreSQL 17.5 (PGlite, sem rede) com
  três cortes: todas as 77 migrations ativas (todas verdadeiras), só `0001`–`0017` (nenhuma
  checagem de migration datada verdadeira) e o corte da V1 `20260810_042300` (nada de 22/08 em
  diante verdadeiro), além de "tira uma de cada vez" (69 réplicas) para achar checagens fracas.
- Checagens fracas conhecidas estão marcadas no `detail` ("partial"/"weak"). Migrations só de
  dados não têm prova de objeto (`kind = data_only`).
- Migrations criadas depois de `a5244ca` (ex.: `20260926_191500_agent_public_profile.sql`) não
  estão cobertas: acrescente checagens próprias antes de usar o kit em outro SHA.

## Uso

Rodar com `psql -X -v ON_ERROR_STOP=1 --csv -f prova_objetos.sql` numa conexão que nunca exponha
a URL (na VPS, o padrão da sessão foi o `pg_service.conf` efêmero gerado por
`/usr/local/libexec/pastorai-backup/prepare-database-service.py`). Comparar a saída com
`prova_prod_resultado_20260926.csv`.
