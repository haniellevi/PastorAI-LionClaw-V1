# MVP: Fase 0 (processo) e Fase 1 (bot responde) — 2026-09-24

**Branches:** `chore/mvp-fase0-simplificacao` (PR #414) e `feat/mvp-fase1-bot-responde`
· **Deploy:** não (o proprietário faz pelo runbook)

## O que foi feito

- **Plano do MVP aprovado** (`docs/ops/MVP-PLANO-SIMPLIFICACAO.md`). Igreja
  piloto: Filadélfia.
- **Fase 0, processo mais simples:**
  - `CLAUDE.md` e `AGENTS.md` com as regras do MVP;
  - removidos 59 arquivos de teste de governança (~46 mil linhas) e 6
    workflows de CI; o snapshot fica em `archive/governanca-2026-09`;
  - checks obrigatórios da `main`: `backend-tests`, `frontend-ci`,
    `e2e-critical`, `rls-integration` e `Vercel`;
  - migrations com `backend/scripts/migrate.py`;
  - `./test-local.sh` roda os testes com as versões do CI.
- **Fase 1, o bot volta a responder:**
  - o worker roda o agente na sessão principal com RLS por igreja;
  - novas envs `WHATSAPP_PILOTO_IGREJA_IDS` (WhatsApp automático só nas
    igrejas piloto: agente, aviso de billing e SLA) e `WHATSAPP_SLA_ENABLED`
    (desligada).

## Decisões

- A sessão dedicada D2A foi pausada: ela devolvia sempre "unavailable" e
  impedia qualquer resposta.
- A lista de piloto cobre o agente, o aviso de billing e o SLA. Ligar
  `ALLOW_REAL_SENDS` sozinho mandaria cobranças de SLA acumuladas para
  líderes de todas as igrejas com WhatsApp conectado. O aviso de agenda
  (`AGENDA_NOTIFY_ENABLED`) e o broadcast agendado (`BROADCAST_ASYNC_ENABLED`)
  **não** passam pela lista; têm flags próprias, desligadas.
- O SLA por WhatsApp tem flag própria. Com ela desligada, a cobrança fica
  pendente (nada é consumido); ao ligar, o acúmulo sai de uma vez, então
  limpe a fila antes. O aviso de billing fora do piloto também fica pendente.

## Pendente / próximo passo

- Proprietário: deploy e o passo a passo da Fase 1 no plano (migration de
  reserva de resposta em PROD, agente ativo, `.env` e teste com celular).
- B3: checar a instância antes de enviar e reenviar em caso de 5xx.
- Fase 2: o LLM passa a ler a mensagem, o perfil da igreja e as últimas
  mensagens.
- Limpeza de worktrees e branches antigas.
- Reconciliar ou recriar o DEV (44 migrations pendentes).

## Verificação

- Backend `pytest -m "not rls_integration"` com Python 3.13: verde.
- Frontend com Node 24: 854/854.
- CI da Fase 0 no PR #414.
