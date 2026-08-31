---
project: igreja12
document_kind: ai-bootstrap
status: canonical
last_verified: 2026-08-31
audited_repository_sha: fb776e270bf3e2ffde0cbb28e400960591b74420
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
| Código | `VERIFICADO / LEDGER-BOOTSTRAP INTEGRADO E COMPROVADO OFFLINE / RECONCILIATION INTEGRADO E COMPROVADO OFFLINE / CAPTURADOR E MATERIALIZADOR INTEGRADOS / ARTEFATOS VERSIONADOS / REVISÃO INDEPENDENTE BLOQUEADA CONCLUÍDA / DECISÃO OWNER-01 REGISTRADA / MANIFESTO DE FONTE CRIADO / REVISÃO TÉCNICA CONCLUÍDA / REVISÃO INDEPENDENTE DO MANIFESTO PENDENTE / NÃO APLICADO / D2B2B3A INTEGRADA E INATIVA` | a revisão externa classificou DEV como `BLOCKED_LEDGER_DIVERGENCE` e PROD como `BLOCKED_EVIDENCE_INSUFFICIENT`; o manifesto atual descreve somente a expectativa da fonte versionada; os pacotes continuam `EVIDENCE_CAPTURED_UNREVIEWED`, sem migration, runner, deploy ou runtime; D2B2B3A continua ausente nos bancos consultados e com flag `false` |
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

O estado é `INVENTÁRIOS DEV E PROD CAPTURADOS / REVISÃO INDEPENDENTE BLOQUEADA
CONCLUÍDA / DECISÃO OWNER-01 REGISTRADA / NÃO APLICADO`. Em PostgreSQL 17, DEV registrou
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

A PR #329 integrou e versionou os seis artefatos, com HEAD
`c5ae430aa865dbd6371953d43e4a4447ca8e6618`, no merge
`341f38a7f1c6993c74d85e99748cb60046cd4501` em `2026-08-29T00:04:50Z`. Os
cinco workflows da PR e os cinco pós-merge concluíram com `SUCCESS`. O merge
gerou o deployment automático Vercel frontend Production `6150482852`, com
`SUCCESS`, em `2026-08-29T00:05:33Z`. Essa metadata prova somente o frontend,
sem provar deploy manual ou do backend, banco ou runtime. A integração versiona
a evidência sanitizada já capturada, mas não revisa os inventários, não aplica
migration e não libera o runner ou qualquer autorização operacional.

A revisão de `REVIEWER-01`, vinculada pelo SHA-256
`18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133`,
bloqueou DEV por divergência do ledger e PROD por evidência insuficiente.
`OWNER-01` aceitou o bloqueio no registro externo de SHA-256
`0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240`,
manteve `operational_authorization=false` e autorizou somente a proposta
técnica offline. Os registros externos não foram versionados e os pacotes
continuam bloqueados.

O manifesto estático de expectativas da fonte foi criado sobre a base
`7f18f7e8b44cd50e6f6033867fb97bfa9eb9c9e6`. Ele fixa 75 migrations e o
digest `84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`,
mas declara `SOURCE_LEVEL_EXPECTATION_ONLY`: não prova o schema final de DEV ou
PROD. O verificador terminou em
`SCHEMA_EXPECTATION_MANIFEST_VERIFIED_SOURCE_ONLY`, com
`OPERATIONAL_AUTHORIZATION=BLOCKED` e
`ENVIRONMENT_ATTESTATION_COMPLETE=false`. A revisão técnica foi feita pelo
mesmo executor e não é independente.

A derivação canônica foi reproduzida e verificada somente offline, duas vezes,
em PostgreSQL 17 descartável, sobre a base
`07d2c05c687d1a0e8deeacbb7f8b16fbdd0e4e86`. As execuções A e B produziram os
mesmos 388390 bytes, o SHA-256
`7040a54d80c0ee4f37e1986ff0a579db275e45c129f4fdafcd66788e22a3eb3e` e o
fingerprint `8ac17d4352a77fb3c5885f9c1a55813a5b7dfcd6fb84c4bd4e9117c1c7883370`.
O estado, as provas e os limites estão na
[`decisão de derivação offline`](../decisions/2026-08-29-offline-canonical-schema-derivation.md).
Isso não atesta DEV, PROD, Data API ou Realtime; `OPERATIONAL_AUTHORIZATION=BLOCKED`
permanece obrigatório.

