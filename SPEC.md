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
- **Pitch:** o **PastorAI** e um SaaS multi-tenant para igrejas no modelo de celulas G12 que transforma o WhatsApp oficial da igreja em um canal de atendimento, cadastro e acompanhamento conduzido por um agente de IA, somado a um painel web que organiza o trabalho pastoral como uma **fila de pendencias** ("o que exige acao hoje").
- **Publico-alvo (personas):**
  1. **Pastor / Admin da Igreja** — responsavel maximo; ve pendencias, toma decisoes sensiveis, configura o sistema.
  2. **Lider de Celula** — rotina semanal; envia relatorio por WhatsApp, acompanha membros/visitantes, recebe alertas. Nao acessa inbox nem configuracao.
  3. **Usuario final via WhatsApp** (visitante/membro/lider) — interage 100% pelo WhatsApp; nao acessa o painel.
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
| E-mail | **Resend** (convites/ativacao) |
| Calendario | **Google Calendar** (sincronizacao de eventos) |
| Pagamento | **Asaas** (PIX, boleto, cartao; setup fee + mensalidade) |
| LLM | **OpenAI (BYO-LLM)** — credencial da propria igreja, extensivel |
| Infra | **Coolify/Dokploy** em VPS unica >= 4GB RAM, TLS automatico (Let's Encrypt) |

### Plataforma
- **Web** responsiva mobile-first + **PWA** (sem app nativo iOS/Android no MVP — RNF-19).
- Usuario final atendido 100% via **WhatsApp**.

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
| US-27 | Cadastrar credencial do provedor LLM (BYO) |
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

#### `igrejas` (tenants — F1)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| nome | text NOT NULL | |
| status | enum(`ativa`,`suspensa`,`aguardando_aprovacao`,`inadimplente`) | default `ativa` |
| plano | text | `ate_100`/`101_200`/`acima_201` |
| created_at | timestamptz | default now() |

#### `pessoas` (modelo unificado — F2/F6/F7; data-contacts, data-contact-detail, data-pipeline-stage)
| Campo | Tipo | Origem (data req / story) |
|-------|------|---------------------------|
| id | uuid PK | |
| igreja_id | uuid FK -> igrejas | F1 / US-02 |
| nome | text NOT NULL | data-contacts.nome / US-09 |
| telefone | text NOT NULL | data-contacts.telefone / US-09 |
| email | text | |
| genero | enum(`m`,`f`) | delta-017/026 (ranking/convite) |
| faixa_etaria | text | delta-017/025 |
| endereco | text | US-10 |
| tipo | enum(`visitante`,`membro`,`lider`,`pastor`,`discipulo`) | data-contacts.tipo / US-18 |
| etapa | enum(`ganhar`,`consolidar`,`discipular`,`enviar`) | data-pipeline-stage.etapa / US-18 |
| subetapa | enum(`novo_contato`,`visitante`,`em_consolidacao`,`consolidado`) | data-pipeline-stage.subetapa |
| presencas_celula | int default 0 | data-pipeline-stage / delta-013 |
| aceitou_jesus | boolean default false | data-pipeline-stage / delta-013 |
| acompanhamento | enum(`sem`,`em_andamento`,`consolidado`) | data-contacts.acompanhamento / US-18 |
| sem_interesse | boolean default false | CSIM (Onda 1/#1) — contato sem interesse ministerial, fora do funil |
| sem_interesse_motivo | text | CSIM (Onda 1/#1) — motivo curto (ex.: empresa, outra cidade) |
| origem | text | US-09 (ex.: whatsapp) |
| primeiro_contato | timestamptz | US-09 |
| celula_id | uuid FK -> celulas NULL | data-contacts.celula / US-20 |
| lider_id | uuid FK -> pessoas NULL | F7 / lideranca G12 (RNF-25) |
| consentimento | boolean default false | data-consent.consentido / US-31 |
| optout | boolean default false | data-consent.optout / US-32 |
| apto_proxima_cd | boolean default false | US-39 / RF-45 |
| created_at | timestamptz default now() | |

#### `app_users` (acesso ao painel via Clerk; data-team, data-user-roles)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK -> igrejas | F1 |
| clerk_user_id | text UNIQUE | US-01 (Clerk) |
| pessoa_id | uuid FK -> pessoas NULL | vincula login a pessoa unificada (F6) |
| nome | text NOT NULL | data-team.nome |
| email | text NOT NULL | data-team.email |
| status | enum(`ativo`,`convidado`) | data-team.status / US-03 |
| created_at | timestamptz default now() | |

#### `user_roles` (papeis acumulados — F3; data-user-roles)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| user_id | uuid FK -> app_users | |
| papel | enum(`admin`,`pastor`,`lider_g12`,`lider_consol`,`lider_celula`,`lider_mult`,`membro`) | data-team.papeis / US-04 |
| UNIQUE(user_id, papel) | | uniao de acessos |

#### `role_permissions` (matriz papel x tela — delta-010; data-role-perms)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| papel | enum(`pastor`,`lider_g12`,`lider_consol`,`lider_celula`,`lider_mult`,`membro`) | data-role-perms.papel / US-04 |
| tela | text | screenId liberado (data-role-perms.telas) |
| UNIQUE(igreja_id, papel, tela) | | admin tem acesso implicito; dashboard garantido a todos |

#### `celulas` (data-cells, data-cell-detail; delta-029)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| nome | text NOT NULL | data-cells.nome / US-21 |
| lider_id | uuid FK -> pessoas | data-cells.lider / US-21 |
| dia_reuniao | text | data-cells.diaReuniao |
| cobertura_espiritual | text NOT NULL | delta-029 (campo obrigatorio) / US-21 |
| ativo | boolean default true | US-21 (inativar) |
| created_at | timestamptz default now() | |

#### `cell_alerts` (alertas sobre liderados — data-cell-detail.alertas; US-23)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| celula_id | uuid FK | |
| pessoa_id | uuid FK -> pessoas | contato alvo do alerta |
| gatilho | text | gatilho configuravel (RF-26) |
| acao_esperada | text | |
| tratado | boolean default false | US-23 (alerta tratado ao baixar) |
| created_at | timestamptz default now() | |

#### `conversations` (data-conversations; US-08/11/12/13)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| pessoa_id | uuid FK -> pessoas | |
| telefone | text NOT NULL | data-conversations.telefone |
| estado | enum(`ia`,`humano`,`aguardando`) | data-conversations.estado |
| assumido_por | uuid FK -> app_users NULL | US-12 (quem assumiu) |
| assumido_em | timestamptz NULL | US-12 (horario) |
| ultima_mensagem | text | data-conversations.ultimaMensagem |
| nao_lidas | int default 0 | data-conversations.naoLidas |
| espera_desde | timestamptz NULL | data-human-queue.esperaMin (US-14) |
| numero_oficial | boolean default true | US-07 (so numero oficial) |
| updated_at | timestamptz | |

#### `messages` (historico cronologico — US-11)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| conversation_id | uuid FK | |
| direcao | enum(`in`,`out`) | |
| autor | enum(`contato`,`ia`,`humano`) | |
| texto | text | |
| criado_em | timestamptz default now() | ordem cronologica |

#### `work_queue_items` (data-work-queue, data-next-actions; US-15/16/17/26/40)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| tipo | enum(`visitante`,`atendimento`,`relatorio`,`conectar_celula`,`fonovisita`) | data-work-queue.tipo + US-40 (delta-022) |
| titulo | text NOT NULL | data-work-queue.titulo |
| contexto | text | data-work-queue.contexto |
| pessoa_id | uuid FK -> pessoas NULL | alvo da pendencia |
| responsavel_id | uuid FK -> app_users NULL | data-work-queue.responsavel (US-17; "Nao atribuido" = NULL) |
| status | enum(`aberto`,`assumido`,`resolvido`) | data-work-queue.status |
| prazo | timestamptz NULL | US-40 (conectar a celula 24h, fonovisita) |
| prioridade | int | ordenacao por urgencia (RF-18) |
| created_at | timestamptz default now() | |

#### `reports` (relatorios de celula — data-reports; US-24/25/26)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| celula_id | uuid FK | data-reports.celula |
| semana | text NOT NULL | data-reports.semana |
| data_reuniao | date | US-24 |
| presentes | int | data-reports.presentes |
| visitantes | int | data-reports.visitantes |
| decisoes | int | US-24 (decisoes por Jesus) |
| oferta | numeric NULL | delta-041 |
| observacoes | text | US-25 |
| status | enum(`recebido`,`pendente`) | data-reports.status |
| origem | enum(`whatsapp_texto`,`whatsapp_audio`,`manual`) | delta-041 |
| created_at | timestamptz default now() | |

#### `broadcasts` (data-broadcasts; US-33 / delta-009)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| titulo | text NOT NULL | data-broadcasts.titulo |
| mensagem | text NOT NULL | data-broadcasts.mensagem |
| segmentos | text[] NOT NULL | data-broadcasts.segmentos (multi-select) |
| modo | enum(`agora`,`agendado`) | data-broadcasts.modo |
| data | date NULL | data-broadcasts.data |
| hora | text NULL | data-broadcasts.hora |
| repeticao | enum(`once`,`daily`,`weekly`,`biweekly`,`monthly`) NULL | data-broadcasts.repeticao |
| alcance | int NULL | data-broadcasts.alcance |
| ignorados_optout | int NULL | RF-38 (excluir opt-out/sem consentimento) |
| status | enum(`rascunho`,`agendado`,`enviado`) | |
| created_at | timestamptz default now() | |

#### `events` (data-events; US-30)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| titulo | text NOT NULL | data-events.titulo |
| data | date NOT NULL | data-events.data |
| hora | text NULL | data-events.hora |
| descricao | text | US-30 |
| google_event_id | text NULL | RF-34 (sync Google Calendar) |
| created_at | timestamptz default now() | |

#### `whatsapp_connections` (data-whatsapp-connection; US-05/06/07)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK UNIQUE | F1 + RF-07 (1 numero por igreja) |
| numero | text | data-whatsapp-connection.numero |
| status | enum(`online`,`offline`,`reconectando`) | data-whatsapp-connection.status |
| instance | text | id da instancia Evolution API |
| ultima_sync | timestamptz | data-whatsapp-connection.ultimaSync |

#### `agent_configs` (data-agent-config; US-28 / delta-009)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK UNIQUE | F1 |
| nome | text | data-agent-config.nome |
| tom | text | data-agent-config.tom |
| comportamento | text NOT NULL | prompt (data-agent-config.comportamento) |
| publico_alvo | text[] | data-agent-config.publicoAlvo |
| acessos | text[] | enum(contatos,celulas,relatorios,calendario,comunicados,assinatura) |
| ativo | boolean default true | data-agent-config.ativo |

#### `llm_credentials` (data-llm-credential; US-27 / RNF-03)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK UNIQUE | F1 / BYO por igreja |
| provedor | text NOT NULL | data-llm-credential.provedor (OpenAI no MVP) |
| api_key_encrypted | text NOT NULL | cifrada; nunca exibida (RNF-03) |
| validado | boolean default false | RF-30 (validar antes de ativar) |
| ativo | boolean default false | |

#### `crons` (data-crons; US-29 / delta-038 — gatilhos por estado)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| nome | text NOT NULL | data-crons.nome |
| frequencia | text NOT NULL | data-crons.frequencia (horario fixo) |
| gatilho_estado | text NULL | RNF-23 (prazo vencendo, meta atingida) |
| acao | text | acao do agente |
| ativo | boolean default true | data-crons.ativo |

#### `subscriptions` (data-subscription; US-34/35/36)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK UNIQUE | F1 |
| plano | text NOT NULL | data-subscription.plano |
| status | enum(`ativa`,`pendente`,`inadimplente`) | data-subscription.status |
| pessoas | int | data-subscription.pessoas (porte) |
| limite | int | data-subscription.limite |
| proxima_cobranca | date NULL | data-subscription.proximaCobranca |
| asaas_customer_id | text NULL | RF-39 (Asaas) |
| asaas_subscription_id | text NULL | |
| setup_pago | boolean default false | US-34 (setup fee R$1.000) |

#### `system_managers` (data-system-managers; US-03/04 — delta-015)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| nome | text NOT NULL | data-system-managers.nome |
| email | text NOT NULL | data-system-managers.email |
| papel_operacional | enum(`admin_sistema`,`operador`) | data-system-managers.papelOperacional |

> **[Fase 1 — divergência de implementação · 2026-06-14]** Tabela `system_managers` **descontinuada**: `operador` → papel `operador` em `user_roles`; `admin_sistema` → papel `admin`. Módulo `system_managers.py` e a API `api-system-managers` (`/system-managers`) **removidos**; a tela `#gerentes`/`nav-gerentes` saiu do contrato operacional (gestão concentra-se em `#equipe` + `#permissoes`). Migração: `0008_add_operador_role.sql` (enums) + `0009_unify_system_managers.sql` (backfill); tabela/enum não dropados ainda (rollback). Conceder acesso passa a vincular `app_user` a uma `pessoa` (FK `app_users.pessoa_id`).

#### `consolidacoes` (data-consolidacao; US-38/39 — delta-018)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| pessoa_id | uuid FK -> pessoas | data-consolidacao.pessoa |
| tipo | enum(`individual`,`universidade_vida`) | data-consolidacao.tipo |
| responsavel_id | uuid FK -> app_users NULL | data-consolidacao.responsavel (consolidador) |
| progresso | int default 0 | data-consolidacao.progresso |
| concluida | boolean default false | data-consolidacao.concluida |
| prazo_conexao | timestamptz NULL | US-40 (24h conectar a celula) |
| created_at | timestamptz default now() | |

#### `consolidacao_etapas` (trilha individual — delta-018; US-39)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| consolidacao_id | uuid FK | |
| etapa | text | aceitou_jesus / conectou_celula / fonovisita / visita_n |
| concluida | boolean default false | US-39 |
| confirmada_por | uuid FK -> app_users NULL | gate por identidade (so consolidador — delta-018) |
| confirmada_em | timestamptz NULL | |

#### `decisions` (data-decision; US-37/40 — delta-021)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| pessoa_id | uuid FK -> pessoas | data-decision.pessoa |
| origem | text | data-decision.origem (culto/celula) |
| vinculo | enum(`celula`,`visitante`) | data-decision.vinculo |
| celula_id | uuid FK NULL | data-decision.celulaId (fluxo A) |
| responsavel_id | uuid FK NULL | data-decision.responsavel |
| prazo_conexao | timestamptz NULL | fluxo B: 24h (data-decision.prazoConexao) |
| created_at | timestamptz default now() | |

#### `multiplicacoes` (data-multiplicacoes, data-aptos-lideranca; enviar — delta-027)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| celula_id | uuid FK | data-multiplicacoes.celula |
| status | enum(`agendada`,`sem_agendamento`,`aprovada`,`concluida`) | data-multiplicacoes.status |
| data_prevista | date NULL | data-multiplicacoes.dataPrevista |
| descendencia | text NULL | data-multiplicacoes.descendencia |
| novo_lider_id | uuid FK -> pessoas NULL | delta-027 (aprovacao gateada) |
| supervisao_ok | boolean default false | delta-027 (botao aprovar desabilitado se pendente) |
| aprovada_por | uuid FK -> app_users NULL | US-23 |

#### `consent_records` (LGPD — delta-040; RNF-06)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| pessoa_id | uuid FK -> pessoas | |
| termo_versao | text | versao do termo aceito |
| aceite_em | timestamptz | data/hora do aceite |

#### `ai_usage_logs` (auditoria de IA — F8/RNF-24; delta-037)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| modelo | text | |
| tokens_in | int | |
| tokens_out | int | |
| custo | numeric | |
| ferramenta | text NULL | tool usada pelo agente |
| created_at | timestamptz default now() | |

#### `agent_conversation_logs` (logs do agente — F8/RNF-24)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | uuid PK | |
| igreja_id | uuid FK | F1 |
| conversation_id | uuid FK NULL | |
| evento | text | interacao/decisao/tool-call |
| payload | jsonb | CPF/dados sensiveis mascarados (delta-040) |
| created_at | timestamptz default now() | |

> **Telas legadas / stub (sem novas tabelas):** `contatos`, `celulas`, `relatorios` reusam `pessoas`/`celulas`/`reports` (deep-link, fora do menu — delta-012). `universidade-vida` e `capacitacao` estao BLOQUEADAS no MVP (delta-019/028): nao requerem tabelas operacionais; quando habilitadas usarao extensoes de `consolidacoes`/trilha. As telas `super-admin-igrejas` / `super-admin-provisionar` sao **stub** (superficie separada — delta-024): **nao** criar tabelas/endpoints no painel operacional.

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
- **Agente (F5/delta-034):** usa service role com o MESMO escopo de `igreja_id` e as mesmas validacoes de negocio de um humano; nunca ignora regras.

### 2.3 Triggers
- **`trg_promote_pipeline`** (AFTER UPDATE em `pessoas`/`reports`/`consolidacoes`) — state machine F2/delta-013/031: avanca `etapa`/`subetapa` automaticamente quando `presencas_celula >= 3` OU `aceitou_jesus = true` (visitante -> membro); ao concluir consolidacao individual, marca criterio de UV.
- **`trg_link_cell_promote`** (AFTER UPDATE em `pessoas.celula_id`) — US-20: ao vincular contato a celula, `acompanhamento = consolidado/membro`, sai da lista "em acompanhamento".
- **`trg_report_received_clears_queue`** (AFTER INSERT em `reports` com `status=recebido`) — US-26/RF-29: baixa automaticamente o `work_queue_items` tipo `relatorio` da celula/semana.
- **`trg_decision_opens_consolidation`** (AFTER INSERT em `decisions`) — US-37/delta-041: cria `consolidacoes` (etapa inicial); se `vinculo=visitante`, cria `work_queue_items` tipo `conectar_celula` com `prazo = now()+24h`.
- **`trg_consent_on_inbound`** (AFTER INSERT em `messages` direcao=in de novo contato) — US-31/RF-36: concede `consentimento=true` na pessoa (a igreja nunca inicia comunicacao espontanea).
- **`trg_subscription_autoupgrade`** (AFTER INSERT/UPDATE em `pessoas`) — US-36/RF-42: ao ultrapassar `subscriptions.limite`, promove `plano` e marca notificacao ao admin.
- **`trg_set_updated_at`** — manutencao de `updated_at`.
- **`trg_sla_engine`** (cron/worker — A1/delta-039/RNF-23): detecta SLA estourando (relatorio 2h, conexao 12h, fonovisita 24h) e dispara cobranca por WhatsApp; escalona lider sem resposta -> coordenacao.

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
celulas (1) ──< (N) reports
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
igrejas (1) ──< (N) ai_usage_logs / agent_conversation_logs
```

---

## 3. Backend

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
      resend_mail.py        # convites/ativacao
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
| api-llm-credential | `POST /agent/credential` | agente | action-save-llm-key | US-27 |
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

### 3.4 Agent Graph (LangGraph) — Orquestrador multiagente
> Arquitetura de agentes: **um Agente Orquestrador central por igreja (tenant)** e que coordena
> sub-agentes especializados. **Principio fundamental:** o Orquestrador e o **unico** que fala no
> **WhatsApp oficial da igreja** — recebe TODA mensagem do numero oficial, decide o roteamento,
> delega aos sub-agentes e consolida a **resposta unica** que sai pelo numero oficial. Os
> sub-agentes **nunca** falam diretamente com o usuario final: eles processam e devolvem o
> resultado ao Orquestrador (US-07: apenas conversas com o numero oficial sao tratadas).

- **Agente Orquestrador (US-08 / delta-034):** ponto unico de entrada e saida no WhatsApp oficial.
  Roteia toda mensagem recebida no numero oficial, mantem o contexto/estado da conversa,
  escolhe qual(is) sub-agente(s) acionar, agrega os resultados e emite a resposta unica via
  LLM BYO (US-08/US-27/RF-11). E o `entry node`/supervisor do grafo LangGraph.

- **Sub-agentes coordenados (skills/nodes especializados — NAO falam direto no WhatsApp; respondem ao Orquestrador):**
  - `intake` — cria/atualiza `pessoas` (nome+telefone, origem, primeiro_contato) — US-09/RF-12.
  - `onboarding` — fluxo configuravel (nome, endereco, interesse, oracao, ja foi a igreja/celula); notifica consolidacao; classifica contato/visitante — US-10/RF-13.
  - `report_capture` — extrai relatorio de celula por texto/audio (presentes, visitantes, decisoes, oferta); decisao por Jesus abre consolidacao — US-24/delta-041.
  - `handoff` — pausa/retoma IA conforme estado da conversa; quando humano assume, o Orquestrador suspende a resposta automatica mas a saida continua pelo numero oficial — US-12/US-13.
  - `consent` — apresenta termo antes de coletar dados alem de nome+telefone (delta-040).
- **Roteamento:** o Orquestrador decide o sub-agente com base na intencao/estado da conversa e da `pessoa` (etapa/subetapa F2); transicoes e respostas trafegam de volta pelo supervisor antes de qualquer envio.
- **Distincao do Assistente do painel (US-41):** o `assistant-panel` e um agente **separado**, interno ao painel web, ciente de papel/tenant; **nao** se confunde com o Orquestrador do WhatsApp (canais e publicos distintos).
- **Tools (F5/delta-034):** registrar decisao, marcar presenca, vincular celula, avancar trilha — invocadas pelos sub-agentes/Orquestrador com as mesmas funcoes/validacoes de um humano, no escopo do tenant.
- **Logs (F8/RNF-24):** registrar interacoes, tools usadas, consumo de IA (modelo/tokens/custo) em `ai_usage_logs`/`agent_conversation_logs`, com mascara de dados sensiveis.
- **SLA engine (A1/delta-039):** detecta prazos (relatorio 2h, conexao 12h, fonovisita 24h, Numero de Sonho UV) e dispara cobranca/escalonamento por WhatsApp.

### 3.5 Integracoes Externas
| Integracao | Uso | Stories |
|-----------|-----|---------|
| **Clerk** | Autenticacao/sessao; papeis vem do cadastro autenticado | US-01, US-04 |
| **Supabase (Postgres+RLS)** | Persistencia e isolamento multi-tenant | US-02, RNF-02/21 |
| **Evolution API** | Conexao (QR), envio/recebimento WhatsApp; processo sempre-ligado | US-05..US-08, US-33 |
| **OpenAI (BYO-LLM)** | Respostas do agente; custo da igreja; chave cifrada | US-08, US-27, RNF-20 |
| **Resend** | E-mail de convite/ativacao de usuarios | US-03 |
| **Google Calendar** | Sincronizacao de eventos | US-30 |
| **Asaas** | Checkout (PIX/boleto/cartao), setup fee, status de assinatura, webhooks | US-34, US-35, US-36 |
| **Coolify/Dokploy** | Containers persistentes, restart automatico, TLS | RNF-04/15/18 |

---

## 4. Frontend

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
7. **Convites (US-03):** admin convida (nome+email+papeis); Resend envia link de ativacao; status `convidado` -> `ativo`. Revogacao de acesso suportada.
8. **Agente (F5):** opera com service role no escopo do tenant, usando as mesmas validacoes de um humano.

### 5.2 Checklist de Seguranca
- [ ] Autenticacao exclusivamente via Clerk; sem senhas proprias (RNF-01).
- [ ] RLS habilitado em todas as tabelas com `igreja_id`; nenhuma consulta cruza tenant (RNF-02/RNF-21).
- [ ] Revalidacao de `igreja_id` + papel em cada endpoint (F4/RNF-05).
- [ ] Credenciais LLM e chaves de integracao **cifradas**; nunca exibidas em texto claro apos salvar (RNF-03/US-27).
- [ ] Todo trafego sobre HTTPS/TLS com certificado automatico (RNF-04).
- [ ] Login nao revela se o e-mail existe (US-01).
- [ ] Inbox/conversas restritos a privilegiados; lideres de celula sem acesso (US-11).
- [ ] Itens da fila so aparecem para quem pode resolve-los (delta-006).
- [ ] Captura restrita ao numero oficial; conversas pessoais do pastor nunca registradas (US-07/RF-09).
- [ ] Consentimento concedido so quando a pessoa inicia conversa; opt-out respeitado em comunicados (US-31/32/33/RNF-06).
- [ ] Registro de termo LGPD (versao + data/hora), re-aceite em nova versao e mascara de CPF/dados sensiveis nos logs (delta-040).
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

# Criptografia de segredos (RNF-03 - credenciais LLM/integracoes)
SECRETS_ENCRYPTION_KEY=base64_32_bytes_key

# Evolution API (WhatsApp - US-05..US-08)
EVOLUTION_API_URL=https://evo.pastorai.com.br
EVOLUTION_API_KEY=xxx
EVOLUTION_WEBHOOK_SECRET=xxx

# OpenAI BYO-LLM (US-27 / RNF-20) - chave default opcional; igreja usa a propria cifrada no banco
OPENAI_API_KEY=

# Resend (e-mail de convite - US-03)
RESEND_API_KEY=re_xxx
RESEND_FROM_EMAIL=no-reply@pastorai.com.br

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
AGENT_GRAPH_CHECKPOINT_URL=postgresql://user:pass@host:5432/pastorai
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
| Resend falha ao enviar convite | Usuario fica `convidado` com aviso "convite nao enviado" + reenviar | `list` (item alerta) | US-03 |
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
- Tela/painel dedicado de **saude de integracoes** (status Evolution/Asaas/Google/Resend) — hoje degradacao e sinalizada por banners nas telas existentes.
- **Central de notificacoes** in-app (ex.: upgrade de plano, convite nao enviado, SLA estourado) — hoje refletido por estados nas telas de origem.
- **Fluxo de merge manual** de contatos duplicados — hoje dedupe e automatico por telefone+igreja.
- **Historico/auditoria visivel no painel** de envios de comunicados e handoffs — hoje so em logs backend (F8).
