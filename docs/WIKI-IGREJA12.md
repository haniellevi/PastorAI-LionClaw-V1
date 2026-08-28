# Wiki do projeto Igreja 12

Snapshot documental de 2026-08-28, baseado no `origin/main`
`1029e1b0adb9479a2a23d60e27e9215a6ae6a10e`, na auditoria D1 e na
reconciliação operacional registrada nesta fase.

## Leitura de 30 segundos

A V1 do Igreja 12 está encerrada como piloto controlado. Autenticação, tenant,
Pessoas, Células, conversas, painéis, filas, integrações protegidas e a fundação
do agente formam uma base funcional.

O produto amplo ainda não está concluído. O objetivo aprovado é operar a rotina
da igreja principalmente pelo WhatsApp, com o painel reservado para
configuração, governança, exceções e ações sensíveis. Para chegar a esse marco,
faltam memória privada durável, conhecimento oficial por igreja, especialistas
de domínio, ações confirmadas, notificações unificadas, formação e validação
operacional ampla.

O canário ativo do agente passou tecnicamente e terminou com os gates fechados,
mas não passou como validação de qualidade: as respostas ficaram robóticas e
repetitivas. Por isso, o próximo trabalho é fortalecer a arquitetura antes de
qualquer expansão do canário.

## Princípios aprovados

- WhatsApp é a interface operacional principal.
- Web é apoio administrativo, de segurança e governança.
- Uma definição global e versionada de LangGraph atende todas as igrejas.
- Dados, memória, conhecimento, credenciais e execução são isolados por tenant.
- Conversas permanecem memória privada até exclusão solicitada e aprovada.
- Registros do sistema e documentos aprovados são as fontes oficiais.
- Conversa privada nunca vira conhecimento institucional automaticamente.
- O agente diz quando não sabe e encaminha a lacuna ao responsável do setor.
- Ações comuns podem terminar no WhatsApp após resumo e confirmação.
- Ações sensíveis terminam no painel autenticado.
- A primeira vertical é o relatório de célula completo pelo WhatsApp.
- OpenAI BYO é o provedor do PastorAI. OpenRouter não faz parte do produto.

## Estado geral

| Área | Estado | Próximo resultado necessário |
|---|---|---|
| V1 | `IMPLEMENTADO` | Preservar o encerramento e tratar a visão ampla como nova fase |
| Agente e Evolution | `PARCIAL / GATE OPERACIONAL` | Corrigir memória, conhecimento e qualidade antes de novo canário |
| Canário ativo | `PASS TÉCNICO / QUALIDADE INSUFICIENTE` | Avaliação conversacional humana após a nova fundação |
| LangGraph | `IMPLEMENTADO STATELESS / D2B1 CANDIDATA OFFLINE` | Integrar o contexto confiável; persistência e subgrafos permanecem posteriores |
| Conhecimento por igreja | `AUSENTE` | Ingestão aprovada, ACL, busca e ferramentas de dados vivos |
| Relatório por WhatsApp | `PARCIAL` | Confirmar e gravar no relatório canônico |
| Central de Células | `PARCIAL FORTE` | Operação e notificações principais pelo WhatsApp |
| Agenda | `PARCIAL` | Consultas, confirmações e avisos pela plataforma unificada |
| Consolidação | `PARCIAL` | Máquina de estados e progresso durável |
| Universidade da Vida | `AUSENTE COMO MÓDULO` | PRD e implementação após Consolidação |
| Capacitação Destino | `AUSENTE COMO MÓDULO` | PRD e implementação após UV |
| Comercial | `GATES OPERACIONAIS` | Canários separados de broadcast, Brevo e Asaas |
| RNFs de campo | `NÃO VERIFICADO INTEGRALMENTE` | Acessibilidade, performance, retenção e recuperação contínua |

## O que está implementado

### Plataforma

- Superfícies separadas para operação, administração da igreja e console SaaS.
- Clerk, RBAC no backend e RLS PostgreSQL por igreja.
- Pessoas, papéis, Jornada G12 básica, Células, reuniões e relatórios web.
- Minha Célula, Central, solicitações, transferência e remoção de membros.
- Conversas, histórico, handoff, transferência humana e mídia privada.
- Painel de Hoje e fila central por responsabilidades existentes.
- Agenda, broadcast, billing e integrações com contenção e auditoria próprias.

### Fundação do agente

- instância Evolution identifica a igreja;
- telefone canônico identifica uma Pessoa ativa dentro do tenant;
- identidade duplicada, ferramenta desconhecida ou papel inconsistente falham
  fechados;
