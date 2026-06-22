# Migrations

SQL aplicado **manualmente** no Supabase (não há runner automático). A ordem de
aplicação é a **ordem alfabética dos nomes de arquivo** — por isso o nome importa.

## Convenção de nomes

- **Histórico (`0001`–`0017`):** numeração sequencial, **congelada**. Não renomear,
  não reutilizar números. Já aplicadas em produção.
- **Novas migrations:** usar **timestamp UTC** — `AAAAMMDD_HHMMSS_slug.sql`
  (ex.: `20260622_143000_add_coluna_x.sql`).

### Por que timestamp em vez de `0018`, `0019`…

Branches paralelas escolhiam o "próximo número" ao mesmo tempo e **colidiam**
(dois `0008`, dois `0012`…), exigindo renumeração manual no merge. O timestamp é
único por construção: cada branch gera um nome diferente, sem coordenação.

Lexicograficamente, `20260622_…` ordena **depois** de `0001`–`0017`, então a ordem
de aplicação fica: todo o histórico numerado e, em seguida, as novas em ordem
cronológica. Sem buraco, sem colisão.

## Como criar uma nova migration

```bash
# a partir de backend/
python scripts/new_migration.py "add coluna x em pessoas"
# cria backend/migrations/<timestamp>_add_coluna_x_em_pessoas.sql
```

Ou crie o arquivo à mão seguindo o formato `AAAAMMDD_HHMMSS_slug.sql`.

## Como aplicar

Aplicar **em ordem de nome de arquivo**, no SQL editor do Supabase (ou via MCP),
as que ainda não foram aplicadas. Como não há controle automático, registre o que
já subiu (ex.: na memória do projeto / nas notas de deploy).

## Regra do `ALTER TYPE ... ADD VALUE`

No PostgreSQL, `ALTER TYPE <enum> ADD VALUE` **não pode** ser referenciado na mesma
transação em que é adicionado (e em PG<12 nem roda dentro de `BEGIN/COMMIT`). Por
isso essas migrations **não abrem transação** (cada statement auto-commita) e o
*seed*/backfill que **usa** o novo valor vai num arquivo separado, posterior.
Veja `0008_add_operador_role.sql` e `0017_app_user_status_revogado.sql` como
referência.
