---
project: igreja12
document_kind: ai-bootstrap
status: canonical
last_verified: 2026-08-28
audited_repository_sha: bce5a9a434077e488cea8baae3e9dd7c7c4ba0f1
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
| Código | `VERIFICADO / D2B2A INTEGRADA E INATIVA / D2B2B1 CANDIDATA` | `origin/main` em `bce5a9a434077e488cea8baae3e9dd7c7c4ba0f1`; D1A, D2A, D2B1 e D2B2a integradas; D2B2a segue sem caller ou aplicação em Supabase; D2B2b1 é código puro e deny-first |
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

O contrato aprovado mantém consentimentos independentes para:

- atendimento solicitado;
- cuidado pastoral;
- tarefas operacionais;
- comunicados.

A D2B2a integrada materializa somente o ledger append-only dessas finalidades,
com estados `concedido|retirado` e fontes
`whatsapp_inbound|painel_autenticado`. Ela ainda não conecta WhatsApp, painel,
worker, LangGraph ou qualquer outro writer, e a migration não foi aplicada em
Supabase. A candidata D2B2b1 acrescenta uma fronteira pura, sem migration ou
caller: chave idempotente opaca gerada no servidor, RBAC deny-first e toda
tentativa de `concedido` recusada.

Texto e versão, hipótese jurídica, prova, política para menores, retenção,
eliminação, transferência internacional, opt-out e responsáveis por direitos e
incidentes não podem ser inventados pelo código. O pacote por finalidade exige
aprovação humana e validação jurídica ou do encarregado antes de catálogo,
evidence store ou writer.

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

A PR #315 integrou a D2B1 no `origin/main`
`84c5b71b415340868c1b0664e892b8b0350d91f4`. O contrato continua
deliberadamente stateless: `TrustedAgentContext` imutável, separado do
`AgentState` por `StateGraph.context_schema`, validado antes do grafo, do
caminho direto e em cada node. O estado mutável rejeita chaves de autoridade e
mantém apenas os dados mínimos necessários ao turno. O contexto preserva a
mesma instância de `PrivilegeContext` que o executor de tools utiliza.

No merge, a suíte offline concluiu com 2.770 testes aprovados e 278
deselecionados; a suíte RLS concluiu com 278 aprovados e zero skips. Os cinco
workflows da PR e os cinco pós-merge ficaram verdes. Essas evidências provam o
comportamento exercitado no código integrado, sem provar migration, ambiente
compartilhado, deploy ou ativação.

No `origin/main`
`bce5a9a434077e488cea8baae3e9dd7c7c4ba0f1`, a PR #317, HEAD
`8ba5c988e9169703c923b1f1a3e47d1c427531e1`, integrou a D2B2a com
migration, ORM, domínio e serviço interno sem caller para
`public.consentimento_finalidade_evento`. O ledger é append-only, usa
`versao_termo`, idempotência por tenant e sequência por stream atribuída em
trigger sob advisory lock transacional. A RLS é habilitada e forçada, com
barreira restritiva dependente somente de `app.tenant_igreja_id` e ACL mínima.

Não existe backfill: consentimento legado não concede as quatro finalidades e o
opt-out global continua prevalecendo. A fundação não foi aplicada em
PostgreSQL compartilhado ou Supabase, não expõe API e não conecta runtime,
painel, webhook, worker, tool ou LangGraph. Ela também não faz deploy, ativação
ou canário.

Os cinco workflows da PR #317 e os cinco pós-merge concluíram com `SUCCESS`.
O Vercel executou somente preview automático, sem backend ou ambiente
compartilhado. Essa evidência prova integração e CI, não aplicação da migration
nem estado operacional.

As fatias permanecem nesta ordem:

1. `D2B1`: integrada no código e ainda sem aplicação operacional;
2. `D2B2a`: integrada no código e inativa, sem caller ou aplicação em
   Supabase. A PR #317 e os cinco workflows pós-merge ficaram verdes;
3. `D2B2b1`: candidata de código puro, sem migration ou caller, com chave opaca
   server-side, RBAC deny-first e toda concessão negada. Não há reidratação por
   valor; retry entre processos depende de futuro recibo durável autenticado.
   Os indicadores de escopo ainda exigem builder server-side vinculado ao
   recurso antes de qualquer caller. O recorte focal passou em 1.114 de 1.114 e
   a suíte RLS completa, em 288 de 288 contra PostgreSQL 17
   descartável; Backend Tests integral permanece gate do merge;
4. pacote humano e jurídico aprovado por finalidade;
5. somente depois, em fatia própria, catálogo imutável, prova correlacionada,
   retenção, eliminação, RBAC e writers server-side seguros;
6. `D2C`: propostas duráveis, confirmação, expiração e idempotência;
7. `D3`: memória privada durável, recuperação seletiva e exclusão integral.

Universidade da Vida e Capacitação Destino permanecem na visão futura, mas
estão excluídas da missão atual e não podem ser inferidas dos placeholders.
A D2B1 não adicionou migration, não acessou Supabase, não provisionou
credencial, não conectou a fronteira privada D2A, worker, fila ou checkpointer,
não fez deploy manual ou do backend, não promoveu a produção, não ativou o
agente e não executou canário. O preview automático da PR não prova execução do
backend. O único gate posterior a esta PR é obter e registrar o pacote humano e
jurídico aprovado para cada finalidade. Catálogo, evidence store, writer,
Supabase DEV ou PROD e D2C permanecem bloqueados até esse gate.

## Roteiro de leitura

| Tarefa | Leia primeiro |
|---|---|
| Estado geral e pendências | [`auditoria D1`](../audits/2026-08-27-d1-security-scope-audit.md), [`auditoria fonte de verdade`](../audits/2026-08-27-project-source-of-truth.md), depois [`docs/WIKI-IGREJA12.md`](../WIKI-IGREJA12.md) |
| Escopo e definição de pronto | [`docs/ai/PRD-COVERAGE.md`](PRD-COVERAGE.md) |
| Agente WhatsApp-first | [`decisão de arquitetura`](../decisions/2026-08-27-whatsapp-first-tenant-agent-architecture.md) |
| Consentimento por finalidade | [`decisão D2B2a`](../decisions/2026-08-28-d2b2-purpose-consent-ledger.md) e [`fronteira D2B2b1`](../decisions/2026-08-28-d2b2b1-consent-security-boundary.md) |
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