A PR #334, HEAD `a864730f0b678cca39cebfa6bb378243ba031cd6`, foi integrada no
merge `c8427b1a505c0aad2a5f675d3bf456ee33716690`; o Git registra
`commit date=2026-08-29T21:21:15Z`, e o GitHub registra
`mergedAt=2026-08-29T21:21:16Z`. Os seis checks da PR e os seis pós-merge
concluíram com `SUCCESS`; os detalhes da API do deployment automático Vercel
frontend Production `6160229001` estão na evidência detalhada em
[`decisão de derivação offline`](../decisions/2026-08-29-offline-canonical-schema-derivation.md).
Os checks provam apenas o comportamento exercitado naquele SHA; a metadata do
deployment prova somente o frontend e não prova backend, banco, migration,
runtime ou atestação de ambiente.

A ferramenta separada de atestação read-only foi implementada no commit técnico
`be958ce96e65d3d497923b7f5f912676634e9587`, sobre a base
`1072e6a8e85d201a1c82f37a8ddeac5417300c49`. A prova focal offline passou em
`81/81`, a seleção relacionada terminou em `367 passed, 47 skipped` e a prova
focal em PostgreSQL 17 TLS descartável passou em `82/82`. Sarah/Terra concluiu
`GO`; o healthcheck do Claude Opus passou, mas a revisão completa travou com
`Execution error` e não foi reclassificada como revisão concluída.

A PR #337, HEAD `abf6f823336b81e93ec1c942dcd5a357d8ac797c`, integrou o tooling
no merge `278afb205a3b4735d4aeb66e2e585f71fd562ef7`, com
`mergedAt=2026-08-30T11:38:16Z`. Os sete workflows do push em `main`
concluíram com `SUCCESS`: Environment Attestation PG17 `33309430738`, Frontend
CI `33309430763`, Canonical Schema Derivation `33309430775`, Backend Tests
`33309430797`, Tooling Static Checks `33309430744`, E2E Critical `33309430731`
e RLS Integration `33309430799`.

A Vercel registrou o deployment frontend Production `6166209567`, com
`state=success`; o deployment e seu status registraram
`created_at=2026-08-30T11:39:02Z`. Essa metadata prova somente o frontend e não
prova backend, banco ou runtime. O estado corrente é
`INTEGRADO E COMPROVADO OFFLINE / AMBIENTES NÃO CONSULTADOS / OPERAÇÃO BLOQUEADA`.

O tooling integrado permanece fail-closed, conforme a
[`decisão de atestação read-only`](../decisions/2026-08-30-read-only-environment-attestation-tooling.md).
Nenhum DEV ou PROD foi consultado e nenhum artefato ambiental foi produzido.
O schema JSON valida somente o envelope; o verificador Python continua
obrigatório. O HMAC serve para correlação e anti-swap, sem substituir
autorização humana nem observar diretamente o project ref. Data API e Realtime
permanecem `PLATFORM_SURFACES_UNATTESTED`.

`OPERATIONAL_AUTHORIZATION=BLOCKED` e
`environment_attestation_complete=false` permanecem invariantes. Runner, DML,
migration, reconciliação, backfill, deploy, flag e runtime continuam
bloqueados.

