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
release estão aprovados. O preflight exige no ledger `public.schema_migrations`
o nome de cada migration ativa do candidato, usando a seleção do
`backend/scripts/migrate.py`, além das colunas V2b/V3 e do contrato de
RLS/ACL/policies da ativação V3 na forma catalogada pelo PostgreSQL 17.
O ledger nominal não prova o conteúdo aplicado, reconciliação de dados,
gates por igreja nem autorização de envio.

Sequência obrigatória para um release futuro, sempre com autorizações próprias:

1. Conferir o estado vivo dos quatro serviços e dos gates. Em 27/09, PROD tinha
   `ALLOW_REAL_SENDS=true` para o piloto Filadélfia; esse registro histórico
   precisa ser reconfirmado no momento do release.
2. Com autorização específica para mudar o gate, fechar `ALLOW_REAL_SENDS` e
   qualquer outro gate aberto, atualizar os quatro serviços e comprovar que o
   Compose resolvido e os processos ativos têm os quatro valores fechados.
   Enquanto `ALLOW_REAL_SENDS=false`, a Filadélfia não envia mensagens reais;
   registrar a janela de interrupção do piloto.
3. Concluir os gates de banco e dados do runbook único, obter autorização de
   deploy para o SHA exato e só então disparar o workflow manual. Falha no
   preflight interrompe o release antes de build ou restart.
4. Conferir saúde e comportamento do backend após o deploy. Reabrir envio e
   outros gates apenas com autorização separada para cada efeito, validar a
   retomada do piloto e registrar o resultado. Se a reabertura não ocorrer,
   manter o release como incompleto e avisar o responsável: o piloto seguirá
   sem envios reais.

Configure o GitHub Environment protegido `backend-production` apenas sob a
autorização separada de release. Seus secrets são `BACKEND_DEPLOY_HOST`,
`BACKEND_DEPLOY_USER`, `BACKEND_DEPLOY_SSH_KEY` e
`BACKEND_DEPLOY_KNOWN_HOSTS`. O último contém a chave SSH do host conferida
fora do workflow; a Action não descobre nem aceita uma chave nova por conta
própria. Valores, URLs, chaves, credenciais do banco e acesso à VPS ficam
fora do Git. A conta de deploy já precisa ter acesso ao Docker e aos
diretórios de release existentes e a Python 3 no host para inspecionar o JSON
resolvido do Compose sem imprimi-lo. A configuração privada do release ativo é
copiada para o candidato sem ser impressa.

Com o gate de PROD separado e concedido, dispare **Backend release (manual)**
na `main` e informe o `release_sha` completo, de 40 caracteres. A Action
recusa SHA fora da `main`, empacota o commit exato, transfere por SSH com
chave de host fixada e chama `deploy/backend-release.sh` na VPS. O script
confere primeiro os gates de efeitos externos no Compose resolvido do candidato
e do release anterior, antes de build ou `up`, e nos quatro contêineres ativos;
depois executa `deploy/check_backend_schema.py` no backend, em transação
somente leitura. Migration ativa ausente do ledger, coluna ou tabela V2b/V3
ausente, RLS/ACL
ou policy de tenant V3 incompleta, erro de banco ou ausência do contêiner fazem
o comando sair com erro **antes de build ou restart**. Antes do preflight e
depois de cada restart, ele também exige em todos os quatro processos
`ALLOW_REAL_SENDS=false`, `ASAAS_BILLING_ENABLED=false`,
`BREVO_SEND_MODE=off` e `BROADCAST_ASYNC_ENABLED=false`; ausência ou outro
valor aborta sem imprimir a configuração. Depois ele constrói a imagem candidata,
recria `backend`, `queue-worker`, `cron-worker` e `broadcast-worker`, aguarda
saúde no Compose, confere `/health` e `/ready` no loopback e só então aponta
`/opt/pastorai-current` para o novo release.

Se restart ou health falhar, o script pré-valida novamente o Compose anterior
e tenta reconstruir e recriar seus quatro serviços somente com gates fechados.
Falha também no rollback deixa o workflow vermelho e
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

Esse modo usa o mesmo verificador de schema e ledger, sem Docker, SSH, build
ou restart. Migration ausente ou schema incompleto retorna código não zero;
uma base descartável com todas as entradas nominais e schema completo retorna
zero. O dry-run não prova schema de PROD nem concede autorização operacional.
