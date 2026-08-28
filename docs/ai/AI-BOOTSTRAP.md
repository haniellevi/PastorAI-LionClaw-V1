---
project: igreja12
document_kind: ai-bootstrap
status: canonical
last_verified: 2026-08-28
audited_repository_sha: 15deaf88fd4cab5b4bebdd1435a81c8b33c2b159
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

| Tema | Estado e proveniência | Leitura correta |
|---|---|---|
| V1 | `IMPLEMENTADO` | Encerrada como piloto controlado; não equivale ao produto amplo concluído |
| Código | `VERIFICADO / D2B2B3A INTEGRADA E INATIVA` | baseline auditada `15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`; a implementação D2B2b3A veio do merge #320 `947d891c2ea278b7a3231fecd9ca1c90cfe29a1f`; esta missão não aplicou a migration D2B2b3A, e DEV e PROD confirmaram a ausência; a flag segue `false` e o backend não foi implantado |
| Produto WhatsApp-first | `PARCIAL` | A visão está aprovada; memória, conhecimento e ações profundas ainda faltam |
| Agente Evolution | `PARCIAL / GATE OPERACIONAL` | Fundação, identidade e contenção existem; qualidade conversacional é insuficiente |
| Canário ativo do agente | `PASS TÉCNICO / QUALIDADE INSUFICIENTE` | Evidência operacional reconciliada nesta missão, não prova previamente versionada em `ad4a272` |
| LangGraph | `IMPLEMENTADO STATELESS` | Grafo único e fallback determinístico, sem checkpoint durável |
| Conhecimento institucional | `AUSENTE` | Não existe RAG com documentos aprovados nem consulta institucional ampla |
| Governança de consentimento | `D2B2B3A INTEGRADA / DRAFT-ONLY INATIVA` | A superfície de rascunhos por igreja está integrada no código; o Master não pode decidir hipótese jurídica, atestar, aprovar ou registrar papéis nominais; esta missão não aplicou schema em banco compartilhado nem ativou backend ou runtime compartilhado, mas consultou metadados de DEV e PROD em modo somente leitura, sem mutação, e o merge gerou deployment automático do frontend Vercel Production |
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
Supabase. A D2B2b1 integrada acrescenta uma fronteira pura, sem migration ou
caller: chave idempotente opaca gerada no servidor, RBAC deny-first e toda
tentativa de `concedido` recusada.

Texto e versão, hipótese jurídica, prova, política para menores, retenção,
eliminação, transferência internacional, opt-out e responsáveis por direitos e
incidentes não podem ser inventados pelo código. O pacote por finalidade exige
aprovação humana e validação jurídica ou do encarregado antes de catálogo,
evidence store ou writer.

A D2B2b3A integra uma superfície administrativa estritamente draft-only no
Console Master. O Master autenticado pode organizar fatos e campos de rascunho
para cada finalidade e igreja, com tenant e ator derivados no servidor. E-mail
não é autoridade nem configuração do tenant. Hipótese jurídica, declaração de
operação baseada em consentimento, decisão sobre menores, atestado, parecer,
aprovação, digest atestado e registros nominais ficam fora da edição. Todo
rascunho operacional continua `DRAFT_NOT_APPROVED`; existem somente callers
administrativos de rascunho, sem caller de aprovação, ledger ou runtime.

