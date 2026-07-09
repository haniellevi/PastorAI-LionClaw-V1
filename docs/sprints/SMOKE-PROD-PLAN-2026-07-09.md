# Plano de smoke funcional autenticado em PROD — 2026-07-09

Plano, não execução. Baseado em `docs/sprints/DEPLOY-HANDOFF-2026-07-09.md` (deploy PASS,
`a7a04c8`, backend + queue-worker) e `docs/ops/PROD-ENV-RUNBOOK.md` (§1b envios reais ligados em prod,
§8 riscos de smoke). Objetivo real do smoke: provar que o fix do PR-A2 (`celula_membro` canônico)
funciona ponta-a-ponta em produção — líder enxerga discípulo vinculado via convite/ativação/link/agente.

## Mapa de efeitos externos (código real, `app/services/outbound_guard.py`)

Em prod, `external_sends_enabled = True` sempre (independe de `ALLOW_REAL_SENDS`) — **qualquer** ação que
bata nesses 5 serviços dispara de verdade:

| Serviço | Dispara em | Router que chama |
|---|---|---|
| WhatsApp (Evolution) | `services/evolution.py` | `broadcasts.py`, `conversations.py`, `whatsapp.py` |
| E-mail (Brevo) | `services/brevo.py` | `team.py` (convite), `auth.py` (reset senha), `platform_admin.py` |
| Cobrança (Asaas) | `services/asaas.py` | `subscription.py` |
| Google Calendar | `services/google_calendar.py` | `calendar.py` (connect/import), possivelmente `events.py` |
| LLM (custo real) | `services/llm.py` | `agent/*`, `api-assistant` |

`link_cell`/`ensure_active_membro`/`deactivate_other_active_membro` (o próprio fix do PR-A2) **não** chama
nenhum desses 5 — é escrita SQL pura + `session.flush()`. Confirmado lendo
`backend/app/services/celula_membro.py` nesta sessão.

## Lista de testes recomendados

### Bloco A — ADMIN (read-only, SAFE)
| # | Teste | Classificação | Efeito externo |
|---|---|---|---|
| A1 | Login Clerk PROD (admin da igreja) | SAFE | nenhum |
| A2 | Dashboard / Painel de Hoje carrega | SAFE | nenhum |
| A3 | Lista de Pessoas/Contatos carrega | SAFE | nenhum |
| A4 | Lista de Células + Central de Célula (dashboard) carrega | SAFE | nenhum |
| A5 | Tela Equipe (lista, sem convidar) carrega | SAFE | nenhum |
| A6 | Tela Assinatura carrega (visualização, sem checkout) | SAFE | nenhum |
| A7 | Tela Agenda/Calendário (lista, sem criar evento) carrega | SAFE | nenhum |

### Bloco B — ADMIN, escrita interna (CAUTION)
| # | Teste | Classificação | Efeito externo |
|---|---|---|---|
| B1 | Criar 1 pessoa de teste (contato novo, telefone fictício claramente marcado) | CAUTION | nenhum (só grava `pessoas`) |
| B2 | Vincular a pessoa de teste a uma célula via `POST /contacts/{id}/cell` (`link_cell`) | CAUTION | **nenhum** — exercita o fix do PR-A2 diretamente |
| B3 | Confirmar no admin que a pessoa aparece com `celula_id` setado | SAFE | nenhum |

### Bloco C — LÍDER DE CÉLULA (read-only, SAFE) — **validação principal do PR-A2**
| # | Teste | Classificação | Efeito externo |
|---|---|---|---|
| C1 | Login Clerk PROD (líder — `celulas.lider_id` aponta pra essa pessoa) | SAFE | nenhum |
| C2 | "Minha Célula" abre, painel do líder carrega | SAFE | nenhum |
| C3 | Lista de discípulos mostra a pessoa de teste do B2 (**PASS/FAIL real do PR-A2**) | SAFE | nenhum |
| C4 | Próxima reunião / avisos / materiais carregam | SAFE | nenhum |

### Bloco D — LÍDER, escrita interna reversível (CAUTION)
| # | Teste | Classificação | Efeito externo | Reversível? |
|---|---|---|---|---|
| D1 | Confirmar própria presença numa reunião real (`POST attendance/confirm`) | CAUTION | nenhum | sim — `DELETE` no mesmo endpoint desfaz |
| D2 | Indicar expectativa de visitante (nominal) | CAUTION | nenhum | não (registro aditivo, baixo impacto) |

