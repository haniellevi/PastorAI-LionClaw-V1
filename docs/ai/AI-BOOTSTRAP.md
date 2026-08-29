---
project: igreja12
document_kind: ai-bootstrap
status: canonical
last_verified: 2026-08-28
audited_repository_sha: 04e5c1720bf89313718c4159a2ac9d0eeeed3c25
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
| Código | `VERIFICADO / LEDGER-BOOTSTRAP INTEGRADO E COMPROVADO OFFLINE / RECONCILIATION INTEGRADO E COMPROVADO OFFLINE / CAPTURADOR E MATERIALIZADOR INTEGRADOS / INVENTÁRIOS DEV E PROD CAPTURADOS, NÃO REVISADOS E BLOQUEADOS / DECISÕES HUMANAS PENDENTES / NÃO APLICADO / D2B2B3A INTEGRADA E INATIVA` | a PR #327 integrou o capturador/materializador e a PR #328 integrou o hotfix; seis artefatos sanitizados registram os dois ambientes em `EVIDENCE_CAPTURED_UNREVIEWED`, sem decisão humana nem autorização operacional; a captura somente leitura não aplicou migration, não executou runner, deploy ou runtime; D2B2B3A continua ausente nos bancos consultados e com flag `false` |
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

A implementação foi desenvolvida e comprovada offline sobre a base versionada
`b43ad92028374fa6763ef10f5eb7a379afd3e7a2`. O código integrado pela PR #323
adiciona o subcomando explícito e fail-closed
`bootstrap-ledger`, separado de `harden-ledger`. Ele exige
`--confirm BOOTSTRAP_LEDGER` antes da conexão e aceita o destino somente por
`M06_MIGRATION_DATABASE_URL`. Em PostgreSQL 17, cria em transação
`SERIALIZABLE` apenas o ledger vazio `public.schema_migrations`, com colunas,
chave primária e defaults exatos, owner estável, RLS, policy deny e ACL
owner-only. Conflitos de objeto, tipo, schema, ownership, grants, default
privileges, membership ou forma física falham com rollback; reaplicar o
contrato exato e vazio não produz mutação.

A verificação concluiu 42/42 testes unitários, 87/87 em PostgreSQL 17-alpine
descartável em duas execuções independentes e 87/87 em Supabase PG17
17.6.1.159 descartável em duas execuções independentes. A revisão de segurança
resultou em `GO`. A suíte RLS completa, em execução serial limpa no PostgreSQL
17 descartável, passou em 326/326, com 3803 deselecionados e 2 warnings
preexistentes, em 162.77s. A suíte offline integral foi interrompida após 5
min sem saída ou progresso; o resultado é `INCONCLUSIVO`, não verde nem falha
e não foi reclassificado. Os workflows Backend Tests da PR #323 e do pós-merge
concluíram com `SUCCESS`. O comando não descobre o catálogo, não consulta, copia ou
altera `supabase_migrations`, não faz backfill ou reconciliação e não aplica ou
registra migration. O ledger vazio mantém `status` e `apply` bloqueados até uma
reconciliação histórica humana formar o prefixo íntegro do catálogo, com no
máximo uma migration pendente.

O `bootstrap-ledger` está integrado em `main`, mas continua não aplicado. A PR
#323, HEAD `74d3f2d87a7ffad501432b2d9fc4163bd3b4ada4`, foi integrada pelo
merge `3a5789c784017ab15a43e28c4270d25af8618359` em
`2026-08-28T15:24:58Z`; seus cinco workflows e os cinco pós-merge concluíram
com `SUCCESS`. A Vercel registrou o Preview automático frontend `6143773477`,
com `SUCCESS`, em `2026-08-28T15:22:43Z`, e o Production automático frontend
`6143819601`, com `SUCCESS`, em `2026-08-28T15:25:43Z`. Essas metadatas provam
somente o frontend, sem provar backend, banco ou runtime. Não houve deploy
manual ou do backend, acesso aos bancos DEV ou PROD, bootstrap ou migration
compartilhada, restart ou alteração de credencial, flag, runtime, agente ou
canário. O preflight PROD e o deployment automático frontend da PR #321
permanecem evidências históricas separadas.