Sobre a base versionada `fe7dcd394bd1cfdc96204ad994bcba9f0c96adb4`, o runner
DEV preflight-only foi implementado e comprovado offline antes da integração.
Os SHA-256
congelados são: runner
`1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f`, testes
unitários `d96fab1afe99531e3cee0f84bc285876de303ed0265fa41c51f8da9a7bcab0a0`,
prova PG17 `ceecfe9afa09066e4863e93be556b8f92c00a2992e0a0aef3b4253458f6fc318`,
testes de atestação existentes
`68f9790a734f8adf78db8a716a5c2d99adad165f00737f922db90afa614b4ed8` e
workflow `80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf`.
Os unitários passaram em `210/210`; duas provas locais sequenciais no
PostgreSQL 17 TLS passaram em `1/1` para a atestação existente e `1/1` para o
runner com CA por FD.

A PR #340, HEAD `b29d3f494eabc3a04fe7f2c434758ad274f03930`, integrou o
runner no merge `82413edb884125d4d8f6e7946ffcaaf48ed8491c`, com
`mergedAt=2026-08-30T13:55:11Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: E2E `33315460948`, Frontend `33315460933`, Tooling
`33315460941`, RLS `33315460942`, Backend `33315460949`, Environment
Attestation PG17 `33315460934` e Canonical Schema Derivation `33315460939`.
A Vercel registrou o deployment frontend Production `6167369343`, com
`state=success`, em `2026-08-30T13:55:56Z`. Essa metadata prova somente o
frontend e não prova backend, banco ou runtime.

O contrato usa `TLS_MODE=VERIFY_FULL_EXPLICIT_CA` e exige que o digest da CA,
`TLS_CA_CERTIFICATE_SHA256`, esteja vinculado à autorização. O escopo
`PROCESS_INVOCATION_ONLY` exige nova autorização nominal para cada invocação.
O HMAC serve somente correlação e anti-swap e não substitui autorização humana.
O resultado produz zero arquivo, zero recibo, zero captura e zero
materialização. Os buffers de chave e nonce são zerados, os descritores são
fechados e os certificados TLS temporários são removidos após a prova. DEV e
PROD não foram consultados. PROD está explicitamente
fora. PROD continua fora. Estado:
`INTEGRADO E COMPROVADO OFFLINE / DEV/PROD NÃO CONSULTADOS / OPERAÇÃO
BLOQUEADA`.

Em 2026-08-30, já no `main`
`64cc157d649256a4a9819741f4276c0420590fd1`, duas invocações DEV foram feitas
sob autorizações humanas nominais distintas e exclusivas, cada uma limitada a
`PROCESS_INVOCATION_ONLY`. O timestamp operacional preciso não foi preservado;
nenhum horário UTC foi inferido. Ambas terminaram com exit `7`,
`RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED`, `ROLLBACK_CONFIRMED=false` e
`CONNECTION_CLOSED=true`. Em ambas, `OPERATIONAL_AUTHORIZATION=false`,
`NEXT_STAGE_AUTHORIZED=false`, `CAPTURE_EXECUTED=false`,
`MATERIALIZATION_EXECUTED=false` e `PROD_ACCESSED=false`. Esses campos não
provam se houve conexão, não provam sucesso ou falha de autenticação e não
identificam a causa raiz.

O diagnóstico posterior passou em `2/2` no caminho full-main sobre PostgreSQL
17 TLS descartável e em `97/97` no foco offline. O runner permaneceu intacto,
SHA-256 `1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f`,
assim como o workflow, SHA-256
`80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf`.
A prova PG17 ampliada tem SHA-256
`ddbc092216604e65cf86070d409837c7d328da96116ae5ea8d0947195b421b9e`.
Essa prova local não reclassifica DEV nem determina a causa do bloqueio. A
evidência detalhada está em
[`diagnóstico do preflight de identidade de DEV`](../decisions/2026-08-30-dev-identity-preflight-diagnostics.md).
Estado: `DUAS INVOCACOES DEV BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO
CONSULTADO / OPERACAO BLOQUEADA`.

A PR #342, HEAD `5076c47b19fffe503e823d68c6dadfc59b11ed5d`, integrou a
prova diagnóstica no merge `bc202da6c0ef83e03ded4392e508441cd4d6a188`, com
`mergedAt=2026-08-30T15:24:45Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Canonical `33319560819`, Environment Attestation PG17
`33319560923`, E2E `33319560908`, RLS `33319560769`, Backend `33319560836`,
Frontend `33319560781` e Tooling `33319560786`. A Vercel registrou o
deployment frontend Production `6168185324`, com status `17531418022`,
`state=success` e `created_at=updated_at=2026-08-30T15:25:32Z`. Essa metadata
prova somente o frontend e não prova backend, banco ou runtime.

