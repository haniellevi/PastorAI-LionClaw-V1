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
execução; falha depois aciona tentativa de rollback só de código. O rollback
**não executa `check_backend_schema.py` no código anterior**: `/health` e
`/ready` não provam compatibilidade com o schema novo. Em ambos os casos,
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
confere primeiro os gates de efeitos externos no Compose resolvido do candidato
e do release anterior, antes de build ou `up`, e nos quatro contêineres ativos;
depois executa `deploy/check_backend_schema.py` no backend, em transação
somente leitura. Migration ativa ausente do ledger, migration no banco sem
arquivo ativo no candidato, coluna ou tabela V2b/V3 ausente, RLS/ACL ou policy
de tenant V3 incompleta, erro de banco ou ausência do contêiner fazem
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
ou restart. Diferença em qualquer direção do ledger ou schema incompleto
retorna código não zero; uma base descartável com todas as entradas nominais e
schema completo retorna zero. O dry-run não prova schema de PROD nem concede
autorização operacional.
