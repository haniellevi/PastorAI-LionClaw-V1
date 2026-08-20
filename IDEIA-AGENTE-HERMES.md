# Ideia de arquitetura — Hermes Agent como agente do Igreja 12

**Status:** proposta para experimento e validação arquitetural

**Data:** 2026-08-20

**Impacto deste documento:** somente documentação; não autoriza deploy, migração de dados nem substituição de componentes em produção

## 1. Resumo executivo

A proposta é hospedar o **Hermes Agent em uma VPS da Hostinger** e usá-lo como a
camada conversacional e agêntica do Igreja 12, acessível preferencialmente pelo
**WhatsApp Business Cloud API oficial da Meta**.

Nesse desenho:

- o **Hermes** se torna o cérebro conversacional: interpreta pedidos, escolhe
  capacidades, usa memória controlada e coordena skills ou subagentes;
- o **Igreja 12 e seu backend** continuam sendo a fonte de verdade para dados,
  identidade, autorização, regras de negócio, auditoria e execução de ações;
- a **Evolution API pode ser removida** da camada de WhatsApp se o piloto com a
  integração oficial da Meta provar cobertura funcional e operacional suficiente;
- o **LangGraph deixa de ser necessariamente o cérebro central**. Ele permanece
  apenas nos workflows que realmente se beneficiem de branching explícito,
  checkpoints, human-in-the-loop, retomada ou recuperação após falhas;
- nenhuma lógica crítica deve ser transferida indiscriminadamente para decisões
  livres de um LLM.

Esta é uma hipótese arquitetural a ser testada. A stack atual continua válida até
que o experimento produza evidências suficientes para uma decisão de migração.

## 2. Objetivos e princípios

### 2.1 Objetivos

1. Permitir consultas e operações administrativas do Igreja 12 por conversa no
   WhatsApp.
2. Reduzir a quantidade de infraestrutura necessária na camada conversacional.
3. Tornar mais natural a coordenação entre capacidades especializadas de
   secretaria, G12 e consolidação.
4. Preservar regras de negócio determinísticas, isolamento multi-tenant e trilha
   de auditoria no backend.
5. Avaliar, com um piloto controlado, se Hermes + WhatsApp oficial pode substituir
   Evolution API e parte da orquestração hoje centralizada no LangGraph.

### 2.2 Princípios inegociáveis

- **O Igreja 12 é a autoridade.** O Hermes não redefine regras, permissões nem o
  estado oficial do sistema.
- **O backend decide se uma ação é permitida.** Instruções do agente nunca
  substituem autenticação, autorização ou validação de domínio.
- **Sem SQL irrestrito.** O Hermes usa APIs e tools específicas, com contratos
  pequenos e auditáveis.
- **Menor privilégio.** Cada identidade, skill e tool recebe apenas o acesso
  necessário para a tarefa.
- **Ações críticas são determinísticas.** Operações financeiras, destrutivas ou
  de segurança não dependem apenas do julgamento do modelo.
- **Migração baseada em evidência.** Evolution e LangGraph só saem dos caminhos
  em que a alternativa demonstrar segurança, confiabilidade e cobertura.

## 3. Arquitetura proposta

```text
USUÁRIO NO WHATSAPP
        │
        ▼
WHATSAPP BUSINESS CLOUD API — META
        │ webhook HTTPS
        ▼
HERMES GATEWAY — VPS HOSTINGER
        │
        ▼
HERMES MASTER "IGREJA 12"
        │
        ├── skills / tools
        ├── memória controlada
        └── subagentes / capacidades especializadas
                │
                ▼
          IGREJA 12 API
                │
        ┌───────┼──────────────┐
        ▼       ▼              ▼
       DB      AUTH         WORKFLOWS
                               │
                      LangGraph ou código
                      determinístico quando
                      realmente necessário
```

### 3.1 Canal oficial do WhatsApp

Para produção, a preferência é a **WhatsApp Business Cloud API oficial da Meta**,
recebendo eventos por webhook HTTPS na VPS. A integração oficial deve ser validada
quanto a templates, janela de atendimento, mídia, assinatura de webhooks, retries,
limites, custos e políticas da Meta.