A integração não repetiu o preflight, não consultou logs, não fez novo acesso a
DEV ou PROD e não determinou a causa do exit `7`. Runner e workflow permanecem
intactos. Estado: `INTEGRADO E COMPROVADO OFFLINE / DUAS INVOCACOES DEV
BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO CONSULTADO / OPERACAO
BLOQUEADA`.

Sobre a base `3685bbcaf11d5a20b3492953d897cb6a459701a8`, o candidato
pré-merge adiciona o enum estático `PREFLIGHT_FAILURE_PHASE` com dez valores:
`PRECONNECT_GUARDS`, `CONNECT_TLS_AUTH`, `SERVER_VERSION`, `SESSION_GUARDS`,
`IDENTITY_VALIDATION`, `ROLLBACK`, `CURSOR_CLOSE`, `CONNECTION_CLOSE`,
`POSTCONNECT_TLS_CA_REVALIDATION` e `POST_IDENTITY_FINALIZATION`. A fase é
somente a última fronteira operacional iniciada, nunca a causa; em especial,
`CONNECT_TLS_AUTH` não prova nem separa rede, TLS ou credencial. Cada saída
`BLOCKED` contém exatamente uma linha de fase, o sucesso não a contém e a
primeira falha vence quando há falhas posteriores.

Os SHA-256 congelados são runner
`8da631fbb602488bb8c82ce1529c9d8ba17acbae8a318ea9b0fc24cdd8f65cd2`,
unitários `c55726f0ad8abf7680de868cba155388f7e56773aa8054e556be89dc87aa90a8` e
PG17 `d86037d759d254581d2259026585ac768e4b2d68595473371ec65daf6c6de5a9`.
Passaram `109 passed, 2 skipped` offline, `2/2` em PostgreSQL 17 TLS
descartável e `222 passed, 2 skipped` no agregado relevante; `pycompile` e
`diff-check` ficaram verdes, os recursos temporários foram removidos e Sarah
concluiu `GO`, sem P0, P1 ou P2. As duas execuções DEV históricas com exit `7`
não podem ser retroclassificadas. A única `query_logs` anterior retornou vazio
e continua `EVIDENCE_INSUFFICIENT`. Esta missão não repetiu a consulta e não
acessou DEV ou PROD. A evidência detalhada está na
[`decisão de fase sanitizada`](../decisions/2026-08-30-dev-preflight-failure-phase-diagnostics.md).

O enum sanitizado foi integrado pela PR #344 no `main`
`bab031a7e0067a257eedb4a24c786cc925801463`. Em `2026-08-31`, uma terceira e
única invocação DEV `PROCESS_INVOCATION_ONLY` nesse `main` terminou com exit
`7`, `RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED` e
`PREFLIGHT_FAILURE_PHASE=CONNECT_TLS_AUTH`. A autorização era válida entre
`2026-08-31T11:03:30Z` e `2026-08-31T11:18:30Z`; essa janela não é o horário
da execução. O timestamp operacional preciso não foi preservado nem inferido.
DNS, TCP, TLS, CA, senha, autenticação, endpoint, disponibilidade, conexão,
transação e identidade permanecem `UNKNOWN`. A autorização foi consumida;
nenhum log foi consultado e não houve retry, captura, materialização, DML,
migration, backfill, deploy, flag, runtime ou acesso a PROD.
A limpeza removeu o diretório temporário de autorização, o launcher e a
worktree operacionais temporários; o checkout ficou limpo, sem `__pycache__` ou
`.pyc`, e o registro Git obsoleto da worktree foi removido.

