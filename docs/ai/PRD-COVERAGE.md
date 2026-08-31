---
project: igreja12
document_kind: prd-coverage
status: canonical-audit
last_verified: 2026-08-31
audited_repository_sha: fb776e270bf3e2ffde0cbb28e400960591b74420
canonical_prd: docs/Docs20260611_163530/PRD20260611_163530.md
---

# Cobertura atual do PRD e da visão WhatsApp-first

Esta matriz reconcilia o PRD global, decisões posteriores e o código no SHA
auditado. Ela separa implementação, operação e intenção futura para impedir que
uma tela, um teste, um documento ou um deploy sejam tratados como prova
equivalente.

## Classificações

- `IMPLEMENTADO`: contrato e fluxo identificáveis no código auditado.
- `PARCIAL`: existe uma base útil, mas falta parte relevante do fluxo.
- `AUSENTE`: não foi encontrado contrato operacional suficiente.
- `GATE OPERACIONAL`: implementação existe, mas efeito real exige ambiente,
  flag, credencial, canário ou autorização.
- `NÃO VERIFICADO`: depende de ambiente vivo ou validação que não foi executada
  nesta auditoria documental.

Uma capacidade pode combinar estados. `IMPLEMENTADO / GATE OPERACIONAL` não
significa ativa em produção.

## Matriz do produto

