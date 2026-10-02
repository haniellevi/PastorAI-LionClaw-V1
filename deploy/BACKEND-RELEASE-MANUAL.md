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
o conjunto exato de migrations ativas do candidato, usando a seleção do
`backend/scripts/migrate.py`, além das colunas V2b/V3 e do contrato de
RLS/ACL/policies da ativação V3 na forma catalogada pelo PostgreSQL 17.
Migration no banco sem arquivo ativo no candidato também aborta. Não há
override automático: uma exceção exige decisão nominal registrada, análise de
compatibilidade e mudança revisada do procedimento antes de outro disparo.
O ledger nominal não prova o conteúdo aplicado, reconciliação de dados,
gates por igreja nem autorização de envio.

**Fechar `ALLOW_REAL_SENDS` não é uma pausa segura de fila.** O cron cancela
como `cancelado/gate_fechado` somente as pendências de `notification_outbox`
que alcançar; a manutenção geral percorre até 20 itens por igreja e ciclo de
dispatch, inclusive itens com `due_at` futuro. Quando o gate V3 fecha, há
também varredura de até 100 notificações V3 por igreja e ciclo. O ciclo do
cron tem padrão de 300 segundos, sujeito à configuração viva. Esses números
são tetos, não garantia de drenagem: o dispatch também tem limite global por
ciclo e pode não alcançar todas as igrejas. Cancelamento é terminal e não se
desfaz ao reabrir (`notification_outbox.py:982-1040`, `:1472-1527`,
`:2696-2746`; `cron_worker.py:349-367`; `config.py:264`).

| Finalidade em `notification_outbox` | Gate que fecha | Alcance por ciclo, por igreja | Destino do remanescente ao reabrir |
| --- | --- | --- | --- |
| `agenda_reminder` | `ALLOW_REAL_SENDS`, piloto ou agenda | Até 20 na manutenção geral | Pode enviar só se inscrição, evento e destinatário ainda forem válidos e a ocorrência ainda não tiver passado; senão fica obsoleto. |
| `agenda_evt7` | `ALLOW_REAL_SENDS`, piloto ou agenda | Até 20 na manutenção geral | Um item ainda sem tentativa só pode iniciar transporte até 10 minutos após a primeira janela elegível; depois expira ou fica obsoleto. |
| `consolidation_connection_open` | `ALLOW_REAL_SENDS`, piloto ou gate V3 | Até 20 na manutenção geral, mais até 100 na varredura V3 | Se o agendador observou o fechamento, fonte anterior à nova época V3 não volta ao agendador; pendência antiga é cercada como obsoleta ou cancelada. |
| `consolidation_connection_deadline` | `ALLOW_REAL_SENDS`, piloto ou gate V3 | Até 20 na manutenção geral, mais até 100 na varredura V3 | Sob a mesma observação, vale o reset de época e o prazo rígido de 24 horas da ocorrência. |
| `consolidation_fonovisita` | `ALLOW_REAL_SENDS`, piloto ou gate V3 | Até 20 na manutenção geral, mais até 100 na varredura V3 | Sob a mesma observação, valem o reset de época e o prazo rígido de 24 horas; não há replay normal. |
| `cell_report_reminder` | `ALLOW_REAL_SENDS`, piloto ou gate V1a | Até 20 na manutenção geral | Se não foi cancelado, pode enviar após reabrir enquanto reunião, líder e janela ainda forem válidos. |

O agendador V3 grava `gate_open=false` somente quando observa o gate fechado
com sucesso. Após observar a reabertura, grava `activated_at` novo:
consolidações e tarefas criadas antes dessa época não voltam ao agendamento
(`notification_outbox.py:2633-2688`, `:2883`, `:2513-2521`, `:2999-3028`,
`:3333-3340`; `consolidation_whatsapp.py:93`). Se o agendador não observar o
fechamento, a época anterior permanece e pendências V3 podem voltar a ficar
elegíveis. Reconstruir avisos V3 pré-janela pelo agendador normal não funciona
quando houve reset de época. Qualquer correção desses casos
exige plano próprio, SQL versionado e revisado, verificação posterior e
autorização de banco/envio separadas; este workflow não executa essa correção.
O `agenda_evt7` tem prazo de dez minutos após a primeira janela elegível
(`notification_outbox.py:129-148`) e V3 expira em 24 horas
(`notification_outbox.py:171-186`).