O probe para separar somente DNS, TCP e TLS foi preparado offline e permanece
`execution_disabled=true`; ele não foi executado e não possui autorização viva.
O contrato e os limites estão na
[`decisão de 2026-08-31`](../decisions/2026-08-31-dev-connect-tls-auth-transport-probe.md).
`OPERATIONAL_AUTHORIZATION=false` e `NEXT_STAGE_AUTHORIZED=false` permanecem
obrigatórios.

A PR #346, HEAD `0c63dc29dc903e0e7012b9fb811b7b2ddb05ab51`, foi integrada no
merge `fb776e270bf3e2ffde0cbb28e400960591b74420`, com
`mergedAt=2026-08-31T13:02:07Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Tooling `33394774001`, Environment Attestation PG17 `33394774013`,
Canonical `33394773986`, E2E `33394774109`, Frontend `33394774063`, RLS
`33394773965` e Backend `33394774029`. A Vercel registrou o deployment
frontend Production `6181597461`, status `17569033825`, `state=success`, em
`2026-08-31T13:02:53Z`. Essa metadata prova somente o frontend e não prova
saúde funcional, backend, banco, DEV, PROD, probe ou migration. A integração
versionou apenas o plano offline: `execution_disabled=true`, implementação e
capacidade de rede ausentes, probe não executado e operação bloqueada.

A PR #347, HEAD `0a257e9aa1985860d5ea0a4506d4f7e84c7b2312`, foi integrada no
merge `36f8d13284a8f4964d0258a2a3b845323a80fe7e`, com
`mergedAt=2026-08-31T14:26:10Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`, e o deployment automático Vercel frontend Production `6183047421`,
status `17572803614`, terminou com `state=success` em
`2026-08-31T14:26:57Z`. Essa metadata prova somente o frontend.

Sobre esse merge, o candidato implementa o probe transport-only em
`backend/scripts/probe_dev_connect_tls_auth_transport.py`, SHA-256
`4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9`, e sua
matriz adversarial, SHA-256
`b79ff9d7473fdafd0a4fcd6ceba98b2c46f5470ef517b6663898812fe8b1296e`.
Passaram `90/90` testes exclusivamente offline, incluindo loopback TLS
sintético descartável. O runner recebe seis descritores privados, fixa o hash
do project-ref DEV e do registro de autorização, envia somente o SSLRequest
PostgreSQL de oito bytes, exige `S`, valida CA e hostname e fecha antes de
StartupMessage. Não recebe senha, usuário, banco ou DSN e não tenta
autenticação nem SQL. O plano JSON permanece histórico e byte-idêntico; seus
campos `execution_disabled=true` e `implementation_present=false` descrevem a
etapa anterior já consumida. A única rede desta rodada foi o `git fetch`
nominal autorizado para obter o merge; nenhum probe vivo, DEV, PROD, banco ou
log foi acessado. `operational_authorization=false` e
`next_stage_authorized=false` permanecem.

A PR #348, HEAD `af91e5218f9317a730aa29ad8d8c645312b30f19`, foi integrada no
merge `1e727cd2ea90ccfb68961174b802d595c71f355b`, com
`mergedAt=2026-08-31T15:22:49Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Tooling `33408103314`, Environment Attestation PG17 `33408103217`,
Canonical `33408103386`, Frontend `33408103193`, E2E `33408103279`, Backend
`33408103254` e RLS `33408103282`. A Vercel registrou o deployment automático
frontend Production `6184050276`, status `17575418445`, `state=success`, em
`2026-08-31T15:23:35Z`. Essa metadata prova somente o deployment do frontend,
não sua saúde funcional, e não prova backend, banco, DEV, PROD ou o probe. O
estado agora é `IMPLEMENTADO / INTEGRADO / COMPROVADO OFFLINE / PROBE NÃO
EXECUTADO / OPERAÇÃO BLOQUEADA`.

