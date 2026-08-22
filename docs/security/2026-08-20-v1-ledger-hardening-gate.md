# V1 — gate de hardening do ledger de migrations

## Objetivo e limite

`public.schema_migrations` é o ledger histórico usado pelo executor de arquivo
único. Em ambientes antigos ele pode ter a estrutura correta, mas ainda estar
sem RLS, policy restritiva e ACLs compatíveis. Nesse estado, o executor recusa
qualquer migration de propósito para não transformar um histórico divergente em
uma escrita insegura.

O subcomando abaixo é o único bootstrap previsto para esse caso:

```bash
cd backend
# O cofre/secret manager injeta a URL; nunca a coloque em argv, log ou conversa.
: "${M06_MIGRATION_DATABASE_URL:?injete a URL aprovada no ambiente do processo}"
python scripts/apply_migrations.py harden-ledger --confirm HARDEN_LEDGER
```

Ele não cria a tabela, não insere, remove ou reordena nomes no ledger, não toca
`supabase_migrations.schema_migrations` e não executa SQL de migration. É um
hardening de plano de controle, não um atalho para aplicar pendências.

## Contrato fail-closed

A operação usa uma única transação `SERIALIZABLE` e um lock exclusivo da tabela.
Antes de qualquer alteração, exige:

- tabela existente com as colunas exatas `name text not null` e
  `applied_at timestamptz not null default now()`, chave primária `name` e sem
  duplicidades;
- todos os nomes do ledger público presentes no catálogo versionado local;
- papéis `anon`, `authenticated` e `service_role` com as propriedades mínimas
  esperadas;
- somente um dos estados iniciais conhecidos: RLS desligado e nenhuma policy,
  ou o estado final já endurecido;
- preservação exata dos privilégios efetivos que `service_role` já possuía.

Na mesma transação ele habilita RLS, cria exclusivamente a policy restritiva
`migration_ledger_service_role_bypass_only`, revoga ACLs de tabela e coluna de
`PUBLIC`, `anon` e `authenticated`, e então revalida grants efetivos, caminhos
por `SET ROLE`/`ADMIN OPTION`, owner e `BYPASSRLS`. Qualquer divergência faz
rollback integral; o comando não tenta corrigir roles, owners, memberships ou
histórico.

O sucesso esperado é explícito: o ledger fica protegido, mas a quantidade e a
ordem de nomes registrados permanecem exatamente as mesmas.

## Preflight operacional obrigatório

Antes de executar em qualquer ambiente hospedado, registrar o alvo, SHA do
código, autorização e os resultados somente leitura de:

1. catálogo local e SHA-256 dos arquivos que serão considerados depois;
2. `public.schema_migrations` (colunas, chave, RLS, policies, ACLs, nomes e
   duplicidades);
3. `supabase_migrations.schema_migrations` (inventário independente, sem
   preencher o ledger público a partir dele);
4. roles, owners e memberships relevantes;
5. advisors de segurança/performance e backup/restauração exigidos pelo
   ambiente.

Não usar `supabase db push`, `apply_migration`, SQL Editor ou qualquer executor
genérico para preencher lacunas históricas. Um nome presente apenas no histórico
nativo do Supabase é evidência para reconciliação humana, não autorização para
reaplicar ou registrar uma migration.

## Próximos gates após sucesso em DEV

O hardening não libera aplicação genérica. Após preflight e smokes, cada
migration continua sendo um gate separado do executor de arquivo único. As duas
pendências V1 atuais são, nesta ordem:

1. `20260810_031050_explicit_deny_policies_for_closed_tables.sql`
   — SHA-256
   `1524fa0944dd3f4c259fa81f528570f8a4be5cff010515d4c44ac30a8df063c6`;
2. `20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade.sql`
   — SHA-256
   `31f1f26f62594e19d6bd1cee3b4e8a4665da8207188192764d09272d880367d1`.

Cada aplicação requer o nome, SHA e `--confirm APPLY`, e deve repetir ledger,
advisors, RLS/billing sandbox e smokes antes de avançar para o próximo ambiente.

## Evidência local

O comportamento foi exercitado em PostgreSQL 17 descartável com histórico fora
de ordem, RLS ausente, grants de tabela e coluna para papéis públicos, policy
inesperada, perda potencial de privilégio de `service_role` e memberships
alcançáveis por `SET ROLE`. Casos divergentes abortam e preservam o estado
anterior; o caso aprovado mantém o executor de arquivo único funcional sem
reconciliar o histórico.
