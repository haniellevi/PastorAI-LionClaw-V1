# Migrations

Este projeto usa migrations SQL imperativas e versionadas. Nenhuma migration é
aplicada automaticamente por merge, deploy ou inicialização do backend.

## Convenção de nomes

- Histórico `0001` a `0017`: numeração congelada, sem renomear ou reutilizar.
- Novas migrations: timestamp UTC no formato
  `AAAAMMDD_HHMMSS_slug.sql`.

Para criar o arquivo:

```bash
cd backend
python scripts/new_migration.py "add coluna x em pessoas"
```

O nome ordena o catálogo local, mas não prova que o arquivo foi aplicado em
qualquer ambiente. O histórico nativo do Supabase
`supabase_migrations.schema_migrations` e o ledger de controle do runner
`public.schema_migrations` são objetos diferentes e nunca são reconciliados por
inferência.

## Executor fail-closed

`scripts/apply_migrations.py` possui operações distintas:

- `list`: lista o catálogo local sem conexão;
- `status`: consulta somente um ledger público já seguro e exige prefixo íntegro
  com, no máximo, uma migration pendente;
- `harden-ledger`: endurece um ledger público histórico já existente, sem criar
  ou preencher entradas;
- `bootstrap-ledger`: cria somente o ledger público vazio no contrato
  owner-only final, sem ler ou copiar histórico;
- `apply`: aplica um único arquivo previamente aprovado, com basename, SHA-256
  e confirmação literal, somente quando o ledger já forma o prefixo seguro.

O destino é aceito exclusivamente pela variável de processo
`M06_MIGRATION_DATABASE_URL`. A CLI não aceita DSN em argumento e nunca deve
receber URL, senha, token ou host em conversa, documentação ou log.

O bootstrap exige PostgreSQL 17 e confirmação explícita:

```bash
cd backend
: "${M06_MIGRATION_DATABASE_URL:?injete a URL aprovada pelo canal secreto}"
python scripts/apply_migrations.py bootstrap-ledger \
  --confirm BOOTSTRAP_LEDGER
```

Esse comando não descobre o catálogo local, não consulta ou altera
`supabase_migrations`, não registra migrations e não autoriza `status` ou
`apply`. Em um ledger vazio com múltiplos arquivos locais, ambos continuam
bloqueados.

## Estado operacional atual

`bootstrap-ledger` foi integrado pela PR #323 e comprovado somente offline,
ainda não aplicado, sobre a base
`b43ad92028374fa6763ef10f5eb7a379afd3e7a2`: 42/42 testes unitários, 87/87 em
PostgreSQL 17-alpine descartável em duas execuções independentes e 87/87 em
Supabase PG17 17.6.1.159 descartável em duas execuções independentes, com
revisão de segurança `GO`. A suíte RLS completa, em execução serial limpa no
PostgreSQL 17 descartável, passou em 326/326, com 3803 deselecionados e 2
warnings preexistentes, em 162.77s. A suíte offline integral foi interrompida
após 5 min sem saída ou progresso; o resultado é `INCONCLUSIVO`, não verde nem
falha e não foi reclassificado. Os workflows Backend Tests da PR #323 e do
pós-merge concluíram com `SUCCESS`.

O merge `3a5789c784017ab15a43e28c4270d25af8618359` integrou o código em
`main`. A Vercel produziu Preview e Production automáticos do frontend; essa
metadata não prova deploy do backend, banco ou runtime.

Nenhuma execução ocorreu em DEV ou PROD. Não use `bootstrap-ledger`,
`harden-ledger`, `status`, `apply`, SQL Editor, `apply_migration`, `db push` ou
MCP para preencher, reaplicar ou reconciliar histórico em ambiente
compartilhado. O próximo gate é uma PR offline e versionada de reconciliação
histórica humana, sem DML e sem inferência.

## Transações especiais

Algumas migrations históricas com `ALTER TYPE ... ADD VALUE` possuem contrato
transacional próprio. O executor valida os bytes e recusa controles de
transação que possam quebrar a atomicidade. Não remova wrappers ou divida um
arquivo para fazê-lo passar; qualquer incompatibilidade exige revisão da
migration e um gate separado.
