# SPEC_PROGRESS - PastorAi-1.0

## Status: 8/8 sprints concluidas
Ultima atualizacao: 2026-07-06T05:24:22.084Z

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

## Sprint 001 - Schema, Migration e Modelos SQLAlchemy (fundacao) [CONCLUIDA]
- Migration aditiva com 3 tabelas, FKs CASCADE, indexes e constraints: Novo arquivo SQL em backend/migrations/ com timestamp AAAAMMDD_HHMMSS_celula_pr2_reuniao_presenca_expectativa.sql que cria as 3 tabelas conforme a secao 2.1 da SPEC, sem tocar em tabelas existentes do PR1.
- RLS enable + policy tenant_isolation nas 3 tabelas: Na mesma migration, habilitar RLS e criar a policy tenant_isolation em cada uma das 3 tabelas novas, no padrao identico ao PR1 (20260703_123803_celula_schema_base_pr1.sql) e ao agenda_alert_recipients.
- Modelos SQLAlchemy CelulaReuniao, CelulaPresenca, CelulaExpectativaVisitante: Adicionar em backend/app/db/models.py os 3 modelos correspondentes, no estilo de Celula/CelulaMembro (mapped_column, server_default, timestamps).
- Testes de modelo/schema (test_celulas_pr2_models.py): Novo arquivo backend/tests/test_celulas_pr2_models.py cobrindo a estrutura dos modelos e da migration (colunas, unicidades, indexes, CHECKs, policies), no estilo dos testes existentes.

## Sprint 002 - Servico de calculo da proxima reuniao + endpoints de Reuniao [CONCLUIDA]
- Servico de calculo da proxima reuniao (domain/cell_meetings_schedule.py): Novo modulo backend/app/domain/cell_meetings_schedule.py com o parser PT-BR de dia_reuniao e o calculo da proxima data, com helper de relogio/data-base injetavel para testes deterministicos.
- Router cell_meetings.py + constantes + registro em main.py: Novo router backend/app/routers/cell_meetings.py que importa e reusa helpers de cells.py, define as constantes string de status/estado/origem e e incluido em main.py via include_router.
- GET /cells/{cellId}/reunioes (listar reunioes): Endpoint que lista as reunioes de uma celula escopadas ao tenant, sem paginacao, com ordenacao determinista.
- POST /cells/{cellId}/reunioes/next (materializar proxima reuniao, idempotente): Endpoint que materializa a proxima reuniao a partir de celulas.dia_reuniao/horario, criando em status planejada se nao existir ou retornando a existente, sempre 200.
- Testes dos endpoints de reuniao e do servico de calculo (US-01..US-04): Novo arquivo backend/tests/test_cell_meetings.py cobrindo o servico de calculo e os dois endpoints de reuniao.

## Sprint 003 - Endpoint de Presenca idempotente (propria e por lider) [CONCLUIDA]
- Helper _get_reuniao_or_404 + schema PresencaOut: Novo helper em cell_meetings.py que resolve a reuniao por id escopada ao tenant (nao exige cellId no path) e schema Pydantic PresencaOut em camelCase.
- POST /cell-reunioes/{reuniaoId}/presenca (auto + terceiro, upsert idempotente): Endpoint que confirma a propria presenca (sem pessoaId) ou marca terceiro (com pessoaId, exige lideranca), com upsert idempotente e checagem de vinculo ativo na celula da reuniao.
- Testes de presenca (US-05..US-08): Amplia backend/tests/test_cell_meetings.py com os cenarios de presenca.

## Sprint 004 - Endpoint de Expectativa de Visitante (nominal) [CONCLUIDA]
- Schemas Pydantic de expectativa (in/out) com validacao de borda: Schema de entrada com validacao de nomeVisitante/observacaoOracao e schema de saida ExpectativaVisitanteOut em camelCase.
- POST /cell-reunioes/{reuniaoId}/expectativas-visitantes (201 CREATED): Endpoint que registra a expectativa sempre da propria pessoa, permitindo N registros por membro/reuniao, sem efeitos externos.
- Testes de expectativa (US-09, US-10): Amplia backend/tests/test_cell_meetings.py com os cenarios de expectativa.

## Sprint 002 - Backend: auth + Minha Celula (Discipulo) [CONCLUIDA]
- Dependencies de autorizacao (deps/auth.py): Estender deps/auth.py com require_role(role), require_central() e get_current_cell_for_leader(). igreja_id e papel derivam sempre do contexto Clerk autenticado (nunca do payload). 'E lider desta celula' deriva de celulas.lider_id ligado a Pessoa do usuario (E9/6.6), nao de flag do cliente nem de celula_membro.papel. Setar set_tenant_context/current_igreja_id() por request.
- Endpoints do Discipulo: GET /api/cells/me/next-meeting, GET /api/cells/me/notices, GET /api/cells/me/history (paginado, projecao minimizada), POST e DELETE /api/cell-meetings/{id}/attendance/confirm, POST /api/cell-meetings/{id}/visitor-expectations. Reusar celula_expectativa_visitante (PR2) e celula_presenca (PR2). Mapear minha_presenca conforme E5 (compareceu->participou, ausente->faltou, confirmada->confirmou, sem linha->nao_confirmou). Fuso America/Sao_Paulo para 'passada'/'futura' (E4).