**Gate consumido em 2026-08-31:**
`SEPARATE_NOMINAL_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE_AUTHORIZATION`. Seu
consumo exige nova autorização humana nominal para exatamente uma invocação
`PROCESS_INVOCATION_ONLY` no checkout de `main` `1e727cd2`, com runner SHA-256
`4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9` e o
`source_main_git_sha=36f8d13284a8f4964d0258a2a3b845323a80fe7e` exigido pelo
contrato interno. Não autoriza retry, senha, autenticação, sessão de banco,
SQL, logs,
captura, materialização, DML, migration, reconciliação, backfill, deploy manual
ou Production, flag, runtime e PROD continuam bloqueados.

Uma única invocação terminou com exit `7`, fase `TLS_HANDSHAKE` e
`RESULT=BLOCKED_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE:TRANSPORT_BLOCKED`.
DNS, política de endereço, TCP e a resposta `S` ao SSLRequest foram
confirmados; handshake e hostname não foram confirmados. Não houve retry,
senha, autenticação, sessão de banco, SQL, logs ou PROD. A causa permanece
indeterminada e o resultado não recebe categoria retroativa. A evolução
offline adiciona somente uma categoria estática de falha TLS, com runner
SHA-256 `0ac585b86dd1c96446622e9a46bccda8a1e43eb0bceb0dcc19226892cb88d191`,
testes SHA-256
`70334dfc33505ea0b5ddb85a6406672fe0d9154e105134da164c773978459489` e
`95/95` testes verdes.