O pacote deny-state versionado e o verificador stdlib separado do runner,
desenvolvidos e comprovados offline sobre a base auditada
`cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`, foram integrados pela PR #325,
HEAD `d9595c3958fec98a875d15de2b6647d6b1de435e`, no merge
`ab7d09f07db96d5c63a2cc32dddf3f910e23bac2` em
`2026-08-28T20:18:08Z`, conforme
[`2026-08-28-migration-history-reconciliation-contract.md`](../decisions/2026-08-28-migration-history-reconciliation-contract.md).
O estado é `INTEGRADO / COMPROVADO OFFLINE / DECISÕES HUMANAS PENDENTES / NÃO
APLICADO`. A integração não acessou DEV ou PROD, não materializou inventário de ambiente ou
decisão humana e não reconciliou nenhum ledger. O verificador não acessa banco, rede,
ambiente ou variáveis de ambiente, não executa SQL, DML ou escrita e não
infere migration aplicada. Os ledgers nativo e público permanecem independentes
e todo sucesso estrutural conserva `OPERATIONAL_AUTHORIZATION=BLOCKED`.

Os workflows da PR concluíram com `SUCCESS`: Backend `33207468055`, E2E
`33207468044`, Frontend `33207468014`, RLS `33207468132` e Tooling
`33207468082`. Os pós-merge também concluíram com `SUCCESS`: Backend
`33207645381`, E2E `33207645348`, Frontend `33207645362`, RLS `33207645399` e
Tooling `33207645340`. A Vercel registrou o Preview automático frontend
`6147914118`, com `SUCCESS`, em `2026-08-28T20:16:00Z` no HEAD, e o Production
automático frontend `6147952424`, com `SUCCESS`, em `2026-08-28T20:18:55Z` no
merge. Essas metadatas provam somente o frontend, sem provar backend, banco ou
runtime; não houve deploy manual ou do backend, migration, bootstrap,
hardening, restart, flag ou runtime nesta missão.

A prova local preservada é `98/98` testes do verificador, `26/26` testes
documentais e `42/42` testes offline do runner: agregado de
`166 passed/45 skipped`. O template deny-state terminou bloqueado com exit `8`.

O capturador e o materializador foram integrados pela PR #327, HEAD
`c4f7a25b81a8091a0d74783c816a168bb7adf44d`, no merge
`f9201a06495fad138e313e4149ad9275ff896900`. A PR #328 integrou o hotfix, HEAD
`2cbdfaf39ae11d984f0aa27dfcf0910c25984840`, no merge
`04e5c1720bf89313718c4159a2ac9d0eeeed3c25`. O catálogo de base
`656d1d9eebe90ad4b2cbb35c21939a6796c46bfe` contém 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`; o SQL
allowlisted tem SHA-256
`8b589e5dda722691fead34cbd63cab75a7a22f32e0cf4bdfe64d6cef603866ee`.

O estado é `INVENTÁRIOS DEV E PROD CAPTURADOS / NÃO REVISADOS / BLOQUEADOS /
DECISÕES HUMANAS PENDENTES / NÃO APLICADO`. Em PostgreSQL 17, DEV registrou
33 linhas no ledger público e 6 no nativo em
`2026-08-28T22:43:11.454382Z`; PROD registrou o ledger público
`ABSENT_CONFIRMED`, com 0 linhas, e 32 linhas no nativo em
`2026-08-28T22:47:43.965243Z`. `native.name` permaneceu sempre `null`. Os dois
pacotes estão em `EVIDENCE_CAPTURED_UNREVIEWED`; cada verificação terminou com
exit `8`, `HUMAN_EVIDENCE_BLOCKED`, e a checagem conjunta terminou
`CROSS_PACKAGE_OK`. A matriz focal offline pós-captura passou com `163 passed,
2 skipped` em `1.40s`; isso não é suíte integral nem reexecução PostgreSQL.

A captura ocorreu somente em leitura e não executou DML, runner,
`bootstrap-ledger`, `harden-ledger`, `status`, `apply`, deploy, flag ou runtime.
Os seis artefatos permanecem bloqueados e não provam decisão humana, migration
aplicada, prefixo reconciliado ou autorização operacional.

O próximo gate único é uma revisão humana offline independente dos pacotes e
das evidências, sem nova consulta a DEV ou PROD e sem liberar o runner. O gate
não autoriza DML, `bootstrap-ledger`, `harden-ledger`, `status`, `apply`, deploy,
flag ou runtime. Universidade da Vida e Capacitação Destino permanecem fora.

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
