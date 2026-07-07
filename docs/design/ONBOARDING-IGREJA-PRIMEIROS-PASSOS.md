# Onboarding da Igreja — Primeiros Passos do Admin

- **Natureza:** docs-only (Missão 5). Zero backend, frontend, migration, env, deploy, Supabase, Vercel ou WhatsApp.
- **Data:** 2026-07-06
- **Base:** scout read-only sobre `main` (`b0ea1c5`) — 6 docs de Células, PRD/stories do pipeline, runbook de prod, sprint das 3 superfícies, frontend (`navigation.ts`, telas) e backend (`platform_admin.py`, `team.py`, `contacts.py`, `cells.py`, `calendar.py`, `whatsapp.py`, `queue_worker.py`, `agent/runtime.py`).
- **Papel deste doc:** fonte de verdade do "primeiro dia" de uma igreja nova. Nenhum documento anterior cobre essa sequência — as palavras "onboarding" e "primeiros passos" não ocorrem em nenhum doc de produto (a única ocorrência de "onboarding" no PRD é o sub-agente de WhatsApp que recebe visitantes, US-10 — outro conceito).

---

## 1. Objetivo

Definir, sem implementar nada agora:

1. O que uma igreja recém-provisionada **já tem** e o que **não tem**.
2. A **sequência ideal** de configuração pelo admin, com superfície, tela e permissão de cada passo.
3. Os **buracos reais** entre essa sequência ideal e o produto atual (CTAs ausentes, gargalo circular, drifts doc↔código).
4. Um **plano de PRs futuros** para fechar os buracos — cada um pequeno, reversível e independente.

Invariantes de produto que este doc consagra (decisões do dono):

- **O cadastro de célula é atribuição da Central de Células** (Jornada G12 → Discipular → Central) e deve ficar **visível** lá — não escondido em tela legada nem dentro de Minha Célula.
- **Minha Célula NÃO é lugar de administrar a primeira célula.** É superfície operacional de discípulo/líder (invariante §15.1 do Contrato UX: "Central NUNCA dentro de Minha Célula" — e o inverso também vale: administração nunca dentro de Minha Célula).
- **O admin da igreja precisa de um caminho claro** para cadastrar pastores, líderes, aptos e a primeira célula — hoje esse caminho existe, mas é não-documentado, parcialmente escondido e com ordem obrigatória não-óbvia (ver §4 e §9.1).

## 2. As 3 superfícies

