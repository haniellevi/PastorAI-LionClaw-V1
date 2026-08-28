---
project: igreja12
document_kind: prd-coverage
status: canonical-audit
last_verified: 2026-08-28
audited_repository_sha: 74951828f48994622a112d8e59eb978e5fb4f406
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
| Fundação do agente | `IMPLEMENTADO / PARCIAL / D2B2B3A DRAFT-ONLY AUTORIZADA` | LangGraph stateless e contexto confiável D2B1 integrados; D2B2a adiciona persistência e serviço interno de consentimento sem caller; D2B2b1 é uma fronteira pura deny-first; D2B2b3A delimita rascunhos no Console Master | Revisar e integrar a fatia draft-only; aprovações humanas, catálogo, writer, memória, conhecimento e subfluxos permanecem posteriores |
| Isolamento da memória | `AUSENTE / FUNDAÇÃO D2A INTEGRADA` | Nenhum checkpointer durável instalado; D2A cria somente role, schema, helper e factory privados ainda inativos | Tabelas com `igreja_id`, FORCE RLS, namespace server-side, exclusão e testes adversariais pertencem à D3 |
| Conhecimento oficial | `AUSENTE` | Não há ingestão aprovada, embeddings ou recuperação institucional | Perfil da igreja, documentos versionados, audiência, RLS e busca híbrida |
| Dados vivos como ferramentas | `PARCIAL` | Quatro ferramentas limitadas e queries determinísticas | Catálogo por especialista, capacidades e serviços compartilhados com o painel |
| Consentimento | `PARCIAL / D2B2B3A DRAFT-ONLY AUTORIZADA` | Legado e opt-out continuam ativos; D2B2a adiciona ledger append-only sem backfill, caller ou aplicação em Supabase; D2B2b1 nega concessões; D2B2b3A permite apenas o preparo de rascunhos por igreja pelo Master | Integrar a superfície draft-only e, em fatias posteriores, obter atestados e aprovações nominais antes de catálogo, prova ou writer |
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
| Onboarding da igreja | `PARCIAL / GOVERNANÇA DRAFT-ONLY DEFINIDA` | telas e configurações administrativas existentes; D2B2b3A define o preparo de rascunhos de consentimento no Console Master | Integrar a superfície, depois criar o fluxo nominal de responsáveis e aprovações sem converter preenchimento em autoridade |
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

### D2B2b3A, superfície Master draft-only autorizada

A decisão D2B2b3A permite que o Admin Master autenticado prepare, no Console,
um rascunho por finalidade e igreja. Tenant e ator são derivados no servidor;
o e-mail do operador não é autoridade nem configuração versionada. A fatia
pode conter migration, persistência, API e painel apenas para rascunhos, com
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

A candidata inativa não prova o wiring do banco. Antes de qualquer aplicação em
banco compartilhado, ativação da flag ou wiring do backend compartilhado, um
preflight separado deve comprovar, sem expor a credencial, que o `DATABASE_URL`
do plano Master usa o owner esperado com acesso efetivo sob `FORCE RLS` ou um
papel explicitamente autorizado com `BYPASSRLS`. Esse requisito não autoriza
nenhuma dessas ações.

A abertura da PR pode gerar Preview automático, e o merge pode gerar deployment
frontend Production automático pela integração Vercel do repositório. O merge
exige revisão humana consciente desse efeito. Isso não autoriza migration
compartilhada, mudança de flag, runtime, ativação ou canário e não constitui
evidência de deployment desta candidata.

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
   deny-first e concessões negadas. A D2B2b3A autoriza somente persistência,
   API e painel do Console Master para rascunhos por igreja. O fluxo nominal de
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

## Próximo gate único

Revisar e integrar a PR D2B2b3A draft-only, comprovando migration em
PostgreSQL 17 descartável, isolamento entre tenants, concorrência por revisão e
ausência de caminhos de aprovação ou runtime. Supabase DEV ou PROD, painel do
tenant, aprovações, catálogo, evidence store, writer, WhatsApp, agente, deploy
manual ou do backend e D2C permanecem bloqueados.

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