| Domínio | Estado | Evidência no repositório | Lacuna para a visão aprovada |
|---|---|---|---|
| Autenticação, RBAC e tenant | `IMPLEMENTADO / D2A INTEGRADA E INATIVA` | D1A integrada e aplicada em DEV; a PR #313 integrou a fronteira privada D2A no SHA auditado | A integração não aplicou migration compartilhada, não provisionou credencial, não conectou o runtime, não fez deploy manual ou do backend, não promoveu a produção e não ativou o agente; houve somente preview automático da PR |
| Pessoas e responsabilidades | `PARCIAL FORTE` | cadastro, papéis, vínculos, fila e escopos existentes | Fechar responsabilidades temporais, owner operacional e composição por setor |
| Conexão WhatsApp | `IMPLEMENTADO / GATE OPERACIONAL` | Evolution, conexão por igreja, webhook e filas | Monitorar recibos, reconnect e capacidade antes de cada canário |
| Conversas e handoff | `IMPLEMENTADO` | histórico, inbox, atribuição, transferência e estado IA/humano | Adicionar memória derivada, exclusão propagada e avaliação de naturalidade |
| Fundação do agente | `IMPLEMENTADO / PARCIAL / LEDGER-BOOTSTRAP INTEGRADO E COMPROVADO OFFLINE / RECONCILIATION INTEGRADO E COMPROVADO OFFLINE / CAPTURADOR E MATERIALIZADOR INTEGRADOS / ARTEFATOS VERSIONADOS / REVISÃO INDEPENDENTE BLOQUEADA CONCLUÍDA / DECISÃO OWNER-01 REGISTRADA / MANIFESTO DE FONTE CRIADO / REVISÃO TÉCNICA CONCLUÍDA / REVISÃO INDEPENDENTE DO MANIFESTO PENDENTE / NÃO APLICADO / D2B2B3A DRAFT-ONLY INTEGRADA E INATIVA` | LangGraph stateless e contexto confiável D2B1 integrados; a preparação D3 offline separa entrada e saída, usa envelope de efeitos `UntrackedValue` por substituição e limita o fallback automático ao modo comprovadamente stateless | Revisão independente do manifesto; atestação posterior, implementação, runner, memória, conhecimento, D2 e operação permanecem bloqueados |
| Isolamento da memória | `AUSENTE / FUNDAÇÃO D2A INTEGRADA` | Nenhum checkpointer durável instalado; o envelope `UntrackedValue` é efêmero e não constitui memória, checkpoint ou retomada | Tabelas com `igreja_id`, FORCE RLS, namespace server-side, exclusão e testes adversariais pertencem à D3 |
| Conhecimento oficial | `AUSENTE` | Não há ingestão aprovada, embeddings ou recuperação institucional | Perfil da igreja, documentos versionados, audiência, RLS e busca híbrida |
| Dados vivos como ferramentas | `PARCIAL` | Quatro ferramentas limitadas e queries determinísticas | Catálogo por especialista, capacidades e serviços compartilhados com o painel |
| Consentimento | `PARCIAL / LEDGER-BOOTSTRAP INTEGRADO E COMPROVADO OFFLINE / RECONCILIATION INTEGRADO E COMPROVADO OFFLINE / CAPTURADOR E MATERIALIZADOR INTEGRADOS / ARTEFATOS VERSIONADOS / REVISÃO INDEPENDENTE BLOQUEADA CONCLUÍDA / DECISÃO OWNER-01 REGISTRADA / MANIFESTO DE FONTE CRIADO / REVISÃO TÉCNICA CONCLUÍDA / REVISÃO INDEPENDENTE DO MANIFESTO PENDENTE / NÃO APLICADO / D2B2B3A DRAFT-ONLY INTEGRADA E INATIVA` | Legado e opt-out continuam ativos; D2B2a adiciona ledger append-only sem caller ou aplicação em Supabase; a revisão externa bloqueou DEV por divergência e PROD por evidência insuficiente | Revisão independente do manifesto; D2, catálogo, prova, writer e operação permanecem bloqueados |
| Propostas e confirmação | `AUSENTE COMO PLATAFORMA` | Confirmações existem apenas em fluxos específicos | Registro durável, expiração, idempotência, revalidação e comprovante |
| Notificações proativas | `PARCIAL E FRAGMENTADO` | SLA, cron, Agenda, event notify e broadcast têm caminhos próprios | Outbox única, finalidade, quiet hours, retry, recibo e escalonamento |
| Painel de Hoje | `IMPLEMENTADO / PARCIAL` | dashboard e work queue por responsabilidade | Compor todas as responsabilidades e as lacunas de conhecimento |
| Minha Célula | `IMPLEMENTADO / PARCIAL` | reuniões, presenças, visitantes, relatórios e materiais | Completar operação WhatsApp e honestidade entre intenção e entrega |
| Central de Células | `IMPLEMENTADO / PARCIAL` | gestão, solicitações, transferência, remoção e eventos append-only | Especialista WhatsApp, planejamento e comunicação pela outbox |
| Relatório de célula web | `IMPLEMENTADO` | `celula_reuniao`, draft, submit e snapshot congelado | Extrair serviço de aplicação compartilhado com o WhatsApp |
| Relatório pelo WhatsApp | `PARCIAL` | parser e evento `report_captured` | Não grava o relatório canônico, não confirma, não transcreve áudio nem comprova idempotência |
| Agenda | `PARCIAL` | CRUD, visões, confirmações, importação Google e alertas internos | Operação WhatsApp, envio futuro unificado e semântica de entrega |
| Consolidação | `PARCIAL` | decisões, etapas, responsáveis, SLA e conclusão manual | Máquina de estados e read model duráveis, transações e elegibilidade |
| Universidade da Vida | `AUSENTE COMO MÓDULO` | Placeholder e referências históricas | PRD, turmas, aulas, presenças, Encontro, batismo, papéis e APIs |
| Capacitação Destino | `AUSENTE COMO MÓDULO` | Placeholder e flag histórica | PRD, módulos, turmas, frequência, pré-requisitos e certificação |
| Enviar e multiplicação | `PARCIAL` | célula, solicitações e multiplicação têm partes implementadas | Jornada de aptidão, aprovação sensível e integração com formação |
| Broadcast | `IMPLEMENTADO / GATE OPERACIONAL` | ledger, worker, retry e dead-letter | Política por finalidade e canário nominal separado |
| Asaas | `IMPLEMENTADO / GATE OPERACIONAL` | operações duráveis, isolamento e hardening | Inventário e canário financeiro real, sem envolver a igreja em cortesia |
| Brevo | `IMPLEMENTADO / GATE OPERACIONAL` | serviço e modo de envio fechado | Domínio, remetente, monitoramento e canário próprio |
| Onboarding da igreja | `PARCIAL / GOVERNANÇA DRAFT-ONLY INTEGRADA E INATIVA` | telas e configurações administrativas existentes; D2B2b3A integra o preparo de rascunhos de consentimento no Console Master | Revisão offline da proposta de remediação; em gate posterior, criar o fluxo nominal de responsáveis e aprovações sem converter preenchimento em autoridade |
| Exclusão e direitos da pessoa | `PARCIAL` | Exclusão de conversa remove conversa, mensagens e mídia | Propagar para transcrição, resumo, checkpoint, vetores e auditoria sem conteúdo |
| Observabilidade de IA | `PARCIAL` | logs, custo, filas e metadados seguros de falha | Métricas por rota e tenant, SLO, retenção e alerta de workflows presos |
| Acessibilidade e performance | `NÃO VERIFICADO INTEGRALMENTE` | Automação e estilos cobrem parte dos riscos | Leitor de tela, teclado, zoom, mobile e métricas de campo |
| Backup e recuperação | `GATE OPERACIONAL` | Runbooks e evidências operacionais anteriores | Manter restauração periódica e incluir novas tabelas privadas |

