# SPEC_PROGRESS - PastorAi-1.0

## Status: 16/16 sprints concluidas
Ultima atualizacao: 2026-06-13T22:14:07.937Z

---

## Sprint 001 - Fundacao de Database (Schema, RLS, Triggers, Seed) [CONCLUIDA]
- Schema completo de tabelas: Criar migrations com todas as tabelas da secao 2.1: igrejas, pessoas, app_users, user_roles, role_permissions, celulas, cell_alerts, conversations, messages, work_queue_items, reports, broadcasts, events, whatsapp_connections, agent_configs, llm_credentials, crons, subscriptions, system_managers, consolidacoes, consolidacao_etapas, decisions, multiplicacoes, consent_records, ai_usage_logs, agent_conversation_logs.
- RLS por tenant e current_igreja_id(): Habilitar RLS em todas as tabelas com igreja_id e criar a funcao current_igreja_id() que deriva o tenant de app_users a partir do clerk_user_id do JWT. Policies padrao USING/WITH CHECK por igreja_id; igrejas restrita ao proprio registro.
- Triggers de state machine e automacoes: Implementar os triggers da secao 2.3: trg_promote_pipeline, trg_link_cell_promote, trg_report_received_clears_queue, trg_decision_opens_consolidation, trg_consent_on_inbound, trg_subscription_autoupgrade, trg_set_updated_at.
- Seed da igreja piloto: Inserir os dados de seed da secao 2.4: igreja piloto, app_user admin (Clerk do pastor) com user_roles {admin,pastor}, role_permissions default, agent_configs default, whatsapp_connections offline, subscriptions piloto e amostras de dominio.

## Sprint 002 - Backend Core (FastAPI, Clerk Auth, Tenant Resolver, RBAC) [CONCLUIDA]
- App FastAPI e modelos: Criar app/main.py com CORS e mount de routers, app/config.py (settings/env conforme .env.example), app/db/session.py (client Supabase/Postgres) e app/db/models.py com os modelos das tabelas da secao 2.1.
- Auth Clerk + Tenant resolver: app/deps.py com validacao do JWT/sessao Clerk, populando current_user e clerk_user_id, e resolucao de current_igreja_id a partir de app_users injetando no contexto RLS do Postgres.
- RBAC require_role e api-login: Dependency require_role que revalida papeis acumulados (user_roles) por endpoint, e endpoint POST /auth/login retornando {token, churchId}. Config exige admin; login com credencial invalida nao revela existencia de e-mail.