- papéis e capacidades são resolvidos no servidor;
- consentimento, opt-out, handoff e estado IA/humano são respeitados;
- credencial BYO válida não ativa o agente;
- `AgentConfig.ativo=false` impede resposta automática;
- `marcar_presenca` permanece desabilitada no runtime;
- falhas novas da fila possuem metadados seguros para investigação.

## O que está parcial

### Conversa e inteligência

O grafo atual é stateless. Ele não carrega histórico, não mantém campos já
respondidos e não consulta uma base oficial da igreja. O LLM é usado apenas
para refinar parte de uma resposta determinística. Esse desenho é um fator
tecnicamente compatível com a repetição vista no canário, mas a execução não
prova que ele seja a causa única.

Mensagens ficam registradas e áudio pode ser armazenado, mas não foi encontrada
transcrição operacional. O parser de relatório produz um evento de auditoria e
uma resposta, porém não grava o relatório oficial da reunião.

### Operação pastoral

Central, Minha Célula, Agenda e Consolidação possuem bases web úteis. Ainda não
formam uma experiência principal pelo WhatsApp. Notificações estão divididas
entre SLA, cron, serviços de evento, no-op de célula e broadcast, sem um ledger
geral de finalidade, consentimento, retry e escalonamento.

### Privacidade

A exclusão atual da conversa cobre conversa, mensagens e mídia. A nova memória
precisará incluir transcrição, resumo, checkpoint e vetores na mesma exclusão
aprovada. Consentimento também precisa ser separado por atendimento, cuidado
pastoral, tarefas operacionais e comunicados.

## O que está ausente

- checkpointer durável conectado ao LangGraph;
- resumos privados e recuperação seletiva do histórico;
- base institucional com documentos aprovados, versão e audiência;
- busca híbrida e vetorial com RLS por igreja;
- propostas duráveis para confirmar ações no WhatsApp;
- outbox unificada para notificações proativas;
- onboarding guiado completo da igreja e de seus responsáveis;
- especialistas completos de Agenda, Consolidação, UV e CD;
- módulos operacionais de Universidade da Vida e Capacitação Destino;
- política completa de retenção e eliminação dos derivados de IA.

## Canário ativo do agente

O canário ativo é evidência operacional reconciliada nesta missão. Ele ainda
não constava como concluído no snapshot anterior `ad4a272`.

Foram enviadas somente as mensagens sintéticas `Olá`, `Aceito` e
`Quero conhecer a igreja`. O resultado técnico foi:

- três mensagens de entrada e três de saída;
- autoria da IA preservada;
- filas e dead-letter canônicas vazias;
- `AgentConfig.ativo=false` e `ALLOW_REAL_SENDS=false` restaurados ao final;
- Asaas, Brevo e broadcast permaneceram fechados.

Esses itens são relato do operador. A janela não deixou artefato versionado
capaz de provar de forma independente isolamento cross-tenant, ausência de tool
call ou ausência de mutação de domínio.

Esse `PASS` não é aprovação de qualidade. A avaliação humana identificou
linguagem robótica, pergunta repetida e falta de memória e conhecimento. O
registro operacional detalhado está em
[`POST-V1-MISSION-REGISTER.md`](ops/POST-V1-MISSION-REGISTER.md), atualizado na
mesma missão documental.

## Arquitetura de destino

```text
WhatsApp
  -> Evolution
  -> webhook e fila idempotente
  -> contexto confiável da igreja e da Pessoa
  -> política de identidade, capacidade e consentimento
  -> LangGraph global
       -> Atendimento
       -> Central de Células
       -> Agenda
       -> Consolidação
       -> Universidade da Vida (visão futura, fora da missão atual)
       -> Capacitação Destino (visão futura, fora da missão atual)
  -> política de resposta e proposta de ação
  -> outbox
  -> Evolution

Dados vivos -> ferramentas tipadas -> serviços de domínio
Documentos aprovados -> busca com tenant e audiência
Conversas -> memória privada, nunca publicação automática
```

O desenho detalhado está em
[`2026-08-27-whatsapp-first-tenant-agent-architecture.md`](decisions/2026-08-27-whatsapp-first-tenant-agent-architecture.md).

## Roteiro de conclusão

### D0, fonte de verdade

Reconciliar PRD, PRODUCT, SPEC, progresso, Wiki, memória de agentes, decisão de
arquitetura e registro do canário. Fase concluída na PR #310.

### D1, segurança