## Situação do agente no SHA auditado

### Implementado

- igreja resolvida pela instância Evolution;
- Pessoa ativa resolvida por telefone dentro do tenant;
- identidade duplicada e ferramenta desconhecida falham fechadas;
- papéis e capacidades são injetados pelo servidor;
- handoff humano, opt-out, consentimento e autoria são preservados;
- `AgentConfig.ativo=false` bloqueia resposta automática;
- a credencial é OpenAI BYO por igreja;
- dead-letter registra metadados seguros para falhas novas.

### Parcial

- o LangGraph possui rotas especializadas, mas não os especialistas de produto
  completos;
- o LLM refina apenas respostas determinísticas e não recebe histórico nem
  conhecimento institucional;
- o relatório é analisado e registrado como evento, mas não grava
  `celula_reuniao`;
- mensagens de áudio são armazenadas e exibidas, sem transcrição encontrada;
- o runtime continua usando consentimento geral; o ledger D2B2a está integrado,
  inativo, não aplicado em Supabase e não possui caller;
- serviços de notificação existem, mas não compartilham uma outbox geral.

### Ausente

- checkpointer PostgreSQL conectado ao LangGraph;
- resumo incremental e recuperação de memória privada;
- RAG documental com publicação e ACL;
- propostas de ação duráveis e genéricas;
- especialistas completos de Agenda, Consolidação, UV e CD;
- indexação e recuperação automáticas e seguras de novos registros oficiais,
  sem treinamento ou fine-tuning por igreja;
- política completa de eliminação dos derivados de conversa.

### D2B1 integrada no código

A PR #315 integrou no `origin/main` auditado um
`TrustedAgentContext` imutável e tipado, injetado pelo servidor por
`StateGraph.context_schema`. Tenant, conversa, Pessoa, estado da conversa,
privilégio e termo legado deixam de ser aceitos como campos de entrada ou de
autoridade no topo do `AgentState` mutável. A
entrada, o caminho compilado, o caminho direto e cada node revalidam a
fronteira; a mesma instância de `PrivilegeContext` chega ao executor de tools.

O merge passou em 2.770 testes offline, com 278 desselecionados, e 278 testes
RLS, com zero skips. Cinco workflows da PR e cinco pós-merge concluíram verdes.
Essa evidência promove D2B1 somente a integrada no código; não prova aplicação,
provisioning, wiring privado, deploy ou ativação e não altera as classificações
de consentimento, memória, conhecimento ou propostas.