Integrações baseadas em sessão de WhatsApp Web ou QR Code podem servir para
experimentos locais, mas não são a opção recomendada para a infraestrutura de
produção da igreja. A VPS precisa ter TLS, gestão segura de segredos, backup,
monitoramento, logs, atualização e capacidade dimensionada no spike técnico.

### 3.2 Papel do Hermes

O Hermes Master recebe a intenção do usuário e coordena as capacidades adequadas.
Ele pode:

- compreender pedidos em linguagem natural;
- selecionar uma skill ou tool autorizada;
- combinar resultados de mais de uma consulta;
- manter memória apenas nos limites definidos pela política de dados;
- delegar tarefas a capacidades especializadas;
- explicar resultados e solicitar confirmação quando o nível de risco exigir.

O Hermes não deve ser a fonte de verdade sobre cadastro, hierarquia ministerial,
permissões, pagamentos, status de consolidação ou qualquer outro dado oficial.

### 3.3 Papel do Igreja 12

O backend do Igreja 12 permanece responsável por:

- autenticar a identidade vinculada ao número do WhatsApp;
- determinar `igreja_id`, papel, escopo e permissões sem confiar em valores
  fornecidos pelo agente;
- aplicar RLS e isolamento entre igrejas;
- validar invariantes e regras de negócio;
- executar transações e workflows;
- garantir idempotência, auditoria e recuperação;
- devolver ao Hermes apenas os dados necessários para a resposta.

Mesmo que o Hermes tenha memória, o estado oficial sempre é lido ou gravado pela
API do Igreja 12.

### 3.4 Papel do LangGraph

LangGraph deixa de ser obrigatório como orquestrador de toda conversa. Ele continua
útil quando o fluxo exige uma máquina de estados explícita, por exemplo:

- branching controlado e caminhos previamente definidos;
- checkpoints e retomada de execução;
- espera por aprovação humana;
- recuperação após falha parcial;
- compensação de etapas;
- execução longa que precisa sobreviver a reinício;
- rastreabilidade rigorosa de cada transição.

Um pedido como "inscreva João no encontro" pode começar no Hermes, mas chamar um
workflow determinístico que valida elegibilidade, confirma pagamento quando
aplicável, cria a inscrição, emite credencial, envia a mensagem e registra a
auditoria. Esse workflow pode continuar em LangGraph ou ser código normal no
backend, conforme a complexidade justificar.

## 4. Capacidades especializadas

O usuário conversa com um único Hermes Master. Internamente, ele seleciona skills
ou subagentes com escopo e ferramentas próprios.

### 4.1 Secretaria

Responsabilidades possíveis:

- localizar cadastros e verificar pendências;
- consultar agenda, eventos e inscrições;
- preparar convites, comunicados e lembretes;
- criar rascunhos de atualização cadastral;
- encaminhar ações sensíveis para confirmação ou aprovação.

### 4.2 G12

Responsabilidades possíveis:

- consultar líderes, discípulos, células e cobertura ministerial;
- identificar relatórios atrasados;
- comparar indicadores de crescimento e acompanhamento;
- resumir frequência e saúde operacional, sem produzir conclusões pastorais
  automáticas como se fossem fatos;
- preparar planos de contato para revisão humana.

### 4.3 Consolidação

Responsabilidades possíveis:

- consultar novos convertidos e estágio da consolidação;
- identificar pessoas sem acompanhamento dentro do prazo;
- listar fonovisitas e próximos passos pendentes;
- preparar follow-ups;
- acionar um workflow determinístico quando uma mudança de estágio exigir
  validação, responsável e auditoria.

As capacidades podem ser implementadas como skills do Hermes, subagentes ou uma
combinação. A escolha técnica não muda o limite de segurança: todas acessam o
sistema por contratos autorizados do Igreja 12.

## 5. Exemplos de uso administrativo pelo WhatsApp

Exemplos de consultas de leitura:

- "Quem são os líderes que ainda não enviaram o relatório desta semana?"
- "Quantas pessoas novas tivemos este mês?"
- "Quais discípulos estão há mais de 30 dias sem acompanhamento?"
- "Como está o G12 dos homens?"
- "Quem faltou nas últimas três reuniões?"
- "João está sendo discipulado por quem?"
- "Quantos novos convertidos tivemos nos últimos 90 dias?"
- "Quais líderes estão crescendo e quais estão diminuindo?"
- "Faça uma análise da consolidação deste mês."

Exemplos que combinam consulta e preparação de ação:

- "Prepare uma mensagem para os 12 líderes com relatório atrasado."
- "Monte uma lista de follow-up dos novos convertidos sem fonovisita."
- "Crie um rascunho de convite para o próximo encontro."

Preparar não significa enviar. O envio ou a alteração do sistema depende do nível
de permissão, da autorização do usuário e das validações do backend.

## 6. Tools e APIs, nunca SQL irrestrito

O Hermes **não recebe credenciais de banco nem uma ferramenta genérica de SQL**.
Em vez disso, o Igreja 12 expõe operações específicas, por exemplo:

```text
localizar_membro(identificador)
listar_lideres(filtros_permitidos)
obter_relatorio(periodo, escopo)
listar_acompanhamentos_pendentes(filtros)
registrar_acompanhamento(dados_validados)
agendar_evento(dados_validados)
preparar_mensagem(destinatarios, contexto)
enviar_mensagem(rascunho_id, confirmacao)
iniciar_workflow_inscricao(pessoa_id, evento_id)
```

Cada contrato deve aplicar, no servidor:

1. autenticação da pessoa que iniciou a conversa;
2. resolução segura de igreja, papel e escopo;
3. autorização por operação e por recurso;
4. validação de schema e regras de domínio;
5. limitação de volume e proteção contra abuso;
6. idempotência para retries do WhatsApp ou do agente;
7. auditoria com ator, igreja, ação, parâmetros seguros, resultado e horário;
8. minimização e mascaramento de dados pessoais na resposta;
9. timeout, tratamento de erro e resposta que não exponha segredos;
10. confirmação ou aprovação humana quando o risco exigir.

Conteúdo recebido por mensagem, documento, áudio ou link deve ser tratado como
entrada não confiável. Prompt injection ou instruções presentes nesse conteúdo não
podem ampliar as permissões das tools.

## 7. Níveis de permissão

O nível é determinado pela operação real no backend, não pelo texto usado pelo
Hermes para descrevê-la.

| Nível | Política | Exemplos | Controle mínimo |
|---|---|---|---|
| **1 — Leitura** | Hermes pode executar sozinho dentro do escopo do usuário | listar líderes, consultar relatório, resumir frequência | autenticação, RLS, autorização, minimização e auditoria |
| **2 — Ação reversível** | Hermes pode executar se houver contrato idempotente e forma clara de desfazer | criar rascunho, registrar lembrete, preparar lista, agendar tarefa cancelável | validação, idempotência, auditoria e indicação do que foi alterado |
| **3 — Ação sensível** | exige confirmação explícita e contextual; alguns casos exigem aprovação de outro papel | enviar comunicação, mudar dados pessoais, alterar vínculo de acompanhamento, avançar etapa | resumo antes da ação, confirmação recente, autorização reforçada e auditoria completa |
| **4 — Ação crítica** | bloqueada para decisão autônoma do Hermes ou executada somente por workflow dedicado com controles adicionais | exclusão em massa, mudança de papéis/permissões, operação financeira, exportação ampla, alteração de segurança | backend bloqueia por padrão; reautenticação, dupla aprovação ou canal administrativo separado quando aplicável |

Confirmação em linguagem natural não transforma uma ação proibida em permitida. O
backend continua tendo a palavra final.

## 8. Fluxos que devem continuar determinísticos

São candidatos fortes a LangGraph ou código explícito no backend:

- inscrição com pagamento, credencial, comunicação e auditoria;
- alteração de dados após validação de identidade e aprovação humana;
- mudança de papel, permissão ou estrutura ministerial;
- transição sensível na jornada G12;
- envio em massa sujeito a consentimento, opt-out e janela de comunicação;
- operações financeiras;
- exclusões, fusões ou movimentações de dados;
- processos longos com checkpoints e recuperação.

O Hermes inicia o fluxo com parâmetros estruturados e acompanha o resultado. Ele
não improvisa etapas, ignora gates nem grava diretamente no banco.

## 9. Possível remoção da Evolution API

A Evolution API pode deixar de ser necessária se o Hermes Gateway integrado à API
oficial da Meta cobrir, com qualidade suficiente:

- recebimento e envio de texto e mídias necessários ao produto;
- verificação, assinatura, retry e deduplicação de webhooks;
- templates e janelas de conversa;
- correlação entre mensagem, usuário, igreja e conversa;
- observabilidade, filas, backpressure e recuperação;
- limites, custos e requisitos operacionais aceitáveis;
- migração de número e convivência temporária sem perda de mensagens.

A remoção não deve acontecer apenas porque o caminho novo funciona em uma
demonstração. É necessário provar equivalência ou definir conscientemente as
diferenças, executar rollout gradual e manter plano de rollback.

## 10. Plano recomendado de experimento

### Fase 0 — inventário e contratos

- mapear todos os fluxos atuais de Evolution, LangGraph e backend;
- classificar cada operação nos quatro níveis de permissão;
- definir identidade, papéis, escopos e política de memória;
- escolher um conjunto pequeno de tools somente de leitura;
- definir métricas, logs, alertas e critérios de rollback.

### Fase 1 — piloto de leitura

- instalar Hermes em ambiente isolado na VPS Hostinger;
- conectar um número e aplicação de teste pela API oficial da Meta;
- liberar apenas usuários internos e consultas de leitura;
- validar isolamento entre igrejas, respostas, latência, custo e auditoria;
- testar entradas maliciosas, retries e indisponibilidade de dependências.

### Fase 2 — ações reversíveis

- liberar rascunhos, lembretes e tarefas canceláveis;
- provar idempotência e desfazer ações;
- validar limites de volume e mensagens duplicadas;
- exercitar falhas parciais e recuperação.

### Fase 3 — ações sensíveis controladas

- adicionar confirmação contextual e, quando necessário, aprovação humana;
- acionar workflows determinísticos pelo backend;
- medir incidentes, falsos acionamentos, taxa de conclusão e carga operacional.

### Fase 4 — decisão arquitetural

Com base nas evidências:

- manter ou remover Evolution API por caminho funcional;
- manter LangGraph somente onde os requisitos de workflow o justificarem;
- promover, limitar ou rejeitar Hermes como cérebro conversacional;
- documentar rollout, rollback e responsabilidades operacionais.

## 11. Critérios mínimos para considerar a proposta aprovada

- nenhuma possibilidade de SQL irrestrito ou bypass de autorização;
- isolamento multi-tenant comprovado por testes negativos;
- identidade do WhatsApp vinculada de forma segura ao usuário e ao papel;
- auditoria consultável de todas as tools e workflows;
- idempotência sob retries e mensagens duplicadas;
- confirmação e aprovação funcionando para níveis 3 e 4;
- métricas e alertas para falha, latência, custo e volume;
- política de memória, retenção e dados pessoais aprovada;
- plano de contingência quando Hermes, Meta ou VPS estiver indisponível;
- comparação documentada com o comportamento atual;
- rollout gradual e rollback testado antes de retirar componentes existentes.

## 12. Decisão recomendada neste momento

**Executar um piloto controlado antes de substituir qualquer componente.**

Hermes + WhatsApp Business Cloud API oficial da Meta + VPS Hostinger é uma
arquitetura promissora para simplificar a camada conversacional do Igreja 12.
Evolution API pode sair, e LangGraph pode deixar de ser o cérebro central, mas
somente depois de validação por fluxo.

O limite permanente é claro: **Hermes é o agente; o Igreja 12 continua sendo a
autoridade sobre dados, identidade, permissões, regras e ações.**
