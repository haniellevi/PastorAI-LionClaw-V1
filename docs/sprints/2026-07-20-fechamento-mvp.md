# Fechamento do MVP — Igreja 12 (PastorAI 1.0) — Veredito 2026-07-20 (M10)

**Data-base:** 2026-07-20
**Commit auditado:** `37e4cd3` (`origin/main`, pós PR#195 / UNIQ-PESSOA-1)
**PRD usado como checklist:** `docs/Docs20260611_163530/PRD20260611_163530.md` — é o PRD
consolidado (RF-01..49, US-01..43, RNF-01..25) e a **fonte de verdade de produto**
apontada por `PRODUCT.md`. Os PRDs em `Docs20260704_*` são recortes posteriores menos
completos; este é o abrangente.
**Fontes cruzadas:** `SPEC_PROGRESS.md`, `docs/audits/2026-07-18-project-source-of-truth.md`,
`docs/decisions/2026-07-18-decisoes-fechamento-mvp.md`,
`docs/security/2026-07-18-sec-baixo-revalidacao.md`, `docs/sprints/*`, e o código em
`backend/app/routers/`, `backend/app/agent/`, `frontend/src/`.

---

## (a) Sumário executivo (linguagem leiga)

O Igreja 12 está pronto para uso: tudo o que o PRD do MVP pediu já está no ar em
produção. O WhatsApp da igreja é atendido por IA que cadastra e encaminha pessoas; o
painel mostra a fila de pendências do dia; a jornada G12 (Ganhar, Consolidar, Discipular,
Enviar) funciona ponta a ponta; células, relatórios por WhatsApp, agenda, comunicados,
equipe/permissões, assinatura e onboarding de igreja estão implementados e deployados.
Nesta rodada final ainda entraram dedupe de contato por igreja, unificação da emissão de
tokens, unicidade de telefone por igreja e a migração dos diálogos para o design system.
Sobraram apenas **4 pequenos refinamentos aprovados pelo dono** (não são requisitos
originais do PRD) já preparados para um próximo pipeline "FECH-2", mais os itens que sempre
foram declarados fora do MVP. **Nenhum requisito do PRD ficou descoberto.**

---

## (b) PRD × status × evidência

Legenda: **Prod** = concluído e deployado em produção · **Prod (sem smoke ver.)** =
deployado mas sem smoke autenticado versionado (confirmação operacional do dono) ·
**Pós-MVP** = declarado fora do MVP ou decisão do dono para FECH-2.

### Autenticação e Multi-tenant (US-01..04 / RF-01..05, D1, D2, D7)
| Item | Status | Evidência |
|---|---|---|
| Login Clerk (RF-01) | Prod | `backend/app/routers/auth.py`; `frontend` #login (Sprint 003) |
| Isolamento RLS por tenant (RF-02, RNF-02/21) | Prod | seam tenant-context C1 (4 PRs, 2026-07-08); `backend/app/db/tenant_session.py` |
| Convite/gestão de usuários (RF-03/04) | Prod | `backend/app/routers/team.py`; Brevo `services/brevo.py` (Sprint 009/016) |
| RBAC por papéis acumulados + backend (RF-05, D1, D7) | Prod | `routers/roles.py`, `deps.py`; ALTO-003 `CENTRAL_ROLES` fonte única (PR#181, `70846d2`) |
| Emissão unificada de JWT de propósito (MEDIO-005) | Prod | `_mint_purpose_token` (commit `1419e97`, `b5b990d`) |

### Conexão WhatsApp (US-05..07 / RF-06..09)
| Item | Status | Evidência |
|---|---|---|
| Conectar QR + estados + reconexão + só nº oficial | Prod | `routers/whatsapp.py`, `services/evolution.py`; #whatsapp (Sprint 014) |

### Atendimento por IA / Agente (US-08..14, 27..29, 41 / RF-10..17, 30..33, 47)
| Item | Status | Evidência |
|---|---|---|
| Orquestrador LangGraph + sub-agentes (RF-10/11/13) | Prod | `backend/app/agent/graph.py`, `nodes.py`, `runtime.py` (Sprint 007) |
| Contato criado/atualizado + dedupe por igreja (RF-12) | Prod | `routers/contacts.py`, `services/pessoa_dedup.py`; MEDIO-004 filtro `igreja_id` (`ce14ee0`, `b5b990d`) |
| Inbox + histórico + handoff IA/humano (RF-14..17) | Prod | `routers/conversations.py`; #inbox (Sprint 014) |
| Credencial LLM BYO cifrada (RF-30/31) | Prod | `routers/agent.py`, `services/crypto.py` (Fernet) |
| Config/comportamento + crons do agente (RF-32/33) | Prod | `routers/agent.py`; governança master via `agent_config_requests` (delta-043/048) |
| Assistente do painel (RF-47) | Prod | `routers/assistant.py`, `services/assistant.py` (Sprint 008) |
| Isolamento do worker assíncrono (delta-045) | Prod | PR3-B seam RLS worker (`queue_worker`), 2026-07-08 |
| Autorização por interlocutor no WhatsApp (delta-046) | Prod | `PrivilegeContext` no roteamento/tools (Fase 2 #10b) |
| Dedupe inbound idempotente (MSG-IDEMP-1) | Prod | PR#176, release `82e1c6f`, migration em PROD |
| Fallback determinístico se OpenAI falha (Decisão 2) | Prod | `agent/runtime.py:313-330` — mantido como está por decisão do dono |

### Painel / Fila de Trabalho (US-15..17 / RF-18..20)
| Item | Status | Evidência |
|---|---|---|
| Dashboard de pendências + ações diretas + por responsável | Prod | `routers/dashboard.py`, `work_queue.py`; #dashboard (Sprint 010) |

### Ganhar — Visitantes e Contatos (US-09/10/18/19/20 / RF-21..23)
| Item | Status | Evidência |
|---|---|---|
| Lista de visitantes, detalhe, vincular célula | Prod | `routers/contacts.py`, `pipeline.py`; #ganhar (Sprint 011); W2 visual (PR#173) |
| Pausa da IA em "sem interesse"/CSIM (CONV-AI-1) | Prod | PR#170 (2026-07-14) |
| Unicidade de telefone por igreja (UNIQ-PESSOA-1) | Prod | índice único parcial + guarda de corrida (`b4c5f3a`, PR#195) |

### Consolidar (US-37..40 / RF-43..46)
| Item | Status | Evidência |
|---|---|---|
| Lançar decisão + abrir consolidação + dashboard restrito + etapas + pendências 24h | Prod | `routers/consolidacao.py`; #consolidar/#consol-individual (Sprint 013) |
| Consolidação aberta única por pessoa (CONSOL-1) | Prod | PR#179, release `82e1c6f`, migration em PROD |

### Discipular — Células e Central (US-21..26 / RF-24..29)
| Item | Status | Evidência |
|---|---|---|
| CRUD células + membros/visitantes + alertas (RF-24..26) | Prod | `routers/cells.py`, `cell_central.py` (Células PR1..PR9 em prod) |
| Relatório de célula via WhatsApp + painel + pendência (RF-27..29) | Prod | `routers/reports.py`, `cell_meetings.py`; captura texto/áudio (delta-041) |
| Minha Célula (discípulo/líder) + solicitações sensíveis (TOCTOU) | Prod | `cell_discipulo.py`, `cell_requests.py`; SEC-4B (PR#156..159) |

### Enviar — Multiplicações (US-21..23)
| Item | Status | Evidência |
|---|---|---|
| Multiplicação transacional/idempotente + aptos + aprovação + histórico | Prod | `routers/multiplicacoes.py`, `services/cell_multiplication_service.py`; #enviar (Sprint 012) |
| Capacidade `pode_transferir` (D2) | Prod | PR#160 (`9121abb`) |

### Pessoas (modelo unificado F6/F1)
| Item | Status | Evidência |
|---|---|---|
| Pessoa como estados (Conhecendo→Líder) + arquivamento seguro | Prod | `services/pessoa_offboarding_service.py`; W3.2A/B (PR#163 backend, PR#169 frontend) |

### Agenda e Eventos (US-30 / RF-34/35, deltas 049..051)
| Item | Status | Evidência |
|---|---|---|
| Agenda 5 abas (Semana/Mês/Ano/A confirmar/Planejamento) MVP = EVT-1..5 manual | Prod | `routers/events.py`, `calendar.py`; #calendario (Sprint 015); promoção EVT MVP (2026-06-30) |
| Lembretes EVT-7 (envio real) | Prod (flag OFF) | outbound guard mantido; `services/event_notify.py` |

### Comunicados, Consentimento e Opt-out (US-31..33 / RF-36..38)
| Item | Status | Evidência |
|---|---|---|
| Consentimento automático + opt-out + comunicado segmentado | Prod | `routers/broadcasts.py`; consent node (Sprint 007/015); opt-out persistido (delta-047) |

### Monetização e Assinatura (US-34..36 / RF-39..42)
| Item | Status | Evidência |
|---|---|---|
| 3 planos por porte + checkout Asaas + setup fee + status + autoupgrade | Prod (sem smoke ver.) | `routers/subscription.py`, `services/asaas.py`; #assinatura (Sprint 016). Autoupgrade por porte presente; smoke de cobrança real não versionado |

### Onboarding de Igreja
| Item | Status | Evidência |
|---|---|---|
| Provisionamento/onboarding da igreja | Prod | `routers/church.py`, `setup.py` (Missão 5, MERGED+deployado) |

### Admin/Equipe (US-03/04, D1/D2 / RF-D1/D2)
| Item | Status | Evidência |
|---|---|---|
| Equipe, Permissões (matriz papel×tela), Gerentes | Prod | `routers/team.py`, `roles.py`; #equipe/#permissoes/#gerentes (Sprint 016) |

### Design System / Visual
| Item | Status | Evidência |
|---|---|---|
| Redesign Fable F0 + migração de diálogos p/ `ds/Dialog` (W2..W5A) | Prod | PRs #161/164..168, #173/174/183/184; W5A (`ce27f4d`, `b5b990d`) |

---

## (c) Explicitamente pós-MVP (não reabrir)

**Já declarados fora do MVP no PRD (Escopo Negativo §7):**
- Console Super-Admin operacional (US-42/43) — só stubs de rastreabilidade; Onda 1 backend
  existe (`routers/platform_admin.py`), superfície própria fica para o pós-MVP.
- Universidade da Vida e Capacitação Destino — telas bloqueadas (`locked-em-breve`).
- App nativo iOS/Android (RNF-19) — coberto por PWA.
- RBAC hierárquico G12 completo além dos papéis ativos.
- Portal do Membro; trilhas de formação completas; aba de gestão avançada de célula
  (materiais/planner/metas) e agente dedicado à célula.
- Ministérios e árvore ministerial configurável.
- Provedores LLM além de OpenAI (multi-LLM).
- Formalização LGPD completa além de consentimento/opt-out/máscara.
- Google Calendar: **import** real (Google→app "a confirmar") = EVT-6, começa pelo fix do
  token por igreja (delta-050); envio real de notificação = EVT-9.

**Decisões do dono (2026-07-18) preparadas para o pipeline FECH-2 — ainda NÃO implementadas:**
- **OPTIN-1** — botão admin "Reativar comunicações" (re-opt-in com novo consentimento). Não é
  RF do PRD (US-32 só cobre opt-out; re-opt-in era manual/follow-up por delta-047).
- **REATIVAR-1** — botão admin "Reativar pessoa" (desarquivar; campos já existem).
- **ROTULO-1** — renomear rótulo visível "Sem interesse (CSIM)" → "Fora da igreja"
  (frontend, ~10 strings; valor técnico interno inalterado).
- **AGENDA-ORD-1** — aba "A confirmar" ordenada por data (frontend trivial).

**Segurança pós-MVP (com gate conhecido):**
- BAIXO-002 (FORCE RLS ausente) e BAIXO-010 (JWT em localStorage) — risco conhecido
  aceito pós-MVP (`docs/security/2026-07-18-sec-baixo-revalidacao.md`).
- Fichas candidatas F1 (helper HTTP client Clerk) e F2 (`func.count` em `list_events`) —
  melhorias, não bloqueiam o MVP.

---

## (d) VEREDITO

**MVP do PRD concluído e em produção.** Os 49 requisitos funcionais (RF-01..49), as 43
user stories (US-01..43) e os deltas aprovados estão implementados e deployados em
`origin/main`=`37e4cd3`. **Nenhum requisito do PRD ficou descoberto** — não há ficha de
missão nova a abrir por lacuna do MVP.

Ressalvas (evidência, não funcionalidade):
1. **Smoke autenticado versionado incompleto.** Só o release `b5b990d` tem smoke
   autenticado PASS documentado (`2026-07-18-smoke-autenticado-release-b5b990d.md`).
   Vários deploys de frontend e o fluxo de billing (cobrança real Asaas) foram confirmados
   operacionalmente pelo dono, mas sem smoke versionado. Recomendação: sprint de evidência
   retroativa (não altera código).
2. **4 refinamentos aprovados pelo dono pendentes** (OPTIN-1, REATIVAR-1, ROTULO-1,
   AGENDA-ORD-1) — melhorias de fechamento, não requisitos originais do PRD, já prontas para
   o pipeline FECH-2.

Formulação alternativa honesta: se o dono considerar as 4 decisões como parte do MVP-close,
então **o MVP está a 4 itens (todos P, código puro, sem migration) de concluído** — e são
exatamente OPTIN-1, REATIVAR-1, ROTULO-1 e AGENDA-ORD-1.

---

## Tabela-resumo por área

| Área | Status |
|---|---|
| Ganhar | Prod (concluído) |
| Consolidar | Prod (concluído) |
| Discipular (Central/Células) | Prod (concluído) |
| Enviar (Multiplicações) | Prod (concluído) |
| Pessoas | Prod (concluído) |
| Comunicação | Prod (concluído) — refino ROTULO-1/OPTIN-1 = FECH-2 |
| Agenda | Prod (MVP EVT-1..5) — AGENDA-ORD-1 = FECH-2; import/EVT-9 = pós-MVP |
| Conversas/IA | Prod (concluído) |
| Células | Prod (concluído) |
| Admin/Equipe | Prod (concluído) |
| Billing | Prod, sem smoke autenticado versionado |
| Onboarding | Prod (concluído) |
