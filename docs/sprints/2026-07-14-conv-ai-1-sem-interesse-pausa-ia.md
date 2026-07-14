# CONV-AI-1 — "Sem interesse" pausa a IA de forma canônica — 2026-07-14

**Branch:** `claude/pastor-ai-sem-interesse-pause-3f5795`  ·  **Base:** `origin/main` `6c7d213`  ·  **Deploy:** não (PR draft; sem migration/PROD)

## Contrato
Todo contato/conversa marcado `sem_interesse` fica fora do atendimento automático
por IA. A UI nunca exibe simultaneamente "Sem interesse" e "IA ativa"; reflete
"IA pausada" e não oferece a ação enganosa "Assumir (pausar IA)".

## O que foi feito
- **Backend já era canônico (nada alterado no runtime):** o worker
  `process_inbound_message` ([backend/app/agent/runtime.py:377](backend/app/agent/runtime.py))
  suprime a auto-resposta em `pessoa.sem_interesse` **antes** de avaliar
  credencial BYO / `AgentConfig.ativo` / estado da conversa. O gate precede o
  handoff (`estado`), então **registro legado** (`sem_interesse=True` com
  conversa ainda `estado="ia"`) já era bloqueado. O boundary de envio
  `run_agent_for_message` ([backend/app/workers/queue_worker.py:459](backend/app/workers/queue_worker.py))
  retorna cedo em `result.suppressed` — nada sai pela Evolution.
- **Testes backend novos** ([backend/tests/test_agent_hygiene.py](backend/tests/test_agent_hygiene.py)):
  1. `test_sem_interesse_legado_suprime_antes_de_avaliar_credencial` — sessão que
     **explode se a credencial/config for lida**, provando que o gate
     `sem_interesse` retorna antes (legado `estado="ia"`).
  2. `test_worker_nao_envia_auto_resposta_para_sem_interesse` — `run_agent_for_message`
     end-to-end com Evolution espiã: **nenhum `send_text`** para contato sem interesse.
- **Frontend — coerência de UI** (reflete a verdade do backend, sem regra nova):
  - `iaPausadaSemInteresse(c)` + `conversationPill(c)` em
    [frontend/src/components/inbox/conversation-format.ts](frontend/src/components/inbox/conversation-format.ts):
    `semInteresse` ⇒ pílula "IA pausada" (tom `muted`); humano assumido continua "Em atendimento".
  - [frontend/src/components/inbox/ConversationThread.tsx](frontend/src/components/inbox/ConversationThread.tsx):
    pílula via `conversationPill`; banner "IA pausada (sem interesse)"; botão
    "Assumir (pausar IA)" vira **"Assumir atendimento"** quando pausado (mantém o
    handoff — humano ainda assume para responder). Simétrico (achado da revisão):
    para contato sem interesse já sob humano, "Devolver para a IA" vira
    **"Encerrar atendimento"** e o toast em
    [InboxScreen.tsx:306](frontend/src/components/inbox/InboxScreen.tsx) reflete
    "Atendimento encerrado. A IA segue pausada." — não promete reativar uma IA
    que o worker mantém suprimida.
  - Testes: [conversation-format.test.ts](frontend/src/components/inbox/conversation-format.test.ts) (derivação pura)
    e [ConversationThread.test.ts](frontend/src/components/inbox/ConversationThread.test.ts) (render: normal vs sem interesse).

## Decisões
- **Sem coluna nova nem regra só-de-frontend.** O enforcement canônico já vive no
  worker; a UI apenas reflete o flag `sem_interesse` já exposto pela API
  (`ConversationOut.semInteresse`). Adicionar campo `iaPausada` seria duplicação.
- **Prioridade da pílula:** humano > sem_interesse ("IA pausada") > aguardando > ia.
  Um humano que assumiu tem estado próprio ("Em atendimento"), sem conflito.
- **"Devolver para a IA" relabelado para "Encerrar atendimento"** na conversa sem
  interesse já sob humano: ao encerrar, o estado volta a `ia`, mas a IA segue
  suprimida no backend (o release não toca `pessoa.sem_interesse`), então o rótulo
  NÃO promete devolver para uma IA que não responde e a UI mostra "IA pausada".
- **Reconciliação em massa NÃO feita** (contrato): nenhum backfill em DEV/PROD.
- **Filtro "IA" da lista NÃO alterado** (achado nit da revisão, fora de escopo):
  um contato sem interesse ocioso tem `estado="ia"` e cai no balde "IA" do filtro.
  A linha da lista já mostra o marcador "Sem interesse" (nenhum texto "IA ativa"),
  então não viola o contrato; mudar a semântica do filtro seria alteração de
  comportamento do fluxo normal. Fica registrado como possível melhoria futura.

## Revisão adversarial (3 lentes: correção / coerência / escopo)
- 0 blocker/major. 2 achados confirmados, ambos cosméticos: (1) o gêmeo
  "Devolver para a IA" — **corrigido**; (2) o balde "IA" do filtro — **não
  alterado** (nit, fora de escopo). 0 achados refutados pendentes.

## Pendente / próximo passo
- Smoke visual autenticado no inbox (dono) — BLOCKED sem sessão nesta conversa.
- Deploy: não faz parte da missão (sem migration; mudança backend é só de teste).

## Verificação
- Backend: `pytest` verde — sweep agent/worker/conversation/classification/csim
  (187 testes, 0 falha); `test_agent_hygiene.py` 8/8 (6 base + 2 novos).
- Frontend: `vitest` inbox 15/15 (10 novos); `tsc --noEmit` limpo; `next lint` limpo.
- `git diff --check` limpo; secret scan sem achados.