### Preparação D3 offline, sem memória ativa

A preparação D3 candidata separa `AgentTurnInput`, `AgentState` e
`AgentTurnOutput` por `input_schema` e `output_schema`. As intenções ficam em um
`AgentTurnEffects` completo, reinicializado por turno, substituído sem reducer
acumulativo e mantido em canal `UntrackedValue`. O fallback automático para o
caminho direto só ocorre quando checkpointer e store estão comprovadamente
ausentes.

Essa contenção reduz o risco de replay acidental, mas não implementa memória.
Não há saver, migration, schema de checkpoint, resumo, recuperação, retomada,
retenção ou exclusão de derivados nesta fatia. O isolamento de memória
permanece `AUSENTE / FUNDAÇÃO D2A INTEGRADA`.
O freeze técnico pré-merge e exclusivamente offline desta preparação vincula:

- `backend/app/agent/context.py`, SHA-256
  `b81afb549b6110553bd4ba5e6b861a9094278670d86c92b128e04fc081f3a729`;
- `backend/app/agent/graph.py`, SHA-256
  `2d0e729e9756e09b161c300fca032fb54e0ee30bc1c963fcaf538295eedcf2c9`;
- `backend/app/agent/nodes.py`, SHA-256
  `e16ffbab8163e58af96e192976f580e1a7690b0932eb720a3b3e2874443d6454`;
- `backend/app/agent/private_checkpoint.py`, SHA-256
  `aa54f4f474fb6aa40ef02b738c5ad1d82905cbd8a1745ce805e7a19a5991dcc6`;
- `backend/app/agent/runtime.py`, SHA-256
  `f3bc2404f9335e5846c9e8a1d70ca30dd4189cc2219bca59d9ec098e05cc1a9e`;
- `backend/tests/test_agent_turn_effect_state.py`, SHA-256
  `eb8b26c43bd958965564668f9763de368a310afa4f658161d7b04b906256fbf8`.

A focal terminou em `144/144`, e a seleção `tests/test_agent*.py` terminou em
`309 passed, 7 skipped`. Essa evidência é local e pré-merge; não prova CI,
integração, saver, migration, memória ativa, deploy ou runtime.



### D2B2a integrada e inativa

No histórico do `origin/main`, a PR #317, HEAD
`8ba5c988e9169703c923b1f1a3e47d1c427531e1`, integrou a D2B2a com o
merge `bce5a9a434077e488cea8baae3e9dd7c7c4ba0f1` e a
migration de `public.consentimento_finalidade_evento`, ORM, tipos de domínio e
serviço interno sem caller. O contrato separa
`atendimento_solicitado|cuidado_pastoral|tarefas_operacionais|comunicados`,
com estados `concedido|retirado`, fontes
`whatsapp_inbound|painel_autenticado`, `versao_termo` e, no INSERT inicial,
operador obrigatório somente para o painel. A exclusão referencial posterior
do AppUser pode anonimizar o operador via `ON DELETE SET NULL`, preservando o
evento. A idempotência é por tenant, e a sequência concorrente fica no banco.

A tabela integrada usa RLS habilitada e forçada, barreira restritiva GUC-only e
ACL mínima. Não há backfill do legado, e o opt-out global continua
prevalecendo. Nenhum caller, API ou wiring integra esta fatia; não houve
aplicação em Supabase, deploy manual ou do backend, ativação ou canário. Textos, base jurídica,
retenção e RBAC por finalidade ainda bloqueiam writers e qualquer ambiente
compartilhado.

Os cinco workflows da PR #317 e os cinco pós-merge concluíram com `SUCCESS`.
A PR gerou Preview e o merge gerou deployment frontend Vercel automático
classificado como Production. Essa metadata prova o deployment do frontend no
ambiente Production da Vercel; não prova backend, banco ou aplicação da
migration em Supabase DEV ou PROD.

### D2B2b1 integrada e inativa

