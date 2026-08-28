---
project: igreja12
document_kind: ai-bootstrap
status: canonical
last_verified: 2026-08-28
audited_repository_sha: 1029e1b0adb9479a2a23d60e27e9215a6ae6a10e
---

# Bootstrap canônico para agentes de IA

Este documento fornece o contexto mínimo para começar a trabalhar no Igreja 12
sem reconstruir a história por conversas anteriores. Ele é um índice e não uma
autorização operacional.

## Produto e princípio de interação

O Igreja 12, também chamado PastorAI no código histórico, é um SaaS
multi-tenant para operação pastoral na Jornada G12.

O WhatsApp oficial da igreja é a interface principal para visitantes, membros,
líderes e responsáveis. A pessoa deve conseguir consultar, responder tarefas e
realizar ações comuns sem aprender o painel. A web permanece necessária para:

- configuração inicial e administração;
- governança, auditoria e filas de exceção;
- permissões, dados pastorais restritos e ações sobre terceiros;
- finanças, integrações, publicação de conhecimento e exclusão de dados.

As superfícies web são `app.`, `admin.` e `painel.`. O núcleo técnico usa
Next.js, FastAPI, PostgreSQL/Supabase com RLS por `igreja_id`, Clerk, Redis,
workers, Evolution e OpenAI BYO. Asaas, Brevo e Google Calendar são integrações
externas com contratos e gates próprios.

## Estado executivo

| Tema | Estado no SHA auditado | Leitura correta |
|---|---|---|
| V1 | `IMPLEMENTADO` | Encerrada como piloto controlado; não equivale ao produto amplo concluído |
| Código | `VERIFICADO / D2B1 CANDIDATA OFFLINE` | `origin/main` em `1029e1b0adb9479a2a23d60e27e9215a6ae6a10e`; D1A e D2A integradas, com D2A inativa; D2B1 existe apenas no diff candidato |
| Produto WhatsApp-first | `PARCIAL` | A visão está aprovada; memória, conhecimento e ações profundas ainda faltam |
| Agente Evolution | `PARCIAL / GATE OPERACIONAL` | Fundação, identidade e contenção existem; qualidade conversacional é insuficiente |
| Canário ativo do agente | `PASS TÉCNICO / QUALIDADE INSUFICIENTE` | Evidência operacional reconciliada nesta missão, não prova previamente versionada em `ad4a272` |
| LangGraph | `IMPLEMENTADO STATELESS` | Grafo único e fallback determinístico, sem checkpoint durável |
| Conhecimento institucional | `AUSENTE` | Não existe RAG com documentos aprovados nem consulta institucional ampla |
| Relatório de célula por WhatsApp | `PARCIAL` | O parser registra evento, mas não envia o relatório canônico |
| Central e Agenda | `PARCIAL FORTE` | Núcleo web existe; operação integral por WhatsApp e notificações unificadas faltam |
| Consolidação | `PARCIAL` | Precisa de máquina de estados e read model duráveis antes da formação |
| UV e CD | `AUSENTE COMO MÓDULOS` | Exigem PRDs próprios, dados, APIs, permissões e UX |
| Broadcast, Brevo e Asaas real | `GATES OPERACIONAIS` | Missões independentes; nenhuma é liberada pela evolução do agente |
| Auditoria D1 | `CONCLUÍDA / D1A EM DEV` | Quatro gaps foram corrigidos pela PR #311; migration aplicada somente em DEV, sem alteração de PROD |

O canário ativo citado acima recebeu apenas as mensagens sintéticas `Olá`,
`Aceito` e `Quero conhecer a igreja`. O operador relatou três entradas, três
saídas, autoria correta, filas canônicas vazias e restauração dos gates, além de
respostas robóticas e repetitivas. Esse relato não prova de forma independente
isolamento cross-tenant, ausência de tool call ou ausência de mutação de
domínio. A fonte operacional é o
[`POST-V1-MISSION-REGISTER.md`](../ops/POST-V1-MISSION-REGISTER.md) atualizado
nesta mesma missão.

## Arquitetura alvo aprovada

O PastorAI terá uma definição global e versionada de LangGraph, reutilizada por
todas as igrejas. Ela conterá um orquestrador e subgrafos especialistas, com a
mesma política central para cada tenant. O que varia por igreja é:

- dados e documentos oficiais;
- memória privada das conversas;
- responsáveis, horários e políticas operacionais;
- credencial OpenAI BYO e configuração inativa até gate nominal.

O servidor cria o contexto confiável com igreja, conversa, Pessoa, papéis,
capacidades e consentimentos. O modelo nunca escolhe ou altera esse contexto.
Nenhum especialista envia diretamente: ele devolve um resultado estruturado ao
grafo pai, que aplica políticas e produz uma única resposta externa.

## Memória e conhecimento

Memória não é sinônimo de fonte oficial:

1. o histórico completo da conversa permanece privado até a pessoa solicitar
   exclusão e o admin aprovar no painel;
2. um resumo incremental e trechos recentes fornecem continuidade sem enviar
   todo o histórico ao modelo em cada turno;
3. registros do sistema e documentos aprovados e versionados formam o
   conhecimento oficial da igreja;
4. mensagens privadas nunca são promovidas automaticamente para a base
   institucional;
