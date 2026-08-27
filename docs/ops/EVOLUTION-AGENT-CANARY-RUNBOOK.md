# Canário do agente Evolution

Este runbook prepara, executa e registra canários controlados do agente de
WhatsApp de uma igreja piloto. Ele não autoriza um canário. Cada execução exige
autorização nominal depois que todos os gates de preparação estiverem
comprovados.

O primeiro alvo é a Igreja Batista Filadélfia Internacional de Corrente. O
procedimento foi escrito para poder ser reutilizado por outra igreja sem copiar
segredos, identificadores pessoais ou dados de produção para o repositório.

## Princípio de contenção

O canário precisa de duas autorizações independentes:

1. `AgentConfig.ativo=true` libera o runtime apenas para a igreja escolhida.
2. `ALLOW_REAL_SENDS=true` libera efeitos externos globais, incluindo LLM e
   Evolution.

Enquanto a preparação estiver em andamento, `AgentConfig.ativo` e
`ALLOW_REAL_SENDS` permanecem `false`. A credencial BYO pode estar validada e
ativa sem ligar o agente.

`ASAAS_BILLING_ENABLED`, `BREVO_SEND_MODE` e `BROADCAST_ASYNC_ENABLED` não fazem
parte deste canário e não podem ser alterados. `marcar_presenca` permanece
desabilitada no registro de capacidades do agente.

## Estado mínimo antes da preparação

- `origin/main` contém a fundação de identidade e autorização da PR #294.
- O backend implantado contém o mesmo commit ou um descendente revisado.
- `/health` responde `ok` e `/ready` responde `ready`.
- A instância Evolution da igreja está online.
- A fila de entrada e a fila de processamento estão vazias.
- A dead-letter canônica está vazia. Um item legado sem metadados seguros não
  pode ser atribuído ao número do canário por suposição: ele bloqueia a
  ativação até ser preservado por uma quarentena atômica, em gate separado,
  sem leitura do payload e sem reprocessamento.
- Existe exatamente um `AgentConfig` para a igreja piloto e ele está inativo.
- Nenhuma outra igreja possui `AgentConfig.ativo=true`.
- A BYO está configurada para `openai`, em modelo permitido, e revalida sem que
  a chave seja retornada.
- O número do primeiro canário ativo é sintético, dedicado, sem papel
  privilegiado e sem histórico de Pessoa, conversa ou mensagens na igreja
  piloto. Autorização do titular não transforma um número pastoral já usado em
  contato sintético.

Qualquer divergência interrompe a preparação. Não corrigir estado desconhecido
abrindo o gate global.

## Fase 1: preparação sem envio

### 1. Fixar a fonte e o runtime

Registrar o SHA de `origin/main` e o caminho do release ativo. O release precisa
conter a PR #294 antes do canário.

```bash
git rev-parse origin/main
readlink -f /opt/pastorai-current
```

Se o nome do release não provar o SHA, registrar o SHA dentro do artefato de
deploy ou comparar o código implantado. Não inferir versão por data.

### 2. Confirmar saúde e gates fechados

Executar na VPS sem imprimir o restante do ambiente:

```bash
cd /opt/pastorai-current/deploy
docker compose ps backend queue-worker cron-worker broadcast-worker
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
docker compose exec -T backend sh -lc '
  for name in ALLOW_REAL_SENDS ASAAS_BILLING_ENABLED BREVO_SEND_MODE BROADCAST_ASYNC_ENABLED; do
    value=$(printenv "$name" 2>/dev/null || true)
    test -n "$value" || value="<unset>"
    printf "%s=%s\n" "$name" "$value"
  done
'
```

O estado obrigatório é:

```text
ALLOW_REAL_SENDS=false
ASAAS_BILLING_ENABLED=false
BREVO_SEND_MODE=off
BROADCAST_ASYNC_ENABLED=false
```

### 3. Salvar comportamento com o agente desligado

Usar o console master, abrir a igreja piloto e salvar pelo endpoint
`PUT /admin/igrejas/{igreja_id}/agente`. O campo `ativo` deve ser enviado como
`false`, inclusive quando a configuração já existir.

Comportamento inicial recomendado:

```text
Adote um tom acolhedor, pastoral, breve e respeitoso. Use frases simples, sem
jargão, e no máximo três frases. Reformule somente a resposta-base, sem
acrescentar dados, promessas, convites, ações, horários, endereços, registros ou
permissões. Preserve as negativas, os limites e o encaminhamento humano com o
mesmo sentido da resposta-base.
```

Nome recomendado: `Assistente Filadélfia`.

Tom recomendado: `acolhedor, pastoral, breve e respeitoso`.

Esse texto controla estilo. Identidade, tenant, papel, ferramentas e efeitos
continuam determinados pelo servidor.

### 4. Revalidar a BYO sem reexibir a chave

O admin da igreja abre `Agente IA > Credencial LLM`. Se a chave precisar ser
substituída, o operador da igreja digita a nova chave diretamente no campo de
senha. O master e o time de suporte não recebem a chave.

O PastorAI aceita somente o provedor `openai` nesta versão e cifra a chave por
igreja. Nunca reutilizar uma chave de ferramenta de desenvolvimento, copiar
chave para este arquivo ou colar segredo em issue, PR, log ou conversa.

Para uma credencial ativa já armazenada, deixar a chave em branco e usar
`Revalidar credencial`. A tela chama o endpoint existente com o modelo atual e
mantém o segredo cifrado somente no servidor:

```http
PUT /agent/model
Authorization: Bearer <token do admin da própria igreja>
Content-Type: application/json

{"modelo":"gpt-5.6-luna"}
```

Somente HTTP 200 com `validado=true` aprova essa etapa. Respostas 401, 403, 409,
422 ou 502 bloqueiam o canário. Não substituir a BYO por uma chave do PastorAI.

### 5. Provar o estado inativo

Validar por duas superfícies:

- console master: `configured=true`, `ativo=false`,
  `credencialStatus=active`;
- painel da igreja: `configured=true`, `ativo=false`, credencial `active` e
  modelo `gpt-5.6-luna`.

Uma consulta administrativa ao banco pode confirmar o estado, mas não substitui
o registro de auditoria produzido pela API. A consulta nunca seleciona
`api_key_encrypted`.

### 6. Provar a contenção com o agente inativo

Este smoke é anterior ao canário ativo. Ele exige autorização para um único
inbound controlado, mas mantém `AgentConfig.ativo=false` e
`ALLOW_REAL_SENDS=false`. Use um número de controle separado; não consuma
nesta etapa o número novo reservado ao canário ativo.

O resultado esperado possui quatro provas:

1. o painel exibe `IA pausada pela igreja`;
2. o inbound é persistido com autoria `contato`;
3. o ledger encerra o ciclo em `ia_sem_resposta`;
4. não existe mensagem posterior com `agent_reply_state='ia'`, autoria de IA
   legada sem estado, ou estado não terminal.

`ia_sem_resposta` é um marcador interno de supressão. Ele pode ocupar uma
linha outbound com autoria `ia` e identificador durável, mas o router o oculta
da thread e o transporte Evolution não o trata como envio confirmado. Por isso,
contar linhas apenas por `direcao='out'` produz falso positivo; a evidência
precisa considerar `agent_reply_state`.

Passar neste smoke comprova contenção. Não qualifica para o canário ativo um
número que já possua papel privilegiado ou histórico operacional.

## Fase 2: pacote de autorização

Preparar estes valores sem abrir qualquer gate:

- SHA exato do backend implantado;
- igreja e instância Evolution escolhidas;
- um único número sintético dedicado e sem papel privilegiado;
- zero Pessoa, conversa e mensagem prévias para o número na igreja piloto;
- três mensagens exatas do roteiro;
- expectativa de rota e de persistência para cada mensagem;
- responsável por observar API, worker, Evolution e banco;
- responsável por fechar o gate;
- horário de início e limite máximo da janela;
- comando de rollback já revisado.

Roteiro inicial recomendado para um contato sintético:

1. Enviar `Olá` e esperar somente o termo de consentimento.
2. Enviar `Aceito` e esperar a confirmação determinística do consentimento.
3. Enviar `Quero conhecer a igreja` e esperar uma única resposta de onboarding,
   refinada pela BYO sem alterar o sentido da resposta-base.

O número deve começar sem papel privilegiado. O primeiro canário não executa
ferramentas de escrita e não testa `marcar_presenca`.

