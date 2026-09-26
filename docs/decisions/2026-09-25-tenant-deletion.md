# Exclusão de tenant e reset administrativo

## Decisão

A exclusão de uma igreja ocorre em duas fases. A primeira é uma transação SQL
única: trava a igreja, valida o grafo, registra no `platform_audit_log` cada
tarefa externa e elimina os dados locais. A segunda começa somente após o
commit e executa cada tarefa separadamente. A auditoria registra conclusão,
falha recuperável ou rejeição definitiva do alvo.

O manifesto fica no plano de plataforma e não possui FK para a igreja. Repetir
`DELETE /admin/igrejas/{id}` após a igreja já estar ausente recompõe apenas as
tarefas pendentes e tenta novamente. Antes de cada efeito externo, a tarefa
reserva sua linha no audit e confirma que nenhum vínculo sobrevivente passou
a usar o mesmo Clerk ID, instance, assinatura ou caminho de Storage.
O subcomando `drain-external` recupera esses manifestos depois do commit local;
ele não cria efeito em dry-run. O esgotamento das tarefas retentáveis exige
`pendentes=0`; rejeições terminais continuam visíveis e exigem tratamento
separado.

O claim durável é feito por linha de tarefa do audit existente, sem nova
migration. Sua transação curta confirma a reserva antes do HTTP, sem manter
lock global durante a chamada; o resultado posterior persiste com token de
fence. O lease permite retomada, mas não impede reassociação por writer não
cooperante nem garante exatamente uma chamada remota após crash.

## Dados locais e preservação do master

Um `AppUser` incluído em `platform_admins` permanece para o console master,
com `igreja_id`, `pessoa_id` e `celula_pendente_id` nulos. Seus papéis, Pessoa
e vínculos tenant são removidos. O login de tenant e as dependências tenant
respondem 403 para essa conta; `/admin/login` e `/admin/me` continuam baseados
na allowlist de plataforma.

Antes do detach, a transação remove as relações com chaves compostas de
`app_users`: `user_roles`, `consent_records`, `messages`, `conversations` e as
referências em Pessoa. `consentimento_finalidade_evento` e
`pessoa_arquivamento_evento` não recebem `DELETE` direto: são removidos pelo
cascade de Pessoa, que preserva seus guards append-only. Os demais dados
tenant seguem o cascade de `igrejas`. Tokens de reset dos Clerk IDs removidos
também são apagados; tokens do master preservado permanecem.

As relações E4B podem estar ausentes enquanto a migration correspondente está
pausada. A exclusão enumera toda tabela ordinária ou particionada
`public.e4b_*`: quando houver `igreja_id`, conta somente a igreja solicitada;
uma tabela desconhecida sem essa coluna e com linhas bloqueia por segurança.
Se houver relação relevante povoada, a exclusão falha antes de DML, commit ou
chamada externa. Não há tentativa de contornar guards imutáveis nem de excluir
retenções E4B nesta fatia.

## Recursos externos

Clerk de contas não protegidas, instance de `whatsapp_connections` e assinatura
Asaas com `externalReference` PastorAI entram no manifesto a partir de vínculos
locais da igreja. Para Storage, o manifesto abrange o prefixo inteiro `UUID/`
em mídia e logos pela identidade da igreja, inclusive órfãos sem `Message` ou
outro ponteiro local, páginas e subdiretórios. Cada caminho enumerado é validado
contra o prefixo do tenant antes de qualquer remoção.
IDs de recurso e caminhos são validados antes de formar uma URL privilegiada.
Asaas confirma propriedade e o mesmo ID remoto antes do cancelamento; Evolution
só conclui com a resposta de sucesso documentada; objetos ausentes são
idempotentes. Um caminho de Storage reatribuído bloqueia a tarefa mesmo que a
igreja recriada tenha o mesmo UUID.

## Reset por CLI

`backend/scripts/reset_tudo.py` nunca aceita URL no argv. Ela lê
`RESET_DATABASE_URL` ou solicita a URL por `getpass`, aceita somente PostgreSQL
com host único verificável e bloqueia opções ou variáveis libpq que possam
redirecionar o destino, incluindo `PGPORT` e `PGOPTIONS`. A URL, usuário e senha
não aparecem no help nem nos erros. Em cada transação de contagem, execução ou
tarefa do drain, fixa `search_path` local em `public`; essa repetição cobre o
commit individual de cada efeito externo. Dry-run é o padrão e mostra apenas
host e contagens. Ele exige principal efetivo `rolsuper` ou `rolbypassrls`
antes de contar ou apagar, pois uma role tenant poderia enxergar subconjunto e
produzir falso sucesso.

Antes de exibir as contagens, o reset enumera todas as tabelas ordinárias ou
particionadas `public.e4b_*` e, quando existir,
`consentimento_finalidade_evento`. Tabela ausente ou vazia permite seguir.
Qualquer contagem positiva interrompe o dry-run e a execução com
`BLOCKED_E4B_POPULATED`, lista somente `tabela=contagem`, retorna código `3` e
faz rollback sem criar auditoria ou apagar dado. O bloqueio do ledger vale
somente para o reset total: a exclusão individual continua usando o cascade de
Pessoa, que é o caminho permitido pelo guard append-only. Na execução, depois
de bloquear `igrejas`, ele bloqueia essas tabelas e repete a contagem antes do
primeiro DML; assim uma linha inserida depois do dry-run não pode passar para a
exclusão.

Com `--execute`, o operador informa `--backup-path`, atesta
`--backup-confirmed` e digita exatamente o host depois de ver as contagens. O
arquivo precisa ser regular, não vazio e não symlink; a CLI abre somente os
primeiros 512 bytes de modo não bloqueante para reconhecer `PGDMP` ou o
cabeçalho de dump PostgreSQL em texto, sem registrar conteúdo. O reset adquire
`LOCK TABLE igrejas IN SHARE ROW EXCLUSIVE MODE`, bloqueia criação concorrente,
apaga todas as igrejas em uma transação e deixa as limpezas externas pendentes
no audit, com o host confirmado. `planos`, `schema_migrations`, masters e
auditoria de plataforma não são apagados. O `pending_tasks` do resultado soma
manifestos novos e pendências antigas do audit. Depois do commit, o reset
retorna `4` se houver alguma pendência externa e `0` se não houver.

Depois desse commit, `drain-external` reabre o audit sob a mesma credencial,
mostra `pendentes` e `rejeitadas` em dry-run e exige `--execute` mais a mesma
confirmação de host para chamar provedores. Cada resultado também registra o
host no audit. Retorna `4` quando há pendência, inclusive se também houver
rejeição; sem pendência, retorna `5` para rejeições terminais ou `0` sem
exceções. A rejeição não deve ser repetida indefinidamente.

## Limites e próximo gate

Esta decisão descreve somente candidato local. Nenhum banco compartilhado,
backup, provedor ou exclusão real foi acionado. Uma falha após um commit pode
ter resultado indeterminado; o operador consulta o audit antes de repetir.
Para `55P03`, `40001` ou outro erro transacional, faz rollback da operação
inteira, consulta o audit e reinicia a transação completa com todas as
revalidações. Não tenta um `UPDATE` isolado para recuperar a concorrência.

O processo simples do MVP, por `backend/scripts/migrate.py`, é a fonte aprovada
para a migration desta fatia. O próximo gate humano único é Raniel autorizar o
merge por número da PR B. A execução real continua fora deste escopo.
