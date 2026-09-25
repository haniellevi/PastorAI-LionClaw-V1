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
trava a relação local do recurso e confirma que nenhum vínculo sobrevivente
passou a usar o mesmo Clerk ID, instance, assinatura ou caminho de Storage.

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
pausada. Se alguma delas existir e contiver linha da igreja, a exclusão falha
antes de DML, commit ou chamada externa. Não há tentativa de contornar os
guards imutáveis nem de excluir retenções E4B nesta fatia.

## Recursos externos

Só entram no manifesto recursos ligados à igreja no banco local: Clerk de
contas não protegidas, instance de `whatsapp_connections`, assinatura Asaas
com `externalReference` PastorAI, logo e mídia sob o prefixo UUID da igreja.
IDs de recurso e caminhos são validados antes de formar uma URL privilegiada.
Asaas confirma propriedade e o mesmo ID remoto antes do cancelamento; Evolution
só conclui com a resposta de sucesso documentada; objetos ausentes são
idempotentes. Um caminho de Storage reatribuído bloqueia a tarefa mesmo que a
igreja recriada tenha o mesmo UUID.

## Reset por CLI

`backend/scripts/reset_tudo.py` recebe `--database-url` explícita, aceita
somente PostgreSQL com host único verificável e bloqueia opções ou variáveis
libpq que possam redirecionar o destino, incluindo `PGPORT` e `PGOPTIONS`.
Em cada transação de contagem ou execução, fixa `search_path` local em `public`.
Dry-run é o padrão e mostra apenas host e contagens. Ele exige principal efetivo
`rolsuper` ou `rolbypassrls`
antes de contar ou apagar, pois uma role tenant poderia enxergar subconjunto e
produzir falso sucesso.

Antes de exibir as contagens, o reset enumera todas as tabelas ordinárias ou
particionadas `public.e4b_*`. Tabela ausente ou vazia permite seguir. Qualquer
contagem positiva interrompe o dry-run e a execução com
`BLOCKED_E4B_POPULATED`, lista somente `tabela=contagem`, retorna código `3` e
faz rollback sem criar auditoria ou apagar dado. Na execução, depois de bloquear
`igrejas`, ele bloqueia essas tabelas e repete a contagem antes do primeiro DML;
assim uma linha inserida depois do dry-run não pode passar para a exclusão.

Com `--execute`, o operador informa `--backup-path`, atesta
`--backup-confirmed` e digita exatamente o host depois de ver as contagens.
O arquivo precisa ser regular e não vazio, mas nunca é aberto. O reset adquire
`LOCK TABLE igrejas IN SHARE ROW EXCLUSIVE MODE`, bloqueia criação concorrente,
apaga todas as igrejas em uma transação e deixa as limpezas externas pendentes
no audit. `planos`, `schema_migrations`, masters e auditoria de plataforma não
são apagados.

## Limites e próximo gate

Esta decisão descreve somente candidato local. Nenhum banco compartilhado,
backup, provedor ou exclusão real foi acionado. Uma falha após um commit pode
ter resultado indeterminado; o operador consulta o audit antes de repetir.

O processo simples do MVP, por `backend/scripts/migrate.py`, é a fonte aprovada
para a migration desta fatia. O próximo gate humano único é Raniel autorizar o
merge por número da PR B. A execução real continua fora deste escopo.