Antes da autorização, comprovar por testes locais os perfis contato, membro,
líder, admin e pastor, além de duplicidade, ferramenta desconhecida,
cross-tenant, handoff, opt-out, restart do webhook e dead-letter.

## Fase 3: execução controlada, somente após autorização nominal

Esta fase não pode ser iniciada por aprovação genérica da PR ou deste runbook.
A autorização precisa nomear a igreja, o número, a janela e a abertura temporária
de `ALLOW_REAL_SENDS`.

Ordem operacional:

1. Confirmar novamente SHA, saúde, filas canônicas vazias e os quatro gates
   fechados.
2. Confirmar que somente a igreja piloto será ativada.
3. Salvar `AgentConfig.ativo=true` pelo console master.
4. Abrir somente `ALLOW_REAL_SENDS=true` na janela aprovada e reiniciar apenas
   os processos que leem essa variável no boot.
5. Executar as três mensagens na ordem e interromper ao primeiro resultado
   divergente ou ambíguo.
6. Fechar `ALLOW_REAL_SENDS=false` e reiniciar os mesmos processos.
7. Salvar `AgentConfig.ativo=false`.
8. Verificar que não existe segunda resposta, retry pendente ou efeito em outro
   tenant.
9. Registrar evidências sem telefone completo, token, chave, conteúdo privado ou
   ciphertext.

Não ligar `BROADCAST_ASYNC_ENABLED`. Não alterar Asaas, Brevo, Calendar ou crons.

## Evidências obrigatórias

- um inbound e no máximo um outbound por mensagem do roteiro;
- tenant derivado da instância correta;
- Pessoa ativa resolvida pelo telefone canônico;
- nenhuma duplicidade de Pessoa ou conversa;
- consentimento persistido antes de coletar dados adicionais;
- nenhum papel inferido do texto;
- nenhum tool call no primeiro canário;
- eventos de auditoria do agente sem PII desnecessária;
- nenhuma linha alterada em outro tenant;
- `AgentConfig.ativo=false`, `ALLOW_REAL_SENDS=false`,
  `ASAAS_BILLING_ENABLED=false`, `BREVO_SEND_MODE=off` e
  `BROADCAST_ASYNC_ENABLED=false` ao terminar.

### Gate de qualidade conversacional

O resultado técnico e o resultado de produto são avaliados separadamente. Um
canário pode provar cardinalidade, autoria, isolamento e rollback e ainda assim
falhar como experiência.

Antes de autorizar rollout para outra igreja, uma revisão humana precisa
confirmar que:

- o agente não repete uma pergunta cuja resposta já apareceu na conversa;
- a resposta é natural, breve e coerente com o contexto, sem soar como uma
  sequência de templates desconectados;
- a negativa por falta de informação oficial é explícita e não inventa fatos;
- o próximo passo é específico, sem pedir novamente tudo o que já foi
  informado;
- conteúdo privado da conversa não é apresentado como conhecimento público ou
  institucional.

Falha nesse gate bloqueia rollout amplo, mesmo quando todos os controles
técnicos passam.

## Critérios de abortar

Abortar e fechar o gate global imediatamente quando ocorrer qualquer um destes
casos:

- release sem a PR #294 ou SHA inconclusivo;
- BYO não revalidada;
- identidade duplicada ou tenant inconclusivo;
- fila de entrada ou processamento prévia, dead-letter canônica não vazia ou
  worker sem heartbeat;
- resposta diferente da rota esperada;
- mais de um outbound;
- timeout após possível envio;
- efeito de ferramenta inesperado;
- mensagem ou mutação em outro tenant;
- perda de saúde do backend, Redis, worker ou Evolution.

Resultado ambíguo nunca recebe reenvio automático.

## Quarentena de dead-letter legada

Uma dead-letter que não possua os metadados seguros `stage`, `error_class`,
`first_failed_at` e `last_failed_at` não pode ser aberta para descobrir a
quem pertence. Também não pode ser apagada ou reprocessada para liberar o
canário.

Em gate humano separado, a contenção recomendada é:

1. confirmar tipo `list`, comprimento esperado e ausência da chave de destino;
2. mover atomicamente a chave canônica com `RENAMENX` para uma chave de
   quarentena datada e exclusiva;