Separação em produção desde 2026-07-06 (PR #101; fonte: `docs/ops/PROD-ENV-RUNBOOK.md` §1b + `docs/sprints/2026-07-06-subdominios-3-superficies.md`). Mesmo deployment Vercel, roteado por Host em `frontend/src/middleware.ts`.

| Superfície | Quem | Papel no onboarding |
|---|---|---|
| **painel.igreja12.com.br** (`/admin`) | Dono do sistema (allowlist `platform_admins`, login próprio) | Provisiona a igreja, convida o 1º admin (Brevo), **aprova** a igreja, define **plano/cobrança**, edita **nome** da igreja, reatribui dono, gerencia o agente-template e o toggle do agente por igreja |
| **admin.igreja12.com.br** (`/gestao`) | Admin da igreja | Configuração: Conexão WhatsApp, Agente IA (chave LLM BYO + base de conhecimento), Assinatura (só dono), Permissões, Usuários do Sistema (convites/papéis), Integrações (Google Agenda + destinatários de avisos) |
| **app.igreja12.com.br** (`/`) | Todos os papéis | Operação diária: Pessoas, células (Central e Minha Célula), Agenda, Conversas, Jornada G12. **Todo cadastro operacional vive aqui** — decisão do dono (2026-07-06): controles pastor+admin (evento, Central, promover, células) ficam no app para não tirar capacidade do pastor |

Sessão da igreja é compartilhada entre app. ↔ admin. (cookie `pastorai_token`, domain `.igreja12.com.br`); o console master usa token separado. O primeiro dia do admin transita **necessariamente pelas duas superfícies** dele (admin. para configurar, app. para cadastrar) — o botão "Admin" no app ([`AppShell.tsx:46-49`](../../frontend/src/components/shell/AppShell.tsx)) é a ponte.

## 3. Estado de nascimento de uma igreja

Fluxo real verificado no código (não há webhook Clerk, self-service nem seed — tudo manual via console master):

1. **Provisionamento** — `POST /admin/igrejas` ([`platform_admin.py:380-446`](../../backend/app/routers/platform_admin.py)): cria `Igreja(status='aguardando_aprovacao')` + `AppUser` `convidado` com papel `admin`, marca-o `dono_id`, envia convite Brevo (best-effort; link de ativação com token de 7 dias).
2. **Aprovação** — `POST /admin/igrejas/{id}/aprovar` ([`platform_admin.py:588-653`](../../backend/app/routers/platform_admin.py)): status → `ativa`, semeia a matriz `role_permissions` e copia o agente-template do master para `AgentConfig` (nasce `ativo=False`). Enquanto `aguardando_aprovacao`, o login é bloqueado (`BLOCKING_IGREJA_STATUSES`, [`deps.py:40`](../../backend/app/deps.py)).
3. **Ativação do dono** — `POST /auth/activate` ([`auth.py:359-398`](../../backend/app/routers/auth.py)): valida o token, cria o usuário no Clerk, e — se `pessoa_id` é NULL — **exige telefone e cria a Pessoa-membro** (delta-049 Parte B). ⚠️ O gap "C2: dono nasce sem pessoa_id e não há como vincular" descrito em `AGENDA-EVENTOS-EVT7-destinatarios-alerta.md` está **desatualizado para igrejas novas** — a ativação atual cria a Pessoa. Continua válido o **C1**: o dono nasce apenas com papel `admin` e a Pessoa dele nasce `membro` comum; ninguém o marca como pastor automaticamente.

O que a igreja **tem** ao nascer: dono-admin ativo com Pessoa vinculada, matriz de permissões default, AgentConfig copiado do template (inativo), plano escolhido pelo master.

O que a igreja **não tem**: pessoas (além do dono), pastores, líderes, aptos, células, eventos, WhatsApp conectado, Google conectado, destinatários de avisos, credencial LLM, assinatura configurada no Asaas. E **nenhuma tela lista o que falta** — o admin cai no `#dashboard` genérico sem guia (único "welcome" no produto é o card estático de membro, [`DashboardScreen.tsx:637-653`](../../frontend/src/components/dashboard/DashboardScreen.tsx)).

Edge verificado: se o orquestrador-template do master estiver vazio, `_seed_agent_from_template` retorna sem criar nada ([`platform_admin.py:1146-1148`](../../backend/app/routers/platform_admin.py)) — igreja nasce **sem AgentConfig algum**. Risco em §9.4.

## 4. Checklist ideal do primeiro dia

Sequência com superfície, tela e permissão. A ordem dos passos 4→7 **não é opcional** hoje — é imposta pelo código (gargalo circular, §9.1).

| # | Passo | Superfície | Tela / rota | Quem pode |
|---|---|---|---|---|
| P0 | Provisionar igreja + convite do dono; **aprovar** | painel. | Console master → "Provisionar igreja" | master |
| P1 | Ativar convite (telefone obrigatório → vira Pessoa) | link de e-mail → app. | `/#ativar/{token}` | dono |
| P2 | Conectar WhatsApp (QR / pairing) | admin. | Conexão WhatsApp (landing default do `/gestao`) | admin |
| P3 | Cadastrar chave LLM do agente (BYO); solicitar mudanças ao master via fila | admin. | Agente IA | admin |
| P4 | Cadastrar as primeiras Pessoas (pastores e futuros líderes **entram como Pessoas primeiro**) | app. | Pessoas → "Novo contato" | qualquer autenticado ([`contacts.py:330`](../../backend/app/routers/contacts.py) sem gate) |
| P5 | Marcar aptos a liderar (= fez o Reencontro) | app. | Pessoas → editar → checkbox "Apto a liderar" | **só admin** ([`contacts.py:448`](../../backend/app/routers/contacts.py)) |
| P6 | Criar a **primeira célula** (líder = pessoa apta) | app. | **Alvo: Central de Células → Gerenciar células → "Nova célula"** (PRD Central §6). **Interino hoje: deep-link `#celulas`** (tela legada, único CTA existente — [`CelulasScreen.tsx:270-283`](../../frontend/src/components/cells/CelulasScreen.tsx)) | admin, pastor, lider_g12 ([`cells.py:37`](../../backend/app/routers/cells.py)) |
| P7 | Convidar equipe (entra **sempre como `membro`**, com célula obrigatória) → depois **promover papéis** (pastor, líderes, operador) | admin. | Usuários do Sistema → convite; depois editar papéis (`PUT /team/{id}/roles`, admin-only) | admin/pastor/lider_celula convidam; só admin promove |
| P8 | Configurar Google Agenda (OAuth por igreja + escolher calendário) e destinatários de avisos internos | admin. | Integrações | admin |
| P9 | Agenda: criar eventos ou importar do Google (botão admin-only) | app. | Agenda | admin/pastor |
| P10 | Conferir Assinatura (status do plano) | admin. | Assinatura | **só dono** (`require_owner`) |

Notas:

- **P4 antes de P5/P6/P7:** não existe import em massa de Pessoas (verificado: nenhum endpoint/tela CSV em `contacts.py`) — cadastro é manual, um a um, ou via agente WhatsApp registrando conversas. Limitação assumida no MVP (candidato a PR futuro, §11).
- **P6 antes de P7:** convite de equipe **exige célula** ([`team.py:332-336`](../../backend/app/routers/team.py) — admin/pastor sem `celulaId` recebem 422 "Selecione a célula do convidado"). Igreja sem célula não convida ninguém pela tela de equipe. Detalhe em §9.1.
- **"Primeiro pastor":** o caminho é P4 (pastor como Pessoa) + P7 (convite como membro → promover a `pastor`). Nenhum doc anterior encadeia esses passos; o convite **não** permite escolher papel (drift com US-03, §8.2).
- **P3/agente:** ver §8.5 — o comportamento real do "ligar agente" divergiu da spec.

## 5. Onde cada cadastro vive (matriz canônica)

| Ação | Superfície | Tela | Endpoint | Papel mínimo |
|---|---|---|---|---|
| Criar igreja / aprovar / plano / nome / dono | painel. | Console master | `POST/PATCH /admin/igrejas*` | master (`platform_admins`) |
| Pessoa (criar) | app. | Pessoas → Novo contato | `POST /contacts` | qualquer autenticado |
| Pessoa (editar, apto, CSIM) | app. | Pessoas → editar | `PATCH /contacts/{id}` | admin |
| Apto a liderar | app. | Pessoas → editar → checkbox | `PATCH /contacts/{id}` (campo `aptoLider`) | admin (CSIM nunca é apto — 422) |
| Célula (criar) | app. | Alvo: Central → Gerenciar células. Hoje: `#celulas` (legada) | `POST /cells` | pastor, lider_g12 (admin implícito) |
| Célula (campos sensíveis: anfitrião/auxiliar/endereço/dia/hora) | app. | Solicitação → aprovação da Central | `/cells/*/requests` | líder solicita; Central decide (flag `CELULAS_REQUESTS_ENABLED`) |
| Convite de equipe | admin. | Usuários do Sistema | `POST /team/invite` | admin, pastor, lider_celula (célula obrigatória; entra `membro`) |
| Papéis (promover a pastor/líder/operador) | admin. | Usuários do Sistema | `PUT /team/{id}/roles` | admin |
| WhatsApp (instância) | admin. | Conexão WhatsApp | `GET/POST /whatsapp/connection` | admin |
| Chave LLM do agente | admin. | Agente IA | `POST /agent/credential` | admin |
| Agente (comportamento/template/toggle) | painel. | Console master | `PUT /admin/igrejas/{id}/agente` | master (admin só solicita via `agent_config_requests`) |
| Google Calendar (OAuth + calendário) | admin. | Integrações | `/calendar/connect|status|list` + `PUT` | admin |
| Import de eventos do Google | app. | Agenda (botão admin-only no card) | `POST /calendar/import` | pastor (admin implícito) |
| Destinatários de avisos da agenda | admin. | Integrações → card destinatários | `/calendar/recipients` (CRUD) | admin |
| Evento (criar/editar/confirmar) | app. | Agenda | `/events*` | pastor (admin implícito) |
| Assinatura | admin. | Assinatura | — | dono (`require_owner`) |

Regra transversal de permissão: **admin passa em qualquer gate** (`has_role`/`has_any_role`, [`deps.py:63-70`](../../backend/app/deps.py)). Gates que dizem "pastor" (ex.: import do Google) incluem admin implicitamente — não é inconsistência.

## 6. Estados vazios e CTAs necessários

Estado atual verificado: **nenhum empty state do produto tem botão de ação**. O componente `DataTable` só aceita `{icon, title, hint}` ([`DataTable.tsx:28,44-51`](../../frontend/src/components/ui/DataTable.tsx)); os CTAs de criação vivem sempre no header das telas. O único empty state especificado com CTA é o da Central ("igreja nova": "Nenhuma célula cadastrada ainda." + CTA "Nova célula" — PRD Central §4.1), **não implementado**.

CTAs necessários para o primeiro dia (todos frontend-only, plano em §10):

| Tela | Empty state hoje | CTA necessário | Papel |
|---|---|---|---|
| Central → Gerenciar células | 3 listas de leitura, sem botão | **"Nova célula"** (o principal desta missão) | pastor/admin |
| Central → Dashboard (rede vazia) | dashboard zerado | "Nova célula" (espelho do PRD Central §4.1) | pastor/admin |
| Pessoas | "Nenhum contato ainda." + hint | "Novo contato" no empty (botão já existe no header) | qualquer |
| Agenda | "Nenhum evento em {período}…" | "Novo evento" no empty (botão já existe no header) | pastor/admin |
| Dashboard (igreja vazia) | "Fila zerada." | Link para o checklist de primeiros passos (PR-O4) | admin |
| Minha Célula (líder sem célula) | "Você ainda não tem uma célula ativa." | **Nenhum CTA de criação** — manter texto "a Central cadastra/atribui" (invariante §1) | — |

## 7. Permissões

- 8 papéis por tenant (`VALID_ROLES`, [`team.py:42-51`](../../backend/app/routers/team.py)): `admin`, `operador`, `pastor`, `lider_g12`, `lider_consol`, `lider_celula`, `lider_mult`, `membro`. Não existe `secretaria` (o mais próximo é `operador`) nem `lider_central` (explicitamente futuro — [`deps.py:34`](../../backend/app/deps.py); no MVP, Central = pastor+admin, Decisões Finais §3.1).
- `admin` tem acesso implícito a tudo; `dono` é derivado por request (`dono_id == app_user.id`) e é o único que vê Assinatura (`require_owner`).
- Liderança de célula é **derivada** (`celulas.lider_id` em célula ativa), nunca de `pessoas.tipo` — regra do dono 2026-07-06, já em produção.
- Matriz papel×tela editável em runtime (`role_permissions`, tela Permissões, admin-only); menu = união dos papéis do usuário.
- Console master é plano separado (`platform_admins`, sem tenant, BYPASSRLS auditado) — master não herda acesso a dados operacionais do tenant.

## 8. Contradições doc ↔ código (verificadas no scout)

| # | Contradição | Fonte doc | Realidade no código | Tratamento |
|---|---|---|---|---|
| 8.1 | **Quem cria célula e onde.** Docs: só Central (pastor/admin), botão na aba Gerenciar células | Contrato UX §8.2; PRD Central §6 | `CELL_CREATE_ROLES = ["pastor","lider_g12"]` + admin implícito ([`cells.py:37`](../../backend/app/routers/cells.py)); Central **não tem o botão**; único CTA na tela legada `#celulas` (deep-link, fora do menu, acessível a 5 papéis pela matriz default) | PR-O1 põe o CTA na Central; decisão pendente: alinhar `CELL_CREATE_ROLES` à spec (tirar `lider_g12`?) e destino da `#celulas` (matar CTA? redirect?) |
| 8.2 | **Convite com papel.** US-03: "convida informando e-mail e papel" | `stories-requisitos*.md:41-48` | Convite entra **sempre `membro`** + célula obrigatória; papéis só depois (`PUT /team/{id}/roles`, admin-only). Quem convida também diverge (código inclui `lider_celula`) | PR-O2 decide: implementar papel no convite OU oficializar convidar→promover (atualizar US-03) |
| 8.3 | **"Dono nasce sem Pessoa" (C2 do doc EVT-7)** | `AGENDA-EVENTOS-EVT7-destinatarios-alerta.md:32-46` | Desatualizado para igrejas novas: `POST /auth/activate` exige telefone e cria a Pessoa (delta-049 Parte B). C1 (dono só-admin) continua válido | Este doc corrige o registro; sem código |
| 8.4 | **Sidebar única do Contrato UX §3.1** (grupos ADMINISTRAÇÃO/CONFIGURAÇÃO no app) | Contrato UX §3.1 | Pós-PR #101: Configuração inteira migrou para `ADMIN_NAV_SECTIONS` em admin./`/gestao`; app tem só Igreja/Jornada/Gestão ([`navigation.ts:44-138`](../../frontend/src/lib/navigation.ts)); sem Árvore Ministerial | Adendo pós-3-superfícies ao Contrato UX (PR-O5); este doc é a descrição vigente |
| 8.5 | **"Master liga o agente."** Spec/fluxo assumido: admin cadastra chave → master ativa (`PUT /admin/igrejas/{id}/agente`, 409 sem credencial) | delta-043; scout | O runtime **não lê `AgentConfig.ativo`** em lugar nenhum ([`runtime.py:68`](../../backend/app/agent/runtime.py) é o único gate — credencial `validado`+`ativo`); e a credencial já nasce `validado=true, ativo=true` quando o admin cadastra chave válida ([`agent.py:118-119`](../../backend/app/routers/agent.py)). **No fluxo inbound, o agente responde assim que a chave válida é cadastrada, independente do toggle do master.** A confirmar se `AgentConfig.ativo` tem efeito em outro caminho (cron/KB) antes de qualquer correção | Registrar; decisão do dono necessária (o toggle do master deve valer? então o runtime precisa lê-lo — PR futuro fora desta missão) |
| 8.6 | **Console master em `admin.igreja12.com.br`** | PRD linha 122 (nota 2026-06-15) | Console vive em **painel.** desde PR #101; `admin.` é do admin da igreja | Atualizar PRD (PR-O5) |

## 9. Riscos

### 9.1 Gargalo circular do primeiro dia (verificado)

`convidar equipe` exige célula ([`team.py:332-336`](../../backend/app/routers/team.py)) → `criar célula` exige líder apto ([`cells.py:288-341`](../../backend/app/routers/cells.py) — 422 se não apto) → `apto` exige Pessoa cadastrada e só admin marca → cadastro de Pessoas é manual, um a um. **Ordem obrigatória: Pessoas → apto → célula → convites.** Se o admin tentar na ordem intuitiva (convidar a equipe primeiro), recebe 422 sem orientação. Nenhuma tela explica isso. Mitigação: checklist deste doc (curto prazo) + PR-O4 (card de primeiros passos na UI).

### 9.2 Criação da 1ª célula escondida

O caminho interino é um deep-link legado (`#celulas`) que não aparece em menu nenhum. O admin que seguir a spec (procurar na Central) não encontra o botão. PR-O1 é a correção prioritária.

### 9.3 Billing / Assinatura (decisão provisória do dono, 2026-07-06)

- O **master/painel é responsável** por plano, cobrança e bloqueio inicial; o admin da igreja **não resolve billing técnico no onboarding**.
- O checklist do admin **pode mostrar** o status da assinatura, mas **não deve bloquear** o cadastro inicial de pessoas/células por falta de configuração do Asaas.
- **Risco operacional do provisionamento master:** o código bloqueia o login da igreja inteira quando `status='inadimplente'` (`BLOCKING_IGREJA_STATUSES`, [`deps.py:40`](../../backend/app/deps.py)). Um provisionamento com billing mal configurado pode derrubar a igreja **semanas depois** do onboarding, sem qualquer aviso prévio na superfície do admin. Cabe ao master garantir plano/cobrança corretos antes de aprovar; monitoramento disso é dele.

### 9.4 WhatsApp conectado com agente sem credencial (comportamento verificado por código)

Cadeia: webhook autentica e enfileira ([`whatsapp.py:252-308`](../../backend/app/routers/whatsapp.py)) → worker **sempre persiste** Pessoa/Conversation/Message (ingestão independe do agente; erro do agente nunca perde a mensagem — [`queue_worker.py:395-406`](../../backend/app/workers/queue_worker.py)) → sem credencial validada/ativa, o runtime loga `agent_skipped_no_credential` e **não responde** ([`runtime.py:373-384`](../../backend/app/agent/runtime.py)). Ou seja: entre P2 e P3 do checklist, mensagens **entram no inbox sem auto-resposta** — comportamento correto, mas que precisa ser dito ao admin ("conectou e ninguém responde" é o esperado até a chave LLM existir). Nota: verificado por leitura de código, não exercitado em runtime de produção. Edge adicional: template do master vazio → igreja sem AgentConfig (§3).

### 9.5 Destinatários de avisos da agenda (EVT-7)

Igreja nova nasce com `destinatarios=0` — os avisos internos de evento ficam inertes até o admin cadastrar destinatários em Integrações. Estado da infraestrutura: migration `20260701_193000_evt7_pr2_agenda_alert_recipients.sql` existe no repo; tabela `agenda_alert_recipients` **confirmada no banco DEV** (verificação read-only via MCP, 2026-07-06); card `AlertRecipientsCard` vivo na superfície admin (PR #101). **Aplicação da migration em PROD: a confirmar** (não foi possível verificar o banco de produção neste scout). A flag global `AGENDA_NOTIFY_ENABLED` segue OFF por padrão.

### 9.6 Nome da igreja é read-only para o admin

RLS de `igrejas` é SELECT-only para o tenant; só o master edita nome (`PATCH /admin/igrejas/{id}`). Erro de digitação no provisionamento exige chamado ao master.

### 9.7 Flag `CELULAS_REQUESTS_ENABLED` sem tratamento no frontend

Com a flag OFF (default), toda escrita do fluxo Solicitação→Aprovação retorna 503 e o frontend não tem estado "módulo desativado". Não afeta a criação direta de célula (P6), mas afeta alterações sensíveis logo depois do onboarding.

## 10. Plano de PRs futuros

Nenhum é desta missão. Ordem sugerida; todos pequenos e reversíveis; escrita sensível atrás de flag quando aplicável.

| PR | Escopo | Tipo | Conteúdo |
|---|---|---|---|
| **PR-O1** | frontend-only | prioritário | CTA "Nova célula" na Central (aba Gerenciar células) reusando `CellFormModal`; empty state da rede com botão (fecha PRD Central §4.1/CA-14). Decidir junto: destino do CTA da `#celulas` legada |
| **PR-O2** | backend+frontend | decisão do dono antes | Convite com papel (fecha US-03) **ou** doc oficial do fluxo convidar→promover + ajuste da US-03. Inclui decidir se convite de equipe deve continuar exigindo célula (o 422 é a raiz do gargalo 9.1) |
| **PR-O3** | backend+frontend | dívida conhecida | Pastor/Central marcam "apto a liderar" (hoje só admin via `PATCH /contacts`); CTA de aptidão a partir da Central (pergunta aberta 17.10 do PRD Central) |
| **PR-O4** | backend+frontend | núcleo do onboarding | Card "Primeiros passos" na superfície admin (`/gestao`): endpoint read-only agregado (WhatsApp conectado? chave LLM? Google? destinatários? pessoas>0? aptos>0? célula>0? assinatura ok?— status informativo, sem bloquear nada, conforme §9.3) + card com links diretos por passo. Zero escrita |
| **PR-O5** | docs-only | manutenção | Atualizar PRD linha 122 (console = painel.), registrar decisão real da US-03, adendo pós-3-superfícies no Contrato UX §3.1 |
| **PR-O6** | backend | depende de decisão 8.5 | Se o dono confirmar que o toggle do master deve valer: runtime passa a ler `AgentConfig.ativo` (flag-off, com cuidado para não silenciar igrejas já ativas) |

Fora de numeração (backlog de produto, maiores): import CSV de Pessoas; runbook de provisionamento de igreja + seed do `platform_admin` em `docs/ops/`.

## 11. Fora de escopo

- Qualquer código, migration, env, deploy ou mudança de infraestrutura (esta missão é docs-only).
- Import em massa de Pessoas (registrado como lacuna; backlog).
- Self-service de cadastro de igreja / webhook Clerk de provisionamento (o status `aguardando_aprovacao` já antevê isso; fora do MVP).
- Wizard interativo de onboarding (multi-step guiado). O MVP proposto é o **card de checklist read-only** (PR-O4) — um wizard é evolução posterior.
- Papéis novos (`lider_central`, `secretaria`).
- Telas de UV/CD/Encontro (produção da aptidão continua manual via Pessoas; a gestão de aptos pela Central é PR-O3).