A PR #318, HEAD `ede4797003e044f582da9f9a3ab86554f708a73a`, integrou a
D2B2b1 no merge `74951828f48994622a112d8e59eb978e5fb4f406`. Ela é código
puro, sem migration ou caller, e restringe a
idempotência a chave opaca gerada pelo servidor, aplica RBAC deny-first e nega
toda tentativa de `concedido`, inclusive quando papel, fonte ou entrada forem
sintaticamente válidos. Não existe reidratação por valor; retry entre processos
fica bloqueado até um recibo durável autenticado provar a origem da chave.
Limpar opt-out não concede novamente.

Essa fronteira não decide texto, hipótese jurídica, prova, tratamento de
menores, retenção, eliminação, transferência internacional ou relação entre
retirada, opt-out e pedidos de direitos. Um responsável humano e a função
jurídica ou encarregado precisam aprovar o pacote por finalidade antes de
catálogo, evidence store ou writer.

O recorte focal passou em 1.114 de 1.114 e a suíte RLS em 288 de 288 contra
PostgreSQL 17 descartável. Os cinco workflows da PR e os cinco pós-merge,
incluindo Backend Tests integral, ficaram verdes. A PR gerou Preview e o merge
gerou deployment frontend Vercel automático classificado como Production; não
houve deploy manual ou do backend, migration, Supabase, ativação ou canário. O
PostgreSQL temporário foi removido.

O template D2B2b2 organiza as decisões pendentes e continua marcado
`TEMPLATE_ONLY / NOT_APPROVED`; sua existência não satisfaz o gate. O contrato
está em
[`2026-08-28-d2b2b2-consent-decision-packet-contract.md`](../decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md).

### D2B2b3A, superfície Master draft-only integrada e inativa

A implementação D2B2b3A permite que o Admin Master autenticado prepare, no
Console,
um rascunho por finalidade e igreja. Tenant e ator são derivados no servidor;
o e-mail do operador não é autoridade nem configuração versionada. A fatia
contém migration, persistência, API e painel apenas para rascunhos, com
revisão otimista e auditoria sem payload.

O Master não escolhe hipótese jurídica, não declara que a operação depende de
consentimento, não decide política de menores, não atesta, não aprova, não
representa funções da igreja e não preenche registros nominais. Os quatro
rascunhos operacionais permanecem `DRAFT_NOT_APPROVED`, com
`controller_approved=false`, `human_packet_complete=false`,
`catalog_ready=false` e `writer_eligible=false`. Supabase compartilhado,
painel do tenant, aprovações, catálogo, evidence store, writer, WhatsApp,
runtime do agente, deploy manual ou do backend e D2C continuam bloqueados. O
contrato está em
[`2026-08-28-d2b2b3-master-governance-drafts.md`](../decisions/2026-08-28-d2b2b3-master-governance-drafts.md).

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

A PR #320, HEAD `66ce06d9a356a52e63366b3a6528b0b83170d12e`, foi integrada no
merge `947d891c2ea278b7a3231fecd9ca1c90cfe29a1f`. Os cinco workflows da
PR e os cinco pós-merge ficaram verdes. O merge gerou o deployment automático
Vercel frontend Production `6140373952`, com `SUCCESS`; essa metadata não
prova backend, banco ou Supabase. Esta missão não aplicou a migration D2B2b3A;
DEV e PROD confirmaram a ausência. A flag permanece `false`, e não houve deploy manual ou do
backend, wiring, ativação ou canário.

## Canário ativo reconciliado

O canário ativo da Filadélfia é evidência operacional reconciliada nesta missão,
não um fato previamente documentado no SHA `ad4a272`. Foram usadas apenas as
mensagens sintéticas `Olá`, `Aceito` e `Quero conhecer a igreja`.

Classificação:

- `PASS TÉCNICO`: três entradas e três saídas, autoria correta, filas canônicas
  limpas e gates restaurados, conforme relato do operador;