3. confirmar comprimento preservado e dead-letter canônica vazia;
4. não definir TTL, não executar `LRANGE`, `LINDEX`, `RPOP` ou replay;
5. registrar a chave de quarentena em uma política de retenção e descarte
   posterior.

Se a chave canônica mudar entre o preflight e o `RENAMENX`, abortar. O
rollback só pode devolver a quarentena ao nome canônico quando este estiver
ausente, também com `RENAMENX`.

### Registro de retenção de 2026-08-26

- chave preservada:
  `pastorai:webhooks:dead:quarantine:20260826T165417Z:994de6119f3664c4`;
- a movimentação atômica preservou um item, deixou a chave canônica ausente e
  manteve a quarentena como `list`, comprimento `1` e sem TTL;
- o payload permanece proibido de leitura, exportação, replay ou
  reprocessamento;
- revisar a necessidade de retenção até 2026-09-25. Extensão, descarte ou
  rollback exigem gate humano separado e evidência de que a chave canônica
  continua ausente;
- não aplicar expiração automática. A revisão deve decidir explicitamente
  entre retenção justificada e descarte integral, sem abrir o payload.

## Estado observado em 2026-08-26

- o smoke de contenção da Filadélfia passou com o agente inativo: o painel
  exibiu a pausa, houve um `ia_sem_resposta`, zero envio de IA confirmado,
  zero envio legado posterior e zero estado não terminal;
- o número apresentado para esse smoke pertence a uma Pessoa ativa com papel
  privilegiado e conversa operacional anterior. Ele está rejeitado como alvo
  do primeiro canário ativo;
- a fila de entrada e a fila de processamento estavam vazias;
- o item legado da dead-letter foi movido atomicamente para a chave de
  quarentena registrada acima. A chave canônica ficou vazia, o comprimento
  foi preservado, não foi definido TTL e o payload não foi lido, apagado ou
  reprocessado;
- `AgentConfig.ativo=false` permaneceu para a Filadélfia e nenhuma igreja
  estava com agente ativo;
- o canário ativo permanece bloqueado até um preflight final do candidato
  sintético e autorização nominal separada para a janela de envio.

## Resultado do primeiro canário ativo em 2026-08-27

Esta seção registra relato operacional confirmado pelo operador. O repositório
não contém o pacote imutável de logs, consultas e SHA de runtime da janela, logo
os itens abaixo não constituem prova independente de deploy. O telefone usado
foi sintético e não é registrado em claro.

- o roteiro recebeu, na ordem, `Olá`, `Aceito` e
  `Quero conhecer a igreja`;
- houve exatamente três entradas e três saídas;
- a autoria das três respostas foi classificada corretamente como IA;
- as filas canônicas e a dead-letter canônica terminaram vazias;
- o registro legado permanece isolado na quarentena, sem leitura, replay ou
  descarte, com revisão de retenção prevista para 2026-09-25;
- `AgentConfig.ativo` e os quatro gates globais foram restaurados ao estado
  fechado no encerramento da janela.

Resultado técnico: **PASS CONTROLADO**.

Resultado de qualidade: **FAIL**. O operador observou tom robótico e repetição
de perguntas. Esse resultado não invalida a prova de contenção, mas bloqueia
qualquer rollout amplo e torna inadequado repetir o mesmo roteiro sem corrigir
a arquitetura conversacional.

O próximo gate é revisar e integrar a PR documental D0. Depois do merge, D1
revalida segurança, capacidades e escopos no novo SHA em modo read-only e sob
autorização própria. Implementação, migration, deploy, ativação e novo canário
permanecem fora deste gate.

Este registro não autoriza ativação, alteração de flag, chamada LLM, envio
Evolution, leitura ou descarte da quarentena.

## Rollback

O rollback começa pela contenção de rede:

1. restaurar `ALLOW_REAL_SENDS=false`;
2. reiniciar os processos consumidores da variável;
3. confirmar o gate fechado dentro dos containers;
4. restaurar `AgentConfig.ativo=false`;
5. preservar mensagens, logs e outbox para investigação;
6. não reenviar resultado `desconhecido`;
7. registrar o incidente e encerrar a janela.

O rollback não apaga Pessoa, conversa, consentimento, mensagem ou auditoria.