No baseline `15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`, o preflight PROD
somente leitura confirmou `DATABASE_URL` presente e
`M06_MIGRATION_DATABASE_URL` ausente. `current_user` e `session_user`
convergiram para a mesma identidade sanitizada; a role runtime possui
`NOSUPERUSER`, `BYPASSRLS`, `LOGIN` e `INHERIT`, é owner de `public.igrejas` e
`public.app_users` e possui `SELECT` e `REFERENCES` efetivos nessas tabelas-pai.
A tabela alvo D2B2b3A, o validator e a própria `public.schema_migrations`
estavam ausentes. A flag `PURPOSE_CONSENT_GOVERNANCE_DRAFTS_ENABLED` permaneceu
`false`. Esta missão não aplicou a migration D2B2b3A; DEV e PROD confirmaram a
ausência. A PR #321 integrou a reconciliação documental anterior no merge
`15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`; esse merge gerou o deployment
automático Vercel frontend Production `6141449639`, com `SUCCESS`, em
2026-08-28T12:53:35Z. Essa metadata prova somente o frontend, sem provar backend,
banco ou Supabase. O preflight VPS em si não executou deploy manual ou do
backend, migration, restart ou alteração da flag. A leitura comprova identidade,
ownership e ACL do caminho runtime atual, mas não o comportamento da tabela
futura sob `FORCE RLS`; o caminho de migration permanece bloqueado pela ausência
de `M06_MIGRATION_DATABASE_URL` e do ledger público.

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

No histórico do `origin/main`, a PR #317, HEAD
`8ba5c988e9169703c923b1f1a3e47d1c427531e1`, integrou a D2B2a com
o merge `bce5a9a434077e488cea8baae3e9dd7c7c4ba0f1`, incluindo
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
A PR gerou Preview automático e o merge em `main` gerou deployment frontend
Vercel classificado como Production. Não houve deploy manual ou do backend, e
essa metadata prova somente o deployment do frontend no ambiente Production
da Vercel; não prova backend, banco, aplicação da migration em Supabase nem o
estado operacional desses componentes.

A PR #318, HEAD `ede4797003e044f582da9f9a3ab86554f708a73a`, integrou a
D2B2b1 no merge `74951828f48994622a112d8e59eb978e5fb4f406`. O recorte focal
passou em 1.114 de 1.114, a suíte RLS em 288 de 288 contra PostgreSQL 17
descartável e o workflow Backend Tests aprovou a suíte integral. Os cinco
workflows da PR e os cinco pós-merge ficaram verdes. A PR gerou Preview e o
merge gerou deployment frontend Vercel automático classificado como
Production; não houve deploy manual ou do backend, migration, Supabase,
ativação ou canário. O PostgreSQL temporário foi removido.

A PR #320, HEAD `66ce06d9a356a52e63366b3a6528b0b83170d12e`, integrou a
D2B2b3A no merge `947d891c2ea278b7a3231fecd9ca1c90cfe29a1f`. A fatia inclui
migration versionada, persistência, API e workspace do Console Master somente
para rascunhos, com tenant e ator derivados no servidor, revisão otimista,
auditoria sem payload e estado fixo `DRAFT_NOT_APPROVED`. Os cinco workflows da
PR e os cinco pós-merge concluíram com `SUCCESS`. O merge gerou o deployment
automático Vercel frontend Production `6140373952`, também com `SUCCESS`; essa
metadata prova somente o frontend nesse ambiente. Esta missão não aplicou a
migration D2B2b3A; DEV e PROD confirmaram a ausência. A flag
`PURPOSE_CONSENT_GOVERNANCE_DRAFTS_ENABLED` permanece `false`, e não houve
deploy manual ou do backend, wiring, ativação ou canário.

As fatias permanecem nesta ordem:

1. `D2B1`: integrada no código e ainda sem aplicação operacional;
2. `D2B2a`: integrada no código e inativa, sem caller ou aplicação em
   Supabase. A PR #317 e os cinco workflows pós-merge ficaram verdes;
3. `D2B2b1`: integrada e inativa, código puro sem migration ou caller, com
   chave opaca server-side, RBAC deny-first e toda concessão negada. Não há reidratação por
   valor; retry entre processos depende de futuro recibo durável autenticado.
   Os indicadores de escopo ainda exigem builder server-side vinculado ao
   recurso antes de qualquer caller. A PR #318 e os cinco workflows pós-merge
   ficaram verdes;