A tabela legada `CellReportReminder` **não tem despachante ativo** neste
backend: `dispatch_cell_report_reminders` delega ao outbox. Sua varredura de
pendentes ocorre em lotes de até 100 por igreja e ciclo somente quando o gate
específico V1a está fechado; `ALLOW_REAL_SENDS=false` sozinho não dispara
essa varredura (`cell_report_reminders.py:420-463,1494-1511,1536-1553,1640`).
Antes de fechar e antes de reabrir, inventariar por finalidade, estado e
origem com consultas read-only aprovadas. Não inferir que fila vazia significa
ausência de consolidações pré-época. O plano humano deve tratar separadamente
itens cancelados, pendentes, obsoletos e fontes V3 que deixaram de ser
agendáveis, com revisão contra duplicação. Se a perda ou mistura de estados
for inaceitável, **não execute este workflow**: modo de pausa sem
terminalização ou outra contenção exige desenho, teste e revisão próprios.

Decisão de projeto ainda aberta para Raniel: criar um modo de pausa que
preserve a fila, com código e testes próprios, ou redesenhar o deploy para
manter envio aberto com contenção equivalente durante build/restart. A segunda
opção exige remover as travas atuais e provar a segurança dos envios durante
build e restart; este workflow não a suporta. Nenhuma das duas opções é
autorizada por este documento.

Sequência obrigatória para um release futuro, sempre com autorizações próprias:

1. Obter autorização nominal de Raniel para o fechamento e registrar o
   operador responsável. A reabertura exige nova decisão nominal de Raniel;
   registrar horário de início e duração máxima numérica, em minutos, além do
   plano de aviso ou tratamento das pendências canceladas e remanescentes.
   Sob gate read-only próprio, comparar o ledger de PROD com as migrations
   ativas do SHA, inclusive
   as antigas `0001` a `0017`, **antes** de iniciar a janela; divergência impede o
   fechamento dos envios. Conferir o estado vivo dos quatro serviços e dos
   gates. Em 27/09, PROD tinha `ALLOW_REAL_SENDS=true` para o piloto Filadélfia;
   esse registro histórico precisa ser reconfirmado no momento do release.
2. Com autorização específica para mudar o gate, fechar `ALLOW_REAL_SENDS` e
   qualquer outro gate aberto, atualizar os quatro serviços e comprovar que o
   Compose resolvido e os processos ativos têm os quatro valores fechados.
   Enquanto `ALLOW_REAL_SENDS=false`, a Filadélfia não envia mensagens reais;
   registrar a interrupção e os efeitos por finalidade da tabela acima. Após o
   cron executar, exigir consulta read-only aprovada, posterior ao fechamento,
   que comprove `consolidation_whatsapp_activation.gate_open=false` para cada
   igreja V3 alvo. Registrar horário, igreja e resultado. Ausência de linha,
   erro do agendador ou marcador ainda aberto não comprovam fechamento:
   manter os gates fechados e escalar, sem avançar ao deploy ou à reabertura.
3. Concluir os gates de banco e dados do runbook único, obter autorização de
   deploy para o SHA exato e só então disparar o workflow manual. Falha no
   preflight interrompe o release antes de build ou restart.
4. Conferir saúde e comportamento do backend após o deploy. Reabrir envio e
   outros gates apenas com autorização separada para cada efeito, validar a
   retomada do piloto e registrar o resultado. Antes de reabrir, inventariar
   itens cancelados, pendentes e fontes V3 anteriores à nova época. Reabrir
   não recupera cancelados; somente algumas finalidades pendentes ainda podem
   enviar, conforme a tabela. Reconfirmar a prova read-only de
   `gate_open=false` por igreja V3 alvo; inventário de outbox não substitui
   esse marcador. Executar o plano de tratamento sob autorização
   própria. Se a reabertura não ocorrer, manter o release como incompleto e
   avisar o responsável: o piloto seguirá sem envios reais.