A PR #350, HEAD `58af39b760b8b5be85723d3ea693abd20fe3f3cf`, foi integrada no
merge `0f8c6a77bf489f9080743ab3f7ce71097d361aea`, com
`mergedAt=2026-08-31T16:38:27Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Backend `33415223927`, Canonical `33415223885`, E2E `33415223922`,
Environment Attestation PG17 `33415223904`, Frontend `33415223881`, RLS
`33415223955` e Tooling `33415223892`. A Vercel registrou o deployment
automático frontend Production `6185328714`, status `17578739446`, com
`SUCCESS`. Essa metadata prova somente o deployment do frontend, sem provar
saúde funcional, backend, banco, DEV, PROD, probe, migration ou runtime.

O gate `REVIEW_AND_CI_DEV_TLS_HANDSHAKE_FAILURE_CATEGORY_PR` foi consumido pela
PR #350. A categoria TLS está integrada e comprovada offline; o resultado
histórico não recebe categoria retroativa e a causa permanece indeterminada.
A árvore do merge é idêntica à do HEAD da PR.

O desenho `migration-epoch v3` deverá tratar como `KNOWN_UNVERIFIED_DRIFT`, sem nova
consulta nem inferência de migration aplicada, os sete índices observados por
evidência operacional anterior: `idx_pessoas_igreja_ativa_created`,
`idx_pessoas_igreja_ativa_tipo`, `idx_celulas_igreja_ativo_lider`,
`idx_work_queue_igreja_status_responsavel`,
`idx_conversations_igreja_assumido`, `idx_app_users_igreja_nome` e
`idx_user_roles_igreja_user`. Essa observação não foi revalidada nesta missão
e não prova o estado atual de DEV. A atestação v1 valida somente envelopes que
continuam bloqueados; ela não comprova conclusão e não pode ser reinterpretada
como `environment_attestation_complete=true`. Os artefatos históricos v1 e v2
permanecem byte-idênticos e fora do escopo.

O pacote candidato `migration-epoch v3` está congelado como
`OFFLINE_EPOCH_CUTOVER_DECISION_PACKAGE_BLOCKED`. O verificador
`backend/scripts/verify_migration_history_divergence_remediation_proposal_v3.py`
tem SHA-256 `8d7712be4f63ead2eff2c9e7af236e610b0c148acb07c85ebcd81db1f6d0877d`;
o teste `backend/tests/test_migration_history_divergence_remediation_v3.py`
tem SHA-256 `b34bd0677feb9d4453477d7503dc19beffcaf6cc8648acb85be56113b7578e24`;
a proposta
`docs/governance/migrations/migration-history-divergence-remediation-proposal-v3.json`
tem SHA-256 `076d04ed179c5128c4707c07cacd8240896101a9bea62e328d2d0569900cd10e`;
e seu schema
`docs/governance/migrations/migration-history-divergence-remediation-proposal-v3.schema.json`
tem SHA-256 `88f7972780f07c7071bb4e4292e1f21c258fff47daf2ab207fc709ff34631b38`.
A matriz nova passou `87/87`, a focal estável passou `138/138`, e o verificador
terminou fail-closed com exit `8` e
`RESULT=BLOCKED_MIGRATION_EPOCH_V3:PENDING_SEPARATE_EVIDENCE`. O estado é
`RECOMMENDATION_ONLY_NOT_APPROVED`; isso comprova somente o desenho offline e
não autoriza evidência viva, cutover, migration ou runtime.

No batch offline depois integrado pela PR #351, a correção de precedência classifica
`TimeoutError` e `socket.timeout` como `DEADLINE_EXCEEDED` antes de `OSError`
genérico em cada fronteira de rede. O batch integrado tem runner SHA-256
`2e2208bfbca1214c0cec024c58716eeac7c05789c33ce36d812c0265c3810809`, teste
SHA-256 `d7161cd7dd7c63935c07431193b0d916222e5341088edbdc6d4ef85ad3063689` e
`102/102` testes verdes. Nenhum probe vivo foi executado. Os hashes da PR #350
`0ac585b86dd1c96446622e9a46bccda8a1e43eb0bceb0dcc19226892cb88d191` e
`70334dfc33505ea0b5ddb85a6406672fe0d9154e105134da164c773978459489`
permanecem evidência histórica e não são substituídos.

O contrato D3 fail-closed integrado usa
`backend/app/agent/private_checkpoint.py`, SHA-256
`098d7186d59b2be9c231e3ca41e328b69901d4bc3e3f9b09651b902c07768f33`,
`backend/app/agent/context.py`, SHA-256
`b8d9ccea0041a81021cb2b4cf8edcbd8af0457ebf4401b021bd974edd29eea7d`, e
`backend/tests/test_agent_private_checkpoint_contract.py`, SHA-256
`2f91523e6a5daacd7c3ac08b933c7d9f857c3eec2a72b9f962c09c98d39f3c8b`.
A seleção `tests/test_agent*.py` terminou em `292 passed, 7 skipped`, com duas
advertências preexistentes. A classificação é `CONTRATO OFFLINE INTEGRADO E INATIVO`: não
há saver, migration ou wiring, e o LangGraph continua stateless.

A PR #351 foi integrada no merge
`bc97dd4e6f2fc9024e85afe8d611708699c8983a`. Os `7/7` checks pós-merge
concluíram com `SUCCESS`. A Vercel registrou o deployment automático do frontend
Production `6187006353`, status `17583083885`, com `SUCCESS`. Essa metadata prova
somente o frontend e não prova backend, banco ou runtime. A preparação D3 de
estado efêmero desta branch permanece candidata offline, sem saver, migration
ou retomada, e não integra a evidência pós-merge da PR #351.

O gate histórico `REVIEW_AND_CI_OFFLINE_AGENT_FOUNDATION_BATCH_PR` foi consumido
pelo push, abertura, CI e Preview da PR #351. Ele não autorizou o merge
posterior, permanece somente como evidência histórica e não é um segundo gate
corrente.

**Próximo gate único:**
`REVIEW_AND_CI_D3_EPHEMERAL_EFFECT_STATE_PR`. O nome não constitui autorização
já concedida. Seu consumo exige autorização humana posterior e separada que
nomeie push, abertura da PR e GitHub CI e aceite o Vercel Preview automático.
O batch permanece exclusivamente offline. Este gate não autoriza merge, Vercel
Production, probe vivo, acesso a DEV ou PROD, banco, logs, SQL, DML, migration,
deploy, flag ou runtime.

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