- `QUALIDADE INSUFICIENTE`: respostas robóticas e perguntas repetidas;
- `NÃO AUTORIZA EXPANSÃO`: o resultado não libera produção ampla nem outro
  canário.

A evidência detalhada pertence ao registro pós-V1 atualizado nesta missão.

## Formação e Jornada G12

### Fundação obrigatória antes de UV

Consolidação precisa se tornar uma fonte durável e coerente antes de matricular
alunos na Universidade da Vida:

1. definir a máquina de estados canônica da Jornada;
2. expor progresso e histórico por read model;
3. tornar conclusão e elegibilidade transacionais;
4. separar vínculo em célula de conclusão da consolidação;
5. testar concorrência, autorização, RLS e reprocessamento;
6. aprovar PRD de Formação e plano de migrations.

### Universidade da Vida

O escopo aprovado para planejamento inclui turmas, dez semanas, aulas 1 a 4,
Encontro na semana 5, aulas 5 a 8, batismo na semana 10, presenças, papéis,
acompanhamento e elegibilidade para CD. Nenhum desses contratos constitui hoje
um módulo completo no código.

### Capacitação Destino

O planejamento histórico indica seis livros ou módulos, dez aulas por módulo,
turmas simultâneas, frequência, pré-requisitos, aptidão para liderança e
certificação. Currículo, limiares de assiduidade, papéis e estados precisam ser
fechados no PRD próprio antes do schema.

## Ordem de execução para a visão completa

1. `D0`: reconciliar fonte de verdade e arquitetura em documentação. Concluída
   na PR #310.
2. `D1`: revalidar segurança, capacidades e escopos no SHA atual. Auditoria e
   hardening concluídos; PR #311 integrada e migration D1A aplicada em DEV.
3. `D2`: a D2A já está integrada como fronteira privada inativa, sem conectar
   worker ou LangGraph. A D2B1 está integrada no código, com contexto confiável
   v1 separado do estado mutável e LangGraph ainda stateless. D2B2a está
   integrada e inativa, sem caller ou aplicação em Supabase. D2B2b1 está
   integrada e inativa e adiciona a fronteira pura com chave opaca, RBAC
   deny-first e concessões negadas. A D2B2b3A integra somente persistência,
   API e painel do Console Master para rascunhos por igreja, ainda inativos. O
   fluxo nominal de
   atestado e aprovação vem depois; somente outra fatia pode criar catálogo,
   prova correlacionada e writers seguros. D2C permanece bloqueada e só depois
   cria propostas duráveis, confirmação, expiração, idempotência e
   revalidação.
4. `D3`: memória durável, privacidade e exclusão integral.
5. `D4`: conhecimento oficial e onboarding guiado.
6. `D5`: outbox e plataforma de notificações.
7. `D6`: relatório de célula completo pelo WhatsApp.
8. `D7`: Central, Agenda e Consolidação no WhatsApp.
9. `D8`: Enviar e demais partes com contrato aprovado. Universidade da Vida e
   Capacitação Destino estão excluídas da missão atual e não serão inferidas a
   partir de placeholders; itens que dependam desses módulos permanecem fora.
10. `D9`: canários externos e operação comercial ampla, cada um em missão
    independente.

## Definições de pronto

| Marco | Definição |
|---|---|
| V1 funcional | Já encerrada como piloto controlado |
| Fundação inteligente | Memória, conhecimento, consentimento, ação confirmada e outbox isolados por tenant |
| Primeira vertical | Relatório de célula completo e idempotente pelo WhatsApp |
| Produto pastoral amplo nesta missão | Central, Agenda, Consolidação e Enviar operáveis com WhatsApp principal; UV e CD permanecem em marco futuro separado |
| Operação comercial | Integrações selecionadas com consentimento, observabilidade, suporte, canários e gates aprovados |