Se o deploy **falhar com o gate fechado**, registrar o ponto da falha e não
reabrir automaticamente. Falha antes do restart deixa o código anterior em
execução; falha depois aciona tentativa de rollback só de código. O rollback para os quatro serviços e executa o verificador do código anterior
com o manifesto de migrations daquele código, usando sua imagem construída e
entrypoint limitado a Python. O `start backend` temporário executa somente o
checker, sem aplicação ou workers; a retomada dos comandos normais depende de
saída zero comprovada. Checker ou manifesto
ausente, diferença de ledger em qualquer sentido ou schema incompatível
bloqueiam a retomada; `/health` e `/ready` não substituem esse preflight. Em ambos os casos,
conferir processos e inventariar cancelados, pendentes e fontes V3 pré-época
antes de decidir qualquer reabertura. Se o rollback ou inventário falhar,
manter envio fechado, registrar a janela ultrapassada e escalar para decisão
nominal de Raniel sobre correção adiante revisada ou outra contenção. Nunca
reconstruir avisos nem reabrir envio como parte automática deste script.

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
recusa checker anterior ausente ou manifesto anterior inválido antes de copiar
a configuração privada ou chamar Docker. Depois confere os gates de efeitos externos no Compose resolvido do candidato
e do release anterior, antes de build ou `up`, e nos quatro contêineres ativos;
depois executa os checkers anterior e candidato no backend ativo, cada um com
o manifesto selecionado por sua própria árvore, em transações somente leitura.
Ambos precisam passar antes de construir ou substituir os serviços; o rollback
repete o checker anterior em sua própria imagem antes de retomar a aplicação.
Um release legado sem checker exige um plano de recuperação revisado antes da
janela, sem copiar o checker candidato para a árvore anterior.
Migration ativa ausente do ledger, migration no banco sem
arquivo ativo no candidato, coluna ou tabela V2b/V3 ausente, RLS/ACL ou policy
de tenant V3 incompleta, erro de banco ou ausência do contêiner fazem
o comando sair com erro **antes de build ou restart**. Antes do preflight e
depois de cada restart, ele também exige em todos os quatro processos
`ALLOW_REAL_SENDS=false`, `ASAAS_BILLING_ENABLED=false`,
`BREVO_SEND_MODE=off` e `BROADCAST_ASYNC_ENABLED=false`; ausência ou outro
valor aborta sem imprimir a configuração. Depois ele constrói a imagem candidata,
cria `backend`, `queue-worker`, `cron-worker` e `broadcast-worker` parados,
inspeciona os quatro gates em cada contêiner e somente depois executa `start`
com espera de saúde no Compose, confere `/health` e `/ready` no loopback e só então aponta
`/opt/pastorai-current` para o novo release.

Se restart ou health falhar, o script para os quatro serviços, pré-valida o
Compose anterior, reconstrói sua imagem e executa o preflight daquele código.
Só depois cria contêineres parados com `up --no-start --no-deps`, inspeciona seus gates e inicia os quatro serviços.
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
ou restart. Diferença em qualquer direção do ledger ou schema incompleto
retorna código não zero; uma base descartável com todas as entradas nominais e
schema completo retorna zero. O dry-run não prova schema de PROD nem concede
autorização operacional.

## Evidência read-only obrigatória, A/B/C/H e P2-2/12

Somente Raniel executa estas consultas em PROD, sob gate read-only nominal.
Nenhuma evidência de CI ou deste teste local prova o estado de PROD. O operador
identifica ambiente, UTC, SHA candidato e anterior, identidade de banco e role,
e mantém conexão e credenciais exclusivamente em seu canal privado. Os arquivos
SQL abaixo são a consulta verbatim versionada; não adaptar cláusulas na janela.

