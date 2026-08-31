# SPEC - PastorAI 1.0 (MVP)
> Gerado automaticamente pelo Development Pipeline 2.0. Fonte de verdade para implementacao.
>
> Design Lock travado em 2026-06-12 (status APROVADO, 13/13 regras). O `design-contract.json` e a fonte oficial de telas, rotas, navegacao, componentes, estados de UI, tokens, data requirements e api expectations. Nenhuma tela fora do lock foi adicionada; a direcao visual nao foi alterada.
>
> Artifact HTML do design lock: `docs/Docs20260611_163530/design/artifact.html`
> Contract: `docs/Docs20260611_163530/design/design-contract.json` (sha256 `fd65bdb967cad3395651b2c8d0126fd0db225999d9b4dda49800f174945930c4`)

---

## 1. Resumo do Produto

### Problema, publico-alvo, pitch
- **Problema:** lideres e pastores perdem pessoas por falta de acompanhamento estruturado — visitantes sem celula, decisoes por Jesus sem consolidacao, relatorios de celula que nao chegam e atendimentos sem resposta. A rotina e operacional, dispersa em planilhas e conversas pessoais.
- **Pitch:** o **PastorAI** e um SaaS multi-tenant para igrejas no modelo de celulas G12 que usa o WhatsApp oficial como interface operacional principal para atendimento, consultas, tarefas e atualizacoes autorizadas. O painel web organiza a **fila de pendencias** ("o que exige acao hoje") e concentra configuracao, governanca, supervisao, excecoes e acoes sensiveis.
- **Publico-alvo (personas):**
  1. **Pastor / Admin da Igreja** — responsavel maximo; ve pendencias, toma decisoes sensiveis, configura o sistema.
  2. **Lider de Celula** — rotina semanal; envia relatorio por WhatsApp, acompanha membros/visitantes, recebe alertas. Nao acessa inbox nem configuracao.
  3. **Usuario final via WhatsApp** (visitante/membro/lider) — resolve a rotina pelo WhatsApp; o painel e opcional para uso comum e obrigatorio apenas quando uma acao sensivel exigir autenticacao web.
  4. **Equipe de Consolidacao** — acompanha decisoes por Jesus; acesso restrito ao Dashboard de Consolidacao.
  5. **Admin do Sistema (Super-Admin)** — gere igrejas/tenants do SaaS; superficie separada (fora do MVP operacional — stub).