O projeto só pode ser chamado de integralmente concluído após o último marco. A
conclusão da V1 permanece válida e não deve ser reaberta para esconder a
expansão de escopo.

Desenvolvida e comprovada offline sobre a base
`b43ad92028374fa6763ef10f5eb7a379afd3e7a2`, a implementação foi integrada
pela PR #323. `bootstrap-ledger` exige `--confirm BOOTSTRAP_LEDGER` e lê
o destino apenas de `M06_MIGRATION_DATABASE_URL`. Em PostgreSQL 17 ele cria,
atomicamente, somente o ledger vazio `public.schema_migrations` no contrato
owner-only final: colunas, chave primária e defaults exatos, RLS, policy deny e
ACL mínima. Homônimos, grants ou default privileges perigosos, memberships,
owner ou forma física divergentes abortam e revertem; a reaplicação exata é um
no-op.

Foram aprovados 42/42 testes unitários, 87/87 em PostgreSQL 17-alpine
descartável em duas execuções independentes, 87/87 em Supabase PG17 17.6.1.159
descartável em duas execuções independentes e a revisão de segurança `GO`. A
suíte RLS completa, em execução serial limpa no PostgreSQL 17 descartável,
passou em 326/326, com 3803 deselecionados e 2 warnings preexistentes, em
162.77s. A suíte offline integral foi interrompida após 5 min sem saída ou
progresso; o resultado é `INCONCLUSIVO`, não verde nem falha e não foi
reclassificado. Os workflows Backend Tests da PR #323 e do pós-merge concluíram
com `SUCCESS`. O bootstrap não descobre o catálogo,
não consulta ou altera `supabase_migrations`, não reconcilia, não faz backfill
e não aplica ou registra migration. `status` e `apply` continuam bloqueados
até existir prefixo íntegro do catálogo, humanamente reconciliado, com no máximo
uma migration pendente. A PR #323, HEAD
`74d3f2d87a7ffad501432b2d9fc4163bd3b4ada4`, foi integrada pelo merge
`3a5789c784017ab15a43e28c4270d25af8618359` em
`2026-08-28T15:24:58Z`; seus cinco workflows e os cinco pós-merge concluíram
com `SUCCESS`. A Vercel registrou o Preview automático frontend `6143773477`,
com `SUCCESS`, em `2026-08-28T15:22:43Z`, e o Production automático frontend
`6143819601`, com `SUCCESS`, em `2026-08-28T15:25:43Z`. Essas metadatas provam
somente o frontend, sem provar backend, banco ou runtime. O bootstrap está
integrado, mas não aplicado. Não houve deploy manual ou do backend, acesso aos
bancos DEV ou PROD, bootstrap ou migration compartilhada, restart ou alteração
de credencial, flag, runtime, agente ou canário.

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
A evidência e os limites estão na
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

O gate abaixo foi consumido em 2026-08-31:
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

## Fontes principais

- `docs/Docs20260611_163530/PRD20260611_163530.md`
- `docs/decisions/2026-08-25-evolution-agent-foundation.md`
- `docs/decisions/2026-08-27-whatsapp-first-tenant-agent-architecture.md`
- `docs/decisions/2026-08-28-d2b2-purpose-consent-ledger.md`
- `docs/decisions/2026-08-28-d2b2b1-consent-security-boundary.md`
- `docs/decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md`
- `docs/decisions/2026-08-28-d2b2b3-master-governance-drafts.md`
- `docs/audits/2026-08-27-d1-security-scope-audit.md`
- `docs/ops/POST-V1-MISSION-REGISTER.md`
- `docs/ops/EVOLUTION-AGENT-CANARY-RUNBOOK.md`
- `Plan-Designer-Igreja12/01-ESTADO-ATUAL-E-GAPS.md`
- `Plan-Designer-Igreja12/03-AGENTE-IA-WHATSAPP.md`
- `Plan-Designer-Igreja12/08-ROADMAP-PRIORIZADO.md`
- código e testes do SHA auditado