Antes da janela, Raniel define e aprova `target_igrejas`: UUIDs distintos de
todas as igrejas com V3 habilitada ou marcador/pendência/fonte V3 anterior,
conferidos contra a configuração efetiva dos quatro processos e o cadastro
privado. União das listas atuais e anteriores, incluindo alvos removidos durante
a janela. Uma lista vazia não prova ausência de V3: PARE e obtenha plano revisado.
O agente nunca escolhe alvos. Registrar o conjunto aprovado em evidência sem PII;
o inventário não descobre automaticamente igrejas fora desse conjunto.

A role `inventory_role` é uma role existente, previamente revisada, NOLOGIN,
NOSUPERUSER e BYPASSRLS, com SELECT nas cinco tabelas de inventário e no ledger,
sem INSERT/UPDATE/DELETE/TRUNCATE. O script não cria role, não concede privilégios
nem desabilita RLS. BYPASSRLS é exigido explicitamente para inventário agregado
completo: role `authenticated` sem tenant/JWT pode esconder linhas e é recusada.
Se essa role não existir, PARE; provisionamento tem gate próprio. Os SELECTs
mostram role efetiva, flags RLS, owner e identidade. A conexão deve permitir
`SET LOCAL ROLE` somente sob a autorização read-only do operador.

Com conexão privada já configurada pelo operador, sem DSN em argumentos:

```bash
psql -X -v ON_ERROR_STOP=1 -v inventory_role="$ROLE_REVISADA" \
  -f deploy/backend-release-ledger.sql
psql -X -v ON_ERROR_STOP=1 -v inventory_role="$ROLE_REVISADA" \
  -v target_igrejas="$ALVOS_V3_APROVADOS" -v require_closed=false \
  -f deploy/backend-release-inventory.sql
```

O primeiro arquivo lista nomes e contagens, inclusive cada prefixo 0001 a 0017;
comparar com o conjunto ativo exato selecionado por `migration_files` no SHA.
Contagem ou presença nominal não prova conteúdo aplicado. O segundo inventaria
outbox por finalidade/estado/origem, legado V1a e fontes V3 por estado e época,
sem IDs de pessoas, títulos, mensagens ou contatos. Erro, timeout, role insegura,
alvos vazios/duplicados ou marcador ausente/época nula retornam não zero: PARE.
A ausência não é convertida em marcador fechado, nem em autorização para criá-lo.

Após fechar e antes de reabrir, repetir o mesmo inventário com
`-v require_closed=true`, conservando o conjunto aprovado. Só `gate_open=false`
com época conhecida para cada alvo satisfaz a consulta. Guardar os três snapshots
(antes do fechamento, depois da observação e imediatamente antes da reabertura)
e comparar cancelados, pendentes, obsoletos e fontes anteriores. Nunca deduzir
que outbox vazia significa ausência de fontes antigas. Cancelados são terminais;
tratamento ou reconstrução precisa de plano próprio revisado e gate nominal.

Para C, registrar início do fechamento, intervalo efetivo `cron_tick_seconds`,
ID do contêiner cron e prazo máximo numérico. Janela proposta: 900 segundos,
consulta a cada 30 segundos, sem prorrogação automática. Se intervalo efetivo ou
ciclo em andamento não permitir comprovação dentro de 900 segundos, PARE antes
da janela e obtenha duração revisada. O padrão 300 segundos não é prova viva.
Sob gate do operador, este comando lê somente o intervalo efetivo:

```bash
docker compose exec -T cron-worker python -c \
  'from app.config import get_settings; print(get_settings().cron_tick_seconds)'
docker compose ps -q cron-worker
```