### Stack escolhida (copiada do PRD)
| Camada | Tecnologia |
|--------|-----------|
| Frontend | **Next.js** (web responsivo mobile-first + **PWA**) |
| Backend | **FastAPI + LangGraph** (agente orquestrador) |
| Worker | **Worker de filas** para webhooks de mensagens |
| WhatsApp | **Evolution API** (processo sempre-ligado) |
| Autenticacao | **Clerk** (sem senhas proprias) |
| Banco de dados | **Supabase (Postgres + RLS)** |
| E-mail | **Brevo** (convites/ativacao, com gate proprio) |
| Calendario | **Google Calendar** (sincronizacao de eventos) |
| Pagamento | **Asaas** (PIX, boleto, cartao; setup fee + mensalidade) |
| LLM | **OpenAI (BYO-LLM)** — credencial da propria igreja; OpenRouter nao integra o PastorAI |
| Infra | **Coolify/Dokploy** em VPS unica >= 4GB RAM, TLS automatico (Let's Encrypt) |

### Plataforma
- **Web** responsiva mobile-first + **PWA** (sem app nativo iOS/Android no MVP — RNF-19).
- **WhatsApp** e a interface operacional principal para membros e liderancas.
- **Web** concentra configuracao inicial, governanca, excecoes, supervisao e conclusao autenticada de acoes sensiveis.

### User stories cobertas (id / titulo)
| ID | Titulo |
|----|--------|
| US-01 | Login no painel |
| US-02 | Isolamento de dados por igreja (multi-tenant) |
| US-03 | Gestao de usuarios da igreja |
| US-04 | Controle de acesso por papel |
| US-05 | Conectar o numero oficial da igreja |
| US-06 | Monitorar e reconectar o WhatsApp |
| US-07 | Nao registrar conversas pessoais do pastor |
| US-08 | Atendimento automatico de quem chama a igreja |
| US-09 | Coleta de dados e criacao de contato pelo agente |
| US-10 | Onboarding de contato/visitante pelo agente |
| US-11 | Lista de conversas (inbox) |
| US-12 | Assumir atendimento (pausar IA) |
| US-13 | Devolver atendimento para a IA |
| US-14 | Fila de atendimentos humanos aguardando |
| US-15 | Dashboard de pendencias pastorais |
| US-16 | Acoes diretas na fila de trabalho |
| US-17 | Proximas acoes por responsavel |
| US-18 | Lista de visitantes sem acompanhamento |
| US-19 | Detalhe do contato |
| US-20 | Conectar visitante a uma celula |
| US-21 | Cadastro de celulas |
| US-22 | Membros e visitantes de uma celula |
| US-23 | Alertas sobre liderados |
| US-24 | Enviar relatorio de celula pelo WhatsApp |
| US-25 | Visualizar relatorios de celula no painel |
| US-26 | Relatorio pendente vira acao na fila |
| US-27 | Cadastrar credencial do provedor LLM (BYO) e selecionar modelo permitido por igreja |
| US-28 | Configurar comportamento do agente |
| US-29 | Configurar crons e agendamentos do agente |
| US-30 | Gerir eventos no calendario |
| US-31 | Registrar consentimento de comunicacao |
| US-32 | Opt-out de comunicacao |
| US-33 | Envio segmentado de comunicados |
| US-34 | Contratar assinatura com setup fee |
| US-35 | Acompanhar status da assinatura |
| US-36 | Upgrade automatico de plano por porte |
| US-37 | Lancar decisao por Jesus e iniciar consolidacao |
| US-38 | Dashboard de Consolidacao (acesso restrito) |
| US-39 | Acompanhar etapas e concluir a consolidacao |
| US-40 | Pendencias de consolidacao (conexao a celula e fonovisita) |
| US-41 | Assistente geral do sistema no painel |
| US-42 | Gerir igrejas (tenants) do SaaS — *stub / superficie separada* |
| US-43 | Provisionar nova igreja — *stub / superficie separada* |

---

## 2. Database Schema

> Fundacoes obrigatorias do Design Lock:
> - **F1 (RNF-21):** toda tabela nasce com `igreja_id` e isolamento por tenant via RLS. A igreja piloto e apenas o 1o registro de `igrejas`.
> - **F2 (RNF-22):** maturidade da pessoa e UM campo de estado (`pessoas.etapa`/`subetapa`) governado por regras (state machine).
> - **F3 (delta-032):** papeis sao **acumulados** por pessoa; menu/dashboard = uniao dos acessos.
> - **F6 (delta-035):** modelo de **pessoa unificado** — Conhecendo/Visitante/Discipulo/Lider/Pastor sao estados da mesma linha.
> - **F7 (RNF-25):** relacao lider->liderado e campo de lideranca no cadastro (`pessoas.lider_id`).
> - **F8 (RNF-24):** logs de conversacao do agente e consumo de IA por igreja desde o dia 1.

### 2.1 Tabelas

> **Atualizado em 2026-07-18:** esta secao lista as **45 tabelas reais** de
> `backend/app/db/models.py` (fonte de verdade do schema, junto com
> `backend/migrations/`). O detalhamento campo a campo do desenho original de
> 2026-06-11 foi substituido por esta visao de inventario; consulte os models
> e as migrations para colunas, constraints e indices.

| Tabela | Proposito |
|--------|-----------|
| `igrejas` | Raiz do tenant (F1); unica tabela core sem `igreja_id`. |
| `pessoas` | Modelo unificado de pessoa (F2/F6/F7): contato/visitante/membro/lider/pastor sao estados da mesma linha. |
| `app_users` | Usuario do painel autenticado via Clerk. |
| `password_reset_tokens` | Um registro por link de "esqueci a senha" (`jti` + uso unico — SEC-3B/MEDIO-003). |
| `user_roles` | Papeis acumulados por usuario (F3). |
| `role_permissions` | Matriz papel x tela (delta-010). |
| `celulas` | Celula (grupo). |
| `celula_membro` | Vinculo canonico pessoa<->celula; fonte de verdade da participacao (`pessoas.celula_id` e espelho legado). |
| `celula_reuniao` | Ocorrencia materializada de reuniao de celula (data/hora), com ciclo de relatorio. |
| `celula_presenca` | Presenca de uma pessoa numa reuniao (UNIQUE por reuniao+pessoa; confirmada/compareceu/ausente). |
| `celula_expectativa_visitante` | Visitante esperado por um membro para uma reuniao (sem UNIQUE — N por membro). |
| `celula_reuniao_registro` | Registro pastoral da reuniao (decisao/oracao/observacao); oculto do discipulo. |
| `celula_visitante` | Visitante presente numa reuniao; pode referenciar a expectativa que o antecedeu. |
| `celula_solicitacao` | Solicitacao de alteracao sensivel / multiplicacao (extensivel por `tipo` + payload proposto). |
| `celula_solicitacao_evento` | Trilha APPEND-ONLY das transicoes de uma solicitacao (trigger bloqueia UPDATE/DELETE). |
| `celula_aviso` | Aviso da celula (origem=celula) ou da Central (origem=central); escopo celula/igreja. |
| `celula_material` | Material de apoio publicado pela Central (link/metadados, sem upload real). |
| `cell_alerts` | Alerta pastoral levantado para uma pessoa dentro de uma celula. |
| `conversations` | Thread de conversa WhatsApp vinculada a uma pessoa (F6). |
| `messages` | Mensagem cronologica dentro de uma conversa (F6). |
| `work_queue_items` | Item acionavel da fila de trabalho compartilhada (F5). |
| `decisions` | Decisao por Jesus (US-37); INSERT dispara abertura de consolidacao via trigger. |
| `consolidacoes` | Trilha de consolidacao individual por pessoa (US-38/39, delta-018). |
| `consolidacao_etapas` | Etapa da trilha individual; confirmacao restrita ao `responsavel_id` (consolidador). |
| `multiplicacoes` | Multiplicacao de celula (enviar — delta-027); transacional e idempotente (Celulas PR3-PR9). |
| `crons` | Job agendado / gatilho por estado executado pelo cron_worker. |
| `subscriptions` | Assinatura de billing (1:1 com igreja); usada no gate de login. |
| `reports` | Tabela legada de relatorio semanal, sem writer na aplicacao vigente; nao e fonte operacional. O fluxo canonico usa `celula_reuniao` e `relatorio_snapshot`. |
| `broadcasts` | Comunicado segmentado (RF-38); respeita opt-out no envio. |
| `events` | Evento da igreja (RF-39 / Agenda); opcionalmente espelhado no Google Calendar. |
| `event_notify_targets` | Contato individual a notificar de um evento (EVT-8), vindo de `conversations`. |
| `calendar_sync` | Conexao Google Calendar por igreja + estado de sync (tokens OAuth cifrados). |
| `agenda_alert_recipients` | Destinatario opt-in de avisos internos da Agenda por WhatsApp (EVT-7 PR2). |
| `whatsapp_connections` | Conexao WhatsApp oficial por igreja (1:1; UNIQUE em `igreja_id`). |
| `pessoa_arquivamento_evento` | Trilha APPEND-ONLY de arquivamento/reativacao de Pessoa (W3.2A). |
| `consent_records` | Registro legado do consentimento geral concedido na primeira mensagem inbound. Nao concede por inferencia nenhuma finalidade D2B2a. |
| `consentimento_finalidade_evento` | D2B2a integrada e inativa, append-only para concessao/retirada por finalidade, ainda sem caller, backfill ou aplicacao em ambiente compartilhado. |
| `purpose_consent_governance_envelope` | D2B2b3A draft-only: no maximo um envelope por igreja, com exatamente quatro rascunhos operacionais, revisao por finalidade e nenhum campo de aprovacao, digest, catalogo ou writer. |
| `agent_configs` | Config de comportamento do agente por igreja (1:1, US-28). |
| `agent_config_requests` | Requisicao admin -> master para mudar o agente (#10b Fase 1 / delta-043). |
| `llm_credentials` | Credencial LLM BYO + modelo permitido por igreja (1:1; chave cifrada, nunca exibida — RNF-03). |
| `ai_usage_logs` | Log de consumo de IA por igreja: modelo/tokens/custo (F8/RNF-24). |
| `agent_conversation_logs` | Auditoria de eventos do agente/webhook numa conversa (F8/RNF-24). |
| `planos` | Catalogo global de planos do SaaS (referencia sem `igreja_id`; CRUD do master). |
| `platform_audit_log` | Auditoria imutavel das acoes cross-tenant do console master (M3; plano de plataforma). |
| `platform_admins` | Allowlist de Super-Admin (plano de plataforma; sem `igreja_id`/RLS por tenant). |
| `platform_orchestrator` | Modelo padrao do orquestrador (1 linha do master), copiado para o `AgentConfig` da igreja na aprovacao. |

### 2.2 RLS Policies
> RNF-02 / F1 / F4 (delta-033): isolamento por tenant em nivel de banco; autorizacao **revalidada no backend** (igreja_id + papel) em todo endpoint.

- **Habilitar RLS** em TODAS as tabelas com `igreja_id`.
- **igreja_id de contexto:** derivar de `app_users.igreja_id` a partir do `clerk_user_id` autenticado (claim Clerk) — funcao `current_igreja_id()`.
- **Policy padrao (SELECT/INSERT/UPDATE/DELETE):**
  ```sql
  USING (igreja_id = current_igreja_id())
  WITH CHECK (igreja_id = current_igreja_id());
  ```
- **`igrejas`:** SELECT apenas do proprio registro (`id = current_igreja_id()`); INSERT/gestao global apenas via service role (Super-Admin — fora do MVP operacional).
- **Restricoes por papel (aplicadas no backend, espelhadas em policies onde aplicavel):**
  - `inbox`/`conversations`/`messages`: somente papeis com privilegio (admin/pastor ou usuario liberado ao atendimento humano); lideres de celula NAO acessam (US-11).
  - `consolidacoes`: leitura restrita a `lider_consol`/admin/pastor (US-38); confirmacao de etapa apenas pelo `responsavel_id` (consolidador) — gate por identidade (delta-018).
  - Telas de Configuracao (`whatsapp`,`agente`,`assinatura`,`gerentes`,`permissoes`): apenas papel `admin` (delta-005).
  - `celulas`: abrir/editar apenas lider da celula ou superior na hierarquia (delta-007).
- **Agente (F5/delta-034):** fixa o tenant no servidor e executa sob papel sem `BYPASSRLS`, com as mesmas validacoes de negocio de um humano. Service role nao substitui escopo, RLS ou autorizacao.
- **D2B2a integrada e inativa:** `consentimento_finalidade_evento` habilita e forca RLS. Uma policy restritiva exige `app.tenant_igreja_id` fixado pelo backend; JWT ou `current_igreja_id()` sem esse GUC nao liberam linhas. `authenticated` recebe somente SELECT e INSERT nas colunas de entrada; `PUBLIC`, `anon`, `service_role` e `agent_runtime` nao recebem privilegios de tabela. UPDATE, DELETE e TRUNCATE permanecem revogados. A migration ainda nao foi aplicada em Supabase.
- **D2B2b3A draft-only:** `purpose_consent_governance_envelope` habilita e forca RLS, nao expoe policy de Data API e revoga privilegios de `PUBLIC`, `anon`, `authenticated`, `service_role` e `agent_runtime`. Somente o caminho auditado do Console Master, com igreja explicita e identidade server-side, pode preparar o rascunho. Esta missao nao aplicou a migration D2B2b3A; DEV e PROD confirmaram a ausencia.

No baseline `15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`, o preflight PROD
somente leitura confirmou `DATABASE_URL` presente e
`M06_MIGRATION_DATABASE_URL` ausente. `current_user` e `session_user`
convergiram para a mesma identidade sanitizada; a role runtime possui
`NOSUPERUSER`, `BYPASSRLS`, `LOGIN` e `INHERIT`, e owner de `public.igrejas` e
`public.app_users` e possui `SELECT` e `REFERENCES` efetivos nessas tabelas-pai.
A tabela alvo D2B2b3A, o validator e a propria `public.schema_migrations`
estavam ausentes. A flag `PURPOSE_CONSENT_GOVERNANCE_DRAFTS_ENABLED` permaneceu
`false`. Esta missao nao aplicou a migration D2B2b3A; DEV e PROD confirmaram a
ausencia. A PR #321 integrou a reconciliacao documental anterior no merge
`15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`; esse merge gerou o deployment
automatico Vercel frontend Production `6141449639`, com `SUCCESS`, em
2026-08-28T12:53:35Z. Essa metadata prova somente o frontend, sem provar backend,
banco ou Supabase. O preflight VPS em si nao executou deploy manual ou do
backend, migration, restart ou alteracao da flag. A leitura comprova identidade,
ownership e ACL do caminho runtime atual, mas nao o comportamento da tabela
futura sob `FORCE RLS`; o caminho de migration permanece bloqueado pela ausencia
de `M06_MIGRATION_DATABASE_URL` e do ledger publico.

### 2.3 Triggers
- **`trg_promote_pipeline`** (BEFORE INSERT/UPDATE em `pessoas`) — state machine F2/delta-013/031: avanca `etapa`/`subetapa` automaticamente quando `presencas_celula >= 3` OU `aceitou_jesus = true` (visitante -> membro). Conclusao de consolidacao usa seu proprio fluxo.
- **`trg_link_cell_promote`** (BEFORE UPDATE em `pessoas.celula_id`) — US-20: ao vincular contato a celula, `acompanhamento = consolidado/membro`, sai da lista "em acompanhamento".
- **`trg_report_received_clears_queue`** (legado; AFTER INSERT em `reports` com `status=recebido`) — permanece instalado, mas a aplicacao vigente nao escreve em `reports`; portanto nao integra o fluxo operacional. D6 deve atualizar a fila a partir do submit canonico de `celula_reuniao`, sem reativar esta tabela.
- **`trg_decision_opens_consolidation`** (AFTER INSERT em `decisions`) — US-37/delta-041: cria `consolidacoes` (etapa inicial); se `vinculo=visitante`, cria `work_queue_items` tipo `conectar_celula` com `prazo = now()+24h`.
- **`trg_consent_on_inbound`** (baseline legada; AFTER INSERT em `messages` direcao=in) — concede o booleano geral `pessoas.consentimento=true`. Esse comportamento nao satisfaz o delta-052 e deve ser substituido por eventos independentes de finalidade; o estado legado nao libera cuidado pastoral, tarefas operacionais ou comunicados.
- **Trigger de sequencia D2B2a** (integrado e inativo; BEFORE INSERT em `consentimento_finalidade_evento`) — serializa cada stream `(igreja_id, pessoa_id, finalidade)` com advisory lock transacional e atribui a proxima `sequencia`; unicidade por stream e `chave_idempotencia` por tenant fecham corrida e replay.
- **`trg_subscription_autoupgrade`** (AFTER INSERT/UPDATE em `pessoas`) — US-36/RF-42: ao ultrapassar `subscriptions.limite`, promove `plano` e marca notificacao ao admin.
- **`trg_set_updated_at`** — manutencao de `updated_at`.
- **`trg_sla_engine`** (cron/worker — A1/delta-039/RNF-23): detecta SLA estourando (relatorio 2h, conexao 24h, fonovisita 24h) e dispara cobranca por WhatsApp; escalona lider sem resposta -> coordenacao.

### 2.4 Seed Data
- **1 igreja piloto** em `igrejas` (status `ativa`, plano `ate_100`) — F1 (1o registro).
- **1 `app_user` admin** vinculado ao Clerk do Pastor, com `user_roles` = {`admin`,`pastor`}.
- **`role_permissions` default:** dashboard liberado a todos os papeis; demais telas conforme ciclo G12 (lider_celula: ganhar/central-celula/g12; lider_consol: consolidar/consol-individual).
- **`agent_configs`** default (comportamento/prompt base) e **`whatsapp_connections`** com status `offline`.
- **`subscriptions`** piloto (status `ativa`, limite 100).
- **Dados de dominio (contatos/celulas/relatorios/conversas):** amostras representativas para validar estados (delta-003) — NAO sao dados reais de producao.

### 2.5 Diagrama ER
```
igrejas (1) ──< (N) pessoas
igrejas (1) ──< (N) app_users ──< (N) user_roles
igrejas (1) ──< (N) role_permissions
igrejas (1) ──< (N) celulas ──< (N) pessoas (celula_id)
pessoas (1, lider_id) ──< (N) pessoas        # organograma G12 (F7)
celulas (1) ──< (N) cell_alerts >── (1) pessoas
celulas (1) ──< (N) celula_reuniao
igrejas (1) ──< (N) reports                    # legado, sem writer operacional
igrejas (1) ──< (N) conversations ──< (N) messages
conversations >── (1) pessoas
igrejas (1) ──< (N) work_queue_items >── (0..1) pessoas / app_users
igrejas (1) ──< (N) broadcasts
igrejas (1) ──< (N) events
igrejas (1) ──1 whatsapp_connections
igrejas (1) ──1 agent_configs
igrejas (1) ──1 llm_credentials
igrejas (1) ──< (N) crons
igrejas (1) ──1 subscriptions
igrejas (1) ──< (N) system_managers
igrejas (1) ──< (N) decisions >── (1) pessoas
pessoas (1) ──< (N) consolidacoes ──< (N) consolidacao_etapas
celulas (1) ──< (N) multiplicacoes >── (0..1) pessoas (novo_lider_id)
pessoas (1) ──< (N) consent_records
pessoas (1) ──< (N) consentimento_finalidade_evento >── (0..1) app_users  # D2B2a integrada e inativa
igrejas (1) ──1 purpose_consent_governance_envelope       # D2B2b3A draft-only
igrejas (1) ──< (N) ai_usage_logs / agent_conversation_logs
```

---

## 3. Backend

> **Nota (2026-07-18):** esta secao reflete o desenho original de 2026-06-11. O historico do que foi entregue/alterado depois esta em `docs/sprints/`.

> Stack: FastAPI (API REST) + LangGraph (agente orquestrador) + worker de filas (webhooks WhatsApp). Autorizacao real no backend (F4): cada endpoint revalida `igreja_id` + papel. Endpoints derivados 1:1 das `apiExpectations` do design lock.

### 3.1 Estrutura de Pastas
```
backend/
  app/
    main.py                 # FastAPI app, CORS, mount routers
    config.py               # settings / env
    deps.py                 # auth (Clerk), current_user, current_igreja_id, require_role
    db/
      session.py            # Supabase/Postgres client
      models.py             # ORM/SQLModel das tabelas (secao 2.1)
      rls.py                # contexto igreja_id
    routers/
      auth.py               # api-login
      work_queue.py         # api-queue-action, api-send-internal-message
      conversations.py      # api-conversations, api-conversation-handoff
      contacts.py           # api-contacts, api-create-contact, api-link-cell
      cells.py              # api-cells
      reports.py            # api-reports
      broadcasts.py         # api-broadcasts
      events.py             # api-events
      whatsapp.py           # api-whatsapp-connection (+ webhook)
      agent.py              # api-llm-credential, api-agent-config, api-crons
      team.py               # api-team-invite, api-team-roles
      subscription.py       # api-subscription (+ webhook Asaas)
      permissions.py        # api-role-perms
      pipeline.py           # api-pipeline
      descendencias.py      # api-descendencias
      multiplicacoes.py     # api-multiplicacoes
      system_managers.py    # api-system-managers
      consolidacao.py       # api-launch-decision
      assistant.py          # api-assistant
    services/
      evolution.py          # Evolution API client (QR, send)
      brevo.py              # convites/ativacao, gate BREVO_SEND_MODE
      gcal.py               # Google Calendar sync
      asaas.py              # checkout/cobranca
      llm.py                # provedor LLM (BYO) + cifragem de chave
      sla_engine.py         # A1 motor de SLAs
    agent/
      graph.py              # LangGraph: orquestrador
      nodes.py              # onboarding, coleta dados, relatorio por conversa
      tools.py              # mesmas funcoes de um humano (F5)
    workers/
      queue_worker.py       # processa webhooks (RNF-17), reprocesso
      cron_worker.py        # crons + gatilhos por estado (F9/RNF-23)
  migrations/               # schema (secao 2.1) + RLS + triggers
```

### 3.2 Endpoints
> Convencao: todos exigem auth Clerk (exceto webhooks com assinatura), aplicam `igreja_id` do tenant e revalidam papel.

| API ID | Operacao | Telas | Actions | Stories |
|--------|----------|-------|---------|---------|
| api-login | `POST /auth/login` | login | action-login | US-01, US-02 |
| api-queue-action | `POST /work-queue/{itemId}/action` | dashboard | action-queue-assume, action-queue-assign | US-16, US-17 |
| api-send-internal-message | `POST /work-queue/{itemId}/message` | dashboard | action-queue-message | US-16, US-17 |
| api-conversations | `GET /conversations` | inbox | action-open-conversation | US-08, US-11 |
| api-conversation-handoff | `POST /conversations/{id}/handoff` | inbox | action-assume-conversation, action-return-conversation | US-12, US-13 |
| api-contacts | `GET /contacts` | contatos, ganhar | action-open-contact, action-open-contact-ganhar | US-18, US-19 |
| api-create-contact | `POST /contacts` | contatos | action-new-contact | US-09, US-10 |
| api-link-cell | `POST /contacts/{id}/cell` | contatos, dashboard | action-link-cell, action-queue-connect-cell | US-20, US-40 |
| api-cells | `GET/POST /cells` | celulas | action-new-cell, action-edit-cell | US-21, US-22, US-23 |
| api-reports | `GET /reports` | relatorios, central-celula | action-view-report, action-charge-report | US-24, US-25, US-26 |
| api-broadcasts | `POST /broadcasts` | comunicados, central-celula | action-new/send/schedule-broadcast, action-message-leaders | US-31, US-32, US-33 |
| api-events | `GET/POST /events` | calendario | action-new-event | US-30 |
| api-whatsapp-connection | `GET/POST /whatsapp/connection` | whatsapp | action-connect-whatsapp, action-reconnect-whatsapp | US-05, US-06, US-07 |
| api-llm-credential | `GET /agent/models`, `GET/POST /agent/credential`, `PUT /agent/model` | agente | action-save-llm-key, action-select-llm-model | US-27 |
| api-agent-config | `PUT /agent/config` | agente | action-save-agent | US-28 |
| api-crons | `GET/POST /agent/crons`, `PUT /agent/crons/{id}` | agente | action-save-cron | US-29 |
| api-team-invite | `POST /team/invite` | equipe | action-invite-user | US-03, US-04 |
| api-team-roles | `PUT /team/{usuarioId}/roles` | equipe | action-edit-roles | US-03, US-04 |
| api-subscription | `GET/POST /subscription` | assinatura | action-contract-plan, action-manage-billing | US-34, US-35, US-36 |
| api-role-perms | `GET/PUT /roles/permissions` | permissoes | action-toggle-perm | US-04 |
| api-pipeline | `GET/PUT /pipeline` | ganhar, consolidar, consol-individual, universidade-vida, capacitacao | action-promote-visitante, action-open-consol-individual, action-open-uv, action-assign-consolidador, action-advance-stage, action-new-turma-uv, action-advance-trilha, action-queue-fonovisita | US-18, US-19, US-20, US-39, US-40 |
| api-descendencias | `GET /descendencias` | g12 | action-open-descendencia | US-21, US-22, US-23 |
| api-multiplicacoes | `GET/POST /multiplicacoes` | enviar | action-schedule-mult, action-approve-mult | US-21, US-22, US-23 |
| api-system-managers | `GET/POST/DELETE /system-managers` | gerentes | action-add-gerente, action-remove-gerente | US-03, US-04 |
| api-launch-decision | `POST /consolidacao/decisao` | consolidar, consol-individual | action-launch-decision, action-launch-decision-ci | US-37, US-40 |
| api-assistant | `POST /assistant/message` | dashboard (+ assistant-panel) | action-assistant-send | US-41 |
| api-super-admin-tenants* | `GET /super-admin/tenants` | super-admin-igrejas | action-open-tenant | US-42 |
| api-super-admin-provision* | `POST /super-admin/tenants` | super-admin-provisionar | action-provision-tenant | US-43 |

\* **Stub / fora do escopo operacional (delta-024):** documentado para rastreabilidade; **nao** implementar no painel da igreja — superficie separada (console multitenant).

**Contratos chave (request -> response):**
- `POST /auth/login` `{email,password}` -> `{token, churchId}`
- `POST /work-queue/{itemId}/action` `{action, assignee}` -> `{status}`
- `POST /work-queue/{itemId}/message` `{destinatarioId, remetente:{nome,papel}, canal:"whatsapp", texto}` -> `{status, messageId}` (prefixo "Nome [papel]: mensagem" — delta-006)
- `POST /conversations/{id}/handoff` `{to:"human|ia"}` -> `{estado}`
- `POST /contacts/{id}/cell` `{cellId}` -> `{status}`
- `POST /broadcasts` `{titulo,mensagem,segmentos,modo,agendamento:{data,hora,repeticao}}` -> `{status,enviados,ignoradosOptout,agendadoPara}`
- `POST /whatsapp/connection` `{action:"connect|reconnect"}` -> `{status, qr}`
- `POST /agent/credential` `{provedor,apiKey}` -> `{status}` (chave cifrada — RNF-03)
- `PUT /pipeline` `{pessoaId,etapa,subetapa}` -> `{status,etapa}`
- `POST /consolidacao/decisao` `{pessoa,origem,vinculo,celulaId}` -> `{status,consolidacaoId,etapa:"inicial",prazoConexao,responsavel}`
- `POST /assistant/message` `{tenantId,usuarioId,papeis,texto}` -> `{resposta,telasSugeridas}`

### 3.3 Middleware
- **Auth (Clerk):** valida JWT/sessao Clerk, popula `current_user`, `clerk_user_id` (US-01/RNF-01).
- **Tenant resolver:** deriva `current_igreja_id()` do `app_users` e injeta no contexto RLS (US-02/RNF-02).
- **RBAC (`require_role`)**: revalida papeis acumulados por endpoint; Config exige `admin`; inbox exige privilegio; consolidacao gate por consolidador (F4/delta-033).
- **HTTPS/TLS:** terminacao TLS automatica via Coolify/Dokploy (RNF-04).
- **Paginacao:** padrao em listas (RNF-09, ate 1.000 registros / 2s).
- **Rate/erro:** login com credenciais invalidas nao revela existencia de e-mail (US-01).
- **Webhook signature:** validacao de assinatura nos webhooks Evolution API e Asaas.
- **Idempotencia:** webhooks de mensagem nao geram contatos duplicados (RNF-16) — dedupe por telefone+igreja.

### 3.4 Agent Graph (LangGraph) — Orquestrador e especialistas
> Arquitetura alvo: uma **definicao global e versionada do LangGraph**, executada com contexto de
> tenant criado pelo servidor, coordena especialistas comuns a todas as igrejas. Dados, memoria,
> documentos, credenciais e acoes permanecem isolados por `igreja_id`. **Principio fundamental:**
> o Orquestrador e o **unico** que fala no
> **WhatsApp oficial da igreja** — recebe TODA mensagem do numero oficial, decide o roteamento,
> delega aos sub-agentes e consolida a **resposta unica** que sai pelo numero oficial. Os
> sub-agentes **nunca** falam diretamente com o usuario final: eles processam e devolvem o
> resultado ao Orquestrador (US-07: apenas conversas com o numero oficial sao tratadas).

- **Agente Orquestrador (US-08 / delta-034):** ponto unico de entrada e saida no WhatsApp oficial.
  Roteia toda mensagem recebida no numero oficial, recebe o contexto autorizado da conversa,
  escolhe qual(is) sub-agente(s) acionar, agrega os resultados e emite a resposta unica via
  LLM BYO (US-08/US-27/RF-11). E o `entry node`/supervisor do grafo LangGraph.

- **Sub-agentes coordenados (skills/nodes especializados — NAO falam direto no WhatsApp; respondem ao Orquestrador):**
  - `intake` — cria/atualiza `pessoas` (nome+telefone, origem, primeiro_contato) — US-09/RF-12.
  - `onboarding` — fluxo configuravel (nome, endereco, interesse, oracao, ja foi a igreja/celula); notifica consolidacao; classifica contato/visitante — US-10/RF-13.
  - `report_capture` — na baseline atual extrai o resumo agregado e registra evento de auditoria, sem gravar o relatorio canonico; a escrita apos confirmacao e a primeira vertical pendente — US-24/delta-041/delta-052.
  - `handoff` — pausa/retoma IA conforme estado da conversa; quando humano assume, o Orquestrador suspende a resposta automatica mas a saida continua pelo numero oficial — US-12/US-13.
  - `consent` — apresenta termo antes de coletar dados alem de nome+telefone (delta-040).
- **Roteamento:** o Orquestrador decide o sub-agente com base na intencao/estado da conversa e da `pessoa` (etapa/subetapa F2); transicoes e respostas trafegam de volta pelo supervisor antes de qualquer envio.
- **Distincao do Assistente do painel (US-41):** o `assistant-panel` e um agente **separado**, interno ao painel web, ciente de papel/tenant; **nao** se confunde com o Orquestrador do WhatsApp (canais e publicos distintos).
- **Tools (F5/delta-034):** registrar decisao, marcar presenca, vincular celula, avancar trilha — invocadas pelos sub-agentes/Orquestrador com as mesmas funcoes/validacoes de um humano, no escopo do tenant.
- **Logs (F8/RNF-24):** registrar interacoes, tools usadas, consumo de IA (modelo/tokens/custo) em `ai_usage_logs`/`agent_conversation_logs`, com mascara de dados sensiveis.
- **SLA engine (A1/delta-039):** detecta prazos (relatorio 2h, conexao 24h, fonovisita 24h, Numero de Sonho UV) e dispara cobranca/escalonamento por WhatsApp.

#### 3.4.1 Baseline implementada e arquitetura aprovada

O codigo atual compila um grafo **stateless**, sem checkpointer duravel. A variavel `AGENT_GRAPH_CHECKPOINT_URL` apenas gera aviso quando configurada; nao ativa persistencia. Os nodes atuais cobrem `handoff`, `optout`, `consent`, `report_capture` e `onboarding`. O `report_capture` registra um evento de auditoria, mas ainda nao grava o relatorio canonico de `celula_reuniao`. Esses pontos permanecem pendentes e nao podem ser tratados como entrega concluida.

A PR #315 integrou a D2B1 no `origin/main`
`84c5b71b415340868c1b0664e892b8b0350d91f4` sem alterar o estado stateless. O
servidor monta um `TrustedAgentContext` imutavel e tipado,
com UUIDs de igreja, conversa e Pessoa, estado da conversa, nome da igreja,
canal WhatsApp, termo legado e a instancia autoritativa de
`PrivilegeContext`. O LangGraph recebe essa fronteira por
`StateGraph.context_schema`; o `AgentState` conserva apenas dados mutaveis
minimos. A entrada e o snapshot de Pessoa rejeitam chaves de autoridade, IDs,
telefone e campos nao utilizados pelo turno. A validacao ocorre antes do caminho compilado, do
fallback direto e em cada node. Falhas de confianca propagam sem entrar no
fallback, que recebe a mesma instancia do contexto.

A fatia integrada nao implementa consentimento por finalidade, memoria,
checkpointer, proposta, ferramenta ou especialista novo. A integracao nao
adicionou migration, nao acessou Supabase, nao provisionou credencial nem
conectou a fronteira privada D2A, worker ou fila. O merge nao prova deploy,
ativacao ou canario.

A PR #317 integrou a D2B2a no `origin/main`: HEAD
`8ba5c988e9169703c923b1f1a3e47d1c427531e1`, merge
`bce5a9a434077e488cea8baae3e9dd7c7c4ba0f1`. A fatia adiciona a
migration de `public.consentimento_finalidade_evento`, o ORM
`ConsentimentoFinalidadeEvento`, tipos de dominio e um servico interno sem
caller. As quatro finalidades aceitam eventos `concedido|retirado` com
`versao_termo` e fonte `whatsapp_inbound|painel_autenticado`. No INSERT
inicial, o operador e obrigatorio somente para a fonte autenticada do painel;
no WhatsApp ele deve ser nulo. A exclusao referencial posterior do AppUser
pode anonimizar o operador via `ON DELETE SET NULL`, preservando o evento. A
projecao interna resulta em
`ausente|concedido|retirado|reaceite_necessario|bloqueado_optout_global`.

O ledger e append-only, usa idempotencia por tenant e sequencia por stream
atribuida no banco. Nao existe backfill: `consent_records` e
`pessoas.consentimento` continuam legados e o opt-out global prevalece. A
fatia nao expoe API, nao conecta WhatsApp, painel, worker, LangGraph, tool
ou broadcast, nao foi aplicada em Supabase e nao fez deploy manual ou do
backend, ativacao ou canario. O merge gerou somente o deployment frontend
automatico da integracao Vercel. Textos e base juridica por finalidade, retencao e RBAC ainda bloqueiam
qualquer writer e ambiente compartilhado.

A PR #318, HEAD `ede4797003e044f582da9f9a3ab86554f708a73a`, integrou a
D2B2b1 no merge `74951828f48994622a112d8e59eb978e5fb4f406`. Ela adiciona
somente uma fronteira pura, sem migration e sem caller. A
chave idempotente deve ser opaca e criada por componente confiavel do servidor;
telefone, mensagem, documento, conteudo pastoral ou identificador escolhido por
modelo ou cliente sao recusados. RBAC e deny-first, e toda tentativa de
`concedido` permanece negada enquanto faltar politica humana aprovada. Fonte
`painel_autenticado`, papel amplo ou autoria do operador nao provam manifestacao
do titular. Nao existe reidratacao por valor nesta fatia; retry entre processos
depende de futuro recibo duravel autenticado que prove a origem da chave. A
decisao tecnica esta em
`docs/decisions/2026-08-28-d2b2b1-consent-security-boundary.md`.
O template D2B2b2 permanece `TEMPLATE_ONLY / NOT_APPROVED` e esta em
`docs/decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md`. Ele
organiza um gate humano posterior, sem autorizar catalogo, writer, Supabase ou
efeito operacional.

A D2B2b3A integra somente a superficie draft-only do Console Master. O Master
autenticado prepara fatos e campos permitidos para cada finalidade e igreja;
tenant e ator sao derivados no servidor, sem e-mail hardcoded ou aceito como
autoridade. Hipotese juridica, declaracao de operacao baseada em consentimento,
decisao sobre menores, atestados, aprovacoes, digest e registros nominais nao
sao editaveis. Os rascunhos permanecem `DRAFT_NOT_APPROVED`. A fatia adiciona
migration versionada, persistencia, API e painel do Console Master,
mas nao aplica schema em Supabase compartilhado nem conecta painel do
tenant, catalogo, evidence store, writer, WhatsApp, agente ou D2C.
`PURPOSE_CONSENT_GOVERNANCE_DRAFTS_ENABLED` permanece `false` por default e
libera somente essa superficie administrativa.

A PR #320, HEAD `66ce06d9a356a52e63366b3a6528b0b83170d12e`, foi integrada no
merge `947d891c2ea278b7a3231fecd9ca1c90cfe29a1f`. Os cinco workflows da
PR e os cinco pos-merge ficaram verdes. O merge gerou o deployment automatico
Vercel frontend Production `6140373952`, com `SUCCESS`; essa metadata nao prova
backend, banco ou Supabase. Esta missao nao aplicou a migration D2B2b3A; DEV e
PROD confirmaram a ausencia. A flag permanece `false`, e nao houve deploy manual ou do
backend, wiring, ativacao ou canario.

A implementacao foi desenvolvida e comprovada offline sobre a base versionada
`b43ad92028374fa6763ef10f5eb7a379afd3e7a2`. O codigo integrado pela PR #323
adiciona o subcomando explicito e fail-closed
`bootstrap-ledger`, separado de `harden-ledger`. Ele exige
`--confirm BOOTSTRAP_LEDGER` antes da conexao e aceita o destino somente por
`M06_MIGRATION_DATABASE_URL`. Em PostgreSQL 17, cria em uma transacao
`SERIALIZABLE` apenas o ledger vazio `public.schema_migrations`, com colunas,
chave primaria e defaults exatos, owner estavel, RLS, policy deny e ACL
owner-only. Default privileges perigosas, grants de `CREATE` no schema,
membership alcancavel, objeto homonimo ou drift fisico abortam com rollback. A
reaplicacao do contrato exato e vazia encerra sem mutacao.

A verificacao concluiu 42/42 testes unitarios, 87/87 em PostgreSQL 17-alpine
descartavel em duas execucoes independentes e 87/87 em Supabase PG17
17.6.1.159 descartavel em duas execucoes independentes. A revisao de seguranca
resultou em `GO`. A suite RLS completa, em execucao serial limpa no PostgreSQL
17 descartavel, passou em 326/326, com 3803 deselecionados e 2 warnings
preexistentes, em 162.77s. A suite offline integral foi interrompida apos 5
min sem saida ou progresso; o resultado e `INCONCLUSIVO`, nao verde nem falha
e nao foi reclassificado. Os workflows Backend Tests da PR #323 e do
pos-merge concluiram com `SUCCESS`. O comando nao descobre o catalogo local, nao consulta, copia
ou altera `supabase_migrations`, nao faz backfill ou reconciliacao e nao aplica
nem registra migration. O ledger vazio mantem `status` e `apply` bloqueados ate
uma reconciliacao historica humana formar o prefixo integro do catalogo, com no
maximo uma migration pendente.

O `bootstrap-ledger` esta integrado em `main`, mas continua nao aplicado. A PR
#323, HEAD `74d3f2d87a7ffad501432b2d9fc4163bd3b4ada4`, foi integrada pelo
merge `3a5789c784017ab15a43e28c4270d25af8618359` em
`2026-08-28T15:24:58Z`; seus cinco workflows e os cinco pos-merge concluiram
com `SUCCESS`. A Vercel registrou o Preview automatico frontend `6143773477`,
com `SUCCESS`, em `2026-08-28T15:22:43Z`, e o Production automatico frontend
`6143819601`, com `SUCCESS`, em `2026-08-28T15:25:43Z`. Essas metadatas provam
somente o frontend, sem provar backend, banco ou runtime. Nao houve deploy
manual ou do backend, acesso aos bancos DEV ou PROD, bootstrap ou migration
compartilhada, restart ou alteracao de credencial, flag, runtime, agente ou
canario. O preflight PROD e o deployment automatico frontend da PR #321
permanecem como evidencia historica separada.

O pacote deny-state versionado e o verificador stdlib separado do runner,
desenvolvidos e comprovados offline sobre a base auditada
`cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`, foram integrados pela PR #325,
HEAD `d9595c3958fec98a875d15de2b6647d6b1de435e`, no merge
`ab7d09f07db96d5c63a2cc32dddf3f910e23bac2` em
`2026-08-28T20:18:08Z`, conforme
`docs/decisions/2026-08-28-migration-history-reconciliation-contract.md`.
O estado e `INTEGRADO / COMPROVADO OFFLINE / DECISOES HUMANAS PENDENTES / NAO
APLICADO`. A integracao nao acessou DEV ou PROD, nao materializou inventario de ambiente ou
decisao humana e nao reconciliou nenhum ledger. O verificador nao acessa banco,
rede, ambiente ou variaveis de ambiente, nao executa SQL, DML ou escrita e nao
infere migration aplicada. Os ledgers nativo e publico permanecem independentes
e todo sucesso estrutural conserva `OPERATIONAL_AUTHORIZATION=BLOCKED`.

Os cinco workflows da PR e os cinco pos-merge concluiram com `SUCCESS`. A
Vercel registrou o Preview automatico frontend `6147914118`, com `SUCCESS`, em
`2026-08-28T20:16:00Z` no HEAD, e o Production automatico frontend
`6147952424`, com `SUCCESS`, em `2026-08-28T20:18:55Z` no merge. Essas metadatas
provam somente o frontend, sem provar backend, banco ou runtime; nao houve
deploy manual ou do backend, migration, bootstrap, hardening, restart, flag ou
runtime nesta missao.

A prova local preservada e `98/98` testes do verificador, `26/26` testes
documentais e `42/42` testes offline do runner: agregado de
`166 passed/45 skipped`. O template deny-state terminou bloqueado com exit `8`.

O capturador e o materializador foram integrados pela PR #327, HEAD
`c4f7a25b81a8091a0d74783c816a168bb7adf44d`, no merge
`f9201a06495fad138e313e4149ad9275ff896900`. A PR #328 integrou o hotfix, HEAD
`2cbdfaf39ae11d984f0aa27dfcf0910c25984840`, no merge
`04e5c1720bf89313718c4159a2ac9d0eeeed3c25`. O catalogo de base
`656d1d9eebe90ad4b2cbb35c21939a6796c46bfe` contem 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`; o SQL
allowlisted tem SHA-256
`8b589e5dda722691fead34cbd63cab75a7a22f32e0cf4bdfe64d6cef603866ee`.

O estado e `INVENTARIOS DEV E PROD CAPTURADOS / REVISAO INDEPENDENTE BLOQUEADA
CONCLUIDA / DECISAO OWNER-01 REGISTRADA / NAO APLICADO`. Em PostgreSQL 17, DEV registrou
33 linhas no ledger publico e 6 no nativo em
`2026-08-28T22:43:11.454382Z`; PROD registrou o ledger publico
`ABSENT_CONFIRMED`, com 0 linhas, e 32 linhas no nativo em
`2026-08-28T22:47:43.965243Z`. `native.name` permaneceu sempre `null`. Os dois
pacotes estao em `EVIDENCE_CAPTURED_UNREVIEWED`; cada verificacao terminou com
exit `8`, `HUMAN_EVIDENCE_BLOCKED`, e a checagem conjunta terminou
`CROSS_PACKAGE_OK`. A matriz focal offline pos-captura passou com `163 passed,
2 skipped` em `1.40s`; isso nao e suite integral nem reexecucao PostgreSQL.

A captura ocorreu somente em leitura e nao executou DML, runner,
`bootstrap-ledger`, `harden-ledger`, `status`, `apply`, deploy, flag ou runtime.
Os seis artefatos permanecem bloqueados e nao provam decisao humana, migration
aplicada, prefixo reconciliado ou autorizacao operacional.

A PR #329 integrou e versionou os seis artefatos, com HEAD
`c5ae430aa865dbd6371953d43e4a4447ca8e6618`, no merge
`341f38a7f1c6993c74d85e99748cb60046cd4501` em `2026-08-29T00:04:50Z`. Os
cinco workflows da PR e os cinco pos-merge concluiram com `SUCCESS`. O merge
gerou o deployment automatico Vercel frontend Production `6150482852`, com
`SUCCESS`, em `2026-08-29T00:05:33Z`. Essa metadata prova somente o frontend,
sem provar deploy manual ou do backend, banco ou runtime. A integracao versiona
a evidencia sanitizada ja capturada, mas nao revisa os inventarios, nao aplica
migration e nao libera o runner ou qualquer autorizacao operacional.

A revisao de `REVIEWER-01`, vinculada pelo SHA-256
`18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133`,
bloqueou DEV por divergencia do ledger e PROD por evidencia insuficiente.
`OWNER-01` aceitou o bloqueio no registro externo de SHA-256
`0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240`,
manteve `operational_authorization=false` e autorizou somente a proposta
tecnica offline. Os registros externos nao foram versionados e os pacotes
continuam bloqueados.

O manifesto estatico de expectativas da fonte foi criado sobre a base
`7f18f7e8b44cd50e6f6033867fb97bfa9eb9c9e6`. Ele fixa 75 migrations e o
digest `84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`,
mas declara `SOURCE_LEVEL_EXPECTATION_ONLY`: nao prova o schema final de DEV ou
PROD. O verificador terminou em
`SCHEMA_EXPECTATION_MANIFEST_VERIFIED_SOURCE_ONLY`, com
`OPERATIONAL_AUTHORIZATION=BLOCKED` e
`ENVIRONMENT_ATTESTATION_COMPLETE=false`. A revisao tecnica foi feita pelo
mesmo executor e nao e independente.

A derivacao canonica foi reproduzida e verificada somente offline, duas vezes,
em PostgreSQL 17 descartavel, sobre a base
`07d2c05c687d1a0e8deeacbb7f8b16fbdd0e4e86`. As execucoes A e B produziram os
mesmos 388390 bytes, o SHA-256
`7040a54d80c0ee4f37e1986ff0a579db275e45c129f4fdafcd66788e22a3eb3e` e o
fingerprint `8ac17d4352a77fb3c5885f9c1a55813a5b7dfcd6fb84c4bd4e9117c1c7883370`.
A evidencia e os limites estao na
[`decisao de derivacao offline`](docs/decisions/2026-08-29-offline-canonical-schema-derivation.md).
Isso nao atesta DEV, PROD, Data API ou Realtime; `OPERATIONAL_AUTHORIZATION=BLOCKED`
permanece obrigatorio.

A PR #334, HEAD `a864730f0b678cca39cebfa6bb378243ba031cd6`, foi integrada no
merge `c8427b1a505c0aad2a5f675d3bf456ee33716690`; o Git registra
`commit date=2026-08-29T21:21:15Z`, e o GitHub registra
`mergedAt=2026-08-29T21:21:16Z`. Os seis checks da PR e os seis pós-merge
concluíram com `SUCCESS`; os detalhes da API do deployment automático Vercel
frontend Production `6160229001` estão na evidência detalhada em
[`decisao de derivacao offline`](docs/decisions/2026-08-29-offline-canonical-schema-derivation.md).
Os checks provam apenas o comportamento exercitado naquele SHA; a metadata do
deployment prova somente o frontend e não prova backend, banco, migration,
runtime ou atestação de ambiente.

A ferramenta separada de atestacao read-only foi implementada no commit tecnico
`be958ce96e65d3d497923b7f5f912676634e9587`, sobre a base
`1072e6a8e85d201a1c82f37a8ddeac5417300c49`. A prova focal offline passou em
`81/81`, a selecao relacionada terminou em `367 passed, 47 skipped` e a prova
focal em PostgreSQL 17 TLS descartavel passou em `82/82`. Sarah/Terra concluiu
`GO`; o healthcheck do Claude Opus passou, mas a revisao completa travou com
`Execution error` e nao foi reclassificada como revisao concluida.

A PR #337, HEAD `abf6f823336b81e93ec1c942dcd5a357d8ac797c`, integrou o tooling
no merge `278afb205a3b4735d4aeb66e2e585f71fd562ef7`, com
`mergedAt=2026-08-30T11:38:16Z`. Os sete workflows do push em `main`
concluiram com `SUCCESS`: Environment Attestation PG17 `33309430738`, Frontend
CI `33309430763`, Canonical Schema Derivation `33309430775`, Backend Tests
`33309430797`, Tooling Static Checks `33309430744`, E2E Critical `33309430731`
e RLS Integration `33309430799`.

A Vercel registrou o deployment frontend Production `6166209567`, com
`state=success`; o deployment e seu status registraram
`created_at=2026-08-30T11:39:02Z`. Essa metadata prova somente o frontend e nao
prova backend, banco ou runtime. O estado corrente e
`INTEGRADO E COMPROVADO OFFLINE / AMBIENTES NÃO CONSULTADOS / OPERAÇÃO BLOQUEADA`.

O tooling integrado permanece fail-closed, conforme a
[`decisao de atestacao read-only`](docs/decisions/2026-08-30-read-only-environment-attestation-tooling.md).
Nenhum DEV ou PROD foi consultado e nenhum artefato ambiental foi produzido.
O schema JSON valida somente o envelope; o verificador Python continua
obrigatorio. O HMAC serve para correlacao e anti-swap, sem substituir
autorizacao humana nem observar diretamente o project ref. Data API e Realtime
permanecem `PLATFORM_SURFACES_UNATTESTED`.

`OPERATIONAL_AUTHORIZATION=BLOCKED` e
`environment_attestation_complete=false` permanecem invariantes. Runner, DML,
migration, reconciliacao, backfill, deploy, flag e runtime continuam
bloqueados.

Sobre a base versionada `fe7dcd394bd1cfdc96204ad994bcba9f0c96adb4`, o runner
DEV preflight-only foi implementado e comprovado offline antes da integracao.
Os SHA-256
congelados sao: runner
`1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f`, testes
unitarios `d96fab1afe99531e3cee0f84bc285876de303ed0265fa41c51f8da9a7bcab0a0`,
prova PG17 `ceecfe9afa09066e4863e93be556b8f92c00a2992e0a0aef3b4253458f6fc318`,
testes de atestacao existentes
`68f9790a734f8adf78db8a716a5c2d99adad165f00737f922db90afa614b4ed8` e
workflow `80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf`.
Os unitarios passaram em `210/210`; duas provas locais sequenciais no
PostgreSQL 17 TLS passaram em `1/1` para a atestacao existente e `1/1` para o
runner com CA por FD.

A PR #340, HEAD `b29d3f494eabc3a04fe7f2c434758ad274f03930`, integrou o
runner no merge `82413edb884125d4d8f6e7946ffcaaf48ed8491c`, com
`mergedAt=2026-08-30T13:55:11Z`. Os sete workflows pos-merge concluiram com
`SUCCESS`: E2E `33315460948`, Frontend `33315460933`, Tooling
`33315460941`, RLS `33315460942`, Backend `33315460949`, Environment
Attestation PG17 `33315460934` e Canonical Schema Derivation `33315460939`.
A Vercel registrou o deployment frontend Production `6167369343`, com
`state=success`, em `2026-08-30T13:55:56Z`. Essa metadata prova somente o
frontend e nao prova backend, banco ou runtime.

O contrato usa `TLS_MODE=VERIFY_FULL_EXPLICIT_CA` e exige que o digest da CA,
`TLS_CA_CERTIFICATE_SHA256`, esteja vinculado a autorizacao. O escopo
`PROCESS_INVOCATION_ONLY` exige nova autorizacao nominal para cada invocacao.
O HMAC serve somente correlacao e anti-swap e nao substitui autorizacao humana.
O resultado produz zero arquivo, zero recibo, zero captura e zero
materializacao. Os buffers de chave e nonce sao zerados, os descritores sao
fechados e os certificados TLS temporarios sao removidos apos a prova. DEV e
PROD nao foram consultados. PROD esta explicitamente
fora. PROD continua fora. Estado:
`INTEGRADO E COMPROVADO OFFLINE / DEV/PROD NÃO CONSULTADOS / OPERAÇÃO
BLOQUEADA`.

Em 2026-08-30, ja no `main`
`64cc157d649256a4a9819741f4276c0420590fd1`, duas invocacoes DEV foram feitas
sob autorizacoes humanas nominais distintas e exclusivas, cada uma limitada a
`PROCESS_INVOCATION_ONLY`. O timestamp operacional preciso nao foi preservado;
nenhum horario UTC foi inferido. Ambas terminaram com exit `7`,
`RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED`, `ROLLBACK_CONFIRMED=false` e
`CONNECTION_CLOSED=true`. Em ambas, `OPERATIONAL_AUTHORIZATION=false`,
`NEXT_STAGE_AUTHORIZED=false`, `CAPTURE_EXECUTED=false`,
`MATERIALIZATION_EXECUTED=false` e `PROD_ACCESSED=false`. Esses campos nao
provam se houve conexao, nao provam sucesso ou falha de autenticacao e nao
identificam a causa raiz.

O diagnostico posterior passou em `2/2` no caminho full-main sobre PostgreSQL
17 TLS descartavel e em `97/97` no foco offline. O runner permaneceu intacto,
SHA-256 `1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f`,
assim como o workflow, SHA-256
`80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf`.
A prova PG17 ampliada tem SHA-256
`ddbc092216604e65cf86070d409837c7d328da96116ae5ea8d0947195b421b9e`.
Essa prova local nao reclassifica DEV nem determina a causa do bloqueio. A
evidencia detalhada esta em
[`2026-08-30-dev-identity-preflight-diagnostics.md`](docs/decisions/2026-08-30-dev-identity-preflight-diagnostics.md).
Estado: `DUAS INVOCACOES DEV BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO
CONSULTADO / OPERACAO BLOQUEADA`.

A PR #342, HEAD `5076c47b19fffe503e823d68c6dadfc59b11ed5d`, integrou a
prova diagnostica no merge `bc202da6c0ef83e03ded4392e508441cd4d6a188`, com
`mergedAt=2026-08-30T15:24:45Z`. Os sete workflows pos-merge concluiram com
`SUCCESS`: Canonical `33319560819`, Environment Attestation PG17
`33319560923`, E2E `33319560908`, RLS `33319560769`, Backend `33319560836`,
Frontend `33319560781` e Tooling `33319560786`. A Vercel registrou o
deployment frontend Production `6168185324`, com status `17531418022`,
`state=success` e `created_at=updated_at=2026-08-30T15:25:32Z`. Essa metadata
prova somente o frontend e nao prova backend, banco ou runtime.

A integracao nao repetiu o preflight, nao consultou logs, nao fez novo acesso a
DEV ou PROD e nao determinou a causa do exit `7`. Runner e workflow permanecem
intactos. Estado: `INTEGRADO E COMPROVADO OFFLINE / DUAS INVOCACOES DEV
BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO CONSULTADO / OPERACAO
BLOQUEADA`.

Sobre a base `3685bbcaf11d5a20b3492953d897cb6a459701a8`, o candidato
pre-merge adiciona o enum estatico `PREFLIGHT_FAILURE_PHASE` com dez valores:
`PRECONNECT_GUARDS`, `CONNECT_TLS_AUTH`, `SERVER_VERSION`, `SESSION_GUARDS`,
`IDENTITY_VALIDATION`, `ROLLBACK`, `CURSOR_CLOSE`, `CONNECTION_CLOSE`,
`POSTCONNECT_TLS_CA_REVALIDATION` e `POST_IDENTITY_FINALIZATION`. A fase e
somente a ultima fronteira operacional iniciada, nunca a causa; em especial,
`CONNECT_TLS_AUTH` nao prova nem separa rede, TLS ou credencial. Cada saida
`BLOCKED` contem exatamente uma linha de fase, o sucesso nao a contem e a
primeira falha vence quando ha falhas posteriores.

Os SHA-256 congelados sao runner
`8da631fbb602488bb8c82ce1529c9d8ba17acbae8a318ea9b0fc24cdd8f65cd2`,
unitarios `c55726f0ad8abf7680de868cba155388f7e56773aa8054e556be89dc87aa90a8` e
PG17 `d86037d759d254581d2259026585ac768e4b2d68595473371ec65daf6c6de5a9`.
Passaram `109 passed, 2 skipped` offline, `2/2` em PostgreSQL 17 TLS
descartavel e `222 passed, 2 skipped` no agregado relevante; `pycompile` e
`diff-check` ficaram verdes, os recursos temporarios foram removidos e
Sarah concluiu `GO`, sem P0, P1 ou P2. As duas execucoes DEV historicas com
exit `7` nao podem ser retroclassificadas. A unica `query_logs` anterior
retornou vazio e continua `EVIDENCE_INSUFFICIENT`. Esta missao nao repetiu a
consulta e nao acessou DEV ou PROD. A evidencia detalhada esta em
[`2026-08-30-dev-preflight-failure-phase-diagnostics.md`](docs/decisions/2026-08-30-dev-preflight-failure-phase-diagnostics.md).

O enum foi integrado pela PR #344 no `main`
`bab031a7e0067a257eedb4a24c786cc925801463`. Em `2026-08-31`, uma terceira e
unica invocacao DEV `PROCESS_INVOCATION_ONLY` nesse `main` terminou com exit
`7`, `RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED` e
`PREFLIGHT_FAILURE_PHASE=CONNECT_TLS_AUTH`. A autorizacao era valida entre
`2026-08-31T11:03:30Z` e `2026-08-31T11:18:30Z`; essa janela nao e o horario
da execucao. O timestamp operacional preciso nao foi preservado nem inferido.
DNS, TCP, TLS, CA, senha, autenticacao, endpoint, disponibilidade, conexao,
transacao e identidade permanecem `UNKNOWN`. A autorizacao foi consumida;
nenhum log foi consultado e nao houve retry, captura, materializacao, DML,
migration, backfill, deploy, flag, runtime ou acesso a PROD.
A limpeza removeu o diretorio temporario de autorizacao, o launcher e a
worktree operacionais temporarios; o checkout ficou limpo, sem `__pycache__` ou
`.pyc`, e o registro Git obsoleto da worktree foi removido.

O probe para separar somente DNS, TCP e TLS foi preparado offline e permanece
`execution_disabled=true`; ele nao foi executado e nao possui autorizacao viva.
O contrato e os limites estao em
[`2026-08-31-dev-connect-tls-auth-transport-probe.md`](docs/decisions/2026-08-31-dev-connect-tls-auth-transport-probe.md).
`OPERATIONAL_AUTHORIZATION=false` e `NEXT_STAGE_AUTHORIZED=false` permanecem
obrigatorios.

A PR #346, HEAD `0c63dc29dc903e0e7012b9fb811b7b2ddb05ab51`, foi integrada no
merge `fb776e270bf3e2ffde0cbb28e400960591b74420`, com
`mergedAt=2026-08-31T13:02:07Z`. Os sete workflows pos-merge concluiram com
`SUCCESS`: Tooling `33394774001`, Environment Attestation PG17 `33394774013`,
Canonical `33394773986`, E2E `33394774109`, Frontend `33394774063`, RLS
`33394773965` e Backend `33394774029`. A Vercel registrou o deployment
frontend Production `6181597461`, status `17569033825`, `state=success`, em
`2026-08-31T13:02:53Z`. Essa metadata prova somente o frontend e nao prova
saude funcional, backend, banco, DEV, PROD, probe ou migration. A integracao
versionou apenas o plano offline: `execution_disabled=true`, implementacao e
capacidade de rede ausentes, probe nao executado e operacao bloqueada.

A PR #347, HEAD `0a257e9aa1985860d5ea0a4506d4f7e84c7b2312`, foi integrada no
merge `36f8d13284a8f4964d0258a2a3b845323a80fe7e`, com
`mergedAt=2026-08-31T14:26:10Z`. Os sete workflows pos-merge concluiram com
`SUCCESS`, e o deployment automatico Vercel frontend Production `6183047421`,
status `17572803614`, terminou com `state=success` em
`2026-08-31T14:26:57Z`. Essa metadata prova somente o frontend.

Sobre esse merge, o candidato implementa o probe transport-only em
`backend/scripts/probe_dev_connect_tls_auth_transport.py`, SHA-256
`4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9`, e sua
matriz adversarial, SHA-256
`b79ff9d7473fdafd0a4fcd6ceba98b2c46f5470ef517b6663898812fe8b1296e`.
Passaram `90/90` testes exclusivamente offline, incluindo loopback TLS
sintetico descartavel. O runner recebe seis descritores privados, fixa o hash
do project-ref DEV e do registro de autorizacao, envia somente o SSLRequest
PostgreSQL de oito bytes, exige `S`, valida CA e hostname e fecha antes de
StartupMessage. Nao recebe senha, usuario, banco ou DSN e nao tenta
autenticacao nem SQL. O plano JSON permanece historico e byte-identico; seus
campos `execution_disabled=true` e `implementation_present=false` descrevem a
etapa anterior ja consumida. A unica rede desta rodada foi o `git fetch`
nominal autorizado para obter o merge; nenhum probe vivo, DEV, PROD, banco ou
log foi acessado. `operational_authorization=false` e
`next_stage_authorized=false` permanecem.

A PR #348, HEAD `af91e5218f9317a730aa29ad8d8c645312b30f19`, foi integrada no
merge `1e727cd2ea90ccfb68961174b802d595c71f355b`, com
`mergedAt=2026-08-31T15:22:49Z`. Os sete workflows pos-merge concluiram com
`SUCCESS`: Tooling `33408103314`, Environment Attestation PG17 `33408103217`,
Canonical `33408103386`, Frontend `33408103193`, E2E `33408103279`, Backend
`33408103254` e RLS `33408103282`. A Vercel registrou o deployment automatico
frontend Production `6184050276`, status `17575418445`, `state=success`, em
`2026-08-31T15:23:35Z`. Essa metadata prova somente o deployment do frontend,
nao sua saude funcional, e nao prova backend, banco, DEV, PROD ou o probe. O
estado agora e `IMPLEMENTADO / INTEGRADO / COMPROVADO OFFLINE / PROBE NAO
EXECUTADO / OPERACAO BLOQUEADA`.

**Gate consumido em 2026-08-31:**
`SEPARATE_NOMINAL_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE_AUTHORIZATION`. Seu
consumo exige nova autorizacao humana nominal para exatamente uma invocacao
`PROCESS_INVOCATION_ONLY` no checkout de `main` `1e727cd2`, com runner SHA-256
`4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9` e o
`source_main_git_sha=36f8d13284a8f4964d0258a2a3b845323a80fe7e` exigido pelo
contrato interno. Nao autoriza retry, senha, autenticacao, sessao de banco,
SQL, logs,
captura, materializacao, DML, migration, reconciliacao, backfill, deploy manual
ou Production, flag, runtime e PROD continuam bloqueados.

Uma única invocacao terminou com exit `7`,
`TRANSPORT_PROBE_FAILURE_PHASE=TLS_HANDSHAKE` e
`RESULT=BLOCKED_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE:TRANSPORT_BLOCKED`.
DNS, politica de endereco, TCP e a resposta `S` ao SSLRequest foram
confirmados; handshake e hostname nao foram confirmados. Nao houve retry,
senha, autenticacao, sessao de banco, SQL, logs ou PROD. A causa permanece
indeterminada e o resultado nao recebe categoria retroativa. A evolucao
offline adiciona somente uma categoria estatica de falha TLS, com runner
SHA-256 `0ac585b86dd1c96446622e9a46bccda8a1e43eb0bceb0dcc19226892cb88d191`,
testes SHA-256
`ef1e23ea13b0469ae4561191c8f46bd34516b94288cce302d41cb5046b2104df` e
`95/95` testes verdes.

**Próximo gate único:**
`REVIEW_AND_CI_DEV_TLS_HANDSHAKE_FAILURE_CATEGORY_PR`. Permite somente preparar
revisao e CI depois de autorizacao humana especifica para push, PR e Preview.
Nao autoriza merge, Vercel Production, nova execucao, DEV adicional, PROD,
banco, logs, SQL, migration, flag ou runtime.

A evolucao aprovada mantem uma unica politica global e adiciona especialistas por dominio de forma incremental. Atendimento, Central de Celulas, Agenda e Consolidacao integram a missao atual; Universidade da Vida e Capacitacao Destino permanecem na visao futura e dependem de PRDs e missoes proprias. Especialistas nunca enviam mensagens diretamente e nunca recebem IDs de tenant escolhidos pelo modelo ou pelo cliente.

Memoria e conhecimento sao contratos diferentes:

- conversa, midia, transcricao, resumo e checkpoint compoem memoria privada;
- dados estruturados do sistema e documentos aprovados pelo admin compoem conhecimento oficial;
- conversa privada nunca e promovida automaticamente a conhecimento institucional;
- documento oficial exige versao, audiencia, validade e responsavel por aprovacao;
- informacao ausente gera resposta de incerteza e pendencia para o responsavel do dominio, sem alucinacao.

O historico privado e retido ate solicitacao da pessoa pelo WhatsApp e aprovacao do admin no painel. A exclusao aprovada deve apagar mensagens, midias, transcricoes, resumos, checkpoints e vetores derivados, preservando apenas auditoria minima sem conteudo pessoal.

Consentimento deve ser separado em quatro finalidades: `atendimento_solicitado`, `cuidado_pastoral`, `tarefas_operacionais` e `comunicados`. A D2B2a integrada materializa somente o ledger interno; um termo desatualizado exige novo aceite, o legado nao concede novas finalidades e o opt-out global continua prevalecendo. A D2B2b1 fecha apenas a fronteira tecnica pura, com chave opaca, RBAC deny-first e toda concessao negada. A D2B2b3A acrescenta somente o preparo auditado de rascunhos pelo Console Master, sem decisao juridica, atestado ou aprovacao. Antes de catalogo, prova ou writer, um fluxo posterior deve aprovar nominalmente por finalidade controlador, base, dados, texto, evidencia, menores, retencao, eliminacao, opt-out e transferencias. D2C permanece bloqueada.

A primeira vertical completa e o relatorio de celula pelo WhatsApp: lembrete, coleta por texto ou audio, resumo editavel, confirmacao explicita, escrita pelo mesmo servico de dominio usado pelo painel e comprovante somente depois do commit. Permissoes, vinculos de terceiros, dados pastorais restritos, exclusoes, financas, publicacao de conhecimento e configuracao da igreja exigem conclusao no painel autenticado.

### 3.5 Integracoes Externas
| Integracao | Uso | Stories |
|-----------|-----|---------|
| **Clerk** | Autenticacao/sessao; papeis vem do cadastro autenticado | US-01, US-04 |
| **Supabase (Postgres+RLS)** | Persistencia e isolamento multi-tenant | US-02, RNF-02/21 |
| **Evolution API** | Conexao (QR), envio/recebimento WhatsApp; processo sempre-ligado | US-05..US-08, US-33 |
| **OpenAI (BYO-LLM)** | Respostas do agente; chave e modelo por igreja; allowlist, validacao de acesso e fallback somente para opcoes mais baratas. OpenRouter fica fora do produto | US-08, US-27, RNF-20 |
| **Brevo** | E-mail de convite/ativacao de usuarios, fechado por `BREVO_SEND_MODE` | US-03 |
| **Google Calendar** | Sincronizacao de eventos | US-30 |
| **Asaas** | Checkout (PIX/boleto/cartao), setup fee, status de assinatura, webhooks | US-34, US-35, US-36 |
| **Coolify/Dokploy** | Containers persistentes, restart automatico, TLS | RNF-04/15/18 |

---

## 4. Frontend

> **Nota (2026-07-18):** esta secao reflete o desenho original de 2026-06-11. O historico do que foi entregue/alterado depois esta em `docs/sprints/`.

### 4.1 Design Lock Source
- **Artifact HTML (fonte visual oficial):** `docs/Docs20260611_163530/design/artifact.html` (sha256 `93f2b3d2224849faf242dc202441f19ac12639f4c157d7db6292ca794b466478`)
- **Design Contract:** `docs/Docs20260611_163530/design/design-contract.json`
- **Design Brief:** `docs/Docs20260611_163530/design/design-brief.md`
- **Lock Report:** `docs/Docs20260611_163530/design/design-lock-report.md` — status **APROVADO**.
- Regras: nenhuma tela fora do lock; direcao visual inalterada; backend so existe se consumido por tela/action ou exigido por requisito.

### 4.2 Mapa de Rotas e Telas
> Roteamento por hash (`#rota`), conforme contract. Menu e dashboard montados pela uniao dos papeis acumulados; tela `permissoes` (matriz papel x tela) e a fonte de verdade dos acessos.

**Grupo Gestao**
| Tela (id) | Rota | Proposito | Estados | Stories |
|-----------|------|-----------|---------|---------|
| login | `#login` | Autenticar via Clerk | idle, loading, error, success | US-01 |
| dashboard | `#dashboard` | Fila de trabalho pastoral, acoes diretas, proximas acoes, pendencias com prazo (24h, fonovisita) | loading, empty, populated | US-02, US-15, US-16, US-17, US-26, US-40 |
| inbox | `#inbox` | Conversas WhatsApp, fila humana, alternancia IA/humano | loading, empty, list, thread-ia-active, thread-human, thread-waiting | US-08, US-11, US-12, US-13, US-14 |
| calendario | `#calendario` | Eventos integrados ao Google Calendar | loading, empty, month | US-30 |
| comunicados | `#comunicados` | Envio segmentado respeitando consentimento/opt-out | compose, segment, review, empty | US-31, US-32, US-33 |
| equipe | `#equipe` | Convidar/gerenciar pessoas e editar papeis acumulados | loading, empty, list, invite, edit-roles | US-03, US-04 |

**Grupo Visao G12 (ciclo ministerial)**
| Tela (id) | Rota | Proposito | Estados | Stories |
|-----------|------|-----------|---------|---------|
| ganhar | `#ganhar` | Novos contatos e visitantes (1a etapa) | loading, empty, novos-contatos, visitantes | US-09, US-10, US-18, US-19, US-20 |
| consolidar | `#consolidar` | Dashboard de Consolidacao (restrito), fila, lancar decisao, 100% consolidadas | loading, empty, fila, 100-consolidadas | US-18, US-19, US-20, US-37, US-38 |
| consol-individual | `#consol-individual` | Acompanhamento 1:1, avancar etapas/concluir | loading, empty, fila, detalhe | US-18, US-19, US-37, US-39 |
| universidade-vida | `#universidade-vida` | Turmas/cronograma da UV **(BLOQUEADA no MVP)** | loading, empty, turmas, detalhe | US-18, US-19 |
| capacitacao | `#capacitacao` | Capacitacao Destino **(BLOQUEADA no MVP — locked-em-breve)** | locked-em-breve | US-18, US-19 |
| g12 | `#g12` | Organograma de descendencias | loading, empty, organograma, descendencia | US-21, US-22, US-23 |
| central-celula | `#central-celula` | Lideres, relatorios recebidos/pendentes, comunicacao com lideres | loading, empty, lideres, relatorios | US-21..US-26 |
| enviar | `#enviar` | Multiplicacoes, aptos a liderar, aprovacao, historico | loading, empty, agendadas, sem-agendamento, aptos, historico | US-21, US-22, US-23 |

**Grupo Configuracao (admin only)**
| Tela (id) | Rota | Proposito | Estados | Stories |
|-----------|------|-----------|---------|---------|
| whatsapp | `#whatsapp` | Conectar via QR, status, reconexao | connected, disconnected, reconnecting | US-05, US-06, US-07 |
| agente | `#agente` | Credencial BYO LLM, comportamento, crons | behavior, credential, crons | US-27, US-28, US-29 |
| assinatura | `#assinatura` | Contratar, status, upgrade por porte | active, past-due, plans | US-34, US-35, US-36 |
| gerentes | `#gerentes` | Operadores de sistema (papel operacional) | loading, empty, list, invite | US-03, US-04 |
| permissoes | `#permissoes` | Matriz papel x tela | matrix, saved | US-04, US-03 |

**Telas legadas (deep-link valido, fora do menu — delta-012)**
| Tela (id) | Rota | Estados | Stories |
|-----------|------|---------|---------|
| contatos | `#contatos` | loading, empty, list, detail | US-09, US-10, US-18, US-19, US-20, US-31, US-32 |
| celulas | `#celulas` | loading, empty, list, detail | US-21, US-22, US-23, US-25 |
| relatorios | `#relatorios` | loading, empty, received, pending | US-24, US-25, US-26 |

**Superficie separada (stubs de rastreabilidade — NAO implementar no painel operacional, delta-024)**
| Tela (id) | Rota | Estados | Stories |
|-----------|------|---------|---------|
| super-admin-igrejas | `#super-admin-igrejas` | loading, empty, list, detail | US-42 |
| super-admin-provisionar | `#super-admin-provisionar` | idle, verifying, provisioned | US-43 |

**Navegacao principal (sidebar-nav):**
- Gestao: `nav-dashboard`->dashboard · `nav-inbox`->inbox · `nav-calendario`->calendario · `nav-comunicados`->comunicados · `nav-equipe`->equipe
- Visao G12: `nav-ganhar` · `nav-consolidar` · `nav-consol-individual` · `nav-universidade-vida` · `nav-capacitacao` · `nav-g12` · `nav-central-celula` · `nav-enviar`
- Configuracao (adminOnly): `nav-whatsapp` · `nav-agente` · `nav-assinatura` · `nav-gerentes` · `nav-permissoes`
- Secundaria: `nav-logout`->login

### 4.3 Componentes por Tela
| Componente (id) | Tipo | Telas (usedInScreenIds) | Estados/Props |
|-----------------|------|-------------------------|---------------|
| btn-primary | form | login, contatos, celulas, comunicados, agente, equipe, assinatura | variant primary; default, hover, loading, disabled |
| form-field | form | login, contatos, comunicados, agente, equipe, calendario | label/helper/error; idle, focus, invalid, disabled |
| sidebar-nav | navigation | dashboard, inbox, contatos, celulas, relatorios, comunicados, calendario, whatsapp, agente, equipe, assinatura | default, active |
| status-pill | display | dashboard, inbox, contatos, relatorios, whatsapp, assinatura | tone ok\|warn\|danger\|accent\|muted |
| work-queue-item | display | dashboard | tipo visitante\|atendimento\|relatorio; pending, resolving, resolved |
| stat-card | display | dashboard, celulas, assinatura | normal, alert |
| conversation-list | display | inbox | default, active |
| conversation-thread | display | inbox | ia-active, human, waiting |
| data-table | display | contatos, celulas, relatorios, equipe, comunicados | empty, populated |
| tabs | navigation | contatos, celulas, relatorios, agente, assinatura | default, active |
| calendar-month | display | calendario | — |
| qr-connect | display | whatsapp | connected, disconnected, reconnecting |
| toggle-switch | form | agente, comunicados, equipe | on, off |
| empty-state | display | inbox, contatos, relatorios, calendario | — |
| deadline-badge | display | dashboard, consolidar | tone ok\|warn\|late; dentro, alerta, atrasado |
| decision-modal | overlay | consolidar, consol-individual | props vinculo celula\|visitante; closed, celula-flow, visitante-flow |
| assistant-panel | overlay | dashboard, inbox, contatos, celulas, consolidar, consol-individual, ganhar, g12, enviar, agente, equipe, permissoes, assinatura | scope tenant, roleAware; closed, open, thinking |

### 4.4 Tokens Visuais
**Direcao:** software web claro, modern-minimal + tech utilitario; base zinc/off-white quente, acento teal dessaturado unico, numeros tabulares, bordas hairline, sem serif e sem preto puro. **Densidade:** balanced.

**Cores (oklch):**
| Token | Valor |
|-------|-------|
| bg | oklch(98.6% 0.003 95) |
| surface | oklch(100% 0 0) |
| sidebar | oklch(21% 0.012 200) |
| fg | oklch(24% 0.01 90) |
| muted | oklch(52% 0.012 90) |
| border | oklch(91% 0.005 95) |
| accent | oklch(52% 0.078 195) |
| ok | oklch(56% 0.09 155) |
| warn | oklch(64% 0.11 75) |
| danger | oklch(56% 0.13 25) |

**Tipografia:** display/body = system-ui (-apple-system / Segoe UI); mono = ui-monospace / JetBrains Mono.

**Espacamento (px):** xs 4 · sm 8 · md 12 · lg 16 · xl 24 · 2xl 32.

**Radii (px):** sm 6 · md 10 · lg 14 · xl 20.

### 4.5 Estados de UI
- **Carregamento/vazio/populado:** `loading`/`empty`/`populated|list` nas listas (dashboard, inbox, ganhar, consolidar, etc.) com `empty-state`.
- **Inbox/handoff:** `thread-ia-active`, `thread-human`, `thread-waiting` no `conversation-thread`; itens com atendimento humano pendente sinalizados (US-11). Acao "Assumir" pausa IA; "Devolver para IA" retoma (US-12/13).
- **WhatsApp:** `connected`/`disconnected`/`reconnecting` espelhados no `qr-connect`; status muda sem recarregar a pagina (US-05/06).
- **Prazos (deadline-badge):** `dentro` (ok), `alerta` (warn, poucas horas), `atrasado` (late/vermelho) para "Conectar a celula" (24h) e fonovisita (US-40/delta-022).
- **Decisao por Jesus (decision-modal):** `celula-flow` (lider assume) ou `visitante-flow` (consolidacao assume, prazo 24h) (US-37/delta-021).
- **Consolidacao:** `fila`, `detalhe`, `100-consolidadas` com selos de consolidacao individual e/ou UV; confirmacao de etapa gateada por identidade (delta-018).
- **Assinatura:** `active`, `past-due`, `plans`.
- **Permissoes:** `matrix`, `saved` — alteracao reflete no menu/dashboard em tempo real (delta-010).
- **Telas bloqueadas:** `locked-em-breve` (capacitacao; UV bloqueada) com simbolo de relogio/cinza claro, sem navegar (delta-019/028).
- **Assistente (assistant-panel):** `closed`/`open`/`thinking`, ciente do papel (sauda citando papeis, sugere so telas permitidas) e restrito ao tenant (US-41/delta-023).

### 4.6 Mapeamento Tela -> API
| Tela | Action(s) | API |
|------|-----------|-----|
| login | action-login | api-login |
| dashboard | action-queue-assume/assign | api-queue-action |
| dashboard | action-queue-message | api-send-internal-message |
| dashboard | action-queue-connect-cell | api-link-cell |
| dashboard | action-queue-fonovisita | api-pipeline |
| dashboard | action-assistant-send | api-assistant |
| inbox | action-open-conversation | api-conversations |
| inbox | action-assume/return-conversation | api-conversation-handoff |
| contatos | action-new-contact | api-create-contact |
| contatos | action-open-contact | api-contacts |
| contatos | action-link-cell | api-link-cell |
| celulas | action-new-cell/edit-cell | api-cells |
| relatorios | action-view-report/charge-report | api-reports |
| comunicados | action-new/send/schedule-broadcast | api-broadcasts |
| calendario | action-new-event | api-events |
| whatsapp | action-connect/reconnect-whatsapp | api-whatsapp-connection |
| agente | action-save-llm-key | api-llm-credential |
| agente | action-save-agent | api-agent-config |
| agente | action-save-cron | api-crons |
| equipe | action-invite-user | api-team-invite |
| equipe | action-edit-roles | api-team-roles |
| assinatura | action-contract-plan/manage-billing | api-subscription |
| permissoes | action-toggle-perm | api-role-perms |
| ganhar | action-open-contact-ganhar | api-contacts |
| ganhar | action-promote-visitante | api-pipeline |
| consolidar | action-open-consol-individual/open-uv | api-pipeline |
| consolidar | action-launch-decision | api-launch-decision |
| consol-individual | action-assign-consolidador/advance-stage | api-pipeline |
| consol-individual | action-launch-decision-ci | api-launch-decision |
| universidade-vida | action-new-turma-uv | api-pipeline |
| capacitacao | action-advance-trilha | api-pipeline |
| g12 | action-open-descendencia | api-descendencias |
| central-celula | action-view-report-central/charge-report-central | api-reports |
| central-celula | action-message-leaders | api-broadcasts |
| enviar | action-schedule-mult/approve-mult | api-multiplicacoes |
| gerentes | action-add-gerente/remove-gerente | api-system-managers |
| super-admin-igrejas* | action-open-tenant | api-super-admin-tenants* |
| super-admin-provisionar* | action-provision-tenant | api-super-admin-provision* |

\* Stub — superficie separada (delta-024).

### 4.7 Mapeamento Story -> Tela
| Story | Tela(s) |
|-------|---------|
| US-01 | login |
| US-02 | dashboard (transversal — RLS em todas) |
| US-03 | equipe, gerentes, permissoes |
| US-04 | permissoes, equipe, gerentes (transversal) |
| US-05, US-06, US-07 | whatsapp |
| US-08 | inbox |
| US-09 | contatos, ganhar |
| US-10 | contatos, ganhar |
| US-11, US-12, US-13, US-14 | inbox (US-14 tambem dashboard) |
| US-15, US-16, US-17 | dashboard |
| US-18 | ganhar, contatos, consolidar, consol-individual |
| US-19 | contatos, ganhar, consol-individual |
| US-20 | contatos, ganhar, consolidar |
| US-21 | celulas, g12, central-celula, enviar |
| US-22 | celulas, g12, central-celula |
| US-23 | celulas, g12, central-celula, enviar |
| US-24 | relatorios, central-celula (captura via WhatsApp/agente) |
| US-25 | relatorios, celulas, central-celula |
| US-26 | dashboard, relatorios, central-celula |
| US-27, US-28, US-29 | agente |
| US-30 | calendario |
| US-31, US-32 | comunicados, contatos |
| US-33 | comunicados, central-celula |
| US-34, US-35, US-36 | assinatura |
| US-37 | consolidar, consol-individual |
| US-38 | consolidar |
| US-39 | consol-individual |
| US-40 | dashboard, consolidar |
| US-41 | dashboard + assistant-panel (telas operacionais) |
| US-42 | super-admin-igrejas (stub) |
| US-43 | super-admin-provisionar (stub) |

### 4.8 Metadados para Planejamento de Sprints UI
> Usado pelo Planner para preencher `DevelopmentV2SprintMetadata` de cada sprint. `affectedScreenIds`/`affectedComponentIds` vem do `design-contract.json`. `touchesUI=true` aponta o artifact HTML.

**Area: Autenticacao & Multi-tenant**
- affectedScreenIds: `login`
- affectedComponentIds: `btn-primary`, `form-field`, `sidebar-nav`
- touchesUI: **true**
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-01, US-02, US-04

**Area: Dashboard / Fila de Trabalho Pastoral**
- affectedScreenIds: `dashboard`
- affectedComponentIds: `work-queue-item`, `stat-card`, `status-pill`, `deadline-badge`, `sidebar-nav`, `assistant-panel`
- touchesUI: **true**
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-15, US-16, US-17, US-26, US-40

**Area: Inbox / Atendimento WhatsApp & Handoff**
- affectedScreenIds: `inbox`
- affectedComponentIds: `conversation-list`, `conversation-thread`, `status-pill`, `empty-state`, `assistant-panel`
- touchesUI: **true**
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-08, US-11, US-12, US-13, US-14

**Area: Contatos & Visitantes (Ganhar)**
- affectedScreenIds: `ganhar`, `contatos`
- affectedComponentIds: `data-table`, `tabs`, `status-pill`, `empty-state`, `btn-primary`, `form-field`, `assistant-panel`
- touchesUI: **true**
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-09, US-10, US-18, US-19, US-20

**Area: Celulas & Lideres (Discipular)**
- affectedScreenIds: `celulas`, `g12`, `central-celula`
- affectedComponentIds: `data-table`, `stat-card`, `tabs`, `btn-primary`, `form-field`, `assistant-panel`
- touchesUI: **true**
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-21, US-22, US-23

**Area: Relatorios de Celula**
- affectedScreenIds: `relatorios`, `central-celula`
- affectedComponentIds: `data-table`, `tabs`, `status-pill`, `empty-state`
- touchesUI: **true**
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-24, US-25, US-26

**Area: Consolidacao (Consolidar / Individual)**
- affectedScreenIds: `consolidar`, `consol-individual`
- affectedComponentIds: `data-table`, `deadline-badge`, `decision-modal`, `status-pill`, `assistant-panel`
- touchesUI: **true**
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-18, US-19, US-20, US-37, US-38, US-39, US-40

**Area: Trilhas Bloqueadas (UV / Capacitacao Destino)**
- affectedScreenIds: `universidade-vida`, `capacitacao`
- affectedComponentIds: (estado `locked-em-breve`; sem componentes interativos)
- touchesUI: **true** (placeholder bloqueado, mas presente no menu)
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-18, US-19 — *BLOQUEADAS no MVP (delta-019/028)*

**Area: Enviar / Multiplicacoes**
- affectedScreenIds: `enviar`
- affectedComponentIds: `data-table`, `tabs`, `btn-primary`, `assistant-panel`
- touchesUI: **true**
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-21, US-22, US-23

**Area: Calendario & Eventos**
- affectedScreenIds: `calendario`
- affectedComponentIds: `calendar-month`, `form-field`, `btn-primary`, `empty-state`
- touchesUI: **true**
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-30
- **revisao (EVT-0, delta-049/050/051):** modulo Agenda expandido (abas Semana/Mes/Ano/A confirmar/Planejamento, status/confirmacao, import Google→pendente). MVP EVT-1..5 manual. Ver `docs/design/AGENDA-EVENTOS-EVT0-decisao.md`.

**Area: Comunicados / Consentimento & Opt-out**
- affectedScreenIds: `comunicados`
- affectedComponentIds: `data-table`, `form-field`, `toggle-switch`, `btn-primary`, `empty-state`
- touchesUI: **true**
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-31, US-32, US-33

**Area: Equipe & Papeis (RBAC)**
- affectedScreenIds: `equipe`, `permissoes`, `gerentes`
- affectedComponentIds: `data-table`, `form-field`, `toggle-switch`, `btn-primary`
- touchesUI: **true**
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-03, US-04

**Area: Conexao WhatsApp**
- affectedScreenIds: `whatsapp`
- affectedComponentIds: `qr-connect`, `status-pill`
- touchesUI: **true**
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-05, US-06, US-07

**Area: Agente IA & Credencial LLM**
- affectedScreenIds: `agente`
- affectedComponentIds: `tabs`, `form-field`, `toggle-switch`, `btn-primary`
- touchesUI: **true**
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-27, US-28, US-29

**Area: Assinatura & Faturamento**
- affectedScreenIds: `assinatura`
- affectedComponentIds: `stat-card`, `tabs`, `status-pill`, `btn-primary`
- touchesUI: **true**
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-34, US-35, US-36

**Area: Assistente do Sistema**
- affectedScreenIds: `dashboard` (+ telas com `assistant-panel`)
- affectedComponentIds: `assistant-panel`
- touchesUI: **true**
- artifactPath: `docs/Docs20260611_163530/design/artifact.html`
- stories: US-41

**Area: Agente Orquestrador WhatsApp (backend / NAO-UI)**
- affectedScreenIds: (nenhuma — reflexo em `inbox`, `ganhar`, `relatorios`, `consolidar`)
- affectedComponentIds: (nenhum)
- touchesUI: **false**
- stories: US-08, US-09, US-10, US-24 (delta-034/041 / A1 SLA)

**Area: Fundacoes & Auditoria (backend / NAO-UI)**
- affectedScreenIds: (nenhuma)
- affectedComponentIds: (nenhum)
- touchesUI: **false**
- stories: US-02 (F1/RLS), US-18 (F2 state machine), US-04 (F3/F4), US-27 (F8 logs IA) — RNF-21..25

**Area: Super-Admin (superficie separada / stub — NAO implementar no painel operacional)**
- affectedScreenIds: `super-admin-igrejas`, `super-admin-provisionar`
- affectedComponentIds: (stub)
- touchesUI: **false** (fora do escopo do painel operacional — delta-024)
- stories: US-42, US-43

---

## 5. Security

### 5.1 Auth Flow Completo
1. **Login (US-01):** usuario autentica via **Clerk** (e-mail/senha e metodos habilitados). Frontend Next.js usa Clerk SDK; nenhuma senha e armazenada pelo PastorAI (RNF-01).
2. **Sessao/JWT:** Clerk emite token de sessao; o backend FastAPI valida o token em cada request (middleware Auth).
3. **Resolucao de tenant (US-02):** a partir do `clerk_user_id`, o backend resolve `app_users.igreja_id` e injeta `current_igreja_id()` no contexto RLS do Postgres.
4. **RBAC por papeis acumulados (US-04/F3):** carrega `user_roles` (uniao); monta menu/dashboard pela uniao dos acessos; `role_permissions` (matriz papel x tela) e a fonte de verdade, refletindo em tempo real.
5. **Autorizacao no backend (F4/delta-033):** cada endpoint revalida `igreja_id` + papel; Config exige `admin`; inbox exige privilegio; consolidacao gate por consolidador.
6. **Redirecionamentos:** sucesso -> `#dashboard` da igreja; credencial invalida -> erro generico (nao revela existencia de e-mail); sessao expirada/invalida -> `#login`.
7. **Convites (US-03):** admin convida (nome+email+papeis); Brevo envia link de ativacao quando seu gate permite; status `convidado` -> `ativo`. Revogacao de acesso suportada.
8. **Agente (F5):** fixa o tenant a partir do contexto validado no servidor, opera sob papel `NOBYPASSRLS` e reaplica as mesmas autorizacoes e servicos de dominio do caminho humano.

### 5.2 Checklist de Seguranca
- [ ] Autenticacao exclusivamente via Clerk; sem senhas proprias (RNF-01).
- [ ] RLS habilitado em todas as tabelas com `igreja_id`; nenhuma consulta cruza tenant (RNF-02/RNF-21).
- [ ] Runtime do agente sem service role ou `BYPASSRLS`; ausencia de tenant falha fechada.
- [ ] Revalidacao de `igreja_id` + papel em cada endpoint (F4/RNF-05).
- [ ] Credenciais LLM e chaves de integracao **cifradas**; nunca exibidas em texto claro apos salvar (RNF-03/US-27).
- [ ] Todo trafego sobre HTTPS/TLS com certificado automatico (RNF-04).
- [ ] Login nao revela se o e-mail existe (US-01).
- [ ] Inbox/conversas restritos a privilegiados; lideres de celula sem acesso (US-11).
- [ ] Itens da fila so aparecem para quem pode resolve-los (delta-006).
- [ ] Captura restrita ao numero oficial; conversas pessoais do pastor nunca registradas (US-07/RF-09).
- [ ] Consentimento por finalidade para atendimento solicitado, cuidado pastoral, tarefas operacionais e comunicados; a D2B2a integrada cobre apenas persistencia interna, sem caller, e o opt-out global prevalece (US-31/32/33/RNF-06).
- [x] Rascunhos D2B2b3A isolados por tenant, com revisao otimista, ator server-side, auditoria sem payload e status fixo `DRAFT_NOT_APPROVED`; implementacao integrada na PR #320 e ainda inativa. Esta missao nao aplicou a migration D2B2b3A; DEV e PROD confirmaram a ausencia.
- [ ] Pacote humano e juridico aprovado por finalidade antes de catalogo ou writer; D2B2b1 nega todo grant enquanto ele estiver ausente.
- [ ] Registro de termo imutavel e prova correlacionada, nao apenas versao + data/hora; re-aceite conforme mudanca aprovada e mascara de CPF/dados sensiveis nos logs (delta-040/052).
- [ ] Memoria privada excluida de ponta a ponta apos solicitacao via WhatsApp e aprovacao admin, incluindo midia, transcricao, resumo, checkpoint e vetores derivados.
- [ ] Webhooks (Evolution API, Asaas) com validacao de assinatura.
- [ ] Idempotencia de mensagens — sem contatos duplicados apos reconexao (RNF-16).
- [ ] Worker de filas com reprocessamento em falha temporaria (RNF-17).
- [ ] Logs de consumo de IA por igreja e logs de conversacao desde o dia 1 (RNF-24).
- [ ] Paginacao em todas as listas (RNF-09).

### 5.3 .env.example
```dotenv
# App
APP_ENV=production
APP_BASE_URL=https://app.pastorai.com.br
FRONTEND_URL=https://app.pastorai.com.br

# Clerk (Auth - US-01 / RNF-01)
CLERK_PUBLISHABLE_KEY=pk_live_xxx
CLERK_SECRET_KEY=sk_live_xxx
CLERK_JWT_ISSUER=https://clerk.pastorai.com.br

# Supabase (Postgres + RLS - US-02 / RNF-02)
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=eyJxxx
SUPABASE_SERVICE_ROLE_KEY=eyJxxx
DATABASE_URL=postgresql://user:pass@host:5432/pastorai

# Runtime privado do agente (D2A). Vazio ate o provisioning operacional.
# Nunca reutilizar DATABASE_URL nem credenciais postgres/service_role.
AGENT_RUNTIME_DATABASE_URL=

# Criptografia de segredos (RNF-03 - credenciais LLM/integracoes)
SECRETS_ENCRYPTION_KEY=base64_32_bytes_key

# Evolution API (WhatsApp - US-05..US-08)
EVOLUTION_API_URL=https://evo.pastorai.com.br
EVOLUTION_API_KEY=xxx
EVOLUTION_WEBHOOK_SECRET=xxx

# OpenAI BYO-LLM (US-27 / RNF-20) - chave default opcional; igreja usa a propria cifrada no banco
OPENAI_API_KEY=
AGENT_DEFAULT_MODEL=gpt-5.6-luna
ASSISTANT_DEFAULT_MODEL=gpt-5.6-luna

# Brevo (e-mail de convite - US-03; fechado por padrao)
BREVO_API_KEY=
BREVO_FROM_EMAIL=no-reply@igreja12.com.br
BREVO_FROM_NAME=Igreja 12
BREVO_SEND_MODE=off
BREVO_CANARY_RECIPIENTS=

# Google Calendar (US-30)
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxx
GOOGLE_REDIRECT_URI=https://app.pastorai.com.br/oauth/google/callback

# Asaas (pagamento - US-34..US-36)
ASAAS_API_KEY=xxx
ASAAS_BASE_URL=https://api.asaas.com/v3
ASAAS_WEBHOOK_SECRET=xxx

# Worker / Filas (RNF-17)
REDIS_URL=redis://localhost:6379/0

# LangGraph / Agente (RNF-08/15)
# Reservado ao checkpointer duravel futuro. A baseline atual apenas avisa se preenchido.
AGENT_GRAPH_CHECKPOINT_URL=
```

---

## 6. Edge Cases, Estados de Falha e Permissoes por Estado

> Enriquecimento do Design Lock: detalha o comportamento de **erro, concorrencia, degradacao, timeout e bloqueio por permissao** DENTRO das telas e estados ja travados (secao 4.2/4.5). Nenhuma tela, menu ou fluxo novo e criado — apenas se especifica o que cada tela existente faz fora do "caminho feliz". Estados novos mapeiam para os estados existentes `loading`/`empty`/`error`/`*-flow` ou como sub-estados internos. Sugestoes que exigiriam tela/fluxo novo estao na secao 6.13 (apenas registro).

### 6.1 login (idle, loading, error, success)
| Edge case | Comportamento | Estado | Refs |
|-----------|---------------|--------|------|
| Clerk indisponivel / timeout de rede | Mensagem generica "nao foi possivel autenticar, tente novamente" + retry; nunca revela existencia de e-mail | `error` | US-01, RNF-01 |
| Autenticado no Clerk mas sem `app_user` vinculado | Bloqueia acesso: "sua conta nao esta vinculada a nenhuma igreja"; oferece logout | `error` | US-02, F1 |
| Igreja `suspensa` / `inadimplente` | Login barrado com aviso de billing; CTA so para admin (ir a `#assinatura`); demais papeis veem mensagem de contato com o admin | `error` | US-35, `igrejas.status` |
| Sessao expirada / token Clerk invalido em uso | Redireciona para `#login`; preserva rota de retorno apos re-login | `idle` (apos redirect) | 5.1, US-01 |
| Multiplas tentativas / rate limit | Resposta generica, sem distinguir e-mail valido; backoff | `error` | US-01 |

### 6.2 dashboard (loading, empty, populated)
| Edge case | Comportamento | Estado | Refs |
|-----------|---------------|--------|------|
| Falha ao carregar a fila (API erro 5xx/timeout) | Banner de erro com botao "tentar novamente"; mantem ultimo conteudo se houver | `error` (sobre `loading`) | US-15 |
| Concorrencia: item ja assumido/resolvido por outro usuario | Acao retorna conflito (stale); item atualiza para o estado real e exibe aviso "ja tratado por <usuario>" | `populated` (item `resolved`) | US-16, delta-006 |
| Item sem permissao para o papel atual | Nao listado para quem nao pode resolver (filtro por papel); se acessado via assistente, exibido read-only | `populated` (filtrado) | delta-006, US-17 |
| `deadline-badge` vence em tempo real | Badge transiciona `dentro`->`alerta`->`atrasado` sem reload; reordena por prioridade | `populated` | US-40, delta-022 |
| Atribuir a responsavel inexistente/inativo | Validacao; impede atribuir a usuario `convidado`/removido | `populated` | US-17 |

### 6.3 inbox (loading, empty, list, thread-ia-active, thread-human, thread-waiting)
| Edge case | Comportamento | Estado | Refs |
|-----------|---------------|--------|------|
| WhatsApp `offline`/`reconectando` | Banner de degradacao no topo da thread; campo de envio desabilitado; instrucao para ir a `#whatsapp` (admin) | `thread-*` degradado | US-06, US-08 |
| Concorrencia no handoff (outro humano ja assumiu) | Acao "Assumir" retorna conflito; thread reflete `thread-human` com `assumido_por` real | `thread-human` | US-12 |
| Falha de envio (Evolution API timeout) | Mensagem marcada como "falha ao enviar" + retry manual; nao duplica no reenvio (idempotencia) | `thread-human` | RNF-16, RNF-17 |
| Lider de celula via deep-link `#inbox` | Bloqueio de permissao: "voce nao tem acesso ao atendimento" | acesso negado | US-11 |
| Conversa de contato sem consentimento ainda | Sinaliza que so nome+telefone foram coletados; agente nao avanca coleta sem termo | `thread-ia-active` | delta-040, US-31 |
| Devolver para IA com IA pausada por erro de credencial | Aviso de que a IA esta indisponivel (sem credencial valida); mantem em `thread-human` | `thread-human` | US-13, RF-30 |

### 6.4 calendario (loading, empty, month)

> **Em expansao (delta-049/050/051 — EVT-0, 2026-06-29):** a tela `month`-only abaixo e o **baseline atual**. O modulo Agenda passa a ter abas **Semana/Mes/Ano/A confirmar/Planejamento**, status do evento (`confirmado`/`a_confirmar`), confirmacao manual e import Google→pendente. MVP = EVT-1..5 (manual, sem Google, sem envio). Decisao completa: `docs/design/AGENDA-EVENTOS-EVT0-decisao.md`.

| Edge case | Comportamento | Estado | Refs |
|-----------|---------------|--------|------|
| Falha de sync / token Google expirado | Banner "calendario desconectado" + CTA reconectar; eventos locais ainda visiveis | `error` (sobre `month`) | US-30, RF-34 |
| Evento salvo local mas falha no Google | Marca evento como "nao sincronizado"; permite re-tentar sync | `month` (item parcial) | US-30 |
| Mes sem eventos | `empty-state` "nenhum evento neste mes" | `empty` | US-30 |

### 6.5 comunicados (compose, segment, review, empty)
| Edge case | Comportamento | Estado | Refs |
|-----------|---------------|--------|------|
| Alcance 0 (todos opt-out/sem consentimento) | Bloqueia envio; aviso "nenhum destinatario elegivel" com contagem de ignorados | `review` (envio desabilitado) | US-32, US-33, RF-38 |
| WhatsApp offline ao enviar "agora" | Impede envio imediato; sugere agendar ou reconectar | `review` | US-06, US-33 |
| Agendamento com data/hora no passado | Validacao impede salvar | `compose`/`review` | US-33 |
| Falha parcial de disparo | Relatorio pos-envio: enviados x falhas; sem reenviar aos ja entregues | `review` (resultado) | US-33, RNF-17 |
| Segmento sem nenhuma pessoa | Aviso no passo `segment` antes de revisar | `segment` | US-33 |

### 6.6 equipe (loading, empty, list, invite, edit-roles)
| Edge case | Comportamento | Estado | Refs |
|-----------|---------------|--------|------|
| E-mail ja convidado/existente | Validacao no `invite`: "ja existe usuario com este e-mail" | `invite` | US-03 |
| Brevo falha ao enviar convite | Usuario fica `convidado` com aviso "convite nao enviado" + reenviar | `list` (item alerta) | US-03 |
| Remover/rebaixar o ultimo admin | Bloqueio: "a igreja precisa de ao menos um admin" | `edit-roles` | US-04, delta-005 |
| Usuario editando os proprios papeis | Restrito (nao pode auto-elevar/auto-rebaixar admin) | `edit-roles` | US-04 |
| Revogar acesso de usuario ativo | Confirma; sessoes futuras bloqueadas (revalidacao backend) | `list` | 5.1, F4 |

### 6.7 ganhar / contatos (loading, empty, novos-contatos, visitantes / list, detail)
| Edge case | Comportamento | Estado | Refs |
|-----------|---------------|--------|------|
| Telefone ja existente (dedupe) | Nao cria duplicado; aponta contato existente (merge por telefone+igreja) | `list` | RNF-16, US-09 |
| Vincular a celula inativa/sem lider | Bloqueia selecao de celula `ativo=false`; exige celula valida | `detail` | US-20, delta-029 |
| Promover visitante sem criterio (presencas<3 e nao aceitou) | Botao de promover desabilitado com tooltip do criterio | `detail` | F2, delta-013 |
| Falha ao salvar contato | Mantem formulario preenchido + erro inline | `detail` | US-09 |

### 6.8 consolidar / consol-individual (loading, empty, fila, detalhe, 100-consolidadas)
| Edge case | Comportamento | Estado | Refs |
|-----------|---------------|--------|------|
| Confirmar etapa sem ser o consolidador responsavel | Bloqueio por gate de identidade: so `responsavel_id` confirma | `detalhe` | delta-018, US-39 |
| Prazo de 24h (fluxo visitante) vencido | `deadline-badge` `atrasado`; item escalado na fila; visivel destaque | `fila`/`detalhe` | US-40, A1/delta-039 |
| Lancar decisao fluxo A sem celula disponivel | `decision-modal` impede concluir `celula-flow`; sugere `visitante-flow` (24h) | `decision-modal` | US-37, delta-021 |
| Papel sem permissao acessa `#consolidar`/`#consol-individual` | Tela restrita: so `lider_consol`/admin/pastor (US-38) | acesso negado | US-38, 2.2 |
| Concluir consolidacao com etapas pendentes | Bloqueia "concluir" ate etapas obrigatorias confirmadas | `detalhe` | US-39 |

### 6.9 whatsapp (connected, disconnected, reconnecting)
| Edge case | Comportamento | Estado | Refs |
|-----------|---------------|--------|------|
| QR code expira antes de escanear | Regenera QR automaticamente; aviso "QR expirado, gerando novo" | `disconnected`/`reconnecting` | US-05 |
| Falha na Evolution API ao conectar | Estado de erro com retry; status nao muda para `connected` | `disconnected` | US-05, US-06 |
| Queda apos conectado | Transiciona para `reconnecting` sem reload; alerta admin | `reconnecting` | US-06 |
| Numero ja conectado em outra instancia | Aviso de conflito (1 numero por igreja — RF-07) | `disconnected` | US-05, RF-07 |

### 6.10 agente (behavior, credential, crons)
| Edge case | Comportamento | Estado | Refs |
|-----------|---------------|--------|------|
| Chave LLM invalida ao salvar | Validacao falha; nao ativa credencial; chave nunca exibida apos tentativa | `credential` | RF-30, RNF-03, US-27 |
| Modelo fora da allowlist ou sem acesso pela chave da igreja | Rejeita sem trocar a selecao salva; a chave nunca e devolvida | `credential` | RNF-03, RNF-20, US-27 |
| Modelo selecionado indisponivel durante uma resposta | Tenta somente a cadeia permitida de menor custo; registra em `ai_usage_logs` o modelo realmente usado | `credential` | F8, RNF-20, RNF-24, US-27 |
| Salvar comportamento com agente ativo | Confirma aplicacao; novas conversas usam a nova config | `behavior` | US-28 |
| Cron com gatilho de estado invalido | Validacao do gatilho antes de salvar | `crons` | US-29, RNF-23 |
| Ativar agente sem credencial valida | Bloqueio: exige credencial validada primeiro | `behavior`/`credential` | US-27, US-28 |

### 6.11 assinatura (active, past-due, plans)
| Edge case | Comportamento | Estado | Refs |
|-----------|---------------|--------|------|
| Pagamento Asaas pendente/aguardando webhook | Estado intermediario "aguardando confirmacao"; sem liberar acesso ate webhook | `past-due`/pendente | US-34, US-35, RF-39 |
| Pagamento falhou / inadimplente | `past-due` com CTA de regularizacao; recursos sensiveis limitados | `past-due` | US-35 |
| Upgrade automatico por porte | Notifica admin do novo plano/limite; reflete em `stat-card` | `active` | US-36, RF-42 |
| Acesso a `#assinatura` por nao-admin | Restrito a `admin` (config) | acesso negado | delta-005 |

### 6.12 enviar / g12 / central-celula / permissoes / assistant-panel
| Tela | Edge case | Comportamento | Estado | Refs |
|------|-----------|---------------|--------|------|
| enviar | Aprovar multiplicacao com `supervisao_ok=false` | Botao "aprovar" desabilitado com motivo | `agendadas`/`aptos` | delta-027 |
| enviar | Multiplicacao `sem_agendamento` | Destaca pendencia de data prevista | `sem-agendamento` | US-21 |
| central-celula | Relatorio pendente estourando SLA (2h) | `status-pill` warn->danger; gera/realca acao na fila | `relatorios` | US-26, A1/delta-039 |
| g12 | Descendencia vazia/sem liderados | `empty-state` no organograma | `empty` | US-21, US-22 |
| permissoes | Tentar remover `dashboard` da matriz | Bloqueio: dashboard garantido a todos | `matrix` | delta-010 |
| permissoes | Falha ao salvar matriz | Erro + mantem alteracoes locais para re-tentar | `matrix` | delta-010 |
| permissoes | Alterar permissao reflete em menu/dashboard | Atualizacao em tempo real apos `saved` | `saved` | delta-010 |
| assistant-panel | Sem credencial LLM / LLM indisponivel / timeout | Estado de erro no painel: "assistente indisponivel"; nao quebra a tela | `open` (erro) | US-41, US-27 |
| assistant-panel | Pergunta sobre tela nao permitida ao papel | Nao sugere telas fora do acesso; orienta dentro do escopo | `thinking`/`open` | delta-023, US-41 |

### 6.13 Sugestoes futuras (fora do Design Lock — apenas registro, NAO implementar)
> Itens que melhorariam o produto mas exigiriam **tela, menu ou fluxo novo** — portanto fora do escopo do lock atual. Registrados para um ciclo futuro, sem alterar a SPEC operacional.
- Tela/painel dedicado de **saude de integracoes** (status Evolution/Asaas/Google/Brevo) — hoje degradacao e sinalizada por banners nas telas existentes.
- **Central de notificacoes** in-app (ex.: upgrade de plano, convite nao enviado, SLA estourado) — hoje refletido por estados nas telas de origem.
- **Fluxo de merge manual** de contatos duplicados — hoje dedupe e automatico por telefone+igreja.
- **Historico/auditoria visivel no painel** de envios de comunicados e handoffs — hoje so em logs backend (F8).