5. quando faltar informação confirmada, o agente declara a lacuna e a atribui
   ao responsável configurado pelo setor.

A exclusão precisa remover mensagem, mídia, transcrição, resumo, checkpoint e
vetores derivados. Pode permanecer apenas auditoria mínima sem conteúdo ou
identificador desnecessário.

## Ações e consentimentos

Haverá consentimentos independentes para:

- atendimento solicitado;
- cuidado pastoral;
- tarefas operacionais;
- comunicados.

Ações comuns podem ser concluídas pelo WhatsApp após resumo estruturado e
confirmação explícita. Ações sensíveis terminam no painel autenticado. Toda
escrita revalida tenant, identidade, papel, capacidade e estado do domínio no
momento da execução, usa idempotência e confirma sucesso somente após commit.

A primeira fatia vertical é o relatório de célula: lembrete após a reunião,
coleta por texto ou áudio, resumo, correção, confirmação, gravação no fluxo
canônico de `celula_reuniao` e comprovante no WhatsApp.

## Invariantes

- Tenant é resolvido pela instância Evolution e validado no servidor.
- Telefone ajuda a identificar a Pessoa, mas não autoriza ações sensíveis.
- Conversas e dados pastorais são privados por padrão.
- Ferramentas do agente usam os mesmos serviços de domínio do painel.
- Ausência de informação oficial produz resposta honesta, nunca invenção.
- OpenRouter não integra o PastorAI. A credencial da igreja é OpenAI BYO.
- `AgentConfig.ativo` e os quatro gates externos permanecem fechados fora de
  canário nominalmente autorizado.

## Sequência corrente da fundação

A PR #313 integrou a D2A no histórico do SHA auditado. Ela continua inativa. A
integração não aplicou migration em ambiente compartilhado, não provisionou
credencial, não conectou o worker ou o LangGraph, não fez deploy manual ou do
backend, não promoveu a produção e não ativou o agente. O único deploy associado
à D2A foi o preview automático da PR, que não prova execução do backend nem
ambiente compartilhado.

Sobre o `origin/main` auditado, a candidata D2B1 adiciona somente um contrato
Python stateless: `TrustedAgentContext` imutável, separado do `AgentState` por
`StateGraph.context_schema`, validado antes do grafo, do caminho direto e em
cada node. O estado mutável rejeita chaves de autoridade e mantém apenas os
dados mínimos necessários ao turno. O contexto preserva a mesma instância de
`PrivilegeContext` que o executor de tools utiliza. A candidata passou em 224
testes focais e recebeu duas passagens adversariais com os achados P1 fechados e
parecer `GO`. A suíte offline completa local ficou `INCONCLUSIVA`: a baseline
limpa no mesmo SHA também excedeu 90 segundos no módulo TestClient inalterado
`test_agent_config_requests.py`. O workflow `Backend Tests` da PR precisa
executar a suíte integral e concluir verde antes da integração.

As fatias permanecem nesta ordem:

1. `D2B1`: candidata offline, aguardando suíte completa e integração;
2. `D2B2`: consentimentos independentes por finalidade, bloqueada até o merge
   da D2B1;
3. `D2C`: propostas duráveis, confirmação, expiração e idempotência;
4. `D3`: memória privada durável, recuperação seletiva e exclusão integral.

Universidade da Vida e Capacitação Destino permanecem na visão futura, mas
estão excluídas da missão atual e não podem ser inferidas dos placeholders.
A D2B1 não adiciona migration, não acessa Supabase, não provisiona credencial,
não conecta a fronteira privada D2A, worker, fila ou checkpointer, não faz
deploy, não ativa o agente e não executa canário. Esta sequência não autoriza
qualquer ação operacional.

## Roteiro de leitura

| Tarefa | Leia primeiro |
|---|---|
| Estado geral e pendências | [`auditoria D1`](../audits/2026-08-27-d1-security-scope-audit.md), [`auditoria fonte de verdade`](../audits/2026-08-27-project-source-of-truth.md), depois [`docs/WIKI-IGREJA12.md`](../WIKI-IGREJA12.md) |
| Escopo e definição de pronto | [`docs/ai/PRD-COVERAGE.md`](PRD-COVERAGE.md) |
| Agente WhatsApp-first | [`decisão de arquitetura`](../decisions/2026-08-27-whatsapp-first-tenant-agent-architecture.md) |
| Produção ou canário | `docs/ops/POST-V1-MISSION-REGISTER.md` e runbook específico |
| Produto e UX | `PRODUCT.md`, PRD canônico e `Plan-Designer-Igreja12/` |
| Banco e RLS | models, migration aplicável, policies e testes RLS |
| História | decisões, sprints e PRDs históricos, sem tratá-los como estado atual |

## Checklist inicial

1. execute `git status --short --branch` e `git rev-parse HEAD`;
2. compare o SHA com este snapshot;
3. classifique a tarefa como código, documentação ou operação externa;
4. leia a matriz do domínio afetado;
5. identifique dados privados, limites de tenant e efeitos externos;
6. fixe critérios de aceite, testes e rollback;
7. não infira deploy, migration, flag ou saúde a partir do Git.

## Manutenção

Atualize `last_verified` e `audited_repository_sha` somente após conferir o novo
SHA. Se código, documentação e produção divergem, descreva cada estado
separadamente e consulte novamente a fonte correspondente.