## Sprint 003 - Backend: Minha Celula (Lider) + Ciclo do relatorio [CONCLUIDA]
- Endpoints do Lider - reuniao, presenca, visitantes, registros: POST /api/cell-meetings (planejar reuniao pontual, relatorio_status nasce 'pendente'), PUT /api/cell-meetings/{id} (editar data/hora/tema; rejeitar campos sensiveis - RF-14), PUT /api/cell-meetings/{id}/attendance (presenca real em celula_presenca), POST /api/cell-meetings/{id}/visitors (celula_visitante, com expectativa_id opcional), GET /api/cell-meetings/{id}/visitor-expectations, POST e GET /api/cell-meetings/{id}/records (celula_reuniao_registro), GET /api/cells/{cell_id}/members (reusar cells.py). Todos restritos a propria celula (get_current_cell_for_leader).
- Ciclo do relatorio (draft, submit, consolidado): PUT /api/cell-meetings/{id}/report (grava oferta_valor e observacoes sem enviar), POST /api/cell-meetings/{id}/report/submit (consolida e muda relatorio_status para 'enviado', grava relatorio_enviado_em/por), GET /api/cell-meetings/{id}/report (consolidado: presencas, visitantes, records, oferta, observacoes, status). Validacoes E1/E2: oferta_valor >=0 e <=999999.99, observacoes <=2000. Regras E10/E11: apos enviado, relatorio bloqueado para edicao; sem reabertura no MVP.

## Sprint 004 - Backend: Solicitacoes de campo sensivel e Multiplicacao transacional [CONCLUIDA]
- Schemas discriminados por tipo e criacao com conflito: Schemas Pydantic de payload_proposto discriminados por tipo (alterar_dia/horario/endereco/anfitriao/auxiliar, transferir_membro, remover_membro, multiplicacao) conforme contratos da 6.3. POST /api/cell-requests: nasce 'aguardando', NAO altera dado real, gera evento 'criada' na mesma transacao, retorna 409 se ja existir solicitacao aberta conflitante (matriz E13/6.8). GET /api/cell-requests (lider ve as suas, Central ve da igreja, filtro por status). GET /api/cell-requests/{id} (detalhe + trilha de eventos).
- Decisao da Central e reenvio/cancelamento: cell_requests_service.py com aprovar/rejeitar/pedir ajuste/reenviar/cancelar. POST approve (Central, sem editar payload; aplica payload por tipo em transacao unica com auditoria 'aprovada'). POST reject e request-adjustment (observacao_central obrigatoria -> 422 se ausente; eventos 'rejeitada'/'ajuste_solicitado'). PUT resubmit (lider autor, so em ajuste_solicitado, evento 'reenviada'). POST cancel (lider autor, so em aguardando/ajuste_solicitado, evento 'cancelada', E12). Cada acao grava evento append-only na mesma transacao; falha parcial -> rollback total.
- Multiplicacao transacional e idempotente: cell_multiplication_service.py acionado por approve quando tipo='multiplicacao'. Exige idempotency_key. Em transacao unica: valida payload (6.3: novo_lider_id membro ativo da origem e presente em membros_transferidos_ids; minimo 1 membro), cria nova celulas com lider_id=novo_lider_id, desativa vinculos celula_membro antigos e cria vinculos ativos na nova celula, sincroniza pessoas.celula_id (espelho legado), grava multiplicacoes com solicitacao_id (UNIQUE), celula_id=origem e celula_nova_id=nova, registra auditoria. Reprocessar mesma aprovacao/idempotency_key nao duplica (RNF-06/07). GET /api/multiplicacoes lista pendentes (solicitacoes tipo multiplicacao aguardando) e registradas.

