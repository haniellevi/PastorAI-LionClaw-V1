# V1 — gate de hardening do ledger de migrations

> Atualização de 2026-08-28: este documento preserva a operação histórica de
> `harden-ledger` para um ledger já existente. A implementação de
> `bootstrap-ledger`, desenvolvida e comprovada offline sobre a base
> `b43ad92028374fa6763ef10f5eb7a379afd3e7a2`, foi integrada pela PR #323. Ela
> cria somente um ledger vazio e não está autorizada em DEV ou PROD.

## Objetivo e limite

`public.schema_migrations` é o ledger histórico usado pelo executor de arquivo
único. Em ambientes antigos ele pode ter a estrutura correta, mas ainda estar
sem RLS, policy restritiva e ACLs compatíveis. Nesse estado, o executor recusa
qualquer migration de propósito para não transformar um histórico divergente em
uma escrita insegura.

O subcomando abaixo é o único hardening previsto para esse caso:

```bash
cd backend
# O cofre/secret manager injeta a URL; nunca a coloque em argv, log ou conversa.
: "${M06_MIGRATION_DATABASE_URL:?injete a URL aprovada no ambiente do processo}"
python scripts/apply_migrations.py harden-ledger --confirm HARDEN_LEDGER
```

Ele não cria a tabela, não insere, remove ou reordena nomes no ledger, não toca
`supabase_migrations.schema_migrations` e não executa SQL de migration. É um
hardening de plano de controle, não um atalho para aplicar pendências.

## Bootstrap de ledger ausente, integrado e comprovado somente offline

`bootstrap-ledger` é uma operação distinta. Ela exige PostgreSQL 17,
`current_user=session_user`, confirmação literal antes da conexão e o destino
somente em `M06_MIGRATION_DATABASE_URL`:

```bash
cd backend
: "${M06_MIGRATION_DATABASE_URL:?injete a URL aprovada no ambiente do processo}"
python scripts/apply_migrations.py bootstrap-ledger \
  --confirm BOOTSTRAP_LEDGER
```

O comando cria numa única transação `SERIALIZABLE` apenas
`public.schema_migrations` vazio, no contrato final owner-only: colunas, chave
primária e defaults exatos, RLS habilitada, uma policy deny e revokes explícitos
de tabela e coluna para `PUBLIC`, `anon`, `authenticated`, `service_role` e,
quando existir, `agent_runtime`. Ele recusa PostgreSQL fora da versão 17,
executor público, `CREATE` alcançável no schema, default privileges perigosas,
membership que alcance o owner, objeto ou tipo homônimo, drift de estrutura,
índice, ACL, policy, trigger, rule, herança ou partição. Qualquer falha reverte
toda a criação. Reaplicar o contrato exato e vazio encerra sem mutação.

O bootstrap não descobre migrations locais, não lê, copia ou altera
`supabase_migrations.schema_migrations`, não faz backfill ou reconciliação e não
aplica nem registra migration. O ledger vazio não libera o runner: `status` e
`apply` falham fechados até uma reconciliação histórica humana produzir um
prefixo íntegro do catálogo com, no máximo, uma migration pendente.

A implementação offline, ainda não aplicada, sobre a base
`b43ad92028374fa6763ef10f5eb7a379afd3e7a2`, passou em 42/42 testes unitários,
87/87 em PostgreSQL 17-alpine descartável em duas execuções independentes e
87/87 em Supabase PG17 17.6.1.159 descartável em duas execuções independentes.
A revisão de segurança resultou em `GO`. A suíte RLS completa, em execução
serial limpa no PostgreSQL 17 descartável, passou em 326/326, com 3803
deselecionados e 2 warnings preexistentes, em 162.77s. A suíte offline
integral foi interrompida após 5 min sem saída ou progresso; o resultado é
`INCONCLUSIVO`, não verde nem falha e não foi reclassificado. Os workflows
Backend Tests da PR #323 e do pós-merge concluíram com `SUCCESS`. O merge
`3a5789c784017ab15a43e28c4270d25af8618359` gerou Preview e Production
automáticos do frontend na Vercel; essa metadata não prova backend, banco ou
runtime. Não houve deploy manual ou do backend, acesso aos bancos DEV ou PROD,
bootstrap, migration, credencial, restart ou alteração de flag em ambiente
compartilhado.

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

## Registro histórico dos gates V1

Os itens abaixo preservam a sequência que valia para o hardening V1. Eles não
autorizam execução atual e não substituem o estado vivo ou o gate vigente.

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

## Gate vigente

Sobre a base auditada `cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`, esta
candidata adiciona somente offline um pacote deny-state versionado e um
verificador stdlib separado do runner, conforme
[`2026-08-28-migration-history-reconciliation-contract.md`](../decisions/2026-08-28-migration-history-reconciliation-contract.md).
O estado é `PACOTE E VERIFICADOR CANDIDATOS / SOMENTE OFFLINE / DECISÕES
HUMANAS PENDENTES / NÃO APLICADO`. O verificador não acessa banco, rede,
ambiente ou variáveis de ambiente, não executa SQL, DML ou escrita e não
infere migration aplicada. Os ledgers permanecem independentes e todo sucesso
estrutural conserva `OPERATIONAL_AUTHORIZATION=BLOCKED`.

A candidata passou `98/98` testes do verificador e `26/26` testes documentais.
O runner preservado passou `42/42` testes offline; `45` integrações foram
puladas por ausência deliberada de banco descartável.

O próximo gate é revisar as evidências focais e os pareceres independentes e,
se todos permanecerem verdes, integrar a PR. Até um gate nominal posterior,
não executar `bootstrap-ledger`,
`harden-ledger`, `status` ou `apply` em DEV ou PROD.

## Evidência local

O comportamento foi exercitado em PostgreSQL 17 descartável com histórico fora
de ordem, RLS ausente, grants de tabela e coluna para papéis públicos, policy
inesperada, perda potencial de privilégio de `service_role` e memberships
alcançáveis por `SET ROLE`. Casos divergentes abortam e preservam o estado
anterior; o caso aprovado mantém o executor de arquivo único funcional sem
reconciliar o histórico.