Revalidar capacidades, papéis, responsabilidades e endpoints sensíveis no SHA
atual. A auditoria confirmou quatro gaps de tenant, integridade e cobertura do
CI. A correção D1A foi integrada pela PR #311 e a migration foi aplicada em
DEV depois de preflight próprio. Produção não foi alterada.

### D2 a D5, fundação

Construir contexto confiável, consentimentos por finalidade, propostas de
ação, memória durável, exclusão integral, conhecimento oficial, onboarding e
outbox unificada. A PR #313 integrou a D2A como fronteira privada inativa: role
sem login, schema privado, helper de tenant e factory exclusiva ainda
desconectada do worker e do LangGraph. O candidato incorporado passou em 278
testes RLS no PostgreSQL 17 descartável e em 2.688 testes offline; isso não
prova execução em ambiente compartilhado. A integração não aplicou migration
compartilhada, não provisionou credencial, não conectou o runtime, não fez
deploy manual ou do backend, não promoveu a produção e não ativou o agente. O
único deploy associado foi o preview automático da PR, que não prova execução
do backend nem ambiente compartilhado.

A candidata D2B1, ainda fora de `origin/main`, cria um contexto confiável v1
imutável e separado do estado mutável do grafo. A fronteira é montada pelo
servidor, revalidada antes do caminho compilado, do caminho direto e em cada
node, e preserva a mesma instância de `PrivilegeContext` até o executor de
tools. A entrada e o snapshot de Pessoa recusam chaves de autoridade, IDs,
telefone e campos não necessários ao turno.

A candidata passou em 224 testes focais. Duas passagens adversariais fecharam
os achados P1 e concluíram `GO`. A suíte offline completa local ficou
`INCONCLUSIVA`: a baseline limpa no mesmo SHA também excedeu 90 segundos no
módulo TestClient inalterado `test_agent_config_requests.py`. O workflow
`Backend Tests` da PR precisa executar a suíte integral e concluir verde antes
da integração. O LangGraph continua stateless, sem checkpointer persistente.

A continuação permanece ordenada em D2B1; `D2B2`, consentimentos independentes
por finalidade, fica bloqueada até o merge da D2B1; `D2C` reserva propostas
duráveis; e `D3`, memória privada durável com exclusão integral. A candidata
não adiciona migration, não acessa Supabase, não provisiona credencial, não
conecta a fronteira privada D2A, worker, fila ou checkpointer, não faz deploy,
não ativa o agente e não executa canário.

### D6, primeira vertical

Entregar relatório de célula pelo WhatsApp com lembrete, texto ou áudio,
resumo corrigível, confirmação, gravação idempotente em `celula_reuniao` e
comprovante após commit.

### D7 e D8, produto pastoral amplo

Levar Central, Agenda, Consolidação e os fluxos de Enviar com contrato aprovado
ao WhatsApp. Universidade da Vida e Capacitação Destino estão excluídas da
missão atual; dependências que exijam esses módulos não serão improvisadas.

### D9, operação comercial

Executar canários independentes das integrações selecionadas, com consentimento,
observabilidade, responsáveis e rollback. A evolução do agente não abre Asaas,
Brevo ou broadcast.

## Dívidas que continuam visíveis

- política e execução de retenção dos logs do agente;
- revisão da quarentena de dead-letter na data registrada no runbook;
- restore periódico incluindo os novos schemas privados;
- avaliação manual com teclado, leitor de tela e zoom;
- métricas de performance em condições reais;
- owner operacional, substitutos e escalonamento por setor;
- critérios jurídicos e operacionais dos quatro consentimentos;
- PRDs próprios para Formação e máquina de estados da Jornada.

## Fontes de verdade

Em divergência, use esta ordem:

1. ambiente vivo consultado e identificado no momento da ação;
2. Git, CI, código, migrations e testes do SHA exato;
3. PRD canônico e decisões aprovadas;
4. `docs/audits/2026-08-27-d1-security-scope-audit.md`,
   `docs/audits/2026-08-27-project-source-of-truth.md`, registro pós-V1 e
   runbooks;
5. Bootstrap, cobertura do PRD, esta Wiki, PRODUCT, SPEC e Plan Designer;
6. planos, sprints e auditorias substituídas ou históricas.

Nenhum item desta Wiki autoriza migration, deploy, flag, mensagem, cobrança ou
canário.

## Próximo gate único

Revisar e integrar a PR D2B1 somente se o workflow `Backend Tests` executar a
suíte offline completa e concluir verde. D2B2 permanece bloqueada e só poderá
ser promovida a próximo gate depois do merge e de nova reconciliação.
Migration, Supabase, provisioning, conexão da fronteira privada D2A, deploy,
ativação e canário permanecem fora.