## Sprint 005 - Backend: Central (dashboard, fila, saude), Avisos e Materiais [CONCLUIDA]
- Avisos (cell_notices.py) e ponto de extensao de notificacao: POST /api/cell-notices (lider: origem='celula', escopo='celula' obrigatorio, so a propria celula; Central: origem='central', escopo celula ou igreja; regra de autoria validada no servidor), GET /api/cell-notices (alcance E15: escopo=igreja para todo usuario autenticado da igreja; escopo=celula para membros ativos+lider+Central; paginado), DELETE /api/cell-notices/{id} (inativa ativo=false por autor compativel). Tambem GET /api/cells/me/notices ja existente no dominio discipulo. cell_notify.py com funcoes notify_* no-op que apenas persistem intencao/estado (celula_aviso.notificado_em), sem chamada externa.
- Materiais (cell_materials.py): POST /api/cell-materials (Central; url obrigatoria iniciando com http://|https://, titulo<=120, descricao<=2000, url<=2048 - E2/6.1), GET /api/cell-materials (materiais ativos da igreja; lider e discipulo visualizam somente leitura - E14; paginado), DELETE /api/cell-materials/{id} (Central inativa ativo=false). Sem upload real de arquivo.
- Central: dashboard, fila de relatorios e saude (cell_central.py + cell_health_service.py): GET /api/cell-central/dashboard (contadores E16, nao paginado), GET /api/cell-central/pending-reports (reunioes passadas nao canceladas com relatorio_status='pendente', com celula_nome e lider_nome derivado de celulas.lider_id - 6.6; paginado), GET /api/cell-central/health (cell_health_service calcula on-read sobre ultimas 10 reunioes com 3 sinais e regras E6; ordena menos saudaveis primeiro). Fuso America/Sao_Paulo para 'passada'. Todos restritos a Central (require_central).

## Sprint 006 - Frontend: camada de API e Minha Celula (Discipulo) [CONCLUIDA]
- Camada de API tipada (*-api.ts): Criar/estender frontend/src/lib: cells-api.ts (getNextMeeting, getMyHistory, getCellMembers), cell-meetings-api.ts (planMeeting, updateMeeting, confirmAttendance, revertAttendance, setRealAttendance, indicateVisitor, getVisitorExpectations, registerVisitor, addRecord, getRecords, saveReport, submitReport, getReport), cell-notices-api.ts, cell-materials-api.ts, cell-requests-api.ts, cell-central-api.ts, multiplicacoes-api.ts (estender). fetch nativo, tipos TS espelhando snake_case do backend, erros ApiError/SessionExpiredError. Sem React Query/SWR/Zustand/Redux.
- Entrada por papel e visao Discipulo: MinhaCelulaEntry decide visao por papel autenticado (lider->Lider, so membro->Discipulo, sem alternador de demo). Disciple: NextMeetingCard (US-01 com empty), ConfirmAttendanceButton (US-02, 1 toque, otimista com rollback, desabilitado sem reuniao), IndicateVisitorModal (US-03, desabilita sem reuniao), NoticesFeed (US-04, celula=azul/central=vermelho), MaterialsFeed (US-21/E14 leitura), MeetingHistoryList (US-05). Reusar components/ui/ e primitivos. Copy pt-BR de E17.

## Sprint 007 - Frontend: Minha Celula (Lider) [CONCLUIDA]
- Painel, planejamento e relatorio da reuniao: LeaderPanel, PlanMeetingModal (US-06, data/hora/tema da reuniao pontual, nao altera padrao), MeetingReportForm em secoes/cards (nao wizard): AttendanceSection (US-07), VisitorsSection (US-08, registrar + confirmar esperados), RecordsSection (US-09), OfferingSection (US-10), SubmitReportButton (US-11, loading no botao, aguarda servidor). Toasts E17. Apos enviado, relatorio bloqueado.
- Discipulos, avisos da celula e solicitacoes: DisciplesList (US-12), CellNoticeForm (US-12A, aviso so da propria celula, azul) + LeaderNoticesFeed (US-12B, celula azul + central vermelho), SensitiveFieldRequestModal (US-13, abre fluxo de solicitacao, NAO salvar direto) + MyRequestsList (US-14: status + observacao_central; reenviar em ajuste_solicitado; cancelar em aguardando/ajuste_solicitado - E12). Materiais em leitura via MaterialsFeed reusado. Copy E17.

## Sprint 008 - Frontend: Central de Celulas (Jornada G12 > Discipular) [CONCLUIDA]
- Shell da Central e Dashboard/Gerenciar celulas: CentralTabs (Dashboard, Gerenciar celulas, Solicitacoes, Avisos, Materiais; abas roláveis) dentro de Jornada G12 > Discipular > Central de Celula, so para pastor/admin, nunca dentro de Minha Celula. Dashboard/WorkQueuePanel (US-22, cards + WorkQueueItem). ManageCells: CellHealthList (US-18, 10 bolinhas verde/vermelho/alerta, menos saudaveis primeiro), PendingReportsList (US-16, celula/lider/reuniao), MultiplicationsList (US-19, pendentes/registradas).
- Solicitacoes, Avisos e Materiais da Central: Requests: RequestsQueue (US-17, fila aguardando, master-detail no desktop) + RequestDecisionPanel (US-15, aprovar/rejeitar/pedir ajuste; observacao_central obrigatoria ao rejeitar/pedir ajuste; Central NAO edita payload). Notices/CentralNoticeForm (US-20, celula especifica ou igreja inteira, vermelho). Materials/MaterialsManager (US-21, publicar url obrigatoria + listar + inativar). Loading no botao nas acoes; toasts E17.