## Sprint 003 - Frontend Foundation + Login + Layout/Sidebar [CONCLUIDA]
- Setup Next.js + tokens visuais: Configurar projeto Next.js (PWA), aplicar tokens de cores oklch, tipografia, espacamento e radii da secao 4.4 como sistema de design global, fiel ao artifact HTML travado.
- Sidebar-nav e roteamento por hash: Implementar sidebar-nav com grupos Gestao, Visao G12 e Configuracao (adminOnly), roteamento por hash (#rota) e montagem do menu pela uniao dos papeis acumulados, usando role_permissions como fonte de verdade.
- Tela de login (Clerk): Tela #login integrada ao Clerk SDK com estados idle/loading/error/success, consumindo api-login, redirecionando para #dashboard em sucesso.

## Sprint 004 - Backend Dominio Pastoral (Pessoas, Celulas, Pipeline, Fila de Trabalho) [CONCLUIDA]
- Contatos e vinculo de celula: Endpoints api-contacts (GET /contacts), api-create-contact (POST /contacts) e api-link-cell (POST /contacts/{id}/cell) sobre pessoas, com dedupe por telefone+igreja e paginacao.
- Celulas, alertas e descendencias: Endpoints api-cells (GET/POST /cells) e api-descendencias (GET /descendencias) usando celulas, cell_alerts e a hierarquia lider_id, com cobertura_espiritual obrigatoria.
- Pipeline (etapa/subetapa): Endpoint api-pipeline (GET/PUT /pipeline) para promover/avancar pessoas conforme state machine, respeitando criterios de promocao.
- Fila de trabalho e mensagem interna: Endpoints api-queue-action (POST /work-queue/{itemId}/action) e api-send-internal-message (POST /work-queue/{itemId}/message), com filtro por papel e tratamento de concorrencia (item ja resolvido).

## Sprint 005 - Backend Consolidacao, Decisoes e Multiplicacoes [CONCLUIDA]
- Lancar decisao e abrir consolidacao: Endpoint api-launch-decision (POST /consolidacao/decisao) que registra decisao e abre consolidacao; fluxo visitante define prazo de conexao de 24h.
- Avanco da trilha com gate por consolidador: Endpoints sobre consolidacoes/consolidacao_etapas (via api-pipeline: assign-consolidador, advance-stage) com confirmacao de etapa apenas pelo responsavel_id.
- Multiplicacoes: Endpoint api-multiplicacoes (GET/POST /multiplicacoes) para agendar e aprovar multiplicacoes, com aprovacao desabilitada quando supervisao_ok=false.

## Sprint 006 - Backend WhatsApp, Conversas, Handoff e Worker [CONCLUIDA]
- Conexao WhatsApp (Evolution API): Endpoint api-whatsapp-connection (GET/POST /whatsapp/connection) e service evolution.py para connect/reconnect retornando QR e status, mantendo 1 numero por igreja.
- Conversas e handoff: Endpoints api-conversations (GET /conversations) e api-conversation-handoff (POST /conversations/{id}/handoff) com estados ia/humano/aguardando e restricao de acesso a privilegiados.
- Webhook de mensagens e worker: Webhook Evolution com validacao de assinatura, dedupe por telefone+igreja, worker de filas (queue_worker) com reprocesso e registro de messages somente do numero oficial.

## Sprint 007 - Agente Orquestrador (LangGraph), LLM BYO e Tools [CONCLUIDA]
- Orquestrador e sub-agentes: Grafo LangGraph (app/agent/graph.py, nodes.py) com Orquestrador supervisor como unico ponto de entrada/saida no WhatsApp oficial (delta-034). Sub-agentes intake/onboarding/report_capture/handoff/consent retornam resultado ao supervisor, que emite resposta unica. Roteamento por intencao/estado (route_intent) com prioridade handoff > optout > consent > report > onboarding. Fallback direto quando o grafo falha; checkpoint via AGENT_GRAPH_CHECKPOINT_URL.
- intake/onboarding/report/consent/optout: intake faz backfill de origem/primeiro_contato; onboarding classifica contato/visitante e coleta dados configuraveis; report_capture extrai presentes/visitantes/decisoes/oferta e emite tool registrar_decisao em decisao por Jesus (abre consolidacao via trigger); consent apresenta termo (delta-040) e grava consent_records com termo_versao+aceite_em, exigindo re-aceite em nova versao; optout grava pessoas.optout=true + consent_record (US-32/RNF-06).
- Credencial LLM BYO: Endpoint POST /agent/credential {provedor,apiKey} -> {status} (app/routers/agent.py), chave validada no provedor, cifrada (Fernet, app/services/crypto.py) e nunca exibida (RNF-03). Chave invalida nao ativa a credencial; runtime recusa operar sem credencial validada+ativa (US-27).
- Tools e logs de IA: app/agent/tools.py (registrar_decisao, marcar_presenca, vincular_celula, avancar_trilha) reaplicam as mesmas validacoes de um humano no escopo do tenant (F5). Cada interacao registra modelo/tokens/custo em ai_usage_logs e evento em agent_conversation_logs com payload mascarado (CPF/email/digitos longos) via app/agent/masking.py (RNF-24). Worker integra o orquestrador (run_agent_for_message) e envia a resposta unica pelo numero oficial.

## Sprint 007 - Agente Orquestrador (LangGraph), LLM BYO e Tools [CONCLUIDA]
- Orquestrador e sub-agentes: Grafo LangGraph com Orquestrador supervisor e sub-agentes intake, onboarding, report_capture, handoff e consent. Sub-agentes nunca falam direto no WhatsApp; resposta unica sai pelo Orquestrador.
- Credencial LLM BYO + tools + logs: Endpoint api-llm-credential (POST /agent/credential) com chave cifrada e validacao, tools do agente (registrar decisao, marcar presenca, vincular celula, avancar trilha) e logs em ai_usage_logs/agent_conversation_logs.

## Sprint 008 - Assistente do Painel e Motor de SLA/Cron [CONCLUIDA]
- Assistente do painel + SLA engine: Endpoint api-assistant (POST /assistant/message) ciente de papel/tenant, e SLA engine + cron_worker que detectam prazos (relatorio 2h, conexao 12h, fonovisita 24h) e disparam cobranca/escalonamento por WhatsApp.

## Sprint 009 - Backend Relatorios, Comunicados, Eventos e Equipe/Config [CONCLUIDA]
- Relatorios, comunicados e eventos: Endpoints api-reports (GET /reports), api-broadcasts (POST /broadcasts) respeitando opt-out, e api-events (GET/POST /events) com sync Google Calendar.
- Equipe, permissoes e gerentes: Endpoints api-team-invite (POST /team/invite via Resend), api-team-roles (PUT /team/{usuarioId}/roles), api-role-perms (GET/PUT /roles/permissions) e api-system-managers (GET/POST/DELETE /system-managers).
- Assinatura (Asaas) e config do agente: Endpoints api-subscription (GET/POST /subscription com webhook Asaas), api-agent-config (PUT /agent/config) e api-crons (POST /agent/crons).

## Sprint 010 - Frontend Dashboard / Fila de Trabalho Pastoral [CONCLUIDA]
- Fila de trabalho e acoes diretas: Renderizar work-queue-item por tipo (visitante/atendimento/relatorio/conectar_celula/fonovisita) com acoes assumir/atribuir e conectar a celula.
- Prazos e stat-cards: Exibir deadline-badge (dentro/alerta/atrasado) reordenando por prioridade e stat-cards de visao geral.

## Sprint 011 - Frontend Contatos & Visitantes (Ganhar) [CONCLUIDA]
- Ganhar (novos contatos e visitantes): Tela #ganhar com tabs novos-contatos/visitantes em data-table, status-pill e empty-state, consumindo api-contacts e api-pipeline.
- Contatos (lista e detalhe): Tela #contatos com lista e detalhe, criacao de contato (form-field/btn-primary) e vinculo de celula.

## Sprint 012 - Frontend Celulas, G12 e Enviar (Discipular/Enviar) [CONCLUIDA]
- Celulas (lista e detalhe): Tela #celulas com data-table, stat-card e tabs; criar/editar celula com cobertura_espiritual obrigatoria.
- G12 (organograma): Tela #g12 com organograma de descendencias consumindo api-descendencias.
- Enviar (multiplicacoes): Tela #enviar com tabs agendadas/sem-agendamento/aptos/historico, agendar e aprovar multiplicacao com gate de supervisao.

## Sprint 013 - Frontend Consolidacao (Consolidar / Individual) e Trilhas Bloqueadas [CONCLUIDA]
- Consolidar (dashboard restrito + decisao): Tela #consolidar com fila, estado 100-consolidadas e decision-modal (fluxo celula/visitante), restrita a lider_consol/admin/pastor.
- Consolidacao individual: Tela #consol-individual com fila e detalhe, avanco de etapas e conclusao com gate por consolidador.
- Trilhas bloqueadas (UV e Capacitacao): Placeholders #universidade-vida e #capacitacao no estado locked-em-breve, presentes no menu mas sem navegar para conteudo.

## Sprint 014 - Frontend Inbox & Conexao WhatsApp [CONCLUIDA]
- Inbox e handoff: Tela #inbox com conversation-list, conversation-thread (ia-active/human/waiting) e acoes assumir/devolver para IA, restrita a privilegiados.
- Conexao WhatsApp (QR): Tela #whatsapp com qr-connect e status-pill nos estados connected/disconnected/reconnecting, consumindo api-whatsapp-connection (admin only).

## Sprint 015 - Frontend Relatorios, Central-Celula, Comunicados e Calendario [CONCLUIDA]
- Relatorios e Central-Celula: Tela #relatorios (data-table, tabs, status-pill, estados received/pending) e #central-celula (lideres + relatorios + comunicar lideres) consumindo api-reports e api-broadcasts.
- Comunicados (segmentado): Tela #comunicados com passos compose/segment/review respeitando opt-out, toggle-switch e data-table de destinatarios.
- Calendario: Tela #calendario com calendar-month, criacao de evento (form-field/btn-primary) e sync Google Calendar.

## Sprint 016 - Frontend Equipe, Permissoes, Gerentes, Assinatura e Agente [CONCLUIDA]
- Equipe, Permissoes e Gerentes: Telas #equipe (list/invite/edit-roles), #permissoes (matrix/saved) e #gerentes (list/invite) consumindo api-team-*, api-role-perms e api-system-managers.
- Assinatura: Tela #assinatura com stat-card, tabs, status-pill nos estados active/past-due/plans, consumindo api-subscription.
- Agente IA: Tela #agente com tabs behavior/credential/crons, toggle-switch e form-field, consumindo api-llm-credential, api-agent-config e api-crons.