Exigir ciclo iniciado após o fechamento, concluído, sem erro da etapa
`Consolidation notification scheduling failed`, e prova por alvo da observação.
Raniel confere os logs privadamente e devolve apenas horários, contêiner, contagem
de ciclos e erros; não encaminha logs brutos. Heartbeat saudável ou `Cron tick
done` geral não prova sucesso V3: a exceção V3 é capturada sem impedir o tick.
A transição documentada de marcador aberto no snapshot anterior para fechado
no posterior prova a observação por alvo. O schema atual não registra horário
próprio de observação do fechamento; se o marcador já estava fechado e não houver
outra prova revisada da etapa por alvo, PARE por evidência insuficiente. Esperar
900 segundos ou encontrar `false` antigo não supre essa lacuna. Ao vencer o
prazo, manter gates fechados, registrar interrupção e escalar a Raniel.

## Configuração e retenção, P2-6/9/10/14

No Environment protegido, configurar sob gate próprio
`BACKEND_DEPLOY_ALLOWED_ACTORS` (logins exatos separados por espaços) e
`BACKEND_DEPLOY_SAFE_BASE_SHA` (SHA completo do primeiro commit revisado que
contém esta camada de segurança). Ausência ou má formação recusa empacotamento.
Ator original e ator de rerun precisam pertencer à allowlist. O candidato deve
ser descendente desse piso e ancestral da main; o piso e o candidato devem
conter `BACKEND_RELEASE_SAFETY_VERSION=2`. A variável não pode apontar à base
antiga. Isso não concede autorização de dispatch ou substitui revisão do SHA.

Tarball do runner é removido mesmo com falha posterior; tarball remoto tem trap
EXIT no comando de extração/release. Candidato existente é recusado. O script
recusa alias/symlink de candidato e configuração candidata preexistente; limpa
sua cópia privada após contenção confirmada e preserva a configuração do ativo.
INT/TERM durante o restart passam pela contenção e pelo rollback, preservando
o código de saída do sinal. Se a parada dos serviços falhar, a configuração
candidata permanece restrita para recuperação humana; não removê-la enquanto
os processos puderem estar ativos. Sinal posterior à promoção do symlink
preserva o release já verificado e sua configuração. Em sucesso,
a configuração do novo ativo e a do anterior necessário ao rollback permanecem
restritas no host. Nenhum conteúdo privado é impresso. SIGKILL, crash de host ou
falha de transporte antes da sessão SSH não garantem traps: o operador deve
remover o tarball temporário e cópias de candidatos rejeitados sob gate próprio,
conferindo o symlink ativo antes de qualquer remoção. Não apagar volumes.

Deploy e rollback validam Compose antes de `up --no-start --no-deps` e inspecionam
contêineres parados antes de `start`; conferem novamente os quatro processos
após início. Rollback incompatível ou sem checker/manifesto para os serviços e
exige correção adiante revisada. Nenhum caminho reabre gate, desfaz migration ou
reconstrói avisos automaticamente.


## Compose suportado e preflight futuro

