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
2. A transação bloqueia a igreja, enumera `public.e4b_*`, verifica E4B, grava tarefas externas no
   `platform_audit_log`, remove dados locais e confirma o commit.
3. Somente depois do commit cada tarefa externa pode ser tentada. Ela confere
   novamente que o recurso não pertence a um vínculo sobrevivente.
4. Se uma tarefa falhar, o audit conserva o manifesto. Repetir o mesmo DELETE
   para a igreja ausente retoma somente tarefas pendentes.

Para Storage, o alvo da limpeza é o namespace inteiro `UUID/` da igreja em
mídia e logos, inclusive objetos órfãos sem `Message`, páginas e subdiretórios.
Cada caminho enumerado deve permanecer no prefixo validado dessa igreja.
O claim de cada tarefa usa sua linha durável do audit, sem nova migration: a
reserva é confirmada em transação curta antes do HTTP, sem lock global durante
o provedor. O resultado é persistido depois com token de fence. Lease expirado
permite retomada, mas não impede reassociação feita por writer não cooperante
nem garante exatamente uma chamada remota se houver crash.

Uma igreja com relação E4B existente e não vazia é bloqueada antes de qualquer
DML. Relação com `igreja_id` é filtrada pela igreja solicitada; uma tabela
`e4b_*` desconhecida sem essa coluna e com linhas bloqueia a operação. A
operação não remove guards, ledger ou retenções para contornar esse estado.
O ledger `consentimento_finalidade_evento` não recebe DELETE direto: a exclusão
individual o remove pelo cascade de Pessoa, no caminho aceito pelo guard
append-only.

## Reset completo

Use sempre uma URL PostgreSQL explícita com host único. A CLI a recebe por
`RESET_DATABASE_URL` ou pelo prompt protegido de `getpass`, nunca por argv. Ela
rejeita drivers não suportados, múltiplos hosts, opções libpq de redirecionamento
e ambientes com `PGHOSTADDR`, `PGOPTIONS`, `PGPORT`, `PGSERVICE` ou
`PGSERVICEFILE` presentes. Ela fixa `search_path` local em `public` nas
transações de contagem, execução e em cada tarefa externa do drain, e nunca
mostra URL, usuário ou senha em mensagens de erro.

Primeiro, faça somente a revisão sem DML:

```bash
python backend/scripts/reset_tudo.py reset
```

Esse comando pede a URL sem eco. `RESET_DATABASE_URL` só pode ser injetada pelo
cofre ou pelo ambiente controlado do operador; não a escreva em linha de comando
ou histórico de shell.

Registre o host e as contagens mostradas. Dry-run não cria auditoria, não chama
provedores e encerra com rollback da sessão de leitura.

Antes de mostrar as contagens, a CLI enumera todas as tabelas ordinárias ou
particionadas `public.e4b_*` e, quando existir,
`public.consentimento_finalidade_evento`. Se alguma tiver linhas, ela mostra apenas
`BLOCKED_E4B_POPULATED` e `tabela=contagem`, encerra com código `3` e não cria
auditoria nem remove dados. Tabela ausente ou vazia permite o dry-run. A saída
não contém PII. O ledger bloqueia apenas o reset total: a exclusão individual
permanece no cascade de Pessoa permitido pelo guard append-only.

A execução futura exige um `pg_dump` já concluído. Passe o caminho do arquivo
regular, não vazio e não symlink, com a atestação explícita. A CLI abre apenas
os primeiros 512 bytes em modo não bloqueante para reconhecer `PGDMP` ou o
cabeçalho de dump PostgreSQL em texto; ela não registra o conteúdo.

```bash
python backend/scripts/reset_tudo.py reset \
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
enumeradas e o ledger quando existente, e repete suas contagens antes do
primeiro DML. Se surgir qualquer linha desde o dry-run, retorna
`BLOCKED_E4B_POPULATED` com código `3` e desfaz a transação inteira.

O reset preserva schema, `schema_migrations`, `planos`, `platform_admins` e
auditoria de plataforma. Masters sobreviventes ficam sem tenant e só acessam o
console de plataforma. Ele grava tarefas externas pendentes, mas não chama
Clerk, Evolution, Asaas ou Storage dentro da transação.
O `pending_tasks` do reset inclui manifestos novos e pendências antigas do
audit. Após o commit local, retorna código `4` se houver alguma pendência, ou
`0` se não houver. Código `4` não desfaz a exclusão local; consulte o audit
antes de qualquer retomada.

## Drain externo posterior ao commit

Depois de um reset confirmado, consulte o audit sem chamar provedor:

```bash
python backend/scripts/reset_tudo.py drain-external
```

Com pendências, a CLI informa as contagens e sai com código `4`, inclusive se
também houver rejeições. Sem pendências, sai com `5` quando houver rejeições
terminais e com `0` quando não houver nenhuma. Para tentar somente os manifestos
pendentes, depois de rever os
gates próprios de Clerk, Evolution, Asaas e Storage, use:

```bash
python backend/scripts/reset_tudo.py drain-external --execute
```

O drain pede o host exibido, recarrega o audit depois da confirmação e só então
chama os provedores. Cada tarefa fixa `search_path` em `public` antes de suas
consultas e grava o host confirmado no evento de resultado. Repita o dry-run
até `pendentes=0`; a repetição não recria manifesto nem refaz tarefa terminal.
Rejeições são exceções terminais visíveis e exigem tratamento separado, não
retentativa indefinida. Código `5` sinaliza essa situação ao operador.

## Falha, retomada e rollback

Antes do commit, a falha reverte toda a exclusão local, inclusive manifestos
de tarefa. Após uma falha que possa ocorrer durante ou depois de commit, trate
o resultado como indeterminado e consulte `platform_audit_log` antes de repetir.
Para `55P03`, `40001` ou outro erro transacional, faça rollback completo,
consulte o audit e repita a transação inteira com as mesmas revalidações. Não
recupere concorrência por `UPDATE` isolado.

Uma restauração a partir de `pg_dump` é um procedimento separado, com seu gate
operacional. Tarefas externas pendentes são retomadas pelo DELETE idempotente
da igreja ausente ou pelo `drain-external`, depois de confirmar os gates próprios
de Clerk, Evolution, Asaas e Storage. Não suponha que teste verde, migration ou
esta documentação habilita um efeito externo.

## Próximo gate humano

Raniel autorizar o merge por número da PR B. A execução real continua fora deste
escopo.