### Bloco E — NÃO RODAR sem aprovação explícita, item a item
| # | Teste | Classificação | Efeito externo | Por quê fora do smoke padrão |
|---|---|---|---|---|
| E1 | `POST /team/invite` (convidar membro real) | DO_NOT_RUN_WITHOUT_APPROVAL | **e-mail real (Brevo)** | manda convite de verdade, precisa endereço descartável + revogação depois |
| E2 | Reset de senha (`auth.py` forgot-password) | DO_NOT_RUN_WITHOUT_APPROVAL | **e-mail real (Brevo)** | idem |
| E3 | `POST /events` (criar evento novo) | DO_NOT_RUN_WITHOUT_APPROVAL | **Google Calendar real**, se integrado | `DELETE` do app não remove o espelho no Google (risco de órfão, já documentado no runbook §8) |
| E4 | `POST /calendar/import` ou `/connect` | DO_NOT_RUN_WITHOUT_APPROVAL | **Google Calendar real** | pode alterar conexão OAuth real da igreja |
| E5 | Qualquer ação em `/subscription` que chame Asaas (checkout, mudar plano) | DO_NOT_RUN_WITHOUT_APPROVAL | **cobrança real** | dinheiro de verdade |
| E6 | `POST /broadcasts` (comunicado) | DO_NOT_RUN_WITHOUT_APPROVAL | **WhatsApp real, em massa** | envia pra contatos reais da igreja, sem opt-out testado no smoke |
| E7 | `/whatsapp/connection` (reconectar/QR) | DO_NOT_RUN_WITHOUT_APPROVAL | risco operacional | pode derrubar a conexão WhatsApp real da igreja em produção |
| E8 | `POST /cell-meetings/{id}/report/submit` | DO_NOT_RUN_WITHOUT_APPROVAL | nenhum externo, mas **irreversível** | "após enviado, relatório bloqueado pra edição; sem reabertura no MVP" (SPEC) — corrompe estado real de uma reunião real |
| E9 | Solicitação de campo sensível (`cell-requests`) | CAUTION-alto, avaliar caso a caso | nenhum (notify_* é no-op) | cria ruído real na fila da Central (pessoas de verdade veem) |
| E10 | Assistente do painel (`api-assistant`) | CAUTION-baixo | **custo real de LLM** | pequeno, mas gasto real de token |

## Ordem segura recomendada

1. Bloco A (admin, todo read-only) — confirma ambiente básico saudável.
2. Bloco C (líder, todo read-only) — confirma acesso do papel líder funciona.
3. Bloco B (admin cria + vincula pessoa de teste) — só depois de A/C passarem.
4. Repetir C3 (líder revê a lista de discípulos) — **este é o teste que decide PASS/FAIL do PR-A2**.
5. Bloco D (opcional, só se quiser testar escrita reversível do líder) — D1 primeiro (reversível),
   avaliar D2 à parte.
6. Bloco E — **não entra no smoke padrão**. Só rodar item a item, com aprovação explícita, sabendo o
   efeito externo de cada um.
7. Cleanup: desativar/remover a pessoa de teste do Bloco B (ou marcar claramente como teste permanente,
   se preferir manter como fixture).

## Dados necessários

- Usuário Clerk **de produção** com papel admin de uma igreja real (≠ instância dev `lenient-bat-59`).
- Usuário Clerk de produção com papel líder, cuja pessoa está em `celulas.lider_id` de uma célula real.
- 1 telefone fictício claramente marcado (ex.: prefixo `+55XX9999-SMOKE` ou similar) pra pessoa de teste
  do Bloco B — evita confundir com contato real.
- Acesso a `docker compose logs` (backend/queue-worker) durante a janela do smoke, pra cruzar com o que
  foi clicado.

## Riscos

- **Poluição de dado real**: Bloco B cria 1 pessoa real em produção — precisa decisão de cleanup (deletar
  ou manter como fixture rotulada).
- **Efeito externo não intencional**: qualquer clique fora do roteiro (ex.: um botão de "reenviar
  convite" sendo clicado sem querer) dispara Brevo/Evolution/Asaas de verdade — não há guard de
  ambiente em prod.
- **Órfão no Google Calendar**: se alguém tocar Bloco E3/E4 sem querer, limpeza é manual do lado do
  Google (app não desfaz).
- **Report irreversível**: Bloco E8 trava a reunião de verdade — maior risco de dado corrompido do plano
  inteiro, por isso isolado.
- **LLM custo real**: qualquer interação com o agente/assistente em prod gasta token de verdade
  (pequeno, mas real).

## Critério de PASS / FAIL

- **PASS do smoke como um todo**: A1-A7 e C1-C4 sem erro; B1-B3 gravam sem erro; **C3 reexecutado depois
  do B2 mostra a pessoa de teste na lista de discípulos do líder** (prova direta e end-to-end de que o
  fix do PR-A2 está ativo em produção — os 4 write-sites gravando `celula_membro` corretamente e a
  leitura do líder, que sempre leu `celula_membro`, agora enxerga).
- **FAIL**: qualquer erro 5xx em A/B/C; ou C3 **não** mostrar a pessoa de teste depois do B2 (significaria
  que o deploy não pegou o fix, ou o backfill/gravação ainda diverge — regressão grave, acionar rollback
  do handoff).
- Blocos D e E não entram no critério de PASS/FAIL do smoke principal — são extensões opcionais,
  avaliadas à parte se rodadas.

## Status

**Plano criado, nada executado.** Aguardando autorização pra rodar Bloco A → C → B → C (reexecução) —
essa sequência mínima já prova o PR-A2 ponta-a-ponta com risco de efeito externo **zero**.
