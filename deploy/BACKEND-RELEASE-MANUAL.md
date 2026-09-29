# Deploy manual do backend

Este mecanismo publica apenas o backend. O workflow
`.github/workflows/backend-deploy-manual.yml` tem somente
`workflow_dispatch`: um merge nunca o inicia. Este documento não autoriza
disparo, banco, VPS, flags ou release em PROD. O runbook único de release será
uma missão separada.

Antes de qualquer disparo futuro, o responsável pelo release precisa obter
autorização para o SHA exato da `main` e comprovar, por gates próprios, que as
migrations V2b e V3 foram aplicadas no banco correto, que o passo 0 da V2b e a
reconciliação LID da V3 foram resolvidos, e que backup e rollback daquele
release estão aprovados. O preflight deste script prova somente a presença de
colunas e tabelas exigidas e RLS/ACL da ativação V3. Não prova ledger de
migrations, reconciliação de dados, flags nem permissão de envio.

Configure o GitHub Environment protegido `backend-production` apenas sob a
autorização separada de release. Seus secrets são `BACKEND_DEPLOY_HOST`,
`BACKEND_DEPLOY_USER`, `BACKEND_DEPLOY_SSH_KEY` e
`BACKEND_DEPLOY_KNOWN_HOSTS`. O último contém a chave SSH do host conferida
fora do workflow; a Action não descobre nem aceita uma chave nova por conta
própria. Valores, URLs, chaves, credenciais do banco e acesso à VPS ficam
fora do Git. A conta de deploy já precisa ter acesso ao Docker e aos
diretórios de release existentes. A configuração privada do release ativo é
copiada para o candidato sem ser impressa.

Com o gate de PROD separado e concedido, dispare **Backend release (manual)**
na `main` e informe o `release_sha` completo, de 40 caracteres. A Action
recusa SHA fora da `main`, empacota o commit exato, transfere por SSH com
chave de host fixada e chama `deploy/backend-release.sh` na VPS. O script
executa primeiro `deploy/check_backend_schema.py` dentro do contêiner backend
ativo, em transação somente leitura. Coluna ou tabela V2b/V3 ausente, RLS/ACL
incompleta, erro de banco ou ausência do contêiner fazem o comando sair com
erro **antes de build ou restart**. Depois ele constrói a imagem candidata,
recria `backend`, `queue-worker`, `cron-worker` e `broadcast-worker`, aguarda
saúde no Compose, confere `/health` e `/ready` no loopback e só então aponta
`/opt/pastorai-current` para o novo release.

Se restart ou health falhar, o script reconstrói e recria os quatro serviços
do release anterior. Falha também no rollback deixa o workflow vermelho e
exige intervenção humana. **Rollback volta somente código e contêineres; ele
nunca desfaz migration.** Se o código antigo não rodar com o schema novo,
mantenha os gates de envio fechados, contenha os processos afetados, preserve
schema e evidências e prepare uma correção adiante revisada ou compensação de
banco autorizada separadamente. Não faça rollback destrutivo improvisado de
schema.

Para dry-run exclusivamente local, use um PostgreSQL 17 descartável e o Python
do projeto:

```bash
DATABASE_URL='<URL_LOCAL_PG17_DESCARTAVEL>' \
  BACKEND_RELEASE_PYTHON='<PYTHON_COM_SQLALCHEMY>' \
  bash deploy/backend-release.sh --dry-run
```

Esse modo usa o mesmo verificador de schema e não chama Docker, SSH, build ou
restart. Schema incompleto deve retornar código não zero e nomear a coluna
`public` ausente; schema sintético completo retorna zero. O dry-run não prova
schema de PROD nem concede autorização operacional.