O piso suportado deste procedimento é **Docker Compose 5.0.0**, com versão
numérica estável e comando `timeout` do GNU coreutils disponível no host.
Esse piso não afirma qual foi a primeira versão histórica das opções.
A [fonte oficial da tag v5.0.0](https://github.com/docker/compose/blob/v5.0.0/cmd/compose/start.go#L44-L46)
declara `start --wait` e `--wait-timeout`; a
[referência oficial do comando](https://docs.docker.com/reference/cli/docker/compose/start/)
descreve essas opções. Um cliente local recente não prova compatibilidade do
host, engine, banco ou recuperação.

Somente em uma **janela futura nominalmente autorizada**, o operador deverá
conferir versão e as duas opções antes de parar candidato ou serviços:

```bash
docker compose version --short
docker compose start --help | grep -E -- '(^|[[:space:]])--wait([[:space:]]|$)'
docker compose start --help | grep -E -- '(^|[[:space:]])--wait-timeout([[:space:]]|$)'
command -v timeout
timeout --signal=TERM --kill-after=5s 1s true
```

Qualquer erro, versão inferior a 5.0.0, versão não numérica estável ou opção
ausente ou probe de timeout com status diferente de zero bloqueia a janela.
O probe executa somente true, sem Docker ou acesso ao ambiente, e valida
as opções reais --signal=TERM e --kill-after=5s com duração de 1s.
Presença do executável sozinha não prova suporte. A espera real do checker
permanece em 180s, com kill-after de 5s.
O script faz essas validações antes de copiar a
configuração, construir ou interromper serviços; cada pipeline acima deve
ter status conferido pelo operador, sem inferir sucesso da última linha.
Esta seção não concede autorização para executar esses comandos em ambiente.

## Transporte do checker e recuperação humana, P2-5

Após conter o candidato, o rollback seleciona o manifesto
`EXPECTED_MIGRATIONS` pelo `backend/scripts/migrate.py` da release anterior
e constrói sua imagem. Um override JSON temporário, restrito e sem credenciais,
substitui somente o backend: entrypoint Python, comando vazio, healthcheck
desativado e política `restart: no`. Valida o Compose resolvido e cria esse
backend com `up --no-start --no-build --no-deps --pull never --force-recreate`.
Inspeciona seus gates ainda parado e copia o checker da árvore anterior por
`docker cp`, sem usar o arquivo candidato.

Com os mesmos arquivos Compose, `start backend` inicia exclusivamente esse
checker. `timeout --signal=TERM --kill-after=5s 180s docker wait` limita a
espera pelo código de saída. Falha de criação, inspeção, cópia, início,
espera, timeout ou status diferente de zero bloqueia a aplicação anterior e
aciona a parada dos quatro serviços. Encerrar a espera não encerra o checker:
a parada explícita é a contenção necessária. Após status zero, os quatro
contêineres são recriados parados com os comandos originais, inspecionados,
iniciados com `start --wait --wait-timeout 180` e verificados novamente.
O código de saída original do release permanece, inclusive INT=130 e TERM=143.
O override temporário é removido pelo trap; não há rollback de schema.

O procedimento humano abaixo é material para revisão da janela futura,
condicionado a autorização nominal própria de Raniel para ambiente, SHA e
recuperação. Sua publicação não autoriza operação nem fecha P2-5 operacional.

1. Registrar ambiente, horário, SHA candidato/anterior, symlink ativo, etapa
   da falha e status, usando apenas evidência sanitizada. Manter os gates
   fechados e não reutilizar automaticamente um comando de início.
2. Sob o gate de contenção da janela, confirmar que os quatro serviços e o
   checker estão parados. Se qualquer parada falhar, preservar configuração
   restrita e artefatos necessários, registrar a contenção incompleta e
   escalar a Raniel. Não apagar arquivos enquanto processos puderem usá-los.
3. Conferir privadamente qual release fornece imagem, checker e manifesto.
   Recusar ausência, diferença de ledger ou schema incompatível; submeter
   correção adiante revisada, com gate de banco separado se necessário.
   Não contornar o checker por saúde HTTP nem desfazer migrations neste fluxo.
4. Retomar código somente por procedimento revisado que repita preflight,
   gates do Compose e contêiner parado, checker anterior com espera limitada
   e saída zero, recriação dos comandos normais e verificação dos quatro
   processos e saúde. Um backend residual dedicado ao checker precisa ser
   recriado, pois seu comando temporário não serve para retomar a aplicação.
5. Conferir symlink e processos antes da limpeza autorizada de tarball,
   override órfão e configuração de candidato rejeitado. SIGKILL/crash não
   garante traps; preservar configuração do ativo e do anterior e volumes.
   Inventariar cancelados, pendentes e fontes V3 pré-época conforme as seções
   anteriores. Reabertura, reconstrução de avisos e envio exigem gates próprios.
# Exceção restrita para manutenção da API legada

O perfil de [manutenção da API](BACKEND-MAINTENANCE-RELEASE.md) permite o backport
de desempenho compatível com o banco legado observado em 02/10/2026. Ele tem
manifestos, checker e recuperação próprios, preserva os workers e não utiliza
este workflow de release integral. Não remove os requisitos abaixo nem autoriza
migrations, ativação V1a/V2b/V3 ou substituição completa da stack.
