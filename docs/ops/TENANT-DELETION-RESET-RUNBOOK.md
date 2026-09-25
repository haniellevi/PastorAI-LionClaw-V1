# Runbook de exclusão de tenant e reset

## Finalidade e fronteira

Este runbook orienta uma execução futura por operador autorizado. Não autoriza
conexão, backup, exclusão, provedor, ambiente compartilhado ou produção. A
prova local só demonstra o comportamento do candidato no SHA revisado.

O reset exige uma credencial PostgreSQL cujo `current_user` seja `rolsuper` ou
`rolbypassrls`. A CLI falha fechada antes de contar quando a role é tenant, pois
contagens filtradas por RLS não provam que todos os tenants foram vistos.

## Exclusão de uma igreja

1. O console chama `DELETE /admin/igrejas/{id}` como platform admin.
2. A transação bloqueia a igreja, verifica E4B, grava tarefas externas no
   `platform_audit_log`, remove dados locais e confirma o commit.
3. Somente depois do commit cada tarefa externa pode ser tentada. Ela confere
   novamente que o recurso não pertence a um vínculo sobrevivente.
4. Se uma tarefa falhar, o audit conserva o manifesto. Repetir o mesmo DELETE
   para a igreja ausente retoma somente tarefas pendentes.

Uma igreja com relação E4B existente e não vazia é bloqueada antes de qualquer
DML. A operação não remove guards, ledger ou retenções para contornar esse
estado.

## Reset completo

Use sempre uma URL PostgreSQL explícita com host único. A CLI rejeita drivers
não suportados, múltiplos hosts, opções libpq de redirecionamento e ambientes
com `PGHOSTADDR`, `PGOPTIONS`, `PGPORT`, `PGSERVICE` ou `PGSERVICEFILE`
presentes. Ela fixa `search_path` local em `public` nas transações de contagem
e execução e nunca mostra URL, usuário ou senha em mensagens de erro.

Primeiro, faça somente a revisão sem DML:

```bash
python backend/scripts/reset_tudo.py --database-url '<URL PostgreSQL explícita>'
```

Registre o host e as contagens mostradas. Dry-run não cria auditoria, não chama
provedores e encerra com rollback da sessão de leitura.

Antes de mostrar as contagens, a CLI enumera todas as tabelas ordinárias ou
particionadas `public.e4b_*`. Se alguma tiver linhas, ela mostra apenas
`BLOCKED_E4B_POPULATED` e `tabela=contagem`, encerra com código `3` e não cria
auditoria nem remove dados. Tabela ausente ou vazia permite o dry-run. A saída
não contém PII.

A execução futura exige um `pg_dump` já concluído. Passe o caminho do arquivo
regular não vazio e a atestação explícita. O comando não abre nem valida o
conteúdo do backup.

```bash
python backend/scripts/reset_tudo.py \
  --database-url '<URL PostgreSQL explícita>' \
  --execute \
  --backup-path '<caminho do pg_dump>' \
  --backup-confirmed
```

Depois das contagens, digite exatamente o host exibido. EOF, host divergente,
backup ausente, role sem privilégio ou erro de transação abortam a operação. Não
existe opção de confirmação automática. A transação adquire
`LOCK TABLE igrejas IN SHARE ROW EXCLUSIVE MODE`, impedindo a criação concorrente
de igreja até o commit ou rollback.

Depois da confirmação interativa, a execução bloqueia as tabelas E4B
enumeradas e repete suas contagens antes do primeiro DML. Se surgir qualquer
linha desde o dry-run, retorna `BLOCKED_E4B_POPULATED` com código `3` e desfaz a
transação inteira.

O reset preserva schema, `schema_migrations`, `planos`, `platform_admins` e
auditoria de plataforma. Masters sobreviventes ficam sem tenant e só acessam o
console de plataforma. Ele grava tarefas externas pendentes, mas não chama
Clerk, Evolution, Asaas ou Storage dentro da transação.

## Falha, retomada e rollback

Antes do commit, a falha reverte toda a exclusão local, inclusive manifestos
de tarefa. Após uma falha que possa ocorrer durante ou depois de commit, trate
o resultado como indeterminado e consulte `platform_audit_log` antes de repetir.

Uma restauração a partir de `pg_dump` é um procedimento separado, com seu gate
operacional. Tarefas externas pendentes são retomadas pelo DELETE idempotente
da igreja ausente, depois de confirmar os gates próprios de Clerk, Evolution,
Asaas e Storage. Não suponha que teste verde, migration ou esta documentação
habilita um efeito externo.

## Próximo gate humano

Raniel autorizar o merge por número da PR B. A execução real continua fora deste
escopo.