4. `D2B2b3A`: integrada e inativa, com persistência, API e painel do Console
   Master limitados a rascunhos por igreja, sem aprovação e sem aplicação em
   Supabase compartilhado;
5. pacote humano e jurídico aprovado por finalidade, em fluxo nominal futuro;
6. somente depois, em fatia própria, catálogo imutável, prova correlacionada,
   retenção, eliminação, RBAC e writers server-side seguros;
7. `D2C`: propostas duráveis, confirmação, expiração e idempotência;
8. `D3`: memória privada durável, recuperação seletiva e exclusão integral.

O formulário vazio e sem autoridade de runtime está em
[`D2B2b2`](../decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md).
Ele organiza o conteúdo. A fronteira draft-only do Console Master está em
[`D2B2b3A`](../decisions/2026-08-28-d2b2b3-master-governance-drafts.md) e não
satisfaz o gate humano.

Universidade da Vida e Capacitação Destino permanecem na visão futura, mas
estão excluídas da missão atual e não podem ser inferidas dos placeholders.
A D2B1 não adicionou migration, não acessou Supabase, não provisionou
credencial, não conectou a fronteira privada D2A, worker, fila ou checkpointer,
não fez deploy manual ou do backend, não promoveu a produção, não ativou o
agente e não executou canário. O preview automático da PR não prova execução do
backend.

O próximo gate único é implementar e testar somente em PostgreSQL 17
descartável, sem acessar DEV ou PROD, um subcomando versionado
`bootstrap-ledger`, explícito e fail-closed, separado de `harden-ledger`. Ele
criará, em transação única, exclusivamente o contrato final vazio de
`public.schema_migrations`, como ledger vazio, com colunas, chave primária (PK) e defaults exatos,
RLS habilitada, policy deny e ACL mínima por grants e revokes explícitos. O comando
validará ownership e roles esperados antes e depois, e abortará se houver objeto
homônimo, schema divergente ou qualquer outro conflito. A reaplicação deverá
encerrar sem mutação; testes adversariais em PostgreSQL 17 cobrirão conflitos
homônimos, falha parcial e rollback integral. O comando operará sem reconciliação
ou backfill: jamais copiará
`supabase_migrations`, inferirá migrations aplicadas ou autorizará `apply`.
`apply` e `status` permanecerão tecnicamente bloqueados até uma reconciliação
humana versionada formar o prefixo íntegro do catálogo, com no máximo uma
migration pendente; o bootstrap não pode reduzir a barreira atual.
Qualquer preenchimento ou reconciliação histórica humana será uma missão
separada, baseada em evidência, e precisará terminar antes de considerar D2 em
DEV ou PROD. Este gate entrega somente a PR offline do bootstrap e não autoriza
painel do tenant, aprovações, catálogo, writer, migration D2B2b3A, flag, D2C,
credencial, wiring, deploy, restart, runtime, ativação ou canário.

## Roteiro de leitura

| Tarefa | Leia primeiro |
|---|---|
| Estado geral e pendências | [`auditoria D1`](../audits/2026-08-27-d1-security-scope-audit.md), [`auditoria fonte de verdade`](../audits/2026-08-27-project-source-of-truth.md), depois [`docs/WIKI-IGREJA12.md`](../WIKI-IGREJA12.md) |
| Escopo e definição de pronto | [`docs/ai/PRD-COVERAGE.md`](PRD-COVERAGE.md) |
| Agente WhatsApp-first | [`decisão de arquitetura`](../decisions/2026-08-27-whatsapp-first-tenant-agent-architecture.md) |
| Consentimento por finalidade | [`decisão D2B2a`](../decisions/2026-08-28-d2b2-purpose-consent-ledger.md), [`fronteira D2B2b1`](../decisions/2026-08-28-d2b2b1-consent-security-boundary.md), [`template D2B2b2`](../decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md) e [`rascunhos D2B2b3A`](../decisions/2026-08-28-d2b2b3-master-governance-drafts.md) |
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
